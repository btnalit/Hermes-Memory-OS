from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SHELL_DIR = REPO_ROOT / "plugins" / "memory-os-agent-os"


class FakePluginContext:
    def __init__(self) -> None:
        self.cli_commands: list[dict[str, Any]] = []
        self.hooks: list[str] = []
        self.hook_callbacks: dict[str, Any] = {}
        self.slash_commands: list[str] = []

    def register_cli_command(self, **kwargs: Any) -> None:
        self.cli_commands.append(kwargs)

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks.append(name)
        self.hook_callbacks[name] = callback

    def register_command(self, name: str, handler: Any, **kwargs: Any) -> None:
        self.slash_commands.append(name)


def load_shell_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("memory_os_agent_os_shell", SHELL_DIR / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_shell_module_from(path: Path, name: str = "memory_os_agent_os_shell_installed") -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shell_manifest_is_official_user_plugin_shape():
    manifest = (SHELL_DIR / "plugin.yaml").read_text(encoding="utf-8")

    assert "name: memory-os-agent-os" in manifest
    assert "version: 0.1.0" in manifest
    assert "kind: standalone" in manifest
    assert "on_session_start" in manifest
    assert "on_session_reset" in manifest
    assert "on_session_finalize" in manifest
    assert "pre_tool_call" in manifest


def test_shell_registers_cli_alias_and_session_marker_hooks_without_slash_commands():
    module = load_shell_module()
    ctx = FakePluginContext()

    module.register(ctx)

    assert [command["name"] for command in ctx.cli_commands] == ["memory-os-agent-os"]
    command = ctx.cli_commands[0]
    assert command["handler_fn"] is module.memory_os_agent_os_command
    assert callable(command["setup_fn"])
    assert ctx.hooks == ["on_session_start", "on_session_reset", "on_session_finalize", "pre_tool_call"]
    assert ctx.slash_commands == []


def test_shell_pre_tool_call_blocks_owner_review_terminal_bypass(monkeypatch, tmp_path):
    module = load_shell_module()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = module._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "cd /root/.hermes && hermes memory-os-agent-os review apply --action apply_proposal --target prop_1 --apply # memory apply oa_05283bb25e3a0f"},
    )

    assert result == {
        "action": "block",
        "message": module._OWNER_ACTION_BYPASS_BLOCK_MESSAGE,
    }
    entries = _audit_entries(tmp_path)
    assert entries[-1]["action"] == "owner_review_tool_bypass_blocked"
    assert entries[-1]["status"] == "blocked"
    assert entries[-1]["details"]["tool_name"] == "terminal"


def test_shell_pre_tool_call_blocks_direct_python_owner_action_bypass():
    module = load_shell_module()

    result = module._on_pre_tool_call(
        tool_name="execute_code",
        args={
            "code": (
                "from plugins.memory.memory_os.owner_actions import "
                "apply_approved_proposal_execution_decision\n"
                "token='oa_05283bb25e3a0f'\n"
            )
        },
    )

    assert result == {"action": "block", "message": module._OWNER_ACTION_BYPASS_BLOCK_MESSAGE}


def test_shell_pre_tool_call_allows_read_only_shell_without_owner_token():
    module = load_shell_module()

    result = module._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "grep -n apply_proposal /root/.hermes/plugins/memory_os/owner_actions.py"},
    )

    assert result is None


def test_shell_pre_tool_call_does_not_block_structured_review_tool():
    module = load_shell_module()

    result = module._on_pre_tool_call(
        tool_name="memory_os_review_reply",
        args={"action": "apply", "action_token": "oa_05283bb25e3a0f"},
    )

    assert result is None


def test_shell_cli_exposes_status_and_doctor_aliases():
    module = load_shell_module()
    parser = argparse.ArgumentParser()

    module.register_cli(parser)

    assert parser.parse_args(["status"]).agent_os_command == "status"
    assert parser.parse_args(["doctor"]).agent_os_command == "doctor"
    hindsight_status_args = parser.parse_args(["hindsight", "status"])
    assert hindsight_status_args.agent_os_command == "hindsight"
    assert hindsight_status_args.hindsight_command == "status"
    hindsight_adopt_args = parser.parse_args(["hindsight", "adopt", "--apply"])
    assert hindsight_adopt_args.agent_os_command == "hindsight"
    assert hindsight_adopt_args.hindsight_command == "adopt"
    assert hindsight_adopt_args.apply is True
    hindsight_retain_args = parser.parse_args(["hindsight", "retain-pending", "--apply"])
    assert hindsight_retain_args.agent_os_command == "hindsight"
    assert hindsight_retain_args.hindsight_command == "retain-pending"
    assert hindsight_retain_args.apply is True
    hindsight_retract_args = parser.parse_args(
        ["hindsight", "retract", "--record-id", "cmem_1", "--reason", "owner_revoked", "--apply"]
    )
    assert hindsight_retract_args.agent_os_command == "hindsight"
    assert hindsight_retract_args.hindsight_command == "retract"
    assert hindsight_retract_args.record_id == "cmem_1"
    assert hindsight_retract_args.reason == "owner_revoked"
    assert hindsight_retract_args.apply is True
    hindsight_reflect_args = parser.parse_args(["hindsight", "reflect", "--query", "what pattern matters?", "--apply"])
    assert hindsight_reflect_args.agent_os_command == "hindsight"
    assert hindsight_reflect_args.hindsight_command == "reflect"
    assert hindsight_reflect_args.query == "what pattern matters?"
    assert hindsight_reflect_args.apply is True
    low_clue_args = parser.parse_args(["low-clue-recall", "dry-run", "--query", "继续昨天那个"])
    assert low_clue_args.agent_os_command == "low-clue-recall"
    assert low_clue_args.low_clue_recall_command == "dry-run"
    assert low_clue_args.query == "继续昨天那个"
    last_args = parser.parse_args(["memory-sources", "last"])
    assert last_args.agent_os_command == "memory-sources"
    assert last_args.memory_sources_command == "last"
    history_args = parser.parse_args(["memory-sources", "history", "--limit", "5"])
    assert history_args.memory_sources_command == "history"
    assert history_args.limit == 5
    stats_args = parser.parse_args(["memory-sources", "stats", "--hours", "24"])
    assert stats_args.memory_sources_command == "stats"
    assert stats_args.hours == 24
    feedback_args = parser.parse_args(["memory-sources", "feedback", "last", "--rating", "useful"])
    assert feedback_args.memory_sources_command == "feedback"
    assert feedback_args.memory_sources_feedback_command == "last"
    assert feedback_args.rating == "useful"
    feedback_history_args = parser.parse_args(["memory-sources", "feedback", "history", "--limit", "3"])
    assert feedback_history_args.memory_sources_feedback_command == "history"
    assert feedback_history_args.limit == 3
    session_status_args = parser.parse_args(["session-mirror", "status"])
    assert session_status_args.agent_os_command == "session-mirror"
    assert session_status_args.session_mirror_command == "status"
    session_apply_status_args = parser.parse_args(["session-mirror", "apply-status"])
    assert session_apply_status_args.session_mirror_command == "apply-status"
    session_scan_args = parser.parse_args(
        [
            "session-mirror",
            "scan",
            "--apply",
            "--max-sessions",
            "1",
            "--platform",
            "telegram",
            "--test-host",
            "--evidence-ref",
            "test:session-mirror",
        ]
    )
    assert session_scan_args.session_mirror_command == "scan"
    assert session_scan_args.apply is True
    assert session_scan_args.max_sessions == 1
    assert session_scan_args.platform == ["telegram"]
    assert session_scan_args.test_host is True
    assert session_scan_args.evidence_ref == ["test:session-mirror"]
    review_status_args = parser.parse_args(["review", "status"])
    assert review_status_args.agent_os_command == "review"
    assert review_status_args.review_command == "status"
    review_aging_args = parser.parse_args(["review", "aging-report"])
    assert review_aging_args.review_command == "aging-report"
    review_queue_args = parser.parse_args(["review", "queue", "--limit", "4"])
    assert review_queue_args.review_command == "queue"
    assert review_queue_args.limit == 4
    review_followups_args = parser.parse_args(["review", "proposal-followups", "--limit", "4"])
    assert review_followups_args.review_command == "proposal-followups"
    assert review_followups_args.limit == 4
    review_followups_gate_args = parser.parse_args(
        ["review", "proposal-followups", "--proposal-id", "prop_1", "--ops-gate", "--apply"]
    )
    assert review_followups_gate_args.review_command == "proposal-followups"
    assert review_followups_gate_args.proposal_id == "prop_1"
    assert review_followups_gate_args.ops_gate is True
    assert review_followups_gate_args.apply is True
    review_followups_all_args = parser.parse_args(
        ["review", "proposal-followups", "--ops-gate", "--all-pending", "--apply"]
    )
    assert review_followups_all_args.review_command == "proposal-followups"
    assert review_followups_all_args.ops_gate is True
    assert review_followups_all_args.all_pending is True
    assert review_followups_all_args.apply is True
    review_followups_auto_args = parser.parse_args(
        ["review", "proposal-followups", "--auto-route", "--apply"]
    )
    assert review_followups_auto_args.review_command == "proposal-followups"
    assert review_followups_auto_args.auto_route is True
    assert review_followups_auto_args.apply is True
    review_followups_apply_args = parser.parse_args(
        [
            "review",
            "proposal-followups",
            "--proposal-id",
            "prop_1",
            "--execution-apply",
            "--owner-approved",
            "--apply",
        ]
    )
    assert review_followups_apply_args.review_command == "proposal-followups"
    assert review_followups_apply_args.proposal_id == "prop_1"
    assert review_followups_apply_args.execution_apply is True
    assert review_followups_apply_args.owner_approved is True
    assert review_followups_apply_args.apply is True
    review_channel_args = parser.parse_args(["review", "channel"])
    assert review_channel_args.review_command == "channel"
    review_cron_status_args = parser.parse_args(["review", "cron-status"])
    assert review_cron_status_args.review_command == "cron-status"
    review_delivery_gate_args = parser.parse_args(["review", "delivery-gate", "--owner", "owner"])
    assert review_delivery_gate_args.review_command == "delivery-gate"
    assert review_delivery_gate_args.owner == "owner"
    review_delivery_status_args = parser.parse_args(["review", "delivery-status"])
    assert review_delivery_status_args.review_command == "delivery-status"
    review_deliver_once_args = parser.parse_args(
        [
            "review",
            "deliver-once",
            "--owner",
            "owner",
            "--delivery-key",
            "rh34d-test",
            "--owner-triggered",
            "--apply",
        ]
    )
    assert review_deliver_once_args.review_command == "deliver-once"
    assert review_deliver_once_args.owner == "owner"
    assert review_deliver_once_args.delivery_key == "rh34d-test"
    assert review_deliver_once_args.owner_triggered is True
    assert review_deliver_once_args.apply is True
    review_preview_args = parser.parse_args(
        [
            "review",
            "preview-digest",
            "--owner",
            "owner",
            "--max-action-required",
            "2",
            "--max-review-suggested",
            "3",
            "--max-fyi",
            "4",
            "--mode",
            "agenda",
        ]
    )
    assert review_preview_args.review_command == "preview-digest"
    assert review_preview_args.owner == "owner"
    assert review_preview_args.max_action_required == 2
    assert review_preview_args.max_review_suggested == 3
    assert review_preview_args.max_fyi == 4
    assert review_preview_args.mode == "agenda"
    review_render_args = parser.parse_args(
        [
            "review",
            "render-digest",
            "--owner",
            "owner",
            "--channel",
            "telegram",
            "--format",
            "text",
            "--bounded",
            "--record-active",
            "--mode",
            "agenda",
        ]
    )
    assert review_render_args.review_command == "render-digest"
    assert review_render_args.owner == "owner"
    assert review_render_args.channel == "telegram"
    assert review_render_args.format == "text"
    assert review_render_args.bounded is True
    assert review_render_args.record_active is True
    assert review_render_args.mode == "agenda"
    review_surface_args = parser.parse_args(
        [
            "review",
            "surface",
            "--operation",
            "detail",
            "--anchor",
            "R3",
            "--limit",
            "2",
            "--channel",
            "telegram",
        ]
    )
    assert review_surface_args.review_command == "surface"
    assert review_surface_args.operation == "detail"
    assert review_surface_args.anchor == "R3"
    assert review_surface_args.limit == 2
    assert review_surface_args.channel == "telegram"
    review_reply_args = parser.parse_args(
        ["review", "reply", "approve", "A1", "--owner", "owner", "--digest-id", "odig_test", "--apply"]
    )
    assert review_reply_args.review_command == "reply"
    assert review_reply_args.reply == ["approve", "A1"]
    assert review_reply_args.owner == "owner"
    assert review_reply_args.digest_id == "odig_test"
    assert review_reply_args.apply is True
    review_apply_args = parser.parse_args(
        [
            "review",
            "apply",
            "--action",
            "approve_candidate",
            "--target",
            "candidate:cand_1",
            "--owner",
            "owner",
            "--apply",
        ]
    )
    assert review_apply_args.review_command == "apply"
    assert review_apply_args.action == "approve_candidate"
    assert review_apply_args.target == "candidate:cand_1"
    assert review_apply_args.owner == "owner"
    assert review_apply_args.apply is True
    review_apply_proposal_args = parser.parse_args(
        [
            "review",
            "apply",
            "--action",
            "apply_proposal",
            "--target",
            "proposal:prop_1",
            "--apply",
        ]
    )
    assert review_apply_proposal_args.review_command == "apply"
    assert review_apply_proposal_args.action == "apply_proposal"
    assert review_apply_proposal_args.target == "proposal:prop_1"
    assert review_apply_proposal_args.apply is True
    review_revoke_crystallized_args = parser.parse_args(
        [
            "review",
            "apply",
            "--action",
            "revoke_crystallized",
            "--target",
            "crystallized:cmem_1",
            "--apply",
        ]
    )
    assert review_revoke_crystallized_args.review_command == "apply"
    assert review_revoke_crystallized_args.action == "revoke_crystallized"
    assert review_revoke_crystallized_args.target == "crystallized:cmem_1"
    assert review_revoke_crystallized_args.apply is True
    expression_feedback_args = parser.parse_args(
        ["review", "apply", "--action", "too_mechanical", "--target", "expr_123"]
    )
    assert expression_feedback_args.review_command == "apply"
    assert expression_feedback_args.action == "too_mechanical"
    assert expression_feedback_args.target == "expr_123"
    metadata_retention_args = parser.parse_args(
        ["metadata-retention", "--memory-sources-days", "30", "--eval-report-root", "eval/reports/memory-os-rh31"]
    )
    assert metadata_retention_args.agent_os_command == "metadata-retention"
    assert metadata_retention_args.memory_sources_days == 30
    assert metadata_retention_args.eval_report_root == "eval/reports/memory-os-rh31"
    modules_status_args = parser.parse_args(["modules", "status"])
    assert modules_status_args.agent_os_command == "modules"
    assert modules_status_args.modules_command == "status"
    modules_doctor_args = parser.parse_args(["modules", "doctor"])
    assert modules_doctor_args.modules_command == "doctor"
    modules_run_once_args = parser.parse_args(["modules", "run-once", "--module", "cron_mirror", "--dry-run"])
    assert modules_run_once_args.modules_command == "run-once"
    assert modules_run_once_args.module == "cron_mirror"
    assert modules_run_once_args.dry_run is True
    modules_validate_args = parser.parse_args(["modules", "validate-no-send"])
    assert modules_validate_args.modules_command == "validate-no-send"
    dr_history_args = parser.parse_args(["modules", "deep_reflection", "history", "--days", "3"])
    assert dr_history_args.modules_command == "deep_reflection"
    assert dr_history_args.deep_reflection_command == "history"
    assert dr_history_args.days == 3
    eval_run_args = parser.parse_args(["eval", "rh31", "run", "--fixture", "synthetic", "--adapter", "grep"])
    assert eval_run_args.agent_os_command == "eval"
    assert eval_run_args.eval_command == "rh31"
    assert eval_run_args.rh31_command == "run"
    assert eval_run_args.fixture == "synthetic"
    assert eval_run_args.adapter == ["grep"]
    cognitive_loop_args = parser.parse_args(["cognitive-loop", "run-once", "--test-host", "--apply"])
    assert cognitive_loop_args.agent_os_command == "cognitive-loop"
    assert cognitive_loop_args.cognitive_loop_command == "run-once"
    assert cognitive_loop_args.test_host is True
    assert cognitive_loop_args.apply is True
    host_probe_args = parser.parse_args(["host-probe", "--json"])
    assert host_probe_args.agent_os_command == "host-probe"
    assert host_probe_args.json is True
    manifest_args = parser.parse_args(["deployment-manifest", "status"])
    assert manifest_args.agent_os_command == "deployment-manifest"
    assert manifest_args.deployment_manifest_command == "status"
    signal_sources_args = parser.parse_args(["signal-sources", "--json"])
    assert signal_sources_args.agent_os_command == "signal-sources"
    assert signal_sources_args.json is True
    projection_args = parser.parse_args(["projection", "collect", "--manual-run-ref", "agent-shell-test"])
    assert projection_args.agent_os_command == "projection"
    assert projection_args.projection_command == "collect"
    assert projection_args.manual_run_ref == "agent-shell-test"
    projection_retention_args = parser.parse_args(["projection", "retention-status"])
    assert projection_retention_args.agent_os_command == "projection"
    assert projection_retention_args.projection_command == "retention-status"
    projection_compact_args = parser.parse_args(
        ["projection", "compact", "--apply", "--keep-latest-status-per-source", "2"]
    )
    assert projection_compact_args.agent_os_command == "projection"
    assert projection_compact_args.projection_command == "compact"
    assert projection_compact_args.apply is True
    assert projection_compact_args.keep_latest_status_per_source == 2
    left_brain_args = parser.parse_args(["left-brain", "advise", "--max-findings", "5", "--no-write"])
    assert left_brain_args.agent_os_command == "left-brain"
    assert left_brain_args.left_brain_command == "advise"
    assert left_brain_args.max_findings == 5
    assert left_brain_args.no_write is True


def test_shell_status_alias_delegates_to_existing_memory_os_cli(monkeypatch, capsys):
    module = load_shell_module()
    calls: list[argparse.Namespace] = []

    def fake_delegate(args: argparse.Namespace) -> int:
        calls.append(args)
        print(json.dumps({"delegated": args.memory_os_command}, sort_keys=True))
        return 0

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", fake_delegate)
    args = argparse.Namespace(agent_os_command="status", passthrough="kept")

    assert module._memory_os_agent_os_exit_code(args) == 0
    assert json.loads(capsys.readouterr().out) == {"delegated": "status"}
    try:
        module.memory_os_agent_os_command(args)
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover - CLI handlers must terminate for Hermes to preserve exit codes.
        raise AssertionError("memory_os_agent_os_command did not exit")

    assert calls[0].memory_os_command == "status"
    assert calls[0].passthrough == "kept"
    assert json.loads(capsys.readouterr().out) == {"delegated": "status"}


def test_hindsight_status_reports_optional_off(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_status_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    report = hindsight_status_report(store)

    assert report["schema_version"] == "memory-os.hindsight_substrate_status.v0"
    assert report["enabled"] is False
    assert report["status"] == "optional_not_configured"
    assert report["direct_hermes_provider_active"] is False
    assert report["substrate_monitor"]["no_raw_retained"] is True


def test_hindsight_status_detects_direct_hermes_provider(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_status_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    (tmp_path / "config.yaml").write_text("memory:\n  provider: hindsight\n", encoding="utf-8")
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    report = hindsight_status_report(store)

    assert report["direct_hermes_provider_active"] is True


def test_hindsight_status_marks_retained_inactive_crystallized_projection_stale(tmp_path):
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.cli import hindsight_status_report
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.substrates.projection import ProjectionLedger

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    service = CrystallizedMemoryService(store)
    service.write_approved_record(
        CrystallizedCandidate(
            candidate_id="cand-stale-projection",
            kind="preference",
            body="User prefers projection stale checks.",
            source_event_ids=["evt-stale-projection"],
            sensitivity="public",
        ),
        ApprovalDecision(
            candidate_id="cand-stale-projection",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at="2026-06-01T00:00:00+00:00",
        ),
        file_name="owner_approved.md",
    )
    record_id = str(service.read_records("owner_approved.md")[0].frontmatter["id"])
    ProjectionLedger(roots.memory_os_root / "system" / "projection_ledger.jsonl").record_retain(
        provider="hindsight",
        source_record_ref=record_id,
        source_version="current",
        substrate_record_id="hindsight-stale-1",
        substrate_snapshot_id="hindsight:bank:v1",
    )
    service.demote_record(record_id, demoted_by="owner", reason="test direct demotion")

    report = hindsight_status_report(store)

    assert report["substrate_monitor"]["inactive_canonical_source_ref_count"] == 1
    assert report["substrate_monitor"]["projection_stale_count"] == 1


def test_hindsight_adopt_dry_run_reads_legacy_config_without_secrets(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_adopt_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    legacy_dir = tmp_path / "hindsight"
    legacy_dir.mkdir()
    (legacy_dir / "config.json").write_text(
        '{"api_url":"http://127.0.0.1:8888","bank_id":"hermes","apiKey":"SECRET","auto_retain":false}',
        encoding="utf-8",
    )

    report = hindsight_adopt_report(store, apply=False)

    assert report["schema_version"] == "memory-os.hindsight_adopt.v0"
    assert report["dry_run"] is True
    assert report["detected"]["bank_id"] == "hermes"
    assert report["detected"]["provider_bank_id"] == "hermes"
    assert report["detected"]["bank_selection_reason"] == "top_level_provider_bank_id"
    assert report["detected"]["api_key_configured"] is True
    assert "SECRET" not in str(report)
    assert report["planned_config"]["recall_mode"] == "shadow"
    assert report["planned_config"]["retain_enabled"] is False
    assert report["planned_config"]["legacy_auto_retain_observed_disabled"] is True


def test_hindsight_adopt_apply_updates_substrate_config_without_secret(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_adopt_report
    from plugins.memory.memory_os.config import load_config
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    legacy_dir = tmp_path / "hindsight"
    legacy_dir.mkdir()
    (legacy_dir / "config.json").write_text(
        '{"api_url":"http://127.0.0.1:8888","bank_id":"hermes","apiKey":"SECRET","auto_retain":false}',
        encoding="utf-8",
    )

    report = hindsight_adopt_report(store, apply=True)
    hindsight = load_config(tmp_path)["substrate_providers"]["hindsight"]

    assert report["dry_run"] is False
    assert hindsight["enabled"] is True
    assert hindsight["adoption_source"] == "hermes_hindsight_config"
    assert hindsight["provider_bank_id"] == "hermes"
    assert hindsight["bank_selection_reason"] == "top_level_provider_bank_id"
    assert hindsight["recall_mode"] == "shadow"
    assert hindsight["retain_enabled"] is False
    assert hindsight["api_key"] == ""


def test_doctor_does_not_warn_when_hindsight_is_optional_off(tmp_path):
    from plugins.memory.memory_os.cli import build_doctor_result
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    result = build_doctor_result(store)
    codes = {finding["code"] for finding in result["findings"]}

    assert "hindsight_adapter_disabled" not in codes


def test_hindsight_retain_pending_dry_run_is_no_write(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_retain_pending_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    report = hindsight_retain_pending_report(store, apply=False)

    assert report["schema_version"] == "memory-os.hindsight_retain_pending.v0"
    assert report["dry_run"] is True
    assert report["actual_retain"] is False
    assert report["raw_body_included"] is False
    assert report["ledger_write"] is False


def test_hindsight_retract_dry_run_is_no_delete(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_retract_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    report = hindsight_retract_report(store, record_id="cmem_1", reason="owner_revoked", apply=False)

    assert report["schema_version"] == "memory-os.hindsight_retract.v0"
    assert report["dry_run"] is True
    assert report["actual_delete"] is False
    assert report["invalidation_reason"] == "owner_revoked"


def test_hindsight_reflect_dry_run_reports_disabled_by_default(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_reflect_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    report = hindsight_reflect_report(store, query="what pattern matters?", apply=False)

    assert report["schema_version"] == "memory-os.hindsight_reflect.v0"
    assert report["status"] == "disabled"
    assert report["off_hot_path"] is True
    assert report["actual_canonical_write"] is False


def test_hindsight_reflect_apply_queues_owner_review_candidate(monkeypatch, tmp_path):
    from plugins.memory.memory_os import cli as memory_cli
    from plugins.memory.memory_os.config import save_config
    from plugins.memory.memory_os.crystallized import read_candidate_queue
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    class FakeClient:
        def reflect(self, *, bank_id, query, budget):
            return {"text": "Hindsight synthesized a bounded pattern for owner review."}

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    save_config(
        {
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "api_url": "http://127.0.0.1:8888",
                    "bank_id": "bank",
                    "recall_mode": "active",
                    "reflect_enabled": True,
                }
            }
        },
        tmp_path,
    )
    monkeypatch.setattr(memory_cli, "_hindsight_http_client_from_config", lambda substrate: FakeClient())

    report = memory_cli.hindsight_reflect_report(store, query="what pattern matters?", apply=True)

    candidates = read_candidate_queue(store)
    assert report["status"] == "ok"
    assert report["candidate_queued"] is True
    assert report["actual_canonical_write"] is False
    assert report["owner_gate_required"] is True
    assert candidates[0].kind == "hindsight_reflect_candidate"
    assert candidates[0].body == "Hindsight synthesized a bounded pattern for owner review."


def test_hindsight_reflect_apply_reports_provider_error_without_candidate(monkeypatch, tmp_path):
    from plugins.memory.memory_os import cli as memory_cli
    from plugins.memory.memory_os.config import save_config
    from plugins.memory.memory_os.crystallized import read_candidate_queue
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.substrates.ledger import SubstrateOperationLedger

    class FailingClient:
        def reflect(self, *, bank_id, query, budget):
            raise RuntimeError("hindsight request failed: timed out")

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    save_config(
        {
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "api_url": "http://127.0.0.1:8888",
                    "bank_id": "bank",
                    "recall_mode": "active",
                    "reflect_enabled": True,
                }
            }
        },
        tmp_path,
    )
    monkeypatch.setattr(memory_cli, "_hindsight_http_client_from_config", lambda substrate: FailingClient())

    report = memory_cli.hindsight_reflect_report(store, query="what pattern matters?", apply=True)
    records = SubstrateOperationLedger(store.roots.memory_os_root / "system" / "substrate_operations.jsonl").read_all()

    assert report["status"] == "error"
    assert report["candidate_queued"] is False
    assert report["actual_canonical_write"] is False
    assert report["owner_gate_required"] is True
    assert "timed out" in report["reason"]
    assert read_candidate_queue(store) == []
    assert records[-1]["operation"] == "reflect"
    assert records[-1]["status"] == "error"
    assert records[-1]["candidate_queued"] is False


def test_shell_memory_sources_alias_delegates_to_existing_memory_os_cli(monkeypatch, capsys):
    module = load_shell_module()
    calls: list[argparse.Namespace] = []

    def fake_delegate(args: argparse.Namespace) -> int:
        calls.append(args)
        print(json.dumps({"delegated": args.memory_os_command, "subcommand": args.memory_sources_command}))
        return 0

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", fake_delegate)
    args = argparse.Namespace(agent_os_command="memory-sources", memory_sources_command="stats", hours=24)

    assert module._memory_os_agent_os_exit_code(args) == 0

    assert calls[0].memory_os_command == "memory-sources"
    assert calls[0].memory_sources_command == "stats"
    assert json.loads(capsys.readouterr().out) == {
        "delegated": "memory-sources",
        "subcommand": "stats",
    }


def test_shell_low_clue_recall_alias_delegates_to_existing_memory_os_cli(monkeypatch, capsys):
    module = load_shell_module()
    calls: list[argparse.Namespace] = []

    def fake_delegate(args: argparse.Namespace) -> int:
        calls.append(args)
        print(json.dumps({"delegated": args.memory_os_command, "subcommand": args.low_clue_recall_command}))
        return 0

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", fake_delegate)
    args = argparse.Namespace(
        agent_os_command="low-clue-recall",
        low_clue_recall_command="dry-run",
        query="继续昨天那个",
    )

    assert module._memory_os_agent_os_exit_code(args) == 0

    assert calls[0].memory_os_command == "low-clue-recall"
    assert calls[0].low_clue_recall_command == "dry-run"
    assert json.loads(capsys.readouterr().out) == {
        "delegated": "low-clue-recall",
        "subcommand": "dry-run",
    }


def test_shell_modules_alias_delegates_to_existing_memory_os_cli(monkeypatch, capsys):
    module = load_shell_module()
    calls: list[argparse.Namespace] = []

    def fake_delegate(args: argparse.Namespace) -> int:
        calls.append(args)
        print(json.dumps({"delegated": args.memory_os_command, "subcommand": args.modules_command}))
        return 0

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", fake_delegate)
    args = argparse.Namespace(
        agent_os_command="modules",
        modules_command="run-once",
        module="cron_mirror",
        dry_run=True,
        apply=False,
    )

    assert module._memory_os_agent_os_exit_code(args) == 0

    assert calls[0].memory_os_command == "modules"
    assert calls[0].modules_command == "run-once"
    assert calls[0].module == "cron_mirror"
    assert json.loads(capsys.readouterr().out) == {
        "delegated": "modules",
        "subcommand": "run-once",
    }


def test_shell_eval_alias_delegates_to_existing_memory_os_cli(monkeypatch, capsys):
    module = load_shell_module()
    calls: list[argparse.Namespace] = []

    def fake_delegate(args: argparse.Namespace) -> int:
        calls.append(args)
        print(json.dumps({"delegated": args.memory_os_command, "subcommand": args.eval_command}))
        return 0

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", fake_delegate)
    args = argparse.Namespace(
        agent_os_command="eval",
        eval_command="rh31",
        rh31_command="run",
        fixture="synthetic",
        adapter=["grep"],
    )

    assert module._memory_os_agent_os_exit_code(args) == 0

    assert calls[0].memory_os_command == "eval"
    assert calls[0].eval_command == "rh31"
    assert calls[0].rh31_command == "run"
    assert json.loads(capsys.readouterr().out) == {
        "delegated": "eval",
        "subcommand": "rh31",
    }


def test_shell_unknown_alias_fails_closed():
    module = load_shell_module()

    result = module._memory_os_agent_os_exit_code(argparse.Namespace(agent_os_command="heartbeat"))

    assert result == 2


def test_shell_handler_exits_with_delegate_code(monkeypatch):
    module = load_shell_module()

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", lambda args: 7)

    try:
        module.memory_os_agent_os_command(argparse.Namespace(agent_os_command="status"))
    except SystemExit as exc:
        assert exc.code == 7
    else:  # pragma: no cover - Hermes ignores returned handler codes.
        raise AssertionError("memory_os_agent_os_command did not exit")


def test_shell_fails_closed_when_memory_os_runtime_is_missing(monkeypatch, capsys):
    module = load_shell_module()

    def missing_runtime():
        raise ModuleNotFoundError("No module named 'plugins.memory.memory_os'")

    monkeypatch.setattr(module, "_load_memory_os_command", missing_runtime)

    result = module._memory_os_agent_os_exit_code(argparse.Namespace(agent_os_command="status"))

    assert result == 1
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "memory-os.agent_os_shell.v0"
    assert report["status"] == "error"
    assert report["code"] == "memory_os_provider_missing"


def test_shell_runtime_path_extends_existing_plugins_namespace(monkeypatch, tmp_path):
    module = load_shell_module()
    hermes_home = tmp_path / "home"
    runtime_root = hermes_home / "memory-os" / "runtime" / "python"
    runtime_plugins = runtime_root / "plugins"
    runtime_memory = runtime_plugins / "memory"
    runtime_plugins.mkdir(parents=True)
    runtime_memory.mkdir()
    existing_plugins = ModuleType("plugins")
    existing_plugins.__path__ = ["bundled/plugins"]  # type: ignore[attr-defined]
    existing_memory = ModuleType("plugins.memory")
    existing_memory.__path__ = ["bundled/plugins/memory"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "plugins", existing_plugins)
    monkeypatch.setitem(sys.modules, "plugins.memory", existing_memory)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    module._ensure_memory_os_runtime_path()

    assert str(runtime_root) in sys.path
    assert str(runtime_plugins) in existing_plugins.__path__  # type: ignore[attr-defined]
    assert str(runtime_memory) in existing_memory.__path__  # type: ignore[attr-defined]


def test_shell_runtime_path_adds_flat_provider_parent(monkeypatch, tmp_path):
    module = load_shell_module()
    hermes_home = tmp_path / "home"
    flat_provider = hermes_home / "plugins" / "memory_os"
    flat_provider.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    module._ensure_memory_os_runtime_path()

    assert str(hermes_home / "plugins") in sys.path


def test_shell_runtime_path_infers_hermes_home_from_installed_plugin_without_env(monkeypatch, tmp_path):
    original_sys_path = list(sys.path)
    hermes_home = tmp_path / "home"
    installed_shell = hermes_home / "plugins" / "memory-os-agent-os"
    installed_shell.mkdir(parents=True)
    shell_init = installed_shell / "__init__.py"
    shell_init.write_text((SHELL_DIR / "__init__.py").read_text(encoding="utf-8"), encoding="utf-8")
    runtime_root = hermes_home / "memory-os" / "runtime" / "python"
    runtime_root.mkdir(parents=True)
    flat_provider = hermes_home / "plugins" / "memory_os"
    flat_provider.mkdir(parents=True)
    monkeypatch.delenv("HERMES_HOME", raising=False)

    try:
        module = load_shell_module_from(shell_init)
        module._ensure_memory_os_runtime_path()

        assert str(runtime_root) in sys.path
        assert str(hermes_home / "plugins") in sys.path
    finally:
        sys.path[:] = original_sys_path
        _clear_imported_memory_os_modules()


def test_shell_alias_imports_provider_from_inferred_runtime_without_env(monkeypatch, tmp_path, capsys):
    original_sys_path = list(sys.path)
    hermes_home = tmp_path / "home"
    installed_shell = hermes_home / "plugins" / "memory-os-agent-os"
    installed_shell.mkdir(parents=True)
    shell_init = installed_shell / "__init__.py"
    shell_init.write_text((SHELL_DIR / "__init__.py").read_text(encoding="utf-8"), encoding="utf-8")
    runtime_pkg = hermes_home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os"
    runtime_pkg.mkdir(parents=True)
    for package in [
        runtime_pkg.parents[2],
        runtime_pkg.parents[1],
        runtime_pkg.parent,
        runtime_pkg,
    ]:
        package.joinpath("__init__.py").write_text("", encoding="utf-8")
    runtime_pkg.joinpath("cli.py").write_text(
        "def memory_os_command(args):\n"
        "    print('{\"status\":\"ok\",\"delegated\":\"%s\"}' % args.memory_os_command)\n"
        "    return 0\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("HERMES_HOME", raising=False)
    for name in [
        "plugins",
        "plugins.memory",
        "plugins.memory.memory_os",
        "plugins.memory.memory_os.cli",
    ]:
        sys.modules.pop(name, None)

    try:
        module = load_shell_module_from(shell_init, name="memory_os_agent_os_shell_installed_runtime")

        result = module._memory_os_agent_os_exit_code(argparse.Namespace(agent_os_command="status"))

        assert result == 0
        assert json.loads(capsys.readouterr().out) == {"delegated": "status", "status": "ok"}
    finally:
        sys.path[:] = original_sys_path
        _clear_imported_memory_os_modules()


def test_shell_session_start_hook_writes_bounded_audit_marker(monkeypatch, tmp_path):
    module = load_shell_module()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    module._on_session_start(session_id="sess-1", platform="telegram", model="test-model")

    entries = _audit_entries(tmp_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "agent_os_shell_session_started"
    assert entry["status"] == "ok"
    assert entry["target"] == "memory-os-agent-os"
    assert entry["details"] == {
        "hook": "on_session_start",
        "model": "test-model",
        "platform": "telegram",
        "session_id": "sess-1",
    }


def test_shell_session_reset_and_finalize_hooks_write_audit_markers(monkeypatch, tmp_path):
    module = load_shell_module()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    module._on_session_reset(session_id="new-session", platform="telegram")
    module._on_session_finalize(session_id="old-session", platform="telegram")

    actions = [entry["action"] for entry in _audit_entries(tmp_path)]
    assert actions == [
        "agent_os_shell_session_reset",
        "agent_os_shell_session_finalized",
    ]


def test_shell_session_hooks_skip_without_hermes_home(monkeypatch, tmp_path):
    module = load_shell_module()
    monkeypatch.delenv("HERMES_HOME", raising=False)

    module._on_session_start(session_id="sess-1", platform="telegram", model="test-model")

    assert not (tmp_path / "memory-os" / "audit" / "write_audit.jsonl").exists()


def _audit_entries(hermes_home: Path) -> list[dict[str, Any]]:
    audit_path = hermes_home / "memory-os" / "audit" / "write_audit.jsonl"
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]


def _clear_imported_memory_os_modules() -> None:
    for name in [
        "plugins",
        "plugins.memory",
        "plugins.memory.memory_os",
        "plugins.memory.memory_os.cli",
        "memory_os",
        "memory_os.cli",
    ]:
        sys.modules.pop(name, None)
