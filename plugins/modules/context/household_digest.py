"""Household digest module over bounded Memory-OS event summaries."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.store import MemoryOSStore


def household_digest_manifest() -> dict[str, Any]:
    """Return the v0.1 household digest module manifest."""

    return {
        "name": "household_digest",
        "kind": "context",
        "version": "0.1.0",
        "layer": "L2",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": [],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["household_digest_refresh"],
            "reads": ["memory_os.events.summary"],
            "writes": ["local_artifact.household_digest"],
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


class HouseholdDigestModule:
    """Build a local summary artifact from profile-local Memory-OS events."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "household_digest"

    @property
    def digest_path(self) -> Path:
        return self.module_root / "household_digest.md"

    @property
    def state_path(self) -> Path:
        return self.module_root / "state.json"

    def status(self) -> dict[str, Any]:
        state = self._read_state()
        counters = state.get("counters") if isinstance(state.get("counters"), dict) else {}
        return {
            "schema_version": "hermes.household_digest_status.v0",
            "module": "household_digest",
            "profile": self.profile,
            "artifact_ref": str(self.digest_path),
            "artifact_exists": self.digest_path.exists(),
            "generated_count": int(counters.get("generated_count") or 0),
            "skipped_count": int(counters.get("skipped_count") or 0),
            "latest_run_status": str(state.get("latest_run_status") or "missing"),
            "latest_skip_reason": str(state.get("latest_skip_reason") or ""),
        }

    def doctor(self, *, store: MemoryOSStore | None = None, min_events: int = 50) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        event_count = 0
        if store is None:
            findings.append(
                {
                    "severity": "warning",
                    "code": "memory_os_store_not_provided",
                    "message": "Household digest doctor needs a MemoryOSStore for event checks",
                }
            )
        else:
            event_count = len(store.read_events())
            if event_count == 0:
                findings.append(
                    {
                        "severity": "warning",
                        "code": "no_memory_os_events",
                        "message": "No Memory-OS events are available for household digest",
                    }
                )
            elif event_count < min_events:
                findings.append(
                    {
                        "severity": "warning",
                        "code": "insufficient_events",
                        "message": f"Only {event_count} events available; digest will run degraded",
                    }
                )

        return {
            "schema_version": "hermes.household_digest_doctor.v0",
            "module": "household_digest",
            "profile": self.profile,
            "status": "warning" if findings else "ok",
            "event_count": event_count,
            "findings": findings,
        }

    def build_digest(
        self,
        *,
        store: MemoryOSStore,
        limit: int = 50,
        min_events: int = 1,
    ) -> dict[str, Any]:
        events = sorted(store.read_events(), key=lambda event: event.ts)[-limit:]
        degraded = len(events) < min_events
        input_fingerprint = _input_fingerprint(
            {
                "profile": self.profile,
                "limit": limit,
                "min_events": min_events,
                "events": [
                    {
                        "id": event.id,
                        "ts": event.ts,
                        "kind": event.kind,
                        "summary": event.summary,
                    }
                    for event in events
                ],
            }
        )
        state = self._read_state()
        if (
            self.digest_path.exists()
            and str(state.get("input_fingerprint") or "") == input_fingerprint
        ):
            self._write_state(
                input_fingerprint=input_fingerprint,
                status="skipped",
                skip_reason="unchanged_input_fingerprint",
                generated_delta=0,
                skipped_delta=1,
            )
            return {
                "schema_version": "hermes.household_digest_result.v0",
                "module": "household_digest",
                "profile": self.profile,
                "status": "skipped",
                "skipped": True,
                "cadence_skipped": True,
                "reason": "unchanged_input_fingerprint",
                "event_count": len(events),
                "degraded": degraded,
                "artifact_ref": str(self.digest_path),
                "actual_send": False,
                "actual_execute": False,
            }

        now = datetime.now(timezone.utc).isoformat()
        lines = [
            "# Household Digest",
            "",
            f"generated_at: {now}",
            f"profile: {self.profile}",
            f"event_count: {len(events)}",
            f"degraded: {str(degraded).lower()}",
            "",
            "## Recent Event Summaries",
            "",
        ]
        if not events:
            lines.append("- No Memory-OS event summaries available.")
        else:
            for event in events:
                lines.append(f"- {event.ts} [{event.kind}] {event.summary}")

        self.digest_path.parent.mkdir(parents=True, exist_ok=True)
        self.digest_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

        result = {
            "schema_version": "hermes.household_digest_result.v0",
            "module": "household_digest",
            "profile": self.profile,
            "status": "ok",
            "event_count": len(events),
            "degraded": degraded,
            "artifact_ref": str(self.digest_path),
            "actual_send": False,
            "actual_execute": False,
        }
        if degraded:
            result["reason"] = "insufficient_events"
        self._write_state(
            input_fingerprint=input_fingerprint,
            status="ok",
            skip_reason="",
            generated_delta=1,
            skipped_delta=0,
        )
        return result

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "schema_version": "hermes.household_digest_state.v0",
                "profile": self.profile,
                "counters": {"generated_count": 0, "skipped_count": 0},
            }
        try:
            parsed = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        parsed.setdefault("schema_version", "hermes.household_digest_state.v0")
        parsed.setdefault("profile", self.profile)
        parsed.setdefault("counters", {"generated_count": 0, "skipped_count": 0})
        return parsed

    def _write_state(
        self,
        *,
        input_fingerprint: str,
        status: str,
        skip_reason: str,
        generated_delta: int,
        skipped_delta: int,
    ) -> None:
        state = self._read_state()
        counters = state.get("counters") if isinstance(state.get("counters"), dict) else {}
        document = {
            "schema_version": "hermes.household_digest_state.v0",
            "profile": self.profile,
            "input_fingerprint": input_fingerprint,
            "latest_run_status": status,
            "latest_skip_reason": skip_reason,
            "latest_run_at": datetime.now(timezone.utc).isoformat(),
            "counters": {
                "generated_count": int(counters.get("generated_count") or 0) + generated_delta,
                "skipped_count": int(counters.get("skipped_count") or 0) + skipped_delta,
            },
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _input_fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
