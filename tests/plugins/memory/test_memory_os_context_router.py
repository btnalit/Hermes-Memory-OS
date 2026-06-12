import argparse
import json

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.context_router import (
    INCLUDE_THRESHOLD,
    ContextSection,
    plan_context_route,
    route_context_sections,
)
from plugins.memory.memory_os.fixtures import build_event, build_working_item
from plugins.memory.memory_os.prefetch import (
    build_context_router_report,
    build_prefetch,
    build_prefetch_section_candidates,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_router_routes_cancellation_to_foreground_control():
    report = plan_context_route(
        "太垃圾了，算了，你还是别做视频了",
        current_task_anchor="Current task: render ComfyUI tutorial video.",
    )

    assert report["route"] == "foreground_control"
    assert report["hard_route"] is True
    assert "cancellation" in report["reason_codes"]


def test_router_routes_vague_continue_to_foreground_control_when_anchor_exists():
    report = plan_context_route(
        "继续当前任务",
        current_task_anchor="Current task: install ComfyUI Impact Pack.",
    )

    assert report["route"] == "foreground_control"
    assert report["hard_route"] is True
    assert "vague_continue_with_anchor" in report["reason_codes"]


def test_router_reports_deferred_cancellation_as_open_case():
    report = plan_context_route(
        "这个先放一下，明天再说",
        current_task_anchor="Current task: render ComfyUI tutorial video.",
    )

    assert report["route"] == "foreground_control"
    assert report["hard_route"] is True
    assert "deferred_cancellation_open" in report["reason_codes"]
    assert report["open_issue"] == "deferred_cancellation_requires_anchor_lifecycle"

    routed = route_context_sections(
        "这个先放一下，明天再说",
        sections=[
            ContextSection(
                section="Current Foreground Task",
                text="Current task: render ComfyUI tutorial video.",
                source_class="foreground",
            )
        ],
        current_task_anchor="Current task: render ComfyUI tutorial video.",
        budget_chars=1200,
    )

    assert routed["open_issue"] == "deferred_cancellation_requires_anchor_lifecycle"


def test_router_routes_explicit_status_to_diagnostic():
    report = plan_context_route("当前记忆架构是什么？")

    assert report["route"] == "diagnostic_current_status"
    assert report["hard_route"] is True
    assert "explicit_diagnostic" in report["reason_codes"]


def test_router_routes_casual_memory_opinion_to_casual_continuity():
    report = plan_context_route("我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？")

    assert report["route"] == "casual_continuity"
    assert report["hard_route"] is False
    assert "ordinary_opinion" in report["reason_codes"]


def test_router_routes_low_clue_recall_to_ambiguous_recall():
    report = plan_context_route("你还记得我之前跟你说过的一个设计吗？")

    assert report["route"] == "ambiguous_recall"
    assert report["hard_route"] is False
    assert "low_clue_recall" in report["reason_codes"]


def test_router_routes_deictic_continue_recall_to_ambiguous_recall():
    for query in ["继续昨天那个。", "继续上次那个。", "继续刚才那个", "继续刚才那个。", "接着刚才那条。"]:
        report = plan_context_route(query)

        assert report["route"] == "ambiguous_recall"
        assert report["hard_route"] is False
        assert "low_clue_deictic_continue" in report["reason_codes"]


def test_router_routes_deictic_continue_to_recall_even_with_current_anchor():
    report = plan_context_route(
        "继续刚才那个",
        current_task_anchor="Current task: inspect ComfyUI layout_report.json.",
    )

    assert report["route"] == "ambiguous_recall"
    assert report["hard_route"] is False
    assert "low_clue_deictic_continue" in report["reason_codes"]


def test_router_keeps_current_task_continue_on_foreground_control():
    report = plan_context_route(
        "继续当前任务",
        current_task_anchor="Current task: inspect ComfyUI layout_report.json.",
    )

    assert report["route"] == "foreground_control"
    assert report["hard_route"] is True
    assert "vague_continue_with_anchor" in report["reason_codes"]


def test_router_routes_candidate_question_to_candidate_review():
    report = plan_context_route("那些 crystallized candidates 是已经沉淀的长期记忆吗？")

    assert report["route"] == "candidate_review"
    assert "candidate_review_terms" in report["reason_codes"]


def test_router_routes_active_task_to_active_task():
    report = plan_context_route("帮我继续安装 ComfyUI 插件，失败后只汇总原因")

    assert report["route"] == "active_task"
    assert "active_task_terms" in report["reason_codes"]


def test_router_routes_architecture_discussion_separately_from_casual():
    report = plan_context_route("Memory-OS 的层级和 Working Memory 是怎么设计的？")

    assert report["route"] == "memory_architecture_discussion"
    assert "architecture_discussion_terms" in report["reason_codes"]


def test_active_task_report_keeps_relevant_working_and_drops_hindsight_noise():
    sections = [
        ContextSection(
            section="Current Foreground Task",
            text="Current task: install ComfyUI Impact Pack and report failure reason.",
            source_class="foreground",
        ),
        ContextSection(
            section="Working Memory",
            text="ComfyUI Impact Pack failed because github.com could not connect.",
            source_class="working",
        ),
        ContextSection(
            section="Working Memory",
            text="Hindsight / hermes02 legacy memory architecture discussion.",
            source_class="working",
        ),
        ContextSection(
            section="Conversation Carryover",
            text="Memory-OS governance and provider-status discussion from earlier.",
            source_class="carryover",
        ),
    ]

    report = route_context_sections(
        "帮我继续安装 ComfyUI 插件",
        sections=sections,
        current_task_anchor="Current task: install ComfyUI Impact Pack.",
        budget_chars=1200,
    )

    selected = {item["section"] + ":" + item["source_class"] for item in report["selected_sections"]}
    dropped_text = json.dumps(report["dropped_sections"], ensure_ascii=False)

    assert report["schema_version"] == "memory-os.context_router.v0"
    assert report["mode"] == "dry_run"
    assert report["route"] == "active_task"
    assert INCLUDE_THRESHOLD == 0.30
    assert "Current Foreground Task:foreground" in selected
    assert "Working Memory:working" in selected
    assert "Hindsight" not in json.dumps(report["selected_sections"], ensure_ascii=False)
    assert "route_excludes_broad_carryover" in dropped_text
    assert "diagnostic_style_in_non_diagnostic_route" in dropped_text


def test_casual_continuity_report_selects_safe_carryover_without_mechanism_working():
    sections = [
        ContextSection(
            section="Conversation Carryover",
            text="Recent conversation has something worth carrying forward without exposing internals.",
            source_class="carryover",
        ),
        ContextSection(
            section="Working Memory",
            text="Memory-OS provider-status note with memory_os canonical store index health audit details.",
            source_class="working",
        ),
        ContextSection(
            section="Indexed Recall",
            text="query route: fast_path; search: memory_os diagnostic architecture.",
            source_class="indexed",
        ),
    ]

    report = route_context_sections(
        "我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？",
        sections=sections,
        current_task_anchor="",
        budget_chars=1200,
    )

    selected = {item["section"] for item in report["selected_sections"]}
    rendered_selected = json.dumps(report["selected_sections"], ensure_ascii=False)

    assert report["route"] == "casual_continuity"
    assert selected == {"Conversation Carryover"}
    assert "memory_os canonical store" not in rendered_selected


def test_router_report_redacts_secrets():
    sections = [
        ContextSection(
            section="Working Memory",
            text="Deploy note with api_key=SHOULD_NOT_LEAK token: ALSO_SECRET.",
            source_class="working",
        )
    ]

    report = route_context_sections(
        "部署脚本",
        sections=sections,
        current_task_anchor="Current task: deploy script.",
        budget_chars=1200,
    )
    rendered = json.dumps(report, ensure_ascii=False)

    assert "SHOULD_NOT_LEAK" not in rendered
    assert "ALSO_SECRET" not in rendered
    assert "[redacted]" in rendered


def test_prefetch_section_candidates_expose_existing_sections_without_changing_default_output(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(build_event(seed=90, profile="memoryos-test"))
    working_item = build_working_item(seed=91, source_event_id=event.id)
    store.append_event(event)
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": working_item.updated_at,
            "items": [{**working_item.__dict__, "text": "ComfyUI install task should remain visible."}],
        },
    )

    before = build_prefetch("帮我继续安装 ComfyUI 插件", budget_chars=2200, store=store, index=None)
    candidates = build_prefetch_section_candidates(
        "帮我继续安装 ComfyUI 插件",
        store=store,
        index=None,
        current_task_anchor="Current task: install ComfyUI plugins.",
    )
    after = build_prefetch("帮我继续安装 ComfyUI 插件", budget_chars=2200, store=store, index=None)

    assert before == after
    assert any(section.section == "Current Foreground Task" for section in candidates)
    assert any(section.section == "Working Memory" for section in candidates)
    assert any("ComfyUI install task" in section.text for section in candidates)


def test_prefetch_context_router_report_is_dry_run_and_does_not_change_live_prefetch(tmp_path):
    store = _store(tmp_path)
    working_item = build_working_item(seed=92, source_event_id="evt-working")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": working_item.updated_at,
            "items": [
                {**working_item.__dict__, "text": "ComfyUI plugin install is failing at github.com."},
                {
                    **build_working_item(seed=93, source_event_id="evt-noise").__dict__,
                    "text": "Hindsight / hermes02 legacy provider-status note should be penalized.",
                },
            ],
        },
    )

    live_context = build_prefetch("帮我继续安装 ComfyUI 插件", budget_chars=2200, store=store, index=None)
    report = build_context_router_report(
        "帮我继续安装 ComfyUI 插件",
        budget_chars=2200,
        store=store,
        index=None,
        current_task_anchor="Current task: install ComfyUI plugin.",
    )
    after = build_prefetch("帮我继续安装 ComfyUI 插件", budget_chars=2200, store=store, index=None)

    assert live_context == after
    assert report["schema_version"] == "memory-os.context_router.v0"
    assert report["mode"] == "dry_run"
    assert report["route"] == "active_task"
    assert "ComfyUI plugin install" in live_context
    assert "Hindsight" not in live_context
    assert json.dumps(report, ensure_ascii=False)


def test_prefetch_context_router_apply_all_filters_live_prefetch(tmp_path):
    store = _store(tmp_path)
    safe_item = build_working_item(seed=95, source_event_id="evt-safe")
    noisy_item = build_working_item(seed=96, source_event_id="evt-noisy")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": safe_item.updated_at,
            "items": [
                {**safe_item.__dict__, "text": "ComfyUI Impact Pack install failed at github.com clone."},
                {**noisy_item.__dict__, "text": "Hindsight / hermes02 legacy provider-status note."},
            ],
        },
    )

    context = build_prefetch(
        "帮我继续安装 ComfyUI 插件",
        budget_chars=2200,
        store=store,
        index=None,
        current_task_anchor="Current task: install ComfyUI Impact Pack.",
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
    )

    assert "Current Foreground Task" in context
    assert "ComfyUI Impact Pack install failed" in context
    assert "Hindsight" not in context
    assert "Conversation Carryover" not in context


def test_prefetch_context_router_foreground_apply_matches_rh25b_foreground_only(tmp_path):
    store = _store(tmp_path)
    item = build_working_item(seed=97, source_event_id="evt-working")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": item.updated_at,
            "items": [{**item.__dict__, "text": "Background Memory-OS architecture discussion."}],
        },
    )
    anchor = "### Memory-OS Current Task Anchor\n- current task: render ComfyUI tutorial video"

    rh25b_context = build_prefetch(
        "太垃圾了，算了，你还是别做视频了",
        budget_chars=2200,
        store=store,
        index=None,
        current_task_anchor=anchor,
        foreground_task_only=True,
    )
    router_context = build_prefetch(
        "太垃圾了，算了，你还是别做视频了",
        budget_chars=2200,
        store=store,
        index=None,
        current_task_anchor=anchor,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["foreground_control"]},
    )

    assert router_context == rh25b_context
    assert "Working Memory" not in router_context


def test_prefetch_context_router_apply_can_be_rolled_back_by_config(tmp_path):
    store = _store(tmp_path)
    item = build_working_item(seed=98, source_event_id="evt-working")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": item.updated_at,
            "items": [{**item.__dict__, "text": "ComfyUI plugin install is active."}],
        },
    )

    baseline = build_prefetch("帮我继续安装 ComfyUI 插件", budget_chars=2200, store=store, index=None)
    rolled_back = build_prefetch(
        "帮我继续安装 ComfyUI 插件",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "dry_run", "apply_routes": ["all"]},
    )

    assert rolled_back == baseline


def test_working_memory_filters_zero_overlap_items_when_query_has_features(tmp_path):
    store = _store(tmp_path)
    relevant = build_working_item(seed=198, source_event_id="evt-relevant")
    noise = build_working_item(seed=199, source_event_id="evt-noise")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": relevant.updated_at,
            "items": [
                {**relevant.__dict__, "text": "ComfyUI plugin install is active."},
                {**noise.__dict__, "text": "Garden irrigation reminder for weekend errands."},
            ],
        },
    )

    context = build_prefetch("ComfyUI plugin install", budget_chars=2200, store=store, index=None)

    assert "ComfyUI plugin install is active" in context
    assert "Garden irrigation" not in context


def test_working_memory_zero_feature_query_keeps_recency_behavior(tmp_path):
    store = _store(tmp_path)
    first = build_working_item(seed=200, source_event_id="evt-first")
    second = build_working_item(seed=201, source_event_id="evt-second")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": second.updated_at,
            "items": [
                {**first.__dict__, "text": "ComfyUI plugin install is active."},
                {**second.__dict__, "text": "Garden irrigation reminder for weekend errands."},
            ],
        },
    )

    context = build_prefetch("", budget_chars=2200, store=store, index=None)

    assert "ComfyUI plugin install is active" in context
    assert "Garden irrigation reminder" in context


def test_context_router_casual_and_ambiguous_exclude_working_memory():
    working = ContextSection(section="Working Memory", text="ComfyUI plugin install", source_class="working")
    carryover = ContextSection(section="Conversation Carryover", text="Recent conversation has something worth carrying forward.")
    guard = ContextSection(section="Recall Clarification Guard", text="Ask for a keyword.", source_class="recall_guard")

    casual = route_context_sections("你觉得最近怎么样", sections=[working, carryover], budget_chars=1200)
    ambiguous = route_context_sections("继续昨天那个", sections=[working, guard], budget_chars=1200)

    assert casual["route"] == "casual_continuity"
    assert any(item["section"] == "Working Memory" and "route_excludes_section" in item["reason_codes"] for item in casual["dropped_sections"])
    assert ambiguous["route"] == "ambiguous_recall"
    assert any(item["section"] == "Working Memory" and "route_excludes_section" in item["reason_codes"] for item in ambiguous["dropped_sections"])


def test_prefetch_context_router_apply_casual_does_not_treat_query_anchor_as_task(tmp_path):
    store = _store(tmp_path)
    item = build_working_item(seed=99, source_event_id="evt-noisy")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": item.updated_at,
            "items": [{**item.__dict__, "text": "Hindsight / hermes02 legacy provider-status note."}],
        },
    )

    context = build_prefetch(
        "我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？",
        budget_chars=2200,
        store=store,
        index=None,
        current_task_anchor=(
            "### Memory-OS Current Task Anchor\n"
            "- current task: 我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？"
        ),
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
    )

    assert "Current Foreground Task" not in context
    assert "Hindsight" not in context


def test_prefetch_low_clue_recall_injects_clarification_guard(tmp_path):
    store = _store(tmp_path)

    context = build_prefetch(
        "你还记得我之前跟你说过的一个设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
    )

    assert "### Recall Clarification Guard" in context
    assert "underspecified" in context
    assert "Do not answer as if one remembered item is certain." in context
    assert "ask for a keyword" in context


def test_prefetch_deictic_continue_uses_recall_guard_at_global_entry(tmp_path):
    store = _store(tmp_path)

    context = build_prefetch(
        "继续昨天那个。",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        low_clue_recall_config={"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
        memory_sources_config={"enabled": True},
    )
    source_record = (tmp_path / "memory-os" / "system" / "memory_sources.jsonl").read_text(encoding="utf-8")

    assert "### Recall Clarification Guard" in context
    assert "Do not answer as if one remembered item is certain." in context
    assert '"route": "ambiguous_recall"' in source_record
    assert '"query_class": "ambiguous_recall"' in source_record


def test_prefetch_deictic_continue_without_punctuation_uses_recall_guard_even_with_anchor(tmp_path):
    store = _store(tmp_path)

    context = build_prefetch(
        "继续刚才那个",
        budget_chars=2200,
        store=store,
        index=None,
        current_task_anchor="Current task: inspect ComfyUI layout_report.json.",
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        low_clue_recall_config={"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
        memory_sources_config={"enabled": True},
    )
    source_record = (tmp_path / "memory-os" / "system" / "memory_sources.jsonl").read_text(encoding="utf-8")

    assert "### Recall Clarification Guard" in context
    assert "### Current Foreground Task" not in context
    assert '"route": "ambiguous_recall"' in source_record
    assert '"router_applied": true' in source_record


def test_prefetch_context_router_apply_diagnostic_does_not_double_wrap_context(tmp_path):
    store = _store(tmp_path)

    context = build_prefetch(
        "当前记忆架构是什么？",
        budget_chars=2200,
        store=store,
        index=None,
        runtime_facts={"provider": "memory_os", "prefetch_mode": "indexed"},
        current_task_anchor="### Memory-OS Current Task Anchor\n- current task: 当前记忆架构是什么？",
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
    )

    assert context.count("## Memory-OS Context") == 1
    assert context.count("### Diagnostic Grounding") == 1
    assert "provider: memory_os" in context


def test_context_router_cli_dry_run_outputs_json_and_does_not_write_store(tmp_path, monkeypatch, capsys):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="")
    store = MemoryOSStore(roots)
    store.initialize()
    item = build_working_item(seed=94, source_event_id="evt-cli")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": item.updated_at,
            "items": [{**item.__dict__, "text": "ComfyUI plugin install is active."}],
        },
    )
    before_audit = roots.audit_path.read_text(encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)

    result = memory_os_command(
        parser.parse_args(
            [
                "context-router",
                "dry-run",
                "--query",
                "帮我继续安装 ComfyUI 插件",
                "--current-task-anchor",
                "Current task: install ComfyUI plugin.",
            ]
        )
    )
    output = json.loads(capsys.readouterr().out)
    after_audit = roots.audit_path.read_text(encoding="utf-8")

    assert result == 0
    assert output["schema_version"] == "memory-os.context_router.v0"
    assert output["mode"] == "dry_run"
    assert output["route"] == "active_task"
    assert before_audit == after_audit
