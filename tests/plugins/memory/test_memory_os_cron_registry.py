import json

from plugins.memory.memory_os.cron_registry import (
    cron_registry_snapshot,
    memory_os_cron_specs,
    specs_from_snapshot,
    write_cron_registry_snapshot,
)


def test_cron_registry_snapshot_round_trips_all_specs(tmp_path):
    snapshot_path = tmp_path / "memory-os" / "system" / "memory_os_cron_registry.json"

    written = write_cron_registry_snapshot(snapshot_path, source_commit="abc123")
    loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
    restored = specs_from_snapshot(loaded)

    assert written == cron_registry_snapshot(source_commit="abc123")
    assert loaded["schema_version"] == "memory-os.cron_registry.v0"
    assert loaded["source_commit"] == "abc123"
    assert [spec.key for spec in restored] == [spec.key for spec in memory_os_cron_specs()]
    assert all(spec.wrapper_script.startswith("memory_os_cron_") for spec in restored)
    assert all(spec.schedule_arg for spec in restored)
    assert all(spec.prompt_ref for spec in restored)
