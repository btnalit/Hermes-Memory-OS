"""Minimal memory provider discovery for the standalone Memory-OS project."""

from __future__ import annotations

from importlib import import_module
from typing import Any


def load_memory_provider(name: str) -> Any | None:
    if name not in {"memory_os", "memory-os"}:
        return None
    module = import_module("plugins.memory.memory_os")
    return module.register_memory_provider()


def discover_memory_providers() -> list[tuple[str, str, str]]:
    return [("memory_os", "plugins.memory.memory_os", "memory-os")]
