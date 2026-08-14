#!/usr/bin/env python3
"""Memory-OS version single-source gate.

pyproject.toml `[project].version` is the single authoritative version.
A release tag `vX.Y.Z` may only be cut from a commit whose pyproject
version matches, so the wheel metadata, the GitHub release, and the
checked-out source can never disagree again (they did: release v0.2.0
was cut while pyproject still said 0.1.0).

Usage:
  --print           print the pyproject version and exit 0
  --tag vX.Y.Z      exit 1 unless tag == f"v{{pyproject version}}"

CI wires --tag on tag pushes; run it locally before `git tag`.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path


def read_pyproject_version(repo_root: Path) -> str:
    pyproject_path = repo_root / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)
    version = str(data.get("project", {}).get("version") or "").strip()
    if not version:
        raise ValueError(f"no [project].version in {pyproject_path}")
    return version


def check_tag(tag: str, version: str) -> str | None:
    """Return an error message when tag and version disagree, else None."""
    expected = f"v{version}"
    if tag != expected:
        return (
            f"release tag {tag!r} does not match pyproject version {version!r} "
            f"(expected tag {expected!r}); bump [project].version before tagging"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Memory-OS version single-source gate.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--tag", default="", help="release tag to validate against pyproject version")
    parser.add_argument("--print", dest="print_version", action="store_true", help="print the pyproject version")
    args = parser.parse_args(argv)

    try:
        version = read_pyproject_version(Path(args.repo_root).resolve())
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"version_consistency_check: {exc}", file=sys.stderr)
        return 1

    if args.print_version:
        print(version)

    if args.tag:
        error = check_tag(args.tag.strip(), version)
        if error:
            print(f"version_consistency_check: {error}", file=sys.stderr)
            return 1
        print(f"version_consistency_check: tag {args.tag.strip()} matches pyproject version {version}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
