from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from plugins.memory.memory_os.operational_truth import read_operational_truth_snapshot
from scripts.memory_os_full_monitor_refresh import _monitor_environment


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_full_monitor_refresh.py"
REAL_MONITOR = SCRIPT.with_name("memory_os_3_200_monitor.py")
DASHBOARD = SCRIPT.with_name("memory_os_monitor_dashboard_snapshot.py")


def test_monitor_environment_includes_installed_scripts_and_runtime(tmp_path):
    home = tmp_path / "home"
    script = home / "scripts" / "memory_os_3_200_monitor.py"
    env = _monitor_environment(home, script)

    paths = env["PYTHONPATH"].split(os.pathsep)
    assert str(script.parent) in paths
    assert str(home / "memory-os" / "runtime" / "python") in paths


def _write_fake_monitor(path: Path, *, write_snapshot: bool, exit_code: int) -> None:
    path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import argparse, json, sys",
                "from pathlib import Path",
                "p = argparse.ArgumentParser()",
                "p.add_argument('--hermes-home')",
                "p.add_argument('--python-bin', required=True)",
                "p.add_argument('--snapshot-out', type=Path, required=True)",
                "p.add_argument('--output')",
                "a = p.parse_args()",
                "assert a.python_bin == sys.executable",
                (
                    "a.snapshot_out.write_text(json.dumps({"
                    "'schema_version': 'memory-os.monitor.v1', "
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
            "--source-head",
            "abc123",
            "--runtime-digest",
            "sha256:runtime-test",
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
    assert payload["schema_version"] == "memory-os.full_monitor_artifact.v1"
    assert payload["source_head"] == "abc123"
    assert payload["runtime_digest"] == "sha256:runtime-test"
    assert payload["monitor_version"] == "memory-os.monitor.v1"
    assert payload["generated_at"].endswith("Z")
    assert payload["producer_receipt"]["monitor_exit_code"] == 2
    assert payload["producer_receipt"]["receipt_id"].startswith("fmpr_")
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
            "--source-head",
            "abc123",
            "--runtime-digest",
            "sha256:runtime-test",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "full monitor refresh failed" in completed.stderr.lower()
    assert not list((home / "memory-os" / "system" / "monitor_artifacts").glob("monitor_*.json"))


def test_refresh_rejects_monitor_payload_without_schema_version(tmp_path):
    home = tmp_path / "home"
    monitor = tmp_path / "schema_less_monitor.py"
    monitor.write_text(
        "\n".join(
            [
                "import argparse, json, sys",
                "from pathlib import Path",
                "p=argparse.ArgumentParser()",
                "p.add_argument('--hermes-home')",
                "p.add_argument('--python-bin', required=True)",
                "p.add_argument('--snapshot-out', type=Path, required=True)",
                "p.add_argument('--output')",
                "a=p.parse_args()",
                "assert a.python_bin == sys.executable",
                "a.snapshot_out.write_text(json.dumps({'classification': {'status': 'PASS'}}))",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--hermes-home",
            str(home),
            "--monitor-script",
            str(monitor),
            "--source-head",
            "abc123",
            "--runtime-digest",
            "sha256:runtime-test",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "schema_version" in completed.stderr
    assert not list((home / "memory-os" / "system" / "monitor_artifacts").glob("monitor_*.json"))


def test_refresh_rejects_unknown_deployment_identity_without_publishing(tmp_path):
    home = tmp_path / "home"
    monitor = tmp_path / "fake_monitor.py"
    _write_fake_monitor(monitor, write_snapshot=True, exit_code=0)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--hermes-home", str(home), "--monitor-script", str(monitor)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "source_head" in completed.stderr
    assert not list((home / "memory-os" / "system" / "monitor_artifacts").glob("monitor_*.json"))


def test_real_monitor_refresh_reader_and_dashboard_contract_end_to_end(tmp_path):
    home = tmp_path / "home"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--hermes-home",
            str(home),
            "--monitor-script",
            str(REAL_MONITOR),
            "--timeout-seconds",
            "300",
            "--source-head",
            "e2e-source-head",
            "--runtime-digest",
            "sha256:e2e-runtime",
            "--monitor-profile",
            "clean-host",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    operational = read_operational_truth_snapshot(
        memory_root=home / "memory-os",
        now=datetime.now(timezone.utc),
        stale_after_seconds=3600,
    ).to_dict()
    full = operational["full_monitor"]
    assert full["read_error"] is None
    assert full["artifact_identity"]["envelope_complete"] is True
    assert full["artifact_identity"]["monitor_version"] == "memory-os.monitor.v1"
    assert full["status"] in {"PASS", "WARN", "FAIL"}

    spec = importlib.util.spec_from_file_location("dashboard_e2e", DASHBOARD)
    assert spec and spec.loader
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)
    rendered = dashboard._monitor_snapshot(
        now=datetime.now(timezone.utc),
        profile="default",
        duration_ms=1,
        status_report={},
        cadence_report={},
        cron_jobs=[],
        owner={"counts": {}},
        memory={"index_fresh": True},
        expression={"drafts": 0, "sent": 0},
        hindsight={"mode": "disabled"},
        boundary=[],
        full_monitor=full,
    )
    if full["status"] == "FAIL":
        assert rendered["status"] == "FAIL"
        assert rendered["fail"] >= 1
