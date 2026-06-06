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
