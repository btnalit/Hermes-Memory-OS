"""Quick data probe for State Overlay design — read-only, no writes."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

# Location-agnostic import resolution: repo checkout > runtime layout.
# The probe reads files the runtime owns, so it must address them through the
# runtime's accessors rather than rebuilding path literals — rebuilding them
# is how this script came to report an empty event_stats block forever while
# the cache sat, healthy, one directory over.
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]  # scripts/ → repo root
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path.home() / ".hermes" / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.event_stats import event_stats_path  # noqa: E402
from plugins.memory.memory_os.roots import last_session_anchor_path  # noqa: E402


def probe(home_str="/root/.hermes"):
    home = Path(home_str).expanduser().resolve()
    mos = home / "memory-os"
    results = {}

    # 1. Crystallized records
    crystallized = mos / "crystallized"
    results["crystallized_files"] = []
    if crystallized.exists():
        for f in sorted(crystallized.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            results["crystallized_files"].append({
                "file": f.name,
                "size_chars": len(text),
                "preview": text[:400]
            })

    # 2. Candidates (last 5 for kind/summary sampling)
    candidates_file = mos / "crystallized" / "candidates.jsonl"  # canonical: MemoryOSRoots.crystallized_root
    results["candidates"] = {"total": 0, "samples": []}
    if candidates_file.exists():
        lines = [l for l in candidates_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        results["candidates"]["total"] = len(lines)
        for line in lines[-5:]:
            try:
                c = json.loads(line)
                results["candidates"]["samples"].append({
                    "candidate_id": c.get("candidate_id"),
                    "kind": c.get("kind"),
                    "bridge_state": c.get("bridge_state"),
                    "body_preview": str(c.get("body", ""))[:200]
                })
            except Exception:
                pass

    # 3. Working items
    working = mos / "working"
    results["working"] = {"files": 0, "total_items": 0, "samples": []}
    if working.exists():
        wfs = sorted(working.glob("*.json"))
        results["working"]["files"] = len(wfs)
        for wf in wfs[:3]:
            try:
                d = json.loads(wf.read_text(encoding="utf-8"))
                items = d.get("items", [])
                results["working"]["total_items"] += len(items)
                for item in items[:3]:
                    results["working"]["samples"].append({
                        "summary": str(item.get("summary", ""))[:200],
                        "kind": item.get("kind"),
                    })
            except Exception:
                pass

    # 4. Event stats (cached)
    event_stats_file = event_stats_path(SimpleNamespace(memory_os_root=mos))
    results["event_stats"] = {"present": False, "path": str(event_stats_file)}
    if event_stats_file.exists():
        es = json.loads(event_stats_file.read_text(encoding="utf-8"))
        results["event_stats"] = {
            "present": True,
            "path": str(event_stats_file),
            "total_events": es.get("total_event_count"),
            # Raw tail — on production this is machine bookkeeping, kept here
            # because the probe's job is to show what is actually on disk.
            "recent_summaries": [
                {"kind": s.get("kind"), "summary": str(s.get("summary", ""))[:200]}
                for s in es.get("recent_event_summaries", [])[:5]
            ],
            # Kind-filtered tail — what recall consumers actually inject.
            "recall_summaries": [
                {"kind": s.get("kind"), "summary": str(s.get("summary", ""))[:200]}
                for s in es.get("recall_event_summaries", [])[:5]
            ],
            "recall_summary_scanned_count": es.get("recall_summary_scanned_count"),
            "recall_summary_excluded_kind_counts": es.get(
                "recall_summary_excluded_kind_counts"
            ),
        }

    # 5. Task anchors (recent activity)
    anchor_file = mos / "system" / "active_task_anchor.jsonl"
    results["task_anchors"] = {"total_lines": 0, "latest": []}
    if anchor_file.exists():
        lines = [l for l in anchor_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        results["task_anchors"]["total_lines"] = len(lines)
        # Last 3 status records
        for line in lines[-3:]:
            try:
                a = json.loads(line)
                results["task_anchors"]["latest"].append({
                    "status": a.get("status"),
                    "anchor_preview": str(a.get("anchor", ""))[:200],
                    "session_id": str(a.get("session_id", ""))[:20]
                })
            except Exception:
                pass

    # 6. Memory edges summary
    db_path = mos / "index" / "memory_os.db"
    results["edges"] = {}
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute("SELECT COUNT(*) FROM memory_edges")
        results["edges"]["total"] = cur.fetchone()[0]
        cur = conn.execute(
            "SELECT relation_type, state, COUNT(*) FROM memory_edges GROUP BY relation_type, state"
        )
        results["edges"]["by_type_state"] = [
            {"relation": r[0], "state": r[1], "count": r[2]} for r in cur
        ]
        conn.close()

    # 7. Last session anchors
    lsa_file = last_session_anchor_path(SimpleNamespace(memory_os_root=mos))
    results["last_sessions"] = {"total_lines": 0, "latest": []}
    if lsa_file.exists():
        lines = [l for l in lsa_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        results["last_sessions"]["total_lines"] = len(lines)
        for line in lines[-2:]:
            try:
                a = json.loads(line)
                results["last_sessions"]["latest"].append({
                    "session_id": str(a.get("session_id", ""))[:20],
                    "foreground_summary": str(a.get("foreground_summary", ""))[:300],
                    "ended_at": a.get("ended_at", "")
                })
            except Exception:
                pass

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Memory-OS data probe for state overlay design.",
    )
    parser.add_argument(
        "--hermes-home",
        default="/root/.hermes",
        help="Path to HERMES_HOME (default: /root/.hermes)",
    )
    parser.add_argument("--output", choices=("json",), default="json")
    args = parser.parse_args(argv)

    data = probe(args.hermes_home)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
