"""Tier0 pre-router and report-only candidate review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def candidate_review_manifest() -> dict[str, Any]:
    return {
        "name": "candidate_review",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {"required": ["memory_os >=0.1.0", "confidence_router"], "optional": ["hindsight_adapter"]},
        "provides": {
            "commands": ["status", "doctor", "review"],
            "schedules": ["candidate_review_shadow"],
            "reads": ["local_artifact.confidence_router"],
            "writes": ["local_artifact.candidate_review"],
        },
        "defaults": {"enabled": False, "delivery_mode": "no-send", "profile_scope": "per-profile"},
    }


class FeaturePreRouter:
    def route(self, routes: list[dict[str, Any]]) -> dict[str, Any]:
        items = [self._route_item(route) for route in routes]
        return {
            "schema_version": "hermes.feature_prerouter_result.v0",
            "module": "feature_prerouter",
            "status": "ok",
            "item_count": len(items),
            "items": items,
            "prerouter_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
        }

    def _route_item(self, route: dict[str, Any]) -> dict[str, Any]:
        band = str(route.get("band") or "")
        score = float(route.get("maturity_score") or route.get("feature_score") or 0.0)
        if band == "low" or score < 0.4:
            pre_route = "fast_discard"
        elif band == "high" or score >= 0.8:
            pre_route = "fast_merge"
        else:
            pre_route = "needs_review"
        subject_ref = str(route.get("subject_ref") or "")
        return {
            "schema_version": "hermes.feature_preroute.v0",
            "pre_route_id": _stable_id("fpr", subject_ref, pre_route, str(score)),
            "subject_ref": subject_ref,
            "maturity_score": round(score, 3),
            "band": band,
            "pre_route": pre_route,
            "live_applied": False,
            "actual_send": False,
            "actual_execute": False,
        }


class CandidateReviewModule:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "candidate_review"

    @property
    def decisions_path(self) -> Path:
        return self.module_root / "decisions.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def review(self, items: list[dict[str, Any]], *, write: bool = True) -> dict[str, Any]:
        decisions = [self._decision(item) for item in items]
        result = {
            "schema_version": "hermes.candidate_review_result.v0",
            "module": "candidate_review",
            "profile": self.profile,
            "status": "ok",
            "decision_count": len(decisions),
            "decisions": decisions,
            "candidate_review_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
            "live_behavior_changed": False,
        }
        if write:
            _write_jsonl(self.decisions_path, decisions)
            _append_jsonl(self.runs_path, {key: value for key, value in result.items() if key != "decisions"})
        return result

    def status(self) -> dict[str, Any]:
        decisions = _read_jsonl(self.decisions_path)
        runs = _read_jsonl(self.runs_path)
        return {
            "schema_version": "hermes.candidate_review_status.v0",
            "module": "candidate_review",
            "profile": self.profile,
            "status": "ok" if decisions or runs else "missing",
            "decision_count": len(decisions),
            "run_count": len(runs),
            "candidate_review_live_applied": any(item.get("live_applied") is True for item in decisions),
            "actual_send": False,
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        if self.status()["candidate_review_live_applied"]:
            findings.append(
                {
                    "severity": "error",
                    "code": "candidate_review_live_applied",
                    "message": "CandidateReview must remain report-only until an acting gate promotes it.",
                }
            )
        return {
            "schema_version": "hermes.candidate_review_doctor.v0",
            "module": "candidate_review",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }

    def _decision(self, item: dict[str, Any]) -> dict[str, Any]:
        pre_route = str(item.get("pre_route") or "")
        if pre_route == "fast_discard":
            decision = "downgrade"
        elif pre_route == "fast_merge":
            decision = "keep"
        else:
            decision = "recollect"
        subject_ref = str(item.get("subject_ref") or "")
        return {
            "schema_version": "hermes.candidate_review_decision.v0",
            "decision_id": _stable_id("cr", subject_ref, decision),
            "profile": self.profile,
            "subject_ref": subject_ref,
            "decision": decision,
            "self_confidence": 0.7 if decision == "recollect" else 0.9,
            "live_applied": False,
            "actual_send": False,
            "actual_execute": False,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
