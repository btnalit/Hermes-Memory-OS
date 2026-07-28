from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.operational_truth import (
    project_public_counts,
    read_full_monitor_truth,
    read_operational_truth_snapshot,
    runtime_count_observation,
)


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, payload: dict, *, mtime: datetime) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    stamp = mtime.timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_typed_truth_keeps_artifact_freshness_separate_from_monitor_classification(tmp_path):
    artifact = _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor_new.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": (NOW - timedelta(hours=31)).isoformat().replace("+00:00", "Z"),
            "source_head": "abc123",
            "runtime_digest": "sha256:runtime",
            "monitor_version": "memory-os.monitor.v0",
            "producer_receipt": {"receipt_id": "fmpr_1", "monitor_exit_code": 2},
            "classification": {
                "status": "FAIL",
                "fail": [{"code": "new_failure"}],
                "warn": [],
            },
        },
        mtime=NOW,
    )

    truth = read_full_monitor_truth(
        memory_root=tmp_path,
        now=NOW,
        stale_after_seconds=30 * 3600,
    )

    assert truth.artifact.path == artifact
    assert truth.artifact.source_head == "abc123"
    assert truth.freshness.state == "stale"
    assert truth.freshness.observed_from == "generated_at"
    assert truth.classification.status == "FAIL"
    assert truth.classification.fail_codes == ("new_failure",)


def test_reader_never_falls_back_from_latest_stale_failure_to_older_green_artifact(tmp_path):
    artifacts = tmp_path / "system" / "monitor_artifacts"
    _write(
        artifacts / "monitor_20260721T040000000000Z.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": (NOW - timedelta(hours=32)).isoformat().replace("+00:00", "Z"),
            "source_head": "old",
            "runtime_digest": "sha256:old",
            "monitor_version": "memory-os.monitor.v0",
            "producer_receipt": {"receipt_id": "fmpr_old"},
            "classification": {"status": "PASS", "fail": [], "warn": []},
        },
        mtime=NOW - timedelta(minutes=1),
    )
    newest = _write(
        artifacts / "monitor_20260721T050000000000Z.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": (NOW - timedelta(hours=31)).isoformat().replace("+00:00", "Z"),
            "source_head": "new",
            "runtime_digest": "sha256:new",
            "monitor_version": "memory-os.monitor.v0",
            "producer_receipt": {"receipt_id": "fmpr_new"},
            "classification": {"status": "FAIL", "fail": [{"code": "latest_red"}], "warn": []},
        },
        mtime=NOW,
    )

    truth = read_full_monitor_truth(
        memory_root=tmp_path,
        now=NOW,
        stale_after_seconds=30 * 3600,
    )

    assert truth.artifact.path == newest
    assert truth.freshness.state == "stale"
    assert truth.classification.status == "FAIL"
    assert truth.classification.fail_codes == ("latest_red",)


def test_legacy_artifact_uses_results_and_mtime_without_requiring_new_envelope(tmp_path):
    artifact = _write(
        tmp_path / "system" / "monitor_legacy.json",
        {
            "schema_version": "memory-os.monitor.v0",
            "results": {"status": "WARN", "fail": [], "warn": [{"code": "legacy_warn"}]},
        },
        mtime=NOW - timedelta(hours=2),
    )

    truth = read_full_monitor_truth(
        memory_root=tmp_path,
        now=NOW,
        stale_after_seconds=30 * 3600,
    )

    assert truth.artifact.path == artifact
    assert truth.artifact.envelope_complete is False
    assert truth.freshness.state == "fresh"
    assert truth.freshness.observed_from == "artifact_mtime_legacy"
    assert truth.classification.status == "WARN"
    assert truth.classification.warn_codes == ("legacy_warn",)


def test_current_v1_generation_always_outranks_newer_legacy_mtime(tmp_path):
    current = _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor_current_green.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": (NOW - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "source_head": "current",
            "runtime_digest": "sha256:current",
            "monitor_version": "memory-os.monitor.v1",
            "producer_receipt": {"receipt_id": "fmpr_current"},
            "classification": {"status": "PASS", "fail": [], "warn": []},
        },
        mtime=NOW - timedelta(minutes=2),
    )
    _write(
        tmp_path / "system" / "monitor_legacy_red.json",
        {
            "schema_version": "memory-os.monitor.v0",
            "results": {"status": "FAIL", "fail": [{"code": "legacy_red"}], "warn": []},
        },
        mtime=NOW,
    )

    truth = read_full_monitor_truth(memory_root=tmp_path, now=NOW, stale_after_seconds=3600)

    assert truth.artifact.path == current
    assert truth.classification.status == "PASS"


def test_unknown_source_metadata_does_not_claim_complete_envelope(tmp_path):
    _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor_unknown.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": NOW.isoformat().replace("+00:00", "Z"),
            "source_head": "unknown",
            "runtime_digest": "unknown",
            "monitor_version": "memory-os.monitor.v0",
            "producer_receipt": {"receipt_id": "fmpr_unknown"},
            "classification": {"status": "PASS", "fail": [], "warn": []},
        },
        mtime=NOW,
    )

    truth = read_full_monitor_truth(memory_root=tmp_path, now=NOW, stale_after_seconds=3600)

    assert truth.artifact.envelope_complete is False
    assert truth.freshness.state == "invalid_envelope"
    assert truth.freshness.observed_from == "v1_envelope_incomplete"
    assert truth.classification.status == "unknown"


def test_count_observation_reports_source_and_conflict_without_choosing_a_winner():
    observation = runtime_count_observation(
        field="crystallized_records",
        observations={
            "full_monitor.memory_status.counts": 13,
            "dashboard.index.crystallized_records": 31,
        },
    )

    assert observation.observed == {
        "full_monitor.memory_status.counts": 13,
        "dashboard.index.crystallized_records": 31,
    }
    assert observation.conflict is True
    assert observation.value is None


def test_future_generated_at_is_invalid_clock_not_fresh(tmp_path):
    _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor_future.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": (NOW + timedelta(days=365)).isoformat().replace("+00:00", "Z"),
            "source_head": "future",
            "runtime_digest": "sha256:future",
            "monitor_version": "memory-os.monitor.v0",
            "producer_receipt": {"receipt_id": "fmpr_future"},
            "classification": {"status": "PASS", "fail": [], "warn": []},
        },
        mtime=NOW,
    )

    truth = read_full_monitor_truth(memory_root=tmp_path, now=NOW, stale_after_seconds=3600)

    assert truth.freshness.state == "invalid_clock"
    assert truth.freshness.stale is True
    assert truth.freshness.observed_from == "generated_at_future_clock"
    assert truth.classification.status == "unknown"
    assert truth.read_error == "generated_at_future_clock"


def test_shared_operational_truth_snapshot_preserves_all_count_sources(tmp_path):
    _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": NOW.isoformat().replace("+00:00", "Z"),
            "source_head": "abc",
            "runtime_digest": "sha256:abc",
            "monitor_version": "memory-os.monitor.v0",
            "producer_receipt": {"receipt_id": "fmpr_shared"},
            "classification": {"status": "WARN", "fail": [], "warn": [{"code": "count_conflict"}]},
            "memory_status": {"counts": {"crystallized_records": 13}},
        },
        mtime=NOW,
    )

    snapshot = read_operational_truth_snapshot(
        memory_root=tmp_path,
        now=NOW,
        stale_after_seconds=3600,
        runtime_count_observations={
            "crystallized_records": {"status.index.crystallized_records": 31},
        },
    ).to_dict()

    assert snapshot["schema_version"] == "memory-os.operational_truth_snapshot.v1"
    assert snapshot["full_monitor"]["artifact_identity"]["producer_receipt_id"] == "fmpr_shared"
    assert snapshot["full_monitor"]["classification"]["status"] == "WARN"
    assert snapshot["runtime_fields"]["crystallized_records"] == {
        "field": "crystallized_records",
        "observed": {
            "full_monitor.memory_status.counts": 13,
            "status.index.crystallized_records": 31,
        },
        "conflict": True,
        "value": None,
        "invalid_sources": [],
    }


def test_invalid_count_source_is_preserved_and_prevents_winner_selection():
    observation = runtime_count_observation(
        field="crystallized_records",
        observations={
            "full_monitor.memory_status.counts": "invalid",
            "dashboard.index.crystallized_records": 31,
        },
    ).to_dict()

    assert observation["observed"] == {
        "full_monitor.memory_status.counts": "invalid",
        "dashboard.index.crystallized_records": 31,
    }
    assert observation["invalid_sources"] == ["full_monitor.memory_status.counts"]
    assert observation["conflict"] is True
    assert observation["value"] is None


def test_incomplete_v1_envelope_cannot_present_pass_as_fresh(tmp_path):
    _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor_incomplete_v1.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": NOW.isoformat().replace("+00:00", "Z"),
            "source_head": "unknown",
            "runtime_digest": "",
            "monitor_version": "memory-os.monitor.v0",
            "producer_receipt": {"receipt_id": "fmpr_incomplete"},
            "classification": {"status": "PASS", "fail": [], "warn": []},
        },
        mtime=NOW,
    )

    truth = read_full_monitor_truth(memory_root=tmp_path, now=NOW, stale_after_seconds=3600)

    assert truth.artifact.envelope_complete is False
    assert truth.freshness.state == "invalid_envelope"
    assert truth.freshness.stale is True
    assert truth.classification.status == "unknown"
    assert truth.read_error == "v1_envelope_incomplete"


@pytest.mark.parametrize("invalid_value", [13.9, -1, "-1", "13.0", " 13", "+13"])
def test_non_canonical_or_negative_counts_are_invalid_sources(invalid_value):
    observation = runtime_count_observation(
        field="working_items",
        observations={"full_monitor.memory_status.counts": invalid_value, "status.index": 13},
    ).to_dict()

    assert observation["observed"]["full_monitor.memory_status.counts"] == invalid_value
    assert observation["invalid_sources"] == ["full_monitor.memory_status.counts"]
    assert observation["conflict"] is True
    assert observation["value"] is None


def test_unparseable_v1_generated_at_is_invalid_envelope(tmp_path):
    _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor_bad_time.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": "not-a-time",
            "source_head": "abc123",
            "runtime_digest": "sha256:runtime",
            "monitor_version": "memory-os.monitor.v0",
            "producer_receipt": {"receipt_id": "fmpr_bad_time"},
            "classification": {"status": "PASS", "fail": [], "warn": []},
        },
        mtime=NOW,
    )

    truth = read_full_monitor_truth(memory_root=tmp_path, now=NOW, stale_after_seconds=3600)

    assert truth.artifact.envelope_complete is False
    assert truth.freshness.state == "invalid_envelope"
    assert truth.classification.status == "unknown"
    assert truth.read_error == "v1_envelope_incomplete"


@pytest.mark.parametrize(
    "schema",
    ["memory-os.full_monitor_artifact.v1 ", [], 123],
)
def test_non_v1_nonempty_schema_is_invalid_not_legacy(tmp_path, schema):
    _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor_bad_schema.json",
        {
            "schema_version": schema,
            "classification": {"status": "PASS"},
        },
        mtime=NOW,
    )

    truth = read_full_monitor_truth(memory_root=tmp_path, now=NOW, stale_after_seconds=3600)

    assert truth.freshness.state == "invalid_envelope"
    assert truth.classification.status == "unknown"
    assert truth.read_error == "unsupported_schema_version"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("source_head", ["abc"]),
        ("runtime_digest", {"digest": "abc"}),
        ("monitor_version", ["v1"]),
        ("receipt_id", {"id": "receipt"}),
    ],
)
def test_v1_identity_fields_require_nonempty_strings(tmp_path, field, invalid_value):
    envelope = {
        "schema_version": "memory-os.full_monitor_artifact.v1",
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "source_head": "abc123",
        "runtime_digest": "sha256:runtime",
        "monitor_version": "memory-os.monitor.v0",
        "producer_receipt": {"receipt_id": "fmpr_typed"},
        "classification": {"status": "PASS", "fail": [], "warn": []},
    }
    if field == "receipt_id":
        envelope["producer_receipt"]["receipt_id"] = invalid_value
    else:
        envelope[field] = invalid_value
    _write(
        tmp_path / "system" / "monitor_artifacts" / f"monitor_bad_{field}.json",
        envelope,
        mtime=NOW,
    )

    truth = read_full_monitor_truth(memory_root=tmp_path, now=NOW, stale_after_seconds=3600)

    assert truth.freshness.state == "invalid_envelope"
    assert truth.classification.status == "unknown"
    assert truth.read_error == "v1_envelope_incomplete"


def test_public_counts_use_projection_and_never_expose_unilateral_conflict_winner():
    projected = project_public_counts(
        {"events": 12, "working_items": 7, "other": 3},
        {
            "runtime_fields": {
                "events": {"conflict": True, "value": None},
                "working_items": {"conflict": False, "value": 7},
            }
        },
    )

    assert projected == {"events": None, "working_items": 7, "other": 3}


def test_invalid_monitor_envelope_is_preserved_as_invalid_count_source(tmp_path):
    _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor_invalid.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": NOW.isoformat().replace("+00:00", "Z"),
            "source_head": "unknown",
            "runtime_digest": "sha256:runtime",
            "monitor_version": "memory-os.monitor.v1",
            "producer_receipt": {"receipt_id": "fmpr_invalid"},
            "classification": {"status": "PASS"},
            "memory_status": {"counts": {"events": 999}},
        },
        mtime=NOW,
    )

    snapshot = read_operational_truth_snapshot(
        memory_root=tmp_path,
        now=NOW,
        stale_after_seconds=3600,
        runtime_count_observations={"events": {"status.events": 12}},
    ).to_dict()

    observation = snapshot["runtime_fields"]["events"]
    assert observation["conflict"] is True
    assert observation["value"] is None
    assert observation["invalid_sources"] == ["full_monitor.memory_status.counts"]
    assert observation["observed"]["full_monitor.memory_status.counts"] == {
        "invalid_artifact": "v1_envelope_incomplete"
    }


def test_newer_corrupt_primary_generation_cannot_fallback_to_older_green(tmp_path):
    _write(
        tmp_path / "system" / "monitor_artifacts" / "monitor_20260727T010000000000Z.json",
        {
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": "2026-07-27T01:00:00Z",
            "source_head": "head",
            "runtime_digest": "sha256:runtime",
            "monitor_version": "memory-os.monitor.v1",
            "producer_receipt": {"receipt_id": "receipt"},
            "classification": {"status": "PASS"},
        },
        mtime=datetime(2026, 7, 27, 1, tzinfo=timezone.utc),
    )
    corrupt = tmp_path / "system" / "monitor_artifacts" / "monitor_20260727T020000000000Z.json"
    corrupt.write_bytes(b"{not-json")

    truth = read_full_monitor_truth(memory_root=tmp_path, now=NOW, stale_after_seconds=3600)

    assert truth.artifact.path == corrupt
    assert truth.classification.status == "unknown"
    assert truth.freshness.state == "invalid_envelope"
    assert truth.read_error == "JSONDecodeError"
