from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json

from scripts import memory_os_expression_feedback_prompt as expression_prompt
from scripts import memory_os_memory_sources_feedback_prompt as memory_sources_prompt
from scripts import memory_os_proposal_followups_ops_gate as proposal_followups


def _capture(func) -> str:
    buffer = StringIO()
    with redirect_stdout(buffer):
        assert func() == 0
    return buffer.getvalue()


def test_expression_feedback_prompt_skips_silent_outcome(monkeypatch):
    monkeypatch.setattr(
        expression_prompt,
        "_run_json",
        lambda _command: {
            "status": "ok",
            "existing_feedback": {"count": 0},
            "latest_outcome": {
                "outcome_silent": True,
                "expression_preview": "[SILENT]",
                "action_tokens": {"like_expression": "oa_like"},
            },
        },
    )

    assert _capture(expression_prompt.main) == ""


def test_expression_feedback_prompt_skips_already_rated_outcome(monkeypatch):
    monkeypatch.setattr(
        expression_prompt,
        "_run_json",
        lambda _command: {
            "status": "ok",
            "existing_feedback": {"count": 1},
            "latest_outcome": {
                "outcome_silent": False,
                "expression_preview": "quiet presence",
                "action_tokens": {"like_expression": "oa_like"},
            },
        },
    )

    assert _capture(expression_prompt.main) == ""


def test_expression_feedback_prompt_renders_unrated_non_silent_outcome(monkeypatch):
    monkeypatch.setattr(
        expression_prompt,
        "_run_json",
        lambda _command: {
            "status": "ok",
            "existing_feedback": {"count": 0},
            "latest_outcome": {
                "outcome_silent": False,
                "expression_preview": "quiet presence",
                "action_tokens": {"like_expression": "oa_like"},
            },
        },
    )

    output = _capture(expression_prompt.main)

    assert "memory feedback oa_like like_expression" in output


def test_memory_sources_feedback_prompt_skips_already_rated_source(monkeypatch):
    monkeypatch.setattr(
        memory_sources_prompt,
        "_run_json",
        lambda _command: {
            "status": "ok",
            "existing_feedback": {"count": 1},
            "latest_memory_source": {
                "action_tokens": {"mark_feedback": "oa_feedback"},
            },
        },
    )

    assert _capture(memory_sources_prompt.main) == ""


def test_memory_sources_feedback_prompt_help_does_not_require_hermes(monkeypatch):
    def fail_run_json(_command):
        raise AssertionError("_run_json should not be called for --help")

    monkeypatch.setattr(memory_sources_prompt, "_run_json", fail_run_json)

    output = _capture(lambda: memory_sources_prompt.main(["--help"]))

    assert "MemorySources feedback prompt" in output


def test_memory_sources_feedback_prompt_renders_unrated_source(monkeypatch):
    monkeypatch.setattr(
        memory_sources_prompt,
        "_run_json",
        lambda _command: {
            "status": "ok",
            "existing_feedback": {"count": 0},
            "latest_memory_source": {
                "action_tokens": {"mark_feedback": "oa_feedback"},
                "owner_utterance_examples": ["memory feedback oa_feedback useful"],
                "source_classes": ["event"],
                "route": "casual_continuity",
                "selected_count": 1,
                "selected_chars_total": 100,
            },
        },
    )

    output = _capture(memory_sources_prompt.main)

    assert output.startswith("OWNER_MESSAGE_BEGIN")
    assert "OWNER_MESSAGE_BEGIN" in output
    assert "本次只问这一轮来源质量" in output
    assert "请只选一个判断，不需要解释" in output
    assert "有帮助、缺上下文、太机制化、要更具体" in output
    assert "Do not write a cron run report" not in output
    assert "Internal handling" not in output
    assert "Rating mapping" not in output
    assert "action_token" not in output
    assert "oa_feedback" not in output
    assert "memory feedback oa_feedback useful" not in output


def test_memory_sources_feedback_prompt_status_json_reports_duplicate_suppression(monkeypatch):
    def fake_run_json(command):
        if command[:5] == ["hermes", "memory-os-agent-os", "review", "surface", "--operation"]:
            return {
                "status": "ok",
                "raw_body_included": False,
                "existing_feedback": {"count": 1},
                "latest_memory_source": {
                    "id": "msrc_latest",
                    "action_tokens": {"mark_feedback": "oa_feedback"},
                },
            }
        if command[:4] == ["hermes", "memory-os-agent-os", "memory-sources", "stats"]:
            return {"schema_version": "memory-os.memory_sources_stats.v0", "total_feedback_count": 4}
        raise AssertionError(command)

    monkeypatch.setattr(memory_sources_prompt, "_run_json", fake_run_json)

    output = _capture(lambda: memory_sources_prompt.main(["--status-json"]))
    report = json.loads(output)

    assert report["schema_version"] == "memory-os.memory_sources_feedback_prompt_status.v0"
    assert report["prompt_status"] == "skipped"
    assert report["skip_reason"] == "already_feedback_for_latest_source"
    assert report["prompt_would_render"] is False
    assert report["latest_memory_source_id"] == "msrc_latest"
    assert report["existing_feedback_count"] == 1
    assert report["total_feedback_count"] == 4
    assert report["canary_remaining"] == 16
    assert report["actual_send"] is False
    assert report["actual_execute"] is False


def test_memory_sources_feedback_prompt_status_json_reports_ready(monkeypatch):
    def fake_run_json(command):
        if command[:5] == ["hermes", "memory-os-agent-os", "review", "surface", "--operation"]:
            return {
                "status": "ok",
                "existing_feedback": {"count": 0},
                "latest_memory_source": {
                    "memory_source_id": "msrc_next",
                    "action_tokens": {"mark_feedback": "oa_feedback"},
                },
            }
        if command[:4] == ["hermes", "memory-os-agent-os", "memory-sources", "stats"]:
            return {"schema_version": "memory-os.memory_sources_stats.v0", "total_feedback_count": 19}
        raise AssertionError(command)

    monkeypatch.setattr(memory_sources_prompt, "_run_json", fake_run_json)

    output = _capture(lambda: memory_sources_prompt.main(["--status-json"]))
    report = json.loads(output)

    assert report["prompt_status"] == "ready"
    assert report["prompt_would_render"] is True
    assert report["latest_memory_source_id"] == "msrc_next"
    assert report["canary_remaining"] == 1
    assert report["canary_complete"] is False


def test_memory_sources_feedback_prompt_status_json_counts_feedback_ledger(monkeypatch, tmp_path):
    ledger = tmp_path / "memory_sources_feedback.jsonl"
    ledger.write_text('{"rating":"useful"}\n\n{"rating":"missing_context"}\n', encoding="utf-8")

    def fake_run_json(command):
        if command[:5] == ["hermes", "memory-os-agent-os", "review", "surface", "--operation"]:
            return {
                "status": "ok",
                "existing_feedback": {"count": 0},
                "latest_memory_source": {
                    "memory_source_id": "msrc_next",
                    "action_tokens": {"mark_feedback": "oa_feedback"},
                },
            }
        if command[:4] == ["hermes", "memory-os-agent-os", "memory-sources", "stats"]:
            return {
                "schema_version": "memory-os.memory_sources_stats.v0",
                "feedback_count": 1,
                "feedback_ledger_path": str(ledger),
            }
        raise AssertionError(command)

    monkeypatch.setattr(memory_sources_prompt, "_run_json", fake_run_json)

    output = _capture(lambda: memory_sources_prompt.main(["--status-json"]))
    report = json.loads(output)

    assert report["total_feedback_count"] == 2
    assert report["total_feedback_count_source"] == "feedback_ledger_line_count"
    assert report["canary_remaining"] == 18


def test_proposal_followups_ops_gate_helper_rejects_execution_ticket(monkeypatch):
    monkeypatch.setattr(
        proposal_followups,
        "_run_json",
        lambda _command: {
            "status": "ok",
            "actual_execute": False,
            "execution_ticket_created": True,
        },
    )

    buffer = StringIO()
    with redirect_stdout(buffer):
        assert proposal_followups.main() == 2


def test_proposal_followups_ops_gate_helper_accepts_report_only(monkeypatch):
    captured = {}

    def fake_run(command):
        captured["command"] = command
        return {
            "status": "ok",
            "actual_execute": False,
            "execution_ticket_created": False,
            "eligible_count": 0,
        }

    monkeypatch.setattr(proposal_followups, "_run_json", fake_run)

    buffer = StringIO()
    with redirect_stdout(buffer):
        assert proposal_followups.main() == 0

    assert "--ops-gate" in captured["command"]
    assert "--all-pending" in captured["command"]
    assert "--apply" in captured["command"]
    assert "hermes_cron" in captured["command"]
