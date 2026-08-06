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
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.state_source_mirror import StateSourceMirror
from plugins.memory.memory_os.store import MemoryOSStore


def main() -> int:
    config = load_config(_HERMES_HOME)
    external_roots = [
        str(root) for root in (config.get("external_state_roots") or []) if str(root or "").strip()
    ]
    profile = os.environ.get("HERMES_PROFILE", "default")
    roots = MemoryOSRoots.from_hermes_home(
        _HERMES_HOME,
        profile=profile,
        external_state_roots=external_roots,
    )
    store = MemoryOSStore(roots)
    store.initialize()
    report = StateSourceMirror(store).scan(dry_run=False)
    report["external_state_root_count"] = len(external_roots)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") in {"ok", "warning"} else 1


if __name__ == "__main__":
    sys.exit(main())
