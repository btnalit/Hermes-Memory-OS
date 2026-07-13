"""V3 synthesis shadow with deterministic admission and provenance expansion."""
from __future__ import annotations

from typing import Any, Callable

from .store import MemoryOSStore
from .v3_body_packet import build_body_state_packet, remove_body_manifests, write_body_packet_manifest
from .v3_wandering import EphemeralAdapter, _result_boundaries_are_safe, _route_is_approved
from .wandering_journal import ingest_thought_batch, read_journal

SYNTHESIS_PROMPT_CONTRACT = """Synthesize only when the bounded private thoughts support a reusable insight.
Abstain with {\"entries\":[]} when uncertain. Do not advise, plan, execute, call tools,
send messages, write identity, or approve memory. Cite only input journal refs. JSON only.
"""


def run_v3_synthesis_cycle(
    store: MemoryOSStore,
    *,
    adapter: EphemeralAdapter,
    route_snapshot: dict[str, Any],
    min_inputs: int,
    min_provenance_diversity: int,
    min_semantic_distance: float,
    semantic_distance: Callable[[str, list[str]], float],
    ttl_days: int,
    max_entry_chars: int,
    max_lineage_hops: int,
) -> dict[str, Any]:
    if not getattr(adapter, "capability", False):
        return _result("capability_unavailable")
    if type(min_inputs) is not int or min_inputs < 2 or type(min_provenance_diversity) is not int or min_provenance_diversity < 2:
        return _result("required_knob_missing")
    if not isinstance(min_semantic_distance, (int, float)) or isinstance(min_semantic_distance, bool) or not 0 <= float(min_semantic_distance) <= 1:
        return _result("required_knob_missing")
    sources = [
        item
        for item in read_journal(store)
        if item.get("record_type") == "thought"
        and item.get("tier") in {"association", "interpretation"}
        and item.get("fate") == "pending"
        and item.get("outlet_status") != "blocked"
    ]
    roots = sorted({str(ref) for item in sources for ref in item.get("lineage_root_refs") or []})
    if len(sources) < min_inputs or len(roots) < min_provenance_diversity:
        return _result("admission_rejected")

    packet = build_body_state_packet(
        quiet_state=True,
        source_window={},
        source_cursors={},
        seed_candidates=[
            {
                "ref": "journal:" + str(item["entry_id"]),
                "kind": "private_thought",
                "bounded_text": str(item.get("content") or ""),
                "epistemic_status": "private_uncommitted",
                "salience_reasons": ["synthesis_admission"],
            }
            for item in sources
        ],
        edges=[],
        sampler_seed="synthesis-shadow",
        max_text_chars=max_entry_chars,
    )
    write_body_packet_manifest(store, packet)
    snapshot_id = str(packet["snapshot_id"])
    try:
        response = adapter.infer(packet=packet, prompt_contract=SYNTHESIS_PROMPT_CONTRACT, route_snapshot=route_snapshot)
    except Exception:
        remove_body_manifests(store, {snapshot_id})
        return _result("provider_error")
    if not _result_boundaries_are_safe(response):
        remove_body_manifests(store, {snapshot_id})
        return _result("boundary_violation")
    if not _route_is_approved(response, route_snapshot):
        remove_body_manifests(store, {snapshot_id})
        return _result("route_drift")
    structured = response.get("structured_output")
    entries = structured.get("entries") if isinstance(structured, dict) and set(structured) == {"entries"} else None
    if not isinstance(entries, list):
        remove_body_manifests(store, {snapshot_id})
        return _result("schema_rejected")
    if not entries:
        ingest_thought_batch(
            store,
            packet=packet,
            model_entries=[],
            ttl_days=ttl_days,
            max_entry_chars=max_entry_chars,
            max_lineage_hops=max_lineage_hops,
        )
        return _result("ok_empty", transmitted=True)

    source_by_ref = {"journal:" + str(item["entry_id"]): item for item in sources}
    cleaned: list[dict[str, Any]] = []
    try:
        for raw in entries:
            if not isinstance(raw, dict) or raw.get("reusable_insight") is not True:
                raise ValueError("not_reusable")
            refs = raw.get("provenance_refs")
            if not isinstance(refs, list) or len(refs) < min_inputs or any(str(ref) not in source_by_ref for ref in refs):
                raise ValueError("provenance")
            entry_roots = sorted({str(root) for ref in refs for root in source_by_ref[str(ref)].get("lineage_root_refs") or []})
            if len(entry_roots) < min_provenance_diversity:
                raise ValueError("provenance_diversity")
            content = str(raw.get("content") or "")
            if float(semantic_distance(content, entry_roots)) < float(min_semantic_distance):
                remove_body_manifests(store, {snapshot_id})
                return _result("semantic_gate_rejected", transmitted=True)
            candidate = dict(raw)
            candidate.pop("reusable_insight", None)
            cleaned.append(candidate)
    except (TypeError, ValueError):
        remove_body_manifests(store, {snapshot_id})
        return _result("schema_rejected", transmitted=True)

    try:
        ingested = ingest_thought_batch(
            store,
            packet=packet,
            model_entries=cleaned,
            ttl_days=ttl_days,
            max_entry_chars=max_entry_chars,
            max_lineage_hops=max_lineage_hops,
        )
    except (TypeError, ValueError, OSError):
        remove_body_manifests(store, {snapshot_id})
        return _result("schema_rejected", transmitted=True)
    return {**_result("ingested", transmitted=True), "entry_count": len(ingested)}


def _result(status: str, *, transmitted: bool = False) -> dict[str, Any]:
    return {
        "status": status,
        "model_input_transmitted": transmitted,
        "owner_delivery_attempted": False,
        "external_action_executed": False,
    }
