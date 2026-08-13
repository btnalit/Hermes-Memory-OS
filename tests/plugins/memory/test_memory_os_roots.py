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


def test_from_hermes_home_derives_profile_from_profile_shaped_home(tmp_path):
    # Counterfactual for the sannai mis-attribution: without derivation this
    # returned "" and every `roots.profile or "default"` consumer stamped the
    # sannai home's records as "default".
    hermes_home = tmp_path / ".hermes" / "profiles" / "sannai"
    hermes_home.mkdir(parents=True)

    roots = MemoryOSRoots.from_hermes_home(hermes_home)

    assert roots.profile == "sannai"


def test_from_hermes_home_keeps_empty_profile_for_plain_home(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path / ".hermes")

    assert roots.profile == ""


def test_from_hermes_home_explicit_profile_outranks_home_shape(tmp_path):
    # Hermes' agent identity may legitimately differ from the home directory
    # name, so an explicitly passed profile wins without raising here; the
    # fail-closed conflict semantics live in resolve_profile_name (the
    # script/cron surface, where "explicit" is env contamination instead).
    hermes_home = tmp_path / ".hermes" / "profiles" / "sannai"
    hermes_home.mkdir(parents=True)

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile="identity-name")

    assert roots.profile == "identity-name"


def test_resolve_profile_name_priority_and_conflict(tmp_path):
    from plugins.memory.memory_os.roots import resolve_profile_name

    plain_home = tmp_path / "home"
    sannai_home = tmp_path / "profiles" / "sannai"

    assert resolve_profile_name(plain_home, environ={}) == "default"
    assert resolve_profile_name(sannai_home, environ={}) == "sannai"
    assert resolve_profile_name(plain_home, environ={"HERMES_PROFILE": "sannai"}) == "sannai"
    assert resolve_profile_name(sannai_home, environ={"HERMES_PROFILE": "sannai"}) == "sannai"
    assert resolve_profile_name(plain_home, "explicit-x", environ={"HERMES_PROFILE": "env-y"}) == "explicit-x"

    with pytest.raises(RootValidationError, match="contradicts"):
        resolve_profile_name(sannai_home, environ={"HERMES_PROFILE": "default"})
    with pytest.raises(RootValidationError, match="contradicts"):
        resolve_profile_name(sannai_home, "other", environ={})
    with pytest.raises(RootValidationError, match="traversal"):
        resolve_profile_name(plain_home, "../escape", environ={})
