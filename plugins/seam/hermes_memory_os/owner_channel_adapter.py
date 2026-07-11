"""Hermes-owned owner-review channel resolution for Memory-OS payloads.

Memory-OS owns review state and payload construction.  This adapter owns the
Hermes config/state-db inspection needed to select an owner interaction channel.
It reads session metadata only and never reads message bodies.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.config import load_config


OWNER_REVIEW_CHANNEL_SCHEMA_VERSION = "memory-os.owner_review_channel.v0"


def resolve_owner_review_channel(
    *,
    hermes_home: Path,
    profile: str = "default",
    owner_id: str = "",
) -> dict[str, Any]:
    home = Path(hermes_home)
    config = load_config(home).get("owner_review", {})
    if not isinstance(config, dict):
        config = {}
    resolved_owner = str(owner_id or config.get("owner_id") or "owner")
    mode = str(config.get("mode") or "dry_run")
    if mode == "disabled":
        return _channel_report(
            status="disabled",
            reason="owner_review_mode_disabled",
            profile=profile,
            owner_id=resolved_owner,
            channel="unknown",
            target_ref="",
            direct_message=False,
            configured_by_owner=False,
            fallback_used=False,
            candidates=[],
        )

    configured = _configured_channel_candidate(config, owner_id=resolved_owner)
    candidates = _state_db_channel_candidates(home, owner_id=resolved_owner, limit=5)
    if configured:
        safe = _channel_candidate_is_safe(configured, allow_group=bool(config.get("allow_group")))
        return _channel_report(
            status="selected" if bool(config.get("enabled")) and safe else "dry_run_only",
            reason="explicit_owner_config" if safe else "explicit_config_not_owner_verified",
            profile=profile,
            owner_id=resolved_owner,
            channel=configured["channel"],
            target_ref=configured["target_ref"],
            direct_message=configured["direct_message"],
            configured_by_owner=True,
            fallback_used=False,
            candidates=candidates,
        )

    direct_candidates = [item for item in candidates if item.get("direct_message")]
    if len(direct_candidates) == 1:
        candidate = direct_candidates[0]
        return _channel_report(
            status="dry_run_only",
            reason="single_owner_direct_metadata_candidate",
            profile=profile,
            owner_id=resolved_owner,
            channel=str(candidate.get("channel") or "unknown"),
            target_ref=str(candidate.get("target_ref") or ""),
            direct_message=True,
            configured_by_owner=False,
            fallback_used=True,
            candidates=candidates,
        )
    if len(direct_candidates) > 1:
        return _channel_report(
            status="dry_run_only",
            reason="multiple_owner_direct_metadata_candidates",
            profile=profile,
            owner_id=resolved_owner,
            channel="cli",
            target_ref="",
            direct_message=False,
            configured_by_owner=False,
            fallback_used=True,
            candidates=candidates,
        )
    return _channel_report(
        status="dry_run_only",
        reason="cli_preview_fallback",
        profile=profile,
        owner_id=resolved_owner,
        channel="cli",
        target_ref="",
        direct_message=False,
        configured_by_owner=False,
        fallback_used=True,
        candidates=candidates,
    )


def channel_shadow_diff(host_report: dict[str, Any], legacy_report: dict[str, Any]) -> dict[str, Any]:
    """Return bounded field differences for the S0.4 shadow phase."""

    fields = (
        "status",
        "reason",
        "profile",
        "owner_id",
        "channel",
        "target_ref",
        "direct_message",
        "configured_by_owner",
        "fallback_used",
        "candidate_count",
        "raw_body_included",
    )
    differences = [
        {"field": field, "host": host_report.get(field), "legacy": legacy_report.get(field)}
        for field in fields
        if host_report.get(field) != legacy_report.get(field)
    ]
    return {
        "schema_version": "memory-os.owner_review_channel_shadow.v0",
        "status": "match" if not differences else "mismatch",
        "difference_count": len(differences),
        "differences": differences,
        "raw_body_included": False,
    }


def _channel_report(
    *,
    status: str,
    reason: str,
    profile: str,
    owner_id: str,
    channel: str,
    target_ref: str,
    direct_message: bool,
    configured_by_owner: bool,
    fallback_used: bool,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": OWNER_REVIEW_CHANNEL_SCHEMA_VERSION,
        "host_observation_owner": "hermes_memory_os_seam",
        "status": status,
        "reason": reason,
        "profile": profile or "default",
        "owner_id": owner_id,
        "channel": _safe_channel(channel),
        "target_ref": _safe_target_ref(target_ref),
        "direct_message": bool(direct_message),
        "last_owner_activity_at": candidates[0].get("last_owner_activity_at") if candidates else "",
        "configured_by_owner": bool(configured_by_owner),
        "fallback_used": bool(fallback_used),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "raw_body_included": False,
    }


def _configured_channel_candidate(config: dict[str, Any], *, owner_id: str) -> dict[str, Any] | None:
    channel = _safe_channel(str(config.get("channel") or ""))
    target_ref = _safe_target_ref(str(config.get("target_ref") or ""))
    if not channel or channel == "unknown" or not target_ref:
        return None
    return {
        "channel": channel,
        "target_ref": target_ref,
        "direct_message": bool(config.get("direct_message")),
        "last_owner_activity_at": "",
        "configured_by_owner": True,
        "owner_id": owner_id,
        "source": "config",
    }


def _channel_candidate_is_safe(candidate: dict[str, Any], *, allow_group: bool) -> bool:
    if not candidate.get("target_ref"):
        return False
    if candidate.get("direct_message") is True:
        return True
    return bool(allow_group)


def _state_db_channel_candidates(home: Path, *, owner_id: str, limit: int) -> list[dict[str, Any]]:
    path = home / "state.db"
    if not path.exists():
        return []
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "sessions"):
                return []
            columns = _table_columns(conn, "sessions")
            id_col = _first_existing(columns, ("id", "session_id", "uuid"))
            if not id_col:
                return []
            platform_col = _first_existing(columns, ("source", "platform", "channel", "kind"))
            updated_col = _first_existing(columns, ("updated_at", "last_updated", "created_at"))
            target_col = _first_existing(
                columns,
                ("target_ref", "target", "chat_id", "conversation_id", "channel_id", "thread_id", "room_id"),
            )
            owner_col = _first_existing(columns, ("owner_id", "user_id", "account_id", "principal_id"))
            direct_col = _first_existing(columns, ("direct_message", "is_direct", "is_dm", "dm", "is_group", "group"))
            rows = conn.execute(f"select * from sessions order by {updated_col or id_col} desc limit 20").fetchall()
    except (OSError, sqlite3.Error):
        return []
    candidates: list[dict[str, Any]] = []
    for row in rows:
        platform = str(row[platform_col]) if platform_col else "unknown"
        target_ref = _target_ref(platform, str(row[target_col]) if target_col else str(row[id_col]))
        direct_message = _direct_flag(row[direct_col], direct_col) if direct_col else False
        row_owner = str(row[owner_col]) if owner_col else ""
        if row_owner and row_owner != owner_id:
            continue
        candidates.append(
            {
                "source": "state_db.sessions",
                "channel": _safe_channel(platform),
                "target_ref": _safe_target_ref(target_ref),
                "direct_message": direct_message,
                "last_owner_activity_at": str(row[updated_col]) if updated_col else "",
                "configured_by_owner": False,
                "owner_id": owner_id,
                "raw_body_included": False,
            }
        )
    return sorted(candidates, key=lambda item: str(item.get("last_owner_activity_at") or ""), reverse=True)[:limit]


def _safe_channel(value: str) -> str:
    channel = str(value or "").strip().lower().replace("-", "_")
    allowed = {
        "telegram",
        "cli",
        "web",
        "slack",
        "whatsapp",
        "wecom",
        "wechat",
        "weixin",
        "matrix",
        "discord",
        "signal",
        "origin",
        "unknown",
    }
    return channel if channel in allowed else "unknown"


def _safe_target_ref(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= 180 else text[:179].rstrip() + "…"


def _target_ref(platform: str, target: str) -> str:
    target = str(target or "").strip()
    if not target:
        return ""
    if ":" in target:
        return target
    safe_platform = _safe_channel(platform)
    return f"session:{target}" if safe_platform == "unknown" else f"{safe_platform}:{target}"


def _direct_flag(value: Any, column_name: str) -> bool:
    truthy = str(value).strip().lower() in {"1", "true", "yes", "y", "dm", "direct"}
    return not truthy if column_name in {"is_group", "group"} else truthy


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("select name from sqlite_master where type='table' and name=?", (table_name,)).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"pragma table_info({table_name})").fetchall()}


def _first_existing(columns: set[str], names: tuple[str, ...]) -> str:
    return next((name for name in names if name in columns), "")
