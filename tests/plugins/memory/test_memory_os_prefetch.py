from plugins.memory import load_memory_provider
from plugins.memory.memory_os.fixtures import (
    build_crystallized_frontmatter,
    build_event,
    build_working_item,
)
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import build_prefetch, continuity_selector_report
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
            "items": [working_item.__dict__],
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

    context = build_prefetch("memory", budget_chars=160, store=store, index=None)

    assert len(context) <= 160
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
    assert context.index("BRIDGE_CRON_MARKER") < context.find("NOISY_WORKING_MEMORY")


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
