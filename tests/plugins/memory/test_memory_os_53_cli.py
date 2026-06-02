import argparse
import json

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def test_53_cli_commands_are_callable_and_metadata_only(tmp_path, monkeypatch, capsys):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="default"))
    store.initialize()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    assert memory_os_command(_parse(["host-probe", "--json"])) == 0
    host_probe = json.loads(capsys.readouterr().out)
    assert host_probe["schema_version"] == "memory-os.host_capability_probe.v0"
    assert host_probe["raw_body_included"] is False

    assert memory_os_command(_parse(["signal-sources", "--collect", "--json"])) == 0
    collection = json.loads(capsys.readouterr().out)
    assert collection["schema_version"] == "memory-os.signal_collection.v0"
    assert collection["raw_body_included"] is False

    assert memory_os_command(_parse(["projection", "collect", "--manual-run-ref", "cli-test"])) == 0
    projection = json.loads(capsys.readouterr().out)
    assert projection["schema_version"] == "memory-os.memory_projection.v0"
    assert projection["live_closure_eligible"] is False

    assert memory_os_command(_parse(["projection", "status"])) == 0
    projection_status = json.loads(capsys.readouterr().out)
    assert projection_status["projection_count"] == projection["written_count"]

    assert memory_os_command(_parse(["left-brain", "advise", "--max-findings", "5"])) == 0
    advisor = json.loads(capsys.readouterr().out)
    assert advisor["schema_version"] == "memory-os.left_brain_advisor.v0"
    assert advisor["actual_execute"] is False

    assert memory_os_command(_parse(["left-brain", "status"])) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["report_count"] == 1


def _parse(argv):
    parser = argparse.ArgumentParser()
    register_cli(parser)
    return parser.parse_args(argv)
