"""Profile-local Proposal Queue module for portable Hermes governance."""

from __future__ import annotations

import json
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
    ) -> dict[str, Any]:
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
            "created_at": _timestamp(),
            "updated_at": _timestamp(),
            "reviews": [],
        }
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
        legacy_state = str(legacy_record.get("status", legacy_record.get("state", "")) or "candidate")
        candidate = {
            "schema_version": "hermes.proposal_candidate.v0",
            "candidate_id": str(legacy_record.get("id", _new_candidate_id())),
            "profile": self.profile,
            "kind": "legacy_owner_review",
            "title": str(legacy_record.get("title", legacy_record.get("text", ""))),
            "body": str(legacy_record.get("body", legacy_record.get("text", ""))),
            "source_refs": [str(source)],
            "state": _map_legacy_state(legacy_state),
            "legacy_state": legacy_state,
            "approval_purpose": "legacy_owner_review_visibility",
            "crystallized_approved": False,
            "created_at": _timestamp(),
            "updated_at": _timestamp(),
            "reviews": [],
        }
        queue = self.read_queue()
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
        return {
            "schema_version": "hermes.proposal_queue_status.v0",
            "module": "proposal_queue",
            "profile": self.profile,
            "candidate_count": len(items),
            "state_counts": dict(sorted(state_counts.items())),
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


def _new_candidate_id() -> str:
    now = datetime.now(timezone.utc)
    return f"prop_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
