import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_gate_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_owner_review_cron_gate.py"
    spec = importlib.util.spec_from_file_location("memory_os_owner_review_cron_gate", path)
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
    print("usage: hermes cron create [--name NAME] [--deliver DELIVER] [--script SCRIPT] [--no-agent] schedule")
    raise SystemExit(0)

if args[:3] == ["memory-os-agent-os", "review", "render-digest"]:
    if os.environ.get("FAKE_UNSAFE_RENDER") == "1":
        print("Candidate kind=moment; source_events=1; sensitivity=private")
    else:
        print("Memory-OS owner review digest\\nA1 Human readable proposal")
    raise SystemExit(0)

if args[:2] == ["cron", "create"]:
    def value(flag):
        return args[args.index(flag) + 1] if flag in args else ""
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    job = {
        "id": "job_owner_review",
        "name": value("--name"),
        "enabled": True,
        "deliver": value("--deliver"),
        "script": value("--script"),
        "no_agent": "--no-agent" in args,
        "prompt": args[-1],
        "schedule": {"display": args[-1]},
    }
    jobs_path.write_text(json.dumps({"jobs": [job]}), encoding="utf-8")
    print("created job_owner_review")
    raise SystemExit(0)

if args[:2] == ["cron", "edit"]:
    def value(flag):
        return args[args.index(flag) + 1] if flag in args else ""
    jobs_path = home / "cron" / "jobs.json"
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    jobs[0].update(
        {
            "deliver": value("--deliver"),
            "script": value("--script"),
            "no_agent": "--no-agent" in args and "--agent" not in args,
            "prompt": value("--prompt"),
            "schedule": {"display": value("--schedule")},
        }
    )
    jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    print("edited", args[2])
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


def _args(module, tmp_path: Path, *, apply: bool = False, owner_approved: bool = False, deliver: str = "telegram:-100123"):
    hermes_home = tmp_path / "home"
    helper = hermes_home / "scripts" / "memory_os_owner_review_digest.py"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    return module.build_parser().parse_args(
        [
            "--hermes-home",
            str(hermes_home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--schedule",
            "0 9 * * *",
            "--deliver",
            deliver,
            *(["--apply"] if apply else []),
            *(["--owner-approved"] if owner_approved else []),
        ]
    )


def test_cron_gate_dry_run_redacts_delivery_target_and_does_not_write_config(tmp_path):
    module = _load_gate_module()
    report = module.run_gate(_args(module, tmp_path))

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["schema_version"] == "memory-os.owner_review_cron_enable_gate.v0"
    assert report["status"] == "dry_run"
    assert report["checks"]["helper_script_present"] is True
    assert report["checks"]["hermes_cron_supports_agent_script_deliver"] is True
    assert report["checks"]["render_check"]["ok"] is True
    assert report["deliver_target_class"] == "explicit_target"
    assert "telegram:-100123" not in serialized
    assert not (tmp_path / "home" / "memory-os" / "config.json").exists()


def test_cron_gate_apply_requires_owner_approval(tmp_path):
    module = _load_gate_module()
    report = module.run_gate(_args(module, tmp_path, apply=True, owner_approved=False))

    assert report["status"] == "blocked"
    assert any(item["code"] == "owner_approval_required_for_apply" for item in report["findings"])
    assert not (tmp_path / "home" / "cron" / "jobs.json").exists()


def test_cron_gate_apply_creates_hermes_cron_job_and_updates_recurring_config(tmp_path):
    module = _load_gate_module()
    report = module.run_gate(_args(module, tmp_path, apply=True, owner_approved=True))

    assert report["status"] == "applied"
    assert report["config_updated"] is True
    jobs = json.loads((tmp_path / "home" / "cron" / "jobs.json").read_text(encoding="utf-8"))["jobs"]
    assert jobs[0]["name"] == "memory-os-owner-review-digest"
    assert jobs[0]["script"] == "memory_os_owner_review_digest.py"
    assert jobs[0]["no_agent"] is False
    assert "用中文" in jobs[0]["prompt"]
    assert "Script Output" in jobs[0]["prompt"]
    assert "全貌" in jobs[0]["prompt"]
    assert "不要只列命令" in jobs[0]["prompt"]
    config = json.loads((tmp_path / "home" / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert config["owner_review"]["recurring_delivery_enabled"] is True
    assert config["owner_review"]["recurring_delivery_mode"] == "hermes_cron_agent"
    assert config["owner_review"]["recurring_delivery_channel"] == "telegram"
    assert config["owner_review"]["recurring_delivery_target_class"] == "explicit_target"


def test_cron_gate_apply_updates_existing_no_agent_job_to_agent_mode(tmp_path):
    module = _load_gate_module()
    args = _args(module, tmp_path, apply=True, owner_approved=True)
    home = Path(args.hermes_home)
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job_owner_review",
                        "name": "memory-os-owner-review-digest",
                        "enabled": True,
                        "deliver": "telegram:-100123",
                        "script": "memory_os_owner_review_digest.py",
                        "no_agent": True,
                        "prompt": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = module.run_gate(args)

    assert report["status"] == "updated"
    assert report["checks"]["existing_job_needs_update"] is True
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    assert jobs[0]["no_agent"] is False
    assert "用中文" in jobs[0]["prompt"]
    assert "全貌" in jobs[0]["prompt"]
    assert "不要只列命令" in jobs[0]["prompt"]


def test_cron_gate_recurring_channel_survives_provider_config_merge(tmp_path):
    module = _load_gate_module()
    report = module.run_gate(_args(module, tmp_path, apply=True, owner_approved=True))
    assert report["status"] == "applied"

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from plugins.memory.memory_os.config import load_config

    owner_review = load_config(tmp_path / "home")["owner_review"]
    assert owner_review["recurring_delivery_channel"] == "telegram"
    assert owner_review["recurring_delivery_target_class"] == "explicit_target"


def test_cron_gate_blocks_unsafe_render_output(tmp_path, monkeypatch):
    module = _load_gate_module()
    monkeypatch.setenv("FAKE_UNSAFE_RENDER", "1")
    report = module.run_gate(_args(module, tmp_path))

    assert report["status"] == "blocked"
    assert any(item["code"] == "render_check_internal_schema_primary" for item in report["findings"])


def test_cron_gate_blocks_local_delivery_target(tmp_path):
    module = _load_gate_module()
    report = module.run_gate(_args(module, tmp_path, deliver="local"))

    assert report["status"] == "blocked"
    assert any(item["code"] == "deliver_target_local_not_owner_channel" for item in report["findings"])


def test_cron_gate_accepts_origin_delivery_target(tmp_path):
    module = _load_gate_module()
    report = module.run_gate(_args(module, tmp_path, deliver="origin"))

    assert report["status"] == "dry_run"
    assert report["deliver_target_class"] == "origin"
    assert not any(item["severity"] == "error" for item in report["findings"])


def test_cron_gate_blocks_unresolved_auto_delivery_target(tmp_path):
    module = _load_gate_module()
    report = module.run_gate(_args(module, tmp_path, deliver="auto"))

    assert report["status"] == "blocked"
    assert any(item["code"] == "deliver_target_auto_unresolved" for item in report["findings"])
