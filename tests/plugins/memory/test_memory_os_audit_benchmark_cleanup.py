import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from plugins.memory.memory_os.cli import (
    approval_report,
    benchmark_report,
    build_doctor_result,
    build_status_report,
    cleanup_report,
    diff_report,
    inspect_event,
    meta_audit,
    memory_os_command,
    register_cli,
    trace_record,
)
from plugins.memory.memory_os.audit import read_audit_entries
from plugins.memory.memory_os.benchmark import BenchmarkConfig, run_benchmark
from plugins.memory.memory_os.cleanup import CleanupPolicy, apply_cleanup, cleanup_plan
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.memory_sources import memory_sources_feedback_path, memory_sources_path
from plugins.memory.memory_os.metadata_retention import MetadataRetentionPolicy, metadata_retention_plan
from plugins.memory.memory_os.migrator import export_shadow_bundle, import_shadow_bundle
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.working import WorkingMemoryService


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _touch(path, *, days_old, now=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stale", encoding="utf-8")
    base = now or datetime.now(timezone.utc)
    ts = (base - timedelta(days=days_old)).timestamp()
    os.utime(path, (ts, ts))


def _touch_dir(path, *, days_old, now=None):
    path.mkdir(parents=True, exist_ok=True)
    marker = path / "summary.json"
    marker.write_text("{}", encoding="utf-8")
    base = now or datetime.now(timezone.utc)
    ts = (base - timedelta(days=days_old)).timestamp()
    os.utime(path, (ts, ts))
    os.utime(marker, (ts, ts))


def test_status_and_doctor_do_not_print_private_bodies(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=31, profile="memoryos-test"),
            "summary": "Safe summary only.",
            "safe_ref": {"raw_body": "PRIVATE RAW BODY"},
        }
    )
    store.append_event(event)
    (store.roots.relationships_root / "owner.md").write_text(
        "PRIVATE RELATIONSHIP BODY",
        encoding="utf-8",
    )

    status = json.dumps(build_status_report(store), ensure_ascii=False)
    doctor = json.dumps(build_doctor_result(store), ensure_ascii=False)

    assert "PRIVATE RAW BODY" not in status
    assert "PRIVATE RELATIONSHIP BODY" not in status
    assert "PRIVATE RAW BODY" not in doctor
    assert "PRIVATE RELATIONSHIP BODY" not in doctor
    assert "Safe summary only." in status


def test_inspect_and_trace_require_include_private_for_body_output(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=32, profile="memoryos-test"),
            "summary": "Safe inspect summary.",
            "safe_ref": {"raw_body": "PRIVATE EVENT BODY"},
        }
    )
    store.append_event(event)
    working = WorkingMemoryService(store)
    item = working.add_item("lingering", "PRIVATE WORKING BODY", weight=0.8)

    public_event = inspect_event(store, event.id)
    private_event = inspect_event(store, event.id, include_private=True)
    public_trace = trace_record(store, item.id)
    private_trace = trace_record(store, item.id, include_private=True)

    assert public_event["safe_ref"] == {"raw_body": "[redacted]"}
    assert private_event["safe_ref"]["raw_body"] == "PRIVATE EVENT BODY"
    assert public_trace["item"]["text"] == "[redacted]"
    assert private_trace["item"]["text"] == "PRIVATE WORKING BODY"


def test_meta_audit_reports_index_stale_and_missing_identity_source(tmp_path):
    store = _store(tmp_path)
    first = EventEnvelope.from_dict(build_event(seed=33, profile="memoryos-test"))
    second = EventEnvelope.from_dict(build_event(seed=34, profile="memoryos-test"))
    store.append_event(first)
    MemoryOSIndex(store.roots).sync_from_store(store)
    store.append_event(second)
    store.roots.identity_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    store.roots.identity_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.identity_manifest.v0",
                "profile": "memoryos-test",
                "identity_sources": [{"kind": "soul", "path": str(tmp_path / "missing-SOUL.md")}],
                "last_checked_at": "2026-05-20T08:00:00+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    audit = meta_audit(store)

    finding_ids = {finding["id"] for finding in audit["findings"]}
    assert "index_stale" in finding_ids
    assert "identity_source_missing" in finding_ids
    assert build_doctor_result(store)["exit_code"] == 1


def test_doctor_exit_zero_for_warnings_only(tmp_path):
    store = _store(tmp_path)

    result = build_doctor_result(store)

    assert result["exit_code"] == 0
    assert any(finding["severity"] == "warning" for finding in result["findings"])


def test_doctor_reports_appended_events_as_index_stale_not_mismatch(tmp_path):
    store = _store(tmp_path)
    first = EventEnvelope.from_dict(build_event(seed=1, profile="memoryos-test"))
    second = EventEnvelope.from_dict(build_event(seed=2, profile="memoryos-test"))
    store.append_event(first)
    MemoryOSIndex(store.roots).sync_from_store(store)

    store.append_event(second)

    result = build_doctor_result(store)

    assert result["exit_code"] == 0
    assert any(finding["code"] == "index_stale" for finding in result["findings"])
    assert not any(finding["code"] == "index_count_mismatch" for finding in result["findings"])


def test_doctor_does_not_count_revoked_crystallized_audit_records_as_index_mismatch(tmp_path):
    store = _store(tmp_path)
    active_frontmatter = {
        "id": "cry_active",
        "kind": "owner_approved",
        "created_at": "2026-06-01T00:00:00Z",
        "approved_by": "owner",
        "approved_at": "2026-06-01T00:00:00Z",
        "source_event_ids": [],
        "tags": ["smoke"],
        "sensitivity": "public",
        "hindsight_indexed": False,
    }
    revoked_frontmatter = {
        **active_frontmatter,
        "id": "cry_revoked",
        "canonical_state": "revoked",
        "revoked_at": "2026-06-01T00:01:00Z",
        "revoked_by": "owner",
    }
    store.append_crystallized_record("owner_approved.md", active_frontmatter, "Active memory.")
    store.append_crystallized_record("owner_approved.md", revoked_frontmatter, "Revoked audit evidence.")
    MemoryOSIndex(store.roots).sync_from_store(store)

    status = build_status_report(store)
    result = build_doctor_result(store)

    assert status["counts"]["crystallized_records"] == 1
    assert status["counts"]["crystallized_records_total"] == 2
    assert status["counts"]["crystallized_records_inactive"] == 1
    assert status["index_counts"]["crystallized_records"] == 1
    assert not any(finding["code"] == "index_count_mismatch" for finding in result["findings"])


def test_doctor_reports_sqlite_row_corruption_as_content_mismatch(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(build_event(seed=3, profile="memoryos-test"))
    store.append_event(event)
    MemoryOSIndex(store.roots).sync_from_store(store)
    with sqlite3.connect(store.roots.index_path) as conn:
        conn.execute("update events set summary = ? where id = ?", ("corrupted summary", event.id))

    result = build_doctor_result(store)

    assert result["exit_code"] == 1
    assert any(finding["code"] == "index_content_mismatch" for finding in result["findings"])


def test_status_and_doctor_report_degraded_prefetch_when_index_missing(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=4, profile="memoryos-test")))

    missing_status = build_status_report(store)
    missing_doctor = build_doctor_result(store)

    assert missing_status["prefetch_mode"] == "degraded_filesystem"
    assert any(finding["code"] == "prefetch_degraded" for finding in missing_doctor["findings"])

    MemoryOSIndex(store.roots).sync_from_store(store)
    indexed_status = build_status_report(store)

    assert indexed_status["prefetch_mode"] == "indexed"


def test_status_reports_index_health_and_fts_tokenizer(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=5, profile="memoryos-test")))
    MemoryOSIndex(store.roots).sync_from_store(store)

    status = build_status_report(store)

    assert status["index_health"]["state"] == "healthy"
    assert status["index_health"]["fts_tokenizer"] in {"trigram", "unicode61"}


def test_status_and_doctor_report_continuity_selector_counts(tmp_path):
    store = _store(tmp_path)
    for seed in range(60, 70):
        store.append_event(EventEnvelope.from_dict(build_event(seed=seed, profile="memoryos-test")))

    status = build_status_report(store)
    doctor = build_doctor_result(store)

    assert status["continuity_selector"]["schema_version"] == "memory-os.continuity_selector.v0"
    assert status["continuity_selector"]["selected_total"] > 0
    assert status["continuity_selector"]["dropped_total"] > 0
    assert doctor["meta_audit"]["continuity_selector"]["selected_total"] == status["continuity_selector"]["selected_total"]


def test_diff_and_approval_report_use_metadata_not_private_bodies(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=35, profile="memoryos-test"),
            "summary": "Visible summary.",
            "safe_ref": {"raw_body": "PRIVATE BODY"},
        }
    )
    store.append_event(event)
    bundle = tmp_path / "bundle"
    source_layout = tmp_path / "source"
    source_store = _store(source_layout)
    export_shadow_bundle(source_store.roots, out_path=bundle)
    import_shadow_bundle(bundle, store.roots, dry_run=False)

    diff = json.dumps(
        diff_report(
            store,
            since="2026-05-20T00:00:00+00:00",
            until="2026-05-21T00:00:00+00:00",
        ),
        ensure_ascii=False,
    )
    approval = json.dumps(approval_report(store), ensure_ascii=False)

    assert "PRIVATE BODY" not in diff
    assert "PRIVATE BODY" not in approval
    assert "event_count" in diff
    assert "approval_state_counts" in approval


def test_tiny_benchmark_uses_synthetic_corpus_and_reports_slo(tmp_path):
    store = _store(tmp_path)

    report = run_benchmark(
        store,
        BenchmarkConfig(record_count=25, seed=41, profile="memoryos-test", large_opt_in=False),
    )

    assert report["schema_version"] == "memory-os.benchmark.v0"
    assert report["record_count"] == 25
    assert report["corpus"]["seed"] == 41
    assert report["corpus"]["source"] == "fixtures.generate_event_corpus"
    assert report["large_opt_in_required"] is False
    assert set(report["metrics"]) == {
        "event_append_p95_ms",
        "prefetch_degraded_ms",
        "prefetch_indexed_ms",
        "sqlite_rebuild_ms",
        "working_decay_ms",
        "status_command_ms",
    }
    assert report["status_counts"]["prefetch_degraded_chars"] >= 0
    assert report["status_counts"]["prefetch_indexed_chars"] >= 0
    assert report["slo"]["sync_turn_enqueue_p95_ms"] == 20.0
    assert report["pass"] is True


def test_large_benchmark_requires_explicit_opt_in(tmp_path):
    store = _store(tmp_path)

    report = run_benchmark(
        store,
        BenchmarkConfig(record_count=100_000, seed=42, profile="memoryos-test", large_opt_in=False),
    )

    assert report["skipped"] is True
    assert report["large_opt_in_required"] is True
    assert not list(store.roots.events_root.glob("*/*.jsonl"))


def test_benchmark_cli_wrapper_returns_json_report(tmp_path):
    store = _store(tmp_path)

    report = benchmark_report(store, record_count=10, seed=43)

    assert report["schema_version"] == "memory-os.benchmark.v0"
    assert report["record_count"] == 10
    assert report["metrics"]["sqlite_rebuild_ms"] >= 0.0


def test_cleanup_plan_is_dry_run_and_excludes_protected_memory(tmp_path):
    store = _store(tmp_path)
    identity_source = tmp_path / "SOUL.md"
    identity_source.write_text("protected identity", encoding="utf-8")
    store.roots.identity_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.identity_manifest.v0",
                "profile": "memoryos-test",
                "identity_sources": [{"kind": "soul", "path": str(identity_source)}],
            }
        ),
        encoding="utf-8",
    )
    crystallized_path = store.append_crystallized_record(
        "moments.md",
        {"schema_version": "memory-os.crystallized.v0", "id": "crystal-1"},
        "protected crystallized body",
    )
    _touch(store.roots.quarantine_root / "malformed_events.jsonl", days_old=90)
    _touch(store.roots.imports_root / "shadow-001" / "import_report.json", days_old=90)
    _touch(store.roots.memory_os_root / "benchmarks" / "benchmark-001.json", days_old=90)
    _touch(store.roots.memory_os_root / "tmp" / "leftover.tmp", days_old=90)
    now = datetime.now(timezone.utc)

    plan = cleanup_plan(
        store,
        now=now,
        policy=CleanupPolicy(
            quarantine_retention_days=30,
            import_retention_days=30,
            benchmark_retention_days=30,
            temp_retention_days=1,
        ),
    )

    assert plan["schema_version"] == "memory-os.cleanup_plan.v0"
    assert plan["dry_run"] is True
    assert plan["plan_id"]
    action_targets = {action["target"] for action in plan["actions"]}
    assert str(store.roots.quarantine_root / "malformed_events.jsonl") in action_targets
    assert str(store.roots.imports_root / "shadow-001" / "import_report.json") in action_targets
    assert str(store.roots.memory_os_root / "benchmarks" / "benchmark-001.json") in action_targets
    assert str(store.roots.memory_os_root / "tmp" / "leftover.tmp") in action_targets
    assert str(identity_source) not in action_targets
    assert str(crystallized_path) not in action_targets
    assert identity_source.exists()
    assert crystallized_path.exists()


def test_apply_cleanup_requires_matching_generated_plan_id(tmp_path):
    store = _store(tmp_path)
    stale_quarantine = store.roots.quarantine_root / "malformed_events.jsonl"
    _touch(stale_quarantine, days_old=90)
    plan = cleanup_plan(
        store,
        now=datetime.now(timezone.utc),
        policy=CleanupPolicy(quarantine_retention_days=30),
    )

    denied = apply_cleanup(store, plan)
    wrong_id = apply_cleanup(store, plan, confirmed_plan_id="wrong-plan")
    applied = apply_cleanup(store, plan, confirmed_plan_id=plan["plan_id"])

    assert denied["applied"] is False
    assert wrong_id["applied"] is False
    assert stale_quarantine.exists() is False
    assert applied["applied"] is True
    assert applied["applied_count"] == 1


def test_cleanup_apply_writes_audit_for_each_action_and_keeps_protected_records(tmp_path):
    store = _store(tmp_path)
    identity_source = tmp_path / "SOUL.md"
    identity_source.write_text("protected identity", encoding="utf-8")
    store.roots.identity_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.identity_manifest.v0",
                "profile": "memoryos-test",
                "identity_sources": [{"kind": "soul", "path": str(identity_source)}],
            }
        ),
        encoding="utf-8",
    )
    crystallized_path = store.append_crystallized_record(
        "insights.md",
        {"schema_version": "memory-os.crystallized.v0", "id": "crystal-2"},
        "protected insight",
    )
    _touch(store.roots.quarantine_root / "bad.jsonl", days_old=90)
    _touch(store.roots.memory_os_root / "tmp" / "bad.tmp", days_old=90)
    plan = cleanup_plan(
        store,
        now=datetime.now(timezone.utc),
        policy=CleanupPolicy(quarantine_retention_days=30, temp_retention_days=1),
    )

    result = apply_cleanup(store, plan, confirmed_plan_id=plan["plan_id"])

    audit_cleanup_actions = [
        entry["action"]
        for entry in read_audit_entries(store.roots.audit_path)
        if entry["action"] == "cleanup_apply_action"
    ]
    assert result["applied"] is True
    assert result["applied_count"] == 2
    assert len(audit_cleanup_actions) == 2
    assert identity_source.exists()
    assert crystallized_path.exists()


def test_cleanup_cli_wrapper_is_dry_run_by_default(tmp_path):
    store = _store(tmp_path)
    stale_quarantine = store.roots.quarantine_root / "cli-bad.jsonl"
    _touch(stale_quarantine, days_old=90)

    report = cleanup_report(
        store,
        now=datetime.now(timezone.utc),
        policy=CleanupPolicy(quarantine_retention_days=30),
    )

    assert report["schema_version"] == "memory-os.cleanup_plan.v0"
    assert report["dry_run"] is True
    assert len(report["actions"]) == 1
    assert stale_quarantine.exists()


def test_metadata_retention_plan_is_dry_run_and_keeps_canonical_paths(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    identity_source = tmp_path / "SOUL.md"
    identity_source.write_text("protected identity", encoding="utf-8")
    store.roots.identity_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.identity_manifest.v0",
                "profile": "memoryos-test",
                "identity_sources": [{"kind": "soul", "path": str(identity_source)}],
            }
        ),
        encoding="utf-8",
    )
    crystallized_path = store.append_crystallized_record(
        "stable.md",
        {"schema_version": "memory-os.crystallized.v0", "id": "crystal-retention"},
        "protected crystallized record",
    )
    memory_sources_path(store.roots).parent.mkdir(parents=True, exist_ok=True)
    old_ts = (now - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    fresh_ts = (now - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    memory_sources_path(store.roots).write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "record_id": "ms_old",
                        "created_at": old_ts,
                        "route": "ambiguous_recall",
                        "raw_prompt": "private body must not appear in plan",
                    },
                    sort_keys=True,
                ),
                json.dumps({"record_id": "ms_fresh", "created_at": fresh_ts, "route": "active_task"}, sort_keys=True),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    memory_sources_feedback_path(store.roots).write_text(
        json.dumps({"feedback_id": "fb_old", "created_at": old_ts, "rating": "useful"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    suggestion_ledger = store.roots.memory_os_root / "system" / "consolidation_suggestions.jsonl"
    suggestion_ledger.write_text(
        json.dumps({"suggestion_id": "sg_old", "created_at": old_ts}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    eval_reports = tmp_path / "eval" / "reports" / "memory-os-rh31"
    _touch_dir(eval_reports / "rh31_old", days_old=46, now=now)
    _touch_dir(eval_reports / "rh31_fresh", days_old=1)

    plan = metadata_retention_plan(
        store.roots,
        now=now,
        policy=MetadataRetentionPolicy(
            memory_sources_retention_days=30,
            feedback_retention_days=30,
            suggestion_retention_days=30,
            eval_report_retention_days=30,
            eval_report_keep_latest=1,
        ),
        eval_report_root=eval_reports,
    )

    assert plan["schema_version"] == "memory-os.metadata_retention_plan.v0"
    assert plan["dry_run"] is True
    assert plan["canonical_paths_touched"] == []
    assert identity_source.exists()
    assert crystallized_path.exists()
    assert "private body must not appear in plan" not in json.dumps(plan, ensure_ascii=False)
    actions = plan["actions"]
    assert {
        (action["kind"], action.get("ledger"), action.get("record_count"))
        for action in actions
        if action["kind"] == "archive_metadata_jsonl_records"
    } == {
        ("archive_metadata_jsonl_records", "memory_sources", 1),
        ("archive_metadata_jsonl_records", "memory_sources_feedback", 1),
        ("archive_metadata_jsonl_records", "consolidation_suggestions", 1),
    }
    assert [action for action in actions if action["kind"] == "archive_report_dir"][0]["target"].endswith("rh31_old")


def test_metadata_retention_cli_is_dry_run(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    memory_sources_path(store.roots).parent.mkdir(parents=True, exist_ok=True)
    memory_sources_path(store.roots).write_text(
        json.dumps(
            {
                "record_id": "ms_cli_old",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=45)).isoformat(),
                "route": "ambiguous_recall",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(["metadata-retention", "--memory-sources-days", "30"])

    result = memory_os_command(args)

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["schema_version"] == "memory-os.metadata_retention_plan.v0"
    assert output["dry_run"] is True
    assert output["actions"][0]["ledger"] == "memory_sources"
    assert memory_sources_path(store.roots).exists()


def test_cleanup_cli_accepts_event_source_class_retention_policy(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    old_telemetry = EventEnvelope.from_dict(
        {
            **build_event(seed=86, profile="memoryos-test"),
            "id": "evt_cli_old_telemetry",
            "ts": (now - timedelta(days=45)).isoformat(),
            "source": "telemetry_probe",
            "kind": "telemetry_status",
            "summary": "Telemetry event should be planned through CLI.",
            "safe_ref": {"source_class": "telemetry", "retention_class": "low_value"},
            "tags": ["telemetry"],
        }
    )
    store.append_event(old_telemetry)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    parser = argparse.ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(["cleanup", "--event-source-class-retention", "telemetry=30"])

    result = memory_os_command(args)

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["dry_run"] is True
    assert output["policy"]["event_retention_days_by_source_class"] == {"telemetry": 30}
    assert [action["event_id"] for action in output["actions"] if action["kind"] == "prune_event_line"] == [
        "evt_cli_old_telemetry"
    ]


def test_retention_prunes_explicit_low_value_source_class_with_archive(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)
    old_telemetry = EventEnvelope.from_dict(
        {
            **build_event(seed=81, profile="memoryos-test"),
            "id": "evt_old_telemetry",
            "ts": (now - timedelta(days=45)).isoformat(),
            "source": "telemetry_probe",
            "kind": "telemetry_status",
            "summary": "PCDN telemetry status repeated normal report.",
            "safe_ref": {"source_class": "telemetry", "retention_class": "low_value"},
            "tags": ["telemetry"],
        }
    )
    fresh_telemetry = EventEnvelope.from_dict(
        {
            **build_event(seed=82, profile="memoryos-test"),
            "id": "evt_fresh_telemetry",
            "ts": (now - timedelta(days=2)).isoformat(),
            "source": "telemetry_probe",
            "kind": "telemetry_status",
            "summary": "Recent telemetry status should remain hot.",
            "safe_ref": {"source_class": "telemetry", "retention_class": "low_value"},
            "tags": ["telemetry"],
        }
    )
    old_foreground = EventEnvelope.from_dict(
        {
            **build_event(seed=83, profile="memoryos-test"),
            "id": "evt_old_foreground",
            "ts": (now - timedelta(days=45)).isoformat(),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": "Old foreground conversation is high-value and should remain.",
            "safe_ref": {"source_class": "foreground"},
            "tags": ["foreground"],
        }
    )
    store.append_event(old_telemetry)
    store.append_event(fresh_telemetry)
    store.append_event(old_foreground)

    plan = cleanup_plan(
        store,
        now=now,
        policy=CleanupPolicy(event_retention_days_by_source_class={"telemetry": 30}),
    )

    actions = plan["actions"]
    prune_actions = [action for action in actions if action["kind"] == "prune_event_line"]
    assert len(prune_actions) == 1
    assert prune_actions[0]["event_id"] == "evt_old_telemetry"
    assert prune_actions[0]["source_class"] == "telemetry"
    assert prune_actions[0]["archive_before_delete"] is True
    assert plan["event_retention"]["scanned_event_count"] == 3

    result = apply_cleanup(store, plan, confirmed_plan_id=plan["plan_id"])

    remaining_ids = {event.id for event in store.read_events()}
    archive_lines = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((store.roots.memory_os_root / "archive" / "retention").glob("*.jsonl"))
    )
    assert result["applied"] is True
    assert "evt_old_telemetry" not in remaining_ids
    assert "evt_fresh_telemetry" in remaining_ids
    assert "evt_old_foreground" in remaining_ids
    assert "evt_old_telemetry" in archive_lines
    assert "PCDN telemetry status repeated normal report." in archive_lines


def test_retention_preserves_high_value_and_active_candidate_events_even_if_policy_matches(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)
    old_foreground = EventEnvelope.from_dict(
        {
            **build_event(seed=84, profile="memoryos-test"),
            "id": "evt_high_value_foreground",
            "ts": (now - timedelta(days=90)).isoformat(),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": "Old foreground conversation must not be automatically pruned.",
            "safe_ref": {"source_class": "foreground"},
            "tags": ["foreground"],
        }
    )
    active_candidate = EventEnvelope.from_dict(
        {
            **build_event(seed=85, profile="memoryos-test"),
            "id": "evt_active_candidate",
            "ts": (now - timedelta(days=90)).isoformat(),
            "source": "governance_feedback",
            "kind": "governance_proposal",
            "summary": "Active proposal queue candidate must remain canonical.",
            "safe_ref": {
                "source_class": "governance",
                "approval_state": "candidate",
                "candidate_allowed": False,
            },
            "tags": ["governance"],
        }
    )
    store.append_event(old_foreground)
    store.append_event(active_candidate)

    plan = cleanup_plan(
        store,
        now=now,
        policy=CleanupPolicy(
            event_retention_days_by_source_class={"foreground": 30, "governance": 30}
        ),
    )

    assert not [action for action in plan["actions"] if action["kind"] == "prune_event_line"]
    archive_actions = [action for action in plan["actions"] if action["kind"] == "archive_high_value_event_summary"]
    assert {action["event_id"] for action in archive_actions} == {
        "evt_high_value_foreground",
        "evt_active_candidate",
    }
    assert all(action["delete_after_archive"] is False for action in archive_actions)

    result = apply_cleanup(store, plan, confirmed_plan_id=plan["plan_id"])

    remaining_ids = {event.id for event in store.read_events()}
    archive_lines = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((store.roots.memory_os_root / "archive" / "retention").glob("*.jsonl"))
    )
    assert result["applied"] is True
    assert "evt_high_value_foreground" in remaining_ids
    assert "evt_active_candidate" in remaining_ids
    assert "evt_high_value_foreground" in archive_lines
    assert "evt_active_candidate" in archive_lines


def test_retention_apply_revalidates_prune_event_line_actions(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)
    old_foreground = EventEnvelope.from_dict(
        {
            **build_event(seed=87, profile="memoryos-test"),
            "id": "evt_forged_foreground",
            "ts": (now - timedelta(days=90)).isoformat(),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": "Forged prune action must not delete foreground conversation.",
            "safe_ref": {"source_class": "foreground"},
            "tags": ["foreground"],
        }
    )
    event_path = store.append_event(old_foreground)
    plan = {
        "schema_version": "memory-os.cleanup_plan.v0",
        "plan_id": "cleanup_plan_forged",
        "actions": [
            {
                "id": "cleanup_action_forged",
                "kind": "prune_event_line",
                "target": str(event_path),
                "event_id": "evt_forged_foreground",
                "source_class": "foreground",
                "archive_before_delete": True,
            }
        ],
    }

    result = apply_cleanup(store, plan, confirmed_plan_id=plan["plan_id"])

    remaining_ids = {event.id for event in store.read_events()}
    assert result["applied"] is False
    assert result["skipped_count"] == 1
    assert "evt_forged_foreground" in remaining_ids
