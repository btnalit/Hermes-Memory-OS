#!/usr/bin/env python3
"""Graph shadow analyzer — assess edge quality from graph_layer_shadow.jsonl.

Usage:
    python scripts/memory_os_graph_shadow_analyzer.py [--hermes-home PATH] [--json]

Reads system/graph_layer_shadow.jsonl and reports:
  - Total shadow records and total edges
  - Noise rate: edges with weight < 0.3
  - Relation type distribution (refines, contradicts, depends_on, co_occurs, etc.)
  - Duplicate edges: same (from_id, to_id) appearing multiple times
  - Contradicts edges: count and list (highest-risk type)
  - Per-record detail: anchor_count, edge_count

Output: human-readable summary (default) or JSON (--json).
Exit 0 on success, 1 on missing file, 2 on parse errors.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path


def analyze_shadow(hermes_home: str) -> dict:
    """Analyze graph shadow data and return structured results."""
    shadow_path = Path(hermes_home) / "memory-os" / "system" / "graph_layer_shadow.jsonl"

    if not shadow_path.exists():
        return {
            "status": "no_data",
            "shadow_path": str(shadow_path),
            "error": "shadow file not found — no graph data to analyze",
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
            "shadow_path": str(shadow_path),
            "record_count": 0,
            "parse_errors": parse_errors,
        }

    # Collect all edges
    all_edges = []
    for rec in records:
        for edge in rec.get("edges", []):
            if isinstance(edge, dict):
                all_edges.append(edge)

    total_edges = len(all_edges)
    if total_edges == 0:
        return {
            "status": "no_edges",
            "shadow_path": str(shadow_path),
            "record_count": len(records),
            "total_edges": 0,
        }

    # Noise rate: weight < 0.3
    low_weight = [e for e in all_edges if float(e.get("weight", 1.0)) < 0.3]
    noise_rate = len(low_weight) / total_edges if total_edges > 0 else 0

    # Relation type distribution
    relation_counts = Counter(str(e.get("relation_type", "unknown")) for e in all_edges)

    # Duplicate edges: same (from_id, to_id)
    pair_counts = Counter(
        (str(e.get("from_record_id", "")), str(e.get("to_record_id", "")))
        for e in all_edges
    )
    duplicates = {pair: count for pair, count in pair_counts.items() if count > 1}

    # Contradicts edges (highest risk)
    contradicts = [e for e in all_edges if e.get("relation_type") == "contradicts"]

    # Proposed by distribution
    proposed_by_counts = Counter(str(e.get("proposed_by", "unknown")) for e in all_edges)

    # Quality assessment
    contradicts_misrate = len(contradicts) / total_edges if total_edges > 0 else 0

    quality_ok = (
        noise_rate <= 0.5
        and contradicts_misrate <= 0.3
        and len(duplicates) / max(total_edges, 1) <= 0.3
    )

    return {
        "status": "ok",
        "shadow_path": str(shadow_path),
        "record_count": len(records),
        "total_edges": total_edges,
        "parse_errors": parse_errors,
        "noise_rate": round(noise_rate, 4),
        "low_weight_edges": len(low_weight),
        "relation_distribution": dict(relation_counts),
        "contradicts_count": len(contradicts),
        "contradicts_misrate": round(contradicts_misrate, 4),
        "duplicate_pairs": len(duplicates),
        "duplicate_rate": round(len(duplicates) / max(total_edges, 1), 4),
        "proposed_by_distribution": dict(proposed_by_counts),
        "quality_gate_pass": quality_ok,
        "unfinished_todos": ["budget_awareness"],  # see checklist C.2
    }


def print_report(result: dict) -> None:
    """Print human-readable quality report."""
    print("=" * 60)
    print("Graph Shadow Quality Report")
    print("=" * 60)

    if result["status"] in ("no_data", "empty", "no_edges"):
        print(f"Status: {result['status']}")
        print(f"Shadow path: {result.get('shadow_path', 'N/A')}")
        if result["status"] == "no_data":
            print("No graph data to analyze — shadow file does not exist.")
            print("Run with graph injection enabled or wait for cron edge proposals.")
        return

    print(f"Shadow records: {result['record_count']}")
    print(f"Total edges: {result['total_edges']}")
    print(f"Parse errors: {result['parse_errors']}")
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
    print()

    print("--- Relation Distribution ---")
    for rel, count in sorted(result["relation_distribution"].items()):
        pct = count / result["total_edges"] * 100
        print(f"  {rel}: {count} ({pct:.0f}%)")
    print()

    print("--- Proposed By ---")
    for src, count in sorted(result["proposed_by_distribution"].items()):
        print(f"  {src}: {count}")
    print()

    print("--- Quality Gate ---")
    status = "PASS" if result["quality_gate_pass"] else "FAIL"
    print(f"Injection quality gate: {status}")
    if not result["quality_gate_pass"]:
        print("Fix proposer edge quality before enabling injection.")
    print()


def main():
    parser = argparse.ArgumentParser(description="Analyze graph shadow edge quality")
    parser.add_argument(
        "--hermes-home",
        default=None,
        help="Hermes home directory (default: HERMES_HOME env or ~/.hermes)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of report")
    args = parser.parse_args()

    # Resolve hermes_home
    if args.hermes_home:
        hermes_home = args.hermes_home
    else:
        hermes_home = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))

    result = analyze_shadow(hermes_home)

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
