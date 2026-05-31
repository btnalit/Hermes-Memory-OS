#!/usr/bin/env python3
"""Compare pre/post Hermes upgrade evidence for Memory-OS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.hermes_upgrade_evidence_compare.v0"


def compare_evidence(
    *,
    pre_compat: dict[str, Any],
    post_compat: dict[str, Any],
    pre_monitor: dict[str, Any] | None = None,
    post_monitor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    compat = _compare_classification("compat", pre_compat, post_compat)
    monitor = (
        _compare_classification("monitor", pre_monitor, post_monitor)
        if pre_monitor is not None and post_monitor is not None
        else _not_provided("monitor")
    )
    hermes_version = {
        "pre": _command_preview(pre_compat, "hermes_version"),
        "post": _command_preview(post_compat, "hermes_version"),
        "changed": _command_preview(pre_compat, "hermes_version") != _command_preview(post_compat, "hermes_version"),
    }

    classification = _classify(compat=compat, monitor=monitor)
    return {
        "schema_version": SCHEMA_VERSION,
        "hermes_version": hermes_version,
        "compat": compat,
        "monitor": monitor,
        "classification": classification,
    }


def render_summary(report: dict[str, Any]) -> str:
    classification = report["classification"]
    lines = [
        f"Memory-OS Hermes upgrade evidence compare: {classification['status']}",
        f"- hermes_version_pre={report['hermes_version']['pre'] or '(unknown)'}",
        f"- hermes_version_post={report['hermes_version']['post'] or '(unknown)'}",
        f"- hermes_version_changed={report['hermes_version']['changed']}",
    ]
    for section_name in ("compat", "monitor"):
        section = report[section_name]
        lines.append(
            f"- {section_name}: provided={section['provided']} "
            f"pre_fail={section['pre_fail_codes']} post_fail={section['post_fail_codes']} "
            f"new_fail={section['new_fail_codes']} new_warn={section['new_warn_codes']}"
        )
    lines.append(f"PASS: {[item['code'] for item in classification['pass']]}")
    lines.append(f"WARN: {[item['code'] for item in classification['warn']]}")
    lines.append(f"FAIL: {[item['code'] for item in classification['fail']]}")
    return "\n".join(lines)


def _compare_classification(name: str, pre: dict[str, Any] | None, post: dict[str, Any] | None) -> dict[str, Any]:
    if pre is None or post is None:
        return _not_provided(name)
    pre_classification = _classification(pre)
    post_classification = _classification(post)
    pre_fail = _codes(pre_classification.get("fail", []))
    post_fail = _codes(post_classification.get("fail", []))
    pre_warn = _codes(pre_classification.get("warn", []))
    post_warn = _codes(post_classification.get("warn", []))
    return {
        "provided": True,
        "pre_status": _status(pre_classification),
        "post_status": _status(post_classification),
        "pre_fail_codes": pre_fail,
        "post_fail_codes": post_fail,
        "new_fail_codes": sorted(set(post_fail) - set(pre_fail)),
        "pre_warn_codes": pre_warn,
        "post_warn_codes": post_warn,
        "new_warn_codes": sorted(set(post_warn) - set(pre_warn)),
    }


def _not_provided(name: str) -> dict[str, Any]:
    return {
        "provided": False,
        "pre_status": "",
        "post_status": "",
        "pre_fail_codes": [],
        "post_fail_codes": [],
        "new_fail_codes": [],
        "pre_warn_codes": [],
        "post_warn_codes": [],
        "new_warn_codes": [],
        "reason": f"{name}_evidence_not_provided",
    }


def _classify(*, compat: dict[str, Any], monitor: dict[str, Any]) -> dict[str, list[dict[str, Any]] | str]:
    passed: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []
    fail: list[dict[str, Any]] = []

    _classify_section("compat", compat, passed, warn, fail)
    _classify_section("monitor", monitor, passed, warn, fail)

    return {
        "status": "FAIL" if fail else "WARN" if warn else "PASS",
        "pass": passed,
        "warn": warn,
        "fail": fail,
    }


def _classify_section(
    prefix: str,
    section: dict[str, Any],
    passed: list[dict[str, Any]],
    warn: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    if not section["provided"]:
        warn.append({"code": f"{prefix}_evidence_missing"})
        return
    if section["post_fail_codes"]:
        fail.append({"code": f"{prefix}_post_fail", "codes": section["post_fail_codes"]})
    elif section["new_fail_codes"]:
        fail.append({"code": f"{prefix}_new_fail", "codes": section["new_fail_codes"]})
    else:
        passed.append({"code": f"{prefix}_no_post_fail"})
    if section["new_warn_codes"]:
        warn.append({"code": f"{prefix}_new_warn", "codes": section["new_warn_codes"]})


def _classification(report: dict[str, Any]) -> dict[str, Any]:
    classification = report.get("classification")
    if isinstance(classification, dict):
        return classification
    return {"pass": [], "warn": [], "fail": [{"code": "classification_missing"}]}


def _status(classification: dict[str, Any]) -> str:
    if classification.get("status"):
        return str(classification["status"])
    return "FAIL" if classification.get("fail") else "WARN" if classification.get("warn") else "PASS"


def _codes(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    codes: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("code"):
            codes.append(str(item["code"]))
        elif isinstance(item, str):
            codes.append(item)
    return sorted(set(codes))


def _command_preview(report: dict[str, Any], command_name: str) -> str:
    commands = report.get("commands")
    if not isinstance(commands, dict):
        return ""
    command = commands.get(command_name)
    if not isinstance(command, dict):
        return ""
    return str(command.get("stdout_preview") or command.get("stderr_preview") or "").splitlines()[0:1][0] if (
        command.get("stdout_preview") or command.get("stderr_preview")
    ) else ""


def _read_json(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise SystemExit(f"{path} did not contain a JSON object")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-compat", type=Path, required=True)
    parser.add_argument("--post-compat", type=Path, required=True)
    parser.add_argument("--pre-monitor", type=Path)
    parser.add_argument("--post-monitor", type=Path)
    parser.add_argument("--output", choices=["summary", "json"], default="summary")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when compare status is not PASS.")
    args = parser.parse_args(argv)

    report = compare_evidence(
        pre_compat=_read_json(args.pre_compat),
        post_compat=_read_json(args.post_compat),
        pre_monitor=_read_json(args.pre_monitor) if args.pre_monitor else None,
        post_monitor=_read_json(args.post_monitor) if args.post_monitor else None,
    )
    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_summary(report))
    if args.strict and report["classification"]["status"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
