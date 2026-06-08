from datetime import datetime, timezone

from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.ops_gate import OpsGateModule, ops_gate_manifest
from plugins.system.lifecycle import ModuleLifecycle
from plugins.system.scheduler import ScheduleCoordinator


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_ops_gate_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
    )

    status = lifecycle.install(ops_gate_manifest())
    enabled = lifecycle.enable("ops_gate")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("ops_gate").status == "ok"


def test_ops_gate_report_only_run_writes_decision_report_and_audit(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=1, profile="main")))
    module = OpsGateModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        proposed_actions=[
            {"id": "diag-1", "kind": "diagnostic", "target": "memory_os_status"},
            {"id": "restart-1", "kind": "gateway_restart", "target": "hermes-gateway.service"},
        ],
    )

    assert result["status"] == "warning"
    assert result["execution_mode"] == "report-only"
    assert result["actual_execute"] is False
    assert [decision["decision"] for decision in result["decisions"]] == ["would_allow", "blocked"]
    assert result["decisions"][1]["reason"] == "production_action_blocked"
    reports = module.read_reports()
    assert len(reports) == 1
    assert reports[0]["report_id"] == result["report_id"]
    audit_lines = store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("ops_gate_report_written" in line for line in audit_lines)


def test_ops_gate_skips_without_report_when_no_proposed_actions(tmp_path):
    store = _store(tmp_path)
    module = OpsGateModule(tmp_path, profile="main")

    result = module.run_once(store=store, proposed_actions=[])

    assert result["status"] == "ok"
    assert result["skipped"] is True
    assert result["cadence_skipped"] is True
    assert result["reason"] == "no_pending_proposed_actions"
    assert result["decision_count"] == 0
    assert result["actual_execute"] is False
    assert "report_id" not in result
    assert module.read_reports() == []
    assert module.read_runs()[0]["cadence_skipped"] is True
    status = module.status()
    assert status["report_count"] == 0
    assert status["run_report_count"] == 1
    assert status["skipped_run_count"] == 1
    assert status["latest_cadence_skipped"] is True
    assert status["latest_skip_reason"] == "no_pending_proposed_actions"
    audit_lines = store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("ops_gate_run_skipped" in line for line in audit_lines)


def test_ops_gate_never_executes_even_would_allowed_actions(tmp_path):
    store = _store(tmp_path)
    module = OpsGateModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        proposed_actions=[{"id": "diag-2", "kind": "diagnostic", "target": "memory_os_doctor"}],
    )

    assert result["decisions"][0]["decision"] == "would_allow"
    assert result["decisions"][0]["actual_execute"] is False
    assert "executor_result" not in result["decisions"][0]


def test_ops_gate_defers_without_report_when_runtime_lock_is_held(tmp_path):
    store = _store(tmp_path)
    coordinator = ScheduleCoordinator(tmp_path / "system-modules" / "locks")
    coordinator.acquire_lock(
        "ops_gate.runtime",
        owner="other-module",
        ttl_seconds=60,
        now=datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc),
    )
    module = OpsGateModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        coordinator=coordinator,
        proposed_actions=[{"id": "diag-3", "kind": "diagnostic", "target": "memory_os_status"}],
        now=datetime(2026, 5, 20, 0, 0, 30, tzinfo=timezone.utc),
    )

    assert result["status"] == "deferred"
    assert result["reason"] == "lock_held"
    assert result["decision_count"] == 0
    assert module.read_reports() == []


def test_ops_gate_status_and_doctor_report_last_gate_health(tmp_path):
    store = _store(tmp_path)
    module = OpsGateModule(tmp_path, profile="main")
    module.run_once(
        store=store,
        proposed_actions=[{"id": "blocked-1", "kind": "filesystem_delete", "target": "/root/.hermes"}],
    )

    status = module.status()
    doctor = module.doctor()

    assert status["last_report_status"] == "warning"
    assert status["blocked_decision_count"] == 1
    assert doctor["status"] == "warning"
    assert doctor["findings"][0]["code"] == "blocked_actions_present"


def test_ops_gate_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    module = OpsGateModule(tmp_path / "main", profile="main")

    module.run_once(
        store=store,
        proposed_actions=[{"id": "diag-4", "kind": "diagnostic", "target": "memory_os_status"}],
    )

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
