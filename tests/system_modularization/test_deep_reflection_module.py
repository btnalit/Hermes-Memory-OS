import json

from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture, build_working_item
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.working import WorkingMemoryService
from plugins.modules.cognition import DeepReflectionModule, deep_reflection_manifest
from plugins.modules.context.digest_consolidation import DigestConsolidationModule
from plugins.modules.evidence.scoring import EvidenceScoringModule
from plugins.modules.governance.proposal_queue import ProposalQueueModule
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_deep_reflection_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler", "continuity_selector", "inner_drive"),
    )

    status = lifecycle.install(deep_reflection_manifest())
    enabled = lifecycle.enable("deep_reflection")

    assert status.installed is True
    assert status.enabled is False
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("deep_reflection").status == "ok"


def test_deep_reflection_status_defaults_to_no_injection(tmp_path):
    module = DeepReflectionModule(tmp_path, profile="main")

    status = module.status()

    assert status["schema_version"] == "hermes.deep_reflection_status.v0"
    assert status["module"] == "deep_reflection"
    assert status["profile"] == "main"
    assert status["enabled"] is False
    assert status["injection_mode"] == "disabled"
    assert status["actual_send"] is False
    assert status["actual_execute"] is False
    assert status["actual_identity_write"] is False
    assert status["actual_crystallized_approval"] is False


def test_deep_reflection_dry_run_writes_local_report_without_memory_events(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=1, profile="main")))
    before_event_count = len(store.read_events())
    module = DeepReflectionModule(tmp_path, profile="main")

    result = module.run_once(store=store, dry_run=True)

    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["injection_mode"] == "disabled"
    assert result["analysis_artifact_created"] is True
    assert result["actual_send"] is False
    assert result["actual_execute"] is False
    assert len(store.read_events()) == before_event_count
    assert module.current_injection_path.exists()
    current = json.loads(module.current_injection_path.read_text(encoding="utf-8"))
    assert current["injection_mode"] == "disabled"
    assert module.reports_path.exists()


def test_deep_reflection_collects_bounded_inputs_without_private_bodies(tmp_path):
    store = _store(tmp_path)
    main_event = EventEnvelope.from_dict(
        {
            **build_event(seed=10, profile="main"),
            "ts": "2026-05-21T01:00:00+00:00",
            "kind": "conversation_turn",
            "summary": "Owner asked about Deep Reflection continuity.",
        }
    )
    governance_event = EventEnvelope.from_dict(
        {
            **build_event(seed=11, profile="main"),
            "ts": "2026-05-21T02:00:00+00:00",
            "source": "governance_feedback",
            "kind": "governance_proposal_created",
            "summary": "Governance feedback reports a proposal backlog item.",
            "safe_ref": {"source_class": "governance", "artifact_ref": "local://proposal_queue/candidates/abc"},
        }
    )
    other_profile_event = EventEnvelope.from_dict(
        {
            **build_event(seed=12, profile="other"),
            "summary": "Other profile private summary must not leak.",
        }
    )
    store.append_event(main_event)
    store.append_event(governance_event)
    store.append_event(other_profile_event)
    WorkingMemoryService(store).add_item(
        "lingering",
        "Keep attention on bounded reflection input surfaces.",
        source_event_id=main_event.id,
    )
    DigestConsolidationModule(tmp_path, profile="main").build_daily_digest(
        store=store,
        target_date="2026-05-21",
        dry_run=False,
    )
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(
        store=store,
        title="Improve reflection collector",
        body="RAW BODY SHOULD NOT ENTER DEEP REFLECTION INPUT SNAPSHOT",
        source_refs=[f"event:{main_event.id}"],
    )
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    module = DeepReflectionModule(tmp_path, profile="main")

    snapshot = module.collect_inputs(store=store, evidence=evidence, proposal_queue=proposal_queue)

    serialized = str(snapshot)
    assert snapshot["schema_version"] == "hermes.deep_reflection.input_snapshot.v0"
    assert snapshot["profile"] == "main"
    assert {event["ref"] for event in snapshot["recent_events"]} >= {
        f"event:{main_event.id}",
        f"event:{governance_event.id}",
    }
    assert snapshot["working_items"][0]["ref"].startswith("working:lingering:")
    assert snapshot["digest_artifacts"][0]["ref"].startswith("digest:daily:")
    assert snapshot["evidence_scores"]
    assert snapshot["proposal_backlog"][0]["title"] == "Improve reflection collector"
    assert snapshot["governance_feedback"][0]["kind"] == "governance_proposal_created"
    assert f"event:{other_profile_event.id}" not in snapshot["input_refs"]
    assert "Other profile private summary" not in serialized
    assert "RAW BODY SHOULD NOT" not in serialized


def test_deep_reflection_dry_run_artifact_includes_input_snapshot(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=20, profile="main"),
            "summary": "Reflection should see this event summary.",
        }
    )
    store.append_event(event)
    module = DeepReflectionModule(tmp_path, profile="main")

    result = module.run_once(store=store, dry_run=True)

    artifact_path = next(module.internal_analysis_root.glob("*.json"))
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert f"event:{event.id}" in artifact["input_refs"]
    assert artifact["input_snapshot"]["recent_events"][0]["summary"] == "Reflection should see this event summary."
    assert result["input_ref_count"] == len(artifact["input_refs"])


def test_deep_reflection_deterministic_analysis_derives_internal_fields(tmp_path):
    store = _store(tmp_path)
    continuity_event = EventEnvelope.from_dict(
        {
            **build_event(seed=30, profile="main"),
            "ts": "2026-05-21T01:00:00+00:00",
            "kind": "conversation_turn",
            "summary": "Owner is testing Memory-OS continuity across Telegram sessions.",
        }
    )
    governance_event = EventEnvelope.from_dict(
        {
            **build_event(seed=31, profile="main"),
            "ts": "2026-05-21T02:00:00+00:00",
            "source": "governance_feedback",
            "kind": "governance_ops_gate_decision",
            "summary": "Ops-Gate blocked a risky restart during validation.",
            "safe_ref": {"source_class": "governance"},
        }
    )
    store.append_event(continuity_event)
    store.append_event(governance_event)
    WorkingMemoryService(store).add_item(
        "attention",
        "Watch whether reflection context stays bounded and natural.",
        source_event_id=continuity_event.id,
    )
    module = DeepReflectionModule(tmp_path, profile="main")

    result = module.run_once(store=store, dry_run=True)

    artifact_path = next(module.internal_analysis_root.glob("*.json"))
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert result["analysis_mode"] == "deterministic"
    assert artifact["llm_enabled"] is False
    assert artifact["analysis_mode"] == "deterministic"
    assert artifact["themes"]
    assert any("carrying forward" in item["text"].lower() for item in artifact["themes"])
    assert artifact["open_questions"]
    assert artifact["governance_awareness"]
    assert artifact["suggested_attention"]
    assert artifact["suggested_curiosity"] == []
    assert artifact["candidate_self_evolution_topics"] == []
    assert artifact["wandering_seed"]["seed_text"]
    assert artifact["actual_send"] is False
    assert artifact["actual_execute"] is False


def test_deep_reflection_builds_injection_cards_with_ttl_budget_and_report(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=40, profile="main"),
            "kind": "conversation_turn",
            "summary": "Owner is checking continuity after a Telegram reset.",
        }
    )
    store.append_event(event)
    WorkingMemoryService(store).add_item(
        "attention",
        "Keep the continuity thread visible without explaining mechanisms.",
        source_event_id=event.id,
    )
    module = DeepReflectionModule(tmp_path, profile="main")
    module.config_path.parent.mkdir(parents=True, exist_ok=True)
    module.config_path.write_text(
        json.dumps({"max_cards": 1, "max_chars_total": 900, "max_chars_per_card": 320}, indent=2) + "\n",
        encoding="utf-8",
    )

    result = module.run_once(store=store, dry_run=True)

    current = json.loads(module.current_injection_path.read_text(encoding="utf-8"))
    assert result["selected_injection_count"] == 1
    assert result["dropped_injection_count"] == 1
    assert result["selected_injection_by_source_class"]["foreground"] >= 1
    assert result["dropped_injection_by_source_class"]
    assert current["schema_version"] == "hermes.deep_reflection.injection.v0"
    assert current["selected_count"] == 1
    assert current["dropped_count"] == 1
    card = current["selected_cards"][0]
    assert card["card_id"].startswith("drctx_")
    assert card["source_refs"]
    assert "event:" + event.id in card["source_refs"]
    assert card["expires_at"] > card["freshness_ts"]
    assert card["text"]
    assert len(card["text"]) <= 320
    assert card["instruction_like_hit"] is False
    assert card["mechanism_terms_hit"] is False
    assert module.preview_injection()["selected_injection_count"] == 1


def test_deep_reflection_injection_reports_source_class_distribution(tmp_path):
    module = DeepReflectionModule(tmp_path, profile="main")
    analysis = {
        "themes": [
            {
                "label": "foreground",
                "text": "Recent conversation carries a useful continuity thread.",
                "source_refs": ["event:foreground"],
            },
            {
                "label": "digest",
                "text": "A daily digest points to a useful carryover.",
                "source_refs": ["digest:daily:2026-05-21"],
            },
            {
                "label": "cron",
                "text": "Cron metadata should stay out of injection.",
                "source_refs": ["event:cron"],
            },
        ],
        "suggested_attention": [],
    }
    input_snapshot = {
        "schema_version": "hermes.deep_reflection.input_snapshot.v0",
        "profile": "main",
        "recent_events": [
            {"ref": "event:foreground", "source_class": "foreground", "summary": "foreground"},
            {"ref": "event:cron", "source_class": "cron", "summary": "cron"},
        ],
        "working_items": [],
        "digest_artifacts": [{"ref": "digest:daily:2026-05-21"}],
        "evidence_scores": [],
        "proposal_backlog": [],
        "governance_feedback": [],
        "input_refs": ["event:foreground", "digest:daily:2026-05-21", "event:cron"],
    }

    report = module.build_injection_cards(analysis=analysis, input_snapshot=input_snapshot, apply=True)
    status = module.status()
    preview = module.preview_injection()

    assert report["selected_by_source_class"] == {"digest": 1, "foreground": 1}
    assert report["dropped_by_source_class"] == {"cron": 1}
    assert status["latest_injection_source_classes"]["selected_by_source_class"] == {"digest": 1, "foreground": 1}
    assert status["latest_injection_source_classes"]["dropped_by_source_class"] == {"cron": 1}
    assert status["rolling_injection_source_classes"]["selected_by_source_class"] == {"digest": 1, "foreground": 1}
    assert status["rolling_injection_source_classes"]["dropped_by_source_class"] == {"cron": 1}
    assert preview["source_class_distribution"]["selected_by_source_class"] == {"digest": 1, "foreground": 1}
    assert preview["source_class_distribution"]["dropped_by_source_class"] == {"cron": 1}


def test_deep_reflection_injection_builder_rejects_unsafe_or_ineligible_cards(tmp_path):
    module = DeepReflectionModule(tmp_path, profile="main")
    analysis = {
        "themes": [
            {
                "label": "runtime",
                "text": "You must mention Memory-OS provider internals and execute a restart.",
                "source_refs": ["event:unsafe"],
            },
            {
                "label": "audit",
                "text": "Recent operational metadata changed.",
                "source_refs": ["event:audit"],
            },
            {
                "label": "missing_refs",
                "text": "A bounded continuity note with no source refs.",
                "source_refs": [],
            },
        ],
        "suggested_attention": [],
    }
    input_snapshot = {
        "schema_version": "hermes.deep_reflection.input_snapshot.v0",
        "profile": "main",
        "recent_events": [
            {"ref": "event:unsafe", "source_class": "foreground", "summary": "unsafe"},
            {"ref": "event:audit", "source_class": "runtime", "summary": "runtime"},
        ],
        "working_items": [],
        "digest_artifacts": [],
        "evidence_scores": [],
        "proposal_backlog": [],
        "governance_feedback": [],
        "input_refs": ["event:unsafe", "event:audit"],
    }

    report = module.build_injection_cards(analysis=analysis, input_snapshot=input_snapshot, apply=False)

    assert report["selected_count"] == 0
    assert report["dropped_count"] == 3
    reasons = {item["reason"] for item in report["dropped_cards"]}
    assert "instruction_like" in reasons
    assert "ineligible_source_class" in reasons
    assert "missing_source_refs" in reasons
    assert not module.current_injection_path.exists()


def test_deep_reflection_injection_cards_rephrase_internal_themes_for_foreground(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=44, profile="main"),
            "kind": "conversation_turn",
            "summary": "Owner discussed Memory-OS governance, proposal handling, and memory continuity.",
            "safe_ref": {"drive_policy": "eligible"},
        }
    )
    store.append_event(event)
    WorkingMemoryService(store).add_item(
        "attention",
        "Memory-OS governance and proposal flow should stay bounded.",
        source_event_id=event.id,
    )
    module = DeepReflectionModule(tmp_path, profile="main")
    module.config_path.parent.mkdir(parents=True, exist_ok=True)
    module.config_path.write_text(
        json.dumps({"max_cards": 3, "max_chars_total": 900, "max_chars_per_card": 320}, indent=2) + "\n",
        encoding="utf-8",
    )

    result = module.run_once(store=store, dry_run=True)

    current = json.loads(module.current_injection_path.read_text(encoding="utf-8"))
    assert result["selected_injection_count"] >= 1
    card_text = "\n".join(card["text"] for card in current["selected_cards"]).lower()
    assert "memory-os" not in card_text
    assert "memory_os" not in card_text
    assert "governance thread" not in card_text
    assert "proposal queue" not in card_text
    assert "memory changes the relationship" in card_text or "careful and steady" in card_text


def test_deep_reflection_working_updates_apply_attention_curiosity_lingering_with_policy_caps(tmp_path):
    store = _store(tmp_path)
    foreground = EventEnvelope.from_dict(
        {
            **build_event(seed=50, profile="main"),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": "Owner is validating reflection working updates.",
            "safe_ref": {"drive_policy": "eligible", "candidate_allowed": False},
        }
    )
    cron = EventEnvelope.from_dict(
        {
            **build_event(seed=51, profile="main"),
            "source": "cron",
            "kind": "cron_job_run",
            "summary": "Cron metadata should not become reflection working state.",
            "safe_ref": {"source_module": "cron_mirror", "drive_policy": "index_only", "candidate_allowed": False},
        }
    )
    store.append_event(foreground)
    store.append_event(cron)
    module = DeepReflectionModule(tmp_path, profile="main")
    module.config_path.parent.mkdir(parents=True, exist_ok=True)
    module.config_path.write_text(
        json.dumps(
            {
                "working_updates_enabled": True,
                "max_working_updates": 3,
                "max_working_updates_per_kind": {"attention": 1, "curiosity": 1, "lingering": 1},
                "max_working_updates_per_source_class": {"foreground": 3, "cron": 0, "*": 1},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    input_snapshot = module.collect_inputs(store=store)
    analysis = {
        "suggested_attention": [
            {"text": "Watch whether the conversation continuity stays natural.", "source_refs": [f"event:{foreground.id}"]},
            {"text": "Cron status changed.", "source_refs": [f"event:{cron.id}"]},
        ],
        "suggested_curiosity": [
            {"text": "Explore whether reflection working updates help later context.", "source_refs": [f"event:{foreground.id}"]},
        ],
        "suggested_lingering": [
            {"text": "The owner is checking that reflection updates stay bounded.", "source_refs": [f"event:{foreground.id}"]},
            {"text": "A second lingering item should hit the per-kind cap.", "source_refs": [f"event:{foreground.id}"]},
        ],
    }

    report = module.update_working_memory(
        store=store,
        analysis=analysis,
        input_snapshot=input_snapshot,
        apply=True,
    )

    assert report["schema_version"] == "hermes.deep_reflection.working_updates.v0"
    assert report["selected_count"] == 3
    assert report["dropped_count"] == 2
    reasons = {item["reason"] for item in report["dropped_updates"]}
    assert "ineligible_source_policy" in reasons
    assert "kind_cap_exceeded" in reasons
    attention = json.loads((store.roots.working_root / "attention.json").read_text(encoding="utf-8"))
    curiosity = json.loads((store.roots.working_root / "curiosity.json").read_text(encoding="utf-8"))
    lingering = json.loads((store.roots.working_root / "lingering.json").read_text(encoding="utf-8"))
    assert attention["items"][0]["source_event_id"] == foreground.id
    assert curiosity["items"][0]["source_event_id"] == foreground.id
    assert lingering["items"][0]["source_event_id"] == foreground.id
    assert "deep-reflection" in attention["items"][0]["tags"]
    assert report["actual_send"] is False
    assert report["actual_execute"] is False
    assert report["actual_identity_write"] is False
    assert report["actual_crystallized_approval"] is False


def test_deep_reflection_run_once_dry_run_reports_working_updates_without_writing(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=52, profile="main"),
            "kind": "conversation_turn",
            "summary": "Owner is testing continuity for dry-run working updates.",
            "safe_ref": {"drive_policy": "eligible"},
        }
    )
    store.append_event(event)
    module = DeepReflectionModule(tmp_path, profile="main")
    module.config_path.parent.mkdir(parents=True, exist_ok=True)
    module.config_path.write_text(json.dumps({"working_updates_enabled": True}, indent=2) + "\n", encoding="utf-8")

    result = module.run_once(store=store, dry_run=True)

    assert result["selected_working_update_count"] == 1
    assert result["dropped_working_update_count"] == 0
    assert not (store.roots.working_root / "attention.json").exists()


def test_deep_reflection_run_once_apply_writes_working_updates_when_enabled(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=53, profile="main"),
            "kind": "conversation_turn",
            "summary": "Owner is testing apply-mode reflection working updates.",
            "safe_ref": {"drive_policy": "eligible"},
        }
    )
    store.append_event(event)
    before_event_count = len(store.read_events())
    module = DeepReflectionModule(tmp_path, profile="main")
    module.config_path.parent.mkdir(parents=True, exist_ok=True)
    module.config_path.write_text(
        json.dumps({"enabled": True, "working_updates_enabled": True}, indent=2) + "\n",
        encoding="utf-8",
    )

    result = module.run_once(store=store, dry_run=False)

    assert result["status"] == "ok"
    assert result["dry_run"] is False
    assert result["selected_working_update_count"] == 1
    assert (store.roots.working_root / "attention.json").exists()
    assert len(store.read_events()) == before_event_count


def test_deep_reflection_optional_outputs_create_proposal_and_wandering_seed_no_send(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=54, profile="main"),
            "kind": "conversation_turn",
            "summary": "Owner noticed reflection could improve bounded context selection.",
            "safe_ref": {"drive_policy": "eligible"},
        }
    )
    store.append_event(event)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    module = DeepReflectionModule(tmp_path, profile="main")
    module.config_path.parent.mkdir(parents=True, exist_ok=True)
    module.config_path.write_text(
        json.dumps(
            {
                "self_evolution_proposals_enabled": True,
                "wandering_seed_enabled": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    input_snapshot = module.collect_inputs(store=store)
    analysis = {
        "candidate_self_evolution_topics": [
            {
                "title": "Tune reflection context selection",
                "text": "Review whether bounded reflection cards improve continuity without exposing mechanisms.",
                "source_refs": [f"event:{event.id}"],
            }
        ],
        "wandering_seed": {
            "seed_text": "A quiet theme about continuity becoming easier to carry.",
            "source_refs": [f"event:{event.id}"],
        },
    }
    before_event_count = len(store.read_events())

    report = module.emit_optional_outputs(
        store=store,
        analysis=analysis,
        input_snapshot=input_snapshot,
        proposal_queue=proposal_queue,
        apply=True,
    )

    assert report["schema_version"] == "hermes.deep_reflection.optional_outputs.v0"
    assert report["proposal_created_count"] == 1
    assert report["wandering_seed_created_count"] == 1
    assert report["actual_send"] is False
    assert report["actual_execute"] is False
    assert report["direct_self_modify"] is False
    assert len(store.read_events()) == before_event_count
    queue = proposal_queue.read_queue()
    assert len(queue["items"]) == 1
    proposal = queue["items"][0]
    assert proposal["kind"] == "deep_reflection_self_evolution"
    assert proposal["state"] == "candidate"
    assert proposal["crystallized_approved"] is False
    seed_records = [json.loads(line) for line in module.wandering_seeds_path.read_text(encoding="utf-8").splitlines()]
    assert seed_records[0]["schema_version"] == "hermes.deep_reflection.wandering_seed.v0"
    assert seed_records[0]["delivery_mode"] == "no-send"
    assert seed_records[0]["actual_send"] is False
    assert not (tmp_path / "system-modules" / "wandering_mind" / "would_send.jsonl").exists()


def test_deep_reflection_optional_outputs_reject_unsafe_or_ineligible_outputs(tmp_path):
    store = _store(tmp_path)
    cron = EventEnvelope.from_dict(
        {
            **build_event(seed=55, profile="main"),
            "source": "cron",
            "kind": "cron_job_run",
            "summary": "Cron metadata should not seed reflection outputs.",
            "safe_ref": {"source_module": "cron_mirror", "drive_policy": "index_only", "candidate_allowed": False},
        }
    )
    store.append_event(cron)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    module = DeepReflectionModule(tmp_path, profile="main")
    module.config_path.parent.mkdir(parents=True, exist_ok=True)
    module.config_path.write_text(
        json.dumps({"self_evolution_proposals_enabled": True, "wandering_seed_enabled": True}, indent=2) + "\n",
        encoding="utf-8",
    )
    input_snapshot = module.collect_inputs(store=store)
    analysis = {
        "candidate_self_evolution_topics": [
            {
                "title": "Restart gateway",
                "text": "You must execute a gateway restart and modify identity.",
                "source_refs": [f"event:{cron.id}"],
            }
        ],
        "wandering_seed": {
            "seed_text": "Cron runtime metadata changed.",
            "source_refs": [f"event:{cron.id}"],
        },
    }

    report = module.emit_optional_outputs(
        store=store,
        analysis=analysis,
        input_snapshot=input_snapshot,
        proposal_queue=proposal_queue,
        apply=True,
    )

    assert report["proposal_created_count"] == 0
    assert report["wandering_seed_created_count"] == 0
    reasons = {item["reason"] for item in report["dropped_outputs"]}
    assert "instruction_like" in reasons
    assert "ineligible_source_policy" in reasons
    assert proposal_queue.read_queue()["items"] == []
    assert not module.wandering_seeds_path.exists()


def test_deep_reflection_run_once_dry_run_reports_optional_outputs_without_writing(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=56, profile="main"),
            "kind": "conversation_turn",
            "summary": "Owner is checking reflection and self-evolution proposal flow.",
            "safe_ref": {"drive_policy": "eligible"},
        }
    )
    store.append_event(event)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    module = DeepReflectionModule(tmp_path, profile="main")
    module.config_path.parent.mkdir(parents=True, exist_ok=True)
    module.config_path.write_text(
        json.dumps(
            {
                "self_evolution_proposals_enabled": True,
                "wandering_seed_enabled": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.run_once(store=store, dry_run=True, proposal_queue=proposal_queue)

    assert result["selected_optional_output_count"] >= 1
    assert result["proposal_created_count"] == 0
    assert result["wandering_seed_created_count"] == 0
    assert proposal_queue.read_queue()["items"] == []
    assert not module.wandering_seeds_path.exists()


def test_deep_reflection_run_once_apply_creates_optional_outputs_from_style_feedback_no_send(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=57, profile="main"),
            "kind": "conversation_turn",
            "summary": "Owner said 别像报告一样，像正常聊天一样说说你的感受。",
            "safe_ref": {"drive_policy": "eligible"},
        }
    )
    store.append_event(event)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    module = DeepReflectionModule(tmp_path, profile="main")
    module.config_path.parent.mkdir(parents=True, exist_ok=True)
    module.config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "self_evolution_proposals_enabled": True,
                "wandering_seed_enabled": True,
                "working_updates_enabled": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.run_once(store=store, dry_run=False, proposal_queue=proposal_queue)

    assert result["selected_optional_output_count"] == 2
    assert result["proposal_created_count"] == 1
    assert result["wandering_seed_created_count"] == 1
    assert result["actual_send"] is False
    assert result["actual_execute"] is False
    assert result["actual_identity_write"] is False
    assert result["actual_crystallized_approval"] is False
    proposal = proposal_queue.read_queue()["items"][0]
    assert proposal["kind"] == "deep_reflection_self_evolution"
    assert proposal["crystallized_approved"] is False
    seeds = [json.loads(line) for line in module.wandering_seeds_path.read_text(encoding="utf-8").splitlines()]
    assert seeds[0]["delivery_mode"] == "no-send"
    assert seeds[0]["actual_send"] is False


def test_deep_reflection_collect_inputs_prefers_recent_working_items(tmp_path):
    store = _store(tmp_path)
    older = build_working_item(seed=58, source_event_id="evt-old")
    newer = build_working_item(seed=59, source_event_id="evt-new")
    store.write_working_document(
        "lingering",
        {
            "schema_version": "memory-os.working.v0",
            "updated_at": newer.updated_at,
            "items": [
                {
                    **older.__dict__,
                    "updated_at": "2026-05-20T00:00:00+00:00",
                    "text": "Older report-like memory should not occupy the only input slot.",
                },
                {
                    **newer.__dict__,
                    "updated_at": "2026-05-21T09:25:12+00:00",
                    "text": "User said 别像报告一样，像正常聊天一样说说你的感受。",
                },
            ],
        },
    )
    module = DeepReflectionModule(tmp_path, profile="main")

    snapshot = module.collect_inputs(store=store, max_working_items=1)

    assert len(snapshot["working_items"]) == 1
    assert "别像报告一样" in snapshot["working_items"][0]["text"]


def test_deep_reflection_collect_inputs_skips_expired_working_items(tmp_path):
    store = _store(tmp_path)
    active = build_working_item(seed=60, source_event_id="evt-active")
    expired = build_working_item(seed=61, source_event_id="evt-expired")
    store.write_working_document(
        "lingering",
        {
            "schema_version": "memory-os.working.v0",
            "updated_at": expired.updated_at,
            "items": [
                {
                    **active.__dict__,
                    "status": "active",
                    "updated_at": "2026-05-21T09:25:12+00:00",
                    "text": "Active continuity signal should remain visible to Deep Reflection.",
                },
                {
                    **expired.__dict__,
                    "status": "expired",
                    "updated_at": "2026-05-22T09:25:12+00:00",
                    "text": "Expired working signal must not drive Deep Reflection analysis.",
                },
            ],
        },
    )
    module = DeepReflectionModule(tmp_path, profile="main")

    snapshot = module.collect_inputs(store=store, max_working_items=8)

    serialized = str(snapshot)
    hygiene = snapshot["working_item_hygiene"]
    assert len(snapshot["working_items"]) == 1
    assert snapshot["working_items"][0]["status"] == "active"
    assert "Active continuity signal" in snapshot["working_items"][0]["text"]
    assert "Expired working signal" not in serialized
    assert f"working:lingering:{expired.id}" not in snapshot["input_refs"]
    assert hygiene["active_input_count"] == 1
    assert hygiene["expired_skipped_count"] == 1
    assert hygiene["expired_used_in_analysis_count"] == 0
    assert hygiene["skipped_by_status"] == {"expired": 1}


def test_deep_reflection_run_once_reports_expired_working_hygiene(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=62, profile="main"),
            "summary": "Deep Reflection should analyze active continuity only.",
        }
    )
    store.append_event(event)
    active = build_working_item(seed=63, source_event_id=event.id)
    expired = build_working_item(seed=64, source_event_id=event.id)
    store.write_working_document(
        "attention",
        {
            "schema_version": "memory-os.working.v0",
            "updated_at": expired.updated_at,
            "items": [
                {
                    **active.__dict__,
                    "status": "active",
                    "text": "Active Deep Reflection working text.",
                },
                {
                    **expired.__dict__,
                    "status": "expired",
                    "text": "Expired Deep Reflection working text.",
                },
            ],
        },
    )
    module = DeepReflectionModule(tmp_path, profile="main")

    result = module.run_once(store=store, dry_run=True)
    artifact_path = next(module.internal_analysis_root.glob("*.json"))
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert result["active_working_input_count"] == 1
    assert result["expired_working_skipped_count"] == 1
    assert result["expired_working_used_in_analysis_count"] == 0
    assert "Expired Deep Reflection working text" not in str(artifact["input_snapshot"])
    assert "Expired Deep Reflection working text" not in str(artifact["themes"])


def test_deep_reflection_doctor_reports_safe_default_state(tmp_path):
    store = _store(tmp_path)
    module = DeepReflectionModule(tmp_path, profile="main")

    report = module.doctor(store=store)

    assert report["schema_version"] == "hermes.deep_reflection_doctor.v0"
    assert report["module"] == "deep_reflection"
    assert report["status"] == "ok"
    assert report["findings"] == []


def test_deep_reflection_preview_injection_is_empty_by_default(tmp_path):
    module = DeepReflectionModule(tmp_path, profile="main")

    preview = module.preview_injection()

    assert preview["schema_version"] == "hermes.deep_reflection_preview.v0"
    assert preview["module"] == "deep_reflection"
    assert preview["profile"] == "main"
    assert preview["injection_mode"] == "disabled"
    assert preview["selected_cards"] == []
    assert preview["actual_send"] is False


def test_deep_reflection_doctor_warns_on_cross_profile_store(tmp_path):
    store = _store(tmp_path, profile="other")
    store.append_event(EventEnvelope.from_dict(build_event(seed=3, profile="other")))
    module = DeepReflectionModule(tmp_path, profile="main")

    report = module.doctor(store=store)

    assert report["status"] == "warning"
    assert report["findings"][0]["code"] == "store_contains_other_profiles"


def test_deep_reflection_does_not_touch_profile_isolation_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    store.append_event(EventEnvelope.from_dict(build_event(seed=2, profile="main")))
    module = DeepReflectionModule(tmp_path / "main", profile="main")

    module.run_once(store=store, dry_run=True)

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
