#!/usr/bin/env python3
"""Cleanup expired working memory items older than RETENTION_DAYS.

Designed for no_agent=True cron. stdout reports removals; every run —
including "nothing to clean" — records a durable last-run reason under
system/lane_last_run/ ("Completion Is Not Output": this lane's old
docstring promised to be *silent* when idle, which made a broken lane and
an idle lane indistinguishable on disk).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERMES_HOME = os.environ.get("HERMES_HOME", "") or str(Path.home() / ".hermes")
_repo_root = Path(__file__).absolute().parents[1]
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

try:
    from plugins.memory.memory_os.lane_last_run import record_lane_last_run
except ModuleNotFoundError:  # pragma: no cover - plugin tree unavailable
    def record_lane_last_run(*_args, **_kwargs) -> bool:  # type: ignore[misc]
        sys.stderr.write("lane_last_run unavailable: plugin tree not importable\n")
        return False

RETENTION_DAYS = 7
_LANE_ID = "working_cleanup"


def main(hermes_home: str | None = None) -> int:
    home = hermes_home or _HERMES_HOME
    working_path = Path(home) / "memory-os" / "working" / "lingering.json"

    if not working_path.exists():
        record_lane_last_run(home, _LANE_ID, status="skipped", reason="working_file_absent")
        return 0

    try:
        doc = json.loads(working_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        record_lane_last_run(
            home, _LANE_ID, status="error", reason="working_file_unreadable", error=str(exc)
        )
        sys.stderr.write(f"working_cleanup: cannot read {working_path}: {exc}\n")
        return 1

    items = doc.get("items", []) if isinstance(doc, dict) else []
    now = datetime.now(timezone.utc)

    before = len(items)
    surviving = []
    removed_count = 0
    removed_chars = 0

    for item in items:
        if not isinstance(item, dict) or item.get("status") != "expired":
            surviving.append(item)
            continue
        ts_str = item.get("updated_at") or item.get("created_at")
        if not ts_str:
            surviving.append(item)
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            surviving.append(item)
            continue
        age_days = (now - ts).total_seconds() / 86400
        if age_days > RETENTION_DAYS:
            removed_count += 1
            removed_chars += len(str(item.get("text", "")))
            continue
        surviving.append(item)

    if removed_count == 0:
        record_lane_last_run(
            home,
            _LANE_ID,
            status="ok",
            reason="no_expired_items",
            counters={"items_scanned": before, "items_removed": 0},
        )
        return 0

    doc["items"] = surviving
    try:
        working_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        record_lane_last_run(
            home, _LANE_ID, status="error", reason="working_file_write_failed", error=str(exc)
        )
        sys.stderr.write(f"working_cleanup: cannot write {working_path}: {exc}\n")
        return 1

    record_lane_last_run(
        home,
        _LANE_ID,
        status="ok",
        reason="removed_expired_items",
        counters={
            "items_scanned": before,
            "items_removed": removed_count,
            "chars_freed": removed_chars,
        },
    )
    print(
        f"🧹 Working Memory Cleanup: removed {removed_count} expired items "
        f"(> {RETENTION_DAYS}d old), freed ~{removed_chars} chars. "
        f"Before: {before} items → After: {len(surviving)} items"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
