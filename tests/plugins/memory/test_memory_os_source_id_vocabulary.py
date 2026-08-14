"""Producer/filter source_id vocabulary guard.

The 2026-08 production incident this pins: prefetch's graph_layer and
indexed sections emitted source_ids using the FTS index's storage-layer
record_type names (``crystallized_record:``/``crystallized_candidate:``),
which the safety allowlist (source_ids.filter_safe_source_id_values) and
the audit-side classification vocabulary
(exposure_rollup.CANONICAL_SOURCE_ID_PREFIXES) do not accept — so every ID
was silently dropped before the disclosure row was written, and the first
real graph/indexed selected sections all landed as attribution gaps
(10 rows, 2026-08-07..08-12, unrecoverable → attribution era v2→v3).

Per the CLAUDE.md rule "a gate whose vocabulary drifts from its producer's
checks nothing, silently", this guard enumerates the producer vocabulary
from source rather than trusting one fixture value.
"""

from __future__ import annotations

import re
from pathlib import Path

from plugins.memory.memory_os.exposure_rollup import CANONICAL_SOURCE_ID_PREFIXES
from plugins.memory.memory_os.memory_sources import ATTRIBUTION_SCHEMA_VERSION
from plugins.memory.memory_os.prefetch import (
    _CANONICAL_SOURCE_ID_PREFIX_BY_RECORD_TYPE,
    _canonical_source_id,
)
from plugins.memory.memory_os.source_ids import filter_safe_source_id_values

_PLUGIN_ROOT = Path(__file__).resolve().parents[3] / "plugins" / "memory" / "memory_os"

# The record types the FTS index writers actually store (source-scanned
# below so a new writer type must be triaged here at birth).
_EXPECTED_INDEX_RECORD_TYPES = {"event", "crystallized_record", "crystallized_candidate"}

_RECORD_TYPE_LITERAL = re.compile(r"record_type=\"([a-z_]+)\"")


def _scan_record_type_literals(path: Path) -> set[str]:
    return set(_RECORD_TYPE_LITERAL.findall(path.read_text(encoding="utf-8")))


def test_index_writer_record_type_vocabulary_is_pinned():
    scanned = _scan_record_type_literals(_PLUGIN_ROOT / "index.py")
    # Writers only; the scan may also catch defaulted query params, which is
    # fine — they use the same vocabulary.
    assert scanned == _EXPECTED_INDEX_RECORD_TYPES, (
        f"index.py record_type vocabulary changed ({scanned}); triage the new "
        f"type in prefetch._CANONICAL_SOURCE_ID_PREFIX_BY_RECORD_TYPE and here"
    )


def test_edge_endpoint_record_types_stay_within_index_vocabulary():
    proposer_files = (
        "structural_edge_proposer.py",
        "llm_edge_proposer.py",
        "vector_edge_proposer.py",
        "edge_provenance.py",
        "llm_contradiction_lane.py",
    )
    pattern = re.compile(r"(?:from|to)_record_type=\"([a-z_]+)\"")
    endpoint_types: set[str] = set()
    for name in proposer_files:
        path = _PLUGIN_ROOT / name
        if path.exists():
            endpoint_types |= set(pattern.findall(path.read_text(encoding="utf-8")))
    assert endpoint_types, "no edge endpoint types found — proposer scan is broken"
    assert endpoint_types <= _EXPECTED_INDEX_RECORD_TYPES, (
        f"edge endpoints use record types outside the index vocabulary: "
        f"{endpoint_types - _EXPECTED_INDEX_RECORD_TYPES}"
    )


def test_every_index_record_type_normalizes_to_an_accepted_source_id():
    for record_type in sorted(_EXPECTED_INDEX_RECORD_TYPES):
        sid = _canonical_source_id(record_type, "some_id_123")
        assert filter_safe_source_id_values([sid]) == [sid], (
            f"{record_type} normalizes to {sid!r}, which the safety allowlist drops"
        )
        assert sid.startswith(CANONICAL_SOURCE_ID_PREFIXES), (
            f"{record_type} normalizes to {sid!r}, which the audit classification "
            f"vocabulary cannot classify"
        )


def test_normalization_map_targets_exist_and_raw_storage_names_are_dropped():
    # Counterfactual for the incident: the RAW storage-layer form is exactly
    # what the old producer emitted, and the safety filter drops it. If the
    # allowlist is ever widened to accept these raw forms instead, this test
    # must be updated consciously together with the classification vocabulary.
    assert filter_safe_source_id_values(["crystallized_record:x"]) == []
    assert filter_safe_source_id_values(["crystallized_candidate:x"]) == []
    for storage_name, canonical in _CANONICAL_SOURCE_ID_PREFIX_BY_RECORD_TYPE.items():
        assert storage_name in _EXPECTED_INDEX_RECORD_TYPES, (
            f"normalization maps unknown storage type {storage_name!r}"
        )
        assert f"{canonical}:" in {p for p in CANONICAL_SOURCE_ID_PREFIXES}, (
            f"normalization target {canonical!r} is not a canonical prefix"
        )


def test_attribution_era_is_v3_after_producer_vocabulary_fix():
    # The v2 era's rows were written while graph/indexed IDs were being
    # dropped; they can never be repaired (the disclosure already happened),
    # so the era boundary advanced. Rolling back this constant resurrects a
    # permanent FAIL built from unrepairable rows.
    assert ATTRIBUTION_SCHEMA_VERSION == "memory-os.memory_sources_attribution.v3"
