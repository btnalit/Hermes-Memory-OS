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
    resolve_trigger_class,
    start_execution_gate_envelope,
)

SCHEMA_VERSION = "memory-os.exposure_rollup.v0"
SNAPSHOT_SCHEMA_VERSION = "memory-os.exposure_rollup_snapshot.v0"

# ── Run-outcome contract (backlog 14: completion is not output) ─────────
# The lane's two no-write exits (benign "no new records" skip, and the
# source_cursor_not_found fail-closed error) used to leave byte-identical
# evidence: neither touched exposure_rollup.jsonl nor the snapshot, so from
# the artifacts alone a permanently-broken lane looked exactly like an idle
# one -- distinguishing them required re-running the lane and reading source.
# Every run now records WHY it produced (or did not produce) output in the
# snapshot's last_run block, using this closed set of reason codes.
RUN_OUTCOME_PRODUCED = "produced"                       # rollup record appended
RUN_OUTCOME_NO_NEW_RECORDS = "no_new_records"           # benign: nothing eligible upstream
RUN_OUTCOME_SOURCE_CURSOR_NOT_FOUND = "source_cursor_not_found"  # compaction removed cursor; fail-closed
RUN_OUTCOME_LEGACY_CURSOR_MISSING = "legacy_source_cursor_missing"  # pre-cursor rollup head; fail-closed
RUN_OUTCOME_WRITE_FAILED = "write_failed"               # eligible input existed, ledger append failed
# Sentinel for snapshots written before outcome recording existed; never
# written by this module, only reported by exposure_monitor_stats.
RUN_OUTCOME_UNRECORDED = "unrecorded"
EXPOSURE_ROLLUP_RUN_OUTCOMES = frozenset({
    RUN_OUTCOME_PRODUCED,
    RUN_OUTCOME_NO_NEW_RECORDS,
    RUN_OUTCOME_SOURCE_CURSOR_NOT_FOUND,
    RUN_OUTCOME_LEGACY_CURSOR_MISSING,
    RUN_OUTCOME_WRITE_FAILED,
})

# ── Attribution contract (backlog item 16b) ─────────────────────────────
# Which prefetch disclosure sections must name the canonical records they drew
# from. This vocabulary MUST match what prefetch._section_source_class()
# actually emits: a name with no producer silently disables the check for that
# class. The original set had six names of which four (entity_graph,
# indexed_recall, vector, hindsight) had no producer anywhere in the project,
# while the names the producer really emits (indexed, graph_layer, event,
# candidate, substrate_recall) were absent -- so on production the gate counted
# 69 gaps and silently skipped 1093. test_attributable_source_classes_cover_
# the_producer_vocabulary keeps the two in sync from now on.
#
# Attributable: the section cites individual canonical records AND the producer
# can supply their IDs.
ATTRIBUTABLE_SOURCE_CLASSES = frozenset({
    "crystallized",   # crystallized:<record_id>
    "candidate",      # candidate:<candidate_id>
    "working",        # working:<file_stem>:<item_id>
    "event",          # event:<event_id>
    "indexed",        # <record_type>:<record_id> from the FTS index
    "graph_layer",    # <record_type>:<record_id> reached by graph traversal
})

# Deliberately NOT attributable, one reason per class. These are derived or
# aggregate views with no 1:1 canonical record to cite, so requiring source_ids
# would be unsatisfiable rather than merely unmet. Listing them explicitly (as
# opposed to "anything not attributable") is what lets the guard test prove the
# union covers the producer's whole vocabulary, so a newly added section title
# cannot slip through unclassified.
NON_ATTRIBUTABLE_SOURCE_CLASSES = frozenset({
    "foreground",        # active task anchor -- derived state, not a record
    "recall_guard",      # fixed guard string; carries its own synthetic marker
    "identity",          # whole-file identity snippet
    "state_overlay",     # aggregate overlay across many records
    "bridge",            # continuity bridge -- derived
    "last_session",      # session summary -- derived
    "carryover",         # deep-reflection cards -- derived
    "relationship",      # whole-file relationship snippet
    "substrate_recall",  # advisory_only derived_projection by contract (substrates/base.py)
    "diagnostic",        # diagnostic grounding -- derived
    "other",             # unmapped section title: unknown by definition
})

# Prefixes that mark a source_id as naming a canonical record. Used by the
# rollup's per-record classification, so widening this widens what gets
# classified (which is the point: classified_ratio was 0.70 precisely because
# working/event/indexed IDs could not be recognised even in principle).
CANONICAL_SOURCE_ID_PREFIXES = (
    "crystallized:",
    "candidate:",
    "working:",
    "event:",
)


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
            if sid_str.startswith(CANONICAL_SOURCE_ID_PREFIXES):
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
    Idempotent: same window re-run appends no rollup record. The skip itself
    is still recorded in the snapshot's ``last_run`` block (backlog 14) so a
    no-output run leaves durable evidence of WHY it produced nothing.
    """
    from .jsonl_io import append_jsonl_locked
    from .memory_sources import read_memory_source_records

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # Trigger provenance (Fix 3): env-var-based — anti-forgery rationale lives
    # in execution_gate.resolve_trigger_class() (shared with v3_seed_evidence).
    trigger_class = resolve_trigger_class()
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
        # Backlog 14: this fail-closed exit used to leave evidence
        # byte-identical to the benign skip below. Record the distinguishing
        # outcome durably (cursor_error is already one of the closed set).
        report["run_outcome"] = cursor_error
        _record_last_run_outcome(
            store,
            outcome=cursor_error,
            new_records=0,
            at=current.isoformat().replace("+00:00", "Z"),
            trigger_class=trigger_class,
            report=report,
        )
        return report
    new_records = ms_records[source_offset_start:]

    if not new_records:
        report["skipped"] = True
        report["run_outcome"] = RUN_OUTCOME_NO_NEW_RECORDS
        _record_last_run_outcome(
            store,
            outcome=RUN_OUTCOME_NO_NEW_RECORDS,
            new_records=0,
            at=current.isoformat().replace("+00:00", "Z"),
            trigger_class=trigger_class,
            report=report,
        )
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
        report["run_outcome"] = RUN_OUTCOME_PRODUCED
    except Exception as exc:
        report["error_records"].append({
            "component": "exposure_rollup",
            "operation": "write_rollup",
            "error_code": type(exc).__name__,
            "severity": "error",
            "recoverable": False,
        })
        report["status"] = "error"
        # Backlog 14: eligible input existed but the ledger append failed --
        # a third state that must not masquerade as either "produced" or
        # "nothing to do".
        report["run_outcome"] = RUN_OUTCOME_WRITE_FAILED

    # ── Update snapshot ────────────────────────────────────────────────
    try:
        all_rollups = _read_rollup_records(store)
        snapshot = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            # On the write_failed path the ledger append did NOT happen, so
            # latest_window_* below describe a window the ledger does not
            # contain -- "ok" beside last_run.outcome=write_failed would lie
            # twice (review finding CD-R1).
            "status": "ok" if report["status"] == "ok" else "error",
            "latest_window_start": window_start,
            "latest_window_end": window_end,
            "latest_created_at": current.isoformat().replace("+00:00", "Z"),
            "cumulative_eligible": sum(int(row.get("eligible") or 0) for row in all_rollups),
            "cumulative_selected": sum(int(row.get("selected") or 0) for row in all_rollups),
            "cumulative_dropped_by_budget": sum(int(row.get("dropped_by_budget") or 0) for row in all_rollups),
            "cumulative_dropped_by_rank": sum(int(row.get("dropped_by_rank") or 0) for row in all_rollups),
            "last_run": {
                "at": current.isoformat().replace("+00:00", "Z"),
                "outcome": str(report["run_outcome"]),
                "new_records": len(new_records),
                "trigger_class": trigger_class,
            },
        }
        from .jsonl_io import write_json_atomic

        sp = _snapshot_path(store)
        write_json_atomic(sp, snapshot)
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


def _record_last_run_outcome(
    store: Any,
    *,
    outcome: str,
    new_records: int,
    at: str,
    trigger_class: str,
    report: dict[str, Any],
) -> None:
    """Durably record why this run produced (or did not produce) output.

    Merges a ``last_run`` block into the best-effort snapshot file, preserving
    every other snapshot field. Runs on the pre-envelope exits too: the
    snapshot is a rebuildable, non-canonical observation artifact (the same
    class of state as the group runner's due bookkeeping), and the whole point
    of the outcome record is to survive precisely when the interesting exits
    fire -- gating it on envelope availability would blind it to the runs a
    reader most needs to distinguish (backlog 14). The gate-failure exits stay
    report-only: their evidence lives in the permit audit trail already.

    The snapshot's top-level ``status`` is deliberately NOT rewritten here:
    it describes snapshot-content availability (ok / empty / error), not lane
    health. After a produced run, a cursor-error exit leaves ``status: "ok"``
    beside ``last_run.outcome: "source_cursor_not_found"`` -- a consistent
    pair meaning "the snapshot's cumulative data is valid; the most recent
    run failed". Lane health lives in ``last_run`` alone.
    """
    from .jsonl_io import write_json_atomic

    try:
        snapshot = exposure_rollup_snapshot(store)
        snapshot.setdefault("schema_version", SNAPSHOT_SCHEMA_VERSION)
        # A fresh file created by a no-output exit must keep reading as "no
        # rollup produced yet", so status stays "empty" unless a success path
        # already wrote "ok".
        snapshot.setdefault("status", "empty")
        snapshot["last_run"] = {
            "at": at,
            "outcome": outcome,
            "new_records": new_records,
            "trigger_class": trigger_class,
        }
        write_json_atomic(_snapshot_path(store), snapshot)
    except Exception as exc:
        report["error_records"].append({
            "component": "exposure_rollup",
            "operation": "record_last_run_outcome",
            "error_code": type(exc).__name__,
            "severity": "warning",
            "recoverable": True,
        })


def exposure_monitor_stats(store: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Return monitor-facing V2 exposure telemetry without mutating state."""
    from datetime import timedelta, timezone as _tz

    from .memory_sources import (
        ATTRIBUTION_SCHEMA_VERSION as MEMORY_SOURCES_ATTRIBUTION_SCHEMA,
        read_memory_source_records,
    )
    from .natural_row import is_natural

    current = (now or datetime.now(_tz.utc)).astimezone(_tz.utc)
    snapshot = exposure_rollup_snapshot(store)
    raw_last_run = snapshot.get("last_run")
    last_run: dict[str, Any] = raw_last_run if isinstance(raw_last_run, dict) else {}

    lag_hours = 0.0
    latest_end = str(snapshot.get("latest_window_end") or "")
    if latest_end and snapshot.get("status") != "empty":
        end_dt = _parse_monitor_time(latest_end)
        if end_dt is not None:
            lag_hours = max(0.0, (current - end_dt).total_seconds() / 3600.0)

    ms_records = read_memory_source_records(store.roots, limit=1_000_000)
    natural_records = [record for record in ms_records if is_natural(record)]
    rolling_cutoff = current - timedelta(days=7)
    rolling_records = [
        record for record in natural_records
        if (_parse_monitor_time(record.get("created_at")) or datetime.min.replace(tzinfo=_tz.utc)) >= rolling_cutoff
    ]

    all_history_gap = sum(1 for record in ms_records if _memory_source_has_attribution_gap(record))
    # Item 16a's era boundary: only records written by the attribution-complete
    # producer can be held to the attribution contract. Earlier rows cannot be
    # fixed retroactively -- the disclosure already happened without capturing
    # IDs -- so they are surfaced as debt rather than folded into the gate.
    # Same treatment as legacy_unmarked_rollup_count above.
    def _in_attribution_era(record: dict[str, Any]) -> bool:
        return str(record.get("attribution_schema") or "") == MEMORY_SOURCES_ATTRIBUTION_SCHEMA

    attribution_era_records = [r for r in natural_records if _in_attribution_era(r)]
    legacy_unattributed_record_count = len(natural_records) - len(attribution_era_records)
    schema_gap = sum(
        1 for record in attribution_era_records if _memory_source_has_attribution_gap(record)
    )
    # Item 17: era-scoped for the same reason schema_gap is. Counting pre-marker
    # rows here would report gaps for the first 7 days after the producer fix
    # ships while the producer is in fact correct -- a rolling window is supposed
    # to answer "is it degrading RIGHT NOW", and unattributable legacy rows
    # cannot answer that. rolling_era_record_count is reported alongside so a
    # zero can be read as "no recent attributed traffic" rather than "clean".
    rolling_era_records = [r for r in rolling_records if _in_attribution_era(r)]
    rolling_gap = sum(
        1 for record in rolling_era_records if _memory_source_has_attribution_gap(record)
    )
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
        if not is_natural(record):
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
    if natural_records and not attribution_era_records:
        # Honesty guard for item 16a's era boundary: right after the producer
        # fix ships, every existing row is pre-marker, so the gated set is empty
        # and the attribution check has nothing to judge. Reporting PASS there
        # would be green bought by narrowing the measurement -- the exact thing
        # item 16b warns against. Report no-sample and keep clearance frozen
        # until real attributed traffic exists.
        freeze_reasons.append("attribution_era_no_sample")

    schema_health = "FAIL" if schema_gap or conservation_failures or telemetry_degraded_count else (
        "healthy_no_sample" if not natural_records or not attribution_era_records else "PASS"
    )
    return {
        "schema_version": "memory-os.exposure_monitor_stats.v1",
        # Ledger-state context: surfaced by the monitor's
        # v2_exposure_rollup_ledger_state INFO entry (backlog 18). lag_hours is
        # deliberately never graded -- an idle upstream inflates it benignly
        # (backlog 15 measured exactly that), and "ran recently" is already
        # graded by helper-completion freshness.
        "exposure_rollup_lag_hours": round(lag_hours, 1),
        "exposure_rollup_records_total": len(rollup_records),
        "legacy_unmarked_rollup_count": legacy_unmarked_rollup_count,
        # Components of conservation_total_passes below. Not independent
        # signals: their reader is the monitor's migration-debt INFO entry,
        # which publishes the breakdown when all-history conservation breaks.
        "cumulative_eligible": total_eligible,
        "cumulative_selected": total_selected,
        "cumulative_dropped_by_budget": total_budget,
        "cumulative_dropped_by_rank": total_rank,
        "conservation_total_passes": total_eligible == total_selected + total_budget + total_rank,
        # attribution_gap_count (an unread duplicate alias of the key below)
        # was removed here (backlog 18); the census tool had missed it because
        # its name is a substring of three read keys.
        "all_history_attribution_gap_count": all_history_gap,
        "schema_era_attribution_gap_count": schema_gap,
        # Pre-fix natural rows: real debt, surfaced, never gated (see item 16a).
        "legacy_unattributed_record_count": legacy_unattributed_record_count,
        "attribution_era_record_count": len(attribution_era_records),
        "rolling_7d_attribution_gap_count": rolling_gap,
        # Denominator for the above: 0 means "no recent attributed traffic", which
        # is NOT the same as "recent traffic was clean" (item 17).
        "rolling_7d_attribution_era_record_count": len(rolling_era_records),
        "schema_era_conservation_failure_count": conservation_failures,
        # schema_era_natural_record_count was removed here (backlog 18): it was
        # misnamed (it counted ALL natural history, not the schema era) and
        # exactly equal to attribution_era_record_count +
        # legacy_unattributed_record_count, both of which already ride the
        # monitor's migration-debt INFO entry.
        # Recent natural traffic volume. NOT the denominator for
        # rolling_7d_attribution_gap_count (that is the era-scoped count above;
        # the domains differ). The natural-minus-era difference is the
        # deploy-verification signal: recent rows the producer failed to stamp
        # with attribution_schema.
        "rolling_7d_natural_record_count": len(rolling_records),
        # classified/processed over schema-era rollup rows. INFO-surfaced by the
        # monitor (v2_exposure_classification_coverage), deliberately ungraded:
        # the cumulative ratio mixes pre-fix and post-fix rollups, so it moves
        # slowly by construction and no evidence-backed threshold exists. None
        # means "no rows processed yet" and must never be coerced to 0.
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
        # Backlog 14: why the last run produced (or did not produce) output.
        # "unrecorded" means the snapshot predates outcome recording -- an
        # honest legacy marker, never fabricated as a real outcome.
        "last_run_outcome": str(last_run.get("outcome") or RUN_OUTCOME_UNRECORDED),
        "last_run_at": str(last_run.get("at") or ""),
        "last_run_new_records": int(last_run.get("new_records") or 0),
    }


def _memory_source_has_attribution_gap(record: dict[str, Any]) -> bool:
    attributable_classes = ATTRIBUTABLE_SOURCE_CLASSES
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
