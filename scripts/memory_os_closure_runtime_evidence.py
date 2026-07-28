#!/usr/bin/env python3
"""Create deploy-time runtime evidence for the public Closure Matrix contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "memory-os.closure_runtime_evidence.v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--service", action="append", default=[], metavar="NAME=STATE")
    return parser


def runtime_tree_digest(runtime_root: Path) -> str:
    root = runtime_root.expanduser().resolve()
    files = sorted(
        path for path in root.rglob("*.py")
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
    )
    if not files:
        return ""
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def fresh_module_probe(runtime_root: Path, *, python_executable: str) -> dict[str, Any]:
    root = runtime_root.expanduser().resolve()
    code = (
        "import importlib,json,pathlib,sys; "
        f"root=pathlib.Path({str(root)!r}).resolve(); sys.path.insert(0,str(root)); "
        "m=importlib.import_module('plugins.memory.memory_os.cli'); "
        "origin=pathlib.Path(m.__file__).resolve(); origin.relative_to(root); "
        "print(json.dumps({'origin':str(origin),'modules':sorted(str(x['module']) for x in m._module_definitions())}))"
    )
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "HERMES_HOME"}}
    completed = subprocess.run(
        [python_executable, "-I", "-c", code],
        cwd="/",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "status": "fail",
            "returncode": completed.returncode,
            "error": completed.stderr.strip()[-500:],
            "origin": "",
            "modules": [],
        }
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        return {"status": "fail", "returncode": 0, "error": f"invalid probe json: {exc}", "origin": "", "modules": []}
    modules = payload.get("modules") if isinstance(payload, dict) else None
    origin = payload.get("origin") if isinstance(payload, dict) else None
    if not isinstance(origin, str) or not isinstance(modules, list) or not all(isinstance(item, str) for item in modules):
        return {"status": "fail", "returncode": 0, "error": "invalid probe payload", "origin": "", "modules": []}
    return {"status": "ok", "returncode": 0, "error": "", "origin": origin, "modules": modules}


def expected_live_modules(contract_path: Path | None) -> list[str] | None:
    if contract_path is None:
        return None
    data = json.loads(contract_path.expanduser().resolve().read_text(encoding="utf-8"))
    rows = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("closure contract modules must be a list")
    modules = sorted(
        item
        for row in rows if isinstance(row, dict)
        for item in row.get("live_modules", []) if isinstance(item, str)
    )
    return modules


def parse_services(values: list[str]) -> dict[str, str]:
    observations: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid service observation: {value}")
        name, state = (part.strip() for part in value.split("=", 1))
        if not name or not state:
            raise ValueError(f"invalid service observation: {value}")
        observations[name] = state
    return observations


def build_evidence(
    *,
    runtime_root: Path,
    source_head: str,
    contract_path: Path | None,
    python_executable: str,
    services: dict[str, str],
) -> dict[str, Any]:
    source_head = source_head.strip()
    digest = runtime_tree_digest(runtime_root)
    probe = fresh_module_probe(runtime_root, python_executable=python_executable)
    expected = expected_live_modules(contract_path)
    observed = probe["modules"]
    module_match = expected is None or expected == observed
    errors: list[str] = []
    if not source_head or source_head.lower() == "unknown":
        errors.append("source_head_missing")
    if not digest:
        errors.append("runtime_digest_missing")
    if probe["status"] != "ok":
        errors.append("fresh_import_failed")
    if not module_match:
        errors.append("live_module_set_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail" if errors else "ok",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_head": source_head,
        "runtime_root": str(runtime_root.expanduser().resolve()),
        "runtime_digest": digest,
        "fresh_import": probe,
        "expected_live_modules": expected,
        "observed_live_modules": observed,
        "module_set_match": module_match,
        "service_observations": dict(sorted(services.items())),
        "errors": errors,
        "boundary": {"actual_send": False, "actual_execute": False, "owner_memory_write": False},
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = build_evidence(
            runtime_root=args.runtime_root,
            source_head=args.source_head,
            contract_path=args.contract,
            python_executable=args.python,
            services=parse_services(args.service),
        )
        atomic_write(args.output, payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"closure runtime evidence failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
