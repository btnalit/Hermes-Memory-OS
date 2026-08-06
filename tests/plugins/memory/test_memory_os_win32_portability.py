"""Windows portability counterfactual tests.

Covers two audited defect classes:

1. Top-level ``import fcntl`` in legacy_right_brain_retirement (POSIX-only)
   broke pytest collection on Windows through the cognitive_loop and monitor
   dashboard snapshot import chains.
2. POSIX-only directory fsync (``os.open(dir, os.O_RDONLY)`` raises
   PermissionError on Windows) in the private atomic writers of
   wandering_journal / v3_retention / v3_body_packet / v3_seed_evidence /
   legacy_right_brain_retirement.

Each test FAILS without the corresponding fix and PASSES with it.  The
directory-descriptor denial is simulated by monkeypatching ``os.open`` so the
counterfactual holds on every platform, not only on Windows.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from plugins.memory.memory_os import legacy_right_brain_retirement as retirement_module
from plugins.memory.memory_os import v3_seed_evidence
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.v3_body_packet import body_packet_manifests_path, remove_body_manifests
from plugins.memory.memory_os.v3_retention import sweep_pending_expired, v3_journal_sweep_status_path
from plugins.memory.memory_os.wandering_journal import query_journal, wandering_journal_path

RETIREMENT_MODULE_NAME = "plugins.memory.memory_os.legacy_right_brain_retirement"


def _store(tmp_path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path / ".hermes", profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _deny_directory_descriptor(monkeypatch) -> None:
    """Make ``os.open`` on a directory raise PermissionError, as Windows does."""

    real_os_open = os.open

    def guarded_open(path, flags, *args, **kwargs):
        try:
            is_directory = Path(path).is_dir()
        except TypeError:
            is_directory = False
        if is_directory:
            raise PermissionError(13, "simulated Windows directory descriptor denial", str(path))
        return real_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)


# ── Defect 1: top-level `import fcntl` (POSIX-only) ─────────────────────────


def test_legacy_right_brain_retirement_imports_when_fcntl_is_unavailable(monkeypatch):
    """Counterfactual: an unguarded top-level ``import fcntl`` makes this
    module (and its importers cognitive_loop / cli / the monitor dashboard
    snapshot script) fail to import on Windows.  Blocking fcntl in
    sys.modules reproduces that on any platform; without the guarded-import
    fix this test fails everywhere."""

    original = sys.modules.pop(RETIREMENT_MODULE_NAME, None)
    monkeypatch.setitem(sys.modules, "fcntl", None)  # `import fcntl` -> ImportError
    try:
        module = importlib.import_module(RETIREMENT_MODULE_NAME)
        assert module.fcntl is None
        assert callable(module.legacy_right_brain_read_lock)
    finally:
        sys.modules.pop(RETIREMENT_MODULE_NAME, None)
        if original is not None:
            sys.modules[RETIREMENT_MODULE_NAME] = original


# ── Defect 2: POSIX-only directory fsync in private atomic writers ──────────


def test_wandering_journal_query_trace_writes_without_directory_descriptor(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _deny_directory_descriptor(monkeypatch)

    assert query_journal(store, scope_class="all") == []

    trace = json.loads(wandering_journal_path(store).read_text(encoding="utf-8").splitlines()[-1])
    assert set(trace) == {"schema_version", "record_type", "queried_at", "scope"}
    assert trace["record_type"] == "query_trace"
    assert trace["scope"] == "all"


def test_v3_ttl_sweep_status_writes_without_directory_descriptor(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _deny_directory_descriptor(monkeypatch)

    report = sweep_pending_expired(store, now=datetime(2026, 7, 15, tzinfo=timezone.utc))

    assert report["cycle_status"] == "ok"
    status = json.loads(v3_journal_sweep_status_path(store).read_text(encoding="utf-8"))
    assert status == {"cycle_status": "ok"}


def test_v3_body_packet_manifest_rewrite_without_directory_descriptor(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _deny_directory_descriptor(monkeypatch)

    remove_body_manifests(store, {"snap-absent"})

    assert body_packet_manifests_path(store).read_text(encoding="utf-8") == ""


def test_v3_seed_evidence_snapshot_writes_without_directory_descriptor(tmp_path, monkeypatch):
    _deny_directory_descriptor(monkeypatch)
    target = tmp_path / "system" / "v3_seed_evidence_snapshot.json"

    v3_seed_evidence._atomic_write_json(target, {"schema_version": "test", "value": 1})

    assert json.loads(target.read_text(encoding="utf-8")) == {"schema_version": "test", "value": 1}


def test_legacy_retirement_config_disable_without_directory_descriptor(tmp_path, monkeypatch):
    (tmp_path / "memory-os").mkdir(parents=True)
    _deny_directory_descriptor(monkeypatch)

    retirement_module._disable_legacy_config(tmp_path)

    config = json.loads((tmp_path / "memory-os" / "config.json").read_text(encoding="utf-8"))
    section = config["right_brain_expression"]
    assert section["legacy_cognitive_loop_enabled"] is False
    assert section["recurring_delivery_enabled"] is False


# ── Lock semantics: the fallback must not break either platform ─────────────


def test_legacy_right_brain_locks_acquire_and_release_on_current_platform(tmp_path):
    """Shared locks coexist; an exclusive lock waits for the shared holder.

    Runs against the platform-native primitive (fcntl.flock on POSIX,
    LockFileEx on Windows), so it guards the POSIX path against regressions
    from the fallback and proves the Windows fallback keeps flock semantics.
    """

    # Two concurrent shared (read) locks in one process must coexist.
    with retirement_module.legacy_right_brain_read_lock(tmp_path):
        with retirement_module.legacy_right_brain_read_lock(tmp_path):
            pass

    entered = threading.Event()
    release = threading.Event()
    acquired = threading.Event()

    def hold_reader():
        with retirement_module.legacy_right_brain_read_lock(tmp_path):
            entered.set()
            assert release.wait(timeout=5)

    def take_writer():
        with retirement_module._legacy_right_brain_write_lock(tmp_path):
            acquired.set()

    reader = threading.Thread(target=hold_reader)
    reader.start()
    assert entered.wait(timeout=2)
    writer = threading.Thread(target=take_writer)
    writer.start()
    assert not acquired.wait(timeout=0.3)  # exclusive must wait for the reader
    release.set()
    reader.join(timeout=5)
    writer.join(timeout=5)
    assert acquired.is_set()
    assert not reader.is_alive()
    assert not writer.is_alive()

    # The exclusive (write) lock is acquirable and releasable afterwards.
    with retirement_module._legacy_right_brain_write_lock(tmp_path):
        pass
