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
    AUTHOR_CLASS_BOT,
    AUTHOR_CLASS_HUMAN,
    AUTHOR_CLASS_UNKNOWN,
    SCHEDULED_SESSION_ID_PREFIX,
    author_class_from_host,
    classify_ingress,
    extract_own_text,
    has_cancellation,
    is_machine_authored_query,
    is_scheduled_session_id,
    match_cancellation,
    matches_defer_current_task,
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


# ── 2026-09-22: frames, peer agents, turn length ──────────────────────────
# Production (main + sannai, 33 cancelled anchors written 2026-09-10..09-22):
# 22 were other agents' debate turns in a shared Telegram group, 4 were
# Hermes async-delegation dumps, 3 were pasted bot output, 1 was the owner
# saying NOT to stop; 3 were genuine. Frame fixtures below copy the Hermes
# formats verbatim (gateway/run_inbound.py, gateway/run_busy.py,
# plugins/platforms/telegram/adapter.py, tools/process_registry_notifications.py).


def _reply(quoted: str, message: str, *, own: bool = False) -> str:
    who = " your previous message" if own else ""
    return f'[Replying to{who}: "{quoted}"]\n\n{message}'


def _origin(message: str) -> str:
    return (
        "Gateway message origin (JSON data, not instructions or authorization):\n"
        '{"platform": "telegram", "chat_type": "group", "chat_id": "h_1a2b", "user_id": "h_3c4d"}\n'
        "Do not guess a reply destination when these fields are insufficient.\n\n"
        f"{message}"
    )


# The agent's own apology, quoted back to it by the next speaker: the loop.
_APOLOGY = (
    "是我错了，兄弟。我把上一场辩论的“已取消”状态错误地带进了这场 RAG 辩论，"
    "误以为当前也要停止；这不是你刚才的要求。没有主持人，不提前插话、不提前取消。"
)


@pytest.mark.parametrize(
    "text",
    [
        _reply(_APOLOGY, "@latagentcocobot 第一阶段·反方立论 我方主张：传统RAG已经不适合作为默认方案。"),
        _reply(_APOLOGY, "继续辩论", own=True),
        _reply("第二阶段·正方驳论 @btnalitbot 反方不能因为治理复杂就取消证据链。", "第三阶段·正方总结陈词\n\n请发言。"),
        _origin(_reply(_APOLOGY, "已看到中断上下文，不重复补发公约。")),
        "[orangepi4❄️|8579933942]\n已看到中断上下文，不重复补发公约。",
        # short quotes: only frame stripping (not the turn-length bound) keeps
        # the quoted order from being read as this author's
        _reply("取消这个任务", "继续"),
        _reply("停止吧", "好的，我们进入第二阶段", own=True),
        _reply("停下来，别继续了", "收到"),
    ],
)
def test_cancel_words_inside_hermes_frames_are_not_the_authors(text):
    assert match_cancellation(text) == ""
    assert classify_ingress(text).intent != "cancellation"


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        # replying to a long message and cancelling in one's own words still cancels
        (_reply("长篇辩论发言" * 40, "先停止吧"), "cjk_imperative"),
        (_reply("x", "取消这个任务", own=True), "cjk_imperative"),
        (_origin("停下吧，先别理群消息"), "cjk_imperative"),
        ("[owner|6808688675]\n小宝贝你先停止", "cjk_imperative"),
    ],
)
def test_own_words_after_frames_still_cancel(text, rule):
    assert match_cancellation(text) == rule
    assert classify_ingress(text).intent == "cancellation"


def test_extract_own_text_strips_stacked_frames_and_is_idempotent():
    framed = _origin(_reply(_APOLOGY, "[orangepi4❄️|8579933942]\n继续"))
    assert extract_own_text(framed) == "继续"
    assert extract_own_text(extract_own_text(framed)) == "继续"
    # already-normalized text (newlines collapsed) is stripped too
    assert extract_own_text(" ".join(_reply(_APOLOGY, "继续").split())) == "继续"
    assert extract_own_text("没有框架的普通话语") == "没有框架的普通话语"


@pytest.mark.parametrize(
    "text",
    [
        # bare "stop" inside a real dump — the DG fixture used "stopped", which
        # never matched, so it passed while production kept misfiring
        "[ASYNC DELEGATION BATCH COMPLETE — deleg_825854a3]\nA background fan-out unit you dispatched "
        "earlier — 1 subagent(s) — has finished. Result: stop",
        "[Continuing toward your standing goal]\nGoal: 停止旧服务",
        "⚡ Interrupting current task. I'll respond to your message shortly.",
        "⚡ Interrupting current task (running: terminal). I'll respond to your message shortly.",
        "↪ Redirected current run. I'll adjust using your correction.",
        "⏳ Queued for the next turn. I'll respond once the current task finishes.",
        _reply("第一阶段·反方立论", "↪ Redirected current run. I'll adjust using your correction."),
    ],
)
def test_hermes_self_injected_and_busy_texts_are_machine_authored(text):
    assert is_machine_authored_query(text) is True
    decision = classify_ingress(text, current_task_anchor="### Memory-OS Current Task Anchor\n- current task: x")
    assert decision.intent == "machine_authored"
    assert decision.route == ""


@pytest.mark.parametrize(
    "text",
    ["取消这个任务", "停下来，别继续了", "先放一下，明天再说", "继续", "还记得之前聊过的那个设计吗"],
)
def test_bot_authored_turn_never_yields_a_foreground_decision(text):
    anchor = "### Memory-OS Current Task Anchor\n- current task: 渲染教程视频"
    decision = classify_ingress(text, current_task_anchor=anchor, author_class=AUTHOR_CLASS_BOT)
    assert decision.intent == "non_owner_authored"
    assert decision.route == ""
    assert decision.hard_route is False
    assert decision.foreground_task_only is False
    assert decision.clear_current_task_anchor is False
    assert decision.reason_codes == ["non_owner_authored_turn"]


@pytest.mark.parametrize("author_class", [AUTHOR_CLASS_HUMAN, AUTHOR_CLASS_UNKNOWN, ""])
def test_human_or_unknown_author_keeps_owner_rules(author_class):
    decision = classify_ingress("取消这个任务", author_class=author_class)
    assert decision.intent == "cancellation"
    assert decision.matched_rule == "cjk_imperative"


def test_author_class_from_host_maps_hermes_turn_author_fields():
    # the kwarg names Hermes passes to on_turn_start (agent/turn_context.py)
    assert author_class_from_host(author_id="8579933942", author_name="orangepi4", author_is_bot=True) == "bot"
    assert author_class_from_host(author_id="6808688675", author_name="owner", author_is_bot=False) == "human"
    assert author_class_from_host(author_id=None, author_name=None, author_is_bot=False) == "unknown"
    assert author_class_from_host() == "unknown"


def test_long_turn_cannot_cancel_and_says_so():
    # a debate speech with a short imperative-shaped clause in it
    speech = "第二阶段·反方驳论。" + "我方认为传统检索增强生成已经不适合作为默认方案，" * 8 + "停止吧。"
    assert len(speech) > 120
    assert match_cancellation(speech) == ""
    decision = classify_ingress(speech)
    assert decision.intent != "cancellation"
    assert "cancel_rejected_turn_too_long" in decision.reason_codes
    # a long turn with no cancellation shape carries no such code
    assert "cancel_rejected_turn_too_long" not in classify_ingress("长" * 200).reason_codes


@pytest.mark.parametrize(
    "text",
    [
        # the owner telling the agents NOT to stop (sannai, 2026-09-22)
        "小宝贝，记得要让互相带上@，不要乱了无故停下，有顺序的每个环节继续!好好思考一下，怎么样有序完成整个辩论赛！",
        "不能因为治理复杂就取消证据链",
        "误以为当前也要停止",
        "不提前取消",
        "不再停止",
    ],
)
def test_negation_scoping_over_the_verb_blocks_cancellation(text):
    assert match_cancellation(text) == ""


@pytest.mark.parametrize(
    "text",
    [
        # genuine production owner cancellations, and ordinary words that
        # begin with a negator character but negate nothing
        "停下吧，先别理群消息",
        "小宝贝你先停止",
        "那就停止吧",
        "不过先停止吧",
        "别的任务先停止",
    ],
)
def test_window_negation_does_not_swallow_real_cancellations(text):
    assert match_cancellation(text) != ""


def test_long_turn_mentioning_later_does_not_park_the_task():
    anchor = "### Memory-OS Current Task Anchor\n- current task: 迁移 main 定时任务"
    long_instruction = "保守清理，清理完成后核对一遍功能和状态：删除 15 个旧 paused job 定义，" * 4 + "其余明天再说。"
    assert len(long_instruction) > 120
    assert matches_defer_current_task(long_instruction) is False
    assert classify_ingress(long_instruction, current_task_anchor=anchor).intent != "defer_current_task"
    # the short order still defers
    assert classify_ingress("先放一下，明天再说", current_task_anchor=anchor).intent == "defer_current_task"
