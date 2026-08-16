import json
import threading
from datetime import datetime, timezone

from plugins.memory.memory_os.execution_gate import (
    boundary_true_paths,
    complete_execution_gate_envelope,
    execution_gate_records_path,
    execution_gate_scope_hash,
    resolve_execution_gate_permit,
    rotate_execution_gate_records,
    start_execution_gate_envelope,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def test_boundary_true_paths_reports_nested_unknown_boundary_keys():
    paths = boundary_true_paths(
        {
            "actual_send": False,
            "nested": {"actual_relationship_write": True},
            "items": [{"hindsight_exported": False}, {"future_boundary": True}],
        }
    )

    assert paths == ["nested.actual_relationship_write", "items[1].future_boundary"]


def test_rotate_execution_gate_records_keeps_union_of_recent_and_latest(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    records_path = execution_gate_records_path(roots)
    records_path.parent.mkdir(parents=True)
    records = [
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": "old-drop",
            "created_at": "2026-05-01T00:00:00Z",
        },
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": "recent-keep",
            "created_at": "2026-05-25T00:00:00Z",
        },
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "completion",
            "execution_gate_envelope_id": "latest-keep",
            "created_at": "2026-05-02T00:00:00Z",
        },
    ]
    records_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    report = rotate_execution_gate_records(
        roots,
        max_records=1,
        max_age_days=14,
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    kept = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]

    assert report["status"] == "ok"
    assert report["before_count"] == 3
    assert report["after_count"] == 2
    assert report["rotated_count"] == 1
    assert [record["execution_gate_envelope_id"] for record in kept] == ["recent-keep", "latest-keep"]
    rotated_files = list((roots.memory_os_root / "system" / "execution_gate").glob("envelopes-*.jsonl"))
    assert len(rotated_files) == 1


def test_rotate_execution_gate_records_reports_lock_cleanup_failure(tmp_path, monkeypatch):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    records_path = execution_gate_records_path(roots)
    records_path.parent.mkdir(parents=True)
    records_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.execution_gate_envelope.v0",
                "stage": "permit",
                "execution_gate_envelope_id": "recent-keep",
                "created_at": "2026-05-25T00:00:00Z",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    original_unlink = type(records_path).unlink

    def fail_rotation_lock_unlink(self, *args, **kwargs):
        if self.name == "rotation.lock":
            raise OSError("synthetic lock cleanup failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(records_path), "unlink", fail_rotation_lock_unlink)

    report = rotate_execution_gate_records(
        roots,
        max_records=10,
        max_age_days=14,
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert report["status"] == "warning"
    assert report["lock_cleanup_error"] == "synthetic lock cleanup failure"


def test_completion_append_and_sidecar_are_idempotent_under_concurrency(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    permit = start_execution_gate_envelope(
        store,
        lane_id="idempotent-completion",
        trigger_surface="test",
        risk_class="bounded_reversible_queue",
        human_approval_required=False,
        why_no_human_approval="test",
        scope={"candidate_id": "cand-idempotent-completion"},
        boundary={},
    )
    errors: list[BaseException] = []

    def complete() -> None:
        try:
            complete_execution_gate_envelope(
                store,
                envelope_id=str(permit["execution_gate_envelope_id"]),
                lane_id="idempotent-completion",
                execution_status="completed",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=complete) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert errors == []
    records = [
        json.loads(line)
        for line in execution_gate_records_path(store.roots).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    completions = [
        row
        for row in records
        if row.get("stage") == "completion"
        and row.get("execution_gate_envelope_id") == permit["execution_gate_envelope_id"]
    ]
    assert len(completions) == 1
    resolution = resolve_execution_gate_permit(
        store.roots,
        envelope_id=str(permit["execution_gate_envelope_id"]),
        lane_id="idempotent-completion",
        risk_class="bounded_reversible_queue",
        require_unused=True,
    )
    assert resolution["completion_count"] == 1


def test_update_gate_index_uses_shared_sidecar_lock(tmp_path, monkeypatch):
    from contextlib import contextmanager

    import plugins.memory.memory_os.execution_gate as execution_gate

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    observed = []

    @contextmanager
    def observe_lock(path):
        observed.append(path)
        yield path

    monkeypatch.setattr(execution_gate, "locked_jsonl_file", observe_lock, raising=False)
    execution_gate._update_gate_index(
        roots,
        "xgate-lock-test",
        "permit",
        {
            "permit_decision": "allowed",
            "lane_id": "test",
            "risk_class": "test",
            "scope_hash": "hash",
            "created_at": "2026-08-01T00:00:00Z",
            "expires_at": "2026-08-01T01:00:00Z",
        },
    )

    assert observed == [execution_gate._gate_index_path(roots)]


def test_resolve_require_unused_rejects_canonical_completion_missing_from_sidecar(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    permit = start_execution_gate_envelope(
        store,
        lane_id="test-lane",
        trigger_surface="test",
        risk_class="bounded_reversible_queue",
        human_approval_required=False,
        why_no_human_approval="test",
        scope={"candidate_id": "cand-stale-index"},
        boundary={},
    )
    completion = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "completion",
        "execution_gate_envelope_id": permit["execution_gate_envelope_id"],
        "created_at": "2026-08-01T00:00:00Z",
        "lane_id": "test-lane",
        "execution_status": "completed",
    }
    with execution_gate_records_path(store.roots).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(completion) + "\n")

    result = resolve_execution_gate_permit(
        store.roots,
        envelope_id=permit["execution_gate_envelope_id"],
        lane_id="test-lane",
        risk_class="bounded_reversible_queue",
        require_unused=True,
    )

    assert result["status"] == "invalid"
    assert result["reason"] == "execution_gate_permit_already_completed"
    assert result["completion_count"] == 1


def test_resolve_execution_gate_permit_validates_lane_risk_and_boundary(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    permit = start_execution_gate_envelope(
        store,
        lane_id="memory_projection",
        trigger_surface="cognitive_loop",
        risk_class="governance_projection",
        human_approval_required=False,
        why_no_human_approval="report-only governance projection",
        scope={"limit": 10},
        boundary={"actual_send": False, "actual_execute": False},
    )
    envelope_id = permit["execution_gate_envelope_id"]

    valid = resolve_execution_gate_permit(
        store.roots,
        envelope_id=envelope_id,
        lane_id="memory_projection",
        risk_class="governance_projection",
    )
    wrong_risk = resolve_execution_gate_permit(
        store.roots,
        envelope_id=envelope_id,
        lane_id="memory_projection",
        risk_class="bounded_append_only_data_ingress",
    )
    manual = resolve_execution_gate_permit(store.roots, envelope_id="manual_cli_explicit")

    assert valid["status"] == "valid"
    assert valid["permit_decision"] == "allowed"
    assert wrong_risk["status"] == "invalid"
    assert wrong_risk["reason"] == "execution_gate_risk_class_mismatch"
    assert manual["status"] == "invalid"
    assert manual["reason"] == "execution_gate_envelope_id_invalid"


def test_resolve_execution_gate_permit_rejects_boundary_true_and_expired(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    records_path = execution_gate_records_path(roots)
    records_path.parent.mkdir(parents=True)
    records = [
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": "xgate_boundary_true",
            "created_at": "2026-06-01T00:00:00Z",
            "lane_id": "memory_projection",
            "risk_class": "governance_projection",
            "permit_decision": "allowed",
            "boundary_true": False,
            "boundary": {"future_boundary": True},
        },
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": "xgate_expired",
            "created_at": "2026-06-01T00:00:00Z",
            "expires_at": "2026-06-01T00:10:00Z",
            "lane_id": "memory_projection",
            "risk_class": "governance_projection",
            "permit_decision": "allowed",
            "boundary_true": False,
            "boundary": {"actual_send": False},
        },
    ]
    records_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    boundary = resolve_execution_gate_permit(
        roots,
        envelope_id="xgate_boundary_true",
        lane_id="memory_projection",
        risk_class="governance_projection",
    )
    expired = resolve_execution_gate_permit(
        roots,
        envelope_id="xgate_expired",
        lane_id="memory_projection",
        risk_class="governance_projection",
        now=datetime(2026, 6, 1, 0, 20, tzinfo=timezone.utc),
    )

    assert boundary["status"] == "invalid"
    assert boundary["reason"] == "execution_gate_boundary_true"
    assert expired["status"] == "invalid"
    assert expired["reason"] == "execution_gate_permit_expired"


def test_start_execution_gate_envelope_records_ttl_and_scope_hash(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    scope = {"max_sessions_per_run": 1, "platform_allowlist": ["telegram"]}

    permit = start_execution_gate_envelope(
        store,
        lane_id="session_mirror_auto_apply",
        trigger_surface="runtime_heartbeat",
        risk_class="bounded_append_only_data_ingress",
        human_approval_required=False,
        why_no_human_approval="owner-approved graduated lane",
        scope=scope,
        boundary={"actual_send": False},
    )

    assert permit["expires_at"]
    assert permit["scope_hash"] == execution_gate_scope_hash(scope)


def test_resolve_execution_gate_permit_requires_fresh_unused_and_scope(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    records_path = execution_gate_records_path(roots)
    records_path.parent.mkdir(parents=True)
    good_scope = {"max_sessions_per_run": 1, "platform_allowlist": ["telegram"]}
    other_scope = {"max_sessions_per_run": 1, "platform_allowlist": ["discord"]}
    records = [
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": "xgate_no_expiry",
            "created_at": "2026-06-01T00:00:00Z",
            "lane_id": "session_mirror_auto_apply",
            "risk_class": "bounded_append_only_data_ingress",
            "permit_decision": "allowed",
            "boundary_true": False,
            "boundary": {"actual_send": False},
            "scope": good_scope,
            "scope_hash": execution_gate_scope_hash(good_scope),
        },
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": "xgate_scope",
            "created_at": "2026-06-01T00:00:00Z",
            "expires_at": "2026-06-01T00:10:00Z",
            "lane_id": "session_mirror_auto_apply",
            "risk_class": "bounded_append_only_data_ingress",
            "permit_decision": "allowed",
            "boundary_true": False,
            "boundary": {"actual_send": False},
            "scope": other_scope,
            "scope_hash": execution_gate_scope_hash(other_scope),
        },
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": "xgate_used",
            "created_at": "2026-06-01T00:00:00Z",
            "expires_at": "2026-06-01T00:10:00Z",
            "lane_id": "session_mirror_auto_apply",
            "risk_class": "bounded_append_only_data_ingress",
            "permit_decision": "allowed",
            "boundary_true": False,
            "boundary": {"actual_send": False},
            "scope": good_scope,
            "scope_hash": execution_gate_scope_hash(good_scope),
        },
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "completion",
            "execution_gate_envelope_id": "xgate_used",
            "created_at": "2026-06-01T00:01:00Z",
            "lane_id": "session_mirror_auto_apply",
            "execution_status": "ok",
        },
    ]
    records_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    no_expiry = resolve_execution_gate_permit(
        roots,
        envelope_id="xgate_no_expiry",
        lane_id="session_mirror_auto_apply",
        risk_class="bounded_append_only_data_ingress",
        require_fresh=True,
        expected_scope=good_scope,
        now=datetime(2026, 6, 1, 0, 1, tzinfo=timezone.utc),
    )
    scope_mismatch = resolve_execution_gate_permit(
        roots,
        envelope_id="xgate_scope",
        lane_id="session_mirror_auto_apply",
        risk_class="bounded_append_only_data_ingress",
        require_fresh=True,
        expected_scope=good_scope,
        now=datetime(2026, 6, 1, 0, 1, tzinfo=timezone.utc),
    )
    reused = resolve_execution_gate_permit(
        roots,
        envelope_id="xgate_used",
        lane_id="session_mirror_auto_apply",
        risk_class="bounded_append_only_data_ingress",
        require_fresh=True,
        require_unused=True,
        expected_scope=good_scope,
        now=datetime(2026, 6, 1, 0, 1, tzinfo=timezone.utc),
    )

    assert no_expiry["status"] == "invalid"
    assert no_expiry["reason"] == "execution_gate_permit_expiry_missing"
    assert scope_mismatch["status"] == "invalid"
    assert scope_mismatch["reason"] == "execution_gate_scope_mismatch"
    assert reused["status"] == "invalid"
    assert reused["reason"] == "execution_gate_permit_already_completed"


# ── B.1: Cliff elimination (spec B1a) ─────────────────────────────────────


def test_old_permit_beyond_2000_window_still_resolvable(tmp_path):
    """B.1: Permits older than the most recent 2000 records are still found.

    Old code (limit=2000): only scans records[-2000:] → old permits unresolvable.
    New code (limit=0): scans ALL records → old permits found.
    """
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    now = datetime.now(timezone.utc)
    expires_at = now.replace(year=now.year + 1).isoformat().replace("+00:00", "Z")

    # Write an old permit (will be outside the 2000 window after we add padding)
    old_envelope_id = "xgate_old_permit_test"
    old_permit = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "permit",
        "execution_gate_envelope_id": old_envelope_id,
        "created_at": "2020-01-01T00:00:00Z",
        "expires_at": expires_at,
        "profile": "memoryos-test",
        "lane_id": "test_lane",
        "trigger_surface": "test",
        "risk_class": "bounded_reversible_queue",
        "human_approval_required": False,
        "why_no_human_approval": "test",
        "scope": {},
        "boundary": {},
        "boundary_true": False,
        "precheck": {},
        "permit_decision": "allowed",
        "permit_reason": "test",
    }

    records_path = execution_gate_records_path(roots)
    records_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the old permit
    with records_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(old_permit, sort_keys=True) + "\n")

    # Pad with 2001 dummy records to push old permit outside a 2000-record window
    for i in range(2001):
        padding = {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "completion",
            "execution_gate_envelope_id": f"xgate_padding_{i:05d}",
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "profile": "memoryos-test",
            "completion_status": "completed",
        }
        with records_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(padding, sort_keys=True) + "\n")

    # Resolve the old permit — should succeed even though it's beyond 2000
    result = resolve_execution_gate_permit(
        roots,
        envelope_id=old_envelope_id,
        lane_id="test_lane",
        risk_class="bounded_reversible_queue",
    )
    assert result["status"] == "valid", (
        f"B.1 FAIL: old permit should be valid; got status={result['status']}, "
        f"reason={result.get('reason')}"
    )


# ── B.2-B.4: Gate index sidecar (spec B1b) ────────────────────────────────


class TestGateIndex:
    """B.2-B.4: Sidecar index for O(1) permit resolution."""

    def test_index_hit_returns_correct_permit(self, tmp_path):
        """B.2: Index hit -> O(1) return of correct permit state."""
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        # Start an envelope -- should populate index
        permit = start_execution_gate_envelope(
            store,
            lane_id="test_index_lane",
            trigger_surface="test",
            risk_class="bounded_reversible_queue",
            human_approval_required=False,
            why_no_human_approval="test",
            scope={"key": "value"},
            boundary={},
        )
        envelope_id = permit["execution_gate_envelope_id"]

        # Read the index directly -- should contain the envelope
        from plugins.memory.memory_os.execution_gate import _read_gate_index

        idx = _read_gate_index(roots)
        assert envelope_id in idx, (
            f"B.2 FAIL: index should contain {envelope_id} after start; "
            f"got keys={list(idx.keys())}"
        )
        entry = idx[envelope_id]
        assert entry["permit_decision"] == "allowed"
        assert entry["lane_id"] == "test_index_lane"

        # Resolve via index path
        result = resolve_execution_gate_permit(
            roots,
            envelope_id=envelope_id,
            lane_id="test_index_lane",
            risk_class="bounded_reversible_queue",
        )
        assert result["status"] == "valid", (
            f"B.2 FAIL: permit should be valid via index; "
            f"got {result['status']}: {result.get('reason')}"
        )

    def test_index_miss_falls_back_to_full_scan(self, tmp_path):
        """B.3: Index miss -> full scan fallback -> rebuild index.

        If the index is deleted/corrupt, resolve still works by scanning
        the full JSONL, then rebuilds the missing index entries.
        """
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        # Start an envelope normally
        permit = start_execution_gate_envelope(
            store,
            lane_id="test_fallback_lane",
            trigger_surface="test",
            risk_class="bounded_reversible_queue",
            human_approval_required=False,
            why_no_human_approval="test",
            scope={},
            boundary={},
        )
        envelope_id = permit["execution_gate_envelope_id"]

        # Corrupt the index -- delete it
        from plugins.memory.memory_os.execution_gate import _gate_index_path, _read_gate_index

        index_path = _gate_index_path(roots)
        index_path.unlink()

        # Index should be empty now
        idx = _read_gate_index(roots)
        assert envelope_id not in idx, "Index should be empty after deletion"

        # Resolve should still work (full-scan fallback)
        result = resolve_execution_gate_permit(
            roots,
            envelope_id=envelope_id,
            lane_id="test_fallback_lane",
            risk_class="bounded_reversible_queue",
        )
        assert result["status"] == "valid", (
            f"B.3 FAIL: permit should be valid via full-scan fallback; "
            f"got {result['status']}: {result.get('reason')}"
        )

        # Index should have been rebuilt
        idx_rebuilt = _read_gate_index(roots)
        assert envelope_id in idx_rebuilt, (
            "B.3 FAIL: index should be rebuilt after full-scan fallback"
        )

    def test_completion_updates_index(self, tmp_path):
        """B.4: append completion -> index updated with completion status."""
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        permit = start_execution_gate_envelope(
            store,
            lane_id="test_completion_lane",
            trigger_surface="test",
            risk_class="bounded_reversible_queue",
            human_approval_required=False,
            why_no_human_approval="test",
            scope={},
            boundary={},
        )
        envelope_id = permit["execution_gate_envelope_id"]

        # Complete the envelope
        from plugins.memory.memory_os.execution_gate import complete_execution_gate_envelope

        complete_execution_gate_envelope(
            store,
            envelope_id=envelope_id,
            lane_id="test_completion_lane",
            execution_status="completed",
            result_summary={"summary": "test completion"},
        )

        # Index should reflect completion
        from plugins.memory.memory_os.execution_gate import _read_gate_index

        idx = _read_gate_index(roots)
        assert envelope_id in idx
        assert idx[envelope_id].get("completion_status") == "completed", (
            f"B.4 FAIL: index should show completion_status='completed'; "
            f"got {idx[envelope_id]}"
        )

        # Resolve with require_unused should now fail
        result = resolve_execution_gate_permit(
            roots,
            envelope_id=envelope_id,
            lane_id="test_completion_lane",
            risk_class="bounded_reversible_queue",
            require_unused=True,
        )
        assert result["status"] == "invalid", (
            f"B.4: permit should be invalid when require_unused and completed; "
            f"got {result['status']}"
        )
        assert "already_completed" in result.get("reason", ""), (
            f"B.4: reason should indicate already completed; got {result.get('reason')}"
        )

    # ── Task F2: C2-C7 fixes ─────────────────────────────────────────────

    def test_completion_count_is_integer_not_boolean(self, tmp_path):
        """C2: completion_count in resolution is actual count, not 0/1."""
        from plugins.memory.memory_os.execution_gate import (
            _update_gate_index, _read_gate_index,
        )
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()
        eid = "xgate_test_c2_count"
        # Write first completion
        _update_gate_index(roots, eid, "completion", {
            "execution_status": "completed", "created_at": "2025-01-01T00:00:00Z"
        })
        # Verify index stores int
        index = _read_gate_index(roots)
        assert index[eid]["completion_count"] == 1, \
            f"Expected 1, got {index[eid].get('completion_count')}"
        # Write second completion
        _update_gate_index(roots, eid, "completion", {
            "execution_status": "completed", "created_at": "2025-01-02T00:00:00Z"
        })
        index = _read_gate_index(roots)
        assert index[eid]["completion_count"] == 2, \
            f"Expected 2, got {index[eid].get('completion_count')}"

    def test_permit_resolution_expires_at_status_respects_require_fresh(self):
        """C3: expires_at_status uses require_fresh when passed."""
        from plugins.memory.memory_os.execution_gate import _permit_resolution
        result = _permit_resolution(
            status="invalid",
            reason="test",
            envelope_id="xgate_c3",
            lane_id="test",
            risk_class="standard",
            permit={"expires_at": ""},
            require_fresh=True,
        )
        assert result["expires_at_status"] == "expiry_missing", \
            f"Expected 'expiry_missing' with require_fresh=True, got {result['expires_at_status']}"

    def test_permit_resolution_expires_at_status_relaxed_by_default(self):
        """C3: expires_at_status uses relaxed mode when require_fresh not passed."""
        from plugins.memory.memory_os.execution_gate import _permit_resolution
        result = _permit_resolution(
            status="valid",
            reason="",
            envelope_id="xgate_c3b",
            lane_id="test",
            risk_class="standard",
            permit={},
        )
        assert result["expires_at_status"] == "valid", \
            f"Expected 'valid' with relaxed default, got {result['expires_at_status']}"

    def test_permit_resolution_reports_index_expiry_fields(self):
        """C3+B1b: fast-path index entries render permit_* timestamps as normal resolution fields."""
        from plugins.memory.memory_os.execution_gate import _permit_resolution
        result = _permit_resolution(
            status="valid",
            reason="",
            envelope_id="xgate_c3_index",
            lane_id="test",
            risk_class="standard",
            permit={
                "permit_created_at": "2030-01-01T00:00:00Z",
                "permit_expires_at": "2030-01-01T00:15:00Z",
                "permit_decision": "allowed",
            },
        )
        assert result["permit_created_at"] == "2030-01-01T00:00:00Z"
        assert result["expires_at"] == "2030-01-01T00:15:00Z"
        assert result["expires_at_status"] == "valid"

    def test_validate_permit_fields_shared_function_exists(self):
        """C6: shared _validate_permit_fields function is importable and works."""
        from plugins.memory.memory_os.execution_gate import _validate_permit_fields
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        # Empty dict should fail lane check
        result = _validate_permit_fields(
            d={},
            target="xgate_c6",
            lane_id="test-lane",
            risk_class="",
            require_fresh=False,
            require_unused=False,
            expected_scope=None,
            expected_scope_hash="",
            now=now,
            completion_count=0,
        )
        assert result is not None  # Should return a failure dict
        assert result["reason"] == "execution_gate_lane_mismatch"

    def test_validate_permit_fields_no_side_effects(self):
        """C5+C6: _validate_permit_fields is pure — no index rebuild side effects."""
        from plugins.memory.memory_os.execution_gate import _validate_permit_fields
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        d = {
            "lane_id": "wrong",
            "risk_class": "standard",
            "permit_decision": "allowed",
        }
        # Should return failure dict WITHOUT triggering any file I/O
        result = _validate_permit_fields(
            d=d, target="xgate_c5", lane_id="right-lane", risk_class="standard",
            require_fresh=False, require_unused=False,
            expected_scope=None, expected_scope_hash="",
            now=now, completion_count=0,
        )
        assert result is not None
        assert result["reason"] == "execution_gate_lane_mismatch"

    # ── Perf fix: success-path index rebuild removed ──────────────────

    def test_require_unused_success_does_not_rewrite_index(self, tmp_path, monkeypatch):
        """Perf fix: N successful require_unused=True resolutions against an
        already-fresh sidecar entry must not scale index rewrites with N.

        Counterfactual: before this fix, resolve_execution_gate_permit()
        called _rebuild_gate_index_from_records() unconditionally on every
        successful full-scan resolution. require_unused=True always takes
        that full-scan path (see the fast-path comment), so N sequential
        append_governed_jsonl() calls under one envelope rewrote
        execution_gate_index.json N times -- the verified perf defect this
        fix removes.
        """
        import plugins.memory.memory_os.execution_gate as execution_gate

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        permit = start_execution_gate_envelope(
            store,
            lane_id="cost-test-lane",
            trigger_surface="test",
            risk_class="bounded_reversible_queue",
            human_approval_required=False,
            why_no_human_approval="test",
            scope={"key": "value"},
            boundary={},
        )
        envelope_id = permit["execution_gate_envelope_id"]

        rebuild_calls: list[int] = []
        real_rebuild = execution_gate._rebuild_gate_index_from_records

        def counting_rebuild(roots_arg, records_arg):
            rebuild_calls.append(1)
            return real_rebuild(roots_arg, records_arg)

        monkeypatch.setattr(execution_gate, "_rebuild_gate_index_from_records", counting_rebuild)

        for _ in range(50):
            result = execution_gate.resolve_execution_gate_permit(
                roots,
                envelope_id=envelope_id,
                lane_id="cost-test-lane",
                risk_class="bounded_reversible_queue",
                require_fresh=True,
                require_unused=True,
                expected_scope_hash=execution_gate_scope_hash({"key": "value"}),
            )
            assert result["status"] == "valid", result

        assert len(rebuild_calls) == 0, (
            f"expected 0 index rebuilds across 50 require_unused=True resolutions "
            f"against an already-fresh sidecar entry (non-scaling); got {len(rebuild_calls)}"
        )

    def test_not_found_and_conflict_resolutions_still_rebuild_index(self, tmp_path, monkeypatch):
        """Regression guard: removing the success-path rebuild must not touch
        the two genuine-staleness rebuild paths (not found / conflict).
        """
        import plugins.memory.memory_os.execution_gate as execution_gate

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        rebuild_calls: list[int] = []
        real_rebuild = execution_gate._rebuild_gate_index_from_records

        def counting_rebuild(roots_arg, records_arg):
            rebuild_calls.append(1)
            return real_rebuild(roots_arg, records_arg)

        monkeypatch.setattr(execution_gate, "_rebuild_gate_index_from_records", counting_rebuild)

        # not found: no permit record exists for this envelope id at all.
        result = execution_gate.resolve_execution_gate_permit(
            roots,
            envelope_id="xgate_does_not_exist",
            lane_id="whatever",
            risk_class="whatever",
        )
        assert result["status"] == "invalid"
        assert result["reason"] == "execution_gate_permit_not_found"
        assert len(rebuild_calls) == 1, "not-found resolution must still rebuild the index"

        # conflict: two permit records for the same envelope id, written
        # straight to the journal so the sidecar has no entry for it either.
        conflict_id = "xgate_conflict_test"
        dup_permit = {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": conflict_id,
            "created_at": "2026-08-01T00:00:00Z",
            "expires_at": "2030-08-01T01:00:00Z",
            "lane_id": "dup-lane",
            "risk_class": "bounded_reversible_queue",
            "permit_decision": "allowed",
        }
        with execution_gate_records_path(roots).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dup_permit) + "\n")
            handle.write(json.dumps(dup_permit) + "\n")

        result = execution_gate.resolve_execution_gate_permit(
            roots,
            envelope_id=conflict_id,
            lane_id="dup-lane",
            risk_class="bounded_reversible_queue",
        )
        assert result["status"] == "invalid"
        assert result["reason"] == "execution_gate_permit_conflict"
        assert len(rebuild_calls) == 2, "conflict resolution must still rebuild the index"

    def test_index_miss_success_still_rebuilds_index(self, tmp_path):
        """Regression guard for test_index_miss_falls_back_to_full_scan's
        contract: a success resolved via full scan because the sidecar
        entry was genuinely missing (not because of a require_unused=True
        bypass) must still populate the index, preserving self-healing.
        """
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        permit = start_execution_gate_envelope(
            store,
            lane_id="self-heal-lane",
            trigger_surface="test",
            risk_class="bounded_reversible_queue",
            human_approval_required=False,
            why_no_human_approval="test",
            scope={},
            boundary={},
        )
        envelope_id = permit["execution_gate_envelope_id"]

        from plugins.memory.memory_os.execution_gate import _gate_index_path, _read_gate_index

        _gate_index_path(roots).unlink()
        assert envelope_id not in _read_gate_index(roots)

        result = resolve_execution_gate_permit(
            roots,
            envelope_id=envelope_id,
            lane_id="self-heal-lane",
            risk_class="bounded_reversible_queue",
        )
        assert result["status"] == "valid"
        assert envelope_id in _read_gate_index(roots), (
            "index should self-heal (be repopulated) after a success resolved "
            "via full scan due to a genuine index miss"
        )

    # ── Invariant: require_unused=True must never validate a used permit ──

    def test_require_unused_invariant_never_validates_completed_permit(self, tmp_path):
        """Invariant (must hold under both ways a completion can reach the
        journal): a permit that has already been completed must NEVER
        validate when require_unused=True.

        Case A: completion recorded through the real API
        (complete_execution_gate_envelope) -- the sidecar index DOES
        correctly show completion_count > 0.

        Case B: completion appended straight to the canonical journal,
        bypassing the sidecar update entirely -- simulates the crash
        window documented in resolve_execution_gate_permit, where the
        sidecar entry exists but is stale. This is the same scenario as
        test_resolve_require_unused_rejects_canonical_completion_missing_
        from_sidecar; it is repeated here, paired with Case A, as the
        single invariant test both cases must jointly satisfy.

        Both cases exercise the same code route today (the full-journal
        fallback, since require_unused=True unconditionally disables the
        O(1) index fast path) -- but are asserted independently so a
        future change to that gate cannot silently reintroduce the hole
        for either case.
        """
        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
        store.initialize()

        # Case A: sidecar index correctly reflects the completion.
        permit_a = start_execution_gate_envelope(
            store,
            lane_id="invariant-lane-a",
            trigger_surface="test",
            risk_class="bounded_reversible_queue",
            human_approval_required=False,
            why_no_human_approval="test",
            scope={},
            boundary={},
        )
        complete_execution_gate_envelope(
            store,
            envelope_id=permit_a["execution_gate_envelope_id"],
            lane_id="invariant-lane-a",
            execution_status="completed",
        )
        result_a = resolve_execution_gate_permit(
            store.roots,
            envelope_id=permit_a["execution_gate_envelope_id"],
            lane_id="invariant-lane-a",
            risk_class="bounded_reversible_queue",
            require_unused=True,
        )
        assert result_a["status"] == "invalid"
        assert result_a["reason"] == "execution_gate_permit_already_completed"

        # Case B: sidecar index does NOT know about the completion.
        permit_b = start_execution_gate_envelope(
            store,
            lane_id="invariant-lane-b",
            trigger_surface="test",
            risk_class="bounded_reversible_queue",
            human_approval_required=False,
            why_no_human_approval="test",
            scope={},
            boundary={},
        )
        bypass_completion = {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "completion",
            "execution_gate_envelope_id": permit_b["execution_gate_envelope_id"],
            "created_at": "2026-08-01T00:00:00Z",
            "lane_id": "invariant-lane-b",
            "execution_status": "completed",
        }
        with execution_gate_records_path(store.roots).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(bypass_completion) + "\n")

        from plugins.memory.memory_os.execution_gate import _read_gate_index

        idx = _read_gate_index(store.roots)
        assert idx[permit_b["execution_gate_envelope_id"]].get("completion_count", 0) == 0, (
            "test setup invariant: sidecar must NOT know about the bypass completion"
        )

        result_b = resolve_execution_gate_permit(
            store.roots,
            envelope_id=permit_b["execution_gate_envelope_id"],
            lane_id="invariant-lane-b",
            risk_class="bounded_reversible_queue",
            require_unused=True,
        )
        assert result_b["status"] == "invalid"
        assert result_b["reason"] == "execution_gate_permit_already_completed"


# ── resolve_trigger_class() tests ────────────────────────────────────────────


def test_resolve_trigger_class_returns_natural_cron_when_env_var_set(monkeypatch):
    """resolve_trigger_class() returns "natural_cron" when MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID is set to non-empty value."""
    from plugins.memory.memory_os.execution_gate import resolve_trigger_class

    monkeypatch.setenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", "xgate_12345")
    assert resolve_trigger_class() == "natural_cron"


def test_resolve_trigger_class_returns_manual_when_env_var_unset(monkeypatch):
    """resolve_trigger_class() returns "manual" when MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID is unset."""
    from plugins.memory.memory_os.execution_gate import resolve_trigger_class

    monkeypatch.delenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", raising=False)
    assert resolve_trigger_class() == "manual"


def test_resolve_trigger_class_returns_manual_when_env_var_empty_string(monkeypatch):
    """resolve_trigger_class() returns "manual" when MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID is set to empty string (falsy edge case)."""
    from plugins.memory.memory_os.execution_gate import resolve_trigger_class

    monkeypatch.setenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", "")
    assert resolve_trigger_class() == "manual"


def test_resolve_trigger_class_shared_between_modules():
    """Both v3_seed_evidence and exposure_rollup reference the same resolve_trigger_class from execution_gate."""
    from plugins.memory.memory_os import execution_gate, v3_seed_evidence, exposure_rollup

    # Assert that both modules have resolve_trigger_class and it's the same function object
    assert hasattr(v3_seed_evidence, "resolve_trigger_class"), (
        "v3_seed_evidence should import resolve_trigger_class"
    )
    assert hasattr(exposure_rollup, "resolve_trigger_class"), (
        "exposure_rollup should import resolve_trigger_class"
    )
    assert v3_seed_evidence.resolve_trigger_class is execution_gate.resolve_trigger_class, (
        "v3_seed_evidence.resolve_trigger_class should be the same object as execution_gate.resolve_trigger_class"
    )
    assert exposure_rollup.resolve_trigger_class is execution_gate.resolve_trigger_class, (
        "exposure_rollup.resolve_trigger_class should be the same object as execution_gate.resolve_trigger_class"
    )
