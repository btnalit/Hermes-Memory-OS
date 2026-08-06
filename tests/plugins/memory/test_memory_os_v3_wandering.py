from __future__ import annotations

import json

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.v3_wandering import (
    collect_seed_inputs_from_store,
    run_v3_wandering_cycle,
)
from plugins.memory.memory_os.wandering_journal import read_journal


def _store(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="default"))
    store.initialize()
    return store


def _seed():
    return {
        "ref": "crystallized:cry_a",
        "kind": "stable_memory",
        "bounded_text": "A stable memory",
        "epistemic_status": "approved",
        "salience_reasons": ["co_selected"],
    }


class FakeAdapter:
    capability = True

    def __init__(self, payload):
        self.payload = payload
        self.called = 0

    def infer(self, *, packet, prompt_contract, route_snapshot):
        self.called += 1
        return {
            "status": "ok",
            "structured_output": self.payload,
            "requested_provider": route_snapshot["provider"],
            "requested_model": route_snapshot["model"],
            "actual_provider": route_snapshot["provider"],
            "actual_model": route_snapshot["model"],
            "fallback_used": False,
            "model_input_transmitted": True,
            "owner_delivery_attempted": False,
            "external_action_executed": False,
            "tools_enabled": False,
        }


def _run(store, adapter, **overrides):
    values = {
        "adapter": adapter,
        "route_snapshot": {"provider": "openai-codex", "model": "gpt-test"},
        "seed_candidates": [_seed()],
        "edges": [],
        "quiet_gate": {"quiet": True, "reason": "off_peak"},
        "ttl_days": 3,
        "max_entry_chars": 300,
        "max_lineage_hops": 2,
        "model_input_char_budget": 2000,
    }
    values.update(overrides)
    return run_v3_wandering_cycle(store, **values)


def test_missing_ephemeral_capability_fails_closed_before_manifest(tmp_path):
    store = _store(tmp_path)

    class MissingAdapter:
        capability = False

    result = _run(store, MissingAdapter())
    assert result["status"] == "capability_unavailable"
    assert read_journal(store) == []
    assert not (store.roots.memory_os_root / "system" / "v3_body_packet_manifests.jsonl").exists()


def test_empty_entries_is_success_and_removes_manifest(tmp_path):
    store = _store(tmp_path)
    adapter = FakeAdapter({"entries": []})
    result = _run(store, adapter)
    assert result["status"] == "healthy_no_sample"
    assert result["reason"] == "empty_entries"
    assert adapter.called == 1
    assert read_journal(store) == []
    manifest = store.roots.memory_os_root / "system" / "v3_body_packet_manifests.jsonl"
    assert not manifest.exists() or not manifest.read_text(encoding="utf-8").strip()


def test_private_wandering_ingests_valid_entry_without_delivery_or_tools(tmp_path):
    store = _store(tmp_path)
    adapter = FakeAdapter(
        {
            "entries": [
                {
                    "tier": "association",
                    "content": "A quiet association.",
                    "provenance_refs": ["crystallized:cry_a"],
                    "concept_key": "quiet-association",
                    "requested_fate": "hold",
                }
            ]
        }
    )
    result = _run(store, adapter)
    assert result["status"] == "ingested"
    assert result["entry_count"] == 1
    assert result["owner_delivery_attempted"] is False
    assert result["external_action_executed"] is False
    assert len([item for item in read_journal(store) if item.get("record_type") == "thought"]) == 1


def test_schema_or_route_poison_rejects_whole_batch(tmp_path):
    store = _store(tmp_path)
    malformed = FakeAdapter({"entries": [{"tier": "fact"}]})
    result = _run(store, malformed)
    assert result["status"] == "schema_rejected"
    assert read_journal(store) == []

    class DriftAdapter(FakeAdapter):
        def infer(self, *, packet, prompt_contract, route_snapshot):
            result = super().infer(packet=packet, prompt_contract=prompt_contract, route_snapshot=route_snapshot)
            result["actual_model"] = "unexpected"
            return result

    result = _run(store, DriftAdapter({"entries": []}))
    assert result["status"] == "route_drift"
    assert read_journal(store) == []


def test_quiet_gate_skip_never_calls_adapter_or_catches_up(tmp_path):
    store = _store(tmp_path)
    adapter = FakeAdapter({"entries": []})
    result = _run(store, adapter, quiet_gate={"quiet": False, "reason": "foreground_task"})
    assert result == {"status": "skipped", "reason": "foreground_task"}
    assert adapter.called == 0


def _write_daily_rows(store, rows):
    daily_path = store.roots.memory_os_root / "system" / "v3_seed_edges_daily.jsonl"
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_collect_seed_inputs_uses_latest_natural_cron_row_not_later_manual_row(tmp_path):
    """Counterfactual (P1 #7): once the 30-day activation gate is open, a
    LATER valid manual row must not become the seed source for real wandering
    — the same trigger-provenance rule as the activation snapshot gate
    (BB.6-2/BC.2), applied at the seed-selection layer below it."""
    store = _store(tmp_path)
    store.append_crystallized_record("seeds.md", {"id": "cry_nat_a"}, "Natural seed A")
    store.append_crystallized_record("seeds.md", {"id": "cry_nat_b"}, "Natural seed B")
    store.append_crystallized_record("seeds.md", {"id": "cry_man_a"}, "Manual seed A")
    store.append_crystallized_record("seeds.md", {"id": "cry_man_b"}, "Manual seed B")
    natural_row = {
        "valid": True,
        "trigger_class": "natural_cron",
        "created_at": "2026-07-16T02:00:00Z",
        "edges": [{"from": "crystallized:cry_nat_a", "to": "crystallized:cry_nat_b"}],
        "source_window": {"start": "2026-07-15T00:00:00Z", "end": "2026-07-16T00:00:00Z"},
        "source_offset_start": 10,
        "source_offset_end": 20,
    }
    manual_row = {
        "valid": True,
        "trigger_class": "manual",
        "created_at": "2026-07-17T09:00:00Z",
        "edges": [{"from": "crystallized:cry_man_a", "to": "crystallized:cry_man_b"}],
        "source_window": {"start": "2026-07-16T00:00:00Z", "end": "2026-07-17T00:00:00Z"},
        "source_offset_start": 20,
        "source_offset_end": 30,
    }
    _write_daily_rows(store, [natural_row, manual_row])

    seeds, edges, window, cursors = collect_seed_inputs_from_store(store)

    assert [seed["ref"] for seed in seeds] == [
        "crystallized:cry_nat_a", "crystallized:cry_nat_b",
    ]
    assert edges == natural_row["edges"]
    assert window == {"start": "2026-07-15T00:00:00Z", "end": "2026-07-16T00:00:00Z"}
    assert cursors == {"memory_sources": {"offset_start": 10, "offset_end": 20}}


def test_collect_seed_inputs_manual_or_legacy_only_rows_yield_no_seed_inputs(tmp_path):
    """Counterfactual (P1 #7, empty path): a daily file containing only valid
    manual and legacy (pre-trigger_class) rows must never feed wandering —
    resolvable crystallized targets notwithstanding."""
    store = _store(tmp_path)
    store.append_crystallized_record("seeds.md", {"id": "cry_man_a"}, "Manual seed A")
    manual_row = {
        "valid": True,
        "trigger_class": "manual",
        "created_at": "2026-07-17T09:00:00Z",
        "edges": [{"from": "crystallized:cry_man_a", "to": "crystallized:cry_man_a"}],
        "source_window": {"start": "2026-07-16T00:00:00Z", "end": "2026-07-17T00:00:00Z"},
        "source_offset_start": 20,
        "source_offset_end": 30,
    }
    legacy_row = {
        # No trigger_class field: rows written before the field existed must
        # be excluded too (same rule as the activation snapshot gate).
        "valid": True,
        "created_at": "2026-07-17T10:00:00Z",
        "edges": [{"from": "crystallized:cry_man_a", "to": "crystallized:cry_man_a"}],
        "source_window": {"start": "2026-07-16T00:00:00Z", "end": "2026-07-17T00:00:00Z"},
        "source_offset_start": 30,
        "source_offset_end": 40,
    }
    _write_daily_rows(store, [manual_row, legacy_row])

    assert collect_seed_inputs_from_store(store) == ([], [], {}, {})


# ═══════════════════════════════════════════════════════════════════════════
# W8 (S4/S5) — quiet gate 前台判定:耐久台账 + fail-closed + 有界年龄
# ═══════════════════════════════════════════════════════════════════════════
#
# evaluate_v3_quiet_gate 此前零测试覆盖 — S4(读 30 分钟陈旧派生缓存)与
# S5(读取失败 fail-open 放行漫游)能存活至生产的直接原因。生产实测
# wandering_enabled=true、六 knob 齐全,唯一拦截是 activation_evidence_ready
# (自动计算值)— 本组测试是该门的第一道防线。


def _w8_gate_config(now):
    return {
        "wandering_enabled": True,
        "wandering_max_attempts_per_window": 1,
        "wandering_attempt_window_seconds": 86400,
        "wandering_model_input_char_budget": 6000,
        "journal_ttl_days": 3,
        "journal_max_entry_chars": 1200,
        "journal_max_lineage_hops": 2,
        "wandering_quiet_hours_utc": [now.hour],
    }


def _w8_ready_evidence(store):
    path = store.roots.memory_os_root / "system" / "v3_seed_evidence_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"activation_evidence_ready": True}), encoding="utf-8")


def _w8_anchor_row(store, *, created_at, status="active"):
    from plugins.memory.memory_os.task_state import active_task_anchor_path

    path = active_task_anchor_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema_version": "memory-os.active_task_anchor.v0",
        "profile": "default",
        "status": status,
        "anchor": "### Memory-OS Current Task Anchor\n- current task: W8 测试前台任务",
        "created_at": created_at,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_w8_active_anchor_blocks_wandering(tmp_path):
    """S4 counterfactual:主人在忙(耐久台账 active 锚点)必须挡住漫游。

    旧实现读 state_overlay 缓存 — 缓存不存在/陈旧为空时误判'不忙'。
    无修复:本场景(台账 active、无缓存)返回 quiet=True → 必红。
    """
    from datetime import datetime, timezone

    from plugins.memory.memory_os.v3_wandering import evaluate_v3_quiet_gate

    store = _store(tmp_path)
    _w8_ready_evidence(store)
    now = datetime.now(timezone.utc)
    _w8_anchor_row(store, created_at=now.isoformat().replace("+00:00", "Z"))

    gate = evaluate_v3_quiet_gate(store, _w8_gate_config(now), now=now)
    assert gate == {"quiet": False, "reason": "foreground_task"}, gate


def test_w8_stale_overlay_cache_is_not_consulted(tmp_path):
    """S4 counterfactual(反向):台账无任务时,陈旧缓存里的旧 active 不得再挡漫游。

    旧实现读缓存 → 本场景(缓存有旧任务、台账无)返回 foreground_task → 必红。
    """
    from datetime import datetime, timezone

    from plugins.memory.memory_os.v3_wandering import evaluate_v3_quiet_gate

    store = _store(tmp_path)
    _w8_ready_evidence(store)
    now = datetime.now(timezone.utc)
    overlay_path = store.roots.memory_os_root / "system" / "state_overlay" / "current.json"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text(json.dumps({
        "active_projects": {"status": "ok", "data": [{"text": "三小时前的旧任务"}]},
    }), encoding="utf-8")

    gate = evaluate_v3_quiet_gate(store, _w8_gate_config(now), now=now)
    assert gate == {"quiet": True, "reason": "off_peak"}, (
        f"stale derived cache must no longer drive the foreground check: {gate}"
    )


def test_w8_zombie_anchor_beyond_max_age_does_not_block(tmp_path):
    """有界年龄守卫:崩溃残留的超龄 active 锚点不得永久压制漫游(反向失效)。"""
    from datetime import datetime, timedelta, timezone

    from plugins.memory.memory_os.v3_wandering import (
        WANDERING_FOREGROUND_ANCHOR_MAX_AGE_HOURS,
        evaluate_v3_quiet_gate,
    )

    store = _store(tmp_path)
    _w8_ready_evidence(store)
    now = datetime.now(timezone.utc)
    stale = now - timedelta(hours=WANDERING_FOREGROUND_ANCHOR_MAX_AGE_HOURS + 1)
    _w8_anchor_row(store, created_at=stale.isoformat().replace("+00:00", "Z"))

    gate = evaluate_v3_quiet_gate(store, _w8_gate_config(now), now=now)
    assert gate == {"quiet": True, "reason": "off_peak"}, gate


def test_w8_unreadable_ledger_fails_closed(tmp_path):
    """S5 counterfactual:台账不可读必须判'在忙'(fail-closed)。

    管自主表达的门在读取失败时放行 — 旧实现 except → overlay={} →
    active_projects=[] → 继续走到 quiet=True → 必红。
    """
    from datetime import datetime, timezone

    from plugins.memory.memory_os.task_state import active_task_anchor_path
    from plugins.memory.memory_os.v3_wandering import evaluate_v3_quiet_gate

    store = _store(tmp_path)
    _w8_ready_evidence(store)
    now = datetime.now(timezone.utc)
    # 台账路径被目录占据 → read_text 必抛 OSError 族
    ledger = active_task_anchor_path(store.roots)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.mkdir()

    gate = evaluate_v3_quiet_gate(store, _w8_gate_config(now), now=now)
    assert gate == {"quiet": False, "reason": "task_state_unreadable"}, gate
