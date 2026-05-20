import json
import sqlite3

from plugins.memory.memory_os.fixtures import (
    build_crystallized_frontmatter,
    build_event,
    build_working_item,
)
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, WORKING_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.roots import MemoryOSRoots
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
    audit_lines = (tmp_path / "memory-os" / "audit" / "write_audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any("quarantine_malformed_event" in line for line in audit_lines)


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
    audit_lines = store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("index_rebuild_failed" in line and "database is locked" in line for line in audit_lines)
