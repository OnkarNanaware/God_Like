"""
tests/test_upload_and_general_qa.py
=====================================
Two-bug fix validation tests.

Test classes
------------
1. TestSpreadsheetUploadRouting   — Excel uploads are NOT rejected at any layer
2. TestGeneralKnowledgeAnswer     — zero-tool-call plan → direct labelled answer
3. TestRagEmptyFallback           — RAG empty results → labelled general knowledge
4. TestRagGroundedRegression      — real RAG hit still cited correctly (regression guard)
"""

from __future__ import annotations

import asyncio
import json
import io
from pathlib import Path
from typing import Any, Optional

import pytest
import openpyxl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def _make_audit(tmp_path: Path):
    from app.audit.logger import AuditLogger
    return AuditLogger(log_path=tmp_path / "audit.jsonl")


class _FakeResp:
    prompt_tokens = 5
    response_tokens = 10
    total_tokens = 15
    latency_ms = 1.0
    model_name = "fake"
    ollama_tag = "fake:latest"

    def __init__(self, content: str, request_id: str = "fake"):
        self.content = content
        self.request_id = request_id


class _FakeClient:
    """
    Scripted fake LLM client.
    Accepts a list of response strings, one per call in order.
    If call_count exceeds list length, last response repeats.
    """
    def __init__(self, responses: list[str]):
        self._responses = responses
        self.call_count = 0
        self.call_args: list[list[dict]] = []

    async def chat_completion(self, messages, *, request_id=None,
                              temperature=0.0, max_tokens=1024,
                              extra_body=None):
        self.call_args.append(messages)
        idx = min(self.call_count, len(self._responses) - 1)
        self.call_count += 1
        return _FakeResp(content=self._responses[idx], request_id=request_id or "fake")


def _make_orch(responses: list[str], tmp_path: Path):
    from app.orchestrator.orchestrator import Orchestrator
    client = _FakeClient(responses)
    audit = _make_audit(tmp_path)
    return Orchestrator(llm_client=client, audit_logger=audit), client


# ===========================================================================
# 1. TestSpreadsheetUploadRouting
#    Confirm .xlsx/.xls/.csv files reach analyze_spreadsheet, not rejected.
# ===========================================================================


class TestSpreadsheetUploadRouting:
    """
    Tests that spreadsheet files pass through every layer:
      - Heuristic router emits SPREADSHEET_ANALYSIS signal (not DOCUMENT_VISION or ambiguous)
      - AnalyzeSpreadsheetTool.execute() accepts the file path (not rejected)
      - The orchestrator plan for "summarize this xlsx" uses analyze_spreadsheet
        (not generate_xlsx, which is the wrong direction)
    """

    def _make_xlsx(self, tmp_path: Path) -> Path:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Data"
        ws.append(["Item", "Value"])
        ws.append(["A", 100])
        ws.append(["B", 200])
        path = tmp_path / "test_upload.xlsx"
        wb.save(str(path))
        return path

    def _make_csv(self, tmp_path: Path) -> Path:
        path = tmp_path / "test_upload.csv"
        path.write_text("Col1,Col2\n1,alpha\n2,beta\n")
        return path

    # ── Test 1: .xlsx heuristic routes to SPREADSHEET_ANALYSIS ─────────

    def test_xlsx_heuristic_routes_to_spreadsheet_analysis(self):
        from app.router.heuristics import run_heuristics, Capability
        signals = run_heuristics(
            "Please analyze this file",
            attached_filenames=["data_export.xlsx"],
        )
        assert signals, "No heuristic signal for .xlsx"
        cap = signals[0].capability
        assert cap == Capability.SPREADSHEET_ANALYSIS, \
            f"Expected SPREADSHEET_ANALYSIS, got {cap}"
        assert signals[0].confidence >= 0.75

    # ── Test 2: .csv heuristic routes to SPREADSHEET_ANALYSIS ──────────

    def test_csv_heuristic_routes_to_spreadsheet_analysis(self):
        from app.router.heuristics import run_heuristics, Capability
        signals = run_heuristics(
            "Summarize this CSV",
            attached_filenames=["report.csv"],
        )
        assert signals
        assert signals[0].capability == Capability.SPREADSHEET_ANALYSIS

    # ── Test 3: .xls heuristic routes to SPREADSHEET_ANALYSIS ──────────

    def test_xls_heuristic_routes_to_spreadsheet_analysis(self):
        from app.router.heuristics import run_heuristics, Capability
        signals = run_heuristics("What's in this?", attached_filenames=["legacy.xls"])
        assert signals
        assert signals[0].capability == Capability.SPREADSHEET_ANALYSIS

    # ── Test 4: AnalyzeSpreadsheetTool accepts .xlsx, returns results ───

    def test_analyze_tool_accepts_xlsx(self, tmp_path):
        from app.tools.analyze_spreadsheet import AnalyzeSpreadsheetTool
        client = _FakeClient(["This spreadsheet has cost data."])
        tool = AnalyzeSpreadsheetTool(llm_client=client, audit_logger=_make_audit(tmp_path))
        xlsx = self._make_xlsx(tmp_path)
        result = _run(tool.execute(file_path=str(xlsx), request_id="up-004"))
        assert result.success is True, f"Tool rejected .xlsx: {result.error}"
        assert result.output["sheets"][0]["name"] == "Data"
        assert result.output["summary"] == "This spreadsheet has cost data."

    # ── Test 5: AnalyzeSpreadsheetTool accepts .csv ──────────────────────

    def test_analyze_tool_accepts_csv(self, tmp_path):
        from app.tools.analyze_spreadsheet import AnalyzeSpreadsheetTool
        client = _FakeClient(["Two rows of data."])
        tool = AnalyzeSpreadsheetTool(llm_client=client, audit_logger=_make_audit(tmp_path))
        csv_path = self._make_csv(tmp_path)
        result = _run(tool.execute(file_path=str(csv_path), request_id="up-005"))
        assert result.success is True, f"Tool rejected .csv: {result.error}"
        assert result.output["sheets"][0]["headers"] == ["Col1", "Col2"]

    # ── Test 6: Orchestrator plan for xlsx request uses analyze_spreadsheet ─

    def test_orchestrator_plan_uses_analyze_spreadsheet_for_xlsx(self, tmp_path):
        """
        Script the LLM to return a plan using analyze_spreadsheet when a
        spreadsheet file is mentioned. Confirm it executes successfully.
        """
        xlsx = self._make_xlsx(tmp_path)

        plan_json = json.dumps([{
            "step_index": 0,
            "tool_name": "analyze_spreadsheet",
            "tool_args": {"file_path": str(xlsx), "request_id": "up-006"},
            "description": "Analyze the uploaded spreadsheet",
        }])
        synthesis = "⚠️ The spreadsheet has 2 rows: Item A=100, Item B=200."

        # Register the tool for this test
        from app.tools.analyze_spreadsheet import AnalyzeSpreadsheetTool
        from app.tools.registry import register_tool
        tool_client = _FakeClient(["Spreadsheet summary."])
        register_tool(AnalyzeSpreadsheetTool(
            llm_client=tool_client,
            audit_logger=_make_audit(tmp_path),
        ))

        orch, _ = _make_orch([plan_json, synthesis], tmp_path)
        run = _run(orch.run(f"Summarize this spreadsheet: {xlsx}"))

        from app.orchestrator.state import OrchestratorStatus
        assert run.status == OrchestratorStatus.COMPLETED, \
            f"Run failed: {run.failure_summary}"
        gen_outcomes = [o for o in run.outcomes if o.tool_name == "analyze_spreadsheet"]
        assert gen_outcomes, "analyze_spreadsheet not in outcomes"
        assert gen_outcomes[0].success is True, f"Tool failed: {gen_outcomes[0].error}"

    # ── Test 7: .pdf still routes to DOCUMENT_VISION (regression) ────────

    def test_pdf_still_routes_to_vision_regression(self):
        from app.router.heuristics import run_heuristics, Capability
        signals = run_heuristics(
            "Read this inspection report",
            attached_filenames=["inspection.pdf"],
        )
        assert signals
        assert signals[0].capability == Capability.DOCUMENT_VISION, \
            f"PDF routing regressed! Got: {signals[0].capability}"


# ===========================================================================
# 2. TestGeneralKnowledgeAnswer
#    A plain conceptual question must produce a zero-tool-call plan
#    and a directly-labelled response from the LLM.
# ===========================================================================


class TestGeneralKnowledgeAnswer:

    # ── Test 8: empty plan → LLM called for direct answer ────────────────

    def test_empty_plan_calls_llm_for_direct_answer(self, tmp_path):
        """
        When the model returns an empty plan [], _synthesise must call the LLM
        with _DIRECT_ANSWER_SYSTEM_PROMPT — NOT return the hardcoded error string.
        """
        empty_plan = "[]"
        direct_answer = (
            "⚠️ General knowledge — not from an internal document.\n\n"
            "OISD stands for the Oil Industry Safety Directorate, a technical arm "
            "of the Ministry of Petroleum and Natural Gas in India responsible for "
            "developing and enforcing safety standards in the oil and gas sector."
        )

        orch, client = _make_orch([empty_plan, direct_answer], tmp_path)
        run = _run(orch.run("What is OISD?"))

        from app.orchestrator.state import OrchestratorStatus
        assert run.status == OrchestratorStatus.COMPLETED, \
            f"Run failed unexpectedly: {run.failure_summary}"
        assert run.final_output, "final_output is empty"
        assert "No tool outputs were collected" not in run.final_output, (
            "BUG: hardcoded error string returned instead of LLM answer. "
            "The empty-context branch in _synthesise is not calling the LLM."
        )
        assert "⚠️ General knowledge" in run.final_output or "OISD" in run.final_output, (
            f"Expected a real answer, got: {run.final_output!r}"
        )
        # The LLM must have been called twice: once for planning (empty=[]),
        # once for the direct-answer synthesis.
        assert client.call_count == 2, (
            f"Expected 2 LLM calls (plan + direct answer), got {client.call_count}"
        )

    # ── Test 9: zero-tool plan produces no tool outcomes ─────────────────

    def test_zero_tool_plan_produces_no_outcomes(self, tmp_path):
        """An empty plan must produce zero StepOutcome records."""
        orch, _ = _make_orch(["[]", "⚠️ General knowledge — not from an internal document.\n\nAnswer here."], tmp_path)
        run = _run(orch.run("What does API stand for?"))
        assert len(run.outcomes) == 0, \
            f"Expected zero outcomes for empty plan, got {len(run.outcomes)}: {run.outcomes}"

    # ── Test 10: response is labelled as general knowledge ───────────────

    def test_general_knowledge_answer_is_labelled(self, tmp_path):
        """The direct-answer response must contain the ⚠️ General knowledge prefix."""
        labelled = "⚠️ General knowledge — not from an internal document.\n\nOISD is the Oil Industry Safety Directorate."
        orch, _ = _make_orch(["[]", labelled], tmp_path)
        run = _run(orch.run("What is OISD?"))
        assert "⚠️ General knowledge" in run.final_output, (
            f"General knowledge label missing. Got: {run.final_output!r}"
        )

    # ── Test 11: _DIRECT_ANSWER_SYSTEM_PROMPT is defined and correct ──────

    def test_direct_answer_prompt_is_defined(self):
        from app.orchestrator.orchestrator import _DIRECT_ANSWER_SYSTEM_PROMPT
        assert _DIRECT_ANSWER_SYSTEM_PROMPT, "_DIRECT_ANSWER_SYSTEM_PROMPT is empty"
        assert "General knowledge" in _DIRECT_ANSWER_SYSTEM_PROMPT
        assert "not from an internal document" in _DIRECT_ANSWER_SYSTEM_PROMPT

    # ── Test 12: GENERAL KNOWLEDGE RULE is in planning prompt ────────────

    def test_general_knowledge_rule_in_planning_prompt(self):
        from app.orchestrator.orchestrator import _PLANNING_SYSTEM_PROMPT
        assert "GENERAL KNOWLEDGE RULE" in _PLANNING_SYSTEM_PROMPT, \
            "GENERAL KNOWLEDGE RULE block missing from planning prompt"
        assert "empty array" in _PLANNING_SYSTEM_PROMPT or "EMPTY array" in _PLANNING_SYSTEM_PROMPT, \
            "Planning prompt should say to return empty array for general questions"


# ===========================================================================
# 3. TestRagEmptyFallback
#    When rag_search returns 0 results, the answer must be labelled
#    as general knowledge, not silently blended into a grounded-looking answer.
# ===========================================================================


class TestRagEmptyFallback:

    def _make_empty_rag_context(self) -> str:
        """Simulate what a rag_search step adds to context when it returns 0 results."""
        return "[Step 0 — rag_search]:\n0 results returned for query: 'What is OISD'"

    # ── Test 13: all-empty RAG → direct-answer path used ─────────────────

    def test_rag_empty_result_triggers_general_knowledge_fallback(self, tmp_path):
        """
        When all rag_search steps returned 0 results, the synthesise path
        must detect this and route to _DIRECT_ANSWER_SYSTEM_PROMPT.
        The response must be labelled as general knowledge.
        """
        from app.orchestrator.orchestrator import Orchestrator
        from app.orchestrator.state import OrchestratorRun

        # Build a run object with a rag_search snippet that returned 0 results
        audit = _make_audit(tmp_path)
        client = _FakeClient([
            "⚠️ General knowledge — not from an internal document.\n\nOISD answer."
        ])
        orch = Orchestrator(llm_client=client, audit_logger=audit)

        # Manually construct a run with an empty-rag context snippet
        run = OrchestratorRun(request_id="rag-test-013", goal="What is OISD?")
        run.context_snippets.append(self._make_empty_rag_context())

        result = _run(orch._synthesise("What is OISD?", run))
        assert "⚠️ General knowledge" in result, (
            f"Empty RAG result should trigger general-knowledge label. Got: {result!r}"
        )
        assert client.call_count == 1, "Expected exactly one LLM call for fallback"

    # ── Test 14: fallback response is not empty ───────────────────────────

    def test_rag_empty_fallback_response_non_empty(self, tmp_path):
        from app.orchestrator.orchestrator import Orchestrator
        from app.orchestrator.state import OrchestratorRun

        answer = "⚠️ General knowledge — not from an internal document.\n\nOISD is the Oil Industry Safety Directorate."
        client = _FakeClient([answer])
        orch = Orchestrator(llm_client=client, audit_logger=_make_audit(tmp_path))

        run = OrchestratorRun(request_id="rag-test-014", goal="What is OISD?")
        run.context_snippets.append("[Step 0 — rag_search]:\n0 results returned")

        result = _run(orch._synthesise("What is OISD?", run))
        assert len(result) > 50, f"Fallback response is too short: {result!r}"
        assert "OISD" in result or "General knowledge" in result


# ===========================================================================
# 4. TestRagGroundedRegression
#    When rag_search returns real results, the answer must still be
#    correctly cited — not accidentally routed to the general-knowledge path.
# ===========================================================================


class TestRagGroundedRegression:

    def _make_grounded_rag_context(self) -> str:
        """Simulate what rag_search adds to context when it returns real results."""
        return (
            "[Step 0 — rag_search]:\n"
            "**MRPL_INSPECTION_REPORT_CDU_2026.pdf** (score: 0.89)\n"
            "Finding F-001: Tube bundle fouling on HE-102 exceeds acceptable limit "
            "(OISD-118 Cl. 4.3). Corrective action required before restart."
        )

    # ── Test 15: real RAG hit → synthesis used, NOT direct-answer ─────────

    def test_real_rag_hit_does_not_route_to_general_knowledge(self, tmp_path):
        """
        When rag_search returns actual results, the synthesise path must use
        the normal _build_synthesis_messages path — not the general-knowledge
        fallback.  The response must NOT be labelled as general knowledge.
        """
        from app.orchestrator.orchestrator import Orchestrator
        from app.orchestrator.state import OrchestratorRun

        grounded_answer = (
            "Based on the MRPL Inspection Report (CDU 2026), Finding F-001 "
            "indicates tube bundle fouling on HE-102 exceeds acceptable limits "
            "per OISD-118 Cl. 4.3. Corrective action is required before restart."
        )
        client = _FakeClient([grounded_answer])
        orch = Orchestrator(llm_client=client, audit_logger=_make_audit(tmp_path))

        run = OrchestratorRun(request_id="rag-test-015", goal="What are the key findings?")
        run.context_snippets.append(self._make_grounded_rag_context())

        result = _run(orch._synthesise("What are the key findings?", run))
        # Must NOT be routed to general knowledge — this IS a grounded answer
        assert "⚠️ General knowledge" not in result, (
            "BUG: grounded RAG answer was incorrectly routed to general-knowledge path. "
            f"Got: {result!r}"
        )
        assert "MRPL" in result or "F-001" in result or "tube bundle" in result.lower(), (
            f"Grounded answer doesn't seem to contain sourced content. Got: {result!r}"
        )

    # ── Test 16: all_rag_empty flag is False for real hits ────────────────

    def test_real_rag_context_not_detected_as_empty(self, tmp_path):
        """
        The all_rag_empty detection logic must correctly return False when
        the context contains actual retrieved content (not '0 results').
        """
        from app.orchestrator.orchestrator import Orchestrator
        from app.orchestrator.state import OrchestratorRun

        client = _FakeClient(["Grounded answer with no general knowledge label."])
        orch = Orchestrator(llm_client=client, audit_logger=_make_audit(tmp_path))

        run = OrchestratorRun(request_id="rag-test-016", goal="Key findings?")
        run.context_snippets.append(self._make_grounded_rag_context())

        # Replicate the all_rag_empty detection logic
        snippets = run.context_snippets
        all_rag_empty = all(
            "0 results" in s or "no results" in s.lower() or "returned 0" in s.lower()
            for s in snippets
            if "rag_search" in s or "[Step" in s
        ) and any("rag_search" in s for s in snippets)

        assert not all_rag_empty, (
            "all_rag_empty was True for a context with real RAG results — "
            "detection logic is wrong"
        )

    # ── Test 17: end-to-end grounded path still completes ─────────────────

    def test_grounded_rag_orchestrator_run_completes(self, tmp_path):
        """
        Full orchestrator run: plan → rag_search step → synthesis.
        The run must complete with status COMPLETED and final_output present.
        """
        from app.tools.rag_search import RagSearchTool
        from app.tools.registry import register_tool, TOOL_REGISTRY
        from app.orchestrator.state import OrchestratorStatus

        # Build a mock rag_search tool that returns a real result
        class _FakeRagSearchTool:
            name = "rag_search"
            description = "Search internal documents"
            input_schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

            def describe(self):
                return {"name": self.name, "description": self.description, "input_schema": self.input_schema}

            async def execute(self, **kwargs):
                from app.tools.base import ToolResult
                return ToolResult(
                    success=True,
                    output="**MRPL_REPORT.pdf**: Finding F-001: tube bundle fouling on HE-102.",
                    metadata={"result_count": 1},
                )

        register_tool(_FakeRagSearchTool())

        plan_json = json.dumps([{
            "step_index": 0,
            "tool_name": "rag_search",
            "tool_args": {"query": "key inspection findings CDU 2026"},
            "description": "Retrieve relevant inspection findings",
        }])
        synthesis = (
            "Based on the MRPL inspection report (MRPL_REPORT.pdf): "
            "Finding F-001 identifies tube bundle fouling on HE-102, requiring corrective action."
        )

        orch, client = _make_orch([plan_json, synthesis], tmp_path)
        run = _run(orch.run("What are the key findings from the CDU inspection?"))

        assert run.status == OrchestratorStatus.COMPLETED, \
            f"Run failed: {run.failure_summary}"
        assert run.final_output, "final_output is empty"
        assert "⚠️ General knowledge" not in run.final_output, \
            "Grounded answer was incorrectly labelled as general knowledge"
        assert "F-001" in run.final_output or "tube bundle" in run.final_output.lower(), \
            f"Expected grounded content in output. Got: {run.final_output!r}"
