#!/usr/bin/env python3
"""Retire on-host residue of the extracted "sannai community" feature.

Commit 47bbc13 removed the community feature's source from this repository:
8 plugin modules, the installer's community-layout initializer, the
``deploy_community.py`` helper, the cognitive-loop step, the
``memory-os-agent-os`` CLI alias, and the StateOverlay section. The repo side
is clean. Hosts that had already installed and run the feature keep every
artifact it left behind, because the deployment path never had an inverse
operation:

- 8 plugin module files under ``plugins/memory_os/`` (``community.py``,
  ``community_shared.py``, ``community_snapshot.py``, ``community_table.py``,
  ``community_triggers.py``, ``community_interest_garden.py``,
  ``community_partner_runtime.py``, ``partner_create.py``). Several contain
  raw ``open(..., "a")`` append surfaces that were previously enumerated in
  the write-surface allowlist.
- the community data layout under ``memory-os/community/`` (``charters/``,
  ``shared/``, ``partners/``, ``system/``, ``roster.jsonl``,
  ``budget.yaml`` with ``enforcement: fail-closed``).
- three executable helper scripts under ``scripts/`` (``deploy_community.py``,
  ``community_monitor.py``, ``community_partner_reply.py``) whose own logic
  can still recreate the removed data layout or keep writing to it.

This script performs the missing inverse operation. It ARCHIVES (never
deletes) that residue under ``memory-os/legacy-archive/community/<timestamp>/``,
records a bounded manifest under
``memory-os/system/community_retirement.json``, and leaves a read-only,
integrity-checkable archive tree. It is idempotent (safe to run twice),
never auto-invoked by install/deploy, and a no-op when a Hermes home has no
community residue at all.

Modeled on ``plugins/memory/memory_os/legacy_right_brain_retirement.py``
(read that module first to see the precedent this mirrors), but kept as a
single self-contained script rather than a new plugin module: the community
feature was deliberately extracted out of the Memory-OS package, and no
runtime code imports this retirement operation. Community work now lives in
a separate repository, https://github.com/btnalit/sannai-community.

Usage::

    python3 memory_os_community_retirement.py --hermes-home /path/to/.hermes
        # plan / dry-run (default): reports what WOULD be archived, changes nothing

    python3 memory_os_community_retirement.py --hermes-home /path/to/.hermes --apply
        # archives residue and writes the retired manifest

    python3 memory_os_community_retirement.py --hermes-home /path/to/.hermes --status
        # reports bounded audit status only; changes nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl is always present on POSIX
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - msvcrt exists only on Windows
    msvcrt = None  # type: ignore[assignment]


SCHEMA_VERSION = "memory-os.community_retirement.v0"
STATUS_SCHEMA_VERSION = "memory-os.community_retirement_status.v0"
REPLACEMENT = "sannai_community_external_repo"
SOURCE_REPO = "https://github.com/btnalit/sannai-community"

# Exact residue inventory. Matches the "moved out" record in
# docs/resolver/hermes-memory-os-optimization-roadmap.md section 11 for what
# commit 47bbc13 extracted, and the ``target = hermes_home / "plugins" /
# "memory_os"`` install layout in scripts/install_memory_os_plugin.py.
COMMUNITY_PLUGIN_MODULE_NAMES = (
    "community.py",
    "community_shared.py",
    "community_snapshot.py",
    "community_table.py",
    "community_triggers.py",
    "community_interest_garden.py",
    "community_partner_runtime.py",
    "partner_create.py",
)
COMMUNITY_HELPER_SCRIPT_NAMES = (
    "deploy_community.py",
    "community_monitor.py",
    "community_partner_reply.py",
)
COMMUNITY_DATA_RELATIVE_PATH = Path("memory-os/community")
COMMUNITY_SOURCE_RELATIVE_PATHS = (
    tuple(Path("plugins/memory_os") / name for name in COMMUNITY_PLUGIN_MODULE_NAMES)
    + tuple(Path("scripts") / name for name in COMMUNITY_HELPER_SCRIPT_NAMES)
    + (COMMUNITY_DATA_RELATIVE_PATH,)
)
MANIFEST_RELATIVE_PATH = Path("memory-os/system/community_retirement.json")
ARCHIVE_ROOT_RELATIVE_PATH = Path("memory-os/legacy-archive/community")
LOCK_RELATIVE_PATH = Path("memory-os/system/community_retirement.lock")
_ARCHIVE_STAMP_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")


@contextmanager
def _community_retirement_write_lock(hermes_home: str | Path):
    with _community_retirement_lock(hermes_home, exclusive=True):
        yield


@contextmanager
def _community_retirement_lock(hermes_home: str | Path, *, exclusive: bool):
    home = Path(hermes_home).expanduser().resolve()
    path = home / LOCK_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    locked = False
    try:
        _lock_descriptor(descriptor, exclusive=exclusive)
        locked = True
        yield
    finally:
        try:
            if locked:
                _unlock_descriptor(descriptor)
        finally:
            os.close(descriptor)


_WIN32_LOCKFILE_EXCLUSIVE_LOCK = 0x00000002


def _win32_lockfileex(descriptor: int, *, exclusive: bool, unlock: bool) -> None:
    """Windows advisory lock through LockFileEx/UnlockFileEx (mirrors fcntl.flock)."""

    import ctypes

    if msvcrt is None:  # pragma: no cover - neither fcntl nor msvcrt present
        raise RuntimeError("no advisory file lock primitive available on this platform")

    class _Overlapped(ctypes.Structure):
        _fields_ = (
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", ctypes.c_uint32),
            ("OffsetHigh", ctypes.c_uint32),
            ("hEvent", ctypes.c_void_p),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = ctypes.c_void_p(msvcrt.get_osfhandle(descriptor))
    overlapped = _Overlapped()
    if unlock:
        ok = kernel32.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
    else:
        mode = _WIN32_LOCKFILE_EXCLUSIVE_LOCK if exclusive else 0
        ok = kernel32.LockFileEx(handle, mode, 0, 1, 0, ctypes.byref(overlapped))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def _lock_descriptor(descriptor: int, *, exclusive: bool) -> None:
    if fcntl is not None:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        return
    _win32_lockfileex(descriptor, exclusive=exclusive, unlock=False)


def _unlock_descriptor(descriptor: int) -> None:
    if fcntl is not None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    _win32_lockfileex(descriptor, exclusive=False, unlock=True)


def retirement_manifest_path(hermes_home: str | Path) -> Path:
    return Path(hermes_home).expanduser().resolve() / MANIFEST_RELATIVE_PATH


def load_retirement_manifest(hermes_home: str | Path) -> dict[str, Any]:
    path = retirement_manifest_path(hermes_home)
    if path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _safe_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed >= 0 else 0


def _manifest_validation_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    if manifest.get("lifecycle") not in {"retirement_pending", "retired"}:
        errors.append("lifecycle")
    if manifest.get("active_observation") is not False or manifest.get("active_execution") is not False:
        errors.append("active_flags")
    if manifest.get("replacement") != REPLACEMENT:
        errors.append("replacement")
    expected_sources = [path.as_posix() for path in COMMUNITY_SOURCE_RELATIVE_PATHS]
    if manifest.get("source_relative_paths") != expected_sources:
        errors.append("source_relative_paths")
    archive_relative = str(manifest.get("archive_relative_path") or "")
    archive_path = Path(archive_relative)
    if (
        archive_path.parent != ARCHIVE_ROOT_RELATIVE_PATH
        or not _ARCHIVE_STAMP_RE.fullmatch(archive_path.name)
        or archive_path.is_absolute()
    ):
        errors.append("archive_relative_path")
    archived_files = manifest.get("archived_files")
    if not isinstance(archived_files, list):
        errors.append("archived_files")
        return errors
    seen: set[str] = set()
    allowed_prefixes = tuple(
        f"{path.as_posix()}/" for path in COMMUNITY_SOURCE_RELATIVE_PATHS if path.suffix == ""
    )
    allowed_exact = {path.as_posix() for path in COMMUNITY_SOURCE_RELATIVE_PATHS if path.suffix != ""}
    for record in archived_files:
        if not isinstance(record, dict):
            errors.append("archived_file_record")
            continue
        relative = str(record.get("relative_path") or "")
        digest = str(record.get("sha256") or "")
        if (
            not relative
            or relative in seen
            or (relative not in allowed_exact and not relative.startswith(allowed_prefixes))
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(record.get("size_bytes"), int)
            or isinstance(record.get("size_bytes"), bool)
            or int(record.get("size_bytes") or 0) < 0
            or not isinstance(record.get("jsonl_record_count"), int)
            or isinstance(record.get("jsonl_record_count"), bool)
            or int(record.get("jsonl_record_count") or 0) < 0
        ):
            errors.append("archived_file_record")
        seen.add(relative)
    if isinstance(manifest.get("archived_file_count"), bool) or manifest.get("archived_file_count") != len(
        archived_files
    ):
        errors.append("archived_file_count")
    expected_jsonl_count = sum(
        int(record.get("jsonl_record_count") or 0)
        for record in archived_files
        if isinstance(record, dict)
    )
    if (
        isinstance(manifest.get("archived_jsonl_record_count"), bool)
        or not isinstance(manifest.get("archived_jsonl_record_count"), int)
        or manifest.get("archived_jsonl_record_count") != expected_jsonl_count
    ):
        errors.append("archived_jsonl_record_count")
    return sorted(set(errors))


def retire_community(
    hermes_home: str | Path,
    *,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    with _community_retirement_write_lock(hermes_home):
        return _retire_community_locked(hermes_home, apply=apply, now=now)


def _retire_community_locked(
    hermes_home: str | Path,
    *,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build or apply an idempotent community retirement plan.

    A Hermes home with zero community residue must be left untouched: no
    manifest, no archive directory, no lock artifact beyond the lock file
    itself. That noop path is checked before any prerequisite or archive
    step runs.
    """

    home = Path(hermes_home).expanduser().resolve()
    existing = load_retirement_manifest(home)
    if existing.get("lifecycle") == "retired":
        status = retirement_status(home)
        if status.get("status") != "ok" and status.get("violations") == [
            "retirement_manifest_writable"
        ]:
            manifest_path = retirement_manifest_path(home)
            manifest_path.chmod(stat.S_IRUSR)
            _fsync_file(manifest_path)
            _fsync_directory(manifest_path.parent)
            status = retirement_status(home)
            if status.get("status") == "ok":
                return {
                    "schema_version": SCHEMA_VERSION,
                    "status": "retired_recovered",
                    "applied": True,
                    "manifest_path": str(manifest_path),
                    "retirement": status,
                }
        if status.get("status") != "ok":
            raise RuntimeError("invalid existing retirement manifest")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "already_retired",
            "applied": False,
            "manifest_path": str(retirement_manifest_path(home)),
            "retirement": status,
        }
    if apply and existing.get("lifecycle") == "retirement_pending":
        if _manifest_validation_errors(existing):
            raise RuntimeError("invalid pending retirement manifest")
        return _recover_pending_retirement(home, existing)
    if _path_lexists(retirement_manifest_path(home)):
        raise RuntimeError("invalid existing retirement manifest")

    file_records = _inventory_sources(home)
    if not file_records:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "noop_no_residue",
            "applied": False,
            "manifest_path": str(retirement_manifest_path(home)),
            "source_relative_paths": [path.as_posix() for path in COMMUNITY_SOURCE_RELATIVE_PATHS],
        }

    _assert_prerequisites(home)
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    retired_at = timestamp.isoformat()
    archive_stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    archive_rel = ARCHIVE_ROOT_RELATIVE_PATH / archive_stamp
    archive_root = home / archive_rel
    cron_records = _community_cron_records(home)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "lifecycle": "retirement_pending" if apply else "retired",
        "retired_at": retired_at,
        "cutoff_at": retired_at,
        "replacement": REPLACEMENT,
        "source_repo": SOURCE_REPO,
        "community_cron_jobs": cron_records,
        "source_relative_paths": [path.as_posix() for path in COMMUNITY_SOURCE_RELATIVE_PATHS],
        "archive_relative_path": archive_rel.as_posix(),
        "archived_files": file_records,
        "archived_file_count": len(file_records),
        "archived_jsonl_record_count": sum(int(item.get("jsonl_record_count") or 0) for item in file_records),
        "active_observation": False,
        "active_execution": False,
        "raw_body_included": False,
        "archive_contains_private_bodies": bool(file_records),
        "actual_send": False,
        "actual_execute": False,
    }
    if not apply:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "dry_run",
            "applied": False,
            "manifest_path": str(retirement_manifest_path(home)),
            "plan": payload,
        }

    manifest_path = retirement_manifest_path(home)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(manifest_path, payload)
    _complete_archive_moves(home, archive_root)
    _make_tree_read_only(archive_root)
    integrity_errors = _archive_integrity_errors(home, archive_root, payload)
    if integrity_errors:
        raise RuntimeError(f"community retirement archive integrity failed: {', '.join(integrity_errors)}")
    payload["lifecycle"] = "retired"
    _atomic_write_json(manifest_path, payload)
    manifest_path.chmod(stat.S_IRUSR)
    _fsync_file(manifest_path)
    _fsync_directory(manifest_path.parent)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "retired",
        "applied": True,
        "manifest_path": str(manifest_path),
        "retirement": retirement_status(home),
    }


def _recover_pending_retirement(home: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    archive_rel = str(manifest.get("archive_relative_path") or "")
    archive_root = _safe_relative_target(home, archive_rel)
    _complete_archive_moves(home, archive_root)
    _make_tree_read_only(archive_root)
    integrity_errors = _archive_integrity_errors(home, archive_root, manifest)
    if integrity_errors:
        raise RuntimeError(f"community retirement archive integrity failed: {', '.join(integrity_errors)}")
    finalized = dict(manifest)
    finalized["lifecycle"] = "retired"
    manifest_path = retirement_manifest_path(home)
    _atomic_write_json(manifest_path, finalized)
    manifest_path.chmod(stat.S_IRUSR)
    _fsync_file(manifest_path)
    _fsync_directory(manifest_path.parent)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "retired_recovered",
        "applied": True,
        "manifest_path": str(manifest_path),
        "retirement": retirement_status(home),
    }


def retirement_status(hermes_home: str | Path) -> dict[str, Any]:
    """Return bounded audit metadata; never return an archived body."""

    home = Path(hermes_home).expanduser().resolve()
    manifest_path = retirement_manifest_path(home)
    manifest = load_retirement_manifest(home)
    manifest_present = _path_lexists(manifest_path)
    manifest_errors = _manifest_validation_errors(manifest) if manifest_present else []
    manifest_writable = bool(
        manifest_present
        and not manifest_path.is_symlink()
        and manifest_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    )
    lifecycle = str(manifest.get("lifecycle") or "active")
    retired = lifecycle == "retired"
    pending = lifecycle == "retirement_pending"
    archive_rel = str(manifest.get("archive_relative_path") or "")
    archive_root = (
        _safe_relative_target(home, archive_rel)
        if archive_rel and "archive_relative_path" not in manifest_errors
        else None
    )
    archived_value = manifest.get("archived_files")
    archived_files: list[Any] = archived_value if isinstance(archived_value, list) else []
    hash_mismatches = 0
    writable_archive_files = 0
    writable_archive_directories = 0
    missing_archive_files = 0
    for record in archived_files:
        if not isinstance(record, dict) or archive_root is None:
            hash_mismatches += 1
            continue
        relative = str(record.get("relative_path") or "")
        try:
            path = _safe_relative_target(archive_root, relative)
        except RuntimeError:
            hash_mismatches += 1
            continue
        if not path.is_file() or path.is_symlink():
            missing_archive_files += 1
            continue
        if _sha256(path) != str(record.get("sha256") or ""):
            hash_mismatches += 1
        if path.stat().st_size != record.get("size_bytes"):
            hash_mismatches += 1
        actual_jsonl_count = _jsonl_record_count(path) if path.suffix == ".jsonl" else 0
        if actual_jsonl_count != record.get("jsonl_record_count"):
            hash_mismatches += 1
        if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            writable_archive_files += 1
    if archive_root and archive_root.is_dir():
        for path in [archive_root, archive_root.parent, *archive_root.rglob("*")]:
            if path.is_dir() and path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                writable_archive_directories += 1

    live_inventory_error = False
    try:
        live_files = _inventory_sources(home)
    except RuntimeError:
        live_files = []
        live_inventory_error = True
    live_sources = [
        relative.as_posix()
        for relative in COMMUNITY_SOURCE_RELATIVE_PATHS
        if _path_lexists(home / relative)
    ]
    archived_paths = {
        str(record.get("relative_path") or "")
        for record in archived_files
        if isinstance(record, dict)
    }
    archive_inventory_error = False
    try:
        current_archive = _inventory(archive_root) if archive_root and archive_root.is_dir() else []
    except RuntimeError:
        current_archive = []
        archive_inventory_error = True
    current_archive_paths = {str(record.get("relative_path") or "") for record in current_archive}
    archive_extra_files = current_archive_paths - archived_paths
    cron_registry_error = False
    try:
        cron_records = _community_cron_records(home)
    except RuntimeError:
        cron_records = []
        cron_registry_error = True
    enabled_community_crons = [record["name"] or record["script"] for record in cron_records if record.get("enabled") is True]
    violations = []
    if manifest_errors:
        violations.append("retirement_manifest_invalid")
    if live_inventory_error:
        violations.append("community_source_inventory_error")
    if archive_inventory_error:
        violations.append("archive_inventory_error")
    if cron_registry_error:
        violations.append("community_cron_registry_invalid")
    if retired and (archive_root is None or not archive_root.is_dir()):
        violations.append("archive_missing")
    if retired and manifest_writable:
        violations.append("retirement_manifest_writable")
    if pending:
        violations.append("retirement_pending_incomplete")
    if retired and live_sources:
        violations.append("community_source_recreated")
    if missing_archive_files:
        violations.append("archive_file_missing")
    if hash_mismatches:
        violations.append("archive_hash_mismatch")
    if writable_archive_files:
        violations.append("archive_file_writable")
    if writable_archive_directories:
        violations.append("archive_directory_writable")
    if archive_extra_files:
        violations.append("archive_extra_file")
    if enabled_community_crons:
        violations.append("community_cron_enabled")
    status = (
        "error"
        if manifest_present and violations
        else "error"
        if pending
        else "not_retired"
        if not retired
        else "ok"
    )
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "status": status,
        "lifecycle": lifecycle,
        "retired_at": manifest.get("retired_at"),
        "cutoff_at": manifest.get("cutoff_at"),
        "replacement": manifest.get("replacement"),
        "source_repo": manifest.get("source_repo"),
        "archived_file_count": _safe_nonnegative_int(manifest.get("archived_file_count")),
        "archived_jsonl_record_count": _safe_nonnegative_int(manifest.get("archived_jsonl_record_count")),
        "archive_present": bool(archive_root and archive_root.is_dir()),
        "manifest_writable": manifest_writable,
        "archive_hash_mismatch_count": hash_mismatches,
        "archive_missing_file_count": missing_archive_files,
        "archive_writable_file_count": writable_archive_files,
        "archive_writable_directory_count": writable_archive_directories,
        "archive_extra_file_count": len(archive_extra_files),
        "post_cutoff_live_root_exists": bool(live_sources),
        "post_cutoff_source_paths": live_sources,
        "post_cutoff_file_count": len(live_files),
        "post_cutoff_jsonl_record_count": sum(int(item.get("jsonl_record_count") or 0) for item in live_files),
        "enabled_community_cron_count": len(enabled_community_crons),
        "enabled_community_cron_names": enabled_community_crons,
        "violations": violations,
        "active_observation": False if retired or pending else None,
        "active_execution": False if retired or pending else None,
        "raw_body_included": False,
        "actual_send": False,
        "actual_execute": False,
    }


def _assert_prerequisites(home: Path) -> None:
    enabled = [record for record in _community_cron_records(home) if record.get("enabled") is True]
    if enabled:
        names = ", ".join(sorted(record["name"] or record["script"] for record in enabled))
        raise RuntimeError(f"community cron jobs must be paused before retirement: {names}")


def _community_cron_records(home: Path) -> list[dict[str, Any]]:
    """Bounded scan of cron/jobs.json for jobs pointing at community scripts.

    Only inspects the ``script`` basename against the known community helper
    script names; it does not need MemoryOSCronSpec wiring since none of
    these scripts were ever wrapped by ExecutionGate.
    """

    jobs_path = home / "cron" / "jobs.json"
    try:
        loaded = json.loads(jobs_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"invalid community cron registry: {jobs_path}") from exc
    if isinstance(loaded, dict):
        jobs = loaded.get("jobs", [])
    elif isinstance(loaded, list):
        jobs = loaded
    else:
        raise RuntimeError(f"invalid community cron registry root: {jobs_path}")
    if not isinstance(jobs, list):
        raise RuntimeError(f"invalid community cron jobs list: {jobs_path}")
    result = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        script = str(job.get("script") or "")
        script_name = Path(script).name if script else ""
        if script_name not in COMMUNITY_HELPER_SCRIPT_NAMES:
            continue
        result.append(
            {
                "name": str(job.get("name") or ""),
                "job_id": str(job.get("job_id") or job.get("id") or ""),
                "enabled": bool(job.get("enabled", True)),
                "script": script,
                "last_run_at": job.get("last_run_at"),
                "last_status": job.get("last_status"),
            }
        )
    return sorted(result, key=lambda item: (item["name"], item["script"]))


def _inventory_sources(home: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative_root in COMMUNITY_SOURCE_RELATIVE_PATHS:
        source = home / relative_root
        if not _path_lexists(source):
            continue
        if source.is_symlink():
            raise RuntimeError(f"symlink is not allowed in community archive: {source}")
        if source.is_file():
            records.append(_file_record(source, relative_root.as_posix()))
            continue
        if not source.is_dir():
            raise RuntimeError(f"unsupported community artifact source: {source}")
        for record in _inventory(source):
            record["relative_path"] = (relative_root / str(record["relative_path"])).as_posix()
            records.append(record)
    return sorted(records, key=lambda item: str(item["relative_path"]))


def _inventory(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"community artifact root must be a real directory: {root}")
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"symlink is not allowed in community archive: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError(f"unsupported file type in community archive: {path}")
        records.append(_file_record(path, path.relative_to(root).as_posix()))
    return records


def _file_record(path: Path, relative: str) -> dict[str, Any]:
    return {
        "relative_path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "jsonl_record_count": _jsonl_record_count(path) if path.suffix == ".jsonl" else 0,
    }


def _complete_archive_moves(home: Path, archive_root: Path) -> None:
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_root.chmod(stat.S_IRWXU)
    for relative in COMMUNITY_SOURCE_RELATIVE_PATHS:
        source = home / relative
        target = archive_root / relative
        if _path_lexists(source) and _path_lexists(target):
            raise RuntimeError(f"community retirement source and archive target both exist: {relative}")
        if not _path_lexists(source):
            continue
        if source.is_symlink():
            raise RuntimeError(f"symlink is not allowed in community archive: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        _fsync_directory(source.parent)
        _fsync_directory(target.parent)


def _jsonl_record_count(path: Path) -> int:
    count = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_integrity_errors(home: Path, archive_root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not archive_root.is_dir() or archive_root.is_symlink():
        return ["archive_root_missing_or_invalid"]
    expected = {
        str(record.get("relative_path") or ""): record
        for record in manifest.get("archived_files", [])
        if isinstance(record, dict)
    }
    actual = {str(record["relative_path"]): record for record in _inventory(archive_root)}
    if set(actual) != set(expected):
        errors.append("archive_file_set")
    for relative, expected_record in expected.items():
        path = archive_root / relative
        if relative not in actual or not path.is_file() or path.is_symlink():
            continue
        if _sha256(path) != str(expected_record.get("sha256") or ""):
            errors.append("archive_hash")
        if path.stat().st_size != expected_record.get("size_bytes"):
            errors.append("archive_size")
        actual_jsonl_count = _jsonl_record_count(path) if path.suffix == ".jsonl" else 0
        if actual_jsonl_count != expected_record.get("jsonl_record_count"):
            errors.append("archive_jsonl_record_count")
        if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            errors.append("archive_file_writable")
    for path in [archive_root, archive_root.parent, *archive_root.rglob("*")]:
        if path.is_symlink():
            errors.append("archive_symlink")
        elif path.is_dir() and path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            errors.append("archive_directory_writable")
        elif not path.is_dir() and not path.is_file():
            errors.append("archive_unsupported_file_type")
    if any(_path_lexists(home / relative) for relative in COMMUNITY_SOURCE_RELATIVE_PATHS):
        errors.append("community_source_still_live")
    expected_total = sum(
        int(record.get("jsonl_record_count") or 0)
        for record in manifest.get("archived_files", [])
        if isinstance(record, dict)
    )
    if manifest.get("archived_jsonl_record_count") != expected_total:
        errors.append("archive_jsonl_record_count_total")
    return sorted(set(errors))


def _make_tree_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_symlink():
            raise RuntimeError(f"symlink is not allowed in community archive: {path}")
        if path.is_file():
            path.chmod(stat.S_IRUSR)
            _fsync_file(path)
        elif path.is_dir():
            path.chmod(stat.S_IRUSR | stat.S_IXUSR)
            _fsync_directory(path)
        else:
            raise RuntimeError(f"unsupported file type in community archive: {path}")
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    root.parent.chmod(stat.S_IRUSR | stat.S_IXUSR)
    _fsync_directory(root)
    _fsync_directory(root.parent)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else stat.S_IRUSR | stat.S_IWUSR
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, existing_mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), existing_mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    """Best-effort directory fsync after an atomic replace.

    Platforms that cannot open directory descriptors (Windows raises
    PermissionError from os.open) skip the directory fsync; the file itself
    is already flushed+fsynced and os.replace stays atomic.
    """

    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
    except (NotImplementedError, OSError):
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    if os.name == "nt":
        # FlushFileBuffers requires a writable handle, but this durability
        # fsync targets manifest/archive files that are chmod'ed read-only
        # first, so a read-only descriptor cannot be fsynced on Windows.
        # The content was already flush+fsync'ed before os.replace.
        return
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_relative_target(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise RuntimeError(f"archive path escapes Hermes home: {relative}") from exc
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Archive residue and write the retired manifest")
    mode.add_argument("--status", action="store_true", help="Report bounded retirement status only; changes nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = Path(args.hermes_home).expanduser().resolve()
    report = retirement_status(home) if args.status else retire_community(home, apply=bool(args.apply))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.status:
        return 0 if report.get("status") in {"ok", "not_retired"} else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
