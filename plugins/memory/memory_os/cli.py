"""Local diagnostic helpers for Memory-OS operator commands."""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _ensure_user_plugin_package() -> None:
    """Make Hermes' direct user-plugin CLI import support relative imports.

    Hermes imports active user memory plugin CLIs as
    ``_hermes_user_memory.<provider>.cli`` before the provider package has
    necessarily been loaded. Creating the missing parent package modules keeps
    this file importable in a fresh Hermes process.
    """
    package = __package__ or ""
    if not package.startswith("_hermes_user_memory."):
        return
    current_dir = Path(__file__).resolve().parent
    root_name = package.split(".", 1)[0]
    provider_package = package
    if root_name not in sys.modules:
        root = types.ModuleType(root_name)
        root.__path__ = [str(current_dir.parent)]  # type: ignore[attr-defined]
        sys.modules[root_name] = root
    if provider_package not in sys.modules:
        provider = types.ModuleType(provider_package)
        provider.__path__ = [str(current_dir)]  # type: ignore[attr-defined]
        sys.modules[provider_package] = provider


_ensure_user_plugin_package()

from .audit import last_audit_age_seconds, read_audit_entries
from .benchmark import BenchmarkConfig, run_benchmark
from .cleanup import CleanupPolicy, cleanup_plan
from .config import load_config
from .conversation_regression import (
    evaluate_transcript_file,
    prompt_set_report,
    status_tool_contract_report,
)
from .cognitive_loop import CognitiveLoopRunner
from .cron_mirror import CronMirror
from .crystallized import read_candidate_queue
from .index import MemoryOSIndex
from .low_clue_recall import build_low_clue_recall_report, low_clue_judge_availability
from .memory_sources import (
    memory_sources_feedback_history_report,
    memory_sources_feedback_last_report,
    memory_sources_history_report,
    memory_sources_last_report,
    memory_sources_stats_report,
)
from .metadata_retention import MetadataRetentionPolicy, metadata_retention_plan
from .migrator import (
    export_shadow_bundle,
    import_shadow_bundle,
    migration_diff_report,
    migration_scan_report,
    replay_shadow_import,
)
from .owner_actions import (
    approved_proposal_followups_report,
    apply_owner_action,
    deliver_owner_review_digest_once,
    owner_review_aging_report,
    owner_review_cron_integration_report,
    owner_review_delivery_gate_report,
    owner_review_delivery_status_report,
    owner_review_digest_preview,
    owner_review_queue_report,
    owner_review_surface_report,
    owner_review_status_report,
    parse_owner_review_reply,
    render_owner_review_digest,
    resolve_owner_review_channel,
    route_approved_proposal_followup_to_ops_gate,
)
from .prefetch import continuity_selector_report
from .prefetch import build_context_router_report
from .roots import MemoryOSRoots
from .runtime import MemoryOSRuntime
from .schema import EVENT_SCHEMA_VERSION, WORKING_SCHEMA_VERSION
from .session_mirror import SessionMirror
from .shadow_journal import ShadowJournalIngestion
from .state_source_mirror import StateSourceMirror
from .store import MemoryOSStore
from .working import WorkingMemoryService


_PRIVATE_SAFE_REF_KEYS = {"raw_body", "body", "content", "transcript", "private_body", "raw_transcript"}


def build_status_report(store: MemoryOSStore) -> dict[str, Any]:
    events = store.read_events()
    store_counts = _store_counts(store)
    index_counts = MemoryOSIndex(store.roots).counts()
    prefetch_mode = _prefetch_mode(store)
    config = load_config(store.roots.hermes_home)
    return {
        "schema_version": "memory-os.status.v0",
        "root": str(store.roots.memory_os_root),
        "profile": store.roots.profile,
        "counts": store_counts,
        "index_counts": index_counts,
        "index_health": _index_health_summary(store, store_counts, index_counts),
        "prefetch_mode": prefetch_mode,
        "continuity_selector": continuity_selector_report(store),
        "queue_backlog": 0,
        "last_write_age_seconds": last_audit_age_seconds(store.roots.audit_path),
        "recent_event_summaries": [
            {"id": event.id, "ts": event.ts, "kind": event.kind, "summary": event.summary}
            for event in sorted(events, key=lambda item: item.ts)[-5:]
        ],
        "hindsight_adapter_enabled": bool(config.get("hindsight_adapter_enabled")),
        "low_clue_recall": {
            "enabled": bool((config.get("low_clue_recall") or {}).get("enabled"))
            if isinstance(config.get("low_clue_recall"), dict)
            else False,
            "judge_availability": low_clue_judge_availability(config.get("low_clue_recall")),
        },
        "owner_review": owner_review_status_report(store),
    }


def build_doctor_result(store: MemoryOSStore) -> dict[str, Any]:
    audit = meta_audit(store)
    has_error = any(finding["severity"] == "error" for finding in audit["findings"])
    return {
        "schema_version": "memory-os.doctor.v0",
        "exit_code": 1 if has_error else 0,
        "status": "fail" if has_error else "ok",
        "findings": audit["findings"],
        "meta_audit": audit,
    }


def meta_audit(store: MemoryOSStore) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    status = build_status_report(store)
    store_counts = status["counts"]
    index_counts = status["index_counts"]
    continuity_selector = status["continuity_selector"]
    if not store.roots.index_path.exists():
        findings.append(_finding("index_missing", "warning", "SQLite index is missing; rebuild is available."))
    else:
        findings.extend(_index_health_findings(store, store_counts, index_counts))

    findings.extend(_identity_source_findings(store))
    if store_counts["events"] == 0:
        findings.append(_finding("store_empty", "warning", "No event records found."))
    if status["prefetch_mode"] == "degraded_filesystem":
        findings.append(
            _finding(
                "prefetch_degraded",
                "warning",
                "Prefetch is using bounded filesystem fallback because the SQLite index is unavailable.",
            )
        )
    if not bool(load_config(store.roots.hermes_home).get("hindsight_adapter_enabled")):
        findings.append(_finding("hindsight_adapter_disabled", "warning", "Hindsight adapter is disabled."))
    judge_availability = status.get("low_clue_recall", {}).get("judge_availability", {})
    if (
        isinstance(judge_availability, dict)
        and judge_availability.get("enabled") is True
        and judge_availability.get("available") is not True
    ):
        findings.append(
            _finding(
                "low_clue_llm_judge_unavailable",
                "warning",
                "Low-clue recall LLM judge is configured but unavailable; deterministic fallback remains active.",
                {
                    "status": judge_availability.get("status"),
                    "code": judge_availability.get("code"),
                    "mode": judge_availability.get("mode"),
                    "degrades_to": "deterministic_fallback",
                },
            )
        )
    return {
        "schema_version": "memory-os.meta_audit.v0",
        "root": str(store.roots.memory_os_root),
        "counts": store_counts,
        "index_counts": index_counts,
        "skipped_private_body_count": _skipped_private_body_count(store),
        "queue_backlog": 0,
        "continuity_selector": continuity_selector,
        "last_write_age_seconds": status["last_write_age_seconds"],
        "findings": findings,
    }


def inspect_event(store: MemoryOSStore, event_id: str, *, include_private: bool = False) -> dict[str, Any]:
    for event in store.read_events():
        if event.id != event_id:
            continue
        result = event.to_dict()
        if not include_private:
            result["safe_ref"] = {
                key: "[redacted]" if key in _PRIVATE_SAFE_REF_KEYS else value
                for key, value in result.get("safe_ref", {}).items()
            }
        return result
    return {"found": False, "id": event_id}


def trace_record(store: MemoryOSStore, record_id: str, *, include_private: bool = False) -> dict[str, Any]:
    trace = WorkingMemoryService(store).trace_working_item(record_id)
    if trace.get("found") and not include_private and isinstance(trace.get("item"), dict):
        trace = dict(trace)
        trace["item"] = dict(trace["item"])
        trace["item"]["text"] = "[redacted]"
    return trace


def diff_report(store: MemoryOSStore, *, since: str, until: str) -> dict[str, Any]:
    since_dt = datetime.fromisoformat(since)
    until_dt = datetime.fromisoformat(until)
    events = [
        event for event in store.read_events()
        if since_dt <= datetime.fromisoformat(event.ts) <= until_dt
    ]
    audit_entries = [
        entry for entry in read_audit_entries(store.roots.audit_path)
        if entry.get("ts") and since_dt <= datetime.fromisoformat(str(entry["ts"])) <= until_dt
    ]
    return {
        "schema_version": "memory-os.diff.v0",
        "since": since,
        "until": until,
        "event_count": len(events),
        "audit_count": len(audit_entries),
        "event_kinds": _count_by(events, "kind"),
        "audit_actions": _count_dict(str(entry.get("action", "")) for entry in audit_entries),
    }


def approval_report(store: MemoryOSStore) -> dict[str, Any]:
    approval_counts: dict[str, int] = {}
    candidate_counts: dict[str, int] = {}
    for report_path in sorted(store.roots.imports_root.glob("*/import_report.json")):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        _merge_counts(approval_counts, report.get("approval_state_counts", {}))
        _merge_counts(candidate_counts, report.get("candidate_status_counts", {}))
    return {
        "schema_version": "memory-os.approval_report.v0",
        "approval_state_counts": approval_counts,
        "candidate_status_counts": candidate_counts,
    }


def benchmark_report(
    store: MemoryOSStore,
    *,
    record_count: int = 1000,
    seed: int = 1,
    large_opt_in: bool = False,
) -> dict[str, Any]:
    return run_benchmark(
        store,
        BenchmarkConfig(
            record_count=record_count,
            seed=seed,
            profile=store.roots.profile or "memoryos-test",
            large_opt_in=large_opt_in,
        ),
    )


def cleanup_report(
    store: MemoryOSStore,
    *,
    now: datetime | None = None,
    policy: CleanupPolicy | None = None,
) -> dict[str, Any]:
    return cleanup_plan(store, now=now, policy=policy)


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="memory_os_command")
    subs.add_parser("status")
    subs.add_parser("doctor")
    heartbeat_parser = subs.add_parser("heartbeat")
    heartbeat_parser.add_argument("--max-events", type=int, default=100)
    inspect_parser = subs.add_parser("inspect")
    inspect_parser.add_argument("event_id")
    inspect_parser.add_argument("--include-private", action="store_true")
    trace_parser = subs.add_parser("trace")
    trace_parser.add_argument("record_id")
    trace_parser.add_argument("--include-private", action="store_true")
    diff_parser = subs.add_parser("diff")
    diff_parser.add_argument("--since", required=True)
    diff_parser.add_argument("--until", required=True)
    subs.add_parser("approval-report")
    benchmark_parser = subs.add_parser("benchmark")
    benchmark_parser.add_argument("--records", type=int, default=1000)
    benchmark_parser.add_argument("--seed", type=int, default=1)
    benchmark_parser.add_argument("--large-opt-in", action="store_true")
    cleanup_parser = subs.add_parser("cleanup")
    cleanup_parser.add_argument("--quarantine-days", type=int, default=30)
    cleanup_parser.add_argument("--import-days", type=int, default=30)
    cleanup_parser.add_argument("--benchmark-days", type=int, default=14)
    cleanup_parser.add_argument("--temp-days", type=int, default=1)
    cleanup_parser.add_argument(
        "--event-source-class-retention",
        action="append",
        default=[],
        metavar="SOURCE_CLASS=DAYS",
        help="Add explicit event retention policy for one source_class, e.g. telemetry=30",
    )
    metadata_retention_parser = subs.add_parser("metadata-retention")
    metadata_retention_parser.add_argument("--memory-sources-days", type=int, default=30)
    metadata_retention_parser.add_argument("--feedback-days", type=int, default=30)
    metadata_retention_parser.add_argument("--suggestion-days", type=int, default=30)
    metadata_retention_parser.add_argument("--eval-report-root", default="")
    metadata_retention_parser.add_argument("--eval-report-days", type=int, default=30)
    metadata_retention_parser.add_argument("--eval-report-keep-latest", type=int, default=20)
    metadata_retention_parser.add_argument("--suggestion-report-root", default="")
    metadata_retention_parser.add_argument("--suggestion-report-days", type=int, default=30)
    metadata_retention_parser.add_argument("--suggestion-report-keep-latest", type=int, default=20)
    cron_parser = subs.add_parser("cron-mirror")
    cron_subs = cron_parser.add_subparsers(dest="cron_mirror_command", required=True)
    cron_subs.add_parser("status")
    cron_subs.add_parser("doctor")
    cron_scan = cron_subs.add_parser("scan")
    cron_scan.add_argument("--dry-run", action="store_true")
    cron_scan.add_argument("--apply", action="store_true")
    session_parser = subs.add_parser("session-mirror")
    session_subs = session_parser.add_subparsers(dest="session_mirror_command", required=True)
    session_subs.add_parser("status")
    session_subs.add_parser("doctor")
    session_scan = session_subs.add_parser("scan")
    session_scan.add_argument("--dry-run", action="store_true")
    session_scan.add_argument("--apply", action="store_true")
    state_source_parser = subs.add_parser("state-source-mirror")
    state_source_parser.add_argument("--state-root", action="append", default=[])
    state_source_subs = state_source_parser.add_subparsers(dest="state_source_mirror_command", required=True)
    state_source_subs.add_parser("status")
    state_source_subs.add_parser("doctor")
    state_source_scan = state_source_subs.add_parser("scan")
    state_source_scan.add_argument("--dry-run", action="store_true")
    state_source_scan.add_argument("--apply", action="store_true")
    shadow_parser = subs.add_parser("shadow-journal")
    shadow_subs = shadow_parser.add_subparsers(dest="shadow_journal_command", required=True)
    shadow_subs.add_parser("status")
    shadow_subs.add_parser("doctor")
    shadow_ingest = shadow_subs.add_parser("ingest")
    shadow_ingest.add_argument("--max-records", type=int, default=100)
    shadow_ingest.add_argument("--dry-run", action="store_true")
    shadow_ingest.add_argument("--apply", action="store_true")
    conversation_parser = subs.add_parser("conversation-regression")
    conversation_subs = conversation_parser.add_subparsers(dest="conversation_regression_command", required=True)
    conversation_subs.add_parser("prompts")
    conversation_subs.add_parser("status-tool-contract")
    conversation_evaluate = conversation_subs.add_parser("evaluate")
    conversation_evaluate.add_argument("--transcript", required=True)
    context_router_parser = subs.add_parser("context-router")
    context_router_subs = context_router_parser.add_subparsers(dest="context_router_command", required=True)
    context_router_dry_run = context_router_subs.add_parser("dry-run")
    context_router_dry_run.add_argument("--query", required=True)
    context_router_dry_run.add_argument("--budget", type=int, default=2200)
    context_router_dry_run.add_argument("--current-task-anchor", default="")
    low_clue_parser = subs.add_parser("low-clue-recall")
    low_clue_subs = low_clue_parser.add_subparsers(dest="low_clue_recall_command", required=True)
    low_clue_dry_run = low_clue_subs.add_parser("dry-run")
    low_clue_dry_run.add_argument("--query", required=True)
    low_clue_dry_run.add_argument("--limit", type=int, default=4)
    low_clue_dry_run.add_argument(
        "--llm-judge",
        choices=["config", "none", "report-only"],
        default="config",
        help="Override low-clue LLM judge for this dry-run only.",
    )
    memory_sources_parser = subs.add_parser("memory-sources")
    memory_sources_subs = memory_sources_parser.add_subparsers(dest="memory_sources_command", required=True)
    memory_sources_subs.add_parser("last")
    memory_sources_history = memory_sources_subs.add_parser("history")
    memory_sources_history.add_argument("--limit", type=int, default=20)
    memory_sources_stats = memory_sources_subs.add_parser("stats")
    memory_sources_stats.add_argument("--hours", type=int, default=24)
    memory_sources_feedback = memory_sources_subs.add_parser("feedback")
    memory_sources_feedback_subs = memory_sources_feedback.add_subparsers(
        dest="memory_sources_feedback_command",
        required=True,
    )
    memory_sources_feedback_last = memory_sources_feedback_subs.add_parser("last")
    memory_sources_feedback_last.add_argument("--rating", required=True)
    memory_sources_feedback_last.add_argument("--note", default="")
    memory_sources_feedback_history = memory_sources_feedback_subs.add_parser("history")
    memory_sources_feedback_history.add_argument("--limit", type=int, default=20)
    review_parser = subs.add_parser("review")
    review_subs = review_parser.add_subparsers(dest="review_command", required=True)
    review_subs.add_parser("status")
    review_subs.add_parser("aging-report")
    review_subs.add_parser("channel")
    review_subs.add_parser("cron-status")
    review_subs.add_parser("delivery-status")
    review_delivery_gate = review_subs.add_parser("delivery-gate")
    review_delivery_gate.add_argument("--owner", default="")
    review_deliver_once = review_subs.add_parser("deliver-once")
    review_deliver_once.add_argument("--owner", default="")
    review_deliver_once.add_argument("--delivery-key", default="")
    review_deliver_once.add_argument("--owner-triggered", action="store_true")
    review_deliver_once.add_argument("--apply", action="store_true")
    review_queue = review_subs.add_parser("queue")
    review_queue.add_argument("--limit", type=int, default=20)
    review_surface = review_subs.add_parser("surface")
    review_surface.add_argument("--operation", choices=["overview", "page", "next_page", "detail", "proposal_followups"], default="overview")
    review_surface.add_argument("--section", choices=["all", "action_required", "review_suggested", "fyi"], default="all")
    review_surface.add_argument("--anchor", default="")
    review_surface.add_argument("--action-token", default="")
    review_surface.add_argument("--offset", type=int, default=0)
    review_surface.add_argument("--limit", type=int, default=5)
    review_surface.add_argument("--owner", default="owner")
    review_surface.add_argument("--channel", default="agent")
    review_followups = review_subs.add_parser("proposal-followups")
    review_followups.add_argument("--limit", type=int, default=20)
    review_followups.add_argument("--proposal-id", default="")
    review_followups.add_argument("--ops-gate", action="store_true")
    review_followups.add_argument("--owner", default="owner")
    review_followups.add_argument("--channel", default="cli")
    review_followups.add_argument("--apply", action="store_true")
    review_preview = review_subs.add_parser("preview-digest")
    review_preview.add_argument("--owner", default="")
    review_preview.add_argument("--max-action-required", type=int)
    review_preview.add_argument("--max-review-suggested", type=int)
    review_preview.add_argument("--max-fyi", type=int)
    review_render = review_subs.add_parser("render-digest")
    review_render.add_argument("--owner", default="")
    review_render.add_argument("--channel", default="cli")
    review_render.add_argument("--max-action-required", type=int)
    review_render.add_argument("--max-review-suggested", type=int)
    review_render.add_argument("--max-fyi", type=int)
    review_render.add_argument("--format", choices=["json", "text"], default="json")
    review_render.add_argument("--bounded", action="store_true")
    review_render.add_argument("--record-active", action="store_true")
    review_reply = review_subs.add_parser("reply")
    review_reply.add_argument("reply", nargs="+")
    review_reply.add_argument("--owner", default="owner")
    review_reply.add_argument("--channel", default="cli")
    review_reply.add_argument("--digest-id", default="")
    review_reply.add_argument("--apply", action="store_true")
    review_reply.add_argument("--max-action-required", type=int)
    review_reply.add_argument("--max-review-suggested", type=int)
    review_reply.add_argument("--max-fyi", type=int)
    review_apply = review_subs.add_parser("apply")
    review_apply.add_argument(
        "--action",
        required=True,
        choices=[
            "approve_candidate",
            "reject_candidate",
            "mark_feedback",
            "approve_proposal",
            "reject_proposal",
            "allow_speak_once",
        ],
    )
    review_apply.add_argument("--target", required=True)
    review_apply.add_argument("--owner", default="owner")
    review_apply.add_argument("--channel", default="cli")
    review_apply.add_argument("--note", default="")
    review_apply.add_argument("--rating", default="")
    review_apply.add_argument("--apply", action="store_true")
    eval_parser = subs.add_parser("eval")
    eval_subs = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_rh31 = eval_subs.add_parser("rh31")
    eval_rh31_subs = eval_rh31.add_subparsers(dest="rh31_command", required=True)
    eval_rh31_run = eval_rh31_subs.add_parser("run")
    eval_rh31_run.add_argument("--fixture", default="synthetic")
    eval_rh31_run.add_argument("--adapter", action="append", default=[])
    eval_rh31_run.add_argument("--report-root", default="")
    eval_rh31_run.add_argument("--no-write-report", action="store_true")
    eval_rh31_run.add_argument("--keep-latest", type=int, default=20)
    eval_rh31_run.add_argument("--retention-days", type=int, default=30)
    eval_rh31_summary = eval_rh31_subs.add_parser("summary")
    eval_rh31_summary.add_argument("--report-root", default="")
    eval_rh31_failures = eval_rh31_subs.add_parser("failures")
    eval_rh31_failures.add_argument("--report-root", default="")
    eval_rh31_failures.add_argument("--class", dest="failure_class", default="")
    cognitive_loop_parser = subs.add_parser("cognitive-loop")
    cognitive_loop_subs = cognitive_loop_parser.add_subparsers(dest="cognitive_loop_command", required=True)
    cognitive_loop_subs.add_parser("status")
    cognitive_loop_subs.add_parser("doctor")
    cognitive_loop_history = cognitive_loop_subs.add_parser("history")
    cognitive_loop_history.add_argument("--limit", type=int, default=20)
    cognitive_loop_run_once = cognitive_loop_subs.add_parser("run-once")
    cognitive_loop_run_once.add_argument("--test-host", action="store_true")
    cognitive_loop_run_once.add_argument("--apply", action="store_true")
    cognitive_loop_run_once.add_argument("--max-events", type=int, default=100)
    validate_parser = subs.add_parser("validate")
    validate_parser.add_argument("--profile", default="")
    validate_parser.add_argument("--no-send", action="store_true")
    validate_parser.add_argument("--write-report", action="store_true")
    modules_parser = subs.add_parser("modules")
    modules_subs = modules_parser.add_subparsers(dest="modules_command", required=True)
    modules_subs.add_parser("status")
    modules_subs.add_parser("doctor")
    modules_run_once = modules_subs.add_parser("run-once")
    modules_run_once.add_argument("--module", required=True)
    modules_run_once.add_argument("--dry-run", action="store_true")
    modules_run_once.add_argument("--apply", action="store_true")
    modules_subs.add_parser("validate-no-send")
    modules_deep_reflection = modules_subs.add_parser("deep_reflection")
    deep_reflection_subs = modules_deep_reflection.add_subparsers(
        dest="deep_reflection_command",
        required=True,
    )
    deep_reflection_subs.add_parser("preview-current")
    deep_reflection_history = deep_reflection_subs.add_parser("history")
    deep_reflection_history.add_argument("--days", type=int, default=7)
    export_parser = subs.add_parser("export-shadow")
    export_parser.add_argument("--profile", default="sannai")
    export_parser.add_argument("--hermes-home", required=True)
    export_parser.add_argument("--state-root", action="append", default=[])
    export_parser.add_argument("--out", required=True)
    export_parser.add_argument("--include-private-bodies", action="store_true")
    export_parser.add_argument("--dry-run", action="store_true")
    migrate_parser = subs.add_parser("migrate")
    migrate_subs = migrate_parser.add_subparsers(dest="migrate_command", required=True)
    migrate_scan = migrate_subs.add_parser("scan")
    migrate_scan.add_argument("--profile", default="sannai")
    migrate_scan.add_argument("--hermes-home", required=True)
    migrate_scan.add_argument("--state-root", action="append", default=[])
    migrate_scan.add_argument("--dry-run", action="store_true", default=True)
    migrate_export = migrate_subs.add_parser("export-shadow")
    migrate_export.add_argument("--profile", default="sannai")
    migrate_export.add_argument("--hermes-home", required=True)
    migrate_export.add_argument("--state-root", action="append", default=[])
    migrate_export.add_argument("--out", required=True)
    migrate_export.add_argument("--redacted", action="store_true")
    migrate_export.add_argument("--include-private-bodies", action="store_true")
    migrate_export.add_argument("--dry-run", action="store_true")
    migrate_import = migrate_subs.add_parser("import-shadow")
    migrate_import.add_argument("--bundle", required=True)
    migrate_import.add_argument("--profile", default="sannai-shadow")
    migrate_import.add_argument("--hermes-home", required=True)
    migrate_import.add_argument("--apply", action="store_true")
    migrate_replay = migrate_subs.add_parser("replay")
    migrate_replay.add_argument("--profile", default="sannai-shadow")
    migrate_replay.add_argument("--hermes-home", required=True)
    migrate_replay.add_argument("--no-adapter-export", action="store_true", default=True)
    migrate_replay.add_argument("--apply", action="store_true")
    migrate_diff = migrate_subs.add_parser("diff")
    migrate_diff.add_argument("--source-report", required=True)
    migrate_diff.add_argument("--target-root", required=True)
    migrate_diff.add_argument("--profile", default="sannai-shadow")


def memory_os_command(args: argparse.Namespace) -> int:
    if args.memory_os_command == "migrate":
        return _migrate_command(args)
    if args.memory_os_command == "export-shadow":
        roots = MemoryOSRoots.from_hermes_home(
            args.hermes_home,
            profile=args.profile,
            external_state_roots=args.state_root,
        )
        print(
            json.dumps(
                export_shadow_bundle(
                    roots,
                    out_path=args.out,
                    include_private_bodies=args.include_private_bodies,
                    dry_run=args.dry_run,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    store = MemoryOSStore(
        MemoryOSRoots.from_hermes_home(
            _active_hermes_home(args),
            profile=getattr(args, "profile", ""),
            external_state_roots=getattr(args, "state_root", []),
        )
    )
    command = args.memory_os_command
    if command == "cron-mirror":
        return _cron_mirror_command(args, store)
    if command == "session-mirror":
        return _session_mirror_command(args, store)
    if command == "state-source-mirror":
        return _state_source_mirror_command(args, store)
    if command == "shadow-journal":
        return _shadow_journal_command(args, store)
    if command == "conversation-regression":
        return _conversation_regression_command(args)
    if command == "context-router":
        return _context_router_command(args, store)
    if command == "low-clue-recall":
        return _low_clue_recall_command(args, store)
    if command == "memory-sources":
        return _memory_sources_command(args, store)
    if command == "review":
        return _review_command(args, store)
    if command == "eval":
        return _eval_command(args)
    if command == "cognitive-loop":
        return _cognitive_loop_command(args, store)
    if command == "validate":
        report = _host_validation_report(store, no_send=bool(args.no_send), write_report=bool(args.write_report))
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if report.get("status") == "error" else 0
    if command == "modules":
        return _modules_command(args, store)
    if command == "status":
        print(json.dumps(build_status_report(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "doctor":
        result = build_doctor_result(store)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return int(result["exit_code"])
    if command == "heartbeat":
        result = MemoryOSRuntime(store).heartbeat(max_events=args.max_events)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "inspect":
        print(json.dumps(inspect_event(store, args.event_id, include_private=args.include_private), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "trace":
        print(json.dumps(trace_record(store, args.record_id, include_private=args.include_private), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "diff":
        print(json.dumps(diff_report(store, since=args.since, until=args.until), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "approval-report":
        print(json.dumps(approval_report(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "benchmark":
        print(
            json.dumps(
                benchmark_report(
                    store,
                    record_count=args.records,
                    seed=args.seed,
                    large_opt_in=args.large_opt_in,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "cleanup":
        print(
            json.dumps(
                cleanup_report(
                    store,
                    policy=CleanupPolicy(
                        quarantine_retention_days=args.quarantine_days,
                        import_retention_days=args.import_days,
                        benchmark_retention_days=args.benchmark_days,
                        temp_retention_days=args.temp_days,
                        event_retention_days_by_source_class=_parse_event_source_class_retention(
                            args.event_source_class_retention
                        ),
                    ),
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "metadata-retention":
        print(
            json.dumps(
                metadata_retention_plan(
                    store.roots,
                    policy=MetadataRetentionPolicy(
                        memory_sources_retention_days=max(int(args.memory_sources_days), 0),
                        feedback_retention_days=max(int(args.feedback_days), 0),
                        suggestion_retention_days=max(int(args.suggestion_days), 0),
                        eval_report_retention_days=max(int(args.eval_report_days), 0),
                        eval_report_keep_latest=max(int(args.eval_report_keep_latest), 0),
                        suggestion_report_retention_days=max(int(args.suggestion_report_days), 0),
                        suggestion_report_keep_latest=max(int(args.suggestion_report_keep_latest), 0),
                    ),
                    eval_report_root=args.eval_report_root or None,
                    suggestion_report_root=args.suggestion_report_root or None,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    return 2


def _parse_event_source_class_retention(values: list[str]) -> dict[str, int]:
    policy: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid event retention policy: {value}. Expected SOURCE_CLASS=DAYS")
        source_class, days_text = value.split("=", 1)
        source_class = source_class.strip().lower()
        if not source_class:
            raise SystemExit(f"Invalid event retention policy: {value}. Empty source class")
        try:
            days = int(days_text)
        except ValueError as exc:
            raise SystemExit(f"Invalid event retention days: {days_text}") from exc
        if days < 0:
            raise SystemExit(f"Invalid event retention days: {days_text}")
        policy[source_class] = days
    return policy


def _cron_mirror_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    mirror = CronMirror(store)
    command = args.cron_mirror_command
    if command == "status":
        print(json.dumps(mirror.status(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "doctor":
        result = mirror.doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if result["status"] == "error" else 0
    if command == "scan":
        dry_run = not bool(getattr(args, "apply", False))
        print(json.dumps(mirror.scan(dry_run=dry_run), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def _session_mirror_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    mirror = SessionMirror(store)
    command = args.session_mirror_command
    if command == "status":
        print(json.dumps(mirror.status(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "doctor":
        result = mirror.doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if result["status"] == "error" else 0
    if command == "scan":
        dry_run = not bool(getattr(args, "apply", False))
        print(json.dumps(mirror.scan(dry_run=dry_run), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def _state_source_mirror_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    mirror = StateSourceMirror(store)
    command = args.state_source_mirror_command
    if command == "status":
        print(json.dumps(mirror.status(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "doctor":
        result = mirror.doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if result["status"] == "error" else 0
    if command == "scan":
        dry_run = not bool(getattr(args, "apply", False))
        print(json.dumps(mirror.scan(dry_run=dry_run), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def _modules_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    command = args.modules_command
    if command == "status":
        print(json.dumps(_modules_status_report(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "doctor":
        report = _modules_doctor_report(store)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if any(finding["severity"] == "error" for finding in report["findings"]) else 0
    if command == "run-once":
        report = _modules_run_once_report(
            store,
            module_id=args.module,
            apply=bool(args.apply),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.get("status") != "error" else 2
    if command == "validate-no-send":
        print(json.dumps(_modules_validate_no_send_report(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "deep_reflection":
        return _modules_deep_reflection_command(args, store)
    return 2


def _cognitive_loop_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    runner = CognitiveLoopRunner(store)
    command = args.cognitive_loop_command
    if command == "status":
        print(json.dumps(runner.status(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "doctor":
        result = runner.doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if result.get("status") == "error" else 0
    if command == "history":
        result = {
            "schema_version": "memory-os.cognitive_loop_history.v0",
            "profile": store.roots.profile or "default",
            "limit": max(int(args.limit), 0),
            "records": runner.read_reports(limit=max(int(args.limit), 0)),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "run-once":
        result = runner.run_once(
            apply=bool(args.apply),
            test_host=bool(args.test_host),
            max_events=int(args.max_events),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.get("status") != "error" else 2
    return 2


def _memory_sources_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    command = args.memory_sources_command
    if command == "last":
        print(json.dumps(memory_sources_last_report(store.roots), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "history":
        print(
            json.dumps(
                memory_sources_history_report(store.roots, limit=max(int(args.limit), 0)),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "stats":
        print(
            json.dumps(
                memory_sources_stats_report(store.roots, hours=max(int(args.hours), 0)),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "feedback":
        feedback_command = args.memory_sources_feedback_command
        if feedback_command == "last":
            report = memory_sources_feedback_last_report(
                store.roots,
                rating=args.rating,
                note=getattr(args, "note", ""),
            )
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if report.get("status") == "ok" else 1
        if feedback_command == "history":
            print(
                json.dumps(
                    memory_sources_feedback_history_report(store.roots, limit=max(int(args.limit), 0)),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
    return 2


def _review_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    command = args.review_command
    if command == "status":
        print(json.dumps(owner_review_status_report(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "aging-report":
        print(json.dumps(owner_review_aging_report(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "channel":
        print(json.dumps(resolve_owner_review_channel(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "cron-status":
        print(json.dumps(owner_review_cron_integration_report(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "delivery-status":
        print(json.dumps(owner_review_delivery_status_report(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "delivery-gate":
        print(
            json.dumps(
                owner_review_delivery_gate_report(store, owner_id=args.owner),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "deliver-once":
        report = deliver_owner_review_digest_once(
            store,
            owner_id=args.owner,
            delivery_key=args.delivery_key,
            owner_triggered=bool(args.owner_triggered),
            apply=bool(args.apply),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.get("status") in {"ready", "smoke_only", "sent", "skipped", "duplicate_ignored"} else 1
    if command == "queue":
        print(
            json.dumps(
                owner_review_queue_report(store, limit=max(int(args.limit), 0)),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "surface":
        print(
            json.dumps(
                owner_review_surface_report(
                    store,
                    owner_id=str(args.owner),
                    channel=str(args.channel),
                    operation=str(args.operation),
                    section=str(args.section),
                    anchor=str(args.anchor),
                    action_token=str(args.action_token),
                    offset=int(args.offset),
                    limit=int(args.limit),
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "proposal-followups":
        if bool(getattr(args, "ops_gate", False)):
            report = route_approved_proposal_followup_to_ops_gate(
                store,
                proposal_id=str(args.proposal_id),
                owner_id=str(args.owner),
                channel=str(args.channel),
                apply=bool(args.apply),
            )
            print(
                json.dumps(
                    report,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if report.get("status") in {"ok", "duplicate_ignored"} else 1
        print(
            json.dumps(
                approved_proposal_followups_report(store, limit=max(int(args.limit), 0)),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "preview-digest":
        print(
            json.dumps(
                owner_review_digest_preview(
                    store,
                    owner_id=args.owner,
                    max_action_required=args.max_action_required,
                    max_review_suggested=args.max_review_suggested,
                    max_fyi=args.max_fyi,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "render-digest":
        report = render_owner_review_digest(
            store,
            owner_id=args.owner,
            channel=args.channel,
            max_action_required=args.max_action_required,
            max_review_suggested=args.max_review_suggested,
            max_fyi=args.max_fyi,
            record_active=bool(args.record_active),
        )
        if args.format == "text":
            print(report["text"])
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "reply":
        report = parse_owner_review_reply(
            store,
            " ".join(args.reply),
            owner_id=args.owner,
            channel=args.channel,
            digest_id=args.digest_id,
            apply=bool(args.apply),
            max_action_required=args.max_action_required,
            max_review_suggested=args.max_review_suggested,
            max_fyi=args.max_fyi,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.get("status") in {"ok", "needs_clarification", "unsupported"} else 1
    if command == "apply":
        report = apply_owner_action(
            store,
            action_type=args.action,
            target=args.target,
            owner_id=args.owner,
            channel=args.channel,
            note=args.note,
            rating=args.rating,
            apply=bool(args.apply),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.get("status") in {"ok", "duplicate_ignored"} else 1
    return 2


def _host_validation_report(store: MemoryOSStore, *, no_send: bool, write_report: bool) -> dict[str, Any]:
    status = build_status_report(store)
    doctor = build_doctor_result(store)
    modules_status = _modules_status_report(store)
    modules_doctor = _modules_doctor_report(store)
    no_send_report = _modules_validate_no_send_report(store)
    deep_reflection_status = _module_status_by_id(modules_status, "deep_reflection")
    config = load_config(store.roots.hermes_home)
    report = {
        "schema_version": "memory-os.host_validation.v0",
        "profile": store.roots.profile or "default",
        "root": str(store.roots.memory_os_root),
        "mode": "no-send" if no_send else "status-only",
        "status": "ok",
        "provider_status": _bounded_module_payload(status),
        "provider_doctor": _bounded_module_payload(doctor),
        "modules_status": _bounded_module_payload(modules_status),
        "modules_doctor": _bounded_module_payload(modules_doctor),
        "deep_reflection_status": _bounded_module_payload(deep_reflection_status),
        "context_router": _bounded_module_payload(config.get("context_router", {})),
        "boundaries": no_send_report["boundaries"],
        "report_written": False,
        "report_path": "",
    }
    if doctor["status"] == "fail" or modules_doctor["status"] == "error":
        report["status"] = "error"
    elif doctor.get("findings") or modules_doctor.get("findings"):
        report["status"] = "warning"
    if write_report:
        path = _write_host_validation_report(store, report)
        report["report_written"] = True
        report["report_path"] = str(path)
    return report


def _module_status_by_id(modules_status: dict[str, Any], module_id: str) -> dict[str, Any]:
    for item in modules_status.get("modules", []):
        if isinstance(item, dict) and item.get("module") == module_id:
            return item
    return {"module": module_id, "status_available": False}


def _write_host_validation_report(store: MemoryOSStore, report: dict[str, Any]) -> Path:
    root = store.roots.memory_os_root / "system-modules" / "validation"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = root / f"validation_{stamp}.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _modules_status_report(store: MemoryOSStore) -> dict[str, Any]:
    modules = []
    for definition in _module_definitions():
        entry = _module_status_entry(store, definition)
        entry.pop("_instance", None)
        modules.append(entry)
    return {
        "schema_version": "memory-os.modules_status.v0",
        "profile": store.roots.profile or "default",
        "root": str(store.roots.memory_os_root),
        "module_count": len(modules),
        "modules": modules,
    }


def _modules_doctor_report(store: MemoryOSStore) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    module_reports: list[dict[str, Any]] = []
    for definition in _module_definitions():
        entry = _module_status_entry(store, definition)
        module_reports.append(entry)
        if not entry["status_available"]:
            findings.append(
                {
                    "severity": "warning",
                    "code": "module_status_unavailable",
                    "module": definition["module"],
                    "message": entry["unavailable_reason"],
                }
            )
            continue
        doctor = _module_doctor(store, definition["module"], entry["_instance"])
        entry.pop("_instance", None)
        if isinstance(doctor, dict):
            module_reports[-1]["doctor"] = _bounded_module_payload(doctor)
            for finding in doctor.get("findings", []) if isinstance(doctor.get("findings", []), list) else []:
                if isinstance(finding, dict):
                    finding = dict(finding)
                    finding.setdefault("module", definition["module"])
                    if (
                        not definition.get("runner")
                        and finding.get("severity") == "error"
                        and finding.get("code") == "missing_required_runtime_dependency"
                    ):
                        finding["severity"] = "warning"
                    findings.append(finding)
    for entry in module_reports:
        entry.pop("_instance", None)
    status = "ok"
    if any(finding.get("severity") == "error" for finding in findings):
        status = "error"
    elif findings:
        status = "warning"
    return {
        "schema_version": "memory-os.modules_doctor.v0",
        "profile": store.roots.profile or "default",
        "status": status,
        "module_count": len(module_reports),
        "modules": module_reports,
        "findings": findings,
    }


def _module_doctor(store: MemoryOSStore, module_id: str, instance: Any) -> Any:
    if module_id == "self_evolution":
        return instance.doctor(
            ops_gate=_ops_gate_module(store),
            proposal_queue=_proposal_queue_module(store),
            evidence_scoring=_evidence_scoring_module(store),
        )
    return _call_module_method(instance, "doctor", store=store)


def _modules_run_once_report(store: MemoryOSStore, *, module_id: str, apply: bool) -> dict[str, Any]:
    definition = _module_definition(module_id)
    if definition is None:
        return {
            "schema_version": "memory-os.modules_run_once.v0",
            "status": "error",
            "code": "unknown_module",
            "module": module_id,
        }
    if not definition.get("runner"):
        return {
            "schema_version": "memory-os.modules_run_once.v0",
            "status": "error",
            "code": "module_not_commandized",
            "module": module_id,
            "message": str(definition.get("unavailable_reason", "Module run-once is not commandized.")),
        }
    if apply:
        return {
            "schema_version": "memory-os.modules_run_once.v0",
            "status": "error",
            "code": "apply_not_enabled",
            "module": module_id,
            "message": "Module run-once apply requires a separate reviewed apply path.",
        }
    try:
        instance = _instantiate_module(store, definition)
        result = _run_module_dry_run(store, module_id, instance)
    except Exception as exc:
        return {
            "schema_version": "memory-os.modules_run_once.v0",
            "status": "error",
            "code": "module_run_failed",
            "module": module_id,
            "error": str(exc),
        }
    if isinstance(result, dict):
        result = dict(result)
        result.setdefault("schema_version", "memory-os.modules_run_once.v0")
        result.setdefault("module", module_id)
        result.setdefault("status", "ok")
        result["dry_run"] = True
        return _bounded_module_payload(result)
    return {
        "schema_version": "memory-os.modules_run_once.v0",
        "status": "ok",
        "module": module_id,
        "dry_run": True,
        "result": str(result),
    }


def _modules_validate_no_send_report(store: MemoryOSStore) -> dict[str, Any]:
    boundaries = {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_crystallized_approval": False,
        "hindsight_exported": False,
    }
    return {
        "schema_version": "memory-os.modules_no_send_validation.v0",
        "profile": store.roots.profile or "default",
        "status": "ok",
        "boundaries": boundaries,
        "candidate_count": len(read_candidate_queue(store)),
        "crystallized_record_count": _crystallized_record_file_count(store),
    }


def _crystallized_record_file_count(store: MemoryOSStore) -> int:
    if not store.roots.crystallized_root.exists():
        return 0
    return len([path for path in store.roots.crystallized_root.glob("*.md") if path.is_file()])


def _modules_deep_reflection_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    module = _deep_reflection_module(store)
    command = args.deep_reflection_command
    if command == "preview-current":
        report = module.preview_injection()
        report = _bounded_module_payload(report)
        if isinstance(report, dict):
            report["status"] = "ok" if int(report.get("selected_injection_count", 0)) else "no_active_card"
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "history":
        report = _deep_reflection_history_report(module, days=max(int(args.days), 0))
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def _deep_reflection_history_report(module: Any, *, days: int) -> dict[str, Any]:
    history_path = module.module_root / "injection" / "history.jsonl"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records: list[dict[str, Any]] = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_timestamp(str(record.get("ts", "")))
            if ts is not None and ts < cutoff:
                continue
            records.append(_bounded_module_payload(record))
    return {
        "schema_version": "hermes.deep_reflection_history.v0",
        "module": "deep_reflection",
        "profile": module.profile,
        "days": days,
        "record_count": len(records),
        "records": records[-50:],
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_crystallized_approval": False,
    }


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _module_status_entry(store: MemoryOSStore, definition: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "module": definition["module"],
        "kind": definition["kind"],
        "package": definition["package"],
        "commandized": bool(definition.get("runner")),
        "run_once_available": bool(definition.get("runner")),
        "status_available": False,
        "unavailable_reason": str(definition.get("unavailable_reason", "")),
    }
    try:
        instance = _instantiate_module(store, definition)
        status = _call_module_method(instance, "status", store=store)
    except Exception as exc:
        entry["unavailable_reason"] = str(exc)
        return entry
    entry["status_available"] = isinstance(status, dict)
    entry["status"] = _bounded_module_payload(status) if isinstance(status, dict) else {}
    if definition["module"] == "inner_drive" and isinstance(entry["status"], dict):
        entry["status"]["runtime_heartbeat"] = _heartbeat_runtime_status(store)
    if definition["module"] == "self_evolution" and isinstance(entry["status"], dict):
        entry["status"]["dependency_context"] = "standalone status reads reports; doctor injects loop dependencies"
    entry["_instance"] = instance
    if not entry["commandized"] and not entry["unavailable_reason"]:
        entry["unavailable_reason"] = "run_once_not_commandized"
    return entry


def _heartbeat_runtime_status(store: MemoryOSStore) -> dict[str, Any]:
    path = store.roots.memory_os_root / "runtime" / "heartbeat_state.json"
    if not path.exists():
        return {
            "schema_version": "memory-os.heartbeat_runtime_status.v0",
            "exists": False,
            "processed_event_count": 0,
            "last_processed_event_id": "",
            "source": "memory-os/runtime/heartbeat_state.json",
        }
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "memory-os.heartbeat_runtime_status.v0",
            "exists": True,
            "status": "error",
            "error": str(exc),
            "source": "memory-os/runtime/heartbeat_state.json",
        }
    return {
        "schema_version": "memory-os.heartbeat_runtime_status.v0",
        "exists": True,
        "last_heartbeat_at": str(document.get("last_heartbeat_at") or ""),
        "last_attempt_at": str(document.get("last_attempt_at") or ""),
        "processed_event_count": int(document.get("processed_event_count") or 0),
        "last_processed_event_id": str(document.get("last_processed_event_id") or ""),
        "source": "memory-os/runtime/heartbeat_state.json",
    }


def _module_definition(module_id: str) -> dict[str, Any] | None:
    for definition in _module_definitions():
        if definition["module"] == module_id:
            return definition
    return None


def _module_definitions() -> list[dict[str, Any]]:
    return [
        {
            "module": "cron_mirror",
            "kind": "mirror",
            "package": "plugins.memory.memory_os.cron_mirror",
            "factory": lambda store: CronMirror(store),
            "runner": "scan",
        },
        {
            "module": "session_mirror",
            "kind": "mirror",
            "package": "plugins.memory.memory_os.session_mirror",
            "factory": lambda store: SessionMirror(store),
            "runner": "scan",
        },
        {
            "module": "state_source_mirror",
            "kind": "mirror",
            "package": "plugins.memory.memory_os.state_source_mirror",
            "factory": lambda store: StateSourceMirror(store),
            "runner": "scan",
        },
        {
            "module": "shadow_journal",
            "kind": "ingestion",
            "package": "plugins.memory.memory_os.shadow_journal",
            "factory": lambda store: ShadowJournalIngestion(store),
            "runner": "ingest",
        },
        {
            "module": "deep_reflection",
            "kind": "cognition",
            "package": "plugins.modules.cognition.deep_reflection",
            "factory": _deep_reflection_module,
            "runner": "run_once",
        },
        {
            "module": "governance_feedback",
            "kind": "governance",
            "package": "plugins.modules.governance.feedback_bridge",
            "factory": _governance_feedback_module,
            "runner": "run_once",
        },
        {
            "module": "left_brain_pipeline_check",
            "kind": "governance",
            "package": "plugins.modules.governance.pipeline_checker",
            "factory": _left_brain_pipeline_check_module,
            "runner": "run_once",
        },
        {
            "module": "digest_consolidation",
            "kind": "context",
            "package": "plugins.modules.context.digest_consolidation",
            "factory": _digest_consolidation_module,
            "runner": "",
            "unavailable_reason": "daily and weekly commands are not wired to modules run-once yet",
        },
        {
            "module": "inner_drive",
            "kind": "cognition",
            "package": "plugins.modules.cognition.inner_drive",
            "factory": _inner_drive_module,
            "runner": "",
            "unavailable_reason": "inner_drive run_once mutates working/candidates and is not exposed through generic dry-run",
        },
        {
            "module": "mailbox",
            "kind": "messaging",
            "package": "plugins.modules.messaging.mailbox",
            "factory": _mailbox_module,
            "runner": "",
            "unavailable_reason": "mailbox run_once is not commandized in v0.1",
        },
        {
            "module": "household_digest",
            "kind": "context",
            "package": "plugins.modules.context.household_digest",
            "factory": _household_digest_module,
            "runner": "",
            "unavailable_reason": "household_digest run_once writes artifacts and is not exposed through generic dry-run",
        },
        {
            "module": "wandering_mind",
            "kind": "cognition",
            "package": "plugins.modules.cognition.wandering_mind",
            "factory": _wandering_mind_module,
            "runner": "",
            "unavailable_reason": "wandering_mind run_once records would-send artifacts and is not exposed through generic dry-run",
        },
        {
            "module": "evidence_scoring",
            "kind": "evidence",
            "package": "plugins.modules.evidence.scoring",
            "factory": _evidence_scoring_module,
            "runner": "",
            "unavailable_reason": "evidence_scoring score_all writes artifacts and is not exposed through generic dry-run",
        },
        {
            "module": "ops_gate",
            "kind": "governance",
            "package": "plugins.modules.governance.ops_gate",
            "factory": _ops_gate_module,
            "runner": "",
            "unavailable_reason": "ops_gate run_once needs proposed actions and is not exposed through generic dry-run",
        },
        {
            "module": "proposal_queue",
            "kind": "governance",
            "package": "plugins.modules.governance.proposal_queue",
            "factory": _proposal_queue_module,
            "runner": "",
            "unavailable_reason": "proposal_queue mutation commands are not exposed through generic dry-run",
        },
        {
            "module": "self_evolution",
            "kind": "governance",
            "package": "plugins.modules.governance.self_evolution",
            "factory": _self_evolution_module,
            "runner": "",
            "unavailable_reason": "self_evolution requires ops/evidence/proposal dependencies and is not exposed through generic dry-run",
        },
        {
            "module": "speak_gate",
            "kind": "expression",
            "package": "plugins.modules.expression.speak_gate",
            "factory": _speak_gate_module,
            "runner": "",
            "unavailable_reason": "speak_gate run_once requires outbound payload input and is not exposed through generic dry-run",
        },
        {
            "module": "expression_draft",
            "kind": "expression",
            "package": "plugins.modules.expression.expression_draft",
            "factory": _expression_draft_module,
            "runner": "",
            "unavailable_reason": "expression_draft creates drafts only from bounded module inputs",
        },
    ]


def _instantiate_module(store: MemoryOSStore, definition: dict[str, Any]) -> Any:
    _ensure_system_module_runtime_path(store.roots.hermes_home)
    factory = definition["factory"]
    return factory(store)


def _ensure_system_module_runtime_path(hermes_home: str | Path) -> None:
    runtime_python = Path(hermes_home).expanduser().resolve() / "memory-os" / "runtime" / "python"
    if runtime_python.exists() and str(runtime_python) not in sys.path:
        sys.path.insert(0, str(runtime_python))
    _extend_loaded_package_path("plugins", runtime_python / "plugins")
    _extend_loaded_package_path("plugins.memory", runtime_python / "plugins" / "memory")


def _extend_loaded_package_path(package_name: str, package_path: Path) -> None:
    loaded_package = sys.modules.get(package_name)
    if package_path.exists() and loaded_package is not None and hasattr(loaded_package, "__path__"):
        package_paths = loaded_package.__path__  # type: ignore[attr-defined]
        if str(package_path) not in package_paths:
            package_paths.append(str(package_path))


def _run_module_dry_run(store: MemoryOSStore, module_id: str, instance: Any) -> Any:
    if module_id in {"cron_mirror", "session_mirror", "state_source_mirror"}:
        return instance.scan(dry_run=True)
    if module_id == "shadow_journal":
        return instance.ingest(dry_run=True)
    if module_id == "deep_reflection":
        return instance.run_once(store=store, dry_run=True)
    if module_id == "governance_feedback":
        return instance.run_once(store=store, dry_run=True)
    if module_id == "left_brain_pipeline_check":
        return instance.run_once(store=store, write=False)
    raise ValueError(f"Module is not commandized: {module_id}")


def _call_module_method(instance: Any, method_name: str, *, store: MemoryOSStore) -> Any:
    method = getattr(instance, method_name)
    signature = inspect.signature(method)
    if "store" in signature.parameters:
        return method(store=store)
    return method()


def _bounded_module_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            str(key): _bounded_module_payload(value)
            for key, value in payload.items()
            if str(key) not in _PRIVATE_SAFE_REF_KEYS
        }
    if isinstance(payload, list):
        return [_bounded_module_payload(value) for value in payload[:20]]
    if isinstance(payload, str) and len(payload) > 500:
        return payload[:500] + "...[truncated]"
    return payload


def _deep_reflection_module(store: MemoryOSStore) -> Any:
    _ensure_system_module_runtime_path(store.roots.hermes_home)
    from plugins.modules.cognition.deep_reflection import DeepReflectionModule

    return DeepReflectionModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _governance_feedback_module(store: MemoryOSStore) -> Any:
    from plugins.modules.governance.feedback_bridge import GovernanceFeedbackBridgeModule

    return GovernanceFeedbackBridgeModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _left_brain_pipeline_check_module(store: MemoryOSStore) -> Any:
    from plugins.modules.governance.pipeline_checker import LeftBrainPipelineCheckModule

    return LeftBrainPipelineCheckModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _digest_consolidation_module(store: MemoryOSStore) -> Any:
    from plugins.modules.context.digest_consolidation import DigestConsolidationModule

    return DigestConsolidationModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _inner_drive_module(store: MemoryOSStore) -> Any:
    from plugins.modules.cognition.inner_drive import InnerDriveRuntimeModule

    return InnerDriveRuntimeModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _mailbox_module(store: MemoryOSStore) -> Any:
    from plugins.modules.messaging.mailbox import MailboxNoSendModule

    return MailboxNoSendModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _household_digest_module(store: MemoryOSStore) -> Any:
    from plugins.modules.context.household_digest import HouseholdDigestModule

    return HouseholdDigestModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _wandering_mind_module(store: MemoryOSStore) -> Any:
    from plugins.modules.cognition.wandering_mind import WanderingMindModule

    return WanderingMindModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _evidence_scoring_module(store: MemoryOSStore) -> Any:
    from plugins.modules.evidence.scoring import EvidenceScoringModule

    return EvidenceScoringModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _ops_gate_module(store: MemoryOSStore) -> Any:
    from plugins.modules.governance.ops_gate import OpsGateModule

    return OpsGateModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _proposal_queue_module(store: MemoryOSStore) -> Any:
    from plugins.modules.governance.proposal_queue import ProposalQueueModule

    return ProposalQueueModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _self_evolution_module(store: MemoryOSStore) -> Any:
    from plugins.modules.governance.self_evolution import SelfEvolutionGovernorModule

    return SelfEvolutionGovernorModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _speak_gate_module(store: MemoryOSStore) -> Any:
    from plugins.modules.expression.speak_gate import SpeakGateModule

    return SpeakGateModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _expression_draft_module(store: MemoryOSStore) -> Any:
    from plugins.modules.expression.expression_draft import ExpressionDraftModule

    return ExpressionDraftModule(store.roots.hermes_home, profile=store.roots.profile or "default")


def _shadow_journal_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    ingestion = ShadowJournalIngestion(store)
    command = args.shadow_journal_command
    if command == "status":
        print(json.dumps(ingestion.status(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "doctor":
        result = ingestion.doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if result["status"] == "error" else 0
    if command == "ingest":
        dry_run = not bool(getattr(args, "apply", False))
        print(
            json.dumps(
                ingestion.ingest(dry_run=dry_run, max_records=args.max_records),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    return 2


def _conversation_regression_command(args: argparse.Namespace) -> int:
    command = args.conversation_regression_command
    if command == "prompts":
        print(json.dumps(prompt_set_report(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "status-tool-contract":
        print(json.dumps(status_tool_contract_report(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "evaluate":
        report = evaluate_transcript_file(args.transcript)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if report["status"] == "fail" else 0
    return 2


def _eval_command(args: argparse.Namespace) -> int:
    if args.eval_command != "rh31":
        return 2
    from eval.memory_os.runner.run import latest_failures, latest_summary, run_rh31_eval

    report_root = str(getattr(args, "report_root", "") or "").strip() or None
    if args.rh31_command == "run":
        try:
            summary = run_rh31_eval(
                fixture=str(getattr(args, "fixture", "synthetic") or "synthetic"),
                adapters=list(getattr(args, "adapter", []) or ["all"]),
                report_root=report_root,
                write_report=not bool(getattr(args, "no_write_report", False)),
                keep_latest=max(int(getattr(args, "keep_latest", 20) or 20), 0),
                retention_days=max(int(getattr(args, "retention_days", 30) or 30), 0),
            )
        except ValueError as exc:
            print(
                json.dumps(
                    {
                        "schema_version": "memory-os.rh31_summary.v0",
                        "status": "error",
                        "code": "rh31_invalid_request",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if summary.get("status") != "fail" else 1
    if args.rh31_command == "summary":
        report = latest_summary(report_root)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.get("status") != "error" else 1
    if args.rh31_command == "failures":
        report = latest_failures(report_root, failure_class=str(getattr(args, "failure_class", "") or ""))
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.get("status") != "error" else 1
    return 2


def _context_router_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    if args.context_router_command == "dry-run":
        print(
            json.dumps(
                build_context_router_report(
                    args.query,
                    budget_chars=args.budget,
                    store=store,
                    index=MemoryOSIndex(store.roots),
                    current_task_anchor=args.current_task_anchor,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    return 2


def _low_clue_recall_command(args: argparse.Namespace, store: MemoryOSStore) -> int:
    if args.low_clue_recall_command == "dry-run":
        config = load_config(store.roots.hermes_home).get("low_clue_recall")
        if args.llm_judge == "none":
            config = _low_clue_recall_cli_config(config, llm_enabled=False, mode="none")
        elif args.llm_judge == "report-only":
            config = _low_clue_recall_cli_config(config, llm_enabled=True, mode="report_only")
        print(
            json.dumps(
                build_low_clue_recall_report(
                    args.query,
                    store=store,
                    limit=max(int(args.limit), 1),
                    config=config,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    return 2


def _low_clue_recall_cli_config(config: Any, *, llm_enabled: bool, mode: str) -> dict[str, Any]:
    source = dict(config) if isinstance(config, dict) else {}
    source["enabled"] = True
    judge = dict(source.get("llm_judge") if isinstance(source.get("llm_judge"), dict) else {})
    judge["enabled"] = llm_enabled
    judge["mode"] = mode
    judge.setdefault("provider", "hermes_default")
    judge.setdefault("model", None)
    source["llm_judge"] = judge
    return source


def _migrate_command(args: argparse.Namespace) -> int:
    command = args.migrate_command
    if command == "scan":
        roots = _source_roots_from_args(args)
        print(json.dumps(migration_scan_report(roots, dry_run=args.dry_run), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "export-shadow":
        roots = _source_roots_from_args(args)
        print(
            json.dumps(
                export_shadow_bundle(
                    roots,
                    out_path=args.out,
                    include_private_bodies=args.include_private_bodies and not args.redacted,
                    dry_run=args.dry_run,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "import-shadow":
        roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=args.profile)
        print(
            json.dumps(
                import_shadow_bundle(args.bundle, roots, dry_run=not args.apply),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "replay":
        roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=args.profile)
        print(
            json.dumps(
                replay_shadow_import(roots, dry_run=not args.apply, no_adapter_export=args.no_adapter_export),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "diff":
        roots = _target_roots_from_arg(args.target_root, profile=args.profile)
        print(json.dumps(migration_diff_report(args.source_report, roots), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def _source_roots_from_args(args: argparse.Namespace) -> MemoryOSRoots:
    return MemoryOSRoots.from_hermes_home(
        args.hermes_home,
        profile=args.profile,
        external_state_roots=args.state_root,
    )


def _active_hermes_home(args: argparse.Namespace) -> str:
    value = getattr(args, "hermes_home", "")
    if value:
        return str(value)
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        return env_home
    try:
        from hermes_constants import get_hermes_home

        return str(get_hermes_home())
    except Exception:
        return str(Path.home() / ".hermes")


def _target_roots_from_arg(target_root: str, *, profile: str) -> MemoryOSRoots:
    path = Path(target_root).expanduser().resolve()
    hermes_home = path.parent if path.name == "memory-os" else path
    return MemoryOSRoots.from_hermes_home(hermes_home, profile=profile)


def _store_counts(store: MemoryOSStore) -> dict[str, int]:
    events = store.read_events()
    working_items = 0
    for path in sorted(store.roots.working_root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        working_items += len(document.get("items", []))
    crystallized_records = 0
    for path in sorted(store.roots.crystallized_root.glob("*.md")):
        crystallized_records += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip() == "---") // 2
    return {
        "events": len(events),
        "working_items": working_items,
        "crystallized_candidates": len(read_candidate_queue(store.roots)),
        "crystallized_records": crystallized_records,
        "audit_entries": len(read_audit_entries(store.roots.audit_path)),
    }


def _indexed_counts_subset(counts: dict[str, int]) -> dict[str, int]:
    return {key: counts.get(key, 0) for key in ("events", "working_items", "crystallized_records")}


def _prefetch_mode(store: MemoryOSStore) -> str:
    if not store.roots.index_path.exists():
        return "degraded_filesystem"
    try:
        with sqlite3.connect(store.roots.index_path) as conn:
            conn.execute("select count(*) from events").fetchone()
    except sqlite3.Error:
        return "degraded_filesystem"
    return "indexed"


def _index_health_summary(
    store: MemoryOSStore,
    store_counts: dict[str, int],
    index_counts: dict[str, int],
) -> dict[str, Any]:
    if not store.roots.index_path.exists():
        return {"state": "missing", "fts_tokenizer": ""}
    findings = _index_health_findings(store, store_counts, index_counts)
    if any(finding["severity"] == "error" for finding in findings):
        state = "mismatch"
    elif any(finding["id"] == "index_stale" for finding in findings):
        state = "stale"
    else:
        state = "healthy"
    return {"state": state, "fts_tokenizer": _index_fts_tokenizer(store)}


def _index_fts_tokenizer(store: MemoryOSStore) -> str:
    try:
        with sqlite3.connect(store.roots.index_path) as conn:
            row = conn.execute("select value from index_metadata where key = ?", ("fts_tokenizer",)).fetchone()
    except sqlite3.Error:
        return ""
    return "" if row is None else str(row[0])


def _index_health_findings(
    store: MemoryOSStore,
    store_counts: dict[str, int],
    index_counts: dict[str, int],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    events = sorted(store.read_events(), key=lambda item: (item.ts, item.id))
    try:
        with sqlite3.connect(store.roots.index_path) as conn:
            conn.row_factory = sqlite3.Row
            indexed_events = conn.execute(
                """
                select id, ts, profile, source, kind, summary, promotion_state, sensitivity, record_hash
                from events
                order by ts, id
                """
            ).fetchall()
    except sqlite3.Error as exc:
        return [_finding("index_unreadable", "error", "SQLite index cannot be read.", {"error": str(exc)})]

    event_by_id = {event.id: event for event in events}
    for row in indexed_events:
        event = event_by_id.get(str(row["id"]))
        if event is None:
            findings.append(
                _finding(
                    "index_orphan_source",
                    "error",
                    "SQLite index references an event missing from the filesystem store.",
                    {"event_id": str(row["id"])},
                )
            )
            continue
        for field_name in ("ts", "profile", "source", "kind", "summary", "promotion_state", "sensitivity"):
            if str(row[field_name]) != str(getattr(event, field_name)):
                findings.append(
                    _finding(
                        "index_content_mismatch",
                        "error",
                        "SQLite index event row conflicts with the filesystem store.",
                        {"event_id": event.id, "field": field_name},
                    )
                )
                break
        indexed_hash = str(row["record_hash"])
        if indexed_hash and indexed_hash != _event_record_hash(event):
            findings.append(
                _finding(
                    "index_content_mismatch",
                    "error",
                    "SQLite index event hash conflicts with the filesystem store.",
                    {"event_id": event.id, "field": "record_hash"},
                )
            )

    if index_counts.get("events", 0) > store_counts.get("events", 0):
        findings.append(
            _finding(
                "index_count_mismatch",
                "error",
                "SQLite index has more events than the filesystem store.",
                {"store_counts": store_counts, "index_counts": index_counts},
            )
        )
    elif index_counts.get("events", 0) < store_counts.get("events", 0) and not _has_index_error(findings):
        findings.append(
            _finding(
                "index_stale",
                "warning",
                "SQLite index is behind append-only filesystem events and should catch up on heartbeat.",
                {"store_counts": store_counts, "index_counts": index_counts},
            )
        )

    for key in ("working_items", "crystallized_records"):
        if index_counts.get(key, 0) != store_counts.get(key, 0):
            findings.append(
                _finding(
                    "index_count_mismatch",
                    "error",
                    "SQLite index counts do not match filesystem store counts.",
                    {"store_counts": store_counts, "index_counts": index_counts, "count_key": key},
                )
            )
    return findings


def _has_index_error(findings: list[dict[str, Any]]) -> bool:
    return any(finding["severity"] == "error" and str(finding["id"]).startswith("index_") for finding in findings)


def _event_record_hash(event: Any) -> str:
    import hashlib

    payload = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity_source_findings(store: MemoryOSStore) -> list[dict[str, Any]]:
    path = store.roots.identity_manifest_path
    if not path.exists():
        return []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [_finding("identity_manifest_unreadable", "error", "Identity manifest cannot be read.", {"error": str(exc)})]
    findings: list[dict[str, Any]] = []
    for source in manifest.get("identity_sources", []):
        source_path = Path(str(source.get("path", "")))
        if not source_path.exists():
            findings.append(
                _finding(
                    "identity_source_missing",
                    "error",
                    "Identity source path is missing.",
                    {"kind": source.get("kind", ""), "path": str(source_path)},
                )
            )
    return findings


def _skipped_private_body_count(store: MemoryOSStore) -> int:
    count = 0
    for report_path in sorted(store.roots.imports_root.glob("*/import_report.json")):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        count += len(report.get("skipped_private_bodies", []))
    return count


def _finding(id_: str, severity: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": id_, "code": id_, "severity": severity, "message": message, "details": details or {}}


def _count_by(items: list[Any], attr: str) -> dict[str, int]:
    return _count_dict(str(getattr(item, attr)) for item in items)


def _count_dict(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _merge_counts(target: dict[str, int], source: dict[str, Any]) -> None:
    for key, value in source.items():
        target[str(key)] = target.get(str(key), 0) + int(value)
