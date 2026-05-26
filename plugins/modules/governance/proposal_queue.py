"""Profile-local Proposal Queue module for portable Hermes governance."""

from __future__ import annotations

import json
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.store import MemoryOSStore


TRANSITIONS = {
    "defer": "owner_defer",
    "reject": "owner_declined",
    "approve": "approved_for_proposal",
}


def proposal_queue_manifest() -> dict[str, Any]:
    """Return the v0.1 Proposal Queue module manifest."""

    return {
        "name": "proposal_queue",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["ops_gate", "evidence_scoring"],
        },
        "provides": {
            "commands": ["status", "doctor", "create", "transition", "import-legacy"],
            "schedules": [],
            "reads": ["memory_os.events.summary", "memory_os.crystallized_candidates"],
            "writes": ["memory_os.audit", "local_artifact.proposal_queue_state"],
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


class ProposalQueueModule:
    """Maintain local proposal candidates without granting crystallized approval."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "proposal_queue"

    @property
    def queue_path(self) -> Path:
        return self.module_root / "queue.json"

    def create_candidate(
        self,
        *,
        store: MemoryOSStore,
        title: str,
        body: str,
        source_refs: list[str] | None = None,
        kind: str = "proposal",
        proposal_class: str = "",
        dedupe_key: str = "",
        proposal_quality: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _timestamp()
        candidate = {
            "schema_version": "hermes.proposal_candidate.v0",
            "candidate_id": _new_candidate_id(),
            "profile": self.profile,
            "kind": kind,
            "title": str(title),
            "body": str(body),
            "source_refs": list(source_refs or []),
            "state": "candidate",
            "legacy_state": "",
            "approval_purpose": "proposal_queue_only",
            "crystallized_approved": False,
            "created_at": now,
            "updated_at": now,
            "followup_state": "none",
            "execution_decision_state": "not_requested",
            "execution_ticket_count": 0,
            "actual_execute": False,
            "reviews": [],
        }
        if proposal_class:
            candidate["proposal_class"] = _bounded_token(proposal_class, 96)
        if dedupe_key:
            candidate["dedupe_key"] = _bounded_token(dedupe_key, 160)
        if proposal_quality:
            candidate["proposal_quality"] = _bounded_proposal_quality(proposal_quality)
        queue = self.read_queue()
        queue["items"].append(candidate)
        self._write_queue(queue)
        self._audit(store, "proposal_queue_candidate_created", "ok", candidate)
        return candidate

    def import_legacy_candidate(
        self,
        *,
        store: MemoryOSStore,
        legacy_record: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        legacy_import_key = _legacy_import_key(legacy_record, source)
        legacy_id = str(legacy_record.get("id", "")).strip()
        queue = self.read_queue()
        for item in queue["items"]:
            same_key = item.get("legacy_import_key") == legacy_import_key
            same_id = bool(legacy_id) and item.get("candidate_id") == legacy_id
            if same_key or same_id:
                existing = dict(item)
                self._audit(store, "proposal_queue_legacy_candidate_import_skipped", "ok", existing)
                return existing

        legacy_state = str(legacy_record.get("status", legacy_record.get("state", "")) or "candidate")
        candidate = {
            "schema_version": "hermes.proposal_candidate.v0",
            "candidate_id": legacy_id or f"legacy_{_stable_digest(legacy_import_key)}",
            "profile": self.profile,
            "kind": "legacy_owner_review",
            "title": str(legacy_record.get("title", legacy_record.get("text", ""))),
            "body": str(legacy_record.get("body", legacy_record.get("text", ""))),
            "source_refs": [str(source)],
            "legacy_import_key": legacy_import_key,
            "state": _map_legacy_state(legacy_state),
            "legacy_state": legacy_state,
            "approval_purpose": "legacy_owner_review_visibility",
            "crystallized_approved": False,
            "created_at": _timestamp(),
            "updated_at": _timestamp(),
            "followup_state": _initial_followup_state(_map_legacy_state(legacy_state)),
            "execution_decision_state": "not_requested",
            "execution_ticket_count": 0,
            "actual_execute": False,
            "reviews": [],
        }
        queue["items"].append(candidate)
        self._write_queue(queue)
        self._audit(store, "proposal_queue_legacy_candidate_imported", "ok", candidate)
        return candidate

    def transition(
        self,
        *,
        store: MemoryOSStore,
        candidate_id: str,
        decision: str,
        reviewer: str,
        note: str = "",
    ) -> dict[str, Any]:
        if decision not in TRANSITIONS:
            raise ValueError(f"Unsupported proposal decision: {decision}")
        queue = self.read_queue()
        for item in queue["items"]:
            if item.get("candidate_id") != candidate_id:
                continue
            item["state"] = TRANSITIONS[decision]
            item["approval_purpose"] = "proposal_queue_only"
            item["crystallized_approved"] = False
            item["updated_at"] = _timestamp()
            item.setdefault("execution_decision_state", "not_requested")
            item.setdefault("execution_ticket_count", 0)
            item["actual_execute"] = False
            if decision == "approve":
                item["followup_state"] = "awaiting_ops_gate"
            elif decision == "reject":
                item["followup_state"] = "closed"
            else:
                item["followup_state"] = "deferred"
            item.setdefault("reviews", []).append(
                {
                    "reviewer": reviewer,
                    "decision": decision,
                    "note": note,
                    "reviewed_at": item["updated_at"],
                }
            )
            self._write_queue(queue)
            self._audit(store, "proposal_queue_candidate_transitioned", "ok", item)
            return dict(item)
        raise KeyError(f"Proposal candidate not found: {candidate_id}")

    def read_queue(self) -> dict[str, Any]:
        if not self.queue_path.exists():
            return {
                "schema_version": "hermes.proposal_queue.v0",
                "profile": self.profile,
                "items": [],
            }
        parsed = json.loads(self.queue_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            return {"schema_version": "hermes.proposal_queue.v0", "profile": self.profile, "items": []}
        parsed.setdefault("items", [])
        return parsed

    def status(self) -> dict[str, Any]:
        items = list(self.read_queue().get("items", []))
        state_counts = Counter(str(item.get("state", "")) for item in items)
        followup_counts = Counter(str(item.get("followup_state", "none")) for item in items)
        execution_ticket_count = sum(int(item.get("execution_ticket_count") or 0) for item in items)
        return {
            "schema_version": "hermes.proposal_queue_status.v0",
            "module": "proposal_queue",
            "profile": self.profile,
            "candidate_count": len(items),
            "state_counts": dict(sorted(state_counts.items())),
            "followup_state_counts": dict(sorted(followup_counts.items())),
            "execution_ticket_count": execution_ticket_count,
            "actual_execute": any(bool(item.get("actual_execute", False)) for item in items),
            "queue_path": str(self.queue_path),
            "delivery_mode": "no-send",
            "crystallized_approval_granted": False,
        }

    def doctor(self) -> dict[str, Any]:
        status = self.status()
        findings: list[dict[str, Any]] = []
        pending_count = int(status["state_counts"].get("candidate", 0)) + int(status["state_counts"].get("owner_eligible", 0))
        if pending_count:
            findings.append(
                {
                    "severity": "warning",
                    "code": "pending_candidates_present",
                    "message": f"{pending_count} proposal candidate(s) are pending review",
                }
            )
        return {
            "schema_version": "hermes.proposal_queue_doctor.v0",
            "module": "proposal_queue",
            "profile": self.profile,
            "status": "warning" if findings else "ok",
            "findings": findings,
        }

    def _write_queue(self, queue: dict[str, Any]) -> None:
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue["schema_version"] = "hermes.proposal_queue.v0"
        queue["profile"] = self.profile
        self.queue_path.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _audit(self, store: MemoryOSStore, action: str, status: str, candidate: dict[str, Any]) -> None:
        append_audit(
            store.roots.audit_path,
            action=action,
            status=status,
            target=str(self.queue_path),
            details={
                "candidate_id": candidate.get("candidate_id", ""),
                "state": candidate.get("state", ""),
                "approval_purpose": candidate.get("approval_purpose", ""),
                "crystallized_approved": bool(candidate.get("crystallized_approved", False)),
            },
        )


def _map_legacy_state(state: str) -> str:
    if state in {"candidate", "owner_eligible", "owner_declined", "owner_defer", "pressure_blocked", "expired"}:
        return state
    return "candidate"


def _initial_followup_state(state: str) -> str:
    if state == "approved_for_proposal":
        return "awaiting_ops_gate"
    if state in {"owner_declined", "expired", "pressure_blocked"}:
        return "closed"
    if state == "owner_defer":
        return "deferred"
    return "none"


def _new_candidate_id() -> str:
    now = datetime.now(timezone.utc)
    return f"prop_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}"


def _legacy_import_key(legacy_record: dict[str, Any], source: str) -> str:
    identity_parts = {
        "source": str(source),
        "id": str(legacy_record.get("id", "")),
        "status": str(legacy_record.get("status", legacy_record.get("state", ""))),
        "title": str(legacy_record.get("title", "")),
        "text": str(legacy_record.get("text", "")),
    }
    return _stable_digest(json.dumps(identity_parts, ensure_ascii=False, sort_keys=True))


def _stable_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_token(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[:limit]


def _bounded_proposal_quality(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "direct_apply_allowed",
        "trigger_rule",
        "feedback_count",
        "feedback_rating",
        "generic_executor_allowed",
        "linked_outcome_count",
        "outcome_refs",
        "policy_versions",
        "quality_gate",
        "request_refs",
        "runtime_target",
        "top_subject_ref",
        "top_subject_kind",
        "maturity_score",
        "evidence_ref_count",
        "maturity_dimensions",
        "unlinked_feedback_count",
    }
    bool_keys = {"direct_apply_allowed", "generic_executor_allowed"}
    int_keys = {"evidence_ref_count", "feedback_count", "linked_outcome_count", "unlinked_feedback_count"}
    list_keys = {"outcome_refs", "request_refs", "policy_versions"}
    result: dict[str, Any] = {}
    for key in allowed:
        if key not in value:
            continue
        item = value[key]
        if key == "maturity_dimensions" and isinstance(item, dict):
            result[key] = item
        elif key == "maturity_score":
            try:
                result[key] = round(float(item), 3)
            except (TypeError, ValueError):
                continue
        elif key in int_keys:
            try:
                result[key] = max(int(item), 0)
            except (TypeError, ValueError):
                continue
        elif key in bool_keys:
            result[key] = bool(item)
        elif key in list_keys and isinstance(item, list):
            result[key] = [_bounded_token(str(entry), 96) for entry in item[:5] if str(entry)]
        else:
            result[key] = _bounded_token(str(item), 240)
    return result
