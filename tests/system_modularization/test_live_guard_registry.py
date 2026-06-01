from plugins.modules.governance.live_guard import LiveGuardRegistry, live_guard_registration_report
from plugins.memory.memory_os.audit import read_audit_entries


def test_live_guard_reports_registered_component_live_apply():
    registry = LiveGuardRegistry()
    registry.register("dummy_router", live_applied_field="live_applied")

    findings = registry.find_live_apply_findings(
        component="dummy_router",
        records=[{"live_applied": True}],
    )

    assert findings == [
        {
            "severity": "error",
            "code": "dummy_router_live_applied",
            "message": "dummy_router must stay live-shadow until a separate acting gate promotes it.",
            "count": 1,
        }
    ]


def test_live_guard_allows_shadow_records_without_live_apply():
    registry = LiveGuardRegistry()
    registry.register("derived_evidence_profile", live_applied_field="profile_live_applied")

    findings = registry.find_live_apply_findings(
        component="derived_evidence_profile",
        records=[
            {"profile_live_applied": False, "pipeline_liveness": "live-shadow"},
            {"pipeline_liveness": "live-shadow"},
        ],
    )

    assert findings == []


def test_live_guard_kill_switch_reads_l4_config():
    assert LiveGuardRegistry.kill_switch_enabled({"l4": {"kill_switch_enabled": True}}) is True
    assert LiveGuardRegistry.kill_switch_enabled({"l4": {"kill_switch_enabled": False}}) is False
    assert LiveGuardRegistry.kill_switch_enabled({}) is False


def test_live_guard_kill_switch_downgrades_acting_mode_and_audits(tmp_path):
    registry = LiveGuardRegistry()
    audit_path = tmp_path / "audit.jsonl"

    decision = registry.apply_automation_mode(
        component="confidence_router",
        requested_mode="autonomous_acting",
        config={"l4": {"kill_switch_enabled": True}},
        audit_path=audit_path,
    )

    assert decision == {
        "schema_version": "memory-os.live_guard_decision.v0",
        "component": "confidence_router",
        "requested_mode": "autonomous_acting",
        "effective_mode": "report-only",
        "kill_switch_engaged": True,
        "actual_send": False,
        "actual_execute": False,
        "live_behavior_changed": False,
    }
    entries = read_audit_entries(audit_path)
    assert [entry["action"] for entry in entries] == ["kill_switch_engaged"]
    assert entries[0]["target"] == "confidence_router"
    assert entries[0]["details"]["requested_mode"] == "autonomous_acting"
    assert entries[0]["details"]["effective_mode"] == "report-only"


def test_live_guard_keeps_requested_mode_when_kill_switch_is_off(tmp_path):
    registry = LiveGuardRegistry()
    audit_path = tmp_path / "audit.jsonl"

    decision = registry.apply_automation_mode(
        component="confidence_router",
        requested_mode="live-shadow",
        config={"l4": {"kill_switch_enabled": False}},
        audit_path=audit_path,
    )

    assert decision["effective_mode"] == "live-shadow"
    assert decision["kill_switch_engaged"] is False
    assert decision["actual_send"] is False
    assert decision["actual_execute"] is False
    assert not audit_path.exists()


def test_live_guard_registration_report_flags_unregistered_acting_component():
    report = live_guard_registration_report(
        [
            {
                "component": "unregistered_sender",
                "autonomy_level": "owner_approved_apply",
                "actual_send": True,
                "live_guard_registered": False,
            }
        ]
    )

    assert report["missing_registration_count"] == 1
    assert report["missing_registration_components"] == [
        {
            "component": "unregistered_sender",
            "markers": ["actual_send", "autonomy_level:owner_approved_apply"],
        }
    ]


def test_live_guard_registration_report_accepts_registered_or_exempted_acting_components():
    report = live_guard_registration_report(
        [
            {
                "component": "registered_sender",
                "autonomy_level": "owner_approved_apply",
                "actual_send": True,
                "live_guard_registered": True,
            },
            {
                "component": "legacy_manual_tool",
                "autonomy_level": "shadow",
                "actual_execute": True,
                "live_guard_registered": False,
            },
        ],
        exemptions={"legacy_manual_tool": "manual operator-only tool outside V7 runtime"},
    )

    assert report["missing_registration_count"] == 0
    assert report["exempted_components"] == [
        {"component": "legacy_manual_tool", "reason": "manual operator-only tool outside V7 runtime"}
    ]
