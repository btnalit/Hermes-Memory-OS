#!/usr/bin/env python3
"""Run the complete pytest suite with /root/.hermes hidden by a mount namespace."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


TARGET_HERMES_HOME = Path("/root/.hermes")


def absolute_without_resolving(path: Path) -> Path:
    """Make a path absolute while preserving a venv launcher symlink."""
    return Path(os.path.abspath(path.expanduser()))


def build_namespace_command(
    *,
    repo_root: Path,
    isolated_home: Path,
    python: Path,
    report_path: Path,
    effective_uid: int,
) -> list[str]:
    namespace = ["unshare", "--mount"]
    if effective_uid != 0:
        namespace.extend(["--user", "--map-root-user"])
    namespace.append("--fork")
    inner = (
        "set -eu; "
        "mount --make-rprivate /; "
        "mount --bind \"$1\" /root/.hermes; "
        "cd \"$2\"; "
        "exec env -u HERMES_HOME -u PYTHONPATH \"$3\" -B -m pytest "
        "-p no:cacheprovider -p scripts.memory_os_pytest_policy "
        "--memory-os-policy-report \"$4\" -q tests"
    )
    return [
        *namespace,
        "sh",
        "-c",
        inner,
        "sh",
        str(isolated_home),
        str(repo_root),
        str(python),
        str(report_path),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--keep-isolated-home", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    python = absolute_without_resolving(args.python)
    report_path = args.report.expanduser().resolve()
    if not (repo_root / "pyproject.toml").is_file():
        raise SystemExit(f"repository root is invalid: {repo_root}")
    if not python.is_file():
        raise SystemExit(f"python interpreter does not exist: {python}")

    created_target = False
    if not TARGET_HERMES_HOME.exists():
        if os.geteuid() != 0:
            raise SystemExit(
                "/root/.hermes is absent; run this entry point as root so the mount target can be created"
            )
        TARGET_HERMES_HOME.mkdir(parents=True)
        created_target = True

    temp_context: tempfile.TemporaryDirectory[str] | None = None
    if args.keep_isolated_home:
        isolated_home = Path(tempfile.mkdtemp(prefix="memory-os-ci-home-"))
    else:
        temp_context = tempfile.TemporaryDirectory(prefix="memory-os-ci-home-")
        isolated_home = Path(temp_context.name)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    command = build_namespace_command(
        repo_root=repo_root,
        isolated_home=isolated_home,
        python=python,
        report_path=report_path,
        effective_uid=os.geteuid(),
    )
    try:
        completed = subprocess.run(command, check=False)
        if not report_path.is_file():
            return completed.returncode or 2
        try:
            policy = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return completed.returncode or 2
        if completed.returncode != 0 or policy.get("status") != "pass":
            return completed.returncode or 1
        return 0
    finally:
        if temp_context is not None:
            temp_context.cleanup()
        if created_target:
            try:
                TARGET_HERMES_HOME.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
