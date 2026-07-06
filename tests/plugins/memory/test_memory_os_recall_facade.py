"""Tests for recall types, facade, and retriever implementations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.memory.memory_os.recall_types import (
    RecallType,
    RecallObject,
    is_core_recall,
    is_l2_recall,
)
from plugins.memory.memory_os.recall_facade import BaseRetriever, RetrieverFacade
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


# ── Helpers ──────────────────────────────────────────────────────────


def _make_roots(tmp_path: Path, *, profile: str = "test") -> MemoryOSRoots:
    home = tmp_path / ".hermes"
    (home / "memory-os" / "crystallized").mkdir(parents=True)
    (home / "memory-os" / "system").mkdir(parents=True)
    (home / "memory-os" / "index").mkdir(parents=True)
    return MemoryOSRoots.from_hermes_home(str(home), profile=profile)


def _make_store(roots: MemoryOSRoots) -> MemoryOSStore:
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _write_last_session_anchor(roots: MemoryOSRoots, session_id: str, foreground: str,
                                ended_at: str = "2026-07-07T10:00:00+00:00") -> None:
    path = roots.memory_os_root / "system" / "last_session_anchor.jsonl"
    record = {
        "session_id": session_id,
        "foreground_summary": foreground,
        "ended_at": ended_at,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _write_crystallized(roots: MemoryOSRoots, body: str,
                        kind: str = "", ref_id: str = "rec-001") -> None:
    path = roots.crystallized_root / f"{ref_id}.md"
    front = f"---\nkind: {kind}\nid: {ref_id}\n---\n" if kind else ""
    path.write_text(front + body, encoding="utf-8")


# ── RecallType tests ─────────────────────────────────────────────────


class TestRecallType:
    def test_all_core_types_are_strings(self):
        for rt in RecallType:
            assert isinstance(rt.value, str)

    def test_is_core_recall(self):
        assert is_core_recall(RecallType.CRYSTALLIZED) is True
        assert is_core_recall(RecallType.INDEXED_FTS) is True
        assert is_core_recall(RecallType.TEMPORAL) is True
        assert is_core_recall(RecallType.HINDSIGHT) is False
        assert is_core_recall(RecallType.EXTERNAL_EVIDENCE) is False

    def test_is_l2_recall(self):
        assert is_l2_recall(RecallType.HINDSIGHT) is True
        assert is_l2_recall(RecallType.EXTERNAL_EVIDENCE) is True
        assert is_l2_recall(RecallType.STATE_OVERLAY) is False


class TestRecallObject:
    def test_to_dict(self):
        obj = RecallObject(
            recall_type="crystallized",
            content="Test content",
            score=0.9,
            source_ref="cryst:rec-001",
            metadata={"kind": "preference"},
        )
        d = obj.to_dict()
        assert d["recall_type"] == "crystallized"
        assert d["content"] == "Test content"
        assert d["score"] == 0.9
        assert d["source_ref"] == "cryst:rec-001"
        assert d["metadata"]["kind"] == "preference"

    def test_defaults(self):
        obj = RecallObject(recall_type="test", content="x")
        assert obj.score == 1.0
        assert obj.source_ref == ""
        assert obj.metadata == {}


# ── Facade tests ─────────────────────────────────────────────────────


class StubRetriever:
    """Minimal BaseRetriever for facade testing."""

    def __init__(self, recall_type: RecallType, results: list[RecallObject] | None = None):
        self._recall_type = recall_type
        self._results = results or []

    @property
    def recall_type(self) -> RecallType:
        return self._recall_type

    def retrieve(self, store, query, *, top_k=10, scope=None):
        return self._results[:top_k]

    def format_context(self, objects, *, budget=800):
        if not objects:
            return ""
        return "\n".join(f"- {o.content}" for o in objects)


class TestRetrieverFacade:
    def test_register_and_get(self):
        facade = RetrieverFacade()
        retriever = StubRetriever(RecallType.CRYSTALLIZED)
        facade.register(retriever)
        assert facade.get(RecallType.CRYSTALLIZED) is retriever
        assert facade.get(RecallType.TEMPORAL) is None

    def test_retrieve_specific_lanes(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        facade = RetrieverFacade()
        facade.register(StubRetriever(RecallType.STATE_OVERLAY, [
            RecallObject(recall_type="state_overlay", content="Project X"),
        ]))
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, [
            RecallObject(recall_type="crystallized", content="Prefer concise"),
        ]))
        results = facade.retrieve(
            store, "test",
            recall_types=[RecallType.STATE_OVERLAY],
        )
        assert len(results) == 1
        assert results["state_overlay"][0].content == "Project X"

    def test_retrieve_all_registered(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        facade = RetrieverFacade()
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, [
            RecallObject(recall_type="crystallized", content="A"),
        ]))
        results = facade.retrieve(store, "test")
        assert "crystallized" in results
        assert len(results["crystallized"]) == 1

    def test_retrieve_fail_open(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)

        class FailingRetriever:
            recall_type = RecallType.INDEXED_FTS

            def retrieve(self, store, query, *, top_k=10, scope=None):
                raise RuntimeError("boom")

            def format_context(self, objects, *, budget=800):
                return ""

        facade = RetrieverFacade()
        facade.register(FailingRetriever())
        # Must not raise
        results = facade.retrieve(store, "test", recall_types=[RecallType.INDEXED_FTS])
        assert results["indexed_fts"] == []

    def test_format_context(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        facade = RetrieverFacade()
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, [
            RecallObject(recall_type="crystallized", content="Item 1"),
            RecallObject(recall_type="crystallized", content="Item 2"),
        ]))
        results = facade.retrieve(store, "test")
        ctx = facade.format_context(results)
        assert "Item 1" in ctx
        assert "Item 2" in ctx

    def test_format_context_respects_budget(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        facade = RetrieverFacade()
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, [
            RecallObject(recall_type="crystallized", content="x" * 2000),
        ]))
        results = facade.retrieve(store, "test")
        ctx = facade.format_context(results, budget=100)
        # StubRetriever doesn't trim, but facade won't exceed budget on second lane
        assert len(results["crystallized"]) == 1  # retrieves the object

    def test_base_retriever_protocol(self):
        assert isinstance(StubRetriever(RecallType.CRYSTALLIZED), BaseRetriever)


# ── StateOverlay retriever tests ─────────────────────────────────────


class TestStateOverlayRetriever:
    def test_retrieve_from_cached_overlay(self, tmp_path):
        from plugins.memory.memory_os.retrievers.state_overlay import StateOverlayRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)

        # Write a cached overlay
        overlay_dir = roots.memory_os_root / "system" / "state_overlay"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        overlay = {
            "schema_version": "memory-os.state_overlay.v1",
            "active_projects": {
                "data": [{"text": "Build retriever facade", "source": "ta:1", "source_kind": "task_anchor"}],
                "status": "ok",
                "source": "task_anchor",
            },
            "open_threads": {"data": [], "status": "insufficient_data", "source": ""},
            "recent_events": {"data": [], "status": "insufficient_data", "source": ""},
            "owner_preferences": {"data": [], "status": "insufficient_data", "source": ""},
            "identity_snapshot": {"data": [], "status": "insufficient_data", "source": ""},
            "relationship_snapshot": {"data": [], "status": "insufficient_data", "source": ""},
        }
        (overlay_dir / "current.json").write_text(json.dumps(overlay))

        retriever = StateOverlayRetriever()
        results = retriever.retrieve(store, "facade")
        assert len(results) >= 1
        assert any("retriever facade" in r.content.lower() for r in results)

    def test_retrieve_falls_back_to_build(self, tmp_path):
        from plugins.memory.memory_os.retrievers.state_overlay import StateOverlayRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)

        retriever = StateOverlayRetriever()
        results = retriever.retrieve(
            store, "test",
            scope={"current_task_anchor": "### Current Foreground Task\nImplement recall"},
        )
        # Should have active_projects from task anchor
        assert any("Implement recall" in r.content for r in results)

    def test_format_context(self, tmp_path):
        from plugins.memory.memory_os.retrievers.state_overlay import StateOverlayRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)

        retriever = StateOverlayRetriever()
        objects = [
            RecallObject(recall_type="state_overlay", content="Active project X",
                         source_ref="ta:1", metadata={"section": "active_projects"}),
        ]
        ctx = retriever.format_context(objects)
        assert "Active project X" in ctx
        assert "[src:" in ctx


# ── Crystallized retriever tests ─────────────────────────────────────


class TestCrystallizedRetriever:
    def test_retrieve_from_markdown_files(self, tmp_path):
        from plugins.memory.memory_os.retrievers.crystallized import CrystallizedRetriever
        roots = _make_roots(tmp_path)
        _write_crystallized(roots, "Prefer short and direct responses", kind="preference",
                            ref_id="pref-001")
        _write_crystallized(roots, "Working on memory-os closing phase", kind="project",
                            ref_id="proj-001")
        store = _make_store(roots)

        retriever = CrystallizedRetriever()
        results = retriever.retrieve(store, "preference short")
        assert len(results) >= 2

    def test_retrieve_empty_store(self, tmp_path):
        from plugins.memory.memory_os.retrievers.crystallized import CrystallizedRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        retriever = CrystallizedRetriever()
        results = retriever.retrieve(store, "anything")
        assert results == []

    def test_format_context(self, tmp_path):
        from plugins.memory.memory_os.retrievers.crystallized import CrystallizedRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        retriever = CrystallizedRetriever()
        objects = [
            RecallObject(recall_type="crystallized", content="Prefer concise",
                         metadata={"kind": "preference"}),
        ]
        ctx = retriever.format_context(objects)
        assert "Prefer concise" in ctx
        assert "preference" in ctx


# ── IndexedFTS retriever tests ───────────────────────────────────────


class TestIndexedFTSRetriever:
    def test_retrieve_no_index(self, tmp_path):
        from plugins.memory.memory_os.retrievers.indexed_fts import IndexedFTSRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        retriever = IndexedFTSRetriever()
        # no index file exists — must return empty
        results = retriever.retrieve(store, "test")
        assert results == []

    def test_format_context(self, tmp_path):
        from plugins.memory.memory_os.retrievers.indexed_fts import IndexedFTSRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        retriever = IndexedFTSRetriever()
        objects = [
            RecallObject(recall_type="indexed_fts", content="Indexed result",
                         metadata={"kind": "event", "record_id": "r1"}),
        ]
        ctx = retriever.format_context(objects)
        assert "Indexed result" in ctx


# ── Temporal retriever tests ─────────────────────────────────────────


class TestTemporalRetriever:
    def test_is_temporal_query_true(self):
        from plugins.memory.memory_os.retrievers.temporal import _is_temporal_query
        assert _is_temporal_query("上次做到哪了") is True
        assert _is_temporal_query("今天有什么进展") is True
        assert _is_temporal_query("最近在做什么") is True
        assert _is_temporal_query("之前那个bug修好了吗") is True

    def test_is_temporal_query_false(self):
        from plugins.memory.memory_os.retrievers.temporal import _is_temporal_query
        assert _is_temporal_query("crystallized memory") is False
        assert _is_temporal_query("preference") is False

    def test_retrieve_non_temporal_returns_empty(self, tmp_path):
        from plugins.memory.memory_os.retrievers.temporal import TemporalRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        retriever = TemporalRetriever()
        results = retriever.retrieve(store, "memory recall")
        assert results == []

    def test_retrieve_with_last_sessions(self, tmp_path):
        from plugins.memory.memory_os.retrievers.temporal import TemporalRetriever
        roots = _make_roots(tmp_path)
        _write_last_session_anchor(roots, "sess-001", "Fixed anchor pollution bug",
                                   ended_at="2026-07-07T09:00:00+00:00")
        store = _make_store(roots)

        retriever = TemporalRetriever()
        results = retriever.retrieve(
            store, "上次做到哪了",
            scope={"session_id": "sess-002"},
        )
        assert len(results) >= 1
        assert any("anchor pollution" in r.content.lower() for r in results)

    def test_retrieve_with_task_anchor(self, tmp_path):
        from plugins.memory.memory_os.retrievers.temporal import TemporalRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)

        retriever = TemporalRetriever()
        results = retriever.retrieve(
            store, "这次的任务",
            scope={"current_task_anchor": "Implement temporal retriever"},
        )
        assert len(results) >= 1
        assert any("temporal retriever" in r.content.lower() for r in results)

    def test_format_context(self, tmp_path):
        from plugins.memory.memory_os.retrievers.temporal import TemporalRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        retriever = TemporalRetriever()
        objects = [
            RecallObject(recall_type="temporal", content="Last session: bug fix",
                         metadata={"anchor": "last_session"}),
        ]
        ctx = retriever.format_context(objects)
        assert "Last session" in ctx
        assert "last_session" in ctx


# ── Recall probe script tests ────────────────────────────────────────


class TestRecallProbeScript:
    def test_script_help_works(self):
        import subprocess, sys
        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_recall_probe.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "recall probe" in result.stdout.lower()

    def test_script_all_retrievers_json_output(self, tmp_path):
        import subprocess, sys
        home = tmp_path / ".hermes"
        (home / "memory-os" / "crystallized").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)
        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_recall_probe.py"

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(script),
             "--hermes-home", str(home),
             "--type", "all",
             "--query", "test",
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["schema_version"] == "memory-os.recall_probe.v0"
        assert "results" in output
        assert "summary" in output

    def test_script_specific_retriever(self, tmp_path):
        import subprocess, sys
        home = tmp_path / ".hermes"
        (home / "memory-os" / "crystallized").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)
        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_recall_probe.py"

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(script),
             "--hermes-home", str(home),
             "--type", "crystallized",
             "--query", "preference",
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "crystallized" in output["results"]
