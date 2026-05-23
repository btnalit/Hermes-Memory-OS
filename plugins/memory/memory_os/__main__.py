"""Standalone module entrypoint for Memory-OS provider CLI commands."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .cli import memory_os_command, register_cli


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memory_os")
    register_cli(parser)
    return int(memory_os_command(parser.parse_args(list(argv) if argv is not None else None)))


if __name__ == "__main__":
    raise SystemExit(main())
