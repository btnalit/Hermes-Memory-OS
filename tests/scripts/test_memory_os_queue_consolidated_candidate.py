import json

from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from scripts import memory_os_queue_consolidated_candidate as helper


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path / ".hermes", profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    event = EventEnvelope.from_dict(build_event(seed=2701, profile="default"))
    store.append_event(event)
    return store, event


def test_queue_consolidated_candidate_is_dry_run_by_default(tmp_path, capsys):
    store, event = _store(tmp_path)

    exit_code = helper.main(
        [
            "--hermes-home",
            str(store.roots.hermes_home),
            "--profile",
            "default",
            "--source-event-id",
            event.id,
            "--body",
            "用户希望 Memory-OS 的审批闭环通过 Hermes 主会话通道完成，而不是停留在 CLI 或 monitor 证据。",
        ]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ready"
    assert report["candidate_queued"] is False
    assert report["actual_crystallized_approval"] is False


def test_queue_consolidated_candidate_apply_writes_candidate_only(tmp_path, capsys):
    store, event = _store(tmp_path)

    exit_code = helper.main(
        [
            "--hermes-home",
            str(store.roots.hermes_home),
            "--profile",
            "default",
            "--source-event-id",
            event.id,
            "--body",
            "用户希望 Memory-OS 的审批闭环通过 Hermes 主会话通道完成，而不是停留在 CLI 或 monitor 证据。",
            "--tag",
            "owner-governance",
            "--apply",
        ]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "queued"
    assert report["candidate_queued"] is True
    assert report["actual_crystallized_approval"] is False

    candidate_path = store.roots.crystallized_root / "candidates.jsonl"
    assert "owner-governance" in candidate_path.read_text(encoding="utf-8")
    assert list(store.roots.crystallized_root.glob("*.md")) == []


def test_queue_consolidated_candidate_rejects_transcript_like_body(tmp_path, capsys):
    store, event = _store(tmp_path)

    exit_code = helper.main(
        [
            "--hermes-home",
            str(store.roots.hermes_home),
            "--profile",
            "default",
            "--source-event-id",
            event.id,
            "--body",
            "User: please remember this. Assistant: ok.",
        ]
    )

    assert exit_code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "invalid"
    assert "body_looks_like_transcript" in report["validation_errors"]
