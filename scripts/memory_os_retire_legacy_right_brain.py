#!/usr/bin/env python3
"""Dry-run or apply legacy right-brain retirement."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _preparse_hermes_home(argv: list[str]) -> str:
    for index, arg in enumerate(argv):
        if arg == "--hermes-home" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--hermes-home="):
            return arg.split("=", 1)[1]
    return ""


_SELF = Path(__file__).absolute()
_REPO_ROOT = _SELF.parents[1]
if (_REPO_ROOT / "plugins" / "memory" / "memory_os").exists():
    _PATHS = [_REPO_ROOT]
else:
    _HOME = Path(_preparse_hermes_home(sys.argv[1:]) or os.environ.get("HERMES_HOME", "") or _SELF.parents[1]).expanduser()
    _PATHS = [_HOME / "memory-os" / "runtime" / "python", _HOME]
for _candidate in reversed(_PATHS):
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from plugins.memory.memory_os.legacy_right_brain_retirement import (  # noqa: E402
    retire_legacy_right_brain,
    retirement_status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--status", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = Path(args.hermes_home).expanduser().resolve()
    report = retirement_status(home) if args.status else retire_legacy_right_brain(home, apply=bool(args.apply))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.status:
        return 0 if report.get("status") in {"ok", "not_retired"} else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
