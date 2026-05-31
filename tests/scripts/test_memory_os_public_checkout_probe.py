import json
import subprocess
import sys
from pathlib import Path

from scripts.memory_os_public_checkout_probe import run_probe


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_working_tree_public_checkout_candidate_is_complete_and_public_safe():
    report = run_probe(REPO_ROOT, source="working-tree")

    assert report["schema_version"] == "memory-os.public_checkout_probe.v0"
    assert report["classification"]["status"] == "PASS"
    assert report["public_docs"] == ["README.md", "configuration.md", "quickstart.md"]
    assert report["internal_docs_visible"] is False
    assert report["private_docs_present"] == []
    assert report["required_public_files"]["eval/memory_os/adapters/retrieval_shadow.py"] is True
    assert report["required_public_files"]["tests/eval/test_memory_os_retrieval_shadow.py"] is True


def test_head_public_checkout_probe_reports_structured_release_drift():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/memory_os_public_checkout_probe.py",
            "--source",
            "head",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    report = json.loads(result.stdout)

    assert report["schema_version"] == "memory-os.public_checkout_probe.v0"
    assert report["source"] == "head"
    assert report["public_docs_ok"] is True
    assert report["internal_docs_visible"] is False
    assert report["private_docs_present"] == []
    assert report["classification"]["status"] in {"PASS", "FAIL"}
    if report["classification"]["status"] == "FAIL":
        missing = set(report["missing_required_public_files"])
        assert "eval/memory_os/adapters/retrieval_shadow.py" in missing
