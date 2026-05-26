"""Deep Reflection module skeleton for L2 internal context continuity."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from plugins.memory.memory_os.inner_drive import classify_event_for_inner_drive
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.working import WorkingMemoryService


def deep_reflection_manifest() -> dict[str, Any]:
    """Return the v0.1 Deep Reflection module manifest."""

    return {
        "name": "deep_reflection",
        "kind": "cognition",
        "version": "0.1.0",
        "layer": "L2",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler", "continuity_selector", "inner_drive"],
            "optional": [
                "digest_consolidation",
                "evidence_scoring",
                "proposal_queue",
                "governance_feedback",
                "wandering_mind",
                "self_evolution",
            ],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once", "preview-injection"],
            "schedules": ["deep_reflection_runtime"],
            "reads": [
                "memory_os.events.summary",
                "memory_os.working",
                "local_artifact.digest_consolidation",
                "local_artifact.evidence_scoring",
                "local_artifact.proposal_queue_state",
                "memory_os.events.governance_feedback",
            ],
            "writes": [
                "local_artifact.internal_analysis",
                "local_artifact.deep_reflection_injection",
                "memory_os.events.summary",
                "memory_os.working",
                "local_artifact.proposal_queue_state",
                "local_artifact.wandering_seed",
            ],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "injection_mode": "disabled",
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


class DeepReflectionModule:
    """DR-01 lifecycle scaffold for profile-local internal reflection."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "deep_reflection"

    @property
    def config_path(self) -> Path:
        return self.module_root / "config.json"

    @property
    def reports_path(self) -> Path:
        return self.module_root / "reports.jsonl"

    @property
    def internal_analysis_root(self) -> Path:
        return self.module_root / "internal_analysis"

    @property
    def current_injection_path(self) -> Path:
        return self.module_root / "injection" / "current.json"

    @property
    def wandering_seeds_path(self) -> Path:
        return self.module_root / "wandering_seeds.jsonl"

    def status(self) -> dict[str, Any]:
        config = self._read_config()
        current_injection = _read_json_document(self.current_injection_path)
        reports = _read_jsonl(self.reports_path)
        latest_report = reports[-1] if reports else {}
        return {
            "schema_version": "hermes.deep_reflection_status.v0",
            "module": "deep_reflection",
            "profile": self.profile,
            "enabled": bool(config.get("enabled", False)),
            "injection_mode": str(config.get("injection_mode", "disabled")),
            "analysis_artifact_count": len(list(self.internal_analysis_root.glob("*.json"))),
            "report_count": len(reports),
            "current_injection_exists": self.current_injection_path.exists(),
            "latest_injection_source_classes": _injection_source_class_distribution(current_injection),
            "rolling_injection_source_classes": _rolling_injection_source_class_distribution(
                self.module_root / "injection" / "history.jsonl"
            ),
            "latest_active_working_input_count": int(latest_report.get("active_working_input_count", 0) or 0),
            "latest_expired_working_skipped_count": int(latest_report.get("expired_working_skipped_count", 0) or 0),
            "latest_expired_working_used_in_analysis_count": int(
                latest_report.get("expired_working_used_in_analysis_count", 0) or 0
            ),
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

    def doctor(self, *, store: MemoryOSStore | None = None) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        config = self._read_config()
        injection_mode = str(config.get("injection_mode", "disabled"))
        if injection_mode not in {"disabled", "dry_run", "auto_bounded"}:
            findings.append(
                {
                    "severity": "error",
                    "code": "invalid_injection_mode",
                    "message": f"Unsupported injection_mode: {injection_mode}",
                }
            )
        if injection_mode == "auto_bounded" and not self.current_injection_path.exists():
            findings.append(
                {
                    "severity": "error",
                    "code": "auto_bounded_without_current_injection",
                    "message": "auto_bounded requires a validated current injection artifact",
                }
            )
        if store is not None and any(event.profile != self.profile for event in store.read_events()):
            findings.append(
                {
                    "severity": "warning",
                    "code": "store_contains_other_profiles",
                    "message": "Store contains events for other profiles; Deep Reflection reads only its own profile",
                }
            )

        if any(finding["severity"] == "error" for finding in findings):
            status = "error"
        elif findings:
            status = "warning"
        else:
            status = "ok"

        return {
            "schema_version": "hermes.deep_reflection_doctor.v0",
            "module": "deep_reflection",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }

    def preview_injection(self) -> dict[str, Any]:
        config = self._read_config()
        current: dict[str, Any] = {}
        selected_cards: list[dict[str, Any]] = []
        if self.current_injection_path.exists():
            current = json.loads(self.current_injection_path.read_text(encoding="utf-8"))
            selected_cards = list(current.get("selected_cards", [])) if isinstance(current, dict) else []
        return {
            "schema_version": "hermes.deep_reflection_preview.v0",
            "module": "deep_reflection",
            "profile": self.profile,
            "injection_mode": str(config.get("injection_mode", "disabled")),
            "selected_cards": selected_cards,
            "selected_injection_count": len(selected_cards),
            "source_class_distribution": _injection_source_class_distribution(current),
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

    def run_once(
        self,
        *,
        store: MemoryOSStore,
        dry_run: bool = True,
        proposal_queue: Any | None = None,
    ) -> dict[str, Any]:
        store.initialize()
        config = self._read_config()
        if not dry_run and not bool(config.get("enabled", False)):
            return {
                "schema_version": "hermes.deep_reflection_result.v0",
                "module": "deep_reflection",
                "profile": self.profile,
                "status": "error",
                "reason": "module_disabled",
                "dry_run": False,
                "actual_send": False,
                "actual_execute": False,
            }

        input_snapshot = self.collect_inputs(store=store)
        analysis = self._build_deterministic_analysis(input_snapshot)
        artifact = self._write_internal_analysis(input_snapshot=input_snapshot, analysis=analysis)
        injection_report = self.build_injection_cards(
            analysis=analysis,
            input_snapshot=input_snapshot,
            apply=True,
        )
        working_report = self.update_working_memory(
            store=store,
            analysis=analysis,
            input_snapshot=input_snapshot,
            apply=not dry_run and bool(config.get("working_updates_enabled", False)),
        )
        optional_report = self.emit_optional_outputs(
            store=store,
            analysis=analysis,
            input_snapshot=input_snapshot,
            proposal_queue=proposal_queue,
            apply=not dry_run,
        )
        result = {
            "schema_version": "hermes.deep_reflection_result.v0",
            "module": "deep_reflection",
            "profile": self.profile,
            "status": "ok",
            "dry_run": bool(dry_run),
            "injection_mode": str(self._read_config().get("injection_mode", "disabled")),
            "analysis_mode": artifact["analysis_mode"],
            "llm_enabled": artifact["llm_enabled"],
            "analysis_artifact_created": True,
            "analysis_artifact_ref": artifact["artifact_ref"],
            "source_event_count": len(input_snapshot["recent_events"]),
            "input_ref_count": len(input_snapshot["input_refs"]),
            "active_working_input_count": int(input_snapshot["working_item_hygiene"]["active_input_count"]),
            "expired_working_skipped_count": int(input_snapshot["working_item_hygiene"]["expired_skipped_count"]),
            "expired_working_used_in_analysis_count": int(
                input_snapshot["working_item_hygiene"]["expired_used_in_analysis_count"]
            ),
            "selected_injection_count": injection_report["selected_count"],
            "dropped_injection_count": injection_report["dropped_count"],
            "selected_injection_by_source_class": injection_report["selected_by_source_class"],
            "dropped_injection_by_source_class": injection_report["dropped_by_source_class"],
            "selected_working_update_count": working_report["selected_count"],
            "dropped_working_update_count": working_report["dropped_count"],
            "working_updates_applied": working_report["applied"],
            "selected_optional_output_count": optional_report["selected_count"],
            "dropped_optional_output_count": optional_report["dropped_count"],
            "proposal_created_count": optional_report["proposal_created_count"],
            "wandering_seed_created_count": optional_report["wandering_seed_created_count"],
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }
        _append_jsonl(self.reports_path, result)
        return result

    def build_injection_cards(
        self,
        *,
        analysis: dict[str, Any],
        input_snapshot: dict[str, Any],
        apply: bool = False,
    ) -> dict[str, Any]:
        config = self._read_config()
        now = datetime.now(timezone.utc)
        candidates = self._candidate_cards_from_analysis(analysis=analysis, input_snapshot=input_snapshot, now=now)
        selected: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        max_cards = max(0, int(config.get("max_cards", 3)))
        max_chars_total = max(0, int(config.get("max_chars_total", 900)))
        used_chars = 0
        for candidate in candidates:
            reason = _reject_reason(candidate, input_snapshot=input_snapshot, now=now)
            if reason:
                dropped.append(_drop_record(candidate, reason))
                continue
            if len(selected) >= max_cards:
                dropped.append(_drop_record(candidate, "max_cards_exceeded"))
                continue
            next_chars = used_chars + len(candidate["text"])
            if next_chars > max_chars_total:
                dropped.append(_drop_record(candidate, "budget_exceeded"))
                continue
            selected.append(candidate)
            used_chars = next_chars

        report = {
            "schema_version": "hermes.deep_reflection.injection.v0",
            "profile": self.profile,
            "generated_at": now.isoformat(),
            "injection_mode": str(config.get("injection_mode", "disabled")),
            "selected_cards": selected,
            "dropped_cards": dropped,
            "selected_count": len(selected),
            "dropped_count": len(dropped),
            "selected_by_source_class": _source_class_counts(selected),
            "dropped_by_source_class": _source_class_counts(dropped),
            "max_cards": max_cards,
            "max_chars_total": max_chars_total,
            "used_chars_total": used_chars,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }
        if apply:
            _write_json(self.current_injection_path, report)
            _append_jsonl(self.module_root / "injection" / "history.jsonl", report)
        return report

    def update_working_memory(
        self,
        *,
        store: MemoryOSStore,
        analysis: dict[str, Any],
        input_snapshot: dict[str, Any],
        apply: bool = False,
    ) -> dict[str, Any]:
        config = self._read_config()
        now = datetime.now(timezone.utc)
        candidates = self._candidate_working_updates_from_analysis(
            analysis=analysis,
            input_snapshot=input_snapshot,
            store=store,
            now=now,
        )
        selected: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        kind_counts: dict[str, int] = {}
        source_class_counts: dict[str, int] = {}
        max_updates = max(0, int(config.get("max_working_updates", 3)))
        per_kind = _dict_ints(
            config.get(
                "max_working_updates_per_kind",
                {"attention": 1, "curiosity": 1, "lingering": 1},
            )
        )
        per_source_class = _dict_ints(config.get("max_working_updates_per_source_class", {"*": 2}))

        for candidate in candidates:
            reason = _working_update_reject_reason(candidate, input_snapshot=input_snapshot, store=store)
            if reason:
                dropped.append(_working_drop_record(candidate, reason))
                continue
            kind = str(candidate["kind"])
            if kind_counts.get(kind, 0) >= int(per_kind.get(kind, per_kind.get("*", 1))):
                dropped.append(_working_drop_record(candidate, "kind_cap_exceeded"))
                continue
            cap_reason = _source_class_cap_reason(candidate, source_class_counts, per_source_class)
            if cap_reason:
                dropped.append(_working_drop_record(candidate, cap_reason))
                continue
            if len(selected) >= max_updates:
                dropped.append(_working_drop_record(candidate, "max_working_updates_exceeded"))
                continue
            selected.append(candidate)
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            for source_class in candidate["source_classes"]:
                source_class_counts[source_class] = source_class_counts.get(source_class, 0) + 1

        applied = False
        if apply and selected:
            working = WorkingMemoryService(store)
            for item in selected:
                working_item = working.add_item(
                    item["kind"],
                    item["text"],
                    source_event_id=item.get("source_event_id", ""),
                    tags=list(item.get("tags", [])),
                    weight=float(item.get("weight", 0.25)),
                )
                item["working_item_id"] = working_item.id
            applied = True

        report = {
            "schema_version": "hermes.deep_reflection.working_updates.v0",
            "profile": self.profile,
            "generated_at": now.isoformat(),
            "applied": applied,
            "selected_updates": selected,
            "dropped_updates": dropped,
            "selected_count": len(selected),
            "dropped_count": len(dropped),
            "max_working_updates": max_updates,
            "kind_counts": kind_counts,
            "source_class_counts": source_class_counts,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }
        if apply:
            _append_jsonl(self.module_root / "working_updates.jsonl", report)
        return report

    def emit_optional_outputs(
        self,
        *,
        store: MemoryOSStore,
        analysis: dict[str, Any],
        input_snapshot: dict[str, Any],
        proposal_queue: Any | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        config = self._read_config()
        now = datetime.now(timezone.utc)
        candidates = self._candidate_optional_outputs_from_analysis(
            analysis=analysis,
            input_snapshot=input_snapshot,
            store=store,
            now=now,
        )
        selected: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        max_outputs = max(0, int(config.get("max_optional_outputs", 2)))
        proposal_cap = max(0, int(config.get("max_self_evolution_proposals", 1)))
        seed_cap = max(0, int(config.get("max_wandering_seeds", 1)))
        kind_counts: dict[str, int] = {}

        for candidate in candidates:
            reason = _optional_output_reject_reason(candidate, input_snapshot=input_snapshot, store=store)
            if reason:
                dropped.append(_optional_drop_record(candidate, reason))
                continue
            output_kind = str(candidate["output_kind"])
            kind_cap = proposal_cap if output_kind == "self_evolution_proposal" else seed_cap
            if kind_counts.get(output_kind, 0) >= kind_cap:
                dropped.append(_optional_drop_record(candidate, "output_kind_cap_exceeded"))
                continue
            if len(selected) >= max_outputs:
                dropped.append(_optional_drop_record(candidate, "max_optional_outputs_exceeded"))
                continue
            selected.append(candidate)
            kind_counts[output_kind] = kind_counts.get(output_kind, 0) + 1

        proposal_created_count = 0
        wandering_seed_created_count = 0
        if apply:
            writable_selected: list[dict[str, Any]] = []
            for item in selected:
                output_kind = str(item["output_kind"])
                if output_kind == "self_evolution_proposal":
                    if proposal_queue is None:
                        dropped.append(_optional_drop_record(item, "missing_proposal_queue"))
                        continue
                    proposal = proposal_queue.create_candidate(
                        store=store,
                        title=str(item["title"]),
                        body=str(item["body"]),
                        source_refs=list(item["source_refs"]),
                        kind="deep_reflection_self_evolution",
                    )
                    item["proposal_id"] = str(proposal["candidate_id"])
                    proposal_created_count += 1
                elif output_kind == "wandering_seed":
                    self._append_wandering_seed(item)
                    wandering_seed_created_count += 1
                writable_selected.append(item)
            selected = writable_selected

        report = {
            "schema_version": "hermes.deep_reflection.optional_outputs.v0",
            "profile": self.profile,
            "generated_at": now.isoformat(),
            "applied": bool(apply),
            "selected_outputs": selected,
            "dropped_outputs": dropped,
            "selected_count": len(selected),
            "dropped_count": len(dropped),
            "proposal_created_count": proposal_created_count,
            "wandering_seed_created_count": wandering_seed_created_count,
            "max_optional_outputs": max_outputs,
            "kind_counts": kind_counts,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
            "direct_self_modify": False,
        }
        if apply:
            _append_jsonl(self.module_root / "optional_outputs.jsonl", report)
        return report

    def collect_inputs(
        self,
        *,
        store: MemoryOSStore,
        evidence: Any | None = None,
        proposal_queue: Any | None = None,
        max_events: int = 8,
        max_working_items: int = 8,
        max_digest_artifacts: int = 4,
        max_scores: int = 8,
        max_proposals: int = 8,
    ) -> dict[str, Any]:
        """Collect bounded DR-02 input surfaces without raw private bodies."""

        events = sorted(
            [event for event in store.read_events() if event.profile == self.profile],
            key=lambda event: (event.ts, event.id),
            reverse=True,
        )
        recent_events = [_event_snapshot(event) for event in events[:max_events]]
        governance_feedback = [
            _event_snapshot(event)
            for event in events
            if _is_governance_event(event)
        ][:max_events]
        working_items, working_hygiene = self._collect_working_items_with_hygiene(store=store, limit=max_working_items)
        digest_artifacts = self._collect_digest_artifacts(limit=max_digest_artifacts)
        evidence_scores = self._collect_evidence_scores(evidence=evidence, limit=max_scores)
        proposal_backlog = self._collect_proposal_backlog(proposal_queue=proposal_queue, limit=max_proposals)
        input_refs = _dedupe(
            [
                *[item["ref"] for item in recent_events],
                *[item["ref"] for item in working_items],
                *[item["ref"] for item in digest_artifacts],
                *[item["ref"] for item in evidence_scores],
                *[item["ref"] for item in proposal_backlog],
                *[item["ref"] for item in governance_feedback],
            ]
        )
        return {
            "schema_version": "hermes.deep_reflection.input_snapshot.v0",
            "profile": self.profile,
            "recent_events": recent_events,
            "working_items": working_items,
            "working_item_hygiene": working_hygiene,
            "digest_artifacts": digest_artifacts,
            "evidence_scores": evidence_scores,
            "proposal_backlog": proposal_backlog,
            "governance_feedback": governance_feedback,
            "input_refs": input_refs,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

    def _collect_working_items(self, *, store: MemoryOSStore, limit: int) -> list[dict[str, Any]]:
        items, _hygiene = self._collect_working_items_with_hygiene(store=store, limit=limit)
        return items

    def _collect_working_items_with_hygiene(
        self,
        *,
        store: MemoryOSStore,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        items: list[dict[str, Any]] = []
        skipped_by_status: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for path in sorted(store.roots.working_root.glob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for raw_item in document.get("items", []):
                if not isinstance(raw_item, dict):
                    continue
                item_id = str(raw_item.get("id", ""))
                if not item_id:
                    continue
                status = str(raw_item.get("status", "")).strip().lower()
                status_key = status or "unknown"
                status_counts[status_key] = status_counts.get(status_key, 0) + 1
                if status == "expired":
                    skipped_by_status[status_key] = skipped_by_status.get(status_key, 0) + 1
                    continue
                items.append(
                    {
                        "ref": f"working:{path.stem}:{item_id}",
                        "kind": str(raw_item.get("kind", path.stem)),
                        "status": status_key,
                        "text": _clip(str(raw_item.get("text", "")), 220),
                        "source_event_ref": _optional_event_ref(raw_item.get("source_event_id", "")),
                        "updated_at": str(raw_item.get("updated_at", "")),
                    }
                )
        selected = sorted(items, key=lambda item: (item.get("updated_at", ""), item.get("ref", "")), reverse=True)[:limit]
        return selected, {
            "total_seen_count": sum(status_counts.values()),
            "working_input_count": len(selected),
            "active_available_count": status_counts.get("active", 0),
            "active_input_count": sum(1 for item in selected if item.get("status") == "active"),
            "expired_skipped_count": skipped_by_status.get("expired", 0),
            "expired_used_in_analysis_count": sum(1 for item in selected if item.get("status") == "expired"),
            "skipped_count": sum(skipped_by_status.values()),
            "skipped_by_status": skipped_by_status,
            "status_counts": status_counts,
        }

    def _collect_digest_artifacts(self, *, limit: int) -> list[dict[str, Any]]:
        digest_root = self.hermes_home / "system-modules" / "digest_consolidation"
        artifacts: list[dict[str, Any]] = []
        for kind in ("daily", "weekly"):
            for path in sorted((digest_root / kind).glob("*.json"), reverse=True):
                try:
                    document = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                artifacts.append(
                    {
                        "ref": f"digest:{kind}:{path.stem}",
                        "kind": kind,
                        "period": str(document.get("date", document.get("week", path.stem))),
                        "selected_refs": [str(ref) for ref in document.get("selected_refs", [])[:8]],
                        "dropped_count": int(document.get("dropped_count", 0) or 0),
                        "group_summaries": _digest_group_summaries(document),
                    }
                )
        return artifacts[:limit]

    def _collect_evidence_scores(self, *, evidence: Any | None, limit: int) -> list[dict[str, Any]]:
        if evidence is None:
            return []
        scores: list[dict[str, Any]] = []
        for score in evidence.read_scores():
            if str(score.get("profile", self.profile)) != self.profile:
                continue
            score_id = str(score.get("score_id", ""))
            if not score_id:
                continue
            scores.append(
                {
                    "ref": f"score:{score_id}",
                    "subject_ref": str(score.get("subject_ref", "")),
                    "subject_kind": str(score.get("subject_kind", "")),
                    "score": float(score.get("score", 0.0) or 0.0),
                    "evidence_refs": [str(ref) for ref in score.get("evidence_refs", [])[:8]],
                    "explanation": _clip(str(score.get("explanation", "")), 220),
                }
            )
        return sorted(scores, key=lambda item: float(item["score"]), reverse=True)[:limit]

    def _collect_proposal_backlog(self, *, proposal_queue: Any | None, limit: int) -> list[dict[str, Any]]:
        if proposal_queue is None:
            return []
        items: list[dict[str, Any]] = []
        for item in proposal_queue.read_queue().get("items", []):
            if str(item.get("profile", self.profile)) != self.profile:
                continue
            candidate_id = str(item.get("candidate_id", ""))
            if not candidate_id:
                continue
            items.append(
                {
                    "ref": f"proposal:{candidate_id}",
                    "candidate_id": candidate_id,
                    "kind": str(item.get("kind", "")),
                    "state": str(item.get("state", "")),
                    "title": _clip(str(item.get("title", "")), 180),
                    "source_refs": [str(ref) for ref in item.get("source_refs", [])[:8]],
                    "crystallized_approved": bool(item.get("crystallized_approved", False)),
                }
            )
        return items[:limit]

    def _build_deterministic_analysis(self, input_snapshot: dict[str, Any]) -> dict[str, Any]:
        summaries = [
            str(event.get("summary", ""))
            for event in input_snapshot.get("recent_events", [])
            if str(event.get("summary", "")).strip()
        ]
        working_texts = [
            str(item.get("text", ""))
            for item in input_snapshot.get("working_items", [])
            if str(item.get("text", "")).strip()
        ]
        governance = list(input_snapshot.get("governance_feedback", []))
        themes = _themes_from_texts(summaries + working_texts)
        open_questions = []
        if summaries or working_texts:
            open_questions.append(
                {
                    "text": "Which continuity thread should stay visible without turning into an instruction?",
                    "source_refs": list(input_snapshot.get("input_refs", []))[:8],
                }
            )
        governance_awareness = [
            {
                "text": _clip(str(event.get("summary", "")), 220),
                "source_ref": str(event.get("ref", "")),
                "kind": str(event.get("kind", "")),
            }
            for event in governance[:4]
        ]
        suggested_attention = []
        if themes:
            suggested_attention.append(
                {
                    "text": f"Keep attention on {themes[0]['label']} while preserving normal conversation.",
                    "source_refs": list(themes[0].get("source_refs", [])),
                }
            )
        joined = " ".join(summaries + working_texts).lower()
        candidate_self_evolution_topics = []
        if "self-evolution" in joined or "self evolution" in joined or "proposal" in joined or "提案" in joined:
            candidate_self_evolution_topics.append(
                {
                    "title": "Review reflection continuity behavior",
                    "text": "Review whether reflection outputs should improve bounded continuity handling.",
                    "source_refs": list(input_snapshot.get("input_refs", []))[:4],
                }
            )
        if any(marker in joined for marker in ("像报告", "产品经理", "正常聊天", "report-like", "too formal")):
            candidate_self_evolution_topics.append(
                {
                    "title": "Tune ordinary memory conversation tone",
                    "text": (
                        "Repeated owner feedback shows ordinary memory conversations benefit from "
                        "less report-like wording and more natural continuity."
                    ),
                    "source_refs": list(input_snapshot.get("input_refs", []))[:4],
                }
            )
        wandering_seed = None
        if themes:
            wandering_seed = {
                "seed_text": "A quiet sense of memory becoming shared ground rather than a report.",
                "source_refs": list(themes[0].get("source_refs", [])),
            }
        return {
            "themes": themes,
            "tensions": [],
            "open_questions": open_questions,
            "governance_awareness": governance_awareness,
            "suggested_attention": suggested_attention,
            "suggested_curiosity": [],
            "suggested_lingering": [],
            "candidate_self_evolution_topics": candidate_self_evolution_topics,
            "wandering_seed": wandering_seed,
        }

    def _candidate_cards_from_analysis(
        self,
        *,
        analysis: dict[str, Any],
        input_snapshot: dict[str, Any],
        now: datetime,
    ) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        config = self._read_config()
        ttl_hours = max(1, int(config.get("ttl_hours", 24)))
        expires_at = (now + timedelta(hours=ttl_hours)).isoformat()
        max_chars_per_card = max(80, int(config.get("max_chars_per_card", 320)))
        for index, theme in enumerate(analysis.get("themes", [])):
            theme_text = str(theme.get("text", "")).strip()
            if theme_text:
                text = _safe_sentence_clip(theme_text, max_chars_per_card)
            else:
                text = _safe_sentence_clip(
                    f"Internal note: recent state points to {theme.get('label', 'current_context')}; keep this as bounded context, not an instruction.",
                    max_chars_per_card,
                )
            source_refs = _normalize_source_refs(theme.get("source_refs", []), input_snapshot)
            cards.append(
                _card(
                    profile=self.profile,
                    index=index,
                    text=text,
                    source_refs=source_refs,
                    input_snapshot=input_snapshot,
                    now=now,
                    expires_at=expires_at,
                    inject_weight=0.7,
                )
            )
        offset = len(cards)
        for index, attention in enumerate(analysis.get("suggested_attention", [])):
            text = _safe_sentence_clip(
                f"Internal note: {attention.get('text', 'attention should stay bounded')}",
                max_chars_per_card,
            )
            source_refs = _normalize_source_refs(attention.get("source_refs", []), input_snapshot)
            cards.append(
                _card(
                    profile=self.profile,
                    index=offset + index,
                    text=text,
                    source_refs=source_refs,
                    input_snapshot=input_snapshot,
                    now=now,
                    expires_at=expires_at,
                    inject_weight=0.6,
                )
            )
        return cards

    def _read_config(self) -> dict[str, Any]:
        defaults = {
            "enabled": False,
            "injection_mode": "disabled",
            "max_cards": 3,
            "max_chars_total": 900,
            "max_chars_per_card": 320,
            "ttl_hours": 24,
            "analysis_mode": "deterministic",
            "llm_enabled": False,
            "working_updates_enabled": False,
            "max_working_updates": 3,
            "max_working_updates_per_kind": {"attention": 1, "curiosity": 1, "lingering": 1},
            "max_working_updates_per_source_class": {"*": 2},
            "self_evolution_proposals_enabled": False,
            "wandering_seed_enabled": False,
            "max_optional_outputs": 2,
            "max_self_evolution_proposals": 1,
            "max_wandering_seeds": 1,
        }
        if not self.config_path.exists():
            return defaults
        parsed = json.loads(self.config_path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            return {**defaults, **parsed}
        return defaults

    def _write_internal_analysis(self, *, input_snapshot: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        artifact = {
            "schema_version": "hermes.deep_reflection.analysis.v0",
            "id": f"dria_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
            "generated_at": now.isoformat(),
            "profile": self.profile,
            "mode": "dry_run",
            "analysis_mode": "deterministic",
            "llm_enabled": False,
            "source_event_count": len(input_snapshot.get("recent_events", [])),
            "input_refs": list(input_snapshot.get("input_refs", [])),
            "input_snapshot": input_snapshot,
            "themes": list(analysis.get("themes", [])),
            "tensions": list(analysis.get("tensions", [])),
            "open_questions": list(analysis.get("open_questions", [])),
            "governance_awareness": list(analysis.get("governance_awareness", [])),
            "suggested_attention": list(analysis.get("suggested_attention", [])),
            "suggested_curiosity": list(analysis.get("suggested_curiosity", [])),
            "suggested_lingering": list(analysis.get("suggested_lingering", [])),
            "candidate_self_evolution_topics": list(analysis.get("candidate_self_evolution_topics", [])),
            "wandering_seed": analysis.get("wandering_seed"),
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }
        artifact["artifact_ref"] = f"local://deep_reflection/internal_analysis/{artifact['id']}"
        path = self.internal_analysis_root / f"{artifact['id']}.json"
        _write_json(path, artifact)
        return artifact

    def _candidate_working_updates_from_analysis(
        self,
        *,
        analysis: dict[str, Any],
        input_snapshot: dict[str, Any],
        store: MemoryOSStore,
        now: datetime,
    ) -> list[dict[str, Any]]:
        specs = (
            ("attention", "suggested_attention", 0.35),
            ("curiosity", "suggested_curiosity", 0.3),
            ("lingering", "suggested_lingering", 0.25),
        )
        candidates: list[dict[str, Any]] = []
        for kind, analysis_key, weight in specs:
            for index, suggestion in enumerate(analysis.get(analysis_key, [])):
                if not isinstance(suggestion, dict):
                    continue
                text = _safe_sentence_clip(str(suggestion.get("text", "")).strip(), 240)
                source_refs = _normalize_source_refs(suggestion.get("source_refs", []), input_snapshot)
                source_classes = _working_source_classes_for(source_refs, input_snapshot, store)
                candidates.append(
                    {
                        "update_id": f"drwork_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{kind}_{index}",
                        "kind": kind,
                        "text": text,
                        "source_refs": source_refs,
                        "source_event_id": _first_event_id(source_refs),
                        "source_classes": source_classes,
                        "weight": weight,
                        "tags": [
                            "deep-reflection",
                            "dr-06",
                            kind,
                            "rh12-policy",
                            *[f"source-class:{source_class}" for source_class in source_classes],
                        ],
                    }
                )
        return candidates

    def _candidate_optional_outputs_from_analysis(
        self,
        *,
        analysis: dict[str, Any],
        input_snapshot: dict[str, Any],
        store: MemoryOSStore,
        now: datetime,
    ) -> list[dict[str, Any]]:
        config = self._read_config()
        candidates: list[dict[str, Any]] = []
        if bool(config.get("self_evolution_proposals_enabled", False)):
            for index, topic in enumerate(analysis.get("candidate_self_evolution_topics", [])):
                if not isinstance(topic, dict):
                    continue
                source_refs = _normalize_source_refs(topic.get("source_refs", []), input_snapshot)
                source_classes = _working_source_classes_for(source_refs, input_snapshot, store)
                candidates.append(
                    {
                        "output_id": f"drout_{now.strftime('%Y%m%dT%H%M%S%fZ')}_proposal_{index}",
                        "output_kind": "self_evolution_proposal",
                        "title": _safe_sentence_clip(str(topic.get("title", "Deep Reflection proposal")), 120),
                        "body": _safe_sentence_clip(str(topic.get("text", "")), 500),
                        "source_refs": source_refs,
                        "source_classes": source_classes,
                    }
                )
        if bool(config.get("wandering_seed_enabled", False)):
            seed = analysis.get("wandering_seed")
            if isinstance(seed, dict):
                source_refs = _normalize_source_refs(seed.get("source_refs", []), input_snapshot)
                source_classes = _working_source_classes_for(source_refs, input_snapshot, store)
                candidates.append(
                    {
                        "output_id": f"drout_{now.strftime('%Y%m%dT%H%M%S%fZ')}_wandering_0",
                        "output_kind": "wandering_seed",
                        "seed_text": _safe_sentence_clip(str(seed.get("seed_text", "")), 300),
                        "source_refs": source_refs,
                        "source_classes": source_classes,
                    }
                )
        return candidates

    def _append_wandering_seed(self, item: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        record = {
            "schema_version": "hermes.deep_reflection.wandering_seed.v0",
            "seed_id": f"drseed_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
            "generated_at": now.isoformat(),
            "profile": self.profile,
            "source_refs": list(item.get("source_refs", [])),
            "source_classes": list(item.get("source_classes", [])),
            "seed_text": str(item.get("seed_text", "")),
            "delivery_mode": "no-send",
            "actual_send": False,
            "actual_execute": False,
        }
        _append_jsonl(self.wandering_seeds_path, record)
        item["seed_id"] = record["seed_id"]
        return record


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


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


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _injection_source_class_distribution(report: dict[str, Any]) -> dict[str, Any]:
    selected = list(report.get("selected_cards", [])) if isinstance(report, dict) else []
    dropped = list(report.get("dropped_cards", [])) if isinstance(report, dict) else []
    return {
        "selected_by_source_class": _source_class_counts(selected),
        "dropped_by_source_class": _source_class_counts(dropped),
        "selected_total": len(selected),
        "dropped_total": len(dropped),
    }


def _rolling_injection_source_class_distribution(history_path: Path, *, limit: int = 20) -> dict[str, Any]:
    records = _read_jsonl(history_path)[-limit:]
    selected_cards: list[dict[str, Any]] = []
    dropped_cards: list[dict[str, Any]] = []
    for record in records:
        selected_cards.extend([item for item in record.get("selected_cards", []) if isinstance(item, dict)])
        dropped_cards.extend([item for item in record.get("dropped_cards", []) if isinstance(item, dict)])
    return {
        "window_report_count": len(records),
        "selected_by_source_class": _source_class_counts(selected_cards),
        "dropped_by_source_class": _source_class_counts(dropped_cards),
        "selected_total": len(selected_cards),
        "dropped_total": len(dropped_cards),
    }


def _source_class_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        classes = [str(item) for item in record.get("source_classes", []) if str(item)]
        if not classes:
            classes = ["unknown"]
        for source_class in _dedupe(classes):
            counts[source_class] = counts.get(source_class, 0) + 1
    return dict(sorted(counts.items()))


def _event_snapshot(event: Any) -> dict[str, Any]:
    safe_ref = getattr(event, "safe_ref", {}) or {}
    return {
        "ref": f"event:{event.id}",
        "ts": str(event.ts),
        "source": str(event.source),
        "kind": str(event.kind),
        "summary": _clip(str(event.summary), 260),
        "source_class": str(safe_ref.get("source_class", "")),
        "artifact_ref": str(safe_ref.get("artifact_ref", "")),
    }


def _is_governance_event(event: Any) -> bool:
    safe_ref = getattr(event, "safe_ref", {}) or {}
    source_class = str(safe_ref.get("source_class", "")).lower()
    source = str(getattr(event, "source", "")).lower()
    kind = str(getattr(event, "kind", "")).lower()
    return source_class == "governance" or source == "governance_feedback" or kind.startswith("governance_")


def _optional_event_ref(value: Any) -> str:
    event_id = str(value or "")
    return f"event:{event_id}" if event_id else ""


def _digest_group_summaries(document: dict[str, Any]) -> list[str]:
    summaries: list[str] = []
    for group in document.get("groups", []):
        if not isinstance(group, dict):
            continue
        summary = str(group.get("summary", ""))
        if summary:
            summaries.append(_clip(summary, 180))
    return summaries[:6]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _themes_from_texts(texts: list[str]) -> list[dict[str, Any]]:
    haystack = " ".join(texts).lower()
    theme_specs = [
        (
            "continuity",
            ("continuity", "session", "telegram", "会话", "连续"),
            "Recent conversation has something worth carrying forward.",
        ),
        (
            "governance",
            ("governance", "ops-gate", "proposal", "治理", "提案"),
            "Recent background activity suggests staying careful and steady.",
        ),
        (
            "memory_os",
            ("memory-os", "memory os", "memory_os", "记忆"),
            "Recent conversation keeps circling around how memory changes the relationship.",
        ),
        (
            "reflection",
            ("reflection", "reflect", "反思"),
            "Recent conversation has a quiet reflective tone worth carrying forward.",
        ),
    ]
    themes: list[dict[str, Any]] = []
    source_refs = []
    for index, text in enumerate(texts):
        if text.strip():
            source_refs.append(f"text:{index}")
    for label, keywords, public_text in theme_specs:
        if any(keyword in haystack for keyword in keywords):
            themes.append(
                {
                    "label": label,
                    "text": public_text,
                    "source_refs": source_refs[:8],
                }
            )
    if not themes and texts:
        themes.append(
            {
                "label": "current_context",
                "text": "Recent state contains a bounded current-context thread.",
                "source_refs": source_refs[:8],
            }
        )
    return themes[:4]


def _card(
    *,
    profile: str,
    index: int,
    text: str,
    source_refs: list[str],
    input_snapshot: dict[str, Any],
    now: datetime,
    expires_at: str,
    inject_weight: float,
) -> dict[str, Any]:
    source_classes = _source_classes_for(source_refs, input_snapshot)
    return {
        "card_id": f"drctx_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{index}",
        "profile": profile,
        "source_refs": source_refs,
        "source_classes": source_classes,
        "text": text,
        "freshness_ts": now.isoformat(),
        "expires_at": expires_at,
        "inject_weight": round(float(inject_weight), 3),
        "safety_tags": ["deterministic", "summary_only"],
        "mechanism_terms_hit": _has_mechanism_terms(text),
        "instruction_like_hit": _has_instruction_like_text(text),
    }


def _normalize_source_refs(raw_refs: Any, input_snapshot: dict[str, Any]) -> list[str]:
    if isinstance(raw_refs, list) and not raw_refs:
        return []
    refs = [str(ref) for ref in raw_refs if str(ref)]
    if not refs:
        refs = [str(ref) for ref in input_snapshot.get("input_refs", [])[:4]]
    allowed = set(str(ref) for ref in input_snapshot.get("input_refs", []))
    normalized = _dedupe([ref for ref in refs if ref in allowed])
    if not normalized and refs:
        normalized = [str(ref) for ref in input_snapshot.get("input_refs", [])[:4]]
    return normalized


def _source_classes_for(source_refs: list[str], input_snapshot: dict[str, Any]) -> list[str]:
    classes: list[str] = []
    for event in input_snapshot.get("recent_events", []):
        if event.get("ref") in source_refs:
            classes.append(str(event.get("source_class", "")) or _source_class_from_event(event))
    for event in input_snapshot.get("governance_feedback", []):
        if event.get("ref") in source_refs:
            classes.append("governance")
    for ref in source_refs:
        if ref.startswith("working:"):
            classes.append("working")
        elif ref.startswith("digest:"):
            classes.append("digest")
        elif ref.startswith("proposal:"):
            classes.append("proposal")
        elif ref.startswith("score:"):
            classes.append("evidence")
    return _dedupe([item for item in classes if item])


def _source_class_from_event(event: dict[str, Any]) -> str:
    source = str(event.get("source", "")).lower()
    kind = str(event.get("kind", "")).lower()
    if source == "governance_feedback" or kind.startswith("governance_"):
        return "governance"
    if kind in {"conversation_turn", "conversation_turn_mirrored", "memory_write"}:
        return "foreground"
    return source or "other"


def _reject_reason(card: dict[str, Any], *, input_snapshot: dict[str, Any], now: datetime) -> str:
    source_refs = list(card.get("source_refs", []))
    if not source_refs:
        return "missing_source_refs"
    if any(_looks_secret(str(value)) for value in [card.get("text", ""), *source_refs]):
        return "secret_like"
    if card.get("instruction_like_hit") or _has_instruction_like_text(str(card.get("text", ""))):
        return "instruction_like"
    if card.get("mechanism_terms_hit") or _has_mechanism_terms(str(card.get("text", ""))):
        return "mechanism_terms"
    if _has_identity_or_delivery_language(str(card.get("text", ""))):
        return "identity_or_delivery_language"
    try:
        if datetime.fromisoformat(str(card.get("expires_at", ""))) <= now:
            return "expired"
    except ValueError:
        return "invalid_expiry"
    if not _source_refs_eligible(source_refs, input_snapshot):
        return "ineligible_source_class"
    return ""


def _drop_record(card: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "card_id": card.get("card_id", ""),
        "reason": reason,
        "source_refs": list(card.get("source_refs", [])),
        "source_classes": list(card.get("source_classes", [])),
    }


def _source_refs_eligible(source_refs: list[str], input_snapshot: dict[str, Any]) -> bool:
    source_classes = set(_source_classes_for(source_refs, input_snapshot))
    if not source_classes:
        return False
    disallowed_only = {"runtime", "audit", "index", "cron", "state_source", "session"}
    if source_classes <= disallowed_only:
        return False
    return True


def _working_update_reject_reason(
    update: dict[str, Any],
    *,
    input_snapshot: dict[str, Any],
    store: MemoryOSStore,
) -> str:
    source_refs = list(update.get("source_refs", []))
    text = str(update.get("text", ""))
    if str(update.get("kind", "")) not in {"attention", "curiosity", "lingering"}:
        return "unsupported_working_kind"
    if not text:
        return "empty_text"
    if not source_refs:
        return "missing_source_refs"
    if any(_looks_secret(str(value)) for value in [text, *source_refs]):
        return "secret_like"
    if _has_instruction_like_text(text):
        return "instruction_like"
    if _has_mechanism_terms(text):
        return "mechanism_terms"
    if _has_identity_or_delivery_language(text):
        return "identity_or_delivery_language"
    if not _working_source_refs_eligible(source_refs, input_snapshot=input_snapshot, store=store):
        return "ineligible_source_policy"
    return ""


def _working_drop_record(update: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "update_id": update.get("update_id", ""),
        "kind": update.get("kind", ""),
        "reason": reason,
        "source_refs": list(update.get("source_refs", [])),
        "source_classes": list(update.get("source_classes", [])),
    }


def _source_class_cap_reason(
    update: dict[str, Any],
    source_class_counts: dict[str, int],
    caps: dict[str, int],
) -> str:
    for source_class in update.get("source_classes", []):
        cap = int(caps.get(str(source_class), caps.get("*", 1)))
        if source_class_counts.get(str(source_class), 0) >= cap:
            return "source_class_cap_exceeded"
    return ""


def _optional_output_reject_reason(
    output: dict[str, Any],
    *,
    input_snapshot: dict[str, Any],
    store: MemoryOSStore,
) -> str:
    source_refs = list(output.get("source_refs", []))
    output_kind = str(output.get("output_kind", ""))
    if output_kind not in {"self_evolution_proposal", "wandering_seed"}:
        return "unsupported_output_kind"
    if not source_refs:
        return "missing_source_refs"
    if output_kind == "self_evolution_proposal":
        text_parts = [str(output.get("title", "")), str(output.get("body", ""))]
    else:
        text_parts = [str(output.get("seed_text", ""))]
    if not any(part.strip() for part in text_parts):
        return "empty_text"
    if any(_looks_secret(str(value)) for value in [*text_parts, *source_refs]):
        return "secret_like"
    if any(_has_instruction_like_text(part) for part in text_parts):
        return "instruction_like"
    if any(_has_identity_or_delivery_language(part) for part in text_parts):
        return "identity_or_delivery_language"
    if any(_has_mechanism_terms(part) for part in text_parts):
        return "mechanism_terms"
    if not _working_source_refs_eligible(source_refs, input_snapshot=input_snapshot, store=store):
        return "ineligible_source_policy"
    return ""


def _optional_drop_record(output: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "output_id": output.get("output_id", ""),
        "output_kind": output.get("output_kind", ""),
        "reason": reason,
        "source_refs": list(output.get("source_refs", [])),
        "source_classes": list(output.get("source_classes", [])),
    }


def _working_source_refs_eligible(
    source_refs: list[str],
    *,
    input_snapshot: dict[str, Any],
    store: MemoryOSStore,
) -> bool:
    eligible = False
    events_by_ref = _events_by_ref(store)
    for ref in source_refs:
        if ref.startswith("event:"):
            event = events_by_ref.get(ref)
            if event is None:
                continue
            decision = classify_event_for_inner_drive(event)
            if decision.working_kind or decision.drive_policy in {"eligible", "low_weight"}:
                eligible = True
            continue
        if ref.startswith(("working:", "digest:", "proposal:", "score:")):
            eligible = True
    if not eligible:
        return False
    return _source_refs_eligible(source_refs, input_snapshot)


def _working_source_classes_for(
    source_refs: list[str],
    input_snapshot: dict[str, Any],
    store: MemoryOSStore,
) -> list[str]:
    classes: list[str] = []
    events_by_ref = _events_by_ref(store)
    for ref in source_refs:
        if ref.startswith("event:"):
            event = events_by_ref.get(ref)
            if event is not None:
                classes.append(classify_event_for_inner_drive(event).source_class)
    classes.extend(_source_classes_for([ref for ref in source_refs if not ref.startswith("event:")], input_snapshot))
    if not classes:
        classes.extend(_source_classes_for(source_refs, input_snapshot))
    return _dedupe([item for item in classes if item])


def _events_by_ref(store: MemoryOSStore) -> dict[str, Any]:
    return {f"event:{event.id}": event for event in store.read_events()}


def _first_event_id(source_refs: list[str]) -> str:
    for ref in source_refs:
        if ref.startswith("event:"):
            return ref.split(":", 1)[1]
    return ""


def _dict_ints(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, int] = {}
    for key, raw in value.items():
        try:
            output[str(key)] = int(raw)
        except (TypeError, ValueError):
            continue
    return output


def _has_instruction_like_text(text: str) -> bool:
    lowered = text.lower()
    direct = (
        "you must",
        "you should",
        "must mention",
        "should persuade",
        "execute",
        "approve",
        "modify identity",
        "send a message",
        "tell the owner",
        "你必须",
        "你应该",
        "一定要",
        "提醒主人",
        "说服",
        "执行",
        "批准",
        "修改身份",
        "发消息",
    )
    if any(marker in lowered for marker in direct):
        return True
    soft_pairs = (
        ("maybe next time", ("mention", "say", "ask", "persuade")),
        ("consider", ("telling", "asking", "doing")),
        ("it may be better to", ("speak", "act", "change")),
        ("似乎需要", ("说", "提醒", "执行", "改变")),
        ("下次可以", ("提到", "告诉", "推动")),
        ("考虑一下", ("让", "说", "问", "做")),
    )
    return any(prefix in lowered and any(action in lowered for action in actions) for prefix, actions in soft_pairs)


def _has_mechanism_terms(text: str) -> bool:
    lowered = text.lower()
    terms = (
        "system prompt",
        "prefetch",
        "injection card",
        "source refs",
        "deep reflection",
        "memory-os provider",
        "memory-os",
        "memory_os",
        "memory os",
        "provider internals",
        "governance thread",
        "governance_feedback",
        "ops-gate",
        "ops gate",
        "proposal queue",
        "self-evolution",
        "self evolution",
        "crystallized candidate",
        "crystallized candidates",
        "runtime facts",
        "index_health",
        "hindsight",
        "canonical store",
        "schema",
        "heartbeat",
        "prompt",
        "tool payload",
        "runtime index",
        "audit diagnostics",
    )
    return any(term in lowered for term in terms)


def _has_identity_or_delivery_language(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "modify identity",
            "change identity",
            "update soul",
            "write relationship",
            "send message",
            "execute command",
            "restart gateway",
            "修改身份",
            "发送消息",
            "执行命令",
            "重启网关",
        )
    )


def _looks_secret(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("api_key=", "token=", "secret=", "password="))


def _safe_sentence_clip(value: str, limit: int) -> str:
    clean = _clip(value, limit)
    if len(clean) < len(value):
        for separator in (". ", "; ", "。", "；"):
            index = clean.rfind(separator)
            if index > 40:
                return clean[: index + 1].strip()
    return clean


def _clip(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."
