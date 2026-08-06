"""R1 census: every RecallType member has one explicit, true disposition.

The enum declares nine recall lanes; the production facade registers five.
Without this census the gap is a false contract — a caller reading the enum
cannot tell a facade lane from an inlined prefetch section from a reserved
name. Each test pins one direction of the table so a new member, a new
retriever registration, or a deleted class must touch the table consciously.
"""

from __future__ import annotations

from pathlib import Path

from plugins.memory.memory_os.recall_facade import RetrieverFacade
from plugins.memory.memory_os.recall_types import RECALL_TYPE_DISPOSITION, RecallType
from plugins.memory.memory_os.retrievers import (
    CrystallizedRetriever,
    EntityGraphRetriever,
    IndexedFTSRetriever,
    StateOverlayRetriever,
    TemporalRetriever,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

_PRODUCTION_RETRIEVER_CLASSES = (
    StateOverlayRetriever,
    IndexedFTSRetriever,
    CrystallizedRetriever,
    EntityGraphRetriever,
    TemporalRetriever,
)

_ALLOWED_DISPOSITIONS = {
    "registered",
    "inlined_prefetch",
    "probe_only",
    "unimplemented_reserved",
}


def test_every_recall_type_has_explicit_disposition():
    assert set(RECALL_TYPE_DISPOSITION) == set(RecallType)
    assert set(RECALL_TYPE_DISPOSITION.values()) <= _ALLOWED_DISPOSITIONS


def test_registered_dispositions_match_production_facade_tuple():
    """Two-way bite: the table's `registered` set must equal exactly the
    recall types of the classes the provider registers, and the provider
    source must register exactly those classes."""
    registered_in_table = {
        member for member, disposition in RECALL_TYPE_DISPOSITION.items()
        if disposition == "registered"
    }
    registered_by_classes = {cls().recall_type for cls in _PRODUCTION_RETRIEVER_CLASSES}
    assert registered_in_table == registered_by_classes

    provider_source = (
        REPO_ROOT / "plugins" / "memory" / "memory_os" / "__init__.py"
    ).read_text(encoding="utf-8")
    for cls in _PRODUCTION_RETRIEVER_CLASSES:
        assert cls.__name__ in provider_source, (
            f"{cls.__name__} not registered in the provider — update "
            "RECALL_TYPE_DISPOSITION and this census together"
        )


def test_inlined_prefetch_types_have_no_registered_retriever():
    facade = RetrieverFacade()
    for cls in _PRODUCTION_RETRIEVER_CLASSES:
        facade.register(cls())
    for member, disposition in RECALL_TYPE_DISPOSITION.items():
        if disposition == "inlined_prefetch":
            assert facade.get(member) is None, (
                f"{member} is marked inlined_prefetch but a retriever is "
                "registered — move it to `registered` in the table"
            )


def test_probe_only_type_has_real_probe_consumer():
    """HINDSIGHT's retriever class is deliberately outside the production
    facade (substrate path owns production recall) but is a real, consumed
    class — the recall probe registers it. Deleting it is an owner decision,
    not dead-code cleanup."""
    from plugins.memory.memory_os.retrievers.hindsight import HindsightRetriever

    assert RECALL_TYPE_DISPOSITION[RecallType.HINDSIGHT] == "probe_only"
    probe_source = (
        REPO_ROOT / "scripts" / "memory_os_recall_probe.py"
    ).read_text(encoding="utf-8")
    assert "HindsightRetriever" in probe_source
    assert HindsightRetriever not in _PRODUCTION_RETRIEVER_CLASSES


def test_unimplemented_reserved_has_no_implementation():
    assert RECALL_TYPE_DISPOSITION[RecallType.EXTERNAL_EVIDENCE] == "unimplemented_reserved"
    retrievers_dir = REPO_ROOT / "plugins" / "memory" / "memory_os" / "retrievers"
    for path in retrievers_dir.glob("*.py"):
        assert "EXTERNAL_EVIDENCE" not in path.read_text(encoding="utf-8"), (
            f"{path.name} implements EXTERNAL_EVIDENCE — update the census table"
        )
