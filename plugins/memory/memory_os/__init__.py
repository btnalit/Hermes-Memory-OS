"""Memory-OS provider."""

from __future__ import annotations

import hashlib
import json
import queue
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from agent.memory_provider import MemoryProvider

from . import config as memory_os_config
from .audit import append_audit, read_audit_entries
from .crystallized import read_candidate_queue
from .ids import new_event_id
from .index import MemoryOSIndex
from .prefetch import build_prefetch
from .roots import MemoryOSRoots
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
from .store import MemoryOSStore


class MemoryOSProvider(MemoryProvider):
    """Profile-local Memory-OS provider."""

    def __init__(self) -> None:
        self.session_id = ""
        self.hermes_home = ""
        self.platform = ""
        self.profile = ""
        self._config = dict(memory_os_config.DEFAULT_CONFIG)
        self._roots: MemoryOSRoots | None = None
        self._store: MemoryOSStore | None = None
        self._index: MemoryOSIndex | None = None
        self._queue: queue.Queue[EventEnvelope] | None = None
        self._worker_thread: threading.Thread | None = None
        self._worker_stop = threading.Event()

    @property
    def name(self) -> str:
        return "memory-os"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self.session_id = session_id
        self.hermes_home = str(kwargs.get("hermes_home") or "")
        self.platform = str(kwargs.get("platform") or "")
        self.profile = str(kwargs.get("agent_identity") or kwargs.get("profile") or "memoryos-test")
        self._config = memory_os_config.load_config(self.hermes_home)
        self._roots = MemoryOSRoots.from_hermes_home(self.hermes_home, profile=self.profile)
        self._store = MemoryOSStore(self._roots)
        self._store.initialize()
        self._index = MemoryOSIndex(self._roots)
        self._queue = queue.Queue(maxsize=int(kwargs.get("queue_max_size") or 128))
        self._worker_stop = threading.Event()
        if kwargs.get("worker_autostart", True):
            self._start_worker()

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._store is None:
            return ""
        return build_prefetch(
            query,
            budget_chars=int(self._config.get("prefetch_char_budget", 2200)),
            store=self._store,
            index=self._index,
            diagnostic_grounding_enabled=memory_os_config.effective_diagnostic_grounding_enabled(
                self._config,
                self.profile,
            ),
            runtime_facts=self._tool_status_report(),
        )

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        event = self._build_event(
            kind="conversation_turn",
            summary=_turn_summary(user_content, assistant_content),
            session_id=session_id,
            safe_ref={"session_id": session_id or self.session_id},
            hashes={
                "user_sha256": _sha256(user_content),
                "assistant_sha256": _sha256(assistant_content),
            },
        )
        self._enqueue(event, drop_action="sync_turn_dropped")

    def system_prompt_block(self) -> str:
        if not self._store:
            return ""
        return "# Memory-OS\nActive. Conversation capture is summary-only by default."

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "memory_os_status",
                "description": (
                    "Inspect the active Memory-OS provider status. Use this when asked "
                    "which memory provider is active, whether Memory-OS is working, or "
                    "whether the current memory backend is Hindsight. Returns counts and "
                    "storage facts without raw private bodies. Treat this tool as "
                    "authoritative for current provider diagnostics, not historical recall."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        if tool_name != "memory_os_status":
            return super().handle_tool_call(tool_name, args, **kwargs)
        return json.dumps(self._tool_status_report(), ensure_ascii=False, sort_keys=True)

    def get_config_schema(self) -> list[dict[str, Any]]:
        return memory_os_config.get_config_schema()

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        memory_os_config.save_config(values, hermes_home)

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
        if action != "add" or target not in {"memory", "user"} or not content.strip():
            return
        event = self._build_event(
            kind="memory_write",
            summary=f"Built-in {target} memory add: {_clip(content, 240)}",
            session_id=str((metadata or {}).get("session_id") or self.session_id),
            safe_ref={
                "session_id": str((metadata or {}).get("session_id") or self.session_id),
                "target": target,
                "action": action,
            },
            hashes={"content_sha256": _sha256(content)},
        )
        self._enqueue(event, drop_action="memory_write_dropped")

    def shutdown(self) -> None:
        if self._queue is None:
            return
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_stop.set()
            self._queue.join()
            self._worker_thread.join(timeout=2.0)
            return
        self._drain_queue_synchronously()

    def _start_worker(self) -> None:
        if self._queue is None or self._worker_thread:
            return
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="memory-os-writer",
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        assert self._queue is not None
        while not self._worker_stop.is_set() or not self._queue.empty():
            try:
                event = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._write_event(event)
            except Exception as exc:
                self._audit("worker_error", "warning", {"event_id": event.id, "error": str(exc)})
            finally:
                self._queue.task_done()

    def _drain_queue_synchronously(self) -> None:
        assert self._queue is not None
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._write_event(event)
            except Exception as exc:
                self._audit("worker_error", "warning", {"event_id": event.id, "error": str(exc)})
            finally:
                self._queue.task_done()

    def _write_event(self, event: EventEnvelope) -> None:
        if self._store is None:
            return
        self._store.append_event(event)

    def _enqueue(self, event: EventEnvelope, *, drop_action: str) -> None:
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self._audit(drop_action, "warning", {"event_id": event.id})

    def _build_event(
        self,
        *,
        kind: str,
        summary: str,
        session_id: str,
        safe_ref: dict[str, Any],
        hashes: dict[str, Any],
    ) -> EventEnvelope:
        now = datetime.now(timezone.utc)
        return EventEnvelope.from_dict(
            {
                "schema_version": EVENT_SCHEMA_VERSION,
                "id": new_event_id(now),
                "ts": now.isoformat(),
                "profile": self.profile or "memoryos-test",
                "source": self.platform or "memory-os",
                "kind": kind,
                "summary": summary,
                "safe_ref": safe_ref,
                "tags": ["memory-os", kind],
                "sensitivity": "private",
                "body_policy": "summary_only",
                "hashes": hashes,
                "promotion_state": "raw",
            }
        )

    def _audit(self, action: str, status: str, details: dict[str, Any]) -> None:
        if self._roots is None:
            return
        append_audit(
            self._roots.audit_path,
            action=action,
            status=status,
            target="memory-os-provider",
            details=details,
        )

    def _tool_status_report(self) -> dict[str, Any]:
        if self._roots is None or self._store is None:
            return {
                "schema_version": "memory-os.tool_status.v0",
                "provider": "memory_os",
                "status": "not_initialized",
            }
        events = self._store.read_events()
        event_sources = Counter(event.source for event in events)
        event_kinds = Counter(event.kind for event in events)
        latest_event_ts = max((event.ts for event in events), default=None)
        index_counts = self._index.counts() if self._index else {}
        adapter_enabled = bool(self._config.get("hindsight_adapter_enabled"))
        uses_hindsight_http_api = False
        working_count = _working_item_count(self._roots)
        candidate_count = len(read_candidate_queue(self._roots))
        return {
            "schema_version": "memory-os.tool_status.v0",
            "provider": "memory_os",
            "provider_name": self.name,
            "status": "active",
            "profile": self.profile,
            "platform": self.platform,
            "canonical_store": str(self._roots.memory_os_root),
            "storage_model": "local_filesystem_jsonl_markdown",
            "event_count": len(events),
            "event_sources": dict(event_sources),
            "event_kinds": dict(event_kinds),
            "latest_event_ts": latest_event_ts,
            "working_item_count": working_count,
            "working_items": working_count,
            "crystallized_candidate_count": candidate_count,
            "crystallized_candidates": candidate_count,
            "crystallized_candidates_label": "review candidates only; not approved crystallized memory",
            "crystallized_records": int(index_counts.get("crystallized_records", 0)),
            "crystallized_records_label": "approved crystallized memory records",
            "audit_entries": len(read_audit_entries(self._roots.audit_path)),
            "index_counts": index_counts,
            "index_health": _tool_index_health(self._roots, len(events), index_counts),
            "prefetch_mode": "indexed" if self._roots.index_path.exists() else "degraded_filesystem",
            "hindsight_adapter_enabled": adapter_enabled,
            "hindsight_role": "optional_adapter_only_not_canonical",
            "uses_hindsight_http_api": uses_hindsight_http_api,
            "body_policy": "summary_only",
            "authoritative_for": [
                "active memory provider",
                "canonical Memory-OS store",
                "whether Hindsight is canonical",
                "runtime counts and index health",
            ],
            "forbidden_claims": _forbidden_claims(
                adapter_enabled=adapter_enabled,
                uses_hindsight_http_api=uses_hindsight_http_api,
            ),
            "stale_memory_warning": "Do not answer provider diagnostics from historical recalled events.",
        }


def register_memory_provider() -> MemoryProvider:
    return MemoryOSProvider()


def _turn_summary(user_content: str, assistant_content: str) -> str:
    return f"User: {_clip(user_content, 180)} | Assistant: {_clip(assistant_content, 180)}"


def _clip(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def _sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _working_item_count(roots: Any) -> int:
    count = 0
    for path in sorted(roots.working_root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        count += len(document.get("items", []))
    return count


def _tool_index_health(roots: Any, event_count: int, index_counts: dict[str, int]) -> str:
    if not roots.index_path.exists():
        return "missing"
    indexed_events = int(index_counts.get("events", 0))
    if indexed_events < event_count:
        return "stale"
    if indexed_events > event_count:
        return "mismatch"
    return "healthy"


def _forbidden_claims(*, adapter_enabled: bool, uses_hindsight_http_api: bool) -> list[str]:
    claims = ["Memory-OS canonical store is /root/.hermes/hindsight/config.json"]
    if not uses_hindsight_http_api:
        claims.append("Memory-OS uses Hindsight HTTP API as its canonical store")
    if not adapter_enabled:
        claims.append("Hindsight is the active canonical provider when provider=memory_os")
    return claims
