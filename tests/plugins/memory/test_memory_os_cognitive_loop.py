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
        "self_evolution",
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
    assert (tmp_path / "system-modules" / "household_digest" / "household_digest.md").is_file()
    assert (tmp_path / "system-modules" / "wandering_mind" / "outputs.jsonl").is_file()
    assert (tmp_path / "system-modules" / "speak_gate" / "would_send.jsonl").is_file()
    assert (tmp_path / "system-modules" / "evidence_scoring" / "scores.jsonl").is_file()
    assert (tmp_path / "system-modules" / "governance_feedback" / "state.json").is_file()
    assert (tmp_path / "system-modules" / "deep_reflection" / "injection" / "current.json").is_file()
    steps = {step["step"]: step for step in result["steps"]}
    wandering_result = steps["wandering_mind"]["result"]
    assert wandering_result["speak_gate_evaluated"] is True
    assert wandering_result["speak_gate_decision"]["decision"] == "would_send"
    assert wandering_result["speak_gate_decision"]["actual_send"] is False


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
