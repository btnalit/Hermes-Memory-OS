import json
from pathlib import Path

from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.context.digest_consolidation import (
    DigestConsolidationModule,
    digest_consolidation_manifest,
)
from plugins.modules.governance.proposal_queue import ProposalQueueModule
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path: Path, *, profile: str = "main") -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _event(
    *,
    seed: int,
    profile: str = "main",
    ts: str,
    kind: str = "conversation_turn",
    source_class: str = "foreground",
    summary: str = "",
    safe_ref: dict | None = None,
) -> EventEnvelope:
    data = build_event(seed=seed, profile=profile)
    merged_safe_ref = {"source_class": source_class}
    merged_safe_ref.update(safe_ref or {})
    data.update(
        {
            "ts": ts,
            "kind": kind,
            "source": source_class,
            "summary": summary or f"{source_class} {kind} {seed}",
            "safe_ref": merged_safe_ref,
        }
    )
    return EventEnvelope.from_dict(data)


def test_digest_consolidation_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler", "proposal_queue"),
    )

    status = lifecycle.install(digest_consolidation_manifest())
    enabled = lifecycle.enable("digest_consolidation")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("digest_consolidation").status == "ok"


def test_daily_digest_uses_profile_timezone_and_records_late_arrivals(tmp_path):
    store = _store(tmp_path)
    module = DigestConsolidationModule(tmp_path, profile="main")
    module.write_config({"time_zone": "Asia/Shanghai"})
    store.append_event(
        _event(
            seed=1,
            ts="2026-05-20T16:30:00+00:00",
            summary="Local May 21 event.",
        )
    )
    store.append_event(
        _event(
            seed=2,
            ts="2026-05-21T16:30:00+00:00",
            summary="Local May 22 event.",
        )
    )
    store.append_event(
        _event(
            seed=3,
            ts="2026-05-19T12:00:00+00:00",
            source_class="foreground",
            summary="Late event from a prior finalized day.",
            safe_ref={"arrived_at": "2026-05-21T02:00:00+08:00"},
        )
    )

    result = module.build_daily_digest(store=store, target_date="2026-05-21", dry_run=True)

    artifact = result["would_write"]
    assert artifact["date"] == "2026-05-21"
    assert artifact["time_zone"] == "Asia/Shanghai"
    assert "event:" + store.read_events()[0].id in artifact["selected_refs"]
    assert "Local May 22 event." not in json.dumps(artifact, ensure_ascii=False)
    late_groups = [group for group in artifact["groups"] if group["source_class"] == "late_arrival"]
    assert late_groups
    assert late_groups[0]["late_arrival_count"] == 1


def test_daily_digest_apply_writes_atomic_artifact_matching_dry_run(tmp_path):
    store = _store(tmp_path)
    store.append_event(
        _event(
            seed=10,
            ts="2026-05-21T01:00:00+00:00",
            summary="Owner asked about digest apply.",
        )
    )
    module = DigestConsolidationModule(tmp_path, profile="main")

    dry_run = module.build_daily_digest(store=store, target_date="2026-05-21", dry_run=True)
    applied = module.build_daily_digest(store=store, target_date="2026-05-21", dry_run=False)

    artifact_path = Path(applied["artifact_ref"])
    assert artifact_path.exists()
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact == dry_run["would_write"]
    assert applied["applied"] is True
    assert list(artifact_path.parent.glob("*.tmp")) == []


def test_candidate_dedup_key_is_order_independent_and_semantic_subject_scoped(tmp_path):
    module = DigestConsolidationModule(tmp_path, profile="main")

    first = module.candidate_dedup_key(
        semantic_subject="memory_os_runtime_diagnostics",
        candidate_kind="weekly_consolidation",
        source_refs=["event:evt_3", "event:evt_1", "event:evt_1", "score:score_2"],
    )
    second = module.candidate_dedup_key(
        semantic_subject="memory_os_runtime_diagnostics",
        candidate_kind="weekly_consolidation",
        source_refs=["score:score_2", "event:evt_1", "event:evt_3"],
    )
    different_subject = module.candidate_dedup_key(
        semantic_subject="telegram_session_continuity",
        candidate_kind="weekly_consolidation",
        source_refs=["score:score_2", "event:evt_1", "event:evt_3"],
    )

    assert first == second
    assert first != different_subject
    assert first["canonical_source_refs"] == ["event:evt_1", "event:evt_3", "score:score_2"]
    assert " " not in first["dedup_key"]


def test_weekly_consolidation_reselects_daily_dropped_events(tmp_path):
    store = _store(tmp_path)
    module = DigestConsolidationModule(tmp_path, profile="main")
    module.write_config({"max_events_per_group": 1})
    for seed in range(20, 23):
        store.append_event(
            _event(
                seed=seed,
                ts=f"2026-05-2{seed - 20}T01:00:00+00:00",
                summary=f"Weekly candidate source {seed}.",
                safe_ref={"semantic_subject": "memory_os_runtime_diagnostics"},
            )
        )
    store.append_event(
        _event(
            seed=23,
            ts="2026-05-21T02:00:00+00:00",
            summary="Daily dropped but weekly visible source.",
            safe_ref={"semantic_subject": "memory_os_runtime_diagnostics"},
        )
    )
    daily = module.build_daily_digest(store=store, target_date="2026-05-21", dry_run=False)
    assert daily["would_write"]["dropped_count"] == 1

    weekly = module.build_weekly_consolidation(store=store, target_week="2026-W21", dry_run=True)

    artifact = weekly["would_write"]
    assert set(artifact["expanded_event_refs"]) == {f"event:{event.id}" for event in store.read_events()}
    assert artifact["daily_digest_refs"] == ["daily:2026-05-21"]
    assert artifact["forbidden_sources"] == ["raw_full_session_transcripts"]


def test_weekly_consolidation_caps_candidates_and_updates_overlap(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    module = DigestConsolidationModule(tmp_path, profile="main")
    subjects = [
        "memory_os_runtime_diagnostics",
        "telegram_session_continuity",
        "cron_failure_backpressure",
        "owner_review_backlog",
        "tool_failure_learning",
        "extra_low_priority_subject",
    ]
    for offset, subject in enumerate(subjects):
        store.append_event(
            _event(
                seed=40 + offset,
                ts=f"2026-05-2{offset % 3}T01:00:00+00:00",
                summary=f"Weekly consolidation source for {subject}.",
                safe_ref={"semantic_subject": subject},
            )
        )

    first = module.build_weekly_consolidation(
        store=store,
        target_week="2026-W21",
        proposal_queue=proposal_queue,
        dry_run=False,
    )
    queue = proposal_queue.read_queue()

    assert first["would_write"]["deferred_candidate_count"] == 1
    assert len(queue["items"]) == 5
    assert all(item["kind"] == "weekly_consolidation" for item in queue["items"])
    assert all(item["crystallized_approved"] is False for item in queue["items"])

    existing = next(item for item in queue["items"] if item["semantic_subject"] == "memory_os_runtime_diagnostics")
    store.append_event(
        _event(
            seed=99,
            ts="2026-05-22T03:00:00+00:00",
            summary="Overlapping diagnostics source.",
            safe_ref={"semantic_subject": "memory_os_runtime_diagnostics"},
        )
    )

    module.build_weekly_consolidation(
        store=store,
        target_week="2026-W21",
        proposal_queue=proposal_queue,
        dry_run=False,
    )
    updated_queue = proposal_queue.read_queue()
    updated = next(
        item for item in updated_queue["items"] if item["candidate_id"] == existing["candidate_id"]
    )

    assert len(updated_queue["items"]) == 5
    assert len(updated["source_refs"]) > len(existing["source_refs"])
    assert updated["dedup_history"][-1]["action"] == "candidate_updated_via_overlap"


def test_weekly_consolidation_blocks_operational_metadata_candidates(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    module = DigestConsolidationModule(tmp_path, profile="main")
    for seed, source_class, kind in (
        (70, "cron", "cron_job_run"),
        (71, "state", "state_source_changed"),
        (72, "session", "session_observed"),
    ):
        store.append_event(
            _event(
                seed=seed,
                ts="2026-05-21T01:00:00+00:00",
                kind=kind,
                source_class=source_class,
                summary=f"{source_class} metadata should not become owner fact.",
            )
        )

    result = module.build_weekly_consolidation(
        store=store,
        target_week="2026-W21",
        proposal_queue=proposal_queue,
        dry_run=False,
    )

    assert result["would_write"]["candidate_suggestions"] == []
    assert proposal_queue.read_queue()["items"] == []


def test_weekly_dry_run_and_apply_artifacts_are_equivalent(tmp_path):
    store = _store(tmp_path)
    module = DigestConsolidationModule(tmp_path, profile="main")
    store.append_event(
        _event(
            seed=80,
            ts="2026-05-21T01:00:00+00:00",
            summary="Weekly dry-run contract source.",
            safe_ref={"semantic_subject": "telegram_session_continuity"},
        )
    )

    dry_run = module.build_weekly_consolidation(store=store, target_week="2026-W21", dry_run=True)
    applied = module.build_weekly_consolidation(store=store, target_week="2026-W21", dry_run=False)
    artifact = json.loads(Path(applied["artifact_ref"]).read_text(encoding="utf-8"))

    assert artifact == dry_run["would_write"]
    assert applied["applied"] is True


def test_digest_doctor_warns_on_artifact_accumulation_threshold(tmp_path):
    module = DigestConsolidationModule(tmp_path, profile="main")
    module.write_config({"artifact_count_warning_threshold": 1})
    (module.daily_root).mkdir(parents=True)
    for day in ("2026-05-20", "2026-05-21"):
        (module.daily_root / f"{day}.json").write_text("{}\n", encoding="utf-8")

    report = module.doctor()

    assert report["status"] == "warning"
    assert report["findings"][0]["code"] == "digest_artifact_count_high"


def test_digest_consolidation_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    store.append_event(
        _event(
            seed=4,
            ts="2026-05-21T01:00:00+00:00",
            summary="Main profile event only.",
        )
    )
    module = DigestConsolidationModule(tmp_path / "main", profile="main")

    module.build_daily_digest(store=store, target_date="2026-05-21", dry_run=True)

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
