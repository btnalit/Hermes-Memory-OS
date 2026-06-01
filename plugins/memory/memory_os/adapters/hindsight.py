"""Disabled-by-default Hindsight export smoke adapter."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from ..audit import append_audit
from ..crystallized import CrystallizedMemoryService, CrystallizedRecord, is_active_crystallized_frontmatter
from ..store import MemoryOSStore, _format_frontmatter


class HindsightClient(Protocol):
    def retain(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HindsightAdapterConfig:
    enabled: bool = False


class HindsightExportRefused(ValueError):
    """Raised when callers try to export non-approved canonical data."""


class HindsightHttpClient:
    """Minimal governed client for Hindsight's HTTP API."""

    def __init__(
        self,
        *,
        api_url: str,
        bank_id: str,
        api_key: str = "",
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_url = str(api_url or "").rstrip("/")
        self.bank_id = str(bank_id or "").strip()
        self.api_key = str(api_key or "").strip()
        self.timeout_seconds = timeout_seconds

    def retain(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata = _string_metadata(payload.get("metadata"))
        record_id = str(payload.get("record_id") or "").strip()
        item = {
            "content": str(payload.get("text") or ""),
            "context": "Memory-OS owner-approved crystallized memory",
            "document_id": record_id or None,
            "tags": _retain_tags(payload),
            "metadata": metadata,
            "timestamp": str(metadata.get("approved_at") or "unset"),
        }
        return self._post(
            f"/v1/default/banks/{_quote_path(self.bank_id)}/memories",
            {"async": False, "items": [item]},
        )

    def recall(self, *, bank_id: str, query: str, budget: str, max_tokens: int) -> dict[str, Any]:
        return self._post(
            f"/v1/default/banks/{_quote_path(bank_id or self.bank_id)}/memories/recall",
            {
                "query": str(query or ""),
                "budget": _budget(budget, default="mid"),
                "max_tokens": max(int(max_tokens or 1200), 1),
                "types": ["world", "experience", "observation"],
            },
        )

    def reflect(self, *, bank_id: str, query: str, budget: str) -> dict[str, Any]:
        return self._post(
            f"/v1/default/banks/{_quote_path(bank_id or self.bank_id)}/reflect",
            {
                "query": str(query or ""),
                "budget": _budget(budget, default="low"),
                "max_tokens": 1200,
                "include": {"facts": {}},
            },
            timeout_seconds=max(self.timeout_seconds, 120.0),
        )

    def invalidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "invalidated_by_memory_os_projection",
            "actual_delete": False,
            "payload": {
                "source_record_ref": str(payload.get("source_record_ref") or ""),
                "source_version": str(payload.get("source_version") or ""),
                "delete_policy": "invalidate_not_delete",
            },
        }

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not self.api_url:
            raise RuntimeError("hindsight api_url not configured")
        if not self.bank_id:
            raise RuntimeError("hindsight bank_id not configured")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.api_url + path,
            data=data,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds or self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"hindsight HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, OSError) as exc:
            raise RuntimeError(f"hindsight request failed: {exc}") from exc
        if not body.strip():
            return {}
        loaded = json.loads(body)
        if not isinstance(loaded, dict):
            return {"value": loaded}
        return loaded

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class HindsightAdapter:
    """Export only safe, owner-approved crystallized records to Hindsight.

    Callers inject either a fake client for tests or HindsightHttpClient for
    governed live projection writes.
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
            if not is_active_crystallized_frontmatter(record.frontmatter):
                _skip(report, record, "canonical_inactive")
                continue
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
                retain_result = self.client.retain(payload)
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
            substrate_record_id = _substrate_record_id(retain_result, fallback=_record_id(record))
            report["exported_count"] += 1
            report["exported_record_ids"].append(_record_id(record))
            report["exported_records"].append(
                {
                    "source_record_ref": _record_id(record),
                    "source_version": "current",
                    "source_class": "crystallized",
                    "substrate_record_id": substrate_record_id,
                    "substrate_snapshot_id": _substrate_snapshot_id(substrate_record_id),
                }
            )
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
    if not is_active_crystallized_frontmatter(record.frontmatter):
        raise HindsightExportRefused("record is not active canonical memory")
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
            "source_class": "crystallized",
            "candidate_id": str(record.frontmatter.get("candidate_id", "")),
            "approved_by": str(record.frontmatter.get("approved_by", "")),
            "approved_at": str(record.frontmatter.get("approved_at", "")),
            "sensitivity": str(record.frontmatter.get("sensitivity", "")),
            "source_record_ref": _record_id(record),
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
        "exported_records": [],
        "skipped": [],
        "errors": [],
    }


def _skip(report: dict[str, Any], record: CrystallizedRecord, reason: str) -> None:
    report["skipped_count"] += 1
    report["skipped"].append({"record_id": _record_id(record), "file_name": record.file_name, "reason": reason})


def _record_id(record: CrystallizedRecord) -> str:
    return str(record.frontmatter.get("id", ""))


def _substrate_record_id(retain_result: Any, *, fallback: str) -> str:
    if isinstance(retain_result, dict):
        return str(retain_result.get("id") or retain_result.get("record_id") or fallback)
    return fallback


def _substrate_snapshot_id(substrate_record_id: str) -> str:
    return f"hindsight:{substrate_record_id}:vcurrent"


def _string_metadata(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    metadata: dict[str, str] = {}
    for key, item in value.items():
        clean_key = str(key or "").strip()
        if not clean_key:
            continue
        metadata[clean_key] = str(item or "")
    return metadata


def _retain_tags(payload: dict[str, Any]) -> list[str]:
    tags = ["memory-os", "crystallized"]
    for tag in payload.get("tags") or []:
        clean = str(tag or "").strip()
        if clean and clean not in tags:
            tags.append(clean)
    return tags


def _quote_path(value: str) -> str:
    return urllib.parse.quote(str(value or ""), safe="")


def _budget(value: str, *, default: str) -> str:
    clean = str(value or "").strip()
    return clean if clean in {"low", "mid", "high"} else default
