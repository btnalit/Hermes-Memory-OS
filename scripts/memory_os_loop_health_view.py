#!/usr/bin/env python3
"""Print the Loop Health View — a read-only projection over lane evidence.

On-demand owner tool (not a cron lane): groups registered lanes into
production loops and rolls up each loop's state from the standard
system/lane_last_run/ evidence. Writes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERMES_HOME = os.environ.get("HERMES_HOME", "") or str(Path.home() / ".hermes")
_repo_root = Path(__file__).absolute().parents[1]
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.loop_health_view import (
    build_loop_health_view,
    render_loop_health_summary,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=_HERMES_HOME)
    parser.add_argument("--output", choices=("json", "summary"), default="summary")
    args = parser.parse_args(argv)

    view = build_loop_health_view(args.hermes_home)
    if args.output == "json":
        print(json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_loop_health_summary(view))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
