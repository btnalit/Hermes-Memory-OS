"""Advisory grounded-expression cross-check judge."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERDICT_CLASSES = ("grounded", "confabulation", "blind_spot", "unresolvable")


def grounded_expression_judge_manifest() -> dict[str, Any]:
    return {
        "name": "grounded_expression_judge",
        "kind": "expression",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0"],
            "optional": ["hindsight_adapter", "confabulation_detector"],
        },
        "provides": {
            "commands": ["status", "doctor", "judge"],
            "schedules": ["grounded_expression_judge_shadow"],
            "reads": ["local_artifact.right_brain_expression", "local_artifact.evidence_profile"],
            "writes": ["local_artifact.grounded_expression_judge"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "advisory-only",
            "profile_scope": "per-profile",
        },
    }


class GroundedExpressionJudge:
    def __init__(
        self,
        hermes_home: str | Path | None = None,
        *,
        profile: str = "default",
        hindsight_adapter_enabled: bool = False,
        alternate_left_map_substrate: bool = False,
    ) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve() if hermes_home is not None else None
        self.profile = profile
        self.hindsight_adapter_enabled = hindsight_adapter_enabled
        self.alternate_left_map_substrate = alternate_left_map_substrate

    @property
    def module_root(self) -> Path:
        base = self.hermes_home if self.hermes_home is not None else Path(".")
        return base / "system-modules" / "grounded_expression_judge"

    @property
    def verdicts_path(self) -> Path:
        return self.module_root / "verdicts.jsonl"

    def run_once(
        self,
        *,
        right_brain_result: dict[str, Any] | None = None,
        confabulation_result: dict[str, Any] | None = None,
        evidence_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        right_brain_claim = _right_brain_claim(right_brain_result or {}, hermes_home=self.hermes_home)
        if _claim_is_silent(right_brain_claim):
            backlog_claim = _next_unjudged_wandering_output_claim(self.hermes_home, self.verdicts_path)
            if backlog_claim:
                right_brain_claim = backlog_claim
            else:
                return self._base_verdict(
                    status="skipped",
                    decision="no_expression_to_judge",
                    verdict_class="skipped",
                    code="no_expression_to_judge",
                    owner_escalation_required=False,
                    audit_action="grounded_expression_no_expression_to_judge",
                )
        left_brain_map = _left_brain_map(
            right_brain_claim=right_brain_claim,
            confabulation_result=confabulation_result or {},
            evidence_result=evidence_result or {},
        )
        return self.judge(right_brain_claim=right_brain_claim, left_brain_map=left_brain_map)

    def judge(self, *, right_brain_claim: dict[str, Any], left_brain_map: dict[str, Any]) -> dict[str, Any]:
        left_brain_map = _normalize_left_brain_map(left_brain_map)
        if not _left_map_substrate_available(left_brain_map):
            verdict = self._base_verdict(
                status="warning",
                decision="advisory_unavailable",
                verdict_class="unresolvable",
                code="left_map_substrate_unavailable",
                owner_escalation_required=False,
                audit_action="left_map_substrate_unavailable",
            )
            verdict["delivery_authority_blocked"] = True
            self._attach_grounding_fields(verdict, right_brain_claim=right_brain_claim, left_brain_map=left_brain_map)
            self._write_verdict(verdict)
            return verdict

        verdict_class = _classify_verdict(right_brain_claim=right_brain_claim, left_brain_map=left_brain_map)
        if verdict_class == "unresolvable":
            verdict = self._base_verdict(
                status="ok",
                decision="unresolvable",
                verdict_class=verdict_class,
                code="cross_check_unresolvable",
                owner_escalation_required=True,
                audit_action="cross_check_unresolvable_escalated",
            )
        elif verdict_class == "confabulation":
            verdict = self._base_verdict(
                status="ok",
                decision="confabulation",
                verdict_class=verdict_class,
                code="cross_check_confabulation",
                owner_escalation_required=True,
                audit_action="cross_check_confabulation_recorded",
            )
        elif verdict_class == "blind_spot":
            verdict = self._base_verdict(
                status="ok",
                decision="blind_spot",
                verdict_class=verdict_class,
                code="cross_check_blind_spot",
                owner_escalation_required=True,
                audit_action="cross_check_blind_spot_recorded",
            )
        else:
            verdict = self._base_verdict(
                status="ok",
                decision="advisory_ok",
                verdict_class=verdict_class,
                code="cross_check_advisory_ok",
                owner_escalation_required=False,
                audit_action="cross_check_advisory_recorded",
            )
        self._attach_grounding_fields(verdict, right_brain_claim=right_brain_claim, left_brain_map=left_brain_map)
        self._write_verdict(verdict)
        return verdict

    def status(self) -> dict[str, Any]:
        verdicts = _read_jsonl(self.verdicts_path)
        verdict_distribution = _verdict_distribution(verdicts)
        coverage_floor_met_count = sum(1 for item in verdicts if item.get("left_map_coverage_floor_met") is True)
        latest_left_map_snapshot_version = ""
        for item in reversed(verdicts):
            latest_left_map_snapshot_version = str(item.get("left_map_snapshot_version") or "")
            if latest_left_map_snapshot_version:
                break
        distribution_degenerate = _distribution_degenerate(verdict_distribution, len(verdicts))
        return {
            "schema_version": "hermes.grounded_expression_judge_status.v0",
            "module": "grounded_expression_judge",
            "profile": self.profile,
            "status": "ok" if verdicts else "missing",
            "hindsight_adapter_enabled": self.hindsight_adapter_enabled,
            "alternate_left_map_substrate_configured": self.alternate_left_map_substrate,
            "verdict_count": len(verdicts),
            "verdict_distribution": verdict_distribution,
            "grounded_count": verdict_distribution["grounded"],
            "confabulation_count": verdict_distribution["confabulation"],
            "blind_spot_count": verdict_distribution["blind_spot"],
            "unresolvable_count": verdict_distribution["unresolvable"],
            "left_map_substrate_warning_count": sum(
                1 for item in verdicts if item.get("code") == "left_map_substrate_unavailable"
            ),
            "left_map_coverage_floor_met_count": coverage_floor_met_count,
            "latest_left_map_snapshot_version": latest_left_map_snapshot_version,
            "verdict_distribution_degenerate": distribution_degenerate,
            "substrate_unavailable_blocker_cleared": coverage_floor_met_count > 0 and not distribution_degenerate,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "delivery_affected": False,
            "delivery_gated": False,
            "policy_live_applied": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        status = self.status()
        if not self.hindsight_adapter_enabled and int(status.get("left_map_coverage_floor_met_count") or 0) <= 0:
            code = "alternate_left_map_substrate_unproven" if self.alternate_left_map_substrate else "left_map_substrate_unavailable"
            findings.append(
                {
                    "severity": "warning",
                    "code": code,
                    "message": "Grounded-expression delivery authority cannot flip without observed Hindsight or alternate left-map substrate.",
                }
            )
        return {
            "schema_version": "hermes.grounded_expression_judge_doctor.v0",
            "module": "grounded_expression_judge",
            "profile": self.profile,
            "status": "warning" if findings else "ok",
            "findings": findings,
        }

    def _base_verdict(
        self,
        *,
        status: str,
        decision: str,
        verdict_class: str,
        code: str,
        owner_escalation_required: bool,
        audit_action: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "hermes.grounded_expression_verdict.v0",
            "module": "grounded_expression_judge",
            "profile": self.profile,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "decision": decision,
            "verdict_class": verdict_class,
            "code": code,
            "owner_escalation_required": owner_escalation_required,
            "audit_action": audit_action,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "delivery_affected": False,
            "delivery_gated": False,
            "delivery_authority_blocked": False,
            "policy_live_applied": False,
            "live_behavior_changed": False,
        }

    def _attach_grounding_fields(
        self,
        verdict: dict[str, Any],
        *,
        right_brain_claim: dict[str, Any],
        left_brain_map: dict[str, Any],
    ) -> None:
        verdict.update(
            {
                "right_brain_grounded": right_brain_claim.get("grounded") is True,
                "hindsight_adapter_enabled": self.hindsight_adapter_enabled,
                "alternate_left_map_substrate_configured": self.alternate_left_map_substrate,
                "left_map_snapshot_version": str(left_brain_map.get("snapshot_version") or ""),
                "left_map_coverage": str(left_brain_map.get("coverage") or "none"),
                "left_map_coverage_floor_met": left_brain_map.get("coverage_floor_met") is True,
                "left_map_evidence_count": int(left_brain_map.get("evidence_count") or 0),
                "left_map_confabulation_flag_count": int(left_brain_map.get("confabulation_flag_count") or 0),
                "left_map_confabulation_weighting": str(left_brain_map.get("confabulation_weighting") or "none"),
                "left_map_lookup_ref_count": len(left_brain_map.get("lookup_refs") or []),
                "right_brain_artifact_kind": str(right_brain_claim.get("artifact_kind") or ""),
                "right_brain_artifact_ref": str(right_brain_claim.get("artifact_ref") or ""),
            }
        )

    def _write_verdict(self, verdict: dict[str, Any]) -> None:
        if self.hermes_home is None:
            return
        self.verdicts_path.parent.mkdir(parents=True, exist_ok=True)
        with self.verdicts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(verdict, ensure_ascii=False, sort_keys=True) + "\n")


def _right_brain_claim(result: dict[str, Any], *, hermes_home: Path | None = None) -> dict[str, Any]:
    output = str(result.get("output") or "")
    explicit_source_refs = _string_list(result.get("source_event_ids")) + _string_list(result.get("source_refs"))
    signal_summary = result.get("signal_summary") if isinstance(result.get("signal_summary"), dict) else {}
    source_event_id = str(result.get("source_event_id") or signal_summary.get("latest_event_id") or "").strip()
    output_ref = str(result.get("output_ref") or "").strip()
    lookup_refs = _lookup_refs_for_source_event(source_event_id)
    if output_ref:
        lookup_refs.append(output_ref)
        output_record = _wandering_output_by_ref(hermes_home, output_ref)
        if output_record and not source_event_id:
            lookup_refs.extend(_lookup_refs_for_source_event(str(output_record.get("source_event_id") or "")))
    return {
        "text": output,
        "grounded": bool(explicit_source_refs or output.strip() == "[SILENT]"),
        "source_refs": _unique(explicit_source_refs),
        "lookup_refs": _unique(lookup_refs),
        "artifact_kind": "wandering_mind_result" if result else "",
        "artifact_ref": output_ref,
    }


def _left_brain_map(
    *,
    right_brain_claim: dict[str, Any],
    confabulation_result: dict[str, Any],
    evidence_result: dict[str, Any],
) -> dict[str, Any]:
    lookup_refs = _string_list(right_brain_claim.get("lookup_refs"))
    if lookup_refs:
        targeted = _targeted_left_brain_map(
            lookup_refs=lookup_refs,
            confabulation_result=confabulation_result,
            evidence_result=evidence_result,
        )
        if targeted is not None:
            return targeted
    flag_count = int(confabulation_result.get("flag_count") or 0)
    evidence_count = int(evidence_result.get("evidence_count") or 0)
    return _normalize_left_brain_map(
        {
            "coverage": _coverage_for_count(evidence_count),
            "evidence_count": evidence_count,
            "confabulation_flag_count": flag_count,
            "confabulation_flagged": flag_count > 0,
            "input_fingerprint": str(evidence_result.get("input_fingerprint") or ""),
            "score_fingerprint_count": len(evidence_result.get("score_fingerprints") or []),
            "lookup_refs": lookup_refs,
        }
    )


def _targeted_left_brain_map(
    *,
    lookup_refs: list[str],
    confabulation_result: dict[str, Any],
    evidence_result: dict[str, Any],
) -> dict[str, Any] | None:
    feature_scores_path = str(evidence_result.get("feature_scores_path") or "").strip()
    if not feature_scores_path:
        return None
    feature_scores = _read_jsonl(Path(feature_scores_path))
    if not feature_scores:
        return None
    normalized_refs = set(_expand_lookup_refs(lookup_refs))
    matched_scores = [
        record
        for record in feature_scores
        if _record_matches_lookup_refs(record, normalized_refs)
    ]
    flags = confabulation_result.get("flags") if isinstance(confabulation_result.get("flags"), list) else []
    matched_flags = [
        flag
        for flag in flags
        if _record_matches_lookup_refs(flag, normalized_refs)
    ]
    return _normalize_left_brain_map(
        {
            "coverage": _coverage_for_count(len(matched_scores)),
            "evidence_count": len(matched_scores),
            "confabulation_flag_count": len(matched_flags),
            "confabulation_flagged": bool(matched_flags),
            "input_fingerprint": str(evidence_result.get("input_fingerprint") or ""),
            "score_fingerprint_count": len(matched_scores),
            "lookup_refs": sorted(normalized_refs),
        }
    )


def _normalize_left_brain_map(left_brain_map: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(left_brain_map, dict) or not left_brain_map:
        return {
            "coverage": "none",
            "coverage_floor_met": False,
            "evidence_count": 0,
            "confabulation_flag_count": 0,
            "confabulation_flagged": False,
            "confabulation_weighting": "none",
            "snapshot_version": "",
        }
    normalized = dict(left_brain_map)
    coverage = str(normalized.get("coverage") or "").strip().lower()
    evidence_count = _int_value(normalized.get("evidence_count"))
    if evidence_count == 0:
        if coverage == "thin":
            evidence_count = 1
        elif coverage == "covered":
            evidence_count = 2
    if coverage not in {"none", "thin", "covered"}:
        coverage = _coverage_for_count(evidence_count)
    flag_count = _int_value(
        normalized.get("confabulation_flag_count", normalized.get("left_map_confabulation_flag_count"))
    )
    if flag_count == 0:
        flag_count = _int_value(normalized.get("flag_count"))
    confabulation_flagged = normalized.get("confabulation_flagged") is True or flag_count > 0
    if confabulation_flagged and flag_count == 0:
        flag_count = 1
    coverage_floor_met = evidence_count >= 2
    snapshot_payload = {
        "coverage": coverage,
        "evidence_count": evidence_count,
        "confabulation_flag_count": flag_count,
        "confabulation_flagged": confabulation_flagged,
        "input_fingerprint": str(normalized.get("input_fingerprint") or ""),
        "score_fingerprint_count": _int_value(normalized.get("score_fingerprint_count")),
    }
    normalized.update(
        {
            "coverage": coverage,
            "coverage_floor_met": coverage_floor_met,
            "evidence_count": evidence_count,
            "confabulation_flag_count": flag_count,
            "confabulation_flagged": confabulation_flagged,
            "confabulation_weighting": "demote_flagged_left_map_records" if confabulation_flagged else "normal",
            "snapshot_version": str(normalized.get("snapshot_version") or _snapshot_version(snapshot_payload)),
            "lookup_refs": _string_list(normalized.get("lookup_refs")),
        }
    )
    return normalized


def _coverage_for_count(evidence_count: int) -> str:
    if evidence_count <= 0:
        return "none"
    if evidence_count == 1:
        return "thin"
    return "covered"


def _left_map_substrate_available(left_brain_map: dict[str, Any]) -> bool:
    return int(left_brain_map.get("evidence_count") or 0) > 0 and str(left_brain_map.get("coverage") or "") in {
        "thin",
        "covered",
    }


def _classify_verdict(*, right_brain_claim: dict[str, Any], left_brain_map: dict[str, Any]) -> str:
    confabulation_flagged = left_brain_map.get("confabulation_flagged") is True
    coverage_floor_met = left_brain_map.get("coverage_floor_met") is True
    if confabulation_flagged and not coverage_floor_met:
        return "unresolvable"
    if confabulation_flagged:
        return "confabulation"
    if right_brain_claim.get("grounded") is False and not coverage_floor_met:
        return "blind_spot"
    return "grounded"


def _snapshot_version(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "leftmap_" + hashlib.sha256(encoded).hexdigest()[:16]


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _verdict_distribution(verdicts: list[dict[str, Any]]) -> dict[str, int]:
    distribution = {key: 0 for key in VERDICT_CLASSES}
    for item in verdicts:
        verdict_class = str(item.get("verdict_class") or "")
        if verdict_class not in distribution:
            decision = str(item.get("decision") or "")
            if decision == "advisory_ok":
                verdict_class = "grounded"
            elif decision in distribution:
                verdict_class = decision
            elif item.get("code") == "left_map_substrate_unavailable":
                verdict_class = "unresolvable"
            else:
                verdict_class = "unresolvable"
        distribution[verdict_class] += 1
    return distribution


def _distribution_degenerate(distribution: dict[str, int], verdict_count: int) -> bool:
    if verdict_count <= 0:
        return True
    non_zero_classes = [key for key, value in distribution.items() if value > 0]
    if len(non_zero_classes) < 2:
        return True
    if distribution.get("grounded") == verdict_count or distribution.get("unresolvable") == verdict_count:
        return True
    return False


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


def _claim_is_silent(claim: dict[str, Any]) -> bool:
    return str(claim.get("text") or "").strip() == "[SILENT]" and not claim.get("artifact_ref")


def _next_unjudged_wandering_output_claim(hermes_home: Path | None, verdicts_path: Path) -> dict[str, Any]:
    if hermes_home is None:
        return {}
    judged_refs = {
        str(item.get("right_brain_artifact_ref") or "")
        for item in _read_jsonl(verdicts_path)
        if str(item.get("right_brain_artifact_ref") or "")
    }
    outputs_path = hermes_home / "system-modules" / "wandering_mind" / "outputs.jsonl"
    for record in _read_jsonl(outputs_path):
        output = str(record.get("output") or "")
        if not output.strip() or output.strip() == "[SILENT]":
            continue
        artifact_ref = str(record.get("output_ref") or "").strip()
        if not artifact_ref:
            artifact_ref = f"local://wandering_mind/{record.get('id')}"
        if artifact_ref in judged_refs:
            continue
        return {
            "text": output,
            "grounded": bool(record.get("source_refs")),
            "source_refs": _string_list(record.get("source_refs")),
            "lookup_refs": _unique([artifact_ref, *_lookup_refs_for_source_event(str(record.get("source_event_id") or ""))]),
            "artifact_kind": "wandering_mind_output",
            "artifact_ref": artifact_ref,
        }
    return {}


def _wandering_output_by_ref(hermes_home: Path | None, output_ref: str) -> dict[str, Any]:
    if hermes_home is None or not output_ref:
        return {}
    outputs_path = hermes_home / "system-modules" / "wandering_mind" / "outputs.jsonl"
    for record in _read_jsonl(outputs_path):
        if str(record.get("output_ref") or "") == output_ref:
            return record
    return {}


def _lookup_refs_for_source_event(source_event_id: str) -> list[str]:
    source_event_id = str(source_event_id or "").strip()
    if not source_event_id:
        return []
    return [f"event:{source_event_id}", f"memory_os:event:{source_event_id}"]


def _expand_lookup_refs(refs: list[str]) -> list[str]:
    expanded: list[str] = []
    for ref in refs:
        ref = str(ref or "").strip()
        if not ref:
            continue
        expanded.append(ref)
        if ref.startswith("event:"):
            expanded.append("memory_os:" + ref)
        elif ref.startswith("memory_os:event:"):
            expanded.append(ref.removeprefix("memory_os:"))
    return _unique(expanded)


def _record_matches_lookup_refs(record: dict[str, Any], lookup_refs: set[str]) -> bool:
    values = {
        str(record.get("subject_ref") or ""),
        str(record.get("source_ref") or ""),
        str(record.get("subject") or ""),
    }
    values.update(_string_list(record.get("source_refs")))
    return any(value in lookup_refs for value in values if value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = [str(item) for item in value]
    else:
        values = [str(value)]
    return [item.strip() for item in values if item and item.strip()]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values
