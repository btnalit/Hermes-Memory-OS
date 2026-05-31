"""Report-only judge consistency, calibration, and canary monitor."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def judge_calibration_manifest() -> dict[str, Any]:
    return {
        "name": "judge_calibration",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {"required": ["memory_os >=0.1.0"], "optional": ["ground_truth_miner"]},
        "provides": {
            "commands": ["status", "doctor", "evaluate"],
            "schedules": ["judge_calibration_shadow"],
            "reads": ["local_artifact.candidate_review", "local_artifact.ground_truth_miner"],
            "writes": ["local_artifact.judge_calibration"],
        },
        "defaults": {"enabled": False, "delivery_mode": "no-send", "profile_scope": "per-profile"},
    }


class JudgeCalibrationMonitor:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "judge_calibration"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def evaluate(
        self,
        *,
        decisions: list[dict[str, Any]],
        canaries: list[dict[str, Any]],
        write: bool = True,
    ) -> dict[str, Any]:
        consistency_rate = _consistency_rate(decisions)
        canary_passed = all(str(item.get("verdict")) == str(item.get("expected")) for item in canaries)
        keep_count = sum(1 for item in decisions if str(item.get("verdict")) == "keep")
        result = {
            "schema_version": "hermes.judge_calibration_result.v0",
            "module": "judge_calibration",
            "profile": self.profile,
            "status": "ok" if canary_passed else "warning",
            "decision_count": len(decisions),
            "canary_count": len(canaries),
            "consistency_rate": round(consistency_rate, 3),
            "keep_rate": round(keep_count / len(decisions), 3) if decisions else 0.0,
            "canary_passed": canary_passed,
            "calibration_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "live_behavior_changed": False,
        }
        if write:
            _append_jsonl(self.runs_path, result)
        return result

    def status(self) -> dict[str, Any]:
        runs = _read_jsonl(self.runs_path)
        return {
            "schema_version": "hermes.judge_calibration_status.v0",
            "module": "judge_calibration",
            "profile": self.profile,
            "status": "ok" if runs else "missing",
            "run_count": len(runs),
            "calibration_live_applied": any(run.get("calibration_live_applied") is True for run in runs),
            "actual_send": False,
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        if self.status()["calibration_live_applied"]:
            findings.append(
                {
                    "severity": "error",
                    "code": "judge_calibration_live_applied",
                    "message": "Judge calibration cannot mutate route or LLM authority in live-shadow.",
                }
            )
        return {
            "schema_version": "hermes.judge_calibration_doctor.v0",
            "module": "judge_calibration",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }


def _consistency_rate(decisions: list[dict[str, Any]]) -> float:
    grouped: dict[str, list[str]] = defaultdict(list)
    for decision in decisions:
        case_id = str(decision.get("case_id") or "")
        if case_id:
            grouped[case_id].append(str(decision.get("verdict") or ""))
    repeated = [values for values in grouped.values() if len(values) > 1]
    if not repeated:
        return 1.0
    rates = []
    for values in repeated:
        counts = Counter(values)
        rates.append(max(counts.values()) / len(values))
    return sum(rates) / len(rates)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
