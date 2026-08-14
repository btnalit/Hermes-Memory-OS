"""memory_os_session_recall — the read half of 分层深入 (owner ruling 2026-08-14).

Injection carries compact summaries plus a session pointer; this tool is what
opens the pointer. Before it existed, prefetch labelled lines
"原始会话 <id>" while nothing in the codebase could retrieve that session —
a pointer to an unreachable place (verified by inventory: zero
read-by-session-id surfaces; the only `messages` query was trapped inside
session_mirror's all-sessions loop).

The security test is the load-bearing one: state.db bodies are the
unredacted source of exactly the secrets session_mirror strips before
writing events. A read path returning raw rows would bypass that boundary
at read time — an injected "go verify session X" becomes a credential
exfiltration channel. 以现状为准 makes redaction free: the agent needs the
conversation, never the stored secret value.
"""

from __future__ import annotations

import json
import sqlite3

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.session_mirror import (
    SESSION_TRANSCRIPT_MAX_MESSAGES,
    read_session_transcript,
)
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path) -> MemoryOSStore:
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    return store


def _create_state_db(path, *, session_id="drill-session", platform="telegram", message_count=6):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "create table sessions (id text primary key, source text, created_at text, updated_at text)"
        )
        conn.execute(
            "create table messages (id integer primary key autoincrement, session_id text,"
            " role text, content text, created_at text)"
        )
        conn.execute(
            "insert into sessions(id, source, created_at, updated_at) values (?, ?, ?, ?)",
            (session_id, platform, "2026-05-21T08:00:00+00:00", "2026-05-21T08:10:00+00:00"),
        )
        rows = []
        for i in range(message_count):
            role = "user" if i % 2 == 0 else "assistant"
            rows.append(
                (session_id, role, f"message {i}: 部署细节第 {i} 条", f"2026-05-21T08:0{i}:01+00:00")
            )
        conn.executemany(
            "insert into messages(session_id, role, content, created_at) values (?, ?, ?, ?)",
            rows,
        )


def test_reads_one_session_from_state_db(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db")

    report = read_session_transcript(store, "drill-session")

    assert report["status"] == "ok"
    assert report["source_kind"] == "state_db"
    assert report["platform"] == "telegram"
    assert report["total_message_count"] == 6
    assert report["returned_message_count"] == 6
    assert report["has_more"] is False
    assert report["messages"][0]["content"].startswith("message 0")
    assert report["secret_redaction_applied"] is True
    assert "以现实为准" in report["agent_instruction"]


def test_secrets_are_redacted_at_the_read_boundary(tmp_path):
    """The exfiltration guard: raw state.db bodies never leave the tool."""
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", message_count=0)
    with sqlite3.connect(tmp_path / "state.db") as conn:
        conn.execute(
            "insert into messages(session_id, role, content, created_at) values (?, ?, ?, ?)",
            (
                "drill-session",
                "user",
                "请记住 api_key=sk-drilldown-UNIQUE-20260814-bbbbbbbbbbbbbbbb 用于部署",
                "2026-05-21T08:00:01+00:00",
            ),
        )

    report = read_session_transcript(store, "drill-session")

    serialized = json.dumps(report, ensure_ascii=False)
    assert "sk-drilldown-UNIQUE" not in serialized
    assert "[REDACTED]" in serialized


def test_pagination_is_bounded_and_resumable(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", message_count=10)

    first = read_session_transcript(store, "drill-session", max_messages=4)
    second = read_session_transcript(store, "drill-session", max_messages=4, offset=8)

    assert first["returned_message_count"] == 4
    assert first["has_more"] is True
    assert second["offset"] == 8
    assert second["returned_message_count"] == 2
    assert second["has_more"] is False
    # The hard ceiling clamps oversized asks instead of honouring them.
    greedy = read_session_transcript(store, "drill-session", max_messages=10_000)
    assert greedy["returned_message_count"] <= SESSION_TRANSCRIPT_MAX_MESSAGES


def test_long_messages_carry_structural_truncation_flags(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db", message_count=0)
    with sqlite3.connect(tmp_path / "state.db") as conn:
        conn.execute(
            "insert into messages(session_id, role, content, created_at) values (?, ?, ?, ?)",
            ("drill-session", "user", "长" * 5000, "2026-05-21T08:00:01+00:00"),
        )

    report = read_session_transcript(store, "drill-session")

    message = report["messages"][0]
    assert message["content_truncated"] is True
    assert message["content_total_chars"] == 5000
    assert len(message["content"]) <= 600


def test_not_found_is_structured_not_an_exception(tmp_path):
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db")

    report = read_session_transcript(store, "no-such-session")

    assert report["status"] == "not_found"
    assert report["checked_state_db"] is True


def test_falls_back_to_session_json_files(tmp_path):
    store = _store(tmp_path)
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    (sessions_root / "session_json-drill.json").write_text(
        json.dumps(
            {
                "id": "json-drill",
                "platform": "cli",
                "updated_at": "2026-06-01T00:00:00+00:00",
                "messages": [
                    {"role": "user", "content": "json 泳道的消息", "created_at": "2026-06-01T00:00:01+00:00"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = read_session_transcript(store, "json-drill")

    assert report["status"] == "ok"
    assert report["source_kind"] == "session_json"
    assert report["messages"][0]["content"] == "json 泳道的消息"


def test_every_read_lands_in_the_audit_ledger(tmp_path):
    """Completion Is Not Output applies to read surfaces too."""
    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db")

    read_session_transcript(store, "drill-session")
    read_session_transcript(store, "no-such-session")

    ledger = store.roots.memory_os_root / "system" / "session_transcript_reads.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["status"] for row in rows] == ["ok", "not_found"]
    assert rows[0]["session_id"] == "drill-session"
    assert rows[0]["returned_message_count"] == 6


def test_read_ledger_is_registered_for_retention_and_ages_out(tmp_path):
    """Registration alone is not enough (continuity_freshness precedent):
    the row must carry a timestamp field retention can actually read, or it
    is retained forever while looking registered. Rows come from the REAL
    producer; only the age is rewritten, and the field name is asserted
    before rewriting so a producer rename fails here instead of silently
    un-ageing the ledger."""
    from datetime import datetime, timedelta, timezone

    from plugins.memory.memory_os.metadata_retention import (
        MetadataRetentionPolicy,
        metadata_retention_plan,
    )

    store = _store(tmp_path)
    _create_state_db(tmp_path / "state.db")
    read_session_transcript(store, "drill-session")
    read_session_transcript(store, "drill-session")

    ledger = store.roots.memory_os_root / "system" / "session_transcript_reads.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert all("created_at" in row for row in rows), "producer renamed the retention timestamp field"
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    rows[0]["created_at"] = (now - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    rows[1]["created_at"] = (now - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    ledger.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    plan = metadata_retention_plan(
        store.roots, now=now, policy=MetadataRetentionPolicy(shadow_retention_days=30),
    )

    summary = next(entry for entry in plan["ledgers"] if entry["ledger"] == "session_transcript_reads")
    assert summary["exists"] is True
    assert summary["total_records"] == 2
    assert summary["retained_records"] == 1
    assert summary["archive_candidate_records"] == 1


def test_provider_registers_and_dispatches_the_tool(tmp_path):
    _create_state_db(tmp_path / "state.db")
    from plugins.memory.memory_os import MemoryOSProvider

    provider = MemoryOSProvider()
    provider.initialize("tool-test-session", hermes_home=str(tmp_path))

    names = [schema["name"] for schema in provider.get_tool_schemas()]
    assert "memory_os_session_recall" in names
    schema = next(s for s in provider.get_tool_schemas() if s["name"] == "memory_os_session_recall")
    assert schema["parameters"]["required"] == ["session_id"]
    assert "以现实为准" in schema["description"] or "verify" in schema["description"]

    raw = provider.handle_tool_call("memory_os_session_recall", {"session_id": "drill-session"})
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["returned_message_count"] == 6


def test_system_prompt_teaches_the_layered_protocol(tmp_path):
    from plugins.memory.memory_os import MemoryOSProvider

    provider = MemoryOSProvider()
    provider.initialize("prompt-test-session", hermes_home=str(tmp_path))

    block = provider.system_prompt_block()
    assert "Layered Recall Rule" in block
    assert "memory_os_session_recall" in block
    assert "以现实为准" in block
    assert "[片段N/M字]" in block
