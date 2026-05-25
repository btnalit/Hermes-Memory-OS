"""Memory-OS provider."""

from __future__ import annotations

import hashlib
import json
import queue
import re
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
from .ingress import classify_ingress
from .low_clue_recall import low_clue_judge_availability
from .owner_actions import parse_owner_review_reply
from .prefetch import build_prefetch
from .roots import MemoryOSRoots
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
from .status_tool_contract import MEMORY_OS_STATUS_TOOL_DESCRIPTION
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
        self._current_task_anchor = ""
        self._foreground_task_only_prefetch = False
        self._last_owner_review_reply_result: dict[str, Any] | None = None
        self._last_owner_review_reply_query = ""

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
        if self._last_owner_review_reply_result and query == self._last_owner_review_reply_query:
            return _owner_review_reply_context_block(self._last_owner_review_reply_result)
        self._refresh_current_task_anchor_from_query(query, session_id=session_id)
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
            current_task_anchor=self._current_task_anchor,
            foreground_task_only=self._foreground_task_only_prefetch,
            context_router_config=self._config.get("context_router"),
            memory_sources_config=self._config.get("memory_sources"),
            low_clue_recall_config=self._config.get("low_clue_recall"),
        )

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        if not (
            self._last_owner_review_reply_query == user_content
            and self._last_owner_review_reply_result
            and self._last_owner_review_reply_result.get("status") == "ok"
        ):
            self._process_owner_review_reply_ingress(user_content, turn_number=None, phase="sync_turn")
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
        lines = ["# Memory-OS", "Active. Conversation capture is summary-only by default."]
        if self._last_owner_review_reply_result:
            lines.extend(["", _owner_review_reply_system_instruction(self._last_owner_review_reply_result)])
        if self._current_task_anchor:
            lines.extend(["", self._current_task_anchor])
        return "\n".join(lines)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "memory_os_status",
                "description": MEMORY_OS_STATUS_TOOL_DESCRIPTION,
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

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        self._last_owner_review_reply_result = None
        self._last_owner_review_reply_query = ""
        self._process_owner_review_reply_ingress(message, turn_number=turn_number, phase="turn_start")

    def _process_owner_review_reply_ingress(self, message: str, *, turn_number: int | None, phase: str) -> None:
        if self._store is None or not _looks_like_owner_review_reply(message):
            return
        owner_review = self._config.get("owner_review")
        if not isinstance(owner_review, dict):
            owner_review = {}
        if owner_review.get("reply_ingress_enabled", True) is False:
            return
        owner_id = str(owner_review.get("owner_id") or "owner")
        channels = _owner_review_reply_channels(str(self.platform or ""), owner_review)
        result: dict[str, Any] | None = None
        channel = channels[0]
        for candidate_channel in channels:
            candidate = parse_owner_review_reply(
                self._store,
                message,
                owner_id=owner_id,
                channel=candidate_channel,
                apply=True,
                require_recorded_digest=True,
            )
            result = candidate
            channel = candidate_channel
            if candidate.get("status") == "ok":
                break
            if candidate.get("reason") not in {
                "digest_not_found_or_expired",
                "anchor_not_found_in_current_digest",
                "action_token_not_found_in_recorded_digest",
            }:
                break
        if result is None:
            return
        self._last_owner_review_reply_result = result
        self._last_owner_review_reply_query = message
        self._audit(
            "owner_review_reply_ingress",
            "ok" if result.get("status") == "ok" else "warning",
            {
                "turn_number": turn_number,
                "phase": phase,
                "status": result.get("status"),
                "reason": result.get("reason", ""),
                "channel": channel,
                "owner_id": owner_id,
                "anchor": (result.get("parsed") or {}).get("anchor", ""),
                "action_token": (result.get("parsed") or {}).get("action_token", ""),
                "action_type": (result.get("parsed") or {}).get("action_type", ""),
            },
        )

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        self._current_task_anchor = _build_current_task_anchor(messages, session_id=self.session_id)
        return self._current_task_anchor

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
            "low_clue_recall": {
                "enabled": bool((self._config.get("low_clue_recall") or {}).get("enabled"))
                if isinstance(self._config.get("low_clue_recall"), dict)
                else False,
                "judge_availability": low_clue_judge_availability(self._config.get("low_clue_recall")),
            },
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

    def _refresh_current_task_anchor_from_query(self, query: str, *, session_id: str = "") -> None:
        text = " ".join(str(query or "").split())
        if not text:
            return
        decision = classify_ingress(text, current_task_anchor=self._current_task_anchor)
        if decision.intent == "defer_current_task" and self._current_task_anchor:
            self._write_deferred_current_task_anchor(
                anchor=self._current_task_anchor,
                deferral=text,
                session_id=session_id or self.session_id,
            )
            self._current_task_anchor = _format_deferred_task_anchor(
                deferral=text,
                previous_anchor=self._current_task_anchor,
                session_id=session_id or self.session_id,
            )
            self._foreground_task_only_prefetch = True
            return
        if decision.intent == "explicit_deferred_resume":
            deferred_anchor = self._read_latest_deferred_current_task_anchor()
            if deferred_anchor:
                self._current_task_anchor = _format_resumed_deferred_task_anchor(
                    anchor=deferred_anchor,
                    session_id=session_id or self.session_id,
                )
                self._foreground_task_only_prefetch = True
                return
            self._current_task_anchor = _format_ambiguous_deferred_resume_anchor(
                query=text,
                session_id=session_id or self.session_id,
            )
            self._foreground_task_only_prefetch = True
            return
        if decision.intent == "cancellation":
            self._current_task_anchor = _format_cancelled_task_anchor(
                cancellation=text,
                previous_anchor=self._current_task_anchor,
                session_id=session_id or self.session_id,
            )
            self._foreground_task_only_prefetch = True
            return
        if decision.intent == "continue_current_task":
            self._foreground_task_only_prefetch = True
            return
        if decision.intent == "ambiguous_recall":
            self._current_task_anchor = ""
            self._foreground_task_only_prefetch = False
            return
        self._current_task_anchor = _format_current_task_anchor(
            task=text,
            operations=[],
            session_id=session_id or self.session_id,
        )
        self._foreground_task_only_prefetch = False

    def _write_deferred_current_task_anchor(self, *, anchor: str, deferral: str, session_id: str = "") -> None:
        if self._roots is None:
            return
        record = _deferred_task_record(
            anchor=anchor,
            deferral=deferral,
            session_id=session_id or self.session_id,
            profile=self.profile,
        )
        path = _deferred_tasks_path(self._roots)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        self._audit(
            "deferred_foreground_task_recorded",
            "ok",
            {
                "record_id": record["record_id"],
                "session_id": record["session_id"],
                "profile": record["profile"],
            },
        )

    def _read_latest_deferred_current_task_anchor(self) -> str:
        if self._roots is None:
            return ""
        path = _deferred_tasks_path(self._roots)
        if not path.exists():
            return ""
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if str(record.get("profile") or self.profile) not in {self.profile, ""}:
                continue
            anchor = str(record.get("anchor") or "")
            if anchor.strip():
                return anchor
        return ""


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


_TASK_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(password\s*[:=]\s*)\S+"),
)


def _build_current_task_anchor(messages: list[dict[str, Any]], *, session_id: str = "") -> str:
    latest_user_index: int | None = None
    latest_user_text = ""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if str(message.get("role", "")) != "user":
            continue
        text = _content_text(message.get("content"))
        if text.strip():
            latest_user_index = index
            latest_user_text = text
            break
    if latest_user_index is None or not latest_user_text.strip():
        return ""

    operations: list[str] = []
    for message in messages[latest_user_index + 1 :]:
        role = str(message.get("role", ""))
        if role not in {"assistant", "tool"}:
            continue
        text = _content_text(message.get("content"))
        if _looks_like_operation_context(text):
            operations.append(f"{role}: {_clip(text, 180)}")
    return _format_current_task_anchor(
        task=latest_user_text,
        operations=operations[-4:],
        session_id=session_id,
    )


def _format_current_task_anchor(*, task: str, operations: list[str], session_id: str = "") -> str:
    task = _redact_task_text(_clip(task, 240))
    if not task:
        return ""
    output = [
        "### Memory-OS Current Task Anchor",
        f"- current task: {task}",
    ]
    if session_id:
        output.append(f"- session: {session_id}")
    if operations:
        output.append("- active tool/process state:")
        for operation in operations:
            output.append(f"  - {_redact_task_text(_clip(operation, 220))}")
    output.append(
        "- compression rule: Continue this foreground task after compaction. "
        "Do not switch back to unrelated historical memory topics."
    )
    return _clip_multiline("\n".join(output), 1200)


def _format_cancelled_task_anchor(*, cancellation: str, previous_anchor: str, session_id: str = "") -> str:
    output = [
        "### Memory-OS Current Task Anchor",
        f"- owner cancelled or rejected the foreground task: {_redact_task_text(_clip(cancellation, 240))}",
    ]
    previous_task = _extract_anchor_current_task(previous_anchor)
    if previous_task:
        output.append(f"- cancelled task: {_redact_task_text(_clip(previous_task, 220))}")
    if session_id:
        output.append(f"- session: {session_id}")
    output.append(
        "- response rule: Acknowledge the cancellation and stop the foreground task. "
        "Do not pivot to unrelated system-memory, provider-status, or historical architecture topics "
        "unless the owner explicitly asks."
    )
    return _clip_multiline("\n".join(output), 1200)


def _format_deferred_task_anchor(*, deferral: str, previous_anchor: str, session_id: str = "") -> str:
    output = [
        "### Memory-OS Current Task Anchor",
        f"- owner deferred the foreground task: {_redact_task_text(_clip(deferral, 240))}",
    ]
    previous_task = _extract_anchor_current_task(previous_anchor)
    if previous_task:
        output.append(f"- deferred task: {_redact_task_text(_clip(previous_task, 220))}")
    if session_id:
        output.append(f"- session: {session_id}")
    output.append(
        "- response rule: Acknowledge the deferral and preserve this task for a later explicit resume. "
        "Do not pivot to unrelated historical memory topics."
    )
    return _clip_multiline("\n".join(output), 1200)


def _format_resumed_deferred_task_anchor(*, anchor: str, session_id: str = "") -> str:
    task = _extract_anchor_current_task(anchor)
    operations = _extract_anchor_operation_lines(anchor)
    lines = [
        "### Memory-OS Current Task Anchor",
        "- owner resumed a deferred foreground task",
    ]
    if task:
        lines.append(f"- current task: {_redact_task_text(_clip(task, 240))}")
    if operations:
        lines.append(f"- latest task state: {_redact_task_text(_clip(operations[-1], 260))}")
    if session_id:
        lines.append(f"- resumed in session: {session_id}")
    lines.append(
        "- response rule: Continue this deferred foreground task. "
        "If details are insufficient, ask which file or artifact to inspect before guessing."
    )
    return _clip_multiline("\n".join(line for line in lines if line), 1200)


def _format_ambiguous_deferred_resume_anchor(*, query: str, session_id: str = "") -> str:
    lines = [
        "### Memory-OS Current Task Anchor",
        f"- deferred resume is ambiguous: {_redact_task_text(_clip(query, 240))}",
    ]
    if session_id:
        lines.append(f"- session: {session_id}")
    lines.append(
        "- response rule: Ask the owner to choose which prior task to resume. "
        "Do not assume the latest recalled topic or continue any historical topic "
        "unless the owner selects it."
    )
    return _clip_multiline("\n".join(lines), 900)


def _extract_anchor_current_task(anchor: str) -> str:
    for line in str(anchor or "").splitlines():
        clean = line.strip()
        if clean.startswith("- current task:"):
            return clean.split(":", 1)[1].strip()
    return ""


def _extract_anchor_operation_lines(anchor: str) -> list[str]:
    operations: list[str] = []
    for line in str(anchor or "").splitlines():
        clean = line.strip()
        if clean.startswith("- assistant:") or clean.startswith("- tool:"):
            operations.append(clean[2:].strip())
    return operations[-4:]


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return " ".join(content.split())
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content") or ""
                if value:
                    parts.append(str(value))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(" ".join(parts).split())
    return " ".join(str(content or "").split())


def _looks_like_owner_review_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return False
    if normalized.startswith("/memory "):
        normalized = "memory " + normalized[len("/memory ") :]
    return bool(
        re.fullmatch(r"(?i)(memory|mos)\s+(approve|reject|allow|批准|通过|拒绝|允许)\s+oa_[0-9a-f]{8,32}[：:,.，。!！?？]?", normalized)
        or re.fullmatch(
            r"(?i)(memory|mos)\s+(feedback|mark|反馈)\s+oa_[0-9a-f]{8,32}\s+(useful|irrelevant|too_mechanistic|missing_context|overconfident|needs_specific_recall)[：:,.，。!！?？]?",
            normalized,
        )
    )


def _owner_review_reply_channels(platform: str, owner_review: dict[str, Any]) -> list[str]:
    candidates = [
        platform,
        str(owner_review.get("recurring_delivery_channel") or ""),
        str(owner_review.get("channel") or ""),
        "unknown",
    ]
    channels: list[str] = []
    for candidate in candidates:
        channel = str(candidate or "").strip()
        if not channel or channel in channels:
            continue
        channels.append(channel)
    return channels or ["unknown"]


def _owner_review_reply_context_block(result: dict[str, Any]) -> str:
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    action_result = result.get("owner_action_result") if isinstance(result.get("owner_action_result"), dict) else {}
    active_digest = result.get("active_digest") if isinstance(result.get("active_digest"), dict) else {}
    lines = [
        "### Memory-OS Owner Review Reply",
        f"- status: {_clip(str(result.get('status') or 'unknown'), 80)}",
        f"- anchor: {_clip(str(parsed.get('anchor') or ''), 40)}",
        f"- action_token: {_clip(str(parsed.get('action_token') or ''), 40)}",
        f"- action: {_clip(str(parsed.get('action_type') or ''), 80)}",
        f"- target: {_clip(str(parsed.get('target_type') or ''), 40)}:{_clip(str(parsed.get('target_id') or ''), 120)}",
        f"- digest_binding: {_clip(str(active_digest.get('binding') or ''), 80)}",
        f"- result: {_clip(str(action_result.get('status') or result.get('reason') or ''), 120)}",
        "- response rule: This owner-review command has already been processed by Memory-OS. "
        "Reply with a short confirmation or clarification only; do not continue the normal conversation thread.",
    ]
    return _clip_multiline("\n".join(lines), 900)


def _owner_review_reply_system_instruction(result: dict[str, Any]) -> str:
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    action_result = result.get("owner_action_result") if isinstance(result.get("owner_action_result"), dict) else {}
    status = str(result.get("status") or "unknown")
    if status == "ok":
        action_type = str(parsed.get("action_type") or "owner review action")
        result_status = str(action_result.get("status") or "ok")
        return (
            "### Memory-OS Owner Review Reply Instruction\n"
            f"- processed action: {_clip(action_type, 80)}\n"
            f"- anchor: {_clip(str(parsed.get('anchor') or ''), 40)}\n"
            f"- action_token: {_clip(str(parsed.get('action_token') or ''), 40)}\n"
            f"- processor result: {_clip(result_status, 80)}\n"
            "- response rule: Acknowledge the processed owner-review action in one short sentence. "
            "Do not ask the owner to choose another review anchor unless Memory-OS reported a clarification need."
        )
    return (
        "### Memory-OS Owner Review Reply Instruction\n"
        f"- parser status: {_clip(status, 80)}\n"
        f"- parser reason: {_clip(str(result.get('reason') or ''), 120)}\n"
        "- response rule: Ask for the exact review command or digest anchor. "
        "Do not reinterpret the message as ordinary conversation."
    )


def _looks_like_operation_context(text: str) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    markers = (
        "terminal:",
        "process",
        "proc_",
        "running",
        "wait ",
        "poll ",
        "install",
        "download",
        "clone",
        "git ",
        "fatal:",
        "error",
        "failed",
        "comfyui",
        "正在",
        "安装",
        "下载",
        "失败",
        "报错",
        "后台",
        "进程",
    )
    return any(marker in lowered for marker in markers)


def _is_continue_current_task_query(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    patterns = (
        "继续当前任务",
        "继续刚才的任务",
        "继续这个任务",
        "继续安装",
        "继续执行",
        "继续吧",
        "继续",
        "接着",
        "接着做",
        "keep going",
        "continue",
        "continue current task",
        "continue the current task",
        "resume",
        "resume current task",
    )
    return normalized in patterns


def _is_cancel_current_task_query(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    markers = (
        "算了",
        "别做",
        "不要做",
        "不做了",
        "停下",
        "停止",
        "收手",
        "放弃",
        "取消",
        "别弄",
        "不用做",
        "cancel",
        "stop",
        "abort",
        "give up",
        "never mind",
    )
    return any(marker in normalized for marker in markers)


def _is_defer_current_task_query(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    markers = (
        "先放一下",
        "先放着",
        "暂时不做",
        "晚点再",
        "等下再",
        "下次再",
        "明天再说",
        "回头再说",
        "先搁置",
        "pause",
        "defer",
        "later",
        "tomorrow",
    )
    return any(marker in normalized for marker in markers)


def _is_deferred_continue_query(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().rstrip("。.!！?？").split())
    if not normalized:
        return False
    markers = {
        "继续延期任务",
        "继续延后的任务",
        "继续搁置任务",
        "继续搁置的任务",
        "继续暂停的任务",
        "继续之前暂停的任务",
        "继续之前延期的任务",
        "继续 deferred task",
        "continue the deferred task",
        "resume the deferred task",
    }
    return normalized in markers


def _redact_task_text(value: str) -> str:
    redacted = value
    for pattern in _TASK_SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    return redacted


def _clip_multiline(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _deferred_tasks_path(roots: MemoryOSRoots) -> Any:
    return roots.memory_os_root / "system" / "deferred_foreground_tasks.jsonl"


def _deferred_task_record(*, anchor: str, deferral: str, session_id: str, profile: str) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    seed = f"{created_at}:{session_id}:{anchor}"
    return {
        "schema_version": "memory-os.deferred_foreground_task.v0",
        "record_id": f"dft_{_sha256(seed)[:16]}",
        "created_at": created_at,
        "profile": profile or "memoryos-test",
        "session_id": str(session_id or ""),
        "deferral": _redact_task_text(_clip(deferral, 240)),
        "anchor": _clip_multiline(anchor, 1200),
        "storage_policy": "runtime_system_metadata_not_canonical_memory",
    }


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
