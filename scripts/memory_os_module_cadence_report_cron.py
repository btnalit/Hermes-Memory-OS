#!/usr/bin/env python3
"""Cron wrapper that writes Memory-OS module cadence evidence."""

from __future__ import annotations

from memory_os_module_cadence_report import main


if __name__ == "__main__":
    raise SystemExit(main(["--apply", "--format", "summary"]))
