import json
from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
from plugins.memory.memory_os.audit import read_audit_entries
from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
)
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.working import WorkingMemoryService
from plugins.memory.memory_os.adapters.hindsight import (
    HindsightAdapter,
    HindsightAdapterConfig,
    HindsightExportRefused,
)


class FakeHindsightClient:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.payloads = []

    def retain(self, payload):
        if self.fail:
            raise RuntimeError("hindsight unavailable")
        self.payloads.append(payload)
        return {"ok": True, "id": f"hindsight-{len(self.payloads)}"}


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _service(tmp_path):
    return CrystallizedMemoryService(_store(tmp_path))


def _write_approved_record(service, *, sensitivity="public", body="Shareable durable memory."):
    event = EventEnvelope.from_dict(build_event(seed=51, profile="memoryos-test"))
    candidate = CrystallizedCandidate(
        candidate_id="candidate-51",
        kind="insight",
        body=body,
        source_event_ids=[event.id],
        sensitivity=sensitivity,
        tags=["memory-os", "adapter-smoke"],
    )
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-05-20T08:00:00+00:00",
        note="PRIVATE APPROVAL NOTE MUST NOT EXPORT",
    )
    service.write_approved_record(
        candidate,
        decision,
        file_name="insights.md",
        now=datetime(2026, 5, 20, 8, 1, tzinfo=timezone.utc),
    )
    return service.read_records("insights.md")[0]


def test_adapter_disabled_by_default_does_not_call_client_or_mutate_store(tmp_path):
    service = _service(tmp_path)
    _write_approved_record(service, sensitivity="public")
    client = FakeHindsightClient()

    report = HindsightAdapter(service.store, client=client).export_all()

    assert report["schema_version"] == "memory-os.hindsight_export_report.v0"
    assert report["enabled"] is False
    assert report["exported_count"] == 0
    assert client.payloads == []
    assert service.read_records("insights.md")[0].frontmatter["hindsight_indexed"] is False


def test_raw_events_working_items_and_cw019_candidates_are_refused(tmp_path):
    store = _store(tmp_path)
    adapter = HindsightAdapter(store, config=HindsightAdapterConfig(enabled=True), client=FakeHindsightClient())
    event = EventEnvelope.from_dict(build_event(seed=52, profile="memoryos-test"))
    working_item = WorkingMemoryService(store).add_item("lingering", "draft working memory")
    cw019_candidate = {
        "status": "candidate",
        "body": "pending body",
        "source": "heartbeat_lingering_candidates.jsonl",
    }

    with pytest.raises(HindsightExportRefused, match="raw events"):
        adapter.export_event(event)
    with pytest.raises(HindsightExportRefused, match="working memory"):
        adapter.export_working_item(working_item)
    with pytest.raises(HindsightExportRefused, match="CW-019 pending"):
        adapter.export_cw019_candidate(cw019_candidate)


def test_public_approved_crystallized_record_exports_payload_and_marks_indexed_after_success(tmp_path):
    service = _service(tmp_path)
    record = _write_approved_record(
        service,
        sensitivity="public",
        body="Owner-approved public memory.",
    )
    client = FakeHindsightClient()
    adapter = HindsightAdapter(service.store, config=HindsightAdapterConfig(enabled=True), client=client)

    report = adapter.export_all()

    assert report["enabled"] is True
    assert report["exported_count"] == 1
    assert report["failed_count"] == 0
    assert report["exported_records"] == [
        {
            "source_record_ref": record.frontmatter["id"],
            "source_version": "current",
            "source_class": "crystallized",
            "substrate_record_id": "hindsight-1",
            "substrate_snapshot_id": "hindsight:hindsight-1:vcurrent",
        }
    ]
    assert client.payloads == [
        {
            "schema_version": "memory-os.hindsight_export.v0",
            "record_id": record.frontmatter["id"],
            "kind": "insight",
            "text": "Owner-approved public memory.",
            "tags": ["memory-os", "adapter-smoke"],
            "source_event_ids": record.frontmatter["source_event_ids"],
            "metadata": {
                "source_class": "crystallized",
                "candidate_id": "candidate-51",
                "approved_by": "owner",
                "approved_at": "2026-05-20T08:00:00+00:00",
                "sensitivity": "public",
            },
        }
    ]
    refreshed = service.read_records("insights.md")[0]
    assert refreshed.frontmatter["hindsight_indexed"] is True


def test_private_crystallized_body_is_not_exported_or_reported(tmp_path):
    service = _service(tmp_path)
    _write_approved_record(service, sensitivity="private", body="PRIVATE BODY MUST NOT EXPORT")
    client = FakeHindsightClient()
    adapter = HindsightAdapter(service.store, config=HindsightAdapterConfig(enabled=True), client=client)

    report = adapter.export_all()

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["exported_count"] == 0
    assert report["skipped_count"] == 1
    assert client.payloads == []
    assert "PRIVATE BODY MUST NOT EXPORT" not in serialized
    assert service.read_records("insights.md")[0].frontmatter["hindsight_indexed"] is False


def test_client_failure_leaves_canonical_store_unmarked_except_audit(tmp_path):
    service = _service(tmp_path)
    _write_approved_record(service, sensitivity="public")
    adapter = HindsightAdapter(
        service.store,
        config=HindsightAdapterConfig(enabled=True),
        client=FakeHindsightClient(fail=True),
    )

    report = adapter.export_all()

    assert report["exported_count"] == 0
    assert report["failed_count"] == 1
    assert service.read_records("insights.md")[0].frontmatter["hindsight_indexed"] is False
    audit_actions = [entry["action"] for entry in read_audit_entries(service.store.roots.audit_path)]
    assert "hindsight_export_failed" in audit_actions
