#!/usr/bin/env python3
"""One-time compaction of duplicate graph edges (W2/E2).

Production accumulated 769 redundant edge rows (332 duplicate
(from, to, relation) triples, worst case x8) while proposer-side dedup was
capped at limit=1000.  W1 moved the dedup authority to the write boundary so
new duplicates are impossible; this script settles the legacy backlog:

  - group non-invalidated edges by exact (from_record_id, to_record_id,
    relation_type) triple (the measured duplication key);
  - keep the EARLIEST row of each group (stable tiebreak by edge_id);
  - transition every other row to ``invalidated`` (G3: invalidate, never
    delete — history lines stay in the ledger).

Durability relies on W0: each transition appends the full updated row to
``graph/edges.jsonl``, so the result survives index_sync / rebuild.

Default is DRY-RUN (prints the plan, writes nothing).  Pass ``--apply`` to
execute.  Idempotent: a second --apply run finds zero duplicate groups.

Invocation:
  python scripts/memory_os_graph_edges_compaction.py \
      --hermes-home /path/to/home --profile default [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            val = argv[i + 1]
            if val.startswith("--"):
                return ""
            return val
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


_CLI_HOME = _preparse_cli_arg(sys.argv, "--hermes-home")
_ENV_HOME = os.environ.get("HERMES_HOME", "")
_HERMES_HOME = _CLI_HOME or _ENV_HOME or str(Path.home() / ".hermes")

_self = Path(__file__).absolute()
_repo_root = _self.parents[1]
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.index import (  # noqa: E402
    MemoryOSIndex,
    _initialize_schema,
    transition_edge_state,
)
from plugins.memory.memory_os.roots import MemoryOSRoots  # noqa: E402


def _effective_edges(edges_path: Path) -> dict[str, dict]:
    """Fold the canonical ledger per edge_id, last-writer-wins in file order.

    This mirrors ``_index_edges``'s projection semantics exactly — the
    compaction must judge the same effective state the projection would.
    """
    effective: dict[str, dict] = {}
    if not edges_path.exists():
        return effective
    for raw in edges_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            edge = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("edge_id") or "")
        if edge_id:
            effective[edge_id] = edge
    return effective


def compact_duplicate_edges(roots: MemoryOSRoots, *, apply: bool) -> dict:
    edges_path = roots.memory_os_root / "graph" / "edges.jsonl"
    effective = _effective_edges(edges_path)

    groups: dict[tuple[str, str, str], list[dict]] = {}
    for edge in effective.values():
        if str(edge.get("state") or "") == "invalidated":
            continue
        key = (
            str(edge.get("from_record_id") or ""),
            str(edge.get("to_record_id") or ""),
            str(edge.get("relation_type") or ""),
        )
        groups.setdefault(key, []).append(edge)

    duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}
    victims: list[str] = []
    for _key, members in sorted(duplicate_groups.items()):
        members.sort(key=lambda e: (str(e.get("created_at") or ""), str(e.get("edge_id") or "")))
        victims.extend(str(e.get("edge_id") or "") for e in members[1:])

    report = {
        "schema_version": "memory-os.graph_edges_compaction.v0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ledger_row_count": sum(1 for _ in edges_path.read_text(encoding="utf-8").splitlines()) if edges_path.exists() else 0,
        "effective_edge_count": len(effective),
        "live_edge_count": sum(len(v) for v in groups.values()),
        "duplicate_group_count": len(duplicate_groups),
        "invalidate_planned_count": len(victims),
        "applied": bool(apply),
        "invalidated_count": 0,
        "failed_count": 0,
        "failed_edge_ids": [],
    }

    if not apply or not victims:
        return report

    conn = sqlite3.connect(str(roots.index_path))
    try:
        _initialize_schema(conn)
        for edge_id in victims:
            result = transition_edge_state(conn, edge_id, "invalidated", roots=roots)
            if result and result.get("state") == "invalidated":
                report["invalidated_count"] += 1
            else:
                report["failed_count"] += 1
                report["failed_edge_ids"].append(edge_id)
    finally:
        conn.close()

    # Durable evidence for the one-time operation (apply runs only).
    out = roots.memory_os_root / "system" / "graph_edges_compaction_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=_HERMES_HOME)
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE", "default"))
    parser.add_argument("--apply", action="store_true", help="execute (default: dry-run)")
    args = parser.parse_args(argv)

    roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=args.profile)
    if not roots.index_path.exists():
        # No index yet — build the projection so transitions can validate.
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(roots)
        store.initialize()
        MemoryOSIndex(roots).rebuild_from_store(store)

    report = compact_duplicate_edges(roots, apply=bool(args.apply))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
