import json
import subprocess
import sys
from pathlib import Path

from scripts.memory_os_upgrade_evidence_compare import compare_evidence, render_summary


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_upgrade_compare_passes_when_post_has_no_new_failures():
    pre = _compat_report(version="Hermes Agent v0.14.0", warn=["hermes_version_unavailable"])
    post = _compat_report(version="Hermes Agent v0.15.2", warn=["hermes_version_unavailable"])
    pre_monitor = _monitor_report(status="PASS")
    post_monitor = _monitor_report(status="PASS")

    report = compare_evidence(
        pre_compat=pre,
        post_compat=post,
        pre_monitor=pre_monitor,
        post_monitor=post_monitor,
    )

    assert report["schema_version"] == "memory-os.hermes_upgrade_evidence_compare.v0"
    assert report["classification"]["status"] == "PASS"
    assert report["hermes_version"]["changed"] is True
    assert "compat_no_post_fail" in render_summary(report)


def test_upgrade_compare_fails_on_post_compat_failure():
    pre = _compat_report(version="Hermes Agent v0.14.0")
    post = _compat_report(version="Hermes Agent v0.15.2", fail=["memory_provider_not_memory_os"])

    report = compare_evidence(pre_compat=pre, post_compat=post)

    assert report["classification"]["status"] == "FAIL"
    assert report["compat"]["post_fail_codes"] == ["memory_provider_not_memory_os"]


def test_upgrade_compare_warns_when_monitor_evidence_is_missing():
    report = compare_evidence(
        pre_compat=_compat_report(version="Hermes Agent v0.14.0"),
        post_compat=_compat_report(version="Hermes Agent v0.15.2"),
    )

    assert report["classification"]["status"] == "WARN"
    assert any(item["code"] == "monitor_evidence_missing" for item in report["classification"]["warn"])


def test_upgrade_compare_cli_reads_files(tmp_path):
    pre = tmp_path / "pre.json"
    post = tmp_path / "post.json"
    pre.write_text(json.dumps(_compat_report(version="Hermes Agent v0.14.0")), encoding="utf-8")
    post.write_text(json.dumps(_compat_report(version="Hermes Agent v0.15.2")), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/memory_os_upgrade_evidence_compare.py",
            "--pre-compat",
            str(pre),
            "--post-compat",
            str(post),
            "--output",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert report["schema_version"] == "memory-os.hermes_upgrade_evidence_compare.v0"
    assert report["compat"]["provided"] is True


def _compat_report(*, version: str, warn=None, fail=None):
    return {
        "schema_version": "memory-os.hermes_upgrade_compat.v0",
        "commands": {
            "hermes_version": {
                "stdout_preview": version,
                "stderr_preview": "",
            }
        },
        "classification": {
            "pass": [{"code": "memory_provider_active"}],
            "warn": [{"code": code} for code in (warn or [])],
            "fail": [{"code": code} for code in (fail or [])],
        },
    }


def _monitor_report(*, status: str, warn=None, fail=None):
    return {
        "classification": {
            "status": status,
            "pass": [],
            "warn": [{"code": code} for code in (warn or [])],
            "fail": [{"code": code} for code in (fail or [])],
        }
    }
