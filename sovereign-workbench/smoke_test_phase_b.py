#!/usr/bin/env python3
"""
smoke_test_phase_b.py
=====================
Real-model end-to-end smoke test for Phase B.

Prerequisites
-------------
1. `ollama serve` is running.
2. The following models are pulled:
   - qwen2.5:14b-instruct-q4_K_M   (used for planning + synthesis)

What this does
--------------
1. Creates a temp file with known content.
2. Instantiates the Router with a real OllamaClient.
3. Routes the goal ("read this file and summarise it") → heuristic stage → text model.
4. Instantiates the Orchestrator with the same real OllamaClient.
5. Runs the orchestrator — expects it to plan a file_read step, execute it,
   and synthesise a real model-generated summary.
6. Prints the routing decision and final output.
7. Verifies the audit log has the correct event types and the chain is intact.
8. Exits 0 on success, 1 on any failure.

Run with:
    source .venv/bin/activate
    python smoke_test_phase_b.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap — ensure the app package is importable from this script's dir.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from app.audit.logger import AuditLogger
from app.models.ollama_client import OllamaClient
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.state import OrchestratorStatus
from app.router.router import Router

AUDIT_PATH = Path("logs/smoke_b_audit.jsonl")
REQUEST_ID = "smoke-phase-b-001"

_BANNER = "=" * 70


def _section(title: str) -> None:
    print(f"\n{_BANNER}\n  {title}\n{_BANNER}")


async def main() -> int:
    _section("Phase B Smoke Test — Real Model")

    # ── Setup ──────────────────────────────────────────────────────────────
    audit = AuditLogger(log_path=AUDIT_PATH)

    # Create a temp file with known content.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(
            "Quarterly Financial Summary\n"
            "===========================\n"
            "Revenue: $4,200,000\n"
            "Operating Expenses: $2,800,000\n"
            "Net Profit: $1,400,000\n"
            "Headcount: 47 FTE\n"
            "Key risk: supply chain delays in Q3.\n"
        )
        tmp_path = f.name

    print(f"  Temp file: {tmp_path}")
    goal = f"Read the file at '{tmp_path}' and produce a one-paragraph executive summary."

    # ── Router ─────────────────────────────────────────────────────────────
    _section("Step 1 — Routing")
    # The goal text doesn't strongly trigger any heuristic, so it will likely
    # default to the text model.  That's the right call here.
    llm_client = OllamaClient(model_name="qwen25_14b_instruct", audit_logger=audit)
    router = Router(audit_logger=audit, llm_client=llm_client)

    decision = await router.route(goal, request_id=REQUEST_ID)
    print(f"  Model selected : {decision.model_name} ({decision.ollama_tag})")
    print(f"  Stage          : {decision.stage}")
    print(f"  Capability     : {decision.capability}")
    print(f"  Reason         : {decision.reason}")

    # ── Orchestrator ───────────────────────────────────────────────────────
    _section("Step 2 — Orchestrating")
    orch = Orchestrator(llm_client=llm_client, audit_logger=audit)

    print(f"  Goal: {goal}\n")
    run = await orch.run(goal, request_id=REQUEST_ID)

    print(f"  Status: {run.status.value}")
    if run.status == OrchestratorStatus.FAILED:
        print(f"  FAILURE: {run.failure_summary}")
        return 1

    print(f"\n  Steps completed: {len(run.outcomes)}")
    for outcome in run.outcomes:
        status_str = "✓" if outcome.success else "✗"
        print(f"    {status_str} Step {outcome.step_index}: {outcome.tool_name} (attempt {outcome.attempt})")

    _section("Final Output (model-generated)")
    print(run.final_output)

    # ── Audit verification ─────────────────────────────────────────────────
    _section("Audit Log Verification")
    records = []
    with AUDIT_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    run_records = [r for r in records if r.get("request_id") == REQUEST_ID]
    event_types = [r["event_type"] for r in run_records]

    print(f"  Total records for request_id={REQUEST_ID!r}: {len(run_records)}")
    print(f"  Event types seen: {sorted(set(event_types))}")

    required_types = {"route_decision", "agent_action", "tool_call", "model_call"}
    missing = required_types - set(event_types)
    if missing:
        print(f"  ✗ MISSING event types: {missing}")
        return 1
    else:
        print(f"  ✓ All required event types present")

    ok, errors = audit.verify_chain()
    if ok:
        print(f"  ✓ Hash chain intact ({len(records)} records)")
    else:
        print(f"  ✗ Hash chain BROKEN:")
        for e in errors:
            print(f"      {e}")
        return 1

    _section("SMOKE TEST PASSED")
    print(f"  Audit log: {AUDIT_PATH.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
