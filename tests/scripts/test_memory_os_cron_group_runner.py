"""Tests for the Memory-OS cron group tick runner.

The consolidation merges 19 Hermes cron jobs into 8 group ticks while keeping
one ExecutionGate envelope per lane. These tests pin the properties that make
that safe: per-lane envelopes survive, a member's cadence is preserved by due
gating rather than by cron, and one member cannot take down the tick.
"""

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_group_runner():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "memory_os_cron_group_runner", SCRIPTS_DIR / "memory_os_cron_group_runner.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["memory_os_cron_group_runner"] = module
    spec.loader.exec_module(module)
    return module


def _write_snapshot(home: Path, members, group_key="tick_test", group_name="memory-os-tick-test"):
    """Install a synthetic group whose members are stub helpers."""
    specs = []
    for member in members:
        specs.append(
            {
                "key": member["key"],
                "name": group_name,
                "raw_script": member["raw_script"],
                "wrapper_script": "memory_os_cron_tick_test.py",
                "lane_id": member.get("lane_id", member["key"]),
                "helper_kind": "local_helper",
                "schedule_arg": "tick_test_schedule",
                "deliver_role": "local",
                "prompt_ref": "empty",
                "no_agent": True,
                "requires_boundary_report": False,
                "group_key": group_key,
                "due_policy": member.get("due_policy", "interval"),
                "due_interval_minutes": member.get("due_interval_minutes", 30),
                "calendar_anchor": member.get("calendar_anchor", ""),
                "timeout_seconds": member.get("timeout_seconds", 30),
            }
        )
    snapshot = {
        "schema_version": "memory-os.cron_registry.v1",
        "source_commit": "test",
        "specs": specs,
        "groups": [
            {
                "key": group_key,
                "name": group_name,
                "wrapper_script": "memory_os_cron_tick_test.py",
                "schedule_arg": "tick_test_schedule",
                "default_schedule": "*/15 * * * *",
                "deliver_role": "local",
                "prompt_ref": "empty",
                "no_agent": True,
                "member_keys": [member["key"] for member in members],
            }
        ],
    }
    path = home / "memory-os" / "system" / "memory_os_cron_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot), encoding="utf-8")


def _stub_helper(name: str, body: str = "print('ok')\n"):
    """Write a stub helper into the repo scripts dir the runner resolves from."""
    path = SCRIPTS_DIR / name
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def stub_helpers():
    created = []

    def _make(name, body="print('ok')\n"):
        created.append(_stub_helper(name, body))
        return name

    yield _make
    for path in created:
        if path.exists():
            path.unlink()


def _envelopes(home: Path):
    path = home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_each_member_gets_its_own_execution_gate_envelope(tmp_path, stub_helpers):
    """Governance granularity must survive scheduling consolidation.

    If members shared one envelope, the monitor's per-lane completion,
    boundary and risk_class accounting would collapse.
    """
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_alpha.py")
    stub_helpers("_stub_beta.py")
    _write_snapshot(
        home,
        [
            {"key": "alpha", "raw_script": "_stub_alpha.py", "lane_id": "alpha_lane"},
            {"key": "beta", "raw_script": "_stub_beta.py", "lane_id": "beta_lane"},
        ],
    )

    report = runner.run_group("tick_test", hermes_home=home)

    assert report["status"] == "ok"
    assert report["member_ran_count"] == 2
    records = _envelopes(home)
    permits = [item for item in records if item["stage"] == "permit"]
    completions = [item for item in records if item["stage"] == "completion"]
    assert {item["lane_id"] for item in permits} == {"alpha_lane", "beta_lane"}
    assert {item["lane_id"] for item in completions} == {"alpha_lane", "beta_lane"}
    # Distinct envelope ids per lane -- never a shared group envelope.
    assert len({item["execution_gate_envelope_id"] for item in permits}) == 2
    assert all(item["trigger_surface"] == "hermes_cron" for item in permits)


def test_member_not_due_is_skipped_on_the_next_tick(tmp_path, stub_helpers):
    """A 30-minute lane inside a 15-minute tick must run every OTHER tick."""
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_alpha.py")
    _write_snapshot(home, [{"key": "alpha", "raw_script": "_stub_alpha.py", "due_interval_minutes": 30}])
    start = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)

    first = runner.run_group("tick_test", hermes_home=home, now=start)
    too_soon = runner.run_group("tick_test", hermes_home=home, now=start + timedelta(minutes=15))
    due_again = runner.run_group("tick_test", hermes_home=home, now=start + timedelta(minutes=30))

    assert first["member_ran_count"] == 1
    assert too_soon["member_ran_count"] == 0
    assert too_soon["member_skipped_not_due_count"] == 1
    assert due_again["member_ran_count"] == 1


def test_calendar_member_runs_once_per_utc_day(tmp_path, stub_helpers):
    """Date-partitioned lanes (v3_seed_evidence) must not drift across the day
    boundary: elapsed gating could skip or double-count a natural_date."""
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_seed.py")
    _write_snapshot(
        home,
        [
            {
                "key": "seed",
                "raw_script": "_stub_seed.py",
                "due_policy": "calendar",
                "calendar_anchor": "00:00",
                "due_interval_minutes": 1440,
            }
        ],
    )
    day1 = datetime(2026, 7, 30, 0, 5, tzinfo=timezone.utc)

    first = runner.run_group("tick_test", hermes_home=home, now=day1)
    same_day_later = runner.run_group("tick_test", hermes_home=home, now=day1 + timedelta(hours=20))
    next_day = runner.run_group("tick_test", hermes_home=home, now=day1 + timedelta(days=1))

    assert first["member_ran_count"] == 1
    assert same_day_later["member_ran_count"] == 0
    assert same_day_later["members"][0]["reason"] == "already_ran_today"
    assert next_day["member_ran_count"] == 1


def test_calendar_member_waits_for_its_anchor(tmp_path, stub_helpers):
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_seed.py")
    _write_snapshot(
        home,
        [
            {
                "key": "seed",
                "raw_script": "_stub_seed.py",
                "due_policy": "calendar",
                "calendar_anchor": "06:00",
                "due_interval_minutes": 1440,
            }
        ],
    )
    day1 = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)
    runner.run_group("tick_test", hermes_home=home, now=day1)

    before_anchor = runner.run_group("tick_test", hermes_home=home, now=day1 + timedelta(hours=21))

    assert before_anchor["member_ran_count"] == 0
    assert before_anchor["members"][0]["reason"] == "before_calendar_anchor"


def test_owner_disabled_lane_is_skipped(tmp_path, stub_helpers):
    """Per-lane disable replaces the per-job disable owners lost to grouping."""
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_alpha.py")
    stub_helpers("_stub_beta.py")
    _write_snapshot(
        home,
        [
            {"key": "alpha", "raw_script": "_stub_alpha.py"},
            {"key": "beta", "raw_script": "_stub_beta.py"},
        ],
    )
    disable_path = home / "memory-os" / "system" / "cron_lane_disabled.json"
    disable_path.write_text(json.dumps({"disabled_lane_keys": ["beta"]}), encoding="utf-8")

    report = runner.run_group("tick_test", hermes_home=home)

    assert report["member_skipped_disabled_count"] == 1
    assert report["member_ran_count"] == 1
    ran = {item["key"] for item in report["members"] if item["status"] == "ok"}
    assert ran == {"alpha"}


def test_corrupt_disable_list_does_not_silently_stop_lanes(tmp_path, stub_helpers):
    """A malformed disable file must fail OPEN. Failing closed would silently
    halt governed lanes with no operator signal."""
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_alpha.py")
    _write_snapshot(home, [{"key": "alpha", "raw_script": "_stub_alpha.py"}])
    disable_path = home / "memory-os" / "system" / "cron_lane_disabled.json"
    disable_path.parent.mkdir(parents=True, exist_ok=True)
    disable_path.write_text("{not json", encoding="utf-8")

    report = runner.run_group("tick_test", hermes_home=home)

    assert report["member_ran_count"] == 1


def test_failing_member_does_not_abort_the_rest_of_the_tick(tmp_path, stub_helpers):
    """Under 1:1 jobs a failure cost one lane. Under a tick it must still
    cost only one lane."""
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_boom.py", "import sys\nsys.exit(9)\n")
    stub_helpers("_stub_after.py")
    _write_snapshot(
        home,
        [
            {"key": "boom", "raw_script": "_stub_boom.py", "lane_id": "boom_lane"},
            {"key": "after", "raw_script": "_stub_after.py", "lane_id": "after_lane"},
        ],
    )

    report = runner.run_group("tick_test", hermes_home=home)

    assert report["status"] == "error"
    assert report["member_error_count"] == 1
    statuses = {item["key"]: item["status"] for item in report["members"]}
    assert statuses["boom"] == "error"
    assert statuses["after"] == "ok"
    # The later member still recorded its own completion envelope.
    completions = [item for item in _envelopes(home) if item["stage"] == "completion"]
    assert {item["lane_id"] for item in completions} == {"boom_lane", "after_lane"}


def test_hanging_member_times_out_and_later_members_still_run(tmp_path, stub_helpers):
    """subprocess.run had no timeout before consolidation; a hang would now
    block every later member of the tick."""
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_hang.py", "import time\ntime.sleep(30)\n")
    stub_helpers("_stub_after.py")
    _write_snapshot(
        home,
        [
            {"key": "hang", "raw_script": "_stub_hang.py", "lane_id": "hang_lane", "timeout_seconds": 1},
            {"key": "after", "raw_script": "_stub_after.py", "lane_id": "after_lane"},
        ],
    )

    report = runner.run_group("tick_test", hermes_home=home)

    statuses = {item["key"]: item for item in report["members"]}
    assert statuses["hang"]["status"] == "timeout"
    assert statuses["hang"]["returncode"] == 124
    assert statuses["after"]["status"] == "ok"
    completions = {item["lane_id"]: item for item in _envelopes(home) if item["stage"] == "completion"}
    assert completions["hang_lane"]["execution_status"] == "timeout"


def test_overlapping_tick_is_reported_not_silently_skipped(tmp_path, stub_helpers):
    """A tick that overruns its cadence must be visible, not a silent pass."""
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_alpha.py")
    _write_snapshot(home, [{"key": "alpha", "raw_script": "_stub_alpha.py"}])
    lock_path = runner._group_lock_path(home, "tick_test")
    held = runner._try_exclusive_lock(lock_path)
    assert held is not None

    try:
        report = runner.run_group("tick_test", hermes_home=home)
    finally:
        runner._release_lock(held)

    assert report["status"] == "skipped_overlap"
    assert report["skipped_overlap_count"] == 1
    assert report["returncode"] == 0
    assert _envelopes(home) == []


def test_unknown_group_key_is_an_error(tmp_path):
    runner = _load_group_runner()

    report = runner.run_group("no_such_group", hermes_home=tmp_path / "home")

    assert report["status"] == "error"
    assert report["error_code"] == "unknown_cron_group"
    assert report["returncode"] == 2


def test_zero_due_interval_does_not_mean_run_every_tick(tmp_path, stub_helpers):
    """A malformed/zero interval must fall back to daily, not to 'always due'.

    Treating 0 as 'run now' would silently convert a weekly lane into a
    per-tick lane on a snapshot written by an older build.
    """
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_alpha.py")
    _write_snapshot(home, [{"key": "alpha", "raw_script": "_stub_alpha.py", "due_interval_minutes": 0}])
    start = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)

    runner.run_group("tick_test", hermes_home=home, now=start)
    soon = runner.run_group("tick_test", hermes_home=home, now=start + timedelta(minutes=20))

    assert soon["member_ran_count"] == 0
    assert soon["member_skipped_not_due_count"] == 1


def test_force_overrides_due_gating(tmp_path, stub_helpers):
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_alpha.py")
    _write_snapshot(home, [{"key": "alpha", "raw_script": "_stub_alpha.py", "due_interval_minutes": 10080}])
    start = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    runner.run_group("tick_test", hermes_home=home, now=start)

    forced = runner.run_group("tick_test", hermes_home=home, now=start + timedelta(minutes=1), force=True)

    assert forced["member_ran_count"] == 1


def test_lane_state_survives_across_ticks(tmp_path, stub_helpers):
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_alpha.py")
    _write_snapshot(home, [{"key": "alpha", "raw_script": "_stub_alpha.py"}])

    runner.run_group("tick_test", hermes_home=home)

    state = json.loads((home / "memory-os" / "system" / "cron_lane_state.json").read_text(encoding="utf-8"))
    assert state["schema_version"] == "memory-os.cron_lane_state.v1"
    assert state["lanes"]["alpha"]["last_status"] == "ok"
    assert state["lanes"]["alpha"]["last_started_at"]


def test_failed_member_still_records_attempt_so_it_retries_on_cadence(tmp_path, stub_helpers):
    """Recording only successes would make a persistently failing lane re-run
    on every single tick instead of at its own cadence."""
    runner = _load_group_runner()
    home = tmp_path / "home"
    stub_helpers("_stub_boom.py", "import sys\nsys.exit(3)\n")
    _write_snapshot(home, [{"key": "boom", "raw_script": "_stub_boom.py", "due_interval_minutes": 60}])
    start = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)

    runner.run_group("tick_test", hermes_home=home, now=start)
    soon = runner.run_group("tick_test", hermes_home=home, now=start + timedelta(minutes=5))

    assert soon["member_ran_count"] == 0
    assert soon["member_skipped_not_due_count"] == 1
