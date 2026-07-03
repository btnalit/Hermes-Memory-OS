#!/usr/bin/env python3
"""Shared host runtime defaults for Memory-OS scripts."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass


# Default repo-root on remote SSH targets.  This is a sensible convention,
# not a hard requirement — the install/deploy tooling derives its own
# REPO_ROOT from the script location.  Override per host via:
#   1. --remote-repo-root <path>          (CLI, always wins)
#   2. MEMORY_OS_REPO_ROOT env var         (session-wide default)
#   3. known-host profile entry             (per-host in KNOWN_HOST_RUNTIME_PROFILES)
DEFAULT_REMOTE_REPO_ROOT = "/opt/Hermes-Memory-OS"
DEFAULT_HERMES_HOME = "/root/.hermes"


@dataclass(frozen=True)
class HostRuntimeProfile:
    host_alias: str
    remote_repo_root: str
    hermes_home: str
    python_bin: str
    monitor_profile: str
    profile_source: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


KNOWN_HOST_RUNTIME_PROFILES: dict[str, dict[str, str]] = {
    "hermes-media": {
        "remote_repo_root": DEFAULT_REMOTE_REPO_ROOT,
        "hermes_home": DEFAULT_HERMES_HOME,
        "python_bin": "python3",
        "monitor_profile": "live",
    },
    "10.20.3.200": {
        "remote_repo_root": DEFAULT_REMOTE_REPO_ROOT,
        "hermes_home": DEFAULT_HERMES_HOME,
        "python_bin": "python3",
        "monitor_profile": "live",
    },
    "hermes-feiniu": {
        "remote_repo_root": DEFAULT_REMOTE_REPO_ROOT,
        "hermes_home": DEFAULT_HERMES_HOME,
        "python_bin": "python3",
        "monitor_profile": "clean-host",
    },
    "10.20.2.66": {
        "remote_repo_root": DEFAULT_REMOTE_REPO_ROOT,
        "hermes_home": DEFAULT_HERMES_HOME,
        "python_bin": "python3",
        "monitor_profile": "clean-host",
    },
}


def resolve_host_runtime_profile(
    *,
    host: str = "",
    remote_repo_root: str = "",
    hermes_home: str = "",
    python_bin: str = "",
    monitor_profile: str = "",
    default_monitor_profile: str = "live",
    require_remote_repo_root: bool = True,
) -> HostRuntimeProfile:
    host_alias = str(host or "").strip()
    known = KNOWN_HOST_RUNTIME_PROFILES.get(host_alias, {})

    # ── Resolution order: CLI > MEMORY_OS_REPO_ROOT env > known-host > default ──
    cli_remote_repo_root = str(remote_repo_root or "").strip()
    env_remote_repo_root = os.environ.get("MEMORY_OS_REPO_ROOT", "").strip()

    if require_remote_repo_root and host_alias and not known and not cli_remote_repo_root and not env_remote_repo_root:
        raise ValueError(
            "--remote-repo-root is required for --host when the host has no known Memory-OS runtime root "
            "(set MEMORY_OS_REPO_ROOT env var or pass --remote-repo-root)"
        )

    base_remote_repo_root = str(known.get("remote_repo_root") or "")
    base_hermes_home = str(known.get("hermes_home") or DEFAULT_HERMES_HOME)
    base_python_bin = str(known.get("python_bin") or ("python3" if host_alias else "python"))
    base_monitor_profile = str(known.get("monitor_profile") or default_monitor_profile or "live")

    effective_remote_repo_root = cli_remote_repo_root or env_remote_repo_root or base_remote_repo_root
    effective_hermes_home = str(hermes_home or "").strip() or base_hermes_home
    effective_python_bin = str(python_bin or "").strip() or base_python_bin
    effective_monitor_profile = str(monitor_profile or "").strip() or base_monitor_profile

    override_used = any(
        (
            bool(str(remote_repo_root or "").strip()) and str(remote_repo_root).strip() != base_remote_repo_root,
            bool(str(hermes_home or "").strip()) and str(hermes_home).strip() != base_hermes_home,
            bool(str(python_bin or "").strip()) and str(python_bin).strip() != base_python_bin,
            bool(str(monitor_profile or "").strip()) and str(monitor_profile).strip() != base_monitor_profile,
        )
    )
    if known:
        profile_source = "known_host+cli_override" if override_used else "known_host"
    elif host_alias:
        profile_source = "cli_override"
    else:
        profile_source = "local+cli_override" if override_used else "local"

    return HostRuntimeProfile(
        host_alias=host_alias or "local",
        remote_repo_root=effective_remote_repo_root,
        hermes_home=effective_hermes_home,
        python_bin=effective_python_bin,
        monitor_profile=effective_monitor_profile,
        profile_source=profile_source,
    )
