"""
tools/rag_search.py
===================
``rag_search`` tool — semantic search over the local Qdrant knowledge base.

Phase C upgrades over the Phase B skeleton
------------------------------------------
* ``source_category`` filter: caller can scope retrieval to ``mrpl_public`` or
  ``oisd_standards`` (or any future category that's added as a subfolder).
* ``status`` filter: ``withdrawn`` chunks are excluded by default.  This is a
  real Qdrant filter in the query, not a post-retrieval Python filter.
* **Audit trail**: every call writes a ``RAG_RETRIEVAL`` event to the audit
  log with ``request_id``, the full query, and the list of
  ``{doc_name, page_number}`` for every returned chunk.  This is the
  source-attribution record that lets us say "retrieved from X, page Y".
* ``metadata.sources`` list: each result's ``doc_name`` + ``page_number`` is
  returned in the tool metadata so the orchestrator / synthesis step can cite
  them.

The tool is backed by:
* :class:`~app.rag.store.VectorStore`  — Qdrant at localhost:6333.
* :class:`~app.rag.embedder.Embedder` — bge-m3 via OllamaClient.

Input schema
------------
{
    "query":           required str  — natural language query
    "collection":      optional str  — target collection (default: "sovereign_knowledge_base")
    "top_k":           optional int  — max results (default: 5)
    "source_category": optional str  — filter to one category folder
}

Output (on success)
-------------------
A markdown string of ranked results:

    **[1] score=0.87** | environment_report.pdf (page 12) | mrpl_public
    > ...chunk text...

    **[2] score=0.81** | ...

Sovereignty note
----------------
Embedding calls go through OllamaClient → localhost:11434.
Qdrant calls go to localhost:6333.  No external network traffic.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.audit.logger import AuditLogger, EventType
from app.rag.embedder import Embedder
from app.rag.store import VectorStore, VectorStoreError
from app.tools.base import BaseTool, ToolResult

_log = logging.getLogger("sovereign.tools.rag_search")

_DEFAULT_COLLECTION = "sovereign_knowledge_base"
_DEFAULT_TOP_K = 5


class RagSearchTool(BaseTool):
    """
    Semantic search tool backed by the local Qdrant vector store.

    Parameters
    ----------
    store:
        Initialised :class:`~app.rag.store.VectorStore` instance.
    embedder:
        Initialised :class:`~app.rag.embedder.Embedder` instance.
    audit_logger:
        Optional :class:`~app.audit.logger.AuditLogger` for retrieval audit
        records.  If not provided, retrieval audit logging is skipped.
    """

    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        audit_logger: Optional[AuditLogger] = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._audit = audit_logger

    # ------------------------------------------------------------------
    # BaseTool interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "rag_search"

    @property
    def description(self) -> str:
        return (
            "Semantic search over the local knowledge base (Qdrant vector store). "
            "Use this to retrieve relevant context from ingested documents before "
            "answering questions that require specific domain knowledge. "
            "Optionally filter by source_category (e.g. 'mrpl_public' or 'oisd_standards')."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language query to search for.",
                },
                "collection": {
                    "type": "string",
                    "description": (
                        f"Qdrant collection to search.  "
                        f"Defaults to '{_DEFAULT_COLLECTION}'."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return.  Default 5.",
                    "minimum": 1,
                    "maximum": 20,
                },
                "source_category": {
                    "type": "string",
                    "description": (
                        "Optional: restrict results to a single source category folder "
                        "(e.g. 'mrpl_public' or 'oisd_standards').  "
                        "Omit to search across all categories."
                    ),
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Embed *query*, search Qdrant with status + category filters, and return
        formatted results.

        Never raises — all errors are returned as ``ToolResult(success=False)``.
        """
        query: Optional[str] = kwargs.get("query")
        collection: str = kwargs.get("collection", _DEFAULT_COLLECTION)
        top_k: int = int(kwargs.get("top_k", _DEFAULT_TOP_K))
        source_category: Optional[str] = kwargs.get("source_category")
        # request_id flows from orchestrator via tool_args if provided
        request_id: Optional[str] = kwargs.get("request_id")

        if not query or not query.strip():
            return ToolResult(
                success=False,
                output=None,
                error="rag_search requires a non-empty 'query' argument",
            )

        query = query.strip()

        try:
            # ── Embed the query (same bge-m3 path as ingestion) ───────
            query_vector = await self._embedder.embed_one(query)

            # ── Search Qdrant with status + category filters ───────────
            # search_filtered() excludes status="withdrawn" by default.
            results = self._store.search_filtered(
                collection=collection,
                query_vector=query_vector,
                top_k=top_k,
                source_category=source_category,  # None → no category filter
                exclude_status=["withdrawn"],       # always exclude withdrawn
            )

            # ── Audit: log retrieval with full source attribution ──────
            if self._audit:
                sources_logged = [
                    {
                        "doc_name": r.doc_name or r.source,
                        "page_number": r.page_number,
                        "score": round(r.score, 4),
                        "source_category": r.source_category,
                    }
                    for r in results
                ]
                self._audit.log_event(
                    EventType.RAG_RETRIEVAL,
                    request_id=request_id or "unset",
                    payload={
                        "query": query[:500],
                        "collection": collection,
                        "source_category_filter": source_category,
                        "top_k": top_k,
                        "hits": len(results),
                        "sources": sources_logged,
                    },
                )

            if not results:
                return ToolResult(
                    success=True,
                    output="No relevant documents found in the knowledge base.",
                    metadata={
                        "collection": collection,
                        "hits": 0,
                        "sources": [],
                    },
                )

            # ── Format results as markdown with citation metadata ──────
            lines: list[str] = []
            sources_meta: list[dict[str, Any]] = []

            for i, r in enumerate(results, start=1):
                doc_label = r.doc_name or r.source
                page_label = f"page {r.page_number}" if r.page_number else "unknown page"
                cat_label = r.source_category or "unknown"

                lines.append(
                    f"**[{i}] score={r.score:.3f}** | {doc_label} ({page_label}) | {cat_label}\n"
                    f"> {r.text}"
                )
                sources_meta.append(
                    {
                        "doc_name": doc_label,
                        "page_number": r.page_number,
                        "source_category": r.source_category,
                        "score": round(r.score, 4),
                    }
                )

            formatted = "\n\n".join(lines)

            _log.info(
                "rag_search: query=%r collection=%r category=%r hits=%d",
                query[:80],
                collection,
                source_category,
                len(results),
            )

            return ToolResult(
                success=True,
                output=formatted,
                metadata={
                    "collection": collection,
                    "hits": len(results),
                    "top_score": results[0].score if results else 0.0,
                    "sources": sources_meta,
                },
            )

        except VectorStoreError as exc:
            _log.error("rag_search VectorStoreError: %s", exc)
            return ToolResult(
                success=False,
                output=None,
                error=f"Vector store error: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            _log.error("rag_search unexpected error: %s", exc)
            return ToolResult(
                success=False,
                output=None,
                error=f"Unexpected error during RAG search: {exc}",
            )
