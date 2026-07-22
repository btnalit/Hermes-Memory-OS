import json
import subprocess
import sys
from pathlib import Path

from scripts.memory_os_public_checkout_probe import run_probe


REPO_ROOT = Path(__file__).resolve().parents[2]
IMPORT_SMOKE_TARGETS = {
    "plugins.memory.memory_os.owner_actions",
    "plugins.memory.memory_os.session_mirror",
    "plugins.memory.memory_os.execution_gate",
    "scripts.memory_os_host_profile",
    "scripts.memory_os_3_200_monitor",
    "scripts.memory_os_monitor",
}


def test_working_tree_public_checkout_candidate_is_complete_and_public_safe():
    report = run_probe(REPO_ROOT, source="working-tree")

    assert report["schema_version"] == "memory-os.public_checkout_probe.v1"
    assert report["classification"]["status"] == "PASS"
    assert report["public_docs"] == [
        "LEGACY_RIGHT_BRAIN_RETIREMENT.md",
        "README.md",
        "V3_INNER_LIFE_RUNBOOK.md",
        "configuration.md",
        "quickstart.md",
    ]
    assert report["internal_docs_visible"] is False
    assert report["private_docs_present"] == []
    assert report["required_public_files"]["eval/memory_os/adapters/retrieval_shadow.py"] is True
    assert report["required_public_files"]["tests/eval/test_memory_os_retrieval_shadow.py"] is True
    assert report["required_public_files"]["scripts/memory_os_host_profile.py"] is True
    assert set(report["import_smoke_targets"]) == IMPORT_SMOKE_TARGETS
    assert report["import_smoke_ok"] is True
    assert report["import_smoke_failures"] == []
    assert any(item["code"] == "import_smoke_ok" for item in report["classification"]["pass"])


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

    assert report["schema_version"] == "memory-os.public_checkout_probe.v1"
    assert report["source"] == "head"
    assert report["public_docs_ok"] is True
    assert report["internal_docs_visible"] is False
    assert report["private_docs_present"] == []
    assert set(report["import_smoke_targets"]) == IMPORT_SMOKE_TARGETS
    assert isinstance(report["import_smoke_failures"], list)
    if report["import_smoke_ok"] is False:
        assert any(item["code"] == "import_smoke_failed" for item in report["classification"]["fail"])
    assert report["classification"]["status"] in {"PASS", "FAIL"}
    if report["classification"]["status"] == "FAIL":
        missing = set(report["missing_required_public_files"])
        assert missing or report["import_smoke_ok"] is False
