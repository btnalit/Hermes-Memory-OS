"""Local diagnostic helpers for Memory-OS operator commands."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import types
from datetime import datetime
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
from .cron_mirror import CronMirror
from .crystallized import read_candidate_queue
from .index import MemoryOSIndex
from .migrator import (
    export_shadow_bundle,
    import_shadow_bundle,
    migration_diff_report,
    migration_scan_report,
    replay_shadow_import,
)
from .prefetch import continuity_selector_report
from .roots import MemoryOSRoots
from .runtime import MemoryOSRuntime
from .schema import EVENT_SCHEMA_VERSION, WORKING_SCHEMA_VERSION
from .session_mirror import SessionMirror
from .state_source_mirror import StateSourceMirror
from .store import MemoryOSStore
from .working import WorkingMemoryService


_PRIVATE_SAFE_REF_KEYS = {"raw_body", "body", "content", "transcript", "private_body", "raw_transcript"}


def build_status_report(store: MemoryOSStore) -> dict[str, Any]:
    events = store.read_events()
    store_counts = _store_counts(store)
    index_counts = MemoryOSIndex(store.roots).counts()
    prefetch_mode = _prefetch_mode(store)
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
        "hindsight_adapter_enabled": bool(load_config(store.roots.hermes_home).get("hindsight_adapter_enabled")),
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
