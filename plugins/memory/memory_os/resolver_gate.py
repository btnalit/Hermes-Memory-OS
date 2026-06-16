"""Deterministic dual-axis gate for LLM auto-approval of memory candidates.

Pure deterministic — no LLM imports, no network, no I/O beyond
crystallized record lookup for side-effect detection.

Gate semantics:
- Reversible candidates: sensitivity in NON_SENSITIVE AND no identity signals
- Identity signals: detected via body+tags text scanning (kind is always "moment")
- Side effects: existing crystallized records with same candidate_id
"""

from __future__ import annotations

from typing import Any

from .crystallized import CrystallizedCandidate, CrystallizedMemoryService
from .store import MemoryOSStore

# ── 身份信号关键词 ──────────────────────────────────────────
IDENTITY_SIGNALS = frozenset({
    "identity", "persona", "personality", "soul", "who i am",
    "self-definition", "self definition", "i am", "我的身份",
    "我是谁", "人格", "自我定义", "红线", "约束", "边界",
    "redline", "constraint", "boundary", "永不", "永远不",
})

# ── 敏感度门 ────────────────────────────────────────────────
NON_SENSITIVE = frozenset({"normal", "low", "private"})
# "private" is the ONLY value in current production (inner_drive.py:51).
# "normal"/"low" included for forward-compatibility.

# ── 桥状态过滤器 ────────────────────────────────────────────
RESOLVER_ELIGIBLE_BRIDGE_STATES = frozenset({"", "inner_drive_candidate"})


def _has_identity_signal(body: str, tags: list[str]) -> bool:
    """Check body text and tags for identity-adjacent signals.

    Does NOT use candidate.kind because kind is always "moment"
    in current production (inner_drive.py:67).
    """
    body_lower = (body or "").lower()
    tags_lower = [str(t).lower() for t in (tags or [])]
    combined = body_lower + " " + " ".join(tags_lower)
    return any(sig.lower() in combined for sig in IDENTITY_SIGNALS)


def _triggers_side_effect(candidate: CrystallizedCandidate, store: MemoryOSStore) -> bool:
    """Check whether auto-approving this candidate would create a side effect."""
    try:
        service = CrystallizedMemoryService(store)
        existing = service.find_records_by_candidate_id(candidate.candidate_id)
        if existing:
            return True
    except Exception:
        return True
    return False


def is_reversible(candidate: CrystallizedCandidate, *, store: MemoryOSStore) -> bool:
    """Candidate is reversible if sensitivity is non-sensitive AND
    no identity signals AND no side effects."""
    return (
        candidate.sensitivity in NON_SENSITIVE
        and not _has_identity_signal(candidate.body, candidate.tags or [])
        and not _triggers_side_effect(candidate, store)
    )


def resolver_eligible(candidate: CrystallizedCandidate, *, store: MemoryOSStore) -> bool:
    """Candidate passes both resolver gates: reversibility + bridge state filter."""
    return (
        is_reversible(candidate, store=store)
        and candidate.bridge_state in RESOLVER_ELIGIBLE_BRIDGE_STATES
    )
