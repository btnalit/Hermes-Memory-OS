"""Discard-side shadow recall safety net."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def shadow_recall_manifest() -> dict[str, Any]:
    return {
        "name": "shadow_recall",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {"required": ["memory_os >=0.1.0"], "optional": ["confidence_router"]},
        "provides": {
            "commands": ["status", "doctor", "evaluate"],
            "schedules": ["shadow_recall_shadow"],
            "reads": ["local_artifact.confidence_router", "memory_os.recall_miss"],
            "writes": ["local_artifact.shadow_recall"],
        },
        "defaults": {"enabled": False, "delivery_mode": "no-send", "profile_scope": "per-profile"},
    }


class ShadowRecallModule:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "shadow_recall"

    @property
    def fingerprints_path(self) -> Path:
        return self.module_root / "discard_fingerprints.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def record_discards(self, candidates: list[dict[str, Any]], *, write: bool = True) -> dict[str, Any]:
        fingerprints = [self._fingerprint(candidate) for candidate in candidates]
        result = {
            "schema_version": "hermes.shadow_recall_record_result.v0",
            "module": "shadow_recall",
            "profile": self.profile,
            "status": "ok",
            "fingerprint_count": len(fingerprints),
            "auto_discard_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
        }
        if write:
            _write_jsonl(self.fingerprints_path, fingerprints)
            _append_jsonl(self.runs_path, result)
        return result

    def evaluate_recall_misses(self, misses: list[dict[str, Any]], *, write: bool = True) -> dict[str, Any]:
        fingerprints = self.read_fingerprints()
        known = {str(item.get("fingerprint") or "") for item in fingerprints}
        hits = []
        for miss in misses:
            fingerprint = _fingerprint_text(str(miss.get("text") or miss.get("query") or ""))
            if fingerprint in known:
                hits.append({"query": str(miss.get("query") or ""), "fingerprint": fingerprint})
        result = {
            "schema_version": "hermes.shadow_recall_eval_result.v0",
            "module": "shadow_recall",
            "profile": self.profile,
            "status": "ok",
            "miss_count": len(misses),
            "miss_hit_count": len(hits),
            "hits": hits,
            "auto_discard_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
            "live_behavior_changed": False,
        }
        if write:
            _append_jsonl(self.runs_path, {key: value for key, value in result.items() if key != "hits"})
        return result

    def status(self) -> dict[str, Any]:
        fingerprints = self.read_fingerprints()
        runs = _read_jsonl(self.runs_path)
        return {
            "schema_version": "hermes.shadow_recall_status.v0",
            "module": "shadow_recall",
            "profile": self.profile,
            "status": "ok" if fingerprints or runs else "missing",
            "fingerprint_count": len(fingerprints),
            "run_count": len(runs),
            "auto_discard_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.shadow_recall_doctor.v0",
            "module": "shadow_recall",
            "profile": self.profile,
            "status": "ok",
            "findings": [],
        }

    def read_fingerprints(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.fingerprints_path)

    def _fingerprint(self, candidate: dict[str, Any]) -> dict[str, Any]:
        text = str(candidate.get("text") or "")
        return {
            "schema_version": "hermes.shadow_recall_fingerprint.v0",
            "profile": self.profile,
            "subject_ref": str(candidate.get("subject_ref") or ""),
            "fingerprint": _fingerprint_text(text),
            "route_intent": str(candidate.get("route_intent") or ""),
            "live_applied": False,
        }


def _fingerprint_text(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()[:24]


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
