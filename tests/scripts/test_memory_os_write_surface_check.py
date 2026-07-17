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


def test_write_surface_check_flags_append_jsonl_locked_call_in_any_file(tmp_path):
    """P2 fix: append_jsonl_locked/_atomic_write_json call-site detection was
    hardcoded to only v3_seed_evidence.py and v3_wandering.py — a bare-name
    call to the governed append_jsonl_locked primitive anywhere else in the
    scanned tree was invisible to the scanner. This is exactly the pattern
    that surfaced plugins/memory/memory_os/recall_policy.py::append_recall_observation
    (line ~133) once generalized; a brand-new file outside the two
    originally-hardcoded ones must be caught too.
    """
    module = tmp_path / "plugins" / "memory" / "memory_os" / "some_other_lane.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from plugins.memory.memory_os.jsonl_io import append_jsonl_locked\n"
        "def write_some_other_lane(path, record):\n"
        "    append_jsonl_locked(path, record)\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts").mkdir()

    report = run_write_surface_check(tmp_path)

    assert report["status"] == "fail"
    assert report["unclassified_count"] == 1
    unclassified = report["unclassified"][0]
    assert unclassified["rel_path"] == "plugins/memory/memory_os/some_other_lane.py"
    assert unclassified["kind"] == "append_jsonl_locked_call"
