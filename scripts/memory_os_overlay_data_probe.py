"""Quick data probe for State Overlay design — read-only, no writes."""
import json, sqlite3
from pathlib import Path

def probe(home_str="/root/.hermes"):
    home = Path(home_str)
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
    candidates_file = mos / "candidates" / "candidates.jsonl"
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
    event_stats_file = mos / "system" / "event_stats.json"
    results["event_stats"] = {}
    if event_stats_file.exists():
        es = json.loads(event_stats_file.read_text(encoding="utf-8"))
        results["event_stats"] = {
            "total_events": es.get("total_event_count"),
            "recent_summaries": [
                {"kind": s.get("kind"), "summary": str(s.get("summary", ""))[:200]}
                for s in es.get("recent_event_summaries", [])[:5]
            ]
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
    lsa_file = mos / "system" / "last_session_anchor.jsonl"
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


if __name__ == "__main__":
    import sys
    home = sys.argv[1] if len(sys.argv) > 1 else "/root/.hermes"
    data = probe(home)
    print(json.dumps(data, ensure_ascii=False, indent=2))
