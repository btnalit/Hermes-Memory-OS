"""Projection coherence helpers for derived substrates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ProjectionLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def record_retain(
        self,
        *,
        provider: str,
        source_record_ref: str,
        source_version: str,
        substrate_record_id: str,
        substrate_snapshot_id: str,
    ) -> None:
        self.append(
            {
                "provider": provider,
                "operation": "retain",
                "source_record_ref": source_record_ref,
                "source_version": source_version,
                "substrate_record_id": substrate_record_id,
                "substrate_snapshot_id": substrate_snapshot_id,
                "projection_status": "active",
            }
        )

    def record_invalidate(
        self,
        *,
        provider: str,
        source_record_ref: str,
        source_version: str,
        reason: str,
        substrate_snapshot_id: str,
    ) -> None:
        self.append(
            {
                "provider": provider,
                "operation": "invalidate",
                "source_record_ref": source_record_ref,
                "source_version": source_version,
                "reason": reason,
                "substrate_snapshot_id": substrate_snapshot_id,
                "projection_status": "invalidated",
            }
        )

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


def derive_projection_coherence(
    records: list[dict[str, Any]],
    *,
    provider: str,
    demoted_source_refs: set[str] | None = None,
) -> dict[str, Any]:
    demoted_source_refs = demoted_source_refs or set()
    provider_records = [record for record in records if record.get("provider") == provider]
    retained_refs = {
        str(record.get("source_record_ref") or "")
        for record in provider_records
        if record.get("operation") == "retain"
    }
    invalidated_refs = {
        str(record.get("source_record_ref") or "")
        for record in provider_records
        if record.get("operation") in {"invalidate", "retract"}
    }
    active_refs = sorted(ref for ref in retained_refs if ref and ref not in invalidated_refs)
    stale_refs = sorted(ref for ref in active_refs if ref in demoted_source_refs)
    coherent_active_refs = [ref for ref in active_refs if ref not in set(stale_refs)]
    return {
        "provider": provider,
        "active_projection_count": len(coherent_active_refs),
        "retract_count": len([ref for ref in invalidated_refs if ref]),
        "projection_stale_count": len(stale_refs),
        "stale_source_refs": stale_refs,
    }
