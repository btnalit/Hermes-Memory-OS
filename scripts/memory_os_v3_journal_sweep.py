#!/usr/bin/env python3
"""Run the private V3 journal TTL sweep; stdout contains cycle status only."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.config import load_config
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.v3_retention import sweep_pending_expired


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE", "default"))
    parser.add_argument("--execution-gate-envelope-id", default=os.environ.get("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", ""))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roots = MemoryOSRoots.from_hermes_home(Path(args.hermes_home), profile=str(args.profile))
    store = MemoryOSStore(roots)
    store.initialize()
    config = load_config(Path(args.hermes_home)).get("v3_inner_life", {})
    ttl_days = config.get("journal_ttl_days") if isinstance(config, dict) else None
    if type(ttl_days) is not int or ttl_days <= 0:
        print('{"cycle_status":"skipped"}')
        return 0
    envelope_id = str(args.execution_gate_envelope_id or "").strip()
    try:
        report = sweep_pending_expired(store, execution_gate_envelope_id=envelope_id)
    except Exception:
        print('{"cycle_status":"error"}')
        return 2
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
