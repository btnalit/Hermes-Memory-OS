from __future__ import annotations

from pathlib import Path

from scripts.install_memory_os_monitor_dashboard_service import install_service, render_service_unit


def _write_dashboard_inputs(repo: Path) -> None:
    (repo / "monitor_dashboard" / "assets").mkdir(parents=True)
    (repo / "monitor_dashboard" / "index.html").write_text("", encoding="utf-8")
    (repo / "monitor_dashboard" / "assets" / "dashboard.js").write_text("", encoding="utf-8")
    (repo / "monitor_dashboard" / "assets" / "mos.css").write_text("", encoding="utf-8")
    (repo / "monitor_dashboard" / "assets" / "sample-data.js").write_text("", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "memory_os_monitor_dashboard_snapshot.py").write_text("", encoding="utf-8")
    (repo / "scripts" / "serve_memory_os_monitor_dashboard.py").write_text("", encoding="utf-8")


def test_dashboard_service_unit_binds_open_source_frontend_port(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    hermes_home = tmp_path / "home"

    unit = render_service_unit(
        repo_root=repo,
        hermes_home=hermes_home,
        profile="main",
        environment="prod",
        refresh_interval_seconds=60,
        host="0.0.0.0",
        port=3693,
        python_bin="/usr/bin/python3",
    )

    assert "Description=Hermes Memory-OS monitor dashboard" in unit
    assert "ExecStartPre=/usr/bin/python3" in unit
    assert "Environment=HERMES_ENV=prod" in unit
    assert "Environment=MOS_DASHBOARD_REFRESH_INTERVAL_SECONDS=60" in unit
    assert "--host 0.0.0.0 --port 3693" in unit
    assert "--snapshot-interval-seconds 60" in unit
    assert "WantedBy=multi-user.target" in unit


def test_dashboard_service_dry_run_reports_enable_commands(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_dashboard_inputs(repo)

    report = install_service(
        repo_root=repo,
        hermes_home=tmp_path / "home",
        profile="main",
        environment="prod",
        refresh_interval_seconds=60,
        host="0.0.0.0",
        port=3693,
        python_bin="/usr/bin/python3",
        systemd_dir=tmp_path / "systemd",
        service_name="hermes-memory-os-monitor-dashboard.service",
        enable=True,
        dry_run=True,
    )

    assert report["schema_version"] == "memory-os.monitor_dashboard_service_install.v0"
    assert report["environment"] == "prod"
    assert report["refresh_interval_seconds"] == 60
    assert report["enable_requested"] is True
    assert report["enabled"] is False
    assert report["commands"] == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "hermes-memory-os-monitor-dashboard.service"],
        ["systemctl", "restart", "hermes-memory-os-monitor-dashboard.service"],
    ]


def test_dashboard_service_rejects_invalid_options(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_dashboard_inputs(repo)

    invalid_cases = [
        {"service_name": "../bad.service", "port": 3693, "refresh_interval_seconds": 60, "host": "0.0.0.0"},
        {"service_name": "bad.timer", "port": 3693, "refresh_interval_seconds": 60, "host": "0.0.0.0"},
        {"service_name": "ok.service", "port": 0, "refresh_interval_seconds": 60, "host": "0.0.0.0"},
        {"service_name": "ok.service", "port": 65536, "refresh_interval_seconds": 60, "host": "0.0.0.0"},
        {"service_name": "ok.service", "port": 3693, "refresh_interval_seconds": -1, "host": "0.0.0.0"},
        {"service_name": "ok.service", "port": 3693, "refresh_interval_seconds": 60, "host": ""},
    ]

    for case in invalid_cases:
        try:
            install_service(
                repo_root=repo,
                hermes_home=tmp_path / "home",
                profile="main",
                environment="prod",
                refresh_interval_seconds=case["refresh_interval_seconds"],
                host=case["host"],
                port=case["port"],
                python_bin="/usr/bin/python3",
                systemd_dir=tmp_path / "systemd",
                service_name=case["service_name"],
                enable=False,
                dry_run=True,
            )
        except SystemExit:
            continue
        raise AssertionError(f"invalid installer options were accepted: {case}")


def test_default_service_name_is_profile_suffixed_for_profile_shaped_home(tmp_path):
    # Same last-deploy-wins class as the heartbeat/cognitive-loop units: with
    # the fixed default name, installing a second profile's dashboard would
    # silently overwrite the first profile's unit.
    from scripts.install_memory_os_monitor_dashboard_service import (
        DEFAULT_SERVICE_NAME,
        _default_service_name,
    )

    assert _default_service_name(tmp_path / "home") == DEFAULT_SERVICE_NAME
    assert (
        _default_service_name(tmp_path / ".hermes" / "profiles" / "sannai")
        == "hermes-memory-os-monitor-dashboard-sannai.service"
    )


def test_main_resolves_suffixed_default_but_explicit_name_wins(tmp_path, capsys):
    import json as _json

    from scripts.install_memory_os_monitor_dashboard_service import main

    home = tmp_path / ".hermes" / "profiles" / "sannai"
    assert main([
        "--hermes-home", str(home),
        "--systemd-dir", str(tmp_path / "systemd"),
        "--dry-run",
    ]) == 0
    report = _json.loads(capsys.readouterr().out)
    assert report["service_name"] == "hermes-memory-os-monitor-dashboard-sannai.service"

    assert main([
        "--hermes-home", str(home),
        "--systemd-dir", str(tmp_path / "systemd"),
        "--service-name", "custom.service",
        "--dry-run",
    ]) == 0
    report = _json.loads(capsys.readouterr().out)
    assert report["service_name"] == "custom.service"
