"""Tests for the Memory-OS overlay data probe helper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "memory_os_overlay_data_probe.py"


class TestOverlayDataProbeScript:
    def test_cli_accepts_named_hermes_home_argument(self, tmp_path):
        home = tmp_path / ".hermes"
        system = home / "memory-os" / "system"
        system.mkdir(parents=True)
        (system / "last_session_anchor.jsonl").write_text(
            json.dumps(
                {
                    "session_id": "sess-probe",
                    "foreground_summary": "Probe saw named hermes home",
                    "ended_at": "2026-07-06T10:00:00+00:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(_script_path()),
                "--hermes-home",
                str(home),
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["last_sessions"]["total_lines"] == 1
        assert data["last_sessions"]["latest"][0]["foreground_summary"] == "Probe saw named hermes home"

    def test_cli_rejects_unknown_arguments_instead_of_silent_misparse(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(_script_path()), "--not-a-real-option", str(tmp_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "unrecognized arguments" in result.stderr
