#!/usr/bin/env python3
"""Read-only Memory-OS shadow bundle exporter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Location-agnostic import resolution.
#
# An unconditional sys.path.insert(parents[1]) breaks on the INSTALLED layout:
# there parents[1] is $HERMES_HOME, whose plugins/ directory shadows the
# memory-os runtime namespace and yields
# "ModuleNotFoundError: No module named 'plugins.memory'". Resolve the repo
# checkout only when it actually contains the package, else fall back to the
# installed runtime tree.
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]


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


# Resolve HERMES_HOME at module level -- CLI > env > default.
_HERMES_HOME = (
    _preparse_cli_arg(sys.argv, "--hermes-home")
    or os.environ.get("HERMES_HOME", "")
    or str(Path.home() / ".hermes")
)

if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.migrator import export_shadow_bundle  # noqa: E402
from plugins.memory.memory_os.roots import MemoryOSRoots  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a read-only Memory-OS shadow bundle.")
    parser.add_argument("--profile", default="sannai")
    parser.add_argument("--hermes-home", required=True)
    parser.add_argument("--state-root", action="append", default=[])
    parser.add_argument("--out", required=True)
    parser.add_argument("--include-private-bodies", action="store_true")
    parser.add_argument("--exclude-secrets", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    roots = MemoryOSRoots.from_hermes_home(
        args.hermes_home,
        profile=args.profile,
        external_state_roots=args.state_root,
    )
    report = export_shadow_bundle(
        roots,
        out_path=args.out,
        include_private_bodies=args.include_private_bodies,
        exclude_secrets=args.exclude_secrets,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
