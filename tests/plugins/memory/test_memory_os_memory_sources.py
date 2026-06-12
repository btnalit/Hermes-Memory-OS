import argparse
import json

from plugins.memory.memory_os.audit import read_audit_entries
from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.context_router import ContextSection
from plugins.memory.memory_os.fixtures import build_working_item
from plugins.memory.memory_os.memory_sources import (
    build_memory_source_record,
    filter_safe_source_ids,
    normalize_memory_sources_config,
    read_memory_source_records,
)
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION
from plugins.memory.memory_os.store import MemoryOSStore


def test_memory_sources_disabled_does_not_write_and_keeps_prefetch_output(tmp_path):
    store = _store(tmp_path)

    baseline = build_prefetch(
        "你还记得我之前跟你说过的一个设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
    )
    with_disabled = build_prefetch(
        "你还记得我之前跟你说过的一个设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        memory_sources_config={"enabled": False},
    )

    assert with_disabled == baseline
    assert not _ledger_path(tmp_path).exists()


def test_memory_sources_enabled_records_live_prefetch_metadata_without_private_text(tmp_path):
    store = _store(tmp_path)
    query = "你还记得我之前跟你说过的一个设计吗？"

    context = build_prefetch(
        query,
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        memory_sources_config={"enabled": True},
    )

    assert "Recall Clarification Guard" in context
    records = read_memory_source_records(store.roots, limit=10)
    assert len(records) == 1
    record = records[0]
    rendered = json.dumps(record, ensure_ascii=False)
    assert record["schema_version"] == "memory-os.memory_sources.v0"
    assert record["query_class"] == "ambiguous_recall"
    assert record["route"] == "ambiguous_recall"
    assert record["router_applied"] is True
    assert record["context_router_routes_applied"] == ["all"]
    assert record["selected"][0]["heading"] == "Recall Clarification Guard"
    assert record["selected"][0]["source_class"] == "recall_guard"
    assert record["selected"][0]["source_ids"] == ["guard:recall_clarification"]
    assert record["boundary"]["actual_send"] is False
    assert record["selected_chars_total"] > 0
    assert query not in rendered
    assert "Do not answer as if one remembered item is certain." not in rendered
    assert "raw_prompt" not in rendered
    assert "section_body" not in rendered


def test_memory_sources_enabled_records_empty_prefetch_attempt(tmp_path):
    store = _store(tmp_path)

    context = build_prefetch(
        "普通聊天",
        budget_chars=2200,
        store=store,
        index=None,
        memory_sources_config={"enabled": True},
    )

    assert context == ""
    records = read_memory_source_records(store.roots, limit=1)
    assert len(records) == 1
    assert records[0]["route"] == "casual_continuity"
    assert records[0]["selected"] == []
    assert records[0]["dropped"] == []


def test_memory_sources_dry_run_router_records_actual_fallback_with_reason(tmp_path):
    store = _store(tmp_path)
    item = build_working_item(seed=310, source_event_id="evt-working")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": item.updated_at,
            "items": [{**item.__dict__, "text": "ComfyUI plugin install is active."}],
        },
    )

    context = build_prefetch(
        "帮我继续安装 ComfyUI 插件",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "dry_run", "apply_routes": ["all"]},
        memory_sources_config={"enabled": True},
    )

    assert "Working Memory" in context
    record = read_memory_source_records(store.roots, limit=1)[0]
    assert record["route"] == "active_task"
    assert record["context_router_mode"] == "dry_run"
    assert record["router_applied"] is False
    assert "router_dry_run_fallback" in record["route_reason_codes"]
    assert any(item["heading"] == "Working Memory" for item in record["selected"])


def test_memory_sources_filter_safe_source_ids_omits_unsafe_values():
    section = ContextSection(
        section="Working Memory",
        text="bounded",
        source_class="working",
        metadata={
            "source_ids": [
                "event:evt_123",
                "working:wk_123",
                "candidate:cand_123",
                "crystallized:cr_123",
                "digest:2026-05-23",
                "reflection_card:card_123",
                "governance_feedback:gf_123",
                "proposal:prop_123",
                "guard:recall_clarification",
                "/root/.hermes/private/session.json",
                "sha256:abcdef",
                "token:secret",
            ]
        },
    )

    assert filter_safe_source_ids(section) == [
        "event:evt_123",
        "working:wk_123",
        "candidate:cand_123",
        "crystallized:cr_123",
        "digest:2026-05-23",
        "reflection_card:card_123",
        "governance_feedback:gf_123",
        "proposal:prop_123",
        "guard:recall_clarification",
    ]


def test_memory_sources_cli_last_history_and_stats_are_bounded(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    build_prefetch(
        "你还记得我之前跟你说过的一个设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        memory_sources_config={"enabled": True},
    )

    result = memory_os_command(_parse_memory_os_args(["memory-sources", "last"]))
    last = json.loads(capsys.readouterr().out)
    assert result == 0
    assert last["schema_version"] == "memory-os.memory_sources_last.v0"
    assert last["record"]["route"] == "ambiguous_recall"

    result = memory_os_command(_parse_memory_os_args(["memory-sources", "history", "--limit", "5"]))
    history = json.loads(capsys.readouterr().out)
    assert result == 0
    assert history["schema_version"] == "memory-os.memory_sources_history.v0"
    assert history["record_count"] == 1

    result = memory_os_command(_parse_memory_os_args(["memory-sources", "stats", "--hours", "24"]))
    stats = json.loads(capsys.readouterr().out)
    rendered = json.dumps(stats, ensure_ascii=False)
    assert result == 0
    assert stats["schema_version"] == "memory-os.memory_sources_stats.v0"
    assert stats["record_count"] == 1
    assert stats["route_distribution"] == {"ambiguous_recall": 1}
    assert stats["selected_source_class_distribution"] == {"recall_guard": 1}
    assert stats["boundary_true_count"] == 0
    assert stats["forbidden_field_findings"] == []
    assert "你还记得" not in rendered
    assert "Do not answer" not in rendered

    result = memory_os_command(_parse_memory_os_args(["memory-sources", "explain-last-injection"]))
    explanation = capsys.readouterr().out
    assert result == 0
    assert "Memory-OS last injection explanation" in explanation
    assert "route: ambiguous_recall" in explanation
    assert "budget: used=" in explanation
    assert "selected sections:" in explanation
    assert "dropped/excluded sections:" in explanation


def test_memory_sources_explain_last_injection_handles_empty_ledger(tmp_path, monkeypatch, capsys):
    _store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(_parse_memory_os_args(["memory-sources", "explain-last-injection"]))
    explanation = capsys.readouterr().out

    assert result == 0
    assert "No Memory Sources injection record exists" in explanation


def test_memory_sources_record_includes_budget_usage(tmp_path):
    store = _store(tmp_path)

    build_prefetch(
        "你还记得我之前跟你说过的一个设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        memory_sources_config={"enabled": True},
    )
    record = read_memory_source_records(store.roots, limit=1)[0]

    assert record["budget_chars"] == 2200
    assert record["used_budget_chars"] > 0


def test_memory_sources_feedback_last_records_explicit_owner_feedback_without_mutating_sources(
    tmp_path,
    monkeypatch,
    capsys,
):
    store = _store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    build_prefetch(
        "你还记得我之前跟你说过的一个设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        memory_sources_config={"enabled": True},
    )
    source_before = read_memory_source_records(store.roots, limit=10)

    result = memory_os_command(
        _parse_memory_os_args(
            [
                "memory-sources",
                "feedback",
                "last",
                "--rating",
                "too-mechanistic",
                "--note",
                "too much mechanism language",
            ]
        )
    )
    feedback = json.loads(capsys.readouterr().out)

    assert result == 0
    assert feedback["schema_version"] == "memory-os.memory_sources_feedback.v0"
    assert feedback["status"] == "ok"
    assert feedback["record"]["rating"] == "too_mechanistic"
    assert feedback["record"]["memory_source_record_id"] == source_before[-1]["record_id"]
    assert feedback["record"]["note"] == "too much mechanism language"
    assert read_memory_source_records(store.roots, limit=10) == source_before
    actions = [entry.get("action") for entry in read_audit_entries(store.roots.audit_path)]
    assert "memory_sources_feedback_recorded" in actions

    result = memory_os_command(_parse_memory_os_args(["memory-sources", "feedback", "history", "--limit", "5"]))
    history = json.loads(capsys.readouterr().out)
    assert result == 0
    assert history["schema_version"] == "memory-os.memory_sources_feedback_history.v0"
    assert history["record_count"] == 1

    result = memory_os_command(_parse_memory_os_args(["memory-sources", "stats", "--hours", "24"]))
    stats = json.loads(capsys.readouterr().out)
    assert result == 0
    assert stats["feedback_count"] == 1
    assert stats["feedback_rating_distribution"] == {"too_mechanistic": 1}


def test_memory_sources_feedback_last_fails_closed_without_source_record(tmp_path, monkeypatch, capsys):
    _store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(
        _parse_memory_os_args(["memory-sources", "feedback", "last", "--rating", "useful"])
    )
    feedback = json.loads(capsys.readouterr().out)

    assert result == 1
    assert feedback["schema_version"] == "memory-os.memory_sources_feedback.v0"
    assert feedback["status"] == "error"
    assert feedback["code"] == "memory_sources_empty"
    assert not (tmp_path / "memory-os" / "system" / "memory_sources_feedback.jsonl").exists()


def test_memory_sources_feedback_last_rejects_unknown_rating(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    build_prefetch(
        "你还记得我之前跟你说过的一个设计吗？",
        budget_chars=2200,
        store=store,
        index=None,
        context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        memory_sources_config={"enabled": True},
    )

    result = memory_os_command(
        _parse_memory_os_args(["memory-sources", "feedback", "last", "--rating", "random"])
    )
    feedback = json.loads(capsys.readouterr().out)

    assert result == 1
    assert feedback["status"] == "error"
    assert feedback["code"] == "invalid_rating"
    assert "useful" in feedback["allowed_ratings"]
    assert not (tmp_path / "memory-os" / "system" / "memory_sources_feedback.jsonl").exists()


def test_memory_sources_record_does_not_mark_available_route_unavailable(tmp_path):
    store = _store(tmp_path)

    record = build_memory_source_record(
        roots=store.roots,
        route_report={"route": "active_task", "selected_sections": [], "dropped_sections": []},
        selected_sections=[],
        context_router_config={"mode": "apply", "apply_routes": ["all"]},
        router_applied=True,
        prefetch_mode="indexed",
    )

    assert record["route"] == "active_task"
    assert "route_unavailable" not in record["route_reason_codes"]


def test_memory_sources_config_normalization_handles_invalid_retention_days():
    config = normalize_memory_sources_config({"enabled": True, "retention_days": "not-a-number"})

    assert config["enabled"] is True
    assert config["retention_days"] == 30


def _parse_memory_os_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    register_cli(parser)
    return parser.parse_args(argv)


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _ledger_path(tmp_path):
    return tmp_path / "memory-os" / "system" / "memory_sources.jsonl"
