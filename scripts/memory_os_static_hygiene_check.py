#!/usr/bin/env python3
"""Repo-native static hygiene check for Memory-OS closeout."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


Runner = Callable[[list[str], Path], dict[str, Any]]


def default_runner(argv: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        argv,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def run_static_hygiene(repo_root: Path, *, runner: Runner = default_runner) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    checks = {
        "compileall": [sys.executable, "-m", "compileall", "-q", "plugins", "scripts", "tests"],
        "diff_check": ["git", "diff", "--check"],
        "closure_matrix": [
            sys.executable,
            "scripts/memory_os_closure_matrix_check.py",
            "--format",
            "summary",
        ],
        "public_checkout_probe": [
            sys.executable,
            "scripts/memory_os_public_checkout_probe.py",
            "--repo-root",
            ".",
        ],
        "write_surface_check": [
            sys.executable,
            "scripts/memory_os_write_surface_check.py",
            "--repo-root",
            ".",
            "--output",
            "summary",
        ],
    }
    results: dict[str, dict[str, Any]] = {}
    provider_literal_hits = []
    memory_os_root = root / "plugins" / "memory" / "memory_os"
    if memory_os_root.exists():
        for path in sorted(memory_os_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "ragflow" in text.lower():
                provider_literal_hits.append(str(path.relative_to(root)))
    results["memory_os_provider_agnostic"] = {
        "status": "fail" if provider_literal_hits else "pass",
        "exit_code": 1 if provider_literal_hits else 0,
        "hits": provider_literal_hits,
    }
    for name, argv in checks.items():
        raw = runner(argv, root)
        results[name] = {
            "status": "pass" if int(raw.get("exit_code") or 0) == 0 else "fail",
            "exit_code": int(raw.get("exit_code") or 0),
        }
    status = "pass" if all(item["status"] == "pass" for item in results.values()) else "fail"
    return {
        "schema_version": "memory-os.static_hygiene.v0",
        "status": status,
        "ruff_required": False,
        "checks": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    report = run_static_hygiene(Path(args.repo_root))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
