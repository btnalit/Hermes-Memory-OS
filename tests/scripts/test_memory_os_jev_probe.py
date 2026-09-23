"""Tests for scripts/memory_os_jev_probe.py -- the minimal post-deploy
operator probe for the optional Jev judge backend (J1 native noul, J2
native choice).

No network calls. The HTTP layer is mocked at urllib.request.urlopen.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "memory_os_jev_probe.py"

_spec = importlib.util.spec_from_file_location("memory_os_jev_probe", _SCRIPT_PATH)
memory_os_jev_probe = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("memory_os_jev_probe", memory_os_jev_probe)
_spec.loader.exec_module(memory_os_jev_probe)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self) -> bytes:
        return self._body


def test_missing_key_produces_typed_failures_without_network(monkeypatch):
    monkeypatch.delenv("PROBE_TEST_UNSET_VAR", raising=False)
    with patch("urllib.request.urlopen") as mock_urlopen:
        report = memory_os_jev_probe.run_probe(api_key_env_var="PROBE_TEST_UNSET_VAR")

    assert not mock_urlopen.called, "missing key must never reach the network"
    assert report["api_key_present"] is False
    for result in report["results"].values():
        assert result["failure_reason"] == "llm_missing_key"
        assert result["durable_fact"] is False


def test_all_three_built_in_candidates_are_probed(monkeypatch):
    monkeypatch.setenv("PROBE_TEST_FAKE_KEY", "fake-not-real")

    def _fake_urlopen(request, timeout=None):
        return _FakeResponse(
            json.dumps({
                "model": "jev-1.13.0",
                "answers": {"durable_fact": {"type": "noul", "noul": 0.9}},
            }).encode()
        )

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        report = memory_os_jev_probe.run_probe(api_key_env_var="PROBE_TEST_FAKE_KEY")

    assert report["api_key_present"] is True
    assert set(report["results"].keys()) == set(memory_os_jev_probe.BUILT_IN_CANDIDATES.keys())
    for result in report["results"].values():
        assert result["failure_reason"] is None
        assert result["jev_model"] == "jev-1.13.0"


def test_report_never_contains_the_key_value(monkeypatch):
    monkeypatch.setenv("PROBE_TEST_FAKE_KEY", "super-secret-value-must-not-leak")

    def _fake_urlopen(request, timeout=None):
        return _FakeResponse(
            json.dumps({
                "model": "jev-1.13.0",
                "answers": {"durable_fact": {"type": "noul", "noul": 0.1}},
            }).encode()
        )

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        report = memory_os_jev_probe.run_probe(api_key_env_var="PROBE_TEST_FAKE_KEY")

    serialized = json.dumps(report)
    assert "super-secret-value-must-not-leak" not in serialized


# ═══════════════════════════════════════════════════════════════════════════
# J2 -- --mode choice (llm_edge_proposer's native-choice relation question)
# ═══════════════════════════════════════════════════════════════════════════


def test_choice_mode_missing_key_produces_typed_failures_without_network(monkeypatch):
    monkeypatch.delenv("PROBE_TEST_UNSET_VAR", raising=False)
    with patch("urllib.request.urlopen") as mock_urlopen:
        report = memory_os_jev_probe.run_choice_probe(api_key_env_var="PROBE_TEST_UNSET_VAR")

    assert not mock_urlopen.called, "missing key must never reach the network"
    assert report["mode"] == "choice"
    assert report["api_key_present"] is False
    for result in report["results"].values():
        assert result["outcome"] == "jev_failed"
        assert result["jev_failure_reason"] == "llm_missing_key"
        # "none" is only ever a legitimate Jev *answer* -- a failed call
        # must still be identifiable via `outcome`, not by relation_type
        # alone (see CLAUDE.md's "Completion Is Not Output").
        assert result["relation_type"] == "none"


def test_choice_mode_all_three_built_in_pairs_are_probed(monkeypatch):
    monkeypatch.setenv("PROBE_TEST_FAKE_KEY", "fake-not-real")

    def _fake_urlopen(request, timeout=None):
        return _FakeResponse(
            json.dumps({
                "model": "jev-1.13.0",
                "answers": {
                    "relation_type": {
                        "type": "choice", "choice": "refines", "confidence": 0.87,
                        "probabilities": {"refines": 0.87},
                    }
                },
            }).encode()
        )

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        report = memory_os_jev_probe.run_choice_probe(api_key_env_var="PROBE_TEST_FAKE_KEY")

    assert report["api_key_present"] is True
    assert set(report["results"].keys()) == set(memory_os_jev_probe.CHOICE_BUILT_IN_PAIRS.keys())
    for result in report["results"].values():
        assert result["outcome"] == "ok"
        assert result["relation_type"] == "refines"
        assert result["jev_model"] == "jev-1.13.0"


def test_choice_mode_report_never_contains_the_key_value(monkeypatch):
    monkeypatch.setenv("PROBE_TEST_FAKE_KEY", "super-secret-value-must-not-leak")

    def _fake_urlopen(request, timeout=None):
        return _FakeResponse(
            json.dumps({
                "model": "jev-1.13.0",
                "answers": {"relation_type": {"type": "choice", "choice": "none", "confidence": 0.5}},
            }).encode()
        )

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        report = memory_os_jev_probe.run_choice_probe(api_key_env_var="PROBE_TEST_FAKE_KEY")

    serialized = json.dumps(report)
    assert "super-secret-value-must-not-leak" not in serialized
