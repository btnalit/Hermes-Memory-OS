"""Retractable owner-label miner for V7 live-shadow governance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit, read_audit_entries
from plugins.memory.memory_os.execution_gate import (
    complete_execution_gate_envelope,
    execution_gate_scope_hash,
    resolve_execution_gate_permit,
)
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.structural_write_gate import append_governed_jsonl


REVERSIBLE_LABELS_LANE_ID = "reversible_labels"
REVERSIBLE_LABELS_RISK_CLASS = "bounded_reversible_label"
REVERSIBLE_LABEL_TTL_DAYS = 90


def reversible_labels_scope(profile: str) -> dict[str, Any]:
    return {
        "profile": str(profile or "default"),
        "label_kind": "owner_approved_candidate",
        "source": "memory_os.audit.owner_action_reply_processed",
        "ttl_days": REVERSIBLE_LABEL_TTL_DAYS,
    }


def ground_truth_miner_manifest() -> dict[str, Any]:
    return {
        "name": "ground_truth_miner",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0"],
            "optional": ["owner_actions", "crystallized_revalidator"],
        },
        "provides": {
            "commands": ["status", "doctor", "mine"],
            "schedules": ["ground_truth_miner_shadow"],
            "reads": ["memory_os.audit"],
            "writes": ["local_artifact.ground_truth_miner"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
    }


class GroundTruthMinerModule:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "ground_truth_miner"

    @property
    def labels_path(self) -> Path:
        return self.module_root / "labels.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def status(self) -> dict[str, Any]:
        labels = self.read_labels(include_expired=True)
        runs = _read_jsonl(self.runs_path)
        counts = _label_state_counts(labels)
        return {
            "schema_version": "hermes.ground_truth_miner_status.v0",
            "module": "ground_truth_miner",
            "profile": self.profile,
            "status": "ok" if labels or runs else "missing",
            "label_count": len(labels),
            "run_count": len(runs),
            "active_label_count": counts["active_label_count"],
            "expired_label_count": counts["expired_label_count"],
            "retracted_label_count": counts["retracted_label_count"],
            "actual_send": False,
            "actual_execute": False,
            "score_live_applied": False,
            "route_live_applied": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        if any(item.get("retractable") is not True for item in self.read_labels()):
            findings.append(
                {
                    "severity": "error",
                    "code": "ground_truth_label_not_retractable",
                    "message": "Owner labels must stay retractable before any scoring/routing flip.",
                }
            )
        return {
            "schema_version": "hermes.ground_truth_miner_doctor.v0",
            "module": "ground_truth_miner",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }

    def run_once(
        self,
        *,
        store: MemoryOSStore,
        execution_envelope_id: str = "",
        expected_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from plugins.memory.memory_os.owner_actions import read_owner_action_records

        audit_entries = read_audit_entries(store.roots.audit_path)
        audit_entries.extend(_audit_entries_from_owner_action_records(read_owner_action_records(store.roots)))
        return self.mine(
            store=store,
            audit_entries=audit_entries,
            execution_envelope_id=execution_envelope_id,
            expected_scope=expected_scope,
        )

    def mine(
        self,
        *,
        store: MemoryOSStore,
        audit_entries: list[dict[str, Any]],
        execution_envelope_id: str = "",
        expected_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        automatic = bool(str(execution_envelope_id or "").strip())
        scope = expected_scope or reversible_labels_scope(self.profile)
        scope_hash = execution_gate_scope_hash(scope)
        resolution: dict[str, Any] = {"status": "not_required", "reason": "manual_or_test_run"}
        if automatic:
            resolution = resolve_execution_gate_permit(
                store.roots,
                envelope_id=execution_envelope_id,
                lane_id=REVERSIBLE_LABELS_LANE_ID,
                risk_class=REVERSIBLE_LABELS_RISK_CLASS,
                require_fresh=True,
                require_unused=True,
                expected_scope_hash=scope_hash,
            )
            if resolution.get("status") != "valid":
                labels = self.read_labels(include_expired=True)
                counts = _label_state_counts(labels)
                return {
                    "schema_version": "hermes.ground_truth_miner_result.v0",
                    "module": "ground_truth_miner",
                    "profile": self.profile,
                    "status": "blocked",
                    "reason": str(resolution.get("reason") or "execution_gate_invalid"),
                    "lane_id": REVERSIBLE_LABELS_LANE_ID,
                    "risk_class": REVERSIBLE_LABELS_RISK_CLASS,
                    "execution_envelope_id": str(execution_envelope_id or ""),
                    "execution_gate_resolution": resolution,
                    "label_count": 0,
                    "total_label_count": len(labels),
                    "active_label_count": counts["active_label_count"],
                    "expired_label_count": counts["expired_label_count"],
                    "retracted_label_count": counts["retracted_label_count"],
                    "actual_send": False,
                    "actual_execute": False,
                    "actual_policy_write": False,
                    "actual_identity_write": False,
                    "actual_relationship_write": False,
                    "actual_route_score_write": False,
                    "hindsight_write": False,
                    "score_live_applied": False,
                    "route_live_applied": False,
                    "boundary": _false_boundary(),
                }
        existing = {str(item.get("label_id") or ""): item for item in self.read_labels(include_expired=True)}
        duplicate_blockers = {
            label_id: item for label_id, item in existing.items() if str(item.get("label_state") or "") != "expired"
        }
        generated = []
        for entry in audit_entries:
            label = self._label_from_audit(entry)
            if not label or label["label_id"] in duplicate_blockers:
                continue
            duplicate_blockers[label["label_id"]] = label
            existing[label["label_id"]] = label
            generated.append(label)
        for label in generated:
            if automatic:
                append_governed_jsonl(
                    store,
                    self.labels_path,
                    label,
                    write_owner="automatic",
                    lane_id=REVERSIBLE_LABELS_LANE_ID,
                    risk_class=REVERSIBLE_LABELS_RISK_CLASS,
                    execution_gate_envelope_id=execution_envelope_id,
                    scope_hash=scope_hash,
                )
            else:
                _append_jsonl(self.labels_path, label)
        labels = [_effective_label(item) for item in existing.values()]
        counts = _label_state_counts(labels)
        result = {
            "schema_version": "hermes.ground_truth_miner_result.v0",
            "module": "ground_truth_miner",
            "profile": self.profile,
            "status": "ok",
            "lane_id": REVERSIBLE_LABELS_LANE_ID,
            "risk_class": REVERSIBLE_LABELS_RISK_CLASS,
            "lane_mode": "limited_auto",
            "execution_envelope_id": str(execution_envelope_id or ""),
            "execution_gate_resolution": resolution,
            "structural_write_gate_bound": automatic,
            "scope_hash": scope_hash,
            "label_count": len(generated),
            "total_label_count": len(labels),
            "active_label_count": counts["active_label_count"],
            "expired_label_count": counts["expired_label_count"],
            "retracted_label_count": counts["retracted_label_count"],
            "actual_send": False,
            "actual_execute": False,
            "actual_policy_write": False,
            "actual_identity_write": False,
            "actual_relationship_write": False,
            "actual_route_score_write": False,
            "hindsight_write": False,
            "score_live_applied": False,
            "route_live_applied": False,
            "boundary": _false_boundary(),
        }
        if automatic:
            append_governed_jsonl(
                store,
                self.runs_path,
                result,
                write_owner="automatic",
                lane_id=REVERSIBLE_LABELS_LANE_ID,
                risk_class=REVERSIBLE_LABELS_RISK_CLASS,
                execution_gate_envelope_id=execution_envelope_id,
                scope_hash=scope_hash,
            )
            complete_execution_gate_envelope(
                store,
                envelope_id=execution_envelope_id,
                lane_id=REVERSIBLE_LABELS_LANE_ID,
                execution_status="ok",
                postcheck={"boundary": _false_boundary(), "label_count": len(generated)},
                result_summary={"label_count": len(generated), "total_label_count": len(labels)},
            )
        else:
            _append_jsonl(self.runs_path, result)
        append_audit(
            store.roots.audit_path,
            action="ground_truth_labels_mined",
            status="ok",
            target=str(self.labels_path),
            details={
                "label_count": len(generated),
                "actual_execute": False,
            },
        )
        return result

    def retract_label(self, label_id: str, *, reason: str) -> dict[str, Any]:
        labels = self.read_labels(include_expired=True)
        current = next((label for label in labels if str(label.get("label_id") or "") == label_id), None)
        found = current is not None
        if current:
            retracted = {
                **current,
                "label_state": "retracted",
                "retraction_reason": reason,
                "retracted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "score_live_applied": False,
                "route_live_applied": False,
                "actual_route_score_write": False,
                "actual_policy_write": False,
                "hindsight_write": False,
                "boundary": _false_boundary(),
            }
            _append_jsonl(self.labels_path, retracted)
        result = {
            "schema_version": "hermes.ground_truth_miner_retraction.v0",
            "module": "ground_truth_miner",
            "profile": self.profile,
            "status": "ok" if found else "missing",
            "label_id": label_id,
            "audit_action": "label_retracted" if found else "label_retraction_missing",
            "reason": reason,
            "actual_execute": False,
            "actual_policy_write": False,
            "actual_route_score_write": False,
            "hindsight_write": False,
            "boundary": _false_boundary(),
        }
        _append_jsonl(self.runs_path, result)
        return result

    def read_labels(self, *, include_expired: bool = False) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for record in _read_jsonl(self.labels_path):
            label_id = str(record.get("label_id") or "")
            if label_id:
                latest[label_id] = record
        labels = [_effective_label(item) for item in latest.values()]
        if not include_expired:
            labels = [item for item in labels if item.get("label_state") != "expired"]
        return labels

    def _label_from_audit(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        if entry.get("action") != "owner_action_reply_processed" or entry.get("status") != "ok":
            return None
        details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
        action_type = str(details.get("action_type") or "")
        target_id = str(details.get("target_id") or "")
        if action_type not in {"approve_candidate", "approve_crystallized_candidate"} or not target_id:
            return None
        label_id = _stable_id("gt_label", action_type, target_id)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=REVERSIBLE_LABEL_TTL_DAYS)
        return {
            "schema_version": "hermes.ground_truth_label.v0",
            "label_id": label_id,
            "profile": self.profile,
            "subject_ref": f"crystallized_candidate:{target_id}",
            "source_scope_ref": f"crystallized_candidate:{target_id}",
            "target_id": target_id,
            "label_kind": "owner_approved_candidate",
            "label_state": "active",
            "source_action": action_type,
            "source_audit_target": str(entry.get("target") or ""),
            "retractable": True,
            "ttl_days": REVERSIBLE_LABEL_TTL_DAYS,
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "live_applied": False,
            "score_live_applied": False,
            "route_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_policy_write": False,
            "actual_identity_write": False,
            "actual_relationship_write": False,
            "actual_route_score_write": False,
            "hindsight_write": False,
            "boundary": _false_boundary(),
        }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def _audit_entries_from_owner_action_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for record in records:
        action_type = str(record.get("action_type") or "")
        target_id = str(record.get("target_id") or "")
        if (
            str(record.get("result") or "") not in {"applied", "duplicate_ignored"}
            or action_type not in {"approve_candidate", "approve_crystallized_candidate"}
            or not target_id
        ):
            continue
        entries.append(
            {
                "action": "owner_action_reply_processed",
                "status": "ok",
                "target": str(record.get("owner_action_id") or ""),
                "created_at": str(record.get("created_at") or ""),
                "details": {
                    "action_type": action_type,
                    "target_id": target_id,
                    "source": "owner_actions_ledger",
                    "owner_action_id": str(record.get("owner_action_id") or ""),
                },
            }
        )
    return entries


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _effective_label(record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    effective = dict(record)
    if str(effective.get("label_state") or "") == "active" and _label_expired(effective, now=now):
        effective["label_state"] = "expired"
        effective["expired"] = True
    return effective


def _label_expired(record: dict[str, Any], *, now: datetime | None = None) -> bool:
    expires_at = _parse_time(str(record.get("expires_at") or ""))
    if expires_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    return expires_at <= current


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _label_state_counts(labels: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "active_label_count": sum(1 for item in labels if item.get("label_state") == "active"),
        "expired_label_count": sum(1 for item in labels if item.get("label_state") == "expired"),
        "retracted_label_count": sum(1 for item in labels if item.get("label_state") == "retracted"),
    }


def _false_boundary() -> dict[str, bool]:
    return {
        "actual_send": False,
        "actual_execute": False,
        "actual_policy_write": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_crystallized_approval": False,
        "actual_route_score_write": False,
        "hindsight_write": False,
    }


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"
