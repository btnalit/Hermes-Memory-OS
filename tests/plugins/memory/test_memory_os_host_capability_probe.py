import json

from plugins.memory.memory_os.deployment_runtime_manifest import write_deployment_runtime_manifest
from plugins.memory.memory_os.host_capability_probe import probe_host_capabilities
from plugins.memory.memory_os.roots import MemoryOSRoots


EXPECTED_V2_CAPABILITY_KEYS = {
    "deployment_runtime_manifest",
    "hermes_version",
    "hermes_home_schema",
    "profile_layout",
    "active_runtime",
    "memory_os_plugin",
    "cron",
    "owner_channel",
    "memory_provider",
    "hindsight",
    "hindsight_write_origin",
    "mailbox",
    "wandering_mind",
    "skills",
    "tools",
    "mcp",
    "gateway",
    "logs",
    "execution_gate",
    "structural_write_gate",
}

LEGACY_COMPATIBILITY_KEYS = {
    "memory_os_core",
    "hermes_cron",
    "profile",
    "memory_sources",
    "session_mirror",
}

CAPABILITY_REQUIRED_FIELDS = {
    "capability_key",
    "owner_system",
    "status",
    "probe_method",
    "confidence",
    "source_scope_ref",
    "observed_at",
    "freshness_status",
    "adapter_required",
    "migration_hint",
}

ALLOWED_CAPABILITY_STATUSES = {"available", "missing", "disabled", "unknown", "migration_needed"}


def test_host_capability_probe_reports_safe_capabilities_without_raw_body(tmp_path):
    (tmp_path / "memory-os" / "system").mkdir(parents=True)
    (tmp_path / "cron").mkdir()
    (tmp_path / "cron" / "jobs.json").write_text(json.dumps({"jobs": []}), encoding="utf-8")
    (tmp_path / "skills").mkdir()
    (tmp_path / "mcp").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "sessions").mkdir()
    (tmp_path / "profiles").mkdir()
    (tmp_path / "config.json").write_text(
        json.dumps({"secret_token": "SHOULD_NOT_LEAK", "memory": {"provider": "memory_os"}}),
        encoding="utf-8",
    )
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")

    report = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["schema_version"] == "memory-os.host_capability_probe.v2"
    assert report["raw_body_included"] is False
    assert report["capabilities"]["memory_os_core"]["status"] == "available"
    assert report["capabilities"]["hermes_cron"]["status"] == "available"
    assert report["capabilities"]["skills"]["status"] == "available"
    assert report["capabilities"]["mcp"]["status"] == "available"
    assert report["capabilities"]["logs"]["status"] == "available"
    assert "SHOULD_NOT_LEAK" not in encoded
    assert "secret_token" not in encoded


def test_host_capability_probe_v2_exposes_full_capability_contract(tmp_path):
    (tmp_path / "memory-os" / "system").mkdir(parents=True)
    (tmp_path / "cron").mkdir()
    (tmp_path / "cron" / "jobs.json").write_text(json.dumps({"jobs": []}), encoding="utf-8")
    (tmp_path / "profiles" / "main").mkdir(parents=True)
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "mcp_servers.json").write_text(json.dumps({"servers": {}}), encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    (tmp_path / "system-modules" / "wandering_mind").mkdir(parents=True)
    (tmp_path / "hindsight").mkdir()
    (tmp_path / "hindsight" / "config.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "memory": {"provider": "memory_os"},
                "substrate_providers": {"hindsight": {"enabled": True, "recall_mode": "shadow"}},
                "owner_review": {"enabled": True},
            }
        ),
        encoding="utf-8",
    )
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    write_deployment_runtime_manifest(
        roots,
        deployed_head="abc123",
        deployed_at="2026-06-03T01:00:00Z",
        active_runtime_path=str(tmp_path / "memory-os" / "runtime" / "python"),
        active_runtime_version="abc123",
        install_profile="upgrade",
        deploy_tool_version="memory-os.deploy.v0",
        source_repo_head="abc123",
    )

    report = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")
    capabilities = report["capabilities"]

    assert EXPECTED_V2_CAPABILITY_KEYS.issubset(capabilities)
    assert LEGACY_COMPATIBILITY_KEYS.issubset(capabilities)
    assert report["capability_contract"]["required_capability_count"] >= len(EXPECTED_V2_CAPABILITY_KEYS)
    assert report["capability_contract"]["contract_status"] == "ok"
    assert report["capability_status_counts"]["available"] >= 1
    assert report["required_capability_status_counts"]["available"] >= 1
    assert report["missing_required_capability_count"] == 0
    assert report["required_missing_status_count"] >= 1
    assert report["required_migration_needed_status_count"] >= 0
    assert report["migration_needed_capability_count"] >= 0
    assert capabilities["structural_write_gate"]["status"] == "available"
    assert capabilities["structural_write_gate"]["append_governed_jsonl_available"] is True

    for key, capability in capabilities.items():
        assert CAPABILITY_REQUIRED_FIELDS.issubset(capability), key
        assert capability["capability_key"] == key
        assert capability["status"] in ALLOWED_CAPABILITY_STATUSES
        assert capability["source_scope_ref"], key
        assert capability["observed_at"].endswith("Z"), key
        assert capability["raw_body_included"] is False
        assert capability["secret_values_included"] is False


def test_host_capability_probe_v2_includes_deployment_runtime_manifest(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    write_deployment_runtime_manifest(
        roots,
        deployed_head="abc123",
        deployed_at="2026-06-03T01:00:00Z",
        active_runtime_path=str(tmp_path / "memory-os" / "runtime" / "python"),
        active_runtime_version="abc123",
        install_profile="upgrade",
        deploy_tool_version="memory-os.deploy.v0",
        source_repo_head="abc123",
    )

    report = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")
    manifest = report["deployment_runtime_manifest"]
    capability = report["capabilities"]["deployment_runtime_manifest"]

    assert manifest["schema_version"] == "memory-os.deployment_runtime_manifest.v0"
    assert manifest["deployed_head"] == "abc123"
    assert capability["status"] == "available"
    assert capability["deployed_head"] == "abc123"
    assert capability["freshness_status"] == "present"


def test_host_capability_probe_marks_optional_runtime_modules_missing(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")

    report = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")

    assert report["capabilities"]["memory_os_core"]["status"] == "missing"
    assert report["capabilities"]["wandering_mind"]["status"] == "missing"
    assert report["capabilities"]["mailbox"]["status"] == "missing"
    assert report["capabilities"]["owner_channel"]["status"] in {"missing", "available", "disabled", "unknown"}


def test_host_capability_probe_marks_disabled_hindsight_substrate_disabled(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"substrate_providers": {"hindsight": {"enabled": False}}}),
        encoding="utf-8",
    )
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")

    report = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")
    hindsight = report["capabilities"]["hindsight"]

    assert hindsight["status"] == "disabled"
    assert hindsight["memory_os_substrate_enabled"] is False
