"""Data ingestion helpers for the K4-L3B retrieval benchmark and UI demo."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from src.chunking import FixedSizeChunker
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


load_dotenv(override=False)


def _parse_scalar(value: str) -> str:
    """Parse the small YAML scalar subset used by lab front matter."""
    value = value.strip()
    if not value:
        return ""
    if value[0:1] in {'"', "'"} and value[-1:] == value[0]:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Return ``(metadata, body)`` for a Markdown document."""
    if not text.startswith("---"):
        return {}, text.strip()

    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}, text.strip()

    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        return {}, text.strip()

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = _parse_scalar(value)
    body = "\n".join(lines[end + 1 :]).strip()
    return metadata, body


def load_documents(data_dir: str | Path, chunker=None) -> list[Document]:
    """Load Markdown/text files and create one ``Document`` per chunk."""
    root = Path(data_dir)
    selected_chunker = chunker or FixedSizeChunker(chunk_size=500, overlap=50)
    documents: list[Document] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        metadata, body = parse_front_matter(text)
        if not body:
            continue

        doc_id = metadata.get("doc_id") or path.stem
        metadata = {
            **metadata,
            "doc_id": doc_id,
            "source": str(path),
        }
        chunks = selected_chunker.chunk(body)
        for index, content in enumerate(chunks):
            documents.append(
                Document(
                    id=f"{doc_id}#{index}",
                    content=content,
                    metadata={**metadata, "chunk_index": str(index)},
                )
            )
    return documents


def build_knowledge_base(
    data_dir: str | Path,
    embedding_fn: Callable[[str], list[float]] | None = None,
    chunker=None,
) -> EmbeddingStore:
    """Build an in-memory knowledge base from a directory of source files."""
    store = EmbeddingStore(collection_name="k4_l3b_knowledge_base", embedding_fn=embedding_fn or _mock_embed)
    store.add_documents(load_documents(data_dir, chunker=chunker))
    return store


def resolve_embedding_from_env():
    """Resolve an optional real embedder, falling back safely to the mock."""
    provider = os.getenv(EMBEDDING_PROVIDER_ENV, "mock").strip().lower()
    try:
        if provider == "local":
            return LocalEmbedder(model_name=os.getenv("LOCAL_EMBEDDING_MODEL", LOCAL_EMBEDDING_MODEL))
        if provider == "openai":
            return OpenAIEmbedder(model_name=os.getenv("OPENAI_EMBEDDING_MODEL", OPENAI_EMBEDDING_MODEL))
        if provider == "gemini":
            return GeminiEmbedder(model_name=os.getenv("GEMINI_EMBEDDING_MODEL", GEMINI_EMBEDDING_MODEL))
    except Exception:
        pass
    return _mock_embed
