"""Shadow journal ingestion for high-frequency non-agent producers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit import append_audit
from .ids import new_event_id
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
from .store import MemoryOSStore


SHADOW_RECORD_SCHEMA_VERSION = "memory-os.shadow_journal_record.v0"
SHADOW_INGEST_SCHEMA_VERSION = "memory-os.shadow_journal_ingest.v0"
SHADOW_STATUS_SCHEMA_VERSION = "memory-os.shadow_journal_status.v0"
SHADOW_DOCTOR_SCHEMA_VERSION = "memory-os.shadow_journal_doctor.v0"


LOW_VALUE_SOURCE_CLASSES = {"telemetry", "status", "metrics", "runtime", "runtime_status"}


@dataclass(frozen=True)
class ShadowSpoolRecord:
    producer: str
    path: Path
    line_number: int
    data: dict[str, Any]
    dedup_key: str


class ShadowJournalIngestion:
    """Accept shadow journal records into canonical Memory-OS events.

    Producers write JSONL into per-producer spool files. Those records are not
    memory until this arbiter validates, deduplicates, and appends them to the
    canonical event stream.
    """

    state_schema_version = "memory-os.shadow_journal_state.v0"

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    @property
    def shadow_root(self) -> Path:
        return self.store.roots.memory_os_root / "shadow-journal"

    @property
    def state_path(self) -> Path:
        return self.store.roots.memory_os_root / "runtime" / "shadow_journal_state.json"

    @property
    def lock_path(self) -> Path:
        return self.store.roots.memory_os_root / "runtime" / "locks" / "shadow_journal_ingest.lock.json"

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        scan = self._scan_spool(state=state)
        return {
            "schema_version": SHADOW_STATUS_SCHEMA_VERSION,
            "status": "ok",
            "profile": self.store.roots.profile,
            "shadow_root": str(self.shadow_root),
            "producer_count": len(scan["producers"]),
            "spool_file_count": scan["spool_file_count"],
            "pending_record_count": len(scan["pending"]),
            "seen_record_count": len(state["seen_records"]),
            "malformed_record_count": len(scan["malformed"]),
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if self.shadow_root.exists() and not self.shadow_root.is_dir():
            findings.append(_finding("shadow_root_not_directory", "error", "shadow root exists but is not a directory"))
        if self.state_path.exists():
            try:
                self._load_state()
            except Exception as exc:
                findings.append(_finding("shadow_state_unreadable", "error", "shadow journal state cannot be parsed", {"error": str(exc)}))
        status = "error" if any(item["severity"] == "error" for item in findings) else "ok"
        return {
            "schema_version": SHADOW_DOCTOR_SCHEMA_VERSION,
            "status": status,
            "profile": self.store.roots.profile,
            "findings": findings,
        }

    def ingest(self, *, dry_run: bool = True, max_records: int = 100) -> dict[str, Any]:
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        self.store.initialize()
        state = self._load_state()
        scan = self._scan_spool(state=state)
        pending = scan["pending"][:max_records]
        malformed = scan["malformed"][:max_records]
        written_event_ids: list[str] = []
        lock_status = "not_required"
        if not dry_run:
            lock_status = self._acquire_lock()
            if lock_status == "held":
                return self._report(
                    dry_run=dry_run,
                    scan=scan,
                    pending=pending,
                    malformed=[],
                    written_event_ids=[],
                    lock_status=lock_status,
                )
            for record in pending:
                event = self._event_for_record(record)
                self.store.append_event(event)
                state["seen_records"][record.dedup_key] = {
                    "event_id": event.id,
                    "producer": record.producer,
                    "accepted_at": datetime.now(timezone.utc).isoformat(),
                }
                written_event_ids.append(event.id)
            for item in malformed:
                self._quarantine_malformed(item)
            state["last_ingest_at"] = datetime.now(timezone.utc).isoformat()
            self._write_state(state)
            self._release_lock()
            append_audit(
                self.store.roots.audit_path,
                action="shadow_journal_ingest",
                status="ok",
                target=str(self.shadow_root),
                details={
                    "dry_run": False,
                    "written_event_count": len(written_event_ids),
                    "malformed_record_count": len(malformed),
                },
            )
        return self._report(
            dry_run=dry_run,
            scan=scan,
            pending=pending,
            malformed=malformed,
            written_event_ids=written_event_ids,
            lock_status=lock_status,
        )

    def _report(
        self,
        *,
        dry_run: bool,
        scan: dict[str, Any],
        pending: list[ShadowSpoolRecord],
        malformed: list[dict[str, Any]],
        written_event_ids: list[str],
        lock_status: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": SHADOW_INGEST_SCHEMA_VERSION,
            "status": "ok" if lock_status != "held" else "warning",
            "profile": self.store.roots.profile,
            "dry_run": dry_run,
            "shadow_root": str(self.shadow_root),
            "producer_count": len(scan["producers"]),
            "spool_file_count": scan["spool_file_count"],
            "pending_record_count": len(scan["pending"]),
            "selected_record_count": len(pending),
            "would_write_event_count": len(pending),
            "written_event_count": len(written_event_ids),
            "written_event_ids": written_event_ids,
            "malformed_record_count": len(malformed),
            "lock_status": lock_status,
        }

    def _scan_spool(self, *, state: dict[str, Any]) -> dict[str, Any]:
        producers: set[str] = set()
        pending: list[ShadowSpoolRecord] = []
        malformed: list[dict[str, Any]] = []
        spool_files = list(self._spool_files())
        seen = set(state.get("seen_records", {}))
        for path in spool_files:
            producer = path.parent.name
            producers.add(producer)
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    record = self._parse_record(path, line_number, line, producer)
                except Exception as exc:
                    malformed.append(
                        {
                            "producer": producer,
                            "path": str(path),
                            "line_number": line_number,
                            "line": line,
                            "error": str(exc),
                        }
                    )
                    continue
                if record.dedup_key in seen:
                    continue
                pending.append(record)
        return {
            "producers": sorted(producers),
            "spool_file_count": len(spool_files),
            "pending": pending,
            "malformed": malformed,
        }

    def _spool_files(self) -> list[Path]:
        if not self.shadow_root.exists():
            return []
        return sorted(path for path in self.shadow_root.glob("*/*.jsonl") if path.is_file())

    def _parse_record(self, path: Path, line_number: int, line: str, producer: str) -> ShadowSpoolRecord:
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError("spool record must be an object")
        if data.get("schema_version") != SHADOW_RECORD_SCHEMA_VERSION:
            raise ValueError("unsupported shadow journal record schema")
        record_producer = str(data.get("producer") or producer)
        summary = str(data.get("summary", "")).strip()
        kind = str(data.get("kind", "")).strip()
        ts = str(data.get("ts", "")).strip()
        if not record_producer or not summary or not kind or not ts:
            raise ValueError("shadow record requires producer, ts, kind, and summary")
        datetime.fromisoformat(ts)
        return ShadowSpoolRecord(
            producer=record_producer,
            path=path,
            line_number=line_number,
            data=data,
            dedup_key=_dedup_key(data, producer=record_producer),
        )

    def _event_for_record(self, record: ShadowSpoolRecord) -> EventEnvelope:
        data = record.data
        source_class = str(data.get("source_class") or "runtime").lower()
        ts = datetime.fromisoformat(str(data["ts"])).astimezone(timezone.utc).isoformat()
        safe_ref = {
            "source_module": "shadow_journal",
            "source_class": source_class,
            "producer": record.producer,
            "record_id": str(data.get("record_id", "")),
            "dedup_key": record.dedup_key,
            "drive_policy": str(data.get("drive_policy") or "index_only"),
            "candidate_allowed": bool(data.get("candidate_allowed", False)),
            "body_policy": "summary_only",
        }
        if source_class in LOW_VALUE_SOURCE_CLASSES:
            safe_ref["retention_class"] = "low_value"
        if str(data.get("kind", "")).lower() in {"action_failure", "tool_failure"}:
            safe_ref["action_outcome"] = "failure"
        return EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id=new_event_id(datetime.fromisoformat(ts), unique=uuid4().hex[:8]),
            ts=ts,
            profile=self.store.roots.profile,
            source=f"shadow_journal:{record.producer}",
            kind=str(data["kind"]),
            summary=str(data["summary"])[:500],
            safe_ref=safe_ref,
            tags=["shadow-journal", source_class, str(data["kind"])],
            sensitivity="private",
            body_policy="summary_only",
            hashes={"shadow_record_sha256": _record_hash(data)},
            promotion_state="raw",
        )

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"schema_version": self.state_schema_version, "last_ingest_at": "", "seen_records": {}}
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("seen_records", {}), dict):
            raise ValueError("shadow journal state shape is invalid")
        data.setdefault("schema_version", self.state_schema_version)
        data.setdefault("last_ingest_at", "")
        data.setdefault("seen_records", {})
        return data

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_name(f"{self.state_path.name}.{uuid4().hex}.tmp")
        try:
            tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            tmp_path.replace(self.state_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _quarantine_malformed(self, item: dict[str, Any]) -> None:
        quarantine_path = self.store.roots.quarantine_root / "shadow_journal_malformed.jsonl"
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with quarantine_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        append_audit(
            self.store.roots.audit_path,
            action="shadow_journal_quarantine_malformed",
            status="warning",
            target=str(item.get("path", "")),
            details={"line_number": item.get("line_number"), "producer": item.get("producer", "")},
        )

    def _acquire_lock(self) -> str:
        now = datetime.now(timezone.utc)
        existing = _read_json(self.lock_path)
        if existing:
            try:
                expires_at = datetime.fromisoformat(str(existing["expires_at"])).astimezone(timezone.utc)
            except Exception:
                expires_at = now - timedelta(seconds=1)
            if expires_at > now:
                return "held"
        record = {
            "schema_version": "hermes.schedule_lock.v0",
            "resource_id": "memory_os.shadow_journal.ingest",
            "owner": "shadow_journal",
            "acquired_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=300)).isoformat(),
        }
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return "acquired"

    def _release_lock(self) -> None:
        if self.lock_path.exists():
            self.lock_path.unlink()


def _dedup_key(data: dict[str, Any], *, producer: str) -> str:
    record_id = str(data.get("record_id", "")).strip()
    if record_id:
        return f"shadow_journal::{producer}::{record_id}"
    return f"shadow_journal::{producer}::{_record_hash(data)}"


def _record_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _finding(code: str, severity: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "details": details or {}}
