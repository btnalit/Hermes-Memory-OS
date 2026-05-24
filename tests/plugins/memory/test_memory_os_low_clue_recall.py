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
