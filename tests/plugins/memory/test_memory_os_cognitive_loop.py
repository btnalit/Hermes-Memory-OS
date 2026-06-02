import argparse
import json
from datetime import datetime, timezone

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.cognitive_loop import CognitiveLoopRunner
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


def test_cognitive_loop_rejects_apply_without_test_host(tmp_path):
    store = _init_store(tmp_path)

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=False)

    assert result["status"] == "error"
    assert result["code"] == "test_host_required"
    assert result["boundaries"]["actual_send"] is False
    assert result["boundaries"]["actual_execute"] is False


def test_cognitive_loop_runs_full_no_send_cycle_and_writes_report(tmp_path):
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User discussed Memory-OS cognitive loop validation.")

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)

    assert result["schema_version"] == "memory-os.cognitive_loop.v0"
    assert result["status"] in {"ok", "warning"}
    assert [step["step"] for step in result["steps"]] == [
        "heartbeat_pre",
        "household_digest",
        "digest_consolidation",
        "wandering_mind",
        "ops_gate",
        "evidence_scoring",
        "confidence_router",
        "candidate_review",
        "judge_calibration",
        "shadow_recall",
        "provisional",
        "cascade_routing_policy",
        "imagination_loop",
        "confabulation_detector",
        "ground_truth_miner",
        "crystallized_revalidator",
        "migration_controller",
        "abstraction_distillation",
        "grounded_expression_judge",
        "self_evolution",
        "left_brain_pipeline_check",
        "host_capability_probe",
        "signal_collection",
        "memory_projection",
        "left_brain_advisor",
        "governance_feedback",
        "deep_reflection",
        "heartbeat_post",
        "doctor_boundary_report",
    ]
    assert result["boundaries"] == {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_crystallized_approval": False,
        "hindsight_exported": False,
    }
    assert (tmp_path / "system-modules" / "cognitive_loop" / "reports.jsonl").is_file()
    persisted = [
        json.loads(line)
        for line in (tmp_path / "system-modules" / "cognitive_loop" / "reports.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ][-1]
    assert [step["step"] for step in persisted["steps"]] == [step["step"] for step in result["steps"]]
    assert persisted["step_summary"]["step_count"] == len(result["steps"])
    assert persisted["step_summary"]["omitted_step_count"] == 0
    assert persisted["step_summary"]["tail_step_statuses"]["left_brain_pipeline_check"] in {"ok", "warning", "skipped"}
    assert persisted["step_summary"]["tail_step_statuses"]["doctor_boundary_report"] in {"ok", "warning"}
    assert (tmp_path / "system-modules" / "household_digest" / "household_digest.md").is_file()
    assert (tmp_path / "system-modules" / "wandering_mind" / "outputs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "speak_gate" / "would_send.jsonl").is_file()
    assert (tmp_path / "system-modules" / "evidence_scoring" / "scores.jsonl").is_file()
    assert (tmp_path / "system-modules" / "confidence_router" / "routing.jsonl").is_file()
    assert (tmp_path / "system-modules" / "candidate_review" / "runs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "judge_calibration" / "runs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "shadow_recall" / "runs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "provisional" / "runs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "cascade_routing_policy" / "policy_proposals.jsonl").is_file()
    assert (tmp_path / "system-modules" / "imagination_loop" / "scenarios.jsonl").is_file()
    assert (tmp_path / "system-modules" / "confabulation_detector" / "runs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "ground_truth_miner" / "runs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "crystallized_revalidator" / "runs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "migration_controller" / "runs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "abstraction_distillation" / "items.jsonl").is_file()
    assert (tmp_path / "system-modules" / "grounded_expression_judge" / "verdicts.jsonl").is_file()
    assert (tmp_path / "memory-os" / "system" / "memory_projections.jsonl").is_file()
    assert (tmp_path / "system-modules" / "left_brain_advisor" / "reports.jsonl").is_file()
    assert (tmp_path / "system-modules" / "governance_feedback" / "state.json").is_file()
    assert (tmp_path / "system-modules" / "deep_reflection" / "injection" / "current.json").is_file()
    steps = {step["step"]: step for step in result["steps"]}
    wandering_result = steps["wandering_mind"]["result"]
    assert wandering_result["speak_gate_evaluated"] is True
    assert wandering_result["speak_gate_decision"]["decision"] == "would_send"
    assert wandering_result["speak_gate_decision"]["actual_send"] is False
    assert steps["confidence_router"]["result"]["route_live_applied"] is False
    assert steps["candidate_review"]["result"]["candidate_review_live_applied"] is False
    assert steps["judge_calibration"]["result"]["calibration_live_applied"] is False
    assert steps["shadow_recall"]["result"]["auto_discard_live_applied"] is False
    assert steps["provisional"]["result"]["auto_promote_live_applied"] is False
    assert steps["cascade_routing_policy"]["result"]["route_strategy_live_applied"] is False
    assert steps["imagination_loop"]["result"]["live_applied"] is False
    assert steps["confabulation_detector"]["result"]["live_behavior_changed"] is False
    assert steps["ground_truth_miner"]["result"]["score_live_applied"] is False
    assert steps["crystallized_revalidator"]["result"]["demotion_live_applied"] is False
    assert steps["migration_controller"]["result"]["migration_live_applied"] is False
    assert steps["abstraction_distillation"]["result"]["distillation_live_applied"] is False
    assert steps["grounded_expression_judge"]["result"]["policy_live_applied"] is False
    assert steps["memory_projection"]["result"]["execution_gate_resolution"]["status"] == "valid"
    assert steps["left_brain_advisor"]["result"]["execution_gate_resolution"]["status"] == "valid"


def test_cognitive_loop_passes_owner_feedback_signals_to_migration_controller(tmp_path):
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User discussed MemorySources owner feedback canary.")
    feedback_path = store.roots.memory_os_root / "system" / "memory_sources_feedback.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.memory_sources_feedback.v0",
                "feedback_id": "msfb_001",
                "created_at": "2026-05-31T00:00:00Z",
                "profile": "default",
                "memory_source_record_id": "msrc_001",
                "route": "casual_continuity",
                "query_class": "casual_continuity",
                "rating": "useful",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)

    steps = {step["step"]: step for step in result["steps"]}
    assert steps["evidence_scoring"]["result"]["memory_sources_feedback_subject_count"] == 1
    migration = steps["migration_controller"]["result"]
    assert migration["owner_feedback_count"] == 1
    assert migration["owner_signal_count"] == 1
    assert migration["migration_live_applied"] is False
    assert migration["actual_execute"] is False


def test_cognitive_loop_skips_right_brain_downstream_when_signal_unchanged(tmp_path):
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User discussed right-brain cadence.")

    runner = CognitiveLoopRunner(store)
    first = runner.run_once(apply=True, test_host=True)
    second = runner.run_once(apply=True, test_host=True)

    first_steps = {step["step"]: step for step in first["steps"]}
    second_steps = {step["step"]: step for step in second["steps"]}
    assert first_steps["wandering_mind"]["result"]["expression_draft_created"] is True
    wandering_result = second_steps["wandering_mind"]["result"]
    assert wandering_result["status"] == "skipped"
    assert wandering_result["cadence_skipped"] is True
    assert wandering_result["expression_draft_skipped"] is True
    assert wandering_result["speak_gate_skipped"] is True
    assert "expression_draft" not in wandering_result
    assert "speak_gate_decision" not in wandering_result
    assert second["boundaries"]["actual_send"] is False


def test_cognitive_loop_continues_after_step_failure(tmp_path, monkeypatch):
    store = _init_store(tmp_path)
    _append_event(store, "evt_1", "User discussed failure isolation.")

    def fail_household_digest(self, **kwargs):
        raise RuntimeError("digest exploded")

    monkeypatch.setattr(
        "plugins.modules.context.household_digest.HouseholdDigestModule.build_digest",
        fail_household_digest,
    )

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)

    steps = {step["step"]: step for step in result["steps"]}
    assert result["status"] == "warning"
    assert steps["household_digest"]["status"] == "error"
    assert steps["wandering_mind"]["status"] in {"ok", "warning"}
    assert steps["doctor_boundary_report"]["status"] in {"ok", "warning"}
    assert result["boundaries"]["actual_send"] is False
    assert result["boundaries"]["actual_execute"] is False


def test_cognitive_loop_reports_hard_boundary_violation(tmp_path, monkeypatch):
    store = _init_store(tmp_path)
    _append_event(store, "evt_1", "User discussed hard boundary enforcement.")

    def unsafe_wandering(self, **kwargs):
        return {
            "schema_version": "test.wandering.v0",
            "status": "ok",
            "actual_send": True,
        }

    monkeypatch.setattr(
        "plugins.modules.cognition.wandering_mind.WanderingMindModule.run_once",
        unsafe_wandering,
    )

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)

    assert result["status"] == "error"
    assert result["boundaries"]["actual_send"] is True
    assert result["steps"][-1]["step"] == "doctor_boundary_report"


def test_cognitive_loop_cli_requires_test_host_for_apply(tmp_path, monkeypatch, capsys):
    _init_store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(_parse_memory_os_args(["cognitive-loop", "run-once", "--apply"]))

    assert result == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error"
    assert output["code"] == "test_host_required"


def test_cognitive_loop_cli_runs_test_host_apply(tmp_path, monkeypatch, capsys):
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User discussed CLI cognitive loop.")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(
        _parse_memory_os_args(["cognitive-loop", "run-once", "--test-host", "--apply"])
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "memory-os.cognitive_loop.v0"
    assert output["test_host"] is True
    assert output["apply"] is True
    assert output["boundaries"]["actual_send"] is False


def _parse_memory_os_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    register_cli(parser)
    return parser.parse_args(argv)


def _init_store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _append_event(store: MemoryOSStore, event_id: str, summary: str) -> None:
    store.append_event(
        EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id=event_id,
            ts=datetime.now(timezone.utc).isoformat(),
            profile="default",
            source="telegram",
            kind="conversation_turn",
            summary=summary,
            safe_ref={"source_class": "foreground"},
            tags=["test"],
            sensitivity="private",
            body_policy="summary_only",
            promotion_state="raw",
        )
    )


def _write_deep_reflection_test_host_config(tmp_path) -> None:
    config_path = tmp_path / "system-modules" / "deep_reflection" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "injection_mode": "auto_bounded",
                "analysis_mode": "deterministic",
                "llm_enabled": False,
                "working_updates_enabled": False,
                "self_evolution_proposals_enabled": True,
                "wandering_seed_enabled": True,
                "max_cards": 2,
                "max_chars_total": 600,
                "max_chars_per_card": 260,
                "ttl_hours": 24,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
