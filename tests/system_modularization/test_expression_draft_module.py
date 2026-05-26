import json

from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.expression.expression_draft import ExpressionDraftModule


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_expression_draft_stores_bounded_preview_and_boundaries(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {**build_event(seed=1, profile="main"), "summary": "Owner talked about right brain expression."}
    )
    store.append_event(event)
    module = ExpressionDraftModule(tmp_path, profile="main")

    context = module.build_context(store=store, max_refs=3)
    draft = module.create_draft(
        store=store,
        source_module="wandering_mind",
        text_preview="今天我想安静地把这条线索放在心里。",
        source_refs=[f"event:{event.id}"],
        feeling_tags=["quiet"],
        risk_flags=[],
    )

    assert context["raw_body_included"] is False
    assert context["source_refs"] == [f"event:{event.id}"]
    assert draft["schema_version"] == "hermes.memory_os.expression_draft.v0"
    assert draft["draft_id"].startswith("expr_")
    assert draft["source_module"] == "wandering_mind"
    assert draft["text_preview"] == "今天我想安静地把这条线索放在心里。"
    assert draft["raw_body_included"] is False
    assert draft["actual_send"] is False
    assert draft["actual_execute"] is False
    assert draft["actual_identity_write"] is False
    assert module.read_recent_drafts(limit=1)[0]["draft_id"] == draft["draft_id"]
    rendered = json.dumps(draft, ensure_ascii=False)
    assert '"raw_body":' not in rendered


def test_expression_draft_accepts_silent_as_product_outcome(tmp_path):
    store = _store(tmp_path)
    module = ExpressionDraftModule(tmp_path, profile="main")

    draft = module.create_draft(
        store=store,
        source_module="deep_reflection",
        text_preview="[SILENT]",
        source_refs=[],
        silence_reason="not_enough_signal",
    )

    assert draft["text_preview"] == "[SILENT]"
    assert draft["silence_reason"] == "not_enough_signal"
    assert draft["actual_send"] is False
