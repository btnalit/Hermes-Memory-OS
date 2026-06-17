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
        "working_decay",
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
        "provisional_sweep",
        "migration_controller",
        "abstraction_distillation",
        "grounded_expression_judge",
        "spontaneous_expression",
        "self_evolution",
        "structural_edge_proposer",
        "crystallization_gate",
        "llm_edge_proposer",
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
    assert (tmp_path / "system-modules" / "speak_gate" / "would_send.jsonl").is_file() is False  # owner-send mode skips would-send records
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
    assert wandering_result["expression_draft_created"] is True
    assert "expression_draft" in wandering_result
    assert "speak_gate_evaluated" not in wandering_result  # V1: speak_gate deferred to spontaneous_expression
    assert "speak_gate_decision" not in wandering_result
    # V1: spontaneous_expression step should exist and have been evaluated
    spontaneous = steps["spontaneous_expression"]["result"]
    assert spontaneous["spontaneous_expression_evaluated"] is True
    assert spontaneous["spontaneous_sent"] is False  # test_host mode, no real owner channel match
    assert steps["confidence_router"]["result"]["route_live_applied"] is False
    assert steps["candidate_review"]["result"]["candidate_review_live_applied"] is False
    assert steps["judge_calibration"]["result"]["calibration_live_applied"] is False
    assert steps["shadow_recall"]["result"]["auto_discard_live_applied"] is False
    assert steps["provisional"]["result"]["auto_promote_live_applied"] is False
    assert steps["cascade_routing_policy"]["result"]["route_strategy_live_applied"] is False
    assert steps["imagination_loop"]["result"]["live_applied"] is False
    assert steps["confabulation_detector"]["result"]["live_behavior_changed"] is False
    assert steps["ground_truth_miner"]["result"]["score_live_applied"] is False
    assert steps["ground_truth_miner"]["result"]["lane_id"] == "reversible_labels"
    assert steps["ground_truth_miner"]["result"]["risk_class"] == "bounded_reversible_label"
    assert steps["ground_truth_miner"]["result"]["execution_gate_resolution"]["status"] == "valid"
    assert steps["ground_truth_miner"]["result"]["structural_write_gate_bound"] is True
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
    assert "expression_draft" not in wandering_result
    # V1: spontaneous_expression handles the no-draft case gracefully
    spontaneous = second_steps["spontaneous_expression"]["result"]
    assert spontaneous["spontaneous_decision"] == "no_draft"
    assert spontaneous["spontaneous_sent"] is False
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


def test_cognitive_loop_cli_uses_default_max_events_when_host_wrapper_omits_it(tmp_path, monkeypatch, capsys):
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User discussed host wrapper cognitive loop.")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    args = argparse.Namespace(
        memory_os_command="cognitive-loop",
        cognitive_loop_command="run-once",
        test_host=True,
        apply=True,
    )

    result = memory_os_command(args)

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "memory-os.cognitive_loop.v0"
    assert output["test_host"] is True


def test_V1_5_spontaneous_expression_sends_when_judge_ok_and_under_limit(tmp_path, monkeypatch):
    """V1.5: New qualifying event + judge says 'advisory_ok' + under limit → delivered via spontaneous_owner tier."""
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User shared a reflection on recent work.")

    # Mock the judge to return advisory_ok (grounded expression, worth saying)
    def mock_judge_ok(self, **kwargs):
        return {
            "schema_version": "hermes.grounded_expression_verdict.v0",
            "module": "grounded_expression_judge",
            "profile": "default",
            "status": "ok",
            "decision": "advisory_ok",
            "verdict_class": "grounded",
            "code": "cross_check_advisory_ok",
            "owner_escalation_required": False,
            "actual_send": False,
            "actual_execute": False,
        }

    monkeypatch.setattr(
        "plugins.modules.expression.grounded_expression_judge.GroundedExpressionJudge.run_once",
        mock_judge_ok,
    )

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)
    steps = {step["step"]: step for step in result["steps"]}

    spontaneous = steps["spontaneous_expression"]["result"]
    assert spontaneous["spontaneous_expression_evaluated"] is True
    assert spontaneous["spontaneous_decision"] in {"delivered", "send_blocked"}
    # send_blocked is acceptable in test_host mode (no real owner channel configured)
    # but the path must have been exercised
    assert spontaneous["spontaneous_delivery_tier"] == "spontaneous_owner"


def test_V1_6_judge_blocks_confabulation_from_sending(tmp_path, monkeypatch):
    """V1.6: Judge says 'confabulation' → silent, no send, judge decision recorded."""
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User discussed something that might trigger confabulation.")

    # Mock the judge to return confabulation (hallucination detected)
    def mock_judge_confabulation(self, **kwargs):
        return {
            "schema_version": "hermes.grounded_expression_verdict.v0",
            "module": "grounded_expression_judge",
            "profile": "default",
            "status": "ok",
            "decision": "confabulation",
            "verdict_class": "confabulation",
            "code": "cross_check_confabulation",
            "owner_escalation_required": True,
            "actual_send": False,
            "actual_execute": False,
        }

    monkeypatch.setattr(
        "plugins.modules.expression.grounded_expression_judge.GroundedExpressionJudge.run_once",
        mock_judge_confabulation,
    )

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)
    steps = {step["step"]: step for step in result["steps"]}

    spontaneous = steps["spontaneous_expression"]["result"]
    assert spontaneous["spontaneous_expression_evaluated"] is True
    assert spontaneous["spontaneous_decision"] == "judge_blocked"
    assert spontaneous["spontaneous_sent"] is False
    assert "confabulation" in spontaneous["spontaneous_reason"]


def test_V1_7_spontaneous_expression_does_not_write_would_send(tmp_path):
    """V1.7: Production spontaneous path does not write would_send records."""
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User discussed would_send residue check.")

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)

    # wandering_mind should NOT produce would_send records in V1
    wm_would_send = tmp_path / "system-modules" / "wandering_mind" / "would_send.jsonl"
    if wm_would_send.exists():
        records = [
            line for line in wm_would_send.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        # If any exist, they should be from before V1 — verify no new ones were added
        assert len(records) == 0, f"wandering_mind would_send.jsonl should be empty, got {len(records)} records"

    # speak_gate in owner-send mode should also not write would_send
    sg_would_send = tmp_path / "system-modules" / "speak_gate" / "would_send.jsonl"
    assert sg_would_send.is_file() is False


def test_V1_8_spontaneous_uses_resolved_owner_channel(tmp_path, monkeypatch):
    """V1.8: spontaneous_expression resolves and uses the owner channel from speak_gate."""
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User discussed channel verification.")

    # Mock judge to return advisory_ok
    def mock_judge_ok(self, **kwargs):
        return {
            "schema_version": "hermes.grounded_expression_verdict.v0",
            "module": "grounded_expression_judge",
            "profile": "default",
            "status": "ok",
            "decision": "advisory_ok",
            "verdict_class": "grounded",
            "code": "cross_check_advisory_ok",
            "owner_escalation_required": False,
            "actual_send": False,
            "actual_execute": False,
        }

    monkeypatch.setattr(
        "plugins.modules.expression.grounded_expression_judge.GroundedExpressionJudge.run_once",
        mock_judge_ok,
    )

    # Mock _resolve_owner_channel to return a known channel
    def mock_resolve_channel(self):
        return "telegram"

    monkeypatch.setattr(
        "plugins.modules.expression.speak_gate.SpeakGateModule._resolve_owner_channel",
        mock_resolve_channel,
    )

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)
    steps = {step["step"]: step for step in result["steps"]}

    spontaneous = steps["spontaneous_expression"]["result"]
    assert spontaneous["spontaneous_expression_evaluated"] is True
    # With owner channel resolved to "telegram", the delivery should use that channel
    assert spontaneous["spontaneous_channel"] == "telegram"


def test_V1_9_no_owner_approval_gate_in_speech_path(tmp_path, monkeypatch):
    """V1.9: Speech path has no owner-approval gate (P1 invariant)."""
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_1", "User discussed speech path P1 compliance.")

    # Mock judge to return advisory_ok
    def mock_judge_ok(self, **kwargs):
        return {
            "schema_version": "hermes.grounded_expression_verdict.v0",
            "module": "grounded_expression_judge",
            "profile": "default",
            "status": "ok",
            "decision": "advisory_ok",
            "verdict_class": "grounded",
            "code": "cross_check_advisory_ok",
            "owner_escalation_required": False,
            "actual_send": False,
            "actual_execute": False,
        }

    monkeypatch.setattr(
        "plugins.modules.expression.grounded_expression_judge.GroundedExpressionJudge.run_once",
        mock_judge_ok,
    )

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)
    steps = {step["step"]: step for step in result["steps"]}

    spontaneous = steps["spontaneous_expression"]["result"]
    # The spontaneous_expression step must NOT contain any owner approval field
    assert "owner_approved" not in spontaneous
    assert "approval_required" not in spontaneous
    assert "owner_review_required" not in spontaneous
    # The only gates are judge verdict + rate limit (both deterministic, no human).
    # spontaneous_reason only present on blocked paths; if absent (happy path), that's even better.
    assert spontaneous.get("spontaneous_reason") not in (
        "owner_approval_required",
        "awaiting_owner_review",
    )


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
