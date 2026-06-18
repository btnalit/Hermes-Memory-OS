"""Contract tests: Memory-OS provider conforms to Hermes agent memory provider spec.

Reference: Hermes agent built-in providers (honcho, supermemory).
"""

from __future__ import annotations

import importlib
import inspect
import sys
from unittest.mock import MagicMock

import pytest


class TestRegisterEntryPoint:
    """F1: __init__ must expose register(ctx) matching honcho's pattern."""

    def test_register_function_exists(self):
        """register(ctx) callable exists at module level."""
        mod = importlib.import_module("plugins.memory.memory_os.__init__")

        assert hasattr(mod, "register"), (
            "Missing register(ctx) — Hermes scans for this function to discover the plugin. "
            "Reference: built-in honcho provider's def register(ctx) -> None."
        )
        assert callable(mod.register), "register must be callable"

    def test_register_signature_accepts_ctx(self):
        """register(ctx) takes exactly one positional parameter."""
        from plugins.memory.memory_os.__init__ import register

        sig = inspect.signature(register)
        params = list(sig.parameters.keys())
        assert len(params) == 1, (
            f"register() should take exactly 1 param (ctx), got {len(params)}: {params}"
        )

    def test_register_calls_ctx_register_memory_provider(self):
        """register(ctx) calls ctx.register_memory_provider with a MemoryOSProvider instance."""
        from plugins.memory.memory_os.__init__ import MemoryOSProvider, register

        ctx = MagicMock()
        register(ctx)
        ctx.register_memory_provider.assert_called_once()
        (provider_instance,) = ctx.register_memory_provider.call_args[0]
        assert isinstance(provider_instance, MemoryOSProvider), (
            f"Expected MemoryOSProvider instance, got {type(provider_instance)}"
        )

    def test_register_returns_none(self):
        """register(ctx) returns None (honcho pattern)."""
        from plugins.memory.memory_os.__init__ import register

        ctx = MagicMock()
        result = register(ctx)
        assert result is None, f"register() must return None, got {type(result)}"


class TestDoctor:
    """F7: doctor command reports specific root causes, not generic 'NOT installed'."""

    def test_doctor_checks_register(self):
        """Doctor detects missing register(ctx)."""
        from plugins.memory.memory_os.cli import _hermes_contract_checks

        results = _hermes_contract_checks()
        register_findings = [r for r in results if "register" in r.get("code", "")]
        # After F1 fix, should have no error about missing register
        errors = [r for r in register_findings if r.get("severity") == "error"]
        assert not errors, f"register(ctx) check should pass after F1 fix: {errors}"

    def test_doctor_checks_sync_turn(self):
        """Doctor detects sync_turn missing messages param."""
        from plugins.memory.memory_os.cli import _hermes_contract_checks

        results = _hermes_contract_checks()
        st_findings = [r for r in results if "sync_turn" in r.get("code", "")]
        errors = [r for r in st_findings if r.get("severity") == "error"]
        assert not errors, f"sync_turn check should pass after F3 fix: {errors}"

    def test_doctor_checks_all_report_specific_detail(self):
        """Every check has a non-empty detail string — never silent pass/fail."""
        from plugins.memory.memory_os.cli import _hermes_contract_checks

        for r in _hermes_contract_checks():
            assert isinstance(r.get("message"), str) and len(r["message"]) > 10, (
                f"Check '{r.get('code')}' has vague detail: {r.get('message')!r}"
            )


class TestIndexRebuildCLI:
    """F8: index rebuild CLI exposes existing rebuild_from_store logic."""

    def test_register_cli_includes_index_rebuild(self):
        """register_cli() registers 'index rebuild' subcommand."""
        import argparse
        from plugins.memory.memory_os.cli import register_cli

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="cmd")
        memory_os_sp = subparsers.add_parser("memory_os")
        register_cli(memory_os_sp)

        args = parser.parse_args(["memory_os", "index", "rebuild"])
        assert args.memory_os_command == "index"
        assert args.index_command == "rebuild"


class TestABCImport:
    """F2: Provider must inherit from agent.memory_provider.MemoryProvider when available."""

    def test_provider_inherits_from_host_abc_when_available(self):
        """In production (hermes agent installed), isinstance check passes."""
        try:
            from agent.memory_provider import MemoryProvider as HostABC
        except ImportError:
            pytest.skip("Hermes agent not installed — vendored ABC fallback is correct")
            return

        from plugins.memory.memory_os.__init__ import MemoryOSProvider

        assert issubclass(MemoryOSProvider, HostABC), (
            "MemoryOSProvider must be a subclass of agent.memory_provider.MemoryProvider "
            "when Hermes agent is installed. Currently inheriting from vendored copy — "
            "isinstance(provider, agent.memory_provider.MemoryProvider) would return False, "
            "causing 'NOT installed'."
        )

    def test_vendored_abc_has_same_abstractmethods_as_host(self):
        """Vendored ABC's abstractmethod set matches host ABC's — prevents drift."""
        try:
            from agent.memory_provider import MemoryProvider as HostABC
        except ImportError:
            pytest.skip("Hermes agent not installed — cannot compare")
            return

        from memory_os_agent.memory_provider import MemoryProvider as VendoredABC

        host_abstracts = set(HostABC.__abstractmethods__)
        vendored_abstracts = set(VendoredABC.__abstractmethods__)

        missing_from_vendored = host_abstracts - vendored_abstracts
        extra_in_vendored = vendored_abstracts - host_abstracts

        assert not missing_from_vendored, (
            f"Vendored ABC missing abstract methods present in host ABC: {missing_from_vendored}"
        )
        assert not extra_in_vendored, (
            f"Vendored ABC has extra abstract methods not in host ABC: {extra_in_vendored}"
        )


class TestSyncTurnSignature:
    """F3: sync_turn must accept messages=None keyword-only parameter."""

    def test_sync_turn_accepts_messages_kwarg(self):
        """MemoryManager.sync_all() passes messages=[...] — our sync_turn must accept it."""
        from plugins.memory.memory_os.__init__ import MemoryOSProvider

        provider = MemoryOSProvider()
        try:
            provider.sync_turn("user msg", "assistant msg", session_id="test", messages=[{"role": "user", "content": "hi"}])
        except TypeError as e:
            pytest.fail(f"sync_turn raised TypeError when passed messages=...: {e}")

    def test_sync_turn_messages_defaults_to_none(self):
        """sync_turn works without messages kwarg (backward compat)."""
        from plugins.memory.memory_os.__init__ import MemoryOSProvider

        provider = MemoryOSProvider()
        try:
            provider.sync_turn("user msg", "assistant msg", session_id="test")
        except TypeError as e:
            pytest.fail(f"sync_turn raised TypeError without messages: {e}")

    def test_sync_turn_signature_matches_host_abc(self):
        """sync_turn parameter names match host ABC exactly."""
        try:
            from agent.memory_provider import MemoryProvider as HostABC
        except ImportError:
            pytest.skip("Hermes agent not installed")
            return

        import inspect
        from plugins.memory.memory_os.__init__ import MemoryOSProvider

        host_sig = inspect.signature(HostABC.sync_turn)
        our_sig = inspect.signature(MemoryOSProvider.sync_turn)

        host_params = set(host_sig.parameters.keys())
        our_params = set(our_sig.parameters.keys())

        missing = host_params - our_params
        assert not missing, (
            f"sync_turn missing parameters present in host ABC: {missing}. "
            f"Host wants: {sorted(host_params)}"
        )
