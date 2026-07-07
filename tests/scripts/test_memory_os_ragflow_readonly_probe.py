"""Tests for read-only RAGFlow external evidence observation probe."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "memory_os_ragflow_readonly_probe.py"


def _seed_canonical(home: Path) -> str:
    crystallized = home / "memory-os" / "crystallized"
    crystallized.mkdir(parents=True)
    target = crystallized / "owner_approved.md"
    target.write_text("stable owner-approved memory\n", encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def test_ragflow_readonly_probe_help_works():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "external evidence" in result.stdout.lower() or "ragflow" in result.stdout.lower()


def test_ragflow_readonly_probe_disabled_does_not_mutate_canonical(tmp_path):
    home = tmp_path / ".hermes"
    before_hash = _seed_canonical(home)
    (home / "memory-os" / "system").mkdir(parents=True)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--hermes-home",
            str(home),
            "--query",
            "Memory-OS RAGFlow boundary smoke",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "memory-os.ragflow_readonly_probe.v0"
    assert payload["mode"] == "read_only_external_evidence"
    assert payload["provider"] == "ragflow"
    assert payload["memory_write_allowed"] is False
    assert payload["crystallization_allowed"] is False
    assert payload["canonical_unchanged"] is True
    assert payload["status"] in {"disabled", "ok"}

    after_hash = hashlib.sha256(
        (home / "memory-os" / "crystallized" / "owner_approved.md").read_bytes()
    ).hexdigest()
    assert after_hash == before_hash
    assert not (home / "memory-os" / "events").exists()


def test_ragflow_readonly_probe_masks_sensitive_config(tmp_path):
    home = tmp_path / ".hermes"
    _seed_canonical(home)
    system = home / "memory-os" / "system"
    system.mkdir(parents=True)
    (system / "seam_config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "ragflow": {
                        "enabled": False,
                        "base_url": "http://127.0.0.1:9380",
                        "api_key_file": "/secret/ragflow-api-key",
                        "dataset_id": "dataset-123",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--hermes-home", str(home), "--output", "json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["config"]["api_key_file"] == "[REDACTED]"
    assert "secret" not in result.stdout


def test_ragflow_readonly_probe_supports_ephemeral_cli_overrides(tmp_path):
    home = tmp_path / ".hermes"
    _seed_canonical(home)
    key_file = tmp_path / "ragflow-api-key"
    key_file.write_text("test-key", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--hermes-home", str(home),
            "--enable-for-probe",
            "--base-url", "http://127.0.0.1:1",
            "--dataset-id", "dataset-123",
            "--api-key-file", str(key_file),
            "--timeout", "0.01",
            "--output", "json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["config"]["enabled"] is True
    assert payload["config"]["dataset_id"] == "dataset-123"
    assert payload["config"]["api_key_file"] == "[REDACTED]"
    assert payload["status"] in {"ok", "no_results_or_unreachable"}
    assert not (home / "memory-os" / "system" / "seam_config.json").exists()


# ── Phase 4: Tainted intake bridge tests ──────────────────────────────


def test_ragflow_probe_intake_dry_run_without_execute(tmp_path):
    """--intake without --execute reports dry_run, no canonical mutations."""
    home = tmp_path / ".hermes"
    before_hash = _seed_canonical(home)
    (home / "memory-os" / "system").mkdir(parents=True)

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--hermes-home", str(home),
            "--query", "test intake",
            "--intake", "0",
            "--output", "json",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "intake" in payload, f"intake section missing: {list(payload.keys())}"
    assert payload["intake"]["executed"] is False
    assert not (home / "memory-os" / "events").exists(), "no events without --execute"


def test_ragflow_probe_parse_intake_indices():
    """_parse_intake_indices parses comma-separated indices correctly."""
    from scripts.memory_os_ragflow_readonly_probe import _parse_intake_indices

    assert _parse_intake_indices("0,2") == [0, 2]
    assert _parse_intake_indices("0") == [0]
    assert _parse_intake_indices("") == []
    assert _parse_intake_indices("  1 , 3 ") == [1, 3]
    assert _parse_intake_indices("invalid") == []


def test_ragflow_probe_intake_with_empty_ref_rejected(tmp_path):
    """Chunk with empty external_ref is rejected (constraint 2: safe default)."""
    from scripts.memory_os_ragflow_readonly_probe import _intake_chunk

    home = tmp_path / ".hermes"
    (home / "memory-os" / "system").mkdir(parents=True)

    result = _intake_chunk(home, {
        "content_preview": "some content",
        "document_id": "",
        "chunk_id": "",
    })
    assert result["intake"] in {"skipped", "rejected"}
    assert "error" in result


def test_ragflow_probe_intake_with_valid_ref_succeeds(tmp_path):
    """Valid chunk with external_ref lands as tainted event."""
    from scripts.memory_os_ragflow_readonly_probe import _intake_chunk

    home = tmp_path / ".hermes"
    (home / "memory-os").mkdir(parents=True)

    result = _intake_chunk(home, {
        "content_preview": "RAGFlow evidence: configure index sync properly",
        "document_id": "doc-001",
        "chunk_id": "chunk-a",
        "dataset_id": "dataset-123",
    })
    assert result["intake"] == "ok", f"Expected ok, got: {result}"
    assert "event_id" in result
    # Verify event was actually written
    events_dir = home / "memory-os" / "events"
    assert events_dir.exists(), f"events dir should exist at {events_dir}"


def test_ragflow_probe_intake_creates_tainted_event(tmp_path):
    """Intake produces events with source_class=external_evidence."""
    from scripts.memory_os_ragflow_readonly_probe import _intake_chunk

    home = tmp_path / ".hermes"
    (home / "memory-os").mkdir(parents=True)

    result = _intake_chunk(home, {
        "content_preview": "External knowledge: vector retrieval tuning",
        "document_id": "doc-002",
        "chunk_id": "chunk-b",
    })
    assert result["intake"] == "ok"

    # Read the event to verify tainting (events stored in MM/DD.jsonl)
    events_dir = home / "memory-os" / "events"
    found = False
    for event_file in events_dir.rglob("*.jsonl"):
        for line in event_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("id") == result["event_id"]:
                assert event["kind"] == "external_evidence_intake"
                safe_ref = event.get("safe_ref", {})
                assert safe_ref.get("source_class") == "external_evidence"
                assert "external-evidence" in event.get("tags", [])
                found = True
    assert found, f"Event {result['event_id']} not found in event store"
