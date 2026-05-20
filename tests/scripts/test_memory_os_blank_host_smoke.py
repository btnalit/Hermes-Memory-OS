import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_blank_host_smoke_script_runs_e2e_and_shadow_flow(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/memory_os_blank_host_smoke.py",
            "--base-dir",
            str(tmp_path / "validation"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert report["schema_version"] == "memory-os.blank_host_smoke.v0"
    assert report["production_touched"] is False
    assert report["e2e"]["event_count"] == 1
    assert report["e2e"]["working_item_count"] == 1
    assert report["e2e"]["crystallized_record_count"] == 1
    assert report["e2e"]["adapter_disabled_exported_count"] == 0
    assert report["e2e"]["adapter_enabled_exported_count"] == 1
    assert report["migrator"]["scan_source_count"] >= 9
    assert report["migrator"]["export_dry_run_wrote"] is False
    assert report["migrator"]["import_source_count"] == report["migrator"]["scan_source_count"]
    assert report["migrator"]["replay_messages_sent"] == 0
    assert report["migrator"]["diff_ready_for_owner_review"] is True
