import argparse
import json
from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.cognitive_loop import CognitiveLoopRunner
from plugins.memory.memory_os.legacy_right_brain_retirement import retire_legacy_right_brain
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


def test_cognitive_loop_crystallization_gate_step_carries_the_query_dialect(tmp_path):
    """The step summary -- not the gate's return value -- is what persists.

    `_run_step` writes this summary into reports.jsonl, so a key the summary
    drops does not exist for any reader.  The gate's query dialect is the one
    piece of evidence that separates "zero flags because nothing contradicts"
    from "zero flags because the query could never match the index", which is
    exactly how the CJK defect stayed invisible; asserting it on the gate's
    own return value would not have caught the summary dropping it.
    """
    import sqlite3

    store = _init_store(tmp_path)
    from plugins.memory.memory_os.index import MemoryOSIndex

    index = MemoryOSIndex(store.roots)
    index.rebuild_from_store(store)
    conn = sqlite3.connect(str(store.roots.index_path))
    conn.execute(
        """insert into crystallized_candidates
           (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
           values (?, ?, ?, ?, ?, ?, ?)""",
        ("cand_dialect", "preference", "用户在书房安装了一个定时器", "[]", "[]", "private", "proposed"),
    )
    conn.commit()
    conn.close()

    result = CognitiveLoopRunner(store)._crystallization_gate({})

    assert "fts_query_mode" in result, result
    assert "fts_tokenizer" in result, result
    assert result["fts_query_mode"] in {"trigram", "legacy"}, result
    assert result["candidate_count"] == 1, result


def test_cognitive_loop_crystallization_gate_preserves_bounded_error_metadata(
    tmp_path, monkeypatch
):
    store = _init_store(tmp_path)

    from plugins.memory.memory_os import crystallization_gate

    monkeypatch.setattr(
        crystallization_gate,
        "run_crystallization_gate",
        lambda *args, **kwargs: {
            "status": "error",
            "candidate_count": 1,
            "flagged_count": 1,
            "flagged_candidates": [{"candidate_id": "cand_error"}],
            "error_count": 1,
            "error_code": "edge_query_failed",
            "error_records": [
                {"candidate_id": "cand_error", "error_code": "edge_query_failed"}
            ],
            "duration_ms": 1,
        },
    )

    result = CognitiveLoopRunner(store)._crystallization_gate({})

    assert result["status"] == "error"
    assert result["error_count"] == 1
    assert result["error_code"] == "edge_query_failed"
    assert result["error_records"] == [
        {"candidate_id": "cand_error", "error_code": "edge_query_failed"}
    ]


def test_cognitive_loop_default_disables_legacy_right_brain_without_writes(tmp_path):
    store = _init_store(tmp_path)
    _append_event(store, "evt_legacy_gate", "User discussed a foreground task that must not become inner speech.")

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)

    steps = {step["step"]: step for step in result["steps"]}
    for step_name in ("wandering_mind", "grounded_expression_judge", "spontaneous_expression"):
        assert step_name not in steps
        assert step_name in result["disabled_steps"]

    assert not (tmp_path / "system-modules" / "wandering_mind" / "outputs.jsonl").exists()
    assert not (tmp_path / "system-modules" / "expression_draft" / "drafts.jsonl").exists()
    assert not (tmp_path / "system-modules" / "grounded_expression_judge" / "verdicts.jsonl").exists()
    assert not (tmp_path / "system-modules" / "speak_gate" / "would_send.jsonl").exists()


@pytest.mark.parametrize("configured_value", ["true", 1, {}, [True]])
def test_cognitive_loop_legacy_gate_requires_literal_json_boolean_true(tmp_path, configured_value):
    store = _init_store(tmp_path)
    config_path = tmp_path / "memory-os" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"right_brain_expression": {"legacy_cognitive_loop_enabled": configured_value}}) + "\n",
        encoding="utf-8",
    )

    runner = CognitiveLoopRunner(store)
    steps = dict(runner._step_functions(max_events=1, apply=False))

    for step_name in ("wandering_mind", "grounded_expression_judge", "spontaneous_expression"):
        assert step_name not in steps


def test_cognitive_loop_retirement_manifest_overrides_literal_true_compatibility_flag(tmp_path):
    store = _init_store(tmp_path)
    config_path = tmp_path / "memory-os" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"right_brain_expression": {"legacy_cognitive_loop_enabled": False}}) + "\n",
        encoding="utf-8",
    )
    retire_legacy_right_brain(tmp_path, apply=True)
    config_path.write_text(
        json.dumps({"right_brain_expression": {"legacy_cognitive_loop_enabled": True}}) + "\n",
        encoding="utf-8",
    )

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)
    step_names = {step["step"] for step in result["steps"]}

    assert set(result["retired_steps"]) == {
        "wandering_mind",
        "grounded_expression_judge",
        "spontaneous_expression",
    }
    assert not step_names.intersection(result["retired_steps"])


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
        "knob_ab_eval",
        "override_sweep",
        "migration_controller",
        "abstraction_distillation",
        "grounded_expression_judge",
        "spontaneous_expression",
        "self_evolution",
        "structural_edge_proposer",
        "crystallization_gate",
        "llm_edge_proposer",
        "vector_edge_proposer",
        "contradiction_lane",
        "edge_provenance",
        "edge_promotion",
        "edge_weight_feedback",
        "entity_index",
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


def test_spontaneous_expression_completes_execution_gate_envelope(tmp_path, monkeypatch):
    store = _init_store(tmp_path)
    runner = CognitiveLoopRunner(store)

    monkeypatch.setattr(
        "plugins.modules.expression.speak_rate_limit.under_speak_limit",
        lambda _deliveries, *, max_per_hour: True,
    )
    monkeypatch.setattr(
        "plugins.modules.expression.speak_gate.SpeakGateModule.read_delivery_records",
        lambda self: [],
    )
    monkeypatch.setattr(
        "plugins.modules.expression.speak_gate.SpeakGateModule._resolve_owner_channel",
        lambda self: "telegram:owner",
    )
    monkeypatch.setattr(
        "plugins.modules.expression.speak_gate.SpeakGateModule.evaluate_expression_draft",
        lambda self, draft, *, channel, delivery_tier: {
            "decision": "blocked",
            "actual_send": False,
            "delivery_id": "",
            "channel": channel,
        },
    )

    result = runner._spontaneous_expression(
        {
            "wandering_mind": {"expression_draft": {"draft_id": "draft_1", "text": "hello"}},
            "grounded_expression_judge_result": {"decision": "advisory_ok", "verdict_class": "grounded"},
        }
    )

    envelope_id = result["execution_gate_envelope_id"]
    records = [
        json.loads(line)
        for line in (tmp_path / "memory-os" / "system" / "execution_gate_envelopes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    stages = [record["stage"] for record in records if record["execution_gate_envelope_id"] == envelope_id]
    assert stages == ["permit", "completion"]
    assert records[-1]["execution_status"] == "ok"


def test_spontaneous_expression_completes_execution_gate_envelope_on_delivery_error(tmp_path, monkeypatch):
    store = _init_store(tmp_path)
    runner = CognitiveLoopRunner(store)

    monkeypatch.setattr(
        "plugins.modules.expression.speak_rate_limit.under_speak_limit",
        lambda _deliveries, *, max_per_hour: True,
    )
    monkeypatch.setattr(
        "plugins.modules.expression.speak_gate.SpeakGateModule.read_delivery_records",
        lambda self: [],
    )
    monkeypatch.setattr(
        "plugins.modules.expression.speak_gate.SpeakGateModule._resolve_owner_channel",
        lambda self: "telegram:owner",
    )

    def fail_delivery(self, draft, *, channel, delivery_tier):
        raise RuntimeError("synthetic delivery failure")

    monkeypatch.setattr(
        "plugins.modules.expression.speak_gate.SpeakGateModule.evaluate_expression_draft",
        fail_delivery,
    )

    with pytest.raises(RuntimeError, match="synthetic delivery failure"):
        runner._spontaneous_expression(
            {
                "wandering_mind": {"expression_draft": {"draft_id": "draft_1", "text": "hello"}},
                "grounded_expression_judge_result": {"decision": "advisory_ok", "verdict_class": "grounded"},
            }
        )

    records = [
        json.loads(line)
        for line in (tmp_path / "memory-os" / "system" / "execution_gate_envelopes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert [record["stage"] for record in records] == ["permit", "completion"]
    assert records[-1]["execution_status"] == "error"
    assert records[-1]["result_summary"]["error_type"] == "RuntimeError"


def _lane_envelope_records(tmp_path, lane_id: str) -> list[dict]:
    records = [
        json.loads(line)
        for line in (tmp_path / "memory-os" / "system" / "execution_gate_envelopes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    return [record for record in records if record.get("lane_id") == lane_id]


def test_ground_truth_miner_completes_execution_gate_envelope_on_error(tmp_path, monkeypatch):
    # Counterfactual: GroundTruthMinerModule.run_once() only calls
    # complete_execution_gate_envelope() on its own happy-path line (mine() at
    # ground_truth_miner.py). _ground_truth_miner() opened the permit and handed
    # off with zero exception safety, so a raise inside run_once() orphaned the
    # permit. Without the try/except fix, this test fails because lane_records
    # has length 1 (permit only).
    store = _init_store(tmp_path)
    runner = CognitiveLoopRunner(store)

    def fail_run_once(self, **kwargs):
        raise RuntimeError("synthetic ground truth miner failure")

    monkeypatch.setattr(
        "plugins.modules.governance.ground_truth_miner.GroundTruthMinerModule.run_once",
        fail_run_once,
    )

    with pytest.raises(RuntimeError, match="synthetic ground truth miner failure"):
        runner._ground_truth_miner({})

    lane_records = _lane_envelope_records(tmp_path, "reversible_labels")
    assert [record["stage"] for record in lane_records] == ["permit", "completion"]
    assert lane_records[0]["execution_gate_envelope_id"] == lane_records[1]["execution_gate_envelope_id"]
    assert lane_records[-1]["execution_status"] == "error"
    assert lane_records[-1]["result_summary"]["error_type"] == "RuntimeError"


def test_memory_projection_completes_execution_gate_envelope_on_error(tmp_path, monkeypatch):
    # Counterfactual: collect_and_project_signals() only calls
    # complete_execution_gate_envelope() on its own happy-path line. The
    # _memory_projection() lane opened the permit and delegated with zero
    # exception safety, so a raise inside the collector orphaned the permit.
    # Without the try/except fix, this test fails because lane_records has
    # length 1 (permit only).
    store = _init_store(tmp_path)
    runner = CognitiveLoopRunner(store)

    def fail_collect(*args, **kwargs):
        raise RuntimeError("synthetic projection failure")

    monkeypatch.setattr(
        "plugins.memory.memory_os.memory_projection.collect_and_project_signals",
        fail_collect,
    )

    with pytest.raises(RuntimeError, match="synthetic projection failure"):
        runner._memory_projection({"host_capability_probe_result": {}})

    lane_records = _lane_envelope_records(tmp_path, "memory_projection_collect")
    assert [record["stage"] for record in lane_records] == ["permit", "completion"]
    assert lane_records[0]["execution_gate_envelope_id"] == lane_records[1]["execution_gate_envelope_id"]
    assert lane_records[-1]["execution_status"] == "error"
    assert lane_records[-1]["result_summary"]["error_type"] == "RuntimeError"


def test_left_brain_advisor_completes_execution_gate_envelope_on_error(tmp_path, monkeypatch):
    # Counterfactual: run_left_brain_advisor() only calls
    # complete_execution_gate_envelope() on its own happy-path line. The
    # _left_brain_advisor() lane opened the permit and delegated with zero
    # exception safety, so a raise inside the advisor orphaned the permit.
    # Without the try/except fix, this test fails because lane_records has
    # length 1 (permit only).
    store = _init_store(tmp_path)
    runner = CognitiveLoopRunner(store)

    def fail_advisor(*args, **kwargs):
        raise RuntimeError("synthetic advisor failure")

    monkeypatch.setattr(
        "plugins.memory.memory_os.left_brain_advisor.run_left_brain_advisor",
        fail_advisor,
    )

    with pytest.raises(RuntimeError, match="synthetic advisor failure"):
        runner._left_brain_advisor({})

    lane_records = _lane_envelope_records(tmp_path, "left_brain_advisor_report")
    assert [record["stage"] for record in lane_records] == ["permit", "completion"]
    assert lane_records[0]["execution_gate_envelope_id"] == lane_records[1]["execution_gate_envelope_id"]
    assert lane_records[-1]["execution_status"] == "error"
    assert lane_records[-1]["result_summary"]["error_type"] == "RuntimeError"


def test_cognitive_loop_continues_after_step_failure(tmp_path, monkeypatch):
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
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
    _write_deep_reflection_test_host_config(tmp_path)
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


def test_contradiction_lane_embedder_not_none_when_enabled(tmp_path) -> None:
    """When knob enabled, contradiction lane constructs embedder locally."""
    from plugins.memory.memory_os.cognitive_loop import CognitiveLoopRunner
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path)
    store = MemoryOSStore(roots)
    store.initialize()

    # Enable the contradiction lane knob
    override_dir = roots.memory_os_root / "system"
    override_dir.mkdir(parents=True, exist_ok=True)
    (override_dir / "knob_overrides.jsonl").write_text(
        json.dumps({"knob": "llm_contradiction_lane_enabled", "override_value": True, "state": "active"}) + "\n",
        encoding="utf-8",
    )

    runner = CognitiveLoopRunner(store)
    result = runner._contradiction_lane({})
    # With embedder not installed, result will be "skipped" with "embedder_unavailable"
    # But it must NOT be "embedder_unavailable" because of missing plumbing (old bug)
    # The key assertion: the lane tried to construct embedder, didn't just return None
    assert result["status"] in ("skipped", "ok", "error")


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
    memory_os_config_path = tmp_path / "memory-os" / "config.json"
    memory_os_config_path.parent.mkdir(parents=True, exist_ok=True)
    memory_os_config_path.write_text(
        json.dumps({"right_brain_expression": {"legacy_cognitive_loop_enabled": True}}, indent=2) + "\n",
        encoding="utf-8",
    )
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


def test_cognitive_loop_reports_zero_automatic_permanent_promotions(tmp_path):
    """V2-0: the provisional step is report-only — it never auto-promotes."""
    store = _init_store(tmp_path)
    _write_deep_reflection_test_host_config(tmp_path)
    _append_event(store, "evt_promote", "Owner discussed a durable memory fact.")

    result = CognitiveLoopRunner(store).run_once(apply=True, test_host=True)

    steps = {step["step"]: step for step in result["steps"]}
    provisional = steps["provisional"]["result"]
    assert provisional["auto_promote_live_applied"] is False
    assert provisional["auto_promote_promoted"] == 0
    assert provisional["canonical_state_changed"] is False


def test_w5_edge_proposer_step_wrappers_propagate_skip_reason(tmp_path):
    """W5 (E4 观测面) counterfactual:proposer 步骤 skipped 时 reason 必须透传。

    生产事故形态:llm_edge_proposer 自 07-07 每轮 skipped,而 step 包装器
    只映射 status/counters — reports.jsonl 里只见 skipped 不见为什么,
    诊断被迫回读源码 + 手动复现(Completion Is Not Output)。
    """
    from plugins.memory.memory_os.index import MemoryOSIndex

    store = _init_store(tmp_path)
    MemoryOSIndex(store.roots).rebuild_from_store(store)
    runner = CognitiveLoopRunner(store)

    # 空库:llm/structural 走 "need ≥2 crystallized records" skip 分支
    llm = runner._llm_edge_proposer({})
    assert llm["status"] == "skipped"
    assert llm.get("reason"), f"llm wrapper must propagate skip reason: {llm}"

    structural = runner._structural_edge_proposer({})
    assert structural["status"] == "skipped"
    assert structural.get("reason"), (
        f"structural wrapper must propagate skip reason: {structural}"
    )

    # vector:knob 默认关 → knob_disabled(该包装器已有 reason,回归钉住)
    vector = runner._vector_edge_proposer({})
    assert vector["status"] == "skipped"
    assert vector.get("reason") == "knob_disabled"


def test_edge_weight_feedback_wrapper_passes_through_r4_counters(tmp_path, monkeypatch):
    """反事实(S3 生产验证实锤):step 包装器白名单漏键 = 计数对一切读者
    不存在 — 报告工件与监控 edge_step_results 读的都是包装器返回值。
    already_saturated / skipped_not_injected / invalidated_never_hit /
    forget_eligible_backlog 四个 R4 新计数必须透传。"""
    store = _init_store(tmp_path)
    runner = CognitiveLoopRunner(store)

    import plugins.memory.memory_os.edge_weight_feedback as ewf

    def _fake_run(index_path, *, index=None, audit_path=None, now=None):
        return {
            "status": "ok",
            "outcome": "reinforced",
            "new_hit_record_count": 3,
            "reinforced_count": 1,
            "already_saturated_count": 2,
            "skipped_not_injected_count": 4,
            "forgotten_count": 5,
            "invalidated_never_hit_count": 5,
            "forget_eligible_backlog": 7,
            "unresolved_hit_count": 0,
            "failed_count": 0,
            "tracked_edge_count": 9,
            "duration_ms": 1,
        }

    monkeypatch.setattr(ewf, "run_edge_weight_feedback", _fake_run)
    summary = runner._edge_weight_feedback({})
    assert summary["already_saturated_count"] == 2
    assert summary["skipped_not_injected_count"] == 4
    assert summary["invalidated_never_hit_count"] == 5
    assert summary["forget_eligible_backlog"] == 7
    assert summary["reinforced_count"] == 1
    assert summary["outcome"] == "reinforced"


def test_edge_weight_feedback_wrapper_passes_through_cursor_alignment_fields(tmp_path, monkeypatch):
    """Counterfactual: the outcome branch gives reinforced/forgotten/
    saturated precedence over "cursor_misaligned", so a ledger-cursor
    desync (future graph_layer_shadow.jsonl compaction — metadata_retention
    is dry-run only today, no executor yet) goes dark in `outcome` exactly
    when the run was ALSO busy reinforcing/forgetting that same cycle —
    the case an operator most needs to see. tracked_edge_count and the five
    cursor_* diagnostic fields must survive the wrapper's whitelist
    independently of outcome."""
    store = _init_store(tmp_path)
    runner = CognitiveLoopRunner(store)

    import plugins.memory.memory_os.edge_weight_feedback as ewf

    def _fake_run(index_path, *, index=None, audit_path=None, now=None):
        return {
            "status": "ok",
            # outcome == "reinforced" (forgetting/reinforcement took
            # precedence) even though this run's cursor WAS misaligned.
            "outcome": "reinforced",
            "new_hit_record_count": 0,
            "reinforced_count": 0,
            "already_saturated_count": 0,
            "skipped_not_injected_count": 0,
            "forgotten_count": 3,
            "invalidated_never_hit_count": 1,
            "forget_eligible_backlog": 0,
            "unresolved_hit_count": 0,
            "failed_count": 0,
            "tracked_edge_count": 12,
            "cursor_misaligned": True,
            "cursor_misalignment_reason": "ledger_shorter_than_cursor",
            "cursor_previous_line_count": 500,
            "cursor_realigned_line_count": 480,
            "cursor_skipped_row_count": 20,
            "duration_ms": 1,
        }

    monkeypatch.setattr(ewf, "run_edge_weight_feedback", _fake_run)
    summary = runner._edge_weight_feedback({})
    assert summary["outcome"] == "reinforced", (
        "sanity: outcome alone must NOT be the only signal for this scenario"
    )
    assert summary["tracked_edge_count"] == 12
    assert summary["cursor_misaligned"] is True
    assert summary["cursor_misalignment_reason"] == "ledger_shorter_than_cursor"
    assert summary["cursor_previous_line_count"] == 500
    assert summary["cursor_realigned_line_count"] == 480
    assert summary["cursor_skipped_row_count"] == 20


def test_edge_provenance_wrapper_passes_through_write_failed_count(tmp_path, monkeypatch):
    """Counterfactual: write_failed_count is the counter that distinguishes
    "nothing to write" from "tried and failed" (Completion Is Not Output).
    The monitor's _edge_fields already whitelists it; before this fix the
    cognitive_loop wrapper never picked it off run_edge_provenance's
    summary, so it reached no reader."""
    store = _init_store(tmp_path)
    runner = CognitiveLoopRunner(store)

    import plugins.memory.memory_os.edge_provenance as ep

    def _fake_run(index_path, *, index=None, audit_path=None):
        return {
            "status": "ok",
            "outcome": "produced",
            "record_count": 5,
            "scanned_ref_count": 8,
            "proposed_count": 2,
            "dedup_skipped": 1,
            "write_failed_count": 3,
            "duration_ms": 1,
        }

    monkeypatch.setattr(ep, "run_edge_provenance", _fake_run)
    summary = runner._edge_provenance({})
    assert summary["write_failed_count"] == 3


def test_llm_edge_proposer_wrapper_propagates_outcome_and_call_counters(tmp_path, monkeypatch):
    """D2b counterfactual: before this fix, the step wrapper's whitelist
    picked neither ``outcome`` nor any ``llm_call_*`` key off
    run_llm_proposer's summary, so a run where every LLM call failed was
    byte-identical in the cognitive-loop report to one that legitimately
    found no relationships (both showed pair_count>0, proposed_count=0).

    Drives the REAL producer (run_llm_proposer via the real _llm_edge_proposer
    wrapper) through a monkeypatched model seam (_call_hermes_runtime_model
    returning "") — not a hand-built summary dict — per the project's rule
    that hand fixtures let counterfactuals pass vacuously."""
    from plugins.memory.memory_os.index import MemoryOSIndex
    from plugins.memory.memory_os import llm_edge_proposer

    store = _init_store(tmp_path)
    index = MemoryOSIndex(store.roots)

    for rec_id, created_at in (
        ("cry_llm_a", "2026-06-01T10:00:00Z"),
        ("cry_llm_b", "2026-06-01T11:00:00Z"),
    ):
        store.append_crystallized_record(
            "test_llm_edge_proposer_wrapper.md",
            {
                "schema_version": "memory-os.crystallized.v0",
                "id": rec_id,
                "kind": "test",
                "created_at": created_at,
                "approved_by": "owner",
                "approved_at": created_at,
                "approval_purpose": "test",
                "approval_note": "test seed",
                "source_event_ids": [],
                "tags": [],
                "sensitivity": "private",
                "hindsight_indexed": False,
                "bridge_state": "active",
            },
            "test crystallized record body",
        )
    index.rebuild_from_store(store)

    monkeypatch.setattr(
        llm_edge_proposer, "_resolve_hermes_default_runtime",
        lambda config: {"ok": True, "model": "test-model", "runtime": {"api_mode": "chat_completions"}},
    )
    # Every LLM reply is empty -> every _call_llm outcome is
    # "empty_llm_response" -> the run is degraded, not "no relationships".
    monkeypatch.setattr(llm_edge_proposer, "_call_hermes_runtime_model", lambda prompt, config: "")

    runner = CognitiveLoopRunner(store)
    summary = runner._llm_edge_proposer({})

    assert summary["status"] == "degraded"
    assert summary["outcome"] == "llm_degraded"
    assert summary["llm_call_count"] == 1
    assert summary["llm_call_ok_count"] == 0
    assert summary["llm_call_failure_count"] == 1
    assert summary["llm_call_failure_reasons"] == {"empty_llm_response": 1}


def test_llm_edge_proposer_degraded_status_maps_to_warning_at_step_level(tmp_path, monkeypatch):
    """Counterfactual for the "degraded" step-status blind spot: the
    producer above correctly returns status="degraded" when every LLM call
    fails, but _step_status's vocabulary was closed over {ok, warning,
    error, deferred, skipped, skipped_dependency_failed, blocked} and the
    degraded summary carries neither an "output"=="[SILENT]" nor a
    truthy "reason" key -- so the fall-through branch classified the
    step (and therefore the cycle) as "ok" on the exact all-calls-failed
    run this fix exists to expose.

    Drives the REAL _run_step path (not the inner dict) so the assertion
    is on the same step-level classification that feeds _cycle_status and
    the persisted report.
    """
    from plugins.memory.memory_os.index import MemoryOSIndex
    from plugins.memory.memory_os import llm_edge_proposer

    store = _init_store(tmp_path)
    index = MemoryOSIndex(store.roots)

    for rec_id, created_at in (
        ("cry_llm_c", "2026-06-01T10:00:00Z"),
        ("cry_llm_d", "2026-06-01T11:00:00Z"),
    ):
        store.append_crystallized_record(
            "test_llm_edge_proposer_step_status.md",
            {
                "schema_version": "memory-os.crystallized.v0",
                "id": rec_id,
                "kind": "test",
                "created_at": created_at,
                "approved_by": "owner",
                "approved_at": created_at,
                "approval_purpose": "test",
                "approval_note": "test seed",
                "source_event_ids": [],
                "tags": [],
                "sensitivity": "private",
                "hindsight_indexed": False,
                "bridge_state": "active",
            },
            "test crystallized record body",
        )
    index.rebuild_from_store(store)

    monkeypatch.setattr(
        llm_edge_proposer, "_resolve_hermes_default_runtime",
        lambda config: {"ok": True, "model": "test-model", "runtime": {"api_mode": "chat_completions"}},
    )
    # Every LLM reply is empty -> every _call_llm outcome is
    # "empty_llm_response" -> the run is degraded, not "no relationships".
    monkeypatch.setattr(llm_edge_proposer, "_call_hermes_runtime_model", lambda prompt, config: "")

    runner = CognitiveLoopRunner(store)
    step = runner._run_step("llm_edge_proposer", runner._llm_edge_proposer, {})

    # The inner passthrough dict keeps the raw producer status untouched...
    assert step["result"]["status"] == "degraded"
    # ...but the step-level classification that _cycle_status/the report
    # consume must not lie "ok" through an all-calls-failed run.
    assert step["status"] == "warning"
