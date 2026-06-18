"""Minimal memory provider discovery for the standalone Memory-OS project."""

from __future__ import annotations

from importlib import import_module
from typing import Any


def load_memory_provider(name: str) -> Any | None:
    """Load a Memory-OS provider by name.

    Creates a mock ctx, calls register(ctx), and returns the registered provider.
    This is a standalone bootstrap helper used by tests — Hermes agent itself
    calls register(ctx) directly on discovery.
    """
    if name not in {"memory_os", "memory-os"}:
        return None
    module = import_module("plugins.memory.memory_os")

    from unittest.mock import MagicMock

    ctx = MagicMock()
    module.register(ctx)
    ctx.register_memory_provider.assert_called_once()
    (provider,) = ctx.register_memory_provider.call_args[0]
    return provider


def discover_memory_providers() -> list[tuple[str, str, str]]:
    return [("memory_os", "plugins.memory.memory_os", "memory-os")]
