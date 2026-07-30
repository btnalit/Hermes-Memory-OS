import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import scripts.memory_os_3_200_monitor as monitor
from scripts.memory_os_3_200_monitor import (
    classify_snapshot,
    compute_deltas,
    find_rh26_heading_anomalies,
    main,
    render_chinese_summary,
    summarize_l4_guard,
    summarize_v7_governance,
)


def test_monitor_script_help_bootstraps_repo_import_path():
    script = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_3_200_monitor.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "No module named 'plugins'" not in result.stderr


def test_neutral_monitor_script_help_preserves_cli_contract():
    script = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_monitor.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "--monitor-profile" in result.stdout
    assert "No module named 'plugins'" not in result.stderr


def test_run_probe_with_stdin_script_does_not_conflict_with_devnull():
    result = monitor._run_probe(
        "",
        "import json\nprint(json.dumps({'ok': True, 'probe': 'stdin'}))\n",
        python_bin=sys.executable,
    )

    assert result == {"ok": True, "probe": "stdin"}


def test_run_probe_timeout_returns_bounded_dict_instead_of_raising(monkeypatch):
    """_run_probe()'s own subprocess.run call had no timeout at all — a hung
    SSH connection or child process could block the whole monitor
    indefinitely, even though every individual command inside the generated
    script is now bounded. TimeoutExpired must be caught and turned into a
    bounded dict, not propagate out of collect_snapshot()/main()."""
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = monitor._run_probe("", "print('unused')", python_bin=sys.executable, timeout_seconds=5)

    assert result == {"_probe_timeout": True, "_probe_timeout_seconds": 5}


def test_collect_snapshot_probe_timeout_short_circuits_to_fail_without_crash(monkeypatch):
    """When _run_probe() reports a timeout, collect_snapshot() must not feed
    the near-empty dict through the summarize_*/classify_snapshot chain (an
    unverified assumption) — it short-circuits to an explicit FAIL with a
    named code, and main()'s exit-code contract (0 vs 2) still works."""
    def fake_run_probe(host, script, python_bin="python3"):
        return {"_probe_timeout": True, "_probe_timeout_seconds": 300}

    monkeypatch.setattr(monitor, "_run_probe", fake_run_probe)

    snapshot = monitor.collect_snapshot(
        host="fake-host", hermes_home="/root/.hermes", python_bin="python3", previous=None, monitor_profile="live",
    )

    assert snapshot["classification"]["status"] == "FAIL"
    assert any(item["code"] == "probe_script_timeout" for item in snapshot["classification"]["fail"])
    # render_chinese_summary must also tolerate the near-empty snapshot.
    assert "监控结果: FAIL" in render_chinese_summary(snapshot)


def test_embedded_remote_command_timeout_is_bounded_and_fail_closed(tmp_path, monkeypatch):
    script = monitor._remote_probe_script(str(tmp_path))
    prefix = script.split("def system_show", 1)[0]
    namespace = {}
    exec(prefix, namespace)

    monkeypatch.setenv("MEMORY_OS_MONITOR_COMMAND_TIMEOUT_SECONDS", "1")

    observed_timeouts = []

    def fake_check_output(command, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"], output=b"partial")

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    result = namespace["run"](["slow-command"])

    assert result["ok"] is False
    assert result["code"] == 124
    assert "partial" in result["out"]
    assert "command_timeout_seconds=1" in result["out"]

    critical_result = namespace["run"](["critical-command"], timeout_seconds=60)
    assert critical_result["code"] == 124
    assert "command_timeout_seconds=60" in critical_result["out"]
    assert observed_timeouts == [1, 60]


def test_embedded_shell_alias_commands_use_bounded_parallel_collection(tmp_path):
    script = monitor._remote_probe_script(str(tmp_path))

    assert "ThreadPoolExecutor(max_workers=workers)" in script
    assert 'MEMORY_OS_MONITOR_COMMAND_WORKERS", "4"' in script
    assert 'MEMORY_OS_MONITOR_COMMAND_TIMEOUT_SECONDS", "20"' in script
    assert '"review_reply": ["hermes", "memory-os-agent-os", "review", "reply"' in script


def test_embedded_cron_fallback_recognizes_retired_jobs_when_adapter_is_unavailable():
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)

    known_specs: Any = namespace["_memory_os_known_cron_specs"]
    assert callable(known_specs)
    specs = known_specs()
    retired = {item["name"]: item for item in specs if item.get("retired") is True}

    assert retired["memory-os-right-brain-expression"]["wrapper_script"] == "memory_os_cron_right_brain_expression_gate.py"
    assert retired["memory-os-right-brain-expression-outcome"]["wrapper_script"] == "memory_os_cron_right_brain_expression_outcome_gate.py"


def test_embedded_cron_fallback_also_recognizes_legacy_pre_wrapper_raw_names():
    """RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES covers two legacy pre-wrapper raw
    script names that RETIRED_MEMORY_OS_CRON_SCRIPTS (keyed by wrapper name)
    doesn't. A host whose jobs.json still carries one of those raw names
    must resolve via known_specs_by_raw, not fall through to
    unregistered_like. The synthetic entry's "name" must not be "" (which
    would collide with any job that has a blank name in known_specs_by_name)."""
    from plugins.memory.memory_os.cron_registry import (
        RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES,
        RETIRED_MEMORY_OS_CRON_SCRIPTS,
    )

    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)
    known_specs: Any = namespace["_memory_os_known_cron_specs"]()
    by_raw = {str(item.get("raw_script") or ""): item for item in known_specs}

    legacy_only = RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES - set(RETIRED_MEMORY_OS_CRON_SCRIPTS.values())
    assert legacy_only, "fixture assumption: at least one legacy-only raw name exists"
    for script in legacy_only:
        assert script in by_raw
        assert by_raw[script]["retired"] is True
        assert by_raw[script]["name"] != ""


def test_execution_gate_cron_summary_classifies_legacy_raw_job_as_known_optional(tmp_path):
    """End-to-end: a jobs.json entry using a legacy pre-wrapper raw script
    name must be classified known_optional (matched via known_specs_by_raw),
    not memory_os_like_unregistered — reproducing (and closing) the exact
    unregistered_like FAIL this diff's retired-job fix targeted, for a host
    that hasn't migrated the job entry to its wrapper name yet."""
    from plugins.memory.memory_os.cron_registry import RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES, RETIRED_MEMORY_OS_CRON_SCRIPTS

    legacy_only = sorted(RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES - set(RETIRED_MEMORY_OS_CRON_SCRIPTS.values()))
    legacy_script = legacy_only[0]

    cron_dir = tmp_path / "cron"
    cron_dir.mkdir(parents=True)
    cron_dir.joinpath("jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {"name": "memory-os-legacy-right-brain", "script": legacy_script, "enabled": False},
                ]
            }
        ),
        encoding="utf-8",
    )

    namespace: dict[str, object] = {}
    original_sys_path = list(sys.path)
    try:
        exec(
            monitor._remote_probe_script(str(tmp_path)).split("\n# ---begin-probe-invocations---", 1)[0],
            namespace,
        )
    finally:
        sys.path[:] = original_sys_path
    namespace["_hermes_home"] = str(tmp_path)

    summary: Any = namespace["execution_gate_cron_summary"]()

    assert summary["memory_os_like_unregistered_count"] == 0
    known_optional_scripts = {job["script"] for job in summary["known_optional_jobs"]}
    assert legacy_script in known_optional_scripts


def test_collect_snapshot_remote_populates_v2_exposure_from_successful_probe(monkeypatch):
    """Fix 1: a successful v2_exposure_and_clearance_probe result from the
    remote SSH probe is consumed directly, instead of leaving
    v2_exposure_monitor/clearance_snapshot_freshness marked
    unavailable_remote_projection (the pre-fix silent-skip behavior)."""
    fake_v2_exposure = {"schema_era_health": "PASS", "conservation_total_passes": True}
    fake_clearance = {"status": "fresh"}

    def fake_run_probe(host, script, python_bin="python3"):
        assert host == "fake-host"
        return {
            "v2_exposure_and_clearance_probe": {
                "ok": True,
                "v2_exposure_monitor": fake_v2_exposure,
                "clearance_snapshot_freshness": fake_clearance,
            },
        }

    monkeypatch.setattr(monitor, "_run_probe", fake_run_probe)

    snapshot = monitor.collect_snapshot(
        host="fake-host", hermes_home="/root/.hermes", python_bin="python3", previous=None, monitor_profile="live",
    )

    assert snapshot["v2_exposure_monitor"] == fake_v2_exposure
    assert snapshot["clearance_snapshot_freshness"] == fake_clearance


def test_collect_snapshot_remote_probe_failure_becomes_explicit_unavailable_with_error_code(monkeypatch):
    """Fix 1: SSH/runtime/bad-JSON style remote sub-probe failure never
    silently skips — it becomes an explicit unavailable+error_code shape
    which classify_snapshot turns into a WARN (Fix 2)."""
    def fake_run_probe(host, script, python_bin="python3"):
        return {"v2_exposure_and_clearance_probe": {"ok": False, "error_code": "ImportError"}}

    monkeypatch.setattr(monitor, "_run_probe", fake_run_probe)

    snapshot = monitor.collect_snapshot(
        host="fake-host", hermes_home="/root/.hermes", python_bin="python3", previous=None, monitor_profile="live",
    )

    assert snapshot["v2_exposure_monitor"] == {"schema_era_health": "unavailable", "error_code": "ImportError"}
    assert snapshot["clearance_snapshot_freshness"] == {"status": "unavailable", "error_code": "ImportError"}
    assert any(
        item["code"] == "v2_exposure_monitor_collection_failed" for item in snapshot["classification"]["warn"]
    )


def test_collect_snapshot_remote_probe_missing_field_is_not_silent(monkeypatch):
    """Defensive: even if the remote probe response is missing the
    v2_exposure_and_clearance_probe field entirely (e.g. an unexpected/older
    remote payload shape), this must still surface as an explicit failure —
    never silently 'unavailable' with no signal at all."""
    def fake_run_probe(host, script, python_bin="python3"):
        return {}

    monkeypatch.setattr(monitor, "_run_probe", fake_run_probe)

    snapshot = monitor.collect_snapshot(
        host="fake-host", hermes_home="/root/.hermes", python_bin="python3", previous=None, monitor_profile="live",
    )

    assert snapshot["v2_exposure_monitor"]["error_code"] == "remote_probe_field_missing"
    assert snapshot["clearance_snapshot_freshness"]["error_code"] == "remote_probe_field_missing"
    assert any(
        item["code"] == "v2_exposure_monitor_collection_failed" for item in snapshot["classification"]["warn"]
    )


def test_collect_snapshot_remote_populates_living_memory_promotion_ledger_from_successful_probe(monkeypatch):
    """BB.6-1: a successful living_memory_promotion_probe result from the
    remote SSH probe is consumed as real ledger counts, instead of leaving
    decision_recovery_failure_count/stale_open_proposal_count stuck at the
    hardcoded-0 placeholders (the pre-fix silent-zero behavior that made
    those FAIL checks structurally unreachable in production)."""
    fake_counts = {
        "proposal_ledger_counts": {"open": 1, "deciding": 0, "approved": 0, "rejected": 0, "deferred": 0, "revoked": 0, "expired": 0},
        "token_ledger_counts": {"open": 0, "consumed": 0, "revoked": 0, "expired": 0},
        "decision_recovery_failure_count": 2,
        "stale_open_proposal_count": 3,
    }

    def fake_run_probe(host, script, python_bin="python3"):
        return {"living_memory_promotion_probe": {"ok": True, "counts": fake_counts}}

    monkeypatch.setattr(monitor, "_run_probe", fake_run_probe)

    snapshot = monitor.collect_snapshot(
        host="fake-host", hermes_home="/root/.hermes", python_bin="python3", previous=None, monitor_profile="live",
    )

    section = snapshot["living_memory_promotion"]
    assert section["decision_recovery_failure_count"] == 2
    assert section["stale_open_proposal_count"] == 3
    assert section["ledger_state_collection_status"] == "collected"
    fail_codes = {item["code"] for item in snapshot["classification"]["fail"]}
    assert "living_memory_decision_recovery_failure" in fail_codes
    assert "living_memory_stale_open_proposal" in fail_codes


def test_collect_snapshot_remote_ledger_probe_failure_becomes_explicit_warn(monkeypatch):
    """BB.6-1: SSH/runtime/bad-JSON style remote ledger sub-probe failure
    never silently leaves the ledger counts looking like a verified zero —
    it becomes an explicit unavailable+error_code shape which classify_snapshot
    turns into a WARN (never a silent pass)."""
    def fake_run_probe(host, script, python_bin="python3"):
        return {"living_memory_promotion_probe": {"ok": False, "error_code": "ImportError"}}

    monkeypatch.setattr(monitor, "_run_probe", fake_run_probe)

    snapshot = monitor.collect_snapshot(
        host="fake-host", hermes_home="/root/.hermes", python_bin="python3", previous=None, monitor_profile="live",
    )

    section = snapshot["living_memory_promotion"]
    assert section["ledger_state_collection_status"] == "unavailable"
    assert section["ledger_state_collection_error_code"] == "ImportError"
    assert any(
        item["code"] == "living_memory_promotion_ledger_state_collection_failed"
        for item in snapshot["classification"]["warn"]
    )


def test_collect_snapshot_remote_ledger_probe_missing_field_is_not_silent(monkeypatch):
    """Defensive: even if the remote probe response is missing the
    living_memory_promotion_probe field entirely, this must still surface
    as an explicit failure — never silently 'unavailable' with no signal."""
    def fake_run_probe(host, script, python_bin="python3"):
        return {}

    monkeypatch.setattr(monitor, "_run_probe", fake_run_probe)

    snapshot = monitor.collect_snapshot(
        host="fake-host", hermes_home="/root/.hermes", python_bin="python3", previous=None, monitor_profile="live",
    )

    section = snapshot["living_memory_promotion"]
    assert section["ledger_state_collection_status"] == "unavailable"
    assert section["ledger_state_collection_error_code"] == "remote_probe_field_missing"


def test_collect_snapshot_remote_probe_field_present_but_not_dict_is_not_silent(monkeypatch):
    """Defensive: an unexpected remote payload shape where the probe field
    is present but not a dict (e.g. a string/list from a version-skewed
    remote script) must be treated the same as a missing field — explicit
    unavailable+error_code, never a silent pass. Covers the
    _consume_remote_probe branch that a present-but-absent test cannot."""
    def fake_run_probe(host, script, python_bin="python3"):
        return {
            "v2_exposure_and_clearance_probe": "not-a-dict",
            "living_memory_promotion_probe": ["also", "not", "a", "dict"],
        }

    monkeypatch.setattr(monitor, "_run_probe", fake_run_probe)

    snapshot = monitor.collect_snapshot(
        host="fake-host", hermes_home="/root/.hermes", python_bin="python3", previous=None, monitor_profile="live",
    )

    assert snapshot["v2_exposure_monitor"]["error_code"] == "remote_probe_field_missing"
    assert snapshot["clearance_snapshot_freshness"]["error_code"] == "remote_probe_field_missing"
    section = snapshot["living_memory_promotion"]
    assert section["ledger_state_collection_error_code"] == "remote_probe_field_missing"


def test_consume_remote_probe_returns_payload_and_empty_error_code_when_ok():
    """Direct unit test: ok payload -- the whole probe dict comes back as
    the payload (call sites pick fields themselves), error_code is ""."""
    raw = {"some_probe": {"ok": True, "counts": {"open": 1}}}

    payload, error_code = monitor._consume_remote_probe(raw, "some_probe")

    assert payload == {"ok": True, "counts": {"open": 1}}
    assert error_code == ""


def test_consume_remote_probe_ok_false_with_error_code_returns_it():
    """Direct unit test: ok is False and error_code is present/truthy ->
    payload is None, error_code is passed through verbatim."""
    raw = {"some_probe": {"ok": False, "error_code": "ImportError", "error_detail": "boom"}}

    payload, error_code = monitor._consume_remote_probe(raw, "some_probe")

    assert payload is None
    assert error_code == "ImportError"


def test_consume_remote_probe_missing_key_falls_back():
    """Direct unit test: probe_key absent from raw entirely -> fallback."""
    payload, error_code = monitor._consume_remote_probe({}, "some_probe")

    assert payload is None
    assert error_code == "remote_probe_field_missing"


def test_consume_remote_probe_non_dict_value_falls_back():
    """Direct unit test: probe_key present but the value is not a dict ->
    same fallback as a missing key, never crashes on .get()."""
    payload, error_code = monitor._consume_remote_probe({"some_probe": "oops"}, "some_probe")

    assert payload is None
    assert error_code == "remote_probe_field_missing"


def test_consume_remote_probe_dict_without_error_code_falls_back():
    """Direct unit test: probe is a dict, ok is not True, and error_code is
    absent (or falsy) -> falls back to remote_probe_field_missing rather
    than surfacing None/"" as a fake error code."""
    payload, error_code = monitor._consume_remote_probe({"some_probe": {"ok": False}}, "some_probe")

    assert payload is None
    assert error_code == "remote_probe_field_missing"

    payload2, error_code2 = monitor._consume_remote_probe(
        {"some_probe": {"ok": False, "error_code": ""}}, "some_probe"
    )

    assert payload2 is None
    assert error_code2 == "remote_probe_field_missing"


def test_production_living_memory_ledger_collection_failure_escalates_to_fail():
    """Counterfactual for the WARN-ordering fix: the ledger-collection WARN is
    registered fail_if_production, so classify_snapshot must append it BEFORE
    the clean-host/production escalation loop. If it is appended after the
    loop (the pre-fix ordering), a production remote ledger-collection failure
    can only ever WARN and the fail_if_production contract is dead code."""
    snapshot = _healthy_snapshot()
    snapshot["living_memory_promotion"] = monitor.summarize_living_memory_promotion(
        ledger_collection_error="ImportError",
    )

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "living_memory_promotion_ledger_state_collection_failed"
        for item in classification["warn"]
    )
    assert any(
        item["code"] == "living_memory_promotion_ledger_state_collection_failed_in_production"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["fail"]
    )
    assert classification["status"] == "FAIL"


def test_clean_host_living_memory_ledger_collection_failure_stays_classified_warn():
    """Clean-host counterpart: the same collection failure stays an expected
    WARN (expected_clean_host classification record, no escalation, no
    clean_host_warn_unclassified FAIL)."""
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["living_memory_promotion"] = monitor.summarize_living_memory_promotion(
        ledger_collection_error="ImportError",
    )

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "living_memory_promotion_ledger_state_collection_failed"
        for item in classification["warn"]
    )
    assert not any(item["code"] == "clean_host_warn_unclassified" for item in classification["fail"])
    assert not any(
        item["code"] == "living_memory_promotion_ledger_state_collection_failed_in_production"
        for item in classification["fail"]
    )
    assert any(
        item["code"] == "living_memory_promotion_ledger_state_collection_failed"
        and item["classification"] == "expected_clean_host"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["clean_host_warn_classification"]
    )


def test_production_living_memory_stale_open_evaluation_unavailable_escalates_to_fail():
    """Counterfactual (P1 #4): a collected ledger whose stale-open evaluation
    failed inside read_permanent_promotion_ledger_counts previously had no
    consumer anywhere — stale_open_proposal_count stayed 0 and the section
    still reported collected, so real stale proposals were silently
    under-reported as a verified-clean zero. The unavailable status must WARN
    and, being registered fail_if_production, escalate to FAIL on production
    (via the BD.1 end-of-function classification loop)."""
    snapshot = _healthy_snapshot()
    snapshot["living_memory_promotion"] = monitor.summarize_living_memory_promotion(
        ledger_counts={
            "stale_open_proposal_count": 0,
            "stale_open_evaluation_status": "unavailable",
            "stale_open_evaluation_error_code": "OSError",
        },
    )

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "living_memory_stale_open_evaluation_unavailable"
        and item["value"] == "OSError"
        for item in classification["warn"]
    )
    assert any(
        item["code"] == "living_memory_stale_open_evaluation_unavailable_in_production"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["fail"]
    )
    assert classification["status"] == "FAIL"


def test_clean_host_living_memory_stale_open_evaluation_unavailable_stays_classified_warn():
    """Clean-host counterpart: a clean host may not have a warmed
    crystallized-record store yet, so the same evaluation failure stays an
    expected_clean_host WARN (no escalation, no clean_host_warn_unclassified
    FAIL)."""
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["living_memory_promotion"] = monitor.summarize_living_memory_promotion(
        ledger_counts={
            "stale_open_proposal_count": 0,
            "stale_open_evaluation_status": "unavailable",
            "stale_open_evaluation_error_code": "OSError",
        },
    )

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "living_memory_stale_open_evaluation_unavailable"
        for item in classification["warn"]
    )
    assert not any(item["code"] == "clean_host_warn_unclassified" for item in classification["fail"])
    assert not any(
        item["code"] == "living_memory_stale_open_evaluation_unavailable_in_production"
        for item in classification["fail"]
    )
    assert any(
        item["code"] == "living_memory_stale_open_evaluation_unavailable"
        and item["classification"] == "expected_clean_host"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["clean_host_warn_classification"]
    )


def test_summarize_collected_counts_missing_stale_open_evaluation_status_never_reads_ok():
    """Counterfactual (P1 #4, version-skew guard): a remote probe can report
    ok=True with a counts dict from an older deployed plugin that predates
    stale_open_evaluation_status. On a collected section the missing key must
    be deliberately marked unavailable — indistinguishable from a failed
    evaluation, never from a healthy one."""
    section = monitor.summarize_living_memory_promotion(ledger_counts={})

    assert section["ledger_state_collection_status"] == "collected"
    assert section["stale_open_evaluation_status"] == "unavailable"
    assert section["stale_open_evaluation_error_code"] == "missing_from_collected_counts"

    snapshot = _healthy_snapshot()
    snapshot["living_memory_promotion"] = section
    classification = classify_snapshot(snapshot)
    assert any(
        item["code"] == "living_memory_stale_open_evaluation_unavailable"
        and item["value"] == "missing_from_collected_counts"
        for item in classification["warn"]
    )


def test_summarize_living_memory_promotion_local_ledger_read_failure_does_not_crash(tmp_path):
    """A non-UTF-8 line is isolated, counted, and remains fail-visible."""
    system = tmp_path / "memory-os" / "system"
    system.mkdir(parents=True)
    (system / "permanent_promotion_proposals.jsonl").write_bytes(b"\xff\xfe not utf-8 \xff")

    section = monitor.summarize_living_memory_promotion(memory_os_root=tmp_path / "memory-os")

    assert section["ledger_state_collection_status"] == "collected"
    assert section["ledger_read_suppressed_error_count"] == 1

    snapshot = _healthy_snapshot()
    snapshot["living_memory_promotion"] = section
    classification = classify_snapshot(snapshot)
    assert any(
        item["code"] == "living_memory_promotion_ledger_partial_read"
        and item["value"] == 1
        for item in classification["fail"]
    )


def test_summarize_with_no_ledger_source_reports_ledger_state_not_supplied():
    """Counterfactual (P2 #9, Section W rule 4): when ALL THREE ledger params
    are None, the section previously kept its hard-zero placeholders with NO
    ledger_state_collection_status key at all — an implicit fourth path
    indistinguishable from healthy verified zeros.  The unconditional else
    must mark it unavailable with error_code ledger_state_not_supplied, and
    classify_snapshot must emit the ledger-collection-failed WARN, escalating
    to FAIL on the production profile."""
    section = monitor.summarize_living_memory_promotion()

    assert section["ledger_state_collection_status"] == "unavailable"
    assert section["ledger_state_collection_error_code"] == "ledger_state_not_supplied"

    snapshot = _healthy_snapshot()
    snapshot["living_memory_promotion"] = section
    classification = classify_snapshot(snapshot)
    assert any(
        item["code"] == "living_memory_promotion_ledger_state_collection_failed"
        and item["value"] == "ledger_state_not_supplied"
        for item in classification["warn"]
    )
    assert any(
        item["code"] == "living_memory_promotion_ledger_state_collection_failed_in_production"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["fail"]
    )
    assert classification["status"] == "FAIL"


def _exec_remote_probe_prefix(namespace: dict[str, object]) -> None:
    original_sys_path = list(sys.path)
    try:
        exec(
            monitor._remote_probe_script("/nonexistent/memory-os-monitor-test-home").split(
                "\ndef shell_alias_no_env():",
                1,
            )[0],
            namespace,
        )
    finally:
        sys.path[:] = original_sys_path


def _v7_component_records(*, exclude: set[str] | None = None) -> list[dict]:
    excluded = set(exclude or set())
    return [
        {
            "component": component,
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }
        for component in monitor.V7_GOVERNANCE_COMPONENTS
        if component not in excluded
    ]


def test_rh26_heading_anomalies_allow_known_casual_empty_and_safe_carryover_state():
    probes = [
        {"id": "cancel_failed_video", "chars": 134, "headings": ["Current Foreground Task"]},
        {"id": "continue_current_task", "chars": 108, "headings": ["Current Foreground Task"]},
        {"id": "casual_memory_system_change", "chars": 0, "headings": []},
        {"id": "casual_memory_system_change", "chars": 1535, "headings": ["Recent Event Summaries"]},
        {
            "id": "diagnostic_current_architecture",
            "chars": 297,
            "headings": ["Diagnostic Grounding", "Current Memory-OS Runtime Facts"],
        },
        {
            "id": "candidate_vs_crystallized",
            "chars": 1306,
            "headings": ["Crystallized Review Candidates", "Crystallized Memory", "Indexed Recall"],
        },
        {
            "id": "candidate_vs_crystallized",
            "chars": 975,
            "headings": ["Crystallized Review Candidates", "Crystallized Memory"],
        },
        {
            "id": "active_comfyui_install",
            "chars": 2051,
            "headings": ["Current Foreground Task", "Crystallized Memory", "Indexed Recall", "Recent Event Summaries"],
        },
        {"id": "deferred_cancellation", "chars": 110, "headings": ["Current Foreground Task"]},
    ]

    assert find_rh26_heading_anomalies(probes) == []


def test_rh26_heading_anomalies_flag_background_context_on_cancel_and_casual():
    probes = [
        {
            "id": "cancel_failed_video",
            "chars": 800,
            "headings": ["Current Foreground Task", "Working Memory"],
        },
        {
            "id": "casual_memory_system_change",
            "chars": 1200,
            "headings": ["Current Foreground Task", "Indexed Recall"],
        },
    ]

    anomalies = find_rh26_heading_anomalies(probes)

    # cancel_failed_video: only extra unexpected "Working Memory" → warning
    assert {
        "id": "cancel_failed_video",
        "severity": "warning",
        "code": "rh26_extra_unexpected_heading",
        "expected": ["Current Foreground Task"],
        "actual": ["Current Foreground Task", "Working Memory"],
        "extra": ["Working Memory"],
    } in anomalies
    # casual_memory_system_change: forbidden headings → still fail
    assert {
        "id": "casual_memory_system_change",
        "severity": "fail",
        "code": "casual_context_forbidden_heading",
        "expected": [],
        "actual": ["Current Foreground Task", "Indexed Recall"],
    } in anomalies


def test_rh26_heading_anomalies_warn_on_unclassified_casual_context():
    probes = [
        {
            "id": "casual_memory_system_change",
            "chars": 900,
            "headings": ["Working Memory"],
        }
    ]

    anomalies = find_rh26_heading_anomalies(probes)

    assert anomalies == [
        {
            "id": "casual_memory_system_change",
            "severity": "warning",
            "code": "casual_context_needs_review",
            "expected": [],
            "actual": ["Working Memory"],
        }
    ]


def test_rh26_extra_only_unexpected_heading_warns():
    """Extra heading not in ALLOWED_RH26_EXTRA_HEADINGS → warning, not fail."""
    probes = [
        {
            "id": "cancel_failed_video",
            "chars": 500,
            "headings": ["Current Foreground Task", "New Unknown Section"],
        },
    ]
    anomalies = find_rh26_heading_anomalies(probes)
    assert len(anomalies) == 1
    assert anomalies[0]["severity"] == "warning"
    assert anomalies[0]["code"] == "rh26_extra_unexpected_heading"
    assert anomalies[0]["extra"] == ["New Unknown Section"]


def test_rh26_missing_expected_heading_fails():
    """Missing a required expected heading → still hard fail."""
    probes = [
        {
            "id": "diagnostic_current_architecture",
            "chars": 200,
            # Missing "Diagnostic Grounding" — required heading
            "headings": ["Current Memory-OS Runtime Facts"],
        },
    ]
    anomalies = find_rh26_heading_anomalies(probes)
    assert len(anomalies) == 1
    assert anomalies[0]["severity"] == "fail"
    assert anomalies[0]["code"] == "rh26_missing_expected_heading"
    assert anomalies[0]["missing"] == ["Diagnostic Grounding"]


def test_rh26_casual_forbidden_heading_still_fails():
    """casual_memory_system_change with a forbidden heading → still fail (unchanged)."""
    probes = [
        {
            "id": "casual_memory_system_change",
            "chars": 900,
            "headings": ["Current Foreground Task"],
        },
    ]
    anomalies = find_rh26_heading_anomalies(probes)
    assert len(anomalies) == 1
    assert anomalies[0]["severity"] == "fail"
    assert anomalies[0]["code"] == "casual_context_forbidden_heading"


def test_rh26_extra_allowed_heading_no_anomaly():
    """Extra heading listed in ALLOWED_RH26_EXTRA_HEADINGS → no anomaly."""
    probes = [
        {
            "id": "candidate_vs_crystallized",
            "chars": 1200,
            # "Indexed Recall" is in ALLOWED_RH26_EXTRA_HEADINGS for this prompt
            "headings": ["Crystallized Review Candidates", "Crystallized Memory", "Indexed Recall"],
        },
    ]
    anomalies = find_rh26_heading_anomalies(probes)
    assert anomalies == []


def test_rh26_degradation_suffix_stripped_before_matching():
    """Heading with degradation suffix matches contract heading without suffix.

    e.g. "Crystallized Memory (deterministic floor recall)" ≈ "Crystallized Memory"
    — the suffix is runtime metadata, not part of the heading contract.
    """
    probes = [
        {
            "id": "candidate_vs_crystallized",
            "chars": 2000,
            "headings": [
                "Crystallized Review Candidates",
                "Crystallized Memory (deterministic floor recall)",
            ],
        },
    ]
    anomalies = find_rh26_heading_anomalies(probes)
    # Both contract headings matched after suffix stripping → no anomaly
    assert anomalies == []


def test_rh26_degradation_suffix_does_not_mask_real_missing():
    """Suffix stripping must not paper over a genuinely missing heading."""
    probes = [
        {
            "id": "candidate_vs_crystallized",
            "chars": 500,
            # Only the degraded heading — "Crystallized Review Candidates" genuinely absent
            "headings": ["Crystallized Memory (deterministic floor recall)"],
        },
    ]
    anomalies = find_rh26_heading_anomalies(probes)
    assert len(anomalies) == 1
    assert anomalies[0]["severity"] == "fail"
    assert anomalies[0]["code"] == "rh26_missing_expected_heading"
    # "Crystallized Memory" matched via suffix strip, only "Crystallized Review Candidates" missing
    assert anomalies[0]["missing"] == ["Crystallized Review Candidates"]


def test_rh26_probe_failure_is_explicit_fail_not_silent_pass():
    """rh26_probe() reports a subprocess failure as a single-element list
    ([{"_error": ..., "_code": ...}]), not a bare dict. classify_snapshot
    must surface that as an explicit FAIL rather than silently finding zero
    anomalies (find_rh26_heading_anomalies skips any entry with no matching
    EXPECTED_RH26_HEADINGS id) and reporting nothing wrong at all."""
    snapshot = {"rh26_apply_probe": [{"_error": "boom", "_code": 124}]}

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "rh26_probe_unavailable" for item in classification["fail"])
    assert classification["status"] == "FAIL"


def test_rh26_probe_non_list_value_does_not_crash_classify_snapshot():
    """Defense at the classify_snapshot boundary: even if rh26_apply_probe
    were ever a bare dict again (the old, pre-fix rh26_probe() error shape),
    classify_snapshot must not crash iterating it as a list."""
    snapshot = {"rh26_apply_probe": {"_error": "boom", "_code": 124}}

    classification = classify_snapshot(snapshot)

    assert classification["status"] in {"PASS", "WARN", "FAIL"}


def test_low_clue_ingress_matrix_probe_failure_is_explicit_fail_not_silent_pass():
    """Same failure class as rh26: low_clue_ingress_matrix() wraps a
    subprocess failure in a single-element list. Each ingress item is
    already isinstance-guarded (non-dict entries are skipped), which used to
    let a probe failure degrade to zero findings — silently. It must now
    surface an explicit FAIL."""
    snapshot = {"low_clue_ingress_matrix": [{"_error": "boom", "_code": 124}]}

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "low_clue_ingress_matrix_unavailable" for item in classification["fail"])
    assert classification["status"] == "FAIL"


def test_low_clue_ingress_matrix_non_list_value_does_not_crash_classify_snapshot():
    snapshot = {"low_clue_ingress_matrix": {"_error": "boom", "_code": 124}}

    classification = classify_snapshot(snapshot)

    assert classification["status"] in {"PASS", "WARN", "FAIL"}


def test_compute_deltas_tracks_count_growth_and_audit_ratios():
    current = {
        "memory_status": {
            "counts": {
                "audit_entries": 110,
                "events": 12,
                "working_items": 7,
                "crystallized_candidates": 7,
                "crystallized_records": 0,
            }
        },
        "audit_actions": {
            "action_counts": {
                "runtime_heartbeat": 20,
                "write_working_document": 12,
                "append_event": 4,
            }
        },
    }
    previous = {
        "memory_status": {
            "counts": {
                "audit_entries": 100,
                "events": 10,
                "working_items": 5,
                "crystallized_candidates": 5,
                "crystallized_records": 0,
            }
        },
        "audit_actions": {
            "action_counts": {
                "runtime_heartbeat": 10,
                "write_working_document": 7,
                "append_event": 2,
            }
        },
    }

    deltas = compute_deltas(current, previous)

    assert deltas["counts_delta"] == {
        "audit_entries": 10,
        "events": 2,
        "working_items": 2,
        "crystallized_candidates": 2,
        "crystallized_records": 0,
    }
    assert deltas["audit_entries_per_new_event"] == 5.0
    assert deltas["audit_action_delta"] == {
        "append_event": 2,
        "runtime_heartbeat": 10,
        "write_working_document": 5,
    }


def test_compute_deltas_tracks_hook_marker_and_session_activity_growth():
    current = {
        "memory_status": {"counts": {"audit_entries": 10, "events": 5}},
        "hook_markers": {"started": 3, "reset": 2, "finalized": 1, "total": 6},
        "session_activity": {"total_session_events": 5},
    }
    previous = {
        "memory_status": {"counts": {"audit_entries": 8, "events": 3}},
        "hook_markers": {"started": 3, "reset": 2, "finalized": 1, "total": 6},
        "session_activity": {"total_session_events": 3},
    }

    deltas = compute_deltas(current, previous)

    assert deltas["hook_marker_delta"] == {"started": 0, "reset": 0, "finalized": 0, "total": 0}
    assert deltas["session_activity_delta"] == {"total_session_events": 2}


def test_compute_deltas_backfills_hook_marker_total_when_previous_snapshot_lacks_total():
    current = {
        "memory_status": {"counts": {"audit_entries": 10, "events": 5}},
        "hook_markers": {"started": 20, "reset": 19, "finalized": 22, "total": 61},
    }
    previous = {
        "memory_status": {"counts": {"audit_entries": 8, "events": 3}},
        "hook_markers": {"started": 17, "reset": 15, "finalized": 17},
    }

    deltas = compute_deltas(current, previous)

    assert deltas["hook_marker_delta"] == {"started": 3, "reset": 4, "finalized": 5, "total": 12}


def test_compute_deltas_does_not_backfill_action_delta_from_legacy_snapshot():
    current = {
        "memory_status": {"counts": {"audit_entries": 110, "events": 12}},
        "audit_actions": {"action_counts": {"runtime_heartbeat": 20}},
    }
    previous = {"memory_status": {"counts": {"audit_entries": 100, "events": 10}}}

    deltas = compute_deltas(current, previous)

    assert deltas["counts_delta"]["audit_entries"] == 10
    assert deltas["audit_action_delta"] == {}


def test_classify_snapshot_warns_on_expected_observation_items_without_fail():
    snapshot = {
        "gateway": {"ActiveState": "active"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "heartbeat_listed": True,
        "cognitive_loop_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "cognitive_loop_listed": True,
        "cognitive_loop": _healthy_cognitive_loop(),
        "cognitive_loop_step_evidence": _healthy_cognitive_loop_step_evidence(),
        "memory_status": {
            "counts": {"crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": [("hindsight_adapter_disabled", "warning")]},
        "status_tool_contract": {"status": "ok", "findings": []},
        "shell_alias_no_env": {
            "status_ok": True,
            "doctor_ok": True,
            "memory_sources_ok": True,
            "metadata_retention_ok": True,
            "low_clue_recall_ok": True,
            "modules_ok": True,
            "eval_ok": True,
            "review_ok": True,
            "review_aging_ok": True,
            "host_probe_ok": True,
            "signal_sources_ok": True,
            "memory_projection_ok": True,
            "left_brain_ok": True,
        },
        "host_capability_probe": _healthy_host_capability_probe(),
        "signal_source_requirements": _healthy_signal_source_requirements(),
        "memory_projection": _healthy_memory_projection(),
        "memory_projection_retention": _healthy_memory_projection_retention(),
        "left_brain_advisor": _healthy_left_brain_advisor(),
        "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        "rh26_apply_probe": [{"id": "casual_memory_system_change", "chars": 0, "headings": []}],
        "deep_reflection": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
            "rolling_injection_source_classes": {
                "selected_by_source_class": {"working": 14},
                "window_report_count": 7,
            },
        },
        "compaction": {"recent_count": 2, "focus_none_count": 2},
        "low_clue_recall": {
            "schema_version": "memory-os.low_clue_recall.v0",
            "decision": "ask_choice",
            "candidate_count": 2,
            "llm_judge": {"status": "disabled", "mode": "none"},
        },
        "low_clue_ingress_matrix": [
            {
                "id": "deictic_yesterday",
                "route": "ambiguous_recall",
                "headings": ["Recall Clarification Guard"],
                "expected_route": "ambiguous_recall",
                "expected_heading": "Recall Clarification Guard",
                "guard_contract_ok": True,
            }
        ],
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert not classification["fail"]
    assert any(item["code"] == "rh26_casual_empty_precision_preserving" for item in classification["pass"])
    assert not any(item["code"] == "rh26_casual_empty" for item in classification["warn"])
    assert any(item["code"] == "deep_reflection_source_skew" for item in classification["warn"])
    assert any(item["code"] == "compression_focus_none" for item in classification["warn"])
    assert any(item["code"] == "shell_alias_no_env_ok" for item in classification["pass"])


def test_classify_snapshot_tracks_left_brain_signal_weaving_online_and_boundaries():
    snapshot = _healthy_snapshot()

    classification = classify_snapshot(snapshot)
    pass_codes = {item["code"] for item in classification["pass"]}

    assert "host_capability_probe_ok" in pass_codes
    assert "structural_write_gate_available" in pass_codes
    assert "signal_source_requirements_ok" in pass_codes
    assert "memory_projection_online" in pass_codes
    assert "memory_projection_registered_source_coverage_ok" in pass_codes
    assert "memory_projection_55c_payload_field_coverage_ok" in pass_codes
    assert "memory_projection_55d_payload_field_coverage_ok" in pass_codes
    assert "memory_projection_55e_payload_field_coverage_ok" in pass_codes
    assert "memory_projection_55f_payload_field_coverage_ok" in pass_codes
    assert "memory_projection_retention_compaction_visible" in pass_codes
    assert "left_brain_advisor_report_only_online" in pass_codes

    snapshot["signal_source_requirements"]["required_missing_count"] = 1
    snapshot["signal_source_requirements"]["sources"] = [
        {"source_key": "execution_gate_envelopes", "required_missing": True}
    ]
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "signal_source_required_missing" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["memory_projection"]["raw_body_included"] = True
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_raw_body_included" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["memory_projection"]["source_scope_missing_count"] = 1
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_source_scope_missing" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["memory_projection"]["duplicate_source_hash_count"] = 1
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_duplicate_records" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["memory_projection"]["registered_source_missing_count"] = 1
    snapshot["memory_projection"]["registered_source_missing_keys"] = ["runtime_logs"]
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_registered_source_missing" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["memory_projection"]["source_payload_fields"]["runtime_logs"] = ["status"]
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_55c_payload_field_coverage_missing" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["memory_projection"]["source_payload_fields"]["owner_review_pressure"] = ["status"]
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_55d_payload_field_coverage_missing" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["memory_projection"]["source_payload_fields"]["skills_inventory"] = ["status"]
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_55e_payload_field_coverage_missing" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["memory_projection"]["source_payload_fields"]["host_capability_contract"] = ["status"]
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_55f_payload_field_coverage_missing" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["memory_projection_retention"]["latest_boundary_true_archived_count"] = 1
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_retention_archived_safety_evidence" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["left_brain_advisor"]["boundary_true_count"] = 1
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "left_brain_advisor_boundary_true" for item in classification["fail"])


def test_classify_snapshot_fails_when_host_capability_contract_is_incomplete():
    snapshot = _healthy_snapshot()
    snapshot["host_capability_probe"]["capabilities"]["cron"] = {"status": "available"}

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "host_capability_probe_contract_incomplete" for item in classification["fail"])


def test_classify_snapshot_fails_when_host_capability_probe_is_still_core_owned():
    snapshot = _healthy_snapshot()
    snapshot["host_capability_probe"].pop("host_observation_owner")

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "host_capability_probe_not_host_owned" for item in classification["fail"])


def test_classify_snapshot_fails_when_structural_write_gate_is_not_available():
    snapshot = _healthy_snapshot()
    snapshot["host_capability_probe"]["capabilities"]["structural_write_gate"]["status"] = "migration_needed"

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "structural_write_gate_not_available" for item in classification["fail"])


def test_classify_snapshot_fails_when_left_brain_advisor_live_report_lacks_structural_write_gate():
    snapshot = _healthy_snapshot()
    snapshot["left_brain_advisor"]["latest_live_closure_eligible"] = True
    snapshot["left_brain_advisor"]["latest_structural_write_governance_present"] = False

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "left_brain_advisor_structural_write_gate_missing" for item in classification["fail"])


def test_classify_snapshot_fails_when_projection_artifact_is_stale_after_deploy():
    snapshot = _healthy_snapshot()
    snapshot["host_capability_probe"]["deployment_runtime_manifest"]["deployed_at"] = "2026-06-03T01:00:00Z"
    snapshot["memory_projection"]["latest_created_at"] = "2026-06-03T00:59:00Z"

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_projection_stale_after_deploy" for item in classification["fail"])


def test_classify_snapshot_clean_host_warns_on_missing_left_brain_signal_sources():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["signal_source_requirements"]["required_missing_count"] = 1
    snapshot["signal_source_requirements"]["sources"] = [
        {"source_key": "execution_gate_envelopes", "required_missing": True}
    ]

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "signal_source_required_missing" for item in classification["warn"])
    assert not any(item["code"] == "signal_source_required_missing" for item in classification["fail"])


def test_classify_snapshot_tracks_rh31_eval_safety_and_status():
    snapshot = _healthy_snapshot()
    snapshot["rh31_eval"] = {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "warning",
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "adapter_count": 6,
        "failure_count": 2,
        "measurement_signal_count": 2,
        "live_guard_candidate_count": 0,
        "failure_class_distribution": {"fts_miss": 1, "lexical_miss": 1},
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "rh31_eval_safety_ok" for item in classification["pass"])
    assert any(item["code"] == "rh31_eval_measurement_signals" for item in classification["warn"])
    assert not any(item["code"] == "rh31_eval_has_failures" for item in classification["warn"])

    snapshot["rh31_eval"]["forbidden_field_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "rh31_eval_forbidden_fields" for item in classification["fail"])


def test_classify_snapshot_accepts_optional_hindsight_off():
    snapshot = _healthy_snapshot()
    snapshot["hindsight_substrate"] = {
        "schema_version": "memory-os.hindsight_substrate_status.v0",
        "enabled": False,
        "status": "optional_not_configured",
    }

    classification = classify_snapshot(snapshot)

    assert {"code": "hindsight_optional_off_ok"} in classification["pass"]
    assert not [item for item in classification["fail"] if item["code"].startswith("hindsight")]


def test_classify_snapshot_accepts_nested_memory_status_hindsight_configured():
    snapshot = _healthy_snapshot()
    snapshot["memory_status"]["hindsight_substrate"] = {
        "schema_version": "memory-os.hindsight_substrate_status.v0",
        "enabled": True,
        "status": "configured",
        "recall_mode": "shadow",
        "substrate_monitor": {
            "raw_retained_count": 0,
            "no_raw_retained": True,
            "projection_stale_count": 0,
            "external_authoritative_count": 0,
            "reflect_off_hot_path": True,
            "recall_llm_triggered": False,
        },
    }

    classification = classify_snapshot(snapshot)

    assert {"code": "hindsight_configured_ok"} in classification["pass"]
    assert not [item for item in classification["fail"] if item["code"].startswith("hindsight")]


def test_classify_snapshot_fails_on_hindsight_raw_retain_projection_or_authority():
    snapshot = _healthy_snapshot()
    snapshot["hindsight_substrate"] = {
        "schema_version": "memory-os.hindsight_substrate_status.v0",
        "enabled": True,
        "status": "configured",
        "recall_mode": "shadow",
        "substrate_monitor": {
            "raw_retained_count": 1,
            "no_raw_retained": False,
            "projection_stale_count": 1,
            "local_first_authority_preserved": False,
            "external_authoritative_count": 1,
        },
    }

    classification = classify_snapshot(snapshot)
    fail_codes = {item["code"] for item in classification["fail"]}

    assert "hindsight_raw_retain_detected" in fail_codes
    assert "hindsight_projection_stale" in fail_codes
    assert "hindsight_overrode_local_authority" in fail_codes


def test_v7_governance_summary_defaults_to_missing_shadow_components():
    snapshot = _healthy_snapshot()

    summary = summarize_v7_governance(snapshot)

    assert summary["schema_version"] == "memory-os.v7_governance_summary.v0"
    assert summary["component_count"] == 18
    assert summary["shadow_live_component_count"] == 0
    assert summary["acting_component_count"] == 0
    assert summary["live_guard_registered_count"] == 0
    assert summary["memory_sources_feedback_volume_ready"] is False
    assert summary["component_status"]["promotion_matrix"] == "missing"
    assert summary["component_status"]["live_guard_registry"] == "missing"
    assert summary["confidence_router_status"] == "missing"
    assert summary["simulation_coverage_status"] == "missing"
    assert summary["confabulation_detection_status"] == "missing"
    assert summary["crystallized_revalidator_status"] == "missing"
    assert summary["cross_check_anchoring_status"] == "missing"
    assert summary["component_status"]["symbolic_offloader"] == "missing"
    assert summary["component_status"]["judge_calibration"] == "missing"
    assert summary["component_status"]["candidate_review"] == "missing"
    assert summary["component_status"]["shadow_recall"] == "missing"
    assert summary["component_status"]["provisional"] == "missing"
    assert summary["component_status"]["cascade_routing_policy"] == "missing"
    assert summary["component_status"]["migration_controller"] == "missing"
    assert summary["component_status"]["abstraction_distillation"] == "missing"


def test_v7_governance_summary_reports_required_and_optional_component_policy():
    snapshot = _healthy_snapshot()

    summary = summarize_v7_governance(snapshot)

    assert summary["required_component_count"] == 17
    assert summary["present_required_component_count"] == 0
    assert "confidence_router" in summary["missing_required_components"]
    assert "symbolic_offloader" not in summary["missing_required_components"]
    assert summary["optional_components"]["symbolic_offloader"]["status"] == "missing"
    assert summary["optional_components"]["symbolic_offloader"]["intentionally_absent"] is True
    assert summary["optional_components"]["symbolic_offloader"]["absence_reason"] == "optional_audit_level_default_disabled"
    assert summary["profile_expected_component_policy"] == "production"


def test_classify_snapshot_fails_live_profile_when_required_v7_component_missing():
    snapshot = _healthy_snapshot()
    snapshot["v7_governance"] = {"components": _v7_component_records(exclude={"confidence_router"})}

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "v7_required_components_missing" and item["components"] == ["confidence_router"]
        for item in classification["fail"]
    )


def test_classify_snapshot_warns_clean_host_when_optional_v7_component_is_absent_with_reason():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["v7_governance"] = {"components": _v7_component_records(exclude={"symbolic_offloader"})}

    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "v7_required_components_missing" for item in classification["fail"])
    assert any(
        item["code"] == "clean_host_v7_optional_component_intentionally_absent"
        and item["component"] == "symbolic_offloader"
        and item["reason"] == "optional_audit_level_default_disabled"
        for item in classification["warn"]
    )


def test_clean_host_warn_classification_table_covers_current_warn_codes():
    expected_codes = {
        "left_brain_pipeline_check_warn",
        "left_brain_proposal_agenda_trace_missing",
        "grounded_expression_alternate_left_map_substrate_pending",
        "module_cadence_split_pending",
        "right_brain_review_speak_preview_missing",
        "index_not_healthy",
        "doctor_warning_finding",
        "context_router_not_apply",
        "memory_sources_feedback_volume_missing",
        "v7_memory_sources_feedback_volume_pending",
        "session_mirror_pending_source_gap",
        "owner_review_proposal_auto_route_boundary_requires_owner",
        "owner_review_approved_proposals_pending_followup",
        "memory_projection_freshness_missing",
        "memory_projection_stale_after_deploy",
        "memory_projection_retention_compaction_missing",
        "monitor_error_observability_suppressed_errors",
    }

    assert expected_codes <= set(monitor.CLEAN_HOST_WARN_CLASSIFICATIONS)


def test_clean_host_warns_include_classification_records():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["context_router"] = {"enabled": False, "mode": "off", "apply_routes": []}

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "context_router_not_apply" for item in classification["warn"])
    assert any(
        item["code"] == "context_router_not_apply"
        and item["classification"] == "expected_clean_host"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["clean_host_warn_classification"]
    )


def test_clean_host_warns_classify_session_mirror_pending_source_gap():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "dry_run_status": "ok",
        "dry_run_written_event_ids_count": 0,
        "pending_session_count": 2,
        "pending_only_group_count": 2,
        "correlation_status": "ok",
    }

    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "clean_host_warn_unclassified" for item in classification["fail"])
    assert any(item["code"] == "session_mirror_pending_source_gap" for item in classification["warn"])
    assert any(
        item["code"] == "session_mirror_pending_source_gap"
        and item["classification"] == "next_lane"
        and item["production_behavior"] == "warn_if_production"
        for item in classification["clean_host_warn_classification"]
    )


def test_clean_host_warns_classify_post_deploy_projection_staleness():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["host_capability_probe"]["deployment_runtime_manifest"]["deployed_at"] = "2026-06-03T01:00:00Z"
    snapshot["memory_projection"]["latest_created_at"] = "2026-06-03T00:59:00Z"

    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "clean_host_warn_unclassified" for item in classification["fail"])
    assert any(item["code"] == "memory_projection_stale_after_deploy" for item in classification["warn"])
    assert any(
        item["code"] == "memory_projection_stale_after_deploy"
        and item["classification"] == "expected_clean_host"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["clean_host_warn_classification"]
    )


def test_clean_host_warns_classify_approved_proposals_pending_followup():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["owner_review_proposal_followups"]["pending_followup_count"] = 1
    snapshot["owner_review_proposal_followups"]["awaiting_ops_gate_count"] = 1

    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "clean_host_warn_unclassified" for item in classification["fail"])
    assert any(item["code"] == "owner_review_approved_proposals_pending_followup" for item in classification["warn"])
    assert any(
        item["code"] == "owner_review_approved_proposals_pending_followup"
        and item["classification"] == "next_lane"
        and item["production_behavior"] == "warn_if_production"
        for item in classification["clean_host_warn_classification"]
    )


def test_clean_host_classifies_monitor_error_observability_suppressed_errors():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["memory_projection"].update(
        {
            "suppressed_error_count": 1,
            "recent_error_codes": ["jsonl_malformed_line"],
        }
    )

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert not any(item["code"] == "clean_host_warn_unclassified" for item in classification["fail"])
    assert any(item["code"] == "monitor_error_observability_suppressed_errors" for item in classification["warn"])
    assert any(
        item["code"] == "monitor_error_observability_suppressed_errors"
        and item["classification"] == "expected_clean_host"
        and item["production_behavior"] == "warn_if_production"
        for item in classification["clean_host_warn_classification"]
    )


def test_clean_host_warns_classify_index_and_doctor_bootstrap_warnings():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["memory_status"]["index_health"] = {"state": "missing"}
    snapshot["doctor"] = {"status": "ok", "findings": [("bootstrap_warning", "warning")]}

    classification = classify_snapshot(snapshot)

    assert not classification["fail"]
    assert any(
        item["code"] == "index_not_healthy"
        and item["classification"] == "expected_clean_host"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["clean_host_warn_classification"]
    )
    assert any(
        item["code"] == "doctor_warning_finding"
        and item["classification"] == "expected_clean_host"
        and item["production_behavior"] == "warn_if_production"
        for item in classification["clean_host_warn_classification"]
    )


def test_production_index_not_healthy_still_fails():
    snapshot = _healthy_snapshot()
    snapshot["memory_status"]["index_health"] = {"state": "missing"}

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "index_not_healthy_in_production"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["fail"]
    )


def test_production_index_stale_within_catchup_window_warns_with_contract():
    snapshot = _healthy_snapshot()
    snapshot["heartbeat_state"] = {"fresh": True, "age_seconds": 30, "max_age_seconds": 900}
    snapshot["memory_status"].update(
        {
            "counts": {"events": 11, "working_items": 7, "crystallized_records": 0},
            "index_counts": {"events": 10, "working_items": 7, "crystallized_records": 0},
            "index_health": {"state": "stale"},
            "last_write_age_seconds": 45,
        }
    )

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert not any(item["code"] == "index_not_healthy_in_production" for item in classification["fail"])
    catchup = next(item for item in classification["warn"] if item["code"] == "index_catchup_pending")
    assert catchup["value"]["within_catchup_window"] is True
    assert catchup["value"]["event_backlog"] == 1
    assert catchup["value"]["max_event_backlog"] == 1
    assert catchup["value"]["max_catchup_age_seconds"] == 900


def test_production_index_stale_large_backlog_fails_even_inside_catchup_age_window():
    snapshot = _healthy_snapshot()
    snapshot["heartbeat_state"] = {"fresh": True, "age_seconds": 30, "max_age_seconds": 900}
    snapshot["memory_status"].update(
        {
            "counts": {"events": 10010, "working_items": 7, "crystallized_records": 0},
            "index_counts": {"events": 10, "working_items": 7, "crystallized_records": 0},
            "index_health": {"state": "stale"},
            "last_write_age_seconds": 45,
        }
    )

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert not any(item["code"] == "index_catchup_pending" for item in classification["warn"])
    failure = next(item for item in classification["fail"] if item["code"] == "index_not_healthy_in_production")
    assert failure["value"]["within_catchup_window"] is False
    assert failure["value"]["event_backlog"] == 10000
    assert failure["value"]["max_event_backlog"] == 1


def test_production_index_stale_remote_max_age_cannot_widen_catchup_window():
    snapshot = _healthy_snapshot()
    snapshot["heartbeat_state"] = {"fresh": True, "age_seconds": 30, "max_age_seconds": 999999}
    snapshot["memory_status"].update(
        {
            "counts": {"events": 11, "working_items": 7, "crystallized_records": 0},
            "index_counts": {"events": 10, "working_items": 7, "crystallized_records": 0},
            "index_health": {"state": "stale"},
            "last_write_age_seconds": 3600,
        }
    )

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert not any(item["code"] == "index_catchup_pending" for item in classification["warn"])
    failure = next(item for item in classification["fail"] if item["code"] == "index_not_healthy_in_production")
    assert failure["value"]["within_catchup_window"] is False
    assert failure["value"]["event_backlog"] == 1
    assert failure["value"]["max_event_backlog"] == 1
    assert failure["value"]["max_catchup_age_seconds"] == 900


def test_production_index_stale_outside_catchup_window_still_fails_with_contract():
    snapshot = _healthy_snapshot()
    snapshot["heartbeat_state"] = {"fresh": False, "age_seconds": 1200, "max_age_seconds": 900}
    snapshot["memory_status"].update(
        {
            "counts": {"events": 12, "working_items": 7, "crystallized_records": 0},
            "index_counts": {"events": 10, "working_items": 7, "crystallized_records": 0},
            "index_health": {"state": "stale"},
            "last_write_age_seconds": 1200,
        }
    )

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    failure = next(item for item in classification["fail"] if item["code"] == "index_not_healthy_in_production")
    assert failure["value"]["within_catchup_window"] is False
    assert failure["value"]["event_backlog"] == 2


def test_production_clean_host_only_warn_escalates_by_policy():
    snapshot = _healthy_snapshot()
    snapshot["context_router"] = {"enabled": False, "mode": "off", "apply_routes": []}

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "context_router_not_apply" for item in classification["warn"])
    assert any(
        item["code"] == "context_router_not_apply_in_production"
        and item["production_behavior"] == "fail_if_production"
        for item in classification["fail"]
    )


def test_v7_governance_summary_uses_total_memory_sources_feedback_when_window_empty():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 0,
        "feedback_count": 0,
        "total_feedback_count": 2,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }

    summary = summarize_v7_governance(snapshot)

    assert summary["memory_sources_feedback_volume_ready"] is True
    assert summary["memory_sources_feedback_count"] == 2
    assert summary["memory_sources_feedback_canary_target"] == 20
    assert summary["memory_sources_feedback_canary_remaining"] == 18
    assert summary["memory_sources_feedback_canary_complete"] is False


def test_classify_snapshot_tracks_memory_sources_feedback_canary_without_blocking_shadow_live():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 0,
        "feedback_count": 1,
        "total_feedback_count": 4,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["module_artifacts"]["v7_meta"] = {
        "promotion_matrix_component": {
            "component": "promotion_matrix",
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "none",
            "task_installed": True,
        }
    }

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "v7_memory_sources_feedback_canary_running"
        and item["feedback_count"] == 4
        and item["target"] == 20
        and item["remaining"] == 16
        for item in classification["pass"]
    )
    assert not any(item["code"] == "v7_memory_sources_feedback_volume_pending" for item in classification["warn"])


def test_v7_owner_signal_lane_does_not_promote_until_canary_complete():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 0,
        "feedback_count": 1,
        "total_feedback_count": 5,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["module_artifacts"]["ground_truth_miner"] = {
        "status": "ok",
        "label_count": 0,
        "run_count": 1,
        "active_label_count": 0,
        "retracted_label_count": 0,
        "actual_execute": False,
        "score_live_applied": False,
        "route_live_applied": False,
    }

    summary = summarize_v7_governance(snapshot)
    classification = classify_snapshot(snapshot)
    label_miner = next(item for item in summary["components"] if item["component"] == "retractable_label_miner")
    other_acting = [
        item
        for item in summary["components"]
        if item["component"] != "retractable_label_miner"
        and item["autonomy_level"] in {"owner_approved_apply", "autonomous_acting"}
    ]

    assert summary["acting_component_count"] == 0
    assert summary["owner_signal_lane"] == "memory_sources_feedback"
    assert summary["owner_signal_owner_approved_apply_count"] == 5
    assert summary["owner_signal_owner_approved_apply_ready"] is False
    assert label_miner["autonomy_level"] == "shadow"
    assert label_miner["owner_signal_lane"] == "memory_sources_feedback"
    assert label_miner["owner_approved_apply_count"] == 5
    assert label_miner["owner_approved_apply_ready"] is False
    assert other_acting == []
    assert any(
        item["code"] == "v7_owner_signal_owner_approved_apply_visible"
        and item["feedback_count"] == 5
        and item["ready"] is False
        for item in classification["pass"]
    )
    assert not any(item["code"] == "v7_component_live_applied_without_acting_gate" for item in classification["fail"])


def test_v7_owner_signal_lane_promotes_only_retractable_label_miner_after_canary_complete():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 0,
        "feedback_count": 3,
        "total_feedback_count": 20,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["module_artifacts"]["ground_truth_miner"] = {
        "status": "ok",
        "label_count": 0,
        "run_count": 1,
        "active_label_count": 0,
        "retracted_label_count": 0,
        "actual_execute": False,
        "score_live_applied": False,
        "route_live_applied": False,
    }

    summary = summarize_v7_governance(snapshot)
    classification = classify_snapshot(snapshot)
    label_miner = next(item for item in summary["components"] if item["component"] == "retractable_label_miner")
    other_acting = [
        item
        for item in summary["components"]
        if item["component"] != "retractable_label_miner"
        and item["autonomy_level"] in {"owner_approved_apply", "autonomous_acting"}
    ]

    assert summary["acting_component_count"] == 1
    assert summary["owner_signal_owner_approved_apply_ready"] is True
    assert summary["owner_signal_selected_component"] == "retractable_label_miner"
    assert label_miner["autonomy_level"] == "owner_approved_apply"
    assert label_miner["owner_approved_apply_count"] == 20
    assert label_miner["owner_approved_apply_ready"] is True
    assert other_acting == []
    assert any(
        item["code"] == "v7_owner_signal_owner_approved_apply_visible"
        and item["feedback_count"] == 20
        and item["ready"] is True
        for item in classification["pass"]
    )


def test_v7_governance_summary_infers_wave1_live_shadow_from_module_artifacts():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "evidence_count": 4,
        "score_count": 4,
        "derived_evidence_profile_count": 4,
        "feature_score_live_applied": False,
        "maturity_live_applied": False,
    }
    snapshot["module_artifacts"]["v7_meta"] = {
        "promotion_matrix_component": {
            "component": "promotion_matrix",
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": False,
            "actual_execute": False,
        },
        "live_guard_registry_present": True,
        "eval_adapter_registry_present": True,
        "eval_adapter_count": 14,
    }
    snapshot["module_artifacts"]["imagination_loop"] = {
        "status": "ok",
        "scenario_count": 5,
        "simulated_count": 5,
        "actual_execute": False,
        "live_behavior_changed": False,
    }
    snapshot["module_artifacts"]["confabulation_detector"] = {
        "status": "ok",
        "flag_count": 1,
        "actual_execute": False,
        "score_live_applied": False,
        "route_live_applied": False,
    }
    snapshot["module_artifacts"]["ground_truth_miner"] = {
        "status": "ok",
        "label_count": 0,
        "run_count": 1,
        "active_label_count": 0,
        "retracted_label_count": 0,
        "actual_execute": False,
        "score_live_applied": False,
        "route_live_applied": False,
    }
    snapshot["module_artifacts"]["confidence_router"] = {
        "status": "ok",
        "route_count": 0,
        "run_count": 1,
        "band_distribution": {},
        "actual_execute": False,
        "score_live_applied": False,
        "route_live_applied": False,
    }
    snapshot["module_artifacts"]["judge_calibration"] = {
        "status": "ok",
        "run_count": 1,
        "calibration_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["candidate_review"] = {
        "status": "ok",
        "decision_count": 3,
        "run_count": 1,
        "candidate_review_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["shadow_recall"] = {
        "status": "ok",
        "fingerprint_count": 1,
        "run_count": 1,
        "auto_discard_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["provisional"] = {
        "status": "ok",
        "record_count": 1,
        "run_count": 1,
        "auto_promote_live_applied": False,
        "actual_crystallized_approval": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["cascade_routing_policy"] = {
        "status": "ok",
        "proposal_count": 1,
        "route_strategy_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["migration_controller"] = {
        "status": "ok",
        "run_count": 1,
        "last_regime": "cold_start",
        "migration_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["symbolic_offloader"] = {
        "status": "ok",
        "report_count": 1,
        "ref_count": 1,
        "canonical_state_changed": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["abstraction_distillation"] = {
        "status": "ok",
        "item_count": 3,
        "distillation_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["crystallized_revalidator"] = {
        "status": "ok",
        "flag_count": 0,
        "run_count": 1,
        "would_demote_count": 0,
        "actual_execute": False,
        "actual_crystallized_approval": False,
        "demotion_live_applied": False,
    }
    snapshot["module_artifacts"]["grounded_expression_judge"] = {
        "status": "ok",
        "verdict_count": 4,
        "verdict_distribution": {
            "grounded": 1,
            "confabulation": 1,
            "blind_spot": 1,
            "unresolvable": 1,
        },
        "unresolvable_count": 1,
        "left_map_substrate_warning_count": 0,
        "left_map_coverage_floor_met_count": 2,
        "latest_left_map_snapshot_version": "leftmap_abc123",
        "verdict_distribution_degenerate": False,
        "substrate_unavailable_blocker_cleared": True,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "delivery_affected": False,
        "delivery_gated": False,
        "policy_live_applied": False,
    }

    summary = summarize_v7_governance(snapshot)
    classification = classify_snapshot(snapshot)

    assert summary["component_status"]["derived_evidence_profile"] == "live-shadow"
    assert summary["component_status"]["promotion_matrix"] == "live-shadow"
    assert summary["component_status"]["live_guard_registry"] == "live-shadow"
    assert summary["component_status"]["eval_adapter_registry"] == "live-shadow"
    assert summary["confidence_router_status"] == "live-shadow"
    assert summary["component_status"]["retractable_label_miner"] == "live-shadow"
    assert summary["component_status"]["judge_calibration"] == "live-shadow"
    assert summary["component_status"]["candidate_review"] == "live-shadow"
    assert summary["component_status"]["shadow_recall"] == "live-shadow"
    assert summary["component_status"]["provisional"] == "live-shadow"
    assert summary["component_status"]["cascade_routing_policy"] == "live-shadow"
    assert summary["component_status"]["migration_controller"] == "live-shadow"
    assert summary["component_status"]["symbolic_offloader"] == "live-shadow"
    assert summary["component_status"]["abstraction_distillation"] == "live-shadow"
    assert summary["simulation_coverage_status"] == "live-shadow"
    assert summary["confabulation_detection_status"] == "live-shadow"
    assert summary["crystallized_revalidator_status"] == "live-shadow"
    assert summary["cross_check_anchoring_status"] == "live-shadow"
    assert summary["shadow_live_component_count"] >= 18
    assert any(item["code"] == "v7_shadow_live_components_visible" for item in classification["pass"])
    assert any(item["code"] == "grounded_expression_verdict_distribution_visible" for item in classification["pass"])
    assert any(item["code"] == "grounded_expression_alternate_left_map_substrate_ready" for item in classification["pass"])


def test_classify_snapshot_fails_grounded_expression_if_delivery_affected():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["grounded_expression_judge"] = {
        "status": "ok",
        "verdict_count": 1,
        "verdict_distribution": {
            "grounded": 1,
            "confabulation": 0,
            "blind_spot": 0,
            "unresolvable": 0,
        },
        "left_map_coverage_floor_met_count": 1,
        "delivery_affected": True,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "policy_live_applied": False,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "grounded_expression_delivery_affected_true" for item in classification["fail"])


def test_v7_governance_summary_uses_code_promotion_matrix_not_docs():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["v7_meta"] = {
        "promotion_matrix_component": {
            "component": "promotion_matrix",
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": False,
            "actual_execute": False,
        },
        "promotion_matrix_present": False,
    }

    summary = summarize_v7_governance(snapshot)

    assert summary["component_status"]["promotion_matrix"] == "live-shadow"
    assert summary["shadow_live_component_count"] == 1
    assert summary["live_guard_registered_count"] == 1


def test_classify_snapshot_accepts_v7_live_shadow_without_acting():
    snapshot = _healthy_snapshot()
    snapshot["v7_governance"] = {
        "schema_version": "memory-os.v7_governance_summary.v0",
        "components": [
            {
                "component": "live_guard_registry",
                "task_installed": True,
                "pipeline_liveness": "live-shadow",
                "autonomy_level": "shadow",
                "live_guard_registered": True,
                "live_applied": False,
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_crystallized_approval": False,
            }
        ],
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "v7_shadow_live_components_visible" for item in classification["pass"])
    assert not any(item["code"] == "v7_component_live_applied_without_acting_gate" for item in classification["fail"])
    assert "V7Governance" in rendered
    assert "shadow_live_component_count" in rendered


def test_l4_guard_summary_tracks_kill_switch_and_live_apply_findings():
    snapshot = _healthy_snapshot()
    snapshot["memory_os_config"] = {"l4": {"kill_switch_enabled": True}}
    snapshot["module_artifacts"]["evidence"] = {
        "feature_score_live_applied": True,
        "maturity_live_applied": False,
    }

    summary = summarize_l4_guard(snapshot)

    assert summary == {
        "schema_version": "memory-os.l4_guard_summary.v0",
        "kill_switch_enabled": True,
        "registered_component_count": 1,
        "missing_registration_count": 0,
        "missing_registration_components": [],
        "live_applied_finding_count": 1,
    }


def test_classify_snapshot_fails_unregistered_v7_acting_component():
    snapshot = _healthy_snapshot()
    snapshot["v7_governance"] = {
        "schema_version": "memory-os.v7_governance_summary.v0",
        "components": [
            {
                "component": "confidence_router",
                "task_installed": True,
                "pipeline_liveness": "live-shadow",
                "autonomy_level": "owner_approved_apply",
                "live_guard_registered": False,
                "live_applied": False,
                "actual_send": False,
                "actual_execute": True,
                "actual_identity_write": False,
                "actual_crystallized_approval": False,
            }
        ],
    }

    summary = summarize_v7_governance(snapshot)
    classification = classify_snapshot(snapshot)

    assert summary["live_guard_missing_registration_count"] == 1
    assert summary["live_guard_missing_registration_components"][0]["component"] == "confidence_router"
    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "l4_guard_missing_registration"
        and item["components"][0]["component"] == "confidence_router"
        for item in classification["fail"]
    )


def test_classify_snapshot_fails_v7_live_apply_without_acting_gate():
    snapshot = _healthy_snapshot()
    snapshot["v7_governance"] = {
        "schema_version": "memory-os.v7_governance_summary.v0",
        "components": [
            {
                "component": "confidence_router",
                "task_installed": True,
                "pipeline_liveness": "live-shadow",
                "autonomy_level": "shadow",
                "live_guard_registered": True,
                "live_applied": True,
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_crystallized_approval": False,
            }
        ],
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "v7_component_live_applied_without_acting_gate"
        and item["component"] == "confidence_router"
        for item in classification["fail"]
    )


def test_classify_snapshot_tracks_owner_review_status_and_illegal_crystallized_writes():
    snapshot = _healthy_snapshot()
    snapshot["owner_review"] = {
        "schema_version": "memory-os.owner_review_status.v0",
        "review_queue": {"pending_count": 3, "action_required_count": 2, "stale_count": 0},
        "owner_action_count": 4,
        "action_type_counts": {"approve_candidate": 1, "reject_candidate": 1},
        "duplicate_ignored_count": 0,
        "error_count": 0,
        "owner_approved_crystallized_write_count": 1,
        "unapproved_crystallized_write_count": 0,
        "digest_burden": {"owner_active_period": True},
        "feedback_backflow": {"feedback_action_count": 1},
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "owner_review_status_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_owner_approved_crystallized_write" for item in classification["pass"])
    assert "OwnerReview" in rendered
    assert "'owner_approved_crystallized': 1" in rendered

    snapshot["owner_review"]["unapproved_crystallized_write_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_unapproved_crystallized_write" for item in classification["fail"])


def test_classify_snapshot_surfaces_owner_burden_budget_trend():
    snapshot = _healthy_snapshot()
    snapshot["owner_review"] = {
        "schema_version": "memory-os.owner_review_status.v0",
        "review_queue": {
            "pending_count": 42,
            "action_required_count": 2,
            "review_suggested_count": 25,
            "fyi_count": 15,
            "stale_count": 3,
        },
        "owner_action_count": 4,
        "action_type_counts": {},
        "duplicate_ignored_count": 0,
        "error_count": 0,
        "owner_approved_crystallized_write_count": 0,
        "unapproved_crystallized_write_count": 0,
        "digest_burden": {
            "schema_version": "memory-os.owner_burden_budget.v0",
            "budget_status": "watch",
            "pending_total": 42,
            "action_required_count": 2,
            "review_suggested_count": 25,
            "fyi_count": 15,
            "informational_count": 40,
            "stale_count": 3,
            "budget": {"action_required_cap": 5, "fyi_cap": 20, "review_suggested_cap": 20},
        },
        "feedback_backflow": {},
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "owner_review_burden_budget_visible" for item in classification["pass"])
    assert "burden_budget_status': 'watch'" in rendered
    assert "'informational': 40" in rendered


def test_classify_snapshot_allows_owner_approved_crystallized_records():
    snapshot = _healthy_snapshot()
    snapshot["memory_status"]["counts"]["crystallized_records"] = 1
    snapshot["owner_review"] = {
        "schema_version": "memory-os.owner_review_status.v0",
        "review_queue": {"pending_count": 0, "action_required_count": 0, "stale_count": 0},
        "owner_action_count": 1,
        "action_type_counts": {"approve_candidate": 1},
        "duplicate_ignored_count": 0,
        "error_count": 0,
        "owner_approved_crystallized_write_count": 1,
        "unapproved_crystallized_write_count": 0,
        "digest_burden": {"owner_active_period": True},
    }

    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "unexpected_crystallized_records" for item in classification["fail"])
    assert any(item["code"] == "crystallized_records_present" for item in classification["pass"])
    assert any(item["code"] == "owner_review_owner_approved_crystallized_write" for item in classification["pass"])


def test_classify_snapshot_tracks_owner_review_channel_and_digest_preview_boundaries():
    snapshot = _healthy_snapshot()

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "owner_review_aging_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_channel_resolver_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_delivery_status_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_delivery_gate_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_digest_preview_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_rendered_digest_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_rendered_digest_response_header_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_rendered_digest_overview_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_agenda_digest_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_reply_dry_run_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_surface_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_surface_expression_feedback_context_visible" for item in classification["pass"])
    assert any(
        item["code"] == "owner_review_surface_memory_sources_feedback_context_visible"
        for item in classification["pass"]
    )
    assert any(item["code"] == "owner_review_surface_agent_tool_contract_ok" for item in classification["pass"])
    assert "latest_memory_source_id" in rendered
    assert any(item["code"] == "owner_review_ingress_guard_token_only" for item in classification["pass"])
    assert any(item["code"] == "owner_review_proposal_followups_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_proposal_auto_route_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_cron_integration_status_ok" for item in classification["pass"])
    assert "OwnerReviewAging" in rendered
    assert "OwnerReviewChannel" in rendered
    assert "OwnerCronIntegration" in rendered
    assert "OwnerDeliveryGate" in rendered
    assert "OwnerDeliveryStatus" in rendered
    assert "OwnerDigestPreview" in rendered
    assert "OwnerAgendaDigest" in rendered
    assert "OwnerReviewSurface" in rendered
    assert any(item["code"] == "owner_review_proposal_auto_route_shadow_metrics_visible" for item in classification["pass"])
    assert any(item["code"] == "owner_review_proposal_auto_route_probation_guard_visible" for item in classification["pass"])

    snapshot["owner_review_digest_preview"]["will_send"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_digest_would_send_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_channel"]["raw_body_included"] = True
    snapshot["owner_review_digest_preview"]["raw_body_included"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_channel_raw_body_included" for item in classification["fail"])
    assert any(item["code"] == "owner_review_digest_raw_body_included" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["text_has_internal_schema"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_internal_schema_text" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["text_has_transcript_marker"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_transcript_marker" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["text_char_count"] = 2401
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_too_long" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["response_header_present"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_missing_response_header" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["overview_present"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_missing_overview" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["speak_item_count"] = 2
    snapshot["owner_review_rendered_digest"]["speak_expression_preview_count"] = 1
    snapshot["owner_review_rendered_digest"]["speak_expression_preview_missing_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "right_brain_review_speak_preview_missing" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_agenda_digest"]["review_suggested_suppressed"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_agenda_digest_review_suggested_not_suppressed" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_agenda_digest"]["backlog_totals_suppressed"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_agenda_digest_backlog_totals_visible" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_reply_dry_run"]["dry_run"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_reply_dry_run_mutated_state" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_reply_dry_run"]["status"] = "needs_clarification"
    snapshot["owner_review_reply_dry_run"]["owner_action_dry_run"] = None
    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "owner_review_reply_owner_action_not_dry_run" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_surface"]["raw_body_included_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_surface_raw_body_included" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_surface"]["boundary_true_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_surface_boundary_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_surface"]["forbidden_owner_command_field_count"] = 1
    snapshot["owner_review_surface"]["forbidden_owner_command_fields"] = ["operator_cli"]
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_surface_forbidden_command_fields" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["legacy_anchor_accepted"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_legacy_anchor_accepted" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["token_command_accepted"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_token_command_not_accepted" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["owner_command_event_count"] = 1
    snapshot["owner_review_ingress_guard"]["owner_command_working_count"] = 1
    snapshot["owner_review_ingress_guard"]["owner_command_candidate_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_command_captured_as_event" for item in classification["fail"])
    assert any(item["code"] == "owner_review_command_promoted_to_working" for item in classification["fail"])
    assert any(item["code"] == "owner_review_command_promoted_to_candidate" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["review_reply_tool_input_mode"] = "reply_fallback"
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_agent_tool_not_structured" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["reply_fallback_used_count"] = 1
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "owner_review_reply_fallback_used" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["owner_review_command_pollution_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_command_pollution_count_nonzero" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["boundary"]["actual_execute"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_proposal_followups_actual_execute_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["actual_execute"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_proposal_followups_actual_execute_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["items"] = [{"actual_execute": True}]
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_proposal_followups_item_actual_execute_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["items"] = [{"execution_ticket_created": True}]
    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "owner_review_proposal_followups_item_execution_ticket_created" for item in classification["fail"])
    assert any(item["code"] == "owner_review_proposal_followups_ok" for item in classification["pass"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["execution_ticket_count"] = 4
    snapshot["owner_review_proposal_followups"]["ticket_created_count"] = 4
    snapshot["owner_review_proposal_followups"]["awaiting_typed_execution_plan_count"] = 3
    snapshot["owner_review_proposal_followups"]["evidence_resolved_count"] = 1
    classification = classify_snapshot(snapshot)

    assert not classification["fail"]
    assert any(item["code"] == "owner_review_proposal_followups_execution_tickets_visible" for item in classification["pass"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["pending_followup_count"] = 1
    snapshot["owner_review_proposal_followups"]["awaiting_ops_gate_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "owner_review_approved_proposals_pending_followup" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["pending_followup_count"] = 0
    snapshot["owner_review_proposal_followups"]["open_followup_count"] = 2
    snapshot["owner_review_proposal_followups"]["awaiting_ops_gate_count"] = 0
    snapshot["owner_review_proposal_followups"]["ops_gate_reviewed_count"] = 2
    snapshot["owner_review_proposal_followups"]["awaiting_explicit_execution_count"] = 2
    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "owner_review_approved_proposals_pending_followup" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_auto_route"]["auto_followup_actual_execute_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "owner_review_proposal_auto_route_actual_execute_count_nonzero"
        for item in classification["fail"]
    )

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_auto_route"]["auto_followup_policy_write_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "owner_review_proposal_auto_route_policy_write_count_nonzero"
        for item in classification["fail"]
    )

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_auto_route"]["owner_action_required_boundary_count"] = 1
    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "owner_review_proposal_auto_route_boundary_guard_visible"
        for item in classification["pass"]
    )
    assert not any(
        item["code"] == "owner_review_proposal_auto_route_boundary_requires_owner"
        for item in classification["warn"]
    )

    snapshot = _healthy_snapshot()
    del snapshot["owner_review_proposal_auto_route"]["wilson_95_lower_bound"]
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "owner_review_proposal_auto_route_shadow_metrics_missing"
        for item in classification["fail"]
    )

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_auto_route"]["full_auto_eligible"] = True
    snapshot["owner_review_proposal_auto_route"]["eligible_sample_count"] = 20
    snapshot["owner_review_proposal_auto_route"]["shadow_decision_count"] = 3
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "owner_review_proposal_auto_route_full_auto_sample_floor_bypass"
        for item in classification["fail"]
    )

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_auto_route"]["auto_followup_actual_send_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "owner_review_proposal_auto_route_actual_send_count_nonzero"
        for item in classification["fail"]
    )

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["ops_gate"]["duplicate_proposal_followup_count"] = 1
    snapshot["module_artifacts"]["ops_gate"]["duplicate_proposal_followup_extra_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "ops_gate_duplicate_proposal_followup_report" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["proposal_queue"]["legacy_template_cleanup_apply_count"] = 1
    snapshot["module_artifacts"]["proposal_queue"]["legacy_template_cleanup_closed_count"] = 2
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "proposal_queue_legacy_template_cleanup_visible" for item in classification["pass"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["proposal_queue"]["legacy_template_cleanup_actual_execute_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "proposal_queue_legacy_template_cleanup_actual_execute_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["proposal_queue"]["legacy_template_cleanup_non_legacy_touched_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "proposal_queue_legacy_template_cleanup_non_legacy_touched" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_delivery_gate"]["boundary"]["actual_send"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_delivery_gate_actual_send_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_delivery_gate"]["status"] = "ready"
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "owner_review_delivery_gate_ready_for_review" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_delivery_status"]["unapproved_send_count"] = 1
    snapshot["owner_review_delivery_status"]["raw_body_included_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_unapproved_send" for item in classification["fail"])
    assert any(item["code"] == "owner_review_delivery_raw_body_included" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_cron_integration"]["enabled"] = True
    snapshot["owner_review_cron_integration"]["helper_script_present"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_cron_helper_missing" for item in classification["fail"])


def test_classify_snapshot_aggregates_error_observability_counters():
    snapshot = _healthy_snapshot()
    snapshot["heartbeat_state"] = {
        "exists": True,
        "fresh": True,
        "suppressed_error_count": 1,
        "recent_error_codes": ["runtime_heartbeat_error"],
        "last_error_record": {
            "schema_version": "memory-os.error_record.v0",
            "component": "runtime",
            "operation": "heartbeat",
            "error_code": "runtime_heartbeat_error",
            "severity": "error",
            "recoverable": True,
        },
    }
    snapshot["memory_projection"].update(
        {
            "suppressed_error_count": 2,
            "recent_error_codes": ["jsonl_malformed_line", "jsonl_non_object_line"],
        }
    )
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "suppressed_error_count": 3,
        "recent_error_codes": ["session_mirror_state_rebuilt"],
        "last_error_record": {
            "schema_version": "memory-os.error_record.v0",
            "component": "session_mirror",
            "operation": "load_state",
            "error_code": "session_mirror_state_rebuilt",
            "severity": "warning",
            "recoverable": True,
        },
    }
    snapshot["module_artifacts"]["prefetch_observability"] = {
        "schema_version": "memory-os.prefetch_observability.v0",
        "suppressed_error_count": 4,
        "recent_error_codes": ["prefetch_index_search_error"],
        "error_records": [
            {
                "schema_version": "memory-os.error_record.v0",
                "component": "prefetch",
                "operation": "index_search",
                "error_code": "prefetch_index_search_error",
                "severity": "warning",
                "recoverable": True,
            }
        ],
    }

    summary = monitor.monitor_error_observability(snapshot)
    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert summary["schema_version"] == "memory-os.monitor_error_observability.v0"
    assert summary["suppressed_error_count"] == 10
    assert summary["degraded_component_count"] == 4
    assert summary["live_write_error_count"] == 1
    assert summary["component_counts"] == {
        "memory_projection": 2,
        "prefetch": 4,
        "runtime": 1,
        "session_mirror": 3,
    }
    assert "runtime_heartbeat_error" in summary["recent_error_codes"]
    assert any(item["code"] == "monitor_error_observability_visible" for item in classification["pass"])
    assert any(item["code"] == "monitor_error_observability_suppressed_errors" for item in classification["warn"])
    assert any(item["code"] == "monitor_live_write_errors_visible" for item in classification["warn"])
    assert "ErrorObservability" in rendered
    assert "'live_write_error_count': 1" in rendered


def test_prefetch_observability_probe_error_does_not_pollute_runtime_suppressed_errors():
    snapshot = _healthy_snapshot()
    baseline = classify_snapshot(snapshot)
    snapshot["module_artifacts"]["prefetch_observability"] = {
        "schema_version": "memory-os.prefetch_observability.v0",
        "status": "error",
        "suppressed_error_count": 1,
        "recent_error_codes": ["prefetch_observability_probe_error"],
        "error_records": [
            {
                "schema_version": "memory-os.error_record.v0",
                "component": "prefetch",
                "operation": "monitor_observability_probe",
                "error_code": "prefetch_observability_probe_error",
                "severity": "warning",
                "recoverable": True,
            }
        ],
    }

    summary = monitor.monitor_error_observability(snapshot)
    classification = classify_snapshot(snapshot)

    assert summary["suppressed_error_count"] == 0
    assert summary["degraded_component_count"] == 0
    assert summary["monitor_probe_error_count"] == 1
    assert summary["monitor_probe_error_codes"] == ["prefetch_observability_probe_error"]
    assert not any(item["code"] == "monitor_error_observability_suppressed_errors" for item in classification["warn"])
    assert any(item["code"] == "monitor_error_observability_self_probe_error_visible" for item in classification["pass"])
    assert classification["status"] == baseline["status"]
    assert {item["code"] for item in classification["warn"]} == {item["code"] for item in baseline["warn"]}


def test_classify_snapshot_makes_owner_informational_aging_visible():
    snapshot = _healthy_snapshot()
    snapshot["owner_review_aging"].update(
        {
            "informational_retention_days": 30,
            "stale_informational_count": 5,
            "stale_review_suggested_count": 2,
            "stale_fyi_count": 3,
        }
    )

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "owner_review_informational_aging_visible" for item in classification["pass"])
    assert "stale_informational': 5" in rendered
    assert "informational_retention_days': 30" in rendered


def test_classify_snapshot_fails_when_owner_review_aging_mutates_state_or_body():
    snapshot = _healthy_snapshot()
    snapshot["owner_review_aging"]["canonical_state_changed"] = True
    snapshot["owner_review_aging"]["owner_action_created"] = True
    snapshot["owner_review_aging"]["raw_body_included"] = True

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_aging_canonical_state_changed_true" for item in classification["fail"])
    assert any(item["code"] == "owner_review_aging_owner_action_created_true" for item in classification["fail"])
    assert any(item["code"] == "owner_review_aging_raw_body_included_true" for item in classification["fail"])


def test_classify_snapshot_passes_module_artifact_summary_and_fails_on_actual_send():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"] = {
        "schema_version": "memory-os.module_artifact_summary.v0",
        "status": "ok",
        "digest": {"daily_artifact_count": 2, "weekly_artifact_count": 1},
        "wandering": {"output_count": 10, "would_send_count": 10},
        "evidence": {"score_count": 545, "subject_counts": {"candidate": 158}},
        "proposal_queue": {"candidate_count": 14, "state_counts": {"candidate": 13}},
        "self_evolution": {"report_count": 11, "proposal_count": 11, "last_status": "ok"},
        "governance_feedback": {"emitted_event_count": 57},
        "deep_reflection": {"report_count": 17, "current_injection_exists": True},
        "ops_gate": {
            "report_count": 22,
            "blocked_decision_count": 0,
            "run_report_count": 23,
            "skipped_run_count": 1,
            "latest_cadence_skipped": True,
            "latest_skip_reason": "no_pending_proposed_actions",
        },
        "speak_gate": {"would_send_count": 0, "actual_send": False},
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "module_artifact_summary_ok" for item in classification["pass"])
    assert any(item["code"] == "ops_gate_no_pending_skip_visible" for item in classification["pass"])

    snapshot["module_artifacts"]["speak_gate"]["actual_send"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "module_artifact_speak_gate_actual_send_true" for item in classification["fail"])


def test_classify_snapshot_tracks_expression_feedback_and_left_brain_pipeline():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "expression_feedback_subject_count": 3,
        "expression_feedback_linked_subject_count": 1,
        "expression_feedback_unlinked_subject_count": 2,
        "expired_used_in_scoring_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "left_brain_pipeline_check_visible" for item in classification["pass"])
    assert any(item["code"] == "expression_feedback_report_only" for item in classification["pass"])
    assert any(item["code"] == "left_brain_expression_feedback_context_linked" for item in classification["pass"])
    assert any(item["code"] == "left_brain_feedback_proposal_quality_ready" for item in classification["pass"])

    snapshot["module_artifacts"]["left_brain_pipeline_check"]["memory_sources_policy_quality_ready_count"] = 1
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "left_brain_memory_sources_policy_quality_ready" for item in classification["pass"])

    snapshot["module_artifacts"]["left_brain_pipeline_check"]["status"] = "fail"
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "left_brain_pipeline_check_failed" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["expression_feedback"]["live_policy_changed_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "expression_feedback_live_policy_changed" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["expression_policy_quality_ready_count"] = 0
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["expression_policy_quality_blocked_count"] = 1
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["proposal_quality_missing_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_feedback_proposal_quality_blocked" for item in classification["warn"])
    assert any(item["code"] == "left_brain_proposal_quality_metadata_missing" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["memory_sources_policy_quality_blocked_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_memory_sources_policy_quality_blocked" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["agenda_trace_missing_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_proposal_agenda_trace_missing" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "expression_feedback_subject_count": 2,
        "expression_feedback_linked_subject_count": 0,
        "expression_feedback_unlinked_subject_count": 2,
        "expired_used_in_scoring_count": 0,
    }
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_expression_feedback_unlinked_only" for item in classification["warn"])


def test_classify_snapshot_warns_when_expired_working_is_scored():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"] = {
        "schema_version": "memory-os.module_artifact_summary.v0",
        "status": "ok",
        "speak_gate": {"would_send_count": 0, "actual_send": False},
        "evidence": {"expired_used_in_scoring_count": 3},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_expired_working_used_in_scoring" for item in classification["warn"])


def test_classify_snapshot_tracks_deep_reflection_expired_working_hygiene():
    snapshot = _healthy_snapshot()
    snapshot["deep_reflection"]["latest_active_working_input_count"] = 3
    snapshot["deep_reflection"]["latest_expired_working_skipped_count"] = 12
    snapshot["deep_reflection"]["latest_expired_working_used_in_analysis_count"] = 0
    snapshot["deep_reflection"]["cadence_skipped_count"] = 1
    snapshot["deep_reflection"]["latest_skip_reason"] = "unchanged_input_fingerprint"

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "deep_reflection_expired_working_not_used" for item in classification["pass"])
    assert any(item["code"] == "deep_reflection_cadence_skip_visible" for item in classification["pass"])

    snapshot["deep_reflection"]["latest_expired_working_used_in_analysis_count"] = 2
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "deep_reflection_expired_working_used_in_analysis" for item in classification["warn"])


def test_classify_snapshot_tracks_deep_reflection_bounded_policy():
    snapshot = _healthy_snapshot()
    snapshot["deep_reflection"]["policy_present"] = True
    snapshot["deep_reflection"]["policy_version"] = 2
    snapshot["deep_reflection"]["policy_apply_count"] = 2
    snapshot["deep_reflection"]["policy_live_applied"] = False
    snapshot["deep_reflection"]["policy_actual_execute_count"] = 0
    snapshot["deep_reflection"]["policy_raw_body_included_count"] = 0

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "deep_reflection_bounded_policy_visible" for item in classification["pass"])

    snapshot["deep_reflection"]["policy_actual_execute_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "deep_reflection_policy_actual_execute_true" for item in classification["fail"])


def test_classify_snapshot_tracks_primary_feature_scoring_and_legacy_comparison():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "evidence_count": 4,
        "score_count": 4,
        "score_mode": "feature_maturity_v2",
        "subject_counts": {"event": 1, "working": 1, "proposal": 1, "crystallized_candidate": 1},
        "working_subject_count": 1,
        "expired_used_in_scoring_count": 0,
        "feature_score_mode": "primary",
        "feature_score_count": 4,
        "hash_score_legacy_count": 0,
        "legacy_hash_comparison_count": 4,
        "comparison_count": 4,
        "feature_score_live_applied": False,
        "owner_feedback_signal_count": 0,
        "expression_feedback_subject_count": 0,
        "run_report_count": 2,
        "skipped_run_count": 1,
        "latest_cadence_skipped": True,
        "latest_skip_reason": "unchanged_input_fingerprint",
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "left_brain_feature_scoring_primary_ok" for item in classification["pass"])
    assert any(item["code"] == "evidence_scoring_cadence_skip_visible" for item in classification["pass"])
    assert "feature_score_count" in rendered
    assert "legacy_hash_comparison_count" in rendered
    assert "skipped_run_count" in rendered

    snapshot["module_artifacts"]["evidence"]["hash_score_legacy_count"] = 4
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "left_brain_legacy_hash_scores_still_primary" for item in classification["fail"])


def test_classify_snapshot_tracks_prototype_aligned_maturity_scoring_primary():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "evidence_count": 4,
        "score_count": 4,
        "expired_used_in_scoring_count": 0,
        "score_mode": "feature_maturity_v2",
        "feature_score_mode": "primary",
        "feature_score_count": 4,
        "hash_score_legacy_count": 0,
        "legacy_hash_comparison_count": 4,
        "comparison_count": 4,
        "feature_score_live_applied": False,
        "prototype_aligned_score_count": 4,
        "maturity_dimension_count": 9,
        "maturity_dimension_keys": [
            "actionability",
            "duplicate_backlog",
            "evidence_strength",
            "freshness_decay",
            "gate_state",
            "owner_feedback",
            "recurrence",
            "risk",
            "source_diversity",
        ],
        "maturity_live_applied": False,
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "left_brain_maturity_scoring_primary_ok" for item in classification["pass"])
    assert "prototype_aligned_score_count" in rendered
    assert "maturity_dimension_count" in rendered

    snapshot["module_artifacts"]["evidence"]["maturity_live_applied"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "left_brain_maturity_scoring_live_applied" for item in classification["fail"])


def test_classify_snapshot_tracks_right_brain_expression_adapter_requests():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"] = {
        "request_count": 2,
        "latest_channel": "origin",
        "latest_delivery_mode": "hermes_cron_agent",
        "latest_actual_send": False,
        "raw_body_included_count": 0,
        "silent_request_count": 0,
        "outcome_count": 0,
        "outcome_actual_send_count": 0,
        "outcome_actual_execute_count": 0,
        "outcome_raw_body_included_count": 0,
        "outcome_internal_marker_count": 0,
    }
    snapshot["expression_artifacts"]["right_brain_adapter_request_count"] = 2
    snapshot["expression_artifacts"]["right_brain_adapter_latest_channel"] = "origin"
    snapshot["expression_artifacts"]["right_brain_adapter_latest_delivery_mode"] = "hermes_cron_agent"
    snapshot["expression_artifacts"]["right_brain_adapter_raw_body_included_count"] = 0

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "right_brain_expression_adapter_visible" for item in classification["pass"])
    assert any(item["code"] == "right_brain_expression_outcome_missing" for item in classification["warn"])
    assert "right_brain_adapter_request_count" in rendered

    snapshot["module_artifacts"]["right_brain_expression_adapter"]["latest_actual_send"] = True
    snapshot["expression_artifacts"]["right_brain_adapter_latest_actual_send"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "right_brain_expression_adapter_actual_send_true" for item in classification["fail"])


def test_classify_snapshot_tracks_right_brain_expression_outcomes():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"] = {
        "request_count": 2,
        "latest_channel": "origin",
        "latest_delivery_mode": "hermes_cron_agent",
        "latest_actual_send": False,
        "raw_body_included_count": 0,
        "silent_request_count": 0,
        "outcome_count": 1,
        "latest_outcome_id": "rbout_123",
        "latest_outcome_request_id": "rbexpr_123",
        "latest_outcome_policy_version": 1,
        "latest_outcome_silent": False,
        "latest_outcome_preview_chars": 38,
        "outcome_actual_send_count": 0,
        "outcome_actual_execute_count": 0,
        "outcome_raw_body_included_count": 0,
        "outcome_internal_marker_count": 0,
        "outcome_feedback_count": 1,
        "latest_outcome_feedback_count": 1,
        "outcome_feedback_missing_count": 0,
    }
    snapshot["module_artifacts"]["expression_feedback"] = {
        "feedback_count": 1,
        "live_policy_changed_count": 0,
        "raw_body_included_count": 0,
        "linked_outcome_count": 1,
        "unlinked_count": 0,
        "linked_outcome_missing_count": 0,
    }
    snapshot["expression_artifacts"]["right_brain_adapter_request_count"] = 2
    snapshot["expression_artifacts"]["right_brain_adapter_outcome_count"] = 1
    snapshot["expression_artifacts"]["right_brain_adapter_latest_outcome_silent"] = False
    snapshot["expression_artifacts"]["right_brain_adapter_latest_outcome_policy_version"] = 1
    snapshot["expression_artifacts"]["right_brain_adapter_outcome_internal_marker_count"] = 0
    snapshot["expression_artifacts"]["right_brain_adapter_outcome_feedback_count"] = 1
    snapshot["expression_artifacts"]["right_brain_adapter_latest_outcome_feedback_count"] = 1
    snapshot["expression_artifacts"]["expression_feedback_linked_outcome_count"] = 1

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert not any(item["code"] == "right_brain_expression_outcome_missing" for item in classification["warn"])
    assert any(item["code"] == "right_brain_expression_outcome_recorded" for item in classification["pass"])
    assert any(item["code"] == "right_brain_expression_feedback_linked" for item in classification["pass"])
    assert "right_brain_adapter_outcome_count" in rendered
    assert "right_brain_adapter_outcome_feedback_count" in rendered

    snapshot["module_artifacts"]["right_brain_expression_adapter"]["outcome_internal_marker_count"] = 1
    snapshot["expression_artifacts"]["right_brain_adapter_outcome_internal_marker_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "right_brain_expression_outcome_internal_marker" for item in classification["fail"])


def test_classify_snapshot_passes_owner_approved_right_brain_speak_once_send():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["speak_permission"] = {
        "ticket_count": 1,
        "sent_count": 1,
        "latest_status": "sent",
        "latest_actual_send": True,
        "unapproved_send_count": 0,
        "raw_body_included_count": 0,
        "error_count": 0,
    }
    snapshot["expression_artifacts"]["speak_permission_sent_count"] = 1

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "right_brain_allow_speak_once_sent" for item in classification["pass"])
    assert not any(item["code"].startswith("right_brain_allow_speak_once_") for item in classification["fail"])


def test_classify_snapshot_fails_when_expression_feedback_links_missing_outcome():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"]["outcome_count"] = 1
    snapshot["module_artifacts"]["right_brain_expression_adapter"]["outcome_feedback_missing_count"] = 1
    snapshot["module_artifacts"]["expression_feedback"] = {
        "feedback_count": 1,
        "live_policy_changed_count": 0,
        "raw_body_included_count": 0,
        "linked_outcome_count": 1,
        "unlinked_count": 0,
        "linked_outcome_missing_count": 1,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "right_brain_expression_feedback_missing_outcome" for item in classification["fail"])


def test_classify_snapshot_warns_when_right_brain_reaction_volume_is_thin():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"] = {
        "request_count": 2,
        "latest_actual_send": False,
        "raw_body_included_count": 0,
        "policy_actual_execute_count": 0,
        "policy_raw_body_included_count": 0,
        "outcome_count": 2,
        "outcome_actual_send_count": 0,
        "outcome_actual_execute_count": 0,
        "outcome_raw_body_included_count": 0,
        "outcome_internal_marker_count": 0,
        "outcome_feedback_count": 1,
        "outcome_feedback_missing_count": 0,
        "latest_outcome_feedback_count": 1,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "right_brain_expression_reaction_volume_thin" for item in classification["warn"])


def test_classify_snapshot_passes_when_right_brain_reaction_volume_is_sufficient():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"] = {
        "request_count": 3,
        "latest_actual_send": False,
        "raw_body_included_count": 0,
        "policy_actual_execute_count": 0,
        "policy_raw_body_included_count": 0,
        "outcome_count": 3,
        "outcome_actual_send_count": 0,
        "outcome_actual_execute_count": 0,
        "outcome_raw_body_included_count": 0,
        "outcome_internal_marker_count": 0,
        "outcome_feedback_count": 3,
        "outcome_feedback_missing_count": 0,
        "latest_outcome_feedback_count": 1,
    }

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "right_brain_expression_reaction_volume_sufficient" for item in classification["pass"]
    )
    assert not any(item["code"] == "right_brain_expression_reaction_volume_thin" for item in classification["warn"])


def test_classify_snapshot_tracks_module_cadence_report():
    snapshot = _healthy_snapshot()
    snapshot["module_cadence"] = {
        "schema_version": "memory-os.module_cadence_monitor_summary.v0",
        "report_count": 1,
        "latest_report_id": "cadence_123",
        "latest_status": "warning",
        "module_count": 18,
        "cron_job_count": 2,
        "cognitive_loop_report_count": 30,
        "integration_harness_member_count": 11,
        "split_recommended_count": 10,
        "expected_hermes_cron_missing_count": 0,
        "finding_count": 10,
        "generated_count": 17,
        "skipped_count": 3,
        "error_count": 1,
        "historical_error_count": 1,
        "current_window_error_count": 0,
        "duplicate_count": 2,
        "counter_coverage_count": 18,
        "module_counters": {
            "self_evolution": {
                "run_count": 2,
                "generated_count": 1,
                "skipped_count": 1,
                "error_count": 0,
                "duplicate_count": 1,
                "last_run_at": "2026-05-26T02:00:00+00:00",
                "last_status": "ok",
            }
        },
        "module_current_window_error_counts": {"self_evolution": 0},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "cron_modified": False,
        },
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "module_cadence_report_visible" for item in classification["pass"])
    assert any(item["code"] == "module_cadence_historical_errors_visible" for item in classification["pass"])
    assert any(item["code"] == "module_cadence_split_pending" for item in classification["warn"])
    assert not any(item["code"] == "module_cadence_current_window_errors" for item in classification["fail"])
    assert "ModuleCadence" in rendered
    assert snapshot["module_cadence"]["module_counters"]["self_evolution"]["duplicate_count"] == 1

    snapshot["module_cadence"]["finding_count"] = 0
    snapshot["module_cadence"]["latest_status"] = "ok"
    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "module_cadence_split_pending" for item in classification["warn"])

    snapshot["module_cadence"]["finding_count"] = 10
    snapshot["module_cadence"]["boundary"]["cron_modified"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "module_cadence_boundary_true" for item in classification["fail"])


def test_classify_snapshot_fails_current_window_module_cadence_errors():
    snapshot = _healthy_snapshot()
    snapshot["module_cadence"] = {
        "schema_version": "memory-os.module_cadence_monitor_summary.v0",
        "report_count": 1,
        "latest_report_id": "cadence_error",
        "latest_status": "warning",
        "finding_count": 0,
        "expected_hermes_cron_missing_count": 0,
        "error_count": 9,
        "historical_error_count": 9,
        "current_window_error_count": 1,
        "module_current_window_error_counts": {"evidence_scoring": 1},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "cron_modified": False,
        },
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "module_cadence_current_window_errors"
        and item["current_window_error_count"] == 1
        and item["module_counts"] == {"evidence_scoring": 1}
        for item in classification["fail"]
    )


def test_classify_snapshot_warns_when_module_cadence_error_window_is_legacy_unknown():
    snapshot = _healthy_snapshot()
    snapshot["module_cadence"] = {
        "schema_version": "memory-os.module_cadence_monitor_summary.v0",
        "report_count": 1,
        "latest_report_id": "cadence_legacy",
        "latest_status": "warning",
        "finding_count": 0,
        "expected_hermes_cron_missing_count": 0,
        "error_count": 2,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "cron_modified": False,
        },
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "module_cadence_error_window_unknown" for item in classification["warn"])


def test_module_cadence_summary_exposes_generated_skipped_error_duplicate_counters(monkeypatch):
    report = {
        "schema_version": "memory-os.module_cadence_report.v0",
        "report_id": "cadence_123",
        "status": "warning",
        "module_count": 18,
        "cron_job_count": 2,
        "cognitive_loop_report_count": 30,
        "integration_harness_member_count": 11,
        "split_recommended_count": 10,
        "expected_hermes_cron_missing_count": 0,
        "finding_count": 10,
        "generated_count": 17,
        "skipped_count": 3,
        "error_count": 1,
        "historical_error_count": 1,
        "current_window_error_count": 0,
        "duplicate_count": 2,
        "counter_coverage_count": 18,
        "modules": [
            {
                "module": "self_evolution",
                "cadence_counters": {
                    "run_count": 2,
                    "generated_count": 1,
                    "skipped_count": 1,
                    "error_count": 0,
                    "duplicate_count": 1,
                    "last_run_at": "2026-05-26T02:00:00+00:00",
                    "last_status": "ok",
                },
                "current_window_error_count": 0,
            }
        ],
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "cron_modified": False,
        },
    }
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)
    monkeypatch.setitem(namespace, "_read_jsonl", lambda path: [report])

    summary = namespace["module_cadence_summary"]()

    assert summary["generated_count"] == 17
    assert summary["skipped_count"] == 3
    assert summary["error_count"] == 1
    assert summary["historical_error_count"] == 1
    assert summary["current_window_error_count"] == 0
    assert summary["duplicate_count"] == 2
    assert summary["counter_coverage_count"] == 18
    assert summary["module_counters"]["self_evolution"]["duplicate_count"] == 1
    assert summary["module_current_window_error_counts"]["self_evolution"] == 0


def test_module_cadence_summary_derives_missing_current_window_total_from_modules(monkeypatch):
    report = {
        "schema_version": "memory-os.module_cadence_report.v0",
        "report_id": "cadence_legacy_aggregate",
        "status": "ok",
        "module_count": 2,
        "error_count": 15,
        "historical_error_count": 15,
        "modules": [
            {
                "module": "self_evolution",
                "cadence_counters": {"error_count": 0},
                "current_window_error_count": 0,
            },
            {
                "module": "speak_gate",
                "cadence_counters": {"error_count": 15},
                "current_window_error_count": 0,
            },
        ],
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "cron_modified": False,
        },
    }
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)
    monkeypatch.setitem(namespace, "_read_jsonl", lambda path: [report])

    summary = namespace["module_cadence_summary"]()

    assert summary["historical_error_count"] == 15
    assert summary["current_window_error_count"] == 0
    assert summary["module_current_window_error_counts"] == {
        "self_evolution": 0,
        "speak_gate": 0,
    }


def test_classify_snapshot_warns_when_session_activity_has_no_hook_marker_delta():
    snapshot = _healthy_snapshot()
    snapshot["session_activity"] = {"total_session_events": 12}
    snapshot["hook_markers"] = {"started": 5, "reset": 4, "finalized": 4, "total": 13}
    snapshot["deltas"] = {
        "session_activity_delta": {"total_session_events": 2},
        "hook_marker_delta": {"started": 0, "reset": 0, "finalized": 0, "total": 0},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "hook_markers_missing_for_session_activity" for item in classification["warn"])


def test_classify_snapshot_passes_hook_coverage_when_no_session_activity_delta():
    snapshot = _healthy_snapshot()
    snapshot["session_activity"] = {"total_session_events": 12}
    snapshot["hook_markers"] = {"started": 5, "reset": 4, "finalized": 4, "total": 13}
    snapshot["deltas"] = {
        "session_activity_delta": {"total_session_events": 0},
        "hook_marker_delta": {"started": 0, "reset": 0, "finalized": 0, "total": 0},
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "hook_coverage_no_session_activity" for item in classification["pass"])
    assert not any(item["code"] == "hook_markers_missing_for_session_activity" for item in classification["warn"])


def test_classify_snapshot_tracks_session_mirror_pending_as_observation():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 29,
        "pending_session_count": 25,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 25,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 0,
        "pending_only_groups": [],
        "raw_private_body_printed": False,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_dry_run_ok" for item in classification["pass"])
    assert any(item["code"] == "session_mirror_pending_no_correlated_gap" for item in classification["pass"])
    assert not any(item["code"] == "session_mirror_pending_sessions" for item in classification["warn"])
    assert not any(item["code"].startswith("session_mirror_") for item in classification["fail"])


def test_classify_snapshot_warns_when_session_mirror_pending_only_groups_exist():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 29,
        "pending_session_count": 25,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 25,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 1,
        "pending_only_groups": ["new_owner_topic"],
        "raw_private_body_printed": False,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_pending_source_gap" for item in classification["warn"])
    assert not any(item["code"] == "session_mirror_pending_sessions" for item in classification["warn"])


def test_classify_snapshot_fails_when_session_mirror_dry_run_writes_or_has_findings():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 29,
        "pending_session_count": 25,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 25,
        "dry_run_written_event_ids_count": 1,
        "dry_run_findings_count": 2,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_dry_run_wrote_events" for item in classification["fail"])
    assert any(item["code"] == "session_mirror_dry_run_findings" for item in classification["fail"])


def test_classify_snapshot_passes_bounded_session_mirror_apply_evidence():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 30,
        "pending_session_count": 24,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 24,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 0,
        "pending_only_groups": [],
        "raw_private_body_printed": False,
        "latest_apply_status": "ok",
        "latest_apply_bounded": True,
        "latest_apply_written_event_ids_count": 1,
        "latest_apply_duplicate_ignored_count": 0,
        "latest_apply_raw_private_body_printed": False,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_apply_bounded_ok" for item in classification["pass"])
    assert not any(item["code"].startswith("session_mirror_apply_") for item in classification["fail"])


def test_classify_snapshot_passes_governed_session_mirror_apply_evidence():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 30,
        "pending_session_count": 24,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 24,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 0,
        "pending_only_groups": [],
        "raw_private_body_printed": False,
        "latest_apply_status": "ok",
        "latest_apply_bounded": True,
        "latest_apply_written_event_ids_count": 1,
        "latest_apply_duplicate_ignored_count": 0,
        "latest_apply_raw_private_body_printed": False,
        "latest_apply_approval_resolved": True,
        "latest_apply_owner_channel_bound": True,
        "latest_apply_owner_approved": True,
        "latest_apply_approval_source": "owner_action_ledger",
        "latest_apply_reused_approval_ref": False,
        "latest_apply_stable_scope_id": "scope-ok",
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_apply_governed_owner_ref_ok" for item in classification["pass"])
    assert not any(item["code"] == "session_mirror_apply_owner_approved_without_resolver" for item in classification["fail"])


def test_classify_snapshot_passes_session_mirror_lane_graduated_auto_apply():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 30,
        "pending_session_count": 24,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 24,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 0,
        "pending_only_groups": [],
        "raw_private_body_printed": False,
        "latest_apply_status": "ok",
        "latest_apply_bounded": True,
        "latest_apply_written_event_ids_count": 1,
        "latest_apply_duplicate_ignored_count": 0,
        "latest_apply_raw_private_body_printed": False,
        "latest_apply_approval_resolved": True,
        "latest_apply_owner_channel_bound": True,
        "latest_apply_owner_approved": True,
        "latest_apply_approval_source": "owner_action_lane_graduation",
        "latest_apply_reused_approval_ref": False,
        "latest_apply_stable_scope_id": "scope-auto",
        "latest_apply_auto_apply": True,
        "latest_apply_lane_graduated": True,
        "latest_apply_execution_gate_envelope_id": "xgate_session_mirror",
        "session_mirror_auto_apply_execution_gate_bound": True,
        "session_mirror_auto_apply_permit_integrity": {
            "status": "ok",
            "execution_gate_envelope_id": "xgate_session_mirror",
            "lane_id": "session_mirror_auto_apply",
            "risk_class": "bounded_append_only_data_ingress",
            "expires_at_status": "valid",
            "unused_before_apply": True,
            "consumed_after_apply": True,
            "scope_match": True,
        },
        "latest_apply_boundary_true_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_apply_governed_owner_ref_ok" for item in classification["pass"])
    assert any(item["code"] == "session_mirror_apply_lane_graduated_auto_ok" for item in classification["pass"])
    assert any(item["code"] == "session_mirror_auto_apply_execution_gate_bound" for item in classification["pass"])
    assert any(item["code"] == "session_mirror_auto_apply_permit_integrity_ok" for item in classification["pass"])
    assert not any(item["code"].startswith("session_mirror_apply_") for item in classification["fail"])


def test_classify_snapshot_fails_session_mirror_auto_apply_without_execution_gate():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 30,
        "pending_session_count": 24,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 24,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 0,
        "pending_only_groups": [],
        "raw_private_body_printed": False,
        "latest_apply_status": "ok",
        "latest_apply_bounded": True,
        "latest_apply_written_event_ids_count": 1,
        "latest_apply_duplicate_ignored_count": 0,
        "latest_apply_raw_private_body_printed": False,
        "latest_apply_approval_resolved": True,
        "latest_apply_owner_channel_bound": True,
        "latest_apply_owner_approved": True,
        "latest_apply_approval_source": "owner_action_lane_graduation",
        "latest_apply_auto_apply": True,
        "latest_apply_lane_graduated": True,
        "latest_apply_execution_gate_envelope_id": "",
        "session_mirror_auto_apply_execution_gate_bound": False,
        "latest_apply_boundary_true_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "session_mirror_auto_apply_execution_gate_missing" for item in classification["fail"])


def test_classify_snapshot_fails_session_mirror_auto_apply_permit_integrity_mismatch():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 30,
        "pending_session_count": 24,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 24,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 0,
        "pending_only_groups": [],
        "raw_private_body_printed": False,
        "latest_apply_status": "ok",
        "latest_apply_bounded": True,
        "latest_apply_written_event_ids_count": 1,
        "latest_apply_duplicate_ignored_count": 0,
        "latest_apply_raw_private_body_printed": False,
        "latest_apply_approval_resolved": True,
        "latest_apply_owner_channel_bound": True,
        "latest_apply_owner_approved": True,
        "latest_apply_approval_source": "owner_action_lane_graduation",
        "latest_apply_auto_apply": True,
        "latest_apply_lane_graduated": True,
        "latest_apply_execution_gate_envelope_id": "xgate_scope_mismatch",
        "session_mirror_auto_apply_execution_gate_bound": True,
        "session_mirror_auto_apply_permit_integrity": {
            "status": "invalid",
            "reason": "execution_gate_scope_mismatch",
            "execution_gate_envelope_id": "xgate_scope_mismatch",
            "lane_id": "session_mirror_auto_apply",
            "risk_class": "bounded_append_only_data_ingress",
            "expires_at_status": "valid",
            "unused_before_apply": True,
            "consumed_after_apply": True,
            "scope_match": False,
        },
        "latest_apply_boundary_true_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "session_mirror_auto_apply_permit_integrity_invalid" for item in classification["fail"])


def test_session_mirror_permit_integrity_accepts_completed_permit_after_ttl(monkeypatch):
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)
    latest_apply = {
        "max_sessions": 1,
        "platform_allowlist": ["telegram"],
        "selected_session_fingerprints": ["smfp_done"],
    }
    latest_governance = {
        "approval_ref": "oa_graduated",
        "stable_scope_id": "lane:telegram",
        "execution_gate_envelope_id": "xgate_completed",
        "execution_gate_permit_resolution": {"unused_before_apply": True},
    }
    scope = {
        "approval_ref": "oa_graduated",
        "stable_scope_id": "lane:telegram",
        "max_sessions_per_run": 1,
        "platform_allowlist": ["telegram"],
        "selected_session_fingerprints": ["smfp_done"],
    }
    records = [
        {
            "stage": "permit",
            "execution_gate_envelope_id": "xgate_completed",
            "lane_id": "session_mirror_auto_apply",
            "risk_class": "bounded_append_only_data_ingress",
            "boundary_true": False,
            "boundary": {
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_unapproved_crystallized_approval": False,
            },
            "scope": scope,
            "scope_hash": namespace["_execution_gate_scope_hash"](scope),
            "created_at": "2000-01-01T00:00:00Z",
            "expires_at": "2000-01-01T00:15:00Z",
        },
        {
            "stage": "completion",
            "execution_gate_envelope_id": "xgate_completed",
            "lane_id": "session_mirror_auto_apply",
            "created_at": "2000-01-01T00:00:05Z",
            "execution_status": "ok",
        },
    ]
    monkeypatch.setitem(namespace, "_read_jsonl", lambda path: records)

    integrity = namespace["session_mirror_auto_apply_permit_integrity"](latest_apply, latest_governance)

    assert integrity["status"] == "ok"
    assert integrity["expires_at_status"] == "valid_at_completion"
    assert integrity["consumed_after_apply"] is True


def test_session_mirror_permit_integrity_rejects_multiple_completions(monkeypatch):
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)
    latest_apply = {
        "max_sessions": 1,
        "platform_allowlist": ["telegram"],
        "selected_session_fingerprints": ["smfp_done"],
    }
    latest_governance = {
        "approval_ref": "oa_graduated",
        "stable_scope_id": "lane:telegram",
        "execution_gate_envelope_id": "xgate_completed_twice",
        "execution_gate_permit_resolution": {"unused_before_apply": True},
    }
    scope = {
        "approval_ref": "oa_graduated",
        "stable_scope_id": "lane:telegram",
        "max_sessions_per_run": 1,
        "platform_allowlist": ["telegram"],
        "selected_session_fingerprints": ["smfp_done"],
    }
    records = [
        {
            "stage": "permit",
            "execution_gate_envelope_id": "xgate_completed_twice",
            "lane_id": "session_mirror_auto_apply",
            "risk_class": "bounded_append_only_data_ingress",
            "boundary_true": False,
            "boundary": {
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_unapproved_crystallized_approval": False,
            },
            "scope": scope,
            "scope_hash": namespace["_execution_gate_scope_hash"](scope),
            "created_at": "2000-01-01T00:00:00Z",
            "expires_at": "2000-01-01T00:15:00Z",
        },
        {
            "stage": "completion",
            "execution_gate_envelope_id": "xgate_completed_twice",
            "lane_id": "session_mirror_auto_apply",
            "created_at": "2000-01-01T00:00:05Z",
            "execution_status": "ok",
        },
        {
            "stage": "completion",
            "execution_gate_envelope_id": "xgate_completed_twice",
            "lane_id": "session_mirror_auto_apply",
            "created_at": "2000-01-01T00:00:06Z",
            "execution_status": "ok",
        },
    ]
    monkeypatch.setitem(namespace, "_read_jsonl", lambda path: records)

    integrity = namespace["session_mirror_auto_apply_permit_integrity"](latest_apply, latest_governance)

    assert integrity["status"] == "invalid"
    assert integrity["reason"] == "execution_gate_completion_count_not_one"
    assert integrity["completion_count"] == 2


def test_classify_snapshot_fails_session_mirror_apply_boundary_true():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 1,
        "covered_session_count": 0,
        "pending_session_count": 0,
        "dry_run_status": "ok",
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "raw_private_body_printed": False,
        "latest_apply_status": "ok",
        "latest_apply_bounded": True,
        "latest_apply_written_event_ids_count": 1,
        "latest_apply_duplicate_ignored_count": 0,
        "latest_apply_raw_private_body_printed": False,
        "latest_apply_boundary_true_count": 1,
        "latest_apply_boundary": {"actual_send": True},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "session_mirror_apply_boundary_true" for item in classification["fail"])


def test_classify_snapshot_passes_memory_os_cron_execution_gate_coverage():
    snapshot = _healthy_snapshot()
    snapshot["execution_gate_cron"] = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "classification_source": "hermes_cron_adapter_probe",
        "adapter_owner": "hermes_memory_os_seam",
        "memory_os_owned_expected_count": 7,
        "memory_os_owned_wrapped_count": 7,
        "memory_os_owned_naked_count": 0,
        "memory_os_like_unregistered_count": 0,
        "unclassified_count": 0,
        "hermes_host_owned_count": 3,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "execution_gate_memory_os_cron_wrapped_ok" for item in classification["pass"])
    assert any(item["code"] == "execution_gate_cron_adapter_host_owned" for item in classification["pass"])
    assert not any(item["code"].startswith("execution_gate_memory_os_cron") for item in classification["fail"])


def test_classify_snapshot_fails_when_cron_probe_is_not_host_owned():
    snapshot = _healthy_snapshot()
    snapshot["execution_gate_cron"] = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "classification_source": "hermes_cron_adapter_probe",
        "adapter_owner": "",
        "memory_os_owned_expected_count": 1,
        "memory_os_owned_wrapped_count": 1,
        "memory_os_owned_naked_count": 0,
        "memory_os_like_unregistered_count": 0,
        "unclassified_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "execution_gate_cron_adapter_not_host_owned" for item in classification["fail"])


def test_classify_snapshot_fails_production_when_known_optional_cron_enabled_outside_active_registry():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "live"
    snapshot["execution_gate_cron"] = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "active_registry_job_count": 2,
        "enabled_memory_os_job_count": 7,
        "memory_os_owned_expected_count": 2,
        "memory_os_owned_wrapped_count": 2,
        "memory_os_owned_naked_count": 0,
        "memory_os_like_unregistered_count": 0,
        "unclassified_count": 0,
        "enabled_known_optional_outside_active_registry_count": 5,
        "enabled_known_optional_outside_active_registry_jobs": [
            {"name": "memory-os-module-cadence-report", "enabled": True}
        ],
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "execution_gate_memory_os_cron_known_optional_enabled_outside_active_registry"
        for item in classification["warn"]
    )
    assert any(
        item["code"]
        == "execution_gate_memory_os_cron_known_optional_enabled_outside_active_registry_in_production"
        for item in classification["fail"]
    )


def test_classify_snapshot_warns_clean_host_when_known_optional_cron_enabled_outside_active_registry():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean-host"
    snapshot["execution_gate_cron"] = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "active_registry_job_count": 2,
        "enabled_memory_os_job_count": 7,
        "memory_os_owned_expected_count": 2,
        "memory_os_owned_wrapped_count": 2,
        "memory_os_owned_naked_count": 0,
        "memory_os_like_unregistered_count": 0,
        "unclassified_count": 0,
        "enabled_known_optional_outside_active_registry_count": 5,
        "enabled_known_optional_outside_active_registry_jobs": [
            {"name": "memory-os-module-cadence-report", "enabled": True}
        ],
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(
        item["code"] == "execution_gate_memory_os_cron_known_optional_enabled_outside_active_registry"
        for item in classification["warn"]
    )
    assert not classification["fail"]
    assert any(
        item["code"] == "execution_gate_memory_os_cron_known_optional_enabled_outside_active_registry"
        and item["classification"] == "expected_clean_host"
        for item in classification["clean_host_warn_classification"]
    )


def test_classify_snapshot_permanent_boundary_sentinels_fail_on_low_risk_authority_expansion():
    snapshot = _healthy_snapshot()
    snapshot["owner_review"]["unapproved_crystallized_write_count"] = 1
    snapshot["owner_review_proposal_auto_route"]["auto_followup_actual_execute_count"] = 1
    snapshot["owner_review_proposal_auto_route"]["auto_followup_policy_write_count"] = 1
    snapshot["owner_review_proposal_auto_route"]["auto_followup_actual_send_count"] = 1
    snapshot["owner_review_proposal_auto_route"]["boundary"] = {
        "actual_send": True,
        "actual_identity_write": True,
    }
    snapshot["rh31_eval"] = {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "ok",
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "retrieval_shadow": {
            "route_live_applied": True,
            "score_live_applied": True,
            "run_count": 1,
        },
    }
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "record_count": 1,
        "policy_actual_execute_count": 1,
    }
    snapshot["deep_reflection"]["policy_live_applied"] = True
    snapshot["deep_reflection"]["policy_actual_execute_count"] = 1
    snapshot["cognitive_loop"]["boundaries"] = {
        "actual_send": True,
        "actual_execute": True,
        "actual_identity_write": True,
        "actual_crystallized_approval": True,
    }

    classification = classify_snapshot(snapshot)
    fail_codes = {item["code"] for item in classification["fail"]}

    assert classification["status"] == "FAIL"
    assert {
        "owner_review_unapproved_crystallized_write",
        "owner_review_proposal_auto_route_actual_execute_count_nonzero",
        "owner_review_proposal_auto_route_policy_write_count_nonzero",
        "owner_review_proposal_auto_route_actual_send_count_nonzero",
        "owner_review_proposal_auto_route_actual_send_true",
        "owner_review_proposal_auto_route_actual_identity_write_true",
        "retrieval_shadow_live_applied",
        "memory_sources_policy_actual_execute_true",
        "deep_reflection_policy_live_applied_true",
        "deep_reflection_policy_actual_execute_true",
        "cognitive_loop_actual_send_true",
        "cognitive_loop_actual_execute_true",
        "cognitive_loop_actual_identity_write_true",
        "cognitive_loop_actual_crystallized_approval_true",
    }.issubset(fail_codes)


def test_classify_snapshot_emits_monitor_evidence_labels_by_profile():
    live = _healthy_snapshot()
    live_classification = classify_snapshot(live)

    assert live_classification["status"] == "WARN"
    assert live_classification["evidence_labels"] == ["live_monitor_warn"]

    clean_host = _healthy_snapshot()
    clean_host["monitor_profile"] = "clean-host"
    clean_host["owner_review_proposal_followups"]["awaiting_ops_gate_count"] = 1
    clean_host_classification = classify_snapshot(clean_host)

    assert clean_host_classification["status"] == "WARN"
    assert clean_host_classification["evidence_labels"] == ["clean_host_warn"]


def test_full_monitor_runtime_contract_warns_on_slow_runtime_without_runtime_fail():
    snapshot = _healthy_snapshot()
    snapshot["full_monitor_runtime_contract"] = monitor.full_monitor_runtime_contract(
        monitor_profile="live",
        elapsed_seconds=191.2,
        caller_timeout_seconds=120,
    )

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary(snapshot)

    warn_codes = {item["code"] for item in classification["warn"]}
    fail_codes = {item["code"] for item in classification["fail"]}
    assert "full_monitor_runtime_over_target" in warn_codes
    assert "full_monitor_caller_timeout_below_contract" in warn_codes
    assert "full_monitor_runtime_over_target" not in fail_codes
    assert "FullMonitorRuntime=" in rendered
    assert "'minimum_caller_timeout_seconds': 300" in rendered


def test_full_monitor_runtime_contract_merge_updates_evidence_label():
    snapshot = {
        "monitor_profile": "live",
        "classification": {"status": "PASS", "pass": [], "warn": [], "fail": [], "evidence_labels": ["live_monitor_pass"]},
        "full_monitor_runtime_contract": monitor.full_monitor_runtime_contract(
            monitor_profile="live",
            elapsed_seconds=191,
            caller_timeout_seconds=0,
        ),
    }

    monitor._merge_runtime_contract_classification(snapshot)

    assert snapshot["classification"]["status"] == "WARN"
    assert snapshot["classification"]["evidence_labels"] == ["live_monitor_warn"]


def test_classify_snapshot_fails_memory_os_cron_naked_or_unregistered_like_jobs():
    snapshot = _healthy_snapshot()
    snapshot["execution_gate_cron"] = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "memory_os_owned_expected_count": 7,
        "memory_os_owned_wrapped_count": 5,
        "memory_os_owned_naked_count": 1,
        "memory_os_like_unregistered_count": 1,
        "unclassified_count": 0,
        "naked_jobs": [{"name": "memory-os-module-cadence-report", "script": "memory_os_module_cadence_report_cron.py"}],
        "unregistered_like_jobs": [{"name": "memory-os-new-helper", "script": "memory_os_new_helper.py"}],
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "execution_gate_memory_os_cron_naked_job" for item in classification["fail"])
    assert any(item["code"] == "execution_gate_memory_os_cron_unregistered_like_job" for item in classification["fail"])


def test_classify_snapshot_fails_memory_os_cron_helper_boundary_true_and_warns_unobserved():
    snapshot = _healthy_snapshot()
    snapshot["execution_gate_cron"] = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "memory_os_owned_expected_count": 7,
        "memory_os_owned_wrapped_count": 7,
        "memory_os_owned_naked_count": 0,
        "memory_os_like_unregistered_count": 0,
        "unclassified_count": 0,
        "helper_completion_expected_count": 7,
        "helper_completion_completed_count": 6,
        "helper_completion_missing_count": 0,
        "helper_completion_not_due_count": 1,
        "helper_boundary_true_count": 1,
        "helper_boundary_unobserved_count": 1,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "execution_gate_memory_os_cron_helper_boundary_true" for item in classification["fail"])
    assert any(item["code"] == "execution_gate_memory_os_cron_helper_boundary_unobserved" for item in classification["warn"])


def test_classify_snapshot_warns_on_memory_os_cron_helper_stale_completion():
    snapshot = _healthy_snapshot()
    snapshot["execution_gate_cron"] = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "memory_os_owned_expected_count": 7,
        "memory_os_owned_wrapped_count": 7,
        "memory_os_owned_naked_count": 0,
        "memory_os_like_unregistered_count": 0,
        "unclassified_count": 0,
        "helper_completion_expected_count": 7,
        "helper_completion_completed_count": 7,
        "helper_completion_missing_count": 0,
        "helper_completion_stale_count": 1,
        "helper_completion_stale_lanes": ["module_cadence_report"],
        "helper_boundary_true_count": 0,
        "helper_boundary_unobserved_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "execution_gate_memory_os_cron_helper_completion_stale" for item in classification["warn"])


def test_classify_snapshot_warns_on_memory_os_cron_helper_disabled_completion():
    snapshot = _healthy_snapshot()
    snapshot["execution_gate_cron"] = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "memory_os_owned_expected_count": 7,
        "memory_os_owned_wrapped_count": 7,
        "memory_os_owned_naked_count": 0,
        "memory_os_like_unregistered_count": 0,
        "unclassified_count": 0,
        "helper_completion_expected_count": 7,
        "helper_completion_completed_count": 6,
        "helper_completion_missing_count": 0,
        "helper_completion_disabled_count": 1,
        "helper_completion_disabled_lanes": ["module_cadence_report"],
        "helper_boundary_true_count": 0,
        "helper_boundary_unobserved_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    disabled_warn = next(
        item for item in classification["warn"] if item["code"] == "execution_gate_memory_os_cron_helper_completion_disabled"
    )
    assert disabled_warn["count"] == 1
    assert disabled_warn["lanes"] == ["module_cadence_report"]
    assert not any(item["code"] == "execution_gate_memory_os_cron_helper_completion_missing" for item in classification["warn"])


def test_classify_snapshot_treats_null_status_tool_contract_as_failed_not_a_crash():
    snapshot = _healthy_snapshot()
    snapshot["status_tool_contract"] = None

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    failed = next(item for item in classification["fail"] if item["code"] == "status_tool_contract_failed")
    assert failed["value"] == {}


def test_classify_snapshot_fails_memory_os_cron_helper_error_completion():
    snapshot = _healthy_snapshot()
    snapshot["execution_gate_cron"] = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "memory_os_owned_expected_count": 7,
        "memory_os_owned_wrapped_count": 7,
        "memory_os_owned_naked_count": 0,
        "memory_os_like_unregistered_count": 0,
        "unclassified_count": 0,
        "helper_completion_expected_count": 7,
        "helper_completion_completed_count": 7,
        "helper_completion_missing_count": 0,
        "helper_completion_error_count": 1,
        "helper_completion_error_lanes": ["module_cadence_report"],
        "helper_boundary_true_count": 0,
        "helper_boundary_unobserved_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "execution_gate_memory_os_cron_helper_completion_error" for item in classification["fail"])


def test_memory_os_cron_specs_missing_snapshot_does_not_use_private_fallback(tmp_path):
    """Missing cron registry snapshot → empty list (no private fallback).

    Uses a custom hermes_home so the probe function looks for the registry
    at a path we control, rather than monkeypatching Path which breaks when
    internal path construction changes (e.g. from raw strings to
    _hermes_home-based Path joins).
    """
    original_sys_path = list(sys.path)
    try:
        script_prefix = monitor._remote_probe_script(str(tmp_path)).split(
            '\n# ---begin-probe-invocations---',
            1,
        )[0]
        namespace: dict[str, object] = {}
        exec(script_prefix, namespace)
        # tmp_path/memory-os/system/memory_os_cron_registry.json does not exist
        # → _memory_os_cron_specs_from_snapshot must return []
        assert namespace["_memory_os_cron_specs_from_snapshot"]() == []
    finally:
        sys.path[:] = original_sys_path

    # Counterfactual: with an actual registry file, specs are returned
    registry_dir = tmp_path / "memory-os" / "system"
    registry_dir.mkdir(parents=True)
    registry_dir.joinpath("memory_os_cron_registry.json").write_text(
        json.dumps({"specs": [{"key": "test-job", "name": "Test Job"}]}),
        encoding="utf-8",
    )
    try:
        script_prefix2 = monitor._remote_probe_script(str(tmp_path)).split(
            '\n# ---begin-probe-invocations---',
            1,
        )[0]
        namespace2: dict[str, object] = {}
        exec(script_prefix2, namespace2)
        specs = namespace2["_memory_os_cron_specs_from_snapshot"]()
        assert len(specs) == 1
        assert specs[0]["key"] == "test-job"
    finally:
        sys.path[:] = original_sys_path


def test_classify_snapshot_fails_session_mirror_owner_approved_without_owner_channel_binding():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 30,
        "pending_session_count": 24,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 24,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 0,
        "pending_only_groups": [],
        "raw_private_body_printed": False,
        "latest_apply_status": "ok",
        "latest_apply_bounded": True,
        "latest_apply_written_event_ids_count": 1,
        "latest_apply_duplicate_ignored_count": 0,
        "latest_apply_raw_private_body_printed": False,
        "latest_apply_approval_resolved": True,
        "latest_apply_owner_channel_bound": False,
        "latest_apply_owner_approved": True,
        "latest_apply_approval_source": "owner_action_ledger",
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "session_mirror_apply_owner_ref_not_owner_channel_bound" for item in classification["fail"])


def test_compact_rh31_eval_summary_strips_scores_from_monitor_snapshot():
    summary = {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "warning",
        "adapter_count": 6,
        "case_count": 6,
        "score_count": 27,
        "failure_count": 4,
        "failure_class_distribution": {"projection_miss": 1},
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "report_dir": "",
        "scores": [
            {
                "adapter": "memory_os_fts",
                "case_id": "private_case",
                "status": "fail",
                "failure_class": "fts_miss",
                "metric_scope": "context",
                "live_behavior_changed": False,
                "details": {"raw": "should not be retained"},
            }
        ],
        "source_distribution": {"working": 8},
    }

    compact = monitor.compact_rh31_eval_summary(summary)

    assert compact == {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "warning",
        "adapter_count": 6,
        "case_count": 6,
        "score_count": 27,
        "failure_count": 4,
        "failure_class_distribution": {"projection_miss": 1},
        "failure_attribution": [
            {
                "adapter": "memory_os_fts",
                "case_id": "private_case",
                "failure_class": "fts_miss",
                "metric_scope": "context",
                "live_behavior_changed": False,
                "guard_decision": "measurement_only",
            }
        ],
        "live_guard_candidate_count": 0,
        "measurement_signal_count": 1,
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "report_written": False,
        "source_distribution": {"working": 8},
    }


def test_compact_rh31_eval_summary_surfaces_retrieval_shadow_without_raw_details():
    summary = {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "pass",
        "adapter_count": 1,
        "case_count": 1,
        "score_count": 1,
        "failure_count": 0,
        "failure_class_distribution": {},
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "report_dir": "",
        "scores": [
            {
                "adapter": "retrieval_shadow",
                "case_id": "retrieval_shadow_summary",
                "status": "pass",
                "metric_scope": "retrieval_shadow",
                "details": {
                    "schema_version": "memory-os.retrieval_shadow_eval.v0",
                    "run_count": 1,
                    "semantic_gap_count": 2,
                    "hybrid_would_retrieve_count": 3,
                    "rrf_would_rank_count": 2,
                    "live_input_available": True,
                    "live_memory_sources_record_count": 4,
                    "live_bounded_source_ref_count": 3,
                    "live_shadow_source_selection_miss_count": 1,
                    "live_shadow_diversification_gap_count": 2,
                    "live_shadow_low_coverage_count": 1,
                    "live_shadow_would_rank_count": 4,
                    "live_route_distribution": {"personal_recall": 4},
                    "live_selected_source_class_distribution": {"event": 3},
                    "live_dropped_source_class_distribution": {"candidate": 2},
                    "live_route_live_applied": False,
                    "live_score_live_applied": False,
                    "live_canonical_state_changed": False,
                    "route_live_applied": False,
                    "score_live_applied": False,
                    "boundary_true_count": 0,
                    "forbidden_field_count": 0,
                    "raw": "should not be retained",
                },
            }
        ],
    }

    compact = monitor.compact_rh31_eval_summary(summary)

    assert compact["retrieval_shadow"] == {
        "run_count": 1,
        "semantic_gap_count": 2,
        "hybrid_would_retrieve_count": 3,
        "rrf_would_rank_count": 2,
        "live_input_available": True,
        "live_memory_sources_record_count": 4,
        "live_bounded_source_ref_count": 3,
        "live_shadow_source_selection_miss_count": 1,
        "live_shadow_diversification_gap_count": 2,
        "live_shadow_low_coverage_count": 1,
        "live_shadow_would_rank_count": 4,
        "live_route_distribution": {"personal_recall": 4},
        "live_selected_source_class_distribution": {"event": 3},
        "live_dropped_source_class_distribution": {"candidate": 2},
        "live_route_live_applied": False,
        "live_score_live_applied": False,
        "live_canonical_state_changed": False,
        "route_live_applied": False,
        "score_live_applied": False,
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
    }
    assert "should not be retained" not in json.dumps(compact)


def test_classify_snapshot_tracks_retrieval_shadow_report_only_fields():
    snapshot = _healthy_snapshot()
    snapshot["rh31_eval"] = {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "pass",
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "adapter_count": 7,
        "failure_count": 0,
        "measurement_signal_count": 0,
        "live_guard_candidate_count": 0,
        "failure_class_distribution": {},
        "retrieval_shadow": {
            "run_count": 1,
            "semantic_gap_count": 1,
            "hybrid_would_retrieve_count": 1,
            "rrf_would_rank_count": 1,
            "live_input_available": True,
            "live_memory_sources_record_count": 4,
            "live_bounded_source_ref_count": 2,
            "live_shadow_source_selection_miss_count": 1,
            "live_shadow_diversification_gap_count": 1,
            "live_shadow_low_coverage_count": 1,
            "live_shadow_would_rank_count": 4,
            "route_live_applied": False,
            "score_live_applied": False,
            "live_route_live_applied": False,
            "live_score_live_applied": False,
            "live_canonical_state_changed": False,
            "boundary_true_count": 0,
            "forbidden_field_count": 0,
        },
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "retrieval_shadow_visible" for item in classification["pass"])
    assert any(item["code"] == "retrieval_shadow_live_memory_sources_visible" for item in classification["pass"])
    assert any(item["code"] == "retrieval_shadow_live_memory_sources_gap_visible" for item in classification["pass"])
    assert any(item["code"] == "retrieval_shadow_semantic_gap_visible" for item in classification["pass"])
    assert any(item["code"] == "retrieval_shadow_report_only" for item in classification["pass"])

    snapshot["rh31_eval"]["retrieval_shadow"]["route_live_applied"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "retrieval_shadow_live_applied" for item in classification["fail"])


def test_classify_snapshot_fails_on_low_clue_ingress_route_mismatch():
    snapshot = _healthy_snapshot()
    snapshot["low_clue_ingress_matrix"] = [
        {
            "id": "deictic_just_now_no_punctuation",
            "route": "foreground_control",
            "headings": ["Current Foreground Task"],
            "expected_route": "ambiguous_recall",
            "expected_heading": "Recall Clarification Guard",
        }
    ]

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "low_clue_ingress_route_mismatch" for item in classification["fail"])
    assert any(item["code"] == "low_clue_ingress_heading_mismatch" for item in classification["fail"])


def test_classify_snapshot_fails_when_low_clue_guard_contract_missing():
    snapshot = _healthy_snapshot()
    snapshot["low_clue_ingress_matrix"] = [
        {
            "id": "deictic_yesterday",
            "route": "ambiguous_recall",
            "headings": ["Recall Clarification Guard"],
            "expected_route": "ambiguous_recall",
            "expected_heading": "Recall Clarification Guard",
            "guard_contract_ok": False,
        }
    ]

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "low_clue_guard_contract_missing" for item in classification["fail"])


def test_classify_snapshot_clean_host_does_not_fail_on_live_host_assumptions():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["gateway"] = {"ActiveState": "inactive", "MainPID": "0"}
    snapshot["low_clue_ingress_matrix"] = [
        {
            "id": "deictic_yesterday",
            "route": "ambiguous_recall",
            "headings": ["Recall Clarification Guard", "Conversation Carryover"],
            "expected_route": "ambiguous_recall",
            "expected_heading": "Recall Clarification Guard",
            "guard_contract_ok": False,
        }
    ]
    snapshot["rh26_apply_probe"] = [
        {
            "id": "cancel_failed_video",
            "chars": 800,
            "headings": ["Current Foreground Task", "Working Memory"],
        }
    ]

    classification = classify_snapshot(snapshot)

    assert classification["status"] != "FAIL"
    assert not any(item["code"] == "gateway_inactive" for item in classification["fail"])
    assert not any(item["code"] == "low_clue_guard_contract_missing" for item in classification["fail"])
    assert not any(item["code"] == "unexpected_rh26_headings" for item in classification["fail"])
    assert any(item["code"] == "clean_host_gateway_inactive_expected" for item in classification["pass"])
    assert any(item["code"] == "clean_host_low_clue_ingress_contract_not_required" for item in classification["pass"])
    assert any(item["code"] == "clean_host_rh26_probe_contract_not_required" for item in classification["pass"])


def test_classify_snapshot_clean_host_accepts_system_gateway_from_hermes_status():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["gateway"] = {"ActiveState": "inactive", "MainPID": "0"}
    snapshot["hermes_status"] = {
        "ok": True,
        "code": 0,
        "gateway_running": True,
        "gateway_manager": "systemd (system)",
        "gateway_pids": "787558",
        "weixin_configured": True,
        "telegram_configured": False,
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert classification["status"] != "FAIL"
    assert not any(item["code"] == "gateway_inactive" for item in classification["fail"])
    assert any(
        item["code"] == "clean_host_gateway_active_via_hermes_status"
        and item["manager"] == "systemd (system)"
        and item["pids"] == "787558"
        for item in classification["pass"]
    )
    assert not any(item["code"] == "clean_host_gateway_inactive_expected" for item in classification["pass"])
    assert "hermes_gateway_running=True" in rendered
    assert "manager=systemd (system)" in rendered


def test_classify_snapshot_fails_when_low_clue_candidate_uses_internal_label():
    snapshot = _healthy_snapshot()
    snapshot["low_clue_recall"] = {
        "schema_version": "memory-os.low_clue_recall.v0",
        "decision": "ask_choice",
        "candidate_count": 4,
        "internal_label_count": 1,
        "llm_judge": {"status": "disabled", "mode": "none"},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "low_clue_internal_candidate_label" for item in classification["fail"])


def test_classify_snapshot_treats_no_selection_judge_as_available():
    snapshot = _healthy_snapshot()
    snapshot["low_clue_recall_config"] = {
        "enabled": True,
        "llm_judge": {"enabled": True, "mode": "report_only"},
    }
    snapshot["low_clue_recall"] = {
        "schema_version": "memory-os.low_clue_recall.v0",
        "decision": "ask_choice",
        "candidate_count": 4,
        "llm_judge": {"status": "no_selection", "mode": "report_only"},
    }

    classification = classify_snapshot(snapshot)
    summary = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "low_clue_llm_judge_available" for item in classification["pass"])
    assert not any(item["code"] == "low_clue_llm_judge_unavailable" for item in classification["warn"])
    assert "'llm_available': True" in summary


def test_classify_snapshot_treats_bounded_vote_judge_as_available():
    snapshot = _healthy_snapshot()
    snapshot["low_clue_recall_config"] = {
        "enabled": True,
        "llm_judge": {"enabled": True, "mode": "bounded_vote"},
    }
    snapshot["low_clue_recall"] = {
        "schema_version": "memory-os.low_clue_recall.v0",
        "decision": "ask_choice",
        "candidate_count": 4,
        "llm_judge": {
            "status": "no_match",
            "mode": "bounded_vote",
            "provider": "hermes_default",
            "resolved_model": "deepseek-v4-flash",
        },
    }

    classification = classify_snapshot(snapshot)
    summary = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "low_clue_llm_judge_available" for item in classification["pass"])
    assert not any(item["code"] == "low_clue_llm_judge_unavailable" for item in classification["warn"])
    assert "'judge_mode': 'bounded_vote'" in summary
    assert "'llm_available': True" in summary


def test_classify_snapshot_fails_when_shell_alias_without_env_breaks():
    snapshot = {
        "gateway": {"ActiveState": "active"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "heartbeat_listed": True,
        "cognitive_loop_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "cognitive_loop_listed": True,
        "cognitive_loop": _healthy_cognitive_loop(),
        "memory_status": {
            "counts": {"crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": []},
        "status_tool_contract": {"status": "ok", "findings": []},
        "shell_alias_no_env": {
            "status_ok": False,
            "doctor_ok": False,
            "status_error": "No module named 'memory_os'",
        },
        "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        "rh26_apply_probe": [],
        "deep_reflection": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
        "compaction": {},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "shell_alias_no_env_failed" for item in classification["fail"])


def test_classify_snapshot_fails_when_shell_modules_alias_without_env_breaks():
    snapshot = _healthy_snapshot()
    snapshot["shell_alias_no_env"]["modules_ok"] = False
    snapshot["shell_alias_no_env"]["modules_error"] = "invalid choice: 'modules'"

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "shell_alias_no_env_failed" for item in classification["fail"])


def test_classify_snapshot_fails_when_metadata_retention_alias_without_env_breaks():
    snapshot = _healthy_snapshot()
    snapshot["shell_alias_no_env"]["metadata_retention_ok"] = False
    snapshot["shell_alias_no_env"]["metadata_retention_error"] = "invalid choice: 'metadata-retention'"

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "shell_alias_no_env_failed" for item in classification["fail"])


def test_classify_snapshot_fails_when_cognitive_loop_service_last_result_failed():
    snapshot = _healthy_snapshot()
    snapshot["cognitive_loop_service"] = {
        "ActiveState": "failed",
        "SubState": "failed",
        "Result": "exit-code",
        "ExecMainStatus": "2",
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "cognitive_loop_service_failed" for item in classification["fail"])


def test_classify_snapshot_passes_memory_sources_stats_and_fails_for_forbidden_fields():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_sources_stats_ok" for item in classification["pass"])

    snapshot["memory_sources"]["forbidden_field_findings"] = [{"path": "$.selected[0].preview"}]
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "memory_sources_forbidden_fields" for item in classification["fail"])


def test_classify_snapshot_warns_when_memory_sources_feedback_surface_has_no_real_feedback():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 0,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["owner_review_surface"]["operations"]["memory_sources_feedback_context"] = {
        "status": "ok",
        "item_count": 1,
        "feedback_action_count": 9,
        "latest_memory_source_id": "msrc_123",
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_sources_feedback_volume_missing" for item in classification["warn"])
    assert classification["status"] == "WARN"


def test_classify_snapshot_passes_when_memory_sources_feedback_volume_exists():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 2,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["owner_review_surface"]["operations"]["memory_sources_feedback_context"] = {
        "status": "ok",
        "item_count": 1,
        "feedback_action_count": 9,
        "latest_memory_source_id": "msrc_123",
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_sources_feedback_volume_present" for item in classification["pass"])
    assert not any(item["code"] == "memory_sources_feedback_volume_missing" for item in classification["warn"])


def test_classify_snapshot_uses_total_memory_sources_feedback_when_window_empty():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 0,
        "total_feedback_count": 2,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["owner_review_surface"]["operations"]["memory_sources_feedback_context"] = {
        "status": "ok",
        "item_count": 1,
        "feedback_action_count": 9,
        "latest_memory_source_id": "msrc_123",
    }

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "memory_sources_feedback_volume_present" and item["feedback_count"] == 2
        for item in classification["pass"]
    )
    assert not any(item["code"] == "memory_sources_feedback_volume_missing" for item in classification["warn"])


def test_enrich_memory_sources_stats_preserves_window_and_total_feedback_counts(monkeypatch):
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)

    def fake_read_jsonl(path):
        if str(path).endswith("memory_sources_feedback.jsonl"):
            return [
                {
                    "schema_version": "memory-os.memory_sources_feedback.v0",
                    "feedback_id": "fb_1",
                    "rating": "useful",
                },
                {
                    "schema_version": "memory-os.memory_sources_feedback.v0",
                    "feedback_id": "fb_2",
                    "rating": "missing_context",
                },
            ]
        return []

    monkeypatch.setitem(namespace, "_read_jsonl", fake_read_jsonl)

    enriched = namespace["enrich_memory_sources_stats"](
        {
            "schema_version": "memory-os.memory_sources_stats.v0",
            "hours": 24,
            "record_count": 0,
            "feedback_count": 0,
            "feedback_rating_distribution": {},
        }
    )

    assert enriched["feedback_count"] == 0
    assert enriched["total_feedback_count"] == 2
    assert enriched["total_feedback_rating_distribution"] == {
        "missing_context": 1,
        "useful": 1,
    }


def test_hermes_status_summary_detects_system_gateway_without_raw_status(monkeypatch):
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)

    def fake_run(cmd, env=None):
        assert env is None
        if cmd == ["hermes", "status"]:
            return {
                "ok": True,
                "code": 0,
                "out": "\n".join(
                    [
                        "Hermes Agent v0.15.1",
                        "◆ Environment",
                        "Model: deepseek-v4-flash",
                        "Provider: DeepSeek",
                        "◆ Messaging Platforms",
                        "Telegram      ✗ not configured",
                        "Weixin        ✓ configured (home: wxid)",
                        "◆ Gateway Service",
                        "Status:       ✓ running",
                        "Manager:      systemd (system)",
                        "PID(s):       787558",
                        "API key: sk-redacted",
                    ]
                ),
            }
        return {"ok": False, "code": 1, "out": ""}

    monkeypatch.setitem(namespace, "run", fake_run)

    summary = namespace["hermes_status_summary"]()

    assert summary == {
        "ok": True,
        "code": 0,
        "gateway_running": True,
        "gateway_manager": "systemd (system)",
        "gateway_pids": "787558",
        "weixin_configured": True,
        "telegram_configured": False,
        "model": "deepseek-v4-flash",
        "provider": "DeepSeek",
    }
    assert "out" not in summary
    assert "API key" not in json.dumps(summary)


def test_classify_snapshot_tracks_memory_sources_policy_apply():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 2,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
        "policy_present": True,
        "policy_version": 1,
        "policy_apply_count": 1,
        "policy_actual_execute_count": 0,
        "policy_raw_body_included_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_sources_policy_present" for item in classification["pass"])
    assert not any(item["code"] == "memory_sources_policy_actual_execute_true" for item in classification["fail"])
    assert not any(item["code"] == "memory_sources_policy_raw_body_included" for item in classification["fail"])


def test_classify_snapshot_fails_when_memory_sources_policy_violates_boundary():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 2,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
        "policy_present": True,
        "policy_version": 1,
        "policy_apply_count": 1,
        "policy_actual_execute_count": 1,
        "policy_raw_body_included_count": 1,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "memory_sources_policy_actual_execute_true" for item in classification["fail"])
    assert any(item["code"] == "memory_sources_policy_raw_body_included" for item in classification["fail"])


def test_classify_snapshot_fails_when_memory_sources_boundary_is_true():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "file_size_bytes": 4096,
        "boundary_true_count": 1,
        "forbidden_field_findings": [],
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "memory_sources_boundary_true" for item in classification["fail"])


def test_classify_snapshot_fails_when_heartbeat_state_is_stale():
    snapshot = _healthy_snapshot()
    snapshot["heartbeat_state"] = {
        "exists": True,
        "last_heartbeat_at": "2026-05-22T00:00:00Z",
        "fresh": False,
        "age_seconds": 9999,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "heartbeat_state_stale" for item in classification["fail"])


def test_classify_snapshot_passes_when_heartbeat_state_is_fresh():
    snapshot = _healthy_snapshot()
    snapshot["heartbeat_state"] = {
        "exists": True,
        "last_heartbeat_at": "2026-05-22T00:00:00Z",
        "fresh": True,
        "age_seconds": 60,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "heartbeat_state_fresh" for item in classification["pass"])


def test_classify_snapshot_fails_when_cognitive_loop_is_not_active_or_violates_boundary():
    snapshot = {
        "gateway": {"ActiveState": "active"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "heartbeat_listed": True,
        "cognitive_loop_timer": {"ActiveState": "inactive", "UnitFileState": "disabled"},
        "cognitive_loop_listed": False,
        "cognitive_loop": {
            "last_status": "error",
            "boundaries": {
                "actual_send": True,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_crystallized_approval": False,
            },
        },
        "memory_status": {
            "counts": {"crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": []},
        "status_tool_contract": {"status": "ok", "findings": []},
        "shell_alias_no_env": {
            "status_ok": True,
            "doctor_ok": True,
            "memory_sources_ok": True,
            "metadata_retention_ok": True,
            "low_clue_recall_ok": True,
            "modules_ok": True,
            "eval_ok": True,
        },
        "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        "rh26_apply_probe": [],
        "deep_reflection": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
        "compaction": {},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "cognitive_loop_timer_inactive" for item in classification["fail"])
    assert any(item["code"] == "cognitive_loop_timer_not_listed" for item in classification["fail"])
    assert any(item["code"] == "cognitive_loop_last_cycle_error" for item in classification["fail"])
    assert any(item["code"] == "cognitive_loop_actual_send_true" for item in classification["fail"])


def test_classify_snapshot_tracks_cognitive_loop_required_step_evidence():
    snapshot = _healthy_snapshot()

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "cognitive_loop_required_steps_visible" for item in classification["pass"])


def test_classify_snapshot_fails_when_cognitive_loop_persisted_report_omits_tail_steps():
    snapshot = _healthy_snapshot()
    snapshot["cognitive_loop_step_evidence"] = {
        "schema_version": "memory-os.cognitive_loop_step_evidence.v0",
        "status": "ok",
        "required_steps": [
            "left_brain_pipeline_check",
            "governance_feedback",
            "deep_reflection",
            "heartbeat_post",
            "doctor_boundary_report",
        ],
        "report_count": 1,
        "latest_step_count": 20,
        "latest_step_names": ["self_evolution"],
        "latest_step_summary": {"omitted_step_count": 5, "tail_step_statuses": {}},
        "missing_required_steps": ["left_brain_pipeline_check", "doctor_boundary_report"],
        "omitted_step_count": 5,
        "tail_step_omitted_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "cognitive_loop_required_step_missing" for item in classification["fail"])
    assert any(item["code"] == "cognitive_loop_tail_step_omitted_by_bounded_report" for item in classification["fail"])


def test_v2_and_clearance_freshness_classification_respects_activation_boundary():
    frozen = monitor.classify_snapshot({
        "monitor_profile": "live",
        "v2_exposure_monitor": {
            "schema_era_health": "PASS",
            "conservation_total_passes": True,
            "downstream_clearance_closure_frozen": True,
            "v2c_unfreeze_ready": False,
            "freeze_reasons": ["production_observation_days:2/30"],
        },
        "clearance_snapshot_freshness": {"status": "stale"},
    })
    assert any(item["code"] == "v2_downstream_clearance_frozen_by_evidence_gates" for item in frozen["pass"])
    assert any(item["code"] == "clearance_snapshot_not_fresh" for item in frozen["warn"])

    activation_ready = monitor.classify_snapshot({
        "monitor_profile": "live",
        "v2_exposure_monitor": {
            "schema_era_health": "PASS",
            "conservation_total_passes": True,
            "v2c_unfreeze_ready": True,
        },
        "clearance_snapshot_freshness": {"status": "stale"},
    })
    assert any(item["code"] == "clearance_snapshot_not_fresh" for item in activation_ready["fail"])

    activation_unavailable = monitor.classify_snapshot({
        "monitor_profile": "live",
        "v2_exposure_monitor": {
            "schema_era_health": "PASS",
            "conservation_total_passes": True,
            "v2c_unfreeze_ready": True,
        },
        "clearance_snapshot_freshness": {"status": "unavailable_remote_projection"},
    })
    assert any(item["code"] == "clearance_snapshot_not_fresh" for item in activation_unavailable["fail"])


def test_v2_exposure_schema_era_fail_is_monitor_fail_not_warn():
    """Fix 2a: a real schema-era attribution/conservation/telemetry break is
    a correctness bug — it must FAIL the monitor, not just warn."""
    classification = monitor.classify_snapshot({
        "monitor_profile": "live",
        "v2_exposure_monitor": {
            "schema_era_health": "FAIL",
            "conservation_total_passes": True,
            "schema_era_conservation_failure_count": 0,
        },
    })
    assert classification["status"] == "FAIL"
    assert any(item["code"] == "v2_exposure_schema_era_unhealthy" for item in classification["fail"])
    assert not any(item["code"] == "v2_exposure_schema_era_unhealthy" for item in classification["warn"])


def test_v2_exposure_conservation_fail_requires_schema_era_failure_count():
    """Fix 2b/2c: all-history conservation drift with zero schema-era
    failures is migration debt (INFO only); a real schema-era failure count
    still FAILs."""
    migration_debt_only = monitor.classify_snapshot({
        "monitor_profile": "live",
        "v2_exposure_monitor": {
            "schema_era_health": "PASS",
            "conservation_total_passes": False,
            "schema_era_conservation_failure_count": 0,
            "all_history_attribution_gap_count": 3,
            "schema_era_attribution_gap_count": 0,
        },
    })
    assert not any(item["code"] == "v2_exposure_conservation_failed" for item in migration_debt_only["fail"])
    assert not any(item["code"] == "v2_exposure_conservation_failed" for item in migration_debt_only["warn"])
    assert any(item["code"] == "v2_exposure_all_history_migration_debt" for item in migration_debt_only["info"])
    migration_info = next(
        item for item in migration_debt_only["info"] if item["code"] == "v2_exposure_all_history_migration_debt"
    )
    assert migration_info["value"]["migration_debt_attribution_gap_count"] == 3

    real_schema_era_failure = monitor.classify_snapshot({
        "monitor_profile": "live",
        "v2_exposure_monitor": {
            "schema_era_health": "PASS",
            "conservation_total_passes": False,
            "schema_era_conservation_failure_count": 2,
            "all_history_attribution_gap_count": 3,
            "schema_era_attribution_gap_count": 0,
        },
    })
    assert real_schema_era_failure["status"] == "FAIL"
    assert any(item["code"] == "v2_exposure_conservation_failed" for item in real_schema_era_failure["fail"])


def test_v2_exposure_and_clearance_collection_failure_escalates_to_fail_in_production():
    """Fix 1/Fix 2: a collection failure (local exception or failed remote
    SSH projection) must never be a silent pass. On a live/production run it
    escalates all the way to FAIL — production hosts must not silently
    tolerate a broken remote SSH/runtime collection. Clean-host tolerates the
    same signal as WARN only (see the clean-host test below)."""
    snapshot = _healthy_snapshot()
    snapshot["v2_exposure_monitor"] = {"schema_era_health": "unavailable", "error_code": "RuntimeError"}
    snapshot["clearance_snapshot_freshness"] = {"status": "unavailable", "error_code": "RuntimeError"}
    classification = monitor.classify_snapshot(snapshot)
    assert any(item["code"] == "v2_exposure_monitor_collection_failed" for item in classification["warn"])
    assert any(
        item["code"] == "clearance_snapshot_freshness_collection_failed" for item in classification["warn"]
    )
    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "v2_exposure_monitor_collection_failed_in_production" for item in classification["fail"]
    )
    assert any(
        item["code"] == "clearance_snapshot_freshness_collection_failed_in_production"
        for item in classification["fail"]
    )

    # A snapshot that simply never set these fields at all (e.g. an older
    # test fixture / schema) must NOT be treated as a collection failure —
    # only an explicit error_code (or the legacy sentinel) triggers the warn.
    silent_baseline = monitor.classify_snapshot({"monitor_profile": "live"})
    assert not any(
        item["code"] in {"v2_exposure_monitor_collection_failed", "clearance_snapshot_freshness_collection_failed"}
        for item in silent_baseline["warn"]
    )


def test_clean_host_classifies_new_v2_and_clearance_collection_failure_codes():
    """Fix 2: the new codes must be gated through CLEAN_HOST_WARN_CLASSIFICATIONS
    as an expected clean-host WARN, instead of falling into
    clean_host_warn_unclassified or escalating to FAIL as production does."""
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["v2_exposure_monitor"] = {"schema_era_health": "unavailable", "error_code": "ConnectionError"}
    snapshot["clearance_snapshot_freshness"] = {"status": "unavailable", "error_code": "ConnectionError"}

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert not any(item["code"] == "clean_host_warn_unclassified" for item in classification["fail"])
    assert any(item["code"] == "v2_exposure_monitor_collection_failed" for item in classification["warn"])
    assert any(
        item["code"] == "clearance_snapshot_freshness_collection_failed" for item in classification["warn"]
    )


def test_render_chinese_summary_omits_private_bodies_and_reports_trends():
    snapshot = _healthy_snapshot()
    snapshot["deltas"] = {
        "counts_delta": {"audit_entries": 10, "events": 2},
        "audit_entries_per_new_event": 5.0,
        "audit_action_delta": {"runtime_heartbeat": 3, "write_working_document": 2},
    }
    snapshot["classification"] = {"status": "WARN", "pass": [{"code": "doctor_ok"}], "warn": [], "fail": []}
    snapshot["audit_actions"] = {
        "total_count": 20,
        "recent_window": 250,
        "recent_action_counts": {"runtime_heartbeat": 8, "write_working_document": 7},
        "action_counts": {"runtime_heartbeat": 10, "write_working_document": 8},
    }
    snapshot["heartbeat_state"] = {"exists": True, "last_heartbeat_at": "2026-05-22T00:00:00Z", "fresh": True}
    snapshot["working_status"] = {
        "documents": {
            "lingering.json": {
                "items": 4,
                "statuses": {"active": 2, "expired": 2},
                "min_weight": 0.1,
                "max_weight": 0.8,
                "avg_weight": 0.45,
            }
        }
    }
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "record_count": 3,
        "file_size_bytes": 2048,
        "feedback_count": 2,
        "feedback_rating_distribution": {"useful": 1, "too_mechanistic": 1},
        "feedback_file_size_bytes": 512,
        "route_distribution": {"ambiguous_recall": 1},
        "selected_source_class_distribution": {"recall_guard": 1},
        "selected_heading_distribution": {"Recent Event Summaries": 2},
        "dropped_heading_distribution": {"Working Memory": 1},
        "forbidden_field_findings": [],
        "boundary_true_count": 0,
    }
    snapshot["hook_markers"] = {"started": 5, "reset": 4, "finalized": 4, "total": 13}
    snapshot["session_activity"] = {"total_session_events": 12}
    snapshot["expression_artifacts"] = {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "wandering_output_count": 10,
        "wandering_would_send_count": 10,
        "wandering_silent_count": 2,
        "speak_gate_evaluated_count": 8,
        "speak_gate_missing_evaluation_count": 2,
        "speak_gate_decision_distribution": {"would_send": 8},
        "speak_gate_would_send_count": 0,
        "speak_gate_blocked_count": 0,
        "speak_gate_actual_send": False,
    }
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 29,
        "pending_session_count": 25,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 25,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
    }

    rendered = render_chinese_summary(snapshot)

    assert "host=debian" in rendered
    assert "context_router=apply" in rendered
    assert "cognitive_loop=ok" in rendered
    assert "shell_alias_no_env" in rendered
    assert "MemorySources" in rendered
    assert "ModuleArtifacts" in rendered
    assert "LegacyRightBrainArchive" in rendered
    assert "feedback_ratings" in rendered
    assert "audit_actions" in rendered
    assert "heartbeat_state" in rendered
    assert "working_status" in rendered
    assert "HookCoverage" in rendered
    assert "ExpressionArtifacts" in rendered
    assert "SessionMirror" in rendered
    assert "selected_headings" in rendered
    assert "audit_entries=+10" in rendered
    assert "events=+2" in rendered
    assert "raw event" not in rendered.lower()
    assert "User:" not in rendered
    assert json.dumps(snapshot, ensure_ascii=False)


def test_remote_module_artifact_summary_guards_retired_legacy_reads():
    script = monitor._remote_probe_script()

    assert "def module_artifact_summary(*, include_retired_legacy=None):" in script
    assert "if include_retired_legacy" in script
    assert 'else []' in script
    for path in (
        "memory-os/system/speak_permission_tickets.jsonl",
        "system-modules/right_brain_expression_adapter/requests.jsonl",
        "system-modules/right_brain_expression_adapter/policy.json",
        "system-modules/right_brain_expression_adapter/policy_applies.jsonl",
        "system-modules/right_brain_expression_adapter/outcomes.jsonl",
    ):
        assert path in script


def test_classify_snapshot_fails_closed_on_retired_archive_integrity_violation():
    snapshot = _healthy_snapshot()
    snapshot["legacy_right_brain_archive"] = {
        "schema_version": "memory-os.legacy_right_brain_retirement_status.v0",
        "lifecycle": "retired",
        "status": "error",
        "violations": ["legacy_live_root_recreated"],
        "raw_body_included": False,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "legacy_right_brain_retirement_integrity_failed"
        for item in classification["fail"]
    )


def test_classify_snapshot_excludes_retired_right_brain_from_active_findings():
    snapshot = _healthy_snapshot()
    snapshot["legacy_right_brain_archive"] = {
        "schema_version": "memory-os.legacy_right_brain_retirement_status.v0",
        "lifecycle": "retired",
        "status": "ok",
        "violations": [],
        "raw_body_included": False,
    }
    snapshot["module_artifacts"] = {
        "schema_version": "memory-os.module_artifact_summary.v0",
        "grounded_expression_judge": {"verdict_count": 1, "verdict_distribution": {}},
        "right_brain_expression_adapter": {"request_count": 1, "outcome_count": 0},
        "expression_feedback": {"linked_outcome_missing_count": 3, "linked_outcome_count": 0},
    }
    snapshot["expression_artifacts"] = {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "latest_expression_draft_missing_count": 0,
        "latest_speak_gate_missing_evaluation_count": 0,
        "speak_gate_actual_send": False,
    }
    snapshot["v7_governance"] = {
        "components": _v7_component_records(exclude={"grounded_expression_judge"})
    }

    classification = classify_snapshot(snapshot)
    codes = {
        str(item.get("code") or "")
        for bucket in ("pass", "warn", "fail")
        for item in classification[bucket]
    }

    assert not any(code.startswith("grounded_expression_") for code in codes)
    assert "right_brain_expression_adapter_visible" not in codes
    assert "right_brain_expression_outcome_missing" not in codes
    assert "right_brain_expression_outcome_recorded" not in codes
    assert "right_brain_expression_feedback_missing_outcome" not in codes
    assert "right_brain_expression_draft_created" not in codes
    assert "right_brain_speak_gate_evaluation_complete" not in codes
    assert "v7_required_components_missing" not in codes


def test_classify_snapshot_warns_when_wandering_outputs_skip_speak_gate():
    snapshot = _healthy_snapshot()
    snapshot["expression_artifacts"] = {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "wandering_would_send_result_count": 3,
        "speak_gate_evaluated_count": 1,
        "speak_gate_missing_evaluation_count": 2,
        "speak_gate_decision_distribution": {"would_send": 1},
        "speak_gate_actual_send": False,
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert classification["status"] == "WARN"
    assert any(item["code"] == "right_brain_speak_gate_missing_evaluation" for item in classification["warn"])
    assert "speak_gate_missing_evaluation_count" in rendered


def test_classify_snapshot_warns_when_expression_draft_is_missing():
    snapshot = _healthy_snapshot()
    snapshot["expression_artifacts"] = {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "expression_draft_missing_count": 2,
        "speak_gate_missing_evaluation_count": 0,
        "speak_gate_actual_send": False,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "right_brain_expression_draft_missing" for item in classification["warn"])


def test_classify_snapshot_uses_latest_expression_cycle_for_current_closure():
    snapshot = _healthy_snapshot()
    snapshot["expression_artifacts"] = {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "expression_draft_missing_count": 23,
        "latest_expression_draft_missing_count": 0,
        "speak_gate_missing_evaluation_count": 15,
        "latest_speak_gate_missing_evaluation_count": 0,
        "speak_gate_actual_send": False,
    }

    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "right_brain_expression_draft_missing" for item in classification["warn"])
    assert not any(item["code"] == "right_brain_speak_gate_missing_evaluation" for item in classification["warn"])
    assert any(item["code"] == "right_brain_expression_draft_created" for item in classification["pass"])
    assert any(item["code"] == "right_brain_speak_gate_evaluation_complete" for item in classification["pass"])


def test_main_can_save_current_snapshot_for_next_delta(tmp_path, monkeypatch, capsys):
    previous = tmp_path / "previous.json"
    output = tmp_path / "current.json"
    previous.write_text(
        json.dumps({"memory_status": {"counts": {"audit_entries": 5, "events": 1}}}),
        encoding="utf-8",
    )

    def fake_collect_snapshot(*, host, hermes_home, python_bin, previous, monitor_profile):
        assert host == "fake-host"
        assert monitor_profile == "clean_host"
        assert previous["memory_status"]["counts"]["audit_entries"] == 5
        return {
            "hostname": "debian",
            "date_utc": "2026-05-22T00:00:00Z",
            "gateway": {"ActiveState": "active", "MainPID": "1"},
            "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
            "heartbeat_listed": True,
            "cognitive_loop_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
            "cognitive_loop_listed": True,
            "cognitive_loop": _healthy_cognitive_loop(),
            "memory_status": {
                "counts": {"audit_entries": 9, "events": 2, "crystallized_records": 0},
                "index_health": {"state": "healthy"},
                "prefetch_mode": "indexed",
            },
            "doctor": {"status": "ok", "findings": []},
            "status_tool_contract": {"status": "ok", "findings": []},
            "shell_alias_no_env": {"status_ok": True, "doctor_ok": True, "memory_sources_ok": True, "metadata_retention_ok": True, "low_clue_recall_ok": True, "modules_ok": True, "eval_ok": True, "review_ok": True, "review_aging_ok": True},
            "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
            "rh26_apply_probe": [],
            "deep_reflection": {},
            "compaction": {},
            "disk_du": "1M",
            "deltas": {"counts_delta": {"audit_entries": 4, "events": 1}, "audit_entries_per_new_event": 4.0},
            "classification": {"status": "PASS", "pass": [], "warn": [], "fail": []},
        }

    monkeypatch.setattr(monitor, "collect_snapshot", fake_collect_snapshot)

    assert main(
        [
            "--host",
            "fake-host",
            "--previous-json",
            str(previous),
            "--snapshot-out",
            str(output),
            "--output",
            "summary",
            "--monitor-profile",
            "clean-host",
        ]
    ) == 0

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["monitor_profile"] == "clean_host"
    assert saved["memory_status"]["counts"]["audit_entries"] == 9
    assert saved["deltas"]["counts_delta"]["audit_entries"] == 4
    assert "audit_entries=+4" in capsys.readouterr().out


def _healthy_cognitive_loop() -> dict:
    return {
        "last_status": "ok",
        "last_cycle_id": "cloop_test",
        "boundaries": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
    }


def _healthy_cognitive_loop_step_evidence() -> dict:
    required_steps = [
        "left_brain_pipeline_check",
        "host_capability_probe",
        "signal_collection",
        "memory_projection",
        "left_brain_advisor",
        "governance_feedback",
        "deep_reflection",
        "heartbeat_post",
        "doctor_boundary_report",
    ]
    return {
        "schema_version": "memory-os.cognitive_loop_step_evidence.v0",
        "status": "ok",
        "required_steps": required_steps,
        "report_count": 3,
        "latest_cycle_id": "cloop_test",
        "latest_status": "ok",
        "latest_step_count": 25,
        "latest_step_names": [
            "prefetch",
            "self_evolution",
            "left_brain_pipeline_check",
            "host_capability_probe",
            "signal_collection",
            "memory_projection",
            "left_brain_advisor",
            "governance_feedback",
            "deep_reflection",
            "heartbeat_post",
            "doctor_boundary_report",
        ],
        "latest_step_summary": {
            "step_count": 25,
            "omitted_step_count": 0,
            "tail_step_statuses": {step: {"status": "ok"} for step in required_steps},
        },
        "missing_required_steps": [],
        "omitted_step_count": 0,
        "tail_step_omitted_count": 0,
    }


def _healthy_snapshot() -> dict:
    return {
        "hostname": "debian",
        "date_utc": "2026-05-22T07:07:41Z",
        "gateway": {"ActiveState": "active", "MainPID": "451894"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "heartbeat_listed": True,
        "cognitive_loop_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "cognitive_loop_listed": True,
        "cognitive_loop": _healthy_cognitive_loop(),
        "cognitive_loop_step_evidence": _healthy_cognitive_loop_step_evidence(),
        "memory_status": {
            "counts": {"audit_entries": 110, "events": 12, "working_items": 7, "crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": [("hindsight_adapter_disabled", "warning")]},
        "status_tool_contract": {"status": "ok", "findings": []},
        "shell_alias_no_env": {
            "status_ok": True,
            "doctor_ok": True,
            "memory_sources_ok": True,
            "metadata_retention_ok": True,
            "low_clue_recall_ok": True,
            "modules_ok": True,
            "eval_ok": True,
            "review_ok": True,
            "review_aging_ok": True,
            "review_channel_ok": True,
            "review_cron_status_ok": True,
            "review_delivery_status_ok": True,
            "review_delivery_gate_ok": True,
            "review_digest_ok": True,
            "review_render_ok": True,
            "review_reply_ok": True,
            "host_probe_ok": True,
            "signal_sources_ok": True,
            "memory_projection_ok": True,
            "left_brain_ok": True,
            "review_surface_ok": True,
        },
        "host_capability_probe": _healthy_host_capability_probe(),
        "signal_source_requirements": _healthy_signal_source_requirements(),
        "memory_projection": _healthy_memory_projection(),
        "memory_projection_retention": _healthy_memory_projection_retention(),
        "left_brain_advisor": _healthy_left_brain_advisor(),
        "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        "rh26_apply_probe": [],
        "deep_reflection": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
        "compaction": {},
        "module_artifacts": _healthy_module_artifacts(),
        "expression_artifacts": _healthy_expression_artifacts(),
        "owner_review": _healthy_owner_review(),
        "owner_review_aging": _healthy_owner_review_aging(),
        "owner_review_channel": _healthy_owner_review_channel(),
        "owner_review_cron_integration": _healthy_owner_cron_integration(),
        "owner_review_delivery_status": _healthy_owner_delivery_status(),
        "owner_review_delivery_gate": _healthy_owner_delivery_gate(),
        "owner_review_digest_preview": _healthy_owner_digest_preview(),
        "owner_review_rendered_digest": _healthy_owner_rendered_digest(),
        "owner_review_agenda_digest": _healthy_owner_agenda_digest(),
        "owner_review_reply_dry_run": _healthy_owner_reply_dry_run(),
        "owner_review_surface": _healthy_owner_review_surface(),
        "owner_review_ingress_guard": _healthy_owner_ingress_guard(),
        "owner_review_proposal_followups": _healthy_owner_proposal_followups(),
        "owner_review_proposal_auto_route": _healthy_owner_proposal_auto_route(),
    }


def _healthy_host_capability_probe() -> dict:
    def capability(key: str, *, status: str = "available") -> dict:
        return {
            "capability_key": key,
            "owner_system": "memory-os" if key in {"deployment_runtime_manifest", "execution_gate"} else "hermes",
            "status": status,
            "probe_method": "fixture",
            "confidence": "high",
            "source_scope_ref": f"{key}:fixture",
            "observed_at": "2026-06-03T01:01:00Z",
            "freshness_status": "present" if status == "available" else status,
            "adapter_required": False,
            "migration_hint": "",
            "raw_body_included": False,
            "secret_values_included": False,
        }

    capabilities = {key: capability(key) for key in monitor.HOST_CAPABILITY_REQUIRED_KEYS}
    capabilities.update(
        {
            "memory_os_core": capability("memory_os_core"),
            "hermes_cron": capability("hermes_cron"),
            "profile": capability("profile"),
            "memory_sources": capability("memory_sources"),
            "session_mirror": capability("session_mirror"),
        }
    )
    capabilities["deployment_runtime_manifest"].update({"deployed_head": "abc123"})
    return {
        "schema_version": "memory-os.host_capability_probe.v2",
        "host_observation_owner": "hermes_memory_os_seam",
        "capabilities": capabilities,
        "capability_contract": {
            "schema_version": "memory-os.host_capability_contract.v0",
            "contract_status": "ok",
            "required_capability_count": len(monitor.HOST_CAPABILITY_REQUIRED_KEYS),
            "capability_count": len(capabilities),
            "missing_required_capability_keys": [],
            "incomplete_capability_count": 0,
            "invalid_status_count": 0,
        },
        "deployment_runtime_manifest": {
            "schema_version": "memory-os.deployment_runtime_manifest.v0",
            "status": "present",
            "deployed_head": "abc123",
            "deployed_at": "2026-06-03T01:00:00Z",
        },
        "raw_body_included": False,
        "secret_values_included": False,
    }


def _healthy_signal_source_requirements() -> dict:
    return {
        "schema_version": "memory-os.signal_source_requirement_report.v0",
        "status": "ok",
        "source_count": 26,
        "required_missing_count": 0,
        "optional_missing_count": 3,
        "sources": [],
    }


def _healthy_memory_projection() -> dict:
    return {
        "schema_version": "memory-os.memory_projection_status.v0",
        "status": "ok",
        "projection_count": 26,
        "latest_created_at": "2026-06-03T01:01:00Z",
        "registered_source_count": 26,
        "unique_source_count": 26,
        "source_key_counts": {
            "execution_gate_envelopes": 1,
            "session_mirror_apply": 1,
            "owner_actions": 1,
            "memory_sources_feedback": 1,
            "hermes_cron_jobs": 1,
            "hindsight_governance_signals": 1,
            "hindsight_provider_stats": 1,
            "mailbox_status": 1,
            "wandering_mind_state": 1,
            "skills_inventory": 1,
            "mcp_server_health": 1,
            "profile_config": 1,
            "kanban_state": 1,
            "tool_registry": 1,
            "runtime_logs": 1,
            "cognitive_loop_status": 1,
            "gateway_runtime_status": 1,
            "proposal_queue_pressure": 1,
            "candidate_queue_pressure": 1,
            "owner_review_pressure": 1,
            "host_capability_contract": 1,
            "hermes_session_index": 1,
            "hindsight_bank_inventory": 1,
            "mailbox_delivery_trace": 1,
            "wandering_mind_cadence": 1,
            "mcp_tool_inventory": 1,
        },
        "source_payload_fields": {
            "hindsight_provider_stats": [
                "operation_count",
                "projection_stale_count",
                "raw_retained_count",
                "recall_count",
                "retain_count",
            ],
            "mailbox_status": [
                "actual_send_count",
                "inbox_count",
                "mailbox_exists",
                "outbox_count",
                "would_send_count",
            ],
            "wandering_mind_state": [
                "actual_send_count",
                "latest_output_at",
                "output_count",
                "state_exists",
                "would_send_count",
            ],
            "mcp_server_health": [
                "config_file_count",
                "configured_server_count",
                "directory_server_count",
                "failed_server_count",
            ],
            "runtime_logs": [
                "error_log_exists",
                "gateway_log_exists",
                "latest_log_age_seconds",
                "log_file_count",
                "rotated_log_count",
            ],
            "cognitive_loop_status": [
                "error_step_count",
                "latest_cycle_id",
                "report_count",
                "required_step_missing_count",
                "step_count",
            ],
            "gateway_runtime_status": [
                "gateway_capability_status",
                "gateway_log_exists",
                "heartbeat_age_seconds",
                "heartbeat_state_exists",
                "processed_event_count",
            ],
            "proposal_queue_pressure": [
                "actual_execute_count",
                "approved_for_proposal_count",
                "awaiting_ops_gate_count",
                "proposal_count",
                "state_candidate_count",
            ],
            "candidate_queue_pressure": [
                "candidate_count",
                "latest_candidate_at",
                "private_candidate_count",
                "public_candidate_count",
                "source_event_ref_count",
            ],
            "owner_review_pressure": [
                "action_required_estimate_count",
                "advisor_finding_count",
                "owner_action_count",
                "pending_candidate_count",
                "pending_proposal_count",
                "review_suggested_estimate_count",
            ],
            "skills_inventory": [
                "latest_skill_age_seconds",
                "skill_count",
                "skill_directory_count",
                "skill_file_count",
                "skill_manifest_count",
            ],
            "profile_config": [
                "channel_config_count",
                "config_exists",
                "config_file_count",
                "hindsight_provider_configured",
                "memory_provider_configured",
                "model_config_present",
                "profile_count",
                "profile_id",
            ],
            "kanban_state": [
                "card_count",
                "column_count",
                "done_card_count",
                "latest_card_age_seconds",
                "open_card_count",
            ],
            "tool_registry": [
                "latest_tool_age_seconds",
                "mcp_tool_count",
                "plugin_count",
                "tool_config_exists",
                "tool_count",
                "tool_manifest_count",
            ],
            "host_capability_contract": [
                "active_runtime_version_present",
                "adapter_missing_count",
                "adapter_required_count",
                "capability_count",
                "contract_status",
                "cron_status",
                "deployed_head_present",
                "deployment_status",
                "execution_gate_status",
                "hermes_version_available",
                "hindsight_status",
                "incomplete_capability_count",
                "invalid_status_count",
                "memory_provider_name",
                "memory_provider_status",
                "migration_needed_count",
                "missing_required_capability_count",
                "owner_channel_status",
                "required_capability_count",
                "structural_write_gate_status",
            ],
            "hermes_session_index": [
                "conversation_file_count",
                "latest_session_age_seconds",
                "platform_count",
                "recent_session_event_count",
                "session_event_count",
                "session_file_count",
            ],
            "hindsight_bank_inventory": [
                "bank_directory_count",
                "bank_file_count",
                "latest_bank_age_seconds",
                "memory_os_config_present",
                "raw_payload_file_count",
                "strategy_file_count",
                "substrate_operation_count",
            ],
            "hindsight_governance_signals": [
                "curation_decision_count",
                "curation_review_suggested_count",
                "demote_decision_count",
                "reject_decision_count",
                "retain_decision_count",
                "suggestion_count",
            ],
            "mailbox_delivery_trace": [
                "cooldown_marker_count",
                "cron_output_file_count",
                "delivery_record_count",
                "failed_delivery_count",
                "latest_delivery_at",
                "latest_failure_at",
                "owner_channel_delivery_count",
            ],
            "wandering_mind_cadence": [
                "cadence_config_present",
                "cooldown_active",
                "generated_count",
                "latest_output_age_seconds",
                "skipped_count",
                "state_exists",
                "would_send_pending_count",
            ],
            "mcp_tool_inventory": [
                "config_file_count",
                "disabled_server_count",
                "http_server_count",
                "latest_config_age_seconds",
                "server_name_count",
                "stdio_server_count",
                "tool_candidate_count",
            ],
        },
        "projected_source_keys": [
            "candidate_queue_pressure",
            "cognitive_loop_status",
            "execution_gate_envelopes",
            "gateway_runtime_status",
            "hermes_cron_jobs",
            "hermes_session_index",
            "host_capability_contract",
            "hindsight_bank_inventory",
            "hindsight_governance_signals",
            "hindsight_provider_stats",
            "kanban_state",
            "mailbox_delivery_trace",
            "mailbox_status",
            "mcp_server_health",
            "mcp_tool_inventory",
            "memory_sources_feedback",
            "owner_actions",
            "owner_review_pressure",
            "profile_config",
            "proposal_queue_pressure",
            "runtime_logs",
            "session_mirror_apply",
            "skills_inventory",
            "tool_registry",
            "wandering_mind_cadence",
            "wandering_mind_state",
        ],
        "registered_source_missing_count": 0,
        "registered_source_missing_keys": [],
        "boundary_true_count": 0,
        "source_scope_missing_count": 0,
        "duplicate_source_hash_count": 0,
        "duplicate_dedup_key_count": 0,
        "raw_body_included": False,
    }


def _healthy_memory_projection_retention() -> dict:
    return {
        "schema_version": "memory-os.memory_projection_retention_status.v0",
        "status": "ok",
        "compaction_count": 1,
        "latest_compaction_id": "mproj_compact_test",
        "latest_dry_run": False,
        "latest_input_count": 30,
        "latest_output_count": 14,
        "latest_archived_count": 16,
        "latest_boundary_true_archived_count": 0,
        "latest_raw_body_included_archived_count": 0,
        "latest_boundary_true_preserved_count": 0,
        "latest_raw_body_included_preserved_count": 0,
        "raw_body_included": False,
        "boundary_true_count": 0,
    }


def _healthy_left_brain_advisor() -> dict:
    return {
        "schema_version": "memory-os.left_brain_advisor_status.v0",
        "status": "ok",
        "report_count": 1,
        "finding_count": 0,
        "owner_visible_finding_count": 0,
        "boundary_true_count": 0,
        "latest_live_closure_eligible": True,
        "latest_structural_write_governance_present": True,
        "latest_structural_write_permit_status": "valid",
        "latest_structural_write_lane_id": "left_brain_advisor_report",
        "latest_structural_write_risk_class": "governance_projection",
        "latest_structural_write_boundary_true": False,
        "raw_body_included": False,
    }


def _healthy_owner_review() -> dict:
    return {
        "schema_version": "memory-os.owner_review_status.v0",
        "review_queue": {"pending_count": 0, "action_required_count": 0, "stale_count": 0},
        "owner_action_count": 0,
        "action_type_counts": {},
        "duplicate_ignored_count": 0,
        "error_count": 0,
        "owner_approved_crystallized_write_count": 0,
        "unapproved_crystallized_write_count": 0,
        "digest_burden": {"owner_active_period": False, "phase": "cold_start"},
        "feedback_backflow": {"feedback_action_count": 0},
    }


def _healthy_owner_review_aging() -> dict:
    return {
        "schema_version": "memory-os.owner_review_aging.v0",
        "enabled": True,
        "action_required_days": 7,
        "fyi_days": 30,
        "raw_action_required_count": 0,
        "effective_action_required_count": 0,
        "aged_to_review_suggested_count": 0,
        "aged_to_fyi_count": 0,
        "unknown_timestamp_count": 0,
        "unknown_timestamp_by_item_type": {},
        "created_at_coverage_ratio": 1.0,
        "created_at_source_distribution": {"producer": 3},
        "created_at_source_by_item_type": {"proposal": {"producer": 3}},
        "true_aged_count": 0,
        "unknown_aged_count": 0,
        "raw_body_included": False,
        "canonical_state_changed": False,
        "owner_action_created": False,
    }


def _healthy_owner_review_channel() -> dict:
    return {
        "schema_version": "memory-os.owner_review_channel.v0",
        "status": "dry_run_only",
        "reason": "cli_preview_fallback",
        "profile": "default",
        "owner_id": "owner",
        "channel": "cli",
        "target_ref": "",
        "direct_message": False,
        "last_owner_activity_at": "",
        "configured_by_owner": False,
        "fallback_used": True,
        "raw_body_included": False,
    }


def _healthy_owner_cron_integration() -> dict:
    return {
        "schema_version": "memory-os.owner_review_cron_integration.v0",
        "status": "ok",
        "enabled": False,
        "mode": "disabled",
        "job_name": "memory-os-owner-review-digest",
        "job_present": False,
        "job_enabled": False,
        "job_id": "",
        "schedule_display": "",
        "helper_script_present": False,
        "helper_script_path": "/root/.hermes/scripts/memory_os_owner_review_digest.py",
        "helper_script_name": "memory_os_owner_review_digest.py",
        "hermes_delivery_configured": False,
        "hermes_delivery_target_class": "missing",
        "rendered_count_24h": 0,
        "skipped_count_24h": 0,
        "error_count_24h": 0,
        "raw_body_included_count": 0,
        "unapproved_send_count": 0,
        "findings": [],
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_digest_preview() -> dict:
    return {
        "schema_version": "memory-os.owner_review_digest_preview.v0",
        "status": "ok",
        "digest_id": "digest_test",
        "owner_id": "owner",
        "will_send": False,
        "delivery_skipped": True,
        "actions_enabled": False,
        "raw_body_included": False,
        "counts": {
            "action_required_total": 0,
            "action_required_shown": 0,
            "review_suggested_total": 0,
            "review_suggested_shown": 0,
            "fyi_total": 1,
            "fyi_shown": 1,
        },
        "overflow": {"action_required": 0, "review_suggested": 0, "fyi": 0},
        "sections": {"action_required": [], "review_suggested": [], "fyi": []},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_rendered_digest() -> dict:
    return {
        "schema_version": "memory-os.owner_review_rendered_digest.v0",
        "status": "ok",
        "will_send": False,
        "raw_body_included": False,
        "text_char_count": 120,
        "text_has_internal_schema": False,
        "text_has_transcript_marker": False,
        "response_header_present": True,
        "overview_present": True,
        "speak_item_count": 0,
        "speak_expression_preview_count": 0,
        "speak_expression_preview_missing_count": 0,
        "section_counts": {"action_required": 0, "review_suggested": 0, "fyi": 1},
        "anchors": {"action_required": [], "review_suggested": [], "fyi": ["F1"]},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_agenda_digest() -> dict:
    return {
        "schema_version": "memory-os.owner_review_rendered_digest.v0",
        "status": "ok",
        "digest_mode": "agenda",
        "raw_body_included": False,
        "text_char_count": 900,
        "text_has_internal_schema": False,
        "text_has_transcript_marker": False,
        "decision_summary_present": True,
        "review_suggested_suppressed": True,
        "fyi_suppressed": True,
        "backlog_totals_suppressed": True,
        "section_counts": {"action_required": 2, "review_suggested": 0, "fyi": 0},
        "counts": {"action_required_total": 2, "action_required_shown": 2},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_reply_dry_run() -> dict:
    return {
        "schema_version": "memory-os.owner_review_reply.v0",
        "status": "ok",
        "dry_run": True,
        "reason": "",
        "owner_utterance_source": "latest_recorded_digest",
        "parsed_action_type": "approve_proposal",
        "parsed_target_type": "proposal",
        "owner_action_status": "ok",
        "owner_action_dry_run": True,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_review_surface() -> dict:
    return {
        "schema_version": "memory-os.owner_review_surface_monitor.v0",
        "status": "ok",
        "operations": {
            "next_page": {
                "status": "ok",
                "item_count": 1,
                "source": "latest_owner_home_digest",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 1,
                "agent_tool_call_count": 1,
            },
            "detail": {
                "status": "ok",
                "item_count": 1,
                "source": "latest_recorded_digest",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 1,
                "agent_tool_call_count": 1,
            },
            "proposal_followups": {
                "status": "ok",
                "item_count": 1,
                "source": "",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 1,
                "agent_tool_call_count": 1,
            },
            "expression_feedback_context": {
                "status": "ok",
                "item_count": 1,
                "feedback_action_count": 6,
                "latest_outcome_id": "rbout_123",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 6,
                "agent_tool_call_count": 6,
            },
            "memory_sources_feedback_context": {
                "status": "ok",
                "item_count": 1,
                "feedback_action_count": 9,
                "latest_memory_source_id": "msrc_123",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 9,
                "agent_tool_call_count": 9,
            },
        },
        "raw_body_included_count": 0,
        "boundary_true_count": 0,
        "forbidden_owner_command_field_count": 0,
        "forbidden_owner_command_fields": [],
        "owner_utterance_example_count": 18,
        "agent_tool_call_count": 18,
    }


def _healthy_owner_ingress_guard() -> dict:
    return {
        "schema_version": "memory-os.owner_review_ingress_guard.v0",
        "probe_status": "ok",
        "capability_observation_status": "observed",
        "legacy_anchor_accepted": False,
        "legacy_reject_anchor_accepted": False,
        "ordinary_anchor_text_accepted": False,
        "token_command_accepted": True,
        "bare_token_command_accepted": True,
        "slash_token_command_accepted": True,
        "feedback_token_command_accepted": True,
        "bare_feedback_token_command_accepted": True,
        "gateway_hook_plugin_present": True,
        "gateway_hook_registered": False,
        "gateway_safety_skip_count": 0,
        "review_reply_tool_available": True,
        "review_reply_tool_status": "ok",
        "review_reply_tool_input_mode": "structured",
        "structured_review_reply_count": 1,
        "reply_fallback_used_count": 0,
        "owner_command_event_count": 0,
        "owner_command_working_count": 0,
        "owner_command_candidate_count": 0,
        "owner_command_promoted_to_candidate": False,
        "owner_review_command_pollution_count": 0,
    }


def test_classify_snapshot_collapses_owner_ingress_bootstrap_failure_to_one_finding():
    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"] = {
        "schema_version": "memory-os.owner_review_ingress_guard.v0",
        "probe_status": "bootstrap_error",
        "bootstrap_stage": "import",
        "bootstrap_reason_code": "module_import_failed",
        "capability_observation_status": "unobserved",
    }

    classification = classify_snapshot(snapshot)
    owner_ingress_fail_codes = {
        item["code"]
        for item in classification["fail"]
        if item["code"].startswith("owner_review_")
    }

    assert owner_ingress_fail_codes == {"owner_review_ingress_probe_bootstrap_error"}


def test_remote_owner_review_ingress_guard_runs_in_clean_child_process():
    repo_root = Path(__file__).resolve().parents[2]
    script = monitor._remote_probe_script(str(repo_root))
    namespace: dict[str, object] = {}
    original_sys_path = list(sys.path)
    try:
        exec(
            script.split(
                '\nstatus = load_json_cmd(["hermes", "memory-os-agent-os", "status"])',
                1,
            )[0],
            namespace,
        )
        report = namespace["owner_review_ingress_guard_summary"]()
    finally:
        sys.path[:] = original_sys_path

    assert report["probe_status"] == "ok"
    assert report["capability_observation_status"] == "observed"
    assert report["review_reply_tool_available"] is True
    assert report["review_reply_tool_status"] == "ok"
    assert report["review_reply_tool_input_mode"] == "structured"
    assert report["structured_review_reply_count"] == 1
    assert report["owner_review_command_pollution_count"] == 0


def _healthy_owner_proposal_followups() -> dict:
    return {
        "schema_version": "memory-os.approved_proposal_followups.v0",
        "status": "ok",
        "approved_proposal_count": 0,
        "pending_followup_count": 0,
        "open_followup_count": 0,
        "shown_count": 0,
        "overflow_count": 0,
        "awaiting_ops_gate_count": 0,
        "ops_gate_reviewed_count": 0,
        "awaiting_explicit_execution_count": 0,
        "execution_ticket_count": 0,
        "actual_execute": False,
        "raw_body_included": False,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "items": [],
    }


def _healthy_owner_proposal_auto_route() -> dict:
    return {
        "schema_version": "memory-os.proposal_followup_auto_route.v0",
        "status": "ok",
        "dry_run": True,
        "lane_id": "proposal_followup_auto_route",
        "lane_mode": "insufficient_volume_running",
        "sample_window_days": 7,
        "minimum_real_samples_for_full_auto": 20,
        "minimum_real_samples_for_limited_auto": 3,
        "observed_owner_agreement_rate_required": 0.9,
        "eligible_sample_count": 0,
        "shadow_decision_count": 0,
        "owner_agreement_count": 0,
        "owner_disagreement_count": 0,
        "owner_agreement_rate": 0.0,
        "wilson_95_lower_bound": 0.0,
        "proposal_kind_coverage": [],
        "full_auto_eligible": False,
        "limited_auto_eligible": False,
        "limited_auto_graduated": False,
        "limited_auto_evidence_source": "insufficient_evidence",
        "limited_auto_first_canary_max_auto_routes_per_day": 1,
        "limited_auto_after_successful_routes": 3,
        "limited_auto_expanded_max_auto_routes_per_day": 3,
        "successful_limited_auto_route_count": 0,
        "current_auto_route_cap_per_day": 1,
        "continue_shadow_comparison": True,
        "auto_demote_on_first_boundary_or_owner_disagreement": True,
        "actual_followup_route_changed": False,
        "eligible_count": 0,
        "selected_count": 0,
        "requested_limit": 10,
        "effective_limit": 10,
        "auto_followup_routed_count": 0,
        "auto_followup_actual_execute_count": 0,
        "auto_followup_policy_write_count": 0,
        "auto_followup_actual_send_count": 0,
        "owner_action_required_count": 0,
        "owner_action_required_boundary_count": 0,
        "auto_followup_boundary_rejected_count": 0,
        "execution_ticket_created": False,
        "actual_execute": False,
        "raw_body_included": False,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_delivery_status() -> dict:
    return {
        "schema_version": "memory-os.owner_review_delivery_status.v0",
        "delivery_count": 0,
        "sent_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "duplicate_ignored_count": 0,
        "owner_approved_digest_delivery_count": 0,
        "unapproved_send_count": 0,
        "raw_body_included_count": 0,
        "last_delivery": {},
    }


def _healthy_owner_delivery_gate() -> dict:
    return {
        "schema_version": "memory-os.owner_review_delivery_gate.v0",
        "profile": "default",
        "owner_id": "owner",
        "status": "disabled",
        "ready_for_delivery": False,
        "delivery_enabled": False,
        "delivery_adapter": "none",
        "blocked_reasons": ["delivery_not_enabled", "delivery_adapter_not_configured"],
        "review_channel": {
            "status": "dry_run_only",
            "reason": "cli_preview_fallback",
            "channel": "cli",
            "target_ref": "",
            "direct_message": False,
            "configured_by_owner": False,
            "fallback_used": True,
            "raw_body_included": False,
        },
        "digest": {
            "schema_version": "memory-os.owner_review_digest_preview.v0",
            "status": "ok",
            "raw_body_included": False,
            "will_send": False,
            "actions_enabled": False,
        },
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_module_artifacts() -> dict:
    return {
        "schema_version": "memory-os.module_artifact_summary.v0",
        "status": "ok",
        "digest": {"daily_artifact_count": 0, "weekly_artifact_count": 0, "household_artifact_exists": False},
        "wandering": {"output_count": 0, "would_send_count": 0},
        "evidence": {"evidence_count": 0, "score_count": 0, "subject_counts": {}},
        "proposal_queue": {
            "candidate_count": 0,
            "state_counts": {},
            "legacy_template_cleanup_apply_count": 0,
            "legacy_template_cleanup_closed_count": 0,
            "legacy_template_cleanup_non_legacy_touched_count": 0,
            "legacy_template_cleanup_actual_execute_count": 0,
            "legacy_template_cleanup_raw_body_included_count": 0,
        },
        "self_evolution": {"report_count": 0, "proposal_count": 0, "last_status": "missing"},
        "governance_feedback": {"emitted_event_count": 0},
        "left_brain_pipeline_check": {
            "status": "ok",
            "finding_count": 0,
            "active_duplicate_group_count": 0,
            "followup_duplicate_group_count": 0,
            "legacy_template_duplicate_group_count": 0,
            "proposal_quality_missing_count": 0,
            "expression_policy_quality_ready_count": 1,
            "expression_policy_quality_blocked_count": 0,
            "expression_policy_unlinked_quality_count": 0,
            "memory_sources_policy_quality_ready_count": 0,
            "memory_sources_policy_quality_blocked_count": 0,
            "memory_sources_policy_unlinked_quality_count": 0,
            "agenda_trace_missing_count": 0,
            "actual_execute": False,
        },
        "deep_reflection": {"report_count": 0, "analysis_artifact_count": 0, "current_injection_exists": False},
        "ops_gate": {
            "report_count": 0,
            "blocked_decision_count": 0,
            "proposal_followup_action_count": 0,
            "duplicate_proposal_followup_count": 0,
            "duplicate_proposal_followup_extra_count": 0,
        },
        "speak_gate": {"would_send_count": 0, "actual_send": False},
        "expression_draft": {
            "draft_count": 0,
            "silent_count": 0,
            "draft_error_count": 0,
            "raw_body_included": False,
        },
        "expression_feedback": {
            "feedback_count": 0,
            "live_policy_changed_count": 0,
            "raw_body_included_count": 0,
            "linked_outcome_count": 0,
            "unlinked_count": 0,
            "linked_outcome_missing_count": 0,
        },
        "right_brain_expression_adapter": {
            "request_count": 0,
            "silent_request_count": 0,
            "latest_channel": None,
            "latest_delivery_mode": None,
            "latest_actual_send": False,
            "raw_body_included_count": 0,
            "outcome_count": 0,
            "latest_outcome_id": "",
            "latest_outcome_request_id": "",
            "latest_outcome_policy_version": None,
            "latest_outcome_silent": None,
            "latest_outcome_preview_chars": None,
            "outcome_actual_send_count": 0,
            "outcome_actual_execute_count": 0,
            "outcome_raw_body_included_count": 0,
            "outcome_internal_marker_count": 0,
            "outcome_feedback_count": 0,
            "latest_outcome_feedback_count": 0,
            "outcome_feedback_missing_count": 0,
        },
        "mailbox": {"mailbox_exists": False, "would_send_count": 0},
    }


def _healthy_expression_artifacts() -> dict:
    return {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "wandering_output_count": 0,
        "wandering_would_send_count": 0,
        "wandering_silent_count": 0,
        "expression_draft_count": 0,
        "expression_draft_created_count": 0,
        "expression_draft_missing_count": 0,
        "latest_expression_draft_missing_count": 0,
        "expression_feedback_count": 0,
        "expression_feedback_linked_outcome_count": 0,
        "expression_feedback_unlinked_count": 0,
        "speak_gate_evaluated_count": 0,
        "speak_gate_missing_evaluation_count": 0,
        "latest_speak_gate_missing_evaluation_count": 0,
        "latest_speak_gate_evaluated_count": 0,
        "speak_gate_decision_distribution": {},
        "speak_gate_would_send_count": 0,
        "speak_gate_blocked_count": 0,
        "speak_gate_actual_send": False,
        "right_brain_adapter_request_count": 0,
        "right_brain_adapter_latest_channel": None,
        "right_brain_adapter_latest_delivery_mode": None,
        "right_brain_adapter_latest_actual_send": False,
        "right_brain_adapter_raw_body_included_count": 0,
        "right_brain_adapter_outcome_count": 0,
        "right_brain_adapter_latest_outcome_silent": None,
        "right_brain_adapter_latest_outcome_policy_version": None,
        "right_brain_adapter_outcome_internal_marker_count": 0,
        "right_brain_adapter_outcome_feedback_count": 0,
        "right_brain_adapter_latest_outcome_feedback_count": 0,
    }


# ── Subprocess env passing tests ──


def test_remote_probe_script_memory_os_cli_uses_hermes_home_not_hardcoded():
    """memory_os_cli() in the generated probe uses _hermes_home, not '/root/.hermes'."""
    script = monitor._remote_probe_script()

    # The old hardcoded pattern must not appear in memory_os_cli
    assert 'env["HERMES_HOME"] = "/root/.hermes"' not in script, (
        "memory_os_cli must use _hermes_home variable, not hardcoded /root/.hermes"
    )

    # The new dynamic pattern must appear
    assert 'env["HERMES_HOME"] = _hermes_home' in script, (
        "memory_os_cli must set HERMES_HOME from _hermes_home"
    )
    assert 'env["PYTHONPATH"] = _hermes_home + "/memory-os/runtime/python:"' in script, (
        "PYTHONPATH must be built from _hermes_home"
    )


def test_remote_probe_script_owner_review_ingress_guard_uses_hermes_home():
    """owner_review_ingress_guard_summary() uses _hermes_home, not hardcoded."""
    script = monitor._remote_probe_script()

    # Count occurrences of the hardcoded path — should be fewer after the fix
    # (some remain in other functions not in scope for this fix)
    hardcoded_count = script.count('env["HERMES_HOME"] = "/root/.hermes"')
    # Before fix: at least 2 (memory_os_cli + owner_review_ingress_guard_summary)
    # After fix: 0 in the fixed functions
    assert hardcoded_count == 0, (
        f"Expected 0 hardcoded HERMES_HOME env assignments in generated script, "
        f"found {hardcoded_count}"
    )


def test_remote_probe_script_cron_adapter_probe_passes_env():
    """_execution_gate_cron_adapter_probe_summary passes env to run()."""
    script = monitor._remote_probe_script()

    # The run() call must include env= parameter with HERMES_HOME
    assert 'env={**os.environ, "HERMES_HOME": hermes_home}' in script, (
        "cron adapter probe subprocess must receive HERMES_HOME in env"
    )


def test_remote_probe_script_hermes_home_variable_still_defined():
    """_hermes_home variable is injected into the generated script (preexisting)."""
    script = monitor._remote_probe_script()
    assert "_hermes_home = " in script, (
        "_hermes_home must be defined in the generated probe script"
    )


# ── Patch A: audit_action_stats + all hardcoded /root/.hermes → _hermes_home ───


def test_remote_probe_script_no_hardcoded_root_hermes_with_custom_home():
    """With custom hermes_home, generated script contains zero /root/.hermes."""
    script = monitor._remote_probe_script("/tmp/custom-hermes")
    assert "/root/.hermes" not in script, (
        "Generated probe script must not contain hardcoded /root/.hermes "
        "when a custom hermes_home is passed"
    )


def test_remote_probe_script_audit_action_stats_receives_hermes_home():
    """audit_action_stats() called with hermes_home=_hermes_home in probe output."""
    script = monitor._remote_probe_script("/tmp/custom-hermes")
    assert "audit_action_stats(hermes_home=_hermes_home)" in script, (
        "audit_action_stats must be called with hermes_home=_hermes_home"
    )
    assert '"audit_actions": audit_action_stats()' not in script, (
        "audit_action_stats must not be called without hermes_home parameter"
    )


def test_remote_probe_script_custom_home_embedded():
    """Custom hermes_home is correctly embedded as _hermes_home variable."""
    script = monitor._remote_probe_script("/tmp/unusual-path")
    assert '_hermes_home = "/tmp/unusual-path"' in script, (
        "Custom hermes_home must be assigned to _hermes_home in generated script"
    )


def test_remote_probe_script_all_key_functions_use_hermes_home_variable():
    """Every path in previously-hardcoded functions references _hermes_home."""
    script = monitor._remote_probe_script("/tmp/custom-hermes")
    checks = [
        'Path(_hermes_home) / "memory-os" / "events"',
        'Path(_hermes_home) / "memory-os" / "runtime" / "heartbeat_state.json"',
        'Path(_hermes_home) / "memory-os" / "working"',
        'os.path.join(_hermes_home, "memory-os/audit")',
        'os.path.join(_hermes_home, "memory-os/system/memory_sources.jsonl")',
        'DeepReflectionModule(""" + json.dumps(_hermes_home) + r""", profile="default")',
        'MemoryOSRoots.from_hermes_home(_hermes_home, profile="default")',
    ]
    for check in checks:
        assert check in script, f"Expected {check!r} in generated probe script"


def test_remote_probe_script_custom_home_compiles():
    """Generated probe script with custom home is syntactically valid Python."""
    script = monitor._remote_probe_script("/tmp/custom-hermes")
    compile(script, "<probe_custom>", "exec")


def test_remote_probe_script_includes_v2_exposure_and_clearance_probe():
    """Fix 1: the generated remote probe script collects V2 exposure stats
    and clearance snapshot freshness using the same SSH remote-execution
    pattern as other remote projections (e.g. seam_host_probe), instead of
    leaving production hosts to silently skip these checks."""
    script = monitor._remote_probe_script()
    assert "def v2_exposure_and_clearance_probe():" in script
    assert '"v2_exposure_and_clearance_probe": v2_exposure_and_clearance_probe_result,' in script
    assert "v2_exposure_and_clearance_probe_result = v2_exposure_and_clearance_probe()" in script
    assert "from plugins.memory.memory_os.exposure_rollup import exposure_monitor_stats" in script
    assert "from plugins.memory.memory_os.clearance_receipts import clearance_snapshot_freshness" in script
    compile(script, "<probe_v2_exposure>", "exec")


def test_remote_probe_v2_exposure_and_clearance_probe_returns_ok_shape():
    """The remote-side function returns the same ok/v2_exposure_monitor/
    clearance_snapshot_freshness shape collect_snapshot() expects, using the
    real exposure_rollup/clearance_receipts modules (no filesystem needed —
    a non-existent hermes_home simply yields empty/near-empty stats)."""
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)

    result = namespace["v2_exposure_and_clearance_probe"]()

    assert result["ok"] is True
    assert result["v2_exposure_monitor"]["schema_version"] == "memory-os.exposure_monitor_stats.v1"
    assert "status" in result["clearance_snapshot_freshness"]


def test_remote_probe_v2_exposure_and_clearance_probe_failure_is_bounded_not_raised(monkeypatch):
    """Fix 1: if the remote host's runtime raises (missing package, corrupt
    local state, etc.), the sub-probe must catch it and report ok=False —
    never let an exception here crash the rest of the remote probe script."""
    from plugins.memory.memory_os import exposure_rollup as _exposure_rollup_module

    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)
    monkeypatch.setattr(
        _exposure_rollup_module,
        "exposure_monitor_stats",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = namespace["v2_exposure_and_clearance_probe"]()

    assert result["ok"] is False
    assert result["error_code"] == "RuntimeError"


def test_remote_probe_script_includes_living_memory_promotion_probe():
    """BB.6-1: the generated remote probe script collects permanent-promotion
    ledger state counts using the same SSH remote-execution pattern as the
    other remote projections, instead of leaving production hosts to always
    report hardcoded-0 recovery/stale-open counts."""
    script = monitor._remote_probe_script()
    assert "def living_memory_promotion_probe():" in script
    assert '"living_memory_promotion_probe": living_memory_promotion_probe_result,' in script
    assert "living_memory_promotion_probe_result = living_memory_promotion_probe()" in script
    assert "from plugins.memory.memory_os.permanent_promotion import read_permanent_promotion_ledger_counts" in script
    compile(script, "<probe_living_memory_promotion>", "exec")


def test_remote_probe_living_memory_promotion_probe_returns_ok_shape():
    """The remote-side function returns the same ok/counts shape
    collect_snapshot() expects, using the real permanent_promotion module —
    a non-existent hermes_home simply yields empty/zeroed ledger counts."""
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)

    result = namespace["living_memory_promotion_probe"]()

    assert result["ok"] is True
    assert result["counts"]["proposal_ledger_counts"] == {
        "open": 0, "deciding": 0, "approved": 0, "rejected": 0, "deferred": 0, "revoked": 0, "expired": 0,
    }
    assert result["counts"]["decision_recovery_failure_count"] == 0


def test_remote_probe_living_memory_promotion_probe_failure_is_bounded_not_raised(monkeypatch):
    """BB.6-1: if the remote host's runtime raises (missing package, corrupt
    local state, etc.), the sub-probe must catch it and report ok=False —
    never let an exception here crash the rest of the remote probe script."""
    from plugins.memory.memory_os import permanent_promotion as _permanent_promotion_module

    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)
    monkeypatch.setattr(
        _permanent_promotion_module,
        "read_permanent_promotion_ledger_counts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = namespace["living_memory_promotion_probe"]()

    assert result["ok"] is False
    assert result["error_code"] == "RuntimeError"


def test_remote_probe_script_default_still_uses_root_hermes():
    """Default parameter (no arg) still embeds /root/.hermes as the home."""
    script = monitor._remote_probe_script()
    assert '_hermes_home = "/root/.hermes"' in script, (
        "Default _remote_probe_script() must embed /root/.hermes as _hermes_home"
    )


def test_counterfactual_audit_action_stats_defaults_to_none():
    """audit_action_stats signature defaults to None, resolves from _hermes_home."""
    script = monitor._remote_probe_script("/tmp/custom-hermes")
    assert "def audit_action_stats(recent_window=250, hermes_home=None):" in script, (
        "audit_action_stats must default to None and resolve from _hermes_home"
    )
    assert "if hermes_home is None:" in script, (
        "audit_action_stats must check for None hermes_home"
    )
    assert "        hermes_home = _hermes_home" in script, (
        "audit_action_stats must fall back to _hermes_home when hermes_home is None"
    )


def test_counterfactual_hook_marker_counts_uses_hermes_home():
    """hook_marker_counts() grep path uses os.path.join with _hermes_home."""
    script = monitor._remote_probe_script("/tmp/custom-hermes")
    assert 'os.path.join(_hermes_home, "memory-os/audit")' in script, (
        "hook_marker_counts must use os.path.join(_hermes_home, ...)"
    )
    assert '"/root/.hermes/memory-os/audit"' not in script, (
        "hook_marker_counts must not hardcode /root/.hermes/memory-os/audit"
    )


# ── Task 8: Living Memory V2-0 permanent-promotion monitor invariants ──────


def _living_memory_promotion_section(**overrides):
    section = {
        "schema_version": "memory-os.living_memory_promotion.v0",
        "permanent_promotion_review_item_count": 0,
        "living_memory_nonpromotion_review_item_count": 0,
        "living_memory_owner_delivery_nonpromotion_count": 0,
        "automatic_permanent_promotion_count": 0,
        "proposal_ledger_counts": {"open": 0, "approved": 0, "rejected": 0, "deferred": 0},
        "token_ledger_counts": {"open": 0, "consumed": 0, "revoked": 0, "expired": 0},
    }
    section.update(overrides)
    return section


def test_monitor_hard_fails_for_automatic_permanent_promotion():
    snapshot = {"living_memory_promotion": _living_memory_promotion_section(
        automatic_permanent_promotion_count=1,
    )}
    classification = classify_snapshot(snapshot)
    codes = {item["code"] for item in classification["fail"]}
    assert "living_memory_automatic_permanent_promotion" in codes


def test_monitor_hard_fails_for_living_memory_nonpromotion_delivery():
    snapshot = {"living_memory_promotion": _living_memory_promotion_section(
        living_memory_owner_delivery_nonpromotion_count=2,
    )}
    classification = classify_snapshot(snapshot)
    codes = {item["code"] for item in classification["fail"]}
    assert "living_memory_owner_delivery_nonpromotion" in codes


def test_monitor_passes_living_memory_hard_zero_and_reports_ledger_state():
    snapshot = {"living_memory_promotion": _living_memory_promotion_section(
        permanent_promotion_review_item_count=3,
        # Query-surface provisional visibility is preserved — NOT a failure.
        living_memory_nonpromotion_review_item_count=5,
        proposal_ledger_counts={"open": 2, "approved": 1, "rejected": 0, "deferred": 0},
        token_ledger_counts={"open": 2, "consumed": 1, "revoked": 0, "expired": 0},
    )}
    classification = classify_snapshot(snapshot)
    fail_codes = {item["code"] for item in classification["fail"]}
    pass_codes = {item["code"] for item in classification["pass"]}
    assert not any(code.startswith("living_memory_") for code in fail_codes)
    assert "living_memory_promotion_hard_zero_ok" in pass_codes
    assert "living_memory_promotion_ledger_state_visible" in pass_codes


def test_monitor_ignores_speak_and_knob_for_living_memory_hard_zero():
    snapshot = {
        "living_memory_promotion": _living_memory_promotion_section(),
        "module_artifacts": {
            "spontaneous_expression": {"status": "ok", "spontaneous_sent": False},
            "knob_ab_eval": {"status": "ok"},
        },
    }
    classification = classify_snapshot(snapshot)
    fail_codes = {item["code"] for item in classification["fail"]}
    assert not any(code.startswith("living_memory_") for code in fail_codes)


def test_summarize_living_memory_promotion_counts_only_registered_target_types():
    delivery = [
        {"target_type": "permanent_memory_promotion"},
        {"target_type": "speak_proposal"},   # not a Living Memory target type
        {"target_type": "knob_tune"},         # not a Living Memory target type
    ]
    review = [
        {"target_type": "provisional_crystallized_record"},  # LM non-promotion
        {"target_type": "permanent_memory_promotion"},        # LM promotion
        {"target_type": "route_score_proposal"},              # not LM
    ]
    section = monitor.summarize_living_memory_promotion(
        delivery_items=delivery, review_items=review,
    )
    # speak/knob/route ignored; only registered LM target types counted.
    assert section["living_memory_owner_delivery_nonpromotion_count"] == 0
    assert section["living_memory_nonpromotion_review_item_count"] == 1
    assert section["permanent_promotion_review_item_count"] == 1


def test_summarize_flags_nonpromotion_living_memory_delivery():
    delivery = [
        {"target_type": "permanent_memory_promotion"},
        {"target_type": "provisional_crystallized_record"},  # must never be delivered
    ]
    section = monitor.summarize_living_memory_promotion(delivery_items=delivery)
    assert section["living_memory_owner_delivery_nonpromotion_count"] == 1


def test_read_permanent_promotion_ledger_counts(tmp_path):
    system = tmp_path / "memory-os" / "system"
    system.mkdir(parents=True)
    proposals = system / "permanent_promotion_proposals.jsonl"
    proposals.write_text(
        json.dumps({"proposal_id": "ppm_a", "status": "open"}) + "\n"
        + json.dumps({"proposal_id": "ppm_a", "status": "approved"}) + "\n"
        + json.dumps({"proposal_id": "ppm_b", "status": "open"}) + "\n",
        encoding="utf-8",
    )
    tokens = system / "owner_action_tokens.jsonl"
    tokens.write_text(
        json.dumps({"token_hash": "h1", "status": "open"}) + "\n"
        + json.dumps({"token_hash": "h1", "status": "consumed"}) + "\n",
        encoding="utf-8",
    )
    counts = monitor.read_permanent_promotion_ledger_counts(tmp_path / "memory-os")
    # ppm_a resolved to approved (terminal), ppm_b stays open.
    assert counts["proposal_ledger_counts"]["approved"] == 1
    assert counts["proposal_ledger_counts"]["open"] == 1
    assert counts["token_ledger_counts"]["consumed"] == 1
    assert counts["token_ledger_counts"]["open"] == 0


def test_permanent_promotion_monitor_projects_delivery_and_recovery_fields(tmp_path):
    system = tmp_path / "memory-os" / "system"
    system.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    proposals = [
        {"proposal_id": "ppm_new", "target_id": "cry_new", "content_hash": "h1", "status": "open", "created_at": (now - timedelta(days=4)).isoformat()},
        {"proposal_id": "ppm_due", "target_id": "cry_due", "content_hash": "h2", "status": "open", "created_at": (now - timedelta(days=8)).isoformat()},
        {"proposal_id": "ppm_deciding", "target_id": "cry_deciding", "content_hash": "h3", "status": "deciding", "created_at": now.isoformat()},
        {"proposal_id": "ppm_deferred", "target_id": "cry_deferred", "content_hash": "h4", "status": "deferred", "deferred_until": (now - timedelta(days=1)).isoformat()},
        {"proposal_id": "ppm_retired", "status": "expired", "reason": "target_retired", "recovered": True},
        {"proposal_id": "ppm_recovered", "status": "approved", "recovered": True},
    ]
    (system / "permanent_promotion_proposals.jsonl").write_text(
        "".join(json.dumps(value) + "\n" for value in proposals),
        encoding="utf-8",
    )
    delivery = {
        "event_id": "proposal_delivery:odig:ppm_due",
        "proposal_id": "ppm_due",
        "status": "acknowledged",
        "delivered_at": (now - timedelta(days=5)).isoformat(),
        "next_reminder_at": (now - timedelta(days=1)).isoformat(),
        "delivery_count": 1,
    }
    (system / "permanent_promotion_deliveries.jsonl").write_text(
        json.dumps(delivery) + "\n" + json.dumps(delivery) + "\n",
        encoding="utf-8",
    )
    (system / "execution_gate_envelopes.jsonl").write_text(
        json.dumps({
            "stage": "completion",
            "lane_id": "permanent_promotion_producer",
            "result_summary": {
                "decision_recovery_attempt_count": 3,
                "decision_recovery_success_count": 2,
                "decision_recovery_failure_count": 1,
            },
        }) + "\n",
        encoding="utf-8",
    )

    counts = monitor.read_permanent_promotion_ledger_counts(tmp_path / "memory-os")

    assert counts["open_proposal_backlog_count"] == 2
    assert counts["never_delivered_open_count"] == 1
    assert counts["due_reminder_count"] == 1
    assert counts["deferred_past_due_count"] == 1
    assert counts["deciding_proposal_count"] == 1
    assert counts["decision_recovery_attempt_count"] == 3
    assert counts["decision_recovery_success_count"] == 2
    assert counts["decision_recovery_failure_count"] == 1
    assert counts["target_retired_close_count"] == 1
    assert counts["approved_reconcile_count"] == 1
    assert counts["duplicate_delivery_suppressed_count"] == 1


def test_monitor_hard_fails_recovery_failure_and_stale_open():
    snapshot = {"living_memory_promotion": _living_memory_promotion_section(
        decision_recovery_failure_count=1,
        stale_open_proposal_count=2,
    )}

    classification = classify_snapshot(snapshot)
    codes = {item["code"] for item in classification["fail"]}

    assert "living_memory_decision_recovery_failure" in codes
    assert "living_memory_stale_open_proposal" in codes


def test_remote_probe_audit_action_stats_imports_read_audit_records():
    """Regression: audit_action_stats must resolve read_audit_records in the
    probe's own scope. The only module import lived inside the nested rh26_probe
    sub-string, so the live monitor raised NameError at snapshot time."""
    import ast

    from scripts.memory_os_3_200_monitor import _remote_probe_script

    tree = ast.parse(_remote_probe_script("/root/.hermes"))
    func = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "audit_action_stats"
        ),
        None,
    )
    assert func is not None, "audit_action_stats missing from probe"
    imports_read_audit = any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "read_audit_records" for alias in node.names)
        for node in ast.walk(func)
    )
    assert imports_read_audit, "audit_action_stats must import read_audit_records in-scope"


def test_remote_probe_bounds_missing_system_commands():
    from scripts.memory_os_3_200_monitor import _remote_probe_script

    script = _remote_probe_script("/tmp/nonexistent-hermes-home")
    assert "except OSError as exc:" in script
    assert '"code": 127' in script


def test_error_record_emitting_components_constant_matches_source():
    """A new `build_error_record(component=...)` emitter must be classified.

    The monitor's headline `suppressed_error_count` can only aggregate a
    component whose status payload actually reaches the snapshot — today
    only four do. Components that emit error records but are not aggregated
    undercount that headline silently, so the full emitter list is recorded
    in ERROR_RECORD_EMITTING_COMPONENTS. This test derives the real list
    from source, so adding an emitter without classifying it fails loudly
    instead of quietly widening the blind spot.
    """
    import re

    repo_root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r'component=\s*"([^"]+)"')
    found: set[str] = set()
    for base in ("plugins", "scripts"):
        for path in (repo_root / base).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            found.update(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))

    missing = found - set(monitor.ERROR_RECORD_EMITTING_COMPONENTS)
    stale = set(monitor.ERROR_RECORD_EMITTING_COMPONENTS) - found
    assert not missing, (
        "new error_record emitter(s) not classified in "
        f"ERROR_RECORD_EMITTING_COMPONENTS: {sorted(missing)}"
    )
    assert not stale, (
        "ERROR_RECORD_EMITTING_COMPONENTS lists component(s) that no longer "
        f"emit error records: {sorted(stale)}"
    )


def test_monitor_error_observability_reports_component_coverage_gap():
    """The undercount must be visible in the monitor output, not silent."""
    report = monitor.monitor_error_observability({})
    coverage = report["component_coverage"]

    assert set(coverage["aggregated_components"]) == {
        "runtime",
        "memory_projection",
        "session_mirror",
        "prefetch",
    }
    # Dotted sub-components roll up to an aggregated parent...
    assert "prefetch._indexed_lines" not in coverage["unaggregated_components"]
    # ...but genuinely uncollected components are reported as such.
    assert "state_source_mirror" in coverage["unaggregated_components"]
    assert "memory_os.permanent_promotion" in coverage["unaggregated_components"]
    assert coverage["unaggregated_component_count"] == len(coverage["unaggregated_components"])
    assert coverage["unaggregated_component_count"] > 0
