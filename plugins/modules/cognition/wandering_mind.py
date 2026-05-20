"""No-send Wandering Mind module over bounded Memory-OS context."""

from __future__ import annotations

import json
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

    def status(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.wandering_mind_status.v0",
            "module": "wandering_mind",
            "profile": self.profile,
            "delivery_mode": self.delivery_mode,
            "household_digest_exists": self.household_digest_path.exists(),
            "would_send_count": len(self.read_would_send_records()),
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
        events = sorted(store.read_events(), key=lambda event: event.ts)[-limit:]
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
        events = sorted(store.read_events(), key=lambda event: event.ts)
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

        latest_summary = _filter_system_language(events[-1].summary)
        output = f"今天我在这些片段里停了一下：{latest_summary}"
        output_record = self._append_output(output, source_event_id=events[-1].id)
        would_send = self._record_would_send(payload_ref=output_record["output_ref"])
        return {
            "schema_version": "hermes.wandering_mind_result.v0",
            "module": "wandering_mind",
            "profile": self.profile,
            "output": output,
            "output_ref": output_record["output_ref"],
            "would_send": True,
            "actual_send": False,
            "would_send_ref": would_send["id"],
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


def _filter_system_language(text: str) -> str:
    filtered = text
    for forbidden in ("cron", "job_id", "proposal"):
        filtered = filtered.replace(forbidden, "")
        filtered = filtered.replace(forbidden.upper(), "")
        filtered = filtered.replace(forbidden.title(), "")
    return filtered
