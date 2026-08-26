"""
tools/docgen/generate_docx.py
=============================
GenerateDocxTool — produce a real .docx from structured content.

The tool is purely local Python (python-docx); no model or network call is
made. This makes it trivially testable offline and sovereignty-safe by design.

Input schema
------------
title           : str          — document title (Heading 1)
sections        : list[dict]   — [{"heading": str, "body": str}]
findings_table  : list[dict]   — optional; [{"id": str, "finding": str,
                                              "severity": str, "status": str}]
recommendations : list[str]    — optional; bulleted list
output_filename : str          — e.g. "approval_note.docx"
request_id      : str | None

Output
------
ToolResult.output   : absolute path to the generated file (str)
ToolResult.metadata : {file_path, size_bytes, section_count, table_rows}

Audit
-----
One DOCGEN record per call: output_path, template_type="docx",
section_count, table_rows, request_id.

Sovereignty note
----------------
No network calls. Writes only to outputs/generated/.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from app.audit.logger import AuditLogger, EventType
from app.tools.base import BaseTool, ToolResult

_log = logging.getLogger("sovereign.tools.docgen.generate_docx")

# Output directory — relative to the project root (two levels up from this file)
_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "outputs" / "generated"

_FINDINGS_HEADERS = ["ID", "Finding", "Severity", "Status"]


class GenerateDocxTool(BaseTool):
    """Generate a formatted .docx Word document from structured content."""

    name = "generate_docx"
    description = (
        "Generate a .docx Word document from structured content: "
        "title, sections (heading + body), an optional findings table, "
        "and optional recommendations.  Returns the absolute path to the "
        "generated file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Document title — rendered as Heading 1.",
            },
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["heading", "body"],
                },
                "description": "List of sections, each with a heading and body text.",
            },
            "findings_table": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":       {"type": "string"},
                        "finding":  {"type": "string"},
                        "severity": {"type": "string"},
                        "status":   {"type": "string"},
                    },
                    "required": ["id", "finding", "severity", "status"],
                },
                "description": "Optional findings table rows.",
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional recommendation bullet points.",
            },
            "output_filename": {
                "type": "string",
                "description": "Filename for the generated file, e.g. 'approval_note.docx'.",
            },
            "request_id": {
                "type": "string",
                "description": "Correlation ID propagated through the audit log.",
            },
        },
        "required": ["title", "sections", "output_filename"],
    }

    def __init__(self, audit_logger: Optional[AuditLogger] = None) -> None:
        self._audit = audit_logger

    async def execute(self, **kwargs: Any) -> ToolResult:
        title: Optional[str] = kwargs.get("title")
        sections: list[dict] = kwargs.get("sections") or []
        findings: list[dict] = kwargs.get("findings_table") or []
        recommendations: list[str] = kwargs.get("recommendations") or []
        output_filename: Optional[str] = kwargs.get("output_filename")
        request_id: Optional[str] = kwargs.get("request_id")

        # Validate required fields
        if not title:
            return ToolResult(success=False, output=None,
                              error="Missing required argument: title")
        if not output_filename:
            return ToolResult(success=False, output=None,
                              error="Missing required argument: output_filename")

        # Ensure .docx extension
        if not output_filename.endswith(".docx"):
            output_filename += ".docx"

        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = _OUTPUT_DIR / output_filename

        t0 = time.monotonic()
        try:
            self._build_docx(
                path=output_path,
                title=title,
                sections=sections,
                findings=findings,
                recommendations=recommendations,
            )
        except Exception as exc:
            _log.exception("generate_docx failed")
            return ToolResult(
                success=False,
                output=None,
                error=f"Document generation failed: {exc}",
            )

        elapsed_ms = (time.monotonic() - t0) * 1000
        size_bytes = output_path.stat().st_size

        self._log_generation(
            output_path=str(output_path),
            section_count=len(sections),
            table_rows=len(findings),
            duration_ms=elapsed_ms,
            request_id=request_id,
        )

        return ToolResult(
            success=True,
            output=str(output_path),
            metadata={
                "file_path": str(output_path),
                "size_bytes": size_bytes,
                "section_count": len(sections),
                "table_rows": len(findings),
            },
        )

    # ------------------------------------------------------------------
    # Document builder
    # ------------------------------------------------------------------

    def _build_docx(
        self,
        path: Path,
        title: str,
        sections: list[dict],
        findings: list[dict],
        recommendations: list[str],
    ) -> None:
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        doc = Document()

        # ── Title ─────────────────────────────────────────────────────
        title_para = doc.add_heading(title, level=1)
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # ── Sections ──────────────────────────────────────────────────
        for sec in sections:
            heading = sec.get("heading", "")
            body = sec.get("body", "")
            doc.add_heading(heading, level=2)
            if body:
                doc.add_paragraph(body)

        # ── Findings table (optional) ──────────────────────────────────
        if findings:
            doc.add_heading("Findings", level=2)
            table = doc.add_table(rows=1, cols=len(_FINDINGS_HEADERS))
            table.style = "Table Grid"

            # Header row
            hdr_cells = table.rows[0].cells
            for i, header in enumerate(_FINDINGS_HEADERS):
                hdr_cells[i].text = header
                run = hdr_cells[i].paragraphs[0].runs[0]
                run.bold = True

            # Data rows
            for row_data in findings:
                row_cells = table.add_row().cells
                row_cells[0].text = str(row_data.get("id", ""))
                row_cells[1].text = str(row_data.get("finding", ""))
                row_cells[2].text = str(row_data.get("severity", ""))
                row_cells[3].text = str(row_data.get("status", ""))

        # ── Recommendations (optional) ─────────────────────────────────
        if recommendations:
            doc.add_heading("Recommendations", level=2)
            for rec in recommendations:
                doc.add_paragraph(rec, style="List Bullet")

        doc.save(str(path))

    def _log_generation(
        self,
        output_path: str,
        section_count: int,
        table_rows: int,
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
                    "template_type": "docx",
                    "output_path": output_path,
                    "section_count": section_count,
                    "table_rows": table_rows,
                    "duration_ms": round(duration_ms, 1),
                },
            )
        except Exception as exc:
            _log.warning("Failed to write DOCGEN audit record: %s", exc)
