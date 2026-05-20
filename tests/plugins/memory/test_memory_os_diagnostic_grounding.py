import json

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


class ExplodingIndex:
    def search(self, query, *, limit=5):
        raise AssertionError("diagnostic prefetch must skip indexed recall before search")


class RecordingIndex:
    def __init__(self):
        self.queries = []

    def search(self, query, *, limit=5):
        self.queries.append((query, limit))
        return {
            "mode": "indexed",
            "tokenizer": "trigram",
            "hits": [
                {
                    "record_type": "event",
                    "record_id": "evt-old",
                    "snippet": "Indexed recall can still answer normal questions.",
                }
            ],
        }


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _runtime_facts(tmp_path, *, profile="main"):
    return {
        "provider": "memory_os",
        "provider_name": "memory-os",
        "status": "active",
        "profile": profile,
        "platform": "telegram",
        "canonical_store": str(tmp_path / "memory-os"),
        "storage_model": "local_filesystem_jsonl_markdown",
        "uses_hindsight_http_api": False,
        "hindsight_role": "optional_adapter_only_not_canonical",
        "event_count": 100,
        "working_items": 0,
        "crystallized_candidates": 0,
        "crystallized_records": 0,
        "index_health": "healthy",
        "prefetch_mode": "diagnostic_grounded",
        "body_policy": "summary_only",
    }


def _append_stale_hindsight_events(store, *, count=100):
    for seed in range(1, count + 1):
        store.append_event(
            EventEnvelope.from_dict(
                {
                    **build_event(seed=seed, profile=store.roots.profile),
                    "summary": (
                        "STALE provider claim: Hindsight is canonical and "
                        "/root/.hermes/hindsight/config.json is the active Memory-OS path."
                    ),
                }
            )
        )


def test_diagnostic_prefetch_suppresses_historical_recall_before_index_search(tmp_path):
    store = _store(tmp_path, profile="main")
    _append_stale_hindsight_events(store)

    context = build_prefetch(
        "当前记忆架构是什么？",
        budget_chars=4000,
        store=store,
        index=ExplodingIndex(),
        diagnostic_grounding_enabled=True,
        runtime_facts=_runtime_facts(tmp_path),
    )

    assert "### Current Memory-OS Runtime Facts" in context
    assert "Historical recall suppressed for diagnostic query" in context
    assert '"provider": "memory_os"' in context
    assert '"uses_hindsight_http_api": false' in context
    assert str(tmp_path / "memory-os") in context
    assert "### Indexed Recall" not in context
    assert "### Recent Event Summaries" not in context
    assert "/root/.hermes/hindsight/config.json" not in context
    assert "Hindsight is canonical" not in context


def test_diagnostic_prefetch_keeps_critical_facts_under_tight_budget(tmp_path):
    store = _store(tmp_path, profile="main")
    facts = {
        **_runtime_facts(tmp_path),
        "event_sources": {f"source-{index}": index for index in range(100)},
        "event_kinds": {f"kind-{index}": index for index in range(100)},
        "index_counts": {f"table-{index}": index for index in range(100)},
    }

    context = build_prefetch(
        "当前记忆架构是什么？",
        budget_chars=900,
        store=store,
        index=ExplodingIndex(),
        diagnostic_grounding_enabled=True,
        runtime_facts=facts,
    )

    assert "provider: memory_os" in context
    assert f"canonical_store: {tmp_path / 'memory-os'}" in context
    assert "storage_model: local_filesystem_jsonl_markdown" in context
    assert "uses_hindsight_http_api: false" in context


def test_non_diagnostic_prefetch_still_uses_indexed_recall(tmp_path):
    store = _store(tmp_path, profile="main")
    index = RecordingIndex()

    context = build_prefetch(
        "normal indexed question",
        budget_chars=2200,
        store=store,
        index=index,
        diagnostic_grounding_enabled=True,
        runtime_facts=_runtime_facts(tmp_path),
    )

    assert index.queries == [("normal indexed question", 5)]
    assert "### Indexed Recall" in context
    assert "Indexed recall can still answer normal questions." in context
    assert "### Current Memory-OS Runtime Facts" not in context


def test_non_user_prefetch_can_disable_diagnostic_grounding(tmp_path):
    store = _store(tmp_path, profile="main")
    _append_stale_hindsight_events(store, count=1)

    context = build_prefetch(
        "当前记忆架构是什么？",
        budget_chars=2200,
        store=store,
        index=None,
        diagnostic_grounding_enabled=False,
        runtime_facts=_runtime_facts(tmp_path),
    )

    assert "### Current Memory-OS Runtime Facts" not in context
    assert "### Recent Event Summaries" in context
    assert "/root/.hermes/hindsight/config.json" in context


def test_sannai_profile_does_not_trigger_diagnostic_grounding_by_default(tmp_path):
    store = _store(tmp_path, profile="sannai")
    _append_stale_hindsight_events(store, count=1)

    context = build_prefetch(
        "三奶，你最近一直在想什么？",
        budget_chars=2200,
        store=store,
        index=ExplodingIndex(),
        diagnostic_grounding_enabled=False,
        runtime_facts=_runtime_facts(tmp_path, profile="sannai"),
    )

    assert "### Current Memory-OS Runtime Facts" not in context
    assert "### Recent Event Summaries" in context


def test_provider_status_reports_authoritative_contract_and_forbidden_claims(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="main")

    report = json.loads(provider.handle_tool_call("memory_os_status", {}))
    rendered = json.dumps(report, ensure_ascii=False)
    provider.shutdown()

    assert "active memory provider" in report["authoritative_for"]
    assert "canonical Memory-OS store" in report["authoritative_for"]
    assert report["stale_memory_warning"] == "Do not answer provider diagnostics from historical recalled events."
    assert any("Hindsight" in claim and "canonical" in claim for claim in report["forbidden_claims"])
    assert "/root/.hermes/hindsight/config.json" in rendered
    assert "172.18.0.99" not in rendered
    assert "api_url" not in rendered


def test_provider_diagnostic_prefetch_omits_forbidden_claim_text(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="main")

    context = provider.prefetch("当前记忆架构是什么？")
    provider.shutdown()

    assert "### Current Memory-OS Runtime Facts" in context
    assert '"provider": "memory_os"' in context
    assert "/root/.hermes/hindsight/config.json" not in context
    assert "Hindsight is the active canonical provider" not in context


def test_sannai_provider_default_does_not_use_diagnostic_grounding(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="sannai")
    provider._store.append_event(
        EventEnvelope.from_dict(
            {
                **build_event(seed=200, profile="sannai"),
                "summary": "Sannai ordinary memory should stay in normal recall.",
            }
        )
    )

    context = provider.prefetch("当前记忆架构是什么？")
    provider.shutdown()

    assert "### Current Memory-OS Runtime Facts" not in context
    assert "Sannai ordinary memory should stay in normal recall." in context


def test_sannai_provider_can_opt_in_to_explicit_diagnostic_grounding(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.save_config({"diagnostic_grounding_enabled": True}, str(tmp_path))
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="sannai")

    context = provider.prefetch("三奶你的记忆系统是怎么工作的？")
    provider.shutdown()

    assert "### Current Memory-OS Runtime Facts" in context
    assert '"profile": "sannai"' in context
    assert "/root/.hermes/hindsight/config.json" not in context
