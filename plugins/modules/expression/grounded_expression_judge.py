"""Advisory grounded-expression cross-check judge."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
        hindsight_adapter_enabled: bool = True,
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
        right_brain_claim = _right_brain_claim(right_brain_result or {})
        left_brain_map = _left_brain_map(
            confabulation_result=confabulation_result or {},
            evidence_result=evidence_result or {},
        )
        return self.judge(right_brain_claim=right_brain_claim, left_brain_map=left_brain_map)

    def judge(self, *, right_brain_claim: dict[str, Any], left_brain_map: dict[str, Any]) -> dict[str, Any]:
        if not self.hindsight_adapter_enabled and not left_brain_map and not self.alternate_left_map_substrate:
            verdict = self._base_verdict(
                status="warning",
                decision="advisory_unavailable",
                code="left_map_substrate_unavailable",
                owner_escalation_required=False,
                audit_action="left_map_substrate_unavailable",
            )
            verdict["delivery_authority_blocked"] = True
            self._write_verdict(verdict)
            return verdict

        ungrounded_right = right_brain_claim.get("grounded") is False
        thin_left = str(left_brain_map.get("coverage") or "") == "thin"
        confabulation_flagged = left_brain_map.get("confabulation_flagged") is True
        if ungrounded_right and (thin_left or confabulation_flagged):
            verdict = self._base_verdict(
                status="ok",
                decision="unresolvable",
                code="cross_check_unresolvable",
                owner_escalation_required=True,
                audit_action="cross_check_unresolvable_escalated",
            )
        else:
            verdict = self._base_verdict(
                status="ok",
                decision="advisory_ok",
                code="cross_check_advisory_ok",
                owner_escalation_required=False,
                audit_action="cross_check_advisory_recorded",
            )
        self._write_verdict(verdict)
        return verdict

    def status(self) -> dict[str, Any]:
        verdicts = _read_jsonl(self.verdicts_path)
        return {
            "schema_version": "hermes.grounded_expression_judge_status.v0",
            "module": "grounded_expression_judge",
            "profile": self.profile,
            "status": "ok" if verdicts else "missing",
            "verdict_count": len(verdicts),
            "unresolvable_count": sum(1 for item in verdicts if item.get("decision") == "unresolvable"),
            "left_map_substrate_warning_count": sum(
                1 for item in verdicts if item.get("code") == "left_map_substrate_unavailable"
            ),
            "actual_send": False,
            "actual_execute": False,
            "delivery_gated": False,
            "policy_live_applied": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        if not self.hindsight_adapter_enabled and not self.alternate_left_map_substrate:
            findings.append(
                {
                    "severity": "warning",
                    "code": "left_map_substrate_unavailable",
                    "message": "Grounded-expression delivery authority cannot flip without Hindsight or alternate left-map substrate.",
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
            "code": code,
            "owner_escalation_required": owner_escalation_required,
            "audit_action": audit_action,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "delivery_gated": False,
            "delivery_authority_blocked": False,
            "policy_live_applied": False,
            "live_behavior_changed": False,
        }

    def _write_verdict(self, verdict: dict[str, Any]) -> None:
        if self.hermes_home is None:
            return
        self.verdicts_path.parent.mkdir(parents=True, exist_ok=True)
        with self.verdicts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(verdict, ensure_ascii=False, sort_keys=True) + "\n")


def _right_brain_claim(result: dict[str, Any]) -> dict[str, Any]:
    output = str(result.get("output") or "")
    return {
        "grounded": bool(result.get("source_event_ids") or result.get("source_refs") or output.strip() == "[SILENT]"),
    }


def _left_brain_map(*, confabulation_result: dict[str, Any], evidence_result: dict[str, Any]) -> dict[str, Any]:
    flag_count = int(confabulation_result.get("flag_count") or 0)
    evidence_count = int(evidence_result.get("evidence_count") or 0)
    return {
        "coverage": "thin" if evidence_count <= 1 else "covered",
        "confabulation_flagged": flag_count > 0,
    }


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
