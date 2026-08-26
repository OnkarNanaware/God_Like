"""
rag/ingest.py
=============
Folder-level knowledge-base ingestion pipeline for the Sovereign Workbench.

This module is the Phase C entry point for bulk ingestion.  It wraps the
lower-level :class:`~app.rag.chunker` / :class:`~app.rag.embedder` /
:class:`~app.rag.store` pieces into a pipeline that understands the
``knowledge_base/`` folder structure:

    knowledge_base/
    ├── mrpl_public/          ← source_category = "mrpl_public"
    │   ├── annual_report.pdf
    │   └── environment_report.pdf
    └── oisd_standards/       ← source_category = "oisd_standards"
        └── OISD_Standards_Detailed_Explanation_Guide_SIH26117.pdf

Design choices
--------------
* **Folder-derived categories** — ``source_category`` is the parent folder name.
  Adding a new category requires only a new subfolder, zero code changes.
* **Deterministic point IDs** — ``sha256(doc_name|page|chunk_idx)[:16]`` as
  UUID.  Re-running ingestion calls Qdrant upsert, which updates existing
  points rather than duplicating them.  Critical for the OISD document which
  will be re-ingested as it is expanded.
* **Zero-text PDFs are skipped, not failed** — a PDF that yields zero
  extractable text logs a ``WARNING`` and is noted in the batch result.  This
  is the signal for the Phase D OCR routing path.
* **Page-by-page chunking** — ``chunk_pdf_paged()`` is used so every chunk
  carries the correct ``page_number`` for downstream citation.
* **Metadata schema** (per chunk payload):
    - ``text``              — chunk text content
    - ``doc_name``          — PDF basename (e.g. "environment_report.pdf")
    - ``source_category``   — derived from parent folder name
    - ``page_number``       — 1-indexed PDF page number
    - ``chunk_index``       — global chunk index within the document
    - ``edition_date``      — null (unknown for current corpus; field exists
                               so it can be populated without schema migration)
    - ``status``            — "in_force" | "withdrawn"  (default "in_force")
    - ``confidentiality``   — "public" | "internal" | "confidential"
                               (default "public"; enforced now for future use)
    - ``source``            — absolute file path

Audit logging
-------------
One ``RAG_INGEST`` event is written per document (not per chunk):
    doc_name, source_category, collection, chunks_ingested, source_sha256

Sovereignty note
----------------
No network calls except:
  - Embedder → OllamaClient → localhost:11434
  - VectorStore → Qdrant → localhost:6333
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.audit.logger import AuditLogger, EventType
from app.rag.chunker import chunk_pdf_paged
from app.rag.embedder import Embedder
from app.rag.store import VectorStore, make_chunk_id

_log = logging.getLogger("sovereign.rag.ingest")

# Only PDF ingestion is supported in this module.
# Text/code ingestion remains in app.rag.ingestor (single-file).
_SUPPORTED_EXTENSIONS = {".pdf"}

# Default chunk parameters — tuned for bge-m3 (~600 chars ≈ ~150 tokens at
# typical English density, well within bge-m3's 8192 token maximum).
_DEFAULT_CHUNK_SIZE = 600
_DEFAULT_OVERLAP = 90


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DocumentIngestResult:
    """Outcome of ingesting a single document."""

    doc_name: str
    source_category: str
    collection: str
    chunks_ingested: int
    source_sha256: str
    duration_ms: float
    skipped: bool = False          # True when zero text was extracted
    skip_reason: Optional[str] = None


@dataclass
class BatchIngestResult:
    """Aggregated outcome of a full folder-level ingestion run."""

    collection: str
    total_documents: int
    total_chunks: int
    skipped_documents: int
    failed_documents: int
    results: list[DocumentIngestResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# KnowledgeBaseIngestor
# ---------------------------------------------------------------------------


class KnowledgeBaseIngestor:
    """
    Folder-aware ingestion pipeline that walks ``knowledge_base/`` and ingests
    every PDF it finds into Qdrant, tagging each chunk with its
    ``source_category`` (derived from the parent folder name).

    Parameters
    ----------
    embedder:
        :class:`~app.rag.embedder.Embedder` backed by the bge-m3 model.
    store:
        :class:`~app.rag.store.VectorStore` pointing at local Qdrant.
    audit_logger:
        Shared :class:`~app.audit.logger.AuditLogger` instance.
    chunk_size, overlap:
        Character-level chunking parameters.  Defaults are tuned for bge-m3.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        audit_logger: AuditLogger,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        overlap: int = _DEFAULT_OVERLAP,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._audit = audit_logger
        self._chunk_size = chunk_size
        self._overlap = overlap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ingest_folder(
        self,
        kb_root: Path | str,
        collection: str,
        request_id: Optional[str] = None,
    ) -> BatchIngestResult:
        """
        Walk ``kb_root``, ingest every PDF in every immediate subfolder.

        Folder structure rule
        ----------------------
        Only **immediate** children of ``kb_root`` are treated as categories.
        Files directly in ``kb_root`` (not in a subfolder) are skipped with
        a WARNING.

        Parameters
        ----------
        kb_root:
            Path to the root knowledge-base directory.
        collection:
            Target Qdrant collection name for all documents in this run.
        request_id:
            Audit correlation ID.  Auto-generated if omitted.

        Returns
        -------
        :class:`BatchIngestResult` with per-document outcomes.
        """
        request_id = request_id or str(_uuid.uuid4())
        root = Path(kb_root).expanduser().resolve()

        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Knowledge-base root not found: {root}")

        _log.info("Starting batch ingest from '%s' → collection='%s'", root, collection)

        batch = BatchIngestResult(collection=collection, total_documents=0, total_chunks=0,
                                  skipped_documents=0, failed_documents=0)

        # Walk immediate subfolders — each is a source_category
        for category_dir in sorted(root.iterdir()):
            if not category_dir.is_dir():
                _log.warning(
                    "Skipping top-level file '%s' — put documents in category subfolders",
                    category_dir.name,
                )
                continue

            source_category = category_dir.name
            pdf_files = sorted(
                p for p in category_dir.iterdir()
                if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
            )

            if not pdf_files:
                _log.warning("Category folder '%s' contains no PDFs — skipping", source_category)
                continue

            _log.info(
                "Category '%s': found %d PDF(s)", source_category, len(pdf_files)
            )

            for pdf_path in pdf_files:
                batch.total_documents += 1
                try:
                    doc_result = await self.ingest_document(
                        pdf_path=pdf_path,
                        source_category=source_category,
                        collection=collection,
                        request_id=request_id,
                    )
                    batch.results.append(doc_result)
                    if doc_result.skipped:
                        batch.skipped_documents += 1
                        _log.warning(
                            "SKIPPED '%s' [%s]: %s",
                            doc_result.doc_name,
                            source_category,
                            doc_result.skip_reason,
                        )
                    else:
                        batch.total_chunks += doc_result.chunks_ingested
                        _log.info(
                            "OK '%s' [%s]: %d chunks",
                            doc_result.doc_name,
                            source_category,
                            doc_result.chunks_ingested,
                        )
                except Exception as exc:  # noqa: BLE001
                    batch.failed_documents += 1
                    err_msg = f"FAILED '{pdf_path.name}' [{source_category}]: {exc}"
                    batch.errors.append(err_msg)
                    _log.error(err_msg)

        _log.info(
            "Batch ingest done: %d docs, %d chunks, %d skipped, %d failed",
            batch.total_documents,
            batch.total_chunks,
            batch.skipped_documents,
            batch.failed_documents,
        )
        return batch

    async def ingest_document(
        self,
        pdf_path: Path | str,
        source_category: str,
        collection: str,
        request_id: Optional[str] = None,
        *,
        status: str = "in_force",
        confidentiality: str = "public",
        edition_date: Optional[str] = None,
    ) -> DocumentIngestResult:
        """
        Ingest a single PDF into Qdrant with full metadata.

        Parameters
        ----------
        pdf_path:
            Absolute path to the PDF file.
        source_category:
            Category tag derived from parent folder name.
        collection:
            Target Qdrant collection.
        request_id:
            Audit correlation ID.
        status:
            "in_force" or "withdrawn".  Default "in_force".
        confidentiality:
            "public", "internal", or "confidential".  Default "public".
        edition_date:
            ISO-8601 date string or None.  Currently null for all documents in
            the corpus; field exists so it can be populated without migration.

        Returns
        -------
        :class:`DocumentIngestResult` — includes ``skipped=True`` when the PDF
        yields zero extractable text (scanned/image-only).
        """
        request_id = request_id or str(_uuid.uuid4())
        path = Path(pdf_path).expanduser().resolve()

        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")

        doc_name = path.name
        t0 = time.monotonic()

        # ── 1. Hash the file for audit integrity ──────────────────────
        source_sha256 = _sha256_file(path)

        # ── 2. Chunk page-by-page ─────────────────────────────────────
        paged_chunks: list[tuple[str, int, int]] = chunk_pdf_paged(
            path, chunk_size=self._chunk_size, overlap=self._overlap
        )

        if not paged_chunks:
            # Zero text extracted — signal for OCR routing (Phase D)
            _log.warning(
                "ZERO_TEXT_PDF doc='%s' category='%s' — "
                "no extractable text; skipping (Phase D OCR routing required)",
                doc_name,
                source_category,
            )
            return DocumentIngestResult(
                doc_name=doc_name,
                source_category=source_category,
                collection=collection,
                chunks_ingested=0,
                source_sha256=source_sha256,
                duration_ms=round((time.monotonic() - t0) * 1000.0, 3),
                skipped=True,
                skip_reason="zero extractable text (scanned/image-only PDF)",
            )

        # ── 3. Build payload dicts with full metadata ─────────────────
        texts = [text for text, _page, _idx in paged_chunks]

        # ── 4. Embed ──────────────────────────────────────────────────
        vectors = await self._embedder.embed_batch(texts, request_id=request_id)

        # ── 5. Build Qdrant point dicts with deterministic IDs ────────
        global_chunk_index = 0
        qdrant_points: list[dict] = []

        for (text, page_number, chunk_idx_on_page), vector in zip(paged_chunks, vectors):
            point_id = make_chunk_id(doc_name, page_number, global_chunk_index)
            payload = {
                "text": text,
                "source": str(path),
                "doc_name": doc_name,
                "source_category": source_category,
                "page_number": page_number,
                "chunk_index": global_chunk_index,
                "chunk_index_on_page": chunk_idx_on_page,
                "edition_date": edition_date,
                "status": status,
                "confidentiality": confidentiality,
                "source_sha256": source_sha256,
            }
            qdrant_points.append({"id": point_id, "vector": vector, "payload": payload})
            global_chunk_index += 1

        # ── 6. Upsert (deterministic IDs → updates, not duplicates) ───
        self._store.upsert_points(collection=collection, points=qdrant_points)

        duration_ms = round((time.monotonic() - t0) * 1000.0, 3)

        # ── 7. Audit log ──────────────────────────────────────────────
        self._audit.log_event(
            EventType.RAG_INGEST,
            request_id=request_id,
            payload={
                "doc_name": doc_name,
                "source_category": source_category,
                "collection": collection,
                "chunks_ingested": len(paged_chunks),
                "source_sha256": source_sha256,
                "duration_ms": duration_ms,
                "status": status,
                "confidentiality": confidentiality,
            },
        )

        _log.info(
            "Ingested '%s' [%s] → collection='%s': %d chunks in %.0f ms",
            doc_name,
            source_category,
            collection,
            len(paged_chunks),
            duration_ms,
        )

        return DocumentIngestResult(
            doc_name=doc_name,
            source_category=source_category,
            collection=collection,
            chunks_ingested=len(paged_chunks),
            source_sha256=source_sha256,
            duration_ms=duration_ms,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file (streaming, memory-safe)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# __main__ — run ingestion from CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import os
    from pathlib import Path

    # Locate knowledge_base relative to this file's project root
    _THIS_DIR = Path(__file__).resolve().parent           # app/rag/
    _PROJECT_ROOT = _THIS_DIR.parent.parent               # sovereign-workbench/
    _KB_ROOT = _PROJECT_ROOT / "knowledge_base"
    _COLLECTION = os.environ.get("RAG_COLLECTION", "docs")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stdout,
    )

    async def _main() -> None:
        from app.audit.logger import AuditLogger
        from app.models.ollama_client import OllamaClient, MODEL_REGISTRY
        from app.rag.embedder import Embedder
        from app.rag.store import VectorStore

        _log.info("Connecting to Qdrant and Ollama...")
        store = VectorStore()
        audit = AuditLogger()

        # Use bge-m3 for embeddings (same model as retrieval — must not drift)
        embedding_model_key = "bge_m3"
        if embedding_model_key not in MODEL_REGISTRY:
            raise RuntimeError(
                f"'{embedding_model_key}' not found in MODEL_REGISTRY. "
                "Check app/models/ollama_client.py."
            )
        ollama_tag = MODEL_REGISTRY[embedding_model_key]["ollama_tag"]
        ollama_client = OllamaClient(model_name=embedding_model_key, ollama_tag=ollama_tag)
        embedder = Embedder(ollama_client)

        kb_ingestor = KnowledgeBaseIngestor(
            embedder=embedder,
            store=store,
            audit_logger=audit,
        )

        _log.info("Starting ingestion from '%s' → collection='%s'", _KB_ROOT, _COLLECTION)
        result = await kb_ingestor.ingest_folder(kb_root=_KB_ROOT, collection=_COLLECTION)

        print("\n" + "=" * 60)
        print(f"  Ingestion complete — collection: {result.collection}")
        print(f"  Documents processed : {result.total_documents}")
        print(f"  Chunks ingested     : {result.total_chunks}")
        print(f"  Documents skipped   : {result.skipped_documents} (zero-text / scanned)")
        print(f"  Documents failed    : {result.failed_documents}")
        print("=" * 60)

        if result.errors:
            print("\nErrors:")
            for e in result.errors:
                print(f"  ✗ {e}")

        for r in result.results:
            status_icon = "⚠" if r.skipped else "✓"
            skip_note = f" [{r.skip_reason}]" if r.skipped else ""
            print(
                f"  {status_icon} [{r.source_category}] {r.doc_name}: "
                f"{r.chunks_ingested} chunks{skip_note}"
            )

    asyncio.run(_main())
