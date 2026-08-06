"""W3 (E1) — candidate→owner_eligible 晋升通道、TTL、digest 渲染与词表守卫。

E1 断链:proposer 全写 candidate,digest 只渲染 owner_eligible,而全代码库
没有任何路径做 candidate→owner_eligible 迁移 — owner 从未见过边审批项。
本文件的测试钉死修复后的完整闭环:
    proposer(candidate) → promotion(owner_eligible) → digest(approve token)
    → owner action(active/invalidated) → prefetch injection(active)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from plugins.memory.memory_os.index import MemoryOSIndex, EDGE_STATE_TRANSITIONS
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="edge-promotion-test")
    store = MemoryOSStore(roots)
    store.initialize()
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)
    return store, index


def _seed_candidates(index, count, *, weight_base=0.0):
    """Seed candidate edges via the real producer path (write_governed_edge)."""
    edges = []
    for i in range(count):
        edge = index.write_governed_edge(
            from_record_type="crystallized_record",
            from_record_id=f"cry_prom_{i}_a",
            to_record_type="crystallized_record",
            to_record_id=f"cry_prom_{i}_b",
            relation_type="refines",
            weight=round(weight_base + (i + 1) * 0.05, 4),
            proposed_by="llm",
        )
        assert edge and edge.get("edge_id"), f"seed {i} failed: {edge}"
        edges.append(edge)
    return edges


def _states(index):
    conn = sqlite3.connect(str(index.roots.index_path))
    rows = conn.execute("select edge_id, state from memory_edges").fetchall()
    conn.close()
    return {str(r[0]): str(r[1]) for r in rows}


# ── 晋升 ───────────────────────────────────────────────────────────────────


def test_w3_promotion_moves_top_candidates_by_weight(tmp_path):
    """E1 counterfactual:candidate 边必须能通过生产代码到达 owner_eligible。

    无晋升通道时不存在任何 candidate→owner_eligible 路径 → 必红。
    """
    from plugins.memory.memory_os.edge_promotion import (
        PROMOTE_PER_RUN,
        run_edge_promotion,
    )

    store, index = _store(tmp_path)
    edges = _seed_candidates(index, PROMOTE_PER_RUN + 2)

    result = run_edge_promotion(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["promoted_count"] == PROMOTE_PER_RUN

    states = _states(index)
    by_weight = sorted(edges, key=lambda e: -float(e["weight"]))
    for e in by_weight[:PROMOTE_PER_RUN]:
        assert states[e["edge_id"]] == "owner_eligible", (
            f"top-weight candidate {e['edge_id']} must be promoted"
        )
    for e in by_weight[PROMOTE_PER_RUN:]:
        assert states[e["edge_id"]] == "candidate"

    # 持久性(依赖 W0):重投影后晋升保持
    index.sync_from_store(store)
    states_after = _states(index)
    assert states_after[by_weight[0]["edge_id"]] == "owner_eligible"


def test_w3_promotion_reports_no_candidates(tmp_path):
    """Completion≠Output:无合格输入时必须落明确原因码,不得静默。"""
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion

    store, index = _store(tmp_path)
    result = run_edge_promotion(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["promoted_count"] == 0
    assert result["outcome"] == "no_candidates"


def test_w3_ttl_invalidates_stale_candidates(tmp_path):
    """E1/TTL counterfactual:超龄 candidate 必须被自动 invalidated(有界)。"""
    from plugins.memory.memory_os.edge_promotion import (
        CANDIDATE_TTL_DAYS,
        PROMOTE_PER_RUN,
        run_edge_promotion,
    )

    store, index = _store(tmp_path)
    _seed_candidates(index, PROMOTE_PER_RUN + 2)

    future = datetime.now(timezone.utc) + timedelta(days=CANDIDATE_TTL_DAYS + 1)
    result = run_edge_promotion(str(index.roots.index_path), index=index, now=future)
    assert result["status"] == "ok"
    assert result["promoted_count"] == PROMOTE_PER_RUN
    assert result["ttl_invalidated_count"] == 2

    states = _states(index)
    counts = {}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    assert counts.get("owner_eligible", 0) == PROMOTE_PER_RUN
    assert counts.get("invalidated", 0) == 2
    assert counts.get("candidate", 0) == 0


def test_w3_ttl_spares_fresh_candidates(tmp_path):
    """新鲜 candidate 不受 TTL 影响。"""
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion

    store, index = _store(tmp_path)
    _seed_candidates(index, 3)
    result = run_edge_promotion(str(index.roots.index_path), index=index)
    assert result["ttl_invalidated_count"] == 0


# ── Digest 渲染(E1 闭环的 owner 可见面)──────────────────────────────────


def test_w3_digest_renders_promoted_edges_with_tokens(tmp_path):
    """E1 counterfactual 终点:晋升后的边必须出现在 digest 并带审批 token。

    修复前 digest 查 owner_eligible 而全库无此状态 → 区段永远为空。
    """
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion
    from plugins.memory.memory_os.owner_actions import _rendered_digest_text

    store, index = _store(tmp_path)
    edges = _seed_candidates(index, 3)
    run_edge_promotion(str(index.roots.index_path), index=index)

    text = _rendered_digest_text(
        {"action_required": [], "review_suggested": [], "fyi": []},
        counts={}, store=store,
    )
    assert "Pending Edge Review" in text
    for e in edges:
        assert f"approve_edge:{e['edge_id']}" in text
        assert f"reject_edge:{e['edge_id']}" in text


def test_w3_digest_caps_at_top_k_with_pending_count(tmp_path):
    """digest 只放 top-K(按 weight),其余以计数行披露——不淹没 owner。"""
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion
    from plugins.memory.memory_os.owner_actions import (
        EDGE_REVIEW_DIGEST_TOP_K,
        _rendered_digest_text,
    )

    store, index = _store(tmp_path)
    _seed_candidates(index, EDGE_REVIEW_DIGEST_TOP_K + 5)
    # 两轮晋升,确保 owner_eligible 数量超过 top-K
    run_edge_promotion(str(index.roots.index_path), index=index)
    run_edge_promotion(str(index.roots.index_path), index=index)

    conn = sqlite3.connect(str(index.roots.index_path))
    eligible = conn.execute(
        "select count(*) from memory_edges where state='owner_eligible'"
    ).fetchone()[0]
    conn.close()
    assert eligible > EDGE_REVIEW_DIGEST_TOP_K

    text = _rendered_digest_text(
        {"action_required": [], "review_suggested": [], "fyi": []},
        counts={}, store=store,
    )
    # 按行首缩进 token 计数,排除批量语法提示行
    shown = text.count("  approve_edge:")
    assert shown == EDGE_REVIEW_DIGEST_TOP_K
    assert f"还有 {eligible - EDGE_REVIEW_DIGEST_TOP_K} 条边待审" in text


# ── 批量审批 ───────────────────────────────────────────────────────────────


def test_w3_batch_approve_edges_comma_separated(tmp_path):
    """按簇批量:approve_edge 的 target 接受逗号分隔的多个 edge_id。"""
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion
    from plugins.memory.memory_os.owner_actions import _apply_state_transition

    store, index = _store(tmp_path)
    edges = _seed_candidates(index, 2)
    run_edge_promotion(str(index.roots.index_path), index=index)

    ids = ",".join(e["edge_id"] for e in edges)
    record = {
        "action_type": "approve_edge",
        "target_id": ids,
        "target_type": "edge",
        "owner_id": "owner-test",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "owner_effect": {},
    }
    result = _apply_state_transition(store, record, note="", rating="")
    assert result.get("approved_count") == 2, f"batch approve failed: {result}"

    states = _states(index)
    for e in edges:
        assert states[e["edge_id"]] == "active"


def test_w3_batch_reject_edges_comma_separated(tmp_path):
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion
    from plugins.memory.memory_os.owner_actions import _apply_state_transition

    store, index = _store(tmp_path)
    edges = _seed_candidates(index, 2)
    run_edge_promotion(str(index.roots.index_path), index=index)

    ids = ",".join(e["edge_id"] for e in edges)
    record = {
        "action_type": "reject_edge",
        "target_id": ids,
        "target_type": "edge",
        "owner_id": "owner-test",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "owner_effect": {},
    }
    result = _apply_state_transition(store, record, note="", rating="")
    assert result.get("rejected_count") == 2, f"batch reject failed: {result}"

    states = _states(index)
    for e in edges:
        assert states[e["edge_id"]] == "invalidated"


def test_w3_single_edge_action_shape_unchanged(tmp_path):
    """单个 edge_id 的返回形状保持旧契约(edge_id/new_state)。"""
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion
    from plugins.memory.memory_os.owner_actions import _apply_state_transition

    store, index = _store(tmp_path)
    edges = _seed_candidates(index, 1)
    run_edge_promotion(str(index.roots.index_path), index=index)

    record = {
        "action_type": "approve_edge",
        "target_id": edges[0]["edge_id"],
        "target_type": "edge",
        "owner_id": "owner-test",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "owner_effect": {},
    }
    result = _apply_state_transition(store, record, note="", rating="")
    assert result.get("edge_id") == edges[0]["edge_id"]
    assert result.get("new_state") == "active"


def test_w3_validate_batch_target_all_must_exist(tmp_path):
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion
    from plugins.memory.memory_os.owner_actions import _validate_action_target

    store, index = _store(tmp_path)
    edges = _seed_candidates(index, 1)
    run_edge_promotion(str(index.roots.index_path), index=index)

    ok = _validate_action_target(
        store, "approve_edge", "edge", edges[0]["edge_id"], rating="",
    )
    assert ok == ""

    bad = _validate_action_target(
        store, "approve_edge", "edge",
        f"{edges[0]['edge_id']},edge_missing_999", rating="",
    )
    assert bad == "edge_not_found"


# ── 词表双向守卫(E1 复发防线)────────────────────────────────────────────


def test_w3_edge_state_vocabulary_bidirectional_guard():
    """双向断言:生产者写出的每个状态都有消费出口;消费者查询的每个状态都有生产者。

    E1 的根因是 digest 消费 owner_eligible 而无人生产它 — fixture 直接调
    transition 走通了状态机,掩盖了断链。本守卫把跨模块常量绑死:
      - proposer/write 默认态 candidate → 晋升通道消费(PROMOTION_SOURCE_STATE)
      - 晋升产出 owner_eligible → digest 消费(EDGE_REVIEW_DIGEST_STATE)
      - approve 产出 active → prefetch 注入消费(GRAPH_INJECTION_EDGE_STATE)
      - invalidated 为唯一终态
    """
    from plugins.memory.memory_os.edge_promotion import (
        PROMOTION_SOURCE_STATE,
        PROMOTION_TARGET_STATE,
    )
    from plugins.memory.memory_os.owner_actions import EDGE_REVIEW_DIGEST_STATE
    from plugins.memory.memory_os.prefetch import GRAPH_INJECTION_EDGE_STATE

    # 状态机全集与四个角色一一对应,无孤儿、无幽灵
    assert set(EDGE_STATE_TRANSITIONS) == {
        "candidate", "owner_eligible", "active", "invalidated",
    }
    # 生产方向:每个非终态被某个消费者的查询常量覆盖
    assert PROMOTION_SOURCE_STATE == "candidate"
    assert EDGE_REVIEW_DIGEST_STATE == PROMOTION_TARGET_STATE == "owner_eligible"
    assert GRAPH_INJECTION_EDGE_STATE == "active"
    # 消费方向:每个消费者查询的状态在状态机中可达
    assert PROMOTION_TARGET_STATE in EDGE_STATE_TRANSITIONS[PROMOTION_SOURCE_STATE]
    assert "active" in EDGE_STATE_TRANSITIONS[EDGE_REVIEW_DIGEST_STATE]
    # 终态封闭
    assert EDGE_STATE_TRANSITIONS["invalidated"] == set()
