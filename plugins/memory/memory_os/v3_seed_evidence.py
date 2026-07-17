"""V3 observation-only daily seed-edge evidence product.

This lane reads the MemorySources attribution ledger and emits bounded metadata
only.  It never invokes a model, injects context, or enables V3 wandering.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .execution_gate import (
    complete_execution_gate_envelope,
    resolve_execution_gate_permit,
    start_execution_gate_envelope,
)
from .jsonl_io import append_jsonl_locked, read_jsonl
from .memory_sources import read_memory_source_records
from .source_ids import SYNTHETIC_GUARD_IDS, filter_safe_source_id_values

DAILY_SCHEMA_VERSION = "memory-os.v3_seed_edges_daily.v0"
SNAPSHOT_SCHEMA_VERSION = "memory-os.v3_seed_evidence_snapshot.v0"
LANE_ID = "v3_seed_evidence"
_ALLOWED_TRAFFIC_CLASSES = {"production", "test", "shadow", "backfill", "synthetic"}


def v3_seed_edges_daily_path(store: Any) -> Path:
    return store.roots.memory_os_root / "system" / "v3_seed_edges_daily.jsonl"


def v3_seed_evidence_snapshot_path(store: Any) -> Path:
    return store.roots.memory_os_root / "system" / "v3_seed_evidence_snapshot.json"


def run_v3_seed_evidence_cycle(
    store: Any,
    *,
    target_date: date | str | None = None,
    now: datetime | None = None,
    max_edges: int = 10_000,
    min_coverage_ratio: float = 1.0,
    require_shared_entity: bool = True,
    reconstructed: bool = False,
    execution_gate_envelope_id: str = "",
) -> dict[str, Any]:
    """Build one exact UTC-day product and its 30-day readiness snapshot."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # BB.6-2: trigger provenance (mirrors exposure_rollup.py Fix 3) — only a
    # process launched under the cron ExecutionGate wrapper
    # (memory_os_execution_gate_runner.py) has this env var set. Basing the
    # signal on the OS environment — not the execution_gate_envelope_id
    # parameter — means a manual/direct call cannot forge "natural_cron" by
    # passing a fabricated envelope id.
    trigger_class = "natural_cron" if os.environ.get("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID") else "manual"
    natural_date = _coerce_date(target_date) if target_date is not None else current.date() - timedelta(days=1)
    window_start = datetime.combine(natural_date, datetime.min.time(), tzinfo=timezone.utc)
    window_end = window_start + timedelta(days=1)
    max_edges = max(0, int(max_edges))
    min_coverage_ratio = min(1.0, max(0.0, float(min_coverage_ratio)))

    all_records = read_memory_source_records(store.roots, limit=1_000_000)
    indexed_day_records: list[tuple[int, dict[str, Any]]] = []
    for offset, record in enumerate(all_records):
        created_at = _parse_datetime(record.get("created_at"))
        if created_at is not None and window_start <= created_at < window_end:
            indexed_day_records.append((offset, record))

    input_records = [record for _, record in indexed_day_records]
    production_records: list[dict[str, Any]] = []
    excluded_traffic_count = 0
    unclassified_traffic_count = 0
    for record in input_records:
        traffic_class = str(record.get("traffic_class") or "").strip()
        is_natural = record.get("natural_production") is True
        if traffic_class == "production" and is_natural:
            production_records.append(record)
            continue
        excluded_traffic_count += 1
        if traffic_class not in _ALLOWED_TRAFFIC_CLASSES or "natural_production" not in record:
            unclassified_traffic_count += 1

    offsets = [offset for offset, _ in indexed_day_records]
    source_cursor_contiguous = not offsets or offsets == list(range(offsets[0], offsets[-1] + 1))
    record_ids = [str(record.get("record_id") or "") for record in input_records]
    if any(not record_id for record_id in record_ids) or len(record_ids) != len(set(record_ids)):
        source_cursor_contiguous = False

    co_selected: Counter[tuple[str, str]] = Counter()
    source_class_distribution: Counter[str] = Counter()
    safe_refs_seen: set[str] = set()
    privacy_source_violation_count = 0
    canonical_inputs: list[dict[str, Any]] = []
    for record in production_records:
        selected_refs: set[str] = set()
        canonical_sections: list[list[str]] = []
        selected_value = record.get("selected")
        selected: list[Any] = selected_value if isinstance(selected_value, list) else []
        for section in selected:
            if not isinstance(section, dict):
                continue
            source_class_distribution[str(section.get("source_class") or "unknown")] += 1
            raw_ids_value = section.get("source_ids")
            raw_ids: list[Any] = raw_ids_value if isinstance(raw_ids_value, list) else []
            safe_ids = filter_safe_source_id_values(raw_ids)
            privacy_source_violation_count += max(0, len({str(item) for item in raw_ids}) - len(safe_ids))
            usable = sorted(ref for ref in safe_ids if ref not in SYNTHETIC_GUARD_IDS)
            selected_refs.update(usable)
            canonical_sections.append(usable)
        ordered = sorted(selected_refs)
        safe_refs_seen.update(ordered)
        for left, right in combinations(ordered, 2):
            co_selected[(left, right)] += 1
        canonical_inputs.append(
            {
                "record_id": str(record.get("record_id") or ""),
                "created_at": str(record.get("created_at") or ""),
                "selected_source_ids": ordered,
                "selected_sections": canonical_sections,
            }
        )

    shared_status, shared_entity = _shared_entity_edges(store, safe_refs_seen)
    all_edges = _edge_records(co_selected, kind="co_selected") + _edge_records(shared_entity, kind="shared_entity")
    all_edges.sort(key=lambda edge: (-int(edge["count"]), str(edge["kind"]), str(edge["from"]), str(edge["to"])))
    exact_edge_count = len(all_edges)
    stored_edges = all_edges[:max_edges]
    truncation_count = exact_edge_count - len(stored_edges)
    coverage_ratio = 1.0 if exact_edge_count == 0 else len(stored_edges) / exact_edge_count

    conservation_passes = len(input_records) == len(production_records) + excluded_traffic_count
    invalid_reasons: list[str] = []
    if window_end > current:
        invalid_reasons.append("natural_day_incomplete")
    if not production_records:
        invalid_reasons.append("no_natural_production_input")
    if unclassified_traffic_count:
        invalid_reasons.append("unclassified_traffic_present")
    if not source_cursor_contiguous:
        invalid_reasons.append("source_cursor_not_contiguous")
    if privacy_source_violation_count:
        invalid_reasons.append("privacy_or_source_id_violation")
    if truncation_count:
        invalid_reasons.append("edge_storage_cap_exceeded")
    if coverage_ratio < min_coverage_ratio:
        invalid_reasons.append("coverage_below_threshold")
    if not conservation_passes:
        invalid_reasons.append("conservation_failed")
    if require_shared_entity and shared_status != "available":
        invalid_reasons.append(f"shared_entity_{shared_status}")

    rebuild_digest = "sha256:" + hashlib.sha256(
        json.dumps(canonical_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    existing = read_jsonl(v3_seed_edges_daily_path(store))
    latest_same_day = next(
        (row for row in reversed(existing) if str(row.get("natural_date") or "") == natural_date.isoformat()),
        None,
    )
    if latest_same_day and str(latest_same_day.get("rebuild_digest") or "") == rebuild_digest:
        return {
            "schema_version": DAILY_SCHEMA_VERSION,
            "status": "ok",
            "skipped": True,
            "reason": "daily_product_unchanged",
            "valid": bool(latest_same_day.get("valid")),
            "daily_record": latest_same_day,
            "snapshot": build_v3_seed_evidence_snapshot(store, daily_records=existing),
        }

    envelope, envelope_id, gate_error = _resolve_or_start_gate(
        store,
        execution_gate_envelope_id=execution_gate_envelope_id,
        natural_date=natural_date.isoformat(),
    )
    if gate_error:
        return {"schema_version": DAILY_SCHEMA_VERSION, "status": "error", "skipped": False, "code": gate_error}

    daily_record = {
        "schema_version": DAILY_SCHEMA_VERSION,
        "record_id": f"v3seed_{natural_date.strftime('%Y%m%d')}_{uuid4().hex[:10]}",
        "created_at": current.isoformat().replace("+00:00", "Z"),
        "natural_date": natural_date.isoformat(),
        "timezone": "UTC",
        "window_start": window_start.isoformat().replace("+00:00", "Z"),
        "window_end": window_end.isoformat().replace("+00:00", "Z"),
        "source_offset_start": offsets[0] if offsets else len(all_records),
        "source_offset_end": offsets[-1] + 1 if offsets else len(all_records),
        "source_cursor_start_record_id": record_ids[0] if record_ids else "",
        "source_cursor_end_record_id": record_ids[-1] if record_ids else "",
        "source_cursor_contiguous": source_cursor_contiguous,
        "input_record_count": len(input_records),
        "natural_production_record_count": len(production_records),
        "excluded_traffic_count": excluded_traffic_count,
        "unclassified_traffic_count": unclassified_traffic_count,
        "source_class_distribution": dict(sorted(source_class_distribution.items())),
        "edges": stored_edges,
        "exact_edge_count": exact_edge_count,
        "stored_edge_count": len(stored_edges),
        "truncation_count": truncation_count,
        "coverage_ratio": coverage_ratio,
        "shared_entity_status": shared_status,
        "privacy_source_violation_count": privacy_source_violation_count,
        "conservation_passes": conservation_passes,
        "reconstructed": bool(reconstructed),
        "rebuild_digest": rebuild_digest,
        "valid": not invalid_reasons,
        "invalid_reasons": invalid_reasons,
        "execution_gate_envelope_id": envelope_id,
        "trigger_class": trigger_class,
    }

    try:
        append_jsonl_locked(v3_seed_edges_daily_path(store), daily_record)
        all_daily = existing + [daily_record]
        snapshot = build_v3_seed_evidence_snapshot(store, daily_records=all_daily)
        _atomic_write_json(v3_seed_evidence_snapshot_path(store), snapshot)
    except Exception as exc:
        if envelope is not None:
            _complete_gate(store, envelope_id, "error", {"error_type": type(exc).__name__})
        return {
            "schema_version": DAILY_SCHEMA_VERSION,
            "status": "error",
            "skipped": False,
            "code": "seed_evidence_write_failed",
            "error_type": type(exc).__name__,
        }

    if envelope is not None:
        complete_error = _complete_gate(
            store,
            envelope_id,
            "ok",
            {"valid": bool(daily_record["valid"]), "natural_date": natural_date.isoformat()},
        )
        if complete_error:
            return {
                "schema_version": DAILY_SCHEMA_VERSION,
                "status": "error",
                "skipped": False,
                "code": complete_error,
                "daily_record": daily_record,
                "snapshot": snapshot,
            }

    return {
        "schema_version": DAILY_SCHEMA_VERSION,
        "status": "ok",
        "skipped": False,
        "valid": bool(daily_record["valid"]),
        "daily_record": daily_record,
        "snapshot": snapshot,
    }


def build_v3_seed_evidence_snapshot(
    store: Any,
    *,
    daily_records: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = list(daily_records) if daily_records is not None else read_jsonl(v3_seed_edges_daily_path(store))
    latest_by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        natural_date = str(row.get("natural_date") or "")
        if not natural_date:
            continue
        previous = latest_by_date.get(natural_date)
        if previous is None or str(row.get("created_at") or "") >= str(previous.get("created_at") or ""):
            latest_by_date[natural_date] = row
    # BB.6-2: the 30-day activation-readiness gate must only count days
    # produced by the cron ExecutionGate wrapper — a manual/backfill run of
    # this lane must not be able to inflate consecutive_valid_day_count or
    # mark activation_evidence_ready early (mirrors exposure_rollup.py Fix 3's
    # natural_cron gating). Rows written before trigger_class existed are
    # visible via legacy_unmarked_day_count but never counted as natural.
    natural_by_date = {
        natural_date: row for natural_date, row in latest_by_date.items()
        if row.get("trigger_class") == "natural_cron"
    }
    legacy_unmarked_day_count = sum(1 for row in latest_by_date.values() if "trigger_class" not in row)
    valid_dates = sorted(_coerce_date(value) for value, row in natural_by_date.items() if row.get("valid") is True)
    longest: list[date] = []
    current_run: list[date] = []
    for item in valid_dates:
        if current_run and item != current_run[-1] + timedelta(days=1):
            if len(current_run) > len(longest):
                longest = current_run
            current_run = []
        current_run.append(item)
    if len(current_run) > len(longest):
        longest = current_run
    coverage_values = [float(row.get("coverage_ratio") or 0.0) for row in natural_by_date.values() if row.get("valid") is True]
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "valid_day_count": len(valid_dates),
        "consecutive_valid_day_count": len(longest),
        "activation_evidence_ready": len(longest) >= 30,
        "first_valid_date": longest[0].isoformat() if longest else "",
        "last_valid_date": longest[-1].isoformat() if longest else "",
        "minimum_valid_coverage_ratio": min(coverage_values) if coverage_values else 0.0,
        "invalid_day_count": sum(1 for row in latest_by_date.values() if row.get("valid") is not True),
        "latest_natural_date": max(latest_by_date) if latest_by_date else "",
        "legacy_unmarked_day_count": legacy_unmarked_day_count,
    }


def _shared_entity_edges(store: Any, refs: set[str]) -> tuple[str, Counter[tuple[str, str]]]:
    if not _entity_index_is_enabled(store):
        return "disabled", Counter()
    if not store.roots.index_path.exists():
        return "unavailable", Counter()
    canonical_by_record_id = {
        ref.split(":", 1)[1]: ref
        for ref in refs
        if ref.startswith("crystallized:") and ":" in ref
    }
    if not canonical_by_record_id:
        return "available", Counter()
    try:
        with sqlite3.connect(store.roots.index_path) as conn:
            rows = conn.execute("select entity_id, record_id from entity_index").fetchall()
    except sqlite3.Error:
        return "error", Counter()
    by_entity: dict[str, set[str]] = defaultdict(set)
    for entity_id, record_id in rows:
        ref = canonical_by_record_id.get(str(record_id))
        if ref:
            by_entity[str(entity_id)].add(ref)
    edges: Counter[tuple[str, str]] = Counter()
    for linked_refs in by_entity.values():
        for left, right in combinations(sorted(linked_refs), 2):
            edges[(left, right)] += 1
    return "available", edges


def _entity_index_is_enabled(store: Any) -> bool:
    try:
        from .knob_overrides import resolve_knob

        return resolve_knob("entity_index_enabled", default=False, roots=store.roots) is True
    except Exception:
        return False


def _edge_records(counter: Counter[tuple[str, str]], *, kind: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for (left, right), count in counter.items():
        digest = hashlib.sha256(f"{kind}\0{left}\0{right}".encode("utf-8")).hexdigest()
        records.append(
            {
                "edge_ref": f"v3edge:sha256:{digest}",
                "from": left,
                "to": right,
                "kind": kind,
                "count": int(count),
            }
        )
    return records


def _resolve_or_start_gate(
    store: Any,
    *,
    execution_gate_envelope_id: str,
    natural_date: str,
) -> tuple[dict[str, Any] | None, str, str]:
    if execution_gate_envelope_id:
        resolution = resolve_execution_gate_permit(
            store.roots,
            envelope_id=execution_gate_envelope_id,
            lane_id=LANE_ID,
            risk_class="local_helper",
            require_fresh=True,
            require_unused=True,
        )
        if resolution.get("status") != "valid":
            return None, "", str(resolution.get("reason") or "execution_gate_permit_invalid")
        return None, execution_gate_envelope_id, ""
    try:
        envelope = start_execution_gate_envelope(
            store,
            lane_id=LANE_ID,
            trigger_surface="direct_helper",
            risk_class="observation",
            human_approval_required=False,
            why_no_human_approval="metadata-only local observation product",
            scope={"source": "memory_sources", "natural_date": natural_date},
            boundary={
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_unapproved_crystallized_approval": False,
            },
        )
    except Exception as exc:
        return None, "", f"execution_gate_start_failed:{type(exc).__name__}"
    return envelope, str(envelope.get("execution_gate_envelope_id") or ""), ""


def _complete_gate(store: Any, envelope_id: str, status: str, postcheck: dict[str, Any]) -> str:
    try:
        complete_execution_gate_envelope(
            store,
            envelope_id=envelope_id,
            lane_id=LANE_ID,
            execution_status=status,
            postcheck=postcheck,
        )
    except Exception as exc:
        return f"execution_gate_complete_failed:{type(exc).__name__}"
    return ""


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    """Best-effort directory fsync after an atomic replace.

    POSIX keeps the pre-existing durability semantics: open a directory
    descriptor and fsync it, propagating fsync errors.  Platforms that cannot
    open directory descriptors (Windows raises PermissionError from os.open)
    skip the directory fsync; the file itself is already flushed+fsynced and
    os.replace stays atomic.
    """

    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except (NotImplementedError, OSError):
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _coerce_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
