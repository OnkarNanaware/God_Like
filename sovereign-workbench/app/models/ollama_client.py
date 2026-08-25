"""
models/ollama_client.py
=======================
Thin, type-safe wrapper around Ollama's OpenAI-compatible REST API.

Network sovereignty guarantee
------------------------------
This module contains exactly one HTTP client (`httpx.AsyncClient`) whose
`base_url` is set from the model registry — which is validated in
`AuditLogger` to be localhost-only.  There is no fallback path that would
ever contact an external host.

The client does NOT import `openai`, `anthropic`, or any other SDK that
might embed telemetry or update-check routines.  We talk to Ollama's raw
HTTP API directly.

Supported call modes
---------------------
* `chat_completion`   — standard non-streaming chat.
* `chat_stream`       — async generator that yields text deltas.
* `embeddings`        — returns a list[float] embedding vector.

All public methods accept and propagate a `request_id` string for audit
correlation.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncGenerator, Optional

import httpx
import yaml
from pathlib import Path

from app.audit.logger import AuditLogger, EventType

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_REGISTRY_PATH = Path(__file__).parent.parent / "config" / "models.yaml"
_DEFAULT_TIMEOUT_SECONDS = 120.0  # generous for large local models
_CONNECT_TIMEOUT_SECONDS = 5.0


def _load_model_registry() -> dict[str, dict[str, Any]]:
    """
    Load models.yaml and return a dict keyed by `name`.

    Raises
    ------
    FileNotFoundError  if models.yaml is missing.
    ValueError         if a model entry is malformed.
    """
    with _REGISTRY_PATH.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    registry: dict[str, dict[str, Any]] = {}
    required_keys = {"name", "ollama_tag", "endpoint", "modality", "context_length"}
    for entry in raw.get("models", []):
        missing = required_keys - entry.keys()
        if missing:
            raise ValueError(
                f"Model registry entry missing required keys: {missing} — entry: {entry}"
            )
        # Enforce local-only endpoints at load time so misconfiguration is
        # caught at startup, not at request time.
        endpoint: str = entry["endpoint"]
        import urllib.parse

        host = urllib.parse.urlparse(endpoint).hostname or ""
        if host not in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
            raise ValueError(
                f"SOVEREIGNTY VIOLATION in models.yaml: model '{entry['name']}' "
                f"has a non-local endpoint '{endpoint}'.  "
                f"All endpoints must resolve to localhost."
            )
        registry[entry["name"]] = entry

    return registry


# Module-level registry — loaded once at import time.
MODEL_REGISTRY: dict[str, dict[str, Any]] = _load_model_registry()


# ---------------------------------------------------------------------------
# Response dataclasses (avoid Pydantic in this low-level module to keep
# the dependency footprint minimal; we'll use Pydantic at the API layer).
# ---------------------------------------------------------------------------


class OllamaResponse:
    """Parsed response from a non-streaming chat completion."""

    __slots__ = (
        "request_id",
        "model_name",
        "ollama_tag",
        "content",
        "prompt_tokens",
        "response_tokens",
        "total_tokens",
        "latency_ms",
        "raw",
    )

    def __init__(
        self,
        request_id: str,
        model_name: str,
        ollama_tag: str,
        content: str,
        prompt_tokens: int,
        response_tokens: int,
        total_tokens: int,
        latency_ms: float,
        raw: dict[str, Any],
    ) -> None:
        self.request_id = request_id
        self.model_name = model_name
        self.ollama_tag = ollama_tag
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.response_tokens = response_tokens
        self.total_tokens = total_tokens
        self.latency_ms = latency_ms
        self.raw = raw

    def __repr__(self) -> str:
        return (
            f"OllamaResponse(model={self.ollama_tag!r}, "
            f"tokens={self.total_tokens}, latency_ms={self.latency_ms:.1f})"
        )


# ---------------------------------------------------------------------------
# OllamaClient
# ---------------------------------------------------------------------------


class OllamaClient:
    """
    Async HTTP client for Ollama's OpenAI-compatible endpoint.

    Parameters
    ----------
    model_name:
        Key in `models.yaml` (e.g. "qwen25_14b_instruct").
    audit_logger:
        Shared AuditLogger instance.  The client will log every call.
    timeout:
        Total request timeout in seconds.  Increase for very long completions.
    """

    def __init__(
        self,
        model_name: str,
        audit_logger: AuditLogger,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if model_name not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model '{model_name}'.  "
                f"Available models: {list(MODEL_REGISTRY)}"
            )

        self._model_cfg: dict[str, Any] = MODEL_REGISTRY[model_name]
        self._model_name = model_name
        self._ollama_tag: str = self._model_cfg["ollama_tag"]
        self._endpoint: str = self._model_cfg["endpoint"]
        self._audit = audit_logger

        # Single httpx client per OllamaClient instance.
        # base_url is always localhost (validated at registry load time).
        self._http = httpx.AsyncClient(
            base_url=self._endpoint,
            timeout=httpx.Timeout(timeout, connect=_CONNECT_TIMEOUT_SECONDS),
            # Explicitly disable any proxy environment variables so a
            # misconfigured HTTPS_PROXY on the host cannot route our
            # inference traffic through an external server.
            trust_env=False,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        request_id: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> OllamaResponse:
        """
        Send a chat-completion request to Ollama and return the full response.

        Parameters
        ----------
        messages:
            List of ``{"role": ..., "content": ...}`` dicts.
        request_id:
            Caller-supplied correlation ID.  A UUID is generated if omitted.
        temperature:
            Sampling temperature (0 = deterministic).
        max_tokens:
            Maximum tokens to generate.
        extra_body:
            Additional Ollama-specific parameters merged into the request body.

        Raises
        ------
        OllamaConnectionError  if Ollama is not reachable.
        OllamaAPIError         if Ollama returns a non-2xx status.
        """
        request_id = request_id or str(uuid.uuid4())
        body: dict[str, Any] = {
            "model": self._ollama_tag,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "options": {},
        }
        if extra_body:
            body.update(extra_body)

        t0 = time.monotonic()
        try:
            response = await self._http.post(
                "/v1/chat/completions",
                json=body,
            )
        except httpx.ConnectError as exc:
            self._audit.log_error(
                request_id=request_id,
                error_type="OllamaConnectionError",
                message=(
                    f"Ollama not reachable at {self._endpoint} — "
                    f"is `ollama serve` running?  Detail: {exc}"
                ),
            )
            raise OllamaConnectionError(
                f"Ollama not reachable at {self._endpoint} — "
                f"is `ollama serve` running?"
            ) from exc
        except httpx.TimeoutException as exc:
            self._audit.log_error(
                request_id=request_id,
                error_type="OllamaTimeoutError",
                message=f"Request timed out after {_DEFAULT_TIMEOUT_SECONDS}s: {exc}",
            )
            raise OllamaTimeoutError(
                f"Ollama request timed out after {_DEFAULT_TIMEOUT_SECONDS}s — "
                f"the model may still be loading."
            ) from exc

        latency_ms = (time.monotonic() - t0) * 1000.0

        if response.status_code != 200:
            error_body = _safe_read_body(response)
            self._audit.log_model_call(
                request_id=request_id,
                model_name=self._model_name,
                ollama_tag=self._ollama_tag,
                endpoint=self._endpoint,
                prompt_tokens=0,
                response_tokens=0,
                latency_ms=latency_ms,
                status="error",
                error_message=f"HTTP {response.status_code}: {error_body}",
            )
            raise OllamaAPIError(
                f"Ollama returned HTTP {response.status_code}: {error_body}"
            )

        data: dict[str, Any] = response.json()
        usage = data.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        response_tokens = int(usage.get("completion_tokens", 0))
        total_tokens = int(usage.get("total_tokens", prompt_tokens + response_tokens))

        content = data["choices"][0]["message"]["content"]

        self._audit.log_model_call(
            request_id=request_id,
            model_name=self._model_name,
            ollama_tag=self._ollama_tag,
            endpoint=self._endpoint,
            prompt_tokens=prompt_tokens,
            response_tokens=response_tokens,
            latency_ms=latency_ms,
            status="success",
        )

        return OllamaResponse(
            request_id=request_id,
            model_name=self._model_name,
            ollama_tag=self._ollama_tag,
            content=content,
            prompt_tokens=prompt_tokens,
            response_tokens=response_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            raw=data,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        request_id: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """
        Stream a chat-completion response, yielding text deltas.

        The first yielded item is the empty string used to open the stream;
        subsequent items are content deltas.  The caller is responsible for
        accumulating them.

        Audit logging happens at stream-close time (once total tokens are
        known from the final `[DONE]` chunk or when usage is available).
        """
        request_id = request_id or str(uuid.uuid4())
        body: dict[str, Any] = {
            "model": self._ollama_tag,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream_options": {"include_usage": True},
        }

        t0 = time.monotonic()
        prompt_tokens = 0
        response_tokens = 0
        accumulated_content = ""

        try:
            async with self._http.stream("POST", "/v1/chat/completions", json=body) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    self._audit.log_error(
                        request_id=request_id,
                        error_type="OllamaAPIError",
                        message=f"HTTP {resp.status_code}: {error_body.decode()[:500]}",
                    )
                    raise OllamaAPIError(
                        f"Ollama returned HTTP {resp.status_code} for stream request"
                    )

                async for raw_line in resp.aiter_lines():
                    if not raw_line or raw_line == "data: [DONE]":
                        continue
                    if raw_line.startswith("data: "):
                        raw_line = raw_line[len("data: "):]
                    try:
                        chunk = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue

                    # Extract usage if present (final chunk)
                    if "usage" in chunk and chunk["usage"]:
                        usage = chunk["usage"]
                        prompt_tokens = int(usage.get("prompt_tokens", prompt_tokens))
                        response_tokens = int(
                            usage.get("completion_tokens", response_tokens)
                        )

                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {}).get("content", "")
                        if delta:
                            accumulated_content += delta
                            yield delta

        except httpx.ConnectError as exc:
            self._audit.log_error(
                request_id=request_id,
                error_type="OllamaConnectionError",
                message=f"Ollama not reachable at {self._endpoint}: {exc}",
            )
            raise OllamaConnectionError(
                f"Ollama not reachable at {self._endpoint} — is `ollama serve` running?"
            ) from exc

        finally:
            latency_ms = (time.monotonic() - t0) * 1000.0
            # Best-effort audit log — even if the stream was interrupted.
            try:
                self._audit.log_model_call(
                    request_id=request_id,
                    model_name=self._model_name,
                    ollama_tag=self._ollama_tag,
                    endpoint=self._endpoint,
                    prompt_tokens=prompt_tokens,
                    response_tokens=response_tokens,
                    latency_ms=latency_ms,
                    status="success" if accumulated_content else "empty_stream",
                )
            except Exception:  # noqa: BLE001 — must not re-raise in a generator finally
                pass

    async def embeddings(
        self,
        text: str,
        *,
        request_id: Optional[str] = None,
    ) -> list[float]:
        """
        Generate an embedding vector for `text` using an embedding-modality model.

        Raises
        ------
        ValueError            if this client's model is not an embedding model.
        OllamaConnectionError if Ollama is not reachable.
        """
        if self._model_cfg.get("modality") != "embedding":
            raise ValueError(
                f"Model '{self._model_name}' has modality "
                f"'{self._model_cfg.get('modality')}', not 'embedding'.  "
                f"Use bge_m3 for embeddings."
            )

        request_id = request_id or str(uuid.uuid4())
        body = {"model": self._ollama_tag, "input": text}

        t0 = time.monotonic()
        try:
            response = await self._http.post("/v1/embeddings", json=body)
        except httpx.ConnectError as exc:
            raise OllamaConnectionError(
                f"Ollama not reachable at {self._endpoint} — is `ollama serve` running?"
            ) from exc

        latency_ms = (time.monotonic() - t0) * 1000.0

        if response.status_code != 200:
            raise OllamaAPIError(
                f"Ollama embedding returned HTTP {response.status_code}: "
                f"{_safe_read_body(response)}"
            )

        data = response.json()
        vector: list[float] = data["data"][0]["embedding"]

        self._audit.log_model_call(
            request_id=request_id,
            model_name=self._model_name,
            ollama_tag=self._ollama_tag,
            endpoint=self._endpoint,
            prompt_tokens=len(text.split()),  # approximation; Ollama may not report
            response_tokens=0,
            latency_ms=latency_ms,
            status="success",
            extra={"embedding_dims": len(vector)},
        )

        return vector

    async def aclose(self) -> None:
        """Close the underlying HTTP client.  Call on application shutdown."""
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def ollama_tag(self) -> str:
        return self._ollama_tag

    @property
    def endpoint(self) -> str:
        return self._endpoint


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class OllamaConnectionError(RuntimeError):
    """Raised when Ollama's HTTP endpoint is not reachable."""


class OllamaTimeoutError(RuntimeError):
    """Raised when a request to Ollama times out."""


class OllamaAPIError(RuntimeError):
    """Raised when Ollama returns a non-2xx HTTP status."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_read_body(response: httpx.Response, max_chars: int = 500) -> str:
    try:
        return response.text[:max_chars]
    except Exception:  # noqa: BLE001
        return "<unreadable body>"
