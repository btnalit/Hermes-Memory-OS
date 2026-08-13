#!/usr/bin/env python3
"""Record bounded outcomes from Hermes right-brain expression cron output.

Hermes owns the agent turn, final wording, scheduling, and delivery. This
helper only scans Hermes-owned cron output for the configured right-brain
expression job and appends bounded outcome evidence for Memory-OS monitor and
feedback loops.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.right_brain_expression_outcome_scan.v0"
OUTCOME_SCHEMA_VERSION = "memory-os.right_brain_expression_outcome.v0"
DEFAULT_JOB_NAME = "memory-os-right-brain-expression"
INTERNAL_MARKERS = (
    "adapter_request_id:",
    "Bounded context summaries:",
    "Memory-OS 只提供 bounded context",
    "schema_version",
    "source_ref",
    "raw_body",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    # Legacy paused per-lane surface: keeps its host-calibrated "main" default
    # on purpose (see memory_os_right_brain_expression.py).
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE", "main"))
    parser.add_argument("--job-name", default=os.environ.get("MEMORY_OS_RIGHT_BRAIN_JOB_NAME", DEFAULT_JOB_NAME))
    parser.add_argument("--max-preview-chars", type=int, default=int(os.environ.get("MEMORY_OS_RIGHT_BRAIN_OUTCOME_MAX_CHARS", "360")))
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hermes_home = Path(args.hermes_home).expanduser().resolve()
    report = scan_outcomes(
        hermes_home=hermes_home,
        profile=args.profile,
        job_name=args.job_name,
        max_preview_chars=max(int(args.max_preview_chars), 80),
        apply=bool(args.apply),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"ok", "warning", "retired"} else 2


def scan_outcomes(
    *,
    hermes_home: Path,
    profile: str,
    job_name: str,
    max_preview_chars: int = 360,
    apply: bool = False,
) -> dict[str, Any]:
    hermes_home = Path(hermes_home).expanduser().resolve()
    _ensure_runtime_path(hermes_home)
    from plugins.memory.memory_os.legacy_right_brain_retirement import (
        legacy_right_brain_is_retired,
        legacy_right_brain_read_lock,
    )

    if legacy_right_brain_is_retired(hermes_home):
        return _retired_report(profile=profile, job_name=job_name, apply=apply)
    with legacy_right_brain_read_lock(hermes_home):
        if legacy_right_brain_is_retired(hermes_home):
            return _retired_report(profile=profile, job_name=job_name, apply=apply)
        return _scan_outcomes_unlocked(
            hermes_home=hermes_home,
            profile=profile,
            job_name=job_name,
            max_preview_chars=max_preview_chars,
            apply=apply,
        )


def _ensure_runtime_path(hermes_home: Path) -> None:
    runtime = hermes_home / "memory-os" / "runtime" / "python"
    if runtime.exists() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    repo_root = Path(__file__).resolve().parents[1]
    if (
        (repo_root / "plugins" / "memory" / "memory_os").is_dir()
        and str(repo_root) not in sys.path
    ):
        sys.path.insert(0, str(repo_root))


def _retired_report(*, profile: str, job_name: str, apply: bool) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "retired",
        "profile": profile,
        "job_name": job_name,
        "job_count": 0,
        "existing_outcome_count": 0,
        "new_outcome_count": 0,
        "written_outcome_count": 0,
        "apply": apply,
        "outcomes_path": "",
        "internal_marker_count": 0,
        "findings": [{"code": "legacy_right_brain_retired", "severity": "info"}],
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "raw_body_included": False,
        },
    }


def _scan_outcomes_unlocked(
    *,
    hermes_home: Path,
    profile: str,
    job_name: str,
    max_preview_chars: int = 360,
    apply: bool = False,
) -> dict[str, Any]:
    jobs = _read_cron_jobs(hermes_home)
    matched_jobs = [job for job in jobs if str(job.get("name") or "") == job_name]
    outcomes_path = _outcomes_path(hermes_home)
    existing = _read_jsonl(outcomes_path)
    seen = {str(item.get("dedup_key") or "") for item in existing if isinstance(item, dict)}
    requests = _read_jsonl(_requests_path(hermes_home))
    findings: list[dict[str, Any]] = []
    if not matched_jobs:
        findings.append({"code": "right_brain_expression_job_not_found", "severity": "warning"})
    candidates: list[dict[str, Any]] = []
    for job in matched_jobs:
        job_id = str(job.get("id") or job.get("job_id") or job.get("name") or "")
        if not job_id:
            continue
        for output_path in sorted((hermes_home / "cron" / "output" / job_id).glob("*")):
            if not output_path.is_file():
                continue
            candidate = _outcome_for_file(
                hermes_home=hermes_home,
                profile=profile,
                job=job,
                output_path=output_path,
                requests=requests,
                max_preview_chars=max_preview_chars,
            )
            if candidate["dedup_key"] not in seen:
                candidates.append(candidate)
    written = 0
    if apply and candidates:
        outcomes_path.parent.mkdir(parents=True, exist_ok=True)
        with outcomes_path.open("a", encoding="utf-8") as handle:
            for item in candidates:
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
                written += 1
                seen.add(item["dedup_key"])
    internal_marker_count = sum(int(item.get("internal_marker_count") or 0) for item in candidates)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "warning" if findings or internal_marker_count else "ok",
        "profile": profile,
        "job_name": job_name,
        "job_count": len(matched_jobs),
        "existing_outcome_count": len(existing),
        "new_outcome_count": len(candidates),
        "written_outcome_count": written,
        "apply": apply,
        "outcomes_path": str(outcomes_path),
        "internal_marker_count": internal_marker_count,
        "findings": findings,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "raw_body_included": False,
        },
    }


def _outcome_for_file(
    *,
    hermes_home: Path,
    profile: str,
    job: dict[str, Any],
    output_path: Path,
    requests: list[dict[str, Any]],
    max_preview_chars: int,
) -> dict[str, Any]:
    raw_text = output_path.read_text(encoding="utf-8", errors="replace")
    output_sha256 = hashlib.sha256(raw_text.encode("utf-8", errors="replace")).hexdigest()
    job_id = str(job.get("id") or job.get("job_id") or job.get("name") or "")
    cleaned = _clean_cron_output(raw_text)
    silent = _is_silent(cleaned)
    request = _latest_request_before(requests, output_path.stat().st_mtime)
    preview = "[SILENT]" if silent else _clip(cleaned, max_preview_chars)
    internal_marker_count = sum(1 for marker in INTERNAL_MARKERS if marker.lower() in cleaned.lower())
    dedup_key = f"right_brain_expression_outcome::{job_id}::{output_path.name}::{output_sha256}"
    created_at = datetime.now(timezone.utc).isoformat()
    observed_at = datetime.fromtimestamp(output_path.stat().st_mtime, timezone.utc).isoformat()
    return {
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "outcome_id": f"rbout_{hashlib.sha256(dedup_key.encode('utf-8')).hexdigest()[:16]}",
        "created_at": created_at,
        "observed_at": observed_at,
        "profile": profile,
        "job_id": job_id,
        "job_name": str(job.get("name") or job_id),
        "delivery_mode": "hermes_cron_agent",
        "delivery_channel": _delivery_channel(job),
        "output_filename": output_path.name,
        "output_sha256": output_sha256,
        "output_size": output_path.stat().st_size,
        "dedup_key": dedup_key,
        "request_id": str(request.get("request_id") or ""),
        "request_created_at": str(request.get("created_at") or ""),
        "policy_id": str(request.get("policy_id") or ""),
        "policy_version": int(request.get("policy_version") or 0) if request else 0,
        "silent": silent,
        "outcome_preview": preview,
        "outcome_preview_chars": len(preview),
        "internal_marker_count": internal_marker_count,
        "raw_body_included": False,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
        "source_path": str(output_path.resolve()),
    }


def _clean_cron_output(text: str) -> str:
    normalized = text.replace("\r\n", "\n").strip()
    response_match = re.search(r"(?im)^## Response\s*$", normalized)
    if response_match:
        normalized = normalized[response_match.end() :].strip()
    normalized = re.sub(r"^Cronjob Response:.*?(?:\n-+\n|\n\n)", "", normalized, flags=re.DOTALL)
    normalized = re.sub(r"\n?To stop or manage this job,.*$", "", normalized, flags=re.DOTALL).strip()
    return normalized


def _is_silent(text: str) -> bool:
    cleaned = text.strip()
    return cleaned == "" or cleaned.upper() == "[SILENT]"


def _latest_request_before(requests: list[dict[str, Any]], mtime: float) -> dict[str, Any]:
    if not requests:
        return {}
    output_ts = datetime.fromtimestamp(mtime, timezone.utc)
    best: dict[str, Any] = {}
    best_ts: datetime | None = None
    for item in requests:
        if not isinstance(item, dict):
            continue
        created_at = _parse_datetime(str(item.get("created_at") or ""))
        if created_at is None:
            continue
        if created_at <= output_ts and (best_ts is None or created_at >= best_ts):
            best = item
            best_ts = created_at
    return best or (requests[-1] if isinstance(requests[-1], dict) else {})


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _delivery_channel(job: dict[str, Any]) -> str:
    deliver = str(job.get("deliver") or job.get("delivery") or job.get("target") or "")
    if deliver:
        return deliver
    return "unknown"


def _read_cron_jobs(hermes_home: Path) -> list[dict[str, Any]]:
    path = hermes_home / "cron" / "jobs.json"
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    jobs = loaded.get("jobs", []) if isinstance(loaded, dict) else loaded
    return [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _requests_path(hermes_home: Path) -> Path:
    return hermes_home / "system-modules" / "right_brain_expression_adapter" / "requests.jsonl"


def _outcomes_path(hermes_home: Path) -> Path:
    return hermes_home / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"


def _clip(text: str, max_chars: int) -> str:
    compact = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "…"


if __name__ == "__main__":
    raise SystemExit(main())
