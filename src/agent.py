from typing import Callable

from .store import EmbeddingStore


class KnowledgeBaseAgent:
    """
    An agent that answers questions using a vector knowledge base.

    Retrieval-augmented generation (RAG) pattern:
        1. Retrieve top-k relevant chunks from the store.
        2. Build a prompt with the chunks as context.
        3. Call the LLM to generate an answer.
    """

    def __init__(self, store: EmbeddingStore, llm_fn: Callable[[str], str]) -> None:
        self.store = store
        self.llm_fn = llm_fn

    def answer(self, question: str, top_k: int = 3) -> str:
        return self._answer_from_results(question, self.store.search(question, top_k=top_k))

    def answer_with_filter(self, question: str, top_k: int = 3, metadata_filter: dict | None = None) -> str:
        """Answer using the same metadata-filtered candidates shown to the user."""
        results = self.store.search_with_filter(
            question,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )
        return self._answer_from_results(question, results)

    def _answer_from_results(self, question: str, results: list[dict]) -> str:
        if not results:
            return "Không tìm thấy thông tin phù hợp trong cơ sở tri thức."

        context_blocks = []
        for index, result in enumerate(results, start=1):
            metadata = result.get("metadata", {})
            source = metadata.get("source_url") or metadata.get("source") or metadata.get("doc_id", "unknown")
            context_blocks.append(
                f"[{index}] Source: {source}\n"
                f"Metadata: {metadata}\n"
                f"Content:\n{result['content']}"
            )

        prompt = (
            "Bạn là trợ lý trả lời câu hỏi dựa trên tài liệu được cung cấp.\n"
            "Chỉ sử dụng thông tin trong CONTEXT; nếu không đủ thông tin, hãy nói rõ "
            "không tìm thấy trong tài liệu. Khi có thể, hãy trích dẫn nguồn bằng [số].\n\n"
            f"QUESTION:\n{question}\n\n"
            "CONTEXT:\n"
            + "\n\n".join(context_blocks)
        )
        return self.llm_fn(prompt)
