"""Summary-only Governance Feedback Bridge for portable Hermes modules."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.memory_sources import memory_sources_feedback_path
from plugins.memory.memory_os.owner_actions import expression_feedback_ledger_path
from plugins.modules.expression.speak_gate import SpeakGateModule
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


GOVERNANCE_EVENT_KINDS = {
    "governance_evidence_scored",
    "governance_ops_gate_decision",
    "governance_proposal_created",
    "governance_proposal_transitioned",
    "governance_expression_feedback",
    "governance_memory_sources_feedback",
    "governance_self_evolution_reported",
    "governance_speak_gate_delivery",
}


def governance_feedback_manifest() -> dict[str, Any]:
    """Return the v0.1 Governance Feedback Bridge manifest."""

    return {
        "name": "governance_feedback",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["evidence_scoring", "ops_gate", "proposal_queue", "self_evolution", "speak_gate"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["governance_feedback_bridge"],
            "reads": [
                "local_artifact.evidence_scoring",
                "local_artifact.ops_gate_report",
                "local_artifact.proposal_queue_state",
                "memory_os.expression_feedback_ledger",
                "memory_os.memory_sources_feedback",
                "local_artifact.self_evolution_report",
                "local_artifact.speak_gate_deliveries",
            ],
            "writes": ["memory_os.events.summary", "memory_os.audit", "local_artifact.governance_feedback_state"],
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


class GovernanceFeedbackBridgeModule:
    """Mirror governance artifact summaries back into Memory-OS events."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "governance_feedback"

    @property
    def state_path(self) -> Path:
        return self.module_root / "state.json"

    def status(self) -> dict[str, Any]:
        state = self.read_state()
        records = state.get("records", [])
        counters = state.get("counters") if isinstance(state.get("counters"), dict) else {}
        return {
            "schema_version": "hermes.governance_feedback_status.v0",
            "module": "governance_feedback",
            "profile": self.profile,
            "emitted_event_count": len(records) if isinstance(records, list) else 0,
            "generated_count": int(counters.get("generated_count") or 0),
            "skipped_count": int(counters.get("skipped_count") or 0),
            "latest_run_status": str(state.get("latest_run_status") or "missing"),
            "latest_skip_reason": str(state.get("latest_skip_reason") or ""),
            "state_path": str(self.state_path),
            "delivery_mode": "no-send",
            "actual_send": False,
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        state = self.read_state()
        if not isinstance(state.get("records", []), list):
            findings.append(
                {
                    "severity": "error",
                    "code": "state_records_not_list",
                    "message": "Governance feedback state records must be a list",
                }
            )
        return {
            "schema_version": "hermes.governance_feedback_doctor.v0",
            "module": "governance_feedback",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }

    def run_once(
        self,
        *,
        store: MemoryOSStore,
        dry_run: bool = True,
        evidence: Any | None = None,
        ops_gate: Any | None = None,
        proposal_queue: Any | None = None,
        governor: Any | None = None,
        self_evolution: Any | None = None,
    ) -> dict[str, Any]:
        store.initialize()
        events = self._collect_events(
            evidence=evidence,
            ops_gate=ops_gate,
            proposal_queue=proposal_queue,
            self_evolution=self_evolution or governor,
        )
        existing_keys = self._existing_keys(store)
        state = self.read_state()
        state_records = list(state.get("records", [])) if isinstance(state.get("records", []), list) else []
        state_keys = {str(record.get("idempotency_key", "")) for record in state_records}
        emitted_keys = {key for key in state_keys | existing_keys if key}
        pending = [event for event in events if str(event.safe_ref.get("governance_feedback_key", "")) not in emitted_keys]

        if not dry_run:
            if pending:
                for event in pending:
                    store.append_event(event)
                    state_records.append(_state_record(event))
                self._write_state(
                    state_records,
                    latest_run_status="ok",
                    latest_skip_reason="",
                    generated_delta=1,
                    skipped_delta=0,
                )
            else:
                self._write_state(
                    state_records,
                    latest_run_status="skipped",
                    latest_skip_reason="no_new_governance_feedback_events",
                    generated_delta=0,
                    skipped_delta=1,
                )
            append_audit(
                store.roots.audit_path,
                action="governance_feedback_events_written" if pending else "governance_feedback_skipped",
                status="ok",
                target=str(self.state_path),
                details={
                    "profile": self.profile,
                    "written_event_count": len(pending),
                    "already_emitted_count": len(events) - len(pending),
                    "actual_send": False,
                    "actual_execute": False,
                },
            )

        result = {
            "schema_version": "hermes.governance_feedback_result.v0",
            "module": "governance_feedback",
            "profile": self.profile,
            "status": "ok" if (dry_run or pending) else "skipped",
            "dry_run": dry_run,
            "would_write_event_count": len(pending),
            "written_event_count": 0 if dry_run else len(pending),
            "already_emitted_count": len(events) - len(pending),
            "source_event_count": len(events),
            "event_kinds": dict(sorted(_kind_counts(events).items())),
            "actual_send": False,
            "actual_execute": False,
        }
        if not dry_run and not pending:
            result.update(
                {
                    "skipped": True,
                    "cadence_skipped": True,
                    "reason": "no_new_governance_feedback_events",
                }
            )
        return result

    def read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "schema_version": "hermes.governance_feedback_state.v0",
                "profile": self.profile,
                "records": [],
            }
        parsed = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            return {
                "schema_version": "hermes.governance_feedback_state.v0",
                "profile": self.profile,
                "records": [],
            }
        parsed.setdefault("records", [])
        parsed.setdefault("counters", {"generated_count": 0, "skipped_count": 0})
        return parsed

    def _collect_events(
        self,
        *,
        evidence: Any | None,
        ops_gate: Any | None,
        proposal_queue: Any | None,
        self_evolution: Any | None,
    ) -> list[EventEnvelope]:
        records: list[dict[str, Any]] = []
        if evidence is not None:
            records.extend(self._evidence_events(evidence))
        if ops_gate is not None:
            records.extend(self._ops_gate_events(ops_gate))
        if proposal_queue is not None:
            records.extend(self._proposal_events(proposal_queue))
        records.extend(self._memory_sources_feedback_events())
        records.extend(self._expression_feedback_events())
        records.extend(self._speak_gate_events())
        if self_evolution is not None:
            records.extend(self._self_evolution_events(self_evolution))
        return [self._to_event(record) for record in records]

    def _evidence_events(self, evidence: Any) -> list[dict[str, Any]]:
        scores = [score for score in evidence.read_scores() if str(score.get("profile", self.profile)) == self.profile]
        if not scores:
            return []
        subject_counts: dict[str, int] = {}
        for score in scores:
            subject_kind = str(score.get("subject_kind", "unknown"))
            subject_counts[subject_kind] = subject_counts.get(subject_kind, 0) + 1
        top = max(scores, key=lambda item: float(item.get("score", 0.0)))
        source_hash = _hash_json(
            [
                {
                    "score_id": score.get("score_id", ""),
                    "subject_ref": score.get("subject_ref", ""),
                    "score": score.get("score", 0.0),
                    "evidence_refs": score.get("evidence_refs", []),
                }
                for score in sorted(scores, key=lambda item: str(item.get("score_id", "")))
            ]
        )
        return [
            {
                "kind": "governance_evidence_scored",
                "source_module": "evidence_scoring",
                "source_key": "evidence_scoring:scores",
                "state_hash": source_hash,
                "artifact_ref": "local://evidence_scoring/scores",
                "summary": (
                    f"Evidence/Scoring recorded {len(scores)} score(s) across "
                    f"{', '.join(f'{key}={value}' for key, value in sorted(subject_counts.items()))}; "
                    f"top score {top.get('score')} for {top.get('subject_ref')}."
                ),
                "evidence_refs": [f"score:{score.get('score_id', '')}" for score in scores[:8]],
            }
        ]

    def _ops_gate_events(self, ops_gate: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for index, report in enumerate(ops_gate.read_reports()):
            if str(report.get("profile", self.profile)) != self.profile:
                continue
            decisions = list(report.get("decisions", [])) if isinstance(report.get("decisions", []), list) else []
            blocked = sum(1 for decision in decisions if decision.get("decision") == "blocked")
            kinds = sorted({str(decision.get("kind", "unknown")) for decision in decisions if decision.get("kind")})
            report_id = str(report.get("report_id") or f"report_{index}")
            records.append(
                {
                    "kind": "governance_ops_gate_decision",
                    "source_module": "ops_gate",
                    "source_key": f"ops_gate:report:{report_id}",
                    "state_hash": _hash_json(report),
                    "artifact_ref": f"local://ops_gate/reports/{report_id}",
                    "summary": (
                        f"Ops-Gate report {report_id} status={report.get('status', 'unknown')}; "
                        f"decisions={len(decisions)}, blocked={blocked}, kinds={','.join(kinds) or 'none'}."
                    ),
                    "evidence_refs": [f"ops_gate:{report_id}"],
                    "source_class": "self_activity",
                    "subtype": "execution",
                }
            )
        return records

    def _proposal_events(self, proposal_queue: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in proposal_queue.read_queue().get("items", []):
            if str(item.get("profile", self.profile)) != self.profile:
                continue
            candidate_id = str(item.get("candidate_id", ""))
            state = str(item.get("state", "candidate"))
            kind = "governance_proposal_created" if state == "candidate" else "governance_proposal_transitioned"
            title = _clip(str(item.get("title", "")), 120)
            records.append(
                {
                    "kind": kind,
                    "source_module": "proposal_queue",
                    "source_key": f"proposal_queue:candidate:{candidate_id}:{state}",
                    "state_hash": _hash_json(
                        {
                            "candidate_id": candidate_id,
                            "state": state,
                            "updated_at": item.get("updated_at", ""),
                            "source_refs": item.get("source_refs", []),
                        }
                    ),
                    "artifact_ref": f"local://proposal_queue/candidates/{candidate_id}",
                    "summary": f"Proposal Queue candidate {candidate_id} is {state}: {title}",
                    "evidence_refs": [str(ref) for ref in item.get("source_refs", [])[:8]],
                    "proposal_id": candidate_id,
                    "proposal_state": state,
                }
            )
        return records

    def _expression_feedback_events(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        roots = MemoryOSRoots.from_hermes_home(self.hermes_home, profile=self.profile)
        for feedback in _read_jsonl(expression_feedback_ledger_path(roots)):
            if str(feedback.get("profile", self.profile)) != self.profile:
                continue
            if not str(feedback.get("schema_version", "")).endswith("expression_feedback.v0"):
                continue
            feedback_id = str(feedback.get("feedback_id", ""))
            draft_id = str(feedback.get("draft_id", ""))
            action_type = str(feedback.get("action_type", "unknown"))
            state_hash = _hash_json(
                {
                    "feedback_id": feedback_id,
                    "draft_id": draft_id,
                    "action_type": action_type,
                    "live_policy_changed": bool(feedback.get("live_policy_changed", False)),
                }
            )
            records.append(
                {
                    "kind": "governance_expression_feedback",
                    "source_module": "expression_feedback",
                    "source_key": f"expression_feedback:{feedback_id}:{action_type}",
                    "state_hash": state_hash,
                    "artifact_ref": f"local://expression_feedback/{feedback_id}",
                    "summary": (
                        f"Expression feedback {action_type} recorded for {draft_id}; "
                        "live_policy_changed=false."
                    ),
                    "evidence_refs": [f"expression_feedback:{feedback_id}"],
                    "expression_feedback_id": feedback_id,
                    "expression_draft_id": draft_id,
                    "expression_feedback_type": action_type,
                }
            )
        return records

    def _speak_gate_events(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        # NOTE: read_delivery_records() reads the entire deliveries.jsonl on every
        # cadence tick — same unbounded-read pattern as _expression_feedback_events()
        # and _memory_sources_feedback_events(). A cursor-based incremental read
        # should be added to all three if file growth becomes a performance concern.
        gate = SpeakGateModule(hermes_home=self.hermes_home, profile=self.profile)
        for delivery in gate.read_delivery_records():
            if str(delivery.get("profile", self.profile)) != self.profile:
                continue
            if not str(delivery.get("schema_version", "")).endswith("speak_gate_delivery.v0"):
                continue
            delivery_id = str(delivery.get("id", ""))
            delivery_source_module = str(delivery.get("source_module", "unknown"))
            channel = str(delivery.get("channel", "unknown"))
            state_hash = _hash_json(
                {
                    "delivery_id": delivery_id,
                    "source_module": delivery_source_module,
                    "channel": channel,
                    "actual_send": bool(delivery.get("actual_send", False)),
                }
            )
            records.append(
                {
                    "kind": "governance_speak_gate_delivery",
                    "source_module": "speak_gate",
                    "source_key": f"speak_gate:delivery:{delivery_id}",
                    "state_hash": state_hash,
                    "artifact_ref": f"local://speak_gate/deliveries/{delivery_id}",
                    "summary": (
                        f"Speak Gate delivered via {delivery_source_module} to {channel}: "
                        f"{_clip(str(delivery.get('payload_ref', '')), 120)}"
                    ),
                    "evidence_refs": [f"speak_gate_delivery:{delivery_id}"],
                    "speak_gate_delivery_id": delivery_id,
                    "speak_gate_source_module": delivery_source_module,
                    "speak_gate_delivery_channel": channel,
                    "source_class": "self_activity",
                    "subtype": "speech",
                }
            )
        return records

    def _memory_sources_feedback_events(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        roots = MemoryOSRoots.from_hermes_home(self.hermes_home, profile=self.profile)
        for feedback in _read_jsonl(memory_sources_feedback_path(roots)):
            if str(feedback.get("profile", self.profile)) != self.profile:
                continue
            if not str(feedback.get("schema_version", "")).endswith("memory_sources_feedback.v0"):
                continue
            feedback_id = str(feedback.get("feedback_id", ""))
            source_record_id = str(feedback.get("memory_source_record_id", ""))
            rating = str(feedback.get("rating", "unknown"))
            route = str(feedback.get("route", "unknown"))
            query_class = str(feedback.get("query_class", "unknown"))
            state_hash = _hash_json(
                {
                    "feedback_id": feedback_id,
                    "memory_source_record_id": source_record_id,
                    "rating": rating,
                    "route": route,
                    "query_class": query_class,
                }
            )
            records.append(
                {
                    "kind": "governance_memory_sources_feedback",
                    "source_module": "memory_sources_feedback",
                    "source_key": f"memory_sources_feedback:{feedback_id}:{rating}",
                    "state_hash": state_hash,
                    "artifact_ref": f"local://memory_sources_feedback/{feedback_id}",
                    "summary": (
                        f"MemorySources feedback {rating} recorded for route={route}; "
                        "live_route_changed=false."
                    ),
                    "evidence_refs": [f"memory_sources_feedback:{feedback_id}"],
                    "memory_sources_feedback_id": feedback_id,
                    "memory_source_record_id": source_record_id,
                    "memory_sources_feedback_rating": rating,
                    "memory_sources_feedback_route": route,
                    "memory_sources_feedback_query_class": query_class,
                }
            )
        return records

    def _self_evolution_events(self, self_evolution: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for index, report in enumerate(self_evolution.read_reports()):
            if str(report.get("profile", self.profile)) != self.profile:
                continue
            if _self_evolution_noop_report(report):
                continue
            proposal_id = str(report.get("proposal_id", ""))
            report_id = proposal_id or _hash_json(report)[:12] or f"report_{index}"
            records.append(
                {
                    "kind": "governance_self_evolution_reported",
                    "source_module": "self_evolution",
                    "source_key": f"self_evolution:report:{report_id}:{index}",
                    "state_hash": _hash_json(report),
                    "artifact_ref": f"local://self_evolution/reports/{report_id}",
                    "summary": (
                        f"Self-Evolution {report.get('execution_mode', 'dry-run')} report status={report.get('status', 'unknown')}; "
                        f"proposal_created={bool(report.get('proposal_created', False))}; "
                        f"score_refs={len(report.get('score_refs', []))}; direct_self_modify=false."
                    ),
                    "evidence_refs": [str(ref) for ref in report.get("score_refs", [])[:8]],
                    "proposal_id": proposal_id,
                }
            )
        return records

    def _to_event(self, record: dict[str, Any]) -> EventEnvelope:
        key = _idempotency_key(record)
        event_id = f"evt_gov_{_stable_digest(key)[:20]}"
        source_class = str(record.get("source_class") or "governance")
        subtype = record.get("subtype")
        safe_ref: dict[str, Any] = {
            "source_class": source_class,
            "source_module": str(record["source_module"]),
            "artifact_ref": str(record["artifact_ref"]),
            "governance_feedback_key": key,
            "source_key": str(record["source_key"]),
            "state_hash": str(record["state_hash"]),
            "drive_policy": "evidence_only",
            "candidate_allowed": False,
            "body_policy": "summary_only",
            "evidence_refs": list(record.get("evidence_refs", [])),
            **_optional_refs(record),
        }
        if subtype:
            safe_ref["self_activity_subtype"] = str(subtype)
        return EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id=event_id,
            ts=_timestamp(),
            profile=self.profile,
            source="governance_feedback",
            kind=str(record["kind"]),
            summary=_clip(str(record["summary"]), 260),
            safe_ref=safe_ref,
            tags=["governance", str(record["source_module"]), "summary_only"],
            sensitivity="private",
            body_policy="summary_only",
            hashes={"source_hash": str(record["state_hash"])},
            promotion_state="raw",
        )

    def _existing_keys(self, store: MemoryOSStore) -> set[str]:
        keys: set[str] = set()
        for event in store.read_events():
            if event.profile != self.profile:
                continue
            key = str((event.safe_ref or {}).get("governance_feedback_key", ""))
            if key:
                keys.add(key)
        return keys

    def _write_state(
        self,
        records: list[dict[str, Any]],
        *,
        latest_run_status: str,
        latest_skip_reason: str,
        generated_delta: int,
        skipped_delta: int,
    ) -> None:
        state = self.read_state()
        counters = state.get("counters") if isinstance(state.get("counters"), dict) else {}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": "hermes.governance_feedback_state.v0",
            "profile": self.profile,
            "records": records,
            "latest_run_at": _timestamp(),
            "latest_run_status": latest_run_status,
            "latest_skip_reason": latest_skip_reason,
            "counters": {
                "generated_count": int(counters.get("generated_count") or 0) + generated_delta,
                "skipped_count": int(counters.get("skipped_count") or 0) + skipped_delta,
            },
        }
        self.state_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _state_record(event: EventEnvelope) -> dict[str, Any]:
    safe_ref = dict(event.safe_ref or {})
    return {
        "event_id": event.id,
        "event_kind": event.kind,
        "idempotency_key": str(safe_ref.get("governance_feedback_key", "")),
        "source_module": str(safe_ref.get("source_module", "")),
        "source_hash": str(safe_ref.get("state_hash", "")),
        "emitted_at": event.ts,
    }


def _optional_refs(record: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key in (
        "proposal_id",
        "proposal_state",
        "expression_feedback_id",
        "expression_draft_id",
        "expression_feedback_type",
        "memory_sources_feedback_id",
        "memory_source_record_id",
        "memory_sources_feedback_rating",
        "memory_sources_feedback_route",
        "memory_sources_feedback_query_class",
        "speak_gate_delivery_id",
        "speak_gate_source_module",
        "speak_gate_delivery_channel",
    ):
        if record.get(key):
            output[key] = record[key]
    return output


def _self_evolution_noop_report(report: dict[str, Any]) -> bool:
    if report.get("proposal_created") is True:
        return False
    reason = str(report.get("reason") or "")
    return (
        report.get("skipped") is True
        or report.get("novelty_skipped") is True
        or report.get("cadence_skipped") is True
        or "duplicate" in reason
    )


def _idempotency_key(record: dict[str, Any]) -> str:
    return _hash_json(
        {
            "kind": record["kind"],
            "source_module": record["source_module"],
            "source_key": record["source_key"],
            "state_hash": record["state_hash"],
        }
    )


def _kind_counts(events: list[EventEnvelope]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        counts[event.kind] = counts.get(event.kind, 0) + 1
    return counts


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _hash_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _stable_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."
