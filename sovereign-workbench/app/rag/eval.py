"""
rag/eval.py
===========
Retrieval evaluation harness for the Sovereign Workbench RAG pipeline.

Usage
-----
    # From the project root:
    python -m app.rag.eval

    # With a custom collection or eval set:
    RAG_COLLECTION=docs EVAL_SET=eval_set.yaml python -m app.rag.eval

What it does
------------
1. Loads ``eval_set.yaml`` (or the path in ``EVAL_SET`` env var).
2. For each query, runs it through ``rag_search`` (same code path as the
   real tool, including the ``status=withdrawn`` filter).
3. Checks whether ``expected_doc`` appears in the top-k results.
4. Prints a pass/fail table + final hit rate.

Pass criterion
--------------
A query *passes* when its ``expected_doc`` filename appears in the
``doc_name`` field of at least one of the top-k results.

Negative queries (``expected_doc: null``) *pass* when:
  - the result set is empty, OR
  - the top result has a score below ``NEGATIVE_SCORE_THRESHOLD`` (0.50).
  This proves the corpus has real discrimination power.

Sovereignty note
----------------
No external network calls.  Embeddings go to localhost:11434 via OllamaClient.
Qdrant goes to localhost:6333.  No external APIs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("sovereign.rag.eval")

# Score below which a top result is considered "low confidence" (for negative queries)
NEGATIVE_SCORE_THRESHOLD: float = 0.50

# How many results to retrieve per query
EVAL_TOP_K: int = 5


def _load_eval_set(yaml_path: Path) -> list[dict[str, Any]]:
    """Load and parse the eval_set.yaml file."""
    try:
        import yaml  # pyyaml
    except ImportError as exc:
        raise ImportError(
            "pyyaml is required for eval.  Run: pip install pyyaml"
        ) from exc

    with yaml_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict) or "queries" not in data:
        raise ValueError(f"eval_set.yaml must have a top-level 'queries' key: {yaml_path}")

    return data["queries"]


def _pass_or_fail(
    query_record: dict[str, Any],
    results: list[Any],   # list[SearchResult]
) -> tuple[bool, str]:
    """
    Determine pass/fail for a single eval query.

    Returns
    -------
    (passed, reason)
    """
    expected_doc: Optional[str] = query_record.get("expected_doc")

    # ── Negative query ────────────────────────────────────────────────
    if expected_doc is None:
        if not results:
            return True, "PASS (no results returned — correct for negative query)"
        top_score = results[0].score
        if top_score < NEGATIVE_SCORE_THRESHOLD:
            return True, f"PASS (top score {top_score:.3f} < threshold {NEGATIVE_SCORE_THRESHOLD})"
        else:
            # High-confidence hit on an out-of-corpus query — false positive
            returned_docs = [r.doc_name or r.source for r in results[:3]]
            return False, (
                f"FAIL (top score {top_score:.3f} ≥ threshold — "
                f"false positive: {returned_docs})"
            )

    # ── Positive query ────────────────────────────────────────────────
    returned_docs = [r.doc_name for r in results]
    if any(expected_doc in doc for doc in returned_docs):
        matching = next(
            (r for r in results if expected_doc in r.doc_name), results[0]
        )
        return True, f"PASS (found '{expected_doc}', page {matching.page_number}, score {matching.score:.3f})"
    else:
        return False, (
            f"FAIL (expected '{expected_doc}' not in top-{EVAL_TOP_K} results; "
            f"got: {returned_docs})"
        )


async def run_eval(
    collection: str = "docs",
    eval_yaml_path: Optional[Path] = None,
    top_k: int = EVAL_TOP_K,
) -> dict[str, Any]:
    """
    Run the full retrieval evaluation.

    Parameters
    ----------
    collection:
        Qdrant collection to search.
    eval_yaml_path:
        Path to eval_set.yaml.  Defaults to ``<project_root>/eval_set.yaml``.
    top_k:
        Number of results to retrieve per query.

    Returns
    -------
    Dict with keys: ``total``, ``passed``, ``failed``, ``hit_rate``,
    ``results`` (list of per-query dicts).
    """
    # ── Locate eval set ────────────────────────────────────────────────
    if eval_yaml_path is None:
        _this = Path(__file__).resolve().parent  # app/rag/
        eval_yaml_path = _this.parent.parent / "eval_set.yaml"

    if not eval_yaml_path.exists():
        raise FileNotFoundError(f"eval_set.yaml not found at: {eval_yaml_path}")

    queries = _load_eval_set(eval_yaml_path)
    _log.info("Loaded %d eval queries from '%s'", len(queries), eval_yaml_path)

    # ── Build retrieval dependencies ───────────────────────────────────
    from app.models.ollama_client import OllamaClient, MODEL_REGISTRY
    from app.rag.embedder import Embedder
    from app.rag.store import VectorStore

    store = VectorStore()
    embedding_model_key = "bge_m3"
    if embedding_model_key not in MODEL_REGISTRY:
        raise RuntimeError(f"'{embedding_model_key}' not in MODEL_REGISTRY")

    ollama_tag = MODEL_REGISTRY[embedding_model_key]["ollama_tag"]
    ollama_client = OllamaClient(model_name=embedding_model_key, ollama_tag=ollama_tag)
    embedder = Embedder(ollama_client)

    # ── Run eval queries ───────────────────────────────────────────────
    eval_results: list[dict[str, Any]] = []
    passed = 0
    failed = 0

    for q in queries:
        qid = q.get("id", "?")
        query_text = q["query"]
        source_category: Optional[str] = q.get("source_category")

        _log.info("Evaluating [%s]: %r", qid, query_text[:80])

        try:
            query_vector = await embedder.embed_one(query_text)
            results = store.search_filtered(
                collection=collection,
                query_vector=query_vector,
                top_k=top_k,
                source_category=source_category,
                exclude_status=["withdrawn"],
            )
        except Exception as exc:  # noqa: BLE001
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

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "hit_rate": hit_rate,
        "results": eval_results,
    }


def _print_report(report: dict[str, Any]) -> None:
    """Print a human-readable eval report to stdout."""
    total = report["total"]
    passed = report["passed"]
    failed = report["failed"]
    hit_rate = report["hit_rate"]

    print("\n" + "=" * 70)
    print("  RETRIEVAL EVALUATION REPORT")
    print("=" * 70)

    for r in report["results"]:
        icon = "✓" if r["passed"] else "✗"
        print(f"\n  [{icon}] [{r['id']}]  {r['query'][:60]}...")
        print(f"       Expected: {r['expected_doc'] or '(none — negative query)'}")
        print(f"       {r['reason']}")
        if r["returned_docs"]:
            for i, d in enumerate(r["returned_docs"][:3], 1):
                print(f"       {i}. {d['doc_name']} (page {d['page_number']}, score={d['score']})")

    print("\n" + "-" * 70)
    print(f"  Total queries : {total}")
    print(f"  Passed        : {passed}")
    print(f"  Failed        : {failed}")
    print(f"  Hit rate      : {passed}/{total} ({hit_rate:.0%})")
    print("=" * 70)


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stdout,
    )

    _collection = os.environ.get("RAG_COLLECTION", "docs")
    _eval_path_env = os.environ.get("EVAL_SET")
    _eval_path = Path(_eval_path_env) if _eval_path_env else None

    async def _main() -> None:
        report = await run_eval(collection=_collection, eval_yaml_path=_eval_path)
        _print_report(report)
        # Exit code 1 if any query failed
        sys.exit(0 if report["failed"] == 0 else 1)

    asyncio.run(_main())
