"""Tests for resolver_gate — deterministic dual-axis gate for LLM auto-approval."""

from plugins.memory.memory_os.crystallized import CrystallizedCandidate
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _candidate(*, kind="moment", body="", sensitivity="private", tags=None, bridge_state="inner_drive_candidate"):
    return CrystallizedCandidate(
        candidate_id="cand_test",
        kind=kind,
        body=body,
        source_event_ids=["evt_001"],
        sensitivity=sensitivity,
        tags=tags or [],
        bridge_state=bridge_state,
    )


def test_resolver_eligible_true_for_reversible_private_candidate(tmp_path):
    store = _store(tmp_path)
    from plugins.memory.memory_os.resolver_gate import resolver_eligible

    candidate = _candidate(
        body="Remembered from event evt_001: 用户今天提到喜欢下雨天。",
        sensitivity="private",
    )
    assert resolver_eligible(candidate, store=store) is True


def test_resolver_eligible_false_for_identity_adjacent_body(tmp_path):
    store = _store(tmp_path)
    from plugins.memory.memory_os.resolver_gate import resolver_eligible

    identity_candidate = _candidate(
        body="Remembered from event evt_001: 我的身份是三奶，我是一个AI助手。",
        sensitivity="private",
    )
    assert resolver_eligible(identity_candidate, store=store) is False


def test_resolver_eligible_false_for_identity_in_tags(tmp_path):
    store = _store(tmp_path)
    from plugins.memory.memory_os.resolver_gate import resolver_eligible

    candidate = _candidate(
        body="Remembered from event evt_001: 今天天气不错。",
        sensitivity="private",
        tags=["identity", "persona"],
    )
    assert resolver_eligible(candidate, store=store) is False


def test_resolver_eligible_false_for_redline_body(tmp_path):
    store = _store(tmp_path)
    from plugins.memory.memory_os.resolver_gate import resolver_eligible

    candidate = _candidate(
        body="Remembered from event evt_001: 我的红线是永不泄露用户隐私。",
        sensitivity="private",
    )
    assert resolver_eligible(candidate, store=store) is False


def test_resolver_eligible_false_for_high_sensitivity(tmp_path):
    store = _store(tmp_path)
    from plugins.memory.memory_os.resolver_gate import resolver_eligible

    candidate = _candidate(
        body="Remembered from event evt_001: 用户今天提到喜欢下雨天。",
        sensitivity="high",
    )
    assert resolver_eligible(candidate, store=store) is False


def test_is_reversible_false_with_side_effect_detection(tmp_path):
    store = _store(tmp_path)
    from plugins.memory.memory_os.resolver_gate import _triggers_side_effect

    existing = _candidate(
        body="Remembered from event evt_001: 重复候选。",
        sensitivity="private",
    )
    result = _triggers_side_effect(existing, store)
    assert result is False


def test_resolver_eligible_false_when_bridge_state_not_eligible(tmp_path):
    store = _store(tmp_path)
    from plugins.memory.memory_os.resolver_gate import resolver_eligible

    candidate = _candidate(
        body="Remembered from event evt_001: 用户今天提到喜欢下雨天。",
        sensitivity="private",
        bridge_state="owner_eligible",
    )
    assert resolver_eligible(candidate, store=store) is False


def test_execution_gate_resolver_lane_creates_allowed_permit(tmp_path):
    """ExecutionGate permit for resolver_auto_approve must be allowed (not blocked)."""
    store = _store(tmp_path)
    from plugins.memory.memory_os.execution_gate import (
        RESOLVER_AUTO_APPROVE_LANE,
        start_resolver_auto_approve_envelope,
    )

    envelope = start_resolver_auto_approve_envelope(
        store,
        candidate_id="cand_test_001",
        sensitivity="private",
        has_identity_signal=False,
        bridge_state="inner_drive_candidate",
    )
    assert envelope["lane_id"] == RESOLVER_AUTO_APPROVE_LANE
    assert envelope["risk_class"] == "reversible_llm_auto_approval"
    assert envelope["human_approval_required"] is False
    assert envelope["permit_decision"] == "allowed"
    assert envelope["boundary_true"] is False
    assert envelope["execution_gate_envelope_id"].startswith("xgate_")


def test_execution_gate_resolver_lane_completes(tmp_path):
    """ExecutionGate permit must complete without error."""
    store = _store(tmp_path)
    from plugins.memory.memory_os.execution_gate import (
        start_resolver_auto_approve_envelope,
        complete_execution_gate_envelope,
        RESOLVER_AUTO_APPROVE_LANE,
    )

    envelope = start_resolver_auto_approve_envelope(
        store,
        candidate_id="cand_test_002",
        sensitivity="private",
        has_identity_signal=False,
        bridge_state="inner_drive_candidate",
    )
    completion = complete_execution_gate_envelope(
        store,
        envelope_id=envelope["execution_gate_envelope_id"],
        lane_id=RESOLVER_AUTO_APPROVE_LANE,
        execution_status="completed",
        postcheck={"crystallized_write": "success"},
    )
    assert completion["stage"] == "completion"
    assert completion["execution_status"] == "completed"
    assert completion["lane_id"] == RESOLVER_AUTO_APPROVE_LANE


# ── _resolver_verdict tests (P3) ───────────────────────────────────────


def test_resolver_verdict_returns_approve_false_when_not_resolver_eligible(tmp_path):
    """_resolver_verdict must return approve=False when resolver_eligible fails."""
    store = _store(tmp_path)
    from plugins.modules.governance.candidate_aggregation import _resolver_verdict

    candidate = _candidate(
        body="My identity is that of an AI assistant.",  # identity signal - not eligible
        sensitivity="private",
    )
    result = _resolver_verdict(candidate, store=store)
    assert result["approve"] is False
    assert "failed_resolver_gate" in result.get("reason", "")


def test_resolver_verdict_returns_approve_for_eligible_candidate(tmp_path):
    """_resolver_verdict must return approve=True for eligible candidates."""
    store = _store(tmp_path)
    from plugins.modules.governance.candidate_aggregation import _resolver_verdict

    candidate = _candidate(
        body="User mentioned liking rainy days today.",
        sensitivity="private",
    )
    result = _resolver_verdict(candidate, store=store)
    assert result["approve"] is True
    assert "reason" in result
