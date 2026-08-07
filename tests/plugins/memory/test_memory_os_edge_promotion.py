"""R2 (owner 决策 2026-08-06) — 晋升通道改造为自动激活 + TTL 遗忘。

W3 原设计:candidate → owner_eligible → digest 审批 → active。
Owner 裁定:「动态图谱应该是动态去更新关系的…不需要人工介入」——
边是派生投影,审批模型废除:
  - 新产出直接 active(见 test_memory_os_graph_layer 的 R1 测试);
  - 存量 candidate 由本通道按权重分批自动激活(平滑消化,不一次性
    放闸污染注入池),30 天 TTL 清尾;
  - 遗留 owner_eligible 一并激活;
  - digest 不再渲染任何边审批区段;reject_edge 保留为 owner 纠错工具。
"""
from __future__ import annotations

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


def _seed_candidates(index, count, *, weight_base=0.0, state="candidate"):
    """Seed edges via the real producer path (write_governed_edge)."""
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
            state=state,
        )
        assert edge and edge.get("edge_id"), f"seed {i} failed: {edge}"
        edges.append(edge)
    return edges


def _states(index):
    conn = sqlite3.connect(str(index.roots.index_path))
    rows = conn.execute("select edge_id, state from memory_edges").fetchall()
    conn.close()
    return {str(r[0]): str(r[1]) for r in rows}


# ── 自动激活 ───────────────────────────────────────────────────────────────


def test_r2_promotion_activates_top_candidates_by_weight(tmp_path):
    """R2 counterfactual:存量 candidate 必须被自动激活为 active(无人审批)。

    W3 旧契约把 top-K 送 owner_eligible 等审批 → 本测试在旧实现下必红。
    """
    from plugins.memory.memory_os.edge_promotion import (
        PROMOTE_PER_RUN,
        PROMOTION_TARGET_STATE,
        run_edge_promotion,
    )

    assert PROMOTION_TARGET_STATE == "active", (
        "R2: the promotion channel is an AUTO-ACTIVATION channel now"
    )

    store, index = _store(tmp_path)
    edges = _seed_candidates(index, PROMOTE_PER_RUN + 2)

    result = run_edge_promotion(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["promoted_count"] == PROMOTE_PER_RUN

    states = _states(index)
    by_weight = sorted(edges, key=lambda e: -float(e["weight"]))
    for e in by_weight[:PROMOTE_PER_RUN]:
        assert states[e["edge_id"]] == "active", (
            f"top-weight candidate {e['edge_id']} must be auto-activated"
        )
    for e in by_weight[PROMOTE_PER_RUN:]:
        assert states[e["edge_id"]] == "candidate"

    # 持久性(W0):重投影后保持
    index.sync_from_store(store)
    assert _states(index)[by_weight[0]["edge_id"]] == "active"


def test_r2_legacy_owner_eligible_also_activated(tmp_path):
    """遗留 owner_eligible(旧审批通道产物)一并自动激活 — 不留孤儿状态。"""
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion

    store, index = _store(tmp_path)
    edges = _seed_candidates(index, 3, state="owner_eligible")

    result = run_edge_promotion(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["promoted_count"] == 3

    states = _states(index)
    for e in edges:
        assert states[e["edge_id"]] == "active"


def test_r2_promotion_reports_no_candidates(tmp_path):
    """Completion≠Output:无合格输入时必须落明确原因码。"""
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion

    store, index = _store(tmp_path)
    result = run_edge_promotion(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["promoted_count"] == 0
    assert result["outcome"] == "no_candidates"


# ── TTL 遗忘 ───────────────────────────────────────────────────────────────


def test_r2_ttl_invalidates_stale_candidates(tmp_path):
    """超龄 candidate 必须被自动作废(有界)— 动态遗忘,不是永远记忆。"""
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

    counts: dict[str, int] = {}
    for state in _states(index).values():
        counts[state] = counts.get(state, 0) + 1
    assert counts.get("active", 0) == PROMOTE_PER_RUN
    assert counts.get("invalidated", 0) == 2
    assert counts.get("candidate", 0) == 0


def test_r2_ttl_spares_fresh_candidates(tmp_path):
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion

    store, index = _store(tmp_path)
    _seed_candidates(index, 3)
    result = run_edge_promotion(str(index.roots.index_path), index=index)
    assert result["ttl_invalidated_count"] == 0


# ── Digest:审批区段废除,纠错 action 保留 ────────────────────────────────


def test_r3_digest_has_no_edge_review_section(tmp_path):
    """R3 counterfactual:digest 不得再渲染任何边审批区段/审批 token。

    Owner:「每次要我去审批就不对了」。旧实现渲染 Pending Edge Review +
    approve_edge token → 本测试在旧实现下必红。
    """
    from plugins.memory.memory_os.edge_promotion import run_edge_promotion
    from plugins.memory.memory_os.owner_actions import _rendered_digest_text

    store, index = _store(tmp_path)
    _seed_candidates(index, 3, state="owner_eligible")
    _seed_candidates(index, 2)

    text = _rendered_digest_text(
        {"action_required": [], "review_suggested": [], "fyi": []},
        counts={}, store=store,
    )
    assert "Pending Edge Review" not in text
    assert "approve_edge:" not in text
    assert "reject_edge:" not in text


def test_r3_reject_edge_action_retained_for_correction(tmp_path):
    """reject_edge 保留为 owner 纠错工具(active → invalidated),不主动推送。"""
    from plugins.memory.memory_os.owner_actions import _apply_state_transition

    store, index = _store(tmp_path)
    edge = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_fix_a",
        to_record_type="crystallized_record", to_record_id="cry_fix_b",
        relation_type="co_occurs", weight=0.9, proposed_by="structural",
        state="active",
    )
    record = {
        "action_type": "reject_edge",
        "target_id": edge["edge_id"],
        "target_type": "edge",
        "owner_id": "owner-test",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "owner_effect": {},
    }
    result = _apply_state_transition(store, record, note="", rating="")
    assert result.get("new_state") == "invalidated"
    assert _states(index)[edge["edge_id"]] == "invalidated"


def test_r3_batch_reject_retained(tmp_path):
    from plugins.memory.memory_os.owner_actions import _apply_state_transition

    store, index = _store(tmp_path)
    edges = _seed_candidates(index, 2, state="active")
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
    assert result.get("rejected_count") == 2


# ── 词表双向守卫(R1/R2 后的新拓扑)────────────────────────────────────────


def test_r2_edge_state_vocabulary_bidirectional_guard():
    """双向断言(R1/R2 后):生产者写出的每个状态都有消费出口。

    新拓扑:proposer/provenance → active(直接);存量 candidate →
    自动激活通道(PROMOTION_SOURCE_STATES)→ active;active → 注入消费
    (GRAPH_INJECTION_EDGE_STATE)+ 权重反馈遗忘;invalidated 终态。
    owner_eligible 为 legacy 态:无生产者,自动激活通道负责清空。
    """
    from plugins.memory.memory_os.edge_promotion import (
        PROMOTION_SOURCE_STATES,
        PROMOTION_TARGET_STATE,
    )
    from plugins.memory.memory_os.prefetch import GRAPH_INJECTION_EDGE_STATE

    assert set(EDGE_STATE_TRANSITIONS) == {
        "candidate", "owner_eligible", "active", "invalidated",
    }
    # 非终态全部被自动激活通道消费(candidate + legacy owner_eligible)
    assert set(PROMOTION_SOURCE_STATES) == {"candidate", "owner_eligible"}
    assert PROMOTION_TARGET_STATE == "active"
    # 激活目标即注入消费态
    assert GRAPH_INJECTION_EDGE_STATE == PROMOTION_TARGET_STATE
    # 状态机可达性
    for source in PROMOTION_SOURCE_STATES:
        assert PROMOTION_TARGET_STATE in EDGE_STATE_TRANSITIONS[source]
    assert EDGE_STATE_TRANSITIONS["invalidated"] == set()
    # digest 不再是消费者:owner_actions 不得暴露 digest 边审批词表
    import plugins.memory.memory_os.owner_actions as oa
    assert not hasattr(oa, "EDGE_REVIEW_DIGEST_STATE"), (
        "R3: the digest edge-review vocabulary must be gone"
    )
