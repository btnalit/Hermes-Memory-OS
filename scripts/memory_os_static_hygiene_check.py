#!/usr/bin/env python3
"""Repo-native static hygiene check for Memory-OS closeout."""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
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
    "plugins.seam.hermes_memory_os",
)
_BOUNDARY_FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "discover_owner_channels",
        "_resolve_deliver",
        "_resolve_owner_review_channel",
    }
)
_BOUNDARY_FORBIDDEN_LITERALS = ("channel_directory.json",)
_BOUNDARY_FORBIDDEN_HOST_SYMBOLS = frozenset(
    {
        "CHANNEL_PRIORITY",
        "OWNER_REVIEW_DELIVERY_ADAPTERS",
        "resolve_owner_review_channel",
        "_configured_channel_candidate",
        "_channel_candidate_is_safe",
        "_session_channel_candidates",
    }
)
_BOUNDARY_HOST_SUBPROCESS_METHODS = frozenset({"run", "Popen", "check_call", "check_output"})

# Exact, count-bounded debt present at eab6ed7.  New violations, including
# additional copies in these files, remain CI failures.  Entries disappear as
# S0.4 moves each capability to the Hermes host adapter.
_DECLARED_LEGACY_BOUNDARY_DEBT: Counter[tuple[str, str, str]] = Counter(
    {
        ("plugins/memory/memory_os/cli.py", "forbidden_host_symbol", "resolve_owner_review_channel"): 1,
        ("plugins/memory/memory_os/hermes_cron_adapter.py", "forbidden_host_invocation", "hermes cron"): 2,
        ("plugins/memory/memory_os/host_capability_probe.py", "forbidden_host_symbol", "resolve_owner_review_channel"): 1,
        ("plugins/memory/memory_os/host_capability_probe.py", "forbidden_host_invocation", "hermes --version"): 1,
        ("plugins/memory/memory_os/owner_actions.py", "forbidden_host_symbol", "OWNER_REVIEW_DELIVERY_ADAPTERS"): 1,
        ("plugins/memory/memory_os/owner_actions.py", "forbidden_host_symbol", "resolve_owner_review_channel"): 4,
        ("plugins/memory/memory_os/owner_actions.py", "forbidden_host_symbol", "_configured_channel_candidate"): 2,
        ("plugins/memory/memory_os/owner_actions.py", "forbidden_host_symbol", "_channel_candidate_is_safe"): 2,
        ("plugins/memory/memory_os/owner_actions.py", "forbidden_host_symbol", "_session_channel_candidates"): 2,
        ("plugins/memory/memory_os/owner_actions.py", "forbidden_host_invocation", "hermes send"): 1,
    }
)


def scan_source_boundary_violations(rel_path: str, source: str) -> list[dict[str, str]]:
    """Flag host-boundary breaches in a single memory_os source file.

    Detects (a) imports of the onboarding/channel-resolution seam by module
    fragment or imported name, and (b) the channel_directory path literal.
    Relative imports and internal delivery-ledger helpers are not violations.
    """
    rel_path = str(rel_path).replace("\\", "/")
    violations: list[dict[str, str]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return violations  # compileall covers syntax separately
    command_bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            signature = _host_command_signature(value)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    if signature:
                        command_bindings[target.id] = signature
                    if target.id in _BOUNDARY_FORBIDDEN_HOST_SYMBOLS:
                        violations.append({"path": rel_path, "kind": "forbidden_host_symbol", "detail": target.id})
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _BOUNDARY_FORBIDDEN_HOST_SYMBOLS:
            violations.append({"path": rel_path, "kind": "forbidden_host_symbol", "detail": node.name})
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
        elif isinstance(node, ast.Call):
            called_name = _called_name(node.func)
            if called_name in _BOUNDARY_FORBIDDEN_HOST_SYMBOLS:
                violations.append({"path": rel_path, "kind": "forbidden_host_symbol", "detail": called_name})
            if _is_subprocess_call(node.func) and node.args:
                signature = (
                    command_bindings.get(node.args[0].id, "")
                    if isinstance(node.args[0], ast.Name)
                    else _host_command_signature(node.args[0])
                )
                if signature:
                    violations.append({"path": rel_path, "kind": "forbidden_host_invocation", "detail": signature})
            elif called_name in {"system", "popen"} and node.args:
                signature = _host_command_signature(node.args[0])
                if signature:
                    violations.append({"path": rel_path, "kind": "forbidden_host_invocation", "detail": signature})
    for literal in _BOUNDARY_FORBIDDEN_LITERALS:
        if literal in source:
            violations.append({"path": rel_path, "kind": "forbidden_path_literal", "detail": literal})
    return violations


def partition_boundary_violations(
    violations: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    remaining = _DECLARED_LEGACY_BOUNDARY_DEBT.copy()
    unapproved: list[dict[str, str]] = []
    declared: list[dict[str, str]] = []
    for violation in violations:
        fingerprint = (
            str(violation.get("path") or ""),
            str(violation.get("kind") or ""),
            str(violation.get("detail") or ""),
        )
        if remaining[fingerprint] > 0:
            remaining[fingerprint] -= 1
            declared.append(violation)
        else:
            unapproved.append(violation)
    return unapproved, declared


def _called_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_subprocess_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "subprocess"
        and node.attr in _BOUNDARY_HOST_SUBPROCESS_METHODS
    )


def _host_command_signature(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value.strip().lower()
        if "hermes" not in text:
            return ""
        if " send" in f" {text}":
            return "hermes send"
        if " cron" in f" {text}":
            return "hermes cron"
        if "--version" in text:
            return "hermes --version"
        return ""
    if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 2:
        return ""
    first = ast.unparse(node.elts[0]).lower()
    if "hermes" not in first:
        return ""
    second = node.elts[1]
    second_value = second.value.lower() if isinstance(second, ast.Constant) and isinstance(second.value, str) else ""
    if second_value == "send":
        return "hermes send"
    if second_value == "cron":
        return "hermes cron"
    if second_value == "--version":
        return "hermes --version"
    return ""


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
    pycache_root = Path(tempfile.mkdtemp(prefix="memory-os-compileall-"))
    checks = {
        "compileall": [
            sys.executable,
            "-X",
            f"pycache_prefix={pycache_root}",
            "-m",
            "compileall",
            "plugins",
            "scripts",
            "tests",
        ],
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
    unapproved_boundary_violations, declared_legacy_boundary_debt = partition_boundary_violations(boundary_violations)
    results["memory_os_host_boundary"] = {
        "status": "fail" if unapproved_boundary_violations else "pass",
        "exit_code": 1 if unapproved_boundary_violations else 0,
        "violations": unapproved_boundary_violations,
        "declared_legacy_debt": declared_legacy_boundary_debt,
    }
    try:
        for name, argv in checks.items():
            raw = runner(argv, root)
            result_entry = {
                "status": "pass" if int(raw.get("exit_code") or 0) == 0 else "fail",
                "exit_code": int(raw.get("exit_code") or 0),
            }
            if name == "compileall" and result_entry["status"] == "fail":
                result_entry["stdout"] = raw.get("stdout", "")
                result_entry["stderr"] = raw.get("stderr", "")
            results[name] = result_entry
    finally:
        shutil.rmtree(pycache_root, ignore_errors=True)
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
