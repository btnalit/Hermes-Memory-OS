"""Disabled-by-default Hindsight export smoke adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from ..audit import append_audit
from ..crystallized import CrystallizedMemoryService, CrystallizedRecord
from ..store import MemoryOSStore, _format_frontmatter


class HindsightClient(Protocol):
    def retain(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HindsightAdapterConfig:
    enabled: bool = False


class HindsightExportRefused(ValueError):
    """Raised when callers try to export non-approved canonical data."""


class HindsightAdapter:
    """Export only safe, owner-approved crystallized records to Hindsight.

    This adapter intentionally has no built-in network client. Tests and future
    integration code must inject a client, keeping Slice 13 a smoke boundary.
    """

    def __init__(
        self,
        store: MemoryOSStore,
        *,
        config: HindsightAdapterConfig | None = None,
        client: HindsightClient | None = None,
    ) -> None:
        self.store = store
        self.config = config or HindsightAdapterConfig()
        self.client = client

    def export_all(self) -> dict[str, Any]:
        if not self.config.enabled:
            self._audit("hindsight_export_disabled", "warning", str(self.store.roots.crystallized_root), {})
            return _report(enabled=False)

        report = _report(enabled=True)
        for record in self._records():
            if record.frontmatter.get("hindsight_indexed") is True:
                _skip(report, record, "already_indexed")
                continue
            if record.frontmatter.get("approval_purpose") != "approve_for_crystallized":
                _skip(report, record, "not_approved_for_crystallized")
                continue
            if record.frontmatter.get("sensitivity") != "public":
                _skip(report, record, "private_body_not_exported")
                self._audit(
                    "hindsight_export_skipped",
                    "warning",
                    record.file_name,
                    {"record_id": _record_id(record), "reason": "private_body_not_exported"},
                )
                continue
            payload = build_export_payload(record)
            try:
                if self.client is None:
                    raise RuntimeError("hindsight client not configured")
                self.client.retain(payload)
            except Exception as exc:
                report["failed_count"] += 1
                report["errors"].append({"record_id": _record_id(record), "reason": str(exc)})
                self._audit(
                    "hindsight_export_failed",
                    "error",
                    record.file_name,
                    {"record_id": _record_id(record), "error": str(exc)},
                )
                continue
            self._mark_indexed(record)
            report["exported_count"] += 1
            report["exported_record_ids"].append(_record_id(record))
            self._audit(
                "hindsight_export_succeeded",
                "ok",
                record.file_name,
                {"record_id": _record_id(record)},
            )
        return report

    def export_event(self, event: Any) -> None:
        raise HindsightExportRefused("Hindsight adapter cannot export raw events")

    def export_working_item(self, item: Any) -> None:
        raise HindsightExportRefused("Hindsight adapter cannot export working memory drafts")

    def export_cw019_candidate(self, candidate: Any) -> None:
        raise HindsightExportRefused("Hindsight adapter cannot export CW-019 pending candidates")

    def _records(self) -> list[CrystallizedRecord]:
        service = CrystallizedMemoryService(self.store)
        records: list[CrystallizedRecord] = []
        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records.extend(service.read_records(path.name))
        return records

    def _mark_indexed(self, record: CrystallizedRecord) -> None:
        path = self.store.roots.crystallized_root / record.file_name
        records = CrystallizedMemoryService(self.store).read_records(record.file_name)
        rendered: list[str] = []
        for current in records:
            frontmatter = dict(current.frontmatter)
            if frontmatter.get("id") == _record_id(record):
                frontmatter["hindsight_indexed"] = True
            rendered.append(_format_frontmatter(frontmatter))
            rendered.append("")
            rendered.append(current.body.rstrip())
            rendered.append("")
        tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            tmp_path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
            tmp_path.replace(path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _audit(self, action: str, status: str, target: str, details: dict[str, Any]) -> None:
        append_audit(
            self.store.roots.audit_path,
            action=action,
            status=status,
            target=target,
            details=details,
        )


def build_export_payload(record: CrystallizedRecord) -> dict[str, Any]:
    if record.frontmatter.get("approval_purpose") != "approve_for_crystallized":
        raise HindsightExportRefused("record is not approved for crystallized export")
    if record.frontmatter.get("sensitivity") != "public":
        raise HindsightExportRefused("record body is private and cannot be exported")
    return {
        "schema_version": "memory-os.hindsight_export.v0",
        "record_id": _record_id(record),
        "kind": str(record.frontmatter.get("kind", "")),
        "text": record.body,
        "tags": [str(tag) for tag in record.frontmatter.get("tags", [])],
        "source_event_ids": [str(item) for item in record.frontmatter.get("source_event_ids", [])],
        "metadata": {
            "candidate_id": str(record.frontmatter.get("candidate_id", "")),
            "approved_by": str(record.frontmatter.get("approved_by", "")),
            "approved_at": str(record.frontmatter.get("approved_at", "")),
            "sensitivity": str(record.frontmatter.get("sensitivity", "")),
        },
    }


def _report(*, enabled: bool) -> dict[str, Any]:
    return {
        "schema_version": "memory-os.hindsight_export_report.v0",
        "enabled": enabled,
        "exported_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "exported_record_ids": [],
        "skipped": [],
        "errors": [],
    }


def _skip(report: dict[str, Any], record: CrystallizedRecord, reason: str) -> None:
    report["skipped_count"] += 1
    report["skipped"].append({"record_id": _record_id(record), "file_name": record.file_name, "reason": reason})


def _record_id(record: CrystallizedRecord) -> str:
    return str(record.frontmatter.get("id", ""))
