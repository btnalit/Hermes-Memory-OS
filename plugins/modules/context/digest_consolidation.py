"""Digest and consolidation module over bounded Memory-OS records."""

from __future__ import annotations

import json
import hashlib
import os
from collections import defaultdict
from datetime import date, datetime, time, timezone
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


DEFAULT_CONFIG = {
    "time_zone": "UTC",
    "max_candidates_per_week": 5,
    "max_events_per_group": 3,
}


def digest_consolidation_manifest() -> dict[str, Any]:
    """Return the RH-13 digest/consolidation module manifest."""

    return {
        "name": "digest_consolidation",
        "kind": "context",
        "version": "0.1.0",
        "layer": "L2",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["proposal_queue", "evidence_scoring"],
        },
        "provides": {
            "commands": ["status", "doctor", "daily-digest", "weekly-consolidation"],
            "schedules": [],
            "reads": [
                "memory_os.events.summary",
                "memory_os.working",
                "memory_os.crystallized_candidates",
                "local_artifact.proposal_queue_state",
                "local_artifact.evidence_scoring",
            ],
            "writes": [
                "memory_os.audit",
                "local_artifact.digest_consolidation",
                "local_artifact.proposal_queue_state",
            ],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
        "memory_os_compat": {
            "min_version": "0.1.0",
            "max_version": "0.2.x",
            "schema_versions": {
                "event": ["memory-os.event.v0"],
                "working": ["memory-os.working.v0"],
                "crystallized": ["memory-os.crystallized.v0"],
            },
        },
    }


class DigestConsolidationModule:
    """Create bounded digest/consolidation artifacts without approval or send."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "digest_consolidation"

    @property
    def config_path(self) -> Path:
        return self.module_root / "config.json"

    @property
    def daily_root(self) -> Path:
        return self.module_root / "daily"

    @property
    def weekly_root(self) -> Path:
        return self.module_root / "weekly"

    def write_config(self, config: dict[str, Any]) -> Path:
        merged = self.config()
        merged.update(config)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self.config_path

    def config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return dict(DEFAULT_CONFIG)
        parsed = json.loads(self.config_path.read_text(encoding="utf-8"))
        config = dict(DEFAULT_CONFIG)
        if isinstance(parsed, dict):
            config.update(parsed)
        return config

    def status(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.digest_consolidation_status.v0",
            "module": "digest_consolidation",
            "profile": self.profile,
            "delivery_mode": "no-send",
            "daily_artifact_count": _count_json_files(self.daily_root),
            "weekly_artifact_count": _count_json_files(self.weekly_root),
            "actual_send": False,
            "actual_approve": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        config = self.config()
        try:
            _zone(config["time_zone"])
        except Exception:
            findings.append(
                {
                    "severity": "error",
                    "code": "invalid_time_zone",
                    "message": "Digest/consolidation time_zone is invalid",
                }
            )
        artifact_count = _count_json_files(self.daily_root) + _count_json_files(self.weekly_root)
        threshold = int(config.get("artifact_count_warning_threshold", 0) or 0)
        if threshold and artifact_count > threshold:
            findings.append(
                {
                    "severity": "warning",
                    "code": "digest_artifact_count_high",
                    "message": f"Digest artifact count {artifact_count} exceeds warning threshold {threshold}",
                }
            )
        status = "ok"
        if any(finding["severity"] == "error" for finding in findings):
            status = "error"
        elif findings:
            status = "warning"
        return {
            "schema_version": "hermes.digest_consolidation_doctor.v0",
            "module": "digest_consolidation",
            "profile": self.profile,
            "status": status,
            "artifact_count": artifact_count,
            "findings": findings,
        }

    def build_daily_digest(
        self,
        *,
        store: MemoryOSStore,
        target_date: str,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        config = self.config()
        tz = _zone(str(config["time_zone"]))
        window_date = date.fromisoformat(target_date)
        max_events_per_group = int(config.get("max_events_per_group", 3))
        events = [event for event in store.read_events() if event.profile == self.profile]
        selected_events = [
            event
            for event in events
            if _event_local_date(event, tz) == window_date
        ]
        late_events = [
            event
            for event in events
            if _is_late_arrival_for_date(event, window_date, tz)
        ]
        groups = _daily_groups(
            selected_events,
            max_events_per_group=max_events_per_group,
        )
        if late_events:
            groups.append(_late_arrival_group(late_events, max_events_per_group=max_events_per_group, tz=tz))
        artifact = {
            "schema_version": "hermes.digest.daily.v0",
            "profile": self.profile,
            "date": target_date,
            "time_zone": str(config["time_zone"]),
            "window_start": datetime.combine(window_date, time.min, tzinfo=tz).isoformat(),
            "window_end": datetime.combine(window_date, time.max, tzinfo=tz).isoformat(),
            "groups": groups,
            "selected_refs": sorted({ref for group in groups for ref in group.get("selected_refs", [])}),
            "dropped_count": sum(int(group.get("dropped_count", 0)) for group in groups),
            "late_arrival_count": len(late_events),
            "actual_send": False,
            "actual_approve": False,
        }
        artifact_path = self.daily_root / f"{target_date}.json"
        if not dry_run:
            if _json_artifact_matches(artifact_path, artifact):
                return {
                    "schema_version": "hermes.digest.daily_result.v0",
                    "module": "digest_consolidation",
                    "profile": self.profile,
                    "date": target_date,
                    "dry_run": dry_run,
                    "applied": False,
                    "skipped": True,
                    "cadence_skipped": True,
                    "reason": "unchanged_daily_digest",
                    "would_write": artifact,
                    "artifact_ref": str(artifact_path),
                    "actual_send": False,
                    "actual_approve": False,
                }
            else:
                _atomic_write_json(artifact_path, artifact)
                append_audit(
                    store.roots.audit_path,
                    action="digest_daily_written",
                    status="ok",
                    target=str(artifact_path),
                    details={
                        "date": target_date,
                        "selected_count": len(artifact["selected_refs"]),
                        "dropped_count": artifact["dropped_count"],
                        "late_arrival_count": artifact["late_arrival_count"],
                        "actual_send": False,
                        "actual_approve": False,
                    },
                )
        return {
            "schema_version": "hermes.digest.daily_result.v0",
            "module": "digest_consolidation",
            "profile": self.profile,
            "date": target_date,
            "dry_run": dry_run,
            "applied": not dry_run,
            "would_write": artifact,
            "artifact_ref": str(artifact_path),
            "actual_send": False,
            "actual_approve": False,
        }

    def build_weekly_consolidation(
        self,
        *,
        store: MemoryOSStore,
        target_week: str,
        proposal_queue: Any | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        config = self.config()
        tz = _zone(str(config["time_zone"]))
        week_start, week_end = _iso_week_window(target_week, tz)
        events = [
            event
            for event in store.read_events()
            if event.profile == self.profile and _event_in_window(event, week_start, week_end, tz)
        ]
        daily_refs = _daily_refs_for_week(self.daily_root, week_start.date())
        candidate_groups = _weekly_candidate_groups(events, self)
        max_candidates = int(config.get("max_candidates_per_week", 5))
        selected_candidates = candidate_groups[:max_candidates]
        deferred_candidates = candidate_groups[max_candidates:]
        artifact = {
            "schema_version": "hermes.digest.weekly.v0",
            "profile": self.profile,
            "week": target_week,
            "time_zone": str(config["time_zone"]),
            "window_start": week_start.isoformat(),
            "window_end": week_end.isoformat(),
            "daily_digest_refs": daily_refs,
            "expanded_event_refs": [_event_ref(event) for event in sorted(events, key=lambda item: item.id)],
            "forbidden_sources": ["raw_full_session_transcripts"],
            "candidate_suggestions": selected_candidates,
            "deferred_candidate_count": len(deferred_candidates),
            "deferred_candidate_refs": [
                ref for candidate in deferred_candidates for ref in candidate["source_refs"]
            ],
            "actual_send": False,
            "actual_approve": False,
        }
        artifact_path = self.weekly_root / f"{target_week}.json"
        if not dry_run:
            queue_synced = proposal_queue is None or _weekly_proposal_queue_synced(
                proposal_queue=proposal_queue,
                candidates=selected_candidates,
            )
            if _json_artifact_matches(artifact_path, artifact) and queue_synced:
                return {
                    "schema_version": "hermes.digest.weekly_result.v0",
                    "module": "digest_consolidation",
                    "profile": self.profile,
                    "week": target_week,
                    "dry_run": dry_run,
                    "applied": False,
                    "skipped": True,
                    "cadence_skipped": True,
                    "reason": "unchanged_weekly_consolidation",
                    "would_write": artifact,
                    "artifact_ref": str(artifact_path),
                    "actual_send": False,
                    "actual_approve": False,
                }
            else:
                _atomic_write_json(artifact_path, artifact)
                if proposal_queue is not None:
                    for candidate in selected_candidates:
                        _upsert_proposal_candidate(
                            proposal_queue=proposal_queue,
                            store=store,
                            candidate=candidate,
                        )
                append_audit(
                    store.roots.audit_path,
                    action="digest_weekly_written",
                    status="ok",
                    target=str(artifact_path),
                    details={
                        "week": target_week,
                        "expanded_event_count": len(events),
                        "candidate_suggestion_count": len(selected_candidates),
                        "deferred_candidate_count": len(deferred_candidates),
                        "actual_send": False,
                        "actual_approve": False,
                    },
                )
        return {
            "schema_version": "hermes.digest.weekly_result.v0",
            "module": "digest_consolidation",
            "profile": self.profile,
            "week": target_week,
            "dry_run": dry_run,
            "applied": not dry_run,
            "would_write": artifact,
            "artifact_ref": str(artifact_path),
            "actual_send": False,
            "actual_approve": False,
        }

    def candidate_dedup_key(
        self,
        *,
        semantic_subject: str,
        candidate_kind: str,
        source_refs: list[str],
    ) -> dict[str, Any]:
        subject = _safe_token(semantic_subject)
        kind = _safe_token(candidate_kind)
        canonical_refs = sorted({str(ref).strip() for ref in source_refs if str(ref).strip()})
        digest = hashlib.sha256(
            json.dumps(
                {
                    "semantic_subject": subject,
                    "candidate_kind": kind,
                    "source_refs": canonical_refs,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "semantic_subject": subject,
            "candidate_kind": kind,
            "canonical_source_refs": canonical_refs,
            "dedup_key": f"digest_dedup_{digest}",
        }


def _daily_groups(events: list[EventEnvelope], *, max_events_per_group: int) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], list[EventEnvelope]] = defaultdict(list)
    for event in events:
        by_key[(_source_class(event), event.kind)].append(event)
    groups: list[dict[str, Any]] = []
    for (source_class, event_kind), group_events in sorted(by_key.items()):
        sorted_events = sorted(group_events, key=lambda event: (event.ts, event.id))
        selected = sorted_events[:max_events_per_group]
        groups.append(
            {
                "source_class": source_class,
                "event_kind": event_kind,
                "selected_count": len(selected),
                "dropped_count": max(0, len(sorted_events) - len(selected)),
                "selected_refs": [_event_ref(event) for event in selected],
                "summaries": [event.summary for event in selected],
                "candidate_allowed": _candidate_allowed(source_class),
                "earliest_ts": sorted_events[0].ts,
                "latest_ts": sorted_events[-1].ts,
            }
        )
    return groups


def _late_arrival_group(events: list[EventEnvelope], *, max_events_per_group: int, tz: ZoneInfo) -> dict[str, Any]:
    sorted_events = sorted(events, key=lambda event: (event.ts, event.id))
    selected = sorted_events[:max_events_per_group]
    original_dates = sorted({_event_local_date(event, tz).isoformat() for event in sorted_events})
    return {
        "source_class": "late_arrival",
        "event_kind": "various",
        "selected_count": len(selected),
        "dropped_count": max(0, len(sorted_events) - len(selected)),
        "selected_refs": [_event_ref(event) for event in selected],
        "summaries": [event.summary for event in selected],
        "original_dates": original_dates,
        "late_arrival_count": len(sorted_events),
        "candidate_allowed": False,
    }


def _is_late_arrival_for_date(event: EventEnvelope, target_date: date, tz: ZoneInfo) -> bool:
    arrived_at = event.safe_ref.get("arrived_at")
    if not arrived_at:
        return False
    try:
        arrived_date = datetime.fromisoformat(str(arrived_at)).astimezone(tz).date()
    except ValueError:
        return False
    return arrived_date == target_date and _event_local_date(event, tz) < target_date


def _event_local_date(event: EventEnvelope, tz: ZoneInfo) -> date:
    return datetime.fromisoformat(event.ts).astimezone(tz).date()


def _source_class(event: EventEnvelope) -> str:
    value = event.safe_ref.get("source_class") or event.safe_ref.get("source_module") or event.source
    return str(value or "unknown")


def _event_ref(event: EventEnvelope) -> str:
    return f"event:{event.id}"


def _candidate_allowed(source_class: str) -> bool:
    return source_class in {"foreground", "memory_write", "mirrored_conversation", "tool_failure"}


def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def _count_json_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.glob("*.json"))


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _json_artifact_matches(path: Path, data: dict[str, Any]) -> bool:
    if not path.exists():
        return False
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return existing == data


def _safe_token(value: str) -> str:
    token = str(value).strip().lower().replace(" ", "_")
    return "".join(character for character in token if character.isalnum() or character in {"_", "-", ":"})


def _iso_week_window(target_week: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    year_text, _, week_text = target_week.partition("-W")
    if not year_text or not week_text:
        raise ValueError(f"Invalid ISO week: {target_week}")
    monday = date.fromisocalendar(int(year_text), int(week_text), 1)
    start = datetime.combine(monday, time.min, tzinfo=tz)
    end = datetime.combine(monday + timedelta(days=6), time.max, tzinfo=tz)
    return start, end


def _event_in_window(event: EventEnvelope, start: datetime, end: datetime, tz: ZoneInfo) -> bool:
    event_time = datetime.fromisoformat(event.ts).astimezone(tz)
    return start <= event_time <= end


def _daily_refs_for_week(daily_root: Path, week_start: date) -> list[str]:
    refs: list[str] = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        path = daily_root / f"{day.isoformat()}.json"
        if path.exists():
            refs.append(f"daily:{day.isoformat()}")
    return refs


def _weekly_candidate_groups(events: list[EventEnvelope], module: DigestConsolidationModule) -> list[dict[str, Any]]:
    by_subject: dict[str, list[EventEnvelope]] = defaultdict(list)
    for event in events:
        source_class = _source_class(event)
        if not _candidate_allowed(source_class):
            continue
        by_subject[_semantic_subject(event)].append(event)
    candidates: list[dict[str, Any]] = []
    for subject, subject_events in by_subject.items():
        ordered_events = sorted(subject_events, key=lambda event: (event.ts, event.id))
        source_refs = [_event_ref(event) for event in ordered_events]
        dedup = module.candidate_dedup_key(
            semantic_subject=subject,
            candidate_kind="weekly_consolidation",
            source_refs=source_refs,
        )
        candidates.append(
            {
                "semantic_subject": dedup["semantic_subject"],
                "candidate_kind": "weekly_consolidation",
                "dedup_key": dedup["dedup_key"],
                "source_refs": dedup["canonical_source_refs"],
                "source_class_counts": _source_class_counts(ordered_events),
                "title": f"Weekly consolidation: {dedup['semantic_subject']}",
                "summary": _bounded_summary(ordered_events),
                "first_ts": ordered_events[0].ts,
                "latest_ts": ordered_events[-1].ts,
                "crystallized_approved": False,
            }
        )
    return sorted(candidates, key=lambda item: (item["first_ts"], item["semantic_subject"]))


def _semantic_subject(event: EventEnvelope) -> str:
    explicit = event.safe_ref.get("semantic_subject")
    if explicit:
        return _safe_token(str(explicit))
    return _safe_token(f"{_source_class(event)}_{event.kind}")


def _source_class_counts(events: list[EventEnvelope]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        source_class = _source_class(event)
        counts[source_class] = counts.get(source_class, 0) + 1
    return dict(sorted(counts.items()))


def _bounded_summary(events: list[EventEnvelope]) -> str:
    summaries = [event.summary for event in events[:3]]
    suffix = "" if len(events) <= 3 else f" (+{len(events) - 3} more refs)"
    return " / ".join(summaries) + suffix


def _upsert_proposal_candidate(*, proposal_queue: Any, store: MemoryOSStore, candidate: dict[str, Any]) -> None:
    queue = proposal_queue.read_queue()
    active_states = {"candidate", "owner_defer", "owner_eligible", "approved_for_proposal"}
    for item in queue.get("items", []):
        same_subject = item.get("semantic_subject") == candidate["semantic_subject"]
        same_kind = item.get("kind") == "weekly_consolidation"
        active = str(item.get("state", "")) in active_states
        if not (same_subject and same_kind and active):
            continue
        old_refs = set(str(ref) for ref in item.get("source_refs", []))
        new_refs = sorted(old_refs.union(candidate["source_refs"]))
        if new_refs != item.get("source_refs", []):
            item["source_refs"] = new_refs
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            item.setdefault("dedup_history", []).append(
                {
                    "action": "candidate_updated_via_overlap",
                    "dedup_key": candidate["dedup_key"],
                    "source_ref_count": len(new_refs),
                }
            )
            proposal_queue._write_queue(queue)
            append_audit(
                store.roots.audit_path,
                action="candidate_updated_via_overlap",
                status="ok",
                target=str(proposal_queue.queue_path),
                details={
                    "candidate_id": item.get("candidate_id", ""),
                    "semantic_subject": candidate["semantic_subject"],
                    "source_ref_count": len(new_refs),
                },
            )
        return

    created = proposal_queue.create_candidate(
        store=store,
        title=str(candidate["title"]),
        body=str(candidate["summary"]),
        source_refs=list(candidate["source_refs"]),
        kind="weekly_consolidation",
        source_module="digest_consolidation",
    )
    queue = proposal_queue.read_queue()
    for item in queue.get("items", []):
        if item.get("candidate_id") != created.get("candidate_id"):
            continue
        item["semantic_subject"] = candidate["semantic_subject"]
        item["dedup_key"] = candidate["dedup_key"]
        item["dedup_history"] = [
            {
                "action": "candidate_created",
                "dedup_key": candidate["dedup_key"],
                "source_ref_count": len(candidate["source_refs"]),
            }
        ]
        item["source_class_counts"] = candidate["source_class_counts"]
        proposal_queue._write_queue(queue)
        return


def _weekly_proposal_queue_synced(*, proposal_queue: Any, candidates: list[dict[str, Any]]) -> bool:
    queue = proposal_queue.read_queue()
    active_states = {"candidate", "owner_defer", "owner_eligible", "approved_for_proposal"}
    items = [item for item in queue.get("items", []) if isinstance(item, dict)]
    for candidate in candidates:
        candidate_refs = {str(ref) for ref in candidate.get("source_refs", [])}
        found = False
        for item in items:
            same_subject = item.get("semantic_subject") == candidate["semantic_subject"]
            same_kind = item.get("kind") == "weekly_consolidation"
            active = str(item.get("state", "")) in active_states
            item_refs = {str(ref) for ref in item.get("source_refs", [])}
            if same_subject and same_kind and active and candidate_refs.issubset(item_refs):
                found = True
                break
        if not found:
            return False
    return True
