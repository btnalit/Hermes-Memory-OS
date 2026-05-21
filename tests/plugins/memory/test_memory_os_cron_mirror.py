import json
import argparse

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.cron_mirror import CronMirror
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_cron_mirror_empty_environment_is_ok_and_dry_run_writes_nothing(tmp_path):
    store = _store(tmp_path)
    mirror = CronMirror(store)

    report = mirror.scan(dry_run=True)

    assert report["status"] == "ok"
    assert report["job_count"] == 0
    assert report["output_file_count"] == 0
    assert report["new_event_count"] == 0
    assert report["dry_run"] is True
    assert store.read_events() == []
    assert not mirror.state_path.exists()


def test_cron_mirror_apply_writes_summary_event_and_state_without_raw_output(tmp_path):
    store = _store(tmp_path)
    cron_root = tmp_path / "cron"
    output_dir = cron_root / "output" / "pcdn-health"
    output_dir.mkdir(parents=True)
    (cron_root / "jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "pcdn-health",
                        "name": "PCDN health",
                        "mode": "no_agent",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "2026-05-21.md").write_text(
        "SECRET_RAW_PROMPT should not be copied\nstatus: error\nloss_rate: 0.08\n",
        encoding="utf-8",
    )
    mirror = CronMirror(store)

    dry_run = mirror.scan(dry_run=True)
    apply_report = mirror.scan(dry_run=False)
    second_apply = mirror.scan(dry_run=False)

    assert dry_run["new_event_count"] == 1
    assert apply_report["new_event_count"] == 1
    assert second_apply["new_event_count"] == 0
    events = store.read_events()
    assert len(events) == 1
    event = events[0]
    assert event.kind == "cron_job_run"
    assert event.source == "cron"
    assert event.body_policy == "summary_only"
    assert event.promotion_state == "raw"
    assert "SECRET_RAW_PROMPT" not in event.summary
    assert "SECRET_RAW_PROMPT" not in json.dumps(event.safe_ref, ensure_ascii=False)
    assert event.safe_ref["job_id"] == "pcdn-health"
    assert event.safe_ref["mode"] == "no_agent"
    assert event.safe_ref["dedup_key"].startswith("cron_output::pcdn-health::2026-05-21.md::")
    state = json.loads(mirror.state_path.read_text(encoding="utf-8"))
    assert event.safe_ref["dedup_key"] in state["seen_outputs"]


def test_cron_mirror_rebuilds_corrupt_state_from_existing_events(tmp_path):
    store = _store(tmp_path)
    output_dir = tmp_path / "cron" / "output" / "daily"
    output_dir.mkdir(parents=True)
    (output_dir / "2026-05-21.md").write_text("status: ok\n", encoding="utf-8")
    mirror = CronMirror(store)
    first = mirror.scan(dry_run=False)
    mirror.state_path.write_text("{not json}", encoding="utf-8")

    second = mirror.scan(dry_run=False)

    assert first["new_event_count"] == 1
    assert second["status"] == "warning"
    assert second["state_rebuilt"] is True
    assert second["new_event_count"] == 0
    assert second["findings"][0]["id"] == "cron_mirror_state_rebuilt"
    assert len(store.read_events()) == 1


def test_cron_mirror_dry_run_does_not_repair_corrupt_state_file(tmp_path):
    store = _store(tmp_path)
    mirror = CronMirror(store)
    mirror.state_path.parent.mkdir(parents=True)
    mirror.state_path.write_text("{not json}", encoding="utf-8")

    report = mirror.scan(dry_run=True)

    assert report["status"] == "warning"
    assert report["state_rebuilt"] is True
    assert report["new_event_count"] == 0
    assert mirror.state_path.read_text(encoding="utf-8") == "{not json}"


def test_cron_mirror_state_rebuild_does_not_quarantine_malformed_events(tmp_path):
    store = _store(tmp_path)
    event_path = tmp_path / "memory-os" / "events" / "2026-05" / "2026-05-21.jsonl"
    event_path.parent.mkdir(parents=True)
    event_path.write_text("{not json}\n", encoding="utf-8")
    mirror = CronMirror(store)
    mirror.state_path.parent.mkdir(parents=True)
    mirror.state_path.write_text("{not json}", encoding="utf-8")

    report = mirror.scan(dry_run=True)

    assert report["status"] == "warning"
    assert not (tmp_path / "memory-os" / "quarantine" / "malformed_events.jsonl").exists()


def test_cron_mirror_cli_scan_apply_outputs_json_report(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "cron" / "output" / "daily"
    output_dir.mkdir(parents=True)
    (output_dir / "2026-05-21.md").write_text("status: ok\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(["cron-mirror", "scan", "--apply"])

    exit_code = memory_os_command(args)

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "memory-os.cron_mirror_report.v0"
    assert report["dry_run"] is False
    assert report["new_event_count"] == 1
