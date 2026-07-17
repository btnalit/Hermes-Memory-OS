from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.candidate_clusters import candidate_cluster_report
from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    append_candidate_queue,
    read_candidate_queue,
)
from plugins.memory.memory_os.owner_actions import owner_review_queue_report
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _roots(tmp_path, *, profile: str = "default") -> MemoryOSRoots:
    return MemoryOSRoots.from_hermes_home(tmp_path / ".hermes", profile=profile)


def _store(tmp_path, *, profile: str = "default") -> MemoryOSStore:
    store = MemoryOSStore(_roots(tmp_path, profile=profile))
    store.initialize()
    return store


def _write_task_rows(roots: MemoryOSRoots, rows: list[object]) -> None:
    path = roots.memory_os_root / "system" / "active_task_anchor.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            row if isinstance(row, str) else json.dumps(row, ensure_ascii=False)
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )


def _task(*, status: str, profile: str = "default", anchor: str = "Ship Phase 0", created_at: str = "2026-07-15T00:00:00Z") -> dict:
    return {
        "record_id": "task-1",
        "status": status,
        "profile": profile,
        "anchor": anchor,
        "created_at": created_at,
        "session_id": "sess-old",
    }


def _candidate(
    candidate_id: str,
    body: str,
    *,
    bridge_state: str = "candidate",
    sensitivity: str = "private",
) -> CrystallizedCandidate:
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="fact",
        body=body,
        source_event_ids=[candidate_id.removeprefix("cand-")],
        sensitivity=sensitivity,
        tags=[],
        bridge_state=bridge_state,
        created_at="2026-07-15T00:00:00Z",
    )


def _write_triage(store: MemoryOSStore, candidate_id: str, target_state: str) -> None:
    path = store.roots.memory_os_root / "crystallized" / "candidate_triage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema_version": "memory-os.candidate_triage.v0",
        "candidate_id": candidate_id,
        "action": "fixture",
        "target_state": target_state,
        "reason": "terminal fixture",
        "created_at": "2026-07-15T00:01:00Z",
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_effective_task_latest_active_record_exposes_revision_and_watermarks(tmp_path):
    from plugins.memory.memory_os.task_state import read_effective_current_task

    roots = _roots(tmp_path)
    _write_task_rows(roots, [_task(status="active")])
    result = read_effective_current_task(
        roots,
        profile="default",
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert result is not None
    assert result["anchor"] == "Ship Phase 0"
    assert result["status"] == "active"
    assert result["revision"] == 1
    assert result["source_at"] == "2026-07-15T00:00:00Z"
    assert result["observed_at"] == "2026-07-15T01:00:00Z"


@pytest.mark.parametrize("terminal", ["completed", "cancelled", "superseded", "unsupported"])
def test_effective_task_latest_terminal_or_unknown_record_fails_closed(tmp_path, terminal):
    from plugins.memory.memory_os.task_state import read_effective_current_task

    roots = _roots(tmp_path)
    _write_task_rows(roots, [_task(status="active"), _task(status=terminal)])

    assert read_effective_current_task(roots, profile="default") is None


def test_effective_task_skips_malformed_rows_and_isolates_profiles_without_writes(tmp_path):
    from plugins.memory.memory_os.task_state import read_effective_current_task

    roots = _roots(tmp_path)
    _write_task_rows(
        roots,
        [
            _task(status="active", profile="default"),
            "{broken-json",
            _task(status="completed", profile="other"),
        ],
    )
    path = roots.memory_os_root / "system" / "active_task_anchor.jsonl"
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    result = read_effective_current_task(roots, profile="default")

    assert result is not None
    assert result["anchor"] == "Ship Phase 0"
    assert result["revision"] == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_effective_task_fails_closed_on_malformed_tail_after_last_valid_record(tmp_path):
    """Counterfactual for FIX 1: a malformed non-empty line AFTER the last
    valid record must fail closed (return None), not resurrect the earlier
    active row. This guards against a crashed/partial write of a
    terminal (completed/cancelled/superseded) tombstone silently vanishing
    and leaving a stale `active` row authoritative."""
    from plugins.memory.memory_os.task_state import read_effective_current_task

    roots = _roots(tmp_path)
    _write_task_rows(
        roots,
        [
            _task(status="active", profile="default"),
            "{this-line-is-corrupted-and-comes-after-the-last-valid-record",
        ],
    )

    assert read_effective_current_task(roots, profile="default") is None


def test_effective_task_malformed_line_before_last_valid_record_still_resolves(tmp_path):
    """Regression guard: a malformed line BEFORE the last valid record must
    keep the pre-existing skip-and-continue behavior (only trailing
    corruption fails closed)."""
    from plugins.memory.memory_os.task_state import read_effective_current_task

    roots = _roots(tmp_path)
    _write_task_rows(
        roots,
        [
            "{this-line-is-corrupted-but-comes-before-the-last-valid-record",
            _task(status="active", profile="default"),
        ],
    )

    result = read_effective_current_task(roots, profile="default")
    assert result is not None
    assert result["anchor"] == "Ship Phase 0"


def test_effective_task_age_gate_fails_closed(tmp_path):
    from plugins.memory.memory_os.task_state import read_effective_current_task

    roots = _roots(tmp_path)
    _write_task_rows(roots, [_task(status="active", created_at="2026-07-14T00:00:00Z")])

    assert read_effective_current_task(
        roots,
        profile="default",
        max_age_hours=12,
        now=datetime(2026, 7, 15, 0, tzinfo=timezone.utc),
    ) is None


def test_effective_candidates_keep_raw_audit_but_exclude_terminal_and_non_owner_items(tmp_path):
    from plugins.memory.memory_os.crystallized import read_effective_candidates

    store = _store(tmp_path)
    owner = _candidate("cand-owner", "Keep the production release boundary intact", bridge_state="owner_eligible")
    terminal = _candidate("cand-terminal", "Keep production release boundary safely", bridge_state="owner_eligible")
    pending = _candidate("cand-pending", "Raw pending observation", bridge_state="candidate")
    for item in (owner, terminal, pending):
        append_candidate_queue(store, item)
    _write_triage(store, terminal.candidate_id, "demoted")

    raw = read_candidate_queue(store)
    effective = read_effective_candidates(store)
    by_id = {item.candidate.candidate_id: item for item in effective}

    assert {item.candidate_id for item in raw} == {"cand-owner", "cand-terminal", "cand-pending"}
    assert by_id["cand-owner"].owner_review_eligible is True
    assert by_id["cand-owner"].terminal is False
    assert by_id["cand-terminal"].effective_state == "demoted"
    assert by_id["cand-terminal"].terminal is True
    assert by_id["cand-terminal"].exclusion_reason == "terminal_state"
    assert by_id["cand-pending"].owner_review_eligible is False
    assert by_id["cand-pending"].exclusion_reason == "not_owner_eligible"


def test_effective_candidates_latest_queue_row_wins_for_duplicate_candidate_id(tmp_path):
    from plugins.memory.memory_os.crystallized import read_effective_candidates

    store = _store(tmp_path)
    path = store.roots.crystallized_root / "candidates.jsonl"
    old = _candidate("cand-dup", "old revision", bridge_state="owner_eligible")
    new = _candidate("cand-dup", "new revision", bridge_state="owner_eligible")
    rows = [
        {
            "candidate_id": item.candidate_id,
            "kind": item.kind,
            "body": item.body,
            "source_event_ids": item.source_event_ids,
            "sensitivity": item.sensitivity,
            "tags": item.tags,
            "bridge_state": item.bridge_state,
            "created_at": item.created_at,
        }
        for item in (old, new)
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    raw = read_candidate_queue(store)
    effective = read_effective_candidates(store)

    assert [item.body for item in raw] == ["old revision", "new revision"]
    assert len(effective) == 1
    assert effective[0].candidate.body == "new revision"


def test_owner_action_lookup_uses_same_latest_candidate_revision_as_review_projection(tmp_path):
    from plugins.memory.memory_os.crystallized import read_effective_candidates
    from plugins.memory.memory_os.owner_actions import _find_candidate

    store = _store(tmp_path)
    path = store.roots.crystallized_root / "candidates.jsonl"
    rows = [
        {
            "candidate_id": "cand-action",
            "kind": "fact",
            "body": body,
            "source_event_ids": ["evt-1"],
            "sensitivity": "low",
            "tags": [],
            "bridge_state": "owner_eligible",
            "created_at": "2026-07-16T00:00:00Z",
        }
        for body in ("OLD WRONG", "NEW REVIEWED")
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    assert read_effective_candidates(store)[0].candidate.body == "NEW REVIEWED"
    found = _find_candidate(store, "cand-action")
    assert found is not None
    assert found.body == "NEW REVIEWED"


def test_actionable_cluster_collapses_member_cards_and_mixed_sensitivity_preserves_individuals(tmp_path):
    store = _store(tmp_path)
    for candidate in (
        _candidate("cand-a", "Keep the production release boundary intact", bridge_state="owner_eligible"),
        _candidate("cand-b", "Keep production release boundary intact", bridge_state="owner_eligible"),
    ):
        append_candidate_queue(store, candidate)

    queue = owner_review_queue_report(store, limit=100)
    review_items = [
        item for item in queue["items"]
        if item.get("target_type") in {"candidate", "candidate_cluster"}
    ]
    assert [item["target_type"] for item in review_items] == ["candidate_cluster"]

    mixed_store = _store(tmp_path / "mixed")
    for candidate in (
        _candidate("cand-c", "Keep the production release boundary intact", bridge_state="owner_eligible", sensitivity="private"),
        _candidate("cand-d", "Keep production release boundary intact", bridge_state="owner_eligible", sensitivity="public"),
    ):
        append_candidate_queue(mixed_store, candidate)

    mixed_queue = owner_review_queue_report(mixed_store, limit=100)
    mixed_items = [
        item for item in mixed_queue["items"]
        if item.get("target_type") in {"candidate", "candidate_cluster"}
    ]
    assert all(item["target_type"] == "candidate" for item in mixed_items)
    assert {item["target_id"] for item in mixed_items} == {"cand-c", "cand-d"}


def test_terminal_or_non_owner_candidates_do_not_reenter_single_or_cluster_review(tmp_path):
    store = _store(tmp_path)
    owner = _candidate("cand-owner", "Keep the production release boundary intact", bridge_state="owner_eligible")
    terminal = _candidate("cand-terminal", "Keep production release boundary safely", bridge_state="owner_eligible")
    pending = _candidate("cand-pending", "Keep production release boundaries", bridge_state="candidate")
    for item in (owner, terminal, pending):
        append_candidate_queue(store, item)
    _write_triage(store, terminal.candidate_id, "demoted")

    clusters = candidate_cluster_report(store)
    queue = owner_review_queue_report(store, limit=100)
    candidate_items = [
        item for item in queue["items"]
        if item.get("target_type") in {"candidate", "candidate_cluster"}
    ]

    assert clusters["candidate_count"] == 1
    assert clusters["cluster_count"] == 1
    assert all(item.get("target_type") != "candidate_cluster" for item in candidate_items)
    assert [item["target_id"] for item in candidate_items] == ["cand-owner"]
