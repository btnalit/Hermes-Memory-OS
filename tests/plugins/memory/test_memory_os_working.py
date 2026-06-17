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


# ── Per-kind default parameters ──────────────────────────────────────────

def test_lingering_default_half_life_is_18h(tmp_path):
    """lingering default half_life_hours is 18 (replaces global 12)."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    item = service.add_item("lingering", "Decay test.", weight=1.0, now=now)
    # After 18h with default half-life=18h: weight = 1.0 * 0.5 = 0.5
    updated = service.decay_items("lingering", now=now + timedelta(hours=18))
    assert updated[0].id == item.id
    assert updated[0].weight == pytest.approx(0.5)
    # Still active (0.5 > 0.10 expire_below)
    assert updated[0].status == "active"


def test_lingering_default_expire_below_is_0_10(tmp_path):
    """lingering expire_below is 0.10 (replaces global 0.25)."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("lingering", "Fading.", weight=0.20, now=now)
    # After 18h: 0.20 * 0.5 = 0.10 — NOT below 0.10 (must be <, not <=)
    updated = service.decay_items("lingering", now=now + timedelta(hours=18))
    assert updated[0].weight == pytest.approx(0.10)
    assert updated[0].status == "active"

    # After 36h: 0.20 * 0.5^2 = 0.05 < 0.10 → expired
    updated2 = service.decay_items("lingering", now=now + timedelta(hours=36))
    assert updated2[0].status == "expired"


def test_emotional_half_life_is_48h(tmp_path):
    """emotional default half_life_hours is 48 (slowest decay)."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("emotional", "Emotional mark.", weight=1.0, now=now)
    # After 48h: 1.0 * 0.5 = 0.5, still active (>> 0.05)
    updated = service.decay_items("emotional", now=now + timedelta(hours=48))
    assert updated[0].weight == pytest.approx(0.5)
    assert updated[0].status == "active"


def test_attention_half_life_is_6h(tmp_path):
    """attention default half_life_hours is 6 (fastest decay)."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("attention", "Focus.", weight=0.20, now=now)
    # After 6h: 0.20 * 0.5 = 0.10 — NOT below 0.10
    updated = service.decay_items("attention", now=now + timedelta(hours=6))
    assert updated[0].weight == pytest.approx(0.10)

    # After 12h: 0.20 * 0.25 = 0.05 < 0.10 → expired
    updated2 = service.decay_items("attention", now=now + timedelta(hours=12))
    assert updated2[0].status == "expired"


def test_explicit_params_override_per_kind_defaults(tmp_path):
    """Explicit half_life_hours/expire_below still override per-kind defaults."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("lingering", "Custom decay.", weight=1.0, now=now)
    # Use explicit half_life=1h, expire_below=0.2 (test-style explicit override)
    updated = service.decay_items(
        "lingering", now=now + timedelta(hours=3),
        half_life_hours=1.0, expire_below=0.2,
    )
    assert updated[0].status == "expired"


# ── BUG fix: field semantics verification ─────────────────────────────────

def test_decay_does_not_touch_updated_at(tmp_path):
    """decay_items must NOT overwrite updated_at — it preserves content recency."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    item = service.add_item("lingering", "Content recency.", weight=1.0, now=now)
    original_updated_at = item.updated_at

    service.decay_items("lingering", now=now + timedelta(hours=3), half_life_hours=1.0, expire_below=0.2)
    document = service.read_document("lingering")
    assert document["items"][0]["updated_at"] == original_updated_at


def test_decay_sets_last_decayed_at(tmp_path):
    """decay_items sets last_decayed_at to the decay timestamp."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("lingering", "Decay bookkeeping.", weight=1.0, now=now)
    decay_time = now + timedelta(hours=3)
    service.decay_items("lingering", now=decay_time, half_life_hours=1.0, expire_below=0.2)

    document = service.read_document("lingering")
    assert document["items"][0]["last_decayed_at"] == decay_time.isoformat()


def test_decay_uses_last_decayed_at_for_elapsed(tmp_path):
    """Second decay starts counting from last_decayed_at, not updated_at."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("lingering", "Two decays.", weight=1.0, now=now)
    # First decay at now+1h with half-life=1h: weight = 1.0 * 0.5^1 = 0.5
    first = service.decay_items("lingering", now=now + timedelta(hours=1), half_life_hours=1.0, expire_below=0.2)
    assert first[0].weight == pytest.approx(0.5)
    assert first[0].last_decayed_at != ""

    # Second decay at now+2h: elapsed from last_decayed_at = 1h, weight = 0.5 * 0.5 = 0.25
    second = service.decay_items("lingering", now=now + timedelta(hours=2), half_life_hours=1.0, expire_below=0.2)
    assert second[0].weight == pytest.approx(0.25)


def test_new_item_has_empty_last_decayed_at(tmp_path):
    """Newly added item has last_decayed_at = '' (never decayed)."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("lingering", "Fresh item.", weight=1.0, now=now)
    document = service.read_document("lingering")
    assert document["items"][0]["last_decayed_at"] == ""


def test_new_item_has_empty_expired_at(tmp_path):
    """Newly added item has expired_at = ''."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("lingering", "Fresh item.", weight=1.0, now=now)
    document = service.read_document("lingering")
    assert document["items"][0]["expired_at"] == ""


def test_updated_at_preserved_across_multiple_decays(tmp_path):
    """updated_at stays at original creation time through multiple decay ticks."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    item = service.add_item("curiosity", "Multi-decay.", weight=1.0, now=now)
    original_updated = item.updated_at

    for offset in (1, 2, 3, 4):
        service.decay_items("curiosity", now=now + timedelta(hours=offset), half_life_hours=1.0, expire_below=0.2)

    document = service.read_document("curiosity")
    assert document["items"][0]["updated_at"] == original_updated


# ── Top-N cap verification ───────────────────────────────────────────────

def test_add_item_below_cap_no_eviction(tmp_path):
    """When below max_items, no items are evicted."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    # lingering cap is 50 — adding 3 items should not evict
    for i in range(3):
        service.add_item("lingering", f"Item {i}.", weight=0.5, now=now)

    document = service.read_document("lingering")
    assert len(document["items"]) == 3


def test_add_item_exceeds_cap_evicts_lowest_weight(tmp_path):
    """When over max_items, the lowest-weight items are evicted first."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    # attention cap is 20 — add 21 items with varying weights
    for i in range(20):
        service.add_item("attention", f"Item {i}.", weight=0.5, now=now)
    # Add one more with weight=0.1 — this should trigger cap eviction
    # The lowest-weight item (0.1) should be evicted after it's added
    service.add_item("attention", "Low weight.", weight=0.1, now=now)

    document = service.read_document("attention")
    assert len(document["items"]) == 20
    # The evicted item should be the one with weight=0.1 (lowest)
    weights = [item["weight"] for item in document["items"]]
    assert all(w >= 0.5 for w in weights)


def test_add_item_cap_evicts_weight_then_created_at(tmp_path):
    """Tiebreaker: same weight → older created_at evicted first."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    # attention cap is 20 — fill with 19 items
    for i in range(19):
        service.add_item("attention", f"Item {i}.", weight=0.5, now=now)
    # Add 2 more items with same weight=0.3; the first (older created_at) should
    # be the one evicted when the 21st pushes over cap
    service.add_item("attention", "Older low-weight.", weight=0.3, now=now)
    service.add_item("attention", "Newer low-weight.", weight=0.3, now=now + timedelta(seconds=1))

    document = service.read_document("attention")
    assert len(document["items"]) == 20
    # "Older low-weight." (earlier created_at) should be gone
    texts = {item["text"] for item in document["items"]}
    assert "Older low-weight." not in texts
    assert "Newer low-weight." in texts


def test_cap_eviction_writes_audit(tmp_path):
    """Cap eviction writes working_item_evicted audit record."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    # attention cap=20 — fill and overflow
    for i in range(20):
        service.add_item("attention", f"Item {i}.", weight=0.5, now=now)
    service.add_item("attention", "Overflow.", weight=0.1, now=now)

    audit_lines = service.store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("working_item_evicted" in line for line in audit_lines)


# ── expired_at field verification ────────────────────────────────────────

def test_expired_at_set_on_first_expiry(tmp_path):
    """expired_at is set when an item first transitions to expired."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("attention", "Will expire.", weight=1.0, now=now)
    expire_time = now + timedelta(hours=4)
    service.decay_items("attention", now=expire_time, half_life_hours=1.0, expire_below=0.2)

    document = service.read_document("attention")
    assert document["items"][0]["expired_at"] == expire_time.isoformat()


def test_expired_at_unchanged_on_second_decay(tmp_path):
    """expired_at stays at first-expiry timestamp; subsequent decays don't change it."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("attention", "Expire once.", weight=1.0, now=now)
    # First decay: triggers expiry
    first_decay = now + timedelta(hours=4)
    service.decay_items("attention", now=first_decay, half_life_hours=1.0, expire_below=0.2)

    doc_after_first = service.read_document("attention")
    first_expired_at = doc_after_first["items"][0]["expired_at"]
    assert first_expired_at == first_decay.isoformat()

    # Second decay: item already expired, expired_at must not change
    second_decay = now + timedelta(hours=6)
    service.decay_items("attention", now=second_decay, half_life_hours=1.0, expire_below=0.2)

    doc_after_second = service.read_document("attention")
    assert doc_after_second["items"][0]["expired_at"] == first_expired_at


def test_prune_uses_expired_at_for_grace(tmp_path):
    """Prune grace period is computed from expired_at, not updated_at."""
    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)

    service.add_item("lingering", "Prune test.", weight=1.0, now=now)
    # Decay to trigger expiry at now+1h
    service.decay_items("lingering", now=now + timedelta(hours=1), half_life_hours=0.5, expire_below=0.3)

    doc = service.read_document("lingering")
    assert doc["items"][0]["expired_at"] != ""

    # Prune at expired_at + 5h with min_age=4h → should prune
    pruned = service.prune_expired_items(
        "lingering", now=now + timedelta(hours=6), min_age_hours=4,
    )
    assert pruned == 1


# ── Backward compatibility (v0 → v1) ────────────────────────────────────

def test_read_v0_document_auto_fills_new_fields(tmp_path):
    """Reading a v0 doc auto-fills last_decayed_at/expired_at as empty strings."""
    import json
    from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION_V0

    service = _service(tmp_path)
    # Write a v0-format document directly
    path = service.store.roots.working_root / "lingering.json"
    v0_doc = {
        "schema_version": WORKING_SCHEMA_VERSION_V0,
        "updated_at": "2026-05-20T08:00:00+00:00",
        "items": [
            {
                "id": "wm_20260520T080000000000Z_0000000001",
                "kind": "lingering",
                "status": "active",
                "created_at": "2026-05-20T08:00:00+00:00",
                "updated_at": "2026-05-20T08:00:00+00:00",
                "text": "V0 item.",
                "source_event_id": "",
                "tags": [],
                "weight": 1.0,
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(v0_doc), encoding="utf-8")

    document = service.read_document("lingering")
    # Schema should be upgraded
    from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION
    assert document["schema_version"] == WORKING_SCHEMA_VERSION
    # New fields should be filled
    assert document["items"][0]["last_decayed_at"] == ""
    assert document["items"][0]["expired_at"] == ""


def test_decay_on_v0_item_uses_updated_at_as_base(tmp_path):
    """When last_decayed_at is empty (v0 data), decay falls back to updated_at."""
    import json
    from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION_V0

    service = _service(tmp_path)
    now = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
    path = service.store.roots.working_root / "lingering.json"
    v0_doc = {
        "schema_version": WORKING_SCHEMA_VERSION_V0,
        "updated_at": now.isoformat(),
        "items": [
            {
                "id": "wm_20260520T080000000000Z_0000000002",
                "kind": "lingering",
                "status": "active",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "text": "V0 item.",
                "source_event_id": "",
                "tags": [],
                "weight": 1.0,
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(v0_doc), encoding="utf-8")

    # Decay 1h later with half_life=1h: weight = 1.0 * 0.5 = 0.5
    updated = service.decay_items("lingering", now=now + timedelta(hours=1), half_life_hours=1.0, expire_below=0.2)
    assert updated[0].weight == pytest.approx(0.5)
    # Should now have last_decayed_at set
    assert updated[0].last_decayed_at != ""


def test_read_v0_document_no_schema_version(tmp_path):
    """Document with empty schema_version is also upgraded (graceful)."""
    import json

    service = _service(tmp_path)
    path = service.store.roots.working_root / "lingering.json"
    v0_doc = {
        "schema_version": "",
        "updated_at": "2026-05-20T08:00:00+00:00",
        "items": [
            {
                "id": "wm_20260520T080000000000Z_0000000003",
                "kind": "lingering",
                "status": "active",
                "created_at": "2026-05-20T08:00:00+00:00",
                "updated_at": "2026-05-20T08:00:00+00:00",
                "text": "Empty schema.",
                "source_event_id": "",
                "tags": [],
                "weight": 1.0,
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(v0_doc), encoding="utf-8")

    document = service.read_document("lingering")
    from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION
    assert document["schema_version"] == WORKING_SCHEMA_VERSION
    assert document["items"][0]["last_decayed_at"] == ""
