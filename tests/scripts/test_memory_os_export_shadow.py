import json
import subprocess
import sys
from pathlib import Path

from plugins.memory.memory_os.fixtures import build_sannai_multi_root_fixture
from plugins.memory.memory_os.migrator import scan_legacy_sources


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_export_shadow_script_dry_run_is_read_only(tmp_path):
    layout = build_sannai_multi_root_fixture(tmp_path)
    before_hashes = {source["path"]: source["sha256"] for source in scan_legacy_sources(layout.roots)}
    out = tmp_path / "bundle"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/memory_os_export_shadow.py",
            "--profile",
            "sannai",
            "--hermes-home",
            str(layout.hermes_home),
            "--state-root",
            str(layout.state_root),
            "--out",
            str(out),
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert report["dry_run"] is True
    assert report["candidate_status_counts"]["owner_eligible"] == 1
    assert not out.exists()
    after_hashes = {source["path"]: source["sha256"] for source in scan_legacy_sources(layout.roots)}
    assert after_hashes == before_hashes


def test_export_shadow_script_writes_bundle_with_private_bodies_when_requested(tmp_path):
    layout = build_sannai_multi_root_fixture(tmp_path)
    out = tmp_path / "bundle"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/memory_os_export_shadow.py",
            "--profile",
            "sannai",
            "--hermes-home",
            str(layout.hermes_home),
            "--state-root",
            str(layout.state_root),
            "--out",
            str(out),
            "--include-private-bodies",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert report["dry_run"] is False
    assert (out / "manifest.json").exists()
    assert (out / "source" / "profile" / "SOUL.md").exists()
