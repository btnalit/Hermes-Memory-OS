"""SessionMirror scanner and bounded apply path for Memory-OS source coverage."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit
from .config import load_config
from .ids import new_event_id
from .roots import MemoryOSRoots
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
from .store import MemoryOSStore


SESSION_MIRROR_APPLY_SCHEMA_VERSION = "memory-os.session_mirror_apply.v0"
SESSION_MIRROR_BOUNDARY_CONTRACT_VERSION = "session-mirror-governed-apply.v1"
SESSION_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[-_\s]?key|token|password|secret)\s*[:=]\s*([^\s;,)\]}]+)"),
)
_BOUNDARY_KEYS = (
    "actual_send",
    "actual_execute",
    "actual_identity_write",
    "actual_unapproved_crystallized_approval",
)


def _false_boundary() -> dict[str, bool]:
    return {key: False for key in _BOUNDARY_KEYS}


def _bounded_auto_apply_dry_run(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": str(report.get("schema_version") or ""),
        "status": str(report.get("status") or ""),
        "candidate_session_count": int(report.get("candidate_session_count") or 0),
        "selected_session_count": int(report.get("selected_session_count") or 0),
        "skipped_by_platform_count": int(report.get("skipped_by_platform_count") or 0),
        "skipped_by_limit_count": int(report.get("skipped_by_limit_count") or 0),
        "selected_session_fingerprints": [
            str(item)
            for item in (report.get("selected_session_fingerprints") if isinstance(report.get("selected_session_fingerprints"), list) else [])
        ][:10],
        "raw_private_body_printed": bool(report.get("raw_private_body_printed")),
    }


def session_mirror_apply_records_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "session_mirror_applies.jsonl"


def read_session_mirror_apply_records(roots: MemoryOSRoots, *, limit: int = 0) -> list[dict[str, Any]]:
    records = _read_jsonl(session_mirror_apply_records_path(roots))
    return records[-max(limit, 0):] if limit else records


def session_mirror_stable_scope_id(
    *,
    digest_item_id: str,
    selected_pending_session_fingerprint: str,
    max_sessions: int,
    platform_allowlist: list[str] | tuple[str, ...] | None,
    expires_at: str = "",
    boundary_contract_version: str = SESSION_MIRROR_BOUNDARY_CONTRACT_VERSION,
) -> str:
    platforms = ",".join(_normalize_platform_allowlist(platform_allowlist))
    material = "|".join(
        [
            str(digest_item_id or ""),
            str(selected_pending_session_fingerprint or ""),
            str(max(int(max_sessions or 0), 0)),
            platforms,
            str(expires_at or ""),
            str(boundary_contract_version or ""),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def session_mirror_graduation_policy(store: MemoryOSStore) -> dict[str, Any]:
    """Return the active owner-approved SessionMirror auto-apply policy, if any."""
    config = load_config(store.roots.hermes_home)
    session_config = config.get("session_mirror") if isinstance(config.get("session_mirror"), dict) else {}
    if session_config.get("auto_apply_after_owner_home_graduation") is False:
        return {
            "schema_version": "memory-os.session_mirror_graduation_policy.v0",
            "status": "disabled",
            "reason": "auto_apply_after_owner_home_graduation_disabled",
            "owner_approved": False,
        }
    try:
        from .owner_actions import read_owner_action_records
    except Exception as exc:
        return {
            "schema_version": "memory-os.session_mirror_graduation_policy.v0",
            "status": "error",
            "reason": "owner_action_records_unavailable",
            "error": str(exc)[:200],
            "owner_approved": False,
        }
    for record in reversed(read_owner_action_records(store.roots)):
        result_ref = record.get("result_ref") if isinstance(record.get("result_ref"), dict) else {}
        token_binding = record.get("token_binding") if isinstance(record.get("token_binding"), dict) else {}
        owner_effect = record.get("owner_effect") if isinstance(record.get("owner_effect"), dict) else {}
        if record.get("schema_version") != "memory-os.owner_action.v0":
            continue
        if record.get("action_type") != "approve_session_mirror_apply":
            continue
        if record.get("target_type") != "session_mirror_apply":
            continue
        if record.get("result") != "applied":
            continue
        if record.get("source") != "latest_owner_home_digest":
            continue
        if token_binding.get("scope") != "owner_home":
            continue
        if owner_effect.get("owner_approved_session_mirror_apply") is not True:
            continue
        if result_ref.get("approval_scope") != "session_mirror_production_bounded_apply":
            continue
        if result_ref.get("auto_apply_after_graduation") is not True:
            continue
        if any(bool(result_ref.get(key)) for key in _BOUNDARY_KEYS):
            continue
        platforms = [
            str(item).lower().replace("-", "_")
            for item in (result_ref.get("platform_allowlist") if isinstance(result_ref.get("platform_allowlist"), list) else [])
            if str(item or "").strip()
        ][:10]
        configured_max = max(int(session_config.get("auto_apply_max_sessions_per_run") or 1), 1)
        approved_max = max(int(result_ref.get("auto_apply_max_sessions_per_run") or result_ref.get("max_sessions") or 1), 1)
        max_sessions = min(configured_max, approved_max)
        return {
            "schema_version": "memory-os.session_mirror_graduation_policy.v0",
            "status": "active",
            "owner_approved": True,
            "approval_ref": str(record.get("owner_action_id") or ""),
            "approval_source": "latest_owner_home_digest",
            "owner_channel_bound": True,
            "stable_scope_id": str(result_ref.get("stable_scope_id") or ""),
            "approved_max_sessions": approved_max,
            "max_sessions_per_run": max_sessions,
            "platform_allowlist": platforms,
            "boundary_contract_version": str(result_ref.get("boundary_contract_version") or ""),
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        }
    return {
        "schema_version": "memory-os.session_mirror_graduation_policy.v0",
        "status": "absent",
        "reason": "no_owner_home_graduation_policy",
        "owner_approved": False,
    }


def auto_apply_graduated_session_mirror(
    store: MemoryOSStore,
    *,
    operator: str = "runtime_heartbeat",
) -> dict[str, Any]:
    """Apply one bounded SessionMirror batch after owner-approved lane graduation."""
    policy = session_mirror_graduation_policy(store)
    if policy.get("status") != "active":
        return {
            "schema_version": "memory-os.session_mirror_auto_apply.v0",
            "status": "skipped",
            "reason": policy.get("reason") or policy.get("status") or "policy_not_active",
            "policy": policy,
            "written_event_ids_count": 0,
            "boundary": _false_boundary(),
        }
    mirror = SessionMirror(store)
    dry_run = mirror.scan(
        dry_run=True,
        max_sessions=int(policy.get("max_sessions_per_run") or 1),
        platform_allowlist=policy.get("platform_allowlist") if isinstance(policy.get("platform_allowlist"), list) else [],
    )
    if int(dry_run.get("selected_session_count") or 0) <= 0:
        return {
            "schema_version": "memory-os.session_mirror_auto_apply.v0",
            "status": "skipped",
            "reason": "no_matching_pending_session",
            "policy": policy,
            "dry_run": _bounded_auto_apply_dry_run(dry_run),
            "written_event_ids_count": 0,
            "boundary": _false_boundary(),
        }
    apply_governance = {
        "owner_approved": True,
        "approval_ref": str(policy.get("approval_ref") or ""),
        "approval_resolved": True,
        "approval_source": "owner_action_lane_graduation",
        "approval_target_type": "session_mirror_apply",
        "approval_target_id": f"production_bounded:{policy.get('stable_scope_id') or ''}",
        "approved_max_sessions": int(policy.get("approved_max_sessions") or 1),
        "owner_channel_bound": True,
        "stable_scope_id": str(policy.get("stable_scope_id") or ""),
        "operator": operator,
        "evidence_refs": [f"session_mirror_lane_graduation:{policy.get('approval_ref') or ''}"],
        "auto_apply": True,
        "lane_graduated": True,
        "historical_bounded_smoke_attested": True,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }
    result = mirror.scan(
        dry_run=False,
        max_sessions=int(policy.get("max_sessions_per_run") or 1),
        platform_allowlist=policy.get("platform_allowlist") if isinstance(policy.get("platform_allowlist"), list) else [],
        apply_governance=apply_governance,
    )
    result["schema_version"] = "memory-os.session_mirror_auto_apply.v0"
    result["auto_apply_policy"] = policy
    return result


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

    def scan(
        self,
        *,
        dry_run: bool = True,
        max_sessions: int = 0,
        platform_allowlist: list[str] | tuple[str, ...] | None = None,
        apply_governance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
        platforms = _normalize_platform_allowlist(platform_allowlist)
        platform_filtered = [
            session for session in new_sessions if not platforms or str(session.get("platform") or "").lower() in platforms
        ]
        limit = max(int(max_sessions or 0), 0)
        if not dry_run and limit == 0:
            limit = 1
        selected_sessions = platform_filtered[:limit] if limit else platform_filtered
        selected_safe_sessions = [_safe_pending_session(session) for session in selected_sessions]
        selected_fingerprints = [str(item["fingerprint"]) for item in selected_safe_sessions]
        skipped_by_platform_count = len(new_sessions) - len(platform_filtered)
        skipped_by_limit_count = max(len(platform_filtered) - len(selected_sessions), 0)
        written_events: list[str] = []
        if not dry_run:
            for session in selected_sessions:
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
                    "candidate_session_count": len(new_sessions),
                    "selected_session_count": len(selected_sessions),
                    "covered_session_count": len(covered),
                    "state_rebuilt": state_rebuilt,
                },
            )
            self._append_apply_record(
                candidate_session_count=len(new_sessions),
                selected_session_count=len(selected_sessions),
                skipped_by_platform_count=skipped_by_platform_count,
                skipped_by_limit_count=skipped_by_limit_count,
                platform_allowlist=platforms,
                max_sessions=limit,
                selected_sessions=selected_safe_sessions,
                selected_session_fingerprints=selected_fingerprints,
                written_event_ids=written_events,
                status="ok" if not findings else "warning",
                findings=findings,
                apply_governance=apply_governance or {},
            )
        governance = _bounded_apply_governance(apply_governance or {})
        return {
            "schema_version": self.report_schema_version,
            "status": "ok" if not findings else "warning",
            "profile": self.store.roots.profile,
            "session_count": len(sessions),
            "covered_session_count": sum(1 for session in sessions if session["session_id"] in covered),
            "candidate_session_count": len(new_sessions),
            "selected_session_count": len(selected_sessions),
            "skipped_by_platform_count": skipped_by_platform_count,
            "skipped_by_limit_count": skipped_by_limit_count,
            "new_event_count": len(selected_sessions),
            "dry_run": dry_run,
            "apply_bounded": not dry_run or bool(limit or platforms),
            "max_sessions": limit,
            "platform_allowlist": platforms,
            "state_rebuilt": state_rebuilt,
            "written_event_ids": written_events,
            "written_event_ids_count": len(written_events),
            "selected_sessions": selected_safe_sessions,
            "selected_session_fingerprints": selected_fingerprints,
            "duplicate_ignored_count": 0,
            "raw_private_body_printed": False,
            "apply_governance": governance,
            "findings": findings,
        }

    def apply_status(self) -> dict[str, Any]:
        records = read_session_mirror_apply_records(self.store.roots)
        latest = records[-1] if records else {}
        return {
            "schema_version": "memory-os.session_mirror_apply_status.v0",
            "profile": self.store.roots.profile,
            "apply_count": len(records),
            "latest_apply": _bounded_apply_record(latest) if latest else {},
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

    def _append_apply_record(
        self,
        *,
        candidate_session_count: int,
        selected_session_count: int,
        skipped_by_platform_count: int,
        skipped_by_limit_count: int,
        platform_allowlist: list[str],
        max_sessions: int,
        selected_sessions: list[dict[str, Any]],
        selected_session_fingerprints: list[str],
        written_event_ids: list[str],
        status: str,
        findings: list[dict[str, Any]],
        apply_governance: dict[str, Any],
    ) -> None:
        now = datetime.now(timezone.utc)
        governance = _bounded_apply_governance(apply_governance)
        record = {
            "schema_version": SESSION_MIRROR_APPLY_SCHEMA_VERSION,
            "apply_id": f"smap_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{hashlib.sha256('|'.join(written_event_ids).encode('utf-8')).hexdigest()[:8]}",
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "profile": self.store.roots.profile or "default",
            "status": status,
            "apply_bounded": bool(max_sessions or platform_allowlist),
            "max_sessions": max_sessions,
            "platform_allowlist": platform_allowlist,
            "candidate_session_count": candidate_session_count,
            "selected_session_count": selected_session_count,
            "skipped_by_platform_count": skipped_by_platform_count,
            "skipped_by_limit_count": skipped_by_limit_count,
            "written_event_ids": written_event_ids,
            "written_event_ids_count": len(written_event_ids),
            "selected_sessions": selected_sessions,
            "selected_session_fingerprints": selected_session_fingerprints,
            "duplicate_ignored_count": 0,
            "raw_private_body_printed": False,
            "finding_count": len(findings),
            "apply_governance": governance,
            "boundary": {
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_unapproved_crystallized_approval": False,
            },
        }
        _append_jsonl(session_mirror_apply_records_path(self.store.roots), record)

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
    last_user = _clip(_redact_secrets(user_messages[-1])) if user_messages else ""
    last_assistant = _clip(_redact_secrets(assistant_messages[-1])) if assistant_messages else ""
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
        "fingerprint": _session_fingerprint(
            source_kind=source_kind,
            session_id=session_id,
            platform=platform,
            updated_at=updated_at,
            event_kind=event_kind,
        ),
    }


def _clip(value: str, limit: int = 80) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "..."


def _redact_secrets(value: str) -> str:
    text = str(value or "")
    for pattern in SESSION_SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return text


def _normalize_platform_allowlist(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        clean = str(value or "").strip().lower().replace("-", "_")
        if clean and clean not in normalized:
            normalized.append(clean)
    return normalized


def _session_fingerprint(*, source_kind: str, session_id: str, platform: str, updated_at: str, event_kind: str) -> str:
    session_hash = hashlib.sha256(str(session_id or "").encode("utf-8")).hexdigest()[:16]
    timestamp_bucket = str(updated_at or "").split("T", 1)[0]
    material = "|".join(
        [
            str(platform or "").lower().replace("-", "_"),
            str(source_kind or ""),
            session_hash,
            timestamp_bucket,
            str(event_kind or ""),
        ]
    )
    return "smfp_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _safe_pending_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "fingerprint": str(session.get("fingerprint") or ""),
        "platform": str(session.get("platform") or ""),
        "source_kind": str(session.get("source_kind") or ""),
        "source_group_id": str(session.get("session_id") or ""),
        "summary": _clip(str(session.get("summary") or ""), limit=180),
        "summary_length": len(str(session.get("summary") or "")),
        "raw_private_body_printed": False,
        "secret_redaction_applied": True,
        "body_material_class": "metadata_or_redacted_summary",
        "message_count": int(session.get("message_count") or 0),
        "tool_count": int(session.get("tool_count") or 0),
    }


def _bounded_apply_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": record.get("schema_version"),
        "apply_id": record.get("apply_id"),
        "created_at": record.get("created_at"),
        "status": record.get("status"),
        "apply_bounded": bool(record.get("apply_bounded")),
        "max_sessions": record.get("max_sessions"),
        "platform_allowlist": record.get("platform_allowlist") if isinstance(record.get("platform_allowlist"), list) else [],
        "candidate_session_count": record.get("candidate_session_count"),
        "selected_session_count": record.get("selected_session_count"),
        "skipped_by_platform_count": record.get("skipped_by_platform_count"),
        "skipped_by_limit_count": record.get("skipped_by_limit_count"),
        "written_event_ids_count": record.get("written_event_ids_count"),
        "selected_session_fingerprints": [
            str(item)
            for item in (record.get("selected_session_fingerprints") if isinstance(record.get("selected_session_fingerprints"), list) else [])
        ][:10],
        "duplicate_ignored_count": record.get("duplicate_ignored_count"),
        "raw_private_body_printed": record.get("raw_private_body_printed"),
        "finding_count": record.get("finding_count"),
        "apply_governance": _bounded_apply_governance(
            record.get("apply_governance") if isinstance(record.get("apply_governance"), dict) else {}
        ),
        "boundary": record.get("boundary") if isinstance(record.get("boundary"), dict) else {},
    }


def _bounded_apply_governance(value: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = value.get("evidence_refs") if isinstance(value.get("evidence_refs"), list) else []
    return {
        "owner_approved": bool(value.get("owner_approved")),
        "approval_ref": str(value.get("approval_ref") or "")[:160],
        "approval_resolved": bool(value.get("approval_resolved")),
        "approval_source": str(value.get("approval_source") or "")[:80],
        "approval_target_type": str(value.get("approval_target_type") or "")[:80],
        "approval_target_id": str(value.get("approval_target_id") or "")[:180],
        "approved_max_sessions": int(value.get("approved_max_sessions") or 0),
        "owner_channel_bound": bool(value.get("owner_channel_bound")),
        "stable_scope_id": str(value.get("stable_scope_id") or "")[:80],
        "selected_pending_session_fingerprint": str(value.get("selected_pending_session_fingerprint") or "")[:120],
        "test_host": bool(value.get("test_host")),
        "test_host_config_allowed": bool(value.get("test_host_config_allowed")),
        "test_host_marker": str(value.get("test_host_marker") or "")[:160],
        "operator": str(value.get("operator") or "")[:120],
        "evidence_refs": [str(item)[:160] for item in evidence_refs[:10] if str(item or "").strip()],
        "auto_apply": bool(value.get("auto_apply")),
        "lane_graduated": bool(value.get("lane_graduated")),
        "historical_bounded_smoke_attested": bool(value.get("historical_bounded_smoke_attested")),
        "historical_bounded_smoke_unattested": bool(value.get("historical_bounded_smoke_unattested")),
    }


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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _finding(id_: str, severity: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": id_, "code": id_, "severity": severity, "message": message, "details": details or {}}
