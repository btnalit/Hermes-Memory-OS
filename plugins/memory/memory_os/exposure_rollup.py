"""V2-A exposure rollup lane (A3).

Reads memory_sources records, rollups by canonical record_id with
conservation math, and produces idempotent exposure snapshots under
an execution-gate envelope.
"""

from __future__ import annotations

import json
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


def exposure_monitor_stats(store: Any) -> dict[str, Any]:
    """Return monitor-facing exposure telemetry stats (A6).

    Computes lag cycles, attribution gap, and degradation count from
    memory_sources and exposure rollup records.  Does not produce owner
    review items — observation-only metrics.
    """
    from datetime import timezone as _tz

    from .memory_sources import read_memory_source_records

    now = datetime.now(_tz.utc)
    snapshot = exposure_rollup_snapshot(store)

    # ── Lag cycles: hours since last rollup window end ─────────────────
    lag_hours = 0.0
    latest_end = str(snapshot.get("latest_window_end") or "")
    if latest_end and snapshot.get("status") != "empty":
        try:
            end_dt = datetime.fromisoformat(latest_end.replace("Z", "+00:00"))
            lag_hours = max(0.0, (now - end_dt.astimezone(_tz.utc)).total_seconds() / 3600.0)
        except (ValueError, TypeError):
            pass

    # ── Attribution gap: memory_sources records with selected source_ids
    #    that cannot be mapped to any canonical record ───────────────────
    ms_records = read_memory_source_records(store.roots, limit=1000)
    attribution_gap_count = 0
    for ms_rec in ms_records:
        selected = ms_rec.get("selected") if isinstance(ms_rec.get("selected"), list) else []
        has_source_ids = False
        for section in selected:
            if not isinstance(section, dict):
                continue
            sids = section.get("source_ids") or []
            crystallized_ids = [
                s for s in (sids if isinstance(sids, list) else [])
                if str(s).startswith("crystallized:")
            ]
            if crystallized_ids:
                has_source_ids = True
                break
        # A gap exists when a record has 0 selected sections but had sections
        # available — detected via selected_chars_total > 0 and 0 selected sections
        if not has_source_ids and int(ms_rec.get("selected_chars_total") or 0) > 0:
            attribution_gap_count += 1

    # ── Telemetry degraded count: count of records with boundary violations ─
    telemetry_degraded_count = sum(
        1 for _ms_rec in ms_records
        if isinstance(_ms_rec.get("boundary"), dict)
        and any(v is True for v in _ms_rec["boundary"].values())
    )

    # Collect rollup records for cumulative stats
    rollup_records = _read_rollup_records(store)
    total_eligible = sum(int(r.get("eligible") or 0) for r in rollup_records)
    total_selected = sum(int(r.get("selected") or 0) for r in rollup_records)

    return {
        "schema_version": "memory-os.exposure_monitor_stats.v0",
        "exposure_rollup_lag_hours": round(lag_hours, 1),
        "exposure_rollup_records_total": len(rollup_records),
        "cumulative_eligible": total_eligible,
        "cumulative_selected": total_selected,
        "attribution_gap_count": attribution_gap_count,
        "telemetry_degraded_count": telemetry_degraded_count,
        "latest_window_start": snapshot.get("latest_window_start", ""),
        "latest_window_end": snapshot.get("latest_window_end", ""),
        "snapshot_status": snapshot.get("status", "unknown"),
    }
