"""Explainable evidence scoring module for portable Hermes governance."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.evidence_profile import EVIDENCE_PROFILE_SCHEMA_VERSION, build_evidence_profile
from plugins.memory.memory_os.memory_sources import memory_sources_feedback_path
from plugins.memory.memory_os.store import MemoryOSStore

MATURITY_DIMENSION_KEYS = [
    "actionability",
    "duplicate_backlog",
    "evidence_strength",
    "freshness_decay",
    "gate_state",
    "owner_feedback",
    "recurrence",
    "risk",
    "source_diversity",
]


def evidence_scoring_manifest() -> dict[str, Any]:
    """Return the v0.1 Evidence / Scoring module manifest."""

    return {
        "name": "evidence_scoring",
        "kind": "evidence",
        "version": "0.1.0",
        "layer": "L2",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["proposal_queue", "ops_gate"],
        },
        "provides": {
            "commands": ["status", "doctor", "score-all"],
            "schedules": [],
            "reads": [
                "memory_os.events.summary",
                "memory_os.working",
                "memory_os.crystallized_candidates",
                "local_artifact.proposal_queue_state",
            ],
            "writes": ["memory_os.audit", "local_artifact.evidence_scoring"],
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


class EvidenceScoringModule:
    """Write evidence-linked score snapshots without taking action."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "evidence_scoring"

    @property
    def evidence_path(self) -> Path:
        return self.module_root / "evidence.jsonl"

    @property
    def scores_path(self) -> Path:
        return self.module_root / "scores.jsonl"

    @property
    def feature_scores_path(self) -> Path:
        return self.module_root / "feature_scores.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def score_all(self, *, store: MemoryOSStore, proposal_queue: Any | None = None) -> dict[str, Any]:
        store.initialize()
        subjects, collection_stats = self._collect_subjects(store=store, proposal_queue=proposal_queue)
        input_fingerprint = _input_fingerprint(subjects=subjects, collection_stats=collection_stats, profile=self.profile)
        latest_run = _latest_jsonl_record(self.runs_path)
        if (
            latest_run.get("input_fingerprint") == input_fingerprint
            and self.evidence_path.exists()
            and self.scores_path.exists()
            and self.feature_scores_path.exists()
        ):
            score_records = self.read_scores()
            feature_score_records = self.read_feature_scores()
            evidence_records = self.read_evidence()
            result = {
                "schema_version": "hermes.evidence_scoring_result.v0",
                "module": "evidence_scoring",
                "profile": self.profile,
                "status": "ok",
                "skipped": True,
                "cadence_skipped": True,
                "reason": "unchanged_input_fingerprint",
                "input_fingerprint": input_fingerprint,
                "score_mode": "feature_maturity_v2",
                "score_count": len(score_records),
                "evidence_count": len(evidence_records),
                "derived_evidence_profile_count": _derived_evidence_profile_count(evidence_records),
                "feature_score_mode": "primary",
                "feature_score_count": len(feature_score_records),
                "generated_score_count": 0,
                "hash_score_legacy_count": 0,
                "legacy_hash_comparison_count": len(feature_score_records),
                "comparison_count": min(len(feature_score_records), len(score_records)),
                "feature_score_report_count": 1 if feature_score_records else 0,
                "feature_score_live_applied": False,
                "prototype_aligned_score_count": len(feature_score_records),
                "maturity_dimension_count": len(MATURITY_DIMENSION_KEYS),
                "maturity_dimension_keys": list(MATURITY_DIMENSION_KEYS),
                "maturity_live_applied": False,
                "score_fingerprints": _fingerprints(score_records),
                "actual_approve": False,
                "actual_execute": False,
                "self_evolution_triggered": False,
                "scores_path": str(self.scores_path),
                "feature_scores_path": str(self.feature_scores_path),
                "evidence_path": str(self.evidence_path),
                **collection_stats,
            }
            _append_jsonl(self.runs_path, result)
            append_audit(
                store.roots.audit_path,
                action="evidence_scoring_run_skipped",
                status="ok",
                target=str(self.module_root),
                details={
                    "reason": "unchanged_input_fingerprint",
                    "input_fingerprint": input_fingerprint,
                    "score_count": len(score_records),
                    "generated_score_count": 0,
                    "actual_execute": False,
                },
            )
            return result

        subject_stats = _subject_signal_stats(subjects)
        evidence_records: list[dict[str, Any]] = []
        score_records: list[dict[str, Any]] = []
        feature_score_records: list[dict[str, Any]] = []
        for subject in subjects:
            evidence = self._build_evidence_record(subject)
            evidence_records.append(evidence)
            legacy_hash_score = _deterministic_score(subject["subject_ref"], subject["evidence_summary"])
            legacy_comparison = {
                "score_id": _stable_id("legacy_hash_score", subject["subject_ref"], evidence["evidence_id"]),
                "score": legacy_hash_score,
                "evidence_refs": [evidence["evidence_id"]],
            }
            feature_score = self.build_feature_score_record(
                subject=subject,
                legacy_score=legacy_comparison,
                subject_stats=subject_stats,
                evidence_profile=evidence["evidence_profile"],
            )
            score = self.build_score_record(
                subject_ref=subject["subject_ref"],
                subject_kind=subject["subject_kind"],
                score=float(feature_score["maturity_score"]),
                evidence_refs=[evidence["evidence_id"]],
                explanation=(
                    f"Feature maturity v2 score derived from {subject['subject_kind']} evidence "
                    "using bounded evidence strength, recurrence, actionability, diversity, "
                    "feedback, risk, freshness, duplicate backlog, and gate-state dimensions."
                ),
                score_source="feature_maturity_v2",
                legacy_hash_score=legacy_hash_score,
            )
            score_records.append(score)
            feature_score["primary_score_id"] = score["score_id"]
            feature_score_records.append(feature_score)

        self._write_jsonl(self.evidence_path, evidence_records)
        self._write_jsonl(self.scores_path, score_records)
        self._write_jsonl(self.feature_scores_path, feature_score_records)
        result = {
            "schema_version": "hermes.evidence_scoring_result.v0",
            "module": "evidence_scoring",
            "profile": self.profile,
            "status": "ok",
            "skipped": False,
            "cadence_skipped": False,
            "input_fingerprint": input_fingerprint,
            "score_mode": "feature_maturity_v2",
            "score_count": len(score_records),
            "evidence_count": len(evidence_records),
            "derived_evidence_profile_count": _derived_evidence_profile_count(evidence_records),
            "feature_score_mode": "primary",
            "feature_score_count": len(feature_score_records),
            "generated_score_count": len(score_records),
            "hash_score_legacy_count": 0,
            "legacy_hash_comparison_count": len(feature_score_records),
            "comparison_count": min(len(feature_score_records), len(score_records)),
            "feature_score_report_count": 1 if feature_score_records else 0,
            "feature_score_live_applied": False,
            "prototype_aligned_score_count": len(feature_score_records),
            "maturity_dimension_count": len(MATURITY_DIMENSION_KEYS),
            "maturity_dimension_keys": list(MATURITY_DIMENSION_KEYS),
            "maturity_live_applied": False,
            "score_fingerprints": _fingerprints(score_records),
            "actual_approve": False,
            "actual_execute": False,
            "self_evolution_triggered": False,
            "scores_path": str(self.scores_path),
            "feature_scores_path": str(self.feature_scores_path),
            "evidence_path": str(self.evidence_path),
            **collection_stats,
        }
        _append_jsonl(self.runs_path, result)
        append_audit(
            store.roots.audit_path,
            action="evidence_scoring_run_written",
            status="ok",
            target=str(self.module_root),
            details={
                "score_count": len(score_records),
                "evidence_count": len(evidence_records),
                "score_mode": "feature_maturity_v2",
                "feature_score_mode": "primary",
                "feature_score_count": len(feature_score_records),
                "generated_score_count": len(score_records),
                "hash_score_legacy_count": 0,
                "legacy_hash_comparison_count": len(feature_score_records),
                "comparison_count": min(len(feature_score_records), len(score_records)),
                "feature_score_live_applied": False,
                "prototype_aligned_score_count": len(feature_score_records),
                "maturity_dimension_count": len(MATURITY_DIMENSION_KEYS),
                "maturity_live_applied": False,
                "actual_approve": False,
                "actual_execute": False,
                "self_evolution_triggered": False,
                "input_fingerprint": input_fingerprint,
                **collection_stats,
            },
        )
        return result

    def build_score_record(
        self,
        *,
        subject_ref: str,
        subject_kind: str,
        score: float,
        evidence_refs: list[str],
        explanation: str,
        score_source: str = "feature_maturity_v2",
        legacy_hash_score: float | None = None,
    ) -> dict[str, Any]:
        if not evidence_refs:
            raise ValueError("score requires evidence_refs")
        if not explanation.strip():
            raise ValueError("score requires explanation")
        if score < 0.0 or score > 1.0:
            raise ValueError("score must be between 0.0 and 1.0")
        score_id = _stable_id("score", subject_ref, *evidence_refs, explanation)
        return {
            "schema_version": "hermes.evidence_score.v0",
            "score_id": score_id,
            "profile": self.profile,
            "subject_ref": subject_ref,
            "subject_kind": subject_kind,
            "score": round(float(score), 3),
            "score_source": score_source,
            "legacy_hash_score": None if legacy_hash_score is None else round(float(legacy_hash_score), 3),
            "evidence_refs": list(evidence_refs),
            "explanation_ref": f"local://evidence_scoring/explanations/{score_id}",
            "explanation": explanation,
            "accepted_without_evidence": False,
            "actual_approve": False,
            "self_evolution_triggered": False,
        }

    def build_feature_score_record(
        self,
        *,
        subject: dict[str, str],
        legacy_score: dict[str, Any],
        subject_stats: dict[str, Any] | None = None,
        evidence_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        features = _feature_inputs(subject)
        maturity_dimensions = _maturity_dimensions(subject, legacy_score, subject_stats or {})
        feature_score = _maturity_score(maturity_dimensions)
        legacy_score_value = round(float(legacy_score.get("score", 0.0)), 3)
        evidence_refs = [str(ref) for ref in legacy_score.get("evidence_refs", [])]
        feature_score_id = _stable_id(
            "feature_score",
            subject["subject_ref"],
            str(legacy_score.get("score_id") or ""),
            *evidence_refs,
        )
        return {
            "schema_version": "hermes.evidence_feature_score.v0",
            "feature_score_id": feature_score_id,
            "profile": self.profile,
            "subject_ref": subject["subject_ref"],
            "subject_kind": subject["subject_kind"],
            "legacy_hash_score_id": legacy_score.get("score_id"),
            "legacy_hash_score": legacy_score_value,
            "legacy_score": legacy_score_value,
            "feature_score": feature_score,
            "maturity_score": feature_score,
            "score_delta": round(feature_score - legacy_score_value, 3),
            "evidence_refs": evidence_refs,
            "evidence_profile": dict(evidence_profile or {}),
            "features": features,
            "maturity_dimensions": maturity_dimensions,
            "prototype_alignment": {
                "source": "10.20.2.88:self_evolution_daily_pipeline",
                "mode": "adapted_primary",
                "mapped_fields": [
                    "maturity_score",
                    "evidence_strength",
                    "evidence_count",
                    "qualified_evidence_count",
                    "actionable_qualified_count",
                    "observation_days",
                    "trigger_rule",
                    "approved_pending_execution",
                ],
            },
            "feature_explanation": (
                "Report-only maturity score adapted from the 10.20.2.88 self-evolution "
                "pipeline shape using bounded evidence strength, recurrence, actionability, "
                "source diversity, owner feedback, risk, freshness, duplicate backlog, and gate-state dimensions."
            ),
            "mode": "primary",
            "live_applied": False,
            "maturity_live_applied": False,
            "actual_approve": False,
            "actual_execute": False,
            "self_evolution_triggered": False,
        }

    def read_scores(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.scores_path)

    def read_feature_scores(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.feature_scores_path)

    def read_evidence(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.evidence_path)

    def status(self) -> dict[str, Any]:
        scores = self.read_scores()
        feature_scores = self.read_feature_scores()
        evidence = self.read_evidence()
        runs = _read_jsonl(self.runs_path)
        skipped_runs = [record for record in runs if record.get("skipped") is True]
        latest_run = runs[-1] if runs else {}
        subject_counts: dict[str, int] = {}
        for score in scores:
            subject_kind = str(score.get("subject_kind", ""))
            subject_counts[subject_kind] = subject_counts.get(subject_kind, 0) + 1
        expired_used = _expired_working_subject_count(evidence, self.hermes_home)
        feature_score_live_applied = any(record.get("live_applied") is True for record in feature_scores)
        expression_feedback_evidence = [
            record for record in evidence if str(record.get("subject_kind") or "") == "expression_feedback"
        ]
        memory_sources_feedback_evidence = [
            record for record in evidence if str(record.get("subject_kind") or "") == "memory_sources_feedback"
        ]
        return {
            "schema_version": "hermes.evidence_scoring_status.v0",
            "module": "evidence_scoring",
            "profile": self.profile,
            "score_mode": "feature_maturity_v2",
            "score_count": len(scores),
            "evidence_count": len(evidence),
            "derived_evidence_profile_count": _derived_evidence_profile_count(evidence),
            "feature_score_mode": "primary",
            "feature_score_count": len(feature_scores),
            "hash_score_legacy_count": 0,
            "legacy_hash_comparison_count": len(feature_scores),
            "comparison_count": min(len(feature_scores), len(scores)),
            "feature_score_report_count": 1 if feature_scores else 0,
            "feature_score_live_applied": feature_score_live_applied,
            "prototype_aligned_score_count": len(
                [record for record in feature_scores if isinstance(record.get("maturity_dimensions"), dict)]
            ),
            "maturity_dimension_count": len(MATURITY_DIMENSION_KEYS),
            "maturity_dimension_keys": list(MATURITY_DIMENSION_KEYS),
            "maturity_live_applied": any(record.get("maturity_live_applied") is True for record in feature_scores),
            "owner_feedback_signal_count": subject_counts.get("expression_feedback", 0)
            + subject_counts.get("memory_sources_feedback", 0),
            "memory_sources_feedback_subject_count": subject_counts.get("memory_sources_feedback", 0),
            "memory_sources_feedback_linked_subject_count": sum(
                1 for record in memory_sources_feedback_evidence if str(record.get("memory_source_record_id") or "")
            ),
            "memory_sources_feedback_corrective_subject_count": sum(
                1
                for record in memory_sources_feedback_evidence
                if str(record.get("feedback_rating") or "")
                in {
                    "irrelevant",
                    "too_mechanistic",
                    "missing_context",
                    "overconfident",
                    "needs_specific_recall",
                    "clarification_rejected",
                    "missing_candidate",
                }
            ),
            "expression_feedback_subject_count": subject_counts.get("expression_feedback", 0),
            "expression_feedback_linked_subject_count": sum(
                1 for record in expression_feedback_evidence if str(record.get("outcome_id") or "")
            ),
            "expression_feedback_unlinked_subject_count": sum(
                1 for record in expression_feedback_evidence if not str(record.get("outcome_id") or "")
            ),
            "subject_counts": dict(sorted(subject_counts.items())),
            "working_subject_count": subject_counts.get("working", 0),
            "expired_used_in_scoring_count": expired_used,
            "run_report_count": len(runs),
            "skipped_run_count": len(skipped_runs),
            "latest_skipped": latest_run.get("skipped") is True,
            "latest_cadence_skipped": latest_run.get("cadence_skipped") is True,
            "latest_skip_reason": str(latest_run.get("reason") or ""),
            "latest_input_fingerprint": str(latest_run.get("input_fingerprint") or ""),
            "delivery_mode": "no-send",
            "actual_approve": False,
            "actual_execute": False,
            "self_evolution_triggered": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        scores = self.read_scores()
        evidence_ids = {str(record.get("evidence_id", "")) for record in self.read_evidence()}
        if not scores:
            findings.append(
                {
                    "severity": "warning",
                    "code": "no_scores_written",
                    "message": "No evidence scores have been written yet",
                }
            )
        for score in scores:
            refs = [str(ref) for ref in score.get("evidence_refs", [])]
            if not refs or not score.get("explanation_ref") or not score.get("explanation"):
                findings.append(
                    {
                        "severity": "error",
                        "code": "score_missing_explanation_or_evidence",
                        "message": f"Score lacks required evidence/explanation: {score.get('score_id', '')}",
                    }
                )
                continue
            if any(ref not in evidence_ids for ref in refs):
                findings.append(
                    {
                        "severity": "error",
                        "code": "score_evidence_ref_missing",
                        "message": f"Score references missing evidence: {score.get('score_id', '')}",
                    }
                )
        if any(finding["severity"] == "error" for finding in findings):
            status = "error"
        elif findings:
            status = "warning"
        else:
            status = "ok"
        return {
            "schema_version": "hermes.evidence_scoring_doctor.v0",
            "module": "evidence_scoring",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }

    def _collect_subjects(
        self,
        *,
        store: MemoryOSStore,
        proposal_queue: Any | None,
    ) -> tuple[list[dict[str, str]], dict[str, int]]:
        subjects: list[dict[str, str]] = []
        governance_event_skipped_count = 0
        working_active_subject_count = 0
        working_expired_skipped_count = 0
        working_unknown_status_count = 0
        for event in sorted(store.read_events(), key=lambda item: item.id):
            if event.profile != self.profile:
                continue
            if _governance_feedback_event(event):
                governance_event_skipped_count += 1
                continue
            subjects.append(
                {
                    "subject_ref": f"event:{event.id}",
                    "subject_kind": "event",
                    "evidence_summary": event.summary,
                    "source_ref": f"memory_os:event:{event.id}",
                }
            )
        for path in sorted(store.roots.working_root.glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for item in document.get("items", []):
                item_id = str(item.get("id", ""))
                if not item_id:
                    continue
                status = str(item.get("status") or "")
                if status == "expired":
                    working_expired_skipped_count += 1
                    continue
                if status == "active":
                    working_active_subject_count += 1
                else:
                    working_unknown_status_count += 1
                subjects.append(
                    {
                        "subject_ref": f"working:{item_id}",
                        "subject_kind": "working",
                        "evidence_summary": str(item.get("text", "")),
                        "source_ref": f"memory_os:working:{path.stem}:{item_id}",
                        "source_status": status or "unknown",
                    }
                )
        if proposal_queue is not None:
            for item in proposal_queue.read_queue().get("items", []):
                candidate_id = str(item.get("candidate_id", ""))
                if not candidate_id:
                    continue
                subjects.append(
                    {
                        "subject_ref": f"proposal:{candidate_id}",
                        "subject_kind": "proposal",
                        "evidence_summary": f"{item.get('title', '')} [{item.get('state', '')}]",
                        "source_ref": f"local://proposal_queue/{candidate_id}",
                    }
                )
        for candidate in read_candidate_queue(store):
            subjects.append(
                {
                    "subject_ref": f"crystallized_candidate:{candidate.candidate_id}",
                    "subject_kind": "crystallized_candidate",
                    "evidence_summary": f"{candidate.kind} from {','.join(candidate.source_event_ids)}",
                    "source_ref": f"memory_os:crystallized_candidate:{candidate.candidate_id}",
                }
            )
        memory_sources_feedback_count = 0
        memory_sources_feedback_corrective_count = 0
        for feedback in _read_jsonl(memory_sources_feedback_path(store.roots)):
            if str(feedback.get("profile", self.profile)) not in {"", self.profile}:
                continue
            feedback_id = str(feedback.get("feedback_id", ""))
            if not feedback_id:
                continue
            memory_sources_feedback_count += 1
            rating = str(feedback.get("rating") or "unknown")
            if rating in {
                "irrelevant",
                "too_mechanistic",
                "missing_context",
                "overconfident",
                "needs_specific_recall",
                "clarification_rejected",
                "missing_candidate",
            }:
                memory_sources_feedback_corrective_count += 1
            memory_source_record_id = str(feedback.get("memory_source_record_id") or "")
            route = str(feedback.get("route") or "unknown")
            query_class = str(feedback.get("query_class") or "unknown")
            note = _bounded_subject_note(str(feedback.get("note") or ""))
            summary_parts = [
                f"memory_sources_feedback rating={rating}",
                f"route={route}",
                f"query_class={query_class}",
            ]
            if memory_source_record_id:
                summary_parts.append(f"record={memory_source_record_id}")
            if note:
                summary_parts.append(f"note={note}")
            subjects.append(
                {
                    "subject_ref": f"memory_sources_feedback:{feedback_id}",
                    "subject_kind": "memory_sources_feedback",
                    "evidence_summary": " ".join(summary_parts),
                    "source_ref": f"memory_os:memory_sources_feedback:{feedback_id}",
                    "source_status": "active",
                    "feedback_rating": rating,
                    "target_id": memory_source_record_id,
                    "memory_source_record_id": memory_source_record_id,
                    "route": route,
                    "query_class": query_class,
                    "linked_memory_source": "true" if memory_source_record_id else "false",
                }
            )
        expression_feedback_count = 0
        expression_feedback_linked_subject_count = 0
        expression_feedback_unlinked_subject_count = 0
        for feedback in _read_jsonl(store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"):
            feedback_id = str(feedback.get("feedback_id", ""))
            if not feedback_id:
                continue
            expression_feedback_count += 1
            rating = str(feedback.get("rating") or feedback.get("action_type") or "unknown")
            target_id = str(feedback.get("draft_id") or feedback.get("target_id") or "")
            outcome_id = str(feedback.get("outcome_id") or "")
            request_id = str(feedback.get("request_id") or "")
            policy_version = str(feedback.get("policy_version") or "")
            if outcome_id:
                expression_feedback_linked_subject_count += 1
            else:
                expression_feedback_unlinked_subject_count += 1
            summary_parts = [f"expression_feedback rating={rating}", f"target={target_id}"]
            if outcome_id:
                summary_parts.append(f"outcome={outcome_id}")
            if policy_version:
                summary_parts.append(f"policy_version={policy_version}")
            subjects.append(
                {
                    "subject_ref": f"expression_feedback:{feedback_id}",
                    "subject_kind": "expression_feedback",
                    "evidence_summary": " ".join(summary_parts),
                    "source_ref": f"memory_os:expression_feedback:{feedback_id}",
                    "source_status": "active",
                    "feedback_rating": rating,
                    "target_id": target_id,
                    "outcome_id": outcome_id,
                    "request_id": request_id,
                    "policy_version": policy_version,
                    "linked_outcome": "true" if outcome_id else "false",
                }
            )
        return sorted(subjects, key=lambda item: item["subject_ref"]), {
            "governance_event_skipped_count": governance_event_skipped_count,
            "working_active_subject_count": working_active_subject_count,
            "working_expired_skipped_count": working_expired_skipped_count,
            "working_unknown_status_count": working_unknown_status_count,
            "memory_sources_feedback_subject_count": memory_sources_feedback_count,
            "memory_sources_feedback_corrective_subject_count": memory_sources_feedback_corrective_count,
            "expression_feedback_subject_count": expression_feedback_count,
            "expression_feedback_linked_subject_count": expression_feedback_linked_subject_count,
            "expression_feedback_unlinked_subject_count": expression_feedback_unlinked_subject_count,
        }

    def _build_evidence_record(self, subject: dict[str, str]) -> dict[str, Any]:
        evidence_id = _stable_id("evidence", subject["subject_ref"], subject["evidence_summary"])
        evidence_profile = build_evidence_profile(
            subject_ref=subject["subject_ref"],
            subject_kind=subject["subject_kind"],
            source_ref=subject["source_ref"],
            evidence_summary=subject["evidence_summary"],
            tags=str(subject.get("tags") or "").split(",") if subject.get("tags") else (),
            provenance=str(subject.get("provenance") or "observed"),
        )
        record = {
            "schema_version": "hermes.evidence_record.v0",
            "evidence_id": evidence_id,
            "profile": self.profile,
            "subject_ref": subject["subject_ref"],
            "subject_kind": subject["subject_kind"],
            "source_ref": subject["source_ref"],
            "source_status": subject.get("source_status", ""),
            "summary": subject["evidence_summary"],
            "evidence_profile": evidence_profile,
            "live_applied": False,
            "actual_execute": False,
        }
        if subject.get("feedback_rating"):
            record["feedback_rating"] = subject["feedback_rating"]
        for key in (
            "target_id",
            "outcome_id",
            "request_id",
            "policy_version",
            "linked_outcome",
            "memory_source_record_id",
            "route",
            "query_class",
            "linked_memory_source",
        ):
            if subject.get(key):
                record[key] = subject[key]
        return record

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


def _latest_jsonl_record(path: Path) -> dict[str, Any]:
    records = _read_jsonl(path)
    return records[-1] if records else {}


def _input_fingerprint(
    *,
    subjects: list[dict[str, str]],
    collection_stats: dict[str, int],
    profile: str,
) -> str:
    payload = {
        "profile": profile,
        "score_mode": "feature_maturity_v2",
        "evidence_profile_schema_version": EVIDENCE_PROFILE_SCHEMA_VERSION,
        "maturity_dimensions": list(MATURITY_DIMENSION_KEYS),
        "subjects": subjects,
        "collection_stats": _fingerprint_collection_stats(collection_stats),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _fingerprint_collection_stats(collection_stats: dict[str, int]) -> dict[str, int]:
    non_scoring_stats = {
        "governance_event_skipped_count",
        "working_expired_skipped_count",
    }
    return {
        key: int(value)
        for key, value in sorted(collection_stats.items())
        if key not in non_scoring_stats
    }


def _expired_working_subject_count(evidence: list[dict[str, Any]], hermes_home: Path) -> int:
    expired_count = 0
    for record in evidence:
        if record.get("subject_kind") != "working":
            continue
        if str(record.get("source_status") or "") == "expired":
            expired_count += 1
    return expired_count


def _derived_evidence_profile_count(evidence: list[dict[str, Any]]) -> int:
    return sum(1 for record in evidence if isinstance(record.get("evidence_profile"), dict))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _subject_signal_stats(subjects: list[dict[str, str]]) -> dict[str, Any]:
    key_counts: Counter[str] = Counter()
    source_classes: dict[str, set[str]] = defaultdict(set)
    for subject in subjects:
        key = _signal_key(subject)
        key_counts[key] += 1
        source_classes[key].add(_source_class(subject.get("source_ref", "")))
    return {
        "key_counts": dict(key_counts),
        "source_classes": {key: sorted(values) for key, values in source_classes.items()},
    }


def _maturity_dimensions(
    subject: dict[str, str],
    legacy_score: dict[str, Any],
    subject_stats: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    summary_length = len(subject.get("evidence_summary", ""))
    subject_kind = subject.get("subject_kind", "")
    source_status = subject.get("source_status", "")
    proposal_state = _proposal_state(subject.get("evidence_summary", "")) if subject_kind == "proposal" else ""
    feedback_rating = subject.get("feedback_rating", "")
    linked_outcome = subject.get("linked_outcome", "") == "true"
    outcome_id = subject.get("outcome_id", "")
    request_id = subject.get("request_id", "")
    policy_version = subject.get("policy_version", "")
    signal_key = _signal_key(subject)
    key_counts = subject_stats.get("key_counts") if isinstance(subject_stats.get("key_counts"), dict) else {}
    source_classes = subject_stats.get("source_classes") if isinstance(subject_stats.get("source_classes"), dict) else {}
    recurrence_count = int(key_counts.get(signal_key) or 1)
    source_class_count = len(source_classes.get(signal_key) or [])
    evidence_count = len(legacy_score.get("evidence_refs") or [])
    summary_bucket = _summary_length_bucket(summary_length)
    risk_level = _risk_level(
        subject_kind=subject_kind,
        proposal_state=proposal_state,
        source_status=source_status,
        feedback_rating=feedback_rating,
    )
    owner_signal = _owner_feedback_signal(proposal_state, feedback_rating=feedback_rating)
    duplicate_backlog = _duplicate_backlog_signal(subject_kind=subject_kind, proposal_state=proposal_state)
    return {
        "evidence_strength": _dimension(
            min(1.0, 0.20 + evidence_count * 0.30 + summary_bucket * 0.15),
            evidence_count=evidence_count,
            summary_length_bucket=summary_bucket,
        ),
        "recurrence": _dimension(
            min(1.0, max(recurrence_count - 1, 0) * 0.25),
            recurrence_count=recurrence_count,
            observation_days_estimate=1 if recurrence_count > 0 else 0,
        ),
        "actionability": _dimension(
            _actionability_score(subject_kind=subject_kind, proposal_state=proposal_state),
            subject_kind=subject_kind,
            proposal_state=proposal_state or "none",
            feedback_rating=feedback_rating or "none",
        ),
        "source_diversity": _dimension(
            min(1.0, source_class_count / 3.0),
            source_class_count=source_class_count,
        ),
        "owner_feedback": _dimension(
            owner_signal,
            proposal_state=proposal_state or "none",
            feedback_rating=feedback_rating or "none",
            explicit_feedback_signal_count=1 if feedback_rating else 0,
            linked_outcome=linked_outcome,
            outcome_id=outcome_id,
            request_id=request_id,
            policy_version=policy_version,
        ),
        "risk": _dimension(
            round(1.0 - risk_level, 3),
            risk_level=risk_level,
            source_status=source_status or "unknown",
        ),
        "freshness_decay": _dimension(
            _freshness_decay_score(source_status),
            source_status=source_status or "unknown",
        ),
        "duplicate_backlog": _dimension(
            duplicate_backlog,
            unresolved_proposal_like=subject_kind == "proposal" and proposal_state in {"candidate", "approved_for_proposal"},
            proposal_state=proposal_state or "none",
        ),
        "gate_state": _dimension(
            1.0,
            gate="report_only",
            live_applied=False,
        ),
    }


def _dimension(score: float, **signals: Any) -> dict[str, Any]:
    return {"score": round(min(max(float(score), 0.0), 1.0), 3), "signals": signals}


def _maturity_score(dimensions: dict[str, dict[str, Any]]) -> float:
    weights = {
        "evidence_strength": 0.16,
        "recurrence": 0.10,
        "actionability": 0.16,
        "source_diversity": 0.10,
        "owner_feedback": 0.12,
        "risk": 0.12,
        "freshness_decay": 0.08,
        "duplicate_backlog": 0.08,
        "gate_state": 0.08,
    }
    total = 0.0
    for key, weight in weights.items():
        total += float(dimensions.get(key, {}).get("score", 0.0)) * weight
    return round(total, 3)


def _signal_key(subject: dict[str, str]) -> str:
    normalized = re.sub(r"\s+", " ", subject.get("evidence_summary", "").strip().lower())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{subject.get('subject_kind', '')}:{digest}"


def _source_class(source_ref: str) -> str:
    if source_ref.startswith("local://proposal_queue"):
        return "proposal_queue"
    if source_ref.startswith("memory_os:working"):
        return "working"
    if source_ref.startswith("memory_os:crystallized_candidate"):
        return "crystallized_candidate"
    if source_ref.startswith("memory_os:event"):
        return "event"
    if source_ref.startswith("memory_os:expression_feedback"):
        return "expression_feedback"
    if source_ref.startswith("memory_os:memory_sources_feedback"):
        return "memory_sources_feedback"
    return "unknown"


def _governance_feedback_event(event: Any) -> bool:
    safe_ref = getattr(event, "safe_ref", {}) or {}
    return (
        str(getattr(event, "source", "") or "") == "governance_feedback"
        or str(safe_ref.get("source_class") or "") == "governance"
        or str(safe_ref.get("source_module") or "") == "governance_feedback"
    )


def _feature_inputs(subject: dict[str, str]) -> dict[str, float | int]:
    summary_length = len(subject.get("evidence_summary", ""))
    subject_kind = subject.get("subject_kind", "")
    source_status = subject.get("source_status", "")
    proposal_state = _proposal_state(subject.get("evidence_summary", "")) if subject_kind == "proposal" else ""
    return {
        "subject_kind_weight": _subject_kind_weight(subject_kind),
        "source_status_weight": _source_status_weight(source_status),
        "summary_length_bucket": _summary_length_bucket(summary_length),
        "summary_length_weight": _summary_length_weight(summary_length),
        "proposal_state_weight": _proposal_state_weight(proposal_state),
    }


def _feature_based_score(features: dict[str, float | int]) -> float:
    score = (
        float(features["subject_kind_weight"])
        + float(features["source_status_weight"])
        + float(features["summary_length_weight"])
        + float(features["proposal_state_weight"])
    )
    return round(min(max(score, 0.0), 1.0), 3)


def _subject_kind_weight(subject_kind: str) -> float:
    weights = {
        "event": 0.55,
        "working": 0.62,
        "proposal": 0.58,
        "crystallized_candidate": 0.50,
        "expression_feedback": 0.72,
        "memory_sources_feedback": 0.74,
    }
    return weights.get(subject_kind, 0.45)


def _source_status_weight(source_status: str) -> float:
    if source_status == "active":
        return 0.08
    if source_status == "expired":
        return -0.20
    return 0.0


def _summary_length_bucket(summary_length: int) -> int:
    if summary_length >= 160:
        return 2
    if summary_length >= 60:
        return 1
    return 0


def _summary_length_weight(summary_length: int) -> float:
    return {0: 0.0, 1: 0.03, 2: 0.06}[_summary_length_bucket(summary_length)]


def _proposal_state(summary: str) -> str:
    match = re.search(r"\[([^\]]+)\]\s*$", summary)
    return match.group(1) if match else ""


def _actionability_score(*, subject_kind: str, proposal_state: str, feedback_rating: str = "") -> float:
    if subject_kind == "expression_feedback":
        return 0.85
    if subject_kind == "memory_sources_feedback":
        return 0.82
    if subject_kind == "proposal":
        if proposal_state == "approved_for_proposal":
            return 0.9
        if proposal_state == "candidate":
            return 0.8
        if proposal_state in {"rejected", "owner_declined", "closed"}:
            return 0.1
        return 0.65
    if subject_kind == "working":
        return 0.5
    if subject_kind == "crystallized_candidate":
        return 0.45
    if subject_kind == "event":
        return 0.3
    return 0.25


def _owner_feedback_signal(proposal_state: str, *, feedback_rating: str = "") -> float:
    if feedback_rating:
        if feedback_rating in {"like_expression"}:
            return 0.7
        if feedback_rating in {
            "too_mechanical",
            "too_frequent",
            "boundary_private",
            "off_voice",
            "mute_period",
            "irrelevant",
            "missing_context",
            "overconfident",
            "needs_specific_recall",
            "clarification_rejected",
            "missing_candidate",
        }:
            return 0.9
        return 0.65
    if proposal_state == "approved_for_proposal":
        return 0.85
    if proposal_state in {"owner_declined", "rejected", "closed"}:
        return 0.15
    return 0.5


def _risk_level(*, subject_kind: str, proposal_state: str, source_status: str, feedback_rating: str = "") -> float:
    risk = 0.20
    if subject_kind == "proposal":
        risk += 0.20
    if subject_kind == "expression_feedback":
        risk += 0.10
    if subject_kind == "memory_sources_feedback":
        risk += 0.10
    if feedback_rating == "boundary_private":
        risk += 0.35
    elif feedback_rating in {"too_frequent", "off_voice"}:
        risk += 0.15
    if proposal_state == "approved_for_proposal":
        risk += 0.10
    if source_status == "expired":
        risk += 0.25
    return round(min(max(risk, 0.0), 1.0), 3)


def _freshness_decay_score(source_status: str) -> float:
    if source_status == "active":
        return 1.0
    if source_status == "expired":
        return 0.1
    return 0.6


def _duplicate_backlog_signal(*, subject_kind: str, proposal_state: str) -> float:
    if subject_kind == "proposal" and proposal_state in {"candidate", "approved_for_proposal"}:
        return 0.35
    if subject_kind == "proposal" and proposal_state in {"owner_declined", "rejected", "closed"}:
        return 0.8
    return 0.65


def _bounded_subject_note(value: str, *, limit: int = 120) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "..."


def _proposal_state_weight(state: str) -> float:
    weights = {
        "candidate": 0.02,
        "approved_for_proposal": 0.05,
        "rejected": -0.08,
        "closed": -0.08,
    }
    return weights.get(state, 0.0)


def _deterministic_score(subject_ref: str, summary: str) -> float:
    digest = hashlib.sha256(f"{subject_ref}\n{summary}".encode("utf-8")).hexdigest()
    return round(0.4 + (int(digest[:4], 16) / 65535.0) * 0.5, 3)


def _fingerprints(scores: list[dict[str, Any]]) -> list[str]:
    return [
        hashlib.sha256(
            json.dumps(
                {
                    "subject_ref": score["subject_ref"],
                    "score": score["score"],
                    "evidence_refs": score["evidence_refs"],
                    "explanation_ref": score["explanation_ref"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        for score in scores
    ]
