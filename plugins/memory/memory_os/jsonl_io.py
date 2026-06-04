"""Shared JSONL and small JSON state IO helpers for Memory-OS."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable


def read_jsonl(path: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
            if limit is not None and len(records) >= limit:
                break
    return records


def latest_jsonl_record(path: str | Path) -> dict[str, Any] | None:
    records = read_jsonl(path)
    return records[-1] if records else None


def append_jsonl(path: str | Path, record: dict[str, Any], *, ensure_parent: bool = True) -> None:
    target = Path(path)
    if ensure_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]], *, ensure_parent: bool = True) -> None:
    target = Path(path)
    if ensure_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def write_json_atomic(path: str | Path, data: Any, *, ensure_parent: bool = True) -> None:
    target = Path(path)
    if ensure_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, target)
