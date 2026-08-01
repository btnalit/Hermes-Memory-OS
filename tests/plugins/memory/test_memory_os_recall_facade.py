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

    def test_crystallized_retriever_excludes_revoked_records(self, tmp_path):
        from plugins.memory.memory_os.retrievers.crystallized import CrystallizedRetriever
        from plugins.memory.memory_os.retrievers.entity_graph import (
            _find_primary_record_ids,
            _read_record_body,
        )

        store = _make_store(_make_roots(tmp_path))
        (store.roots.crystallized_root / "active.md").write_text(
            "---\nid: mem-active\nkind: fact\ncanonical_state: active\napproved_by: owner\n---\nactive release boundary\n",
            encoding="utf-8",
        )
        (store.roots.crystallized_root / "revoked.md").write_text(
            "---\nid: mem-revoked\nkind: fact\ncanonical_state: owner_revoked\napproved_by: owner\n---\nrevoked release boundary\n",
            encoding="utf-8",
        )

        objects = CrystallizedRetriever().retrieve(store, "release boundary")

        assert [obj.source_ref for obj in objects] == ["crystallized:mem-active"]
        assert objects[0].authority_class == "owner_confirmed"
        assert _find_primary_record_ids(store.roots.crystallized_root, "release boundary") == ["mem-active"]
        assert _read_record_body(store.roots.crystallized_root, "mem-revoked") == ""

    def test_crystallized_retriever_exposes_structured_cooldown_escape_metadata(self, tmp_path):
        from plugins.memory.memory_os.retrievers.crystallized import CrystallizedRetriever

        store = _make_store(_make_roots(tmp_path))
        (store.roots.crystallized_root / "rules.md").write_text(
            "---\nid: rule-1\nkind: safety_rule\ncanonical_state: active\napproved_by: owner\n"
            "owner_pinned: true\nentity_refs: Flask, Memory-OS\n---\nFlask production safety boundary\n",
            encoding="utf-8",
        )

        objects = CrystallizedRetriever().retrieve(store, "Flask safety")

        assert len(objects) == 1
        assert objects[0].metadata["entity_refs"] == ["Flask", "Memory-OS"]
        assert objects[0].metadata["owner_approved_permanent"] is True
        assert objects[0].metadata["owner_pinned"] is True
        assert objects[0].metadata["safety_rule"] is True

    def test_provisional_or_non_owner_record_cannot_claim_owner_pin_or_safety_privilege(self, tmp_path):
        from plugins.memory.memory_os.retrievers.crystallized import CrystallizedRetriever

        store = _make_store(_make_roots(tmp_path))
        (store.roots.crystallized_root / "provisional.md").write_text(
            "---\nid: provisional-1\nkind: safety_rule\ncanonical_state: active\n"
            "approved_by: resolver\nprovisional: true\nowner_pinned: true\n---\nclaimed safety boundary\n",
            encoding="utf-8",
        )

        obj = CrystallizedRetriever().retrieve(store, "safety boundary")[0]

        assert obj.authority_class == "session_working"
        assert obj.metadata["owner_approved_permanent"] is False
        assert obj.metadata["owner_pinned"] is False
        assert obj.metadata["safety_rule"] is False

    def test_owner_approval_identity_is_exact_not_prefix_based(self, tmp_path):
        from plugins.memory.memory_os.retrievers.crystallized import CrystallizedRetriever

        store = _make_store(_make_roots(tmp_path))
        (store.roots.crystallized_root / "spoof.md").write_text(
            "---\nid: spoof-1\nkind: safety_rule\ncanonical_state: active\n"
            "approved_by: ownership_attacker\nowner_pinned: true\n---\nspoof safety boundary\n",
            encoding="utf-8",
        )

        obj = CrystallizedRetriever().retrieve(store, "spoof safety boundary")[0]

        assert obj.authority_class == "session_working"
        assert obj.metadata["owner_approved_permanent"] is False
        assert obj.metadata["owner_pinned"] is False
        assert obj.metadata["safety_rule"] is False

    def test_indexed_fts_retriever_uses_real_index_schema_and_excludes_revoked_records(self, tmp_path):
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.retrievers.indexed_fts import IndexedFTSRetriever

        store = _make_store(_make_roots(tmp_path))
        (store.roots.crystallized_root / "active.md").write_text(
            "---\nid: mem-active\nkind: fact\ncanonical_state: active\napproved_by: owner\n---\nactive release boundary\n",
            encoding="utf-8",
        )
        (store.roots.crystallized_root / "revoked.md").write_text(
            "---\nid: mem-revoked\nkind: fact\ncanonical_state: active\napproved_by: owner\n---\nrevoked release boundary\n",
            encoding="utf-8",
        )
        MemoryOSIndex(store.roots).rebuild_from_store(store)
        (store.roots.crystallized_root / "revoked.md").write_text(
            "---\nid: mem-revoked\nkind: fact\ncanonical_state: owner_revoked\napproved_by: owner\n---\nrevoked release boundary\n",
            encoding="utf-8",
        )

        objects = IndexedFTSRetriever().retrieve(store, "release boundary")

        assert [obj.source_ref for obj in objects] == ["fts5:mem-active"]
        assert objects[0].content == "active release boundary"
        assert objects[0].authority_class == "indexed_derived"

    @pytest.mark.parametrize("record_type", ["event", "crystallized_candidate"])
    def test_indexed_fts_retriever_excludes_derived_rows_missing_from_canonical_store(
        self, tmp_path, record_type,
    ):
        import sqlite3

        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.retrievers.indexed_fts import IndexedFTSRetriever

        store = _make_store(_make_roots(tmp_path))
        MemoryOSIndex(store.roots).rebuild_from_store(store)
        with sqlite3.connect(store.roots.index_path) as conn:
            conn.execute(
                "insert into memory_fts (record_type, record_id, title, text) values (?, ?, ?, ?)",
                (record_type, "stale-derived", "stale", "stale authority nonce"),
            )

        assert IndexedFTSRetriever().retrieve(store, "stale authority nonce") == []

    def test_indexed_fts_retriever_fails_closed_when_active_canonical_body_changed_after_index(self, tmp_path):
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.retrievers.indexed_fts import IndexedFTSRetriever

        store = _make_store(_make_roots(tmp_path))
        path = store.roots.crystallized_root / "active.md"
        path.write_text(
            "---\nid: mem-active\nkind: fact\ncanonical_state: active\napproved_by: owner\n---\nold release boundary\n",
            encoding="utf-8",
        )
        MemoryOSIndex(store.roots).rebuild_from_store(store)
        path.write_text(
            "---\nid: mem-active\nkind: fact\ncanonical_state: active\napproved_by: owner\n---\nnew unrelated canonical truth\n",
            encoding="utf-8",
        )

        assert IndexedFTSRetriever().retrieve(store, "old release boundary") == []

    def test_indexed_fts_top_k_backfills_past_any_number_of_stale_or_revoked_hits(self, tmp_path):
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.retrievers.indexed_fts import IndexedFTSRetriever

        store = _make_store(_make_roots(tmp_path))
        for index in range(30):
            (store.roots.crystallized_root / f"stale-{index:02d}.md").write_text(
                f"---\nid: stale-{index}\nkind: fact\ncanonical_state: active\napproved_by: owner\n---\n"
                + "release boundary " * 8,
                encoding="utf-8",
            )
        (store.roots.crystallized_root / "z-active.md").write_text(
            "---\nid: active\nkind: fact\ncanonical_state: active\napproved_by: owner\n---\nrelease boundary weaker surviving fact\n",
            encoding="utf-8",
        )
        MemoryOSIndex(store.roots).rebuild_from_store(store)
        for index in range(30):
            (store.roots.crystallized_root / f"stale-{index:02d}.md").write_text(
                f"---\nid: stale-{index}\nkind: fact\ncanonical_state: owner_revoked\napproved_by: owner\n---\n"
                + "release boundary " * 8,
                encoding="utf-8",
            )

        objects = IndexedFTSRetriever().retrieve(store, "release boundary", top_k=1)

        assert [obj.source_ref for obj in objects] == ["fts5:active"]

    def test_indexed_fts_retriever_preserves_bm25_relevance_before_top_k(self, tmp_path):
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.retrievers.indexed_fts import IndexedFTSRetriever

        store = _make_store(_make_roots(tmp_path))
        (store.roots.crystallized_root / "a-weak.md").write_text(
            "---\nid: weak\nkind: fact\ncanonical_state: active\napproved_by: owner\n---\nrelease boundary incidental filler words\n",
            encoding="utf-8",
        )
        (store.roots.crystallized_root / "z-strong.md").write_text(
            "---\nid: strong\nkind: fact\ncanonical_state: active\napproved_by: owner\n---\nrelease boundary release boundary release boundary\n",
            encoding="utf-8",
        )
        MemoryOSIndex(store.roots).rebuild_from_store(store)

        objects = IndexedFTSRetriever().retrieve(store, "release boundary", top_k=1)

        assert [obj.source_ref for obj in objects] == ["fts5:strong"]
        assert 0.0 < objects[0].score <= 1.0

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

    def test_session_injection_ledger_records_only_context_that_was_formatted(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        facade = RetrieverFacade(arbitration_mode="shadow")
        facade.register(StubRetriever(RecallType.STATE_OVERLAY, [
            RecallObject(
                recall_type="state_overlay",
                content="current task context that fills the tiny budget",
                source_ref="state:1",
                task_revision="task:r1",
            ),
        ]))
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, [
            RecallObject(recall_type="crystallized", content="stable memory excluded by budget", source_ref="mem:1"),
        ]))
        results = facade.retrieve(store, "memory", scope={"task_revision": "task:r1"})
        assert not any(item["reason"] == "session_duplicate" for item in facade.last_recall_plan["suppressed"])

        assert facade.format_context(results, budget=len("- current task context that fills the tiny budget"))
        facade.retrieve(store, "memory", scope={"task_revision": "task:r1"})

        session_suppressed = {
            item["source_ref"]
            for item in facade.last_recall_plan["suppressed"]
            if item["reason"] == "session_duplicate"
        }
        assert session_suppressed == {"state:1"}

    def test_session_injection_ledger_uses_exact_whole_objects_not_shared_text_prefixes(self, tmp_path):
        store = _make_store(_make_roots(tmp_path))
        common = "shared prefix exactly over twenty four characters "
        first = RecallObject(
            recall_type="state_overlay",
            content=common + "first",
            source_ref="state:first",
            task_revision="task:r1",
        )
        second = RecallObject(
            recall_type="state_overlay",
            content=common + "second",
            source_ref="state:second",
            task_revision="task:r1",
        )
        retriever = StubRetriever(RecallType.STATE_OVERLAY, [first, second])
        facade = RetrieverFacade(arbitration_mode="shadow")
        facade.register(retriever)

        results = facade.retrieve(store, "shared", scope={"task_revision": "task:r1"})
        first_only = retriever.format_context([first])
        assert facade.format_context(results, budget=len(first_only)) == first_only

        facade.retrieve(store, "shared", scope={"task_revision": "task:r1"})
        suppressed = {
            item["source_ref"]
            for item in facade.last_recall_plan["suppressed"]
            if item["reason"] == "session_duplicate"
        }
        assert suppressed == {"state:first"}

    def test_session_ledger_never_marks_an_object_whose_tail_was_not_rendered(self, tmp_path):
        store = _make_store(_make_roots(tmp_path))
        content = "x" * 220 + "UNFORMATTED_TAIL"
        obj = RecallObject(
            recall_type="indexed_fts",
            content=content,
            source_ref="fts5:long",
            authority_class="indexed_derived",
            task_revision="task:r1",
        )
        retriever = StubRetriever(RecallType.INDEXED_FTS, [obj])
        from plugins.memory.memory_os.retrievers.indexed_fts import IndexedFTSRetriever
        retriever.format_context = IndexedFTSRetriever().format_context  # type: ignore[method-assign]
        facade = RetrieverFacade(arbitration_mode="apply_canary")
        facade.register(retriever)
        full_render = retriever.format_context([obj])

        first = facade.retrieve(store, "long", scope={"task_revision": "task:r1"})
        rendered = facade.format_context(first, budget=len(full_render))
        assert "UNFORMATTED_TAIL" in rendered

        second = facade.retrieve(store, "long", scope={"task_revision": "task:r1"})
        assert second == {}
        assert facade.last_recall_plan["suppressed"][0]["reason"] == "session_duplicate"

    def test_session_ledger_suppresses_duplicates_when_no_active_task_revision_exists(self, tmp_path):
        store = _make_store(_make_roots(tmp_path))
        obj = RecallObject(
            recall_type="indexed_fts",
            content="ordinary session recall",
            source_ref="fts5:no-task",
            authority_class="indexed_derived",
        )
        facade = RetrieverFacade(arbitration_mode="apply_canary")
        facade.register(StubRetriever(RecallType.INDEXED_FTS, [obj]))

        first = facade.retrieve(store, "ordinary")
        assert facade.format_context(first, budget=200)
        second = facade.retrieve(store, "ordinary")

        assert second == {}
        assert facade.last_recall_plan["suppressed"][0]["reason"] == "session_duplicate"

    def test_facade_passes_current_query_for_implicit_entity_cooldown_escape(self, tmp_path):
        store = _make_store(_make_roots(tmp_path))
        obj = RecallObject(
            recall_type="crystallized",
            content="Flask deployment uses a blue-green boundary",
            source_ref="crystallized:flask",
            authority_class="approved_canonical",
            metadata={"entity_refs": ["Flask"]},
        )
        facade = RetrieverFacade(arbitration_mode="apply_canary")
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, [obj]))

        first = facade.retrieve(store, "先看 Flask 部署", scope={"task_revision": "task:r1"})
        assert facade.format_context(first, budget=300)
        second = facade.retrieve(store, "继续 Flask 部署下一步", scope={"task_revision": "task:r1"})

        assert second["crystallized"][0].source_ref == "crystallized:flask"
        assert facade.last_recall_plan["selected"][0]["cooldown_escape_reason"] == "current_query_entity"

    def test_shadow_facade_persists_metadata_only_matrix_bound_observation_and_invalidates_old_window(self, tmp_path):
        from plugins.memory.memory_os.jsonl_io import append_jsonl_locked, read_jsonl
        from plugins.memory.memory_os.recall_policy import (
            OBSERVATION_WINDOW_ID,
            read_recall_observation_window,
            recall_observation_path,
        )

        store = _make_store(_make_roots(tmp_path))
        path = recall_observation_path(store.roots)
        append_jsonl_locked(path, {
            "schema_version": "memory-os.recall_observation.v1",
            "observation_window_id": "old-version:old-digest",
            "observed_at": "2026-07-15T00:00:00Z",
        })
        facade = RetrieverFacade(arbitration_mode="shadow")
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, [
            RecallObject(
                recall_type="crystallized",
                content="private body must not enter observation ledger",
                source_ref="crystallized:private",
                authority_class="owner_confirmed",
            ),
        ]))

        facade.retrieve(store, "private query must not enter observation ledger")
        status = read_recall_observation_window(store.roots)
        rows = read_jsonl(path)

        assert status["window_reset_required"] is True
        assert status["invalidated_observation_count"] == 1
        assert status["current_observation_count"] == 1
        assert status["observation_window_id"] == OBSERVATION_WINDOW_ID
        current = rows[-1]
        assert current["observation_window_id"] == OBSERVATION_WINDOW_ID
        assert current["selected_count"] == 1
        serialized = json.dumps(current, ensure_ascii=False)
        assert "private query" not in serialized
        assert "private body" not in serialized
        assert not ({"query", "content", "object", "selected", "suppressed"} & set(current))

    def test_format_context_respects_budget(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        facade = RetrieverFacade()
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, [
            RecallObject(recall_type="crystallized", content="x" * 2000),
        ]))
        results = facade.retrieve(store, "test")
        ctx = facade.format_context(results, budget=100)
        assert len(results["crystallized"]) == 1
        assert len(ctx) <= 100

    def test_shadow_arbitration_reports_but_preserves_live_results(self, tmp_path):
        store = _make_store(_make_roots(tmp_path))
        facade = RetrieverFacade(arbitration_mode="shadow")
        duplicate = [
            RecallObject(recall_type="crystallized", content="same", source_ref="one"),
            RecallObject(recall_type="crystallized", content="same", source_ref="two"),
        ]
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, duplicate))

        results = facade.retrieve(store, "same", scope={"task_revision": "rev-1"})

        assert len(results["crystallized"]) == 2
        assert facade.last_recall_plan["mode"] == "shadow"
        assert facade.last_recall_plan["selected_count"] == 1
        assert facade.last_recall_plan["exact_duplicate_count"] == 1

    def test_apply_canary_arbitration_uses_plan(self, tmp_path):
        store = _make_store(_make_roots(tmp_path))
        facade = RetrieverFacade(arbitration_mode="apply_canary")
        facade.register(StubRetriever(RecallType.CRYSTALLIZED, [
            RecallObject(recall_type="crystallized", content="same", source_ref="one"),
            RecallObject(recall_type="crystallized", content="same", source_ref="two"),
        ]))

        results = facade.retrieve(store, "same", scope={"task_revision": "rev-1"})

        assert len(results["crystallized"]) == 1

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
        task = next(r for r in results if "temporal retriever" in r.content.lower())
        assert task.authority_class == "direct_current_task"
        assert task.metadata["critical_recall_class"] == "task_boundary"

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
