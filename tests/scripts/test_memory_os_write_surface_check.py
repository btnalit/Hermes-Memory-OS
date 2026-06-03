from pathlib import Path

from scripts.memory_os_write_surface_check import run_write_surface_check


def test_write_surface_check_passes_current_registered_surfaces():
    report = run_write_surface_check(Path("."))

    assert report["schema_version"] == "memory-os.write_surface_check.v0"
    assert report["status"] == "pass"
    assert report["unclassified_count"] == 0
    assert report["allowed_count"] == report["surface_count"]


def test_write_surface_check_flags_unregistered_direct_jsonl_append(tmp_path):
    module = tmp_path / "plugins" / "memory" / "memory_os" / "new_lane.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "import json\n"
        "def write_new_lane(path, record):\n"
        "    with path.open('a', encoding='utf-8') as handle:\n"
        "        handle.write(json.dumps(record) + '\\n')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts").mkdir()

    report = run_write_surface_check(tmp_path)

    assert report["status"] == "fail"
    assert report["unclassified_count"] == 1
    assert report["unclassified"][0]["rel_path"] == "plugins/memory/memory_os/new_lane.py"
