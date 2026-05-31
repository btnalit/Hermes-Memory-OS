"""Shadow confidence router for V7 governance."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def confidence_router_manifest() -> dict[str, Any]:
    return {
        "name": "confidence_router",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "evidence_scoring"],
            "optional": ["ground_truth_miner", "confabulation_detector"],
        },
        "provides": {
            "commands": ["status", "doctor", "route-all"],
            "schedules": ["confidence_router_shadow"],
            "reads": ["local_artifact.evidence_scoring"],
            "writes": ["local_artifact.confidence_router"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
    }


class ConfidenceRouterModule:
    def __init__(self, hermes_home: str | Path, *, profile: str, t_low: float = 0.4, t_high: float = 0.8) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile
        self.t_low = float(t_low)
        self.t_high = float(t_high)

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "confidence_router"

    @property
    def routes_path(self) -> Path:
        return self.module_root / "routing.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def route_records(self, records: list[dict[str, Any]], *, write: bool = True) -> dict[str, Any]:
        routes = [self._route(record) for record in records]
        distribution = Counter(route["band"] for route in routes)
        result = {
            "schema_version": "hermes.confidence_router_result.v0",
            "module": "confidence_router",
            "profile": self.profile,
            "status": "ok",
            "route_count": len(routes),
            "band_distribution": dict(sorted(distribution.items())),
            "actual_send": False,
            "actual_execute": False,
            "route_live_applied": False,
            "score_live_applied": False,
            "live_behavior_changed": False,
        }
        if write:
            self._write_jsonl(self.routes_path, routes)
            _append_jsonl(self.runs_path, result)
        return result

    def route_all(self, *, scoring: Any) -> dict[str, Any]:
        records = scoring.read_feature_scores()
        return self.route_records(records)

    def status(self) -> dict[str, Any]:
        routes = self.read_routes()
        runs = _read_jsonl(self.runs_path)
        distribution = Counter(route.get("band") for route in routes)
        return {
            "schema_version": "hermes.confidence_router_status.v0",
            "module": "confidence_router",
            "profile": self.profile,
            "status": "ok" if routes or runs else "missing",
            "route_count": len(routes),
            "run_count": len(runs),
            "band_distribution": dict(sorted(distribution.items())),
            "actual_send": False,
            "actual_execute": False,
            "route_live_applied": any(route.get("live_applied") is True for route in routes),
            "score_live_applied": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        if any(route.get("live_applied") is True for route in self.read_routes()):
            findings.append(
                {
                    "severity": "error",
                    "code": "confidence_route_live_applied",
                    "message": "ConfidenceRouter must stay shadow until route autonomy is explicitly promoted.",
                }
            )
        return {
            "schema_version": "hermes.confidence_router_doctor.v0",
            "module": "confidence_router",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }

    def read_routes(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.routes_path)

    def _route(self, record: dict[str, Any]) -> dict[str, Any]:
        maturity = float(record.get("maturity_score", record.get("feature_score", 0.0)) or 0.0)
        if maturity < self.t_low:
            band = "low"
            intent = "auto_discard_candidate"
        elif maturity < self.t_high:
            band = "mid"
            intent = "llm_review_candidate"
        else:
            band = "high"
            intent = "owner_agenda_candidate"
        subject_ref = str(record.get("subject_ref") or "")
        score_id = str(record.get("score_id") or record.get("primary_score_id") or record.get("feature_score_id") or "")
        return {
            "schema_version": "memory-os.confidence_route.v0",
            "route_id": _stable_id("confidence_route", subject_ref, score_id, str(maturity)),
            "profile": self.profile,
            "subject_ref": subject_ref,
            "subject_kind": str(record.get("subject_kind") or ""),
            "maturity_score": round(maturity, 3),
            "band": band,
            "thresholds": {"t_low": self.t_low, "t_high": self.t_high},
            "score_id": score_id,
            "route_intent": intent,
            "live_applied": False,
            "actual_send": False,
            "actual_execute": False,
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
