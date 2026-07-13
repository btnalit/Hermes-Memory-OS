from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_exposure_rollup_helper_writes_rollup_snapshot_and_execution_report(tmp_path: Path) -> None:
    from plugins.memory.memory_os.memory_sources import append_memory_source_record
    from plugins.memory.memory_os.roots import MemoryOSRoots

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    (roots.memory_os_root / "system").mkdir(parents=True, exist_ok=True)
    append_memory_source_record(
        roots,
        {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_helper_001",
            "created_at": "2026-07-12T01:00:00Z",
            "profile": "default",
            "route": "active_task",
            "selected": [{"source_ids": ["crystallized:helper_selected"]}],
            "dropped": [
                {
                    "source_ids": ["crystallized:helper_budget"],
                    "reason_codes": ["budget"],
                }
            ],
        },
    )
    report_path = tmp_path / "execution-report.json"
    from plugins.memory.memory_os.execution_gate import start_execution_gate_envelope
    from plugins.memory.memory_os.store import MemoryOSStore

    store = MemoryOSStore(roots)
    store.initialize()
    permit = start_execution_gate_envelope(
        store,
        lane_id="exposure_rollup",
        trigger_surface="test_wrapper",
        risk_class="local_helper",
        human_approval_required=False,
        why_no_human_approval="test observation helper",
        scope={"registry_key": "exposure_rollup"},
        boundary={"actual_send": False, "actual_execute": False, "actual_identity_write": False, "actual_unapproved_crystallized_approval": False},
    )
    envelope_id = permit["execution_gate_envelope_id"]
    script = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_exposure_rollup.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--hermes-home", str(tmp_path), "--profile", "default"],
        text=True,
        capture_output=True,
        env={
            "MEMORY_OS_EXECUTION_REPORT_PATH": str(report_path),
            "MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID": envelope_id,
        },
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "ok"
    assert result["conservation_passes"] is True
    assert result["eligible"] == 2
    assert result["selected"] == 1
    assert result["dropped_by_budget"] == 1
    assert (roots.memory_os_root / "system" / "exposure_rollup.jsonl").is_file()
    rollup = json.loads((roots.memory_os_root / "system" / "exposure_rollup.jsonl").read_text().splitlines()[-1])
    assert rollup["execution_gate_envelope"] == envelope_id
    snapshot = json.loads((roots.memory_os_root / "system" / "exposure_rollup_snapshot.json").read_text())
    assert snapshot["cumulative_eligible"] == 2
    assert snapshot["cumulative_dropped_by_budget"] == 1
    execution_report = json.loads(report_path.read_text())
    assert execution_report["boundary"] == {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }
    assert execution_report["result_summary"]["conservation_passes"] is True
