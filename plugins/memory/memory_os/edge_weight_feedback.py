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
  - **孤儿边级联作废(G0)**:active 边的结晶端点若已离开 active 结晶集
    (过期 provisional / discard / demote / revoke / superseded ——
    ``crystallized.INACTIVE_CANONICAL_STATES``)→ invalidated,原因码
    ``endpoint_inactive``,每轮上限 ``ORPHAN_CASCADE_MAX_PER_RUN``。与
    遗忘机制独立(不看命中信号,不受 first_injection_at 门控)——生产实测
    96%(main)/82%(sannai)的结晶↔结晶边指向已失效端点且从未被作废。
  - **shadow 账本体积治理(G0)**:``graph_layer_shadow.jsonl`` 无界增长
    (生产实测约 15MB,过去只有"未来再压缩"的注释)——本步骤末尾用
    ``jsonl_io.compact_jsonl_tail`` 做 size-gated 压缩(先归档再丢弃,
    见 GRAPH_LAYER_SHADOW_KEEP_RECORDS/_COMPACT_MIN_BYTES),置于 cursor
    状态持久化**之后**,使一次压缩事件只可能影响下一轮(该游标的错位
    检测机制本就是为这个场景准备的)。

Durable state: ``system/edge_weight_feedback_state.json``
(processed_line_count cursor + per-edge last_hit + first_run_at +
first_injection_at)。Completion Is Not Output: closed outcome +
production counters(含 already_saturated / skipped_not_injected /
invalidated_never_hit / forget_eligible_backlog / orphan_scanned /
orphan_invalidated / orphan_skipped_by_cap / shadow_compaction_reason)。

Runs as a cognitive-loop step.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from .audit import append_audit
from .crystallized import INACTIVE_CANONICAL_STATES, CrystallizedMemoryService
from .jsonl_io import build_error_record, compact_jsonl_tail
from .store import MemoryOSStore
from .state_overlay import _atomic_write_json

# 乘性强化:w += RATE × (1 − w)。1.0 是不可达渐近线 — 高分区并列消失
# (排序始终有区分度),且 weight==1.0 从此可判定为未迁移遗留行。出生
# 0.55 起 5 次命中 ≈0.76、10 次 ≈0.86、20 次 ≈0.96。旧版加性 +0.05 在
# 全 1.0 出生权重下永远抬不动任何边(P3)。
HIT_LEARNING_RATE = 0.12
FORGET_AFTER_DAYS = 60
FORGET_MAX_PER_RUN = 50
STATE_FILENAME = "edge_weight_feedback_state.json"

# G0 orphan-edge cascade: an active edge whose crystallized endpoint is no
# longer in the active crystallized set (expired provisional / discarded /
# demoted / revoked / superseded — see crystallized.INACTIVE_CANONICAL_STATES)
# is dead weight the forgetting lane above never catches, because forgetting
# only fires on 60-day hit-idleness, not on endpoint liveness. Measured on
# production: 96% (main) / 82% (sannai) of crystallized<->crystallized edges
# point at an inactive endpoint and are never invalidated. Bounded per run
# like the forgetting lane above (own cap — a different mechanism, not the
# same backlog). Event endpoints are out of scope: only endpoints typed
# "crystallized_record" are checked for liveness.
ORPHAN_CASCADE_MAX_PER_RUN = 200
ORPHAN_CASCADE_INVALIDATION_REASON = "endpoint_inactive"

# G0 shadow-ledger size bound: system/graph_layer_shadow.jsonl had no bound
# at all (measured ~15MB on production, code only said "future compaction").
# Compaction runs here — the same offline lifecycle step that already reads
# this ledger via a line-count cursor with built-in misalignment detection
# (see the "Cursor alignment check" section below), so a compaction event is
# not a new failure mode for that reader, it is the scenario the cursor
# fingerprint check was already built to survive. keep_records must stay
# >= every known reader's tail window: the 3.200 monitor's
# graph_injection_shadow_state() reads rows[-2000:] over a 7-day cutoff, and
# prefetch.graph_layer_shadow_novelty_summary() defaults to max_records=2000.
GRAPH_LAYER_SHADOW_KEEP_RECORDS = 5000
GRAPH_LAYER_SHADOW_COMPACT_MIN_BYTES = 1_048_576


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


def _canonical_crystallized_states(roots: Any) -> tuple[dict[str, str], str]:
    """Map every crystallized record id in the canonical files to its canonical_state.

    Returns ``(states, skip_reason)``. A non-empty ``skip_reason`` means the
    canonical view cannot be trusted this run, so no edge may be judged an
    orphan: no crystallized files at all, or a non-empty file that parses to
    zero records (its ids would otherwise all read as "absent"). State changes
    rewrite a record in place, so an id appears once; should it ever appear
    twice, any active occurrence wins — ambiguity never invalidates.
    """
    crystallized_root = roots.crystallized_root
    if not crystallized_root.exists():
        return {}, "canonical_empty"
    service = CrystallizedMemoryService(MemoryOSStore(roots))
    states: dict[str, str] = {}
    for path in sorted(crystallized_root.glob("*.md")):
        records = service.read_records(path.name)
        if not records and path.read_text(encoding="utf-8").strip():
            return {}, "canonical_unparseable_file"
        for record in records:
            record_id = str(record.frontmatter.get("id") or "").strip()
            if not record_id:
                continue
            state = str(record.frontmatter.get("canonical_state") or "active").strip().lower()
            if states.get(record_id, "") not in INACTIVE_CANONICAL_STATES and record_id in states:
                continue  # an active occurrence already recorded wins
            states[record_id] = state
    if not states:
        return {}, "canonical_empty"
    return states, ""


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
    orphan_scanned = 0
    orphan_invalidated = 0
    orphan_skipped_by_cap = 0
    # Closed set: "" | canonical_empty | canonical_unparseable_file | canonical_read_failed
    orphan_cascade_skipped_reason = ""
    orphan_cascade_error_records: list[dict[str, Any]] = []

    shadow_exists = shadow_path.exists()
    lines: list[str] = []
    if shadow_exists:
        try:
            raw_text = shadow_path.read_text(encoding="utf-8")
        except OSError:
            raw_text = ""
        lines = raw_text.splitlines()
        # The per-turn prefetch writer (_record_graph_layer_shadow ->
        # jsonl_io.append_jsonl_locked) appends one full line + "\n" in a
        # single handle.write() under a sidecar lock, so every DURABLE
        # ledger line always ends with "\n". This reader takes no lock on
        # the hot ledger, so it can race a write in progress and observe a
        # torn (partially-written) last line with no trailing newline.
        # Treat only newline-terminated lines as durable: drop a
        # non-terminated tail element before it is counted, sliced, or
        # fingerprinted. A partial line is simply invisible to this run and
        # will be consumed next run once the writer finishes it -- this is
        # what keeps the fingerprint always computed over a complete line
        # and prevents a torn read from producing a false
        # `ledger_fingerprint_mismatch` next run.
        if raw_text and not raw_text.endswith("\n"):
            lines = lines[:-1]

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
        if cursor_misalignment_reason == "ledger_shorter_than_cursor":
            # Best-effort, count-based lower bound on how many
            # previously-tracked ledger positions vanished out from under
            # the cursor. It is a bound, not a claim about how many real
            # injection hits were lost — some or all of that gap may have
            # already been reinforced in a prior run.
            cursor_skipped_row_count = max(0, processed - len(lines))
        else:
            # "ledger_fingerprint_mismatch": the ledger is same-or-larger
            # than the old cursor but its content diverged (a
            # compaction+append that coincidentally lands the new length at
            # or past the old cursor value). `new_lines` above was dropped
            # in full, so the unconsumed forward backlog is everything from
            # `len(lines) - processed` onward. This is also only a bound,
            # not an exact count: how much of the renumbered prefix
            # (positions [0, processed)) was truly already-consumed content
            # versus newly-shifted content is unknowable from a line count
            # alone.
            cursor_skipped_row_count = max(0, len(lines) - processed)
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

        # ── 3. Cascade-invalidate active edges with an inactive
        # crystallized endpoint ("orphan" edges, G0) ────────────────────
        # Independent of the injection/hit signal above — runs regardless
        # of first_injection_at, because this is a correctness sweep for
        # edges whose crystallized_record endpoint left the active
        # crystallized set (expired provisional / discarded / demoted /
        # revoked / superseded — crystallized.INACTIVE_CANONICAL_STATES),
        # not a usage-based forgetting decision. An endpoint id absent from
        # crystallized_records means a full rebuild already dropped it
        # (_index_crystallized_records skips inactive frontmatter entirely
        # — the dominant production shape); an endpoint id present with a
        # canonical_state in INACTIVE_CANONICAL_STATES means it was
        # demoted/revoked incrementally (update_canonical_state_in_index)
        # since the last rebuild. Events are out of scope — only
        # from/to_record_type == "crystallized_record" is checked.
        try:
            orphan_candidates = conn.execute(
                "select edge_id, from_record_type, from_record_id,"
                " to_record_type, to_record_id from memory_edges"
                " where state = 'active'"
                " and (from_record_type = 'crystallized_record'"
                "      or to_record_type = 'crystallized_record')",
            ).fetchall()
        except sqlite3.Error:
            orphan_candidates = []
        orphan_scanned = len(orphan_candidates)

        referenced_ids: set[str] = set()
        for row in orphan_candidates:
            if str(row["from_record_type"]) == "crystallized_record":
                referenced_ids.add(str(row["from_record_id"]))
            if str(row["to_record_type"]) == "crystallized_record":
                referenced_ids.add(str(row["to_record_id"]))

        # Liveness comes from the canonical crystallized files, never from the
        # rebuildable index: an empty, mid-rebuild or erroring index would
        # read every endpoint as "absent" and invalidate the whole graph
        # through canonical writes. An untrustworthy canonical view skips
        # the cascade for this run (fail-closed) and says why.
        crystallized_state_by_id: dict[str, str] = {}
        if referenced_ids:
            try:
                crystallized_state_by_id, orphan_cascade_skipped_reason = _canonical_crystallized_states(roots)
            except Exception as exc:  # canonical read must never half-succeed silently
                orphan_cascade_skipped_reason = "canonical_read_failed"
                orphan_cascade_error_records.append(
                    build_error_record(
                        component="edge_weight_feedback",
                        operation="orphan_cascade_canonical_read",
                        error_code="canonical_read_failed",
                        severity="warning",
                        recoverable=True,
                        details={"error_type": type(exc).__name__},
                    )
                )

        def _endpoint_is_orphaned(record_type: str, record_id: str) -> bool:
            if record_type != "crystallized_record":
                return False
            state_value = crystallized_state_by_id.get(record_id)
            if state_value is None:
                # Absent from the canonical files: the record was removed
                # (edge birth requires a real record), so the edge is an orphan.
                return True
            return state_value in INACTIVE_CANONICAL_STATES

        orphan_eligible = 0
        if orphan_cascade_skipped_reason:
            orphan_candidates = []
        for row in orphan_candidates:
            edge_id = str(row["edge_id"])
            is_orphan = (
                _endpoint_is_orphaned(str(row["from_record_type"]), str(row["from_record_id"]))
                or _endpoint_is_orphaned(str(row["to_record_type"]), str(row["to_record_id"]))
            )
            if not is_orphan:
                continue
            # 全量计数 eligible(积压可见性),cap 只限制本轮处决数 — 同
            # forgetting 步骤的 forget_eligible 模式。
            orphan_eligible += 1
            if orphan_invalidated >= ORPHAN_CASCADE_MAX_PER_RUN:
                continue
            result = transition_edge_state(
                conn, edge_id, "invalidated", roots=roots,
                reason=ORPHAN_CASCADE_INVALIDATION_REASON,
            )
            if result and result.get("state") == "invalidated":
                orphan_invalidated += 1
                last_hit.pop(edge_id, None)
            else:
                failed += 1
        orphan_skipped_by_cap = max(0, orphan_eligible - orphan_invalidated)
    finally:
        conn.close()

    # ── 4. Persist cursor + hit watermarks (durable state) ──────────────
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

    # ── 5. Producer-side size-gated compaction of the shadow ledger (G0) ─
    # Deliberately AFTER the cursor/state persist above: this run's cursor
    # was computed from the PRE-compaction `lines` (read earlier, unaffected
    # by a later on-disk rewrite), so ordering it after the persist means a
    # crash between the two steps just leaves compaction un-run — never a
    # cursor pointed past a file that no longer exists. A FOLLOWING run
    # observing the shorter, compacted file is exactly the scenario the
    # cursor-alignment check above was already built to survive ("future
    # graph_layer_shadow.jsonl compaction" in its own comments) — it
    # realigns and reports the gap rather than reprocessing from zero.
    # compact_jsonl_tail refuses (no-op, reason="malformed_lines_present")
    # if the ledger contains any line this reader could not parse — never
    # silently deletes what cannot be reconstructed.
    shadow_compaction: dict[str, Any] = {
        "reason": "no_file", "records_kept": 0, "records_archived": 0,
        "error_records": [],
    }
    if shadow_exists:
        shadow_compaction = compact_jsonl_tail(
            shadow_path,
            keep_records=GRAPH_LAYER_SHADOW_KEEP_RECORDS,
            min_bytes=GRAPH_LAYER_SHADOW_COMPACT_MIN_BYTES,
            archive_path=shadow_path.with_name(f"{shadow_path.stem}.archive.jsonl"),
            component="edge_weight_feedback",
            operation="graph_layer_shadow_compaction",
        )

    if reinforced or forgotten or already_saturated or orphan_invalidated:
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
        "status": "ok" if not (
            failed and not reinforced and not forgotten and not orphan_invalidated
        ) else "error",
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
        # G0 orphan-edge cascade counters (Completion Is Not Output: a lane
        # that scans and finds nothing must say so through a real 0, not by
        # omitting the keys).
        "orphan_scanned_count": orphan_scanned,
        "orphan_invalidated_count": orphan_invalidated,
        "orphan_skipped_by_cap_count": orphan_skipped_by_cap,
        "orphan_cascade_skipped_reason": orphan_cascade_skipped_reason,
        "orphan_cascade_error_records": orphan_cascade_error_records,
        # G0 shadow-ledger compaction (closed reason set — see
        # jsonl_io.COMPACT_JSONL_TAIL_REASONS).
        "shadow_compaction_reason": shadow_compaction["reason"],
        "shadow_compaction_records_archived": shadow_compaction["records_archived"],
        "shadow_compaction_suppressed_error_count": len(shadow_compaction.get("error_records") or []),
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
