#!/usr/bin/env python3
"""
scripts/ingest_corpus.py
========================
Bulk-ingest the full knowledge_base/ corpus into the embedded Qdrant
``sovereign_knowledge_base`` collection.

Usage
-----
    cd sovereign-workbench
    source .venv/bin/activate
    python scripts/ingest_corpus.py [--collection sovereign_knowledge_base] [--dry-run]

Design
------
* Uses the same embedded Qdrant storage path (``qdrant_storage/``) that
  ``app/main.py`` uses, so data written here is immediately available to
  the running server.
* Ingests all PDF files found in the three corpus sub-folders.
* Re-running is safe: Qdrant upsert, not insert — duplicate chunks are
  updated, not added twice.
* Skips files that yield zero text (scanned-only PDFs) and reports them
  so you know which files need the OCR path.

Audit
-----
One ``RAG_INGEST`` record is written per ingested document.  Run this
before the live demo so the audit trail reflects real data, not smoke-test
data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# ── Make sure the project root is on sys.path ──────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
_log = logging.getLogger("ingest_corpus")

# ── Corpus configuration ───────────────────────────────────────────────────
_KB_ROOT = _PROJECT_ROOT / "knowledge_base"
_QDRANT_STORAGE = _PROJECT_ROOT / "qdrant_storage"
_DEFAULT_COLLECTION = "sovereign_knowledge_base"

# Subfolders to ingest (folder name becomes source_category in metadata)
_CORPUS_DIRS = [
    _KB_ROOT / "mrpl_public",
    _KB_ROOT / "oisd_standards",
    _KB_ROOT / "synthetic_demo",
]

_PDF_EXTENSIONS = {".pdf"}
_TEXT_EXTENSIONS = {".txt", ".md"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_files(dirs: list[Path]) -> list[tuple[Path, str]]:
    """
    Walk each directory and return (file_path, source_category) pairs
    for all ingestable files.
    """
    files: list[tuple[Path, str]] = []
    for d in dirs:
        if not d.exists():
            _log.warning("Corpus directory not found, skipping: %s", d)
            continue
        category = d.name  # mrpl_public | oisd_standards | synthetic_demo
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in (_PDF_EXTENSIONS | _TEXT_EXTENSIONS):
                files.append((p, category))
    return files


async def _ingest_pdf(
    file_path: Path,
    source_category: str,
    collection: str,
    ingestor,
    request_id: str,
) -> dict:
    """Ingest a single PDF file.  Returns a result dict."""
    t0 = time.monotonic()
    try:
        result = await ingestor.ingest_document(
            pdf_path=file_path,
            source_category=source_category,
            collection=collection,
            request_id=request_id,
        )
        duration_ms = (time.monotonic() - t0) * 1000
        # result.skipped is True for scanned/image-only PDFs with zero text
        if getattr(result, "skipped", False):
            status_str = "zero_text_skipped"
        else:
            status_str = "ok" if result.chunks_ingested > 0 else "zero_text_skipped"
        return {
            "file": file_path.name,
            "category": source_category,
            "chunks": result.chunks_ingested,
            "sha256": result.source_sha256[:12] + "…" if result.source_sha256 else "",
            "duration_ms": round(duration_ms, 0),
            "status": status_str,
        }
    except Exception as exc:
        duration_ms = (time.monotonic() - t0) * 1000
        _log.error("FAILED to ingest %s: %s", file_path.name, exc)
        return {
            "file": file_path.name,
            "category": source_category,
            "chunks": 0,
            "sha256": "",
            "duration_ms": round(duration_ms, 0),
            "status": f"error: {exc}",
        }


async def _ingest_text(
    file_path: Path,
    source_category: str,
    collection: str,
    single_ingestor,
    request_id: str,
) -> dict:
    """Ingest a single text/markdown file via the single-file ingestor."""
    t0 = time.monotonic()
    try:
        result = await single_ingestor.ingest(
            source_path=str(file_path),
            collection=collection,
            request_id=request_id,
        )
        duration_ms = (time.monotonic() - t0) * 1000
        return {
            "file": file_path.name,
            "category": source_category,
            "chunks": result.chunks_ingested,
            "sha256": result.source_sha256[:12] + "…",
            "duration_ms": round(duration_ms, 0),
            "status": "ok",
        }
    except Exception as exc:
        duration_ms = (time.monotonic() - t0) * 1000
        _log.error("FAILED to ingest %s: %s", file_path.name, exc)
        return {
            "file": file_path.name,
            "category": source_category,
            "chunks": 0,
            "sha256": "",
            "duration_ms": round(duration_ms, 0),
            "status": f"error: {exc}",
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(collection: str, dry_run: bool) -> int:
    """Entry point.  Returns exit code (0 = success, 1 = any errors)."""
    _log.info("=" * 60)
    _log.info("Sovereign Workbench — Corpus Ingestor")
    _log.info("Collection : %s", collection)
    _log.info("Storage    : %s", _QDRANT_STORAGE)
    _log.info("Corpus root: %s", _KB_ROOT)
    _log.info("Dry run    : %s", dry_run)
    _log.info("=" * 60)

    # ── Collect files ──────────────────────────────────────────────────
    files = _collect_files(_CORPUS_DIRS)
    if not files:
        _log.error("No ingestable files found under %s", _KB_ROOT)
        return 1
    _log.info("Found %d files to ingest:", len(files))
    for fp, cat in files:
        size_kb = fp.stat().st_size // 1024
        _log.info("  [%s] %s (%d KB)", cat, fp.name, size_kb)

    if dry_run:
        _log.info("Dry run complete — no data written.")
        return 0

    # ── Bootstrap Qdrant + embedding ──────────────────────────────────
    _log.info("Initialising embedded Qdrant at %s …", _QDRANT_STORAGE)
    _QDRANT_STORAGE.mkdir(parents=True, exist_ok=True)

    try:
        from app.audit.logger import AuditLogger
        from app.models.ollama_client import OllamaClient
        from app.rag.embedder import Embedder
        from app.rag.ingest import KnowledgeBaseIngestor
        from app.rag.ingestor import Ingestor
        from app.rag.store import VectorStore
    except ImportError as exc:
        _log.error(
            "Import failed: %s\n"
            "Make sure the virtualenv is active and all deps are installed:\n"
            "  pip install -r requirements.txt",
            exc,
        )
        return 1

    audit = AuditLogger()
    embedding_client = OllamaClient(model_name="bge_m3", audit_logger=audit)
    vector_store = VectorStore(storage_path=_QDRANT_STORAGE)
    embedder = Embedder(embedding_client)

    # PDF ingestor (page-level chunking, source_category metadata)
    pdf_ingestor = KnowledgeBaseIngestor(
        embedder=embedder,
        store=vector_store,
        audit_logger=audit,
    )
    # Single-file ingestor for .txt / .md files (synthetic_demo)
    text_ingestor = Ingestor(
        embedder=embedder,
        store=vector_store,
        audit_logger=audit,
    )

    # ── Ingest each file ───────────────────────────────────────────────
    results = []
    total_t0 = time.monotonic()

    for idx, (file_path, source_category) in enumerate(files, start=1):
        request_id = f"corpus-ingest-{idx:03d}"
        _log.info("[%d/%d] Ingesting: %s …", idx, len(files), file_path.name)

        suffix = file_path.suffix.lower()
        if suffix in _PDF_EXTENSIONS:
            result = await _ingest_pdf(
                file_path, source_category, collection, pdf_ingestor, request_id
            )
        else:
            result = await _ingest_text(
                file_path, source_category, collection, text_ingestor, request_id
            )

        results.append(result)
        status_icon = (
            "OK  "
            if result["status"] == "ok"
            else ("SKIP" if "zero_text" in result["status"] else "FAIL")
        )
        _log.info(
            "  [%s] %s — %d chunks in %.0f ms",
            status_icon, result["file"], result["chunks"], result["duration_ms"],
        )

    total_elapsed = time.monotonic() - total_t0

    # ── Summary ────────────────────────────────────────────────────────
    ok = [r for r in results if r["status"] == "ok"]
    zero_text = [r for r in results if "zero_text" in r["status"]]
    errors = [r for r in results if r["status"] not in ("ok",) and "zero_text" not in r["status"]]
    total_chunks = sum(r["chunks"] for r in ok)

    _log.info("")
    _log.info("=" * 60)
    _log.info("INGEST SUMMARY")
    _log.info("  Collection    : %s", collection)
    _log.info("  Files OK      : %d / %d", len(ok), len(files))
    _log.info("  Total chunks  : %d", total_chunks)
    _log.info("  Zero-text PDFs: %d (need OCR path for these)", len(zero_text))
    _log.info("  Errors        : %d", len(errors))
    _log.info("  Elapsed       : %.1f s", total_elapsed)
    _log.info("=" * 60)

    if zero_text:
        _log.warning("Zero-text (scanned-only) PDFs — not searchable via text RAG:")
        for r in zero_text:
            _log.warning("  %s [%s]", r["file"], r["category"])

    if errors:
        _log.error("Errors — these files were NOT ingested:")
        for r in errors:
            _log.error("  %s: %s", r["file"], r["status"])
        return 1

    _log.info("Corpus ingestion complete.")
    _log.info("Next step: python scripts/verify_corpus_retrieval.py")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bulk-ingest knowledge_base/ corpus into embedded Qdrant.",
    )
    parser.add_argument(
        "--collection",
        default=_DEFAULT_COLLECTION,
        help="Qdrant collection name (default: sovereign_knowledge_base)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be ingested without writing anything.",
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(main(collection=args.collection, dry_run=args.dry_run)))
