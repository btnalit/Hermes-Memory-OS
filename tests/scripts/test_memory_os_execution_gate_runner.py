import json
import shutil
import subprocess
import sys
from pathlib import Path


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
