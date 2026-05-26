from __future__ import annotations

import shutil
from pathlib import Path

from scripts.memory_os_closure_matrix_check import build_report, parse_classification_overlay


def test_closure_matrix_check_passes_for_current_repo() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    report = build_report(repo_root)

    assert report["schema_version"] == "memory-os.closure_matrix_check.v1"
    assert report["status"] == "ok"
    assert report["live_module_count"] == 16
    assert report["matrix_module_count"] == 28
    assert report["active_work_item_count"] == 19
    assert report["active_work_mapping_count"] == 19
    assert report["missing_live_modules"] == []
    assert report["missing_contract_labels"] == []
    assert report["invalid_row_count"] == 0
    assert report["missing_active_work_items"] == []
    assert report["stale_active_work_mappings"] == []
    assert report["invalid_active_work_mapping_count"] == 0
    assert report["findings"] == []


def test_closure_matrix_check_fails_when_live_module_row_is_missing(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    shutil.copytree(repo_root / "docs", shadow_repo / "docs")
    matrix_path = shadow_repo / "docs" / "system-modularization" / "36-module-closure-matrix.md"
    text = matrix_path.read_text(encoding="utf-8")
    matrix_path.write_text(
        "\n".join(
            line
            for line in text.splitlines()
            if not line.startswith("| DeepReflection |")
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert "DeepReflection" in report["missing_live_modules"]
    assert any(
        finding["code"] == "live_module_missing_matrix_row"
        and finding["module"] == "DeepReflection"
        for finding in report["findings"]
    )


def test_closure_matrix_check_rejects_freeform_classification_text(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    shutil.copytree(repo_root / "docs", shadow_repo / "docs")
    matrix_path = shadow_repo / "docs" / "system-modularization" / "36-module-closure-matrix.md"
    text = matrix_path.read_text(encoding="utf-8")
    matrix_path.write_text(
        text.replace(
            "| Mailbox | hermes_mailbox_internal | monitor_only | event_driven_fast |",
            "| Mailbox | hermes_mailbox_internal | monitor_only | event_driven_fast with cooldown |",
        ),
        encoding="utf-8",
    )

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert any(
        finding["code"] == "invalid_closure_classification"
        and finding["module"] == "Mailbox"
        and finding["errors"] == ["cadence_class"]
        for finding in report["findings"]
    )


def test_closure_matrix_check_accepts_expression_feedback_class() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    report = build_report(repo_root)

    matrix_path = repo_root / "docs" / "system-modularization" / "36-module-closure-matrix.md"
    rows = {row["module"]: row for row in parse_classification_overlay(matrix_path.read_text(encoding="utf-8"))}
    assert "expression_feedback" in rows["Wandering Mind"]["state_change_class"]
    assert "expression_feedback" in rows["Speak Gate"]["state_change_class"]
    assert not any(
        finding["code"] == "invalid_closure_classification"
        and finding["module"] in {"Wandering Mind", "Speak Gate"}
        for finding in report["findings"]
    )


def test_closure_matrix_check_fails_when_active_work_mapping_is_missing(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    shutil.copytree(repo_root / "docs", shadow_repo / "docs")
    matrix_path = shadow_repo / "docs" / "system-modularization" / "36-module-closure-matrix.md"
    text = matrix_path.read_text(encoding="utf-8")
    matrix_path.write_text(
        "\n".join(
            line
            for line in text.splitlines()
            if not line.startswith("| P1-O |")
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert "P1-O" in report["missing_active_work_items"]
    assert any(
        finding["code"] == "active_work_item_missing_closure_mapping"
        and finding["work_item"] == "P1-O"
        for finding in report["findings"]
    )
