#!/usr/bin/env python3
"""Deploy L3 prefetch behavior probe as a scheduled Memory-OS cron job.

Usage:
    python3 scripts/deploy_l3_probe.py                        # Plan (default, read-only)
    python3 scripts/deploy_l3_probe.py --apply                # Deploy
    python3 scripts/deploy_l3_probe.py --apply --smoke        # Deploy + immediate smoke test
    python3 scripts/deploy_l3_probe.py --cleanup              # Remove deployed job + helper
    python3 scripts/deploy_l3_probe.py --dry-run              # Show what would be done

Phase design (following deploy_memory_os.py pattern):
    plan      → read-only: check current state, report what needs doing
    dry-run   → show exact commands without executing
    apply     → execute deployment
    postcheck → verify the deployed job is running and try a smoke test
    cleanup   → reverse deployment

The probe_l3_prefetch_behavior.py script (in this repo) is the actual
governance-path probe. This deploy script installs a thin no_agent cron
helper that subprocesses it each run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import shared identity markers from the helper (same scripts/ directory)
try:
    from memory_os_l3_probe_helper import _MEMORY_OS_IDENTITY_MARKERS
except ImportError:
    # Fallback for deploy from non-standard paths
    _MEMORY_OS_IDENTITY_MARKERS = ["pyproject.toml", "plugins/memory/memory_os/__init__.py"]

from plugins.seam.hermes_memory_os.cron_adapter import HermesCronAdapter

SCHEMA_VERSION = "memory-os.l3_probe_deploy.v0"

# ── file constants ─────────────────────────────────────────────────
HERMES_SCRIPTS = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "scripts"
SOURCE_HELPER = REPO_ROOT / "scripts" / "memory_os_l3_probe_helper.py"
DEPLOY_HELPER = HERMES_SCRIPTS / "memory_os_l3_probe_helper.py"

# ── cron job parameters ────────────────────────────────────────────
JOB_NAME = "memory-os-l3-probe-verification"
SCHEDULE = "every 360m"
DELIVER = "origin"
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy L3 prefetch behavior probe as a cron job.")
    parser.add_argument("--apply", action="store_true", help="Execute deployment")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--smoke", action="store_true", help="Run immediate smoke test after apply")
    parser.add_argument("--cleanup", action="store_true", help="Remove deployed cron job and helper script")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    return parser


def run_plan(hermes_home: Path) -> dict[str, Any]:
    """Read-only: check current state and report what needs doing."""
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "phase": "plan",
        "hermes_home": str(hermes_home),
    }

    # Check helper script
    helper_installed = DEPLOY_HELPER.is_file()
    helper_current = (
        helper_installed
        and SOURCE_HELPER.is_file()
        and DEPLOY_HELPER.read_text() == SOURCE_HELPER.read_text()
    ) if SOURCE_HELPER.is_file() else helper_installed
    report["helper_installed"] = helper_installed
    report["helper_current"] = helper_current

    # Check cron job
    jobs = HermesCronAdapter(hermes_home=hermes_home).read_jobs()
    existing_job = _find_job_by_name(jobs, JOB_NAME)
    if existing_job:
        report["job_exists"] = True
        report["job_id"] = str(existing_job.get("job_id") or existing_job.get("id") or "")
        report["job_enabled"] = bool(existing_job.get("enabled", True))
        report["job_script"] = str(existing_job.get("script") or "")
        report["job_schedule"] = str(existing_job.get("schedule") or "")
        report["job_deliver"] = str(existing_job.get("deliver") or "")
    else:
        report["job_exists"] = False

    # Determine what needs doing
    needs: list[str] = []
    if not helper_installed:
        needs.append("install_helper")
    elif not helper_current:
        needs.append("update_helper")
    if not existing_job:
        needs.append("create_cron_job")
    if not needs:
        report["status"] = "no_action_needed"
        report["message"] = "L3 probe is already deployed and current."
    else:
        report["status"] = "action_needed"
        report["needs"] = needs
        report["message"] = f"Needs: {', '.join(needs)}"

    return report


def run_dry_run(hermes_home: Path) -> dict[str, Any]:
    """Show commands that would be executed."""
    plan = run_plan(hermes_home)
    if plan.get("status") == "no_action_needed":
        return {**plan, "phase": "dry_run", "commands": []}

    commands: list[dict[str, str]] = []
    needs = plan.get("needs", [])

    if "install_helper" in needs or "update_helper" in needs:
        commands.append({
            "operation": "cp" if SOURCE_HELPER.is_file() else "write",
            "source": str(SOURCE_HELPER) if SOURCE_HELPER.is_file() else "inline",
            "target": str(DEPLOY_HELPER),
        })
    if "create_cron_job" in needs:
        commands.append({
            "operation": "hermes cron create",
            "name": JOB_NAME,
            "schedule": SCHEDULE,
            "script": DEPLOY_HELPER.name,
            "no_agent": "true",
            "deliver": DELIVER,
        })

    return {**plan, "phase": "dry_run", "commands": commands}


def run_apply(hermes_home: Path) -> dict[str, Any]:
    """Execute deployment: install helper and create cron job."""
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "phase": "apply",
        "hermes_home": str(hermes_home),
    }
    # The l3_probe_verification lane is now a member of the
    # "memory-os-tick-evidence" group tick, created by
    # memory_os_owner_cron_onboarding.py. Creating the old standalone
    # "memory-os-l3-probe-verification" job here as well would run the lane
    # twice -- once from this job and once from the tick -- with two
    # independent ExecutionGate envelopes per cycle. Refuse loudly instead.
    result["status"] = "blocked"
    result["error_code"] = "superseded_by_group_tick"
    result["superseded_by"] = "memory-os-tick-evidence"
    result["detail"] = (
        "l3_probe_verification is scheduled by the memory-os-tick-evidence group tick. "
        "Run memory_os_owner_cron_onboarding.py --apply instead. "
        "Use --cleanup here to remove a leftover standalone job."
    )
    result["actions"] = []
    return result


def run_smoke(hermes_home: Path) -> dict[str, Any]:
    """Run the probe immediately to verify the deployment works."""
    import subprocess
    helper = DEPLOY_HELPER

    if not helper.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "phase": "smoke",
            "status": "error",
            "error": f"Helper not found at {helper}",
        }

    # Pre-flight: verify the repo root config points to valid Memory-OS source
    repo_root_file = helper.with_name("l3_probe_repo_root.txt")
    repo_root_check = _check_deployed_repo_root(repo_root_file)
    if not repo_root_check["valid"]:
        return {
            "schema_version": SCHEMA_VERSION,
            "phase": "smoke",
            "status": "error",
            "error": f"Repo root config invalid: {repo_root_check['error']}",
            "repo_root_check": repo_root_check,
        }

    result = subprocess.run(
        [sys.executable, str(helper), "--smoke"],
        capture_output=True, text=True, timeout=120,
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    try:
        parsed: dict = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        parsed = {"raw_stdout": stdout[:1000]}

    details_dict = parsed.get("details", {})
    verdict = details_dict.get("verdict", "") if isinstance(details_dict, dict) else ""
    passed = (
        result.returncode == 0
        and "GOVERNANCE PATH" in str(parsed)
        or "GOVERNANCE PATH" in str(verdict)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "smoke",
        "status": "passed" if passed else "failed",
        "returncode": result.returncode,
        "verdict": verdict,
        "repo_root_check": repo_root_check,
        "raw_parsed": parsed,
        "stderr_truncated": stderr[-500:] if stderr else None,
    }


def run_cleanup(hermes_home: Path) -> dict[str, Any]:
    """Remove cron job and helper script."""
    actions: list[dict[str, Any]] = []

    # Remove cron job
    jobs = HermesCronAdapter(hermes_home=hermes_home).read_jobs()
    existing = _find_job_by_name(jobs, JOB_NAME)
    if existing:
        job_id = str(existing.get("job_id") or existing.get("id") or "")
        if job_id:
            env = dict(os.environ)
            env["HERMES_HOME"] = str(hermes_home)
            completed = subprocess.run(
                [HERMES_BIN, "cron", "remove", job_id],
                check=False, text=True, capture_output=True, env=env,
            )
            actions.append({
                "action": "remove_cron_job",
                "job_id": job_id,
                "status": "removed" if completed.returncode == 0 else "error",
                "stderr": (completed.stderr or "").strip()[:300] if completed.returncode != 0 else "",
            })
    else:
        actions.append({"action": "remove_cron_job", "status": "not_found"})

    # Remove helper
    if DEPLOY_HELPER.exists():
        DEPLOY_HELPER.unlink()
        actions.append({"action": "remove_helper", "path": str(DEPLOY_HELPER), "status": "removed"})
    else:
        actions.append({"action": "remove_helper", "status": "not_found"})

    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "cleanup",
        "actions": actions,
        "status": "cleaned",
    }


# ── helpers ────────────────────────────────────────────────────────

def _find_job_by_name(jobs: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for job in jobs:
        if str(job.get("name") or "") == name:
            return job
    return None


def _verify_written_repo_root(config_file: Path, repo_root: Path) -> None:
    """Fail-loud if the just-written repo_root doesn't look like Memory-OS source.

    This prevents the "wrong path silently accepted" class of failure:
    if deploy runs from a non-standard location and writes a path that
    isn't actually a Memory-OS clone, we catch it here rather than
    letting the cron helper silently run against wrong/old source.
    """
    missing = [m for m in _MEMORY_OS_IDENTITY_MARKERS if not (repo_root / m).is_file()]
    if missing:
        raise SystemExit(
            f"Deploy refused: REPO_ROOT ({repo_root}) does not appear to be a "
            f"Memory-OS repository. Missing marker files: {', '.join(missing)}. "
            "Run deploy from within a Memory-OS clone, or set REPO_ROOT "
            "manually in the script before deploying."
        )


def _check_deployed_repo_root(config_file: Path) -> dict:
    """Verify the deployed l3_probe_repo_root.txt points to valid source."""
    if not config_file.is_file():
        return {"valid": False, "error": f"Config file missing: {config_file}"}
    try:
        candidate = Path(config_file.read_text(encoding="utf-8").strip())
    except Exception as exc:
        return {"valid": False, "error": f"Cannot read config: {exc}"}

    if not candidate.is_dir():
        return {"valid": False, "error": f"Path does not exist: {candidate}"}

    missing = [m for m in _MEMORY_OS_IDENTITY_MARKERS if not (candidate / m).is_file()]
    if missing:
        return {
            "valid": False,
            "error": f"Path {candidate} is not a Memory-OS repo. Missing: {', '.join(missing)}",
        }

    return {"valid": True, "repo_root": str(candidate)}


# ── main ───────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hermes_home = Path(args.hermes_home).expanduser().resolve()

    if args.cleanup:
        report = run_cleanup(hermes_home)
    elif args.apply:
        report = run_apply(hermes_home)
        if args.smoke and report.get("status") == "applied":
            smoke = run_smoke(hermes_home)
            report["smoke"] = smoke
    elif args.dry_run:
        report = run_dry_run(hermes_home)
    else:
        report = run_plan(hermes_home)

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report.get("status") in ("error", "failed"):
        return 2
    if args.smoke and report.get("smoke", {}).get("status") == "failed":
        return 2
    return 0


# Inline fallback helper (should not be needed since SOURCE_HELPER exists)
# Reads repo root from config file written alongside it during deploy.
_FALLBACK_HELPER = """\
#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path

def _is_repo(p):
    return p.is_dir() and (p / "pyproject.toml").is_file() and (p / "plugins/memory/memory_os/__init__.py").is_file()

_repo_env = os.environ.get("MEMORY_OS_REPO_ROOT", "").strip()
_repo = None
if _repo_env:
    _c = Path(_repo_env)
    if _is_repo(_c): _repo = _c
    elif _c.is_dir():
        raise SystemExit(f"MEMORY_OS_REPO_ROOT ({_c}) is not a Memory-OS repo")
if _repo is None:
    _root_txt = Path(__file__).with_name("l3_probe_repo_root.txt")
    if _root_txt.is_file():
        _c = Path(_root_txt.read_text(encoding="utf-8").strip())
        if _is_repo(_c): _repo = _c
        elif _c.is_dir():
            raise SystemExit(f"l3_probe_repo_root.txt ({_c}) is not a Memory-OS repo")
if _repo is None:
    raise SystemExit("Cannot resolve Memory-OS repo root; set MEMORY_OS_REPO_ROOT or l3_probe_repo_root.txt")
p = _repo / "scripts" / "probe_l3_prefetch_behavior.py"
r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True, timeout=120, cwd=str(_repo))
all_pass = r.returncode == 0 and "GOVERNANCE PATH" in (r.stdout or "")
if "--smoke" in sys.argv:
    print(json.dumps({"status":"smoke","returncode":r.returncode,"stdout":(r.stdout or "")[:1000]}))
elif not all_pass:
    print(json.dumps({"status":"L3_FAIL","returncode":r.returncode,"stderr":(r.stderr or "")[:500]}))
raise SystemExit(0 if all_pass else 1)
"""

if __name__ == "__main__":
    raise SystemExit(main())
