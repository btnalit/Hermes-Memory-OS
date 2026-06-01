"""Owner-approved crystallized-memory service."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .approval import ApprovalDecision, ApprovalPurpose
from .audit import append_audit
from .ids import new_crystallized_id
from .schema import CRYSTALLIZED_SCHEMA_VERSION
from .store import MemoryOSStore, _format_frontmatter


INACTIVE_CANONICAL_STATES = {"owner_revoked", "revoked", "demoted"}


class CrystallizedApprovalError(ValueError):
    """Raised when a candidate lacks crystallized-memory approval."""


@dataclass(frozen=True)
class CrystallizedCandidate:
    candidate_id: str
    kind: str
    body: str
    source_event_ids: list[str]
    sensitivity: str = "private"
    tags: list[str] | None = None
    bridge_state: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class CrystallizedRecord:
    file_name: str
    frontmatter: dict[str, Any]
    body: str


class CrystallizedMemoryService:
    """Write and read owner-approved long-term memory records."""

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    def write_approved_record(
        self,
        candidate: CrystallizedCandidate,
        decision: ApprovalDecision,
        *,
        file_name: str,
        now: datetime | None = None,
    ) -> Path:
        self._ensure_crystallized_approval(candidate, decision)
        created_at = _timestamp(now)
        frontmatter = {
            "schema_version": CRYSTALLIZED_SCHEMA_VERSION,
            "id": new_crystallized_id(_datetime(now)),
            "candidate_id": candidate.candidate_id,
            "kind": candidate.kind,
            "created_at": created_at,
            "approved_by": decision.reviewer,
            "approved_at": decision.reviewed_at,
            "approval_purpose": decision.purpose.value,
            "approval_note": decision.note,
            "source_event_ids": list(candidate.source_event_ids),
            "tags": list(candidate.tags or []),
            "sensitivity": candidate.sensitivity,
            "hindsight_indexed": False,
            "bridge_state": candidate.bridge_state or decision.source_state,
        }
        path = self.store.append_crystallized_record(file_name, frontmatter, candidate.body)
        append_audit(
            self.store.roots.audit_path,
            action="crystallized_record_written",
            status="ok",
            target=str(path),
            details={
                "record_id": frontmatter["id"],
                "candidate_id": candidate.candidate_id,
                "approval_purpose": decision.purpose.value,
                "source_event_ids": list(candidate.source_event_ids),
            },
        )
        return path

    def read_records(self, file_name: str) -> list[CrystallizedRecord]:
        path = self.store.roots.crystallized_root / file_name
        if not path.exists():
            return []
        return [
            CrystallizedRecord(file_name=file_name, frontmatter=frontmatter, body=body)
            for frontmatter, body in _parse_markdown_records(path.read_text(encoding="utf-8"))
        ]

    def find_record(self, record_id: str) -> CrystallizedRecord | None:
        normalized = str(record_id or "").strip()
        if not normalized or not self.store.roots.crystallized_root.exists():
            return None
        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            for record in self.read_records(path.name):
                if str(record.frontmatter.get("id") or "") == normalized:
                    return record
        return None

    def revoke_record(
        self,
        record_id: str,
        *,
        revoked_by: str,
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = str(record_id or "").strip()
        if not normalized:
            raise KeyError("crystallized record id is required")
        if not self.store.roots.crystallized_root.exists():
            raise KeyError(normalized)

        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records = self.read_records(path.name)
            rendered: list[str] = []
            changed = False
            matched: dict[str, Any] | None = None
            for current in records:
                frontmatter = dict(current.frontmatter)
                if str(frontmatter.get("id") or "") == normalized:
                    matched = {
                        "record_id": normalized,
                        "file_name": current.file_name,
                        "already_revoked": not is_active_crystallized_frontmatter(frontmatter),
                    }
                    if is_active_crystallized_frontmatter(frontmatter):
                        frontmatter["canonical_state"] = "owner_revoked"
                        frontmatter["revoked_by"] = revoked_by
                        frontmatter["revoked_at"] = _timestamp(now)
                        frontmatter["revocation_reason"] = reason
                        changed = True
                rendered.append(_format_frontmatter(frontmatter))
                rendered.append("")
                rendered.append(current.body.rstrip())
                rendered.append("")
            if matched is None:
                continue
            if changed:
                tmp_path = path.with_name(f"{path.name}.{normalized}.revoke.tmp")
                try:
                    tmp_path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
                    tmp_path.replace(path)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
                append_audit(
                    self.store.roots.audit_path,
                    action="crystallized_record_revoked",
                    status="ok",
                    target=str(path),
                    details={
                        "record_id": normalized,
                        "revoked_by": revoked_by,
                    },
                )
            matched["canonical_state_changed"] = changed
            return matched
        raise KeyError(normalized)

    def demote_record(
        self,
        record_id: str,
        *,
        demoted_by: str,
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = str(record_id or "").strip()
        if not normalized:
            raise KeyError("crystallized record id is required")
        if not self.store.roots.crystallized_root.exists():
            raise KeyError(normalized)

        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records = self.read_records(path.name)
            rendered: list[str] = []
            changed = False
            matched: dict[str, Any] | None = None
            for current in records:
                frontmatter = dict(current.frontmatter)
                if str(frontmatter.get("id") or "") == normalized:
                    matched = {
                        "record_id": normalized,
                        "file_name": current.file_name,
                        "already_demoted": not is_active_crystallized_frontmatter(frontmatter),
                    }
                    if is_active_crystallized_frontmatter(frontmatter):
                        frontmatter["canonical_state"] = "demoted"
                        frontmatter["demoted_by"] = demoted_by
                        frontmatter["demoted_at"] = _timestamp(now)
                        frontmatter["demotion_reason"] = reason
                        changed = True
                rendered.append(_format_frontmatter(frontmatter))
                rendered.append("")
                rendered.append(current.body.rstrip())
                rendered.append("")
            if matched is None:
                continue
            if changed:
                tmp_path = path.with_name(f"{path.name}.{normalized}.demote.tmp")
                try:
                    tmp_path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
                    tmp_path.replace(path)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
                append_audit(
                    self.store.roots.audit_path,
                    action="crystallized_record_demoted",
                    status="ok",
                    target=str(path),
                    details={
                        "record_id": normalized,
                        "demoted_by": demoted_by,
                    },
                )
            matched["canonical_state_changed"] = changed
            return matched
        raise KeyError(normalized)

    def _ensure_crystallized_approval(
        self,
        candidate: CrystallizedCandidate,
        decision: ApprovalDecision,
    ) -> None:
        if decision.candidate_id != candidate.candidate_id:
            raise CrystallizedApprovalError("approval candidate_id does not match candidate")
        if decision.purpose is not ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED:
            bridge = candidate.bridge_state or decision.source_state
            suffix = f"; bridge_state={bridge}" if bridge else ""
            raise CrystallizedApprovalError(
                f"Crystallized writes require approve_for_crystallized, got {decision.purpose.value}{suffix}"
            )
        if not candidate.source_event_ids:
            raise CrystallizedApprovalError("crystallized records require source_event_ids")


def append_candidate_queue(store: MemoryOSStore, candidate: CrystallizedCandidate) -> Path:
    path = store.roots.crystallized_root / "candidates.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(candidate)
    data["tags"] = list(candidate.tags or [])
    data["created_at"] = str(data.get("created_at") or _timestamp(None))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    append_audit(
        store.roots.audit_path,
        action="crystallized_candidate_queued",
        status="ok",
        target=str(path),
        details={
            "candidate_id": candidate.candidate_id,
            "source_event_ids": list(candidate.source_event_ids),
        },
    )
    return path


def read_candidate_queue(roots_or_store: Any) -> list[CrystallizedCandidate]:
    roots = getattr(roots_or_store, "roots", roots_or_store)
    path = roots.crystallized_root / "candidates.jsonl"
    if not path.exists():
        return []
    candidates: list[CrystallizedCandidate] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        candidates.append(
            CrystallizedCandidate(
                candidate_id=str(raw["candidate_id"]),
                kind=str(raw["kind"]),
                body=str(raw["body"]),
                source_event_ids=[str(item) for item in raw.get("source_event_ids", [])],
                sensitivity=str(raw.get("sensitivity", "private")),
                tags=[str(item) for item in (raw.get("tags") or [])],
                bridge_state=str(raw.get("bridge_state", "")),
                created_at=str(raw.get("created_at") or ""),
            )
        )
    return candidates


def is_active_crystallized_frontmatter(frontmatter: dict[str, Any]) -> bool:
    state = str(frontmatter.get("canonical_state") or "active").strip().lower()
    return state not in INACTIVE_CANONICAL_STATES


def _parse_markdown_records(content: str) -> list[tuple[dict[str, Any], str]]:
    lines = content.splitlines()
    records: list[tuple[dict[str, Any], str]] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != "---":
            index += 1
            continue
        index += 1
        frontmatter_lines: list[str] = []
        while index < len(lines) and lines[index].strip() != "---":
            frontmatter_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            break
        index += 1
        body_lines: list[str] = []
        while index < len(lines) and lines[index].strip() != "---":
            body_lines.append(lines[index])
            index += 1
        body = "\n".join(body_lines).strip()
        records.append((_parse_frontmatter(frontmatter_lines), body))
    return records


def _parse_frontmatter(lines: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    current_list_key = ""
    for line in lines:
        if line.startswith("  - ") and current_list_key:
            parsed[current_list_key].append(line[4:])
            continue
        current_list_key = ""
        if line.endswith(":"):
            key = line[:-1]
            parsed[key] = []
            current_list_key = key
            continue
        key, _, raw_value = line.partition(": ")
        if not key:
            continue
        parsed[key] = _parse_scalar(raw_value)
    return parsed


def _parse_scalar(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _datetime(value: datetime | None) -> datetime:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _timestamp(value: datetime | None) -> str:
    return _datetime(value).isoformat()
