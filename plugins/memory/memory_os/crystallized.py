"""Owner-approved crystallized-memory service."""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4

from .approval import ApprovalDecision, ApprovalPurpose
from .audit import append_audit
from .jsonl_io import append_jsonl_locked, append_jsonl_lines_locked, locked_jsonl_file, _append_line_under_lock
from .ids import new_crystallized_id
from .schema import CRYSTALLIZED_SCHEMA_VERSION
from .store import MemoryOSStore, _format_frontmatter
from .review_content_safety import permanent_promotion_forbidden_reason_codes


INACTIVE_CANONICAL_STATES = {
    "owner_revoked", "revoked", "demoted",
    "provisional_expired", "provisional_cap_evicted",
    "provisional_rejected",
    "superseded",  # V2-B: demoted by supersession (owner_assertion conflict resolution)
}

# Triage action types for candidate_aggregation lane
CANDIDATE_TRIAGE_ACTIONS = frozenset({"promote", "demote", "fleeting", "discard", "flag", "dedup_absorb"})
CANDIDATE_TRIAGE_FILE = "candidate_triage.jsonl"

# Default TTL for auto-demote (72 hours)
CANDIDATE_DEMOTE_TTL_SECONDS = 259200


class CrystallizedApprovalError(ValueError):
    """Raised when a candidate lacks crystallized-memory approval."""


_PERMANENT_PROMOTION_WRITE_CAPABILITY = object()
_RESOLVER_PROVISIONAL_WRITE_CAPABILITY = object()
_PROBE_PROVISIONAL_WRITE_CAPABILITY = object()


def _read_jsonl_dict_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _validate_consumed_owner_write_context(
    store: MemoryOSStore,
    owner_action_context: dict[str, Any] | None,
    *,
    candidate: CrystallizedCandidate,
    decision: ApprovalDecision,
) -> bool:
    """Revalidate a consumed Owner action without importing owner_actions.

    Keeping this verification on canonical ledgers avoids a crystallized ↔
    owner_actions import cycle and, more importantly, avoids trusting a Python
    object as permanent-write authority.
    """

    if not isinstance(owner_action_context, dict):
        return False
    context = owner_action_context.get("owner_write_context")
    if not isinstance(context, dict):
        return False
    required = {
        "digest_id",
        "reply_ingress_id",
        "owner_id",
        "channel",
        "action_type",
        "target_type",
        "target_id",
    }
    if any(not context.get(key) for key in required):
        return False
    if decision.reviewer != str(context.get("owner_id") or ""):
        return False

    action_type = str(context.get("action_type") or "")
    target_type = str(context.get("target_type") or "")
    target_id = str(context.get("target_id") or "")
    if action_type in {"approve_candidate", "approve_external_evidence"}:
        if target_type != "candidate" or target_id != candidate.candidate_id:
            return False
    elif action_type == "approve_candidate_cluster":
        action_context = owner_action_context.get("action_context")
        if not isinstance(action_context, dict):
            return False
        scope = action_context.get("candidate_cluster_scope")
        if not isinstance(scope, dict):
            return False
        if f"{scope.get('cluster_id', '')}:{scope.get('scope_hash', '')}" != target_id:
            return False
        members = scope.get("member_candidate_ids")
        if not isinstance(members, list) or candidate.candidate_id not in {str(value) for value in members}:
            return False
    else:
        return False

    token_binding = owner_action_context.get("token_binding")
    if not isinstance(token_binding, dict):
        return False
    digest_id = str(context.get("digest_id") or "")
    owner_id = str(context.get("owner_id") or "")
    channel = str(context.get("channel") or "")
    token_hash = str(token_binding.get("action_token_hash") or "")
    review_item_id = str(token_binding.get("review_item_id") or "")
    digest_path = store.roots.memory_os_root / "system" / "owner_review_rendered_digests.jsonl"
    digest_record = next(
        (
            record
            for record in reversed(_read_jsonl_dict_records(digest_path))
            if str(record.get("digest_id") or "") == digest_id
            and str(record.get("owner_id") or "") == owner_id
            and str(record.get("channel") or "") == channel
        ),
        None,
    )
    if digest_record is None:
        return False
    rendered = digest_record.get("rendered_digest")
    if not isinstance(rendered, dict):
        return False
    sections = rendered.get("sections")
    if not isinstance(sections, dict):
        return False
    token_match = False
    for section_items in sections.values():
        if not isinstance(section_items, list):
            continue
        for item in section_items:
            if not isinstance(item, dict) or str(item.get("review_item_id") or "") != review_item_id:
                continue
            actions = item.get("action_tokens")
            targets = item.get("action_targets")
            if not isinstance(actions, dict) or not isinstance(targets, dict):
                continue
            token = str(actions.get(action_type) or "")
            target = targets.get(action_type)
            if not token or not isinstance(target, dict):
                continue
            token_match = (
                hashlib.sha256(token.encode("utf-8")).hexdigest() == token_hash
                and str(target.get("target_type") or "") == target_type
                and str(target.get("target_id") or "") == target_id
            )
            if token_match:
                break
        if token_match:
            break
    if not token_match:
        return False

    consumption_path = store.roots.memory_os_root / "system" / "owner_action_context_consumptions.jsonl"
    return any(
        str(record.get("status") or "") == "consumed"
        and str(record.get("context_id") or "") == str(owner_action_context.get("owner_write_context_id") or "")
        and all(str(record.get(key) or "") == str(context.get(key) or "") for key in (
            "digest_id", "owner_id", "channel", "action_type", "target_type", "target_id"
        ))
        for record in _read_jsonl_dict_records(consumption_path)
    )


def _canonical_transition_locked(method):
    """Serialize every in-place canonical Markdown state transition.

    Confirmation, TTL/cap retirement, revoke, demote, and provisional renewal
    all rewrite the same canonical files.  A shared sidecar lock makes each
    method re-read and compare state after the previous contender commits.
    """

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        lock_target = self.store.roots.crystallized_root / ".canonical_transition"
        with locked_jsonl_file(lock_target):
            return method(self, *args, **kwargs)

    return wrapped


def _emit_corpus_change_event(store: Any, change_type: str, record_id: str) -> None:
    """Emit a corpus change event after a permanent state transition.

    Called from crystallized write paths after the canonical write succeeds.
    Fail-open: errors are audited but never block the canonical write.
    """
    try:
        from .clearance_receipts import append_corpus_change_event

        append_corpus_change_event(store.roots, change_type, record_id)
    except Exception:
        from .audit import append_audit

        try:
            append_audit(
                store.roots.audit_path,
                action="corpus_change_event_emit_failed",
                status="warning",
                target=record_id,
                details={"change_type": change_type},
            )
        except Exception:
            pass


@dataclass(frozen=True)
class CrystallizedCandidate:
    candidate_id: str
    kind: str
    body: str
    source_event_ids: list[str]
    sensitivity: str = "private"
    tags: list[str] | None = None
    bridge_state: str = ""
    created_at: str = ""
    rejection_count: int = 0
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class EffectiveCandidate:
    """Read-only projection of one candidate's current governance state."""

    candidate: CrystallizedCandidate
    effective_state: str
    latest_triage: dict[str, Any] | None
    owner_review_eligible: bool
    terminal: bool
    exclusion_reason: str


@dataclass(frozen=True)
class CrystallizedRecord:
    file_name: str
    frontmatter: dict[str, Any]
    body: str


@dataclass(frozen=True)
class CrystallizedWriteReceipt:
    path: Path
    record_id: str


class CrystallizedMemoryService:
    """Write and read owner-approved long-term memory records."""

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    @_canonical_transition_locked
    def write_approved_record(
        self,
        candidate: CrystallizedCandidate,
        decision: ApprovalDecision,
        *,
        file_name: str,
        now: datetime | None = None,
        capability: object | None = None,
        owner_action_context: dict[str, Any] | None = None,
        return_receipt: bool = False,
    ) -> Path | CrystallizedWriteReceipt:
        self._ensure_crystallized_approval(candidate, decision)
        if decision.provisional:
            allowed = (
                capability is _RESOLVER_PROVISIONAL_WRITE_CAPABILITY
                or capability is _PROBE_PROVISIONAL_WRITE_CAPABILITY
            )
            if not allowed:
                raise CrystallizedApprovalError("invalid provisional write capability")
        else:
            # Permanent canonical authority is not a module singleton.  The
            # Owner-action ingress must first bind and consume one recorded
            # digest action context; the validator re-checks that durable
            # context against this exact candidate and decision.
            if not _validate_consumed_owner_write_context(
                self.store,
                owner_action_context,
                candidate=candidate,
                decision=decision,
            ):
                raise CrystallizedApprovalError("invalid or unconsumed owner action context")
        created_at = _timestamp(now)
        provenance = dict(candidate.provenance or {})
        from .provenance import candidate_external_ref, is_tainted

        external_ref = candidate_external_ref(candidate, store=self.store) or ""
        if not provenance and is_tainted(candidate, store=self.store):
            provenance = {"source_class": "external_evidence"}
            if external_ref:
                provenance["external_ref"] = external_ref
        frontmatter = {
            "schema_version": CRYSTALLIZED_SCHEMA_VERSION,
            "id": new_crystallized_id(_datetime(now)),
            "candidate_id": candidate.candidate_id,
            "kind": candidate.kind,
            "created_at": created_at,
            "approved_by": decision.reviewer,
            "approved_at": decision.reviewed_at,
            "approval_purpose": decision.purpose.value,
            "approval_note": decision.note,
            "source_event_ids": list(candidate.source_event_ids),
            "tags": list(candidate.tags or []),
            "sensitivity": candidate.sensitivity,
            "hindsight_indexed": False,
            "bridge_state": candidate.bridge_state or decision.source_state,
        }
        if decision.provisional:
            expires = (decision.expires_at or "").strip()
            if not expires:
                raise CrystallizedApprovalError(
                    "provisional crystallized record requires a valid expires_at"
                )
            # TTL validation: moment records prescribed by
            # docs/resolver/hermes-memory-os-source-gate-quality-spec.md §S2.
            # The cap is applied at auto-generation time (auto_promote), not
            # here — owner-approved expires_at values are preserved as-is.
            frontmatter["provisional"] = True
            frontmatter["expires_at"] = expires
            frontmatter["recurrence"] = str(decision.recurrence)
        if provenance:
            frontmatter["provenance"] = provenance
        if decision.external_evidence_ack:
            frontmatter["external_evidence_ack"] = True
            frontmatter["acked_external_ref"] = decision.acked_external_ref or ""
        path = self.store.append_crystallized_record(file_name, frontmatter, candidate.body)
        append_audit(
            self.store.roots.audit_path,
            action="crystallized_record_written",
            status="ok",
            target=str(path),
            details={
                "record_id": frontmatter["id"],
                "candidate_id": candidate.candidate_id,
                "approval_purpose": decision.purpose.value,
                "source_event_ids": list(candidate.source_event_ids),
                "external_evidence_ack": bool(decision.external_evidence_ack),
                "acked_external_ref": decision.acked_external_ref or "",
                "external_ref": external_ref,
            },
        )
        _emit_corpus_change_event(
            self.store,
            "supersede" if decision.provisional else "add",
            frontmatter["id"],
        )
        if return_receipt:
            return CrystallizedWriteReceipt(path=path, record_id=str(frontmatter["id"]))
        return path

    def read_records(self, file_name: str) -> list[CrystallizedRecord]:
        path = self.store.roots.crystallized_root / file_name
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        records = [
            CrystallizedRecord(file_name=file_name, frontmatter=frontmatter, body=body)
            for frontmatter, body in _parse_markdown_records(raw)
        ]
        # P3: fail-loud — non-empty file yielding 0 records is not silent
        if raw.strip() and not records:
            from plugins.memory.memory_os.audit import append_audit

            append_audit(
                self.store.roots.audit_path,
                action="crystallized_file_unparseable",
                status="warning",
                target=str(path),
                details={
                    "file_name": file_name,
                    "error_code": "crystallized_file_unparseable",
                },
            )
        return records

    def find_record(self, record_id: str) -> CrystallizedRecord | None:
        normalized = str(record_id or "").strip()
        if not normalized or not self.store.roots.crystallized_root.exists():
            return None
        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            for record in self.read_records(path.name):
                if str(record.frontmatter.get("id") or "") == normalized:
                    return record
        return None

    def find_records_by_candidate_id(self, candidate_id: str) -> list[CrystallizedRecord]:
        """Return all crystallized records with the given candidate_id, if any."""
        normalized = str(candidate_id or "").strip()
        if not normalized or not self.store.roots.crystallized_root.exists():
            return []
        results: list[CrystallizedRecord] = []
        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            for record in self.read_records(path.name):
                if str(record.frontmatter.get("candidate_id") or "") == normalized:
                    results.append(record)
        return results

    @_canonical_transition_locked
    def revoke_record(
        self,
        record_id: str,
        *,
        revoked_by: str,
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = str(record_id or "").strip()
        if not normalized:
            raise KeyError("crystallized record id is required")
        if not self.store.roots.crystallized_root.exists():
            raise KeyError(normalized)

        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records = self.read_records(path.name)
            rendered: list[str] = []
            changed = False
            matched: dict[str, Any] | None = None
            for current in records:
                frontmatter = dict(current.frontmatter)
                if str(frontmatter.get("id") or "") == normalized:
                    matched = {
                        "record_id": normalized,
                        "file_name": current.file_name,
                        "already_revoked": not is_active_crystallized_frontmatter(frontmatter),
                    }
                    if is_active_crystallized_frontmatter(frontmatter):
                        frontmatter["canonical_state"] = "owner_revoked"
                        frontmatter["revoked_by"] = revoked_by
                        frontmatter["revoked_at"] = _timestamp(now)
                        frontmatter["revocation_reason"] = reason
                        changed = True
                rendered.append(_format_frontmatter(frontmatter))
                rendered.append("")
                rendered.append(current.body.rstrip())
                rendered.append("")
            if matched is None:
                continue
            if changed:
                tmp_path = path.with_name(f"{path.name}.{normalized}.revoke.tmp")
                try:
                    tmp_path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
                    tmp_path.replace(path)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
                # C2: update index canonical_state (best-effort)
                try:
                    from ._canonical_state_sync import update_canonical_state_in_index
                    update_canonical_state_in_index(
                        self.store.roots.index_path, normalized, "owner_revoked",
                    )
                except Exception:
                    pass
                append_audit(
                    self.store.roots.audit_path,
                    action="crystallized_record_revoked",
                    status="ok",
                    target=str(path),
                    details={
                        "record_id": normalized,
                        "revoked_by": revoked_by,
                    },
                )
                # Invalidate all active edges involving the revoked node (守 G3)
                from .jsonl_io import read_jsonl
                edges_path = self.store.roots.memory_os_root / "graph" / "edges.jsonl"
                changed_edges = 0
                if edges_path.exists():
                    # Hold the same sidecar lock used by governed edge appenders
                    # across the entire read/modify/write transaction.  Locking
                    # only the final rewrite can discard an append that lands
                    # after the read but before replacement.
                    with locked_jsonl_file(edges_path):
                        edges = read_jsonl(str(edges_path))
                        invalidated_at = datetime.now(timezone.utc).isoformat()
                        for edge in edges:
                            if (edge.get("from_record_id") == normalized or edge.get("to_record_id") == normalized) \
                                    and edge.get("state") == "active":
                                edge["state"] = "invalidated"
                                edge["invalidated_at"] = invalidated_at
                                changed_edges += 1
                        if changed_edges:
                            from .jsonl_io import write_jsonl
                            write_jsonl(edges_path, edges, ensure_parent=False)
                    if changed_edges:
                        append_audit(
                            self.store.roots.audit_path,
                            action="node_edges_invalidated",
                            status="ok",
                            target=normalized,
                            details={"invalidated_count": changed_edges},
                        )
            if changed:
                _emit_corpus_change_event(self.store, "revoke", normalized)
            matched["canonical_state_changed"] = changed
            return matched
        raise KeyError(normalized)

    @_canonical_transition_locked
    def demote_record(
        self,
        record_id: str,
        *,
        demoted_by: str,
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = str(record_id or "").strip()
        if not normalized:
            raise KeyError("crystallized record id is required")
        if not self.store.roots.crystallized_root.exists():
            raise KeyError(normalized)

        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records = self.read_records(path.name)
            rendered: list[str] = []
            changed = False
            matched: dict[str, Any] | None = None
            for current in records:
                frontmatter = dict(current.frontmatter)
                if str(frontmatter.get("id") or "") == normalized:
                    matched = {
                        "record_id": normalized,
                        "file_name": current.file_name,
                        "already_demoted": not is_active_crystallized_frontmatter(frontmatter),
                    }
                    if is_active_crystallized_frontmatter(frontmatter):
                        frontmatter["canonical_state"] = "demoted"
                        frontmatter["demoted_by"] = demoted_by
                        frontmatter["demoted_at"] = _timestamp(now)
                        frontmatter["demotion_reason"] = reason
                        changed = True
                rendered.append(_format_frontmatter(frontmatter))
                rendered.append("")
                rendered.append(current.body.rstrip())
                rendered.append("")
            if matched is None:
                continue
            if changed:
                tmp_path = path.with_name(f"{path.name}.{normalized}.demote.tmp")
                try:
                    tmp_path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
                    tmp_path.replace(path)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
                # C2: update index canonical_state (best-effort)
                try:
                    from ._canonical_state_sync import update_canonical_state_in_index
                    update_canonical_state_in_index(
                        self.store.roots.index_path, normalized, "demoted",
                    )
                except Exception:
                    pass
                append_audit(
                    self.store.roots.audit_path,
                    action="crystallized_record_demoted",
                    status="ok",
                    target=str(path),
                    details={
                        "record_id": normalized,
                        "demoted_by": demoted_by,
                    },
                )
            if changed:
                _emit_corpus_change_event(self.store, "retire", normalized)
            matched["canonical_state_changed"] = changed
            return matched
        raise KeyError(normalized)

    @_canonical_transition_locked
    def invalidate_provisional_record(
        self,
        record_id: str,
        *,
        reason: str,
        invalidated_by: str = "provisional_sweep",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Invalidate a provisional crystallized record (invalidate-not-delete).

        Sets canonical_state based on reason and adds invalidation metadata.
        The record remains on disk — only its active status changes.

        Valid reasons:
          - "resolver_ttl_expired" → canonical_state = "provisional_expired"
          - "resolver_cap_evicted" → canonical_state = "provisional_cap_evicted"
          - "owner_rejected" → canonical_state = "provisional_rejected"
        """
        normalized = str(record_id or "").strip()
        if not normalized:
            raise KeyError("crystallized record id is required")
        if not self.store.roots.crystallized_root.exists():
            raise KeyError(normalized)

        state_map = {
            "resolver_ttl_expired": "provisional_expired",
            "resolver_cap_evicted": "provisional_cap_evicted",
            "owner_rejected": "provisional_rejected",
        }
        target_state = state_map.get(reason)
        if target_state is None:
            raise ValueError(
                f"invalid reason: {reason!r}; expected one of {list(state_map.keys())}"
            )

        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records = self.read_records(path.name)
            rendered: list[str] = []
            changed = False
            matched: dict[str, Any] | None = None
            for current in records:
                frontmatter = dict(current.frontmatter)
                if str(frontmatter.get("id") or "") == normalized:
                    matched = {
                        "record_id": normalized,
                        "file_name": current.file_name,
                        "already_invalidated": (
                            frontmatter.get("provisional") is not True
                            or not is_active_crystallized_frontmatter(frontmatter)
                        ),
                    }
                    if (
                        frontmatter.get("provisional") is True
                        and is_active_crystallized_frontmatter(frontmatter)
                    ):
                        frontmatter["canonical_state"] = target_state
                        frontmatter["invalidated_at"] = _timestamp(now)
                        frontmatter["invalidated_by"] = invalidated_by
                        frontmatter["invalidation_reason"] = reason
                        changed = True
                rendered.append(_format_frontmatter(frontmatter))
                rendered.append("")
                rendered.append(current.body.rstrip())
                rendered.append("")
            if matched is None:
                continue
            if changed:
                tmp_path = path.with_name(f"{path.name}.{normalized}.invalidate.tmp")
                try:
                    tmp_path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
                    tmp_path.replace(path)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
                # C2: update index canonical_state (best-effort)
                try:
                    from ._canonical_state_sync import update_canonical_state_in_index
                    update_canonical_state_in_index(
                        self.store.roots.index_path, normalized, target_state,
                    )
                except Exception:
                    pass
                append_audit(
                    self.store.roots.audit_path,
                    action="provisional_record_invalidated",
                    status="ok",
                    target=str(path),
                    details={
                        "record_id": normalized,
                        "reason": reason,
                        "invalidated_by": invalidated_by,
                    },
                )
            if changed:
                _emit_corpus_change_event(self.store, "retire", normalized)
            matched["canonical_state_changed"] = changed
            return matched
        raise KeyError(normalized)

    def confirm_provisional_record(
        self,
        record_id: str,
        *,
        authorization: Any | None = None,
        confirmed_by: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Reject direct canonical confirmation; the promotion service owns it."""
        raise CrystallizedApprovalError(
            "permanent confirmation must use PermanentPromotionService"
        )

    @_canonical_transition_locked
    def _confirm_provisional_record_from_permanent_service(
        self,
        record_id: str,
        *,
        proposal_id: str,
        capability: object,
        confirmed_by: str = "",
        contested_refs: list[str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Apply a service-validated permanent-promotion transition.

        When *contested_refs* is provided (owner approved over conflict),
        the frontmatter records the conflict pair for the A0 contested
        projection index.
        """
        if capability is not _PERMANENT_PROMOTION_WRITE_CAPABILITY:
            raise CrystallizedApprovalError("invalid permanent promotion write capability")
        normalized = str(record_id or "").strip()
        normalized_proposal_id = str(proposal_id or "").strip()
        if not normalized_proposal_id:
            raise CrystallizedApprovalError("permanent promotion proposal id is required")
        if not normalized:
            raise KeyError("crystallized record id is required")
        if not self.store.roots.crystallized_root.exists():
            raise KeyError(normalized)

        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records = self.read_records(path.name)
            rendered: list[str] = []
            changed = False
            matched: dict[str, Any] | None = None
            for current in records:
                frontmatter = dict(current.frontmatter)
                if str(frontmatter.get("id") or "") == normalized:
                    matched = {
                        "record_id": normalized,
                        "file_name": current.file_name,
                    }
                    if frontmatter.get("provisional") is True:
                        if frontmatter.get("canonical_state") in (
                            "provisional_expired", "provisional_cap_evicted", "provisional_rejected",
                        ):
                            raise CrystallizedApprovalError("evidence_increment_unavailable")
                        frontmatter["provisional"] = False
                        frontmatter["expires_at"] = ""
                        frontmatter["confirmed_by"] = "owner"
                        frontmatter["confirmed_at"] = _timestamp(now)
                        frontmatter["permanent_promotion_proposal_id"] = normalized_proposal_id
                        if contested_refs:
                            frontmatter["contested_refs"] = list(contested_refs)
                        changed = True
                    else:
                        confirmed_proposal_id = str(
                            frontmatter.get("permanent_promotion_proposal_id") or ""
                        )
                        requested_proposal_id = normalized_proposal_id
                        if confirmed_proposal_id != requested_proposal_id:
                            raise CrystallizedApprovalError(
                                "record already confirmed by different permanent proposal"
                            )
                rendered.append(_format_frontmatter(frontmatter))
                rendered.append("")
                rendered.append(current.body.rstrip())
                rendered.append("")
            if matched is None:
                continue
            if changed:
                tmp_path = path.with_name(f"{path.name}.{normalized}.confirm.tmp")
                try:
                    tmp_path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
                    tmp_path.replace(path)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
                append_audit(
                    self.store.roots.audit_path,
                    action="provisional_record_confirmed",
                    status="ok",
                    target=str(path),
                    details={
                        "record_id": normalized,
                        "confirmed_by": confirmed_by,
                    },
                )
            if changed:
                _emit_corpus_change_event(self.store, "supersede", normalized)
            matched["canonical_state_changed"] = changed
            return matched
        raise KeyError(normalized)

    @_canonical_transition_locked
    def bump_recurrence_and_renew(
        self,
        record_id: str,
        *,
        max_renewals: int = 10,
        now: datetime | None = None,
        execution_gate_envelope_id: str = "",
    ) -> dict[str, Any]:
        """recurrence += 1; expires_at = now + 7d (renew); write audit.

        Exceeds max_renewals -> returns requires_owner_decision=True, no renewal.
        Only operates on provisional records (guard: provisional is True).
        """
        from datetime import timedelta

        _now = now or datetime.now(timezone.utc)
        normalized = str(record_id or "").strip()
        if not normalized:
            raise KeyError("crystallized record id is required")
        if not self.store.roots.crystallized_root.exists():
            raise KeyError(normalized)

        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records = self.read_records(path.name)
            rendered: list[str] = []
            changed = False
            matched: dict[str, Any] | None = None
            for current in records:
                frontmatter = dict(current.frontmatter)
                if str(frontmatter.get("id") or "") == normalized:
                    # Guard: only operate on provisional records
                    if frontmatter.get("provisional") is not True:
                        matched = {
                            "record_id": normalized,
                            "file_name": current.file_name,
                            "renewed": False,
                            "requires_owner_decision": False,
                            "current_recurrence": 0,
                            "error": "not_provisional",
                        }
                        continue
                    matched = {"record_id": normalized, "file_name": current.file_name}
                    current_recurrence = 0
                    try:
                        current_recurrence = int(frontmatter.get("recurrence", 0))
                    except (ValueError, TypeError):
                        pass

                    if current_recurrence >= max_renewals:
                        matched["renewed"] = False
                        matched["requires_owner_decision"] = True
                        matched["current_recurrence"] = current_recurrence
                    else:
                        frontmatter["recurrence"] = str(current_recurrence + 1)
                        frontmatter["expires_at"] = (_now + timedelta(days=7)).isoformat()
                        frontmatter["last_renewed_at"] = _timestamp(_now)
                        matched["renewed"] = True
                        matched["requires_owner_decision"] = False
                        matched["current_recurrence"] = current_recurrence + 1
                        changed = True

                rendered.append(_format_frontmatter(frontmatter))
                rendered.append("")
                rendered.append(current.body.rstrip())
                rendered.append("")

            if matched is None:
                continue
            if changed:
                tmp_path = path.with_name(f"{path.name}.{normalized}.renew.tmp")
                try:
                    tmp_path.write_text(
                        "\n".join(rendered).rstrip() + "\n", encoding="utf-8"
                    )
                    tmp_path.replace(path)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
                append_audit(
                    self.store.roots.audit_path,
                    action="provisional_renewed",
                    status="ok",
                    target=str(path),
                    details={
                        "record_id": normalized,
                        "recurrence": matched["current_recurrence"],
                        "max_renewals": max_renewals,
                        "execution_gate_envelope_id": str(execution_gate_envelope_id or ""),
                    },
                )
            return matched
        raise KeyError(normalized)

    def list_provisional_records(self) -> list[dict[str, Any]]:
        """Return all active provisional crystallized records.

        Active provisional = provisional=True AND canonical_state not inactive.
        Used by provisional_sweep to find records subject to TTL/cap eviction.
        """
        results: list[dict[str, Any]] = []
        if not self.store.roots.crystallized_root.exists():
            return results
        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            for record in self.read_records(path.name):
                fm = record.frontmatter
                if fm.get("provisional") is True and is_active_crystallized_frontmatter(fm):
                    results.append({
                        "id": fm.get("id", ""),
                        "candidate_id": fm.get("candidate_id", ""),
                        "provisional": True,
                        "expires_at": fm.get("expires_at", ""),
                        "approved_by": fm.get("approved_by", ""),
                        "approved_at": fm.get("approved_at", ""),
                        "body": record.body,
                        "file_name": record.file_name,
                        "canonical_state": fm.get("canonical_state", "active"),
                    })
        return results

    def collect_permanent_promotion_eligibility(
        self,
        *,
        now: datetime | None = None,
        dry_run: bool = False,
        _store_root: Path | None = None,
    ) -> dict[str, Any]:
        """Non-mutating V2-0 permanent-promotion eligibility report.

        Replaces the removed silent age-based auto-promote write. Reports which
        provisional records the legacy age rule *would* have promoted — a
        derived ``legacy_auto_promoted`` projection — but never writes permanent
        state, never rewrites frontmatter, and never mints an owner action.
        In V2-0.5 the digest producer may automatically open a bounded proposal,
        but only an owner-bound action token may perform the permanent write.

        Governance: read-only; owner can disable via the
        ``permanent_proposal_enabled`` knob (legacy ``auto_promote_enabled``
        is migrated with a deprecation warning).
        """
        _now = _datetime(now)
        from .knob_overrides import resolve_migrated_knob

        # Resolve knobs from the store being operated on (not ambient ~/.hermes)
        # so tests with a synthetic store are isolated from the user's real overrides.
        _resolve_kwargs: dict[str, Any] = {}
        if _store_root is not None:
            _resolve_kwargs["_store_root"] = _store_root
        else:
            _resolve_kwargs["roots"] = self.store.roots

        enabled = resolve_migrated_knob(
            "permanent_proposal_enabled", True, **_resolve_kwargs
        )
        if not enabled:
            return {
                "schema_version": "memory-os.permanent_promotion_eligibility.v1",
                "status": "disabled",
                "reason": "knob permanent_proposal_enabled=False",
                "eligible_count": 0,
                "promoted_count": 0,
                "skipped_rejected_count": 0,
                "skipped_too_young_count": 0,
                "skipped_forbidden_content_count": 0,
                "skipped_permanent_duplicate_count": 0,
                "dry_run": dry_run,
                "eligible_records": [],
                "ineligible_records": [],
                "error_records": [],
            }

        min_age_days = resolve_migrated_knob(
            "permanent_proposal_min_age_days", 7, **_resolve_kwargs
        )
        cutoff_dt = _now - timedelta(days=min_age_days)

        # ── B2 fast track knob ───────────────────────────────────────────
        from .knob_overrides import resolve_knob as _resolve_knob_simple
        fast_path_enabled = bool(_resolve_knob_simple(
            "fast_path_enabled", default=False, **_resolve_kwargs
        ))

        eligible_count = 0
        skipped_rejected_count = 0
        skipped_too_young_count = 0
        skipped_forbidden_content_count = 0
        skipped_permanent_duplicate_count = 0
        eligible_records: list[dict[str, Any]] = []
        ineligible_records: list[dict[str, Any]] = []
        error_records: list[dict[str, Any]] = []

        permanent_body_hashes: set[str] = set()
        if self.store.roots.crystallized_root.exists():
            for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
                for existing in self.read_records(path.name):
                    if (
                        existing.frontmatter.get("provisional") is not True
                        and is_active_crystallized_frontmatter(existing.frontmatter)
                    ):
                        permanent_body_hashes.add(
                            hashlib.sha256(existing.body.encode("utf-8")).hexdigest()
                        )

        for record in self.list_provisional_records():
            record_id = str(record.get("id") or "")
            if not record_id:
                continue

            body = str(record.get("body") or "")
            forbidden_reasons = permanent_promotion_forbidden_reason_codes(body)
            if forbidden_reasons:
                skipped_forbidden_content_count += 1
                ineligible_records.append({
                    "record_id": record_id,
                    "candidate_id": str(record.get("candidate_id") or ""),
                    "reason_codes": forbidden_reasons,
                })
                continue

            body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            if body_hash in permanent_body_hashes:
                skipped_permanent_duplicate_count += 1
                ineligible_records.append({
                    "record_id": record_id,
                    "candidate_id": str(record.get("candidate_id") or ""),
                    "reason_codes": ["permanent_duplicate"],
                })
                continue

            # Never surface owner-rejected records as eligible
            canonical_state = str(record.get("canonical_state") or "")
            if canonical_state == "provisional_rejected":
                skipped_rejected_count += 1
                ineligible_records.append({
                    "record_id": record_id,
                    "candidate_id": str(record.get("candidate_id") or ""),
                    "reason_codes": ["target_rejected"],
                })
                continue

            # ── B2: owner_assertion fast track (before age check) ──────
            approved_by = str(record.get("approved_by") or "").strip()
            provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
            is_owner_assertion = (
                approved_by == "owner"
                or provenance.get("source_class") == "owner_assertion"
                or str(provenance.get("derivation") or "") == "owner_assertion"
            )
            fast_path_applied = False
            stability_basis = "provisional_age"

            if fast_path_enabled and is_owner_assertion:
                # V2-E clearance gate: must have clear verdict (fail-closed)
                from .clearance_receipts import ClearanceReceipt, read_clearance_receipts
                clearance_receipts = read_clearance_receipts(self.store.roots)
                active_clearance = None
                for cr_dict in clearance_receipts:
                    cr = ClearanceReceipt.from_dict(cr_dict)
                    if cr.record_id == record_id and cr.is_active:
                        active_clearance = cr
                        break
                if active_clearance is not None and active_clearance.verdict == "clear":
                    fast_path_applied = True
                    stability_basis = "owner_assertion_fast_path"

            # Check age threshold (skipped for fast-path eligible records)
            age_days = 0
            if fast_path_applied:
                # Fast path: skip age gate, compute age for dossier display only
                approved_at_str = str(record.get("approved_at") or "").strip()
                if approved_at_str:
                    try:
                        approved_dt = datetime.fromisoformat(approved_at_str)
                        if approved_dt.tzinfo is None:
                            approved_dt = approved_dt.replace(tzinfo=timezone.utc)
                        else:
                            approved_dt = approved_dt.astimezone(timezone.utc)
                        age_days = (_now - approved_dt).days
                    except (ValueError, TypeError):
                        age_days = 0
            else:
                approved_at_str = str(record.get("approved_at") or "").strip()
                if not approved_at_str:
                    skipped_too_young_count += 1
                    ineligible_records.append({
                        "record_id": record_id,
                        "candidate_id": str(record.get("candidate_id") or ""),
                        "reason_codes": ["approved_at_missing"],
                    })
                    continue
                try:
                    approved_dt = datetime.fromisoformat(approved_at_str)
                except (ValueError, TypeError):
                    skipped_too_young_count += 1
                    ineligible_records.append({
                        "record_id": record_id,
                        "candidate_id": str(record.get("candidate_id") or ""),
                        "reason_codes": ["approved_at_invalid"],
                    })
                    continue

                if approved_dt.tzinfo is None:
                    approved_dt = approved_dt.replace(tzinfo=timezone.utc)
                else:
                    approved_dt = approved_dt.astimezone(timezone.utc)

                if approved_dt > cutoff_dt:
                    skipped_too_young_count += 1
                    ineligible_records.append({
                        "record_id": record_id,
                        "candidate_id": str(record.get("candidate_id") or ""),
                        "reason_codes": ["minimum_age_not_met"],
                    })
                    continue
                age_days = (_now - approved_dt).days

            eligible_count += 1
            reason_codes = [
                "active_provisional",
                "content_allowed",
                "no_permanent_duplicate",
            ]
            if fast_path_applied:
                reason_codes.append("fast_path_owner_assertion")
                reason_codes.append("minimum_age_waived")
            else:
                reason_codes.append("minimum_age_met")

            eligible_entry: dict[str, Any] = {
                "record_id": record_id,
                "candidate_id": str(record.get("candidate_id") or ""),
                "projection": "legacy_auto_promoted",
                "approved_at": approved_at_str,
                "age_days": age_days,
                "stability_basis": stability_basis,
                "fast_path": fast_path_applied,
                "reason_codes": reason_codes,
            }
            eligible_records.append(eligible_entry)
            # Eligibility remains report-only. The V2-0.5 delivery producer may
            # consume this projection to open a proposal, never to write permanent state.

        return {
            "schema_version": "memory-os.permanent_promotion_eligibility.v1",
            "status": "ok" if not error_records else "partial",
            "eligible_count": eligible_count,
            "promoted_count": 0,
            "skipped_rejected_count": skipped_rejected_count,
            "skipped_too_young_count": skipped_too_young_count,
            "skipped_forbidden_content_count": skipped_forbidden_content_count,
            "skipped_permanent_duplicate_count": skipped_permanent_duplicate_count,
            "dry_run": dry_run,
            "eligible_records": eligible_records,
            "ineligible_records": ineligible_records,
            "error_records": error_records,
        }

    def auto_promote_provisional_records(
        self,
        *,
        now: datetime | None = None,
        dry_run: bool = False,
        _store_root: Path | None = None,
    ) -> dict[str, Any]:
        """Deprecated V2-0 compatibility wrapper — non-mutating.

        The silent age-based permanent write was removed in V2-0. This name is
        retained only so existing callers keep resolving; it delegates to
        :meth:`collect_permanent_promotion_eligibility` and never writes
        permanent state or mints an owner action. New code must call that
        method directly.
        """
        return self.collect_permanent_promotion_eligibility(
            now=now, dry_run=dry_run, _store_root=_store_root,
        )

    def _ensure_crystallized_approval(
        self,
        candidate: CrystallizedCandidate,
        decision: ApprovalDecision,
    ) -> None:
        if decision.candidate_id != candidate.candidate_id:
            raise CrystallizedApprovalError("approval candidate_id does not match candidate")
        if decision.purpose is not ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED:
            bridge = candidate.bridge_state or decision.source_state
            suffix = f"; bridge_state={bridge}" if bridge else ""
            raise CrystallizedApprovalError(
                f"Crystallized writes require approve_for_crystallized, got {decision.purpose.value}{suffix}"
            )
        if not candidate.source_event_ids:
            raise CrystallizedApprovalError("crystallized records require source_event_ids")
        from .provenance import candidate_external_ref, is_tainted

        if is_tainted(candidate, store=self.store):
            external_ref = candidate_external_ref(candidate, store=self.store) or ""
            if not external_ref:
                append_audit(
                    self.store.roots.audit_path,
                    action="external_evidence_crystallization_rejected",
                    status="blocked",
                    target=candidate.candidate_id,
                    details={"reason": "external_evidence_ref_unresolved"},
                )
                raise CrystallizedApprovalError("external_evidence_ref_unresolved")
            if not decision.external_evidence_ack:
                append_audit(
                    self.store.roots.audit_path,
                    action="external_evidence_crystallization_rejected",
                    status="blocked",
                    target=candidate.candidate_id,
                    details={"reason": "external_evidence_requires_explicit_ack", "external_ref": external_ref},
                )
                raise CrystallizedApprovalError("external_evidence_requires_explicit_ack")
            acked_ref = str(decision.acked_external_ref or "").strip()
            if acked_ref != external_ref:
                append_audit(
                    self.store.roots.audit_path,
                    action="external_evidence_crystallization_rejected",
                    status="blocked",
                    target=candidate.candidate_id,
                    details={
                        "reason": "external_evidence_ack_ref_mismatch",
                        "external_ref": external_ref,
                        "acked_external_ref": acked_ref,
                    },
                )
                raise CrystallizedApprovalError("external_evidence_ack_ref_mismatch")


def _candidate_id_present_locked(target: Path, candidate_id: str) -> bool:
    """Return True if *candidate_id* already appears in the canonical queue.

    *target* must already be held under the sidecar flock. Fail-open: any read
    or parse error returns False so a transient IO failure never causes a
    candidate to be dropped (dropped memory is worse than a rare duplicate
    row — and the SQLite index already de-dupes on SELECT via PK REPLACE).
    """
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("candidate_id") == candidate_id:
                return True
        return False
    except OSError:
        return False


def append_candidate_queue(store: MemoryOSStore, candidate: CrystallizedCandidate) -> Path:
    """Append a candidate, de-duplicating by ``candidate_id`` at write time.

    Idempotency guard (fix for duplicate-candidate rows): if a candidate with
    the same ``candidate_id`` already exists in the canonical queue, the append
    is skipped instead of producing a second physical row. The membership check
    and the append happen inside a single sidecar-flock acquisition, so a
    concurrent ``inner_drive`` re-processing of the same event cannot both pass
    the check (no TOCTOU).

    Design choices:
    - Fail-open: if the existing queue cannot be read we still append rather
      than risk dropping a candidate.
    - Emits a ``crystallized_candidate_dedup_skipped`` audit when an append is
      elided, so the skip is observable rather than silent.
    """
    path = store.roots.crystallized_root / "candidates.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(candidate)
    data["tags"] = list(candidate.tags or [])
    data["created_at"] = str(data.get("created_at") or _timestamp(None))

    candidate_id = candidate.candidate_id
    already_present = False
    with locked_jsonl_file(path) as target:
        # Membership check + append under the same lock the writer uses → no TOCTOU.
        if _candidate_id_present_locked(target, candidate_id):
            already_present = True
        else:
            line = json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n"
            _append_line_under_lock(target, line)
    if already_present:
        append_audit(
            store.roots.audit_path,
            action="crystallized_candidate_dedup_skipped",
            status="ok",
            target=str(path),
            details={"candidate_id": candidate_id},
        )
    else:
        append_audit(
            store.roots.audit_path,
            action="crystallized_candidate_queued",
            status="ok",
            target=str(path),
            details={
                "candidate_id": candidate.candidate_id,
                "source_event_ids": list(candidate.source_event_ids),
            },
        )
    return path


def read_candidate_queue(
    roots_or_store: Any,
    *,
    error_records: list[dict[str, Any]] | None = None,
) -> list[CrystallizedCandidate]:
    roots = getattr(roots_or_store, "roots", roots_or_store)
    path = roots.crystallized_root / "candidates.jsonl"
    if not path.exists():
        return []
    from .jsonl_io import read_jsonl_result

    io_result = read_jsonl_result(
        path,
        component="crystallized_candidate_queue",
        operation="read_candidate_queue",
    )
    if error_records is not None:
        error_records.extend(io_result.error_records[-5:])
    candidates: list[CrystallizedCandidate] = []
    for raw in io_result.records:
        candidate_id = raw.get("candidate_id")
        kind = raw.get("kind")
        body = raw.get("body")
        source_event_ids = raw.get("source_event_ids", [])
        tags = raw.get("tags") or []
        provenance = raw.get("provenance")
        if not all(isinstance(value, str) and value.strip() for value in (candidate_id, kind, body)):
            continue
        if not isinstance(source_event_ids, list) or not isinstance(tags, list):
            continue
        if provenance is not None and not isinstance(provenance, dict):
            continue
        try:
            rejection_count = int(raw.get("rejection_count", 0))
        except (TypeError, ValueError):
            continue
        candidates.append(
            CrystallizedCandidate(
                candidate_id=str(candidate_id),
                kind=str(kind),
                body=str(body),
                source_event_ids=[str(item) for item in source_event_ids],
                sensitivity=str(raw.get("sensitivity", "private")),
                tags=[str(item) for item in tags],
                bridge_state=str(raw.get("bridge_state", "")),
                created_at=str(raw.get("created_at") or ""),
                rejection_count=rejection_count,
                provenance=(dict(provenance) or None) if provenance is not None else None,
            )
        )
    return candidates


def is_active_crystallized_frontmatter(frontmatter: dict[str, Any]) -> bool:
    state = str(frontmatter.get("canonical_state") or "active").strip().lower()
    return state not in INACTIVE_CANONICAL_STATES


def _parse_markdown_records(content: str) -> list[tuple[dict[str, Any], str]]:
    lines = content.splitlines()
    records: list[tuple[dict[str, Any], str]] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != "---":
            index += 1
            continue
        index += 1
        frontmatter_lines: list[str] = []
        while index < len(lines) and lines[index].strip() != "---":
            frontmatter_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            break
        index += 1
        body_lines: list[str] = []
        while index < len(lines) and lines[index].strip() != "---":
            body_lines.append(lines[index])
            index += 1
        body = "\n".join(body_lines).strip()
        records.append((_parse_frontmatter(frontmatter_lines), body))
    return records


def _parse_frontmatter(lines: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    current_list_key = ""
    for line in lines:
        if line.startswith("  - ") and current_list_key:
            parsed[current_list_key].append(line[4:])
            continue
        current_list_key = ""
        if line.endswith(":"):
            key = line[:-1]
            parsed[key] = []
            current_list_key = key
            continue
        key, _, raw_value = line.partition(": ")
        if not key:
            continue
        parsed[key] = _parse_scalar(raw_value)
    return parsed


def _parse_scalar(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _datetime(value: datetime | None) -> datetime:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _timestamp(value: datetime | None) -> str:
    return _datetime(value).isoformat()


# ── Candidate triage (candidate_aggregation lane) ──────────────────────────


def append_candidate_triage(
    store: MemoryOSStore,
    *,
    candidate_id: str,
    action: str,
    target_state: str,
    reason: str,
    cluster_key: str = "",
    cluster_size: int = 0,
    execution_gate_envelope_id: str = "",
    now: datetime | None = None,
) -> Path:
    """Append a triage action record to candidate_triage.jsonl.

    Append-only. Never modifies candidates.jsonl. Never crystallizes.
    The lane reads both files at query time and resolves effective state.

    Governance path:
      - Every append requires a non-empty ExecutionGate envelope id and is
        validated by append_governed_jsonl. Empty/whitespace tokens fail closed;
        operator backfills must open an explicit governed envelope.
    """
    if action not in CANDIDATE_TRIAGE_ACTIONS:
        raise ValueError(f"invalid triage action: {action!r}; expected one of {CANDIDATE_TRIAGE_ACTIONS}")
    envelope_id = str(execution_gate_envelope_id or "").strip()
    if not envelope_id:
        raise PermissionError("candidate triage requires a non-empty execution gate envelope id")
    path = store.roots.crystallized_root / CANDIDATE_TRIAGE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "candidate_id": str(candidate_id),
        "action": str(action),
        "target_state": str(target_state),
        "reason": str(reason),
        "cluster_key": str(cluster_key or ""),
        "cluster_size": int(cluster_size),
        "execution_gate_envelope_id": envelope_id,
        "created_at": _timestamp(now),
    }
    # Use governed write — bare path.open('a') would fail write_surface_check.
    from .structural_write_gate import append_governed_jsonl

    append_governed_jsonl(
        store,
        path,
        record,
        write_owner="cognitive_loop",
        lane_id="candidate_aggregation",
        risk_class="bounded_reversible_queue",
        execution_gate_envelope_id=envelope_id,
        scope_hash="",
        allow_owner_action_without_envelope=False,
    )
    append_audit(
        store.roots.audit_path,
        action="candidate_triage_appended",
        status="ok",
        target=str(path),
        details={"candidate_id": candidate_id, "action": action, "target_state": target_state},
    )
    return path


def read_candidate_triage(store: MemoryOSStore) -> list[dict[str, Any]]:
    """Read all triage actions from candidate_triage.jsonl, newest first."""
    path = store.roots.crystallized_root / CANDIDATE_TRIAGE_FILE
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    records.reverse()  # newest first
    return records


# ── Candidate aggregation status (Fix 3: surface lane outcome to owner digest) ──

# Language-agnostic constant used for both the file name and the surface key.
AGGR_STATUS_FILE = "candidate_aggregation_status.jsonl"


def write_candidate_aggregation_status(
    store: MemoryOSStore,
    *,
    summary: dict[str, Any],
    execution_gate_envelope_id: str = "",
    now: datetime | None = None,
) -> Path:
    """Append one candidate_aggregation lane outcome record (append-only).

    The lane returns promoted/demoted/fleeting/compacted counts that previously
    went only to stdout. Persisting them here lets the owner review digest read
    the latest outcome and surface it in the Hermes main-session review message.

    Governance path: mirrors append_candidate_triage — lane ticks (envelope_id
    non-empty) go through append_governed_jsonl; operator/backfill writes use
    write_owner="owner_action" with allow_owner_action_without_envelope=True
    (classified exemption in write_surface_check).
    """
    path = store.roots.crystallized_root / AGGR_STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "candidates_read": int(summary.get("candidates_read", 0)),
        "pending": int(summary.get("pending", 0)),
        "already_triaged": int(summary.get("already_triaged", 0)),
        "promoted_count": int(summary.get("promoted_count", 0)),
        "rejected_demoted_count": int(summary.get("rejected_demoted_count", 0)),
        "demoted_count": int(summary.get("demoted_count", 0)),
        "fleeting_count": int(summary.get("fleeting_count", 0)),
        "compacted_count": int(summary.get("compacted_count", 0)),
        "execution_gate_envelope_id": str(execution_gate_envelope_id or ""),
        "created_at": _timestamp(now),
    }
    from .structural_write_gate import append_governed_jsonl
    from .execution_gate import execution_gate_scope_hash

    has_envelope = bool(execution_gate_envelope_id and str(execution_gate_envelope_id).strip())
    scope_hash = (
        ""
        if has_envelope
        else execution_gate_scope_hash(
            {
                "lane": "candidate_aggregation",
                "action": "write_aggregation_status",
            }
        )
    )
    append_governed_jsonl(
        store,
        path,
        record,
        write_owner="cognitive_loop" if has_envelope else "owner_action",
        lane_id="candidate_aggregation",
        risk_class="bounded_reversible_queue",
        execution_gate_envelope_id=str(execution_gate_envelope_id or ""),
        scope_hash=scope_hash,
        allow_owner_action_without_envelope=not has_envelope,
    )
    append_audit(
        store.roots.audit_path,
        action="candidate_aggregation_status_appended",
        status="ok",
        target=str(path),
        details={"promoted_count": record["promoted_count"]},
    )
    return path


def read_candidate_aggregation_status(store: MemoryOSStore) -> list[dict[str, Any]]:
    """Read all aggregation status records, newest first."""
    path = store.roots.crystallized_root / AGGR_STATUS_FILE
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    records.reverse()  # newest first
    return records


def latest_candidate_aggregation_status(store: MemoryOSStore) -> dict[str, Any] | None:
    """Return the most recent aggregation status record, or None if none yet."""
    records = read_candidate_aggregation_status(store)
    return records[0] if records else None


def resolve_candidate_effective_state(
    candidate: CrystallizedCandidate,
    triage_records: list[dict[str, Any]],
) -> str:
    """Resolve a candidate's effective state given original + triage history.

    The latest triage action for this candidate_id overrides its bridge_state.
    No triage = original bridge_state. This is computed at read time, never
    written back to candidates.jsonl.
    """
    cid = candidate.candidate_id
    for rec in triage_records:
        if rec.get("candidate_id") == cid:
            return str(rec.get("target_state", candidate.bridge_state))
    return candidate.bridge_state


_TERMINAL_CANDIDATE_STATES = frozenset(
    {
        "demoted",
        "fleeting",
        "absorbed",
        "discarded",
        "rejected",
        "owner_rejected",
        "closed",
        "archived",
        "crystallized",
        "owner_closed",
    }
)
_TERMINAL_CANDIDATE_ACTIONS = frozenset(
    {"approve_candidate", "reject_candidate", "approve_external_evidence"}
)


def read_effective_candidates(store: MemoryOSStore) -> list[EffectiveCandidate]:
    """Return the common latest-effective candidate projection.

    Raw queue rows remain available through :func:`read_candidate_queue` for
    audit and conservation reporting. This reader never writes, compacts, or
    approves memory.
    """

    triage_records = read_candidate_triage(store)
    latest_triage: dict[str, dict[str, Any]] = {}
    for record in triage_records:  # newest first
        candidate_id = str(record.get("candidate_id") or "")
        if candidate_id and candidate_id not in latest_triage:
            latest_triage[candidate_id] = dict(record)

    canonical_candidate_ids: set[str] = set()
    service = CrystallizedMemoryService(store)
    if store.roots.crystallized_root.exists():
        for path in sorted(store.roots.crystallized_root.glob("*.md")):
            for record in service.read_records(path.name):
                candidate_id = str(record.frontmatter.get("candidate_id") or "")
                if candidate_id and is_active_crystallized_frontmatter(record.frontmatter):
                    canonical_candidate_ids.add(candidate_id)

    owner_closed_ids: set[str] = set()
    owner_actions_path = store.roots.memory_os_root / "system" / "owner_actions.jsonl"
    if owner_actions_path.exists():
        for raw in owner_actions_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                action = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(action, dict):
                continue
            if str(action.get("target_type") or "") != "candidate":
                continue
            if str(action.get("action_type") or "") not in _TERMINAL_CANDIDATE_ACTIONS:
                continue
            if str(action.get("result") or "") not in {"applied", "duplicate_ignored"}:
                continue
            candidate_id = str(action.get("target_id") or "")
            if candidate_id:
                owner_closed_ids.add(candidate_id)

    raw_candidates = read_candidate_queue(store.roots)
    latest_candidates_reversed: list[CrystallizedCandidate] = []
    seen_candidate_ids: set[str] = set()
    for candidate in reversed(raw_candidates):
        if candidate.candidate_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(candidate.candidate_id)
        latest_candidates_reversed.append(candidate)
    latest_candidates = list(reversed(latest_candidates_reversed))

    projected: list[EffectiveCandidate] = []
    for candidate in latest_candidates:
        triage = latest_triage.get(candidate.candidate_id)
        state = resolve_candidate_effective_state(candidate, triage_records).strip().lower()
        if candidate.candidate_id in canonical_candidate_ids:
            state = "crystallized"
        elif candidate.candidate_id in owner_closed_ids:
            state = "owner_closed"
        terminal = state in _TERMINAL_CANDIDATE_STATES
        owner_review_eligible = state in {"owner_eligible", ""} and not terminal
        exclusion_reason = ""
        if terminal:
            exclusion_reason = "terminal_state"
        elif not owner_review_eligible:
            exclusion_reason = "not_owner_eligible"
        projected.append(
            EffectiveCandidate(
                candidate=candidate,
                effective_state=state,
                latest_triage=dict(triage) if triage is not None else None,
                owner_review_eligible=owner_review_eligible,
                terminal=terminal,
                exclusion_reason=exclusion_reason,
            )
        )
    return projected


def compact_candidate_queue(
    store: MemoryOSStore,
    *,
    archive_path: Path | None = None,
    retention_days: int = 7,
) -> int:
    """Archive-and-compact: move stale candidates to archive file.

    A candidate is 'active' (stays in main file) if:
      - effective state resolves to owner_eligible (owner needs to see it)
      - effective state is NOT demoted/absorbed AND created_age < retention_days

    Demoted/absorbed candidates are resolved outcomes and are ALWAYS archived
    (even when newer than retention_days) so they stop cluttering the live
    candidate queue. Other non-owner-eligible, non-terminal candidates within
    the retention window stay active for observation.

    Others are appended to archive and excluded from the main file.
    Returns count of archived candidates.
    Never deletes anything (append-only, INV-3).

    When *archive_path* is None (the default), a default archive path is
    derived from the crystallized root so stale candidates are always
    preserved — the default must never be a silent data-loss path.

    Holds a shared sidecar lock with append_candidate_queue so concurrent
    appends cannot be lost during the read→replace window (§3.3).
    A conservation assertion catches silent write-loss (§3.4A fail-closed).
    """
    if archive_path is None:
        archive_path = store.roots.crystallized_root / "candidates.archive.jsonl"
    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    if not candidates_path.exists():
        return 0

    now = datetime.now(timezone.utc)
    triage = read_candidate_triage(store)

    with locked_jsonl_file(candidates_path) as target:
        # Re-read under lock — prevents TOCTOU between read and replace
        lines = target.read_text(encoding="utf-8").splitlines()
        active: list[str] = []
        archived: list[str] = []
        archived_count = 0

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            raw = json.loads(line_stripped)
            cand = CrystallizedCandidate(
                candidate_id=str(raw["candidate_id"]),
                kind=str(raw["kind"]),
                body=str(raw["body"]),
                source_event_ids=[str(i) for i in raw.get("source_event_ids", [])],
                sensitivity=str(raw.get("sensitivity", "private")),
                tags=[str(t) for t in (raw.get("tags") or [])],
                bridge_state=str(raw.get("bridge_state", "")),
                created_at=str(raw.get("created_at") or ""),
                provenance=dict(raw.get("provenance") or {}) or None,
            )
            effective = resolve_candidate_effective_state(cand, triage)
            age = _candidate_age_seconds(cand.created_at, now)

            # Active (stays in main file) if the owner still needs to see it,
            # OR it is within the retention window AND not a resolved outcome.
            # Demoted/fleeting/absorbed are resolved — always archive them so
            # they stop cluttering the live queue (previously only archived
            # once aged past retention_days, leaving young demoted/fleeting/
            # absorbed in active).
            if effective == "owner_eligible" or (
                effective not in ("demoted", "fleeting", "absorbed") and age < retention_days * 86400
            ):
                active.append(line_stripped)
            else:
                archived.append(line_stripped)
                archived_count += 1

        # Conservation assertion (§3.4A — fail-closed)
        # Every non-blank line must end up in either active or archived
        blank_count = sum(1 for l in lines if not l.strip())
        if len(lines) - blank_count != len(active) + len(archived):
            append_audit(
                store.roots.audit_path,
                action="candidate_compact_conservation",
                status="violation",
                target=str(candidates_path),
                details={
                    "lines_before": len(lines),
                    "blank": blank_count,
                    "active": len(active),
                    "archived": len(archived),
                },
            )
            return 0  # Abort — do NOT replace the file

        # Archive via locked append FIRST — fail before touching main file.
        # If archive append fails, candidates.jsonl is untouched (no data loss).
        if archived:
            try:
                archived_records = [json.loads(line) for line in archived]
                # Dedup: skip records whose candidate_id already exists in archive.
                # Prevents duplicate archive rows when os.replace() fails after a
                # prior successful archive append (safe but leaves duplicate entries).
                if archive_path.exists():
                    existing_ids: set[str] = set()
                    for _line in archive_path.read_text(encoding="utf-8").splitlines():
                        if not _line.strip():
                            continue
                        try:
                            _cid = json.loads(_line).get("candidate_id")
                            if _cid:
                                existing_ids.add(_cid)
                        except (json.JSONDecodeError, AttributeError):
                            # Skip malformed lines and non-dict JSON values
                            continue
                    _before = len(archived_records)
                    archived_records = [
                        r for r in archived_records
                        if r.get("candidate_id") not in existing_ids
                    ]
                    _skipped = _before - len(archived_records)
                    if _skipped > 0:
                        append_audit(
                            store.roots.audit_path,
                            action="candidate_compact_dedup",
                            status="ok",
                            target=str(candidates_path),
                            details={"skipped_duplicates": _skipped},
                        )
                if archived_records:
                    append_jsonl_lines_locked(archive_path, archived_records)
            except Exception:
                append_audit(
                    store.roots.audit_path,
                    action="candidate_compact_conservation",
                    status="error",
                    target=str(candidates_path),
                    details={
                        "phase": "archive_append_failed",
                        "archived_count": len(archived),
                        "active_kept": len(active),
                    },
                )
                raise  # candidates.jsonl untouched — no data loss

        # Atomic replace only after archive succeeded
        tmp_path = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        tmp_path.write_text(
            "\n".join(active) + "\n" if active else "", encoding="utf-8"
        )
        os.replace(tmp_path, target)

        # Conservation OK baseline audit
        append_audit(
            store.roots.audit_path,
            action="candidate_compact_conservation",
            status="ok",
            target=str(candidates_path),
            details={
                "lines_before": len(lines),
                "active": len(active),
                "archived": archived_count,
            },
        )

    append_audit(
        store.roots.audit_path,
        action="candidate_queue_compacted",
        status="ok",
        target=str(candidates_path),
        details={"archived_count": archived_count, "retention_days": retention_days},
    )
    return archived_count


def _candidate_age_seconds(created_at: str, now: datetime) -> float:
    """Parse a candidate's created_at timestamp and return age in seconds."""
    if not created_at:
        return float("inf")  # no timestamp = keep
    try:
        parsed = datetime.fromisoformat(created_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (now - parsed).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def find_crystallized_by_body(
    store: MemoryOSStore,
    body: str,
    *,
    min_similarity: float = 0.85,
) -> list[dict[str, Any]]:
    """Find crystallized records whose body overlaps with the given text.

    Used by promote logic (candidate_aggregation, backfill) to avoid
    re-promoting candidates that are already crystallized (dedup).

    Uses exact substring overlap (normalized) rather than ML similarity —
    deterministic, cheap, and safe for owner-review dedup.

    Returns list of matching crystallized records with id, body, file_name.
    Empty list = no match (safe to promote).
    """
    norm_body = body.strip().lower()
    if not norm_body or len(norm_body) < 20:
        return []

    results: list[dict[str, Any]] = []
    for path in sorted(store.roots.crystallized_root.glob("*.md")):
        records = CrystallizedMemoryService(store).read_records(path.name)
        for record in records:
            rec_body = (record.body or "").strip().lower()
            # Simple overlap check: is the candidate body a substring of
            # the crystallized body, or vice versa?
            if not rec_body:
                continue
            if norm_body in rec_body or rec_body in norm_body:
                results.append({
                    "record_id": record.frontmatter.get("id", ""),
                    "candidate_id": record.frontmatter.get("candidate_id", ""),
                    "body_preview": record.body[:120] if record.body else "",
                    "file_name": record.file_name,
                    "canonical_state": record.frontmatter.get("canonical_state", "active"),
                })
    return results
