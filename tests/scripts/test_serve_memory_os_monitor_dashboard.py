from __future__ import annotations

from pathlib import Path

import pytest

from scripts.serve_memory_os_monitor_dashboard import DEFAULT_DASHBOARD_DIR, build_parser, main


def test_parser_defaults_to_open_source_frontend_port() -> None:
    args = build_parser().parse_args([])

    assert args.host == "0.0.0.0"
    assert args.port == 3693
    assert args.directory == DEFAULT_DASHBOARD_DIR


def test_missing_dashboard_directory_fails(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing"

    with pytest.raises(SystemExit, match="Dashboard directory does not exist"):
        main(["--directory", str(missing_dir)])
