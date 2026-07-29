"""
Community Table — a shared space where anyone can leave a note.

Like a table in the middle of the courtyard: anyone can put something down,
anyone passing by can see it. No recipient, no pressure.

Schema: memory-os.community.table.v1
File: community/shared/table.jsonl (append-only)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TABLE_SCHEMA_VERSION = "memory-os.community.table.v1"

# Per-actor rate limit
MAX_ENTRIES_PER_HOUR = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return result


def _is_rate_limited(path: Path, actor: str, max_per_hour: int = MAX_ENTRIES_PER_HOUR) -> bool:
    """Check if actor has written too many entries in the last hour."""
    if not path.exists():
        return False
    now = datetime.now(timezone.utc)
    one_hour_ago = now.timestamp() - 3600
    count = 0
    # Read file backwards to check recent entries
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("actor") != actor:
            continue
        row_ts = _parse_ts(str(row.get("ts", "")))
        if row_ts is None:
            continue
        if row_ts.timestamp() < one_hour_ago:
            break  # Older entries — since file is chronological, stop
        count += 1
        if count >= max_per_hour:
            return True
    return False


def write_to_table(
    community_root: str | Path,
    *,
    actor: str,
    actor_name: str = "",
    text: str,
    share_url: str | None = None,
    share_type: str = "note",
    max_per_hour: int = MAX_ENTRIES_PER_HOUR,
) -> dict[str, Any]:
    """Leave a note on the community table.

    Args:
        community_root: Path to community directory
        actor: Who is writing (e.g. 'sannai', 'partner-df1c2405', 'hermes')
        actor_name: Display name (e.g. '三奶', '流萤', 'Hermes')
        text: The message (max 500 chars)
        share_url: Optional URL for "look together" shares
        share_type: "note" (casual thought) or "share" (look at this!)
        max_per_hour: Rate limit — max entries per actor per hour

    Returns:
        The entry dict that was written.
    """
    actor = str(actor or "").strip()
    text = str(text or "").strip()

    if not actor:
        raise ValueError("actor is required")
    if not text:
        raise ValueError("text is required")
    if len(text) > 500:
        text = text[:500]

    if share_type not in ("note", "share"):
        raise ValueError('share_type must be "note" or "share"')

    root = Path(community_root)
    table_path = root / "shared" / "table.jsonl"
    table_path.parent.mkdir(parents=True, exist_ok=True)

    if _is_rate_limited(table_path, actor, max_per_hour):
        raise RuntimeError(f"rate limited: {actor} has exceeded {max_per_hour} entries/hour")

    entry: dict[str, Any] = {
        "schema_version": TABLE_SCHEMA_VERSION,
        "ts": _now_iso(),
        "actor": actor,
        "actor_name": str(actor_name or actor),
        "text": text,
        "share_type": share_type,
    }
    if share_url:
        entry["share_url"] = str(share_url)[:1000]

    with open(table_path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def read_table(
    community_root: str | Path,
    *,
    limit: int = 20,
    since_ts: str | None = None,
    only_shares: bool = False,
) -> list[dict[str, Any]]:
    """Read notes from the community table, newest first.

    Args:
        community_root: Path to community directory
        limit: Max entries to return
        since_ts: Only return entries newer than this ISO timestamp
        only_shares: Only return "share" type entries (look-together moments)

    Returns:
        List of table entries, newest first.
    """
    root = Path(community_root)
    table_path = root / "shared" / "table.jsonl"
    if not table_path.exists():
        return []

    entries = _read_jsonl(table_path)

    # Filter
    if since_ts:
        cursor = _parse_ts(since_ts)
        if cursor:
            entries = [e for e in entries if _parse_ts(str(e.get("ts", ""))) and
                       _parse_ts(str(e.get("ts", ""))) > cursor]  # type: ignore[operator]
    if only_shares:
        entries = [e for e in entries if e.get("share_type") == "share"]

    # Sort newest first, limit
    entries.sort(key=lambda e: str(e.get("ts", "")), reverse=True)
    return entries[:limit]


def get_unread_shares(
    community_root: str | Path,
    last_seen_ts: str,
) -> list[dict[str, Any]]:
    """Get new "look together" shares since last_seen_ts."""
    return read_table(community_root, since_ts=last_seen_ts, only_shares=True)
