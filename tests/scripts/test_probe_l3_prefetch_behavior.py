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
