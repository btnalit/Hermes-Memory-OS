"""Helper-side ExecutionGate completion report writer."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


HELPER_EXECUTION_REPORT_SCHEMA_VERSION = "memory-os.helper_execution_report.v0"
SAFE_HELPER_BOUNDARY = {
    "actual_send": False,
    "actual_execute": False,
    "actual_identity_write": False,
    "actual_unapproved_crystallized_approval": False,
}


def write_helper_execution_report(
    *,
    boundary: dict[str, Any] | None = None,
    result_summary: dict[str, Any] | None = None,
    status: str = "ok",
) -> None:
    path = os.environ.get("MEMORY_OS_EXECUTION_REPORT_PATH", "").strip()
    if not path:
        return
    report = {
        "schema_version": HELPER_EXECUTION_REPORT_SCHEMA_VERSION,
        "status": str(status or "ok"),
        "boundary": {**SAFE_HELPER_BOUNDARY, **(boundary or {})},
        "result_summary": result_summary or {},
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8")
