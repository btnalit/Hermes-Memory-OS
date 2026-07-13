from __future__ import annotations

import json

from plugins.memory.memory_os.config import load_config


def test_v3_inner_life_defaults_all_active_lanes_closed(tmp_path):
    config = load_config(tmp_path)["v3_inner_life"]

    assert config["seed_evidence"]["enabled"] is False
    assert config["wandering_enabled"] is False
    assert config["expression_enabled"] is False
    assert config["synthesis_admission_enabled"] is False
    assert config["wandering_max_attempts_per_window"] is None
    assert config["journal_ttl_days"] is None


def test_v3_inner_life_rejects_truthy_and_invalid_activation_values(tmp_path):
    path = tmp_path / "memory-os" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "v3_inner_life": {
                    "seed_evidence": {
                        "enabled": "true",
                        "max_edges": -1,
                        "min_coverage_ratio": "1.0",
                        "require_shared_entity": 1,
                    },
                    "wandering_enabled": "true",
                    "expression_enabled": 1,
                    "synthesis_admission_enabled": [True],
                    "journal_ttl_days": "7",
                    "semantic_dedupe_threshold": True,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(tmp_path)["v3_inner_life"]
    assert config["seed_evidence"] == {
        "enabled": False,
        "max_edges": 10000,
        "min_coverage_ratio": 1.0,
        "require_shared_entity": False,
    }
    assert config["wandering_enabled"] is False
    assert config["expression_enabled"] is False
    assert config["synthesis_admission_enabled"] is False
    assert config["journal_ttl_days"] is None
    assert config["semantic_dedupe_threshold"] is None
