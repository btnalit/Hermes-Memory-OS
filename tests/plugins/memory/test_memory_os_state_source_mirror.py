import argparse
import json

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.state_source_mirror import StateSourceMirror
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path, *, state_roots=None):
    roots = MemoryOSRoots.from_hermes_home(
        tmp_path,
        profile="memoryos-test",
        external_state_roots=state_roots or [],
    )
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_state_source_mirror_empty_allowlist_is_ok_and_dry_run_writes_nothing(tmp_path):
    store = _store(tmp_path)
    mirror = StateSourceMirror(store)

    report = mirror.scan(dry_run=True)

    assert report["status"] == "ok"
    assert report["source_count"] == 0
    assert report["new_event_count"] == 0
    assert report["dry_run"] is True
    assert store.read_events() == []
    assert not mirror.state_path.exists()


def test_state_source_mirror_writes_allowlisted_sources_without_private_bodies(tmp_path):
    state_root = tmp_path / "state"
    (state_root / "memory_journal").mkdir(parents=True)
    (state_root / "memory_journal" / "events.jsonl").write_text(
        json.dumps({"summary": "PRIVATE_JOURNAL_BODY_SHOULD_NOT_APPEAR"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (state_root / "heartbeat_lingering_candidates.jsonl").write_text(
        json.dumps({"status": "candidate", "body": "PRIVATE_CANDIDATE_BODY_SHOULD_NOT_APPEAR"}) + "\n",
        encoding="utf-8",
    )
    (state_root / "diary.md").write_text("PRIVATE_DIARY_BODY_SHOULD_NOT_APPEAR\n", encoding="utf-8")
    store = _store(tmp_path, state_roots=[state_root])
    mirror = StateSourceMirror(store)

    applied = mirror.scan(dry_run=False)
    repeated = mirror.scan(dry_run=False)

    assert applied["new_event_count"] == 3
    assert repeated["new_event_count"] == 0
    events = store.read_events()
    assert {event.kind for event in events} == {
        "candidate_surface_changed",
        "journal_card_observed",
        "state_source_changed",
    }
    by_class = {event.safe_ref["source_class"]: event for event in events}
    assert by_class["state:memory_journal_events"].safe_ref["drive_policy"] == "low_weight"
    assert by_class["state:heartbeat_lingering_candidates"].safe_ref["drive_policy"] == "candidate_surface"
    assert by_class["state:diary"].safe_ref["drive_policy"] == "evidence_only"
    assert by_class["state:heartbeat_lingering_candidates"].safe_ref["candidate_allowed"] is False
    assert by_class["state:diary"].body_policy == "summary_only"
    rendered = json.dumps([event.to_dict() for event in events], ensure_ascii=False)
    assert "PRIVATE_JOURNAL_BODY_SHOULD_NOT_APPEAR" not in rendered
    assert "PRIVATE_CANDIDATE_BODY_SHOULD_NOT_APPEAR" not in rendered
    assert "PRIVATE_DIARY_BODY_SHOULD_NOT_APPEAR" not in rendered


def test_state_source_mirror_dry_run_does_not_repair_corrupt_state_file(tmp_path):
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / "treasure_index.md").write_text("PRIVATE_TREASURE_BODY_SHOULD_NOT_APPEAR\n", encoding="utf-8")
    store = _store(tmp_path, state_roots=[state_root])
    mirror = StateSourceMirror(store)
    mirror.state_path.parent.mkdir(parents=True)
    mirror.state_path.write_text("{not json}", encoding="utf-8")

    report = mirror.scan(dry_run=True)

    assert report["status"] == "warning"
    assert report["state_rebuilt"] is True
    assert report["new_event_count"] == 1
    assert mirror.state_path.read_text(encoding="utf-8") == "{not json}"


def test_state_source_mirror_cli_scan_apply_outputs_json_report(tmp_path, monkeypatch, capsys):
    state_root = tmp_path / "state"
    (state_root / "digests" / "daily").mkdir(parents=True)
    (state_root / "digests" / "daily" / "2026-05-21.md").write_text(
        "PRIVATE_DIGEST_BODY_SHOULD_NOT_APPEAR\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(["state-source-mirror", "--state-root", str(state_root), "scan", "--apply"])

    exit_code = memory_os_command(args)

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "memory-os.state_source_mirror_report.v0"
    assert report["dry_run"] is False
    assert report["new_event_count"] == 1
    event = _store(tmp_path, state_roots=[state_root]).read_events()[0]
    assert event.safe_ref["source_class"] == "state:digest_daily"
    assert "PRIVATE_DIGEST_BODY_SHOULD_NOT_APPEAR" not in json.dumps(event.to_dict(), ensure_ascii=False)
