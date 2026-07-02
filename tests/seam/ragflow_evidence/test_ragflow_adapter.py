"""Tests for RAGFlow seam adapter (P2.2)."""

from __future__ import annotations

import pytest


class TestRagflowEvidenceClient:
    """Tests for RagflowEvidenceClient construction and stub behavior."""

    def test_client_requires_base_url(self):
        """Q.5: ValueError if base_url not configured."""
        from plugins.seam.ragflow_evidence.adapter import RagflowEvidenceClient

        with pytest.raises(ValueError, match="base_url"):
            RagflowEvidenceClient(base_url="")
        with pytest.raises(ValueError, match="base_url"):
            RagflowEvidenceClient(base_url="   ")

    def test_client_accepts_valid_config(self):
        from plugins.seam.ragflow_evidence.adapter import RagflowEvidenceClient

        client = RagflowEvidenceClient(
            base_url="http://localhost:9380",
            api_key="test-key",
            dataset_id="test-ds",
            profile="test",
        )
        assert client.base_url == "http://localhost:9380"
        assert client.api_key == "test-key"
        assert client.dataset_id == "test-ds"

    def test_retrieve_raises_not_implemented(self):
        """HTTP client not yet wired."""
        from plugins.seam.ragflow_evidence.adapter import RagflowEvidenceClient

        client = RagflowEvidenceClient(base_url="http://localhost:9380")
        with pytest.raises(NotImplementedError):
            client.retrieve("test query")


class TestIngestEvidence:
    """Tests for ingest_evidence entry point."""

    def test_disabled_returns_empty(self, tmp_path):
        """Q.7: config disabled -> returns [].

        The hermes_home parameter is unused when config is explicitly provided,
        so we pass an arbitrary path that may or may not have the config file.
        P2.2 iron law: enabled=false -> no-op.
        """
        from plugins.seam.ragflow_evidence.adapter import ingest_evidence
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path)
        store = MemoryOSStore(roots)
        store.initialize()

        config = {"ragflow_evidence": {"enabled": False}}
        result = ingest_evidence(store, "test query", config=config)
        assert result == []

    def test_ingest_calls_external_intake(self, tmp_path):
        """Q.6: mock retrieve -> external_intake called with provider='ragflow'."""
        from plugins.seam.ragflow_evidence.adapter import (
            EvidenceChunk,
            RagflowEvidenceClient,
            ingest_evidence,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from unittest.mock import patch

        roots = MemoryOSRoots.from_hermes_home(tmp_path)
        store = MemoryOSStore(roots)
        store.initialize()

        mock_chunks = [
            EvidenceChunk(
                content="Test chunk content",
                external_ref="external:test:doc1:chunk1",
                score=0.95,
            ),
        ]

        config = {
            "ragflow_evidence": {
                "enabled": True,
                "base_url": "http://localhost:9380",
                "api_key": "test-key",
                "dataset_id": "test-ds",
            }
        }

        with patch.object(RagflowEvidenceClient, "retrieve", return_value=mock_chunks):
            result = ingest_evidence(store, "test query", config=config)
            assert len(result) == 1
            assert result[0].startswith("evt_")

        # Verify event metadata
        events = store.read_events()
        matching = [e for e in events if e.id == result[0]]
        assert len(matching) == 1
        assert matching[0].safe_ref.get("provider") == "ragflow"
        assert matching[0].safe_ref.get("source_class") == "external_evidence"
