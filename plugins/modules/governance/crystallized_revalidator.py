"""Flag-only crystallized memory revalidator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
from plugins.memory.memory_os.substrates.projection import ProjectionLedger
from plugins.memory.memory_os.store import MemoryOSStore


def crystallized_revalidator_manifest() -> dict[str, Any]:
    return {
        "name": "crystallized_revalidator",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0"],
            "optional": ["ground_truth_miner"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["crystallized_revalidator_shadow"],
            "reads": ["memory_os.crystallized", "memory_os.events.summary"],
            "writes": ["local_artifact.crystallized_revalidator"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
    }


def invalidate_hindsight_projection_for_canonical_change(
    *,
    projection_ledger_path: Path,
    record_id: str,
    record_version: str,
    reason: str,
    substrate_snapshot_id: str,
) -> None:
    ProjectionLedger(projection_ledger_path).record_invalidate(
        provider="hindsight",
        source_record_ref=record_id,
        source_version=record_version,
        reason=reason,
        substrate_snapshot_id=substrate_snapshot_id,
    )


class CrystallizedRevalidatorModule:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "crystallized_revalidator"

    @property
    def flags_path(self) -> Path:
        return self.module_root / "revalidation_flags.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def evaluate(
        self,
        *,
        records: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        write: bool = True,
    ) -> dict[str, Any]:
        record_ids = {str(record.get("record_id") or record.get("file_name") or "") for record in records}
        flags = []
        for observation in observations:
            record_id = str(observation.get("contradicts_record_id") or "")
            if not record_id or record_id not in record_ids:
                continue
            flags.append(self._flag(record_id=record_id, observation=observation))
        result = {
            "schema_version": "hermes.crystallized_revalidator_result.v0",
            "module": "crystallized_revalidator",
            "profile": self.profile,
            "status": "ok",
            "record_count": len(records),
            "observation_count": len(observations),
            "flag_count": len(flags),
            "flags": flags,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
            "demotion_live_applied": False,
            "live_behavior_changed": False,
        }
        if write:
            self._write_jsonl(self.flags_path, flags)
            _append_jsonl(self.runs_path, {key: value for key, value in result.items() if key != "flags"})
        return result

    def run_once(self, *, store: MemoryOSStore) -> dict[str, Any]:
        return self.evaluate(
            records=_crystallized_records(store),
            observations=_event_observations(store),
            write=True,
        )

    def status(self) -> dict[str, Any]:
        flags = self.read_flags()
        runs = _read_jsonl(self.runs_path)
        return {
            "schema_version": "hermes.crystallized_revalidator_status.v0",
            "module": "crystallized_revalidator",
            "profile": self.profile,
            "status": "ok" if flags or runs else "missing",
            "flag_count": len(flags),
            "run_count": len(runs),
            "would_demote_count": sum(1 for item in flags if item.get("action") == "would_demote"),
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
            "demotion_live_applied": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        if any(flag.get("live_applied") is True for flag in self.read_flags()):
            findings.append(
                {
                    "severity": "error",
                    "code": "crystallized_revalidator_live_applied",
                    "message": "Revalidator flags must not demote crystallized memory in live-shadow.",
                }
            )
        return {
            "schema_version": "hermes.crystallized_revalidator_doctor.v0",
            "module": "crystallized_revalidator",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }

    def read_flags(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.flags_path)

    def _flag(self, *, record_id: str, observation: dict[str, Any]) -> dict[str, Any]:
        source_ref = str(observation.get("source_ref") or "")
        return {
            "schema_version": "hermes.crystallized_revalidation_flag.v0",
            "flag_id": _stable_id("crv", record_id, source_ref),
            "profile": self.profile,
            "record_id": record_id,
            "source_ref": source_ref,
            "action": "would_demote",
            "audit_action": "crystallized_regression_flagged",
            "live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_crystallized_approval": False,
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


def _crystallized_records(store: MemoryOSStore) -> list[dict[str, Any]]:
    service = CrystallizedMemoryService(store)
    records: list[dict[str, Any]] = []
    if not store.roots.crystallized_root.exists():
        return records
    for path in sorted(store.roots.crystallized_root.glob("*.md")):
        for record in service.read_records(path.name):
            record_id = str(record.frontmatter.get("id") or record.file_name)
            records.append(
                {
                    "record_id": record_id,
                    "file_name": record.file_name,
                    "subject_ref": f"crystallized:{record_id}",
                }
            )
    return records


def _event_observations(store: MemoryOSStore) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for event in store.read_events():
        safe_ref = event.safe_ref if isinstance(event.safe_ref, dict) else {}
        observations.append(
            {
                "source_ref": f"event:{event.id}",
                "contradicts_record_id": str(safe_ref.get("contradicts_record_id") or ""),
                "evidence_profile": {
                    "derivation": "direct_observation",
                    "provenance": "observed",
                },
            }
        )
    return observations


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"
