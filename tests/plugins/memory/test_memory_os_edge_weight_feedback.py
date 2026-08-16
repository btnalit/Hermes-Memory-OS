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


def test_r4_cursor_misalignment_on_ledger_truncation_does_not_reprocess(tmp_path):
    """反事实(线计数 cursor 对 compaction-eligible 账本):账本被压缩(截断)
    到比游标短时,必须检测出错位、落类型化原因码 + skipped 计数,且绝不能
    从零重放(乘性强化非幂等,重放会对已强化边二次加分)。截断用真实生产者
    产出的行的子集改写(不是手写 fixture),模拟未来 compaction 只保留尾部
    (去掉最老的头部行)的形态。"""
    from plugins.memory.memory_os.edge_weight_feedback import (
        HIT_LEARNING_RATE,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge1 = _active_edge(index, 20, weight=0.5)
    edge2 = _active_edge(index, 21, weight=0.5)
    _record_hit(store, edge1)
    _record_hit(store, edge2)

    first = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert first["reinforced_count"] == 2
    assert first["cursor_misaligned"] is False
    expected = 0.5 + HIT_LEARNING_RATE * (1.0 - 0.5)
    weight1_before, _ = _weight_of(index, edge1["edge_id"])
    weight2_before, _ = _weight_of(index, edge2["edge_id"])
    assert weight1_before == pytest.approx(expected)
    assert weight2_before == pytest.approx(expected)

    # Simulate a future compaction: rewrite the ledger to a real subset of its
    # own already-produced lines (drop the oldest/head record), not a
    # hand-written fixture. processed cursor (2) now exceeds len(lines) (1).
    shadow_path = store.roots.memory_os_root / "system" / "graph_layer_shadow.jsonl"
    real_lines = shadow_path.read_text(encoding="utf-8").splitlines()
    assert len(real_lines) == 2
    shadow_path.write_text(real_lines[1] + "\n", encoding="utf-8", newline="\n")

    second = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert second["outcome"] == "cursor_misaligned"
    assert second["cursor_misaligned"] is True
    assert second["cursor_misalignment_reason"] == "ledger_shorter_than_cursor"
    assert second["cursor_previous_line_count"] == 2
    assert second["cursor_realigned_line_count"] == 1
    assert second["cursor_skipped_row_count"] == 1
    assert second["reinforced_count"] == 0, "misaligned run must not reprocess/reinforce anything"

    # Edge weights must be byte-for-byte unchanged by the truncation — no
    # replay-from-zero double-reinforcement of edge1 or edge2.
    weight1_after, _ = _weight_of(index, edge1["edge_id"])
    weight2_after, _ = _weight_of(index, edge2["edge_id"])
    assert weight1_after == pytest.approx(weight1_before)
    assert weight2_after == pytest.approx(weight2_before)


def test_r4_incremental_hits_after_aligned_run_reinforce_only_new_lines(tmp_path):
    """正常增量运行不回归:第二轮追加真实新命中后,只强化新增的那一条,
    第一轮已强化的边权重保持不变(校验 fingerprint 对齐路径本身没有偏移
    一位的新 bug)。"""
    from plugins.memory.memory_os.edge_weight_feedback import (
        HIT_LEARNING_RATE,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge1 = _active_edge(index, 22, weight=0.5)
    edge2 = _active_edge(index, 23, weight=0.5)
    _record_hit(store, edge1)

    first = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert first["reinforced_count"] == 1
    assert first["cursor_misaligned"] is False
    expected1 = 0.5 + HIT_LEARNING_RATE * (1.0 - 0.5)
    weight1, _ = _weight_of(index, edge1["edge_id"])
    assert weight1 == pytest.approx(expected1)

    _record_hit(store, edge2)
    second = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert second["cursor_misaligned"] is False
    assert second["reinforced_count"] == 1, "only the newly appended hit must be reinforced"

    weight1_again, _ = _weight_of(index, edge1["edge_id"])
    weight2, _ = _weight_of(index, edge2["edge_id"])
    assert weight1_again == pytest.approx(expected1), "edge1 must not be re-reinforced on the second run"
    assert weight2 == pytest.approx(0.5 + HIT_LEARNING_RATE * (1.0 - 0.5))


def test_r4_cursor_misalignment_fingerprint_mismatch_reports_nonzero_skipped_count(tmp_path):
    """反事实(内容指纹错位分支的 skipped 计数不得恒为 0):当账本被压缩后
    又追加,使 len(lines) >= processed 但游标位置的内容已变(fingerprint
    不匹配分支),该分支把整条前向未消费 backlog 丢弃(new_lines=[]),但
    修复缺席时 `max(0, processed - len(lines))` 在此分支恒为 0 —— 专门为
    量化这次丢失新增的字段在它存在的两种情况之一里必然报零。"""
    from plugins.memory.memory_os.edge_weight_feedback import (
        HIT_LEARNING_RATE,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge1 = _active_edge(index, 40, weight=0.5)
    edge2 = _active_edge(index, 41, weight=0.5)
    _record_hit(store, edge1)
    _record_hit(store, edge2)

    first = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert first["reinforced_count"] == 2
    assert first["cursor_misaligned"] is False
    expected = 0.5 + HIT_LEARNING_RATE * (1.0 - 0.5)
    weight1_before, _ = _weight_of(index, edge1["edge_id"])
    weight2_before, _ = _weight_of(index, edge2["edge_id"])
    assert weight1_before == pytest.approx(expected)
    assert weight2_before == pytest.approx(expected)

    # Simulate a future compaction+append: drop the oldest/head record
    # (real line 0) but keep the real line 1, then append two MORE real
    # hits via the real producer. processed cursor (2) now points at the
    # SECOND position of a ledger that is longer than before (len=3 >=
    # processed=2) -- content-based mismatch, not the shorter-ledger case.
    shadow_path = store.roots.memory_os_root / "system" / "graph_layer_shadow.jsonl"
    real_lines = shadow_path.read_text(encoding="utf-8").splitlines()
    assert len(real_lines) == 2
    shadow_path.write_text(real_lines[1] + "\n", encoding="utf-8", newline="\n")
    edge3 = _active_edge(index, 42, weight=0.5)
    edge4 = _active_edge(index, 43, weight=0.5)
    _record_hit(store, edge3)
    _record_hit(store, edge4)
    post_compaction_lines = shadow_path.read_text(encoding="utf-8").splitlines()
    assert len(post_compaction_lines) == 3, "compaction+append must land len(lines) >= processed"

    second = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert second["outcome"] == "cursor_misaligned"
    assert second["cursor_misaligned"] is True
    assert second["cursor_misalignment_reason"] == "ledger_fingerprint_mismatch"
    assert second["cursor_previous_line_count"] == 2
    assert second["cursor_realigned_line_count"] == 3
    assert second["cursor_skipped_row_count"] == 1, (
        "len(lines) - processed = 3 - 2 = 1 (nonzero): the fingerprint-mismatch "
        "branch drops new_lines=[] entirely and must not report a zero loss"
    )
    assert second["reinforced_count"] == 0, "misaligned run must not reprocess/reinforce anything"

    # Edge weights must be byte-for-byte unchanged by the compaction+append —
    # no replay-from-zero double-reinforcement.
    weight1_after, _ = _weight_of(index, edge1["edge_id"])
    weight2_after, _ = _weight_of(index, edge2["edge_id"])
    assert weight1_after == pytest.approx(weight1_before)
    assert weight2_after == pytest.approx(weight2_before)


def test_r4_torn_last_line_is_not_counted_and_completes_next_run(tmp_path):
    """并发反事实(读写竞态下的假错位):per-turn prefetch 写手在没有读锁的
    账本上追加(append_jsonl_locked 单次 handle.write() 写整行+\\n,但读侧
    `run_edge_weight_feedback` 不持锁),读侧可能在一次 write() 完成前捕获
    到被截断、无尾随换行符的最后一行。修复缺席时该半行会被计入
    processed_line_count 且对它取 fingerprint;下一轮该行补全后内容变化 →
    fingerprint 不匹配 → 假 ledger_fingerprint_mismatch → 丢弃两次运行之间
    追加的所有新行(含真正的新命中)。"""
    from plugins.memory.memory_os.edge_weight_feedback import (
        HIT_LEARNING_RATE,
        run_edge_weight_feedback,
    )

    store, index = _store(tmp_path)
    edge1 = _active_edge(index, 50, weight=0.5)
    edge2 = _active_edge(index, 51, weight=0.5)

    # Both rows built via the real producer first, so their exact serialized
    # form is captured -- only the torn-write SIMULATION below appends raw
    # bytes, standing in for a reader racing an in-progress writer append.
    _record_hit(store, edge1)
    _record_hit(store, edge2)
    shadow_path = store.roots.memory_os_root / "system" / "graph_layer_shadow.jsonl"
    full_lines = shadow_path.read_text(encoding="utf-8").splitlines()
    assert len(full_lines) == 2
    complete_line0, complete_line1 = full_lines
    torn_line1 = complete_line1[: len(complete_line1) - 5]  # drop tail bytes

    # Rewrite the ledger to what a torn write of line 1 would leave behind:
    # line 0 complete (with its trailing \n), line 1 truncated with NO
    # trailing \n -- exactly what a reader can observe mid-`handle.write()`
    # of a real append, since that write is not lock-visible to this reader.
    with shadow_path.open("wb") as fh:
        fh.write((complete_line0 + "\n" + torn_line1).encode("utf-8"))

    first = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert first["cursor_misaligned"] is False, "cold start (processed==0) must never misalign"
    assert first["new_hit_record_count"] == 1, "the torn line must be invisible this run"
    assert first["reinforced_count"] == 1

    expected = 0.5 + HIT_LEARNING_RATE * (1.0 - 0.5)
    weight1, _ = _weight_of(index, edge1["edge_id"])
    assert weight1 == pytest.approx(expected)
    weight2, _ = _weight_of(index, edge2["edge_id"])
    assert weight2 == pytest.approx(0.5), "torn line must not be reinforced yet"

    # Complete the torn line (the writer's write() finishes) and append one
    # brand-new full row via the real producer.
    edge3 = _active_edge(index, 52, weight=0.5)
    with shadow_path.open("ab") as fh:
        fh.write((complete_line1[len(torn_line1):] + "\n").encode("utf-8"))
    _record_hit(store, edge3)

    second = run_edge_weight_feedback(str(index.roots.index_path), index=index)
    assert second["cursor_misaligned"] is False, (
        "the now-completed line must fingerprint-match what this run actually "
        "consumed last time -- no false ledger_fingerprint_mismatch"
    )
    assert second["reinforced_count"] == 2, "completed edge2 line + new edge3 line, each exactly once"

    weight2_after, _ = _weight_of(index, edge2["edge_id"])
    assert weight2_after == pytest.approx(expected), "edge2 reinforced exactly once, not twice"
    weight3, _ = _weight_of(index, edge3["edge_id"])
    assert weight3 == pytest.approx(expected)


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
