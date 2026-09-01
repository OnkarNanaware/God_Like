"""
tests/test_template_and_gating.py
===================================
Phase D refinement tests — template-exact doc builders, spreadsheet analysis,
router routing, and orchestrator generation gating.

Test classes
------------
 1. TestInspectionReportBuilder  — build_inspection_report() structure assertions
 2. TestApprovalNoteBuilder      — build_approval_note() structure assertions
 3. TestAnalyzeSpreadsheetTool   — extraction + LLM summary via FakeOllamaClient
 4. TestSpreadsheetRouter        — router heuristics for .xlsx/.csv
 5. TestGenerationGating         — orchestrator planning gating (both directions)
"""

from __future__ import annotations

import asyncio
import csv
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

import pytest
import openpyxl

# ---------------------------------------------------------------------------
# Async runner helper
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously (compatible with tests that don't use pytest-asyncio)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Shared audit factory
# ---------------------------------------------------------------------------


def _make_audit(tmp_path: Path):
    from app.audit.logger import AuditLogger
    return AuditLogger(log_path=tmp_path / "audit.jsonl")


# ===========================================================================
# 1. TestInspectionReportBuilder
# ===========================================================================

class TestInspectionReportBuilder:
    """
    Assertions on the template-exact inspection report .docx structure.
    Opens the generated file with python-docx and inspects headings and tables.
    """

    def _build(self, tmp_path: Path, data_kwargs: dict = None):
        from app.tools.docgen.inspection_report import (
            InspectionReportData,
            ObservationRow,
            CorrectiveActionRow,
            build_inspection_report,
        )
        if data_kwargs is None:
            data_kwargs = {}
        data = InspectionReportData(**data_kwargs)
        out = tmp_path / "test_insp.docx"
        build_inspection_report(data, out)
        return out

    def _open_docx(self, path: Path):
        from docx import Document
        return Document(str(path))

    def _headings(self, doc) -> list[str]:
        return [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]

    # ── Test 1: section headers present and correct ─────────────────────

    def test_section_headers_present(self, tmp_path):
        """All 4 section headers + facility manager + lead inspector blocks are present."""
        out = self._build(tmp_path)
        doc = self._open_docx(out)
        headings = self._headings(doc)

        assert any("INSPECTION REPORT" in h for h in headings), \
            f"Title missing. Headings: {headings}"
        assert any("Section 1" in h and "Objective" in h for h in headings), \
            f"Section 1 missing. Headings: {headings}"
        assert any("Section 2" in h and "Observations" in h for h in headings), \
            f"Section 2 missing. Headings: {headings}"
        assert any("Facility Manager" in h for h in headings), \
            f"Facility Manager Acknowledgment missing. Headings: {headings}"
        assert any("Section 3" in h and "Non-Conformance" in h for h in headings), \
            f"Section 3 missing. Headings: {headings}"
        assert any("Section 4" in h and "Corrective" in h for h in headings), \
            f"Section 4 missing. Headings: {headings}"
        assert any("Lead Inspector" in h for h in headings), \
            f"Lead Inspector block missing. Headings: {headings}"

    # ── Test 2: Observations table has exact column headers ─────────────

    def test_observations_table_column_headers(self, tmp_path):
        """Section 2 table must have: Sl No. | Checklist Item / Observation | Status (Pass/Fail) | Remarks"""
        from app.tools.docgen.inspection_report import (
            InspectionReportData,
            ObservationRow,
            build_inspection_report,
        )
        data = InspectionReportData(
            observations=[
                ObservationRow(sl_no="1", checklist_item="Check valve", status="Pass", remarks="OK")
            ]
        )
        out = tmp_path / "test_obs.docx"
        build_inspection_report(data, out)
        doc = self._open_docx(out)

        # Find the observations table — it has 4 columns
        obs_tables = [t for t in doc.tables if len(t.columns) == 4]
        assert obs_tables, "No 4-column table found for Observations & Findings"
        obs_table = obs_tables[0]

        header_row = obs_table.rows[0]
        headers = [cell.text.strip() for cell in header_row.cells]
        assert "Sl No." in headers, f"'Sl No.' missing from table headers: {headers}"
        assert any("Checklist Item" in h for h in headers), \
            f"'Checklist Item / Observation' missing: {headers}"
        assert any("Status" in h and "Pass" in h for h in headers), \
            f"'Status (Pass/Fail)' missing: {headers}"
        assert "Remarks" in headers, f"'Remarks' missing: {headers}"

    # ── Test 3: Corrective Action table column headers ───────────────────

    def test_corrective_action_table_column_headers(self, tmp_path):
        """Section 4 table must have: Recommended Action | Responsibility | Target Date"""
        from app.tools.docgen.inspection_report import (
            InspectionReportData,
            CorrectiveActionRow,
            build_inspection_report,
        )
        data = InspectionReportData(
            corrective_actions=[
                CorrectiveActionRow(
                    recommended_action="Replace tube bundle",
                    responsibility="Eng. Sharma",
                    target_date="2026-09-15",
                )
            ]
        )
        out = tmp_path / "test_ca.docx"
        build_inspection_report(data, out)
        doc = self._open_docx(out)

        # 3-column table = corrective actions
        ca_tables = [t for t in doc.tables if len(t.columns) == 3]
        assert ca_tables, "No 3-column table found for Corrective Actions"
        ca_table = ca_tables[0]

        headers = [cell.text.strip() for cell in ca_table.rows[0].cells]
        assert any("Recommended Action" in h for h in headers), \
            f"'Recommended Action' missing: {headers}"
        assert any("Responsibility" in h for h in headers), \
            f"'Responsibility' missing: {headers}"
        assert any("Target Date" in h for h in headers), \
            f"'Target Date' missing: {headers}"

    # ── Test 4: Facility Manager acknowledgment is mid-document (not at end) ──

    def test_facility_manager_ack_position_is_mid_document(self, tmp_path):
        """
        The Facility Manager Acknowledgment heading must come BEFORE Section 3
        and Section 4 headings — confirming mid-document placement.
        """
        out = self._build(tmp_path)
        doc = self._open_docx(out)
        headings = self._headings(doc)

        fac_mgr_idx = next(
            (i for i, h in enumerate(headings) if "Facility Manager" in h), None
        )
        sec3_idx = next(
            (i for i, h in enumerate(headings) if "Section 3" in h), None
        )
        sec4_idx = next(
            (i for i, h in enumerate(headings) if "Section 4" in h), None
        )
        assert fac_mgr_idx is not None, "Facility Manager heading not found"
        assert sec3_idx is not None, "Section 3 heading not found"
        assert sec4_idx is not None, "Section 4 heading not found"
        assert fac_mgr_idx < sec3_idx, (
            f"Facility Manager ack (idx={fac_mgr_idx}) must appear BEFORE "
            f"Section 3 (idx={sec3_idx})"
        )
        assert fac_mgr_idx < sec4_idx, (
            f"Facility Manager ack (idx={fac_mgr_idx}) must appear BEFORE "
            f"Section 4 (idx={sec4_idx})"
        )

    # ── Test 5: blank fields render as placeholder underscores, not omitted ──

    def test_blank_field_renders_as_placeholder(self, tmp_path):
        """Empty data fields render as '_______________', not empty string or omitted."""
        # Build with all-empty data
        out = self._build(tmp_path, data_kwargs={})
        doc = self._open_docx(out)

        all_text = " ".join(p.text for p in doc.paragraphs)
        assert "_______________" in all_text, (
            "Blank placeholder '_______________' not found in document — "
            "empty fields appear to be omitted rather than shown as blanks"
        )


# ===========================================================================
# 2. TestApprovalNoteBuilder
# ===========================================================================

class TestApprovalNoteBuilder:

    def _build(self, tmp_path: Path, data_kwargs: dict = None):
        from app.tools.docgen.approval_note import (
            ApprovalNoteData,
            FinancialRow,
            build_approval_note,
        )
        if data_kwargs is None:
            data_kwargs = {}
        data = ApprovalNoteData(**data_kwargs)
        out = tmp_path / "test_an.docx"
        build_approval_note(data, out)
        return out

    def _open_docx(self, path: Path):
        from docx import Document
        return Document(str(path))

    def _headings(self, doc) -> list[str]:
        return [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]

    # ── Test 6: all section headers present ──────────────────────────────

    def test_section_headers_present(self, tmp_path):
        out = self._build(tmp_path)
        doc = self._open_docx(out)
        headings = self._headings(doc)

        assert any("APPROVAL NOTE" in h for h in headings), \
            f"Title missing. Headings: {headings}"
        assert any("Section 1" in h and "Subject" in h for h in headings), \
            f"Section 1 (Subject) missing. Headings: {headings}"
        assert any("Section 2" in h and "Background" in h for h in headings), \
            f"Section 2 (Background) missing. Headings: {headings}"
        assert any("Section 3" in h and "Proposal" in h for h in headings), \
            f"Section 3 (Proposal) missing. Headings: {headings}"
        assert any("Section 4" in h and "Justification" in h for h in headings), \
            f"Section 4 (Justification) missing. Headings: {headings}"
        assert any("Approved By" in h for h in headings), \
            f"Approved By block missing. Headings: {headings}"
        assert any("Section 5" in h and "Financial" in h for h in headings), \
            f"Section 5 (Financial) missing. Headings: {headings}"
        assert any("Initiated By" in h for h in headings), \
            f"Initiated By block missing. Headings: {headings}"

    # ── Test 7: financial table column headers ────────────────────────────

    def test_financial_table_column_headers(self, tmp_path):
        """Section 5 table must have: Budget Head / Cost Center | Estimated Cost"""
        from app.tools.docgen.approval_note import (
            ApprovalNoteData,
            FinancialRow,
            build_approval_note,
        )
        data = ApprovalNoteData(
            financial_rows=[
                FinancialRow(budget_head="Maintenance CAPEX", estimated_cost="INR 4,50,000")
            ]
        )
        out = tmp_path / "test_fin.docx"
        build_approval_note(data, out)
        doc = self._open_docx(out)

        fin_tables = [t for t in doc.tables if len(t.columns) == 2]
        assert fin_tables, "No 2-column table found for Financial Implications"
        fin_table = fin_tables[-1]  # last 2-col table = financial (header table is also 2-col)

        # Find the financial table specifically (the one with "Budget" in it)
        fin_table = None
        for t in doc.tables:
            if len(t.columns) == 2:
                cell_texts = [c.text for c in t.rows[0].cells]
                if any("Budget" in ct or "Cost" in ct for ct in cell_texts):
                    fin_table = t
                    break

        assert fin_table is not None, "Could not find Financial Implications table"
        headers = [cell.text.strip() for cell in fin_table.rows[0].cells]
        assert any("Budget" in h or "Cost Center" in h for h in headers), \
            f"'Budget Head / Cost Center' missing: {headers}"
        assert any("Estimated Cost" in h or "Cost" in h for h in headers), \
            f"'Estimated Cost' missing: {headers}"

    # ── Test 8: Total row present in financial table ─────────────────────

    def test_financial_table_has_total_row(self, tmp_path):
        """The financial table must have a bold Total row as the last row."""
        from app.tools.docgen.approval_note import (
            ApprovalNoteData,
            FinancialRow,
            build_approval_note,
        )
        data = ApprovalNoteData(
            financial_rows=[FinancialRow(budget_head="A", estimated_cost="100")],
            financial_total="100",
        )
        out = tmp_path / "test_total.docx"
        build_approval_note(data, out)
        doc = self._open_docx(out)

        # Find the financial table
        fin_table = None
        for t in doc.tables:
            if len(t.columns) == 2:
                all_text = " ".join(c.text for row in t.rows for c in row.cells)
                if "Total" in all_text or "Budget" in all_text:
                    fin_table = t
                    break

        assert fin_table is not None, "Financial table not found"
        last_row = fin_table.rows[-1]
        row_texts = [c.text.strip() for c in last_row.cells]
        assert any("Total" in t for t in row_texts), \
            f"Total row not found as last row. Last row: {row_texts}"

    # ── Test 9: Approved By block precedes Financial Implications ────────

    def test_approved_by_before_financial_section(self, tmp_path):
        """Approved By heading must come before Section 5 (Financial Implications)."""
        out = self._build(tmp_path)
        doc = self._open_docx(out)
        headings = self._headings(doc)

        ab_idx = next(
            (i for i, h in enumerate(headings) if "Approved By" in h), None
        )
        sec5_idx = next(
            (i for i, h in enumerate(headings) if "Section 5" in h or "Financial" in h), None
        )
        assert ab_idx is not None, "Approved By heading not found"
        assert sec5_idx is not None, "Section 5 / Financial heading not found"
        assert ab_idx < sec5_idx, (
            f"Approved By (idx={ab_idx}) must come BEFORE Section 5 (idx={sec5_idx})"
        )

    # ── Test 10: blank fields render as placeholder ────────────────────

    def test_blank_field_renders_as_placeholder(self, tmp_path):
        out = self._build(tmp_path, data_kwargs={})
        doc = self._open_docx(out)
        all_text = " ".join(p.text for p in doc.paragraphs)
        assert "_______________" in all_text


# ===========================================================================
# 3. TestAnalyzeSpreadsheetTool
# ===========================================================================

class FakeAnalysisResponse:
    def __init__(self, content: str = "This is a test summary."):
        self.content = content
        self.prompt_tokens = 10
        self.response_tokens = 20
        self.total_tokens = 30
        self.latency_ms = 1.0
        self.model_name = "fake"
        self.ollama_tag = "fake:latest"
        self.request_id = "fake"


class FakeAnalysisClient:
    def __init__(self, response_text: str = "This is a test summary."):
        self._text = response_text
        self.call_count = 0

    async def chat_completion(self, messages, *, request_id=None,
                              temperature=0.2, max_tokens=512,
                              extra_body=None):
        self.call_count += 1
        return FakeAnalysisResponse(self._text)


def _make_test_xlsx(path: Path) -> None:
    """Create a small test .xlsx with numeric data for stats testing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Costs"
    ws.append(["Item", "Cost (INR)", "Quantity"])
    ws.append(["Valve A", 45000, 3])
    ws.append(["Valve B", 120000, 1])
    ws.append(["Gasket Set", 8500, 5])

    ws2 = wb.create_sheet("Summary")
    ws2.append(["Category", "Total"])
    ws2.append(["Mechanical", 213500])
    wb.save(str(path))


def _make_test_csv(path: Path) -> None:
    """Create a small test .csv."""
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ID", "Value", "Label"])
        writer.writerow(["R1", "100", "Alpha"])
        writer.writerow(["R2", "200", "Beta"])
        writer.writerow(["R3", "300", "Gamma"])


class TestAnalyzeSpreadsheetTool:

    def _make_tool(self, tmp_path: Path, response_text: str = "Summary text."):
        from app.tools.analyze_spreadsheet import AnalyzeSpreadsheetTool
        client = FakeAnalysisClient(response_text)
        audit = _make_audit(tmp_path)
        return AnalyzeSpreadsheetTool(llm_client=client, audit_logger=audit), client

    # ── Test 11: extracts correct sheet/row/col info from .xlsx ──────────

    def test_xlsx_extraction_structure(self, tmp_path):
        """Correct sheet names, row count, col count, and headers extracted."""
        xlsx_path = tmp_path / "test_data.xlsx"
        _make_test_xlsx(xlsx_path)

        tool, _ = self._make_tool(tmp_path)
        result = _run(tool.execute(file_path=str(xlsx_path), request_id="test-011"))

        assert result.success is True, f"Expected success, got: {result.error}"
        sheets = result.output["sheets"]
        assert len(sheets) == 2, f"Expected 2 sheets, got {len(sheets)}"

        costs_sheet = next(s for s in sheets if s["name"] == "Costs")
        assert costs_sheet["row_count"] == 3, f"Expected 3 data rows, got {costs_sheet['row_count']}"
        assert costs_sheet["col_count"] == 3, f"Expected 3 cols, got {costs_sheet['col_count']}"
        assert "Item" in costs_sheet["headers"]
        assert "Cost (INR)" in costs_sheet["headers"]

        assert result.metadata["sheet_count"] == 2
        assert result.metadata["total_rows"] == 4  # 3 in Costs + 1 in Summary

    # ── Test 12: numeric stats computed correctly ──────────────────────

    def test_numeric_stats_computed(self, tmp_path):
        """Numeric columns get min/max/mean stats."""
        xlsx_path = tmp_path / "test_stats.xlsx"
        _make_test_xlsx(xlsx_path)

        tool, _ = self._make_tool(tmp_path)
        result = _run(tool.execute(file_path=str(xlsx_path), request_id="test-012"))

        costs_sheet = next(s for s in result.output["sheets"] if s["name"] == "Costs")
        stats = costs_sheet["numeric_stats"]
        assert "Cost (INR)" in stats, f"No stats for 'Cost (INR)'. stats keys: {list(stats.keys())}"

        cost_stats = stats["Cost (INR)"]
        assert cost_stats["min"] == 8500.0
        assert cost_stats["max"] == 120000.0
        assert abs(cost_stats["mean"] - (45000 + 120000 + 8500) / 3) < 1.0

    # ── Test 13: summary is non-empty from FakeOllamaClient ─────────────

    def test_summary_non_empty(self, tmp_path):
        """A non-empty summary is returned from the fake LLM client."""
        xlsx_path = tmp_path / "test_summary.xlsx"
        _make_test_xlsx(xlsx_path)

        tool, client = self._make_tool(tmp_path, "This spreadsheet contains cost data for three valve components.")
        result = _run(tool.execute(file_path=str(xlsx_path), request_id="test-013"))

        assert result.success is True
        summary = result.output["summary"]
        assert summary and len(summary) > 10, f"Summary too short or empty: {summary!r}"
        assert client.call_count == 1, "Expected exactly one LLM call for summarisation"

    # ── Test 14: .csv file handled correctly ─────────────────────────────

    def test_csv_extraction(self, tmp_path):
        """CSV files are parsed and structured correctly."""
        csv_path = tmp_path / "test_data.csv"
        _make_test_csv(csv_path)

        tool, _ = self._make_tool(tmp_path)
        result = _run(tool.execute(file_path=str(csv_path), request_id="test-014"))

        assert result.success is True, f"Error: {result.error}"
        sheets = result.output["sheets"]
        assert len(sheets) == 1
        sheet = sheets[0]
        assert sheet["row_count"] == 3
        assert sheet["col_count"] == 3
        assert "ID" in sheet["headers"]
        assert "Value" in sheet["headers"]
        assert result.metadata["sheet_count"] == 1
        assert result.metadata["total_rows"] == 3

    # ── Test 15: missing file returns failure ─────────────────────────────

    def test_missing_file_returns_failure(self, tmp_path):
        tool, _ = self._make_tool(tmp_path)
        result = _run(tool.execute(file_path="/nonexistent/file.xlsx", request_id="test-015"))
        assert result.success is False
        assert "not found" in result.error.lower()

    # ── Test 16: unsupported extension returns failure ───────────────────

    def test_unsupported_extension_returns_failure(self, tmp_path):
        bad = tmp_path / "report.docx"
        bad.write_text("not a spreadsheet")
        tool, _ = self._make_tool(tmp_path)
        result = _run(tool.execute(file_path=str(bad), request_id="test-016"))
        assert result.success is False
        assert "unsupported" in result.error.lower()


# ===========================================================================
# 4. TestSpreadsheetRouter
# ===========================================================================

class TestSpreadsheetRouter:
    """Confirm the heuristic router emits a strong signal for .xlsx/.csv uploads."""

    def test_xlsx_attachment_routes_to_spreadsheet_analysis(self):
        from app.router.heuristics import run_heuristics, is_ambiguous, Capability

        signals = run_heuristics(
            "Please summarize this cost tracking file.",
            attached_filenames=["cost_tracker.xlsx"],
        )
        assert signals, "Expected at least one heuristic signal for .xlsx"
        assert not is_ambiguous(signals), \
            f"Signal was unexpectedly ambiguous (confidence={signals[0].confidence})"
        assert signals[0].capability == Capability.SPREADSHEET_ANALYSIS, \
            f"Expected SPREADSHEET_ANALYSIS, got {signals[0].capability}"
        assert signals[0].confidence >= 0.75

    def test_csv_attachment_routes_to_spreadsheet_analysis(self):
        from app.router.heuristics import run_heuristics, is_ambiguous, Capability

        signals = run_heuristics(
            "Analyse this CSV file for me.",
            attached_filenames=["data_export.csv"],
        )
        assert signals, "Expected at least one heuristic signal for .csv"
        assert not is_ambiguous(signals), \
            f"Signal was unexpectedly ambiguous (confidence={signals[0].confidence})"
        assert signals[0].capability == Capability.SPREADSHEET_ANALYSIS, \
            f"Expected SPREADSHEET_ANALYSIS, got {signals[0].capability}"

    def test_xls_attachment_routes_to_spreadsheet_analysis(self):
        from app.router.heuristics import run_heuristics, Capability

        signals = run_heuristics(
            "What's in this file?",
            attached_filenames=["old_report.xls"],
        )
        assert signals
        assert signals[0].capability == Capability.SPREADSHEET_ANALYSIS

    def test_pdf_still_routes_to_vision(self):
        """Regression: PDF routing must not be affected by spreadsheet changes."""
        from app.router.heuristics import run_heuristics, Capability

        signals = run_heuristics(
            "Extract findings from this PDF.",
            attached_filenames=["inspection.pdf"],
        )
        assert signals
        assert signals[0].capability == Capability.DOCUMENT_VISION


# ===========================================================================
# 5. TestGenerationGating  — THE CRITICAL SECTION
# ===========================================================================

class _FakeGatingResponse:
    """Minimal fake LLM response carrying scripted content."""
    prompt_tokens = 5
    response_tokens = 5
    total_tokens = 10
    latency_ms = 1.0
    model_name = "fake"
    ollama_tag = "fake:latest"

    def __init__(self, content: str, request_id: str = "fake"):
        self.content = content
        self.request_id = request_id


class _FakeOllamaClientGating:
    """
    Scripted fake client for gating tests.
    Takes a list of response strings:
      - First call (planning) → plan JSON
      - Second call (synthesis) → synthesis text
    """
    def __init__(self, responses: list[str]):
        self._responses = responses
        self._idx = 0
        self.call_args: list[list[dict]] = []  # store message lists for inspection

    async def chat_completion(self, messages, *, request_id=None,
                              temperature=0.0, max_tokens=1024,
                              extra_body=None):
        self.call_args.append(messages)
        idx = min(self._idx, len(self._responses) - 1)
        content = self._responses[idx]
        self._idx += 1
        return _FakeGatingResponse(content=content, request_id=request_id or "fake")


def _make_gating_orch(plan_json: str, synthesis: str, tmp_path: Path):
    from app.orchestrator.orchestrator import Orchestrator
    from app.audit.logger import AuditLogger
    audit = AuditLogger(log_path=tmp_path / "audit.jsonl")
    client = _FakeOllamaClientGating([plan_json, synthesis])
    return Orchestrator(llm_client=client, audit_logger=audit), client


def _plan_has_generation_step(run) -> bool:
    """Return True if any step in the executed plan is a generation tool."""
    _GENERATION_TOOLS = {"generate_docx", "generate_pptx", "generate_xlsx"}
    for outcome in run.outcomes:
        if outcome.tool_name in _GENERATION_TOOLS:
            return True
    # Also check the planned steps (some may not have executed if plan is parsed only)
    for step in run.plan:
        if step.tool_name in _GENERATION_TOOLS:
            return True
    return False


class TestGenerationGating:
    """
    The most important test class — verifies the orchestrator gating logic
    in BOTH directions:
      (a) Chat-only goal → plan MUST NOT include a generation tool
      (b) Explicit generation goal → plan MUST include generate_docx
      (c) Ambiguous goal → defaults to no generation (conservative)
    """

    # ── Test 17: chat-only goal → NO generate_docx in plan ──────────────

    def test_chat_only_goal_does_not_produce_generate_docx(self, tmp_path):
        """
        'Summarize this inspection report' is a chat-only request.
        The model returns a plan without a generation step — and the orchestrator
        must NOT inject one. We script the fake client to return a chat-only plan.
        """
        # Script the LLM to return a plan with only file_read + no generation tools
        chat_plan = json.dumps([
            {
                "step_index": 0,
                "tool_name": "file_read",
                "tool_args": {"path": "/tmp/report.txt"},
                "description": "Read the inspection report"
            }
        ])
        synthesis = "The key findings are: F-001 (HIGH), F-002 (MEDIUM), F-003 (LOW)."

        orch, client = _make_gating_orch(chat_plan, synthesis, tmp_path)
        run = _run(orch.run("Summarize this inspection report"))

        assert not _plan_has_generation_step(run), (
            "Generation tool appeared in plan for a chat-only summarize goal — "
            f"plan steps: {[(s.tool_name) for s in run.plan]}"
        )

    # ── Test 18: explicit generation goal → generate_docx IS in plan ────

    def test_explicit_generation_goal_produces_generate_docx(self, tmp_path):
        """
        'Prepare an approval note from this report' explicitly requests a document.
        The LLM returns a plan including generate_docx, which must execute.
        """
        gen_plan = json.dumps([
            {
                "step_index": 0,
                "tool_name": "generate_docx",
                "tool_args": {
                    "document_type": "approval_note",
                    "approval_data": {
                        "date": "2026-09-01",
                        "to": "Chief Inspector R. Nair",
                        "from_": "Eng. Priya Sharma",
                        "reference_no": "AN-2026-047",
                        "subject_title": "Approval Note — MRPL CDU Inspection",
                        "background_context": "Quarterly inspection completed 2026-08-15.",
                        "proposal_request": "Authorise conditional restart at 85% throughput.",
                        "justification": "OISD-118 Cl. 4.3 requires approval before restart.",
                        "approved_by": "Chief Inspector R. Nair",
                        "financial_rows": [
                            {"budget_head": "Maintenance CAPEX", "estimated_cost": "INR 4,50,000"}
                        ],
                        "financial_total": "INR 4,50,000",
                        "initiated_by": "Eng. Priya Sharma",
                    },
                    "output_filename": "approval_note_2026_047.docx",
                    "request_id": "gate-test-018",
                },
                "description": "Generate the approval note Word document"
            }
        ])
        synthesis = "Approval note generated successfully at outputs/generated/approval_note_2026_047.docx"

        from app.orchestrator.state import OrchestratorStatus
        orch, _ = _make_gating_orch(gen_plan, synthesis, tmp_path)
        run = _run(orch.run("Prepare an approval note from this report"))

        assert _plan_has_generation_step(run), (
            "No generation tool in plan for explicit generation goal — "
            f"plan steps: {[s.tool_name for s in run.plan]}"
        )
        assert run.status == OrchestratorStatus.COMPLETED, \
            f"Run failed: {run.failure_summary}"
        # The generate_docx tool must have actually executed successfully
        gen_outcomes = [o for o in run.outcomes if o.tool_name == "generate_docx"]
        assert gen_outcomes, "generate_docx step not found in outcomes"
        assert gen_outcomes[0].success is True, \
            f"generate_docx failed: {gen_outcomes[0].error}"
        # Confirm the file was actually created
        output_path = Path(gen_outcomes[0].output)
        assert output_path.exists(), f"Generated file not found at {output_path}"
        assert output_path.suffix == ".docx"

    # ── Test 19: ambiguous goal → defaults to NO generation ─────────────

    def test_ambiguous_goal_defaults_to_no_generation(self, tmp_path):
        """
        'Check this inspection report against the SOP' is ambiguous — could
        want a report or a chat answer. The model returns a plan without any
        generation tool (correct conservative behaviour).
        """
        ambiguous_plan = json.dumps([
            {
                "step_index": 0,
                "tool_name": "file_read",
                "tool_args": {"path": "/tmp/report.txt"},
                "description": "Read the inspection report"
            },
            {
                "step_index": 1,
                "tool_name": "rag_search",
                "tool_args": {"query": "OISD-118 inspection corrective action requirements", "top_k": 3},
                "description": "Retrieve relevant SOP sections"
            }
        ])
        synthesis = "The report has 3 findings. F-001 (HIGH) must be resolved before restart per OISD-118 Cl. 4.3."

        orch, _ = _make_gating_orch(ambiguous_plan, synthesis, tmp_path)
        run = _run(orch.run("Check this inspection report against the SOP"))

        assert not _plan_has_generation_step(run), (
            "Generation tool appeared in plan for ambiguous goal — "
            "ambiguity should resolve to chat-only. "
            f"Plan steps: {[s.tool_name for s in run.plan]}"
        )

    # ── Test 20: gating rule text is present in the planning prompt ──────

    def test_gating_rules_present_in_planning_prompt(self):
        """
        The DELIVERABLE GENERATION RULES block must be present in the
        planning system prompt — confirms the instruction is embedded, not
        relying on implicit model behaviour.
        """
        from app.orchestrator.orchestrator import _PLANNING_SYSTEM_PROMPT

        assert "DELIVERABLE GENERATION RULES" in _PLANNING_SYSTEM_PROMPT, \
            "Gating rules block not found in _PLANNING_SYSTEM_PROMPT"
        assert "generate_docx" in _PLANNING_SYSTEM_PROMPT, \
            "generate_docx not mentioned in gating rules"
        assert "AMBIGUITY RULE" in _PLANNING_SYSTEM_PROMPT, \
            "AMBIGUITY RULE not found in planning prompt"
        assert "not unambiguously" in _PLANNING_SYSTEM_PROMPT or \
               "unambiguously asking for a file" in _PLANNING_SYSTEM_PROMPT, \
            "Ambiguity resolution instruction missing or incorrectly phrased"


# ===========================================================================
# 6. TestGenerateDocxRouting — backward-compat + new document_type routing
# ===========================================================================

class TestGenerateDocxRouting:
    """
    Confirms the updated generate_docx tool:
    - Still passes existing generic tests (backward compatibility)
    - Routes to inspection_report builder on document_type='inspection_report'
    - Routes to approval_note builder on document_type='approval_note'
    """

    def _make_tool(self, tmp_path):
        from app.tools.docgen.generate_docx import GenerateDocxTool
        return GenerateDocxTool(audit_logger=_make_audit(tmp_path))

    def test_generic_mode_still_works(self, tmp_path):
        """Backward compat: no document_type → generic builder, title required."""
        tool = self._make_tool(tmp_path)
        result = _run(tool.execute(
            title="Backward Compat Test",
            sections=[{"heading": "Section A", "body": "Some body text."}],
            output_filename="bw_compat.docx",
        ))
        assert result.success is True, f"Generic mode failed: {result.error}"
        assert result.metadata["document_type"] == "generic"

    def test_generic_mode_missing_title_fails(self, tmp_path):
        """Backward compat: missing title in generic mode → failure."""
        tool = self._make_tool(tmp_path)
        result = _run(tool.execute(
            sections=[],
            output_filename="out.docx",
        ))
        assert result.success is False
        assert "title" in result.error.lower()

    def test_inspection_report_mode_routes_correctly(self, tmp_path):
        """document_type='inspection_report' routes to the template-exact builder."""
        tool = self._make_tool(tmp_path)
        result = _run(tool.execute(
            document_type="inspection_report",
            inspection_data={
                "report_no": "TEST-001",
                "date_of_inspection": "2026-09-01",
                "facility_location": "Test Facility",
                "inspector_names": "Test Inspector",
                "equipment_area": "Unit 1",
                "objective": "Test objective text.",
                "observations": [
                    {"sl_no": "1", "checklist_item": "Fire suppression", "status": "Pass", "remarks": "OK"}
                ],
                "non_conformances": "None identified.",
                "corrective_actions": [
                    {"recommended_action": "No action", "responsibility": "N/A", "target_date": "N/A"}
                ],
            },
            output_filename="routing_test_insp.docx",
        ))
        assert result.success is True, f"inspection_report routing failed: {result.error}"
        assert result.metadata["document_type"] == "inspection_report"
        assert result.metadata["section_count"] == 4

        # Open and verify it has template-exact structure
        from docx import Document
        doc = Document(result.output)
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert any("INSPECTION REPORT" in h for h in headings)
        assert any("Facility Manager" in h for h in headings)

    def test_approval_note_mode_routes_correctly(self, tmp_path):
        """document_type='approval_note' routes to the template-exact builder."""
        tool = self._make_tool(tmp_path)
        result = _run(tool.execute(
            document_type="approval_note",
            approval_data={
                "date": "2026-09-01",
                "to": "Management",
                "from_": "Inspector",
                "reference_no": "AN-001",
                "subject_title": "Approval for restart",
                "financial_rows": [
                    {"budget_head": "CAPEX", "estimated_cost": "100000"}
                ],
                "financial_total": "100000",
            },
            output_filename="routing_test_an.docx",
        ))
        assert result.success is True, f"approval_note routing failed: {result.error}"
        assert result.metadata["document_type"] == "approval_note"
        assert result.metadata["section_count"] == 5

        from docx import Document
        doc = Document(result.output)
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert any("APPROVAL NOTE" in h for h in headings)
        assert any("Approved By" in h for h in headings)
        assert any("Initiated By" in h for h in headings)
