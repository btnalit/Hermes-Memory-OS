"""Tests for crystallized expiry cliff and provisional decay governance.

Covers D.1-D.10 from hermes-crystallized-expiry-cliff-and-provisional-decay-spec.md.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


# ═══════════════════════════════════════════════════════════════════
# P3: parser fail-loud (D.10)
# ═══════════════════════════════════════════════════════════════════

def test_unparseable_file_produces_error_record(tmp_path):
    """D.10: Non-empty file yielding 0 records → audit crystallized_file_unparseable."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    # Write a .md file without valid frontmatter
    bad_path = store.roots.crystallized_root / "bad.md"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("this is not valid markdown\nno frontmatter here\n", encoding="utf-8")

    # read_records should return empty list and not raise
    records = service.read_records("bad.md")
    assert records == []

    # Audit should contain crystallized_file_unparseable
    audit_path = store.roots.audit_path
    assert audit_path.exists()
    audit_lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    unparseable_events = [
        json.loads(line)
        for line in audit_lines
        if json.loads(line).get("action") == "crystallized_file_unparseable"
    ]
    assert len(unparseable_events) == 1
    assert unparseable_events[0]["details"]["file_name"] == "bad.md"
    assert unparseable_events[0]["status"] == "warning"
