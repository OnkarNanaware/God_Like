"""
rag/store.py
============
Qdrant vector-store wrapper for the Sovereign Workbench RAG pipeline.

Design decisions
----------------
* One Qdrant collection = one knowledge-base namespace (e.g. "docs", "code").
  The caller controls the collection name via the ``/ingest`` API.
* Collections are created on first upsert with ``COSINE`` distance and
  ``size=1024`` (bge-m3 output dimension).  If you ever swap the embedding
  model, drop and recreate the collection — the dimension will differ.
* All Qdrant calls catch ``qdrant_client`` exceptions specifically and re-raise
  as ``VectorStoreError`` so callers don't need to import Qdrant internals.

Sovereignty note
----------------
Qdrant is always reached at ``localhost:6333``.  The client is created with
``prefer_grpc=False`` to keep traffic on plain HTTP/REST (avoids gRPC
certificate edge-cases in offline environments).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

_log = logging.getLogger("sovereign.rag.store")

# bge-m3 produces 1024-dimensional vectors.
# Change this constant if you ever swap the embedding model,
# then drop + recreate all Qdrant collections.
_EMBEDDING_DIM = 1024
_DISTANCE = "Cosine"
_QDRANT_HOST = "localhost"
_QDRANT_PORT = 6333


class VectorStoreError(RuntimeError):
    """Raised on any Qdrant operation failure."""


@dataclass(frozen=True)
class SearchResult:
    """A single ranked result from :meth:`VectorStore.search`."""

    score: float
    text: str
    source: str        # originating file path / URL
    chunk_id: str      # stable UUID for this chunk
    collection: str


class VectorStore:
    """
    Local Qdrant vector store.

    Parameters
    ----------
    host, port:
        Qdrant server address.  Always localhost in the sovereign workbench.
    """

    def __init__(
        self,
        host: str = _QDRANT_HOST,
        port: int = _QDRANT_PORT,
    ) -> None:
        try:
            from qdrant_client import QdrantClient  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "qdrant-client is required.  Install with:  pip install qdrant-client"
            ) from exc

        self._client = QdrantClient(host=host, port=port, prefer_grpc=False)
        _log.info("VectorStore connected to Qdrant at %s:%d", host, port)

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def _ensure_collection(self, collection: str) -> None:
        """Create *collection* if it doesn't already exist."""
        try:
            from qdrant_client.models import Distance, VectorParams  # type: ignore[import]

            existing = {c.name for c in self._client.get_collections().collections}
            if collection not in existing:
                self._client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(size=_EMBEDDING_DIM, distance=Distance.COSINE),
                )
                _log.info("Created Qdrant collection '%s' (dim=%d)", collection, _EMBEDDING_DIM)
        except Exception as exc:
            raise VectorStoreError(
                f"Failed to ensure collection '{collection}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(
        self,
        collection: str,
        chunks: list[str],
        vectors: list[list[float]],
        source: str,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> list[str]:
        """
        Upsert a batch of chunk+vector pairs into *collection*.

        Parameters
        ----------
        collection:
            Target Qdrant collection name.
        chunks:
            Raw text strings (stored as payload for retrieval).
        vectors:
            Parallel list of embedding vectors.  ``len(vectors) == len(chunks)``.
        source:
            File path or identifier logged in each point's payload.
        extra_metadata:
            Optional extra key/value pairs merged into every point's payload.

        Returns
        -------
        List of point IDs (UUIDs) for the upserted chunks.

        Raises
        ------
        ValueError         if ``len(chunks) != len(vectors)`` or either is empty.
        VectorStoreError   on any Qdrant failure.
        """
        if len(chunks) != len(vectors):
            raise ValueError(
                f"chunks ({len(chunks)}) and vectors ({len(vectors)}) must have the same length"
            )
        if not chunks:
            raise ValueError("Cannot upsert an empty batch")

        self._ensure_collection(collection)

        try:
            from qdrant_client.models import PointStruct  # type: ignore[import]
        except ImportError as exc:
            raise VectorStoreError("qdrant-client not installed") from exc

        point_ids: list[str] = []
        points: list[Any] = []

        for text, vector in zip(chunks, vectors):
            point_id = str(uuid.uuid4())
            payload: dict[str, Any] = {"text": text, "source": source}
            if extra_metadata:
                payload.update(extra_metadata)
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))
            point_ids.append(point_id)

        try:
            self._client.upsert(collection_name=collection, points=points)
        except Exception as exc:
            raise VectorStoreError(
                f"Qdrant upsert to collection '{collection}' failed: {exc}"
            ) from exc

        _log.info(
            "Upserted %d points into collection '%s' (source=%s)",
            len(points),
            collection,
            source,
        )
        return point_ids

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[SearchResult]:
        """
        Semantic search over *collection*.

        Parameters
        ----------
        collection:
            Target Qdrant collection name.
        query_vector:
            Embedding of the query text (same model as ingestion time).
        top_k:
            Maximum number of results to return.

        Returns
        -------
        List of :class:`SearchResult` objects sorted by score descending.

        Raises
        ------
        VectorStoreError  if the collection doesn't exist or Qdrant errors.
        """
        try:
            hits = self._client.search(
                collection_name=collection,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            raise VectorStoreError(
                f"Qdrant search on collection '{collection}' failed: {exc}"
            ) from exc

        results: list[SearchResult] = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                SearchResult(
                    score=float(hit.score),
                    text=payload.get("text", ""),
                    source=payload.get("source", ""),
                    chunk_id=str(hit.id),
                    collection=collection,
                )
            )
        return results
