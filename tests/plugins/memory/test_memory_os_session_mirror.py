import argparse
import hashlib
import json
import sqlite3

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.runtime import MemoryOSRuntime
from plugins.memory.memory_os.session_mirror import (
    SessionMirror,
    auto_apply_graduated_session_mirror,
    read_session_mirror_apply_records,
    session_mirror_graduation_policy,
)
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


def _append_owner_action(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _owner_action_record(store, *, owner_action_id="oact_session_mirror_ok", fingerprint=""):
    stable_scope_id = hashlib.sha256(
        "|".join(
            [
                "session_mirror_apply",
                fingerprint or "fp_session_mirror_ok",
                "1",
                "telegram",
                "",
                "session-mirror-governed-apply.v1",
            ]
        ).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "schema_version": "memory-os.owner_action.v0",
        "owner_action_id": owner_action_id,
        "idempotency_key": f"owner|session_mirror_apply|production_bounded:{stable_scope_id}|approve_session_mirror_apply",
        "action_type": "approve_session_mirror_apply",
        "target_type": "session_mirror_apply",
        "target_id": f"production_bounded:{stable_scope_id}",
        "owner_id": "owner",
        "channel": "telegram",
        "created_at": "2026-06-02T08:02:00Z",
        "result": "applied",
        "source": "latest_owner_home_digest",
        "digest_id": "odig_session_mirror_ok",
        "reply_ingress_id": "audit_reply_ingress_ok",
        "token_binding": {
            "scope": "owner_home",
            "digest_id": "odig_session_mirror_ok",
            "review_item_id": "session_mirror_apply",
            "action_token_hash": "hash_ok",
        },
        "result_ref": {
            "approval_scope": "session_mirror_production_bounded_apply",
            "stable_scope_id": stable_scope_id,
            "selected_pending_session_fingerprint": fingerprint or "fp_session_mirror_ok",
            "boundary_contract_version": "session-mirror-governed-apply.v1",
            "max_sessions": 1,
            "platform_allowlist": ["telegram"],
            "auto_apply_after_graduation": True,
            "auto_apply_max_sessions_per_run": 1,
            "expires_at": "2099-01-01T00:00:00Z",
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "owner_effect": {"owner_approved_session_mirror_apply": True},
    }


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
    assert report["reason"] == "session_mirror_apply_owner_ref_not_found"
    store_events = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path)).read_events()
    assert store_events == []


def test_session_mirror_cli_scan_apply_rejects_env_only_test_host_gate(tmp_path, monkeypatch, capsys):
    _create_state_db(tmp_path / "state.db", session_id="cli-session")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_OS_ALLOW_TEST_HOST_APPLY", "1")
    parser = argparse.ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(["session-mirror", "scan", "--apply", "--test-host", "--evidence-ref", "test:smoke"])

    exit_code = memory_os_command(args)

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "memory-os.session_mirror_apply_gate.v0"
    assert report["status"] == "blocked"
    assert report["reason"] == "session_mirror_apply_test_host_not_verified"
    assert report["apply_governance"]["test_host"] is True
    assert report["apply_governance"]["test_host_config_allowed"] is False
    store_events = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path)).read_events()
    assert store_events == []


def test_session_mirror_cli_scan_apply_allows_verified_test_host_gate(tmp_path, monkeypatch, capsys):
    _create_state_db(tmp_path / "state.db", session_id="cli-session")
    save_config(
        {
            "session_mirror": {
                "test_host_apply_allowed": True,
                "test_host_marker": "install_preset:test-host",
            }
        },
        tmp_path,
    )
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
    assert report["apply_governance"]["test_host_config_allowed"] is True
    assert report["apply_governance"]["test_host_marker"] == "install_preset:test-host"
    assert report["apply_governance"]["evidence_refs"] == ["test:smoke"]
    assert report["apply_governance"]["historical_bounded_smoke_unattested"] is False


def test_session_mirror_dry_run_exposes_safe_pending_fingerprint_without_raw_body(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="fingerprint-session", platform="telegram")
    mirror = SessionMirror(store)

    report = mirror.scan(dry_run=True, max_sessions=1, platform_allowlist=["telegram"])

    assert report["selected_session_fingerprints"]
    selected = report["selected_sessions"][0]
    assert selected["fingerprint"] == report["selected_session_fingerprints"][0]
    assert selected["raw_private_body_printed"] is False
    assert selected["secret_redaction_applied"] is True
    serialized = json.dumps(selected, ensure_ascii=False)
    assert "PCDN" in serialized
    assert "PRIVATE_TOOL_TRACE_SHOULD_NOT_APPEAR" not in serialized


def test_session_mirror_cli_scan_apply_accepts_owner_channel_approval_once(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="governed-session", platform="telegram")
    dry_run = SessionMirror(store).scan(dry_run=True, max_sessions=1, platform_allowlist=["telegram"])
    fingerprint = dry_run["selected_session_fingerprints"][0]
    owner_record = _owner_action_record(store, fingerprint=fingerprint)
    _append_owner_action(store.roots.memory_os_root / "system" / "owner_actions.jsonl", owner_record)
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
            owner_record["owner_action_id"],
            "--evidence-ref",
            "full_lane_b:owner_channel:odig_session_mirror_ok",
            "--max-sessions",
            "1",
            "--platform",
            "telegram",
        ]
    )

    exit_code = memory_os_command(args)

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["written_event_ids_count"] == 1
    assert report["apply_governance"]["owner_approved"] is True
    assert report["apply_governance"]["approval_resolved"] is True
    assert report["apply_governance"]["approval_source"] == "owner_action_ledger"
    assert report["apply_governance"]["approval_ref"] == owner_record["owner_action_id"]
    assert report["apply_governance"]["owner_channel_bound"] is True
    assert report["apply_governance"]["stable_scope_id"] == owner_record["result_ref"]["stable_scope_id"]


def test_session_mirror_cli_scan_apply_rejects_expired_owner_ref(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="expired-session", platform="telegram")
    dry_run = SessionMirror(store).scan(dry_run=True, max_sessions=1, platform_allowlist=["telegram"])
    owner_record = _owner_action_record(store, fingerprint=dry_run["selected_session_fingerprints"][0])
    owner_record["result_ref"]["expires_at"] = "2000-01-01T00:00:00Z"
    _append_owner_action(store.roots.memory_os_root / "system" / "owner_actions.jsonl", owner_record)
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
            owner_record["owner_action_id"],
            "--evidence-ref",
            "full_lane_b:owner_channel:expired",
            "--max-sessions",
            "1",
            "--platform",
            "telegram",
        ]
    )

    exit_code = memory_os_command(args)

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["reason"] == "session_mirror_apply_owner_ref_expired"
    assert report["written_event_ids_count"] == 0
    assert store.read_events() == []


def test_session_mirror_cli_scan_apply_rejects_consumed_owner_ref(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="governed-session", platform="telegram")
    dry_run = SessionMirror(store).scan(dry_run=True, max_sessions=1, platform_allowlist=["telegram"])
    owner_record = _owner_action_record(store, fingerprint=dry_run["selected_session_fingerprints"][0])
    _append_owner_action(store.roots.memory_os_root / "system" / "owner_actions.jsonl", owner_record)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)
    first = parser.parse_args(
        [
            "session-mirror",
            "scan",
            "--apply",
            "--owner-approved",
            "--approval-ref",
            owner_record["owner_action_id"],
            "--evidence-ref",
            "full_lane_b:owner_channel:odig_session_mirror_ok",
            "--max-sessions",
            "1",
            "--platform",
            "telegram",
        ]
    )
    assert memory_os_command(first) == 0
    capsys.readouterr()
    second = parser.parse_args(
        [
            "session-mirror",
            "scan",
            "--apply",
            "--owner-approved",
            "--approval-ref",
            owner_record["owner_action_id"],
            "--evidence-ref",
            "full_lane_b:owner_channel:odig_session_mirror_ok",
            "--max-sessions",
            "1",
            "--platform",
            "telegram",
        ]
    )

    exit_code = memory_os_command(second)

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["reason"] == "session_mirror_apply_owner_ref_already_consumed"
    assert report["written_event_ids_count"] == 0
    assert len(read_session_mirror_apply_records(store.roots)) == 1


def test_session_mirror_cli_scan_apply_rejects_owner_ref_without_owner_home_binding(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="governed-session", platform="telegram")
    dry_run = SessionMirror(store).scan(dry_run=True, max_sessions=1, platform_allowlist=["telegram"])
    owner_record = _owner_action_record(store, fingerprint=dry_run["selected_session_fingerprints"][0])
    owner_record["source"] = "cli"
    owner_record["token_binding"]["scope"] = "cli"
    _append_owner_action(store.roots.memory_os_root / "system" / "owner_actions.jsonl", owner_record)
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
            owner_record["owner_action_id"],
            "--evidence-ref",
            "full_lane_b:owner_channel:odig_session_mirror_ok",
            "--max-sessions",
            "1",
            "--platform",
            "telegram",
        ]
    )

    exit_code = memory_os_command(args)

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["reason"] == "session_mirror_apply_owner_ref_not_owner_channel_bound"
    assert report["written_event_ids_count"] == 0


def test_session_mirror_auto_apply_ignores_one_shot_owner_smoke_without_graduation(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="auto-session-1", platform="telegram")
    dry_run = SessionMirror(store).scan(dry_run=True, max_sessions=1, platform_allowlist=["telegram"])
    owner_record = _owner_action_record(store, fingerprint=dry_run["selected_session_fingerprints"][0])
    owner_record["result_ref"]["auto_apply_after_graduation"] = False
    _append_owner_action(store.roots.memory_os_root / "system" / "owner_actions.jsonl", owner_record)

    policy = session_mirror_graduation_policy(store)
    report = auto_apply_graduated_session_mirror(store)

    assert policy["status"] == "absent"
    assert report["status"] == "skipped"
    assert report["reason"] == "no_owner_home_graduation_policy"
    assert report["written_event_ids_count"] == 0
    assert store.read_events() == []


def test_runtime_heartbeat_auto_applies_one_session_after_session_mirror_lane_graduation(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="auto-session-1", platform="telegram")
    with sqlite3.connect(tmp_path / "state.db") as conn:
        conn.execute(
            "insert into sessions(id, source, created_at, updated_at) values (?, ?, ?, ?)",
            ("auto-session-2", "telegram", "2026-05-21T09:00:00+00:00", "2026-05-21T09:01:00+00:00"),
        )
        conn.execute(
            "insert into messages(session_id, role, content, created_at) values (?, ?, ?, ?)",
            ("auto-session-2", "user", "第二条 SessionMirror 自动导入测试", "2026-05-21T09:00:01+00:00"),
        )
    dry_run = SessionMirror(store).scan(dry_run=True, max_sessions=1, platform_allowlist=["telegram"])
    owner_record = _owner_action_record(store, fingerprint=dry_run["selected_session_fingerprints"][0])
    _append_owner_action(store.roots.memory_os_root / "system" / "owner_actions.jsonl", owner_record)

    first = MemoryOSRuntime(store).heartbeat(max_events=10)
    second = MemoryOSRuntime(store).heartbeat(max_events=10)

    assert first["session_mirror_auto_apply"]["status"] == "ok"
    assert first["session_mirror_auto_apply"]["written_event_ids_count"] == 1
    assert first["session_mirror_auto_apply"]["approval_source"] == "latest_owner_home_digest"
    assert first["session_mirror_auto_apply"]["owner_channel_bound"] is True
    assert first["session_mirror_auto_apply"]["execution_gate_envelope_id"]
    assert first["session_mirror_auto_apply_written_event_ids_count"] == 1
    assert second["session_mirror_auto_apply"]["status"] == "ok"
    assert second["session_mirror_auto_apply"]["written_event_ids_count"] == 1
    events = store.read_events()
    assert len(events) == 2
    assert {event.safe_ref["session_id"] for event in events} == {"auto-session-1", "auto-session-2"}
    apply_records = read_session_mirror_apply_records(store.roots)
    assert len(apply_records) == 2
    assert apply_records[0]["apply_governance"]["approval_source"] == "owner_action_lane_graduation"
    assert apply_records[0]["apply_governance"]["auto_apply"] is True
    assert apply_records[0]["apply_governance"]["lane_graduated"] is True
    assert apply_records[0]["apply_governance"]["execution_gate_envelope_id"] == first["session_mirror_auto_apply"]["execution_gate_envelope_id"]
    assert apply_records[1]["apply_governance"]["approval_ref"] == owner_record["owner_action_id"]
