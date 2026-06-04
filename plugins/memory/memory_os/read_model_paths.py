"""Neutral read-model path helpers shared across Memory-OS modules."""

from __future__ import annotations

from pathlib import Path

from .roots import MemoryOSRoots


def owner_actions_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "owner_actions.jsonl"


def session_mirror_apply_records_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "session_mirror_applies.jsonl"
