"""Profile-local module coordination event log."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


MODULE_BUS_SCHEMA_VERSION = "hermes.module_bus.v0"


@dataclass(frozen=True)
class ModuleBusEvent:
    schema_version: str
    id: str
    ts: str
    event_type: str
    profile: str
    module: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "ts": self.ts,
            "event_type": self.event_type,
            "profile": self.profile,
            "module": self.module,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleBusEvent":
        return cls(
            schema_version=str(data["schema_version"]),
            id=str(data["id"]),
            ts=str(data["ts"]),
            event_type=str(data["event_type"]),
            profile=str(data["profile"]),
            module=str(data["module"]),
            payload=dict(data.get("payload", {})),
        )


class ModuleBus:
    """Append-only coordination log for module status events."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def publish(
        self,
        event_type: str,
        *,
        profile: str,
        module: str,
        payload: dict[str, Any] | None = None,
    ) -> ModuleBusEvent:
        now = datetime.now(timezone.utc)
        event = ModuleBusEvent(
            schema_version=MODULE_BUS_SCHEMA_VERSION,
            id=f"mbus_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
            ts=now.isoformat(),
            event_type=event_type,
            profile=profile,
            module=module,
            payload=payload or {},
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return event

    def read_events(self, *, profile: str | None = None) -> list[ModuleBusEvent]:
        if not self.path.exists():
            return []
        events: list[ModuleBusEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                continue
            event = ModuleBusEvent.from_dict(parsed)
            if profile is None or event.profile == profile:
                events.append(event)
        return events
