from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.fixtures import build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.expression.speak_gate import SpeakGateModule, speak_gate_manifest
from plugins.modules.governance.proposal_queue import ProposalQueueModule
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_speak_gate_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler", "proposal_queue"),
    )

    status = lifecycle.install(speak_gate_manifest())
    enabled = lifecycle.enable("speak_gate")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "would-send"
    assert lifecycle.doctor("speak_gate").status == "ok"


def test_speak_gate_distinguishes_no_send_would_send_and_send_without_real_delivery(tmp_path):
    no_send = SpeakGateModule(tmp_path / "no-send", profile="main", delivery_mode="no-send")
    would_send = SpeakGateModule(tmp_path / "would-send", profile="main", delivery_mode="would-send")
    send = SpeakGateModule(tmp_path / "send", profile="main", delivery_mode="send")

    no_send_result = no_send.evaluate_delivery(
        payload_ref="local://payload/no-send",
        source_module="self_evolution",
        channel="telegram",
    )
    would_send_result = would_send.evaluate_delivery(
        payload_ref="local://payload/would-send",
        source_module="self_evolution",
        channel="telegram",
    )
    send_result = send.evaluate_delivery(
        payload_ref="local://payload/send",
        source_module="self_evolution",
        channel="telegram",
    )

    assert no_send_result["decision"] == "no_send"
    assert no_send_result["actual_send"] is False
    assert no_send.read_would_send_records() == []
    assert would_send_result["decision"] == "would_send"
    assert would_send_result["actual_send"] is False
    assert len(would_send.read_would_send_records()) == 1
    assert send_result["decision"] == "send_blocked"
    assert send_result["requested_delivery_mode"] == "send"
    assert send_result["actual_send"] is False
    assert send.doctor()["status"] == "error"


def test_speak_gate_diagnostic_mode_is_profile_configured(tmp_path):
    main = SpeakGateModule(tmp_path / "main", profile="main")
    sannai_default = SpeakGateModule(tmp_path / "sannai", profile="sannai")
    sannai_explicit = SpeakGateModule(
        tmp_path / "sannai-explicit",
        profile="sannai",
        diagnostic_grounding_enabled=True,
    )

    main_decision = main.evaluate_prompt("当前记忆架构是什么？Hindsight 是 canonical store 吗？")
    default_decision = sannai_default.evaluate_prompt("当前记忆架构是什么？")
    explicit_decision = sannai_explicit.evaluate_prompt("当前记忆架构是什么？")

    assert main_decision["context_mode"] == "diagnostic_runtime_facts"
    assert main_decision["system_report_allowed"] is True
    assert default_decision["context_mode"] == "ordinary_recall"
    assert default_decision["system_report_allowed"] is False
    assert explicit_decision["context_mode"] == "diagnostic_runtime_facts"


def test_speak_gate_sannai_style_self_memory_prompt_does_not_trigger_system_report(tmp_path):
    module = SpeakGateModule(tmp_path, profile="sannai")

    decision = module.evaluate_prompt("三奶，你还记得我们昨天说过的话吗？你现在心里在想什么？")

    assert decision["context_mode"] == "ordinary_self_memory"
    assert decision["diagnostic"] is False
    assert decision["system_report_allowed"] is False


def test_speak_gate_keeps_wandering_mind_non_task(tmp_path):
    module = SpeakGateModule(tmp_path, profile="main")

    silent = module.evaluate_wandering_output("[SILENT]", channel="origin")
    spoken = module.evaluate_wandering_output("今天我在那些片段里停了一下。", channel="origin")

    assert silent["decision"] == "no_send"
    assert silent["reason"] == "wandering_mind_silent"
    assert spoken["decision"] == "would_send"
    assert spoken["actual_send"] is False
    records = module.read_would_send_records()
    assert len(records) == 1
    assert records[0]["source_module"] == "wandering_mind"
    assert records[0]["created_at"] == records[0]["ts"]
    assert "proposal" not in records[0]
    assert "agenda" not in records[0]
    assert "task" not in records[0]


def test_speak_gate_evaluates_expression_draft_with_silent_and_error_counts(tmp_path):
    module = SpeakGateModule(tmp_path, profile="main")
    silent = {
        "draft_id": "expr_silent",
        "text_preview": "[SILENT]",
        "source_module": "wandering_mind",
        "raw_body_included": False,
    }
    spoken = {
        "draft_id": "expr_spoken",
        "text_preview": "今天我想把这个瞬间轻轻放下。",
        "source_module": "wandering_mind",
        "raw_body_included": False,
    }

    silent_decision = module.evaluate_expression_draft(silent, channel="origin")
    spoken_decision = module.evaluate_expression_draft(spoken, channel="origin")

    assert silent_decision["decision"] == "silent"
    assert silent_decision["actual_send"] is False
    assert spoken_decision["decision"] == "would_send"
    assert spoken_decision["draft_id"] == "expr_spoken"
    assert spoken_decision["payload_ref"] == "local://expression_draft/expr_spoken"
    assert len(module.read_would_send_records()) == 1


def test_speak_gate_requires_proposal_queue_approval_before_would_send(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidate = proposal_queue.create_candidate(
        store=store,
        title="Speak later",
        body="This should stay pending until owner review.",
    )
    module = SpeakGateModule(tmp_path, profile="main")

    pending = module.evaluate_proposal(candidate["candidate_id"], proposal_queue=proposal_queue)
    proposal_queue.transition(
        store=store,
        candidate_id=candidate["candidate_id"],
        decision="approve",
        reviewer="owner",
    )
    approved = module.evaluate_proposal(candidate["candidate_id"], proposal_queue=proposal_queue)

    assert pending["decision"] == "no_send"
    assert pending["reason"] == "proposal_not_approved"
    assert approved["decision"] == "would_send"
    assert approved["actual_send"] is False
    assert module.read_would_send_records()[0]["payload_ref"].endswith(candidate["candidate_id"])


def test_speak_gate_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    module = SpeakGateModule(tmp_path / "main", profile="main")

    module.evaluate_delivery(
        payload_ref="local://payload/main",
        source_module="self_evolution",
        channel="origin",
    )

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()


def test_speak_gate_owner_send_delivers_when_channel_matches_owner(tmp_path):
    store = _store(tmp_path)
    save_config(
        {"owner_review": {"mode": "active", "enabled": True, "channel": "telegram", "target_ref": "owner_123"}},
        store.roots.hermes_home,
    )
    module = SpeakGateModule(
        tmp_path,
        profile="main",
        delivery_mode="owner-send",
        store=store,
    )
    result = module.evaluate_delivery(
        payload_ref="local://payload/owner-test",
        source_module="wandering_mind",
        channel="telegram",
    )
    assert result["decision"] == "delivered"
    assert result["actual_send"] is True
    assert result["requested_delivery_mode"] == "owner-send"
    assert "delivery_id" in result
    delivery_dir = tmp_path / "delivery" / "outbox"
    delivery_files = list(delivery_dir.glob("*.json"))
    assert len(delivery_files) == 1


def test_speak_gate_owner_send_blocks_non_owner_channel(tmp_path):
    store = _store(tmp_path)
    save_config(
        {"owner_review": {"mode": "active", "enabled": True, "channel": "telegram", "target_ref": "owner_123"}},
        store.roots.hermes_home,
    )
    module = SpeakGateModule(
        tmp_path,
        profile="main",
        delivery_mode="owner-send",
        store=store,
    )
    result = module.evaluate_delivery(
        payload_ref="local://payload/world-test",
        source_module="inner_drive",
        channel="origin",
    )
    assert result["decision"] == "send_blocked"
    assert result["actual_send"] is False
    assert "channel_mismatch" in result["reason"]
    delivery_dir = tmp_path / "delivery" / "outbox"
    assert not delivery_dir.exists() or len(list(delivery_dir.glob("*.json"))) == 0


def test_speak_gate_owner_send_requires_store(tmp_path):
    module = SpeakGateModule(
        tmp_path,
        profile="main",
        delivery_mode="owner-send",
    )
    result = module.evaluate_delivery(
        payload_ref="local://payload/no-store-test",
        source_module="wandering_mind",
        channel="telegram-direct",
    )
    assert result["decision"] == "send_blocked"
    assert result["reason"] == "owner_send_requires_store"
    assert result["actual_send"] is False


def test_speak_gate_owner_send_status_reflects_deliveries(tmp_path):
    store = _store(tmp_path)
    save_config(
        {"owner_review": {"mode": "active", "enabled": True, "channel": "telegram", "target_ref": "owner_123"}},
        store.roots.hermes_home,
    )
    module = SpeakGateModule(
        tmp_path,
        profile="main",
        delivery_mode="owner-send",
        store=store,
    )
    status_before = module.status()
    assert status_before["actual_send"] is False

    module.evaluate_delivery(
        payload_ref="local://payload/status-test",
        source_module="wandering_mind",
        channel="telegram",
    )
    status_after = module.status()
    assert status_after["actual_send"] is True
    assert status_after["delivery_count"] == 1