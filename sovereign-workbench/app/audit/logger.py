"""
audit/logger.py
===============
Append-only, JSON-lines structured logger for the Sovereign Workbench.

Design goals
------------
* Every record is a single JSON line — easy to grep, parse, and stream.
* Records are written with an exclusive file lock so concurrent FastAPI
  workers don't interleave partial writes.
* Each record carries a `prev_hash` field (SHA-256 of the previous line's
  raw bytes) so the log forms a hash chain.  Phase E will harden this into
  a fully tamper-evident structure; this implementation seeds that format
  so no schema migration is needed later.
* Network sovereignty: this module never opens a socket.  It only writes
  to a local file path resolved from the environment / config.

Usage
-----
    from app.audit.logger import AuditLogger

    logger = AuditLogger()               # or pass log_path explicitly
    logger.log_model_call(
        request_id="abc-123",
        model_name="qwen25_14b_instruct",
        ollama_tag="qwen2.5:14b-instruct-q4_K_M",
        endpoint="http://localhost:11434",
        prompt_tokens=142,
        response_tokens=87,
        latency_ms=1234.5,
        status="success",
    )
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Internal stdlib logger — used only for logger-internal errors so we don't
# create a circular dependency.
# ---------------------------------------------------------------------------
_internal_log = logging.getLogger("sovereign.audit.internal")


class EventType(str, Enum):
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    ROUTE_DECISION = "route_decision"
    FILE_WRITE = "file_write"
    AGENT_ACTION = "agent_action"
    STARTUP = "startup"
    ERROR = "error"


@dataclass
class AuditRecord:
    """
    Single audit log entry.

    All timestamps are ISO-8601 UTC strings so the log file is both
    human-readable and machine-parseable without context.
    """

    event_type: str
    timestamp_utc: str
    request_id: str
    payload: dict[str, Any]
    # Hash chain fields — populated by AuditLogger before writing.
    sequence: int = 0
    prev_hash: str = "GENESIS"  # sentinel for the very first record
    self_hash: str = ""  # SHA-256 of the serialised record (with self_hash="")


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AuditLogger:
    """
    Thread-safe, append-only, hash-chained audit logger.

    Parameters
    ----------
    log_path:
        Absolute path to the `.jsonl` log file.  Defaults to the value of
        the ``AUDIT_LOG_PATH`` environment variable, or
        ``./logs/audit.jsonl`` if that variable is not set.
    """

    _DEFAULT_LOG_PATH = Path("logs/audit.jsonl")

    def __init__(self, log_path: Optional[Path | str] = None) -> None:
        raw = log_path or os.environ.get("AUDIT_LOG_PATH", str(self._DEFAULT_LOG_PATH))
        self._path = Path(raw).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Serialised state — protects _sequence and _prev_hash across threads.
        self._lock = threading.Lock()
        self._sequence, self._prev_hash = self._recover_chain_state()

        self._log_startup_event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_model_call(
        self,
        *,
        request_id: str,
        model_name: str,
        ollama_tag: str,
        endpoint: str,
        prompt_tokens: int,
        response_tokens: int,
        latency_ms: float,
        status: str,
        error_message: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record a completed call to an Ollama model."""
        payload: dict[str, Any] = {
            "model_name": model_name,
            "ollama_tag": ollama_tag,
            "endpoint": endpoint,
            "prompt_tokens": prompt_tokens,
            "response_tokens": response_tokens,
            "latency_ms": round(latency_ms, 3),
            "status": status,
        }
        if error_message is not None:
            payload["error_message"] = error_message
        if extra:
            payload.update(extra)

        # Sovereignty assertion: the endpoint must be localhost.
        if not self._is_local_endpoint(endpoint):
            self._write_record(
                EventType.ERROR,
                request_id=request_id,
                payload={
                    "violation": "non_local_endpoint_detected",
                    "endpoint": endpoint,
                    "model_name": model_name,
                },
            )
            raise ValueError(
                f"SOVEREIGNTY VIOLATION: model call directed at non-local endpoint "
                f"'{endpoint}'.  All inference must go through localhost:11434."
            )

        self._write_record(EventType.MODEL_CALL, request_id=request_id, payload=payload)

    def log_event(
        self,
        event_type: EventType,
        *,
        request_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Generic event logger for routing decisions, tool calls, etc."""
        self._write_record(event_type, request_id=request_id, payload=payload)

    def log_error(
        self,
        *,
        request_id: str,
        error_type: str,
        message: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        payload: dict[str, Any] = {"error_type": error_type, "message": message}
        if extra:
            payload.update(extra)
        self._write_record(EventType.ERROR, request_id=request_id, payload=payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_local_endpoint(endpoint: str) -> bool:
        """
        Return True only if the endpoint resolves to the local machine.

        Accepted forms: localhost, 127.0.0.1, ::1, 0.0.0.0.
        """
        import urllib.parse

        parsed = urllib.parse.urlparse(endpoint)
        host = parsed.hostname or ""
        return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

    def _recover_chain_state(self) -> tuple[int, str]:
        """
        Re-read the log file to find the last sequence number and hash so
        we can continue the chain after a process restart.
        """
        if not self._path.exists():
            return 0, "GENESIS"

        last_seq = 0
        last_hash = "GENESIS"
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        rec = json.loads(raw_line)
                        seq = int(rec.get("sequence", 0))
                        if seq >= last_seq:
                            last_seq = seq
                            last_hash = rec.get("self_hash", "GENESIS")
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError as exc:
            _internal_log.warning("Could not read existing audit log: %s", exc)

        return last_seq, last_hash

    def _write_record(
        self,
        event_type: EventType,
        *,
        request_id: str,
        payload: dict[str, Any],
    ) -> None:
        ts = datetime.now(tz=timezone.utc).isoformat()

        with self._lock:
            self._sequence += 1
            seq = self._sequence
            prev_hash = self._prev_hash

            record: dict[str, Any] = {
                "event_type": event_type.value,
                "timestamp_utc": ts,
                "request_id": request_id,
                "sequence": seq,
                "prev_hash": prev_hash,
                "self_hash": "",  # placeholder — will be replaced below
                "payload": payload,
            }

            # Compute self_hash over the record with self_hash="" so the
            # field is part of the signed content but has a stable value
            # during hashing.
            canonical = json.dumps(record, sort_keys=True, ensure_ascii=False)
            self_hash = _sha256_of(canonical)
            record["self_hash"] = self_hash

            line = json.dumps(record, ensure_ascii=False) + "\n"

            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    fcntl.flock(fh, fcntl.LOCK_EX)
                    try:
                        fh.write(line)
                        fh.flush()
                        os.fsync(fh.fileno())
                    finally:
                        fcntl.flock(fh, fcntl.LOCK_UN)
            except OSError as exc:
                # Log to stderr only — we must not swallow audit failures.
                _internal_log.error(
                    "AUDIT WRITE FAILURE seq=%d request_id=%s: %s", seq, request_id, exc
                )
                raise RuntimeError(
                    f"Audit log write failed (seq={seq}): {exc}"
                ) from exc

            self._prev_hash = self_hash

    def _log_startup_event(self) -> None:
        self._write_record(
            EventType.STARTUP,
            request_id="SYSTEM",
            payload={
                "log_path": str(self._path),
                "pid": os.getpid(),
                "message": "AuditLogger initialised",
            },
        )

    # ------------------------------------------------------------------
    # Chain verification (utility — useful in tests and Phase E)
    # ------------------------------------------------------------------

    def verify_chain(self) -> tuple[bool, list[str]]:
        """
        Walk the entire log file and verify every hash link.

        Returns
        -------
        (ok, errors)
            ok     — True if the chain is intact.
            errors — list of human-readable violation messages.
        """
        errors: list[str] = []
        prev_hash = "GENESIS"
        expected_seq = 1

        with self._path.open("r", encoding="utf-8") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    rec = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    errors.append(f"Line {lineno}: invalid JSON — {exc}")
                    continue

                seq = rec.get("sequence")
                if seq != expected_seq:
                    errors.append(
                        f"Line {lineno}: sequence gap — expected {expected_seq}, got {seq}"
                    )

                recorded_prev = rec.get("prev_hash")
                if recorded_prev != prev_hash:
                    errors.append(
                        f"Line {lineno} seq={seq}: prev_hash mismatch — "
                        f"expected '{prev_hash}', got '{recorded_prev}'"
                    )

                # Re-derive self_hash: copy the record, set self_hash="" (the
                # placeholder value used during the original hash computation),
                # then re-serialise with the same sort_keys=True to reproduce
                # the exact canonical string that was hashed at write time.
                stored_self = rec.get("self_hash", "")
                rec_for_hash = dict(rec)  # shallow copy — safe for flat JSON
                rec_for_hash["self_hash"] = ""
                canonical = json.dumps(rec_for_hash, sort_keys=True, ensure_ascii=False)
                derived = _sha256_of(canonical)
                if derived != stored_self:
                    errors.append(
                        f"Line {lineno} seq={seq}: self_hash mismatch — record may have been tampered"
                    )


                prev_hash = stored_self
                expected_seq += 1

        return (len(errors) == 0), errors
