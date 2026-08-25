"""
tools/rag_search.py
===================
``rag_search`` tool — semantic search over the local Qdrant knowledge base.

The tool is backed by:
* :class:`~app.rag.store.VectorStore`  — Qdrant at localhost:6333.
* :class:`~app.rag.embedder.Embedder` — bge-m3 via OllamaClient.

The orchestrator passes it a query string and (optionally) a collection name.
The tool embeds the query, searches Qdrant, and returns a formatted markdown
snippet list that the agent can read directly.

Input schema
------------
{
    "query":      required str  — natural language query
    "collection": optional str  — target collection (default: "docs")
    "top_k":      optional int  — max results (default: 5)
}

Output (on success)
-------------------
A markdown string of ranked results:

    **[1] score=0.87** (source: /path/to/file.txt)
    > ...chunk text...

    **[2] score=0.81** (source: /path/to/other.md)
    > ...

Sovereignty note
----------------
Embedding calls go through OllamaClient → localhost:11434.
Qdrant calls go to localhost:6333.  No external network traffic.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.rag.embedder import Embedder
from app.rag.store import VectorStore, VectorStoreError
from app.tools.base import BaseTool, ToolResult

_log = logging.getLogger("sovereign.tools.rag_search")

_DEFAULT_COLLECTION = "docs"
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
    """

    def __init__(self, store: VectorStore, embedder: Embedder) -> None:
        self._store = store
        self._embedder = embedder

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
            "answering questions that require specific domain knowledge."
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
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Embed *query*, search Qdrant, and return formatted results.

        Never raises — all errors are returned as ``ToolResult(success=False)``.
        """
        query: Optional[str] = kwargs.get("query")
        collection: str = kwargs.get("collection", _DEFAULT_COLLECTION)
        top_k: int = int(kwargs.get("top_k", _DEFAULT_TOP_K))

        if not query or not query.strip():
            return ToolResult(
                success=False,
                output=None,
                error="rag_search requires a non-empty 'query' argument",
            )

        try:
            # Embed the query
            query_vector = await self._embedder.embed_one(query.strip())

            # Search Qdrant
            results = self._store.search(
                collection=collection,
                query_vector=query_vector,
                top_k=top_k,
            )

            if not results:
                return ToolResult(
                    success=True,
                    output="No relevant documents found in the knowledge base.",
                    metadata={"collection": collection, "hits": 0},
                )

            # Format results as markdown
            lines: list[str] = []
            for i, r in enumerate(results, start=1):
                lines.append(
                    f"**[{i}] score={r.score:.3f}** (source: {r.source})\n> {r.text}"
                )
            formatted = "\n\n".join(lines)

            _log.info(
                "rag_search: query=%r collection=%r hits=%d",
                query[:80],
                collection,
                len(results),
            )

            return ToolResult(
                success=True,
                output=formatted,
                metadata={
                    "collection": collection,
                    "hits": len(results),
                    "top_score": results[0].score if results else 0.0,
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
