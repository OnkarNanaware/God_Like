"""
rag/embedder.py
===============
Thin embedding wrapper around :class:`~app.models.ollama_client.OllamaClient`.

Design
------
* Sequential (not concurrent): Ollama is single-GPU, so batching concurrent
  requests provides no throughput benefit and risks queue contention.
* ``embed_batch`` calls ``ollama_client.embeddings()`` once per text.
  For Phase C doc sizes (hundreds of chunks) this is acceptable.  A future
  optimisation could chunk requests to Ollama's native batch endpoint if one
  becomes available.

Sovereignty note
----------------
Every embedding call goes to ``localhost:11434`` via ``OllamaClient`` —
no external network calls ever.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

_log = logging.getLogger("sovereign.rag.embedder")


@runtime_checkable
class EmbeddingClientProtocol(Protocol):
    """
    Structural protocol for the embedding client.

    Any object with an async ``embeddings(text, *, request_id)`` method
    satisfies this interface — used for easy mocking in tests.
    """

    async def embeddings(
        self,
        text: str,
        *,
        request_id: str | None = None,
    ) -> list[float]:
        ...


class Embedder:
    """
    Sequential batch embedder backed by an :class:`EmbeddingClientProtocol`.

    Parameters
    ----------
    client:
        An :class:`~app.models.ollama_client.OllamaClient` (or any object
        satisfying :class:`EmbeddingClientProtocol`).  Must be initialised
        with an embedding-modality model (``bge_m3``).
    """

    def __init__(self, client: EmbeddingClientProtocol) -> None:
        self._client = client

    async def embed_one(
        self,
        text: str,
        *,
        request_id: str | None = None,
    ) -> list[float]:
        """Embed a single string.  Returns a ``list[float]`` vector."""
        return await self._client.embeddings(text, request_id=request_id)

    async def embed_batch(
        self,
        texts: list[str],
        *,
        request_id: str | None = None,
    ) -> list[list[float]]:
        """
        Embed a list of strings sequentially.

        Parameters
        ----------
        texts:
            Non-empty list of strings to embed.
        request_id:
            Shared correlation ID for audit logging.

        Returns
        -------
        Parallel list of embedding vectors.  ``result[i]`` is the vector
        for ``texts[i]``.

        Raises
        ------
        ValueError  if *texts* is empty.
        """
        if not texts:
            raise ValueError("embed_batch requires at least one text")

        vectors: list[list[float]] = []
        for i, text in enumerate(texts):
            _log.debug("Embedding chunk %d/%d (len=%d chars)", i + 1, len(texts), len(text))
            vec = await self._client.embeddings(text, request_id=request_id)
            vectors.append(vec)

        _log.info("embed_batch: embedded %d chunk(s), dim=%d", len(texts), len(vectors[0]))
        return vectors
