"""降级准入 (owner ruling 2026-08-14): candidates reach recall at candidate
authority without approval; only permanent crystallization stays owner-gated,
and the owner's reject is the correction half of that bargain.

Each test here is the counterfactual for one measured production defect:

* 258-row candidate queue, 136 of them already terminal, yet the recall path
  read raw queue rows with no state filter — a rejected candidate kept
  surfacing.
* The same path scored only `[:5]`, the five OLDEST rows, so a relevant
  candidate that arrived later was unreachable (head-of-queue starvation,
  the pattern already documented for session_mirror).
* "cloudflare 密钥" against a body saying "凭证" shares one token, the
  relevance floor needs two, and the fact was dropped although it sat in the
  pool.
* Credential/deployment summaries are stored clipped and summary-only, with
  a `safe_ref.session_id` pointer the recall path never surfaced.
"""

from __future__ import annotations

from datetime import datetime, timezone

from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    TERMINAL_CANDIDATE_STATES,
    append_candidate_queue,
    read_candidate_recall_exclusions,
    write_candidate_recall_exclusions,
)
from plugins.memory.memory_os.prefetch import (
    _candidate_lines,
    _expand_query_tokens,
    _extract_query_tokens,
    _live_state_marker,
    _record_body_score,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path) -> MemoryOSStore:
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    return store


def _candidate(store: MemoryOSStore, candidate_id: str, body: str) -> CrystallizedCandidate:
    candidate = CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="moment",
        body=body,
        sensitivity="private",
        tags=[],
        source_event_ids=[],
        created_at=datetime.now(timezone.utc).isoformat(),
        bridge_state="",
    )
    append_candidate_queue(store, candidate)
    return candidate


class _Event:
    def __init__(self, summary: str, safe_ref: dict | None = None, kind: str = "conversation_turn"):
        self.summary = summary
        self.safe_ref = safe_ref or {}
        self.kind = kind
        self.id = "evt_test"
        self.ts = "2026-08-14T00:00:00Z"


def test_excluded_candidate_never_surfaces_in_recall(tmp_path):
    """The correction loop: an owner reject / lane demote must actually stop
    the candidate from being recalled. Without the exclusion projection the
    recall path read raw queue rows and this candidate would surface."""
    store = _store(tmp_path)
    _candidate(store, "cand_kept", "Cloudflare 凭证 与 部署 记录 A")
    _candidate(store, "cand_rejected", "Cloudflare 凭证 与 部署 记录 B")

    query = "cloudflare 密钥"
    before = _candidate_lines(store, query=query, seen=set(), source_ids=[])
    assert any("cand_rejected" in line for line in before), before

    write_candidate_recall_exclusions(store, {"cand_rejected"})
    after = _candidate_lines(store, query=query, seen=set(), source_ids=[])

    assert any("cand_kept" in line for line in after)
    assert not any("cand_rejected" in line for line in after)


def test_missing_exclusion_projection_is_fail_open(tmp_path):
    """A missing snapshot must degrade to the previous behavior (surface
    candidates), never to silence — memory loss is the worse failure."""
    store = _store(tmp_path)
    _candidate(store, "cand_open", "Cloudflare 凭证 与 部署 记录")

    assert read_candidate_recall_exclusions(store.roots) == set()
    lines = _candidate_lines(store, query="cloudflare 密钥", seen=set(), source_ids=[])
    assert any("cand_open" in line for line in lines)


def test_relevance_ranking_replaces_head_of_queue_selection(tmp_path):
    """A relevant candidate that arrived after five irrelevant ones must be
    reachable. Under the old `[:5]` slice only the oldest five were scored,
    so this returns nothing."""
    store = _store(tmp_path)
    for index in range(6):
        _candidate(store, f"cand_noise_{index}", f"无关的日常记录 {index}")
    _candidate(store, "cand_late_relevant", "Cloudflare 凭证 用于 部署 outline server")

    lines = _candidate_lines(store, query="cloudflare 密钥", seen=set(), source_ids=[])

    assert any("cand_late_relevant" in line for line in lines), lines


def test_synonym_expansion_reaches_the_relevance_floor_without_lowering_it():
    """The exact production miss: query says 密钥, body says 凭证."""
    tokens = _extract_query_tokens("cloudflare 密钥")
    body = "Owner 提供了 Cloudflare 凭证用于 outline-server 部署"

    assert _record_body_score(body, tokens) == 1  # below the >=2 floor
    assert _record_body_score(body, _expand_query_tokens(tokens)) >= 2

    # The floor itself must stay at 2 — >=1 was empirically noise. An
    # unrelated body must not be dragged over the line by expansion.
    unrelated = _expand_query_tokens(_extract_query_tokens("我们什么时候开会？"))
    assert _record_body_score("一份关于功能混淆的报告", unrelated) < 2


def test_synonym_expansion_is_additive_and_keeps_user_words_first():
    tokens = _extract_query_tokens("部署 状态")
    expanded = _expand_query_tokens(tokens)

    assert expanded[: len(tokens)] == tokens
    assert set(tokens) <= set(expanded)
    # A query touching no synonym group is returned unchanged.
    plain = _extract_query_tokens("今天天气怎么样")
    assert _expand_query_tokens(plain) == plain


def test_live_state_marker_points_at_the_session_for_drift_prone_facts():
    """Owner instruction 以现状为准: credential/deployment recall must carry
    its pointer and a verify instruction, because the event layer stores a
    clipped summary_only body — the detail was never captured."""
    marker = _live_state_marker(
        _Event("Owner 交代了 Cloudflare 密钥用于部署", {"session_id": "20260809_182035_9d2e4307"})
    )

    assert "以现状为准" in marker
    assert "20260809_182035_9d2e4307" in marker


def test_live_state_marker_is_silent_for_ordinary_facts():
    assert _live_state_marker(_Event("聊了聊今天的天气", {"session_id": "s1"})) == ""


def test_live_state_marker_survives_a_missing_safe_ref():
    marker = _live_state_marker(_Event("部署完成", {}))
    assert "以现状为准" in marker
    assert "原始会话" not in marker


def test_terminal_vocabulary_has_one_public_source():
    """Three copies of one vocabulary is the drift this project keeps paying
    for; the recall path and the projection must read the same names."""
    from plugins.memory.memory_os import crystallized

    assert crystallized._TERMINAL_CANDIDATE_STATES is TERMINAL_CANDIDATE_STATES
    for state in ("owner_rejected", "discarded", "demoted", "crystallized"):
        assert state in TERMINAL_CANDIDATE_STATES


# ── owner reject must actually bite (correction half of 降级准入) ────────────
#
# Admitting candidates to recall without approval is only defensible because
# the owner keeps a reject. These are the counterfactuals for the two ways
# that reject silently did nothing:
#
#   * add_candidate_recall_exclusion existed, was docstring-labelled "immediate
#     (owner reject path)", and had ZERO call sites — a single reject only took
#     effect when candidate_aggregation next republished the projection, i.e.
#     up to 6h later (due_interval_minutes=360).
#   * reject_candidate_cluster — the verb an owner facing a large queue
#     actually reaches for — never reached the exclusion set AT ALL: it writes
#     one action whose target_type is "candidate_cluster" (not "candidate")
#     and whose member ids live in result_ref, so both the immediate path and
#     the authority path in read_effective_candidates structurally missed it.


def _owner_eligible_candidate(store: MemoryOSStore, candidate_id: str, body: str, event_id: str):
    candidate = CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="preference",
        body=body,
        source_event_ids=[event_id],
        sensitivity="private",
        tags=["test"],
        bridge_state="owner_eligible",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    append_candidate_queue(store, candidate)
    return candidate


def _recall_text(store: MemoryOSStore, query: str) -> str:
    return "\n".join(_candidate_lines(store, query=query, seen=set(), source_ids=[]))


def _cluster_review_item(store: MemoryOSStore) -> dict:
    from plugins.memory.memory_os.owner_actions import owner_review_queue_report

    for entry in owner_review_queue_report(store, limit=20).get("items") or []:
        if entry.get("target_type") == "candidate_cluster":
            return entry
    raise AssertionError("no candidate_cluster review item was produced")


def _republish_projection_like_the_lane(store: MemoryOSStore) -> set[str]:
    """Recompute the exclusion set exactly as candidate_aggregation does.

    The lane publishes the FULL set every run, so anything the immediate path
    writes but the authority cannot re-derive is erased within one cycle. That
    is why the authority hop is mandatory, not a nicety.
    """
    from plugins.memory.memory_os.crystallized import read_effective_candidates

    effective = read_effective_candidates(store)
    excluded = {item.candidate.candidate_id for item in effective if item.terminal}
    write_candidate_recall_exclusions(store, excluded)
    return excluded


def test_owner_reject_stops_recall_immediately_without_waiting_for_the_lane(tmp_path):
    from plugins.memory.memory_os.owner_actions import apply_owner_action

    store = _store(tmp_path)
    _owner_eligible_candidate(
        store, "cand-reject-now", "Owner 交代了 Cloudflare 部署密钥的存放位置", "evt-r1"
    )
    query = "cloudflare 密钥 部署"
    assert "cand-reject-now" in _recall_text(store, query)

    result = apply_owner_action(
        store,
        action_type="reject_candidate",
        target="candidate:cand-reject-now",
        owner_id="owner-test",
        channel="test",
        apply=True,
    )

    assert result["status"] == "ok"
    # No lane run in between — that is the whole point of the immediate path.
    assert "cand-reject-now" in read_candidate_recall_exclusions(store.roots)
    assert "cand-reject-now" not in _recall_text(store, query)


def test_dry_run_reject_previews_without_touching_recall(tmp_path):
    """A preview must stay a preview: apply=False may not exclude anything."""
    from plugins.memory.memory_os.owner_actions import apply_owner_action

    store = _store(tmp_path)
    _owner_eligible_candidate(
        store, "cand-preview", "Owner 交代了 Cloudflare 部署密钥的存放位置", "evt-p1"
    )
    query = "cloudflare 密钥 部署"

    apply_owner_action(
        store,
        action_type="reject_candidate",
        target="candidate:cand-preview",
        owner_id="owner-test",
        channel="test",
        apply=False,
    )

    assert "cand-preview" not in read_candidate_recall_exclusions(store.roots)
    assert "cand-preview" in _recall_text(store, query)


def test_cluster_reject_stops_recall_for_every_member_immediately(tmp_path):
    from plugins.memory.memory_os.owner_actions import apply_owner_action

    store = _store(tmp_path)
    body = "Owner 交代了 Cloudflare 部署密钥的存放位置与注入方式"
    _owner_eligible_candidate(store, "cand-clu-a", body, "evt-c1")
    _owner_eligible_candidate(store, "cand-clu-b", body + "，另外补充了一句", "evt-c2")
    query = "cloudflare 密钥 部署"
    surfaced = _recall_text(store, query)
    assert "cand-clu-a" in surfaced and "cand-clu-b" in surfaced

    item = _cluster_review_item(store)
    assert {"cand-clu-a", "cand-clu-b"} <= set(item["cluster_scope"]["member_candidate_ids"])

    result = apply_owner_action(
        store,
        action_type="reject_candidate_cluster",
        target=f"candidate_cluster:{item['target_id']}",
        owner_id="owner-test",
        channel="test",
        apply=True,
    )

    assert result["status"] == "ok"
    assert {"cand-clu-a", "cand-clu-b"} <= read_candidate_recall_exclusions(store.roots)
    after = _recall_text(store, query)
    assert "cand-clu-a" not in after and "cand-clu-b" not in after


def test_cluster_reject_survives_the_lane_full_republish(tmp_path):
    """The authority hop, isolated.

    Without read_effective_candidates learning to read cluster member ids out
    of result_ref, the lane's next full republish drops both members back into
    recall — an owner decision quietly expiring after <=6h, which is worse
    than a reject that never appeared to work at all.
    """
    from plugins.memory.memory_os.crystallized import read_effective_candidates
    from plugins.memory.memory_os.owner_actions import apply_owner_action

    store = _store(tmp_path)
    body = "Owner 交代了 GitHub 部署密钥由主机统一注入，不要写进仓库配置"
    _owner_eligible_candidate(store, "cand-sur-a", body, "evt-s1")
    _owner_eligible_candidate(store, "cand-sur-b", body + "，并说明了轮换周期", "evt-s2")
    item = _cluster_review_item(store)
    apply_owner_action(
        store,
        action_type="reject_candidate_cluster",
        target=f"candidate_cluster:{item['target_id']}",
        owner_id="owner-test",
        channel="test",
        apply=True,
    )

    terminal_ids = {
        entry.candidate.candidate_id
        for entry in read_effective_candidates(store)
        if entry.terminal
    }
    assert {"cand-sur-a", "cand-sur-b"} <= terminal_ids

    republished = _republish_projection_like_the_lane(store)
    assert {"cand-sur-a", "cand-sur-b"} <= republished
    after = _recall_text(store, "github 密钥 部署")
    assert "cand-sur-a" not in after and "cand-sur-b" not in after
