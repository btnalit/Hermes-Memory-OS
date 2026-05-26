import importlib.util
import json
from pathlib import Path


def _load_helper_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_owner_review_digest.py"
    spec = importlib.util.spec_from_file_location("memory_os_owner_review_digest", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_digest_helper_prefers_recurring_delivery_channel_config(tmp_path, monkeypatch):
    module = _load_helper_module()
    config_path = tmp_path / "memory-os" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"owner_review": {"recurring_delivery_channel": "telegram"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    assert module._resolve_channel() == "telegram"


def test_digest_helper_falls_back_to_channel_report_when_config_missing(tmp_path, monkeypatch):
    module = _load_helper_module()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(module, "_run_json", lambda command: {"channel": "matrix"})

    assert module._resolve_channel() == "matrix"


def test_digest_helper_agenda_mode_only_treats_decisions_as_meaningful():
    module = _load_helper_module()

    assert (
        module._has_meaningful_content(
            {"counts": {"action_required_shown": 0, "review_suggested_shown": 2, "fyi_shown": 2}},
            digest_mode="agenda",
        )
        is False
    )
    assert (
        module._has_meaningful_content(
            {"counts": {"action_required_shown": 1, "review_suggested_shown": 0, "fyi_shown": 0}},
            digest_mode="agenda",
        )
        is True
    )


def test_digest_helper_review_mode_can_render_pull_review_content():
    module = _load_helper_module()

    assert (
        module._has_meaningful_content(
            {"counts": {"action_required_shown": 0, "review_suggested_shown": 1, "fyi_shown": 0}},
            digest_mode="review",
        )
        is True
    )
