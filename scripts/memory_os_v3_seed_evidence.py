#!/usr/bin/env python3
"""Build the V3 daily seed-evidence product as a local no-agent helper."""
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
    sys.path.insert(0, str(_REPO_ROOT))
else:
    runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if runtime_root.exists():
        sys.path.insert(0, str(runtime_root))

from plugins.memory.memory_os.config import load_config
from plugins.memory.memory_os.roots import MemoryOSRoots, resolve_profile_name
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.v3_seed_evidence import run_v3_seed_evidence_cycle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=_HERMES_HOME)
    parser.add_argument("--profile", default="")
    parser.add_argument("--target-date", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.hermes_home).get("v3_inner_life", {})
    seed_config = config.get("seed_evidence") if isinstance(config, dict) else {}
    if not isinstance(seed_config, dict) or seed_config.get("enabled") is not True:
        result = {"status": "ok", "skipped": True, "reason": "v3_seed_evidence_disabled"}
    else:
        roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=resolve_profile_name(args.hermes_home, args.profile))
        store = MemoryOSStore(roots)
        store.initialize()
        result = run_v3_seed_evidence_cycle(
            store,
            target_date=args.target_date or None,
            max_edges=int(seed_config.get("max_edges") or 10_000),
            min_coverage_ratio=float(seed_config.get("min_coverage_ratio") or 1.0),
            require_shared_entity=seed_config.get("require_shared_entity") is True,
            execution_gate_envelope_id=os.environ.get("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", ""),
        )

    summary = {
        "status": str(result.get("status") or "error"),
        "skipped": bool(result.get("skipped")),
        "reason": str(result.get("reason") or result.get("code") or ""),
        "valid": bool(result.get("valid")),
        "natural_date": str((result.get("daily_record") or {}).get("natural_date") or ""),
        "valid_day_count": int((result.get("snapshot") or {}).get("valid_day_count") or 0),
        "consecutive_valid_day_count": int((result.get("snapshot") or {}).get("consecutive_valid_day_count") or 0),
        "activation_evidence_ready": bool((result.get("snapshot") or {}).get("activation_evidence_ready")),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))

    report_path = os.environ.get("MEMORY_OS_EXECUTION_REPORT_PATH", "")
    if report_path:
        report = {
            "schema_version": "memory-os.helper_execution_report.v0",
            "boundary": {
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_unapproved_crystallized_approval": False,
            },
            "result_summary": summary,
        }
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if summary["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
