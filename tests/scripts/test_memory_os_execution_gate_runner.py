import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_execution_gate_runner_preserves_stdout_and_writes_envelopes(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    shutil.copy2(runner, scripts_dir / "memory_os_execution_gate_runner.py")
    (scripts_dir / "memory_os_module_cadence_report_cron.py").write_text(
        "print('HELPER_STDOUT_OK')\n",
        encoding="utf-8",
    )
    hermes_home = tmp_path / "home"

    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "memory_os_execution_gate_runner.py"),
            "--registry-key",
            "module_cadence_report",
            "--hermes-home",
            str(hermes_home),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "HELPER_STDOUT_OK"
    assert result.stderr == ""
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    assert [record["stage"] for record in records] == ["permit", "completion"]
    assert records[0]["lane_id"] == "module_cadence_report"
    assert records[0]["permit_decision"] == "allowed"
    assert records[0]["human_approval_required"] is False
    assert records[1]["execution_gate_envelope_id"] == records[0]["execution_gate_envelope_id"]
