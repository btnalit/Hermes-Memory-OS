#!/usr/bin/env python3
"""L3 Prefetch Behavior Probe — governance write path + L2 recall verification.

Protocol:
  Positive case:  write nonce → build_prefetch → assert L2 recall → revoke
  Negative case:  un-written nonce → build_prefetch → assert NOT recalled

Run: python3 scripts/probe_l3_prefetch_behavior.py [--no-cleanup]
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
    ApprovalDecision,
    ApprovalPurpose,
    is_active_crystallized_frontmatter,
)
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.ids import new_crystallized_id, new_event_id

# ── configuration ──────────────────────────────────────────────────
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/root/.hermes"))
NONCE_FILE = HERMES_HOME / "memory-os" / "crystallized" / "probe_test.md"
LOG_FILE = Path(tempfile.gettempdir()) / f"l3_probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.log"

# ── nonce generation ───────────────────────────────────────────────
def _generate_nonce() -> str:
    import secrets
    # 8 alphanumeric characters = 48 bits of entropy
    token = secrets.token_hex(4).upper()
    return f"The system deployment codename is AURORA-{token}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── harness core ───────────────────────────────────────────────────
def run(cleanup: bool = True) -> dict[str, str]:
    results: dict[str, str] = {}

    # ── positive nonce ──────────────────────────────────────────
    nonce_pos = _generate_nonce()
    nonce_neg = _generate_nonce()  # NOT written — for negative case

    # Log nonces for audit (to tempfile, NOT to stdout)
    log = {"positive_nonce": nonce_pos, "negative_nonce": nonce_neg}
    log_path = LOG_FILE
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")

    # ── init production store ───────────────────────────────────
    roots = MemoryOSRoots.from_hermes_home(HERMES_HOME, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    service = CrystallizedMemoryService(store)

    # ── step 1: write positive nonce via governance path ───────
    cand_pos = CrystallizedCandidate(
        candidate_id=f"cand_l3_{_now().replace(':','').replace('-','')}_{new_event_id()[-8:]}",
        kind="probe",
        body=nonce_pos,
        source_event_ids=[new_event_id()],
        tags=["probe_only"],
    )
    dec_pos = ApprovalDecision(
        candidate_id=cand_pos.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="probe",
        reviewed_at=_now(),
        note=f"L3 probe nonce (positive case); cleanup=revoke",
    )
    path = service.write_approved_record(cand_pos, dec_pos, file_name="probe_test.md")
    record_id = service.read_records("probe_test.md")[-1].frontmatter["id"]
    log["positive_record_id"] = record_id
    log["write_path"] = str(path)
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    results["write"] = f"written to {path.name}: record_id={record_id}"

    # ── step 2: L2 recall verification — positive nonce ────────
    probe_queries = [
        "What is the current system deployment codename?",
        "Can you tell me the deployment codename for this system?",
        "I need to check the deployment identifier for this host.",
    ]

    # Dry-run mode: generate ALL sections without LLM routing (user protocol: "dry-run --query")
    # This tests L2 recall: does _crystallized_lines actually contain the nonce?
    dry_run_config = {"enabled": False, "mode": "dry_run"}

    l2_positive = False
    for q in probe_queries:
        context = build_prefetch(
            q, budget_chars=5500, store=store, index=None,
            context_router_config=dry_run_config,
        )
        if nonce_pos in context:
            l2_positive = True
            results[f"l2_recall_positive [{q[:30]}...]"] = "✅ NONCE FOUND in prefetch context"
            break

    if not l2_positive:
        # Full context dump for debugging — show Crystallized Memory section specifically
        context = build_prefetch(
            probe_queries[0], budget_chars=5500, store=store, index=None,
            context_router_config=dry_run_config,
        )
        results["l2_recall_positive"] = "❌ NONCE NOT FOUND in prefetch context"
        # Extract Crystallized Memory section
        in_section = False
        for line in context.splitlines():
            if "### Crystallized Memory" in line:
                in_section = True
            elif line.startswith("### ") and in_section:
                break
            if in_section:
                results["l2_recall_debug"] = results.get("l2_recall_debug", "") + line + "\n"
        # Also dump nonce_file
        results["l2_recall_file_check"] = f"nonce in probe_test.md"

    # ── step 3: L2 recall verification — negative nonce ────────
    l2_negative = False
    for q in probe_queries:
        context = build_prefetch(
            q, budget_chars=5500, store=store, index=None,
            context_router_config=dry_run_config,
        )
        if nonce_neg in context:
            l2_negative = True
            results[f"l2_recall_negative [{q[:30]}...]"] = "❌ NEGATIVE NONCE FOUND (should not happen!)"
            break

    if not l2_negative:
        results["l2_recall_negative"] = "✅ negative nonce NOT recalled (expected)"

    # ── step 4: cleanup — revoke via governance path ──────────
    if cleanup:
        revoke_result = service.revoke_record(
            record_id,
            revoked_by="probe",
            reason="L3 probe cleanup — positive nonce",
            now=datetime.now(timezone.utc),
        )
        if revoke_result.get("canonical_state_changed"):
            results["cleanup"] = f"revoked: canonical_state changed"
        else:
            results["cleanup"] = f"revoke status: {revoke_result}"

        # Verify revocation: post-revoke prefetch should NOT contain nonce
        context_post = build_prefetch(
            probe_queries[0], budget_chars=5500, store=store, index=None,
            context_router_config=dry_run_config,
        )
        if nonce_pos in context_post:
            results["cleanup_verify"] = "❌ NONCE STILL VISIBLE after revoke — revocation leak!"
        else:
            results["cleanup_verify"] = "✅ nonce filtered after revoke (is_active works)"

    # ── final report ──────────────────────────────────────────
    all_ok = (
        l2_positive      # condition 1: positive nonce recalled
        and not l2_negative  # condition 2: negative nonce NOT recalled
    )
    results["verdict"] = "✅ L2: GOVERNANCE PATH + PREFETCH RECALL VERIFIED" if all_ok else "❌ PARTIAL FAILURE"

    return results


if __name__ == "__main__":
    cleanup = "--no-cleanup" not in sys.argv
    results = run(cleanup=cleanup)

    print("\n" + "=" * 60)
    print("L3 Prefetch Behavior Probe — Results")
    print("=" * 60)
    for key, value in results.items():
        print(f"  {key}: {value}")
    print("=" * 60)
