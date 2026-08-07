"""W4 — 溯源边挖掘:source_event_ids → event→crystallized evidence_for 边。

图源三档原则第 2 档:溯源关系已躺在结晶元数据里(结晶批准时已过
OwnerGate),免 LLM、免相似度、确定性;方向定为 event → crystallized
(事件是结晶的证据),使 FTS 锚点落在 event 段时能一跳召回结晶目标。
"""
from __future__ import annotations

import sqlite3

import pytest

from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="edge-provenance-test")
    store = MemoryOSStore(roots)
    store.initialize()
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)
    return store, index


def _seed_crystallized(store, records):
    """写规范 markdown 结晶记录,再由 rebuild 投影(真实生产链)。

    与 test_memory_os_graph_layer._seed_canonical_crystallized 同构
    (测试模块间不可 import,故内联)。
    """
    store.initialize()
    for rec in records:
        frontmatter = {
            "schema_version": "memory-os.crystallized.v0",
            "id": rec["id"],
            "kind": rec.get("kind", "test"),
            "created_at": rec.get("created_at", "2026-06-01T00:00:00Z"),
            "approved_by": "owner",
            "approved_at": rec.get("created_at", "2026-06-01T00:00:00Z"),
            "approval_purpose": "test",
            "approval_note": "test seed",
            "source_event_ids": rec.get("source_event_ids", []),
            "tags": rec.get("tags", []),
            "sensitivity": "private",
            "hindsight_indexed": False,
            "bridge_state": "active",
        }
        body = rec.get("body", "test crystallized record body")
        store.append_crystallized_record("test_provenance.md", frontmatter, body)


def test_w4_provenance_edges_created_from_source_event_ids(tmp_path):
    """反事实:结晶记录的 source_event_ids 必须产出 event→crystallized 边。

    无 W4 时全库不存在任何跨层边挖掘路径 → 必红。
    """
    from plugins.memory.memory_os.edge_provenance import run_edge_provenance

    store, index = _store(tmp_path)
    _seed_crystallized(store, [
        {"id": "cry_prov_a", "kind": "preference", "created_at": "2026-08-01T10:00:00Z",
         "source_event_ids": ["evt_prov_1", "evt_prov_2"], "tags": [], "body": "prov body a"},
        {"id": "cry_prov_b", "kind": "fact", "created_at": "2026-08-02T10:00:00Z",
         "source_event_ids": ["evt_prov_3"], "tags": [], "body": "prov body b"},
    ])
    index.rebuild_from_store(store)

    result = run_edge_provenance(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"
    assert result["proposed_count"] == 3

    conn = sqlite3.connect(str(index.roots.index_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select * from memory_edges where proposed_by = 'provenance' order by from_record_id"
    ).fetchall()
    conn.close()
    assert len(rows) == 3
    by_from = {str(r["from_record_id"]): r for r in rows}
    assert set(by_from) == {"evt_prov_1", "evt_prov_2", "evt_prov_3"}
    for r in rows:
        assert str(r["from_record_type"]) == "event"
        assert str(r["to_record_type"]) == "crystallized_record"
        assert str(r["relation_type"]) == "evidence_for"
        # 元数据在结晶批准时已过 OwnerGate → auto-active
        assert str(r["state"]) == "active"
    assert str(by_from["evt_prov_1"]["to_record_id"]) == "cry_prov_a"
    assert str(by_from["evt_prov_3"]["to_record_id"]) == "cry_prov_b"


def test_w4_provenance_idempotent(tmp_path):
    """第二次运行 0 新边(写入口三元组去重兜底 + 自身幂等)。"""
    from plugins.memory.memory_os.edge_provenance import run_edge_provenance

    store, index = _store(tmp_path)
    _seed_crystallized(store, [
        {"id": "cry_prov_c", "kind": "fact", "created_at": "2026-08-01T10:00:00Z",
         "source_event_ids": ["evt_prov_9"], "tags": [], "body": "prov body c"},
    ])
    index.rebuild_from_store(store)

    first = run_edge_provenance(str(index.roots.index_path), index=index)
    assert first["proposed_count"] == 1
    second = run_edge_provenance(str(index.roots.index_path), index=index)
    assert second["proposed_count"] == 0
    assert second["dedup_skipped"] == 1


def test_w4_event_anchor_reaches_crystallized(tmp_path):
    """消费端验收:FTS 锚点落在 event 上时,一跳查询必须返回结晶目标。"""
    from plugins.memory.memory_os.edge_provenance import run_edge_provenance

    store, index = _store(tmp_path)
    _seed_crystallized(store, [
        {"id": "cry_prov_d", "kind": "fact", "created_at": "2026-08-01T10:00:00Z",
         "source_event_ids": ["evt_anchor_7"], "tags": [], "body": "prov body d"},
    ])
    index.rebuild_from_store(store)
    run_edge_provenance(str(index.roots.index_path), index=index)

    edges = index.query_edges(["evt_anchor_7"], depth=1, state="active", limit=8)
    assert edges, "event anchor must reach the crystallized record via provenance edge"
    assert any(str(e.get("to_record_id")) == "cry_prov_d" for e in edges)


def test_w4_injection_suppresses_unresolved_noncrystallized_targets(tmp_path):
    """注入过滤:非 crystallized 邻居解析失败(已被 retention 归档)时整行
    抑制,outcome=non_crystallized_target;解析失败的结晶邻居同样整行丢弃,
    outcome=unresolved — record_id 不再作为兜底行出现(P2:诊断归 shadow
    outcome,不进 agent 上下文)。
    """
    from plugins.memory.memory_os.prefetch import _render_graph_layer_lines

    store, _index = _store(tmp_path)
    edges = [
        {
            "relation_type": "evidence_for",
            "weight": 0.9,
            "to_record_type": "event",
            "to_record_id": "evt_archived_404",
            "from_record_type": "crystallized_record",
            "from_record_id": "cry_src",
            "state": "active",
        },
        {
            "relation_type": "co_occurs",
            "weight": 0.8,
            "to_record_type": "crystallized_record",
            "to_record_id": "nonexistent_cry_777",
            "from_record_type": "crystallized_record",
            "from_record_id": "cry_src",
            "state": "active",
        },
    ]
    lines, decisions = _render_graph_layer_lines(
        store, edges, anchor_ids=["cry_src"], seen=set(),
    )
    assert lines == [], (
        f"neither neighbor is renderable — no id-fallback lines allowed: {lines}"
    )
    by_target = {str(d["edge"]["to_record_id"]): d["outcome"] for d in decisions}
    assert by_target["evt_archived_404"] == "non_crystallized_target"
    assert by_target["nonexistent_cry_777"] == "unresolved"
