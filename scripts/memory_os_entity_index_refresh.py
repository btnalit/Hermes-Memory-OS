#!/usr/bin/env python3
"""Memory-OS Entity Index refresh helper (no_agent).

Extracts structural entities from crystallized records and populates
the entity_index SQLite table.  Idempotent — the table is cleared and
repopulated each call so stale entities are removed.

Fail-open: any exception is recorded and the script exits 0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
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

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.entity_index import refresh_entity_index, entity_index_stats
from plugins.memory.memory_os.knob_overrides import resolve_knob


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Memory-OS entity index (no_agent, fail-open).",
    )
    parser.add_argument(
        "--hermes-home", default=_HERMES_HOME,
        help="Path to HERMES_HOME",
    )
    parser.add_argument("--profile", default="default")
    parser.add_argument("--output", choices=("json",), default="json")
    args = parser.parse_args(argv)

    t0 = time.monotonic()
    run_status = "ok"
    error_msg = ""
    entity_count = 0
    record_count = 0

    try:
        roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=args.profile)
        enabled = bool(resolve_knob(
            "entity_index_enabled", default=False, roots=roots,
        ))
        report = refresh_entity_index(
            roots.index_path,
            roots.crystallized_root,
            enabled=enabled,
        )
        run_status = report["status"]
        entity_count = report.get("entity_count", 0)
        record_count = report.get("record_count", 0)

    except Exception as exc:
        run_status = "error"
        error_msg = f"{type(exc).__name__}: {exc}"

    duration_ms = int((time.monotonic() - t0) * 1000)

    # Append run record (fail-open)
    try:
        roots_r = MemoryOSRoots.from_hermes_home(args.hermes_home)
        run_path = roots_r.memory_os_root / "system" / "entity_index_runs.jsonl"
        run_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": "memory-os.entity_index_run.v0",
            "ts": datetime.now(timezone.utc).isoformat(),
            "status": run_status,
            "error": error_msg,
            "entity_count": entity_count,
            "record_count": record_count,
            "duration_ms": duration_ms,
        }
        with run_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as _exc:
        # fail-open — even run record failure must not crash the script.
        import sys as _sys
        _sys.stderr.write(f"entity_index_refresh: run record write failed: {_exc}\n")

    if args.output == "json":
        print(json.dumps({
            "status": run_status,
            "error": error_msg,
            "entity_count": entity_count,
            "record_count": record_count,
            "duration_ms": duration_ms,
            "profile": args.profile,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }))

    return 0


if __name__ == "__main__":
    sys.exit(main())
