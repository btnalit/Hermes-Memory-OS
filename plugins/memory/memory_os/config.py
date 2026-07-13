"""Configuration helpers for the Memory-OS provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_CONFIG: dict[str, Any] = {
    "capture_policy": "summary_only",
    "prefetch_char_budget": 20000,
    "fast_path_keywords": None,
    "hindsight_adapter_enabled": False,
    "allow_full_local_capture": False,
    "diagnostic_grounding_enabled": None,
    "substrate_providers": {
        "hindsight": {
            "enabled": False,
            "adoption_source": "none",
            "api_url": "",
            "bank_id": "",
            "provider_config_path": "",
            "provider_bank_id": "",
            "bank_selection_reason": "not_selected",
            "configured_provider_bank_ids": [],
            "non_provider_configured_bank_count": 0,
            "api_key": "",
            "api_key_env_var": "HINDSIGHT_API_KEY",
            "retain_enabled": False,
            "recall_mode": "off",
            "reflect_enabled": False,
            "allowed_retain_sources": ["crystallized", "owner_approved"],
            "reject_raw_turns": True,
            "recall_budget": "mid",
            "recall_max_tokens": 1200,
            "legacy_provider_was_hindsight": False,
            "legacy_auto_retain_observed_disabled": False,
            "projection_coherence_window_seconds": 300,
            "effective_config_source": "substrate_providers.hindsight",
            "pollution_scan_status": "unknown",
        },
    },
    "context_router": {
        "enabled": False,
        "mode": "dry_run",
        "apply_routes": [],
        "dry_run_routes": [],
        "llm_judge_mode": "disabled",
    },
    "memory_sources": {
        "enabled": False,
        "mode": "metadata_only",
        "retention_days": 30,
        "record_live_prefetch": True,
        "record_dry_run": False,
    },
    "low_clue_recall": {
        "enabled": False,
        "candidate_limit": 4,
        "llm_judge": {
            "enabled": False,
            "mode": "none",
            "provider": "hermes_default",
            "model": None,
            "temperature": 0,
            "timeout_ms": 8000,
            "max_tokens": 1024,
            "max_candidates": 4,
            "on_error": "deterministic_fallback",
        },
    },
    "owner_review": {
        "enabled": False,
        "mode": "dry_run",
        "owner_id": "owner",
        "channel": "cli",
        "target_ref": "",
        "direct_message": False,
        "allow_group": False,
        "schedule": "daily",
        "raw_body": False,
        "actions_enabled": False,
        "reply_ingress_enabled": True,
        "delivery_enabled": False,
        "delivery_adapter": "none",
        "hermes_bin": "hermes",
        "recurring_delivery_enabled": False,
        "recurring_delivery_mode": "disabled",
        "recurring_delivery_channel": "unknown",
        "recurring_delivery_target_class": "missing",
        "cron_job_name": "memory-os-owner-review-digest",
        "aging_enabled": True,
        "aging_action_required_days": 7,
        "aging_fyi_days": 30,
        "max_action_required": 3,
        "max_review_suggested": 5,
        "max_fyi": 5,
    },
    "right_brain_expression": {
        "legacy_cognitive_loop_enabled": False,
        "recurring_delivery_enabled": False,
        "recurring_delivery_mode": "disabled",
        "recurring_delivery_channel": "unknown",
        "recurring_delivery_target_class": "missing",
        "speak_once_delivery_enabled": False,
        "delivery_adapter": "none",
        "target_ref": "",
        "hermes_bin": "hermes",
    },
    "v3_inner_life": {
        "seed_evidence": {
            "enabled": False,
            "max_edges": 10000,
            "min_coverage_ratio": 1.0,
            "require_shared_entity": True,
        },
        "host_agent_root": None,
        "wandering_enabled": False,
        "expression_enabled": False,
        "outlet_shadow_enabled": False,
        "synthesis_admission_enabled": False,
        "synthesis_min_inputs": None,
        "synthesis_min_provenance_diversity": None,
        "synthesis_min_semantic_distance": None,
        "wandering_max_attempts_per_window": None,
        "wandering_attempt_window_seconds": None,
        "wandering_model_input_char_budget": None,
        "wandering_quiet_hours_utc": None,
        "share_max_per_window": None,
        "share_window_seconds": None,
        "share_cooldown_seconds": None,
        "share_min_lineage_diversity": None,
        "journal_ttl_days": None,
        "journal_max_entry_chars": None,
        "journal_max_lineage_hops": None,
        "semantic_dedupe_threshold": None,
    },
    "session_mirror": {
        "test_host_apply_allowed": False,
        "test_host_marker": "",
        "production_apply_owner_ref_required": True,
        "auto_apply_after_owner_home_graduation": True,
        "auto_apply_max_sessions_per_run": 1,
    },
    "l4": {
        "kill_switch_enabled": False,
    },
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
            "key": "fast_path_keywords",
            "description": "Optional custom Chinese keyword list for fast-path query routing (null = use built-in defaults)",
            "default": DEFAULT_CONFIG["fast_path_keywords"],
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
        {
            "key": "substrate_providers",
            "description": "Optional governed memory substrates such as Hindsight",
            "default": DEFAULT_CONFIG["substrate_providers"],
        },
        {
            "key": "context_router",
            "description": "Context Relevance Router mode and route allowlist",
            "default": DEFAULT_CONFIG["context_router"],
        },
        {
            "key": "memory_sources",
            "description": "Memory Sources attribution metadata ledger",
            "default": DEFAULT_CONFIG["memory_sources"],
        },
        {
            "key": "low_clue_recall",
            "description": "Low-clue recall router and optional report-only LLM judge",
            "default": DEFAULT_CONFIG["low_clue_recall"],
        },
        {
            "key": "owner_review",
            "description": "Owner review digest and channel resolver settings",
            "default": DEFAULT_CONFIG["owner_review"],
        },
        {
            "key": "right_brain_expression",
            "description": "Right-brain expression delivery and owner-approved speak-once settings",
            "default": DEFAULT_CONFIG["right_brain_expression"],
        },
        {
            "key": "v3_inner_life",
            "description": "V3 private inner-life observation, journal, wandering, synthesis, and expression gates",
            "default": DEFAULT_CONFIG["v3_inner_life"],
        },
        {
            "key": "session_mirror",
            "description": "SessionMirror bounded apply governance gates",
            "default": DEFAULT_CONFIG["session_mirror"],
        },
        {
            "key": "l4",
            "description": "V7 L4 live-shadow and acting safety settings",
            "default": DEFAULT_CONFIG["l4"],
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
    merged["substrate_providers"] = _merge_substrate_providers_config(merged.get("substrate_providers"))
    merged["context_router"] = _merge_context_router_config(merged.get("context_router"))
    merged["memory_sources"] = _merge_memory_sources_config(merged.get("memory_sources"))
    merged["low_clue_recall"] = _merge_low_clue_recall_config(merged.get("low_clue_recall"))
    merged["owner_review"] = _merge_owner_review_config(merged.get("owner_review"))
    merged["right_brain_expression"] = _merge_right_brain_expression_config(merged.get("right_brain_expression"))
    merged["v3_inner_life"] = _merge_v3_inner_life_config(merged.get("v3_inner_life"))
    merged["session_mirror"] = _merge_session_mirror_config(merged.get("session_mirror"))
    merged["l4"] = _merge_l4_config(merged.get("l4"))
    return merged


def _known_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: values[key] for key in DEFAULT_CONFIG if key in values}


def _merge_substrate_providers_config(value: Any) -> dict[str, Any]:
    default = json.loads(json.dumps(DEFAULT_CONFIG["substrate_providers"]))
    if not isinstance(value, dict):
        return default
    hindsight_value = value.get("hindsight")
    if isinstance(hindsight_value, dict):
        hindsight = dict(default["hindsight"])
        for key in hindsight:
            if key in hindsight_value:
                hindsight[key] = hindsight_value[key]
        if hindsight["adoption_source"] not in {"none", "hermes_hindsight_config", "wizard", "manual"}:
            hindsight["adoption_source"] = "none"
        if hindsight["recall_mode"] not in {"off", "shadow", "active"}:
            hindsight["recall_mode"] = "off"
        try:
            hindsight["recall_max_tokens"] = max(int(hindsight.get("recall_max_tokens") or 1200), 1)
        except (TypeError, ValueError):
            hindsight["recall_max_tokens"] = 1200
        try:
            hindsight["projection_coherence_window_seconds"] = max(
                int(hindsight.get("projection_coherence_window_seconds") or 300),
                1,
            )
        except (TypeError, ValueError):
            hindsight["projection_coherence_window_seconds"] = 300
        if "legacy_auto_retain_hardened" in hindsight_value and "legacy_auto_retain_observed_disabled" not in hindsight_value:
            hindsight["legacy_auto_retain_observed_disabled"] = bool(hindsight_value.get("legacy_auto_retain_hardened"))
        if not isinstance(hindsight.get("allowed_retain_sources"), list):
            hindsight["allowed_retain_sources"] = ["crystallized", "owner_approved"]
        hindsight["allowed_retain_sources"] = [
            str(item)
            for item in hindsight["allowed_retain_sources"]
            if str(item) in {"crystallized", "owner_approved", "distilled"}
        ] or ["crystallized", "owner_approved"]
        if not isinstance(hindsight.get("configured_provider_bank_ids"), list):
            hindsight["configured_provider_bank_ids"] = []
        hindsight["configured_provider_bank_ids"] = [
            str(item) for item in hindsight["configured_provider_bank_ids"] if str(item)
        ]
        try:
            hindsight["non_provider_configured_bank_count"] = max(
                int(hindsight.get("non_provider_configured_bank_count") or 0),
                0,
            )
        except (TypeError, ValueError):
            hindsight["non_provider_configured_bank_count"] = 0
        hindsight["effective_config_source"] = "substrate_providers.hindsight"
        default["hindsight"] = hindsight
    return default


def _merge_context_router_config(value: Any) -> dict[str, Any]:
    default = dict(DEFAULT_CONFIG["context_router"])
    if not isinstance(value, dict):
        return default
    merged = dict(default)
    for key in default:
        if key in value:
            merged[key] = value[key]
    if not isinstance(merged.get("apply_routes"), list):
        merged["apply_routes"] = []
    if not isinstance(merged.get("dry_run_routes"), list):
        merged["dry_run_routes"] = []
    return merged


def _merge_memory_sources_config(value: Any) -> dict[str, Any]:
    default = dict(DEFAULT_CONFIG["memory_sources"])
    if not isinstance(value, dict):
        return default
    merged = dict(default)
    for key in default:
        if key in value:
            merged[key] = value[key]
    try:
        merged["retention_days"] = int(merged.get("retention_days") or 30)
    except (TypeError, ValueError):
        merged["retention_days"] = 30
    return merged


def _merge_low_clue_recall_config(value: Any) -> dict[str, Any]:
    default = json.loads(json.dumps(DEFAULT_CONFIG["low_clue_recall"]))
    if not isinstance(value, dict):
        return default
    merged = dict(default)
    for key in ("enabled", "candidate_limit"):
        if key in value:
            merged[key] = value[key]
    judge = dict(default["llm_judge"])
    incoming_judge = value.get("llm_judge")
    if isinstance(incoming_judge, dict):
        for key in judge:
            if key in incoming_judge:
                judge[key] = incoming_judge[key]
    try:
        merged["candidate_limit"] = max(int(merged.get("candidate_limit") or 4), 1)
    except (TypeError, ValueError):
        merged["candidate_limit"] = 4
    try:
        judge["timeout_ms"] = max(int(judge.get("timeout_ms") or 8000), 100)
    except (TypeError, ValueError):
        judge["timeout_ms"] = 8000
    try:
        judge["max_candidates"] = max(int(judge.get("max_candidates") or 4), 1)
    except (TypeError, ValueError):
        judge["max_candidates"] = 4
    merged["llm_judge"] = judge
    return merged


def _merge_owner_review_config(value: Any) -> dict[str, Any]:
    default = dict(DEFAULT_CONFIG["owner_review"])
    if not isinstance(value, dict):
        return default
    merged = dict(default)
    for key in default:
        if key in value:
            merged[key] = value[key]
    for key in (
        "max_action_required",
        "max_review_suggested",
        "max_fyi",
        "aging_action_required_days",
        "aging_fyi_days",
    ):
        try:
            merged[key] = max(int(merged.get(key) or default[key]), 0)
        except (TypeError, ValueError):
            merged[key] = default[key]
    merged["mode"] = str(merged.get("mode") or "dry_run")
    merged["channel"] = str(merged.get("channel") or "cli")
    merged["target_ref"] = str(merged.get("target_ref") or "")
    merged["owner_id"] = str(merged.get("owner_id") or "owner")
    merged["enabled"] = bool(merged.get("enabled"))
    merged["direct_message"] = bool(merged.get("direct_message"))
    merged["allow_group"] = bool(merged.get("allow_group"))
    merged["raw_body"] = False
    merged["actions_enabled"] = bool(merged.get("actions_enabled"))
    merged["reply_ingress_enabled"] = bool(merged.get("reply_ingress_enabled"))
    merged["delivery_enabled"] = bool(merged.get("delivery_enabled"))
    merged["delivery_adapter"] = str(merged.get("delivery_adapter") or "none")
    merged["hermes_bin"] = str(merged.get("hermes_bin") or "hermes")
    merged["recurring_delivery_enabled"] = bool(merged.get("recurring_delivery_enabled"))
    merged["recurring_delivery_mode"] = str(merged.get("recurring_delivery_mode") or "disabled")
    merged["recurring_delivery_channel"] = str(merged.get("recurring_delivery_channel") or "unknown")
    merged["recurring_delivery_target_class"] = str(merged.get("recurring_delivery_target_class") or "missing")
    merged["cron_job_name"] = str(merged.get("cron_job_name") or "memory-os-owner-review-digest")
    merged["aging_enabled"] = bool(merged.get("aging_enabled"))
    return merged


def _merge_v3_inner_life_config(value: Any) -> dict[str, Any]:
    default = DEFAULT_CONFIG["v3_inner_life"]
    merged = dict(default)
    merged["seed_evidence"] = dict(default["seed_evidence"])
    if not isinstance(value, dict):
        return merged

    seed_value = value.get("seed_evidence")
    if isinstance(seed_value, dict):
        seed = dict(default["seed_evidence"])
        seed["enabled"] = seed_value.get("enabled") is True
        max_edges = seed_value.get("max_edges")
        if type(max_edges) is int and 1 <= max_edges <= 1_000_000:
            seed["max_edges"] = max_edges
        coverage = seed_value.get("min_coverage_ratio")
        if isinstance(coverage, (int, float)) and not isinstance(coverage, bool) and 0.0 <= float(coverage) <= 1.0:
            seed["min_coverage_ratio"] = float(coverage)
        seed["require_shared_entity"] = seed_value.get("require_shared_entity") is True
        merged["seed_evidence"] = seed

    host_root = value.get("host_agent_root")
    merged["host_agent_root"] = (
        str(Path(host_root).expanduser().resolve())
        if isinstance(host_root, str) and host_root.strip() and Path(host_root).expanduser().is_absolute()
        else None
    )
    for key in ("wandering_enabled", "expression_enabled", "outlet_shadow_enabled", "synthesis_admission_enabled"):
        merged[key] = value.get(key) is True
    for key in (
        "wandering_max_attempts_per_window",
        "wandering_attempt_window_seconds",
        "wandering_model_input_char_budget",
        "synthesis_min_inputs",
        "synthesis_min_provenance_diversity",
        "share_max_per_window",
        "share_window_seconds",
        "share_cooldown_seconds",
        "share_min_lineage_diversity",
        "journal_ttl_days",
        "journal_max_entry_chars",
        "journal_max_lineage_hops",
    ):
        candidate = value.get(key)
        merged[key] = candidate if type(candidate) is int and candidate > 0 else None
    quiet_hours = value.get("wandering_quiet_hours_utc")
    if isinstance(quiet_hours, list) and quiet_hours and all(type(item) is int and 0 <= item <= 23 for item in quiet_hours):
        merged["wandering_quiet_hours_utc"] = sorted(set(quiet_hours))
    else:
        merged["wandering_quiet_hours_utc"] = None
    for key in ("semantic_dedupe_threshold", "synthesis_min_semantic_distance"):
        threshold = value.get(key)
        merged[key] = (
            float(threshold)
            if isinstance(threshold, (int, float))
            and not isinstance(threshold, bool)
            and 0.0 <= float(threshold) <= 1.0
            else None
        )
    return merged


def _merge_right_brain_expression_config(value: Any) -> dict[str, Any]:
    default = dict(DEFAULT_CONFIG["right_brain_expression"])
    if not isinstance(value, dict):
        return default
    merged = dict(default)
    for key in default:
        if key in value:
            merged[key] = value[key]
    merged["legacy_cognitive_loop_enabled"] = merged.get("legacy_cognitive_loop_enabled") is True
    merged["recurring_delivery_enabled"] = bool(merged.get("recurring_delivery_enabled"))
    merged["recurring_delivery_mode"] = str(merged.get("recurring_delivery_mode") or "disabled")
    merged["recurring_delivery_channel"] = str(merged.get("recurring_delivery_channel") or "unknown")
    merged["recurring_delivery_target_class"] = str(merged.get("recurring_delivery_target_class") or "missing")
    merged["speak_once_delivery_enabled"] = bool(merged.get("speak_once_delivery_enabled"))
    merged["delivery_adapter"] = str(merged.get("delivery_adapter") or "none")
    merged["target_ref"] = str(merged.get("target_ref") or "")
    merged["hermes_bin"] = str(merged.get("hermes_bin") or "hermes")
    return merged


def _merge_session_mirror_config(value: Any) -> dict[str, Any]:
    default = dict(DEFAULT_CONFIG["session_mirror"])
    if not isinstance(value, dict):
        return default
    merged = dict(default)
    for key in default:
        if key in value:
            merged[key] = value[key]
    merged["test_host_apply_allowed"] = bool(merged.get("test_host_apply_allowed"))
    merged["test_host_marker"] = str(merged.get("test_host_marker") or "")
    merged["production_apply_owner_ref_required"] = bool(merged.get("production_apply_owner_ref_required"))
    return merged


def _merge_l4_config(value: Any) -> dict[str, Any]:
    default = dict(DEFAULT_CONFIG["l4"])
    if not isinstance(value, dict):
        return default
    merged = dict(default)
    for key in default:
        if key in value:
            merged[key] = value[key]
    merged["kill_switch_enabled"] = bool(merged.get("kill_switch_enabled"))
    return merged


def effective_diagnostic_grounding_enabled(config: dict[str, Any], profile: str) -> bool:
    configured = config.get("diagnostic_grounding_enabled")
    if isinstance(configured, bool):
        return configured
    return str(profile or "").strip().lower() != "sannai"
