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
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.hermes_cron_adapter import HermesCronAdapter
from plugins.memory.memory_os.cron_registry import memory_os_cron_spec_by_key, write_cron_registry_snapshot

SCHEMA_VERSION = "memory-os.l3_probe_deploy.v0"

# ── file constants ─────────────────────────────────────────────────
HERMES_SCRIPTS = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "scripts"
SOURCE_HELPER = REPO_ROOT / "scripts" / "memory_os_l3_probe_helper.py"
DEPLOY_HELPER = HERMES_SCRIPTS / "memory_os_l3_probe_helper.py"
REGISTRY_PATH = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "memory-os" / "system" / "memory_os_cron_registry.json"

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
    actions: list[dict[str, Any]] = []

    # Step 1: ensure scripts dir exists
    HERMES_SCRIPTS.mkdir(parents=True, exist_ok=True)

    # Step 2: deploy helper script
    if SOURCE_HELPER.is_file():
        shutil.copy2(SOURCE_HELPER, DEPLOY_HELPER)
        DEPLOY_HELPER.chmod(DEPLOY_HELPER.stat().st_mode | stat.S_IXUSR)
        actions.append({
            "action": "deploy_helper",
            "source": str(SOURCE_HELPER),
            "target": str(DEPLOY_HELPER),
            "status": "copied",
        })
    else:
        # Fallback: write helper inline
        DEPLOY_HELPER.write_text(_FALLBACK_HELPER, encoding="utf-8")
        DEPLOY_HELPER.chmod(DEPLOY_HELPER.stat().st_mode | stat.S_IXUSR)
        actions.append({
            "action": "deploy_helper",
            "source": "inline",
            "target": str(DEPLOY_HELPER),
            "status": "written",
        })
    # Write repo root config so the deployed helper can find probe_l3_prefetch_behavior.py
    repo_root_file = DEPLOY_HELPER.with_name("l3_probe_repo_root.txt")
    repo_root_file.write_text(str(REPO_ROOT), encoding="utf-8")
    actions.append({
        "action": "write_repo_root_config",
        "path": str(repo_root_file),
        "repo_root": str(REPO_ROOT),
    })
    result["helper_deployed"] = True

    # Step 3: create cron job via Hermes CLI
    if SOURCE_HELPER.is_file():
        # Use the onboarder's cron registry snapshot update pattern
        _ensure_registry_snapshot_exists(hermes_home)
    else:
        _ensure_registry_snapshot_exists(hermes_home)

    cron_result = _ensure_cron_job(hermes_home)
    actions.append(cron_result)
    result["cron_job"] = cron_result

    result["actions"] = actions
    result["status"] = "applied" if cron_result.get("status") in ("applied", "already_configured", "updated") else "error"
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


def _ensure_registry_snapshot_exists(hermes_home: Path) -> dict[str, Any]:
    """Ensure the cron registry snapshot exists (writes from central MEMORY_OS_CRON_SPECS)."""
    registry_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    central_spec = memory_os_cron_spec_by_key("l3_probe_verification")
    if central_spec is None:
        return {"status": "error", "reason": "l3_probe_verification not found in central MEMORY_OS_CRON_SPECS"}
    spec_dict = central_spec.to_json()
    if registry_path.exists():
        loaded = json.loads(registry_path.read_text(encoding="utf-8"))
        specs = loaded.get("specs", [])
        for spec in specs:
            if spec.get("key") == "l3_probe_verification":
                return {"status": "already_registered"}
        specs.append(spec_dict)
        registry_path.write_text(
            json.dumps({**loaded, "specs": specs}, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return {"status": "registered"}
    else:
        write_cron_registry_snapshot(registry_path)
        return {"status": "created"}


def _ensure_cron_job(hermes_home: Path) -> dict[str, Any]:
    """Create or update the cron job via hermes CLI."""
    adapter = HermesCronAdapter(hermes_home=hermes_home, hermes_bin=HERMES_BIN)
    existing = _find_job_by_name(adapter.read_jobs(), JOB_NAME)
    env = dict(os.environ)
    env["HERMES_HOME"] = str(hermes_home)

    if existing:
        job_id = str(existing.get("job_id") or existing.get("id") or "")
        # Update via hermes cron edit
        completed = subprocess.run(
            [HERMES_BIN, "cron", "edit", job_id,
             "--schedule", SCHEDULE,
             "--script", DEPLOY_HELPER.name,
             "--deliver", DELIVER],
            check=False, text=True, capture_output=True, env=env,
        )
        if completed.returncode != 0:
            return {
                "action": "update_cron_job",
                "job_id": job_id,
                "status": "error",
                "stderr": (completed.stderr or completed.stdout or "").strip()[:500],
            }
        return {
            "action": "update_cron_job",
            "job_id": job_id,
            "status": "updated",
        }

    # Create new job via hermes cron create
    completed = subprocess.run(
        [HERMES_BIN, "cron", "create",
         "--name", JOB_NAME,
         "--schedule", SCHEDULE,
         "--script", DEPLOY_HELPER.name,
         "--no-agent",
         "--deliver", DELIVER],
        check=False, text=True, capture_output=True, env=env,
    )
    if completed.returncode != 0:
        return {
            "action": "create_cron_job",
            "status": "error",
            "stderr": (completed.stderr or completed.stdout or "").strip()[:500],
        }
    created = _find_job_by_name(adapter.read_jobs(), JOB_NAME)
    return {
        "action": "create_cron_job",
        "job_id": str((created or {}).get("job_id") or (created or {}).get("id") or ""),
        "status": "applied",
    }


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
_root_txt = Path(__file__).with_name("l3_probe_repo_root.txt")
if _root_txt.is_file():
    _repo = Path(_root_txt.read_text(encoding="utf-8").strip())
else:
    _repo = Path(os.environ.get("MEMORY_OS_REPO_ROOT", "/opt/Hermes-Memory-OS"))
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
