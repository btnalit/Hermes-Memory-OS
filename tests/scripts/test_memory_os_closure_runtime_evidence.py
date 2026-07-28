from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.memory_os_closure_runtime_evidence import atomic_write, build_evidence


def _runtime(root: Path, modules: list[str]) -> Path:
    package = root / "plugins" / "memory" / "memory_os"
    package.mkdir(parents=True)
    (root / "plugins" / "memory" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        "def _module_definitions():\n"
        f"    return {[{'module': item} for item in modules]!r}\n",
        encoding="utf-8",
    )
    return root


def _contract(path: Path, modules: list[str]) -> Path:
    path.write_text(
        json.dumps({"modules": [{"live_modules": modules}]}),
        encoding="utf-8",
    )
    return path


def test_runtime_evidence_binds_fresh_origin_digest_modules_and_services(tmp_path):
    runtime = _runtime(tmp_path / "runtime", ["alpha", "beta"])
    contract = _contract(tmp_path / "contract.json", ["alpha", "beta"])

    evidence = build_evidence(
        runtime_root=runtime,
        source_head="abc123",
        contract_path=contract,
        python_executable=sys.executable,
        services={"gateway": "active"},
    )

    assert evidence["status"] == "ok"
    assert evidence["runtime_digest"].startswith("sha256:")
    assert evidence["fresh_import"]["origin"].startswith(str(runtime.resolve()))
    assert evidence["module_set_match"] is True
    assert evidence["service_observations"] == {"gateway": "active"}


def test_runtime_evidence_fails_closed_on_module_set_mismatch(tmp_path):
    runtime = _runtime(tmp_path / "runtime", ["alpha"])
    contract = _contract(tmp_path / "contract.json", ["alpha", "missing"])

    evidence = build_evidence(
        runtime_root=runtime,
        source_head="abc123",
        contract_path=contract,
        python_executable=sys.executable,
        services={},
    )

    assert evidence["status"] == "fail"
    assert "live_module_set_mismatch" in evidence["errors"]


def test_runtime_evidence_atomic_write_replaces_complete_json(tmp_path):
    output = tmp_path / "evidence.json"
    output.write_text("old", encoding="utf-8")

    atomic_write(output, {"schema_version": "test", "status": "ok"})

    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "ok"
    assert not list(tmp_path.glob("*.tmp"))
