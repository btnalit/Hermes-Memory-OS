"""Live-shadow confabulation detector."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def confabulation_detector_manifest() -> dict[str, Any]:
    return {
        "name": "confabulation_detector",
        "kind": "evidence",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "evidence_scoring"],
            "optional": ["imagination_loop"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["confabulation_detector_shadow"],
            "reads": ["local_artifact.evidence_scoring"],
            "writes": ["local_artifact.confabulation_detector"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
    }


class ConfabulationDetectorModule:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "confabulation_detector"

    @property
    def flags_path(self) -> Path:
        return self.module_root / "flags.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def evaluate_records(self, records: list[dict[str, Any]], *, write: bool = True) -> dict[str, Any]:
        flags = [self._flag(record) for record in records if self._should_flag(record)]
        result = {
            "schema_version": "hermes.confabulation_detector_result.v0",
            "module": "confabulation_detector",
            "profile": self.profile,
            "status": "ok",
            "record_count": len(records),
            "flag_count": len(flags),
            "flags": flags,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "score_live_applied": False,
            "route_live_applied": False,
            "live_behavior_changed": False,
        }
        if write:
            self._write_jsonl(self.flags_path, flags)
            _append_jsonl(
                self.runs_path,
                {
                    key: value
                    for key, value in result.items()
                    if key != "flags"
                },
            )
        return result

    def run_once(self, *, scoring: Any) -> dict[str, Any]:
        return self.evaluate_records(scoring.read_feature_scores(), write=True)

    def status(self) -> dict[str, Any]:
        flags = self.read_flags()
        runs = _read_jsonl(self.runs_path)
        return {
            "schema_version": "hermes.confabulation_detector_status.v0",
            "module": "confabulation_detector",
            "profile": self.profile,
            "status": "ok" if flags or runs else "missing",
            "flag_count": len(flags),
            "run_count": len(runs),
            "actual_send": False,
            "actual_execute": False,
            "score_live_applied": False,
            "route_live_applied": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        if any(flag.get("action") != "report_only" for flag in self.read_flags()):
            findings.append(
                {
                    "severity": "error",
                    "code": "confabulation_non_report_only_flag",
                    "message": "Confabulation flags must stay report-only in live-shadow.",
                }
            )
        return {
            "schema_version": "hermes.confabulation_detector_doctor.v0",
            "module": "confabulation_detector",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }

    def read_flags(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.flags_path)

    def _should_flag(self, record: dict[str, Any]) -> bool:
        profile = record.get("evidence_profile") if isinstance(record.get("evidence_profile"), dict) else {}
        coverage = profile.get("coverage") if isinstance(profile.get("coverage"), dict) else {}
        return (
            float(record.get("maturity_score") or 0.0) >= 0.85
            and int(coverage.get("source_diversity") or 0) <= 1
            and int(coverage.get("recurrence") or 0) <= 1
            and str(profile.get("derivation") or "") in {"inference", "simulated"}
        )

    def _flag(self, record: dict[str, Any]) -> dict[str, Any]:
        profile = record.get("evidence_profile") if isinstance(record.get("evidence_profile"), dict) else {}
        coverage = profile.get("coverage") if isinstance(profile.get("coverage"), dict) else {}
        subject_ref = str(record.get("subject_ref") or "")
        flag_id = _stable_id("confab", subject_ref, str(record.get("maturity_score") or ""), json.dumps(profile, sort_keys=True))
        return {
            "schema_version": "hermes.confabulation_flag.v0",
            "flag_id": flag_id,
            "profile": self.profile,
            "subject_ref": subject_ref,
            "maturity_score": round(float(record.get("maturity_score") or 0.0), 3),
            "derivation": str(profile.get("derivation") or ""),
            "provenance": str(profile.get("provenance") or ""),
            "source_diversity": int(coverage.get("source_diversity") or 0),
            "recurrence": int(coverage.get("recurrence") or 0),
            "action": "report_only",
            "audit_action": "confabulation_flagged",
            "actual_send": False,
            "actual_execute": False,
            "score_live_applied": False,
            "route_live_applied": False,
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
