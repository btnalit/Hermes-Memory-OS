from datetime import datetime, timedelta, timezone

import pytest

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.working import WorkingMemoryService


def _service(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return WorkingMemoryService(store)


def test_add_item_persists_active_working_document(tmp_path):
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    item = service.add_item(
        "lingering",
        "A thought that keeps returning.",
        source_event_id="evt_20260520T000000000000Z_0000000001",
        tags=["thought"],
        weight=0.8,
        now=now,
    )

    document = service.read_document("lingering")
    assert document["schema_version"] == WORKING_SCHEMA_VERSION
    assert document["items"][0]["id"] == item.id
    assert document["items"][0]["kind"] == "lingering"
    assert document["items"][0]["status"] == "active"
    assert document["items"][0]["weight"] == 0.8


def test_decay_is_deterministic_and_marks_expired_items_with_audit(tmp_path):
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
    item = service.add_item("lingering", "Fading thought.", weight=1.0, now=now)

    updated = service.decay_items(
        "lingering",
        now=now + timedelta(hours=3),
        half_life_hours=1.0,
        expire_below=0.2,
    )

    assert updated[0].id == item.id
    assert updated[0].weight == pytest.approx(0.125)
    assert updated[0].status == "expired"
    document = service.read_document("lingering")
    assert document["items"][0]["status"] == "expired"
    audit_lines = service.store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("working_item_expired" in line and item.id in line for line in audit_lines)


def test_status_summary_uses_salience_language_only(tmp_path):
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
    service.add_item("lingering", "Active lingering item.", weight=0.7, now=now)
    service.add_item("curiosity", "Active curiosity item.", weight=0.6, now=now)

    summary = service.status_summary()

    assert "lingering: 1 active" in summary
    assert "curiosity: 1 active" in summary
    assert "weight" in summary
    assert "score" not in summary.lower()
    assert "proposal" not in summary.lower()
    assert "ops" not in summary.lower()


def test_trace_working_item_finds_expired_item_and_lifecycle_audit(tmp_path):
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
    item = service.add_item("emotional", "A temporary emotional mark.", weight=0.5, now=now)
    service.decay_items(
        "emotional",
        now=now + timedelta(hours=4),
        half_life_hours=1.0,
        expire_below=0.2,
    )

    trace = service.trace_working_item(item.id)

    assert trace["found"] is True
    assert trace["document"] == "emotional"
    assert trace["item"]["status"] == "expired"
    assert "working_item_added" in trace["audit_actions"]
    assert "working_item_expired" in trace["audit_actions"]


def test_engine_facing_operations_do_not_write_crystallized_memory(tmp_path):
    service = _service(tmp_path)

    service.add_item("attention", "Current focus.", weight=0.9)
    service.decay_items("attention")
    service.status_summary()

    assert list(service.store.roots.crystallized_root.glob("*.md")) == []
