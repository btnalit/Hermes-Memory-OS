"""Retire the legacy right-brain lane without deleting its audit history.

The retirement operation is deliberately one-way for a concrete Hermes home:
it moves legacy wandering artifacts out of the live module tree, records bounded
metadata and hashes, and makes the archive read-only.  It never reads artifact
bodies into the manifest and never enables or executes a legacy lane.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import fcntl

from plugins.memory.memory_os.cron_registry import (
    RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES,
    RETIRED_MEMORY_OS_CRON_SCRIPTS,
)

SCHEMA_VERSION = "memory-os.legacy_right_brain_retirement.v0"
STATUS_SCHEMA_VERSION = "memory-os.legacy_right_brain_retirement_status.v0"
LEGACY_STEPS = (
    "wandering_mind",
    "grounded_expression_judge",
    "spontaneous_expression",
)
LEGACY_CRON_NAMES = tuple(RETIRED_MEMORY_OS_CRON_SCRIPTS)
LEGACY_CRON_SCRIPTS = RETIRED_MEMORY_OS_CRON_SCRIPTS
LEGACY_SOURCE_RELATIVE_PATHS = (
    Path("system-modules/wandering_mind"),
    Path("system-modules/grounded_expression_judge"),
    Path("system-modules/expression_draft"),
    Path("system-modules/speak_gate"),
    Path("system-modules/right_brain_expression_adapter"),
    Path("system-modules/speak_permission"),
    Path("memory-os/system/speak_permission_tickets.jsonl"),
    Path("system-modules/deep_reflection/wandering_seeds.jsonl"),
)
LIVE_RELATIVE_PATH = LEGACY_SOURCE_RELATIVE_PATHS[0]
MANIFEST_RELATIVE_PATH = Path("memory-os/system/legacy_right_brain_retirement.json")
ARCHIVE_ROOT_RELATIVE_PATH = Path("memory-os/legacy-archive/right-brain")
LOCK_RELATIVE_PATH = Path("memory-os/system/legacy_right_brain_retirement.lock")
_ARCHIVE_STAMP_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")


@contextmanager
def legacy_right_brain_read_lock(hermes_home: str | Path):
    """Keep one legacy producer stable while a retirement writer waits."""

    with _legacy_right_brain_lock(hermes_home, exclusive=False):
        yield


@contextmanager
def _legacy_right_brain_write_lock(hermes_home: str | Path):
    with _legacy_right_brain_lock(hermes_home, exclusive=True):
        yield


@contextmanager
def _legacy_right_brain_lock(hermes_home: str | Path, *, exclusive: bool):
    home = Path(hermes_home).expanduser().resolve()
    path = home / LOCK_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, mode)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


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
    if manifest.get("replacement") != "v3_inner_life":
        errors.append("replacement")
    expected_sources = [path.as_posix() for path in LEGACY_SOURCE_RELATIVE_PATHS]
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
        f"{path.as_posix()}/" for path in LEGACY_SOURCE_RELATIVE_PATHS if path.suffix == ""
    )
    allowed_exact = {path.as_posix() for path in LEGACY_SOURCE_RELATIVE_PATHS if path.suffix != ""}
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


def legacy_right_brain_is_retired(hermes_home: str | Path) -> bool:
    """Fail closed for execution once any retirement lifecycle marker exists.

    Manifest integrity is evaluated separately by ``retirement_status``. A
    malformed pending/retired marker must never reopen the legacy lane.
    """

    return _path_lexists(retirement_manifest_path(hermes_home))


def archived_legacy_artifact_path(hermes_home: str | Path, relative_path: str | Path) -> Path | None:
    """Resolve one manifest-listed archived file without trusting manifest paths."""

    home = Path(hermes_home).expanduser().resolve()
    manifest = load_retirement_manifest(home)
    if manifest.get("lifecycle") != "retired" or retirement_status(home).get("status") != "ok":
        return None
    relative = Path(relative_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    allowed = {
        str(record.get("relative_path") or "")
        for record in manifest.get("archived_files", [])
        if isinstance(record, dict)
    }
    normalized = relative.as_posix()
    if normalized not in allowed:
        return None
    archive_relative = str(manifest.get("archive_relative_path") or "")
    if not archive_relative:
        return None
    try:
        archive_root = _safe_relative_target(home, archive_relative)
        candidate = _safe_relative_target(archive_root, normalized)
    except RuntimeError:
        return None
    return candidate if candidate.is_file() else None


def retire_legacy_right_brain(
    hermes_home: str | Path,
    *,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    with _legacy_right_brain_write_lock(hermes_home):
        return _retire_legacy_right_brain_locked(hermes_home, apply=apply, now=now)


def _retire_legacy_right_brain_locked(
    hermes_home: str | Path,
    *,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build or apply an idempotent legacy-right-brain retirement plan."""

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

    _assert_prerequisites(home)
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    retired_at = timestamp.isoformat()
    archive_stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    archive_rel = ARCHIVE_ROOT_RELATIVE_PATH / archive_stamp
    archive_root = home / archive_rel
    file_records = _inventory_sources(home)
    cron_records = _legacy_cron_records(home)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "lifecycle": "retirement_pending" if apply else "retired",
        "retired_at": retired_at,
        "cutoff_at": retired_at,
        "replacement": "v3_inner_life",
        "legacy_steps": list(LEGACY_STEPS),
        "legacy_cron_jobs": cron_records,
        "source_relative_paths": [path.as_posix() for path in LEGACY_SOURCE_RELATIVE_PATHS],
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
    _disable_legacy_config(home)
    _atomic_write_json(manifest_path, payload)
    _complete_archive_moves(home, archive_root)
    _make_tree_read_only(archive_root)
    integrity_errors = _archive_integrity_errors(home, archive_root, payload)
    if integrity_errors:
        raise RuntimeError(f"legacy retirement archive integrity failed: {', '.join(integrity_errors)}")
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
    _disable_legacy_config(home)
    _complete_archive_moves(home, archive_root)
    _make_tree_read_only(archive_root)
    integrity_errors = _archive_integrity_errors(home, archive_root, manifest)
    if integrity_errors:
        raise RuntimeError(f"legacy retirement archive integrity failed: {', '.join(integrity_errors)}")
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
        for relative in LEGACY_SOURCE_RELATIVE_PATHS
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
        cron_records = _legacy_cron_records(home)
    except RuntimeError:
        cron_records = []
        cron_registry_error = True
    enabled_legacy_crons = [record["name"] for record in cron_records if record.get("enabled") is True]
    violations = []
    if manifest_errors:
        violations.append("retirement_manifest_invalid")
    if live_inventory_error:
        violations.append("legacy_source_inventory_error")
    if archive_inventory_error:
        violations.append("archive_inventory_error")
    if cron_registry_error:
        violations.append("legacy_cron_registry_invalid")
    if retired and (archive_root is None or not archive_root.is_dir()):
        violations.append("archive_missing")
    if retired and manifest_writable:
        violations.append("retirement_manifest_writable")
    if pending:
        violations.append("retirement_pending_incomplete")
    if retired and live_sources:
        violations.append("legacy_source_recreated")
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
    if enabled_legacy_crons:
        violations.append("legacy_cron_enabled")
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
        "enabled_legacy_cron_count": len(enabled_legacy_crons),
        "enabled_legacy_cron_names": enabled_legacy_crons,
        "violations": violations,
        "active_observation": False if retired or pending else None,
        "active_execution": False if retired or pending else None,
        "raw_body_included": False,
        "actual_send": False,
        "actual_execute": False,
    }


def _assert_prerequisites(home: Path) -> None:
    config_path = home / "memory-os" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid Memory-OS config: {config_path}") from exc
    right_brain = config.get("right_brain_expression") if isinstance(config, dict) else {}
    if isinstance(right_brain, dict) and right_brain.get("legacy_cognitive_loop_enabled") is True:
        raise RuntimeError("legacy_cognitive_loop_enabled must be false before retirement")
    enabled = [record["name"] for record in _legacy_cron_records(home) if record.get("enabled") is True]
    if enabled:
        raise RuntimeError(f"legacy cron jobs must be paused before retirement: {', '.join(enabled)}")


def _disable_legacy_config(home: Path) -> None:
    path = home / "memory-os" / "config.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        loaded = {}
    if not isinstance(loaded, dict):
        raise RuntimeError(f"invalid Memory-OS config root: {path}")
    section = loaded.get("right_brain_expression")
    if not isinstance(section, dict):
        section = {}
        loaded["right_brain_expression"] = section
    section.update(
        {
            "legacy_cognitive_loop_enabled": False,
            "recurring_delivery_enabled": False,
            "recurring_delivery_mode": "disabled",
            "recurring_delivery_channel": "unknown",
            "recurring_delivery_target_class": "missing",
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, loaded)


def _legacy_cron_records(home: Path) -> list[dict[str, Any]]:
    jobs_path = home / "cron" / "jobs.json"
    try:
        loaded = json.loads(jobs_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"invalid legacy cron registry: {jobs_path}") from exc
    if isinstance(loaded, dict):
        jobs = loaded.get("jobs", [])
    elif isinstance(loaded, list):
        jobs = loaded
    else:
        raise RuntimeError(f"invalid legacy cron registry root: {jobs_path}")
    if not isinstance(jobs, list):
        raise RuntimeError(f"invalid legacy cron jobs list: {jobs_path}")
    result = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        name = str(job.get("name") or "")
        script = str(job.get("script") or "")
        if name not in LEGACY_CRON_NAMES and script not in RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES:
            continue
        schedule = job.get("schedule")
        if isinstance(schedule, dict):
            schedule = schedule.get("display") or schedule.get("expr") or schedule.get("kind")
        result.append(
            {
                "name": name,
                "job_id": str(job.get("job_id") or job.get("id") or ""),
                "enabled": bool(job.get("enabled", True)),
                "state": str(job.get("state") or ("scheduled" if job.get("enabled", True) else "paused")),
                "schedule": str(schedule or ""),
                "script": script,
                "deliver": str(job.get("deliver") or ""),
                "no_agent": bool(job.get("no_agent", False)),
                "last_run_at": job.get("last_run_at"),
                "last_status": job.get("last_status"),
            }
        )
    return sorted(result, key=lambda item: item["name"])


def _inventory_sources(home: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative_root in LEGACY_SOURCE_RELATIVE_PATHS:
        source = home / relative_root
        if not _path_lexists(source):
            continue
        if source.is_symlink():
            raise RuntimeError(f"symlink is not allowed in legacy archive: {source}")
        if source.is_file():
            records.append(_file_record(source, relative_root.as_posix()))
            continue
        if not source.is_dir():
            raise RuntimeError(f"unsupported legacy artifact source: {source}")
        for record in _inventory(source):
            record["relative_path"] = (relative_root / str(record["relative_path"])).as_posix()
            records.append(record)
    return sorted(records, key=lambda item: str(item["relative_path"]))


def _inventory(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"legacy artifact root must be a real directory: {root}")
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"symlink is not allowed in legacy archive: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError(f"unsupported file type in legacy archive: {path}")
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
    for relative in LEGACY_SOURCE_RELATIVE_PATHS:
        source = home / relative
        target = archive_root / relative
        if _path_lexists(source) and _path_lexists(target):
            raise RuntimeError(f"legacy retirement source and archive target both exist: {relative}")
        if not _path_lexists(source):
            continue
        if source.is_symlink():
            raise RuntimeError(f"symlink is not allowed in legacy archive: {source}")
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
    if any(_path_lexists(home / relative) for relative in LEGACY_SOURCE_RELATIVE_PATHS):
        errors.append("legacy_source_still_live")
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
            raise RuntimeError(f"symlink is not allowed in legacy archive: {path}")
        if path.is_file():
            path.chmod(stat.S_IRUSR)
            _fsync_file(path)
        elif path.is_dir():
            path.chmod(stat.S_IRUSR | stat.S_IXUSR)
            _fsync_directory(path)
        else:
            raise RuntimeError(f"unsupported file type in legacy archive: {path}")
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
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
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
