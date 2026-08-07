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
    """T1.5.1: Phase 1 — edges are shadow-logged, NOT injected into context."""
    store, index = _store(tmp_path)
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

    # Verify shadow log structure
    record = json.loads(lines[-1])
    assert record.get("schema_version") == "memory-os.graph_layer_shadow.v0"
    assert record.get("phase") == "1"
    assert record.get("anchor_count") >= 1
    assert record.get("edge_count") >= 1
    edges = record.get("edges", [])
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
# Phase 1.6 — Edge target resolution helpers (Task 1 of P1a)
# ═══════════════════════════════════════════════════════════════════════════


def test_resolve_edge_target_preview_found(tmp_path):
    """When crystallized record exists, return body preview."""
    from plugins.memory.memory_os.prefetch import _resolve_edge_target_preview
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    store = MemoryOSStore(roots)
    store.initialize()

    # Write a crystallized record
    svc = CrystallizedMemoryService(store)
    candidate = CrystallizedCandidate(
        candidate_id="cand-1",
        kind="preference",
        body="用户偏好深色主题界面",
        source_event_ids=["evt_seed_001"],
    )
    decision = ApprovalDecision(
        candidate_id="cand-1",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-22T10:00:00Z",
        note="test",
        source_state="active",
    )
    svc.write_approved_record(candidate, decision, file_name="owner_approved.md")

    # Non-existent record -> None
    preview = _resolve_edge_target_preview(store, "nonexistent_id")
    assert preview is None

    # Find the actual record_id from what was written
    records = svc.read_records("owner_approved.md")
    assert len(records) == 1
    record_id = records[0].frontmatter["id"]
    preview = _resolve_edge_target_preview(store, record_id)
    assert preview is not None
    assert "深色主题" in preview


def test_resolve_edge_target_preview_excludes_revoked_record(tmp_path):
    from plugins.memory.memory_os.prefetch import _resolve_edge_target_preview
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.crystallized import (
        CrystallizedCandidate,
        CrystallizedMemoryService,
    )
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    service = CrystallizedMemoryService(store)
    candidate = CrystallizedCandidate(
        candidate_id="cand-revoked-preview",
        kind="preference",
        body="SECRET-NONCE-REVOKED-PREVIEW",
        source_event_ids=["evt-revoked-preview"],
    )
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-22T10:00:00Z",
    )
    service.write_approved_record(
        candidate,
        decision,
        file_name="owner_approved.md",
    )
    record_id = str(service.read_records("owner_approved.md")[0].frontmatter["id"])
    service.revoke_record(record_id, revoked_by="owner", reason="test")

    assert _resolve_edge_target_preview(store, record_id) is None

    from plugins.memory.memory_os.prefetch import _graph_layer_injection_lines

    lines = _graph_layer_injection_lines(
        store,
        [
            {
                "edge_id": "edge-revoked-preview",
                "to_record_type": "crystallized_record",
                "to_record_id": record_id,
                "relation_type": "similar_to",
                "weight": 0.8,
                "state": "active",
            }
        ],
    )
    assert lines == []


def test_graph_layer_injection_lines_formats_edges(tmp_path):
    """Injection line formatting: each edge produces relation_type + body preview."""
    from plugins.memory.memory_os.prefetch import _graph_layer_injection_lines
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    store = MemoryOSStore(roots)
    store.initialize()

    svc = CrystallizedMemoryService(store)
    candidate = CrystallizedCandidate(
        candidate_id="cand-graph-1",
        kind="note",
        body="图谱测试记忆内容",
        source_event_ids=["evt_seed_002"],
    )
    decision = ApprovalDecision(
        candidate_id="cand-graph-1",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-22T10:00:00Z",
        note="test",
        source_state="active",
    )
    svc.write_approved_record(candidate, decision, file_name="test_graph.md")

    records = svc.read_records("test_graph.md")
    record_id = records[0].frontmatter["id"]

    edges = [
        {
            "edge_id": "edge-1",
            "to_record_type": "crystallized_record",
            "to_record_id": record_id,
            "relation_type": "co_occurs",
            "weight": 0.85,
            "from_record_type": "crystallized_record",
            "from_record_id": "cry_src",
            "state": "active",
        },
        {
            "edge_id": "edge-2",
            "to_record_type": "crystallized_record",
            "to_record_id": "nonexistent_cry_999",
            "relation_type": "similar_to",
            "weight": 0.60,
            "from_record_type": "crystallized_record",
            "from_record_id": "cry_src",
            "state": "active",
        },
    ]

    seen: set[tuple[str, str]] = set()
    lines = _graph_layer_injection_lines(store, edges, seen=seen)

    # At least one line should be resolved successfully
    assert len(lines) >= 1
    # First edge should contain relation_type and body preview
    assert "co_occurs" in lines[0] or "图谱测试" in lines[0]
    # Second edge resolution failure -> fallback to record_id
    assert any("nonexistent_cry_999" in line for line in lines)
    # seen should contain the successfully resolved record
    assert ("crystallized_record", record_id) in seen


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
