#!/usr/bin/env python3
"""Memory-OS Hindsight health probe (no_agent, L2 optional).

Checks whether the Hindsight advisory substrate is configured, reachable,
and healthy.  Returns a structured status that distinguishes:

* ``disabled`` — provider not enabled in config
* ``unconfigured`` — enabled but missing api_url / bank_id
* ``timeout`` — endpoint unreachable
* ``unhealthy`` — endpoint reachable but error response
* ``healthy`` — endpoint reachable and responding

Fail-open: probe failures never affect Memory-OS core operations.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Location-agnostic import resolution.
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]


def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    """Extract a --flag value from raw argv before argparse runs."""
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            val = argv[i + 1]
            if val.startswith("--"):
                return ""  # next token is another flag, not a value
            return val
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


# Resolve HERMES_HOME at module level — CLI > env > default.
_CLI_HOME = _preparse_cli_arg(sys.argv, "--hermes-home")
_ENV_HOME = os.environ.get("HERMES_HOME", "")
_HERMES_HOME = _CLI_HOME or _ENV_HOME or str(Path.home() / ".hermes")

if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.lane_last_run import record_lane_last_run
from plugins.memory.memory_os.substrates.hindsight import GovernedHindsightConfig


def _read_hindsight_config(hermes_home: str) -> dict[str, Any] | None:
    """Read hindsight config from memory-os config.json."""
    import json as _json
    cfg_path = Path(hermes_home) / "memory-os" / "config.json"
    if not cfg_path.exists():
        return None
    try:
        cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    substrates = cfg.get("substrate_providers", {})
    if not isinstance(substrates, dict):
        return None
    return substrates.get("hindsight")


def probe_hindsight_health(
    hermes_home: str,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Probe Hindsight service health.

    Returns a dict with ``status``, ``health``, and diagnostic fields.
    Never raises — fail-open.
    """
    raw = _read_hindsight_config(hermes_home)

    if raw is None or not isinstance(raw, dict) or not raw.get("enabled"):
        return {
            "schema_version": "memory-os.hindsight_health.v0",
            "status": "disabled",
            "health": "disabled",
            "reason": "hindsight_not_enabled",
            "config": None,
            "latency_ms": 0,
        }

    config = GovernedHindsightConfig.from_dict(raw)

    # Check minimum configuration
    if not config.api_url or not config.bank_id:
        return {
            "schema_version": "memory-os.hindsight_health.v0",
            "status": "unconfigured",
            "health": "unconfigured",
            "reason": "missing_api_url_or_bank_id",
            "config": {
                "recall_mode": config.recall_mode,
                "reflect_enabled": config.reflect_enabled,
                "bank_id": config.bank_id or "",
            },
            "latency_ms": 0,
        }

    t0 = time.monotonic()
    try:
        import urllib.request as _req
        url = f"{config.api_url.rstrip('/')}/health"
        req = _req.Request(url)
        if config.api_key:
            req.add_header("Authorization", f"Bearer {config.api_key}")
        resp = _req.urlopen(req, timeout=timeout_seconds)
        body = json.loads(resp.read().decode("utf-8"))
        latency_ms = int((time.monotonic() - t0) * 1000)

        if resp.status == 200:
            return {
                "schema_version": "memory-os.hindsight_health.v0",
                "status": "healthy",
                "health": "healthy",
                "config": {
                    "recall_mode": config.recall_mode,
                    "reflect_enabled": config.reflect_enabled,
                    "bank_id": config.bank_id,
                    "api_url": config.api_url,
                },
                "response": body,
                "latency_ms": latency_ms,
            }
        else:
            return {
                "schema_version": "memory-os.hindsight_health.v0",
                "status": "unhealthy",
                "health": "unhealthy",
                "reason": f"non_200_status_{resp.status}",
                "config": {"recall_mode": config.recall_mode},
                "latency_ms": latency_ms,
            }
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        error_str = str(exc)[:200]
        if "timeout" in error_str.lower() or "timed out" in error_str.lower():
            health = "timeout"
        elif "refused" in error_str.lower() or "name or service not known" in error_str.lower():
            health = "unreachable"
        else:
            health = "unhealthy"
        return {
            "schema_version": "memory-os.hindsight_health.v0",
            "status": health,
            "health": health,
            "reason": error_str,
            "config": {
                "recall_mode": config.recall_mode,
                "api_url": config.api_url,
            },
            "latency_ms": latency_ms,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe Hindsight advisory substrate health (L2 optional).",
    )
    parser.add_argument("--hermes-home", default=_HERMES_HOME)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output", choices=("json",), default="json")
    args = parser.parse_args(argv)

    report = probe_hindsight_health(args.hermes_home, timeout_seconds=args.timeout)
    # The probe's taxonomy used to be stdout-only, leaving a broken substrate
    # indistinguishable from an idle one on disk.  Persist the closed outcome
    # set so readers never have to re-run the probe.
    outcome = str(report.get("status") or "unknown")
    record_lane_last_run(
        args.hermes_home,
        "hindsight_health_probe",
        status="ok",
        reason=outcome,
        counters={"latency_ms": int(report.get("latency_ms") or 0)},
        error=str(report.get("reason") or "") if outcome in ("timeout", "unreachable", "unhealthy") else "",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
