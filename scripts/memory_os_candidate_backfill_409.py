#!/usr/bin/env python3
"""One-time backfill script for the ~409 candidate backlog.

This script processes the existing inner_drive_candidate backlog:
  - Classifies candidates into fleeting (no decision content) or merge-worthy
  - Tags fleeting candidates in candidate_triage.jsonl
  - Merges similar high-signal candidates into owner_eligible entries
  - Never crystallizes. Output is an owner-reviewable batch.

Usage:
  python3 memory_os_candidate_backfill_409.py --dry-run        # preview only
  python3 memory_os_candidate_backfill_409.py --apply          # write triage actions
  python3 memory_os_candidate_backfill_409.py --apply --confirm-backfill  # safety gate

TASK ANCHOR: A1-A7 all enforced. Never crystallizes, never deletes.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Point to Memory-OS runtime root for plugin imports
# Script lives in ~/.hermes/scripts/; runtime is at ~/.hermes/memory-os/runtime/python/
_HERMES_HOME = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
REPO_ROOT = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
    append_candidate_triage,
    read_candidate_queue,
    read_candidate_triage,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.candidate_aggregation import (
    _is_fleeting_candidate,
    _matched_keywords,
    _cluster_key,
)


def classify_backlog(
    candidates: list[CrystallizedCandidate],
    triage_ids: set[str],
) -> dict[str, Any]:
    """Classify backlog candidates into groups.

    Returns:
      fleeting: candidates to tag as fleeting
      merge_clusters: dict of cluster_key -> [candidates] for promotion
      no_action: candidates with no clear classification
    """
    fleeting: list[CrystallizedCandidate] = []
    merge_clusters: dict[str, list[CrystallizedCandidate]] = {}
    no_action: list[CrystallizedCandidate] = []

    for c in candidates:
        if c.candidate_id in triage_ids:
            continue  # already triaged
        if _is_fleeting_candidate(c):
            fleeting.append(c)
            continue
        key = _cluster_key(c)
        if key:
            merge_clusters.setdefault(key, []).append(c)
        else:
            no_action.append(c)

    return {
        "fleeting": fleeting,
        "merge_clusters": merge_clusters,
        "no_action": no_action,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--apply", action="store_true", help="Apply triage actions")
    parser.add_argument(
        "--confirm-backfill", action="store_true",
        help="Safety gate: must be set for actual writes",
    )
    parser.add_argument(
        "--hermes-home", default=os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes"),
    )
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE") or "default")
    args = parser.parse_args(argv)

    if args.apply and not args.confirm_backfill:
        print("ERROR: --apply requires --confirm-backfill (typo protection)", file=sys.stderr)
        return 1

    hermes_home = str(args.hermes_home)
    profile = str(args.profile)

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()

    now = datetime.now(timezone.utc)
    candidates = read_candidate_queue(store)
    triage_records = read_candidate_triage(store)
    triage_ids: set[str] = set()
    for rec in triage_records:
        cid = rec.get("candidate_id")
        if cid:
            triage_ids.add(cid)

    pending = [c for c in candidates if c.candidate_id not in triage_ids]
    
    # Dedup against crystallized: skip candidates whose candidate_id already
    # exists in owner_approved.md (or any crystallized .md file).
    crystallized_service = CrystallizedMemoryService(store)
    crystallized_count = 0
    deduped: list[CrystallizedCandidate] = []
    for c in pending:
        if not crystallized_service.find_records_by_candidate_id(c.candidate_id):
            deduped.append(c)
        else:
            crystallized_count += 1
    pending = deduped
    if crystallized_count:
        print(f"Already crystallized (skipped): {crystallized_count}")
    print(f"Total candidates: {len(candidates)}")
    print(f"Already triaged: {len(triage_ids)}")
    print(f"Pending: {len(pending)}")
    print()

    classified = classify_backlog(pending, triage_ids)

    # ── Fleeting ─────────────────────────────────────────────────────
    fleeting = classified["fleeting"]
    print(f"[fleeting] {len(fleeting)} candidates — no decision content")
    for c in fleeting[:5]:
        print(f"  - {c.candidate_id}: {c.body[:60]!r}")
    if len(fleeting) > 5:
        print(f"  ... and {len(fleeting) - 5} more")

    # ── Merge clusters ───────────────────────────────────────────────
    clusters = classified["merge_clusters"]
    print(f"\n[merge] {len(clusters)} clusters")
    for key, members in sorted(clusters.items(), key=lambda x: -len(x[1])):
        mkw = _matched_keywords(members)
        print(f"  cluster '{key}': {len(members)} members, keywords={mkw}")
        for c in members[:3]:
            print(f"    - {c.candidate_id}: {c.body[:60]!r}")
        if len(members) > 3:
            print(f"    ... and {len(members) - 3} more")

    # ── No action ────────────────────────────────────────────────────
    no_action = classified["no_action"]
    print(f"\n[no_action] {len(no_action)} candidates — no clear classification")

    # ── Summary ──────────────────────────────────────────────────────
    promoted_count = sum(len(members) for members in clusters.values())
    print(f"\n{'='*50}")
    print(f"SUMMARY (dry-run={args.dry_run}, apply={args.apply})")
    print(f"  Fleeting:      {len(fleeting)}")
    print(f"  Merge+Promote: {promoted_count} (into {len(clusters)} clusters)")
    print(f"  No action:     {len(no_action)}")
    print(f"  Total:         {len(fleeting) + promoted_count + len(no_action)}")

    # ── Apply ────────────────────────────────────────────────────────
    if args.apply:
        written = 0

        # Tag fleeting
        for c in fleeting:
            append_candidate_triage(
                store,
                candidate_id=c.candidate_id,
                action="fleeting",
                target_state="fleeting",
                reason="backfill: no decision content (chat/acknowledgment only)",
                now=now,
            )
            written += 1

        # Promote clusters
        for key, members in clusters.items():
            mkw = _matched_keywords(members)
            reason = (
                f"backfill: cluster match (size={len(members)}, "
                f"keywords={mkw!r}, cluster_key={key})"
            )
            for c in members:
                append_candidate_triage(
                    store,
                    candidate_id=c.candidate_id,
                    action="promote",
                    target_state="owner_eligible",
                    reason=reason,
                    cluster_key=key,
                    now=now,
                )
                written += 1

        print(f"\n✅ Applied {written} triage actions (append-only).")
        print("   No candidates were deleted. No crystallized records were written.")
        print(f"   Owner can now review {promoted_count} promoted items via owner_actions.")
    else:
        print("\nℹ️  Dry-run mode. Use --apply --confirm-backfill to write.")

    # Anchor verification
    print("\n🔒 ANCHOR CHECK:")
    print("   actual_crystallized_approval = false (no crystallization in backfill)")
    print("   append-only = true (no deletions)")
    print("   heuristics drive presentation, not crystallization = true")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
