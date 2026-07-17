"""Provider-agnostic port for external evidence intake.

This module provides a single public function ``external_intake`` that accepts
external evidence from any external provider and lands it as a tainted event
in the canonical event store.  Tainting is governed by the
``source_class="external_evidence"`` marker in the event's ``safe_ref``, and
the P0 immunity wall (``provenance.is_tainted``) blocks such events from being
auto-crystallized without explicit owner acknowledgement.

The module contains **zero** provider-specific literals -- adapters that
integrate specific external systems live outside ``memory_os/``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .execution_gate import (
    complete_execution_gate_envelope,
    start_execution_gate_envelope,
)
from .ids import new_event_id
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
from .store import MemoryOSStore


def external_intake(
    store: MemoryOSStore,
    *,
    content: str,
    external_ref: str,
    provider: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Accept external evidence and land it as a tainted event.

    Validates ``external_ref``, opens an ExecutionGate permit envelope,
    creates an ``EventEnvelope`` tagged with the tainted source class
    (``source_class="external_evidence"``), appends it to the event store,
    and completes the permit.

    The returned event ID can be used to reference the event in provenance
    chains.  Candidates that transitively reference this event will be
    classified as tainted by ``provenance.is_tainted``.

    Args:
        store: The ``MemoryOSStore`` instance.
        content: The evidence content (first 500 chars become the event summary).
        external_ref: Required non-empty external reference identifier.
        provider: Provider name (e.g. ``"external_adapter"``).
        metadata: Optional metadata dict attached to the event's ``safe_ref``.

    Returns:
        The ``event_id`` string of the created event.

    Raises:
        ValueError: If ``external_ref`` is empty or whitespace-only.
    """
    if not external_ref or not external_ref.strip():
        raise ValueError("external_ref must be a non-empty string")

    # ── Open ExecutionGate permit envelope ──────────────────────────────
    envelope = start_execution_gate_envelope(
        store,
        lane_id="external_evidence_intake",
        trigger_surface="external_intake",
        risk_class="low",
        human_approval_required=False,
        why_no_human_approval="external_evidence_intake_is_data_ingress_only_no_acting",
        scope={"surface": "canonical_event_store", "mode": "append_only"},
        boundary={
            "actual_send": False,
            "actual_execute": False,
            "actual_crystallized_approval": False,
            "actual_identity_write": False,
        },
    )
    envelope_id: str = envelope["execution_gate_envelope_id"]

    now = datetime.now(timezone.utc)

    # ── Build safe_ref ──────────────────────────────────────────────────
    safe_ref: dict[str, Any] = {
        "source_class": "external_evidence",
        "candidate_allowed": True,
        "external_ref": external_ref.strip(),
        "provider": provider,
        "execution_gate_envelope_id": envelope_id,
    }
    if metadata:
        safe_ref["metadata"] = metadata

    # ── Create and persist the event ────────────────────────────────────
    event = EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=new_event_id(now),
        ts=now.isoformat(),
        profile=store.roots.profile or "default",
        source="external_intake",
        kind="external_evidence_intake",
        summary=(content or "")[:500],
        safe_ref=safe_ref,
        tags=[
            "external-evidence",
            "tainted",
            f"provider:{provider}",
        ],
        sensitivity="private",
        body_policy="summary_only",
        hashes={},
        promotion_state="raw",
    )

    store.append_event(event)

    # ── Close the permit ────────────────────────────────────────────────
    complete_execution_gate_envelope(
        store,
        envelope_id=envelope_id,
        lane_id="external_evidence_intake",
        execution_status="completed",
        postcheck={"event_appended_count": 1},
        result_summary={"event_id": event.id},
    )

    return event.id
