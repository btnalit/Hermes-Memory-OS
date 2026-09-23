#!/usr/bin/env python3
"""Post-deploy operator probe for the optional TypeSafe Jev judge backend (J1).

Minimal, standalone verification that:
  1. The credential env var (default ``TYPESAFE_API_KEY``) is set on this host.
  2. The real ``/v1/systemone`` endpoint answers fact_judge's exact native-noul
     durable-fact question the same way production will.

Deliberately reuses ``fact_judge._judge_via_jev`` (a private cross-module
import, precedented in this codebase -- see CLAUDE.md's "LLM Integration --
Reuse, Never Rebuild") rather than re-deriving the question mapping here, so
the probe can never silently drift from what the lane actually asks.

Never prints the API key or request headers -- only the parsed judgement
result (label/confidence/probability/model/latency) and which env var NAME
was checked (never its value).

Usage:
    python scripts/memory_os_jev_probe.py
    python scripts/memory_os_jev_probe.py --api-key-env-var TYPESAFE_API_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Location-agnostic import resolution (same pattern as the other memory_os_*
# probe scripts in this directory).
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

from plugins.memory.memory_os.jev_backend import JEV_API_KEY_ENV_VAR_DEFAULT
from plugins.modules.governance.fact_judge import _judge_via_jev

# Synthetic-only bodies -- no real personal data ever goes through this probe.
BUILT_IN_CANDIDATES: dict[str, str] = {
    "clear_durable": (
        "I prefer dark mode and always use pytest with an 80 percent "
        "coverage threshold for this project."
    ),
    "transient_moment": "Thanks! Let me check that real quick.",
    "ambiguous": "Maybe I will switch to Postgres at some point, not sure yet.",
}


def run_probe(*, api_key_env_var: str, active_crystallized_count: int = 0) -> dict[str, Any]:
    """Ask the real Jev endpoint fact_judge's durable-fact question for each
    built-in synthetic candidate. Returns a key-free, header-free report.

    Never raises -- _judge_via_jev / jev_backend are both typed-failure,
    never-raise surfaces; any transport problem shows up as a
    ``failure_reason`` per candidate, not an exception here.
    """
    key_present = bool(os.environ.get(api_key_env_var, "").strip())
    config = {"api_key_env_var": api_key_env_var}
    results: dict[str, Any] = {}
    for label, body in BUILT_IN_CANDIDATES.items():
        verdict = _judge_via_jev(body, active_crystallized_count, config)
        results[label] = {
            "durable_fact": verdict.get("durable_fact"),
            "failure_reason": verdict.get("failure_reason"),
            "judge_confidence": verdict.get("judge_confidence"),
            "jev_probability": verdict.get("jev_probability"),
            "jev_model": verdict.get("jev_model"),
            "jev_latency_ms": verdict.get("jev_latency_ms"),
        }
    return {
        "schema_version": "memory-os.jev_probe.v0",
        "api_key_env_var": api_key_env_var,
        "api_key_present": key_present,
        "active_crystallized_count": active_crystallized_count,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Post-deploy operator probe for the optional Jev judge backend "
            "(J1). Reads the credential via --api-key-env-var (default "
            f"{JEV_API_KEY_ENV_VAR_DEFAULT}). Never prints the key or headers."
        ),
    )
    parser.add_argument("--api-key-env-var", default=JEV_API_KEY_ENV_VAR_DEFAULT)
    parser.add_argument(
        "--active-crystallized-count", type=int, default=0,
        help="Simulates fact_judge's lean/strict prompt selection (default 0 = lean).",
    )
    args = parser.parse_args(argv)

    report = run_probe(
        api_key_env_var=args.api_key_env_var,
        active_crystallized_count=args.active_crystallized_count,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
