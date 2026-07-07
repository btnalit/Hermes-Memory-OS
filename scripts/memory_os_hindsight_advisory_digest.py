#!/usr/bin/env python3
"""Memory-OS Hindsight advisory digest (weekly, L2 optional).

Calls Hindsight reflect and emits an advisory-only owner finding.
Advisory findings appear in the owner digest as non-actionable notes —
they never auto-write canonical memory, never bypass owner governance,
and always carry ``advisory_only=True``.

Designed for weekly cron execution (independent of cognitive_loop,
constraint 4).  Timeout protection prevents hanging (constraint 5).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Location-agnostic import resolution.
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]
_HERMES_HOME = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")

if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.substrates.hindsight import GovernedHindsightConfig

# Reuse shared config reader from health probe (code-review fix: dedup)
from scripts.memory_os_hindsight_health_probe import _read_hindsight_config


def _get_hindsight_client(config: GovernedHindsightConfig) -> Any | None:
    """Build a Hindsight HTTP client from config. Returns None if not configured."""
    if not config.api_url or not config.api_key:
        return None
    try:
        from plugins.memory.memory_os.adapters.hindsight import HindsightHttpClient
        return HindsightHttpClient(
            api_url=config.api_url,
            api_key=config.api_key,
            timeout=5.0,
        )
    except Exception:
        return None


def _write_advisory_finding(
    hermes_home: str,
    content: str,
    *,
    kind: str = "hindsight_advisory_note",
    advisory_only: bool = True,
) -> Path:
    """Write an advisory finding to the system-modules directory for owner digest pickup.

    Advisory findings are owner-visible but non-actionable — they never
    write canonical memory and never bypass the owner review gate.
    """
    out_dir = Path(hermes_home) / "memory-os" / "system-modules" / "advisory"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "hindsight_advisory.json"

    finding: dict[str, Any] = {
        "schema_version": "memory-os.hindsight_advisory.v0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "advisory_only": advisory_only,
        "content": content[:2000],
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    }
    try:
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(finding, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(out_path)
    except OSError:
        pass
    return out_path


def run_advisory_digest(
    hermes_home: str,
    *,
    timeout: float = 5.0,
    query: str = "What patterns can you offer about recent memory usage?",
    budget: str = "medium",
) -> dict[str, Any]:
    """Run one Hindsight reflection cycle and emit an advisory finding.

    Returns a structured report.  Never raises — fail-open (constraint 2).
    """
    t0 = time.monotonic()
    raw = _read_hindsight_config(hermes_home)

    if raw is None or not isinstance(raw, dict) or not raw.get("enabled"):
        return {
            "schema_version": "memory-os.hindsight_advisory_digest.v0",
            "status": "disabled",
            "reason": "hindsight_not_enabled",
            "advisory_emitted": False,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    config = GovernedHindsightConfig.from_dict(raw)

    if not config.reflect_enabled:
        return {
            "schema_version": "memory-os.hindsight_advisory_digest.v0",
            "status": "disabled",
            "reason": "reflect_not_enabled",
            "advisory_emitted": False,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    if not config.api_url or not config.bank_id:
        return {
            "schema_version": "memory-os.hindsight_advisory_digest.v0",
            "status": "unconfigured",
            "reason": "missing_api_url_or_bank_id",
            "advisory_emitted": False,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    # ── Build substrate and attempt reflect ──────────────────────────
    try:
        from plugins.memory.memory_os.substrates.hindsight import GovernedHindsightSubstrate

        client = _get_hindsight_client(config)
        substrate = GovernedHindsightSubstrate(config, client=client)

        health = substrate.health()
        if health.status != "ok":
            return {
                "schema_version": "memory-os.hindsight_advisory_digest.v0",
                "status": health.status,
                "reason": health.reason or "substrate_not_healthy",
                "advisory_emitted": False,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }

        result = substrate.reflect(query=query, consumer="weekly_advisory_digest")

        if result.get("status") != "ok":
            return {
                "schema_version": "memory-os.hindsight_advisory_digest.v0",
                "status": result.get("status", "no_result"),
                "reason": result.get("reason", "reflect_returned_non_ok"),
                "advisory_emitted": False,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }

        # ── Extract summary from reflect response ───────────────────
        response = result.get("response", {})
        summary = ""
        if isinstance(response, dict):
            summary = str(
                response.get("summary")
                or response.get("reflection")
                or response.get("text")
                or response.get("result")
                or ""
            ).strip()
        if not summary and isinstance(response, dict):
            # Try to construct from response keys
            parts = []
            for key in ("observations", "patterns", "themes", "insights"):
                val = response.get(key)
                if isinstance(val, list):
                    parts.extend(str(v) for v in val[:3] if v)
                elif isinstance(val, str) and val.strip():
                    parts.append(val)
            summary = "; ".join(parts[:5]) if parts else ""

        if not summary:
            summary = "Hindsight reflect completed but produced no extractable summary."

        # ── Emit advisory finding ───────────────────────────────────
        _write_advisory_finding(
            hermes_home,
            summary,
            kind="hindsight_advisory_note",
            advisory_only=True,
        )

        return {
            "schema_version": "memory-os.hindsight_advisory_digest.v0",
            "status": "ok",
            "advisory_emitted": True,
            "advisory_only": True,
            "provenance": "reflect_synthesized",
            "summary": summary[:500],
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        error_str = str(exc)[:200]
        if "timeout" in error_str.lower() or "timed out" in error_str.lower():
            status = "timeout"
        else:
            status = "error"
        return {
            "schema_version": "memory-os.hindsight_advisory_digest.v0",
            "status": status,
            "reason": error_str,
            "advisory_emitted": False,
            "latency_ms": latency_ms,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Weekly Hindsight advisory digest (L2 optional, advisory only).",
    )
    parser.add_argument("--hermes-home", default=_HERMES_HOME)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--query",
        default="What patterns can you offer about recent memory usage?",
        help="Reflect query for Hindsight.",
    )
    parser.add_argument("--budget", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--output", choices=("json",), default="json")
    args = parser.parse_args(argv)

    report = run_advisory_digest(
        args.hermes_home,
        timeout=args.timeout,
        query=args.query,
        budget=args.budget,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "ok" or report.get("status") == "disabled" else 2


if __name__ == "__main__":
    sys.exit(main())
