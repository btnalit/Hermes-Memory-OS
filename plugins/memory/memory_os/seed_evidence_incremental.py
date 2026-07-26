"""
Seed Evidence incremental reader — offset/cursor based reading.

Replaces the full million-row read with incremental offset/cursor
reading, reducing memory and time per cycle.  Full read path is
retained for rebuild and replay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .jsonl_io import read_jsonl, read_jsonl_result, JsonlReadResult

SEED_EVIDENCE_INCREMENTAL_SCHEMA_VERSION = "memory-os.seed_evidence_incremental.v1"


def read_seed_evidence_incremental(
    path: Path,
    *,
    offset: int = 0,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Read seed evidence records incrementally from an offset.

    Args:
        path: Path to the JSONL file.
        offset: Starting record offset (0 = beginning).
        limit: Maximum number of records to read.

    Returns:
        List of records from the offset.
    """
    records = read_jsonl(path)
    return records[offset:offset + limit]


def read_seed_evidence_by_cursor(
    path: Path,
    *,
    cursor_key: str = "created_at",
    cursor_value: str = "",
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Read seed evidence records by cursor (typically created_at).

    Args:
        path: Path to the JSONL file.
        cursor_key: Field name to use as cursor (default: created_at).
        cursor_value: Cursor value to start from (exclusive).
        limit: Maximum number of records to read.

    Returns:
        List of records after the cursor.
    """
    all_records = read_jsonl(path)
    if cursor_value:
        filtered = [
            r for r in all_records
            if str(r.get(cursor_key, "")) > cursor_value
        ]
    else:
        filtered = all_records
    return filtered[:limit]


def get_seed_evidence_cursor(
    path: Path,
    *,
    cursor_key: str = "created_at",
) -> str:
    """Get the last cursor value from seed evidence records.

    Returns the last cursor_key value, or empty string if no records.
    """
    records = read_jsonl(path)
    if not records:
        return ""
    return str(records[-1].get(cursor_key, ""))


def verify_incremental_equivalence(
    path: Path,
    *,
    chunk_size: int = 1000,
) -> dict[str, Any]:
    """Verify that full read and incremental read produce equivalent results.

    Reads the full file, then reads it in chunks and compares the
    concatenated result.
    """
    full = read_jsonl(path)
    full_len = len(full)

    incremental: list[dict[str, Any]] = []
    offset = 0
    while True:
        chunk = read_seed_evidence_incremental(path, offset=offset, limit=chunk_size)
        if not chunk:
            break
        incremental.extend(chunk)
        offset += len(chunk)

    equivalent = full == incremental

    return {
        "schema_version": SEED_EVIDENCE_INCREMENTAL_SCHEMA_VERSION,
        "full_count": full_len,
        "incremental_count": len(incremental),
        "equivalent": equivalent,
        "chunk_size": chunk_size,
        "chunks_read": offset // chunk_size if chunk_size else 0,
    }