import json
import os
import sqlite3

from plugins.memory.memory_os.fixtures import (
    build_crystallized_frontmatter,
    build_event,
    build_working_item,
)
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, WORKING_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.audit import read_audit_entries
from plugins.memory.memory_os.store import MemoryOSStore


def _make_event(event_id="evt_20260520T010203000000Z_abcdef1234"):
    return EventEnvelope.from_dict(
        {
            "schema_version": EVENT_SCHEMA_VERSION,
            "id": event_id,
            "ts": "2026-05-20T09:02:03+08:00",
            "profile": "sannai",
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": "Owner asked about Memory-OS.",
            "safe_ref": {"session_id": "session-1"},
            "tags": ["memory-os"],
            "sensitivity": "private",
            "body_policy": "summary_only",
            "hashes": {},
            "promotion_state": "raw",
        }
    )


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_store_initialize_creates_only_memory_os_tree(tmp_path):
    store = _store(tmp_path)

    expected_dirs = {
        tmp_path / "memory-os",
        tmp_path / "memory-os" / "events",
        tmp_path / "memory-os" / "working",
        tmp_path / "memory-os" / "crystallized",
        tmp_path / "memory-os" / "identity",
        tmp_path / "memory-os" / "relationships",
        tmp_path / "memory-os" / "index",
        tmp_path / "memory-os" / "audit",
        tmp_path / "memory-os" / "imports",
        tmp_path / "memory-os" / "quarantine",
    }
    assert {p for p in (tmp_path / "memory-os").rglob("*") if p.is_dir()} | {tmp_path / "memory-os"} == expected_dirs
    assert store.roots.memory_os_root == tmp_path / "memory-os"


def test_append_event_uses_monthly_jsonl_and_preserves_existing_lines(tmp_path):
    store = _store(tmp_path)
    first = _make_event("evt_20260520T010203000000Z_aaaaaaaaaa")
    second = _make_event("evt_20260520T010204000000Z_bbbbbbbbbb")

    store.append_event(first)
    store.append_event(second)

    event_path = tmp_path / "memory-os" / "events" / "2026-05" / "2026-05-20.jsonl"
    lines = event_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == first.id
    assert json.loads(lines[1])["id"] == second.id
    assert [event.id for event in store.read_events()] == [first.id, second.id]


def test_write_and_read_working_document_atomically(tmp_path):
    store = _store(tmp_path)
    document = {
        "schema_version": WORKING_SCHEMA_VERSION,
        "updated_at": "2026-05-20T09:02:03+08:00",
        "items": [],
    }

    store.write_working_document("lingering", document)

    assert store.read_working_document("lingering") == document
    assert not list((tmp_path / "memory-os" / "working").glob("*.tmp"))


def test_append_crystallized_markdown_record(tmp_path):
    store = _store(tmp_path)
    frontmatter = {
        "schema_version": "memory-os.crystallized.v0",
        "id": "cry_20260520T010203000000Z_aaaaaaaaaa",
        "kind": "moment",
        "approved_by": "owner",
    }

    store.append_crystallized_record("moments.md", frontmatter, "Agent-rewritten memory.")

    content = (tmp_path / "memory-os" / "crystallized" / "moments.md").read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "id: cry_20260520T010203000000Z_aaaaaaaaaa" in content
    assert "Agent-rewritten memory." in content


def test_read_events_quarantines_malformed_jsonl_without_crashing(tmp_path):
    store = _store(tmp_path)
    event_path = tmp_path / "memory-os" / "events" / "2026-05" / "2026-05-20.jsonl"
    event_path.parent.mkdir(parents=True)
    event_path.write_text("{not json}\n" + json.dumps(_make_event().to_dict()) + "\n", encoding="utf-8")

    events = store.read_events()

    assert [event.id for event in events] == [_make_event().id]
    quarantine_lines = (tmp_path / "memory-os" / "quarantine" / "malformed_events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(quarantine_lines) == 1
    assert "not json" in quarantine_lines[0]
    audit_entries = read_audit_entries(tmp_path / "memory-os" / "audit" / "write_audit.jsonl")
    assert any(entry["action"] == "quarantine_malformed_event" for entry in audit_entries)


def test_index_rebuilds_from_filesystem_after_db_delete(tmp_path):
    store = _store(tmp_path)
    first = EventEnvelope.from_dict(build_event(seed=1, profile="memoryos-test"))
    second = EventEnvelope.from_dict(build_event(seed=2, profile="memoryos-test"))
    working_item = build_working_item(seed=3, source_event_id=first.id)
    crystallized = build_crystallized_frontmatter(seed=4, source_event_ids=[first.id, second.id])

    store.append_event(first)
    store.append_event(second)
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": working_item.updated_at,
            "items": [working_item.__dict__],
        },
    )
    store.append_crystallized_record(
        "moments.md",
        crystallized.__dict__,
        "Synthetic crystallized memory.",
    )
    index = MemoryOSIndex(store.roots)

    index.rebuild_from_store(store)
    store.roots.index_path.unlink()

    assert [event.id for event in store.read_events()] == [first.id, second.id]

    index.rebuild_from_store(store)

    assert index.counts()["events"] == 2
    assert index.counts()["working_items"] == 1
    assert index.counts()["crystallized_records"] == 1


def test_index_unavailable_keeps_store_readable_and_emits_audit(tmp_path, monkeypatch):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(build_event(seed=5, profile="memoryos-test"))
    store.append_event(event)

    def raise_locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("plugins.memory.memory_os.index.sqlite3.connect", raise_locked)

    rebuilt = MemoryOSIndex(store.roots).try_rebuild_from_store(store)

    assert rebuilt is False
    assert [stored.id for stored in store.read_events()] == [event.id]
    audit_entries = read_audit_entries(store.roots.audit_path)
    assert any(
        entry["action"] == "index_rebuild_failed" and "database is locked" in json.dumps(entry)
        for entry in audit_entries
    )


def test_index_search_matches_chinese_event_summary_and_reports_tokenizer(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=42, profile="memoryos-test"),
            "summary": "今天主人推荐了 Dolores 的歌。",
        }
    )
    store.append_event(event)
    index = MemoryOSIndex(store.roots)
    index.sync_from_store(store)

    result = index.search("推荐")

    assert result["mode"] == "indexed"
    assert result["tokenizer"] in {"trigram", "unicode61"}
    assert any(hit["record_id"] == event.id for hit in result["hits"])


def test_index_projects_structured_event_payload_into_fts_without_private_body(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=52, profile="memoryos-test"),
            "source": "cron",
            "kind": "cron_job_run",
            "summary": "PCDN monitor reported an operational anomaly.",
            "safe_ref": {
                "producer": "pcdn_cron",
                "status": "error",
                "metrics": {"loss_rate": 0.08, "queue_depth": 12},
                "raw_transcript": "PRIVATE_BODY_SHOULD_NOT_BE_INDEXED",
            },
            "tags": ["telemetry", "pcdn"],
        }
    )
    store.append_event(event)
    index = MemoryOSIndex(store.roots)
    index.sync_from_store(store)

    assert any(hit["record_id"] == event.id for hit in index.search("loss_rate")["hits"])
    assert any(hit["record_id"] == event.id for hit in index.search("0.08")["hits"])
    assert any(hit["record_id"] == event.id for hit in index.search("queue_depth")["hits"])
    assert not index.search("PRIVATE_BODY_SHOULD_NOT_BE_INDEXED")["hits"]
    raw_event = json.loads(next(store.roots.events_root.glob("*/*.jsonl")).read_text(encoding="utf-8").splitlines()[0])
    assert raw_event["safe_ref"]["raw_transcript"] == "PRIVATE_BODY_SHOULD_NOT_BE_INDEXED"


def test_index_projection_covers_session_governance_and_failure_payloads(tmp_path):
    store = _store(tmp_path)
    session_event = EventEnvelope.from_dict(
        {
            **build_event(seed=54, profile="memoryos-test"),
            "source": "session_mirror",
            "kind": "session_observed",
            "summary": "Session mirror observed bounded session metadata.",
            "safe_ref": {
                "session_count": 22,
                "covered_session_count": 9,
                "private_body": "SESSION_BODY_SHOULD_NOT_BE_INDEXED",
            },
        }
    )
    governance_event = EventEnvelope.from_dict(
        {
            **build_event(seed=55, profile="memoryos-test"),
            "source": "governance_feedback",
            "kind": "governance_feedback",
            "summary": "Governance feedback summarized proposal state.",
            "safe_ref": {
                "proposal_state": "approved_for_proposal",
                "decision": "would_send",
                "private_report_body": "GOVERNANCE_BODY_SHOULD_NOT_BE_INDEXED",
            },
        }
    )
    failure_event = EventEnvelope.from_dict(
        {
            **build_event(seed=56, profile="memoryos-test"),
            "source": "ops_gate",
            "kind": "action_failure",
            "summary": "Action failure was converted into evidence.",
            "safe_ref": {
                "status": "failed",
                "failure_code": "gateway_restart_blocked",
                "error_body": "FAILURE_BODY_SHOULD_NOT_BE_INDEXED",
            },
        }
    )
    for event in (session_event, governance_event, failure_event):
        store.append_event(event)
    index = MemoryOSIndex(store.roots)
    index.sync_from_store(store)

    assert any(hit["record_id"] == session_event.id for hit in index.search("session_count")["hits"])
    assert any(hit["record_id"] == governance_event.id for hit in index.search("proposal_state")["hits"])
    assert any(hit["record_id"] == governance_event.id for hit in index.search("decision")["hits"])
    assert any(hit["record_id"] == failure_event.id for hit in index.search("failure_code")["hits"])
    assert not index.search("SESSION_BODY_SHOULD_NOT_BE_INDEXED")["hits"]
    assert not index.search("GOVERNANCE_BODY_SHOULD_NOT_BE_INDEXED")["hits"]
    assert not index.search("FAILURE_BODY_SHOULD_NOT_BE_INDEXED")["hits"]


def test_index_records_fts_projection_version_for_rebuildability(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=53, profile="memoryos-test")))

    MemoryOSIndex(store.roots).sync_from_store(store)

    with sqlite3.connect(store.roots.index_path) as conn:
        row = conn.execute(
            "select value from index_metadata where key = ?",
            ("fts_text_projection_version",),
        ).fetchone()
    assert row is not None
    assert row[0] == "memory-os.fts_projection.v1"


def test_index_search_matches_approved_crystallized_markdown_body(tmp_path):
    store = _store(tmp_path)
    frontmatter = build_crystallized_frontmatter(seed=43, source_event_ids=["evt_43"])
    store.append_crystallized_record("moments.md", frontmatter.__dict__, "这是一段沉淀记忆 ZETA_CRYSTAL。")
    index = MemoryOSIndex(store.roots)
    index.sync_from_store(store)

    result = index.search("沉淀记忆")

    assert any(
        hit["record_type"] == "crystallized_record" and hit["record_id"] == frontmatter.id
        for hit in result["hits"]
    )


def test_index_sync_records_passive_wal_checkpoint_metadata(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=44, profile="memoryos-test")))

    MemoryOSIndex(store.roots).sync_from_store(store)

    with sqlite3.connect(store.roots.index_path) as conn:
        row = conn.execute(
            "select value from index_metadata where key = ?",
            ("last_checkpoint_mode",),
        ).fetchone()
    assert row[0] == "PASSIVE"


def test_index_checkpoint_escalates_to_full_after_repeated_busy_passive(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=50, profile="memoryos-test")))
    modes = []

    def fake_checkpoint(conn, mode):
        modes.append(mode)
        return mode == "PASSIVE"

    monkeypatch.setattr("plugins.memory.memory_os.index._run_checkpoint", fake_checkpoint)

    for _ in range(3):
        MemoryOSIndex(store.roots).sync_from_store(store)

    with sqlite3.connect(store.roots.index_path) as conn:
        row = conn.execute(
            "select value from index_metadata where key = ?",
            ("last_checkpoint_mode",),
        ).fetchone()
    assert row[0] == "FULL"
    assert modes.count("FULL") == 1


def test_index_checkpoint_escalates_to_truncate_when_wal_is_large(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=51, profile="memoryos-test")))
    modes = []

    def fake_checkpoint(conn, mode):
        modes.append(mode)
        return False

    monkeypatch.setattr("plugins.memory.memory_os.index._run_checkpoint", fake_checkpoint)
    monkeypatch.setattr("plugins.memory.memory_os.index._wal_file_size_bytes", lambda path: 101 * 1024 * 1024)

    MemoryOSIndex(store.roots).sync_from_store(store)

    with sqlite3.connect(store.roots.index_path) as conn:
        row = conn.execute(
            "select value from index_metadata where key = ?",
            ("last_checkpoint_mode",),
        ).fetchone()
    assert row[0] == "TRUNCATE"
    assert modes[-1] == "TRUNCATE"


def test_index_schema_reserves_vector_and_graph_extension_tables(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=45, profile="memoryos-test")))

    MemoryOSIndex(store.roots).sync_from_store(store)

    with sqlite3.connect(store.roots.index_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("select name from sqlite_master where type = 'table'").fetchall()
        }
    assert "memory_embeddings" in tables
    assert "memory_edges" in tables


def test_index_sync_records_event_source_state(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(build_event(seed=46, profile="memoryos-test"))
    store.append_event(event)

    MemoryOSIndex(store.roots).sync_from_store(store)

    with sqlite3.connect(store.roots.index_path) as conn:
        row = conn.execute(
            """
            select source_kind, indexed_line_count, last_record_id
            from index_source_state
            where source_kind = ?
            """,
            ("events_jsonl",),
        ).fetchone()
    assert row == ("events_jsonl", 1, event.id)


def test_index_rebuild_uses_staging_db_and_atomic_replace(tmp_path, monkeypatch):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(build_event(seed=47, profile="memoryos-test"))
    store.append_event(event)
    replace_calls = []
    original_replace = os.replace

    def record_replace(src, dst):
        replace_calls.append((str(src), str(dst)))
        original_replace(src, dst)

    monkeypatch.setattr("plugins.memory.memory_os.index.os.replace", record_replace)

    MemoryOSIndex(store.roots).rebuild_from_store(store)

    assert replace_calls
    assert replace_calls[-1][0].endswith(".rebuild.db")
    assert replace_calls[-1][1] == str(store.roots.index_path)
    assert MemoryOSIndex(store.roots).counts()["events"] == 1


def test_failed_staging_rebuild_preserves_existing_live_index(tmp_path, monkeypatch):
    store = _store(tmp_path)
    first = EventEnvelope.from_dict(build_event(seed=48, profile="memoryos-test"))
    second = EventEnvelope.from_dict(build_event(seed=49, profile="memoryos-test"))
    store.append_event(first)
    index = MemoryOSIndex(store.roots)
    index.rebuild_from_store(store)
    store.append_event(second)

    def raise_during_staging(*args, **kwargs):
        raise sqlite3.OperationalError("staging failed")

    monkeypatch.setattr("plugins.memory.memory_os.index._index_working_items", raise_during_staging)

    rebuilt = index.try_rebuild_from_store(store)

    assert rebuilt is False
    assert MemoryOSIndex(store.roots).counts()["events"] == 1
    assert not store.roots.index_path.with_name(f"{store.roots.index_path.name}.rebuild.db").exists()
