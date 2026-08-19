"""Guards for the event_stats path drift and the unbounded anchor read (DB).

Two defects landed together because fixing either alone was wrong:

* ``event_stats.json`` was written by the producer under ``runtime/`` and read
  by three consumers under ``system/``.  ``exists()`` was therefore False on
  every run the deployment ever had, with no error record and no counter —
  the source contributed nothing, silently, for its whole life.
* ``last_session_anchor.jsonl`` was read in full by three readers, two of them
  on the per-turn hot path, while growing without bound.

The path fix alone would have been a regression: the raw tail the consumers
read is machine bookkeeping on production, so connecting it without a kind
filter injects cron-mirror and governance rows into owner-facing context.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from plugins.memory.memory_os.continuity_constants import (
    _BOOKKEEPING_FILL_KIND_MARKERS,
)
from plugins.memory.memory_os.event_stats import (
    RECALL_MEANINGFUL_EVENT_KINDS,
    RECALL_SUMMARY_LIMIT,
    build_event_stats,
    event_stats_path,
    read_event_stats,
    write_event_stats,
)
from plugins.memory.memory_os.jsonl_io import (
    COMPACT_JSONL_TAIL_REASONS,
    compact_jsonl_tail,
    read_jsonl,
    read_jsonl_tail,
)
from plugins.memory.memory_os.roots import (
    LAST_SESSION_ANCHOR_KEEP_RECORDS,
    LAST_SESSION_ANCHOR_TAIL_RECORDS,
    MemoryOSRoots,
    last_session_anchor_path,
)
from plugins.memory.memory_os.store import MemoryOSStore

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_roots(tmp_path: Path) -> MemoryOSRoots:
    home = tmp_path / ".hermes"
    (home / "memory-os" / "crystallized").mkdir(parents=True)
    (home / "memory-os" / "system").mkdir(parents=True)
    return MemoryOSRoots.from_hermes_home(str(home), profile="test")


def _source_files() -> list[Path]:
    files: list[Path] = []
    for base in ("plugins", "scripts"):
        for path in (REPO_ROOT / base).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


# ── 1. Path drift guards ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "filename, owner_rel_path",
    [
        ("event_stats.json", "plugins/memory/memory_os/event_stats.py"),
        ("last_session_anchor.jsonl", "plugins/memory/memory_os/roots.py"),
    ],
)
def test_ledger_filename_literal_appears_only_in_its_owning_module(
    filename: str, owner_rel_path: str
) -> None:
    """A bare quoted filename may appear only where its accessor lives.

    This is the guard the drift needed and did not have.  It targets the
    *quoted* token — the form a path join uses — so prose mentions in
    docstrings and human-readable source labels stay legal while a second
    hand-built path becomes a test failure.

    Deliberately blunt in the same way as the exposure firewall test: if a
    legitimate change trips it, the fix is to route through the accessor,
    never to relax the pattern.
    """
    pattern = re.compile(rf"""['"]{re.escape(filename)}['"]""")
    offenders = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in _source_files()
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    )
    assert offenders == [owner_rel_path], (
        f"{filename} must be addressed through its accessor in {owner_rel_path}; "
        f"path literals found in: {offenders}"
    )


# Basenames that legitimately exist under several directories: each module
# owns its own copy, so two directories means two different files, not drift.
# Anything NOT listed here must resolve to exactly one directory across the
# whole source tree.
_PER_MODULE_BASENAMES = frozenset({
    "config.json",            # memory-os/, hindsight/, deep_reflection/, ragflow
    "current.json",           # state_overlay/, injection/, working/
    "policy.json",            # one per module that has a policy
    "policy_applies.jsonl",   # ditto
    "reports.jsonl",          # one per module (ops_gate, left_brain_advisor, …)
    "runs.jsonl",             # ditto
    "would_send.jsonl",       # mailbox/ and speak_gate/ are distinct lanes
})

_PATH_JOIN_RE = re.compile(
    r'"([a-z0-9_\-]+)"\s*/\s*"([a-zA-Z0-9_\-.]+\.(?:jsonl|json|db|md))"'
)


def test_no_data_file_is_addressed_under_two_directories() -> None:
    """The whole defect family, as one assertion.

    A producer writing ``runtime/x.json`` while a consumer reads
    ``system/x.json`` never raises: ``exists()`` simply returns False forever,
    so the source contributes nothing and no error record is emitted.  The
    project-wide sweep this test encodes found four instances, every one of
    them confirmed against the production host:

    * ``event_stats.json`` — producer runtime/, three consumers system/;
      system/ has never existed on either profile or in any backup.
    * ``session_mirror_state.json`` — producer runtime/, capability probe
      system/; the capability reported absent on every host, forever.
    * ``write_audit.jsonl`` — canonical audit/, one module system/; because
      append_audit shards monthly off the parent, that built a whole parallel
      audit trail (22 KB and still being written) that no reader globs.
    * ``candidates.jsonl`` — canonical crystallized/, one probe candidates/.

    If a new basename legitimately belongs to several modules, add it to
    _PER_MODULE_BASENAMES with a note saying why — do not widen the pattern.
    """
    by_name: dict[str, set[str]] = {}
    locations: dict[str, set[str]] = {}
    for path in _source_files():
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            for directory, filename in _PATH_JOIN_RE.findall(line):
                if filename in _PER_MODULE_BASENAMES:
                    continue
                by_name.setdefault(filename, set()).add(directory)
                locations.setdefault(filename, set()).add(f"{rel}:{lineno}")

    drifted = {
        name: (sorted(dirs), sorted(locations[name]))
        for name, dirs in by_name.items()
        if len(dirs) > 1
    }
    assert not drifted, (
        "data file(s) addressed under more than one directory — a producer and "
        f"its consumer have drifted apart silently: {drifted}"
    )


def test_producer_and_consumers_resolve_the_same_event_stats_file(tmp_path) -> None:
    """The bug, stated as an assertion: writer and readers must agree.

    Written through the real producer and read back through the real reader,
    so a fixture cannot agree with a wrong path the way the overlay fixtures
    used to.
    """
    roots = _make_roots(tmp_path)
    write_event_stats(roots, build_event_stats([
        {"id": "e1", "ts": "2026-01-01T00:00:00Z",
         "kind": "conversation_turn", "summary": "hello"},
    ]))
    assert event_stats_path(roots).exists()
    stats, freshness = read_event_stats(roots)
    assert stats is not None and freshness != "missing"
    # And nothing was left in the directory the consumers used to read.
    assert not (roots.memory_os_root / "system" / "event_stats.json").exists()


def test_read_event_stats_reports_missing_rather_than_returning_empty(tmp_path) -> None:
    """An absent cache must be distinguishable from an empty one.

    The original consumers used a bare ``if path.exists():`` with no else, so
    "file is in another directory" and "no summaries this run" produced
    byte-identical evidence: nothing at all.
    """
    roots = _make_roots(tmp_path)
    stats, freshness = read_event_stats(roots)
    assert stats is None
    assert freshness == "missing"


# ── 2. Kind filter (fail-closed) ─────────────────────────────────────


def _production_shaped_events() -> list[dict[str, object]]:
    """Events shaped like the production tail that motivated the filter."""
    return [
        {"id": "u1", "ts": "2026-01-01T00:00:00Z",
         "kind": "conversation_turn", "summary": "owner asked about the cron list"},
        {"id": "m1", "ts": "2026-01-01T00:01:00Z", "kind": "conversation_turn_mirrored",
         "summary": "Session cron_af9f_20260718 on cron mirrored; last_user=..."},
        {"id": "g1", "ts": "2026-01-01T00:02:00Z", "kind": "governance_resolver_approved",
         "summary": "Resolver approved crystallized record cand_l3_2026"},
        {"id": "g2", "ts": "2026-01-01T00:03:00Z", "kind": "governance_resolver_invalidated",
         "summary": "Resolver invalidated provisional record"},
        {"id": "s1", "ts": "2026-01-01T00:04:00Z", "kind": "session_observed",
         "summary": "Session 20260713 on cli observed with 0 messages"},
        {"id": "f1", "ts": "2026-01-01T00:05:00Z", "kind": "session_fact_extracted",
         "summary": "Durable facts extracted from session 20260525 (telegram)."},
    ]


def test_recall_summaries_exclude_machine_kinds_that_the_raw_tail_keeps() -> None:
    """The counterfactual for shipping the path fix on its own.

    The last five events here are all machine bookkeeping, exactly as measured
    on both production profiles.  ``recent_event_summaries`` keeps them —
    that field is the honest raw tail and must not change.  The recall field
    must keep none of them.
    """
    stats = build_event_stats(_production_shaped_events())

    raw_kinds = [s["kind"] for s in stats.recent_event_summaries]
    assert "conversation_turn_mirrored" in raw_kinds
    assert any(k.startswith("governance_") for k in raw_kinds)

    recall_kinds = [s["kind"] for s in stats.recall_event_summaries]
    assert recall_kinds == ["conversation_turn"]
    assert all(k in RECALL_MEANINGFUL_EVENT_KINDS for k in recall_kinds)


def test_unclassified_kind_is_excluded_and_counted_not_silently_dropped() -> None:
    """Fail-closed, but never silent.

    A kind nobody has classified must not reach owner-facing recall, and the
    exclusion must be visible — otherwise the filter becomes the next silent
    blindness rather than the cure for one.
    """
    stats = build_event_stats([
        {"id": "x1", "ts": "2026-01-01T00:00:00Z",
         "kind": "some_future_machine_kind", "summary": "emitted by a lane written next year"},
    ])
    assert stats.recall_event_summaries == []
    assert stats.recall_summary_excluded_kind_counts == {"some_future_machine_kind": 1}
    assert stats.recall_summary_scanned_count == 1


def test_recall_allowlist_never_contradicts_the_bookkeeping_markers() -> None:
    """Bind the two vocabularies so they cannot drift into contradiction.

    ``_BOOKKEEPING_FILL_KIND_MARKERS`` is fail-open (it governs a display);
    this allowlist is fail-closed (it governs injection).  Opposite polarity
    is deliberate, but a kind that is recall-meaningful here while being
    bookkeeping there would be a genuine contradiction.
    """
    for kind in RECALL_MEANINGFUL_EVENT_KINDS:
        lowered = kind.lower()
        assert not any(
            lowered == marker or lowered.startswith(marker)
            for marker in _BOOKKEEPING_FILL_KIND_MARKERS
        ), f"{kind} is allowlisted for recall but classified as bookkeeping"


def test_empty_summary_on_an_allowlisted_kind_is_counted_separately() -> None:
    """A blank summary is not recall content, and says so in its own bucket."""
    stats = build_event_stats([
        {"id": "e1", "ts": "2026-01-01T00:00:00Z", "kind": "conversation_turn", "summary": "   "},
    ])
    assert stats.recall_event_summaries == []
    assert stats.recall_summary_excluded_kind_counts == {"conversation_turn:empty_summary": 1}


def test_recall_summaries_are_bounded_and_oldest_first() -> None:
    events = [
        {"id": f"e{i}", "ts": f"2026-01-01T00:{i:02d}:00Z",
         "kind": "conversation_turn", "summary": f"turn {i}"}
        for i in range(20)
    ]
    stats = build_event_stats(events)
    assert len(stats.recall_event_summaries) == RECALL_SUMMARY_LIMIT
    assert [s["summary"] for s in stats.recall_event_summaries] == [
        "turn 15", "turn 16", "turn 17", "turn 18", "turn 19",
    ]


def test_recall_summaries_survive_the_write_read_roundtrip(tmp_path) -> None:
    roots = _make_roots(tmp_path)
    write_event_stats(roots, build_event_stats(_production_shaped_events()))
    read_back, _freshness = read_event_stats(roots)
    assert read_back is not None
    assert [s["kind"] for s in read_back.recall_event_summaries] == ["conversation_turn"]
    assert read_back.recall_summary_excluded_kind_counts["conversation_turn_mirrored"] == 1
    assert read_back.recall_summary_scanned_count == 6


def test_legacy_cache_without_the_recall_field_reads_as_empty(tmp_path) -> None:
    """A cache written before this field existed must not crash or guess."""
    roots = _make_roots(tmp_path)
    path = event_stats_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "updated_at": "2026-01-01T00:00:00+00:00",
        "total_event_count": 7,
        "recent_event_summaries": [{"kind": "conversation_turn", "summary": "old"}],
    }), encoding="utf-8")
    stats, _freshness = read_event_stats(roots)
    assert stats is not None
    assert stats.recall_event_summaries == []
    assert stats.recall_summary_scanned_count == 0


# ── 3. Bounded tail reads ────────────────────────────────────────────


def _write_anchor_ledger(path: Path, count: int, *, pad: int = 700) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(count):
        lines.append(json.dumps({
            "session_id": f"session-{i:05d}",
            "ended_at": f"2026-01-01T{i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}+00:00",
            "foreground_summary": f"summary {i} " + ("x" * pad),
            "schema_version": "memory-os.last_session_anchor.v0",
        }, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture()
def forbid_whole_file_anchor_read(monkeypatch):
    """Fail loudly if anything reads the whole anchor ledger.

    This is the counterfactual for the tail-read fix: every reader used
    ``read_text().splitlines()``, so without the fix each of these tests
    trips this guard instead of passing.
    """
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes

    def _guard(name):
        def _inner(self, *args, **kwargs):
            if self.name == "last_session_anchor.jsonl":
                raise AssertionError(
                    f"whole-file {name} on the append-only anchor ledger — "
                    "readers must use read_jsonl_tail"
                )
            return (original_read_text if name == "read_text" else original_read_bytes)(
                self, *args, **kwargs
            )
        return _inner

    monkeypatch.setattr(Path, "read_text", _guard("read_text"))
    monkeypatch.setattr(Path, "read_bytes", _guard("read_bytes"))
    return None


def test_read_jsonl_tail_matches_read_jsonl_without_reading_everything(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"
    records = [{"i": i, "pad": "y" * 900} for i in range(1500)]
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    assert path.stat().st_size > 1_000_000
    tail = read_jsonl_tail(path, max_records=3)
    assert [r["i"] for r in tail.records] == [r["i"] for r in read_jsonl(path)[-3:]]
    assert tail.error_records == []


def test_read_jsonl_tail_reports_a_truncated_scan_instead_of_a_short_result(tmp_path) -> None:
    """A scan that hit its byte cap must say so, not look like a small file."""
    path = tmp_path / "ledger.jsonl"
    records = [{"i": i, "pad": "y" * 900} for i in range(1500)]
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    result = read_jsonl_tail(path, max_records=900, max_bytes=4096)
    assert len(result.records) < 900
    assert "jsonl_tail_scan_truncated" in result.recent_error_codes


def test_prefetch_last_session_lines_reads_only_the_tail(
    tmp_path, forbid_whole_file_anchor_read
) -> None:
    from plugins.memory.memory_os.prefetch import _last_session_lines

    roots = _make_roots(tmp_path)
    store = MemoryOSStore(roots)
    _write_anchor_ledger(last_session_anchor_path(roots), 400)
    lines = _last_session_lines(store, session_id="current-session")
    assert len(lines) == 1
    assert "summary 399" in lines[0]


def test_temporal_retriever_reads_only_the_tail(
    tmp_path, forbid_whole_file_anchor_read
) -> None:
    from plugins.memory.memory_os.retrievers.temporal import TemporalRetriever

    roots = _make_roots(tmp_path)
    store = MemoryOSStore(roots)
    _write_anchor_ledger(last_session_anchor_path(roots), 400)
    objects = TemporalRetriever().retrieve(
        store, "上次我们聊到哪了", scope={"session_id": "current-session"}
    )
    anchors = [o for o in objects if o.metadata.get("anchor") == "last_session"]
    assert len(anchors) == 3
    assert "summary 399" in anchors[0].content


def test_state_overlay_anchor_read_is_bounded(
    tmp_path, forbid_whole_file_anchor_read
) -> None:
    from plugins.memory.memory_os.state_overlay import _read_last_session_anchors

    roots = _make_roots(tmp_path)
    path = last_session_anchor_path(roots)
    _write_anchor_ledger(path, 400)
    records = _read_last_session_anchors(path, limit=3)
    assert [r["session_id"] for r in records] == [
        "session-00399", "session-00398", "session-00397",
    ]


def test_tail_window_is_wide_enough_for_every_hot_path_reader() -> None:
    """The window must exceed what any hot-path reader asks for.

    prefetch needs one anchor and temporal needs three; a window narrowed to
    those numbers would silently drop the newest anchor whenever a single
    same-session or summary-less record sat at the tail.
    """
    assert LAST_SESSION_ANCHOR_TAIL_RECORDS >= 10


# ── 4. Size-gated compaction ─────────────────────────────────────────


def test_compaction_is_a_no_op_below_the_size_gate(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"
    _write_anchor_ledger(path, 20)
    before = path.read_bytes()
    result = compact_jsonl_tail(path, keep_records=5, min_bytes=10_000_000)
    assert result["reason"] == "below_threshold"
    assert path.read_bytes() == before


def test_compaction_archives_every_dropped_record_before_dropping_it(tmp_path) -> None:
    """Bounding a ledger must never lose a record."""
    path = tmp_path / "ledger.jsonl"
    archive = tmp_path / "ledger.archive.jsonl"
    _write_anchor_ledger(path, 300)
    result = compact_jsonl_tail(
        path, keep_records=50, min_bytes=1, archive_path=archive
    )
    assert result["reason"] == "compacted"
    assert result["records_kept"] == 50
    assert result["records_archived"] == 250

    kept = read_jsonl(path)
    archived = read_jsonl(archive)
    assert len(kept) == 50
    assert len(archived) == 250
    # Union of kept + archived is exactly the original ledger, in order.
    recovered = [r["session_id"] for r in archived] + [r["session_id"] for r in kept]
    assert recovered == [f"session-{i:05d}" for i in range(300)]


def test_compaction_distinguishes_its_no_op_outcomes(tmp_path) -> None:
    """Closed reason set: an idle compaction and a missing file differ."""
    missing = compact_jsonl_tail(tmp_path / "nope.jsonl", keep_records=5, min_bytes=1)
    assert missing["reason"] == "no_file"

    path = tmp_path / "ledger.jsonl"
    _write_anchor_ledger(path, 3)
    nothing = compact_jsonl_tail(path, keep_records=500, min_bytes=1)
    assert nothing["reason"] == "nothing_to_drop"

    for reason in (missing["reason"], nothing["reason"]):
        assert reason in COMPACT_JSONL_TAIL_REASONS


def test_compaction_refuses_to_rewrite_a_ledger_with_malformed_lines(tmp_path) -> None:
    """Compaction rewrites only what parsed — so it must not run on garbage.

    Without this refusal a single corrupt line turns a bounding operation
    into silent deletion of the one record nobody can reconstruct.
    """
    path = tmp_path / "ledger.jsonl"
    _write_anchor_ledger(path, 30)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not valid json\n")
    before = path.read_bytes()

    result = compact_jsonl_tail(path, keep_records=5, min_bytes=1)

    assert result["reason"] == "malformed_lines_present"
    assert result["reason"] in COMPACT_JSONL_TAIL_REASONS
    assert path.read_bytes() == before, "a refused compaction must not touch the file"
    assert result["error_records"], "the malformed line must be reported, not ignored"


def test_overlay_event_stats_health_reasons_are_a_pinned_closed_set(tmp_path) -> None:
    """Every reason the overlay can emit must be in the declared set.

    Derived from the source rather than hand-listed, so adding a branch that
    invents a new reason fails here instead of shipping an unlisted value.
    """
    import re as _re
    from plugins.memory.memory_os import state_overlay as _so

    source = Path(_so.__file__).read_text(encoding="utf-8")
    body = source.split("def build_state_overlay", 1)[1].split("\ndef ", 1)[0]
    emitted = set(
        _re.findall(r'event_stats_health\["reason"\]\s*=\s*\(?\s*\n?\s*"([a-z_]+)"', body)
    )
    emitted |= set(_re.findall(r'else\s+"([a-z_]+)"\s*\n?\s*\)', body))
    assert emitted, "reason assignments must be discoverable in the builder"
    unlisted = emitted - _so.EVENT_STATS_HEALTH_REASONS
    assert not unlisted, f"reason(s) emitted but not declared: {sorted(unlisted)}"

    # And the missing-cache branch really produces a declared value.
    roots = _make_roots(tmp_path)
    store = MemoryOSStore(roots)
    overlay = _so.build_state_overlay(store, roots)
    assert overlay["event_stats_health"]["reason"] == "cache_missing"
    assert (
        overlay["event_stats_health"]["reason"] in _so.EVENT_STATS_HEALTH_REASONS
    )


def test_compaction_keeps_more_records_than_the_widest_reader_window() -> None:
    """Compaction may bound what nobody reads — never what a reader reads."""
    from plugins.memory.memory_os.state_overlay import _read_last_session_anchors
    import inspect

    overlay_max_lines = inspect.signature(
        _read_last_session_anchors
    ).parameters["max_lines"].default
    assert LAST_SESSION_ANCHOR_KEEP_RECORDS >= overlay_max_lines
    assert LAST_SESSION_ANCHOR_KEEP_RECORDS >= LAST_SESSION_ANCHOR_TAIL_RECORDS
