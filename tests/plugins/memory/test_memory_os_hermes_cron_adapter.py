import subprocess

from plugins.memory.memory_os.cron_registry import memory_os_cron_spec_by_key, memory_os_cron_specs
from plugins.memory.memory_os import hermes_cron_adapter as legacy_cron_adapter
from plugins.seam.hermes_memory_os.cron_adapter import classify_hermes_cron_jobs, plan_hermes_cron_job_upsert
from plugins.seam.hermes_memory_os.cron_adapter import HermesCronDesiredJob
from plugins.seam.hermes_memory_os.cron_adapter import probe_hermes_cron_capabilities


def test_hermes_cron_adapter_classifies_wrapped_naked_and_unregistered_jobs():
    cadence = memory_os_cron_spec_by_key("module_cadence_report")
    governance = memory_os_cron_spec_by_key("proposal_followups_opsgate")
    assert cadence is not None
    assert governance is not None

    summary = classify_hermes_cron_jobs(
        [
            {"name": cadence.name, "script": cadence.wrapper_script, "enabled": True},
            # "Naked": a live job name running the lane helper DIRECTLY instead
            # of through its ExecutionGate wrapper, so it produces no permit.
            {"name": governance.name, "script": governance.raw_script},
            {"name": "memory-os-extra", "script": "memory_os_extra.py"},
            {"name": "hermes-heartbeat", "script": "hermes_heartbeat.py"},
        ],
        memory_os_cron_specs(),
    )

    assert summary["memory_os_owned_wrapped_count"] == 1
    assert summary["memory_os_owned_naked_count"] == 1
    assert summary["memory_os_like_unregistered_count"] == 1
    assert summary["hermes_host_owned_count"] == 1
    # One entry per Hermes JOB, not per lane -- several lanes share a group tick.
    assert summary["active_registry_job_count"] == len({spec.name for spec in memory_os_cron_specs()})
    assert summary["enabled_memory_os_job_count"] == 1


def test_hermes_cron_adapter_separates_retired_legacy_from_known_optional_jobs():
    owner_review = memory_os_cron_spec_by_key("owner_review_digest")
    memory_sources = memory_os_cron_spec_by_key("memory_sources_feedback_request")
    right_brain = memory_os_cron_spec_by_key("right_brain_expression")
    assert owner_review is not None
    assert memory_sources is not None
    assert right_brain is None

    summary = classify_hermes_cron_jobs(
        [
            {"name": owner_review.name, "script": owner_review.wrapper_script, "enabled": True},
            {"name": memory_sources.name, "script": memory_sources.wrapper_script, "enabled": True},
            {
                "name": "memory-os-right-brain-expression",
                "script": "memory_os_cron_right_brain_expression_gate.py",
                "enabled": False,
            },
        ],
        [owner_review],
    )

    assert summary["active_registry_job_count"] == 1
    assert summary["memory_os_owned_wrapped_count"] == 1
    assert summary["memory_os_known_optional_count"] == 1
    assert summary["memory_os_retired_legacy_count"] == 1
    assert summary["enabled_retired_legacy_count"] == 0
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


def test_hermes_cron_adapter_classifies_legacy_per_lane_jobs_as_superseded_known_optional():
    # Post-consolidation registry: the passed-in "active/installed" specs are
    # the full (already-onboarded) registry, so every spec.name is now a
    # group tick name (e.g. "memory-os-tick-evidence"), not a per-lane name.
    # A leftover pre-consolidation per-lane job -- name "memory-os-<lane>"
    # running "memory_os_cron_<lane>_gate.py" -- must NOT fall through to
    # unregistered_like (which the 3.200 monitor treats as a FAIL).
    specs = memory_os_cron_specs()
    jobs = [
        {"name": "memory-os-index-sync", "script": "memory_os_cron_index_sync_gate.py", "enabled": True},
        {"name": "memory-os-working-cleanup", "script": "memory_os_cron_working_cleanup_gate.py", "enabled": False},
    ]

    summary = legacy_cron_adapter.classify_hermes_cron_jobs(jobs, specs)

    assert summary["memory_os_like_unregistered_count"] == 0
    assert summary["memory_os_known_optional_count"] == 2
    assert summary["enabled_known_optional_outside_active_registry_count"] == 1
    # Total enabled Memory-OS-owned job count is unaffected by which bucket
    # an enabled job lands in -- both known_optional and unregistered_like
    # feed enabled_memory_os_job_count, so reclassifying must not drop it.
    assert summary["enabled_memory_os_job_count"] == 1
    reasons = {job["known_registry_key"]: job["known_optional_reason"] for job in summary["known_optional_jobs"]}
    assert reasons == {
        "memory-os-index-sync": "superseded_by_group_tick",
        "memory-os-working-cleanup": "superseded_by_group_tick",
    }


def test_hermes_cron_adapter_legacy_hindsight_probe_job_gets_superseded_reason_not_generic_one():
    # memory_os_hindsight_health_probe.py is BOTH the legacy per-lane wrapper
    # script for "memory-os-hindsight-health-probe" AND the current
    # hindsight_health_probe lane's raw_script (a tick_evidence member). The
    # known_specs_by_raw lookup would match this script too and tag it
    # "not_in_active_installed_snapshot" -- the legacy check must win first
    # so the more precise "superseded_by_group_tick" reason is reported.
    specs = memory_os_cron_specs()
    jobs = [
        {"name": "memory-os-hindsight-health-probe", "script": "memory_os_hindsight_health_probe.py", "enabled": True},
    ]

    summary = legacy_cron_adapter.classify_hermes_cron_jobs(jobs, specs)

    assert summary["memory_os_like_unregistered_count"] == 0
    assert summary["memory_os_known_optional_count"] == 1
    job = summary["known_optional_jobs"][0]
    assert job["known_optional_reason"] == "superseded_by_group_tick"
    assert job["known_registry_key"] == "memory-os-hindsight-health-probe"


def test_hermes_cron_adapter_active_tick_evidence_job_stays_wrapped_despite_hindsight_raw_script_collision():
    # The ACTIVE group job for the tick_evidence group (whose members include
    # the hindsight_health_probe lane) must still resolve via the by-name
    # branch and land in "wrapped", never in the legacy known_optional bucket.
    hindsight_lane = memory_os_cron_spec_by_key("hindsight_health_probe")
    assert hindsight_lane is not None
    specs = memory_os_cron_specs()
    jobs = [
        {"name": hindsight_lane.name, "script": hindsight_lane.wrapper_script, "enabled": True},
    ]

    summary = legacy_cron_adapter.classify_hermes_cron_jobs(jobs, specs)

    assert summary["memory_os_owned_wrapped_count"] == 1
    assert summary["memory_os_known_optional_count"] == 0
    assert summary["memory_os_like_unregistered_count"] == 0


def test_hermes_cron_adapters_classify_raw_script_aliases_as_enabled_retired_legacy():
    jobs = [
        {
            "name": "renamed-expression-job",
            "script": "memory_os_right_brain_expression.py",
            "enabled": True,
        },
        {
            "name": "renamed-outcome-job",
            "script": "memory_os_right_brain_expression_outcome_cron.py",
            "enabled": True,
        },
    ]

    for classifier in (classify_hermes_cron_jobs, legacy_cron_adapter.classify_hermes_cron_jobs):
        summary = classifier(jobs, ())
        assert summary["memory_os_retired_legacy_count"] == 2
        assert summary["enabled_retired_legacy_count"] == 2
        assert summary["memory_os_like_unregistered_count"] == 0


def test_hermes_cron_adapter_classifies_renamed_ragflow_probe_as_external_seam_job():
    summary = classify_hermes_cron_jobs(
        [
            {
                "name": "external-evidence-ragflow-readonly-probe",
                "script": "external_evidence_ragflow_readonly_probe.sh",
                "enabled": True,
                "deliver": "local",
                "no_agent": True,
            }
        ],
        (),
    )

    assert summary["memory_os_like_unregistered_count"] == 0
    assert summary["memory_os_owned_expected_count"] == 0
    assert summary["external_unmanaged_count"] == 1
    assert summary["external_unmanaged_jobs"] == [
        {
            "name": "external-evidence-ragflow-readonly-probe",
            "script": "external_evidence_ragflow_readonly_probe.sh",
            "enabled": True,
            "deliver": "local",
            "no_agent": True,
        }
    ]


def test_hermes_cron_host_seam_shadow_matches_legacy_adapter():
    specs = memory_os_cron_specs()
    jobs = [
        {
            "id": "job-1",
            "name": specs[0].name,
            "script": specs[0].wrapper_script,
            "enabled": True,
            "deliver": "local",
            "no_agent": True,
        },
        {
            "id": "job-2",
            "name": "external-evidence-ragflow-readonly-probe",
            "script": "external_evidence_ragflow_readonly_probe.sh",
            "enabled": True,
            "deliver": "local",
            "no_agent": True,
        },
    ]

    assert classify_hermes_cron_jobs(jobs, specs) == legacy_cron_adapter.classify_hermes_cron_jobs(
        jobs, specs
    )


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


def test_seam_adapter_classifies_legacy_per_lane_jobs_as_superseded_not_drift():
    """Counterfactual for the PRODUCTION classification path.

    memory_os_cron_adapter_probe.py imports classify_hermes_cron_jobs from the
    seam module, and the 3.200 monitor prefers that probe's report. A leftover
    pre-consolidation per-lane job must land in known_optional; falling through
    to unregistered_like makes the monitor FAIL
    (execution_gate_memory_os_cron_unregistered_like_job) on every upgraded
    host, since group consolidation means no active spec carries those names.
    """
    summary = classify_hermes_cron_jobs(
        [
            {"name": "memory-os-index-sync", "script": "memory_os_cron_index_sync_gate.py", "enabled": False},
            {"name": "memory-os-working-cleanup", "script": "memory_os_cron_working_cleanup_gate.py", "enabled": False},
        ],
        memory_os_cron_specs(),
    )

    assert summary["memory_os_like_unregistered_count"] == 0
    assert summary["memory_os_known_optional_count"] == 2
    assert all(
        job["known_optional_reason"] == "superseded_by_group_tick"
        for job in summary["known_optional_jobs"]
    )


def test_seam_and_memory_adapters_agree_on_legacy_per_lane_classification():
    """The two copies of this logic must not diverge -- the seam one is what
    production reads, the memory one is what most tests exercise."""
    jobs = [{"name": "memory-os-fact-judge", "script": "memory_os_cron_fact_judge_gate.py", "enabled": False}]

    seam = classify_hermes_cron_jobs(jobs, memory_os_cron_specs())
    memory = legacy_cron_adapter.classify_hermes_cron_jobs(jobs, memory_os_cron_specs())

    assert seam["memory_os_known_optional_count"] == memory["memory_os_known_optional_count"] == 1
    assert seam["memory_os_like_unregistered_count"] == memory["memory_os_like_unregistered_count"] == 0
    assert (
        seam["known_optional_jobs"][0]["known_optional_reason"]
        == memory["known_optional_jobs"][0]["known_optional_reason"]
        == "superseded_by_group_tick"
    )


def test_seam_and_legacy_adapter_classify_identically_across_all_buckets():
    """T2 pin: production reads the seam copy, tooling reads the in-package
    copy — two near-identical implementations of the same classifier. This
    full-dict equality over one fixture spanning every bucket turns any
    future one-sided edit into a loud failure instead of silent vocabulary
    drift. (The monitor's embedded third copy is DELIBERATELY divergent and
    is pinned separately in tests/scripts/test_memory_os_3_200_monitor.py —
    never assert equality against it.)"""
    from plugins.memory.memory_os.cron_registry import (
        LEGACY_PER_LANE_CRON_JOBS,
        RETIRED_MEMORY_OS_CRON_SCRIPTS,
    )

    cadence = memory_os_cron_spec_by_key("module_cadence_report")
    governance = memory_os_cron_spec_by_key("proposal_followups_opsgate")
    legacy_name, legacy_script = sorted(LEGACY_PER_LANE_CRON_JOBS.items())[0]
    retired_name, retired_script = sorted(RETIRED_MEMORY_OS_CRON_SCRIPTS.items())[0]
    jobs = [
        {"name": cadence.name, "script": cadence.wrapper_script, "enabled": True},
        {"name": governance.name, "script": governance.raw_script, "enabled": True},
        {"name": legacy_name, "script": legacy_script, "enabled": False},
        {"name": retired_name, "script": retired_script, "enabled": False},
        {"name": "hermes-heartbeat", "script": "hermes_heartbeat.py", "enabled": True},
        {"name": "backup-nightly", "script": "backup.sh", "enabled": True},
        {"name": "memory-os-mystery", "script": "mystery_helper.py", "enabled": True},
    ]

    seam = classify_hermes_cron_jobs(jobs, memory_os_cron_specs())
    legacy = legacy_cron_adapter.classify_hermes_cron_jobs(jobs, memory_os_cron_specs())

    assert seam == legacy, (
        "seam and in-package classify_hermes_cron_jobs diverged — every "
        "change must be applied to both copies (and reviewed against the "
        "monitor's embedded third copy)"
    )
