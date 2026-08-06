"""Read-only CronMirror scanner for Memory-OS source coverage."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit
from .ids import new_event_id
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
from .store import MemoryOSStore


class CronMirror:
    """Mirror Hermes cron output metadata into summary-only Memory-OS events."""

    state_schema_version = "memory-os.cron_mirror_state.v0"
    report_schema_version = "memory-os.cron_mirror_report.v0"

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    @property
    def cron_root(self) -> Path:
        return self.store.roots.hermes_home / "cron"

    @property
    def output_root(self) -> Path:
        return self.cron_root / "output"

    @property
    def jobs_path(self) -> Path:
        return self.cron_root / "jobs.json"

    @property
    def state_path(self) -> Path:
        return self.store.roots.memory_os_root / "runtime" / "cron_mirror_state.json"

    def status(self) -> dict[str, Any]:
        state, rebuilt, findings = self._load_state(persist_repair=False)
        outputs = self._discover_outputs()
        pending = [item for item in outputs if item["dedup_key"] not in state["seen_outputs"]]
        return {
            "schema_version": "memory-os.cron_mirror_status.v0",
            "status": "ok" if not findings else "warning",
            "profile": self.store.roots.profile,
            "job_count": len(self._load_jobs()),
            "output_file_count": len(outputs),
            "pending_output_count": len(pending),
            "state_path": str(self.state_path),
            "state_rebuilt": rebuilt,
            "findings": findings,
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if self.cron_root.exists() and not self.cron_root.is_dir():
            findings.append(_finding("cron_root_not_directory", "error", "cron root exists but is not a directory"))
        if self.output_root.exists() and not self.output_root.is_dir():
            findings.append(_finding("cron_output_not_directory", "error", "cron output root exists but is not a directory"))
        if self.jobs_path.exists():
            try:
                self._load_jobs()
            except Exception as exc:
                findings.append(_finding("cron_jobs_unreadable", "error", "cron jobs.json cannot be parsed", {"error": str(exc)}))
        status = "error" if any(item["severity"] == "error" for item in findings) else "ok"
        return {
            "schema_version": "memory-os.cron_mirror_doctor.v0",
            "status": status,
            "profile": self.store.roots.profile,
            "findings": findings,
        }

    def scan(self, *, dry_run: bool = True) -> dict[str, Any]:
        self.store.initialize()
        state, state_rebuilt, findings = self._load_state(persist_repair=not dry_run)
        outputs = self._discover_outputs()
        new_outputs = [item for item in outputs if item["dedup_key"] not in state["seen_outputs"]]
        written_events: list[str] = []
        if not dry_run:
            for item in new_outputs:
                event = self._event_for_output(item)
                self.store.append_event(event)
                state["seen_outputs"][item["dedup_key"]] = {
                    "event_id": event.id,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                }
                written_events.append(event.id)
            state["last_scan_at"] = datetime.now(timezone.utc).isoformat()
            self._write_state(state)
            append_audit(
                self.store.roots.audit_path,
                action="cron_mirror_scan",
                status="ok",
                target=str(self.output_root),
                details={
                    "dry_run": False,
                    "new_event_count": len(written_events),
                    "state_rebuilt": state_rebuilt,
                },
            )
        return {
            "schema_version": self.report_schema_version,
            "status": "ok" if not findings else "warning",
            "profile": self.store.roots.profile,
            "job_count": len(self._load_jobs()),
            "output_file_count": len(outputs),
            "new_event_count": len(new_outputs),
            "dry_run": dry_run,
            "state_rebuilt": state_rebuilt,
            "written_event_ids": written_events,
            "findings": findings,
        }

    def _load_jobs(self) -> dict[str, dict[str, Any]]:
        if not self.jobs_path.exists():
            return {}
        data = json.loads(self.jobs_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            jobs = data
        elif isinstance(data, dict):
            jobs = data.get("jobs", [])
        else:
            jobs = []
        result: dict[str, dict[str, Any]] = {}
        for item in jobs:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("id") or item.get("job_id") or item.get("name") or "")
            if job_id:
                result[job_id] = dict(item)
        return result

    def _discover_outputs(self) -> list[dict[str, Any]]:
        if not self.output_root.exists():
            return []
        jobs = self._load_jobs()
        outputs: list[dict[str, Any]] = []
        for path in sorted(self.output_root.glob("*/*")):
            if not path.is_file():
                continue
            job_id = path.parent.name
            output_hash = _sha256_file(path)
            job = jobs.get(job_id, {})
            mode = str(job.get("mode") or job.get("type") or "unknown")
            outputs.append(
                {
                    "job_id": job_id,
                    "job_name": str(job.get("name") or job_id),
                    "mode": mode,
                    "path": path,
                    "output_filename": path.name,
                    "output_sha256": output_hash,
                    "output_size": path.stat().st_size,
                    "status": _infer_status(path),
                    "dedup_key": f"cron_output::{job_id}::{path.name}::{output_hash}",
                }
            )
        return outputs

    def _load_state(self, *, persist_repair: bool) -> tuple[dict[str, Any], bool, list[dict[str, Any]]]:
        if not self.state_path.exists():
            return self._rebuild_state(), False, []
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("seen_outputs", {}), dict):
                raise ValueError("state shape is invalid")
            data.setdefault("schema_version", self.state_schema_version)
            data.setdefault("last_scan_at", "")
            data.setdefault("seen_outputs", {})
            return data, False, []
        except Exception as exc:
            state = self._rebuild_state()
            if persist_repair:
                self._write_state(state)
            return state, True, [
                _finding(
                    "cron_mirror_state_rebuilt",
                    "warning",
                    "CronMirror state was corrupt and rebuilt from Memory-OS events.",
                    {"error": str(exc)},
                )
            ]

    def _rebuild_state(self) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for record in self._read_existing_cron_event_records():
            if record.get("kind") != "cron_job_run":
                continue
            safe_ref = record.get("safe_ref", {})
            if not isinstance(safe_ref, dict):
                continue
            dedup_key = str(safe_ref.get("dedup_key", ""))
            if dedup_key:
                seen[dedup_key] = {
                    "event_id": str(record.get("id", "")),
                    "indexed_at": str(record.get("ts", "")),
                }
        return {
            "schema_version": self.state_schema_version,
            "seen_outputs": seen,
            "last_scan_at": "",
        }

    def _read_existing_cron_event_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.store.roots.events_root.glob("*/*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)
        return records

    def _write_state(self, state: dict[str, Any]) -> None:
        from .jsonl_io import write_json_atomic

        write_json_atomic(self.state_path, state)

    def _event_for_output(self, item: dict[str, Any]) -> EventEnvelope:
        now = datetime.now(timezone.utc)
        summary = (
            f"Cron job {item['job_id']} wrote output; "
            f"mode={item['mode']}; status={item['status']}."
        )
        unique = hashlib.sha256(str(item["dedup_key"]).encode("utf-8")).hexdigest()[:10]
        return EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id=new_event_id(now, unique=unique),
            ts=now.isoformat(),
            profile=self.store.roots.profile or "default",
            source="cron",
            kind="cron_job_run",
            summary=summary,
            safe_ref={
                "source_module": "cron_mirror",
                "job_id": item["job_id"],
                "job_name": item["job_name"],
                "mode": item["mode"],
                "status": item["status"],
                "source_path": str(Path(item["path"]).resolve()),
                "output_filename": item["output_filename"],
                "output_sha256": item["output_sha256"],
                "output_size": item["output_size"],
                "dedup_key": item["dedup_key"],
                "drive_policy": "index_only",
                "candidate_allowed": False,
                "body_policy": "summary_only",
            },
            tags=["cron", "mirror", item["status"], item["mode"]],
            sensitivity="private",
            body_policy="summary_only",
            hashes={"output_sha256": item["output_sha256"]},
            promotion_state="raw",
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _infer_status(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "unknown"
    lowered = text.lower()
    if "[silent]" in lowered:
        return "silent"
    if "error" in lowered or "failed" in lowered or "exception" in lowered:
        return "error"
    if text.strip():
        return "ok"
    return "empty"


def _finding(id_: str, severity: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": id_, "code": id_, "severity": severity, "message": message, "details": details or {}}
