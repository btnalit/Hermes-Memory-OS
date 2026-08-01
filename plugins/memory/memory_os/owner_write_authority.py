"""Single source of authority for Owner-approved permanent canonical writes.

This module is deliberately low-level.  It depends only on ``roots``/``store``
path helpers and JSONL primitives, and it must never import ``owner_actions``
or ``crystallized`` — both of those import *it*.

It exists because the same verification used to be written twice.  ``owner_actions``
carried the strict copy and ``crystallized`` carried a hand-rolled one added to
break an import cycle; the two drifted, and the weaker of the pair was the one
actually guarding production writes.  The ``crystallized`` copy never checked
that the action context came from a recorded digest (``source``), never checked
the action type against the canonical-write allowlist, never checked the token
hash was a full SHA-256, and matched the consumption ledger without comparing
``action_token_hash``.  Duplicating a security boundary is how a boundary
quietly becomes optional, so there is one implementation here and no other.

Authority is proved against canonical ledgers on disk.  There is intentionally
no importable capability object for permanent writes: holding a Python value
must never stand in for an Owner decision recorded in a delivered digest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .roots import MemoryOSRoots
from .store import MemoryOSStore


# The only action types that may authorize a permanent canonical write.
OWNER_CANONICAL_WRITE_ACTION_TYPES = frozenset(
    {"approve_candidate", "approve_candidate_cluster", "approve_external_evidence"}
)

# An Owner action context is only trusted when it was bound to a digest that was
# actually rendered and recorded.  Surface-derived bindings are recomputed from
# current live state and prove nothing about delivery, so they are not listed.
RECORDED_DIGEST_CONTEXT_SOURCES = frozenset(
    {"recorded_digest", "latest_recorded_digest", "latest_owner_home_digest"}
)

OWNER_WRITE_CONTEXT_CONSUMPTION_SCHEMA_VERSION = "memory-os.owner_write_context_consumption.v0"

_SAFE_CHANNELS = frozenset(
    {
        "telegram",
        "cli",
        "web",
        "slack",
        "whatsapp",
        "wecom",
        "wechat",
        "weixin",
        "matrix",
        "discord",
        "signal",
        "origin",
        "unknown",
    }
)


def safe_channel(value: str) -> str:
    channel = str(value or "").strip().lower().replace("-", "_")
    return channel if channel in _SAFE_CHANNELS else "unknown"


def owner_review_rendered_digests_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "owner_review_rendered_digests.jsonl"


def owner_action_context_consumptions_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "owner_action_context_consumptions.jsonl"


def read_jsonl_dict_records(path: Path) -> list[dict[str, Any]]:
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


def find_rendered_digest_record(
    roots: MemoryOSRoots,
    *,
    digest_id: str,
    owner_id: str,
    channel: str,
) -> dict[str, Any] | None:
    for record in reversed(read_jsonl_dict_records(owner_review_rendered_digests_path(roots))):
        if str(record.get("digest_id") or "") != digest_id:
            continue
        if owner_id and str(record.get("owner_id") or "") != owner_id:
            continue
        if channel and str(record.get("channel") or "") != safe_channel(channel):
            continue
        return record
    return None


def _canonical_write_target(action_type: str, item: dict[str, Any]) -> tuple[str, str]:
    """Resolve the target a rendered action token points at.

    Mirrors the generic digest target resolution for the canonical-write action
    types: an explicit ``action_targets`` entry wins, otherwise the item's own
    target fields stand in.  The expression-feedback special case in the generic
    resolver is intentionally absent — those action types can never reach here.
    """

    action_targets = item.get("action_targets") if isinstance(item.get("action_targets"), dict) else {}
    target = action_targets.get(action_type) if isinstance(action_targets.get(action_type), dict) else {}
    if target:
        return str(target.get("target_type") or ""), str(target.get("target_id") or "")
    return str(item.get("target_type") or ""), str(item.get("target_id") or "")


def _match_recorded_action_token(
    rendered: dict[str, Any],
    *,
    token_hash: str,
) -> dict[str, Any] | None:
    """Find the rendered item whose action token hashes to *token_hash*.

    Tokens are matched by hash rather than by value so the caller never has to
    carry the raw token, and lower-cased before hashing to match how the reply
    ingress derives the binding.
    """

    sections = rendered.get("sections") if isinstance(rendered.get("sections"), dict) else {}
    for items in sections.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            tokens = item.get("action_tokens") if isinstance(item.get("action_tokens"), dict) else {}
            for action_type, token in tokens.items():
                clean = str(token or "").lower()
                if not clean:
                    continue
                if hashlib.sha256(clean.encode("utf-8")).hexdigest() != token_hash:
                    continue
                target_type, target_id = _canonical_write_target(str(action_type), item)
                return {
                    "item": item,
                    "action_type": str(action_type),
                    "target_type": target_type,
                    "target_id": target_id,
                }
    return None


def verify_owner_write_binding(
    store: MemoryOSStore,
    record: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Verify an Owner action record may authorize a permanent canonical write.

    Returns ``(consumption, "")`` when the record is bound to a recorded digest
    action token for exactly this owner, channel, action type and target, or
    ``({}, error_code)`` otherwise.  Every failure path returns an error code —
    there is no path that returns an empty error with an unverified record.
    """

    context = record.get("owner_write_context") if isinstance(record.get("owner_write_context"), dict) else {}
    token_binding = record.get("token_binding") if isinstance(record.get("token_binding"), dict) else {}
    action_type = str(record.get("action_type") or "")
    target_type = str(record.get("target_type") or "")
    target_id = str(record.get("target_id") or "")
    owner_id = str(record.get("owner_id") or "")
    channel = safe_channel(str(record.get("channel") or ""))
    digest_id = str(context.get("digest_id") or "")
    reply_ingress_id = str(context.get("reply_ingress_id") or "")
    token_hash = str(token_binding.get("action_token_hash") or "")
    source = str(context.get("source") or "")
    if action_type not in OWNER_CANONICAL_WRITE_ACTION_TYPES:
        return {}, "owner_write_action_not_authorized"
    if source not in RECORDED_DIGEST_CONTEXT_SOURCES:
        return {}, "owner_write_recorded_digest_required"
    if not digest_id or not reply_ingress_id or len(token_hash) != 64:
        return {}, "owner_write_context_incomplete"
    if any(
        str(context.get(key) or "") != expected
        for key, expected in (
            ("owner_id", owner_id),
            ("channel", channel),
            ("action_type", action_type),
            ("target_type", target_type),
            ("target_id", target_id),
        )
    ):
        return {}, "owner_write_context_mismatch"
    digest_record = find_rendered_digest_record(
        store.roots,
        digest_id=digest_id,
        owner_id=owner_id,
        channel=channel,
    )
    if not digest_record:
        return {}, "owner_write_recorded_digest_not_found"
    rendered = digest_record.get("rendered_digest") if isinstance(digest_record.get("rendered_digest"), dict) else {}
    matched = _match_recorded_action_token(rendered, token_hash=token_hash)
    if not matched:
        return {}, "owner_write_token_not_in_recorded_digest"
    if any(
        str(matched.get(key) or "") != expected
        for key, expected in (
            ("action_type", action_type),
            ("target_type", target_type),
            ("target_id", target_id),
        )
    ):
        return {}, "owner_write_token_target_mismatch"
    item = matched.get("item") if isinstance(matched.get("item"), dict) else {}
    expected_review_item_id = str(item.get("review_item_id") or f"{target_type}:{target_id}")
    if str(token_binding.get("review_item_id") or "") != expected_review_item_id:
        return {}, "owner_write_review_item_mismatch"
    return {
        "schema_version": OWNER_WRITE_CONTEXT_CONSUMPTION_SCHEMA_VERSION,
        "context_id": reply_ingress_id,
        "digest_id": digest_id,
        "reply_sha256": str(context.get("reply_sha256") or ""),
        "action_token_hash": token_hash,
        "review_item_id": expected_review_item_id,
        "action_type": action_type,
        "target_type": target_type,
        "target_id": target_id,
        "owner_id": owner_id,
        "channel": channel,
    }, ""


def validate_consumed_owner_write_context(
    store: MemoryOSStore,
    owner_action_context: dict[str, Any] | None,
    *,
    candidate_id: str,
    reviewer: str,
) -> bool:
    """Re-verify a consumed Owner action against one specific candidate.

    Takes ``candidate_id``/``reviewer`` as plain strings rather than the
    candidate and decision objects so this module stays free of any import of
    ``crystallized``.  Re-running the full binding check here (rather than
    trusting that ingress already ran it) is deliberate: the write path must be
    able to prove authority on its own, from the ledgers, at the moment it
    writes.
    """

    if not isinstance(owner_action_context, dict):
        return False
    consumption, error = verify_owner_write_binding(store, owner_action_context)
    if error:
        return False
    if str(reviewer or "") != str(consumption.get("owner_id") or ""):
        return False
    action_type = str(consumption.get("action_type") or "")
    target_type = str(consumption.get("target_type") or "")
    target_id = str(consumption.get("target_id") or "")
    if action_type in {"approve_candidate", "approve_external_evidence"}:
        if target_type != "candidate" or target_id != str(candidate_id):
            return False
    elif action_type == "approve_candidate_cluster":
        action_context = (
            owner_action_context.get("action_context")
            if isinstance(owner_action_context.get("action_context"), dict)
            else {}
        )
        scope = (
            action_context.get("candidate_cluster_scope")
            if isinstance(action_context.get("candidate_cluster_scope"), dict)
            else {}
        )
        scoped_target_id = f"{str(scope.get('cluster_id') or '')}:{str(scope.get('scope_hash') or '')}"
        if scoped_target_id != target_id:
            return False
        members = scope.get("member_candidate_ids")
        if not isinstance(members, list):
            return False
        if str(candidate_id) not in {str(value) for value in members}:
            return False
    else:
        return False
    context_id = str(consumption.get("context_id") or "")
    for existing in reversed(read_jsonl_dict_records(owner_action_context_consumptions_path(store.roots))):
        if str(existing.get("context_id") or "") != context_id:
            continue
        return str(existing.get("status") or "") == "consumed" and all(
            str(existing.get(key) or "") == str(consumption.get(key) or "")
            for key in (
                "digest_id",
                "action_token_hash",
                "action_type",
                "target_type",
                "target_id",
                "owner_id",
                "channel",
            )
        )
    return False
