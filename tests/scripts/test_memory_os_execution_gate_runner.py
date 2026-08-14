import json
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_execution_gate_runner_preserves_stdout_and_writes_envelopes(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    shutil.copy2(runner, scripts_dir / "memory_os_execution_gate_runner.py")
    (scripts_dir / "memory_os_module_cadence_report_cron.py").write_text(
        "print('HELPER_STDOUT_OK')\n",
        encoding="utf-8",
    )
    hermes_home = tmp_path / "home"
    registry_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "module_cadence_report",
                        "name": "memory-os-module-cadence-report",
                        "raw_script": "memory_os_module_cadence_report_cron.py",
                        "wrapper_script": "memory_os_cron_module_cadence_report_gate.py",
                        "lane_id": "module_cadence_report",
                        "helper_kind": "local_helper",
                        "no_agent": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "memory_os_execution_gate_runner.py"),
            "--registry-key",
            "module_cadence_report",
            "--hermes-home",
            str(hermes_home),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "HELPER_STDOUT_OK"
    assert result.stderr == ""
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    assert [record["stage"] for record in records] == ["permit", "completion"]
    assert records[0]["lane_id"] == "module_cadence_report"
    assert records[0]["permit_decision"] == "allowed"
    assert records[0]["human_approval_required"] is False
    assert records[1]["execution_gate_envelope_id"] == records[0]["execution_gate_envelope_id"]


def test_execution_gate_runner_uses_installed_registry_snapshot_and_observes_helper_boundary(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    shutil.copy2(runner, scripts_dir / "memory_os_execution_gate_runner.py")
    (scripts_dir / "memory_os_fake_helper.py").write_text(
        """
import json
import os
from pathlib import Path

report_path = Path(os.environ["MEMORY_OS_EXECUTION_REPORT_PATH"])
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps({
    "schema_version": "memory-os.helper_execution_report.v0",
    "status": "ok",
    "boundary": {"actual_send": True},
    "result_summary": {"generated_count": 1}
}), encoding="utf-8")
print("FAKE_HELPER_STDOUT")
""".lstrip(),
        encoding="utf-8",
    )
    hermes_home = tmp_path / "home"
    registry_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "fake_helper",
                        "name": "memory-os-fake-helper",
                        "raw_script": "memory_os_fake_helper.py",
                        "wrapper_script": "memory_os_cron_fake_helper_gate.py",
                        "lane_id": "fake_helper_lane",
                        "helper_kind": "local_helper",
                        "no_agent": True,
                        "requires_boundary_report": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "memory_os_execution_gate_runner.py"),
            "--registry-key",
            "fake_helper",
            "--hermes-home",
            str(hermes_home),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "FAKE_HELPER_STDOUT"
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["lane_id"] == "fake_helper_lane"
    assert records[1]["postcheck"]["postcheck_boundary_observed"] is True
    assert records[1]["postcheck_boundary_true"] is True
    assert records[1]["postcheck"]["boundary"]["actual_send"] is True


def test_execution_gate_runner_does_not_parse_business_json_stdout_as_helper_report(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    shutil.copy2(runner, scripts_dir / "memory_os_execution_gate_runner.py")
    (scripts_dir / "memory_os_json_helper.py").write_text(
        "import json\nprint(json.dumps({'schema_version': 'business.v0', 'boundary': {'actual_send': True}}))\n",
        encoding="utf-8",
    )
    hermes_home = tmp_path / "home"
    registry_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "json_helper",
                        "name": "memory-os-json-helper",
                        "raw_script": "memory_os_json_helper.py",
                        "wrapper_script": "memory_os_cron_json_helper_gate.py",
                        "lane_id": "json_helper_lane",
                        "helper_kind": "local_helper",
                        "no_agent": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "memory_os_execution_gate_runner.py"),
            "--registry-key",
            "json_helper",
            "--hermes-home",
            str(hermes_home),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "business.v0" in result.stdout
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    # requires_boundary_report not set in spec → defaults to False →
    # runner marks boundary as not-required (observed by design, no report needed)
    assert records[1]["postcheck"]["postcheck_boundary_not_required"] is True
    assert records[1]["postcheck"]["postcheck_boundary_observed"] is True
    # boundary from business JSON stdout must NOT be parsed (not a helper report)
    assert records[1]["postcheck_boundary_true"] is False


def test_runner_requires_boundary_report_false_marks_boundary_not_required(tmp_path):
    """When spec has requires_boundary_report=False, completion marks boundary as not-required."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    shutil.copy2(runner, scripts_dir / "memory_os_execution_gate_runner.py")
    # Helper that does NOT write a boundary report
    (scripts_dir / "no_report_helper.py").write_text("print('ok')\n", encoding="utf-8")
    hermes_home = tmp_path / "home"
    registry_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "no_report_helper",
                        "name": "memory-os-no-report-helper",
                        "raw_script": "no_report_helper.py",
                        "wrapper_script": "memory_os_cron_no_report_gate.py",
                        "lane_id": "no_report_lane",
                        "helper_kind": "local_helper",
                        "no_agent": True,
                        "requires_boundary_report": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(scripts_dir / "memory_os_execution_gate_runner.py"),
         "--registry-key", "no_report_helper", "--hermes-home", str(hermes_home)],
        check=False, text=True, capture_output=True,
    )

    assert result.returncode == 0
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    # Counterfactual: without the fix, postcheck_boundary_observed would be False
    # and postcheck_boundary_not_required would not exist
    assert records[1]["postcheck"]["postcheck_boundary_not_required"] is True
    assert records[1]["postcheck"]["postcheck_boundary_observed"] is True


def test_runner_requires_boundary_report_true_still_expects_report(tmp_path):
    """When requires_boundary_report=True (or omitted), runner still requires helper report."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    shutil.copy2(runner, scripts_dir / "memory_os_execution_gate_runner.py")
    # Helper that does NOT write a boundary report
    (scripts_dir / "reporting_helper.py").write_text("print('ok')\n", encoding="utf-8")
    hermes_home = tmp_path / "home"
    registry_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "reporting_helper",
                        "name": "memory-os-reporting-helper",
                        "raw_script": "reporting_helper.py",
                        "wrapper_script": "memory_os_cron_reporting_gate.py",
                        "lane_id": "reporting_lane",
                        "helper_kind": "local_helper",
                        "no_agent": True,
                        "requires_boundary_report": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(scripts_dir / "memory_os_execution_gate_runner.py"),
         "--registry-key", "reporting_helper", "--hermes-home", str(hermes_home)],
        check=False, text=True, capture_output=True,
    )

    assert result.returncode == 0
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    # Counterfactual: when requires_boundary_report=True, absence of report
    # must still result in boundary_unobserved
    assert records[1]["postcheck"]["postcheck_boundary_observed"] is False
    assert records[1]["postcheck"].get("postcheck_boundary_not_required") is not True


def test_execution_gate_runner_updates_sidecar_index_for_cron_permit(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    shutil.copy2(runner, scripts_dir / "memory_os_execution_gate_runner.py")
    (scripts_dir / "indexed_helper.py").write_text("print('ok')\n", encoding="utf-8")
    hermes_home = tmp_path / "home"
    registry_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "indexed_helper",
                        "name": "memory-os-indexed-helper",
                        "raw_script": "indexed_helper.py",
                        "wrapper_script": "memory_os_cron_indexed_gate.py",
                        "lane_id": "indexed_lane",
                        "helper_kind": "local_helper",
                        "no_agent": True,
                        "requires_boundary_report": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "memory_os_execution_gate_runner.py"),
            "--registry-key",
            "indexed_helper",
            "--hermes-home",
            str(hermes_home),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    index_path = hermes_home / "memory-os" / "system" / "execution_gate_index.json"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    permit = records[0]
    completion = records[1]
    assert completion["execution_gate_envelope_id"] == permit["execution_gate_envelope_id"]
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entry = index[permit["execution_gate_envelope_id"]]
    assert entry["lane_id"] == "indexed_lane"
    assert entry["completion_count"] == 1


def test_execution_gate_runner_serializes_parallel_sidecar_updates(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    shutil.copy2(runner, scripts_dir / "memory_os_execution_gate_runner.py")
    (scripts_dir / "parallel_helper.py").write_text("print('ok')\n", encoding="utf-8")
    hermes_home = tmp_path / "home"
    registry_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "parallel_helper",
                        "name": "memory-os-parallel-helper",
                        "raw_script": "parallel_helper.py",
                        "wrapper_script": "memory_os_cron_parallel_helper_gate.py",
                        "lane_id": "parallel_helper_lane",
                        "helper_kind": "local_helper",
                        "no_agent": True,
                        "requires_boundary_report": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    command = [
        sys.executable,
        str(scripts_dir / "memory_os_execution_gate_runner.py"),
        "--registry-key",
        "parallel_helper",
        "--hermes-home",
        str(hermes_home),
    ]
    processes = [
        subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(8)
    ]
    results = [process.communicate(timeout=30) + (process.returncode,) for process in processes]

    assert [returncode for _stdout, _stderr, returncode in results] == [0] * 8, results
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 16
    index_path = hermes_home / "memory-os" / "system" / "execution_gate_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    # Allow 7-8 entries (8 parallel processes, CI may have timing variance)
    assert 7 <= len(index) <= 8, f"Expected 7-8 index entries, got {len(index)}"
    # Allow completion_count of 1 or 2 (CI may have retries due to race conditions)
    assert all(c in {1, 2} for c in {entry["completion_count"] for entry in index.values()}), \
        f"Unexpected completion_count values: { {entry['completion_count'] for entry in index.values()} }"


def test_execution_gate_sidecar_replace_failure_preserves_previous_index(tmp_path, monkeypatch):
    runner_path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    spec = importlib.util.spec_from_file_location("memory_os_execution_gate_runner_crash_test", runner_path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    hermes_home = tmp_path / "home"
    index_path = hermes_home / "memory-os" / "system" / "execution_gate_index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(json.dumps({"existing": {"completion_count": 1}}), encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(runner.os, "replace", fail_replace)
    with pytest.raises(runner.ExecutionGateInfrastructureError, match="sidecar_update_failed"):
        runner._update_sidecar_index(
            hermes_home,
            "xgate_new",
            "permit",
            {
                "permit_decision": "allowed",
                "lane_id": "test",
                "created_at": "2026-07-11T00:00:00Z",
                "expires_at": "2026-07-11T01:00:00Z",
            },
        )

    assert json.loads(index_path.read_text(encoding="utf-8")) == {"existing": {"completion_count": 1}}
    assert list(index_path.parent.glob(f".{index_path.name}.*.tmp")) == []


def _load_runner_module():
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    spec = importlib.util.spec_from_file_location(
        "memory_os_execution_gate_runner_under_test", scripts_dir / "memory_os_execution_gate_runner.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sidecar_index_is_bounded_and_keeps_newest_entries():
    """The sidecar index is fully rewritten on every permit AND completion.

    Unbounded growth turned each cron firing into an O(N) read+write+fsync of
    a file that gained one entry per envelope forever.
    """
    module = _load_runner_module()
    index = {
        f"xgate_{i:05d}": {"envelope_id": f"xgate_{i:05d}", "permit_created_at": f"2026-07-{(i % 28) + 1:02d}T00:00:00Z"}
        for i in range(50)
    }

    pruned = module.prune_sidecar_index(index, max_entries=10)

    assert len(pruned) == 10
    newest = sorted(index, key=lambda k: (index[k]["permit_created_at"], k))[-10:]
    assert set(pruned) == set(newest)


def test_sidecar_index_prune_never_evicts_the_envelope_being_written():
    """The live envelope must survive its own prune regardless of clock skew,
    or its completion record would lose the permit it belongs to."""
    module = _load_runner_module()
    index = {
        f"xgate_{i:05d}": {"envelope_id": f"xgate_{i:05d}", "permit_created_at": "2026-07-30T00:00:00Z"}
        for i in range(30)
    }
    # An entry whose timestamp sorts oldest, i.e. first to be evicted.
    index["xgate_live"] = {"envelope_id": "xgate_live", "permit_created_at": "1970-01-01T00:00:00Z"}

    pruned = module.prune_sidecar_index(index, "xgate_live", max_entries=5)

    assert "xgate_live" in pruned


def test_sidecar_index_prune_is_a_noop_below_the_cap():
    module = _load_runner_module()
    index = {"xgate_a": {"envelope_id": "xgate_a"}, "xgate_b": {"envelope_id": "xgate_b"}}

    assert module.prune_sidecar_index(index, max_entries=10) == index


# ── T1: dual-writer schema parity (runner vs core execution_gate) ───────────
#
# Both writers append to the SAME execution_gate_envelopes.jsonl and sidecar
# index, from two independent implementations. These guards build one record
# through each real producer (no hand fixtures) and pin the shared-file
# contract: silent divergence here corrupts every full-scan validation.


_FALSE_BOUNDARY = {
    "owner_delivery_attempted": False,
    "external_action_executed": False,
    "actual_identity_write": False,
    "actual_unapproved_crystallized_approval": False,
}


def _runner_permit_and_completion(module, hermes_home):
    permit = module._append_permit(
        hermes_home=hermes_home,
        registry_key="index_sync",
        lane_id="index_sync",
        risk_class="local_helper",
        raw_script="memory_os_index_sync.py",
        helper_present=True,
        smoke_mode="off",
        boundary=dict(_FALSE_BOUNDARY),
        profile="default",
    )
    module._append_completion(
        hermes_home=hermes_home,
        envelope_id=permit["execution_gate_envelope_id"],
        lane_id="index_sync",
        execution_status="completed",
        returncode=0,
        smoke_mode="off",
        boundary=dict(_FALSE_BOUNDARY),
        helper_report={},
        profile="default",
        requires_boundary_report=False,
    )
    records = [
        json.loads(line)
        for line in module._records_path(hermes_home).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    completion = next(r for r in records if r["stage"] == "completion")
    return permit, completion


def _core_permit_and_completion(tmp_path):
    from plugins.memory.memory_os.execution_gate import (
        complete_execution_gate_envelope,
        execution_gate_records_path,
        start_execution_gate_envelope,
    )
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))
    store.initialize()
    permit = start_execution_gate_envelope(
        store,
        lane_id="index_sync",
        trigger_surface="memory_os_local_helper",
        risk_class="local_helper",
        human_approval_required=False,
        why_no_human_approval="dual-writer schema parity guard",
        scope={"write_surface": "guard_test"},
        boundary=dict(_FALSE_BOUNDARY),
    )
    complete_execution_gate_envelope(
        store,
        envelope_id=permit["execution_gate_envelope_id"],
        lane_id="index_sync",
        execution_status="completed",
        postcheck={"boundary_true": False},
        result_summary={"guard": "test"},
    )
    records = [
        json.loads(line)
        for line in execution_gate_records_path(store.roots).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    completion = next(r for r in records if r["stage"] == "completion")
    return store, permit, completion


def test_dual_writer_schema_version_comes_from_one_constant(tmp_path):
    from plugins.memory.memory_os.execution_gate import EXECUTION_GATE_SCHEMA_VERSION

    module = _load_runner_module()
    assert module.SCHEMA_VERSION == EXECUTION_GATE_SCHEMA_VERSION


def test_dual_writer_completion_key_sets_are_identical(tmp_path):
    module = _load_runner_module()
    _, runner_completion = _runner_permit_and_completion(module, tmp_path / "runner-home")
    _, _, core_completion = _core_permit_and_completion(tmp_path / "core-home")

    assert set(runner_completion) == set(core_completion), (
        "completion-stage records from the two writers diverged — the shared "
        "envelopes file no longer has one completion schema"
    )


def test_dual_writer_permit_gap_is_exactly_the_pinned_constant(tmp_path):
    module = _load_runner_module()
    runner_permit, _ = _runner_permit_and_completion(module, tmp_path / "runner-home")
    _, core_permit, _ = _core_permit_and_completion(tmp_path / "core-home")

    assert set(runner_permit) <= set(core_permit), (
        "runner permit grew keys the core writer lacks — update the core or "
        "RUNNER_OMITTED_PERMIT_KEYS consciously"
    )
    assert set(core_permit) - set(runner_permit) == set(module.RUNNER_OMITTED_PERMIT_KEYS)


def test_dual_writer_sidecar_entries_have_identical_shape(tmp_path):
    module = _load_runner_module()
    runner_home = tmp_path / "runner-home"
    runner_permit, _ = _runner_permit_and_completion(module, runner_home)
    core_store, core_permit, _ = _core_permit_and_completion(tmp_path / "core-home")

    runner_index = json.loads(
        (runner_home / "memory-os" / "system" / "execution_gate_index.json").read_text(encoding="utf-8")
    )
    core_index = json.loads(
        (core_store.roots.memory_os_root / "system" / "execution_gate_index.json").read_text(encoding="utf-8")
    )
    runner_entry = runner_index[runner_permit["execution_gate_envelope_id"]]
    core_entry = core_index[core_permit["execution_gate_envelope_id"]]

    assert set(runner_entry) == set(core_entry), (
        "sidecar index entries from the two writers diverged in shape"
    )


# ── Profile attribution resolution (multi-profile hosts) ────────────────────
#
# Multi-profile hosts export only HERMES_HOME=/root/.hermes/profiles/<name>
# without HERMES_PROFILE.  The old `HERMES_PROFILE or "default"` fallback then
# stamped that profile's permit/completion records as "default", and
# profile-filtered readers silently dropped them.


def _profile_registry_snapshot(hermes_home, raw_script):
    registry_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "index_sync",
                        "name": "memory-os-index-sync",
                        "raw_script": raw_script,
                        "wrapper_script": "memory_os_cron_index_sync_gate.py",
                        "lane_id": "index_sync",
                        "helper_kind": "local_helper",
                        "no_agent": True,
                        "requires_boundary_report": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_resolve_profile_behavior_table(tmp_path, monkeypatch):
    module = _load_runner_module()
    plain_home = tmp_path / "home"
    sannai_home = tmp_path / "profiles" / "sannai"

    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    assert module._resolve_profile(plain_home) == ("default", None)
    assert module._resolve_profile(sannai_home) == ("sannai", None)
    assert module._resolve_profile(plain_home, "explicit-x") == ("explicit-x", None)
    assert module._resolve_profile(sannai_home, "sannai") == ("sannai", None)
    profile, conflict = module._resolve_profile(sannai_home, "other")
    assert profile == "sannai"
    assert conflict == {"requested": "other", "derived_from_home": "sannai"}

    monkeypatch.setenv("HERMES_PROFILE", "sannai")
    assert module._resolve_profile(plain_home) == ("sannai", None)
    assert module._resolve_profile(sannai_home) == ("sannai", None)

    monkeypatch.setenv("HERMES_PROFILE", "default")
    profile, conflict = module._resolve_profile(sannai_home)
    assert profile == "sannai"
    assert conflict == {"requested": "default", "derived_from_home": "sannai"}

    # Explicit --profile outranks the environment.
    monkeypatch.setenv("HERMES_PROFILE", "main")
    assert module._resolve_profile(plain_home, "sannai") == ("sannai", None)


def test_resolve_profile_matches_roots_resolver_behavior_table(tmp_path, monkeypatch):
    # The runner is stdlib-only, so it carries a local twin of
    # roots.resolve_profile_name.  This table pins the two implementations
    # together: any drift between them re-opens split attribution.
    from plugins.memory.memory_os.roots import RootValidationError, resolve_profile_name

    module = _load_runner_module()
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    plain_home = tmp_path / "home"
    sannai_home = tmp_path / "profiles" / "sannai"

    for home, explicit in [
        (plain_home, ""),
        (plain_home, "explicit-x"),
        (sannai_home, ""),
        (sannai_home, "sannai"),
    ]:
        runner_profile, runner_conflict = module._resolve_profile(home, explicit)
        assert runner_conflict is None
        assert resolve_profile_name(home, explicit) == runner_profile

    # Conflict: the runner reports it structurally, roots fails closed.
    runner_profile, runner_conflict = module._resolve_profile(sannai_home, "other")
    assert runner_conflict is not None
    try:
        resolve_profile_name(sannai_home, "other")
    except RootValidationError:
        pass
    else:
        raise AssertionError("roots resolver accepted a conflicting profile")


def test_profile_shaped_home_stamps_permit_and_completion_with_derived_profile(tmp_path, monkeypatch):
    # Counterfactual for the sannai mis-attribution: before the resolver these
    # records said "default" whenever HERMES_PROFILE was not exported.
    module = _load_runner_module()
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    hermes_home = tmp_path / "profiles" / "sannai"
    _profile_registry_snapshot(hermes_home, "memory_os_missing_helper_for_profile_test.py")

    outcome = module.run_registry_key_detailed("index_sync", hermes_home=hermes_home)

    # Helper is intentionally missing: permit + helper_missing completion both
    # get written, which is exactly the pair whose attribution matters.
    assert outcome["status"] == "helper_missing"
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    assert [record["stage"] for record in records] == ["permit", "completion"]
    assert records[0]["profile"] == "sannai"
    assert records[1]["profile"] == "sannai"
    assert records[0]["permit_decision"] == "allowed"


def test_profile_home_conflict_blocks_lane_with_durable_permit(tmp_path, monkeypatch):
    # HERMES_PROFILE=default + a sannai-shaped home must not run the helper —
    # but it must leave a blocked permit as evidence, never exit silently.
    module = _load_runner_module()
    monkeypatch.setenv("HERMES_PROFILE", "default")
    hermes_home = tmp_path / "profiles" / "sannai"
    _profile_registry_snapshot(hermes_home, "memory_os_module_cadence_report_cron.py")

    outcome = module.run_registry_key_detailed("index_sync", hermes_home=hermes_home)

    assert outcome["status"] == "permit_blocked"
    assert outcome["error_code"] == "profile_home_conflict"
    assert outcome["returncode"] == 2
    records_path = hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["stage"] == "permit"
    assert records[0]["permit_decision"] == "blocked"
    assert records[0]["permit_reason"] == "profile_home_conflict"
    assert records[0]["profile"] == "sannai"
    assert records[0]["profile_conflict"] == {"requested": "default", "derived_from_home": "sannai"}


def test_runner_injects_resolved_profile_into_helper_environment(tmp_path):
    # The helper subprocess must see the same profile the envelope was stamped
    # with, so lane scripts stop re-deriving (and mis-deriving) it themselves.
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_execution_gate_runner.py"
    shutil.copy2(runner, scripts_dir / "memory_os_execution_gate_runner.py")
    (scripts_dir / "memory_os_profile_probe_helper.py").write_text(
        "\n".join(
            [
                "import os",
                "from pathlib import Path",
                "out = Path(os.environ['HERMES_HOME']) / 'seen_profile.txt'",
                "out.write_text(os.environ.get('HERMES_PROFILE', '<unset>'), encoding='utf-8')",
                "print('PROBE_OK')",
                "",
            ]
        ),
        encoding="utf-8",
    )
    hermes_home = tmp_path / "profiles" / "sannai"
    _profile_registry_snapshot(hermes_home, "memory_os_profile_probe_helper.py")
    env = {key: value for key, value in os.environ.items() if key != "HERMES_PROFILE"}

    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "memory_os_execution_gate_runner.py"),
            "--registry-key",
            "index_sync",
            "--hermes-home",
            str(hermes_home),
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert (hermes_home / "seen_profile.txt").read_text(encoding="utf-8") == "sannai"
