from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "memory_os_v3_journal_sweep.py"


def test_journal_sweep_helper_is_fail_closed_without_ttl_and_leaks_no_refs(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--hermes-home", str(tmp_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == '{"cycle_status":"skipped"}'


def test_journal_sweep_helper_stdout_is_status_only(tmp_path):
    config = tmp_path / "memory-os" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"v3_inner_life": {"journal_ttl_days": 1}}), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--hermes-home", str(tmp_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"cycle_status": "ok"}
    assert "wnd_" not in completed.stdout
    assert "v3body_" not in completed.stdout
