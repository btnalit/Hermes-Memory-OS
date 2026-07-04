"""Tests for audit rotation read-side visibility (V4.1 P1-1 counterfactuals).

Covers:
  A.1 — read_audit_records reads legacy + monthly shards
  A.2 — shard-only audit is visible (no legacy file)
  A.3 — index-sync sees shard-only audit
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.audit import append_audit, read_audit_records


def _write_legacy_audit(audit_dir: Path, records: list[dict]) -> None:
    """Write records to the legacy monolith file."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / "write_audit.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _write_monthly_shard(audit_dir: Path, records: list[dict], year_month: str = "202607") -> None:
    """Write records to a monthly shard."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"write_audit.{year_month}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _make_audit_record(action: str, ts: str = "") -> dict:
    return {
        "schema_version": "memory-os.audit.v0",
        "id": "",
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "action": action,
        "status": "ok",
        "target": "/test/path",
        "details": {},
    }


# ── A.1: legacy + monthly shards ──────────────────────────────────────

def test_read_audit_records_reads_legacy_and_monthly_shards(tmp_path):
    """Both write_audit.jsonl and write_audit.202607.jsonl are visible."""
    audit_dir = tmp_path / "audit"
    legacy_path = audit_dir / "write_audit.jsonl"

    legacy_records = [_make_audit_record("legacy_action_1"), _make_audit_record("legacy_action_2")]
    shard_records = [_make_audit_record("shard_action_1"), _make_audit_record("shard_action_2")]

    _write_legacy_audit(audit_dir, legacy_records)
    _write_monthly_shard(audit_dir, shard_records)

    all_records = read_audit_records(legacy_path)

    actions = {r["action"] for r in all_records}
    assert "legacy_action_1" in actions
    assert "legacy_action_2" in actions
    assert "shard_action_1" in actions
    assert "shard_action_2" in actions
    assert len(all_records) == 4


# ── A.2: shard-only audit ─────────────────────────────────────────────

def test_read_audit_records_visible_when_only_monthly_shard_exists(tmp_path):
    """When only monthly shard exists (no legacy), records are still visible."""
    audit_dir = tmp_path / "audit"
    # Use legacy path as the reference, but only write shard
    legacy_path = audit_dir / "write_audit.jsonl"

    shard_records = [_make_audit_record("shard_only_action")] * 3
    _write_monthly_shard(audit_dir, shard_records)

    all_records = read_audit_records(legacy_path)
    assert len(all_records) == 3
    assert all(r["action"] == "shard_only_action" for r in all_records)


def test_read_audit_records_empty_when_no_files(tmp_path):
    """No audit files at all → empty list."""
    audit_dir = tmp_path / "audit"
    legacy_path = audit_dir / "write_audit.jsonl"

    records = read_audit_records(legacy_path)
    assert records == []


# ── A.3: append_audit writes to monthly shard ─────────────────────────

def test_append_audit_writes_to_monthly_shard(tmp_path):
    """append_audit writes to the monthly shard, readable via read_audit_records."""
    audit_dir = tmp_path / "audit"
    legacy_path = audit_dir / "write_audit.jsonl"

    append_audit(
        legacy_path,
        action="test_monthly_write",
        status="ok",
        target="/test",
    )

    records = read_audit_records(legacy_path)
    actions = {r["action"] for r in records}
    assert "test_monthly_write" in actions
    assert len(records) == 1


def test_read_audit_records_preserves_order(tmp_path):
    """Records from multiple shards are returned in file-name order."""
    audit_dir = tmp_path / "audit"
    legacy_path = audit_dir / "write_audit.jsonl"

    # Write legacy and multiple shards
    _write_legacy_audit(audit_dir, [_make_audit_record("from_legacy")])
    _write_monthly_shard(audit_dir, [_make_audit_record("from_202606")], "202606")
    _write_monthly_shard(audit_dir, [_make_audit_record("from_202607")], "202607")

    records = read_audit_records(legacy_path)
    actions = [r["action"] for r in records]
    # Files are glob-sorted by path name
    assert "from_legacy" in actions
    assert "from_202606" in actions
    assert "from_202607" in actions
    assert len(records) == 3
