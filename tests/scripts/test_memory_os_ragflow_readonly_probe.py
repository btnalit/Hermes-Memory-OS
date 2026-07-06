"""Tests for read-only RAGFlow external evidence observation probe."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


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
    assert "read-only" in result.stdout.lower()


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
