"""Adversarial contracts for the governed Hermes Community layer."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.community import (
    RosterEntry,
    add_to_roster,
    get_active_roster,
    reserve_roster_entry,
    transition_partner_status,
    validate_partner_id,
    validate_roster,
)
from plugins.memory.memory_os.community_shared import (
    read_shared_memory,
    write_newspaper_entry,
    write_shared_memory,
)
from plugins.memory.memory_os.community_snapshot import build_community_snapshot
from plugins.memory.memory_os.community_triggers import (
    PartnerState,
    check_newspaper_trigger,
    check_shared_followup_trigger,
)
from plugins.memory.memory_os.partner_create import create_partner as _create_partner_api, generate_partner_id


def _community_root(tmp_path: Path) -> Path:
    root = tmp_path / "profiles" / "sannai" / "memory-os"
    (root / "community" / "charters").mkdir(parents=True)
    (root / "community" / "roster.jsonl").touch()
    (root / "community" / "budget.yaml").write_text(
        "global:\n  max_active_partners: 3\n",
        encoding="utf-8",
    )
    return root


def _call_create_partner(root: Path, *args, **kwargs):
    backend = str(kwargs.pop("backend", "partner-model"))
    sannai_backend = str(kwargs.pop("sannai_backend", "sannai-model"))
    root.parent.joinpath("config.yaml").write_text(
        "model:\n"
        f"  default: {sannai_backend}\n"
        "  provider: sannai-provider\n"
        "  base_url: https://sannai.example/v1\n",
        encoding="utf-8",
    )
    try:
        validate_partner_id(str(kwargs.get("partner_id") or ""))
        profile_id = str(kwargs["partner_id"])
    except ValueError:
        profile_id = "fixture-invalid"
    partner_config = root.parent.parent / profile_id / "config.yaml"
    partner_config.parent.mkdir(parents=True, exist_ok=True)
    partner_config.write_text(
        "model:\n"
        f"  default: {backend}\n"
        "  provider: partner-provider\n"
        "  base_url: https://partner.example/v1\n",
        encoding="utf-8",
    )
    kwargs["partner_config_path"] = partner_config
    return _create_partner_api(root, *args, **kwargs)


@pytest.mark.parametrize("partner_id", ["../escape", "a/b", "", ".", "A B"])
def test_partner_id_rejects_unsafe_or_nonportable_values(partner_id: str) -> None:
    with pytest.raises(ValueError):
        validate_partner_id(partner_id)


def test_generated_partner_id_is_portable_when_name_has_no_ascii_slug() -> None:
    partner_id = generate_partner_id("阿澜")
    validate_partner_id(partner_id)
    assert partner_id.startswith("partner-")


def test_create_partner_rejects_path_traversal_without_writing(tmp_path: Path) -> None:
    root = _community_root(tmp_path)
    result = _call_create_partner(
        root,
        "恶意",
        "test",
        partner_id="../../../escaped",
        actor="sannai",
        backend="partner-model",
        sannai_backend="sannai-model",
    )
    assert result.status == "fail"
    assert result.errors == ["invalid partner id"]
    assert not (tmp_path / "escaped").exists()


def test_create_partner_requires_authorized_actor(tmp_path: Path) -> None:
    root = _community_root(tmp_path)
    result = _call_create_partner(root, "A", "friendly", partner_id="a-01")
    assert result.status == "fail"
    assert result.errors == ["actor is not authorized to create partners"]


def test_create_partner_rejects_same_backend_as_sannai(tmp_path: Path) -> None:
    root = _community_root(tmp_path)
    result = _call_create_partner(
        root,
        "P",
        "kind",
        partner_id="p-01",
        actor="sannai",
        backend="same-model",
        sannai_backend="same-model",
    )
    assert result.status == "fail"
    assert result.errors == ["partner backend must differ from sannai backend"]


def test_create_partner_rejects_same_physical_endpoint_under_aliases(tmp_path: Path) -> None:
    root = _community_root(tmp_path)
    root.parent.joinpath("config.yaml").write_text(
        "model:\n  default: alias-a\n  provider: provider-a\n  base_url: https://same.example/v1\n",
        encoding="utf-8",
    )
    partner_config = root.parent.parent / "p-01" / "config.yaml"
    partner_config.parent.mkdir(parents=True, exist_ok=True)
    partner_config.write_text(
        "model:\n  default: alias-b\n  provider: provider-b\n  base_url: https://same.example/other\n",
        encoding="utf-8",
    )
    result = _create_partner_api(
        root, "P", "kind", partner_id="p-01", actor="sannai",
        partner_config_path=partner_config,
    )
    assert result.status == "fail"
    assert result.errors == ["partner backend must differ from sannai backend"]


def test_create_partner_requires_real_partner_profile_config(tmp_path: Path) -> None:
    root = _community_root(tmp_path)
    result = _create_partner_api(root, "P", "kind", partner_id="p-01", actor="sannai")
    assert result.status == "fail"
    assert result.errors == ["partner profile config required in non-embedded mode"]


def test_partner_creation_fails_closed_on_invalid_budget(tmp_path: Path) -> None:
    root = _community_root(tmp_path)
    (root / "community" / "budget.yaml").write_text("global: [broken\n", encoding="utf-8")
    result = _call_create_partner(
        root,
        "P",
        "kind",
        partner_id="p-01",
        actor="sannai",
        backend="different-model",
        sannai_backend="sannai-model",
    )
    assert result.status == "fail"
    assert result.errors == ["budget configuration invalid"]


@pytest.mark.parametrize(
    ("budget_text", "expected"),
    [
        (None, "budget configuration missing"),
        ("global:\n  max_active_partners: 0\n", "community active partner limit reached"),
    ],
)
def test_partner_creation_fails_closed_when_budget_unavailable_or_zero(
    tmp_path: Path,
    budget_text: str | None,
    expected: str,
) -> None:
    root = _community_root(tmp_path)
    budget = root / "community" / "budget.yaml"
    if budget_text is None:
        budget.unlink()
    else:
        budget.write_text(budget_text, encoding="utf-8")
    result = _call_create_partner(
        root, "P", "kind", partner_id="p-01", actor="sannai",
        backend="partner-model", sannai_backend="sannai-model",
    )
    assert result.status == "fail"
    assert result.errors == [expected]


def test_partner_creation_fails_closed_on_invalid_roster(tmp_path: Path) -> None:
    root = _community_root(tmp_path)
    (root / "community" / "roster.jsonl").write_text("[]\n", encoding="utf-8")
    result = _call_create_partner(
        root, "P", "kind", partner_id="p-01", actor="sannai",
        backend="partner-model", sannai_backend="sannai-model",
    )
    assert result.status == "fail"
    assert result.errors[0].startswith("roster invalid:")


def test_create_partner_rejects_duplicate_without_overwriting_profile(tmp_path: Path) -> None:
    root = _community_root(tmp_path)
    first = _call_create_partner(
        root, "A", "first", partner_id="dup-01", actor="sannai",
        backend="partner-model", sannai_backend="sannai-model",
    )
    assert first.status == "ok"
    soul_path = root / "community" / "partners" / "dup-01" / "SOUL.md"
    original = soul_path.read_text(encoding="utf-8")

    second = _call_create_partner(
        root, "B", "second", partner_id="dup-01", actor="sannai",
        backend="partner-model", sannai_backend="sannai-model",
    )

    assert second.status == "fail"
    assert second.errors == ["duplicate id: dup-01"]
    assert soul_path.read_text(encoding="utf-8") == original
    assert validate_roster(root / "community" / "roster.jsonl") == []


def test_create_partner_losing_publish_race_never_deletes_winner(tmp_path: Path, monkeypatch) -> None:
    root = _community_root(tmp_path)
    winner = root / "community" / "partners" / "race-01"
    original_rename = Path.rename

    def lose_race(source: Path, target: Path):
        if target == winner:
            target.mkdir(parents=True)
            (target / "winner.txt").write_text("survives", encoding="utf-8")
            raise FileExistsError("winner published")
        return original_rename(source, target)

    monkeypatch.setattr(Path, "rename", lose_race)
    result = _call_create_partner(
        root, "Race", "curious", partner_id="race-01", actor="sannai",
        backend="partner-model", sannai_backend="sannai-model",
    )

    assert result.status == "fail"
    assert result.errors == ["duplicate id: race-01"]
    assert (winner / "winner.txt").read_text(encoding="utf-8") == "survives"


def test_roster_readers_skip_non_object_json_lines(tmp_path: Path) -> None:
    roster = tmp_path / "roster.jsonl"
    roster.write_text(
        "[]\n" + json.dumps({"id": "valid-01", "name": "Valid", "status": "active"}) + "\n",
        encoding="utf-8",
    )
    errors = validate_roster(roster)
    assert errors == ["line 1: record must be an object"]
    assert [entry.id for entry in get_active_roster(roster)] == ["valid-01"]


def test_roster_reads_legacy_unicode_partner_id(tmp_path: Path) -> None:
    roster = tmp_path / "roster.jsonl"
    roster.write_text(
        json.dumps({"id": "阿澜-ab12cd34", "name": "阿澜", "status": "active"}) + "\n",
        encoding="utf-8",
    )
    assert validate_roster(roster) == []
    assert [entry.id for entry in get_active_roster(roster)] == ["阿澜-ab12cd34"]


def test_add_to_roster_is_duplicate_safe(tmp_path: Path) -> None:
    roster = tmp_path / "roster.jsonl"
    entry = RosterEntry(id="safe-01", name="Safe")
    assert add_to_roster(roster, entry) == []
    assert add_to_roster(roster, entry) == ["duplicate id: safe-01"]
    assert len(roster.read_text(encoding="utf-8").splitlines()) == 1


def test_roster_reservation_enforces_active_limit_under_concurrency(tmp_path: Path) -> None:
    roster = tmp_path / "roster.jsonl"
    entries = [RosterEntry(id=f"p-{index:02d}", name=f"P{index}") for index in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda entry: reserve_roster_entry(roster, entry, max_active=1), entries))
    assert sorted(result == [] for result in results) == [False, True]
    assert len(get_active_roster(roster)) == 1


def test_status_transition_appends_new_authoritative_state(tmp_path: Path) -> None:
    roster = tmp_path / "roster.jsonl"
    assert add_to_roster(roster, RosterEntry(id="p-01", name="Partner")) == []
    result = transition_partner_status(roster, "p-01", "retired", actor="owner")
    assert result == []
    assert get_active_roster(roster) == []
    assert validate_roster(roster) == []


def test_shared_memory_requires_sannai_actor(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        write_shared_memory(tmp_path, "p-01", "private", actor="partner")
    assert not (tmp_path / "shared").exists()


def test_shared_memory_rejects_unsafe_partner_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_shared_memory(tmp_path, "../escape", "private", actor="sannai")


def test_shared_reader_skips_non_object_json_lines(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    path = shared / "sannai__p-01.jsonl"
    path.write_text("[]\n" + json.dumps({"summary": "valid", "partner_id": "p-01"}) + "\n")
    assert [entry.summary for entry in read_shared_memory(tmp_path, "p-01")] == ["valid"]


def test_newspaper_requires_trusted_actor(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        write_newspaper_entry(tmp_path, "news", actor="partner")
    entry = write_newspaper_entry(tmp_path, "news", actor="info_collect")
    assert entry.summary == "news"


def test_stale_shared_followup_does_not_trigger(tmp_path: Path) -> None:
    entry = write_shared_memory(
        tmp_path,
        "p-01",
        "old thread",
        actor="sannai",
        sannai_feeling="curious",
    )
    path = tmp_path / "shared" / "sannai__p-01.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["ts"] = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = check_shared_followup_trigger(PartnerState(partner_id="p-01"), tmp_path)
    assert not result.should_trigger


def test_newspaper_trigger_uses_last_seen_cursor(tmp_path: Path) -> None:
    entry = write_newspaper_entry(tmp_path, "news", actor="info_collect")
    state = PartnerState(partner_id="p-01", last_newspaper_ts=entry.ts)
    assert not check_newspaper_trigger(state, tmp_path).should_trigger


def test_snapshot_uses_injected_inbox_and_filters_non_partner_senders(tmp_path: Path) -> None:
    community = tmp_path / "community"
    community.mkdir()
    (community / "roster.jsonl").write_text(
        json.dumps({"id": "p-01", "name": "Partner", "status": "active"}) + "\n",
        encoding="utf-8",
    )
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "partner.json").write_text(
        json.dumps({"from": "p-01", "read": False, "delivery_state": "unread"})
    )
    (inbox / "owner.json").write_text(json.dumps({"from": "owner", "read": False}))

    snapshot = build_community_snapshot(community, inbox_dir=inbox)

    assert snapshot["unread_messages"] == 1
    assert snapshot["active_partners"] == ["Partner"]


def test_state_overlay_includes_community_projection(tmp_path: Path) -> None:
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.state_overlay import build_state_overlay
    from plugins.memory.memory_os.state_overlay_renderer import render_state_overlay_md_short
    from plugins.memory.memory_os.store import MemoryOSStore

    home = tmp_path / ".hermes"
    roots = MemoryOSRoots.from_hermes_home(home, profile="sannai")
    store = MemoryOSStore(roots)
    store.initialize()
    community = roots.memory_os_root / "community"
    community.mkdir()
    (community / "roster.jsonl").write_text(
        json.dumps({"id": "p-01", "name": "Partner", "status": "active"}) + "\n",
        encoding="utf-8",
    )
    shared_mailbox = tmp_path / "shared-mailbox"
    inbox = shared_mailbox / "agents" / "sannai" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "message.json").write_text(
        json.dumps({"from": "p-01", "delivery_state": "unread", "read": False}),
        encoding="utf-8",
    )
    (home / "config.yaml").write_text(
        f"platforms:\n  mailbox:\n    extra:\n      root: {shared_mailbox}\n      agent_id: sannai\n",
        encoding="utf-8",
    )

    overlay = build_state_overlay(store, roots)
    rendered = render_state_overlay_md_short(overlay)

    assert overlay["community_snapshot"]["status"] == "ok"
    assert "Partner" in overlay["community_snapshot"]["data"][0]["text"]
    assert any(
        "Unread partner messages: 1" in item["text"]
        for item in overlay["community_snapshot"]["data"]
    )
    assert "Community" in rendered
