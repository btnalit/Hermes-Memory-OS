import json

from plugins.memory.memory_os.execution_gate import start_execution_gate_envelope
from plugins.memory.memory_os.left_brain_advisor import (
    left_brain_advisor_reports_path,
    left_brain_advisor_status,
    run_left_brain_advisor,
)
from plugins.memory.memory_os.memory_projection import memory_projection_records_path
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def test_left_brain_advisor_generates_report_only_findings(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                '{"schema_version":"memory-os.memory_projection_record.v0","projection_id":"p1","source_key":"mailbox_status","projection_type":"operational_signal","payload":{"status":"missing","capability_status":"missing","available":false},"raw_body_included":false,"boundary":{"actual_send":false}}',
                '{"schema_version":"memory-os.memory_projection_record.v0","projection_id":"p2","source_key":"execution_gate_envelopes","projection_type":"operational_signal","payload":{"status":"ok","boundary_true_count":0},"raw_body_included":false,"boundary":{"actual_send":false}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_left_brain_advisor(store, write=True, max_findings=10)

    assert report["schema_version"] == "memory-os.left_brain_advisor.v0"
    assert report["status"] in {"ok", "warning"}
    assert report["actual_execute"] is False
    assert report["actual_send"] is False
    assert report["actual_policy_write"] is False
    assert report["actual_crystallized_approval"] is False
    assert report["findings"]
    assert report["findings"][0]["target_type"] == "left_brain_advisor_finding"
    assert report["findings"][0]["actions_suppressed"] is True
    assert report["findings"][0]["dedup_key"]
    assert report["findings"][0]["confidence"] > 0
    assert report["findings"][0]["owner_burden_class"] == "review_suggested"
    assert report["findings"][0]["expires_at"]
    assert report["findings"][0]["allowed_action_type"] == "review_only"
    assert left_brain_advisor_reports_path(store.roots).exists()


def test_left_brain_advisor_automatic_write_uses_structural_write_gate(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"schema_version":"memory-os.memory_projection_record.v0","projection_id":"p1","source_key":"mailbox_status","projection_type":"operational_signal","payload":{"status":"missing","available":false},"raw_body_included":false,"boundary":{"actual_send":false}}\n',
        encoding="utf-8",
    )
    scope = {"projection_count": 1, "profile": "memoryos-test"}
    permit = start_execution_gate_envelope(
        store,
        lane_id="left_brain_advisor_report",
        trigger_surface="cognitive_loop",
        risk_class="governance_projection",
        human_approval_required=False,
        why_no_human_approval="report-only advisor",
        scope=scope,
        boundary={"actual_send": False, "actual_execute": False},
    )

    report = run_left_brain_advisor(
        store,
        write=True,
        trigger_type="cognitive_loop",
        execution_envelope_id=permit["execution_gate_envelope_id"],
        expected_scope=scope,
    )
    records = [
        json.loads(line)
        for line in left_brain_advisor_reports_path(store.roots).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    governance = records[0]["structural_write_governance"]

    assert report["execution_gate_resolution"]["status"] == "valid"
    assert governance["permit_status"] == "valid"
    assert governance["lane_id"] == "left_brain_advisor_report"
    assert governance["risk_class"] == "governance_projection"
    assert governance["boundary_true"] is False
    status = left_brain_advisor_status(store.roots)
    assert status["latest_structural_write_governance_present"] is True
    assert status["latest_structural_write_permit_status"] == "valid"
    assert status["latest_structural_write_lane_id"] == "left_brain_advisor_report"
    assert status["latest_structural_write_risk_class"] == "governance_projection"
    assert status["latest_structural_write_boundary_true"] is False


def test_left_brain_advisor_blocks_boundary_true_projection(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"schema_version":"memory-os.memory_projection_record.v0","projection_id":"bad","source_key":"runtime_logs","payload":{"status":"ok"},"raw_body_included":false,"boundary":{"actual_send":true}}\n',
        encoding="utf-8",
    )

    report = run_left_brain_advisor(store, write=False)

    assert report["status"] == "blocked"
    assert report["boundary_true_count"] == 1
    assert report["finding_count"] == 0


def test_left_brain_advisor_labels_available_false_without_claiming_status_ok(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"schema_version":"memory-os.memory_projection_record.v0","projection_id":"pavail","source_key":"mcp_server_health","source_hash":"mcp1","projection_type":"operational_signal","payload":{"status":"ok","available":false},"raw_body_included":false,"boundary":{"actual_send":false}}\n',
        encoding="utf-8",
    )

    report = run_left_brain_advisor(store, write=False, max_findings=10)

    assert report["findings"][0]["summary"] == "mcp_server_health projection reported status=availability_missing."


def test_left_brain_advisor_surfaces_repeated_external_cron_failures_as_review_suggested(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                '{"schema_version":"memory-os.memory_projection_record.v0","projection_id":"pcron","source_key":"hermes_cron_jobs","source_hash":"hcron1","source_scope_ref":"scope1","projection_type":"operational_signal","payload":{"status":"warning","external_failure_count":2,"timeout_failure_count":1,"latest_failure_job":"info-reflect-ai","latest_failure_reason":"Script timed out after 120s","latest_failure_at":"2026-06-03T03:02:35Z"},"raw_body_included":false,"boundary":{"actual_send":false}}',
                '{"schema_version":"memory-os.memory_projection_record.v0","projection_id":"pcron_duplicate","source_key":"hermes_cron_jobs","source_hash":"hcron2","source_scope_ref":"scope1","projection_type":"operational_signal","payload":{"status":"warning","external_failure_count":3,"timeout_failure_count":2,"latest_failure_job":"info-reflect-ai","latest_failure_reason":"Script timed out after 120s","latest_failure_at":"2026-06-03T03:32:35Z"},"raw_body_included":false,"boundary":{"actual_send":false}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_left_brain_advisor(store, write=False, max_findings=10)
    cron_findings = [finding for finding in report["findings"] if finding["source_key"] == "hermes_cron_jobs"]
    finding = cron_findings[0]

    assert report["status"] == "warning"
    assert len(cron_findings) == 1
    assert finding["priority"] == "review_suggested"
    assert finding["owner_burden_class"] == "review_suggested"
    assert finding["allowed_action_type"] == "review_only"
    assert finding["actual_execute"] is False
    assert finding["actual_send"] is False
    assert "info-reflect-ai" in finding["summary"]
    assert "120s" in finding["summary"]


def test_left_brain_advisor_surfaces_hindsight_governance_suggestions_without_writes(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"schema_version":"memory-os.memory_projection_record.v0","projection_id":"phindsight","source_key":"hindsight_provider_stats","source_hash":"hs1","source_scope_ref":"hindsight:default","projection_type":"governance_signal","payload":{"status":"ok","recall_mode":"active","raw_retained_count":1,"projection_stale_count":2,"pollution_indicator_count":3},"raw_body_included":false,"boundary":{"actual_send":false}}\n',
        encoding="utf-8",
    )

    report = run_left_brain_advisor(store, write=False, max_findings=10)
    hindsight_findings = [finding for finding in report["findings"] if finding["source_key"] == "hindsight_provider_stats"]

    assert len(hindsight_findings) == 3
    assert {finding["allowed_action_type"] for finding in hindsight_findings} == {"review_only"}
    assert {finding["owner_burden_class"] for finding in hindsight_findings} == {"review_suggested"}
    assert all(finding["hindsight_write"] is False for finding in hindsight_findings)
    assert all(finding["actual_execute"] is False for finding in hindsight_findings)
    assert any("stale" in finding["summary"] for finding in hindsight_findings)
