#!/usr/bin/env python3
"""Capability-gated private V3 wandering helper; aggregate stdout only."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    for index, arg in enumerate(argv):
        if arg == flag and index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            return argv[index + 1]
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


_HERMES_HOME = _preparse_cli_arg(sys.argv, "--hermes-home") or os.environ.get("HERMES_HOME", "") or str(Path.home() / ".hermes")
_SELF = Path(__file__).absolute()
_REPO_ROOT = _SELF.parents[1]
if (_REPO_ROOT / "plugins" / "memory" / "memory_os").exists():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
else:
    _RUNTIME_ROOT = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _RUNTIME_ROOT.exists() and str(_RUNTIME_ROOT) not in sys.path:
        sys.path.insert(0, str(_RUNTIME_ROOT))

from plugins.memory.memory_os.config import load_config
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.v3_ephemeral_adapter import HermesEphemeralAdapter, resolve_host_route_snapshot
from plugins.memory.memory_os.v3_wandering import (
    collect_seed_inputs_from_store,
    evaluate_v3_quiet_gate,
    record_v3_wandering_run,
    run_v3_wandering_cycle,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    args = parser.parse_args(argv)
    home = Path(args.hermes_home).expanduser().resolve()
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(home, profile="default"))
    store.initialize()
    cfg = load_config(home).get("v3_inner_life", {})
    cfg = cfg if isinstance(cfg, dict) else {}
    quiet_gate = evaluate_v3_quiet_gate(store, cfg)
    adapter = HermesEphemeralAdapter(
        host_agent_root=Path(cfg["host_agent_root"]) if cfg.get("host_agent_root") else None,
        hermes_home=home,
    )
    if quiet_gate.get("quiet") is not True:
        result = {"status": "skipped", "reason": str(quiet_gate.get("reason") or "quiet_gate_closed")}
    elif not adapter.capability:
        result = {"status": "capability_unavailable", "model_input_transmitted": False, "owner_delivery_attempted": False, "external_action_executed": False}
    else:
        seeds, edges, window, cursors = collect_seed_inputs_from_store(store)
        if not seeds:
            result = {"status": "skipped", "reason": "no_resolved_seed_candidates"}
        else:
            result = run_v3_wandering_cycle(
                store,
                adapter=adapter,
                route_snapshot=resolve_host_route_snapshot(home),
                seed_candidates=seeds,
                edges=edges,
                quiet_gate=quiet_gate,
                ttl_days=int(cfg["journal_ttl_days"]),
                max_entry_chars=int(cfg["journal_max_entry_chars"]),
                max_lineage_hops=int(cfg["journal_max_lineage_hops"]),
                model_input_char_budget=int(cfg["wandering_model_input_char_budget"]),
                execution_gate_envelope_id=str(os.environ.get("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID") or ""),
                source_window=window,
                source_cursors=cursors,
            )
    record_v3_wandering_run(store, result)
    public = {
        "status": str(result.get("status") or "unknown"),
        "model_input_transmitted": result.get("model_input_transmitted") is True,
        "owner_delivery_attempted": result.get("owner_delivery_attempted") is True,
        "external_action_executed": result.get("external_action_executed") is True,
    }
    print(json.dumps(public, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
