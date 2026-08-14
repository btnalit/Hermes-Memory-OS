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
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
    CrystallizedWriteReceipt,
    ApprovalDecision,
    ApprovalPurpose,
    _PROBE_PROVISIONAL_WRITE_CAPABILITY,
    is_active_crystallized_frontmatter,
)
from plugins.memory.memory_os.config import load_config
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.ids import new_crystallized_id, new_event_id

# ── configuration ──────────────────────────────────────────────────
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
# System-internal probe file (not user memory).  The underscore prefix
# signals "Memory-OS owned; do not edit by hand".  The file is
# self-cleaning: after a successful revoke the probe compacts it,
# removing all inactive records, and deletes it when empty.
NONCE_FILE = HERMES_HOME / "memory-os" / "crystallized" / "_system_probe.md"

def _probe_log_slug(hermes_home: Path) -> str:
    """Per-home slug for the shared-tempdir probe log.

    Both profiles' evidence ticks fire on the same minute, and the filename
    is only second-granular, so two co-tenant probes could overwrite each
    other's diagnostics in the shared temp directory (the same shared-name
    collision class as the systemd units and the l3 last-result file, which
    now lives under HERMES_HOME). Root homes keep the legacy bare name.
    """
    home = Path(hermes_home).expanduser().resolve()
    return f"_{home.name}" if home.name and home.parent.name == "profiles" else ""


LOG_FILE = (
    Path(tempfile.gettempdir())
    / f"l3_probe{_probe_log_slug(HERMES_HOME)}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.log"
)

def _resolve_probe_budget(hermes_home: Path) -> int:
    """Read prefetch_char_budget from Memory-OS config, with 20000 fallback.

    Budgets below MIN_BUDGET (5000 chars) are too small to hold a meaningful
    Crystallized Memory section and are silently replaced by the fallback.
    """
    MIN_BUDGET = 5000
    try:
        config = load_config(hermes_home)
        budget = int(config.get("prefetch_char_budget", 0))
        if budget >= MIN_BUDGET:
            return budget
    except Exception as exc:
        import sys
        print(
            f"Warning: failed to read prefetch_char_budget from config "
            f"({type(exc).__name__}), using default 20000",
            file=sys.stderr,
        )
    return 20000

# ── nonce generation ───────────────────────────────────────────────
def _generate_nonce() -> str:
    import secrets
    # 8 alphanumeric characters = 48 bits of entropy
    token = secrets.token_hex(4).upper()
    return f"The system deployment codename is AURORA-{token}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_probe_file(service: CrystallizedMemoryService) -> str:
    """Rewrite the probe file containing only active records; delete if empty.

    After each L3 probe run, one new nonce is written and one prior nonce
    is revoked.  Over time the file would accumulate inactive records
    indefinitely.  This compaction step keeps the probe artifact lean by
    removing every record whose canonical_state is inactive, and unlinking
    the file entirely when no active records remain.
    """
    probe_name = "_system_probe.md"
    probe_path = service.store.roots.crystallized_root / probe_name
    try:
        records = service.read_records(probe_name)
    except Exception:
        return "compact: file not found (nothing to compact)"

    active = [r for r in records if is_active_crystallized_frontmatter(r.frontmatter)]
    if not active:
        # All records are inactive — remove the file entirely
        try:
            probe_path.unlink(missing_ok=True)
            return "compact: deleted (no active records)"
        except OSError as exc:
            return f"compact: delete failed ({exc})"

    inactive_count = len(records) - len(active)
    if inactive_count == 0:
        return "compact: no inactive records (already clean)"

    # Render only active records to a temp file, then atomically replace
    tmp_path = probe_path.with_suffix(".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for record in active:
                from plugins.memory.memory_os.store import _format_frontmatter
                handle.write(_format_frontmatter(record.frontmatter))
                handle.write("\n\n")
                handle.write(record.body.rstrip())
                handle.write("\n\n")
        tmp_path.replace(probe_path)
        return f"compact: removed {inactive_count} inactive record(s)"
    except Exception as exc:
        # Best-effort — failure to compact must not fail the probe
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return f"compact: failed ({exc})"


def _exercise_prefetch(
    *,
    store: MemoryOSStore,
    nonce_pos: str,
    nonce_neg: str,
    budget_chars: int,
    results: dict[str, str],
) -> tuple[bool, bool, list[str], dict[str, str]]:
    probe_queries = [
        "What is the current system deployment codename?",
        "Can you tell me the deployment codename for this system?",
        "I need to check the deployment identifier for this host.",
    ]
    dry_run_config = {"enabled": False, "mode": "dry_run"}
    l2_positive = False
    for query in probe_queries:
        context = build_prefetch(
            query, budget_chars=budget_chars, store=store, index=None,
            context_router_config=dry_run_config,
        )
        if nonce_pos in context:
            l2_positive = True
            results[f"l2_recall_positive [{query[:30]}...]"] = "✅ NONCE FOUND in prefetch context"
            break
    if not l2_positive:
        context = build_prefetch(
            probe_queries[0], budget_chars=budget_chars, store=store, index=None,
            context_router_config=dry_run_config,
        )
        results["l2_recall_positive"] = "❌ NONCE NOT FOUND in prefetch context"
        in_section = False
        for line in context.splitlines():
            if "### Crystallized Memory" in line:
                in_section = True
            elif line.startswith("### ") and in_section:
                break
            if in_section:
                results["l2_recall_debug"] = results.get("l2_recall_debug", "") + line + "\n"
        results["l2_recall_file_check"] = "nonce in _system_probe.md"

    l2_negative = False
    for query in probe_queries:
        context = build_prefetch(
            query, budget_chars=budget_chars, store=store, index=None,
            context_router_config=dry_run_config,
        )
        if nonce_neg in context:
            l2_negative = True
            results[f"l2_recall_negative [{query[:30]}...]"] = "❌ NEGATIVE NONCE FOUND (should not happen!)"
            break
    if not l2_negative:
        results["l2_recall_negative"] = "✅ negative nonce NOT recalled (expected)"
    return l2_positive, l2_negative, probe_queries, dry_run_config


def _cleanup_probe_record(
    service: CrystallizedMemoryService,
    record_id: str,
    results: dict[str, str],
) -> bool:
    try:
        revoke_result = service.revoke_record(
            record_id,
            revoked_by="probe",
            reason="L3 probe cleanup — positive nonce",
            now=datetime.now(timezone.utc),
        )
        if revoke_result.get("canonical_state_changed"):
            results["cleanup"] = "revoked: canonical_state changed"
        else:
            results["cleanup"] = f"revoke status: {revoke_result}"
        results["cleanup_compact"] = _compact_probe_file(service)
        remaining_ids = {
            str(record.frontmatter.get("id") or "")
            for record in service.read_records("_system_probe.md")
        }
        removed = record_id not in remaining_ids
        results["cleanup_record_verification"] = (
            "✅ stable record id absent after cleanup"
            if removed
            else "❌ stable record id remains after cleanup"
        )
        return removed
    except Exception as exc:
        results["cleanup"] = f"cleanup failed: {type(exc).__name__}"
        return False


# ── harness core ───────────────────────────────────────────────────
def run(cleanup: bool = True) -> dict[str, str]:
    results: dict[str, str] = {}
    budget_chars = _resolve_probe_budget(HERMES_HOME)

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
        source_state="l3_probe",
        provisional=True,
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    cleanup_ok = not cleanup
    cleanup_recall_ok = not cleanup
    l2_positive = False
    l2_negative = True
    probe_queries = ["What is the current system deployment codename?"]
    dry_run_config = {"enabled": False, "mode": "dry_run"}
    receipt = service.write_approved_record(
        cand_pos,
        dec_pos,
        file_name="_system_probe.md",
        capability=_PROBE_PROVISIONAL_WRITE_CAPABILITY,
        return_receipt=True,
    )
    if not isinstance(receipt, CrystallizedWriteReceipt):
        raise TypeError("probe write did not return a stable write receipt")
    path = receipt.path
    record_id = receipt.record_id
    try:
        log["positive_record_id"] = record_id
        log["write_path"] = str(path)
        log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
        results["write"] = f"written to {path.name}: record_id={record_id}"
        l2_positive, l2_negative, probe_queries, dry_run_config = _exercise_prefetch(
            store=store,
            nonce_pos=nonce_pos,
            nonce_neg=nonce_neg,
            budget_chars=budget_chars,
            results=results,
        )
    finally:
        if cleanup:
            cleanup_ok = _cleanup_probe_record(service, str(record_id), results)
            try:
                context_post = build_prefetch(
                    probe_queries[0], budget_chars=budget_chars, store=store, index=None,
                    context_router_config=dry_run_config,
                )
                cleanup_recall_ok = nonce_pos not in context_post
                results["cleanup_recall_verification"] = (
                    "✅ revoked nonce no longer recalled"
                    if cleanup_recall_ok
                    else "❌ revoked nonce STILL recalled"
                )
            except Exception as exc:
                cleanup_recall_ok = False
                results["cleanup_recall_verification"] = (
                    f"❌ cleanup recall verification failed: {type(exc).__name__}"
                )

    # ── final report ──────────────────────────────────────────
    all_ok = (
        l2_positive      # condition 1: positive nonce recalled
        and not l2_negative  # condition 2: negative nonce NOT recalled
        and cleanup_ok
        and cleanup_recall_ok
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
