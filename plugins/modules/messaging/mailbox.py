"""No-send mailbox module scaffold for portable Hermes deployments."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


_MAILBOX_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _configured_mailbox_root(hermes_home: Path) -> Path | None:
    """Resolve a per-agent mailbox root from config.yaml.

    Reads ``platforms.mailbox.extra.root`` and ``platforms.mailbox.extra.agent_id``
    from ``<hermes_home>/config.yaml``. Both fields must be present and valid
    (``agent_id`` must match ``[A-Za-z0-9_-]{1,64}``) for a configured root to
    be returned; a relative ``root`` is resolved against ``hermes_home``. The
    returned path is the bare per-agent directory (``<root>/agents/<agent_id>``);
    ``inbox_root``/``outbox_root`` append their own suffixes on top of it, the
    same way they do for the hardcoded ``hermes_home / "mailbox"`` default.

    Returns ``None`` -- never raises -- when config.yaml is absent, unreadable,
    malformed, or the mailbox/extra fields are missing or invalid, so callers
    fall back to the hardcoded default unchanged.
    """
    config_path = hermes_home / "config.yaml"
    if not config_path.is_file():
        return None
    try:
        import yaml

        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(loaded, dict):
        return None
    platforms = loaded.get("platforms")
    mailbox_cfg = platforms.get("mailbox") if isinstance(platforms, dict) else None
    extra = mailbox_cfg.get("extra") if isinstance(mailbox_cfg, dict) else None
    if not isinstance(extra, dict):
        return None
    raw_root = extra.get("root")
    agent_id = extra.get("agent_id")
    if not isinstance(raw_root, str) or not raw_root.strip():
        return None
    if not isinstance(agent_id, str) or not _MAILBOX_AGENT_ID_PATTERN.fullmatch(agent_id):
        return None
    root_path = Path(raw_root.strip())
    if not root_path.is_absolute():
        root_path = hermes_home / root_path
    return root_path / "agents" / agent_id


def mailbox_manifest() -> dict[str, Any]:
    """Return the v0.1 mailbox module manifest."""

    return {
        "name": "mailbox",
        "kind": "messaging",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["delivery_sink"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": [],
            "reads": ["memory_os.events.summary"],
            "writes": ["memory_os.events", "module_bus.would_send"],
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


class MailboxNoSendModule:
    """Mailbox adapter boundary with outbound delivery disabled by default."""

    def __init__(self, hermes_home: str | Path, *, profile: str, delivery_mode: str = "no-send") -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile
        self.delivery_mode = delivery_mode

    @property
    def mailbox_root(self) -> Path:
        configured = _configured_mailbox_root(self.hermes_home)
        if configured is not None:
            return configured
        return self.hermes_home / "mailbox"

    @property
    def inbox_root(self) -> Path:
        return self.mailbox_root / "inbox"

    @property
    def outbox_root(self) -> Path:
        return self.mailbox_root / "outbox"

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "mailbox"

    @property
    def would_send_path(self) -> Path:
        return self.module_root / "would_send.jsonl"

    def status(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.mailbox_status.v0",
            "module": "mailbox",
            "profile": self.profile,
            "delivery_mode": self.delivery_mode,
            "roots": {
                "mailbox_root": str(self.mailbox_root),
                "mailbox_exists": self.mailbox_root.exists(),
                "inbox_exists": self.inbox_root.exists(),
                "outbox_exists": self.outbox_root.exists(),
            },
            "would_send_count": len(self.read_would_send_records()),
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if self.delivery_mode == "send":
            findings.append(
                {
                    "severity": "error",
                    "code": "delivery_send_enabled",
                    "message": "Mailbox module is no-send by default; real send is not enabled in v0.1",
                }
            )
        if not self.mailbox_root.exists():
            findings.append(
                {
                    "severity": "warning",
                    "code": "mailbox_root_missing",
                    "message": "Mailbox root is missing; receive/status can be enabled after root setup",
                }
            )
        elif not self.mailbox_root.is_dir():
            findings.append(
                {
                    "severity": "error",
                    "code": "mailbox_root_not_directory",
                    "message": "Mailbox root exists but is not a directory",
                }
            )

        if any(finding["severity"] == "error" for finding in findings):
            status = "error"
        elif findings:
            status = "warning"
        else:
            status = "ok"
        return {
            "schema_version": "hermes.mailbox_doctor.v0",
            "module": "mailbox",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }

    def record_would_send(self, *, to: str, channel: str, payload_ref: str, reason: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        record = {
            "schema_version": "hermes.delivery_would_send.v0",
            "id": f"wsend_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
            "ts": now.isoformat(),
            "profile": self.profile,
            "module": "mailbox",
            "mode": "would_send",
            "actual_send": False,
            "to": to,
            "channel": channel,
            "payload_ref": payload_ref,
            "reason": reason,
        }
        self.would_send_path.parent.mkdir(parents=True, exist_ok=True)
        with self.would_send_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return record

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
