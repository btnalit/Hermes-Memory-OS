"""Offline session-transcript fact-extraction lane for Memory-OS.

Defect this closes: ``MemoryOSProvider.sync_turn`` (plugins/memory/memory_os/
__init__.py) only ever writes ``_turn_summary(user, assistant)`` to the event
queue, and that summary clips each side to 140 characters (see ``_clip`` /
``_turn_summary`` there). ``inner_drive.py`` then builds candidate bodies from
that already-truncated summary. Any durable fact stated beyond the first 140
characters of a message never enters memory.

SFE (2026-09-23): this lane's input source changed. It used to read raw
session transcripts from ``<hermes_home>/sessions/session_*.json``, but
Hermes stopped writing that format around 2026-05/06 -- it now writes
``<hermes_home>/state.db`` (SQLite: a ``sessions`` table keyed by session id,
with ``source`` / ``user_id`` / ``started_at`` (epoch REAL) / ``message_count``
/ ``last_activity_at``, and a ``messages`` table with ``session_id`` /
``role`` / ``content`` / ``timestamp``). The lane had produced nothing since
the switch (C0's ``lane_input_stale`` monitor code exists to catch exactly
this). This module now reads state.db instead, via
``plugins.memory.memory_os.roots.state_db_path`` (read-only URI connection --
Memory-OS never writes to Hermes' own database).

A second change rides along with the input-source switch: state.db carries a
session-level ``source`` + ``user_id``, which is enough to run every session
through ``principal.resolve_principal()`` before spending any LLM budget on
it -- something the old JSON transcripts (no author information at all)
could never support. Only sessions that resolve to ``owner`` or ``unknown``
(the pre-2026-09 compatibility state for an unconfigured platform) are
extracted; ``peer_agent`` / ``other_human`` / ``system`` sessions are skipped
and counted (see "Principal filter" below). This is why the run-report schema
bumped to v1: an old v0 row was reporting on the dead JSON-file input and
carried no principal-filter counters at all -- a genuinely different era of
this lane's behaviour, not an additive field.

Governance boundaries (non-negotiable):
  - INV-5: no LLM on the hot path. This module is only ever invoked from the
    ``session_fact_extraction`` cron lane (offline), never from prefetch,
    sync_turn, or heartbeat.
  - OwnerGate: this lane writes ONLY unapproved candidates (via
    ``append_candidate_queue``) plus its own bounded observation artifacts
    (processed-session fingerprints, per-run report). It never writes
    crystallized memory, never approves anything, never writes identity or
    relationship data, never sends externally.
  - Read-only on state.db: opened only via a ``mode=ro`` URI connection.
    Nothing here writes to, moves, or deletes Hermes' database.
  - P4 (principal.py is the only judge): this module never decides "who is
    this session from" itself -- every session is routed through
    ``principal.resolve_principal()``, including machine sessions (cron /
    subagent map to ``system`` via ``non_primary_context``, not via a local
    if/else here).
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
    recoverable) rather than swallowed. State.db access failures use the
    ``session_fact_extraction.state_db`` component (a distinct sub-component
    from the module's general ``session_fact_extraction`` errors) so a reader
    can tell "the input source itself is broken" apart from "extraction/write
    failed" without inspecting details.

Bounding (INV-5's "always bound the input too" -- a single production message
has been measured at 975,665 characters against a 1024-token reply budget):
  - ``session_fact_extraction_max_sessions_scanned_per_tick`` bounds how many
    session rows a single tick reads from state.db (default 500). This is
    DELIBERATELY separate from ``max_sessions_per_tick`` (the LLM-extraction
    budget, default 2): production's session mix is ~95% cron/subagent
    (machine, principal=system) interleaved by recency with the small
    owner-conversation minority, so a single shared cap combined with
    newest-first ordering would let machine noise starve owner sessions out
    of the window every tick -- the same head-of-queue failure shape as
    ``SessionMirror.scan``'s documented lexicographic bias, just arriving via
    source-mix instead of file naming.
  - ``session_fact_extraction_lookback_days`` bounds the ``started_at`` query
    window (default 180 days -- state.db has been the input since ~2026-05).
    ``started_at`` is an epoch-seconds REAL column: the cutoff MUST be a
    numeric epoch value, never an ISO string (a REAL-vs-TEXT comparison in
    SQLite is always false, so the query would silently return zero rows
    regardless of how much real data exists in the window). See
    ``_lookback_cutoff_epoch``.
  - Message content is read via ``substr(content, 1, ?)`` bound to
    ``max_message_chars``, so an oversized message body never leaves SQLite
    as an unbounded Python string in the first place (``extract_fact_from_message``
    then applies the same bound again for the LLM prompt -- belt and braces,
    not a behaviour change there).
  - Only ``role IN ('user', 'assistant')`` rows are read per session
    (excludes ``tool`` / ``session_meta`` rows, which are not conversation
    content), and reads are capped at ``_MESSAGE_READ_HARD_CAP`` rows per
    session regardless of ``message_count``.

Principal filter (P0-lite integration, 2026-09-23):
  - Every scanned session is routed through
    ``principal.resolve_principal(source=..., author_id=sessions.user_id,
    author_class="", config=<memory_os config>, session_id=...,
    non_primary_context=<source in {"cron", "subagent"}>)``.
  - ``author_class`` is not available at the session level -- state.db has no
    per-message author signal, only a session-level ``source`` + ``user_id``.
    The documented safe default is the empty string (never ``"bot"`` and
    never ``"unknown"``): passing ``""`` skips the bot-forced-peer_agent
    branch (state.db cannot tell us a session's author was a bot) and skips
    the author-unknown compatibility branch (state.db DOES have a per-session
    author id, so this is not "the host sent no author signal at all") --
    resolution instead falls through to the normal owner-identity lookup
    (or, for an unconfigured platform, the same ``unknown`` compat outcome).
  - ``cron`` and ``subagent`` sources are mapped to ``non_primary_context``
    (never hardcoded to a "system" result here -- see the P4 note above).
    Because that mapping is a pure function of ``source`` and never
    persisted state, these sessions are NEVER durably fingerprinted: the
    classification is free to recompute every tick, so there is nothing to
    gain (and a large, unbounded write volume to lose -- these sources are
    ~95% of production session volume) by writing a terminal ledger row for
    each one.
  - A session resolving to ``peer_agent`` / ``other_human`` (never ``system``,
    which is exempted above) IS durably fingerprinted
    (``FINGERPRINT_STATUS_SKIPPED_NON_OWNER``, terminal) so it is never
    re-examined -- these are comparatively rare in production and the
    classification is stable (an author's platform-configured identity does
    not change tick to tick).
  - Only ``owner`` and ``unknown`` may reach extraction. ``unknown`` is the
    documented pre-2026-09 compatibility state for a platform nobody has
    configured an owner identity for -- treating it as extraction-eligible
    (not a rejection) matches ``principal.py``'s own contract.

Group-chat tripwire (INFO only, never a gate -- monitor wiring deferred to a
follow-up PR, same as C0's other new counters): Hermes splits a group chat
into one state.db session per sender only when configured to do so; a
session whose ``chat_type == "group"`` but whose ``session_key`` does not
carry its own ``user_id`` as a substring means that split is NOT happening,
and every sender in that chat is sharing one session -- which would make the
per-session ``user_id`` this lane's principal filter depends on meaningless
for that chat. ``group_sessions_scanned`` / ``group_sessions_without_user_suffix``
report this ratio per tick so the assumption is visible rather than silently
relied upon.

Selection strategy (why this converges instead of re-chewing the same head of
the queue forever, unlike ``SessionMirror.scan``'s documented head-of-queue
bias):
  - One state.db session is a unit of work; each tick fully processes at most
    ``session_fact_extraction_max_sessions_per_tick`` owner/unknown-eligible
    ones (after the principal filter above has already removed
    system/peer_agent/other_human sessions from contention).
  - A durable fingerprint ledger (``processed_sessions.jsonl``) records which
    sessions have already been processed (or durably skipped as non-owner).
    A fingerprint combines the session id, ``message_count``, and
    ``last_activity_at`` (falling back to ``started_at``), so a session that
    grows (new messages appended) gets a new fingerprint and is reconsidered
    -- the direct state.db analogue of the old file-based size+mtime
    fingerprint.
  - Selection order is newest-first (by ``started_at``), preserving the
    original lane's documented bias: recent activity is examined before
    older backlog. Given production's owner-conversation volume is small
    relative to this lane's per-tick capacity and cadence (see the scan-cap
    knob comment above), this remains safe in practice; if owner-session
    volume ever grew to exceed capacity, very old backlog items could in
    principle be starved the same way the original file-based design could
    have been -- a risk carried over unchanged, not introduced here.

LLM integration follows ``plugins/modules/governance/fact_judge.py``: the same
private cross-module import of ``_call_hermes_runtime_model_result`` /
``_extract_json_object`` from ``low_clue_recall.py`` (W2), and the same typed
retry failure reasons (``llm_exception`` / ``llm_empty_content`` /
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
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
from plugins.memory.memory_os.ids import new_event_id
from plugins.memory.memory_os.jsonl_io import build_error_record, read_jsonl
from plugins.memory.memory_os.low_clue_recall import (
    LlmCallResult,
    _call_hermes_runtime_model_result,
    _extract_json_object,
    _llm_call_diagnostics,
)
from plugins.memory.memory_os.principal import (
    MACHINE_SESSION_SOURCES,
    PRINCIPAL_OWNER,
    PRINCIPAL_SYSTEM,
    PRINCIPAL_UNKNOWN,
    resolve_principal,
)
from plugins.memory.memory_os.roots import state_db_path
from plugins.memory.memory_os.schema import (
    EVENT_PRINCIPAL_SCHEMA_VERSION,
    EVENT_SCHEMA_VERSION,
    EventEnvelope,
)
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.structural_write_gate import append_governed_jsonl


def _call_diagnostics(call_result: LlmCallResult | None) -> dict[str, Any]:
    """Typed transport diagnostics to fold onto an extraction result (W2).

    ``llm_transport_failure_reason`` is the RAW closed-set reason from
    :class:`LlmCallResult` -- distinct from this module's own
    ``failure_reason`` vocabulary (llm_exception/llm_empty_content/
    llm_parse_failed/llm_missing_key), which additionally covers post-
    transport parsing/schema failures the transport layer knows nothing
    about. Kept in a separate field so the two vocabularies never collide.

    W4-A: delegates to the single shared seam
    (``low_clue_recall._llm_call_diagnostics``) that also now forwards
    ``llm_expected_model``/``llm_actual_model``/``llm_route_unexpected``/
    ``llm_route_unknown`` (plan row L1) -- every key this function
    previously returned is unchanged in name and value.
    """
    return _llm_call_diagnostics(call_result)


def session_fact_extraction_manifest() -> dict[str, Any]:
    return {
        "name": "session_fact_extraction",
        "kind": "cognition",
        "version": "0.2.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "execution_gate"],
        },
        "provides": {
            "commands": ["run_session_fact_extraction_lane"],
            "schedules": ["session_fact_extraction"],
            "reads": ["hermes_state_db.sessions", "hermes_state_db.messages"],
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

# Sources Hermes stamps for machine-initiated work. Routed into
# resolve_principal's `non_primary_context` (never returned as a hardcoded
# result here -- P4: judgment lives only in principal.py). Never durably
# fingerprinted: this classification is a free, stable function of `source`
# alone, and these sources are ~95% of production session volume.
_MACHINE_SOURCES = MACHINE_SESSION_SOURCES

# Hard safety cap on messages read per session, independent of
# `max_messages_per_session` (the eligible-message cap applied AFTER
# filtering). Applied at the SQL layer so one pathological session (e.g. a
# tool-heavy subagent run) cannot return an unbounded row set before role
# filtering narrows it down.
_MESSAGE_READ_HARD_CAP = 500

_SESSION_SELECT_COLUMNS = (
    "id", "source", "user_id", "started_at", "last_activity_at", "message_count", "chat_type", "session_key",
)

# ── Config defaults (knob names/defaults mirror fact_judge's naming) ────
DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "hermes_default",
    "max_sessions_per_tick": 2,
    "max_sessions_scanned_per_tick": 500,
    "lookback_days": 180,
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
FINGERPRINT_STATUS_PROCESSED = "processed"             # terminal: extraction completed
FINGERPRINT_STATUS_DEFERRED = "deferred"               # NOT terminal: retry on a later tick
FINGERPRINT_STATUS_ABANDONED = "abandoned"             # terminal: retry budget exhausted
FINGERPRINT_STATUS_SKIPPED_NON_OWNER = "skipped_non_owner"  # terminal: peer_agent/other_human principal
TERMINAL_FINGERPRINT_STATUSES = frozenset({
    FINGERPRINT_STATUS_PROCESSED,
    FINGERPRINT_STATUS_ABANDONED,
    FINGERPRINT_STATUS_SKIPPED_NON_OWNER,
})

SCHEMA_VERSION = "memory-os.session_fact_extraction_run.v1"
FINGERPRINT_SCHEMA_VERSION = "memory-os.session_fact_extraction_fingerprint.v1"

# Closed set of documented skip reasons. A reader must be able to tell these
# apart from the persisted artifact alone, without re-running anything.
SKIPPED_REASON_CODES = frozenset({
    "state_db_absent",           # (a) no eligible input existed: state.db file does not exist
    "state_db_open_failed",      # (b) input existed but could not be read: the file is there, the
                                  # read-only open raised (corrupt, locked, permission) -- see error_records
    "sessions_table_missing",    # (a) no eligible input existed: state.db exists but lacks sessions/messages tables
    "no_sessions_in_window",     # (a) no eligible input existed: zero rows matched the started_at window
    "no_actionable_sessions",    # rows existed, but none are currently processable (already terminal
                                  # and/or non-owner/system principal) -- see sessions_skipped_by_principal
                                  # and sessions_skipped_already_processed for the breakdown
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
    """Combine session id + message_count + last_activity_at so a growing
    session is reconsidered.

    ``session_ref`` is state.db's ``sessions.id``; ``size`` is
    ``sessions.message_count``; ``mtime`` is ``sessions.last_activity_at``
    (falling back to ``started_at`` when NULL). This is the state.db
    analogue of the original file-based fingerprint's filename+size+mtime:
    computable from the session row alone, no need to read its messages just
    to check whether it was already processed.
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
    last_call_result: LlmCallResult | None = None
    for attempt in range(1 + MAX_EXTRACT_RETRIES):
        try:
            call_result = _call_hermes_runtime_model_result(prompt, effective)
        except Exception:
            # Defensive only: _call_hermes_runtime_model_result is designed to
            # never raise (every failure is a typed LlmCallResult).
            last_failure = "llm_exception"
            if attempt < MAX_EXTRACT_RETRIES:
                continue
            break
        last_call_result = call_result

        if call_result.failure_reason == "llm_empty_content":
            last_failure = "llm_empty_content"
            if attempt < MAX_EXTRACT_RETRIES:
                continue
            break
        if call_result.failure_reason:
            # Any other typed transport failure -- collapse to this module's
            # pre-existing "llm_exception" bucket (matching the pre-W2
            # behavior where every non-empty-response failure was a bare "").
            # The raw, finer-grained reason survives in _call_diagnostics.
            last_failure = "llm_exception"
            if attempt < MAX_EXTRACT_RETRIES:
                continue
            break

        response_text = call_result.text
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
                **_call_diagnostics(call_result),
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
            **_call_diagnostics(call_result),
        }

    # All retries exhausted. Defer -- do not manufacture a fact.
    return {
        "has_durable_fact": False,
        "fact": "",
        "reason": "llm_unavailable_extraction_deferred",
        "failure_reason": last_failure,
        **_call_diagnostics(last_call_result),
    }


# ── Candidate construction ──────────────────────────────────────────────


def _build_provenance_event(
    *,
    store: MemoryOSStore,
    session_id: str,
    platform: str,
    fingerprint: str,
    principal: str,
    shared_session_unsplit: bool,
) -> EventEnvelope:
    """Build the per-session provenance event that extracted facts cite.

    CE.2: the crystallized write gate requires non-empty source_event_ids on
    EVERY approval path (owner included), so a candidate born without event
    provenance can never be crystallized -- the lane's first five production
    candidates took the durable-fact bypass and crashed every
    candidate_aggregation tick. One metadata-only event per session per tick
    gives the whole chain a real anchor: crystallized -> event -> session.
    Mirrors session_mirror's event shape: candidate_allowed=False so the
    heartbeat candidate generator cannot mint a SECOND candidate from the
    provenance event itself (the facts already became candidates directly).

    ``principal`` (owner/unknown -- non-owner sessions never reach this
    function) is carried into ``safe_ref`` so a reader can distinguish a
    verified-owner fact from one captured under the pre-2026-09
    unconfigured-platform compatibility state without re-deriving it.
    """
    now = datetime.now(timezone.utc)
    unique = hashlib.sha256(f"{fingerprint}|{session_id}".encode("utf-8")).hexdigest()[:10]
    safe_session_id = _clip(str(session_id), 120)
    return EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=new_event_id(now, unique=unique),
        ts=now.isoformat(),
        profile=store.roots.profile or "default",
        source="session_fact_extraction",
        kind="session_fact_extracted",
        summary=f"Durable facts extracted from session {safe_session_id} ({platform or 'unknown'}).",
        safe_ref={
            "source_module": "session_fact_extraction",
            "session_id": safe_session_id,
            "platform": str(platform or "unknown"),
            "session_fingerprint": fingerprint,
            "candidate_allowed": False,
            "body_policy": "bounded_summary",
            "principal": str(principal or ""),
            "shared_session_unsplit": bool(shared_session_unsplit),
        },
        tags=["session", "fact_extraction", str(platform or "unknown")],
        sensitivity="private",
        body_policy="bounded_summary",
        hashes={},
        promotion_state="raw",
        # P2: first-class mirror of the same value already carried in
        # safe_ref["principal"] above (owner/unknown -- non-owner sessions
        # never reach this function).
        principal=str(principal or ""),
        principal_schema_version=EVENT_PRINCIPAL_SCHEMA_VERSION,
    )


def _build_candidate(
    *,
    session_id: str,
    platform: str,
    fingerprint: str,
    message_index: int,
    role: str,
    fact_text: str,
    source_event_ids: list[str],
    principal: str,
    shared_session_unsplit: bool,
) -> CrystallizedCandidate:
    # Identity material deliberately EXCLUDES the session fingerprint: the
    # fingerprint carries last_activity_at, so an appended-to session gets a
    # new one, and folding it in here would mint a fresh candidate_id for a
    # fact already extracted from an unchanged earlier message.
    # append_candidate_queue de-duplicates by candidate_id at write time
    # (crystallized.py:1116), so a STABLE id makes re-processing idempotent
    # while an activity-derived one defeats that guard and floods owner
    # review with duplicates every time a live session grows. Keyed on
    # (session_id, message_index, fact_text), all three of which are stable
    # across appends.
    material = f"{session_id}|{message_index}|{fact_text}"
    candidate_id = "cand_sfe_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    body = _clip(f"Extracted from session {session_id} ({platform}): {fact_text}", 600)
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="moment",
        body=body,
        # CE.2: never empty -- the crystallized write gate rejects
        # provenance-less candidates on every approval path.
        source_event_ids=list(source_event_ids),
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
            "principal": str(principal or ""),
            # True when this session's single user_id may not be the sender of
            # every message in it (see _session_sender_ambiguous) -- carried
            # per candidate so an owner reviewing one fact in isolation can see
            # it, not only the lane's aggregate tripwire counter.
            "shared_session_unsplit": bool(shared_session_unsplit),
        },
    )


# ── state.db access ──────────────────────────────────────────────────────


def _lookback_cutoff_epoch(now: datetime, lookback_days: int) -> float:
    """Numeric epoch-seconds cutoff for ``sessions.started_at``.

    MUST stay numeric. ``started_at`` is a REAL (epoch-seconds) column;
    comparing it against an ISO-formatted string does not raise -- SQLite's
    type affinity means a REAL-vs-TEXT comparison is always false, so the
    query silently returns zero rows regardless of how much real data exists
    in the window. See the module docstring's bounding section.
    """
    return (now - timedelta(days=max(int(lookback_days), 0))).timestamp()


def _sessions_and_messages_tables_present(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('sessions', 'messages')"
    ).fetchall()
    names = {row[0] for row in rows}
    return "sessions" in names and "messages" in names


def _fetch_candidate_sessions(
    conn: sqlite3.Connection, *, cutoff_epoch: float, limit: int
) -> list[sqlite3.Row]:
    """Newest-first sessions in the window, machine sources excluded in SQL.

    Machine sessions are ~95% of production volume (main, 30 days: 1131 of
    1190) and always resolve to principal ``system``. Left in, they fill the
    LIMIT window (~12 days of traffic at 500) so an owner session older than
    that would never be scanned and the backlog would never drain. They are
    counted separately (``_count_machine_sessions``) so the exclusion stays
    visible.
    """
    columns = ", ".join(_SESSION_SELECT_COLUMNS)
    machine = sorted(_MACHINE_SOURCES)
    placeholders = ", ".join("?" for _ in machine)
    return conn.execute(
        f"SELECT {columns} FROM sessions WHERE started_at >= ? AND lower(source) NOT IN ({placeholders}) "
        "ORDER BY started_at DESC LIMIT ?",
        (float(cutoff_epoch), *machine, max(int(limit), 0)),
    ).fetchall()


def _count_machine_sessions(conn: sqlite3.Connection, *, cutoff_epoch: float) -> int:
    machine = sorted(_MACHINE_SOURCES)
    placeholders = ", ".join("?" for _ in machine)
    row = conn.execute(
        f"SELECT COUNT(*) FROM sessions WHERE started_at >= ? AND lower(source) IN ({placeholders})",
        (float(cutoff_epoch), *machine),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _fetch_eligible_role_messages(
    conn: sqlite3.Connection, *, session_id: str, max_message_chars: int
) -> list[sqlite3.Row]:
    """Read user/assistant messages for one session, oldest first.

    Content is clipped to ``max_message_chars`` at the SQL layer via
    ``substr`` so an oversized body (measured up to 975,665 characters in
    production) never leaves SQLite as an unbounded Python string.
    ``MESSAGE_ELIGIBILITY_THRESHOLD_CHARS`` (140) is always far smaller than
    ``max_message_chars`` (knob-bounded to >= 500), so this clip never causes
    a message that should be eligible to read as under-threshold.
    """
    clip = max(int(max_message_chars), 1)
    return conn.execute(
        "SELECT role, substr(content, 1, ?) AS content, timestamp FROM messages "
        "WHERE session_id = ? AND role IN ('user', 'assistant') "
        "ORDER BY timestamp ASC LIMIT ?",
        (clip, session_id, _MESSAGE_READ_HARD_CAP),
    ).fetchall()


def _group_session_lacks_user_suffix(row: sqlite3.Row) -> bool:
    """True when a group-chat session's key does not carry its own user id.

    Hermes splits a group chat into one session per sender only when
    configured to do so; when it is not, every sender in the chat shares one
    session and the per-session ``user_id`` this lane's principal filter
    relies on stops meaning "the sender of this session's messages". Reported
    as an INFO tripwire (see the module docstring) -- never a gate here.
    """
    if str(row["chat_type"] or "") != "group":
        return False
    user_id = str(row["user_id"] or "").strip()
    session_key = str(row["session_key"] or "").strip()
    if not user_id or not session_key:
        return True
    return user_id not in session_key


def _session_sender_ambiguous(row: sqlite3.Row) -> bool:
    """True when the session's ``user_id`` may not be the sender of every
    message in it: an unsplit group chat, or a webhook session (its user id
    names the integration that posted, not a person)."""
    return _group_session_lacks_user_suffix(row) or str(row["chat_type"] or "") == "webhook"


# ── Lane entry point ─────────────────────────────────────────────────────


def run_session_fact_extraction_lane(
    store: MemoryOSStore,
    *,
    now: datetime | None = None,
    execution_gate_envelope_id: str = "",
) -> dict[str, Any]:
    """Run one tick of the session_fact_extraction cron lane.

    Reads state.db sessions within a bounded recent window (newest first),
    routes every scanned session through ``principal.resolve_principal()``
    (system/peer_agent/other_human sessions are skipped and counted, never
    extracted), and extracts durable facts from owner/unknown-eligible
    sessions' messages whose redacted length exceeds
    MESSAGE_ELIGIBILITY_THRESHOLD_CHARS, writing them as unapproved
    candidates via the existing governed candidate-queue path. Never
    crystallizes, never approves, never sends. Offline cron only (INV-5).
    """
    _now = now or datetime.now(timezone.utc)
    error_records: list[dict[str, Any]] = []

    from plugins.memory.memory_os.config import load_config
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
    max_sessions_scanned_per_tick = _safe_int_knob(
        "session_fact_extraction_max_sessions_scanned_per_tick", DEFAULT_CONFIG["max_sessions_scanned_per_tick"],
    )
    lookback_days = _safe_int_knob(
        "session_fact_extraction_lookback_days", DEFAULT_CONFIG["lookback_days"],
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

    memory_os_config = load_config(store.roots.hermes_home)

    def _base_report() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "lane_id": LANE_ID,
            "created_at": _now.isoformat().replace("+00:00", "Z"),
            "input_source": "state_db",
            "sessions_scanned": 0,
            "sessions_eligible": 0,
            "sessions_processed": 0,
            "sessions_skipped_already_processed": 0,
            "sessions_skipped_by_principal": {},
            "group_sessions_scanned": 0,
            "group_sessions_without_user_suffix": 0,
            "messages_considered": 0,
            "messages_eligible_over_threshold": 0,
            "facts_extracted": 0,
            "candidates_written": 0,
            "llm_calls": 0,
            "llm_failures_by_reason": {},
            "fallback_used_count": 0,
            # W2: typed LLM transport diagnostics (ADD-only; llm_failures_by_reason
            # above keeps its pre-W2 meaning/vocabulary unchanged).
            "llm_transport_failures_by_reason": {},
            "llm_provider": "",
            "llm_model": "",
            "llm_transport": "",
            "llm_usage_prompt_tokens": 0,
            "llm_usage_completion_tokens": 0,
            # W4-A / plan row L1: route-mismatch counters (ADD-only).
            "llm_route_unexpected_count": 0,
            "llm_route_unknown_count": 0,
            "llm_route_unexpected_expected_model": "",
            "llm_route_unexpected_actual_model": "",
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

    db_path = state_db_path(store.roots)

    if not db_path.exists():
        report = _base_report()
        report["skipped"] = True
        report["skipped_reason"] = "state_db_absent"
        report["error_records"] = error_records
        _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
        report["error_records"] = error_records
        return report

    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        error_records.append(
            build_error_record(
                component="session_fact_extraction.state_db",
                operation="open_state_db",
                error_code="state_db_open_failed",
                severity="error",
                recoverable=True,
                path=db_path,
                details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
            )
        )
        report = _base_report()
        report["skipped"] = True
        report["skipped_reason"] = "state_db_open_failed"
        report["error_records"] = error_records
        _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
        report["error_records"] = error_records
        return report

    try:
        try:
            tables_present = _sessions_and_messages_tables_present(conn)
        except Exception as exc:
            error_records.append(
                build_error_record(
                    component="session_fact_extraction.state_db",
                    operation="check_tables",
                    error_code="state_db_query_failed",
                    severity="error",
                    recoverable=True,
                    path=db_path,
                    details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                )
            )
            tables_present = False

        if not tables_present:
            report = _base_report()
            report["skipped"] = True
            report["skipped_reason"] = "sessions_table_missing"
            report["error_records"] = error_records
            _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
            report["error_records"] = error_records
            return report

        cutoff_epoch = _lookback_cutoff_epoch(_now, lookback_days)
        try:
            rows = _fetch_candidate_sessions(conn, cutoff_epoch=cutoff_epoch, limit=max_sessions_scanned_per_tick)
        except Exception as exc:
            error_records.append(
                build_error_record(
                    component="session_fact_extraction.state_db",
                    operation="query_sessions",
                    error_code="state_db_query_failed",
                    severity="error",
                    recoverable=True,
                    path=db_path,
                    details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                )
            )
            rows = []

        try:
            machine_sessions_in_window = _count_machine_sessions(conn, cutoff_epoch=cutoff_epoch)
        except Exception as exc:
            error_records.append(
                build_error_record(
                    component="session_fact_extraction.state_db",
                    operation="count_machine_sessions",
                    error_code="state_db_query_failed",
                    severity="warning",
                    recoverable=True,
                    path=db_path,
                    details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                )
            )
            machine_sessions_in_window = 0

        sessions_scanned = len(rows)

        if sessions_scanned == 0:
            report = _base_report()
            report["skipped"] = True
            if machine_sessions_in_window:
                report["skipped_reason"] = "no_actionable_sessions"
                report["sessions_skipped_by_principal"] = {PRINCIPAL_SYSTEM: machine_sessions_in_window}
            else:
                report["skipped_reason"] = "no_sessions_in_window"
            report["error_records"] = error_records
            _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
            report["error_records"] = error_records
            return report

        # ── Group-chat tripwire (INFO, computed over this tick's scanned window) ──
        group_sessions_scanned = 0
        group_sessions_without_user_suffix = 0
        for row in rows:
            if str(row["chat_type"] or "") == "group":
                group_sessions_scanned += 1
                if _group_session_lacks_user_suffix(row):
                    group_sessions_without_user_suffix += 1

        processed_fingerprints = read_processed_session_fingerprints(store)

        sessions_skipped_already_processed = 0
        sessions_skipped_by_principal: dict[str, int] = (
            {PRINCIPAL_SYSTEM: machine_sessions_in_window} if machine_sessions_in_window else {}
        )
        # (fingerprint, status, attempt) for terminal non-extraction outcomes
        # decided before the extraction loop (skipped_non_owner). Extraction
        # outcomes (processed/deferred/abandoned) are appended later.
        fingerprint_outcomes: list[tuple[str, str, int]] = []
        # (row, fingerprint, source, principal) -- newest-first, matching `rows`.
        owner_eligible: list[tuple[sqlite3.Row, str, str, str]] = []

        for row in rows:
            session_id = str(row["id"])
            source_norm = str(row["source"] or "").strip().lower()

            decision = resolve_principal(
                source=source_norm,
                author_id=row["user_id"],
                # Not available at the session level (state.db has no
                # per-message author_class) -- see the module docstring's
                # "Principal filter" section for why "" (never "unknown") is
                # the safe default here.
                author_class="",
                config=memory_os_config,
                session_id=session_id,
                non_primary_context=source_norm in _MACHINE_SOURCES,
            )

            if decision.principal == PRINCIPAL_SYSTEM:
                # Never fingerprinted: a pure, stable function of `source`
                # alone, and ~95% of production session volume -- persisting
                # a terminal row per session here would be an unbounded
                # ledger for zero benefit (see module docstring).
                sessions_skipped_by_principal[PRINCIPAL_SYSTEM] = (
                    sessions_skipped_by_principal.get(PRINCIPAL_SYSTEM, 0) + 1
                )
                continue

            fingerprint = _session_fingerprint(
                session_ref=session_id,
                size=int(row["message_count"] or 0),
                mtime=float(row["last_activity_at"] or row["started_at"] or 0.0),
            )

            if fingerprint in processed_fingerprints:
                sessions_skipped_already_processed += 1
                continue

            if decision.principal not in (PRINCIPAL_OWNER, PRINCIPAL_UNKNOWN):
                sessions_skipped_by_principal[decision.principal] = (
                    sessions_skipped_by_principal.get(decision.principal, 0) + 1
                )
                fingerprint_outcomes.append((fingerprint, FINGERPRINT_STATUS_SKIPPED_NON_OWNER, 0))
                continue

            owner_eligible.append((row, fingerprint, source_norm, decision.principal))

        sessions_eligible = len(owner_eligible)

        if sessions_eligible == 0:
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
                "sessions_skipped_already_processed": sessions_skipped_already_processed,
                "sessions_skipped_by_principal": sessions_skipped_by_principal,
                "group_sessions_scanned": group_sessions_scanned,
                "group_sessions_without_user_suffix": group_sessions_without_user_suffix,
                "skipped": True,
                "skipped_reason": "no_actionable_sessions",
            })
            report["error_records"] = error_records
            _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
            report["error_records"] = error_records
            return report

        selected = owner_eligible[: max(max_sessions_per_tick, 0)]

        messages_considered = 0
        messages_eligible_over_threshold = 0
        facts_extracted = 0
        candidates_written = 0
        llm_calls = 0
        llm_failures_by_reason: dict[str, int] = {}
        fallback_used_count = 0
        # W2: typed LLM transport diagnostics, aggregated across this tick's calls.
        llm_transport_failures_by_reason: dict[str, int] = {}
        llm_provider = ""
        llm_model = ""
        llm_transport = ""
        llm_usage_prompt_tokens = 0
        llm_usage_completion_tokens = 0
        # W4-A / plan row L1: route-mismatch counters, plus a sample of the
        # expected/actual model names from the most recent mismatch this
        # tick (see LlmCallResult's docstring for the definition and the
        # alias-handling note).
        llm_route_unexpected_count = 0
        llm_route_unknown_count = 0
        llm_route_unexpected_expected_model = ""
        llm_route_unexpected_actual_model = ""
        sessions_deferred_llm_failure = 0
        sessions_abandoned_after_max_attempts = 0
        deferral_attempts = read_session_deferral_attempts(store)

        for row, fingerprint, source_norm, principal in selected:
            session_id = str(row["id"])
            platform = source_norm

            try:
                message_rows = _fetch_eligible_role_messages(
                    conn, session_id=session_id, max_message_chars=max_message_chars,
                )
            except Exception as exc:
                error_records.append(
                    build_error_record(
                        component="session_fact_extraction.state_db",
                        operation="query_messages",
                        error_code="state_db_query_failed",
                        severity="warning",
                        recoverable=True,
                        details={
                            "error_type": type(exc).__name__,
                            "message": str(exc)[:200],
                            "session_id": _clip(session_id, 120),
                        },
                    )
                )
                # Terminal: a query that fails once for this session/query
                # shape will not become readable by retrying.
                fingerprint_outcomes.append((fingerprint, FINGERPRINT_STATUS_PROCESSED, 0))
                continue

            messages = [
                {"role": str(r["role"] or "unknown"), "content": str(r["content"] or "")}
                for r in message_rows
            ]
            messages_considered += len(messages)

            # Redact first (matches _turn_summary's redact-then-clip order), then
            # filter to messages whose redacted length exceeds the eligibility
            # threshold -- filtering BEFORE the per-session message cap, so a
            # session with a long tail of short "ok"/"thanks" turns after its
            # substantive messages does not starve the substantive ones out of
            # the bounded window.
            eligible_messages: list[tuple[int, dict[str, Any], str]] = []
            for idx, message in enumerate(messages):
                redacted = _redact_secrets(message["content"])
                if len(redacted) > MESSAGE_ELIGIBILITY_THRESHOLD_CHARS:
                    eligible_messages.append((idx, message, redacted))
            messages_eligible_over_threshold += len(eligible_messages)

            bounded_eligible = (
                eligible_messages[-max_messages_per_session:] if max_messages_per_session > 0 else eligible_messages
            )

            session_fact_count = 0
            session_llm_failed = False
            provenance_event_id: str | None = None
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

                # ── W2 transport diagnostics ────────────────────────────────
                transport_reason = str(result.get("llm_transport_failure_reason") or "")
                if transport_reason:
                    llm_transport_failures_by_reason[transport_reason] = (
                        llm_transport_failures_by_reason.get(transport_reason, 0) + 1
                    )
                if result.get("llm_provider"):
                    llm_provider = str(result["llm_provider"])
                if result.get("llm_model"):
                    llm_model = str(result["llm_model"])
                if result.get("llm_transport"):
                    llm_transport = str(result["llm_transport"])
                llm_usage_prompt_tokens += int(result.get("llm_usage_prompt_tokens") or 0)
                llm_usage_completion_tokens += int(result.get("llm_usage_completion_tokens") or 0)
                if result.get("llm_route_unexpected"):
                    llm_route_unexpected_count += 1
                    llm_route_unexpected_expected_model = str(result.get("llm_expected_model") or "")
                    llm_route_unexpected_actual_model = str(result.get("llm_actual_model") or "")
                if result.get("llm_route_unknown"):
                    llm_route_unknown_count += 1
                # ─────────────────────────────────────────────────────────────

                if not result.get("has_durable_fact"):
                    continue

                fact_text = str(result.get("fact") or "").strip()
                if not fact_text:
                    continue

                facts_extracted += 1
                session_fact_count += 1

                try:
                    # Lazy per-session provenance event: minted once, on the first
                    # fact, and cited by every fact candidate from this session.
                    # Written BEFORE the candidate so a candidate can never exist
                    # without its anchor (the reverse order could).
                    if provenance_event_id is None:
                        provenance_event = _build_provenance_event(
                            store=store,
                            session_id=session_id,
                            platform=platform,
                            fingerprint=fingerprint,
                            principal=principal,
                            shared_session_unsplit=_session_sender_ambiguous(row),
                        )
                        store.append_event(provenance_event)
                        provenance_event_id = provenance_event.id
                    candidate = _build_candidate(
                        session_id=session_id,
                        platform=platform,
                        fingerprint=fingerprint,
                        message_index=idx,
                        role=str(message.get("role") or "unknown"),
                        fact_text=fact_text,
                        source_event_ids=[provenance_event_id],
                        principal=principal,
                        shared_session_unsplit=_session_sender_ambiguous(row),
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
            "sessions_skipped_already_processed": sessions_skipped_already_processed,
            "sessions_skipped_by_principal": sessions_skipped_by_principal,
            "group_sessions_scanned": group_sessions_scanned,
            "group_sessions_without_user_suffix": group_sessions_without_user_suffix,
            "messages_considered": messages_considered,
            "messages_eligible_over_threshold": messages_eligible_over_threshold,
            "facts_extracted": facts_extracted,
            "candidates_written": candidates_written,
            "llm_calls": llm_calls,
            "llm_failures_by_reason": llm_failures_by_reason,
            "fallback_used_count": fallback_used_count,
            "llm_transport_failures_by_reason": llm_transport_failures_by_reason,
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "llm_transport": llm_transport,
            "llm_usage_prompt_tokens": llm_usage_prompt_tokens,
            "llm_usage_completion_tokens": llm_usage_completion_tokens,
            "llm_route_unexpected_count": llm_route_unexpected_count,
            "llm_route_unknown_count": llm_route_unknown_count,
            "llm_route_unexpected_expected_model": llm_route_unexpected_expected_model,
            "llm_route_unexpected_actual_model": llm_route_unexpected_actual_model,
            "sessions_deferred_llm_failure": sessions_deferred_llm_failure,
            "sessions_abandoned_after_max_attempts": sessions_abandoned_after_max_attempts,
            "skipped": False,
            "skipped_reason": "",
        })
        report["error_records"] = error_records
        _append_run_report(store, report, execution_gate_envelope_id=execution_gate_envelope_id, error_records=error_records)
        report["error_records"] = error_records
        return report
    finally:
        conn.close()
