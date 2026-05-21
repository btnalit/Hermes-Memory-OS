import argparse
import json
from datetime import datetime, timezone

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _append_spool_record(store, producer: str, record: dict):
    path = store.roots.memory_os_root / "shadow-journal" / producer / "spool.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return path


def test_shadow_journal_dry_run_reports_pending_without_writing_events(tmp_path):
    store = _store(tmp_path)
    _append_spool_record(
        store,
        "pcdn",
        {
            "schema_version": "memory-os.shadow_journal_record.v0",
            "record_id": "pcdn-1",
            "ts": "2026-05-21T10:00:00+00:00",
            "producer": "pcdn",
            "kind": "telemetry_status",
            "source_class": "telemetry",
            "summary": "PCDN reports normal status.",
            "payload": {"status": "ok", "loss_rate": 0.01},
        },
    )

    from plugins.memory.memory_os.shadow_journal import ShadowJournalIngestion

    report = ShadowJournalIngestion(store).ingest(dry_run=True, max_records=10)

    assert report["schema_version"] == "memory-os.shadow_journal_ingest.v0"
    assert report["dry_run"] is True
    assert report["pending_record_count"] == 1
    assert report["would_write_event_count"] == 1
    assert report["written_event_ids"] == []
    assert store.read_events() == []


def test_shadow_journal_apply_writes_summary_event_and_dedups_second_run(tmp_path):
    store = _store(tmp_path)
    _append_spool_record(
        store,
        "pcdn",
        {
            "schema_version": "memory-os.shadow_journal_record.v0",
            "record_id": "pcdn-2",
            "ts": "2026-05-21T10:05:00+00:00",
            "producer": "pcdn",
            "kind": "telemetry_status",
            "source_class": "telemetry",
            "summary": "PCDN packet loss warning.",
            "payload": {"status": "warning", "loss_rate": 0.12},
        },
    )

    from plugins.memory.memory_os.shadow_journal import ShadowJournalIngestion

    first = ShadowJournalIngestion(store).ingest(dry_run=False, max_records=10)
    second = ShadowJournalIngestion(store).ingest(dry_run=False, max_records=10)

    events = store.read_events()
    assert first["written_event_count"] == 1
    assert second["written_event_count"] == 0
    assert len(events) == 1
    assert events[0].kind == "telemetry_status"
    assert events[0].source == "shadow_journal:pcdn"
    assert events[0].summary == "PCDN packet loss warning."
    assert events[0].body_policy == "summary_only"
    assert events[0].safe_ref["source_class"] == "telemetry"
    assert events[0].safe_ref["source_module"] == "shadow_journal"
    assert events[0].safe_ref["drive_policy"] == "index_only"
    assert events[0].safe_ref["candidate_allowed"] is False
    assert events[0].safe_ref["retention_class"] == "low_value"


def test_shadow_journal_apply_quarantines_malformed_records_without_events(tmp_path):
    store = _store(tmp_path)
    path = store.roots.memory_os_root / "shadow-journal" / "bad-producer" / "spool.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json\n", encoding="utf-8")

    from plugins.memory.memory_os.shadow_journal import ShadowJournalIngestion

    report = ShadowJournalIngestion(store).ingest(dry_run=False, max_records=10)

    quarantine = store.roots.quarantine_root / "shadow_journal_malformed.jsonl"
    assert report["malformed_record_count"] == 1
    assert report["written_event_count"] == 0
    assert store.read_events() == []
    assert quarantine.exists()
    assert "not json" in quarantine.read_text(encoding="utf-8")


def test_shadow_journal_cli_status_and_ingest_are_dry_run_by_default(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _append_spool_record(
        store,
        "router",
        {
            "schema_version": "memory-os.shadow_journal_record.v0",
            "record_id": "router-1",
            "ts": datetime(2026, 5, 21, tzinfo=timezone.utc).isoformat(),
            "producer": "router",
            "kind": "telemetry_status",
            "source_class": "telemetry",
            "summary": "Router status update.",
            "payload": {"status": "ok"},
        },
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)

    status_args = parser.parse_args(["shadow-journal", "status"])
    ingest_args = parser.parse_args(["shadow-journal", "ingest"])
    assert memory_os_command(status_args) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["pending_record_count"] == 1

    assert memory_os_command(ingest_args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["would_write_event_count"] == 1
    assert store.read_events() == []


def test_shadow_journal_apply_defers_when_ingest_lock_is_held(tmp_path):
    store = _store(tmp_path)
    _append_spool_record(
        store,
        "router",
        {
            "schema_version": "memory-os.shadow_journal_record.v0",
            "record_id": "router-locked",
            "ts": "2026-05-21T10:10:00+00:00",
            "producer": "router",
            "kind": "telemetry_status",
            "source_class": "telemetry",
            "summary": "Router status should wait for lock.",
            "payload": {"status": "ok"},
        },
    )
    lock_path = store.roots.memory_os_root / "runtime" / "locks" / "shadow_journal_ingest.lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.schedule_lock.v0",
                "resource_id": "memory_os.shadow_journal.ingest",
                "owner": "other-worker",
                "acquired_at": "2026-05-21T10:00:00+00:00",
                "expires_at": "2999-01-01T00:00:00+00:00",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    from plugins.memory.memory_os.shadow_journal import ShadowJournalIngestion

    report = ShadowJournalIngestion(store).ingest(dry_run=False, max_records=10)

    assert report["status"] == "warning"
    assert report["lock_status"] == "held"
    assert report["written_event_count"] == 0
    assert store.read_events() == []
