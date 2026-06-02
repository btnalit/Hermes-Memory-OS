import json

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

    assert report["schema_version"] == "memory-os.host_capability_probe.v0"
    assert report["raw_body_included"] is False
    assert report["capabilities"]["memory_os_core"]["status"] == "present"
    assert report["capabilities"]["hermes_cron"]["status"] == "present"
    assert report["capabilities"]["skills"]["status"] == "present"
    assert report["capabilities"]["mcp"]["status"] == "present"
    assert report["capabilities"]["logs"]["status"] == "present"
    assert "SHOULD_NOT_LEAK" not in encoded
    assert "secret_token" not in encoded


def test_host_capability_probe_marks_optional_runtime_modules_missing(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")

    report = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")

    assert report["capabilities"]["memory_os_core"]["status"] == "missing"
    assert report["capabilities"]["wandering_mind"]["status"] == "missing"
    assert report["capabilities"]["mailbox"]["status"] == "missing"
    assert report["capabilities"]["owner_channel"]["status"] in {"missing", "configured", "dry_run_only"}
