"""Read-only StateSourceMirror scanner for Memory-OS source coverage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit
from .ids import new_event_id
from .jsonl_io import build_error_record, read_json_state_result
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
from .store import MemoryOSStore


@dataclass(frozen=True)
class StateSourceClass:
    source_class: str
    relative_pattern: str
    event_kind: str
    drive_policy: str


STATE_SOURCE_CLASSES: tuple[StateSourceClass, ...] = (
    StateSourceClass("state:memory_journal_events", "memory_journal/events.jsonl", "journal_card_observed", "low_weight"),
    StateSourceClass("state:digest_daily", "digests/daily/*", "state_source_changed", "low_weight"),
    StateSourceClass("state:digest_weekly", "digests/weekly/*", "state_source_changed", "low_weight"),
    StateSourceClass("state:treasure_index", "treasure_index.md", "state_source_changed", "low_weight"),
    StateSourceClass("state:quiet_moments", "quiet_moments.jsonl", "candidate_surface_changed", "candidate_surface"),
    StateSourceClass(
        "state:heartbeat_lingering_candidates",
        "heartbeat_lingering_candidates.jsonl",
        "candidate_surface_changed",
        "candidate_surface",
    ),
    StateSourceClass("state:diary", "diary.md", "state_source_changed", "evidence_only"),
    StateSourceClass("state:self_memory", "self_memory.md", "state_source_changed", "evidence_only"),
    # Hermes host-maintained owner memory files (2026-08-06, owner decision:
    # the mirror is meant to be USED — production's only real state root is
    # <hermes_home>/memories with exactly these two files). Metadata-only
    # events like every other class: hash/size/mtime, never content.
    StateSourceClass("state:owner_memory_md", "MEMORY.md", "state_source_changed", "evidence_only"),
    StateSourceClass("state:owner_user_md", "USER.md", "state_source_changed", "evidence_only"),
    StateSourceClass("state:relationship_memory", "relationship_memory.md", "state_source_changed", "evidence_only"),
    StateSourceClass("state:lingering_thoughts", "lingering_thoughts.json", "state_source_changed", "evidence_only"),
)


class StateSourceMirror:
    """Mirror allowlisted state-source facts into summary-only Memory-OS events."""

    state_schema_version = "memory-os.state_source_mirror_state.v0"
    report_schema_version = "memory-os.state_source_mirror_report.v0"

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    @property
    def state_path(self) -> Path:
        return self.store.roots.memory_os_root / "runtime" / "state_source_mirror_state.json"

    def status(self) -> dict[str, Any]:
        state, rebuilt, findings, error_records = self._load_state(persist_repair=False)
        sources = self._discover_sources(findings)
        pending = [source for source in sources if source["dedup_key"] not in state["seen_sources"]]
        return {
            "schema_version": "memory-os.state_source_mirror_status.v0",
            "status": "ok" if not findings else "warning",
            "profile": self.store.roots.profile,
            "state_root_count": len(self.store.roots.external_state_roots),
            "source_count": len(sources),
            "pending_source_count": len(pending),
            "state_path": str(self.state_path),
            "state_rebuilt": rebuilt,
            "suppressed_error_count": len(error_records),
            "recent_error_codes": _recent_error_codes(error_records),
            "findings": findings,
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        for root in self.store.roots.external_state_roots:
            if not root.exists():
                findings.append(_finding("state_root_missing", "warning", "Configured state root does not exist.", {"root": str(root)}))
            elif not root.is_dir():
                findings.append(_finding("state_root_not_directory", "error", "Configured state root is not a directory.", {"root": str(root)}))
        self._discover_sources(findings)
        status = "error" if any(finding["severity"] == "error" for finding in findings) else ("warning" if findings else "ok")
        return {
            "schema_version": "memory-os.state_source_mirror_doctor.v0",
            "status": status,
            "profile": self.store.roots.profile,
            "findings": findings,
        }

    def scan(self, *, dry_run: bool = True) -> dict[str, Any]:
        if not dry_run:
            self.store.initialize()
        state, state_rebuilt, findings, error_records = self._load_state(persist_repair=not dry_run)
        sources = self._discover_sources(findings)
        new_sources = [source for source in sources if source["dedup_key"] not in state["seen_sources"]]
        written_events: list[str] = []
        if not dry_run:
            for source in new_sources:
                event = self._event_for_source(source)
                self.store.append_event(event)
                state["seen_sources"][source["dedup_key"]] = {
                    "event_id": event.id,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                }
                written_events.append(event.id)
            state["last_scan_at"] = datetime.now(timezone.utc).isoformat()
            self._write_state(state)
            append_audit(
                self.store.roots.audit_path,
                action="state_source_mirror_scan",
                status="ok",
                target=str(self.store.roots.external_state_roots),
                details={
                    "dry_run": False,
                    "new_event_count": len(written_events),
                    "state_rebuilt": state_rebuilt,
                },
            )
        return {
            "schema_version": self.report_schema_version,
            "status": "ok" if not findings else "warning",
            "profile": self.store.roots.profile,
            "state_root_count": len(self.store.roots.external_state_roots),
            "source_count": len(sources),
            "new_event_count": len(new_sources),
            "dry_run": dry_run,
            "state_rebuilt": state_rebuilt,
            "suppressed_error_count": len(error_records),
            "recent_error_codes": _recent_error_codes(error_records),
            "written_event_ids": written_events,
            "findings": findings,
        }

    def _discover_sources(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for root in self.store.roots.external_state_roots:
            if not root.exists() or not root.is_dir():
                continue
            for source_class in STATE_SOURCE_CLASSES:
                for path in sorted(root.glob(source_class.relative_pattern)):
                    if not path.is_file():
                        continue
                    try:
                        sources.append(_source_record(root, path, source_class))
                    except OSError as exc:
                        findings.append(
                            _finding(
                                "state_source_unreadable",
                                "error",
                                "Allowlisted state source cannot be read.",
                                {"path": str(path), "error": str(exc)},
                            )
                        )
        return sources

    def _load_state(self, *, persist_repair: bool) -> tuple[dict[str, Any], bool, list[dict[str, Any]], list[dict[str, Any]]]:
        if not self.state_path.exists():
            return self._rebuild_state(), False, [], []
        state_result = read_json_state_result(
            self.state_path,
            component="state_source_mirror",
            operation="load_state",
        )
        error_records = list(state_result.error_records)
        data = state_result.data
        if not error_records and not isinstance(data.get("seen_sources", {}), dict):
            error_records.append(
                build_error_record(
                    component="state_source_mirror",
                    operation="load_state",
                    error_code="state_source_mirror_state_invalid_shape",
                    severity="warning",
                    recoverable=True,
                    path=self.state_path,
                )
            )
        if error_records:
            state = self._rebuild_state()
            if persist_repair:
                self._write_state(state)
            return state, True, [
                _finding(
                    "state_source_mirror_state_rebuilt",
                    "warning",
                    "StateSourceMirror state was corrupt and rebuilt from Memory-OS events.",
                    {"error_records": [_bounded_error_record(record) for record in error_records]},
                )
            ], error_records
        data.setdefault("schema_version", self.state_schema_version)
        data.setdefault("last_scan_at", "")
        data.setdefault("seen_sources", {})
        return data, False, [], []

    def _rebuild_state(self) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for record in _read_event_records(self.store):
            safe_ref = record.get("safe_ref", {})
            if not isinstance(safe_ref, dict) or safe_ref.get("source_module") != "state_source_mirror":
                continue
            dedup_key = str(safe_ref.get("dedup_key", ""))
            if dedup_key:
                seen[dedup_key] = {
                    "event_id": str(record.get("id", "")),
                    "indexed_at": str(record.get("ts", "")),
                }
        return {
            "schema_version": self.state_schema_version,
            "seen_sources": seen,
            "last_scan_at": "",
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _event_for_source(self, source: dict[str, Any]) -> EventEnvelope:
        now = datetime.now(timezone.utc)
        unique = hashlib.sha256(str(source["dedup_key"]).encode("utf-8")).hexdigest()[:10]
        summary = (
            f"State source {source['source_class']} changed; "
            f"records={source['record_count']}; size={source['source_size']}."
        )
        safe_ref = {
            "source_module": "state_source_mirror",
            "source_class": source["source_class"],
            "source_ref": source["source_ref"],
            "relative_path": source["relative_path"],
            "source_sha256": source["source_sha256"],
            "source_size": source["source_size"],
            "source_mtime": source["source_mtime"],
            "record_count": source["record_count"],
            "dedup_key": source["dedup_key"],
            "drive_policy": source["drive_policy"],
            "candidate_allowed": False,
            "body_policy": "summary_only",
        }
        if source.get("candidate_status_counts"):
            safe_ref["candidate_status_counts"] = dict(source["candidate_status_counts"])
        return EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id=new_event_id(now, unique=unique),
            ts=now.isoformat(),
            profile=self.store.roots.profile or "default",
            source="state_source_mirror",
            kind=source["event_kind"],
            summary=summary,
            safe_ref=safe_ref,
            tags=["state", "mirror", source["event_kind"], source["source_class"]],
            sensitivity="private",
            body_policy="summary_only",
            hashes={"source_sha256": source["source_sha256"]},
            promotion_state="raw",
        )


def _source_record(root: Path, path: Path, source_class: StateSourceClass) -> dict[str, Any]:
    source_hash = _sha256_file(path)
    relative_path = path.relative_to(root).as_posix()
    record = {
        "source_class": source_class.source_class,
        "source_ref": str(path.resolve()),
        "relative_path": relative_path,
        "source_sha256": source_hash,
        "source_size": path.stat().st_size,
        "source_mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "record_count": _record_count(path),
        "event_kind": source_class.event_kind,
        "drive_policy": source_class.drive_policy,
        "dedup_key": f"state_source::{source_class.source_class}::{relative_path}::{source_hash}",
    }
    if source_class.source_class in {"state:heartbeat_lingering_candidates", "state:quiet_moments"}:
        record["candidate_status_counts"] = _candidate_status_counts(path)
    return record


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_count(path: Path) -> int:
    if path.suffix == ".jsonl":
        return len([line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()])
    if path.suffix == ".json":
        try:
            parsed = json.loads(path.read_text(encoding="utf-8", errors="replace"))
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
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            status = str(record.get("status") or "candidate")
            counts[status] = counts.get(status, 0) + 1
    return counts


def _read_event_records(store: MemoryOSStore) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(store.roots.events_root.glob("*/*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def _recent_error_codes(error_records: list[dict[str, Any]]) -> list[str]:
    return [str(record.get("error_code") or "") for record in error_records if record.get("error_code")][:10]


def _bounded_error_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": record.get("schema_version"),
        "component": record.get("component"),
        "operation": record.get("operation"),
        "error_code": record.get("error_code"),
        "severity": record.get("severity"),
        "recoverable": record.get("recoverable"),
        "path": record.get("path"),
    }


def _finding(id_: str, severity: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": id_, "code": id_, "severity": severity, "message": message, "details": details or {}}
