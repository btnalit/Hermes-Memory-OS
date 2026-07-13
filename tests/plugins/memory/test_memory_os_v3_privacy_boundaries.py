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
