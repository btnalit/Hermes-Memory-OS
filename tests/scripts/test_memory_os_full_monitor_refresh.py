from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_full_monitor_refresh.py"


def _write_fake_monitor(path: Path, *, write_snapshot: bool, exit_code: int) -> None:
    path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import argparse, json",
                "from pathlib import Path",
                "p = argparse.ArgumentParser()",
                "p.add_argument('--hermes-home')",
                "p.add_argument('--snapshot-out', type=Path, required=True)",
                "a = p.parse_args()",
                (
                    "a.snapshot_out.write_text(json.dumps({"
                    "'schema_version': 'memory-os.monitor.v0', "
                    "'classification': {'status': 'FAIL', 'fail_codes': ['expected_observation_gate']}"
                    "}), encoding='utf-8')"
                    if write_snapshot
                    else "pass"
                ),
                f"raise SystemExit({exit_code})",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_refresh_publishes_valid_fail_classification_without_alerting(tmp_path):
    home = tmp_path / "home"
    monitor = tmp_path / "fake_monitor.py"
    _write_fake_monitor(monitor, write_snapshot=True, exit_code=2)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--hermes-home",
            str(home),
            "--monitor-script",
            str(monitor),
            "--timeout-seconds",
            "10",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    artifacts = list((home / "memory-os" / "system" / "monitor_artifacts").glob("monitor_*.json"))
    assert len(artifacts) == 1
    payload = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert payload["classification"]["status"] == "FAIL"
    assert not list(artifacts[0].parent.glob("*.tmp"))


def test_refresh_fails_loudly_when_monitor_does_not_create_valid_artifact(tmp_path):
    home = tmp_path / "home"
    monitor = tmp_path / "broken_monitor.py"
    _write_fake_monitor(monitor, write_snapshot=False, exit_code=3)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--hermes-home",
            str(home),
            "--monitor-script",
            str(monitor),
            "--timeout-seconds",
            "10",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "full monitor refresh failed" in completed.stderr.lower()
    assert not list((home / "memory-os" / "system" / "monitor_artifacts").glob("monitor_*.json"))
