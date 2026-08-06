from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_private_journal_and_manifest_are_not_indexed_prefetched_or_projected():
    forbidden_consumers = [
        REPO_ROOT / "plugins/memory/memory_os/index.py",
        REPO_ROOT / "plugins/memory/memory_os/prefetch.py",
        REPO_ROOT / "plugins/memory/memory_os/memory_sources.py",
        REPO_ROOT / "plugins/memory/memory_os/memory_projection.py",
        REPO_ROOT / "plugins/memory/memory_os/hindsight_substrate.py",
    ]
    private_names = ("wandering_journal.jsonl", "v3_body_packet_manifests.jsonl")
    for path in forbidden_consumers:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for private_name in private_names:
            assert private_name not in source, f"{path} consumes private V3 store {private_name}"


def test_v3_external_speech_has_exactly_one_speak_gate_adapter():
    modules = list((REPO_ROOT / "plugins/memory/memory_os").glob("v3_*.py"))
    speak_gate_users = []
    for path in modules:
        source = path.read_text(encoding="utf-8")
        assert "send_message(" not in source
        assert "delivery/outbox" not in source
        if "SpeakGateModule" in source:
            speak_gate_users.append(path.name)
    assert speak_gate_users == ["v3_outlet.py"]


def test_resolve_owner_channel_callers_are_symbol_enumerated():
    """The v3_*.py glob above cannot see non-v3 callers of speak_gate's
    private ``_resolve_owner_channel`` — cognitive_loop.py was an invisible
    second cross-module caller for months. Enumerate consumers BY SYMBOL over
    the whole plugin tree so a new caller (or a removed one) must touch this
    census consciously, instead of widening a directory glob that drifts from
    reality."""
    expected = {
        "plugins/modules/expression/speak_gate.py",  # the defining module
        "plugins/memory/memory_os/cognitive_loop.py",
        "plugins/memory/memory_os/v3_outlet.py",
    }
    actual = set()
    for path in (REPO_ROOT / "plugins").rglob("*.py"):
        if "_resolve_owner_channel" in path.read_text(encoding="utf-8"):
            actual.add(path.relative_to(REPO_ROOT).as_posix())
    assert actual == expected, (
        f"_resolve_owner_channel caller set changed: added={sorted(actual - expected)} "
        f"removed={sorted(expected - actual)} — update this census consciously"
    )


def test_private_store_names_do_not_appear_in_ragflow_or_backup_payload_builders():
    private_names = ("wandering_journal.jsonl", "v3_body_packet_manifests.jsonl")
    candidates = [
        *REPO_ROOT.glob("scripts/*ragflow*.py"),
        *REPO_ROOT.glob("plugins/memory/memory_os/*ragflow*.py"),
    ]
    for path in candidates:
        source = path.read_text(encoding="utf-8")
        for private_name in private_names:
            assert private_name not in source
