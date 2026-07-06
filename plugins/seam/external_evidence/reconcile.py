"""P3 laundering reconcile — detect crystallized records without provenance.

Runs as an optional low-frequency cron job.  Finds crystallized records
that reference external content but lack a verified external provenance
chain (external_intake → tainted event → owner ack → crystallized).

Output: owner-visible findings in the digest.  NEVER auto-revokes,
auto-demotes, or auto-deletes — this is a report-only lane.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def run_laundering_reconcile(
    crystallized_root: Path,
    events_root: Path,
    *,
    similarity_threshold: float = 0.7,
) -> dict[str, Any]:
    """Scan crystallized records for potential laundering.

    Laundering candidates are crystallized records whose content
    materially overlaps with tainted external evidence events but
    whose provenance chain does not include an owner ``approve_external_evidence``
    action.

    Returns a report dict suitable for the owner digest.
    Never mutates canonical data.
    """
    findings: list[dict[str, Any]] = []

    # 1) Collect tainted event refs
    tainted_refs = _collect_tainted_external_refs(events_root)

    # 2) Collect owner-ack'd external refs
    acked_refs = _collect_acked_external_refs(events_root)

    # 3) Scan crystallized files for potential laundering
    if not crystallized_root.exists():
        return _build_report(findings, tainted_refs, acked_refs)

    for md_path in sorted(crystallized_root.glob("*.md")):
        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError:
            continue

        # Check if content references any tainted external_ref
        matched = []
        for ref in tainted_refs:
            if _text_overlap(content, ref, threshold=similarity_threshold):
                matched.append(ref)

        if not matched:
            continue

        # Check if any matched ref has been ack'd
        all_acked = all(ref in acked_refs for ref in matched)
        if all_acked:
            continue

        findings.append({
            "record_file": md_path.name,
            "matched_refs": matched,
            "acked_refs": [r for r in matched if r in acked_refs],
            "unacked_refs": [r for r in matched if r not in acked_refs],
        })

    return _build_report(findings, tainted_refs, acked_refs)


def _collect_tainted_external_refs(events_root: Path) -> set[str]:
    """Collect all external_ref values from tainted external_evidence events."""
    refs: set[str] = set()
    if not events_root.exists():
        return refs
    for jsonl_path in sorted(events_root.glob("*/*.jsonl")):
        try:
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                safe_ref = record.get("safe_ref", {})
                if not isinstance(safe_ref, dict):
                    continue
                if safe_ref.get("source_class") != "external_evidence":
                    continue
                ext_ref = str(safe_ref.get("external_ref", ""))
                if ext_ref:
                    refs.add(ext_ref)
        except (json.JSONDecodeError, OSError):
            continue
    return refs


def _collect_acked_external_refs(events_root: Path) -> set[str]:
    """Collect external_ref values that have owner ack events."""
    refs: set[str] = set()
    if not events_root.exists():
        return refs
    for jsonl_path in sorted(events_root.glob("*/*.jsonl")):
        try:
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                if str(record.get("kind", "")) != "owner_ack_external_evidence":
                    continue
                safe_ref = record.get("safe_ref", {})
                if not isinstance(safe_ref, dict):
                    continue
                ext_ref = str(safe_ref.get("external_ref", ""))
                if ext_ref:
                    refs.add(ext_ref)
        except (json.JSONDecodeError, OSError):
            continue
    return refs


def _text_overlap(text: str, ref: str, *, threshold: float = 0.7) -> bool:
    """Naive overlap check — True if *ref* appears in *text* (case-insensitive).

    A full similarity check (e.g. embedding cosine) would be more precise
    but requires an embedder.  For P3 (FINDING only), substring match is
    a reasonable first-pass signal.
    """
    return ref.lower() in text.lower()


def _build_report(
    findings: list[dict[str, Any]],
    tainted_refs: set[str],
    acked_refs: set[str],
) -> dict[str, Any]:
    return {
        "schema_version": "memory-os.laundering_reconcile.v0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "tainted_external_ref_count": len(tainted_refs),
        "acked_external_ref_count": len(acked_refs),
        "laundering_candidate_count": len(findings),
        "findings": findings,
        "recommendation": (
            "Review candidates in owner digest. "
            "Use approve_external_evidence to ack legitimate provenance, "
            "or demote/discard unverified records."
        ),
    }
