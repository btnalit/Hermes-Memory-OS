import json
import threading

import plugins.memory.memory_os.memory_projection as memory_projection_module
from plugins.memory.memory_os.execution_gate import read_execution_gate_records, start_execution_gate_envelope
from plugins.memory.memory_os.host_capability_probe import probe_host_capabilities
from plugins.memory.memory_os.jsonl_io import append_jsonl_locked
from plugins.memory.memory_os.memory_projection import (
    MEMORY_PROJECTION_COMPACTION_REASONS,
    compact_memory_projection_records,
    collect_and_project_signals,
    memory_projection_records_path,
    memory_projection_retention_status,
    memory_projection_status,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.signal_source_registry import signal_source_specs
from plugins.memory.memory_os.store import MemoryOSStore


def test_memory_projection_requires_execution_gate_for_automatic_write(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    capabilities = probe_host_capabilities(store.roots, hermes_bin="definitely-missing-hermes-bin")

    report = collect_and_project_signals(
        store,
        host_capabilities=capabilities,
        trigger_type="cognitive_loop",
        execution_envelope_id="manual_cli_explicit",
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "execution_gate_envelope_id_invalid"
    assert memory_projection_status(store.roots)["projection_count"] == 0


def test_memory_projection_appends_records_with_valid_execution_gate(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    capabilities = probe_host_capabilities(store.roots, hermes_bin="definitely-missing-hermes-bin")
    source_count = len(signal_source_specs())
    permit = start_execution_gate_envelope(
        store,
        lane_id="memory_projection_collect",
        trigger_surface="cognitive_loop",
        risk_class="governance_projection",
        human_approval_required=False,
        why_no_human_approval="read-only signal projection",
        scope={"source_count": source_count, "profile": "memoryos-test"},
        boundary={"actual_send": False, "actual_execute": False, "actual_crystallized_approval": False},
    )

    report = collect_and_project_signals(
        store,
        host_capabilities=capabilities,
        trigger_type="cognitive_loop",
        execution_envelope_id=permit["execution_gate_envelope_id"],
        expected_scope={"source_count": source_count, "profile": "memoryos-test"},
    )
    status = memory_projection_status(store.roots)
    execution_records = read_execution_gate_records(store.roots)
    completions = [item for item in execution_records if item.get("stage") == "completion"]
    projection_records = [
        json.loads(line)
        for line in (store.roots.memory_os_root / "system" / "memory_projections.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["status"] in {"ok", "warning"}
    assert report["written_count"] > 0
    assert status["projection_count"] == report["written_count"]
    assert status["registered_source_count"] == source_count
    assert status["unique_source_count"] == source_count
    assert status["registered_source_missing_count"] == 0
    assert set(status["projected_source_keys"]) >= {"execution_gate_envelopes", "hermes_cron_jobs", "runtime_logs"}
    assert "log_file_count" in status["source_payload_fields"]["runtime_logs"]
    assert "operation_count" in status["source_payload_fields"]["hindsight_provider_stats"]
    assert "curation_review_suggested_count" in status["source_payload_fields"]["hindsight_governance_signals"]
    assert "would_send_count" in status["source_payload_fields"]["mailbox_status"]
    assert "wandering_mind_state" not in status["source_payload_fields"]
    assert "wandering_mind_cadence" not in status["source_payload_fields"]
    assert "configured_server_count" in status["source_payload_fields"]["mcp_server_health"]
    assert "step_count" in status["source_payload_fields"]["cognitive_loop_status"]
    assert "heartbeat_state_exists" in status["source_payload_fields"]["gateway_runtime_status"]
    assert "proposal_count" in status["source_payload_fields"]["proposal_queue_pressure"]
    assert "candidate_count" in status["source_payload_fields"]["candidate_queue_pressure"]
    assert "owner_action_count" in status["source_payload_fields"]["owner_review_pressure"]
    assert status["boundary_true_count"] == 0
    assert status["source_scope_missing_count"] == 0
    assert status["duplicate_source_hash_count"] == 0
    assert completions[-1]["execution_status"] == "ok"
    assert completions[-1]["postcheck_boundary_true"] is False
    assert '"raw_body":' not in encoded
    assert "private_body" not in encoded
    assert report["execution_gate_resolution"]["status"] == "valid"
    assert projection_records[0]["structural_write_governance"]["permit_status"] == "valid"
    assert projection_records[0]["structural_write_governance"]["lane_id"] == "memory_projection_collect"


def test_memory_projection_deduplicates_stable_source_hashes(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    capabilities = probe_host_capabilities(store.roots, hermes_bin="definitely-missing-hermes-bin")
    scope = {"source_count": len(signal_source_specs()), "profile": "memoryos-test"}

    first_permit = start_execution_gate_envelope(
        store,
        lane_id="memory_projection_collect",
        trigger_surface="cognitive_loop",
        risk_class="governance_projection",
        human_approval_required=False,
        why_no_human_approval="read-only signal projection",
        scope=scope,
        boundary={"actual_send": False, "actual_execute": False, "actual_crystallized_approval": False},
    )
    first = collect_and_project_signals(
        store,
        host_capabilities=capabilities,
        trigger_type="cognitive_loop",
        execution_envelope_id=first_permit["execution_gate_envelope_id"],
        expected_scope=scope,
    )
    second_permit = start_execution_gate_envelope(
        store,
        lane_id="memory_projection_collect",
        trigger_surface="cognitive_loop",
        risk_class="governance_projection",
        human_approval_required=False,
        why_no_human_approval="read-only signal projection",
        scope=scope,
        boundary={"actual_send": False, "actual_execute": False, "actual_crystallized_approval": False},
    )
    second = collect_and_project_signals(
        store,
        host_capabilities=capabilities,
        trigger_type="cognitive_loop",
        execution_envelope_id=second_permit["execution_gate_envelope_id"],
        expected_scope=scope,
    )
    status = memory_projection_status(store.roots)

    assert first["written_count"] > 0
    assert second["duplicate_skipped_count"] > 0
    assert status["duplicate_source_hash_count"] == 0


def test_memory_projection_compaction_archives_short_lived_status_records(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        _projection_record("old-a", "gateway_status", "hash-old-a", retention_class="short_lived_status"),
        _projection_record("old-b", "gateway_status", "hash-old-b", retention_class="short_lived_status"),
        _projection_record("new", "gateway_status", "hash-new", retention_class="short_lived_status"),
        _projection_record("gov", "owner_actions", "hash-gov", retention_class="governance_evidence"),
    ]
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")

    report = compact_memory_projection_records(store.roots, keep_latest_status_per_source=1, apply=True)
    remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    retention = memory_projection_retention_status(store.roots)

    assert report["status"] == "ok"
    assert report["reason"] == "compacted"
    assert report["reason"] in MEMORY_PROJECTION_COMPACTION_REASONS
    assert report["input_count"] == 4
    assert report["output_count"] == 2
    assert report["archived_count"] == 2
    assert {record["projection_id"] for record in remaining} == {"new", "gov"}
    assert report["archive_path"]
    assert (store.roots.memory_os_root / report["archive_path"]).is_file()
    assert retention["latest_archived_count"] == 2
    assert retention["latest_boundary_true_archived_count"] == 0
    assert retention["latest_reason"] == "compacted"
    assert retention["latest_completed_at"]


def test_memory_projection_compaction_reports_nothing_to_drop(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [_projection_record("only", "gateway_status", "hash-only", retention_class="short_lived_status")]
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")

    report = compact_memory_projection_records(store.roots, keep_latest_status_per_source=3, apply=True)
    remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert report["status"] == "ok"
    assert report["reason"] == "nothing_to_drop"
    assert report["reason"] in MEMORY_PROJECTION_COMPACTION_REASONS
    assert report["archived_count"] == 0
    assert len(remaining) == 1


def test_memory_projection_compaction_refuses_malformed_lines(tmp_path):
    """Counterfactual for the pre-fix behavior: the old ``_read_jsonl`` helper
    silently swallowed unparsable lines (``except json.JSONDecodeError:
    continue``), so a rewrite computed from what parsed would permanently
    delete a malformed line -- exactly the content nobody can reconstruct.
    Without the fix this test fails: the malformed line disappears from the
    live file and the report claims ``status == "ok"``.
    """
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    good_records = [
        _projection_record("old", "gateway_status", "hash-old", retention_class="short_lived_status"),
        _projection_record("new", "gateway_status", "hash-new", retention_class="short_lived_status"),
    ]
    original_text = "\n".join(json.dumps(record, sort_keys=True) for record in good_records) + "\n{not-json}\n"
    path.write_text(original_text, encoding="utf-8")

    report = compact_memory_projection_records(store.roots, keep_latest_status_per_source=1, apply=True)
    retention = memory_projection_retention_status(store.roots)

    assert report["status"] == "refused"
    assert report["reason"] == "malformed_lines_present"
    assert report["reason"] in MEMORY_PROJECTION_COMPACTION_REASONS
    assert report["archived_count"] == 0
    assert report["malformed_line_count"] == 1
    assert path.read_text(encoding="utf-8") == original_text, "refusal must leave the live file byte-for-byte untouched"
    assert retention["latest_reason"] == "malformed_lines_present"
    assert retention["latest_status"] == "refused"


def test_memory_projection_compaction_write_failure_is_recorded_and_non_destructive(tmp_path, monkeypatch):
    """Counterfactual: if a write failure during the live-file rewrite were
    left unhandled, the OSError would propagate uncaught out of the cron
    helper with no durable evidence of why nothing happened. With the fix,
    the archive write (which happens first) has already landed, the live
    file is left untouched (never overwritten with a partial/kept set), and
    the report records reason="write_failed" rather than raising or silently
    reporting success.
    """
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        _projection_record("old", "gateway_status", "hash-old", retention_class="short_lived_status"),
        _projection_record("new", "gateway_status", "hash-new", retention_class="short_lived_status"),
    ]
    original_text = "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n"
    path.write_text(original_text, encoding="utf-8")

    original_write = memory_projection_module._write_jsonl_atomic
    call_count = {"n": 0}

    def flaky_write(target_path, recs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError("simulated disk failure on live-file rewrite")
        return original_write(target_path, recs)

    monkeypatch.setattr(memory_projection_module, "_write_jsonl_atomic", flaky_write)

    report = compact_memory_projection_records(store.roots, keep_latest_status_per_source=1, apply=True)

    assert report["status"] == "error"
    assert report["reason"] == "write_failed"
    assert report["reason"] in MEMORY_PROJECTION_COMPACTION_REASONS
    # The archive write (call #1) succeeded before the failing live-file
    # rewrite (call #2) -- archive-before-drop held even on failure.
    assert report["archive_path"]
    assert (store.roots.memory_os_root / report["archive_path"]).is_file()
    # The live file must still contain every original record: the failed
    # rewrite must never have partially applied.
    assert path.read_text(encoding="utf-8") == original_text
    # ...and the report describes that on-disk state, not the intended split.
    assert report["output_count"] == report["input_count"]
    assert report["archived_count"] == 0


def test_memory_projection_compaction_serializes_with_concurrent_append(tmp_path, monkeypatch):
    """Counterfactual for the pre-fix race: compaction used to read then
    rewrite the live file with no lock at all, while ``append_governed_jsonl``
    / ``append_jsonl_locked`` (the automatic collection lane's write path)
    always acquired the sidecar flock on the same file. A concurrent append
    landing between compaction's read and its whole-file overwrite would be
    silently lost -- the overwrite is computed from a snapshot that predates
    the append. With the fix, compaction holds the same sidecar lock for its
    whole read-modify-write, so the append can only land strictly before or
    strictly after compaction, never during it.
    """
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        _projection_record(f"old-{i}", "gateway_status", f"hash-old-{i}", retention_class="short_lived_status")
        for i in range(3)
    ]
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")

    entered_live_write = threading.Event()
    proceed = threading.Event()
    order: list[str] = []
    original_write = memory_projection_module._write_jsonl_atomic

    def delayed_write(target_path, recs):
        if target_path == path:
            entered_live_write.set()
            assert proceed.wait(timeout=5), "test setup: append thread never signalled proceed"
        return original_write(target_path, recs)

    monkeypatch.setattr(memory_projection_module, "_write_jsonl_atomic", delayed_write)

    def run_compaction() -> None:
        compact_memory_projection_records(store.roots, keep_latest_status_per_source=1, apply=True)
        order.append("compaction_done")

    compaction_thread = threading.Thread(target=run_compaction)
    compaction_thread.start()
    assert entered_live_write.wait(timeout=5), "compaction never reached its live-file rewrite"

    def run_append() -> None:
        append_jsonl_locked(
            path,
            _projection_record("concurrent", "gateway_status", "hash-concurrent", retention_class="short_lived_status"),
        )
        order.append("append_done")

    append_thread = threading.Thread(target=run_append)
    append_thread.start()
    # The append must block behind compaction's held lock -- give it ample
    # time to (wrongly) race in before releasing compaction.
    append_thread.join(timeout=0.5)
    assert order == [], "append completed while compaction still held the lock -- the two are not mutually exclusive"

    proceed.set()
    compaction_thread.join(timeout=5)
    append_thread.join(timeout=5)

    assert order == ["compaction_done", "append_done"], "append must only complete after compaction released the lock"
    remaining_ids = {
        json.loads(line)["projection_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    }
    assert "concurrent" in remaining_ids, "the concurrent append must survive compaction's rewrite, not be clobbered"


def test_memory_projection_compaction_preserves_boundary_and_safety_records(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        _projection_record("old", "gateway_status", "hash-old", retention_class="short_lived_status"),
        _projection_record("new", "gateway_status", "hash-new", retention_class="short_lived_status"),
        _projection_record(
            "boundary",
            "gateway_status",
            "hash-boundary",
            retention_class="short_lived_status",
            boundary={"actual_send": True},
        ),
        _projection_record("raw", "gateway_status", "hash-raw", retention_class="short_lived_status", raw_body_included=True),
    ]
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")

    report = compact_memory_projection_records(store.roots, keep_latest_status_per_source=1, apply=True)
    remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert report["archived_count"] == 1
    assert report["boundary_true_preserved_count"] == 1
    assert report["raw_body_included_preserved_count"] == 1
    assert {record["projection_id"] for record in remaining} == {"new", "boundary", "raw"}


def test_memory_projection_status_reports_suppressed_jsonl_errors(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_projection_record("ok", "gateway_status", "hash-ok", retention_class="short_lived_status"))
        + "\n{bad-json}\n[]\n",
        encoding="utf-8",
    )

    status = memory_projection_status(store.roots)

    assert status["projection_count"] == 1
    assert status["suppressed_error_count"] == 2
    assert status["recent_error_codes"] == ["jsonl_malformed_line", "jsonl_non_object_line"]


def _projection_record(
    projection_id: str,
    source_key: str,
    source_hash: str,
    *,
    retention_class: str,
    boundary: dict | None = None,
    raw_body_included: bool = False,
) -> dict:
    return {
        "schema_version": "memory-os.memory_projection_record.v0",
        "projection_id": projection_id,
        "dedup_key": f"dedup-{projection_id}",
        "created_at": f"2026-06-03T00:0{len(projection_id) % 9}:00Z",
        "host_id": "test-host",
        "hermes_home_ref": "test-home",
        "profile_id": "memoryos-test",
        "source_scope_ref": "scope-test",
        "source_key": source_key,
        "source_hash": source_hash,
        "projection_type": "operational_signal",
        "retention_class": retention_class,
        "payload": {"status": "ok"},
        "raw_body_included": raw_body_included,
        "boundary": boundary or {"actual_send": False},
    }
