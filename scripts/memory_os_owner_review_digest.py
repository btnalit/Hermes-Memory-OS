#!/usr/bin/env python3
"""Render a bounded Memory-OS owner review digest for Hermes cron delivery.

This script intentionally does not send messages. Hermes cron owns scheduling
and delivery via `hermes cron create ... --script ... --deliver ...` in agent
mode. The script prints a bounded review brief only when there is meaningful
review content; empty stdout lets Hermes cron stay silent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from memory_os_execution_report import write_helper_execution_report
except ModuleNotFoundError:
    from scripts.memory_os_execution_report import write_helper_execution_report


def main() -> int:
    owner = os.environ.get("MEMORY_OS_OWNER_REVIEW_OWNER", "owner")
    channel = os.environ.get("MEMORY_OS_OWNER_REVIEW_CHANNEL", "")
    digest_mode = os.environ.get("MEMORY_OS_OWNER_REVIEW_DIGEST_MODE", "agenda").strip() or "agenda"
    limits = _limit_args()

    if not channel:
        channel = _resolve_channel()

    delivery_ref = "cron_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    render = _run_json(
        [
            "hermes",
            "memory-os-agent-os",
            "review",
            "render-delivery-digest",
            "--owner",
            owner,
            "--channel",
            channel,
            "--delivery-ref",
            delivery_ref,
            "--format",
            "json",
            "--mode",
            digest_mode,
            *limits,
        ]
    )
    if not _has_meaningful_content(render, digest_mode=digest_mode):
        return 0
    text = str(render.get("text") or "").strip()
    if text:
        print(text)
        sys.stdout.flush()
        delivery = render.get("permanent_promotion_delivery")
        proposal_ids = (
            delivery.get("shown_proposal_ids")
            if isinstance(delivery, dict) and isinstance(delivery.get("shown_proposal_ids"), list)
            else []
        )
        if proposal_ids:
            ack_command = [
                "hermes",
                "memory-os-agent-os",
                "review",
                "ack-delivery-digest",
                "--delivery-ref",
                delivery_ref,
                "--ack-source",
                "hermes_cron_emission",
            ]
            for proposal_id in proposal_ids:
                ack_command.extend(["--proposal-id", str(proposal_id)])
            _run_json(ack_command)
    return 0


def _limit_args() -> list[str]:
    args: list[str] = []
    for env_name, cli_name in (
        ("MEMORY_OS_OWNER_REVIEW_MAX_ACTION_REQUIRED", "--max-action-required"),
        ("MEMORY_OS_OWNER_REVIEW_MAX_REVIEW_SUGGESTED", "--max-review-suggested"),
        ("MEMORY_OS_OWNER_REVIEW_MAX_FYI", "--max-fyi"),
    ):
        value = os.environ.get(env_name, "").strip()
        if value:
            args.extend([cli_name, value])
    return args


def _has_meaningful_content(preview: dict[str, object], *, digest_mode: str = "review") -> bool:
    counts = preview.get("counts")
    if not isinstance(counts, dict):
        return False
    if str(digest_mode).strip().lower().replace("-", "_") == "agenda":
        # The recurring owner agenda should push only explicit decisions or
        # real alerts. Review-suggested and FYI items remain available through
        # the pull-based review surface, not daily Telegram noise.
        return int(counts.get("action_required_shown") or 0) > 0
    shown = (
        int(counts.get("action_required_shown") or 0)
        + int(counts.get("review_suggested_shown") or 0)
        + int(counts.get("fyi_shown") or 0)
    )
    return shown > 0


def _resolve_channel() -> str:
    configured = _configured_recurring_channel()
    if configured:
        return configured
    report = _run_json(["hermes", "memory-os-agent-os", "review", "channel"])
    channel = str(report.get("channel") or "").strip()
    return channel or "owner_review_cron"


def _configured_recurring_channel() -> str:
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    path = hermes_home / "memory-os" / "config.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(loaded, dict):
        return ""
    owner_review = loaded.get("owner_review")
    if not isinstance(owner_review, dict):
        return ""
    return str(owner_review.get("recurring_delivery_channel") or "").strip()


def _run_json(command: list[str]) -> dict[str, object]:
    output = _run_text(command)
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Memory-OS owner review command did not return JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("Memory-OS owner review command returned non-object JSON")
    return parsed


def _run_text(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise SystemExit("hermes command not found; cannot render owner review digest") from exc
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or exc.stdout or str(exc))
        raise SystemExit(exc.returncode) from exc
    return completed.stdout


if __name__ == "__main__":
    result = main()
    write_helper_execution_report(result_summary={"returncode": result, "helper": "owner_review_digest"})
    raise SystemExit(result)
