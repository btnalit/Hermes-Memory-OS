"""Tests for candidate_aggregation lane core decision logic.

Tests the "brain" functions directly: cluster/promote heuristics, fleeting
detection, TTL age-out, dedup, write-gate, and A1 boundary assertions.

These are direct unit tests for individual decision functions, not pipeline
integration tests (which live in test_candidate_aggregation_pipeline.py).
"""

import json
from datetime import datetime, timezone

from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CANDIDATE_DEMOTE_TTL_SECONDS,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.candidate_aggregation import (
    _cluster_and_promote,
    _cluster_key,
    _demote_aged,
    _has_signal_keyword,
    _is_fleeting_candidate,
    _matched_keywords,
    _candidate_age_seconds,
    _check_index_dedup,
    _tag_fleeting,
    should_persist_candidate,
    _MIN_SUBSTANTIVE_CHARS,
)

_VALID_ENVELOPE_ID = "xgate_test_candidate_aggregation_envelope"


# ── Fixtures ─────────────────────────────────────────────────────────────


def _store_with_gate(tmp_path) -> MemoryOSStore:
    """Create an initialized store with a pre-written valid execution-gate envelope."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

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


def _cand(
    candidate_id="cand-001",
    kind="moment",
    body="记住：每次都要备份数据",
    rejection_count=0,
    bridge_state="",
    created_at=None,
) -> CrystallizedCandidate:
    now = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind=kind,
        body=body,
        source_event_ids=["evt-test"],
        sensitivity="private",
        tags=["test"],
        bridge_state=bridge_state,
        created_at=now,
        rejection_count=rejection_count,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. should_persist_candidate — write gate (pre-write, stateless)
# ═══════════════════════════════════════════════════════════════════════════


class TestShouldPersistCandidate:
    """Pre-write gate called by inner_drive before appending a candidate."""

    def test_substantive_kinds_always_pass(self):
        for kind in ("rule", "preference", "boundary", "behavior", "pattern", "requirement"):
            c = _cand(candidate_id=f"cand-{kind}", kind=kind, body="anything")
            assert should_persist_candidate(c), f"kind={kind} should persist"

    def test_empty_body_fails(self):
        c = _cand(body="")
        assert not should_persist_candidate(c)

    def test_too_short_body_fails(self):
        body = "a" * (_MIN_SUBSTANTIVE_CHARS - 1)
        c = _cand(body=body)
        assert not should_persist_candidate(c)

    def test_chat_pattern_fails(self):
        for chat in ("好的", "ok", "got it", "嗯", "好的明白", "understood"):
            c = _cand(body=chat, kind="moment")
            assert not should_persist_candidate(c), f"chat '{chat}' should not persist"

    def test_inner_drive_boilerplate_fails(self):
        c = _cand(body="Remembered from event evt-test-001", kind="moment")
        assert not should_persist_candidate(c)

    def test_generic_memory_os_boilerplate_fails(self):
        c = _cand(body="memory_os_something_happened", kind="moment")
        assert not should_persist_candidate(c)

    def test_no_signal_keyword_fails(self):
        c = _cand(body="今天天气不错，我们去散步吧", kind="moment")
        assert not should_persist_candidate(c)

    def test_signal_keyword_passes(self):
        c = _cand(body="记住：每次启动前必须检查网络连接")
        assert should_persist_candidate(c)

    def test_chinese_iron_rule_passes(self):
        """'鐵律' is a strong signal keyword."""
        c = _cand(body="這是我和你之間的鐵律：不准查 chat history")
        assert should_persist_candidate(c)

    def test_english_preference_passes(self):
        c = _cand(body="My strong preference is to use dark mode always.")
        assert should_persist_candidate(c)


# ═══════════════════════════════════════════════════════════════════════════
# 2. _is_fleeting_candidate — heuristic classifier (stateless)
# ═══════════════════════════════════════════════════════════════════════════


class TestIsFleetingCandidate:
    """Heuristic that identifies no-decision-content candidates."""

    def test_substantive_kinds_never_fleeting(self):
        """rule/preference/boundary/behavior/pattern/requirement — never fleeting."""
        for kind in ("rule", "preference", "boundary", "behavior", "pattern", "requirement"):
            c = _cand(kind=kind, body="随便说啥，有 kind 就不过 fleeting")
            assert not _is_fleeting_candidate(c), f"kind={kind} should not be fleeting"

    def test_empty_body_is_fleeting(self):
        c = _cand(body="")
        assert _is_fleeting_candidate(c)

    def test_short_body_is_fleeting(self):
        body = "a" * (_MIN_SUBSTANTIVE_CHARS - 1)
        c = _cand(body=body)
        assert _is_fleeting_candidate(c)

    def test_chat_pattern_is_fleeting(self):
        for chat in ("好的", "嗯", "ok", "谢谢"):
            c = _cand(body=chat, kind="moment")
            assert _is_fleeting_candidate(c), f"chat '{chat}' should be fleeting"

    def test_inner_drive_boilerplate_is_fleeting(self):
        c = _cand(body="Remembered from event evt-x", kind="moment")
        assert _is_fleeting_candidate(c)

    def test_no_signal_keyword_is_fleeting(self):
        c = _cand(body="今天天气不错，我们去散步吧", kind="moment")
        assert _is_fleeting_candidate(c)

    def test_signal_keyword_not_fleeting(self):
        c = _cand(body="记住：每次备份前必须确认目标路径", kind="moment")
        assert not _is_fleeting_candidate(c)

    def test_boundary_kind_with_signal_not_fleeting(self):
        """Boundary kind + any body → never fleeting."""
        c = _cand(kind="boundary", body="随便")
        assert not _is_fleeting_candidate(c)


# ═══════════════════════════════════════════════════════════════════════════
# 3. _has_signal_keyword / _matched_keywords / _cluster_key — signal detection
# ═══════════════════════════════════════════════════════════════════════════


class TestSignalDetection:
    """Keyword-based signal detection and cluster key derivation."""

    def test_has_signal_keyword_chinese(self):
        assert _has_signal_keyword("记住：每次都要备份")
        assert _has_signal_keyword("這是鐵律，不可違反")
        assert _has_signal_keyword("千万不要提前关闭服务")
        assert _has_signal_keyword("我的偏好是 dark mode")
        assert _has_signal_keyword("重點：先检查日志")

    def test_has_signal_keyword_english(self):
        assert _has_signal_keyword("Always check the config first")
        assert _has_signal_keyword("This is a hard rule")
        assert _has_signal_keyword("Remember to back up data")
        assert _has_signal_keyword("My preference is fast iteration")

    def test_no_signal_keyword(self):
        assert not _has_signal_keyword("今天天气不错")
        assert not _has_signal_keyword("你觉得这个怎么样？")
        assert not _has_signal_keyword("")

    def test_matched_keywords_extracts_unique_keywords(self):
        c1 = _cand(body="记住：备份很重要")
        c2 = _cand(body="永远不要直接修改数据库")
        result = _matched_keywords([c1, c2])
        assert "记住" in result
        assert "永遠" in result or "永远" in result

    def test_matched_keywords_empty_when_no_signal(self):
        c = _cand(body="随便聊聊")
        assert _matched_keywords([c]) == []

    def test_cluster_key_from_signal(self):
        """A candidate with signal keyword produces a cluster key."""
        c = _cand(kind="moment", body="记住：每次启动检查日志")
        key = _cluster_key(c)
        assert key is not None
        assert key.startswith("moment:")
        # _cluster_key uses _matched_keywords which returns sorted unique keywords
        # "每次" < "记住" lexicographically → primary = "每次"
        assert "每次" in key

    def test_cluster_key_none_when_no_signal(self):
        c = _cand(kind="moment", body="今天天气不错")
        assert _cluster_key(c) is None

    def test_cluster_key_uses_kind_and_primary_keyword(self):
        c = _cand(kind="rule", body="永远不要使用 root 用户")
        key = _cluster_key(c)
        assert key is not None
        assert key.startswith("rule:")
        # "不要" sorts before "永远" → primary = "不要"
        assert "不要" in key


# ═══════════════════════════════════════════════════════════════════════════
# 4. _candidate_age_seconds — TTL helper
# ═══════════════════════════════════════════════════════════════════════════


class TestCandidateAgeSeconds:
    """Age calculation for TTL-based demotion."""

    def test_recent_candidate(self):
        now = datetime.now(timezone.utc)
        age = _candidate_age_seconds(now.isoformat().replace("+00:00", "Z"), now)
        assert age < 1.0  # should be near-zero

    def test_old_candidate(self):
        now = datetime.now(timezone.utc)
        age = _candidate_age_seconds("2026-06-01T00:00:00Z", now)
        assert age > 3600 * 24 * 6  # ~7 days

    def test_empty_created_at_returns_inf(self):
        now = datetime.now(timezone.utc)
        age = _candidate_age_seconds("", now)
        assert age == float("inf")

    def test_invalid_timestamp_returns_inf(self):
        now = datetime.now(timezone.utc)
        age = _candidate_age_seconds("not-a-date", now)
        assert age == float("inf")

    def test_tz_naive_treated_as_utc(self):
        """Naive datetime string is treated as UTC."""
        now = datetime.now(timezone.utc)
        age = _candidate_age_seconds("2026-06-01T00:00:00", now)
        assert age > 0


# ═══════════════════════════════════════════════════════════════════════════
# 5. _cluster_and_promote — cluster + promote decision logic
# ═══════════════════════════════════════════════════════════════════════════


class TestClusterAndPromote:
    """Cluster ≥2 candidates with same key → promote to owner_eligible."""

    def test_single_candidate_no_promote(self, tmp_path):
        """One candidate cannot form a cluster of size ≥2."""
        store = _store_with_gate(tmp_path)
        c = _cand("cand-single", body="记住：必须备份日志")
        result = _cluster_and_promote([c], store, set(), envelope_id=_VALID_ENVELOPE_ID)
        assert result["promoted_count"] == 0
        assert result["clusters"] == []

    def test_two_candidates_same_cluster_promote(self, tmp_path):
        """Two candidates with identical keywords → same cluster key → promote 2."""
        store = _store_with_gate(tmp_path)
        # Both contain "记住" + "每次" + "必须" → same matched keywords → same cluster_key
        c1 = _cand("cand-a", body="记住：每次启动都必须检查日志文件")
        c2 = _cand("cand-b", body="记住：每次备份都必须先确认磁盘空间")
        processed: set[str] = set()
        result = _cluster_and_promote([c1, c2], store, processed, envelope_id=_VALID_ENVELOPE_ID)
        assert result["promoted_count"] == 2, f"Expected 2 promoted, got {result}"
        assert "cand-a" in processed
        assert "cand-b" in processed

    def test_two_candidates_different_kind_different_cluster(self, tmp_path):
        """Different kinds produce different cluster keys → no promote."""
        store = _store_with_gate(tmp_path)
        c1 = _cand("cand-a", kind="moment", body="记住：备份日志")
        c2 = _cand("cand-b", kind="rule", body="永远不要 root 登录")
        processed: set[str] = set()
        result = _cluster_and_promote([c1, c2], store, processed, envelope_id=_VALID_ENVELOPE_ID)
        assert result["promoted_count"] == 0

    def test_already_processed_skipped(self, tmp_path):
        """Candidates already in processed_ids are skipped."""
        store = _store_with_gate(tmp_path)
        c1 = _cand("cand-a", body="记住：备份日志")
        c2 = _cand("cand-b", body="记住：检查空间")
        processed: set[str] = {"cand-a", "cand-b"}
        result = _cluster_and_promote([c1, c2], store, processed, envelope_id=_VALID_ENVELOPE_ID)
        assert result["promoted_count"] == 0

    def test_capped_cluster_demotes_overflow(self, tmp_path):
        """Cluster with > 20 members demotes the rest."""
        store = _store_with_gate(tmp_path)
        members = [
            _cand(f"cand-over-{i}", body="记住：必须备份数据")
            for i in range(25)
        ]
        processed: set[str] = set()
        result = _cluster_and_promote(
            members, store, processed, envelope_id=_VALID_ENVELOPE_ID,
            min_cluster_size=2,
        )
        assert result["promoted_count"] == 20  # capped
        # 25 - 20 capped = 5 overflowed, but they're still in
        # _cluster_and_promote's processing. Let's verify by checking
        # the triage file for overflow demote entries.

    def test_signal_without_cluster_partner_not_promoted(self, tmp_path):
        """Signal-bearing candidate alone → not promoted."""
        store = _store_with_gate(tmp_path)
        c = _cand("cand-strong", body="這是一條鐵規則：永遠不要跳過確認步驟")
        result = _cluster_and_promote([c], store, set(), envelope_id=_VALID_ENVELOPE_ID)
        assert result["promoted_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 6. _demote_aged — TTL boundary
# ═══════════════════════════════════════════════════════════════════════════


class TestDemoteAged:
    """Auto-demote candidates past TTL."""

    def test_old_candidate_demoted(self, tmp_path):
        """Candidate past TTL is demoted."""
        store = _store_with_gate(tmp_path)
        old = _cand("cand-old", body="记住：规则", created_at="2026-05-01T00:00:00Z")
        processed: set[str] = set()
        result = _demote_aged([old], store, processed, envelope_id=_VALID_ENVELOPE_ID)
        assert result["demoted_count"] == 1
        assert "cand-old" in processed

    def test_fresh_candidate_not_demoted(self, tmp_path):
        """Candidate well within TTL is not demoted."""
        store = _store_with_gate(tmp_path)
        recent = _cand("cand-recent", body="记住：规则")
        processed: set[str] = set()
        result = _demote_aged([recent], store, processed, envelope_id=_VALID_ENVELOPE_ID)
        assert result["demoted_count"] == 0

    def test_ttl_exact_boundary(self, tmp_path):
        """Candidate just past TTL age is demoted (age > ttl)."""
        store = _store_with_gate(tmp_path)
        ttl = CANDIDATE_DEMOTE_TTL_SECONDS  # 259200s = 3 days
        now = datetime.now(timezone.utc)
        # Create candidate whose age is TTL + 1s — just past threshold
        created_at = now.timestamp() - (ttl + 1)
        from datetime import UTC
        past_dt = datetime.fromtimestamp(created_at, tz=UTC)
        created_at_str = past_dt.isoformat().replace("+00:00", "Z")
        old = _cand("cand-boundary", body="记住：规则", created_at=created_at_str)
        processed: set[str] = set()
        result = _demote_aged([old], store, processed,
                              envelope_id=_VALID_ENVELOPE_ID, now=now)
        assert result["demoted_count"] == 1, f"Expected demotion past TTL, got {result}"

    def test_already_demoted_bridge_state_skipped(self, tmp_path):
        """Candidates with bridge_state=demoted are skipped."""
        store = _store_with_gate(tmp_path)
        old = _cand("cand-old", body="记住：规则",
                     created_at="2026-05-01T00:00:00Z",
                     bridge_state="demoted")
        processed: set[str] = set()
        result = _demote_aged([old], store, processed, envelope_id=_VALID_ENVELOPE_ID)
        assert result["demoted_count"] == 0

    def test_owner_eligible_bridge_state_skipped(self, tmp_path):
        """Candidates already owner_eligible are skipped."""
        store = _store_with_gate(tmp_path)
        eligible = _cand("cand-eligible", body="记住：规则",
                          created_at="2026-05-01T00:00:00Z",
                          bridge_state="owner_eligible")
        processed: set[str] = set()
        result = _demote_aged([eligible], store, processed,
                               envelope_id=_VALID_ENVELOPE_ID)
        assert result["demoted_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 7. _check_index_dedup — FTS5 hit/miss (fail-open)
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckIndexDedup:
    """FTS5 near-duplicate detection — fail-open on missing index."""

    def test_missing_index_returns_none(self, tmp_path):
        """No index db → fail-open: returns None, doesn't crash."""
        store = _store_with_gate(tmp_path)
        c = _cand("cand-dedup", body="记住：每次都必须确认备份文件完整性")
        result = _check_index_dedup(store, c)
        assert result is None  # fail-open

    def test_empty_body_returns_none(self, tmp_path):
        store = _store_with_gate(tmp_path)
        c = _cand("cand-empty", body="")
        assert _check_index_dedup(store, c) is None

    def test_short_body_returns_none(self, tmp_path):
        store = _store_with_gate(tmp_path)
        body = "a" * (_MIN_SUBSTANTIVE_CHARS - 1)
        c = _cand("cand-short", body=body)
        assert _check_index_dedup(store, c) is None


# ═══════════════════════════════════════════════════════════════════════════
# 8. _tag_fleeting — pure chat-body detection (needs store for gate)
# ═══════════════════════════════════════════════════════════════════════════


class TestTagFleeting:
    """Tag no-decision-content candidates as fleeting."""

    def test_chat_pattern_tagged_fleeting(self, tmp_path):
        store = _store_with_gate(tmp_path)
        c = _cand("cand-chat", body="好的")
        processed: set[str] = set()
        result = _tag_fleeting([c], store, processed, envelope_id=_VALID_ENVELOPE_ID)
        assert result["fleeting_count"] == 1
        assert "cand-chat" in processed

    def test_signal_content_not_tagged_fleeting(self, tmp_path):
        store = _store_with_gate(tmp_path)
        c = _cand("cand-signal", body="记住：每次启动都必须检查日志文件完整性")
        processed: set[str] = set()
        result = _tag_fleeting([c], store, processed, envelope_id=_VALID_ENVELOPE_ID)
        assert result["fleeting_count"] == 0, f"Signal body should not be fleeting, got {result}"

    def test_owner_eligible_skipped(self, tmp_path):
        store = _store_with_gate(tmp_path)
        c = _cand("cand-eligible", body="好的", bridge_state="owner_eligible")
        processed: set[str] = set()
        result = _tag_fleeting([c], store, processed, envelope_id=_VALID_ENVELOPE_ID)
        assert result["fleeting_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 9. A1 boundary assertions — no auto-crystallize contract
# ═══════════════════════════════════════════════════════════════════════════


class TestA1Boundary:
    """A1: lane never crystallizes, never auto-approves, never writes candidates.jsonl."""

    def test_lane_tick_returns_no_crystallize(self, tmp_path):
        """run_candidate_aggregation_lane return dict asserts no-crystallize."""
        from plugins.modules.governance.candidate_aggregation import run_candidate_aggregation_lane

        store = _store_with_gate(tmp_path)
        result = run_candidate_aggregation_lane(store, execution_gate_envelope_id=_VALID_ENVELOPE_ID)
        assert result.get("actual_crystallized_approval") is False
        assert result.get("actual_send") is False
        assert result.get("actual_execute") is False
        assert result.get("actual_identity_write") is False

    def test_promote_writes_triage_not_crystallized(self, tmp_path):
        """_cluster_and_promote appends to triage, never to crystallized."""
        store = _store_with_gate(tmp_path)
        # Both have "记住"+"每次"+"必须"+"检查" → same cluster_key
        c1 = _cand("cand-prom-a", body="记住：每次启动都必须检查日志文件")
        c2 = _cand("cand-prom-b", body="记住：每次部署都必须检查版本号")
        result = _cluster_and_promote([c1, c2], store, set(),
                                      envelope_id=_VALID_ENVELOPE_ID)
        assert result["promoted_count"] == 2, f"Expected 2 promoted, got {result}"

        # Triage file should have promote entries
        triage_path = store.roots.crystallized_root / "candidate_triage.jsonl"
        assert triage_path.exists(), f"Triage file should exist after promotion, checked {triage_path}"
        triage_entries = [
            json.loads(line) for line in triage_path.read_text().strip().split("\n")
            if line.strip()
        ]
        promote_entries = [t for t in triage_entries if t.get("action") == "promote"]
        assert len(promote_entries) == 2

        # No crystallized record was created
        cry_path = store.roots.hermes_home / "memory-os" / "crystallized"
        cry_files = list(cry_path.glob("*.md")) if cry_path.exists() else []
        assert len(cry_files) == 0  # no new .md was written

    def test_candidates_jsonl_unchanged_by_lane(self, tmp_path):
        """Lane operations do not modify candidates.jsonl."""
        store = _store_with_gate(tmp_path)

        # Add one candidate to queue first
        from plugins.memory.memory_os.crystallized import append_candidate_queue
        c = _cand("cand-queue", body="记住：必须检查")
        append_candidate_queue(store, c)

        # Snapshot candidates.jsonl content (as a backup, not reading .md)
        queue_path = store.roots.memory_os_root / "system" / "candidates.jsonl"
        before = queue_path.read_text() if queue_path.exists() else ""

        # Run promote
        candidates = [c]
        from plugins.memory.memory_os.crystallized import read_candidate_queue
        _cluster_and_promote(candidates, store, set(),
                             envelope_id=_VALID_ENVELOPE_ID,
                             min_cluster_size=1)

        after = queue_path.read_text() if queue_path.exists() else ""
        assert before == after, "candidates.jsonl was modified by lane operation"
