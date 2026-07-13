from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "memory_os_v3_seed_evidence.py"


def test_v3_seed_evidence_helper_emits_only_aggregate_status(tmp_path):
    config_path = tmp_path / "memory-os" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "v3_inner_life": {
                    "seed_evidence": {
                        "enabled": True,
                        "max_edges": 100,
                        "min_coverage_ratio": 1.0,
                        "require_shared_entity": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    ledger = tmp_path / "memory-os" / "system" / "memory_sources.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(
            {
                "record_id": "msrc_private_ref",
                "created_at": "2026-07-12T01:00:00Z",
                "traffic_class": "production",
                "natural_production": True,
                "selected": [
                    {
                        "source_class": "crystallized",
                        "source_ids": ["crystallized:private_a", "crystallized:private_b"],
                    }
                ],
                "dropped": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--hermes-home",
            str(tmp_path),
            "--target-date",
            "2026-07-12",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["natural_date"] == "2026-07-12"
    assert "crystallized:private_a" not in completed.stdout
    assert "crystallized:private_b" not in completed.stdout
    assert "edges" not in payload
