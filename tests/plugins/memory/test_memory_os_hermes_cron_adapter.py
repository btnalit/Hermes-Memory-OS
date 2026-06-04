import subprocess

from plugins.memory.memory_os.cron_registry import memory_os_cron_spec_by_key, memory_os_cron_specs
from plugins.memory.memory_os.hermes_cron_adapter import classify_hermes_cron_jobs, plan_hermes_cron_job_upsert
from plugins.memory.memory_os.hermes_cron_adapter import HermesCronDesiredJob
from plugins.memory.memory_os.hermes_cron_adapter import probe_hermes_cron_capabilities


def test_hermes_cron_adapter_classifies_wrapped_naked_and_unregistered_jobs():
    cadence = memory_os_cron_spec_by_key("module_cadence_report")
    assert cadence is not None

    summary = classify_hermes_cron_jobs(
        [
            {"name": cadence.name, "script": cadence.wrapper_script, "enabled": True},
            {"name": "memory-os-proposal-followups-opsgate", "script": "memory_os_proposal_followups_ops_gate.py"},
            {"name": "memory-os-extra", "script": "memory_os_extra.py"},
            {"name": "hermes-heartbeat", "script": "hermes_heartbeat.py"},
        ],
        memory_os_cron_specs(),
    )

    assert summary["memory_os_owned_wrapped_count"] == 1
    assert summary["memory_os_owned_naked_count"] == 1
    assert summary["memory_os_like_unregistered_count"] == 1
    assert summary["hermes_host_owned_count"] == 1
    assert summary["active_registry_job_count"] == len(memory_os_cron_specs())
    assert summary["enabled_memory_os_job_count"] == 1


def test_hermes_cron_adapter_counts_enabled_known_optional_jobs_outside_active_registry():
    owner_review = memory_os_cron_spec_by_key("owner_review_digest")
    memory_sources = memory_os_cron_spec_by_key("memory_sources_feedback_request")
    right_brain = memory_os_cron_spec_by_key("right_brain_expression")
    assert owner_review is not None
    assert memory_sources is not None
    assert right_brain is not None

    summary = classify_hermes_cron_jobs(
        [
            {"name": owner_review.name, "script": owner_review.wrapper_script, "enabled": True},
            {"name": memory_sources.name, "script": memory_sources.wrapper_script, "enabled": True},
            {"name": right_brain.name, "script": right_brain.wrapper_script, "enabled": False},
        ],
        [owner_review],
    )

    assert summary["active_registry_job_count"] == 1
    assert summary["memory_os_owned_wrapped_count"] == 1
    assert summary["memory_os_known_optional_count"] == 2
    assert summary["enabled_known_optional_outside_active_registry_count"] == 1
    assert summary["enabled_memory_os_job_count"] == 2
    assert summary["enabled_known_optional_outside_active_registry_jobs"] == [
        {
            "name": memory_sources.name,
            "script": memory_sources.wrapper_script,
            "enabled": True,
            "deliver": "",
            "no_agent": False,
            "known_registry_key": memory_sources.key,
            "known_optional_reason": "not_in_active_installed_snapshot",
        }
    ]


def test_hermes_cron_adapter_upsert_plan_owns_schedule_prompt_wrapper_and_no_agent():
    spec = memory_os_cron_spec_by_key("module_cadence_report")
    assert spec is not None
    desired = HermesCronDesiredJob(
        spec=spec,
        schedule="*/10 * * * *",
        deliver="local",
        prompt="",
        wrapper_script=spec.wrapper_script,
        no_agent=True,
    )

    plan = plan_hermes_cron_job_upsert(
        "hermes",
        desired,
        existing_job={
            "id": "job1",
            "name": spec.name,
            "schedule_display": "*/30 * * * *",
            "deliver": "telegram",
            "prompt": "old",
            "script": spec.raw_script,
            "no_agent": False,
        },
    )

    assert plan.status == "edit"
    assert set(plan.migration_fields) == {"schedule", "prompt", "deliver", "wrapper_script", "no_agent"}
    assert plan.command[:3] == ["hermes", "cron", "edit"]
    assert "--script" in plan.command
    assert "--no-agent" in plan.command
    assert plan.command[-1] == "job1"


def test_hermes_cron_adapter_blocks_edit_without_job_id():
    spec = memory_os_cron_spec_by_key("module_cadence_report")
    assert spec is not None
    desired = HermesCronDesiredJob(
        spec=spec,
        schedule="*/10 * * * *",
        deliver="local",
        prompt="",
        wrapper_script=spec.wrapper_script,
        no_agent=True,
    )

    plan = plan_hermes_cron_job_upsert("hermes", desired, existing_job={"name": spec.name})

    assert plan.status == "blocked"
    assert plan.reason == "existing_job_id_missing"


def test_hermes_cron_adapter_probe_reports_timeout_as_incompatible(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)

    capabilities = probe_hermes_cron_capabilities("hermes")

    assert capabilities.status == "incompatible"
    assert any(item["code"] == "hermes_cron_create_help_unavailable" for item in capabilities.findings)
    assert any(item["code"] == "hermes_cron_edit_help_unavailable" for item in capabilities.findings)
