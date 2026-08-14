"""Standard per-lane last-run evidence ("Completion Is Not Output").

An ExecutionGate envelope records that a lane *ran*, never that it
*produced* anything — a lane with nothing to do and a broken lane both
close a clean envelope.  Every lane that can legitimately produce nothing
must therefore leave a durable per-run record of WHY, using a closed
per-lane reason set, so a reader can separate "no eligible input" from
"input existed but processing failed" without re-running anything or
reading source.

This module is the standard writer for that record:
``<hermes_home>/memory-os/system/lane_last_run/<lane_id>.json``.

Semantics:
* ``status`` describes the lane RUN itself: ``ok`` (ran to its decision
  point), ``skipped`` (declined to run: disabled / not eligible), or
  ``error`` (the run failed).
* ``reason`` is the lane's closed-set outcome code (e.g. ``produced``,
  ``no_new_records``, ``sessions_dir_absent``, ``llm_empty_content``).
* ``counters`` are small bounded ints (inputs scanned / eligible /
  produced, failures by reason).

Lanes that already carry richer artifacts (exposure_rollup's snapshot
``last_run`` block, session_mirror's auto-apply file, v3_wandering's runs
ledger) keep them; this file is the uniform surface new wiring targets and
the Loop Health projection reads first.

Writes are single-file atomic replaces (state file, not a ledger), matching
the ``session_mirror_auto_apply_last_run.json`` precedent, and fail-open:
evidence about a lane must never break the lane.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LANE_LAST_RUN_SCHEMA_VERSION = "memory-os.lane_last_run.v0"

_ALLOWED_STATUSES = ("ok", "skipped", "error")
_MAX_ERROR_CHARS = 300
_MAX_COUNTERS = 24


def lane_last_run_path(hermes_home: str | Path, lane_id: str) -> Path:
    return Path(hermes_home) / "memory-os" / "system" / "lane_last_run" / f"{lane_id}.json"


def record_lane_last_run(
    hermes_home: str | Path,
    lane_id: str,
    *,
    status: str,
    reason: str,
    counters: dict[str, int] | None = None,
    error: str = "",
) -> bool:
    """Atomically write the lane's last-run record. Fail-open, returns success."""
    try:
        if status not in _ALLOWED_STATUSES:
            status = "error"
        record: dict[str, Any] = {
            "schema_version": LANE_LAST_RUN_SCHEMA_VERSION,
            "lane_id": str(lane_id),
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": status,
            "reason": str(reason)[:120],
        }
        if counters:
            bounded: dict[str, int] = {}
            for index, (key, value) in enumerate(sorted(counters.items())):
                if index >= _MAX_COUNTERS:
                    break
                try:
                    bounded[str(key)[:64]] = int(value)
                except (TypeError, ValueError):
                    continue
            record["counters"] = bounded
        if error:
            record["error"] = str(error)[:_MAX_ERROR_CHARS]
        path = lane_last_run_path(hermes_home, lane_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{lane_id}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, sort_keys=True)
            os.replace(tmp_name, path)
        except BaseException:
            with_suppressed_unlink(tmp_name)
            raise
        return True
    except Exception as exc:  # noqa: BLE001 - evidence must never break the lane
        try:
            sys.stderr.write(f"lane_last_run: write failed for {lane_id}: {exc}\n")
        except Exception:  # noqa: BLE001
            pass
        return False


def with_suppressed_unlink(tmp_name: str) -> None:
    try:
        os.unlink(tmp_name)
    except OSError:
        pass


def read_lane_last_run(hermes_home: str | Path, lane_id: str) -> dict[str, Any] | None:
    """Read the lane's last-run record; None when absent or malformed."""
    path = lane_last_run_path(hermes_home, lane_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
