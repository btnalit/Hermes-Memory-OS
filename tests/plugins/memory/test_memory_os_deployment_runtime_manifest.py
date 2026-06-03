import json
from datetime import datetime, timedelta, timezone

from plugins.memory.memory_os.deployment_runtime_manifest import (
    deployment_runtime_manifest_path,
    freshness_against_manifest,
    read_deployment_runtime_manifest,
    write_deployment_runtime_manifest,
)
from plugins.memory.memory_os.roots import MemoryOSRoots


def test_deployment_runtime_manifest_round_trips_manifest_without_secrets(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")

    manifest = write_deployment_runtime_manifest(
        roots,
        deployed_head="abc123",
        deployed_at="2026-06-03T01:00:00Z",
        active_runtime_path=str(tmp_path / "memory-os" / "runtime" / "python"),
        active_runtime_version="abc123",
        install_profile="upgrade",
        deploy_tool_version="memory-os.deploy.v0",
        source_repo_head="abc123",
    )
    loaded = read_deployment_runtime_manifest(roots)
    encoded = json.dumps(loaded, ensure_ascii=False)

    assert manifest["schema_version"] == "memory-os.deployment_runtime_manifest.v0"
    assert deployment_runtime_manifest_path(roots).is_file()
    assert loaded["status"] == "present"
    assert loaded["deployed_head"] == "abc123"
    assert loaded["profile_id"] == "memoryos-test"
    assert "SHOULD_NOT_LEAK" not in encoded


def test_freshness_against_manifest_splits_cycle_and_artifact_freshness(tmp_path):
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
    manifest = read_deployment_runtime_manifest(roots)

    stale = freshness_against_manifest(
        manifest,
        artifact_created_at="2026-06-03T00:59:00Z",
        cycle_started_at="2026-06-03T01:10:00Z",
    )
    fresh = freshness_against_manifest(
        manifest,
        artifact_created_at="2026-06-03T01:11:00Z",
        cycle_started_at="2026-06-03T01:10:00Z",
    )
    idle = freshness_against_manifest(
        manifest,
        artifact_created_at="2026-06-03T00:59:00Z",
        cycle_started_at=(datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        input_changed=False,
    )

    assert stale["fresh_after_deploy"] is False
    assert stale["artifact_freshness_status"] == "fail"
    assert fresh["fresh_after_deploy"] is True
    assert fresh["fresh_after_cycle"] is True
    assert fresh["artifact_freshness_status"] == "pass"
    assert idle["cycle_freshness_status"] == "pass"
    assert idle["idle_status"] == "healthy"
    assert idle["artifact_freshness_status"] == "idle"
