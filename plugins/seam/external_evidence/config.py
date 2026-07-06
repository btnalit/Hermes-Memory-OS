"""External Evidence Seam configuration — profile-scoped, default disabled.

Reads from ``$HERMES_HOME/memory-os/system/seam_config.json``.
When the file or a provider section is missing, every provider
defaults to ``enabled: false``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SEAM_CONFIG_SCHEMA_VERSION = "memory-os.seam_config.v0"

DEFAULT_PROVIDER_CONFIG: dict[str, Any] = {
    "enabled": False,
    "base_url": "",
    "api_key_file": "",
    "dataset_id": "",
}


def load_seam_config(hermes_home: str | Path) -> dict[str, Any]:
    """Load the seam configuration from disk.

    Returns the full config dict.  When the file is missing or
    unreadable, returns an empty providers dict (all disabled).
    """
    config_path = Path(hermes_home) / "memory-os" / "system" / "seam_config.json"
    if not config_path.exists():
        return {"providers": {}, "schema_version": SEAM_CONFIG_SCHEMA_VERSION}

    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"providers": {}, "schema_version": SEAM_CONFIG_SCHEMA_VERSION}

    if not isinstance(loaded, dict):
        return {"providers": {}, "schema_version": SEAM_CONFIG_SCHEMA_VERSION}

    return loaded


def get_provider_config(
    config: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    """Return the config for *provider*, merged with defaults.

    Always returns ``enabled: false`` for unknown providers.
    """
    providers = config.get("providers", {}) if isinstance(config, dict) else {}
    provider_cfg = providers.get(provider, {}) if isinstance(providers, dict) else {}
    if not isinstance(provider_cfg, dict):
        provider_cfg = {}
    merged = dict(DEFAULT_PROVIDER_CONFIG)
    merged.update({k: v for k, v in provider_cfg.items() if k in merged})
    merged["enabled"] = bool(merged.get("enabled"))
    return merged


def is_provider_enabled(config: dict[str, Any], provider: str) -> bool:
    """Return True if *provider* is enabled in *config*."""
    return bool(get_provider_config(config, provider).get("enabled"))
