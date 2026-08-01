"""Crystallization gate — contradiction check for crystallized candidate promotion.

Runs as a cognitive-loop step.  Reads crystallized candidates pending promotion,
searches FTS5 for similar existing crystallized records, then checks the edge
graph for `contradicts` relations.  If a contradiction is found, the candidate
is flagged for owner review (shadow mode — no auto-block, just evidence).

Rule from §5b of graph-layer-roadmap.md:

    crystallized gate / candidate promote:
        traverse graph, check if "incoming item contradicts / near-duplicate
        with existing active node"
          → hit → fail-closed: intercept auto-promote, redirect to owner review
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .audit import append_audit


_MAX_CANDIDATES = 100
_FTS_LIMIT = 5  # most similar records to check per candidate


def _gate_error_result(code: str, *, component: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": code,
        "error_code": code,
        "error_count": 1,
        "error_records": [
            {"code": code, "candidate_id": "", "component": component}
        ],
        "candidate_count": 0,
        "flagged_count": 0,
        "flagged_candidates": [],
        "duration_ms": 0,
    }


def _tokenize(text: str) -> set[str]:
    """Lowercase alpha-numeric token set for FTS5 query building."""
    return set(re.findall(r"[a-z\u4e00-\u9fff][a-z0-9\u4e00-\u9fff]*", text.lower()))


# ── Core gate logic ────────────────────────────────────────────────────────


def run_crystallization_gate(
    index_path: str,
    *,
    index: object | None = None,
    audit_path: str | None = None,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the crystallization contradiction gate.

    Args:
        index_path: Path to the index DB.
        index: MemoryOSIndex instance (needed for edge queries).
        audit_path: Optional audit path.

    Returns a dict with per-candidate gate results.
    """
    start_time = datetime.now(timezone.utc)

    # 1. Read crystallized candidates from the index.
    try:
        conn = sqlite3.connect(index_path)
    except (sqlite3.Error, Exception):
        return _gate_error_result("cannot_open_index", component="sqlite")
    conn.row_factory = sqlite3.Row
    if candidates is None:
        try:
            candidates_raw = conn.execute(
                "select * from crystallized_candidates limit ?",
                (_MAX_CANDIDATES,),
            ).fetchall()
        except sqlite3.Error:
            return _gate_error_result("cannot_read_candidates", component="sqlite")
        finally:
            conn.close()
        candidate_rows: list[dict[str, Any]] = [dict(row) for row in candidates_raw]
    else:
        conn.close()
        candidate_rows = [dict(row) for row in candidates[:_MAX_CANDIDATES]]

    if not candidate_rows:
        return {
            "status": "ok",
            "candidate_count": 0,
            "flagged_count": 0,
            "flagged_candidates": [],
            "duration_ms": 0,
        }

    # 2. For each candidate, search for similar crystallized records and check
    #    for contradicts edges.
    flagged: list[dict[str, Any]] = []
    error_records: list[dict[str, str]] = []
    conn2 = sqlite3.connect(index_path)
    conn2.row_factory = sqlite3.Row
    try:
        for cand in candidate_rows:
            cid = str(cand.get("candidate_id", ""))
            body = str(cand.get("body", ""))
            cand_tags = cand.get("tags_json", []) or []
            if isinstance(cand_tags, str):
                try:
                    cand_tags = json.loads(cand_tags)
                except (json.JSONDecodeError, TypeError):
                    cand_tags = []
            if not body.strip():
                continue

            # Search FTS5 for similar crystallized record bodies.
            # Use the first 300 chars as query (FTS5 words).
            query_words = " OR ".join(
                _tokenize(body[:300])
            )
            if not query_words.strip():
                continue
            similar = conn2.execute(
                """select record_id, snippet(memory_fts, 1, '<b>', '</b>', '...', 60) as snippet
                   from memory_fts
                   where memory_fts match ?
                     and record_type = 'crystallized_record'
                   order by rank
                   limit ?""",
                (query_words, _FTS_LIMIT),
            ).fetchall()

            if not similar:
                continue

            # For each similar record, check edges for contradicts.
            similar_ids = [str(r["record_id"]) for r in similar]
            contradictions: list[dict[str, Any]] = []
            if similar_ids and not (index and hasattr(index, "query_edges")):
                error_records.append(
                    {
                        "candidate_id": cid,
                        "error_code": "edge_index_unavailable",
                    }
                )
                flagged.append(
                    {
                        "candidate_id": cid,
                        "reason_code": "edge_index_unavailable",
                        "body_preview": body[:120],
                        "similar_record_ids": similar_ids[:10],
                        "contradiction_count": 0,
                        "contradictions": [],
                    }
                )
                continue
            if index and hasattr(index, "query_edges"):
                try:
                    # Only consume active edges — candidate edges have not
                    # passed owner review (§6) and must not trigger automation.
                    for check_state in ("active",):
                        edges = index.query_edges(
                            similar_ids,
                            depth=1,
                            state=check_state,
                            limit=50,
                            strict=True,
                        )
                        if isinstance(edges, list):
                            for edge in edges:
                                if str(edge.get("relation_type", "")) == "contradicts":
                                    contradictions.append({
                                        "edge_id": str(edge.get("edge_id", "")),
                                        "from_record_id": str(edge.get("from_record_id", "")),
                                        "to_record_id": str(edge.get("to_record_id", "")),
                                        "relation_type": "contradicts",
                                        "edge_state": str(edge.get("state", "")),
                                    })
                except Exception:
                    # A failed graph read is not evidence that the candidate is
                    # contradiction-free.  Keep the gate read-only, but route
                    # the candidate to owner review and expose a bounded error.
                    error_records.append({
                        "candidate_id": cid,
                        "error_code": "edge_query_failed",
                    })
                    flagged.append({
                        "candidate_id": cid,
                        "body_preview": body[:120],
                        "similar_record_ids": similar_ids,
                        "contradiction_count": 0,
                        "contradictions": [],
                        "reason_code": "edge_query_failed",
                    })
                    continue

            if contradictions:
                flagged.append({
                    "candidate_id": cid,
                    "body_preview": body[:120],
                    "similar_record_ids": similar_ids,
                    "contradiction_count": len(contradictions),
                    "contradictions": contradictions[:5],  # cap display
                })
    except sqlite3.Error:
        error_records.append({
            "candidate_id": "",
            "error_code": "fts_query_failed",
        })
        already_flagged = {
            str(item.get("candidate_id") or "") for item in flagged
        }
        for cand in candidate_rows:
            cid = str(cand.get("candidate_id", ""))
            if cid in already_flagged:
                continue
            flagged.append({
                "candidate_id": cid,
                "body_preview": str(cand.get("body", ""))[:120],
                "similar_record_ids": [],
                "contradiction_count": 0,
                "contradictions": [],
                "reason_code": "fts_query_failed",
            })
    finally:
        conn2.close()

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
    status = "error" if error_records else "ok"
    result = {
        "status": status,
        "candidate_count": len(candidate_rows),
        "flagged_count": len(flagged),
        "flagged_candidates": flagged,
        "error_count": len(error_records),
        "error_code": error_records[0]["error_code"] if error_records else "",
        "error_records": error_records,
        "duration_ms": elapsed_ms,
    }

    if audit_path:
        from pathlib import Path
        append_audit(
            Path(audit_path),
            action="crystallization_gate_run",
            status=status,
            target=str(index_path),
            details={
                "candidate_count": len(candidate_rows),
                "flagged_count": len(flagged),
                "flagged_ids": [f["candidate_id"] for f in flagged],
                "error_count": len(error_records),
                "error_codes": sorted({r["error_code"] for r in error_records}),
            },
        )

    return result
