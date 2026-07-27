"""Governed roster contracts for Hermes Community."""

from __future__ import annotations

import json

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonl_io import _append_line_under_lock, locked_jsonl_file

ROSTER_SCHEMA_VERSION = "memory-os.community.roster.v1"

_VALID_STATUSES = {"active", "dormant", "retired"}
_ALLOWED_TRANSITIONS = {
    "active": {"dormant", "retired"},
    "dormant": {"active", "retired"},
    "retired": set(),
}


@dataclass
class RosterEntry:
    """Current identity and lifecycle state for one community member."""

    id: str
    name: str
    type: str = "agent"
    backend: str = ""
    channel: str = ""
    introduced_by: str = "owner"
    relationship: str = "acquaintance"
    known_since: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "active"
    charter: str = ""
    lifecycle: str = "open-ended"
    token_budget_weekly: int = 200000

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ROSTER_SCHEMA_VERSION,
            "event": "created",
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "backend": self.backend,
            "channel": self.channel,
            "introduced_by": self.introduced_by,
            "relationship": self.relationship,
            "known_since": self.known_since,
            "tags": list(self.tags),
            "status": self.status,
            "charter": self.charter,
            "lifecycle": self.lifecycle,
            "token_budget_weekly": self.token_budget_weekly,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def validate_partner_id(partner_id: str) -> str:
    """Return a path-safe partner id or raise ``ValueError``.

    New generated IDs are portable ASCII slugs. Existing Unicode IDs remain
    readable for backward compatibility; path separators, dots and whitespace
    are never accepted.
    """

    value = str(partner_id or "")
    if not (2 <= len(value) <= 64):
        raise ValueError("invalid partner id")
    if not value[0].isalpha():
        raise ValueError("invalid partner id")
    if any(not (char.isalnum() or char in {"-", "_"}) for char in value):
        raise ValueError("invalid partner id")
    return value


def _read_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    if not path.exists():
        return rows, ["roster file not found"]
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return rows, [f"roster read error: {type(exc).__name__}"]
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"line {line_number}: record must be an object")
            continue
        rows.append(row)
    return rows, errors


def _materialize_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    current: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for row in rows:
        partner_id = str(row.get("id") or "")
        if not partner_id:
            errors.append("missing id")
            continue
        try:
            validate_partner_id(partner_id)
        except ValueError:
            errors.append(f"invalid id: {partner_id}")
            continue
        event = str(row.get("event") or "created")
        if event == "status_transition":
            prior = current.get(partner_id)
            if prior is None:
                errors.append(f"transition without existing id: {partner_id}")
                continue
            from_status = str(row.get("from_status") or "")
            to_status = str(row.get("status") or "")
            if from_status != str(prior.get("status") or ""):
                errors.append(f"stale transition for id: {partner_id}")
                continue
            if to_status not in _ALLOWED_TRANSITIONS.get(from_status, set()):
                errors.append(f"invalid transition: {from_status}->{to_status}")
                continue
            updated = dict(prior)
            updated.update(row)
            current[partner_id] = updated
            continue
        if partner_id in current:
            errors.append(f"duplicate id: {partner_id}")
            continue
        current[partner_id] = dict(row)
    return current, errors


def validate_roster(path: Path) -> list[str]:
    """Validate JSONL syntax, row types, identity uniqueness and lifecycle."""

    rows, errors = _read_rows(path)
    if errors == ["roster file not found"]:
        return errors
    current, semantic_errors = _materialize_rows(rows)
    errors.extend(semantic_errors)
    for partner_id, row in current.items():
        if not row.get("name"):
            errors.append(f"missing name: {partner_id}")
        status = str(row.get("status") or "")
        if status not in _VALID_STATUSES:
            errors.append(f"invalid status: {status}")
    # Preserve the line-oriented wording used by the public validator tests.
    line_errors: list[str] = []
    if path.exists():
        seen: set[str] = set()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(row, dict):
                continue
            partner_id = str(row.get("id") or "")
            event = str(row.get("event") or "created")
            if not partner_id:
                line_errors.append(f"line {line_number}: missing id")
            elif event != "status_transition" and partner_id in seen:
                line_errors.append(f"line {line_number}: duplicate id: {partner_id}")
            if event != "status_transition":
                seen.add(partner_id)
            if not row.get("name") and event != "status_transition":
                line_errors.append(f"line {line_number}: missing name")
            status = str(row.get("status") or "")
            if status and status not in _VALID_STATUSES:
                line_errors.append(f"line {line_number}: invalid status: {status}")
    # Prefer detailed line errors and remove equivalent summary duplicates.
    summarized = {
        item for item in errors
        if not any(item.endswith(detail.split(": ", 1)[-1]) for detail in line_errors)
    }
    return [*line_errors, *sorted(summarized)]


def reserve_roster_entry(
    path: Path,
    entry: RosterEntry,
    *,
    max_active: int | None = None,
) -> list[str]:
    """Atomically reserve a unique identity and optional active-budget slot."""

    try:
        validate_partner_id(entry.id)
    except ValueError as exc:
        return [str(exc)]
    if entry.status not in _VALID_STATUSES:
        return [f"invalid status: {entry.status}"]
    with locked_jsonl_file(path) as target:
        rows, read_errors = _read_rows(target)
        if read_errors and read_errors != ["roster file not found"]:
            return read_errors
        current, semantic_errors = _materialize_rows(rows)
        if semantic_errors:
            return semantic_errors
        if entry.id in current:
            return [f"duplicate id: {entry.id}"]
        if max_active is not None and entry.status == "active":
            active_count = sum(1 for row in current.values() if str(row.get("status") or "") == "active")
            if active_count >= max_active:
                return ["community active partner limit reached"]
        _append_line_under_lock(
            target,
            json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        )
    return []


def add_to_roster(path: Path, entry: RosterEntry) -> list[str]:
    """Atomically append a unique roster identity."""

    return reserve_roster_entry(path, entry)


def get_roster(path: Path) -> list[RosterEntry]:
    rows, _errors = _read_rows(path)
    current, _semantic_errors = _materialize_rows(rows)
    entries: list[RosterEntry] = []
    for row in current.values():
        try:
            entries.append(
                RosterEntry(**{
                    key: value
                    for key, value in row.items()
                    if key in RosterEntry.__dataclass_fields__
                })
            )
        except TypeError:
            continue
    return entries


def get_active_roster(path: Path) -> list[RosterEntry]:
    return [entry for entry in get_roster(path) if entry.status == "active"]


def transition_partner_status(
    path: Path,
    partner_id: str,
    status: str,
    *,
    actor: str,
) -> list[str]:
    """Append a governed lifecycle transition; retirement is owner-only."""

    try:
        validate_partner_id(partner_id)
    except ValueError as exc:
        return [str(exc)]
    if actor not in {"owner", "sannai"}:
        return ["actor is not authorized to transition partners"]
    if status == "retired" and actor != "owner":
        return ["retirement requires owner authorization"]
    with locked_jsonl_file(path) as target:
        rows, errors = _read_rows(target)
        if errors and errors != ["roster file not found"]:
            return errors
        current, semantic_errors = _materialize_rows(rows)
        if semantic_errors:
            return semantic_errors
        prior = current.get(partner_id)
        if prior is None:
            return [f"partner not found: {partner_id}"]
        from_status = str(prior.get("status") or "")
        if status not in _ALLOWED_TRANSITIONS.get(from_status, set()):
            return [f"invalid transition: {from_status}->{status}"]
        record = {
            "schema_version": ROSTER_SCHEMA_VERSION,
            "event": "status_transition",
            "id": partner_id,
            "name": str(prior.get("name") or ""),
            "from_status": from_status,
            "status": status,
            "actor": actor,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _append_line_under_lock(
            target,
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n",
        )
    return []


def build_community_snapshot(roster_path: Path) -> dict[str, Any]:
    """Compatibility snapshot containing active names and count."""

    active = get_active_roster(roster_path)
    return {
        "schema_version": ROSTER_SCHEMA_VERSION,
        "active_partners": [entry.name for entry in active],
        "partner_count": len(active),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
