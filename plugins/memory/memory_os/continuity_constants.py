"""Continuity-selector constants — a leaf module with no Memory-OS imports.

These values are shared by ``prefetch`` (the live selector) and
``event_stats`` (the O(1) mirror of it).  They live here rather than in
``prefetch`` so that reading them does not require importing ``prefetch``:
``event_stats`` pulled the whole prefetch module in for three constants, and
once ``state_overlay`` needed ``event_stats`` that produced a genuine import
cycle (event_stats → prefetch → state_overlay → event_stats).

``prefetch`` re-imports these names, so ``prefetch._MAX_CONTINUITY_RECORDS``
and its siblings keep resolving for existing callers and tests.
"""

from __future__ import annotations

_BRIDGE_SEED_SLOTS = {
    "foreground": 2,
    "cron": 1,
    "mailbox": 1,
    "room_family": 1,
    "state_source": 1,
    "governance": 1,
}

_MAX_CONTINUITY_RECORDS = 8

# Bookkeeping event kinds are excluded from the selector's GLOBAL recency
# fill — and only from the fill. The seeded slots above stay untouched: one
# state_source line and one governance line per bridge is a pinned design
# (test_prefetch_continuity_selector_preserves_bridge_seed_events) giving the
# agent cross-lane awareness. The fill is a different animal: production's
# recent event window carries bursts of producer bookkeeping (a clearance
# cycle emitted 158 governance_resolver_approved + 118 _invalidated events),
# and a pure-recency fill lets one burst crowd every conversation turn out of
# Recent Event Summaries. Fail-open by construction: an UNKNOWN kind is never
# hidden — hiding requires opting into this list, so producer-vocabulary
# drift shows new kinds instead of losing them (the CC lesson, inverted to
# the safe side).
_BOOKKEEPING_FILL_KIND_MARKERS = (
    "governance_",
    "state_source_",
    "session_fact_extracted",
    "session_observed",
)
