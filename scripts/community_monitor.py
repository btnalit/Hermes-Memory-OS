#!/usr/bin/env python3
"""
Track A Community Monitor — lightweight status reporter for the Sannai Community.

Reports:
  - replies_24h (replies in last 24h per partner)
  - total_partner_replies (all-time)
  - budget & error_record counts
  - cron health (last cron run)
  - snapshot summary

Run: python3 community_monitor.py [--community-root PATH]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TRACK_A_SCHEMA_VERSION = "memory-os.community.monitor_track_a.v1"


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_track_a_report(community_root: Path) -> dict:
    root = Path(community_root)
    now = datetime.now(timezone.utc)

    # Read roster
    roster_path = root / "roster.jsonl"
    if not roster_path.exists():
        return {"schema_version": TRACK_A_SCHEMA_VERSION, "status": "no_roster"}

    # Parse active partners
    current: dict[str, dict] = {}
    for line in roster_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        pid = str(row.get("id", ""))
        if not pid:
            continue
        if row.get("event") == "status_transition":
            if pid in current:
                current[pid]["status"] = row.get("status", current[pid].get("status"))
        else:
            current[pid] = row

    active = {pid: r for pid, r in current.items() if r.get("status") == "active"}

    partners_report = []
    total_replies_24h = 0
    total_replies_all = 0
    total_errors = 0
    total_skips = 0
    total_notes = 0

    for pid, entry in active.items():
        partner_dir = root / "partners" / pid
        replies_path = partner_dir / "replies.jsonl"
        notes_path = partner_dir / "notes.jsonl"
        state_path = partner_dir / "memory" / "state.json"
        error_path = partner_dir / "error_record.jsonl"

        # Count replies
        reply_lines: list[str] = []
        if replies_path.exists():
            reply_lines = [l for l in replies_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        total_replies = len(reply_lines)
        total_replies_all += total_replies

        # Count replies in last 24h
        replies_24h = 0
        for line in reply_lines:
            try:
                r = json.loads(line)
                ts = _parse_ts(str(r.get("ts", "")))
                if ts and (now - ts).total_seconds() < 86400:
                    replies_24h += 1
            except (json.JSONDecodeError, TypeError):
                pass
        total_replies_24h += replies_24h

        # Count notes
        note_count = 0
        if notes_path.exists():
            note_count = len([l for l in notes_path.read_text(encoding="utf-8").splitlines() if l.strip()])
        total_notes += note_count

        # Count error records
        error_count = 0
        if error_path.exists():
            error_count = len([l for l in error_path.read_text(encoding="utf-8").splitlines() if l.strip()])
        total_errors += error_count

        # Read state
        mood = "unknown"
        cursor = 0
        if state_path.exists():
            try:
                st = json.loads(state_path.read_text(encoding="utf-8"))
                mood = st.get("mood", "unknown")
                cursor = int(st.get("cursor", 0))
            except (json.JSONDecodeError, OSError, ValueError):
                pass

        # Count budget skips (from state)
        skip_count = 0
        state_obj = {}
        if state_path.exists():
            try:
                state_obj = json.loads(state_path.read_text(encoding="utf-8"))
                skip_count = int(state_obj.get("skip_count", state_obj.get("budget_skips", 0)))
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        total_skips += skip_count

        partners_report.append({
            "partner_id": pid,
            "name": entry.get("name", pid),
            "total_replies": total_replies,
            "replies_24h": replies_24h,
            "notes": note_count,
            "errors": error_count,
            "skip_count": skip_count,
            "mood": mood,
            "cursor": cursor,
        })

    # Cron health check: look at the last cron job output
    cron_healthy = True
    cron_last_run = ""
    cron_errors = 0
    # Check if there's a cron output directory
    cron_dir = root.parent.parent / "cron" / "output"
    if cron_dir.exists():
        # Find most recent community_partner_reply output
        latest = None
        for f in cron_dir.glob("*.json"):
            if "community_partner_reply" in f.name or "partner_reply" in f.name:
                mtime = f.stat().st_mtime
                if latest is None or mtime > latest[0]:
                    latest = (mtime, f)
        if latest:
            cron_last_run = datetime.fromtimestamp(latest[0], tz=timezone.utc).isoformat()
            try:
                cron_output = json.loads(latest[1].read_text(encoding="utf-8"))
                if cron_output.get("errors"):
                    cron_healthy = False
                    cron_errors = len(cron_output.get("errors"))
            except (json.JSONDecodeError, OSError):
                pass

    return {
        "schema_version": TRACK_A_SCHEMA_VERSION,
        "status": "ok",
        "generated_at": now.isoformat(),
        "summary": {
            "active_partners": len(active),
            "total_replies_all_time": total_replies_all,
            "total_replies_24h": total_replies_24h,
            "total_errors": total_errors,
            "total_budget_skips": total_skips,
            "total_notes": total_notes,
            "cron_healthy": cron_healthy,
            "cron_last_run": cron_last_run,
            "cron_errors": cron_errors,
        },
        "partners": partners_report,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Track A Community Monitor")
    parser.add_argument(
        "--community-root",
        default="/vol1/.hermes/profiles/sannai/memory-os/community",
        help="Path to community root directory",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    report = build_track_a_report(args.community_root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        s = report.get("summary", {})
        print("=== Track A 社区监控 ===")
        print(f"活跃伙伴: {s.get('active_partners', 0)}")
        print(f"24h 内回复: {s.get('total_replies_24h', 0)}")
        print(f"总回复数: {s.get('total_replies_all_time', 0)}")
        print(f"错误记录: {s.get('total_errors', 0)}")
        print(f"Budget 跳过: {s.get('total_budget_skips', 0)}")
        print(f"Cron 健康: {'✅' if s.get('cron_healthy', False) else '❌'}")
        if s.get("cron_last_run"):
            print(f"Cron 上次运行: {s.get('cron_last_run')}")
        for p in report.get("partners", []):
            print(f"\n  {p['name']}: {p['replies_24h']}条/24h | {p['total_replies']}条总计 | mood={p['mood']} | errors={p['errors']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
