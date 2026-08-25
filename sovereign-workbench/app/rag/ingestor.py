"""
rag/ingestor.py
===============
Document ingestion pipeline: chunk → embed → upsert → audit.

Supported file types (auto-detected by extension):
    .pdf                  → chunk_pdf  (pymupdf)
    .txt / .md / .rst     → chunk_text (stdlib)
    .py / .js / .ts / .go
    / .java / .cpp / .c   → chunk_text (treated as plain text)

Unknown extensions are also ingested as plain text with a WARNING.

Audit record
------------
Every successful ingest writes a ``RAG_INGEST`` event containing:
    source_path, collection, chunks_ingested, source_sha256, duration_ms

Sovereignty note
----------------
No network calls except via ``Embedder → OllamaClient → localhost:11434``
and ``VectorStore → Qdrant → localhost:6333``.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.audit.logger import AuditLogger, EventType
from app.rag.chunker import chunk_pdf, chunk_text
from app.rag.embedder import Embedder
from app.rag.store import VectorStore

_log = logging.getLogger("sovereign.rag.ingestor")

# File extensions treated as plain text
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".go",
    ".java", ".cpp", ".c", ".h", ".sh", ".yaml", ".yml",
    ".json", ".toml", ".ini", ".cfg", ".xml", ".html", ".css",
}


@dataclass(frozen=True)
class IngestResult:
    """Outcome of a single ingest call."""

    request_id: str
    source_path: str
    collection: str
    chunks_ingested: int
    source_sha256: str
    duration_ms: float


class Ingestor:
    """
    Document ingestion pipeline.

    Parameters
    ----------
    embedder:
        :class:`~app.rag.embedder.Embedder` backed by the bge-m3 model.
    store:
        :class:`~app.rag.store.VectorStore` pointing at local Qdrant.
    audit_logger:
        Shared :class:`~app.audit.logger.AuditLogger` instance.
    chunk_size, overlap:
        Passed through to the chunking functions.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        audit_logger: AuditLogger,
        chunk_size: int = 512,
        overlap: int = 64,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._audit = audit_logger
        self._chunk_size = chunk_size
        self._overlap = overlap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ingest(
        self,
        source_path: Path | str,
        collection: str,
        request_id: Optional[str] = None,
    ) -> IngestResult:
        """
        Ingest a document into the vector store.

        Parameters
        ----------
        source_path:
            Absolute (or cwd-relative) path to the file to ingest.
        collection:
            Target Qdrant collection name (caller-controlled namespace).
        request_id:
            Audit correlation ID.  Auto-generated if omitted.

        Returns
        -------
        :class:`IngestResult` with counts and timing.

        Raises
        ------
        FileNotFoundError  if *source_path* does not exist.
        ValueError         if the file cannot be chunked (empty result).
        RuntimeError       propagated from ``VectorStore`` on Qdrant failure.
        """
        import uuid as _uuid

        request_id = request_id or str(_uuid.uuid4())
        path = Path(source_path).expanduser().resolve()

        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")

        t0 = time.monotonic()

        # ── 1. Hash the file for audit integrity ──────────────────────
        source_sha256 = _sha256_file(path)

        # ── 2. Chunk ──────────────────────────────────────────────────
        chunks = self._chunk(path)
        if not chunks:
            raise ValueError(
                f"No text could be extracted from '{path}'.  "
                f"For scanned PDFs, use the vision pipeline instead."
            )

        # ── 3. Embed ──────────────────────────────────────────────────
        vectors = await self._embedder.embed_batch(chunks, request_id=request_id)

        # ── 4. Upsert ─────────────────────────────────────────────────
        self._store.upsert(
            collection=collection,
            chunks=chunks,
            vectors=vectors,
            source=str(path),
            extra_metadata={"source_sha256": source_sha256},
        )

        duration_ms = (time.monotonic() - t0) * 1000.0

        # ── 5. Audit log ──────────────────────────────────────────────
        self._audit.log_event(
            EventType.RAG_INGEST,
            request_id=request_id,
            payload={
                "source_path": str(path),
                "collection": collection,
                "chunks_ingested": len(chunks),
                "source_sha256": source_sha256,
                "duration_ms": round(duration_ms, 3),
            },
        )

        _log.info(
            "Ingested '%s' → collection='%s': %d chunks in %.0f ms",
            path.name,
            collection,
            len(chunks),
            duration_ms,
        )

        return IngestResult(
            request_id=request_id,
            source_path=str(path),
            collection=collection,
            chunks_ingested=len(chunks),
            source_sha256=source_sha256,
            duration_ms=round(duration_ms, 3),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chunk(self, path: Path) -> list[str]:
        """Dispatch to the correct chunker based on file extension."""
        ext = path.suffix.lower()

        if ext == ".pdf":
            try:
                return chunk_pdf(path, chunk_size=self._chunk_size, overlap=self._overlap)
            except ImportError as exc:
                _log.error("PDF chunking unavailable: %s", exc)
                raise

        if ext in _TEXT_EXTENSIONS or ext == "":
            if ext not in _TEXT_EXTENSIONS:
                _log.warning(
                    "Unknown extension '%s' for '%s' — treating as plain text", ext, path.name
                )
            text = path.read_text(encoding="utf-8", errors="replace")
            return chunk_text(text, chunk_size=self._chunk_size, overlap=self._overlap)

        # Fallback: try plain text for any unrecognised extension
        _log.warning(
            "Unrecognised extension '%s' for '%s' — attempting plain-text chunking",
            ext,
            path.name,
        )
        text = path.read_text(encoding="utf-8", errors="replace")
        return chunk_text(text, chunk_size=self._chunk_size, overlap=self._overlap)


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file (streaming, memory-safe)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()
