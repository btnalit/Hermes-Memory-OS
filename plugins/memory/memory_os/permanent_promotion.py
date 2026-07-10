"""Ledger-backed permanent-promotion domain contract (Living Memory V2-0)."""
from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .jsonl_io import _append_line_under_lock, locked_jsonl_file, write_jsonl_atomic_locked

PROPOSAL_SCHEMA_VERSION = "memory-os.permanent-promotion-proposal.v1"
TOKEN_SCHEMA_VERSION = "memory-os.permanent-promotion-token.v1"
PERMANENT_PROMOTION_TARGET_TYPE = "permanent_memory_promotion"
PERMANENT_ACTIONS = frozenset({"propose", "approve", "reject", "defer"})


class PermanentPromotionError(ValueError):
    """Raised with a stable fail-closed reason code."""


def utc_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise PermanentPromotionError("timestamp_must_be_timezone_aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


def build_proposal_record(
    *,
    proposal_id: str,
    target_id: str,
    candidate_id: str,
    body: str,
    created_at: str,
    channel: str,
    evidence_profile_version: str = "v2-0-existing-eligibility",
    eligibility: dict[str, Any] | None = None,
    clearance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_action_target("propose", PERMANENT_PROMOTION_TARGET_TYPE)
    if not proposal_id.startswith("ppm_") or not target_id or not candidate_id:
        raise PermanentPromotionError("invalid_proposal_binding")
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
        "eligibility": eligibility or {"status": "eligible", "reason_codes": []},
        # V2-E does not exist yet. Owner-initiated CLI records this explicit
        # carve-out; automatic callers will be refused by the service layer.
        "clearance": clearance or {"status": "unavailable", "reason_code": "v2e_not_enabled"},
    }
    snapshot_input = {key: value for key, value in record.items() if key != "dossier_snapshot_hash"}
    record["dossier_snapshot_hash"] = canonical_json_hash(snapshot_input)
    return record


class ProposalLedger:
    """Append-only proposal events plus atomically-derived open snapshot."""

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
        opens = [state for state in self._states().values() if state.get("status") == "open"]
        write_jsonl_atomic_locked(self.open_snapshot_path, sorted(opens, key=lambda item: str(item["created_at"])))

    def create_or_get(self, *, target_id: str, candidate_id: str, body: str, channel: str) -> tuple[dict[str, Any], bool]:
        if channel != "cli":
            raise PermanentPromotionError("automatic_proposal_generation_blocked_pre_v2e")
        body_hash = content_hash(body)
        evidence_version = "v2-0-existing-eligibility"
        # Interleave read/idempotency/append under one lock to prevent duplicate opens.
        with locked_jsonl_file(self.proposals_path) as target:
            states = self._states()
            existing_open: dict[str, Any] | None = None
            for existing in states.values():
                if existing.get("status") == "open" and existing.get("content_hash") == body_hash and existing.get("evidence_profile_version") == evidence_version:
                    existing_open = existing
                    break
            if existing_open is not None:
                proposal, created = existing_open, False
            else:
                proposal = build_proposal_record(
                    proposal_id=make_proposal_id(), target_id=target_id, candidate_id=candidate_id,
                    body=body, created_at=utc_timestamp(self.clock()), channel=channel,
                )
                _append_line_under_lock(target, json.dumps(proposal, ensure_ascii=False, sort_keys=True) + "\n")
                created = True
        # Always (re)derive the open snapshot from the ledger so a prior failed
        # snapshot write self-heals on the next call — the snapshot is a derived
        # projection, never the source of truth.
        self._write_open_snapshot()
        return proposal, created

    def append_terminal(self, proposal_id: str, status: str, *, deferred_until: str = "") -> None:
        if status not in {"approved", "rejected", "deferred", "revoked", "expired"}:
            raise PermanentPromotionError("invalid_terminal_proposal_status")
        event = {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal_id": proposal_id, "status": status, "updated_at": utc_timestamp(self.clock())}
        if deferred_until:
            event["deferred_until"] = deferred_until
        with locked_jsonl_file(self.proposals_path) as target:
            _append_line_under_lock(target, json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        self._write_open_snapshot()


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

    def issue(self, proposal: dict[str, Any], *, channel: str, expires_at: datetime | None = None) -> str:
        if channel != "cli" or proposal.get("status") != "open":
            raise PermanentPromotionError("token_issuance_not_allowed")
        token = issue_token()
        now = self.clock()
        from datetime import timedelta
        expiry = expires_at or (now + timedelta(hours=24))
        record = {
            "schema_version": TOKEN_SCHEMA_VERSION, "token_hash": content_hash(token),
            "proposal_id": proposal["proposal_id"], "target_type": PERMANENT_PROMOTION_TARGET_TYPE,
            "target_id": proposal["target_id"], "content_hash": proposal["content_hash"],
            "dossier_snapshot_hash": proposal["dossier_snapshot_hash"], "issued_at": utc_timestamp(now),
            "expires_at": utc_timestamp(expiry), "channel": channel, "status": "open",
        }
        with locked_jsonl_file(self.path) as target:
            _append_line_under_lock(target, json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return token

    def validate(self, token: str, *, proposal: dict[str, Any], current_body: str) -> dict[str, Any]:
        if str(token).startswith("oa_"):
            raise PermanentPromotionError("legacy_token")
        state = self._states().get(content_hash(token))
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
        try:
            expiry = datetime.fromisoformat(str(state["expires_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            raise PermanentPromotionError("token_expired")
        if expiry <= self.clock().astimezone(timezone.utc):
            raise PermanentPromotionError("token_expired")
        return state

    def consume(self, token: str) -> dict[str, Any]:
        token_hash = content_hash(token)
        state = self._states().get(token_hash)
        if not state:
            raise PermanentPromotionError("token_not_found")
        if state.get("status") != "open":
            raise PermanentPromotionError(f"token_{state.get('status')}")
        event = {"schema_version": TOKEN_SCHEMA_VERSION, "token_hash": token_hash, "status": "consumed", "updated_at": utc_timestamp(self.clock())}
        with locked_jsonl_file(self.path) as target:
            _append_line_under_lock(target, json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event


@dataclass(frozen=True)
class PermanentPromotionAuthorization:
    proposal_id: str
    target_id: str
    token_hash: str


class PermanentPromotionService:
    """Single owner-initiated proposal/token/permanent-write route."""

    def __init__(self, store: Any, *, clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.proposals = ProposalLedger(store.roots.memory_os_root, clock=self.clock)
        self.tokens = TokenLedger(store.roots.memory_os_root, clock=self.clock)

    def propose(self, record_id: str, *, channel: str = "cli") -> dict[str, Any]:
        from .crystallized import CrystallizedMemoryService, is_active_crystallized_frontmatter
        record = CrystallizedMemoryService(self.store).find_record(record_id)
        if record is None:
            return {"status": "ineligible", "reason_codes": ["target_not_found"]}
        frontmatter = record.frontmatter
        if frontmatter.get("provisional") is not True or not is_active_crystallized_frontmatter(frontmatter):
            return {"status": "ineligible", "reason_codes": ["target_not_active_provisional"]}
        body = str(record.body or "")
        if not body.strip():
            return {"status": "ineligible", "reason_codes": ["empty_content"]}
        proposal, created = self.proposals.create_or_get(
            target_id=record_id, candidate_id=str(frontmatter.get("candidate_id") or record_id), body=body, channel=channel
        )
        token = self.tokens.issue(proposal, channel=channel) if created else ""
        return {"status": "open", "proposal_id": proposal["proposal_id"], "token": token, "idempotent": not created}

    def approve(self, token: str) -> dict[str, Any]:
        # Validate first, burn token before markdown write (safe crash direction).
        token_hash = content_hash(token)
        state = self.tokens._states().get(token_hash)
        if not state:
            raise PermanentPromotionError("token_not_found")
        proposal = self.proposals._states().get(str(state.get("proposal_id") or ""))
        if not proposal or proposal.get("status") != "open":
            raise PermanentPromotionError("proposal_closed")
        from .crystallized import CrystallizedMemoryService
        record = CrystallizedMemoryService(self.store).find_record(str(proposal["target_id"]))
        if record is None:
            raise PermanentPromotionError("target_not_found")
        self.tokens.validate(token, proposal=proposal, current_body=record.body)
        self.tokens.consume(token)
        authorization = PermanentPromotionAuthorization(proposal["proposal_id"], proposal["target_id"], token_hash)
        result = CrystallizedMemoryService(self.store).confirm_provisional_record(proposal["target_id"], authorization=authorization)
        self.proposals.append_terminal(proposal["proposal_id"], "approved")
        return {"status": "approved", "proposal_id": proposal["proposal_id"], "record_id": proposal["target_id"], "canonical_state_changed": bool(result.get("canonical_state_changed"))}

    def _close_without_write(self, token: str, status: str, *, until: str = "") -> dict[str, Any]:
        token_hash = content_hash(token)
        state = self.tokens._states().get(token_hash)
        if not state:
            raise PermanentPromotionError("token_not_found")
        proposal = self.proposals._states().get(str(state.get("proposal_id") or ""))
        if not proposal or proposal.get("status") != "open":
            raise PermanentPromotionError("proposal_closed")
        if until:
            try: datetime.fromisoformat(until.replace("Z", "+00:00"))
            except ValueError: raise PermanentPromotionError("invalid_deferred_until")
        self.tokens.consume(token)
        self.proposals.append_terminal(proposal["proposal_id"], status, deferred_until=until)
        return {"status": status, "proposal_id": proposal["proposal_id"], "record_id": proposal["target_id"], "canonical_state_changed": False, "deferred_until": until}

    def reject(self, token: str) -> dict[str, Any]:
        return self._close_without_write(token, "rejected")

    def defer(self, token: str, *, until: str) -> dict[str, Any]:
        return self._close_without_write(token, "deferred", until=until)
