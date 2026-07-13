"""R5 would-share/proposal outlet with deterministic gates and one delivery adapter."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from .crystallized import CrystallizedCandidate, append_candidate_queue, read_candidate_queue
from .store import MemoryOSStore
from .v3_fate import claim_outlet, close_outlet, complete_proposal, complete_share
from .wandering_journal import read_journal


class DeliveryOutlet(Protocol):
    def deliver(self, entry: dict[str, Any]) -> dict[str, Any]: ...


class ProposalOutlet(Protocol):
    def propose(self, entry: dict[str, Any]) -> dict[str, Any]: ...


class SpeakGateDeliveryOutlet:
    """The sole V3 external-speech adapter: ExpressionDraft -> SpeakGate."""

    def __init__(self, store: MemoryOSStore, *, profile: str) -> None:
        self.store = store
        self.profile = profile

    def deliver(self, entry: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.expression.expression_draft import ExpressionDraftModule
        from plugins.modules.expression.speak_gate import SpeakGateModule

        home = self.store.roots.hermes_home
        draft = ExpressionDraftModule(home, profile=self.profile).create_draft(
            store=self.store,
            source_module="v3_journal_outlet",
            text_preview=str(entry.get("content") or ""),
            source_refs=sorted(str(item) for item in entry.get("lineage_root_refs") or []),
            feeling_tags=[],
            risk_flags=[],
        )
        gate = SpeakGateModule(home, profile=self.profile, delivery_mode="owner-send", store=self.store)
        channel = gate._resolve_owner_channel()
        decision = gate.evaluate_expression_draft(draft, channel=channel, delivery_tier="v3_journal_share")
        receipt_id = str(decision.get("delivery_id") or "")
        outbox = home / "delivery" / "outbox" / f"{receipt_id}.json"
        succeeded = decision.get("actual_send") is True and bool(receipt_id) and outbox.is_file()
        return {
            "entry_id": str(entry.get("entry_id") or ""),
            "delivery_succeeded": succeeded,
            "receipt_id": receipt_id,
            "actual_send": succeeded,
        }


class V3ProposalSink:
    """Queue into Proposal Intake only; never writes an approval decision."""

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    def propose(self, entry: dict[str, Any]) -> dict[str, Any]:
        candidate_id = "cand_v3_" + str(entry["entry_id"])
        roots = sorted(str(item) for item in entry.get("lineage_root_refs") or [])
        body = str(entry.get("content") or "")
        candidate = CrystallizedCandidate(
            candidate_id=candidate_id,
            kind="insight",
            body=body,
            source_event_ids=roots,
            sensitivity="private",
            tags=["v3-journal-proposal"],
            bridge_state="proposal_intake_pending",
            provenance={"journal_entry_id": str(entry["entry_id"]), "lineage_root_refs": roots},
        )
        append_candidate_queue(self.store, candidate)
        matches = [item for item in read_candidate_queue(self.store) if item.candidate_id == candidate_id]
        if len(matches) != 1:
            raise RuntimeError("proposal_receipt_not_unique")
        stored = matches[0]
        return {
            "candidate_id": stored.candidate_id,
            "body_hash": "sha256:" + hashlib.sha256(stored.body.encode("utf-8")).hexdigest(),
            "provenance_refs": sorted(str(item) for item in entry.get("provenance_refs") or []),
        }


def evaluate_v3_outlet(
    store: MemoryOSStore,
    *,
    mode: str,
    expression_enabled: bool,
    max_share_per_window: int,
    share_window_seconds: int,
    cooldown_seconds: int,
    min_lineage_diversity: int,
    semantic_duplicate: Callable[[str], bool],
    delivery: DeliveryOutlet | None,
    proposal_sink: ProposalOutlet | None,
    prior_share_receipts: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    if mode not in {"shadow", "active"}:
        raise ValueError("mode")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    knobs = (max_share_per_window, share_window_seconds, cooldown_seconds, min_lineage_diversity)
    if any(type(item) is not int or item <= 0 for item in knobs):
        return {"status": "required_knob_missing", "would_share": 0, "would_propose": 0, "blocked": 0}
    if mode == "active" and expression_enabled is not True:
        return {"status": "disabled", "shared": 0, "proposed": 0, "blocked": 0}

    candidates = sorted(
        [
            item
            for item in read_journal(store)
            if item.get("record_type") == "thought"
            and item.get("fate") == "pending"
            and item.get("outlet_status") == "queued"
            and item.get("requested_fate") in {"share", "propose"}
        ],
        key=lambda item: (str(item.get("born_at") or ""), str(item.get("entry_id") or "")),
    )
    recent = _recent_successes(prior_share_receipts, current, share_window_seconds)
    recent_timestamps = [parsed for item in recent if (parsed := _timestamp(item.get("created_at") or item.get("ts"))) is not None]
    last_share = max(recent_timestamps, default=None)
    summary = {"status": "shadow" if mode == "shadow" else "ok", "would_share": 0, "would_propose": 0, "blocked": 0}
    if mode == "active":
        summary = {"status": "ok", "shared": 0, "proposed": 0, "blocked": 0}

    for entry in candidates:
        requested = str(entry.get("requested_fate") or "")
        roots = sorted(str(item) for item in entry.get("lineage_root_refs") or [])
        reason = ""
        if len(set(roots)) < min_lineage_diversity:
            reason = "lineage_diversity"
        elif semantic_duplicate(str(entry.get("content") or "")):
            reason = "semantic_duplicate"
        elif requested == "share" and len(recent) >= max_share_per_window:
            reason = "share_cap"
        elif requested == "share" and last_share is not None and current - last_share < timedelta(seconds=cooldown_seconds):
            reason = "share_cooldown"
        elif requested == "share" and delivery is None:
            reason = "delivery_capability_unavailable"
        elif requested == "propose" and proposal_sink is None:
            reason = "proposal_capability_unavailable"
        if reason:
            summary["blocked"] += 1
            if mode == "active":
                claimed = claim_outlet(store, str(entry["entry_id"]), expected_requested_fate=requested, now=current)
                close_outlet(store, str(claimed["entry_id"]), reason_code="blocked")
            continue
        if mode == "shadow":
            summary["would_share" if requested == "share" else "would_propose"] += 1
            continue

        claimed = claim_outlet(store, str(entry["entry_id"]), expected_requested_fate=requested, now=current)
        external_completed = False
        try:
            if requested == "share":
                assert delivery is not None
                receipt = delivery.deliver(claimed)
                external_completed = receipt.get("actual_send") is True
                if not external_completed:
                    close_outlet(store, str(claimed["entry_id"]), reason_code="blocked")
                    summary["blocked"] += 1
                    continue
                complete_share(store, str(claimed["entry_id"]), receipt, now=current)
                summary["shared"] += 1
                recent.append({"actual_send": True, "created_at": current.isoformat()})
                last_share = current
            else:
                assert proposal_sink is not None
                receipt = proposal_sink.propose(claimed)
                external_completed = True
                complete_proposal(store, str(claimed["entry_id"]), receipt, now=current)
                summary["proposed"] += 1
        except Exception:
            if not external_completed:
                close_outlet(store, str(claimed["entry_id"]), reason_code="provider_error")
            summary["blocked"] += 1
    return summary


def _recent_successes(records: list[dict[str, Any]], now: datetime, window_seconds: int) -> list[dict[str, Any]]:
    cutoff = now - timedelta(seconds=window_seconds)
    return [item for item in records if item.get("actual_send") is True and (_timestamp(item.get("created_at") or item.get("ts")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
