from pathlib import Path

import pytest

from plugins.memory.memory_os.roots import MemoryOSRoots, RootValidationError


def test_roots_resolve_profile_local_memory_os_paths(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")

    assert roots.profile == "memoryos-test"
    assert roots.memory_os_root == tmp_path / "memory-os"
    assert roots.events_root == tmp_path / "memory-os" / "events"
    assert roots.working_root == tmp_path / "memory-os" / "working"
    assert roots.crystallized_root == tmp_path / "memory-os" / "crystallized"
    assert roots.identity_manifest_path == tmp_path / "memory-os" / "identity" / "manifest.json"
    assert roots.relationships_root == tmp_path / "memory-os" / "relationships"
    assert roots.index_path == tmp_path / "memory-os" / "index" / "memory_os.db"
    assert roots.audit_path == tmp_path / "memory-os" / "audit" / "write_audit.jsonl"
    assert roots.imports_root == tmp_path / "memory-os" / "imports"
    assert roots.quarantine_root == tmp_path / "memory-os" / "quarantine"


def test_roots_collect_sannai_multi_root_identity_sources(tmp_path):
    hermes_home = tmp_path / "root" / ".hermes" / "profiles" / "sannai"
    state_root = tmp_path / "vol1" / ".hermes" / "state" / "sannai"
    (hermes_home / "memories").mkdir(parents=True)
    state_root.mkdir(parents=True)
    (hermes_home / "SOUL.md").write_text("soul", encoding="utf-8")
    (hermes_home / "memories" / "MEMORY.md").write_text("memory", encoding="utf-8")
    (hermes_home / "memories" / "USER.md").write_text("user", encoding="utf-8")
    (state_root / "diary.md").write_text("diary", encoding="utf-8")
    (state_root / "self_memory.md").write_text("self", encoding="utf-8")
    (state_root / "lingering_thoughts.json").write_text("[]", encoding="utf-8")

    roots = MemoryOSRoots.from_hermes_home(
        hermes_home,
        profile="sannai",
        external_state_roots=[state_root],
    )

    source_by_kind = {source.kind: source for source in roots.identity_sources}
    assert source_by_kind["soul"].path == str((hermes_home / "SOUL.md").resolve())
    assert source_by_kind["memory"].path == str((hermes_home / "memories" / "MEMORY.md").resolve())
    assert source_by_kind["user"].path == str((hermes_home / "memories" / "USER.md").resolve())
    assert source_by_kind["state:diary"].path == str((state_root / "diary.md").resolve())
    assert source_by_kind["state:self_memory"].path == str((state_root / "self_memory.md").resolve())
    assert source_by_kind["state:lingering_thoughts"].memory_os_writable is False


def test_roots_reject_profile_path_traversal(tmp_path):
    with pytest.raises(RootValidationError, match="profile"):
        MemoryOSRoots.from_hermes_home(tmp_path, profile="../sannai")


def test_roots_reject_external_state_root_path_traversal(tmp_path):
    traversal = Path("..") / "state" / "sannai"

    with pytest.raises(RootValidationError, match="external_state_roots"):
        MemoryOSRoots.from_hermes_home(tmp_path, external_state_roots=[traversal])
