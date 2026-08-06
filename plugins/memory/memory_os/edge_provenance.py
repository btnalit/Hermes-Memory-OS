"""Provenance edge mining — event→crystallized evidence_for edges (W4).

图源三档原则第 2 档:溯源关系已经躺在结晶记录的 ``source_event_ids``
元数据里,结晶批准时整条链已过 OwnerGate — 因此这些边免 LLM、免相似度、
确定性,写为 auto-active。方向为 ``event → crystallized``(事件是结晶的
证据),使 FTS 锚点落在 event 段时能一跳召回结晶目标 — prefetch 锚点大量
落在 event/working 段,而此前图里只有结晶↔结晶边,锚点几乎永远查不到边
(shadow 账本一个月仅 4 次命中)。

事件会被 retention 清出热存储(``cleanup._prune_event_line``):事件侧
悬挂是可容忍设计 — 锚点随事件出索引自然停火;注入侧配套规则(prefetch
对非 crystallized 目标不落 [unresolved:] 兜底行)防止其变成噪音。

Runs as a cognitive-loop step.  Bounded per run; idempotent (write-boundary
triple dedup is the authority, an in-run set avoids wasted writes).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .audit import append_audit

# Per-run bound: production has tens of crystallized records; the cap only
# guards against pathological metadata.
MAX_EDGES_PER_RUN = 200


def run_edge_provenance(
    index_path: str,
    *,
    index: object | None = None,
    audit_path: str | None = None,
) -> dict[str, Any]:
    """Mine event→crystallized evidence_for edges from source_event_ids."""
    start_time = datetime.now(timezone.utc)

    try:
        conn = sqlite3.connect(index_path)
    except sqlite3.Error:
        return {"status": "error", "error": f"cannot_open_index: {index_path}", "proposed_count": 0}
    conn.row_factory = sqlite3.Row
    try:
        try:
            records = conn.execute(
                "select id, source_event_ids_json from crystallized_records order by created_at"
            ).fetchall()
        except sqlite3.Error:
            return {"status": "error", "error": "cannot_read_crystallized_records", "proposed_count": 0}
    finally:
        conn.close()

    if not records:
        return {
            "status": "ok",
            "outcome": "no_crystallized_records",
            "record_count": 0,
            "proposed_count": 0,
            "dedup_skipped": 0,
        }

    proposed = 0
    dedup_skipped = 0
    write_failed = 0
    scanned_refs = 0
    in_run: set[tuple[str, str]] = set()

    for rec in records:
        if proposed >= MAX_EDGES_PER_RUN:
            break
        record_id = str(rec["id"] or "")
        if not record_id:
            continue
        raw = rec["source_event_ids_json"]
        event_ids: list[str] = []
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    event_ids = [str(v) for v in parsed if str(v or "").strip()]
            except (json.JSONDecodeError, TypeError):
                event_ids = []
        elif isinstance(raw, list):
            event_ids = [str(v) for v in raw if str(v or "").strip()]

        for event_id in event_ids:
            if proposed >= MAX_EDGES_PER_RUN:
                break
            scanned_refs += 1
            key = (event_id, record_id)
            if key in in_run:
                continue
            in_run.add(key)
            if index and hasattr(index, "write_governed_edge"):
                result = index.write_governed_edge(
                    from_record_type="event",
                    from_record_id=event_id,
                    to_record_type="crystallized_record",
                    to_record_id=record_id,
                    relation_type="evidence_for",
                    weight=1.0,
                    source_event_id=event_id,
                    proposed_by="provenance",
                    # 元数据在结晶批准时已过 OwnerGate → auto-active;
                    # 与 llm 的 _AUTO_ACTIVE_TYPES(evidence_for 在列)一致。
                    state="active",
                )
                if result.get("skipped_duplicate"):
                    dedup_skipped += 1
                elif result:
                    proposed += 1
                else:
                    write_failed += 1

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
    summary = {
        "status": "ok",
        "outcome": "produced" if proposed else ("all_known" if scanned_refs else "no_source_event_ids"),
        "record_count": len(records),
        "scanned_ref_count": scanned_refs,
        "proposed_count": proposed,
        "dedup_skipped": dedup_skipped,
        "write_failed_count": write_failed,
        "duration_ms": elapsed_ms,
        "begin_at": start_time.isoformat(),
    }

    if audit_path:
        from pathlib import Path
        append_audit(
            Path(audit_path),
            action="edge_provenance_run",
            status="ok",
            target=str(index_path),
            details=summary,
        )

    return summary
