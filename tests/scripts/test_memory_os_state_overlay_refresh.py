"""Tests for the state overlay refresh cron script."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "memory_os_state_overlay_refresh.py"


def _load_refresh_module():
    """Load memory_os_state_overlay_refresh.py directly (same importlib
    pattern used by other tests under tests/scripts/), so a test can
    monkeypatch its module globals in-process instead of only exercising it
    as an opaque subprocess.
    """
    spec = importlib.util.spec_from_file_location(
        "memory_os_state_overlay_refresh_direct", _script_path(),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestStateOverlayRefreshScript:
    def test_script_help_works(self):
        result = subprocess.run(
            [sys.executable, str(_script_path()), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Refresh Memory State Overlay" in result.stdout

    def test_script_creates_output_files(self, tmp_path):
        home = tmp_path / ".hermes"
        (home / "memory-os" / "crystallized").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(_script_path()),
             "--hermes-home", str(home),
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0

        # Check output JSON
        output = json.loads(result.stdout)
        assert output["status"] == "ok"
        assert "sections" in output

        # Check current.json created
        json_path = home / "memory-os" / "system" / "state_overlay" / "current.json"
        assert json_path.exists()

        # Check current.md created
        md_path = home / "memory-os" / "system" / "state_overlay" / "current.md"
        assert md_path.exists()
        md_text = md_path.read_text(encoding="utf-8")
        assert "### Memory State Overlay" in md_text

        # Check runs.jsonl has a record
        runs_path = home / "memory-os" / "system" / "state_overlay" / "runs.jsonl"
        assert runs_path.exists()
        lines = runs_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1

    def test_script_fail_open_with_no_data(self, tmp_path):
        """Script succeeds (exit 0) even when no data sources exist."""
        home = tmp_path / ".hermes"
        # Don't create any data — just the bare home
        (home / "memory-os").mkdir(parents=True)

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(_script_path()),
             "--hermes-home", str(home),
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] in ("ok", "error")

    def test_script_with_last_sessions_populates_overlay(self, tmp_path):
        home = tmp_path / ".hermes"
        (home / "memory-os" / "crystallized").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)

        # Write a last session anchor
        lsa_path = home / "memory-os" / "system" / "last_session_anchor.jsonl"
        lsa_path.write_text(json.dumps({
            "session_id": "sess-001",
            "foreground_summary": "Fixed anchor pollution bug",
            "ended_at": "2026-07-06T10:00:00+00:00",
        }) + "\n")

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(_script_path()),
             "--hermes-home", str(home),
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] == "ok"

        # Verify overlay content
        json_path = home / "memory-os" / "system" / "state_overlay" / "current.json"
        overlay = json.loads(json_path.read_text(encoding="utf-8"))
        assert overlay["open_threads"]["status"] == "ok"
        assert len(overlay["open_threads"]["data"]) >= 1

    def test_script_with_task_anchor_populates_active_projects(self, tmp_path):
        home = tmp_path / ".hermes"
        (home / "memory-os" / "crystallized").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)

        # Write an active task anchor
        anchor_path = home / "memory-os" / "system" / "active_task_anchor.jsonl"
        anchor_path.write_text(json.dumps({
            "anchor": "### Current Foreground Task\nImplement state overlay\n\nCompleted: setup",
            "status": "active",
            "session_id": "sess-001",
        }) + "\n")

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(_script_path()),
             "--hermes-home", str(home),
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] == "ok"

        json_path = home / "memory-os" / "system" / "state_overlay" / "current.json"
        overlay = json.loads(json_path.read_text(encoding="utf-8"))
        assert overlay["active_projects"]["status"] == "ok"
        assert len(overlay["active_projects"]["data"]) >= 1

    def test_script_overlay_exposes_task_record_id_not_dead_watermark_field(self, tmp_path):
        """Counterfactual for FIX 2: the overlay must expose the effective
        task's real `record_id` under `task_record_id`, and must not write
        the dead `task_source_watermark` field (never populated by
        read_effective_current_task, so it was always an empty string with
        no consumer)."""
        home = tmp_path / ".hermes"
        (home / "memory-os" / "crystallized").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)

        anchor_path = home / "memory-os" / "system" / "active_task_anchor.jsonl"
        anchor_path.write_text(json.dumps({
            "record_id": "ata_counterfactualtest01",
            "anchor": "### Current Foreground Task\nImplement task_record_id fix",
            "status": "active",
            "session_id": "sess-002",
            "profile": "default",
        }) + "\n")

        env = {**__import__("os").environ, "HERMES_HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(_script_path()),
             "--hermes-home", str(home),
             "--profile", "default",
             "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0

        json_path = home / "memory-os" / "system" / "state_overlay" / "current.json"
        overlay = json.loads(json_path.read_text(encoding="utf-8"))

        assert overlay["task_record_id"] == "ata_counterfactualtest01"
        assert "task_source_watermark" not in overlay


class TestStateOverlaySectionCounterSingleSourceOfTruth:
    """Counterfactual for the six-site registry-duplication drift bug: this
    script's ``section_count`` loop must derive the set of sections from
    ``state_overlay_schema.OVERLAY_SECTION_FIELDS`` (the single source of
    truth), not a private hardcoded tuple. A previously hardcoded copy here
    silently excluded a since-removed section (community_snapshot) from the
    refresh cron's reported section_count for its entire lifetime.
    """

    def test_section_count_reflects_a_newly_added_derived_section(self, tmp_path, monkeypatch):
        module = _load_refresh_module()

        home = tmp_path / ".hermes"
        (home / "memory-os" / "crystallized").mkdir(parents=True)
        (home / "memory-os" / "system").mkdir(parents=True)

        # Simulate a future StateOverlay section that isn't among today's
        # real 8 sections, by extending the derived constant the script
        # actually imports and injecting it into the built overlay. Without
        # the fix (a hardcoded tuple in this script), this section would
        # never be counted no matter what OVERLAY_SECTION_FIELDS says.
        monkeypatch.setattr(
            module, "OVERLAY_SECTION_FIELDS",
            (*module.OVERLAY_SECTION_FIELDS, "future_section"),
        )
        original_build = module.build_state_overlay

        def _patched_build(*args, **kwargs):
            overlay = original_build(*args, **kwargs)
            overlay["future_section"] = {
                "data": [{"text": "x", "source": "s", "source_kind": "k"}],
                "source": "s",
                "status": "ok",
            }
            return overlay

        monkeypatch.setattr(module, "build_state_overlay", _patched_build)

        rc = module.main([
            "--hermes-home", str(home),
            "--output", "json",
        ])
        assert rc == 0

        json_path = home / "memory-os" / "system" / "state_overlay" / "current.json"
        overlay = json.loads(json_path.read_text(encoding="utf-8"))
        assert overlay["future_section"]["status"] == "ok"

        runs_path = home / "memory-os" / "system" / "state_overlay" / "runs.jsonl"
        last_run = json.loads(runs_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        # No real data was written (empty home), so only future_section is
        # "ok" — the count must be exactly 1, proving the injected section
        # was picked up by the counting loop.
        assert last_run["sections"] == 1

    def test_no_hand_maintained_section_tuple_remains_in_source(self):
        """Static guard: the historical hardcoded 8-tuple must not reappear."""
        source = _script_path().read_text(encoding="utf-8")
        assert "OVERLAY_SECTION_FIELDS" in source
        assert '"identity_snapshot", "relationship_snapshot", "active_projects",' not in source


class TestStateOverlayCronRegistration:
    def test_state_overlay_refresh_in_cron_specs(self):
        """state_overlay_refresh is registered in MEMORY_OS_CRON_SPECS."""
        from plugins.memory.memory_os.cron_registry import (
            MEMORY_OS_CRON_SPECS,
            memory_os_cron_spec_by_key,
        )
        spec = memory_os_cron_spec_by_key("state_overlay_refresh")
        assert spec is not None, "state_overlay_refresh must be in MEMORY_OS_CRON_SPECS"
        assert spec.name == "memory-os-state-overlay-refresh"
        assert spec.raw_script == "memory_os_state_overlay_refresh.py"
        assert spec.no_agent is True
        assert spec.helper_kind == "local_helper"
