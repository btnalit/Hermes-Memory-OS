import json
from datetime import datetime, timedelta, timezone

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.audit import read_audit_entries
from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.runtime import MemoryOSRuntime
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.cli import build_status_report, _index_health_counts_findings, _index_health_summary
from plugins.memory.memory_os.cognitive_loop import CognitiveLoopRunner


def _event(seed, *, profile="main", source="telegram", kind="conversation_turn", summary=None, safe_ref=None, tags=None):
    return EventEnvelope.from_dict(
        {
            **build_event(seed=seed, profile=profile),
            "source": source,
            "kind": kind,
            "summary": summary or f"runtime policy event {seed}",
            "safe_ref": safe_ref or {},
            "tags": tags or [],
        }
    )


def test_runtime_heartbeat_processes_new_events_into_working_and_candidates(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="main")
    provider.sync_turn("runtime marker alpha", "stored alpha", session_id="session-1")
    provider.sync_turn("runtime marker beta", "stored beta", session_id="session-1")
    provider.shutdown()
    roots = MemoryOSRoots.from_hermes_home(tmp_path)
    store = MemoryOSStore(roots)

    report = MemoryOSRuntime(store).heartbeat()

    assert report["processed_event_count"] == 2
    assert report["working_item_count"] == 2
    assert report["candidate_count"] == 2
    assert report["crystallized_record_count"] == 0
    lingering = json.loads((tmp_path / "memory-os" / "working" / "lingering.json").read_text(encoding="utf-8"))
    assert len(lingering["items"]) == 2
    candidates = read_candidate_queue(roots)
    assert [candidate.candidate_id for candidate in candidates] == [
        f"cand_{event.id}" for event in store.read_events()
    ]
    context = build_prefetch("runtime marker", budget_chars=2000, store=store, index=None)
    assert "### Working Memory" in context
    assert "runtime marker alpha" in context
    status = build_status_report(store)
    assert status["counts"]["working_items"] == 2
    assert status["counts"]["crystallized_candidates"] == 2


def test_runtime_heartbeat_is_idempotent_for_processed_events(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="main")
    provider.sync_turn("runtime idempotent marker", "stored", session_id="session-1")
    provider.shutdown()
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))

    first = MemoryOSRuntime(store).heartbeat()
    second = MemoryOSRuntime(store).heartbeat()

    assert first["processed_event_count"] == 1
    assert second["processed_event_count"] == 0
    assert second["already_processed_event_count"] == 1
    assert len(read_candidate_queue(store.roots)) == 1


def test_runtime_heartbeat_noop_updates_state_without_runtime_audit_noise(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))
    store.initialize()

    report = MemoryOSRuntime(store).heartbeat()

    actions = [entry.get("action") for entry in read_audit_entries(store.roots.audit_path)]
    state = json.loads((tmp_path / "memory-os" / "runtime" / "heartbeat_state.json").read_text(encoding="utf-8"))
    assert report["processed_event_count"] == 0
    assert state["last_heartbeat_at"]
    assert state["processed_event_count"] == 0
    assert "runtime_heartbeat" not in actions


def test_runtime_heartbeat_decay_only_does_not_write_generic_working_audit(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))
    store.initialize()
    working = store.roots.working_root / "lingering.json"
    working.parent.mkdir(parents=True, exist_ok=True)
    working.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.working.v0",
                "updated_at": "2026-05-23T00:00:00+00:00",
                "items": [
                    {
                        "id": "wrk_decay_only",
                        "kind": "lingering",
                        "status": "active",
                        "created_at": "2026-05-23T00:00:00+00:00",
                        "updated_at": "2026-05-23T00:00:00+00:00",
                        "text": "Decay-only item",
                        "source_event_id": "evt_decay_only",
                        "tags": ["test"],
                        "weight": 0.9,
                    }
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    report = MemoryOSRuntime(store).heartbeat(now=datetime(2026, 5, 23, 1, tzinfo=timezone.utc))

    actions = [entry.get("action") for entry in read_audit_entries(store.roots.audit_path)]
    assert report["processed_event_count"] == 0
    assert report["decayed_documents"] == ["lingering"]
    assert "write_working_document" not in actions
    assert "runtime_heartbeat" not in actions


def test_runtime_heartbeat_keeps_expiry_audit_when_decay_expires_item(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))
    store.initialize()
    stale = datetime(2026, 5, 23, 0, tzinfo=timezone.utc)
    now = stale + timedelta(hours=80)
    working = store.roots.working_root / "lingering.json"
    working.parent.mkdir(parents=True, exist_ok=True)
    working.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.working.v0",
                "updated_at": stale.isoformat(),
                "items": [
                    {
                        "id": "wrk_expires",
                        "kind": "lingering",
                        "status": "active",
                        "created_at": stale.isoformat(),
                        "updated_at": stale.isoformat(),
                        "text": "Expiring item",
                        "source_event_id": "evt_expires",
                        "tags": ["test"],
                        "weight": 0.9,
                    }
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    report = MemoryOSRuntime(store).heartbeat(now=now)

    actions = [entry.get("action") for entry in read_audit_entries(store.roots.audit_path)]
    assert report["processed_event_count"] == 0
    assert report["decayed_documents"] == ["lingering"]
    assert "working_item_expired" in actions
    assert "write_working_document" not in actions
    assert "runtime_heartbeat" not in actions


def test_runtime_heartbeat_errors_are_audited_and_record_attempt(tmp_path, monkeypatch):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))
    store.initialize()

    def fail_read_events():
        raise RuntimeError("synthetic event read failure")

    monkeypatch.setattr(store, "read_events", fail_read_events)

    try:
        MemoryOSRuntime(store).heartbeat(now=datetime(2026, 5, 23, 1, tzinfo=timezone.utc))
    except RuntimeError:
        pass
    else:
        raise AssertionError("heartbeat should re-raise the original failure")

    actions = [entry.get("action") for entry in read_audit_entries(store.roots.audit_path)]
    entries = read_audit_entries(store.roots.audit_path)
    state = json.loads((tmp_path / "memory-os" / "runtime" / "heartbeat_state.json").read_text(encoding="utf-8"))
    assert "heartbeat_error_summary" in actions
    assert state["last_attempt_at"] == "2026-05-23T01:00:00+00:00"
    assert state.get("last_error")
    assert state["suppressed_error_count"] == 1
    assert state["recent_error_codes"] == ["runtime_heartbeat_error"]
    assert state["last_error_record"]["schema_version"] == "memory-os.error_record.v0"
    assert state["last_error_record"]["component"] == "runtime"
    assert state["last_error_record"]["operation"] == "heartbeat"
    assert entries[-1]["details"]["error_record"]["error_code"] == "runtime_heartbeat_error"


def test_runtime_heartbeat_attempt_state_errors_are_audited(tmp_path, monkeypatch):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))
    store.initialize()
    runtime = MemoryOSRuntime(store)

    def fail_attempt_state(_current):
        raise RuntimeError("synthetic attempt-state failure")

    monkeypatch.setattr(runtime, "_write_attempt_state", fail_attempt_state)

    try:
        runtime.heartbeat(now=datetime(2026, 5, 23, 1, tzinfo=timezone.utc))
    except RuntimeError:
        pass
    else:
        raise AssertionError("heartbeat should re-raise the attempt-state failure")

    entries = read_audit_entries(store.roots.audit_path)
    assert [entry.get("action") for entry in entries] == ["heartbeat_error_summary"]
    assert entries[0]["details"]["error_type"] == "RuntimeError"
    assert entries[0]["details"]["message"] == "synthetic attempt-state failure"


def test_runtime_heartbeat_indexes_new_events_without_duplicates(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="main")
    provider.sync_turn("runtime index marker alpha", "stored alpha", session_id="session-1")
    provider.sync_turn("runtime index marker beta", "stored beta", session_id="session-1")
    provider.shutdown()
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))

    first = MemoryOSRuntime(store).heartbeat()
    second = MemoryOSRuntime(store).heartbeat()

    assert first["index_counts"]["events"] == 2
    assert second["index_counts"]["events"] == 2
    assert MemoryOSIndex(store.roots).counts()["events"] == 2


def test_runtime_heartbeat_uses_approved_crystallized_record_count_not_markdown_blocks(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))
    store.initialize()
    active_frontmatter = {
        "schema_version": "memory-os.crystallized.v0",
        "id": "cry_active_001",
        "kind": "preference",
        "created_at": "2026-07-07T00:00:00+00:00",
        "approved_by": "owner",
        "approved_at": "2026-07-07T00:00:01+00:00",
        "source_event_ids": [],
        "tags": [],
        "sensitivity": "private",
    }
    revoked_frontmatter = {
        **active_frontmatter,
        "id": "cry_revoked_001",
        "canonical_state": "owner_revoked",
    }
    store.append_crystallized_record("owner_approved.md", active_frontmatter, "Active approved memory.")
    store.append_crystallized_record("owner_approved.md", revoked_frontmatter, "Revoked memory.")

    report = MemoryOSRuntime(store).heartbeat()

    assert report["crystallized_record_count"] == 1
    assert report["approved_crystallized_record_count"] == 1
    assert report["index_counts"]["crystallized_records"] == 1
    assert report["legacy_markdown_record_block_count"] == 2


def test_cognitive_loop_boundary_report_uses_approved_crystallized_count(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))
    store.initialize()
    active_frontmatter = {
        "schema_version": "memory-os.crystallized.v0",
        "id": "cry_active_002",
        "kind": "preference",
        "created_at": "2026-07-07T00:00:00+00:00",
        "approved_by": "owner",
        "approved_at": "2026-07-07T00:00:01+00:00",
        "source_event_ids": [],
        "tags": [],
        "sensitivity": "private",
    }
    store.append_crystallized_record("owner_approved.md", active_frontmatter, "Active approved memory.")
    MemoryOSIndex(store.roots).rebuild_from_store(store)

    report = CognitiveLoopRunner(store)._doctor_boundary_report({})

    assert report["crystallized_record_count"] == 1
    assert report["approved_crystallized_record_count"] == 1
    assert report["legacy_crystallized_file_count"] == 1


def test_runtime_heartbeat_indexes_candidates_separately_from_crystallized_records(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="main")
    provider.sync_turn("runtime candidate index marker", "stored", session_id="session-1")
    provider.shutdown()
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))

    report = MemoryOSRuntime(store).heartbeat()

    assert report["index_counts"]["crystallized_candidates"] == 1
    assert report["index_counts"]["crystallized_records"] == 0
    assert MemoryOSIndex(store.roots).counts()["crystallized_candidates"] == 1


def test_runtime_policy_prevents_mirror_metadata_from_creating_candidates(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    cron = _event(
        101,
        source="cron",
        kind="cron_job_run",
        summary="Cron mirror metadata should stay index only.",
        safe_ref={"source_module": "cron_mirror", "drive_policy": "index_only", "candidate_allowed": False},
        tags=["cron", "mirror"],
    )
    observed = _event(
        102,
        source="session_mirror",
        kind="session_observed",
        summary="Metadata-only session should not become lingering.",
        safe_ref={"source_module": "session_mirror", "drive_policy": "index_only", "candidate_allowed": False},
    )
    candidate_surface = _event(
        103,
        source="state_source_mirror",
        kind="candidate_surface_changed",
        summary="Candidate surface should not recursively create candidates.",
        safe_ref={"source_module": "state_source_mirror", "drive_policy": "candidate_surface", "candidate_allowed": False},
    )
    unknown = _event(104, source="mystery", kind="new_unknown_kind", summary="Unknown event must default index only.")
    for event in (cron, observed, candidate_surface, unknown):
        store.append_event(event)

    report = MemoryOSRuntime(store).heartbeat()

    assert report["processed_event_count"] == 4
    assert report["policy_skipped_event_count"] == 4
    assert report["candidate_count"] == 0
    assert read_candidate_queue(store.roots) == []
    assert not (store.roots.working_root / "lingering.json").exists()


def test_runtime_policy_allows_bounded_mirrored_conversation_working_without_candidate(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    mirrored = _event(
        110,
        source="session_mirror",
        kind="conversation_turn_mirrored",
        summary="Bounded mirrored conversation can influence working memory.",
        safe_ref={
            "source_module": "session_mirror",
            "drive_policy": "eligible",
            "body_policy": "bounded_summary",
            "candidate_allowed": False,
        },
    )
    store.append_event(mirrored)

    report = MemoryOSRuntime(store).heartbeat()

    assert report["processed_event_count"] == 1
    assert report["working_item_count"] == 1
    assert report["candidate_count"] == 0
    lingering = json.loads((store.roots.working_root / "lingering.json").read_text(encoding="utf-8"))
    assert lingering["items"][0]["source_event_id"] == mirrored.id
    assert lingering["items"][0]["weight"] <= 0.35
    assert read_candidate_queue(store.roots) == []


def test_runtime_policy_source_caps_prevent_cron_batch_from_dominating(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    for seed in range(120, 130):
        store.append_event(
            _event(
                seed,
                source="cron",
                kind="cron_job_run",
                safe_ref={"source_module": "cron_mirror", "drive_policy": "index_only", "candidate_allowed": False},
            )
        )
    foreground = _event(140, summary="Foreground should still be processed despite cron batch.")
    store.append_event(foreground)

    report = MemoryOSRuntime(store).heartbeat(max_events=20, max_events_per_source_class=2)

    assert report["processed_event_count"] == 3
    assert report["policy_skipped_event_count"] == 2
    assert report["cap_deferred_event_count"] == 8
    assert report["source_class_counts"]["cron"] == 2
    assert report["source_class_counts"]["foreground"] == 1
    assert report["candidate_count"] == 1


# ── _index_health_counts_findings O(1) tests ──────────────────────────

def test_counts_findings_healthy_when_all_match():
    counts = _index_health_counts_findings(
        {"events": 10, "working_items": 5, "crystallized_records": 3},
        {"events": 10, "working_items": 5, "crystallized_records": 3},
    )
    assert counts == [], f"Expected no findings for matching counts, got {counts}"


def test_counts_findings_error_when_index_has_more_events():
    counts = _index_health_counts_findings(
        {"events": 5, "working_items": 0, "crystallized_records": 0},
        {"events": 10, "working_items": 0, "crystallized_records": 0},
    )
    assert any(f["id"] == "index_count_mismatch" and f["severity"] == "error" for f in counts), (
        f"Expected index_count_mismatch error, got {counts}"
    )


def test_counts_findings_stale_when_store_ahead():
    counts = _index_health_counts_findings(
        {"events": 10, "working_items": 0, "crystallized_records": 0},
        {"events": 5, "working_items": 0, "crystallized_records": 0},
    )
    assert any(f["id"] == "index_stale" and f["severity"] == "warning" for f in counts), (
        f"Expected index_stale warning, got {counts}"
    )


def test_counts_findings_error_on_working_items_mismatch():
    counts = _index_health_counts_findings(
        {"events": 10, "working_items": 5, "crystallized_records": 3},
        {"events": 10, "working_items": 3, "crystallized_records": 3},
    )
    mismatches = [f for f in counts if f["id"] == "index_count_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0]["details"]["count_key"] == "working_items"


def test_counts_findings_error_on_crystallized_records_mismatch():
    counts = _index_health_counts_findings(
        {"events": 10, "working_items": 5, "crystallized_records": 3},
        {"events": 10, "working_items": 5, "crystallized_records": 7},
    )
    mismatches = [f for f in counts if f["id"] == "index_count_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0]["details"]["count_key"] == "crystallized_records"


# ── _index_health_summary O(1) fast path ──────────────────────────────

def test_index_health_summary_fast_path_does_not_read_events(tmp_path, monkeypatch):
    """deep=False must not call store.read_events() — O(1) guarantee."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path)
    store = MemoryOSStore(roots)
    store.initialize()

    # Build the index so it exists (empty)
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)

    read_events_called = []

    def _tracking_read_events(*args, **kwargs):
        read_events_called.append(True)
        return store._original_read_events(*args, **kwargs)

    store._original_read_events = store.read_events
    monkeypatch.setattr(store, "read_events", _tracking_read_events, raising=True)

    store_counts = {"events": 0, "working_items": 0, "crystallized_records": 0}
    index_counts = MemoryOSIndex(roots).counts()

    result = _index_health_summary(store, store_counts, index_counts)
    assert result["state"] == "healthy"
    assert len(read_events_called) == 0, (
        "deep=False path must not call store.read_events()"
    )


def test_index_health_summary_deep_path_reads_events(tmp_path, monkeypatch):
    """deep=True must call store.read_events() for full verification."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path)
    store = MemoryOSStore(roots)
    store.initialize()

    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)

    read_events_called = []

    def _tracking_read_events(*args, **kwargs):
        read_events_called.append(True)
        return store._original_read_events(*args, **kwargs)

    store._original_read_events = store.read_events
    monkeypatch.setattr(store, "read_events", _tracking_read_events, raising=True)

    store_counts = {"events": 0, "working_items": 0, "crystallized_records": 0}
    index_counts = MemoryOSIndex(roots).counts()

    result = _index_health_summary(store, store_counts, index_counts, deep=True)
    assert result["state"] == "healthy"
    assert len(read_events_called) == 1, (
        "deep=True path must call store.read_events()"
    )


def test_index_health_summary_missing_when_no_index(tmp_path):
    """When index file doesn't exist, return missing state without loading."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path)
    store = MemoryOSStore(roots)
    store.initialize()
    # Do NOT build the index

    result = _index_health_summary(store, {"events": 0}, {"events": 0})
    assert result["state"] == "missing"
    assert result["fts_tokenizer"] == ""


def test_build_status_report_uses_O1_index_health(tmp_path, monkeypatch):
    """build_status_report index_health path must not trigger full event scan.

    Counterfactual: before the deep=False fix, build_status_report would
    call _index_health_findings → store.read_events() on every invocation.
    """
    from plugins.memory.memory_os.event_stats import build_event_stats, write_event_stats

    roots = MemoryOSRoots.from_hermes_home(tmp_path)
    store = MemoryOSStore(roots)
    store.initialize()

    # Add a few events and build the index
    for i in range(5):
        store.append_event(_event(200 + i, summary=f"status event {i}"))
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)

    # Write fresh event stats so the O(1) path is taken
    events = sorted(store.read_events(), key=lambda e: e.ts)
    event_dicts = [e.to_dict() for e in events]
    stats = build_event_stats(event_dicts)
    stats.events_root = str(roots.events_root)
    write_event_stats(roots, stats)

    # Track read_events calls
    read_events_called = []

    def _tracking_read_events(*args, **kwargs):
        read_events_called.append(True)
        return store._original_read_events(*args, **kwargs)

    store._original_read_events = store.read_events
    monkeypatch.setattr(store, "read_events", _tracking_read_events, raising=True)

    status = build_status_report(store)
    assert status["counts"]["events"] == 5
    assert status["index_health"]["state"] in ("healthy", "stale")
    assert len(read_events_called) == 0, (
        f"build_status_report must not call store.read_events() on the O(1) path, "
        f"but it was called {len(read_events_called)} time(s)"
    )
