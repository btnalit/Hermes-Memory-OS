"""Configuration helpers for the Memory-OS provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_CONFIG: dict[str, Any] = {
    "capture_policy": "summary_only",
    "prefetch_char_budget": 2200,
    "hindsight_adapter_enabled": False,
    "allow_full_local_capture": False,
    "diagnostic_grounding_enabled": None,
}


def get_config_schema() -> list[dict[str, Any]]:
    return [
        {
            "key": "capture_policy",
            "description": "Conversation capture policy",
            "default": DEFAULT_CONFIG["capture_policy"],
            "choices": ["summary_only"],
        },
        {
            "key": "prefetch_char_budget",
            "description": "Maximum Memory-OS prefetch characters",
            "default": DEFAULT_CONFIG["prefetch_char_budget"],
        },
        {
            "key": "hindsight_adapter_enabled",
            "description": "Enable optional approved-memory export adapter",
            "default": DEFAULT_CONFIG["hindsight_adapter_enabled"],
        },
        {
            "key": "allow_full_local_capture",
            "description": "Allow full local transcript capture",
            "default": DEFAULT_CONFIG["allow_full_local_capture"],
        },
        {
            "key": "diagnostic_grounding_enabled",
            "description": "Enable current-runtime grounding for memory provider diagnostics",
            "default": DEFAULT_CONFIG["diagnostic_grounding_enabled"],
        },
    ]


def config_path(hermes_home: str | Path) -> Path:
    return Path(hermes_home).expanduser().resolve() / "memory-os" / "config.json"


def load_config(hermes_home: str | Path) -> dict[str, Any]:
    path = config_path(hermes_home)
    loaded: dict[str, Any] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            loaded = raw
    return _merge_known(loaded)


def save_config(values: dict[str, Any], hermes_home: str | Path) -> None:
    path = config_path(hermes_home)
    existing = load_config(hermes_home)
    existing.update(_known_values(values))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _merge_known(values: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    merged.update(_known_values(values))
    return merged


def _known_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: values[key] for key in DEFAULT_CONFIG if key in values}


def effective_diagnostic_grounding_enabled(config: dict[str, Any], profile: str) -> bool:
    configured = config.get("diagnostic_grounding_enabled")
    if isinstance(configured, bool):
        return configured
    return str(profile or "").strip().lower() != "sannai"
