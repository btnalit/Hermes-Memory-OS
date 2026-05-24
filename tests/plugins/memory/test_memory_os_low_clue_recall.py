import argparse
import json

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.fixtures import build_event, build_working_item
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.low_clue_recall import build_low_clue_recall_report, low_clue_judge_availability
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
