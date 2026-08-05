"""Offline session-transcript fact-extraction lane for Memory-OS.

Defect this closes: ``MemoryOSProvider.sync_turn`` (plugins/memory/memory_os/
__init__.py) only ever writes ``_turn_summary(user, assistant)`` to the event
queue, and that summary clips each side to 140 characters (see ``_clip`` /
``_turn_summary`` there). ``inner_drive.py`` then builds candidate bodies from
that already-truncated summary. Any durable fact stated beyond the first 140
characters of a message never enters memory.

Full message bodies survive on disk as raw session transcripts under
``<hermes_home>/sessions/session_*.json`` (see ``SessionMirror.sessions_root``
in session_mirror.py for the canonical path -- not imported here to avoid
growing that module's cross-import fan-in; CLAUDE.md forbids new cross-import
chains between governance modules). This lane reads those transcripts
OFFLINE, extracts durable facts from the long messages, and emits bounded,
UNAPPROVED review candidates on the existing governed candidate-queue path
(``append_candidate_queue``) -- the same path ``inner_drive`` and
``session_mirror`` write through. It never approves, crystallizes, or sends
anything itself.

Governance boundaries (non-negotiable):
  - INV-5: no LLM on the hot path. This module is only ever invoked from the
    ``session_fact_extraction`` cron lane (offline), never from prefetch,
    sync_turn, or heartbeat.
  - OwnerGate: this lane writes ONLY unapproved candidates (via
    ``append_candidate_queue``) plus its own bounded observation artifacts
    (processed-session fingerprints, per-run report). It never writes
    crystallized memory, never approves anything, never writes identity or
    relationship data, never sends externally.
  - Read-only on session transcripts: session files are only ever opened for
    read. Nothing here modifies, moves, or deletes them.
  - Every automatic JSONL append this module makes goes through
    ``append_governed_jsonl`` (structural_write_gate.py), matching the
    precedent in ``crystallized.append_candidate_triage`` /
    ``write_candidate_aggregation_status`` for other ``tick_evidence``
    subprocess lanes: the runner supplies a fresh, unused ExecutionGate
    permit keyed by (lane_id, risk_class); this lane matches lane_id/
    risk_class and passes ``scope_hash=""`` (the runner's permit carries no
    caller-defined scope to match against -- see cron_registry.py /
    memory_os_execution_gate_runner.py). Candidate writes go through the
    pre-existing ``append_candidate_queue`` surface, which -- like the
    ``inner_drive`` and ``session_mirror`` lanes that already write through
    it -- carries no ExecutionGate requirement of its own; only ledger/report
    bookkeeping introduced by this lane is newly gated here.
  - No silent failures: every read/parse/write failure is recorded as a
    bounded ``error_record`` (component, operation, error_code, severity,
    recoverable) rather than swallowed.

Selection strategy (why this converges instead of re-chewing the same head of
the queue forever, unlike ``SessionMirror.scan``'s documented head-of-queue
bias):
  - One session file is a unit of work; each tick processes at most
    ``session_fact_extraction_max_sessions_per_tick`` of them.
  - A durable fingerprint ledger (``processed_sessions.jsonl``) records which
    sessions have already been processed. A fingerprint combines the
    filename, file size, and mtime, so an appended-to session (same name,
    different size/mtime) is reconsidered.
  - Selection order is newest-unprocessed-first (by mtime), so the backlog
    drains from the most recently active sessions rather than being
    permanently starved by whichever file sorts first lexicographically.

LLM integration follows ``plugins/modules/governance/fact_judge.py``: the same
private cross-module import of ``_call_hermes_runtime_model`` /
``_extract_json_object`` from ``low_clue_recall.py``, and the same typed retry
failure reasons (``llm_exception`` / ``llm_empty_content`` /
``llm_parse_failed`` / ``llm_missing_key``).

It deliberately DIVERGES from fact_judge on the fallback, and the reason is
load-bearing: fact_judge answers a *boolean* about content that already
exists, so a marker-matching heuristic is a legitimate degraded answer. This
lane has to *generate* a summary of a message too long to keep verbatim, and
there is no heuristic that summarizes. A marker-matched raw clip is not a
recovered fact -- it is the same truncation this lane exists to undo, and
because candidates are ``bridge_state="inner_drive_candidate"`` (in
``resolver_gate.RESOLVER_ELIGIBLE_BRIDGE_STATES``) it could be auto-promoted
to *provisional* crystallized. ``fact_judge._DURABLE_MARKERS`` also contains
``"用"``, which appears in almost any long Chinese message, so a marker gate
here would fire nearly always rather than rarely.

So on LLM failure this lane **defers instead of manufacturing**: no candidate
is written, the typed failure is counted, and the session is NOT fingerprinted
as processed, so it is retried on a later tick when the model is available.
Deferral is bounded by ``MAX_EXTRACTION_ATTEMPTS`` -- after that the session is
recorded ``abandoned`` and stops consuming the per-tick budget. This matters
precisely because the measured ``llm_empty_content`` rate is 27.5%: fingerprint-
on-failure would permanently lose facts in the lane's most likely failure mode,
which is the exact defect the lane was built to fix.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
from plugins.memory.memory_os.jsonl_io import build_error_record, read_jsonl
from plugins.memory.memory_os.low_clue_recall import _call_hermes_runtime_model, _extract_json_object
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.structural_write_gate import append_governed_jsonl


def session_fact_extraction_manifest() -> dict[str, Any]:
    return {
        "name": "session_fact_extraction",
        "kind": "cognition",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "execution_gate"],
        },
        "provides": {
            "commands": ["run_session_fact_extraction_lane"],
            "schedules": ["session_fact_extraction"],
            "reads": ["local_artifact.session_transcripts"],
            "writes": [
                "memory_os.crystallized_candidates",
                "local_artifact.session_fact_extraction_fingerprints",
                "local_artifact.session_fact_extraction_runs",
            ],
            "consumed_by": ["fact_judge", "candidate_aggregation", "owner_actions"],
        },
        "defaults": {
            "enabled": True,
            "profile_scope": "per-profile",
        },
    }


# ── Eligibility threshold ────────────────────────────────────────────────
# Tied to plugins/memory/memory_os/__init__.py::_turn_summary, which does
# `_clip(_redact_secrets(content), 140)` per side. A message whose redacted
# length is at or under this already survives capture intact through the
# live summary path -- re-extracting it here would be pure duplicate work.
MESSAGE_ELIGIBILITY_THRESHOLD_CHARS = 140

# ── Lane identity (must match the cron_registry.py lane def) ────────────
LANE_ID = "session_fact_extraction"
RISK_CLASS = "local_helper"

# ── Config defaults (knob names/defaults mirror fact_judge's naming) ────
DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "hermes_default",
    "max_sessions_per_tick": 2,
    "max_messages_per_session": 20,
    "max_message_chars": 4000,
    "max_facts_per_session": 5,
    "max_tokens": 1024,
    "timeout_ms": 15000,
}

MAX_EXTRACT_RETRIES = 2  # per-message LLM retries; mirrors fact_judge.MAX_JUDGE_RETRIES

# Per-SESSION retry budget across ticks. A session whose extraction failed is
# left un-fingerprinted so a later tick retries it, but that cannot be
# unbounded: a message that always fails to parse would otherwise re-consume
# the per-tick budget forever and starve every other session.
MAX_EXTRACTION_ATTEMPTS = 3

# Fingerprint-ledger statuses. Only TERMINAL ones suppress re-processing.
FINGERPRINT_STATUS_PROCESSED = "processed"   # terminal: extraction completed
FINGERPRINT_STATUS_DEFERRED = "deferred"     # NOT terminal: retry on a later tick
FINGERPRINT_STATUS_ABANDONED = "abandoned"   # terminal: retry budget exhausted
TERMINAL_FINGERPRINT_STATUSES = frozenset({
    FINGERPRINT_STATUS_PROCESSED,
    FINGERPRINT_STATUS_ABANDONED,
})

SCHEMA_VERSION = "memory-os.session_fact_extraction_run.v0"
FINGERPRINT_SCHEMA_VERSION = "memory-os.session_fact_extraction_fingerprint.v0"

# Closed set of documented skip reasons. A reader must be able to tell these
# apart from the persisted artifact alone, without re-running anything.
SKIPPED_REASON_CODES = frozenset({
    "sessions_dir_absent",       # (a) no eligible input existed: no sessions dir at all
    "no_session_files_found",   # (a) no eligible input existed: dir exists, zero session files
    "no_unprocessed_sessions",  # healthy-drained: files exist, all already fingerprinted
})

_EXTRACT_SYSTEM_PROMPT = (
    "You are a durable-fact extractor for a memory system. You will be given "
    "one long conversation message that was too long to be captured verbatim "
    "by the live summary pipeline, which only keeps the first 140 characters "
    "per side of a turn. Your ONLY task: read the FULL message and decide "
    "whether it states a durable fact worth permanently remembering -- a "
    "user preference, decision, commitment, or factual claim about the user "
    "or their project -- that a 140-character clip would plausibly have cut "
    "off or missed.\n\n"
    "Mark has_durable_fact True for: preferences (\"I prefer...\"), decisions "
    "and commitments (\"I'll use...\"), factual claims about the user or "
    "project, and explicit requests to remember something.\n"
    "Mark has_durable_fact False for: greetings, process/navigation chatter, "
    "momentary emotional statements, pure information requests, and content "
    "with no substantive claim.\n\n"
    "Return ONLY a JSON object with keys:\n"
    "- has_durable_fact: boolean\n"
    "- fact: a short (<=500 chars) restatement of the durable fact, in the "
    "same language as the message. Empty string if has_durable_fact is "
    "false.\n"
    "- reason: short string explaining the decision (max 160 chars)\n"
)

# ── Local secret redaction (self-contained; same pattern family used by
# _turn_summary/_redact_secrets in __init__.py and session_mirror.py, kept
# local here rather than imported to avoid a cross-module coupling for a
# four-line regex helper). ──────────────────────────────────────────────
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(password\s*[:=]\s*)\S+"),
)


def _redact_secrets(value: str) -> str:
    redacted = str(value or "")
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    return redacted


def _clip(value: str, limit: int) -> str:
    collapsed = " ".join(str(value or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 0)].rstrip() + "..."


# ── Fingerprint ledger ───────────────────────────────────────────────────


def _session_fingerprint(*, session_ref: str, size: int, mtime: float) -> str:
    """Combine filename + size + mtime so an appended-to session is reconsidered.

    Computable from filesystem stat() alone -- no need to read/parse a
    session's content just to check whether it was already processed, which
    matters at production scale (~468 session files against a small per-tick
    cap).
    """
    material = f"{session_ref}|{int(size)}|{mtime:.6f}"
    return "sfefp_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _module_root(store: MemoryOSStore) -> Path:
    return store.roots.memory_os_root / "system-modules" / "session_fact_extraction"


def _fingerprints_path(store: MemoryOSStore) -> Path:
    return _module_root(store) / "processed_sessions.jsonl"


def _runs_path(store: MemoryOSStore) -> Path:
    return _module_root(store) / "runs.jsonl"


def read_processed_session_fingerprints(store: MemoryOSStore) -> set[str]:
    """Public reader: fingerprints that must NOT be re-processed.

    Only terminal statuses suppress re-processing. A ``deferred`` row means the
    LLM was unavailable, so that session is deliberately still eligible --
    otherwise an outage would permanently lose the facts this lane exists to
    recover. Rows written before the status field existed are treated as
    ``processed`` so historical ledgers keep their meaning.
    """
    terminal: set[str] = set()
    for record in read_jsonl(_fingerprints_path(store)):
        fingerprint = str(record.get("fingerprint") or "")
        if not fingerprint:
            continue
        status = str(record.get("status") or FINGERPRINT_STATUS_PROCESSED)
        if status in TERMINAL_FINGERPRINT_STATUSES:
            terminal.add(fingerprint)
    return terminal


def read_session_deferral_attempts(store: MemoryOSStore) -> dict[str, int]:
    """Public reader: how many times each fingerprint has been deferred."""
    attempts: dict[str, int] = {}
    for record in read_jsonl(_fingerprints_path(store)):
        fingerprint = str(record.get("fingerprint") or "")
        if not fingerprint:
            continue
        if str(record.get("status") or "") != FINGERPRINT_STATUS_DEFERRED:
            continue
        try:
            attempt = int(record.get("attempt") or 0)
        except (TypeError, ValueError):
            attempt = 0
        attempts[fingerprint] = max(attempts.get(fingerprint, 0), attempt)
    return attempts


def read_session_fact_extraction_runs(store: MemoryOSStore, *, limit: int = 0) -> list[dict[str, Any]]:
    """Public reader: persisted per-run reports, oldest first on disk."""
    records = read_jsonl(_runs_path(store))
    return records[-max(limit, 0):] if limit else records


def _append_processed_fingerprint(
    store: MemoryOSStore,
    *,
    fingerprint: str,
    execution_gate_envelope_id: str,
    now: datetime,
    error_records: list[dict[str, Any]],
    status: str = FINGERPRINT_STATUS_PROCESSED,
    attempt: int = 0,
) -> None:
    record = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "status": status,
        "attempt": int(attempt),
        # MUST be `created_at`: metadata_retention._record_created_at() reads
        # only created_at/ts/timestamp, so a ledger timestamped anything else
        # (e.g. `processed_at`) is judged "no timestamp" and can never age out
        # -- the defect recorded as backlog item 9 for two sibling ledgers.
        "created_at": now.isoformat().replace("+00:00", "Z"),
    }
    try:
        append_governed_jsonl(
            store,
            _fingerprints_path(store),
            record,
            write_owner="automatic",
            lane_id=LANE_ID,
            risk_class=RISK_CLASS,
            execution_gate_envelope_id=execution_gate_envelope_id,
            scope_hash="",
        )
    except Exception as exc:  # governed write can legitimately fail (bad/expired permit)
        error_records.append(
            build_error_record(
                component="session_fact_extraction",
                operation="append_processed_fingerprint",
                error_code="processed_fingerprint_write_failed",
                severity="error",
                recoverable=True,
                details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
            )
        )


def _append_run_report(
    store: MemoryOSStore,
    report: dict[str, Any],
    *,
    execution_gate_envelope_id: str,
    error_records: list[dict[str, Any]],
) -> None:
    try:
        append_governed_jsonl(
            store,
            _runs_path(store),
            dict(report),
            write_owner="automatic",
            lane_id=LANE_ID,
            risk_class=RISK_CLASS,
            execution_gate_envelope_id=execution_gate_envelope_id,
            scope_hash="",
        )
    except Exception as exc:
        error_records.append(
            build_error_record(
                component="session_fact_extraction",
                operation="append_run_report",
                error_code="run_report_write_failed",
                severity="error",
                recoverable=True,
                details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
            )
        )


def extract_fact_from_message(
    message_text: str,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract a durable fact from one long (already-redacted) message.

    Follows fact_judge.judge_candidate's retry loop and typed failure
    reasons. Returns:
        {"has_durable_fact": bool, "fact": str, "reason": str,
         "failure_reason": str | None}
    ``failure_reason`` is one of llm_exception / llm_empty_content /
    llm_parse_failed / llm_missing_key when the LLM path failed; None on a
    clean LLM verdict (whether or not a fact was found).

    On failure this returns a DEFERRAL, never a manufactured fact: no
    heuristic can summarize a message, and a marker-matched raw clip would be
    the same truncation this lane exists to undo (see the module docstring).
    The caller must leave such a session un-fingerprinted so it is retried.
    """
    effective = dict(DEFAULT_CONFIG, **(config or {}))
    text = str(message_text or "").strip()
    if not text:
        return {"has_durable_fact": False, "fact": "", "reason": "empty_message", "failure_reason": None}

    bounded_text = text[: max(int(effective.get("max_message_chars") or 4000), 0)]
    prompt = (
        f"{_EXTRACT_SYSTEM_PROMPT}\n\n"
        f'Message: """{bounded_text}"""\n\n'
        f"Return JSON."
    )

    last_failure: str | None = None
    for attempt in range(1 + MAX_EXTRACT_RETRIES):
        try:
            response_text = _call_hermes_runtime_model(prompt, effective)
        except Exception:
            last_failure = "llm_exception"
            if attempt < MAX_EXTRACT_RETRIES:
                continue
            break

        if not response_text:
            last_failure = "llm_empty_content"
            if attempt < MAX_EXTRACT_RETRIES:
                continue
            break

        try:
            parsed = _extract_json_object(response_text)
        except Exception:
            last_failure = "llm_parse_failed"
            if attempt < MAX_EXTRACT_RETRIES:
                continue
            break

        if not isinstance(parsed, dict):
            last_failure = "llm_parse_failed"
            if attempt < MAX_EXTRACT_RETRIES:
                continue
            break

        has_fact = parsed.get("has_durable_fact")
        if not isinstance(has_fact, bool):
            last_failure = "llm_missing_key"
            if attempt < MAX_EXTRACT_RETRIES:
                continue
            break

        if not has_fact:
            return {
                "has_durable_fact": False,
                "fact": "",
                "reason": str(parsed.get("reason") or "")[:200],
                "failure_reason": None,
            }

        fact = parsed.get("fact")
        if not isinstance(fact, str) or not fact.strip():
            last_failure = "llm_missing_key"
            if attempt < MAX_EXTRACT_RETRIES:
                continue
            break

        return {
            "has_durable_fact": True,
            "fact": _clip(fact.strip(), 500),
            "reason": str(parsed.get("reason") or "")[:200],
            "failure_reason": None,
        }

    # All retries exhausted. Defer -- do not manufacture a fact.
    return {
        "has_durable_fact": False,
        "fact": "",
        "reason": "llm_unavailable_extraction_deferred",
        "failure_reason": last_failure,
    }


# ── Candidate construction ──────────────────────────────────────────────


def _build_candidate(
    *,
    session_id: str,
    platform: str,
    fingerprint: str,
    message_index: int,
    role: str,
    fact_text: str,
) -> CrystallizedCandidate:
    # Identity material deliberately EXCLUDES the session fingerprint: the
    # fingerprint carries mtime, so an appended-to session gets a new one, and
    # folding it in here would mint a fresh candidate_id for a fact already
    # extracted from an unchanged earlier message. append_candidate_queue
    # de-duplicates by candidate_id at write time (crystallized.py:1116), so a
    # STABLE id makes re-processing idempotent while an mtime-derived one
    # defeats that guard and floods owner review with duplicates every time a
    # live session grows. Keyed on (session_id, message_index, fact_text),
    # all three of which are stable across appends.
    material = f"{session_id}|{message_index}|{fact_text}"
    candidate_id = "cand_sfe_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    body = _clip(f"Extracted from session {session_id} ({platform}): {fact_text}", 600)
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="moment",
        body=body,
        source_event_ids=[],
        sensitivity="private",
        tags=["session_fact_extraction", "long_message_fact", str(platform or "unknown")],
        bridge_state="inner_drive_candidate",
        provenance={
            "source_module": "session_fact_extraction",
            "session_fingerprint": fingerprint,
            "session_id": _clip(str(session_id), 120),
            "platform": str(platform or "unknown"),
            "message_index": int(message_index),
            "role": str(role or "unknown"),
        },
    )


# ── Session discovery ────────────────────────────────────────────────────


def _discover_session_files(
    sessions_root: Path,
    *,
    error_records: list[dict[str, Any]],
) -> list[tuple[Path, Any]]:
    """Return (path, stat_result) pairs, newest mtime first.

    Per-file stat() failures (e.g. a TOCTOU race against a deleted file) are
    recorded as bounded error_records and excluded, rather than crashing the
    sort or the whole run.
    """
    pairs: list[tuple[Path, Any]] = []
    for path in sessions_root.glob("session_*.json"):
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError as exc:
            error_records.append(
                build_error_record(
                    component="session_fact_extraction",
                    operation="stat_session_file",
                    error_code="session_file_stat_failed",
                    severity="warning",
                    recoverable=True,
                    path=path,
                    details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                )
            )
            continue
        pairs.append((path, stat))
    pairs.sort(key=lambda item: item[1].st_mtime, reverse=True)
    return pairs


# ── Lane entry point ─────────────────────────────────────────────────────


def run_session_fact_extraction_lane(
    store: MemoryOSStore,
    *,
    now: datetime | None = None,
    execution_gate_envelope_id: str = "",
) -> dict[str, Any]:
    """Run one tick of the session_fact_extraction cron lane.

    Reads up to ``session_fact_extraction_max_sessions_per_tick`` not-yet-
    processed session transcripts (newest-first), extracts durable facts
    from messages whose redacted length exceeds
    MESSAGE_ELIGIBILITY_THRESHOLD_CHARS, and writes them as unapproved
    candidates via the existing governed candidate-queue path. Never
    crystallizes, never approves, never sends. Offline cron only (INV-5).
    """
    _now = now or datetime.now(timezone.utc)
    error_records: list[dict[str, Any]] = []

    from plugins.memory.memory_os.knob_overrides import resolve_knob

    def _safe_int_knob(name: str, default: int) -> int:
        raw = resolve_knob(name, default=default, roots=store.roots)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    max_sessions_per_tick = _safe_int_knob(
        "session_fact_extraction_max_sessions_per_tick", DEFAULT_CONFIG["max_sessions_per_tick"],
    )
    max_messages_per_session = _safe_int_knob(
        "session_fact_extraction_max_messages_per_session", DEFAULT_CONFIG["max_messages_per_session"],
    )
    max_message_chars = _safe_int_knob(
        "session_fact_extraction_max_message_chars", DEFAULT_CONFIG["max_message_chars"],
    )
    max_facts_per_session = _safe_int_knob(
        "session_fact_extraction_max_facts_per_session", DEFAULT_CONFIG["max_facts_per_session"],
    )
    max_tokens = _safe_int_knob("session_fact_extraction_max_tokens", DEFAULT_CONFIG["max_tokens"])
    timeout_ms = _safe_int_knob("session_fact_extraction_timeout_ms", DEFAULT_CONFIG["timeout_ms"])

    llm_config = {
        "provider": "hermes_default",
        "max_tokens": max_tokens,
        "timeout_ms": timeout_ms,
        "max_message_chars": max_message_chars,
    }

    def _base_report() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "lane_id": LANE_ID,
            "created_at": _now.isoformat().replace("+00:00", "Z"),
            "sessions_scanned": 0,
            "sessions_eligible": 0,
            "sessions_processed": 0,
            "sessions_skipped_already_processed": 0,
            "messages_considered": 0,
            "messages_eligible_over_threshold": 0,
            "facts_extracted": 0,
            "candidates_written": 0,
            "llm_calls": 0,
            "llm_failures_by_reason": {},
            "fallback_used_count": 0,
            # Deferral visibility: without these, an LLM outage and a genuinely
            # fact-free batch both read as "0 facts extracted".
            "sessions_deferred_llm_failure": 0,
            "sessions_abandoned_after_max_attempts": 0,
            "status": "ok",
            "skipped": False,
            "skipped_reason": "",
            "error_records": [],
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

    # Canonical path resolution: <hermes_home>/sessions. This mirrors
    # SessionMirror.sessions_root in session_mirror.py (that file is
    # read-only reference material per the task's whitelist, not imported,
    # to avoid growing its cross-import fan-in).
    sessions_root = store.roots.hermes_home / "sessions"

    if not sessions_root.exists():
        report = _base_report()
        report["skipped"] = True
        report["skipped_reason"] = "sessions_dir_absent"
        report["error_records"] = error_records
        _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
        report["error_records"] = error_records
        return report

    pairs = _discover_session_files(sessions_root, error_records=error_records)
    sessions_scanned = len(pairs)

    if sessions_scanned == 0:
        report = _base_report()
        report["skipped"] = True
        report["skipped_reason"] = "no_session_files_found"
        report["error_records"] = error_records
        _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
        report["error_records"] = error_records
        return report

    processed_fingerprints = read_processed_session_fingerprints(store)

    eligible: list[tuple[Path, Any, str]] = []  # (path, stat, fingerprint)
    for path, stat in pairs:
        fingerprint = _session_fingerprint(session_ref=path.name, size=stat.st_size, mtime=stat.st_mtime)
        if fingerprint in processed_fingerprints:
            continue
        eligible.append((path, stat, fingerprint))

    sessions_eligible = len(eligible)
    # sessions_scanned is len(pairs), and _discover_session_files already
    # EXCLUDES files whose stat() failed, so those never entered this total.
    # Subtracting them again here would under-report how many sessions were
    # skipped as already-processed -- and these counters are this lane's
    # contract for telling "nothing to do" apart from "something broke".
    sessions_skipped_already_processed = sessions_scanned - sessions_eligible

    if sessions_eligible == 0:
        report = _base_report()
        report["sessions_scanned"] = sessions_scanned
        report["sessions_skipped_already_processed"] = max(sessions_skipped_already_processed, 0)
        report["skipped"] = True
        report["skipped_reason"] = "no_unprocessed_sessions"
        report["error_records"] = error_records
        _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
        report["error_records"] = error_records
        return report

    selected = eligible[: max(max_sessions_per_tick, 0)]

    messages_considered = 0
    messages_eligible_over_threshold = 0
    facts_extracted = 0
    candidates_written = 0
    llm_calls = 0
    llm_failures_by_reason: dict[str, int] = {}
    fallback_used_count = 0
    sessions_deferred_llm_failure = 0
    sessions_abandoned_after_max_attempts = 0
    # (fingerprint, status, attempt) -- status decides whether the session is
    # suppressed from future ticks. Never append unconditionally: see the
    # module docstring on deferral.
    fingerprint_outcomes: list[tuple[str, str, int]] = []
    deferral_attempts = read_session_deferral_attempts(store)

    for path, _stat, fingerprint in selected:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            error_records.append(
                build_error_record(
                    component="session_fact_extraction",
                    operation="read_session_file",
                    error_code="session_json_unreadable",
                    severity="warning",
                    recoverable=True,
                    path=path,
                    details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                )
            )
            # Terminal: a malformed file will not become readable by retrying.
            fingerprint_outcomes.append((fingerprint, FINGERPRINT_STATUS_PROCESSED, 0))
            continue

        if not isinstance(raw, dict):
            error_records.append(
                build_error_record(
                    component="session_fact_extraction",
                    operation="read_session_file",
                    error_code="session_json_not_an_object",
                    severity="warning",
                    recoverable=True,
                    path=path,
                    details={"parsed_type": type(raw).__name__},
                )
            )
            # Terminal for the same reason as the unreadable-JSON branch above.
            fingerprint_outcomes.append((fingerprint, FINGERPRINT_STATUS_PROCESSED, 0))
            continue

        session_id = str(raw.get("id") or raw.get("session_id") or path.stem)
        platform = str(raw.get("platform") or raw.get("source") or raw.get("channel") or "unknown")
        raw_messages = raw.get("messages", [])
        messages = [dict(item) for item in raw_messages if isinstance(item, dict)]
        messages_considered += len(messages)

        # Redact first (matches _turn_summary's redact-then-clip order), then
        # filter to messages whose redacted length exceeds the eligibility
        # threshold -- filtering BEFORE the per-session message cap, so a
        # session with a long tail of short "ok"/"thanks" turns after its
        # substantive messages does not starve the substantive ones out of
        # the bounded window.
        eligible_messages: list[tuple[int, dict[str, Any], str]] = []
        for idx, message in enumerate(messages):
            redacted = _redact_secrets(str(message.get("content") or ""))
            if len(redacted) > MESSAGE_ELIGIBILITY_THRESHOLD_CHARS:
                eligible_messages.append((idx, message, redacted))
        messages_eligible_over_threshold += len(eligible_messages)

        bounded_eligible = (
            eligible_messages[-max_messages_per_session:] if max_messages_per_session > 0 else eligible_messages
        )

        session_fact_count = 0
        session_llm_failed = False
        for idx, message, redacted_content in bounded_eligible:
            if session_fact_count >= max_facts_per_session:
                break

            llm_calls += 1
            try:
                result = extract_fact_from_message(redacted_content, config=llm_config)
            except Exception as exc:  # defensive: extraction must never crash the tick
                error_records.append(
                    build_error_record(
                        component="session_fact_extraction",
                        operation="extract_fact_from_message",
                        error_code="extraction_unexpected_exception",
                        severity="error",
                        recoverable=True,
                        details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                    )
                )
                session_llm_failed = True
                continue

            failure_reason = result.get("failure_reason")
            if failure_reason:
                llm_failures_by_reason[failure_reason] = llm_failures_by_reason.get(failure_reason, 0) + 1
                fallback_used_count += 1
                # This message produced no fact because the MODEL failed, not
                # because the content held none. Mark the session so it is not
                # fingerprinted as done -- otherwise the facts are lost for good.
                session_llm_failed = True

            if not result.get("has_durable_fact"):
                continue

            fact_text = str(result.get("fact") or "").strip()
            if not fact_text:
                continue

            facts_extracted += 1
            session_fact_count += 1

            try:
                candidate = _build_candidate(
                    session_id=session_id,
                    platform=platform,
                    fingerprint=fingerprint,
                    message_index=idx,
                    role=str(message.get("role") or "unknown"),
                    fact_text=fact_text,
                )
                append_candidate_queue(store, candidate)
                candidates_written += 1
            except Exception as exc:
                error_records.append(
                    build_error_record(
                        component="session_fact_extraction",
                        operation="append_candidate_queue",
                        error_code="candidate_write_failed",
                        severity="error",
                        recoverable=True,
                        details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                    )
                )

        if session_llm_failed:
            attempt = deferral_attempts.get(fingerprint, 0) + 1
            if attempt >= MAX_EXTRACTION_ATTEMPTS:
                # Retry budget exhausted: stop consuming the per-tick budget,
                # but record it as abandoned (not processed) so the give-up is
                # visible in the ledger rather than indistinguishable from success.
                fingerprint_outcomes.append((fingerprint, FINGERPRINT_STATUS_ABANDONED, attempt))
                sessions_abandoned_after_max_attempts += 1
            else:
                fingerprint_outcomes.append((fingerprint, FINGERPRINT_STATUS_DEFERRED, attempt))
                sessions_deferred_llm_failure += 1
        else:
            fingerprint_outcomes.append((fingerprint, FINGERPRINT_STATUS_PROCESSED, 0))

    for fingerprint, status, attempt in fingerprint_outcomes:
        _append_processed_fingerprint(
            store,
            fingerprint=fingerprint,
            execution_gate_envelope_id=execution_gate_envelope_id,
            now=_now,
            error_records=error_records,
            status=status,
            attempt=attempt,
        )

    report = _base_report()
    report.update({
        "sessions_scanned": sessions_scanned,
        "sessions_eligible": sessions_eligible,
        "sessions_processed": len(selected),
        "sessions_skipped_already_processed": max(sessions_skipped_already_processed, 0),
        "messages_considered": messages_considered,
        "messages_eligible_over_threshold": messages_eligible_over_threshold,
        "facts_extracted": facts_extracted,
        "candidates_written": candidates_written,
        "llm_calls": llm_calls,
        "llm_failures_by_reason": llm_failures_by_reason,
        "fallback_used_count": fallback_used_count,
        "sessions_deferred_llm_failure": sessions_deferred_llm_failure,
        "sessions_abandoned_after_max_attempts": sessions_abandoned_after_max_attempts,
        "skipped": False,
        "skipped_reason": "",
    })
    report["error_records"] = error_records
    _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
    report["error_records"] = error_records
    return report
