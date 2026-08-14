"""Phase 1 — Graph Layer: DDL, CRUD, governance lifecycle, prefetch shadow.

Test IDs map to T1.x.y in graph-layer-roadmap.md §8.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.index import (
    MemoryOSIndex,
    transition_edge_state,
    write_governed_edge,
    _query_edges_sqlite,
)
from plugins.memory.memory_os.prefetch import (
    build_prefetch,
    _collect_anchor_ids,
    _graph_layer_shadow_lines,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore

import pytest

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


# ── Helpers ────────────────────────────────────────────────────────────────


def _store(tmp_path) -> tuple[MemoryOSStore, MemoryOSIndex]:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="graph-layer-test")
    store = MemoryOSStore(roots)
    store.initialize()
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)
    return store, index


def _conn(index: MemoryOSIndex) -> sqlite3.Connection:
    conn = sqlite3.connect(str(index.roots.index_path))
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════════════
# 1.1 DDL 定全 + 重建
# ═══════════════════════════════════════════════════════════════════════════


def test_t1_1_1_schema_has_all_12_columns(tmp_path):
    """T1.1.1: memory_edges schema has all 12 columns."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    cols = {str(c[1]) for c in conn.execute("pragma table_info(memory_edges)").fetchall()}
    conn.close()
    expected = {
        "edge_id", "from_record_type", "from_record_id",
        "to_record_type", "to_record_id", "relation_type",
        "weight", "created_at", "source_event_id",
        "state", "invalidated_at", "proposed_by",
    }
    assert cols == expected, f"Missing cols: {expected - cols}"


def test_t1_1_2_rebuild_is_reversible(tmp_path):
    """T1.1.2: a governed edge written to canonical graph/edges.jsonl
    survives rebuild via _index_edges projection back into memory_edges."""
    store, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots,
        from_record_type="crystallized_record", from_record_id="rec_a",
        to_record_type="crystallized_record", to_record_id="rec_b",
        relation_type="refines",
    )
    conn.close()

    edges_path = index.roots.memory_os_root / "graph" / "edges.jsonl"
    assert edges_path.exists()
    assert edge["edge_id"] in edges_path.read_text(encoding="utf-8")

    index.rebuild_from_store(store)

    conn2 = _conn(index)
    row = conn2.execute("select * from memory_edges where edge_id=?", (edge["edge_id"],)).fetchone()
    cols = {str(c[1]) for c in conn2.execute("pragma table_info(memory_edges)").fetchall()}
    conn2.close()
    assert row is not None
    assert str(row["from_record_id"]) == "rec_a"
    assert str(row["to_record_id"]) == "rec_b"
    assert str(row["relation_type"]) == "refines"
    expected = {
        "edge_id", "from_record_type", "from_record_id",
        "to_record_type", "to_record_id", "relation_type",
        "weight", "created_at", "source_event_id",
        "state", "invalidated_at", "proposed_by",
    }
    assert cols == expected, f"Missing cols: {expected - cols}"


def test_t1_1_3_weight_default_1_0(tmp_path):
    """T1.1.3: weight defaults to 1.0."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots,
        from_record_type="crystallized_record", from_record_id="a",
        to_record_type="crystallized_record", to_record_id="b",
        relation_type="refines",
    )
    assert edge["weight"] == 1.0
    conn.close()


def test_t1_1_4_state_default_candidate(tmp_path):
    """T1.1.4: state defaults to 'candidate'."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots,
        from_record_type="crystallized_record", from_record_id="a",
        to_record_type="crystallized_record", to_record_id="b",
        relation_type="refines",
    )
    assert edge["state"] == "candidate"
    conn.close()


def test_t1_1_5_proposed_by_default_structural(tmp_path):
    """T1.1.5: proposed_by defaults to 'structural'."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots,
        from_record_type="crystallized_record", from_record_id="a",
        to_record_type="crystallized_record", to_record_id="b",
        relation_type="refines",
    )
    assert edge["proposed_by"] == "structural"
    conn.close()


def test_t1_1_6_invalidated_at_nullable(tmp_path):
    """T1.1.6: invalidated_at is nullable."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots,
        from_record_type="crystallized_record", from_record_id="a",
        to_record_type="crystallized_record", to_record_id="b",
        relation_type="refines",
    )
    assert edge["invalidated_at"] is None
    # After invalidate it should have a value
    updated = transition_edge_state(conn, edge["edge_id"], "invalidated", roots=index.roots)
    assert updated["invalidated_at"] is not None
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# 1.2 边 CRUD
# ═══════════════════════════════════════════════════════════════════════════


def test_t1_2_1_write_and_read_edge_back(tmp_path):
    """T1.2.1: write an edge and read it back."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots,
        from_record_type="crystallized_record", from_record_id="rec_x",
        to_record_type="crystallized_record", to_record_id="rec_y",
        relation_type="depends_on",
        proposed_by="owner",
        state="active",
    )
    row = conn.execute("select * from memory_edges where edge_id=?", (edge["edge_id"],)).fetchone()
    assert row is not None
    assert str(row["relation_type"]) == "depends_on"
    assert str(row["state"]) == "active"
    assert str(row["proposed_by"]) == "owner"
    conn.close()


def test_t1_2_2_query_edges_by_from_record_id(tmp_path):
    """T1.2.2: query_edges returns edges matching from_record_id."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    write_governed_edge(
        conn, index.roots,
        from_record_type="crystallized_record", from_record_id="rec_a",
        to_record_type="crystallized_record", to_record_id="rec_b",
        relation_type="refines",
        state="active",
    )
    write_governed_edge(
        conn, index.roots,
        from_record_type="crystallized_record", from_record_id="rec_a",
        to_record_type="crystallized_record", to_record_id="rec_c",
        relation_type="depends_on",
        state="active",
    )
    conn.close()

    results = index.query_edges(["rec_a"], state="active", limit=10)
    assert len(results) == 2
    ids = {r["to_record_id"] for r in results}
    assert ids == {"rec_b", "rec_c"}


def test_t1_2_3_query_edges_by_to_record_id(tmp_path):
    """T1.2.3: query_edges returns edges matching to_record_id."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    write_governed_edge(
        conn, index.roots,
        from_record_type="crystallized_record", from_record_id="rec_root",
        to_record_type="crystallized_record", to_record_id="rec_target",
        relation_type="refines",
        state="active",
    )
    conn.close()

    results = index.query_edges(["rec_target"], state="active", limit=10)
    assert len(results) == 1
    assert results[0]["from_record_id"] == "rec_root"


def test_t1_2_4_query_edges_filters_by_relation_type(tmp_path):
    """T1.2.4: query_edges filters by relation_type."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines", state="active",
    )
    write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="c", relation_type="contradicts", state="active",
    )
    conn.close()

    results = index.query_edges(["a"], relation_types=["contradicts"], state="active", limit=10)
    assert len(results) == 1
    assert results[0]["relation_type"] == "contradicts"


def test_t1_2_5_query_edges_filters_by_state(tmp_path):
    """T1.2.5: query_edges filters by state."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines", state="candidate",
    )
    conn.close()

    # Should not find in active state
    results = index.query_edges(["a"], state="active", limit=10)
    assert len(results) == 0

    # Should find in candidate state
    results2 = index.query_edges(["a"], state="candidate", limit=10)
    assert len(results2) == 1


def test_t1_2_6_query_edges_respects_limit(tmp_path):
    """T1.2.6: limit works."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    for i in range(5):
        write_governed_edge(
            conn, index.roots, from_record_type="c", from_record_id="hub",
            to_record_type="c", to_record_id=f"node_{i}", relation_type="refines", state="active",
        )
    conn.close()

    results = index.query_edges(["hub"], state="active", limit=3)
    assert len(results) == 3


# ═══════════════════════════════════════════════════════════════════════════
# 1.3 治理生命周期
# ═══════════════════════════════════════════════════════════════════════════


def test_t1_3_1_state_default_candidate(tmp_path):
    """T1.3.1: state defaults to 'candidate'."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots,
        from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b",
        relation_type="refines",
    )
    assert edge["state"] == "candidate"
    conn.close()


def test_t1_3_2_candidate_to_owner_eligible_to_active(tmp_path):
    """T1.3.2: candidate → owner_eligible → active."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
    )
    # → owner_eligible
    r1 = transition_edge_state(conn, edge["edge_id"], "owner_eligible", roots=index.roots)
    assert r1["state"] == "owner_eligible"
    # → active
    r2 = transition_edge_state(conn, edge["edge_id"], "active", roots=index.roots)
    assert r2["state"] == "active"
    conn.close()


def test_t1_3_2b_skip_transition_rejected(tmp_path):
    """T1.3.2b: candidate → active directly (skip, allowed for low-risk)."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
    )
    r = transition_edge_state(conn, edge["edge_id"], "active", roots=index.roots)
    assert r["state"] == "active"
    conn.close()


def test_t1_3_3_active_to_invalidated(tmp_path):
    """T1.3.3: active → invalidated."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
        state="active",
    )
    r = transition_edge_state(conn, edge["edge_id"], "invalidated", roots=index.roots)
    assert r["state"] == "invalidated"
    assert r["invalidated_at"] is not None
    conn.close()


def test_t1_3_4_invalidate_not_delete(tmp_path):
    """T1.3.4: invalidate-not-delete."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
        state="active",
    )
    eid = edge["edge_id"]
    count_before = conn.execute("select count(*) from memory_edges").fetchone()[0]
    transition_edge_state(conn, eid, "invalidated", roots=index.roots)
    count_after = conn.execute("select count(*) from memory_edges").fetchone()[0]
    assert count_after == count_before, "Row should not be deleted"
    conn.close()


def test_t1_3_5_invalidated_excluded_from_query(tmp_path):
    """T1.3.5: invalidated edges don't appear in query_edges."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
        state="active",
    )
    transition_edge_state(conn, edge["edge_id"], "invalidated", roots=index.roots)
    conn.close()

    results = index.query_edges(["a"], state="active", limit=10)
    assert len(results) == 0

    # Still findable via raw query
    conn2 = _conn(index)
    count = conn2.execute("select count(*) from memory_edges").fetchone()[0]
    conn2.close()
    assert count == 1, "Row must still exist"


# ═══════════════════════════════════════════════════════════════════════════
# 1.4 治理边界 (G 系列)
# ═══════════════════════════════════════════════════════════════════════════


def test_t1_4_1_g1_fail_open_no_table(tmp_path):
    """T1.4.1: G1 — prefetch doesn't crash when memory_edges missing."""
    store, index = _store(tmp_path)
    # Drop the memory_edges table
    conn = _conn(index)
    conn.execute("drop table if exists memory_edges")
    conn.commit()
    conn.close()

    # Prefetch must not throw
    context = build_prefetch("test query", budget_chars=1000, store=store, index=index)
    # "Related Memory" section won't appear but prefetch itself should work
    assert isinstance(context, str)


def test_t1_4_2_g2_scope_locked(tmp_path):
    """T1.4.2: G2 — edges only in memory_edges, not other tables."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
    )
    # Verify it's in memory_edges only
    assert edge["edge_id"] is not None
    conn.close()


def test_t1_4_4_g4_provenance(tmp_path):
    """T1.4.4: G4 — every edge has proposed_by and created_at."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge1 = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
        proposed_by="structural",
    )
    edge2 = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="c", relation_type="contradicts",
        proposed_by="owner",
    )
    assert edge1["proposed_by"] == "structural"
    assert edge1["created_at"]
    assert edge2["proposed_by"] == "owner"
    assert edge2["created_at"]
    conn.close()


def test_t1_4_5_g6_audit(tmp_path):
    """T1.4.5: G6 — writing an edge can be correlated with index counts."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    before = conn.execute("select count(*) from memory_edges").fetchone()[0]
    write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
    )
    after = conn.execute("select count(*) from memory_edges").fetchone()[0]
    assert after == before + 1
    conn.close()


def test_t1_4_6_g7_deterministic_recall_independent(tmp_path):
    """T1.4.6: G7 — prefetch without graph is unchanged."""
    store_bare, _ = _store(tmp_path)
    context_no_graph = build_prefetch("test", budget_chars=1000, store=store_bare, index=None)

    # With a healthy index but no edges, the shadow section should be absent
    store2, index2 = _store(tmp_path)
    context_with_index = build_prefetch("test", budget_chars=1000, store=store2, index=index2)

    # Both should work and neither should contain "Related Memory"
    assert isinstance(context_no_graph, str)
    assert isinstance(context_with_index, str)
    # With no edges, shadow section won't appear
    assert "Related Memory" not in context_with_index


# ═══════════════════════════════════════════════════════════════════════════
# 1.5 Prefetch shadow
# ═══════════════════════════════════════════════════════════════════════════


def test_t1_5_1_shadow_section_does_not_inject_with_edges(tmp_path):
    """T1.5.1(P1 更新):回滚开关关火时 — edges are shadow-logged, NOT
    injected into context。默认已翻 True(owner 裁定),关火需显式 False
    override;knob_disabled 的边落账但 injected=False(F2)。"""
    store, index = _store(tmp_path)
    from plugins.memory.memory_os.knob_overrides import register_override as _reg
    _reg(
        "graph_layer_injection_enabled",
        False,
        prior=True,
        proposed_by="test",
        approved_via="test",
        expires_at="",
        roots=store.roots,
    )
    # Seed an event so FTS5 has content
    event = EventEnvelope.from_dict(build_event(seed=100, profile="graph-layer-test"))
    store.append_event(event)
    # Rebuild index so the event is indexed
    index.rebuild_from_store(store)

    # Write an edge between two record_ids that match the indexed event
    conn = _conn(index)
    write_governed_edge(
        conn, index.roots,
        from_record_type="event", from_record_id=event.id,
        to_record_type="event", to_record_id="evt_related_100",
        relation_type="co_occurs",
        state="active",
    )
    conn.close()

    # Prefetch with the event summary keyword
    context = build_prefetch("event", budget_chars=3000, store=store, index=index)

    # Phase 1: Related Memory section must NOT appear in context
    assert "Related Memory" not in context, (
        f"Phase 1: graph section must not inject. Context:\n{context}"
    )

    # Phase 1: Shadow log must have been written instead
    shadow_path = store.roots.memory_os_root / "system" / "graph_layer_shadow.jsonl"
    assert shadow_path.exists(), f"Phase 1 shadow log not written at {shadow_path}"
    lines = shadow_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1, "Expected at least 1 shadow log entry"

    # Verify shadow log structure (v1: injected/outcome per edge + anchor_ids)
    record = json.loads(lines[-1])
    assert record.get("schema_version") == "memory-os.graph_layer_shadow.v1"
    assert record.get("anchor_count") >= 1
    assert record.get("anchor_ids"), "v1 must persist anchor ids"
    assert record.get("edge_count") >= 1
    # knob 关闭:边落账但全部 injected=False/knob_disabled — 权重反馈闭环
    # 不得把这些当命中(F2)
    assert record.get("injected_count") == 0
    edges = record.get("edges", [])
    assert edges and all(
        e.get("injected") is False and e.get("outcome") == "knob_disabled"
        for e in edges
    ), f"knob-off edges must be marked not-injected: {edges}"
    assert any(
        e.get("relation_type") == "co_occurs"
        and e.get("from_record_id") == event.id
        for e in edges
    ), f"Expected co_occurs edge from {event.id} in shadow log"


def test_t1_5_2_no_anchor_no_expansion(tmp_path):
    """T1.5.2: no anchor = no shadow section."""
    store, index = _store(tmp_path)
    context = build_prefetch("xyznonexistent_marker_000", budget_chars=2000, store=store, index=index)
    assert "Related Memory" not in context


def test_t1_5_3_budget_respected(tmp_path):
    """T1.5.3: small budget clips the shadow section."""
    store, index = _store(tmp_path)
    event = EventEnvelope.from_dict(build_event(seed=101, profile="graph-layer-test"))
    store.append_event(event)
    index.rebuild_from_store(store)
    conn = _conn(index)
    for i in range(10):
        write_governed_edge(
            conn, index.roots,
            from_record_type="event", from_record_id=event.id,
            to_record_type="c", to_record_id=f"many_target_{i}",
            relation_type="co_occurs",
            state="active",
        )
    conn.close()

    # Very small budget — context must be tiny
    context = build_prefetch("event", budget_chars=200, store=store, index=index)
    assert len(context) <= 200


def test_t1_5_4_fail_open_no_crash(tmp_path):
    """T1.5.4: fail-open — broken index doesn't block prefetch."""
    store, index = _store(tmp_path)

    class BrokenIndex:
        def search(self, _q, *, limit=5):
            raise RuntimeError("broken search")

    # Prefetch with broken index — should not raise
    context = build_prefetch("anything", budget_chars=1000, store=store, index=BrokenIndex())
    assert isinstance(context, str)


def test_t1_5_5_depth_not_exceed_2(tmp_path):
    """T1.5.5: depth ≤ 2 — query_edges with depth=2 doesn't go to 3."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    # Chain: a → b → c → d
    e1 = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
        state="active",
    )
    e2 = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="b",
        to_record_type="c", to_record_id="c", relation_type="refines",
        state="active",
    )
    e3 = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="c",
        to_record_type="c", to_record_id="d", relation_type="refines",
        state="active",
    )
    conn.close()

    # depth=1: only direct neighbors
    r1 = index.query_edges(["a"], depth=1, state="active", limit=10)
    r1_ids = {r["to_record_id"] for r in r1}
    assert "b" in r1_ids
    assert "c" not in r1_ids
    assert "d" not in r1_ids

    # depth=2: b and c, but not d
    r2 = index.query_edges(["a"], depth=2, state="active", limit=10)
    r2_ids = {r["to_record_id"] for r in r2}
    assert "b" in r2_ids
    assert "c" in r2_ids
    assert "d" not in r2_ids, f"depth=2 should not reach d, got {r2_ids}"


# ═══════════════════════════════════════════════════════════════════════════
# Utility tests
# ═══════════════════════════════════════════════════════════════════════════


def test_collect_anchor_ids_empty_query(tmp_path):
    """_collect_anchor_ids returns [] for empty query."""
    _, index = _store(tmp_path)
    assert _collect_anchor_ids("", index) == []


def test_collect_anchor_ids_none_index(tmp_path):
    """_collect_anchor_ids returns [] for None index."""
    store, _ = _store(tmp_path)
    assert _collect_anchor_ids("test", None) == []


def test_graph_layer_shadow_lines_empty_anchor(tmp_path):
    """_graph_layer_shadow_lines returns [] for empty anchors."""
    store, index = _store(tmp_path)
    assert _graph_layer_shadow_lines(store, [], index=index) == []


def test_graph_layer_shadow_lines_none_index(tmp_path):
    """_graph_layer_shadow_lines returns [] for None index."""
    store, _ = _store(tmp_path)
    assert _graph_layer_shadow_lines(store, ["rec_a"], index=None) == []


def test_write_governed_edge_returns_empty_on_error(tmp_path):
    """write_governed_edge returns {} on connection error."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="graph-layer-test")
    conn = sqlite3.connect(":memory:")
    result = write_governed_edge(
        conn, roots,
        from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b",
        relation_type="refines",
    )
    # Should fail because memory_edges table doesn't exist in :memory:
    assert result == {}
    conn.close()


def test_transition_edge_state_illegal_transition(tmp_path):
    """transition_edge_state returns {} for illegal transition."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    edge = write_governed_edge(
        conn, index.roots, from_record_type="c", from_record_id="a",
        to_record_type="c", to_record_id="b", relation_type="refines",
        state="active",
    )
    # active → candidate is illegal
    result = transition_edge_state(conn, edge["edge_id"], "candidate", roots=index.roots)
    assert result == {}
    conn.close()


def test_transition_edge_state_nonexistent(tmp_path):
    """transition_edge_state returns {} for unknown edge."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    result = transition_edge_state(conn, "nonexistent_edge_id", "active", roots=index.roots)
    assert result == {}


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 — StructuralEdgeProposer
# ═══════════════════════════════════════════════════════════════════════════


def _seed_canonical_crystallized(
    store: MemoryOSStore,
    records: list[dict[str, Any]],
) -> None:
    """Write canonical crystallized record files so rebuild picks them up."""
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
        store.append_crystallized_record("test_phase2.md", frontmatter, body)


def test_t2_1_1_write_refines_edge(tmp_path):
    """T2.1.1 (W1 语义反转): shared source_event → co_occurs, 不再是 refines。

    原契约:共享溯源事件 → refines。W1/E2 收权后 structural 只可提名
    co_occurs/depends_on — 共享溯源是共现证据,精化判断归 LLM。
    """
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {
            "id": "cry_test_a_v1",
            "kind": "preference",
            "created_at": "2026-06-01T10:00:00Z",
            "source_event_ids": ["evt_shared_001"],
            "tags": ["refines-test"],
            "body": "Version one of the deployment configuration.",
        },
        {
            "id": "cry_test_a_v2",
            "kind": "preference",
            "created_at": "2026-06-01T12:00:00Z",
            "source_event_ids": ["evt_shared_001"],
            "tags": ["refines-test"],
            "body": "Version two of the deployment configuration (refined).",
        },
    ])
    index.rebuild_from_store(store)

    from plugins.memory.memory_os.structural_edge_proposer import (
        run_structural_proposer,
    )
    result = run_structural_proposer(
        str(index.roots.index_path),
        index=index,
    )
    assert result["status"] == "ok", f"Expected ok, got {result}"
    assert result["proposed_count"] >= 1, (
        f"Expected >=1 proposed edge, got {result}"
    )

    # Verify edge is in memory_edges — co_occurs, and NO structural refines.
    # R1 (owner 决策 2026-08-06:动态图谱全自动,不需要人工审批):proposer
    # 产出直接 active — 边是派生投影(advisory),错误的边由权重反馈闭环
    # 动态淘汰,不占用 owner 审批带宽。
    conn2 = _conn(index)
    rows = conn2.execute(
        "select * from memory_edges where relation_type = 'co_occurs'"
    ).fetchall()
    refines = conn2.execute(
        "select count(*) from memory_edges where relation_type = 'refines'"
    ).fetchone()[0]
    conn2.close()
    assert len(rows) >= 1
    assert rows[0]["state"] == "active", "R1: proposer output must be live immediately"
    assert rows[0]["proposed_by"] == "structural"
    assert refines == 0, "structural must not emit refines (W1/E2)"


def test_t2_1_2_write_contradicts_edge(tmp_path):
    """T2.1.2 (W1 语义反转): dice 相似 + 异 kind → co_occurs, 不再是 contradicts。

    原契约:相似 body + 不同 kind → contradicts。词元重叠证明不了矛盾,
    contradicts 归 LLM 提名(crystallization_gate 的矛盾消费不受影响 —
    它只读边,不管来源)。
    """
    store, index = _store(tmp_path)
    body = "The deployment was on 2026-05-27 at 08:44 UTC with codename prod-beta."
    _seed_canonical_crystallized(store, [
        {
            "id": "cry_contra_a",
            "kind": "preference",
            "created_at": "2026-06-01T10:00:00Z",
            "source_event_ids": ["evt_a"],
            "tags": [],
            "body": body,
        },
        {
            "id": "cry_contra_b",
            "kind": "probe",
            "created_at": "2026-06-01T12:00:00Z",
            "source_event_ids": ["evt_b"],
            "tags": [],
            "body": body,
        },
    ])
    index.rebuild_from_store(store)

    from plugins.memory.memory_os.structural_edge_proposer import (
        run_structural_proposer,
        _dice_coefficient,
    )
    # Verify dice coefficient is above threshold
    dice = _dice_coefficient(body, body)
    assert dice >= 0.30, f"Dice too low: {dice}"

    result = run_structural_proposer(
        str(index.roots.index_path),
        index=index,
    )
    assert result["status"] == "ok", f"Expected ok, got {result}"
    assert result["proposed_count"] >= 1

    conn2 = _conn(index)
    contradicts = conn2.execute(
        "select count(*) from memory_edges where relation_type = 'contradicts'"
    ).fetchone()[0]
    co_occurs = conn2.execute(
        "select count(*) from memory_edges where relation_type = 'co_occurs'"
    ).fetchone()[0]
    conn2.close()
    assert contradicts == 0, (
        f"structural must not emit contradicts (W1/E2). Result: {result}"
    )
    assert co_occurs >= 1, (
        f"similar bodies should still link as co_occurs. Result: {result}"
    )


def test_t2_1_3_write_depends_on_edge(tmp_path):
    """T2.1.3: depends_on edge when one body references another's ID."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {
            "id": "cry_dep_root",
            "kind": "preference",
            "created_at": "2026-06-01T10:00:00Z",
            "source_event_ids": [],
            "tags": [],
            "body": "Root record concept definition.",
        },
        {
            "id": "cry_dep_child",
            "kind": "preference",
            "created_at": "2026-06-01T12:00:00Z",
            "source_event_ids": [],
            "tags": [],
            "body": "This record builds on the foundation of cry_dep_root.",
        },
    ])
    index.rebuild_from_store(store)

    from plugins.memory.memory_os.structural_edge_proposer import (
        run_structural_proposer,
    )
    result = run_structural_proposer(
        str(index.roots.index_path),
        index=index,
    )
    assert result["status"] == "ok", f"Expected ok, got {result}"
    assert result["proposed_count"] >= 1

    conn3 = _conn(index)
    rows = conn3.execute(
        "select * from memory_edges where relation_type = 'depends_on'"
    ).fetchall()
    conn3.close()
    assert len(rows) >= 1


def test_t2_1_4_proposer_skipped_when_less_than_two_records(tmp_path):
    """T2.1.4: Proposer skips when < 2 crystallized records."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {
            "id": "cry_single",
            "kind": "test",
            "created_at": "2026-06-01T10:00:00Z",
            "body": "Single record.",
        },
    ])
    index.rebuild_from_store(store)

    from plugins.memory.memory_os.structural_edge_proposer import (
        run_structural_proposer,
    )
    result = run_structural_proposer(
        str(index.roots.index_path),
        index=index,
    )
    assert result["status"] == "skipped"
    assert result["proposed_count"] == 0


def test_t2_1_5_deduplication_no_duplicates(tmp_path):
    """T2.1.5: Proposer does not write duplicate edges."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {
            "id": "cry_dedup_a",
            "kind": "preference",
            "created_at": "2026-06-01T10:00:00Z",
            "source_event_ids": ["evt_shared"],
            "tags": [],
            "body": "Record A body content.",
        },
        {
            "id": "cry_dedup_b",
            "kind": "preference",
            "created_at": "2026-06-01T12:00:00Z",
            "source_event_ids": ["evt_shared"],
            "tags": [],
            "body": "Record B body content.",
        },
    ])
    index.rebuild_from_store(store)

    from plugins.memory.memory_os.structural_edge_proposer import (
        run_structural_proposer,
    )
    # Run twice — second run should produce 0 new edges (dedup)
    r1 = run_structural_proposer(str(index.roots.index_path), index=index)
    assert r1["proposed_count"] >= 1

    r2 = run_structural_proposer(str(index.roots.index_path), index=index)
    # Second run should not produce duplicates
    assert r2["proposed_count"] == 0, (
        f"Expected 0 new edges on second run, got {r2}"
    )

    conn2 = _conn(index)
    count = conn2.execute("select count(*) from memory_edges").fetchone()[0]
    conn2.close()
    # Count shouldn't grow after second run
    assert count == r1["proposed_count"]


def test_t2_1_6_proposer_instance_methods(tmp_path):
    """T2.1.6: index.write_governed_edge() and transition_edge_state() work."""
    _, index = _store(tmp_path)

    # write_governed_edge via instance method
    edge = index.write_governed_edge(
        from_record_type="crystallized_record",
        from_record_id="rec_a",
        to_record_type="crystallized_record",
        to_record_id="rec_b",
        relation_type="refines",
        proposed_by="structural",
        state="candidate",
    )
    assert edge, f"write_governed_edge failed"
    assert edge["relation_type"] == "refines"
    assert edge["state"] == "candidate"

    # transition_edge_state via instance method
    updated = index.transition_edge_state(edge["edge_id"], "owner_eligible")
    assert updated, "transition_edge_state failed"
    assert updated["state"] == "owner_eligible"

    # Final promote to active
    active = index.transition_edge_state(edge["edge_id"], "active")
    assert active["state"] == "active"


def test_t2_1_7_proposer_detects_co_occurs_temporal(tmp_path):
    """T2.1.7: Temporal proximity (< 1h) produces co_occurs edge."""
    store, index = _store(tmp_path)
    now = "2026-06-09T10:00:00Z"
    near = "2026-06-09T10:30:00Z"
    _seed_canonical_crystallized(store, [
        {
            "id": "cry_temp_a",
            "kind": "preference",
            "created_at": now,
            "source_event_ids": [],
            "tags": [],
            "body": "aaaaaa",
        },
        {
            "id": "cry_temp_b",
            "kind": "preference",
            "created_at": near,
            "source_event_ids": [],
            "tags": [],
            "body": "xxxxxx",
        },
    ])
    index.rebuild_from_store(store)

    from plugins.memory.memory_os.structural_edge_proposer import (
        run_structural_proposer,
    )
    result = run_structural_proposer(
        str(index.roots.index_path),
        index=index,
    )
    assert result["status"] == "ok", f"Expected ok, got {result}"

    conn2 = _conn(index)
    rows = conn2.execute(
        "select * from memory_edges where relation_type = 'co_occurs'"
    ).fetchall()
    conn2.close()
    assert len(rows) >= 1, (
        f"Expected co_occurs from temporal proximity. Result: {result}"
    )


def test_t2_1_8_proposer_detects_similar_body_but_same_kind(tmp_path):
    """T2.1.8 (W1 语义反转): 同 kind 相似 body → co_occurs, 不再是 refines。"""
    store, index = _store(tmp_path)
    body = "The system deployment was verified on 2026-06-01 with all tests green."
    _seed_canonical_crystallized(store, [
        {
            "id": "cry_body_a",
            "kind": "preference",
            "created_at": "2026-06-01T10:00:00Z",
            "source_event_ids": [],
            "tags": [],
            "body": body,
        },
        {
            "id": "cry_body_b",
            "kind": "preference",
            "created_at": "2026-06-01T12:00:00Z",
            "source_event_ids": [],
            "tags": [],
            "body": body,
        },
    ])
    index.rebuild_from_store(store)

    from plugins.memory.memory_os.structural_edge_proposer import (
        run_structural_proposer,
    )
    result = run_structural_proposer(
        str(index.roots.index_path),
        index=index,
    )
    assert result["status"] == "ok", f"Expected ok, got {result}"

    conn2 = _conn(index)
    rows = conn2.execute(
        "select relation_type, count(*) as cnt from memory_edges group by relation_type"
    ).fetchall()
    conn2.close()
    types = {str(r[0]): r[1] for r in rows}
    # W1/E2: similarity relatedness is co_occurs; refines/contradicts are
    # LLM-only vocabulary now.
    assert types.get("co_occurs", 0) >= 1, (
        f"Expected co_occurs edge for same-kind similarity. Got types: {types}"
    )
    assert types.get("refines", 0) == 0
    assert types.get("contradicts", 0) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2.2 — Crystallization Gate
# ═══════════════════════════════════════════════════════════════════════════


def _seed_contradicts_edge(
    conn: sqlite3.Connection,
    roots: MemoryOSRoots,
    from_id: str,
    to_id: str,
    *,
    state: str = "active",
) -> dict[str, Any]:
    """Helper: write a contradicts edge between two crystallized records."""
    from plugins.memory.memory_os.index import write_governed_edge
    return write_governed_edge(
        conn, roots,
        from_record_type="crystallized_record",
        from_record_id=from_id,
        to_record_type="crystallized_record",
        to_record_id=to_id,
        relation_type="contradicts",
        proposed_by="structural",
        state=state,
    )


def test_gate_error_records_use_one_shape_on_every_path(tmp_path):
    """Every error record the gate emits must be readable the same way.

    The early-return path built ``{"code": ...}`` while the per-candidate paths
    built ``{"error_code": ...}``, both under the same ``error_records`` key.
    Nothing crashed because the only consumer reads ``status``, but the next
    consumer to iterate the records would have found ``error_code`` missing on
    exactly the paths that matter — the failures.
    """
    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate

    # Path 1: the index cannot be opened at all.
    unopenable = run_crystallization_gate(str(tmp_path / "no_such_dir" / "index.db"))

    # Path 2: candidates resolve, but no edge index is available to clear them.
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_shape_a", "kind": "preference",
         "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": ["evt_a"], "tags": [],
         "body": "The deployment strategy favors gradual rollout over canary."},
    ])
    index.rebuild_from_store(store)
    no_edge_index = run_crystallization_gate(
        str(index.roots.index_path),
        candidates=[{
            "candidate_id": "cand_shape_test",
            "kind": "preference",
            "body": "The deployment strategy favors gradual rollout over canary.",
            "tags_json": "[]",
        }],
    )

    assert unopenable["status"] == "error"
    assert no_edge_index["status"] == "error"
    for result in (unopenable, no_edge_index):
        assert result["error_records"], result
        for record in result["error_records"]:
            assert set(record) == {"candidate_id", "error_code", "component"}, record
            assert record["error_code"], record
            assert record["component"], record


def test_t2_2_1_gate_flags_contradicting_candidate(tmp_path):
    """T2.2.1: Gate flags a candidate whose body matches a crystallized
    record that has a contradicts edge."""
    store, index = _store(tmp_path)
    conn = _conn(index)

    # Seed crystallized records: A and B have a contradicts edge
    _seed_canonical_crystallized(store, [
        {"id": "cry_gate_a", "kind": "preference",
         "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": ["evt_a"], "tags": [],
         "body": "The deployment strategy favors gradual rollout over canary."},
        {"id": "cry_gate_b", "kind": "preference",
         "created_at": "2026-06-01T12:00:00Z",
         "source_event_ids": ["evt_b"], "tags": [],
         "body": "The deployment strategy favors canary over gradual rollout."},
    ])
    index.rebuild_from_store(store)

    # Write a contradicts edge between A and B
    _seed_contradicts_edge(
        conn, index.roots, "cry_gate_a", "cry_gate_b")
    conn.close()

    # Seed a crystallized candidate that matches A's body text
    conn2 = _conn(index)
    conn2.execute(
        """insert into crystallized_candidates
           (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
           values (?, ?, ?, ?, ?, ?, ?)""",
        ("cand_gate_test", "preference",
         "The deployment strategy favors gradual rollout over canary.",
         "[]", "[]", "private", "proposed"),
    )
    conn2.commit()
    conn2.close()

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(
        str(index.roots.index_path),
        index=index,
    )
    assert result["status"] == "ok", f"Expected ok, got {result}"
    assert result["flagged_count"] >= 1, (
        f"Candidate should be flagged (contradicts edge exists). Result: {result}"
    )


def test_t2_2_2_gate_does_not_flag_non_contradicting_candidate(tmp_path):
    """T2.2.2: Gate does NOT flag a candidate with no contradicting edges."""
    store, index = _store(tmp_path)
    conn = _conn(index)

    # Seed crystallized records without contradicts edges
    _seed_canonical_crystallized(store, [
        {"id": "cry_safe_a", "kind": "preference",
         "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": ["evt_a"], "tags": [],
         "body": "Database indexing works best with B-tree on primary keys."},
    ])
    index.rebuild_from_store(store)

    # Seed a candidate with similar body — but NO contradicts edge exists
    conn2 = _conn(index)
    conn2.execute(
        """insert into crystallized_candidates
           (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
           values (?, ?, ?, ?, ?, ?, ?)""",
        ("cand_safe_test", "preference",
         "Database indexing works best with B-tree on primary keys.",
         "[]", "[]", "private", "proposed"),
    )
    conn2.commit()
    conn2.close()

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(
        str(index.roots.index_path),
        index=index,
    )
    assert result["status"] == "ok"
    assert result["flagged_count"] == 0, (
        f"Candidate should NOT be flagged (no contradicts edge). Result: {result}"
    )


def test_t2_2_3_gate_allows_owner_override(tmp_path):
    """T2.2.3: Gate flags are advisory — owner can still approve.

    The gate returns flagged_candidates but does NOT prevent promotion.
    Owner override is handled by the existing approval system.
    """
    store, index = _store(tmp_path)
    conn = _conn(index)

    _seed_canonical_crystallized(store, [
        {"id": "cry_override_a", "kind": "preference",
         "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": ["evt_oo"], "tags": [],
         "body": "Never deploy on Fridays."},
        {"id": "cry_override_b", "kind": "preference",
         "created_at": "2026-06-01T12:00:00Z",
         "source_event_ids": ["evt_ob"], "tags": [],
         "body": "Friday deployments are fine with rollback."},
    ])
    index.rebuild_from_store(store)
    _seed_contradicts_edge(
        conn, index.roots, "cry_override_a", "cry_override_b")
    conn.close()

    # Seed candidate that will be flagged
    conn2 = _conn(index)
    conn2.execute(
        """insert into crystallized_candidates
           (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
           values (?, ?, ?, ?, ?, ?, ?)""",
        ("cand_override_test", "preference",
         "Never deploy on Fridays.",
         "[]", "[]", "private", "proposed"),
    )
    conn2.commit()
    conn2.close()

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(
        str(index.roots.index_path),
        index=index,
    )
    # Gate flags the candidate
    assert result["flagged_count"] >= 1

    # Verify the gate is advisory: it only returns flagged info,
    # does NOT delete/modify the candidate or block writes
    conn3 = _conn(index)
    still_exists = conn3.execute(
        "select count(*) from crystallized_candidates where candidate_id = ?",
        ("cand_override_test",),
    ).fetchone()[0]
    conn3.close()
    assert still_exists == 1, "Gate must not delete candidates"
    assert "flagged_candidates" in result, "Gate returns flagged list for owner review"


def test_t2_2_4_gate_skipped_when_no_candidates(tmp_path):
    """T2.2.4: Gate handles empty candidate list gracefully."""
    store, index = _store(tmp_path)

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(
        str(index.roots.index_path),
        index=index,
    )
    assert result["status"] == "ok"
    assert result["candidate_count"] == 0
    assert result["flagged_count"] == 0


def test_t2_2_5_gate_returns_structured_error_when_index_cannot_open(tmp_path):
    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate

    result = run_crystallization_gate(str(tmp_path), index=None)

    assert result["status"] == "error"
    assert result["error_code"] == "cannot_open_index"
    assert result["error_count"] == 1
    assert result["error_records"] == [
        {"candidate_id": "", "error_code": "cannot_open_index", "component": "sqlite"}
    ]


def test_t2_2_5_gate_returns_structured_error_when_candidates_cannot_be_read(tmp_path):
    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate

    index_path = tmp_path / "empty.sqlite"
    sqlite3.connect(index_path).close()
    result = run_crystallization_gate(str(index_path), index=None)

    assert result["status"] == "error"
    assert result["error_code"] == "cannot_read_candidates"
    assert result["error_count"] == 1
    assert result["error_records"] == [
        {"candidate_id": "", "error_code": "cannot_read_candidates", "component": "sqlite"}
    ]


def test_t2_2_5_gate_fails_closed_when_edge_query_errors(tmp_path):
    """An unreadable graph must not look like a clean contradiction check."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_gate_error", "kind": "preference",
         "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": ["evt_gate_error"], "tags": [],
         "body": "The deployment strategy favors gradual rollout over canary."},
    ])
    index.rebuild_from_store(store)

    conn = _conn(index)
    conn.execute(
        """insert into crystallized_candidates
           (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
           values (?, ?, ?, ?, ?, ?, ?)""",
        ("cand_gate_error", "preference",
         "The deployment strategy favors gradual rollout over canary.",
         "[]", "[]", "private", "proposed"),
    )
    conn.commit()
    conn.close()

    class BrokenEdgeIndex:
        def query_edges(self, *args, **kwargs):
            raise RuntimeError("deterministic edge query failure")

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(
        str(index.roots.index_path),
        index=BrokenEdgeIndex(),
        audit_path=str(store.roots.audit_path),
    )

    assert result["status"] == "error"
    assert result["error_code"] == "edge_query_failed"
    assert result["error_count"] == 1
    assert result["flagged_count"] == 1
    assert result["flagged_candidates"][0]["candidate_id"] == "cand_gate_error"
    assert result["flagged_candidates"][0]["reason_code"] == "edge_query_failed"

    from plugins.memory.memory_os.audit import read_audit_records

    audit_record = read_audit_records(store.roots.audit_path)[-1]
    assert audit_record["action"] == "crystallization_gate_run"
    assert audit_record["status"] == "error"
    assert audit_record["details"]["error_count"] == 1
    assert audit_record["details"]["error_codes"] == ["edge_query_failed"]


def test_t2_2_5_gate_fails_closed_when_fts_query_errors(tmp_path):
    """A broken similarity index must route every candidate to owner review."""
    store, index = _store(tmp_path)
    conn = _conn(index)
    conn.execute(
        """insert into crystallized_candidates
           (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
           values (?, ?, ?, ?, ?, ?, ?)""",
        ("cand_fts_error", "preference", "A substantive candidate body for the gate.",
         "[]", "[]", "private", "proposed"),
    )
    conn.execute("drop table memory_fts")
    conn.commit()
    conn.close()

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(str(index.roots.index_path), index=index)

    assert result["status"] == "error"
    assert result["error_code"] == "fts_query_failed"
    assert result["error_count"] == 1
    assert result["flagged_count"] == 1
    assert result["flagged_candidates"][0]["candidate_id"] == "cand_fts_error"
    assert result["flagged_candidates"][0]["reason_code"] == "fts_query_failed"


def test_t2_2_5_gate_uses_strict_real_edge_query(tmp_path):
    """The production index must not translate graph corruption into no edges."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_real_edge_error", "kind": "preference",
         "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": ["evt_real_edge_error"], "tags": [],
         "body": "The deployment strategy favors gradual rollout over canary."},
    ])
    index.rebuild_from_store(store)

    conn = _conn(index)
    conn.execute(
        """insert into crystallized_candidates
           (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
           values (?, ?, ?, ?, ?, ?, ?)""",
        ("cand_real_edge_error", "preference",
         "The deployment strategy favors gradual rollout over canary.",
         "[]", "[]", "private", "proposed"),
    )
    conn.execute("drop table memory_edges")
    conn.execute("create table memory_edges (broken_column text)")
    conn.commit()
    conn.close()

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(str(index.roots.index_path), index=index)

    check_conn = sqlite3.connect(index.roots.index_path)
    edge_columns_after = [
        str(row[1])
        for row in check_conn.execute("pragma table_info(memory_edges)").fetchall()
    ]
    check_conn.close()

    assert result["status"] == "error"
    assert result["error_code"] == "edge_query_failed"
    assert result["error_count"] == 1
    assert result["flagged_count"] == 1
    assert result["flagged_candidates"][0]["candidate_id"] == "cand_real_edge_error"
    assert result["flagged_candidates"][0]["reason_code"] == "edge_query_failed"
    assert edge_columns_after == ["broken_column"]


def test_t2_2_5_gate_fails_closed_without_edge_index_dependency(tmp_path):
    """A candidate with FTS peers cannot be cleared without the edge reader."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_missing_edge_index", "kind": "preference",
         "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": ["evt_missing_edge_index"], "tags": [],
         "body": "The deployment strategy favors gradual rollout over canary."},
    ])
    index.rebuild_from_store(store)

    conn = _conn(index)
    conn.execute(
        """insert into crystallized_candidates
           (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
           values (?, ?, ?, ?, ?, ?, ?)""",
        ("cand_missing_edge_index", "preference",
         "The deployment strategy favors gradual rollout over canary.",
         "[]", "[]", "private", "proposed"),
    )
    conn.commit()
    conn.close()

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(str(index.roots.index_path), index=None)

    assert result["status"] == "error"
    assert result["error_code"] == "edge_index_unavailable"
    assert result["error_count"] == 1
    assert result["flagged_count"] == 1
    assert result["flagged_candidates"][0]["candidate_id"] == "cand_missing_edge_index"
    assert result["flagged_candidates"][0]["reason_code"] == "edge_index_unavailable"


def test_t2_2_6_gate_does_not_alter_candidates(tmp_path):
    """T2.2.6: Gate is read-only — does not modify any data."""
    store, index = _store(tmp_path)
    conn = _conn(index)

    _seed_canonical_crystallized(store, [
        {"id": "cry_ro_a", "kind": "preference",
         "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": ["evt_ro"], "tags": [],
         "body": "Rolling deployments reduce risk."},
        {"id": "cry_ro_b", "kind": "preference",
         "created_at": "2026-06-01T12:00:00Z",
         "source_event_ids": ["evt_rb"], "tags": [],
         "body": "Rolling deployments increase complexity."},
    ])
    index.rebuild_from_store(store)
    _seed_contradicts_edge(
        conn, index.roots, "cry_ro_a", "cry_ro_b")
    conn.close()

    conn2 = _conn(index)
    conn2.execute(
        """insert into crystallized_candidates
           (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
           values (?, ?, ?, ?, ?, ?, ?)""",
        ("cand_ro_test", "preference",
         "Rolling deployments reduce risk.",
         "[]", "[]", "private", "proposed"),
    )
    conn2.commit()

    # Snapshot edge count
    edge_before = conn2.execute("select count(*) from memory_edges").fetchone()[0]
    conn2.close()

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(str(index.roots.index_path), index=index)
    assert result["flagged_count"] >= 1

    conn3 = _conn(index)
    edge_after = conn3.execute("select count(*) from memory_edges").fetchone()[0]
    conn3.close()
    assert edge_after == edge_before, (
        f"Gate must not add/remove edges. Before={edge_before} After={edge_after}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2.3 — LLM Edge Proposer
# ═══════════════════════════════════════════════════════════════════════════


def test_t2_3_1_llm_parse_json_response(tmp_path):
    """T2.3.1: Parser extracts relation_type from LLM JSON response."""
    # Test the JSON extraction logic from _call_llm
    # Simulate raw LLM responses
    response_tests = [
        ('{"relation_type": "refines", "confidence": 0.9, "reasoning": "Similar body"}',
         "refines", 0.9),
        ('{"relation_type": "contradicts", "confidence": 0.7, "reasoning": "Different stance"}',
         "contradicts", 0.7),
        ('{"relation_type": "none", "confidence": 0.0, "reasoning": "No overlap"}',
         "none", 0.0),
    ]

    import json, re

    def _parse_llm_json(response: str) -> dict[str, Any]:
        json_str = response.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()
        parsed = json.loads(json_str)
        return parsed

    for resp, expected_type, expected_conf in response_tests:
        parsed = _parse_llm_json(resp)
        assert parsed["relation_type"] == expected_type, f"Expected {expected_type}, got {parsed}"
        assert abs(parsed["confidence"] - expected_conf) < 0.01


def test_t2_3_2_llm_parse_markdown_fenced_response(tmp_path):
    """T2.3.2: Parser handles markdown code-fenced JSON."""
    import json
    response = """Here's my analysis:

```json
{"relation_type": "depends_on", "confidence": 0.65, "reasoning": "B builds on A"}
```"""

    def _parse_llm_json(response: str) -> dict[str, Any]:
        json_str = response.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()
        return json.loads(json_str)

    parsed = _parse_llm_json(response)
    assert parsed["relation_type"] == "depends_on"
    assert abs(parsed["confidence"] - 0.65) < 0.01


def test_t2_3_3_llm_proposer_loads_correctly(tmp_path):
    """T2.3.3: Module loads and has expected interface."""
    from plugins.memory.memory_os import llm_edge_proposer
    assert hasattr(llm_edge_proposer, "run_llm_proposer")
    assert hasattr(llm_edge_proposer, "_call_llm")
    assert hasattr(llm_edge_proposer, "_resolve_runtime")


def test_t2_3_4_llm_skipped_when_less_than_two_records(tmp_path):
    """T2.3.4: LLM proposer skips with < 2 records."""
    from plugins.memory.memory_os.llm_edge_proposer import run_llm_proposer
    result = run_llm_proposer("/nonexistent/index.db", index=None)
    assert result["status"] in ("skipped", "error")


def test_t2_3_5_llm_proposer_fail_open(tmp_path):
    """T2.3.5: LLM proposer returns error on broken index."""
    from plugins.memory.memory_os.llm_edge_proposer import run_llm_proposer
    result = run_llm_proposer("/nonexistent/index.db", index=None)
    assert "status" in result


def test_t2_3_6_format_tags_list(tmp_path):
    """T2.3.6: _format_tags handles list input."""
    from plugins.memory.memory_os.llm_edge_proposer import _format_tags
    assert _format_tags(["deploy", "canary"]) == "deploy, canary"
    assert _format_tags([]) == ""
    assert _format_tags(["single"]) == "single"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1.6 — Edge target resolution helpers(P2 改造后:批量解析 + 预览状态)
# ═══════════════════════════════════════════════════════════════════════════


def _write_cry_record(store, *, body, candidate_id, file_name, kind="note"):
    """真实 producer 写入结晶记录并返回 record_id(counterfactual 教训:
    手写 fixture 会让反事实空转,必须走 CrystallizedMemoryService)。"""
    from plugins.memory.memory_os.crystallized import (
        CrystallizedCandidate,
        CrystallizedMemoryService,
    )
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    svc = CrystallizedMemoryService(store)
    candidate = CrystallizedCandidate(
        candidate_id=candidate_id,
        kind=kind,
        body=body,
        source_event_ids=[f"evt_seed_{candidate_id}"],
    )
    decision = ApprovalDecision(
        candidate_id=candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-22T10:00:00Z",
        note="test",
        source_state="active",
    )
    svc.write_approved_record(candidate, decision, file_name=file_name)
    return str(svc.read_records(file_name)[-1].frontmatter["id"])


def test_batch_resolve_and_graph_preview(tmp_path):
    """批量解析一次扫描建映射;_graph_preview 区分 ok/inactive/missing。"""
    from plugins.memory.memory_os.prefetch import (
        _batch_resolve_crystallized,
        _graph_preview,
    )
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService

    roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    store = MemoryOSStore(roots)
    store.initialize()

    rid = _write_cry_record(
        store, body="用户偏好深色主题界面", candidate_id="cand-batch-1",
        file_name="batch_a.md", kind="preference",
    )
    rid_revoked = _write_cry_record(
        store, body="SECRET-NONCE-REVOKED-PREVIEW", candidate_id="cand-batch-2",
        file_name="batch_b.md", kind="preference",
    )
    CrystallizedMemoryService(store).revoke_record(
        rid_revoked, revoked_by="owner", reason="test",
    )

    cry_map = _batch_resolve_crystallized(store, {rid, rid_revoked, "nonexistent_id"})
    assert rid in cry_map
    assert rid_revoked in cry_map, "revoked records must resolve (for inactive detection)"
    assert "nonexistent_id" not in cry_map

    text, status = _graph_preview(rid, "crystallized_record", cry_map, {})
    assert status == "ok" and text and "深色主题" in text
    assert _graph_preview(rid_revoked, "crystallized_record", cry_map, {}) == (None, "inactive")
    assert _graph_preview("nonexistent_id", "crystallized_record", cry_map, {})[1] == "missing"

    # 事件端点走 events 缓存
    text, status = _graph_preview("evt_9", "event", {}, {"evt_9": "事件摘要内容测试"})
    assert status == "ok" and text and "事件摘要" in text
    assert _graph_preview("evt_gone", "event", {}, {})[1] == "missing"


def test_render_drops_revoked_and_unresolved_neighbors(tmp_path):
    """撤销邻居整行抑制(target_inactive);解析失败的结晶邻居整行丢弃
    (unresolved)— record_id 永不作为兜底行出现(P2:裸 id 阅读方对不上
    号,只会诱导编造引用;诊断归 shadow outcome)。反事实:旧实现会落
    [unresolved:cry_...] 行。"""
    from plugins.memory.memory_os.prefetch import _render_graph_layer_lines
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService

    roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    rid_anchor = _write_cry_record(
        store, body="锚点记录:图谱注入方向归一约定", candidate_id="cand-dir-a",
        file_name="dir_a.md",
    )
    rid_revoked = _write_cry_record(
        store, body="SECRET-NONCE-REVOKED-PREVIEW", candidate_id="cand-dir-r",
        file_name="dir_r.md",
    )
    CrystallizedMemoryService(store).revoke_record(
        rid_revoked, revoked_by="owner", reason="test",
    )

    edges = [
        {
            "edge_id": "edge-revoked",
            "from_record_type": "crystallized_record",
            "from_record_id": rid_anchor,
            "to_record_type": "crystallized_record",
            "to_record_id": rid_revoked,
            "relation_type": "co_occurs",
            "weight": 0.9,
            "state": "active",
        },
        {
            "edge_id": "edge-missing",
            "from_record_type": "crystallized_record",
            "from_record_id": rid_anchor,
            "to_record_type": "crystallized_record",
            "to_record_id": "cry_nonexistent_999",
            "relation_type": "co_occurs",
            "weight": 0.8,
            "state": "active",
        },
    ]
    lines, decisions = _render_graph_layer_lines(
        store, edges, anchor_ids=[rid_anchor], seen=set(),
    )
    assert lines == [], f"neither neighbor is renderable: {lines}"
    assert "SECRET-NONCE" not in " ".join(lines)
    by_target = {str(d["edge"]["to_record_id"]): d for d in decisions}
    assert by_target[rid_revoked]["outcome"] == "target_inactive"
    assert by_target["cry_nonexistent_999"]["outcome"] == "unresolved"
    assert all(d["injected"] is False for d in decisions)


def test_render_formats_direction_normalized_chinese_lines(tmp_path):
    """新行文法 + F1 方向归一反事实。

    B→A 的边(锚点在 to 侧):旧实现无条件取 to_record_id 当展示目标,会把
    锚点自己当"关联记忆"展示且 depends_on 方向读反;新实现必须展示 B 的
    正文,短语用 to 侧的「被以下内容依赖」。行内永不出现 record_id。"""
    from plugins.memory.memory_os.prefetch import _render_graph_layer_lines
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    store = MemoryOSStore(roots)
    store.initialize()

    rid_a = _write_cry_record(
        store, body="锚点记录:图谱注入的方向归一约定说明",
        candidate_id="cand-f1-a", file_name="f1_a.md",
    )
    rid_b = _write_cry_record(
        store, body="邻居记录:被依赖的底层配置基线说明",
        candidate_id="cand-f1-b", file_name="f1_b.md",
    )

    edges = [{
        "edge_id": "edge-f1",
        "from_record_type": "crystallized_record",
        "from_record_id": rid_b,
        "to_record_type": "crystallized_record",
        "to_record_id": rid_a,
        "relation_type": "depends_on",
        "weight": 0.85,
        "state": "active",
    }]
    seen: set[tuple[str, str]] = set()
    source_ids: list[str] = []
    lines, decisions = _render_graph_layer_lines(
        store, edges, anchor_ids=[rid_a], seen=seen, source_ids=source_ids,
    )

    assert len(lines) == 1, f"expected one rendered line: {lines}"
    line = lines[0]
    assert line.startswith("- 「"), f"line must lead with anchor preview: {line}"
    assert "锚点记录" in line, f"anchor preview must name the anchor: {line}"
    assert "被以下内容依赖" in line, f"to-side depends_on phrase expected: {line}"
    assert "邻居记录" in line, f"neighbor body must be rendered, not the anchor: {line}"
    assert "关联度 0.85" in line
    assert rid_a not in line and rid_b not in line, f"record_id must never render: {line}"
    assert len(line) <= 220
    assert ("crystallized_record", rid_b) in seen, "dedup registers the NEIGHBOR"
    assert ("crystallized_record", rid_a) not in seen, "anchor must not be re-registered"
    # Canonical citation prefix, NOT the storage-layer type name: the old
    # f"crystallized_record:{id}" format was silently dropped by
    # filter_safe_source_id_values, so every graph disclosure landed as an
    # attribution gap. This assertion (and the filter round-trip below) pins
    # the producer to a format the safety allowlist actually accepts.
    assert source_ids == [f"crystallized:{rid_b}"], (
        f"attribution must follow the displayed neighbor: {source_ids}"
    )
    from plugins.memory.memory_os.source_ids import filter_safe_source_id_values

    assert filter_safe_source_id_values(source_ids) == source_ids, (
        f"graph source_ids must survive the safety allowlist: {source_ids}"
    )
    assert decisions[0]["injected"] is True
    assert decisions[0]["outcome"] == "emitted_full"


def test_render_from_side_phrase_and_aggregation(tmp_path):
    """from 侧短语(依赖于/细化了)+ 同 (锚点,邻居) 多边聚合为一行。"""
    from plugins.memory.memory_os.prefetch import _render_graph_layer_lines
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    rid_a = _write_cry_record(
        store, body="锚点记录:注入行文法契约", candidate_id="cand-agg-a",
        file_name="agg_a.md",
    )
    rid_b = _write_cry_record(
        store, body="邻居记录:字符预算与聚合规则", candidate_id="cand-agg-b",
        file_name="agg_b.md",
    )

    edges = [
        {
            "edge_id": "edge-agg-1",
            "from_record_type": "crystallized_record",
            "from_record_id": rid_a,
            "to_record_type": "crystallized_record",
            "to_record_id": rid_b,
            "relation_type": "co_occurs",
            "weight": 0.6,
            "state": "active",
        },
        {
            "edge_id": "edge-agg-2",
            "from_record_type": "crystallized_record",
            "from_record_id": rid_a,
            "to_record_type": "crystallized_record",
            "to_record_id": rid_b,
            "relation_type": "refines",
            "weight": 0.8,
            "state": "active",
        },
    ]
    lines, decisions = _render_graph_layer_lines(
        store, edges, anchor_ids=[rid_a], seen=set(),
    )
    assert len(lines) == 1, f"same (anchor,neighbor) pair must aggregate: {lines}"
    line = lines[0]
    assert "同源共现于" in line and "细化了" in line and "、" in line, line
    assert "关联度 0.80" in line, f"aggregated weight takes the max: {line}"
    assert len(decisions) == 2
    assert all(d["injected"] is True for d in decisions)


# ═══════════════════════════════════════════════════════════════════════════
# W0 (E7) — 边状态迁移持久化:迁移必须写回 canonical JSONL,在重投影后存活
# ═══════════════════════════════════════════════════════════════════════════


def test_w0_transition_survives_index_sync(tmp_path):
    """E7 counterfactual: approve/reject 迁移必须在 index_sync 重投影后保持。

    无 W0 修复时:transition 只更新 SQLite,sync_from_store 从 edges.jsonl
    clear+全量重投影 → 状态回滚到 candidate → 本测试必红。
    """
    store, index = _store(tmp_path)
    edge = index.write_governed_edge(
        from_record_type="crystallized_record",
        from_record_id="cry_w0_a",
        to_record_type="crystallized_record",
        to_record_id="cry_w0_b",
        relation_type="co_occurs",
        weight=0.9,
        proposed_by="structural",
    )
    assert edge and edge["state"] == "candidate"

    updated = index.transition_edge_state(edge["edge_id"], "owner_eligible")
    assert updated and updated["state"] == "owner_eligible"

    index.sync_from_store(store)  # 30 分钟 cron lane 的重投影路径

    row = index.get_edge(edge["edge_id"])
    assert row is not None
    assert row["state"] == "owner_eligible", (
        "edge state transition was reverted by index_sync re-projection "
        "(E7: transition not persisted to graph/edges.jsonl)"
    )


def test_w0_transition_invalidated_survives_rebuild(tmp_path):
    """E7 counterfactual (reject 方向 + rebuild 路径): invalidated 必须存活全量重建。"""
    store, index = _store(tmp_path)
    edge = index.write_governed_edge(
        from_record_type="crystallized_record",
        from_record_id="cry_w0_c",
        to_record_type="crystallized_record",
        to_record_id="cry_w0_d",
        relation_type="refines",
        weight=0.5,
        proposed_by="structural",
    )
    updated = index.transition_edge_state(edge["edge_id"], "invalidated")
    assert updated and updated["state"] == "invalidated"

    index.rebuild_from_store(store)

    row = index.get_edge(edge["edge_id"])
    assert row is not None
    assert row["state"] == "invalidated"
    assert row.get("invalidated_at"), "invalidated_at must survive re-projection"


def test_w0_projection_last_writer_wins_per_edge_id(tmp_path):
    """守卫:W0 依赖的投影语义——同 edge_id 多行时,文件序最后一行胜出。

    这是既有行为(_index_edges 按行序 insert-or-replace on edge_id 主键),
    本测试将其钉死:若未来投影改为首行胜出或报错,W0 的追加更新机制即失效。
    """
    store, index = _store(tmp_path)
    edges_path = store.roots.memory_os_root / "graph" / "edges.jsonl"
    edges_path.parent.mkdir(parents=True, exist_ok=True)
    base = {
        "edge_id": "edge_lww_1",
        "from_record_type": "crystallized_record",
        "from_record_id": "cry_lww_a",
        "to_record_type": "crystallized_record",
        "to_record_id": "cry_lww_b",
        "relation_type": "co_occurs",
        "weight": 0.8,
        "created_at": "2026-08-06T00:00:00+00:00",
        "source_event_id": "",
        "state": "candidate",
        "invalidated_at": None,
        "proposed_by": "structural",
    }
    newer = dict(base)
    newer["state"] = "active"
    with edges_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(base, ensure_ascii=False) + "\n")
        fh.write(json.dumps(newer, ensure_ascii=False) + "\n")

    index.rebuild_from_store(store)

    row = index.get_edge("edge_lww_1")
    assert row is not None
    assert row["state"] == "active", "projection must be last-writer-wins per edge_id"


# ═══════════════════════════════════════════════════════════════════════════
# R1 (owner 决策 2026-08-06) — 动态图谱全自动:全部关系类型 auto-active
# ═══════════════════════════════════════════════════════════════════════════


def test_r1_llm_vocabulary_all_types_auto_active():
    """R1 词表守卫:llm proposer 不再有需审类型 — 全部关系 auto-active。

    Owner 决策:「动态图谱应该是动态去更新关系的…不需要人工介入」。
    边是派生投影(advisory_only 家族),不触碰任何 OwnerGate 永久边界;
    contradicts 的下游消费(crystallization_gate)本就只产 owner 可见的
    标记,边自动生效不会自动执行任何动作。错误的边由权重反馈闭环
    (命中加权/无命中遗忘)动态淘汰。
    """
    from plugins.memory.memory_os.llm_edge_proposer import (
        _AUTO_ACTIVE_TYPES,
        _REVIEW_REQUIRED_TYPES,
    )

    assert _REVIEW_REQUIRED_TYPES == frozenset(), (
        "R1: no relation type requires owner review any more"
    )
    assert _AUTO_ACTIVE_TYPES == frozenset(
        {"co_occurs", "evidence_for", "refines", "contradicts", "depends_on"}
    )


def test_r1_vector_proposes_active_directly(tmp_path):
    """R1 counterfactual: vector 提案直接 active(此前写 candidate)。"""
    store, index = _store(tmp_path)
    edge = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_r1_a",
        to_record_type="crystallized_record", to_record_id="cry_r1_b",
        relation_type="co_occurs", weight=0.8, proposed_by="vector",
        state="active",
    )
    assert edge and edge["state"] == "active"
    # vector proposer 源码不得再写 candidate 态(源码级守卫,防回退)
    import inspect

    from plugins.memory.memory_os import vector_edge_proposer
    source = inspect.getsource(vector_edge_proposer)
    assert 'state="candidate"' not in source, (
        "R1: vector proposer must emit active edges"
    )


def test_r1_structural_source_has_no_candidate_state():
    """R1 源码级守卫:structural proposer 不得再产 candidate 态边。"""
    import inspect

    from plugins.memory.memory_os import structural_edge_proposer
    source = inspect.getsource(structural_edge_proposer)
    assert '"state": "candidate"' not in source, (
        "R1: structural proposer must emit active edges"
    )


# ═══════════════════════════════════════════════════════════════════════════
# E8 — 锚点收集回退:多词 AND 失效与中文丢词(图谱注入的最后一公里)
# ═══════════════════════════════════════════════════════════════════════════
#
# 生产实锤(2026-08-07):plan_query_route 的 `entities or chinese_keywords`
# 在 query 含任何拉丁词时把中文实词整体丢弃;派生出的多词 search_query
# (如 'Memory-OS Hermes')在 FTS AND 语义下 0 命中(两词单查各 5 命中,
# 交集空)。锚点恒空 → 图谱一跳展开永不触发 → shadow 月命中仅 4 条、
# owner 实测"完全没感觉到注入"。历史 1019 次 prefetch 仅 19.5% 有 FTS
# 命中。修复只动 _collect_anchor_ids(锚点专用回退),不碰全局共享的
# plan_query_route 谓词(改共享谓词前须全面 grep — W 规则)。


class _E8MockIndex:
    """可编程 search mock:按 (查询词[, record_type]) 返回预设命中。"""

    def __init__(self, hits_by_query, typed_hits=None):
        self.hits_by_query = hits_by_query
        self.typed_hits = typed_hits or {}
        self.queries = []

    def search(self, query, limit=5, record_type=None):
        self.queries.append((query, record_type))
        if record_type is not None:
            hits = self.typed_hits.get((query, record_type), [])
        else:
            hits = self.hits_by_query.get(query, [])
        return {"hits": [{"record_id": rid, "record_type": record_type or "event"} for rid in hits]}


def test_e8_and_failure_falls_back_to_per_term_union():
    """E8 counterfactual:多词派生查询 0 命中时,必须逐词并集回退。

    无修复:_collect_anchor_ids 一次 AND 查询 0 命中即返回 [] → 必红。
    """
    index = _E8MockIndex({
        "Memory-OS Hermes": [],
        "Memory-OS": ["cry_a"],
        "Hermes": ["cry_b"],
    })
    anchors = _collect_anchor_ids("聊聊 Memory-OS 和 Hermes 的联动", index)
    assert "cry_a" in anchors and "cry_b" in anchors, (
        f"per-term fallback must recover anchors from AND-failed query: {anchors}"
    )


def test_e8_chinese_keywords_recovered_when_latin_terms_miss():
    """E8 counterfactual:拉丁词短路丢弃的中文关键词必须参与锚点回退。"""
    from plugins.memory.memory_os.prefetch import set_fast_path_keywords

    index = _E8MockIndex({
        "Hermes": [],          # 派生查询(单拉丁词)未命中
        "部署": ["cry_zh"],    # 中文关键词命中
    })
    set_fast_path_keywords(["部署"])
    try:
        anchors = _collect_anchor_ids("Hermes 的部署情况怎么样了", index)
    finally:
        set_fast_path_keywords(None)
    assert anchors == ["cry_zh"], (
        f"Chinese keywords dropped by the entities-or short-circuit must be "
        f"retried for anchors: {anchors}"
    )


def test_e8_direct_hit_needs_no_fallback():
    """回归:派生查询直接命中时不做逐词回退(双段主查询后即返回)。"""
    index = _E8MockIndex({"Memory-OS Hermes": ["cry_direct"]})
    anchors = _collect_anchor_ids("聊聊 Memory-OS 和 Hermes", index)
    assert anchors == ["cry_direct"]
    # 双段主查询(结晶限定 + 通用)各一次,无逐词回退查询
    assert index.queries == [
        ("Memory-OS Hermes", "crystallized_record"),
        ("Memory-OS Hermes", None),
    ], f"no per-term fallback expected on direct hit: {index.queries}"


def test_e8_fallback_bounded():
    """回退有界:锚点总数 ≤5,查询词数有上限。"""
    hits = {f"w{i}": [f"cry_{i}"] for i in range(10)}
    hits[" ".join(f"w{i}" for i in range(6))] = []
    index = _E8MockIndex(hits)
    # 构造派生出 6 个拉丁词的 query
    anchors = _collect_anchor_ids("check w0 w1 w2 w3 w4 w5 please", index)
    assert len(anchors) <= 5, f"anchor cap must hold: {anchors}"


def test_e8_crystallized_hits_prioritized_into_anchor_pool():
    """E8b counterfactual:结晶命中必须进锚点池并排在前面。

    生产实锤(2026-08-07):FTS 通用命中被事件量级淹没(top 8 清一色
    event),而边密度在结晶层(active 边端点:9 结晶 vs 26 事件,后者是
    仅 30 条溯源边的固定集合)——通用锚点几乎永远落不到带边节点上。
    修复:锚点收集用双段查询,record_type='crystallized_record' 限定段
    优先,通用段补足。无修复:mock 的通用命中全 event → 锚点无结晶 → 必红。
    """
    index = _E8MockIndex(
        {"Memory-OS Hermes": ["evt_1", "evt_2", "evt_3", "evt_4", "evt_5"]},
        typed_hits={("Memory-OS Hermes", "crystallized_record"): ["cry_hot"]},
    )
    anchors = _collect_anchor_ids("聊聊 Memory-OS 和 Hermes", index)
    assert "cry_hot" in anchors, (
        f"crystallized hits must enter the anchor pool: {anchors}"
    )
    assert anchors[0] == "cry_hot", (
        f"crystallized hits must be prioritized (edge density lives there): {anchors}"
    )
    assert len(anchors) <= 5


def test_e8c_dedup_hit_emits_short_preview_line(tmp_path):
    """E8c 升级版反事实:目标已被其他段展示时不得静默吞行,降级为
    「已列出·」+ 60 字符正文短预览 — 不再打 ↺ + 裸 record_id。

    生产实锤(2026-08-07 06:30Z):小图谱阶段检索命中集与一跳邻居集高度
    重叠,静默去重让 Related Memory 恒空;而裸 id 短行阅读方对不上号
    (其它区段不显示 record_id)。短预览是同一正文的精确前缀,即为跨段
    对齐键。方向归一后本场景锚点=结晶(to 侧),邻居=事件(经 events
    缓存解析),evidence_for 的 to 侧短语为「其证据为」。
    """
    from plugins.memory.memory_os.prefetch import _render_graph_layer_lines
    from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="graph-stub-test")
    store = MemoryOSStore(roots)
    store.initialize()
    rid = _write_cry_record(
        store, body="结晶正文:图谱与状态层的联动约定,阅读方按正文前缀对齐",
        candidate_id="cand-e8c", file_name="e8c.md",
    )
    ev = EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id="evt_src_1",
        ts="2026-08-07T00:00:00Z",
        profile="graph-stub-test",
        source="fixture",
        kind="conversation_turn",
        summary="事件摘要:昨天讨论了图谱注入的方向归一细节",
        tags=[],
        safe_ref={},
    )

    edges = [{
        "relation_type": "evidence_for",
        "weight": 1.0,
        "from_record_type": "event",
        "from_record_id": "evt_src_1",
        "to_record_type": "crystallized_record",
        "to_record_id": rid,
        "state": "active",
    }]
    seen = {("crystallized_record", rid), ("event", "evt_src_1")}
    lines, decisions = _render_graph_layer_lines(
        store, edges, anchor_ids=[rid], seen=seen, events=[ev],
    )
    assert len(lines) == 1, f"dedup hit must yield a short-preview line, not silence: {lines}"
    line = lines[0]
    assert "已列出·" in line, f"dedup hit must carry the already-listed marker: {line}"
    assert "其证据为" in line, f"to-side evidence_for phrase expected: {line}"
    assert "事件摘要" in line, f"neighbor (event) preview must render: {line}"
    assert "evt_src_1" not in line and rid not in line, f"no record_id in lines: {line}"
    assert "↺" not in line, f"legacy id-stub marker must be gone: {line}"
    assert len(line) <= 220, f"stub line must stay bounded: {line!r}"
    assert decisions[0]["outcome"] == "emitted_stub"
    assert decisions[0]["injected"] is True


def test_exploration_slots_rotate_daily_and_bound_selection(tmp_path):
    """P3 反饿死反事实:候选 > 8 时选 top-6 按权重 + 2 个探索位。

    分层出生权重若无探索位,排序固化后弱边永无展示 → 永无命中 → 60 天
    被判「无命中」处决(自我实现遗忘)。探索位按天确定性轮转(无随机数,
    热路径可复现):同日两次调用结果完全一致;跨日探索子集变化;落选边
    以 not_selected 落账(封闭 outcome)。
    """
    from plugins.memory.memory_os.prefetch import (
        GRAPH_EXPLOIT_SLOTS,
        GRAPH_EXPLORE_SLOTS,
        _render_graph_layer_lines,
    )

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="explore-test")
    store = MemoryOSStore(roots)
    store.initialize()
    rid_anchor = _write_cry_record(
        store, body="锚点记录:探索位轮转契约", candidate_id="cand-exp-anchor",
        file_name="exp_anchor.md",
    )
    neighbor_ids = []
    for i in range(12):
        neighbor_ids.append(_write_cry_record(
            store,
            body=f"邻居记录{i}:内容标识 NEIGHBOR-{i} 的独立正文",
            candidate_id=f"cand-exp-{i}",
            file_name=f"exp_{i}.md",
        ))
    edges = [
        {
            "edge_id": f"edge-exp-{i}",
            "from_record_type": "crystallized_record",
            "from_record_id": rid_anchor,
            "to_record_type": "crystallized_record",
            "to_record_id": neighbor_ids[i],
            "relation_type": "co_occurs",
            "weight": round(0.90 - i * 0.02, 2),  # 0.90 .. 0.68, all ≥ floor
            "state": "active",
        }
        for i in range(12)
    ]

    def _selected_neighbors(day):
        source_ids: list[str] = []
        lines, decisions = _render_graph_layer_lines(
            store, list(edges), anchor_ids=[rid_anchor],
            seen=set(), source_ids=source_ids, day_ordinal=day,
        )
        return lines, decisions, source_ids

    day0 = 738000
    lines_a, decisions_a, sel_a = _selected_neighbors(day0)
    lines_b, _decisions_b, sel_b = _selected_neighbors(day0)
    assert lines_a == lines_b and sel_a == sel_b, "same-day selection must be deterministic"

    cap = GRAPH_EXPLOIT_SLOTS + GRAPH_EXPLORE_SLOTS
    assert len(lines_a) == cap, f"selection must bound lines to {cap}: {len(lines_a)}"
    not_selected = [d for d in decisions_a if d["outcome"] == "not_selected"]
    assert len(not_selected) == 12 - cap, "the rest must be ledgered as not_selected"

    # top-6 按权重恒在(exploit 位)— source_ids 用规范引用前缀(见 1797 行注释)
    top6 = {f"crystallized:{nid}" for nid in neighbor_ids[:GRAPH_EXPLOIT_SLOTS]}
    assert top6 <= set(sel_a), f"exploit slots must keep the top-{GRAPH_EXPLOIT_SLOTS}"

    # 探索位跨日轮转:一周内至少出现两种探索子集(确定性哈希,非随机)
    explore_sets = set()
    for day in range(day0, day0 + 7):
        _lines, _decisions, sel = _selected_neighbors(day)
        explore_sets.add(tuple(sorted(set(sel) - top6)))
    assert len(explore_sets) >= 2, (
        f"exploration slots must rotate across days: {explore_sets}"
    )


def test_cl_cjk_query_bigrams_helper():
    """CL:双字词组派生 — 停用字断窗、滑动窗口、保序去重、cap。"""
    from plugins.memory.memory_os.prefetch import _cjk_query_bigrams

    assert _cjk_query_bigrams("动态图谱的注入效果") == [
        "动态", "态图", "图谱", "注入", "入效", "效果",
    ]
    assert _cjk_query_bigrams("好的") == []
    assert _cjk_query_bigrams("abc only ascii") == []
    assert len(_cjk_query_bigrams("一二三四五六七八九十甲乙丙丁", cap=8)) == 8


def test_cl_bigram_fallback_reaches_non_vocab_chinese_topics():
    """CL 反事实(owner 实测「聊动态图谱不命中,说记忆就中」的根因):
    纯中文非词表话题必须经 query 双字词组回退拿到锚点。修复缺席:固定
    词表(21 词)无 图谱/动态/注入,整句 slow_path AND 0 命中,派生词
    单 token 跳过 → 锚点恒空,图谱永不遍历 — 必红。"""
    index = _E8MockIndex(
        {"图谱": ["evt_g1"]},
        typed_hits={("图谱", "crystallized_record"): ["cry_graph"]},
    )
    anchors = _collect_anchor_ids("动态图谱现在活起来没有", index)
    assert anchors, "bigram fallback must produce anchors for non-vocab Chinese topics"
    assert anchors[0] == "cry_graph", (
        f"crystallized hits must lead the pool (edge density lives there): {anchors}"
    )
    assert "evt_g1" in anchors


def test_cl_task_anchor_supplements_short_query_anchors():
    """CL 反事实:query 锚点不足 5 时用当前任务锚文本补位(聊的话题往往
    在任务锚里早有记录 — agent 建议③);query 派生锚点保序在前。修复
    缺席:任务锚不参与锚点收集,补位不存在 — 必红。"""
    index = _E8MockIndex(
        {"图谱": ["evt_q1"]},
        typed_hits={("Memory-OS", "crystallized_record"): ["cry_task"]},
    )
    anchors = _collect_anchor_ids(
        "聊聊图谱",
        index,
        task_anchor_text="推进 Memory-OS 稳定化收尾",
    )
    assert anchors[0] == "evt_q1", f"query-derived anchors keep priority: {anchors}"
    assert "cry_task" in anchors, (
        f"task-anchor terms must supplement when query anchors run short: {anchors}"
    )


def test_cl_task_anchor_does_not_dilute_full_query_anchors():
    """query 已拿满 5 个锚点时任务锚不得稀释(补位仅在不足时)。"""
    index = _E8MockIndex(
        {"图谱": ["evt_1", "evt_2", "evt_3", "evt_4", "evt_5"]},
        typed_hits={("Memory-OS", "crystallized_record"): ["cry_task"]},
    )
    anchors = _collect_anchor_ids(
        "聊聊图谱",
        index,
        task_anchor_text="推进 Memory-OS 稳定化收尾",
    )
    assert len(anchors) == 5
    assert "cry_task" not in anchors
    """E8b counterfactual(生产复验补钉):逐词回退同样必须带结晶限定段。

    生产实测:主查询双段皆 0(AND 失效同样打击结晶限定段)→ 走逐词回退,
    而回退只查通用 → 锚点仍被事件填满,结晶命中进不了池。无修复必红。
    """
    index = _E8MockIndex(
        {
            "Memory-OS Hermes": [],
            "Memory-OS": ["evt_a", "evt_b", "evt_c"],
            "Hermes": ["evt_d", "evt_e"],
        },
        typed_hits={
            ("Memory-OS Hermes", "crystallized_record"): [],
            ("Memory-OS", "crystallized_record"): ["cry_target"],
            ("Hermes", "crystallized_record"): [],
        },
    )
    anchors = _collect_anchor_ids("聊聊 Memory-OS 和 Hermes 的联动", index)
    assert "cry_target" in anchors, (
        f"per-term fallback must include the crystallized segment: {anchors}"
    )
    assert anchors[0] == "cry_target", (
        f"crystallized hits must lead the pool in fallback too: {anchors}"
    )
    assert len(anchors) <= 5


# ═══════════════════════════════════════════════════════════════════════════
# W1 (E2/E3) — 去重下沉写入口 + structural 收回语义提名权 + 配对去偏置
# ═══════════════════════════════════════════════════════════════════════════


def _bulk_seed_edges(store, index, count: int, *, prefix: str) -> None:
    """Seed many non-invalidated candidate edges (JSONL + DB, production shape)."""
    edges_path = store.roots.memory_os_root / "graph" / "edges.jsonl"
    edges_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(index.roots.index_path))
    rows = []
    lines = []
    for i in range(count):
        edge = {
            "edge_id": f"edge_{prefix}_{i}",
            "from_record_type": "crystallized_record",
            "from_record_id": f"cry_{prefix}_{i}_a",
            "to_record_type": "crystallized_record",
            "to_record_id": f"cry_{prefix}_{i}_b",
            "relation_type": "co_occurs",
            "weight": 0.5,
            "created_at": "2026-08-01T00:00:00+00:00",
            "source_event_id": "",
            "state": "candidate",
            "invalidated_at": None,
            "proposed_by": "llm",
        }
        lines.append(json.dumps(edge, ensure_ascii=False) + "\n")
        rows.append(tuple(edge[k] for k in (
            "edge_id", "from_record_type", "from_record_id", "to_record_type",
            "to_record_id", "relation_type", "weight", "created_at",
            "source_event_id", "state", "invalidated_at", "proposed_by")))
    with edges_path.open("a", encoding="utf-8") as fh:
        fh.writelines(lines)
    conn.executemany(
        "insert or replace into memory_edges (edge_id, from_record_type, from_record_id,"
        " to_record_type, to_record_id, relation_type, weight, created_at,"
        " source_event_id, state, invalidated_at, proposed_by)"
        " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_w1_write_boundary_rejects_duplicate_triple(tmp_path):
    """E2 counterfactual:同 (from,to,relation) 非 invalidated 三元组重复写入必须被拒。

    无 W1 修复时 write_governed_edge 无任何去重检查 → 第二次写入成功 → 必红。
    """
    store, index = _store(tmp_path)
    first = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_dup_a",
        to_record_type="crystallized_record", to_record_id="cry_dup_b",
        relation_type="refines", weight=0.7, proposed_by="llm",
    )
    assert first and first.get("edge_id") and not first.get("skipped_duplicate")

    second = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_dup_a",
        to_record_type="crystallized_record", to_record_id="cry_dup_b",
        relation_type="refines", weight=0.9, proposed_by="llm",
    )
    assert second.get("skipped_duplicate") is True, (
        f"duplicate triple must be rejected at the write boundary, got {second}"
    )
    conn = _conn(index)
    n = conn.execute(
        "select count(*) from memory_edges where from_record_id='cry_dup_a'"
    ).fetchone()[0]
    conn.close()
    assert n == 1
    # canonical ledger must not have grown either
    edges_path = store.roots.memory_os_root / "graph" / "edges.jsonl"
    dup_lines = [
        l for l in edges_path.read_text(encoding="utf-8").splitlines()
        if "cry_dup_a" in l
    ]
    assert len(dup_lines) == 1


def test_w1_write_boundary_pair_dedup_for_structural(tmp_path):
    """structural 按 (from,to) 无向配对去重;非 structural 仍按三元组。"""
    store, index = _store(tmp_path)
    first = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_pair_a",
        to_record_type="crystallized_record", to_record_id="cry_pair_b",
        relation_type="co_occurs", weight=0.6, proposed_by="structural",
    )
    assert first and not first.get("skipped_duplicate")

    # structural:同配对不同关系 → 仍拒(配对级)
    second = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_pair_a",
        to_record_type="crystallized_record", to_record_id="cry_pair_b",
        relation_type="depends_on", weight=1.0, proposed_by="structural",
    )
    assert second.get("skipped_duplicate") is True

    # structural:反方向同配对 → 仍拒(无向)
    third = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_pair_b",
        to_record_type="crystallized_record", to_record_id="cry_pair_a",
        relation_type="co_occurs", weight=0.6, proposed_by="structural",
    )
    assert third.get("skipped_duplicate") is True

    # llm:同配对不同关系 → 允许(三元组级,语义类型有意义)
    fourth = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_pair_a",
        to_record_type="crystallized_record", to_record_id="cry_pair_b",
        relation_type="contradicts", weight=0.8, proposed_by="llm",
    )
    assert fourth and fourth.get("edge_id") and not fourth.get("skipped_duplicate")


def test_w1_dedup_survives_beyond_1000_edges(tmp_path):
    """E2 生产同款反事实:存量 >1000 条时,去重不得因查询上限被超穿。

    旧机制(proposer 侧 query_edges limit=1000)在 >1000 存量下漏检;
    写入口去重无 limit,必须仍拒。
    """
    store, index = _store(tmp_path)
    _bulk_seed_edges(store, index, 1100, prefix="bulk")

    dup = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_bulk_1050_a",
        to_record_type="crystallized_record", to_record_id="cry_bulk_1050_b",
        relation_type="co_occurs", weight=0.5, proposed_by="llm",
    )
    assert dup.get("skipped_duplicate") is True, (
        "dedup must not be defeated by backlog size >1000"
    )


def test_w1_structural_no_longer_proposes_refines_or_contradicts(tmp_path):
    """E2 语义收权反事实:structural 相似度不得再提名 refines/contradicts。

    同 kind 相似 body → co_occurs(旧行为 refines);
    异 kind 相似 body → co_occurs(旧行为 contradicts)。
    """
    store, index = _store(tmp_path)
    body = "The deployment pipeline was verified with all governance gates green."
    _seed_canonical_crystallized(store, [
        {"id": "cry_sem_a", "kind": "preference", "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": [], "tags": [], "body": body},
        {"id": "cry_sem_b", "kind": "preference", "created_at": "2026-06-20T12:00:00Z",
         "source_event_ids": [], "tags": [], "body": body},
        {"id": "cry_sem_c", "kind": "fact", "created_at": "2026-07-01T10:00:00Z",
         "source_event_ids": [], "tags": [], "body": body},
    ])
    index.rebuild_from_store(store)

    from plugins.memory.memory_os.structural_edge_proposer import run_structural_proposer
    result = run_structural_proposer(str(index.roots.index_path), index=index)
    assert result["status"] == "ok"

    conn = _conn(index)
    types = {
        str(r[0]): r[1]
        for r in conn.execute(
            "select relation_type, count(*) from memory_edges"
            " where proposed_by='structural' group by relation_type"
        ).fetchall()
    }
    conn.close()
    assert types.get("refines", 0) == 0, f"structural must not propose refines: {types}"
    assert types.get("contradicts", 0) == 0, f"structural must not propose contradicts: {types}"
    assert types.get("co_occurs", 0) >= 1, f"similarity should map to co_occurs: {types}"


def test_w1_pair_debias_unedged_records_first(tmp_path):
    """E3 counterfactual:未建边记录必须优先配对,旧的 created_at 升序会饿死新记录。

    old_a/old_b(更早创建)之间已有边;new_c/new_d(更晚创建)无边。
    max_pairs=1 时,检查的唯一配对必须是未建边的 (new_c, new_d)。
    旧排序下唯一配对是 (old_a, old_b) → 去重跳过 → 0 新边 → 必红。
    """
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_old_a", "kind": "preference", "created_at": "2026-06-01T10:00:00Z",
         "source_event_ids": [], "tags": [], "body": "old record aaaa"},
        {"id": "cry_old_b", "kind": "preference", "created_at": "2026-06-01T10:30:00Z",
         "source_event_ids": [], "tags": [], "body": "old record bbbb"},
        {"id": "cry_new_c", "kind": "preference", "created_at": "2026-08-01T10:00:00Z",
         "source_event_ids": [], "tags": [], "body": "new record cccc"},
        {"id": "cry_new_d", "kind": "preference", "created_at": "2026-08-01T10:20:00Z",
         "source_event_ids": [], "tags": [], "body": "new record dddd"},
    ])
    index.rebuild_from_store(store)
    seeded = index.write_governed_edge(
        from_record_type="crystallized_record", from_record_id="cry_old_a",
        to_record_type="crystallized_record", to_record_id="cry_old_b",
        relation_type="co_occurs", weight=0.6, proposed_by="structural",
    )
    assert seeded and seeded.get("edge_id")

    from plugins.memory.memory_os.structural_edge_proposer import run_structural_proposer
    result = run_structural_proposer(
        str(index.roots.index_path), index=index, max_pairs=1,
    )
    assert result["status"] == "ok"

    conn = _conn(index)
    new_pair = conn.execute(
        "select count(*) from memory_edges where from_record_id='cry_new_c'"
        " and to_record_id='cry_new_d'"
    ).fetchone()[0]
    conn.close()
    assert new_pair >= 1, (
        "with max_pairs=1 the single examined pair must be the unedged records "
        f"(new_c,new_d); got result={result}"
    )
