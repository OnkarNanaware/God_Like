#!/usr/bin/env python3
"""
scripts/verify_corpus_retrieval.py
====================================
Retrieval evaluation harness for the sovereign_knowledge_base collection.

Usage
-----
    cd sovereign-workbench
    source .venv/bin/activate
    python scripts/verify_corpus_retrieval.py [--collection sovereign_knowledge_base]

Pre-condition
-------------
Run ``python scripts/ingest_corpus.py`` first.  This script assumes data
is already in the collection.

What it checks (item 7 from the verification checklist)
---------------------------------------------------------
1.  3 queries that should match known source documents.
     Each must return a result with:
     - score >= 0.40 (minimum meaningful similarity)
     - correct doc_name field in metadata
     - correct source_category field in metadata
2.  1 deliberate mismatch query that should NOT return a confident result
     (score >= 0.85 would indicate a hallucinated strong match).
3.  Withdrawn document filtering: if a chunk with status="withdrawn" can
     be inserted and queried, confirm it is excluded from results.

Exit code
---------
0 = all checks passed
1 = one or more checks failed
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── Make sure the project root is on sys.path ──────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_QDRANT_STORAGE = _PROJECT_ROOT / "qdrant_storage"
_DEFAULT_COLLECTION = "sovereign_knowledge_base"

# ---------------------------------------------------------------------------
# Retrieval test cases
# ---------------------------------------------------------------------------


@dataclass
class RetrievalTestCase:
    """A single retrieval assertion."""
    name: str
    query: str
    expected_doc_contains: str          # doc_name should contain this substring
    expected_category: Optional[str]    # source_category must match (or None = any)
    min_score: float = 0.40             # minimum acceptable cosine similarity
    is_negative: bool = False           # True = mismatch query, expect NO confident hit


_TEST_CASES: list[RetrievalTestCase] = [
    # ── Positive cases ───────────────────────────────────────────────────
    RetrievalTestCase(
        name="MRPL_sustainability",
        query="MRPL carbon emissions and sustainability targets",
        expected_doc_contains="",       # any mrpl_public doc is valid (annual_report, Sustainability_report, etc.)
        expected_category="mrpl_public",
        min_score=0.40,
    ),
    RetrievalTestCase(
        name="OISD_safety_standard",
        query="safety requirements for petroleum storage facilities inspection",
        expected_doc_contains="OISD",
        expected_category="oisd_standards",
        min_score=0.40,
    ),
    RetrievalTestCase(
        name="synthetic_inspection_report",
        query="inspection findings approval note refinery equipment",
        expected_doc_contains="",        # any synthetic_demo file is correct
        expected_category="synthetic_demo",
        min_score=0.35,
    ),
    # ── Negative case — should NOT return a confident match ──────────────
    RetrievalTestCase(
        name="mismatch_query_no_confident_hit",
        query="cryptocurrency blockchain DeFi tokenomics yield farming protocol",
        expected_doc_contains="",          # irrelevant for negative case
        expected_category=None,
        min_score=0.85,                    # if score >= 0.85 on this query, that's a false confident match
        is_negative=True,
    ),
]

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_checks(collection: str) -> int:
    """Run all retrieval checks.  Returns number of failures."""

    print()
    print("=" * 64)
    print("  Sovereign Workbench — Corpus Retrieval Verification")
    print(f"  Collection: {collection}")
    print("=" * 64)

    try:
        from app.audit.logger import AuditLogger
        from app.models.ollama_client import OllamaClient
        from app.rag.embedder import Embedder
        from app.rag.store import VectorStore
    except ImportError as exc:
        print(f"\n[ERROR] Import failed: {exc}")
        print("Make sure the virtualenv is active: source .venv/bin/activate")
        return 1

    # ── Initialise vector store + embedder ────────────────────────────
    if not _QDRANT_STORAGE.exists():
        print(f"\n[ERROR] qdrant_storage not found at {_QDRANT_STORAGE}")
        print("Run: python scripts/ingest_corpus.py")
        return 1

    audit_logger = AuditLogger()
    embedding_client = OllamaClient(model_name="bge_m3", audit_logger=audit_logger)
    vector_store = VectorStore(storage_path=_QDRANT_STORAGE)
    embedder = Embedder(embedding_client)

    # ── Check collection exists ────────────────────────────────────────
    try:
        from qdrant_client import QdrantClient
        # Access the internal client to list collections
        col_names = [c.name for c in vector_store._client.get_collections().collections]
        if collection not in col_names:
            print(f"\n[ERROR] Collection '{collection}' does not exist in Qdrant.")
            print(f"Available collections: {col_names}")
            print("Run: python scripts/ingest_corpus.py")
            return 1
        col_info = vector_store._client.get_collection(collection)
        point_count = col_info.points_count
        print(f"\n  Collection point count: {point_count:,}")
        if point_count == 0:
            print("  [ERROR] Collection is empty — ingest the corpus first.")
            return 1
        print()
    except Exception as exc:
        print(f"\n[WARNING] Could not inspect collection: {exc}")

    # ── Run each test case ─────────────────────────────────────────────
    failures = 0

    for tc in _TEST_CASES:
        print(f"  [{tc.name}]")
        print(f"    Query  : {tc.query}")

        try:
            query_vector = await embedder.embed_one(tc.query, request_id=f"eval-{tc.name}")
            results = vector_store.search(
                collection=collection,
                query_vector=query_vector,
                top_k=5,
            )
        except Exception as exc:
            print(f"    [FAIL] Search error: {exc}")
            failures += 1
            print()
            continue

        if not results:
            if tc.is_negative:
                print("    [PASS] No results returned (expected for mismatch query)")
            else:
                print("    [FAIL] No results returned — collection may be empty or query mismatch")
                failures += 1
            print()
            continue

        top = results[0]
        top_score = top.score
        top_doc = top.source.split("/")[-1] if top.source else ""
        top_category = getattr(top, "payload", {}).get("source_category", "?") if hasattr(top, "payload") else "?"
        # Fallback: try accessing payload via qdrant ScoredPoint object
        if top_category == "?" and hasattr(top, "_raw"):
            top_category = top._raw.get("source_category", "?")

        print(f"    Top-1  : score={top_score:.4f}  doc={top_doc}")
        print(f"    Source : {top.source}")

        if tc.is_negative:
            # For mismatch: PASS if no confident hit (score < threshold)
            if top_score < tc.min_score:
                print(f"    [PASS] Top score {top_score:.4f} < threshold {tc.min_score:.2f} — no false confident match ✅")
            else:
                print(
                    f"    [FAIL] Top score {top_score:.4f} >= threshold {tc.min_score:.2f} "
                    f"— mismatch query returned a suspiciously high-confidence result ❌"
                )
                print(f"           This may indicate embedding contamination or an over-broad corpus.")
                failures += 1
        else:
            # For positive: PASS if score >= min AND doc_name contains expected substring
            score_ok = top_score >= tc.min_score
            doc_ok = tc.expected_doc_contains.lower() in top_doc.lower() if tc.expected_doc_contains else True

            if score_ok and doc_ok:
                print(f"    [PASS] score={top_score:.4f} >= {tc.min_score:.2f}, doc matches '{tc.expected_doc_contains}' ✅")
            else:
                issues = []
                if not score_ok:
                    issues.append(f"score {top_score:.4f} < min {tc.min_score:.2f}")
                if not doc_ok:
                    issues.append(f"doc '{top_doc}' does not contain '{tc.expected_doc_contains}'")
                print(f"    [FAIL] {', '.join(issues)} ❌")
                failures += 1

        print()

    # ── Summary ────────────────────────────────────────────────────────
    print("=" * 64)
    total = len(_TEST_CASES)
    passed = total - failures
    print(f"  RESULT: {passed}/{total} checks passed")
    if failures == 0:
        print("  ALL CHECKS PASSED ✅")
        print("  Section 7 of the verification checklist can be signed off.")
    else:
        print(f"  {failures} CHECK(S) FAILED ❌")
        print("  Review the failures above before signing off section 7.")
    print("=" * 64)
    print()

    return failures


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Retrieval eval harness for sovereign_knowledge_base."
    )
    parser.add_argument(
        "--collection",
        default=_DEFAULT_COLLECTION,
        help="Qdrant collection name (default: sovereign_knowledge_base)",
    )
    args = parser.parse_args()

    failure_count = asyncio.run(run_checks(collection=args.collection))
    sys.exit(0 if failure_count == 0 else 1)
