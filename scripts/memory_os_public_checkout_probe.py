#!/usr/bin/env python3
"""Validate the Memory-OS public checkout/archive surface."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "memory-os.public_checkout_probe.v1"

PUBLIC_DOCS = {"README.md", "configuration.md", "quickstart.md"}
PRIVATE_DOCS = {
    "memory-os-v7-3-200-grounded-task-plan.md",
    "memory-os-v7-promotion-matrix.md",
}
REQUIRED_PUBLIC_FILES = (
    ".gitignore",
    "docs/README.md",
    "docs/configuration.md",
    "docs/quickstart.md",
    "scripts/install_memory_os.sh",
    "scripts/memory_os_3_200_monitor.py",
    "scripts/memory_os_blank_host_smoke.py",
    "scripts/memory_os_host_profile.py",
    "scripts/memory_os_monitor.py",
    "scripts/memory_os_public_checkout_probe.py",
    "scripts/memory_os_upgrade_compat_check.py",
    "scripts/memory_os_upgrade_evidence_compare.py",
    "plugins/memory/memory_os/execution_gate.py",
    "plugins/memory/memory_os/owner_actions.py",
    "plugins/memory/memory_os/session_mirror.py",
    "plugins/modules/expression/grounded_expression_judge.py",
    "eval/memory_os/runner/registry.py",
    "eval/memory_os/adapters/retrieval_shadow.py",
    "eval/memory_os/data/retrieval_shadow_cases.jsonl",
    "tests/eval/test_memory_os_retrieval_shadow.py",
    "tests/scripts/test_memory_os_public_checkout_probe.py",
    "tests/scripts/test_memory_os_upgrade_evidence_compare.py",
)
IMPORT_SMOKE_TARGETS = (
    "plugins.memory.memory_os.owner_actions",
    "plugins.memory.memory_os.session_mirror",
    "plugins.memory.memory_os.execution_gate",
    "scripts.memory_os_host_profile",
    "scripts.memory_os_3_200_monitor",
    "scripts.memory_os_monitor",
)


def run_probe(repo_root: Path, *, source: str) -> dict[str, object]:
    repo_root = repo_root.resolve()
    head = _git(repo_root, "rev-parse", "--short", "HEAD").strip()
    with tempfile.TemporaryDirectory(prefix="memory-os-public-checkout-") as tmp:
        checkout_root = Path(tmp) / "checkout"
        checkout_root.mkdir()
        if source == "head":
            _extract_head_archive(repo_root, checkout_root)
        elif source == "working-tree":
            _copy_working_tree_candidate(repo_root, checkout_root)
        else:  # pragma: no cover - argparse restricts values.
            raise ValueError(f"Unsupported source: {source}")

        docs_root = checkout_root / "docs"
        public_docs = sorted(path.name for path in docs_root.glob("*.md")) if docs_root.exists() else []
        required_presence = {
            relpath: (checkout_root / Path(relpath)).exists()
            for relpath in REQUIRED_PUBLIC_FILES
        }
        missing_required = sorted(relpath for relpath, present in required_presence.items() if not present)
        private_docs_present = sorted(
            relpath
            for relpath in _private_doc_relpaths(checkout_root)
            if (checkout_root / relpath).exists()
        )
        public_docs_ok = set(public_docs) == PUBLIC_DOCS
        internal_docs_visible = (checkout_root / "docs" / "internal-memory-os").exists()
        import_smoke = _run_import_smoke(checkout_root)

    classification = _classify(
        public_docs_ok=public_docs_ok,
        missing_required=missing_required,
        private_docs_present=private_docs_present,
        internal_docs_visible=internal_docs_visible,
        import_smoke_ok=bool(import_smoke["ok"]),
        import_smoke_failures=list(import_smoke["failures"]),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "head": head,
        "public_docs": public_docs,
        "public_docs_ok": public_docs_ok,
        "internal_docs_visible": internal_docs_visible,
        "private_docs_present": private_docs_present,
        "required_public_files": required_presence,
        "missing_required_public_files": missing_required,
        "import_smoke_targets": list(IMPORT_SMOKE_TARGETS),
        "import_smoke_ok": bool(import_smoke["ok"]),
        "import_smoke_failures": list(import_smoke["failures"]),
        "classification": classification,
    }


def _extract_head_archive(repo_root: Path, checkout_root: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    archive_path = checkout_root.parent / "head.tar"
    archive_path.write_bytes(archive)
    with tarfile.open(archive_path) as tar:
        try:
            tar.extractall(checkout_root, filter="data")
        except TypeError:  # Python < 3.12 does not support extraction filters.
            tar.extractall(checkout_root)


def _copy_working_tree_candidate(repo_root: Path, checkout_root: Path) -> None:
    files = _git(repo_root, "ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    for relpath in files:
        if not relpath or relpath.startswith(".codegraph/"):
            continue
        source = repo_root / relpath
        target = checkout_root / relpath
        if not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _private_doc_relpaths(checkout_root: Path) -> Iterable[Path]:
    for filename in PRIVATE_DOCS:
        yield Path("docs") / filename
    internal = checkout_root / "docs" / "internal-memory-os"
    if internal.exists():
        yield Path("docs") / "internal-memory-os"


def _run_import_smoke(checkout_root: Path) -> dict[str, object]:
    failures: list[dict[str, object]] = []
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(checkout_root)
        if not existing_pythonpath
        else str(checkout_root) + os.pathsep + existing_pythonpath
    )
    for target in IMPORT_SMOKE_TARGETS:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib, sys; importlib.import_module(sys.argv[1])",
                target,
            ],
            cwd=checkout_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            failures.append(
                {
                    "module": target,
                    "returncode": result.returncode,
                    "stderr": result.stderr.strip()[-2000:],
                }
            )
    return {"ok": not failures, "failures": failures}


def _classify(
    *,
    public_docs_ok: bool,
    missing_required: list[str],
    private_docs_present: list[str],
    internal_docs_visible: bool,
    import_smoke_ok: bool,
    import_smoke_failures: list[dict[str, object]],
) -> dict[str, list[dict[str, object]] | str]:
    passed: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []

    if public_docs_ok:
        passed.append({"code": "public_docs_allowlist_ok"})
    else:
        failed.append({"code": "public_docs_allowlist_mismatch"})
    if missing_required:
        failed.append({"code": "required_public_files_missing", "paths": missing_required})
    else:
        passed.append({"code": "required_public_files_present"})
    if private_docs_present or internal_docs_visible:
        failed.append({"code": "private_docs_visible", "paths": private_docs_present})
    else:
        passed.append({"code": "private_docs_absent"})
    if import_smoke_ok:
        passed.append({"code": "import_smoke_ok", "targets": list(IMPORT_SMOKE_TARGETS)})
    else:
        failed.append({"code": "import_smoke_failed", "failures": import_smoke_failures})

    return {
        "status": "FAIL" if failed else "PASS",
        "pass": passed,
        "fail": failed,
        "warn": [],
    }


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source", choices=["head", "working-tree"], default="head")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when classification is not PASS.")
    args = parser.parse_args(argv)

    report = run_probe(args.repo_root, source=args.source)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.strict and report["classification"]["status"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
