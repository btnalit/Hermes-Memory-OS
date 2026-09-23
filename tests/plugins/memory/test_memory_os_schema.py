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
    EVENT_PRINCIPAL_SCHEMA_VERSION,
    EVENT_SCHEMA_VERSION,
    EventEnvelope,
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
        "principal": "owner",
        "principal_schema_version": EVENT_PRINCIPAL_SCHEMA_VERSION,
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


def test_event_envelope_from_dict_without_principal_defaults_to_legacy_era():
    """P2 backward compatibility: a pre-P2 row on disk has neither key.

    from_dict() must not raise (it is read on every startup against years of
    existing events), and the defaults must read as "legacy/unattributed",
    never silently as a real principal like "unknown" the resolver would
    have chosen -- "" is not in principal.PRINCIPALS, so a reader can always
    tell "nobody recorded an opinion" apart from "the resolver said unknown".
    """
    raw = _event_dict()
    del raw["principal"]
    del raw["principal_schema_version"]

    event = EventEnvelope.from_dict(raw)

    assert event.principal == ""
    assert event.principal_schema_version == ""
    assert event.principal_schema_version != EVENT_PRINCIPAL_SCHEMA_VERSION


def test_legacy_event_round_trips_byte_identically_so_its_index_hash_is_stable():
    """#95 review counterfactual: record_hash in the index is sha256 of
    json.dumps(event.to_dict(), sort_keys=True). If to_dict() always emitted
    the two P2 keys, every pre-P2 event would hash differently after the
    upgrade and doctor / deploy postcheck would report index_content_mismatch
    (FAIL) for the whole history until the next index_sync."""
    import hashlib
    import json

    raw = _event_dict()
    del raw["principal"]
    del raw["principal_schema_version"]

    reserialized = EventEnvelope.from_dict(raw).to_dict()

    assert reserialized == raw
    assert (
        hashlib.sha256(json.dumps(reserialized, sort_keys=True).encode("utf-8")).hexdigest()
        == hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
    )


def test_marked_event_without_principal_still_serializes_both_keys():
    """The monitor must be able to see a producer bug: a marked row with an
    empty principal keeps both keys rather than looking legacy."""
    raw = _event_dict()
    raw["principal"] = ""

    reserialized = EventEnvelope.from_dict(raw).to_dict()

    assert reserialized["principal"] == ""
    assert reserialized["principal_schema_version"] == EVENT_PRINCIPAL_SCHEMA_VERSION


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


def test_every_event_producer_sets_principal():
    """P2 census: every real EventEnvelope producer under plugins/ must set a
    principal. A producer that marks an event (principal_schema_version) but
    forgets principal writes exactly the defect the monitor's
    event_marked_without_principal WARN exists to catch -- this census catches
    it at commit time instead of after a monitor cycle.

    Deliberately coarse (file-level line-window, not full-parse call-site),
    matching this repo's existing promotion_state census immediately above:
    a call to EventEnvelope(...) / EventEnvelope.from_dict(...) must have the
    word "principal" somewhere in its surrounding lines.

    Two documented exemptions, not gaps:
    - store.py::read_events() calls EventEnvelope.from_dict() on bytes
      already written to disk (a reader/deserializer) -- it does not fabricate
      a NEW event's principal, it carries through whatever the original
      producer wrote (or didn't, for a pre-P2 row).
    - benchmark.py builds a synthetic load-test corpus (fixtures.
      generate_event_corpus) that never reaches a real owner or a real
      profile; "principal" has no referent for it.
    """
    import re
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    exempt = {
        repo_root / "plugins" / "memory" / "memory_os" / "store.py",
        repo_root / "plugins" / "memory" / "memory_os" / "benchmark.py",
    }
    call_pattern = re.compile(r"EventEnvelope\(|EventEnvelope\.from_dict\(")
    window_lines = 40
    offenders: list[str] = []
    for path in (repo_root / "plugins").rglob("*.py"):
        if path in exempt:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not call_pattern.search(line):
                continue
            window = "\n".join(lines[index : index + window_lines])
            if "principal" not in window:
                offenders.append(f"{path}:{index + 1}")
    assert not offenders, (
        "EventEnvelope producer call(s) with no 'principal' in the "
        f"surrounding {window_lines} lines -- every producer must set "
        f"principal (P2): {offenders}"
    )
