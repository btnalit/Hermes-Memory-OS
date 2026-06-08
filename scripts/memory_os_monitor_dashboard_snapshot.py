#!/usr/bin/env python3
"""Build a read-only snapshot for the Memory-OS monitoring dashboard.

The dashboard is a presentation surface. This helper reads bounded Memory-OS
evidence files and emits the `window.MOS` shape used by the static frontend.
It never approves, applies, sends, mutates cron, or appends monitor evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import socket
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.memory_os_module_cadence_report import build_cadence_report


SCHEMA_VERSION = "memory-os.monitor_dashboard_snapshot.v0"
DEFAULT_PROFILE = "main"
EXPECTED_CRON_NAMES = (
    "memory-os-owner-review-digest",
    "memory-os-right-brain-expression",
    "memory-os-module-cadence-report",
    "memory-os-right-brain-expression-outcome",
    "memory-os-proposal-followups-opsgate",
    "memory-os-expression-feedback-request",
    "memory-os-memory-sources-feedback-request",
)
BOUNDARY_ROWS = (
    ("actual_send", "Direct platform send", "blocked"),
    ("actual_execute", "External execution", "blocked"),
    ("actual_identity_write", "Identity write", "gated"),
    ("actual_unapproved_crystallized_approval", "Unapproved crystallize", "blocked"),
    ("ungoverned_hindsight_export", "Ungoverned Hindsight export", "blocked"),
    ("raw_turn_retain", "Raw-turn retain", "disabled"),
    ("cleanup_apply", "Cleanup apply", "gated"),
    ("shadow_journal_apply", "Shadow-journal apply", "gated"),
    ("cron_modified", "Cron mutation by MOS", "false"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE", DEFAULT_PROFILE))
    parser.add_argument("--output", type=Path, help="Write snapshot to this path. Defaults to stdout.")
    parser.add_argument("--format", choices=("js", "json"), default="js")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Use an empty synthetic profile path so the command can be smoke-tested without Hermes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hermes_home = Path("__memory_os_dashboard_sample__") if args.sample else Path(args.hermes_home)
    snapshot = build_dashboard_snapshot(
        hermes_home=hermes_home.expanduser().resolve(),
        profile=str(args.profile or DEFAULT_PROFILE),
    )
    output_text = render_snapshot(snapshot, output_format=args.format)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text)
    return 0


def render_snapshot(snapshot: dict[str, Any], *, output_format: str) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
    if output_format == "json":
        return payload + "\n"
    return "window.MOS = " + payload + ";\n"


def build_dashboard_snapshot(*, hermes_home: Path, profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    started_at = time.perf_counter()
    memory_root = hermes_home / "memory-os"
    status_report = _safe_status_report(hermes_home, memory_root, profile)
    cadence_report = build_cadence_report(hermes_home=hermes_home, profile=profile, apply=False)
    cron_jobs = _read_cron_jobs(hermes_home)
    owner = _owner_review_snapshot(memory_root)
    memory = _memory_snapshot(memory_root)
    expression = _expression_snapshot(hermes_home, memory_root)
    proposals = _proposal_snapshot(hermes_home, memory_root)
    hindsight = _hindsight_snapshot(hermes_home, memory_root, status_report)
    feedback = _feedback_snapshot(memory_root)
    boundary = _boundary_snapshot(cadence_report, status_report, hindsight)
    audit = _audit_snapshot(memory_root)
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    monitor = _monitor_snapshot(
        now=now,
        profile=profile,
        duration_ms=duration_ms,
        status_report=status_report,
        cadence_report=cadence_report,
        cron_jobs=cron_jobs,
        owner=owner,
        memory=memory,
        expression=expression,
        hindsight=hindsight,
        boundary=boundary,
    )
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "meta": _meta_snapshot(now, hermes_home, profile, status_report, cron_jobs, hindsight),
        "monitor": monitor,
        "kpis": _kpis_snapshot(memory, owner, cron_jobs, cadence_report, hindsight),
        "cron": _cron_snapshot(cron_jobs),
        "ownerReview": owner,
        "memory": memory,
        "modules": _modules_snapshot(cadence_report),
        "expression": expression,
        "proposals": proposals,
        "hindsight": hindsight,
        "feedback": feedback,
        "boundary": boundary,
        "audit": audit,
    }
    _fill_audit_from_monitor_if_empty(snapshot)
    return snapshot


def _meta_snapshot(
    now: datetime,
    hermes_home: Path,
    profile: str,
    status_report: dict[str, Any],
    cron_jobs: list[dict[str, Any]],
    hindsight: dict[str, Any],
) -> dict[str, Any]:
    version = _project_version()
    channel = _owner_channel(status_report) or _owner_channel_from_config(hermes_home) or "unknown"
    install_mode = "operational" if len([job for job in cron_jobs if job.get("enabled", True)]) >= 7 else "partial"
    host = _host_snapshot()
    return {
        "product": "Hermes · Memory-OS",
        "profile": profile,
        "hermes_home": str(hermes_home),
        "provider": "memory_os",
        "shell_plugin": "memory-os-agent-os",
        "install_mode": install_mode,
        "hindsight_mode": str(hindsight.get("mode") or "off"),
        "host": host["hostname"],
        "host_fqdn": host["fqdn"],
        "environment": host["environment"],
        "version": f"memory-os {version}",
        "monitor_build": "dashboard snapshot v0",
        "owner_channel": channel,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "uptime": host["uptime"],
        "uptime_seconds": host["uptime_seconds"],
    }


def _monitor_snapshot(
    *,
    now: datetime,
    profile: str,
    duration_ms: int,
    status_report: dict[str, Any],
    cadence_report: dict[str, Any],
    cron_jobs: list[dict[str, Any]],
    owner: dict[str, Any],
    memory: dict[str, Any],
    expression: dict[str, Any],
    hindsight: dict[str, Any],
    boundary: list[dict[str, str]],
) -> dict[str, Any]:
    missing_cron = len(set(EXPECTED_CRON_NAMES) - {str(job.get("name") or "") for job in cron_jobs})
    module_error = int(cadence_report.get("error_count") or 0)
    module_findings = int(cadence_report.get("finding_count") or 0)
    index_warn = 0 if memory.get("index_fresh") else 1
    boundary_warn = sum(1 for item in boundary if item["key"] == "cron_modified" and item["state"] != "false")
    sections = [
        {"key": "provider", "label": "Provider 核心", "checks": 6, "warn": 0 if status_report else 1, "fail": 0},
        {"key": "indexes", "label": "SQLite 索引", "checks": 5, "warn": index_warn, "fail": 0},
        {"key": "cron", "label": "Cron 作业", "checks": 7, "warn": missing_cron, "fail": 0},
        {
            "key": "owner_review",
            "label": "Owner 审批",
            "checks": 6,
            "warn": 1 if int(owner.get("counts", {}).get("action_required_shown") or 0) else 0,
            "fail": 0,
        },
        {"key": "modules", "label": "模块 cadence", "checks": 18, "warn": module_findings, "fail": module_error},
        {
            "key": "expression",
            "label": "Right-brain 表达",
            "checks": 5,
            "warn": 0 if int(expression.get("drafts") or 0) or int(expression.get("sent") or 0) else 1,
            "fail": 0,
        },
        {
            "key": "hindsight",
            "label": "Hindsight 投影",
            "checks": 5,
            "warn": 0 if hindsight.get("mode") in {"shadow", "active"} else 1,
            "fail": 0,
        },
        {"key": "boundary", "label": "Safety 边界", "checks": 9, "warn": boundary_warn, "fail": 0},
    ]
    checks_total = sum(int(item["checks"]) for item in sections)
    warn = sum(int(item["warn"]) for item in sections)
    fail = sum(int(item["fail"]) for item in sections)
    status = "FAIL" if fail else "WARN" if warn else "PASS"
    run_seed = f"{profile}:{now.isoformat()}:{checks_total}:{warn}:{fail}"
    return {
        "status": status,
        "run_id": "dash_" + hashlib.sha256(run_seed.encode("utf-8")).hexdigest()[:12],
        "schema": SCHEMA_VERSION,
        "checks_total": checks_total,
        "pass": max(checks_total - warn - fail, 0),
        "warn": warn,
        "fail": fail,
        "duration_ms": max(int(duration_ms), 0),
        "last_run_at": now.strftime("%H:%M:%S"),
        "last_run_ago": "just now",
        "next_run_in": _snapshot_refresh_label(),
        "sections": sections,
        "history": _status_history(status),
        "checks_trend": _flat_series(checks_total, 21),
    }


def _kpis_snapshot(
    memory: dict[str, Any],
    owner: dict[str, Any],
    cron_jobs: list[dict[str, Any]],
    cadence_report: dict[str, Any],
    hindsight: dict[str, Any],
) -> list[dict[str, Any]]:
    enabled_cron = len([job for job in cron_jobs if job.get("enabled", True)])
    modules = int(cadence_report.get("module_count") or 0)
    return [
        _kpi("working", "Working memory", "items", memory.get("working"), "+0", "flat"),
        _kpi("crystallized", "Crystallized", "approved", memory.get("crystallized"), "+0", "flat"),
        _kpi(
            "pending",
            "待 owner 审批",
            "oa_ tokens",
            owner.get("states", {}).get("pending"),
            "+0",
            "flat",
            good="down",
        ),
        _kpi("cron_ok", "Cron 健康", "enabled jobs", enabled_cron, "+0", "flat"),
        _kpi("modules", "活跃模块", "/ 18", modules, "+0", "flat"),
        _kpi("hindsight", "Hindsight 记录", "retained", hindsight.get("retained"), "+0", "flat"),
    ]


def _kpi(
    key: str,
    label: str,
    unit: str,
    value: Any,
    delta: str,
    direction: str,
    *,
    good: str | None = None,
) -> dict[str, Any]:
    item = {
        "key": key,
        "label": label,
        "unit": unit,
        "value": _safe_int(value),
        "delta": delta,
        "dir": direction,
        "spark": _flat_series(_safe_int(value), 21),
    }
    if good:
        item["good"] = good
    return item


def _cron_snapshot(cron_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    jobs = [_cron_job_snapshot(job) for job in cron_jobs]
    return {
        "enabled": sum(1 for job in cron_jobs if job.get("enabled", True)),
        "total": len(cron_jobs),
        "jobs": jobs,
    }


def _cron_job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    name = str(job.get("name") or job.get("id") or "unknown")
    enabled = bool(job.get("enabled", True))
    deliver = str(job.get("deliver") or job.get("delivery") or "local")
    agent_value = job.get("agent")
    if agent_value is None:
        agent_value = deliver not in {"local", "none", ""}
    return {
        "name": name,
        "deliver": deliver,
        "agent": bool(agent_value),
        "schedule": str(job.get("schedule") or ""),
        "last": str(job.get("last") or job.get("last_run_at") or "n/a"),
        "last_ms": _safe_int(job.get("last_ms") or job.get("duration_ms")),
        "next": str(job.get("next") or job.get("next_run_at") or "n/a"),
        "status": "ok" if enabled else "disabled",
        "out": str(job.get("out") or ""),
    }


def _owner_review_snapshot(memory_root: Path) -> dict[str, Any]:
    latest_digest = _latest_jsonl(memory_root / "system" / "owner_review_rendered_digests.jsonl")
    sections = latest_digest.get("sections") if isinstance(latest_digest.get("sections"), dict) else {}
    items = []
    for section_name, severity in (
        ("action_required", "action_required"),
        ("review_suggested", "review_suggested"),
        ("fyi", "fyi"),
    ):
        section_items = sections.get(section_name) if isinstance(sections.get(section_name), list) else []
        for item in section_items:
            if isinstance(item, dict):
                items.append(_owner_queue_item(item, severity))
    actions = _read_jsonl(memory_root / "system" / "owner_actions.jsonl")
    by_result = Counter(str(item.get("result") or item.get("status") or "") for item in actions)
    by_type = Counter(str(item.get("action_type") or "") for item in actions)
    return {
        "mode": str(latest_digest.get("digest_mode") or latest_digest.get("mode") or "agenda"),
        "counts": {
            "action_required_shown": len(sections.get("action_required") or []),
            "review_suggested_shown": len(sections.get("review_suggested") or []),
            "fyi_shown": len(sections.get("fyi") or []),
        },
        "states": {
            "pending": len(items),
            "approved": int(by_type.get("approve_candidate", 0)) + int(by_type.get("approve_proposal", 0)),
            "applied": int(by_type.get("apply_proposal", 0)) + int(by_result.get("applied", 0)),
            "rejected": int(by_type.get("reject_candidate", 0)) + int(by_type.get("reject_proposal", 0)),
            "allowed": int(by_type.get("allow_speak_once", 0)),
        },
        "queue": items[:12],
        "throughput": _flat_series(len(actions), 21),
    }


def _owner_queue_item(item: dict[str, Any], severity: str) -> dict[str, Any]:
    token = ""
    action_tokens = item.get("action_tokens") if isinstance(item.get("action_tokens"), dict) else {}
    if action_tokens:
        token = str(next(iter(action_tokens.values())) or "")
    return {
        "anchor": str(item.get("anchor") or ""),
        "token": token,
        "kind": str(item.get("target_type") or item.get("kind") or "review_item"),
        "surface": str(item.get("source") or item.get("surface") or "owner-home"),
        "age": _age_label(item.get("created_at")),
        "sev": severity,
        "state": "pending",
        "note": _bounded_text(item.get("summary") or item.get("question") or item.get("reason") or "", 120),
    }


def _memory_snapshot(memory_root: Path) -> dict[str, Any]:
    working_records = _count_files(memory_root / "working", "*.json")
    candidates = _read_jsonl(memory_root / "crystallized" / "candidates.jsonl")
    crystallized_records, classes = _crystallized_counts(memory_root / "crystallized")
    index_path = memory_root / "index" / "memory_os.db"
    fts_rows = _sqlite_count(index_path, "fts_entries") or _sqlite_count(index_path, "events")
    return {
        "working": working_records,
        "crystallized": crystallized_records,
        "candidates": len(candidates),
        "canonical_files": _count_files(memory_root, "*"),
        "index_mb": round(index_path.stat().st_size / (1024 * 1024), 1) if index_path.exists() else 0,
        "index_fresh": index_path.exists(),
        "index_rebuilt": _mtime_label(index_path),
        "fts_rows": fts_rows,
        "working_trend": _flat_series(working_records, 21),
        "crystallized_trend": _flat_series(crystallized_records, 21),
        "classes": _class_rows(classes),
    }


def _modules_snapshot(cadence_report: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for item in cadence_report.get("modules", []) if isinstance(cadence_report.get("modules"), list) else []:
        if not isinstance(item, dict):
            continue
        counters = item.get("cadence_counters") if isinstance(item.get("cadence_counters"), dict) else {}
        rows.append(
            {
                "module": str(item.get("module") or ""),
                "runner": str(item.get("current_runner") or ""),
                "cadence": str(item.get("target_cadence_class") or ""),
                "run": _safe_int(counters.get("run_count")),
                "gen": _safe_int(counters.get("generated_count")),
                "skip": _safe_int(counters.get("skipped_count")),
                "err": _safe_int(counters.get("error_count")),
                "dup": _safe_int(counters.get("duplicate_count")),
                "last": str(counters.get("last_status") or "missing"),
                "split": bool(item.get("production_split_recommended"))
                and not bool(item.get("module_local_skip_gate_visible")),
            }
        )
    return {
        "status": str(cadence_report.get("status") or "unknown"),
        "module_count": _safe_int(cadence_report.get("module_count")),
        "integration_harness_member_count": _safe_int(cadence_report.get("integration_harness_member_count")),
        "split_recommended_count": _safe_int(cadence_report.get("split_recommended_count")),
        "expected_hermes_cron_missing_count": _safe_int(cadence_report.get("expected_hermes_cron_missing_count")),
        "finding_count": _safe_int(cadence_report.get("finding_count")),
        "totals": {
            "generated_count": _safe_int(cadence_report.get("generated_count")),
            "skipped_count": _safe_int(cadence_report.get("skipped_count")),
            "error_count": _safe_int(cadence_report.get("error_count")),
            "duplicate_count": _safe_int(cadence_report.get("duplicate_count")),
            "counter_coverage_count": sum(1 for row in rows if row["run"] or row["gen"] or row["skip"] or row["err"]),
        },
        "rows": rows,
        "findings": cadence_report.get("findings") if isinstance(cadence_report.get("findings"), list) else [],
    }


def _expression_snapshot(hermes_home: Path, memory_root: Path) -> dict[str, Any]:
    modules = hermes_home / "system-modules"
    drafts = _read_jsonl(modules / "expression_draft" / "drafts.jsonl")
    would_send = _read_jsonl(modules / "speak_gate" / "would_send.jsonl")
    requests = _read_jsonl(modules / "right_brain_expression_adapter" / "requests.jsonl")
    outcomes = _read_jsonl(modules / "right_brain_expression_adapter" / "outcomes.jsonl")
    feedback_records = _read_jsonl(memory_root / "system" / "expression_feedback_ledger.jsonl")
    feedback_counts = Counter(str(item.get("rating") or item.get("action_type") or item.get("feedback") or "neutral") for item in feedback_records)
    silent = sum(1 for item in outcomes if "[SILENT]" in str(item.get("outcome_preview") or item.get("preview") or ""))
    sent = sum(1 for item in outcomes if str(item.get("status") or "") in {"sent", "ok"} or bool(item.get("actual_send")))
    return {
        "drafts": len(drafts),
        "would_send": len(would_send),
        "silent": silent,
        "sent": sent or len(requests),
        "outcomes_recorded": len(outcomes),
        "cadence_trend": _flat_series(len(outcomes) or len(requests), 21),
        "feedback": _feedback_tag_rows(feedback_counts),
    }


def _proposal_snapshot(hermes_home: Path, memory_root: Path) -> dict[str, Any]:
    self_evolution = _read_jsonl(hermes_home / "system-modules" / "self_evolution" / "reports.jsonl")
    ops_gate = _read_jsonl(hermes_home / "system-modules" / "ops_gate" / "reports.jsonl")
    proposal_actions = _read_jsonl(memory_root / "system" / "proposal_action_ledger.jsonl")
    action_types = Counter(str(item.get("action_type") or item.get("result") or item.get("status") or "") for item in proposal_actions)
    states = [
        {"label": "pending_followup", "value": len(self_evolution), "tone": "warn"},
        {"label": "in_opsgate_review", "value": len(ops_gate), "tone": "accent"},
        {"label": "report_only", "value": sum(1 for item in ops_gate if str(item.get("decision") or item.get("status") or "").startswith("report")), "tone": "muted"},
        {"label": "applied", "value": int(action_types.get("apply_proposal", 0)) + int(action_types.get("applied", 0)), "tone": "good"},
        {"label": "rejected", "value": int(action_types.get("reject_proposal", 0)) + int(action_types.get("rejected", 0)), "tone": "fail"},
    ]
    return {
        "states": states,
        "lanes": [
            {"lane": "report_only", "desc": "process motion · no execution", "count": states[2]["value"], "graduated": False},
            {"lane": "opsgate_review", "desc": "approved → bounded review", "count": states[1]["value"], "graduated": False},
            {"lane": "bounded_apply", "desc": "rollback + monitor + apply token", "count": states[3]["value"], "graduated": bool(states[3]["value"])},
        ],
    }


def _hindsight_snapshot(hermes_home: Path, memory_root: Path, status_report: dict[str, Any]) -> dict[str, Any]:
    status = status_report.get("hindsight_substrate") if isinstance(status_report.get("hindsight_substrate"), dict) else {}
    ledger = _read_jsonl(memory_root / "system" / "projection_ledger.jsonl")
    retained = [item for item in ledger if str(item.get("operation") or item.get("action") or "").lower().endswith("retain")]
    retracted = [item for item in ledger if "retract" in str(item.get("operation") or item.get("action") or "").lower() or "invalidate" in str(item.get("operation") or item.get("action") or "").lower()]
    recall_hits = sum(_safe_int(item.get("recall_hit_count") or item.get("hit_count")) for item in ledger)
    recall_mode = str(status.get("recall_mode") or "")
    mode = recall_mode if status.get("enabled") and recall_mode in {"shadow", "active"} else ("shadow" if retained else "off")
    raw_turn_retain = bool(status.get("substrate_monitor", {}).get("raw_retained_count")) if isinstance(status.get("substrate_monitor"), dict) else False
    return {
        "mode": mode,
        "retain_source": "crystallized · owner-approved · distilled",
        "raw_turn_retain": raw_turn_retain,
        "recall": "advisory · derived_projection",
        "retained": len(retained),
        "retracted": len(retracted),
        "ledger_entries": len(ledger),
        "advisory_recall_hits": recall_hits,
        "retained_trend": _flat_series(len(retained), 21),
        "recall_trend": _flat_series(recall_hits, 21),
    }


def _feedback_snapshot(memory_root: Path) -> dict[str, Any]:
    memory_source_records = _read_jsonl(memory_root / "system" / "memory_sources.jsonl")
    memory_feedback = _read_jsonl(memory_root / "system" / "memory_sources_feedback.jsonl")
    expression_feedback = _read_jsonl(memory_root / "system" / "expression_feedback_ledger.jsonl")
    return {
        "memory_sources": {
            "prompts": len(memory_source_records),
            "responses": len(memory_feedback),
            "attribution_quality": _ratio(len(memory_feedback), len(memory_source_records)),
        },
        "expression": {
            "prompts": len(expression_feedback),
            "responses": len(expression_feedback),
            "satisfaction": _positive_feedback_ratio(expression_feedback),
        },
        "quality_trend": _flat_series(_positive_feedback_ratio(memory_feedback + expression_feedback), 21),
    }


def _boundary_snapshot(cadence_report: dict[str, Any], status_report: dict[str, Any], hindsight: dict[str, Any]) -> list[dict[str, str]]:
    boundary = cadence_report.get("boundary") if isinstance(cadence_report.get("boundary"), dict) else {}
    rows = []
    for key, label, default_state in BOUNDARY_ROWS:
        state = default_state
        if key == "cron_modified":
            state = "true" if boundary.get("cron_modified") is True else "false"
        elif key == "raw_turn_retain":
            state = "enabled" if hindsight.get("raw_turn_retain") else "disabled"
        elif boundary.get(key) is True:
            state = "warn"
        rows.append({"key": key, "label": label, "state": state})
    return rows


def _audit_snapshot(memory_root: Path) -> list[dict[str, str]]:
    rows = []
    for record in _read_jsonl(memory_root / "audit" / "write_audit.jsonl")[-8:]:
        rows.append(
            {
                "t": _time_label(record.get("ts") or record.get("created_at")),
                "actor": str(record.get("actor") or "memory_os"),
                "action": str(record.get("action") or "audit.event"),
                "detail": _bounded_text(record.get("target") or record.get("status") or "", 160),
                "tone": _status_tone(str(record.get("status") or "")),
            }
        )
    return rows


def _fill_audit_from_monitor_if_empty(snapshot: dict[str, Any]) -> None:
    if snapshot.get("audit"):
        return
    mon = snapshot["monitor"]
    snapshot["audit"] = [
        {
            "t": mon["last_run_at"],
            "actor": "dashboard",
            "action": "snapshot.build",
            "detail": f"status={mon['status']} · {mon['checks_total']} checks · {mon['warn']} warn",
            "tone": _status_tone(mon["status"]),
        }
    ]


def _safe_status_report(hermes_home: Path, memory_root: Path, profile: str) -> dict[str, Any]:
    # Read only a bounded subset here. Importing the full CLI status path may
    # quarantine malformed records, so the dashboard avoids that side effect.
    counts = {
        "events": _count_files(memory_root / "events", "*.jsonl"),
        "working_items": _count_files(memory_root / "working", "*.json"),
        "crystallized_candidates": len(_read_jsonl(memory_root / "crystallized" / "candidates.jsonl")),
        "crystallized_records": _crystallized_counts(memory_root / "crystallized")[0],
    }
    index_path = memory_root / "index" / "memory_os.db"
    return {
        "schema_version": "memory-os.status.v0",
        "root": str(memory_root),
        "profile": profile,
        "counts": counts,
        "index_health": {"state": "healthy" if index_path.exists() else "missing"},
        "hindsight_substrate": _hindsight_config_status(hermes_home),
        "owner_review": {},
    }


def _hindsight_config_status(hermes_home: Path) -> dict[str, Any]:
    config = _read_json(hermes_home / "memory-os" / "config.json")
    substrate = {}
    if isinstance(config, dict):
        providers = config.get("substrate_providers") if isinstance(config.get("substrate_providers"), dict) else {}
        substrate = providers.get("hindsight") if isinstance(providers.get("hindsight"), dict) else {}
    legacy_provider = _legacy_memory_provider(hermes_home)
    enabled = bool(substrate.get("enabled"))
    recall_mode = str(substrate.get("recall_mode") or ("active" if legacy_provider == "hindsight" else "off"))
    return {
        "schema_version": "memory-os.hindsight_substrate_status.v0",
        "enabled": enabled,
        "status": "configured" if enabled else "optional_not_configured",
        "adoption_source": str(substrate.get("adoption_source") or ""),
        "provider_bank_id": str(substrate.get("provider_bank_id") or substrate.get("bank_id") or ""),
        "bank_selection_reason": str(substrate.get("bank_selection_reason") or ""),
        "recall_mode": recall_mode,
        "retain_enabled": bool(substrate.get("retain_enabled")),
        "reflect_enabled": bool(substrate.get("reflect_enabled")),
        "legacy_provider_was_hindsight": bool(substrate.get("legacy_provider_was_hindsight")) or legacy_provider == "hindsight",
        "legacy_auto_retain_observed_disabled": bool(substrate.get("legacy_auto_retain_observed_disabled")),
        "substrate_monitor": {},
    }


def _legacy_memory_provider(hermes_home: Path) -> str:
    config = _read_json(hermes_home / "config.yaml")
    if not isinstance(config, dict):
        return ""
    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    return str(memory.get("provider") or "")


def _host_snapshot() -> dict[str, Any]:
    hostname = (os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or socket.gethostname() or "").strip()
    fqdn = (socket.getfqdn() or hostname or "").strip()
    uptime_seconds = _read_uptime_seconds()
    return {
        "hostname": hostname or "unknown",
        "fqdn": fqdn or hostname or "unknown",
        "environment": os.environ.get("HERMES_ENV") or "host",
        "uptime": _format_uptime_seconds(uptime_seconds),
        "uptime_seconds": uptime_seconds,
    }


def _read_uptime_seconds(path: Path = Path("/proc/uptime")) -> int:
    try:
        text = path.read_text(encoding="utf-8").split()[0]
        return max(int(float(text)), 0)
    except (OSError, ValueError, IndexError):
        return 0


def _format_uptime_seconds(seconds: int) -> str:
    if seconds <= 0:
        return "unknown"
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    rem_hours = hours % 24
    rem_minutes = minutes % 60
    if days:
        return f"{days}d {rem_hours}h {rem_minutes}m"
    if hours:
        return f"{hours}h {rem_minutes}m"
    return f"{rem_minutes}m"


def _snapshot_refresh_label() -> str:
    try:
        seconds = int(os.environ.get("MOS_DASHBOARD_REFRESH_INTERVAL_SECONDS", "0") or "0")
    except ValueError:
        seconds = 0
    if seconds <= 0:
        return "manual"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h"


def _read_cron_jobs(hermes_home: Path) -> list[dict[str, Any]]:
    raw = _read_json(hermes_home / "cron" / "jobs.json")
    if isinstance(raw, list):
        jobs = raw
    elif isinstance(raw, dict) and isinstance(raw.get("jobs"), list):
        jobs = raw["jobs"]
    else:
        jobs = []
    return [job for job in jobs if isinstance(job, dict)]


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _read_simple_yaml(text)


def _read_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if not value:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _yaml_scalar(value)
    return result


def _yaml_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    return value.strip("'\"")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            records.append(loaded)
    return records


def _latest_jsonl(path: Path) -> dict[str, Any]:
    records = _read_jsonl(path)
    return records[-1] if records else {}


def _count_files(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for item in root.rglob(pattern) if item.is_file())


def _crystallized_counts(root: Path) -> tuple[int, Counter[str]]:
    classes: Counter[str] = Counter()
    count = 0
    if not root.exists():
        return count, classes
    for path in root.glob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        parts = text.split("---")
        for index in range(1, len(parts), 2):
            frontmatter = _frontmatter(parts[index])
            if frontmatter:
                count += 1
                classes[str(frontmatter.get("kind") or "unknown")] += 1
    return count, classes


def _frontmatter(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def _sqlite_count(path: Path, table: str) -> int:
    if not path.exists():
        return 0
    try:
        with sqlite3.connect(path) as conn:
            return int(conn.execute(f"select count(*) from {table}").fetchone()[0])
    except sqlite3.Error:
        return 0


def _class_rows(classes: Counter[str]) -> list[dict[str, Any]]:
    if not classes:
        return [{"label": label, "value": 0} for label in ("identity", "preference", "relationship", "procedure", "fact")]
    return [{"label": key, "value": value} for key, value in classes.most_common(5)]


def _feedback_tag_rows(counts: Counter[str]) -> list[dict[str, Any]]:
    if not counts:
        return [
            {"tag": "like_expression", "value": 0, "tone": "good"},
            {"tag": "resonant", "value": 0, "tone": "good"},
            {"tag": "neutral", "value": 0, "tone": "muted"},
            {"tag": "too_mechanistic", "value": 0, "tone": "warn"},
            {"tag": "off_tone", "value": 0, "tone": "warn"},
        ]
    rows = []
    for tag, value in counts.most_common(5):
        rows.append({"tag": tag, "value": value, "tone": _feedback_tone(tag)})
    return rows


def _feedback_tone(tag: str) -> str:
    if tag in {"like_expression", "resonant", "useful", "clarification_selected"}:
        return "good"
    if tag in {"neutral", "unknown"}:
        return "muted"
    return "warn"


def _positive_feedback_ratio(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    positives = sum(
        1
        for item in records
        if str(item.get("rating") or item.get("action_type") or item.get("feedback") or "")
        in {"like_expression", "resonant", "useful", "clarification_selected"}
    )
    return round(positives / len(records), 2)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 2)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _flat_series(value: Any, n: int) -> list[int | float]:
    numeric = _safe_int(value) if not isinstance(value, float) else value
    return [numeric for _ in range(n)]


def _status_history(status: str) -> list[int]:
    code = {"PASS": 0, "WARN": 1, "FAIL": 2}.get(status, 1)
    return [code for _ in range(21)]


def _mtime_label(path: Path) -> str:
    if not path.exists():
        return "missing"
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%H:%M:%S")


def _time_label(value: Any) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return "n/a"
    return parsed.strftime("%H:%M:%S")


def _age_label(value: Any) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return "n/a"
    delta = datetime.now(timezone.utc) - parsed
    days = delta.days
    if days > 0:
        return f"{days}d"
    hours = int(delta.total_seconds() // 3600)
    if hours > 0:
        return f"{hours}h"
    minutes = max(int(delta.total_seconds() // 60), 0)
    return f"{minutes}m"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bounded_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


def _status_tone(status: str) -> str:
    normalized = status.upper()
    if normalized in {"PASS", "OK", "GOOD", "APPLIED"}:
        return "good"
    if normalized in {"FAIL", "ERROR", "BLOCKED"}:
        return "fail"
    if normalized in {"WARN", "WARNING"}:
        return "warn"
    return "muted"


def _owner_channel(status_report: dict[str, Any]) -> str:
    review = status_report.get("owner_review") if isinstance(status_report.get("owner_review"), dict) else {}
    channel = review.get("review_channel") if isinstance(review.get("review_channel"), dict) else {}
    return str(channel.get("channel") or channel.get("platform") or "")


def _owner_channel_from_config(hermes_home: Path) -> str:
    directory = _read_json(hermes_home / "channel_directory.json")
    if isinstance(directory, dict):
        return str(directory.get("owner_channel") or directory.get("platform") or "")
    return ""


def _project_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if not pyproject.exists():
        return "unknown"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
