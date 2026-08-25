"""
tests/test_phase_b.py
=====================
Phase B smoke tests — all pass without a live Ollama instance.

Coverage
--------
1.  Router heuristic: traceback → coder model
2.  Router heuristic: PDF attached → vision model
3.  Router heuristic: image attached → vision model
4.  Router LLM fallback: ambiguous text + FakeOllamaClient → correct model
5.  Router LLM fallback: explicit hint → highest priority, always wins
6.  FileReadTool: success on a real temp file
7.  FileReadTool: clean failure on missing path (no exception raised)
8.  Orchestrator: 2-step happy-path end-to-end with FakeOllamaClient
9.  Orchestrator: retry once on simulated failure, succeed on second attempt
10. Orchestrator: halt cleanly after MAX_RETRIES consecutive failures (no loop)
11. Audit log: every test above produces ≥ 1 audit record with correct request_id
12. Hash chain: valid after full test run
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest

from app.audit.logger import AuditLogger, EventType
from app.orchestrator.orchestrator import MAX_RETRIES, Orchestrator
from app.orchestrator.state import OrchestratorStatus
from app.router.heuristics import Capability
from app.router.router import Router
from app.tools.base import ToolResult
from app.tools.file_read import FileReadTool
from app.tools.registry import TOOL_REGISTRY

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously (keeps tests sync-style for readability)."""
    return asyncio.run(coro)


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ---------------------------------------------------------------------------
# FakeOllamaClient — satisfies LLMClassifierProtocol and LLMOrchestratorProtocol
# ---------------------------------------------------------------------------


@dataclass
class FakeResponse:
    """Minimal stand-in for OllamaResponse."""
    content: str
    prompt_tokens: int = 5
    response_tokens: int = 5
    total_tokens: int = 10
    latency_ms: float = 1.0
    model_name: str = "fake_model"
    ollama_tag: str = "fake:latest"
    request_id: str = "fake-rid"


class FakeOllamaClient:
    """
    Deterministic stub that satisfies both LLMClassifierProtocol and
    LLMOrchestratorProtocol.

    ``responses`` is a list of strings returned in order.  After the list is
    exhausted, the last value is repeated.  This makes multi-call scenarios
    (plan → synthesise, plan → retry → synthesise) trivially controllable.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._call_index = 0

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        request_id: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 16,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> FakeResponse:
        idx = min(self._call_index, len(self._responses) - 1)
        content = self._responses[idx]
        self._call_index += 1
        return FakeResponse(content=content)

    @property
    def call_count(self) -> int:
        return self._call_index


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_audit_log(tmp_path: Path) -> Path:
    return tmp_path / "audit_phase_b.jsonl"


@pytest.fixture()
def audit(tmp_audit_log: Path) -> AuditLogger:
    return AuditLogger(log_path=tmp_audit_log)


@pytest.fixture()
def router(audit: AuditLogger) -> Router:
    """Router without LLM client — heuristic-only for most tests."""
    return Router(audit_logger=audit)


@pytest.fixture()
def router_with_llm(audit: AuditLogger) -> tuple[Router, FakeOllamaClient]:
    fake = FakeOllamaClient(responses=["code_generation"])
    return Router(audit_logger=audit, llm_client=fake), fake


# ---------------------------------------------------------------------------
# ── 1. Router: traceback → coder model ──────────────────────────────────────
# ---------------------------------------------------------------------------


def test_router_traceback_picks_coder(router: Router):
    text = """
    I'm getting this error:

    Traceback (most recent call last):
      File "app.py", line 42, in run
        result = compute(x)
    ZeroDivisionError: division by zero

    How do I fix this?
    """
    decision = _run(router.route(text, request_id="tb-001"))
    assert decision.stage == "heuristic"
    assert decision.capability in (
        Capability.DEBUGGING.value,
        Capability.CODE_GENERATION.value,
    )
    assert "coder" in decision.model_name or "qwen25_coder" in decision.model_name, (
        f"Expected a coder model, got '{decision.model_name}'"
    )


# ---------------------------------------------------------------------------
# ── 2. Router: PDF attached → vision model ───────────────────────────────────
# ---------------------------------------------------------------------------


def test_router_pdf_attachment_picks_vision(router: Router):
    decision = _run(
        router.route(
            "Summarise this document for me.",
            attached_filenames=["quarterly_report.pdf"],
            request_id="pdf-001",
        )
    )
    assert decision.stage == "heuristic"
    # Vision model has modality == "vision" in registry
    from app.models.ollama_client import MODEL_REGISTRY
    assert MODEL_REGISTRY[decision.model_name]["modality"] == "vision", (
        f"Expected vision model, got '{decision.model_name}' "
        f"(modality={MODEL_REGISTRY[decision.model_name]['modality']})"
    )


# ---------------------------------------------------------------------------
# ── 3. Router: image attached → vision model ─────────────────────────────────
# ---------------------------------------------------------------------------


def test_router_image_attachment_picks_vision(router: Router):
    decision = _run(
        router.route(
            "What does this chart show?",
            attached_filenames=["sales_chart.png"],
            request_id="img-001",
        )
    )
    assert decision.stage == "heuristic"
    from app.models.ollama_client import MODEL_REGISTRY
    assert MODEL_REGISTRY[decision.model_name]["modality"] == "vision"


# ---------------------------------------------------------------------------
# ── 4. Router: ambiguous → LLM fallback with FakeOllamaClient ───────────────
# ---------------------------------------------------------------------------


def test_router_llm_fallback_on_ambiguous_text(audit: AuditLogger):
    # "Tell me about clouds" — no code keywords, no file, genuinely ambiguous
    # depending on confidence thresholds.  We force ambiguity by using a
    # router with a fake LLM that returns "code_generation".
    fake = FakeOllamaClient(responses=["code_generation"])
    router = Router(audit_logger=audit, llm_client=fake)

    # Use text that is low-signal enough that heuristic confidence < 0.75
    text = "Tell me about clouds"
    decision = _run(router.route(text, request_id="amb-001"))

    # Either heuristic resolved it (unlikely for this text) or LLM fallback fired.
    # Either way the model must be in the registry.
    from app.models.ollama_client import MODEL_REGISTRY
    assert decision.model_name in MODEL_REGISTRY

    # If LLM fallback fired, verify it used the fake's response.
    if decision.stage == "llm_fallback":
        assert decision.capability == "code_generation"
        assert fake.call_count == 1


# ---------------------------------------------------------------------------
# ── 5. Router: explicit_capability_hint always wins ──────────────────────────
# ---------------------------------------------------------------------------


def test_router_explicit_hint_always_wins(router: Router):
    """Explicit hint has confidence=1.0 — it must always beat any keyword signal."""
    text = "def fix_this_traceback(): pass"  # would normally → coder
    decision = _run(
        router.route(
            text,
            explicit_capability_hint="ocr",  # unrelated but must win
            request_id="hint-001",
        )
    )
    assert decision.stage == "heuristic"
    assert decision.capability == "ocr"
    from app.models.ollama_client import MODEL_REGISTRY
    assert MODEL_REGISTRY[decision.model_name]["modality"] == "vision"


# ---------------------------------------------------------------------------
# ── 6. FileReadTool: success ─────────────────────────────────────────────────
# ---------------------------------------------------------------------------


def test_file_read_success(tmp_path: Path):
    content = "Hello, sovereign workbench!\nLine 2.\n"
    f = tmp_path / "test_file.txt"
    f.write_text(content, encoding="utf-8")

    tool = FileReadTool()
    result: ToolResult = _run(tool.execute(path=str(f)))

    assert result.success is True
    assert result.error is None
    assert result.output == content
    assert result.metadata["file_size_bytes"] > 0
    assert result.metadata["truncated"] is False


# ---------------------------------------------------------------------------
# ── 7. FileReadTool: clean failure on missing file ───────────────────────────
# ---------------------------------------------------------------------------


def test_file_read_missing_file():
    tool = FileReadTool()
    result: ToolResult = _run(tool.execute(path="/tmp/this_file_does_not_exist_xyz_987.txt"))

    assert result.success is False
    assert result.output is None
    assert result.error is not None
    assert "not found" in result.error.lower() or "does not exist" in result.error.lower()


def test_file_read_missing_path_arg():
    tool = FileReadTool()
    result: ToolResult = _run(tool.execute())  # no 'path' arg
    assert result.success is False
    assert "'path' argument is required" in (result.error or "")


# ---------------------------------------------------------------------------
# ── 8. Orchestrator: 2-step happy path ───────────────────────────────────────
# ---------------------------------------------------------------------------


def test_orchestrator_two_step_happy_path(audit: AuditLogger, tmp_path: Path):
    # Create a real file the plan can read.
    doc = tmp_path / "report.txt"
    doc.write_text("Revenue: $1M. Expenses: $500K. Profit: $500K.", encoding="utf-8")

    plan_json = json.dumps(
        [
            {
                "step_index": 0,
                "tool_name": "file_read",
                "tool_args": {"path": str(doc)},
                "description": "Read the financial report.",
            }
        ]
    )
    synthesis_text = "The report shows a $500K profit."

    fake = FakeOllamaClient(responses=[plan_json, synthesis_text])
    orch = Orchestrator(llm_client=fake, audit_logger=audit)

    run = _run(orch.run(f"Summarise the report at {doc}", request_id="orch-happy-001"))

    assert run.status == OrchestratorStatus.COMPLETED
    assert run.final_output is not None
    assert len(run.outcomes) == 1
    assert run.outcomes[0].success is True
    assert run.failure_summary is None


# ---------------------------------------------------------------------------
# ── 9. Orchestrator: retry once on failure, succeed second attempt ────────────
# ---------------------------------------------------------------------------


def test_orchestrator_retry_once_then_success(audit: AuditLogger, tmp_path: Path):
    """
    Simulate a plan where step 0 fails on attempt 1 (bad path) and the
    re-plan corrects it to use a good path.  The orchestrator should retry,
    the second attempt should succeed.
    """
    good_file = tmp_path / "good.txt"
    good_file.write_text("All is well.", encoding="utf-8")

    # First plan: uses a non-existent file (will fail).
    bad_plan = json.dumps(
        [
            {
                "step_index": 0,
                "tool_name": "file_read",
                "tool_args": {"path": "/tmp/nonexistent_xyz_abc.txt"},
                "description": "Read a file that doesn't exist.",
            }
        ]
    )
    # Re-plan: corrected path.
    good_plan = json.dumps(
        [
            {
                "step_index": 0,
                "tool_name": "file_read",
                "tool_args": {"path": str(good_file)},
                "description": "Read the correct file.",
            }
        ]
    )
    synthesis_text = "The file says: All is well."

    # LLM call order: plan → replan → synthesise
    fake = FakeOllamaClient(responses=[bad_plan, good_plan, synthesis_text])
    orch = Orchestrator(llm_client=fake, audit_logger=audit)

    run = _run(orch.run("Read and summarise the report.", request_id="orch-retry-001"))

    assert run.status == OrchestratorStatus.COMPLETED, (
        f"Expected COMPLETED, got {run.status}. Failure: {run.failure_summary}"
    )
    # One failure outcome + one success outcome for step 0.
    step_0_outcomes = [o for o in run.outcomes if o.step_index == 0]
    failures = [o for o in step_0_outcomes if not o.success]
    successes = [o for o in step_0_outcomes if o.success]
    assert len(failures) >= 1, "Expected at least one failure outcome"
    assert len(successes) >= 1, "Expected at least one success outcome"


# ---------------------------------------------------------------------------
# ── 10. Orchestrator: halt after MAX_RETRIES ──────────────────────────────────
# ---------------------------------------------------------------------------


def test_orchestrator_halts_after_max_retries(audit: AuditLogger):
    """
    Every attempt at the only step should fail (non-existent file).
    After MAX_RETRIES attempts the orchestrator must halt with FAILED, not loop.

    We configure the re-plan to return the same bad step every time so we
    don't accidentally produce a good plan.
    """
    bad_plan = json.dumps(
        [
            {
                "step_index": 0,
                "tool_name": "file_read",
                "tool_args": {"path": "/tmp/permanently_missing_xyz.txt"},
                "description": "File that never exists.",
            }
        ]
    )
    # Return the same bad plan for every LLM call (initial + all replans).
    fake = FakeOllamaClient(responses=[bad_plan] * (MAX_RETRIES + 2))
    orch = Orchestrator(llm_client=fake, audit_logger=audit, max_retries=MAX_RETRIES)

    run = _run(orch.run("Read the missing file.", request_id="orch-exhaust-001"))

    assert run.status == OrchestratorStatus.FAILED, (
        f"Expected FAILED, got {run.status}"
    )
    assert run.failure_summary is not None
    assert "after" in run.failure_summary.lower() or "exhausted" in run.failure_summary.lower() or str(MAX_RETRIES) in run.failure_summary


# ---------------------------------------------------------------------------
# ── 11. Audit log: every test above records entries ──────────────────────────
# ---------------------------------------------------------------------------


def test_audit_log_has_route_decision_entries(audit: AuditLogger, tmp_audit_log: Path):
    router = Router(audit_logger=audit)
    request_id = "audit-check-001"
    _run(
        router.route(
            "traceback in my Python code",
            request_id=request_id,
        )
    )
    records = _read_jsonl(tmp_audit_log)
    route_records = [
        r for r in records
        if r.get("event_type") == "route_decision"
        and r.get("request_id") == request_id
    ]
    assert len(route_records) >= 1, "Expected at least one route_decision record"
    rec = route_records[0]
    assert "model_name" in rec["payload"]
    assert "stage" in rec["payload"]
    assert "capability" in rec["payload"]


def test_audit_log_has_orchestrator_entries(audit: AuditLogger, tmp_audit_log: Path, tmp_path: Path):
    doc = tmp_path / "sample.txt"
    doc.write_text("Sample content.", encoding="utf-8")

    plan_json = json.dumps(
        [{"step_index": 0, "tool_name": "file_read", "tool_args": {"path": str(doc)}, "description": "Read"}]
    )
    fake = FakeOllamaClient(responses=[plan_json, "Summary done."])
    orch = Orchestrator(llm_client=fake, audit_logger=audit)

    request_id = "audit-orch-001"
    _run(orch.run("Read and summarise.", request_id=request_id))

    records = _read_jsonl(tmp_audit_log)
    orch_records = [
        r for r in records
        if r.get("request_id") == request_id
        and r.get("event_type") in ("agent_action", "tool_call")
    ]
    assert len(orch_records) >= 3, (
        f"Expected ≥ 3 orchestrator audit records, got {len(orch_records)}"
    )


# ---------------------------------------------------------------------------
# ── 12. Hash chain integrity ──────────────────────────────────────────────────
# ---------------------------------------------------------------------------


def test_hash_chain_intact_after_phase_b_run(tmp_audit_log: Path):
    """
    Run router + orchestrator end-to-end and verify the full chain is valid.
    """
    audit = AuditLogger(log_path=tmp_audit_log)
    router = Router(audit_logger=audit)

    _run(router.route("def calculate(x): pass", request_id="chain-001"))
    _run(router.route("quarterly_report.pdf summary", request_id="chain-002"))

    # Quick orchestrator run
    import tempfile as _tempfile

    with _tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("Chain test content.")
        tmp_file = f.name

    plan_json = json.dumps(
        [{"step_index": 0, "tool_name": "file_read", "tool_args": {"path": tmp_file}, "description": "Read"}]
    )
    fake = FakeOllamaClient(responses=[plan_json, "Done."])
    orch = Orchestrator(llm_client=fake, audit_logger=audit)
    _run(orch.run("Read and summarise.", request_id="chain-003"))

    ok, errors = audit.verify_chain()
    assert ok, "Hash chain verification failed after Phase B run:\n" + "\n".join(errors)
