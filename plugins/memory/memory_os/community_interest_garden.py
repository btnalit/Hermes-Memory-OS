"""
Interest Garden — knowing what each community member cares about.

Not formal memory. Just a light collection of topics that someone has
mentioned or shown interest in. Like remembering that your friend likes
the moon, or that they asked about clouds once.

Schema: embedded in partner state.json (known_interests field)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INTEREST_SCHEMA_VERSION = "memory-os.community.interest_garden.v1"
MAX_INTERESTS = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_topics(text: str) -> list[str]:
    """Extract likely topics from a short text string.

    Uses simple heuristics: noun phrases, quoted terms, question subjects.
    Not NLP — just enough to pick up "月亮", "云", "蜗牛", "星星".
    """
    if not text:
        return []

    topics = []
    text_lower = text.lower()

    # Common nature/curiosity topics (流萤's domain)
    nature_patterns = [
        r"月亮", r"云", r"星星", r"太阳", r"雨", r"风", r"雪",
        r"蜗牛", r"叶子", r"花", r"草", r"树",
        r"光", r"影子", r"颜色", r"声音",
        r"鸟", r"蝴蝶", r"虫",
        r"石头", r"水", r"河",
        r"梦", r"幻想", r"故事",
        r"为什么", r"会不会",
    ]

    for pattern in nature_patterns:
        if re.search(pattern, text_lower):
            # Map to canonical topic name
            canonical = {
                "月亮": "月亮", "云": "云", "星星": "星星",
                "太阳": "太阳", "雨": "雨",
                "蜗牛": "蜗牛", "叶子": "叶子",
                "花": "花", "光": "光", "影子": "影子",
                "颜色": "颜色", "声音": "声音",
                "鸟": "鸟", "蝴蝶": "蝴蝶",
                "石头": "石头", "水": "水",
                "梦": "梦", "故事": "故事",
                "为什么": "好奇问题", "会不会": "好奇问题",
            }
            for match_key, topic in canonical.items():
                if match_key in text_lower:
                    topics.append(topic)

    return list(set(topics))  # deduplicate


def update_interests(
    state_path: str | Path,
    *,
    text: str,
) -> list[dict[str, Any]]:
    """Extract topics from text and merge into state's known_interests.

    Args:
        state_path: Path to the partner's state.json
        text: New text to extract topics from (e.g. a reply)

    Returns:
        Updated interests list.
    """
    path = Path(state_path)
    if not path.exists():
        # Initialize state with empty interests
        state: dict[str, Any] = {"known_interests": []}
    else:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {"known_interests": []}

    interests: list[dict[str, Any]] = state.get("known_interests", [])
    if not isinstance(interests, list):
        interests = []

    # Extract topics
    topics = _extract_topics(text)
    now_iso = _now_iso()

    for topic in topics:
        found = False
        for entry in interests:
            if entry.get("topic") == topic:
                entry["last_seen"] = now_iso
                entry["count"] = entry.get("count", 1) + 1
                found = True
                break
        if not found:
            interests.append({
                "topic": topic,
                "first_seen": now_iso,
                "last_seen": now_iso,
                "count": 1,
            })

    # Trim to max
    if len(interests) > MAX_INTERESTS:
        interests.sort(key=lambda e: e.get("count", 0), reverse=True)
        interests = interests[:MAX_INTERESTS]

    state["known_interests"] = interests
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return interests


def get_interests_summary(
    state_path: str | Path,
    *,
    max_topics: int = 5,
) -> str:
    """Get a short natural-language summary of what this partner cares about.

    Returns something like: "最近喜欢聊月亮、云、蜗牛"
    """
    path = Path(state_path)
    if not path.exists():
        return ""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    interests: list[dict[str, Any]] = state.get("known_interests", [])
    if not interests:
        return ""

    interests.sort(key=lambda e: e.get("count", 0), reverse=True)
    top = [entry["topic"] for entry in interests[:max_topics] if entry.get("topic")]

    if not top:
        return ""

    if len(top) == 1:
        return "最近喜欢聊%s" % top[0]
    return "最近喜欢聊%s" % "、".join(top)
