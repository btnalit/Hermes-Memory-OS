"""Minimal MemoryProvider interface used by the standalone Memory-OS provider.

Kept synchronized with agent.memory_provider.MemoryProvider (host ABC).
When Hermes agent is installed, the conditional import in __init__.py
resolves to the host ABC; this file is the ImportError fallback.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MemoryProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider (e.g. 'builtin', 'honcho', 'memory-os')."""

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def initialize(self, session_id: str, **kwargs: Any) -> None:
        raise NotImplementedError

    def system_prompt_block(self) -> str:
        return ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        return None

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "", messages=None) -> None:
        return None

    @abstractmethod
    def get_tool_schemas(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        return "{}"

    def get_config_schema(self) -> list[dict[str, Any]]:
        return []

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        return None

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        return None

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        return None

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        return ""

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        return None

    def on_session_switch(self, new_session_id: str, *, parent_session_id: str = "", reset: bool = False, rewound: bool = False, **kwargs: Any) -> None:
        return None

    def on_delegation(self, task: str, result: str, *, child_session_id: str = "", **kwargs: Any) -> None:
        return None

    def shutdown(self) -> None:
        return None
