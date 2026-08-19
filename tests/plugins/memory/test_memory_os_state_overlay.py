"""Tests for Memory State Overlay builder, renderer, and integration."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.state_overlay_schema import (
    StateOverlay,
    OverlayEntry,
    OverlaySection,
    STATE_OVERLAY_SCHEMA_VERSION,
    OVERLAY_SECTION_FIELDS,
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
from plugins.memory.memory_os.event_stats import build_event_stats, write_event_stats
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.roots import MemoryOSRoots


def _write_event_stats_via_producer(roots: MemoryOSRoots, events: list[dict]) -> None:
    """Materialise event_stats.json the way production does.

    Deliberately routed through build_event_stats + write_event_stats rather
    than hand-writing JSON at a path literal.  Hand-written fixtures are what
    hid the producer/consumer path drift here for the deployment's whole
    life: the fixture wrote to the same wrong directory the consumer read
    from, so the test agreed with the bug instead of catching it.
    """
    write_event_stats(roots, build_event_stats(events))


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
        """Expectation is derived from OVERLAY_SECTION_FIELDS (the dataclass's
        own fields typed OverlaySection) rather than a hand-typed list. A
        hand-typed list here was itself part of a real drift bug: it was kept
        in sync with to_dict() only, so it never caught that four other
        consumers had silently dropped a removed section.
        """
        overlay = StateOverlay.create(profile="test")
        d = overlay.to_dict()
        assert d["schema_version"] == STATE_OVERLAY_SCHEMA_VERSION
        # Sanity: the derivation actually found the sections (guards against
        # a no-op that would make every assertion below vacuously true).
        assert len(OVERLAY_SECTION_FIELDS) == 8
        for key in OVERLAY_SECTION_FIELDS:
            assert key in d
            assert isinstance(d[key], dict)
            assert "status" in d[key]
            assert "source" in d[key]
            assert "data" in d[key]

    def test_state_overlay_to_dict_key_order_matches_declaration_order(self):
        """Byte-identical serialization guarantee (constraint 4): to_dict()'s
        key order must still be schema_version, generated_at, profile, each
        section in declaration order, risk_notes, evidence_refs — unchanged
        by the refactor to derive sections from OVERLAY_SECTION_FIELDS.
        """
        d = StateOverlay.create(profile="test").to_dict()
        assert list(d.keys()) == [
            "schema_version", "generated_at", "profile",
            "identity_snapshot", "relationship_snapshot", "active_projects",
            "open_threads", "recent_events", "owner_preferences",
            "capability_map", "material_index",
            "risk_notes", "evidence_refs",
        ]


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

    def test_build_overlay_deduplicates_identical_open_threads_across_sessions(self, tmp_path):
        roots = _make_roots(tmp_path)
        shared = "Implement the daily almanac workflow"
        _write_last_session_anchor(
            roots,
            session_id="sess-older",
            foreground=shared,
            ended_at="2026-07-06T09:00:00+00:00",
        )
        _write_last_session_anchor(
            roots,
            session_id="sess-newer",
            foreground=shared,
            ended_at="2026-07-06T10:00:00+00:00",
        )
        store = _make_store(roots)

        overlay = build_state_overlay(store, roots)
        matching = [
            entry for entry in overlay["open_threads"]["data"]
            if entry["text"] == shared
        ]

        assert len(matching) == 1
        assert matching[0]["source"] == "last_session:sess-newer"

    def test_build_overlay_deduplicates_session_and_candidate_open_thread(self, tmp_path):
        roots = _make_roots(tmp_path)
        shared = "Implement vector decoupling for embedder"
        _write_last_session_anchor(
            roots,
            session_id="sess-newer",
            foreground=shared,
            ended_at="2026-07-06T10:00:00+00:00",
        )
        now_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        (roots.crystallized_root / "candidates.jsonl").write_text(
            json.dumps({
                "candidate_id": "cand-duplicate",
                "canonical_state": "owner_eligible",
                "summary": shared,
                "last_updated": now_ts,
            }) + "\n",
            encoding="utf-8",
        )
        store = _make_store(roots)

        overlay = build_state_overlay(store, roots)
        matching = [
            entry for entry in overlay["open_threads"]["data"]
            if entry["text"] == shared
        ]

        assert len(matching) == 1
        assert matching[0]["source_kind"] == "last_session"

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
        _write_event_stats_via_producer(roots, [
            {"id": "e1", "ts": "2026-01-01T00:00:00Z",
             "kind": "conversation_turn", "summary": "Discussed overlay design"},
            {"id": "e2", "ts": "2026-01-01T00:01:00Z",
             "kind": "fact_judge", "summary": "Judged memory candidates"},
        ])
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        assert len(overlay["recent_events"]["data"]) >= 1
        assert overlay["recent_events"]["status"] == "ok"
        # The overlay must read what the producer actually wrote.  If the
        # consumer rebuilds its own path literal again, read_event_stats
        # returns nothing here and this section falls back to empty.
        assert any(
            "Discussed overlay design" in e["text"]
            for e in overlay["recent_events"]["data"]
        )
        assert overlay["event_stats_health"]["reason"] == "produced"
        # fact_judge is not recall-meaningful — excluded, and counted rather
        # than silently dropped.
        assert overlay["event_stats_health"]["excluded_kind_counts"].get("fact_judge") == 1

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

    # ── Candidate open threads tests ──────────────────────────────────

    def test_build_overlay_with_candidates_populates_open_threads(self, tmp_path):
        """owner_eligible candidates within 7 days appear in open_threads."""
        roots = _make_roots(tmp_path)
        now_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        candidates_path = roots.crystallized_root / "candidates.jsonl"
        candidates_path.write_text(
            json.dumps({
                "candidate_id": "cand-001",
                "canonical_state": "owner_eligible",
                "summary": "Implement vector decoupling for embedder",
                "last_updated": now_ts,
            }) + "\n" +
            json.dumps({
                "candidate_id": "cand-002",
                "canonical_state": "owner_eligible",
                "summary": "Fix heartbeat count alignment issue",
                "last_updated": now_ts,
            }) + "\n",
            encoding="utf-8",
        )
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        assert len(overlay["open_threads"]["data"]) >= 1
        assert overlay["open_threads"]["status"] == "ok"
        candidate_entries = [
            e for e in overlay["open_threads"]["data"]
            if e["source_kind"] == "candidate"
        ]
        assert len(candidate_entries) >= 1
        texts = " ".join(e["text"] for e in candidate_entries)
        assert "vector decoupling" in texts or "heartbeat" in texts

    def test_candidates_outside_7_day_window_filtered_out(self, tmp_path):
        """Candidates older than 7 days must be excluded (constraint 2: safe default)."""
        roots = _make_roots(tmp_path)
        old_ts = "2026-06-01T10:00:00+00:00"  # >7 days ago
        candidates_path = roots.crystallized_root / "candidates.jsonl"
        candidates_path.write_text(
            json.dumps({
                "candidate_id": "stale-001",
                "canonical_state": "owner_eligible",
                "summary": "Stale candidate from last month",
                "last_updated": old_ts,
            }) + "\n",
            encoding="utf-8",
        )
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        candidate_entries = [
            e for e in overlay["open_threads"]["data"]
            if e["source_kind"] == "candidate"
        ]
        assert len(candidate_entries) == 0, f"Stale candidate should be excluded, got: {candidate_entries}"

    def test_candidates_non_owner_eligible_filtered_out(self, tmp_path):
        """Only canonical_state=owner_eligible candidates enter open_threads."""
        roots = _make_roots(tmp_path)
        now_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        candidates_path = roots.crystallized_root / "candidates.jsonl"
        candidates_path.write_text(
            json.dumps({
                "candidate_id": "cand-fleeting",
                "canonical_state": "fleeting",
                "summary": "Fleeting candidate should not appear",
                "last_updated": now_ts,
            }) + "\n" +
            json.dumps({
                "candidate_id": "cand-discard",
                "canonical_state": "owner_discard",
                "summary": "Discarded candidate should not appear",
                "last_updated": now_ts,
            }) + "\n",
            encoding="utf-8",
        )
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        candidate_entries = [
            e for e in overlay["open_threads"]["data"]
            if e["source_kind"] == "candidate"
        ]
        assert len(candidate_entries) == 0

    def test_candidates_file_missing_no_crash(self, tmp_path):
        """Missing candidates.jsonl must not crash build_state_overlay (fail-open)."""
        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        # No candidates.jsonl written — must not raise
        overlay = build_state_overlay(store, roots)
        assert isinstance(overlay, dict)
        assert overlay["schema_version"] == STATE_OVERLAY_SCHEMA_VERSION

    def test_candidates_merge_with_session_threads(self, tmp_path):
        """Candidates and last-session threads merge into open_threads."""
        roots = _make_roots(tmp_path)
        # Write last session anchor
        _write_last_session_anchor(roots, session_id="sess-001",
                                   foreground="Fixed anchor pollution bug",
                                   ended_at="2026-07-06T10:00:00+00:00")
        # Write candidate
        now_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        candidates_path = roots.crystallized_root / "candidates.jsonl"
        candidates_path.write_text(
            json.dumps({
                "candidate_id": "cand-001",
                "canonical_state": "owner_eligible",
                "summary": "Implement vector decoupling",
                "last_updated": now_ts,
            }) + "\n",
            encoding="utf-8",
        )
        store = _make_store(roots)
        overlay = build_state_overlay(store, roots)
        # Both sources contribute
        source_kinds = {e["source_kind"] for e in overlay["open_threads"]["data"]}
        assert "last_session" in source_kinds, "Session threads must be present"
        assert "candidate" in source_kinds, "Candidate threads must be present"

    def test_build_overlay_with_document_upload_boilerplate(self, tmp_path):
        roots = _make_roots(tmp_path)
        _write_event_stats_via_producer(roots, [
            {
                "id": "e1",
                "ts": "2026-01-01T00:00:00Z",
                "kind": "conversation_turn",
                "summary": (
                    "[The user sent a text document: 'memory-os-plan.md'. "
                    "Its content has been included below. The file is also saved at: /tmp/doc.md]"
                ),
            },
            {
                "id": "e2",
                "ts": "2026-01-01T00:01:00Z",
                "kind": "conversation_turn",
                "summary": "Useful event: overlay filter added",
            },
        ])
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

    # ── Quality JSON tests ────────────────────────────────────────────

    def test_write_state_overlay_creates_quality_json(self, tmp_path):
        """write_state_overlay must also write quality.json alongside current.json."""
        roots = _make_roots(tmp_path)
        overlay = StateOverlay.create(profile="test")
        overlay.active_projects.data.append(
            OverlayEntry(text="Active task", source="ta:1", source_kind="task_anchor"))
        overlay.active_projects.status = "ok"
        overlay.open_threads.data.append(
            OverlayEntry(text="Open thread", source="cand:1", source_kind="candidate"))
        overlay.open_threads.status = "ok"
        out_path = write_state_overlay(roots, overlay.to_dict())
        quality_path = out_path.parent / "quality.json"
        assert quality_path.exists(), f"quality.json must exist at {quality_path}"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        assert quality["schema_version"] == "memory-os.state_overlay_quality.v0"
        assert "generated_at" in quality
        assert "sections" in quality

    def test_quality_json_section_statuses(self, tmp_path):
        """quality.json sections dict reflects each overlay section status."""
        roots = _make_roots(tmp_path)
        overlay = StateOverlay.create(profile="test")
        overlay.active_projects.status = "ok"
        overlay.open_threads.status = "insufficient_data"
        out_path = write_state_overlay(roots, overlay.to_dict())
        quality_path = out_path.parent / "quality.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        assert quality["sections"]["active_projects"] == "ok"
        assert quality["sections"]["open_threads"] == "insufficient_data"

    def test_quality_json_counts_open_threads_and_recent_events(self, tmp_path):
        """quality.json records accurate entry counts."""
        roots = _make_roots(tmp_path)
        overlay = StateOverlay.create(profile="test")
        overlay.open_threads.data = [
            OverlayEntry(text="t1", source="s1", source_kind="candidate"),
            OverlayEntry(text="t2", source="s2", source_kind="last_session"),
        ]
        overlay.open_threads.status = "ok"
        overlay.recent_events.data = [
            OverlayEntry(text="e1", source="s3", source_kind="event"),
        ]
        overlay.recent_events.status = "ok"
        out_path = write_state_overlay(roots, overlay.to_dict())
        quality_path = out_path.parent / "quality.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        assert quality["open_threads_count"] == 2
        assert quality["recent_events_count"] == 1

    def test_quality_json_stale_sections(self, tmp_path):
        """stale_sections lists sections with insufficient_data status."""
        roots = _make_roots(tmp_path)
        overlay = StateOverlay.create(profile="test")
        # Most sections remain insufficient_data (default) — only one populated
        overlay.active_projects.data.append(
            OverlayEntry(text="Only active section", source="ta:1", source_kind="task_anchor"))
        overlay.active_projects.status = "ok"
        out_path = write_state_overlay(roots, overlay.to_dict())
        quality_path = out_path.parent / "quality.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        assert len(quality["stale_sections"]) >= 1
        assert "identity_snapshot" in quality["stale_sections"]

    def test_quality_json_private_body_always_false(self, tmp_path):
        """private_body_printed must never be true — overlay never prints raw event bodies."""
        roots = _make_roots(tmp_path)
        overlay = StateOverlay.create(profile="test").to_dict()
        out_path = write_state_overlay(roots, overlay)
        quality_path = out_path.parent / "quality.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        assert quality["private_body_printed"] is False

    def test_quality_json_source_refs_count(self, tmp_path):
        """source_refs_count tallies all entries with a source field."""
        roots = _make_roots(tmp_path)
        overlay = StateOverlay.create(profile="test")
        overlay.active_projects.data.append(
            OverlayEntry(text="t1", source="ta:1", source_kind="task_anchor"))
        overlay.open_threads.data.append(
            OverlayEntry(text="t2", source="cand:1", source_kind="candidate"))
        out_path = write_state_overlay(roots, overlay.to_dict())
        quality_path = out_path.parent / "quality.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        assert quality["source_refs_count"] == 2


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


# ── Registry single-source-of-truth tests ────────────────────────────
#
# These guard against the confirmed drift bug: the set of StateOverlay
# sections used to be hand-duplicated across six independent sites with no
# shared source of truth. When `community_snapshot` was removed from the
# dataclass, three of those sites were never updated and the section quietly
# vanished from `_overlay_has_data`, the refresh cron's `section_count`, and
# the retriever — for its *entire* lifetime, with no test catching it,
# because the old version of `test_state_overlay_to_dict_has_all_sections`
# (above) was itself a seventh hand-typed copy, kept in sync with `to_dict()`
# only.
#
# Every site now derives from `OVERLAY_SECTION_FIELDS`
# (state_overlay_schema.py). The tests below fail if that stops being true.


class TestOverlaySectionRegistrySingleSourceOfTruth:
    def test_renderer_labels_cover_every_derived_section(self):
        """Site 2 (state_overlay_renderer._SECTION_LABELS) must have a label
        for every section — not more, not fewer."""
        from plugins.memory.memory_os.state_overlay_renderer import _SECTION_LABELS
        assert set(_SECTION_LABELS) == set(OVERLAY_SECTION_FIELDS)

    def test_renderer_short_sections_is_valid_subset(self):
        """Site 3 (_SHORT_SECTIONS) is a deliberate subset — must not
        reference a section name that doesn't exist (typo/removed-section
        guard)."""
        from plugins.memory.memory_os.state_overlay_renderer import _SHORT_SECTIONS
        assert _SHORT_SECTIONS <= set(OVERLAY_SECTION_FIELDS)
        assert _SHORT_SECTIONS  # non-trivial subset

    def test_renderer_placeholder_sections_is_valid_subset(self):
        """The renderer's "skip insufficient_data marker" subset must not
        reference a section name that doesn't exist."""
        from plugins.memory.memory_os.state_overlay_renderer import _PLACEHOLDER_SECTIONS
        assert _PLACEHOLDER_SECTIONS <= set(OVERLAY_SECTION_FIELDS)

    def test_renderer_raises_loudly_on_unlabeled_section(self):
        """Counterfactual: if a section were added to the dataclass and left
        unlabeled, the renderer must fail loudly at (re-)validation time
        instead of silently rendering it blank. Simulates the addition via a
        synthetic extended tuple rather than mutating StateOverlay itself.
        """
        from plugins.memory.memory_os.state_overlay_renderer import (
            _assert_labels_cover_all_sections,
        )
        with pytest.raises(RuntimeError, match="community_snapshot"):
            _assert_labels_cover_all_sections(("community_snapshot", *OVERLAY_SECTION_FIELDS))
        # And the real, current section set must still validate cleanly.
        _assert_labels_cover_all_sections(OVERLAY_SECTION_FIELDS)

    def test_retriever_sections_partition_the_full_derived_set(self):
        """Site 6 (retrievers/state_overlay.py) must classify every section
        as either retrievable or explicitly not-retrievable — the union must
        equal the full derived set with no overlap."""
        from plugins.memory.memory_os.retrievers.state_overlay import (
            _RETRIEVABLE_SECTIONS,
            _NOT_RETRIEVABLE_SECTIONS,
        )
        retrievable = set(_RETRIEVABLE_SECTIONS)
        assert retrievable | _NOT_RETRIEVABLE_SECTIONS == set(OVERLAY_SECTION_FIELDS)
        assert retrievable & _NOT_RETRIEVABLE_SECTIONS == set()
        # No duplicate entries within the retrievable tuple itself.
        assert len(_RETRIEVABLE_SECTIONS) == len(retrievable)

    def test_retriever_raises_loudly_on_unclassified_section(self):
        """Counterfactual: if a section were added to the dataclass and left
        unclassified here, the retriever must fail loudly instead of
        silently omitting it from recall (exactly what happened to
        community_snapshot)."""
        from plugins.memory.memory_os.retrievers.state_overlay import (
            _assert_sections_classified,
        )
        with pytest.raises(RuntimeError, match="community_snapshot"):
            _assert_sections_classified(("community_snapshot", *OVERLAY_SECTION_FIELDS))
        _assert_sections_classified(OVERLAY_SECTION_FIELDS)

    def test_overlay_has_data_honors_whatever_section_keys_it_is_given(self):
        """Site 4 (prefetch._overlay_has_data) must have no private hardcoded
        section list of its own — its result must depend entirely on the
        section_keys argument the caller (prefetch._state_overlay_lines)
        passes in, which is OVERLAY_SECTION_FIELDS. Simulates a newly added
        section ('future_section') to prove detection isn't tied to a fixed
        list baked into this function.
        """
        from plugins.memory.memory_os.prefetch import _overlay_has_data

        overlay = {
            "identity_snapshot": {"status": "insufficient_data"},
            "future_section": {"status": "ok"},
        }
        # Without the new section wired into the passed-in key list, it's
        # invisible — this is the historical bug, reproduced deliberately.
        assert _overlay_has_data(overlay, OVERLAY_SECTION_FIELDS) is False
        # Once the (derived) key list includes it, it's detected.
        assert _overlay_has_data(overlay, (*OVERLAY_SECTION_FIELDS, "future_section")) is True

    def test_refresh_script_section_counter_uses_derived_fields(self):
        """Site 5 (scripts/memory_os_state_overlay_refresh.py) must import
        OVERLAY_SECTION_FIELDS rather than hand-maintaining its own tuple.
        Direct behavioral coverage (via subprocess + monkeypatched module)
        lives in tests/scripts/test_memory_os_state_overlay_refresh.py; this
        is a lightweight static check that the import exists and matches.
        """
        script_path = (
            Path(__file__).resolve().parents[3]
            / "scripts" / "memory_os_state_overlay_refresh.py"
        )
        source = script_path.read_text(encoding="utf-8")
        assert "OVERLAY_SECTION_FIELDS" in source
        assert (
            "from plugins.memory.memory_os.state_overlay_schema import "
            "OVERLAY_SECTION_FIELDS" in source
        )
        # And the old hand-typed tuple must be gone.
        assert '"identity_snapshot", "relationship_snapshot", "active_projects",' not in source


# ═══════════════════════════════════════════════════════════════════════════
# W7 (S1/S3) — live 锚点覆盖缓存 active_projects
# ═══════════════════════════════════════════════════════════════════════════

_LIVE_ANCHOR_B = (
    "### Memory-OS Current Task Anchor\n"
    "- current task: 任务B 正在修复图谱治理断链\n"
    "- session: 20260806_test"
)


class TestW7LiveAnchorOverride:
    def _cache_with_anchor_a(self, roots, *, task_revision: str = "42"):
        overlay = StateOverlay.create(profile="test")
        overlay.active_projects.data.append(
            OverlayEntry(text="任务A 陈旧缓存里的旧任务", source="task_anchor:current",
                         source_kind="task_anchor"))
        overlay.active_projects.status = "ok"
        payload = overlay.to_dict()
        payload["task_revision"] = task_revision
        payload["task_source_at"] = "2026-08-06T11:02:00Z"
        payload["task_record_id"] = "atr_stale"
        write_state_overlay(roots, payload)

    def test_w7_live_anchor_overrides_stale_cached_anchor(self, tmp_path):
        """S1 反事实②(关键的那条):缓存含旧锚点 A + live 锚点 B → 必须渲染 B。

        只测"缓存空+live 非空"会被"仅填空"实现蒙混——本测试钉死覆盖语义。
        无修复:快路径无条件用缓存 → 渲染 A → 必红。
        """
        from plugins.memory.memory_os.prefetch import _state_overlay_lines

        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        self._cache_with_anchor_a(roots)

        lines = _state_overlay_lines(
            store, roots=roots, current_task_anchor=_LIVE_ANCHOR_B,
        )
        joined = "\n".join(lines)
        assert "任务B" in joined, f"live anchor must override cached active: {joined}"
        assert "任务A" not in joined, f"stale cached anchor must not survive: {joined}"

    def test_w7_live_anchor_fills_empty_cached_active(self, tmp_path):
        """S1 反事实①:缓存 active 为空(cron 跑在会话开始前)+ live 非空 → 渲染含锚点。"""
        from plugins.memory.memory_os.prefetch import _state_overlay_lines

        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        overlay = StateOverlay.create(profile="test")
        overlay.open_threads.data.append(
            OverlayEntry(text="一个开放线程", source="last_session", source_kind="last_session"))
        overlay.open_threads.status = "ok"
        write_state_overlay(roots, overlay.to_dict())

        lines = _state_overlay_lines(
            store, roots=roots, current_task_anchor=_LIVE_ANCHOR_B,
        )
        joined = "\n".join(lines)
        assert "任务B" in joined, f"(insufficient data) 生产症状必须消失: {joined}"

    def test_w7_no_live_anchor_keeps_cache(self, tmp_path):
        """回归:无 live 锚点时缓存行为不变(快路径 O(1) 保持)。"""
        from plugins.memory.memory_os.prefetch import _state_overlay_lines

        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        self._cache_with_anchor_a(roots)

        lines = _state_overlay_lines(store, roots=roots)
        joined = "\n".join(lines)
        assert "任务A" in joined

    def test_s6_final_overlay_injects_fully_on_every_route(self, tmp_path):
        """S6 终局(owner 决策 2026-08-06:「状态层百分之百原样注入,S6 降为
        观察项。状态层是整个记忆系统的精髓,活起来最重要的东西」)。

        任何路由 — 包括 casual_continuity 兜底 — Overlay 全部节完整注入,
        Active 为 W7 live 覆盖后的实时锚点。本测试钉死该 owner 决策:
        未来任何人把路由抑制加回来(整段或按节)都必须先红在这里,
        经 owner 重新决策才能改。S6 泄漏点(闲聊上下文含前台任务内容)
        为已知观察项,不做代码抑制。
        """
        from plugins.memory.memory_os.prefetch import _state_overlay_lines

        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        overlay = StateOverlay.create(profile="test")
        overlay.active_projects.data.append(
            OverlayEntry(text="任务A 陈旧缓存里的旧任务", source="task_anchor:current",
                         source_kind="task_anchor"))
        overlay.active_projects.status = "ok"
        overlay.open_threads.data.append(
            OverlayEntry(text="开放线程内容", source="last_session",
                         source_kind="last_session"))
        overlay.open_threads.status = "ok"
        write_state_overlay(roots, overlay.to_dict())

        for query in ("你觉得最近怎么样", "继续修复图谱治理断链的部署", ""):
            lines = _state_overlay_lines(
                store, roots=roots, query=query,
                current_task_anchor=_LIVE_ANCHOR_B,
            )
            joined = "\n".join(lines)
            assert "任务B" in joined, (
                f"query={query!r}: live Active 必须注入(百分百原样): {joined}"
            )
            assert "开放线程内容" in joined, (
                f"query={query!r}: 其余节必须注入: {joined}"
            )

    def test_w7_retriever_override_and_revision_neutralized(self, tmp_path):
        """S3 反事实:retriever 同款覆盖,且 task_revision 错配必须中和。

        覆盖后缓存的 task_revision/task_source_at/task_record_id 是 cron 时刻
        读数,不再对应 active_projects — 不中和就是把旧修订号钉在新内容上。
        """
        from plugins.memory.memory_os.retrievers.state_overlay import StateOverlayRetriever

        roots = _make_roots(tmp_path)
        store = _make_store(roots)
        self._cache_with_anchor_a(roots, task_revision="42")

        objects = StateOverlayRetriever().retrieve(
            store, "任务", scope={"current_task_anchor": _LIVE_ANCHOR_B},
        )
        active = [o for o in objects if o.metadata.get("section") == "active_projects"]
        assert active, f"active_projects object must exist: {objects}"
        assert "任务B" in active[0].content
        assert all("任务A" not in o.content for o in active)
        assert active[0].source_ref == "task_anchor:live"
        assert active[0].task_revision == "", (
            "stale cache task_revision must be neutralized on live override"
        )
