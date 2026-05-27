from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO

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

    assert "MemorySources feedback request" in output
    assert "memory feedback oa_feedback useful" in output


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
