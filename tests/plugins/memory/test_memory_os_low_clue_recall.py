import argparse
import json

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.fixtures import build_event, build_working_item
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.low_clue_recall import build_low_clue_recall_report, low_clue_judge_availability
from plugins.memory.memory_os.memory_sources import append_memory_source_record
import plugins.memory.memory_os.low_clue_recall as low_clue_recall_module
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _write_working(store, texts):
    items = []
    for index, text in enumerate(texts, start=1):
        item = build_working_item(seed=700 + index, source_event_id=f"evt-working-{index}")
        items.append({**item.__dict__, "text": text})
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": "2026-05-24T00:00:00+00:00",
            "items": items,
        },
    )


def _append_event(store, *, seed, summary):
    event = build_event(seed=seed)
    store.append_event(EventEnvelope.from_dict({**event, "summary": summary}))


def test_low_clue_recall_asks_choice_when_multiple_plausible_candidates(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "n8n 与 AI 智能体分工：n8n 做流程外壳，智能体做判断。",
            "互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。",
            "ComfyUI 视频链路：layout_report.json 失败时先查 composition。",
        ],
    )

    report = build_low_clue_recall_report("你还记得我之前跟你说过的一个设计吗？", store=store, limit=4)

    assert report["schema_version"] == "memory-os.low_clue_recall.v0"
    assert report["decision"] == "ask_choice"
    assert report["candidate_count"] >= 3
    labels = json.dumps(report["candidates"], ensure_ascii=False)
    assert "n8n" in labels
    assert "互联网数据采集" in labels
    assert "ComfyUI" in labels
    assert report["llm_judge"]["status"] == "disabled"


def test_low_clue_recall_merges_duplicate_topic_candidates(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "n8n 与 AI 智能体协作方案：n8n 做编排，agent 做判断。",
            "n8n 与 AI 智能体分工：n8n 管流程，agent 管生成。",
            "互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。",
            "ComfyUI 视频渲染问题：内容层没有进入 composition。",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    labels = [candidate["label"] for candidate in report["candidates"]]
    assert sum(1 for label in labels if "n8n" in label.lower()) == 1
    assert any(candidate.get("merged_candidate_count", 1) >= 2 for candidate in report["candidates"])
    assert report["candidate_quality"]["raw_candidate_count"] > report["candidate_quality"]["cluster_count"]
    assert report["candidate_quality"]["merged_duplicates"] >= 1


def test_low_clue_recall_uses_source_diversity_when_recent_working_would_monopolize(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [f"项目 {index} 工作线索：这是第 {index} 个 working 主题。" for index in range(40)],
    )
    _append_event(store, seed=901, summary="互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。")
    _append_event(store, seed=902, summary="公开材料写作：先讲 Memory-OS 解决什么问题。")

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    source_classes = {candidate["source_class"] for candidate in report["candidates"]}
    assert "working" in source_classes
    assert "event" in source_classes
    assert report["candidate_quality"]["source_distribution"]["event"] == 2


def test_low_clue_recall_keeps_memory_sources_candidate_when_working_would_monopolize(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [f"项目 {index} 工作线索：这是第 {index} 个 working 主题。" for index in range(40)],
    )
    append_memory_source_record(
        store.roots,
        {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_test_architecture",
            "created_at": "2026-05-24T00:00:00Z",
            "route": "ambiguous_recall",
            "query_class": "ambiguous_recall",
            "selected": [
                {"heading": "Recall Clarification Guard", "source_class": "recall_guard", "chars": 100},
                {"heading": "Internet collection architecture", "source_class": "event", "chars": 100},
            ],
        },
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    source_classes = {candidate["source_class"] for candidate in report["candidates"]}
    assert "working" in source_classes
    assert "memory_sources" in source_classes
    assert report["candidate_quality"]["diversity_applied"] is True


def test_low_clue_recall_skips_memory_sources_with_only_internal_projection_headings(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。",
            "n8n 与 AI 智能体分工：n8n 做流程外壳，智能体做判断。",
        ],
    )
    append_memory_source_record(
        store.roots,
        {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_internal_only",
            "created_at": "2026-05-24T00:00:00Z",
            "route": "ambiguous_recall",
            "query_class": "ambiguous_recall",
            "selected": [
                {"heading": "Recall Clarification Guard", "source_class": "recall_guard", "chars": 100},
                {"heading": "Current Foreground Task", "source_class": "foreground", "chars": 100},
            ],
        },
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)
    labels = [str(candidate["label"]) for candidate in report["candidates"]]

    assert all("ambiguous_recall" not in label for label in labels)
    assert all("Current Foreground Task" not in label for label in labels)
    assert "memory_sources" not in {candidate["source_class"] for candidate in report["candidates"]}


def test_low_clue_recall_applies_recent_correction_penalty_without_long_term_write(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "n8n 与 AI 智能体协作方案：n8n 做编排，agent 做判断。",
            "Make 自动化评估：适合轻量流程串联。",
            "互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。",
        ],
    )
    _append_event(store, seed=903, summary="User: 不对，是不是少了？ | Assistant: 我刚才漏掉了其他候选。")

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    assert report["candidate_quality"]["feedback_penalty_applied"] is True
    assert any("recent_correction_penalty" in candidate["reason_codes"] for candidate in report["candidates"])
    assert report["boundaries"]["actual_crystallized_approval"] is False


def test_low_clue_recall_normalizes_transcript_fragments_into_topic_titles(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            (
                "User: 你还记得昨天那个方案吗？ | Assistant: 记得，应该是 Project Atlas "
                "数据同步架构：入口、调度、解析、校验、存储。后续可以继续展开。"
            ),
            (
                "User: 不是这个，是另一个。 | Assistant: 那更像 Project Atlas 数据同步分层："
                "source adapter、scheduler、validator、serving API。"
            ),
            "Render pipeline composition fallback：template layer missing, only preview visual moved.",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    labels = [candidate["label"] for candidate in report["candidates"]]
    assert report["candidate_quality"]["title_normalization_applied"] is True
    assert any("Project Atlas" in label for label in labels)
    assert all("User:" not in label and "Assistant:" not in label and "|" not in label for label in labels)
    assert all(len(label) <= 96 for label in labels)


def test_low_clue_recall_preserves_distinctive_entity_in_normalized_title(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "make / 自动化 / Claude / AI / app 背景：X9Flow 与智能体协作方案，流程外壳负责触发、重试、回滚。",
            "make / 自动化 / Claude / AI / app 继续：X9Flow 与 AI 智能体分工，编排层做确定性执行。",
            "make / 自动化 / Claude / AI / app 评估：X9Flow 适合 webhook、审批、通知、日志审计。",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)
    labels = [candidate["label"] for candidate in report["candidates"]]

    assert any("X9Flow" in label for label in labels)
    assert all("make / 自动化 / Claude / AI / app" not in label for label in labels)


def test_low_clue_recall_llm_judge_receives_normalized_titles(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            (
                "User: 继续上次那个。 | Assistant: 上次是 Project Borealis 采集流水线："
                "入口、队列、解析、质量校验、审计。"
            ),
            "Project Borealis collector layering：task spec, fetcher, parser, validator.",
            "Episode render gate：composition inspection before final video export.",
        ],
    )
    captured = {}

    def runner(payload, config):
        captured["payload"] = payload
        return {
            "status": "ok",
            "selected_candidate_id": "",
            "confidence": 0.2,
            "reason_codes": ["ambiguous_query"],
        }

    report = build_low_clue_recall_report(
        "继续昨天那个。",
        store=store,
        limit=4,
        config={"enabled": True, "llm_judge": {"enabled": True, "mode": "report_only"}},
        llm_runner=runner,
    )

    assert report["decision"] == "ask_choice"
    judge_labels = [candidate["label"] for candidate in captured["payload"]["candidates"]]
    assert any("Project Borealis" in label for label in judge_labels)
    assert all("User:" not in label and "Assistant:" not in label and "|" not in label for label in judge_labels)
    assert captured["payload"]["query_features"]["low_clue"] is True
    assert captured["payload"]["query_features"]["generic_terms"]
    assert "继续昨天那个。" not in json.dumps(captured["payload"], ensure_ascii=False)


def test_low_clue_recall_llm_judge_receives_bounded_query_features_without_raw_query(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "Project Borealis collector layering：task spec, fetcher, parser, validator.",
            "Episode render gate：composition inspection before final video export.",
        ],
    )
    captured = {}

    def runner(payload, config):
        captured["payload"] = payload
        return {
            "status": "ok",
            "selected_candidate_id": "",
            "confidence": 0.2,
            "reason_codes": ["bounded_query_features"],
        }

    query = "继续 Project Borealis 那个。api_key=secret C:\\Users\\owner\\private.txt"
    build_low_clue_recall_report(
        query,
        store=store,
        limit=4,
        config={"enabled": True, "llm_judge": {"enabled": True, "mode": "report_only"}},
        llm_runner=runner,
    )

    features = captured["payload"]["query_features"]
    payload_text = json.dumps(captured["payload"], ensure_ascii=False)
    assert features["schema_version"] == "memory-os.low_clue_query_features.v0"
    assert features["has_specific_terms"] is True
    assert features["low_clue"] is False
    assert "project" in features["specific_terms"]
    assert "borealis" in features["specific_terms"]
    assert "api_key=secret" not in payload_text
    assert "private.txt" not in payload_text
    assert query not in payload_text


def test_low_clue_recall_filters_system_note_candidates_and_keeps_titles_short(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "[System note: Your previous turn was interrupted before you could process the last tool result(...",
            "Review the conversation above and consider saving to memory if appropriate. Focus on stable user preferences.",
            "Project Cygnus sync architecture: intake queue, parser, validator, audit ledger.",
            "Render quality gate: composition inspection before export.",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    labels = [candidate["label"] for candidate in report["candidates"]]
    assert all("System note" not in label and "previous turn" not in label for label in labels)
    assert all("Review the conversation" not in label and "saving to memory" not in label for label in labels)
    assert all(len(label) <= 96 for label in labels)
    assert any("Project Cygnus" in label for label in labels)


def test_low_clue_recall_filters_non_topic_transcript_artifact_titles(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "[The user sent an attachment~ Here's what I can see in the preview panel.]",
            "Project Delta data intake architecture: source registry, fetch queue, parser, validator.",
            "Render pipeline composition gate: inspect template, data binding, and export readiness.",
            "Automation orchestration boundary: deterministic flow runner, agent judgment, audit trail.",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    labels = [candidate["label"] for candidate in report["candidates"]]
    assert report["decision"] == "ask_choice"
    assert report["candidate_quality"]["filtered_non_topic_title_count"] == 1
    assert all("The user sent" not in label and "Here's what I can see" not in label for label in labels)
    assert any("Project Delta" in label for label in labels)


def test_low_clue_recall_compresses_sentence_titles_for_choice_buttons(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "Project Orion memory planning: scoring, attribution, retention, owner feedback.",
            (
                "agentmemory is not something to copy wholesale, but a few pieces are useful for "
                "the current Memory-OS design: consent, relevant source attribution, and memory "
                "management review."
            ),
            "Workflow automation boundary: deterministic runner, model judgment, rollback, audit.",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    labels = [candidate["label"] for candidate in report["candidates"]]
    assert report["decision"] == "ask_choice"
    assert any("agentmemory" in label for label in labels)
    assert all(len(label) <= 40 for label in labels)
    assert all("not something to copy wholesale" not in label for label in labels)


def test_low_clue_recall_removes_artifact_paths_from_titles(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            (
                "Asset preview completed: MEDIA:/workspace/output/topic_card_00001.png "
                "shows the visual style direction for the tutorial scene."
            ),
            "Tutorial evidence card design: readable UI screenshot, compact caption, source proof.",
            "Project Lyra automation architecture: trigger, planner, executor, audit trail.",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    labels = [candidate["label"] for candidate in report["candidates"]]
    assert all("MEDIA:" not in label and ".png" not in label and "/workspace/" not in label for label in labels)
    assert any("Tutorial" in label or "evidence" in label for label in labels)


def test_low_clue_recall_counts_merged_event_source_as_selected_diversity(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "Project Epsilon recall architecture: candidate clustering, source quota, clarification guard.",
            "Project Epsilon recall routing: candidate clustering, source quota, owner clarification.",
            "Render pipeline quality gate: composition inspection before export.",
        ],
    )
    _append_event(
        store,
        seed=904,
        summary="Project Epsilon recall architecture: candidate clustering and source diversity validation.",
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    selected_distribution = report["candidate_quality"]["selected_source_distribution"]
    labels = [candidate["label"] for candidate in report["candidates"]]
    assert report["candidate_quality"]["diversity_applied"] is True
    assert selected_distribution["working"] >= 1
    assert selected_distribution["event"] >= 1
    assert any("Epsilon" in label for label in labels)


def test_low_clue_recall_forces_lower_ranked_merged_event_source_into_choices(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "Epsilon diversity event coverage.",
            "Alpha routing evidence archive.",
            "Alpha routing evidence ledger.",
            "Alpha archive ledger.",
            "Beta digest archive ledger.",
            "Beta digest archive summary.",
            "Beta ledger summary.",
            "Gamma cadence scheduler monitor.",
            "Gamma scheduler monitor.",
            "Gamma cadence skipgate.",
            "Delta scoring maturity quality.",
            "Delta scoring quality.",
            "Delta maturity dimensions.",
        ],
    )
    _append_event(
        store,
        seed=906,
        summary="Epsilon diversity event coverage.",
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    selected_distribution = report["candidate_quality"]["selected_source_distribution"]
    labels = [candidate["label"] for candidate in report["candidates"]]
    assert report["candidate_quality"]["diversity_applied"] is True
    assert selected_distribution["event"] >= 1
    assert any("Epsilon" in label for label in labels)


def test_low_clue_recall_source_diversity_slot_uses_merged_source_classes():
    selected = [
        {"candidate_id": "a", "source_class": "working", "source_classes": ["working"], "score": 0.5},
        {"candidate_id": "b", "source_class": "working", "source_classes": ["working"], "score": 0.4},
    ]
    clusters = [
        *selected,
        {
            "candidate_id": "c",
            "source_class": "working",
            "source_classes": ["working", "event"],
            "score": 0.35,
            "reason_codes": [],
        },
    ]

    diversified, changed = low_clue_recall_module._ensure_source_diversity_slot(selected, clusters, limit=2)

    assert changed is True
    assert any("event" in candidate.get("source_classes", []) for candidate in diversified)


def test_low_clue_recall_preserves_duplicate_label_sources_across_collectors(tmp_path):
    store = _store(tmp_path)
    topic = "Project Zeta recall contract: source diversity, topic eligibility, owner clarification."
    _write_working(store, [topic, "Render pipeline quality gate: composition inspection before export."])
    _append_event(store, seed=905, summary=topic)

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    selected_distribution = report["candidate_quality"]["selected_source_distribution"]
    zeta = next(candidate for candidate in report["candidates"] if "zeta" in candidate["cluster_terms"])
    assert "working" in zeta["source_classes"]
    assert "event" in zeta["source_classes"]
    assert selected_distribution["working"] >= 1
    assert selected_distribution["event"] >= 1


def test_low_clue_recall_removes_artifact_paths_even_when_single_candidate(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            (
                "Asset preview completed: MEDIA:/workspace/output/topic_card_00001.png "
                "shows visual style direction for tutorial scene."
            ),
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    assert report["candidate_count"] == 1
    label = report["candidates"][0]["label"]
    assert "MEDIA:" not in label and ".png" not in label and "/workspace/" not in label
    assert "tutorial" in label.lower()


def test_low_clue_recall_filters_self_review_memory_prompts(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "Review the conversation above and consider saving to memory if appropriate. Focus on stable user preferences.",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    assert report["decision"] == "ask_keyword"
    assert report["candidate_count"] == 0


def test_low_clue_recall_filters_owner_review_command_artifacts(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "approve A3",
            "R2, R3, or R4?",
            "What should I do with oa_10521e52d56f93 -- approve, reject, allow, or feedback?",
            "Assistant / 系统",
            "Owner approval workflow architecture: digest tokens, structured tool calls, audit ledger.",
            "互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    labels = [candidate["label"] for candidate in report["candidates"]]
    serialized = json.dumps(labels, ensure_ascii=False)
    assert report["candidate_quality"]["filtered_non_topic_title_count"] >= 4
    assert "approve A3" not in serialized
    assert "R2, R3" not in serialized
    assert "oa_10521e52d56f93" not in serialized
    assert "Assistant / 系统" not in serialized
    assert any("approval" in label.lower() and "workflow" in label.lower() for label in labels)
    assert any("互联网数据采集" in label for label in labels)


def test_low_clue_recall_falls_back_to_topic_terms_for_sentence_like_titles(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "each visual should feel like a selected evidence screenshot that supports the tutorial scene.",
            "Visual evidence screenshot style: readable interface, compact annotation, source proof.",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    label = report["candidates"][0]["label"]
    assert not label.lower().startswith("each visual should")
    assert "visual" in label.lower()
    assert len(label) <= 96


def test_low_clue_recall_prefers_user_topic_over_internal_diagnostic_terms(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            (
                "User: 别像报告一样，像正常聊天一样说说你的感受。 | "
                "Assistant: 现在这种感觉变了，我知道在 Audit Entries 里保留了更多记忆。"
            ),
            (
                "User: 老实说，我们现在这套记忆系统强大么？你用着的感觉如何？ | "
                "Assistant: 强在 memory_os canonical store index health audit 链路和 provider status。"
            ),
            "互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。",
        ],
    )

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    labels = [candidate["label"] for candidate in report["candidates"]]
    assert any("记忆系统强大" in label or "用着的感觉" in label for label in labels)
    assert "记忆" not in labels
    assert all("canonical / store / index" not in label.lower() for label in labels)


def test_low_clue_recall_direct_resume_when_keyword_confidence_is_clear(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "n8n 与 AI 智能体分工：n8n 做流程外壳，智能体做判断。",
            "互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。",
            "ComfyUI 视频链路：layout_report.json 失败时先查 composition。",
        ],
    )

    report = build_low_clue_recall_report("我们之前那个互联网采集系统设计继续说", store=store, limit=4)

    assert report["decision"] == "direct_resume"
    assert report["candidates"][0]["source_class"] == "working"
    assert "互联网数据采集" in report["candidates"][0]["label"]
    assert report["candidates"][0]["score"] >= 0.75


def test_low_clue_recall_asks_for_keyword_when_no_candidates(tmp_path):
    store = _store(tmp_path)

    report = build_low_clue_recall_report("继续昨天那个。", store=store, limit=4)

    assert report["decision"] == "ask_keyword"
    assert report["candidate_count"] == 0
    assert "no_candidates" in report["reason_codes"]


def test_low_clue_recall_cli_dry_run_is_bounded_and_read_only(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _write_working(store, ["互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。"])
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    before = store.roots.audit_path.read_text(encoding="utf-8")
    parser = argparse.ArgumentParser()
    register_cli(parser)

    result = memory_os_command(
        parser.parse_args(["low-clue-recall", "dry-run", "--query", "继续那个互联网设计"])
    )
    output = json.loads(capsys.readouterr().out)
    after = store.roots.audit_path.read_text(encoding="utf-8")

    assert result == 0
    assert output["schema_version"] == "memory-os.low_clue_recall.v0"
    assert output["decision"] == "direct_resume"
    assert "互联网数据采集" in json.dumps(output["candidates"], ensure_ascii=False)
    assert "继续那个互联网设计" not in json.dumps(output, ensure_ascii=False)
    assert before == after


def test_prefetch_low_clue_guard_includes_bounded_choices_when_enabled(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "n8n 与 AI 智能体分工：n8n 做流程外壳，智能体做判断。",
            "互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。",
        ],
    )

    context = build_prefetch(
        "你还记得我之前跟你说过的一个设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        low_clue_recall_config={"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
    )

    assert "### Recall Clarification Guard" in context
    assert "Plausible recall candidates" in context
    assert "n8n 与 AI 智能体分工" in context
    assert "互联网数据采集系统分层" in context
    assert "Working Memory" not in context


def test_prefetch_low_clue_guard_blocks_unclustered_tool_shortlists(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "n8n 与 AI 智能体分工：n8n 做流程外壳，智能体做判断。",
            "继续 n8n 与智能体方案：n8n 负责流程，智能体负责判断。",
            "继续 n8n 与 AI 智能体方案：自动化编排不等于智能体替代。",
        ],
    )

    context = build_prefetch(
        "继续昨天那个",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        low_clue_recall_config={"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
    )

    assert "### Recall Clarification Guard" in context
    assert "authoritative shortlist" in context
    assert "Do not create a competing shortlist from raw session_search/tool results." in context
    assert "merge duplicate variants into the existing candidate topics" in context
    assert "ask for a keyword instead of guessing" in context


def test_prefetch_high_confidence_low_clue_guard_allows_likely_resume(tmp_path):
    store = _store(tmp_path)
    _write_working(
        store,
        [
            "互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。",
            "n8n 与 AI 智能体分工：n8n 做流程外壳，智能体做判断。",
        ],
    )

    context = build_prefetch(
        "你还记得我之前跟你说过的互联网数据采集系统设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        low_clue_recall_config={"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
    )

    assert "### Recall Clarification Guard" in context
    assert "likely recall candidate" in context
    assert "state the likely match briefly" in context
    assert "Plausible recall candidates" not in context


def test_low_clue_recall_report_only_llm_judge_uses_injected_runner_without_changing_decision(tmp_path):
    store = _store(tmp_path)
    _write_working(store, ["互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。"])

    report = build_low_clue_recall_report(
        "继续那个互联网设计",
        store=store,
        limit=4,
        config={
            "enabled": True,
            "llm_judge": {
                "enabled": True,
                "mode": "report_only",
                "provider": "hermes_default",
                "model": None,
            },
        },
        llm_runner=lambda payload, cfg: {
            "status": "ok",
            "selected_candidate_id": payload["candidates"][0]["candidate_id"],
            "confidence": 0.91,
            "reason_codes": ["semantic_match"],
        },
    )

    assert report["decision"] == "direct_resume"
    assert report["llm_judge"]["status"] == "ok"
    assert report["llm_judge"]["mode"] == "report_only"
    assert report["llm_judge"]["selected_candidate_id"] == report["candidates"][0]["candidate_id"]


def test_low_clue_recall_bounded_vote_llm_judge_uses_injected_runner_without_changing_decision(tmp_path):
    store = _store(tmp_path)
    _write_working(store, ["互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。"])

    report = build_low_clue_recall_report(
        "继续那个互联网设计",
        store=store,
        limit=4,
        config={
            "enabled": True,
            "llm_judge": {
                "enabled": True,
                "mode": "bounded_vote",
                "provider": "hermes_default",
                "model": None,
            },
        },
        llm_runner=lambda payload, cfg: {
            "status": "no_match",
            "selected_candidate_id": "",
            "confidence": 0.0,
            "reason_codes": ["ambiguous_recall_low_clue"],
        },
    )

    assert report["decision"] == "direct_resume"
    assert report["llm_judge"]["status"] == "no_match"
    assert report["llm_judge"]["mode"] == "bounded_vote"
    assert report["llm_judge"]["selected_candidate_id"] == ""


def test_low_clue_recall_llm_judge_reports_resolved_runtime_model(tmp_path):
    store = _store(tmp_path)
    _write_working(store, ["互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。"])

    report = build_low_clue_recall_report(
        "继续那个互联网设计",
        store=store,
        limit=4,
        config={
            "enabled": True,
            "llm_judge": {
                "enabled": True,
                "mode": "report_only",
                "provider": "hermes_default",
                "model": None,
            },
        },
        llm_runner=lambda payload, cfg: {
            "status": "ok",
            "selected_candidate_id": payload["candidates"][0]["candidate_id"],
            "confidence": 0.8,
            "reason_codes": ["clear_match"],
            "resolved_provider": "deepseek",
            "resolved_model": "deepseek-v4-flash",
            "api_mode": "chat_completions",
        },
    )

    assert report["llm_judge"]["model"] == "deepseek-v4-flash"
    assert report["llm_judge"]["resolved_model"] == "deepseek-v4-flash"
    assert report["llm_judge"]["resolved_provider"] == "deepseek"
    assert report["llm_judge"]["api_mode"] == "chat_completions"


def test_run_hermes_default_judge_prechecks_runtime_and_classifies_empty_response(monkeypatch):
    monkeypatch.setattr(
        low_clue_recall_module,
        "low_clue_judge_availability",
        lambda config: {
            "available": True,
            "resolved_provider": "deepseek",
            "resolved_model": "deepseek-v4-flash",
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr(low_clue_recall_module, "_call_hermes_runtime_model", lambda prompt, config: "")

    result = low_clue_recall_module._run_hermes_default_judge(
        {
            "schema_version": "memory-os.low_clue_recall_judge_input.v0",
            "query_class": "ambiguous_recall",
            "candidates": [
                {
                    "candidate_id": "c1",
                    "label": "Project Borealis",
                    "source_class": "working",
                    "score": 0.8,
                    "reason_codes": ["topic_term"],
                }
            ],
        },
        {"enabled": True, "mode": "report_only", "provider": "hermes_default"},
    )

    assert result["status"] == "skipped"
    assert result["reason_codes"] == ["judge_empty_response"]
    assert result["resolved_model"] == "deepseek-v4-flash"
    assert result["api_mode"] == "chat_completions"


def test_low_clue_recall_prefetch_disables_report_only_judge_to_avoid_turn_latency(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _write_working(store, ["互联网数据采集系统分层：任务定义、调度、抓取、解析、校验、存储。"])
    calls = []

    def slow_runner(payload, cfg):
        calls.append(payload)
        return {"status": "ok", "selected_candidate_id": payload["candidates"][0]["candidate_id"]}
    monkeypatch.setattr(low_clue_recall_module, "_run_hermes_default_judge", slow_runner)

    context = build_prefetch(
        "你还记得我之前跟你说过的互联网数据采集系统设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        low_clue_recall_config={
            "enabled": True,
            "llm_judge": {
                "enabled": True,
                "mode": "report_only",
                "provider": "hermes_default",
            },
            "_llm_runner": slow_runner,
        },
    )

    assert "### Recall Clarification Guard" in context
    assert calls == []


def test_low_clue_judge_availability_degrades_for_unsupported_provider():
    report = low_clue_judge_availability(
        {
            "enabled": True,
            "llm_judge": {
                "enabled": True,
                "mode": "report_only",
                "provider": "custom-provider",
            },
        }
    )

    assert report["schema_version"] == "memory-os.low_clue_judge_availability.v0"
    assert report["available"] is False
    assert report["status"] == "unavailable"
    assert report["code"] == "unsupported_provider"
    assert report["degrades_to"] == "deterministic_fallback"


def test_low_clue_judge_availability_accepts_bounded_vote_mode(monkeypatch):
    monkeypatch.setattr(
        low_clue_recall_module,
        "_resolve_hermes_default_runtime",
        lambda config: {
            "ok": True,
            "api_mode": "chat_completions",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "credential_present": True,
        },
    )

    report = low_clue_judge_availability(
        {
            "enabled": True,
            "llm_judge": {
                "enabled": True,
                "mode": "bounded_vote",
                "provider": "hermes_default",
            },
        }
    )

    assert report["available"] is True
    assert report["status"] == "available"
    assert report["mode"] == "bounded_vote"
    assert report["resolved_model"] == "deepseek-v4-flash"


def test_status_and_doctor_report_low_clue_judge_unavailable_as_warning(tmp_path, monkeypatch, capsys):
    _store(tmp_path)
    save_config(
        {
            "low_clue_recall": {
                "enabled": True,
                "llm_judge": {
                    "enabled": True,
                    "mode": "report_only",
                    "provider": "custom-provider",
                },
            }
        },
        tmp_path,
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)

    assert memory_os_command(parser.parse_args(["status"])) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["low_clue_recall"]["judge_availability"]["available"] is False
    assert status["low_clue_recall"]["judge_availability"]["degrades_to"] == "deterministic_fallback"

    assert memory_os_command(parser.parse_args(["doctor"])) == 0
    doctor = json.loads(capsys.readouterr().out)
    findings = {item["code"]: item for item in doctor["findings"]}
    assert findings["low_clue_llm_judge_unavailable"]["severity"] == "warning"
    assert findings["low_clue_llm_judge_unavailable"]["details"]["degrades_to"] == "deterministic_fallback"
