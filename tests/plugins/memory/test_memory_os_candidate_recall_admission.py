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
