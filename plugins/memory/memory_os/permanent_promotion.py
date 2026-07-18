"""Ledger-backed permanent-promotion domain contract (Living Memory V2-0.5)."""
from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit import append_audit
from .jsonl_io import _append_line_under_lock, locked_jsonl_file, write_jsonl_atomic_locked

PROPOSAL_SCHEMA_VERSION = "memory-os.permanent-promotion-proposal.v1"
TOKEN_SCHEMA_VERSION = "memory-os.permanent-promotion-token.v1"
DELIVERY_SCHEMA_VERSION = "memory-os.permanent-promotion-delivery.v1"
PERMANENT_PROMOTION_TARGET_TYPE = "permanent_memory_promotion"
PERMANENT_ACTIONS = frozenset({"propose", "approve", "reject", "defer"})
PERMANENT_DECISION_ACTIONS = frozenset({"approve", "reject", "defer"})
PERMANENT_PROMOTION_CHANNELS = frozenset({"cli", "owner_digest"})
PERMANENT_PROMOTION_ORIGINS = frozenset({"owner_initiated", "automatic"})
PROPOSAL_TERMINAL_STATUSES = frozenset({"approved", "rejected", "deferred", "revoked", "expired"})
PERMANENT_PROMOTION_LANE_ID = "permanent_promotion_producer"
PERMANENT_PROMOTION_RISK_CLASS = "bounded_reversible_queue"


class PermanentPromotionError(ValueError):
    """Raised with a stable fail-closed reason code."""


def utc_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise PermanentPromotionError("timestamp_must_be_timezone_aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def content_hash(body: str) -> str:
    return hashlib.sha256(str(body).encode("utf-8")).hexdigest()


def canonical_json_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_proposal_id(hex_source: str | None = None) -> str:
    source = str(hex_source or uuid4().hex)
    if len(source) != 32 or any(char not in "0123456789abcdef" for char in source):
        raise PermanentPromotionError("invalid_proposal_id_source")
    return f"ppm_{source}"


def issue_token(token_factory: Callable[[int], str] = secrets.token_urlsafe) -> str:
    # 32 bytes entropy; token is intentionally returned only to its issuer.
    return "ppmt_" + token_factory(32)


def validate_action_target(action: str, target_type: str) -> None:
    if action not in PERMANENT_ACTIONS:
        raise PermanentPromotionError("invalid_permanent_action")
    if target_type != PERMANENT_PROMOTION_TARGET_TYPE:
        raise PermanentPromotionError("invalid_permanent_target_type")


@dataclass(frozen=True)
class AutomaticWriteContext:
    """ExecutionGate proof reused by locked permanent-promotion appends."""

    store: Any
    envelope_id: str
    scope_hash: str
    lane_id: str = PERMANENT_PROMOTION_LANE_ID
    risk_class: str = PERMANENT_PROMOTION_RISK_CLASS

    def prepare(self, path: Path, record: dict[str, Any]) -> dict[str, Any]:
        from .structural_write_gate import prepare_governed_jsonl_record

        return prepare_governed_jsonl_record(
            self.store,
            path,
            record,
            write_owner="automatic",
            lane_id=self.lane_id,
            risk_class=self.risk_class,
            execution_gate_envelope_id=self.envelope_id,
            scope_hash=self.scope_hash,
        )


@dataclass(frozen=True)
class _VerifiedHostDeliveryReceipt:
    """Bound receipt created only after the owner-review claim is resolved."""

    delivery_ref: str
    digest_id: str
    receipt_id: str
    receipt_status: str
    proposal_ids: tuple[str, ...]


def build_proposal_record(
    *,
    proposal_id: str,
    target_id: str,
    candidate_id: str,
    body: str,
    created_at: str,
    channel: str,
    origin: str = "owner_initiated",
    evidence_profile_version: str = "v2-0-existing-eligibility",
    eligibility: dict[str, Any] | None = None,
    clearance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_action_target("propose", PERMANENT_PROMOTION_TARGET_TYPE)
    if not proposal_id.startswith("ppm_") or not target_id or not candidate_id:
        raise PermanentPromotionError("invalid_proposal_binding")
    if channel not in PERMANENT_PROMOTION_CHANNELS:
        raise PermanentPromotionError("proposal_channel_not_allowed")
    if origin not in PERMANENT_PROMOTION_ORIGINS:
        raise PermanentPromotionError("proposal_origin_not_allowed")
    record: dict[str, Any] = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "target_type": PERMANENT_PROMOTION_TARGET_TYPE,
        "target_id": target_id,
        "candidate_id": candidate_id,
        "content_hash": content_hash(body),
        "evidence_profile_version": evidence_profile_version,
        "status": "open",
        "created_at": created_at,
        "channel": channel,
        "origin": origin,
        "eligibility": eligibility or {"status": "eligible", "reason_codes": []},
        "clearance": clearance or {"status": "unavailable", "reason_code": "v2e_not_enabled"},
    }
    snapshot_input = {key: value for key, value in record.items() if key != "dossier_snapshot_hash"}
    record["dossier_snapshot_hash"] = canonical_json_hash(snapshot_input)
    return record


def _resolve_clearance_for_proposal(
    roots: Any,
    record_id: str,
    origin: str,
    v2e_enabled: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    """Query clearance receipts and map verdict → clearance dict per constitution matrix.

    Constitution matrix (V2-E §5):
    ─────────────┬─────────────────┬──────────────────
      Verdict     │ Automatic       │ Owner-initiated
    ─────────────┼─────────────────┼──────────────────
      clear       │ ✅ allow        │ ✅ allow
      conflict    │ ❌ contested     │ ⚠️ warn, allow
      unknown     │ ❌ blocked       │ ❌ blocked
      (no receipt)│ ❌ blocked       │ ❌ blocked
    ─────────────┴─────────────────┴──────────────────

    Returns ``(clearance_dict, block_reason_or_None)``.
    When *block_reason* is not ``None`` the proposal **must not** be created.
    """
    if not v2e_enabled:
        return (None, None)

    from .clearance_receipts import ClearanceReceipt as _CR, read_clearance_receipts as _read

    receipts = _read(roots)
    active_receipt = None
    for rec in receipts:
        cr = _CR.from_dict(rec)
        if cr.record_id == record_id and cr.is_active:
            active_receipt = cr
            break

    if active_receipt is None:
        return (
            {"status": "unavailable", "reason_code": "no_clearance_receipt"},
            "no_clearance_receipt",
        )

    verdict = active_receipt.verdict

    if verdict == "clear":
        return (
            {"status": "clear", "receipt_id": active_receipt.receipt_id},
            None,
        )

    if verdict == "conflict":
        clearance = {
            "status": "conflict",
            "receipt_id": active_receipt.receipt_id,
            "conflict_refs": list(active_receipt.conflict_refs),
        }
        if origin == "automatic":
            clearance["contested"] = True
            return (clearance, "clearance_conflict")
        else:
            clearance["owner_override"] = True
            return (clearance, None)

    if verdict == "unknown":
        return (
            {"status": "unknown", "receipt_id": active_receipt.receipt_id},
            "clearance_unknown",
        )

    # Defensive: unexpected verdict → block
    return (
        {"status": "unavailable", "reason_code": "unexpected_verdict",
         "raw_verdict": verdict},
        "unexpected_verdict",
    )


def _evidence_increment_detected(
    rejection_evidence: dict[str, Any],
    current_evidence: dict[str, Any],
) -> bool:
    """B5: detect meaningful evidence improvement since rejection.

    Returns True when at least one of:
    - coverage counts rose (source_diversity or recurrence up)
    - derivation level upgraded (L2→L1, L1→L0)
    """
    if not rejection_evidence or not current_evidence:
        # No prior evidence snapshot or no current evidence — allow
        return True

    # Check coverage increment
    old_cov = (
        rejection_evidence.get("coverage")
        if isinstance(rejection_evidence.get("coverage"), dict)
        else {}
    )
    new_cov = (
        current_evidence.get("coverage")
        if isinstance(current_evidence.get("coverage"), dict)
        else {}
    )
    old_diversity = int(old_cov.get("source_diversity") or 0)
    new_diversity = int(new_cov.get("source_diversity") or 0)
    old_recurrence = int(old_cov.get("recurrence") or 0)
    new_recurrence = int(new_cov.get("recurrence") or 0)

    if new_diversity > old_diversity or new_recurrence > old_recurrence:
        return True

    # Check derivation upgrade
    derivation_order = {"L3": 0, "L2": 1, "L1": 2, "L0": 3}
    old_derivation = str(rejection_evidence.get("derivation") or "")
    new_derivation = str(current_evidence.get("derivation") or "")
    old_level = str(rejection_evidence.get("abstraction_level") or "")
    new_level = str(current_evidence.get("abstraction_level") or "")

    if derivation_order.get(new_level, -1) > derivation_order.get(old_level, -1):
        return True
    if derivation_order.get(new_derivation, -1) > derivation_order.get(old_derivation, -1):
        return True

    return False


def _write_absorption_audit(
    roots: Any,
    *,
    absorbed_content_hash: str,
    target_permanent_id: str,
    similarity_basis: str = "",
) -> None:
    """B6: Write absorption audit record — no silent drops."""
    import json as _json
    from datetime import timezone as _tz

    from .jsonl_io import append_jsonl_locked

    path = roots.memory_os_root / "system" / "absorption_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "memory-os.absorption_audit.v0",
        "absorbed_content_hash": str(absorbed_content_hash),
        "target_permanent_id": str(target_permanent_id),
        "similarity_basis": str(similarity_basis or "exact_match"),
        "absorbed_at": datetime.now(_tz.utc).isoformat().replace("+00:00", "Z"),
    }
    try:
        append_jsonl_locked(path, record)
    except Exception:
        pass  # fail-open: audit loss must not block proposal flow


class ProposalLedger:
    """Append-only proposal events plus atomically-derived pending snapshot."""

    def __init__(self, memory_os_root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self.memory_os_root = Path(memory_os_root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def proposals_path(self) -> Path:
        return self.memory_os_root / "system" / "permanent_promotion_proposals.jsonl"

    @property
    def open_snapshot_path(self) -> Path:
        return self.memory_os_root / "system" / "permanent_promotion_open.jsonl"

    def _events(self) -> list[dict[str, Any]]:
        if not self.proposals_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.proposals_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def _states(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for event in self._events():
            proposal_id = str(event.get("proposal_id") or "")
            if proposal_id:
                states[proposal_id] = {**states.get(proposal_id, {}), **event}
        return states

    def _write_open_snapshot(self) -> None:
        pending = [
            state for state in self._states().values()
            if state.get("status") in {"open", "deciding"}
        ]
        write_jsonl_atomic_locked(
            self.open_snapshot_path,
            sorted(pending, key=lambda item: (str(item.get("created_at") or ""), str(item.get("proposal_id") or ""))),
        )

    def _append_locked(
        self,
        target: Path,
        event: dict[str, Any],
        *,
        write_context: AutomaticWriteContext | None = None,
    ) -> dict[str, Any]:
        payload = write_context.prepare(self.proposals_path, event) if write_context else dict(event)
        _append_line_under_lock(target, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return payload

    def create_or_get(
        self,
        *,
        target_id: str,
        candidate_id: str,
        body: str,
        channel: str,
        origin: str = "owner_initiated",
        eligibility: dict[str, Any] | None = None,
        clearance: dict[str, Any] | None = None,
        v2e_enabled: bool = False,
        write_context: AutomaticWriteContext | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if channel not in PERMANENT_PROMOTION_CHANNELS:
            raise PermanentPromotionError("proposal_channel_not_allowed")
        if origin not in PERMANENT_PROMOTION_ORIGINS:
            raise PermanentPromotionError("proposal_origin_not_allowed")
        if origin == "automatic" and write_context is None:
            raise PermanentPromotionError("automatic_write_requires_execution_gate")
        resolved_clearance = clearance or {"status": "unavailable", "reason_code": "v2e_not_enabled"}
        if origin == "automatic" and v2e_enabled and resolved_clearance.get("status") != "clear":
            raise PermanentPromotionError("automatic_clearance_required")

        body_hash = content_hash(body)
        evidence_version = "v2-0-existing-eligibility"
        with locked_jsonl_file(self.proposals_path) as target:
            states = self._states()

            # Same target with a changed body must never leave two actionable
            # proposals. Close the stale binding before opening the replacement.
            for proposal_id, existing in list(states.items()):
                if (
                    existing.get("status") in {"open", "deciding"}
                    and existing.get("target_id") == target_id
                    and existing.get("content_hash") != body_hash
                ):
                    stale_event = {
                        "schema_version": PROPOSAL_SCHEMA_VERSION,
                        "proposal_id": proposal_id,
                        "status": "revoked",
                        "reason": "content_drift",
                        "updated_at": utc_timestamp(self.clock()),
                    }
                    self._append_locked(target, stale_event, write_context=write_context)
                    states[proposal_id] = {**existing, **stale_event}

            existing_open: dict[str, Any] | None = None
            for existing in states.values():
                if (
                    existing.get("status") in {"open", "deciding"}
                    and existing.get("content_hash") == body_hash
                    and existing.get("evidence_profile_version") == evidence_version
                ):
                    existing_open = existing
                    break
            if existing_open is not None:
                proposal, created = existing_open, False
            else:
                for existing in states.values():
                    if existing.get("target_id") != target_id or existing.get("content_hash") != body_hash:
                        continue
                    status = str(existing.get("status") or "")
                    if status == "rejected" and origin == "automatic":
                        # ── B5: evidence increment predicate ──────────
                        from .knob_overrides import resolve_knob as _resolve_knob_inc
                        if _resolve_knob_inc(
                            "evidence_increment_enabled", default=False,
                            _store_root=self.memory_os_root,
                        ):
                            # Check if evidence has improved since rejection
                            rejection_evidence = (
                                existing.get("evidence_profile_snapshot")
                                if isinstance(existing.get("evidence_profile_snapshot"), dict)
                                else {}
                            )
                            current_evidence = (
                                eligibility.get("evidence_profile")
                                if isinstance(eligibility, dict) and isinstance(eligibility.get("evidence_profile"), dict)
                                else {}
                            )
                            if not _evidence_increment_detected(
                                rejection_evidence, current_evidence,
                            ):
                                raise PermanentPromotionError("automatic_reproposal_rejected_no_evidence_increment")
                            # Evidence improved — fall through to allow re-proposal
                        else:
                            raise PermanentPromotionError("automatic_reproposal_rejected")
                    if status == "approved":
                        # ── B6: absorption audit — don't silently drop ──
                        _write_absorption_audit(
                            self.store.roots,
                            absorbed_content_hash=body_hash,
                            target_permanent_id=str(existing.get("target_id") or ""),
                            similarity_basis="exact_content_hash_match",
                        )
                        raise PermanentPromotionError("content_already_permanent")
                    if status == "deferred":
                        due = parse_timestamp(existing.get("deferred_until"))
                        if due is not None and due > self.clock().astimezone(timezone.utc):
                            return existing, False
                proposal = build_proposal_record(
                    proposal_id=make_proposal_id(),
                    target_id=target_id,
                    candidate_id=candidate_id,
                    body=body,
                    created_at=utc_timestamp(self.clock()),
                    channel=channel,
                    origin=origin,
                    eligibility=eligibility,
                    clearance=resolved_clearance,
                    evidence_profile_version=evidence_version,
                )
                proposal = self._append_locked(target, proposal, write_context=write_context)
                created = True
        self._write_open_snapshot()
        return proposal, created

    def append_terminal(
        self,
        proposal_id: str,
        status: str,
        *,
        deferred_until: str = "",
        reason: str = "",
        operation_id: str = "",
        result_ref: dict[str, Any] | None = None,
        recovered: bool = False,
        write_context: AutomaticWriteContext | None = None,
    ) -> dict[str, Any]:
        if status not in PROPOSAL_TERMINAL_STATUSES:
            raise PermanentPromotionError("invalid_terminal_proposal_status")
        with locked_jsonl_file(self.proposals_path) as target:
            current = self._states().get(str(proposal_id or ""))
            if current is None:
                raise PermanentPromotionError("proposal_not_found")
            current_status = str(current.get("status") or "")
            if current_status in PROPOSAL_TERMINAL_STATUSES:
                if current_status == status:
                    return current
                raise PermanentPromotionError("proposal_closed")
            if current_status not in {"open", "deciding"}:
                raise PermanentPromotionError("proposal_not_actionable")
            event: dict[str, Any] = {
                "schema_version": PROPOSAL_SCHEMA_VERSION,
                "proposal_id": proposal_id,
                "status": status,
                "updated_at": utc_timestamp(self.clock()),
            }
            if deferred_until:
                event["deferred_until"] = deferred_until
            if reason:
                event["reason"] = reason
            if operation_id:
                event["operation_id"] = operation_id
            if result_ref:
                event["result_ref"] = _bounded_result_ref(result_ref)
            if recovered:
                event["recovered"] = True
            payload = self._append_locked(target, event, write_context=write_context)
            result = {**current, **payload}
        self._write_open_snapshot()
        return result


class TokenLedger:
    """Append-only random token issuance/state ledger; raw tokens never persist."""

    def __init__(self, memory_os_root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self.memory_os_root = Path(memory_os_root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def path(self) -> Path:
        return self.memory_os_root / "system" / "owner_action_tokens.jsonl"

    def _states(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        if not self.path.exists():
            return states
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            token_hash = str(event.get("token_hash") or "") if isinstance(event, dict) else ""
            if token_hash:
                states[token_hash] = {**states.get(token_hash, {}), **event}
        return states

    def _append_locked(
        self,
        target: Path,
        event: dict[str, Any],
        *,
        write_context: AutomaticWriteContext | None = None,
    ) -> dict[str, Any]:
        payload = write_context.prepare(self.path, event) if write_context else dict(event)
        _append_line_under_lock(target, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return payload

    def issue(
        self,
        proposal: dict[str, Any],
        *,
        channel: str,
        expires_at: datetime | None = None,
        delivery_ref: str = "",
        write_context: AutomaticWriteContext | None = None,
    ) -> str:
        if channel not in PERMANENT_PROMOTION_CHANNELS or proposal.get("status") != "open":
            raise PermanentPromotionError("token_issuance_not_allowed")
        if channel == "owner_digest" and write_context is None:
            raise PermanentPromotionError("automatic_write_requires_execution_gate")
        token = issue_token()
        now = self.clock()
        expiry = expires_at or (now + timedelta(hours=48))
        record: dict[str, Any] = {
            "schema_version": TOKEN_SCHEMA_VERSION,
            "token_hash": content_hash(token),
            "proposal_id": proposal["proposal_id"],
            "target_type": PERMANENT_PROMOTION_TARGET_TYPE,
            "target_id": proposal["target_id"],
            "content_hash": proposal["content_hash"],
            "dossier_snapshot_hash": proposal["dossier_snapshot_hash"],
            "issued_at": utc_timestamp(now),
            "expires_at": utc_timestamp(expiry),
            "channel": channel,
            "status": "open",
        }
        if delivery_ref:
            record["delivery_ref"] = str(delivery_ref)[:160]
        with locked_jsonl_file(self.path) as target:
            self._append_locked(target, record, write_context=write_context)
        return token

    def _validate_state(
        self,
        state: dict[str, Any] | None,
        *,
        proposal: dict[str, Any],
        current_body: str,
        allow_expired_after_validated_at: str = "",
    ) -> dict[str, Any]:
        if not state:
            raise PermanentPromotionError("token_not_found")
        if state.get("status") != "open":
            raise PermanentPromotionError(f"token_{state.get('status')}")
        if state.get("proposal_id") != proposal.get("proposal_id") or state.get("target_id") != proposal.get("target_id"):
            raise PermanentPromotionError("token_binding_mismatch")
        if state.get("content_hash") != content_hash(current_body):
            raise PermanentPromotionError("content_hash_mismatch")
        if state.get("dossier_snapshot_hash") != proposal.get("dossier_snapshot_hash"):
            raise PermanentPromotionError("dossier_snapshot_mismatch")
        expiry = parse_timestamp(state.get("expires_at"))
        if expiry is None:
            raise PermanentPromotionError("token_expired")
        validated_at = parse_timestamp(allow_expired_after_validated_at)
        comparison = validated_at or self.clock().astimezone(timezone.utc)
        if expiry <= comparison:
            raise PermanentPromotionError("token_expired")
        return state

    def validate(self, token: str, *, proposal: dict[str, Any], current_body: str) -> dict[str, Any]:
        if str(token).startswith("oa_"):
            raise PermanentPromotionError("legacy_token")
        return self._validate_state(
            self._states().get(content_hash(token)),
            proposal=proposal,
            current_body=current_body,
        )

    def _consume_hash_locked(
        self,
        target: Path,
        token_hash: str,
        *,
        operation_id: str = "",
        write_context: AutomaticWriteContext | None = None,
    ) -> dict[str, Any]:
        state = self._states().get(token_hash)
        if not state:
            raise PermanentPromotionError("token_not_found")
        if state.get("status") == "consumed" and operation_id and state.get("operation_id") == operation_id:
            return state
        if state.get("status") != "open":
            raise PermanentPromotionError(f"token_{state.get('status')}")
        event: dict[str, Any] = {
            "schema_version": TOKEN_SCHEMA_VERSION,
            "token_hash": token_hash,
            "status": "consumed",
            "updated_at": utc_timestamp(self.clock()),
        }
        if operation_id:
            event["operation_id"] = operation_id
        return self._append_locked(target, event, write_context=write_context)

    def consume(
        self,
        token: str,
        *,
        operation_id: str = "",
        write_context: AutomaticWriteContext | None = None,
    ) -> dict[str, Any]:
        token_hash = content_hash(token)
        with locked_jsonl_file(self.path) as target:
            return self._consume_hash_locked(
                target,
                token_hash,
                operation_id=operation_id,
                write_context=write_context,
            )

    def complete_consume_by_hash(
        self,
        token_hash: str,
        *,
        operation_id: str,
        write_context: AutomaticWriteContext | None = None,
    ) -> dict[str, Any]:
        with locked_jsonl_file(self.path) as target:
            return self._consume_hash_locked(
                target,
                token_hash,
                operation_id=operation_id,
                write_context=write_context,
            )

    def sweep_expired(
        self,
        *,
        now: datetime | None = None,
        write_context: AutomaticWriteContext | None = None,
    ) -> dict[str, Any]:
        """Revoke open tokens whose expiry has already passed.

        This is the token ledger's `revoked` producer: without it, superseded or
        expired tokens stay `status="open"` forever (nominally open, actually
        dead), so the ledger grows unboundedly. Only already-expired tokens are
        swept, so a still-valid older token — which the owner may reply to across
        digest cycles — is deliberately left untouched.
        """
        current = (now or self.clock()).astimezone(timezone.utc)
        swept = 0
        with locked_jsonl_file(self.path) as target:
            for token_hash, state in self._states().items():
                if state.get("status") != "open":
                    continue
                expiry = parse_timestamp(state.get("expires_at"))
                if expiry is not None and expiry > current:
                    continue
                event = {
                    "schema_version": TOKEN_SCHEMA_VERSION,
                    "token_hash": token_hash,
                    "status": "revoked",
                    "reason": "token_expired_sweep",
                    "updated_at": utc_timestamp(current),
                }
                self._append_locked(target, event, write_context=write_context)
                swept += 1
        return {"expired_token_swept_count": swept}


class PermanentPromotionDeliveryLedger:
    """Acknowledged owner-digest exposure and bounded reminder schedule."""

    _ACK_SOURCES = frozenset({"hermes_send_receipt"})
    _REMINDER_DELAYS = (3, 7, 14, 30)

    def __init__(self, memory_os_root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self.memory_os_root = Path(memory_os_root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def path(self) -> Path:
        return self.memory_os_root / "system" / "permanent_promotion_deliveries.jsonl"

    def _events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def states(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for event in self._events():
            proposal_id = str(event.get("proposal_id") or "")
            if proposal_id:
                states[proposal_id] = {**states.get(proposal_id, {}), **event}
        return states

    def _append_locked(
        self,
        target: Any,
        event: dict[str, Any],
        *,
        write_context: AutomaticWriteContext,
    ) -> dict[str, Any]:
        payload = write_context.prepare(self.path, event)
        _append_line_under_lock(target, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return payload

    def select_due(
        self,
        proposals: list[dict[str, Any]],
        *,
        now: datetime | None = None,
        cap: int = 5,
        new_reserve: int = 3,
        reminder_reserve: int = 2,
    ) -> dict[str, Any]:
        selected_at = (now or self.clock()).astimezone(timezone.utc)
        bounded_cap = max(0, int(cap))
        requested_new = max(0, int(new_reserve))
        requested_reminder = max(0, int(reminder_reserve))
        requested_total = requested_new + requested_reminder
        if requested_total <= bounded_cap:
            bounded_new = requested_new
            bounded_reminder = requested_reminder
        elif bounded_cap == 0:
            bounded_new = 0
            bounded_reminder = 0
        elif not requested_new:
            bounded_new = 0
            bounded_reminder = min(requested_reminder, bounded_cap)
        elif not requested_reminder:
            bounded_new = min(requested_new, bounded_cap)
            bounded_reminder = 0
        elif bounded_cap == 1:
            bounded_new = int(requested_new >= requested_reminder)
            bounded_reminder = 1 - bounded_new
        else:
            proportional_new = (
                bounded_cap * requested_new + requested_total // 2
            ) // requested_total
            bounded_new = max(1, min(requested_new, bounded_cap - 1, proportional_new))
            bounded_reminder = min(requested_reminder, bounded_cap - bounded_new)
            remaining_reserve = bounded_cap - bounded_new - bounded_reminder
            if remaining_reserve > 0:
                extra_new = min(requested_new - bounded_new, remaining_reserve)
                bounded_new += extra_new
                remaining_reserve -= extra_new
            if remaining_reserve > 0:
                bounded_reminder += min(
                    requested_reminder - bounded_reminder,
                    remaining_reserve,
                )
        states = self.states()
        actionable = [
            proposal for proposal in proposals
            if str(proposal.get("status") or "") == "open"
        ]
        never_delivered = sorted(
            [item for item in actionable if str(item.get("proposal_id") or "") not in states],
            key=lambda item: (
                str(item.get("created_at") or ""),
                str(item.get("target_id") or ""),
                str(item.get("proposal_id") or ""),
            ),
        )
        due_reminders = sorted(
            [
                item for item in actionable
                if str(item.get("proposal_id") or "") in states
                and (
                    parse_timestamp(states[str(item.get("proposal_id") or "")].get("next_reminder_at"))
                    or datetime.max.replace(tzinfo=timezone.utc)
                ) <= selected_at
            ],
            key=lambda item: (
                str(states[str(item.get("proposal_id") or "")].get("next_reminder_at") or ""),
                str(item.get("target_id") or ""),
                str(item.get("proposal_id") or ""),
            ),
        )

        selected_new = never_delivered[:bounded_new]
        selected_reminders = due_reminders[:bounded_reminder]
        remaining = bounded_cap - len(selected_new) - len(selected_reminders)
        if remaining > 0:
            extra_new = never_delivered[len(selected_new):len(selected_new) + remaining]
            selected_new.extend(extra_new)
            remaining -= len(extra_new)
        if remaining > 0:
            selected_reminders.extend(
                due_reminders[len(selected_reminders):len(selected_reminders) + remaining]
            )
        return {
            "selected": selected_new + selected_reminders,
            "selected_new_count": len(selected_new),
            "selected_reminder_count": len(selected_reminders),
            "never_delivered_open_count": len(never_delivered),
            "due_reminder_count": len(due_reminders),
            "open_proposal_backlog_count": len(actionable),
        }

    def acknowledge(
        self,
        proposal_ids: list[str],
        *,
        owner_digest_delivery_id: str,
        ack_source: str,
        delivery_receipt_id: str,
        digest_id: str,
        now: datetime | None = None,
        write_context: AutomaticWriteContext | None = None,
    ) -> dict[str, Any]:
        if write_context is None:
            raise PermanentPromotionError("automatic_write_requires_execution_gate")
        if ack_source not in self._ACK_SOURCES:
            raise PermanentPromotionError("delivery_ack_source_not_allowed")
        delivery_id = str(owner_digest_delivery_id or "").strip()
        if not delivery_id:
            raise PermanentPromotionError("delivery_id_required")
        receipt_id = str(delivery_receipt_id or "").strip()
        if not receipt_id:
            raise PermanentPromotionError("delivery_receipt_required")
        bounded_digest_id = str(digest_id or "").strip()
        if not bounded_digest_id:
            raise PermanentPromotionError("delivery_digest_id_required")
        delivered_at = (now or self.clock()).astimezone(timezone.utc)
        acknowledged_count = 0
        duplicate_count = 0
        with locked_jsonl_file(self.path) as target:
            events = self._events()
            event_ids = {str(item.get("event_id") or "") for item in events}
            states: dict[str, dict[str, Any]] = {}
            for event in events:
                proposal_id = str(event.get("proposal_id") or "")
                if proposal_id:
                    states[proposal_id] = {**states.get(proposal_id, {}), **event}
            for proposal_id in dict.fromkeys(str(item or "") for item in proposal_ids):
                if not proposal_id:
                    continue
                event_id = f"proposal_delivery:{delivery_id}:{proposal_id}"
                if event_id in event_ids:
                    duplicate_count += 1
                    continue
                delivery_count = int(states.get(proposal_id, {}).get("delivery_count") or 0) + 1
                delay_index = min(delivery_count - 1, len(self._REMINDER_DELAYS) - 1)
                event = {
                    "schema_version": DELIVERY_SCHEMA_VERSION,
                    "event_id": event_id,
                    "proposal_id": proposal_id,
                    "owner_digest_delivery_id": delivery_id,
                    "digest_id": bounded_digest_id,
                    "delivery_receipt_id": receipt_id[:160],
                    "ack_source": ack_source,
                    "status": "acknowledged",
                    "delivered_at": utc_timestamp(delivered_at),
                    "delivery_count": delivery_count,
                    "next_reminder_at": utc_timestamp(
                        delivered_at + timedelta(days=self._REMINDER_DELAYS[delay_index])
                    ),
                }
                payload = self._append_locked(target, event, write_context=write_context)
                states[proposal_id] = {**states.get(proposal_id, {}), **payload}
                event_ids.add(event_id)
                acknowledged_count += 1
        return {
            "status": "ok",
            "acknowledged_count": acknowledged_count,
            "duplicate_delivery_suppressed_count": duplicate_count,
        }


class PermanentPromotionService:
    """Single proposal/token/permanent-write state machine for CLI and digest."""

    def __init__(
        self,
        store: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        v2e_enabled: bool | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if v2e_enabled is None:
            from .knob_overrides import resolve_knob as _resolve_knob

            v2e_enabled = bool(_resolve_knob(
                "v2e_enabled", default=False, roots=store.roots,
            ))
        self.v2e_enabled = bool(v2e_enabled)
        self.proposals = ProposalLedger(store.roots.memory_os_root, clock=self.clock)
        self.tokens = TokenLedger(store.roots.memory_os_root, clock=self.clock)

    def create_proposal(
        self,
        record_id: str,
        *,
        channel: str = "cli",
        origin: str | None = None,
        clearance: dict[str, Any] | None = None,
        write_context: AutomaticWriteContext | None = None,
        eligibility_item: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .crystallized import CrystallizedMemoryService, is_active_crystallized_frontmatter

        resolved_origin = str(origin or ("automatic" if channel == "owner_digest" else "owner_initiated"))
        record = CrystallizedMemoryService(self.store).find_record(record_id)
        if record is None:
            return {"status": "ineligible", "reason_codes": ["target_not_found"]}
        frontmatter = record.frontmatter
        if frontmatter.get("provisional") is not True or not is_active_crystallized_frontmatter(frontmatter):
            return {"status": "ineligible", "reason_codes": ["target_not_active_provisional"]}
        body = str(record.body or "")
        if not body.strip():
            return {"status": "ineligible", "reason_codes": ["empty_content"]}

        eligible = eligibility_item
        eligibility_report: dict[str, Any] = {}
        if eligible is None:
            eligibility_report = CrystallizedMemoryService(self.store).collect_permanent_promotion_eligibility(
                now=self.clock()
            )
            eligible = next(
                (
                    item for item in eligibility_report.get("eligible_records", [])
                    if str(item.get("record_id") or "") == str(record_id)
                ),
                None,
            )
        if eligible is None:
            rejected = next(
                (
                    item for item in eligibility_report.get("ineligible_records", [])
                    if str(item.get("record_id") or "") == str(record_id)
                ),
                None,
            )
            return {
                "status": "ineligible",
                "reason_codes": list((rejected or {}).get("reason_codes") or ["eligibility_gate_rejected"]),
            }

        proposal, created = self.proposals.create_or_get(
            target_id=record_id,
            candidate_id=str(frontmatter.get("candidate_id") or record_id),
            body=body,
            channel=channel,
            origin=resolved_origin,
            eligibility={
                "status": "eligible",
                "reason_codes": list(eligible.get("reason_codes") or ["min_age_satisfied"]),
                "age_days": int(eligible.get("age_days") or 0),
            },
            clearance=clearance,
            v2e_enabled=self.v2e_enabled,
            write_context=write_context,
        )
        return {
            "status": str(proposal.get("status") or "open"),
            "proposal": proposal,
            "proposal_id": proposal["proposal_id"],
            "idempotent": not created,
        }

    def issue_proposal_token(
        self,
        proposal: dict[str, Any],
        *,
        channel: str,
        write_context: AutomaticWriteContext | None = None,
    ) -> str:
        if str(proposal.get("status") or "") != "open":
            raise PermanentPromotionError("proposal_not_actionable")
        return self.tokens.issue(proposal, channel=channel, write_context=write_context)

    def propose(
        self,
        record_id: str,
        *,
        channel: str = "cli",
        origin: str | None = None,
        clearance: dict[str, Any] | None = None,
        write_context: AutomaticWriteContext | None = None,
    ) -> dict[str, Any]:
        resolved_origin = str(origin or "owner_initiated")
        # V2-E: resolve clearance receipt before proposing (owner path)
        if self.v2e_enabled and clearance is None:
            clearance_dict, block_reason = _resolve_clearance_for_proposal(
                self.store.roots, record_id, resolved_origin, self.v2e_enabled,
            )
            if block_reason:
                raise PermanentPromotionError(block_reason)
            clearance = clearance_dict
        created = self.create_proposal(
            record_id,
            channel=channel,
            origin=origin,
            clearance=clearance,
            write_context=write_context,
        )
        if created.get("status") == "ineligible":
            return created
        proposal = dict(created.get("proposal") or {})
        if proposal.get("status") == "deciding":
            return {
                "status": "deciding",
                "proposal_id": proposal["proposal_id"],
                "token": "",
                "idempotent": True,
            }
        token = self.issue_proposal_token(proposal, channel=channel, write_context=write_context)
        return {
            "status": "open",
            "proposal_id": proposal["proposal_id"],
            "token": token,
            "idempotent": bool(created.get("idempotent")),
        }

    def begin_decision_and_consume(
        self,
        token: str,
        action: str,
        *,
        deferred_until: str = "",
    ) -> dict[str, Any]:
        if action not in PERMANENT_DECISION_ACTIONS:
            raise PermanentPromotionError("invalid_permanent_action")
        if action == "defer":
            due = parse_timestamp(deferred_until)
            if due is None:
                raise PermanentPromotionError("invalid_deferred_until")

        token_hash = content_hash(token)
        hint = self.tokens._states().get(token_hash)
        if not hint:
            raise PermanentPromotionError("token_not_found")
        proposal_id = str(hint.get("proposal_id") or "")
        operation_id = f"ppop_{uuid4().hex}"

        # Fixed lock order: proposal then token. The pre-read above is only an
        # id hint; every security decision is revalidated while both are held.
        with locked_jsonl_file(self.proposals.proposals_path) as proposal_target:
            with locked_jsonl_file(self.tokens.path) as token_target:
                proposal = self.proposals._states().get(proposal_id)
                token_state = self.tokens._states().get(token_hash)
                if not proposal:
                    raise PermanentPromotionError("proposal_not_found")
                status = str(proposal.get("status") or "")
                if status in PROPOSAL_TERMINAL_STATUSES:
                    return proposal
                if status == "deciding":
                    if str(proposal.get("decision_action") or "") != action:
                        raise PermanentPromotionError("proposal_deciding")
                    return proposal
                if status != "open":
                    raise PermanentPromotionError("proposal_not_actionable")

                from .crystallized import CrystallizedMemoryService

                record = CrystallizedMemoryService(self.store).find_record(str(proposal.get("target_id") or ""))
                if record is None:
                    raise PermanentPromotionError("target_not_found")
                validated = self.tokens._validate_state(
                    token_state,
                    proposal=proposal,
                    current_body=record.body,
                )
                intent = {
                    "schema_version": PROPOSAL_SCHEMA_VERSION,
                    "proposal_id": proposal_id,
                    "status": "deciding",
                    "decision_action": action,
                    "operation_id": operation_id,
                    "decision_token_hash": token_hash,
                    "token_validated_at": utc_timestamp(self.clock()),
                    "token_expires_at": str(validated.get("expires_at") or ""),
                    "updated_at": utc_timestamp(self.clock()),
                }
                if deferred_until:
                    intent["deferred_until"] = deferred_until
                intent_payload = self.proposals._append_locked(proposal_target, intent)
                self.tokens._consume_hash_locked(
                    token_target,
                    token_hash,
                    operation_id=operation_id,
                )
                claimed = {**proposal, **intent_payload}
        self.proposals._write_open_snapshot()
        return claimed

    def _resume_decision(
        self,
        proposal: dict[str, Any],
        *,
        write_context: AutomaticWriteContext | None = None,
        recovered: bool = False,
    ) -> dict[str, Any]:
        action = str(proposal.get("decision_action") or "")
        operation_id = str(proposal.get("operation_id") or "")
        token_hash = str(proposal.get("decision_token_hash") or "")
        if not action or not operation_id:
            raise PermanentPromotionError("decision_intent_incomplete")
        if token_hash:
            self.tokens.complete_consume_by_hash(
                token_hash,
                operation_id=operation_id,
                write_context=write_context,
            )

        if action in {"reject", "defer"}:
            status = "rejected" if action == "reject" else "deferred"
            terminal = self.proposals.append_terminal(
                str(proposal["proposal_id"]),
                status,
                deferred_until=str(proposal.get("deferred_until") or ""),
                operation_id=operation_id,
                result_ref={"canonical_state_changed": False},
                recovered=recovered,
                write_context=write_context,
            )
            return self._result_from_state(terminal)

        from .crystallized import (
            CrystallizedMemoryService,
            _PERMANENT_PROMOTION_WRITE_CAPABILITY,
            is_active_crystallized_frontmatter,
        )

        crystallized = CrystallizedMemoryService(self.store)
        record = crystallized.find_record(str(proposal.get("target_id") or ""))
        if record is None:
            terminal = self.proposals.append_terminal(
                str(proposal["proposal_id"]),
                "expired",
                reason="target_retired",
                operation_id=operation_id,
                recovered=recovered,
                write_context=write_context,
            )
            return self._result_from_state(terminal)
        frontmatter = record.frontmatter
        if frontmatter.get("provisional") is not True:
            if (
                str(frontmatter.get("permanent_promotion_proposal_id") or "")
                == str(proposal.get("proposal_id") or "")
                and content_hash(record.body) == str(proposal.get("content_hash") or "")
            ):
                terminal = self.proposals.append_terminal(
                    str(proposal["proposal_id"]),
                    "approved",
                    operation_id=operation_id,
                    result_ref={"canonical_state_changed": False},
                    recovered=recovered,
                    write_context=write_context,
                )
                return self._result_from_state(terminal)
            raise PermanentPromotionError("target_confirmed_by_different_proposal")
        if not is_active_crystallized_frontmatter(frontmatter):
            terminal = self.proposals.append_terminal(
                str(proposal["proposal_id"]),
                "expired",
                reason="target_retired",
                operation_id=operation_id,
                recovered=recovered,
                write_context=write_context,
            )
            return self._result_from_state(terminal)

        self._validate_approve_intent(
            proposal,
            token_hash=token_hash,
            current_body=record.body,
        )
        # ── A0: when owner approved over conflict, pass contested_refs ──
        clearance = proposal.get("clearance") if isinstance(proposal.get("clearance"), dict) else {}
        contested_refs = (
            list(clearance.get("conflict_refs") or [])
            if clearance.get("contested") or clearance.get("owner_override")
            else None
        )

        result = crystallized._confirm_provisional_record_from_permanent_service(
            str(proposal["target_id"]),
            proposal_id=str(proposal["proposal_id"]),
            capability=_PERMANENT_PROMOTION_WRITE_CAPABILITY,
            confirmed_by="owner",
            contested_refs=contested_refs,
            now=self.clock(),
        )
        terminal = self.proposals.append_terminal(
            str(proposal["proposal_id"]),
            "approved",
            operation_id=operation_id,
            result_ref={"canonical_state_changed": bool(result.get("canonical_state_changed"))},
            recovered=recovered,
            write_context=write_context,
        )
        return self._result_from_state(terminal)

    def _validate_approve_intent(
        self,
        proposal: dict[str, Any],
        *,
        token_hash: str,
        current_body: str,
    ) -> None:
        """Validate durable proposal/token state before the canonical write."""
        proposal_id = str(proposal.get("proposal_id") or "")
        target_id = str(proposal.get("target_id") or "")
        projected = self.proposals._states().get(proposal_id, {})
        token_state = self.tokens._states().get(str(token_hash or ""), {})
        operation_id = str(projected.get("operation_id") or "")
        expected_content_hash = content_hash(current_body)
        if (
            not proposal_id
            or not target_id
            or not token_hash
            or str(projected.get("status") or "") not in {"deciding", "approved"}
            or str(projected.get("decision_action") or "") != "approve"
            or not operation_id
            or str(projected.get("target_id") or "") != target_id
            or str(projected.get("content_hash") or "") != expected_content_hash
            or str(projected.get("decision_token_hash") or "") != token_hash
        ):
            raise PermanentPromotionError("authorization_proposal_binding_mismatch")
        if (
            str(token_state.get("status") or "") != "consumed"
            or str(token_state.get("proposal_id") or "") != proposal_id
            or str(token_state.get("target_id") or "") != target_id
            or str(token_state.get("content_hash") or "") != expected_content_hash
            or str(token_state.get("dossier_snapshot_hash") or "")
            != str(projected.get("dossier_snapshot_hash") or "")
            or str(token_state.get("operation_id") or "") != operation_id
        ):
            raise PermanentPromotionError("authorization_token_binding_mismatch")

    def _act(self, token: str, action: str, *, deferred_until: str = "") -> dict[str, Any]:
        proposal = self.begin_decision_and_consume(
            token,
            action,
            deferred_until=deferred_until,
        )
        if str(proposal.get("status") or "") in PROPOSAL_TERMINAL_STATUSES:
            return self._result_from_state(proposal)
        return self._resume_decision(proposal)

    def approve(self, token: str) -> dict[str, Any]:
        return self._act(token, "approve")

    def reject(self, token: str) -> dict[str, Any]:
        return self._act(token, "reject")

    def defer(self, token: str, *, until: str) -> dict[str, Any]:
        return self._act(token, "defer", deferred_until=until)

    def inspect_action_token(self, token: str) -> dict[str, Any]:
        token_state = self.tokens._states().get(content_hash(token))
        if not token_state:
            raise PermanentPromotionError("token_not_found")
        proposal = self.proposals._states().get(str(token_state.get("proposal_id") or ""))
        if not proposal:
            raise PermanentPromotionError("proposal_not_found")
        if str(proposal.get("status") or "") in PROPOSAL_TERMINAL_STATUSES:
            return self._result_from_state(proposal)
        from .crystallized import CrystallizedMemoryService

        record = CrystallizedMemoryService(self.store).find_record(str(proposal.get("target_id") or ""))
        if record is None:
            raise PermanentPromotionError("target_not_found")
        self.tokens.validate(token, proposal=proposal, current_body=record.body)
        return {
            "status": str(proposal.get("status") or "open"),
            "proposal_id": str(proposal.get("proposal_id") or ""),
            "record_id": str(proposal.get("target_id") or ""),
            "canonical_state_changed": False,
        }

    def reconcile(self, *, write_context: AutomaticWriteContext | None = None) -> dict[str, Any]:
        """Autonomously converge incomplete decisions and retired targets."""
        from .execution_gate import (
            complete_execution_gate_envelope,
            execution_gate_scope_hash,
            start_execution_gate_envelope,
        )

        pending = [
            state for state in self.proposals._states().values()
            if state.get("status") in {"open", "deciding"}
        ]
        scope = {
            "operation": "permanent_promotion_reconcile",
            "target_type": PERMANENT_PROMOTION_TARGET_TYPE,
            "proposal_ids": sorted(str(item.get("proposal_id") or "") for item in pending)[:100],
            "writes": ["proposal_terminal", "token_consume_repair", "token_expired_sweep"],
        }
        owns_context = write_context is None
        if owns_context:
            permit = start_execution_gate_envelope(
                self.store,
                lane_id=PERMANENT_PROMOTION_LANE_ID,
                trigger_surface="owner_review_digest_preassembly",
                risk_class=PERMANENT_PROMOTION_RISK_CLASS,
                human_approval_required=False,
                why_no_human_approval="reconcile only completes recorded owner decisions or target-retirement bookkeeping",
                scope=scope,
                boundary={
                    "actual_send": False,
                    "actual_execute": False,
                    "actual_identity_write": False,
                    "actual_unapproved_crystallized_approval": False,
                    "automatic_permanent_promotion": False,
                },
            )
            context = AutomaticWriteContext(
                store=self.store,
                envelope_id=str(permit["execution_gate_envelope_id"]),
                scope_hash=execution_gate_scope_hash(scope),
            )
        else:
            context = write_context
        report: dict[str, Any] = {
            "status": "ok",
            "open_proposal_count": len(pending),
            "decision_recovery_attempt_count": 0,
            "decision_recovery_success_count": 0,
            "decision_recovery_failure_count": 0,
            "approved_reconcile_count": 0,
            "target_retired_close_count": 0,
            "expired_token_swept_count": 0,
            "error_records": [],
            "execution_gate_envelope_id": context.envelope_id,
        }
        from .crystallized import CrystallizedMemoryService, is_active_crystallized_frontmatter

        crystallized = CrystallizedMemoryService(self.store)
        for state in pending:
            proposal_id = str(state.get("proposal_id") or "")
            try:
                if state.get("status") == "deciding":
                    report["decision_recovery_attempt_count"] += 1
                    result = self._resume_decision(state, write_context=context, recovered=True)
                    report["decision_recovery_success_count"] += 1
                    if result.get("status") == "approved":
                        report["approved_reconcile_count"] += 1
                    elif result.get("status") == "expired":
                        report["target_retired_close_count"] += 1
                    continue

                record = crystallized.find_record(str(state.get("target_id") or ""))
                if record is not None and record.frontmatter.get("provisional") is not True:
                    if (
                        str(record.frontmatter.get("permanent_promotion_proposal_id") or "") == proposal_id
                        and content_hash(record.body) == str(state.get("content_hash") or "")
                    ):
                        self.proposals.append_terminal(
                            proposal_id,
                            "approved",
                            reason="confirmed_target_recovered",
                            result_ref={"canonical_state_changed": False},
                            recovered=True,
                            write_context=context,
                        )
                        report["approved_reconcile_count"] += 1
                        continue
                if record is None or not is_active_crystallized_frontmatter(record.frontmatter):
                    self.proposals.append_terminal(
                        proposal_id,
                        "expired",
                        reason="target_retired",
                        recovered=True,
                        write_context=context,
                    )
                    report["target_retired_close_count"] += 1
            except Exception as exc:
                report["decision_recovery_failure_count"] += 1
                report["error_records"].append({
                    "proposal_id": proposal_id,
                    "error_code": type(exc).__name__,
                    "message": str(exc)[:200],
                })
                append_audit(
                    self.store.roots.audit_path,
                    action="permanent_promotion_reconcile_failed",
                    status="error",
                    target=proposal_id,
                    details={"error_code": type(exc).__name__, "message": str(exc)[:200]},
                )
        try:
            sweep = self.tokens.sweep_expired(now=self.clock(), write_context=context)
            report["expired_token_swept_count"] = int(sweep.get("expired_token_swept_count") or 0)
        except Exception as exc:
            report["error_records"].append({
                "proposal_id": "",
                "error_code": type(exc).__name__,
                "message": str(exc)[:200],
            })
            append_audit(
                self.store.roots.audit_path,
                action="permanent_promotion_token_sweep_failed",
                status="error",
                target="",
                details={"error_code": type(exc).__name__, "message": str(exc)[:200]},
            )
        if report["decision_recovery_failure_count"] or report["error_records"]:
            report["status"] = "partial"
        if owns_context:
            complete_execution_gate_envelope(
                self.store,
                envelope_id=context.envelope_id,
                lane_id=PERMANENT_PROMOTION_LANE_ID,
                execution_status="completed" if report["status"] == "ok" else "partial",
                postcheck={
                    "actual_send": False,
                    "actual_execute": False,
                    "actual_identity_write": False,
                    "actual_unapproved_crystallized_approval": False,
                    "automatic_permanent_promotion": False,
                },
                result_summary={
                    key: value for key, value in report.items()
                    if key.endswith("_count") or key == "status"
                },
            )
        return report

    @staticmethod
    def _result_from_state(state: dict[str, Any]) -> dict[str, Any]:
        result_ref = state.get("result_ref") if isinstance(state.get("result_ref"), dict) else {}
        result = {
            "status": str(state.get("status") or "unknown"),
            "proposal_id": str(state.get("proposal_id") or ""),
            "record_id": str(state.get("target_id") or ""),
            "canonical_state_changed": bool(result_ref.get("canonical_state_changed")),
        }
        if state.get("deferred_until"):
            result["deferred_until"] = str(state.get("deferred_until") or "")
        if state.get("reason"):
            result["reason"] = str(state.get("reason") or "")
        if state.get("operation_id"):
            result["operation_id"] = str(state.get("operation_id") or "")
        return result


def _bounded_result_ref(value: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key)[:80]: item
        for key, item in value.items()
        if isinstance(item, (str, int, float, bool)) or item is None
    }


def preview_permanent_promotion_delivery(
    store: Any,
    *,
    now: datetime | None = None,
    cap: int = 5,
    new_reserve: int = 3,
    reminder_reserve: int = 2,
) -> dict[str, Any]:
    """Project the delivery queue without creating proposals or tokens."""
    from .crystallized import CrystallizedMemoryService, is_active_crystallized_frontmatter

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    crystallized = CrystallizedMemoryService(store)
    eligibility = crystallized.collect_permanent_promotion_eligibility(
        now=current,
        dry_run=True,
    )
    eligible_by_record = {
        str(item.get("record_id") or ""): item
        for item in eligibility.get("eligible_records", [])
        if str(item.get("record_id") or "")
    }
    service = PermanentPromotionService(store, clock=lambda: current)
    open_proposals: list[dict[str, Any]] = []
    for state in service.proposals._states().values():
        if state.get("status") != "open":
            continue
        target = crystallized.find_record(str(state.get("target_id") or ""))
        if (
            target is not None
            and target.frontmatter.get("provisional") is True
            and is_active_crystallized_frontmatter(target.frontmatter)
        ):
            open_proposals.append(state)
    existing_targets = {str(item.get("target_id") or "") for item in open_proposals}
    synthetic = [
        {
            "proposal_id": "preview_" + content_hash(record_id)[:24],
            "target_id": record_id,
            "status": "open",
            "created_at": utc_timestamp(current),
            "eligibility": item,
            "preview_only": True,
        }
        for record_id, item in eligible_by_record.items()
        if record_id not in existing_targets
    ]
    queue = PermanentPromotionDeliveryLedger(
        store.roots.memory_os_root,
        clock=lambda: current,
    ).select_due(
        open_proposals + synthetic,
        now=current,
        cap=cap,
        new_reserve=new_reserve,
        reminder_reserve=reminder_reserve,
    )
    items: list[dict[str, Any]] = []
    for proposal in queue["selected"]:
        record_id = str(proposal.get("target_id") or "")
        record = crystallized.find_record(record_id)
        if record is None:
            continue
        eligibility_data = (
            proposal.get("eligibility")
            if isinstance(proposal.get("eligibility"), dict)
            else eligible_by_record.get(record_id, {})
        )
        body = str(record.body or "")
        items.append({
            "review_item_id": str(proposal.get("proposal_id") or ""),
            "target_type": PERMANENT_PROMOTION_TARGET_TYPE,
            "target_id": str(proposal.get("proposal_id") or ""),
            "proposal_id": str(proposal.get("proposal_id") or ""),
            "record_id": record_id,
            "source_module": "permanent_promotion",
            "priority": "action_required",
            "created_at": str(proposal.get("created_at") or utc_timestamp(current)),
            "created_at_source": "permanent_promotion_preview",
            "summary": body[:1000],
            "proposed_memory": body[:1000],  # render (_render_review_item) re-bounds to 1000; the gate
            "age_days": int(eligibility_data.get("age_days") or 0),
            "eligibility_reason_codes": list(eligibility_data.get("reason_codes") or []),
            "action_token": "",
            "action_token_available": False,
            "preview_only": True,
            "delivery_eligible": True,
            "raw_body_included": False,
        })
    return {
        "status": "preview",
        "items": items,
        "proposal_would_create_count": len(synthetic),
        "proposal_reused_count": len(open_proposals),
        "automatic_permanent_promotion_count": 0,
        **{key: value for key, value in queue.items() if key != "selected"},
    }


def prepare_permanent_promotion_delivery(
    store: Any,
    *,
    delivery_ref: str,
    now: datetime | None = None,
    cap: int = 5,
    new_reserve: int = 3,
    reminder_reserve: int = 2,
    v2e_enabled: bool | None = None,
) -> dict[str, Any]:
    """Prepare permanent-only review items without acknowledging delivery."""
    from .crystallized import CrystallizedMemoryService
    from .execution_gate import (
        complete_execution_gate_envelope,
        execution_gate_scope_hash,
        start_execution_gate_envelope,
    )

    from .knob_overrides import resolve_knob as _resolve_knob

    # Resolve v2e_enabled from knob when not explicitly passed
    if v2e_enabled is None:
        v2e_enabled = bool(_resolve_knob(
            "v2e_enabled", default=False, roots=store.roots,
        ))

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    crystallized = CrystallizedMemoryService(store)
    eligibility = crystallized.collect_permanent_promotion_eligibility(now=current)
    candidate_ids = sorted(
        str(item.get("record_id") or "")
        for item in eligibility.get("eligible_records", [])
        if str(item.get("record_id") or "")
    )
    service = PermanentPromotionService(store, clock=lambda: current, v2e_enabled=v2e_enabled)
    pending_ids = sorted(
        str(item.get("proposal_id") or "")
        for item in service.proposals._states().values()
        if item.get("status") in {"open", "deciding"}
    )
    scope = {
        "operation": "prepare_permanent_promotion_delivery",
        "delivery_ref": str(delivery_ref or "")[:160],
        "eligible_record_ids": candidate_ids[:500],
        "pending_proposal_ids": pending_ids[:500],
        "writes": ["proposal_create", "proposal_reconcile", "token_issue"],
    }
    permit = start_execution_gate_envelope(
        store,
        lane_id=PERMANENT_PROMOTION_LANE_ID,
        trigger_surface="owner_review_digest_preassembly",
        risk_class=PERMANENT_PROMOTION_RISK_CLASS,
        human_approval_required=False,
        why_no_human_approval="only prepares bounded owner-review proposals; permanent confirmation remains owner-token gated",
        scope=scope,
        boundary={
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "automatic_permanent_promotion": False,
        },
    )
    context = AutomaticWriteContext(
        store=store,
        envelope_id=str(permit["execution_gate_envelope_id"]),
        scope_hash=execution_gate_scope_hash(scope),
    )
    report: dict[str, Any] = {
        "status": "ok",
        "items": [],
        "automatic_permanent_promotion_count": 0,
        "proposal_created_count": 0,
        "proposal_reused_count": 0,
        "proposal_skipped_count": 0,
        "error_records": [],
        "execution_gate_envelope_id": context.envelope_id,
    }
    try:
        reconcile = service.reconcile(write_context=context)
        report["reconcile"] = reconcile
        for key, value in reconcile.items():
            if key.endswith("_count"):
                report[key] = int(value or 0)
        report.setdefault("clearance_blocked_count", 0)
        report.setdefault("clearance_blocked", [])
        for item in eligibility.get("eligible_records", []):
            record_id = str(item.get("record_id") or "")
            try:
                # V2-E: resolve clearance receipt before proposing
                clearance_dict, block_reason = _resolve_clearance_for_proposal(
                    store.roots, record_id, "automatic", v2e_enabled,
                )
                if block_reason:
                    report["proposal_skipped_count"] += 1
                    report["clearance_blocked_count"] += 1
                    report["clearance_blocked"].append({
                        "record_id": record_id,
                        "reason": block_reason,
                    })
                    continue
                created = service.create_proposal(
                    record_id,
                    channel="owner_digest",
                    origin="automatic",
                    write_context=context,
                    eligibility_item=item,
                    clearance=clearance_dict,
                )
                if created.get("status") == "ineligible":
                    report["proposal_skipped_count"] += 1
                elif created.get("idempotent"):
                    report["proposal_reused_count"] += 1
                else:
                    report["proposal_created_count"] += 1
            except PermanentPromotionError as exc:
                report["proposal_skipped_count"] += 1
                if str(exc) not in {"automatic_reproposal_rejected", "content_already_permanent"}:
                    report["error_records"].append({"record_id": record_id, "reason_code": str(exc)})

        open_proposals = [
            state for state in service.proposals._states().values()
            if state.get("status") == "open"
        ]
        delivery_ledger = PermanentPromotionDeliveryLedger(
            store.roots.memory_os_root,
            clock=lambda: current,
        )
        queue = delivery_ledger.select_due(
            open_proposals,
            now=current,
            cap=cap,
            new_reserve=new_reserve,
            reminder_reserve=reminder_reserve,
        )
        report.update({key: value for key, value in queue.items() if key != "selected"})
        for proposal in queue["selected"]:
            record = crystallized.find_record(str(proposal.get("target_id") or ""))
            if record is None:
                continue
            token = service.issue_proposal_token(
                proposal,
                channel="owner_digest",
                write_context=context,
            )
            eligibility_data = proposal.get("eligibility") if isinstance(proposal.get("eligibility"), dict) else {}
            body = str(record.body or "")
            item: dict[str, Any] = {
                "review_item_id": str(proposal.get("proposal_id") or ""),
                "target_type": PERMANENT_PROMOTION_TARGET_TYPE,
                "target_id": str(proposal.get("proposal_id") or ""),
                "proposal_id": str(proposal.get("proposal_id") or ""),
                "record_id": str(proposal.get("target_id") or ""),
                "source_module": "permanent_promotion",
                "priority": "action_required",
                "created_at": str(proposal.get("created_at") or utc_timestamp(current)),
                "created_at_source": "permanent_promotion_proposal",
                "summary": body[:1000],
                "proposed_memory": body[:1000],
                "age_days": int(eligibility_data.get("age_days") or 0),
                "eligibility_reason_codes": list(eligibility_data.get("reason_codes") or []),
                "action_token": token,
                "delivery_eligible": True,
                "raw_body_included": False,
            }

            # ── B1: Dossier enrichment (gated by dossier_enrichment_enabled) ─
            if _resolve_knob("dossier_enrichment_enabled", default=False, roots=store.roots):
                from .evidence_profile import build_evidence_profile

                fm = dict(record.frontmatter or {})
                clearance = (
                    proposal.get("clearance")
                    if isinstance(proposal.get("clearance"), dict)
                    else {}
                )
                item["evidence_profile"] = build_evidence_profile(
                    subject_ref=str(proposal.get("target_id") or ""),
                    subject_kind=str(fm.get("kind") or "item"),
                    source_ref=str(fm.get("approved_by") or ""),
                    evidence_summary=body[:200],
                    tags=list(fm.get("tags") or []),
                    provenance=str(fm.get("provenance", {}).get("source_class", "observed") if isinstance(fm.get("provenance"), dict) else "observed"),
                )
                item["stability_basis"] = str(
                    eligibility_data.get("stability_basis") or "provisional_age"
                )
                item["stability_value_days"] = int(eligibility_data.get("age_days") or 0)
                item["clearance_summary"] = {
                    "verdict": str(clearance.get("verdict") or clearance.get("status") or "unavailable"),
                    "receipt_id": str(clearance.get("receipt_id") or ""),
                    "conflict_refs": list(clearance.get("conflict_refs") or []),
                }
                item["exposure"] = "unavailable"

            report["items"].append(item)
    except Exception:
        complete_execution_gate_envelope(
            store,
            envelope_id=context.envelope_id,
            lane_id=PERMANENT_PROMOTION_LANE_ID,
            execution_status="failed",
            postcheck={"automatic_permanent_promotion": False, "actual_send": False},
            result_summary={"status": "failed", "automatic_permanent_promotion_count": 0},
        )
        raise
    if report["error_records"] or report.get("reconcile", {}).get("status") != "ok":
        report["status"] = "partial"
    complete_execution_gate_envelope(
        store,
        envelope_id=context.envelope_id,
        lane_id=PERMANENT_PROMOTION_LANE_ID,
        execution_status="completed" if report["status"] == "ok" else "partial",
        postcheck={
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "automatic_permanent_promotion": False,
        },
        result_summary={
            key: value for key, value in report.items()
            if key.endswith("_count") or key == "status"
        },
    )
    return report


def acknowledge_permanent_promotion_delivery(
    store: Any,
    *,
    verified_receipt: _VerifiedHostDeliveryReceipt,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record exposure only for a claim-bound receipt verified by owner_actions."""
    from .execution_gate import (
        complete_execution_gate_envelope,
        execution_gate_scope_hash,
        start_execution_gate_envelope,
    )

    if not isinstance(verified_receipt, _VerifiedHostDeliveryReceipt):
        raise PermanentPromotionError("verified_delivery_receipt_required")
    clean_ids = sorted({
        str(value or "")
        for value in verified_receipt.proposal_ids
        if str(value or "")
    })
    if not clean_ids:
        return {
            "status": "ok",
            "acknowledged_count": 0,
            "duplicate_delivery_suppressed_count": 0,
        }
    scope = {
        "operation": "acknowledge_permanent_promotion_delivery",
        "owner_digest_delivery_id": verified_receipt.delivery_ref[:160],
        "digest_id": verified_receipt.digest_id[:160],
        "ack_source": "hermes_send_receipt",
        "delivery_receipt_id": verified_receipt.receipt_id[:160],
        "delivery_receipt_status": verified_receipt.receipt_status[:40],
        "proposal_ids": clean_ids[:500],
        "writes": ["permanent_promotion_delivery_ack"],
    }
    permit = start_execution_gate_envelope(
        store,
        lane_id=PERMANENT_PROMOTION_LANE_ID,
        trigger_surface="owner_review_digest_delivery_ack",
        risk_class=PERMANENT_PROMOTION_RISK_CLASS,
        human_approval_required=False,
        why_no_human_approval="acknowledges exposure only; it cannot decide or promote memory",
        scope=scope,
        boundary={
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "automatic_permanent_promotion": False,
        },
    )
    context = AutomaticWriteContext(
        store=store,
        envelope_id=str(permit["execution_gate_envelope_id"]),
        scope_hash=execution_gate_scope_hash(scope),
    )
    try:
        result = PermanentPromotionDeliveryLedger(
            store.roots.memory_os_root,
            clock=(lambda: now.astimezone(timezone.utc)) if now is not None else None,
        ).acknowledge(
            clean_ids,
            owner_digest_delivery_id=verified_receipt.delivery_ref,
            ack_source="hermes_send_receipt",
            delivery_receipt_id=verified_receipt.receipt_id,
            digest_id=verified_receipt.digest_id,
            now=now,
            write_context=context,
        )
    except Exception:
        complete_execution_gate_envelope(
            store,
            envelope_id=context.envelope_id,
            lane_id=PERMANENT_PROMOTION_LANE_ID,
            execution_status="failed",
            postcheck={"automatic_permanent_promotion": False, "actual_send": False},
            result_summary={"status": "failed", "acknowledged_count": 0},
        )
        raise
    complete_execution_gate_envelope(
        store,
        envelope_id=context.envelope_id,
        lane_id=PERMANENT_PROMOTION_LANE_ID,
        execution_status="completed",
        postcheck={
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "automatic_permanent_promotion": False,
        },
        result_summary=result,
    )
    result["execution_gate_envelope_id"] = context.envelope_id
    return result


def read_permanent_promotion_ledger_counts(memory_os_root: Path) -> dict[str, Any]:
    """Bounded permanent-promotion proposal/token ledger state counts.

    Diagnostics only — the ledgers are the source of truth; these are a
    read-only projection for monitor visibility. Last-status-wins per id.

    Lives in this plugin module (not in the monitor script) so it is part
    of the deployed runtime and callable from a remote-host SSH probe, not
    only from a local monitor run.
    """
    root = Path(memory_os_root)

    def _events(path: Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not path.exists():
            return records
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            records.append(event)
        return records

    def _final_states(events: list[dict[str, Any]], id_key: str) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for event in events:
            key = str(event.get(id_key) or "")
            if key:
                states[key] = {**states.get(key, {}), **event}
        return states

    def _tally(states: dict[str, dict[str, Any]], keys: tuple[str, ...]) -> dict[str, int]:
        tally = {key: 0 for key in keys}
        for state in states.values():
            status = str(state.get("status") or "")
            tally[status] = tally.get(status, 0) + 1
        return tally

    def _parse_ts(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)
    proposal_events = _events(root / "system" / "permanent_promotion_proposals.jsonl")
    token_events = _events(root / "system" / "owner_action_tokens.jsonl")
    delivery_events = _events(root / "system" / "permanent_promotion_deliveries.jsonl")
    proposals = _final_states(proposal_events, "proposal_id")
    tokens = _final_states(token_events, "token_hash")
    deliveries = _final_states(delivery_events, "proposal_id")
    open_states = {
        proposal_id: state for proposal_id, state in proposals.items()
        if state.get("status") == "open"
    }
    deciding_states = {
        proposal_id: state for proposal_id, state in proposals.items()
        if state.get("status") == "deciding"
    }
    never_delivered = {
        proposal_id: state for proposal_id, state in open_states.items()
        if proposal_id not in deliveries
    }
    due_reminder_count = sum(
        1 for proposal_id in open_states
        if proposal_id in deliveries
        and (_parse_ts(deliveries[proposal_id].get("next_reminder_at")) or datetime.max.replace(tzinfo=timezone.utc))
        <= now
    )
    open_bindings = {
        (str(state.get("target_id") or ""), str(state.get("content_hash") or ""))
        for state in open_states.values()
    }
    deferred_past_due_count = sum(
        1 for state in proposals.values()
        if state.get("status") == "deferred"
        and (_parse_ts(state.get("deferred_until")) or datetime.max.replace(tzinfo=timezone.utc)) <= now
        and (str(state.get("target_id") or ""), str(state.get("content_hash") or "")) not in open_bindings
    )

    stale_open_count = 0
    stale_open_evaluation_status = "ok"
    stale_open_evaluation_error_code = ""
    try:
        from plugins.memory.memory_os.crystallized import (
            CrystallizedMemoryService,
            is_active_crystallized_frontmatter,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(root.parent, profile="monitor"))
        crystallized = CrystallizedMemoryService(store)
        for state in open_states.values():
            record = crystallized.find_record(str(state.get("target_id") or ""))
            if (
                record is None
                or record.frontmatter.get("provisional") is not True
                or not is_active_crystallized_frontmatter(record.frontmatter)
                or hashlib.sha256(record.body.encode("utf-8")).hexdigest()
                != str(state.get("content_hash") or "")
            ):
                stale_open_count += 1
    except Exception as exc:
        # No Silent Failures: record the failure class so the monitor can
        # surface that stale_open_proposal_count above is an un-evaluated
        # zero (evaluation never ran), not a verified-clean zero.
        stale_open_evaluation_status = "unavailable"
        stale_open_evaluation_error_code = type(exc).__name__

    latest_recovery: dict[str, Any] = {}
    for event in _events(root / "system" / "execution_gate_envelopes.jsonl"):
        summary = event.get("result_summary") if isinstance(event.get("result_summary"), dict) else {}
        if (
            event.get("stage") == "completion"
            and event.get("lane_id") == "permanent_promotion_producer"
            and "decision_recovery_attempt_count" in summary
        ):
            latest_recovery = summary
    recovered_events = [event for event in proposal_events if event.get("recovered") is True]
    recovery_success_count = int(
        (latest_recovery.get("decision_recovery_success_count") or 0)
        if latest_recovery
        else len(recovered_events)
    )
    recovery_failure_count = int(latest_recovery.get("decision_recovery_failure_count") or 0)
    recovery_attempt_count = int(
        (latest_recovery.get("decision_recovery_attempt_count") or 0)
        if latest_recovery
        else recovery_success_count + recovery_failure_count
    )

    def _oldest_age_days(states: dict[str, dict[str, Any]], key: str) -> int | None:
        values = [_parse_ts(state.get(key)) for state in states.values()]
        parsed = [value for value in values if value is not None]
        if not parsed:
            return None
        return max(int((now - min(parsed)).total_seconds() // 86400), 0)

    delivery_event_ids = [str(event.get("event_id") or "") for event in delivery_events if event.get("event_id")]
    return {
        "proposal_ledger_counts": _tally(
            proposals, ("open", "deciding", "approved", "rejected", "deferred", "revoked", "expired")
        ),
        "token_ledger_counts": _tally(tokens, ("open", "consumed", "revoked", "expired")),
        "open_proposal_backlog_count": len(open_states),
        "never_delivered_open_count": len(never_delivered),
        "due_reminder_count": due_reminder_count,
        "deferred_past_due_count": deferred_past_due_count,
        "deciding_proposal_count": len(deciding_states),
        "decision_recovery_attempt_count": recovery_attempt_count,
        "decision_recovery_success_count": recovery_success_count,
        "decision_recovery_failure_count": recovery_failure_count,
        "stale_open_proposal_count": stale_open_count,
        "stale_open_evaluation_status": stale_open_evaluation_status,
        "stale_open_evaluation_error_code": stale_open_evaluation_error_code,
        "target_retired_close_count": sum(
            1 for event in proposal_events
            if event.get("status") == "expired" and event.get("reason") == "target_retired"
        ),
        "approved_reconcile_count": sum(
            1 for event in proposal_events
            if event.get("status") == "approved"
            and (event.get("recovered") is True or event.get("reason") == "confirmed_target_recovered")
        ),
        "duplicate_delivery_suppressed_count": len(delivery_event_ids) - len(set(delivery_event_ids)),
        "oldest_open_proposal_age_days": _oldest_age_days(open_states, "created_at"),
        "oldest_never_delivered_age_days": _oldest_age_days(never_delivered, "created_at"),
        "oldest_delivery_age_days": _oldest_age_days(deliveries, "delivered_at"),
    }
