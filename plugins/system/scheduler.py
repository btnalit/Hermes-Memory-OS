"""File-lock schedule coordination for portable modules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class LockResult:
    acquired: bool
    status: str
    resource_id: str
    owner: str
    lock_path: Path
    lock_contention_count: int = 0


class ScheduleCoordinator:
    """Coordinate long-running module jobs with TTL lock files."""

    def __init__(self, lock_root: str | Path) -> None:
        self.lock_root = Path(lock_root)

    def acquire_lock(
        self,
        resource_id: str,
        *,
        owner: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> LockResult:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        path = self._lock_path(resource_id)
        existing = self._read_lock(path)
        if existing:
            expires_at = datetime.fromisoformat(existing["expires_at"]).astimezone(timezone.utc)
            if expires_at > current:
                contention_count = int(existing.get("lock_contention_count", 0)) + 1
                existing["lock_contention_count"] = contention_count
                self._write_lock(path, existing)
                return LockResult(
                    acquired=False,
                    status="held",
                    resource_id=resource_id,
                    owner=owner,
                    lock_path=path,
                    lock_contention_count=contention_count,
                )
            status = "expired_replaced"
        else:
            status = "acquired"

        record = {
            "schema_version": "hermes.schedule_lock.v0",
            "lock_id": f"lock_{uuid4().hex}",
            "resource_id": resource_id,
            "owner": owner,
            "acquired_at": current.isoformat(),
            "expires_at": (current + timedelta(seconds=ttl_seconds)).isoformat(),
            "lock_contention_count": int(existing.get("lock_contention_count", 0)) if existing else 0,
        }
        self._write_lock(path, record)
        return LockResult(
            acquired=True,
            status=status,
            resource_id=resource_id,
            owner=owner,
            lock_path=path,
            lock_contention_count=int(record["lock_contention_count"]),
        )

    def release_lock(self, resource_id: str, *, owner: str) -> bool:
        path = self._lock_path(resource_id)
        existing = self._read_lock(path)
        if not existing or existing.get("owner") != owner:
            return False
        path.unlink()
        return True

    def _lock_path(self, resource_id: str) -> Path:
        safe_name = resource_id.replace("/", "_").replace("\\", "_")
        return self.lock_root / f"{safe_name}.lock.json"

    @staticmethod
    def _read_lock(path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    @staticmethod
    def _write_lock(path: Path, record: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
