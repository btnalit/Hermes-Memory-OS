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
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope, WORKING_SCHEMA_VERSION
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
        "profile": roots.profile,
        "dry_run": dry_run,
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
        decision = approval_from_cw019_state(
            candidate_id="shadow-count",
            cw019_state=status,
            reviewer="shadow-import",
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        state = {
            "approve_for_visibility": "approved_for_s5_visibility",
            "reject": "rejected",
            "defer": "deferred",
        }.get(decision.purpose.value, decision.purpose.value)
        mapped[state] = mapped.get(state, 0) + int(count)
    return mapped


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
        store.write_working_document(
            "lingering",
            {"schema_version": WORKING_SCHEMA_VERSION, "updated_at": datetime.now(timezone.utc).isoformat(), "items": []},
        )


def _bundle_relative_path(source: dict[str, Any]) -> Path:
    return Path(str(source["area"])) / Path(str(source["relative_path"]))


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
