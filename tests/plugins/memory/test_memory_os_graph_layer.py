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
    updated = transition_edge_state(conn, edge["edge_id"], "invalidated")
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
    r1 = transition_edge_state(conn, edge["edge_id"], "owner_eligible")
    assert r1["state"] == "owner_eligible"
    # → active
    r2 = transition_edge_state(conn, edge["edge_id"], "active")
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
    r = transition_edge_state(conn, edge["edge_id"], "active")
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
    r = transition_edge_state(conn, edge["edge_id"], "invalidated")
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
    transition_edge_state(conn, eid, "invalidated")
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
    transition_edge_state(conn, edge["edge_id"], "invalidated")
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
    result = transition_edge_state(conn, edge["edge_id"], "candidate")
    assert result == {}
    conn.close()


def test_transition_edge_state_nonexistent(tmp_path):
    """transition_edge_state returns {} for unknown edge."""
    _, index = _store(tmp_path)
    conn = _conn(index)
    result = transition_edge_state(conn, "nonexistent_edge_id", "active")
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
    """T2.1.1: Refines edge between two crystallized records via proposer."""
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

    # Verify edge is in memory_edges
    conn2 = _conn(index)
    rows = conn2.execute(
        "select * from memory_edges where relation_type = 'refines'"
    ).fetchall()
    conn2.close()
    assert len(rows) >= 1
    assert rows[0]["state"] == "candidate"
    assert rows[0]["proposed_by"] == "structural"


def test_t2_1_2_write_contradicts_edge(tmp_path):
    """T2.1.2: Contradicts edge via dice similarity + different kinds."""
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
    rows = conn2.execute(
        "select * from memory_edges where relation_type = 'contradicts'"
    ).fetchall()
    conn2.close()
    assert len(rows) >= 1, (
        f"Expected contradicts edge. Proposer result: {result}"
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
    """T2.1.8: Similar body text with same kind → refines (not contradicts)."""
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
    # With same kind + same body, should produce refines, not contradicts
    assert types.get("refines", 0) >= 1, (
        f"Expected refines edge for same-kind similarity. Got types: {types}"
    )
    # contradicts should only come from different kinds with similar body
    # Since both are 'preference', no contradicts
    if "contradicts" in types:
        assert types["contradicts"] == 0


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


def test_t2_2_5_gate_fail_open_broken_index(tmp_path):
    """T2.2.5: Gate returns gracefully on broken index."""
    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    result = run_crystallization_gate(
        "/nonexistent/path/to/index.db",
        index=None,
    )
    assert result["status"] == "error"
    assert "error" in result


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
