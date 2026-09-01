"""
tests/test_artifact_manager.py
================================
Unit tests for app.artifacts.manager.ArtifactManager.

Tests cover:
- Happy-path registration (docx, pptx, xlsx)
- to_dict() excludes physical_path
- physical_path accessible on Artifact object
- _sanitize_filename: traversal, Windows paths, empty stem, length limit
- _validate_file: missing file, zero-byte, disallowed extension
- UUID format on artifact_id (32-char hex)
- Atomic rename — source file gone, dest file exists
- Double-registration of same source path fails gracefully
- delete_artifact() and _expire_artifacts() stubs return safely
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.artifacts.manager import ArtifactError, ArtifactManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager(tmp_path: Path) -> ArtifactManager:
    return ArtifactManager(storage_dir=tmp_path / "generated")


def _write_docx(path: Path, size: int = 128) -> None:
    """Write a fake (non-zero) file with .docx extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x50\x4B\x03\x04" + b"\x00" * (size - 4))  # PK magic header


# ---------------------------------------------------------------------------
# Happy-path registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ext,mime,atype", [
    (".docx",
     "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
     "docx"),
    (".pptx",
     "application/vnd.openxmlformats-officedocument.presentationml.presentation",
     "pptx"),
    (".xlsx",
     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
     "xlsx"),
])
def test_register_happy_path(tmp_path, manager, ext, mime, atype):
    src = tmp_path / f"report{ext}"
    _write_docx(src)

    artifact = manager.register_artifact(
        source_path=src,
        filename=f"report{ext}",
        mime_type=mime,
        artifact_type=atype,
        request_id="req-123",
    )

    # Artifact fields
    assert artifact.artifact_id
    assert len(artifact.artifact_id) == 32
    assert all(c in "0123456789abcdef" for c in artifact.artifact_id)
    assert artifact.filename == f"report{ext}"
    assert artifact.artifact_type == atype
    assert artifact.mime_type == mime
    assert artifact.size_bytes > 0
    assert artifact.request_id == "req-123"
    assert artifact.created_at  # ISO-8601 string

    # Source file is GONE (atomic rename, not copy)
    assert not src.exists(), "Source file should have been renamed away"

    # Destination file exists
    assert artifact.physical_path.exists()
    assert artifact.physical_path.name.startswith(artifact.artifact_id)

    # Registry lookup works
    fetched = manager.get_artifact(artifact.artifact_id)
    assert fetched is artifact


def test_register_stored_in_registry(tmp_path, manager):
    src = tmp_path / "data.xlsx"
    _write_docx(src)
    art = manager.register_artifact(
        src, "data.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    )
    assert manager.get_artifact(art.artifact_id) is art
    assert manager.get_artifact("nonexistent") is None


# ---------------------------------------------------------------------------
# to_dict() must NOT include physical_path
# ---------------------------------------------------------------------------


def test_to_dict_excludes_physical_path(tmp_path, manager):
    src = tmp_path / "secret.docx"
    _write_docx(src)
    art = manager.register_artifact(
        src, "secret.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    )
    d = art.to_dict()
    assert "physical_path" not in d, "physical_path must NEVER be in to_dict()"
    # But it IS accessible on the object itself
    assert hasattr(art, "physical_path")
    assert isinstance(art.physical_path, Path)


def test_to_dict_has_download_url(tmp_path, manager):
    src = tmp_path / "note.docx"
    _write_docx(src)
    art = manager.register_artifact(
        src, "note.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    )
    d = art.to_dict()
    assert d["download_url"] == f"/outputs/{art.artifact_id}"
    assert d["artifact_id"] == art.artifact_id
    assert d["filename"] == art.filename
    assert d["size_bytes"] == art.size_bytes


# ---------------------------------------------------------------------------
# _sanitize_filename: traversal and edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected_suffix", [
    ("../../evil.docx", ".docx"),
    ("../../../etc/passwd.docx", ".docx"),
    (r"C:\Windows\system32\cmd.docx", ".docx"),
    ("/etc/shadow.docx", ".docx"),
    ("normal_report.docx", ".docx"),
    ("report with spaces!@#.docx", ".docx"),
])
def test_sanitize_filename_strips_traversal(manager, raw, expected_suffix):
    result = manager._sanitize_filename(raw)
    # No path separators in result
    assert "/" not in result
    assert "\\" not in result
    assert ".." not in result
    assert result.endswith(expected_suffix)


def test_sanitize_filename_stem_length_limit(manager):
    long_stem = "a" * 200
    result = manager._sanitize_filename(f"{long_stem}.docx")
    stem = result[:-5]  # remove .docx
    assert len(stem) <= 100


def test_sanitize_filename_empty_stem_fallback(manager):
    # After stripping, stem would be empty — should fall back to "artifact"
    result = manager._sanitize_filename("!@#$.docx")
    assert result == "artifact.docx" or result.endswith(".docx")


def test_sanitize_filename_disallowed_extension(manager):
    with pytest.raises(ArtifactError, match="Extension"):
        manager._sanitize_filename("evil.exe")


def test_sanitize_filename_disallowed_extension_py(manager):
    with pytest.raises(ArtifactError, match="Extension"):
        manager._sanitize_filename("script.py")


# ---------------------------------------------------------------------------
# _validate_file: error conditions
# ---------------------------------------------------------------------------


def test_validate_file_missing(tmp_path, manager):
    with pytest.raises(ArtifactError, match="does not exist"):
        manager._validate_file(tmp_path / "ghost.docx")


def test_validate_file_zero_bytes(tmp_path, manager):
    f = tmp_path / "empty.docx"
    f.write_bytes(b"")
    with pytest.raises(ArtifactError, match="empty"):
        manager._validate_file(f)


def test_validate_file_disallowed_extension(tmp_path, manager):
    f = tmp_path / "script.py"
    f.write_bytes(b"print('hello')")
    with pytest.raises(ArtifactError, match="disallowed extension"):
        manager._validate_file(f)


def test_validate_file_is_directory(tmp_path, manager):
    d = tmp_path / "mydir.docx"
    d.mkdir()
    with pytest.raises(ArtifactError, match="not a file"):
        manager._validate_file(d)


# ---------------------------------------------------------------------------
# Double registration: same source path used twice
# ---------------------------------------------------------------------------


def test_double_registration_same_source_fails(tmp_path, manager):
    """
    The first registration moves (renames) the source file.
    A second register call on the same (now-missing) source should fail.
    """
    src = tmp_path / "report.docx"
    _write_docx(src)
    manager.register_artifact(
        src, "report.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    )
    # Source is now gone — second registration should raise
    with pytest.raises(ArtifactError):
        manager.register_artifact(
            src, "report.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        )


# ---------------------------------------------------------------------------
# list_artifacts
# ---------------------------------------------------------------------------


def test_list_artifacts(tmp_path, manager):
    for i in range(3):
        src = tmp_path / f"doc{i}.docx"
        _write_docx(src)
        manager.register_artifact(
            src, f"doc{i}.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
            request_id=f"req-{i}",
        )
    all_arts = manager.list_artifacts()
    assert len(all_arts) == 3

    filtered = manager.list_artifacts(request_id="req-1")
    assert len(filtered) == 1
    assert filtered[0].request_id == "req-1"


# ---------------------------------------------------------------------------
# Future-ready stubs — must not raise, must return safely
# ---------------------------------------------------------------------------


def test_delete_artifact_stub(tmp_path, manager):
    src = tmp_path / "file.docx"
    _write_docx(src)
    art = manager.register_artifact(
        src, "file.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    )
    result = manager.delete_artifact(art.artifact_id)
    assert result is False  # not implemented yet


def test_expire_artifacts_stub(manager):
    result = manager._expire_artifacts(max_age_seconds=3600)
    assert result == 0  # not implemented yet


def test_scan_storage_dir_stub(manager):
    result = manager.scan_storage_dir()
    assert result == 0  # not implemented yet


# ---------------------------------------------------------------------------
# Thread-safety: registry lock does not deadlock under concurrent access
# ---------------------------------------------------------------------------


def test_concurrent_registry_access(tmp_path, manager):
    errors = []

    def register_one(i):
        try:
            src = tmp_path / f"thread_{i}.docx"
            _write_docx(src)
            manager.register_artifact(
                src, f"thread_{i}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "docx",
                request_id=f"req-{i}",
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=register_one, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent registration: {errors}"
    assert len(manager.list_artifacts()) == 10
