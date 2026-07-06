"""Tests for External Evidence Seam — D1-D5 coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.external_intake import external_intake


# ── Helpers ──────────────────────────────────────────────────────────


def _make_roots(tmp_path: Path, *, profile: str = "test") -> MemoryOSRoots:
    home = tmp_path / ".hermes"
    (home / "memory-os" / "events").mkdir(parents=True)
    (home / "memory-os" / "system").mkdir(parents=True)
    return MemoryOSRoots.from_hermes_home(str(home), profile=profile)


def _make_store(roots: MemoryOSRoots) -> MemoryOSStore:
    store = MemoryOSStore(roots)
    store.initialize()
    return store


# ── D1: external_intake hardening ────────────────────────────────────


class TestExternalIntake:
    def test_intake_rejects_empty_external_ref(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        with pytest.raises(ValueError, match="external_ref"):
            external_intake(store, content="test", external_ref="", provider="test")

    def test_intake_rejects_whitespace_external_ref(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        with pytest.raises(ValueError, match="external_ref"):
            external_intake(store, content="test", external_ref="   ", provider="test")

    def test_intake_creates_tainted_event(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        event_id = external_intake(
            store,
            content="External evidence about memory-os",
            external_ref="ext://doc-001",
            provider="test_provider",
        )
        assert event_id
        # Verify the event was appended
        events = store.read_events()
        tainted = [e for e in events if e.id == event_id]
        assert len(tainted) == 1
        event = tainted[0]
        assert event.kind == "external_evidence_intake"
        assert event.safe_ref["source_class"] == "external_evidence"
        assert event.safe_ref["external_ref"] == "ext://doc-001"
        assert "tainted" in event.tags

    def test_intake_truncates_long_content(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        long_content = "x" * 1000
        event_id = external_intake(
            store, content=long_content, external_ref="ext://long",
            provider="test",
        )
        events = store.read_events()
        event = [e for e in events if e.id == event_id][0]
        assert len(event.summary) <= 500

    def test_intake_stores_metadata(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        event_id = external_intake(
            store,
            content="Evidence with metadata",
            external_ref="ext://meta",
            provider="test",
            metadata={"source_page": 3, "confidence": 0.9},
        )
        events = store.read_events()
        event = [e for e in events if e.id == event_id][0]
        assert event.safe_ref["metadata"]["source_page"] == 3


# ── D2: Seam types + config ──────────────────────────────────────────


class TestEvidenceTypes:
    def test_evidence_chunk_valid(self):
        from plugins.seam.external_evidence.types import EvidenceChunk, EvidenceSource
        chunk = EvidenceChunk(
            content="test", external_ref="ref://1",
            source=EvidenceSource(provider="ragflow"),
        )
        assert chunk.is_valid() is True

    def test_evidence_chunk_invalid_empty_ref(self):
        from plugins.seam.external_evidence.types import EvidenceChunk
        chunk = EvidenceChunk(content="test", external_ref="")
        assert chunk.is_valid() is False

    def test_evidence_chunk_to_dict(self):
        from plugins.seam.external_evidence.types import EvidenceChunk, EvidenceSource
        chunk = EvidenceChunk(
            content="test content",
            external_ref="ref://1",
            source=EvidenceSource(provider="ragflow", dataset_id="ds-1"),
            score=0.85,
        )
        d = chunk.to_dict()
        assert d["content"] == "test content"
        assert d["external_ref"] == "ref://1"
        assert d["score"] == 0.85
        assert d["source"]["provider"] == "ragflow"


class TestSeamConfig:
    def test_load_missing_config_returns_defaults(self, tmp_path):
        from plugins.seam.external_evidence.config import load_seam_config
        config = load_seam_config(str(tmp_path))
        assert config["providers"] == {}

    def test_get_provider_config_defaults_disabled(self):
        from plugins.seam.external_evidence.config import get_provider_config
        cfg = get_provider_config({}, "ragflow")
        assert cfg["enabled"] is False
        assert cfg["base_url"] == ""

    def test_is_provider_enabled_false_by_default(self):
        from plugins.seam.external_evidence.config import is_provider_enabled
        assert is_provider_enabled({}, "ragflow") is False

    def test_provider_enabled_when_configured(self, tmp_path):
        from plugins.seam.external_evidence.config import (
            load_seam_config,
            get_provider_config,
            is_provider_enabled,
        )
        home = tmp_path / ".hermes"
        (home / "memory-os" / "system").mkdir(parents=True)
        cfg_path = home / "memory-os" / "system" / "seam_config.json"
        cfg_path.write_text(json.dumps({
            "providers": {
                "ragflow": {
                    "enabled": True,
                    "base_url": "http://10.20.3.200:9380",
                    "dataset_id": "memory-os-docs",
                },
            },
        }))
        config = load_seam_config(str(home))
        assert is_provider_enabled(config, "ragflow") is True
        assert get_provider_config(config, "ragflow")["base_url"] == "http://10.20.3.200:9380"

    def test_unknown_provider_always_disabled(self):
        from plugins.seam.external_evidence.config import get_provider_config
        cfg = get_provider_config({}, "nonexistent")
        assert cfg["enabled"] is False


# ── D3: ragflow_adapter mock tests ───────────────────────────────────


class TestRAGFlowAdapter:
    def test_adapter_disabled_by_default(self):
        from plugins.seam.external_evidence.ragflow_adapter import RAGFlowAdapter
        adapter = RAGFlowAdapter()
        assert adapter.enabled is False

    def test_adapter_search_returns_empty_when_disabled(self):
        from plugins.seam.external_evidence.ragflow_adapter import RAGFlowAdapter
        adapter = RAGFlowAdapter()
        results = adapter.search("test query")
        assert results == []

    def test_adapter_search_with_mock_client(self):
        from plugins.seam.external_evidence.ragflow_adapter import RAGFlowAdapter

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "data": {
                        "documents": [
                            {
                                "content": "Memory-OS uses file-first design",
                                "document_id": "doc-001",
                                "chunk_id": "chunk-001",
                                "score": 0.92,
                            },
                            {
                                "content": "External evidence is tainted by default",
                                "document_id": "doc-002",
                                "chunk_id": "chunk-002",
                                "score": 0.78,
                            },
                        ],
                    },
                }

        class MockClient:
            def post(self, url, *, json, headers, timeout):
                return MockResponse()

        config = {
            "providers": {
                "ragflow": {
                    "enabled": True,
                    "base_url": "http://localhost:9380",
                    "dataset_id": "test-ds",
                    "api_key_file": "",  # no key needed for mock
                },
            },
        }
        # Override api_key_file read — mock doesn't need it
        adapter = RAGFlowAdapter(config, client=MockClient())
        # Bypass api_key check for mock
        adapter._read_api_key = lambda: "mock-key"

        results = adapter.search("memory-os design", top_k=2)
        assert len(results) == 2
        assert results[0].content == "Memory-OS uses file-first design"
        assert results[0].score == 0.92
        assert results[0].source.provider == "ragflow"
        assert results[1].external_ref == "ragflow:doc-002:chunk-002"

    def test_adapter_search_empty_on_http_error(self):
        from plugins.seam.external_evidence.ragflow_adapter import RAGFlowAdapter

        class ErrorClient:
            def post(self, url, *, json, headers, timeout):
                raise ConnectionError("unreachable")

        config = {
            "providers": {
                "ragflow": {
                    "enabled": True,
                    "base_url": "http://localhost:9999",
                    "dataset_id": "test",
                },
            },
        }
        adapter = RAGFlowAdapter(config, client=ErrorClient())
        adapter._read_api_key = lambda: "key"
        results = adapter.search("query")  # must not raise
        assert results == []

    def test_adapter_search_empty_on_non_200(self):
        from plugins.seam.external_evidence.ragflow_adapter import RAGFlowAdapter

        class UnauthorizedResponse:
            status_code = 401

            def json(self):
                return {"error": "unauthorized"}

        class UnauthorizedClient:
            def post(self, url, *, json, headers, timeout):
                return UnauthorizedResponse()

        config = {
            "providers": {
                "ragflow": {
                    "enabled": True,
                    "base_url": "http://localhost:9380",
                    "dataset_id": "test",
                },
            },
        }
        adapter = RAGFlowAdapter(config, client=UnauthorizedClient())
        adapter._read_api_key = lambda: "key"
        results = adapter.search("query")
        assert results == []

    def test_chunks_missing_external_ref_are_skipped(self):
        from plugins.seam.external_evidence.ragflow_adapter import RAGFlowAdapter
        adapter = RAGFlowAdapter()
        # Parse a response where one document has no id
        data = {
            "data": {
                "documents": [
                    {"content": "Valid", "document_id": "d1", "id": "c1"},
                    {"content": "No ID", "document_id": "", "id": ""},
                ],
            },
        }
        chunks = adapter._parse_response(data, 5)
        assert len(chunks) == 1
        assert chunks[0].content == "Valid"


# ── D4: reconcile tests ──────────────────────────────────────────────


class TestLaunderingReconcile:
    def test_reconcile_no_data(self, tmp_path):
        from plugins.seam.external_evidence.reconcile import run_laundering_reconcile
        home = tmp_path / "home"
        crystallized = home / "crystallized"
        events = home / "events"
        crystallized.mkdir(parents=True)
        events.mkdir(parents=True)

        report = run_laundering_reconcile(crystallized, events)
        assert report["status"] == "ok"
        assert report["laundering_candidate_count"] == 0

    def test_reconcile_finds_laundering_candidates(self, tmp_path):
        from plugins.seam.external_evidence.reconcile import run_laundering_reconcile
        home = tmp_path / "home"
        crystallized = home / "crystallized"
        events = home / "events"
        crystallized.mkdir(parents=True)
        (events / "2026").mkdir(parents=True)

        # Write a tainted event
        event_record = json.dumps({
            "schema_version": "memory-os.event.v0",
            "id": "evt-001",
            "ts": "2026-07-07T10:00:00Z",
            "kind": "external_evidence_intake",
            "safe_ref": {
                "source_class": "external_evidence",
                "external_ref": "ragflow:doc-001:chunk-001",
            },
        })
        (events / "2026" / "07.jsonl").write_text(event_record + "\n")

        # Write a crystallized record referencing the same content
        (crystallized / "rec-001.md").write_text(
            "---\nid: rec-001\n---\nragflow:doc-001:chunk-001\nImportant findings about memory."
        )

        report = run_laundering_reconcile(crystallized, events)
        assert report["laundering_candidate_count"] >= 1
        finding = report["findings"][0]
        assert "rec-001.md" in finding["record_file"]
        assert "ragflow:doc-001:chunk-001" in finding["unacked_refs"]

    def test_reconcile_acked_ref_not_flagged(self, tmp_path):
        from plugins.seam.external_evidence.reconcile import run_laundering_reconcile
        home = tmp_path / "home"
        crystallized = home / "crystallized"
        events = home / "events"
        crystallized.mkdir(parents=True)
        (events / "2026").mkdir(parents=True)

        # Tainted event
        (events / "2026" / "07.jsonl").write_text(
            json.dumps({
                "schema_version": "memory-os.event.v0",
                "id": "evt-001",
                "ts": "2026-07-07T10:00:00Z",
                "kind": "external_evidence_intake",
                "safe_ref": {"source_class": "external_evidence",
                             "external_ref": "ragflow:doc-001:chunk-001"},
            }) + "\n" +
            # Owner ack event
            json.dumps({
                "schema_version": "memory-os.event.v0",
                "id": "evt-002",
                "ts": "2026-07-07T10:01:00Z",
                "kind": "owner_ack_external_evidence",
                "safe_ref": {"external_ref": "ragflow:doc-001:chunk-001"},
            }) + "\n"
        )

        (crystallized / "rec-001.md").write_text(
            "---\nid: rec-001\n---\nragflow:doc-001:chunk-001\nAck'd content."
        )

        report = run_laundering_reconcile(crystallized, events)
        assert report["laundering_candidate_count"] == 0


# ── D5: static hygiene guard ─────────────────────────────────────────


class TestExternalEvidenceStaticHygiene:
    def _find_in_dir(self, directory: Path, pattern: str) -> list[str]:
        """Find files containing *pattern* in *directory* (Python-native, no grep)."""
        matches: list[str] = []
        for py_file in sorted(directory.rglob("*.py")):
            try:
                text = py_file.read_text(encoding="utf-8")
            except OSError:
                continue
            if pattern in text:
                matches.append(str(py_file.relative_to(directory.parent)))
        return matches

    def test_core_has_no_ragflow_literal(self):
        """plugins/memory/memory_os/ must never contain 'ragflow'."""
        repo = Path(__file__).resolve().parents[3]
        matches = self._find_in_dir(
            repo / "plugins" / "memory" / "memory_os", "ragflow",
        )
        if matches:
            pytest.fail(f"ragflow literal found in core files: {matches}")

    def test_core_has_no_cognee_literal(self):
        """plugins/memory/memory_os/ must never contain 'cognee'."""
        repo = Path(__file__).resolve().parents[3]
        matches = self._find_in_dir(
            repo / "plugins" / "memory" / "memory_os", "cognee",
        )
        if matches:
            pytest.fail(f"cognee literal found in core files: {matches}")

    def test_seam_dir_allows_ragflow_literal(self):
        """plugins/seam/external_evidence/ IS allowed to contain 'ragflow'."""
        repo = Path(__file__).resolve().parents[3]
        matches = self._find_in_dir(
            repo / "plugins" / "seam" / "external_evidence", "ragflow",
        )
        assert len(matches) > 0, "Expected ragflow in seam directory"

    def test_hard_assertion_seam_deletion_core_tests_still_green(self):
        """Conceptual gate: seam modules must not be imported by core."""
        repo = Path(__file__).resolve().parents[3]
        matches = self._find_in_dir(
            repo / "plugins" / "memory" / "memory_os", "plugins.seam",
        )
        if matches:
            pytest.fail(
                f"Core files import from seam (violates L2 boundary): {matches}"
            )
