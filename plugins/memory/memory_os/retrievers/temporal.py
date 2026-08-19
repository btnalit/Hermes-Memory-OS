"""Temporal retriever — time-anchored recall for session/event queries.

Handles queries like "上次" / "今天" / "最近" / "当时" / "之前" that
imply a temporal anchor.  Routes to recent event summaries, last session
anchors, and active task anchors — no LLM dependency.
"""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.event_stats import read_event_stats
from plugins.memory.memory_os.jsonl_io import read_jsonl_tail
from plugins.memory.memory_os.recall_types import RecallObject, RecallType
from plugins.memory.memory_os.roots import (
    LAST_SESSION_ANCHOR_TAIL_RECORDS,
    last_session_anchor_path,
)

if TYPE_CHECKING:
    from plugins.memory.memory_os.store import MemoryOSStore

# ── Temporal signal keywords ─────────────────────────────────────────
_TEMPORAL_PATTERNS: list[tuple[str, str]] = [
    (r"(上次|上一回|上回|刚才|刚刚)", "recent_past"),
    (r"(今天|今日)", "today"),
    (r"(最近|近来|这几天|这周)", "recent_window"),
    (r"(当时|那时候|之前|此前|以前)", "past_anchor"),
    (r"(之后|后来|然后|接下来)", "future_anchor"),
    (r"(这次|这回)", "current_anchor"),
]


def _detect_temporal_signals(query: str) -> list[str]:
    """Return temporal signal labels found in *query*."""
    signals: list[str] = []
    for pattern, label in _TEMPORAL_PATTERNS:
        if re.search(pattern, query):
            signals.append(label)
    return list(dict.fromkeys(signals))  # deduplicate, preserve order


def _is_temporal_query(query: str) -> bool:
    """Return True if *query* contains temporal keywords."""
    return bool(_detect_temporal_signals(query))


class TemporalRetriever:
    """Time-anchored recall from session and event sources.

    Only active when the query contains temporal keywords.
    Otherwise returns an empty list to avoid polluting non-temporal
    recall with irrelevant results.
    """

    @property
    def recall_type(self) -> RecallType:
        return RecallType.TEMPORAL

    def retrieve(
        self,
        store: "MemoryOSStore",
        query: str,
        *,
        top_k: int = 10,
        scope: dict[str, Any] | None = None,
    ) -> list[RecallObject]:
        if not _is_temporal_query(query):
            return []

        signals = _detect_temporal_signals(query)
        objects: list[RecallObject] = []
        roots = store.roots

        # 1) Last session anchors — most recent non-current session
        lsa_path = last_session_anchor_path(roots)
        if lsa_path.exists():
            records: list[dict[str, Any]] = []
            current_sid = str((scope or {}).get("session_id", ""))
            # Bounded tail read: the retriever runs per turn while the ledger
            # is append-only, so a full read grows with deployment age.  Only
            # the three newest anchors are used.  read_jsonl_tail absorbs
            # malformed lines and OS errors into bounded error records, so the
            # fail-open try/except this replaced is no longer needed.
            tail = read_jsonl_tail(
                lsa_path,
                max_records=LAST_SESSION_ANCHOR_TAIL_RECORDS,
                component="temporal_retriever",
                operation="last_session_anchors",
            )
            for record in tail.records:
                if current_sid and str(record.get("session_id", "")) == current_sid:
                    continue
                if record.get("foreground_summary"):
                    records.append(record)
            records.sort(key=lambda r: str(r.get("ended_at", "")), reverse=True)
            for record in records[:3]:
                summary = str(record.get("foreground_summary", ""))
                objects.append(RecallObject(
                    recall_type=RecallType.TEMPORAL.value,
                    content=summary[:300],
                    score=0.7,
                    source_ref=f"temporal:last_session:{str(record.get('session_id', ''))[:12]}",
                    metadata={
                        "anchor": "last_session",
                        "session_id": str(record.get("session_id", "")),
                        "ended_at": str(record.get("ended_at", "")),
                        "signals": signals,
                    },
                ))

        # 2) Active task anchor — current foreground task
        current_task_anchor = str((scope or {}).get("current_task_anchor", ""))
        if current_task_anchor.strip():
            objects.append(RecallObject(
                recall_type=RecallType.TEMPORAL.value,
                content=current_task_anchor[:300],
                score=0.85,
                source_ref="temporal:current_task",
                metadata={
                    "anchor": "current_task",
                    "signals": signals,
                    "critical_recall_class": "task_boundary",
                },
                authority_class="direct_current_task",
            ))

        # 3) Event stats — recent summaries
        #
        # Read through read_event_stats (which owns the file's location) —
        # never a path literal.  This branch spent its whole life pointed at
        # system/event_stats.json while the producer wrote runtime/, so
        # exists() was permanently False and the source contributed nothing,
        # with no error record to say so.
        #
        # The field read is recall_event_summaries, not recent_event_summaries:
        # the latter is a raw tail that on production is entirely machine
        # bookkeeping (cron mirror / governance rows).  Injecting that into
        # recall is worse than injecting nothing, which is why the path fix
        # and the kind filter had to land together.
        stats, _freshness = read_event_stats(roots)
        if stats is not None:
            for s in stats.recall_event_summaries[-5:]:
                summary = str(s.get("summary", "")).strip()
                if summary:
                    objects.append(RecallObject(
                        recall_type=RecallType.TEMPORAL.value,
                        content=summary[:200],
                        score=0.6,
                        source_ref=f"temporal:event:{s.get('kind', 'event')}",
                        metadata={"anchor": "event_stats", "signals": signals},
                    ))

        objects.sort(key=lambda o: o.score, reverse=True)
        return objects[:top_k]

    def format_context(
        self,
        objects: list[RecallObject],
        *,
        budget: int = 800,
    ) -> str:
        if not objects:
            return ""
        lines = ["### Temporal Recall"]
        for obj in objects:
            anchor = obj.metadata.get("anchor", "")
            tag = f" [{anchor}]" if anchor else ""
            lines.append(f"-{tag} {obj.content}")
        return "\n".join(lines)
