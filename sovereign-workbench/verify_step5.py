"""
verify_step5_rag.py
===================
Step 5: RAG live run — ingest + eval + orchestrator RAG goal.

Writes progress to stdout as documents complete.
Expected runtime: 15–40 min depending on PDF size.
"""
import asyncio, sys, time, uuid, json, pathlib
sys.stdout.reconfigure(line_buffering=True)

_ROOT = pathlib.Path(__file__).resolve().parent
_KB = _ROOT / "knowledge_base"
_LOG_DIR = _ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_AUDIT_LOG = _LOG_DIR / "verify_step5_audit.jsonl"
_COLLECTION = "docs_verify5"


async def main():
    from qdrant_client import QdrantClient
    from app.audit.logger import AuditLogger
    from app.models.ollama_client import OllamaClient, MODEL_REGISTRY
    from app.rag.embedder import Embedder
    from app.rag.store import VectorStore
    from app.rag.ingest import KnowledgeBaseIngestor
    from app.rag.eval import _load_eval_set, _pass_or_fail
    from app.orchestrator.orchestrator import Orchestrator
    from app.orchestrator.state import OrchestratorStatus
    from app.tools.rag_search import RagSearchTool
    from app.tools.registry import register_tool, TOOL_REGISTRY

    # Infrastructure
    audit = AuditLogger(log_path=_AUDIT_LOG)
    store = VectorStore.__new__(VectorStore)
    store._client = QdrantClient(":memory:")

    embed_client = OllamaClient(model_name="bge_m3", audit_logger=audit)
    embedder = Embedder(embed_client)

    # ── 5a. Ingestion ────────────────────────────────────────────────
    print("=== STEP 5a: INGESTION ===")
    kb_ingestor = KnowledgeBaseIngestor(embedder=embedder, store=store, audit_logger=audit)

    t0 = time.monotonic()
    batch = await kb_ingestor.ingest_folder(kb_root=_KB, collection=_COLLECTION)
    elapsed = time.monotonic() - t0

    print(f"\nIngestion complete in {elapsed:.0f}s:")
    print(f"  docs={batch.total_documents} chunks={batch.total_chunks} "
          f"skipped={batch.skipped_documents} failed={batch.failed_documents}")
    for r in batch.results:
        icon = "⚠" if r.skipped else "✓"
        skip = f" [{r.skip_reason}]" if r.skipped else ""
        print(f"  {icon} [{r.source_category}] {r.doc_name}: {r.chunks_ingested} chunks "
              f"({r.duration_ms:.0f}ms){skip}")
    if batch.errors:
        for e in batch.errors:
            print(f"  ✗ {e}")

    ingest_ok = batch.failed_documents == 0
    print(f"\nStep 5a result: {'PASS' if ingest_ok else 'FAIL'}")

    if not ingest_ok:
        return

    # ── 5b. Eval ────────────────────────────────────────────────────
    print("\n=== STEP 5b: RETRIEVAL EVAL ===")
    eval_yaml = _ROOT / "eval_set.yaml"
    queries = _load_eval_set(eval_yaml)
    passed_eval = 0
    failed_eval = 0

    for q in queries:
        qid = q.get("id", "?")
        t0 = time.monotonic()
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
            print(f"  [FAIL:{qid}] exception: {exc}")
            continue

        ok, reason = _pass_or_fail(q, res)
        elapsed_q = time.monotonic() - t0
        if ok:
            passed_eval += 1
        else:
            failed_eval += 1
        print(f"  [{'PASS' if ok else 'FAIL'}:{qid}] {reason} ({elapsed_q:.1f}s)")
        if res:
            top = res[0]
            print(f"    top: {top.doc_name} page={top.page_number} score={top.score:.3f}")

    total_eval = passed_eval + failed_eval
    hit_rate = passed_eval / total_eval if total_eval else 0.0
    print(f"\nStep 5b result: {'PASS' if failed_eval == 0 else 'FAIL'}")
    print(f"HIT RATE: {passed_eval}/{total_eval} ({hit_rate:.0%})")

    # ── 5c. Orchestrator RAG goal ─────────────────────────────────
    print("\n=== STEP 5c: ORCHESTRATOR RAG GOAL ===")

    rag_tool = RagSearchTool(store=store, embedder=embedder, audit_logger=audit)
    register_tool(rag_tool)

    llm = OllamaClient(model_name="qwen25_7b_instruct", audit_logger=audit)
    orch = Orchestrator(llm_client=llm, audit_logger=audit, max_retries=2)

    goal = (
        "Search the knowledge base for what MRPL's environment report says about "
        "compliance with environmental regulations. Return the answer with the "
        "exact document name and page number you found it on."
    )
    rid = f"verify-rag-{str(uuid.uuid4())[:8]}"
    print(f"Goal: {goal}")
    print(f"Request ID: {rid}")

    t0 = time.monotonic()
    try:
        run = await asyncio.wait_for(orch.run(goal, request_id=rid), timeout=300.0)
        elapsed = time.monotonic() - t0

        completed = run.status == OrchestratorStatus.COMPLETED
        has_output = bool(run.final_output and run.final_output.strip())
        output_lower = (run.final_output or "").lower()
        cites_doc = (
            "environment" in output_lower
            and ("page" in output_lower or any(c.isdigit() for c in output_lower))
        )

        print(f"\nStatus    : {run.status.value}")
        print(f"Elapsed   : {elapsed:.1f}s")
        print(f"Outcomes  : {len(run.outcomes)}")
        for i, o in enumerate(run.outcomes):
            print(f"  [{i}] tool={o.tool_name} success={o.success}")
            if not o.success:
                print(f"       error={o.error}")
        print(f"Cites doc : {cites_doc}")
        print(f"\nFinal output:\n{run.final_output or '[empty]'}")

        rag_ok = completed and has_output
        print(f"\nStep 5c result: {'PASS' if rag_ok else 'FAIL'}")
        if not rag_ok and run.failure_summary:
            print(f"Failure: {run.failure_summary}")

    except asyncio.TimeoutError:
        print("Step 5c result: FAIL — timed out after 300s")
    except Exception as exc:
        print(f"Step 5c result: FAIL — {type(exc).__name__}: {exc}")

    # ── 5d. Sovereignty + hash chain ─────────────────────────────
    print("\n=== STEP 5d: SOVEREIGNTY + HASH CHAIN ===")
    violations = []
    try:
        records = [json.loads(l) for l in _AUDIT_LOG.read_text().splitlines() if l.strip()]
        for r in records:
            ep = r.get("payload", {}).get("endpoint", "")
            if ep and "localhost" not in ep and "127.0.0.1" not in ep:
                violations.append(ep)
        chain_ok, chain_errors = audit.verify_chain()
        print(f"Non-local endpoints in audit: {len(violations)} {'(violations!)' if violations else '(clean)'}")
        print(f"Hash chain: {'intact' if chain_ok else 'BROKEN — ' + str(chain_errors[:2])}")
        print(f"Total audit records: {len(records)}")
        sov_ok = len(violations) == 0 and chain_ok
        print(f"Step 5d result: {'PASS' if sov_ok else 'FAIL'}")
    except Exception as exc:
        print(f"Step 5d result: FAIL — {type(exc).__name__}: {exc}")


asyncio.run(main())
