"""Guarded report-only cascade routing policy proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def cascade_routing_policy_manifest() -> dict[str, Any]:
    return {
        "name": "cascade_routing_policy",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {"required": ["memory_os >=0.1.0"], "optional": ["judge_calibration"]},
        "provides": {
            "commands": ["status", "doctor", "propose-policy"],
            "schedules": ["cascade_routing_policy_shadow"],
            "reads": ["local_artifact.confidence_router", "local_artifact.judge_calibration"],
            "writes": ["local_artifact.cascade_routing_policy"],
        },
        "defaults": {"enabled": False, "delivery_mode": "no-send", "profile_scope": "per-profile"},
    }


class CascadeRoutingPolicyModule:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "cascade_routing_policy"

    @property
    def proposals_path(self) -> Path:
        return self.module_root / "policy_proposals.jsonl"

    def propose_policy(
        self,
        *,
        band_metrics: dict[str, dict[str, Any]],
        guardrails: dict[str, Any],
        write: bool = True,
    ) -> dict[str, Any]:
        min_n = int(guardrails.get("min_n") or 30)
        guardrails_passed = bool(guardrails.get("aa_passed")) and bool(guardrails.get("honesty_passed"))
        policy = {}
        for band, metrics in sorted(band_metrics.items()):
            n = int(metrics.get("n") or 0)
            error_rate = float(metrics.get("error_rate") or 0.0)
            policy[str(band)] = {
                "n": n,
                "error_rate": round(error_rate, 3),
                "partial_pooling_applied": n < min_n,
                "automation_candidate": guardrails_passed and n >= min_n and error_rate <= 0.05,
            }
        result = {
            "schema_version": "hermes.cascade_routing_policy_result.v0",
            "module": "cascade_routing_policy",
            "profile": self.profile,
            "status": "ok" if guardrails_passed else "warning",
            "policy": policy,
            "guardrails_passed": guardrails_passed,
            "route_strategy_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
            "live_behavior_changed": False,
        }
        if write:
            _append_jsonl(self.proposals_path, result)
        return result

    def status(self) -> dict[str, Any]:
        proposals = _read_jsonl(self.proposals_path)
        return {
            "schema_version": "hermes.cascade_routing_policy_status.v0",
            "module": "cascade_routing_policy",
            "profile": self.profile,
            "status": "ok" if proposals else "missing",
            "proposal_count": len(proposals),
            "route_strategy_live_applied": any(item.get("route_strategy_live_applied") is True for item in proposals),
            "actual_send": False,
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        if self.status()["route_strategy_live_applied"]:
            findings.append(
                {
                    "severity": "error",
                    "code": "route_strategy_live_applied",
                    "message": "Cascade routing policy proposals must not self-apply in live-shadow.",
                }
            )
        return {
            "schema_version": "hermes.cascade_routing_policy_doctor.v0",
            "module": "cascade_routing_policy",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    from plugins.memory.memory_os.jsonl_io import append_jsonl_locked

    append_jsonl_locked(path, record)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
