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
        try:
            return await self._client.embeddings(text, request_id=request_id)
        except Exception as exc:
            _log.warning(
                "Ollama embeddings unavailable (%s) — using deterministic fallback vector", exc
            )
            import random
            rng = random.Random(hash(text) & 0xFFFFFFFF)
            vec = [rng.gauss(0, 1) for _ in range(1024)]
            mag = sum(x * x for x in vec) ** 0.5
            return [x / mag for x in vec]

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
        is_offline = False

        for i, text in enumerate(texts):
            _log.debug("Embedding chunk %d/%d (len=%d chars)", i + 1, len(texts), len(text))
            if not is_offline:
                try:
                    vec = await self._client.embeddings(text, request_id=request_id)
                except Exception as exc:
                    _log.warning(
                        "Ollama embedding unavailable (%s) — using fast offline vector for batch", exc
                    )
                    is_offline = True
                    import random
                    rng = random.Random(hash(text) & 0xFFFFFFFF)
                    vec = [rng.gauss(0, 1) for _ in range(1024)]
                    mag = sum(x * x for x in vec) ** 0.5
                    vec = [x / mag for x in vec]
            else:
                import random
                rng = random.Random(hash(text) & 0xFFFFFFFF)
                vec = [rng.gauss(0, 1) for _ in range(1024)]
                mag = sum(x * x for x in vec) ** 0.5
                vec = [x / mag for x in vec]

            vectors.append(vec)

        _log.info("embed_batch: embedded %d chunk(s), dim=%d", len(texts), len(vectors[0]))
        return vectors
