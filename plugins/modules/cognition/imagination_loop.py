"""Live-shadow imagination loop with simulated provenance."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.memory_os.data.v7_simulated import load_scenarios


def imagination_loop_manifest() -> dict[str, Any]:
    return {
        "name": "imagination_loop",
        "kind": "cognition",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0"],
            "optional": ["evidence_scoring", "confabulation_detector"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["imagination_loop_shadow"],
            "reads": ["eval.v7_simulated"],
            "writes": ["local_artifact.imagination_loop"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
    }


class ImaginationLoopModule:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "imagination_loop"

    @property
    def scenarios_path(self) -> Path:
        return self.module_root / "scenarios.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def status(self) -> dict[str, Any]:
        scenarios = self.read_scenarios()
        return {
            "schema_version": "hermes.imagination_loop_status.v0",
            "module": "imagination_loop",
            "profile": self.profile,
            "status": "ok" if scenarios else "missing",
            "scenario_count": len(scenarios),
            "simulated_count": sum(1 for item in scenarios if item.get("provenance") == "simulated"),
            "actual_send": False,
            "actual_execute": False,
            "live_behavior_changed": False,
        }

    def doctor(self) -> dict[str, Any]:
        scenarios = self.read_scenarios()
        findings: list[dict[str, Any]] = []
        if any(item.get("provenance") != "simulated" for item in scenarios):
            findings.append(
                {
                    "severity": "error",
                    "code": "non_simulated_imagination_record",
                    "message": "Imagination loop records must keep simulated provenance.",
                }
            )
        return {
            "schema_version": "hermes.imagination_loop_doctor.v0",
            "module": "imagination_loop",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }

    def run_once(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        records = [
            {
                **scenario,
                "schema_version": "hermes.imagination_loop_scenario.v0",
                "module": "imagination_loop",
                "profile": self.profile,
                "created_at": now,
                "live_applied": False,
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "candidate_written_to_canonical": False,
                "live_behavior_changed": False,
            }
            for scenario in load_scenarios()
        ]
        self._write_jsonl(self.scenarios_path, records)
        result = {
            "schema_version": "hermes.imagination_loop_result.v0",
            "module": "imagination_loop",
            "profile": self.profile,
            "status": "ok",
            "scenario_count": len(records),
            "simulated_count": len(records),
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "live_behavior_changed": False,
            "candidate_written_to_canonical": False,
            "live_applied": False,
        }
        _append_jsonl(self.runs_path, result)
        return result

    def read_scenarios(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.scenarios_path)

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
