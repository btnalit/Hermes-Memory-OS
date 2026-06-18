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
