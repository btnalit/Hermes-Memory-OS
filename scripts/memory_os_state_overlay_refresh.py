#!/usr/bin/env python3
"""Memory-OS State Overlay refresh helper (no_agent).

Reads last session anchors, task anchors, event stats, and crystallized
preferences to build a state overlay projection.  Writes to
``system/state_overlay/current.json`` and ``current.md``.

Fail-open: any exception is recorded as an error run and the script
exits 0 so cron scheduling is not disrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Location-agnostic import resolution (same pattern as index_sync.py).
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]  # scripts/ → repo root


def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    """Extract a --flag value from raw argv before argparse runs."""
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            val = argv[i + 1]
            if val.startswith("--"):
                return ""  # next token is another flag, not a value
            return val
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


# Resolve HERMES_HOME at module level — CLI > env > default.
_CLI_HOME = _preparse_cli_arg(sys.argv, "--hermes-home")
_ENV_HOME = os.environ.get("HERMES_HOME", "")
_HERMES_HOME = _CLI_HOME or _ENV_HOME or str(Path.home() / ".hermes")

if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.roots import MemoryOSRoots, resolve_profile_name
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.state_overlay import (
    build_state_overlay,
    write_state_overlay,
    append_overlay_run,
)
from plugins.memory.memory_os.state_overlay_renderer import render_state_overlay_md
from plugins.memory.memory_os.state_overlay_schema import OVERLAY_SECTION_FIELDS
from plugins.memory.memory_os.task_state import read_effective_current_task


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Memory State Overlay (no_agent, fail-open).",
    )
    parser.add_argument(
        "--hermes-home",
        default=_HERMES_HOME,
        help="Path to HERMES_HOME (default: $HERMES_HOME or ~/.hermes)",
    )
    parser.add_argument(
        "--profile",
        default="",
        help="Memory-OS profile name",
    )
    parser.add_argument(
        "--output",
        choices=("json",),
        default="json",
    )
    args = parser.parse_args(argv)
    profile = resolve_profile_name(args.hermes_home, args.profile)

    t0 = time.monotonic()
    run_status = "ok"
    error_msg = ""
    section_count = 0

    try:
        roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=profile)
        store = MemoryOSStore(roots)
        store.initialize()

        effective_task = read_effective_current_task(roots, profile=profile)
        current_task_anchor = str((effective_task or {}).get("anchor") or "")

        overlay = build_state_overlay(
            store,
            roots,
            current_task_anchor=current_task_anchor,
        )
        overlay["task_revision"] = str((effective_task or {}).get("revision") or "")
        overlay["task_source_at"] = str((effective_task or {}).get("source_at") or "")
        # `source_watermark` was never populated by read_effective_current_task
        # (it emits revision/source_at/observed_at, plus the raw record's own
        # record_id) -- this key was a dead write with no consumer. Use the
        # anchor record's own record_id instead, which is real and stable.
        overlay["task_record_id"] = str((effective_task or {}).get("record_id") or "")

        # Count populated sections — derived from OVERLAY_SECTION_FIELDS
        # (state_overlay_schema.py), the single source of truth for the set
        # of StateOverlay sections. Do not hand-maintain a separate tuple
        # here: a previously hardcoded copy silently excluded a since-removed
        # section for its entire lifetime because it was never kept in sync.
        for key in OVERLAY_SECTION_FIELDS:
            section = overlay.get(key)
            if isinstance(section, dict) and section.get("status") == "ok":
                section_count += 1

        # Write JSON
        json_path = write_state_overlay(roots, overlay)

        # Render and write markdown (atomic: temp + rename)
        md_text = render_state_overlay_md(overlay)
        md_dir = roots.memory_os_root / "system" / "state_overlay"
        md_dir.mkdir(parents=True, exist_ok=True)
        md_path = md_dir / "current.md"
        tmp_path = md_path.with_suffix(md_path.suffix + ".tmp")
        tmp_path.write_text(md_text + "\n", encoding="utf-8")
        tmp_path.replace(md_path)

    except Exception as exc:
        run_status = "error"
        error_msg = f"{type(exc).__name__}: {exc}"

    duration_ms = int((time.monotonic() - t0) * 1000)

    try:
        # Re-resolve roots for error path (roots may not be bound if init failed)
        _roots_error = MemoryOSRoots.from_hermes_home(args.hermes_home)
        append_overlay_run(
            _roots_error,
            {
                "status": run_status,
                "error": error_msg,
                "sections": section_count,
                "duration_ms": duration_ms,
            },
        )
    except Exception as _exc:
        # fail-open — even run record failure must not crash the script.
        # Emit to stderr so the cron wrapper can capture the signal.
        import sys as _sys
        _sys.stderr.write(f"state_overlay_refresh: run record write failed: {_exc}\n")

    if args.output == "json":
        print(json.dumps({
            "status": run_status,
            "error": error_msg,
            "sections": section_count,
            "duration_ms": duration_ms,
            "profile": profile,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }))

    return 0  # Always exit 0 — fail-open


if __name__ == "__main__":
    sys.exit(main())
