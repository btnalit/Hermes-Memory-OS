"""Deployment-integrity findings on `memory-os doctor`.

These checks live on `doctor` instead of a separate `deploy-doctor`
subcommand. The argument for splitting was noise on the README's
blank-machine lane, where `doctor` runs against a bare temp dir; gating each
check on the presence of the artifact it inspects removes that noise at the
source. `test_bare_profile_emits_no_deployment_findings` is what pins that
contract -- without it, someone can drop the gating and the blank-machine
lane silently becomes noisy again.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from plugins.memory.memory_os.cli import (
    _cron_snapshot_drift_findings,
    _deployment_integrity_checks,
    _orphan_systemd_unit_findings,
    build_doctor_result,
)
from plugins.memory.memory_os.cron_registry import (
    memory_os_cron_groups,
    memory_os_cron_specs,
    write_cron_registry_snapshot,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path: Path) -> MemoryOSStore:
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path / "home"))
    store.initialize()
    return store


def _snapshot_path(store: MemoryOSStore) -> Path:
    return store.roots.memory_os_root / "system" / "memory_os_cron_registry.json"


# ── The gating contract itself ────────────────────────────────────────────


def test_bare_profile_emits_no_deployment_findings(tmp_path, monkeypatch):
    """A profile with no snapshot and no unit files must stay silent.

    This is the whole justification for merging these checks into `doctor`
    instead of a separate subcommand. If it ever fails, either restore the
    gating or split the surface -- do not relax the assertion.
    """
    # Even where a real systemd exists, the answer must not depend on it.
    monkeypatch.setattr(
        "plugins.memory.memory_os.cli._systemctl_user_units", lambda: {"unrelated.timer"}
    )
    store = _store(tmp_path)

    assert _deployment_integrity_checks(store) == []
    assert build_doctor_result(store)["deployment_integrity_checks"]["count"] == 0


# ── (a) cron registry snapshot drift ──────────────────────────────────────


def test_snapshot_missing_a_registered_lane_is_reported(tmp_path):
    """Counterfactual: this is the failure CLAUDE.md records as undetected.

    The snapshot is produced by the REAL writer, then one lane is dropped --
    hand-rolling the JSON would let the test pass even if the writer's shape
    drifted away from what the runner reads.
    """
    store = _store(tmp_path)
    group = next(g for g in memory_os_cron_groups() if len(g.member_keys) >= 2)
    dropped = group.member_keys[0]

    specs = tuple(spec for spec in memory_os_cron_specs() if spec.key != dropped)
    trimmed_groups = tuple(
        g if g.key != group.key
        else dataclasses.replace(
            g, member_keys=tuple(k for k in g.member_keys if k != dropped)
        )
        for g in memory_os_cron_groups()
    )
    path = _snapshot_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_cron_registry_snapshot(path, specs=specs, groups=trimmed_groups)

    findings = _cron_snapshot_drift_findings(store)

    assert len(findings) == 1
    assert findings[0]["code"] == "cron_registry_snapshot_missing_lanes"
    assert findings[0]["details"]["missing_lane_keys"] == [dropped]
    assert findings[0]["details"]["group_key"] == group.key
    # Warning, not error: a version-skewed checkout against an older host
    # HOME is a real false-positive path, so this must not fail an install.
    assert findings[0]["severity"] == "warning"


def test_snapshot_matching_the_registry_is_silent(tmp_path):
    """The dual -- a correct host must produce nothing."""
    store = _store(tmp_path)
    path = _snapshot_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_cron_registry_snapshot(path, specs=memory_os_cron_specs(), groups=memory_os_cron_groups())

    assert _cron_snapshot_drift_findings(store) == []


def test_absent_snapshot_is_not_a_finding(tmp_path):
    """No snapshot means the runner falls back to the compiled-in registry."""
    store = _store(tmp_path)

    assert not _snapshot_path(store).exists()
    assert _cron_snapshot_drift_findings(store) == []


def test_unreadable_snapshot_is_reported_rather_than_swallowed(tmp_path):
    store = _store(tmp_path)
    path = _snapshot_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")

    findings = _cron_snapshot_drift_findings(store)

    assert len(findings) == 1
    assert findings[0]["code"] == "cron_registry_snapshot_unreadable"


# ── (b) orphan systemd units ──────────────────────────────────────────────


def _write_timer(store: MemoryOSStore, name: str) -> None:
    systemd_dir = store.roots.memory_os_root / "systemd"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    (systemd_dir / name).write_text("[Timer]\n", encoding="utf-8")


def test_unit_files_systemd_never_saw_are_reported(tmp_path, monkeypatch):
    """The exact shape the fresh-host deployment hit."""
    store = _store(tmp_path)
    _write_timer(store, "hermes-memory-os-cognitive-loop.timer")
    monkeypatch.setattr(
        "plugins.memory.memory_os.cli._systemctl_user_units",
        lambda: {"hermes-memory-os-heartbeat.timer"},
    )

    findings = _orphan_systemd_unit_findings(store)

    assert len(findings) == 1
    assert findings[0]["code"] == "systemd_timer_unit_not_registered"
    assert findings[0]["details"]["unregistered_units"] == [
        "hermes-memory-os-cognitive-loop.timer"
    ]
    # Install-without-enable plus cron fallback is a supported steady state.
    assert findings[0]["severity"] == "warning"


def test_registered_units_are_silent(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _write_timer(store, "hermes-memory-os-heartbeat.timer")
    monkeypatch.setattr(
        "plugins.memory.memory_os.cli._systemctl_user_units",
        lambda: {"hermes-memory-os-heartbeat.timer"},
    )

    assert _orphan_systemd_unit_findings(store) == []


def test_no_systemctl_means_no_sample_not_a_finding(tmp_path, monkeypatch):
    """Unknowable is not the same as broken -- and gets no invented severity."""
    store = _store(tmp_path)
    _write_timer(store, "hermes-memory-os-cognitive-loop.timer")
    monkeypatch.setattr("plugins.memory.memory_os.cli._systemctl_user_units", lambda: None)

    assert _orphan_systemd_unit_findings(store) == []


def test_profile_suffixed_unit_names_are_taken_from_disk(tmp_path, monkeypatch):
    """Unit names come from the filenames, never re-derived from the profile.

    Re-deriving the per-profile suffix is how a probe ends up asking systemd
    about a unit that was never installed (fixed once already in CV).
    """
    store = _store(tmp_path)
    _write_timer(store, "hermes-memory-os-cognitive-loop-sannai.timer")
    monkeypatch.setattr("plugins.memory.memory_os.cli._systemctl_user_units", lambda: set())

    findings = _orphan_systemd_unit_findings(store)

    assert findings[0]["details"]["unregistered_units"] == [
        "hermes-memory-os-cognitive-loop-sannai.timer"
    ]
