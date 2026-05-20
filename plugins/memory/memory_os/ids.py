"""Stable ID helpers for Memory-OS records."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def _new_id(prefix: str, now: datetime | None = None, *, unique: str | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    suffix = unique if unique is not None else uuid4().hex[:10]
    return f"{prefix}_{stamp}_{suffix}"


def new_event_id(now: datetime | None = None, *, unique: str | None = None) -> str:
    return _new_id("evt", now, unique=unique)


def new_working_id(now: datetime | None = None, *, unique: str | None = None) -> str:
    return _new_id("wrk", now, unique=unique)


def new_crystallized_id(now: datetime | None = None, *, unique: str | None = None) -> str:
    return _new_id("cry", now, unique=unique)


def new_audit_id(now: datetime | None = None, *, unique: str | None = None) -> str:
    return _new_id("audit", now, unique=unique)


def new_view_id(now: datetime | None = None, *, unique: str | None = None) -> str:
    return _new_id("view", now, unique=unique)
