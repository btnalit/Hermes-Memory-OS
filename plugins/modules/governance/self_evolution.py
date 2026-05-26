"""Dry-run Self-Evolution Governor module for portable Hermes governance."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.store import MemoryOSStore


def self_evolution_manifest() -> dict[str, Any]:
    """Return the v0.1 Self-Evolution Governor module manifest."""

    return {
        "name": "self_evolution",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler", "ops_gate", "proposal_queue", "evidence_scoring"],
            "optional": ["speak_gate"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["self_evolution_dry_run"],
            "reads": ["local_artifact.evidence_scoring", "local_artifact.proposal_queue_state"],
            "writes": ["memory_os.audit", "local_artifact.self_evolution_digest", "local_artifact.proposal_queue_state"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
        "memory_os_compat": {
            "min_version": "0.1.0",
            "max_version": "0.2.x",
            "schema_versions": {
                "event": ["memory-os.event.v0"],
                "working": ["memory-os.working.v0"],
                "crystallized": ["memory-os.crystallized.v0"],
            },
        },
    }


class SelfEvolutionGovernorModule:
    """Generate dry-run evolution proposals from explainable evidence scores."""

    def __init__(self, hermes_home: str | Path, *, profile: str, execution_mode: str = "dry-run") -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile
        self.execution_mode = execution_mode

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "self_evolution"

    @property
    def digest_path(self) -> Path:
        return self.module_root / "runtime_digest.md"

    @property
    def reports_path(self) -> Path:
        return self.module_root / "reports.jsonl"

    def run_once(
        self,
        *,
        store: MemoryOSStore,
        ops_gate: Any,
        proposal_queue: Any,
        evidence_scoring: Any,
    ) -> dict[str, Any]:
        store.initialize()
        scores = sorted(
            _primary_governance_scores(evidence_scoring),
            key=lambda item: (-float(item.get("maturity_score", item.get("score", 0.0))), str(item.get("subject_ref", ""))),
        )
        if not scores:
            result = self._result(
                status="warning",
                proposal_created=False,
                proposal_id="",
                ops_gate_decision={},
                score_refs=[],
                reason="no_scores",
            )
            self._write_report(result)
            append_audit(
                store.roots.audit_path,
                action="self_evolution_dry_run_written",
                status="warning",
                target=str(self.reports_path),
                details={"proposal_created": False, "reason": "no_scores"},
            )
            return result

        selected = scores[:3]
        score_refs = [_score_ref(score) for score in selected]
        digest = self._write_digest(selected, evidence_scoring=evidence_scoring)
        duplicate = _unresolved_self_evolution_duplicate(proposal_queue, score_refs)
        if duplicate is not None:
            result = self._result(
                status="ok",
                proposal_created=False,
                proposal_id="",
                ops_gate_decision={},
                score_refs=score_refs,
                digest_ref=str(digest),
                reason="duplicate_unresolved_proposal",
                novelty_skipped=True,
                existing_proposal_id=str(duplicate.get("candidate_id") or ""),
            )
            self._write_report(result)
            append_audit(
                store.roots.audit_path,
                action="self_evolution_dry_run_written",
                status="ok",
                target=str(self.reports_path),
                details={
                    "proposal_created": False,
                    "reason": "duplicate_unresolved_proposal",
                    "existing_proposal_id": result.get("existing_proposal_id", ""),
                    "score_ref_count": len(score_refs),
                    "direct_self_modify": False,
                    "actual_execute": False,
                },
            )
            return result
        gate_result = ops_gate.run_once(
            store=store,
            proposed_actions=[
                {
                    "id": "self-evolution-proposal",
                    "kind": "proposal_create",
                    "target": "proposal_queue:self_evolution",
                }
            ],
        )
        gate_decision = gate_result.get("decisions", [{}])[0] if gate_result.get("decisions") else {}
        proposal_created = gate_decision.get("decision") == "would_allow"
        proposal_id = ""
        if proposal_created:
            proposal_shape = _proposal_shape(selected)
            proposal = proposal_queue.create_candidate(
                store=store,
                title=proposal_shape["title"],
                body=proposal_shape["body"],
                source_refs=score_refs,
                kind=proposal_shape["kind"],
            )
            proposal_id = str(proposal["candidate_id"])

        result = self._result(
            status="ok",
            proposal_created=proposal_created,
            proposal_id=proposal_id,
            ops_gate_decision=gate_decision,
            score_refs=score_refs,
            digest_ref=str(digest),
        )
        self._write_report(result)
        append_audit(
            store.roots.audit_path,
            action="self_evolution_dry_run_written",
            status="ok",
            target=str(self.reports_path),
            details={
                "proposal_created": proposal_created,
                "proposal_id": proposal_id,
                "score_ref_count": len(score_refs),
                "direct_self_modify": False,
                "actual_execute": False,
            },
        )
        return result

    def status(self) -> dict[str, Any]:
        reports = self.read_reports()
        last = reports[-1] if reports else {}
        return {
            "schema_version": "hermes.self_evolution_status.v0",
            "module": "self_evolution",
            "profile": self.profile,
            "execution_mode": self.execution_mode,
            "digest_exists": self.digest_path.exists(),
            "report_count": len(reports),
            "proposal_count": sum(1 for report in reports if report.get("proposal_created")),
            "novelty_skipped_count": sum(1 for report in reports if report.get("novelty_skipped")),
            "duplicate_unresolved_proposal_count": sum(
                1 for report in reports if report.get("reason") == "duplicate_unresolved_proposal"
            ),
            "last_status": str(last.get("status", "missing")),
            "direct_self_modify": False,
            "actual_execute": False,
        }

    def doctor(
        self,
        *,
        ops_gate: Any | None = None,
        proposal_queue: Any | None = None,
        evidence_scoring: Any | None = None,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        missing = [
            name
            for name, dependency in (
                ("ops_gate", ops_gate),
                ("proposal_queue", proposal_queue),
                ("evidence_scoring", evidence_scoring),
            )
            if dependency is None
        ]
        if missing:
            findings.append(
                {
                    "severity": "error",
                    "code": "missing_required_runtime_dependency",
                    "message": "Missing runtime dependency: " + ", ".join(missing),
                }
            )
        elif not self.digest_path.exists():
            findings.append(
                {
                    "severity": "warning",
                    "code": "runtime_digest_missing",
                    "message": "No Self-Evolution runtime digest has been written yet",
                }
            )
        if any(finding["severity"] == "error" for finding in findings):
            status = "error"
        elif findings:
            status = "warning"
        else:
            status = "ok"
        return {
            "schema_version": "hermes.self_evolution_doctor.v0",
            "module": "self_evolution",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }

    def read_reports(self) -> list[dict[str, Any]]:
        if not self.reports_path.exists():
            return []
        reports: list[dict[str, Any]] = []
        for line in self.reports_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    reports.append(parsed)
        return reports

    def _write_digest(self, scores: list[dict[str, Any]], *, evidence_scoring: Any) -> Path:
        evidence_by_id = {
            str(record.get("evidence_id", "")): str(record.get("summary", ""))
            for record in evidence_scoring.read_evidence()
        }
        lines = [
            "# Self-Evolution Runtime Digest",
            "",
            f"generated_at: {datetime.now(timezone.utc).isoformat()}",
            f"profile: {self.profile}",
            "mode: dry-run",
            "",
            "## Evidence Signals",
            "",
        ]
        for score in scores:
            score_value = score.get("maturity_score", score.get("score", ""))
            lines.append(
                f"- {score['subject_ref']} maturity_score={score_value}: {score.get('feature_explanation') or score.get('explanation', '')}"
            )
            for evidence_ref in score.get("evidence_refs", []):
                lines.append(f"  - evidence_ref: {evidence_ref}")
                summary = evidence_by_id.get(str(evidence_ref), "")
                if summary:
                    lines.append(f"    summary: {summary}")
        self.digest_path.parent.mkdir(parents=True, exist_ok=True)
        self.digest_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return self.digest_path

    def _write_report(self, result: dict[str, Any]) -> None:
        self.reports_path.parent.mkdir(parents=True, exist_ok=True)
        with self.reports_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _result(
        self,
        *,
        status: str,
        proposal_created: bool,
        proposal_id: str,
        ops_gate_decision: dict[str, Any],
        score_refs: list[str],
        digest_ref: str = "",
        reason: str = "",
        novelty_skipped: bool = False,
        existing_proposal_id: str = "",
    ) -> dict[str, Any]:
        result = {
            "schema_version": "hermes.self_evolution_result.v0",
            "module": "self_evolution",
            "profile": self.profile,
            "status": status,
            "execution_mode": self.execution_mode,
            "proposal_created": proposal_created,
            "proposal_id": proposal_id,
            "score_refs": list(score_refs),
            "digest_ref": digest_ref,
            "ops_gate_decision": dict(ops_gate_decision),
            "novelty_skipped": bool(novelty_skipped),
            "existing_proposal_id": existing_proposal_id,
            "direct_self_modify": False,
            "actual_execute": False,
        }
        if reason:
            result["reason"] = reason
        return result


def _unresolved_self_evolution_duplicate(proposal_queue: Any, score_refs: list[str]) -> dict[str, Any] | None:
    unresolved_states = {"candidate", "owner_eligible", "owner_defer", "approved_for_proposal"}
    score_ref_set = set(score_refs)
    queue = proposal_queue.read_queue()
    for item in queue.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("kind") not in {"self_evolution", "expression_policy"}:
            continue
        if str(item.get("state") or "") not in unresolved_states:
            continue
        source_refs = {str(ref) for ref in item.get("source_refs") or []}
        if not source_refs or source_refs == score_ref_set:
            return item
        title = str(item.get("title") or "")
        if title in {"Self-Evolution dry-run proposal", "Tune right-brain expression policy"}:
            return item
    return None


def _primary_governance_scores(evidence_scoring: Any) -> list[dict[str, Any]]:
    feature_scores = list(evidence_scoring.read_feature_scores())
    if feature_scores:
        return feature_scores
    return list(evidence_scoring.read_scores())


def _score_ref(score: dict[str, Any]) -> str:
    feature_id = str(score.get("feature_score_id") or "")
    if feature_id:
        return f"feature_score:{feature_id}"
    return f"score:{score['score_id']}"


def _proposal_shape(scores: list[dict[str, Any]]) -> dict[str, str]:
    ratings = [
        str(
            score.get("maturity_dimensions", {})
            .get("owner_feedback", {})
            .get("signals", {})
            .get("feedback_rating", "")
        )
        for score in scores
        if str(score.get("subject_kind") or "") == "expression_feedback"
    ]
    ratings = [rating for rating in ratings if rating and rating != "none"]
    if ratings:
        rating = ratings[0]
        return {
            "kind": "expression_policy",
            "title": "Tune right-brain expression policy",
            "body": (
                "Create a prompt/cadence/policy proposal for right-brain expression based on "
                f"owner expression feedback rating={rating}. This is proposal-only: do not "
                "change prompts, cadence, SpeakGate policy, or delivery behavior without a later apply gate."
            ),
        }
    return {
        "kind": "self_evolution",
        "title": "Self-Evolution dry-run proposal",
        "body": "Use the highest feature-maturity evidence signal to prepare a reviewed governance improvement.",
    }
