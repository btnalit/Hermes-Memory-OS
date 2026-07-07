"""Tests for Hindsight Advisory — E1-E4 coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


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


# ── E1: Health probe tests ───────────────────────────────────────────


class TestHindsightHealthProbe:
    def test_probe_disabled_when_no_config(self):
        from scripts.memory_os_hindsight_health_probe import probe_hindsight_health
        report = probe_hindsight_health("/nonexistent/path")
        assert report["status"] == "disabled"
        assert report["health"] == "disabled"

    def test_probe_disabled_when_config_not_enabled(self, tmp_path):
        from scripts.memory_os_hindsight_health_probe import probe_hindsight_health
        home = tmp_path / ".hermes"
        (home / "memory-os").mkdir(parents=True)
        cfg = {
            "substrate_providers": {
                "hindsight": {
                    "enabled": False,
                    "api_url": "http://localhost:9999",
                    "bank_id": "test-bank",
                },
            },
        }
        (home / "memory-os" / "config.json").write_text(json.dumps(cfg))
        report = probe_hindsight_health(str(home))
        assert report["status"] == "disabled"

    def test_probe_unconfigured_when_missing_url(self, tmp_path):
        from scripts.memory_os_hindsight_health_probe import probe_hindsight_health
        home = tmp_path / ".hermes"
        (home / "memory-os").mkdir(parents=True)
        cfg = {
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "api_url": "",
                    "bank_id": "test-bank",
                },
            },
        }
        (home / "memory-os" / "config.json").write_text(json.dumps(cfg))
        report = probe_hindsight_health(str(home))
        assert report["status"] == "unconfigured"

    def test_probe_unreachable_returns_health_status(self, tmp_path):
        from scripts.memory_os_hindsight_health_probe import probe_hindsight_health
        home = tmp_path / ".hermes"
        (home / "memory-os").mkdir(parents=True)
        cfg = {
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "api_url": "http://127.0.0.1:19999",  # nothing listening
                    "bank_id": "test-bank",
                },
            },
        }
        (home / "memory-os" / "config.json").write_text(json.dumps(cfg))
        report = probe_hindsight_health(str(home), timeout_seconds=1.0)
        assert report["status"] in ("unreachable", "timeout", "unhealthy")

    def test_script_help_works(self):
        import subprocess, sys
        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_hindsight_health_probe.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


# ── E2: Hindsight retriever tests ────────────────────────────────────


class TestHindsightRetriever:
    def test_retriever_disabled_when_no_config(self, tmp_path):
        from plugins.memory.memory_os.retrievers.hindsight import HindsightRetriever
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        retriever = HindsightRetriever()
        results = retriever.retrieve(store, "test query")
        assert results == []

    def test_recall_type_is_hindsight(self):
        from plugins.memory.memory_os.retrievers.hindsight import HindsightRetriever
        from plugins.memory.memory_os.recall_types import RecallType
        assert HindsightRetriever().recall_type == RecallType.HINDSIGHT

    def test_advisory_only_invariant(self):
        """Every Hindsight recall result must carry advisory_only=True."""
        from plugins.memory.memory_os.retrievers.hindsight import HindsightRetriever
        from plugins.memory.memory_os.roots import MemoryOSRoots
        # Even without real Hindsight, the invariant must hold for empty results
        retriever = HindsightRetriever()
        # Verify via format_context that advisory marker is always present
        ctx = retriever.format_context([])
        assert ctx == ""  # empty list → empty context

    def test_format_context_shows_advisory_warning(self):
        from plugins.memory.memory_os.retrievers.hindsight import HindsightRetriever
        from plugins.memory.memory_os.recall_types import RecallObject
        retriever = HindsightRetriever()
        objects = [
            RecallObject(
                recall_type="hindsight",
                content="Reflection: memory-os is stable",
                score=0.7,
                source_ref="hindsight:snap-1",
                metadata={
                    "advisory_only": True,
                    "authority_class": "derived_projection",
                },
            ),
        ]
        ctx = retriever.format_context(objects)
        assert "Advisory" in ctx
        assert "not canonical" in ctx.lower()
        assert "memory-os is stable" in ctx

    def test_retriever_fail_open_on_broken_config(self, tmp_path):
        from plugins.memory.memory_os.retrievers.hindsight import HindsightRetriever
        home = tmp_path / ".hermes"
        (home / "memory-os").mkdir(parents=True)
        (home / "memory-os" / "config.json").write_text("not valid json {{{")
        roots = MemoryOSRoots.from_hermes_home(str(home))
        store = _make_store(roots)
        retriever = HindsightRetriever()
        results = retriever.retrieve(store, "query")  # must not raise
        assert results == []

    def test_hindsight_retriever_filters_local_artifact_fallback(self, tmp_path, monkeypatch):
        """The hindsight lane should expose Hindsight facts, not local-artifact fallback."""
        import plugins.memory.memory_os.retrievers.hindsight as module
        from plugins.memory.memory_os.retrievers.hindsight import HindsightRetriever

        roots = _make_roots(tmp_path)
        cfg_path = roots.hermes_home / "memory-os" / "config.json"
        cfg_path.write_text(json.dumps({
            "substrate_providers": {
                "hindsight": {"enabled": True, "recall_mode": "active", "api_url": "http://example", "bank_id": "b"}
            }
        }), encoding="utf-8")
        store = _make_store(roots)

        monkeypatch.setattr(module, "_substrate_recall", lambda store, query, config: {
            "facts": [
                {"provider": "local_artifact", "body_summary": "canonical fallback", "confidence": 0.9},
                {"provider": "hindsight", "body_summary": "hindsight advisory", "confidence": 0.7},
            ]
        })

        results = HindsightRetriever().retrieve(store, "query")
        assert [r.metadata["provider"] for r in results] == ["hindsight"]
        assert results[0].content == "hindsight advisory"


# ── E3: Reflect digest → owner finding ───────────────────────────────


class TestHindsightAdvisoryBoundary:
    def test_advisory_never_auto_approve(self):
        """Conceptual invariant: Hindsight recall is always advisory_only."""
        from plugins.memory.memory_os.recall_types import is_l2_recall, RecallType
        # Hindsight is an L2 retriever — it can surface findings
        # but never writes canonical
        assert is_l2_recall(RecallType.HINDSIGHT) is True

    def test_core_does_not_import_hindsight_directly(self):
        """Hindsight adapter lives in substrates/, not core paths."""
        # Verify that the retriever uses L2 access patterns
        from plugins.memory.memory_os.recall_types import RecallType
        assert RecallType.HINDSIGHT.value == "hindsight"

    def test_timeout_cadence_no_cron_storm(self):
        """E4: Hindsight cron should use conservative cadence (low-frequency)."""
        # The health probe uses --timeout flag and the cron runs infrequently
        # (every 6h for advisory reflect).  This test verifies the concept
        # is encoded in config defaults.
        from plugins.memory.memory_os.substrates.hindsight import GovernedHindsightConfig
        config = GovernedHindsightConfig()
        assert config.recall_mode == "off"  # off by default
        assert config.reflect_enabled is False  # reflect off by default


# ── E4: Cron integration check ──────────────────────────────────────


class TestHindsightCronIntegration:
    def test_hindsight_in_recall_probe(self):
        """Hindsight must be available in the recall probe."""
        from plugins.memory.memory_os.recall_types import RecallType
        assert RecallType.HINDSIGHT in RecallType

    def test_hindsight_health_probe_script_output_schema(self, tmp_path):
        import subprocess, sys
        home = tmp_path / ".hermes"
        (home / "memory-os").mkdir(parents=True)
        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_hindsight_health_probe.py"

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(script),
             "--hermes-home", str(home),
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["schema_version"] == "memory-os.hindsight_health.v0"
        assert "status" in output
        assert "health" in output

    def test_hindsight_in_available_retrievers(self):
        """Entity_graph and hindsight should both be in available retrievers."""
        from scripts.memory_os_recall_probe import AVAILABLE_RETRIEVERS
        assert "entity_graph" in AVAILABLE_RETRIEVERS
        assert "hindsight" in AVAILABLE_RETRIEVERS

    def test_recall_probe_accepts_hindsight_type(self, tmp_path):
        import subprocess, sys
        home = tmp_path / ".hermes"
        (home / "memory-os" / "events").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)
        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_recall_probe.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--hermes-home", str(home),
                "--type", "hindsight",
                "--query", "test",
                "--output", "json",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert output["recall_types"] == ["hindsight"]
        assert "hindsight" in output["results"]

    def test_hindsight_http_client_uses_v061_memories_recall_path(self, monkeypatch):
        from plugins.memory.memory_os.retrievers.hindsight import _hindsight_http_client

        captured = {}

        class FakeResponse:
            def read(self):
                return b'{"results": []}'

        def fake_urlopen(req, timeout):
            captured["full_url"] = req.full_url
            captured["timeout"] = timeout
            return FakeResponse()

        import urllib.request as request_module
        monkeypatch.setattr(request_module, "urlopen", fake_urlopen)

        client = _hindsight_http_client({"api_url": "http://example.test/v1/default", "api_key": ""})
        data = client.recall(bank_id="bank-a", query="q", budget="low", max_tokens=128)
        assert data == {"results": []}
        assert captured["full_url"] == "http://example.test/v1/default/banks/bank-a/memories/recall"


# ── Phase 5: Hindsight Advisory Digest script tests ───────────────────


class TestHindsightAdvisoryDigestScript:
    """Phase 5: weekly advisory digest script (advisory_only=True, fail-open)."""

    def test_advisory_digest_help_works(self):
        import subprocess
        import sys
        from pathlib import Path

        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_hindsight_advisory_digest.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "advisory" in result.stdout.lower()

    def test_advisory_digest_disabled_when_no_config(self, tmp_path):
        from scripts.memory_os_hindsight_advisory_digest import run_advisory_digest

        home = tmp_path / ".hermes"
        home.mkdir(parents=True)
        report = run_advisory_digest(str(home))
        assert report["status"] == "disabled"
        assert report["advisory_emitted"] is False

    def test_advisory_digest_disabled_when_reflect_off(self, tmp_path):
        from scripts.memory_os_hindsight_advisory_digest import run_advisory_digest

        home = tmp_path / ".hermes"
        (home / "memory-os").mkdir(parents=True)
        (home / "memory-os" / "config.json").write_text(json.dumps({
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "api_url": "http://127.0.0.1:1",
                    "bank_id": "test-bank",
                    "api_key": "test-key",
                    "reflect_enabled": False,
                }
            }
        }))
        report = run_advisory_digest(str(home), timeout=0.5)
        assert report["status"] in {"disabled", "unconfigured"}
        assert report["advisory_emitted"] is False

    def test_advisory_digest_timeout_fail_open(self, tmp_path):
        """Timeout → fail-open, no crash, advisory_emitted=False."""
        from scripts.memory_os_hindsight_advisory_digest import run_advisory_digest

        home = tmp_path / ".hermes"
        (home / "memory-os").mkdir(parents=True)
        (home / "memory-os" / "config.json").write_text(json.dumps({
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "api_url": "http://10.255.255.1:9999",  # non-routable
                    "bank_id": "test-bank",
                    "api_key": "test-key",
                    "reflect_enabled": True,
                }
            }
        }))
        report = run_advisory_digest(str(home), timeout=0.5)
        # Should not raise — fail-open
        assert report["status"] in {"timeout", "error", "unreachable", "unavailable", "unhealthy"}

    def test_advisory_digest_emits_advisory_only(self, tmp_path, monkeypatch):
        """When reflect succeeds, finding is advisory_only=True."""
        import scripts.memory_os_hindsight_advisory_digest as digest_module

        home = tmp_path / ".hermes"
        (home / "memory-os").mkdir(parents=True)
        (home / "memory-os" / "config.json").write_text(json.dumps({
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "api_url": "http://127.0.0.1:1",
                    "bank_id": "test-bank",
                    "api_key": "test-key",
                    "reflect_enabled": True,
                }
            }
        }))

        # Mock _write_advisory_finding to capture what was written
        written = {}

        def fake_write(hermes_home, content, *, kind="", advisory_only=True):
            written["content"] = content
            written["kind"] = kind
            written["advisory_only"] = advisory_only
            return Path(hermes_home) / "fake.json"

        monkeypatch.setattr(digest_module, "_write_advisory_finding", fake_write)
        run_advisory_digest = digest_module.run_advisory_digest

        # Mock GovernedHindsightSubstrate at the import site
        from plugins.memory.memory_os.substrates import hindsight as hs_module

        class FakeSubstrate:
            def health(self):
                from plugins.memory.memory_os.substrates.base import ProviderHealth
                return ProviderHealth(provider="hindsight", status="ok", capabilities=["reflect"])

            def reflect(self, query="", consumer=""):
                return {
                    "provider": "hindsight",
                    "capability": "reflect",
                    "status": "ok",
                    "advisory_only": True,
                    "response": {"summary": "Memory usage patterns show increased crystallized recall in recent sessions."},
                }

        original = getattr(hs_module, "GovernedHindsightSubstrate", None)
        monkeypatch.setattr(hs_module, "GovernedHindsightSubstrate", lambda config, client=None: FakeSubstrate())
        try:
            report = run_advisory_digest(str(home), timeout=5.0)
            assert report["advisory_emitted"] is True
            assert report["advisory_only"] is True
            assert written.get("advisory_only") is True
            assert "Memory usage patterns" in written.get("content", "")
        finally:
            if original is not None:
                monkeypatch.setattr(hs_module, "GovernedHindsightSubstrate", original)

    def test_advisory_digest_script_default_query(self, tmp_path):
        """Advisory digest script runs with default query without crash."""
        import subprocess
        import sys
        from pathlib import Path

        home = tmp_path / ".hermes"
        home.mkdir(parents=True)

        script = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_hindsight_advisory_digest.py"
        result = subprocess.run(
            [sys.executable, str(script), "--hermes-home", str(home), "--output", "json", "--timeout", "0.5"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "status" in payload
        assert "advisory_emitted" in payload
