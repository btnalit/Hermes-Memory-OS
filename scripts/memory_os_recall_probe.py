#!/usr/bin/env python3
"""Memory-OS recall probe — debug each retriever independently.

Usage::

    python scripts/memory_os_recall_probe.py --type state_overlay
    python scripts/memory_os_recall_probe.py --type crystallized --query "preference"
    python scripts/memory_os_recall_probe.py --type temporal --query "上次做到哪了"
    python scripts/memory_os_recall_probe.py --type all --query "memory"

Output: JSON with structured RecallObject per lane.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Location-agnostic import resolution.
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]
_HERMES_HOME = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")

if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.recall_types import RecallType
from plugins.memory.memory_os.recall_facade import RetrieverFacade
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

# ── Retriever imports — each lane is independently importable ─────────
from plugins.memory.memory_os.retrievers.state_overlay import StateOverlayRetriever
from plugins.memory.memory_os.retrievers.crystallized import CrystallizedRetriever
from plugins.memory.memory_os.retrievers.indexed_fts import IndexedFTSRetriever
from plugins.memory.memory_os.retrievers.temporal import TemporalRetriever
from plugins.memory.memory_os.retrievers.entity_graph import EntityGraphRetriever

# L2 retrievers — imported only when requested
_L2_RETRIEVERS: dict[str, type] = {}  # filled lazily

AVAILABLE_RETRIEVERS: dict[str, type] = {
    RecallType.STATE_OVERLAY.value: StateOverlayRetriever,
    RecallType.CRYSTALLIZED.value: CrystallizedRetriever,
    RecallType.INDEXED_FTS.value: IndexedFTSRetriever,
    RecallType.TEMPORAL.value: TemporalRetriever,
    RecallType.ENTITY_GRAPH.value: EntityGraphRetriever,
}


def _build_facade(types: list[str]) -> RetrieverFacade:
    facade = RetrieverFacade()
    for rt_str in types:
        if rt_str == "all":
            for cls in AVAILABLE_RETRIEVERS.values():
                facade.register(cls())
            break
        cls = AVAILABLE_RETRIEVERS.get(rt_str)
        if cls is not None:
            facade.register(cls())
    return facade


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Memory-OS recall probe — debug retrievers.")
    parser.add_argument(
        "--type", dest="recall_type", default="all",
        choices=["all"] + sorted(AVAILABLE_RETRIEVERS.keys()),
        help="Recall lane to probe (default: all)",
    )
    parser.add_argument("--query", default="memory", help="Search query")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--hermes-home", default=_HERMES_HOME,
        help="Path to HERMES_HOME",
    )
    parser.add_argument("--profile", default="default")
    parser.add_argument("--output", choices=("json",), default="json")
    args = parser.parse_args(argv)

    types = (
        sorted(AVAILABLE_RETRIEVERS.keys())
        if args.recall_type == "all"
        else [args.recall_type]
    )

    roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=args.profile)
    store = MemoryOSStore(roots)
    store.initialize()

    facade = _build_facade(types)
    results = facade.retrieve(
        store, args.query, top_k=args.top_k,
        scope={"session_id": "probe", "current_task_anchor": ""},
    )

    output = {
        "schema_version": "memory-os.recall_probe.v0",
        "query": args.query,
        "recall_types": types,
        "results": {
            rt: [obj.to_dict() for obj in objs]
            for rt, objs in results.items()
        },
        "summary": {
            rt: len(objs) for rt, objs in results.items()
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
