#!/usr/bin/env python3
"""Interactive/dry-run onboarding for Memory-OS owner-facing Hermes cron.

Hermes owns channel delivery, cron scheduling, and agent interaction. This
script discovers configured Hermes owner channels, then delegates job creation
to the existing owner-review and right-brain cron gates.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORT_ROOT = (
    REPO_ROOT
    if (REPO_ROOT / "plugins" / "memory" / "memory_os").is_dir()
    else REPO_ROOT / "memory-os" / "runtime" / "python"
)
if str(IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPORT_ROOT))

from plugins.memory.memory_os.cron_registry import (
    RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES,
    memory_os_cron_specs,
    write_cron_registry_snapshot,
)
from plugins.seam.hermes_memory_os.cron_adapter import HermesCronAdapter


SCHEMA_VERSION = "memory-os.owner_cron_onboarding.v0"

# Registry keys deliberately withheld from the active-closure cron profile.
# A key belongs here ONLY for a documented, deliberate reason -- never
# merely because the spec happens to be new. Every OTHER key returned by
# memory_os_cron_specs() is onboarded on active-closure hosts by default, so
# a future registry addition defaults to being installed and visible rather
# than silently skipped (a hand-typed inclusion allowlist is exactly the
# "unknown spec silently dropped" trap this derivation avoids).
#
#   - module_cadence_report: the cadence report artifact itself is already
#     produced on-demand by build_cadence_report() from both the monitor
#     dashboard snapshot and the 3.200 full monitor on every run, so a
#     dedicated periodic cron job is redundant. It remains available under
#     the "full" cron profile for hosts that want a standalone report cron.
ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS = frozenset({
    # Permanent exclusion: its report is already generated on demand elsewhere.
    "module_cadence_report",
    # DEFERRED ACTIVATION, not a permanent exclusion.
    #
    # clearance_cycle is a real registered spec whose helper/gate scripts the
    # installer already deploys, but it was never added to the (previously
    # hand-typed) active-closure key set -- an oversight, since every sibling
    # spec was classified in the same commit that registered it. So the job has
    # never actually been created on a production host, and the lane has never
    # run there.
    #
    # It is held back here on purpose rather than switched on as a side effect
    # of the registry-drift fix: the same change set also repaired
    # `append_terminal(detail=...)`, which means
    # `sweep_unavailable_open_proposals_on_flag_flip` -- which REVOKES open
    # proposals and lives in clearance_cycle.py -- went from raising TypeError
    # on every call to actually working. Enabling the cron in the same step
    # would make two never-exercised paths live at once on 3.200, so a failure
    # could not be attributed to either.
    #
    # To enable: delete this one line. The drift guard below still guarantees a
    # newly registered spec can never be silently omitted again.
    "clearance_cycle",
})
ACTIVE_CLOSURE_CRON_KEYS = frozenset(
    spec.key for spec in memory_os_cron_specs()
) - ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS
DEFAULT_OWNER_REVIEW_SCHEDULE = "0 9 * * *"
DEFAULT_RIGHT_BRAIN_SCHEDULE = "30 4 * * 0"
DEFAULT_FACT_JUDGE_SCHEDULE = "0 */4 * * *"
EXPRESSION_FEEDBACK_AGENT_PROMPT = (
    "你正在处理 Memory-OS 右脑表达反馈请求。Script Output 为空时只回复 [SILENT]。"
    "如果非空，请用中文自然询问 owner，并保留每个 memory feedback oa_... token 命令。"
    "不要替 owner 判断；owner 明确给 token/rating 后才调用 memory_os_review_reply。"
)
MEMORY_SOURCES_FEEDBACK_AGENT_PROMPT = (
    "你正在处理 Memory-OS MemorySources 反馈请求。Script Output 为空时最终只回复 [SILENT]。"
    "如果非空，你的最终回复会直接发送给 owner；不要写 Cron Run Report、运行报告、表格或技术摘要。"
    "只输出 OWNER_MESSAGE_BEGIN 和 OWNER_MESSAGE_END 之间的内容，不要输出分隔符本身。"
    "不要展示 action token、tool call、record id、route/query_class、source_classes 或内部字段。"
    "一次只问一个判断；owner 后续给出一个明确反馈后，再调用 memory_os_review_reply 记录对应 rating。"
    "反馈映射：有帮助=useful，缺上下文/缺了关键上下文=missing_context，"
    "太机制化/程序味=too_mechanistic，要更具体/需要更具体的召回=needs_specific_recall。"
)
CHANNEL_PRIORITY = (
    "telegram",
    "discord",
    "signal",
    "whatsapp",
    "slack",
    "matrix",
    "mattermost",
    "email",
    "sms",
)

SOURCE_EXECUTION_GATE_RUNNER = Path(__file__).resolve().parent / "memory_os_execution_gate_runner.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Onboard Memory-OS owner-review and right-brain Hermes cron jobs.")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--hermes-bin", default=os.environ.get("HERMES_BIN", "hermes"))
    parser.add_argument("--owner", default=os.environ.get("MEMORY_OS_OWNER", "owner"))
    parser.add_argument("--channel", default=os.environ.get("MEMORY_OS_OWNER_REVIEW_CHANNEL", "owner_review_cron"))
    parser.add_argument("--owner-review-deliver", default="auto")
    parser.add_argument("--right-brain-deliver", default="origin")
    parser.add_argument("--owner-review-schedule", default=DEFAULT_OWNER_REVIEW_SCHEDULE)
    parser.add_argument("--right-brain-schedule", default=DEFAULT_RIGHT_BRAIN_SCHEDULE)
    parser.add_argument("--module-cadence-schedule", default="15 */6 * * *")
    parser.add_argument("--right-brain-outcome-schedule", default="45 4 * * 0")
    parser.add_argument("--proposal-followups-schedule", default="*/30 * * * *")
    parser.add_argument("--expression-feedback-schedule", default="0 5 * * 0")
    parser.add_argument("--memory-sources-feedback-schedule", default="30 10 * * *")
    parser.add_argument("--candidate-aggregation-schedule", default="0 */6 * * *")
    parser.add_argument("--fact-judge-schedule", default=DEFAULT_FACT_JUDGE_SCHEDULE)
    parser.add_argument("--index-sync-schedule", default="*/30 * * * *")
    parser.add_argument("--working-cleanup-schedule", default="0 3 * * 0")
    parser.add_argument("--l3-probe-schedule", default="0 */6 * * *")
    parser.add_argument("--event-stats-refresh-schedule", default="7,22,37,52 * * * *")
    parser.add_argument("--exposure-rollup-schedule", default="5 0 * * *")
    parser.add_argument("--full-monitor-refresh-schedule", default="30 2 * * *")
    parser.add_argument("--v3-seed-evidence-schedule", default="15 0 * * *")
    parser.add_argument("--v3-wandering-schedule", default="17 */6 * * *")
    parser.add_argument("--v3-journal-sweep-schedule", default="30 3 * * *")
    parser.add_argument("--state-overlay-refresh-schedule", default="17,47 * * * *")
    parser.add_argument("--entity-index-refresh-schedule", default="25,55 * * * *")
    parser.add_argument("--hindsight-advisory-digest-schedule", default="20 2 * * 0")
    parser.add_argument("--hindsight-health-probe-schedule", default="33 * * * *")
    parser.add_argument("--clearance-cycle-schedule", default="*/10 * * * *")
    parser.add_argument(
        "--cron-profile",
        choices=("active-closure", "full"),
        default=os.environ.get("MEMORY_OS_CRON_PROFILE", "active-closure"),
        help="active-closure installs current Memory-OS automation closure jobs plus baseline local index sync; full installs optional feedback/right-brain/report jobs too.",
    )
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--owner-approved", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_onboarding(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"dry_run", "applied", "already_configured", "updated"} else 2


def run_onboarding(args: argparse.Namespace) -> dict[str, Any]:
    hermes_home = Path(args.hermes_home).expanduser().resolve()
    channels = discover_owner_channels(hermes_home)
    findings: list[dict[str, str]] = []

    owner_review_deliver = _resolve_deliver(
        requested=str(args.owner_review_deliver),
        channels=channels,
        interactive=bool(args.interactive),
        prompt="Select owner review delivery channel",
    )
    right_brain_deliver = _resolve_deliver(
        requested=str(args.right_brain_deliver),
        channels=channels,
        interactive=bool(args.interactive),
        prompt="Select right-brain expression delivery channel",
        allow_origin=True,
    )

    if owner_review_deliver == "auto":
        findings.append(_finding("owner_review_deliver_auto_unresolved", "error"))
    if not owner_review_deliver:
        findings.append(_finding("owner_review_deliver_missing", "error"))
    if not right_brain_deliver:
        findings.append(_finding("right_brain_deliver_missing", "error"))
    if args.apply and not args.owner_approved:
        findings.append(_finding("owner_approval_required_for_apply", "error"))

    status = "blocked" if _has_error(findings) else "dry_run"
    owner_review_channel = _resolve_owner_review_channel(str(args.channel), owner_review_deliver)
    owner_report: dict[str, Any] = {}
    right_brain_report: dict[str, Any] = {}
    operational_jobs: list[dict[str, Any]] = []
    operational_specs = _operational_specs(args, owner_review_deliver, right_brain_deliver)
    paused_optional_jobs: list[dict[str, Any]] = []
    for spec in operational_specs:
        if not (hermes_home / "scripts" / spec["script"]).is_file():
            findings.append(_finding(f"{spec['name']}_script_missing", "error"))
        if not (hermes_home / "scripts" / spec["raw_script"]).is_file():
            findings.append(_finding(f"{spec['name']}_raw_script_missing", "error"))
    status = "blocked" if _has_error(findings) else status
    if not _has_error(findings):
        if args.apply:
            _write_execution_gate_assets(hermes_home=hermes_home, specs=operational_specs)
        owner_gate = _load_script_module("memory_os_owner_review_cron_gate.py")
        right_brain_gate = _load_script_module("memory_os_right_brain_expression_cron_gate.py")
        owner_review_enabled = any(str(spec.get("registry_key") or "") == "owner_review_digest" for spec in operational_specs)
        right_brain_enabled = any(str(spec.get("registry_key") or "") == "right_brain_expression" for spec in operational_specs)
        if args.apply:
            if owner_review_enabled:
                owner_gate.HELPER_NAME = _spec_by_key(operational_specs, "owner_review_digest")["script"]
            if right_brain_enabled:
                right_brain_gate.HELPER_NAME = _spec_by_key(operational_specs, "right_brain_expression")["script"]
        if owner_review_enabled:
            owner_args = owner_gate.build_parser().parse_args(
                [
                    "--hermes-home",
                    str(hermes_home),
                    "--hermes-bin",
                    str(args.hermes_bin),
                    "--schedule",
                    str(args.owner_review_schedule),
                    "--deliver",
                    owner_review_deliver,
                    "--owner",
                    str(args.owner),
                    "--channel",
                    owner_review_channel,
                    *(["--apply"] if args.apply else []),
                    *(["--owner-approved"] if args.owner_approved else []),
                ]
            )
            owner_report = owner_gate.run_gate(owner_args)
        else:
            owner_report = {"status": "skipped", "reason": "cron_profile_excludes_owner_review_digest", "findings": []}
        if right_brain_enabled:
            rb_args = right_brain_gate.build_parser().parse_args(
                [
                    "--hermes-home",
                    str(hermes_home),
                    "--hermes-bin",
                    str(args.hermes_bin),
                    "--schedule",
                    str(args.right_brain_schedule),
                    "--deliver",
                    right_brain_deliver,
                    *(["--apply"] if args.apply else []),
                    *(["--owner-approved"] if args.owner_approved else []),
                ]
            )
            right_brain_report = right_brain_gate.run_gate(rb_args)
        else:
            right_brain_report = {"status": "skipped", "reason": "cron_profile_excludes_right_brain_expression", "findings": []}
        findings.extend(_prefixed_findings("owner_review", owner_report.get("findings")))
        findings.extend(_prefixed_findings("right_brain", right_brain_report.get("findings")))
        if _has_error(findings):
            status = "blocked"
        elif args.apply:
            for spec in operational_specs:
                operational_jobs.append(_ensure_cron_job(hermes_home=hermes_home, hermes_bin=str(args.hermes_bin), spec=spec))
            if str(args.cron_profile) == "active-closure":
                paused_optional_jobs = _pause_known_optional_cron_jobs(
                    hermes_home=hermes_home,
                    hermes_bin=str(args.hermes_bin),
                    active_specs=operational_specs,
                )
            gate_statuses = {str(owner_report.get("status") or ""), str(right_brain_report.get("status") or "")}
            operational_statuses = {str(item.get("status") or "") for item in operational_jobs}
            optional_statuses = {str(item.get("status") or "") for item in paused_optional_jobs}
            if "error" in operational_statuses or "error" in optional_statuses:
                status = "blocked"
            elif gate_statuses <= {"already_configured", "skipped"} and operational_statuses <= {"already_configured"}:
                status = "already_configured"
            elif gate_statuses <= {"applied", "already_configured", "updated", "skipped"}:
                status = "applied" if "applied" in gate_statuses else "updated"
            else:
                status = "blocked"
        else:
            status = "dry_run"
            operational_jobs = [
                *[
                {
                    "name": spec["name"],
                    "schedule": spec["schedule"],
                    "deliver": spec["deliver"],
                    "script": spec["script"],
                    "raw_script": spec["raw_script"],
                    "registry_key": spec["registry_key"],
                    "no_agent": spec["no_agent"],
                    "status": "dry_run",
                }
                for spec in operational_specs
                ],
            ]

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "apply_requested": bool(args.apply),
        "owner_approved": bool(args.owner_approved),
        "detected_channels": channels,
        "selected_owner_review_deliver": owner_review_deliver,
        "selected_owner_review_channel": owner_review_channel,
        "selected_right_brain_deliver": right_brain_deliver,
        "owner_review_schedule": str(args.owner_review_schedule),
        "right_brain_schedule": str(args.right_brain_schedule),
        "cron_profile": str(args.cron_profile),
        "owner_review": _summarize_gate(owner_report),
        "right_brain": _summarize_gate(right_brain_report),
        "operational_cron_jobs": operational_jobs,
        "paused_optional_cron_jobs": paused_optional_jobs,
        "findings": findings,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _operational_specs(args: argparse.Namespace, owner_deliver: str, right_brain_deliver: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for cron_spec in memory_os_cron_specs():
        if str(args.cron_profile) == "active-closure" and cron_spec.key not in ACTIVE_CLOSURE_CRON_KEYS:
            continue
        specs.append(
            {
                "_cron_spec": cron_spec,
                "registry_key": cron_spec.key,
                "name": cron_spec.name,
                "schedule": _schedule_for_spec(args, cron_spec.schedule_arg),
                "deliver": _deliver_for_spec(cron_spec.deliver_role, owner_deliver, right_brain_deliver),
                "script": cron_spec.wrapper_script,
                "raw_script": cron_spec.raw_script,
                "no_agent": cron_spec.no_agent,
                "prompt": _prompt_for_spec(cron_spec.prompt_ref),
            }
        )
    return specs


def _schedule_for_spec(args: argparse.Namespace, schedule_arg: str) -> str:
    return str(getattr(args, schedule_arg))


def _deliver_for_spec(role: str, owner_deliver: str, right_brain_deliver: str) -> str:
    if role == "owner":
        return owner_deliver
    if role == "right_brain":
        return right_brain_deliver
    return "local"


def _prompt_for_spec(prompt_ref: str) -> str:
    if prompt_ref == "owner_review_agent_prompt":
        return _load_script_module("memory_os_owner_review_cron_gate.py").OWNER_REVIEW_AGENT_PROMPT
    if prompt_ref == "right_brain_agent_prompt":
        return _load_script_module("memory_os_right_brain_expression_cron_gate.py").RIGHT_BRAIN_AGENT_PROMPT
    if prompt_ref == "expression_feedback_agent_prompt":
        return EXPRESSION_FEEDBACK_AGENT_PROMPT
    if prompt_ref == "memory_sources_feedback_agent_prompt":
        return MEMORY_SOURCES_FEEDBACK_AGENT_PROMPT
    return ""


def _write_execution_gate_assets(*, hermes_home: Path, specs: list[dict[str, Any]]) -> None:
    scripts_dir = hermes_home / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    selected_specs = tuple(spec["_cron_spec"] for spec in specs)
    write_cron_registry_snapshot(
        hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json",
        specs=selected_specs,
    )
    runner_target = scripts_dir / "memory_os_execution_gate_runner.py"
    if SOURCE_EXECUTION_GATE_RUNNER.is_file():
        shutil.copy2(SOURCE_EXECUTION_GATE_RUNNER, runner_target)
        runner_target.chmod(runner_target.stat().st_mode | stat.S_IXUSR)
    else:
        raise RuntimeError(f"execution gate runner source missing: {SOURCE_EXECUTION_GATE_RUNNER}")
    for spec in specs:
        if str(spec["script"]) == str(spec["raw_script"]):
            continue
        wrapper = scripts_dir / str(spec["script"])
        wrapper.write_text(
            (
                "#!/usr/bin/env python3\n"
                "from memory_os_execution_gate_runner import main\n\n"
                "if __name__ == \"__main__\":\n"
                f"    raise SystemExit(main([\"--registry-key\", \"{spec['registry_key']}\"]))\n"
            ),
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)


def _spec_by_key(specs: list[dict[str, Any]], key: str) -> dict[str, Any]:
    for spec in specs:
        if str(spec.get("registry_key") or "") == key:
            return spec
    raise KeyError(key)


def _ensure_cron_job(*, hermes_home: Path, hermes_bin: str, spec: dict[str, Any]) -> dict[str, Any]:
    adapter = HermesCronAdapter(hermes_home=hermes_home, hermes_bin=hermes_bin)
    existing = _find_job_by_name(adapter.read_jobs(), str(spec["name"]))
    desired = adapter.desired_job(
        spec["_cron_spec"],
        schedule=str(spec["schedule"]),
        deliver=str(spec["deliver"]),
        prompt=str(spec["prompt"]),
    )
    plan = adapter.plan_upsert(desired, existing_job=existing)
    if existing:
        if plan.status == "edit":
            env = dict(os.environ)
            env["HERMES_HOME"] = str(hermes_home)
            completed = subprocess.run(plan.command, check=False, text=True, capture_output=True, env=env)
            if completed.returncode != 0:
                return {
                    "name": spec["name"],
                    "job_id": str(existing.get("id") or existing.get("job_id") or ""),
                    "status": "error",
                    "stderr": (completed.stderr or completed.stdout or "").strip()[:500],
                "deliver": str(spec["deliver"]),
                "script": str(spec["script"]),
                "raw_script": str(spec["raw_script"]),
                "registry_key": str(spec["registry_key"]),
                "no_agent": bool(spec.get("no_agent")),
                "migration_fields": list(plan.migration_fields),
            }
            existing = _find_job_by_name(adapter.read_jobs(), str(spec["name"])) or existing
            return {
                "name": spec["name"],
                "job_id": str(existing.get("id") or existing.get("job_id") or ""),
                "status": "updated",
                "deliver": str(existing.get("deliver") or spec["deliver"]),
                "script": str(existing.get("script") or spec["script"]),
                "raw_script": str(spec["raw_script"]),
                "registry_key": str(spec["registry_key"]),
                "no_agent": bool(existing.get("no_agent")),
                "migration_fields": list(plan.migration_fields),
            }
        if plan.status == "blocked":
            return {
                "name": spec["name"],
                "job_id": str(existing.get("id") or existing.get("job_id") or ""),
                "status": "error",
                "stderr": plan.reason,
                "deliver": str(spec["deliver"]),
                "script": str(existing.get("script") or spec["script"]),
                "raw_script": str(spec["raw_script"]),
                "registry_key": str(spec["registry_key"]),
                "no_agent": bool(existing.get("no_agent")),
            }
        return {
            "name": spec["name"],
            "job_id": str(existing.get("id") or existing.get("job_id") or ""),
            "status": "already_configured",
            "deliver": str(existing.get("deliver") or spec["deliver"]),
            "script": str(existing.get("script") or spec["script"]),
            "raw_script": str(spec["raw_script"]),
            "registry_key": str(spec["registry_key"]),
            "no_agent": bool(existing.get("no_agent")),
        }
    env = dict(os.environ)
    env["HERMES_HOME"] = str(hermes_home)
    completed = subprocess.run(plan.command, check=False, text=True, capture_output=True, env=env)
    if completed.returncode != 0:
        return {
            "name": spec["name"],
            "status": "error",
            "stderr": (completed.stderr or completed.stdout or "").strip()[:500],
            "deliver": str(spec["deliver"]),
            "script": str(spec["script"]),
            "raw_script": str(spec["raw_script"]),
            "registry_key": str(spec["registry_key"]),
            "no_agent": bool(spec.get("no_agent")),
        }
    created = _find_job_by_name(_read_jobs(hermes_home / "cron" / "jobs.json"), str(spec["name"]))
    return {
        "name": spec["name"],
        "job_id": str((created or {}).get("id") or (created or {}).get("job_id") or ""),
        "status": "applied",
        "deliver": str(spec["deliver"]),
        "script": str(spec["script"]),
        "raw_script": str(spec["raw_script"]),
        "registry_key": str(spec["registry_key"]),
        "no_agent": bool(spec.get("no_agent")),
    }


def _pause_known_optional_cron_jobs(
    *,
    hermes_home: Path,
    hermes_bin: str,
    active_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    active_names = {str(spec.get("name") or "") for spec in active_specs}
    known_keys_by_name = {spec.name: spec.key for spec in memory_os_cron_specs()}
    known_keys_by_name.update(
        {
            "memory-os-right-brain-expression": "right_brain_expression",
            "memory-os-right-brain-expression-outcome": "right_brain_expression_outcome",
        }
    )
    adapter = HermesCronAdapter(hermes_home=hermes_home, hermes_bin=hermes_bin)
    results: list[dict[str, Any]] = []
    env = dict(os.environ)
    env["HERMES_HOME"] = str(hermes_home)
    for job in adapter.read_jobs():
        name = str(job.get("name") or "")
        script = str(job.get("script") or "")
        registry_key = known_keys_by_name.get(name)
        if registry_key is None and script in RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES:
            registry_key = "legacy_right_brain_retired"
        if not registry_key or name in active_names:
            continue
        job_id = str(job.get("id") or job.get("job_id") or "")
        enabled = job.get("enabled") is not False
        base = {
            "name": name,
            "job_id": job_id,
            "registry_key": registry_key,
            "script": script,
            "was_enabled": enabled,
        }
        if not enabled:
            results.append({**base, "status": "already_paused"})
            continue
        if not job_id:
            results.append({**base, "status": "error", "stderr": "job_id_missing"})
            continue
        completed = subprocess.run(
            [hermes_bin, "cron", "pause", job_id],
            check=False,
            text=True,
            capture_output=True,
            env=env,
        )
        if completed.returncode != 0:
            results.append(
                {
                    **base,
                    "status": "error",
                    "stderr": (completed.stderr or completed.stdout or "").strip()[:500],
                }
            )
        else:
            results.append({**base, "status": "paused"})
    return results


def _cron_job_update_command(*, hermes_bin: str, existing: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    job_id = str(existing.get("id") or existing.get("job_id") or "")
    if not job_id:
        return []

    command = [hermes_bin, "cron", "edit"]
    desired_schedule = str(spec.get("schedule") or "")
    existing_schedule = _cron_schedule_display(existing)
    if desired_schedule and existing_schedule and existing_schedule != desired_schedule:
        command.extend(["--schedule", desired_schedule])

    desired_prompt = str(spec.get("prompt") or "")
    if str(existing.get("prompt") or "") != desired_prompt:
        command.extend(["--prompt", desired_prompt])

    desired_deliver = str(spec.get("deliver") or "")
    if desired_deliver and str(existing.get("deliver") or "") != desired_deliver:
        command.extend(["--deliver", desired_deliver])

    desired_script = str(spec.get("script") or "")
    if desired_script and str(existing.get("script") or "") != desired_script:
        command.extend(["--script", desired_script])

    desired_no_agent = bool(spec.get("no_agent"))
    if bool(existing.get("no_agent")) != desired_no_agent:
        command.append("--no-agent" if desired_no_agent else "--agent")

    if len(command) == 3:
        return []
    command.append(job_id)
    return command


def _cron_schedule_display(job: dict[str, Any]) -> str:
    if str(job.get("schedule_display") or ""):
        return str(job.get("schedule_display") or "")
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return str(schedule.get("expr") or schedule.get("display") or "")
    return str(schedule or "")


def _gate_job_entry(
    *,
    name: str,
    report: dict[str, Any],
    deliver: str,
    script: str,
    no_agent: bool,
    schedule: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "job_id": str(report.get("job_id") or ""),
        "status": str(report.get("status") or "dry_run"),
        "schedule": schedule,
        "deliver": deliver,
        "script": script,
        "no_agent": no_agent,
    }


def _read_jobs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    jobs = loaded.get("jobs", loaded) if isinstance(loaded, dict) else loaded
    return [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []


def _find_job_by_name(jobs: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for job in jobs:
        if str(job.get("name") or "") == name:
            return job
    return None


def discover_owner_channels(hermes_home: str | Path) -> list[dict[str, str]]:
    home = Path(hermes_home).expanduser().resolve()
    directory = home / "channel_directory.json"
    platforms: dict[str, Any] = {}
    if directory.exists():
        try:
            loaded = json.loads(directory.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("platforms"), dict):
                platforms = dict(loaded["platforms"])
        except json.JSONDecodeError:
            platforms = {}
    ordered_platforms = [name for name in CHANNEL_PRIORITY if name in platforms]
    ordered_platforms.extend(sorted(name for name in platforms if name not in ordered_platforms))
    channels: list[dict[str, str]] = []
    for platform in ordered_platforms:
        entries = platforms.get(platform)
        if not isinstance(entries, list) or not entries:
            continue
        first = entries[0] if isinstance(entries[0], dict) else {}
        channels.append(
            {
                "platform": str(platform),
                "deliver": str(platform),
                "target_class": "platform_home",
                "source": "channel_directory",
                "entry_count": str(len(entries)),
                "sample_type": str(first.get("type") or ""),
                "sample_name": str(first.get("name") or ""),
            }
        )
    return channels


def _resolve_deliver(
    *,
    requested: str,
    channels: list[dict[str, str]],
    interactive: bool,
    prompt: str,
    allow_origin: bool = False,
) -> str:
    value = str(requested or "").strip()
    if value != "auto":
        return value
    choices = list(channels)
    if allow_origin:
        choices.insert(
            0,
            {
                "platform": "origin",
                "deliver": "origin",
                "target_class": "origin",
                "source": "hermes_origin",
                "entry_count": "",
                "sample_type": "",
                "sample_name": "",
            },
        )
    if not choices:
        return "auto"
    if interactive and sys.stdin.isatty():
        for idx, channel in enumerate(choices, start=1):
            suffix = f" ({channel.get('sample_name')})" if channel.get("sample_name") else ""
            print(f"{idx}. {channel['deliver']}{suffix}")
        selected = input(f"{prompt} [1]: ").strip()
        if selected:
            try:
                index = int(selected)
            except ValueError:
                return selected
            if 1 <= index <= len(choices):
                return choices[index - 1]["deliver"]
    return choices[0]["deliver"]


def _resolve_owner_review_channel(requested: str, owner_review_deliver: str) -> str:
    value = str(requested or "").strip()
    if value and value not in {"auto", "owner_review_cron", "unknown"}:
        return value
    label = str(owner_review_deliver or "").strip()
    label = label.split(":", 1)[0]
    label = label.replace("-", "_")
    return label or "owner_review"


def _load_script_module(filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(Path(filename).stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _summarize_gate(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}
    return {
        "status": report.get("status"),
        "job_name": report.get("job_name"),
        "job_id": report.get("job_id"),
        "deliver_target_class": report.get("deliver_target_class"),
        "config_updated": report.get("config_updated"),
        "findings": report.get("findings") if isinstance(report.get("findings"), list) else [],
    }


def _prefixed_findings(prefix: str, findings: Any) -> list[dict[str, str]]:
    if not isinstance(findings, list):
        return []
    result: list[dict[str, str]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "")
        if code == "cron_job_already_present":
            continue
        result.append({"code": f"{prefix}_{code}", "severity": str(item.get("severity") or "warning")})
    return result


def _has_error(findings: list[dict[str, str]]) -> bool:
    return any(item.get("severity") == "error" for item in findings)


def _finding(code: str, severity: str) -> dict[str, str]:
    return {"code": code, "severity": severity}


if __name__ == "__main__":
    raise SystemExit(main())
