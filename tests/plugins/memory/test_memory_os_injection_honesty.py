"""Injection honesty (2026-08-14 production audit, both 3.200 profiles).

The audit found the agent was being handed "fragments that look complete":

* recall lines cut at the load-bearing point — mid-URL
  (``https://github.c...``), mid-path (``scripts/.en...``) — with a bare
  ``...`` that cannot be told apart from a fact that simply ends there;
* the crystallized floor section burning 40% (main) / 51% (sannai) of the
  whole injection on records with zero query relevance, twenty at a time;
* the same provisional fact injected NINE times in one prefetch.

Each test here is the counterfactual for one of those measured defects.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
    append_candidate_queue,
)
# _clip_annotated is imported inside its own tests so that reverting the fix
# makes the floor/dedup tests fail on BEHAVIOR, not on collection.
from plugins.memory.memory_os.prefetch import (
    _candidate_lines,
    _crystallized_lines,
    _event_lines,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


def _store(tmp_path) -> MemoryOSStore:
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    return store


class _ZeroHitIndex:
    def search(self, _query, *, limit):
        return {"hits": []}


def _write_record(store, service, candidate_id: str, body: str, file_name: str) -> None:
    candidate = CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="moment",
        body=body,
        source_event_ids=[f"evt_{candidate_id}"],
    )
    decision = ApprovalDecision(
        candidate_id=candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-25T12:00:00Z",
        provisional=False,
    )
    service.write_approved_record(candidate, decision, file_name=file_name)


# ── floor mode: score-0 filler exclusion + cap ──────────────────────────────


def test_floor_mode_excludes_zero_score_filler(tmp_path):
    """Floor is a query-aware fallback, not a universal recall.

    Production: twenty philosophy-chat records with no relation to the query
    filled this section. Score-0 records are pure filler and must not ride
    the floor into the injection.
    """
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    _write_record(store, service, "rel_001", "关于时间管理的记录，明确包含时间这个主题。", "rel_001.md")
    for i in range(3):
        _write_record(
            store, service, f"junk_{i:03d}",
            f"哲学聊天记录 {i}：讨论了幻觉、想象与梦境的意向对象问题。",
            f"junk_{i:03d}.md",
        )

    lines, degradation, _ids = _crystallized_lines(
        store, query="时间", index=_ZeroHitIndex(), error_records=[],
    )

    assert degradation == 2
    assert any("时间" in ln for ln in lines)
    assert not any("哲学聊天" in ln for ln in lines), (
        "score-0 filler rode the floor into the injection:\n" + "\n".join(lines)
    )


def test_floor_mode_caps_at_five_records(tmp_path):
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    for i in range(8):
        _write_record(
            store, service, f"rel_{i:03d}",
            f"关于时间管理的记录 {i}：这条记录明确讨论时间安排。",
            f"rel_{i:03d}.md",
        )

    lines, degradation, _ids = _crystallized_lines(
        store, query="时间", index=_ZeroHitIndex(), error_records=[],
    )

    assert degradation == 2
    assert len(lines) == 5, f"floor cap: expected 5, got {len(lines)}"


def test_floor_mode_may_be_empty_rather_than_filled(tmp_path):
    """An empty section beats 4000 chars of zero-relevance records."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    for i in range(3):
        _write_record(
            store, service, f"junk_{i:03d}",
            f"哲学聊天记录 {i}：讨论了幻觉、想象与梦境。",
            f"junk_{i:03d}.md",
        )

    lines, degradation, _ids = _crystallized_lines(
        store, query="时间", index=_ZeroHitIndex(), error_records=[],
    )

    assert degradation == 2
    assert lines == []


def test_fts_hit_mode_keeps_the_wide_caps(tmp_path):
    """The 20/15/5 caps still govern the relevance-gated (non-floor) path —
    the floor cap must not leak into normal FTS-hit recall."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    rids: list[str] = []
    for i in range(8):
        _write_record(
            store, service, f"hit_{i:03d}",
            f"记录 {i}：与查询相关的内容。",
            f"hit_{i:03d}.md",
        )
    # Collect the real record ids the service assigned.
    for path in store.roots.crystallized_root.glob("hit_*.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("id: "):
                rids.append(line.split("id: ", 1)[1].strip())

    class AllHitIndex:
        def search(self, _query, *, limit):
            return {
                "hits": [
                    {"record_type": "crystallized_record", "record_id": rid}
                    for rid in rids
                ]
            }

    lines, degradation, _ids = _crystallized_lines(
        store, query="记录", index=AllHitIndex(), error_records=[],
    )

    assert degradation == 0
    assert len(lines) == 8  # all relevance-gated hits survive (under the 15 cap)


# ── injection-time dedup ────────────────────────────────────────────────────


def test_duplicate_bodies_inject_once(tmp_path):
    """Production: one proposal-approval fact injected nine times."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    body = "用户已批准 proposal「Review reflection continuity behavior」，其状态为 approved_for_proposal。时间线记录。"
    for i in range(4):
        _write_record(store, service, f"dup_{i:03d}", body, f"dup_{i:03d}.md")

    lines, _degradation, _ids = _crystallized_lines(
        store, query="时间", index=_ZeroHitIndex(), error_records=[],
    )

    matching = [ln for ln in lines if "Review reflection" in ln]
    assert len(matching) == 1, (
        f"duplicate body injected {len(matching)} times:\n" + "\n".join(lines)
    )


# ── honest truncation ───────────────────────────────────────────────────────


def test_clip_annotated_marks_the_cut_with_both_lengths():
    from plugins.memory.memory_os.prefetch import _clip_annotated

    long = "A" * 500
    out = _clip_annotated(long, 320)
    assert "…[片段" in out and "/500字]" in out


def test_clip_annotated_leaves_short_text_untouched():
    from plugins.memory.memory_os.prefetch import _clip_annotated

    assert _clip_annotated("short fact", 320) == "short fact"


def test_truncated_candidate_line_says_so(tmp_path):
    store = _store(tmp_path)
    body = "Owner 交代了 GitHub 部署密钥的存放位置：" + "细节" * 200
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand-long",
            kind="preference",
            body=body,
            source_event_ids=["evt-l1"],
            bridge_state="owner_eligible",
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
    )

    lines = _candidate_lines(store, query="github 密钥 部署", seen=set(), source_ids=[])

    assert lines, "candidate should surface"
    assert "…[片段" in lines[0], f"no truncation annotation: {lines[0][-120:]}"
    # The live-state marker still renders after the annotation.
    assert "以现状为准" in lines[0]


def test_event_summary_is_injected_whole(tmp_path):
    """sync_turn stores at most ~296 chars; the old second clip at 220 was
    pure loss. At 320 the stored summary must appear complete."""
    from plugins.memory.memory_os.fixtures import build_event
    from plugins.memory.memory_os.store import EventEnvelope

    store = _store(tmp_path)
    summary = "User: " + "问" * 140 + " | Assistant: " + "答" * 140
    event = EventEnvelope.from_dict(
        {**build_event(seed=901, profile="memoryos-test"), "summary": summary}
    )
    store.append_event(event)

    lines = _event_lines(store, session_id="", seen=set(), source_ids=[])

    joined = "\n".join(lines)
    assert summary in joined, "stored summary was re-clipped at injection"
