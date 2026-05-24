"""Synthetic-only fixture corpus for RH-31."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.memory_os.runner.types import Rh31Case, Rh31Document


_DATA_DIR = Path(__file__).resolve().parent


def load_cases() -> list[Rh31Case]:
    return [
        Rh31Case(
            case_id=str(record["case_id"]),
            query=str(record["query"]),
            expected_class=str(record["expected_class"]),
            expected_terms=tuple(str(item) for item in record.get("expected_terms", [])),
            expected_heading=str(record.get("expected_heading") or ""),
            family=str(record.get("family") or "general"),
            weight=float(record.get("weight") or 1.0),
        )
        for record in _read_jsonl(_DATA_DIR / "questions.jsonl")
    ]


def load_corpus() -> list[Rh31Document]:
    return [
        Rh31Document(
            doc_id=str(record["doc_id"]),
            text=str(record["text"]),
            source_class=str(record["source_class"]),
            tags=tuple(str(item) for item in record.get("tags", [])),
        )
        for record in _read_jsonl(_DATA_DIR / "corpus.jsonl")
    ]


def load_expected() -> dict[str, dict[str, object]]:
    return {str(record["case_id"]): dict(record) for record in _read_jsonl(_DATA_DIR / "expected.jsonl")}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            records.append(parsed)
    return records
