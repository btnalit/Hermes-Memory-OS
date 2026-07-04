"""Append-only substrate operation ledger for derived monitor evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RAW_SOURCE_CLASSES = {"raw", "raw_turn", "conversation_turn", "event", "working"}


class SubstrateOperationLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: dict[str, Any]) -> None:
        # TODO(data-plane): use append_jsonl_locked for inter-process safety
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
        return records


def derive_substrate_monitor_fields(records: list[dict[str, Any]], *, provider: str) -> dict[str, Any]:
    provider_records = [record for record in records if record.get("provider") == provider]
    retain_records = [record for record in provider_records if record.get("operation") == "retain"]
    recall_records = [record for record in provider_records if record.get("operation") == "recall"]
    reflect_records = [record for record in provider_records if record.get("operation") == "reflect"]
    retract_records = [record for record in provider_records if record.get("operation") in {"retract", "invalidate"}]
    raw_retain_records = [
        record
        for record in retain_records
        if record.get("raw_body_included") is True or str(record.get("source_class") or "") in RAW_SOURCE_CLASSES
    ]
    hot_reflect_records = [record for record in reflect_records if record.get("phase") == "hot_path"]
    latest_snapshot = ""
    for record in reversed(provider_records):
        latest_snapshot = str(record.get("substrate_snapshot_id") or "")
        if latest_snapshot:
            break
    return {
        "provider": provider,
        "retain_count": len(retain_records),
        "raw_retained_count": len(raw_retain_records),
        "no_raw_retained": len(raw_retain_records) == 0,
        "retract_count": len(retract_records),
        "recall_count": len(recall_records),
        "recall_llm_triggered": any(bool(record.get("recall_llm_triggered")) for record in recall_records),
        "reflect_count": len(reflect_records),
        "reflect_hot_path_count": len(hot_reflect_records),
        "reflect_off_hot_path": len(hot_reflect_records) == 0,
        "substrate_snapshot_id": latest_snapshot,
    }
