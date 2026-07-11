import json
import sqlite3

from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.owner_actions import resolve_owner_review_channel as legacy_resolve_owner_review_channel
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.seam.hermes_memory_os.owner_channel_adapter import (
    channel_shadow_diff,
    resolve_owner_review_channel,
)


def _legacy_report(home):
    roots = MemoryOSRoots.from_hermes_home(home, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    return legacy_resolve_owner_review_channel(store)


def test_host_owner_channel_adapter_matches_legacy_for_explicit_owner_config(tmp_path):
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "mode": "dry_run",
                "owner_id": "owner",
                "channel": "telegram",
                "target_ref": "telegram:12345",
                "direct_message": True,
            }
        },
        tmp_path,
    )

    host = resolve_owner_review_channel(hermes_home=tmp_path)
    legacy = _legacy_report(tmp_path)

    assert channel_shadow_diff(host, legacy)["status"] == "match"
    assert host["status"] == "selected"
    assert host["target_ref"] == "telegram:12345"
    assert host["raw_body_included"] is False


def test_host_owner_channel_adapter_reads_state_db_metadata_without_message_bodies(tmp_path):
    with sqlite3.connect(tmp_path / "state.db") as conn:
        conn.execute(
            "create table sessions (id text, platform text, chat_id text, updated_at text, is_direct integer)"
        )
        conn.execute(
            "insert into sessions values (?, ?, ?, ?, ?)",
            ("sess_1", "matrix", "room-1", "2026-07-11T01:00:00Z", 1),
        )
        conn.execute("create table messages (session_id text, role text, content text)")
        conn.execute(
            "insert into messages values (?, ?, ?)",
            ("sess_1", "user", "PRIVATE BODY MUST NOT APPEAR"),
        )

    report = resolve_owner_review_channel(hermes_home=tmp_path)

    assert report["status"] == "dry_run_only"
    assert report["reason"] == "single_owner_direct_metadata_candidate"
    assert report["channel"] == "matrix"
    assert report["target_ref"] == "matrix:room-1"
    assert "PRIVATE BODY" not in json.dumps(report, ensure_ascii=False)
