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

    @property
    def agenda_candidates_path(self) -> Path:
        return self.module_root / "agenda_candidates.jsonl"

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

        cadence_day = _utc_day()
        reports = self.read_reports()
        selected: list[dict[str, Any]] = []
        score_refs: list[str] = []
        proposal_shape: dict[str, Any] = {}
        cadence_input_fingerprint = ""
        agenda_candidate: dict[str, Any] = {}
        blocked_attempt: dict[str, Any] | None = None
        for attempt_scores, attempt_shape in _proposal_shape_options(scores, evidence_scoring=evidence_scoring):
            attempt_refs = [_score_ref(score) for score in attempt_scores]
            attempt_fingerprint = _cadence_input_fingerprint(
                attempt_refs,
                proposal_shape=attempt_shape,
            )
            attempt_agenda = _agenda_candidate(
                self.profile,
                scores=attempt_scores,
                score_refs=attempt_refs,
                proposal_shape=attempt_shape,
                cadence_day=cadence_day,
                cadence_input_fingerprint=attempt_fingerprint,
            )
            blocked = _proposal_attempt_blocker(
                proposal_queue=proposal_queue,
                reports=reports,
                score_refs=attempt_refs,
                proposal_shape=attempt_shape,
                cadence_day=cadence_day,
                cadence_input_fingerprint=attempt_fingerprint,
            )
            if blocked is not None:
                if blocked_attempt is None:
                    blocked_attempt = {
                        **blocked,
                        "selected": attempt_scores,
                        "score_refs": attempt_refs,
                        "proposal_shape": attempt_shape,
                        "cadence_input_fingerprint": attempt_fingerprint,
                        "agenda_candidate": attempt_agenda,
                    }
                continue
            selected = attempt_scores
            score_refs = attempt_refs
            proposal_shape = attempt_shape
            cadence_input_fingerprint = attempt_fingerprint
            agenda_candidate = attempt_agenda
            break
        if not proposal_shape and blocked_attempt is not None:
            return self._write_blocked_attempt_result(store, cadence_day=cadence_day, blocked_attempt=blocked_attempt)
        if not proposal_shape:
            selected = scores[:3]
            score_refs = [_score_ref(score) for score in selected]
            proposal_shape = _proposal_shape(selected, evidence_scoring=evidence_scoring)
            cadence_input_fingerprint = _cadence_input_fingerprint(score_refs, proposal_shape=proposal_shape)
            agenda_candidate = _agenda_candidate(
                self.profile,
                scores=selected,
                score_refs=score_refs,
                proposal_shape=proposal_shape,
                cadence_day=cadence_day,
                cadence_input_fingerprint=cadence_input_fingerprint,
            )
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
        agenda_record = _agenda_candidate_status(
            agenda_candidate,
            status="promoted_to_proposal" if proposal_created else "blocked_by_ops_gate",
            promotion_allowed=bool(proposal_created),
            reason="" if proposal_created else str(gate_decision.get("reason") or "ops_gate_not_allowed"),
        )
        if proposal_created:
            proposal_quality = proposal_shape.get("proposal_quality")
            if isinstance(proposal_quality, dict):
                proposal_quality = _proposal_quality_with_agenda(proposal_quality, agenda_record)
            proposal = proposal_queue.create_candidate(
                store=store,
                title=proposal_shape["title"],
                body=proposal_shape["body"],
                source_refs=score_refs,
                kind=proposal_shape["kind"],
                proposal_class=str(proposal_shape.get("proposal_class") or ""),
                dedupe_key=str(proposal_shape.get("dedupe_key") or ""),
                proposal_quality=proposal_quality,
            )
            proposal_id = str(proposal["candidate_id"])
            agenda_record = dict(agenda_record)
            agenda_record["proposal_id"] = proposal_id
        self._write_agenda_candidate(agenda_record)

        # ── Knob tune proposals ─────────────────────────────────────────────
        # Generate knob_tune proposals for overridable non-meta knobs and
        # auto-approve+enact those that pass the 3-condition gate.
        from plugins.memory.memory_os.knob_overrides import knob_override_auto_approvable
        from plugins.memory.memory_os.knob_overrides import register_override as ko_register
        from plugins.memory.memory_os.audit import append_audit as aud_append
        from datetime import timedelta

        knob_tunes = self._knob_tune_proposals()
        for kt in knob_tunes:
            gate_result_knob = ops_gate.run_once(
                store=store,
                proposed_actions=[
                    {
                        "id": f"knob-tune-{kt['knob']}",
                        "kind": "knob_tune",
                        "target": f"knob_overrides:{kt['knob']}",
                        "details": kt,
                    }
                ],
            )
            if knob_override_auto_approvable(kt["knob"], kt["to"]):
                now = datetime.now(timezone.utc)
                expires = (now + timedelta(days=7)).isoformat()
                try:
                    ko_register(
                        kt["knob"], kt["to"],
                        prior=kt["from"],
                        proposed_by="self_evolution",
                        approved_via="resolver",
                        expires_at=expires,
                    )
                    aud_append(
                        store.roots.audit_path,
                        action="knob_override_registered",
                        status="ok",
                        target=f"knob:{kt['knob']}",
                        details={"from": kt["from"], "to": kt["to"], "approved_via": "resolver"},
                    )
                except ValueError:
                    pass  # bounds/meta guard rejected

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
            agenda_candidate=agenda_record,
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
        agenda_candidates = self.read_agenda_candidates()
        latest_agenda = agenda_candidates[-1] if agenda_candidates else {}
        return {
            "schema_version": "hermes.self_evolution_status.v0",
            "module": "self_evolution",
            "profile": self.profile,
            "execution_mode": self.execution_mode,
            "digest_exists": self.digest_path.exists(),
            "agenda_candidate_count": len(agenda_candidates),
            "agenda_candidate_promoted_count": sum(
                1 for item in agenda_candidates if item.get("status") == "promoted_to_proposal"
            ),
            "agenda_candidate_blocked_count": sum(
                1 for item in agenda_candidates if item.get("promotion_allowed") is False
            ),
            "agenda_candidate_ready_count": sum(
                1 for item in agenda_candidates if item.get("promotion_allowed") is True
            ),
            "latest_agenda_candidate_status": str(latest_agenda.get("status", "")),
            "report_count": len(reports),
            "proposal_count": sum(1 for report in reports if report.get("proposal_created")),
            "novelty_skipped_count": sum(1 for report in reports if report.get("novelty_skipped")),
            "proposal_quality_gate_failed_count": sum(
                1 for report in reports if report.get("proposal_quality_gate_failed") is True
            ),
            "duplicate_unresolved_proposal_count": sum(
                1 for report in reports if report.get("reason") == "duplicate_unresolved_proposal"
            ),
            "cadence_skipped_count": sum(1 for report in reports if report.get("cadence_skipped")),
            "same_signal_skipped_count": sum(
                1 for report in reports if report.get("reason") == "cadence_same_day_same_signal"
            ),
            "last_quality_gate_reason": str(last.get("quality_gate_reason") or ""),
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

    def read_agenda_candidates(self) -> list[dict[str, Any]]:
        if not self.agenda_candidates_path.exists():
            return []
        candidates: list[dict[str, Any]] = []
        for line in self.agenda_candidates_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    candidates.append(parsed)
        return candidates

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

    def _write_agenda_candidate(self, candidate: dict[str, Any]) -> None:
        self.agenda_candidates_path.parent.mkdir(parents=True, exist_ok=True)
        with self.agenda_candidates_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(candidate, ensure_ascii=False, sort_keys=True))
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
        proposal_quality_gate_failed: bool = False,
        quality_gate_reason: str = "",
        proposal_quality: dict[str, Any] | None = None,
        agenda_candidate: dict[str, Any] | None = None,
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
            "proposal_quality_gate_failed": bool(proposal_quality_gate_failed),
            "quality_gate_reason": quality_gate_reason,
            "direct_self_modify": False,
            "actual_execute": False,
        }
        if agenda_candidate:
            result["agenda_candidate_id"] = str(agenda_candidate.get("agenda_candidate_id") or "")
            result["agenda_candidate_status"] = str(agenda_candidate.get("status") or "")
            result["agenda_promotion_allowed"] = bool(agenda_candidate.get("promotion_allowed"))
            result["agenda_promotion_block_reason"] = str(agenda_candidate.get("reason") or "")
        if proposal_quality is not None:
            result["proposal_quality"] = dict(proposal_quality)
        if reason:
            result["reason"] = reason
        return result

    def _knob_tune_proposals(self) -> list[dict[str, Any]]:
        """Generate knob_tune proposals for overridable non-meta knobs.

        First cut: propose current value (to=from, a no-change) — validates
        the auto-approve+enact mechanism without changing production behavior.
        The tuning strategy evolves later.
        """
        from plugins.memory.memory_os.knob_overrides import (
            OVERRIDABLE_KNOBS,
            resolve_knob,
        )

        proposals: list[dict[str, Any]] = []
        for knob_name, spec in OVERRIDABLE_KNOBS.items():
            if spec.get("meta") is True:
                continue
            current = resolve_knob(knob_name, default=spec["default"])
            bounds = spec.get("bounds", [])
            if not bounds:
                continue

            proposals.append({
                "kind": "knob_tune",
                "knob": knob_name,
                "from": current,
                "to": current,
                "bounds": bounds,
                "module": spec.get("module", ""),
            })
        return proposals

    def _write_blocked_attempt_result(
        self,
        store: MemoryOSStore,
        *,
        cadence_day: str,
        blocked_attempt: dict[str, Any],
    ) -> dict[str, Any]:
        proposal_shape = (
            blocked_attempt.get("proposal_shape") if isinstance(blocked_attempt.get("proposal_shape"), dict) else {}
        )
        agenda_candidate = (
            blocked_attempt.get("agenda_candidate")
            if isinstance(blocked_attempt.get("agenda_candidate"), dict)
            else {}
        )
        score_refs = [str(ref) for ref in blocked_attempt.get("score_refs", [])]
        reason = str(blocked_attempt.get("reason") or "")
        agenda_reason = (
            str(blocked_attempt.get("quality_gate_reason") or "")
            if reason == "proposal_quality_gate_failed"
            else reason
        )
        status = str(blocked_attempt.get("agenda_status") or "blocked_quality_gate")
        agenda_record = _agenda_candidate_status(
            agenda_candidate,
            status=status,
            promotion_allowed=False,
            reason=agenda_reason,
            existing_proposal_id=str(blocked_attempt.get("existing_proposal_id") or ""),
            previous_report_id=str(blocked_attempt.get("previous_report_id") or ""),
            previous_proposal_id=str(blocked_attempt.get("previous_proposal_id") or ""),
        )
        self._write_agenda_candidate(agenda_record)
        result = self._result(
            status="ok",
            proposal_created=False,
            proposal_id="",
            ops_gate_decision={},
            score_refs=score_refs,
            digest_ref=str(self.digest_path) if self.digest_path.exists() else "",
            reason=reason,
            novelty_skipped=reason == "duplicate_unresolved_proposal",
            existing_proposal_id=str(blocked_attempt.get("existing_proposal_id") or ""),
            proposal_class=str(proposal_shape.get("proposal_class") or ""),
            dedupe_key=str(proposal_shape.get("dedupe_key") or ""),
            skipped=True,
            cadence_skipped=reason == "cadence_same_day_same_signal",
            cadence_day=cadence_day,
            cadence_input_fingerprint=str(blocked_attempt.get("cadence_input_fingerprint") or ""),
            previous_report_id=str(blocked_attempt.get("previous_report_id") or ""),
            previous_proposal_id=str(blocked_attempt.get("previous_proposal_id") or ""),
            proposal_quality_gate_failed=reason == "proposal_quality_gate_failed",
            quality_gate_reason=str(blocked_attempt.get("quality_gate_reason") or ""),
            proposal_quality=proposal_shape.get("proposal_quality")
            if isinstance(proposal_shape.get("proposal_quality"), dict)
            else None,
            agenda_candidate=agenda_record,
        )
        self._write_report(result)
        append_audit(
            store.roots.audit_path,
            action="self_evolution_dry_run_written",
            status="ok",
            target=str(self.reports_path),
            details={
                "proposal_created": False,
                "reason": reason,
                "existing_proposal_id": result.get("existing_proposal_id", ""),
                "previous_report_id": result.get("previous_report_id", ""),
                "previous_proposal_id": result.get("previous_proposal_id", ""),
                "quality_gate_reason": result.get("quality_gate_reason", ""),
                "score_ref_count": len(score_refs),
                "direct_self_modify": False,
                "actual_execute": False,
            },
        )
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


def _agenda_candidate(
    profile: str,
    *,
    scores: list[dict[str, Any]],
    score_refs: list[str],
    proposal_shape: dict[str, Any],
    cadence_day: str,
    cadence_input_fingerprint: str,
) -> dict[str, Any]:
    top_score = scores[0] if scores else {}
    quality = proposal_shape.get("proposal_quality") if isinstance(proposal_shape.get("proposal_quality"), dict) else {}
    maturity_dimensions = quality.get("maturity_dimensions") if isinstance(quality.get("maturity_dimensions"), dict) else {}
    agenda_key = "|".join(
        [
            profile,
            str(proposal_shape.get("kind") or ""),
            str(proposal_shape.get("proposal_class") or ""),
            str(proposal_shape.get("dedupe_key") or ""),
            cadence_input_fingerprint,
        ]
    )
    return {
        "schema_version": "hermes.self_evolution_agenda_candidate.v0",
        "agenda_candidate_id": f"agc_{_stable_digest(agenda_key)}",
        "profile": profile,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_module": "self_evolution",
        "candidate_kind": str(proposal_shape.get("kind") or ""),
        "title": _bounded_line(str(proposal_shape.get("title") or ""), 140),
        "proposal_class": str(proposal_shape.get("proposal_class") or ""),
        "dedupe_key": str(proposal_shape.get("dedupe_key") or ""),
        "signal_refs": list(score_refs),
        "top_subject_ref": str(top_score.get("subject_ref") or quality.get("top_subject_ref") or ""),
        "top_subject_kind": str(top_score.get("subject_kind") or quality.get("top_subject_kind") or ""),
        "maturity_score": quality.get("maturity_score", top_score.get("maturity_score", top_score.get("score", 0.0))),
        "maturity_dimensions": maturity_dimensions,
        "evidence_ref_count": int(quality.get("evidence_ref_count") or 0),
        "trigger_rule": str(quality.get("trigger_rule") or ""),
        "quality_gate": str(quality.get("quality_gate") or "feature_maturity_top_signal"),
        "runtime_target": str(quality.get("runtime_target") or "governance_followup_review"),
        "cadence_day": cadence_day,
        "cadence_input_fingerprint": cadence_input_fingerprint,
        "direct_apply_allowed": False,
        "generic_executor_allowed": False,
        "actual_execute": False,
    }


def _agenda_candidate_status(
    candidate: dict[str, Any],
    *,
    status: str,
    promotion_allowed: bool,
    reason: str = "",
    existing_proposal_id: str = "",
    previous_report_id: str = "",
    previous_proposal_id: str = "",
) -> dict[str, Any]:
    result = dict(candidate)
    result.update(
        {
            "status": status,
            "promotion_allowed": bool(promotion_allowed),
            "reason": _bounded_line(reason, 180),
            "existing_proposal_id": existing_proposal_id,
            "previous_report_id": previous_report_id,
            "previous_proposal_id": previous_proposal_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "actual_execute": False,
        }
    )
    return result


def _proposal_quality_with_agenda(quality: dict[str, Any], agenda_candidate: dict[str, Any]) -> dict[str, Any]:
    result = dict(quality)
    result.update(
        {
            "agenda_candidate_id": str(agenda_candidate.get("agenda_candidate_id") or ""),
            "agenda_promotion_status": str(agenda_candidate.get("status") or ""),
            "agenda_maturity_gate": str(agenda_candidate.get("quality_gate") or ""),
            "agenda_candidate_evidence_ref_count": int(agenda_candidate.get("evidence_ref_count") or 0),
        }
    )
    return result


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
        if report.get("proposal_quality_gate_failed") is True:
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
        if item.get("kind") not in {"self_evolution", "expression_policy", "memory_sources_policy"}:
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
    if followup_state in {"closed", "applied_expression_policy", "applied_memory_sources_policy"}:
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


def _proposal_shape_options(
    scores: list[dict[str, Any]],
    *,
    evidence_scoring: Any,
) -> list[tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Return mature agenda attempts in score order.

    The governor should not stop forever on the highest-scoring signal when
    that signal already produced a proposal today. This keeps the pipeline
    moving to the next concrete signal while preserving score-order priority.
    """

    evidence_by_id = {
        str(record.get("evidence_id", "")): record
        for record in evidence_scoring.read_evidence()
        if isinstance(record, dict)
    }
    attempts: list[list[dict[str, Any]]] = []
    seen_keys: set[str] = set()
    feedback_attempt_seen = False
    for score in scores:
        before_count = len(attempts)
        subject_kind = str(score.get("subject_kind") or "")
        key = ""
        if subject_kind == "expression_feedback":
            rating = _score_feedback_rating(score, evidence_by_id=evidence_by_id)
            if rating:
                key = f"expression_feedback:{rating}"
                grouped = _scores_for_feedback(scores, evidence_by_id=evidence_by_id, subject_kind=subject_kind, rating=rating)
                attempts.append(grouped[:3])
                feedback_attempt_seen = True
        elif subject_kind == "memory_sources_feedback":
            rating = _score_feedback_rating(score, evidence_by_id=evidence_by_id)
            route = _score_evidence_field(score, evidence_by_id=evidence_by_id, field="route") or "unknown"
            query_class = _score_evidence_field(score, evidence_by_id=evidence_by_id, field="query_class") or "unknown"
            if rating:
                key = f"memory_sources_feedback:{rating}:{route}:{query_class}"
                grouped = [
                    item
                    for item in _scores_for_feedback(
                        scores,
                        evidence_by_id=evidence_by_id,
                        subject_kind=subject_kind,
                        rating=rating,
                    )
                    if (_score_evidence_field(item, evidence_by_id=evidence_by_id, field="route") or "unknown") == route
                    and (_score_evidence_field(item, evidence_by_id=evidence_by_id, field="query_class") or "unknown")
                    == query_class
                ]
                attempts.append(grouped[:3])
                feedback_attempt_seen = True
        else:
            key = f"generic:{subject_kind}:{score.get('subject_ref')}"
            other_generic = [
                item
                for item in scores
                if item is not score
                and str(item.get("subject_kind") or "") not in {"expression_feedback", "memory_sources_feedback"}
            ]
            attempts.append([score, *other_generic[:2]])
        if not key:
            continue
        if key in seen_keys:
            if len(attempts) > before_count:
                attempts.pop()
            continue
        seen_keys.add(key)
    if feedback_attempt_seen:
        attempts = [
            attempt
            for attempt in attempts
            if attempt
            and str(attempt[0].get("subject_kind") or "") in {"expression_feedback", "memory_sources_feedback"}
        ]
    if not attempts:
        attempts = [scores[:3]]
    result: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
    seen_shapes: set[str] = set()
    for attempt_scores in attempts:
        if not attempt_scores:
            continue
        shape = _proposal_shape(attempt_scores, evidence_scoring=evidence_scoring)
        shape_key = "|".join(
            [
                str(shape.get("kind") or ""),
                str(shape.get("proposal_class") or ""),
                str(shape.get("dedupe_key") or ""),
            ]
        )
        if shape_key in seen_shapes:
            continue
        seen_shapes.add(shape_key)
        result.append((attempt_scores, shape))
    return result


def _proposal_attempt_blocker(
    *,
    proposal_queue: Any,
    reports: list[dict[str, Any]],
    score_refs: list[str],
    proposal_shape: dict[str, Any],
    cadence_day: str,
    cadence_input_fingerprint: str,
) -> dict[str, Any] | None:
    duplicate = _unresolved_self_evolution_duplicate(
        proposal_queue,
        score_refs,
        proposal_shape=proposal_shape,
    )
    if duplicate is not None:
        return {
            "reason": "duplicate_unresolved_proposal",
            "agenda_status": "blocked_duplicate_unresolved",
            "existing_proposal_id": str(duplicate.get("candidate_id") or ""),
        }
    processed_proposal = _same_day_proposal_history_processed(
        proposal_queue,
        proposal_shape=proposal_shape,
        cadence_day=cadence_day,
    )
    if processed_proposal is not None:
        return {
            "reason": "cadence_same_day_same_signal",
            "agenda_status": "skipped_same_day_same_signal",
            "previous_proposal_id": str(processed_proposal.get("candidate_id") or ""),
        }
    processed = _same_day_same_signal_processed(
        reports,
        cadence_day=cadence_day,
        cadence_input_fingerprint=cadence_input_fingerprint,
    )
    if processed is not None:
        return {
            "reason": "cadence_same_day_same_signal",
            "agenda_status": "skipped_same_day_same_signal",
            "previous_report_id": str(processed.get("report_id") or ""),
        }
    if proposal_shape.get("quality_gate_failed") is True:
        return {
            "reason": "proposal_quality_gate_failed",
            "agenda_status": "blocked_quality_gate",
            "quality_gate_reason": str(proposal_shape.get("quality_gate_reason") or ""),
        }
    return None


def _score_feedback_rating(score: dict[str, Any], *, evidence_by_id: dict[str, dict[str, Any]]) -> str:
    return _score_evidence_field(score, evidence_by_id=evidence_by_id, field="feedback_rating")


def _score_evidence_field(score: dict[str, Any], *, evidence_by_id: dict[str, dict[str, Any]], field: str) -> str:
    for evidence_ref in score.get("evidence_refs", []):
        record = evidence_by_id.get(str(evidence_ref), {})
        value = str(record.get(field) or "")
        if value:
            return value
    return ""


def _scores_for_feedback(
    scores: list[dict[str, Any]],
    *,
    evidence_by_id: dict[str, dict[str, Any]],
    subject_kind: str,
    rating: str,
) -> list[dict[str, Any]]:
    return [
        score
        for score in scores
        if str(score.get("subject_kind") or "") == subject_kind
        and _score_feedback_rating(score, evidence_by_id=evidence_by_id) == rating
    ]


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
    expression_feedback = _expression_feedback_signals(scores, evidence_by_id=evidence_by_id)
    memory_sources_feedback = _memory_sources_feedback_signals(scores, evidence_by_id=evidence_by_id)
    top_score = scores[0] if scores else {}
    top_summary = _score_summary(top_score, evidence_by_id=evidence_by_id)
    top_subject = str(top_score.get("subject_ref") or "unknown_subject")
    top_subject_kind = str(top_score.get("subject_kind") or "unknown")
    rating = str(expression_feedback.get("feedback_rating") or "")
    if top_subject_kind == "memory_sources_feedback":
        rating = ""
    top_score_value = top_score.get("maturity_score", top_score.get("score", ""))
    quality = _proposal_quality(top_score, trigger_rule="feature_maturity_top_signal")
    if rating:
        proposal_class = f"expression_policy:{_safe_key(rating)}"
        proposal_quality = _expression_feedback_proposal_quality(
            top_score,
            trigger_rule="expression_feedback_policy",
            signals=expression_feedback,
        )
        evidence_bits = [
            f"owner 标记右脑表达 {rating}",
            f"feedback_count={expression_feedback.get('feedback_count', 0)}",
            f"linked_outcome_count={expression_feedback.get('linked_outcome_count', 0)}",
            f"unlinked_feedback_count={expression_feedback.get('unlinked_feedback_count', 0)}",
            f"maturity_score={top_score_value}",
            f"summary={top_summary}",
        ]
        outcome_refs = expression_feedback.get("outcome_refs") if isinstance(expression_feedback.get("outcome_refs"), list) else []
        policy_versions = (
            expression_feedback.get("policy_versions")
            if isinstance(expression_feedback.get("policy_versions"), list)
            else []
        )
        if outcome_refs:
            evidence_bits.append("outcomes=" + ",".join(str(ref) for ref in outcome_refs[:3]))
        if policy_versions:
            evidence_bits.append("policy_versions=" + ",".join(str(version) for version in policy_versions[:3]))
        quality_gate_failed = int(expression_feedback.get("linked_outcome_count") or 0) <= 0
        return {
            "kind": "expression_policy",
            "title": f"调整右脑表达策略：{rating} 反馈",
            "proposal_class": proposal_class,
            "dedupe_key": proposal_class,
            "proposal_quality": proposal_quality,
            "quality_gate_failed": quality_gate_failed,
            "quality_gate_reason": "expression_feedback_requires_linked_outcome" if quality_gate_failed else "",
            "body": _proposal_body(
                proposed_change=(
                    f"根据 owner 表达反馈 rating={rating}，形成一条右脑表达策略调整 proposal；"
                    "只说明要调整的 prompt/policy/cadence 候选，不直接写入运行时。"
                ),
                evidence="; ".join(evidence_bits),
                acceptance=(
                    "必须写清要改 prompt、cadence 还是 SpeakGate policy，owner 可见效果，"
                    "monitor 检查字段、对照样例、rollback/stop signal；至少引用一个 linked expression outcome。"
                ),
                follow_up=(
                    "approved_for_proposal -> OpsGate report-only -> owner manual apply decision；"
                    "actual_execute=false."
                ),
            ),
        }
    memory_sources_rating = str(memory_sources_feedback.get("feedback_rating") or "")
    if memory_sources_rating:
        route = str(memory_sources_feedback.get("route") or "unknown")
        query_class = str(memory_sources_feedback.get("query_class") or "unknown")
        proposal_class = f"memory_sources_policy:{_safe_key(memory_sources_rating)}"
        dedupe_key = f"{proposal_class}:{_safe_key(route)}:{_safe_key(query_class)}"
        proposal_quality = _memory_sources_feedback_proposal_quality(
            top_score,
            trigger_rule="memory_sources_feedback_policy",
            signals=memory_sources_feedback,
        )
        is_corrective = memory_sources_rating in _MEMORY_SOURCES_CORRECTIVE_RATINGS
        has_linked_source = int(memory_sources_feedback.get("linked_memory_source_count") or 0) > 0
        evidence_bits = [
            f"owner 标记 MemorySources {memory_sources_rating}",
            f"feedback_count={memory_sources_feedback.get('feedback_count', 0)}",
            f"linked_memory_source_count={memory_sources_feedback.get('linked_memory_source_count', 0)}",
            f"route={route}",
            f"query_class={query_class}",
            f"maturity_score={top_score_value}",
            f"summary={top_summary}",
        ]
        record_refs = memory_sources_feedback.get("memory_source_record_refs")
        if isinstance(record_refs, list) and record_refs:
            evidence_bits.append("memory_source_records=" + ",".join(str(ref) for ref in record_refs[:3]))
        quality_gate_reason = ""
        if not is_corrective:
            quality_gate_reason = "memory_sources_feedback_requires_corrective_rating"
        elif not has_linked_source:
            quality_gate_reason = "memory_sources_feedback_requires_source_record"
        return {
            "kind": "memory_sources_policy",
            "title": f"调整记忆来源/召回策略：{memory_sources_rating} 反馈",
            "proposal_class": proposal_class,
            "dedupe_key": dedupe_key,
            "proposal_quality": proposal_quality,
            "quality_gate_failed": bool(quality_gate_reason),
            "quality_gate_reason": quality_gate_reason,
            "body": _proposal_body(
                proposed_change=(
                    f"根据 owner 对 MemorySources 的 {memory_sources_rating} 反馈，复核 route={route} / "
                    f"query_class={query_class} 的上下文来源选择、低线索召回候选和反馈惩罚策略；"
                    "只形成可审查策略候选，不直接改路由或检索。"
                ),
                evidence="; ".join(evidence_bits),
                acceptance=(
                    "必须列出受影响的 route/query_class、MemorySources record、候选变化预期、"
                    "monitor 字段和回滚/停止信号；不能把 selected 当 successful_use。"
                ),
                follow_up=(
                    "approved_for_proposal -> OpsGate report-only -> 选择一个具体 bounded apply kind；"
                    "generic executor forbidden; actual_execute=false."
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


def _expression_feedback_signals(
    scores: list[dict[str, Any]],
    *,
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    selected_records: list[dict[str, Any]] = []
    for score in scores:
        if str(score.get("subject_kind") or "") != "expression_feedback":
            continue
        for evidence_ref in score.get("evidence_refs", []):
            record = evidence_by_id.get(str(evidence_ref), {})
            if str(record.get("subject_kind") or "") == "expression_feedback":
                selected_records.append(record)
    selected_ratings = [str(record.get("feedback_rating") or "") for record in selected_records]
    selected_ratings = [rating for rating in selected_ratings if rating and rating != "none"]
    if not selected_ratings:
        return {}
    rating = selected_ratings[0]
    records = [
        record
        for record in evidence_by_id.values()
        if str(record.get("subject_kind") or "") == "expression_feedback"
        and str(record.get("feedback_rating") or "") == rating
    ]
    outcome_refs = _unique_bounded([str(record.get("outcome_id") or "") for record in records])
    request_refs = _unique_bounded([str(record.get("request_id") or "") for record in records])
    policy_versions = _unique_bounded([str(record.get("policy_version") or "") for record in records])
    feedback_count = len(records)
    linked_count = len([record for record in records if str(record.get("outcome_id") or "")])
    return {
        "feedback_rating": rating,
        "feedback_count": feedback_count,
        "linked_outcome_count": linked_count,
        "unlinked_feedback_count": max(feedback_count - linked_count, 0),
        "outcome_refs": outcome_refs,
        "request_refs": request_refs,
        "policy_versions": policy_versions,
    }


_MEMORY_SOURCES_CORRECTIVE_RATINGS = {
    "irrelevant",
    "too_mechanistic",
    "missing_context",
    "overconfident",
    "needs_specific_recall",
    "clarification_rejected",
    "missing_candidate",
}


def _memory_sources_feedback_signals(
    scores: list[dict[str, Any]],
    *,
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    selected_records: list[dict[str, Any]] = []
    for score in scores:
        if str(score.get("subject_kind") or "") != "memory_sources_feedback":
            continue
        for evidence_ref in score.get("evidence_refs", []):
            record = evidence_by_id.get(str(evidence_ref), {})
            if str(record.get("subject_kind") or "") == "memory_sources_feedback":
                selected_records.append(record)
    selected_ratings = [str(record.get("feedback_rating") or "") for record in selected_records]
    selected_ratings = [rating for rating in selected_ratings if rating and rating != "none"]
    if not selected_ratings:
        return {}
    corrective = [rating for rating in selected_ratings if rating in _MEMORY_SOURCES_CORRECTIVE_RATINGS]
    rating = corrective[0] if corrective else selected_ratings[0]
    records = [
        record
        for record in evidence_by_id.values()
        if str(record.get("subject_kind") or "") == "memory_sources_feedback"
        and str(record.get("feedback_rating") or "") == rating
    ]
    routes = _unique_bounded([str(record.get("route") or "") for record in records])
    query_classes = _unique_bounded([str(record.get("query_class") or "") for record in records])
    source_refs = _unique_bounded([str(record.get("memory_source_record_id") or "") for record in records])
    feedback_count = len(records)
    linked_count = len([record for record in records if str(record.get("memory_source_record_id") or "")])
    return {
        "feedback_rating": rating,
        "feedback_count": feedback_count,
        "linked_memory_source_count": linked_count,
        "unlinked_memory_source_count": max(feedback_count - linked_count, 0),
        "route": routes[0] if routes else "unknown",
        "query_class": query_classes[0] if query_classes else "unknown",
        "routes": routes,
        "query_classes": query_classes,
        "memory_source_record_refs": source_refs,
    }


def _expression_feedback_proposal_quality(
    score: dict[str, Any],
    *,
    trigger_rule: str,
    signals: dict[str, Any],
) -> dict[str, Any]:
    quality = _proposal_quality(score, trigger_rule=trigger_rule)
    quality.update(
        {
            "quality_gate": "linked_expression_feedback",
            "feedback_rating": str(signals.get("feedback_rating") or ""),
            "feedback_count": int(signals.get("feedback_count") or 0),
            "linked_outcome_count": int(signals.get("linked_outcome_count") or 0),
            "unlinked_feedback_count": int(signals.get("unlinked_feedback_count") or 0),
            "outcome_refs": list(signals.get("outcome_refs") or []),
            "request_refs": list(signals.get("request_refs") or []),
            "policy_versions": list(signals.get("policy_versions") or []),
            "runtime_target": "expression_policy",
            "direct_apply_allowed": False,
            "generic_executor_allowed": False,
        }
    )
    return quality


def _memory_sources_feedback_proposal_quality(
    score: dict[str, Any],
    *,
    trigger_rule: str,
    signals: dict[str, Any],
) -> dict[str, Any]:
    quality = _proposal_quality(score, trigger_rule=trigger_rule)
    quality.update(
        {
            "quality_gate": "linked_corrective_memory_sources_feedback",
            "feedback_rating": str(signals.get("feedback_rating") or ""),
            "feedback_count": int(signals.get("feedback_count") or 0),
            "linked_memory_source_count": int(signals.get("linked_memory_source_count") or 0),
            "unlinked_memory_source_count": int(signals.get("unlinked_memory_source_count") or 0),
            "routes": list(signals.get("routes") or []),
            "query_classes": list(signals.get("query_classes") or []),
            "memory_source_record_refs": list(signals.get("memory_source_record_refs") or []),
            "runtime_target": "context_retrieval_policy_review",
            "direct_apply_allowed": False,
            "generic_executor_allowed": False,
            "selected_equals_successful_use": False,
        }
    )
    return quality


def _unique_bounded(values: list[str], *, limit: int = 5) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _bounded_line(value, 96)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
        if len(result) >= limit:
            break
    return result


def _safe_key(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"_", "-", ":"} else "_" for ch in str(value or "").strip().lower())
    return clean.strip("_") or "unknown"


def _stable_digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
