from __future__ import annotations

import pytest

from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.v3_body_packet import (
    build_body_state_packet,
    resolve_body_manifest,
    verify_body_packet_manifest,
    write_body_packet_manifest,
)


def _store(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="default"))
    store.initialize()
    return store


def _packet():
    return build_body_state_packet(
        quiet_state=True,
        source_window={"start": "2026-07-12T00:00:00Z", "end": "2026-07-13T00:00:00Z"},
        source_cursors={"memory_sources": {"record_id": "msrc_1", "offset": 4}},
        seed_candidates=[
            {
                "ref": "crystallized:cry_a",
                "kind": "stable_memory",
                "bounded_text": "A" * 500,
                "epistemic_status": "approved",
                "salience_reasons": ["co_selected"],
            },
            {
                "ref": "event:evt_b",
                "kind": "working_attention",
                "bounded_text": "B",
                "epistemic_status": "working",
                "salience_reasons": ["lingering"],
            },
        ],
        edges=[
            {
                "from": "crystallized:cry_a",
                "to": "event:evt_b",
                "kind": "co_selected",
                "weight": 2,
            }
        ],
        sampler_seed="seed-1",
        max_text_chars=80,
    )


def test_packet_is_bounded_and_manifest_binds_exact_canonical_bytes(tmp_path):
    store = _store(tmp_path)
    packet = _packet()
    assert len(packet["seed_candidates"][0]["bounded_text"]) == 80
    assert packet["boundaries"] == {
        "no_tools": True,
        "no_external_action": True,
        "no_identity_write": True,
        "no_permanent_memory_write": True,
    }

    manifest = write_body_packet_manifest(store, packet)
    resolved = resolve_body_manifest(store, packet["snapshot_id"])
    assert resolved == manifest
    assert verify_body_packet_manifest(store, packet) == manifest
    assert manifest["body_text_included"] is False
    assert manifest["model_output_included"] is False
    assert "bounded_text" not in str(manifest)


def test_packet_rejects_unsafe_or_unresolved_edge_refs(tmp_path):
    with pytest.raises(ValueError, match="unsafe_source_ref"):
        build_body_state_packet(
            quiet_state=True,
            source_window={},
            source_cursors={},
            seed_candidates=[
                {
                    "ref": "raw_session:secret",
                    "kind": "stable_memory",
                    "bounded_text": "secret",
                    "epistemic_status": "approved",
                    "salience_reasons": [],
                }
            ],
            edges=[],
            sampler_seed="x",
        )

    packet = _packet()
    packet["edges"][0]["to"] = "event:not_in_packet"
    with pytest.raises(ValueError, match="edge_ref_not_in_packet"):
        write_body_packet_manifest(_store(tmp_path), packet)


def test_manifest_resolution_fails_closed_on_duplicate_snapshot(tmp_path):
    store = _store(tmp_path)
    packet = _packet()
    write_body_packet_manifest(store, packet)
    with pytest.raises(ValueError, match="duplicate_snapshot_id"):
        write_body_packet_manifest(store, packet)
