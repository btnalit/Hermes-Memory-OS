"""Live-shadow provisional tier for high-confidence candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def provisional_manifest() -> dict[str, Any]:
    return {
        "name": "provisional",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {"required": ["memory_os >=0.1.0"], "optional": ["ops_gate", "candidate_review"]},
        "provides": {
            "commands": ["status", "doctor", "evaluate-promotions"],
            "schedules": ["provisional_shadow"],
            "reads": ["local_artifact.candidate_review"],
            "writes": ["local_artifact.provisional"],
        },
        "defaults": {"enabled": False, "delivery_mode": "no-send", "profile_scope": "per-profile"},
    }


class ProvisionalModule:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "provisional"

    @property
    def records_path(self) -> Path:
        return self.module_root / "records.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def write_provisional(self, candidates: list[dict[str, Any]], *, write: bool = True) -> dict[str, Any]:
        records = [self._record(candidate) for candidate in candidates]
        result = {
            "schema_version": "hermes.provisional_result.v0",
            "module": "provisional",
            "profile": self.profile,
            "status": "ok",
            "provisional_count": len(records),
            "records": records,
            "provisional_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_crystallized_approval": False,
            "canonical_state_changed": False,
        }
        if write:
            _write_jsonl(self.records_path, records)
            _append_jsonl(self.runs_path, {key: value for key, value in result.items() if key != "records"})
        return result

    def evaluate_promotions(self, *, min_maturity: float = 0.9, write: bool = True) -> dict[str, Any]:
        records = self.read_records()
        would_promote = [
            record
            for record in records
            if float(record.get("maturity_score") or 0.0) >= min_maturity
            and str(record.get("decision") or "") == "keep"
        ]
        result = {
            "schema_version": "hermes.provisional_promotion_result.v0",
            "module": "provisional",
            "profile": self.profile,
            "status": "ok",
            "record_count": len(records),
            "would_promote_count": len(would_promote),
            "auto_promote_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_crystallized_approval": False,
            "canonical_state_changed": False,
            "live_behavior_changed": False,
        }
        if write:
            _append_jsonl(self.runs_path, result)
        return result

    def status(self) -> dict[str, Any]:
        records = self.read_records()
        runs = _read_jsonl(self.runs_path)
        return {
            "schema_version": "hermes.provisional_status.v0",
            "module": "provisional",
            "profile": self.profile,
            "status": "ok" if records or runs else "missing",
            "record_count": len(records),
            "run_count": len(runs),
            "auto_promote_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_crystallized_approval": False,
        }

    def doctor(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.provisional_doctor.v0",
            "module": "provisional",
            "profile": self.profile,
            "status": "ok",
            "findings": [],
        }

    def read_records(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.records_path)

    def _record(self, candidate: dict[str, Any]) -> dict[str, Any]:
        subject_ref = str(candidate.get("subject_ref") or "")
        return {
            "schema_version": "hermes.provisional_record.v0",
            "provisional_id": _stable_id("prov", subject_ref, str(candidate.get("maturity_score") or "")),
            "profile": self.profile,
            "subject_ref": subject_ref,
            "decision": str(candidate.get("decision") or ""),
            "maturity_score": round(float(candidate.get("maturity_score") or 0.0), 3),
            "source_refs": [str(ref) for ref in candidate.get("source_refs") or []],
            "live_applied": False,
            "actual_crystallized_approval": False,
        }


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    from plugins.memory.memory_os.jsonl_io import append_jsonl_locked

    append_jsonl_locked(path, record)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
