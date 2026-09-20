#!/usr/bin/env python3
"""Personal measurement tool for Checkpoint 5 -- NOT graded by pytest.

Loads data/ecommerce/*.md, chunks each document's body, loads the chunks
into an EmbeddingStore, and runs the group's 5 benchmark queries through
search_with_filter() so the top-3 (score + doc_id) can be checked by hand
against each query's gold answer.

Usage:
    python bench.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DAY_DIR))

# Windows consoles often default to a non-UTF-8 codepage, which breaks
# printing Vietnamese text; force UTF-8 stdout regardless of platform.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from src.chunking import RecursiveChunker
from src.embeddings import (
    EMBEDDING_PROVIDER_ENV,
    GEMINI_EMBEDDING_MODEL,
    LOCAL_EMBEDDING_MODEL,
    OPENAI_EMBEDDING_MODEL,
    GeminiEmbedder,
    LocalEmbedder,
    OpenAIEmbedder,
    _mock_embed,
)
from src.models import Document
from src.store import EmbeddingStore

CORPUS_DIR = DAY_DIR / "data" / "ecommerce"
CACHE_PATH = DAY_DIR / ".bench_embedding_cache.json"

# --- The one line each person changes to try their own strategy ---------
CHUNKER = RecursiveChunker(chunk_size=300)  # Vu Duc Thien's personal strategy
# --------------------------------------------------------------------------

QUERIES = [
    {
        "question": "Cần làm những bước nào để gửi yêu cầu trả hàng/hoàn tiền và cần cung cấp bằng chứng gì?",
        "metadata_filter": {"audience": "buyer"},
    },
    {
        "question": "Những hành vi gian lận trên sàn có thể bị xử lý như thế nào?",
        "metadata_filter": {"audience": "seller"},
    },
    {
        "question": "Khi trả hàng, trường hợp nào được miễn phí và trường hợp nào được hoàn phí dưới dạng Shopee Xu?",
        "metadata_filter": None,
    },
    {
        "question": "Đối với Shopee Mall, thời hạn yêu cầu trả hàng/hoàn tiền và thời hạn gửi hàng sau khi được chấp nhận là bao lâu?",
        "metadata_filter": None,
    },
    {
        "question": "Quy trình Shopee giải quyết tranh chấp/khiếu nại gồm những bước nào và thời hạn xử lý là bao lâu?",
        "metadata_filter": None,
    },
]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a `---\\nkey: value\\n---\\nbody` file into (metadata, body)."""
    _, fm_block, body = text.split("---", 2)
    metadata = dict(re.findall(r"^(\w+):\s*(.+)$", fm_block, re.M))
    for key, value in metadata.items():
        metadata[key] = value.strip().strip('"')
    return metadata, body.strip()


def load_chunked_documents() -> list[Document]:
    """1) parse frontmatter, 2) chunk the body OUTSIDE the store, one
    Document per chunk -- loading a whole file as a single Document (like
    main.py's demo does) would make retrieval just return entire files."""
    documents: list[Document] = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        for i, chunk_text in enumerate(CHUNKER.chunk(body)):
            documents.append(
                Document(
                    id=f"{path.stem}#{i}",
                    content=chunk_text,
                    # doc_id must point at the source file, not the chunk id,
                    # and frontmatter has to be spread onto every chunk or
                    # search_with_filter() has nothing to filter on.
                    metadata={**frontmatter, "doc_id": path.stem, "chunk_index": i},
                )
            )
    return documents


class CachingEmbedder:
    """Wraps any embedder with a content-hash -> vector cache on disk, so
    re-running the script (e.g. after a rate-limit crash) doesn't re-pay for
    or re-throttle on chunks already embedded."""

    def __init__(self, embedder, cache_path: Path) -> None:
        self._embedder = embedder
        self._cache_path = cache_path
        self._backend_name = getattr(embedder, "_backend_name", "embedder")
        try:
            self._cache: dict[str, list[float]] = json.loads(cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self._cache = {}
        self._dirty = False
        self._since_flush = 0

    def _key(self, text: str) -> str:
        return f"{self._backend_name}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def __call__(self, text: str) -> list[float]:
        key = self._key(text)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        vector = self._embedder(text)
        self._cache[key] = vector
        self._dirty = True
        self._since_flush += 1
        # Flush periodically (not just at the end) so a mid-run crash --
        # e.g. hitting the daily free-tier quota -- doesn't throw away
        # every embedding already paid for in this run.
        if self._since_flush >= 10:
            self.flush()
        return vector

    def flush(self) -> None:
        if self._dirty:
            self._cache_path.write_text(json.dumps(self._cache), encoding="utf-8")
            self._dirty = False
            self._since_flush = 0


def rate_limited(embedder, min_interval: float = 0.7, max_retries: int = 6):
    """Pace calls + retry-with-backoff on 429s (free-tier embedding APIs
    like Gemini's 100 requests/min will otherwise crash mid-corpus)."""
    last_call = [0.0]

    def wrapped(text: str) -> list[float]:
        elapsed = time.monotonic() - last_call[0]
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        last_call[0] = time.monotonic()

        delay = 2.0
        for attempt in range(max_retries):
            try:
                return embedder(text)
            except Exception as error:
                is_rate_limit = "429" in str(error) or "RESOURCE_EXHAUSTED" in str(error)
                if not is_rate_limit or attempt == max_retries - 1:
                    raise
                print(f"[warn] rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(delay)
                delay = min(delay * 2, 30.0)

    wrapped._backend_name = getattr(embedder, "_backend_name", "unknown")
    return wrapped


def pick_embedder():
    load_dotenv(override=False)
    provider = os.getenv(EMBEDDING_PROVIDER_ENV, "mock").strip().lower()
    try:
        if provider == "local":
            return LocalEmbedder(model_name=os.getenv("LOCAL_EMBEDDING_MODEL", LOCAL_EMBEDDING_MODEL))
        if provider == "openai":
            return rate_limited(OpenAIEmbedder(model_name=os.getenv("OPENAI_EMBEDDING_MODEL", OPENAI_EMBEDDING_MODEL)))
        if provider == "gemini":
            return rate_limited(GeminiEmbedder(model_name=os.getenv("GEMINI_EMBEDDING_MODEL", GEMINI_EMBEDDING_MODEL)))
    except Exception as error:  # pragma: no cover - environment dependent
        print(f"[warn] could not init '{provider}' embedder ({error}); falling back to mock.")
    return _mock_embed


def main() -> int:
    raw_embedder = pick_embedder()
    backend_name = getattr(raw_embedder, "_backend_name", "mock embeddings fallback")
    print(f"Embedding backend: {backend_name}")
    if backend_name == "mock embeddings fallback":
        print(
            "[warn] MockEmbedder khong co ngu nghia that -- diem so/relevance duoi day "
            "chi de kiem tra pipeline chay duoc, khong dung de dien REPORT_CANHAN muc 5."
        )

    embedder = CachingEmbedder(raw_embedder, CACHE_PATH)

    docs = load_chunked_documents()
    n_source_docs = len(list(CORPUS_DIR.glob("*.md")))
    print(f"Chunker: {CHUNKER.__class__.__name__}(chunk_size={getattr(CHUNKER, 'chunk_size', '?')})")

    store = EmbeddingStore(collection_name="bench", embedding_fn=embedder)
    store.add_documents(docs)
    embedder.flush()

    print(f"Loaded {store.get_collection_size()} chunks from {n_source_docs} documents\n")

    for i, q in enumerate(QUERIES, start=1):
        print(f"=== Query {i}: {q['question']} ===")
        if q["metadata_filter"]:
            print(f"metadata_filter={q['metadata_filter']}")
        results = store.search_with_filter(q["question"], top_k=3, metadata_filter=q["metadata_filter"])
        for rank, r in enumerate(results, start=1):
            preview = r["content"][:150].replace("\n", " ")
            print(f"  top-{rank} score={r['score']:.3f} doc_id={r['metadata'].get('doc_id')} :: {preview}...")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
