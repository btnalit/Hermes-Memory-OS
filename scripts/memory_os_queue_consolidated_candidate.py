#!/usr/bin/env python3
"""Queue one bounded consolidated crystallized-memory candidate.

This is an operator helper for closing the owner-approved crystallization loop.
It never writes crystallized memory. It only queues an approvable candidate
that must still be sent to the owner and approved through OwnerActionProcessor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

# Location-agnostic import resolution.
#
# An unconditional sys.path.insert(parents[1]) breaks on the INSTALLED layout:
# there parents[1] is $HERMES_HOME, whose plugins/ directory shadows the
# memory-os runtime namespace and yields
# "ModuleNotFoundError: No module named 'plugins.memory'". Resolve the repo
# checkout only when it actually contains the package, else fall back to the
# installed runtime tree.
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]


def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    """Extract a --flag value from raw argv before argparse runs."""
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            val = argv[i + 1]
            if val.startswith("--"):
                return ""  # next token is another flag, not a value
            return val
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


# Resolve HERMES_HOME at module level -- CLI > env > default.
_HERMES_HOME = (
    _preparse_cli_arg(sys.argv, "--hermes-home")
    or os.environ.get("HERMES_HOME", "")
    or str(Path.home() / ".hermes")
)

if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.crystallized import (  # noqa: E402
    CrystallizedCandidate,
    append_candidate_queue,
    read_candidate_queue,
)
from plugins.memory.memory_os.roots import MemoryOSRoots  # noqa: E402
from plugins.memory.memory_os.store import MemoryOSStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes"))
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE") or "default")
    parser.add_argument("--source-event-id", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--kind", default="preference")
    parser.add_argument("--sensitivity", default="private")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=args.profile)
    store = MemoryOSStore(roots)
    store.initialize()

    source_event_id = str(args.source_event_id).strip()
    body = _normalize_body(args.body)
    validation_errors = _candidate_validation_errors(store, source_event_id=source_event_id, body=body)
    candidate_id = str(args.candidate_id or _candidate_id(source_event_id, body)).strip()
    existing = {candidate.candidate_id for candidate in read_candidate_queue(store.roots)}

    report: dict[str, Any] = {
        "schema_version": "memory-os.consolidated_candidate_queue.v0",
        "profile": roots.profile or "default",
        "candidate_id": candidate_id,
        "source_event_id": source_event_id,
        "kind": str(args.kind or "preference"),
        "body_chars": len(body),
        "body_preview": body,
        "dry_run": not bool(args.apply),
        "candidate_queued": False,
        "owner_action_created": False,
        "actual_crystallized_approval": False,
        "actual_execute": False,
        "actual_send": False,
        "raw_body_included": False,
        "validation_errors": validation_errors,
        "duplicate_candidate": candidate_id in existing,
    }
    if validation_errors:
        report["status"] = "invalid"
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    if candidate_id in existing:
        report["status"] = "duplicate_ignored"
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.apply:
        append_candidate_queue(
            store,
            CrystallizedCandidate(
                candidate_id=candidate_id,
                kind=str(args.kind or "preference"),
                body=body,
                source_event_ids=[source_event_id],
                sensitivity=str(args.sensitivity or "private"),
                tags=[str(tag) for tag in args.tag],
                bridge_state="owner_eligible",
            ),
        )
        report["candidate_queued"] = True
        report["status"] = "queued"
    else:
        report["status"] = "ready"
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _candidate_validation_errors(store: MemoryOSStore, *, source_event_id: str, body: str) -> list[str]:
    errors: list[str] = []
    if not any(str(event.id) == source_event_id for event in store.read_events()):
        errors.append("source_event_not_found")
    if len(body) < 20:
        errors.append("body_too_short")
    if len(body) > 220:
        errors.append("body_too_long")
    lowered = body.lower()
    if any(marker in lowered for marker in ("user:", "assistant:", "| user", "| assistant", "用户:", "助手:")):
        errors.append("body_looks_like_transcript")
    if "evt_" in body:
        errors.append("body_contains_event_id")
    if "\n" in body:
        errors.append("body_contains_newline")
    return errors


def _candidate_id(source_event_id: str, body: str) -> str:
    digest = hashlib.sha256(f"{source_event_id}\n{body}".encode("utf-8")).hexdigest()[:16]
    return f"cand_consolidated_{digest}"


def _normalize_body(value: str) -> str:
    return " ".join(str(value or "").split())


if __name__ == "__main__":
    raise SystemExit(main())
