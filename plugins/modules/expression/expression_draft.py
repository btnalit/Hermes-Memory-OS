"""Bounded right-brain expression draft artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.store import MemoryOSStore


EXPRESSION_DRAFT_SCHEMA_VERSION = "hermes.memory_os.expression_draft.v0"


def expression_draft_manifest() -> dict[str, Any]:
    return {
        "name": "expression_draft",
        "kind": "expression",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0"],
            "optional": ["wandering_mind", "deep_reflection", "household_digest", "speak_gate"],
        },
        "provides": {
            "commands": ["status", "doctor"],
            "schedules": [],
            "reads": ["memory_os.events.summary", "local_artifact.household_digest"],
            "writes": ["local_artifact.expression_draft"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
    }


class ExpressionDraftModule:
    """Store bounded expression drafts without sending or executing."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "expression_draft"

    @property
    def drafts_path(self) -> Path:
        return self.module_root / "drafts.jsonl"

    def status(self) -> dict[str, Any]:
        drafts = self.read_recent_drafts(limit=0)
        silent_count = sum(1 for draft in drafts if str(draft.get("text_preview") or "").strip() == "[SILENT]")
        return {
            "schema_version": "hermes.memory_os.expression_draft_status.v0",
            "module": "expression_draft",
            "profile": self.profile,
            "draft_count": len(drafts),
            "silent_count": silent_count,
            "draft_error_count": sum(1 for draft in drafts if not draft.get("draft_id")),
            "body_included": any(
                bool(draft.get("raw_body")) or bool(draft.get("raw_body_included") is True)
                for draft in drafts
            ),
            "actual_send": False,
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.memory_os.expression_draft_doctor.v0",
            "module": "expression_draft",
            "profile": self.profile,
            "status": "ok",
            "findings": [],
        }

    def build_context(self, *, store: MemoryOSStore, max_refs: int = 8) -> dict[str, Any]:
        events = sorted(store.read_events(), key=lambda event: event.ts)[-max(0, int(max_refs)) :]
        source_refs = [f"event:{event.id}" for event in events]
        summaries = [_clip(event.summary, 180) for event in events]
        return {
            "schema_version": "hermes.memory_os.expression_context.v0",
            "profile": self.profile,
            "source_refs": source_refs,
            "summaries": summaries,
            "raw_body_included": False,
            "actual_send": False,
            "actual_execute": False,
        }

    def create_draft(
        self,
        *,
        store: MemoryOSStore,
        source_module: str,
        text_preview: str,
        source_refs: list[str],
        feeling_tags: list[str] | None = None,
        risk_flags: list[str] | None = None,
        silence_reason: str | None = None,
    ) -> dict[str, Any]:
        store.initialize()
        created_at = datetime.now(timezone.utc).isoformat()
        clean_preview = _clip(" ".join(str(text_preview or "").split()) or "[SILENT]", 480)
        record = {
            "schema_version": EXPRESSION_DRAFT_SCHEMA_VERSION,
            "draft_id": _draft_id(created_at, clean_preview, source_refs),
            "created_at": created_at,
            "profile": self.profile,
            "source_module": str(source_module or "unknown"),
            "source_refs": [str(ref) for ref in source_refs[:12]],
            "text_preview": clean_preview,
            "feeling_tags": [str(tag) for tag in (feeling_tags or [])[:8]],
            "risk_flags": [str(flag) for flag in (risk_flags or [])[:8]],
            "silence_reason": str(silence_reason or ""),
            "raw_body_included": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        }
        _append_jsonl(self.drafts_path, record)
        return dict(record)

    def read_recent_drafts(self, *, limit: int = 20) -> list[dict[str, Any]]:
        records = _read_jsonl(self.drafts_path)
        if limit and limit > 0:
            return records[-limit:]
        return records


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    from plugins.memory.memory_os.jsonl_io import append_jsonl_locked

    append_jsonl_locked(path, record)


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


def _draft_id(created_at: str, text_preview: str, source_refs: list[str]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {"created_at": created_at, "text_preview": text_preview, "source_refs": source_refs},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    stamp = created_at.replace("-", "").replace(":", "").replace("+00:00", "Z").replace(".", "")
    return f"expr_{stamp}_{digest}"


def _clip(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."
