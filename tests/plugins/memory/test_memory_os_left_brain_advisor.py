from plugins.memory.memory_os.left_brain_advisor import left_brain_advisor_reports_path, run_left_brain_advisor
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
    assert left_brain_advisor_reports_path(store.roots).exists()


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
