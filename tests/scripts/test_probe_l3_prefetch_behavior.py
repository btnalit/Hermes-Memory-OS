import importlib

import pytest

from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def test_l3_probe_failure_revokes_and_compacts_provisional_record(tmp_path, monkeypatch):
    probe = importlib.import_module("scripts.probe_l3_prefetch_behavior")
    monkeypatch.setattr(probe, "HERMES_HOME", tmp_path)
    monkeypatch.setattr(probe, "LOG_FILE", tmp_path / "probe-log.json")

    def fail_prefetch(*args, **kwargs):
        raise RuntimeError("injected prefetch failure")

    monkeypatch.setattr(probe, "build_prefetch", fail_prefetch)

    with pytest.raises(RuntimeError, match="injected prefetch failure"):
        probe.run(cleanup=True)

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    service = CrystallizedMemoryService(store)
    assert service.read_records("_system_probe.md") == []


def test_probe_run_does_not_hardcode_an_explicit_profile():
    """run() must let the profiles/<name> home shape derive the profile: an
    explicit profile silently wins over the derivation (from_hermes_home has
    no contradiction check), so a hardcoded "default" would mis-attribute a
    sannai-home probe run the moment anything on the probe's write path
    starts stamping roots.profile."""
    import inspect

    probe = importlib.import_module("scripts.probe_l3_prefetch_behavior")
    assert "profile=" not in inspect.getsource(probe.run)


def test_probe_log_name_is_namespaced_per_profile(tmp_path):
    """Both profiles' evidence ticks fire on the same minute and the log name
    is only second-granular, so a shared tempdir name could let co-tenant
    probes overwrite each other's diagnostics."""
    probe = importlib.import_module("scripts.probe_l3_prefetch_behavior")

    assert probe._probe_log_slug(tmp_path / ".hermes") == ""
    assert probe._probe_log_slug(tmp_path / ".hermes" / "profiles" / "sannai") == "_sannai"
