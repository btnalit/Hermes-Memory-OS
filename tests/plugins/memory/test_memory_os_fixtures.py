from collections.abc import Iterator

from plugins.memory.memory_os.fixtures import (
    build_crystallized_frontmatter,
    build_event,
    build_sannai_multi_root_fixture,
    build_working_item,
    generate_event_corpus,
)
from plugins.memory.memory_os.schema import EventEnvelope


def test_fixture_factories_are_deterministic_for_same_seed():
    first_event = build_event(seed=17, profile="sannai")
    second_event = build_event(seed=17, profile="sannai")
    first_working = build_working_item(seed=17, source_event_id=first_event["id"])
    second_working = build_working_item(seed=17, source_event_id=second_event["id"])
    first_crystallized = build_crystallized_frontmatter(seed=17, source_event_ids=[first_event["id"]])
    second_crystallized = build_crystallized_frontmatter(seed=17, source_event_ids=[second_event["id"]])

    assert first_event == second_event
    assert first_working == second_working
    assert first_crystallized == second_crystallized
    assert first_event["summary"] == "Synthetic memory event 17 for sannai"


def test_fixture_factories_vary_by_seed_while_preserving_schema():
    first = build_event(seed=17, profile="sannai")
    second = build_event(seed=18, profile="sannai")

    assert first["id"] != second["id"]
    assert first["ts"] != second["ts"]
    assert EventEnvelope.from_dict(first).profile == "sannai"
    assert EventEnvelope.from_dict(second).profile == "sannai"


def test_sannai_multi_root_fixture_creates_separate_profile_and_state_roots(tmp_path):
    layout = build_sannai_multi_root_fixture(tmp_path)

    assert layout.profile == "sannai"
    assert layout.hermes_home != layout.state_root
    assert (layout.hermes_home / "SOUL.md").read_text(encoding="utf-8") == "Synthetic Sannai soul\n"
    assert (layout.hermes_home / "memories" / "MEMORY.md").exists()
    assert (layout.hermes_home / "memories" / "USER.md").exists()
    assert (layout.state_root / "diary.md").exists()
    assert (layout.state_root / "self_memory.md").exists()
    assert (layout.state_root / "lingering_thoughts.json").exists()
    assert layout.roots.hermes_home == layout.hermes_home.resolve()
    assert layout.roots.external_state_roots == (layout.state_root.resolve(),)


def test_event_corpus_generator_is_streaming_and_schema_valid():
    corpus = generate_event_corpus(count=3, seed=91, profile="memoryos-test")

    assert isinstance(corpus, Iterator)
    events = list(corpus)
    assert len(events) == 3
    assert [event["summary"] for event in events] == [
        "Synthetic memory event 91 for memoryos-test",
        "Synthetic memory event 92 for memoryos-test",
        "Synthetic memory event 93 for memoryos-test",
    ]
    assert all(EventEnvelope.from_dict(event).profile == "memoryos-test" for event in events)
