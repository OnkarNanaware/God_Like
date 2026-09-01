"""
tools/docgen/generate_docx.py
=============================
GenerateDocxTool — produce a real .docx from structured content.

The tool is purely local Python (python-docx); no model or network call is
made. This makes it trivially testable offline and sovereignty-safe by design.

Input schema
------------
document_type   : str          — "inspection_report" | "approval_note" | "generic"
                                 Default: "generic"  (backward-compatible)
title           : str          — document title (Heading 1)  [generic only]
sections        : list[dict]   — [{"heading": str, "body": str}]  [generic only]
findings_table  : list[dict]   — optional generic findings table
recommendations : list[str]    — optional bulleted list  [generic only]
inspection_data : dict         — fields for InspectionReportData  [inspection_report]
approval_data   : dict         — fields for ApprovalNoteData       [approval_note]
output_filename : str          — e.g. "approval_note.docx"
request_id      : str | None

Output
------
ToolResult.output   : absolute path to the generated file (str)
ToolResult.metadata : {file_path, size_bytes, section_count, table_rows, document_type}

Audit
-----
One DOCGEN record per call: output_path, template_type="docx",
document_type, section_count, table_rows, request_id.

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
            "document_type": {
                "type": "string",
                "enum": ["inspection_report", "approval_note", "generic"],
                "description": (
                    "Which document template to use. "
                    "'inspection_report' and 'approval_note' produce template-exact "
                    "output matching the organisation's standard forms. "
                    "'generic' (default) uses the original title+sections structure."
                ),
            },
            "title": {
                "type": "string",
                "description": "Document title — rendered as Heading 1 (generic mode only).",
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
                "description": "List of sections (generic mode only).",
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
                "description": "Optional findings table rows (generic mode only).",
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional recommendation bullet points (generic mode only).",
            },
            "inspection_data": {
                "type": "object",
                "description": (
                    "Structured data for inspection_report document_type. "
                    "Fields: report_no, date_of_inspection, facility_location, "
                    "inspector_names, equipment_area, objective, observations (list), "
                    "facility_manager_sig, facility_manager_date, non_conformances, "
                    "corrective_actions (list), lead_inspector_sig, lead_inspector_date."
                ),
            },
            "approval_data": {
                "type": "object",
                "description": (
                    "Structured data for approval_note document_type. "
                    "Fields: date, to, from_, reference_no, subject_title, "
                    "background_context, proposal_request, justification, "
                    "approved_by, financial_rows (list), financial_total, initiated_by."
                ),
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
        "required": ["output_filename"],
    }

    def __init__(self, audit_logger: Optional[AuditLogger] = None) -> None:
        self._audit = audit_logger

    async def execute(self, **kwargs: Any) -> ToolResult:
        document_type: str = kwargs.get("document_type") or "generic"
        output_filename: Optional[str] = kwargs.get("output_filename")
        request_id: Optional[str] = kwargs.get("request_id")

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
            section_count, table_rows = self._dispatch_build(
                document_type=document_type,
                path=output_path,
                kwargs=kwargs,
            )
        except Exception as exc:
            _log.exception("generate_docx failed (document_type=%s)", document_type)
            return ToolResult(
                success=False,
                output=None,
                error=f"Document generation failed: {exc}",
            )

        elapsed_ms = (time.monotonic() - t0) * 1000
        size_bytes = output_path.stat().st_size

        self._log_generation(
            output_path=str(output_path),
            document_type=document_type,
            section_count=section_count,
            table_rows=table_rows,
            duration_ms=elapsed_ms,
            request_id=request_id,
        )

        return ToolResult(
            success=True,
            output=str(output_path),
            metadata={
                "file_path": str(output_path),
                "size_bytes": size_bytes,
                "section_count": section_count,
                "table_rows": table_rows,
                "document_type": document_type,
            },
        )

    # ------------------------------------------------------------------
    # Dispatch — route to the correct builder
    # ------------------------------------------------------------------

    def _dispatch_build(
        self,
        document_type: str,
        path: Path,
        kwargs: dict[str, Any],
    ) -> tuple[int, int]:
        """
        Build the document and return (section_count, table_rows) for audit.
        Raises on any build error — caller catches.
        """
        if document_type == "inspection_report":
            return self._build_inspection_report(path, kwargs)
        if document_type == "approval_note":
            return self._build_approval_note(path, kwargs)
        # Default: generic builder (unchanged original logic)
        return self._build_generic_docx(path, kwargs)

    def _build_inspection_report(
        self, path: Path, kwargs: dict[str, Any]
    ) -> tuple[int, int]:
        """Route to the template-exact inspection report builder."""
        from app.tools.docgen.inspection_report import (
            InspectionReportData,
            ObservationRow,
            CorrectiveActionRow,
            build_inspection_report,
        )
        raw = kwargs.get("inspection_data") or {}
        observations = [
            ObservationRow(**r) if isinstance(r, dict) else r
            for r in (raw.get("observations") or [])
        ]
        corrective_actions = [
            CorrectiveActionRow(**r) if isinstance(r, dict) else r
            for r in (raw.get("corrective_actions") or [])
        ]
        data = InspectionReportData(
            report_no=raw.get("report_no", ""),
            date_of_inspection=raw.get("date_of_inspection", ""),
            facility_location=raw.get("facility_location", ""),
            inspector_names=raw.get("inspector_names", ""),
            equipment_area=raw.get("equipment_area", ""),
            objective=raw.get("objective", ""),
            observations=observations,
            facility_manager_sig=raw.get("facility_manager_sig", ""),
            facility_manager_date=raw.get("facility_manager_date", ""),
            non_conformances=raw.get("non_conformances", ""),
            corrective_actions=corrective_actions,
            lead_inspector_sig=raw.get("lead_inspector_sig", ""),
            lead_inspector_date=raw.get("lead_inspector_date", ""),
        )
        build_inspection_report(data, path)
        return 4, len(observations)  # 4 numbered sections

    def _build_approval_note(
        self, path: Path, kwargs: dict[str, Any]
    ) -> tuple[int, int]:
        """Route to the template-exact approval note builder."""
        from app.tools.docgen.approval_note import (
            ApprovalNoteData,
            FinancialRow,
            build_approval_note,
        )
        raw = kwargs.get("approval_data") or {}
        financial_rows = [
            FinancialRow(**r) if isinstance(r, dict) else r
            for r in (raw.get("financial_rows") or [])
        ]
        data = ApprovalNoteData(
            date=raw.get("date", ""),
            to=raw.get("to", ""),
            from_=raw.get("from_", ""),
            reference_no=raw.get("reference_no", ""),
            subject_title=raw.get("subject_title", ""),
            background_context=raw.get("background_context", ""),
            proposal_request=raw.get("proposal_request", ""),
            justification=raw.get("justification", ""),
            approved_by=raw.get("approved_by", ""),
            financial_rows=financial_rows,
            financial_total=raw.get("financial_total", ""),
            initiated_by=raw.get("initiated_by", ""),
        )
        build_approval_note(data, path)
        return 5, len(financial_rows)  # 5 numbered sections

    # ------------------------------------------------------------------
    # Generic document builder (original logic — unchanged)
    # ------------------------------------------------------------------

    def _build_generic_docx(
        self,
        path: Path,
        kwargs: dict[str, Any],
    ) -> tuple[int, int]:
        """Original generic title+sections+findings builder. Returns (section_count, table_rows)."""
        title: Optional[str] = kwargs.get("title")
        sections: list[dict] = kwargs.get("sections") or []
        findings: list[dict] = kwargs.get("findings_table") or []
        recommendations: list[str] = kwargs.get("recommendations") or []

        if not title:
            raise ValueError("Missing required argument: title")

        from docx import Document
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
                runs = hdr_cells[i].paragraphs[0].runs
                if runs:
                    runs[0].bold = True

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
        return len(sections), len(findings)

    def _log_generation(
        self,
        output_path: str,
        document_type: str,
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
                    "document_type": document_type,
                    "output_path": output_path,
                    "section_count": section_count,
                    "table_rows": table_rows,
                    "duration_ms": round(duration_ms, 1),
                },
            )
        except Exception as exc:
            _log.warning("Failed to write DOCGEN audit record: %s", exc)
