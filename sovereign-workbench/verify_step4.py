"""
verify_step4_orchestrator.py
============================
Step 4: Orchestrator live run against a real LLM (file_read → summarize).
"""
import asyncio, sys, time, uuid, tempfile, pathlib, json
sys.stdout.reconfigure(line_buffering=True)

async def main():
    from app.audit.logger import AuditLogger
    from app.models.ollama_client import OllamaClient
    from app.orchestrator.orchestrator import Orchestrator
    from app.orchestrator.state import OrchestratorStatus
    from app.tools.file_read import FileReadTool
    from app.tools.registry import register_tool, TOOL_REGISTRY

    tmp = pathlib.Path(tempfile.mkdtemp())
    audit = AuditLogger(log_path=tmp / 'audit.jsonl')

    # Register file_read if not already in
    if "file_read" not in TOOL_REGISTRY:
        register_tool(FileReadTool())

    # Write test document
    test_file = tmp / "safety_audit_summary.txt"
    test_file.write_text(
        "MRPL Internal Safety Audit FY2024 — Summary\n\n"
        "Scope: This audit covered process safety, fire prevention, and environmental compliance "
        "across all three refinery units. 147 observations were recorded. "
        "Critical findings (P1): 3. High-priority (P2): 22. Medium (P3): 122. "
        "All P1 items have been closed. P2 closure rate: 91%. "
        "Next audit scheduled: March 2025.\n",
        encoding="utf-8",
    )

    llm = OllamaClient(model_name="qwen25_7b_instruct", audit_logger=audit)
    orch = Orchestrator(llm_client=llm, audit_logger=audit, max_retries=3)

    goal = f"Read the file at '{test_file}' and write a three-bullet summary of its key findings."
    rid = f"verify-orch-{str(uuid.uuid4())[:8]}"

    print(f"Goal: {goal}")
    print(f"Request ID: {rid}")
    t0 = time.monotonic()

    try:
        run = await asyncio.wait_for(orch.run(goal, request_id=rid), timeout=180.0)
        elapsed = time.monotonic() - t0

        print(f"\nStatus        : {run.status.value}")
        print(f"Plan steps    : {len(run.plan)}")
        print(f"Outcomes      : {len(run.outcomes)}")
        print(f"Elapsed       : {elapsed:.1f}s")
        print(f"Final output  : {repr((run.final_output or '')[:300])}")
        if run.failure_summary:
            print(f"Failure       : {run.failure_summary}")

        for i, o in enumerate(run.outcomes):
            print(f"  Outcome[{i}]: tool={o.tool_name} success={o.success} attempt={o.attempt}")
            if not o.success:
                print(f"             error={o.error}")

        retries = sum(1 for o in run.outcomes if not o.success)
        completed = run.status == OrchestratorStatus.COMPLETED
        has_output = bool(run.final_output and run.final_output.strip())
        ok = completed and has_output

        print(f"\nStep 4 result : {'PASS' if ok else 'FAIL'}")
        print(f"JSON parser stress: retries={retries} ({'exercised — replan triggered' if retries > 0 else 'no retry needed — first plan parsed successfully'})")

        # Audit log check
        records = [json.loads(l) for l in (tmp / 'audit.jsonl').read_text().splitlines() if l.strip()]
        orch_records = [r for r in records if r.get('event_type') in ('agent_action', 'tool_call')]
        request_ids_in_log = {r.get('request_id') for r in records}
        chain_ok, chain_errors = audit.verify_chain()
        print(f"Audit records : {len(records)} total, {len(orch_records)} tool/action events")
        print(f"Request ID in log: {rid in request_ids_in_log}")
        print(f"Hash chain    : {'intact' if chain_ok else 'BROKEN — ' + str(chain_errors[:2])}")

    except asyncio.TimeoutError:
        print("Step 4 result: FAIL — timed out after 180s")
    except Exception as exc:
        print(f"Step 4 result: FAIL — exception: {type(exc).__name__}: {exc}")

asyncio.run(main())
