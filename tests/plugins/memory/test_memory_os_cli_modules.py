import argparse
import json
import importlib
from datetime import datetime, timedelta, timezone

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.cli import _check_vector_available, _ensure_system_module_runtime_path


def test_vector_availability_probe_never_contaminates_structured_stdout(monkeypatch, capsys):
    import importlib.util as importlib_util

    from plugins.memory.memory_os import cli as cli_module

    def noisy_spec_lookup(_name, *args, **kwargs):
        print("optional dependency probe noise")
        raise ValueError("broken spec lookup")

    monkeypatch.setattr(cli_module, "_vector_available_cache", None)
    monkeypatch.setattr(importlib_util, "find_spec", noisy_spec_lookup)

    assert _check_vector_available() is False
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_vector_probe_never_executes_the_vector_stack(monkeypatch):
    """Backlog 11: importing sentence_transformers executes torch and cost a
    measured 17-29s per CLI status/doctor call, multiplied by
    shell_alias_no_env's 22 concurrent CLI probes (backlog 3's suspected
    production flake). The probe must answer "installed?" from spec metadata
    without EXECUTING the package.

    Counterfactual: the old importlib.import_module probe trips the exploding
    loader below (AssertionError, uncaught by its except ImportError) -- the
    17-29s import cost made observable; the spec lookup sees the module
    exists and never runs it.
    """
    import importlib.machinery
    import sys

    from plugins.memory.memory_os import cli as cli_module

    class _ExplodingLoader:
        def create_module(self, spec):
            raise AssertionError(f"vector probe executed {spec.name}")

        def exec_module(self, module):
            raise AssertionError(f"vector probe executed {module}")

    class _ExplodingFinder:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in {"sentence_transformers", "torch"}:
                return importlib.machinery.ModuleSpec(fullname, _ExplodingLoader())
            return None

    for name in list(sys.modules):
        if name.split(".")[0] in {"sentence_transformers", "torch"}:
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(cli_module, "_vector_available_cache", None)
    finder = _ExplodingFinder()
    sys.meta_path.insert(0, finder)
    try:
        assert cli_module._check_vector_available() is True
    finally:
        sys.meta_path.remove(finder)


def test_vector_probe_result_is_cached_per_process(monkeypatch):
    import importlib.util as importlib_util

    from plugins.memory.memory_os import cli as cli_module

    calls: list[str] = []

    def counting_find_spec(name, *args, **kwargs):
        calls.append(name)
        return None

    monkeypatch.setattr(cli_module, "_vector_available_cache", None)
    monkeypatch.setattr(importlib_util, "find_spec", counting_find_spec)

    assert cli_module._check_vector_available() is False
    assert cli_module._check_vector_available() is False
    assert calls == ["sentence_transformers"]
from plugins.memory.memory_os.__main__ import main as memory_os_module_main
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

import pytest

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


def test_modules_status_reports_commandized_and_uncommandized_modules(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(_parse_memory_os_args(["modules", "status"]))

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    modules = {item["module"]: item for item in output["modules"]}
    assert output["schema_version"] == "memory-os.modules_status.v0"
    assert output["profile"] == "default"
    assert output["operational_truth"]["schema_version"] == "memory-os.operational_truth_snapshot.v1"
    assert modules["cron_mirror"]["commandized"] is True
    assert modules["deep_reflection"]["commandized"] is True
    assert modules["inner_drive"]["commandized"] is False
    assert modules["imagination_loop"]["status_available"] is True
    assert modules["imagination_loop"]["commandized"] is False
    assert modules["confabulation_detector"]["status_available"] is True
    assert modules["confabulation_detector"]["commandized"] is False
    assert modules["ground_truth_miner"]["status_available"] is True
    assert modules["ground_truth_miner"]["commandized"] is False
    assert modules["confidence_router"]["status_available"] is True
    assert modules["confidence_router"]["commandized"] is False
    assert modules["crystallized_revalidator"]["status_available"] is True
    assert modules["crystallized_revalidator"]["commandized"] is False
    assert modules["judge_calibration"]["status_available"] is True
    assert modules["candidate_review"]["status_available"] is True
    assert modules["shadow_recall"]["status_available"] is True
    assert modules["provisional"]["status_available"] is True
    assert modules["cascade_routing_policy"]["status_available"] is True
    assert modules["migration_controller"]["status_available"] is True
    assert modules["symbolic_offloader"]["status_available"] is True
    assert modules["symbolic_offloader"]["commandized"] is False
    assert modules["abstraction_distillation"]["status_available"] is True
    assert modules["grounded_expression_judge"]["status_available"] is True
    assert modules["grounded_expression_judge"]["commandized"] is False
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


def _seed_provisional(store, *, candidate_id, file_name):
    from datetime import datetime, timezone, timedelta
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService

    now = datetime.now(timezone.utc)
    svc = CrystallizedMemoryService(store)
    candidate = CrystallizedCandidate(candidate_id, "fact", f"Durable fact {candidate_id}.", [f"evt_{candidate_id}"])
    decision = ApprovalDecision(
        candidate_id, ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
        (now - timedelta(days=10)).isoformat(), provisional=True,
        expires_at=(now + timedelta(days=30)).isoformat(),
    )
    svc.write_approved_record(candidate, decision, file_name=file_name)
    return svc.read_records(file_name)[0].frontmatter["id"]


def test_permanent_cli_propose_approve_end_to_end(tmp_path, monkeypatch, capsys):
    store = _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    record_id = _seed_provisional(store, candidate_id="cand_cli_ok", file_name="cli_ok.md")

    rc = memory_os_command(_parse_memory_os_args(["permanent", "propose", record_id]))
    assert rc == 0
    proposed = json.loads(capsys.readouterr().out)
    assert proposed["status"] == "open"
    token = proposed["token"]
    assert token.startswith("ppmt_")

    rc = memory_os_command(_parse_memory_os_args(["permanent", "approve", token]))
    assert rc == 0
    approved = json.loads(capsys.readouterr().out)
    assert approved["status"] == "approved"

    # Canonical record is now permanent; raw token never persisted.
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
    fm = CrystallizedMemoryService(store).read_records("cli_ok.md")[0].frontmatter
    assert fm["provisional"] is False
    system = store.roots.memory_os_root / "system"
    proposals_text = (system / "permanent_promotion_proposals.jsonl").read_text(encoding="utf-8")
    tokens_text = (system / "owner_action_tokens.jsonl").read_text(encoding="utf-8")
    assert proposed["proposal_id"] in proposals_text
    assert token not in tokens_text  # only the token hash is stored
    from plugins.memory.memory_os.owner_actions import read_owner_action_records
    owner_actions = read_owner_action_records(store.roots)
    assert owner_actions[-1]["action_type"] == "approve_permanent_promotion"


def test_permanent_cli_reject_returns_success_exit_code(tmp_path, monkeypatch, capsys):
    store = _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    record_id = _seed_provisional(store, candidate_id="cand_cli_reject", file_name="cli_reject.md")

    memory_os_command(_parse_memory_os_args(["permanent", "propose", record_id]))
    token = json.loads(capsys.readouterr().out)["token"]

    rc = memory_os_command(_parse_memory_os_args(["permanent", "reject", token]))
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["status"] == "rejected"
    assert rc == 0  # a successful reject is not a failure exit code
    # Record stays provisional — reject performs no permanent write.
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
    assert CrystallizedMemoryService(store).read_records("cli_reject.md")[0].frontmatter["provisional"] is True


def test_permanent_cli_defer_returns_success_exit_code(tmp_path, monkeypatch, capsys):
    store = _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    record_id = _seed_provisional(store, candidate_id="cand_cli_defer", file_name="cli_defer.md")

    memory_os_command(_parse_memory_os_args(["permanent", "propose", record_id]))
    token = json.loads(capsys.readouterr().out)["token"]

    rc = memory_os_command(_parse_memory_os_args(
        ["permanent", "defer", token, "--until", "2026-08-01T00:00:00Z"]
    ))
    deferred = json.loads(capsys.readouterr().out)
    assert deferred["status"] == "deferred"
    assert deferred["deferred_until"] == "2026-08-01T00:00:00Z"
    assert rc == 0
