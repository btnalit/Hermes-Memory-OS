"""Speak Gate expression module for portable Hermes deployments."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def speak_gate_manifest() -> dict[str, Any]:
    """Return the v0.1 Speak Gate module manifest."""

    return {
        "name": "speak_gate",
        "kind": "expression",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler", "proposal_queue"],
            "optional": ["delivery_sink"],
        },
        "provides": {
            "commands": ["status", "doctor", "evaluate-prompt", "evaluate-delivery"],
            "schedules": [],
            "reads": ["memory_os.events.summary", "local_artifact.proposal_queue_state"],
            "writes": ["local_artifact.speak_gate_would_send"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "would-send",
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


class SpeakGateModule:
    """Decide whether expression would happen without sending anything."""

    def __init__(
        self,
        hermes_home: str | Path,
        *,
        profile: str,
        delivery_mode: str = "would-send",
        diagnostic_grounding_enabled: bool | None = None,
    ) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile
        self.delivery_mode = delivery_mode
        self.diagnostic_grounding_enabled = (
            profile != "sannai" if diagnostic_grounding_enabled is None else bool(diagnostic_grounding_enabled)
        )

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "speak_gate"

    @property
    def would_send_path(self) -> Path:
        return self.module_root / "would_send.jsonl"

    def status(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.speak_gate_status.v0",
            "module": "speak_gate",
            "profile": self.profile,
            "delivery_mode": self.delivery_mode,
            "diagnostic_grounding_enabled": self.diagnostic_grounding_enabled,
            "would_send_count": len(self.read_would_send_records()),
            "actual_send": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if self.delivery_mode == "send":
            findings.append(
                {
                    "severity": "error",
                    "code": "delivery_send_enabled",
                    "message": "Speak Gate v0.1 records would-send only; real send is disabled",
                }
            )
        if self.profile == "sannai" and self.diagnostic_grounding_enabled:
            findings.append(
                {
                    "severity": "warning",
                    "code": "sannai_diagnostic_grounding_enabled",
                    "message": "Sannai diagnostic grounding is explicit-only and may affect personality continuity",
                }
            )
        if any(finding["severity"] == "error" for finding in findings):
            status = "error"
        elif findings:
            status = "warning"
        else:
            status = "ok"
        return {
            "schema_version": "hermes.speak_gate_doctor.v0",
            "module": "speak_gate",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }

    def evaluate_prompt(self, prompt: str) -> dict[str, Any]:
        text = str(prompt)
        if _is_self_memory_prompt(text):
            return _prompt_decision(
                profile=self.profile,
                context_mode="ordinary_self_memory",
                diagnostic=False,
                system_report_allowed=False,
            )
        diagnostic = self.diagnostic_grounding_enabled and _is_diagnostic_prompt(text)
        if diagnostic:
            return _prompt_decision(
                profile=self.profile,
                context_mode="diagnostic_runtime_facts",
                diagnostic=True,
                system_report_allowed=True,
            )
        return _prompt_decision(
            profile=self.profile,
            context_mode="ordinary_recall",
            diagnostic=False,
            system_report_allowed=False,
        )

    def evaluate_delivery(
        self,
        *,
        payload_ref: str,
        source_module: str,
        channel: str,
        reason: str = "",
    ) -> dict[str, Any]:
        if self.delivery_mode == "no-send":
            return self._delivery_result(
                decision="no_send",
                payload_ref=payload_ref,
                source_module=source_module,
                channel=channel,
                reason=reason or "delivery_disabled_no_send",
            )
        if self.delivery_mode == "send":
            return self._delivery_result(
                decision="send_blocked",
                payload_ref=payload_ref,
                source_module=source_module,
                channel=channel,
                reason=reason or "real_send_disabled_in_v0_1",
            )
        record = self._record_would_send(
            payload_ref=payload_ref,
            source_module=source_module,
            channel=channel,
            reason=reason or "would_send_only",
        )
        result = self._delivery_result(
            decision="would_send",
            payload_ref=payload_ref,
            source_module=source_module,
            channel=channel,
            reason=reason or "would_send_only",
        )
        result["would_send_ref"] = record["id"]
        return result

    def evaluate_wandering_output(self, output: str, *, channel: str) -> dict[str, Any]:
        if not output.strip() or output.strip() == "[SILENT]":
            return self._delivery_result(
                decision="no_send",
                payload_ref="local://wandering_mind/silent",
                source_module="wandering_mind",
                channel=channel,
                reason="wandering_mind_silent",
            )
        return self.evaluate_delivery(
            payload_ref=f"local://wandering_mind/output/{_stable_suffix(output)}",
            source_module="wandering_mind",
            channel=channel,
            reason="wandering_mind_right_brain",
        )

    def evaluate_proposal(self, candidate_id: str, *, proposal_queue: Any, channel: str = "origin") -> dict[str, Any]:
        candidate = _find_candidate(proposal_queue.read_queue(), candidate_id)
        if not candidate or candidate.get("state") != "approved_for_proposal":
            return self._delivery_result(
                decision="no_send",
                payload_ref=f"local://proposal_queue/{candidate_id}",
                source_module="proposal_queue",
                channel=channel,
                reason="proposal_not_approved",
            )
        return self.evaluate_delivery(
            payload_ref=f"local://proposal_queue/{candidate_id}",
            source_module="proposal_queue",
            channel=channel,
            reason="proposal_queue_approved",
        )

    def read_would_send_records(self) -> list[dict[str, Any]]:
        if not self.would_send_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.would_send_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    records.append(parsed)
        return records

    def _record_would_send(
        self,
        *,
        payload_ref: str,
        source_module: str,
        channel: str,
        reason: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        record = {
            "schema_version": "hermes.speak_gate_would_send.v0",
            "id": f"sgws_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
            "ts": now.isoformat(),
            "profile": self.profile,
            "module": "speak_gate",
            "source_module": source_module,
            "delivery_mode": "would-send",
            "actual_send": False,
            "channel": channel,
            "payload_ref": payload_ref,
            "reason": reason,
        }
        self.would_send_path.parent.mkdir(parents=True, exist_ok=True)
        with self.would_send_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return record

    def _delivery_result(
        self,
        *,
        decision: str,
        payload_ref: str,
        source_module: str,
        channel: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "hermes.speak_gate_delivery_decision.v0",
            "module": "speak_gate",
            "profile": self.profile,
            "decision": decision,
            "requested_delivery_mode": self.delivery_mode,
            "actual_send": False,
            "source_module": source_module,
            "channel": channel,
            "payload_ref": payload_ref,
            "reason": reason,
        }


def _prompt_decision(
    *,
    profile: str,
    context_mode: str,
    diagnostic: bool,
    system_report_allowed: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "hermes.speak_gate_prompt_decision.v0",
        "module": "speak_gate",
        "profile": profile,
        "context_mode": context_mode,
        "diagnostic": diagnostic,
        "system_report_allowed": system_report_allowed,
    }


def _is_diagnostic_prompt(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "当前记忆架构",
        "memory provider",
        "canonical store",
        "hindsight",
        "memory-os",
        "memory os",
        "记忆系统",
        "provider",
    )
    return any(marker in lowered for marker in markers)


def _is_self_memory_prompt(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "你还记得",
            "还记得我们",
            "心里在想什么",
            "self memory",
            "关系记忆",
        )
    )


def _find_candidate(queue: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    for item in queue.get("items", []):
        if item.get("candidate_id") == candidate_id:
            return dict(item)
    return {}


def _stable_suffix(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
