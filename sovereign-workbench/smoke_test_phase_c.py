"""
smoke_test_phase_c.py
=====================
Real-data end-to-end test for Phase C.

Runs against the actual knowledge_base/ PDFs using a local in-memory Qdrant
(qdrant_client ':memory:') so no Qdrant server is required.  Embedding calls
go to Ollama at localhost:11434 — Ollama must be running with bge-m3 pulled.

Usage
-----
    python smoke_test_phase_c.py

What it does
------------
1. Ingests all documents from knowledge_base/ into an in-memory Qdrant.
2. Runs the retrieval evaluation (eval_set.yaml) and reports hit rate.
3. Executes one full orchestrator pass with a goal that should trigger
   rag_search and cite the correct doc_name + page_number.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger("smoke_test_phase_c")

# Project root
_ROOT = Path(__file__).resolve().parent
_KB_ROOT = _ROOT / "knowledge_base"
_COLLECTION = "docs_smoke"


async def _build_infra():
    """Build shared infra: in-memory store, embedder, audit logger."""
    from qdrant_client import QdrantClient
    from app.audit.logger import AuditLogger
    from app.models.ollama_client import OllamaClient, MODEL_REGISTRY
    from app.rag.embedder import Embedder
    from app.rag.store import VectorStore

    # In-memory Qdrant — no server required
    store = VectorStore.__new__(VectorStore)
    store._client = QdrantClient(":memory:")

    audit = AuditLogger(log_path=_ROOT / "logs" / "smoke_phase_c_audit.jsonl")

    if "bge_m3" not in MODEL_REGISTRY:
        raise RuntimeError("bge_m3 not in MODEL_REGISTRY")

    ollama_client = OllamaClient(model_name="bge_m3", audit_logger=audit)
    embedder = Embedder(ollama_client)

    return store, embedder, audit


async def step1_ingest(store, embedder, audit):
    """Step 1: Ingest all knowledge_base/ documents."""
    from app.rag.ingest import KnowledgeBaseIngestor

    print("\n" + "=" * 60)
    print("  STEP 1: Ingestion")
    print("=" * 60)

    kb_ingestor = KnowledgeBaseIngestor(
        embedder=embedder,
        store=store,
        audit_logger=audit,
    )

    result = await kb_ingestor.ingest_folder(kb_root=_KB_ROOT, collection=_COLLECTION)

    print(f"\n  Documents processed : {result.total_documents}")
    print(f"  Chunks ingested     : {result.total_chunks}")
    print(f"  Skipped (zero-text) : {result.skipped_documents}")
    print(f"  Failed              : {result.failed_documents}")
    print()

    for r in result.results:
        icon = "⚠" if r.skipped else "✓"
        skip_note = f" [{r.skip_reason}]" if r.skipped else ""
        print(f"  {icon} [{r.source_category}] {r.doc_name}: {r.chunks_ingested} chunks{skip_note}")

    if result.failed_documents > 0:
        print("\nErrors:")
        for e in result.errors:
            print(f"  ✗ {e}")

    return result


async def step2_eval(store, embedder):
    """Step 2: Retrieval evaluation."""
    from app.rag.eval import run_eval, _print_report

    print("\n" + "=" * 60)
    print("  STEP 2: Retrieval Evaluation")
    print("=" * 60)

    # Monkey-patch run_eval to use our in-memory store
    # (eval.py creates its own store by default — we override with ours)
    from app.rag import eval as _eval_mod

    _orig_vs = None
    original_run_eval = _eval_mod.run_eval

    async def _patched_eval(collection=_COLLECTION, eval_yaml_path=None, top_k=5):
        from app.rag.eval import _load_eval_set, _pass_or_fail, NEGATIVE_SCORE_THRESHOLD

        if eval_yaml_path is None:
            eval_yaml_path = _ROOT / "eval_set.yaml"

        queries = _load_eval_set(eval_yaml_path)
        eval_results = []
        passed = 0
        failed = 0

        for q in queries:
            qid = q.get("id", "?")
            query_text = q["query"]
            source_category = q.get("source_category")

            try:
                query_vector = await embedder.embed_one(query_text)
                results = store.search_filtered(
                    collection=collection,
                    query_vector=query_vector,
                    top_k=top_k,
                    source_category=source_category,
                    exclude_status=["withdrawn"],
                )
            except Exception as exc:
                eval_results.append({
                    "id": qid,
                    "query": query_text,
                    "expected_doc": q.get("expected_doc"),
                    "passed": False,
                    "reason": f"ERROR: {exc}",
                    "returned_docs": [],
                })
                failed += 1
                continue

            ok, reason = _pass_or_fail(q, results)
            returned_docs = [
                {"doc_name": r.doc_name, "page_number": r.page_number, "score": round(r.score, 4)}
                for r in results
            ]

            if ok:
                passed += 1
            else:
                failed += 1

            eval_results.append({
                "id": qid,
                "query": query_text,
                "expected_doc": q.get("expected_doc"),
                "source_category": source_category,
                "passed": ok,
                "reason": reason,
                "returned_docs": returned_docs,
            })

        total = passed + failed
        hit_rate = passed / total if total > 0 else 0.0
        return {"total": total, "passed": passed, "failed": failed,
                "hit_rate": hit_rate, "results": eval_results}

    report = await _patched_eval()
    _print_report(report)
    return report


async def step3_orchestrator(store, embedder, audit):
    """Step 3: One full orchestrator pass with rag_search."""
    from app.orchestrator.orchestrator import Orchestrator
    from app.tools.rag_search import RagSearchTool
    from app.tools.registry import register_tool
    from app.models.ollama_client import OllamaClient, MODEL_REGISTRY

    print("\n" + "=" * 60)
    print("  STEP 3: Full Orchestrator Pass")
    print("=" * 60)

    # Register our in-memory rag_search tool
    tool = RagSearchTool(store=store, embedder=embedder, audit_logger=audit)
    register_tool(tool)

    # Use actual LLM for orchestration
    text_model = "qwen25_14b_instruct"
    if text_model not in MODEL_REGISTRY:
        text_model = next(iter(MODEL_REGISTRY))
    llm_client = OllamaClient(model_name=text_model, audit_logger=audit)

    orch = Orchestrator(llm_client=llm_client, audit_logger=audit)

    goal = (
        "What does MRPL's environment report say about compliance with "
        "environmental regulations? Cite the specific document and page number."
    )

    print(f"\n  Goal: {goal}\n")
    run = await orch.run(goal, request_id="smoke-phase-c-001")

    print(f"\n  Status     : {run.status.value}")
    print(f"  Steps run  : {len(run.outcomes)}")
    for o in run.outcomes:
        icon = "✓" if o.success else "✗"
        print(f"  {icon} [{o.tool_name}] attempt={o.attempt} success={o.success}")
    print(f"\n  Final output:\n  {'─' * 56}")
    if run.final_output:
        for line in run.final_output.splitlines():
            print(f"  {line}")
    if run.failure_summary:
        print(f"\n  FAILURE: {run.failure_summary}")


async def main():
    print("\n" + "=" * 60)
    print("  SOVEREIGN WORKBENCH — Phase C Smoke Test")
    print("  Real-data run (in-memory Qdrant + live Ollama bge-m3)")
    print("=" * 60)

    try:
        store, embedder, audit = await _build_infra()
    except Exception as exc:
        print(f"\n  ✗ Failed to build infra: {exc}")
        print("  Is Ollama running?  Run: ollama serve")
        print("  Is bge-m3 pulled?   Run: ollama pull bge-m3")
        sys.exit(1)

    ingest_result = await step1_ingest(store, embedder, audit)
    eval_report = await step2_eval(store, embedder)
    await step3_orchestrator(store, embedder, audit)

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Chunks ingested  : {ingest_result.total_chunks}")
    print(f"  Eval hit rate    : {eval_report['passed']}/{eval_report['total']} "
          f"({eval_report['hit_rate']:.0%})")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
