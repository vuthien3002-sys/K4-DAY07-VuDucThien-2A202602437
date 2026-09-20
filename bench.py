"""Run the five-query K4-L3B retrieval benchmark.

The benchmark deliberately keeps the query set in code so it is easy to review
and copy into REPORT_NHOM.md.  Replace or extend it with the group's final
questions when the corpus is finalized.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from ingest import build_knowledge_base, load_documents, resolve_embedding_from_env
from src.chunking import FixedSizeChunker, RecursiveChunker, SentenceChunker


DEFAULT_QUERIES = [
    {
        "id": "Q1",
        "question": "Trong bao lâu người mua có thể yêu cầu trả hàng hoặc hoàn tiền?",
        "audience": "buyer",
        "gold_doc": "buyer-return-window",
        "gold_terms": ["15 ngày"],
    },
    {
        "id": "Q2",
        "question": "Người bán phải phản hồi yêu cầu trả hàng trong bao lâu?",
        "audience": "seller",
        "gold_doc": "seller-return-response",
        "gold_terms": ["02 ngày lịch"],
    },
    {
        "id": "Q3",
        "question": "Nếu yêu cầu được chấp nhận thì tiền hoàn thường được chuyển trong bao lâu?",
        "audience": "buyer",
        "gold_doc": "refund-request-process",
        "gold_terms": ["1–14 ngày làm việc"],
    },
    {
        "id": "Q4",
        "question": "Các điều kiện cơ bản để được bảo hành là gì?",
        "audience": "buyer",
        "gold_doc": "warranty-conditions",
        "gold_terms": ["còn thời hạn bảo hành", "tem hoặc phiếu bảo hành"],
    },
    {
        "id": "Q5",
        "question": "Trong một số trường hợp, ai chịu chi phí vận chuyển chiều hoàn trả?",
        "audience": "seller",
        "gold_doc": "return-shipping-costs",
        "gold_terms": ["Người bán chịu chi phí"],
    },
]


class HeadingChunker:
    """Keep Markdown section headings attached to their section content."""

    _heading_pattern = re.compile(r"(?m)^(#{1,6}\s+.+?)\s*$")

    def __init__(self, chunk_size: int = 320) -> None:
        self.chunk_size = max(1, chunk_size)

    def chunk(self, text: str) -> list[str]:
        matches = list(self._heading_pattern.finditer(text))
        if not matches:
            return RecursiveChunker(chunk_size=self.chunk_size).chunk(text)

        sections: list[str] = []
        prefix = text[: matches[0].start()].strip()
        if prefix:
            sections.append(prefix)
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            section = text[match.start() : end].strip()
            if section:
                sections.append(section)

        chunks: list[str] = []
        for section in sections:
            if len(section) <= self.chunk_size:
                chunks.append(section)
                continue
            heading = section.splitlines()[0].strip()
            body = section[len(section.splitlines()[0]) :].strip()
            for part in RecursiveChunker(chunk_size=max(1, self.chunk_size - len(heading) - 1)).chunk(body):
                chunks.append(f"{heading}\n{part}")
        return chunks


def make_chunker(strategy: str):
    if strategy == "fixed":
        return FixedSizeChunker(chunk_size=320, overlap=48)
    if strategy == "sentence":
        return SentenceChunker(max_sentences_per_chunk=2)
    if strategy == "recursive":
        return RecursiveChunker(chunk_size=320)
    if strategy == "heading":
        return HeadingChunker(chunk_size=320)
    raise ValueError(f"Unknown strategy: {strategy}")


def run_query(store, query: dict, top_k: int = 3) -> dict:
    results = store.search_with_filter(
        query["question"],
        top_k=top_k,
        metadata_filter={"audience": query["audience"]},
    )
    relevant = [
        result
        for result in results
        if result["metadata"].get("doc_id") == query["gold_doc"]
        and any(term.lower() in result["content"].lower() for term in query["gold_terms"])
    ]
    return {
        "id": query["id"],
        "question": query["question"],
        "metadata_filter": {"audience": query["audience"]},
        "gold_doc": query["gold_doc"],
        "results": results,
        "gold_in_top3": bool(relevant),
        "gold_rank": next(
            (index for index, result in enumerate(results, start=1) if result in relevant),
            None,
        ),
    }


def run_benchmark(data_dir: str | Path, strategy: str) -> dict:
    embedding = resolve_embedding_from_env()
    store = build_knowledge_base(data_dir, embedding_fn=embedding, chunker=make_chunker(strategy))
    return {
        "strategy": strategy,
        "embedding_backend": getattr(embedding, "_backend_name", "mock"),
        "chunk_count": store.get_collection_size(),
        "queries": [run_query(store, query) for query in DEFAULT_QUERIES],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the K4-L3B retrieval benchmark")
    parser.add_argument("--data-dir", default="data/ecommerce/shopee")
    parser.add_argument("--strategy", choices=["fixed", "sentence", "recursive", "heading"], default="sentence")
    parser.add_argument("--all-strategies", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    strategies = ["fixed", "sentence", "recursive", "heading"] if args.all_strategies else [args.strategy]
    reports = [run_benchmark(args.data_dir, strategy) for strategy in strategies]

    if args.as_json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return 0

    for report in reports:
        hits = sum(query["gold_in_top3"] for query in report["queries"])
        print(f"=== Strategy: {report['strategy']} ===")
        print(f"Embedding: {report['embedding_backend']}")
        print(f"Stored chunks: {report['chunk_count']}")
        print(f"Top-3 content hits: {hits}/{len(report['queries'])}")
        for query in report["queries"]:
            print(f"{query['id']} | rank={query['gold_rank'] or '-'} | {query['question']}")
            for index, result in enumerate(query["results"], start=1):
                print(
                    f"  {index}. score={result['score']:.3f} "
                    f"doc={result['metadata'].get('doc_id')} "
                    f"chunk={result['metadata'].get('chunk_index')}"
                )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
