import argparse
import hashlib
import json
import sqlite3

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.execution_gate import execution_gate_records_path, execution_gate_scope_hash
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.read_model_paths import owner_actions_path
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


def _append_execution_gate_permit(store, *, envelope_id, risk_class, scope):
    path = execution_gate_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "permit",
        "execution_gate_envelope_id": envelope_id,
        "created_at": "2026-06-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "profile": store.roots.profile or "default",
        "lane_id": "session_mirror_auto_apply",
        "trigger_surface": "runtime_heartbeat",
        "risk_class": risk_class,
        "permit_decision": "allowed",
        "boundary_true": False,
        "boundary": {"actual_send": False, "actual_execute": False},
        "scope": scope,
        "scope_hash": execution_gate_scope_hash(scope),
    }
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


def _test_host_governance():
    return {
        "test_host": True,
        "test_host_config_allowed": True,
        "test_host_marker": "install_preset:test-host",
        "evidence_refs": ["test:session_mirror_fixture_apply"],
    }


def _enable_test_host_apply(store):
    save_config(
        {
            "session_mirror": {
                "test_host_apply_allowed": True,
                "test_host_marker": "install_preset:test-host",
            }
        },
        store.roots.hermes_home,
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
    _enable_test_host_apply(store)
    _create_state_db(tmp_path / "state.db")
    mirror = SessionMirror(store)

    dry_run = mirror.scan(dry_run=True)
    applied = mirror.scan(dry_run=False, apply_governance=_test_host_governance())
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
    _enable_test_host_apply(store)
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

    report = mirror.scan(
        dry_run=False,
        max_sessions=1,
        platform_allowlist=["telegram"],
        apply_governance=_test_host_governance(),
    )
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
    _enable_test_host_apply(store)
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

    report = mirror.scan(dry_run=False, apply_governance=_test_host_governance())

    assert report["session_count"] == 1
    event = store.read_events()[0]
    assert event.safe_ref["source_kind"] == "session_json"
    assert event.safe_ref["platform"] == "cli"
    assert "CLI" in event.summary


def test_session_mirror_uses_session_json_fallback_when_state_db_has_no_sessions(tmp_path):
    store = _store(tmp_path)
    _enable_test_host_apply(store)
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

    report = mirror.scan(dry_run=False, apply_governance=_test_host_governance())

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
    assert report["suppressed_error_count"] == 1
    assert report["recent_error_codes"] == ["session_mirror_state_rebuilt"]
    assert report["findings"][0]["details"]["error_record"]["schema_version"] == "memory-os.error_record.v0"
    assert report["findings"][0]["details"]["error_record"]["component"] == "session_mirror"
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


def test_session_mirror_direct_scan_apply_without_governance_is_blocked(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="ungoverned-direct-session", platform="telegram")

    report = SessionMirror(store).scan(dry_run=False, max_sessions=1, platform_allowlist=["telegram"])

    assert report["status"] == "blocked"
    assert report["reason"] == "session_mirror_apply_governance_missing"
    assert report["written_event_ids_count"] == 0
    assert store.read_events() == []
    assert read_session_mirror_apply_records(store.roots) == []


def test_session_mirror_direct_scan_apply_rejects_forged_owner_metadata(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="forged-direct-session", platform="telegram")

    report = SessionMirror(store).scan(
        dry_run=False,
        max_sessions=1,
        platform_allowlist=["telegram"],
        apply_governance={
            "owner_approved": True,
            "approval_resolved": True,
            "approval_ref": "oact_forged",
            "owner_channel_bound": True,
        },
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "session_mirror_apply_owner_ref_not_found"
    assert report["written_event_ids_count"] == 0
    assert store.read_events() == []


def test_session_mirror_direct_scan_apply_rejects_forged_test_host_metadata(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="forged-test-host-session", platform="telegram")

    report = SessionMirror(store).scan(
        dry_run=False,
        max_sessions=1,
        platform_allowlist=["telegram"],
        apply_governance={
            "test_host": True,
            "test_host_config_allowed": True,
            "test_host_marker": "install_preset:test-host",
            "evidence_refs": ["test:forged-direct-api"],
        },
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "session_mirror_apply_test_host_not_verified"
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


def test_session_mirror_auto_apply_rejects_same_lane_wrong_risk_execution_gate(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="wrong-risk-session", platform="telegram")
    dry_run = SessionMirror(store).scan(dry_run=True, max_sessions=1, platform_allowlist=["telegram"])
    fingerprint = dry_run["selected_session_fingerprints"][0]
    owner_record = _owner_action_record(store, fingerprint=fingerprint)
    _append_owner_action(store.roots.memory_os_root / "system" / "owner_actions.jsonl", owner_record)
    scope = {
        "approval_ref": owner_record["owner_action_id"],
        "stable_scope_id": owner_record["result_ref"]["stable_scope_id"],
        "max_sessions_per_run": 1,
        "platform_allowlist": ["telegram"],
        "selected_session_fingerprints": [fingerprint],
    }
    _append_execution_gate_permit(
        store,
        envelope_id="xgate_wrong_risk",
        risk_class="route_score_modification",
        scope=scope,
    )

    report = SessionMirror(store).scan(
        dry_run=False,
        max_sessions=1,
        platform_allowlist=["telegram"],
        apply_governance={
            "owner_approved": True,
            "approval_ref": owner_record["owner_action_id"],
            "approval_resolved": True,
            "approval_source": "owner_action_lane_graduation",
            "owner_channel_bound": True,
            "stable_scope_id": owner_record["result_ref"]["stable_scope_id"],
            "execution_gate_envelope_id": "xgate_wrong_risk",
            "auto_apply": True,
            "lane_graduated": True,
        },
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "execution_gate_risk_class_mismatch"
    assert report["written_event_ids_count"] == 0
    assert store.read_events() == []


def test_session_mirror_auto_apply_rejects_execution_gate_scope_mismatch(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="scope-mismatch-session", platform="telegram")
    dry_run = SessionMirror(store).scan(dry_run=True, max_sessions=1, platform_allowlist=["telegram"])
    fingerprint = dry_run["selected_session_fingerprints"][0]
    owner_record = _owner_action_record(store, fingerprint=fingerprint)
    _append_owner_action(store.roots.memory_os_root / "system" / "owner_actions.jsonl", owner_record)
    permit_scope = {
        "approval_ref": owner_record["owner_action_id"],
        "stable_scope_id": owner_record["result_ref"]["stable_scope_id"],
        "max_sessions_per_run": 1,
        "platform_allowlist": ["telegram"],
        "selected_session_fingerprints": ["fp_different_session"],
    }
    _append_execution_gate_permit(
        store,
        envelope_id="xgate_scope_mismatch",
        risk_class="bounded_append_only_data_ingress",
        scope=permit_scope,
    )

    report = SessionMirror(store).scan(
        dry_run=False,
        max_sessions=1,
        platform_allowlist=["telegram"],
        apply_governance={
            "owner_approved": True,
            "approval_ref": owner_record["owner_action_id"],
            "approval_resolved": True,
            "approval_source": "owner_action_lane_graduation",
            "owner_channel_bound": True,
            "stable_scope_id": owner_record["result_ref"]["stable_scope_id"],
            "execution_gate_envelope_id": "xgate_scope_mismatch",
            "auto_apply": True,
            "lane_graduated": True,
        },
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "execution_gate_scope_mismatch"
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
    assert apply_records[0]["apply_governance"]["execution_gate_scope_hash"]
    assert apply_records[0]["apply_governance"]["execution_gate_permit_resolution"]["status"] == "valid"
    assert apply_records[0]["apply_governance"]["execution_gate_permit_resolution"]["risk_class"] == "bounded_append_only_data_ingress"
    assert apply_records[0]["apply_governance"]["execution_gate_permit_resolution"]["unused_before_apply"] is True
    assert apply_records[0]["apply_governance"]["execution_gate_permit_resolution"]["scope_match"] is True
    assert apply_records[1]["apply_governance"]["approval_ref"] == owner_record["owner_action_id"]


def test_unreadable_session_json_is_surfaced_not_silently_skipped(tmp_path):
    """A dropped session file must be distinguishable from one that never existed.

    `_read_session_json_files` used to skip malformed files with a bare
    `except Exception: continue` — no error record, no counter, no finding.
    A truncated or non-UTF8 session simply vanished from the SessionMirror
    auto-apply candidate list with zero operator-visible signal.
    """
    store = _store(tmp_path)
    sessions_root = store.roots.hermes_home / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)

    # One good session, one truncated, one valid JSON that is not an object.
    (sessions_root / "session_good.json").write_text(
        json.dumps({"id": "s-good", "platform": "telegram", "messages": []}),
        encoding="utf-8",
    )
    (sessions_root / "session_truncated.json").write_text('{"id": "s-bad",', encoding="utf-8")
    (sessions_root / "session_notdict.json").write_text("[1, 2, 3]", encoding="utf-8")

    mirror = SessionMirror(store)
    sessions = mirror._read_session_json_files()

    # The good session is still returned; the two bad ones are excluded...
    assert [item["session_id"] for item in sessions] == ["s-good"]

    # ...but their exclusion is now recorded, with the full error_record schema.
    error_codes = {
        record["error_code"] for record in mirror._session_read_error_records
    }
    assert error_codes == {"session_json_unreadable", "session_json_not_an_object"}
    for record in mirror._session_read_error_records:
        assert record["component"] == "session_mirror"
        assert record["operation"] == "read_session_json_files"
        assert record["severity"] == "warning"
        assert record["recoverable"] is True

    # And doctor() surfaces them to an operator as findings.
    findings = mirror.doctor()["findings"]
    surfaced = {
        finding["id"]
        for finding in findings
        if finding["id"] in {"session_json_unreadable", "session_json_not_an_object"}
    }
    assert surfaced == {"session_json_unreadable", "session_json_not_an_object"}


# ── Owner reject: scan-level exclusion ────────────────────────────────


def _add_session(path, *, session_id, platform="telegram", marker="B"):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "insert into sessions(id, source, created_at, updated_at) values (?, ?, ?, ?)",
            (session_id, platform, "2026-05-21T09:00:00+00:00", "2026-05-21T09:01:00+00:00"),
        )
        conn.executemany(
            "insert into messages(session_id, role, content, created_at) values (?, ?, ?, ?)",
            [
                (session_id, "user", "第二个会话的问题 " + marker * 120, "2026-05-21T09:00:01+00:00"),
                (session_id, "assistant", "第二个会话的回答 " + marker * 120, "2026-05-21T09:00:02+00:00"),
            ],
        )


def _reject_owner_action(store, fingerprint, *, result="applied"):
    _append_owner_action(
        owner_actions_path(store.roots),
        {
            "schema_version": "memory-os.owner_action.v0",
            "owner_action_id": f"oact_reject_{fingerprint[:8]}",
            "action_type": "reject_session_mirror_apply",
            "target_type": "session_mirror_apply",
            "target_id": f"production_bounded:{fingerprint}",
            "owner_id": "owner",
            "channel": "telegram",
            "result": result,
            "result_ref": {"selected_pending_session_fingerprint": fingerprint},
            "owner_effect": {"owner_rejected_session_mirror_apply": True},
        },
    )


def test_owner_rejected_session_stops_starving_the_sessions_behind_it(tmp_path):
    """Counterfactual: selection is pure head-of-queue (`platform_filtered[:limit]`).

    Without the scan-level rejection filter, the rejected session stays at the
    head, is re-offered on every digest, and is still the session the lane would
    import once graduated -- so every session behind it is starved forever.
    """
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="session-a")
    _add_session(tmp_path / "state.db", session_id="session-b")

    first = SessionMirror(store).scan(dry_run=True, max_sessions=1)
    head = first["selected_session_fingerprints"][0]
    assert first["skipped_by_owner_rejection_count"] == 0

    _reject_owner_action(store, head)
    after = SessionMirror(store).scan(dry_run=True, max_sessions=1)

    assert after["skipped_by_owner_rejection_count"] == 1
    assert len(after["selected_session_fingerprints"]) == 1
    assert head not in after["selected_session_fingerprints"]


def test_owner_rejection_survives_session_mirror_state_rebuild(tmp_path):
    """The rejection is read from the append-only owner action ledger, never from
    SessionMirror state: `_rebuild_state()` reconstructs state from Memory-OS
    events, so a rejection stored there would silently vanish on the next repair
    and the rejected session would be re-offered and eventually imported."""
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="session-a")
    _add_session(tmp_path / "state.db", session_id="session-b")

    head = SessionMirror(store).scan(dry_run=True, max_sessions=1)["selected_session_fingerprints"][0]
    _reject_owner_action(store, head)

    mirror = SessionMirror(store)
    mirror.state_path.parent.mkdir(parents=True, exist_ok=True)
    mirror.state_path.write_text("{ this is not json", encoding="utf-8")

    rebuilt = SessionMirror(store).scan(dry_run=True, max_sessions=1)

    assert rebuilt["state_rebuilt"] is True
    assert rebuilt["skipped_by_owner_rejection_count"] == 1
    assert head not in rebuilt["selected_session_fingerprints"]


def test_unapplied_reject_record_does_not_exclude_the_session(tmp_path):
    """A dry-run owner action is not a decision. Only applied/duplicate_ignored
    rejections may remove a session from the candidate list."""
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", session_id="session-a")

    head = SessionMirror(store).scan(dry_run=True, max_sessions=1)["selected_session_fingerprints"][0]
    _reject_owner_action(store, head, result="dry_run")

    after = SessionMirror(store).scan(dry_run=True, max_sessions=1)

    assert after["skipped_by_owner_rejection_count"] == 0
    assert after["selected_session_fingerprints"] == [head]


def test_owner_rejected_session_is_never_imported_by_a_real_apply(tmp_path):
    """The exclusion must hold on the write path, not only on the digest surface."""
    store = _store(tmp_path)
    _enable_test_host_apply(store)
    _create_state_db(tmp_path / "state.db", session_id="session-a")
    _add_session(tmp_path / "state.db", session_id="session-b")

    head = SessionMirror(store).scan(dry_run=True, max_sessions=1)["selected_session_fingerprints"][0]
    _reject_owner_action(store, head)

    applied = SessionMirror(store).scan(
        dry_run=False, max_sessions=1, apply_governance=_test_host_governance()
    )

    assert applied["skipped_by_owner_rejection_count"] == 1
    assert head not in applied["selected_session_fingerprints"]
    assert applied["new_event_count"] == 1


def _write_session_json(sessions_root, name, session_id, content):
    (sessions_root / name).write_text(
        json.dumps({
            "id": session_id,
            "platform": "telegram",
            "updated_at": "2026-08-01T00:00:00+00:00",
            "messages": [
                {"role": "user", "content": content},
                {"role": "assistant", "content": "回答：" + content},
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def test_scan_orders_never_imported_sessions_before_reimports(tmp_path):
    """Backlog 13: dedup_key embeds the content hash, so an active session
    re-enters the pending queue on every content change -- and discovery
    order is stable, so pure head-of-queue selection with a per-run cap keeps
    re-importing the same low-position active sessions while the tail starves
    (measured on production: 637 runs, backlog 1574 -> 1575).

    Counterfactual: without the never-imported-first ordering, the active
    session (session_a.json sorts first) is selected again and the
    never-imported one behind it is not reachable at any horizon.
    """
    store = _store(tmp_path)
    sessions_root = store.roots.hermes_home / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)

    _write_session_json(sessions_root, "session_a.json", "s-active", "第一版内容")
    mirror = SessionMirror(store)
    discovered = mirror._discover_sessions()
    assert [item["session_id"] for item in discovered] == ["s-active"]
    # Import A's first content version via the real event producer, so the
    # "imported before" signal comes from the artifact production writes.
    store.append_event(mirror._event_for_session(discovered[0]))

    # A grows new content (new dedup_key -> pending again); B has never been
    # imported and sits behind A in queue order.
    _write_session_json(sessions_root, "session_a.json", "s-active", "第二版内容，追加了新消息")
    _write_session_json(sessions_root, "session_b.json", "s-tail", "从未被导入的会话")

    report = mirror.scan(dry_run=True, max_sessions=1)
    assert report["candidate_session_count"] == 2
    assert [item["source_group_id"] for item in report["selected_sessions"]] == ["s-tail"]

    # And the signal survives a state rebuild: it derives from events, not
    # from SessionMirror state (same rationale as the owner-rejection fix).
    state_path = mirror.state_path
    if state_path.exists():
        state_path.unlink()
    report = mirror.scan(dry_run=True, max_sessions=1)
    assert [item["source_group_id"] for item in report["selected_sessions"]] == ["s-tail"]

    # Guard the dual: with no prior imports at all, queue order is untouched.
    fresh_store = _store(tmp_path / "fresh")
    fresh_root = fresh_store.roots.hermes_home / "sessions"
    fresh_root.mkdir(parents=True, exist_ok=True)
    _write_session_json(fresh_root, "session_a.json", "s-one", "内容一")
    _write_session_json(fresh_root, "session_b.json", "s-two", "内容二")
    fresh_report = SessionMirror(fresh_store).scan(dry_run=True, max_sessions=1)
    assert [item["source_group_id"] for item in fresh_report["selected_sessions"]] == ["s-one"]


def test_auto_apply_records_durable_last_run_reason(tmp_path, monkeypatch):
    """Backlog 14 (completion is not output): every auto-apply exit before the
    real scan returned a typed reason and persisted NOTHING, so a lane that
    ran hundreds of times producing nothing left no artifact a reader could
    consult.

    Counterfactual: without the recorder the last-run file does not exist on
    either path below.
    """
    store = _store(tmp_path)

    result = auto_apply_graduated_session_mirror(store)
    assert result["status"] == "skipped"
    last_run_path = store.roots.memory_os_root / "system" / "session_mirror_auto_apply_last_run.json"
    record = json.loads(last_run_path.read_text(encoding="utf-8"))
    assert record["status"] == "skipped"
    assert record["reason"] == result["reason"]
    assert record["written_event_ids_count"] == 0
    # No scan ran on this path: counters must be OMITTED, not zero-filled --
    # a missing measurement must never read as a real zero.
    assert "counters" not in record

    # Graduated lane, empty queue: the scan really ran, so its zeros are real
    # measurements and travel with the reason code.
    import plugins.memory.memory_os.session_mirror as session_mirror_module

    monkeypatch.setattr(
        session_mirror_module,
        "session_mirror_graduation_policy",
        lambda _store: {"status": "active", "max_sessions_per_run": 1, "platform_allowlist": []},
    )
    result = session_mirror_module.auto_apply_graduated_session_mirror(store)
    assert result["reason"] == "no_matching_pending_session"
    record = json.loads(last_run_path.read_text(encoding="utf-8"))
    assert record["reason"] == "no_matching_pending_session"
    assert record["counters"]["candidate_session_count"] == 0
    assert record["counters"]["selected_session_count"] == 0
