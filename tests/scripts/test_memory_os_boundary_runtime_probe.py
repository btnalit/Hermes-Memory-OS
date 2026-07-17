import json
import subprocess
import sys
from pathlib import Path

import scripts.memory_os_boundary_runtime_probe as boundary_probe


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


def test_boundary_runtime_probe_does_not_treat_boundary_observed_as_boundary_true(tmp_path):
    hermes_home = tmp_path / "home"
    _jsonl(
        hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl",
        [
            {
                "stage": "permit",
                "execution_gate_envelope_id": "xgate_observed",
                "permit_decision": "allowed",
                "boundary_true": False,
                "boundary": {"actual_send": False},
            },
            {
                "stage": "completion",
                "execution_gate_envelope_id": "xgate_observed",
                "execution_status": "ok",
                "postcheck_boundary_true": False,
                "postcheck": {
                    "postcheck_boundary_observed": True,
                    "boundary": {
                        "actual_send": False,
                        "actual_execute": False,
                        "actual_unapproved_crystallized_approval": False,
                    },
                },
            },
        ],
    )

    result = _run_probe(hermes_home)
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["status"] == "ok"
    assert report["execution_gate"]["completion_postcheck_boundary_true_count"] == 0


def _legacy_provisional_postcheck(*, permanent: bool) -> dict:
    """The exact pre-P1-1-fix shape `provisional_write_postcheck()` used to
    return: a bare `actual_crystallized_approval: True` / `actual_provisional_
    crystallized_write: True` alongside provisional evidence. Records already
    on disk in this shape must not start FAILing once the probe's
    `actual_crystallized_approval` handling is fixed.
    """
    return {
        "crystallized_write": "provisional_success",
        "provisional_crystallized_write_count": 1,
        "actual_crystallized_approval": True,
        "actual_provisional_crystallized_write": True,
        "actual_permanent_crystallized_approval": permanent,
        "actual_unapproved_permanent_crystallized_write": False,
        "actual_unapproved_crystallized_approval": False,
    }


def test_boundary_runtime_probe_exempts_legacy_provisional_write_postcheck(tmp_path):
    """P1-1: a historical completion record in the old provisional-write
    postcheck shape (bare actual_crystallized_approval=True + provisional
    evidence, actual_permanent_crystallized_approval=False) is exempt --
    it is not a real boundary violation, just a legitimate bounded,
    reversible provisional write recorded before the postcheck shape fix.

    Counterfactual: reverting the `_provisional_write_exempt` exemption in
    `_postcheck_boundary_true` (i.e. treating `actual_crystallized_approval`
    like every other key in `_BOUNDARY_KEYS`) flips this record back to a
    violation and the probe FAILs.
    """
    hermes_home = tmp_path / "home"
    _jsonl(
        hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl",
        [
            {
                "stage": "permit",
                "execution_gate_envelope_id": "xgate_legacy_prov",
                "lane_id": "resolver_auto_approve",
                "permit_decision": "allowed",
                "boundary_true": False,
                "boundary": {"actual_send": False},
            },
            {
                "stage": "completion",
                "execution_gate_envelope_id": "xgate_legacy_prov",
                "lane_id": "resolver_auto_approve",
                "execution_status": "completed",
                "postcheck_boundary_true": True,
                "postcheck": _legacy_provisional_postcheck(permanent=False),
            },
        ],
    )

    result = _run_probe(hermes_home)
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["status"] == "ok"
    assert report["execution_gate"]["completion_postcheck_boundary_true_count"] == 0
    assert report["permanent_boundary_counters"]["execution_gate_completion_boundary_true_count"] == 0
    assert report["findings"] == []


def test_boundary_runtime_probe_still_fails_legacy_shape_with_permanent_approval(tmp_path):
    """The same legacy postcheck shape, but with
    actual_permanent_crystallized_approval=True, must remain a violation --
    the provisional exemption never covers a recorded permanent approval.
    """
    hermes_home = tmp_path / "home"
    _jsonl(
        hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl",
        [
            {
                "stage": "permit",
                "execution_gate_envelope_id": "xgate_legacy_perm",
                "lane_id": "resolver_auto_approve",
                "permit_decision": "allowed",
                "boundary_true": False,
                "boundary": {"actual_send": False},
            },
            {
                "stage": "completion",
                "execution_gate_envelope_id": "xgate_legacy_perm",
                "lane_id": "resolver_auto_approve",
                "execution_status": "completed",
                "postcheck_boundary_true": True,
                "postcheck": _legacy_provisional_postcheck(permanent=True),
            },
        ],
    )

    result = _run_probe(hermes_home)
    report = json.loads(result.stdout)

    assert result.returncode == 1
    assert report["status"] == "fail"
    assert report["execution_gate"]["completion_postcheck_boundary_true_count"] == 1
    assert {
        "severity": "fail",
        "code": "boundary_counter_nonzero:execution_gate_completion_boundary_true_count",
        "value": 1,
    } in report["findings"]


def test_boundary_runtime_probe_builds_host_remote_command():
    command = boundary_probe.remote_probe_command(
        host="hermes-feiniu",
        remote_repo_root="/opt/Hermes-Memory-OS",
        hermes_home="/root/.hermes",
        profile="sannai",
        python_bin="python3",
    )

    assert command[0] == "ssh"
    assert command[1] == "hermes-feiniu"
    assert "python3 /opt/Hermes-Memory-OS/scripts/memory_os_boundary_runtime_probe.py" in command[2]
    assert "--hermes-home /root/.hermes" in command[2]
    assert "--profile sannai" in command[2]
    assert "--output json" in command[2]
