"""
tools/docgen/generate_xlsx.py
=============================
GenerateXlsxTool — produce a real .xlsx spreadsheet from structured row data.

Input schema
------------
sheet_name      : str          — name of the worksheet (default "Sheet1")
headers         : list[str]    — column header labels
rows            : list[list]   — 2-D list of cell values
formula_row     : list[str]    — optional final row of Excel formula strings
                                 (e.g. ["=SUM(B2:B10)", "=AVERAGE(C2:C10)"])
output_filename : str          — e.g. "findings_data.xlsx"
request_id      : str | None

Output
------
ToolResult.output   : sanitized display filename (str, e.g. "data.xlsx")
ToolResult.metadata : {"artifact": <Artifact.to_dict()>} on success
                      {"artifact_error": {filename, error}} if registration fails

Audit
-----
One DOCGEN record per call: output_path, template_type="xlsx",
row_count, col_count, request_id.

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

_log = logging.getLogger("sovereign.tools.docgen.generate_xlsx")

# Output directory — the generator writes here first; ArtifactManager renames
# to a UUID-prefixed path atomically.
_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "outputs" / "generated"


class GenerateXlsxTool(BaseTool):
    """Generate a .xlsx Excel workbook from structured tabular data."""

    name = "generate_xlsx"
    description = (
        "Generate a .xlsx Excel workbook from structured tabular data: "
        "headers, data rows, and an optional formula row. Returns the "
        "absolute path to the generated file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "sheet_name": {
                "type": "string",
                "description": "Name of the worksheet (default: 'Sheet1').",
            },
            "headers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Column header labels.",
            },
            "rows": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {},
                },
                "description": "2-D list of cell values (strings or numbers).",
            },
            "formula_row": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional final row of Excel formula strings "
                    "(e.g. '=SUM(B2:B10)'). Use empty string '' to skip a cell."
                ),
            },
            "output_filename": {
                "type": "string",
                "description": "Filename for the generated file, e.g. 'data.xlsx'.",
            },
            "request_id": {
                "type": "string",
                "description": "Correlation ID propagated through the audit log.",
            },
        },
        "required": ["headers", "rows", "output_filename"],
    }

    def __init__(self, audit_logger: Optional[AuditLogger] = None) -> None:
        self._audit = audit_logger

    async def execute(self, **kwargs: Any) -> ToolResult:
        sheet_name: str = kwargs.get("sheet_name") or "Sheet1"
        headers: list[str] = kwargs.get("headers") or []
        rows: list[list] = kwargs.get("rows") or []
        formula_row: list[str] = kwargs.get("formula_row") or []
        output_filename: Optional[str] = kwargs.get("output_filename")
        request_id: Optional[str] = kwargs.get("request_id")

        if not headers:
            return ToolResult(success=False, output=None,
                              error="Missing required argument: headers")
        if not output_filename:
            return ToolResult(success=False, output=None,
                              error="Missing required argument: output_filename")

        if not output_filename.endswith(".xlsx"):
            output_filename += ".xlsx"

        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = _OUTPUT_DIR / output_filename

        t0 = time.monotonic()
        try:
            self._build_xlsx(
                path=output_path,
                sheet_name=sheet_name,
                headers=headers,
                rows=rows,
                formula_row=formula_row,
            )
        except Exception as exc:
            _log.exception("generate_xlsx failed")
            return ToolResult(
                success=False,
                output=None,
                error=f"Spreadsheet generation failed: {exc}",
            )

        elapsed_ms = (time.monotonic() - t0) * 1000

        # ── Register artifact (atomic rename → UUID-named file) ────────────
        try:
            manager = get_artifact_manager()
            artifact = manager.register_artifact(
                source_path=output_path,
                filename=output_filename,
                mime_type="application/vnd.openxmlformats-officedocument"
                          ".spreadsheetml.sheet",
                artifact_type="xlsx",
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
            row_count=len(rows),
            col_count=len(headers),
            duration_ms=elapsed_ms,
            request_id=request_id,
        )

        return ToolResult(
            success=True,
            output=artifact.filename,
            metadata={
                "artifact": artifact.to_dict(),
                "row_count": len(rows),
                "col_count": len(headers),
            },
        )

    # ------------------------------------------------------------------
    # Workbook builder
    # ------------------------------------------------------------------

    def _build_xlsx(
        self,
        path: Path,
        sheet_name: str,
        headers: list[str],
        rows: list[list],
        formula_row: list[str],
    ) -> None:
        import openpyxl
        from openpyxl.styles import Font

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name

        # ── Header row ─────────────────────────────────────────────────
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)

        # ── Data rows ──────────────────────────────────────────────────
        for row in rows:
            ws.append(list(row))

        # ── Optional formula row ───────────────────────────────────────
        if formula_row:
            formula_cells = []
            for val in formula_row:
                formula_cells.append(val if val else None)
            ws.append(formula_cells)

        # Auto-size columns (best-effort)
        for col in ws.columns:
            max_len = max(
                (len(str(cell.value)) if cell.value is not None else 0)
                for cell in col
            )
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)

        wb.save(str(path))

    def _log_generation(
        self,
        output_path: str,
        row_count: int,
        col_count: int,
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
                    "template_type": "xlsx",
                    "output_path": output_path,
                    "row_count": row_count,
                    "col_count": col_count,
                    "duration_ms": round(duration_ms, 1),
                },
            )
        except Exception as exc:
            _log.warning("Failed to write DOCGEN audit record: %s", exc)
