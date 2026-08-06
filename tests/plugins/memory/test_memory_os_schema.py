from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.ids import (
    new_audit_id,
    new_crystallized_id,
    new_event_id,
    new_view_id,
    new_working_id,
)
from plugins.memory.memory_os.schema import (
    EVENT_SCHEMA_VERSION,
    EventEnvelope,
    SchemaRegistry,
    ValidationError,
)


def _event_dict():
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "id": "evt_20260520T010203000000Z_abcdef1234",
        "ts": "2026-05-20T09:02:03+08:00",
        "profile": "sannai",
        "source": "telegram",
        "kind": "conversation_turn",
        "summary": "Owner asked about Memory-OS.",
        "safe_ref": {"session_id": "session-1"},
        "tags": ["memory-os"],
        "sensitivity": "private",
        "body_policy": "summary_only",
        "hashes": {"body_sha256": "abc"},
        "promotion_state": "raw",
    }


def test_event_envelope_round_trips_known_schema_version():
    event = EventEnvelope.from_dict(_event_dict())

    assert event.schema_version == EVENT_SCHEMA_VERSION
    assert event.profile == "sannai"
    assert event.safe_ref["session_id"] == "session-1"
    assert event.to_dict() == _event_dict()


def test_event_envelope_rejects_missing_required_field():
    raw = _event_dict()
    raw.pop("summary")

    with pytest.raises(ValidationError, match="summary"):
        EventEnvelope.from_dict(raw)


def test_event_envelope_rejects_unknown_schema_version():
    raw = _event_dict()
    raw["schema_version"] = "memory-os.event.v99"

    with pytest.raises(ValidationError, match="Unsupported schema_version"):
        EventEnvelope.from_dict(raw)


def test_schema_registry_reads_only_declared_versions():
    registry = SchemaRegistry()

    assert registry.current_write_version("event") == EVENT_SCHEMA_VERSION
    assert registry.can_read("event", EVENT_SCHEMA_VERSION) is True
    assert registry.can_read("event", "memory-os.event.v99") is False


def test_ids_are_prefixed_and_sortable_for_supplied_times():
    early = datetime(2026, 5, 20, 1, 2, 3, tzinfo=timezone.utc)
    later = datetime(2026, 5, 20, 1, 2, 4, tzinfo=timezone.utc)

    assert new_event_id(early, unique="a").startswith("evt_")
    assert new_working_id(early, unique="a").startswith("wrk_")
    assert new_crystallized_id(early, unique="a").startswith("cry_")
    assert new_audit_id(early, unique="a").startswith("audit_")
    assert new_view_id(early, unique="a").startswith("view_")
    assert new_event_id(early, unique="a") < new_event_id(later, unique="a")


def test_promotion_state_is_reserved_every_producer_writes_raw():
    """D5 census: promotion_state is a RESERVED field — the state machine it
    implies was never built, so every literal assignment in the codebase must
    be "raw". A producer writing any other value is half-implementing the
    machine without the migration/consumer side; that must be a conscious,
    census-updating change, not silent drift."""
    import re
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    pattern = re.compile(r"promotion_state[\"']?\s*[:=]\s*[\"'](\w+)[\"']")
    offenders: list[str] = []
    for path in (repo_root / "plugins").rglob("*.py"):
        for value in pattern.findall(path.read_text(encoding="utf-8")):
            if value != "raw":
                offenders.append(f"{path}: {value}")
    assert not offenders, (
        "promotion_state literals other than 'raw' found — the promotion "
        f"state machine is unimplemented; offenders: {offenders}"
    )
