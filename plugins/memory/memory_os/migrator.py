"""Transition helpers for legacy Hermes/Sannai memory shapes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .approval import approval_from_cw019_state
from .audit import append_audit
from .ids import new_event_id
from .roots import MemoryOSRoots
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
from .store import MemoryOSStore
from .working import WorkingMemoryService


_PROFILE_FILES = (
    ("soul", Path("SOUL.md")),
    ("memory", Path("memories") / "MEMORY.md"),
    ("user", Path("memories") / "USER.md"),
)

_STATE_FILES = (
    ("state:diary", Path("diary.md")),
    ("state:self_memory", Path("self_memory.md")),
    ("state:lingering_thoughts", Path("lingering_thoughts.json")),
    ("state:quiet_moments", Path("quiet_moments.jsonl")),
    ("state:heartbeat_lingering_candidates", Path("heartbeat_lingering_candidates.jsonl")),
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)\S+"),
)

# Assigned states (census-pinned by test_migrator_state_literals_census):
# scan_only, redacted_bundle, shadow_bundle, shadow_import, shadow_replay,
# diff_report. The last three below are RESERVED — declared for the
# owner-approved apply/rollback phases that were never built; no code path
# assigns them. Implementing one means consciously updating the census test.
MIGRATOR_STATES = (
    "scan_only",
    "redacted_bundle",
    "shadow_bundle",
    "shadow_import",
    "shadow_replay",
    "diff_report",
    "owner_review",
    "approved_apply",
    "rollback_ready",
)


def scan_legacy_sources(roots: MemoryOSRoots) -> list[dict[str, Any]]:
    """Return metadata for known legacy Sannai/Hermes source shapes."""

    sources: list[dict[str, Any]] = []
    for kind, relative in _PROFILE_FILES:
        path = roots.hermes_home / relative
        if path.exists():
            sources.append(_source_metadata(kind, path, "profile", relative))

    for state_root in roots.external_state_roots:
        for kind, relative in _STATE_FILES:
            path = state_root / relative
            if path.exists():
                sources.append(_source_metadata(kind, path, "state", relative))
        daily_root = state_root / "digests" / "daily"
        if daily_root.exists():
            for path in sorted(daily_root.glob("*")):
                if path.is_file():
                    sources.append(_source_metadata("state:digests_daily", path, "state", path.relative_to(state_root)))
    return sources


def migration_scan_report(roots: MemoryOSRoots, *, dry_run: bool = True) -> dict[str, Any]:
    sources = scan_legacy_sources(roots)
    return {
        "schema_version": "memory-os.migration_scan.v0",
        "state": "scan_only",
        "profile": roots.profile,
        "dry_run": dry_run,
        "source_count": len(sources),
        "record_count": sum(int(source.get("record_count", 0)) for source in sources),
        "candidate_status_counts": _merge_candidate_counts(sources),
        "would_write_paths": [],
        "written_paths": [],
        "sources": sources,
    }


def export_shadow_bundle(
    roots: MemoryOSRoots,
    *,
    out_path: str | Path,
    include_private_bodies: bool = False,
    exclude_secrets: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    out = Path(out_path)
    sources = scan_legacy_sources(roots)
    candidate_counts = _merge_candidate_counts(sources)
    would_write_paths = [str(out / "manifest.json")]
    if include_private_bodies:
        would_write_paths.extend(str(out / "source" / _bundle_relative_path(source)) for source in sources)
    report = {
        "schema_version": "memory-os.shadow_bundle.v0",
        "state": "shadow_bundle" if include_private_bodies else "redacted_bundle",
        "profile": roots.profile,
        "dry_run": dry_run,
        "redacted": not include_private_bodies,
        "include_private_bodies": include_private_bodies,
        "exclude_secrets": exclude_secrets,
        "source_count": len(sources),
        "record_count": sum(int(source.get("record_count", 0)) for source in sources),
        "candidate_status_counts": candidate_counts,
        "would_write_paths": would_write_paths,
        "written_paths": [],
        "skipped_paths": [],
        "sources": sources,
    }
    if dry_run:
        return report

    out.mkdir(parents=True, exist_ok=True)
    if include_private_bodies:
        for source in sources:
            target = out / "source" / _bundle_relative_path(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = Path(str(source["path"])).read_text(encoding="utf-8")
            if exclude_secrets:
                content = _redact(content)
            target.write_text(content, encoding="utf-8")
            report["written_paths"].append(str(target))
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["written_paths"].append(str(manifest_path))
    return report


def import_shadow_bundle(
    bundle_path: str | Path,
    roots: MemoryOSRoots,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    bundle = Path(bundle_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    import_root = roots.imports_root / bundle.name
    report_path = import_root / "import_report.json"
    candidate_counts = dict(manifest.get("candidate_status_counts", {}))
    approval_counts = _approval_state_counts(candidate_counts)
    report = {
        "schema_version": "memory-os.shadow_import_report.v0",
        "state": "shadow_import",
        "profile": roots.profile,
        "dry_run": dry_run,
        "source_count": int(manifest.get("source_count", 0)),
        "record_count": int(manifest.get("record_count", 0)),
        "candidate_status_counts": candidate_counts,
        "approval_state_counts": approval_counts,
        "would_write_paths": [str(report_path), str(roots.events_root)],
        "written_paths": [],
        "skipped_private_bodies": [],
        "schema_errors": [],
    }
    if dry_run:
        return report

    store = MemoryOSStore(roots)
    store.initialize()
    import_root.mkdir(parents=True, exist_ok=True)
    (import_root / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report["written_paths"].append(str(import_root / "source_manifest.json"))
    for source in manifest.get("sources", []):
        event = _event_for_source(source, roots.profile)
        store.append_event(event)
    _import_lingering_if_present(bundle, store)
    report["written_paths"].append(str(report_path))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    append_audit(
        roots.audit_path,
        action="shadow_bundle_imported",
        status="ok",
        target=str(import_root),
        details={
            "source_count": report["source_count"],
            "candidate_status_counts": candidate_counts,
        },
    )
    return report


def replay_shadow_import(
    roots: MemoryOSRoots,
    *,
    dry_run: bool = True,
    no_adapter_export: bool = True,
) -> dict[str, Any]:
    if not no_adapter_export:
        raise ValueError("Memory-OS v0 shadow replay requires adapter export to stay disabled.")

    store = MemoryOSStore(roots)
    events = [event for event in store.read_events() if event.source == "shadow_import"]
    report = {
        "schema_version": "memory-os.migration_replay.v0",
        "state": "shadow_replay",
        "profile": roots.profile,
        "dry_run": dry_run,
        "events_replayed": len(events),
        "message_delivery": "disabled",
        "messages_sent": 0,
        "adapter_export": "disabled",
        "adapter_exported": False,
        "crystallized_created": 0,
        "would_write_paths": [str(roots.audit_path)],
        "written_paths": [],
    }
    if dry_run:
        return report

    append_audit(
        roots.audit_path,
        action="shadow_replay_completed",
        status="ok",
        target=str(roots.memory_os_root),
        details={
            "events_replayed": len(events),
            "message_delivery": "disabled",
            "adapter_export": "disabled",
        },
    )
    report["written_paths"].append(str(roots.audit_path))
    return report


def migration_diff_report(source_report_path: str | Path, roots: MemoryOSRoots) -> dict[str, Any]:
    source_report_file = Path(source_report_path)
    source_report = json.loads(source_report_file.read_text(encoding="utf-8"))
    store = MemoryOSStore(roots)
    imported_events = [event for event in store.read_events() if event.source == "shadow_import"]
    import_reports = _read_import_reports(roots)
    candidate_counts = dict(source_report.get("candidate_status_counts", {}))
    if not candidate_counts:
        for import_report in import_reports:
            _merge_counts(candidate_counts, import_report.get("candidate_status_counts", {}))
    schema_errors: list[Any] = []
    skipped_private_bodies = _skipped_private_bodies(source_report, source_report_file)
    would_write_paths = set(str(path) for path in source_report.get("would_write_paths", []))
    would_write_paths.add(str(roots.events_root))
    for import_report in import_reports:
        schema_errors.extend(import_report.get("schema_errors", []))
        skipped_private_bodies.extend(import_report.get("skipped_private_bodies", []))
        would_write_paths.update(str(path) for path in import_report.get("would_write_paths", []))

    source_count = int(source_report.get("source_count", 0))
    imported_count = len(imported_events)
    return {
        "schema_version": "memory-os.migration_diff.v0",
        "state": "diff_report",
        "profile": roots.profile,
        "source_report": str(source_report_file.resolve()),
        "target_root": str(roots.memory_os_root),
        "source_count": source_count,
        "imported_count": imported_count,
        "record_count": int(source_report.get("record_count", 0)),
        "skipped_private_bodies": sorted(set(str(path) for path in skipped_private_bodies)),
        "skipped_private_body_count": len(set(str(path) for path in skipped_private_bodies)),
        "schema_errors": schema_errors,
        "candidate_status_counts": candidate_counts,
        "approval_state_counts": _approval_state_counts(candidate_counts),
        "approval_state_mapping": {
            status: _approval_state_for_cw019_status(status)
            for status in sorted(candidate_counts)
        },
        "would_write_paths": sorted(would_write_paths),
        "crystallized_count": _crystallized_record_count(roots),
        "ready_for_owner_review": source_count == imported_count and not schema_errors,
    }


def _source_metadata(kind: str, path: Path, area: str, relative_path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "kind": kind,
        "area": area,
        "relative_path": str(relative_path).replace("\\", "/"),
        "path": str(path.resolve()),
        "size": path.stat().st_size,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "sha256": _sha256_file(path),
        "record_count": _record_count(path),
    }
    if kind == "state:heartbeat_lingering_candidates":
        metadata["candidate_status_counts"] = _candidate_status_counts(path)
    return metadata


def _record_count(path: Path) -> int:
    if path.suffix == ".jsonl":
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
    if path.suffix == ".json":
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        if isinstance(parsed, list):
            return len(parsed)
        if isinstance(parsed, dict):
            return 1
        return 0
    return 1


def _candidate_status_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = str(record.get("status") or "candidate")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _merge_candidate_counts(sources: list[dict[str, Any]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for source in sources:
        for status, count in source.get("candidate_status_counts", {}).items():
            merged[status] = merged.get(status, 0) + int(count)
    return merged


def _approval_state_counts(candidate_counts: dict[str, int]) -> dict[str, int]:
    mapped: dict[str, int] = {}
    for status, count in candidate_counts.items():
        state = _approval_state_for_cw019_status(status)
        mapped[state] = mapped.get(state, 0) + int(count)
    return mapped


def _approval_state_for_cw019_status(status: str) -> str:
    decision = approval_from_cw019_state(
        candidate_id="shadow-count",
        cw019_state=status,
        reviewer="shadow-import",
        reviewed_at=datetime.now(timezone.utc).isoformat(),
    )
    return {
        "approve_for_visibility": "approved_for_s5_visibility",
        "reject": "rejected",
        "defer": "deferred",
    }.get(decision.purpose.value, decision.purpose.value)


def _event_for_source(source: dict[str, Any], profile: str) -> EventEnvelope:
    now = datetime.now(timezone.utc)
    return EventEnvelope.from_dict(
        {
            "schema_version": EVENT_SCHEMA_VERSION,
            "id": new_event_id(now),
            "ts": now.isoformat(),
            "profile": profile,
            "source": "shadow_import",
            "kind": "legacy_source",
            "summary": f"Imported shadow source {source.get('kind')}: {source.get('relative_path')}",
            "safe_ref": {
                "kind": source.get("kind"),
                "relative_path": source.get("relative_path"),
                "sha256": source.get("sha256"),
                "candidate_status_counts": source.get("candidate_status_counts", {}),
            },
            "tags": ["memory-os", "shadow-import"],
            "sensitivity": "private",
            "body_policy": "summary_only",
            "hashes": {"source_sha256": source.get("sha256", "")},
            "promotion_state": "raw",
        }
    )


def _import_lingering_if_present(bundle: Path, store: MemoryOSStore) -> None:
    lingering_path = bundle / "source" / "state" / "lingering_thoughts.json"
    if not lingering_path.exists():
        return
    try:
        parsed = json.loads(lingering_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(parsed, list):
        return
    service = WorkingMemoryService(store)
    imported_items = []
    for index, record in enumerate(parsed):
        if isinstance(record, dict):
            text = str(record.get("text") or record.get("summary") or record.get("thought") or f"legacy lingering item {index}")
            weight = float(record.get("weight") or record.get("intensity") or 0.5)
        else:
            text = str(record)
            weight = 0.5
        imported_items.append(asdict(service.add_item("lingering", text, tags=["shadow-import"], weight=weight)))
    if not imported_items and parsed == []:
        service.initialize_empty_document("lingering")


def _bundle_relative_path(source: dict[str, Any]) -> Path:
    return Path(str(source["area"])) / Path(str(source["relative_path"]))


def _read_import_reports(roots: MemoryOSRoots) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for report_path in sorted(roots.imports_root.glob("*/import_report.json")):
        try:
            reports.append(json.loads(report_path.read_text(encoding="utf-8")))
        except Exception as exc:
            reports.append({"schema_errors": [{"path": str(report_path), "error": str(exc)}]})
    return reports


def _skipped_private_bodies(source_report: dict[str, Any], source_report_file: Path) -> list[str]:
    if source_report.get("include_private_bodies"):
        skipped = []
        for source in source_report.get("sources", []):
            body_path = source_report_file.parent / "source" / _bundle_relative_path(source)
            if not body_path.exists():
                skipped.append(str(_bundle_relative_path(source)))
        return skipped
    return [str(_bundle_relative_path(source)) for source in source_report.get("sources", [])]


def _crystallized_record_count(roots: MemoryOSRoots) -> int:
    count = 0
    for path in sorted(roots.crystallized_root.glob("*.md")):
        count += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip() == "---") // 2
    return count


def _merge_counts(target: dict[str, int], source: dict[str, Any]) -> None:
    for key, value in source.items():
        target[str(key)] = target.get(str(key), 0) + int(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redact(content: str) -> str:
    redacted = content
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    return redacted
