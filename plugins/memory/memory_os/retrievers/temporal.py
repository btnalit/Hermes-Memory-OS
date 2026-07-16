"""Temporal retriever — time-anchored recall for session/event queries.

Handles queries like "上次" / "今天" / "最近" / "当时" / "之前" that
imply a temporal anchor.  Routes to recent event summaries, last session
anchors, and active task anchors — no LLM dependency.
"""

from __future__ import annotations

import json
import re
from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.recall_types import RecallObject, RecallType

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
        lsa_path = roots.memory_os_root / "system" / "last_session_anchor.jsonl"
        if lsa_path.exists():
            try:
                records: list[dict[str, Any]] = []
                current_sid = str((scope or {}).get("session_id", ""))
                for line in lsa_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        continue
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
            except (json.JSONDecodeError, OSError):
                pass

        # 2) Active task anchor — current foreground task
        current_task_anchor = str((scope or {}).get("current_task_anchor", ""))
        if current_task_anchor.strip():
            objects.append(RecallObject(
                recall_type=RecallType.TEMPORAL.value,
                content=current_task_anchor[:300],
                score=0.85,
                source_ref="temporal:current_task",
                metadata={"anchor": "current_task", "signals": signals},
            ))

        # 3) Event stats — recent summaries
        event_stats_path = roots.memory_os_root / "system" / "event_stats.json"
        if event_stats_path.exists():
            try:
                es = json.loads(event_stats_path.read_text(encoding="utf-8"))
                summaries = es.get("recent_event_summaries", [])
                if isinstance(summaries, list):
                    for s in summaries[-5:]:
                        if not isinstance(s, dict):
                            continue
                        summary = str(s.get("summary", "")).strip()
                        if summary:
                            objects.append(RecallObject(
                                recall_type=RecallType.TEMPORAL.value,
                                content=summary[:200],
                                score=0.6,
                                source_ref=f"temporal:event:{s.get('kind', 'event')}",
                                metadata={"anchor": "event_stats", "signals": signals},
                            ))
            except (json.JSONDecodeError, OSError):
                pass

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
