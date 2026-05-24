"""Read-only baseline inventory for RH-31."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from plugins.memory.memory_os.audit import read_audit_entries
from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.memory_sources import memory_sources_stats_report
from plugins.memory.memory_os.store import MemoryOSStore


def build_inventory(store: MemoryOSStore) -> dict[str, Any]:
    events = store.read_events()
    event_by_source = Counter(event.source for event in events)
    event_by_kind = Counter(event.kind for event in events)
    working_by_status: Counter[str] = Counter()
    working_by_kind: Counter[str] = Counter()
    for path in sorted(store.roots.working_root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in document.get("items", []) if isinstance(document.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            working_by_status[str(item.get("status") or "unknown")] += 1
            working_by_kind[str(item.get("kind") or "unknown")] += 1
    audit_by_action = Counter(str(entry.get("action") or "unknown") for entry in read_audit_entries(store.roots.audit_path))
    memory_sources = memory_sources_stats_report(store.roots, hours=24)
    candidates = read_candidate_queue(store.roots)
    return {
        "schema_version": "memory-os.rh31_inventory.v0",
        "profile": store.roots.profile or "default",
        "event_distribution": {
            "count": len(events),
            "by_source": dict(event_by_source),
            "by_kind": dict(event_by_kind),
        },
        "working_distribution": {
            "count": sum(working_by_status.values()),
            "by_status": dict(working_by_status),
            "by_kind": dict(working_by_kind),
        },
        "candidate_distribution": {
            "count": len(candidates),
            "by_kind": dict(Counter(candidate.kind for candidate in candidates)),
        },
        "audit_distribution": {
            "count": sum(audit_by_action.values()),
            "by_action": dict(audit_by_action),
        },
        "memory_sources": {
            "schema_version": memory_sources.get("schema_version"),
            "record_count": memory_sources.get("record_count"),
            "feedback_count": memory_sources.get("feedback_count"),
            "route_distribution": memory_sources.get("route_distribution"),
            "selected_source_class_distribution": memory_sources.get("selected_source_class_distribution"),
            "boundary_true_count": memory_sources.get("boundary_true_count"),
            "forbidden_field_count": len(memory_sources.get("forbidden_field_findings") or []),
        },
        "monitor_field_mapping": {
            "memory_status.counts.events": "event_distribution.count",
            "memory_status.counts.working_items": "working_distribution.count",
            "memory_status.counts.crystallized_candidates": "candidate_distribution.count",
            "audit_actions.action_counts": "audit_distribution.by_action",
            "memory_sources": "memory_sources",
        },
        "fixture_weight_recommendations": _fixture_weight_recommendations(
            events=len(events),
            working=sum(working_by_status.values()),
            candidates=len(candidates),
            memory_source_records=int(memory_sources.get("record_count") or 0),
        ),
        "boundaries": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
    }


def _fixture_weight_recommendations(
    *,
    events: int,
    working: int,
    candidates: int,
    memory_source_records: int,
) -> dict[str, float]:
    total = max(events + working + candidates + memory_source_records, 1)
    return {
        "low_clue": round(max(memory_source_records, 1) / total, 3),
        "context_projection": round(max(working, 1) / total, 3),
        "candidate_boundary": round(max(candidates, 1) / total, 3),
        "diagnostic_grounding": 0.2,
    }
