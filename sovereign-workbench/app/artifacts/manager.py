"""
artifacts/manager.py
====================
Central artifact registration and download management.

Design
------
* All generated files (DOCX, PPTX, XLSX) are registered here immediately after
  their generator writes them to disk.
* Registration performs an atomic ``Path.rename()`` — the original
  generator-named file is moved to a UUID-prefixed name.  No copy is made;
  only one physical file exists per artifact.
* The ``Artifact.to_dict()`` method intentionally EXCLUDES ``physical_path``
  so that internal storage paths are never serialised to SSE events or API
  responses.
* The download endpoint resolves the path internally from the registry using
  ``artifact.physical_path`` — callers never receive or supply filesystem paths.

Sovereignty note
----------------
No network calls.  All I/O is local filesystem operations.

Future hooks (reserved but not implemented)
-------------------------------------------
``delete_artifact(artifact_id)``
    Remove a registered artifact from the registry and delete its file.
``_expire_artifacts(max_age_seconds)``
    Called by a future background task to clean up old artifacts by TTL.
``scan_storage_dir()``
    Rebuild the in-process registry from existing files on disk (useful after
    server restart to re-serve files that were generated before the restart).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_log = logging.getLogger("sovereign.artifacts.manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Only these extensions may be registered.  Hard-coded — not configurable.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".docx", ".pptx", ".xlsx"})

MIME_TYPES: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Allowed characters in a sanitized filename (after extension is split off).
# Anything else is stripped.
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._\-]")
_MAX_STEM_LEN = 100  # characters, before extension


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ArtifactError(Exception):
    """Raised when artifact registration or validation fails."""


# ---------------------------------------------------------------------------
# Artifact dataclass
# ---------------------------------------------------------------------------


@dataclass
class Artifact:
    """
    Represents a single registered file artifact.

    ``physical_path`` is intentionally excluded from ``to_dict()`` — it must
    never be sent to the frontend or included in SSE payloads.
    """

    artifact_id: str          # 32-char hex UUID4 (uuid.uuid4().hex)
    filename: str             # sanitized display name (e.g. "report.docx")
    artifact_type: str        # "docx" | "pptx" | "xlsx"
    mime_type: str
    physical_path: Path       # INTERNAL ONLY — never serialised
    size_bytes: int
    request_id: Optional[str]
    created_at: str           # ISO-8601 UTC timestamp

    def to_dict(self) -> dict:
        """
        Frontend-safe serialisation.

        ``physical_path`` is EXCLUDED.  The caller receives only the
        ``download_url`` (``/outputs/{artifact_id}``) to trigger a download.
        """
        return {
            "artifact_id": self.artifact_id,
            "filename": self.filename,
            "artifact_type": self.artifact_type,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "request_id": self.request_id,
            "created_at": self.created_at,
            "download_url": f"/outputs/{self.artifact_id}",
        }


# ---------------------------------------------------------------------------
# ArtifactManager
# ---------------------------------------------------------------------------


class ArtifactManager:
    """
    Thread-safe in-process artifact registry.

    Lifecycle
    ---------
    1. A docgen tool writes a file to ``storage_dir`` using the user-supplied
       ``output_filename``.
    2. ``register_artifact()`` is called with the source path.
    3. The manager sanitizes the filename, validates the file, generates a UUID,
       and atomically renames the file to ``{uuid}_{safe_filename}``.
    4. The ``Artifact`` is stored in the in-process registry.
    5. The download endpoint calls ``get_artifact(artifact_id)`` and serves
       the file via ``artifact.physical_path`` — this path never leaves the server.

    Thread safety
    -------------
    All mutations to ``_registry`` are protected by ``_lock``.
    ``Path.rename()`` is used instead of ``shutil.copy`` to ensure atomicity and
    to guarantee a single physical file per artifact.
    """

    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._registry: dict[str, Artifact] = {}
        self._lock = threading.Lock()
        _log.info("ArtifactManager initialised — storage_dir=%s", self._storage_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_artifact(
        self,
        source_path: Path,
        filename: str,
        mime_type: str,
        artifact_type: str,
        request_id: Optional[str] = None,
    ) -> Artifact:
        """
        Register a generated file as an artifact.

        Steps
        -----
        1. Sanitize ``filename`` (strips traversal chars, enforces allowed extension).
        2. Validate ``source_path`` (exists, is_file, size > 0, readable, allowed ext).
        3. Generate ``artifact_id = uuid.uuid4().hex``.
        4. Atomically rename ``source_path`` → ``storage_dir/{artifact_id}_{safe_name}``.
        5. Stat the destination to confirm the rename succeeded and get final size.
        6. Register and return the ``Artifact``.

        Raises
        ------
        ArtifactError
            On any validation, rename, or registration failure.
        """
        safe_name = self._sanitize_filename(filename)
        self._validate_file(source_path, context="source")

        artifact_id = uuid.uuid4().hex
        dest_path = self._storage_dir / f"{artifact_id}_{safe_name}"

        try:
            # Atomic rename — no copy, single file.
            # Path.rename() on Windows uses os.replace() semantics in Python ≥ 3.3,
            # which overwrites the destination if it exists.  Since destinations
            # are UUID-prefixed, collisions are astronomically unlikely.
            source_path.rename(dest_path)
        except OSError as exc:
            raise ArtifactError(
                f"Failed to move artifact file {source_path!r} → {dest_path!r}: {exc}"
            ) from exc

        # Confirm the rename landed correctly.
        try:
            size_bytes = dest_path.stat().st_size
        except OSError as exc:
            raise ArtifactError(
                f"Artifact file missing after rename ({dest_path!r}): {exc}"
            ) from exc

        if size_bytes == 0:
            # Remove the zero-byte file and abort.
            dest_path.unlink(missing_ok=True)
            raise ArtifactError(
                f"Artifact file is empty after rename ({dest_path.name})."
            )

        artifact = Artifact(
            artifact_id=artifact_id,
            filename=safe_name,
            artifact_type=artifact_type,
            mime_type=mime_type,
            physical_path=dest_path,
            size_bytes=size_bytes,
            request_id=request_id,
            created_at=datetime.now(tz=timezone.utc).isoformat(),
        )

        with self._lock:
            self._registry[artifact_id] = artifact

        _log.info(
            "Artifact registered: id=%s  name=%s  size=%d bytes  request_id=%s",
            artifact_id,
            safe_name,
            size_bytes,
            request_id,
        )
        return artifact

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Return the ``Artifact`` for *artifact_id*, or ``None`` if not found."""
        with self._lock:
            return self._registry.get(artifact_id)

    def list_artifacts(self, request_id: Optional[str] = None) -> list[Artifact]:
        """
        Return all registered artifacts, optionally filtered by *request_id*.
        """
        with self._lock:
            arts = list(self._registry.values())
        if request_id is not None:
            arts = [a for a in arts if a.request_id == request_id]
        return arts

    # ------------------------------------------------------------------
    # Future-ready stubs (not implemented — reserved for later phases)
    # ------------------------------------------------------------------

    def delete_artifact(self, artifact_id: str) -> bool:
        """
        Remove an artifact from the registry and delete its physical file.

        .. note::
            Not yet implemented.  Reserved for a future TTL/cleanup phase.
            Returns ``False`` unconditionally until implemented.
        """
        _log.debug("delete_artifact called for %s — not implemented yet", artifact_id)
        return False

    def _expire_artifacts(self, max_age_seconds: int) -> int:
        """
        Scan the registry and delete artifacts older than *max_age_seconds*.

        .. note::
            Not yet implemented.  Reserved for a future background-task phase.
            Returns 0 unconditionally until implemented.
        """
        _log.debug(
            "_expire_artifacts called (max_age=%ds) — not implemented yet",
            max_age_seconds,
        )
        return 0

    def scan_storage_dir(self) -> int:
        """
        Scan ``storage_dir`` to rebuild the in-process registry from existing
        files on disk.  Useful after a server restart to re-serve previously
        generated artifacts.

        .. note::
            Not yet implemented.  Reserved for a future persistence phase.
            Returns 0 unconditionally until implemented.
        """
        _log.debug("scan_storage_dir called — not implemented yet")
        return 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sanitize_filename(self, name: str) -> str:
        """
        Return a filesystem-safe basename.

        Rules applied (in order):
        1. Take only the final path component (``Path(name).name``) — strips
           any directory prefix including ``..``.
        2. Split stem and extension.
        3. Validate extension is in ``ALLOWED_EXTENSIONS``.
        4. Strip all characters from the stem that are not
           ``[a-zA-Z0-9._-]``.
        5. Collapse the stem to ``_MAX_STEM_LEN`` characters.
        6. Fall back to ``"artifact"`` if the stem is empty after stripping.
        7. Reassemble ``stem + ext``.

        Raises
        ------
        ArtifactError
            If the extension is not in ``ALLOWED_EXTENSIONS``.
        """
        # Step 1: basename only
        basename = Path(name).name
        # Extra belt-and-suspenders: remove any remaining / \ .. sequences
        basename = re.sub(r"[/\\]|\.\.", "", basename).strip(". ")
        if not basename:
            raise ArtifactError(
                f"Filename {name!r} is empty after sanitization."
            )

        # Step 2: split stem + ext
        p = Path(basename)
        ext = p.suffix.lower()
        stem = p.stem

        # Step 3: extension validation
        if ext not in ALLOWED_EXTENSIONS:
            raise ArtifactError(
                f"Extension {ext!r} is not allowed. "
                f"Permitted: {sorted(ALLOWED_EXTENSIONS)}"
            )

        # Step 4: strip unsafe characters from stem
        stem = _SAFE_NAME_RE.sub("_", stem)

        # Step 5: length limit
        stem = stem[:_MAX_STEM_LEN]

        # Step 6: fallback
        if not stem:
            stem = "artifact"

        return stem + ext

    def _validate_file(self, path: Path, context: str = "file") -> None:
        """
        Raise ``ArtifactError`` if *path* does not point to a valid, non-empty,
        readable file with an allowed extension.
        """
        if not path.exists():
            raise ArtifactError(f"Artifact {context} does not exist: {path!r}")
        if not path.is_file():
            raise ArtifactError(f"Artifact {context} is not a file: {path!r}")

        ext = path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ArtifactError(
                f"Artifact {context} has disallowed extension {ext!r}: {path.name!r}"
            )

        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ArtifactError(
                f"Cannot stat artifact {context} {path!r}: {exc}"
            ) from exc

        if size == 0:
            raise ArtifactError(
                f"Artifact {context} is empty (0 bytes): {path.name!r}"
            )

        # Quick readability check — open for reading without consuming content.
        try:
            with path.open("rb") as fh:
                fh.read(1)
        except OSError as exc:
            raise ArtifactError(
                f"Artifact {context} is not readable: {path.name!r} — {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: Optional[ArtifactManager] = None
_manager_lock = threading.Lock()

# Default storage directory — two levels up from this file → sovereign-workbench/
_DEFAULT_STORAGE_DIR = Path(__file__).resolve().parents[2] / "outputs" / "generated"


def get_artifact_manager(storage_dir: Optional[Path] = None) -> ArtifactManager:
    """
    Return the process-wide ``ArtifactManager`` singleton.

    Thread-safe.  The singleton is created on first call.

    Parameters
    ----------
    storage_dir:
        Override the default storage directory (``outputs/generated/``).
        Ignored on subsequent calls (singleton already exists).
    """
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ArtifactManager(
                    storage_dir=storage_dir or _DEFAULT_STORAGE_DIR
                )
    return _manager
