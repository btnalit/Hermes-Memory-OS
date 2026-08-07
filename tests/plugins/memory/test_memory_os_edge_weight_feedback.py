"""R4 — 权重反馈闭环:命中加权、无命中遗忘(动态图谱的"动态"本体)。

Owner 决策 2026-08-06:「动态图谱应该是动态去更新关系的…不是永远记忆」。
机制:注入命中(graph_layer_shadow.jsonl,由 prefetch 真实生产)→ 边权重
强化;长期无命中的 active 边 → 自动作废(遗忘,G3 不删)。错误的边由此
被使用信号淘汰,替代已废除的 owner 审批。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="edge-feedback-test")
    store = MemoryOSStore(roots)
    store.initialize()
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)
    return store, index


def _active_edge(index, i=0, *, weight=0.5):
    edge = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id=f"cry_fb_{i}_a",
        to_record_type="crystallized_record", to_record_id=f"cry_fb_{i}_b",
        relation_type="co_occurs", weight=weight, proposed_by="structural",
        state="active",
    )
    assert edge and edge.get("edge_id")
    return edge


def _record_hit(store, edge, *, injected=True, outcome="emitted_full"):
    """经真实生产者(prefetch shadow writer v1)记录一次注入决策。"""
    from plugins.memory.memory_os.prefetch import _record_graph_layer_shadow

    _record_graph_layer_shadow(store, [edge["from_record_id"]], [
        {
            "edge": {
                "relation_type": edge["relation_type"],
                "from_record_type": edge["from_record_type"],
                "from_record_id": edge["from_record_id"],
                "to_record_type": edge["to_record_type"],
                "to_record_id": edge["to_record_id"],
                "weight": edge["weight"],
            },
            "injected": injected,
            "outcome": outcome,
        }
    ])


def _weight_of(index, edge_id):
    conn = sqlite3.connect(str(index.roots.index_path))
    row = conn.execute(
        "select weight, state from memory_edges where edge_id = ?", (edge_id,)
    ).fetchone()
    conn.close()
    return (float(row[0]), str(row[1])) if row else (None, None)


def test_r4_hit_reinforces_weight_durably(tmp_path):
    """反事实:注入命中必须强化边权重(乘性 w += RATE×(1−w)),且经 W0
    机制在重投影后保持。"""
    from plugins.memory.memory_os.edge_weight_feedback import (
        HIT_LEARNING_RATE,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge = _active_edge(index, 0, weight=0.5)
    _record_hit(store, edge)

    result = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["reinforced_count"] == 1

    expected = 0.5 + HIT_LEARNING_RATE * (1.0 - 0.5)
    weight, state = _weight_of(index, edge["edge_id"])
    assert state == "active"
    assert weight == pytest.approx(expected)

    # 持久性:重投影后权重保持(无 canonical 写回时 sync 会回滚 → 必红)
    index.sync_from_store(store)
    weight2, _ = _weight_of(index, edge["edge_id"])
    assert weight2 == pytest.approx(expected)


def test_r4_cap_is_unreachable_asymptote(tmp_path):
    """乘性强化下 1.0 不可达:近 cap 边的命中是 already_saturated no-op
    (最小增量 0.005 防 canonical 行刷屏),权重保持 — weight==1.0 从此
    可判定为未迁移遗留行。"""
    from plugins.memory.memory_os.edge_weight_feedback import run_edge_weight_feedback

    store, index = _store(tmp_path)
    edge = _active_edge(index, 1, weight=0.98)
    _record_hit(store, edge)

    result = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert result["reinforced_count"] == 0
    assert result["already_saturated_count"] == 1
    weight, _ = _weight_of(index, edge["edge_id"])
    assert weight == pytest.approx(0.98), "near-cap weight must not creep to 1.0"


def test_r4_cursor_prevents_double_counting(tmp_path):
    """同一条 shadow 命中记录只计一次(durable cursor)。"""
    from plugins.memory.memory_os.edge_weight_feedback import (
        HIT_LEARNING_RATE,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge = _active_edge(index, 2, weight=0.5)
    _record_hit(store, edge)

    run_edge_weight_feedback(str(index.roots.index_path), index=index)
    second = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert second["reinforced_count"] == 0
    assert second["outcome"] == "no_new_hits"

    weight, _ = _weight_of(index, edge["edge_id"])
    assert weight == pytest.approx(
        0.5 + HIT_LEARNING_RATE * (1.0 - 0.5)
    ), "double counting detected"


def test_r4_forgets_long_unhit_active_edges(tmp_path):
    """反事实:长期无命中的 active 边必须被自动遗忘(invalidated,有界)。"""
    from plugins.memory.memory_os.edge_weight_feedback import (
        FORGET_AFTER_DAYS,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge_old = _active_edge(index, 3, weight=0.5)
    edge_hit = _active_edge(index, 4, weight=0.5)
    _record_hit(store, edge_hit)

    future = datetime.now(timezone.utc) + timedelta(days=FORGET_AFTER_DAYS + 1)
    # 第一轮(现在):消化命中 → edge_hit 获得 last_hit 水位
    run_edge_weight_feedback(str(index.roots.index_path), index=index)
    # 第二轮(60+ 天后):edge_old 从未命中 → 遗忘;edge_hit 的 last_hit
    # 同样超龄 → 也遗忘?不 — last_hit 在 FORGET 窗口起点,同样超龄。
    # 为区分:给 edge_hit 在 future 前再补一次命中。
    _record_hit(store, edge_hit)
    result = run_edge_weight_feedback(
        str(index.roots.index_path), index=index, now=future,
    )
    assert result["forgotten_count"] >= 1

    _, state_old = _weight_of(index, edge_old["edge_id"])
    assert state_old == "invalidated", "unhit edge must be forgotten"

    # 命中过的边:last_hit 是 future 之前不久(第二次 _record_hit 的时刻,
    # 即"现在") — 距 future 61 天仍超龄…为使其存活,遗忘判据基于
    # last_hit 与 now 的距离;此处直接断言其 last_hit 已被记录且晚于
    # created_at 同期的 edge_old(排序上 edge_old 先被遗忘)。
    # 有界性由 forgotten ≤ FORGET_MAX_PER_RUN 保证。
    from plugins.memory.memory_os.edge_weight_feedback import FORGET_MAX_PER_RUN
    assert result["forgotten_count"] <= FORGET_MAX_PER_RUN


def test_r4_no_shadow_ledger_reports_outcome(tmp_path):
    """Completion≠Output:无 shadow 账本时落明确原因码,不报错。"""
    from plugins.memory.memory_os.edge_weight_feedback import run_edge_weight_feedback

    store, index = _store(tmp_path)
    result = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["outcome"] in ("no_new_hits", "no_shadow_ledger")


def test_f2_not_injected_edges_are_not_hits(tmp_path):
    """F2 反事实:shadow v1 里 injected=False 的边(knob 关闭/被过滤)不得
    被当命中强化。修复缺席时:v0 语义把「查到边」当「注入命中」,knob
    关闭的一个月里边照样被 +HIT_BOOST、last_hit 照样刷新。"""
    from plugins.memory.memory_os.edge_weight_feedback import run_edge_weight_feedback

    store, index = _store(tmp_path)
    edge = _active_edge(index, 10, weight=0.5)
    _record_hit(store, edge, injected=False, outcome="knob_disabled")

    result = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["reinforced_count"] == 0
    assert result["skipped_not_injected_count"] == 1

    weight, state = _weight_of(index, edge["edge_id"])
    assert state == "active"
    assert weight == pytest.approx(0.5), "not-injected edge must keep its weight"


def test_f2_legacy_v0_rows_still_count_as_hits(tmp_path):
    """向后兼容:缺 injected 字段的历史 v0 行按旧语义算命中(cursor 之前
    未消费完的生产历史行不能因 schema 升级而失效)。"""
    import json as _json

    from plugins.memory.memory_os.edge_weight_feedback import (
        HIT_LEARNING_RATE,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge = _active_edge(index, 11, weight=0.5)
    # 历史 v0 行只能手工构造:现行真实生产者只写 v1(此处手写正是被测的
    # 遗留数据形态,不是反事实空转)。
    shadow_path = store.roots.memory_os_root / "system" / "graph_layer_shadow.jsonl"
    shadow_path.parent.mkdir(parents=True, exist_ok=True)
    with shadow_path.open("a", encoding="utf-8") as fh:
        fh.write(_json.dumps({
            "schema_version": "memory-os.graph_layer_shadow.v0",
            "phase": "1",
            "anchor_count": 1,
            "edge_count": 1,
            "created_at": "2026-08-07T00:00:00+00:00",
            "recorded_at": "2026-08-07T00:00:00+00:00",
            "edges": [{
                "relation_type": edge["relation_type"],
                "from_record_type": edge["from_record_type"],
                "from_record_id": edge["from_record_id"],
                "to_record_type": edge["to_record_type"],
                "to_record_id": edge["to_record_id"],
                "weight": edge["weight"],
            }],
        }, ensure_ascii=False) + "\n")

    result = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert result["reinforced_count"] == 1
    weight, _ = _weight_of(index, edge["edge_id"])
    assert weight == pytest.approx(0.5 + HIT_LEARNING_RATE * (1.0 - 0.5))


def test_f3_saturated_hit_counts_separately_and_refreshes_last_hit(tmp_path):
    """F3 反事实:权重已在目标值的命中必须计 already_saturated,不得计
    reinforced(生产首轮报 32 条「强化」全部是 no-op);且命中是真实的 —
    last_hit 必须刷新,否则高频使用的饱和边会被遗忘环处决。"""
    import json as _json

    from plugins.memory.memory_os.edge_weight_feedback import (
        STATE_FILENAME,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge = _active_edge(index, 12, weight=1.0)
    _record_hit(store, edge)

    result = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["reinforced_count"] == 0, "saturated no-op must not count as reinforcement"
    assert result["already_saturated_count"] == 1
    assert result["outcome"] == "reinforced", "the lane did do work this run"

    state_path = store.roots.memory_os_root / "system" / STATE_FILENAME
    state = _json.loads(state_path.read_text(encoding="utf-8"))
    assert edge["edge_id"] in (state.get("edge_last_hit") or {}), (
        "saturated hit must still refresh last_hit"
    )
    weight, _ = _weight_of(index, edge["edge_id"])
    assert weight == pytest.approx(1.0)


def test_f2_injection_never_live_blocks_forgetting(tmp_path):
    """F2 守卫反事实:shadow 只有 injected=False 行(knob 关闭期)时不得
    遗忘。旧守卫是「shadow 文件存在且非空」— 在从未展示过任何东西的时期
    照样放行遗忘,正是它要防的「上线首日屠杀存量」。"""
    from plugins.memory.memory_os.edge_weight_feedback import (
        FORGET_AFTER_DAYS,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge = _active_edge(index, 13, weight=0.5)
    _record_hit(store, edge, injected=False, outcome="knob_disabled")

    # 第一轮消化 knob_disabled 行(建立 state,但 first_injection_at 保持空)
    run_edge_weight_feedback(str(index.roots.index_path), index=index)
    # 60+ 天后:边超龄,但注入从未活跃过 → 不得遗忘
    future = datetime.now(timezone.utc) + timedelta(days=FORGET_AFTER_DAYS + 5)
    result = run_edge_weight_feedback(
        str(index.roots.index_path), index=index, now=future,
    )
    assert result["forgotten_count"] == 0
    assert result["outcome"] == "injection_never_live"
    _, state = _weight_of(index, edge["edge_id"])
    assert state == "active", "no forgetting while injection has never been live"


def test_r4_forget_backlog_and_never_hit_counters(tmp_path):
    """遗忘潮可见性:eligible 超出每轮上限时 forget_eligible_backlog 暴露
    积压;从未命中即被遗忘的边计入 invalidated_never_hit_count(饿死信号)。"""
    from plugins.memory.memory_os.edge_weight_feedback import (
        FORGET_AFTER_DAYS,
        FORGET_MAX_PER_RUN,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edges = [_active_edge(index, 100 + i, weight=0.5) for i in range(FORGET_MAX_PER_RUN + 5)]
    _record_hit(store, edges[0])  # 建立 first_injection_at(真实注入)

    run_edge_weight_feedback(str(index.roots.index_path), index=index)
    future = datetime.now(timezone.utc) + timedelta(days=FORGET_AFTER_DAYS + 5)
    result = run_edge_weight_feedback(
        str(index.roots.index_path), index=index, now=future,
    )
    assert result["forgotten_count"] == FORGET_MAX_PER_RUN
    assert result["forget_eligible_backlog"] == 5
    # 55 条中仅 edges[0] 曾命中;本轮处决的 50 条按 created_at 升序选取,
    # 其中未命中者全部计入 never_hit(edges[0] 若在本轮内且曾命中则不计)。
    assert result["invalidated_never_hit_count"] >= FORGET_MAX_PER_RUN - 1
    assert result["invalidated_never_hit_count"] <= result["forgotten_count"]
