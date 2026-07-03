#!/usr/bin/env python3
"""Graph edge quality analyzer — assess edge quality from SQLite or shadow JSONL.

Usage:
    python scripts/memory_os_graph_shadow_analyzer.py [--hermes-home PATH] [--json]
    python scripts/memory_os_graph_shadow_analyzer.py --source shadow-jsonl [--hermes-home PATH]

Default source is ``sqlite`` — reads the ``memory_edges`` table from the
Memory-OS index database (full edge population: candidate + active).

Pass ``--source shadow-jsonl`` for backward-compatible shadow audit
(injection-only active edges from graph_layer_shadow.jsonl).

Output: human-readable summary (default) or JSON (--json).
Exit 0 on success, 1 on missing data, 2 on parse errors.
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path


# ── SQLite source (default) ────────────────────────────────────────────────

def _resolve_index_db(hermes_home: str) -> Path:
    """Return the path to the Memory-OS index database."""
    return Path(hermes_home) / "memory-os" / "index" / "memory_os.db"


def analyze_sqlite(hermes_home: str) -> dict:
    """Analyze graph edge quality from the SQLite memory_edges table.

    Covers ALL edges (candidate + active), not just the injection-audit
    subset recorded in graph_layer_shadow.jsonl.
    """
    db_path = _resolve_index_db(hermes_home)

    if not db_path.exists():
        return {
            "status": "no_data",
            "source": "sqlite",
            "db_path": str(db_path),
            "error": "index database not found — run index sync first",
        }

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Verify the table exists
        tables = [
            r[0]
            for r in conn.execute(
                "select name from sqlite_master where type='table' and name='memory_edges'"
            ).fetchall()
        ]
        if not tables:
            conn.close()
            return {
                "status": "no_data",
                "source": "sqlite",
                "db_path": str(db_path),
                "error": "memory_edges table not found — index schema may need rebuild",
            }

        rows = conn.execute(
            "select edge_id, from_record_id, to_record_id, relation_type, "
            "weight, state, proposed_by, created_at "
            "from memory_edges"
        ).fetchall()

        if not rows:
            conn.close()
            return {
                "status": "no_edges",
                "source": "sqlite",
                "db_path": str(db_path),
                "total_edges": 0,
            }

        all_edges = [dict(r) for r in rows]
        total_edges = len(all_edges)
        conn.close()
    except sqlite3.Error as exc:
        conn.close()
        return {
            "status": "error",
            "source": "sqlite",
            "db_path": str(db_path),
            "error": f"SQLite error: {exc}",
        }

    return _compute_quality(all_edges, source="sqlite", source_path=str(db_path))


# ── Shadow JSONL source (backward-compatible) ──────────────────────────────

def analyze_shadow(hermes_home: str) -> dict:
    """Analyze graph edge quality from graph_layer_shadow.jsonl.

    This is the backward-compatible path — only covers edges that were
    recorded in the injection-audit shadow (active edges only).
    """
    shadow_path = Path(hermes_home) / "memory-os" / "system" / "graph_layer_shadow.jsonl"

    if not shadow_path.exists():
        return {
            "status": "no_data",
            "source": "shadow-jsonl",
            "shadow_path": str(shadow_path),
            "error": "shadow file not found — no injection audit data to analyze",
        }

    records = []
    parse_errors = 0
    for line in shadow_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            parse_errors += 1

    if not records:
        return {
            "status": "empty",
            "source": "shadow-jsonl",
            "shadow_path": str(shadow_path),
            "record_count": 0,
            "parse_errors": parse_errors,
        }

    # Collect all edges from shadow records
    all_edges = []
    for rec in records:
        for edge in rec.get("edges", []):
            if isinstance(edge, dict):
                all_edges.append(edge)

    if not all_edges:
        return {
            "status": "no_edges",
            "source": "shadow-jsonl",
            "shadow_path": str(shadow_path),
            "record_count": len(records),
            "total_edges": 0,
        }

    result = _compute_quality(all_edges, source="shadow-jsonl", source_path=str(shadow_path))
    result["record_count"] = len(records)
    result["parse_errors"] = parse_errors
    return result


# ── Quality computation (shared) ────────────────────────────────────────────

def _compute_quality(all_edges: list[dict], *, source: str, source_path: str) -> dict:
    """Compute quality metrics from a flat list of edge dicts."""
    total_edges = len(all_edges)

    # State distribution (candidate vs active — available in SQLite)
    state_counts = Counter(str(e.get("state", "candidate")) for e in all_edges)

    # Noise rate: weight < 0.3
    low_weight = [e for e in all_edges if float(e.get("weight", 1.0)) < 0.3]
    noise_rate = len(low_weight) / total_edges if total_edges > 0 else 0

    # Relation type distribution
    relation_counts = Counter(str(e.get("relation_type", "unknown")) for e in all_edges)

    # Proposed-by distribution
    proposed_by_counts = Counter(str(e.get("proposed_by", "unknown")) for e in all_edges)

    # Duplicate edges: same (from_id, to_id)
    pair_counts = Counter(
        (str(e.get("from_record_id", "")), str(e.get("to_record_id", "")))
        for e in all_edges
    )
    duplicates = {pair: count for pair, count in pair_counts.items() if count > 1}

    # Contradicts edges (highest risk)
    contradicts = [e for e in all_edges if e.get("relation_type") == "contradicts"]

    # Cross-proposer duplicates: same pair proposed by different sources
    proposer_by_pair: dict[tuple[str, str], set[str]] = {}
    for e in all_edges:
        pair = (str(e.get("from_record_id", "")), str(e.get("to_record_id", "")))
        proposer_by_pair.setdefault(pair, set()).add(str(e.get("proposed_by", "unknown")))
    cross_proposer_dupes = sum(1 for proposers in proposer_by_pair.values() if len(proposers) > 1)

    # Quality assessment
    contradicts_misrate = len(contradicts) / total_edges if total_edges > 0 else 0
    dup_rate = len(duplicates) / max(total_edges, 1)

    quality_ok = (
        noise_rate <= 0.5
        and contradicts_misrate <= 0.3
        and dup_rate <= 0.3
    )

    return {
        "status": "ok",
        "source": source,
        "source_path": source_path,
        "total_edges": total_edges,
        "state_distribution": dict(state_counts),
        "candidate_count": state_counts.get("candidate", 0),
        "active_count": state_counts.get("active", 0),
        "noise_rate": round(noise_rate, 4),
        "low_weight_edges": len(low_weight),
        "relation_distribution": dict(relation_counts),
        "contradicts_count": len(contradicts),
        "contradicts_misrate": round(contradicts_misrate, 4),
        "duplicate_pairs": len(duplicates),
        "duplicate_rate": round(dup_rate, 4),
        "cross_proposer_duplicate_pairs": cross_proposer_dupes,
        "proposed_by_distribution": dict(proposed_by_counts),
        "quality_gate_pass": quality_ok,
        # Edge weight stats
        "weight_bucket": {
            "w_lt_03": len(low_weight),
            "w_03_05": sum(1 for e in all_edges if 0.3 <= float(e.get("weight", 0)) < 0.5),
            "w_05_07": sum(1 for e in all_edges if 0.5 <= float(e.get("weight", 0)) < 0.7),
            "w_07_09": sum(1 for e in all_edges if 0.7 <= float(e.get("weight", 0)) < 0.9),
            "w_09_10": sum(1 for e in all_edges if 0.9 <= float(e.get("weight", 0)) <= 1.0),
        },
    }


# ── Report ─────────────────────────────────────────────────────────────────

def print_report(result: dict) -> None:
    """Print human-readable quality report."""
    print("=" * 60)
    src = result.get("source", "unknown")
    print(f"Graph Edge Quality Report (source: {src})")
    print("=" * 60)

    if result["status"] in ("no_data", "empty", "no_edges", "error"):
        print(f"Status: {result['status']}")
        print(f"Source path: {result.get('source_path', result.get('shadow_path', 'N/A'))}")
        print(f"Error: {result.get('error', 'N/A')}")
        return

    print(f"Total edges: {result['total_edges']}")
    print(f"Source: {result.get('source_path', 'N/A')}")
    print()

    # State distribution (sqlite only)
    if "state_distribution" in result:
        print("--- State Distribution ---")
        for state in sorted(result["state_distribution"]):
            cnt = result["state_distribution"][state]
            pct = cnt / result["total_edges"] * 100
            print(f"  {state}: {cnt} ({pct:.0f}%)")
        print()

    print("--- Edge Quality ---")
    print(
        f"Noise rate (weight < 0.3): {result['noise_rate']:.1%} ({result['low_weight_edges']} edges)"
    )
    print(
        f"Contradicts: {result['contradicts_count']} ({result['contradicts_misrate']:.1%} of total)"
    )
    print(
        f"Duplicate rate: {result['duplicate_rate']:.1%} ({result['duplicate_pairs']} duplicate pairs)"
    )
    if result.get("cross_proposer_duplicate_pairs"):
        print(
            f"Cross-proposer duplicates: {result['cross_proposer_duplicate_pairs']} pairs"
        )
    print()

    # Weight bucket distribution
    wb = result.get("weight_bucket", {})
    if wb:
        print("--- Weight Distribution ---")
        print(f"  < 0.3:  {wb.get('w_lt_03', 0)}")
        print(f"  0.3-0.5: {wb.get('w_03_05', 0)}")
        print(f"  0.5-0.7: {wb.get('w_05_07', 0)}")
        print(f"  0.7-0.9: {wb.get('w_07_09', 0)}")
        print(f"  0.9-1.0: {wb.get('w_09_10', 0)}")
        print()

    print("--- Relation Distribution ---")
    for rel, count in sorted(result["relation_distribution"].items()):
        pct = count / result["total_edges"] * 100
        print(f"  {rel}: {count} ({pct:.0f}%)")
    print()

    print("--- Proposed By ---")
    for src_name, count in sorted(result["proposed_by_distribution"].items()):
        print(f"  {src_name}: {count}")
    print()

    print("--- Quality Gate ---")
    status = "PASS" if result["quality_gate_pass"] else "FAIL"
    print(f"Injection quality gate: {status}")
    if not result["quality_gate_pass"]:
        print("Fix proposer edge quality before enabling injection.")
    print()


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyze graph edge quality")
    parser.add_argument(
        "--hermes-home",
        default=None,
        help="Hermes home directory (default: HERMES_HOME env or ~/.hermes)",
    )
    parser.add_argument(
        "--source",
        choices=("sqlite", "shadow-jsonl"),
        default="sqlite",
        help="Data source: sqlite (default, all edges) or shadow-jsonl (injection audit only)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of report")
    args = parser.parse_args()

    # Resolve hermes_home
    if args.hermes_home:
        hermes_home = args.hermes_home
    else:
        hermes_home = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))

    if args.source == "shadow-jsonl":
        result = analyze_shadow(hermes_home)
    else:
        result = analyze_sqlite(hermes_home)

    if args.json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print_report(result)

    # Exit code
    if result["status"] == "no_data":
        sys.exit(1)
    elif result.get("parse_errors", 0) > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
