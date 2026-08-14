"""Wiring tests: lanes whose reason taxonomies used to be stdout-only must
now persist a durable last-run record ("Completion Is Not Output").

Counterfactual: before this wiring, every one of these runs left NO
lane_last_run file, so the assertions on its existence fail on the old code.
"""

from __future__ import annotations

from plugins.memory.memory_os.lane_last_run import read_lane_last_run

from scripts import cleanup_expired_working as working_cleanup
from scripts import memory_os_hindsight_advisory_digest as advisory_digest
from scripts import memory_os_hindsight_health_probe as health_probe
import json


def test_hindsight_health_probe_persists_disabled_outcome(tmp_path, capsys):
    assert health_probe.main(["--hermes-home", str(tmp_path)]) == 0

    record = read_lane_last_run(tmp_path, "hindsight_health_probe")

    assert record is not None
    assert record["status"] == "ok"
    assert record["reason"] == "disabled"
    capsys.readouterr()  # drain probe stdout


def test_hindsight_advisory_digest_persists_skip_reason(tmp_path, capsys):
    assert advisory_digest.main(["--hermes-home", str(tmp_path)]) == 0

    record = read_lane_last_run(tmp_path, "hindsight_advisory_digest")

    assert record is not None
    assert record["status"] == "skipped"
    assert record["reason"] == "hindsight_not_enabled"
    assert record["counters"]["advisory_emitted"] == 0
    capsys.readouterr()


def test_working_cleanup_records_absent_file(tmp_path):
    assert working_cleanup.main(str(tmp_path)) == 0

    record = read_lane_last_run(tmp_path, "working_cleanup")

    assert record["status"] == "skipped"
    assert record["reason"] == "working_file_absent"


def test_working_cleanup_records_no_expired_items(tmp_path):
    working = tmp_path / "memory-os" / "working" / "lingering.json"
    working.parent.mkdir(parents=True)
    working.write_text(
        json.dumps({"items": [{"status": "active", "text": "keep me"}]}),
        encoding="utf-8",
    )

    assert working_cleanup.main(str(tmp_path)) == 0

    record = read_lane_last_run(tmp_path, "working_cleanup")
    assert record["status"] == "ok"
    assert record["reason"] == "no_expired_items"
    assert record["counters"] == {"items_scanned": 1, "items_removed": 0}


def test_working_cleanup_records_removal_and_prunes_file(tmp_path, capsys):
    working = tmp_path / "memory-os" / "working" / "lingering.json"
    working.parent.mkdir(parents=True)
    working.write_text(
        json.dumps(
            {
                "items": [
                    {"status": "expired", "updated_at": "2020-01-01T00:00:00+00:00", "text": "old"},
                    {"status": "active", "text": "keep"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert working_cleanup.main(str(tmp_path)) == 0

    record = read_lane_last_run(tmp_path, "working_cleanup")
    assert record["reason"] == "removed_expired_items"
    assert record["counters"]["items_removed"] == 1
    remaining = json.loads(working.read_text(encoding="utf-8"))["items"]
    assert [item["text"] for item in remaining] == ["keep"]
    assert "Working Memory Cleanup" in capsys.readouterr().out


def test_state_source_mirror_helper_persists_scan_outcome(tmp_path, monkeypatch, capsys):
    from scripts import memory_os_state_source_mirror_helper as mirror_helper

    class _StubStore:
        def __init__(self, roots):
            self.roots = roots

        def initialize(self):
            return None

    class _StubMirror:
        def __init__(self, _store):
            pass

        def scan(self, dry_run):
            return {
                "status": "warning",
                "findings": [{"code": "state_root_missing"}, {"code": "state_root_missing"}],
            }

    monkeypatch.setattr(mirror_helper, "_HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(mirror_helper, "load_config", lambda _home: {})
    monkeypatch.setattr(mirror_helper, "MemoryOSStore", _StubStore)
    monkeypatch.setattr(mirror_helper, "StateSourceMirror", _StubMirror)

    assert mirror_helper.main() == 0

    record = read_lane_last_run(tmp_path, "state_source_mirror")
    assert record["status"] == "ok"
    assert record["reason"] == "scan_warning"
    assert record["counters"] == {"findings": 2, "state_root_missing": 2}
    capsys.readouterr()


def test_working_cleanup_records_unreadable_file(tmp_path, capsys):
    working = tmp_path / "memory-os" / "working" / "lingering.json"
    working.parent.mkdir(parents=True)
    working.write_text("{broken json", encoding="utf-8")

    assert working_cleanup.main(str(tmp_path)) == 1

    record = read_lane_last_run(tmp_path, "working_cleanup")
    assert record["status"] == "error"
    assert record["reason"] == "working_file_unreadable"
    assert "cannot read" in capsys.readouterr().err
