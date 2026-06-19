"""Tests for crystallized expiry cliff and provisional decay governance.

Covers D.1-D.10 from hermes-crystallized-expiry-cliff-and-provisional-decay-spec.md.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


# ═══════════════════════════════════════════════════════════════════
# P3: parser fail-loud (D.10)
# ═══════════════════════════════════════════════════════════════════

def test_unparseable_file_produces_error_record(tmp_path):
    """D.10: Non-empty file yielding 0 records → audit crystallized_file_unparseable."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    # Write a .md file without valid frontmatter
    bad_path = store.roots.crystallized_root / "bad.md"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("this is not valid markdown\nno frontmatter here\n", encoding="utf-8")

    # read_records should return empty list and not raise
    records = service.read_records("bad.md")
    assert records == []

    # Audit should contain crystallized_file_unparseable
    audit_path = store.roots.audit_path
    assert audit_path.exists()
    audit_lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    unparseable_events = [
        json.loads(line)
        for line in audit_lines
        if json.loads(line).get("action") == "crystallized_file_unparseable"
    ]
    assert len(unparseable_events) == 1
    assert unparseable_events[0]["details"]["file_name"] == "bad.md"
    assert unparseable_events[0]["status"] == "warning"


# ═══════════════════════════════════════════════════════════════════
# P1: expiry cliff guard (D.1-D.5)
# ═══════════════════════════════════════════════════════════════════

from plugins.modules.governance.provisional_sweep import find_expiring_provisional


def test_find_expiring_provisional_filters_48h(tmp_path):
    """D.1: 48h 内过期的 active provisional 被找出，按 expires_at 升序."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = datetime.now(timezone.utc)

    # 造 3 条: 24h 过期、47h 过期、49h 过期
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    def _write_provisional(seed, hours_to_expiry):
        c = CrystallizedCandidate(
            candidate_id=f"cand_exp_{seed}",
            kind="moment",
            body=f"test body {seed}",
            bridge_state="resolver_approved",
            sensitivity="private",
            source_event_ids=["ev_sweep_test"],
            created_at=(now - timedelta(days=6)).isoformat(),
        )
        d = ApprovalDecision(
            candidate_id=c.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=now.isoformat(),
            note="test",
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(hours=hours_to_expiry)).isoformat(),
            recurrence=0,
        )
        service.write_approved_record(c, d, file_name="owner_approved.md", now=now)

    _write_provisional(1, 24)   # 24h 内过期
    _write_provisional(2, 47)   # 47h 内过期
    _write_provisional(3, 49)   # 超出 48h

    result = find_expiring_provisional(store, within_hours=48)

    assert len(result) == 2
    assert result[0]["hours_remaining"] <= result[1]["hours_remaining"]
    # 49h 的不可出现
    ids = {r.get("candidate_id") for r in result}
    assert "cand_exp_3" not in ids


def test_expiring_section_in_digest(tmp_path):
    """D.2: 临近过期 → digest 区段出现，带 confirm/let_expire token."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = datetime.now(timezone.utc)

    from plugins.memory.memory_os.crystallized import CrystallizedCandidate
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    c = CrystallizedCandidate(
        candidate_id="cand_d2",
        kind="preference",
        body="用户偏好:使用暗色主题编辑代码",
        bridge_state="resolver_approved",
        sensitivity="private",
        source_event_ids=["ev_sweep_test"],
        created_at=(now - timedelta(days=6)).isoformat(),
    )
    d = ApprovalDecision(
        candidate_id=c.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=now.isoformat(),
        note="test",
        source_state="resolver_approved",
        provisional=True,
        expires_at=(now + timedelta(hours=24)).isoformat(),
        recurrence=0,
    )
    service.write_approved_record(c, d, file_name="owner_approved.md", now=now)

    # 写临时文件供 digest 读取
    from plugins.modules.governance.provisional_sweep import _expiring_list_path as _sweep_expiring_path
    near = find_expiring_provisional(store, within_hours=48)
    p = _sweep_expiring_path(store)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(near, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    # 调 digest 区段渲染
    from plugins.memory.memory_os.owner_actions import _render_expiring_provisional_section
    section_text = _render_expiring_provisional_section(store)

    assert "即将过期" in section_text
    assert "oa_confirm_" in section_text
    assert "oa_let_expire_" in section_text
    assert "24h" in section_text or "剩" in section_text


def test_owner_confirm_makes_permanent(tmp_path):
    """D.3: owner confirm → provisional=False + expires_at 清空（核心逃生路）."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = datetime.now(timezone.utc)

    from plugins.memory.memory_os.crystallized import CrystallizedCandidate
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    c = CrystallizedCandidate(
        candidate_id="cand_d3",
        kind="rule",
        body="项目默认使用 Python 3.11+",
        bridge_state="resolver_approved",
        sensitivity="private",
        source_event_ids=["ev_sweep_test"],
        created_at=(now - timedelta(days=5)).isoformat(),
    )
    d = ApprovalDecision(
        candidate_id=c.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=now.isoformat(),
        note="test",
        source_state="resolver_approved",
        provisional=True,
        expires_at=(now + timedelta(hours=24)).isoformat(),
        recurrence=0,
    )
    service.write_approved_record(c, d, file_name="owner_approved.md", now=now)

    # 找到刚写入的 record_id
    prov_records = service.list_provisional_records()
    assert len(prov_records) == 1
    record_id = prov_records[0]["id"]

    # 执行 confirm
    result = service.confirm_provisional_record(
        record_id,
        confirmed_by="owner",
        now=now,
    )
    assert result["canonical_state_changed"] is True

    # 读回确认已是 permanent
    all_records = service.read_records(result["file_name"])
    confirmed = [
        r for r in all_records
        if r.frontmatter.get("id") == record_id
    ]
    assert len(confirmed) == 1
    fm = confirmed[0].frontmatter
    assert fm.get("provisional") is False
    assert fm.get("expires_at") == ""
    assert fm.get("confirmed_by") == "owner"
    assert fm.get("confirmed_at")


def test_expired_provisional_invalidated(tmp_path):
    """D.4: owner 不动 → 到期 sweep 照常 invalidate（provisional_expired）."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = datetime.now(timezone.utc)

    from plugins.memory.memory_os.crystallized import CrystallizedCandidate
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    c = CrystallizedCandidate(
        candidate_id="cand_d4",
        kind="moment",
        body="expired test body",
        bridge_state="resolver_approved",
        sensitivity="private",
        source_event_ids=["ev_sweep_test"],
        created_at=(now - timedelta(days=8)).isoformat(),
    )
    d = ApprovalDecision(
        candidate_id=c.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=(now - timedelta(days=7)).isoformat(),
        note="test",
        source_state="resolver_approved",
        provisional=True,
        expires_at=(now - timedelta(hours=1)).isoformat(),  # 已过期
        recurrence=0,
    )
    service.write_approved_record(c, d, file_name="owner_approved.md", now=now)

    # 跑 sweep
    from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule
    sweep = ProvisionalSweepModule(store.roots.hermes_home, profile="memoryos-test")
    result = sweep.run_once(store=store)
    assert result["expired_count"] >= 1

    # 确认记录仍存在但 canonical_state 已变
    prov_records = service.list_provisional_records()
    assert len(prov_records) == 0  # 不再是 active

    # 文件仍存在
    md_files = list(store.roots.crystallized_root.glob("*.md"))
    assert len(md_files) >= 1


def test_thundering_herd_top_n(tmp_path):
    """D.5: 惊群防护——一次只推 top-N，其余下次."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = datetime.now(timezone.utc)

    from plugins.memory.memory_os.crystallized import CrystallizedCandidate
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    # 造 12 条临近过期
    for i in range(12):
        c = CrystallizedCandidate(
            candidate_id=f"cand_herd_{i}",
            kind="moment",
            body=f"herd body {i}",
            bridge_state="resolver_approved",
            sensitivity="private",
            source_event_ids=["ev_sweep_test"],
            created_at=(now - timedelta(days=6)).isoformat(),
        )
        d = ApprovalDecision(
            candidate_id=c.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=now.isoformat(),
            note="test",
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(hours=12)).isoformat(),
            recurrence=0,
        )
        service.write_approved_record(c, d, file_name="owner_approved.md", now=now)

    near = find_expiring_provisional(store, within_hours=48)
    assert len(near) == 12

    # 模拟 digest top-N（默认 10）
    from plugins.memory.memory_os.knob_overrides import resolve_knob
    max_n = resolve_knob("max_expiring_in_digest", default=10)
    top_n = near[:max_n]
    assert len(top_n) == 10
    assert len(near) > len(top_n)  # 2 条留给下次


# ═══════════════════════════════════════════════════════════════════
# P2: recurrence bump + dedup (D.6-D.9)
# ═══════════════════════════════════════════════════════════════════

from plugins.modules.governance.candidate_aggregation import _match_existing_provisional


def test_bump_recurrence_on_match(tmp_path):
    """D.6: durable 撞已有 provisional → bump recurrence+1 + expires_at 续期，不新建."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = datetime.now(timezone.utc)

    from plugins.memory.memory_os.crystallized import CrystallizedCandidate
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    # 先建一条已有 provisional
    body = "用户反复提及的数据: PostgreSQL 是首选数据库"
    c = CrystallizedCandidate(
        candidate_id="cand_existing",
        kind="preference",
        body=body,
        bridge_state="resolver_approved",
        sensitivity="private",
        source_event_ids=[],
        created_at=(now - timedelta(days=3)).isoformat(),
    )
    d = ApprovalDecision(
        candidate_id=c.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=now.isoformat(),
        note="test",
        source_state="resolver_approved",
        provisional=True,
        expires_at=(now + timedelta(days=1)).isoformat(),
        recurrence=0,
    )
    service.write_approved_record(c, d, file_name="owner_approved.md", now=now)

    # 找到已有 record
    existing = service.list_provisional_records()
    assert len(existing) == 1
    original_expires = existing[0]["expires_at"]
    existing_id = existing[0]["id"]

    # FTS5 匹配
    match_id = _match_existing_provisional(store, body)
    assert match_id is not None

    # bump
    result = service.bump_recurrence_and_renew(match_id, max_renewals=10, now=now)
    assert result["renewed"] is True
    assert result["current_recurrence"] == 1

    # 验证 expires_at 被续期
    updated = service.list_provisional_records()
    assert len(updated) == 1
    new_expires = updated[0]["expires_at"]
    assert new_expires != original_expires

    # 验证 recurrence 已更新
    records = service.read_records("owner_approved.md")
    bumped = [r for r in records if r.frontmatter.get("id") == existing_id]
    assert len(bumped) == 1
    assert int(bumped[0].frontmatter.get("recurrence", 0)) == 1


def test_new_record_when_no_match(tmp_path):
    """D.7: 未撞 → FTS5 返回 None（现有路径不变）."""
    store = _store(tmp_path)

    match_id = _match_existing_provisional(store, "completely novel content never seen before")
    assert match_id is None


def test_repeated_observation_accumulates_recurrence(tmp_path):
    """D.8: 反复观察 N 次 → recurrence=N，一直不过期."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = datetime.now(timezone.utc)

    from plugins.memory.memory_os.crystallized import CrystallizedCandidate
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    body = "反复出现的事实: 用户使用 VSCode 作为主要编辑器"
    c = CrystallizedCandidate(
        candidate_id="cand_repeat",
        kind="preference",
        body=body,
        bridge_state="resolver_approved",
        sensitivity="private",
        source_event_ids=[],
        created_at=(now - timedelta(days=5)).isoformat(),
    )
    d = ApprovalDecision(
        candidate_id=c.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=now.isoformat(),
        note="test",
        source_state="resolver_approved",
        provisional=True,
        expires_at=(now + timedelta(days=2)).isoformat(),
        recurrence=0,
    )
    service.write_approved_record(c, d, file_name="owner_approved.md", now=now)

    # bump 5 次
    existing = service.list_provisional_records()
    record_id = existing[0]["id"]
    for i in range(5):
        result = service.bump_recurrence_and_renew(record_id, max_renewals=10, now=now)
        assert result["renewed"] is True
        assert result["current_recurrence"] == i + 1

    # 验证 recurrence=5
    records = service.read_records("owner_approved.md")
    bumped = [r for r in records if r.frontmatter.get("id") == record_id]
    assert int(bumped[0].frontmatter.get("recurrence", 0)) == 5
    # 验证未过期（expires_at 被续到未来）
    expires_str = bumped[0].frontmatter.get("expires_at", "")
    assert expires_str
    expires_dt = datetime.fromisoformat(expires_str)
    assert expires_dt > now


def test_max_renewals_requires_owner_decision(tmp_path):
    """D.9: MAX_RENEWALS 后 → requires_owner_decision=True，不续期."""
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = datetime.now(timezone.utc)

    from plugins.memory.memory_os.crystallized import CrystallizedCandidate
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    body = "高频但可能无价值的事实"
    c = CrystallizedCandidate(
        candidate_id="cand_max",
        kind="moment",
        body=body,
        bridge_state="resolver_approved",
        sensitivity="private",
        source_event_ids=[],
        created_at=(now - timedelta(days=10)).isoformat(),
    )
    d = ApprovalDecision(
        candidate_id=c.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=now.isoformat(),
        note="test",
        source_state="resolver_approved",
        provisional=True,
        expires_at=(now + timedelta(hours=12)).isoformat(),
        recurrence=9,  # 已有 9 次
    )
    service.write_approved_record(c, d, file_name="owner_approved.md", now=now)

    existing = service.list_provisional_records()
    record_id = existing[0]["id"]

    # 第 10 次 bump（max_renewals=10）
    result = service.bump_recurrence_and_renew(record_id, max_renewals=10, now=now)
    assert result["renewed"] is True  # 第 10 次本身允许（recurrence 9→10）
    assert result["current_recurrence"] == 10

    # 第 11 次 bump → 拒绝
    result2 = service.bump_recurrence_and_renew(record_id, max_renewals=10, now=now)
    assert result2["renewed"] is False
    assert result2["requires_owner_decision"] is True
    assert result2["current_recurrence"] == 10  # 没有增加
