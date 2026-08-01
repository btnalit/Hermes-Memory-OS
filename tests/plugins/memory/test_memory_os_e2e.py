from datetime import datetime, timezone

import pytest

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.adapters.hindsight import (
    HindsightAdapter,
    HindsightAdapterConfig,
    HindsightExportRefused,
)
from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.inner_drive import InnerDriveEngine
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


class FakeHindsightClient:
    def __init__(self):
        self.payloads = []

    def retain(self, payload):
        self.payloads.append(payload)
        return {"ok": True, "id": f"fake-{len(self.payloads)}"}


def test_sync_turn_to_crystallized_to_optional_adapter_export_e2e(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize(
        "e2e-session",
        hermes_home=str(tmp_path),
        platform="e2e",
        agent_identity="memoryos-test",
        worker_autostart=False,
    )

    provider.sync_turn(
        "Owner asked Memory-OS to remember a stable engineering decision.",
        "Agent captured only a summary-only event.",
        session_id="e2e-session",
    )
    provider.shutdown()

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    events = store.read_events()
    assert len(events) == 1
    event = events[0]
    assert event.kind == "conversation_turn"
    assert event.body_policy == "summary_only"

    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)
    assert index.counts()["events"] == 1

    drive = InnerDriveEngine(store)
    process_result = drive.process_event(event, candidate_sensitivity="public")
    working_document = store.read_working_document("lingering")
    assert working_document["items"][0]["id"] == process_result.working_item.id
    assert working_document["items"][0]["source_event_id"] == event.id
    assert process_result.candidate.source_event_ids == [event.id]
    assert process_result.candidate.sensitivity == "public"

    decision = ApprovalDecision(
        candidate_id=process_result.candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-05-20T08:00:00+00:00",
        note="Approved in E2E test.",
    )
    crystallized = CrystallizedMemoryService(store)
    crystallized.write_approved_record(
        process_result.candidate,
        decision,
        file_name="moments.md",
        now=datetime(2026, 5, 20, 8, 1, tzinfo=timezone.utc),
    )
    records = crystallized.read_records("moments.md")
    assert len(records) == 1
    assert records[0].frontmatter["source_event_ids"] == [event.id]
    assert records[0].frontmatter["approved_by"] == "owner"
    assert records[0].frontmatter["approval_purpose"] == "approve_for_crystallized"
    assert records[0].frontmatter["hindsight_indexed"] is False

    disabled_client = FakeHindsightClient()
    disabled_report = HindsightAdapter(store, client=disabled_client).export_all()
    assert disabled_report["enabled"] is False
    assert disabled_report["exported_count"] == 0
    assert disabled_client.payloads == []
    assert crystallized.read_records("moments.md")[0].frontmatter["hindsight_indexed"] is False

    enabled_client = FakeHindsightClient()
    adapter = HindsightAdapter(
        store,
        config=HindsightAdapterConfig(enabled=True),
        client=enabled_client,
    )
    with pytest.raises(HindsightExportRefused, match="raw events"):
        adapter.export_event(event)
    with pytest.raises(HindsightExportRefused, match="working memory"):
        adapter.export_working_item(process_result.working_item)
    with pytest.raises(HindsightExportRefused, match="CW-019 pending"):
        adapter.export_cw019_candidate({"status": "candidate"})

    export_report = adapter.export_all()
    assert export_report["enabled"] is True
    assert export_report["exported_count"] == 1
    assert enabled_client.payloads[0]["source_event_ids"] == [event.id]
    assert crystallized.read_records("moments.md")[0].frontmatter["hindsight_indexed"] is True
