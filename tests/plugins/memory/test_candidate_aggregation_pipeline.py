"""Tests for candidate_aggregation pipeline — mutual exclusion via processed_ids.

Tests the pipeline stage logic directly. Uses a real MemoryOSStore with
a pre-created execution gate envelope so append_candidate_triage succeeds.
"""

import json
from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.candidate_aggregation import (
    _cluster_and_promote,
    _demote_aged,
    _tag_fleeting,
    _auto_demote_rejected,
    _REJECTION_THRESHOLD,
)

# Valid execution-gate envelope ID written to the store's gate envelope file
_VALID_ENVELOPE_ID = "xgate_test_candidate_aggregation_envelope"


def _store_with_gate(tmp_path) -> MemoryOSStore:
    """Create an initialized store with a pre-written valid execution-gate envelope."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    # Write a valid permit envelope so append_candidate_triage passes
    # the structural_write_gate check.
    now = datetime.now(timezone.utc)
    expires_at = now.replace(year=now.year + 1).isoformat().replace("+00:00", "Z")
    envelope = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "permit",
        "execution_gate_envelope_id": _VALID_ENVELOPE_ID,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at,
        "profile": "memoryos-test",
        "lane_id": "candidate_aggregation",
        "trigger_surface": "hermes_cron",
        "risk_class": "bounded_reversible_queue",
        "human_approval_required": False,
        "why_no_human_approval": "test",
        "scope": {"registry_key": "candidate_aggregation", "raw_script": "test"},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "boundary_true": False,
        "precheck": {"helper_present": True},
        "permit_decision": "allowed",
        "permit_reason": "boundary_false",
    }
    gate_path = roots.hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    with gate_path.open("a") as f:
        f.write(json.dumps(envelope, sort_keys=True) + "\n")

    return store


def _candidate(candidate_id="cand-test-001", kind="moment",
               body="记住：每次都要备份数据", rejection_count=0,
               bridge_state="", created_at=None):
    now = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind=kind,
        body=body,
        source_event_ids=["evt-test-001"],
        sensitivity="private",
        tags=["test"],
        bridge_state=bridge_state,
        created_at=now,
        rejection_count=rejection_count,
    )


def test_processed_ids_prevent_duplicate_processing(tmp_path):
    """Once a candidate_id is in processed_ids, no stage should process it."""
    store = _store_with_gate(tmp_path)
    c = _candidate("cand-001", body="好的")
    processed: set[str] = {"cand-001"}

    rejected = _auto_demote_rejected([c], store, processed,
                                     envelope_id=_VALID_ENVELOPE_ID)
    promoted = _cluster_and_promote([c], store, processed,
                                    envelope_id=_VALID_ENVELOPE_ID)
    demoted = _demote_aged([c], store, processed,
                           envelope_id=_VALID_ENVELOPE_ID)
    fleeting = _tag_fleeting([c], store, processed,
                             envelope_id=_VALID_ENVELOPE_ID)

    assert rejected["rejected_demoted_count"] == 0
    assert promoted["promoted_count"] == 0
    assert demoted["demoted_count"] == 0
    assert fleeting["fleeting_count"] == 0


def test_processed_ids_accumulates_across_stages(tmp_path):
    """processed_ids from stage A prevents double-processing by stage B."""
    store = _store_with_gate(tmp_path)
    chat = _candidate("cand-chat", body="好的")
    signal = _candidate("cand-signal", body="记住：每次都必须备份用户数据，这是不可妥协的规则")

    processed: set[str] = set()

    # Stage 1: auto-demote rejected (none rejected → processed stays empty)
    r1 = _auto_demote_rejected([chat, signal], store, processed,
                               envelope_id=_VALID_ENVELOPE_ID)
    assert r1["rejected_demoted_count"] == 0
    assert len(processed) == 0

    # Stage 2: _tag_fleeting tags chat → chat added to processed
    r2 = _tag_fleeting([chat, signal], store, processed,
                       envelope_id=_VALID_ENVELOPE_ID)
    assert r2["fleeting_count"] == 1, f"Expected 1 fleeting, got {r2}"
    assert "cand-chat" in processed

    # Stage 3: _cluster_and_promote should skip chat (in processed),
    # only consider signal. With Fix 1 (min_cluster_size=1) the lone signal
    # candidate routes through the resolver verdict (promoted_count == 1),
    # but chat must NOT be reprocessed.
    r3 = _cluster_and_promote([chat, signal], store, processed,
                              envelope_id=_VALID_ENVELOPE_ID)
    assert r3["promoted_count"] == 1
    # signal may or may not be added to processed — that's fine
    # The key contract: chat is NOT processed again
    assert "cand-chat" in processed
    # With Fix 1, the lone signal candidate forms a singleton cluster (size 1)
    # and is routed through the resolver; cand-signal is now in processed.
    assert "cand-signal" in processed


def test_auto_demote_rejected_at_threshold(tmp_path):
    """_auto_demote_rejected demotes candidates with rejection_count >= threshold."""
    store = _store_with_gate(tmp_path)
    over = _candidate("cand-over", body="记住：规则1",
                      rejection_count=_REJECTION_THRESHOLD)
    under = _candidate("cand-under", body="记住：规则2",
                       rejection_count=_REJECTION_THRESHOLD - 1)
    zero = _candidate("cand-zero", body="记住：规则3", rejection_count=0)

    processed: set[str] = set()
    result = _auto_demote_rejected([over, under, zero], store, processed,
                                   envelope_id=_VALID_ENVELOPE_ID)

    assert result["rejected_demoted_count"] == 1
    assert "cand-over" in processed
    assert "cand-under" not in processed
    assert "cand-zero" not in processed


def test_auto_demote_rejected_skips_processed(tmp_path):
    """Already-processed candidates are skipped by _auto_demote_rejected."""
    store = _store_with_gate(tmp_path)
    over = _candidate("cand-over", body="记住：规则1",
                      rejection_count=_REJECTION_THRESHOLD)
    processed: set[str] = {"cand-over"}

    result = _auto_demote_rejected([over], store, processed,
                                   envelope_id=_VALID_ENVELOPE_ID)
    assert result["rejected_demoted_count"] == 0


def test_demote_aged_skips_processed(tmp_path):
    """_demote_aged skips candidates in processed_ids."""
    store = _store_with_gate(tmp_path)
    old = _candidate("cand-old", body="记住：规则1",
                     created_at="2026-05-20T00:00:00Z")
    processed: set[str] = {"cand-old"}

    result = _demote_aged([old], store, processed,
                          envelope_id=_VALID_ENVELOPE_ID)
    assert result["demoted_count"] == 0


def test_fleeting_skips_processed(tmp_path):
    """_tag_fleeting skips candidates in processed_ids."""
    store = _store_with_gate(tmp_path)
    chat = _candidate("cand-chat", body="好的")
    processed: set[str] = {"cand-chat"}

    result = _tag_fleeting([chat], store, processed,
                           envelope_id=_VALID_ENVELOPE_ID)
    assert result["fleeting_count"] == 0


def test_rejection_count_dataclass_field():
    """CrystallizedCandidate correctly carries rejection_count."""
    c = _candidate("cand-rc", body="记住：规则1", rejection_count=5)
    assert c.rejection_count == 5

    c_default = _candidate("cand-default", body="记住：规则1")
    assert c_default.rejection_count == 0


# ── 14-day stale TTL vs the promote shield (starvation hole, 2026-08-14) ────
#
# Production proof of the hole: all 8 pre-August queue rows (66–98 days old)
# carried one promote→owner_eligible triage row per run — the promote stage
# re-claimed every keyword-rich candidate each run before _demote_aged could
# see it, making the 14-day stale TTL structurally unreachable. run_once's
# own comment ("Promoted candidates remain in pending so _demote_aged can
# re-evaluate stale owner_eligible ones") documented the intent the stage
# order defeated.


def _stale_owner_eligible_candidate(store, candidate_id, *, days_old):
    """Real-producer setup: an appended candidate plus a genuine
    promote→owner_eligible triage row, aged past the stale TTL."""
    from datetime import timedelta

    from plugins.memory.memory_os.crystallized import (
        append_candidate_queue,
        append_candidate_triage,
    )

    now = datetime.now(timezone.utc)
    created = (now - timedelta(days=days_old)).isoformat().replace("+00:00", "Z")
    candidate = _candidate(
        candidate_id,
        body="记住：Memory-OS 的部署配置讨论,关键词富集必然成簇的建造期元讨论。",
        created_at=created,
    )
    append_candidate_queue(store, candidate)
    append_candidate_triage(
        store,
        candidate_id=candidate_id,
        action="promote",
        target_state="owner_eligible",
        reason="cluster match (test fixture, resolver declined)",
        cluster_key="moment:记住",
        cluster_size=2,
        execution_gate_envelope_id=_VALID_ENVELOPE_ID,
        now=now - timedelta(days=days_old),
    )
    return candidate


def test_stale_owner_eligible_candidate_finally_ages_out_through_run_once(tmp_path):
    """The counterfactual for the starvation fix: with the old stage order
    (promote before aged) this candidate is re-claimed by promote every run
    and stays owner_eligible forever; with the stale sweep running first it
    must come out of run_once demoted."""
    from plugins.modules.governance.candidate_aggregation import (
        run_candidate_aggregation_lane,
    )

    store = _store_with_gate(tmp_path)
    _stale_owner_eligible_candidate(store, "cand-stale-20d", days_old=20)

    result = run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )

    assert result["stale_owner_eligible_demoted_count"] == 1, result
    assert result["demoted_count"] >= 1
    triage_rows = []
    triage_path = store.roots.crystallized_root / "candidate_triage.jsonl"
    for line in triage_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            triage_rows.append(json.loads(line))
    stale_demotes = [
        row for row in triage_rows
        if row.get("candidate_id") == "cand-stale-20d"
        and row.get("action") == "demote"
        and "stale owner_eligible" in str(row.get("reason") or "")
    ]
    assert stale_demotes, (
        "no stale-owner_eligible demote triage row — the promote stage "
        f"re-claimed it before the stale sweep. triage={triage_rows}"
    )
    # The full loop closes in the SAME run: demoted → compacted out of the
    # live queue immediately (terminal states are archived at once).
    from plugins.memory.memory_os.crystallized import read_candidate_queue

    live_ids = {c.candidate_id for c in read_candidate_queue(store.roots)}
    assert "cand-stale-20d" not in live_ids, "demoted candidate not compacted"


def _stale_candidate_from_queue(store, candidate_id):
    from plugins.memory.memory_os.crystallized import read_candidate_queue

    for candidate in read_candidate_queue(store.roots):
        if candidate.candidate_id == candidate_id:
            return candidate
    raise AssertionError(f"{candidate_id} missing from queue")


def test_young_owner_eligible_candidate_is_untouched_by_the_stale_sweep(tmp_path):
    """Two days old: the stale sweep must skip it, and the promote stage
    keeps owning it (waiting for the owner) — the fix ages out only what the
    resolver has already declined for 14+ days."""
    from plugins.modules.governance.candidate_aggregation import (
        run_candidate_aggregation_lane,
    )

    store = _store_with_gate(tmp_path)
    _stale_owner_eligible_candidate(store, "cand-young-2d", days_old=2)

    result = run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )

    assert result["stale_owner_eligible_demoted_count"] == 0, result
    # The pinned invariant is exactly "the stale sweep did not touch it".
    # What promote does next is environment-dependent (the conftest autouse
    # stub auto-allows the resolver gate, so under pytest the young candidate
    # may legitimately crystallize provisionally and leave the queue — a GOOD
    # outcome; under the real gate it stays owner_eligible). Either way, a
    # stale-demote triage row for it must not exist.
    triage_path = store.roots.crystallized_root / "candidate_triage.jsonl"
    stale_rows = [
        json.loads(line)
        for line in triage_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        and json.loads(line).get("candidate_id") == "cand-young-2d"
        and "stale owner_eligible" in str(json.loads(line).get("reason") or "")
    ]
    assert stale_rows == [], stale_rows


def test_backlogged_raw_candidate_still_reaches_the_resolver_first(tmp_path):
    """The reason the fix is NOT a blanket reorder: a 4-day-old candidate
    with NO triage history must still get the promote stage's evaluation —
    running the full aged pass before promote would demote backlogged
    candidates the resolver has never seen."""
    from datetime import timedelta

    from plugins.memory.memory_os.crystallized import append_candidate_queue
    from plugins.modules.governance.candidate_aggregation import (
        run_candidate_aggregation_lane,
    )

    store = _store_with_gate(tmp_path)
    now = datetime.now(timezone.utc)
    created = (now - timedelta(days=4)).isoformat().replace("+00:00", "Z")
    append_candidate_queue(
        store,
        _candidate(
            "cand-backlog-4d",
            body="记住：每次都必须备份用户数据,这是不可妥协的规则。",
            created_at=created,
        ),
    )

    result = run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )

    # The promote stage owned it (any promote outcome counts); the stale
    # sweep must not have touched a candidate with no owner_eligible state.
    assert result["stale_owner_eligible_demoted_count"] == 0, result
    assert result["promoted_count"] >= 1, result


# ── 洞 B：结晶残影不朽 (2026-08-14 生产 8/8 坐实) ───────────────────────────
#
# 生产队列的 8 条 66–98 天候选走的不是 promote 饿死洞——它们都曾被结晶过：
# ① run_once 的前置过滤按"有无结晶记录"把它们排除出 pending（不查活性），
#   其中 3 条的 provisional 已被 resolver 驱逐——被驱逐的记录还在替队列行
#   挡刀，任何阶段永远碰不到它；
# ② compact 用 triage-only 状态视图，看不到结晶 overlay——5 条 effective=
#   crystallized(terminal、已进召回排除) 的行因最新 triage 还写着
#   owner_eligible 而在活队列里永生。


def _crystallize_candidate(store, candidate, *, provisional):
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService

    service = CrystallizedMemoryService(store)
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver" if provisional else "owner",
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        provisional=provisional,
        expires_at=(
            datetime.now(timezone.utc).isoformat() if provisional else ""
        ),
    )
    path = service.write_approved_record(
        candidate, decision, file_name=f"{candidate.candidate_id}.md",
    )
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("id: "):
            return service, line.split("id: ", 1)[1].strip()
    raise AssertionError("record id not found")


@pytest.mark.usefixtures("crystallized_test_write_authority")
def test_evicted_provisional_no_longer_shields_the_queue_row(tmp_path):
    """被驱逐的 provisional 不再替队列行挡刀：候选重回 pending，且因 20 天
    stale 被当轮清扫降级。反事实：旧前置过滤(不查活性)下它永远不进 pending。"""
    from plugins.modules.governance.candidate_aggregation import (
        run_candidate_aggregation_lane,
    )

    store = _store_with_gate(tmp_path)
    candidate = _stale_owner_eligible_candidate(store, "cand-evicted-20d", days_old=20)
    service, record_id = _crystallize_candidate(store, candidate, provisional=True)
    service.revoke_record(record_id, revoked_by="resolver", reason="resolver_cap_evicted")

    result = run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )

    assert result["stale_owner_eligible_demoted_count"] == 1, result
    from plugins.memory.memory_os.crystallized import read_candidate_queue

    live_ids = {c.candidate_id for c in read_candidate_queue(store.roots)}
    assert "cand-evicted-20d" not in live_ids, "evicted-record shield survived"


@pytest.mark.usefixtures("crystallized_test_write_authority")
def test_actively_crystallized_row_is_archived_by_the_full_terminal_view(tmp_path):
    """活跃结晶的候选不进 pending(不得重复晋升)，但其队列行必须被完整终态
    视图归档、其 id 必须进召回排除集——不再靠 triage-only 视图在活队列永生。"""
    from plugins.memory.memory_os.crystallized import (
        read_candidate_queue,
        read_candidate_recall_exclusions,
    )
    from plugins.modules.governance.candidate_aggregation import (
        run_candidate_aggregation_lane,
    )

    store = _store_with_gate(tmp_path)
    candidate = _stale_owner_eligible_candidate(store, "cand-crystal-old", days_old=60)
    _crystallize_candidate(store, candidate, provisional=False)

    result = run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )

    # Not re-promoted, not stale-swept (it is closed, not stale):
    assert result["stale_owner_eligible_demoted_count"] == 0, result
    assert "cand-crystal-old" in read_candidate_recall_exclusions(store.roots)
    live_ids = {c.candidate_id for c in read_candidate_queue(store.roots)}
    assert "cand-crystal-old" not in live_ids, (
        "crystallized-long-ago row still immortal in the live queue"
    )


def test_compact_without_terminal_view_keeps_triage_only_behavior(tmp_path):
    """默认参数 = 历史行为：不传终态视图时，triage 说 owner_eligible 的行
    保留在活队列（钉住默认不是陷阱、老调用方行为不变）。"""
    from plugins.memory.memory_os.crystallized import (
        compact_candidate_queue,
        read_candidate_queue,
    )

    store = _store_with_gate(tmp_path)
    _stale_owner_eligible_candidate(store, "cand-triage-only", days_old=60)

    archived = compact_candidate_queue(store, provisional_backed_candidate_ids=set())

    live_ids = {c.candidate_id for c in read_candidate_queue(store.roots)}
    assert "cand-triage-only" in live_ids
    assert archived == 0


# ── Defect A counterpart, REVISED 2026-08-15: a read_effective_candidates
# failure must NOT run compaction. Reversed from the original Defect A fix,
# which degraded to terminal_candidate_ids=None (compact's own triage-only
# view) on a view failure. Defect C then established that triage-only
# compaction is exactly what archives a provisional-backed candidate
# irreversibly -- so degrading to it on the one path where we have the
# LEAST information about which candidates are provisional-backed was
# itself unsafe. A view failure now joins the two pre-existing
# upstream-error sources (read_candidate_queue, _cluster_and_promote,
# pinned separately in test_candidate_aggregation_logic.py) in skipping
# compaction outright: not compacting just lets the live queue grow --
# visible, bounded, and fully recoverable once the malformed record is
# fixed -- versus archiving under uncertainty, which is not recoverable
# (candidates.archive.jsonl has no production reader).


@pytest.mark.usefixtures("crystallized_test_write_authority")
def test_effective_view_failure_skips_compaction_and_records_the_reason(tmp_path, monkeypatch):
    """Counterfactual for the 2026-08-15 reversal: a read_effective_candidates
    failure must skip compact_candidate_queue entirely -- not run it with
    terminal_candidate_ids=None -- and the lane must record WHY via the
    closed-set compaction_skip_reason field, distinguishable from both "ran
    and archived nothing" (compaction_skip_reason is None) and the two
    pre-existing upstream-error sources.

    Two fixtures make the "compaction did not run at all" proof precise:

      - a pre-seeded `demoted` triage row -- would be archived by compact's
        own triage-only view if compaction ran (as it does in
        test_compact_without_terminal_view_keeps_triage_only_behavior's
        sibling case), so its survival here proves compaction did not run,
        not merely that it archived nothing for some other reason.
      - a crystallized ghost (permanently crystallized, stale owner_eligible
        triage, same shape as test_actively_crystallized_row_is_archived_by_
        the_full_terminal_view above) -- would ALSO be archived if
        compaction ran (via the full terminal view), so it must survive too.

    Patches aggregation.read_effective_candidates (the name bound inside the
    candidate_aggregation module at import time), not
    crystallized.read_effective_candidates -- the lane imports the symbol by
    name, so patching the source module would not reach it.
    """
    import plugins.modules.governance.candidate_aggregation as aggregation
    from plugins.memory.memory_os.crystallized import (
        append_candidate_queue,
        append_candidate_triage,
        read_candidate_queue,
    )

    store = _store_with_gate(tmp_path)

    demoted = _candidate("cand-demoted-fixture", body="记住：这是一条已裁决的候选")
    append_candidate_queue(store, demoted)
    append_candidate_triage(
        store,
        candidate_id="cand-demoted-fixture",
        action="demote",
        target_state="demoted",
        reason="pre-seeded terminal fixture",
        execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )

    ghost = _stale_owner_eligible_candidate(store, "cand-ghost-view-fail", days_old=60)
    _crystallize_candidate(store, ghost, provisional=False)

    def _raise_view_failure(_store):
        raise RuntimeError("synthetic effective-view failure")

    monkeypatch.setattr(aggregation, "read_effective_candidates", _raise_view_failure)

    result = aggregation.run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )

    assert result["status"] == "warning"
    assert "candidate_effective_view_failed" in result["recent_error_codes"]
    assert result["recall_exclusion_count"] == -1, (
        "a view failure must not silently republish recall exclusions"
    )
    assert result["compacted_count"] == 0, (
        "compaction must NOT run on a view failure -- archiving under "
        "uncertainty about which candidates are provisional-backed is "
        "unrecoverable, unlike a queue that merely grows"
    )
    assert result["compaction_skip_reason"] == "effective_view_unavailable", (
        "the reason must be durable and distinguishable from the two "
        f"pre-existing upstream-error sources, got {result['compaction_skip_reason']!r}"
    )
    live_ids = {c.candidate_id for c in read_candidate_queue(store.roots)}
    assert "cand-demoted-fixture" in live_ids, (
        "demoted row was archived -- compaction ran despite the view "
        "failure, which is exactly the unsafe fallback this test guards "
        "against"
    )
    assert "cand-ghost-view-fail" in live_ids, (
        "crystallized-ghost row was archived -- compaction ran despite the "
        "view failure"
    )


# ── Defect B: provisional-backed terminality must not be archivable ────────
#
# Verified chain: any active crystallized record (provisional included)
# marks a candidate terminal in read_effective_candidates. Before this fix,
# candidate_aggregation passed that FULL terminal set straight to
# compact_candidate_queue, so a resolver-approved provisional candidate got
# archived out of the live queue on the same or a later tick. Once
# provisional_sweep later invalidates the provisional (TTL/cap eviction),
# the candidate is in NEITHER the live queue NOR active crystallized memory
# -- candidates.archive.jsonl has no production reader, so there is no
# automatic path back. The fix: EffectiveCandidate.provisional_backed marks
# "terminal only because of an active provisional record, no active
# permanent record backs it", and the lane excludes those ids from the set
# it hands to compact_candidate_queue while still including them in the
# FULL set it publishes to write_candidate_recall_exclusions (the content is
# already in crystallized memory, so it must not double-surface in recall).


@pytest.mark.usefixtures("crystallized_test_write_authority")
def test_provisional_backed_terminal_row_is_not_archived(tmp_path):
    """Counterfactual for Defect B: a provisional-backed terminal candidate
    must stay in the live queue -- archival is one-way, and the provisional
    anchor is reversible by design (resolver TTL/cap eviction, owner
    reject). It IS excluded from recall (content already crystallized).

    Deliberately the provisional=True mirror of
    test_actively_crystallized_row_is_archived_by_the_full_terminal_view
    above (same _stale_owner_eligible_candidate baseline, same days_old=60,
    same owner_eligible triage state) so the only variable is the
    provisional flag -- isolating exactly what changed."""
    from plugins.memory.memory_os.crystallized import (
        read_candidate_queue,
        read_candidate_recall_exclusions,
    )
    from plugins.modules.governance.candidate_aggregation import (
        run_candidate_aggregation_lane,
    )

    store = _store_with_gate(tmp_path)
    candidate = _stale_owner_eligible_candidate(store, "cand-prov-backed", days_old=60)
    _crystallize_candidate(store, candidate, provisional=True)

    result = run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )

    # Not re-promoted, not stale-swept (shielded by the active provisional
    # record, same pre-filter as the permanent case):
    assert result["stale_owner_eligible_demoted_count"] == 0, result
    live_ids = {c.candidate_id for c in read_candidate_queue(store.roots)}
    assert "cand-prov-backed" in live_ids, (
        "provisional-backed row was archived -- the provisional anchor is "
        "reversible, archival is not"
    )
    assert "cand-prov-backed" in read_candidate_recall_exclusions(store.roots), (
        "a provisional-backed candidate must still be excluded from recall "
        "-- its content is already in crystallized memory"
    )


@pytest.mark.usefixtures("crystallized_test_write_authority")
def test_invalidated_provisional_lets_the_pipeline_reach_the_candidate_again(tmp_path):
    """Counterfactual for Defect B's reversal half: once the provisional
    anchor is invalidated through the REAL API
    (invalidate_provisional_record with resolver_ttl_expired -- the same
    call provisional_sweep makes), the candidate must resurface as
    non-terminal so the pipeline can reach it again. Mirrors
    test_evicted_provisional_no_longer_shields_the_queue_row above (which
    uses revoke_record with resolver_cap_evicted); this uses the TTL-expiry
    path the acceptance criteria calls out explicitly."""
    from plugins.memory.memory_os.crystallized import (
        read_candidate_queue,
        read_effective_candidates,
    )
    from plugins.modules.governance.candidate_aggregation import (
        run_candidate_aggregation_lane,
    )

    store = _store_with_gate(tmp_path)
    candidate = _stale_owner_eligible_candidate(store, "cand-prov-expires", days_old=20)
    service, record_id = _crystallize_candidate(store, candidate, provisional=True)

    # While the provisional is active, the row stays but is terminal.
    pre_effective = {
        item.candidate.candidate_id: item for item in read_effective_candidates(store)
    }
    assert pre_effective["cand-prov-expires"].terminal is True
    assert pre_effective["cand-prov-expires"].provisional_backed is True

    service.invalidate_provisional_record(
        record_id, reason="resolver_ttl_expired", invalidated_by="provisional_sweep",
    )

    post_effective = {
        item.candidate.candidate_id: item for item in read_effective_candidates(store)
    }
    assert post_effective["cand-prov-expires"].terminal is False, (
        "candidate must resurface as non-terminal once its only anchor is "
        "invalidated"
    )

    # The pipeline can now act on it again (stale sweep reaches it, since
    # it is no longer shielded by an active crystallized record).
    result = run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )
    assert result["stale_owner_eligible_demoted_count"] == 1, result
    live_ids = {c.candidate_id for c in read_candidate_queue(store.roots)}
    assert "cand-prov-expires" not in live_ids, (
        "resurfaced candidate should now be reachable and demoted/compacted "
        "by the stale sweep, not stuck"
    )


# ── Defect C (coordinator follow-up, 2026-08-15): the retention-window
# elif/else branch inside compact_candidate_queue resolves state from triage
# rows alone (resolve_candidate_effective_state) and has no idea a candidate
# is provisional-backed. Excluding a provisional-backed id from
# archivable_terminal_ids (Defect B's fix) only protects it from the FIRST
# branch of compact_candidate_queue; a resolver-approved provisional
# candidate whose triage state is "resolver_approved" (not "owner_eligible")
# still ages out through the retention-window branch once its row passes
# retention_days -- the same loss shape as Defect B, reached a different
# way, and arguably more likely since provisional TTLs can exceed
# retention_days. The fix: compact_candidate_queue takes an explicit
# provisional_backed_candidate_ids set and keeps those rows active
# UNCONDITIONALLY, checked first, ahead of every other branch.
#
# Deliberately uses "resolver_approved" triage (not the "owner_eligible"
# baseline every earlier fixture in this file used) -- owner_eligible's
# first-clause exemption already made it immune to the age branch, which is
# exactly what left this branch untested.


def _resolver_approved_aged_candidate(store, candidate_id, *, days_old):
    """Real-producer setup mirroring _cluster_and_promote's own
    resolver-approve triage write (target_state='resolver_approved'), aged
    past retention_days. bridge_state is set to a non-default value so the
    raw-bridge_state filter in _cluster_and_promote's candidates_for_promote
    (c.bridge_state in ("", "inner_drive_candidate")) excludes it from being
    re-clustered on a later lane run -- isolating the retention/demote
    branches this test targets from an unrelated promote-stage race."""
    from datetime import timedelta

    from plugins.memory.memory_os.crystallized import (
        append_candidate_queue,
        append_candidate_triage,
    )

    now = datetime.now(timezone.utc)
    created = (now - timedelta(days=days_old)).isoformat().replace("+00:00", "Z")
    candidate = _candidate(
        candidate_id,
        body="记住：Memory-OS 的部署配置讨论,关键词富集必然成簇的建造期元讨论。",
        bridge_state="resolver_approved",
        created_at=created,
    )
    append_candidate_queue(store, candidate)
    append_candidate_triage(
        store,
        candidate_id=candidate_id,
        action="promote",
        target_state="resolver_approved",
        reason="cluster match (test fixture, resolver approved)",
        cluster_key="moment:记住",
        cluster_size=2,
        execution_gate_envelope_id=_VALID_ENVELOPE_ID,
        now=now - timedelta(days=days_old),
    )
    return candidate


@pytest.mark.usefixtures("crystallized_test_write_authority")
def test_provisional_backed_resolver_approved_row_survives_retention_window_archival(tmp_path):
    """Counterfactual for Defect C: a provisional-backed candidate whose
    triage state is resolver_approved (not owner_eligible) and whose row is
    aged past retention_days must still survive compaction. Without
    provisional_backed_candidate_ids reaching compact_candidate_queue, this
    row falls through the terminal-ids branch (correctly excluded by Defect
    B) straight into the retention-window elif/else, which does not know it
    is provisional-backed and archives it once age >= retention_days.

    Then invalidates the provisional through the REAL API
    (invalidate_provisional_record, resolver_ttl_expired) and shows the
    pipeline can still reach and act on the candidate afterward."""
    from plugins.memory.memory_os.crystallized import (
        read_candidate_queue,
        read_candidate_recall_exclusions,
        read_effective_candidates,
    )
    from plugins.modules.governance.candidate_aggregation import (
        run_candidate_aggregation_lane,
    )

    store = _store_with_gate(tmp_path)
    candidate = _resolver_approved_aged_candidate(
        store, "cand-resolver-approved-aged", days_old=20,
    )
    service, record_id = _crystallize_candidate(store, candidate, provisional=True)

    result = run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )

    live_ids = {c.candidate_id for c in read_candidate_queue(store.roots)}
    assert "cand-resolver-approved-aged" in live_ids, (
        "provisional-backed row with resolver_approved triage, aged past "
        "retention_days, was archived through the retention-window branch "
        "-- the reversibility guarantee was not enforced on every branch "
        f"of compact_candidate_queue. result={result}"
    )
    assert "cand-resolver-approved-aged" in read_candidate_recall_exclusions(store.roots), (
        "a provisional-backed candidate must still be excluded from recall"
    )

    # Reversal half: once the provisional anchor is invalidated through the
    # real API, the candidate must resurface as non-terminal...
    service.invalidate_provisional_record(
        record_id, reason="resolver_ttl_expired", invalidated_by="provisional_sweep",
    )
    post_effective = {
        item.candidate.candidate_id: item for item in read_effective_candidates(store)
    }
    assert post_effective["cand-resolver-approved-aged"].terminal is False, (
        "candidate must resurface as non-terminal once its only anchor is "
        "invalidated"
    )

    # ...and the pipeline must be able to reach and act on it again (no
    # longer shielded by an active crystallized record, it is now old
    # enough for the general aged-demote sweep to close it).
    result2 = run_candidate_aggregation_lane(
        store, execution_gate_envelope_id=_VALID_ENVELOPE_ID,
    )
    assert result2["demoted_count"] >= 1, result2
    live_ids_after = {c.candidate_id for c in read_candidate_queue(store.roots)}
    assert "cand-resolver-approved-aged" not in live_ids_after, (
        "resurfaced candidate should now be reachable and demoted/compacted "
        "by the general aged sweep, not stuck"
    )
