"""Tests for entity index, entity_graph retriever, and cron refresh."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.entity_index import (
    refresh_entity_index,
    query_related_records,
    entity_index_stats,
)


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


def _ensure_entity_index_table(db_path: Path) -> None:
    """Create the entity_index table if missing (mimics index.py schema)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        create table if not exists entity_index (
            entity_id text not null,
            entity_text text not null,
            record_id text not null,
            role text not null,
            proposed_by text not null default 'structural',
            created_at text not null,
            primary key (entity_id, record_id, role)
        )
    """)
    conn.commit()
    conn.close()


def _write_crystallized(roots: MemoryOSRoots, body: str,
                        record_id: str = "rec-001",
                        kind: str = "") -> None:
    path = roots.crystallized_root / f"{record_id}.md"
    front = f"---\nid: {record_id}\n"
    if kind:
        front += f"kind: {kind}\n"
    front += "---\n"
    path.write_text(front + body, encoding="utf-8")


# ── Entity index tests ───────────────────────────────────────────────


class TestEntityIndex:
    def test_refresh_indexes_entities_from_crystallized(self, tmp_path):
        roots = _make_roots(tmp_path)
        _ensure_entity_index_table(roots.index_path)
        _write_crystallized(roots, "Working on /opt/hermes/memory-os plugin",
                            record_id="rec-001")
        _write_crystallized(roots, "Also touching /etc/config/settings.json",
                            record_id="rec-002")

        report = refresh_entity_index(roots.index_path, roots.crystallized_root)
        assert report["status"] == "ok"
        assert report["entity_count"] >= 2  # at least the two paths

    def test_refresh_is_idempotent(self, tmp_path):
        roots = _make_roots(tmp_path)
        _ensure_entity_index_table(roots.index_path)
        _write_crystallized(roots, "Path: /opt/hermes/config.json",
                            record_id="rec-001")

        r1 = refresh_entity_index(roots.index_path, roots.crystallized_root)
        r2 = refresh_entity_index(roots.index_path, roots.crystallized_root)
        assert r1["entity_count"] == r2["entity_count"]

    def test_refresh_skipped_when_disabled(self, tmp_path):
        roots = _make_roots(tmp_path)
        _ensure_entity_index_table(roots.index_path)
        report = refresh_entity_index(
            roots.index_path, roots.crystallized_root, enabled=False,
        )
        assert report["status"] == "skipped"

    def test_refresh_no_crystallized_files(self, tmp_path):
        roots = _make_roots(tmp_path)
        _ensure_entity_index_table(roots.index_path)
        report = refresh_entity_index(roots.index_path, roots.crystallized_root)
        assert report["entity_count"] == 0

    def test_query_related_records_finds_shared_entities(self, tmp_path):
        roots = _make_roots(tmp_path)
        _ensure_entity_index_table(roots.index_path)
        _write_crystallized(roots, "Fixing /opt/hermes bug in index-sync",
                            record_id="rec-001")
        _write_crystallized(roots, "Working on /opt/hermes memory plugin",
                            record_id="rec-002")

        refresh_entity_index(roots.index_path, roots.crystallized_root)
        related = query_related_records(roots.index_path, ["rec-001"])
        assert len(related) >= 1
        assert "rec-002" in [r["related_record_id"] for r in related]
        # Should have a related_reason
        for r in related:
            assert "shared_entity" in r["related_reason"] or r["shared_entity"]

    def test_query_related_empty_db(self, tmp_path):
        roots = _make_roots(tmp_path)
        related = query_related_records(roots.index_path, ["rec-001"])
        assert related == []

    def test_entity_index_stats(self, tmp_path):
        roots = _make_roots(tmp_path)
        _ensure_entity_index_table(roots.index_path)
        _write_crystallized(roots, "Service hermes-gateway config at /etc/hermes/config.json",
                            record_id="rec-001")
        refresh_entity_index(roots.index_path, roots.crystallized_root)
        stats = entity_index_stats(roots.index_path)
        assert stats["entity_count"] >= 1
        assert stats["record_count"] >= 1


# ── EntityGraph retriever tests ──────────────────────────────────────


class TestEntityGraphRetriever:
    def test_retrieve_related_records(self, tmp_path):
        from plugins.memory.memory_os.retrievers.entity_graph import EntityGraphRetriever
        roots = _make_roots(tmp_path)
        _ensure_entity_index_table(roots.index_path)
        _write_crystallized(roots, "Fixing memory-os bug in /opt/hermes/bin",
                            record_id="rec-001")
        _write_crystallized(roots, "Deploying /opt/hermes/bin update",
                            record_id="rec-002")
        refresh_entity_index(roots.index_path, roots.crystallized_root)
        store = _make_store(roots)

        retriever = EntityGraphRetriever()
        results = retriever.retrieve(store, "memory-os bug /opt/hermes")
        assert len(results) >= 1
        assert any(r.metadata.get("related_reason", "") for r in results)

    def test_retrieve_no_index(self, tmp_path):
        from plugins.memory.memory_os.retrievers.entity_graph import EntityGraphRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        retriever = EntityGraphRetriever()
        results = retriever.retrieve(store, "anything")
        assert results == []

    def test_format_context_shows_shared_entity(self, tmp_path):
        from plugins.memory.memory_os.retrievers.entity_graph import EntityGraphRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        retriever = EntityGraphRetriever()
        objects = [
            RecallObject(recall_type="entity_graph",
                         content="Related record content",
                         metadata={"related_reason": "shared_entity=/opt/hermes",
                                   "shared_entity": "/opt/hermes"}),
        ]
        ctx = retriever.format_context(objects)
        assert "/opt/hermes" in ctx
        assert "Related record" in ctx

    def test_recall_type_is_entity_graph(self):
        from plugins.memory.memory_os.retrievers.entity_graph import EntityGraphRetriever
        from plugins.memory.memory_os.recall_types import RecallType
        assert EntityGraphRetriever().recall_type == RecallType.ENTITY_GRAPH


# ── Cron script tests ────────────────────────────────────────────────


class TestEntityIndexRefreshScript:
    def test_script_help_works(self):
        import subprocess, sys
        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_entity_index_refresh.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_script_runs_with_no_data(self, tmp_path):
        import subprocess, sys
        home = tmp_path / ".hermes"
        (home / "memory-os" / "crystallized").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)
        (home / "memory-os" / "index").mkdir(parents=True)
        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_entity_index_refresh.py"

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(script),
             "--hermes-home", str(home),
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] in ("ok", "skipped")

    def test_script_with_crystallized_data(self, tmp_path):
        import subprocess, sys
        home = tmp_path / ".hermes"
        (home / "memory-os" / "crystallized").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)
        (home / "memory-os" / "index").mkdir(parents=True)
        _write_crystallized(
            MemoryOSRoots.from_hermes_home(str(home)),
            "Working on /opt/hermes/memory-os plugin",
            record_id="rec-001",
        )
        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_entity_index_refresh.py"

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(script),
             "--hermes-home", str(home),
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        # Disabled by default (knob entity_index_enabled=False)
        assert output["status"] in ("ok", "skipped")


# ── Cron registration test ───────────────────────────────────────────


class TestEntityIndexCronRegistration:
    def test_entity_index_refresh_in_cron_specs(self):
        from plugins.memory.memory_os.cron_registry import memory_os_cron_spec_by_key
        spec = memory_os_cron_spec_by_key("entity_index_refresh")
        assert spec is not None
        assert spec.name == "memory-os-entity-index-refresh"
        assert spec.no_agent is True

    def test_entity_graph_in_recall_probe(self):
        from scripts.memory_os_recall_probe import AVAILABLE_RETRIEVERS
        assert "entity_graph" in AVAILABLE_RETRIEVERS


# ── Helpers for the module ───────────────────────────────────────────
from plugins.memory.memory_os.recall_types import RecallObject
