import json
import os
import subprocess
import sys
from pathlib import Path


def _fake_hermes(tmp_path: Path) -> Path:
    script = tmp_path / "fake_hermes.py"
    script.write_text(
        """
import sys
args = sys.argv[1:]
if args[:3] == ["cron", "create", "--help"]:
    print("usage: hermes cron create --script --no-agent")
    raise SystemExit(0)
if args[:3] == ["cron", "edit", "--help"]:
    print("usage: hermes cron edit --script --no-agent")
    raise SystemExit(0)
print("unexpected", args, file=sys.stderr)
raise SystemExit(2)
""".lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        launcher = tmp_path / "hermes.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tmp_path / "hermes"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


def test_cron_adapter_probe_uses_installed_snapshot_and_adapter_classification(tmp_path):
    hermes_home = tmp_path / "home"
    snapshot_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "fake",
                        "name": "memory-os-fake",
                        "raw_script": "memory_os_fake.py",
                        "wrapper_script": "memory_os_cron_fake_gate.py",
                        "lane_id": "fake_lane",
                        "helper_kind": "local_helper",
                        "schedule_arg": "fake_schedule",
                        "deliver_role": "local",
                        "prompt_ref": "empty",
                        "no_agent": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    jobs_path = hermes_home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps({"jobs": [{"name": "memory-os-fake", "script": "memory_os_cron_fake_gate.py"}]}),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_cron_adapter_probe.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--hermes-home",
            str(hermes_home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--output",
            "json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["schema_version"] == "memory-os.hermes_cron_adapter_probe.v0"
    assert report["spec_source"] == "installed_snapshot"
    assert report["capabilities"]["supports_script"] is True
    assert report["classification"]["memory_os_owned_expected_count"] == 1
    assert report["classification"]["memory_os_owned_wrapped_count"] == 1
