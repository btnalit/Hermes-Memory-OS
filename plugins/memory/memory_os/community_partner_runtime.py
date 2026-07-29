"""Embedded partner runtime — reads Sannai's shared notes and produces replies.

This module is the "partner runtime" for embedded-mode (notes-based) community
partners.  It is called from a cron job (community_partner_reply) and:

- Reads the roster to find embedded partners (channel="embedded-notes").
- For each such partner, reads sannai_says.jsonl entries after the
  partner's state cursor.
- Constructs a bounded prompt from soul.md + recent notes + the message.
- Calls the injected model_call callable (no direct API calls here).
- Appends the reply to replies.jsonl and updates notes/state.
- Respects budget limits; skips silently when over budget.
- Quiet "no reply" is always valid — the cron tick may produce nothing.

Memory boundary: the partner reads ONLY sannai_says.jsonl + its own directory.
It never reads Sannai's canonical memory, diary, events, or crystallized records.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .community import RosterEntry, get_roster
from .jsonl_io import append_jsonl_locked, write_json_atomic

logger = logging.getLogger(__name__)

RUNTIME_SCHEMA_VERSION = "memory-os.community.partner_runtime.v1"

_MAX_NOTES = 20           # max recent notes kept per partner
_MAX_NOTE_CHARS = 300     # max chars per note
_MAX_NOTE_TOTAL = 6000    # max total chars across all notes
_MAX_REPLY_TOKENS = 1000  # max model output tokens


@dataclass
class PartnerRuntimeState:
    """Persistent state for one embedded partner, stored in state.json."""

    cursor: int = 0                      # last-read line index in sannai_says.jsonl
    mood: str = "平静"
    last_interaction: str = ""
    pending_thoughts: list[str] = field(default_factory=list)
    topic_interest: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursor": self.cursor,
            "mood": self.mood,
            "last_interaction": self.last_interaction,
            "pending_thoughts": list(self.pending_thoughts),
            "topic_interest": list(self.topic_interest),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PartnerRuntimeState:
        return cls(
            cursor=int(data.get("cursor", 0)),
            mood=str(data.get("mood", "平静")),
            last_interaction=str(data.get("last_interaction", "")),
            pending_thoughts=list(data.get("pending_thoughts", [])),
            topic_interest=list(data.get("topic_interest", [])),
        )


def _load_partner_state(partner_dir: Path) -> PartnerRuntimeState:
    """Load partner runtime state from state.json."""
    state_path = partner_dir / "memory" / "state.json"
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return PartnerRuntimeState.from_dict(data)
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return PartnerRuntimeState()


def _save_partner_state(partner_dir: Path, state: PartnerRuntimeState) -> None:
    """Atomically save partner runtime state."""
    (partner_dir / "memory").mkdir(parents=True, exist_ok=True)
    write_json_atomic(partner_dir / "memory" / "state.json", state.to_dict())


def _load_notes(partner_dir: Path) -> list[str]:
    """Load partner notes; returns most recent _MAX_NOTES entries."""
    notes_path = partner_dir / "notes.jsonl"
    if not notes_path.exists():
        return []
    notes: list[str] = []
    try:
        for line in notes_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                text = str(entry.get("text", ""))
                if text:
                    notes.append(text)
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError:
        return []
    return notes[-_MAX_NOTES:]


def _append_note(partner_dir: Path, text: str) -> None:
    """Append one note to notes.jsonl, capping total chars."""
    if not text.strip():
        return
    text = text.strip()[:_MAX_NOTE_CHARS]

    # Read existing notes to check total size
    notes_path = partner_dir / "notes.jsonl"
    existing_lines: list[str] = []
    total_chars = 0
    if notes_path.exists():
        try:
            for line in notes_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                existing_lines.append(line)
                total_chars += len(line)
        except OSError:
            existing_lines = []
            total_chars = 0

    # Trim from front if over limit
    while total_chars + len(text) > _MAX_NOTE_TOTAL and existing_lines:
        removed = existing_lines.pop(0)
        total_chars -= len(removed)
    if total_chars + len(text) > _MAX_NOTE_TOTAL:
        return  # note too large even after trim; discard

    entry = json.dumps(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "text": text,
        },
        ensure_ascii=False,
    )
    try:
        with open(notes_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except OSError:
        pass


def _build_prompt(
    soul_md: str,
    recent_notes: list[str],
    message: dict[str, Any],
) -> str:
    """Build a bounded prompt for the partner model."""
    notes_section = ""
    if recent_notes:
        notes_section = "\n你最近的笔记（回忆）：\n" + "\n".join(f"- {n}" for n in recent_notes[-5:])

    prompt = f"""{soul_md}

{notes_section}

你现在收到 Sannai 给你的一张纸条：

> {message.get('text', '（没有内容）')}

请用你真实的性格回应她。如果是好奇的问题就好奇地回应，如果是分享就高兴地分享她的心情。
只说你想说的就好——不用太长，自然就好。
如果你没什么想说的，也可以不回复。"""
    return prompt.strip()


def run_once(
    memory_os_root: Path,
    model_call: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Run one tick of the partner runtime for all embedded partners.

    Args:
        memory_os_root: Path to Memory-OS root directory.
        model_call: Callable that takes a prompt string and returns the
            model's response text.  If None, no model call is made
            (dry-run / test mode).

    Returns:
        A dict with keys:
            - "partners_checked": int
            - "replies_written": int
            - "no_replies": int
            - "skipped": list[str]  # reasons for skipping
            - "errors": list[str]
    """
    result: dict[str, Any] = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "ts": datetime.now(timezone.utc).isoformat(),
        "partners_checked": 0,
        "replies_written": 0,
        "no_replies": 0,
        "skipped": [],
        "errors": [],
    }

    root = Path(memory_os_root).resolve()
    community_root = root / "community"
    roster_path = community_root / "roster.jsonl"
    shared_path = community_root / "shared" / "sannai_says.jsonl"

    if not roster_path.exists():
        result["skipped"].append("roster not found")
        return result

    # Load roster
    try:
        roster = get_roster(roster_path)
    except (OSError, ValueError) as exc:
        result["errors"].append(f"failed to load roster: {exc}")
        return result

    # Find embedded partners: channel == "embedded-notes" and status == "active"
    embedded_partners = [
        entry for entry in roster
        if entry.channel == "embedded-notes" and entry.status == "active"
    ]

    if not embedded_partners:
        result["skipped"].append("no active embedded partners found")
        return result

    # Read sannai_says
    says_lines: list[str] = []
    if shared_path.exists():
        try:
            says_lines = shared_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            result["errors"].append(f"failed to read sannai_says: {exc}")
            return result

    for entry in embedded_partners:
        result["partners_checked"] += 1
        pid = entry.id
        partner_dir = community_root / "partners" / pid

        if not partner_dir.exists():
            result["skipped"].append(f"{pid}: partner directory not found")
            continue

        # Load state
        state = _load_partner_state(partner_dir)
        cursor = state.cursor

        # Find unread messages
        unread_lines = says_lines[cursor:]
        unread_parsed: list[dict[str, Any]] = []
        for i, line in enumerate(unread_lines):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    unread_parsed.append(parsed)
            except (json.JSONDecodeError, ValueError):
                continue

        if not unread_parsed:
            # Nothing new; still a valid "no reply" tick
            result["no_replies"] += 1
            continue

        # Read soul.md
        soul_path = partner_dir / "SOUL.md"
        soul_md = ""
        if soul_path.exists():
            try:
                soul_md = soul_path.read_text(encoding="utf-8")
            except OSError:
                soul_md = ""
        if not soul_md:
            result["skipped"].append(f"{pid}: no SOUL.md found")
            continue

        # Read recent notes
        recent_notes = _load_notes(partner_dir)

        # Process last unread message
        last_msg = unread_parsed[-1]

        # Build prompt
        prompt = _build_prompt(soul_md, recent_notes, last_msg)

        # Call model (if provided)
        reply_text = ""
        if model_call is not None:
            try:
                reply_text = model_call(prompt)
            except Exception as exc:
                result["errors"].append(f"{pid}: model_call failed: {type(exc).__name__}: {exc}")
                continue
        else:
            # Dry-run mode: no model call; still record the tick
            result["no_replies"] += 1
            continue

        reply_text = reply_text.strip()
        if not reply_text:
            # Partner chose not to reply — valid "no reply"
            result["no_replies"] += 1
            note_text = f"收到 Sannai 的消息但暂时没什么想回的。"
            _append_note(partner_dir, note_text)
            # Update cursor + interaction timestamp
            state.cursor = cursor + len(unread_lines)
            state.last_interaction = datetime.now(timezone.utc).isoformat()
            _save_partner_state(partner_dir, state)
            continue

        # Write reply to replies.jsonl
        reply_entry = json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "reply_to_ts": last_msg.get("ts", ""),
                "text": reply_text,
            },
            ensure_ascii=False,
        )
        replies_path = partner_dir / "replies.jsonl"
        try:
            with open(replies_path, "a", encoding="utf-8") as f:
                f.write(reply_entry + "\n")
        except OSError as exc:
            result["errors"].append(f"{pid}: failed to write reply: {exc}")
            continue

        result["replies_written"] += 1

        # Update notes
        note_text = reply_text[:_MAX_NOTE_CHARS]
        _append_note(partner_dir, note_text)

        # Update state
        state.cursor = cursor + len(unread_lines)
        state.last_interaction = datetime.now(timezone.utc).isoformat()
        if "?" in reply_text or "？" in reply_text:
            if "好奇" not in state.mood.lower():
                state.mood = "好奇"
        elif "!" in reply_text or "！" in reply_text:
            if "高兴" not in state.mood.lower():
                state.mood = "高兴"
        else:
            state.mood = "平静"
        _save_partner_state(partner_dir, state)

    return result
