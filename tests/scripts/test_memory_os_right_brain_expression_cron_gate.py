import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_gate_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_right_brain_expression_cron_gate.py"
    spec = importlib.util.spec_from_file_location("memory_os_right_brain_expression_cron_gate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _fake_hermes(tmp_path: Path) -> Path:
    script = tmp_path / "fake_hermes.py"
    script.write_text(
        """
import json
import os
import pathlib
import sys

args = sys.argv[1:]
home = pathlib.Path(os.environ.get("HERMES_HOME", "."))

if args[:3] == ["cron", "create", "--help"]:
    print("usage: hermes cron create [--name NAME] [--deliver DELIVER] [--script SCRIPT] schedule prompt")
    raise SystemExit(0)

if args[:2] == ["cron", "create"]:
    def value(flag):
        return args[args.index(flag) + 1] if flag in args else ""
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_path.write_text(json.dumps({"jobs": [{
        "id": "job_right_brain",
        "name": value("--name"),
        "enabled": True,
        "deliver": value("--deliver"),
        "script": value("--script"),
        "no_agent": "--no-agent" in args,
        "prompt": args[-1],
    }]}), encoding="utf-8")
    print("created job_right_brain")
    raise SystemExit(0)

print("unexpected command", args, file=sys.stderr)
raise SystemExit(2)
""".lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        launcher = tmp_path / "hermes.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tmp_path / "hermes"
        launcher.write_text(f'#! /bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


def _args(module, tmp_path: Path, *, apply: bool = False, owner_approved: bool = False):
    hermes_home = tmp_path / "home"
    helper = hermes_home / "scripts" / "memory_os_right_brain_expression.py"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    return module.build_parser().parse_args(
        [
            "--hermes-home",
            str(hermes_home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--schedule",
            "30 4 * * 0",
            "--deliver",
            "origin",
            *(["--apply"] if apply else []),
            *(["--owner-approved"] if owner_approved else []),
        ]
    )


def test_right_brain_cron_gate_dry_run_requires_agent_mode_and_owner_channel(tmp_path):
    module = _load_gate_module()
    report = module.run_gate(_args(module, tmp_path))

    assert report["schema_version"] == "memory-os.right_brain_expression_cron_enable_gate.v0"
    assert report["status"] == "dry_run"
    assert report["checks"]["helper_script_present"] is True
    assert report["checks"]["hermes_cron_supports_agent_script_deliver"] is True
    assert report["deliver_target_class"] == "origin"
    assert report["boundary"]["actual_send"] is False


def test_right_brain_cron_gate_apply_creates_agent_cron_job_and_config(tmp_path):
    module = _load_gate_module()
    report = module.run_gate(_args(module, tmp_path, apply=True, owner_approved=True))

    assert report["status"] == "applied"
    jobs = json.loads((tmp_path / "home" / "cron" / "jobs.json").read_text(encoding="utf-8"))["jobs"]
    assert jobs[0]["name"] == "memory-os-right-brain-expression"
    assert jobs[0]["script"] == "memory_os_right_brain_expression.py"
    assert jobs[0]["no_agent"] is False
    assert "右脑低频表达" in jobs[0]["prompt"]
    config = json.loads((tmp_path / "home" / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert config["right_brain_expression"]["recurring_delivery_enabled"] is True
    assert config["right_brain_expression"]["recurring_delivery_mode"] == "hermes_cron_agent"


def test_right_brain_cron_gate_apply_is_idempotent_when_job_exists(tmp_path):
    module = _load_gate_module()
    module.run_gate(_args(module, tmp_path, apply=True, owner_approved=True))
    report = module.run_gate(_args(module, tmp_path, apply=True, owner_approved=True))

    assert report["status"] == "already_configured"
    jobs = json.loads((tmp_path / "home" / "cron" / "jobs.json").read_text(encoding="utf-8"))["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["id"] == "job_right_brain"
