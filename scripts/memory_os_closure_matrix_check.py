#!/usr/bin/env python3
"""Check that Memory-OS modules are represented in the RH-36 closure matrix."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.closure_matrix_check.v1"

VALID_DELIVERY_CLASSES = {
    "none",
    "owner_origin",
    "internal_local",
    "no_agent_script",
    "hermes_mailbox_internal",
}

VALID_STATE_CHANGE_CLASSES = {
    "none",
    "monitor_only",
    "context_projection",
    "candidate_review",
    "proposal_review",
    "feedback_ledger",
    "expression_feedback",
    "speak_permission",
    "retention_metadata",
}

VALID_CADENCE_CLASSES = {
    "event_driven_fast",
    "cycle_each",
    "daily_once",
    "weekly_once",
    "owner_daily",
    "on_demand",
    "monitor_poll",
    "disabled_until_opt_in",
}

LIVE_MODULE_TO_CLOSURE_LABEL = {
    "cron_mirror": "Cron / Session / State Mirrors",
    "session_mirror": "Cron / Session / State Mirrors",
    "state_source_mirror": "Cron / Session / State Mirrors",
    "shadow_journal": "Cron / Session / State Mirrors",
    "deep_reflection": "DeepReflection",
    "governance_feedback": "Governance Feedback",
    "digest_consolidation": "Digest Consolidation",
    "inner_drive": "Heartbeat / Inner Drive",
    "mailbox": "Mailbox",
    "household_digest": "Household Digest",
    "wandering_mind": "Wandering Mind",
    "evidence_scoring": "Evidence Scoring",
    "ops_gate": "Ops Gate",
    "proposal_queue": "Proposal Queue",
    "self_evolution": "Self-Evolution",
    "speak_gate": "Speak Gate",
}

REQUIRED_CONTRACT_LABELS = {
    "Conversation Carryover",
    "Context Router / Low-Clue Recall",
    "MemorySources Attribution",
    "RH-31 Eval Harness",
    "Metadata Retention",
    "Owner Review Queue / Aging",
    "Review Digest Renderer",
    "Agent / Memory-OS Collaboration Contract",
    "Right-Brain Expression Closure Contract",
    "Left-Brain Governance Quality Contract",
    "Agent-Mediated Review Surface",
    "Agent-Mediated Owner Reply Tool",
    "Owner Reply Parser",
    "OwnerActionProcessor",
    "Owner Review Hermes Cron Helper",
}

ACTIVE_WORK_ITEM_RE = re.compile(r"^### (P1-[A-Z]|P2-F) - ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--format", choices=["json", "summary"], default="json")
    args = parser.parse_args(argv)

    report = build_report(Path(args.repo_root).resolve())
    if args.format == "summary":
        print(render_summary(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


def build_report(repo_root: Path) -> dict[str, Any]:
    matrix_path = repo_root / "docs" / "system-modularization" / "36-module-closure-matrix.md"
    matrix_text = matrix_path.read_text(encoding="utf-8")
    rows = parse_classification_overlay(matrix_text)
    row_by_module = {row["module"]: row for row in rows}
    active_work_mappings = parse_active_work_closure_mapping(matrix_text)
    mapping_by_item = {mapping["work_item"]: mapping for mapping in active_work_mappings}

    roadmap_path = repo_root / "docs" / "system-modularization" / "32-active-roadmap-and-gates.md"
    active_work_items = parse_active_work_items(roadmap_path.read_text(encoding="utf-8"))

    live_modules = load_live_module_definitions(repo_root)
    unknown_live_modules = sorted(
        module for module in live_modules if module not in LIVE_MODULE_TO_CLOSURE_LABEL
    )
    missing_live_modules = sorted(
        {
            LIVE_MODULE_TO_CLOSURE_LABEL[module]
            for module in live_modules
            if module in LIVE_MODULE_TO_CLOSURE_LABEL
            and LIVE_MODULE_TO_CLOSURE_LABEL[module] not in row_by_module
        }
    )
    missing_contract_labels = sorted(label for label in REQUIRED_CONTRACT_LABELS if label not in row_by_module)
    invalid_rows = [row for row in rows if row_classification_errors(row)]
    missing_active_work_items = sorted(item for item in active_work_items if item not in mapping_by_item)
    stale_active_work_mappings = sorted(
        mapping["work_item"]
        for mapping in active_work_mappings
        if mapping["work_item"] not in active_work_items
    )
    invalid_active_work_mappings = [
        mapping
        for mapping in active_work_mappings
        if active_work_mapping_errors(mapping, row_by_module)
    ]

    findings: list[dict[str, Any]] = []
    for module in unknown_live_modules:
        findings.append(
            {
                "code": "live_module_missing_closure_alias",
                "severity": "error",
                "module": module,
            }
        )
    for label in missing_live_modules:
        findings.append(
            {
                "code": "live_module_missing_matrix_row",
                "severity": "error",
                "module": label,
            }
        )
    for label in missing_contract_labels:
        findings.append(
            {
                "code": "contract_surface_missing_matrix_row",
                "severity": "error",
                "module": label,
            }
        )
    for row in invalid_rows:
        findings.append(
            {
                "code": "invalid_closure_classification",
                "severity": "error",
                "module": row["module"],
                "errors": row_classification_errors(row),
            }
        )
    for item in missing_active_work_items:
        findings.append(
            {
                "code": "active_work_item_missing_closure_mapping",
                "severity": "error",
                "work_item": item,
            }
        )
    for item in stale_active_work_mappings:
        findings.append(
            {
                "code": "active_work_mapping_stale",
                "severity": "error",
                "work_item": item,
            }
        )
    for mapping in invalid_active_work_mappings:
        findings.append(
            {
                "code": "invalid_active_work_closure_mapping",
                "severity": "error",
                "work_item": mapping["work_item"],
                "errors": active_work_mapping_errors(mapping, row_by_module),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok" if not findings else "fail",
        "matrix_path": str(matrix_path),
        "roadmap_path": str(roadmap_path),
        "live_module_count": len(live_modules),
        "matrix_module_count": len(rows),
        "active_work_item_count": len(active_work_items),
        "active_work_mapping_count": len(active_work_mappings),
        "live_modules": live_modules,
        "active_work_items": active_work_items,
        "missing_live_modules": missing_live_modules,
        "missing_contract_labels": missing_contract_labels,
        "unknown_live_modules": unknown_live_modules,
        "invalid_row_count": len(invalid_rows),
        "missing_active_work_items": missing_active_work_items,
        "stale_active_work_mappings": stale_active_work_mappings,
        "invalid_active_work_mapping_count": len(invalid_active_work_mappings),
        "findings": findings,
    }


def parse_classification_overlay(text: str) -> list[dict[str, str]]:
    in_overlay = False
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "## Classification Overlay":
            in_overlay = True
            continue
        if in_overlay and stripped.startswith("## "):
            break
        if not in_overlay or not stripped.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
        if len(cells) != 5 or cells[0] in {"Module", "---"} or set(cells[0]) == {"-"}:
            continue
        rows.append(
            {
                "module": cells[0],
                "delivery_class": cells[1],
                "state_change_class": cells[2],
                "cadence_class": cells[3],
                "current_action_path": cells[4],
            }
        )
    return rows


def parse_active_work_closure_mapping(text: str) -> list[dict[str, str]]:
    in_mapping = False
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "## Active Work Closure Mapping":
            in_mapping = True
            continue
        if in_mapping and stripped.startswith("## "):
            break
        if not in_mapping or not stripped.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
        if len(cells) != 4 or cells[0] in {"Work item", "---"} or set(cells[0]) == {"-"}:
            continue
        rows.append(
            {
                "work_item": cells[0],
                "closure_rows": cells[1],
                "not_applicable_reason": cells[2],
                "validation_note": cells[3],
            }
        )
    return rows


def parse_active_work_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        match = ACTIVE_WORK_ITEM_RE.match(line.strip())
        if match:
            items.append(match.group(1))
    return sorted(items)


def load_live_module_definitions(repo_root: Path) -> list[str]:
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from plugins.memory.memory_os.cli import _module_definitions

    return sorted(str(item["module"]) for item in _module_definitions())


def row_classification_errors(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if not _classes_are_valid(row["delivery_class"], VALID_DELIVERY_CLASSES):
        errors.append("delivery_class")
    if not _classes_are_valid(row["state_change_class"], VALID_STATE_CHANGE_CLASSES):
        errors.append("state_change_class")
    if not _classes_are_valid(row["cadence_class"], VALID_CADENCE_CLASSES):
        errors.append("cadence_class")
    return errors


def active_work_mapping_errors(
    mapping: dict[str, str],
    row_by_module: dict[str, dict[str, str]],
) -> list[str]:
    errors: list[str] = []
    closure_rows = mapping["closure_rows"].strip()
    reason = mapping["not_applicable_reason"].strip()
    if closure_rows == "not_applicable":
        if not reason:
            errors.append("not_applicable_reason")
        return errors
    if reason:
        errors.append("not_applicable_reason_must_be_empty_when_mapped")
    labels = [label.strip() for label in closure_rows.split(";") if label.strip()]
    if not labels:
        errors.append("closure_rows")
        return errors
    missing = [label for label in labels if label not in row_by_module]
    if missing:
        errors.append("unknown_closure_rows:" + ",".join(missing))
    return errors


def _classes_are_valid(value: str, allowed: set[str]) -> bool:
    parts = [
        part.strip()
        for chunk in value.split("/")
        for part in chunk.split("+")
        if part.strip()
    ]
    return bool(parts) and all(part in allowed for part in parts)


def render_summary(report: dict[str, Any]) -> str:
    lines = [
        f"status={report['status']}",
        f"live_module_count={report['live_module_count']}",
        f"matrix_module_count={report['matrix_module_count']}",
        f"active_work_item_count={report['active_work_item_count']}",
        f"active_work_mapping_count={report['active_work_mapping_count']}",
        f"finding_count={len(report['findings'])}",
    ]
    for finding in report["findings"]:
        lines.append(f"- {finding['code']}: {finding.get('module') or finding.get('work_item')}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
