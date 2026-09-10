"""Ingress classification: cancellation intent and machine-authored guards.

Counterfactual for the 2026-09-10 production defect: ``has_cancellation`` was a
bare substring scan, so every scheduled-job prompt containing "停止"/"停下" and
every owner mention of "取消" (订单 / 提示词 / 修复请求) was read as an owner
cancellation and wrote a cancelled anchor plus a "stop the foreground task"
instruction into the next context. Phrases below are structurally equivalent
to the production ledger rows, not verbatim owner chat.
"""
import pytest

from plugins.memory.memory_os.ingress import (
    SCHEDULED_SESSION_ID_PREFIX,
    classify_ingress,
    has_cancellation,
    is_machine_authored_query,
    is_scheduled_session_id,
    match_cancellation,
)

# The Hermes cron runner preamble, followed by prose from the two production
# job prompts that were misread ("再停下来询问主人", "如果跳过 → 停止").
_CRON_PROMPT = (
    "[IMPORTANT: You are running as a scheduled cron job. DELIVERY: Your final "
    "response will be automatically delivered to the user — do NOT use send_message "
    "or try to deliver the output yourself.] 涉及不可逆或超出个人边界的事，再停下来询问主人。"
    "※ 如果跳过 → 停止。不读其他文件、不写日记、不发消息。"
)


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("太垃圾了，算了，你还是别做视频了", "cjk_resignation"),
        ("那算了，太麻烦了，我还是手动来", "cjk_resignation"),
        ("取消这个任务", "cjk_imperative"),
        ("这个任务取消，不要继续了", "cjk_imperative"),
        ("停下来，别继续了", "cjk_imperative"),
        ("取消吧", "cjk_imperative"),
        ("取消安装", "cjk_imperative"),
        ("我想取消这个任务", "cjk_imperative"),
        # The object is not whitelisted. An earlier draft required one of ~20
        # task nouns after the verb and rejected all of these — a false
        # negative is worse than the bug being fixed here, because the
        # cancellation sentence then becomes a new *active* anchor.
        ("取消掉这个渲染任务", "cjk_imperative"),
        ("停止安装插件", "cjk_imperative"),
        ("停止渲染视频", "cjk_imperative"),
        ("放弃这个方案", "cjk_imperative"),
        ("取消这个视频的渲染", "cjk_imperative"),
        ("取消下载模型", "cjk_imperative"),
        ("停下手上的活", "cjk_imperative"),
        ("那个渲染任务先取消掉吧", "cjk_imperative"),
        # 后台 contains 后 but is not the "取消…后多久" descriptive frame.
        ("停止后台任务", "cjk_imperative"),
        ("Please stop this task.", "ascii_imperative"),
        ("abort", "ascii_imperative"),
        ("never mind, skip it", "ascii_imperative"),
        ("请stop吧", "ascii_imperative"),
    ],
)
def test_cancellation_imperatives_match_with_rule_id(text, rule):
    assert match_cancellation(text) == rule
    assert has_cancellation(text) is True
    decision = classify_ingress(text)
    assert decision.intent == "cancellation"
    assert decision.route == "foreground_control"
    assert decision.matched_rule == rule


@pytest.mark.parametrize(
    "text",
    [
        # descriptive / temporal frame around the verb
        "取消前台任务时，同时清除对应的全局 task anchor",
        "为什么老是有取消的提示词？",
        # business object, not the foreground task
        "取消订单后多久到账",
        "取消订阅要去哪里操作",
        # negated / reported verb
        "服务不要停止，修一下就好",
        "llama-server 已取消开机启动",
        "do not stop the service",
        # inflected ASCII forms are not the bare imperative
        "The job stopped unexpectedly, please investigate",
        "the process is unstoppable, check stop_reason",
        # resignation forms inside another construction
        "算了一下账目",
        "不要做成微服务",
        # questions are never commands
        "这个任务取消了吗？",
        "是不是取消了",
        # ops instructions issued *while* the foreground task continues —
        # stopping a service is not cancelling the work (production shapes,
        # reworded)
        "在这次迁移里停止远端 3.14 的 source gateway，其余不动",
        "旧服务该停止的要确保停止了",
        # a cancellation word buried in a long clause is a mention, not an order
        "在政府宣布取消限购之后各地房价出现明显波动，市场需要时间消化这一政策变化",
        # machine-authored frames
        _CRON_PROMPT,
        "Cronjob Response: job-x (job_id: 1) ⚠️ stop",
        "[ASYNC DELEGATION BATCH COMPLETE — deleg_abc123] 3 subagents finished; one was stopped.",
        "",
    ],
)
def test_non_imperative_mentions_do_not_match(text):
    assert match_cancellation(text) == ""
    assert has_cancellation(text) is False
    assert classify_ingress(text).intent != "cancellation"


def test_scheduled_session_id_prefix_is_the_hermes_cron_shape():
    assert SCHEDULED_SESSION_ID_PREFIX == "cron_"
    assert is_scheduled_session_id("cron_9c0605348522_20260910_090002") is True
    assert is_scheduled_session_id("telegram-8123") is False
    assert is_scheduled_session_id("") is False


def test_machine_authored_query_is_detected_by_hermes_preamble():
    assert is_machine_authored_query(_CRON_PROMPT) is True
    assert is_machine_authored_query("  cronjob response: x") is True
    assert is_machine_authored_query("取消这个任务") is False


def test_scheduled_session_never_yields_a_foreground_control_decision():
    cron_session = "cron_9c0605348522_20260910_090002"
    anchor = "### Memory-OS Current Task Anchor\n- current task: 渲染教程视频"
    for text in ("取消这个任务", "先放一下，明天再说", "继续", _CRON_PROMPT, "later today"):
        decision = classify_ingress(text, current_task_anchor=anchor, session_id=cron_session)
        assert decision.intent == "machine_authored", text
        assert decision.route == ""
        assert decision.hard_route is False
        assert decision.foreground_task_only is False
        assert decision.clear_current_task_anchor is False
        assert decision.reason_codes == ["machine_authored_query"]


def test_machine_authored_prompt_is_guarded_even_without_session_id():
    anchor = "### Memory-OS Current Task Anchor\n- current task: 渲染教程视频"
    decision = classify_ingress(_CRON_PROMPT, current_task_anchor=anchor)
    assert decision.intent == "machine_authored"
    assert decision.route == ""


def test_owner_session_with_same_text_still_cancels():
    decision = classify_ingress("取消这个任务", session_id="telegram-8123")
    assert decision.intent == "cancellation"
    assert decision.foreground_task_only is True
    assert decision.matched_rule == "cjk_imperative"
