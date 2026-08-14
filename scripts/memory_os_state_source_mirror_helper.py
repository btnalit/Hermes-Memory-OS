#!/usr/bin/env python3
"""Memory-OS StateSourceMirror cron helper (daily lane).

Scans the config-declared external state roots (allowlisted patterns only)
and mirrors changed state files into summary-only Memory-OS events —
hash/size/mtime metadata, never file content. Empty external_state_roots
config means the lane runs and reports idle (state_root_count=0), which the
report says on its face: no-output-with-a-reason, per the completion-is-not-
output contract.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_self = Path(__file__).absolute()
_repo_root = _self.parents[1]

_HERMES_HOME = os.environ.get("HERMES_HOME", "") or str(Path.home() / ".hermes")

if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
if not (_repo_root / "plugins" / "memory" / "memory_os").exists():
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.config import load_config
from plugins.memory.memory_os.lane_last_run import record_lane_last_run
from plugins.memory.memory_os.roots import MemoryOSRoots, resolve_profile_name
from plugins.memory.memory_os.state_source_mirror import StateSourceMirror
from plugins.memory.memory_os.store import MemoryOSStore


def main() -> int:
    config = load_config(_HERMES_HOME)
    external_roots = [
        str(root) for root in (config.get("external_state_roots") or []) if str(root or "").strip()
    ]
    profile = resolve_profile_name(_HERMES_HOME)
    roots = MemoryOSRoots.from_hermes_home(
        _HERMES_HOME,
        profile=profile,
        external_state_roots=external_roots,
    )
    store = MemoryOSStore(roots)
    store.initialize()
    report = StateSourceMirror(store).scan(dry_run=False)
    report["external_state_root_count"] = len(external_roots)
    # The scan's findings/status used to be stdout-only while the durable
    # state file only bumped a timestamp — persist the outcome per run.
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    findings_by_code: dict[str, int] = {}
    for finding in findings:
        code = str(finding.get("code") or "unknown") if isinstance(finding, dict) else "unknown"
        findings_by_code[code] = findings_by_code.get(code, 0) + 1
    scan_status = str(report.get("status") or "")
    record_lane_last_run(
        _HERMES_HOME,
        "state_source_mirror",
        status="ok" if scan_status in {"ok", "warning"} else "error",
        reason=f"scan_{scan_status or 'failed'}",
        counters={"findings": len(findings), **findings_by_code},
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") in {"ok", "warning"} else 1


if __name__ == "__main__":
    sys.exit(main())
