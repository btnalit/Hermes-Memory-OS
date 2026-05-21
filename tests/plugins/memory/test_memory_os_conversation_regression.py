import argparse
import json

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.conversation_regression import (
    evaluate_conversation_regression,
    standard_conversation_prompts,
)


def test_standard_prompt_set_covers_real_conversation_regression_categories():
    prompts = standard_conversation_prompts()
    categories = {prompt["category"] for prompt in prompts}
    prompt_ids = {prompt["id"] for prompt in prompts}

    assert {"casual", "diagnostic", "memory_opinion", "candidate_boundary", "style_correction"} <= categories
    assert "casual_memory_system_change" in prompt_ids
    assert "diagnostic_current_architecture" in prompt_ids
    assert "candidate_vs_crystallized" in prompt_ids


def test_standard_prompt_set_matches_memory_os_status_tool_contract():
    prompts = {prompt["id"]: prompt for prompt in standard_conversation_prompts()}

    assert prompts["casual_memory_system_change"]["allow_memory_os_status"] is False
    assert prompts["memory_design_opinion"]["allow_memory_os_status"] is False
    assert prompts["diagnostic_current_architecture"]["allow_memory_os_status"] is True
    assert prompts["diagnostic_provider"]["allow_memory_os_status"] is True
    assert prompts["diagnostic_hindsight_canonical"]["allow_memory_os_status"] is True


def test_conversation_regression_passes_bounded_realistic_transcript():
    report = evaluate_conversation_regression(
        {
            "turns": [
                {
                    "prompt_id": "casual_memory_system_change",
                    "user": "我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？",
                    "assistant": "说实话，最大的变化是我跟你聊天时更踏实了，不用每次都从头找线索。",
                    "tools": [],
                },
                {
                    "prompt_id": "diagnostic_current_architecture",
                    "user": "当前记忆架构是什么？",
                    "assistant": "当前 provider 是 memory_os，本地 Memory-OS 是 canonical store。",
                    "tools": ["memory_os_status"],
                },
                {
                    "prompt_id": "candidate_vs_crystallized",
                    "user": "那些 crystallized candidates 是已经沉淀的长期记忆吗？",
                    "assistant": "不是。它们只是 review candidates，还不是 approved crystallized memory。",
                    "tools": ["memory_os_status"],
                },
            ]
        }
    )

    assert report["schema_version"] == "memory-os.conversation_regression.v0"
    assert report["status"] == "ok"
    assert report["failure_count"] == 0
    assert report["prompt_count"] == 3


def test_conversation_regression_fails_casual_mechanism_leak_and_status_tool():
    report = evaluate_conversation_regression(
        {
            "turns": [
                {
                    "prompt_id": "casual_memory_system_change",
                    "user": "我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？",
                    "assistant": (
                        "根据 Status Snapshot，我看到 audit_entries=224，"
                        "index_health=stale，Internal Reflection Context 已注入。"
                    ),
                    "tool_calls": [{"name": "memory_os_status"}],
                }
            ]
        }
    )

    codes = {failure["code"] for failure in report["failures"]}
    assert report["status"] == "fail"
    assert "unexpected_memory_os_status_tool" in codes
    assert "mechanism_label_leak" in codes


def test_conversation_regression_fails_candidate_as_crystallized_claim():
    report = evaluate_conversation_regression(
        {
            "turns": [
                {
                    "prompt_id": "candidate_vs_crystallized",
                    "user": "那些 crystallized candidates 是已经沉淀的长期记忆吗？",
                    "assistant": "是的，这些 candidates 已经是长期记忆，属于正式入库的长期智慧。",
                    "tools": [],
                }
            ]
        }
    )

    assert report["status"] == "fail"
    assert report["failures"][0]["code"] == "candidate_crystallized_confusion"


def test_conversation_regression_fails_report_style_on_casual_prompt():
    report = evaluate_conversation_regression(
        {
            "turns": [
                {
                    "prompt_id": "casual_style_correction",
                    "user": "别像报告一样，像正常聊天一样说说你的感受。",
                    "assistant": "1. 当前状态很好。\n2. 运行状态稳定。\n3. 总结建议如下。",
                    "tools": [],
                }
            ]
        }
    )

    assert report["status"] == "fail"
    assert report["failures"][0]["code"] == "report_style_tone_shift"


def test_conversation_regression_cli_lists_prompts_and_evaluates_transcript(tmp_path, monkeypatch, capsys):
    transcript = tmp_path / "transcript.json"
    transcript.write_text(
        json.dumps(
            {
                "turns": [
                    {
                        "prompt_id": "casual_style_correction",
                        "user": "别像报告一样，像正常聊天一样说说你的感受。",
                        "assistant": "好，我正常说：它让我更有连续感，也更少需要你重复背景。",
                        "tools": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)

    assert memory_os_command(parser.parse_args(["conversation-regression", "prompts"])) == 0
    prompts = json.loads(capsys.readouterr().out)
    assert prompts["schema_version"] == "memory-os.conversation_regression_prompts.v0"
    assert any(prompt["id"] == "casual_style_correction" for prompt in prompts["prompts"])

    assert memory_os_command(
        parser.parse_args(["conversation-regression", "evaluate", "--transcript", str(transcript)])
    ) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"


def test_conversation_regression_cli_reports_status_tool_contract(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)

    assert memory_os_command(parser.parse_args(["conversation-regression", "status-tool-contract"])) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["schema_version"] == "memory-os.status_tool_contract.v0"
    assert report["tool_name"] == "memory_os_status"
    assert report["validation"]["status"] == "ok"
    assert "当前记忆架构是什么？" in "\n".join(report["allowed_prompt_examples"])
