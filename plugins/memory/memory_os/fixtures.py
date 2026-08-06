"""Deterministic fixture builders for Memory-OS tests."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .ids import new_crystallized_id, new_event_id, new_working_id
from .roots import MemoryOSRoots
from .schema import (
    CRYSTALLIZED_SCHEMA_VERSION,
    EVENT_SCHEMA_VERSION,
    WorkingItem,
)


_BASE_TIME = datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SannaiFixtureLayout:
    profile: str
    hermes_home: Path
    state_root: Path
    roots: MemoryOSRoots


def _timestamp(seed: int) -> datetime:
    return _BASE_TIME + timedelta(seconds=seed)


def _iso(seed: int) -> str:
    return _timestamp(seed).isoformat()


def _suffix(seed: int) -> str:
    return f"{seed:010x}"[-10:]


def build_event(*, seed: int, profile: str = "memoryos-test") -> dict[str, object]:
    """Build a schema-valid synthetic event envelope."""

    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "id": new_event_id(_timestamp(seed), unique=_suffix(seed)),
        "ts": _iso(seed),
        "profile": profile,
        "source": "fixture",
        "kind": "synthetic_event",
        "summary": f"Synthetic memory event {seed} for {profile}",
        "safe_ref": {"fixture_seed": seed},
        "tags": ["synthetic", profile],
        "sensitivity": "private",
        "body_policy": "summary_only",
        "hashes": {},
        "promotion_state": "raw",
    }


def build_working_item(
    *,
    seed: int,
    source_event_id: str = "",
    kind: str = "lingering",
) -> WorkingItem:
    """Build a deterministic working-memory item."""

    created_at = _iso(seed)
    return WorkingItem(
        id=new_working_id(_timestamp(seed), unique=_suffix(seed)),
        kind=kind,
        status="active",
        created_at=created_at,
        updated_at=created_at,
        text=f"Synthetic working item {seed}",
        source_event_id=source_event_id,
        tags=["synthetic", kind],
        weight=0.5,
    )


def build_crystallized_frontmatter(
    *,
    seed: int,
    source_event_ids: list[str] | None = None,
    kind: str = "moment",
) -> dict[str, object]:
    """Build deterministic crystallized-memory frontmatter.

    Returns a plain dict — the same shape production crystallized paths use
    (the CrystallizedFrontmatter dataclass was fixture-only and is gone).
    """

    created_at = _iso(seed)
    return {
        "schema_version": CRYSTALLIZED_SCHEMA_VERSION,
        "id": new_crystallized_id(_timestamp(seed), unique=_suffix(seed)),
        "kind": kind,
        "created_at": created_at,
        "approved_by": "owner",
        "approved_at": created_at,
        "source_event_ids": list(source_event_ids or []),
        "tags": ["synthetic", kind],
        "sensitivity": "private",
        "hindsight_indexed": False,
    }


def build_sannai_multi_root_fixture(base_path: str | Path) -> SannaiFixtureLayout:
    """Create a synthetic Sannai-like profile root plus separate state root."""

    base = Path(base_path)
    hermes_home = base / "root" / ".hermes" / "profiles" / "sannai"
    state_root = base / "vol1" / ".hermes" / "state" / "sannai"
    memories_root = hermes_home / "memories"
    memories_root.mkdir(parents=True, exist_ok=True)
    state_root.mkdir(parents=True, exist_ok=True)

    (hermes_home / "SOUL.md").write_text("Synthetic Sannai soul\n", encoding="utf-8")
    (memories_root / "MEMORY.md").write_text("Synthetic Sannai memory\n", encoding="utf-8")
    (memories_root / "USER.md").write_text("Synthetic owner memory\n", encoding="utf-8")
    (state_root / "diary.md").write_text("Synthetic diary\n", encoding="utf-8")
    (state_root / "self_memory.md").write_text("Synthetic self memory\n", encoding="utf-8")
    (state_root / "lingering_thoughts.json").write_text(
        json.dumps(
            [
                {
                    "id": "lingering-1",
                    "text": "Synthetic lingering thought",
                    "intensity": 0.6,
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (state_root / "quiet_moments.jsonl").write_text(
        json.dumps({"id": "quiet-1", "summary": "Synthetic quiet moment"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (state_root / "heartbeat_lingering_candidates.jsonl").write_text(
        "\n".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True)
            for record in (
                {"id": "cand-1", "status": "candidate", "text": "Synthetic pending candidate"},
                {"id": "cand-2", "status": "owner_eligible", "text": "Synthetic eligible candidate"},
                {"id": "cand-3", "status": "owner_defer", "text": "Synthetic deferred candidate"},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    daily_digest = state_root / "digests" / "daily"
    daily_digest.mkdir(parents=True, exist_ok=True)
    (daily_digest / "2026-05-20.md").write_text("Synthetic daily digest\n", encoding="utf-8")

    roots = MemoryOSRoots.from_hermes_home(
        hermes_home,
        profile="sannai",
        external_state_roots=[state_root],
    )
    return SannaiFixtureLayout(
        profile="sannai",
        hermes_home=hermes_home,
        state_root=state_root,
        roots=roots,
    )


def generate_event_corpus(
    *,
    count: int,
    seed: int,
    profile: str = "memoryos-test",
) -> Iterator[dict[str, object]]:
    """Yield schema-valid event fixtures without materializing the full corpus."""

    for offset in range(count):
        yield build_event(seed=seed + offset, profile=profile)
