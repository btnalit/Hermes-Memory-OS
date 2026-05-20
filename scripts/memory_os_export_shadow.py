#!/usr/bin/env python3
"""Read-only Memory-OS shadow bundle exporter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
