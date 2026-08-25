"""
tools/file_read.py
==================
``file_read`` — reads a local file and returns its content.

This is the first concrete tool implementation and is intentionally simple.
It exists to prove the orchestrator's control-flow (success path, error path,
retry path) before we add tools with real complexity.

Safety constraints
------------------
* Path traversal guard: the resolved absolute path is returned in ``metadata``
  so the orchestrator can log what was actually read, not just what was asked for.
* No network calls — reads only the local filesystem.
* File size cap (``MAX_BYTES``): returns a truncation notice rather than dumping
  a 500 MB binary into the orchestrator's context.
* Binary detection: if the file contains null bytes in the first 8 KB, it is
  treated as binary and an error is returned with a helpful message.

The tool does NOT enforce access control — that is the orchestrator's concern
(and ultimately the nftables egress rules in Phase E).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool, ToolResult

_log = logging.getLogger("sovereign.tools.file_read")

# Maximum bytes to read — prevents the orchestrator context from exploding.
MAX_BYTES: int = 512 * 1024  # 512 KB
_BINARY_SNIFF_BYTES: int = 8 * 1024


class FileReadTool(BaseTool):
    """
    Read the contents of a local file.

    Input schema fields
    -------------------
    path : str
        Absolute or relative path to the file.  Relative paths are resolved
        against the process working directory.
    encoding : str, optional
        Text encoding.  Defaults to "utf-8".

    Output
    ------
    ``ToolResult.output`` is a ``str`` containing the file text (possibly
    truncated at ``MAX_BYTES`` characters with a notice appended).

    On failure, ``ToolResult.output`` is ``None`` and ``ToolResult.error``
    contains a human-readable message suitable for feeding back to the model
    in a re-plan step.
    """

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def description(self) -> str:
        return (
            "Read the text content of a local file by path. "
            "Returns the file content as a string, or an error if the file "
            "cannot be found or read."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to read.",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding (default: utf-8).",
                    "default": "utf-8",
                },
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Read the file at ``path`` and return its content.

        Never raises — all failures are captured in ``ToolResult.error``.
        """
        path_raw: str | None = kwargs.get("path")
        if not path_raw:
            return ToolResult(
                success=False,
                output=None,
                error="'path' argument is required but was not provided.",
            )

        encoding: str = kwargs.get("encoding", "utf-8")
        resolved: Path = Path(path_raw).expanduser().resolve()

        # ── Existence check ────────────────────────────────────────────────
        if not resolved.exists():
            return ToolResult(
                success=False,
                output=None,
                error=f"File not found: '{resolved}'.  Check that the path is correct.",
                metadata={"requested_path": path_raw, "resolved_path": str(resolved)},
            )

        if not resolved.is_file():
            return ToolResult(
                success=False,
                output=None,
                error=f"Path exists but is not a regular file: '{resolved}'.",
                metadata={"requested_path": path_raw, "resolved_path": str(resolved)},
            )

        # ── Binary detection ───────────────────────────────────────────────
        try:
            with resolved.open("rb") as fh:
                sniff = fh.read(_BINARY_SNIFF_BYTES)
        except OSError as exc:
            return ToolResult(
                success=False,
                output=None,
                error=f"Cannot read file '{resolved}': {exc}",
                metadata={"requested_path": path_raw, "resolved_path": str(resolved)},
            )

        if b"\x00" in sniff:
            return ToolResult(
                success=False,
                output=None,
                error=(
                    f"File '{resolved}' appears to be binary (null bytes detected). "
                    f"Only text files are supported by file_read."
                ),
                metadata={
                    "requested_path": path_raw,
                    "resolved_path": str(resolved),
                    "file_size_bytes": resolved.stat().st_size,
                    "is_binary": True,
                },
            )

        # ── Read content ───────────────────────────────────────────────────
        file_size = resolved.stat().st_size
        truncated = file_size > MAX_BYTES

        try:
            with resolved.open("r", encoding=encoding, errors="replace") as fh:
                content = fh.read(MAX_BYTES)
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult(
                success=False,
                output=None,
                error=f"Error reading '{resolved}' as {encoding}: {exc}",
                metadata={"requested_path": path_raw, "resolved_path": str(resolved)},
            )

        if truncated:
            notice = (
                f"\n\n[TRUNCATED: file is {file_size:,} bytes; "
                f"showing first {MAX_BYTES:,} bytes only]"
            )
            content += notice

        _log.debug("file_read: read %d chars from '%s'", len(content), resolved)

        return ToolResult(
            success=True,
            output=content,
            error=None,
            metadata={
                "requested_path": path_raw,
                "resolved_path": str(resolved),
                "file_size_bytes": file_size,
                "chars_read": len(content),
                "encoding": encoding,
                "truncated": truncated,
            },
        )
