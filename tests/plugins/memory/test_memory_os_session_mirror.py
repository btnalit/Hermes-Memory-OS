import argparse
import json
import sqlite3

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.session_mirror import SessionMirror, read_session_mirror_apply_records
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _create_state_db(path, *, session_id="session-db-1", platform="telegram"):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            create table sessions (
                id text primary key,
                source text,
                created_at text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            create table messages (
                id integer primary key autoincrement,
                session_id text,
                role text,
                content text,
                created_at text
            )
            """
        )
        conn.execute(
            "insert into sessions(id, source, created_at, updated_at) values (?, ?, ?, ?)",
            (session_id, platform, "2026-05-21T08:00:00+00:00", "2026-05-21T08:01:00+00:00"),
        )
        conn.executemany(
            "insert into messages(session_id, role, content, created_at) values (?, ?, ?, ?)",
            [
                (session_id, "user", "查一下 PCDN 昨晚为什么失败 " + "U" * 120, "2026-05-21T08:00:01+00:00"),
                (session_id, "assistant", "昨晚失败原因是队列超时 " + "A" * 120, "2026-05-21T08:00:02+00:00"),
                (session_id, "tool", "PRIVATE_TOOL_TRACE_SHOULD_NOT_APPEAR", "2026-05-21T08:00:03+00:00"),
            ],
        )


def test_session_mirror_empty_environment_is_ok_and_dry_run_writes_nothing(tmp_path):
    store = _store(tmp_path)
    mirror = SessionMirror(store)

    report = mirror.scan(dry_run=True)

    assert report["status"] == "ok"
    assert report["session_count"] == 0
    assert report["new_event_count"] == 0
    assert report["dry_run"] is True
    assert store.read_events() == []
    assert not mirror.state_path.exists()


def test_session_mirror_state_db_primary_writes_bounded_summary_without_raw_tool_body(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db")
    mirror = SessionMirror(store)

    dry_run = mirror.scan(dry_run=True)
    applied = mirror.scan(dry_run=False)
    repeated = mirror.scan(dry_run=False)

    assert dry_run["new_event_count"] == 1
    assert applied["new_event_count"] == 1
    assert repeated["new_event_count"] == 0
    events = store.read_events()
    assert len(events) == 1
    event = events[0]
    assert event.kind == "conversation_turn_mirrored"
    assert event.source == "session_mirror"
    assert event.body_policy == "bounded_summary"
    assert event.safe_ref["source_kind"] == "state_db"
    assert event.safe_ref["session_id"] == "session-db-1"
    assert event.safe_ref["platform"] == "telegram"
    assert event.safe_ref["message_count"] == 3
    assert event.safe_ref["tool_count"] == 1
    assert event.safe_ref["drive_policy"] == "eligible"
    assert event.safe_ref["candidate_allowed"] is False
    rendered = json.dumps(event.to_dict(), ensure_ascii=False)
    assert "PRIVATE_TOOL_TRACE_SHOULD_NOT_APPEAR" not in rendered
    assert "U" * 120 not in rendered
    assert "A" * 120 not in rendered
    assert "PCDN" in event.summary


def test_session_mirror_apply_is_bounded_by_platform_and_redacts_secrets(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="telegram-session", platform="telegram")
    with sqlite3.connect(tmp_path / "state.db") as conn:
        conn.execute(
            "insert into sessions(id, source, created_at, updated_at) values (?, ?, ?, ?)",
            ("discord-session", "discord", "2026-05-21T09:00:00+00:00", "2026-05-21T09:01:00+00:00"),
        )
        conn.executemany(
            "insert into messages(session_id, role, content, created_at) values (?, ?, ?, ?)",
            [
                (
                    "telegram-session",
                    "user",
                    "请记住 api_key=sk-sessionmirror-UNIQUE-20260601-aaaaaaaaaaaaaaaa",
                    "2026-05-21T08:00:04+00:00",
                ),
                (
                    "discord-session",
                    "user",
                    "Discord session should remain pending",
                    "2026-05-21T09:00:01+00:00",
                ),
            ],
        )
    mirror = SessionMirror(store)

    report = mirror.scan(dry_run=False, max_sessions=1, platform_allowlist=["telegram"])
    repeated = mirror.scan(dry_run=False, max_sessions=1, platform_allowlist=["telegram"])

    assert report["status"] == "ok"
    assert report["apply_bounded"] is True
    assert report["candidate_session_count"] == 2
    assert report["selected_session_count"] == 1
    assert report["skipped_by_platform_count"] == 1
    assert report["skipped_by_limit_count"] == 0
    assert report["written_event_ids_count"] == 1
    assert report["raw_private_body_printed"] is False
    assert repeated["written_event_ids_count"] == 0
    event = store.read_events()[0]
    serialized = json.dumps(event.to_dict(), ensure_ascii=False)
    assert "sk-sessionmirror-UNIQUE" not in serialized
    assert "[REDACTED]" in serialized
    apply_records = read_session_mirror_apply_records(store.roots)
    assert apply_records[-1]["written_event_ids_count"] == 0
    assert apply_records[0]["written_event_ids_count"] == 1
    assert apply_records[0]["platform_allowlist"] == ["telegram"]


def test_session_mirror_skips_provider_captured_session(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="already-captured")
    captured = EventEnvelope.from_dict(
        {
            **build_event(seed=301, profile="memoryos-test"),
            "source": "telegram",
            "kind": "conversation_turn",
            "safe_ref": {"session_id": "already-captured"},
        }
    )
    store.append_event(captured)
    mirror = SessionMirror(store)

    report = mirror.scan(dry_run=False)

    assert report["session_count"] == 1
    assert report["covered_session_count"] == 1
    assert report["new_event_count"] == 0
    assert [event.id for event in store.read_events()] == [captured.id]


def test_session_mirror_uses_session_json_fallback_when_state_db_missing(tmp_path):
    store = _store(tmp_path)
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    (sessions_root / "session_json_1.json").write_text(
        json.dumps(
            {
                "id": "session-json-1",
                "platform": "cli",
                "created_at": "2026-05-21T09:00:00+00:00",
                "messages": [
                    {"role": "user", "content": "记一下 CLI 入口测试"},
                    {"role": "assistant", "content": "已经记录 CLI 入口测试"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    mirror = SessionMirror(store)

    report = mirror.scan(dry_run=False)

    assert report["session_count"] == 1
    event = store.read_events()[0]
    assert event.safe_ref["source_kind"] == "session_json"
    assert event.safe_ref["platform"] == "cli"
    assert "CLI" in event.summary


def test_session_mirror_uses_session_json_fallback_when_state_db_has_no_sessions(tmp_path):
    store = _store(tmp_path)
    with sqlite3.connect(tmp_path / "state.db") as conn:
        conn.execute("create table unrelated(id text)")
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    (sessions_root / "session_json_2.json").write_text(
        json.dumps(
            {
                "id": "session-json-2",
                "platform": "telegram",
                "messages": [
                    {"role": "user", "content": "JSON fallback should survive empty db"},
                    {"role": "assistant", "content": "JSON fallback survived"},
                ],
            }
        ),
        encoding="utf-8",
    )
    mirror = SessionMirror(store)

    report = mirror.scan(dry_run=False)

    assert report["new_event_count"] == 1
    assert store.read_events()[0].safe_ref["session_id"] == "session-json-2"


def test_session_mirror_dry_run_does_not_repair_corrupt_state_file(tmp_path):
    store = _store(tmp_path)
    mirror = SessionMirror(store)
    mirror.state_path.parent.mkdir(parents=True)
    mirror.state_path.write_text("{not json}", encoding="utf-8")

    report = mirror.scan(dry_run=True)

    assert report["status"] == "warning"
    assert report["state_rebuilt"] is True
    assert report["new_event_count"] == 0
    assert mirror.state_path.read_text(encoding="utf-8") == "{not json}"


def test_session_mirror_cli_scan_apply_requires_governance_metadata(tmp_path, monkeypatch, capsys):
    _create_state_db(tmp_path / "state.db", session_id="cli-session")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(["session-mirror", "scan", "--apply"])

    exit_code = memory_os_command(args)

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "memory-os.session_mirror_apply_gate.v0"
    assert report["status"] == "blocked"
    assert report["reason"] == "session_mirror_apply_owner_metadata_required"
    assert report["dry_run"] is True
    store_events = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path)).read_events()
    assert store_events == []


def test_session_mirror_cli_scan_apply_rejects_forged_owner_metadata(tmp_path, monkeypatch, capsys):
    _create_state_db(tmp_path / "state.db", session_id="cli-session")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(
        [
            "session-mirror",
            "scan",
            "--apply",
            "--owner-approved",
            "--approval-ref",
            "fake-ticket",
            "--evidence-ref",
            "test:smoke",
        ]
    )

    exit_code = memory_os_command(args)

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "memory-os.session_mirror_apply_gate.v0"
    assert report["status"] == "blocked"
    assert report["reason"] == "session_mirror_apply_owner_ref_not_validated"
    store_events = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path)).read_events()
    assert store_events == []


def test_session_mirror_cli_scan_apply_allows_explicit_test_host_gate(tmp_path, monkeypatch, capsys):
    _create_state_db(tmp_path / "state.db", session_id="cli-session")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_OS_ALLOW_TEST_HOST_APPLY", "1")
    parser = argparse.ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(["session-mirror", "scan", "--apply", "--test-host", "--evidence-ref", "test:smoke"])

    exit_code = memory_os_command(args)

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "memory-os.session_mirror_report.v0"
    assert report["dry_run"] is False
    assert report["new_event_count"] == 1
    assert report["apply_governance"]["test_host"] is True
    assert report["apply_governance"]["evidence_refs"] == ["test:smoke"]
    assert report["apply_governance"]["historical_bounded_smoke_unattested"] is False
