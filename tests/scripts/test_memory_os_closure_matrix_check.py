from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.memory_os_closure_matrix_check import build_report, main, parse_classification_overlay


def _matrix_path(repo_root: Path) -> Path:
    return repo_root / "docs" / "internal-memory-os" / "01-contracts" / "36-module-closure-matrix.md"


INTERNAL_MATRIX_PATH = _matrix_path(Path(__file__).resolve().parents[2])
PUBLIC_CONTRACT_RELATIVE_PATH = Path("docs/contracts/memory-os-closure-matrix.v1.json")

requires_internal_docs = pytest.mark.skipif(
    not INTERNAL_MATRIX_PATH.exists(),
    reason="internal closure matrix docs are not included in public checkouts",
)


def _copy_public_contract(repo_root: Path, shadow_repo: Path) -> Path:
    target = shadow_repo / PUBLIC_CONTRACT_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / PUBLIC_CONTRACT_RELATIVE_PATH, target)
    return target


def test_closure_matrix_check_runs_when_internal_docs_are_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    _copy_public_contract(repo_root, shadow_repo)

    report = build_report(shadow_repo)

    assert report["schema_version"] == "memory-os.closure_matrix_check.v1"
    assert report["status"] == "ok"
    assert set(report["missing_internal_docs"]) == {"closure_matrix", "active_roadmap"}
    assert report["live_module_count"] == 32
    assert report["matrix_module_count"] == 29
    assert report["unknown_live_modules"] == []
    assert report["missing_live_modules"] == []
    assert report["invalid_row_count"] == 0
    assert report["findings"] == [
        {
            "code": "internal_docs_missing",
            "severity": "info",
            "missing_internal_docs": ["closure_matrix", "active_roadmap"],
        }
    ]

    assert main(["--repo-root", str(shadow_repo), "--format", "summary"]) == 0
    output = capsys.readouterr().out
    assert "status=ok" in output
    assert "skip_reason=" not in output


def test_cli_rejects_legacy_skipped_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.memory_os_closure_matrix_check.build_report",
        lambda _repo_root: {"status": "skipped"},
    )
    monkeypatch.setattr(
        "scripts.memory_os_closure_matrix_check.render_summary",
        lambda _report: "status=skipped",
    )

    assert main(["--format", "summary"]) == 1


def test_public_contract_fails_when_live_module_row_is_missing(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["modules"] = [row for row in contract["modules"] if row["module"] != "DeepReflection"]
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert report["missing_live_modules"] == ["DeepReflection"]
    assert any(
        finding["code"] == "live_module_missing_matrix_row"
        and finding["module"] == "DeepReflection"
        for finding in report["findings"]
    )


def test_public_contract_rejects_unknown_live_module_alias(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["modules"][0]["live_modules"].append("not_a_live_module")
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert report["unknown_contract_live_modules"] == ["not_a_live_module"]
    assert any(
        finding["code"] == "contract_live_module_unknown"
        and finding["module"] == "not_a_live_module"
        for finding in report["findings"]
    )


def test_public_contract_fails_when_live_module_has_no_contract_alias(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    deep_reflection = next(row for row in contract["modules"] if row["module"] == "DeepReflection")
    deep_reflection["live_modules"] = []
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert report["unknown_live_modules"] == ["deep_reflection"]
    assert any(
        finding["code"] == "live_module_missing_closure_alias"
        and finding["module"] == "deep_reflection"
        for finding in report["findings"]
    )


def test_public_contract_rejects_non_list_live_modules(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["modules"][0]["live_modules"] = "cron_mirror"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert any(
        finding["code"] == "public_contract_invalid"
        and finding["field"] == "modules[0].live_modules"
        for finding in report["findings"]
    )


def test_public_contract_rejects_duplicate_live_module_alias(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["modules"][1]["live_modules"].append("cron_mirror")
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert any(
        finding["code"] == "contract_live_module_duplicate"
        and finding["module"] == "cron_mirror"
        for finding in report["findings"]
    )


def test_public_contract_rejects_duplicate_module_label_before_deduplication(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    duplicate = dict(contract["modules"][0])
    duplicate["delivery_class"] = "INVALID"
    contract["modules"].insert(0, duplicate)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert any(
        finding["code"] == "contract_module_duplicate"
        and finding["module"] == duplicate["module"]
        for finding in report["findings"]
    )
    assert any(
        finding["code"] == "invalid_closure_classification"
        and finding["module"] == duplicate["module"]
        and "delivery_class" in finding["errors"]
        for finding in report["findings"]
    )


def test_private_extension_cannot_override_public_classification(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    public_row = contract["modules"][0]
    matrix_path = _matrix_path(shadow_repo)
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.write_text(
        "## Classification Overlay\n\n"
        "| Module | Delivery class | State change class | Cadence class | Current action path |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"| {public_row['module']} | owner_origin | {public_row['state_change_class']} | "
        f"{public_row['cadence_class']} | private override |\n",
        encoding="utf-8",
    )
    roadmap = shadow_repo / "docs" / "internal-memory-os" / "00-control" / "32-active-roadmap-and-gates.md"
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_text("# no active work\n", encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert any(
        finding["code"] == "private_extension_conflicts_public_contract"
        and finding["module"] == public_row["module"]
        for finding in report["findings"]
    )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (lambda row: row.update(module="   "), "module"),
        (lambda row: row.pop("delivery_class"), "delivery_class"),
        (lambda row: row.pop("state_change_class"), "state_change_class"),
        (lambda row: row.pop("cadence_class"), "cadence_class"),
        (lambda row: row.pop("current_action_path"), "current_action_path"),
        (lambda row: row.update(current_action_path=123), "current_action_path"),
    ],
)
def test_public_contract_required_fields_fail_closed(
    tmp_path: Path,
    mutation,
    expected_error: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    mutation(contract["modules"][0])
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert any(
        finding["code"] == "invalid_closure_classification"
        and expected_error in finding["errors"]
        for finding in report["findings"]
    )


@pytest.mark.parametrize(
    ("raw_contract", "expected_reason"),
    [
        ("{not-json", "json_decode"),
        ("[]", "root_object"),
    ],
)
def test_public_contract_parse_failures_are_structured(
    tmp_path: Path,
    raw_contract: str,
    expected_reason: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract_path.write_text(raw_contract, encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert report["findings"][0]["code"] == "public_contract_invalid"
    assert report["findings"][0]["field"] == expected_reason


def test_public_contract_rejects_empty_current_action_path(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["modules"][0]["current_action_path"] = ""
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert any(
        finding["code"] == "invalid_closure_classification"
        and finding["module"] == contract["modules"][0]["module"]
        and "current_action_path" in finding["errors"]
        for finding in report["findings"]
    )


def test_public_contract_rejects_invalid_classification(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    contract_path = _copy_public_contract(repo_root, shadow_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    mailbox = next(row for row in contract["modules"] if row["module"] == "Mailbox")
    mailbox["cadence_class"] = "event_driven_fast with cooldown"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = build_report(shadow_repo)

    assert report["status"] == "fail"
    assert report["invalid_row_count"] == 1
    assert any(
        finding["code"] == "invalid_closure_classification"
        and finding["module"] == "Mailbox"
        and finding["errors"] == ["cadence_class"]
        for finding in report["findings"]
    )


@requires_internal_docs
def test_closure_matrix_check_passes_for_current_repo() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    report = build_report(repo_root)

    assert report["schema_version"] == "memory-os.closure_matrix_check.v1"
    assert report["status"] == "ok"
    assert report["live_module_count"] == 32
    assert report["matrix_module_count"] == 45
    assert report["active_work_item_count"] == 20
    assert report["active_work_mapping_count"] == 20
    assert report["missing_live_modules"] == []
    assert report["missing_contract_labels"] == []
    assert report["invalid_row_count"] == 0
    assert report["missing_active_work_items"] == []
    assert report["stale_active_work_mappings"] == []
    assert report["invalid_active_work_mapping_count"] == 0
    assert report["findings"] == []


@requires_internal_docs
def test_closure_matrix_check_fails_when_live_module_row_is_missing(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    shutil.copytree(repo_root / "docs", shadow_repo / "docs")
    matrix_path = _matrix_path(shadow_repo)
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


@requires_internal_docs
def test_closure_matrix_check_rejects_freeform_classification_text(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    shutil.copytree(repo_root / "docs", shadow_repo / "docs")
    matrix_path = _matrix_path(shadow_repo)
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


@requires_internal_docs
def test_closure_matrix_check_accepts_expression_feedback_class() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    report = build_report(repo_root)

    matrix_path = _matrix_path(repo_root)
    rows = {row["module"]: row for row in parse_classification_overlay(matrix_path.read_text(encoding="utf-8"))}
    assert "expression_feedback" in rows["Wandering Mind"]["state_change_class"]
    assert "expression_feedback" in rows["Speak Gate"]["state_change_class"]
    assert not any(
        finding["code"] == "invalid_closure_classification"
        and finding["module"] in {"Wandering Mind", "Speak Gate"}
        for finding in report["findings"]
    )


@requires_internal_docs
def test_closure_matrix_check_fails_when_active_work_mapping_is_missing(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shadow_repo = tmp_path / "repo"
    shutil.copytree(repo_root / "docs", shadow_repo / "docs")
    matrix_path = _matrix_path(shadow_repo)
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
