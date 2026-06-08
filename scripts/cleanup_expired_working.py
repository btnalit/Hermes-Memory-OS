#!/usr/bin/env python3
"""
Cleanup expired working memory items older than RETENTION_DAYS.
Designed for no_agent=True cron (stdout-only watchdog pattern).
Silent when nothing to clean; reports count + chars when items removed.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

WORKING_PATH = Path("/root/.hermes/memory-os/working/lingering.json")
RETENTION_DAYS = 7

if not WORKING_PATH.exists():
    raise SystemExit(0)

doc = json.loads(WORKING_PATH.read_text(encoding="utf-8"))
items = doc.get("items", [])
now = datetime.now(timezone.utc)

before = len(items)
surviving = []
removed_count = 0
removed_chars = 0

for item in items:
    if item.get("status") != "expired":
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
    raise SystemExit(0)

doc["items"] = surviving
WORKING_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

msg = (
    f"🧹 Working Memory Cleanup: removed {removed_count} expired items "
    f"(> {RETENTION_DAYS}d old), freed ~{removed_chars} chars. "
    f"Before: {before} items → After: {len(surviving)} items"
)
print(msg)
