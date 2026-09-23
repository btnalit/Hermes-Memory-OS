"""Build temporary Memory-OS stores from RH-31 synthetic fixtures."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from eval.memory_os.runner.types import Rh31Document
from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, WORKING_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


@contextmanager
def synthetic_store(documents: list[Rh31Document]) -> Iterator[MemoryOSStore]:
    with tempfile.TemporaryDirectory(prefix="memory-os-rh31-") as temp_root:
        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(Path(temp_root)))
        store.initialize()
        working_items = []
        for index, document in enumerate(documents, start=1):
            event_id = f"evt_rh31_{index:03d}"
            store.append_event(
                EventEnvelope(
                    schema_version=EVENT_SCHEMA_VERSION,
                    id=event_id,
                    ts=f"2026-05-25T00:{index:02d}:00",
                    profile="default",
                    source=document.source_class,
                    kind="synthetic",
                    summary=document.text,
                    tags=list(document.tags),
                )
            )
            if document.source_class == "candidate":
                append_candidate_queue(
                    store,
                    CrystallizedCandidate(
                        candidate_id=f"cand_rh31_{index:03d}",
                        kind="synthetic",
                        body=document.text,
                        source_event_ids=[event_id],
                        sensitivity="private",
                        tags=list(document.tags),
                    ),
                )
            working_items.append(
                {
                    "id": f"work_rh31_{index:03d}",
                    "kind": "synthetic",
                    "status": "active",
                    "created_at": f"2026-05-25T00:{index:02d}:00Z",
                    "updated_at": f"2026-05-25T00:{index:02d}:00Z",
                    "text": document.text,
                    "source_event_id": event_id,
                    "tags": list(document.tags),
                    "weight": 0.5,
                }
            )
        store.write_working_document(
            "lingering",
            {
                "schema_version": WORKING_SCHEMA_VERSION,
                "updated_at": "2026-05-25T00:10:00Z",
                "items": working_items,
            },
        )
        yield store


@contextmanager
def graph_replay_pair_store(
    record_a: dict[str, Any],
    record_b: dict[str, Any],
) -> Iterator[tuple[MemoryOSStore, MemoryOSIndex]]:
    """Build an isolated Memory-OS store holding exactly two crystallized
    records (G4 graph-replay eval).

    Each record is written through the real producer path (canonical
    markdown via ``store.append_crystallized_record``), then a fresh index
    is rebuilt from the store — mirroring the pattern used by
    ``test_memory_os_edge_weight_feedback._active_edge`` / ``_seed_crystallized``
    so ``structural_edge_proposer`` and the prefetch graph layer see real
    ``crystallized_records`` + ``memory_fts`` projections, never hand-built
    SQLite rows. Isolated per-pair (rather than one shared store for the
    whole corpus) so ``run_structural_proposer``'s per-cycle pair budget
    never truncates before reaching a case's pair, and so cases cannot leak
    edges into each other.
    """
    with tempfile.TemporaryDirectory(prefix="memory-os-graph-replay-") as temp_root:
        roots = MemoryOSRoots.from_hermes_home(Path(temp_root))
        store = MemoryOSStore(roots)
        store.initialize()
        for record in (record_a, record_b):
            record_id = str(record["id"])
            created_at = str(record["created_at"])
            frontmatter = {
                "schema_version": "memory-os.crystallized.v0",
                "id": record_id,
                "kind": str(record["kind"]),
                "created_at": created_at,
                "approved_by": "owner",
                "approved_at": created_at,
                "approval_purpose": "graph_replay_eval",
                "approval_note": "G4 synthetic fixture — never real user data",
                "source_event_ids": [],
                "tags": [],
                "sensitivity": "private",
                "hindsight_indexed": False,
                "bridge_state": "active",
            }
            store.append_crystallized_record(f"{record_id}.md", frontmatter, str(record["body"]))
        index = MemoryOSIndex(roots)
        index.rebuild_from_store(store)
        yield store, index
