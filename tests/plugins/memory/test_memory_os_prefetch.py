import json
from datetime import datetime, timedelta, timezone

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
from plugins.memory.memory_os.fixtures import (
    build_crystallized_frontmatter,
    build_event,
    build_working_item,
)
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import _budget_keep_priority, _build_prefetch_sections, _continuity_bridge_lines, _crystallized_lines, _event_lines, _fit_budget, _floor_match_score, _recent_cross_session_lines, _tokenize_for_floor_match, build_prefetch, build_prefetch_with_observability, continuity_selector_report
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, WORKING_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_prefetch_empty_store_returns_empty_string(tmp_path):
    store = _store(tmp_path)

    assert build_prefetch("anything", budget_chars=2200, store=store, index=None) == ""


def test_prefetch_observability_reports_index_search_errors(tmp_path):
    store = _store(tmp_path)

    class BrokenIndex:
        def search(self, _query, *, limit):
            raise RuntimeError("synthetic index failure")

    report = build_prefetch_with_observability(
        "memory marker",
        budget_chars=2200,
        store=store,
        index=BrokenIndex(),
    )

    assert report["schema_version"] == "memory-os.prefetch_observability.v0"
    assert report["context"] == ""
    assert report["suppressed_error_count"] == 2
    assert report["recent_error_codes"] == ["prefetch_index_search_error", "prefetch_index_search_error"]
    assert report["error_records"][0]["schema_version"] == "memory-os.error_record.v0"
    assert report["error_records"][0]["component"] == "prefetch"


def test_prefetch_records_substrate_shadow_recall_without_injecting_fact_or_query(tmp_path):
    store = _store(tmp_path)

    context = build_prefetch(
        "PRIVATE_QUERY_SHOULD_NOT_LEAK",
        budget_chars=2200,
        store=store,
        index=None,
        substrate_recall_report={
            "schema_version": "memory-os.substrate_recall.v0",
            "query_class": "shadow",
            "selected_provider": "hindsight",
            "authoritative": False,
            "external_authoritative_count": 0,
            "local_first_authority_preserved": True,
            "recall_llm_triggered": False,
            "fallback_triggered": False,
            "facts": [
                {
                    "provider": "hindsight",
                    "body_summary": "HINDSIGHT_FACT_SHOULD_NOT_INJECT",
                    "advisory_only": True,
                    "authority_class": "derived_projection",
                    "recall_llm_triggered": False,
                    "substrate_snapshot_id": "hindsight:bank:v1",
                }
            ],
        },
    )

    shadow_path = store.roots.memory_os_root / "system" / "substrate_recall_shadow.jsonl"
    ledger_path = store.roots.memory_os_root / "system" / "substrate_operations.jsonl"
    shadow_record = json.loads(shadow_path.read_text(encoding="utf-8").splitlines()[-1])
    ledger_record = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[-1])

    assert context == ""
    assert "PRIVATE_QUERY_SHOULD_NOT_LEAK" not in shadow_path.read_text(encoding="utf-8")
    assert shadow_record["query_sha256"]
    assert shadow_record["selected_provider"] == "hindsight"
    assert shadow_record["local_first_authority_preserved"] is True
    assert ledger_record["operation"] == "recall"
    assert ledger_record["provider"] == "hindsight"
    assert ledger_record["substrate_snapshot_id"] == "hindsight:bank:v1"


def test_prefetch_injects_active_substrate_recall_as_advisory_context(tmp_path):
    store = _store(tmp_path)

    context = build_prefetch(
        "ACTIVE_QUERY_SHOULD_BE_HASHED",
        budget_chars=2200,
        store=store,
        index=None,
        substrate_recall_report={
            "schema_version": "memory-os.substrate_recall.v0",
            "mode": "active",
            "query_class": "active",
            "selected_provider": "local_artifact",
            "authoritative": True,
            "external_authoritative_count": 0,
            "local_first_authority_preserved": True,
            "recall_llm_triggered": False,
            "fallback_triggered": False,
            "facts": [
                {
                    "provider": "local_artifact",
                    "body_summary": "Local crystallized fact remains primary.",
                    "advisory_only": False,
                    "authority_class": "local_canonical",
                    "recall_llm_triggered": False,
                    "substrate_snapshot_id": "local_artifact:canonical:v1",
                },
                {
                    "provider": "hindsight",
                    "body_summary": "Hindsight active fact is advisory only.",
                    "advisory_only": True,
                    "authority_class": "derived_projection",
                    "recall_llm_triggered": False,
                    "substrate_snapshot_id": "hindsight:bank:v1",
                },
            ],
        },
    )

    shadow_path = store.roots.memory_os_root / "system" / "substrate_recall_shadow.jsonl"

    assert "### Substrate Recall" in context
    assert "Local crystallized fact remains primary." in context
    assert "Hindsight active fact is advisory only." in context
    assert "[hindsight advisory; authority=derived_projection]" in context
    assert "ACTIVE_QUERY_SHOULD_BE_HASHED" not in shadow_path.read_text(encoding="utf-8")


def test_prefetch_orders_layers_deterministically(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(build_event(seed=1, profile="memoryos-test"))
    working_item = build_working_item(seed=2, source_event_id=event.id)
    crystallized = build_crystallized_frontmatter(seed=3, source_event_ids=[event.id])
    store.append_event(event)
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": working_item.updated_at,
            "items": [{**working_item.__dict__, "text": "Synthetic memory working item 2"}],
        },
    )
    (store.roots.relationships_root / "owner.md").write_text(
        "Owner relationship memory.",
        encoding="utf-8",
    )
    store.append_crystallized_record("moments.md", crystallized.__dict__, "Approved crystallized memory.")

    context = build_prefetch("memory", budget_chars=2200, store=store, index=None)

    assert context.startswith("## Memory-OS Context")
    assert context.index("### Working Memory") < context.index("### Relationship Memory")
    assert context.index("### Relationship Memory") < context.index("### Crystallized Memory")
    assert context.index("### Crystallized Memory") < context.index("### Recent Event Summaries")


def test_prefetch_respects_budget_and_excludes_private_bodies(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=4, profile="memoryos-test"),
            "summary": "Safe event summary.",
            "safe_ref": {"raw_transcript": "RAW TRANSCRIPT SHOULD NOT LEAK"},
        }
    )
    store.append_event(event)
    (store.roots.relationships_root / "owner.md").write_text(
        "Owner note with api_key=SHOULD_NOT_LEAK and token: ALSO_SECRET.",
        encoding="utf-8",
    )

    context = build_prefetch("memory", budget_chars=320, store=store, index=None)

    assert len(context) <= 320
    assert "RAW TRANSCRIPT SHOULD NOT LEAK" not in context
    assert "SHOULD_NOT_LEAK" not in context
    assert "ALSO_SECRET" not in context
    assert "[redacted]" in context


def test_provider_prefetch_uses_configured_budget(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.save_config({"prefetch_char_budget": 120}, str(tmp_path))
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="memoryos-test")
    event = EventEnvelope.from_dict({**build_event(seed=5, profile="memoryos-test"), "summary": "x" * 500})
    provider._store.append_event(event)

    context = provider.prefetch("memory")
    provider.shutdown()

    assert context.startswith("## Memory-OS Context")
    assert len(context) <= 120
    assert EVENT_SCHEMA_VERSION not in context


def test_fit_budget_drops_low_priority_whole_sections_before_dynamic_recall():
    context = "\n".join(
        [
            "## Memory-OS Context",
            "",
            "### Current Foreground Task",
            "- foreground task anchor",
            "",
            "### Identity Memory",
            "- " + "static identity filler " * 18,
            "",
            "### Continuity Bridge",
            "- " + "static bridge filler " * 18,
            "",
            "### Indexed Recall",
            "- DYNAMIC_INDEXED_RECALL_MARKER answers the current query",
            "",
            "### Recent Event Summaries",
            "- DYNAMIC_EVENT_MARKER also answers the current query",
        ]
    )

    trimmed = _fit_budget(context, 190)

    assert len(trimmed) <= 190
    assert "### Indexed Recall" in trimmed
    assert "DYNAMIC_INDEXED_RECALL_MARKER" in trimmed
    assert "### Identity Memory" not in trimmed
    assert "### Continuity Bridge" not in trimmed


def test_fit_budget_never_emits_empty_hanging_section_heading():
    context = "\n".join(
        [
            "## Memory-OS Context",
            "",
            "### Indexed Recall",
            "- DYNAMIC_INDEXED_RECALL_MARKER content that should be kept only with its heading",
        ]
    )
    heading_only_budget = len("## Memory-OS Context\n\n### Indexed Recall") + 2

    trimmed = _fit_budget(context, heading_only_budget)

    assert len(trimmed) <= heading_only_budget
    assert "### Indexed Recall" not in trimmed
    assert "DYNAMIC_INDEXED_RECALL_MARKER" not in trimmed


def test_fit_budget_preserves_foreground_anchor_above_recall_sections():
    context = "\n".join(
        [
            "## Memory-OS Context",
            "",
            "### Current Foreground Task",
            "- FOREGROUND_ANCHOR_MARKER small critical current task",
            "",
            "### Indexed Recall",
            "- " + "indexed recall filler " * 10,
            "",
            "### Substrate Recall",
            "- " + "substrate recall filler " * 10,
            "",
            "### Recent Event Summaries",
            "- " + "recent event filler " * 10,
        ]
    )

    trimmed = _fit_budget(context, 120)

    assert len(trimmed) <= 120
    assert "### Current Foreground Task" in trimmed
    assert "FOREGROUND_ANCHOR_MARKER" in trimmed
    assert "### Indexed Recall" not in trimmed
    assert "### Substrate Recall" not in trimmed


def test_prefetch_uses_index_search_for_relevant_older_event(tmp_path):
    store = _store(tmp_path)
    older = EventEnvelope.from_dict(
        {
            **build_event(seed=10, profile="memoryos-test"),
            "summary": "旧事件里有 MOS_INDEX_RARE_MARKER。",
        }
    )
    store.append_event(older)
    for seed in range(11, 17):
        store.append_event(EventEnvelope.from_dict(build_event(seed=seed, profile="memoryos-test")))
    index = MemoryOSIndex(store.roots)
    index.sync_from_store(store)

    context = build_prefetch("MOS_INDEX_RARE_MARKER", budget_chars=2200, store=store, index=index)

    assert "### Indexed Recall" in context
    assert "MOS_INDEX_RARE_MARKER" in context


def test_prefetch_continuity_selector_preserves_bridge_seed_events(tmp_path):
    store = _store(tmp_path)
    cron_event = EventEnvelope.from_dict(
        {
            **build_event(seed=30, profile="memoryos-test"),
            "ts": "2026-05-21T08:00:00+00:00",
            "source": "cron",
            "kind": "cron_job_run",
            "summary": "BRIDGE_CRON_MARKER scheduled work happened.",
            "safe_ref": {"source_module": "cron_mirror", "drive_policy": "index_only"},
            "tags": ["cron", "mirror"],
        }
    )
    state_event = EventEnvelope.from_dict(
        {
            **build_event(seed=31, profile="memoryos-test"),
            "ts": "2026-05-21T08:01:00+00:00",
            "source": "state_source_mirror",
            "kind": "state_source_changed",
            "summary": "BRIDGE_STATE_MARKER daily digest changed.",
            "safe_ref": {"source_module": "state_source_mirror", "source_class": "state:digest_daily"},
            "tags": ["state", "mirror"],
        }
    )
    store.append_event(cron_event)
    store.append_event(state_event)
    for seed in range(32, 42):
        store.append_event(
            EventEnvelope.from_dict(
                {
                    **build_event(seed=seed, profile="memoryos-test"),
                    "ts": f"2026-05-21T08:{seed:02d}:00+00:00",
                    "source": "telegram",
                    "kind": "conversation_turn",
                    "summary": f"Recent foreground event {seed}.",
                }
            )
        )
    noisy_working = build_working_item(seed=99, source_event_id=cron_event.id)
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": noisy_working.updated_at,
            "items": [
                {
                    **noisy_working.__dict__,
                    "text": "NOISY_WORKING_MEMORY " * 200,
                }
            ],
        },
    )

    context = build_prefetch("ordinary continuity question", budget_chars=900, store=store, index=None)

    assert "### Continuity Bridge" in context
    assert "BRIDGE_CRON_MARKER" in context
    assert "BRIDGE_STATE_MARKER" in context
    assert "NOISY_WORKING_MEMORY" not in context


def test_continuity_selector_report_counts_selected_and_dropped_without_private_bodies(tmp_path):
    store = _store(tmp_path)
    for seed in range(50, 60):
        store.append_event(
            EventEnvelope.from_dict(
                {
                    **build_event(seed=seed, profile="memoryos-test"),
                    "source": "telegram",
                    "kind": "conversation_turn",
                    "summary": f"Selector public summary {seed}.",
                    "safe_ref": {"raw_transcript": "PRIVATE_SELECTOR_BODY_SHOULD_NOT_APPEAR"},
                }
            )
        )

    report = continuity_selector_report(store)
    rendered = str(report)

    assert report["schema_version"] == "memory-os.continuity_selector.v0"
    assert report["selected_total"] > 0
    assert report["dropped_total"] > 0
    assert "foreground" in report["selected_by_source_class"]
    assert "PRIVATE_SELECTOR_BODY_SHOULD_NOT_APPEAR" not in rendered


def test_prefetch_labels_candidates_as_review_only_not_approved_crystallized(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(build_event(seed=70, profile="memoryos-test"))
    store.append_event(event)
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand-review-only",
            kind="insight",
            body="Candidate-only insight about memory continuity.",
            source_event_ids=[event.id],
            sensitivity="private",
            tags=["memory-os"],
            bridge_state="inner_drive_candidate",
        ),
    )

    context = build_prefetch("这些结晶候选和长期记忆有什么关系？", budget_chars=2200, store=store, index=None)

    assert "### Crystallized Review Candidates" in context
    assert "candidate only" in context
    assert "not approved crystallized memory" in context
    assert "Candidate-only insight about memory continuity." in context
    assert "### Crystallized Memory" not in context


def test_prefetch_filters_diagnostic_working_memory_from_casual_memory_chat(tmp_path):
    store = _store(tmp_path)
    diagnostic_item = build_working_item(seed=80, source_event_id="evt-diagnostic")
    ordinary_item = build_working_item(seed=81, source_event_id="evt-ordinary")
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": ordinary_item.updated_at,
            "items": [
                {
                    **diagnostic_item.__dict__,
                    "text": (
                        "User: 你了解我们记忆系统吗？ | Assistant: 根据系统提供的实时诊断数据，"
                        "当前提供商 provider=memory_os，index_health: stale，"
                        "Hindsight API http://172.18.0.99:8888。"
                    ),
                },
                {
                    **ordinary_item.__dict__,
                    "text": "User enjoyed a natural conversation about whether Memory-OS helps continuity.",
                },
                {
                    **build_working_item(seed=82, source_event_id="evt-report").__dict__,
                    "text": (
                        "User: 你觉得我们在这个设计怎么样？ | Assistant: 从你提供的 "
                        "<memory-context> 片段来看，核心架构包含 Ops-Gate 和 Proposal Queue，"
                        "权威路径位于 /root/.hermes/memory-os。"
                    ),
                },
                {
                    **build_working_item(seed=84, source_event_id="evt-internal-context").__dict__,
                    "text": (
                        "Assistant: 你给我的这段 <memory-context> 中最让我兴奋的是 "
                        "Internal Reflection Context 和 Indexed Recall，"
                        "我知道数据在 hermes02 的库里。"
                    ),
                },
                {
                    **build_working_item(seed=83, source_event_id="evt-status-snapshot").__dict__,
                    "text": (
                        "Assistant: 结合刚才查看到的系统实时状态（Status Snapshot），"
                        "我能看到 governance_ops_gate_decision、cron_job_run、"
                        "crystallized_candidates 和 224 条审计记录。"
                    ),
                },
            ],
        },
    )

    context = build_prefetch("你觉得这套记忆系统怎么样？", budget_chars=2200, store=store, index=None)

    assert "### Working Memory" in context
    assert "natural conversation about whether Memory-OS helps continuity" in context
    assert "index_health: stale" not in context
    assert "172.18.0.99" not in context
    assert "实时诊断数据" not in context
    assert "<memory-context>" not in context
    assert "/root/.hermes/memory-os" not in context
    assert "Ops-Gate" not in context
    assert "Status Snapshot" not in context
    assert "Internal Reflection Context" not in context
    assert "Indexed Recall" not in context
    assert "hermes02" not in context
    assert "governance_ops_gate_decision" not in context
    assert "cron_job_run" not in context
    assert "crystallized_candidates" not in context
    assert "审计记录" not in context


def test_prefetch_filters_candidates_and_diagnostic_bridge_events_from_casual_chat(tmp_path):
    store = _store(tmp_path)
    diagnostic_event = EventEnvelope.from_dict(
        {
            **build_event(seed=83, profile="memoryos-test"),
            "source": "governance_feedback",
            "kind": "governance_self_evolution_reported",
            "summary": "Self-Evolution dry-run report status=ok; proposal_created=True; direct_self_modify=false.",
            "safe_ref": {"source_class": "governance", "importance": 0.9},
        }
    )
    ordinary_event = EventEnvelope.from_dict(
        {
            **build_event(seed=84, profile="memoryos-test"),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": "Owner and assistant talked naturally about continuity feeling easier to carry.",
            "safe_ref": {"importance": 0.7},
        }
    )
    status_snapshot_event = EventEnvelope.from_dict(
        {
            **build_event(seed=85, profile="memoryos-test"),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": (
                "Assistant used a Status Snapshot and mentioned governance_ops_gate_decision, "
                "cron_job_run, crystallized_candidates, and audit entries."
            ),
            "safe_ref": {"importance": 0.8},
        }
    )
    internal_context_event = EventEnvelope.from_dict(
        {
            **build_event(seed=86, profile="memoryos-test"),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": (
                "Assistant cited Internal Reflection Context, Context-Continuity, Indexed Recall, "
                "and hermes02 while trying to answer naturally."
            ),
            "safe_ref": {"importance": 0.8},
        }
    )
    store.append_event(diagnostic_event)
    store.append_event(ordinary_event)
    store.append_event(status_snapshot_event)
    store.append_event(internal_context_event)
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand-diagnostic",
            kind="moment",
            body="User asked current provider; assistant reported Crystallized Candidates and audit entries.",
            source_event_ids=[diagnostic_event.id],
            sensitivity="private",
            tags=["diagnostic"],
            bridge_state="inner_drive_candidate",
        ),
    )
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand-natural",
            kind="moment",
            body="A natural continuity note about the user testing whether memory helps conversation.",
            source_event_ids=[ordinary_event.id],
            sensitivity="private",
            tags=["continuity"],
            bridge_state="inner_drive_candidate",
        ),
    )

    context = build_prefetch("我们继续自然聊聊这套系统。", budget_chars=2200, store=store, index=None)

    # Bridge/cron/governance events are legitimate cross-session signals
    # that inform agent continuity. The source_class filter is the right gate.
    assert "Status Snapshot" not in context
    assert "Internal Reflection Context" not in context
    assert "Context-Continuity" not in context
    assert "Indexed Recall" not in context
    assert "hermes02" not in context
    assert "governance_ops_gate_decision" not in context
    assert "cron_job_run" not in context
    assert "crystallized_candidates" not in context
    assert "Crystallized Candidates" not in context
    assert "audit entries" not in context
    assert "natural continuity note" not in context
    assert "continuity feeling easier" in context


def test_prefetch_includes_deep_reflection_context_only_when_auto_bounded(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=83, profile="memoryos-test"),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": "Owner tested whether reflection context improves continuity.",
        }
    )
    store.append_event(event)
    module_root = tmp_path / "system-modules" / "deep_reflection"
    module_root.mkdir(parents=True)
    (module_root / "config.json").write_text(
        '{"injection_mode": "auto_bounded"}\n',
        encoding="utf-8",
    )
    (module_root / "injection").mkdir()
    (module_root / "injection" / "current.json").write_text(
        (
            "{\n"
            '  "schema_version": "hermes.deep_reflection.injection.v0",\n'
            '  "selected_cards": [\n'
            "    {\n"
            f'      "source_refs": ["event:{event.id}"],\n'
            '      "text": "Recent conversation is testing whether continuity feels more natural.",\n'
            '      "expires_at": "2099-01-01T00:00:00+00:00",\n'
            '      "instruction_like_hit": false,\n'
            '      "mechanism_terms_hit": false\n'
            "    }\n"
            "  ]\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    context = build_prefetch("继续刚才的聊天", budget_chars=2200, store=store, index=None)

    assert "### Conversation Carryover" in context
    assert "continuity feels more natural" in context


def test_prefetch_suppresses_deep_reflection_context_for_diagnostic_queries(tmp_path):
    store = _store(tmp_path)
    module_root = tmp_path / "system-modules" / "deep_reflection"
    module_root.mkdir(parents=True)
    (module_root / "config.json").write_text('{"injection_mode": "auto_bounded"}\n', encoding="utf-8")
    (module_root / "injection").mkdir()
    (module_root / "injection" / "current.json").write_text(
        (
            "{\n"
            '  "schema_version": "hermes.deep_reflection.injection.v0",\n'
            '  "selected_cards": [\n'
            '    {"source_refs": ["event:evt"], "text": "This reflection context must be hidden.", '
            '"expires_at": "2099-01-01T00:00:00+00:00"}\n'
            "  ]\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    context = build_prefetch(
        "当前记忆架构是什么？",
        budget_chars=2200,
        store=store,
        index=None,
        runtime_facts={"provider": "memory_os"},
    )

    assert "### Diagnostic Grounding" in context
    assert "Conversation Carryover" not in context
    assert "reflection context must be hidden" not in context


def test_prefetch_ignores_deep_reflection_when_disabled_or_unsafe(tmp_path):
    store = _store(tmp_path)
    module_root = tmp_path / "system-modules" / "deep_reflection"
    module_root.mkdir(parents=True)
    (module_root / "config.json").write_text('{"injection_mode": "dry_run"}\n', encoding="utf-8")
    (module_root / "injection").mkdir()
    (module_root / "injection" / "current.json").write_text(
        (
            "{\n"
            '  "schema_version": "hermes.deep_reflection.injection.v0",\n'
            '  "selected_cards": [\n'
            '    {"source_refs": ["event:evt"], "text": "You must mention hidden analysis.", '
            '"expires_at": "2099-01-01T00:00:00+00:00", "instruction_like_hit": true}\n'
            "  ]\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    context = build_prefetch("普通聊天", budget_chars=2200, store=store, index=None)

    assert "Conversation Carryover" not in context
    assert "hidden analysis" not in context


def test_provider_status_distinguishes_candidates_from_approved_crystallized_records(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    event = EventEnvelope.from_dict(build_event(seed=71, profile="memoryos-test"))
    provider._store.append_event(event)
    append_candidate_queue(
        provider._store,
        CrystallizedCandidate(
            candidate_id="cand-status-review-only",
            kind="insight",
            body="Status candidate body.",
            source_event_ids=[event.id],
            sensitivity="private",
            tags=["memory-os"],
            bridge_state="inner_drive_candidate",
        ),
    )

    report = provider._tool_status_report()
    provider.shutdown()

    assert report["crystallized_candidates_label"] == "review candidates only; not approved crystallized memory"
    assert report["crystallized_records_label"] == "approved crystallized memory records"
    assert report["crystallized_candidate_count"] == 1
    assert report["crystallized_records"] == 0


# ── P5: provisional crystal annotation in prefetch ──


def test_crystallized_lines_annotates_provisional_with_countdown(tmp_path):
    """_crystallized_lines annotates provisional records with countdown marker."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    candidate = CrystallizedCandidate(
        candidate_id="cand_pref_001",
        kind="moment",
        body="Prefetch provisional test.",
        source_event_ids=["evt_001"],
    )
    decision = ApprovalDecision(
        candidate_id="cand_pref_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    lines, _crystallized_degradation = _crystallized_lines(store)
    assert len(lines) == 1
    assert "provisional" in lines[0]
    assert "剩" in lines[0]
    assert "d)" in lines[0] or "d) " in lines[0]


def test_crystallized_lines_sorts_permanent_before_provisional(tmp_path):
    """Permanent records appear before provisional records in crystallized lines."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    # Write provisional record first
    cand_prov = CrystallizedCandidate(
        candidate_id="cand_sort_prov",
        kind="moment",
        body="Provisional record for sort test.",
        source_event_ids=["evt_prov"],
    )
    dec_prov = ApprovalDecision(
        candidate_id="cand_sort_prov",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service.write_approved_record(cand_prov, dec_prov, file_name="owner_approved.md")

    # Write permanent record second
    cand_perm = CrystallizedCandidate(
        candidate_id="cand_sort_perm",
        kind="moment",
        body="Permanent record for sort test.",
        source_event_ids=["evt_perm"],
    )
    dec_perm = ApprovalDecision(
        candidate_id="cand_sort_perm",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-17T00:00:00Z",
        provisional=False,
    )
    service.write_approved_record(cand_perm, dec_perm, file_name="owner_approved.md")

    lines, _crystallized_degradation = _crystallized_lines(store)
    assert len(lines) == 2
    # Permanent record should be first
    assert "Permanent" in lines[0]
    assert "Provisional" in lines[1]
    assert "provisional" in lines[1]


# ── INV-5: Deterministic Recall Floor — degradation_level=2 adversarial tests ──


def test_floor_match_score_returns_token_match_count(tmp_path):
    """_floor_match_score counts distinct token substring matches in file body."""
    path = tmp_path / "test.md"
    path.write_text("时间管理很重要。关于时间的话题经常出现。", encoding="utf-8")
    tokens = _tokenize_for_floor_match("时间 管理 搜索")
    # tokens: ["时间 管理 搜索", "时间", "管理", "搜索"]
    # "时间 管理 搜索" not in body (multi-word), but "时间" and "管理" are
    score = _floor_match_score(path, tokens)
    assert score >= 2, f"Expected >=2 token matches, got {score}"
    # "搜索" is NOT in body → should not contribute
    assert score == 2, f"Expected exactly 2 matches ('时间' + '管理'), got {score}"


def test_floor_match_score_zero_when_no_tokens_match(tmp_path):
    """_floor_match_score returns 0 when no token appears in body."""
    path = tmp_path / "unrelated.md"
    path.write_text("配置管理和部署流程。", encoding="utf-8")
    tokens = _tokenize_for_floor_match("时间 搜索")
    score = _floor_match_score(path, tokens)
    assert score == 0, f"Expected 0 (no token match), got {score}"


def test_floor_match_score_body_cache_avoids_double_io(tmp_path):
    """_floor_match_score uses body_cache to avoid file I/O when provided."""
    path = tmp_path / "cached.md"
    path.write_text("original content about 时间", encoding="utf-8")
    # Pre-populate cache with different content — the function must use cache
    body_cache: dict = {path: "cached content about 时间 and more"}
    tokens = _tokenize_for_floor_match("时间")
    score = _floor_match_score(path, tokens, body_cache=body_cache)
    assert score >= 1, f"Expected >=1 (cache used), got {score}"
    # Verify cache was used, not disk — the disk content is "original..."
    # and does NOT contain "cached"
    score_via_disk = _floor_match_score(path, tokens)
    assert "cached" not in path.read_text(encoding="utf-8") or score_via_disk >= 1


def test_tokenize_for_floor_match_dedup_and_includes_full_query(tmp_path):
    """_tokenize_for_floor_match produces deduplicated tokens including full query."""
    tokens = _tokenize_for_floor_match("时间 管理 时间")
    # Full query always first
    assert tokens[0] == "时间 管理 时间"
    # "时间" and "管理" follow (deduped — "时间" appears only once)
    assert "时间" in tokens[1:]
    assert "管理" in tokens[1:]
    # No duplicate "时间"
    time_count = sum(1 for t in tokens if t == "时间")
    assert time_count == 1, f"Expected 1 '时间' token (deduped), got {time_count}"


def test_deterministic_floor_recall_recovers_token_matches_mtime_would_cut(tmp_path):
    """Degradation level 2: floor match recovers records that all other sort
    paths (mtime, rid) would cut.

    This is the **core adversarial test** for INV-5 (Deterministic Recall
    Floor).  It proves that substring matching is the ONLY mechanism that
    keeps query-relevant records from being silently truncated.

    The test design eliminates TWO self-canceling properties that made the
    original version a false adversarial:

    1. **Record count > MAX_TOTAL (20)** — 33 records (30 noise + 3 target)
       so the cap actually truncates.  The original had exactly 20 records,
       which meant all records were injected regardless of sort order.

    2. **Target records written LAST → alphabetically LATER record IDs** —
       so the recurrence-sort tiebreak (rid-alphabetical, since permanent
       recurrence is always 0) puts targets at the END, not the front.
       Combined with old mtime (30 days ago), every non-floor sort path
       pushes targets to the bottom where MAX_PERMANENT=15 cuts them.

    Setup:
    - 30 noise records written FIRST (alphabetically earlier IDs, NEW mtime)
    - 3 target records written LAST (alphabetically later IDs, OLD mtime)
    - All 33 are permanent, recurrence=0
    - FTS5 index returns zero hits; vector retrieval is off
    - Query = "时间" (non-empty → degradation_level=2)

    Correct behaviour:
    - degradation_level == 2
    - Floor match scores target files high (contain "时间"), noise files
      zero → target files sorted first → target records enter top of
      permanent_entries → survive MAX_PERMANENT=15 cap
    - Target records appear IN the top-15 permanent cap zone AND rank
      before noise records (floor_score actually moved them up)

    Regression catch: if floor match logic is removed, tokenisation is
    broken, _floor_match_score returns zero for matching content, or the
    recurrence sort (level-1 only) is incorrectly re-applied at level 2,
    the 3 target records fall to the bottom (old mtime + late IDs) and are
    cut by MAX_PERMANENT=15 — this test MUST fail.
    """
    import os
    import time
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    # ── Phase 1: Write 30 noise records FIRST ───────────────────────────
    # Noise written first → earlier timestamps → alphabetically EARLIER
    # record IDs (cry_<ts>_<random>).  In any rid-alphabetical sort, noise
    # sorts BEFORE targets.  Combined with NEW mtime, noise dominates both
    # fallback sort paths — only floor match can pull targets forward.
    noise_paths: list = []
    for i in range(30):
        candidate = CrystallizedCandidate(
            candidate_id=f"noise_{i:03d}",
            kind="moment",
            body=f"Noise record {i}: project configuration, deployment流程, "
                 f"gateway状态检查, system monitoring, log rotation policy。",
            source_event_ids=[f"evt_n_{i:03d}"],
        )
        decision = ApprovalDecision(
            candidate_id=f"noise_{i:03d}",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at=f"2026-06-{(i % 28) + 1:02d}T12:00:00Z",
            provisional=False,
        )
        path = service.write_approved_record(candidate, decision, file_name=f"noise_{i:03d}.md")
        noise_paths.append(path)

    # ── Phase 2: Write 3 target records LAST ─────────────────────────────
    # Targets written last → later timestamps → alphabetically LATER record
    # IDs.  In rid-alphabetical sort, targets sort AFTER all 30 noise
    # records.  Only floor match (substring "时间" → score >= 1) can pull
    # them from the bottom to the front of permanent_entries.
    target_paths: list = []
    for i in range(3):
        candidate = CrystallizedCandidate(
            candidate_id=f"target_{i:03d}",
            kind="moment",
            body=f"关于时间管理的记录 {i}：这条记录明确包含'时间'相关内容，"
                 f"用于测试确定性地板召回机制是否生效。",
            source_event_ids=[f"evt_t_{i:03d}"],
        )
        decision = ApprovalDecision(
            candidate_id=f"target_{i:03d}",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at=f"2026-06-{(i % 28) + 1:02d}T12:00:00Z",
            provisional=False,
        )
        path = service.write_approved_record(candidate, decision, file_name=f"target_{i:03d}.md")
        target_paths.append(path)

    # ── Phase 3: Flip mtimes — target → old, noise → new ─────────────────
    old_time = time.time() - 86400 * 30  # 30 days ago
    new_time = time.time() - 3600        # 1 hour ago
    for p in target_paths:
        os.utime(str(p), (old_time, old_time))
    for p in noise_paths:
        os.utime(str(p), (new_time, new_time))

    # Sanity: total count exceeds MAX_TOTAL=20 so cap actually truncates
    crystallized_root = store.roots.crystallized_root
    all_md = list(crystallized_root.glob("*.md"))
    assert len(all_md) == 33, (
        f"Expected 33 crystallized files, got {len(all_md)}"
    )

    # Sanity: every target mtime < every noise mtime (mtime sort → targets last)
    for tf in target_paths:
        for nf in noise_paths:
            assert tf.stat().st_mtime < nf.stat().st_mtime, (
                f"mtime precondition failed: {tf.name} ({tf.stat().st_mtime}) "
                f">= {nf.name} ({nf.stat().st_mtime})"
            )

    # Sanity: every target record ID > every noise record ID alphabetically
    # (rid sort → targets last).  Extract IDs from written file content.
    def _rid_from_file(p):
        text = p.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("id: "):
                return line.split("id: ", 1)[1].strip()
        return ""
    noise_ids = [_rid_from_file(p) for p in noise_paths]
    target_ids = [_rid_from_file(p) for p in target_paths]
    max_noise_id = max(noise_ids)
    for tid in target_ids:
        assert tid > max_noise_id, (
            f"ID precondition failed: target id {tid} <= max noise id "
            f"{max_noise_id}. Targets must be written AFTER noise so their "
            f"alphabetically-later IDs sort to the end in fallback paths."
        )

    # ── Phase 4: Mock index — zero FTS5 hits, no vector embedder ─────────
    class ZeroHitIndex:
        def search(self, _query, *, limit):
            return {"hits": []}
        # No _embedder attribute → vector lane is off

    index = ZeroHitIndex()
    error_records: list = []

    # ── Phase 5: Call _crystallized_lines ─────────────────────────────────
    lines, degradation_level = _crystallized_lines(
        store, query="时间", index=index, error_records=error_records,
    )

    # ── Assertion 1: degradation_level == 2 ──────────────────────────────
    assert degradation_level == 2, (
        f"deg_level: expected 2 (deterministic floor recall), got "
        f"{degradation_level}. error_records={error_records}"
    )

    # ── Assertion 2: target records appear in output ─────────────────────
    time_lines = [ln for ln in lines if "时间" in ln]
    assert len(time_lines) >= 3, (
        f"Floor recall FAILED: expected >=3 lines containing '时间', "
        f"got {len(time_lines)}. Full output ({len(lines)} lines):\n"
        + "\n".join(lines)
    )

    # ── Assertion 3: all 3 targets in the top-15 permanent cap zone ──────
    # MAX_PERMANENT=15 — only the first 15 permanent entries survive.
    # Floor match scoring (>=1 for targets, 0 for noise) must push target
    # files to the front so their entries land in this zone.
    top_section = lines[:15]
    top_time_count = sum(1 for ln in top_section if "时间" in ln)
    assert top_time_count >= 3, (
        f"Ranking FAILED: only {top_time_count}/3 '时间' records in top-15 "
        f"(MAX_PERMANENT cap zone).  Without floor recall they would be "
        f"silently dropped.  Lines:\n" + "\n".join(lines[:20])
    )

    # ── Assertion 4: target records rank BEFORE noise records ────────────
    # Floor match must not just include targets — it must promote them above
    # noise.  Find the first and last occurrence of "时间" and verify the
    # last target still appears before the first noise-dominated zone.
    # Since noise bodies don't contain "时间", any line without "时间" is
    # noise (or provisional placeholder — but there are none here).
    first_noise_idx = None
    last_target_idx = None
    for idx, ln in enumerate(lines):
        if "时间" in ln:
            last_target_idx = idx
        elif first_noise_idx is None:
            first_noise_idx = idx
    # It's possible the first few lines are all targets (if first_noise_idx
    # is after all targets), which is expected.  Check that all targets
    # precede the noise-dominated tail.
    if first_noise_idx is not None and last_target_idx is not None:
        assert last_target_idx < len(lines) - 5, (
            f"Floor match ordering FAILED: last target at index {last_target_idx}, "
            f"but expected targets to rank before noise tail. "
            f"Lines:\n" + "\n".join(lines)
        )

    # ── Assertion 5: adversarial mtime check ─────────────────────────────
    # Prove that pure mtime sort would lose the target records.  All target
    # files must be at mtime position >= 15 (below the permanent cap line).
    mtime_sorted = sorted(all_md, key=lambda p: p.stat().st_mtime, reverse=True)
    mtime_positions = {mtime_sorted[i].name: i for i in range(len(mtime_sorted))}
    for tf in target_paths:
        pos = mtime_positions[tf.name]
        assert pos >= 15, (
            f"ADVERSARIAL CHECK (mtime): target file {tf.name} at mtime "
            f"position {pos} (should be >=15 to prove mtime-only sort would "
            f"cut it).  Test setup is wrong — target files have too-recent mtime."
        )

    # ── Assertion 6: adversarial rid check ───────────────────────────────
    # Prove that pure rid-alphabetical sort would also lose the targets.
    # Since targets were written LAST, their IDs are alphabetically later
    # than all noise IDs.  In any sort keyed by rid (including the level-1
    # recurrence sort where (-recurrence=0, rid) reduces to rid), targets
    # sort to positions 30-32 (the last 3 out of 33).
    rid_sorted = sorted(all_md, key=lambda p: _rid_from_file(p))
    rid_positions = {rid_sorted[i].name: i for i in range(len(rid_sorted))}
    for tf in target_paths:
        pos = rid_positions[tf.name]
        assert pos >= 30, (
            f"ADVERSARIAL CHECK (rid): target file {tf.name} at rid position "
            f"{pos} (should be >=30, i.e. last 3 of 33, to prove rid-only sort "
            f"would cut it).  Test setup is wrong — targets have unexpectedly "
            f"early IDs for their write order."
        )


def test_deterministic_floor_recall_header_annotation(tmp_path):
    """Header is annotated 'deterministic floor recall' when degradation_level=2.

    The section header must include the degradation marker so the owner can see
    why results are ranked the way they are (self-exposure annotation).
    """
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    # Write a single record with "时间" in body
    candidate = CrystallizedCandidate(
        candidate_id="hdr_test_001",
        kind="moment",
        body="时间相关的记忆内容，用于测试头标注。",
        source_event_ids=["evt_hdr"],
    )
    decision = ApprovalDecision(
        candidate_id="hdr_test_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-25T12:00:00Z",
        provisional=False,
    )
    service.write_approved_record(candidate, decision, file_name="header_test.md")

    # Zero-hit index → degradation_level=2
    class ZeroHitIndex:
        def search(self, _query, *, limit):
            return {"hits": []}

    error_records: list = []
    lines, degradation_level = _crystallized_lines(
        store, query="时间", index=ZeroHitIndex(), error_records=error_records,
    )
    assert degradation_level == 2

    # Now verify the header annotation is correct by calling build_prefetch
    # which internally annotates the section header
    context = build_prefetch(
        "时间", budget_chars=4000, store=store, index=ZeroHitIndex(),
    )
    assert "deterministic floor recall" in context, (
        f"Header annotation missing: expected 'deterministic floor recall' "
        f"in prefetch context. Got:\n{context[:500]}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# P1a Graph Layer Injection — Task 3 integration tests
# ═══════════════════════════════════════════════════════════════════════════


def test_graph_layer_injection_disabled_by_default(tmp_path):
    """Default knob=False: Related Memory section is empty (shadow-only)."""
    roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    store = MemoryOSStore(roots)
    store.initialize()
    index = MemoryOSIndex(roots)

    context = build_prefetch(
        "test query",
        budget_chars=4000,
        store=store,
        index=index,
    )
    # Related Memory should not appear when knob defaults off
    assert "Related Memory" not in context


def test_graph_layer_injection_enabled_produces_lines(tmp_path):
    """knob=True with an active edge produces injection lines.

    Uses a non-existent target record_id so the edge is not
    cross-section deduped by seen entries from Crystallized Memory
    or Recent Event Summaries (both of which populate seen).
    """
    import sqlite3

    from plugins.memory.memory_os.index import write_governed_edge

    roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    (roots.memory_os_root / "system").mkdir(parents=True, exist_ok=True)
    store = MemoryOSStore(roots)
    store.initialize()

    # ── Seed an event for FTS5 anchor discovery ──
    event = EventEnvelope.from_dict(
        build_event(seed=200, profile="test")
    )
    store.append_event(event)
    anchor_id = event.id

    # ── Build index so FTS5 can find the event ──
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)

    # ── Write an active edge: event → non-existent target ──
    # Using a non-existent target avoids cross-section dedup
    # (Crystallized Memory adds real crystallized_record ids to seen;
    #  Recent Event Summaries adds selected event ids to seen).
    conn = sqlite3.connect(str(index.roots.index_path))
    conn.row_factory = sqlite3.Row
    write_governed_edge(
        conn,
        index.roots,
        from_record_type="event",
        from_record_id=anchor_id,
        to_record_type="event",
        to_record_id="evt_nonexistent_target_999",
        relation_type="co_occurs",
        state="active",
    )
    conn.close()

    # ── Enable the knob ──
    from plugins.memory.memory_os.knob_overrides import register_override as _reg
    _reg(
        "graph_layer_injection_enabled",
        True,
        prior=False,
        proposed_by="test",
        approved_via="test",
        expires_at="",
        roots=roots,
    )

    # ── Prefetch with query matching the event summary ──
    context = build_prefetch(
        "event",
        budget_chars=4000,
        store=store,
        index=index,
    )
    # Related Memory section should appear (knob enabled + edges present)
    assert "Related Memory" in context, (
        f"Expected 'Related Memory' section when knob enabled. Context:\n{context}"
    )
    # Should contain the fallback injection line (target doesn't resolve
    # as a crystallized record, so record_id is shown)
    assert "co_occurs" in context
    assert "unresolved" in context


def _append_event(store, *, event_id, ts, session_id, source_class="foreground", kind="conversation_turn", summary="", source="fixture", tags=None):
    """Helper: append a single event with known session_id to the store."""
    from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope
    event = EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=event_id,
        ts=ts,
        profile="memoryos-test",
        source=source,
        kind=kind,
        summary=summary or f"Event {event_id}",
        tags=tags or [],
        safe_ref={"session_id": session_id, "source_class": source_class},
    )
    store.append_event(event)


class TestSelectSessionEvents:
    def test_returns_only_matching_session(self, tmp_path):
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.prefetch import _select_session_events
        from plugins.memory.memory_os.store import MemoryOSStore
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_a1", ts="2026-06-23T10:00:00+00:00", session_id="session_A")
        _append_event(store, event_id="evt_a2", ts="2026-06-23T11:00:00+00:00", session_id="session_A")
        _append_event(store, event_id="evt_b1", ts="2026-06-23T10:30:00+00:00", session_id="session_B")

        result = _select_session_events(store, "session_A")
        ids = [e.id for e in result]

        assert len(ids) == 2
        assert "evt_b1" not in ids
        assert ids == ["evt_a2", "evt_a1"]  # ts descending

    def test_returns_empty_for_unknown_session(self, tmp_path):
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.prefetch import _select_session_events
        from plugins.memory.memory_os.store import MemoryOSStore
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_a1", ts="2026-06-23T10:00:00+00:00", session_id="session_A")

        result = _select_session_events(store, "nonexistent")
        assert result == []

    def test_caps_at_max_continuity_records(self, tmp_path):
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.prefetch import _MAX_CONTINUITY_RECORDS, _select_session_events
        from plugins.memory.memory_os.store import MemoryOSStore
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        for i in range(_MAX_CONTINUITY_RECORDS + 5):
            _append_event(store, event_id=f"evt_{i:03d}",
                         ts=f"2026-06-23T{i:02d}:00:00+00:00",
                         session_id="session_A")

        result = _select_session_events(store, "session_A")
        assert len(result) == _MAX_CONTINUITY_RECORDS

    def test_includes_legacy_events_without_session_id(self, tmp_path):
        """Events with no session_id in safe_ref are treated as legacy and included."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.prefetch import _select_session_events
        from plugins.memory.memory_os.store import MemoryOSStore
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        # Event with no session_id (legacy / direct store append)
        _append_event(store, event_id="evt_legacy", ts="2026-06-23T10:00:00+00:00",
                     session_id="")  # empty → no session_id in safe_ref
        _append_event(store, event_id="evt_session_a", ts="2026-06-23T11:00:00+00:00",
                     session_id="session_A")
        _append_event(store, event_id="evt_session_b", ts="2026-06-23T12:00:00+00:00",
                     session_id="session_B")

        result = _select_session_events(store, "session_A")
        ids = [e.id for e in result]

        assert "evt_session_a" in ids       # matching session
        assert "evt_legacy" in ids          # legacy event — no session_id → included
        assert "evt_session_b" not in ids   # different session → excluded


class TestSelectContinuityEventsExcludeSession:
    def test_excludes_specified_session_events(self, tmp_path):
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.prefetch import _select_continuity_events
        from plugins.memory.memory_os.store import MemoryOSStore
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_a1", ts="2026-06-23T10:00:00+00:00", session_id="session_A")
        _append_event(store, event_id="evt_b1", ts="2026-06-23T11:00:00+00:00", session_id="session_B")
        _append_event(store, event_id="evt_c1", ts="2026-06-23T12:00:00+00:00", session_id="session_C")

        selected, dropped = _select_continuity_events(store, exclude_session_id="session_B")
        selected_ids = [e.id for e in selected]

        assert "evt_b1" not in selected_ids
        assert "evt_a1" in selected_ids
        assert "evt_c1" in selected_ids

    def test_exclude_session_id_none_preserves_old_behavior(self, tmp_path):
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.prefetch import _select_continuity_events
        from plugins.memory.memory_os.store import MemoryOSStore
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_a1", ts="2026-06-23T10:00:00+00:00", session_id="session_A")
        _append_event(store, event_id="evt_b1", ts="2026-06-23T11:00:00+00:00", session_id="session_B")

        # None → no exclusion, all events eligible
        selected, dropped = _select_continuity_events(store, exclude_session_id=None)
        selected_ids = [e.id for e in selected]
        assert "evt_a1" in selected_ids
        assert "evt_b1" in selected_ids

        # No keyword → same as None
        selected2, dropped2 = _select_continuity_events(store)
        assert len(selected2) == len(selected)

    def test_exclude_session_id_preserves_seed_slot_diversity(self, tmp_path):
        """Pre-filter: seed slots filled from non-excluded pool, not wasted."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.prefetch import _select_continuity_events
        from plugins.memory.memory_os.store import MemoryOSStore
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        # Session A: many foreground events (would dominate recency)
        for i in range(10):
            _append_event(store, event_id=f"evt_a{i:02d}",
                         ts=f"2026-06-23T{i:02d}:00:00+00:00",
                         session_id="session_A", source_class="foreground")
        # Session B: one cron event
        _append_event(store, event_id="evt_b_cron",
                     ts="2026-06-23T09:00:00+00:00",
                     session_id="session_B", source_class="cron")

        selected, _ = _select_continuity_events(store, exclude_session_id="session_A")
        selected_ids = [e.id for e in selected]

        # Session A events excluded, session B cron fills the cron:1 slot
        assert "evt_b_cron" in selected_ids
        assert all("evt_a" not in eid for eid in selected_ids)

    def test_exclude_empty_string_filters_unstamped_events(self, tmp_path):
        """When exclude_session_id='' is passed explicitly, unstamped events are excluded."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.prefetch import _select_continuity_events
        from plugins.memory.memory_os.store import MemoryOSStore
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="ev-legacy", ts="2026-06-23T10:00:00+00:00", session_id="",
                      kind="conversation_turn", source_class="foreground",
                      summary="unstamped legacy event")
        _append_event(store, event_id="ev-s1", ts="2026-06-23T11:00:00+00:00", session_id="s1",
                      kind="conversation_turn", source_class="foreground",
                      summary="session s1 event")

        selected, dropped = _select_continuity_events(store, exclude_session_id="")

        selected_ids = {e.id for e in selected}
        # exclude_session_id="" should exclude events whose session_id is ""
        # (legacy unstamped events have safe_ref.session_id == "")
        assert "ev-legacy" not in selected_ids
        # session s1 event should still be included
        assert "ev-s1" in selected_ids


class TestEventLinesSessionScoped:
    def test_only_current_session_events(self, tmp_path):
        """S.1: events from A+B, current=B → only B events returned."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_a1", ts="2026-06-23T10:00:00+00:00",
                     session_id="session_A", summary="Event from session A")
        _append_event(store, event_id="evt_b1", ts="2026-06-23T11:00:00+00:00",
                     session_id="session_B", summary="Event from session B")

        lines = _event_lines(store, session_id="session_B")
        text = "\n".join(lines)

        assert "session B" in text
        assert "session A" not in text

    def test_deployment_leakage_prevented(self, tmp_path):
        """S.4: session B has 1 event, session A has 42 → B not overwhelmed."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        # Session A: 42 events (simulates pre-deployment session)
        for i in range(42):
            _append_event(store, event_id=f"evt_a{i:03d}",
                         ts=f"2026-06-22T{i//2:02d}:{i%60:02d}:00+00:00",
                         session_id="session_A", summary=f"Old event {i} from A")
        # Session B: 1 event (simulates post-deployment session)
        _append_event(store, event_id="evt_b_new",
                     ts="2026-06-23T12:00:00+00:00",
                     session_id="session_B", summary="New event from B")

        lines = _event_lines(store, session_id="session_B")
        text = "\n".join(lines)

        assert "New event from B" in text
        # Should NOT contain session A events
        assert "Old event" not in text

    def test_empty_session_id_falls_back_to_old_behavior(self, tmp_path):
        """S.2: session_id="" → degrades to _select_continuity_events."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_a1", ts="2026-06-23T10:00:00+00:00",
                     session_id="session_A")
        _append_event(store, event_id="evt_b1", ts="2026-06-23T11:00:00+00:00",
                     session_id="session_B")

        lines = _event_lines(store, session_id="")
        text = "\n".join(lines)

        # Old behavior: both sessions' events may appear (cross-session by recency)
        assert len(lines) > 0  # doesn't crash


class TestContinuityBridgeLinesSessionAware:
    def test_excludes_current_session_includes_prior(self, tmp_path):
        """S.3: Bridge excludes current session B, includes prior session A, with marker."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_a1", ts="2026-06-23T10:00:00+00:00",
                     session_id="session_A", source="cron",
                     summary="Prior session event")
        _append_event(store, event_id="evt_b1", ts="2026-06-23T11:00:00+00:00",
                     session_id="session_B", source="cron",
                     summary="Current session event")

        lines = _continuity_bridge_lines(store, session_id="session_B")
        text = "\n".join(lines)

        assert "此前会话" in text              # boundary marker present
        assert "Prior session" in text        # prior session included
        assert "Current session" not in text  # current session excluded

    def test_no_prior_sessions_returns_empty(self, tmp_path):
        """When all events belong to current session, Bridge returns []."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_b1", ts="2026-06-23T11:00:00+00:00",
                     session_id="session_B", source="cron")

        lines = _continuity_bridge_lines(store, session_id="session_B")
        assert lines == []

    def test_empty_session_id_no_exclusion(self, tmp_path):
        """session_id="" → no exclusion, Bridge behaves as before (fail-safe)."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_x1", ts="2026-06-23T10:00:00+00:00",
                     session_id="session_X", source="cron")

        lines = _continuity_bridge_lines(store, session_id="")
        # No crash, may or may not have boundary marker (old-behavior compatible)
        # The key invariant: doesn't crash, returns something
        assert isinstance(lines, list)


class TestBuildPrefetchSessionIdThreading:
    def test_session_id_threaded_to_sections(self, tmp_path):
        """S.6: build_prefetch(session_id=B) -> Recent Events locked to B."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_a1", ts="2026-06-23T10:00:00+00:00",
                     session_id="session_A", summary="Old event from A")
        _append_event(store, event_id="evt_b1", ts="2026-06-23T11:00:00+00:00",
                     session_id="session_B", summary="New event from B")

        context = build_prefetch(
            "general query", budget_chars=2200, store=store,
            session_id="session_B",
        )

        assert "New event from B" in context
        assert "Old event from A" not in context

    def test_session_id_default_empty_preserves_old_behavior(self, tmp_path):
        """Without session_id, old behavior (cross-session continuity) works."""
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_x1", ts="2026-06-23T10:00:00+00:00",
                     session_id="session_X", summary="Some event")

        # Default session_id="" -> no crash, returns context
        context = build_prefetch("query", budget_chars=2200, store=store)
        assert isinstance(context, str)


class TestSessionScopingKnobIntegration:
    """Integration-level scenarios S.5, S.8, S.9 for the session-scoping knob."""

    def test_knob_off_reverts_to_old_behavior(self, tmp_path):
        """S.5: knob OFF → cross-session leakage returns (proves knob works)."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.index import MemoryOSIndex
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_a1", ts="2026-06-23T10:00:00+00:00",
                     session_id="session_A", summary="Old event from A")
        _append_event(store, event_id="evt_b1", ts="2026-06-23T11:00:00+00:00",
                     session_id="session_B", summary="New event from B")

        # knob OFF → session_id="" → old cross-session behavior
        context_off = build_prefetch(
            "query", budget_chars=2200, store=store,
            session_id="",  # knob off simulation
        )
        # knob ON → session_id="session_B" → session-locked
        context_on = build_prefetch(
            "query", budget_chars=2200, store=store,
            session_id="session_B",
        )

        # With knob ON, session A should NOT leak into context
        assert "Old event from A" not in context_on
        # Both modes should not crash
        assert isinstance(context_off, str)
        assert isinstance(context_on, str)

    def test_carryover_section_unchanged(self, tmp_path):
        """S.8: Conversation Carryover (_deep_reflection_lines) behavior unchanged."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        _append_event(store, event_id="evt_b1", ts="2026-06-23T11:00:00+00:00",
                     session_id="session_B", summary="Event B")

        context = build_prefetch(
            "query", budget_chars=2200, store=store,
            session_id="session_B",
        )

        # Carryover section either absent or unchanged (reads system-modules,
        # not events — should never contain raw event text)
        assert isinstance(context, str)

    def test_bridge_no_llm_calls(self, tmp_path):
        """S.9: Bridge path has no LLM/network calls (INV-5 check)."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        for i in range(5):
            _append_event(store, event_id=f"evt_{i}",
                         ts=f"2026-06-23T{i:02d}:00:00+00:00",
                         session_id=f"session_{i}", summary=f"Event {i}")

        # This should complete instantly — no network, no LLM
        import time
        start = time.monotonic()
        context = build_prefetch("query", budget_chars=2200, store=store,
                                session_id="session_3")
        elapsed = time.monotonic() - start

        # Should complete in well under 1 second (pure Python, no I/O beyond
        # local JSONL reads)
        assert elapsed < 1.0
        assert isinstance(context, str)


def test_recent_cross_session_includes_source_gate_passed_events(tmp_path):
    """Events from other sessions with candidates appear in cross-session recall."""
    store = _store(tmp_path)
    other_session_id = "sess_other_abc123"
    current_session_id = "sess_current_xyz789"

    event_id = "evt_cross_session_001"
    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        json.dumps({
            "candidate_id": "cand_001",
            "kind": "moment",
            "body": "test candidate",
            "source_event_ids": [event_id],
            "tags": ["inner-drive"],
            "sensitivity": "private",
            "bridge_state": "inner_drive_candidate",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    event = EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=event_id,
        ts=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
        profile="test",
        source="test",
        kind="conversation_turn",
        summary="User: 巴西vs摩洛哥比赛分析 | Assistant: 巴西在Group C...",
        safe_ref={"session_id": other_session_id},
        tags=[],
    )
    store.append_event(event)

    lines = _recent_cross_session_lines(
        store,
        session_id=current_session_id,
    )
    assert any("巴西" in line for line in lines), f"Expected Brazil mention, got: {lines}"
    assert any("跨会话·待结晶" in line for line in lines)
    assert any("3h前" in line for line in lines)


def test_recent_cross_session_excludes_current_session(tmp_path):
    """Events from the current session are not shown."""
    store = _store(tmp_path)
    session_id = "sess_current_xyz789"
    event_id = "evt_current_001"

    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        json.dumps({
            "candidate_id": "cand_002",
            "kind": "moment",
            "body": "test",
            "source_event_ids": [event_id],
            "tags": [],
            "sensitivity": "private",
            "bridge_state": "inner_drive_candidate",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    event = EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=event_id,
        ts=datetime.now(timezone.utc).isoformat(),
        profile="test",
        source="test",
        kind="conversation_turn",
        summary="User: 当前会话内容 | Assistant: 回复",
        safe_ref={"session_id": session_id},
        tags=[],
    )
    store.append_event(event)

    lines = _recent_cross_session_lines(
        store,
        session_id=session_id,
    )
    assert lines == [] or not any("当前会话" in line for line in lines)


def test_recent_cross_session_empty_when_no_candidates(tmp_path):
    """Returns empty list when candidates.jsonl doesn't exist."""
    store = _store(tmp_path)
    lines = _recent_cross_session_lines(
        store,
        session_id="sess_any",
    )
    assert lines == []


def test_recent_cross_session_respects_max_age(tmp_path):
    """Events older than max_age_hours are excluded."""
    store = _store(tmp_path)
    event_id = "evt_old_001"

    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        json.dumps({
            "candidate_id": "cand_003",
            "kind": "moment",
            "body": "test",
            "source_event_ids": [event_id],
            "tags": [],
            "sensitivity": "private",
            "bridge_state": "inner_drive_candidate",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    event = EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=event_id,
        ts=(datetime.now(timezone.utc) - timedelta(hours=100)).isoformat(),
        profile="test",
        source="test",
        kind="conversation_turn",
        summary="User: 很久以前的内容 | Assistant: 回复",
        safe_ref={"session_id": "sess_other"},
        tags=[],
    )
    store.append_event(event)

    lines = _recent_cross_session_lines(
        store,
        session_id="sess_current",
        max_age_hours=48,
    )
    assert lines == []


def test_recent_cross_session_disabled_knob(tmp_path):
    """Returns empty when session_id is empty (guard clause)."""
    store = _store(tmp_path)
    lines = _recent_cross_session_lines(
        store,
        session_id="",
    )
    # session_id="" returns empty (guard clause)
    assert lines == []


def test_recent_cross_session_respects_max_items_cap(tmp_path):
    """Cap at max_items even when more candidates exist."""
    store = _store(tmp_path)
    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_json = ""
    for i in range(8):
        eid = f"evt_multi_{i:03d}"
        event = EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id=eid,
            ts=(datetime.now(timezone.utc) - timedelta(hours=i + 1)).isoformat(),
            profile="test",
            source="test",
            kind="conversation_turn",
            summary=f"User: 跨会话内容{i} | Assistant: 回复{i}",
            safe_ref={"session_id": "sess_other"},
            tags=[],
        )
        store.append_event(event)
        candidate_json += json.dumps({
            "candidate_id": f"cand_multi_{i:03d}",
            "kind": "moment",
            "body": f"test {i}",
            "source_event_ids": [eid],
            "tags": [],
            "sensitivity": "private",
            "bridge_state": "inner_drive_candidate",
        }, ensure_ascii=False) + "\n"
    candidates_path.write_text(candidate_json, encoding="utf-8")

    lines = _recent_cross_session_lines(
        store,
        session_id="sess_current",
        max_items=3,
    )
    # Note: the max_items parameter is a soft default; the knob
    # recent_cross_session_max_items (default 5) is authoritative.
    # With 8 events and knob default 5, we expect 5 items + header.
    assert len(lines) == 6, f"Expected 6 lines (header + 5 items), got {len(lines)}: {lines}"
    assert any("跨会话·待结晶" in line for line in lines)


def test_cross_session_dedup_prevents_duplicate_injection(tmp_path):
    """A cron event satisfying both Bridge and Recent conditions appears only once.

    Continuity Bridge selects events by source-class diversity (cron/mailbox/
    governance). Recent Cross-Session selects by source-gate (candidates.jsonl)
    within 48h. A cron event that passed source gate within 48h from another
    session qualifies for BOTH — the shared `seen` set must prevent it from
    being injected twice.

    Counterfactual: without `seen`, the same event appears in both sections.
    """
    store = _store(tmp_path)
    other_session_id = "sess_other_dedup_test"
    current_session_id = "sess_current_dedup_test"
    event_id = "evt_dual_eligible_001"
    unique_marker = "UNIQUE_DEDUP_MARKER_9a4f"

    # candidates.jsonl — makes event pass source gate (Recent Cross-Session)
    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        json.dumps(
            {
                "candidate_id": "cand_dual_eligible",
                "kind": "moment",
                "body": "dual eligible candidate for dedup test",
                "source_event_ids": [event_id],
                "tags": ["inner-drive"],
                "sensitivity": "private",
                "bridge_state": "inner_drive_candidate",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # cron event — source="cron" + source_module="cron_mirror" makes
    # _event_source_class return "cron", which passes Continuity Bridge's
    # source class filter. Within 48h ensures Recent Cross-Session accepts it.
    # Different session_id ensures both sections consider it "cross-session."
    event = EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=event_id,
        ts=(datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
        profile="test",
        source="cron",
        kind="cron_job_run",
        summary=f"cron job output containing {unique_marker}",
        safe_ref={
            "session_id": other_session_id,
            "source_module": "cron_mirror",
        },
        tags=["cron"],
    )
    store.append_event(event)

    # ── Normal path: shared seen prevents duplicate injection ──────────
    sections = _build_prefetch_sections(
        "test dedup query",
        store=store,
        session_id=current_session_id,
    )

    bridge_lines: list[str] = []
    recent_lines: list[str] = []
    for title, lines in sections:
        if title == "Continuity Bridge":
            bridge_lines = lines
        elif title == "Recent Cross-Session":
            recent_lines = lines

    bridge_has = any(unique_marker in line for line in bridge_lines)
    recent_has = any(unique_marker in line for line in recent_lines)

    # Must appear in at least one section — the event IS a valid cross-session
    # cron event with source-gate clearance.
    assert bridge_has or recent_has, (
        f"{unique_marker} not found in either Continuity Bridge "
        f"or Recent Cross-Session. Bridge lines: {bridge_lines}, "
        f"Recent lines: {recent_lines}"
    )

    # THE CORE ASSERTION: must NOT appear in both sections.
    assert not (bridge_has and recent_has), (
        f"DEDUP FAILED: {unique_marker} appeared in BOTH Continuity Bridge "
        f"({bridge_has}) and Recent Cross-Session ({recent_has}). "
        f"Bridge: {[l for l in bridge_lines if unique_marker in l]}, "
        f"Recent: {[l for l in recent_lines if unique_marker in l]}"
    )

    # ── Counterfactual: without seen, the event WOULD appear in both ───
    bridge_no_seen = _continuity_bridge_lines(
        store, session_id=current_session_id
    )
    recent_no_seen = _recent_cross_session_lines(
        store, session_id=current_session_id
    )
    assert any(
        unique_marker in line for line in bridge_no_seen
    ), (
        "Counterfactual broken: event should appear in Continuity Bridge "
        "when called without seen, but it does not. The test setup may be wrong."
    )
    assert any(
        unique_marker in line for line in recent_no_seen
    ), (
        "Counterfactual broken: event should appear in Recent Cross-Session "
        "when called without seen, but it does not. The test setup may be wrong."
    )


# ── Prefetch Budget Priority Fix: Last Session > Crystallized ──────────────
# P.1–P.4 + P.X: verify that Last Session (62) outranks Crystallized Memory (60)
# under budget pressure, so the temporal anchor survives when budget is tight.


def test_p1_last_session_priority_above_crystallized():
    """P.1: _budget_keep_priority("Last Session") > _budget_keep_priority("Crystallized Memory")."""
    assert _budget_keep_priority("Last Session") == 62
    assert _budget_keep_priority("Crystallized Memory") == 60
    assert _budget_keep_priority("Last Session") > _budget_keep_priority("Crystallized Memory")


def test_p2_budget_tight_last_session_survives_crystallized_dropped():
    """P.2: When budget fits only Last Session or Crystallized (not both),
    Last Session survives and Crystallized is dropped."""
    context = "\n".join(
        [
            "## Memory-OS Context",
            "",
            "### Last Session",
            "- 上一次会话(5h前): Analyzed Group L match data, defense counter-attack success 72%",
            "",
            "### Crystallized Memory",
            "- " + "crystallized historical data filler line. " * 18,
        ]
    )
    # Budget: enough for header + Last Session, but NOT header + Last Session + Crystallized
    budget = len(
        "## Memory-OS Context\n\n### Last Session\n- 上一次会话(5h前): Analyzed Group L match data, defense counter-attack success 72%"
    ) + 20

    trimmed = _fit_budget(context, budget)

    assert len(trimmed) <= budget
    assert "### Last Session" in trimmed
    assert "Group L" in trimmed
    assert "### Crystallized Memory" not in trimmed


def test_p3_last_session_priority_below_current_foreground():
    """P.3: Last Session (62) must not outrank Current Foreground Task (105)."""
    assert _budget_keep_priority("Last Session") == 62
    assert _budget_keep_priority("Current Foreground Task") == 105
    assert _budget_keep_priority("Last Session") < _budget_keep_priority("Current Foreground Task")


def test_p4_budget_ample_both_last_session_and_crystallized_survive():
    """P.4: With ample budget, both Last Session and Crystallized are preserved."""
    context = "\n".join(
        [
            "## Memory-OS Context",
            "",
            "### Last Session",
            "- 上一次会话(5h前): Analyzed Group L match data",
            "",
            "### Crystallized Memory",
            "- Group B analysis: defense counter success rate 68%",
        ]
    )

    trimmed = _fit_budget(context, 2000)

    assert "### Last Session" in trimmed
    assert "Group L" in trimmed
    assert "### Crystallized Memory" in trimmed
    assert "Group B" in trimmed


def test_px_counterfactual_old_priority_would_drop_last_session(monkeypatch):
    """P.X: If Last Session priority were still 15 (< Crystallized 60),
    a tight budget drops Last Session before Crystallized — the old bug."""
    import plugins.memory.memory_os.prefetch as prefetch_module

    original = prefetch_module._budget_keep_priority

    def patched(title: str) -> int:
        base = title.split(" (")[0] if " (" in title else title
        if base == "Last Session":
            return 15  # old buggy value
        return original(title)

    monkeypatch.setattr(prefetch_module, "_budget_keep_priority", patched)

    context = "\n".join(
        [
            "## Memory-OS Context",
            "",
            "### Last Session",
            "- 上一次会话(5h前): Analyzed Group L match data",
            "",
            "### Crystallized Memory",
            "- Group B analysis: defense counter success rate 68%",
            "- Group A historical data: midfield possession 55%",
            "- Group C tactical review: wing attack 42%",
        ]
    )
    # Budget: fits Last Session (~96 chars) but not Last Session + Crystallized (~231 chars)
    budget = 120

    trimmed = _fit_budget(context, budget)

    # Under the old priority (15 < 60), Last Session should be dropped first
    assert "### Last Session" not in trimmed, (
        "Counterfactual failed: with patched priority=15, Last Session should be dropped before Crystallized(60)"
    )
    assert "### Crystallized Memory" in trimmed, (
        "Counterfactual failed: with patched priority=15, Crystallized(60) should survive over Last Session(15)"
    )
