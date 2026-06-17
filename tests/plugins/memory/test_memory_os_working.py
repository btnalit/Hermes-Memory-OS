from datetime import datetime, timedelta, timezone

import pytest

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.working import WorkingMemoryService, WorkingMemoryError


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


# ── prune_expired_items ──────────────────────────────────────────────────

def test_prune_removes_expired_items_past_grace_period(tmp_path):
    """Expired items older than min_age_hours are removed from the document."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    # Add an item and immediately expire it with a short half-life
    service.add_item("lingering", "Will be pruned.", weight=1.0, now=now)
    service.decay_items(
        "lingering",
        now=now + timedelta(hours=4),
        half_life_hours=1.0,
        expire_below=0.2,
    )
    # Item is now expired (weight ≈0.0625, status="expired")
    document = service.read_document("lingering")
    assert document["items"][0]["status"] == "expired"

    # Prune with min_age_hours=0 — immediately eligible
    pruned = service.prune_expired_items("lingering", now=now + timedelta(hours=5), min_age_hours=0)
    assert pruned == 1
    document_after = service.read_document("lingering")
    assert len(document_after["items"]) == 0


def test_prune_respects_min_age_hours_grace_period(tmp_path):
    """Items expired less than min_age_hours ago are kept."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("attention", "Recently expired.", weight=1.0, now=now)
    # After 3h with half_life=1h: weight = 1.0 * 0.5^3 = 0.125 < 0.2 → expired
    service.decay_items(
        "attention",
        now=now + timedelta(hours=3),
        half_life_hours=1.0,
        expire_below=0.2,
    )
    # Item expired at now+3h. Prune at now+3h with min_age_hours=48 → keep
    pruned = service.prune_expired_items(
        "attention", now=now + timedelta(hours=3), min_age_hours=48,
    )
    assert pruned == 0
    document = service.read_document("attention")
    assert len(document["items"]) == 1
    assert document["items"][0]["status"] == "expired"


def test_prune_does_not_touch_active_items(tmp_path):
    """Active items are never pruned, even with min_age_hours=0."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("lingering", "Still active.", weight=1.0, now=now)
    # Do NOT decay — item remains active
    pruned = service.prune_expired_items("lingering", now=now + timedelta(hours=100), min_age_hours=0)
    assert pruned == 0
    document = service.read_document("lingering")
    assert len(document["items"]) == 1
    assert document["items"][0]["status"] == "active"


def test_prune_handles_empty_document(tmp_path):
    """Pruning an empty document returns 0."""
    service = _service(tmp_path)
    pruned = service.prune_expired_items("emotional")
    assert pruned == 0


def test_prune_handles_mixed_active_and_expired(tmp_path):
    """Only expired items past the grace period are pruned; active items stay."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    # Item 1: created 48h ago with low weight — will be deeply expired
    service.add_item("curiosity", "Old expired.", weight=0.3, now=now - timedelta(hours=48))
    # Item 2: created 1h ago with full weight — still fresh
    service.add_item("curiosity", "Still fresh.", weight=1.0, now=now - timedelta(hours=1))

    # Decay at 'now': item 1 (elapsed=48h, weight≈0) → expired; item 2 (elapsed=1h, weight=0.5) → active
    service.decay_items(
        "curiosity",
        now=now,
        half_life_hours=1.0,
        expire_below=0.2,
    )

    # Prune at now+25h with min_age_hours=24:
    #   Item 1: expired at 'now' (updated_at=now), age=25h >= 24h → pruned
    #   Item 2: status='active' → kept
    pruned = service.prune_expired_items(
        "curiosity", now=now + timedelta(hours=25), min_age_hours=24,
    )
    assert pruned == 1
    document_after = service.read_document("curiosity")
    assert len(document_after["items"]) == 1
    assert document_after["items"][0]["status"] == "active"


def test_prune_audit_is_written(tmp_path):
    """Pruning writes an audit record for each pruned item."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("attention", "Audited prune.", weight=1.0, now=now)
    service.decay_items("attention", now=now + timedelta(hours=3), half_life_hours=1.0, expire_below=0.2)

    service.prune_expired_items("attention", now=now + timedelta(hours=30), min_age_hours=0)
    audit_lines = service.store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("working_item_pruned" in line for line in audit_lines)


def test_prune_rejects_negative_min_age_hours(tmp_path):
    """min_age_hours must be non-negative."""
    service = _service(tmp_path)
    with pytest.raises(WorkingMemoryError, match="min_age_hours must be non-negative"):
        service.prune_expired_items("lingering", min_age_hours=-1)


# ── New default parameters ───────────────────────────────────────────────

def test_decay_defaults_use_tighter_half_life(tmp_path):
    """Default half_life_hours is now 12 (was 24)."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    item = service.add_item("lingering", "Decay test.", weight=0.6, now=now)
    # After 12h with default half-life=12h, weight should be 0.6 * 0.5 = 0.3
    updated = service.decay_items("lingering", now=now + timedelta(hours=12))
    assert updated[0].id == item.id
    assert updated[0].weight == pytest.approx(0.3)
    # Still active (0.3 > 0.25 default expire_below)
    assert updated[0].status == "active"


def test_decay_defaults_expire_at_tighter_threshold(tmp_path):
    """With half_life=12h, a 0.45-weight item expires after ~12h (below 0.25)."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("lingering", "Fading.", weight=0.45, now=now)
    # After 12h: 0.45 * 0.5 = 0.225 < 0.25 → expired
    updated = service.decay_items("lingering", now=now + timedelta(hours=12))
    assert updated[0].status == "expired"
