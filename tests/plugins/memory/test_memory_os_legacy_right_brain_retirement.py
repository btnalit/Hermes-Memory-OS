import json
import shutil
import stat
import threading
import time
from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os import legacy_right_brain_retirement as retirement_module

from plugins.memory.memory_os.legacy_right_brain_retirement import (
    LEGACY_CRON_NAMES,
    archived_legacy_artifact_path,
    legacy_right_brain_is_retired,
    load_retirement_manifest,
    retire_legacy_right_brain,
    retirement_manifest_path,
    retirement_status,
)


def _write_fixture(home, *, enabled_cron=False, legacy_enabled=False):
    config = home / "memory-os" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"right_brain_expression": {"legacy_cognitive_loop_enabled": legacy_enabled}}) + "\n",
        encoding="utf-8",
    )
    jobs = home / "cron" / "jobs.json"
    jobs.parent.mkdir(parents=True)
    jobs.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": f"job-{index}",
                        "name": name,
                        "enabled": enabled_cron,
                        "state": "scheduled" if enabled_cron else "paused",
                        "schedule": {"expr": "30 4 * * 0"},
                        "script": f"{name}.py",
                        "deliver": "local",
                    }
                    for index, name in enumerate(LEGACY_CRON_NAMES)
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    root = home / "system-modules" / "wandering_mind"
    root.mkdir(parents=True)
    (root / "outputs.jsonl").write_text(
        json.dumps({"id": "wout_1", "output": "PRIVATE_LEGACY_BODY"}) + "\n",
        encoding="utf-8",
    )
    (root / "state.json").write_text(json.dumps({"generated_count": 1}) + "\n", encoding="utf-8")
    for module_name in (
        "grounded_expression_judge",
        "expression_draft",
        "speak_gate",
        "right_brain_expression_adapter",
        "speak_permission",
    ):
        module_root = home / "system-modules" / module_name
        module_root.mkdir(parents=True)
        (module_root / "history.jsonl").write_text(
            json.dumps({"module": module_name, "body": "PRIVATE_LEGACY_BODY"}) + "\n",
            encoding="utf-8",
        )
    deep_root = home / "system-modules" / "deep_reflection"
    deep_root.mkdir(parents=True)
    (deep_root / "wandering_seeds.jsonl").write_text(
        json.dumps({"seed_id": "old-seed", "seed_text": "PRIVATE_LEGACY_BODY"}) + "\n",
        encoding="utf-8",
    )
    speak_tickets = home / "memory-os" / "system" / "speak_permission_tickets.jsonl"
    speak_tickets.parent.mkdir(parents=True, exist_ok=True)
    speak_tickets.write_text(
        json.dumps({"ticket_id": "old-ticket", "actual_send": False}) + "\n",
        encoding="utf-8",
    )


def test_retirement_dry_run_is_bounded_and_does_not_mutate(tmp_path):
    _write_fixture(tmp_path)

    report = retire_legacy_right_brain(
        tmp_path,
        apply=False,
        now=datetime(2026, 7, 14, 3, 0, tzinfo=timezone.utc),
    )

    assert report["status"] == "dry_run"
    assert report["plan"]["archived_jsonl_record_count"] == 8
    assert report["plan"]["raw_body_included"] is False
    assert "PRIVATE_LEGACY_BODY" not in json.dumps(report)
    assert (tmp_path / "system-modules" / "wandering_mind" / "outputs.jsonl").is_file()
    assert not (tmp_path / "memory-os" / "system" / "legacy_right_brain_retirement.json").exists()


def test_retirement_moves_history_to_read_only_archive_and_is_idempotent(tmp_path):
    _write_fixture(tmp_path)

    report = retire_legacy_right_brain(
        tmp_path,
        apply=True,
        now=datetime(2026, 7, 14, 3, 0, tzinfo=timezone.utc),
    )

    assert report["status"] == "retired"
    assert report["retirement"]["status"] == "ok"
    assert legacy_right_brain_is_retired(tmp_path) is True
    assert not (tmp_path / "system-modules" / "wandering_mind").exists()
    for module_name in (
        "grounded_expression_judge",
        "expression_draft",
        "speak_gate",
        "right_brain_expression_adapter",
        "speak_permission",
    ):
        assert not (tmp_path / "system-modules" / module_name).exists()
    assert not (tmp_path / "system-modules" / "deep_reflection" / "wandering_seeds.jsonl").exists()
    assert not (tmp_path / "memory-os" / "system" / "speak_permission_tickets.jsonl").exists()
    manifest = load_retirement_manifest(tmp_path)
    assert manifest["active_observation"] is False
    assert manifest["active_execution"] is False
    assert manifest["raw_body_included"] is False
    assert "PRIVATE_LEGACY_BODY" not in json.dumps(manifest)
    archive = tmp_path / manifest["archive_relative_path"]
    archived_output = archive / "system-modules" / "wandering_mind" / "outputs.jsonl"
    assert archived_output.read_text(encoding="utf-8").find("PRIVATE_LEGACY_BODY") >= 0
    assert archived_output.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    assert (
        archived_legacy_artifact_path(tmp_path, "system-modules/wandering_mind/outputs.jsonl")
        == archived_output
    )
    assert archived_legacy_artifact_path(tmp_path, "../../etc/passwd") is None
    config = json.loads((tmp_path / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert config["right_brain_expression"]["legacy_cognitive_loop_enabled"] is False
    assert config["right_brain_expression"]["recurring_delivery_enabled"] is False
    assert config["right_brain_expression"]["recurring_delivery_mode"] == "disabled"

    duplicate = retire_legacy_right_brain(tmp_path, apply=True)
    assert duplicate["status"] == "already_retired"
    assert duplicate["retirement"]["status"] == "ok"


def test_retired_manifest_permission_crash_window_recovers(tmp_path):
    _write_fixture(tmp_path)
    retire_legacy_right_brain(tmp_path, apply=True)
    manifest = retirement_manifest_path(tmp_path)
    manifest.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert retirement_status(tmp_path)["violations"] == ["retirement_manifest_writable"]
    recovered = retire_legacy_right_brain(tmp_path, apply=True)

    assert recovered["status"] == "retired_recovered"
    assert recovered["retirement"]["status"] == "ok"
    assert manifest.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0


def test_retirement_status_fails_closed_if_live_lane_reappears(tmp_path):
    _write_fixture(tmp_path)
    retire_legacy_right_brain(tmp_path, apply=True)
    live = tmp_path / "system-modules" / "wandering_mind"
    live.mkdir(parents=True)
    (live / "outputs.jsonl").write_text('{"id":"post-cutoff"}\n', encoding="utf-8")

    status = retirement_status(tmp_path)

    assert status["status"] == "error"
    assert status["post_cutoff_jsonl_record_count"] == 1
    assert "legacy_source_recreated" in status["violations"]
    assert status["raw_body_included"] is False


def test_pending_retirement_recovers_after_atomic_archive_move(tmp_path):
    _write_fixture(tmp_path)
    dry = retire_legacy_right_brain(
        tmp_path,
        apply=False,
        now=datetime(2026, 7, 14, 4, 0, tzinfo=timezone.utc),
    )
    pending = dict(dry["plan"])
    pending["lifecycle"] = "retirement_pending"
    archive = tmp_path / pending["archive_relative_path"]
    first_target = archive / "system-modules" / "wandering_mind"
    first_target.parent.mkdir(parents=True)
    (tmp_path / "system-modules" / "wandering_mind").rename(first_target)
    manifest = tmp_path / "memory-os" / "system" / "legacy_right_brain_retirement.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(pending) + "\n", encoding="utf-8")
    assert legacy_right_brain_is_retired(tmp_path) is True
    pending_status = retirement_status(tmp_path)
    assert pending_status["status"] == "error"
    assert "retirement_pending_incomplete" in pending_status["violations"]

    result = retire_legacy_right_brain(tmp_path, apply=True)

    assert result["status"] == "retired_recovered"
    assert result["retirement"]["status"] == "ok"
    assert legacy_right_brain_is_retired(tmp_path) is True


@pytest.mark.parametrize("legacy_enabled,enabled_cron", [(True, False), (False, True)])
def test_retirement_refuses_live_execution_prerequisites(tmp_path, legacy_enabled, enabled_cron):
    _write_fixture(tmp_path, legacy_enabled=legacy_enabled, enabled_cron=enabled_cron)

    with pytest.raises(RuntimeError):
        retire_legacy_right_brain(tmp_path, apply=True)

    assert (tmp_path / "system-modules" / "wandering_mind" / "outputs.jsonl").is_file()


def test_malformed_retired_manifest_is_error_and_cannot_bypass_live_config(tmp_path):
    _write_fixture(tmp_path, legacy_enabled=True)
    manifest = tmp_path / "memory-os" / "system" / "legacy_right_brain_retirement.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"lifecycle":"retired"}\n', encoding="utf-8")

    status = retirement_status(tmp_path)

    assert status["status"] == "error"
    assert "retirement_manifest_invalid" in status["violations"]
    assert legacy_right_brain_is_retired(tmp_path) is True
    with pytest.raises(RuntimeError, match="invalid existing retirement manifest"):
        retire_legacy_right_brain(tmp_path, apply=True)
    assert (tmp_path / "system-modules" / "wandering_mind" / "outputs.jsonl").is_file()


@pytest.mark.parametrize(
    "body",
    [
        "{not-json\n",
        json.dumps({"lifecycle": "active"}) + "\n",
        json.dumps({"lifecycle": "cancelled"}) + "\n",
        json.dumps({"lifecycle": "retired", "archived_file_count": "not-an-int"}) + "\n",
    ],
)
def test_any_invalid_retirement_marker_fails_execution_closed_and_reports_error(tmp_path, body):
    _write_fixture(tmp_path, legacy_enabled=True)
    manifest = retirement_manifest_path(tmp_path)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(body, encoding="utf-8")

    assert legacy_right_brain_is_retired(tmp_path) is True
    status = retirement_status(tmp_path)
    assert status["status"] == "error"
    assert "retirement_manifest_invalid" in status["violations"]


def test_retirement_rejects_dangling_top_level_legacy_symlink(tmp_path):
    _write_fixture(tmp_path)
    legacy = tmp_path / "system-modules" / "expression_draft"
    shutil.rmtree(legacy)
    legacy.symlink_to(tmp_path / "missing-expression-draft", target_is_directory=True)

    with pytest.raises(RuntimeError, match="symlink is not allowed"):
        retire_legacy_right_brain(tmp_path, apply=True)

    assert legacy.is_symlink()
    assert not retirement_manifest_path(tmp_path).exists()


def test_pending_recovery_rejects_tampered_archive_metadata(tmp_path):
    _write_fixture(tmp_path)
    dry = retire_legacy_right_brain(tmp_path, apply=False)
    pending = dict(dry["plan"])
    pending["lifecycle"] = "retirement_pending"
    files = [dict(record) for record in pending["archived_files"]]
    files[0]["size_bytes"] += 1
    files[0]["jsonl_record_count"] += 1
    pending["archived_files"] = files
    pending["archived_jsonl_record_count"] += 1
    manifest = retirement_manifest_path(tmp_path)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(pending) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="archive integrity failed"):
        retire_legacy_right_brain(tmp_path, apply=True)

    assert load_retirement_manifest(tmp_path)["lifecycle"] == "retirement_pending"


def test_archived_accessor_rejects_writable_or_hash_mismatched_file(tmp_path):
    _write_fixture(tmp_path)
    retire_legacy_right_brain(tmp_path, apply=True)
    manifest = load_retirement_manifest(tmp_path)
    archived = (
        tmp_path
        / manifest["archive_relative_path"]
        / "system-modules"
        / "wandering_mind"
        / "outputs.jsonl"
    )

    archived.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert archived_legacy_artifact_path(tmp_path, "system-modules/wandering_mind/outputs.jsonl") is None

    archived.write_text('{"id":"tampered"}\n', encoding="utf-8")
    archived.chmod(stat.S_IRUSR)
    assert archived_legacy_artifact_path(tmp_path, "system-modules/wandering_mind/outputs.jsonl") is None


def test_pending_recovery_rejects_archive_path_outside_fixed_prefix(tmp_path):
    _write_fixture(tmp_path)
    dry = retire_legacy_right_brain(
        tmp_path,
        apply=False,
        now=datetime(2026, 7, 14, 4, 0, tzinfo=timezone.utc),
    )
    pending = dict(dry["plan"])
    pending["lifecycle"] = "retirement_pending"
    pending["archive_relative_path"] = "attacker-selected"
    manifest = tmp_path / "memory-os" / "system" / "legacy_right_brain_retirement.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(pending) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid pending retirement manifest"):
        retire_legacy_right_brain(tmp_path, apply=True)

    assert (tmp_path / "system-modules" / "wandering_mind" / "outputs.jsonl").is_file()
    assert not (tmp_path / "attacker-selected").exists()


def test_retirement_waits_for_shared_legacy_reader_lock(tmp_path):
    _write_fixture(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    result = {}

    def hold_reader():
        with retirement_module.legacy_right_brain_read_lock(tmp_path):
            entered.set()
            assert release.wait(timeout=5)

    def apply_retirement():
        result.update(retire_legacy_right_brain(tmp_path, apply=True))

    reader = threading.Thread(target=hold_reader)
    reader.start()
    assert entered.wait(timeout=2)
    writer = threading.Thread(target=apply_retirement)
    writer.start()
    time.sleep(0.1)
    assert writer.is_alive()
    assert not (tmp_path / "memory-os" / "system" / "legacy_right_brain_retirement.json").exists()
    release.set()
    reader.join(timeout=5)
    writer.join(timeout=5)

    assert not reader.is_alive()
    assert not writer.is_alive()
    assert result["status"] == "retired"


def test_retirement_refuses_enabled_raw_script_alias_cron(tmp_path):
    _write_fixture(tmp_path)
    jobs = tmp_path / "cron" / "jobs.json"
    jobs.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "alias",
                        "name": "renamed-expression",
                        "enabled": True,
                        "script": "memory_os_right_brain_expression.py",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="legacy cron jobs must be paused"):
        retire_legacy_right_brain(tmp_path, apply=True)

    assert not retirement_manifest_path(tmp_path).exists()


def test_retirement_refuses_malformed_cron_registry(tmp_path):
    _write_fixture(tmp_path)
    jobs = tmp_path / "cron" / "jobs.json"
    jobs.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid legacy cron registry"):
        retire_legacy_right_brain(tmp_path, apply=True)

    assert (tmp_path / "system-modules" / "wandering_mind" / "outputs.jsonl").is_file()
    assert not retirement_manifest_path(tmp_path).exists()
