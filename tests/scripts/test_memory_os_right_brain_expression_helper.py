import importlib.util
import json
import os
import sys
from pathlib import Path

from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


def _load_helper():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_right_brain_expression.py"
    spec = importlib.util.spec_from_file_location("memory_os_right_brain_expression", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_right_brain_expression_helper_outputs_agent_prompt_and_records_request(tmp_path, capsys, monkeypatch):
    module = _load_helper()
    roots = MemoryOSRoots.from_hermes_home(tmp_path / "home", profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    store.append_event(
        EventEnvelope.from_dict(
            {
                **build_event(seed=1, profile="main"),
                "summary": "Owner希望右脑表达更自然，但不要变成任务报告。",
            }
        )
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERMES_PROFILE", "main")
    old_argv = sys.argv
    try:
        sys.argv = ["memory_os_right_brain_expression.py", "--channel", "origin", "--max-refs", "3"]
        assert module.main() == 0
    finally:
        sys.argv = old_argv

    output = capsys.readouterr().out
    assert "Hermes agent" in output
    assert "用中文" in output
    assert "Memory-OS 只提供 bounded context" in output
    assert "不要执行任务" in output
    assert "Owner希望右脑表达更自然" in output
    assert "raw_body" not in output

    requests = (tmp_path / "home" / "system-modules" / "right_brain_expression_adapter" / "requests.jsonl")
    records = [json.loads(line) for line in requests.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["delivery_mode"] == "hermes_cron_agent"
    assert records[-1]["channel"] == "origin"
    assert records[-1]["actual_send"] is False
    assert records[-1]["raw_body_included"] is False


def test_right_brain_expression_helper_stays_silent_without_context(tmp_path, capsys, monkeypatch):
    module = _load_helper()
    MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path / "home", profile="main")).initialize()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERMES_PROFILE", "main")
    old_argv = sys.argv
    try:
        sys.argv = ["memory_os_right_brain_expression.py"]
        assert module.main() == 0
    finally:
        sys.argv = old_argv

    assert capsys.readouterr().out == ""
