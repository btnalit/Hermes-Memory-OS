"""Build temporary Memory-OS stores from RH-31 synthetic fixtures."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from eval.memory_os.runner.types import Rh31Document
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
