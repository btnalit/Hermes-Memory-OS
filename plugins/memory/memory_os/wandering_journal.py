"""Private mutable V3 wandering journal with fail-closed query tracing."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar
from uuid import uuid4

from .execution_gate import complete_execution_gate_envelope, start_execution_gate_envelope
from .jsonl_io import locked_jsonl_file
from .store import MemoryOSStore
from .v3_body_packet import remove_body_manifests, verify_body_packet_manifest

JOURNAL_SCHEMA_VERSION = "memory-os.v3_wandering_journal.v0"
_TIERS = {"association", "interpretation", "claim"}
_REQUESTED = {"hold", "share", "propose"}
_OPTIONAL_TEXT_FIELDS = ("felt_tone", "concern", "motive_fragment", "self_narrative_fragment")
T = TypeVar("T")


def wandering_journal_path(store: MemoryOSStore) -> Path:
    return store.roots.memory_os_root / "system" / "wandering_journal.jsonl"


def read_journal(store: MemoryOSStore) -> list[dict[str, Any]]:
    return _read_strict_records(wandering_journal_path(store))


def ingest_thought_batch(
    store: MemoryOSStore,
    *,
    packet: dict[str, Any],
    model_entries: list[dict[str, Any]],
    ttl_days: int,
    max_entry_chars: int,
    max_lineage_hops: int,
    execution_gate_envelope_id: str = "",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if type(ttl_days) is not int or ttl_days <= 0:
        raise ValueError("ttl_days")
    if type(max_entry_chars) is not int or max_entry_chars <= 0:
        raise ValueError("max_entry_chars")
    if type(max_lineage_hops) is not int or max_lineage_hops < 0:
        raise ValueError("max_lineage_hops")
    manifest = verify_body_packet_manifest(store, packet)
    if not isinstance(model_entries, list):
        raise ValueError("batch_schema_invalid")
    if not model_entries:
        remove_body_manifests(store, {str(packet["snapshot_id"])})
        return []

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    born_at = current.isoformat()
    expires_at = (current + timedelta(days=ttl_days)).isoformat()
    allowed_refs = {str(item) for item in manifest.get("source_refs") or []}
    validated: list[dict[str, Any]] = []
    try:
        for raw in model_entries:
            validated.append(
                _validate_and_build_entry(
                    raw,
                    packet=packet,
                    allowed_refs=allowed_refs,
                    born_at=born_at,
                    expires_at=expires_at,
                    max_entry_chars=max_entry_chars,
                    max_lineage_hops=max_lineage_hops,
                )
            )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"batch_schema_invalid:{exc}") from exc

    envelope_id = str(execution_gate_envelope_id or "").strip()
    internal_envelope = not envelope_id
    if internal_envelope:
        envelope = start_execution_gate_envelope(
            store,
            lane_id="v3_journal_ingest",
            trigger_surface="memory_os_internal",
            risk_class="private_ephemeral_state_write",
            human_approval_required=False,
            why_no_human_approval="bounded automatic journal ingest with no external action",
            scope={"write_surface": "v3_wandering_journal", "entry_count": len(validated)},
            boundary={
                "owner_delivery_attempted": False,
                "external_action_executed": False,
                "actual_identity_write": False,
                "actual_unapproved_crystallized_approval": False,
            },
            precheck={"packet_manifest_verified": True},
            evidence_refs=[],
        )
        envelope_id = str(envelope["execution_gate_envelope_id"])

    def mutate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        existing_ids = {str(item.get("entry_id") or "") for item in records if item.get("record_type") == "thought"}
        if any(str(item["entry_id"]) in existing_ids for item in validated):
            raise ValueError("duplicate_entry_id")
        return [*records, *validated], validated

    try:
        result = _mutate_journal(store, mutate)
        if internal_envelope:
            complete_execution_gate_envelope(
                store,
                envelope_id=envelope_id,
                lane_id="v3_journal_ingest",
                execution_status="completed",
                postcheck={"boundary_true": False},
                result_summary={"entry_count": len(result)},
            )
        return result
    except Exception as exc:
        if internal_envelope:
            complete_execution_gate_envelope(
                store,
                envelope_id=envelope_id,
                lane_id="v3_journal_ingest",
                execution_status="failed",
                postcheck={"boundary_true": False},
                result_summary={"error_code": type(exc).__name__},
            )
        raise


def query_journal(
    store: MemoryOSStore,
    *,
    scope_class: str,
    tier: str = "",
    entry_id: str = "",
    limit: int = 20,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if scope_class not in {"recent", "tier", "entry", "all"}:
        raise ValueError("scope_class")
    if type(limit) is not int or limit <= 0 or limit > 100:
        raise ValueError("limit")
    if scope_class == "tier" and tier not in _TIERS:
        raise ValueError("tier")
    if scope_class == "entry" and not entry_id:
        raise ValueError("entry_id")

    queried_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()

    def mutate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        thoughts = [dict(item) for item in records if item.get("record_type") == "thought"]
        if scope_class == "tier":
            result = [item for item in thoughts if item.get("tier") == tier]
        elif scope_class == "entry":
            result = [item for item in thoughts if item.get("entry_id") == entry_id]
        elif scope_class == "recent":
            result = sorted(thoughts, key=lambda item: str(item.get("born_at") or ""), reverse=True)
        else:
            result = thoughts
        result = result[:limit]
        count = len(result)
        trace = {
            "record_type": "query_trace",
            "trace_id": "wndq_" + uuid4().hex,
            "queried_at": queried_at,
            "scope_class": scope_class,
            "result_count_bucket": "0" if count == 0 else "1-5" if count <= 5 else "6+",
        }
        _rewrite_records_under_lock(wandering_journal_path(store), [*records, trace])
        return [*records, trace], result

    return _mutate_journal(store, mutate, callback_performs_write=True)


def mutate_thought(
    store: MemoryOSStore,
    entry_id: str,
    updater: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    def mutate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        found: dict[str, Any] | None = None
        updated_records: list[dict[str, Any]] = []
        for item in records:
            if item.get("record_type") == "thought" and str(item.get("entry_id") or "") == str(entry_id):
                if found is not None:
                    raise ValueError("entry_not_unique")
                found = updater(dict(item))
                updated_records.append(found)
            else:
                updated_records.append(item)
        if found is None:
            raise ValueError("entry_not_found")
        return updated_records, found

    return _mutate_journal(store, mutate)


def _validate_and_build_entry(
    raw: dict[str, Any],
    *,
    packet: dict[str, Any],
    allowed_refs: set[str],
    born_at: str,
    expires_at: str,
    max_entry_chars: int,
    max_lineage_hops: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("entry_not_object")
    tier = str(raw.get("tier") or "")
    requested_fate = str(raw.get("requested_fate") or "")
    if tier not in _TIERS or requested_fate not in _REQUESTED:
        raise ValueError("tier_or_requested_fate")
    if tier == "claim" and requested_fate == "share":
        raise ValueError("claim_cannot_share")
    if tier != "claim" and requested_fate == "propose":
        raise ValueError("non_claim_cannot_propose")
    content = str(raw.get("content") or "").strip()
    if not content or len(content) > max_entry_chars:
        raise ValueError("content_length")
    concept_key = str(raw.get("concept_key") or "").strip()
    if not concept_key or len(concept_key) > 160:
        raise ValueError("concept_key")
    refs_value = raw.get("provenance_refs")
    if not isinstance(refs_value, list):
        raise ValueError("provenance_refs")
    refs = sorted({str(item).strip() for item in refs_value if str(item).strip()})
    if not refs or any(ref not in allowed_refs for ref in refs):
        raise ValueError("provenance_not_in_packet")
    if not any(not ref.startswith("journal:") for ref in refs):
        raise ValueError("non_journal_root_required")
    lineage_hop = raw.get("lineage_hop", 0)
    if type(lineage_hop) is not int or lineage_hop < 0 or lineage_hop > max_lineage_hops:
        raise ValueError("lineage_hop")

    lineage_payload = "|".join([str(packet["snapshot_id"]), *refs, concept_key.casefold()])
    content_hash = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    outlet_status = "queued" if requested_fate in {"share", "propose"} else "none"
    record: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "record_type": "thought",
        "entry_id": "wnd_" + uuid4().hex,
        "thought_lineage_id": "wln_" + hashlib.sha256(lineage_payload.encode("utf-8")).hexdigest()[:32],
        "lineage_hop": lineage_hop,
        "tier": tier,
        "epistemic_status": "private_uncommitted",
        "provenance_refs": refs,
        "body_snapshot_id": str(packet["snapshot_id"]),
        "concept_key": concept_key,
        "content": content,
        "content_hash": content_hash,
        "born_at": born_at,
        "expires_at": expires_at,
        "requested_fate": requested_fate,
        "outlet_status": outlet_status,
        "outlet_claimed_at": None,
        "outlet_result": None,
        "fate": "pending",
        "fate_at": None,
        "fate_ref": None,
    }
    for field in _OPTIONAL_TEXT_FIELDS:
        value = raw.get(field)
        record[field] = None if value is None else str(value).strip()[:max_entry_chars] or None
    return record


def _mutate_journal(
    store: MemoryOSStore,
    callback: Callable[[list[dict[str, Any]]], tuple[list[dict[str, Any]], T]],
    *,
    callback_performs_write: bool = False,
) -> T:
    path = wandering_journal_path(store)
    with locked_jsonl_file(path) as target:
        records = _read_strict_records(target)
        updated, result = callback(records)
        if not callback_performs_write:
            _rewrite_records_under_lock(target, updated)
        return result


def _read_strict_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("journal_non_object")
        result.append(value)
    return result


def _rewrite_records_under_lock(target: Path, records: list[dict[str, Any]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    blob = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records)
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
