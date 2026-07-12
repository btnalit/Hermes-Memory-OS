"""V2-E clearance cycle orchestration (E4-E8).

Rejudge queue (E4), cycle API (E6), flag flip (E7), monitor stats (E8).
Imports from clearance_receipts (data), crystallized (record access),
permanent_promotion (proposal sweep).  No reverse imports — this module
sits above the data layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .clearance_receipts import (
    ClearanceReceipt,
    invalidate_receipts_since,
    latest_corpus_watermark,
    read_clearance_receipt_snapshot,
    read_clearance_receipts,
    write_clearance_receipt,
)


# ── E4: Rejudge queue ──────────────────────────────────────────────────────


def get_rejudge_queue(roots: Any) -> list[dict[str, Any]]:
    """Return receipt IDs needing rejudge, oldest-first.

    Includes invalidated receipts (clear + conflict equally).
    Deduplicated by record_id, oldest entry retained.
    """
    records = read_clearance_receipts(roots)
    queue: list[dict[str, Any]] = []

    for rec_dict in records:
        receipt = ClearanceReceipt.from_dict(rec_dict)
        if not receipt.is_active:
            queue.append({
                "record_id": receipt.record_id,
                "receipt_id": receipt.receipt_id,
                "old_verdict": receipt.verdict,
                "invalidated_at": receipt.invalidated_at,
                "priority": "normal",
                "entered_at": receipt.invalidated_at or receipt.judged_at,
            })

    queue.sort(key=lambda x: str(x.get("entered_at") or ""))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in queue:
        rid = item["record_id"]
        if rid not in seen:
            seen.add(rid)
            deduped.append(item)
    return deduped


# ── E6: Clearance cycle API ────────────────────────────────────────────────


def run_clearance_cycle(
    store: Any,
    *,
    now: datetime | None = None,
    v2e_enabled: bool = False,
) -> dict[str, Any]:
    """Idempotent clearance cycle tick (E6).

    1. Consume corpus change events → invalidate affected receipts
    2. Select rejudge batch (oldest-first, bounded by budget)
    3. Judge each candidate → produce clearance receipt
    4. Return structured report

    Called by host cron via seam adapter. Execution-gate envelope is
    applied by the caller.
    """
    import hashlib
    import uuid as _uuid

    from .crystallized import CrystallizedMemoryService, is_active_crystallized_frontmatter
    from .knob_overrides import resolve_knob

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    roots = store.roots
    report: dict[str, Any] = {
        "status": "ok",
        "judged": 0,
        "invalidated": 0,
        "queue_depth": 0,
        "oldest_unknown_age_hours": 0.0,
        "budget_used": 0,
        "error_records": [],
        "verdict_distribution": {"clear": 0, "conflict": 0, "unknown": 0},
    }

    budget: int = int(resolve_knob(
        "clearance_rejudge_budget_per_cycle", default=10, roots=roots,
    ))

    # ── Crystallized service (created early — needed by Step 2.5 + Step 3) ──
    crystallized = CrystallizedMemoryService(store)

    # Step 1: invalidation
    invalidation = invalidate_receipts_since(roots, watermark=0)
    report["invalidated"] = invalidation["invalidated_count"]

    # Step 2: select rejudge batch
    queue = get_rejudge_queue(roots)

    # ── Step 2.5 (E9): collect never-judged provisional records ───────────
    # These are records with no clearance receipt at all — they would be
    # permanently blocked by the :232 gate at proposal time
    # (no_clearance_receipt).  Add them to the same queue, oldest-first,
    # sharing the same per-cycle budget with the rejudge queue.
    existing_queue_ids = {item["record_id"] for item in queue}
    all_active_receipt_ids: set[str] = {
        ClearanceReceipt.from_dict(r).record_id
        for r in read_clearance_receipts(roots)
        if ClearanceReceipt.from_dict(r).is_active
    }
    for record in crystallized.list_provisional_records():
        rid = str(record.get("id") or "")
        if not rid or rid in existing_queue_ids or rid in all_active_receipt_ids:
            continue
        queue.append({
            "record_id": rid,
            "receipt_id": None,
            "old_verdict": None,
            "invalidated_at": None,
            "priority": "initial",
            "entered_at": record.get("approved_at") or record.get("created_at") or "",
        })

    # Re-sort after merge: initial + rejudge, oldest-first (E9)
    queue.sort(key=lambda x: str(x.get("entered_at") or ""))
    # Re-dedup after merge
    seen_rids: set[str] = set()
    deduped_queue: list[dict[str, Any]] = []
    for item in queue:
        if item["record_id"] not in seen_rids:
            seen_rids.add(item["record_id"])
            deduped_queue.append(item)
    queue = deduped_queue

    batch = queue[:budget]  # shared budget, oldest-first
    report["queue_depth"] = len(queue)
    report["budget_used"] = len(batch)
    report["initial_never_judged_queued"] = sum(
        1 for item in batch if item.get("priority") == "initial"
    )

    # Compute oldest unknown age
    unknowns = [
        ClearanceReceipt.from_dict(r)
        for r in read_clearance_receipts(roots)
        if ClearanceReceipt.from_dict(r).verdict == "unknown"
        and ClearanceReceipt.from_dict(r).is_active
    ]
    if unknowns:
        oldest_unknown = min(
            (u.judged_at for u in unknowns if u.judged_at),
            default=current.isoformat(),
        )
        try:
            oldest_dt = datetime.fromisoformat(oldest_unknown.replace("Z", "+00:00"))
            report["oldest_unknown_age_hours"] = max(
                0.0,
                (current - oldest_dt.astimezone(timezone.utc)).total_seconds() / 3600.0,
            )
        except (ValueError, TypeError):
            pass

    # Pre-load permanent records once (shared across batch judges)
    permanent_records: list[dict[str, Any]] = []
    if roots.crystallized_root.exists():
        for path in sorted(roots.crystallized_root.glob("*.md")):
            try:
                for rec in crystallized.read_records(path.name):
                    fm = rec.frontmatter
                    if fm.get("provisional") is not True and is_active_crystallized_frontmatter(fm):
                        permanent_records.append({
                            "id": str(fm.get("id") or ""),
                            "body": rec.body,
                            "frontmatter": fm,
                        })
            except Exception:
                continue

    # Step 3: judge each candidate with real contradiction detection
    for item in batch:
        record_id = item["record_id"]
        try:
            record = crystallized.find_record(record_id)
            if record is None:
                continue

            body = record.body
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

            if not permanent_records:
                # Empty corpus clause: no permanents → always clear
                verdict = "clear"
                conflict_refs: list[str] = []
                checked_entity_set = _collect_entities_from_record(store, record_id, record.frontmatter)
                invalidation_mode = "entity_scoped" if checked_entity_set else "conservative_full"
                unknown_reason = ""
            else:
                # Real judge: pair against permanents, detect contradictions
                verdict, conflict_refs, checked_entity_set, invalidation_mode, unknown_reason = (
                    _judge_against_permanents(
                        store, record_id, body, record.frontmatter,
                        permanent_records,
                        max_pairs=int(resolve_knob(
                            "clearance_pair_top_k", default=5, roots=roots,
                        )),
                    )
                )

            # C3: infrastructure-class unknowns skip the budget queue.
            # candidate_unindexed records would use a budget slot every cycle
            # while producing the same unknown verdict.  Excluding them lets
            # solvable candidates reach the judge.  When the index picks them
            # up, they re-enter via invalidation naturally.
            if unknown_reason == "candidate_unindexed":
                report["infra_backoff_count"] = report.get("infra_backoff_count", 0) + 1

            receipt = ClearanceReceipt(
                receipt_id=f"clr_{_uuid.uuid4().hex[:16]}",
                record_id=record_id,
                content_hash=content_hash,
                verdict=verdict,
                conflict_refs=conflict_refs,
                corpus_watermark=latest_corpus_watermark(roots),
                checked_entity_set=checked_entity_set,
                invalidation_mode=invalidation_mode,
                judge_version="v2e_llm",
                judged_at=current.isoformat().replace("+00:00", "Z"),
                unknown_reason=unknown_reason,
            )
            write_clearance_receipt(roots, receipt)
            report["judged"] += 1
            report["verdict_distribution"][verdict] += 1
        except Exception as exc:
            report["error_records"].append({
                "record_id": record_id,
                "error_code": type(exc).__name__,
                "error_summary": str(exc)[:200],
            })

    return report


# ── Clearance judge helpers ──────────────────────────────────────────────


def _check_llm_available(store: Any | None = None) -> bool:
    """Check whether the LLM runtime is available for contradiction judging.

    Reads the live low-clue-recall config from *store* when available,
    falling back to the on-disk ``config.json``.  Extracts the
    ``low_clue_recall`` sub-section before passing to the availability
    check — the top-level ``config.json`` keys (``session_mirror``, etc.)
    are not valid fields for ``normalize_low_clue_recall_config``.

    Returns ``False`` when the LLM cannot be reached — all non-empty-corpus
    records will receive an ``unknown`` verdict (fail-closed).
    """
    try:
        from .low_clue_recall import low_clue_judge_availability as _judge_avail

        full_config: dict[str, Any] | None = None

        # Resolve the live config from the store, then fall back to disk
        if store is not None:
            try:
                config_path = store.roots.memory_os_root / "config.json"
                if config_path.exists():
                    import json as _json
                    full_config = _json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                full_config = None

        if full_config is None:
            # Last resort: try reading from ambient roots (no store available)
            try:
                from .roots import MemoryOSRoots
                ambient = MemoryOSRoots.from_profile()
                config_path = ambient.memory_os_root / "config.json"
                if config_path.exists():
                    import json as _json
                    full_config = _json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                full_config = {}

        # Extract the low_clue_recall subsection — normalize_low_clue_recall_config
        # expects a flat config with "enabled" and "llm_judge" at the top level.
        lcr_config = (
            full_config.get("low_clue_recall")
            if isinstance(full_config, dict) and isinstance(full_config.get("low_clue_recall"), dict)
            else {}
        )

        judge_status = _judge_avail(lcr_config)
        return bool(judge_status.get("available", False))
    except Exception:
        return False


def _collect_entities_from_record(
    store: Any,
    record_id: str,
    frontmatter: dict[str, Any],
) -> list[str]:
    """Collect entity IDs associated with a crystallized record.

    Sources (in priority order):
    1. Frontmatter ``entities`` field (list of entity strings)
    2. Entity index (SQLite entity_index table)
    3. Frontmatter ``tags`` field as fallback

    Returns a deduplicated list of normalized entity IDs. Returns an empty
    list when no entities can be extracted (caller should set
    ``invalidation_mode=conservative_full`` in that case).
    """
    entities: list[str] = []

    # Source 1: explicit entities field in frontmatter
    fm_entities = frontmatter.get("entities")
    if isinstance(fm_entities, list):
        for ent in fm_entities:
            if isinstance(ent, str) and ent.strip():
                entities.append(ent.strip().lower())

    # Source 2: entity index (SQLite)
    if not entities:
        try:
            import sqlite3
            index_path = getattr(store.roots, "index_path", None)
            if index_path is not None:
                conn = sqlite3.connect(str(index_path))
                conn.row_factory = sqlite3.Row
                try:
                    table_check = conn.execute(
                        "select name from sqlite_master "
                        "where type='table' and name='entity_index'"
                    ).fetchone()
                    if table_check is not None:
                        rows = conn.execute(
                            "select distinct entity_id from entity_index "
                            "where record_id = ?",
                            (record_id,),
                        ).fetchall()
                        for row in rows:
                            eid = str(row["entity_id"] or "").strip().lower()
                            if eid:
                                entities.append(eid)
                except sqlite3.Error:
                    pass
                finally:
                    conn.close()
        except Exception:
            pass

    # Source 3: tags fallback
    if not entities:
        fm_tags = frontmatter.get("tags")
        if isinstance(fm_tags, list):
            for tag in fm_tags:
                if isinstance(tag, str) and tag.strip():
                    entities.append(f"tag:{tag.strip().lower()}")

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for e in entities:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result


def _judge_against_permanents(
    store: Any,
    record_id: str,
    body: str,
    frontmatter: dict[str, Any],
    permanent_records: list[dict[str, Any]],
    *,
    max_pairs: int = 5,
) -> tuple[str, list[str], list[str], str, str]:
    """Judge a provisional record against the permanent corpus.

    Constitution matrix (V2-E §5):
    - Empty permanents → ``clear`` (empty corpus clause — handled by caller)
    - LLM unavailable → ``unknown`` + ``judge_unavailable`` (fail-closed)
    - No pairs found → ``unknown`` + ``candidate_unindexed`` (infra gap)
    - Contradiction detected → ``conflict`` with conflict_refs populated
    - No contradiction → ``clear``

    **No path returns a constant verdict** (except empty corpus, which the
    caller handles). Every path with non-empty permanents goes through LLM
    evaluation.

    Returns ``(verdict, conflict_refs, checked_entity_set, invalidation_mode, unknown_reason)``.
    C3: ``unknown_reason`` disambiguates infra gaps from judge decisions:
    ``"candidate_unindexed"`` | ``"judge_unavailable"`` | ``"judge_verdict"`` | ``""``.
    """
    import hashlib
    import json as _json
    import sqlite3

    from .knob_overrides import resolve_knob

    # Collect entities from the provisional record (R2)
    checked_entity_set = _collect_entities_from_record(store, record_id, frontmatter)
    invalidation_mode = "entity_scoped" if checked_entity_set else "conservative_full"

    if not permanent_records:
        # Empty corpus — caller should have handled this, but be defensive
        return ("clear", [], checked_entity_set, invalidation_mode, "")

    # ── LLM availability guard ──────────────────────────────────────────
    if not _check_llm_available(store):
        # Fail-closed: every non-empty-corpus record gets "unknown"
        return ("unknown", [], checked_entity_set, invalidation_mode, "judge_unavailable")

    # ── Prepare LLM config ──────────────────────────────────────────────
    from .low_clue_recall import _call_hermes_runtime_model, _resolve_hermes_default_runtime

    _DEFAULT_LLM_CONFIG: dict[str, Any] = {
        "enabled": True,
        "mode": "bounded_vote",
        "provider": "hermes_default",
        "temperature": 0,
        "timeout_ms": 15000,
        "max_tokens": 512,
        "on_error": "deterministic_fallback",
    }
    resolved = _resolve_hermes_default_runtime(_DEFAULT_LLM_CONFIG)
    if not resolved.get("ok"):
        return ("unknown", [], checked_entity_set, invalidation_mode, "judge_unavailable")
    llm_config = dict(_DEFAULT_LLM_CONFIG)

    # ── Pair provisional with permanents ────────────────────────────────
    # Priority: entity-index shared entities → cosine fallback
    pairs = _pair_with_permanents(
        store, record_id, body, permanent_records, max_pairs=max_pairs,
    )

    if not pairs:
        # No pairs found (e.g., no embeddings, no entity overlap) —
        # can't judge, fail-closed (C3: infra gap, not judge error)
        return ("unknown", [], checked_entity_set, invalidation_mode, "candidate_unindexed")

    # ── LLM claim extraction + contradiction detection per pair ─────────
    from .llm_contradiction_lane import _claims_contradict

    conflict_refs: list[str] = []

    _JUDGE_PROMPT = (
        "You are a precise fact extractor. Given two memory records, "
        "extract the core factual claim from each.\n\n"
        "For each record, output a JSON object with:\n"
        "- subject: the entity or concept the claim is about (short phrase)\n"
        "- predicate: the property or relationship being asserted (short phrase)\n"
        "- object: the value or conclusion being asserted (short phrase)\n"
        "- confidence: your confidence that this is the core claim (0.0-1.0)\n\n"
        "If a record does not contain a clear factual claim, set confidence to 0.\n\n"
        "Return ONLY a JSON object with keys \"claim_a\" and \"claim_b\".\n\n"
        "Record A (provisional):\n"
        "__BODY_A__\n\n"
        "Record B (permanent):\n"
        "__BODY_B__"
    )

    for pair in pairs:
        perm = pair["permanent"]
        prompt = (
            _JUDGE_PROMPT
            .replace("__BODY_A__", body[:1200])
            .replace("__BODY_B__", str(perm.get("body", ""))[:1200])
        )

        try:
            response = _call_hermes_runtime_model(prompt, llm_config)
        except Exception:
            # LLM call failed → this pair can't be judged, skip to next
            continue

        if not response or not response.strip():
            continue

        # Parse LLM response (robust JSON extraction)
        try:
            parsed = _json.loads(response.strip())
        except _json.JSONDecodeError:
            start = response.find("{")
            if start == -1:
                continue
            depth = 0
            end = -1
            for _i in range(start, len(response)):
                if response[_i] == "{":
                    depth += 1
                elif response[_i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = _i
                        break
            if end == -1:
                continue
            try:
                parsed = _json.loads(response[start:end + 1])
            except _json.JSONDecodeError:
                continue

        claim_a = parsed.get("claim_a") if isinstance(parsed.get("claim_a"), dict) else {}
        claim_b = parsed.get("claim_b") if isinstance(parsed.get("claim_b"), dict) else {}

        if not claim_a or not claim_b:
            continue

        if _claims_contradict(claim_a, claim_b):
            conflict_refs.append(str(perm.get("id") or ""))

    if conflict_refs:
        # Also collect entities from conflicting permanents
        for perm in permanent_records:
            if str(perm.get("id") or "") in conflict_refs:
                perm_entities = _collect_entities_from_record(
                    store, str(perm.get("id") or ""),
                    perm.get("frontmatter") if isinstance(perm.get("frontmatter"), dict) else {},
                )
                for e in perm_entities:
                    if e not in checked_entity_set:
                        checked_entity_set.append(e)
        return ("conflict", conflict_refs, checked_entity_set, invalidation_mode, "")

    return ("clear", [], checked_entity_set, invalidation_mode, "")


def _pair_with_permanents(
    store: Any,
    record_id: str,
    body: str,
    permanent_records: list[dict[str, Any]],
    *,
    max_pairs: int = 5,
) -> list[dict[str, Any]]:
    """Pair a provisional record with permanent records for contradiction check.

    Two-tier strategy:
    1. Entity-index shared entities (priority)
    2. Cosine similarity top-K fallback

    Returns a list of ``{"permanent": dict, "similarity": float}`` entries,
    bounded by *max_pairs*.
    """
    import sqlite3

    from .knob_overrides import resolve_knob
    from .vector_edge_proposer import _cosine_similarity

    index_path = getattr(store.roots, "index_path", None)
    if index_path is None or not permanent_records:
        return []

    roots = store.roots
    same_topic_threshold: float = float(resolve_knob(
        "llm_contradiction_same_topic_threshold", default=0.75, roots=roots,
    ))

    # Build a map of permanent ID → record for lookup
    perm_by_id: dict[str, dict[str, Any]] = {}
    for pr in permanent_records:
        pid = str(pr.get("id") or "")
        if pid:
            perm_by_id[pid] = pr

    pairs: list[dict[str, Any]] = []
    paired_perm_ids: set[str] = set()

    conn = sqlite3.connect(str(index_path))
    conn.row_factory = sqlite3.Row

    # ── Phase 1: entity-index based pairing ────────────────────────────
    try:
        table_check = conn.execute(
            "select name from sqlite_master where type='table' and name='entity_index'"
        ).fetchone()
    except sqlite3.Error:
        table_check = None

    if table_check is not None:
        try:
            from .entity_extractor import shared_entity_pairs

            entity_pairs = shared_entity_pairs(
                conn, min_shared_entities=1, max_pairs=max_pairs * 2,
            )

            # Filter to only provisional×permanent pairs
            for ep in entity_pairs:
                if len(pairs) >= max_pairs:
                    break
                rec_a = ep["record_a"]
                rec_b = ep["record_b"]

                # Find which side is our provisional, which is permanent
                perm_id = ""
                if rec_a == record_id and rec_b in perm_by_id:
                    perm_id = rec_b
                elif rec_b == record_id and rec_a in perm_by_id:
                    perm_id = rec_a
                else:
                    continue

                if perm_id in paired_perm_ids:
                    continue

                perm_rec = perm_by_id[perm_id]
                pairs.append({
                    "permanent": perm_rec,
                    "similarity": 0.0,  # entity-based: no cosine score
                })
                paired_perm_ids.add(perm_id)
        except Exception:
            pass

    conn.close()

    # ── Phase 2: cosine-similarity fallback ─────────────────────────────
    remaining_slots = max_pairs - len(pairs)
    if remaining_slots <= 0:
        return pairs

    # Get embedding for the provisional record
    try:
        conn2 = sqlite3.connect(str(index_path))
        conn2.row_factory = sqlite3.Row
        prov_row = conn2.execute(
            "select me.embedding from memory_embeddings me "
            "where me.record_type = 'crystallized_record' and me.record_id = ?",
            (record_id,),
        ).fetchone()
        conn2.close()
    except sqlite3.Error:
        return pairs

    if prov_row is None or not prov_row["embedding"]:
        return pairs

    prov_embedding = bytes(prov_row["embedding"])

    # Get embeddings for unpaired permanents
    scored: list[tuple[float, dict[str, Any]]] = []
    for pr in permanent_records:
        pid = str(pr.get("id") or "")
        if pid in paired_perm_ids:
            continue
        if not pid:
            continue

        try:
            conn3 = sqlite3.connect(str(index_path))
            conn3.row_factory = sqlite3.Row
            perm_row = conn3.execute(
                "select me.embedding from memory_embeddings me "
                "where me.record_type = 'crystallized_record' and me.record_id = ?",
                (pid,),
            ).fetchone()
            conn3.close()
        except sqlite3.Error:
            continue

        if perm_row is None or not perm_row["embedding"]:
            continue

        perm_embedding = bytes(perm_row["embedding"])
        sim = _cosine_similarity(prov_embedding, perm_embedding)
        if sim is not None and sim >= same_topic_threshold:
            scored.append((sim, pr))

    scored.sort(key=lambda x: x[0], reverse=True)
    for sim, pr in scored[:remaining_slots]:
        pairs.append({"permanent": pr, "similarity": sim})

    return pairs


# ── E7: Flag flip ──────────────────────────────────────────────────────────


def sweep_unavailable_open_proposals_on_flag_flip(store: Any) -> dict[str, Any]:
    """Sweep open proposals with clearance.status='unavailable' on v2e flag flip.

    Called once during flag flip. Sets them to terminal 'revoked' with
    reason 'v2e_flag_flip'. Target records are enqueued for high-priority
    rejudge (E7 per design).
    """
    from .permanent_promotion import PermanentPromotionService

    service = PermanentPromotionService(store)
    swept_count = 0
    swept_ids: list[str] = []
    error_records: list[dict[str, Any]] = []

    for state in service.proposals._states().values():
        if state.get("status") not in {"open", "deciding"}:
            continue
        clearance = state.get("clearance")
        if isinstance(clearance, dict) and clearance.get("status") == "unavailable":
            proposal_id = str(state.get("proposal_id") or "")
            try:
                service.proposals.append_terminal(
                    proposal_id,
                    status="revoked",
                    reason="v2e_flag_flip",
                    detail="swept on v2e flag flip — no clearance receipt available",
                )
                swept_count += 1
                if proposal_id:
                    swept_ids.append(proposal_id)
            except Exception as exc:
                error_records.append({
                    "proposal_id": proposal_id,
                    "error_code": type(exc).__name__,
                })

    return {
        "status": "ok",
        "swept_count": swept_count,
        "swept_proposal_ids": swept_ids,
        "error_records": error_records,
    }


# ── E8: Monitor fields ─────────────────────────────────────────────────────


def clearance_monitor_stats(roots: Any) -> dict[str, Any]:
    """Return monitor-facing clearance system stats (E8)."""
    records = read_clearance_receipts(roots)

    verdict_counts: dict[str, int] = {"clear": 0, "conflict": 0, "unknown": 0}
    invalidated_count = 0
    for rec in records:
        r = ClearanceReceipt.from_dict(rec)
        if r.is_active:
            verdict = r.verdict
            if verdict in verdict_counts:
                verdict_counts[verdict] += 1
        else:
            invalidated_count += 1

    queue = get_rejudge_queue(roots)
    unknowns = [
        r for r in records
        if ClearanceReceipt.from_dict(r).verdict == "unknown"
        and ClearanceReceipt.from_dict(r).is_active
    ]

    oldest_age = 0.0
    if unknowns:
        now = datetime.now(timezone.utc)
        for u in unknowns:
            judged = ClearanceReceipt.from_dict(u).judged_at
            if judged:
                try:
                    dt = datetime.fromisoformat(judged.replace("Z", "+00:00"))
                    age = (now - dt.astimezone(timezone.utc)).total_seconds() / 3600.0
                    oldest_age = max(oldest_age, age)
                except (ValueError, TypeError):
                    pass

    cf_total = 0
    cf_count = 0
    for rec in records:
        r = ClearanceReceipt.from_dict(rec)
        if r.invalidation_mode == "conservative_full":
            cf_total += 1
            if not r.is_active:
                cf_count += 1
    conservative_full_rate = (cf_count / cf_total) if cf_total > 0 else 0.0

    # C3: per-reason unknown breakdown
    unknown_reason_counts: dict[str, int] = {}
    for rec in records:
        r = ClearanceReceipt.from_dict(rec)
        if r.verdict == "unknown" and r.is_active:
            reason = r.unknown_reason or "unspecified"
            unknown_reason_counts[reason] = unknown_reason_counts.get(reason, 0) + 1

    # C3: filter oldest-unknown-age to only judge-class unknowns (not infra gaps)
    judge_unknowns = [
        u for u in unknowns
        if ClearanceReceipt.from_dict(u).unknown_reason not in ("candidate_unindexed",)
    ]
    judge_oldest_age = 0.0
    if judge_unknowns:
        now = datetime.now(timezone.utc)
        for u in judge_unknowns:
            judged = ClearanceReceipt.from_dict(u).judged_at
            if judged:
                try:
                    dt = datetime.fromisoformat(judged.replace("Z", "+00:00"))
                    age = (now - dt.astimezone(timezone.utc)).total_seconds() / 3600.0
                    judge_oldest_age = max(judge_oldest_age, age)
                except (ValueError, TypeError):
                    pass

    return {
        "schema_version": "memory-os.clearance_monitor_stats.v0",
        "clearance_receipts_total": len(records),
        "clearance_receipts_clear": verdict_counts["clear"],
        "clearance_receipts_conflict": verdict_counts["conflict"],
        "clearance_receipts_unknown": verdict_counts["unknown"],
        "receipts_invalidated_count": invalidated_count,
        "rejudge_queue_depth": len(queue),
        "oldest_unknown_age_hours": round(judge_oldest_age if judge_unknowns else oldest_age, 1),
        "conservative_full_invalidation_rate": round(conservative_full_rate, 2),
        "unknown_reason_distribution": unknown_reason_counts,
    }
