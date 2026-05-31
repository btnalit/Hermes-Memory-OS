"""V7 migration controller for cold-start and automation regime signals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plugins.modules.governance.live_guard import LiveGuardRegistry


def migration_controller_manifest() -> dict[str, Any]:
    return {
        "name": "migration_controller",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {"required": ["memory_os >=0.1.0"], "optional": ["ground_truth_miner", "imagination_loop"]},
        "provides": {
            "commands": ["status", "doctor", "evaluate"],
            "schedules": ["migration_controller_shadow"],
            "reads": ["local_artifact.ground_truth_miner", "local_artifact.imagination_loop"],
            "writes": ["local_artifact.migration_controller"],
        },
        "defaults": {"enabled": False, "delivery_mode": "no-send", "profile_scope": "per-profile"},
    }


class MigrationControllerModule:
    def __init__(self, hermes_home: str | Path, *, profile: str, label_floor: int = 20) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile
        self.label_floor = int(label_floor)

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "migration_controller"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def evaluate(
        self,
        *,
        signals: dict[str, Any],
        config: dict[str, Any] | None = None,
        write: bool = True,
    ) -> dict[str, Any]:
        label_count = int(signals.get("owner_label_count") or 0)
        cold_start = label_count < self.label_floor
        requested_mode = "live-shadow" if cold_start else "acting_candidate"
        guard = LiveGuardRegistry().apply_automation_mode(
            component="migration_controller",
            requested_mode=requested_mode,
            config=config or {},
            audit_path=self.module_root / "audit.jsonl",
        )
        automation_allowed = not cold_start and guard["effective_mode"] == "acting_candidate"
        result = {
            "schema_version": "hermes.migration_controller_result.v0",
            "module": "migration_controller",
            "profile": self.profile,
            "status": "ok",
            "regime": "cold_start" if cold_start else "eligible_shadow",
            "owner_label_count": label_count,
            "label_floor": self.label_floor,
            "simulation_preheated": bool(signals.get("simulation_preheated")),
            "effective_mode": guard["effective_mode"],
            "automation_allowed": automation_allowed,
            "migration_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
            "live_behavior_changed": False,
        }
        if write:
            _append_jsonl(self.runs_path, result)
        return result

    def status(self) -> dict[str, Any]:
        runs = _read_jsonl(self.runs_path)
        return {
            "schema_version": "hermes.migration_controller_status.v0",
            "module": "migration_controller",
            "profile": self.profile,
            "status": "ok" if runs else "missing",
            "run_count": len(runs),
            "last_regime": str(runs[-1].get("regime") or "") if runs else "",
            "migration_live_applied": any(run.get("migration_live_applied") is True for run in runs),
            "actual_send": False,
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        if self.status()["migration_live_applied"]:
            findings.append(
                {
                    "severity": "error",
                    "code": "migration_live_applied",
                    "message": "MigrationController cannot flip automation from inside live-shadow.",
                }
            )
        return {
            "schema_version": "hermes.migration_controller_doctor.v0",
            "module": "migration_controller",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
