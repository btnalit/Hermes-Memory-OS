import os

import pytest

from scripts.memory_os_host_profile import resolve_host_runtime_profile


def test_host_runtime_profile_resolves_known_media_defaults():
    profile = resolve_host_runtime_profile(host="hermes-media")

    assert profile.host_alias == "hermes-media"
    assert profile.remote_repo_root == "/opt/Hermes-Memory-OS"
    assert profile.hermes_home == "/root/.hermes"
    assert profile.monitor_profile == "live"
    assert profile.profile_source == "known_host"


def test_host_runtime_profile_records_cli_overrides():
    profile = resolve_host_runtime_profile(
        host="hermes-feiniu",
        remote_repo_root="/srv/custom",
        hermes_home="/srv/hermes",
        monitor_profile="live",
        python_bin="/venv/bin/python",
    )

    assert profile.host_alias == "hermes-feiniu"
    assert profile.remote_repo_root == "/srv/custom"
    assert profile.hermes_home == "/srv/hermes"
    assert profile.monitor_profile == "live"
    assert profile.python_bin == "/venv/bin/python"
    assert profile.profile_source == "known_host+cli_override"


def test_host_runtime_profile_resolves_ip_literal_aliases():
    media = resolve_host_runtime_profile(host="10.20.3.200")
    feiniu = resolve_host_runtime_profile(host="10.20.2.66")

    assert media.remote_repo_root == "/opt/Hermes-Memory-OS"
    assert media.hermes_home == "/root/.hermes"
    assert media.monitor_profile == "live"
    assert media.profile_source == "known_host"
    assert feiniu.remote_repo_root == "/opt/Hermes-Memory-OS"
    assert feiniu.hermes_home == "/root/.hermes"
    assert feiniu.monitor_profile == "clean-host"
    assert feiniu.profile_source == "known_host"


# ── Resolution order: CLI > MEMORY_OS_REPO_ROOT env > known-host > default ──

def test_env_var_overrides_known_host_default(monkeypatch):
    """MEMORY_OS_REPO_ROOT env var takes priority over known-host default."""
    monkeypatch.setenv("MEMORY_OS_REPO_ROOT", "/root/Hermes-Memory-OS")
    profile = resolve_host_runtime_profile(host="hermes-media")

    # env var beats the known-host default (/opt/Hermes-Memory-OS)
    assert profile.remote_repo_root == "/root/Hermes-Memory-OS"
    assert profile.profile_source == "known_host"  # env is not a "CLI override"


def test_cli_still_wins_over_env_var(monkeypatch):
    """--remote-repo-root CLI flag beats MEMORY_OS_REPO_ROOT env var."""
    monkeypatch.setenv("MEMORY_OS_REPO_ROOT", "/root/Hermes-Memory-OS")
    profile = resolve_host_runtime_profile(
        host="hermes-media",
        remote_repo_root="/srv/explicit",
    )

    assert profile.remote_repo_root == "/srv/explicit"
    assert profile.profile_source == "known_host+cli_override"


def test_unknown_host_with_env_var_does_not_raise(monkeypatch):
    """Unknown host + MEMORY_OS_REPO_ROOT env var → no error, env used."""
    monkeypatch.setenv("MEMORY_OS_REPO_ROOT", "/root/Hermes-Memory-OS")
    profile = resolve_host_runtime_profile(host="unknown-box")

    assert profile.remote_repo_root == "/root/Hermes-Memory-OS"
    assert profile.host_alias == "unknown-box"
    assert profile.profile_source == "cli_override"


def test_unknown_host_without_cli_or_env_raises():
    """Unknown host + no --remote-repo-root + no env var → ValueError."""
    with pytest.raises(ValueError, match="--remote-repo-root is required"):
        resolve_host_runtime_profile(host="unknown-box")


def test_env_var_ignored_when_cli_provided_for_unknown_host(monkeypatch):
    """CLI still wins for unknown host, and env var prevents the error if CLI absent."""
    monkeypatch.setenv("MEMORY_OS_REPO_ROOT", "/root/Hermes-Memory-OS")
    # With env var set, no CLI needed — should work
    profile = resolve_host_runtime_profile(host="new-host")
    assert profile.remote_repo_root == "/root/Hermes-Memory-OS"

    # CLI overrides env
    profile2 = resolve_host_runtime_profile(
        host="new-host",
        remote_repo_root="/opt/explicit",
    )
    assert profile2.remote_repo_root == "/opt/explicit"
