"""Vector-based edge proposer using embedding cosine similarity.

Uses the same LocalEmbedder as the vector retrieval lane to propose
edges between crystallized records whose embeddings are close in cosine
space. Deterministic — no LLM, no network. Same input embeddings →
same output edges every run.

INV-5 safe: proposer only runs when embedder.is_available(); degrades
to zero proposed edges when the dependency is not installed.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit

# ── Thresholds ───────────────────────────────────────────────────────────────

_COSINE_REFINES_THRESHOLD = 0.75   # very similar → refines
_COSINE_CO_OCCURS_THRESHOLD = 0.65  # similar → co_occurs
_COSINE_CONTRADICTS_THRESHOLD = 0.35  # dissimilar + different kind → contradicts
_MAX_PAIRS = 500
# At most ~32 records can participate in 500 pairs (n*(n-1)/2 ≤ 500).
# Add a small margin so we don't truncate early on sparse-embedding datasets.
_RECORD_LIMIT = int((2 * _MAX_PAIRS) ** 0.5) + 2


# ── Helpers ──────────────────────────────────────────────────────────────────


def _cosine_similarity(vec_a: bytes, vec_b: bytes) -> float | None:
    """Compute cosine similarity between two serialized float32 embedding blobs.

    Returns None if shapes mismatch (different embedding dimensions).
    """
    try:
        import numpy as np

        a = np.frombuffer(vec_a, dtype=np.float32)
        b = np.frombuffer(vec_b, dtype=np.float32)
    except Exception:
        return None
    if a.shape != b.shape:
        return None
    a_norm = float(np.linalg.norm(a))
    b_norm = float(np.linalg.norm(b))
    if a_norm == 0.0 or b_norm == 0.0:
        return None
    return float(np.dot(a, b) / (a_norm * b_norm))


def _detect_relation_from_similarity(
    sim: float,
    kind_a: str,
    kind_b: str,
) -> str | None:
    """Map cosine similarity + kind match/mismatch → edge relation_type.

    Returns None if no edge should be proposed (similarity in the
    ambiguous mid-range).
    """
    if sim >= _COSINE_REFINES_THRESHOLD:
        if kind_a == kind_b:
            return "refines"
        else:
            return "co_occurs"
    if sim >= _COSINE_CO_OCCURS_THRESHOLD:
        return "co_occurs"
    # Dissimilar + different categories → potential contradiction
    if sim <= _COSINE_CONTRADICTS_THRESHOLD and kind_a != kind_b:
        return "contradicts"
    return None


# ── Entry point ──────────────────────────────────────────────────────────────


def run_vector_proposer(
    index_path: str,
    *,
    index: object | None = None,
    embedder: object | None = None,
    audit_path: str | None = None,
    max_pairs: int = _MAX_PAIRS,
) -> dict[str, Any]:
    """Run the vector edge proposer across all crystallized record pairs.

    Uses embedding cosine similarity to propose edges. Requires an
    embedder with is_available() == True and embed() → bytes.

    Args:
        index_path: Path to the index DB.
        index: MemoryOSIndex instance (needed for edge writing).
        embedder: LocalEmbedder instance (needed for embeddings).
        audit_path: Optional audit path.
        max_pairs: Maximum number of pairs to evaluate.

    Returns a summary dict.
    """
    start_time = datetime.now(timezone.utc)

    # ── Guard: embedder not available ────────────────────────────────────
    if embedder is None or not getattr(embedder, "is_available", lambda: False)():
        return {
            "status": "skipped",
            "reason": "embedder_unavailable",
            "proposed_count": 0,
            "pair_count": 0,
        }

    # ── 1. Read crystallized records with embeddings ─────────────────────
    try:
        conn = sqlite3.connect(index_path)
    except (sqlite3.Error, Exception):
        return {"status": "error", "error": f"cannot_open_index: {index_path}"}
    conn.row_factory = sqlite3.Row

    # Get records with their embeddings.  Apply a computed LIMIT so we
    # only fetch as many rows as max_pairs can actually pair.
    record_limit = max(int((2 * max_pairs) ** 0.5) + 2, 2)
    try:
        rows = conn.execute(
            "select cr.id, cr.kind, me.embedding "
            "from crystallized_records cr "
            "inner join memory_embeddings me "
            "  on me.record_type = 'crystallized_record' "
            "  and me.record_id = cr.id "
            "order by cr.created_at "
            "limit ?",
            (record_limit,),
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return {"status": "error", "error": "cannot_read_crystallized_records"}

    records: list[dict[str, Any]] = []
    for row in rows:
        rid = str(row["id"] or "")
        embedding = row["embedding"]
        if not rid or not embedding:
            continue
        records.append({
            "id": rid,
            "kind": str(row["kind"] or ""),
            "embedding": bytes(embedding),
        })

    if len(records) < 2:
        conn.close()
        return {
            "status": "skipped",
            "reason": f"need ≥2 records with embeddings, got {len(records)}",
            "proposed_count": 0,
            "pair_count": 0,
        }

    # ── 2. Collect existing edges for dedup ──────────────────────────────
    existing_edges: set[str] = set()
    if index and hasattr(index, "query_edges"):
        try:
            all_ids = [r["id"] for r in records]
            for state_filter in ("candidate", "active"):
                raw = index.query_edges(
                    all_ids, depth=1, state=state_filter, limit=2000
                )
                if isinstance(raw, list):
                    for e in raw:
                        key = (
                            f"{e.get('from_record_id','')}:"
                            f"{e.get('to_record_id','')}:"
                            f"{e.get('relation_type','')}"
                        )
                        existing_edges.add(key)
        except Exception:
            pass  # fail-open

    # ── 3. Build pairs and compute similarity ────────────────────────────
    pairs = 0
    proposed = 0

    for i in range(len(records)):
        if pairs >= max_pairs:
            break
        for j in range(i + 1, len(records)):
            if pairs >= max_pairs:
                break
            pairs += 1

            rec_a = records[i]
            rec_b = records[j]

            sim = _cosine_similarity(rec_a["embedding"], rec_b["embedding"])
            if sim is None:
                continue

            rtype = _detect_relation_from_similarity(
                sim,
                rec_a["kind"],
                rec_b["kind"],
            )
            if rtype is None:
                continue

            # Check dedup — both directions
            dedup_key_fwd = f"{rec_a['id']}:{rec_b['id']}:{rtype}"
            dedup_key_rev = f"{rec_b['id']}:{rec_a['id']}:{rtype}"
            if dedup_key_fwd in existing_edges or dedup_key_rev in existing_edges:
                continue
            existing_edges.add(dedup_key_fwd)

            # ── Write edge ───────────────────────────────────────────────
            if index and hasattr(index, "write_governed_edge"):
                edge = index.write_governed_edge(
                    conn=conn,
                    from_record_type="crystallized_record",
                    from_record_id=rec_a["id"],
                    to_record_type="crystallized_record",
                    to_record_id=rec_b["id"],
                    relation_type=rtype,
                    weight=round(sim, 4),
                    source_event_id=None,
                    proposed_by="vector",
                    state="candidate",
                )
                if edge:
                    proposed += 1

    conn.close()

    elapsed_ms = int(
        (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
    )

    summary = {
        "status": "ok",
        "record_count": len(records),
        "pair_count": pairs,
        "proposed_count": proposed,
        "duration_ms": elapsed_ms,
        "begin_at": start_time.isoformat(),
    }

    if audit_path:
        append_audit(
            Path(audit_path),
            action="vector_edge_proposer_run",
            status="ok",
            target=str(index_path),
            details=summary,
        )

    return summary
