"""CE: core-switch guard — upgrades re-enable the core disclosure ledger, and
the monitor alarms on the four-day-outage signature.

Background: a July config rewrite flipped ``memory_sources.enabled`` off. The
provider caches config at initialize, so the flip lay dormant until an Aug 1
gateway restart — then the disclosure ledger froze for four days while
conversation events kept flowing, and ``record_count: 0`` sat in every monitor
snapshot with no reader. Three layers close that hole:

1. installer upgrades auto-re-enable the one core, non-graduated switch;
2. CLI status exposes the recorder state so the monitor has something to read;
3. the monitor alarms on both the switch (``memory_sources_recording_disabled``)
   and the outage signature itself (``memory_sources_disclosure_outage``).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scripts.memory_os_3_200_monitor as monitor
from scripts.install_memory_os_plugin import _ensure_config_defaults


# ── Layer 1: installer ─────────────────────────────────────────────────────


def test_ensure_config_defaults_re_enables_core_disclosure_ledger(tmp_path: Path):
    """Counterfactual: without the fix the upgrade leaves enabled=False and
    reports nothing about core modes.

    The dual is as load-bearing as the flip: graduated modes
    (recall_arbitration / context_router / owner_review) must be REPORTED,
    never auto-flipped — flipping them would bypass their graduation
    governance.
    """
    home = tmp_path / "home"
    (home / "memory-os").mkdir(parents=True)
    (home / "memory-os" / "config.json").write_text(json.dumps({
        "prefetch_char_budget": 6000,
        "memory_sources": {"enabled": False, "mode": "metadata_only", "retention_days": 30},
        "recall_arbitration": {"mode": "shadow"},
        "context_router": {"enabled": True, "mode": "apply"},
    }), encoding="utf-8")

    report = _ensure_config_defaults(home)

    assert report["status"] == "updated"
    assert any("memory_sources.enabled" in change for change in report["changes"])
    saved = json.loads((home / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert saved["memory_sources"]["enabled"] is True
    # Graduated modes untouched on disk, visible in the report.
    assert saved["recall_arbitration"]["mode"] == "shadow"
    assert saved["context_router"]["mode"] == "apply"
    assert report["core_mode_report"]["recall_arbitration.mode"] == "shadow"
    assert report["core_mode_report"]["context_router.mode"] == "apply"
    assert report["core_mode_report"]["memory_sources.enabled"] is True

    # Second run: nothing left to change, but the drift report still ships.
    report_again = _ensure_config_defaults(home)
    assert report_again["status"] == "already_current"
    assert report_again["core_mode_report"]["memory_sources.enabled"] is True


def test_ensure_config_defaults_dry_run_reports_without_writing(tmp_path: Path):
    home = tmp_path / "home"
    (home / "memory-os").mkdir(parents=True)
    (home / "memory-os" / "config.json").write_text(json.dumps({
        "prefetch_char_budget": 6000,
        "memory_sources": {"enabled": False, "mode": "metadata_only"},
    }), encoding="utf-8")

    report = _ensure_config_defaults(home, dry_run=True)

    assert report["status"] == "would_update"
    saved = json.loads((home / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert saved["memory_sources"]["enabled"] is False


# ── Layer 2: CLI status exposes the recorder state ─────────────────────────


def test_status_report_exposes_memory_sources_recording_state(tmp_path: Path):
    from plugins.memory.memory_os.cli import build_status_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    home = tmp_path / "home"
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(home, profile="default"))
    store.initialize()

    # Default config: recorder off.
    status = build_status_report(store)
    assert status["memory_sources_recording"]["enabled"] is False

    (home / "memory-os" / "config.json").write_text(json.dumps({
        "memory_sources": {"enabled": True, "mode": "metadata_only"},
    }), encoding="utf-8")
    status = build_status_report(store)
    assert status["memory_sources_recording"] == {
        "enabled": True,
        "raw_enabled": True,
        "mode": "metadata_only",
    }


# ── Layer 3: monitor alarms ────────────────────────────────────────────────


def _stats_block(record_count: int) -> dict:
    return {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": record_count,
        "hours": 24,
    }


def test_recording_disabled_is_alarmed():
    """Counterfactual: before CE this exact production state (recorder off,
    everything else green) produced zero warnings for four days."""
    snapshot = monitor.classify_snapshot({
        "monitor_profile": "live",
        "status": {"memory_sources_recording": {"enabled": False, "mode": "metadata_only"}},
        "memory_sources": _stats_block(record_count=0),
    })
    assert any(
        item["code"] == "memory_sources_recording_disabled"
        for item in snapshot["warn"] + snapshot["fail"]
    )
    # The registry escalates it on production rather than leaving it advisory.
    entry = monitor.CLEAN_HOST_WARN_CLASSIFICATIONS["memory_sources_recording_disabled"]
    assert entry["production_behavior"] == "fail_if_production"


def test_disclosure_outage_signature_is_alarmed():
    """Zero disclosures in the stats window while a provider-captured
    conversation happened inside that window: the outage signature."""
    fresh_turn = datetime.now(timezone.utc).isoformat()
    snapshot = monitor.classify_snapshot({
        "monitor_profile": "live",
        "status": {"memory_sources_recording": {"enabled": True, "mode": "metadata_only"}},
        "session_mirror": {
            "schema_version": "memory-os.session_mirror_monitor_summary.v0",
            "latest_conversation_turn_ts": fresh_turn,
        },
        "memory_sources": _stats_block(record_count=0),
    })
    outage = [
        item for item in snapshot["warn"] + snapshot["fail"]
        if item["code"] == "memory_sources_disclosure_outage"
    ]
    assert outage, "fresh conversation + zero disclosures must alarm"
    assert outage[0]["value"]["window_hours"] == 24
    entry = monitor.CLEAN_HOST_WARN_CLASSIFICATIONS["memory_sources_disclosure_outage"]
    assert entry["production_behavior"] == "fail_if_production"


def test_disclosure_outage_stays_silent_without_the_signature():
    """A quiet ledger is only an outage when conversation traffic existed in
    the same window — idle is not broken (backlog 15's lesson, config side)."""
    stale_turn = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

    # Conversation older than the window: quiet ledger is idle, not broken.
    idle = monitor.classify_snapshot({
        "monitor_profile": "live",
        "status": {"memory_sources_recording": {"enabled": True, "mode": "metadata_only"}},
        "session_mirror": {
            "schema_version": "memory-os.session_mirror_monitor_summary.v0",
            "latest_conversation_turn_ts": stale_turn,
        },
        "memory_sources": _stats_block(record_count=0),
    })
    # Disclosures present: no outage regardless of conversation freshness.
    healthy = monitor.classify_snapshot({
        "monitor_profile": "live",
        "status": {"memory_sources_recording": {"enabled": True, "mode": "metadata_only"}},
        "session_mirror": {
            "schema_version": "memory-os.session_mirror_monitor_summary.v0",
            "latest_conversation_turn_ts": datetime.now(timezone.utc).isoformat(),
        },
        "memory_sources": _stats_block(record_count=3),
    })
    # Old snapshot without the recording block: value-guarded silence, and no
    # fabricated disabled alarm either.
    legacy = monitor.classify_snapshot({
        "monitor_profile": "live",
        "memory_sources": _stats_block(record_count=0),
    })
    for result in (idle, healthy, legacy):
        for code in ("memory_sources_disclosure_outage", "memory_sources_recording_disabled"):
            assert not any(
                item["code"] == code for item in result["warn"] + result["fail"]
            ), code
