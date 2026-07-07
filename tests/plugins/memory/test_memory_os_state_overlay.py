"""Tests for Memory State Overlay builder, renderer, and integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.memory.memory_os.state_overlay_schema import (
    StateOverlay,
    OverlayEntry,
    OverlaySection,
    STATE_OVERLAY_SCHEMA_VERSION,
)
from plugins.memory.memory_os.state_overlay import (
    build_state_overlay,
    write_state_overlay,
    append_overlay_run,
)
from plugins.memory.memory_os.state_overlay_renderer import (
    render_state_overlay_md,
    render_state_overlay_md_short,
)
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.roots import MemoryOSRoots


# ── Helpers ──────────────────────────────────────────────────────────


def _make_roots(tmp_path: Path, *, profile: str = "test") -> MemoryOSRoots:
    """Create MemoryOSRoots pointing into a temp directory."""
    home = tmp_path / ".hermes"
    # Ensure crystallized dir exists so the builder can read from it
    (home / "memory-os" / "crystallized").mkdir(parents=True)
    (home / "memory-os" / "system").mkdir(parents=True)
    return MemoryOSRoots.from_hermes_home(str(home), profile=profile)


def _make_store(roots: MemoryOSRoots) -> MemoryOSStore:
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _write_last_session_anchor(roots: MemoryOSRoots, **kw: str) -> None:
    """Append a last session anchor record."""
    path = roots.memory_os_root / "system" / "last_session_anchor.jsonl"
    record = {
        "session_id": kw.get("session_id", "sess-001"),
        "foreground_summary": kw.get("foreground", "Test foreground"),
        "ended_at": kw.get("ended_at", "2026-07-06T10:00:00+00:00"),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _write_crystallized_preference(roots: MemoryOSRoots, body: str, ref_id: str = "pref-001") -> None:
    """Write a crystallized markdown file with kind=preference."""
    path = roots.crystallized_root / f"{ref_id}.md"
    content = f"""---
kind: preference
id: {ref_id}
---
{body}
"""
    path.write_text(content, encoding="utf-8")


# ── Schema tests ─────────────────────────────────────────────────────


class TestStateOverlaySchema:
    def test_overlay_entry_to_dict(self):
        entry = OverlayEntry(text="hello", source="test:1", source_kind="test")
        d = entry.to_dict()
        assert d["text"] == "hello"
        assert d["source"] == "test:1"
        assert d["source_kind"] == "test"

    def test_overlay_section_empty_status(self):
        section = OverlaySection(source="test source")
        d = section.to_dict()
        assert d["status"] == "insufficient_data"
        assert d["data"] == []

    def test_overlay_section_with_data_status(self):
        section = OverlaySection(
            data=[OverlayEntry(text="x", source="s")],
            source="test source",
        )
        d = section.to_dict()
        assert d["status"] == "ok"

    def test_state_overlay_create_sets_generated_at(self):
        overlay = StateOverlay.create(profile="test")
        assert overlay.generated_at
        assert overlay.profile == "test"
        assert overlay.schema_version == STATE_OVERLAY_SCHEMA_VERSION

    def test_state_overlay_to_dict_has_all_sections(self):
        overlay = StateOverlay.create(profile="test")
        d = overlay.to_dict()
        assert d["schema_version"] == STATE_OVERLAY_SCHEMA_VERSION
        for key in (
            "identity_snapshot", "relationship_snapshot", "active_projects",
            "open_threads", "recent_events", "owner_preferences",
            "capability_map", "material_index",
        ):
            assert key in d
            assert isinstance(d[key], dict)
            assert "status" in d[key]
            assert "source" in d[key]
            assert "data" in d[key]


# ── Builder tests ────────────────────────────────────────────────────


class TestBuildStateOverlay:
    def test_build_overlay_empty_store_returns_all_sections(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        assert overlay["schema_version"] == STATE_OVERLAY_SCHEMA_VERSION
        # All sections present even when empty
        assert overlay["active_projects"]["status"] == "insufficient_data"

    def test_build_overlay_with_task_anchor_populates_active_projects(self, tmp_path):
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        anchor = "### Current Foreground Task\nImplement state overlay\n\nCompleted: setup"
        overlay = build_state_overlay(store, roots, current_task_anchor=anchor)
        assert len(overlay["active_projects"]["data"]) >= 1
        assert overlay["active_projects"]["status"] == "ok"
        assert "state overlay" in overlay["active_projects"]["data"][0]["text"].lower()

    def test_build_overlay_with_last_sessions_populates_open_threads(self, tmp_path):
        roots = _make_roots(tmp_path)
        _write_last_session_anchor(roots, session_id="sess-001",
                                   foreground="Fixed anchor pollution bug",
                                   ended_at="2026-07-06T09:00:00+00:00")
        _write_last_session_anchor(roots, session_id="sess-002",
                                   foreground="Deployed fact judge hardening",
                                   ended_at="2026-07-06T10:00:00+00:00")
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        assert len(overlay["open_threads"]["data"]) >= 1
        assert overlay["open_threads"]["status"] == "ok"

    def test_build_overlay_with_preference_crystallized(self, tmp_path):
        roots = _make_roots(tmp_path)
        _write_crystallized_preference(roots, "Prefer concise responses", "pref-001")
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        assert len(overlay["owner_preferences"]["data"]) >= 1
        assert overlay["owner_preferences"]["status"] == "ok"

    def test_build_overlay_never_writes_to_canonical(self, tmp_path):
        """build_state_overlay returns a dict — no filesystem side effects."""
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        # Count files before
        before = list(roots.memory_os_root.rglob("*"))
        build_state_overlay(store, roots)
        after = list(roots.memory_os_root.rglob("*"))
        # No new files should appear (only dirs may have been created by initialize)
        assert len(after) == len(before)

    def test_build_overlay_with_event_stats(self, tmp_path):
        roots = _make_roots(tmp_path)
        stats_path = roots.memory_os_root / "system" / "event_stats.json"
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps({
            "total_event_count": 5,
            "recent_event_summaries": [
                {"kind": "conversation_turn", "summary": "Discussed overlay design"},
                {"kind": "fact_judge", "summary": "Judged memory candidates"},
            ],
        }))
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        assert len(overlay["recent_events"]["data"]) >= 1
        assert overlay["recent_events"]["status"] == "ok"

    def test_build_overlay_empty_roots_no_crash(self, tmp_path):
        """Even with zero data, build_state_overlay must not raise."""
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        assert isinstance(overlay, dict)
        assert overlay["schema_version"] == STATE_OVERLAY_SCHEMA_VERSION

    def test_build_overlay_filters_compaction_and_prior_context_noise(self, tmp_path):
        roots = _make_roots(tmp_path)
        _write_last_session_anchor(
            roots,
            session_id="sess-noise",
            foreground=(
                "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted\n"
                "Earli... compacted summary residue that should be removed\n"
                "[PRIOR CONTEXT — for reference only; not a new message]\n"
                "Real follow-up: verify BGE-M3 runs on CPU"
            ),
            ended_at="2026-07-06T10:00:00+00:00",
        )
        store = _make_store(roots)

        overlay = build_state_overlay(
            store,
            roots,
            current_task_anchor=(
                "[System note: The following is recalled memory context, NOT new user input.]\n"
                "### Current Foreground Task\n"
                "Fix State Overlay cleaning"
            ),
        )
        rendered = json.dumps(overlay, ensure_ascii=False)

        assert "CONTEXT COMPACTION" not in rendered
        assert "PRIOR CONTEXT" not in rendered
        assert "System note:" not in rendered
        assert "Earlier turns" not in rendered
        assert "Earli..." not in rendered
        assert "Real follow-up: verify BGE-M3 runs on CPU" in rendered
        assert "Fix State Overlay cleaning" in rendered

    def test_build_overlay_filters_document_upload_boilerplate(self, tmp_path):
        roots = _make_roots(tmp_path)
        stats_path = roots.memory_os_root / "system" / "event_stats.json"
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps({
            "recent_event_summaries": [
                {
                    "kind": "conversation_turn",
                    "summary": (
                        "[The user sent a text document: 'memory-os-plan.md'. "
                        "Its content has been included below. The file is also saved at: /tmp/doc.md]"
                    ),
                },
                {"kind": "conversation_turn", "summary": "Useful event: overlay filter added"},
            ],
        }), encoding="utf-8")
        store = _make_store(roots)

        overlay = build_state_overlay(store, roots)
        rendered = json.dumps(overlay, ensure_ascii=False)

        assert "The user sent a text document" not in rendered
        assert "Its content has been included below" not in rendered
        assert "file is also saved" not in rendered
        assert "Useful event: overlay filter added" in rendered


# ── I/O tests ────────────────────────────────────────────────────────


class TestWriteStateOverlay:
    def test_write_state_overlay_creates_current_json(self, tmp_path):
        roots = _make_roots(tmp_path)
        overlay = StateOverlay.create(profile="test").to_dict()
        out_path = write_state_overlay(roots, overlay)
        assert out_path.exists()
        assert out_path.name == "current.json"
        assert "state_overlay" in str(out_path)
        # Round-trip
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert loaded["schema_version"] == STATE_OVERLAY_SCHEMA_VERSION

    def test_append_overlay_run_appends_to_runs_jsonl(self, tmp_path):
        roots = _make_roots(tmp_path)
        append_overlay_run(roots, {"status": "ok", "sections": 3, "duration_ms": 42})
        append_overlay_run(roots, {"status": "ok", "sections": 2, "duration_ms": 35})
        runs_path = roots.memory_os_root / "system" / "state_overlay" / "runs.jsonl"
        assert runs_path.exists()
        lines = runs_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            record = json.loads(line)
            assert record["status"] == "ok"
            assert "ts" in record


# ── Renderer tests ───────────────────────────────────────────────────


class TestRenderStateOverlayMd:
    def test_render_basic_produces_markdown(self):
        overlay = StateOverlay.create(profile="test").to_dict()
        result = render_state_overlay_md(overlay)
        assert "### Memory State Overlay" in result

    def test_render_with_data_sections(self):
        overlay = StateOverlay.create(profile="test")
        overlay.active_projects.data.append(
            OverlayEntry(text="Build state overlay", source="task_anchor:current",
                         source_kind="task_anchor"))
        overlay.active_projects.status = "ok"
        overlay.open_threads.data.append(
            OverlayEntry(text="Fix anchor bug", source="last_session:sess-001",
                         source_kind="last_session"))
        overlay.open_threads.status = "ok"
        result = render_state_overlay_md(overlay.to_dict())
        assert "[Active]" in result
        assert "[Open threads]" in result
        assert "[src:" in result

    def test_render_truncates_when_too_long(self):
        overlay = StateOverlay.create(profile="test")
        # Add lots of data to force truncation
        for i in range(50):
            overlay.recent_events.data.append(
                OverlayEntry(
                    text=f"Event number {i}: some long description " + "x" * 50,
                    source=f"event:{i}",
                    source_kind="event",
                )
            )
        overlay.recent_events.status = "ok"
        result = render_state_overlay_md(overlay.to_dict(), max_chars=500)
        assert len(result) <= 500
        assert "..._(truncated)_" in result

    def test_render_short_excludes_non_short_sections(self):
        overlay = StateOverlay.create(profile="test")
        overlay.recent_events.data.append(
            OverlayEntry(text="Recent event", source="e:1", source_kind="event"))
        overlay.recent_events.status = "ok"
        overlay.active_projects.data.append(
            OverlayEntry(text="Active project", source="ta:1", source_kind="task_anchor"))
        overlay.active_projects.status = "ok"
        result = render_state_overlay_md_short(overlay.to_dict(), max_chars=600)
        # Short version includes active_projects but NOT recent_events
        assert "[Active]" in result
        assert "[Recent]" not in result

    def test_render_short_respects_max_chars(self):
        overlay = StateOverlay.create(profile="test")
        for i in range(20):
            overlay.active_projects.data.append(
                OverlayEntry(text=f"Project {i} " + "x" * 80, source=f"p:{i}",
                             source_kind="task_anchor"))
        overlay.active_projects.status = "ok"
        result = render_state_overlay_md_short(overlay.to_dict(), max_chars=300)
        assert len(result) <= 300

    def test_render_insufficient_data_section_shows_marker(self):
        overlay = StateOverlay.create(profile="test")
        # open_threads should show insufficient_data when empty (not skipped)
        result = render_state_overlay_md(overlay.to_dict())
        assert "insufficient data" in result

    def test_render_empty_overlay_no_error(self):
        """Empty overlay must render without raising."""
        overlay = StateOverlay.create(profile="test").to_dict()
        result = render_state_overlay_md(overlay)
        assert len(result) > 0
        assert result.startswith("### Memory State Overlay")


class TestPrefetchStateOverlayIntegration:
    def test_state_overlay_lines_do_not_duplicate_prefetch_section_header(self, tmp_path):
        from plugins.memory.memory_os.prefetch import _state_overlay_lines

        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        overlay = StateOverlay.create(profile="test")
        overlay.active_projects.data.append(
            OverlayEntry(text="Build state overlay", source="task_anchor:current",
                         source_kind="task_anchor"))
        overlay.active_projects.status = "ok"
        write_state_overlay(roots, overlay.to_dict())

        lines = _state_overlay_lines(store, roots=roots)

        assert lines
        assert lines[0] != "### Memory State Overlay"
        assert all(line != "### Memory State Overlay" for line in lines)
