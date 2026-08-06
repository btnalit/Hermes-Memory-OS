"""T4 pins: the two FTS query paths are deliberately divergent — keep it loud.

`retrievers/indexed_fts.py::_fts5_safe_query` sanitizes + prefix-expands and
cross-validates hits against canonical bodies, with NO LIKE fallback;
`index.py::search` runs the raw query through FTS5 MATCH and falls back to a
LIKE scan when FTS returns nothing OR raises (malformed MATCH). Nothing pinned
either behavior before — this file is the first coverage of the fallback, so a
future "unification" must consciously break these tests rather than silently
change recall results.
"""

from __future__ import annotations

import pytest

from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.retrievers.indexed_fts import _fts5_safe_query
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


def _indexed_store(tmp_path, body: str):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="fts-pin-test")
    store = MemoryOSStore(roots)
    store.initialize()
    store.append_crystallized_record(
        "fts_pin.md",
        {
            "schema_version": "memory-os.crystallized.v0",
            "id": "cry_fts_pin_001",
            "kind": "note",
            "created_at": "2026-08-01T00:00:00Z",
            "approved_by": "owner",
            "approved_at": "2026-08-01T00:00:00Z",
            "source_event_ids": [],
            "tags": [],
            "sensitivity": "private",
            "hindsight_indexed": False,
        },
        body,
    )
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)
    return index


def test_fts5_safe_query_sanitizes_and_prefix_matches():
    assert _fts5_safe_query("hello (world)!") == "hello* world*"
    # Single-character terms stay bare (no prefix star).
    assert _fts5_safe_query("a beta") == "a beta*"
    # Fully-special input degrades to a harmless empty phrase, never a MATCH error.
    assert _fts5_safe_query("()!*") == '""'


def test_index_search_like_fallback_fires_on_fts_syntax_error(tmp_path):
    """index.search feeds the RAW query to MATCH; a malformed query raises
    inside _fts_hits (swallowed) and the LIKE scan answers instead. The
    retriever path would have sanitized first — this asymmetry is the pinned
    divergence."""
    index = _indexed_store(tmp_path, "syntax (error) probe body")

    result = index.search("(error", limit=5)

    assert result["mode"] == "indexed"
    assert result["hits"], "LIKE fallback must answer when MATCH raises"
    assert result["hits"][0]["record_id"] == "cry_fts_pin_001"


def test_index_search_like_fallback_fires_on_zero_fts_hits(tmp_path):
    """A two-character query cannot match the trigram tokenizer (3-gram
    minimum) and unicode61 treats it as a distinct token — either way FTS
    returns nothing and the LIKE substring scan answers."""
    index = _indexed_store(tmp_path, "memory event body")

    result = index.search("em", limit=5)

    assert result["hits"], "LIKE fallback must answer when FTS finds nothing"
    assert result["hits"][0]["record_id"] == "cry_fts_pin_001"
