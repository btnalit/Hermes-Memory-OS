#!/usr/bin/env python3
"""Post-deploy operator probe for the optional TypeSafe Jev judge backend
(J1 native ``noul``, J2 native ``choice``).

Minimal, standalone verification that:
  1. The credential env var (default ``TYPESAFE_API_KEY``) is set on this host.
  2. The real ``/v1/systemone`` endpoint answers a lane's exact native
     question the same way production will -- ``--mode noul`` for
     fact_judge's durable-fact question (J1, default), ``--mode choice``
     for llm_edge_proposer's relation-type question (J2).

Deliberately reuses ``fact_judge._judge_via_jev`` (noul) /
``llm_edge_proposer._call_jev`` (choice) -- both private cross-module
imports, precedented in this codebase -- see CLAUDE.md's "LLM Integration --
Reuse, Never Rebuild") -- rather than re-deriving either question mapping
here, so the probe can never silently drift from what a lane actually asks.

Never prints the API key or request headers -- only the parsed judgement
result (label/relation_type/confidence/model/latency) and which env var
NAME was checked (never its value).

Usage:
    python scripts/memory_os_jev_probe.py
    python scripts/memory_os_jev_probe.py --api-key-env-var TYPESAFE_API_KEY
    python scripts/memory_os_jev_probe.py --mode choice
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
from plugins.memory.memory_os.llm_edge_proposer import _call_jev
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

# Synthetic-only record pairs for J2's native-choice relation question --
# one intended to land on each of three distinct relation buckets. The
# labels here are the probe's own organization, not an assertion Jev will
# necessarily agree -- this is a live connectivity/shape probe, not a
# correctness test.
CHOICE_BUILT_IN_PAIRS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "refines": (
        {"kind": "preference", "tags_json": ["editor"], "body": "I use VS Code as my primary editor."},
        {
            "kind": "preference", "tags_json": ["editor"],
            "body": "Specifically, I use VS Code with the Vim keybinding extension and a dark theme.",
        },
    ),
    "contradicts": (
        {"kind": "preference", "tags_json": ["database"], "body": "I always use PostgreSQL for new projects."},
        {
            "kind": "preference", "tags_json": ["database"],
            "body": "I never use PostgreSQL anymore -- I switched to SQLite for everything.",
        },
    ),
    "unrelated": (
        {"kind": "note", "tags_json": ["weather"], "body": "It rained heavily in Seattle yesterday."},
        {"kind": "note", "tags_json": ["cooking"], "body": "The recipe calls for two cups of flour and one egg."},
    ),
}


def run_probe(*, api_key_env_var: str, active_crystallized_count: int = 0) -> dict[str, Any]:
    """Ask the real Jev endpoint fact_judge's durable-fact (native ``noul``)
    question for each built-in synthetic candidate. Returns a key-free,
    header-free report.

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
        "mode": "noul",
        "api_key_env_var": api_key_env_var,
        "api_key_present": key_present,
        "active_crystallized_count": active_crystallized_count,
        "results": results,
    }


def run_choice_probe(*, api_key_env_var: str) -> dict[str, Any]:
    """Ask the real Jev endpoint llm_edge_proposer's relation-type (native
    ``choice``) question for each of three synthetic record pairs. Returns
    a key-free, header-free report.

    Never raises -- ``_call_jev`` is a typed-failure, never-raise surface;
    any transport or wire-contract problem shows up as ``outcome ==
    "jev_failed"`` plus a typed ``jev_failure_reason``, never a bare
    exception, and never a "none" relation_type silently disguising a
    failure (the ``outcome`` field is what disambiguates a real "none"
    judgement from a failed call that also fills relation_type with "none").
    """
    key_present = bool(os.environ.get(api_key_env_var, "").strip())
    config = {"api_key_env_var": api_key_env_var}
    results: dict[str, Any] = {}
    for label, (record_a, record_b) in CHOICE_BUILT_IN_PAIRS.items():
        outcome = _call_jev(record_a, record_b, config=config)
        results[label] = {
            "relation_type": outcome.get("relation_type"),
            "confidence": outcome.get("confidence"),
            "outcome": outcome.get("outcome"),
            "jev_failure_reason": outcome.get("jev_failure_reason"),
            "jev_model": outcome.get("jev_model"),
            "jev_latency_ms": outcome.get("jev_latency_ms"),
        }
    return {
        "schema_version": "memory-os.jev_probe.v0",
        "mode": "choice",
        "api_key_env_var": api_key_env_var,
        "api_key_present": key_present,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Post-deploy operator probe for the optional Jev judge backend "
            "-- J1 native noul (fact_judge, default) or J2 native choice "
            "(llm_edge_proposer, --mode choice). Reads the credential via "
            f"--api-key-env-var (default {JEV_API_KEY_ENV_VAR_DEFAULT}). "
            "Never prints the key or headers."
        ),
    )
    parser.add_argument("--api-key-env-var", default=JEV_API_KEY_ENV_VAR_DEFAULT)
    parser.add_argument(
        "--mode", choices=["noul", "choice"], default="noul",
        help="noul = fact_judge durable-fact probe (J1, default); "
             "choice = llm_edge_proposer relation-type probe (J2).",
    )
    parser.add_argument(
        "--active-crystallized-count", type=int, default=0,
        help="noul mode only: simulates fact_judge's lean/strict prompt "
             "selection (default 0 = lean).",
    )
    args = parser.parse_args(argv)

    if args.mode == "choice":
        report = run_choice_probe(api_key_env_var=args.api_key_env_var)
    else:
        report = run_probe(
            api_key_env_var=args.api_key_env_var,
            active_crystallized_count=args.active_crystallized_count,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
