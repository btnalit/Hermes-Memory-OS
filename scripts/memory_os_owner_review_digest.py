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
from pathlib import Path


def main() -> int:
    owner = os.environ.get("MEMORY_OS_OWNER_REVIEW_OWNER", "owner")
    channel = os.environ.get("MEMORY_OS_OWNER_REVIEW_CHANNEL", "")
    limits = _limit_args()

    preview = _run_json(["hermes", "memory-os-agent-os", "review", "preview-digest", "--owner", owner, *limits])
    if not _has_meaningful_content(preview):
        return 0

    if not channel:
        channel = _resolve_channel()

    render = _run_text(
        [
            "hermes",
            "memory-os-agent-os",
            "review",
            "render-digest",
            "--owner",
            owner,
            "--channel",
            channel,
            "--format",
            "text",
            "--bounded",
            "--record-active",
            *limits,
        ]
    )
    text = render.strip()
    if text:
        print(text)
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


def _has_meaningful_content(preview: dict[str, object]) -> bool:
    counts = preview.get("counts")
    if not isinstance(counts, dict):
        return False
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
    raise SystemExit(main())
