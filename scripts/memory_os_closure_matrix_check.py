#!/usr/bin/env python3
"""Check that Memory-OS modules are represented in the RH-36 closure matrix."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.closure_matrix_check.v1"
PUBLIC_CONTRACT_SCHEMA_VERSION = "memory-os.closure_matrix_contract.v1"
PUBLIC_CONTRACT_PATH = ("docs", "contracts", "memory-os-closure-matrix.v1.json")

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
    "left_brain_pipeline_check": "Left-Brain Pipeline Check",
    "confidence_router": "Confidence Router",
    "ground_truth_miner": "Ground Truth Miner",
    "crystallized_revalidator": "Crystallized Revalidator",
    "judge_calibration": "Judge Calibration / Canary",
    "candidate_review": "FeaturePreRouter / CandidateReview",
    "shadow_recall": "Shadow Recall",
    "provisional": "Provisional Tier",
    "cascade_routing_policy": "Cascade Routing Policy",
    "migration_controller": "Migration Controller",
    "symbolic_offloader": "Symbolic Offloader",
    "abstraction_distillation": "Abstraction Distillation",
    "digest_consolidation": "Digest Consolidation",
    "inner_drive": "Heartbeat / Inner Drive",
    "mailbox": "Mailbox",
    "household_digest": "Household Digest",
    "wandering_mind": "Wandering Mind",
    "imagination_loop": "Imagination Loop",
    "evidence_scoring": "Evidence Scoring",
    "confabulation_detector": "Confabulation Detector",
    "ops_gate": "Ops Gate",
    "proposal_queue": "Proposal Queue",
    "self_evolution": "Self-Evolution",
    "speak_gate": "Speak Gate",
    "expression_draft": "Expression Draft",
    "grounded_expression_judge": "Grounded Expression Judge",
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

MATRIX_PATH_CANDIDATES = (
    ("docs", "internal-memory-os", "01-contracts", "36-module-closure-matrix.md"),
    ("docs", "system-modularization", "36-module-closure-matrix.md"),
)

ROADMAP_PATH_CANDIDATES = (
    ("docs", "internal-memory-os", "00-control", "32-active-roadmap-and-gates.md"),
    ("docs", "system-modularization", "32-active-roadmap-and-gates.md"),
)


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
    public_contract_path = repo_root.joinpath(*PUBLIC_CONTRACT_PATH)
    matrix_path = find_doc_path(
        repo_root,
        MATRIX_PATH_CANDIDATES,
    )
    roadmap_path = find_doc_path(
        repo_root,
        ROADMAP_PATH_CANDIDATES,
    )
    missing_internal_docs = []
    if matrix_path is None:
        missing_internal_docs.append("closure_matrix")
    if roadmap_path is None:
        missing_internal_docs.append("active_roadmap")

    live_modules: list[str] = []
    if not public_contract_path.exists():
        return missing_public_contract_report(
            public_contract_path,
            matrix_path,
            roadmap_path,
            live_modules,
            missing_internal_docs,
        )

    try:
        public_contract = json.loads(public_contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return invalid_public_contract_report(
            public_contract_path,
            matrix_path,
            roadmap_path,
            live_modules,
            missing_internal_docs,
            "json_decode",
        )
    if not isinstance(public_contract, dict):
        return invalid_public_contract_report(
            public_contract_path,
            matrix_path,
            roadmap_path,
            live_modules,
            missing_internal_docs,
            "root_object",
        )
    if public_contract.get("schema_version") != PUBLIC_CONTRACT_SCHEMA_VERSION:
        return invalid_public_contract_report(
            public_contract_path,
            matrix_path,
            roadmap_path,
            live_modules,
            missing_internal_docs,
            "schema_version",
        )
    evidence_contract = {
        "contract_scope": "source_and_static_wiring_only",
        "runtime_evidence_required": True,
        "runtime_evidence_schema": "memory-os.closure_runtime_evidence.v1",
        "runtime_evidence_path": "memory-os/system/closure_runtime_evidence.v1.json",
    }
    for field, expected in evidence_contract.items():
        if public_contract.get(field) != expected:
            return invalid_public_contract_report(
                public_contract_path,
                matrix_path,
                roadmap_path,
                live_modules,
                missing_internal_docs,
                field,
            )
    public_rows = public_contract.get("modules")
    if not isinstance(public_rows, list) or not all(isinstance(row, dict) for row in public_rows):
        return invalid_public_contract_report(
            public_contract_path,
            matrix_path,
            roadmap_path,
            live_modules,
            missing_internal_docs,
            "modules",
        )
    for index, row in enumerate(public_rows):
        aliases = row.get("live_modules")
        if not isinstance(aliases, list) or not all(isinstance(module, str) for module in aliases):
            return invalid_public_contract_report(
                public_contract_path,
                matrix_path,
                roadmap_path,
                live_modules,
                missing_internal_docs,
                f"modules[{index}].live_modules",
            )

    live_modules = load_live_module_definitions(repo_root)

    private_extension_enabled = matrix_path is not None and roadmap_path is not None
    matrix_text = matrix_path.read_text(encoding="utf-8") if private_extension_enabled else ""
    private_rows = parse_classification_overlay(matrix_text)
    public_module_counts = Counter(str(row.get("module", "")) for row in public_rows)
    private_module_counts = Counter(str(row.get("module", "")) for row in private_rows)
    duplicate_public_modules = sorted(
        module for module, count in public_module_counts.items() if module and count > 1
    )
    duplicate_private_modules = sorted(
        module for module, count in private_module_counts.items() if module and count > 1
    )
    public_by_label: dict[str, dict[str, Any]] = {}
    for row in public_rows:
        public_by_label.setdefault(str(row.get("module", "")), row)
    classification_fields = (
        "delivery_class",
        "state_change_class",
        "cadence_class",
        "current_action_path",
    )
    private_conflicts: list[dict[str, Any]] = []
    private_extension_rows: list[dict[str, Any]] = []
    seen_private_extension_labels: set[str] = set()
    for row in private_rows:
        label = str(row.get("module", ""))
        public_row = public_by_label.get(label)
        if public_row is not None:
            differing_fields = [
                field for field in classification_fields if row.get(field) != public_row.get(field)
            ]
            if differing_fields:
                private_conflicts.append(
                    {"module": label, "differing_fields": differing_fields}
                )
            continue
        if label not in seen_private_extension_labels:
            private_extension_rows.append(row)
            seen_private_extension_labels.add(label)
    rows = [*public_rows, *private_extension_rows]
    row_by_module = {str(row.get("module", "")): row for row in rows}
    active_work_mappings = parse_active_work_closure_mapping(matrix_text) if private_extension_enabled else []
    mapping_by_item = {mapping["work_item"]: mapping for mapping in active_work_mappings}

    active_work_items = (
        parse_active_work_items(roadmap_path.read_text(encoding="utf-8"))
        if roadmap_path is not None and private_extension_enabled
        else []
    )

    public_contract_live_modules = sorted(
        str(module)
        for row in public_rows
        for module in row.get("live_modules", [])
        if isinstance(module, str)
    )
    public_alias_counts = Counter(public_contract_live_modules)
    duplicate_contract_live_modules = sorted(
        module for module, count in public_alias_counts.items() if count > 1
    )
    unknown_live_modules = sorted(set(live_modules) - set(public_contract_live_modules))
    missing_live_modules = sorted(
        {
            LIVE_MODULE_TO_CLOSURE_LABEL[module]
            for module in live_modules
            if module in LIVE_MODULE_TO_CLOSURE_LABEL
            and LIVE_MODULE_TO_CLOSURE_LABEL[module] not in row_by_module
        }
    )
    unknown_contract_live_modules = sorted(set(public_contract_live_modules) - set(live_modules))
    missing_contract_labels = sorted(
        label for label in REQUIRED_CONTRACT_LABELS if label not in row_by_module
    )
    invalid_rows = [
        row for row in [*public_rows, *private_rows] if row_classification_errors(row, repo_root)
    ]
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
    for module in duplicate_public_modules:
        findings.append(
            {
                "code": "contract_module_duplicate",
                "severity": "error",
                "module": module,
            }
        )
    for module in duplicate_private_modules:
        findings.append(
            {
                "code": "private_extension_module_duplicate",
                "severity": "error",
                "module": module,
            }
        )
    for conflict in private_conflicts:
        findings.append(
            {
                "code": "private_extension_conflicts_public_contract",
                "severity": "error",
                **conflict,
            }
        )
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
    for module in unknown_contract_live_modules:
        findings.append(
            {
                "code": "contract_live_module_unknown",
                "severity": "error",
                "module": module,
            }
        )
    for module in duplicate_contract_live_modules:
        findings.append(
            {
                "code": "contract_live_module_duplicate",
                "severity": "error",
                "module": module,
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
                "module": str(row.get("module") or ""),
                "errors": row_classification_errors(row, repo_root),
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

    if missing_internal_docs:
        findings.append(
            {
                "code": "internal_docs_missing",
                "severity": "info",
                "missing_internal_docs": missing_internal_docs,
            }
        )

    has_errors = any(finding["severity"] == "error" for finding in findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail" if has_errors else "ok",
        "closure_status": "contract_invalid" if has_errors else "runtime_evidence_required",
        "contract_scope": public_contract["contract_scope"],
        "runtime_evidence_required": True,
        "runtime_evidence_schema": public_contract["runtime_evidence_schema"],
        "runtime_evidence_path": public_contract["runtime_evidence_path"],
        "public_contract_path": str(public_contract_path),
        "matrix_path": str(matrix_path or public_contract_path),
        "private_matrix_path": str(matrix_path) if matrix_path else "",
        "roadmap_path": str(roadmap_path) if roadmap_path else "",
        "missing_internal_docs": missing_internal_docs,
        "private_extension_enabled": private_extension_enabled,
        "live_module_count": len(live_modules),
        "matrix_module_count": len(rows),
        "active_work_item_count": len(active_work_items),
        "active_work_mapping_count": len(active_work_mappings),
        "live_modules": live_modules,
        "active_work_items": active_work_items,
        "missing_live_modules": missing_live_modules,
        "missing_contract_labels": missing_contract_labels,
        "unknown_live_modules": unknown_live_modules,
        "unknown_contract_live_modules": unknown_contract_live_modules,
        "invalid_row_count": len(invalid_rows),
        "missing_active_work_items": missing_active_work_items,
        "stale_active_work_mappings": stale_active_work_mappings,
        "invalid_active_work_mapping_count": len(invalid_active_work_mappings),
        "findings": findings,
    }


def missing_public_contract_report(
    public_contract_path: Path,
    matrix_path: Path | None,
    roadmap_path: Path | None,
    live_modules: list[str],
    missing_internal_docs: list[str],
) -> dict[str, Any]:
    return invalid_contract_base_report(
        public_contract_path,
        matrix_path,
        roadmap_path,
        live_modules,
        missing_internal_docs,
        {"code": "public_contract_missing", "severity": "error"},
    )


def invalid_public_contract_report(
    public_contract_path: Path,
    matrix_path: Path | None,
    roadmap_path: Path | None,
    live_modules: list[str],
    missing_internal_docs: list[str],
    field: str,
) -> dict[str, Any]:
    return invalid_contract_base_report(
        public_contract_path,
        matrix_path,
        roadmap_path,
        live_modules,
        missing_internal_docs,
        {"code": "public_contract_invalid", "severity": "error", "field": field},
    )


def invalid_contract_base_report(
    public_contract_path: Path,
    matrix_path: Path | None,
    roadmap_path: Path | None,
    live_modules: list[str],
    missing_internal_docs: list[str],
    finding: dict[str, Any],
) -> dict[str, Any]:
    findings = [finding]
    if missing_internal_docs:
        findings.append(
            {
                "code": "internal_docs_missing",
                "severity": "info",
                "missing_internal_docs": missing_internal_docs,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "public_contract_path": str(public_contract_path),
        "matrix_path": str(matrix_path) if matrix_path else "",
        "private_matrix_path": str(matrix_path) if matrix_path else "",
        "roadmap_path": str(roadmap_path) if roadmap_path else "",
        "missing_internal_docs": missing_internal_docs,
        "private_extension_enabled": False,
        "live_module_count": len(live_modules),
        "matrix_module_count": 0,
        "active_work_item_count": 0,
        "active_work_mapping_count": 0,
        "live_modules": live_modules,
        "active_work_items": [],
        "missing_live_modules": [],
        "missing_contract_labels": [],
        "unknown_live_modules": [],
        "unknown_contract_live_modules": [],
        "invalid_row_count": 0,
        "missing_active_work_items": [],
        "stale_active_work_mappings": [],
        "invalid_active_work_mapping_count": 0,
        "findings": findings,
    }


def resolve_doc_path(
    repo_root: Path,
    candidates: tuple[tuple[str, ...], ...],
    label: str,
) -> Path:
    attempted: list[str] = []
    for candidate in candidates:
        path = repo_root.joinpath(*candidate)
        attempted.append(str(path))
        if path.exists():
            return path
    raise FileNotFoundError(f"{label} not found. Tried: {', '.join(attempted)}")


def find_doc_path(
    repo_root: Path,
    candidates: tuple[tuple[str, ...], ...],
) -> Path | None:
    for candidate in candidates:
        path = repo_root.joinpath(*candidate)
        if path.exists():
            return path
    return None


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
    """Read the CLI registry from its source AST without importing ambient packages."""
    cli_path = (repo_root / "plugins" / "memory" / "memory_os" / "cli.py").resolve()
    cli_path.relative_to(repo_root.resolve())
    tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
    registry = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_module_definitions"
        ),
        None,
    )
    if registry is None:
        raise RuntimeError("live module registry symbol missing: _module_definitions")
    return_node = next((node for node in ast.walk(registry) if isinstance(node, ast.Return)), None)
    if return_node is None or not isinstance(return_node.value, (ast.List, ast.Tuple)):
        raise RuntimeError("live module registry must return a literal list")
    modules: list[str] = []
    for item in return_node.value.elts:
        if not isinstance(item, ast.Dict):
            raise RuntimeError("live module registry entries must be literal dicts")
        module_value: str | None = None
        for key, value in zip(item.keys, item.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "module":
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    module_value = value.value
                break
        if not module_value:
            raise RuntimeError("live module registry entry missing literal module id")
        modules.append(module_value)
    return sorted(modules)


def row_classification_errors(row: dict[str, Any], repo_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not str(row.get("module") or "").strip():
        errors.append("module")
    delivery_class = row.get("delivery_class")
    if not isinstance(delivery_class, str) or not _classes_are_valid(delivery_class, VALID_DELIVERY_CLASSES):
        errors.append("delivery_class")
    state_change_class = row.get("state_change_class")
    if not isinstance(state_change_class, str) or not _classes_are_valid(state_change_class, VALID_STATE_CHANGE_CLASSES):
        errors.append("state_change_class")
    cadence_class = row.get("cadence_class")
    if not isinstance(cadence_class, str) or not _classes_are_valid(cadence_class, VALID_CADENCE_CLASSES):
        errors.append("cadence_class")
    current_action_path = row.get("current_action_path")
    if not isinstance(current_action_path, str) or not current_action_path.strip():
        errors.append("current_action_path")
    elif repo_root is not None:
        reference_error = _action_reference_error(current_action_path, repo_root)
        if reference_error:
            errors.append("current_action_path:" + reference_error)
    return errors


def _action_reference_error(reference: str, repo_root: Path) -> str:
    """Require a portable, existing ``relative/path.py::symbol`` action reference."""
    if "::" not in reference:
        return "unstructured"
    relative_text, symbol = (part.strip() for part in reference.split("::", 1))
    relative = Path(relative_text)
    if not relative_text or relative.is_absolute() or ".." in relative.parts:
        return "unsafe_path"
    if not symbol:
        return "missing_symbol"
    target = (repo_root / relative).resolve()
    try:
        target.relative_to(repo_root.resolve())
    except ValueError:
        return "outside_repo"
    if not target.is_file():
        return "missing_file"
    try:
        source = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "unreadable_file"
    try:
        tree = ast.parse(source, filename=str(target))
    except SyntaxError:
        return "invalid_source"
    definitions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    if symbol not in definitions:
        return "missing_symbol"
    return ""


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
        f"closure_status={report.get('closure_status', 'contract_invalid')}",
        *([f"skip_reason={report['skip_reason']}"] if report.get("skip_reason") else []),
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
