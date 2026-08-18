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
from typing import Any, Callable

from .audit import append_audit


_MAX_CANDIDATES = 100
_FTS_LIMIT = 5  # most similar records to check per candidate


def _gate_error_result(code: str, *, component: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": code,
        "error_code": code,
        "error_count": 1,
        # Same record shape as the per-candidate errors below.  These two used to
        # disagree ("code" here, "error_code" there) inside one return field, so
        # any consumer that read error_code would have found None on this path.
        "error_records": [
            {"candidate_id": "", "error_code": code, "component": component}
        ],
        "candidate_count": 0,
        "flagged_count": 0,
        "flagged_candidates": [],
        "duration_ms": 0,
        # Same key set on every return shape: a reader must never have to
        # guess whether a missing dialect means "legacy" or "no query ran".
        "fts_tokenizer": "",
        "fts_query_mode": "not_queried",
    }


# \u2500\u2500 FTS5 query-term builders \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
#
# These tokens become an FTS5 MATCH query, so they MUST agree with the
# tokenizer the index was actually built with (index.py records the choice in
# ``index_metadata.fts_tokenizer``).  Getting this wrong is not a weaker
# search -- it is a silently empty one:
#
#   * ``trigram`` (the preferred form, index.py:638) matches on character
#     trigrams, so a query term shorter than 3 characters cannot match at all.
#     ``_legacy_tokens`` below collapses a whole run of CJK into ONE token
#     (the character-class ranges never break between Chinese characters), so
#     on a trigram index a Chinese candidate degenerates to "the entire
#     sentence must appear verbatim as a substring": measured against a real
#     trigram table, such a query found only the row it came from and never a
#     paraphrase, leaving the gate's edge check unreachable for Chinese
#     content.  Character trigrams restore it.
#     Bigrams do NOT -- on the same real trigram table a bigram OR-query
#     returned ZERO rows, i.e. a bigram "fix" is indistinguishable from the
#     defect it claims to repair, which is exactly how it would ship unnoticed.
#   * ``unicode61`` (the fallback form, index.py:646) tokenizes indexed CJK
#     into whole runs as well, so query and index agree there.  Recall is weak
#     (no paraphrase matching) but self-consistent, and NO query-side change
#     can improve it -- that needs an index rebuild, which is legitimate but
#     out of this function's scope.  The legacy tokens are kept deliberately.
#
# Anything else, including a missing ``index_metadata`` table, is treated as
# the fallback: never guess trigram semantics for an unknown index.
_TRIGRAM_TOKENIZER = "trigram"

# CJK ideographs + kana + hangul.  The defect is not Chinese-specific: every
# script here is matched by the legacy class without any intra-run break.
_CJK_RUN_PATTERN = r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+"


def _legacy_tokens(text: str) -> set[str]:
    """Whole-run token set matching a ``unicode61``-shaped index."""
    return set(re.findall(r"[a-z\u4e00-\u9fff][a-z0-9\u4e00-\u9fff]*", text.lower()))


def _trigram_tokens(text: str) -> set[str]:
    """Query terms for a ``tokenize='trigram'`` index.

    CJK/kana/hangul runs become character trigrams; ASCII alphanumeric tokens
    are kept only at length >= 3, because a trigram index cannot match a
    shorter term at all.  Dropping "ok"/"db" is that index's semantics, not a
    regression introduced here.
    """
    lowered = text.lower()
    terms: set[str] = set(re.findall(r"[a-z0-9]{3,}", lowered))
    for run in re.findall(_CJK_RUN_PATTERN, lowered):
        for start in range(max(0, len(run) - 2)):
            terms.add(run[start:start + 3])
    return terms


def _fts_match_query(terms: set[str]) -> str:
    """OR-join terms as quoted FTS5 phrases.

    Quoting is not cosmetic: a bare CJK or mixed term can be parsed as MATCH
    syntax rather than as text, which raises instead of searching.  Sorted for
    a deterministic query string per candidate.
    """
    cleaned = sorted({term.replace('"', "").strip() for term in terms} - {""})
    return " OR ".join(f'"{term}"' for term in cleaned)


def _query_builder_for(fts_tokenizer: str) -> tuple[str, Callable[[str], set[str]]]:
    """Return ``(reported_mode, term_builder)`` for an index tokenizer.

    Deliberately ONE function: if the dialect that gets reported and the
    dialect that actually builds the query were derived separately, a future
    edit could change one and leave the other lying -- which is precisely the
    "a gate whose vocabulary drifts from its producer checks nothing" failure
    this codebase has already paid for once.
    """
    if fts_tokenizer == _TRIGRAM_TOKENIZER:
        return "trigram", _trigram_tokens
    return "legacy", _legacy_tokens


def _tokenize(text: str) -> set[str]:
    """Backwards-compatible alias for the legacy (unicode61-shaped) tokens."""
    return _legacy_tokens(text)


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
            "fts_tokenizer": "",
            "fts_query_mode": "not_queried",
        }

    # 2. For each candidate, search for similar crystallized records and check
    #    for contradicts edges.
    flagged: list[dict[str, Any]] = []
    error_records: list[dict[str, str]] = []
    # Bound before the connection so the reported dialect is always defined,
    # including on the `fts_query_failed` path below.
    fts_tokenizer = ""
    fts_query_mode, build_query_terms = _query_builder_for(fts_tokenizer)
    conn2 = sqlite3.connect(index_path)
    conn2.row_factory = sqlite3.Row
    try:
        # Resolve the index's own tokenizer ONCE per run and build every query
        # in its dialect.  ``_metadata_value`` returns "" for a database with
        # no ``index_metadata`` table, which lands on the conservative legacy
        # branch rather than guessing trigram semantics.
        from .index import _metadata_value

        fts_tokenizer = _metadata_value(conn2, "fts_tokenizer")
        fts_query_mode, build_query_terms = _query_builder_for(fts_tokenizer)
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
            # Use the first 300 chars as query, in the index's own dialect.
            # A body that is a single 2-character CJK run yields no trigram at
            # all -- that lands on the same empty-query skip as an empty body.
            head = body[:300]
            query_words = _fts_match_query(
                build_query_terms(head)
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
                        "component": "crystallization_gate",
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
                        "component": "crystallization_gate",
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
            "component": "crystallization_gate",
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
        # Which dialect the queries were built in.  Without this a zero-flag
        # run cannot be told apart from a run whose queries could never match
        # the index -- the exact confusion that hid the CJK defect for months.
        "fts_tokenizer": fts_tokenizer or "unknown",
        "fts_query_mode": fts_query_mode,
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
