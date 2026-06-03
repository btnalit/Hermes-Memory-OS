import json

from plugins.memory.memory_os.deployment_runtime_manifest import write_deployment_runtime_manifest
from plugins.memory.memory_os.host_capability_probe import probe_host_capabilities
from plugins.memory.memory_os.roots import MemoryOSRoots


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
    assert report["capabilities"]["memory_os_core"]["status"] == "present"
    assert report["capabilities"]["hermes_cron"]["status"] == "present"
    assert report["capabilities"]["skills"]["status"] == "present"
    assert report["capabilities"]["mcp"]["status"] == "present"
    assert report["capabilities"]["logs"]["status"] == "present"
    assert "SHOULD_NOT_LEAK" not in encoded
    assert "secret_token" not in encoded


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
    assert capability["status"] == "present"
    assert capability["deployed_head"] == "abc123"
    assert capability["freshness_status"] == "present"


def test_host_capability_probe_marks_optional_runtime_modules_missing(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")

    report = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")

    assert report["capabilities"]["memory_os_core"]["status"] == "missing"
    assert report["capabilities"]["wandering_mind"]["status"] == "missing"
    assert report["capabilities"]["mailbox"]["status"] == "missing"
    assert report["capabilities"]["owner_channel"]["status"] in {"missing", "configured", "dry_run_only"}
