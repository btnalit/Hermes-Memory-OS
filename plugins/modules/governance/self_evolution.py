"""Dry-run Self-Evolution Governor module for portable Hermes governance."""

from __future__ import annotations

import json
import hashlib
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
        proposal_shape = _proposal_shape(selected, evidence_scoring=evidence_scoring)
        cadence_day = _utc_day()
        cadence_input_fingerprint = _cadence_input_fingerprint(
            score_refs,
            proposal_shape=proposal_shape,
        )
        duplicate = _unresolved_self_evolution_duplicate(
            proposal_queue,
            score_refs,
            proposal_shape=proposal_shape,
        )
        if duplicate is not None:
            result = self._result(
                status="ok",
                proposal_created=False,
                proposal_id="",
                ops_gate_decision={},
                score_refs=score_refs,
                digest_ref=str(self.digest_path) if self.digest_path.exists() else "",
                reason="duplicate_unresolved_proposal",
                novelty_skipped=True,
                existing_proposal_id=str(duplicate.get("candidate_id") or ""),
                proposal_class=str(proposal_shape.get("proposal_class") or ""),
                dedupe_key=str(proposal_shape.get("dedupe_key") or ""),
                skipped=True,
                cadence_day=cadence_day,
                cadence_input_fingerprint=cadence_input_fingerprint,
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
        processed_proposal = _same_day_proposal_history_processed(
            proposal_queue,
            proposal_shape=proposal_shape,
            cadence_day=cadence_day,
        )
        if processed_proposal is not None:
            result = self._result(
                status="ok",
                proposal_created=False,
                proposal_id="",
                ops_gate_decision={},
                score_refs=score_refs,
                digest_ref=str(self.digest_path) if self.digest_path.exists() else "",
                reason="cadence_same_day_same_signal",
                proposal_class=str(proposal_shape.get("proposal_class") or ""),
                dedupe_key=str(proposal_shape.get("dedupe_key") or ""),
                skipped=True,
                cadence_skipped=True,
                cadence_day=cadence_day,
                cadence_input_fingerprint=cadence_input_fingerprint,
                previous_proposal_id=str(processed_proposal.get("candidate_id") or ""),
            )
            self._write_report(result)
            append_audit(
                store.roots.audit_path,
                action="self_evolution_dry_run_written",
                status="ok",
                target=str(self.reports_path),
                details={
                    "proposal_created": False,
                    "reason": "cadence_same_day_same_signal",
                    "previous_proposal_id": result.get("previous_proposal_id", ""),
                    "score_ref_count": len(score_refs),
                    "direct_self_modify": False,
                    "actual_execute": False,
                },
            )
            return result
        processed = _same_day_same_signal_processed(
            self.read_reports(),
            cadence_day=cadence_day,
            cadence_input_fingerprint=cadence_input_fingerprint,
        )
        if processed is not None:
            result = self._result(
                status="ok",
                proposal_created=False,
                proposal_id="",
                ops_gate_decision={},
                score_refs=score_refs,
                digest_ref=str(self.digest_path) if self.digest_path.exists() else "",
                reason="cadence_same_day_same_signal",
                proposal_class=str(proposal_shape.get("proposal_class") or ""),
                dedupe_key=str(proposal_shape.get("dedupe_key") or ""),
                skipped=True,
                cadence_skipped=True,
                cadence_day=cadence_day,
                cadence_input_fingerprint=cadence_input_fingerprint,
                previous_report_id=str(processed.get("report_id") or ""),
            )
            self._write_report(result)
            append_audit(
                store.roots.audit_path,
                action="self_evolution_dry_run_written",
                status="ok",
                target=str(self.reports_path),
                details={
                    "proposal_created": False,
                    "reason": "cadence_same_day_same_signal",
                    "score_ref_count": len(score_refs),
                    "direct_self_modify": False,
                    "actual_execute": False,
                },
            )
            return result
        digest = self._write_digest(selected, evidence_scoring=evidence_scoring)
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
            proposal = proposal_queue.create_candidate(
                store=store,
                title=proposal_shape["title"],
                body=proposal_shape["body"],
                source_refs=score_refs,
                kind=proposal_shape["kind"],
                proposal_class=str(proposal_shape.get("proposal_class") or ""),
                dedupe_key=str(proposal_shape.get("dedupe_key") or ""),
                proposal_quality=proposal_shape.get("proposal_quality")
                if isinstance(proposal_shape.get("proposal_quality"), dict)
                else None,
            )
            proposal_id = str(proposal["candidate_id"])

        result = self._result(
            status="ok",
            proposal_created=proposal_created,
            proposal_id=proposal_id,
            ops_gate_decision=gate_decision,
            score_refs=score_refs,
            digest_ref=str(digest),
            proposal_class=str(proposal_shape.get("proposal_class") or ""),
            dedupe_key=str(proposal_shape.get("dedupe_key") or ""),
            cadence_day=cadence_day,
            cadence_input_fingerprint=cadence_input_fingerprint,
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
            "cadence_skipped_count": sum(1 for report in reports if report.get("cadence_skipped")),
            "same_signal_skipped_count": sum(
                1 for report in reports if report.get("reason") == "cadence_same_day_same_signal"
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
        proposal_class: str = "",
        dedupe_key: str = "",
        skipped: bool = False,
        cadence_skipped: bool = False,
        cadence_day: str = "",
        cadence_input_fingerprint: str = "",
        previous_report_id: str = "",
        previous_proposal_id: str = "",
    ) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).isoformat()
        result = {
            "schema_version": "hermes.self_evolution_result.v0",
            "report_id": _stable_digest("|".join([self.profile, generated_at, ",".join(score_refs), reason])),
            "module": "self_evolution",
            "profile": self.profile,
            "generated_at": generated_at,
            "status": status,
            "execution_mode": self.execution_mode,
            "proposal_created": proposal_created,
            "proposal_id": proposal_id,
            "score_refs": list(score_refs),
            "digest_ref": digest_ref,
            "ops_gate_decision": dict(ops_gate_decision),
            "novelty_skipped": bool(novelty_skipped),
            "existing_proposal_id": existing_proposal_id,
            "proposal_class": proposal_class,
            "dedupe_key": dedupe_key,
            "skipped": bool(skipped),
            "cadence_skipped": bool(cadence_skipped),
            "cadence_day": cadence_day,
            "cadence_input_fingerprint": cadence_input_fingerprint,
            "previous_report_id": previous_report_id,
            "previous_proposal_id": previous_proposal_id,
            "direct_self_modify": False,
            "actual_execute": False,
        }
        if reason:
            result["reason"] = reason
        return result


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _cadence_input_fingerprint(score_refs: list[str], *, proposal_shape: dict[str, Any]) -> str:
    payload = {
        "score_refs": list(score_refs),
        "kind": str(proposal_shape.get("kind") or ""),
        "proposal_class": str(proposal_shape.get("proposal_class") or ""),
        "dedupe_key": str(proposal_shape.get("dedupe_key") or ""),
    }
    return _stable_digest(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _same_day_same_signal_processed(
    reports: list[dict[str, Any]],
    *,
    cadence_day: str,
    cadence_input_fingerprint: str,
) -> dict[str, Any] | None:
    if not cadence_day or not cadence_input_fingerprint:
        return None
    for report in reversed(reports):
        if str(report.get("cadence_day") or "") != cadence_day:
            continue
        if str(report.get("cadence_input_fingerprint") or "") != cadence_input_fingerprint:
            continue
        if report.get("proposal_created") is True:
            return report
        if report.get("novelty_skipped") is True:
            return report
        if report.get("cadence_skipped") is True:
            return report
    return None


def _same_day_proposal_history_processed(
    proposal_queue: Any,
    *,
    proposal_shape: dict[str, Any],
    cadence_day: str,
) -> dict[str, Any] | None:
    target_dedupe_key = str(proposal_shape.get("dedupe_key") or "")
    target_class = str(proposal_shape.get("proposal_class") or "")
    target_kind = str(proposal_shape.get("kind") or "")
    target_title = str(proposal_shape.get("title") or "")
    queue = proposal_queue.read_queue()
    for item in reversed(queue.get("items", [])):
        if not isinstance(item, dict):
            continue
        if _proposal_still_unresolved(item):
            continue
        if str(item.get("kind") or "") != target_kind:
            continue
        created_day = str(item.get("created_at") or "")[:10]
        updated_day = str(item.get("updated_at") or "")[:10]
        if cadence_day not in {created_day, updated_day}:
            continue
        if target_dedupe_key and str(item.get("dedupe_key") or "") == target_dedupe_key:
            return item
        if target_class and str(item.get("proposal_class") or "") == target_class:
            return item
        if target_title and str(item.get("title") or "") == target_title:
            return item
    return None


def _unresolved_self_evolution_duplicate(
    proposal_queue: Any,
    score_refs: list[str],
    *,
    proposal_shape: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    score_ref_set = set(score_refs)
    target_dedupe_key = str((proposal_shape or {}).get("dedupe_key") or "")
    target_class = str((proposal_shape or {}).get("proposal_class") or "")
    queue = proposal_queue.read_queue()
    for item in queue.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("kind") not in {"self_evolution", "expression_policy"}:
            continue
        if not _proposal_still_unresolved(item):
            continue
        if _legacy_template_proposal(item):
            continue
        if target_dedupe_key and str(item.get("dedupe_key") or "") == target_dedupe_key:
            return item
        if target_class and str(item.get("proposal_class") or "") == target_class:
            return item
        source_refs = {str(ref) for ref in item.get("source_refs") or []}
        if not source_refs or source_refs == score_ref_set:
            return item
        title = str(item.get("title") or "")
        if title in {"Self-Evolution dry-run proposal", "Tune right-brain expression policy"}:
            return item
    return None


def _proposal_still_unresolved(item: dict[str, Any]) -> bool:
    state = str(item.get("state") or "")
    followup_state = str(item.get("followup_state") or "")
    if state in {"owner_declined", "expired", "pressure_blocked"}:
        return False
    if followup_state in {"closed", "applied_expression_policy"}:
        return False
    return state in {"candidate", "owner_eligible", "owner_defer", "approved_for_proposal"}


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


def _proposal_shape(scores: list[dict[str, Any]], *, evidence_scoring: Any) -> dict[str, Any]:
    evidence_by_id = {
        str(record.get("evidence_id", "")): record
        for record in evidence_scoring.read_evidence()
        if isinstance(record, dict)
    }
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
    top_score = scores[0] if scores else {}
    top_summary = _score_summary(top_score, evidence_by_id=evidence_by_id)
    top_subject = str(top_score.get("subject_ref") or "unknown_subject")
    top_subject_kind = str(top_score.get("subject_kind") or "unknown")
    top_score_value = top_score.get("maturity_score", top_score.get("score", ""))
    evidence_line = _evidence_line(top_score, evidence_by_id=evidence_by_id)
    quality = _proposal_quality(top_score, trigger_rule="feature_maturity_top_signal")
    if ratings:
        rating = ratings[0]
        proposal_class = f"expression_policy:{_safe_key(rating)}"
        return {
            "kind": "expression_policy",
            "title": f"调整右脑表达策略：{rating} 反馈",
            "proposal_class": proposal_class,
            "dedupe_key": proposal_class,
            "proposal_quality": _proposal_quality(top_score, trigger_rule="expression_feedback_policy"),
            "body": _proposal_body(
                proposed_change=(
                    f"根据 owner 表达反馈 rating={rating}，形成一条右脑表达策略调整方案。"
                ),
                evidence=(
                    f"owner 标记右脑表达 {rating}; maturity_score={top_score_value}; summary={top_summary}"
                ),
                acceptance=(
                    "必须写清要改 prompt、cadence 还是 SpeakGate policy，owner 可见效果，"
                    "monitor 检查字段，以及 rollback/stop signal。"
                ),
                follow_up=(
                    "approved_for_proposal -> OpsGate report-only -> owner manual apply decision；"
                    "actual_execute=false."
                ),
            ),
        }
    title = _governance_title(top_score, top_summary=top_summary)
    proposal_class = f"self_evolution:{_safe_key(top_subject_kind)}"
    return {
        "kind": "self_evolution",
        "title": title,
        "proposal_class": proposal_class,
        "dedupe_key": f"{proposal_class}:{_stable_digest(top_subject)}",
        "proposal_quality": quality,
        "body": _proposal_body(
            proposed_change=(
                "基于最高成熟度信号创建一条有边界的治理 follow-up，替代泛化 dry-run item。"
            ),
            evidence=(
                f"subject={top_subject}; maturity_score={top_score_value}; summary={top_summary}"
            ),
            acceptance=(
                "必须写清具体模块或合同、monitor/test 证明、rollback/stop signal；"
                "不能直接应用运行时行为。"
            ),
            follow_up=(
                "approved_for_proposal -> OpsGate report-only -> owner/manual apply design；"
                "actual_execute=false."
            ),
        ),
    }


def _proposal_body(*, proposed_change: str, evidence: str, acceptance: str, follow_up: str) -> str:
    return "\n".join(
        [
            f"具体改动: {_bounded_line(proposed_change, 420)}",
            f"证据: {_bounded_line(evidence, 520)}",
            f"验收标准: {_bounded_line(acceptance, 520)}",
            f"后续状态: {_bounded_line(follow_up, 360)}",
            "边界: 这只是 proposal，不会直接改 prompt、route、send、schedule 或执行行为；后续必须另走显式 apply gate。",
        ]
    )


def _score_summary(score: dict[str, Any], *, evidence_by_id: dict[str, dict[str, Any]]) -> str:
    for evidence_ref in score.get("evidence_refs", []):
        evidence = evidence_by_id.get(str(evidence_ref), {})
        summary = _bounded_line(str(evidence.get("summary") or ""), 260)
        if summary:
            return summary
    return _bounded_line(str(score.get("feature_explanation") or score.get("explanation") or ""), 260)


def _evidence_line(score: dict[str, Any], *, evidence_by_id: dict[str, dict[str, Any]]) -> str:
    evidence_refs = [str(ref) for ref in score.get("evidence_refs", []) if str(ref)]
    source_refs: list[str] = []
    for evidence_ref in evidence_refs[:3]:
        record = evidence_by_id.get(evidence_ref, {})
        source_ref = str(record.get("source_ref") or "")
        if source_ref:
            source_refs.append(source_ref)
    parts = [f"score_ref={_score_ref(score)}"]
    if evidence_refs:
        parts.append("evidence_refs=" + ",".join(evidence_refs[:3]))
    if source_refs:
        parts.append("source_refs=" + ",".join(source_refs[:3]))
    return _bounded_line("; ".join(parts), 420)


def _governance_title(score: dict[str, Any], *, top_summary: str) -> str:
    subject_kind = str(score.get("subject_kind") or "governance")
    if top_summary:
        return _bounded_line(f"复核 {subject_kind} 治理信号：{top_summary}", 96)
    subject_ref = str(score.get("subject_ref") or "governance signal")
    return _bounded_line(f"复核 {subject_kind} 治理信号：{subject_ref}", 96)


def _bounded_line(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "..."


def _proposal_quality(score: dict[str, Any], *, trigger_rule: str) -> dict[str, Any]:
    evidence_refs = [str(ref) for ref in score.get("evidence_refs", []) if str(ref)]
    return {
        "trigger_rule": trigger_rule,
        "top_subject_ref": str(score.get("subject_ref") or ""),
        "top_subject_kind": str(score.get("subject_kind") or ""),
        "maturity_score": score.get("maturity_score", score.get("score", 0.0)),
        "evidence_ref_count": len(evidence_refs),
        "maturity_dimensions": score.get("maturity_dimensions")
        if isinstance(score.get("maturity_dimensions"), dict)
        else {},
    }


def _safe_key(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"_", "-", ":"} else "_" for ch in str(value or "").strip().lower())
    return clean.strip("_") or "unknown"


def _stable_digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
