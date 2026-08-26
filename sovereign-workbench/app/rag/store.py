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
* **Deterministic point IDs**: ``upsert_points()`` accepts caller-computed
  stable UUIDs derived from ``sha256(doc_name + page + chunk_idx)[:16]``.
  Re-running ingestion therefore *updates* rather than *duplicates* points.

Sovereignty note
----------------
Qdrant is always reached at ``localhost:6333``.  The client is created with
``prefer_grpc=False`` to keep traffic on plain HTTP/REST (avoids gRPC
certificate edge-cases in offline environments).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# Chunk metadata schema
# ---------------------------------------------------------------------------

def make_chunk_id(doc_name: str, page_number: int, chunk_index: int) -> str:
    """
    Deterministic UUID for a chunk — stable across re-ingestion.

    Derived from SHA-256(``doc_name|page_number|chunk_index``), truncated to
    16 bytes and interpreted as a UUID.  Re-ingesting the same page/chunk
    always produces the same ID, so Qdrant upsert semantics update rather than
    duplicate.

    Parameters
    ----------
    doc_name:
        File basename (e.g. ``"environment_report.pdf"``).
    page_number:
        1-indexed page number (0 for non-PDF sources).
    chunk_index:
        Global chunk index across the document.

    Returns
    -------
    UUID string (``str(uuid.UUID(...))``) suitable for Qdrant point ID.
    """
    key = f"{doc_name}|{page_number}|{chunk_index}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16]))


@dataclass(frozen=True)
class SearchResult:
    """A single ranked result from :meth:`VectorStore.search` or :meth:`VectorStore.search_filtered`."""

    score: float
    text: str
    source: str        # originating file path / URL
    chunk_id: str      # stable UUID for this chunk
    collection: str
    # Phase C metadata fields — populated from Qdrant payload.
    doc_name: str = ""
    source_category: str = ""
    page_number: int = 0
    status: str = "in_force"
    confidentiality: str = "public"
    edition_date: Optional[str] = None


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
    # Write — Phase C: upsert_points() with full metadata + deterministic IDs
    # ------------------------------------------------------------------

    def upsert_points(
        self,
        collection: str,
        points: list[dict[str, Any]],
    ) -> list[str]:
        """
        Upsert pre-built points with full metadata into *collection*.

        Each element of *points* must be a dict with keys:
            ``id``       — deterministic UUID string (from :func:`make_chunk_id`)
            ``vector``   — ``list[float]`` embedding vector
            ``payload``  — dict with ``text`` + all metadata fields

        Parameters
        ----------
        collection:
            Target Qdrant collection name.
        points:
            List of point dicts.

        Returns
        -------
        List of point IDs that were upserted.

        Raises
        ------
        ValueError         if *points* is empty.
        VectorStoreError   on any Qdrant failure.
        """
        if not points:
            raise ValueError("Cannot upsert an empty batch")

        self._ensure_collection(collection)

        try:
            from qdrant_client.models import PointStruct  # type: ignore[import]
        except ImportError as exc:
            raise VectorStoreError("qdrant-client not installed") from exc

        qdrant_points: list[Any] = []
        point_ids: list[str] = []

        for p in points:
            qdrant_points.append(
                PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p["payload"],
                )
            )
            point_ids.append(p["id"])

        try:
            self._client.upsert(collection_name=collection, points=qdrant_points)
        except Exception as exc:
            raise VectorStoreError(
                f"Qdrant upsert to collection '{collection}' failed: {exc}"
            ) from exc

        _log.info(
            "upsert_points: %d points → collection '%s'",
            len(qdrant_points),
            collection,
        )
        return point_ids

    # ------------------------------------------------------------------
    # Write — backward-compat upsert() (random UUIDs, flat metadata)
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

        **Backward-compatible** wrapper kept for Phase B tests and the old
        :class:`~app.rag.ingestor.Ingestor`.  New code should prefer
        :meth:`upsert_points` which supports deterministic IDs and full
        metadata.

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
        points_list: list[Any] = []

        for text, vector in zip(chunks, vectors):
            point_id = str(uuid.uuid4())
            payload: dict[str, Any] = {"text": text, "source": source}
            if extra_metadata:
                payload.update(extra_metadata)
            points_list.append(PointStruct(id=point_id, vector=vector, payload=payload))
            point_ids.append(point_id)

        try:
            self._client.upsert(collection_name=collection, points=points_list)
        except Exception as exc:
            raise VectorStoreError(
                f"Qdrant upsert to collection '{collection}' failed: {exc}"
            ) from exc

        _log.info(
            "Upserted %d points into collection '%s' (source=%s)",
            len(points_list),
            collection,
            source,
        )
        return point_ids

    # ------------------------------------------------------------------
    # Read — backward-compat search() (no filter)
    # ------------------------------------------------------------------

    def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[SearchResult]:
        """
        Semantic search over *collection* with no payload filter.

        **Backward-compatible** — kept for Phase B / existing tests.
        New code should use :meth:`search_filtered` which excludes withdrawn
        chunks and supports category scoping.

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

        return [self._hit_to_result(hit, collection) for hit in hits]

    # ------------------------------------------------------------------
    # Read — search_filtered() (Phase C: status + category filters)
    # ------------------------------------------------------------------

    def search_filtered(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 5,
        source_category: Optional[str] = None,
        exclude_status: Optional[list[str]] = None,
    ) -> list[SearchResult]:
        """
        Semantic search over *collection* with mandatory status/category filters.

        This is the preferred search method for all Phase C+ retrieval.  It
        always excludes withdrawn chunks (unless *exclude_status* is explicitly
        set to ``[]``), and optionally scopes results to a single
        ``source_category``.

        Parameters
        ----------
        collection:
            Target Qdrant collection name.
        query_vector:
            Embedding of the query text (same model as ingestion time).
        top_k:
            Maximum number of results to return.
        source_category:
            If provided, only chunks with this ``source_category`` payload value
            are returned (e.g. ``"mrpl_public"`` | ``"oisd_standards"``).
        exclude_status:
            Chunks whose ``status`` payload value is in this list are excluded.
            Defaults to ``["withdrawn"]``.  Pass ``[]`` to disable filtering.

        Returns
        -------
        List of :class:`SearchResult` objects sorted by score descending.

        Raises
        ------
        VectorStoreError  if the collection doesn't exist or Qdrant errors.
        """
        if exclude_status is None:
            exclude_status = ["withdrawn"]

        try:
            from qdrant_client.models import (  # type: ignore[import]
                FieldCondition,
                Filter,
                MatchValue,
                MatchAny,
            )
        except ImportError as exc:
            raise VectorStoreError("qdrant-client not installed") from exc

        must_conditions: list[Any] = []
        must_not_conditions: list[Any] = []

        # ── Category filter (must match) ──────────────────────────────
        if source_category:
            must_conditions.append(
                FieldCondition(
                    key="source_category",
                    match=MatchValue(value=source_category),
                )
            )

        # ── Status filter (must NOT be in excluded list) ──────────────
        if exclude_status:
            must_not_conditions.append(
                FieldCondition(
                    key="status",
                    match=MatchAny(any=exclude_status),
                )
            )

        query_filter = None
        if must_conditions or must_not_conditions:
            query_filter = Filter(
                must=must_conditions if must_conditions else None,
                must_not=must_not_conditions if must_not_conditions else None,
            )

        try:
            hits = self._client.search(
                collection_name=collection,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True,
                query_filter=query_filter,
            )
        except Exception as exc:
            raise VectorStoreError(
                f"Qdrant search_filtered on collection '{collection}' failed: {exc}"
            ) from exc

        return [self._hit_to_result(hit, collection) for hit in hits]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hit_to_result(self, hit: Any, collection: str) -> SearchResult:
        """Convert a raw Qdrant ScoredPoint into a typed :class:`SearchResult`."""
        payload = hit.payload or {}
        return SearchResult(
            score=float(hit.score),
            text=payload.get("text", ""),
            source=payload.get("source", ""),
            chunk_id=str(hit.id),
            collection=collection,
            doc_name=payload.get("doc_name", ""),
            source_category=payload.get("source_category", ""),
            page_number=int(payload.get("page_number", 0)),
            status=payload.get("status", "in_force"),
            confidentiality=payload.get("confidentiality", "public"),
            edition_date=payload.get("edition_date"),
        )
