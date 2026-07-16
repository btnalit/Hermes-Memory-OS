"""Deterministic bounded BodyStatePacket and provenance-only manifests for V3."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .jsonl_io import _append_line_under_lock, locked_jsonl_file
from .source_ids import SYNTHETIC_GUARD_IDS, filter_safe_source_id_values
from .store import MemoryOSStore

BODY_PACKET_SCHEMA_VERSION = "memory-os.v3_body_state.v0"
BODY_MANIFEST_SCHEMA_VERSION = "memory-os.v3_body_packet_manifest.v0"
_ALLOWED_KINDS = {"stable_memory", "working_attention", "open_thread", "unsettled_candidate", "private_thought"}
_ALLOWED_EPISTEMIC = {"approved", "working", "unapproved", "private_uncommitted"}
_ALLOWED_EDGE_KINDS = {"co_selected", "shared_entity", "contrasts"}
_ALLOWED_SEED_PREFIXES = ("crystallized:", "event:", "working:", "candidate:", "digest:", "reflection_card:")


def body_packet_manifests_path(store: MemoryOSStore) -> Path:
    return store.roots.memory_os_root / "system" / "v3_body_packet_manifests.jsonl"


def canonical_packet_bytes(packet: dict[str, Any]) -> bytes:
    return json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def packet_digest(packet: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_packet_bytes(packet)).hexdigest()


def build_body_state_packet(
    *,
    quiet_state: bool,
    source_window: dict[str, Any],
    source_cursors: dict[str, Any],
    seed_candidates: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    sampler_seed: str,
    max_text_chars: int = 320,
    max_seed_candidates: int = 16,
    max_edges: int = 32,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if type(quiet_state) is not bool:
        raise ValueError("quiet_state_must_be_boolean")
    if type(max_text_chars) is not int or max_text_chars <= 0:
        raise ValueError("max_text_chars")
    if type(max_seed_candidates) is not int or max_seed_candidates <= 0:
        raise ValueError("max_seed_candidates")
    if type(max_edges) is not int or max_edges < 0:
        raise ValueError("max_edges")

    normalized_seeds: list[dict[str, Any]] = []
    refs: set[str] = set()
    for raw in seed_candidates[:max_seed_candidates]:
        if not isinstance(raw, dict):
            raise ValueError("seed_candidate_invalid")
        ref = str(raw.get("ref") or "").strip()
        if not _is_safe_seed_ref(ref):
            raise ValueError(f"unsafe_source_ref:{ref}")
        if ref in refs:
            continue
        kind = str(raw.get("kind") or "")
        epistemic = str(raw.get("epistemic_status") or "")
        if kind not in _ALLOWED_KINDS or epistemic not in _ALLOWED_EPISTEMIC:
            raise ValueError("seed_candidate_invalid")
        text = str(raw.get("bounded_text") or "").strip()
        if not text:
            raise ValueError("seed_text_missing")
        reasons = sorted({str(item) for item in raw.get("salience_reasons") or [] if str(item).strip()})[:8]
        normalized_seeds.append(
            {
                "ref": ref,
                "kind": kind,
                "bounded_text": text[:max_text_chars],
                "epistemic_status": epistemic,
                "salience_reasons": reasons,
            }
        )
        refs.add(ref)

    normalized_edges: list[dict[str, Any]] = []
    for raw in edges[:max_edges]:
        if not isinstance(raw, dict):
            raise ValueError("edge_invalid")
        left, right = str(raw.get("from") or ""), str(raw.get("to") or "")
        if left not in refs or right not in refs:
            raise ValueError("edge_ref_not_in_packet")
        kind = str(raw.get("kind") or "")
        weight = raw.get("weight")
        if (
            kind not in _ALLOWED_EDGE_KINDS
            or not isinstance(weight, (int, float))
            or isinstance(weight, bool)
            or float(weight) < 0
        ):
            raise ValueError("edge_invalid")
        normalized_edges.append({"from": left, "to": right, "kind": kind, "weight": weight})

    now = generated_at or datetime.now(timezone.utc)
    return {
        "schema_version": BODY_PACKET_SCHEMA_VERSION,
        "snapshot_id": "v3body_" + uuid4().hex,
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "quiet_state": quiet_state,
        "source_window": dict(source_window),
        "source_cursors": dict(source_cursors),
        "seed_candidates": normalized_seeds,
        "edges": normalized_edges,
        "sampler_seed": str(sampler_seed),
        "boundaries": {
            "no_tools": True,
            "no_external_action": True,
            "no_identity_write": True,
            "no_permanent_memory_write": True,
        },
    }


def write_body_packet_manifest(store: MemoryOSStore, packet: dict[str, Any]) -> dict[str, Any]:
    _validate_packet(packet)
    path = body_packet_manifests_path(store)
    snapshot_id = str(packet["snapshot_id"])
    source_refs = [str(item["ref"]) for item in packet["seed_candidates"]]
    eligibility = {str(item["ref"]): list(item.get("salience_reasons") or []) for item in packet["seed_candidates"]}
    edge_refs = [_edge_ref(item) for item in packet["edges"]]
    manifest = {
        "schema_version": BODY_MANIFEST_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "generated_at": str(packet["generated_at"]),
        "source_window": dict(packet.get("source_window") or {}),
        "source_cursors": dict(packet.get("source_cursors") or {}),
        "source_refs": source_refs,
        "edge_refs": edge_refs,
        "sampler_seed": str(packet.get("sampler_seed") or ""),
        "eligibility_reasons": eligibility,
        "eligibility_policy_version": 1,
        "packet_digest": packet_digest(packet),
        "body_text_included": False,
        "model_output_included": False,
    }
    line = json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n"
    with locked_jsonl_file(path) as target:
        records = _read_strict_jsonl(target)
        if any(str(item.get("snapshot_id") or "") == snapshot_id for item in records):
            raise ValueError("duplicate_snapshot_id")
        _append_line_under_lock(target, line, durable=True)
    return manifest


def resolve_body_manifest(store: MemoryOSStore, snapshot_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in _read_strict_jsonl(body_packet_manifests_path(store))
        if str(item.get("snapshot_id") or "") == str(snapshot_id)
    ]
    if not matches:
        raise ValueError("manifest_not_found")
    if len(matches) != 1:
        raise ValueError("manifest_not_unique")
    return matches[0]


def verify_body_packet_manifest(store: MemoryOSStore, packet: dict[str, Any]) -> dict[str, Any]:
    _validate_packet(packet)
    manifest = resolve_body_manifest(store, str(packet["snapshot_id"]))
    if str(manifest.get("packet_digest") or "") != packet_digest(packet):
        raise ValueError("packet_digest_mismatch")
    packet_refs = sorted(str(item["ref"]) for item in packet["seed_candidates"])
    if sorted(str(item) for item in manifest.get("source_refs") or []) != packet_refs:
        raise ValueError("manifest_source_refs_mismatch")
    return manifest


def remove_body_manifests(store: MemoryOSStore, snapshot_ids: set[str]) -> None:
    if not snapshot_ids:
        return
    path = body_packet_manifests_path(store)
    with locked_jsonl_file(path) as target:
        records = _read_strict_jsonl(target)
        retained = [item for item in records if str(item.get("snapshot_id") or "") not in snapshot_ids]
        _rewrite_records_under_lock(target, retained)


def _validate_packet(packet: dict[str, Any]) -> None:
    if not isinstance(packet, dict) or packet.get("schema_version") != BODY_PACKET_SCHEMA_VERSION:
        raise ValueError("packet_schema_invalid")
    refs = {str(item.get("ref") or "") for item in packet.get("seed_candidates") or [] if isinstance(item, dict)}
    if not refs or any(not _is_safe_seed_ref(ref) for ref in refs):
        raise ValueError("unsafe_source_ref")
    for edge in packet.get("edges") or []:
        if not isinstance(edge, dict) or str(edge.get("from") or "") not in refs or str(edge.get("to") or "") not in refs:
            raise ValueError("edge_ref_not_in_packet")


def _is_safe_seed_ref(ref: str) -> bool:
    if ref.startswith("journal:wnd_") and all(ch.isalnum() or ch in "_-" for ch in ref.split(":", 1)[1]):
        return True
    return (
        ref not in SYNTHETIC_GUARD_IDS
        and ref.startswith(_ALLOWED_SEED_PREFIXES)
        and filter_safe_source_id_values([ref]) == [ref]
    )


def _edge_ref(edge: dict[str, Any]) -> str:
    payload = json.dumps(edge, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "edge:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _read_strict_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError("jsonl_non_object")
        records.append(parsed)
    return records


def _rewrite_records_under_lock(target: Path, records: list[dict[str, Any]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    blob = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records)
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    """Best-effort directory fsync after an atomic replace.

    POSIX keeps the pre-existing durability semantics: open a directory
    descriptor and fsync it, propagating fsync errors.  Platforms that cannot
    open directory descriptors (Windows raises PermissionError from os.open)
    skip the directory fsync; the file itself is already flushed+fsynced and
    os.replace stays atomic.
    """

    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except (NotImplementedError, OSError):
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
