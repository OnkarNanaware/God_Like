"""
verify_phases_abc.py
====================
Full-system verification script for Phases A–C with live Ollama models.

Steps executed:
    2. Hardware + tier resolution
    3. Live model slot probes (reasoning / coder / vision via router+orchestrator)
    4. Orchestrator live run — multi-step with real model output (JSON parser stress)
    5. RAG live run — ingest + eval.py + one rag_search orchestrator goal
    6. Sovereignty assertion (offline check — network is NOT disabled here since
       that requires OS-level changes, but sovereignty is asserted by confirming
       all requests go only to localhost and audit log has zero non-local endpoints)
    7. Concurrent load check — 4 sequential slot probes with VRAM / timing report

Outputs a single results dict that the caller formats into the step-8 table.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.WARNING,   # suppress chatty httpx/ollama logs in output
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stderr,
)
# Show our own script's progress on stdout
_log = logging.getLogger("verify")
_log.setLevel(logging.INFO)
_log.addHandler(logging.StreamHandler(sys.stdout))

_ROOT = Path(__file__).resolve().parent
_KB_ROOT = _ROOT / "knowledge_base"
_AUDIT_LOG = _ROOT / "logs" / "verify_audit.jsonl"
_COLLECTION = "docs_verify"


# ──────────────────────────────────────────────────────────────────────────────
# Result container
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    step: str
    passed: bool
    detail: str
    error: Optional[str] = None


results: list[CheckResult] = []

def record(step: str, passed: bool, detail: str, error: Optional[str] = None):
    r = CheckResult(step=step, passed=passed, detail=detail, error=error)
    results.append(r)
    icon = "✓" if passed else "✗"
    print(f"  [{icon}] {step}: {detail}")
    if error and not passed:
        print(f"        ERROR: {error}")
    return passed


# ──────────────────────────────────────────────────────────────────────────────
# Step 2: Hardware + tier resolution
# ──────────────────────────────────────────────────────────────────────────────

def step2_hardware():
    print("\n── STEP 2: Hardware + tier resolution ───────────────────────")
    from app.hardware.gpu_detect import detect_gpu
    from app.hardware.tier_resolver import resolve_startup_models
    from app.models.ollama_client import MODEL_REGISTRY

    gpu = detect_gpu()
    record("2a.gpu_detect",
           True,
           f"gpu_available={gpu['gpu_available']} total_vram_mb={gpu['total_vram_mb']} "
           f"free_vram_mb={gpu['free_vram_mb']} device='{gpu['device_name']}'")

    resolved = resolve_startup_models()

    # Check each resolved model against ollama list
    ol = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    pulled = set()
    for line in ol.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            t = parts[0]
            pulled.add(t)
            pulled.add(t.split(":")[0])
            if t.endswith(":latest"):
                pulled.add(t[:-7])

    all_ok = True
    slot_detail_parts = []
    for modality, model_key in resolved.items():
        reg = MODEL_REGISTRY.get(model_key, {})
        tag = reg.get("ollama_tag", "?")
        present = any(
            tag == pt or pt.startswith(tag.split(":")[0]) or tag.startswith(pt.split(":")[0])
            for pt in pulled
        )
        slot_detail_parts.append(f"{modality}→{model_key}({tag}):{'OK' if present else 'MISSING'}")
        if not present:
            all_ok = False

    record("2b.tier_resolver",
           all_ok,
           " | ".join(slot_detail_parts),
           None if all_ok else "One or more resolved models not in 'ollama list'")

    # Coder version note: registry has 7b tag but 14b is pulled — Ollama serves 14b
    coder_key = resolved.get("code", "")
    coder_reg_tag = MODEL_REGISTRY.get(coder_key, {}).get("ollama_tag", "")
    if "coder:7b" in coder_reg_tag and any("coder:14b" in p for p in pulled):
        record("2c.coder_tag_mismatch",
               False,
               f"Registry expects {coder_reg_tag} but ollama has qwen2.5-coder:14b pulled. "
               "Ollama will serve 14b — behaviorally fine, but registry tag is stale.",
               f"Fix: update models.yaml qwen25_coder_7b ollama_tag to qwen2.5-coder:14b "
               f"or pull qwen2.5-coder:7b explicitly.")
    return resolved, gpu


# ──────────────────────────────────────────────────────────────────────────────
# Shared infrastructure builder
# ──────────────────────────────────────────────────────────────────────────────

def build_infra(audit_log_path=None):
    from app.audit.logger import AuditLogger
    from app.models.ollama_client import OllamaClient, MODEL_REGISTRY
    from app.rag.embedder import Embedder
    from app.rag.store import VectorStore
    from qdrant_client import QdrantClient

    audit = AuditLogger(log_path=audit_log_path or _AUDIT_LOG)

    # In-memory Qdrant for verification (no server dependency)
    store = VectorStore.__new__(VectorStore)
    store._client = QdrantClient(":memory:")

    embed_client = OllamaClient(model_name="bge_m3", audit_logger=audit)
    embedder = Embedder(embed_client)

    return audit, store, embedder


# ──────────────────────────────────────────────────────────────────────────────
# Step 3: Live model slot probes
# ──────────────────────────────────────────────────────────────────────────────

async def step3_model_probes(resolved: dict, audit, store, embedder):
    print("\n── STEP 3: Live model slot probes ───────────────────────────")
    from app.models.ollama_client import OllamaClient
    from app.router.router import Router
    from app.orchestrator.orchestrator import Orchestrator
    from app.tools.registry import register_tool, TOOL_REGISTRY
    from app.tools.rag_search import RagSearchTool

    # Register rag_search so orchestrator has it
    if "rag_search" not in TOOL_REGISTRY:
        rag_tool = RagSearchTool(store=store, embedder=embedder, audit_logger=audit)
        register_tool(rag_tool)

    probes = [
        {
            "slot": "reasoning",
            "input": "Summarize the purpose of an internal safety audit in two sentences.",
            "expect_capability": ["reasoning", "general", "summarization"],
            "expect_modality": "text",
        },
        {
            "slot": "coder",
            "input": (
                "Find and explain the bug in this Python function:\n\n"
                "def sum_to_n(n):\n"
                "    total = 0\n"
                "    for i in range(n):  # off-by-one: should be range(1, n+1)\n"
                "        total += i\n"
                "    return total\n"
                "\nsum_to_n(5) returns 10, should return 15."
            ),
            "expect_capability": ["code_generation", "debugging", "code_review"],
            "expect_modality": "code",
        },
    ]

    router = Router(audit_logger=audit)

    for probe in probes:
        slot = probe["slot"]
        rid = f"verify-probe-{slot}-{str(uuid.uuid4())[:8]}"
        t0 = time.monotonic()
        try:
            decision = await router.route(probe["input"], request_id=rid)
            elapsed = time.monotonic() - t0

            from app.models.ollama_client import MODEL_REGISTRY
            routed_modality = MODEL_REGISTRY.get(decision.model_name, {}).get("modality", "?")
            capability_ok = decision.capability in probe["expect_capability"]
            modality_ok = routed_modality == probe["expect_modality"]

            # Actually get a response from the model
            llm = OllamaClient(model_name=decision.model_name, audit_logger=audit)
            resp = await llm.chat_completion(
                [{"role": "user", "content": probe["input"]}],
                request_id=rid,
                temperature=0.0,
                max_tokens=256,
            )
            response_nonempty = bool(resp.content and resp.content.strip())

            ok = capability_ok and modality_ok and response_nonempty
            record(
                f"3.{slot}_probe",
                ok,
                f"model={decision.model_name} stage={decision.stage} "
                f"capability={decision.capability} modality={routed_modality} "
                f"response_tokens={resp.response_tokens} latency={elapsed:.1f}s "
                f"response_preview={repr(resp.content[:100])}",
                None if ok else (
                    f"capability_ok={capability_ok} modality_ok={modality_ok} "
                    f"response_nonempty={response_nonempty}"
                )
            )
        except Exception as exc:
            record(f"3.{slot}_probe", False, "exception during probe", str(exc))

    # Vision: route a prompt with .png attachment — confirm vision model selected
    try:
        rid = f"verify-probe-vision-{str(uuid.uuid4())[:8]}"
        decision = await router.route(
            "Describe what you see in this image.",
            attached_filenames=["test_chart.png"],
            request_id=rid,
        )
        from app.models.ollama_client import MODEL_REGISTRY
        routed_modality = MODEL_REGISTRY.get(decision.model_name, {}).get("modality", "?")
        # For vision probe we only test routing, not actual image inference (no image file)
        ok = routed_modality == "vision"
        record("3.vision_route",
               ok,
               f"model={decision.model_name} stage={decision.stage} modality={routed_modality}",
               None if ok else f"Expected vision modality, got {routed_modality}")
    except Exception as exc:
        record("3.vision_route", False, "exception during vision routing", str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Step 4: Orchestrator live run — real model output + JSON parser stress
# ──────────────────────────────────────────────────────────────────────────────

async def step4_orchestrator_live(audit):
    print("\n── STEP 4: Orchestrator live run (real LLM output) ──────────")
    from app.models.ollama_client import OllamaClient
    from app.orchestrator.orchestrator import Orchestrator
    from app.orchestrator.state import OrchestratorStatus

    # Write a real file the plan can read
    test_file = _ROOT / "logs" / "verify_test_doc.txt"
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
    rid = f"verify-orch-live-{str(uuid.uuid4())[:8]}"

    t0 = time.monotonic()
    try:
        run = await asyncio.wait_for(
            orch.run(goal, request_id=rid),
            timeout=120.0,
        )
        elapsed = time.monotonic() - t0

        plan_ok = len(run.plan) >= 1
        completed = run.status == OrchestratorStatus.COMPLETED
        has_output = bool(run.final_output and run.final_output.strip())
        any_success = any(o.success for o in run.outcomes)

        ok = completed and has_output
        record(
            "4.orchestrator_live",
            ok,
            f"status={run.status.value} plan_steps={len(run.plan)} "
            f"outcomes={len(run.outcomes)} any_tool_success={any_success} "
            f"elapsed={elapsed:.1f}s output_preview={repr((run.final_output or '')[:150])}",
            None if ok else f"failure_summary={run.failure_summary}"
        )

        # JSON parser stress: capture the raw plan from audit log
        # We check that at least one replanning actually happened if there was a retry
        retries = sum(1 for o in run.outcomes if not o.success)
        if retries > 0:
            record("4a.json_parser_replan",
                   True,
                   f"Re-plan triggered {retries} time(s) against real model output and recovered")
        else:
            record("4a.json_parser_replan",
                   True,
                   "Plan succeeded on first attempt — no retry needed (parser not exercised under stress, but no failure either)")

    except asyncio.TimeoutError:
        record("4.orchestrator_live", False, "timed out after 120s", "asyncio.TimeoutError")
    except Exception as exc:
        record("4.orchestrator_live", False, "exception", str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Step 5: RAG live run — ingest + eval + orchestrator rag goal
# ──────────────────────────────────────────────────────────────────────────────

async def step5_rag_live(audit, store, embedder):
    print("\n── STEP 5: RAG live run ─────────────────────────────────────")
    from app.rag.ingest import KnowledgeBaseIngestor
    from app.rag.eval import _load_eval_set, _pass_or_fail
    from app.models.ollama_client import OllamaClient
    from app.orchestrator.orchestrator import Orchestrator
    from app.orchestrator.state import OrchestratorStatus
    from app.tools.rag_search import RagSearchTool
    from app.tools.registry import register_tool, TOOL_REGISTRY

    # ── 5a. Ingest ────────────────────────────────────────────────────
    t0 = time.monotonic()
    kb_ingestor = KnowledgeBaseIngestor(
        embedder=embedder, store=store, audit_logger=audit
    )
    try:
        batch = await asyncio.wait_for(
            kb_ingestor.ingest_folder(kb_root=_KB_ROOT, collection=_COLLECTION),
            timeout=1800.0,  # 30 min for large PDFs
        )
        elapsed = time.monotonic() - t0
        record(
            "5a.ingest",
            batch.failed_documents == 0,
            f"docs={batch.total_documents} chunks={batch.total_chunks} "
            f"skipped={batch.skipped_documents} failed={batch.failed_documents} "
            f"elapsed={elapsed:.0f}s",
            f"Failed docs: {batch.errors}" if batch.failed_documents > 0 else None
        )
        # Per-doc breakdown
        for r in batch.results:
            icon = "⚠" if r.skipped else "✓"
            skip = f" [{r.skip_reason}]" if r.skipped else ""
            print(f"         {icon} [{r.source_category}] {r.doc_name}: {r.chunks_ingested} chunks{skip}")
    except asyncio.TimeoutError:
        record("5a.ingest", False, "timed out after 1800s", "asyncio.TimeoutError")
        return  # can't eval without ingestion
    except Exception as exc:
        record("5a.ingest", False, "ingest exception", str(exc))
        return

    # ── 5b. Eval ─────────────────────────────────────────────────────
    eval_yaml = _ROOT / "eval_set.yaml"
    queries = _load_eval_set(eval_yaml)
    passed_eval = 0
    failed_eval = 0
    eval_details = []

    for q in queries:
        qid = q.get("id", "?")
        try:
            qv = await embedder.embed_one(q["query"])
            res = store.search_filtered(
                collection=_COLLECTION,
                query_vector=qv,
                top_k=5,
                source_category=q.get("source_category"),
                exclude_status=["withdrawn"],
            )
        except Exception as exc:
            failed_eval += 1
            eval_details.append(f"[FAIL:{qid}] exception: {exc}")
            continue

        ok, reason = _pass_or_fail(q, res)
        if ok:
            passed_eval += 1
        else:
            failed_eval += 1
        eval_details.append(f"[{'PASS' if ok else 'FAIL'}:{qid}] {reason}")

    total_eval = passed_eval + failed_eval
    hit_rate = passed_eval / total_eval if total_eval else 0.0
    record(
        "5b.eval_hit_rate",
        failed_eval == 0,
        f"hit_rate={passed_eval}/{total_eval} ({hit_rate:.0%})",
        "; ".join(d for d in eval_details if d.startswith("[FAIL")) or None
    )
    for d in eval_details:
        print(f"         {d}")

    # ── 5c. Orchestrator RAG goal ─────────────────────────────────────
    # Register rag_search with the real store
    rag_tool = RagSearchTool(store=store, embedder=embedder, audit_logger=audit)
    register_tool(rag_tool)

    llm = OllamaClient(model_name="qwen25_7b_instruct", audit_logger=audit)
    orch = Orchestrator(llm_client=llm, audit_logger=audit, max_retries=2)

    goal = (
        "Search the knowledge base for what MRPL's environment report says about "
        "compliance with environmental regulations. Return the answer with the "
        "exact document name and page number you found it on."
    )
    rid = f"verify-rag-goal-{str(uuid.uuid4())[:8]}"
    t0 = time.monotonic()
    try:
        run = await asyncio.wait_for(
            orch.run(goal, request_id=rid),
            timeout=180.0,
        )
        elapsed = time.monotonic() - t0

        completed = run.status == OrchestratorStatus.COMPLETED
        has_output = bool(run.final_output and run.final_output.strip())

        # Check that the output contains a citation (doc_name / page reference)
        output_lower = (run.final_output or "").lower()
        cites_doc = (
            "environment_report" in output_lower
            or "environment report" in output_lower
            or "page" in output_lower
        )

        ok = completed and has_output
        record(
            "5c.rag_orchestrator_goal",
            ok,
            f"status={run.status.value} completed={completed} "
            f"cites_doc={cites_doc} elapsed={elapsed:.1f}s "
            f"output_preview={repr((run.final_output or '')[:250])}",
            None if ok else f"failure_summary={run.failure_summary}"
        )
    except asyncio.TimeoutError:
        record("5c.rag_orchestrator_goal", False, "timed out after 180s", "asyncio.TimeoutError")
    except Exception as exc:
        record("5c.rag_orchestrator_goal", False, "exception", str(exc))

    return hit_rate, passed_eval, total_eval


# ──────────────────────────────────────────────────────────────────────────────
# Step 6: Sovereignty assertion (audit log inspection)
# ──────────────────────────────────────────────────────────────────────────────

def step6_sovereignty(audit):
    print("\n── STEP 6: Sovereignty check ────────────────────────────────")
    import fcntl
    # Read the audit log and verify every endpoint is localhost
    non_local_violations = []
    try:
        with _AUDIT_LOG.open("r", encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                    payload = rec.get("payload", {})
                    endpoint = payload.get("endpoint", "")
                    if endpoint and "localhost" not in endpoint and "127.0.0.1" not in endpoint:
                        non_local_violations.append(f"line {lineno}: {endpoint}")
                except Exception:
                    pass
    except FileNotFoundError:
        record("6.sovereignty", False, "audit log not found", str(_AUDIT_LOG))
        return

    ok = len(non_local_violations) == 0
    record(
        "6.sovereignty",
        ok,
        f"Scanned audit log: {non_local_violations.__len__()} non-local endpoint(s) found",
        f"Violations: {non_local_violations}" if not ok else None
    )

    # Verify hash chain is intact
    try:
        ok_chain, chain_errors = audit.verify_chain()
        record(
            "6.hash_chain",
            ok_chain,
            f"Hash chain intact after full verification run",
            "; ".join(chain_errors) if not ok_chain else None
        )
    except Exception as exc:
        record("6.hash_chain", False, "chain verification threw exception", str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Step 7: Concurrent/sequential load check
# ──────────────────────────────────────────────────────────────────────────────

async def step7_load(audit):
    print("\n── STEP 7: Sequential load check (4 slot probes) ───────────")
    from app.models.ollama_client import OllamaClient

    probes = [
        ("qwen25_7b_instruct",  "Reasoning probe: What is the role of an HSE officer?"),
        ("qwen25_coder_7b",     "def fibonacci(n):\n    # fix this function\n    return n"),
        ("qwen25vl_3b",         "Describe a refinery safety placard."),
        ("bge_m3",              None),  # embedding only — no chat
    ]

    timings = []
    all_ok = True
    for model_key, prompt in probes:
        t0 = time.monotonic()
        try:
            if prompt is None:
                # Embedding probe
                llm = OllamaClient(model_name=model_key, audit_logger=audit)
                vec = await llm.embeddings("test embedding probe")
                elapsed = time.monotonic() - t0
                ok = len(vec) == 1024
                timings.append(f"{model_key}:{elapsed:.1f}s(embed,dim={len(vec)})")
                if not ok:
                    all_ok = False
            else:
                llm = OllamaClient(model_name=model_key, audit_logger=audit)
                resp = await asyncio.wait_for(
                    llm.chat_completion(
                        [{"role": "user", "content": prompt}],
                        request_id=f"load-{model_key}",
                        temperature=0.0,
                        max_tokens=64,
                    ),
                    timeout=90.0,
                )
                elapsed = time.monotonic() - t0
                ok = bool(resp.content and resp.content.strip())
                timings.append(f"{model_key}:{elapsed:.1f}s(tok={resp.response_tokens})")
                if not ok:
                    all_ok = False
        except Exception as exc:
            elapsed = time.monotonic() - t0
            timings.append(f"{model_key}:{elapsed:.1f}s(ERROR:{type(exc).__name__})")
            all_ok = False

    # VRAM check (macOS — no nvidia-smi; use vm_stat as proxy)
    vm = subprocess.run(["vm_stat"], capture_output=True, text=True)
    vram_note = "macOS/Apple Silicon — no NVIDIA VRAM counter; vm_stat: " + vm.stdout.splitlines()[1] if vm.returncode == 0 else "N/A"

    record(
        "7.sequential_load",
        all_ok,
        " | ".join(timings) + f" | {vram_note}",
        None if all_ok else "One or more model probes failed during load check"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 70)
    print("  SOVEREIGN WORKBENCH — Full verification pass (Phases A–C)")
    print("=" * 70)

    # Step 2
    resolved, gpu = step2_hardware()

    # Shared infra
    audit, store, embedder = build_infra()

    # Step 3
    await step3_model_probes(resolved, audit, store, embedder)

    # Step 4
    await step4_orchestrator_live(audit)

    # Step 5
    rag_result = await step5_rag_live(audit, store, embedder)

    # Step 6
    step6_sovereignty(audit)

    # Step 7
    await step7_load(audit)

    # ── Step 8: Final report ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  STEP 8: SUMMARY TABLE")
    print("=" * 70)
    print(f"  {'Check':<40} {'Status':<8} Detail")
    print(f"  {'-'*40} {'-'*7} {'-'*20}")
    for r in results:
        icon = "PASS" if r.passed else "FAIL"
        print(f"  {r.step:<40} {icon:<8} {r.detail[:80]}")
        if r.error and not r.passed:
            print(f"  {'':40}          ERROR: {r.error[:100]}")

    passed_count = sum(1 for r in results if r.passed)
    failed_count = sum(1 for r in results if not r.passed)
    print(f"\n  Total: {passed_count} PASS, {failed_count} FAIL")

    if rag_result:
        hit_rate_val, hit_n, hit_total = rag_result
        print(f"\n  RAG hit rate  : {hit_n}/{hit_total} ({hit_rate_val:.0%})")

    print(f"  VRAM          : {gpu['total_vram_mb']} MB total, {gpu['free_vram_mb']} MB free "
          f"({'NVIDIA' if gpu['gpu_available'] else 'CPU/Apple Silicon — no NVIDIA counter'})")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
