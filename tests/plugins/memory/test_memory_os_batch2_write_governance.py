"""Batch-2 upper-layer write-governance regression tests."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import plugins.modules.governance.fact_judge as fact_judge
import plugins.modules.governance.provisional_sweep as provisional_sweep
import plugins.memory.memory_os.session_mirror as session_mirror
from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES_ROOT = REPO_ROOT / "plugins" / "modules"


def _function_source(fn) -> str:
    return inspect.getsource(fn)


def test_module_layer_append_jsonl_helpers_use_locked_jsonl_io() -> None:
    offenders: list[str] = []
    for path in sorted(MODULES_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_append_jsonl":
                src = ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
                if "append_jsonl_locked" not in src:
                    offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_session_mirror_append_jsonl_uses_locked_io() -> None:
    src = _function_source(session_mirror._append_jsonl)
    assert "append_jsonl_locked" in src
    assert ".open(" not in src


def test_provisional_sweep_writes_are_locked_or_atomic() -> None:
    src = _function_source(provisional_sweep.ProvisionalSweepModule.run_once)
    assert "append_jsonl_locked(self.runs_path" in src
    assert "write_json_atomic(" in src
    assert ".open(\"a\"" not in src
    assert ".write_text(" not in src


def test_fact_judge_declares_manifest_and_locked_verdict_writes() -> None:
    manifest = fact_judge.fact_judge_manifest()
    assert "fact_judge" in manifest["name"]
    assert "candidate_aggregation" in manifest["provides"]["consumed_by"]
    assert "fact_judge" in manifest["provides"]["schedules"]
    src = _function_source(fact_judge._append_verdict)
    assert "append_jsonl_locked" in src
    assert ".open(" not in src


def test_max_expiring_in_digest_is_owner_overridable() -> None:
    spec = OVERRIDABLE_KNOBS["max_expiring_in_digest"]
    assert spec["module"] == "owner_review_digest"
    assert spec["bounds"] == [1, 25]
    assert spec["meta"] is False
