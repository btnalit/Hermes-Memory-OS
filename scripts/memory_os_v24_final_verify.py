#!/usr/bin/env python3
"""One-shot final verification for the v2.4 corrective release.

This is intentionally a single top-level invocation. It records the exact
working-tree fingerprint, targeted regressions, governance gates, the
mount-isolated full suite, wheel build, and a clean-tree full suite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "memory-os.v24_final_verification.v1"
IGNORED_COPY_PARTS = {
    ".git", ".pytest_cache", ".venv", "__pycache__", "build", "dist",
    ".mypy_cache", ".ruff_cache", ".coverage", "htmlcov", ".tox",
    "memory-os", "snapshot.generated.js",
}


def ignored_name(name: str) -> bool:
    return name in IGNORED_COPY_PARTS or name.endswith((".pyc", ".egg-info"))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    result.add_argument("--report", type=Path, required=True)
    result.add_argument("--python", default=sys.executable)
    return result


def tree_manifest(repo_root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(repo_root)
        if any(ignored_name(part) for part in relative.parts):
            continue
        manifest[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def tree_fingerprint(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for relative, file_digest in sorted(tree_manifest(repo_root).items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def run_step(name: str, command: list[str], *, cwd: Path, timeout: int = 1800) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return {
        "name": name,
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": completed.stdout[-12000:],
        "stderr_tail": completed.stderr[-12000:],
        "status": "pass" if completed.returncode == 0 else "fail",
    }


def copy_clean_tree(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if ignored_name(name)}

    shutil.copytree(source, destination, ignore=ignore, symlinks=False)


def initialize_clean_git(repo_root: Path, source_root: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Memory-OS Verification",
        "GIT_AUTHOR_EMAIL": "verification@localhost",
        "GIT_COMMITTER_NAME": "Memory-OS Verification",
        "GIT_COMMITTER_EMAIL": "verification@localhost",
    }
    for command in (["git", "init", "-q"], ["git", "add", "-A"]):
        subprocess.run(command, cwd=repo_root, env=env, check=True, capture_output=True, text=True)
    tracked_result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=source_root, check=True, capture_output=True
    ).stdout
    tracked_paths = [path for path in tracked_result.split(b"\0") if path]
    # `git add -f` below runs with cwd=repo_root (the copy_clean_tree-filtered
    # copy), not source_root — a tracked path that copy_clean_tree excluded
    # (anything under an IGNORED_COPY_PARTS directory) exists in source_root
    # but not in repo_root, so the existence check must test repo_root or
    # the pathspec includes a path git can't find and `git add -f` fails.
    existing_tracked = [
        path
        for path in tracked_paths
        if (repo_root / os.fsdecode(path)).exists()
    ]
    tracked = b"\0".join(existing_tracked) + (b"\0" if existing_tracked else b"")
    if tracked:
        subprocess.run(
            ["git", "add", "-f", "--pathspec-from-file=-", "--pathspec-file-nul"],
            cwd=repo_root,
            env=env,
            input=tracked,
            check=True,
            capture_output=True,
        )
    subprocess.run(
        ["git", "commit", "-q", "-m", "verification candidate"],
        cwd=repo_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    report_path = args.report.expanduser().resolve()
    python = str(Path(args.python).expanduser().resolve())
    started_at = datetime.now(timezone.utc)
    before_manifest = tree_manifest(repo_root)
    before = tree_fingerprint(repo_root)
    steps: list[dict[str, Any]] = []

    targeted = [
        "tests/plugins/memory/test_memory_os_operational_truth.py",
        "tests/scripts/test_memory_os_full_monitor_refresh.py",
        "tests/scripts/test_memory_os_monitor_dashboard_snapshot.py",
        "tests/scripts/test_memory_os_closure_matrix_check.py",
        "tests/scripts/test_memory_os_closure_runtime_evidence.py",
        "tests/scripts/test_memory_os_pytest_policy.py",
        "tests/plugins/memory/test_memory_os_deploy_clean_host.py",
        "tests/plugins/memory/test_memory_os_private_backup.py",
        "tests/plugins/memory/test_memory_os_section_status.py",
        "tests/plugins/memory/test_memory_os_jsonl_robustness.py",
        "tests/plugins/memory/test_memory_os_recovery_marker.py",
        "tests/plugins/memory/test_memory_os_restraint.py",
        "tests/plugins/memory/test_memory_os_natural_row.py",
        "tests/plugins/memory/test_memory_os_natural_evidence.py",
    ]
    commands = [
        ("targeted_regressions", [python, "-m", "pytest", "-q", *targeted]),
        ("git_diff_check", ["git", "diff", "--check"]),
        ("import_cycle_gate", [python, "scripts/memory_os_import_cycle_check.py", "--repo-root", "."]),
        ("write_surface_gate", [python, "scripts/memory_os_write_surface_check.py", "--repo-root", ".", "--output", "summary"]),
        ("static_hygiene_gate", [python, "scripts/memory_os_static_hygiene_check.py", "--repo-root", "."]),
        ("public_checkout_gate", [python, "scripts/memory_os_public_checkout_probe.py", "--repo-root", ".", "--source", "working-tree", "--strict"]),
        ("closure_matrix_gate", [python, "scripts/memory_os_closure_matrix_check.py", "--repo-root", ".", "--format", "summary"]),
        ("mount_isolated_full_suite", [python, "scripts/memory_os_mount_isolated_pytest.py", "--repo-root", ".", "--python", python, "--report", str(report_path.with_name("v24-pytest-policy.json"))]),
    ]
    for name, command in commands:
        steps.append(run_step(name, command, cwd=repo_root))

    with tempfile.TemporaryDirectory(prefix="memory-os-v24-wheel-") as wheel_dir:
        steps.append(
            run_step(
                "wheel_build",
                [python, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", wheel_dir, "."],
                cwd=repo_root,
            )
        )

    with tempfile.TemporaryDirectory(prefix="memory-os-v24-clean-") as temporary:
        clean_root = Path(temporary) / "repo"
        copy_clean_tree(repo_root, clean_root)
        initialize_clean_git(clean_root, repo_root)
        clean_before_manifest = tree_manifest(clean_root)
        clean_before = tree_fingerprint(clean_root)
        clean_commands = [
            ("clean_public_checkout_gate", [python, "scripts/memory_os_public_checkout_probe.py", "--repo-root", ".", "--source", "working-tree", "--strict"]),
            ("clean_closure_matrix_gate", [python, "scripts/memory_os_closure_matrix_check.py", "--repo-root", ".", "--format", "summary"]),
            ("clean_mount_isolated_full_suite", [python, "scripts/memory_os_mount_isolated_pytest.py", "--repo-root", ".", "--python", python, "--report", str(report_path.with_name("v24-clean-pytest-policy.json"))]),
        ]
        for name, command in clean_commands:
            steps.append(run_step(name, command, cwd=clean_root))
        clean_after_manifest = tree_manifest(clean_root)
        clean_after = tree_fingerprint(clean_root)

    after_manifest = tree_manifest(repo_root)
    after = tree_fingerprint(repo_root)
    fingerprint_stable = before == after
    failed_steps = [step["name"] for step in steps if step["status"] != "pass"]
    if not fingerprint_stable:
        failed_steps.append("source_tree_mutated_during_verification")
    if clean_before != clean_after:
        failed_steps.append("clean_tree_mutated_during_verification")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if not failed_steps else "fail",
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repo_root": str(repo_root),
        "python": python,
        "source_tree_fingerprint_before": before,
        "source_tree_fingerprint_after": after,
        "source_tree_fingerprint_stable": fingerprint_stable,
        "source_tree_changed_paths": sorted(
            path for path in set(before_manifest) | set(after_manifest)
            if before_manifest.get(path) != after_manifest.get(path)
        ),
        "clean_tree_fingerprint_before": clean_before,
        "clean_tree_fingerprint_after": clean_after,
        "clean_tree_changed_paths": sorted(
            path for path in set(clean_before_manifest) | set(clean_after_manifest)
            if clean_before_manifest.get(path) != clean_after_manifest.get(path)
        ),
        "failed_steps": failed_steps,
        "steps": steps,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_name(f".{report_path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, report_path)
    print(json.dumps({
        "status": payload["status"],
        "failed_steps": failed_steps,
        "report": str(report_path),
        "source_tree_fingerprint": before,
        "step_count": len(steps),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
