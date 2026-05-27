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
        duplicate = report.get("duplicate_unresolved") if isinstance(report.get("duplicate_unresolved"), dict) else {}
        proposal_quality = report.get("proposal_quality") if isinstance(report.get("proposal_quality"), dict) else {}
        return {
            "schema_version": "hermes.memory_os.left_brain_pipeline_check_status.v0",
            "module": "left_brain_pipeline_check",
            "profile": self.profile,
            "status": report.get("status", "missing"),
            "finding_count": len(report.get("findings", [])) if isinstance(report.get("findings"), list) else 0,
            "active_duplicate_group_count": duplicate.get("active_duplicate_group_count"),
            "followup_duplicate_group_count": duplicate.get("followup_duplicate_group_count"),
            "legacy_template_duplicate_group_count": duplicate.get("legacy_template_duplicate_group_count"),
            "proposal_quality_missing_count": proposal_quality.get("quality_metadata_missing_count"),
            "expression_policy_quality_ready_count": proposal_quality.get("expression_policy_quality_ready_count"),
            "expression_policy_quality_blocked_count": proposal_quality.get("expression_policy_quality_blocked_count"),
            "expression_policy_unlinked_quality_count": proposal_quality.get("expression_policy_unlinked_quality_count"),
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
            "proposal_quality": self._proposal_quality(proposals),
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
            previous = self.read_latest()
            if previous and _stable_report(previous) == _stable_report(report):
                return {
                    **report,
                    "skipped": True,
                    "cadence_skipped": True,
                    "reason": "unchanged_pipeline_report",
                }
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
        if unresolved_duplicates["active_duplicate_group_count"]:
            findings.append(
                {
                    "severity": "warning",
                    "code": "duplicate_unresolved_proposals",
                    "message": "Multiple owner-actionable proposal candidates share the same class/dedupe key.",
                    "count": unresolved_duplicates["active_duplicate_group_count"],
                }
            )
        proposal_quality = self._proposal_quality(proposals)
        if proposal_quality["expression_policy_quality_blocked_count"]:
            findings.append(
                {
                    "severity": "warning",
                    "code": "expression_policy_proposal_quality_gap",
                    "message": "Owner-actionable expression_policy proposals must reference linked expression feedback and stay bounded to explicit apply.",
                    "count": proposal_quality["expression_policy_quality_blocked_count"],
                }
            )
        if proposal_quality["quality_metadata_missing_count"]:
            findings.append(
                {
                    "severity": "warning",
                    "code": "proposal_quality_metadata_missing",
                    "message": "Owner-actionable non-legacy proposals should carry proposal_quality metadata.",
                    "count": proposal_quality["quality_metadata_missing_count"],
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
        active_groups: dict[str, list[str]] = {}
        followup_groups: dict[str, list[str]] = {}
        legacy_template_groups: dict[str, list[str]] = {}
        resolved_or_terminal_skipped_count = 0
        for item in proposals:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", ""))
            if not candidate_id:
                continue
            if _proposal_resolved_or_terminal(item):
                resolved_or_terminal_skipped_count += 1
                continue
            key = _proposal_duplicate_key(item)
            if _legacy_template_proposal(item):
                legacy_template_groups.setdefault(key, []).append(candidate_id)
                continue
            state = str(item.get("state", "candidate"))
            if state in {"candidate", "owner_eligible", "owner_defer"}:
                active_groups.setdefault(key, []).append(candidate_id)
            elif state == "approved_for_proposal":
                followup_groups.setdefault(key, []).append(candidate_id)
        active_duplicates = _duplicate_groups(active_groups)
        followup_duplicates = _duplicate_groups(followup_groups)
        legacy_template_duplicates = _duplicate_groups(legacy_template_groups)
        return {
            "duplicate_group_count": len(active_duplicates),
            "duplicate_candidate_count": sum(len(ids) for ids in active_duplicates.values()),
            "active_duplicate_group_count": len(active_duplicates),
            "active_duplicate_candidate_count": sum(len(ids) for ids in active_duplicates.values()),
            "followup_duplicate_group_count": len(followup_duplicates),
            "followup_duplicate_candidate_count": sum(len(ids) for ids in followup_duplicates.values()),
            "legacy_template_duplicate_group_count": len(legacy_template_duplicates),
            "legacy_template_duplicate_candidate_count": sum(len(ids) for ids in legacy_template_duplicates.values()),
            "resolved_or_terminal_skipped_count": resolved_or_terminal_skipped_count,
            "grouping": "dedupe_key_or_proposal_class_with_title_fallback",
        }

    def _proposal_quality(self, proposals: list[dict[str, Any]]) -> dict[str, Any]:
        owner_actionable = [
            item
            for item in proposals
            if isinstance(item, dict)
            and not _proposal_resolved_or_terminal(item)
            and not _legacy_template_proposal(item)
            and str(item.get("state", "candidate")) in {"candidate", "owner_eligible", "owner_defer"}
        ]
        quality_missing = [item for item in owner_actionable if not isinstance(item.get("proposal_quality"), dict)]
        concrete_body_missing = [item for item in owner_actionable if not _has_concrete_body(str(item.get("body") or ""))]
        expression_policy_items = [
            item
            for item in owner_actionable
            if str(item.get("kind") or "") == "expression_policy"
            or str(item.get("proposal_class") or "").startswith("expression_policy:")
        ]
        expression_policy_ready: list[dict[str, Any]] = []
        expression_policy_blocked: list[dict[str, Any]] = []
        expression_policy_unlinked = 0
        for item in expression_policy_items:
            quality = item.get("proposal_quality") if isinstance(item.get("proposal_quality"), dict) else {}
            linked_outcome_count = int(quality.get("linked_outcome_count") or 0)
            is_unlinked = linked_outcome_count <= 0
            if is_unlinked:
                expression_policy_unlinked += 1
            ready = (
                str(quality.get("quality_gate") or "") == "linked_expression_feedback"
                and linked_outcome_count > 0
                and str(quality.get("runtime_target") or "") == "expression_policy"
                and quality.get("direct_apply_allowed") is False
                and quality.get("generic_executor_allowed") is False
                and _has_concrete_body(str(item.get("body") or ""))
            )
            if ready:
                expression_policy_ready.append(item)
            else:
                expression_policy_blocked.append(item)
        return {
            "owner_actionable_proposal_count": len(owner_actionable),
            "quality_metadata_missing_count": len(quality_missing),
            "concrete_body_missing_count": len(concrete_body_missing),
            "expression_policy_count": len(expression_policy_items),
            "expression_policy_quality_ready_count": len(expression_policy_ready),
            "expression_policy_quality_blocked_count": len(expression_policy_blocked),
            "expression_policy_unlinked_quality_count": expression_policy_unlinked,
            "runtime_target_expression_policy_count": sum(
                1
                for item in expression_policy_items
                if isinstance(item.get("proposal_quality"), dict)
                and str(item["proposal_quality"].get("runtime_target") or "") == "expression_policy"
            ),
            "actual_execute": False,
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


def _proposal_resolved_or_terminal(item: dict[str, Any]) -> bool:
    state = str(item.get("state", ""))
    followup_state = str(item.get("followup_state", ""))
    if state in {"owner_declined", "expired", "pressure_blocked"}:
        return True
    return followup_state in {"closed", "applied_expression_policy"}


def _proposal_duplicate_key(item: dict[str, Any]) -> str:
    dedupe_key = " ".join(str(item.get("dedupe_key") or "").lower().split())
    if dedupe_key:
        return f"dedupe:{dedupe_key}"
    proposal_class = " ".join(str(item.get("proposal_class") or "").lower().split())
    if proposal_class:
        return f"class:{proposal_class}"
    return "|".join(
        [
            str(item.get("kind") or "proposal"),
            " ".join(str(item.get("title") or "").lower().split()),
        ]
    )


def _legacy_template_proposal(item: dict[str, Any]) -> bool:
    title = str(item.get("title") or "")
    body = " ".join(str(item.get("body") or "").split())
    if "Proposed change:" in body and "Acceptance criteria:" in body:
        return False
    if "具体改动:" in body and "验收标准:" in body:
        return False
    if title == "Self-Evolution dry-run proposal":
        return True
    if title == "Tune right-brain expression policy" and "prompt/cadence/policy proposal" in body:
        return True
    return False


def _has_concrete_body(body: str) -> bool:
    compact = " ".join(str(body or "").split())
    return (
        ("具体改动:" in compact and "验收标准:" in compact)
        or ("Proposed change:" in compact and "Acceptance criteria:" in compact)
    )


def _duplicate_groups(groups: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: ids for key, ids in groups.items() if len(ids) > 1}


def _stable_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"skipped", "cadence_skipped", "reason"}
    }
