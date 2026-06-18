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
