"""
Continuity freshness grading and disclosure for Memory-OS.

Defines structured freshness policy for current task, open threads,
recent decisions, and capability maps.  Each continuity object carries a
freshness timestamp and a stale_after duration; when the age exceeds
stale_after the object is graded ``stale``.

**Grading discloses; it never filters.**  A stale grade is published as a
``stale_task_revision`` finding — the upstream producer Gap Note needs — and
recorded in a report-only diagnostic ledger.  It does not remove anything from
recall, and it does not touch the recency filters that already exist
(``state_overlay.py`` 7-day owner-eligible candidate window, ``prefetch.py``
48-hour cross-session window, and ``recall_arbitration``'s freshness guard).
Those windows were measured against live behaviour;
``DEFAULT_STALE_AFTER`` below was written for an "inside one session" model
this system does not use.  It is therefore a **grading scale, not a gate** —
substituting its 2-hour open-thread value for the production 7-day window
would cut that context by ~84x on the strength of an unvalidated constant.

Do not "finish the job" by wiring these values into a filter.  See
``docs/resolver/hermes-memory-os-adoption-closure-plan.md`` §4.2 for the
ruling and its three independent reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

CONTINUITY_SCHEMA_VERSION = "memory-os.continuity.v1"
CONTINUITY_FRESHNESS_SCHEMA_VERSION = "memory-os.continuity_freshness.v0"

# The one reason code this module produces.  Gap Note's ``ELIGIBLE_REASON_CODES``
# recognises exactly two codes and, before this lane, Gap Note had no upstream it
# could actually read.
#
# There IS a second emitter of this same string — ``recall_arbitration.py:86`` —
# and a future reader grepping for the code will find it, so be precise about why
# it is not the producer Gap Note consumes:
#
#   1. It emits under key ``"reason"``; ``gap_note.build_gap_note_candidate``
#      reads ``"code"``.  Structurally invisible to Gap Note either way.
#   2. Its semantics differ: a STATE_OVERLAY object whose ``task_revision`` is
#      unequal to the current one — a *mismatch* test, not an *age* test.
#   3. It is dormant under default config (``recall_arbitration.mode = "off"``,
#      so the facade is never constructed and ``build_recall_plan`` never runs).
#   4. Its use is *suppression* — it drops the object — which is exactly the
#      behaviour the owner ruling rejects for continuity.
#
# So the two are complements, not duplicates: arbitration suppresses on revision
# identity, this module discloses on age.  Batch D must decide deliberately which
# one it renders rather than assuming there is only one.
STALE_TASK_REVISION_REASON_CODE = "stale_task_revision"


class FreshnessGrade(str):
    """Freshness grades for continuity objects."""

    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    UNKNOWN = "unknown"


DEFAULT_STALE_AFTER: dict[str, int] = {
    "current_task": 3600,       # 1 hour
    "open_thread": 7200,        # 2 hours
    "recent_decision": 43200,   # 12 hours
    "capability_map": 86400,    # 24 hours
}


def default_stale_after(kind: str) -> int:
    return DEFAULT_STALE_AFTER.get(kind, 3600)


@dataclass
class ContinuityObject:
    """A continuity object with freshness tracking."""

    kind: str
    object_id: str
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    stale_after_seconds: int = 3600
    revision: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def age_seconds(self, now: datetime | None = None) -> float | None:
        ref = now or datetime.now(timezone.utc)
        if not self.updated_at:
            return None
        try:
            from .timeutil import parse_utc
            # allow_naive=True is load-bearing, not laxity.  Every timestamp
            # this module grades is machine-written UTC, and ``task_state``
            # — the module that owns the current-task record — coerces a bare
            # naive stamp to UTC in its own age math.  Parsing strictly here
            # would return None for the same input that module accepts, and
            # None grades UNKNOWN, which never grades stale: the feature would
            # silently spin forever on exactly the records it exists to grade.
            # parse_utc still rejects date-only and second-less stamps; those
            # surface as UNKNOWN and are counted, never silently dropped.
            updated = parse_utc(self.updated_at, allow_naive=True)
            if updated is None:
                return None
            return (ref - updated).total_seconds()
        except (ValueError, TypeError):
            return None

    def freshness_grade(self, now: datetime | None = None) -> str:
        age = self.age_seconds(now)
        if age is None:
            return FreshnessGrade.UNKNOWN
        if age < 0:
            return FreshnessGrade.FRESH
        if age < self.stale_after_seconds * 0.75:
            return FreshnessGrade.FRESH
        if age < self.stale_after_seconds:
            return FreshnessGrade.AGING
        return FreshnessGrade.STALE

    def is_stale(self, now: datetime | None = None) -> bool:
        return self.freshness_grade(now) == FreshnessGrade.STALE

    def is_fresh(self, now: datetime | None = None) -> bool:
        return self.freshness_grade(now) == FreshnessGrade.FRESH

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONTINUITY_SCHEMA_VERSION,
            "kind": self.kind,
            "object_id": self.object_id,
            "summary": self.summary[:80],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stale_after_seconds": self.stale_after_seconds,
            "revision": self.revision,
            "freshness_grade": self.freshness_grade(),
            "is_stale": self.is_stale(),
        }


@dataclass
class ContinuityState:
    """Aggregate continuity state for a session."""

    current_task: ContinuityObject | None = None
    open_threads: list[ContinuityObject] = field(default_factory=list)
    recent_decisions: list[ContinuityObject] = field(default_factory=list)
    capability_map: ContinuityObject | None = None

    def active_open_threads(self, now: datetime | None = None) -> list[ContinuityObject]:
        """Return open threads that are not stale."""
        return [t for t in self.open_threads if not t.is_stale(now)]

    def stale_open_threads(self, now: datetime | None = None) -> list[ContinuityObject]:
        return [t for t in self.open_threads if t.is_stale(now)]

    def current_task_grade(self, now: datetime | None = None) -> str:
        """Grade the current task, treating "absent" as UNKNOWN — not stale.

        "There is no current task" and "the current task has expired" are
        different states and must not collapse.  They collapsed here until
        this lane: :meth:`current_task_is_stale` returned ``True`` for
        ``current_task is None``, so every fresh session with no anchor yet
        would have been graded stale.  Fed to a disclosure surface, that
        renders "your task information may be out of date" to an owner who
        has not started a task.
        """
        if self.current_task is None:
            return FreshnessGrade.UNKNOWN
        return self.current_task.freshness_grade(now)

    def current_task_is_stale(self, now: datetime | None = None) -> bool:
        """Return True only when a current task exists *and* has expired.

        Absence is not staleness — see :meth:`current_task_grade`.
        """
        return self.current_task_grade(now) == FreshnessGrade.STALE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONTINUITY_SCHEMA_VERSION,
            "current_task": self.current_task.to_dict() if self.current_task else None,
            "active_open_threads": len(self.active_open_threads()),
            "stale_open_threads": len(self.stale_open_threads()),
            "recent_decisions": len(self.recent_decisions),
            "has_capability_map": self.capability_map is not None,
        }


# ── Mapping: canonical current-task record → graded continuity object ───────


def build_current_task_continuity_object(
    record: dict[str, Any] | None,
    *,
    stale_after_seconds: int | None = None,
) -> ContinuityObject | None:
    """Map a ``task_state.read_effective_current_task`` projection to an object.

    Returns None when there is no effective current task — the caller must
    keep "absent" distinct from "stale" (see
    :meth:`ContinuityState.current_task_grade`).

    The state overlay is deliberately *not* the source here.  ``OverlayEntry``
    carries only ``text``/``source``/``source_kind``: the candidate timestamps
    it is built from are read and then dropped at
    ``state_overlay.py:_read_open_threads_from_candidates``, so nothing in the
    overlay projection can be graded.  ``read_effective_current_task`` instead
    projects ``source_at`` (``updated_at`` or ``created_at``) and ``revision``
    — and ``created_at`` is written by ``_active_task_anchor_record`` as
    ``.isoformat().replace("+00:00", "Z")``, so the writer is fully traceable.

    Metadata only: the anchor body is never copied into ``summary``.  This
    object feeds a JSONL diagnostic ledger, and the signal-collection contract
    forbids raw bodies on that surface.
    """
    if not isinstance(record, dict):
        return None
    updated_at = str(
        record.get("source_at")
        or record.get("updated_at")
        or record.get("created_at")
        or ""
    ).strip()
    try:
        revision = int(record.get("revision") or 0)
    except (TypeError, ValueError):
        revision = 0
    return ContinuityObject(
        kind="current_task",
        object_id=str(record.get("record_id") or ""),
        summary="",  # metadata-only surface — never the anchor body
        created_at=str(record.get("created_at") or ""),
        updated_at=updated_at,
        stale_after_seconds=(
            int(stale_after_seconds)
            if stale_after_seconds is not None
            else default_stale_after("current_task")
        ),
        revision=revision,
        metadata={
            "session_id": str(record.get("session_id") or ""),
            "status": str(record.get("status") or ""),
        },
    )


# ── Disclosure: findings, recall plan, diagnostic record ────────────────────


def build_continuity_findings(
    state: ContinuityState,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return Gap-Note-shaped findings for everything graded stale.

    Shape matches what ``gap_note.build_gap_note_candidate`` reads
    (``finding["code"]``), so batch D can consume this without a translation
    layer.  Note that ``recall_arbitration``'s same-named finding uses
    ``"reason"`` instead and is therefore invisible to Gap Note — see the
    comment on :data:`STALE_TASK_REVISION_REASON_CODE`.

    Only STALE produces a finding: AGING is a warning to the diagnostic ledger,
    not an owner-facing claim, and UNKNOWN is counted separately because
    "cannot tell" must never render as "out of date".
    """
    findings: list[dict[str, Any]] = []
    task = state.current_task
    if task is not None and state.current_task_grade(now) == FreshnessGrade.STALE:
        age = task.age_seconds(now)
        findings.append({
            "code": STALE_TASK_REVISION_REASON_CODE,
            "kind": task.kind,
            "object_id": task.object_id,
            "revision": task.revision,
            "freshness_grade": FreshnessGrade.STALE,
            "age_seconds": int(age) if age is not None else None,
            "stale_after_seconds": task.stale_after_seconds,
        })
    return findings


def build_continuity_recall_plan(
    state: ContinuityState,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a minimal recall-plan dict consumable by ``gap_note``.

    ``gap_note.build_gap_note_candidate`` reads ``plan["findings"]`` and
    ``plan["schema_version"]`` and nothing else.
    """
    return {
        "schema_version": CONTINUITY_FRESHNESS_SCHEMA_VERSION,
        "findings": build_continuity_findings(state, now=now),
    }


def build_continuity_freshness_record(
    state: ContinuityState,
    *,
    now: datetime | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Build the report-only diagnostic record for one grading pass.

    This is the "what did this recall grade, and what did it hide" record the
    owner ruling requires.  ``filters_applied``/``filtered_count`` are pinned
    to empty/0 on purpose: they are the machine-readable statement that
    grading hid nothing, so a future change that starts filtering cannot do it
    without this record contradicting itself.

    Metadata only — no bodies, no anchor text, no query.
    """
    ref = now or datetime.now(timezone.utc)
    graded: list[ContinuityObject] = []
    if state.current_task is not None:
        graded.append(state.current_task)
    graded.extend(state.open_threads)
    graded.extend(state.recent_decisions)
    if state.capability_map is not None:
        graded.append(state.capability_map)

    grade_counts: dict[str, int] = {
        FreshnessGrade.FRESH: 0,
        FreshnessGrade.AGING: 0,
        FreshnessGrade.STALE: 0,
        FreshnessGrade.UNKNOWN: 0,
    }
    for obj in graded:
        grade = obj.freshness_grade(ref)
        grade_counts[grade] = grade_counts.get(grade, 0) + 1

    findings = build_continuity_findings(state, now=ref)
    return {
        "schema_version": CONTINUITY_FRESHNESS_SCHEMA_VERSION,
        "recorded_at": ref.isoformat().replace("+00:00", "Z"),
        "session_id": str(session_id or ""),
        "mode": "disclose_only",
        "filters_applied": [],
        "filtered_count": 0,
        "graded_count": len(graded),
        "grade_counts": grade_counts,
        "unknown_grade_count": grade_counts.get(FreshnessGrade.UNKNOWN, 0),
        "current_task_present": state.current_task is not None,
        "current_task_grade": state.current_task_grade(ref),
        "current_task_object_id": (
            state.current_task.object_id if state.current_task is not None else ""
        ),
        "current_task_revision": (
            state.current_task.revision if state.current_task is not None else 0
        ),
        "stale_task_count": len(findings),
        "findings": findings,
        "raw_body_included": False,
    }


def continuity_freshness_signature(record: dict[str, Any]) -> str:
    """Identity of one grading *state*, so the ledger records transitions.

    Without this the ledger would grow one line per conversational turn, not
    one per state change.  ``stale_after`` for a current task is one hour, but
    the task anchor is only rewritten on an intent transition (defer / resume /
    cancel / new task) — so any single task worked on for longer than an hour
    keeps grading STALE on every turn, and the per-turn prefetch path would
    append to this file indefinitely.

    ``session_id`` is part of the identity on purpose: a new session seeing the
    same stale object is a new fact worth one line, and it is what makes a
    degraded answer locatable to a session.
    """
    if not isinstance(record, dict):
        return ""
    return "|".join((
        str(record.get("session_id") or ""),
        str(record.get("current_task_object_id") or ""),
        str(record.get("current_task_revision") or 0),
        str(record.get("current_task_grade") or ""),
        str(record.get("unknown_grade_count") or 0),
    ))


def continuity_freshness_record_is_reportable(record: dict[str, Any]) -> bool:
    """Return True when a grading pass found something worth recording.

    An all-fresh pass has no diagnostic value and would append one line per
    turn forever, so it is skipped.  UNKNOWN *is* reportable: an unparseable
    timestamp is how this feature would fail silently, and the counter is what
    makes that visible.
    """
    if not isinstance(record, dict):
        return False
    if record.get("findings"):
        return True
    try:
        return int(record.get("unknown_grade_count") or 0) > 0
    except (TypeError, ValueError):
        return False