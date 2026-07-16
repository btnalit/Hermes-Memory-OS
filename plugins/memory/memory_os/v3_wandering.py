"""Private V3 wandering orchestrator; never owns a delivery path."""
from __future__ import annotations

from typing import Any, Protocol
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .crystallized import CrystallizedMemoryService
from .jsonl_io import append_jsonl_locked, read_jsonl
from .store import MemoryOSStore
from .v3_body_packet import (
    build_body_state_packet,
    remove_body_manifests,
    write_body_packet_manifest,
)
from .wandering_journal import ingest_thought_batch

WANDERING_PROMPT_CONTRACT = """You receive bounded memory fragments and relations.
You may associate freely or return {\"entries\":[]}.
Do not search for insights, summarize meaning, give advice, make plans, call tools,
execute tasks, send messages, modify identity, or write permanent memory.
Every provenance ref must come from the input allowlist. Return structured JSON only.
"""


class EphemeralAdapter(Protocol):
    @property
    def capability(self) -> bool: ...

    def infer(
        self,
        *,
        packet: dict[str, Any],
        prompt_contract: str,
        route_snapshot: dict[str, Any],
    ) -> dict[str, Any]: ...


def run_v3_wandering_cycle(
    store: MemoryOSStore,
    *,
    adapter: EphemeralAdapter,
    route_snapshot: dict[str, Any],
    seed_candidates: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    quiet_gate: dict[str, Any],
    ttl_days: int,
    max_entry_chars: int,
    max_lineage_hops: int,
    model_input_char_budget: int,
    execution_gate_envelope_id: str = "",
    source_window: dict[str, Any] | None = None,
    source_cursors: dict[str, Any] | None = None,
    sampler_seed: str = "",
) -> dict[str, Any]:
    if not isinstance(quiet_gate, dict) or quiet_gate.get("quiet") is not True:
        return {"status": "skipped", "reason": str((quiet_gate or {}).get("reason") or "quiet_gate_closed")}
    if not seed_candidates:
        return _boundary_result("healthy_no_sample", reason="no_eligible_input")
    if not getattr(adapter, "capability", False):
        return _boundary_result("capability_unavailable")
    if (
        type(ttl_days) is not int
        or ttl_days <= 0
        or type(max_entry_chars) is not int
        or max_entry_chars <= 0
        or type(max_lineage_hops) is not int
        or max_lineage_hops <= 0
        or type(model_input_char_budget) is not int
        or model_input_char_budget <= 0
    ):
        return _boundary_result("required_knob_missing")
    expected_provider = str(route_snapshot.get("provider") or "")
    expected_model = str(route_snapshot.get("model") or "")
    if not expected_provider or not expected_model:
        return _boundary_result("route_snapshot_missing")

    per_seed_budget = max(1, min(max_entry_chars, model_input_char_budget // max(len(seed_candidates), 1)))
    try:
        packet = build_body_state_packet(
            quiet_state=True,
            source_window=source_window or {},
            source_cursors=source_cursors or {},
            seed_candidates=seed_candidates,
            edges=edges,
            sampler_seed=sampler_seed,
            max_text_chars=per_seed_budget,
        )
        write_body_packet_manifest(store, packet)
    except (TypeError, ValueError):
        return _boundary_result("packet_rejected")

    snapshot_id = str(packet["snapshot_id"])
    try:
        result = adapter.infer(
            packet=packet,
            prompt_contract=WANDERING_PROMPT_CONTRACT,
            route_snapshot=route_snapshot,
        )
    except Exception:
        remove_body_manifests(store, {snapshot_id})
        return _boundary_result("provider_error")

    if not _result_boundaries_are_safe(result):
        remove_body_manifests(store, {snapshot_id})
        return _boundary_result("boundary_violation")
    if not _route_is_approved(result, route_snapshot):
        remove_body_manifests(store, {snapshot_id})
        return _boundary_result("route_drift")
    if str(result.get("status") or "") != "ok":
        remove_body_manifests(store, {snapshot_id})
        return _boundary_result(str(result.get("status") or "provider_error"))

    structured = result.get("structured_output")
    if not isinstance(structured, dict) or set(structured) != {"entries"} or not isinstance(structured.get("entries"), list):
        remove_body_manifests(store, {snapshot_id})
        return _boundary_result("schema_rejected")
    try:
        ingested = ingest_thought_batch(
            store,
            packet=packet,
            model_entries=structured["entries"],
            ttl_days=ttl_days,
            max_entry_chars=max_entry_chars,
            max_lineage_hops=max_lineage_hops,
            execution_gate_envelope_id=execution_gate_envelope_id,
        )
    except (TypeError, ValueError, OSError):
        remove_body_manifests(store, {snapshot_id})
        return _boundary_result("schema_rejected")
    if not ingested:
        return {
            **_boundary_result("healthy_no_sample", reason="empty_entries"),
            "model_input_transmitted": True,
        }
    return {
        **_boundary_result("ingested"),
        "entry_count": len(ingested),
        "model_input_transmitted": True,
    }


def evaluate_v3_quiet_gate(
    store: MemoryOSStore,
    config: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if config.get("wandering_enabled") is not True:
        return {"quiet": False, "reason": "wandering_disabled"}
    required_positive = (
        "wandering_max_attempts_per_window",
        "wandering_attempt_window_seconds",
        "wandering_model_input_char_budget",
        "journal_ttl_days",
        "journal_max_entry_chars",
        "journal_max_lineage_hops",
    )
    if any(type(config.get(key)) is not int or int(config[key]) <= 0 for key in required_positive):
        return {"quiet": False, "reason": "required_knob_missing"}
    hours = config.get("wandering_quiet_hours_utc")
    if not isinstance(hours, list) or current.hour not in hours:
        return {"quiet": False, "reason": "outside_quiet_window"}
    evidence_path = store.roots.memory_os_root / "system" / "v3_seed_evidence_snapshot.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        evidence = {}
    if evidence.get("activation_evidence_ready") is not True:
        return {"quiet": False, "reason": "seed_evidence_not_ready"}
    overlay_path = store.roots.memory_os_root / "system" / "state_overlay" / "current.json"
    try:
        overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        overlay = {}
    active_projects = ((overlay.get("active_projects") or {}).get("data") or []) if isinstance(overlay, dict) else []
    if active_projects:
        return {"quiet": False, "reason": "foreground_task"}
    window_seconds = int(config["wandering_attempt_window_seconds"])
    cutoff = current - timedelta(seconds=window_seconds)
    attempts = 0
    for row in read_jsonl(v3_wandering_runs_path(store)) or []:
        if row.get("model_input_transmitted") is not True:
            continue
        timestamp = _parse_timestamp(row.get("created_at"))
        if timestamp is not None and timestamp >= cutoff:
            attempts += 1
    if attempts >= int(config["wandering_max_attempts_per_window"]):
        return {"quiet": False, "reason": "attempt_budget_exhausted"}
    return {"quiet": True, "reason": "off_peak"}


def collect_seed_inputs_from_store(
    store: MemoryOSStore,
    *,
    max_seed_candidates: int = 8,
    max_edges: int = 16,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    daily_path = store.roots.memory_os_root / "system" / "v3_seed_edges_daily.jsonl"
    rows = [item for item in (read_jsonl(daily_path) or []) if item.get("valid") is True]
    if not rows:
        return [], [], {}, {}
    latest = rows[-1]
    refs: list[str] = []
    raw_edges = latest.get("edges") if isinstance(latest.get("edges"), list) else []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        for key in ("from", "to"):
            ref = str(edge.get(key) or "")
            if ref and ref not in refs:
                refs.append(ref)
    seeds: list[dict[str, Any]] = []
    for ref in refs:
        resolved = _resolve_seed_candidate(store, ref)
        if resolved is not None:
            seeds.append(resolved)
        if len(seeds) >= max_seed_candidates:
            break
    allowed = {str(item["ref"]) for item in seeds}
    edges = [
        dict(item)
        for item in raw_edges
        if isinstance(item, dict) and str(item.get("from") or "") in allowed and str(item.get("to") or "") in allowed
    ][:max_edges]
    window = {
        "start": str((latest.get("source_window") or {}).get("start") or ""),
        "end": str((latest.get("source_window") or {}).get("end") or ""),
    }
    cursors = {
        "memory_sources": {
            "offset_start": int(latest.get("source_offset_start") or 0),
            "offset_end": int(latest.get("source_offset_end") or 0),
        }
    }
    return seeds, edges, window, cursors


def record_v3_wandering_run(store: MemoryOSStore, result: dict[str, Any], *, now: datetime | None = None) -> None:
    record = {
        "schema_version": "memory-os.v3_wandering_run.v0",
        "created_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "status": str(result.get("status") or "unknown"),
        "reason": str(result.get("reason") or ""),
        "model_input_transmitted": result.get("model_input_transmitted") is True,
        "owner_delivery_attempted": result.get("owner_delivery_attempted") is True,
        "external_action_executed": result.get("external_action_executed") is True,
    }
    append_jsonl_locked(v3_wandering_runs_path(store), record)


def v3_wandering_runs_path(store: MemoryOSStore) -> Path:
    return store.roots.memory_os_root / "system" / "v3_wandering_runs.jsonl"


def _resolve_seed_candidate(store: MemoryOSStore, ref: str) -> dict[str, Any] | None:
    if not ref.startswith("crystallized:"):
        return None
    record_id = ref.split(":", 1)[1]
    record = CrystallizedMemoryService(store).find_record(record_id)
    if record is None or not str(record.body).strip():
        return None
    return {
        "ref": ref,
        "kind": "stable_memory",
        "bounded_text": str(record.body).strip(),
        "epistemic_status": "approved",
        "salience_reasons": ["co_selected"],
    }


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _route_is_approved(result: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    actual = {
        "provider": str(result.get("actual_provider") or ""),
        "model": str(result.get("actual_model") or ""),
    }
    primary = {"provider": str(snapshot.get("provider") or ""), "model": str(snapshot.get("model") or "")}
    if result.get("fallback_used") is not True:
        return actual == primary
    allowed = snapshot.get("allowed_routes")
    return isinstance(allowed, list) and actual in allowed


def _result_boundaries_are_safe(result: Any) -> bool:
    return (
        isinstance(result, dict)
        and result.get("model_input_transmitted") is True
        and result.get("owner_delivery_attempted") is False
        and result.get("external_action_executed") is False
        and result.get("tools_enabled") is False
    )


def _boundary_result(status: str, *, reason: str = "") -> dict[str, Any]:
    result = {
        "status": status,
        "model_input_transmitted": False,
        "owner_delivery_attempted": False,
        "external_action_executed": False,
    }
    if reason:
        result["reason"] = reason
    return result
