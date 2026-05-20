"""Explainable evidence scoring module for portable Hermes governance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.store import MemoryOSStore


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

    def score_all(self, *, store: MemoryOSStore, proposal_queue: Any | None = None) -> dict[str, Any]:
        store.initialize()
        subjects = self._collect_subjects(store=store, proposal_queue=proposal_queue)
        evidence_records: list[dict[str, Any]] = []
        score_records: list[dict[str, Any]] = []
        for subject in subjects:
            evidence = self._build_evidence_record(subject)
            evidence_records.append(evidence)
            score_records.append(
                self.build_score_record(
                    subject_ref=subject["subject_ref"],
                    subject_kind=subject["subject_kind"],
                    score=_deterministic_score(subject["subject_ref"], subject["evidence_summary"]),
                    evidence_refs=[evidence["evidence_id"]],
                    explanation=f"Score derived from {subject['subject_kind']} evidence summary and 1 evidence ref.",
                )
            )

        self._write_jsonl(self.evidence_path, evidence_records)
        self._write_jsonl(self.scores_path, score_records)
        result = {
            "schema_version": "hermes.evidence_scoring_result.v0",
            "module": "evidence_scoring",
            "profile": self.profile,
            "status": "ok",
            "score_count": len(score_records),
            "evidence_count": len(evidence_records),
            "score_fingerprints": _fingerprints(score_records),
            "actual_approve": False,
            "self_evolution_triggered": False,
            "scores_path": str(self.scores_path),
            "evidence_path": str(self.evidence_path),
        }
        append_audit(
            store.roots.audit_path,
            action="evidence_scoring_run_written",
            status="ok",
            target=str(self.module_root),
            details={
                "score_count": len(score_records),
                "evidence_count": len(evidence_records),
                "actual_approve": False,
                "self_evolution_triggered": False,
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
            "evidence_refs": list(evidence_refs),
            "explanation_ref": f"local://evidence_scoring/explanations/{score_id}",
            "explanation": explanation,
            "accepted_without_evidence": False,
            "actual_approve": False,
            "self_evolution_triggered": False,
        }

    def read_scores(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.scores_path)

    def read_evidence(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.evidence_path)

    def status(self) -> dict[str, Any]:
        scores = self.read_scores()
        evidence = self.read_evidence()
        subject_counts: dict[str, int] = {}
        for score in scores:
            subject_kind = str(score.get("subject_kind", ""))
            subject_counts[subject_kind] = subject_counts.get(subject_kind, 0) + 1
        return {
            "schema_version": "hermes.evidence_scoring_status.v0",
            "module": "evidence_scoring",
            "profile": self.profile,
            "score_count": len(scores),
            "evidence_count": len(evidence),
            "subject_counts": dict(sorted(subject_counts.items())),
            "delivery_mode": "no-send",
            "actual_approve": False,
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

    def _collect_subjects(self, *, store: MemoryOSStore, proposal_queue: Any | None) -> list[dict[str, str]]:
        subjects: list[dict[str, str]] = []
        for event in sorted(store.read_events(), key=lambda item: item.id):
            if event.profile != self.profile:
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
                subjects.append(
                    {
                        "subject_ref": f"working:{item_id}",
                        "subject_kind": "working",
                        "evidence_summary": str(item.get("text", "")),
                        "source_ref": f"memory_os:working:{path.stem}:{item_id}",
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
        return sorted(subjects, key=lambda item: item["subject_ref"])

    def _build_evidence_record(self, subject: dict[str, str]) -> dict[str, Any]:
        evidence_id = _stable_id("evidence", subject["subject_ref"], subject["evidence_summary"])
        return {
            "schema_version": "hermes.evidence_record.v0",
            "evidence_id": evidence_id,
            "profile": self.profile,
            "subject_ref": subject["subject_ref"],
            "subject_kind": subject["subject_kind"],
            "source_ref": subject["source_ref"],
            "summary": subject["evidence_summary"],
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


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


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
