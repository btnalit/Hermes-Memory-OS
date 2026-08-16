"""Edge weight-feedback loop — hit reinforcement + long-idle forgetting (R4).

Owner 决策 2026-08-06:「动态图谱应该是动态去更新关系的…不是永远记忆,
不需要人工介入」。审批模型废除(R1/R2/R3)后,本闭环是边质量的唯一
治理机制:

  - **强化**:prefetch 注入命中(``system/graph_layer_shadow.jsonl``,由
    ``_record_graph_layer_shadow`` 真实生产)→ 命中边 weight 强化,经 W0
    同款 canonical 写回持久。**只有 ``injected=True`` 的边算命中**(shadow
    v1/F2):knob 关闭、被权重下限过滤、目标解析失败的边都会落账但不算
    命中 — v0 时代「查到边」与「注入命中」共用一份语义,从未展示过的边
    也被当命中强化过。缺 ``injected`` 字段的历史行按旧语义(算命中)。
  - **遗忘**:active 边 ``FORGET_AFTER_DAYS`` 无命中 → invalidated
    (G3 不删,每轮上限 FORGET_MAX_PER_RUN)。遗忘水位取
    max(created_at, last_hit, first_injection_at) — 「60 天无命中」必须从
    **首次真实注入**之日起算(v0 用闭环首跑时间,但 knob 关闭期间 shadow
    照样有行,守卫 ``shadow_exists and lines`` 会在从未展示过任何东西的
    时期放行遗忘);无 first_injection_at(注入从未活跃)不遗忘。

Durable state: ``system/edge_weight_feedback_state.json``
(processed_line_count cursor + per-edge last_hit + first_run_at +
first_injection_at)。Completion Is Not Output: closed outcome +
production counters(含 already_saturated / skipped_not_injected /
invalidated_never_hit / forget_eligible_backlog)。

Runs as a cognitive-loop step.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from .audit import append_audit
from .state_overlay import _atomic_write_json

# 乘性强化:w += RATE × (1 − w)。1.0 是不可达渐近线 — 高分区并列消失
# (排序始终有区分度),且 weight==1.0 从此可判定为未迁移遗留行。出生
# 0.55 起 5 次命中 ≈0.76、10 次 ≈0.86、20 次 ≈0.96。旧版加性 +0.05 在
# 全 1.0 出生权重下永远抬不动任何边(P3)。
HIT_LEARNING_RATE = 0.12
FORGET_AFTER_DAYS = 60
FORGET_MAX_PER_RUN = 50
STATE_FILENAME = "edge_weight_feedback_state.json"


def _load_state(path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _line_fingerprint(line: str) -> str:
    """Content fingerprint for the last-consumed shadow-ledger line.

    Used to detect cursor misalignment (e.g. a future compaction that
    trims/rewrites the head of ``graph_layer_shadow.jsonl``) even in the
    edge case where the post-compaction line count happens to still be
    >= the old cursor — a bare line-count comparison alone would miss that.
    """
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]


def run_edge_weight_feedback(
    index_path: str,
    *,
    index: object | None = None,
    audit_path: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    start_time = datetime.now(timezone.utc)
    current = (now or start_time).astimezone(timezone.utc)

    roots = getattr(index, "roots", None)
    if roots is None:
        return {
            "status": "error", "outcome": "error",
            "error": "index_with_roots_required",
            "reinforced_count": 0, "forgotten_count": 0,
        }

    shadow_path = roots.memory_os_root / "system" / "graph_layer_shadow.jsonl"
    state_path = roots.memory_os_root / "system" / STATE_FILENAME
    state = _load_state(state_path)
    processed = int(state.get("processed_line_count") or 0)
    expected_fingerprint = state.get("processed_line_fingerprint")
    last_hit: dict[str, str] = dict(state.get("edge_last_hit") or {})
    first_run_at = str(state.get("first_run_at") or "") or current.isoformat()
    # v0→v1 state 迁移:v0 只有 first_run_at(闭环首跑)。生产的 shadow 自
    # E8c 起才有真实注入,首跑(2026-08-07)与首次注入同日,保守继承。
    # 只对 v0 状态迁移:v1 状态里 first_injection_at 为空是「注入从未活跃」
    # 的真实信号(knob 关闭期),回落 first_run_at 会误开遗忘。
    first_injection_at = str(state.get("first_injection_at") or "")
    if not first_injection_at and str(state.get("schema_version") or "").endswith(".v0"):
        first_injection_at = str(state.get("first_run_at") or "")

    reinforced = 0
    forgotten = 0
    failed = 0
    unresolved_hits = 0
    skipped_not_injected = 0
    already_saturated = 0
    invalidated_never_hit = 0
    forget_eligible = 0

    shadow_exists = shadow_path.exists()
    lines: list[str] = []
    if shadow_exists:
        try:
            lines = shadow_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []

    # ── Cursor alignment check ──────────────────────────────────────────
    # `processed` is a LINE-COUNT cursor into a ledger the write side
    # (prefetch._record_graph_layer_shadow) appends to without bound and
    # metadata_retention.py registers for future compaction planning (that
    # planner is dry-run only today — nothing removes rows yet — but the
    # cursor must not silently assume it never will). If the ledger is ever
    # compacted (head rows removed/renumbered), a bare `lines[processed:]`
    # either replays already-reinforced rows (non-idempotent: HIT_LEARNING_RATE
    # over-reinforces on replay) or — the branch already guarded by
    # `len(lines) > processed` — silently drops the entire unconsumed
    # backlog and rewrites the cursor as if it had been consumed. Detect
    # misalignment via (a) the ledger having fewer lines than the old
    # cursor expected, or (b) the content at the old cursor position no
    # longer matching what was last consumed (guards a same-or-larger
    # line count after a compaction+append that coincidentally lands on
    # the old cursor value). A missing/empty stored fingerprint (state
    # written before this fix, or processed == 0) never triggers (b) —
    # only (a) can fire against pre-fix state.
    cursor_misaligned = False
    cursor_misalignment_reason: str | None = None
    cursor_previous_line_count = processed
    if processed > 0:
        if len(lines) < processed:
            cursor_misaligned = True
            cursor_misalignment_reason = "ledger_shorter_than_cursor"
        elif expected_fingerprint and _line_fingerprint(lines[processed - 1]) != expected_fingerprint:
            cursor_misaligned = True
            cursor_misalignment_reason = "ledger_fingerprint_mismatch"

    if cursor_misaligned:
        # Do NOT reprocess from zero (non-idempotent reinforcement would
        # over-weight already-seen edges) and do NOT trust `lines[processed:]`
        # (those indices no longer mean what they used to). Realign the
        # cursor to the current file and process nothing this run; the gap
        # is reported below instead of silently disappearing into a clean
        # "no_new_hits" outcome. `last_hit` / `first_injection_at` are left
        # untouched — they are independent of the shadow-ledger cursor.
        new_lines: list[str] = []
        # Best-effort, count-based lower bound on how many previously-tracked
        # ledger positions vanished out from under the cursor. It is a bound,
        # not a claim about how many real injection hits were lost — some or
        # all of that gap may have already been reinforced in a prior run.
        cursor_skipped_row_count = max(0, processed - len(lines))
    else:
        new_lines = lines[processed:] if len(lines) > processed else []
        cursor_skipped_row_count = 0

    try:
        conn = sqlite3.connect(index_path)
    except sqlite3.Error:
        return {
            "status": "error", "outcome": "error",
            "error": f"cannot_open_index: {index_path}",
            "reinforced_count": 0, "forgotten_count": 0,
        }
    conn.row_factory = sqlite3.Row
    try:
        from .index import transition_edge_state, update_edge_weight

        # ── 1. Reinforce hit edges from new shadow records ─────────────
        for raw in new_lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            hit_at = str(record.get("created_at") or record.get("recorded_at") or "") or current.isoformat()
            for edge_ref in record.get("edges") or []:
                if not isinstance(edge_ref, dict):
                    continue
                # Shadow v1(F2):只有真实进入 agent 上下文的边算命中。
                # 缺字段的历史 v0 行按旧语义(算命中),已消费 cursor 之前
                # 的行不受影响。
                if edge_ref.get("injected", True) is False:
                    skipped_not_injected += 1
                    continue
                if not first_injection_at:
                    first_injection_at = hit_at
                try:
                    row = conn.execute(
                        "select edge_id, weight from memory_edges"
                        " where from_record_id = ? and to_record_id = ?"
                        " and relation_type = ? and state = 'active' limit 1",
                        (
                            str(edge_ref.get("from_record_id") or ""),
                            str(edge_ref.get("to_record_id") or ""),
                            str(edge_ref.get("relation_type") or ""),
                        ),
                    ).fetchone()
                except sqlite3.Error:
                    row = None
                if row is None:
                    unresolved_hits += 1
                    continue
                edge_id = str(row["edge_id"])
                current_weight = float(row["weight"])
                result = update_edge_weight(
                    conn,
                    edge_id,
                    current_weight + HIT_LEARNING_RATE * (1.0 - current_weight),
                    roots=roots,
                )
                if result and result.get("weight_update_noop"):
                    # F3:权重已在目标值(饱和)— 强化没有发生,不许计成
                    # reinforced(生产首轮报 32 条「强化」,全部是此类
                    # no-op)。但命中是真实的:必须刷新 last_hit,否则被
                    # 高频使用的饱和边会被遗忘环处决。
                    already_saturated += 1
                    last_hit[edge_id] = hit_at
                elif result:
                    reinforced += 1
                    last_hit[edge_id] = hit_at
                else:
                    failed += 1

        # ── 2. Forget long-idle active edges ───────────────────────────
        # Only when injection has EVER really delivered lines to the agent
        # (first_injection_at):v0 守卫是「shadow 文件存在且非空」,但 knob
        # 关闭期间 shadow 照样有行(v1 更是每次都落账)— 那个守卫会在从未
        # 展示过任何东西的时期放行遗忘,正是它要防的「上线首日屠杀存量」。
        if first_injection_at:
            cutoff = (current - timedelta(days=FORGET_AFTER_DAYS)).isoformat()
            try:
                actives = conn.execute(
                    "select edge_id, created_at from memory_edges"
                    " where state = 'active' order by created_at asc",
                ).fetchall()
            except sqlite3.Error:
                actives = []
            for row in actives:
                edge_id = str(row["edge_id"])
                anchor = max(
                    str(row["created_at"] or ""),
                    last_hit.get(edge_id, ""),
                    first_injection_at,
                )
                if not anchor or anchor >= cutoff:
                    continue
                # 全量计数 eligible(积压可见性):cap 只限制本轮处决数,
                # 大规模遗忘潮会摊成多轮 — 监控要能看到待遗忘积压,否则
                # 看起来像闭环卡住。
                forget_eligible += 1
                if forgotten >= FORGET_MAX_PER_RUN:
                    continue
                never_hit = edge_id not in last_hit
                result = transition_edge_state(
                    conn, edge_id, "invalidated", roots=roots,
                )
                if result and result.get("state") == "invalidated":
                    forgotten += 1
                    if never_hit:
                        # 从未获得任何展示机会就被判「无命中」— 该计数若
                        # 居高不下,说明探索轮转覆盖不足(饿死信号),不是
                        # 边没价值。
                        invalidated_never_hit += 1
                    last_hit.pop(edge_id, None)
                else:
                    failed += 1
    finally:
        conn.close()

    # ── 3. Persist cursor + hit watermarks (durable state) ─────────────
    state_out = {
        "schema_version": "memory-os.edge_weight_feedback_state.v1",
        "first_run_at": first_run_at,
        "first_injection_at": first_injection_at,
        "processed_line_count": len(lines),
        "processed_line_fingerprint": _line_fingerprint(lines[-1]) if lines else None,
        "edge_last_hit": last_hit,
        "updated_at": current.isoformat(),
    }
    if cursor_misaligned:
        state_out["last_cursor_misalignment"] = {
            "detected_at": current.isoformat(),
            "reason": cursor_misalignment_reason,
            "previous_line_count": cursor_previous_line_count,
            "realigned_line_count": len(lines),
            "skipped_row_count": cursor_skipped_row_count,
        }
    elif "last_cursor_misalignment" in state:
        # Preserve the most recent misalignment record across aligned runs
        # so it stays visible until the next misalignment overwrites it.
        state_out["last_cursor_misalignment"] = state["last_cursor_misalignment"]
    try:
        _atomic_write_json(state_path, state_out)
    except Exception:
        failed += 1

    if reinforced or forgotten or already_saturated:
        outcome = "reinforced"
    elif cursor_misaligned:
        # Distinct from "no_new_hits": we did NOT verify there was nothing
        # new — the cursor could no longer be trusted, so nothing was read.
        outcome = "cursor_misaligned"
    elif not shadow_exists:
        outcome = "no_shadow_ledger"
    elif not first_injection_at:
        outcome = "injection_never_live"
    else:
        outcome = "no_new_hits"

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
    summary = {
        "status": "ok" if not (failed and not reinforced and not forgotten) else "error",
        "outcome": outcome,
        "new_hit_record_count": len(new_lines),
        "reinforced_count": reinforced,
        "already_saturated_count": already_saturated,
        "skipped_not_injected_count": skipped_not_injected,
        "forgotten_count": forgotten,
        "invalidated_never_hit_count": invalidated_never_hit,
        "forget_eligible_backlog": max(0, forget_eligible - forgotten),
        "unresolved_hit_count": unresolved_hits,
        "failed_count": failed,
        "tracked_edge_count": len(last_hit),
        # Cursor-alignment fields are unconditional (0/None when aligned) so
        # monitors get a stable schema; they can be non-zero even when
        # `outcome == "reinforced"` (forgetting still runs on a misaligned
        # run — only the shadow-hit reinforcement stream is affected).
        "cursor_misaligned": cursor_misaligned,
        "cursor_misalignment_reason": cursor_misalignment_reason,
        "cursor_previous_line_count": cursor_previous_line_count,
        "cursor_realigned_line_count": len(lines),
        "cursor_skipped_row_count": cursor_skipped_row_count,
        "duration_ms": elapsed_ms,
        "begin_at": start_time.isoformat(),
    }

    if audit_path:
        from pathlib import Path
        append_audit(
            Path(audit_path),
            action="edge_weight_feedback_run",
            status=summary["status"],
            target=str(index_path),
            details={k: v for k, v in summary.items() if k != "begin_at"},
        )

    return summary
