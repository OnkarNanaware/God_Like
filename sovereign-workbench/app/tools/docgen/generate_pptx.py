"""
tools/docgen/generate_pptx.py
=============================
GeneratePptxTool — produce a real .pptx from structured slide content.

Input schema
------------
title           : str          — presentation title (title slide)
slides          : list[dict]   — [{"heading": str, "bullets": [str]}]
output_filename : str          — e.g. "findings_summary.pptx"
request_id      : str | None

Output
------
ToolResult.output   : sanitized display filename (str, e.g. "summary.pptx")
ToolResult.metadata : {"artifact": <Artifact.to_dict()>} on success
                      {"artifact_error": {filename, error}} if registration fails

Audit
-----
One DOCGEN record per call: output_path, template_type="pptx",
slide_count, request_id.

Sovereignty note
----------------
No network calls. Writes only to outputs/generated/.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from app.artifacts.manager import ArtifactError, get_artifact_manager
from app.audit.logger import AuditLogger, EventType
from app.tools.base import BaseTool, ToolResult

_log = logging.getLogger("sovereign.tools.docgen.generate_pptx")

# Output directory — the generator writes here first; ArtifactManager renames
# to a UUID-prefixed path atomically.
_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "outputs" / "generated"


class GeneratePptxTool(BaseTool):
    """Generate a formatted .pptx PowerPoint from structured slide content."""

    name = "generate_pptx"
    description = (
        "Generate a .pptx PowerPoint presentation from structured content: "
        "a title slide and a list of content slides each with a heading and "
        "bullet points. Returns the absolute path to the generated file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Presentation title — shown on the title slide.",
            },
            "slides": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["heading", "bullets"],
                },
                "description": "List of content slides, each with a heading and bullet list.",
            },
            "output_filename": {
                "type": "string",
                "description": "Filename for the generated file, e.g. 'summary.pptx'.",
            },
            "request_id": {
                "type": "string",
                "description": "Correlation ID propagated through the audit log.",
            },
        },
        "required": ["title", "slides", "output_filename"],
    }

    def __init__(self, audit_logger: Optional[AuditLogger] = None) -> None:
        self._audit = audit_logger

    async def execute(self, **kwargs: Any) -> ToolResult:
        title: Optional[str] = kwargs.get("title")
        slides: list[dict] = kwargs.get("slides") or []
        output_filename: Optional[str] = kwargs.get("output_filename")
        request_id: Optional[str] = kwargs.get("request_id")

        if not title:
            return ToolResult(success=False, output=None,
                              error="Missing required argument: title")
        if not output_filename:
            return ToolResult(success=False, output=None,
                              error="Missing required argument: output_filename")

        if not output_filename.endswith(".pptx"):
            output_filename += ".pptx"

        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = _OUTPUT_DIR / output_filename

        t0 = time.monotonic()
        try:
            self._build_pptx(path=output_path, title=title, slides=slides)
        except Exception as exc:
            _log.exception("generate_pptx failed")
            return ToolResult(
                success=False,
                output=None,
                error=f"Presentation generation failed: {exc}",
            )

        elapsed_ms = (time.monotonic() - t0) * 1000

        # ── Register artifact (atomic rename → UUID-named file) ────────────
        try:
            manager = get_artifact_manager()
            artifact = manager.register_artifact(
                source_path=output_path,
                filename=output_filename,
                mime_type="application/vnd.openxmlformats-officedocument"
                          ".presentationml.presentation",
                artifact_type="pptx",
                request_id=request_id,
            )
        except ArtifactError as exc:
            _log.error(
                "Artifact registration failed for %s: %s", output_filename, exc
            )
            output_path.unlink(missing_ok=True)
            return ToolResult(
                success=False,
                output=None,
                error=f"Artifact registration failed: {exc}",
                metadata={"artifact_error": {"filename": output_filename, "error": str(exc)}},
            )

        self._log_generation(
            output_path=str(artifact.physical_path),
            slide_count=len(slides),
            duration_ms=elapsed_ms,
            request_id=request_id,
        )

        return ToolResult(
            success=True,
            output=artifact.filename,
            metadata={
                "artifact": artifact.to_dict(),
                "slide_count": len(slides),
            },
        )

    # ------------------------------------------------------------------
    # Presentation builder
    # ------------------------------------------------------------------

    def _build_pptx(self, path: Path, title: str, slides: list[dict]) -> None:
        from pptx import Presentation

        prs = Presentation()

        # ── Title slide ────────────────────────────────────────────────
        title_layout = prs.slide_layouts[0]  # "Title Slide"
        slide = prs.slides.add_slide(title_layout)
        slide.shapes.title.text = title
        if len(slide.placeholders) > 1:
            slide.placeholders[1].text = "Generated by Sovereign Workbench"

        # ── Content slides ─────────────────────────────────────────────
        content_layout = prs.slide_layouts[1]  # "Title and Content"
        for slide_data in slides:
            heading = slide_data.get("heading", "")
            bullets = slide_data.get("bullets") or []

            sl = prs.slides.add_slide(content_layout)
            sl.shapes.title.text = heading

            body = sl.placeholders[1]
            tf = body.text_frame
            tf.clear()

            for i, bullet in enumerate(bullets):
                para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                para.text = bullet
                para.level = 0

        prs.save(str(path))

    def _log_generation(
        self,
        output_path: str,
        slide_count: int,
        duration_ms: float,
        request_id: Optional[str],
    ) -> None:
        if not self._audit:
            return
        try:
            self._audit.log_event(
                event_type=EventType.DOCGEN,
                request_id=request_id or "",
                payload={
                    "template_type": "pptx",
                    "output_path": output_path,
                    "slide_count": slide_count,
                    "duration_ms": round(duration_ms, 1),
                },
            )
        except Exception as exc:
            _log.warning("Failed to write DOCGEN audit record: %s", exc)
