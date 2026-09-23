#!/usr/bin/env python3
"""Memory-OS memory-projection retention compaction cron helper (daily lane).

Wires the already-implemented, previously-unwired
``memory_projection.compact_memory_projection_records`` into production as
the ``memory_projection_compaction`` member of the ``tick_daily`` cron group.
Before this lane existed, ``memory_projections.jsonl`` had no compaction
caller at all (the only production invocation on record was a one-off manual
CLI run) and grew without bound.

Completion Is Not Output: ``compact_memory_projection_records(apply=True)``
itself durably records a closed-outcome report on every call --
``system/memory_projection_compactions.jsonl`` gains one entry with
``reason`` in {"compacted", "nothing_to_drop", "malformed_lines_present",
"write_failed"} -- so this lane is classified ``dedicated_artifact`` in
``cron_registry.LANE_LAST_RUN_EVIDENCE`` rather than also writing a
``lane_last_run`` record: the compaction report already is the per-run
evidence, readable via ``memory_projection_retention_status()`` without
re-running anything.

Exit code: 0 for a healthy run (compacted or nothing to drop), 1 for a
refused/failed run (malformed ledger or a write failure) so the wrapping
ExecutionGate completion is marked ``error`` and the monitor's generic
cron-helper-completion classifier surfaces it.
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

from plugins.memory.memory_os.memory_projection import compact_memory_projection_records
from plugins.memory.memory_os.roots import MemoryOSRoots, resolve_profile_name

# Matches compact_memory_projection_records' own default -- keep the newest
# 3 short_lived_status records per (source_scope_ref, source_key) scope.
# Not exposed as a knob: this mirrors the edge_weight_feedback shadow-ledger
# compaction precedent (module-level constants, not per-lane knobs) since
# there is exactly one call site and no A/B or operator-tuning need yet.
KEEP_LATEST_STATUS_PER_SOURCE = 3

_HEALTHY_REASONS = {"compacted", "nothing_to_drop"}


def main() -> int:
    profile = resolve_profile_name(_HERMES_HOME)
    roots = MemoryOSRoots.from_hermes_home(_HERMES_HOME, profile=profile)
    report = compact_memory_projection_records(
        roots,
        keep_latest_status_per_source=KEEP_LATEST_STATUS_PER_SOURCE,
        apply=True,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    reason = str(report.get("reason") or "")
    return 0 if reason in _HEALTHY_REASONS else 1


if __name__ == "__main__":
    sys.exit(main())
