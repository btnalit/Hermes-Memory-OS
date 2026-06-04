import json
import subprocess
import sys
from pathlib import Path


def _jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def _script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "memory_os_boundary_runtime_probe.py"


def _run_probe(hermes_home: Path):
    return subprocess.run(
        [
            sys.executable,
            str(_script()),
            "--hermes-home",
            str(hermes_home),
            "--output",
            "json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )


def test_boundary_runtime_probe_passes_with_zero_boundaries_and_gate_records(tmp_path):
    hermes_home = tmp_path / "home"
    _jsonl(
        hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl",
        [
            {
                "stage": "permit",
                "execution_gate_envelope_id": "xgate_ok",
                "lane_id": "memory_projection_collect",
                "risk_class": "governance_projection",
                "permit_decision": "allowed",
                "boundary_true": False,
                "boundary": {"actual_send": False},
            },
            {
                "stage": "completion",
                "execution_gate_envelope_id": "xgate_ok",
                "lane_id": "memory_projection_collect",
                "execution_status": "ok",
                "postcheck_boundary_true": False,
                "postcheck": {"actual_send": False},
            },
        ],
    )
    _jsonl(
        hermes_home / "memory-os" / "system" / "owner_actions.jsonl",
        [
            {
                "owner_effect": {"owner_approved_crystallized_write": True},
                "boundary": {
                    "actual_unapproved_crystallized_approval": False,
                    "actual_send": False,
                    "actual_identity_write": False,
                },
            }
        ],
    )
    _jsonl(
        hermes_home / "memory-os" / "system" / "hindsight_curation_decisions.jsonl",
        [
            {
                "actual_hindsight_write": False,
                "actual_hindsight_delete": False,
                "actual_hindsight_demote": False,
                "actual_route_score_write": False,
                "actual_send": False,
                "boundary": {"actual_route_score_write": False},
            }
        ],
    )

    result = _run_probe(hermes_home)
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["schema_version"] == "memory-os.boundary_runtime_probe.v0"
    assert report["status"] == "ok"
    assert report["permanent_boundary_counters"]["owner_approved_crystallized_write_count"] == 1
    assert report["permanent_boundary_counters"]["unapproved_or_automatic_crystallized_write_count"] == 0
    assert report["findings"] == []


def test_boundary_runtime_probe_fails_when_permanent_boundary_counter_is_nonzero(tmp_path):
    hermes_home = tmp_path / "home"
    _jsonl(
        hermes_home / "memory-os" / "system" / "owner_actions.jsonl",
        [
            {
                "boundary": {
                    "actual_unapproved_crystallized_approval": True,
                    "actual_send": False,
                }
            }
        ],
    )
    _jsonl(
        hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl",
        [
            {
                "stage": "permit",
                "execution_gate_envelope_id": "xgate_ok",
                "permit_decision": "allowed",
                "boundary_true": False,
                "boundary": {"actual_send": False},
            },
            {
                "stage": "completion",
                "execution_gate_envelope_id": "xgate_ok",
                "execution_status": "ok",
                "postcheck_boundary_true": False,
                "postcheck": {"actual_send": False},
            },
        ],
    )

    result = _run_probe(hermes_home)
    report = json.loads(result.stdout)

    assert result.returncode == 1
    assert report["status"] == "fail"
    assert {
        "severity": "fail",
        "code": "boundary_counter_nonzero:unapproved_or_automatic_crystallized_write_count",
        "value": 1,
    } in report["findings"]


def test_boundary_runtime_probe_warns_when_gate_records_are_missing(tmp_path):
    result = _run_probe(tmp_path / "empty-home")
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["status"] == "warning"
    assert {item["code"] for item in report["findings"]} == {
        "execution_gate_completion_records_missing",
        "execution_gate_permit_records_missing",
    }
