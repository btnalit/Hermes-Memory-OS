"""Turn author: another agent's turn must never steer the owner's foreground task.

Production 2026-09-22 (main + sannai): three Hermes agents debating in one
Telegram group. Hermes opens a session per sender, and every peer agent's turn
reached this provider as a user turn: 22 of the 33 cancelled anchors written
since 2026-09-10 were peer debate turns, each injected "stop the foreground
task", the agent apologised, the next speaker quoted the apology, and the
quote cancelled again. Peer sessions also recovered the owner's anchor at
initialize, tombstoned it, and marked it completed at session end.

The author comes from Hermes: ``on_turn_start(turn, message, author_id=,
author_name=, author_is_bot=)`` immediately before ``prefetch`` on the same
thread, and ``sync_turn(..., turn_author={"id", "name", "is_bot"})``.
"""
from __future__ import annotations

import json

from plugins.memory import load_memory_provider
from plugins.memory.memory_os import _active_task_anchor_path
from plugins.memory.memory_os.audit import read_audit_entries
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.context_router import plan_context_route
from plugins.memory.memory_os.inner_drive import classify_event_for_inner_drive
from plugins.memory.memory_os.roots import MemoryOSRoots

_OWNER_ID = "1000000001"
_PEER_ID = "2000000002"
_OTHER_HUMAN_ID = "4000000004"
_OWNER_ANCHOR = "### Memory-OS Current Task Anchor\n- current task: 安装 ComfyUI 并配置 IPAdapter 插件"
_APOLOGY = "是我错了，兄弟。我把上一场辩论的“已取消”状态错误地带进了这场 RAG 辩论，误以为当前也要停止。"


def _provider(tmp_path, session_id, *, platform="telegram", **kwargs):
    provider = load_memory_provider("memory_os")
    provider.initialize(
        session_id,
        hermes_home=str(tmp_path),
        platform=platform,
        agent_identity="memoryos-test",
        **kwargs,
    )
    return provider


def _seed_owner_identity(tmp_path, platform, owner_id):
    """Build the fixture via the real producer (config.save_config /
    _merge_principal_config), not a hand-written config.json shortcut."""
    save_config({"principal": {"owner_identities": {platform: [owner_id]}}}, tmp_path)


def _owner_turn(provider, message=""):
    provider.on_turn_start(1, message, author_id=_OWNER_ID, author_name="owner", author_is_bot=False)


def _other_human_turn(provider, message=""):
    provider.on_turn_start(1, message, author_id=_OTHER_HUMAN_ID, author_name="other-human", author_is_bot=False)


def _peer_turn(provider, message=""):
    provider.on_turn_start(1, message, author_id=_PEER_ID, author_name="peer-bot", author_is_bot=True)


def _records(tmp_path):
    path = _active_task_anchor_path(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _audit(provider, action):
    return [entry for entry in read_audit_entries(provider._roots.audit_path) if entry.get("action") == action]


def _seed_owner_anchor(tmp_path):
    owner = _provider(tmp_path, "20260922_owner_dm")
    try:
        _owner_turn(owner)
        owner._current_task_anchor = _OWNER_ANCHOR
        owner._write_active_task_anchor(anchor=_OWNER_ANCHOR)
    finally:
        owner.shutdown()
    assert _records(tmp_path)[-1]["status"] == "active"


def test_peer_agent_cancellation_writes_no_anchor_and_is_audited(tmp_path):
    provider = _provider(tmp_path, "20260913_140133_peer")
    try:
        _peer_turn(provider, "取消这个任务")
        provider.prefetch("取消这个任务", session_id="20260913_140133_peer")
        assert provider._turn_author_class == "bot"
        assert provider._foreground_task_only_prefetch is False
        assert provider._current_task_anchor == ""
        skipped = _audit(provider, "ingress_foreground_control_skipped")
    finally:
        provider.shutdown()
    assert _records(tmp_path) == []
    assert skipped and skipped[-1]["details"]["reason"] == "non_owner_authored_turn"
    assert skipped[-1]["details"]["author_class"] == "bot"


def test_peer_session_lifecycle_never_touches_the_owner_anchor(tmp_path):
    _seed_owner_anchor(tmp_path)
    before = _records(tmp_path)

    peer = _provider(tmp_path, "20260913_140133_peer")
    try:
        _peer_turn(peer, "第一阶段·反方立论")
        # nothing of the owner's task is pulled into the peer's context
        assert peer._current_task_anchor == ""
        context = peer.prefetch(
            f'[Replying to: "{_APOLOGY}"]\n\n第一阶段·反方立论 我方主张：传统RAG已经不适合作为默认方案。',
            session_id="20260913_140133_peer",
        )
        peer.on_pre_compress([{"role": "user", "content": "第一阶段·反方立论 我方主张：传统RAG已经不是默认方案"}])
        peer.on_session_end([{"role": "user", "content": "第一阶段·反方立论"}])
    finally:
        peer.shutdown()

    assert "ComfyUI" not in context
    after = _records(tmp_path)
    assert after == before, "a peer-agent session wrote to the owner's anchor ledger"

    owner_again = _provider(tmp_path, "20260922_owner_dm_2")
    try:
        _owner_turn(owner_again)
        assert "ComfyUI" in owner_again._current_task_anchor
    finally:
        owner_again.shutdown()


def test_owner_quote_reply_cancel_still_cancels_and_records_author(tmp_path):
    provider = _provider(tmp_path, "20260922_owner_group")
    try:
        _owner_turn(provider)
        provider._current_task_anchor = _OWNER_ANCHOR
        query = f'[Replying to your previous message: "{"长篇辩论发言" * 40}"]\n\n先停止吧'
        provider.prefetch(query, session_id="20260922_owner_group")
        assert provider._foreground_task_only_prefetch is True
        recorded = _audit(provider, "active_task_anchor_recorded")
    finally:
        provider.shutdown()
    cancelled = [r for r in _records(tmp_path) if r["status"] == "cancelled"]
    assert len(cancelled) == 1
    # the anchor names the owner's own words, not the quoted speech
    assert "先停止吧" in cancelled[0]["anchor"]
    assert "长篇辩论发言" not in cancelled[0]["anchor"]
    details = recorded[-1]["details"]
    assert details["ingress_rule"] == "cjk_imperative"
    assert details["author_class"] == "human"


def test_owner_quote_of_own_apology_does_not_recancel(tmp_path):
    provider = _provider(tmp_path, "20260922_owner_group")
    try:
        _owner_turn(provider)
        provider._current_task_anchor = _OWNER_ANCHOR
        provider.prefetch(f'[Replying to: "{_APOLOGY}"]\n\n继续辩论', session_id="20260922_owner_group")
        assert provider._foreground_task_only_prefetch is False
    finally:
        provider.shutdown()
    assert [r for r in _records(tmp_path) if r["status"] == "cancelled"] == []


def test_non_primary_agent_context_never_recovers_or_writes(tmp_path):
    _seed_owner_anchor(tmp_path)
    before = _records(tmp_path)
    sub = _provider(tmp_path, "20260922_subagent", agent_context="subagent")
    try:
        _owner_turn(sub)
        assert sub._current_task_anchor == ""
        sub.prefetch("取消这个任务", session_id="20260922_subagent")
        sub.on_pre_compress([{"role": "user", "content": "安装 ComfyUI"}])
        sub.on_session_end([{"role": "user", "content": "安装 ComfyUI"}])
    finally:
        sub.shutdown()
    assert _records(tmp_path) == before


def _queued_event(provider):
    return provider._queue.get_nowait()


def test_sync_turn_marks_peer_and_control_turns_non_driving(tmp_path):
    provider = _provider(tmp_path, "20260922_owner_group", worker_autostart=False)
    try:
        provider.sync_turn(
            f'[Replying to: "{_APOLOGY}"]\n\n第一阶段·反方立论',
            "收到",
            session_id="20260922_owner_group",
            turn_author={"id": _PEER_ID, "name": "peer-bot", "is_bot": True},
        )
        peer_event = _queued_event(provider)
        provider.sync_turn(
            "停下吧，先别理群消息",
            "收到，已停止。",
            session_id="20260922_owner_group",
            turn_author={"id": _OWNER_ID, "name": "owner", "is_bot": False},
        )
        control_event = _queued_event(provider)
        provider.sync_turn(
            "帮我把 ComfyUI 的 IPAdapter 插件装好",
            "好的，开始安装。",
            session_id="20260922_owner_group",
            turn_author={"id": _OWNER_ID, "name": "owner", "is_bot": False},
        )
        normal_event = _queued_event(provider)
        # a host that sends no turn_author: the on_turn_start value is used,
        # and the event says so
        _owner_turn(provider)
        provider.sync_turn("再装一个插件", "好的。", session_id="20260922_owner_group")
        fallback_event = _queued_event(provider)
    finally:
        provider.shutdown()

    assert peer_event.safe_ref["drive_policy"] == "index_only"
    assert peer_event.safe_ref["non_driving_reason"] == "non_owner_author"
    assert peer_event.safe_ref["author_class"] == "bot"
    assert peer_event.safe_ref["author_source"] == "turn_author"
    # the summary carries the author's words, not the quoted apology
    assert "误以为" not in peer_event.summary
    assert control_event.safe_ref["non_driving_reason"] == "foreground_control_exchange"
    assert "drive_policy" not in normal_event.safe_ref
    assert normal_event.safe_ref["author_class"] == "human"
    assert fallback_event.safe_ref["author_source"] == "turn_start_fallback"
    assert fallback_event.safe_ref["author_class"] == "human"

    for event in (peer_event, control_event):
        decision = classify_event_for_inner_drive(event)
        assert decision.working_kind == ""
        assert decision.candidate_allowed is False
    assert classify_event_for_inner_drive(normal_event).working_kind == "lingering"


def test_peer_author_cannot_exercise_owner_review_actions(tmp_path):
    provider = _provider(tmp_path, "20260922_owner_group")
    try:
        _peer_turn(provider)
        result = provider._process_owner_review_reply_ingress(
            "approve oa_0123456789abcdef", turn_number=1, phase="tool_call"
        )
        audits = _audit(provider, "owner_review_reply_ingress")
    finally:
        provider.shutdown()
    assert result["status"] == "ignored"
    assert result["reason"] == "non_owner_author"
    assert audits and audits[-1]["details"]["reason"] == "non_owner_author"


def test_router_agrees_with_provider_on_peer_turns():
    assert plan_context_route("取消这个任务")["route"] == "foreground_control"
    assert plan_context_route("取消这个任务", author_class="bot")["route"] != "foreground_control"


def test_long_owner_turn_mentioning_later_is_audited_as_refused_deferral(tmp_path):
    provider = _provider(tmp_path, "20260922_owner_dm")
    try:
        _owner_turn(provider)
        provider._current_task_anchor = _OWNER_ANCHOR
        long_instruction = "保守清理，清理完成后核对一遍功能和状态：删除 15 个旧 paused job 定义，" * 4 + "其余明天再说。"
        provider.prefetch(long_instruction, session_id="20260922_owner_dm")
        skipped = _audit(provider, "ingress_foreground_control_skipped")
    finally:
        provider.shutdown()
    # no deferral was recorded for a long instruction that merely says "明天再说"
    assert not (tmp_path / "memory-os" / "system" / "deferred_foreground_tasks.jsonl").exists()
    assert skipped and skipped[-1]["details"]["reason"] == "defer_rejected_turn_too_long"
    assert skipped[-1]["details"]["author_class"] == "human"


# ── principal (P0-lite, 2026-09-23): configured owner identities ──────────
# "human" (author_class) only ever meant "the host admitted a non-bot
# author" -- never a verified owner. These tests configure
# principal.owner_identities so a *human*, non-bot author who is not the
# owner is still blocked, and the owner is still recognized once configured.


def test_configured_non_owner_human_cannot_cancel_the_owner_task(tmp_path):
    """Counterfactual: without resolve_principal wired into
    _refresh_current_task_anchor_from_query, a configured non-owner human
    (author_class="human", same as the owner) would still cancel the owner's
    foreground task -- exactly the gap author_class alone cannot close."""
    _seed_owner_identity(tmp_path, "telegram", _OWNER_ID)
    provider = _provider(tmp_path, "20260923_other_human_cancel")
    try:
        _other_human_turn(provider)
        assert provider._turn_principal == "other_human"
        provider._current_task_anchor = _OWNER_ANCHOR
        provider.prefetch("取消这个任务", session_id="20260923_other_human_cancel")
        assert provider._foreground_task_only_prefetch is False
        skipped = _audit(provider, "ingress_foreground_control_skipped")
    finally:
        provider.shutdown()
    assert [r for r in _records(tmp_path) if r["status"] == "cancelled"] == []
    assert skipped and skipped[-1]["details"]["reason"] == "non_owner_authored_turn"
    assert skipped[-1]["details"]["author_class"] == "human"
    assert skipped[-1]["details"]["principal"] == "other_human"


def test_configured_non_owner_human_cannot_approve_an_owner_action(tmp_path):
    """Counterfactual: without resolve_principal wired into
    _process_owner_review_reply_ingress (which used to gate on
    author_class == "bot" only), a configured non-owner human could approve
    an owner action merely by being a non-bot author."""
    _seed_owner_identity(tmp_path, "telegram", _OWNER_ID)
    provider = _provider(tmp_path, "20260923_other_human_review")
    try:
        _other_human_turn(provider)
        result = provider._process_owner_review_reply_ingress(
            "approve oa_0123456789abcdef", turn_number=1, phase="tool_call"
        )
        audits = _audit(provider, "owner_review_reply_ingress")
    finally:
        provider.shutdown()
    assert result["status"] == "ignored"
    assert result["reason"] == "non_owner_author"
    assert audits and audits[-1]["details"]["reason"] == "non_owner_author"
    assert audits[-1]["details"]["principal"] == "other_human"


def test_configured_owner_can_still_cancel_once_bound(tmp_path):
    """The other side of the same rule: configuring owner_identities must not
    accidentally lock the real owner out."""
    _seed_owner_identity(tmp_path, "telegram", _OWNER_ID)
    provider = _provider(tmp_path, "20260923_owner_configured")
    try:
        _owner_turn(provider)
        assert provider._turn_principal == "owner"
        provider._current_task_anchor = _OWNER_ANCHOR
        provider.prefetch("取消这个任务", session_id="20260923_owner_configured")
        assert provider._foreground_task_only_prefetch is True
    finally:
        provider.shutdown()
    assert [r for r in _records(tmp_path) if r["status"] == "cancelled"]


def test_configured_owner_can_still_approve_an_owner_action_once_bound(tmp_path):
    _seed_owner_identity(tmp_path, "telegram", _OWNER_ID)
    provider = _provider(tmp_path, "20260923_owner_review")
    try:
        _owner_turn(provider)
        result = provider._process_owner_review_reply_ingress(
            "approve oa_0123456789abcdef", turn_number=1, phase="tool_call"
        )
    finally:
        provider.shutdown()
    # oa_ token unknown to this fresh store -> not "ignored" for author reasons
    assert result["reason"] != "non_owner_author"


def test_mailbox_source_never_drives_foreground_control(tmp_path):
    """Owner ruling: mailbox is a peer channel, never owner-authenticated --
    not even an owner-shaped author_id on the mailbox source may cancel."""
    provider = _provider(tmp_path, "20260923_mailbox_1", platform="mailbox")
    try:
        _owner_turn(provider)
        assert provider._turn_principal == "peer_agent"
        provider._current_task_anchor = _OWNER_ANCHOR
        provider.prefetch("取消这个任务", session_id="20260923_mailbox_1")
        assert provider._foreground_task_only_prefetch is False
    finally:
        provider.shutdown()
    assert [r for r in _records(tmp_path) if r["status"] == "cancelled"] == []


def test_local_cli_source_drives_foreground_control_without_any_configured_identity(tmp_path):
    """Owner ruling: local shell access already implies higher trust than
    the conversational owner gate -- no principal.owner_identities entry is
    needed for a cli/tui/acp session to be treated as owner."""
    provider = _provider(tmp_path, "20260923_cli_1", platform="cli")
    try:
        provider.on_turn_start(1, "", author_id="root", author_name="root", author_is_bot=False)
        assert provider._turn_principal == "owner"
        provider._current_task_anchor = _OWNER_ANCHOR
        provider.prefetch("取消这个任务", session_id="20260923_cli_1")
        assert provider._foreground_task_only_prefetch is True
    finally:
        provider.shutdown()
    assert [r for r in _records(tmp_path) if r["status"] == "cancelled"]


def test_sync_turn_marks_configured_non_owner_human_non_driving(tmp_path):
    _seed_owner_identity(tmp_path, "telegram", _OWNER_ID)
    provider = _provider(tmp_path, "20260923_other_human_sync", worker_autostart=False)
    try:
        provider.sync_turn(
            "帮我记一下这个想法",
            "好的",
            session_id="20260923_other_human_sync",
            turn_author={"id": _OTHER_HUMAN_ID, "name": "other-human", "is_bot": False},
        )
        event = _queued_event(provider)
    finally:
        provider.shutdown()
    assert event.safe_ref["author_class"] == "human"
    assert event.safe_ref["principal"] == "other_human"
    assert event.safe_ref["drive_policy"] == "index_only"
    assert event.safe_ref["non_driving_reason"] == "non_owner_author"


def test_sync_turn_still_drives_for_configured_owner(tmp_path):
    _seed_owner_identity(tmp_path, "telegram", _OWNER_ID)
    provider = _provider(tmp_path, "20260923_owner_sync", worker_autostart=False)
    try:
        provider.sync_turn(
            "帮我把 ComfyUI 装好",
            "好的",
            session_id="20260923_owner_sync",
            turn_author={"id": _OWNER_ID, "name": "owner", "is_bot": False},
        )
        event = _queued_event(provider)
    finally:
        provider.shutdown()
    assert event.safe_ref["principal"] == "owner"
    assert "drive_policy" not in event.safe_ref


def test_router_agrees_with_provider_on_configured_non_owner_human():
    """Same shape as test_router_agrees_with_provider_on_peer_turns, for the
    principal parameter: the router must reach the same eligibility verdict
    the provider does for a configured non-owner human."""
    assert plan_context_route("取消这个任务", principal="owner")["route"] == "foreground_control"
    assert plan_context_route("取消这个任务", principal="unknown")["route"] == "foreground_control"
    assert plan_context_route("取消这个任务", principal="other_human")["route"] != "foreground_control"
    assert plan_context_route("取消这个任务", principal="peer_agent")["route"] != "foreground_control"
    assert plan_context_route("取消这个任务", principal="system")["route"] != "foreground_control"


def test_cron_session_turn_keeps_its_pre_principal_handling(tmp_path):
    """Counterfactual: a scheduled session resolves to principal "system".
    Routing that through the non-owner gate turned every cron turn
    index-only (non_driving_reason=non_owner_author) and skipped its
    operation capture -- a behaviour change for ~770 cron sessions a month on
    production that P0-lite never set out to make. Cron turns keep the
    scheduled-session handling they had before the principal model."""
    session_id = "cron_1a2b3c4d5e6f_20260923_010000"
    _seed_owner_identity(tmp_path, "telegram", _OWNER_ID)
    provider = _provider(tmp_path, session_id, worker_autostart=False)
    try:
        provider.on_turn_start(1, "run the nightly digest")
        provider.sync_turn("run the nightly digest", "digest done", session_id=session_id)
        event = _queued_event(provider)
    finally:
        provider.shutdown()
    assert event.safe_ref["principal"] == "system"
    assert "drive_policy" not in event.safe_ref
    assert "non_driving_reason" not in event.safe_ref


def test_subagent_context_turn_keeps_its_pre_principal_handling(tmp_path):
    """The other path to principal "system": a non-primary Hermes context
    (subagent, ~360 sessions a month on production main) with an ordinary
    session id. sync_turn does not short-circuit non-primary contexts, so its
    turns reach the foreground gate too and must keep the pre-principal
    handling, exactly as cron turns do."""
    session_id = "20260923_subagent_session"
    _seed_owner_identity(tmp_path, "telegram", _OWNER_ID)
    provider = _provider(tmp_path, session_id, worker_autostart=False, agent_context="subagent")
    try:
        provider.on_turn_start(1, "summarise the build log")
        provider.sync_turn("summarise the build log", "summary", session_id=session_id)
        event = _queued_event(provider)
    finally:
        provider.shutdown()
    assert event.safe_ref["principal"] == "system"
    assert "drive_policy" not in event.safe_ref
    assert "non_driving_reason" not in event.safe_ref
