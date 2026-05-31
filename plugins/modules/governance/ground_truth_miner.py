"""Retractable owner-label miner for V7 live-shadow governance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit, read_audit_entries
from plugins.memory.memory_os.store import MemoryOSStore


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
        labels = self.read_labels()
        runs = _read_jsonl(self.runs_path)
        return {
            "schema_version": "hermes.ground_truth_miner_status.v0",
            "module": "ground_truth_miner",
            "profile": self.profile,
            "status": "ok" if labels or runs else "missing",
            "label_count": len(labels),
            "run_count": len(runs),
            "active_label_count": sum(1 for item in labels if item.get("label_state") == "active"),
            "retracted_label_count": sum(1 for item in labels if item.get("label_state") == "retracted"),
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

    def run_once(self, *, store: MemoryOSStore) -> dict[str, Any]:
        return self.mine(store=store, audit_entries=read_audit_entries(store.roots.audit_path))

    def mine(self, *, store: MemoryOSStore, audit_entries: list[dict[str, Any]]) -> dict[str, Any]:
        existing = {str(item.get("label_id") or ""): item for item in self.read_labels()}
        labels = list(existing.values())
        generated = []
        for entry in audit_entries:
            label = self._label_from_audit(entry)
            if not label or label["label_id"] in existing:
                continue
            labels.append(label)
            existing[label["label_id"]] = label
            generated.append(label)
        self._write_jsonl(self.labels_path, labels)
        result = {
            "schema_version": "hermes.ground_truth_miner_result.v0",
            "module": "ground_truth_miner",
            "profile": self.profile,
            "status": "ok",
            "label_count": len(generated),
            "total_label_count": len(labels),
            "actual_send": False,
            "actual_execute": False,
            "score_live_applied": False,
            "route_live_applied": False,
        }
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
        labels = self.read_labels()
        found = False
        updated = []
        for label in labels:
            if str(label.get("label_id") or "") == label_id:
                label = {
                    **label,
                    "label_state": "retracted",
                    "retraction_reason": reason,
                    "retracted_at": datetime.now(timezone.utc).isoformat(),
                    "score_live_applied": False,
                    "route_live_applied": False,
                }
                found = True
            updated.append(label)
        self._write_jsonl(self.labels_path, updated)
        result = {
            "schema_version": "hermes.ground_truth_miner_retraction.v0",
            "module": "ground_truth_miner",
            "profile": self.profile,
            "status": "ok" if found else "missing",
            "label_id": label_id,
            "audit_action": "label_retracted" if found else "label_retraction_missing",
            "reason": reason,
            "actual_execute": False,
        }
        _append_jsonl(self.runs_path, result)
        return result

    def read_labels(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.labels_path)

    def _label_from_audit(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        if entry.get("action") != "owner_action_reply_processed" or entry.get("status") != "ok":
            return None
        details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
        action_type = str(details.get("action_type") or "")
        target_id = str(details.get("target_id") or "")
        if action_type not in {"approve_candidate", "approve_crystallized_candidate"} or not target_id:
            return None
        label_id = _stable_id("gt_label", action_type, target_id)
        return {
            "schema_version": "hermes.ground_truth_label.v0",
            "label_id": label_id,
            "profile": self.profile,
            "subject_ref": f"crystallized_candidate:{target_id}",
            "target_id": target_id,
            "label_kind": "owner_approved_candidate",
            "label_state": "active",
            "source_action": action_type,
            "source_audit_target": str(entry.get("target") or ""),
            "retractable": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "live_applied": False,
            "score_live_applied": False,
            "route_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
        }

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )


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


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"
