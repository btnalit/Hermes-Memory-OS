from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from plugins.memory.memory_os.cron_registry import (
    memory_os_cron_groups,
    memory_os_cron_spec_by_key,
    memory_os_cron_specs,
)


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_owner_cron_onboarding.py"
    spec = importlib.util.spec_from_file_location("memory_os_owner_cron_onboarding", path)
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
    print("usage: hermes cron create [--name NAME] [--deliver DELIVER] [--script SCRIPT] [--no-agent] schedule prompt")
    raise SystemExit(0)

if args[:3] == ["memory-os-agent-os", "review", "render-digest"]:
    print("Memory-OS owner review digest\\nA1 Human readable proposal")
    raise SystemExit(0)

if args[:2] == ["cron", "create"]:
    def value(flag):
        return args[args.index(flag) + 1] if flag in args else ""
    positionals = []
    i = 2
    while i < len(args):
        if args[i] in {"--name", "--deliver", "--script"}:
            i += 2
        elif args[i] == "--no-agent":
            i += 1
        else:
            positionals.append(args[i])
            i += 1
    schedule = positionals[0] if positionals else ""
    prompt = positionals[1] if len(positionals) > 1 else ""
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    if jobs_path.exists():
        loaded = json.loads(jobs_path.read_text(encoding="utf-8"))
    else:
        loaded = {"jobs": []}
    jobs = loaded.get("jobs", [])
    job_name = value("--name")
    job = {
        "id": "job_" + job_name.replace("-", "_"),
        "name": job_name,
        "enabled": True,
        "deliver": value("--deliver"),
        "script": value("--script"),
        "no_agent": "--no-agent" in args,
        "schedule_display": schedule,
        "schedule": {"kind": "cron", "expr": schedule},
        "prompt": prompt,
    }
    jobs.append(job)
    jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    print("created", job["id"])
    raise SystemExit(0)

if args[:2] == ["cron", "edit"]:
    def value(flag):
        return args[args.index(flag) + 1] if flag in args else None
    jobs_path = home / "cron" / "jobs.json"
    loaded = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = loaded.get("jobs", [])
    job_id = args[-1]
    for job in jobs:
        if job.get("id") == job_id:
            if value("--schedule") is not None:
                job["schedule_display"] = value("--schedule")
                job["schedule"] = {"kind": "cron", "expr": value("--schedule")}
            if value("--prompt") is not None:
                job["prompt"] = value("--prompt")
            if value("--name") is not None:
                job["name"] = value("--name")
            if value("--deliver") is not None:
                job["deliver"] = value("--deliver")
            if value("--script") is not None:
                job["script"] = value("--script")
            if "--no-agent" in args:
                job["no_agent"] = True
            if "--agent" in args:
                job["no_agent"] = False
            jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
            print("updated", job_id)
            raise SystemExit(0)
    print("missing job", job_id, file=sys.stderr)
    raise SystemExit(2)

if args[:2] == ["cron", "pause"]:
    jobs_path = home / "cron" / "jobs.json"
    loaded = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = loaded.get("jobs", [])
    job_id = args[2]
    for job in jobs:
        if job.get("id") == job_id:
            job["enabled"] = False
            jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
            print("paused", job_id)
            raise SystemExit(0)
    print("missing job", job_id, file=sys.stderr)
    raise SystemExit(2)

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


def _registry_script_names() -> list[str]:
    """Every script onboarding expects on the host, derived from the registry.

    Covers each lane's helper (raw_script) plus each group's cron entrypoint
    (wrapper_script), so adding a lane or a group tick never silently leaves
    this fixture short.
    """
    names: list[str] = []
    for spec in memory_os_cron_specs():
        names.extend([spec.raw_script, spec.wrapper_script])
    # Retired right-brain scripts: not in the registry any more, but several
    # tests place them on the host to assert they get paused/retired.
    names.extend(
        [
            "memory_os_right_brain_expression.py",
            "memory_os_cron_right_brain_expression_gate.py",
            "memory_os_right_brain_expression_outcome_cron.py",
            "memory_os_cron_right_brain_expression_outcome_gate.py",
        ]
    )
    return sorted(dict.fromkeys(names))


def test_execution_gate_asset_install_is_idempotent_in_installed_layout(tmp_path, monkeypatch):
    """Running the deployed onboarding script must not copy a file onto itself."""
    module = _load_module()
    hermes_home = tmp_path / "home"
    scripts_dir = hermes_home / "scripts"
    scripts_dir.mkdir(parents=True)
    execution_runner = scripts_dir / "memory_os_execution_gate_runner.py"
    group_runner = scripts_dir / "memory_os_cron_group_runner.py"
    execution_runner.write_text("# execution\n", encoding="utf-8")
    group_runner.write_text("# group\n", encoding="utf-8")
    monkeypatch.setattr(module, "SOURCE_EXECUTION_GATE_RUNNER", execution_runner)
    monkeypatch.setattr(module, "SOURCE_CRON_GROUP_RUNNER", group_runner)

    module._write_execution_gate_assets(hermes_home=hermes_home, specs=[])

    assert execution_runner.read_text(encoding="utf-8") == "# execution\n"
    assert group_runner.read_text(encoding="utf-8") == "# group\n"
    assert execution_runner.stat().st_mode & 0o100
    assert group_runner.stat().st_mode & 0o100


def _home_with_helpers(
    tmp_path: Path,
    *,
    platforms: dict[str, list[dict[str, str]]],
    omit_helpers: set[str] | None = None,
) -> Path:
    home = tmp_path / "home"
    scripts = home / "scripts"
    scripts.mkdir(parents=True)
    omitted = omit_helpers or set()
    # Derived from the registry rather than hand-listed: a hand-typed script
    # list silently rots whenever the cron surface changes (it did when
    # per-lane jobs were consolidated into group ticks), and the resulting
    # "script_missing" finding blocks onboarding for a reason unrelated to
    # what the test is actually asserting.
    for helper in _registry_script_names():
        if helper in omitted:
            continue
        scripts.joinpath(helper).write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    home.joinpath("channel_directory.json").write_text(
        json.dumps({"platforms": platforms}, ensure_ascii=False),
        encoding="utf-8",
    )
    return home


def test_discovers_configured_owner_channel_without_telegram_default(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [], "discord": [{"id": "room-1", "type": "dm", "name": "owner"}]},
    )

    channels = module.discover_owner_channels(home)

    assert channels[0]["deliver"] == "discord"
    assert channels[0]["source"] == "channel_directory"
    assert all(channel["deliver"] != "telegram" for channel in channels)


def test_onboarding_dry_run_selects_detected_channel_and_does_not_create_jobs(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [], "discord": [{"id": "room-1", "type": "dm", "name": "owner"}]},
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "dry_run"
    assert report["selected_owner_review_deliver"] == "discord"
    assert report["selected_owner_review_channel"] == "discord"
    assert report["selected_right_brain_deliver"] == "origin"
    assert report["apply_requested"] is False
    assert report["cron_profile"] == "active-closure"
    # Derive the expected active-closure job set from the registry itself
    # (via the module's own ACTIVE_CLOSURE_CRON_KEYS), not a hand-typed
    # literal -- a hardcoded list here would silently re-hide the same
    # registry-drift bug (a real registered spec, e.g. clearance_cycle,
    # missing from the active-closure install) that this test exists to
    # catch. See test_active_closure_cron_keys_are_derived_from_the_registry_not_hand_typed
    # for the direct counterfactual on the derivation itself.
    expected_names = {
        spec.name for spec in memory_os_cron_specs()
        if spec.key in module.ACTIVE_CLOSURE_CRON_KEYS
    }
    assert len(report["operational_cron_jobs"]) == len(expected_names)
    assert {job["name"] for job in report["operational_cron_jobs"]} == expected_names
    # Each lane is now scheduled by its GROUP job. Assert the mapping via the
    # registry so this cannot drift back into per-lane job assumptions.
    jobs_by_name = {job["name"]: job for job in report["operational_cron_jobs"]}
    groups_by_name = {group.name: group for group in memory_os_cron_groups()}
    for lane_key, expected_group_job in (
        ("index_sync", "memory-os-tick-derived"),
        ("exposure_rollup", "memory-os-tick-daily"),
        ("hindsight_advisory_digest", "memory-os-tick-daily"),
        ("hindsight_health_probe", "memory-os-tick-evidence"),
    ):
        spec = memory_os_cron_spec_by_key(lane_key)
        assert spec is not None, lane_key
        assert spec.name == expected_group_job, lane_key
        job = jobs_by_name[expected_group_job]
        # Schedule comes from the registry, not a literal, so staggering the
        # tick minutes cannot silently drift this assertion.
        assert job["schedule"] == groups_by_name[expected_group_job].default_schedule, lane_key
        assert job["deliver"] == "local", lane_key
        assert job["no_agent"] is True, lane_key
        # The lane's own helper must be listed among the tick's members.
        assert spec.raw_script in job["raw_scripts"], lane_key

    # full_monitor_refresh keeps a dedicated job (heavyweight, owner-delivered).
    full_monitor = jobs_by_name["memory-os-full-monitor-refresh"]
    assert full_monitor["schedule"] == "30 2 * * *"
    assert full_monitor["script"] == "memory_os_full_monitor_refresh.py"
    assert full_monitor["raw_script"] == "memory_os_full_monitor_refresh.py"
    assert full_monitor["deliver"] == "discord"
    assert full_monitor["no_agent"] is True
    # clearance_cycle is a real registered spec whose helper and gate scripts
    # the installer already deploys, but its activation is DEFERRED (see the
    # comment on ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS): enabling it in the same
    # change that repaired append_terminal would make two never-exercised
    # paths live at once on production. Assert the deferral is real and
    # deliberate -- not the old silent drift.
    assert not [
        job for job in report["operational_cron_jobs"]
        if job["name"] == "memory-os-clearance-cycle"
    ]
    assert "clearance_cycle" in module.ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS
    for job in report["operational_cron_jobs"]:
        assert home.joinpath("scripts", job["script"]).is_file(), job["script"]
    assert not home.joinpath("cron", "jobs.json").exists()


def test_onboarding_fail_closed_when_active_closure_wrapper_script_missing(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "owner", "type": "dm", "name": "owner"}]},
        # The cron entrypoint for index_sync is now its group tick wrapper.
        omit_helpers={"memory_os_cron_tick_derived.py"},
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "blocked"
    assert any(item["code"] == "memory-os-tick-derived_script_missing" for item in report["findings"])
    assert not report["operational_cron_jobs"]


def test_onboarding_apply_requires_owner_approval(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "6808688675", "type": "dm", "name": "owner"}]},
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--apply",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "blocked"
    assert any(item["code"] == "owner_approval_required_for_apply" for item in report["findings"])
    assert not home.joinpath("cron", "jobs.json").exists()


def test_onboarding_apply_creates_owner_review_and_right_brain_cron_jobs(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "6808688675", "type": "dm", "name": "owner"}]},
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--cron-profile",
            "full",
            "--apply",
            "--owner-approved",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "applied"
    assert report["selected_owner_review_deliver"] == "telegram"
    assert report["selected_owner_review_channel"] == "telegram"
    assert report["cron_profile"] == "full"
    # Full profile installs one job per GROUP, not per lane.
    assert len(report["operational_cron_jobs"]) == len({spec.name for spec in memory_os_cron_specs()})
    jobs = json.loads(home.joinpath("cron", "jobs.json").read_text(encoding="utf-8"))["jobs"]
    by_name = {job["name"]: job for job in jobs}
    # One Hermes job per group, derived from the registry so the expected set
    # cannot drift from what onboarding actually installs.
    assert set(by_name) == {spec.name for spec in memory_os_cron_specs()}
    assert by_name["memory-os-owner-review-digest"]["deliver"] == "telegram"
    assert by_name["memory-os-owner-review-digest"]["script"] == "memory_os_cron_owner_review_digest_gate.py"
    assert by_name["memory-os-owner-review-digest"]["no_agent"] is False

    assert by_name["memory-os-module-cadence-report"]["deliver"] == "local"
    assert by_name["memory-os-module-cadence-report"]["script"] == "memory_os_cron_module_cadence_report_gate.py"
    assert by_name["memory-os-module-cadence-report"]["no_agent"] is True
    # Grouped lanes are scheduled by their tick, not by a per-lane job.
    assert by_name["memory-os-tick-daily"]["deliver"] == "local"
    assert by_name["memory-os-tick-daily"]["script"] == "memory_os_cron_tick_daily.py"
    assert by_name["memory-os-tick-daily"]["no_agent"] is True
    assert by_name["memory-os-tick-daily"]["schedule_display"] == "5 0 * * *"
    assert memory_os_cron_spec_by_key("hindsight_advisory_digest").name == "memory-os-tick-daily"
    assert by_name["memory-os-tick-evidence"]["deliver"] == "local"
    assert by_name["memory-os-tick-evidence"]["script"] == "memory_os_cron_tick_evidence.py"
    assert by_name["memory-os-tick-evidence"]["no_agent"] is True
    assert (
        by_name["memory-os-tick-evidence"]["schedule_display"]
        == {g.name: g for g in memory_os_cron_groups()}["memory-os-tick-evidence"].default_schedule
    )
    assert memory_os_cron_spec_by_key("hindsight_health_probe").name == "memory-os-tick-evidence"
    assert home.joinpath("scripts", "memory_os_hindsight_health_probe.py").read_text(encoding="utf-8") == "#!/usr/bin/env python3\n"

    assert by_name["memory-os-tick-governance"]["deliver"] == "local"
    assert by_name["memory-os-tick-governance"]["script"] == "memory_os_cron_tick_governance.py"
    assert by_name["memory-os-tick-governance"]["no_agent"] is True
    assert memory_os_cron_spec_by_key("proposal_followups_opsgate").name == "memory-os-tick-governance"
    assert by_name["memory-os-expression-feedback-request"]["deliver"] == "telegram"
    assert by_name["memory-os-expression-feedback-request"]["script"] == "memory_os_cron_expression_feedback_request_gate.py"
    assert by_name["memory-os-expression-feedback-request"]["no_agent"] is False
    assert by_name["memory-os-memory-sources-feedback-request"]["deliver"] == "telegram"
    assert by_name["memory-os-memory-sources-feedback-request"]["script"] == "memory_os_cron_memory_sources_feedback_request_gate.py"
    assert by_name["memory-os-memory-sources-feedback-request"]["no_agent"] is False
    assert (home / "scripts" / "memory_os_execution_gate_runner.py").is_file()
    assert (home / "scripts" / "memory_os_cron_module_cadence_report_gate.py").is_file()
    memory_sources_prompt = by_name["memory-os-memory-sources-feedback-request"]["prompt"]
    assert "不要写 Cron Run Report" in memory_sources_prompt
    assert "只输出 OWNER_MESSAGE_BEGIN 和 OWNER_MESSAGE_END 之间的内容" in memory_sources_prompt
    config = json.loads(home.joinpath("memory-os", "config.json").read_text(encoding="utf-8"))
    assert config["owner_review"]["recurring_delivery_enabled"] is True
    assert config.get("right_brain_expression", {}).get("recurring_delivery_enabled", False) is False


def test_onboarding_migrates_existing_memory_os_raw_helper_to_gate_wrapper(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "6808688675", "type": "dm", "name": "owner"}]},
    )
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job_memory_os_module_cadence_report",
                        "name": "memory-os-module-cadence-report",
                        "enabled": True,
                        "deliver": "local",
                        "script": "memory_os_module_cadence_report_cron.py",
                        "no_agent": True,
                        "prompt": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--cron-profile",
            "full",
            "--apply",
            "--owner-approved",
        ]
    )

    report = module.run_onboarding(args)

    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    cadence = next(job for job in jobs if job["name"] == "memory-os-module-cadence-report")
    assert report["status"] in {"applied", "updated"}
    assert cadence["script"] == "memory_os_cron_module_cadence_report_gate.py"
    assert any(
        item["name"] == "memory-os-module-cadence-report" and item["status"] == "updated"
        for item in report["operational_cron_jobs"]
    )


def test_active_closure_onboarding_pauses_known_optional_memory_os_jobs(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "owner", "type": "dm", "name": "owner"}]},
    )
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job_right_brain_expression",
                        "name": "memory-os-right-brain-expression",
                        "enabled": True,
                        "deliver": "telegram",
                        "script": "memory_os_cron_right_brain_expression_gate.py",
                        "no_agent": False,
                        "prompt": "",
                    },
                    {
                        "id": "job_right_brain_alias",
                        "name": "renamed-right-brain-outcome",
                        "enabled": True,
                        "deliver": "local",
                        "script": "memory_os_right_brain_expression_outcome_cron.py",
                        "no_agent": True,
                        "prompt": "",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--apply",
            "--owner-approved",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] in {"already_configured", "updated", "applied"}
    assert report["cron_profile"] == "active-closure"
    assert report["paused_optional_cron_jobs"] == [
        {
            "name": "memory-os-right-brain-expression",
            "job_id": "job_right_brain_expression",
            "registry_key": "right_brain_expression",
            "script": "memory_os_cron_right_brain_expression_gate.py",
            "was_enabled": True,
            "status": "paused",
        },
        {
            "name": "renamed-right-brain-outcome",
            "job_id": "job_right_brain_alias",
            "registry_key": "legacy_right_brain_retired",
            "script": "memory_os_right_brain_expression_outcome_cron.py",
            "was_enabled": True,
            "status": "paused",
        },
    ]
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    by_name = {job["name"]: job for job in jobs}
    assert by_name["memory-os-owner-review-digest"]["enabled"] is True
    assert by_name["memory-os-tick-governance"]["enabled"] is True
    assert by_name["memory-os-tick-derived"]["enabled"] is True
    assert by_name["memory-os-tick-derived"]["script"] == "memory_os_cron_tick_derived.py"
    assert by_name["memory-os-tick-derived"]["no_agent"] is True
    # Right-brain expression stays optional (not in active-closure) and gets paused
    assert by_name["memory-os-right-brain-expression"]["enabled"] is False
    assert by_name["renamed-right-brain-outcome"]["enabled"] is False


def test_updates_existing_memory_sources_feedback_cron_prompt(tmp_path, monkeypatch):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "owner", "type": "dm", "name": "owner"}]},
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job_memory_sources",
                        "name": "memory-os-memory-sources-feedback-request",
                        "enabled": True,
                        "deliver": "telegram",
                        "script": "memory_os_memory_sources_feedback_prompt.py",
                        "no_agent": False,
                        "prompt": "旧提示：请写报告",
                        "schedule_display": "30 10 * * *",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--cron-profile",
            "full",
            "--apply",
            "--owner-approved",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "applied"
    memory_sources_job_report = [
        job for job in report["operational_cron_jobs"] if job["name"] == "memory-os-memory-sources-feedback-request"
    ][0]
    assert memory_sources_job_report["status"] == "updated"
    updated_jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    updated_job = [job for job in updated_jobs if job["name"] == "memory-os-memory-sources-feedback-request"][0]
    assert "旧提示" not in updated_job["prompt"]
    assert "不要写 Cron Run Report" in updated_job["prompt"]
    assert "只输出 OWNER_MESSAGE_BEGIN 和 OWNER_MESSAGE_END 之间的内容" in updated_job["prompt"]


def test_active_closure_cron_keys_are_derived_from_the_registry_not_hand_typed():
    """Counterfactual for the registry-drift bug this module fixes.

    ACTIVE_CLOSURE_CRON_KEYS must be computed from memory_os_cron_specs()
    minus an explicit, documented exclusion set -- not a hand-typed
    frozenset literal. Every prior addition to MEMORY_OS_CRON_SPECS updated
    the (then hand-typed) active-closure key set in the same commit,
    except clearance_cycle: its commit registered the spec, wired the
    onboarding CLI schedule arg, and updated the installer, but never added
    the key to ACTIVE_CLOSURE_CRON_KEYS. A fresh active-closure install
    therefore silently never created the clearance_cycle cron job even
    though its helper/gate scripts were deployed by the installer.

    Without the derivation fix this test fails: the hand-typed frozenset has
    no ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS companion (this module previously
    defined none), so an unlisted spec was silently dropped rather than
    deliberately classified.

    Note the distinction this test enforces: clearance_cycle is still not
    onboarded today, but it is now EXCLUDED BY NAME with a documented reason
    (deferred activation) instead of merely being absent from a hand-typed
    list. That is the whole point -- omission must be a decision, not an
    accident.
    """
    module = _load_module()
    all_keys = {spec.key for spec in memory_os_cron_specs()}

    assert module.ACTIVE_CLOSURE_CRON_KEYS == all_keys - module.ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS
    # Both exclusions are documented and deliberate: module_cadence_report is
    # permanent (generated on demand elsewhere); clearance_cycle is deferred
    # pending a separate, observed enablement.
    assert module.ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS == {
        "module_cadence_report",
        "clearance_cycle",
    }
    assert "clearance_cycle" not in module.ACTIVE_CLOSURE_CRON_KEYS
    assert "module_cadence_report" not in module.ACTIVE_CLOSURE_CRON_KEYS
    # Every registered key must be classified one way or the other -- no
    # key silently falls through unclassified.
    assert module.ACTIVE_CLOSURE_CRON_KEYS | module.ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS == all_keys
