"""
rag/chunker.py
==============
Text and PDF chunking utilities for the RAG ingestion pipeline.

All functions are pure Python / stdlib-only *except* ``chunk_pdf`` which
optionally uses ``pymupdf`` (fitz).  If ``pymupdf`` is not installed,
``chunk_pdf`` raises an ``ImportError`` with a clear install instruction.

Design
------
* Sliding-window character chunker: deterministic, no ML deps.
* Chunk size and overlap are configurable per call.
* Text shorter than *chunk_size* is returned as a single chunk.
* PDF chunking: text is extracted page-by-page, then passed through
  ``chunk_text``.  Scanned-only pages (zero extracted chars) are skipped
  with a warning.

Sovereignty note
----------------
No network calls.  No external API.
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger("sovereign.rag.chunker")

# Sensible defaults tuned for bge-m3 (max 8 192 tokens ≈ ~6 000 chars).
_DEFAULT_CHUNK_SIZE = 512   # characters
_DEFAULT_OVERLAP = 64       # characters — shared context between windows


def chunk_text(
    text: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    overlap: int = _DEFAULT_OVERLAP,
) -> list[str]:
    """
    Split *text* into overlapping windows of *chunk_size* characters.

    Parameters
    ----------
    text:
        Raw text to chunk.  Leading/trailing whitespace is stripped before
        splitting.
    chunk_size:
        Target character count per chunk.
    overlap:
        Number of characters shared between consecutive chunks.

    Returns
    -------
    A list of non-empty string chunks.  Returns ``[""]`` only if *text* is
    empty so callers can always iterate without a guard.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be > 0, got {chunk_size}")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError(
            f"overlap must be in [0, chunk_size), got overlap={overlap} chunk_size={chunk_size}"
        )

    text = text.strip()
    if not text:
        return []

    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += step

    return chunks


def chunk_pdf(
    path: Path | str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    overlap: int = _DEFAULT_OVERLAP,
) -> list[str]:
    """
    Extract text from a PDF and return overlapping chunks.

    Requires ``pymupdf`` (``pip install pymupdf``).  Pages with no
    extractable text (scanned images without OCR) are skipped.

    Parameters
    ----------
    path:
        Absolute or relative path to the PDF file.
    chunk_size, overlap:
        Passed through to :func:`chunk_text`.

    Returns
    -------
    List of text chunks from the entire PDF.

    Raises
    ------
    ImportError        if pymupdf is not installed.
    FileNotFoundError  if the PDF does not exist.
    RuntimeError       if the PDF cannot be opened.
    """
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise ImportError(
            "pymupdf is required for PDF chunking.  "
            "Install it with:  pip install pymupdf"
        ) from exc

    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF '{pdf_path}': {exc}") from exc

    all_chunks: list[str] = []
    skipped_pages = 0
    page_count = doc.page_count

    try:
        for page_num, page in enumerate(doc, start=1):
            page_text = page.get_text("text")  # type: ignore[attr-defined]
            if not page_text or not page_text.strip():
                skipped_pages += 1
                _log.debug("Page %d has no extractable text — skipping", page_num)
                continue
            page_chunks = chunk_text(page_text, chunk_size=chunk_size, overlap=overlap)
            all_chunks.extend(page_chunks)
    finally:
        doc.close()

    if skipped_pages:
        _log.warning(
            "%d page(s) in '%s' had no extractable text (possibly scanned). "
            "Use the vision pipeline for OCR on those pages.",
            skipped_pages,
            pdf_path.name,
        )

    _log.info(
        "chunked PDF '%s': %d chunks from %d page(s) (%d skipped)",
        pdf_path.name,
        len(all_chunks),
        page_count,
        skipped_pages,
    )
    return all_chunks


def chunk_pdf_paged(
    path: Path | str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    overlap: int = _DEFAULT_OVERLAP,
) -> list[tuple[str, int, int]]:
    """
    Extract text from a PDF and return chunks annotated with page provenance.

    Unlike :func:`chunk_pdf`, this function preserves per-page origin so the
    ingestion pipeline can store ``page_number`` in Qdrant metadata and later
    surface it in citations ("per MRPL Environment Report, page 12").

    Parameters
    ----------
    path:
        Absolute or relative path to the PDF file.
    chunk_size, overlap:
        Passed through to :func:`chunk_text`.

    Returns
    -------
    List of ``(chunk_text, page_number, chunk_index_within_page)`` tuples.
    ``page_number`` is 1-indexed (matches human-readable PDF page numbers).

    Raises
    ------
    ImportError        if pymupdf is not installed.
    FileNotFoundError  if the PDF does not exist.
    RuntimeError       if the PDF cannot be opened.
    """
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise ImportError(
            "pymupdf is required for PDF chunking.  "
            "Install it with:  pip install pymupdf"
        ) from exc

    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF '{pdf_path}': {exc}") from exc

    results: list[tuple[str, int, int]] = []
    skipped_pages = 0

    try:
        for page_num, page in enumerate(doc, start=1):
            page_text = page.get_text("text")  # type: ignore[attr-defined]
            if not page_text or not page_text.strip():
                skipped_pages += 1
                _log.debug("Page %d has no extractable text — skipping", page_num)
                continue
            page_chunks = chunk_text(page_text, chunk_size=chunk_size, overlap=overlap)
            for chunk_idx, chunk in enumerate(page_chunks):
                results.append((chunk, page_num, chunk_idx))
    finally:
        doc.close()

    if skipped_pages:
        _log.warning(
            "%d page(s) in '%s' had no extractable text (possibly scanned). "
            "Use the vision pipeline for OCR on those pages.",
            skipped_pages,
            pdf_path.name,
        )

    _log.info(
        "chunk_pdf_paged '%s': %d chunks across pages (%d page(s) skipped)",
        pdf_path.name,
        len(results),
        skipped_pages,
    )
    return results
