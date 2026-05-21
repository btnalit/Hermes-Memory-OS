"""Read-only SessionMirror scanner for Memory-OS source coverage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit
from .ids import new_event_id
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
from .store import MemoryOSStore


class SessionMirror:
    """Mirror profile session facts into bounded-summary Memory-OS events."""

    state_schema_version = "memory-os.session_mirror_state.v0"
    report_schema_version = "memory-os.session_mirror_report.v0"

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    @property
    def state_db_path(self) -> Path:
        return self.store.roots.hermes_home / "state.db"

    @property
    def sessions_root(self) -> Path:
        return self.store.roots.hermes_home / "sessions"

    @property
    def state_path(self) -> Path:
        return self.store.roots.memory_os_root / "runtime" / "session_mirror_state.json"

    def status(self) -> dict[str, Any]:
        state, rebuilt, findings = self._load_state(persist_repair=False)
        sessions = self._discover_sessions()
        covered = self._provider_captured_session_ids()
        pending = [
            session
            for session in sessions
            if session["session_id"] not in covered and session["dedup_key"] not in state["seen_sessions"]
        ]
        return {
            "schema_version": "memory-os.session_mirror_status.v0",
            "status": "ok" if not findings else "warning",
            "profile": self.store.roots.profile,
            "session_count": len(sessions),
            "covered_session_count": sum(1 for session in sessions if session["session_id"] in covered),
            "pending_session_count": len(pending),
            "state_db_present": self.state_db_path.exists(),
            "sessions_root_present": self.sessions_root.exists(),
            "state_path": str(self.state_path),
            "state_rebuilt": rebuilt,
            "findings": findings,
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if self.state_db_path.exists():
            try:
                self._read_state_db_sessions()
            except Exception as exc:
                findings.append(_finding("session_state_db_unreadable", "error", "state.db cannot be read in read-only mode", {"error": str(exc)}))
        if self.sessions_root.exists() and not self.sessions_root.is_dir():
            findings.append(_finding("sessions_root_not_directory", "error", "sessions root exists but is not a directory"))
        status = "error" if any(finding["severity"] == "error" for finding in findings) else "ok"
        return {
            "schema_version": "memory-os.session_mirror_doctor.v0",
            "status": status,
            "profile": self.store.roots.profile,
            "findings": findings,
        }

    def scan(self, *, dry_run: bool = True) -> dict[str, Any]:
        if not dry_run:
            self.store.initialize()
        state, state_rebuilt, findings = self._load_state(persist_repair=not dry_run)
        sessions = self._discover_sessions()
        covered = self._provider_captured_session_ids()
        new_sessions = [
            session
            for session in sessions
            if session["session_id"] not in covered and session["dedup_key"] not in state["seen_sessions"]
        ]
        written_events: list[str] = []
        if not dry_run:
            for session in new_sessions:
                event = self._event_for_session(session)
                self.store.append_event(event)
                state["seen_sessions"][session["dedup_key"]] = {
                    "event_id": event.id,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                }
                written_events.append(event.id)
            state["last_scan_at"] = datetime.now(timezone.utc).isoformat()
            self._write_state(state)
            append_audit(
                self.store.roots.audit_path,
                action="session_mirror_scan",
                status="ok",
                target=str(self.store.roots.hermes_home),
                details={
                    "dry_run": False,
                    "new_event_count": len(written_events),
                    "covered_session_count": len(covered),
                    "state_rebuilt": state_rebuilt,
                },
            )
        return {
            "schema_version": self.report_schema_version,
            "status": "ok" if not findings else "warning",
            "profile": self.store.roots.profile,
            "session_count": len(sessions),
            "covered_session_count": sum(1 for session in sessions if session["session_id"] in covered),
            "new_event_count": len(new_sessions),
            "dry_run": dry_run,
            "state_rebuilt": state_rebuilt,
            "written_event_ids": written_events,
            "findings": findings,
        }

    def _discover_sessions(self) -> list[dict[str, Any]]:
        if self.state_db_path.exists():
            sessions = self._read_state_db_sessions()
            if sessions:
                return sessions
        return self._read_session_json_files()

    def _read_state_db_sessions(self) -> list[dict[str, Any]]:
        uri = f"file:{self.state_db_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "sessions"):
                return []
            session_columns = _table_columns(conn, "sessions")
            message_columns = _table_columns(conn, "messages") if _table_exists(conn, "messages") else set()
            id_col = _first_existing(session_columns, ("id", "session_id", "uuid"))
            source_col = _first_existing(session_columns, ("source", "platform", "channel", "kind"))
            updated_col = _first_existing(session_columns, ("updated_at", "last_updated", "created_at"))
            if not id_col:
                return []
            rows = conn.execute(f"select * from sessions order by {id_col}").fetchall()
            sessions = []
            for row in rows:
                session_id = str(row[id_col])
                platform = str(row[source_col]) if source_col else "unknown"
                updated_at = str(row[updated_col]) if updated_col else datetime.now(timezone.utc).isoformat()
                messages = _read_messages_for_session(conn, message_columns, session_id)
                sessions.append(_session_record(
                    source_kind="state_db",
                    source_ref=str(self.state_db_path.resolve()),
                    session_id=session_id,
                    platform=platform,
                    updated_at=updated_at,
                    messages=messages,
                ))
            return sessions

    def _read_session_json_files(self) -> list[dict[str, Any]]:
        if not self.sessions_root.exists():
            return []
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.sessions_root.glob("session_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            session_id = str(data.get("id") or data.get("session_id") or path.stem)
            platform = str(data.get("platform") or data.get("source") or data.get("channel") or "unknown")
            updated_at = str(data.get("updated_at") or data.get("created_at") or datetime.now(timezone.utc).isoformat())
            raw_messages = data.get("messages", [])
            messages = [dict(item) for item in raw_messages if isinstance(item, dict)]
            sessions.append(_session_record(
                source_kind="session_json",
                source_ref=str(path.resolve()),
                session_id=session_id,
                platform=platform,
                updated_at=updated_at,
                messages=messages,
            ))
        return sessions

    def _load_state(self, *, persist_repair: bool) -> tuple[dict[str, Any], bool, list[dict[str, Any]]]:
        if not self.state_path.exists():
            return self._rebuild_state(), False, []
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("seen_sessions", {}), dict):
                raise ValueError("state shape is invalid")
            data.setdefault("schema_version", self.state_schema_version)
            data.setdefault("last_scan_at", "")
            data.setdefault("seen_sessions", {})
            return data, False, []
        except Exception as exc:
            state = self._rebuild_state()
            if persist_repair:
                self._write_state(state)
            return state, True, [
                _finding(
                    "session_mirror_state_rebuilt",
                    "warning",
                    "SessionMirror state was corrupt and rebuilt from Memory-OS events.",
                    {"error": str(exc)},
                )
            ]

    def _rebuild_state(self) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for record in _read_event_records(self.store):
            if record.get("kind") != "conversation_turn_mirrored":
                continue
            safe_ref = record.get("safe_ref", {})
            if not isinstance(safe_ref, dict):
                continue
            dedup_key = str(safe_ref.get("dedup_key", ""))
            if dedup_key:
                seen[dedup_key] = {
                    "event_id": str(record.get("id", "")),
                    "indexed_at": str(record.get("ts", "")),
                }
        return {
            "schema_version": self.state_schema_version,
            "seen_sessions": seen,
            "last_scan_at": "",
        }

    def _provider_captured_session_ids(self) -> set[str]:
        captured: set[str] = set()
        for record in _read_event_records(self.store):
            if record.get("kind") != "conversation_turn":
                continue
            safe_ref = record.get("safe_ref", {})
            if isinstance(safe_ref, dict) and safe_ref.get("session_id"):
                captured.add(str(safe_ref["session_id"]))
        return captured

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _event_for_session(self, session: dict[str, Any]) -> EventEnvelope:
        now = datetime.now(timezone.utc)
        unique = hashlib.sha256(str(session["dedup_key"]).encode("utf-8")).hexdigest()[:10]
        return EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id=new_event_id(now, unique=unique),
            ts=now.isoformat(),
            profile=self.store.roots.profile or "default",
            source="session_mirror",
            kind=session["event_kind"],
            summary=session["summary"],
            safe_ref={
                "source_module": "session_mirror",
                "source_kind": session["source_kind"],
                "source_ref": session["source_ref"],
                "session_id": session["session_id"],
                "platform": session["platform"],
                "message_count": session["message_count"],
                "tool_count": session["tool_count"],
                "content_sha256": session["content_sha256"],
                "dedup_key": session["dedup_key"],
                "drive_policy": session["drive_policy"],
                "candidate_allowed": False,
                "body_policy": "bounded_summary",
            },
            tags=["session", "mirror", session["source_kind"], session["platform"]],
            sensitivity="private",
            body_policy="bounded_summary",
            hashes={"content_sha256": session["content_sha256"]},
            promotion_state="raw",
        )


def _read_messages_for_session(conn: sqlite3.Connection, columns: set[str], session_id: str) -> list[dict[str, Any]]:
    if not columns:
        return []
    session_col = _first_existing(columns, ("session_id", "sid"))
    role_col = _first_existing(columns, ("role", "author", "type"))
    content_col = _first_existing(columns, ("content", "text", "body", "message"))
    created_col = _first_existing(columns, ("created_at", "ts", "timestamp"))
    if not session_col:
        return []
    order_col = created_col or "rowid"
    rows = conn.execute(
        f"select * from messages where {session_col} = ? order by {order_col}",
        (session_id,),
    ).fetchall()
    messages: list[dict[str, Any]] = []
    for row in rows:
        messages.append(
            {
                "role": str(row[role_col]) if role_col else "",
                "content": str(row[content_col]) if content_col else "",
                "created_at": str(row[created_col]) if created_col else "",
            }
        )
    return messages


def _session_record(
    *,
    source_kind: str,
    source_ref: str,
    session_id: str,
    platform: str,
    updated_at: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    user_messages = [str(item.get("content", "")) for item in messages if str(item.get("role", "")).lower() == "user"]
    assistant_messages = [str(item.get("content", "")) for item in messages if str(item.get("role", "")).lower() == "assistant"]
    tool_count = sum(1 for item in messages if str(item.get("role", "")).lower() == "tool")
    raw_material = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    content_sha256 = hashlib.sha256(raw_material.encode("utf-8")).hexdigest()
    last_user = _clip(user_messages[-1]) if user_messages else ""
    last_assistant = _clip(assistant_messages[-1]) if assistant_messages else ""
    if last_user or last_assistant:
        event_kind = "conversation_turn_mirrored"
        drive_policy = "eligible"
        summary = (
            f"Session {session_id} on {platform} mirrored; "
            f"last_user={last_user}; last_assistant={last_assistant}."
        )
    else:
        event_kind = "session_observed"
        drive_policy = "index_only"
        summary = f"Session {session_id} on {platform} observed with {len(messages)} messages."
    return {
        "source_kind": source_kind,
        "source_ref": source_ref,
        "session_id": session_id,
        "platform": platform,
        "updated_at": updated_at,
        "message_count": len(messages),
        "tool_count": tool_count,
        "content_sha256": content_sha256,
        "dedup_key": f"session::{source_kind}::{session_id}::{content_sha256}",
        "event_kind": event_kind,
        "drive_policy": drive_policy,
        "summary": summary,
    }


def _clip(value: str, limit: int = 80) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "..."


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("select name from sqlite_master where type = 'table' and name = ?", (table_name,)).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"pragma table_info({table_name})").fetchall()}


def _first_existing(columns: set[str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in columns:
            return name
    return ""


def _read_event_records(store: MemoryOSStore) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(store.roots.events_root.glob("*/*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def _finding(id_: str, severity: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": id_, "code": id_, "severity": severity, "message": message, "details": details or {}}
