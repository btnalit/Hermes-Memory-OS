"""Dry-run-first cleanup and retention helpers for Memory-OS."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit import append_audit
from .ids import new_audit_id
from .jsonl_io import locked_jsonl_file
from .store import MemoryOSStore


@dataclass(frozen=True)
class CleanupPolicy:
    quarantine_retention_days: int | None = 30
    import_retention_days: int | None = 30
    benchmark_retention_days: int | None = 14
    temp_retention_days: int | None = 1
    expired_working_retention_days: int | None = None
    event_retention_days_by_source_class: dict[str, int] | None = None


LOW_VALUE_EVENT_SOURCE_CLASSES = {
    "telemetry",
    "status",
    "metrics",
    "runtime",
    "runtime_status",
}


HIGH_VALUE_EVENT_SOURCE_CLASSES = {
    "foreground",
    "memory_write",
    "mirrored_conversation",
    "tool_failure",
    "milestone",
    "governance",
    "owner",
    "relationship",
}


PROTECTED_APPROVAL_STATES = {
    "candidate",
    "owner_eligible",
    "owner_defer",
    "approved_for_proposal",
    "approved_for_s5_visibility",
    "approved_crystallized",
    "crystallized",
}


def cleanup_plan(
    store: MemoryOSStore,
    *,
    now: datetime | None = None,
    policy: CleanupPolicy | None = None,
) -> dict[str, Any]:
    """Return cleanup actions without mutating the filesystem."""

    current = _datetime(now)
    active_policy = policy or CleanupPolicy()
    protected_paths = _protected_paths(store)
    actions: list[dict[str, Any]] = []

    _collect_file_actions(
        actions,
        store.roots.quarantine_root,
        kind="delete_quarantine_file",
        retention_days=active_policy.quarantine_retention_days,
        now=current,
        protected_paths=protected_paths,
    )
    _collect_file_actions(
        actions,
        store.roots.imports_root,
        kind="delete_import_file",
        retention_days=active_policy.import_retention_days,
        now=current,
        protected_paths=protected_paths,
    )
    _collect_file_actions(
        actions,
        store.roots.memory_os_root / "benchmarks",
        kind="delete_benchmark_artifact",
        retention_days=active_policy.benchmark_retention_days,
        now=current,
        protected_paths=protected_paths,
    )
    _collect_file_actions(
        actions,
        store.roots.memory_os_root / "tmp",
        kind="delete_temp_file",
        retention_days=active_policy.temp_retention_days,
        now=current,
        protected_paths=protected_paths,
    )
    if active_policy.expired_working_retention_days is not None:
        _collect_expired_working_actions(
            actions,
            store,
            retention_days=active_policy.expired_working_retention_days,
            now=current,
            protected_paths=protected_paths,
        )
    event_retention = _collect_event_retention_actions(
        actions,
        store,
        retention_by_source_class=active_policy.event_retention_days_by_source_class or {},
        now=current,
    )

    return {
        "schema_version": "memory-os.cleanup_plan.v0",
        "plan_id": _new_plan_id(current),
        "created_at": current.isoformat(),
        "dry_run": True,
        "policy": {
            "quarantine_retention_days": active_policy.quarantine_retention_days,
            "import_retention_days": active_policy.import_retention_days,
            "benchmark_retention_days": active_policy.benchmark_retention_days,
            "temp_retention_days": active_policy.temp_retention_days,
            "expired_working_retention_days": active_policy.expired_working_retention_days,
            "event_retention_days_by_source_class": active_policy.event_retention_days_by_source_class or {},
        },
        "event_retention": event_retention,
        "actions": actions,
        "protected_paths": [str(path) for path in sorted(protected_paths)],
    }


def apply_cleanup(
    store: MemoryOSStore,
    plan: dict[str, Any],
    *,
    confirmed_plan_id: str | None = None,
    require_confirmed_plan_id: bool = True,
) -> dict[str, Any]:
    """Apply a generated cleanup plan only after explicit plan-id confirmation."""

    plan_id = str(plan.get("plan_id", ""))
    if require_confirmed_plan_id and confirmed_plan_id != plan_id:
        append_audit(
            store.roots.audit_path,
            action="cleanup_apply_denied",
            status="warning",
            target=str(store.roots.memory_os_root),
            details={"plan_id": plan_id, "confirmed_plan_id": confirmed_plan_id or ""},
        )
        return {
            "schema_version": "memory-os.cleanup_result.v0",
            "plan_id": plan_id,
            "applied": False,
            "applied_count": 0,
            "skipped_count": len(plan.get("actions", [])),
            "errors": [],
        }

    protected_paths = _protected_paths(store)
    applied_count = 0
    skipped_count = 0
    errors: list[dict[str, Any]] = []
    for action in plan.get("actions", []):
        result = _apply_action(store, action, plan_id=plan_id, protected_paths=protected_paths)
        if result["status"] == "ok":
            applied_count += 1
        elif result["status"] == "error":
            errors.append(result)
        else:
            skipped_count += 1

    return {
        "schema_version": "memory-os.cleanup_result.v0",
        "plan_id": plan_id,
        "applied": applied_count > 0 and not errors,
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "errors": errors,
    }


def _collect_file_actions(
    actions: list[dict[str, Any]],
    root: Path,
    *,
    kind: str,
    retention_days: int | None,
    now: datetime,
    protected_paths: set[Path],
) -> None:
    if retention_days is None or not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if _is_protected(resolved, protected_paths):
            continue
        if not _older_than(path, now=now, days=retention_days):
            continue
        actions.append(_file_action(kind, resolved, now=now, reason=f"older_than_{retention_days}_days"))


def _collect_expired_working_actions(
    actions: list[dict[str, Any]],
    store: MemoryOSStore,
    *,
    retention_days: int,
    now: datetime,
    protected_paths: set[Path],
) -> None:
    if not store.roots.working_root.exists():
        return
    for path in sorted(store.roots.working_root.glob("*.json")):
        resolved = path.resolve()
        if _is_protected(resolved, protected_paths):
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in document.get("items", []):
            if str(item.get("status", "")) != "expired":
                continue
            updated_at = _parse_datetime(str(item.get("updated_at", "")))
            if updated_at is None or now - updated_at < timedelta(days=retention_days):
                continue
            action = _file_action(
                "prune_expired_working_item",
                resolved,
                now=now,
                reason=f"expired_item_older_than_{retention_days}_days",
            )
            action["item_id"] = str(item.get("id", ""))
            actions.append(action)


def _collect_event_retention_actions(
    actions: list[dict[str, Any]],
    store: MemoryOSStore,
    *,
    retention_by_source_class: dict[str, int],
    now: datetime,
) -> dict[str, Any]:
    summary = {
        "policy_source_classes": sorted(retention_by_source_class),
        "scanned_event_count": 0,
        "eligible_low_value_event_count": 0,
        "protected_event_count": 0,
        "archive_only_event_count": 0,
    }
    if not retention_by_source_class:
        return summary
    for event in store.read_events():
        summary["scanned_event_count"] += 1
        source_class = _event_source_class(event)
        retention_days = retention_by_source_class.get(source_class)
        if retention_days is None:
            continue
        age_days = _event_age_days(event, now=now)
        if age_days < retention_days:
            continue
        target = _event_storage_path(store, event)
        if _is_low_value_event(event):
            summary["eligible_low_value_event_count"] += 1
            actions.append(
                {
                    "id": new_audit_id(now, unique=uuid4().hex[:8]).replace(
                        "audit_", "cleanup_action_", 1
                    ),
                    "kind": "prune_event_line",
                    "target": str(target),
                    "event_id": event.id,
                    "source_class": source_class,
                    "reason": f"source_class_{source_class}_older_than_{retention_days}_days",
                    "age_days": age_days,
                    "archive_before_delete": True,
                }
            )
        else:
            summary["protected_event_count"] += 1
            summary["archive_only_event_count"] += 1
            actions.append(
                {
                    "id": new_audit_id(now, unique=uuid4().hex[:8]).replace(
                        "audit_", "cleanup_action_", 1
                    ),
                    "kind": "archive_high_value_event_summary",
                    "target": str(target),
                    "event_id": event.id,
                    "source_class": source_class,
                    "reason": "high_value_or_active_state_requires_archive_not_delete",
                    "age_days": age_days,
                    "delete_after_archive": False,
                }
            )
    return summary


def _apply_action(
    store: MemoryOSStore,
    action: dict[str, Any],
    *,
    plan_id: str,
    protected_paths: set[Path],
) -> dict[str, Any]:
    kind = str(action.get("kind", ""))
    target = Path(str(action.get("target", ""))).resolve()
    is_event_line_action = kind in {"prune_event_line", "archive_high_value_event_summary"}
    if not is_event_line_action and _is_protected(target, protected_paths):
        return _audit_action(store, action, plan_id=plan_id, status="skipped", reason="protected_path")
    if not _allowed_action_target(store, kind, target):
        return _audit_action(store, action, plan_id=plan_id, status="skipped", reason="outside_cleanup_roots")
    try:
        if kind == "prune_expired_working_item":
            _prune_working_item(store, target, str(action.get("item_id", "")))
        elif kind == "archive_high_value_event_summary":
            _archive_event_action(store, action, plan_id=plan_id, deleted=False)
        elif kind == "prune_event_line":
            event = _event_from_file(target, str(action.get("event_id", "")))
            if not event:
                return _audit_action(store, action, plan_id=plan_id, status="skipped", reason="event_not_found")
            if not _is_low_value_event_data(event):
                return _audit_action(store, action, plan_id=plan_id, status="skipped", reason="protected_event")
            _prune_event_line(store, target, str(action.get("event_id", "")), action, plan_id=plan_id)
        else:
            if target.exists():
                target.unlink()
        return _audit_action(store, action, plan_id=plan_id, status="ok", reason="")
    except Exception as exc:
        return _audit_action(store, action, plan_id=plan_id, status="error", reason=str(exc))


def _prune_working_item(store: MemoryOSStore, target: Path, item_id: str) -> None:
    with locked_jsonl_file(target):
        document = json.loads(target.read_text(encoding="utf-8"))
        document["items"] = [
            item for item in document.get("items", [])
            if str(item.get("id", "")) != item_id
        ]
        store.write_working_document(target.stem, document)


def _prune_event_line(
    store: MemoryOSStore,
    target: Path,
    event_id: str,
    action: dict[str, Any],
    *,
    plan_id: str,
) -> None:
    _archive_event_action(store, action, plan_id=plan_id, deleted=True)
    if not target.exists():
        return
    retained_lines: list[str] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = EventLine.from_json(line)
        except Exception:
            retained_lines.append(line)
            continue
        if event.id == event_id:
            continue
        retained_lines.append(line)
    tmp_path = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(
            "".join(f"{line}\n" for line in retained_lines),
            encoding="utf-8",
        )
        tmp_path.replace(target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


class EventLine:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.id = str(data.get("id", ""))

    @classmethod
    def from_json(cls, line: str) -> "EventLine":
        return cls(json.loads(line))


def _archive_event_action(
    store: MemoryOSStore,
    action: dict[str, Any],
    *,
    plan_id: str,
    deleted: bool,
) -> None:
    target = Path(str(action.get("target", "")))
    event_id = str(action.get("event_id", ""))
    event = _event_from_file(target, event_id)
    archive_path = store.roots.memory_os_root / "archive" / "retention" / f"{plan_id}.jsonl"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "memory-os.retention_archive.v0",
        "plan_id": plan_id,
        "action_id": action.get("id", ""),
        "action_kind": action.get("kind", ""),
        "event_id": event_id,
        "source_class": action.get("source_class", ""),
        "deleted_from_hot_events": deleted,
        "event": event,
    }
    with archive_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _event_from_file(target: Path, event_id: str) -> dict[str, Any]:
    if not target.exists():
        return {}
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        if str(event.get("id", "")) == event_id:
            return event
    return {}


def _audit_action(
    store: MemoryOSStore,
    action: dict[str, Any],
    *,
    plan_id: str,
    status: str,
    reason: str,
) -> dict[str, Any]:
    append_audit(
        store.roots.audit_path,
        action="cleanup_apply_action",
        status=status,
        target=str(action.get("target", "")),
        details={
            "plan_id": plan_id,
            "action_id": action.get("id", ""),
            "kind": action.get("kind", ""),
            "reason": reason,
        },
    )
    return {"status": status, "target": str(action.get("target", "")), "reason": reason}


def _allowed_action_target(store: MemoryOSStore, kind: str, target: Path) -> bool:
    allowed_roots = {
        "delete_quarantine_file": store.roots.quarantine_root,
        "delete_import_file": store.roots.imports_root,
        "delete_benchmark_artifact": store.roots.memory_os_root / "benchmarks",
        "delete_temp_file": store.roots.memory_os_root / "tmp",
        "prune_expired_working_item": store.roots.working_root,
        "prune_event_line": store.roots.events_root,
        "archive_high_value_event_summary": store.roots.events_root,
    }
    root = allowed_roots.get(kind)
    return root is not None and _is_relative_to(target, root.resolve())


def _protected_paths(store: MemoryOSStore) -> set[Path]:
    paths = {
        store.roots.identity_manifest_path.resolve(),
        store.roots.identity_manifest_path.parent.resolve(),
        store.roots.crystallized_root.resolve(),
        store.roots.events_root.resolve(),
    }
    for source in store.roots.identity_sources:
        paths.add(Path(source.path).resolve())
    if store.roots.identity_manifest_path.exists():
        try:
            manifest = json.loads(store.roots.identity_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        for source in manifest.get("identity_sources", []):
            path = source.get("path")
            if path:
                paths.add(Path(str(path)).resolve())
    return paths


def _is_protected(path: Path, protected_paths: set[Path]) -> bool:
    return any(path == protected or _is_relative_to(path, protected) for protected in protected_paths)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _older_than(path: Path, *, now: datetime, days: int) -> bool:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return now - mtime >= timedelta(days=days)


def _event_age_days(event: Any, *, now: datetime) -> float:
    parsed = _parse_datetime(str(event.ts))
    if parsed is None:
        return 0.0
    return max(0.0, (now - parsed).total_seconds() / 86400.0)


def _event_source_class(event: Any) -> str:
    safe_ref = getattr(event, "safe_ref", {}) or {}
    value = safe_ref.get("source_class") or safe_ref.get("source_module") or getattr(event, "source", "")
    return str(value).lower()


def _event_storage_path(store: MemoryOSStore, event: Any) -> Path:
    parsed = datetime.fromisoformat(str(event.ts))
    return (
        store.roots.events_root
        / f"{parsed.year:04d}-{parsed.month:02d}"
        / f"{parsed.year:04d}-{parsed.month:02d}-{parsed.day:02d}.jsonl"
    )


def _is_low_value_event(event: Any) -> bool:
    safe_ref = getattr(event, "safe_ref", {}) or {}
    source_class = _event_source_class(event)
    return _is_low_value_event_fields(
        safe_ref=safe_ref,
        source_class=source_class,
        kind=str(getattr(event, "kind", "")).lower(),
    )


def _is_low_value_event_data(event: dict[str, Any]) -> bool:
    safe_ref = event.get("safe_ref", {})
    if not isinstance(safe_ref, dict):
        safe_ref = {}
    source_class = str(
        safe_ref.get("source_class") or safe_ref.get("source_module") or event.get("source", "")
    ).lower()
    return _is_low_value_event_fields(
        safe_ref=safe_ref,
        source_class=source_class,
        kind=str(event.get("kind", "")).lower(),
    )


def _is_low_value_event_fields(
    *,
    safe_ref: dict[str, Any],
    source_class: str,
    kind: str,
) -> bool:
    retention_class = str(safe_ref.get("retention_class", "")).lower()
    approval_state = str(safe_ref.get("approval_state", "")).lower()
    if approval_state in PROTECTED_APPROVAL_STATES:
        return False
    if source_class in HIGH_VALUE_EVENT_SOURCE_CLASSES:
        return False
    if kind.startswith(("conversation", "governance", "proposal", "action_failure", "milestone")):
        return False
    return retention_class == "low_value" or source_class in LOW_VALUE_EVENT_SOURCE_CLASSES


def _file_action(kind: str, target: Path, *, now: datetime, reason: str) -> dict[str, Any]:
    return {
        "id": new_audit_id(now, unique=uuid4().hex[:8]).replace("audit_", "cleanup_action_", 1),
        "kind": kind,
        "target": str(target),
        "reason": reason,
        "age_days": _age_days(target, now=now),
    }


def _age_days(path: Path, *, now: datetime) -> float:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return max(0.0, (now - mtime).total_seconds() / 86400.0)


def _new_plan_id(now: datetime) -> str:
    return new_audit_id(now, unique=uuid4().hex[:8]).replace("audit_", "cleanup_plan_", 1)


def _datetime(value: datetime | None) -> datetime:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return None
