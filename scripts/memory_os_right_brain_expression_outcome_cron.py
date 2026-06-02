#!/usr/bin/env python3
"""Cron wrapper that records right-brain expression outcomes."""

from __future__ import annotations

try:
    from memory_os_execution_report import write_helper_execution_report
except ModuleNotFoundError:
    from scripts.memory_os_execution_report import write_helper_execution_report
from memory_os_right_brain_expression_outcome import main


if __name__ == "__main__":
    result = main(["--apply"])
    write_helper_execution_report(result_summary={"returncode": result, "mode": "apply"})
    raise SystemExit(result)
