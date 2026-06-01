from plugins.memory.memory_os.config import load_config, save_config


def test_hindsight_substrate_defaults_to_disabled(tmp_path):
    config = load_config(tmp_path)

    hindsight = config["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is False
    assert hindsight["adoption_source"] == "none"
    assert hindsight["retain_enabled"] is False
    assert hindsight["recall_mode"] == "off"
    assert hindsight["reflect_enabled"] is False
    assert hindsight["reject_raw_turns"] is True
    assert hindsight["allowed_retain_sources"] == ["crystallized", "owner_approved"]
    assert hindsight["projection_coherence_window_seconds"] == 300
    assert hindsight["legacy_auto_retain_observed_disabled"] is False
    assert hindsight["provider_bank_id"] == ""
    assert hindsight["bank_selection_reason"] == "not_selected"
    assert hindsight["configured_provider_bank_ids"] == []
    assert hindsight["non_provider_configured_bank_count"] == 0
    assert hindsight["effective_config_source"] == "substrate_providers.hindsight"


def test_hindsight_substrate_save_merges_known_values(tmp_path):
    save_config(
        {
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "adoption_source": "hermes_hindsight_config",
                    "api_url": "http://127.0.0.1:8888",
                    "bank_id": "memory-os",
                    "provider_bank_id": "memory-os",
                    "bank_selection_reason": "top_level_provider_bank_id",
                    "configured_provider_bank_ids": ["business", "memory-os"],
                    "non_provider_configured_bank_count": 1,
                    "retain_enabled": True,
                    "recall_mode": "shadow",
                    "reflect_enabled": False,
                    "legacy_provider_was_hindsight": True,
                    "legacy_auto_retain_observed_disabled": True,
                }
            }
        },
        tmp_path,
    )

    hindsight = load_config(tmp_path)["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is True
    assert hindsight["recall_mode"] == "shadow"
    assert hindsight["reflect_enabled"] is False
    assert hindsight["api_key"] == ""
    assert hindsight["api_key_env_var"] == "HINDSIGHT_API_KEY"
    assert hindsight["legacy_auto_retain_observed_disabled"] is True
    assert hindsight["provider_bank_id"] == "memory-os"
    assert hindsight["bank_selection_reason"] == "top_level_provider_bank_id"
    assert hindsight["configured_provider_bank_ids"] == ["business", "memory-os"]
    assert hindsight["non_provider_configured_bank_count"] == 1


def test_legacy_hindsight_adapter_enabled_is_not_effective_source(tmp_path):
    save_config(
        {
            "hindsight_adapter_enabled": True,
            "substrate_providers": {
                "hindsight": {
                    "enabled": False,
                    "recall_mode": "off",
                }
            },
        },
        tmp_path,
    )

    config = load_config(tmp_path)

    assert config["hindsight_adapter_enabled"] is True
    assert config["substrate_providers"]["hindsight"]["enabled"] is False
    assert config["substrate_providers"]["hindsight"]["effective_config_source"] == "substrate_providers.hindsight"
