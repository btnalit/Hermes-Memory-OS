"""Counterfactual tests for the P0.2 embedding-preservation guard.

_copy_embeddings_from_live (index.py) exists to prevent a silent vector
recall wipe: when rebuild_from_store runs with no embedder available, it
must copy memory_embeddings across from the live index rather than ship a
staging DB with zero embedding rows. Before this fix the function swallowed
every sqlite3.Error with a bare ``pass`` and the ATTACH statement string-
interpolated the live path -- both defects made a total embedding loss
byte-identical, in the audit log, to a healthy rebuild.

These tests build all fixtures through the real producers (MemoryOSStore,
CrystallizedMemoryService, MemoryOSIndex.rebuild_from_store) rather than
hand-written dicts, per repo convention.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
from plugins.memory.memory_os.audit import read_audit_records
from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
)
from plugins.memory.memory_os.index import MemoryOSIndex, _copy_embeddings_from_live
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


class MockEmbedder:
    """Deterministic mock embedder -- no model download needed."""

    def __init__(self, available: bool = True):
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def embed(self, text: str) -> bytes:
        vec = np.array([float(len(text)), float(len(text)) * 0.5, 1.0], dtype=np.float32)
        padded = np.zeros(384, dtype=np.float32)
        padded[: len(vec)] = vec
        return padded.tobytes()


def _make_store(home: "os.PathLike[str] | str") -> tuple[MemoryOSRoots, MemoryOSStore]:
    roots = MemoryOSRoots.from_hermes_home(str(home), profile="test")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    store = MemoryOSStore(roots)
    store.initialize()
    return roots, store


def _write_crystallized_records(store: MemoryOSStore, count: int) -> None:
    svc = CrystallizedMemoryService(store)
    for i in range(count):
        candidate = CrystallizedCandidate(
            candidate_id=f"guard-c{i}",
            kind="note",
            body=f"记忆内容 guard {i}",
            source_event_ids=[f"guard-evt-{i}"],
        )
        decision = ApprovalDecision(
            candidate_id=f"guard-c{i}",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at="2026-06-22T10:00:00Z",
            source_state="active",
        )
        svc.write_approved_record(candidate, decision, file_name="guard.md")


def _embedding_count(index_path) -> int:
    conn = sqlite3.connect(str(index_path))
    try:
        return conn.execute("select count(*) from memory_embeddings").fetchone()[0]
    finally:
        conn.close()


def _latest(records: list[dict], action: str) -> dict:
    matches = [r for r in records if r.get("action") == action]
    assert matches, f"no audit record found for action={action!r}"
    return matches[-1]


# ── Acceptance 1: healthy rebuild preserves embeddings and audits counts ──


def test_rebuild_preserves_embeddings_when_embedder_unavailable_and_audits_counts(tmp_path):
    roots, store = _make_store(tmp_path / "hermes")
    _write_crystallized_records(store, count=3)

    # First rebuild with an embedder available -- populates the live index.
    index = MemoryOSIndex(roots)
    index._embedder = MockEmbedder(available=True)
    index.rebuild_from_store(store)
    assert _embedding_count(roots.index_path) == 3

    # Second rebuild with the embedder unavailable: must preserve, not wipe.
    index2 = MemoryOSIndex(roots)
    index2._embedder = MockEmbedder(available=False)
    index2.rebuild_from_store(store)

    assert _embedding_count(roots.index_path) == 3

    entry = _latest(read_audit_records(roots.audit_path), "index_rebuild")
    preservation = entry["details"]["embedding_preservation"]
    assert preservation["outcome"] == "copied"
    assert preservation["live_row_count"] == 3
    assert preservation["copied_row_count"] == 3


# ── Acceptance 2: a copy failure is loud, not silent, and fail-open ──────


def test_rebuild_reports_copy_failed_with_nonzero_live_row_count_when_attach_raises(tmp_path, monkeypatch):
    roots, store = _make_store(tmp_path / "hermes")
    _write_crystallized_records(store, count=4)

    index = MemoryOSIndex(roots)
    index._embedder = MockEmbedder(available=True)
    index.rebuild_from_store(store)
    assert _embedding_count(roots.index_path) == 4

    real_connect = sqlite3.connect

    class _AttachRaisingConnection:
        """Proxy that raises only on the ATTACH statement; everything else
        passes through to the real connection untouched. sqlite3.Connection
        is a C type and cannot be monkeypatched directly (attempting
        ``sqlite3.Connection.execute = ...`` raises TypeError: cannot set
        'execute' attribute of immutable type), so the proxy wraps the
        object returned by sqlite3.connect instead."""

        def __init__(self, real_conn):
            object.__setattr__(self, "_real", real_conn)

        def execute(self, sql, *args, **kwargs):
            if "ATTACH DATABASE" in sql:
                raise sqlite3.OperationalError("database is locked")
            return self._real.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

        def __setattr__(self, name, value):
            setattr(self._real, name, value)

    def wrapped_connect(*args, **kwargs):
        return _AttachRaisingConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr("plugins.memory.memory_os.index.sqlite3.connect", wrapped_connect)

    index2 = MemoryOSIndex(roots)
    index2._embedder = MockEmbedder(available=False)
    index2.rebuild_from_store(store)  # must NOT raise -- fail-open

    monkeypatch.undo()

    # The rebuild completed and shipped a staging DB with zero embeddings.
    assert _embedding_count(roots.index_path) == 0

    records = read_audit_records(roots.audit_path)
    rebuild_entry = _latest(records, "index_rebuild")
    preservation = rebuild_entry["details"]["embedding_preservation"]
    assert preservation["outcome"] == "copy_failed"
    assert preservation["live_row_count"] > 0
    assert preservation["copied_row_count"] == 0

    # No Silent Failures: a bounded error record must have been emitted,
    # consistent with the entity_index_knob_resolution_failed pattern
    # already used elsewhere in index.py.
    failure_entry = _latest(records, "index_rebuild_embeddings_copy_failed")
    assert failure_entry["status"] == "warning"
    error_record = failure_entry["details"]["error_record"]
    assert error_record["component"] == "sqlite"
    assert error_record["severity"] == "warning"
    assert error_record["recoverable"] is True
    assert error_record["details"]["live_row_count"] > 0


# ── Acceptance 3: apostrophe in the live index path no longer breaks ATTACH ──


def test_rebuild_preserves_embeddings_when_hermes_home_path_has_apostrophe(tmp_path):
    home = tmp_path / "o'brien" / "hermes"
    roots, store = _make_store(home)
    _write_crystallized_records(store, count=2)

    index = MemoryOSIndex(roots)
    index._embedder = MockEmbedder(available=True)
    index.rebuild_from_store(store)
    assert _embedding_count(roots.index_path) == 2

    index2 = MemoryOSIndex(roots)
    index2._embedder = MockEmbedder(available=False)
    index2.rebuild_from_store(store)  # must not raise despite the apostrophe

    assert _embedding_count(roots.index_path) == 2
    entry = _latest(read_audit_records(roots.audit_path), "index_rebuild")
    preservation = entry["details"]["embedding_preservation"]
    assert preservation["outcome"] == "copied"
    assert preservation["live_row_count"] == 2
    assert preservation["copied_row_count"] == 2


# ── Closed reason-code coverage: no live index yet, and a live index with ──
# ── no memory_embeddings table (e.g. pre-embeddings schema).             ──


def test_rebuild_reports_no_live_index_on_first_ever_rebuild(tmp_path):
    roots, store = _make_store(tmp_path / "hermes")
    _write_crystallized_records(store, count=1)

    index = MemoryOSIndex(roots)
    index._embedder = MockEmbedder(available=False)
    index.rebuild_from_store(store)  # no prior live index exists at all

    entry = _latest(read_audit_records(roots.audit_path), "index_rebuild")
    preservation = entry["details"]["embedding_preservation"]
    assert preservation == {
        "outcome": "no_live_index",
        "live_row_count": 0,
        "copied_row_count": 0,
    }


def test_copy_embeddings_from_live_reports_live_table_missing(tmp_path):
    live_path = tmp_path / "live.db"
    live_conn = sqlite3.connect(str(live_path))
    live_conn.execute("create table not_embeddings (x int)")
    live_conn.commit()
    live_conn.close()

    staging_conn = sqlite3.connect(":memory:")
    staging_conn.execute(
        """
        create table memory_embeddings (
            record_type text not null,
            record_id text not null,
            embedding_model text not null,
            embedding blob not null,
            created_at text not null,
            primary key (record_type, record_id, embedding_model)
        )
        """
    )

    result = _copy_embeddings_from_live(staging_conn, live_path)
    staging_conn.close()

    assert result == {"outcome": "live_table_missing", "live_row_count": 0, "copied_row_count": 0}
