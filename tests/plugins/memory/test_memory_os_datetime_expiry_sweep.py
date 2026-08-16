"""Counterfactual coverage for the Rule-5 datetime-expiry sweep (2026-08-15).

Defect shape (first fixed in knob_overrides.py::_is_expired, the reference
implementation): ``datetime.fromisoformat(naive_iso_string)`` parses without
error and returns a timezone-*naive* datetime. Comparing/subtracting it
against a timezone-*aware* ``now`` raises
``TypeError: can't subtract offset-naive and offset-aware datetimes`` --
which a bare ``except ValueError:`` (or no try/except at all) does not
catch, so the naive-but-otherwise-valid record crashes the caller instead
of being handled by whatever fail-open/fail-safe contract the site intended
for genuinely unparseable input.

This file covers the six sites fixed in this sweep:
  - owner_actions.py::_provisional_knob_override_review_items
  - override_sweep.py::OverrideSweepModule.run_once (TTL expiry)
  - provisional_sweep.py::ProvisionalSweepModule.run_once (TTL expiry)
  - provisional_sweep.py::find_expiring_provisional
  - deep_reflection.py::_reject_reason
  - event_stats.py::read_event_stats
  - working.py::WorkingMemoryService.decay_items (no try/except at all --
    different shape, see the dedicated section below)
  - working.py::WorkingMemoryService.prune_expired_items (a *second*,
    undocumented instance of the same shape found during this sweep: the
    existing except only wrapped the parse, not the subtraction that
    followed it)

Each test proves two things: the fixed site does not raise on a
naive-but-valid stored timestamp, AND it computes the correct answer
(normalizing naive-as-UTC) rather than merely swallowing the crash into a
different wrong answer.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


# ── shared fixtures ──────────────────────────────────────────────────────

def _store(tmp_path: Path, profile: str = "test") -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


# ── 1. owner_actions.py::_provisional_knob_override_review_items ────────

class TestOwnerActionsKnobOverrideDigest:
    def test_naive_future_expires_at_yields_correct_days_left(self, tmp_path):
        """A knob-override record with a naive (no-offset) future expires_at
        must not crash the digest render, and days_left must reflect the
        real remaining time (not just a swallowed-to-empty fallback).

        Fixture: register_override validates only that expires_at PARSES
        (knob_overrides.py line ~679: "Naive (no-offset) timestamps DO
        parse here and are accepted"), not that it is aware -- so this is
        a legitimate value a real caller can persist through the real
        producer, not a hand-edited corruption.
        """
        from plugins.memory.memory_os.knob_overrides import register_override
        from plugins.memory.memory_os.owner_actions import _provisional_knob_override_review_items

        store = _store(tmp_path)
        now = datetime.now(timezone.utc)
        naive_future_expiry = (now + timedelta(days=3)).replace(tzinfo=None).isoformat()
        # Must register through roots=store.roots (not _store_root) --
        # _provisional_knob_override_review_items reads via
        # list_active_overrides(roots=store.roots) with no _now override
        # (real wall-clock), so the fixture has to resolve to the same
        # store path the digest function will read from.
        register_override(
            "min_cluster_size", 3, prior=2, proposed_by="test",
            approved_via="resolver", expires_at=naive_future_expiry,
            _now=now, roots=store.roots,
        )

        items = _provisional_knob_override_review_items(store, closed=set())

        assert len(items) == 1
        # ~3 days remain; must not have fallen back to the "?" no-parse marker.
        assert items[0]["summary"].count("?") == 0
        assert "3d" in items[0]["summary"] or "2d" in items[0]["summary"]


# ── 2. override_sweep.py::OverrideSweepModule.run_once (TTL expiry) ─────

class TestOverrideSweepNaiveExpiry:
    def test_naive_future_expiry_does_not_crash_the_ttl_loop(self, tmp_path):
        """A naive-but-not-yet-expired override must survive run_once without
        raising, and must NOT be reverted early (it genuinely hasn't expired).

        Note: an override that is *already* expired at registration time
        never reaches override_sweep's own TTL loop at all --
        list_active_overrides() (knob_overrides.py, already fixed) filters
        expired provisional records out of `active` before override_sweep
        ever sees them, using the identical `now`. So the only way to
        exercise override_sweep.py's own parse+compare at lines 113-118 is
        with an override that is still active as of `now`: any
        naive-but-valid expires_at reaching that comparison -- regardless
        of whether it is chronologically past or future -- raises
        TypeError pre-fix, because comparing naive to aware always raises
        (the comparison operator does not evaluate order before raising).
        """
        from plugins.memory.memory_os.knob_overrides import register_override, resolve_knob
        from plugins.modules.governance.override_sweep import OverrideSweepModule

        now = datetime.now(timezone.utc)
        naive_future_expiry = (now + timedelta(days=3)).replace(tzinfo=None).isoformat()
        register_override(
            "min_cluster_size", 3, prior=2, proposed_by="test",
            approved_via="resolver", expires_at=naive_future_expiry,
            _now=now, _store_root=tmp_path,
        )

        module = OverrideSweepModule(str(tmp_path), profile="test")
        result = module.run_once(_store_root=tmp_path, _now=now)

        assert result["active_total"] == 1
        assert result["expired_count"] == 0  # not actually expired yet
        assert result["revert_fail_count"] == 0
        val = resolve_knob("min_cluster_size", default=2, _now=now, _store_root=tmp_path)
        assert val == 3  # still the override -- not prematurely reverted


# ── 3a. provisional_sweep.py::ProvisionalSweepModule.run_once (TTL) ─────

def _write_provisional_record(store: MemoryOSStore, *, record_id: str, expires_at: str, now: datetime):
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService

    service = CrystallizedMemoryService(store)
    candidate = CrystallizedCandidate(
        candidate_id=record_id,
        kind="moment",
        body=f"Sweep test memory {record_id}.",
        source_event_ids=[f"evt_{record_id}"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
    )
    decision = ApprovalDecision(
        candidate_id=record_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=now.isoformat(),
        source_state="resolver_approved",
        provisional=True,
        expires_at=expires_at,
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    return service


@pytest.mark.usefixtures("crystallized_test_write_authority")
class TestProvisionalSweepNaiveExpiry:
    def test_naive_past_expiry_ttl_sweep_invalidates_not_crashes(self, tmp_path):
        from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

        store = _store(tmp_path)
        now = datetime.now(timezone.utc)
        naive_past = (now - timedelta(hours=1)).replace(tzinfo=None).isoformat()
        service = _write_provisional_record(store, record_id="cand_naive_past", expires_at=naive_past, now=now)

        module = ProvisionalSweepModule(tmp_path, profile="test")
        result = module.run_once(store=store)

        assert result["provisional_total"] == 1
        assert result["expired_count"] == 1
        assert len(service.list_provisional_records()) == 0

    # ── 3b. provisional_sweep.py::find_expiring_provisional ─────────────

    def test_naive_near_expiry_is_found_with_correct_remaining_time(self, tmp_path):
        from plugins.modules.governance.provisional_sweep import find_expiring_provisional

        store = _store(tmp_path)
        now = datetime.now(timezone.utc)
        # 10 hours out, naive -- within the default 48h window.
        naive_near = (now + timedelta(hours=10)).replace(tzinfo=None).isoformat()
        _write_provisional_record(store, record_id="cand_naive_near", expires_at=naive_near, now=now)

        expiring = find_expiring_provisional(store, within_hours=48)

        assert len(expiring) == 1
        # Correct normalization means ~10h/~0d remaining, not a crash and
        # not a wildly-wrong value from mis-handling the naive value.
        assert 0 <= expiring[0]["hours_remaining"] <= 10
        assert expiring[0]["days_remaining"] == 0


# ── 4. deep_reflection.py::_reject_reason ────────────────────────────────

class TestDeepReflectionRejectReasonNaiveExpiry:
    def test_naive_future_expiry_is_not_rejected_as_invalid(self):
        from plugins.modules.cognition.deep_reflection import _card, _reject_reason

        now = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        card = _card(
            profile="main",
            index=0,
            text="A benign continuity note about yesterday's conversation.",
            source_refs=["event:test"],
            input_snapshot={},
            now=now,
            expires_at=(now + timedelta(hours=6)).isoformat(),
            inject_weight=1.0,
        )
        # Simulate a legacy/hand-edited card whose expires_at lost its
        # offset -- the real producer (_card, above) always stamps aware
        # ISO strings, so this can only occur via non-standard input.
        card["expires_at"] = (now + timedelta(hours=6)).replace(tzinfo=None).isoformat()

        reason = _reject_reason(card, input_snapshot={}, now=now)

        assert reason != "invalid_expiry"
        assert reason != "expired"  # 6h in the future, must not read as expired

    def test_naive_past_expiry_is_rejected_as_expired_not_crashed(self):
        from plugins.modules.cognition.deep_reflection import _card, _reject_reason

        now = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        card = _card(
            profile="main",
            index=0,
            text="A benign continuity note about yesterday's conversation.",
            source_refs=["event:test"],
            input_snapshot={},
            now=now,
            expires_at=(now - timedelta(hours=1)).isoformat(),
            inject_weight=1.0,
        )
        card["expires_at"] = (now - timedelta(hours=1)).replace(tzinfo=None).isoformat()

        reason = _reject_reason(card, input_snapshot={}, now=now)

        assert reason == "expired"

    def test_genuinely_malformed_expiry_still_falls_back_to_invalid(self):
        """Fail-open contract for truly unparseable input must survive the fix."""
        from plugins.modules.cognition.deep_reflection import _card, _reject_reason

        now = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        card = _card(
            profile="main",
            index=0,
            text="A benign continuity note about yesterday's conversation.",
            source_refs=["event:test"],
            input_snapshot={},
            now=now,
            expires_at="not-a-timestamp",
            inject_weight=1.0,
        )

        assert _reject_reason(card, input_snapshot={}, now=now) == "invalid_expiry"


# ── 5. event_stats.py::read_event_stats ──────────────────────────────────

class TestEventStatsNaiveUpdatedAt:
    def test_naive_updated_at_computes_correct_freshness_not_missing(self, tmp_path):
        from plugins.memory.memory_os.event_stats import (
            build_event_stats, event_stats_path, read_event_stats, write_event_stats,
        )

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        (roots.memory_os_root / "runtime").mkdir(parents=True, exist_ok=True)

        stats = build_event_stats([])
        stats.events_root = str(roots.events_root)
        write_event_stats(roots, stats)  # writer always stamps an aware updated_at

        # Hand-edit to a naive value: no writer in this codebase produces
        # this, but a legacy/hand-repaired file could, and read_event_stats
        # must survive it.
        path = event_stats_path(roots)
        data = json.loads(path.read_text(encoding="utf-8"))
        naive_recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(tzinfo=None).isoformat()
        data["updated_at"] = naive_recent
        path.write_text(json.dumps(data), encoding="utf-8")

        read_back, freshness = read_event_stats(roots)

        assert read_back is not None
        # 5 minutes old must read as "fresh" (<15min), not "degraded" (the
        # float("inf") fallback that a swallowed TypeError would produce).
        assert freshness == "fresh"


# ── 6a. working.py::WorkingMemoryService.decay_items (no try/except) ────

def _working_service(tmp_path: Path):
    from plugins.memory.memory_os.working import WorkingMemoryService

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return WorkingMemoryService(store)


class TestWorkingDecayNaiveOrMalformedBase:
    def test_naive_last_decayed_at_decays_correctly_not_crashed(self, tmp_path):
        """decay_items had NO try/except at all around this parse+subtract.
        A naive-but-valid last_decayed_at must decay normally (elapsed
        time computed correctly), not raise.
        """
        service = _working_service(tmp_path)
        now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
        service.add_item("lingering", "Fading thought.", weight=1.0, now=now)

        # Hand-edit last_decayed_at to a naive value via the real store
        # write path (no add_item/decay_items call ever produces a naive
        # value itself -- this simulates a legacy/hand-repaired document).
        document = service.read_document("lingering")
        document["items"][0]["last_decayed_at"] = now.replace(tzinfo=None).isoformat()
        service.store.write_working_document("lingering", document, audit=False)

        updated = service.decay_items(
            "lingering", now=now + timedelta(hours=3), half_life_hours=1.0, expire_below=0.2,
        )

        # 3 hours elapsed at half_life=1h -> weight = 1.0 * 0.5^3 = 0.125,
        # proving the naive value was normalized and used for real decay
        # math rather than falling back to "decayed just now" (weight 1.0).
        assert updated[0].weight == pytest.approx(0.125)
        assert updated[0].status == "expired"

    def test_malformed_decay_base_self_heals_without_crashing(self, tmp_path):
        """Genuinely unparseable last_decayed_at must not crash the
        heartbeat decay path. Chosen fallback: treat as "decayed just now"
        (weight unchanged this cycle) and re-stamp last_decayed_at with a
        valid aware value so the record self-heals from the next cycle,
        with a warning audit record for diagnosability.
        """
        service = _working_service(tmp_path)
        now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
        item = service.add_item("lingering", "Corrupted timestamp.", weight=1.0, now=now)

        document = service.read_document("lingering")
        document["items"][0]["last_decayed_at"] = "not-a-timestamp"
        service.store.write_working_document("lingering", document, audit=False)

        updated = service.decay_items(
            "lingering", now=now + timedelta(hours=3), half_life_hours=1.0, expire_below=0.2,
        )

        assert updated[0].weight == pytest.approx(1.0)  # unchanged this cycle
        assert updated[0].status == "active"
        # last_decayed_at re-stamped with a valid, aware value (self-heal).
        document_after = service.read_document("lingering")
        healed = document_after["items"][0]["last_decayed_at"]
        healed_dt = datetime.fromisoformat(healed)
        assert healed_dt.tzinfo is not None

        from plugins.memory.memory_os.audit import read_audit_entries
        entries = read_audit_entries(service.store.roots.audit_path)
        warnings = [e for e in entries if e.get("action") == "working_item_decay_base_invalid"]
        assert len(warnings) == 1
        assert warnings[0]["details"]["item_id"] == item.id


# ── 6b. working.py::WorkingMemoryService.prune_expired_items ────────────
#
# Second, undocumented instance of the same defect shape found during this
# sweep: the existing `except (ValueError, TypeError)` wrapped only the
# `fromisoformat` call, not the `(current - expiry_dt)` subtraction that
# followed it outside the try block -- so a naive-but-valid expired_at
# still crashed prune, just one line lower than decay's bug.

class TestWorkingPruneNaiveExpiredAt:
    def test_naive_expired_at_prunes_correctly_not_crashed(self, tmp_path):
        service = _working_service(tmp_path)
        now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
        service.add_item("attention", "Will be pruned.", weight=1.0, now=now)
        service.decay_items(
            "attention", now=now + timedelta(hours=4), half_life_hours=1.0, expire_below=0.2,
        )
        document = service.read_document("attention")
        assert document["items"][0]["status"] == "expired"
        naive_expired_at = document["items"][0]["expired_at"]
        naive_expired_at = datetime.fromisoformat(naive_expired_at).replace(tzinfo=None).isoformat()
        document["items"][0]["expired_at"] = naive_expired_at
        service.store.write_working_document("attention", document, audit=False)

        pruned = service.prune_expired_items("attention", now=now + timedelta(hours=100), min_age_hours=0)

        assert pruned == 1
        document_after = service.read_document("attention")
        assert len(document_after["items"]) == 0

    def test_malformed_expired_at_keeps_item_not_crashed(self, tmp_path):
        """Genuinely unparseable expired_at: keep the item (no data loss) --
        the pre-existing, unchanged fail-safe for this site.
        """
        service = _working_service(tmp_path)
        now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
        service.add_item("attention", "Corrupted expiry.", weight=1.0, now=now)
        service.decay_items(
            "attention", now=now + timedelta(hours=4), half_life_hours=1.0, expire_below=0.2,
        )
        document = service.read_document("attention")
        document["items"][0]["expired_at"] = "not-a-timestamp"
        document["items"][0]["updated_at"] = "not-a-timestamp"
        service.store.write_working_document("attention", document, audit=False)

        pruned = service.prune_expired_items("attention", now=now + timedelta(hours=100), min_age_hours=0)

        assert pruned == 0
        document_after = service.read_document("attention")
        assert len(document_after["items"]) == 1


# ═══════════════════════════════════════════════════════════════════════
# Round 2 (2026-08-15): eight further sites of the same defect shape,
# found by audit outside round 1's allowed files. Covers:
#   7.  scripts/cleanup_expired_working.py::main (the production
#       working_cleanup cron lane -- bypasses WorkingMemoryService, so
#       round 1's working.py fix does not protect this path)
#   8.  state_overlay.py::_read_open_threads_from_candidates
#   9.  memory_sources.py::_records_since
#   10. loop_health_view.py::_parse_recorded_at (+ build_loop_health_view)
#   11. __init__.py::_read_latest_active_task_anchor
#   12. speak_rate_limit.py::_parse_ts (+ under_speak_limit)
#   13. cli.py::diff_report
#   14. scripts/install_memory_os_plugin.py::_run_expired_working_migration
# ═══════════════════════════════════════════════════════════════════════


# ── 7. scripts/cleanup_expired_working.py::main ─────────────────────────
#
# The real working_cleanup cron lane: duplicates raw JSON manipulation
# instead of calling WorkingMemoryService, so it has its own instance of
# the "except wraps only the parse, not the subtraction" bug. This lane
# DELETES expired items, so the malformed-input fallback keeps the item
# (no data loss) -- matching working.py::prune_expired_items' direction
# -- and now also records the bad-input count in the durable
# lane_last_run counters rather than swallowing it silently.

class TestCleanupExpiredWorkingNaiveOrMalformedTimestamp:
    def test_naive_expired_timestamp_removed_not_crashed(self, tmp_path):
        from scripts import cleanup_expired_working as working_cleanup
        from plugins.memory.memory_os.lane_last_run import read_lane_last_run

        working = tmp_path / "memory-os" / "working" / "lingering.json"
        working.parent.mkdir(parents=True)
        naive_old = (datetime.now(timezone.utc) - timedelta(days=10)).replace(tzinfo=None).isoformat()
        working.write_text(
            json.dumps({"items": [{"status": "expired", "updated_at": naive_old, "text": "old"}]}),
            encoding="utf-8",
        )

        assert working_cleanup.main(str(tmp_path)) == 0

        record = read_lane_last_run(tmp_path, "working_cleanup")
        assert record["reason"] == "removed_expired_items"
        assert record["counters"]["items_removed"] == 1
        assert "items_malformed_timestamp" not in record["counters"]
        remaining = json.loads(working.read_text(encoding="utf-8"))["items"]
        assert remaining == []

    def test_malformed_timestamp_kept_and_recorded_not_crashed(self, tmp_path):
        """Genuinely unparseable timestamp: keep the item (no data loss) and
        record the malformed count in the durable lane_last_run counters
        rather than swallowing it -- this lane deletes data, so a wrong
        answer here is data loss.
        """
        from scripts import cleanup_expired_working as working_cleanup
        from plugins.memory.memory_os.lane_last_run import read_lane_last_run

        working = tmp_path / "memory-os" / "working" / "lingering.json"
        working.parent.mkdir(parents=True)
        working.write_text(
            json.dumps({"items": [{"status": "expired", "updated_at": "not-a-timestamp", "text": "corrupt"}]}),
            encoding="utf-8",
        )

        assert working_cleanup.main(str(tmp_path)) == 0

        record = read_lane_last_run(tmp_path, "working_cleanup")
        assert record["reason"] == "no_expired_items"
        assert record["counters"]["items_malformed_timestamp"] == 1
        remaining = json.loads(working.read_text(encoding="utf-8"))["items"]
        assert len(remaining) == 1  # kept, not deleted


# ── 8. state_overlay.py::_read_open_threads_from_candidates ─────────────

class TestStateOverlayOpenThreadsNaiveLastUpdated:
    def test_naive_recent_last_updated_included_not_crashed(self, tmp_path):
        """The except wrapped only the parse; the `ts < cutoff` comparison
        sat outside it. Reachable from the per-turn prefetch path, so the
        fix must stay a cheap `continue`, not add I/O or logging.
        """
        from plugins.memory.memory_os.state_overlay import _read_open_threads_from_candidates

        crystallized_root = tmp_path / "crystallized"
        crystallized_root.mkdir(parents=True)
        naive_recent = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None).isoformat()
        record = {
            "candidate_id": "cand_naive",
            "canonical_state": "owner_eligible",
            "last_updated": naive_recent,
            "summary": "A naive-timestamped open thread.",
        }
        (crystallized_root / "candidates.jsonl").write_text(
            json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8",
        )

        threads = _read_open_threads_from_candidates(crystallized_root)

        assert threads == [("A naive-timestamped open thread.", "cand_naive")]


# ── 9. memory_sources.py::_records_since ─────────────────────────────────

class TestMemorySourcesRecordsSinceNaiveCreatedAt:
    def test_naive_recent_created_at_included_not_crashed(self):
        """Pre-fix: `except ValueError` only (TypeError escaped), and the
        `created_at >= cutoff` comparison sat outside the try. On the
        per-turn disclosure path.
        """
        from plugins.memory.memory_os.memory_sources import _records_since

        naive_recent = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None).isoformat()
        records = [{"created_at": naive_recent, "id": "r1"}]

        result = _records_since(records, hours=24)

        assert result == records


# ── 10. loop_health_view.py::_parse_recorded_at ──────────────────────────

class TestLoopHealthViewNaiveRecordedAt:
    def test_naive_recorded_at_age_computed_not_crashed(self, tmp_path):
        """_parse_recorded_at caught (ValueError, TypeError) around the
        parse but never normalized a successfully-parsed naive value; the
        `moment - recorded_at` subtraction one call site above raised
        TypeError, uncaught (nothing wraps build_loop_health_view's loop).
        Fixed at the parser so every caller benefits.
        """
        from plugins.memory.memory_os.lane_last_run import lane_last_run_path
        from plugins.memory.memory_os.loop_health_view import build_loop_health_view

        now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
        naive_recorded_at = (now - timedelta(minutes=30)).replace(tzinfo=None).isoformat()
        path = lane_last_run_path(tmp_path, "full_monitor_refresh")
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "memory-os.lane_last_run.v0",
                    "lane_id": "full_monitor_refresh",
                    "recorded_at": naive_recorded_at,
                    "status": "ok",
                    "reason": "artifact_published",
                }
            ),
            encoding="utf-8",
        )

        view = build_loop_health_view(tmp_path, now=now)

        observability = next(loop for loop in view["loops"] if loop["loop"] == "observability")
        assert observability["state"] == "active"
        member = observability["members"][0]
        assert member["age_minutes"] == 30  # correct elapsed time, not a crash
        assert member.get("stale") is not True


# ── 11. __init__.py::_read_latest_active_task_anchor ─────────────────────

class TestReadLatestActiveTaskAnchorNaiveSourceAt:
    def test_naive_created_at_cross_session_age_label_not_crashed(self, tmp_path):
        """The parse caught (ValueError, TypeError) but never normalized;
        the age_min subtraction against the aware `now` sat outside the
        try. This runs during provider initialize() -- a naive source_at
        in a cross-session anchor record would crash provider startup.
        """
        import re
        from plugins.memory import load_memory_provider
        from plugins.memory.memory_os.__init__ import _active_task_anchor_path

        provider = load_memory_provider("memory_os")
        provider.initialize(
            "session-current", hermes_home=str(tmp_path), platform="cli",
            agent_identity="memoryos-test",
        )
        anchor_path = _active_task_anchor_path(provider._roots)
        anchor_path.parent.mkdir(parents=True, exist_ok=True)
        naive_created_at = (
            datetime.now(timezone.utc) - timedelta(minutes=30)
        ).replace(tzinfo=None).isoformat()
        record = {
            "schema_version": "memory-os.active_task_anchor.v0",
            "record_id": "ata_naive_cross_session",
            "created_at": naive_created_at,
            "profile": "memoryos-test",
            "session_id": "session-other",
            "anchor": (
                "### Memory-OS Current Task Anchor\n"
                "- current task: naive时间戳跨会话恢复\n"
                "- session: session-other"
            ),
            "status": "active",
            "storage_policy": "runtime_system_metadata_not_canonical_memory",
        }
        anchor_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

        recovered = provider._read_latest_active_task_anchor(max_age_hours=24)
        provider.shutdown()

        assert recovered != ""
        assert "跨会话恢复" in recovered
        # A correctly-normalized age label is a numeric "<N>m前"/"<N>h前",
        # not the "?" fallback reserved for genuinely unparseable input.
        assert re.search(r"\d+[mh]前", recovered) is not None

    def test_genuinely_malformed_created_at_falls_back_to_unknown_age(self, tmp_path):
        """Fail-open contract for truly unparseable input must survive the
        fix unchanged: age_label stays "?" rather than crashing.
        """
        from plugins.memory import load_memory_provider
        from plugins.memory.memory_os.__init__ import _active_task_anchor_path

        provider = load_memory_provider("memory_os")
        provider.initialize(
            "session-current", hermes_home=str(tmp_path), platform="cli",
            agent_identity="memoryos-test",
        )
        anchor_path = _active_task_anchor_path(provider._roots)
        anchor_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": "memory-os.active_task_anchor.v0",
            "record_id": "ata_malformed_cross_session",
            "created_at": "not-a-timestamp",
            "profile": "memoryos-test",
            "session_id": "session-other",
            "anchor": (
                "### Memory-OS Current Task Anchor\n"
                "- current task: malformed时间戳跨会话恢复\n"
                "- session: session-other"
            ),
            "status": "active",
            "storage_policy": "runtime_system_metadata_not_canonical_memory",
        }
        anchor_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

        # max_age_hours=0 (not 24): task_state.read_effective_current_task's
        # OWN age gate only runs when max_age_hours > 0 and would otherwise
        # reject this record itself (returning None) before it ever reaches
        # _read_latest_active_task_anchor's re-parse -- that would prove the
        # wrong site's fail-open contract. 0 isolates the site under test.
        recovered = provider._read_latest_active_task_anchor(max_age_hours=0)
        provider.shutdown()

        assert recovered != ""
        assert "?" in recovered


# ── 12. speak_rate_limit.py::_parse_ts ───────────────────────────────────

class TestSpeakRateLimitNaiveTimestamp:
    def test_naive_recent_ts_counts_toward_limit_not_crashed(self):
        """Pre-fix, a successfully-parsed-but-naive `ts` was returned
        un-normalized; comparing it against the aware `cutoff` in
        under_speak_limit raised TypeError. The established fail-open
        contract (genuinely unparseable -> datetime.min -> not counted,
        so bad data never falsely suppresses speech) is preserved; this
        only fixes the crash for a naive-but-real timestamp, which must
        be normalized and counted like any other recent delivery.
        """
        from plugins.modules.expression.speak_rate_limit import under_speak_limit

        now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
        naive_recent = (now - timedelta(minutes=5)).replace(tzinfo=None).isoformat()
        deliveries = [
            {"ts": naive_recent, "decision": "delivered"},
            {"ts": "2026-06-17T11:56:00+00:00", "decision": "delivered"},
            {"ts": "2026-06-17T11:57:00+00:00", "decision": "delivered"},
            {"ts": "2026-06-17T11:58:00+00:00", "decision": "delivered"},
            {"ts": "2026-06-17T11:59:00+00:00", "decision": "delivered"},
        ]

        # 5 delivered in-window (including the naive one) -> at the cap.
        assert under_speak_limit(deliveries, now=now) is False


# ── 13. cli.py::diff_report ───────────────────────────────────────────────

class TestDiffReportSinceUntilRequiresCleanInput:
    def test_naive_since_raises_clear_cli_error_not_traceback(self, tmp_path):
        """since/until are raw --since/--until CLI strings. A bare
        (offset-less) value is ambiguous user input -- the fix requires an
        explicit UTC offset and fails with a clear SystemExit message
        instead of silently assuming UTC or crashing with a raw
        TypeError traceback from the per-event comparison below.
        """
        from plugins.memory.memory_os.cli import diff_report
        from plugins.memory.memory_os.fixtures import build_event
        from plugins.memory.memory_os.schema import EventEnvelope

        store = _store(tmp_path)
        store.append_event(EventEnvelope.from_dict(build_event(seed=1, profile="test")))

        with pytest.raises(SystemExit, match="UTC offset"):
            diff_report(store, since="2026-08-01T00:00:00", until="2026-08-02T00:00:00+00:00")

    def test_unparseable_since_raises_clear_cli_error_not_traceback(self, tmp_path):
        """Pre-fix, since/until had ZERO exception handling at all -- a
        completely unparseable value raised a raw ValueError traceback.
        """
        from plugins.memory.memory_os.cli import diff_report

        store = _store(tmp_path)

        with pytest.raises(SystemExit, match="invalid --since/--until timestamp"):
            diff_report(store, since="not-a-timestamp", until="2026-08-02T00:00:00+00:00")

    def test_valid_aware_bounds_still_work(self, tmp_path):
        """Regression guard: the common case (aware since/until) must keep
        working exactly as before.
        """
        from plugins.memory.memory_os.cli import diff_report
        from plugins.memory.memory_os.fixtures import build_event
        from plugins.memory.memory_os.schema import EventEnvelope

        store = _store(tmp_path)
        store.append_event(EventEnvelope.from_dict(build_event(seed=1, profile="test")))

        report = diff_report(
            store,
            since="2026-05-20T00:00:00+00:00",
            until="2026-05-21T00:00:00+00:00",
        )

        assert report["event_count"] == 1


# ── 14. scripts/install_memory_os_plugin.py::_run_expired_working_migration

class TestInstallMigrationNaiveOrMalformedTimestamp:
    def test_naive_expired_timestamp_removed_not_crashed(self, tmp_path):
        from scripts.install_memory_os_plugin import _run_expired_working_migration

        working_dir = tmp_path / "memory-os" / "working"
        working_dir.mkdir(parents=True)
        naive_old = (datetime.now(timezone.utc) - timedelta(days=10)).replace(tzinfo=None).isoformat()
        (working_dir / "lingering.json").write_text(
            json.dumps({"items": [{"status": "expired", "updated_at": naive_old, "text": "old"}]}),
            encoding="utf-8",
        )

        result = _run_expired_working_migration(tmp_path, dry_run=False)

        assert result["status"] == "cleaned"
        assert result["removed"] == 1
        remaining = json.loads((working_dir / "lingering.json").read_text(encoding="utf-8"))["items"]
        assert remaining == []

    def test_malformed_timestamp_kept_not_crashed(self, tmp_path):
        """Same conservative direction as site 7: keep the item on
        genuinely unparseable input rather than risk deleting something
        that was not actually expired.
        """
        from scripts.install_memory_os_plugin import _run_expired_working_migration

        working_dir = tmp_path / "memory-os" / "working"
        working_dir.mkdir(parents=True)
        (working_dir / "lingering.json").write_text(
            json.dumps({"items": [{"status": "expired", "updated_at": "not-a-timestamp", "text": "corrupt"}]}),
            encoding="utf-8",
        )

        result = _run_expired_working_migration(tmp_path, dry_run=False)

        assert result["status"] == "no_expired_old"
        assert result["before"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Round 3 (2026-08-15, final): eight further sites of the same defect
# shape, found by two independent audits outside rounds 1-2's allowed
# files. Covers:
#   15. prefetch.py::_last_session_lines (per-turn hot path)
#   16. prefetch.py::_recent_cross_session_lines (per-turn hot path)
#   17. audit.py::last_audit_age_seconds (zero exception handling at all)
#   18. structural_edge_proposer.py::_detect_relation via _parse_iso
#   19. provisional_sweep.py::_days_until_expiry (silently-wrong, not crash)
#   20. override_sweep.py::_days_until_expiry (silently-wrong, not crash)
#   21. owner_actions.py::_provisional_crystallized_review_items
#       (silently-wrong, not crash)
#   22. prefetch.py::_crystallized_lines provisional countdown (both: a
#       silently-wrong countdown AND a downstream sort crash a few lines
#       away from the actual defect)
# ═══════════════════════════════════════════════════════════════════════


# ── 15. prefetch.py::_last_session_lines ─────────────────────────────────

class TestLastSessionLinesNaiveEndedAt:
    def test_naive_ended_at_age_computed_not_crashed(self, tmp_path):
        """Pre-fix, the try/except wrapped only the `fromisoformat` call;
        the `ended_at > best[0]` comparison and the `now - ended_ts`
        subtraction both sat outside it, unnormalized. Reachable from the
        per-turn prefetch path -- a naive stored ended_at would crash the
        user's turn.
        """
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from plugins.memory.memory_os.prefetch import _last_session_lines

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        anchor_path = store.roots.memory_os_root / "system" / "last_session_anchor.jsonl"
        anchor_path.parent.mkdir(parents=True, exist_ok=True)
        naive_ended_at = (
            datetime.now(timezone.utc) - timedelta(hours=5)
        ).replace(tzinfo=None).isoformat()
        record = {
            "session_id": "session-1",
            "ended_at": naive_ended_at,
            "foreground_summary": "Naive-timestamped last session.",
        }
        anchor_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

        lines = _last_session_lines(store, session_id="session-2")

        assert len(lines) == 1
        assert "5h前" in lines[0]
        assert "Naive-timestamped last session." in lines[0]


# ── 16. prefetch.py::_recent_cross_session_lines ─────────────────────────

class TestRecentCrossSessionLinesNaiveEventTs:
    def test_naive_event_ts_age_computed_not_crashed(self, tmp_path):
        """Pre-fix, the try/except wrapped only the `fromisoformat` call;
        `ts < cutoff` sat outside it, unnormalized. Reachable from the
        per-turn prefetch path.
        """
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope
        from plugins.memory.memory_os.prefetch import _recent_cross_session_lines

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        other_session_id = "sess_other_naive"
        current_session_id = "sess_current_naive"
        event_id = "evt_naive_ts_001"

        candidates_path = store.roots.crystallized_root / "candidates.jsonl"
        candidates_path.parent.mkdir(parents=True, exist_ok=True)
        candidates_path.write_text(
            json.dumps({
                "candidate_id": "cand_naive_ts",
                "kind": "moment",
                "body": "test candidate",
                "source_event_ids": [event_id],
                "tags": ["inner-drive"],
                "sensitivity": "private",
                "bridge_state": "inner_drive_candidate",
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        naive_ts = (
            datetime.now(timezone.utc) - timedelta(hours=3)
        ).replace(tzinfo=None).isoformat()
        event = EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id=event_id,
            ts=naive_ts,
            profile="test",
            source="test",
            kind="conversation_turn",
            summary="Naive timestamp cross-session summary marker.",
            safe_ref={"session_id": other_session_id},
            tags=[],
        )
        store.append_event(event)

        lines = _recent_cross_session_lines(store, session_id=current_session_id)

        assert any("Naive timestamp cross-session" in line for line in lines)
        assert any("3h前" in line for line in lines)


# ── 17. audit.py::last_audit_age_seconds ──────────────────────────────────

class TestLastAuditAgeSecondsMixedAwareness:
    def test_naive_and_aware_ts_mixed_no_crash_correct_latest(self, tmp_path):
        """Pre-fix, `max(datetime.fromisoformat(...) for entry in entries)`
        had ZERO exception handling: a mix of naive and aware `ts` values
        across entries raises TypeError inside max()'s own comparison.
        """
        from plugins.memory.memory_os.audit import last_audit_age_seconds
        from plugins.memory.memory_os.roots import MemoryOSRoots

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        audit_path = roots.audit_path
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        month_path = audit_path.parent / f"{audit_path.stem}.202608.jsonl"

        now = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        older_aware = (now - timedelta(minutes=10)).isoformat()
        newer_naive = (now - timedelta(minutes=1)).replace(tzinfo=None).isoformat()
        records = [
            {"id": "a1", "ts": older_aware, "action": "probe", "status": "ok", "target": "x", "details": {}},
            {"id": "a2", "ts": newer_naive, "action": "probe", "status": "ok", "target": "y", "details": {}},
        ]
        with month_path.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        age = last_audit_age_seconds(audit_path, now=now)

        assert age is not None
        # The most recent record is the naive one (1 minute ago), not the
        # aware one (10 minutes ago) -- proves max() correctly compared
        # them (rather than crashing) and normalized the naive value
        # instead of silently mis-ordering it.
        assert age == pytest.approx(60.0, abs=1.0)

    def test_malformed_ts_skipped_valid_ts_still_used(self, tmp_path):
        """A malformed ts string (ValueError) must not crash the whole
        function -- pre-fix there was no try/except at all around the
        parse, so one bad record broke the CLI status report for every
        entry.
        """
        from plugins.memory.memory_os.audit import last_audit_age_seconds
        from plugins.memory.memory_os.roots import MemoryOSRoots

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        audit_path = roots.audit_path
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        month_path = audit_path.parent / f"{audit_path.stem}.202608.jsonl"

        now = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        valid_recent = (now - timedelta(minutes=5)).isoformat()
        records = [
            {"id": "a1", "ts": "not-a-timestamp", "action": "probe", "status": "ok", "target": "x", "details": {}},
            {"id": "a2", "ts": valid_recent, "action": "probe", "status": "ok", "target": "y", "details": {}},
        ]
        with month_path.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        age = last_audit_age_seconds(audit_path, now=now)

        assert age == pytest.approx(300.0, abs=1.0)


# ── 18. structural_edge_proposer.py::_detect_relation via _parse_iso ─────

class TestStructuralEdgeProposerParseIsoMixedAwareness:
    def test_naive_and_aware_created_at_temporal_edge_not_crashed(self):
        """Pre-fix, `_parse_iso` never normalized a successfully-parsed
        naive value, and `ts_a - ts_b` had NO exception handling at all --
        so two crystallized records whose created_at differ in
        naive/aware-ness crashed the structural proposer for that pair.
        Bodies chosen below the dice-similarity threshold (see
        test_memory_os_edge_weights.py's identical strings) so temporal
        proximity is the only signal exercised.
        """
        from plugins.memory.memory_os.structural_edge_proposer import _detect_relation

        record_a = {
            "id": "cry_temporal_naive",
            "kind": "note",
            "tags_json": "[]",
            "source_event_ids_json": "[]",
            "body": "内容完全不同的一段甲",
            "created_at": "2026-08-07T00:00:00",  # naive
        }
        record_b = {
            "id": "cry_temporal_aware",
            "kind": "note",
            "tags_json": "[]",
            "source_event_ids_json": "[]",
            "body": "彼此毫无词面重叠乙",
            "created_at": "2026-08-07T00:10:00+00:00",  # aware, 10 min later
        }

        edges = _detect_relation(record_a, record_b)

        temporal = [e for e in edges if e["relation_type"] == "co_occurs"]
        assert temporal, (
            "naive/aware created_at pair must still produce the "
            "temporal_proximity edge, not crash or silently drop it"
        )


# ── 19. provisional_sweep.py::_days_until_expiry ──────────────────────────

class TestProvisionalSweepDaysUntilExpiryNaive:
    def test_naive_future_expiry_reports_correct_days_not_infinite(self):
        """Pre-fix, naive input hit `except (ValueError, TypeError)` (from
        the aware subtraction, not the parse) and fell back to
        float("inf"), so the record was never "expiring soon" in
        near_expiry_count -- an owner-facing prioritization miss, not a
        crash.
        """
        from plugins.modules.governance.provisional_sweep import _days_until_expiry

        naive_two_days = (
            datetime.now(timezone.utc) + timedelta(days=2)
        ).replace(tzinfo=None).isoformat()

        days = _days_until_expiry(naive_two_days)

        assert days != float("inf")
        assert 1.5 <= days <= 2.5

    def test_genuinely_malformed_expiry_still_returns_inf(self):
        """Fail-open contract for truly unparseable input must survive the
        fix unchanged.
        """
        from plugins.modules.governance.provisional_sweep import _days_until_expiry

        assert _days_until_expiry("not-a-timestamp") == float("inf")


# ── 20. override_sweep.py::_days_until_expiry ─────────────────────────────

class TestOverrideSweepDaysUntilExpiryNaive:
    def test_naive_future_expiry_reports_correct_days_not_infinite(self):
        """Same shape as provisional_sweep.py's identically-named helper."""
        from plugins.modules.governance.override_sweep import _days_until_expiry

        naive_two_days = (
            datetime.now(timezone.utc) + timedelta(days=2)
        ).replace(tzinfo=None).isoformat()

        days = _days_until_expiry(naive_two_days)

        assert days != float("inf")
        assert 1.5 <= days <= 2.5

    def test_genuinely_malformed_expiry_still_returns_inf(self):
        from plugins.modules.governance.override_sweep import _days_until_expiry

        assert _days_until_expiry("not-a-timestamp") == float("inf")


# ── 21. owner_actions.py::_provisional_crystallized_review_items ─────────

@pytest.mark.usefixtures("crystallized_test_write_authority")
class TestOwnerActionsProvisionalCrystallizedNaiveExpiry:
    def test_naive_near_expiry_priority_action_required_not_fyi(self, tmp_path):
        """Pre-fix, naive expires_at hit `except (ValueError, TypeError)`
        (from the aware subtraction, not the parse) and fell through to
        the remaining_days=999 default, silently mis-prioritizing this
        item to "fyi" in the owner digest instead of its real
        action_required urgency (<=3 days out).
        """
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
        from plugins.memory.memory_os import owner_actions as owner_actions_module

        store = _store(tmp_path)
        service = CrystallizedMemoryService(store)
        now = datetime.now(timezone.utc)
        naive_near = (now + timedelta(days=2)).replace(tzinfo=None).isoformat()

        candidate = CrystallizedCandidate(
            candidate_id="cand_oa_naive",
            kind="moment",
            body="Naive-expiry owner review item.",
            source_event_ids=["evt_oa_naive"],
        )
        decision = ApprovalDecision(
            candidate_id="cand_oa_naive",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=now.isoformat(),
            source_state="resolver_approved",
            provisional=True,
            expires_at=naive_near,
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        items = owner_actions_module._provisional_crystallized_review_items(store, closed=set())

        assert len(items) == 1
        assert items[0]["remaining_days"] <= 3
        assert items[0]["priority"] == "action_required"

    def test_genuinely_malformed_expiry_falls_back_to_999_fyi(self, tmp_path):
        """Fail-open contract for truly unparseable input must survive the
        fix unchanged: remaining_days stays 999, priority stays "fyi".
        """
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
        from plugins.memory.memory_os import owner_actions as owner_actions_module

        store = _store(tmp_path)
        service = CrystallizedMemoryService(store)
        now = datetime.now(timezone.utc)

        candidate = CrystallizedCandidate(
            candidate_id="cand_oa_malformed",
            kind="moment",
            body="Malformed-expiry owner review item.",
            source_event_ids=["evt_oa_malformed"],
        )
        decision = ApprovalDecision(
            candidate_id="cand_oa_malformed",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=now.isoformat(),
            source_state="resolver_approved",
            provisional=True,
            expires_at="not-a-timestamp",
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        items = owner_actions_module._provisional_crystallized_review_items(store, closed=set())

        assert len(items) == 1
        assert items[0]["remaining_days"] == 999
        assert items[0]["priority"] == "fyi"


# ── 22. prefetch.py::_crystallized_lines provisional countdown ───────────

@pytest.mark.usefixtures("crystallized_test_write_authority")
class TestCrystallizedLinesProvisionalCountdownNaiveExpiry:
    """Pre-fix, the try/except wrapped BOTH the parse and the subtraction,
    so a naive-but-valid expires_at did not raise immediately -- but the
    partial assignment left `expires_dt` naive (not the aware
    `datetime.max` sentinel) while `days_remaining` silently stayed at its
    999 default. That naive `expires_dt` then went into
    provisional_entries and crashed the LATER
    `provisional_entries.sort(key=lambda e: e[0])` as soon as a second
    provisional entry with a genuinely-aware expires_at existed to compare
    against -- a defect surfacing several lines away from its cause.
    """

    def test_naive_and_aware_provisional_expiry_sort_together_correct_countdown(self, tmp_path):
        import re

        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
        from plugins.memory.memory_os.prefetch import _crystallized_lines

        store = _store(tmp_path)
        service = CrystallizedMemoryService(store)
        now = datetime.now(timezone.utc)

        naive_expiry = (now + timedelta(days=2)).replace(tzinfo=None).isoformat()
        aware_expiry = (now + timedelta(days=5)).isoformat()

        cand_naive = CrystallizedCandidate(
            candidate_id="cand_ctdn_naive",
            kind="moment",
            body="Naive-expiry provisional record.",
            source_event_ids=["evt_ctdn_naive"],
        )
        dec_naive = ApprovalDecision(
            candidate_id="cand_ctdn_naive",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=now.isoformat(),
            source_state="resolver_approved",
            provisional=True,
            expires_at=naive_expiry,
        )
        service.write_approved_record(cand_naive, dec_naive, file_name="owner_approved.md")

        cand_aware = CrystallizedCandidate(
            candidate_id="cand_ctdn_aware",
            kind="moment",
            body="Aware-expiry provisional record.",
            source_event_ids=["evt_ctdn_aware"],
        )
        dec_aware = ApprovalDecision(
            candidate_id="cand_ctdn_aware",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=now.isoformat(),
            source_state="resolver_approved",
            provisional=True,
            expires_at=aware_expiry,
        )
        service.write_approved_record(cand_aware, dec_aware, file_name="owner_approved.md")

        # Pre-fix this call raises TypeError inside provisional_entries.sort()
        # as soon as both records are collected -- not at the parse site.
        lines, _degradation, _record_ids = _crystallized_lines(store)

        naive_line = next(line for line in lines if "Naive-expiry" in line)
        match = re.search(r"剩(\d+)d", naive_line)
        assert match is not None
        # ~2 days remain; must not have fallen back to the 999-day sentinel.
        assert int(match.group(1)) <= 2
