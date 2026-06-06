"""Live-shadow imagination loop with simulated provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.memory_os.data.v7_simulated import load_scenarios
from plugins.memory.memory_os.jsonl_io import JsonlReadResult, append_jsonl, read_jsonl_result, write_jsonl


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
        scenario_result = self._read_scenarios_result()
        scenarios = scenario_result.records
        return {
            "schema_version": "hermes.imagination_loop_status.v0",
            "module": "imagination_loop",
            "profile": self.profile,
            "status": "ok" if scenarios else "missing",
            "scenario_count": len(scenarios),
            "simulated_count": sum(1 for item in scenarios if item.get("provenance") == "simulated"),
            "suppressed_error_count": scenario_result.suppressed_error_count,
            "recent_error_codes": scenario_result.recent_error_codes[-5:],
            "actual_send": False,
            "actual_execute": False,
            "live_behavior_changed": False,
        }

    def doctor(self) -> dict[str, Any]:
        scenario_result = self._read_scenarios_result()
        scenarios = scenario_result.records
        findings: list[dict[str, Any]] = []
        if any(item.get("provenance") != "simulated" for item in scenarios):
            findings.append(
                {
                    "severity": "error",
                    "code": "non_simulated_imagination_record",
                    "message": "Imagination loop records must keep simulated provenance.",
                }
            )
        for error_record in scenario_result.error_records[-5:]:
            findings.append(
                {
                    "severity": "warning",
                    "code": "imagination_loop_jsonl_suppressed_error",
                    "error_record": error_record,
                }
            )
        return {
            "schema_version": "hermes.imagination_loop_doctor.v0",
            "module": "imagination_loop",
            "profile": self.profile,
            "status": "error" if any(item.get("severity") == "error" for item in findings) else "warning" if findings else "ok",
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
        write_jsonl(self.scenarios_path, records)
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
        append_jsonl(self.runs_path, result)
        return result

    def read_scenarios(self) -> list[dict[str, Any]]:
        return self._read_scenarios_result().records

    def _read_scenarios_result(self) -> JsonlReadResult:
        return read_jsonl_result(
            self.scenarios_path,
            component="imagination_loop",
            operation="read_scenarios",
        )
