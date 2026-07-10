#!/usr/bin/env python3
"""Repo-native static hygiene check for Memory-OS closeout."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


Runner = Callable[[list[str], Path], dict[str, Any]]


# ── Host-boundary guard (N2) ────────────────────────────────────────────────
# Memory-OS is a governed plugin: it must NOT own transport, channel resolution,
# or scheduling — those stay in the Hermes host / cron onboarding seam. This is
# a compile-time lock so the boundary is enforced by CI, not by discipline.
# Internal "delivery"/"deliver" helper *names* (e.g. prepare_permanent_promotion_delivery,
# owner_review_deliveries_path) are intra-package and intentionally NOT flagged;
# only imports of the host/onboarding seam and its path literal are.
_BOUNDARY_FORBIDDEN_IMPORT_FRAGMENTS = (
    "owner_cron_onboarding",
    "channel_directory",
)
_BOUNDARY_FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "discover_owner_channels",
        "_resolve_deliver",
        "_resolve_owner_review_channel",
    }
)
_BOUNDARY_FORBIDDEN_LITERALS = ("channel_directory.json",)


def scan_source_boundary_violations(rel_path: str, source: str) -> list[dict[str, str]]:
    """Flag host-boundary breaches in a single memory_os source file.

    Detects (a) imports of the onboarding/channel-resolution seam by module
    fragment or imported name, and (b) the channel_directory path literal.
    Relative imports and internal delivery-ledger helpers are not violations.
    """
    violations: list[dict[str, str]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return violations  # compileall covers syntax separately
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0 and any(frag in module for frag in _BOUNDARY_FORBIDDEN_IMPORT_FRAGMENTS):
                violations.append({"path": rel_path, "kind": "forbidden_import_module", "detail": module})
            for alias in node.names:
                if alias.name in _BOUNDARY_FORBIDDEN_IMPORT_NAMES:
                    violations.append({"path": rel_path, "kind": "forbidden_import_name", "detail": alias.name})
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(frag in alias.name for frag in _BOUNDARY_FORBIDDEN_IMPORT_FRAGMENTS):
                    violations.append({"path": rel_path, "kind": "forbidden_import_module", "detail": alias.name})
    for literal in _BOUNDARY_FORBIDDEN_LITERALS:
        if literal in source:
            violations.append({"path": rel_path, "kind": "forbidden_path_literal", "detail": literal})
    return violations


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
    boundary_violations: list[dict[str, str]] = []
    memory_os_root = root / "plugins" / "memory" / "memory_os"
    if memory_os_root.exists():
        for path in sorted(memory_os_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel_path = str(path.relative_to(root))
            text = path.read_text(encoding="utf-8")
            if "ragflow" in text.lower():
                provider_literal_hits.append(rel_path)
            boundary_violations.extend(scan_source_boundary_violations(rel_path, text))
    results["memory_os_provider_agnostic"] = {
        "status": "fail" if provider_literal_hits else "pass",
        "exit_code": 1 if provider_literal_hits else 0,
        "hits": provider_literal_hits,
    }
    results["memory_os_host_boundary"] = {
        "status": "fail" if boundary_violations else "pass",
        "exit_code": 1 if boundary_violations else 0,
        "violations": boundary_violations,
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
