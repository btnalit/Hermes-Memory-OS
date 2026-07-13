from __future__ import annotations

import json

from plugins.memory.memory_os.v3_ephemeral_adapter import HermesEphemeralAdapter, resolve_host_route_snapshot


def test_capability_is_injected_and_not_an_ambient_path_guess(monkeypatch):
    import plugins.memory.memory_os.v3_ephemeral_adapter as module

    monkeypatch.setattr(module, "_load_auxiliary_callable", lambda _root, _home: (lambda **_kwargs: None))
    assert HermesEphemeralAdapter().capability is True


def test_adapter_uses_pinned_route_no_tools_and_structured_json():
    adapter = HermesEphemeralAdapter()
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return {"content": '{"entries":[]}', "model": "demo/model"}

    adapter._callable = fake
    route = {"provider": "custom:demo", "model": "demo/model", "allowed_routes": [{"provider": "custom:demo", "model": "demo/model"}]}
    result = adapter.infer(packet={"snapshot_id": "v3body_test"}, prompt_contract="JSON only", route_snapshot=route)
    assert result["structured_output"] == {"entries": []}
    assert result["actual_provider"] == "custom:demo"
    assert result["fallback_used"] is False
    assert captured["tools"] == []
    assert captured["messages"][0]["role"] == "system"
    assert json.loads(captured["messages"][1]["content"])["snapshot_id"] == "v3body_test"


def test_isolated_worker_executes_without_session_or_delivery_files(tmp_path):
    import os
    import sys

    host = tmp_path / "host"
    (host / "agent").mkdir(parents=True)
    (host / "agent" / "__init__.py").write_text("", encoding="utf-8")
    (host / "agent" / "auxiliary_client.py").write_text(
        "class R:\n    model='demo/model'\n    content='{\\\"entries\\\":[]}'\n"
        "def call_llm(**kwargs):\n    assert kwargs['tools']==[]\n    return R()\n"
        "def extract_content_or_reasoning(response):\n    return response.content\n",
        encoding="utf-8",
    )
    (host / "venv" / "bin").mkdir(parents=True)
    os.symlink(sys.executable, host / "venv" / "bin" / "python")
    home = tmp_path / "home" / ".hermes"
    home.mkdir(parents=True)
    adapter = HermesEphemeralAdapter(host_agent_root=host, hermes_home=home)
    result = adapter.infer(
        packet={"snapshot_id": "v3body_test"},
        prompt_contract="JSON only",
        route_snapshot={"provider": "custom:demo", "model": "demo/model", "allowed_routes": [{"provider": "custom:demo", "model": "demo/model"}]},
    )
    assert result["structured_output"] == {"entries": []}
    assert not (home / "state.db").exists()
    assert not (home / "delivery").exists()


def test_route_snapshot_never_contains_credentials(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "model:\n  provider: custom:demo\n  default: demo/model\nproviders:\n  demo:\n    api_key: SECRET\n",
        encoding="utf-8",
    )
    snapshot = resolve_host_route_snapshot(tmp_path)
    assert snapshot["provider"] == "custom:demo"
    assert snapshot["model"] == "demo/model"
    assert "SECRET" not in repr(snapshot)
    assert set(snapshot) == {"provider", "model", "allowed_routes"}


def test_adapter_source_never_constructs_agent_session_or_delivery():
    import plugins.memory.memory_os.v3_ephemeral_adapter as module

    source = open(module.__file__, encoding="utf-8").read()
    for forbidden in ("AIAgent(", "SessionDB", "session_db", "send_message", "delivery/outbox", "trajectory"):
        assert forbidden not in source
