"""
Unified time-utility module for Memory-OS.

Consolidates all timestamp parsing, formatting, and comparison logic
into a single authoritative module.  Every module that needs to parse
or format a datetime should import from here instead of defining its
own private helper.

Semantic matrix
===============
| Dimension          | Behaviour                                              |
|--------------------|--------------------------------------------------------|
| Z suffix           | Accepted and normalised to UTC                         |
| naive datetime     | Fail-closed (returns None) unless explicit allow_naive  |
| empty / invalid    | Returns None                                           |
| date-only          | Not allowed (returns None)                             |
| microsecond ommis  | Normalised to 0 (sorted consistently)                  |
| timezone offset    | Normalised to UTC before comparison                    |
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

# ── ISO-8601 patterns ──────────────────────────────────────────────────────
_ISO_UTC_RE = re.compile(
    r"^"
    r"(\d{4})-(\d{2})-(\d{2})"
    r"[T ]"
    r"(\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d+))?"         # optional fractional seconds
    r"(?:Z|[+-]\d{2}:?\d{2})?"  # optional timezone (Z or offset)
    r"$"
)

_ISO_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TIMEUTIL_SCHEMA_VERSION = "memory-os.timeutil.v1"


def parse_utc(value: str | None, *, allow_naive: bool = False) -> datetime | None:
    """Parse an ISO-8601 string to a timezone-aware datetime in UTC.

    Returns None when the value is empty, unparseable, date-only, or
    naive (unless allow_naive=True).
    """
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    # Reject date-only
    if _ISO_DATE_ONLY_RE.match(value):
        return None
    m = _ISO_UTC_RE.match(value)
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour, minute, second = int(m.group(4)), int(m.group(5)), int(m.group(6))
    frac = m.group(7)
    microsecond = 0
    if frac:
        # Pad or truncate to 6 digits
        frac = frac[:6].ljust(6, "0")
        microsecond = int(frac)
    # Detect timezone
    tz: timezone | None = None
    if value.endswith("Z") or "Z" in value[len(value) - 6:]:
        tz = timezone.utc
    else:
        offset_match = re.search(r"([+-])(\d{2}):?(\d{2})$", value)
        if offset_match:
            sign = 1 if offset_match.group(1) == "+" else -1
            hours = int(offset_match.group(2))
            minutes = int(offset_match.group(3))
            offset = timedelta(hours=hours, minutes=minutes) * sign
            tz = timezone(offset)
        elif not allow_naive:
            return None
    try:
        dt = datetime(year, month, day, hour, minute, second, microsecond, tzinfo=tz)
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is not None and dt.tzinfo != timezone.utc:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_utc(dt: datetime | None) -> str:
    """Format a datetime as ISO-8601 UTC string with Z suffix.

    Returns empty string when dt is None.
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}"[:3] + "Z"


def format_utc_micro(dt: datetime | None) -> str:
    """Format with full microsecond precision."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}" + "Z"


def now_utc() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def is_naive(dt: datetime) -> bool:
    """Return True if the datetime is timezone-naive."""
    return dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None


def safe_compare(a: datetime | None, b: datetime | None) -> int:
    """Compare two datetimes safely.

    Returns -1 if a < b, 0 if a == b, 1 if a > b.
    None is treated as -infinity (less than any real datetime).
    """
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    # Normalise both to UTC for comparison
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    else:
        a = a.astimezone(timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    else:
        b = b.astimezone(timezone.utc)
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def max_safe(*args: datetime | None) -> datetime | None:
    """Return the latest non-None datetime."""
    non_none = [dt for dt in args if dt is not None]
    return max(non_none) if non_none else None


def min_safe(*args: datetime | None) -> datetime | None:
    """Return the earliest non-None datetime."""
    non_none = [dt for dt in args if dt is not None]
    return min(non_none) if non_none else None


def age_seconds(dt: datetime | None, *, now: datetime | None = None) -> float | None:
    """Return the age in seconds of a datetime relative to now.

    Returns None when dt is None.
    """
    if dt is None:
        return None
    ref = now if now is not None else now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (ref - dt).total_seconds()


# ── Backward-compatible aliases for existing callers ───────────────────────
# These allow gradual migration: new code imports from timeutil directly,
# old modules can be migrated one by one.

def parse_timestamp(value: str | None, *, allow_naive: bool = False) -> datetime | None:
    """Alias for parse_utc — for callers that expect a 'timestamp' parse."""
    return parse_utc(value, allow_naive=allow_naive)


def parse_dt(value: str | None) -> datetime | None:
    """Alias for parse_utc — strict mode (no naive allowed)."""
    return parse_utc(value, allow_naive=False)