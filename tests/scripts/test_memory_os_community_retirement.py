import json
import stat
from pathlib import Path

import pytest

from scripts.memory_os_community_retirement import (
    ARCHIVE_ROOT_RELATIVE_PATH,
    MANIFEST_RELATIVE_PATH,
    build_parser,
    main,
    retire_community,
    retirement_status,
)


def _seed_residue(home: Path) -> None:
    """Create a minimal but representative slice of on-host community residue.

    Two plugin module files (one with a raw append write surface, matching
    the review finding), the community data layout with a roster.jsonl, and
    one leftover cron helper script.
    """

    plugin_dir = home / "plugins" / "memory_os"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "community.py").write_text("# community core\n", encoding="utf-8")
    (plugin_dir / "community_shared.py").write_text(
        "def write(path):\n    with open(path, 'a') as fh:\n        fh.write('x')\n",
        encoding="utf-8",
    )

    community_data = home / "memory-os" / "community"
    (community_data / "charters").mkdir(parents=True)
    (community_data / "shared").mkdir(parents=True)
    (community_data / "roster.jsonl").write_text('{"partner": "a"}\n{"partner": "b"}\n', encoding="utf-8")
    (community_data / "budget.yaml").write_text("enforcement: fail-closed\n", encoding="utf-8")

    scripts_dir = home / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "community_partner_reply.py").write_text("# leftover cron script\n", encoding="utf-8")


def test_status_reports_not_retired_when_no_residue_present(tmp_path):
    report = retirement_status(tmp_path)

    assert report["status"] == "not_retired"
    assert report["lifecycle"] == "active"
    assert report["violations"] == []
    assert report["archived_file_count"] == 0


def test_apply_is_noop_when_no_community_residue_exists(tmp_path):
    """Must not be destructive if $HERMES_HOME has no community residue at all:

    no manifest, no archive directory, applied stays False."""

    report = retire_community(tmp_path, apply=True)

    assert report["status"] == "noop_no_residue"
    assert report["applied"] is False
    assert not (tmp_path / MANIFEST_RELATIVE_PATH).exists()
    assert not (tmp_path / ARCHIVE_ROOT_RELATIVE_PATH).exists()


def test_dry_run_plan_reports_files_without_moving_or_writing_anything(tmp_path):
    _seed_residue(tmp_path)
    community_py = tmp_path / "plugins" / "memory_os" / "community.py"
    roster = tmp_path / "memory-os" / "community" / "roster.jsonl"

    report = retire_community(tmp_path, apply=False)

    assert report["status"] == "dry_run"
    assert report["applied"] is False
    plan = report["plan"]
    assert plan["archived_file_count"] >= 5
    relative_paths = {item["relative_path"] for item in plan["archived_files"]}
    assert "plugins/memory_os/community.py" in relative_paths
    assert "memory-os/community/roster.jsonl" in relative_paths
    # dry-run changes nothing on disk.
    assert community_py.is_file()
    assert roster.is_file()
    assert not (tmp_path / MANIFEST_RELATIVE_PATH).exists()
    assert not (tmp_path / ARCHIVE_ROOT_RELATIVE_PATH).exists()


def test_apply_archives_sources_and_is_idempotent_on_second_run(tmp_path):
    _seed_residue(tmp_path)
    community_py = tmp_path / "plugins" / "memory_os" / "community.py"
    community_data_dir = tmp_path / "memory-os" / "community"

    first = retire_community(tmp_path, apply=True)

    assert first["status"] == "retired"
    assert first["applied"] is True
    # Sources are moved (archived), never deleted outright: they must no
    # longer exist at their original live location.
    assert not community_py.exists()
    assert not community_data_dir.exists()
    manifest = json.loads((tmp_path / MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8"))
    assert manifest["lifecycle"] == "retired"
    archive_root = tmp_path / manifest["archive_relative_path"]
    archived_community_py = archive_root / "plugins" / "memory_os" / "community.py"
    assert archived_community_py.is_file()
    assert archived_community_py.read_text(encoding="utf-8") == "# community core\n"
    # Archive is read-only.
    mode = stat.S_IMODE(archived_community_py.stat().st_mode)
    assert not (mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

    second = retire_community(tmp_path, apply=True)

    assert second["status"] == "already_retired"
    assert second["applied"] is False
    # Re-running must not duplicate or re-move anything.
    assert archived_community_py.read_text(encoding="utf-8") == "# community core\n"

    status = retirement_status(tmp_path)
    assert status["status"] == "ok"
    assert status["violations"] == []


def test_apply_blocked_while_enabled_community_cron_job_present(tmp_path):
    """Counterfactual: without the enabled-cron prerequisite guard, apply
    would silently move community_partner_reply.py out from under a still
    -enabled cron job. This must refuse instead, and must not touch any
    file when it refuses."""

    _seed_residue(tmp_path)
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir(parents=True)
    cron_dir.joinpath("jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {"name": "community-partner-reply", "script": "community_partner_reply.py", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    community_partner_reply = tmp_path / "scripts" / "community_partner_reply.py"

    with pytest.raises(RuntimeError, match="community cron jobs must be paused"):
        retire_community(tmp_path, apply=True)

    assert community_partner_reply.is_file()
    assert not (tmp_path / MANIFEST_RELATIVE_PATH).exists()
    assert not (tmp_path / ARCHIVE_ROOT_RELATIVE_PATH).exists()


def test_status_flags_tampered_archive_as_violation(tmp_path):
    _seed_residue(tmp_path)
    retire_community(tmp_path, apply=True)
    manifest = json.loads((tmp_path / MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8"))
    archive_root = tmp_path / manifest["archive_relative_path"]
    archived_community_py = archive_root / "plugins" / "memory_os" / "community.py"

    archived_community_py.chmod(stat.S_IRUSR | stat.S_IWUSR)
    archived_community_py.write_text("# tampered\n", encoding="utf-8")

    status = retirement_status(tmp_path)

    assert status["status"] == "error"
    assert "archive_hash_mismatch" in status["violations"]


def test_cli_default_mode_without_apply_flag_is_dry_run_and_writes_nothing(tmp_path):
    """Default parameters must never be traps: forgetting --apply must never
    silently archive/move anything."""

    _seed_residue(tmp_path)

    exit_code = main(["--hermes-home", str(tmp_path)])

    assert exit_code == 0
    assert not (tmp_path / MANIFEST_RELATIVE_PATH).exists()
    assert (tmp_path / "plugins" / "memory_os" / "community.py").is_file()


def test_build_parser_apply_and_status_are_mutually_exclusive(tmp_path):
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--hermes-home", str(tmp_path), "--apply", "--status"])
