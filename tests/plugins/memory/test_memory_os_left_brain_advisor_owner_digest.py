from plugins.memory.memory_os.left_brain_advisor import run_left_brain_advisor
from plugins.memory.memory_os.memory_projection import memory_projection_records_path
from plugins.memory.memory_os.owner_actions import owner_review_queue_report, render_owner_review_digest
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def test_left_brain_advisor_findings_enter_owner_digest_without_action_tokens(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"schema_version":"memory-os.memory_projection_record.v0","projection_id":"p-mailbox","source_key":"mailbox_status","projection_type":"operational_signal","payload":{"status":"missing","available":false},"raw_body_included":false,"boundary":{"actual_send":false}}\n',
        encoding="utf-8",
    )
    advisor = run_left_brain_advisor(store, write=True)

    queue = owner_review_queue_report(store, limit=20)
    items = [item for item in queue["items"] if item["target_type"] == "left_brain_advisor_finding"]
    digest = render_owner_review_digest(store, owner_id="owner", digest_mode="review")
    rendered_items = [
        item
        for section_items in digest["sections"].values()
        for item in section_items
        if item["target_type"] == "left_brain_advisor_finding"
    ]

    assert advisor["owner_visible_finding_count"] == 1
    assert queue["review_suggested_count"] >= 1
    assert items
    assert items[0]["priority"] == "review_suggested"
    assert rendered_items
    assert rendered_items[0]["action_tokens"] == {}
    assert "left_brain_advisor" in digest["text"]
    assert digest["boundary"]["actual_send"] is False
