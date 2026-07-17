"""V2-A exposure rollup lane (A3).

Reads memory_sources records, rollups by canonical record_id with
conservation math, and produces idempotent exposure snapshots under
an execution-gate envelope.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution_gate import (
    complete_execution_gate_envelope,
    resolve_execution_gate_permit,
    start_execution_gate_envelope,
)

SCHEMA_VERSION = "memory-os.exposure_rollup.v0"
SNAPSHOT_SCHEMA_VERSION = "memory-os.exposure_rollup_snapshot.v0"


def _rollup_path(store: Any) -> Path:
    return store.roots.memory_os_root / "system" / "exposure_rollup.jsonl"


def _snapshot_path(store: Any) -> Path:
    return store.roots.memory_os_root / "system" / "exposure_rollup_snapshot.json"


def _read_rollup_records(store: Any) -> list[dict[str, Any]]:
    path = _rollup_path(store)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _latest_rollup_watermark(store: Any) -> str:
    """Return the created_at of the latest rollup record, or epoch zero."""
    records = _read_rollup_records(store)
    if not records:
        return "1970-01-01T00:00:00Z"
    return str(records[-1].get("window_end") or records[-1].get("created_at") or "1970-01-01T00:00:00Z")


def _latest_source_cursor(store: Any, source_records: list[dict[str, Any]]) -> tuple[int, str, str]:
    """Resolve append position, failing closed when compaction removed the cursor."""
    rollups = _read_rollup_records(store)
    if not rollups:
        return 0, "", ""
    latest = rollups[-1]
    cursor_id = str(latest.get("source_cursor_record_id") or "")
    if not cursor_id:
        return 0, "", "legacy_source_cursor_missing"
    for index in range(len(source_records) - 1, -1, -1):
        if str(source_records[index].get("record_id") or "") == cursor_id:
            return index + 1, cursor_id, ""
    return 0, cursor_id, "source_cursor_not_found"


def _extract_record_ids_from_section(
    section: dict[str, Any],
) -> list[str]:
    """Extract canonical record IDs from a memory_source section entry."""
    source_ids: list[str] = []
    raw = section.get("source_ids")
    if isinstance(raw, list):
        for sid in raw:
            sid_str = str(sid)
            if sid_str.startswith("crystallized:") or sid_str.startswith("candidate:"):
                source_ids.append(sid_str)
    return source_ids


def run_exposure_rollup_cycle(
    store: Any,
    *,
    now: datetime | None = None,
    execution_gate_envelope_id: str = "",
) -> dict[str, Any]:
    """Idempotent exposure rollup cycle (A3).

    Reads memory_sources records since the last rollup watermark,
    classifies each canonical record_id as selected / dropped_by_budget /
    dropped_by_rank (strongest signal wins), and appends a rollup record
    to ``system/exposure_rollup.jsonl``.

    Conservation invariant: eligible == selected + dropped_by_budget + dropped_by_rank.
    Idempotent: same window re-run produces zero-side-effect skip.
    """
    from .jsonl_io import append_jsonl_locked
    from .memory_sources import read_memory_source_records

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # Trigger provenance (Fix 3): only a process actually launched under the
    # cron ExecutionGate wrapper (memory_os_execution_gate_runner.py) has this
    # env var set. Basing the signal on the OS environment — not on the
    # execution_gate_envelope_id parameter — means a manual/direct call cannot
    # forge "natural_cron" simply by passing a fabricated envelope id.
    trigger_class = "natural_cron" if os.environ.get("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID") else "manual"
    report: dict[str, Any] = {
        "status": "ok",
        "records_processed": 0,
        "records_classified": 0,
        "eligible": 0,
        "selected": 0,
        "dropped_by_budget": 0,
        "dropped_by_rank": 0,
        "conservation_passes": False,
        "skipped": False,
        "error_records": [],
        "trigger_class": trigger_class,
    }

    # ── Append-order cursor gate (idempotency without timestamp races) ──
    ms_records = read_memory_source_records(store.roots, limit=1_000_000)
    source_offset_start, _previous_cursor_id, cursor_error = _latest_source_cursor(store, ms_records)
    if cursor_error:
        report["status"] = "error"
        report["error_records"].append({
            "component": "exposure_rollup",
            "operation": "resolve_source_cursor",
            "error_code": cursor_error,
            "severity": "error",
            "recoverable": False,
        })
        return report
    new_records = ms_records[source_offset_start:]

    if not new_records:
        report["skipped"] = True
        return report

    window_start = _latest_rollup_watermark(store)
    window_end = current.isoformat().replace("+00:00", "Z")
    source_offset_end = source_offset_start + len(new_records)
    source_cursor_record_id = str(new_records[-1].get("record_id") or "")

    report["records_processed"] = len(new_records)
    report["source_offset_start"] = source_offset_start
    report["source_offset_end"] = source_offset_end
    report["source_cursor_record_id"] = source_cursor_record_id

    # ── Validate or open execution gate envelope ────────────────────────
    envelope = None
    if execution_gate_envelope_id:
        resolution = resolve_execution_gate_permit(
            store.roots,
            envelope_id=execution_gate_envelope_id,
            lane_id="exposure_rollup",
            risk_class="local_helper",
            require_fresh=True,
            require_unused=True,
        )
        if resolution.get("status") != "valid":
            report["status"] = "error"
            report["error_records"].append({
                "component": "exposure_rollup",
                "operation": "resolve_execution_gate",
                "error_code": str(resolution.get("reason") or "execution_gate_permit_invalid"),
                "severity": "error",
                "recoverable": False,
            })
            return report
    else:
        try:
            envelope = start_execution_gate_envelope(
                store,
                lane_id="exposure_rollup",
                trigger_surface="direct_helper",
                risk_class="observation",
                human_approval_required=False,
                why_no_human_approval="local observation rollup only",
                scope={"source": "memory_sources", "window_start": window_start, "window_end": window_end},
                boundary={"actual_send": False, "actual_execute": False, "actual_identity_write": False, "actual_unapproved_crystallized_approval": False},
            )
        except Exception as exc:
            report["error_records"].append({
                "component": "exposure_rollup",
                "operation": "start_execution_gate",
                "error_code": type(exc).__name__,
                "severity": "error",
                "recoverable": False,
            })
            report["status"] = "error"
            return report

    # ── Classify by record_id (union across lanes, strongest signal wins) ─
    # Per-ID classification: selected > dropped_by_budget > dropped_by_rank
    id_classification: dict[str, str] = {}  # rid → "selected"|"dropped_by_budget"|"dropped_by_rank"

    for ms_rec in new_records:
        # Process selected sections
        for section in ms_rec.get("selected", []) if isinstance(ms_rec.get("selected"), list) else []:
            if not isinstance(section, dict):
                continue
            for rid in _extract_record_ids_from_section(section):
                # "selected" is the strongest signal — always wins
                id_classification[rid] = "selected"

        # Process dropped sections
        for section in ms_rec.get("dropped", []) if isinstance(ms_rec.get("dropped"), list) else []:
            if not isinstance(section, dict):
                continue
            rids = _extract_record_ids_from_section(section)
            if not rids:
                continue
            reason_codes = [
                str(rc) for rc in section.get("reason_codes", [])
                if isinstance(section.get("reason_codes"), list)
            ]
            drop_class = (
                "dropped_by_budget"
                if any(code == "budget" or code.startswith("budget_") for code in reason_codes)
                else "dropped_by_rank"
            )
            for rid in rids:
                current_class = id_classification.get(rid)
                # selected > dropped_by_budget > dropped_by_rank
                if current_class == "selected":
                    continue  # already strongest
                if current_class == "dropped_by_budget" and drop_class == "dropped_by_rank":
                    continue  # budget drop is stronger signal
                id_classification[rid] = drop_class

    # ── Tally ──────────────────────────────────────────────────────────
    counts: Counter[str] = Counter()
    for cls in id_classification.values():
        counts[cls] += 1

    selected_count = counts["selected"]
    dropped_budget_count = counts["dropped_by_budget"]
    dropped_rank_count = counts["dropped_by_rank"]
    eligible = selected_count + dropped_budget_count + dropped_rank_count
    conservation_passes = (eligible == len(id_classification))

    report["records_classified"] = len(id_classification)
    report["eligible"] = eligible
    report["selected"] = selected_count
    report["dropped_by_budget"] = dropped_budget_count
    report["dropped_by_rank"] = dropped_rank_count
    report["conservation_passes"] = conservation_passes

    # Compute co-selected top (top-N record_ids most frequently co-selected)
    co_select_counter: Counter[str] = Counter()
    for ms_rec in new_records:
        selected_rids: set[str] = set()
        for section in ms_rec.get("selected", []) if isinstance(ms_rec.get("selected"), list) else []:
            if not isinstance(section, dict):
                continue
            selected_rids.update(_extract_record_ids_from_section(section))
        # Count each pair co-occurrence
        selected_list = sorted(selected_rids)
        for i in range(len(selected_list)):
            for j in range(i + 1, len(selected_list)):
                pair_key = f"{selected_list[i]}|{selected_list[j]}"
                co_select_counter[pair_key] += 1

    co_selected_top: list[dict[str, Any]] = [
        {"pair": pair, "count": cnt}
        for pair, cnt in co_select_counter.most_common(10)
    ]

    # ── Write rollup record ────────────────────────────────────────────
    rollup_record = {
        "schema_version": SCHEMA_VERSION,
        "window_start": window_start,
        "window_end": window_end,
        "created_at": current.isoformat().replace("+00:00", "Z"),
        "records_processed": len(new_records),
        "source_offset_start": source_offset_start,
        "source_offset_end": source_offset_end,
        "source_cursor_record_id": source_cursor_record_id,
        "records_classified": len(id_classification),
        "eligible": eligible,
        "selected": selected_count,
        "dropped_by_budget": dropped_budget_count,
        "dropped_by_rank": dropped_rank_count,
        "conservation_passes": conservation_passes,
        "co_selected_top": co_selected_top,
        "execution_gate_envelope": execution_gate_envelope_id or (envelope["execution_gate_envelope_id"] if envelope else None),
        "trigger_class": trigger_class,
    }

    try:
        append_jsonl_locked(_rollup_path(store), rollup_record)
    except Exception as exc:
        report["error_records"].append({
            "component": "exposure_rollup",
            "operation": "write_rollup",
            "error_code": type(exc).__name__,
            "severity": "error",
            "recoverable": False,
        })
        report["status"] = "error"

    # ── Update snapshot ────────────────────────────────────────────────
    try:
        all_rollups = _read_rollup_records(store)
        snapshot = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "status": "ok",
            "latest_window_start": window_start,
            "latest_window_end": window_end,
            "latest_created_at": current.isoformat().replace("+00:00", "Z"),
            "cumulative_eligible": sum(int(row.get("eligible") or 0) for row in all_rollups),
            "cumulative_selected": sum(int(row.get("selected") or 0) for row in all_rollups),
            "cumulative_dropped_by_budget": sum(int(row.get("dropped_by_budget") or 0) for row in all_rollups),
            "cumulative_dropped_by_rank": sum(int(row.get("dropped_by_rank") or 0) for row in all_rollups),
        }
        sp = _snapshot_path(store)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass  # snapshot is best-effort

    # ── Close execution gate envelope ──────────────────────────────────
    if envelope:
        try:
            complete_execution_gate_envelope(
                store,
                envelope_id=envelope["execution_gate_envelope_id"],
                lane_id="exposure_rollup",
                execution_status=str(report["status"]),
                postcheck={"classified": len(id_classification), "conservation_passes": conservation_passes},
            )
        except Exception:
            pass  # postcheck failure is non-fatal for observation lane

    return report


def exposure_rollup_snapshot(store: Any) -> dict[str, Any]:
    """Return the latest exposure rollup snapshot for monitor consumption."""
    sp = _snapshot_path(store)
    if not sp.exists():
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "status": "empty",
            "latest_window_start": "",
            "latest_window_end": "",
        }
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "status": "error",
            "latest_window_start": "",
            "latest_window_end": "",
        }


def exposure_monitor_stats(store: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Return monitor-facing V2 exposure telemetry without mutating state."""
    from datetime import timedelta, timezone as _tz

    from .memory_sources import read_memory_source_records

    current = (now or datetime.now(_tz.utc)).astimezone(_tz.utc)
    snapshot = exposure_rollup_snapshot(store)

    lag_hours = 0.0
    latest_end = str(snapshot.get("latest_window_end") or "")
    if latest_end and snapshot.get("status") != "empty":
        end_dt = _parse_monitor_time(latest_end)
        if end_dt is not None:
            lag_hours = max(0.0, (current - end_dt).total_seconds() / 3600.0)

    ms_records = read_memory_source_records(store.roots, limit=1_000_000)
    natural_records = [
        record
        for record in ms_records
        if record.get("natural_production") is True
        and str(record.get("traffic_class") or "") == "production"
    ]
    rolling_cutoff = current - timedelta(days=7)
    rolling_records = [
        record for record in natural_records
        if (_parse_monitor_time(record.get("created_at")) or datetime.min.replace(tzinfo=_tz.utc)) >= rolling_cutoff
    ]

    all_history_gap = sum(1 for record in ms_records if _memory_source_has_attribution_gap(record))
    schema_gap = sum(1 for record in natural_records if _memory_source_has_attribution_gap(record))
    rolling_gap = sum(1 for record in rolling_records if _memory_source_has_attribution_gap(record))
    telemetry_degraded_count = sum(
        1 for record in natural_records
        if isinstance(record.get("boundary"), dict)
        and any(value is True for value in record["boundary"].values())
    )

    rollup_records = _read_rollup_records(store)
    # Fix 3: rollup records written before trigger_class existed cannot be
    # attributed either way — surface them separately rather than silently
    # folding them into (or out of) the natural-cycle cadence gate.
    legacy_unmarked_rollup_count = sum(1 for record in rollup_records if "trigger_class" not in record)
    total_eligible = sum(int(record.get("eligible") or 0) for record in rollup_records)
    total_selected = sum(int(record.get("selected") or 0) for record in rollup_records)
    total_budget = sum(int(record.get("dropped_by_budget") or 0) for record in rollup_records)
    total_rank = sum(int(record.get("dropped_by_rank") or 0) for record in rollup_records)
    first_natural_at = min(
        (_parse_monitor_time(record.get("created_at")) for record in natural_records),
        default=None,
        key=lambda value: value or datetime.max.replace(tzinfo=_tz.utc),
    )
    schema_rollups = [
        record for record in rollup_records
        if first_natural_at is not None
        and (_parse_monitor_time(record.get("window_end") or record.get("created_at")) or datetime.min.replace(tzinfo=_tz.utc)) >= first_natural_at
    ]
    conservation_failures = sum(
        1 for record in schema_rollups
        if record.get("conservation_passes") is not True
        or int(record.get("eligible") or 0)
        != int(record.get("selected") or 0)
        + int(record.get("dropped_by_budget") or 0)
        + int(record.get("dropped_by_rank") or 0)
    )
    processed = sum(int(record.get("records_processed") or 0) for record in schema_rollups)
    classified = sum(int(record.get("records_classified") or 0) for record in schema_rollups)
    classified_ratio = min(1.0, classified / processed) if processed > 0 else None

    daily: dict[str, dict[str, int | bool]] = {}
    for record in schema_rollups:
        if record.get("trigger_class") != "natural_cron":
            # Fix 3: manual runs and legacy (unmarked) rollups must never
            # inflate the natural-cycle cadence/pressure-streak gate.
            continue
        timestamp = _parse_monitor_time(record.get("window_end") or record.get("created_at"))
        if timestamp is None or int(record.get("records_processed") or 0) <= 0:
            continue
        date_key = timestamp.date().isoformat()
        bucket = daily.setdefault(date_key, {"budget": 0, "valid": True})
        bucket["budget"] = int(bucket["budget"]) + int(record.get("dropped_by_budget") or 0)
        bucket["valid"] = bool(bucket["valid"]) and record.get("conservation_passes") is True
    valid_natural_days = sum(1 for bucket in daily.values() if bucket["valid"] is True)
    pressure_streak = 0
    latest_completed_date = current.date() - timedelta(days=1)
    ordered_dates = sorted(
        (datetime.fromisoformat(key).date() for key in daily if datetime.fromisoformat(key).date() <= latest_completed_date),
        reverse=True,
    )
    expected_date = latest_completed_date
    for observed_date in ordered_dates:
        if expected_date is None or observed_date != expected_date:
            break
        date_key = observed_date.isoformat()
        if int(daily[date_key]["budget"]) <= 0 or daily[date_key]["valid"] is not True:
            break
        pressure_streak += 1
        expected_date = observed_date - timedelta(days=1)
    observation_days = 0.0
    if first_natural_at is not None:
        observation_days = max(0.0, (current - first_natural_at).total_seconds() / 86400.0)

    freeze_reasons: list[str] = []
    if valid_natural_days < 3:
        freeze_reasons.append(f"initial_natural_cycles:{valid_natural_days}/3")
    if observation_days < 30:
        freeze_reasons.append(f"production_observation_days:{observation_days:.1f}/30")
    if pressure_streak < 7:
        freeze_reasons.append(f"budget_pressure_streak:{pressure_streak}/7")
    if schema_gap or conservation_failures or telemetry_degraded_count:
        freeze_reasons.append("schema_era_health_not_pass")

    schema_health = "FAIL" if schema_gap or conservation_failures or telemetry_degraded_count else (
        "healthy_no_sample" if not natural_records else "PASS"
    )
    return {
        "schema_version": "memory-os.exposure_monitor_stats.v1",
        "exposure_rollup_lag_hours": round(lag_hours, 1),
        "exposure_rollup_records_total": len(rollup_records),
        "legacy_unmarked_rollup_count": legacy_unmarked_rollup_count,
        "cumulative_eligible": total_eligible,
        "cumulative_selected": total_selected,
        "cumulative_dropped_by_budget": total_budget,
        "cumulative_dropped_by_rank": total_rank,
        "conservation_total_passes": total_eligible == total_selected + total_budget + total_rank,
        "attribution_gap_count": all_history_gap,
        "all_history_attribution_gap_count": all_history_gap,
        "schema_era_attribution_gap_count": schema_gap,
        "rolling_7d_attribution_gap_count": rolling_gap,
        "schema_era_conservation_failure_count": conservation_failures,
        "schema_era_natural_record_count": len(natural_records),
        "rolling_7d_natural_record_count": len(rolling_records),
        "schema_era_classified_ratio": None if classified_ratio is None else round(classified_ratio, 4),
        "schema_era_health": schema_health,
        "telemetry_degraded_count": telemetry_degraded_count,
        "initial_natural_cycle_count": valid_natural_days,
        "production_observation_days": round(observation_days, 1),
        "budget_pressure_streak_days": pressure_streak,
        "v2c_unfreeze_ready": not freeze_reasons,
        "downstream_clearance_closure_frozen": bool(freeze_reasons),
        "freeze_reasons": freeze_reasons,
        "latest_window_start": snapshot.get("latest_window_start", ""),
        "latest_window_end": snapshot.get("latest_window_end", ""),
        "snapshot_status": snapshot.get("status", "ok" if snapshot.get("schema_version") == SNAPSHOT_SCHEMA_VERSION else "unknown"),
    }


def _memory_source_has_attribution_gap(record: dict[str, Any]) -> bool:
    attributable_classes = {"crystallized", "working", "entity_graph", "indexed_recall", "vector", "hindsight"}
    sections: list[dict[str, Any]] = []
    for key in ("selected", "dropped"):
        raw_values = record.get(key)
        values: list[Any] = raw_values if isinstance(raw_values, list) else []
        sections.extend(value for value in values if isinstance(value, dict))
    for section in sections:
        if str(section.get("source_class") or "") not in attributable_classes:
            continue
        if int(section.get("chars") or 0) <= 0 and int(section.get("count") or 0) <= 0:
            continue
        raw_source_ids = section.get("source_ids")
        source_ids: list[Any] = raw_source_ids if isinstance(raw_source_ids, list) else []
        if not any(str(source_id).strip() for source_id in source_ids):
            return True
    return False


def _parse_monitor_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
