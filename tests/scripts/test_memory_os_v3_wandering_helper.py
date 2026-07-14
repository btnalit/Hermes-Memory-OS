from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "memory_os_v3_wandering.py"


def test_wandering_helper_default_disabled_and_stdout_is_aggregate_only(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--hermes-home", str(tmp_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload == {
        "external_action_executed": False,
        "model_input_transmitted": False,
        "owner_delivery_attempted": False,
        "status": "skipped",
    }
    assert "crystallized:" not in completed.stdout
    assert "wnd_" not in completed.stdout


def test_wandering_helper_bootstraps_from_installed_layout(tmp_path):
    installed = tmp_path / "scripts" / SCRIPT.name
    installed.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, installed)
    runtime = tmp_path / "memory-os" / "runtime" / "python"
    runtime.parent.mkdir(parents=True)
    runtime.symlink_to(REPO_ROOT, target_is_directory=True)

    completed = subprocess.run(
        [sys.executable, str(installed), "--hermes-home", str(tmp_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "skipped"
