#!/usr/bin/env python3
"""Cron wrapper that writes Memory-OS module cadence evidence."""

from __future__ import annotations

try:
    from memory_os_execution_report import write_helper_execution_report
except ModuleNotFoundError:
    from scripts.memory_os_execution_report import write_helper_execution_report
from memory_os_module_cadence_report import main


if __name__ == "__main__":
    result = main(["--apply", "--format", "summary"])
    write_helper_execution_report(result_summary={"returncode": result, "mode": "apply_summary"})
    raise SystemExit(result)
