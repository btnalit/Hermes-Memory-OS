import argparse
import json
import importlib
import sys
from datetime import datetime, timedelta, timezone

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.cli import _ensure_system_module_runtime_path
from plugins.memory.memory_os.__main__ import main as memory_os_module_main
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def test_modules_status_reports_commandized_and_uncommandized_modules(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(_parse_memory_os_args(["modules", "status"]))

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    modules = {item["module"]: item for item in output["modules"]}
    assert output["schema_version"] == "memory-os.modules_status.v0"
    assert output["profile"] == "default"
    assert modules["cron_mirror"]["commandized"] is True
    assert modules["deep_reflection"]["commandized"] is True
    assert modules["inner_drive"]["commandized"] is False
    assert modules["inner_drive"]["unavailable_reason"]
    assert "raw_body" not in json.dumps(output)


def test_modules_status_inner_drive_includes_runtime_heartbeat_authority(tmp_path, monkeypatch, capsys):
    store = _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    heartbeat_root = store.roots.memory_os_root / "runtime"
    heartbeat_root.mkdir(parents=True)
    (heartbeat_root / "heartbeat_state.json").write_text(
        json.dumps(
            {
                "last_heartbeat_at": "2026-05-25T03:00:00Z",
                "last_attempt_at": "2026-05-25T03:00:00Z",
                "processed_event_count": 221,
                "last_processed_event_id": "event_221",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = memory_os_command(_parse_memory_os_args(["modules", "status"]))

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    modules = {item["module"]: item for item in output["modules"]}
    runtime = modules["inner_drive"]["status"]["runtime_heartbeat"]
    assert runtime["schema_version"] == "memory-os.heartbeat_runtime_status.v0"
    assert runtime["exists"] is True
    assert runtime["processed_event_count"] == 221
    assert runtime["last_processed_event_id"] == "event_221"


def test_review_proposal_followups_ops_gate_error_returns_nonzero(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(
        _parse_memory_os_args(
            ["review", "proposal-followups", "--proposal-id", "does_not_exist", "--ops-gate"]
        )
    )

    assert result == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error"
    assert output["reason"] == "proposal_not_found"


def test_memory_os_module_main_exposes_provider_cli_without_hermes_command(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_module_main(["status"])

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "memory-os.status.v0"


def test_modules_doctor_returns_ok_for_warning_only_uncommandized_modules(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(_parse_memory_os_args(["modules", "doctor"]))

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "memory-os.modules_doctor.v0"
    assert output["status"] in {"ok", "warning"}
    assert not any(finding["severity"] == "error" for finding in output["findings"])


def test_modules_doctor_injects_self_evolution_dependencies(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(_parse_memory_os_args(["modules", "doctor"]))

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    self_evolution = next(item for item in output["modules"] if item["module"] == "self_evolution")
    assert self_evolution["doctor"]["schema_version"] == "hermes.self_evolution_doctor.v0"
    assert not any(
        finding.get("code") == "missing_required_runtime_dependency"
        for finding in self_evolution["doctor"].get("findings", [])
    )
    assert not any(
        finding.get("module") == "self_evolution"
        and finding.get("code") == "missing_required_runtime_dependency"
        for finding in output["findings"]
    )


def test_modules_run_once_cron_mirror_defaults_to_dry_run(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(_parse_memory_os_args(["modules", "run-once", "--module", "cron_mirror"]))

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["module"] == "cron_mirror"
    assert output["dry_run"] is True
    assert output["new_event_count"] == 0


def test_modules_run_once_rejects_uncommandized_apply(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(
        _parse_memory_os_args(["modules", "run-once", "--module", "inner_drive", "--apply"])
    )

    assert result == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error"
    assert output["code"] == "module_not_commandized"
    assert output["module"] == "inner_drive"


def test_modules_validate_no_send_reports_hard_boundaries(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(_parse_memory_os_args(["modules", "validate-no-send"]))

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "memory-os.modules_no_send_validation.v0"
    assert output["status"] == "ok"
    assert output["boundaries"] == {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_crystallized_approval": False,
        "hindsight_exported": False,
    }


def test_modules_deep_reflection_preview_current_reports_bounded_card(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    injection_root = tmp_path / "system-modules" / "deep_reflection" / "injection"
    injection_root.mkdir(parents=True)
    (injection_root / "current.json").write_text(
        json.dumps(
            {
                "selected_cards": [
                    {
                        "card_id": "card_1",
                        "source_class": "working",
                        "body": "保持当前 ComfyUI 任务焦点。",
                        "source_refs": ["event:private_should_not_expand"],
                    }
                ],
                "selected_by_source_class": {"working": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = memory_os_command(
        _parse_memory_os_args(["modules", "deep_reflection", "preview-current"])
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "hermes.deep_reflection_preview.v0"
    assert output["status"] == "ok"
    assert output["selected_injection_count"] == 1
    assert output["actual_send"] is False
    assert output["actual_execute"] is False


def test_modules_deep_reflection_preview_ensures_installed_runtime_path(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    calls: list[str] = []

    def fake_ensure_runtime_path(hermes_home):
        calls.append(str(hermes_home))

    monkeypatch.setitem(
        memory_os_command.__globals__,
        "_ensure_system_module_runtime_path",
        fake_ensure_runtime_path,
    )

    result = memory_os_command(
        _parse_memory_os_args(["modules", "deep_reflection", "preview-current"])
    )

    assert result == 0
    assert calls == [str(tmp_path.resolve())]


def test_modules_deep_reflection_history_filters_by_days(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    history_path = tmp_path / "system-modules" / "deep_reflection" / "injection" / "history.jsonl"
    history_path.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    records = [
        {"ts": (now - timedelta(days=9)).isoformat(), "selected_cards": [{"card_id": "old"}]},
        {"ts": (now - timedelta(days=1)).isoformat(), "selected_cards": [{"card_id": "recent"}]},
    ]
    history_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    result = memory_os_command(
        _parse_memory_os_args(["modules", "deep_reflection", "history", "--days", "7"])
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "hermes.deep_reflection_history.v0"
    assert output["record_count"] == 1
    assert output["records"][0]["selected_cards"][0]["card_id"] == "recent"


def test_validate_no_send_writes_bounded_host_validation_report(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(
        _parse_memory_os_args(["validate", "--no-send", "--write-report"])
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "memory-os.host_validation.v0"
    assert output["status"] in {"ok", "warning"}
    assert output["report_written"] is True
    assert output["boundaries"]["actual_send"] is False
    assert output["boundaries"]["actual_execute"] is False
    assert output["boundaries"]["actual_crystallized_approval"] is False
    report_path = tmp_path / output["report_path"]
    assert report_path.is_file()
    report_text = report_path.read_text(encoding="utf-8")
    assert '"raw_body"' not in report_text
    assert '"private_body"' not in report_text


def test_installed_cli_adds_system_module_runtime_path(tmp_path, monkeypatch):
    runtime_python = tmp_path / "memory-os" / "runtime" / "python"
    runtime_python.mkdir(parents=True)
    monkeypatch.setattr("sys.path", [path for path in __import__("sys").path if path != str(runtime_python)])

    _ensure_system_module_runtime_path(tmp_path)

    assert __import__("sys").path[0] == str(runtime_python)


def test_installed_cli_extends_loaded_plugins_package_path(tmp_path, monkeypatch):
    runtime_python = tmp_path / "memory-os" / "runtime" / "python"
    runtime_plugins = runtime_python / "plugins"
    runtime_memory_plugins = runtime_plugins / "memory"
    runtime_plugins.mkdir(parents=True)
    runtime_memory_plugins.mkdir()
    plugins_package = importlib.import_module("plugins")
    memory_package = importlib.import_module("plugins.memory")
    original_path = list(plugins_package.__path__)
    original_memory_path = list(memory_package.__path__)
    monkeypatch.setattr(plugins_package, "__path__", original_path.copy())
    monkeypatch.setattr(memory_package, "__path__", original_memory_path.copy())

    _ensure_system_module_runtime_path(tmp_path)

    assert str(runtime_plugins) in plugins_package.__path__
    assert str(runtime_memory_plugins) in memory_package.__path__


def _parse_memory_os_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    register_cli(parser)
    return parser.parse_args(argv)


def _init_store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    return store
