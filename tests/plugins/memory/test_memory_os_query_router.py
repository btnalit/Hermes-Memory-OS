from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import build_prefetch, plan_query_route
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


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
                    "record_id": "evt-route",
                    "snippet": "Routed indexed recall hit.",
                }
            ],
        }


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_query_router_fast_path_extracts_mixed_operational_keywords():
    route = plan_query_route("查查刚才 PCDN 为什么报错 loss_rate")

    assert route["route"] == "fast_path"
    assert route["search_query"] == "PCDN loss_rate"
    assert route["display_query"] == "PCDN loss_rate"


def test_query_router_slow_path_for_abstract_query_without_entities():
    route = plan_query_route("上次那个老问题又出现了")

    assert route["route"] == "slow_path"
    assert route["search_query"] == "上次那个老问题又出现了"


def test_query_router_diagnostic_route_preserves_diagnostic_authority():
    route = plan_query_route("当前记忆架构是什么？")

    assert route["route"] == "diagnostic"
    assert route["search_query"] == ""


def test_query_router_redacts_secret_like_user_input():
    route = plan_query_route("帮我查 api_key=SUPERSECRET gateway_restart 为什么失败")

    assert route["route"] == "fast_path"
    assert "SUPERSECRET" not in route["search_query"]
    assert "SUPERSECRET" not in route["display_query"]
    assert "gateway_restart" in route["search_query"]


def test_prefetch_uses_routed_query_and_reports_route(tmp_path):
    store = _store(tmp_path)
    index = RecordingIndex()

    context = build_prefetch(
        "查查刚才 PCDN 为什么报错 loss_rate",
        budget_chars=2200,
        store=store,
        index=index,
        diagnostic_grounding_enabled=True,
    )

    assert index.queries == [("PCDN loss_rate", 5), ("PCDN loss_rate", 5)]
    assert "query route: fast_path" in context
    assert "PCDN loss_rate" in context
    assert "Routed indexed recall hit." in context


def test_prefetch_keeps_targeted_indexed_recall_inside_tight_budget(tmp_path):
    store = _store(tmp_path)
    rare = EventEnvelope.from_dict(
        {
            **build_event(seed=90, profile="memoryos-test"),
            "summary": "Rare operational payload includes PCDN loss_rate.",
            "safe_ref": {"producer": "pcdn_cron", "metrics": {"loss_rate": 0.08}},
        }
    )
    store.append_event(rare)
    for seed in range(91, 105):
        store.append_event(
            EventEnvelope.from_dict(
                {
                    **build_event(seed=seed, profile="memoryos-test"),
                    "summary": f"Generic recent summary filler {seed} " * 8,
                }
            )
        )
    index = MemoryOSIndex(store.roots)
    index.sync_from_store(store)

    context = build_prefetch(
        "查查刚才 PCDN 为什么报错 loss_rate",
        budget_chars=900,
        store=store,
        index=index,
        diagnostic_grounding_enabled=True,
    )

    assert "### Indexed Recall" in context
    assert "query route: fast_path" in context
    assert rare.id in context
