"""Report retention planning for Memory-OS metadata artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_report_retention_plan(
    reports_root: str | Path,
    *,
    keep_latest: int = 20,
    retention_days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(reports_root)
    if not root.exists():
        return {
            "schema_version": "memory-os.report_retention_plan.v0",
            "reports_root": str(root),
            "keep_latest": max(int(keep_latest), 0),
            "retention_days": max(int(retention_days), 0),
            "candidate_count": 0,
            "would_archive_or_prune": [],
            "canonical_paths_touched": [],
        }
    current = now or datetime.now(timezone.utc)
    candidates = [path for path in root.iterdir() if path.is_dir()]
    candidates.sort(key=lambda path: (path.name, path.stat().st_mtime), reverse=True)
    keep_count = max(int(keep_latest), 0)
    retention_seconds = max(int(retention_days), 0) * 86400
    would_archive_or_prune: list[dict[str, Any]] = []
    for index, path in enumerate(candidates):
        age_seconds = max(0, int(current.timestamp() - path.stat().st_mtime))
        if index < keep_count:
            continue
        if retention_days == 0 or age_seconds > retention_seconds:
            would_archive_or_prune.append(
                {
                    "path": str(path),
                    "age_seconds": age_seconds,
                    "reason_codes": ["outside_keep_latest", "older_than_retention" if retention_days else "retention_zero"],
                }
            )
    return {
        "schema_version": "memory-os.report_retention_plan.v0",
        "reports_root": str(root),
        "keep_latest": keep_count,
        "retention_days": max(int(retention_days), 0),
        "candidate_count": len(candidates),
        "would_archive_or_prune": would_archive_or_prune,
        "canonical_paths_touched": [],
    }
