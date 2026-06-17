"""No-send Wandering Mind module over bounded Memory-OS context."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from plugins.memory.memory_os.store import MemoryOSStore


def wandering_mind_manifest() -> dict[str, Any]:
    """Return the v0.1 Wandering Mind module manifest."""

    return {
        "name": "wandering_mind",
        "kind": "cognition",
        "version": "0.1.0",
        "layer": "L2",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["household_digest", "delivery_sink"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["weekly_wandering"],
            "reads": ["memory_os.events.summary", "local_artifact.household_digest"],
            "writes": ["local_artifact.wandering_output", "module_bus.would_send"],
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


class WanderingMindModule:
    """Build bounded right-brain context and record no-send outputs."""

    def __init__(self, hermes_home: str | Path, *, profile: str, delivery_mode: str = "no-send") -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile
        self.delivery_mode = delivery_mode

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "wandering_mind"

    @property
    def household_digest_path(self) -> Path:
        return self.hermes_home / "system-modules" / "household_digest" / "household_digest.md"

    @property
    def outputs_path(self) -> Path:
        return self.module_root / "outputs.jsonl"

    @property
    def would_send_path(self) -> Path:
        return self.module_root / "would_send.jsonl"

    @property
    def state_path(self) -> Path:
        return self.module_root / "state.json"

    def status(self) -> dict[str, Any]:
        state = _read_json_dict(self.state_path)
        return {
            "schema_version": "hermes.wandering_mind_status.v0",
            "module": "wandering_mind",
            "profile": self.profile,
            "delivery_mode": self.delivery_mode,
            "household_digest_exists": self.household_digest_path.exists(),
            "would_send_count": len(self.read_would_send_records()),
            "generated_count": int(state.get("generated_count") or 0),
            "skipped_count": int(state.get("skipped_count") or 0),
            "latest_status": str(state.get("latest_status") or ""),
            "latest_reason": str(state.get("latest_reason") or ""),
        }

    def doctor(self, *, store: MemoryOSStore | None = None) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if self.delivery_mode == "send":
            findings.append(
                {
                    "severity": "error",
                    "code": "delivery_send_enabled",
                    "message": "Wandering Mind is no-send by default; real send is not enabled in v0.1",
                }
            )
        if not self.household_digest_path.exists():
            findings.append(
                {
                    "severity": "warning",
                    "code": "household_digest_missing",
                    "message": "Household digest artifact is missing; Wandering Mind may return [SILENT]",
                }
            )
        if store is not None and not store.read_events():
            findings.append(
                {
                    "severity": "warning",
                    "code": "no_memory_os_events",
                    "message": "No Memory-OS event summaries are available",
                }
            )

        if any(finding["severity"] == "error" for finding in findings):
            status = "error"
        elif findings:
            status = "warning"
        else:
            status = "ok"
        return {
            "schema_version": "hermes.wandering_mind_doctor.v0",
            "module": "wandering_mind",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }

    def build_context(self, *, store: MemoryOSStore, limit: int = 20) -> str:
        events = _right_brain_eligible_events(store.read_events())[-limit:]
        lines = [
            "# Wandering Mind Context",
            "",
            "## Household Digest",
            "",
        ]
        if self.household_digest_path.exists():
            lines.append(_filter_system_language(self.household_digest_path.read_text(encoding="utf-8").strip()))
        else:
            lines.append("_No household digest artifact._")

        lines.extend(["", "## Recent Event Summaries", ""])
        if not events:
            lines.append("- No recent event summaries.")
        for event in events:
            lines.append(f"- {event.ts}: {_filter_system_language(event.summary)}")
        return "\n".join(lines).rstrip() + "\n"

    def run_once(self, *, store: MemoryOSStore, min_events: int = 1) -> dict[str, Any]:
        events = _right_brain_eligible_events(store.read_events())
        if len(events) < min_events or not self.household_digest_path.exists():
            return {
                "schema_version": "hermes.wandering_mind_result.v0",
                "module": "wandering_mind",
                "profile": self.profile,
                "output": "[SILENT]",
                "would_send": False,
                "actual_send": False,
                "reason": "insufficient_context",
            }

        signal = self._right_brain_signal(store=store, events=events)
        state = _read_json_dict(self.state_path)
        if state.get("latest_signal_fingerprint") == signal["fingerprint"]:
            skipped_count = int(state.get("skipped_count") or 0) + 1
            self._write_state(
                {
                    **state,
                    "schema_version": "hermes.wandering_mind_state.v0",
                    "module": "wandering_mind",
                    "profile": self.profile,
                    "latest_status": "skipped",
                    "latest_reason": "unchanged_right_brain_signal",
                    "latest_signal_fingerprint": signal["fingerprint"],
                    "latest_signal": signal["summary"],
                    "skipped_count": skipped_count,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return {
                "schema_version": "hermes.wandering_mind_result.v0",
                "module": "wandering_mind",
                "profile": self.profile,
                "status": "skipped",
                "skipped": True,
                "cadence_skipped": True,
                "output": "[SILENT]",
                "would_send": False,
                "actual_send": False,
                "reason": "unchanged_right_brain_signal",
                "signal_fingerprint": signal["fingerprint"],
                "signal_summary": signal["summary"],
            }

        latest_summary = _filter_system_language(events[-1].summary)
        output = f"今天我在这些片段里停了一下：{latest_summary}"
        output_record = self._append_output(output, source_event_id=events[-1].id)
        # NOTE: V1 — would_send tracking removed from wandering_mind.
        # Delivery is now handled by cognitive_loop._spontaneous_expression
        # via speak_gate._deliver_to_owner (owner-send mode). The would_send
        # path is reserved for disabled world-level send mode only.
        generated_count = int(state.get("generated_count") or 0) + 1
        self._write_state(
            {
                **state,
                "schema_version": "hermes.wandering_mind_state.v0",
                "module": "wandering_mind",
                "profile": self.profile,
                "latest_status": "ok",
                "latest_reason": "new_right_brain_signal",
                "latest_signal_fingerprint": signal["fingerprint"],
                "latest_signal": signal["summary"],
                "latest_output_ref": output_record["output_ref"],
                "generated_count": generated_count,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return {
            "schema_version": "hermes.wandering_mind_result.v0",
            "module": "wandering_mind",
            "profile": self.profile,
            "output": output,
            "output_ref": output_record["output_ref"],
            "would_send": False,
            "actual_send": False,
            "signal_fingerprint": signal["fingerprint"],
            "signal_summary": signal["summary"],
        }

    def read_would_send_records(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.would_send_path)

    def _append_output(self, output: str, *, source_event_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        record = {
            "schema_version": "hermes.wandering_mind_output.v0",
            "id": f"wout_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
            "ts": now.isoformat(),
            "profile": self.profile,
            "module": "wandering_mind",
            "source_event_id": source_event_id,
            "output": output,
        }
        record["output_ref"] = f"local://wandering_mind/{record['id']}"
        _append_jsonl(self.outputs_path, record)
        return record

    def _record_would_send(self, *, payload_ref: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        record = {
            "schema_version": "hermes.delivery_would_send.v0",
            "id": f"wsend_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
            "ts": now.isoformat(),
            "created_at": now.isoformat(),
            "profile": self.profile,
            "module": "wandering_mind",
            "mode": "would_send",
            "actual_send": False,
            "channel": "origin",
            "payload_ref": payload_ref,
            "reason": "wandering_mind_no_send",
        }
        _append_jsonl(self.would_send_path, record)
        return record

    def _right_brain_signal(self, *, store: MemoryOSStore, events: list[Any]) -> dict[str, Any]:
        latest_event = events[-1]
        latest_outcome = _latest_jsonl_record(
            self.hermes_home / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"
        )
        feedback_records = _read_jsonl(store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl")
        latest_feedback = feedback_records[-1] if feedback_records else {}
        policy = _read_json_dict(
            self.hermes_home / "system-modules" / "right_brain_expression_adapter" / "policy.json"
        )
        summary = {
            "latest_event_id": str(getattr(latest_event, "id", "") or ""),
            "latest_event_ts": str(getattr(latest_event, "ts", "") or ""),
            "latest_event_summary_hash": _sha256_text(str(getattr(latest_event, "summary", "") or "")),
            "household_digest_exists": self.household_digest_path.exists(),
            "latest_outcome_id": str(latest_outcome.get("outcome_id") or ""),
            "latest_outcome_policy_version": latest_outcome.get("policy_version"),
            "outcome_count": len(
                _read_jsonl(self.hermes_home / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl")
            ),
            "latest_feedback_id": str(latest_feedback.get("feedback_id") or ""),
            "feedback_count": len(feedback_records),
            "policy_version": policy.get("policy_version"),
        }
        fingerprint = _sha256_text(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return {"fingerprint": fingerprint, "summary": summary}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


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


def _right_brain_eligible_events(events: list[Any]) -> list[Any]:
    eligible: list[Any] = []
    for event in sorted(events, key=lambda item: getattr(item, "ts", "")):
        source = str(getattr(event, "source", "") or "").lower()
        kind = str(getattr(event, "kind", "") or "").lower()
        safe_ref = getattr(event, "safe_ref", {}) or {}
        source_class = str(safe_ref.get("source_class") or safe_ref.get("class") or "").lower()
        if source in {"memory_os", "governance_feedback", "self_evolution", "cognitive_loop"}:
            continue
        if kind in {"governance_event", "proposal_event", "self_evolution_report"}:
            continue
        if source in {"telegram", "hermes", "hermes_gateway", "session_mirror", "fixture"}:
            eligible.append(event)
            continue
        if kind in {"conversation_turn", "synthetic_event"}:
            eligible.append(event)
            continue
        if source_class in {"foreground", "conversation", "telegram", "session"}:
            eligible.append(event)
    return eligible


def _latest_jsonl_record(path: Path) -> dict[str, Any]:
    records = _read_jsonl(path)
    return records[-1] if records else {}


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _filter_system_language(text: str) -> str:
    filtered = text
    for forbidden in ("cron", "job_id", "proposal"):
        filtered = filtered.replace(forbidden, "")
        filtered = filtered.replace(forbidden.upper(), "")
        filtered = filtered.replace(forbidden.title(), "")
    return filtered
