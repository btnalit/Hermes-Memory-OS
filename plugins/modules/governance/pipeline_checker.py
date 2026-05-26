"""Report-only left-brain pipeline closure checker."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from plugins.modules.evidence.scoring import EvidenceScoringModule
from plugins.modules.governance.proposal_queue import ProposalQueueModule
from plugins.memory.memory_os.store import MemoryOSStore


LEFT_BRAIN_PIPELINE_CHECK_SCHEMA_VERSION = "hermes.memory_os.left_brain_pipeline_check.v0"


def left_brain_pipeline_check_manifest() -> dict[str, Any]:
    return {
        "name": "left_brain_pipeline_check",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "proposal_queue", "evidence_scoring"],
            "optional": ["ops_gate"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["left_brain_pipeline_check"],
            "reads": ["local_artifact.proposal_queue_state", "local_artifact.evidence_scoring"],
            "writes": ["local_artifact.left_brain_pipeline_check"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
    }


class LeftBrainPipelineCheckModule:
    """Check left-brain closure without creating tickets or executing work."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "left_brain_pipeline_check"

    @property
    def report_path(self) -> Path:
        return self.module_root / "latest.json"

    def status(self) -> dict[str, Any]:
        report = self.read_latest()
        return {
            "schema_version": "hermes.memory_os.left_brain_pipeline_check_status.v0",
            "module": "left_brain_pipeline_check",
            "profile": self.profile,
            "status": report.get("status", "missing"),
            "finding_count": len(report.get("findings", [])) if isinstance(report.get("findings"), list) else 0,
            "report_path": str(self.report_path),
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        status = self.status()
        findings = []
        if status["status"] == "missing":
            findings.append(
                {
                    "severity": "warning",
                    "code": "left_brain_pipeline_check_missing",
                    "message": "No left-brain pipeline check report has been written yet.",
                }
            )
        return {
            "schema_version": "hermes.memory_os.left_brain_pipeline_check_doctor.v0",
            "module": "left_brain_pipeline_check",
            "profile": self.profile,
            "status": "warning" if findings else "ok",
            "findings": findings,
        }

    def run_once(self, *, store: MemoryOSStore, write: bool = True) -> dict[str, Any]:
        proposal_queue = ProposalQueueModule(self.hermes_home, profile=self.profile)
        evidence = EvidenceScoringModule(self.hermes_home, profile=self.profile)
        proposals = [
            item
            for item in proposal_queue.read_queue().get("items", [])
            if str(item.get("profile", self.profile)) == self.profile
        ]
        feature_scores = [
            score
            for score in evidence.read_feature_scores()
            if str(score.get("profile", self.profile)) in {"", self.profile}
        ]
        findings = self._findings(proposals=proposals, feature_scores=feature_scores)
        severity_rank = {"info": 0, "warning": 1, "error": 2}
        max_severity = max((severity_rank.get(str(f.get("severity", "info")), 0) for f in findings), default=0)
        status = "fail" if max_severity >= 2 else "warn" if max_severity == 1 else "ok"
        report = {
            "schema_version": LEFT_BRAIN_PIPELINE_CHECK_SCHEMA_VERSION,
            "module": "left_brain_pipeline_check",
            "profile": self.profile,
            "status": status,
            "proposal_lifecycle": self._proposal_lifecycle(proposals),
            "duplicate_unresolved": self._duplicate_unresolved(proposals),
            "approved_followup": self._approved_followup(proposals),
            "execution_boundary": self._execution_boundary(proposals),
            "feature_scoring": self._feature_scoring(feature_scores),
            "findings": findings,
            "raw_body_included": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
        }
        if write:
            self.module_root.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report

    def read_latest(self) -> dict[str, Any]:
        if not self.report_path.exists():
            return {}
        parsed = json.loads(self.report_path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}

    def _findings(self, *, proposals: list[dict[str, Any]], feature_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        live_feature_scores = [
            score
            for score in feature_scores
            if bool(score.get("live_applied", False)) or bool(score.get("maturity_live_applied", False))
        ]
        if live_feature_scores:
            findings.append(
                {
                    "severity": "error",
                    "code": "feature_score_live_applied",
                    "message": "Feature scoring must stay report-only until a separate apply gate promotes it.",
                    "count": len(live_feature_scores),
                }
            )
        if any(bool(item.get("actual_execute", False)) for item in proposals):
            findings.append(
                {
                    "severity": "error",
                    "code": "proposal_actual_execute",
                    "message": "Proposal follow-up must not execute work.",
                }
            )
        unresolved_duplicates = self._duplicate_unresolved(proposals)
        if unresolved_duplicates["duplicate_group_count"]:
            findings.append(
                {
                    "severity": "warning",
                    "code": "duplicate_unresolved_proposals",
                    "message": "Multiple unresolved proposal candidates share the same title/kind.",
                    "count": unresolved_duplicates["duplicate_group_count"],
                }
            )
        return findings

    def _proposal_lifecycle(self, proposals: list[dict[str, Any]]) -> dict[str, Any]:
        state_counts = Counter(str(item.get("state", "candidate")) for item in proposals)
        followup_counts = Counter(str(item.get("followup_state", "none")) for item in proposals)
        return {
            "proposal_count": len(proposals),
            "state_counts": dict(sorted(state_counts.items())),
            "followup_state_counts": dict(sorted(followup_counts.items())),
        }

    def _duplicate_unresolved(self, proposals: list[dict[str, Any]]) -> dict[str, Any]:
        unresolved = [
            item
            for item in proposals
            if str(item.get("state", "")) not in {"owner_declined", "expired", "pressure_blocked"}
        ]
        groups: dict[str, list[str]] = {}
        for item in unresolved:
            key = "|".join(
                [
                    str(item.get("kind") or "proposal"),
                    " ".join(str(item.get("title") or "").lower().split()),
                ]
            )
            groups.setdefault(key, []).append(str(item.get("candidate_id", "")))
        duplicates = {key: ids for key, ids in groups.items() if len([item for item in ids if item]) > 1}
        return {
            "duplicate_group_count": len(duplicates),
            "duplicate_candidate_count": sum(len(ids) for ids in duplicates.values()),
        }

    def _approved_followup(self, proposals: list[dict[str, Any]]) -> dict[str, Any]:
        approved = [item for item in proposals if str(item.get("state", "")) == "approved_for_proposal"]
        awaiting_ops_gate = [
            item
            for item in approved
            if str(item.get("followup_state", "awaiting_ops_gate")) == "awaiting_ops_gate"
        ]
        return {
            "approved_for_proposal_count": len(approved),
            "awaiting_ops_gate_count": len(awaiting_ops_gate),
            "ops_gate_reviewed_count": sum(1 for item in approved if str(item.get("followup_state", "")) == "ops_gate_reviewed"),
        }

    def _execution_boundary(self, proposals: list[dict[str, Any]]) -> dict[str, Any]:
        ticket_count = sum(int(item.get("execution_ticket_count") or 0) for item in proposals)
        return {
            "execution_ticket_count": ticket_count,
            "actual_execute": any(bool(item.get("actual_execute", False)) for item in proposals),
        }

    def _feature_scoring(self, feature_scores: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "feature_score_count": len(feature_scores),
            "report_only": not any(
                bool(score.get("live_applied", False)) or bool(score.get("maturity_live_applied", False))
                for score in feature_scores
            ),
            "live_applied_count": sum(
                1
                for score in feature_scores
                if bool(score.get("live_applied", False)) or bool(score.get("maturity_live_applied", False))
            ),
        }
