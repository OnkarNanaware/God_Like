"""
tests/test_artifact_collision.py
=================================
Concurrency / collision tests for the docgen artifact pipeline.

Key assertion:
  Two simultaneous generate_docx calls with the SAME output_filename
  must produce TWO unique artifacts with two separate physical files,
  neither overwriting the other.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.artifacts.manager import ArtifactManager, get_artifact_manager
from app.tools.docgen.generate_docx import GenerateDocxTool
from app.tools.docgen.generate_pptx import GeneratePptxTool
from app.tools.docgen.generate_xlsx import GenerateXlsxTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path) -> ArtifactManager:
    """Create an isolated ArtifactManager for the test — does NOT replace the singleton."""
    return ArtifactManager(storage_dir=tmp_path / "generated")


# ---------------------------------------------------------------------------
# Concurrent same-filename DOCX
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_concurrent_docx_same_filename(tmp_path, monkeypatch):
    """
    Two simultaneous GenerateDocxTool calls with output_filename='report.docx'
    must produce 2 unique artifacts pointing to 2 separate physical files.
    """
    manager = _make_manager(tmp_path)

    # Patch the module-level _OUTPUT_DIR for both tool instances to use tmp_path
    import app.tools.docgen.generate_docx as docx_mod
    monkeypatch.setattr(docx_mod, "_OUTPUT_DIR", tmp_path / "generated")
    # Patch get_artifact_manager to return our isolated manager
    monkeypatch.setattr(docx_mod, "get_artifact_manager", lambda: manager)

    tool = GenerateDocxTool(audit_logger=None)

    kwargs = dict(
        title="Concurrent Report",
        sections=[{"heading": "Section A", "body": "Body text."}],
        output_filename="report.docx",
        request_id="req-collision-test",
    )

    result_a, result_b = await asyncio.gather(
        tool.execute(**kwargs),
        tool.execute(**kwargs),
    )

    # Both must succeed
    assert result_a.success, f"result_a failed: {result_a.error}"
    assert result_b.success, f"result_b failed: {result_b.error}"

    art_a = result_a.metadata["artifact"]
    art_b = result_b.metadata["artifact"]

    # Unique artifact IDs
    assert art_a["artifact_id"] != art_b["artifact_id"], \
        "Two simultaneous registrations must produce unique artifact IDs"

    # Unique download URLs
    assert art_a["download_url"] != art_b["download_url"]

    # No physical_path in to_dict()
    assert "physical_path" not in art_a
    assert "physical_path" not in art_b

    # Both physical files exist
    phys_a = manager.get_artifact(art_a["artifact_id"]).physical_path
    phys_b = manager.get_artifact(art_b["artifact_id"]).physical_path
    assert phys_a.exists(), f"Physical file for artifact A missing: {phys_a}"
    assert phys_b.exists(), f"Physical file for artifact B missing: {phys_b}"
    assert phys_a != phys_b, "Two artifacts must have different physical files"


# ---------------------------------------------------------------------------
# Concurrent same-filename PPTX
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_concurrent_pptx_same_filename(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)

    import app.tools.docgen.generate_pptx as pptx_mod
    monkeypatch.setattr(pptx_mod, "_OUTPUT_DIR", tmp_path / "generated")
    monkeypatch.setattr(pptx_mod, "get_artifact_manager", lambda: manager)

    tool = GeneratePptxTool(audit_logger=None)
    kwargs = dict(
        title="Concurrent Deck",
        slides=[{"heading": "Slide 1", "bullets": ["Bullet A", "Bullet B"]}],
        output_filename="deck.pptx",
        request_id="req-pptx-collision",
    )

    result_a, result_b = await asyncio.gather(
        tool.execute(**kwargs),
        tool.execute(**kwargs),
    )

    assert result_a.success and result_b.success
    art_a = result_a.metadata["artifact"]
    art_b = result_b.metadata["artifact"]
    assert art_a["artifact_id"] != art_b["artifact_id"]
    assert "physical_path" not in art_a
    assert "physical_path" not in art_b


# ---------------------------------------------------------------------------
# Concurrent same-filename XLSX
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_concurrent_xlsx_same_filename(tmp_path, monkeypatch):
    manager = _make_manager(tmp_path)

    import app.tools.docgen.generate_xlsx as xlsx_mod
    monkeypatch.setattr(xlsx_mod, "_OUTPUT_DIR", tmp_path / "generated")
    monkeypatch.setattr(xlsx_mod, "get_artifact_manager", lambda: manager)

    tool = GenerateXlsxTool(audit_logger=None)
    kwargs = dict(
        headers=["Name", "Score"],
        rows=[["Alice", 95], ["Bob", 88]],
        output_filename="scores.xlsx",
        request_id="req-xlsx-collision",
    )

    result_a, result_b = await asyncio.gather(
        tool.execute(**kwargs),
        tool.execute(**kwargs),
    )

    assert result_a.success and result_b.success
    art_a = result_a.metadata["artifact"]
    art_b = result_b.metadata["artifact"]
    assert art_a["artifact_id"] != art_b["artifact_id"]
    assert "physical_path" not in art_a
    assert "physical_path" not in art_b


# ---------------------------------------------------------------------------
# Mass concurrent registrations — uniqueness at scale
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mass_concurrent_docx(tmp_path, monkeypatch):
    """Register 20 concurrent docs with the same filename — all must be unique."""
    manager = _make_manager(tmp_path)

    import app.tools.docgen.generate_docx as docx_mod
    monkeypatch.setattr(docx_mod, "_OUTPUT_DIR", tmp_path / "generated")
    monkeypatch.setattr(docx_mod, "get_artifact_manager", lambda: manager)

    tool = GenerateDocxTool(audit_logger=None)
    kwargs = dict(
        title="Mass Report",
        sections=[{"heading": "H", "body": "B"}],
        output_filename="mass_report.docx",
    )

    results = await asyncio.gather(*[tool.execute(**kwargs) for _ in range(20)])

    succeeded = [r for r in results if r.success]
    assert len(succeeded) == 20, f"Expected all 20 to succeed, got {len(succeeded)}"

    ids = {r.metadata["artifact"]["artifact_id"] for r in succeeded}
    assert len(ids) == 20, f"Expected 20 unique artifact IDs, got {len(ids)}"
