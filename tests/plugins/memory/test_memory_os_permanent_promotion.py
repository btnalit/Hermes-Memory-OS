"""V2-0 permanent-promotion public contract tests (Task 1)."""
from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


def test_proposal_id_and_content_hash_are_stable_for_same_input():
    from plugins.memory.memory_os.permanent_promotion import content_hash, make_proposal_id

    assert content_hash("stable body") == content_hash("stable body")
    assert re.fullmatch(r"ppm_[0-9a-f]{32}", make_proposal_id("0123456789abcdef0123456789abcdef"))


def test_issue_token_uses_unpredictable_secret_material():
    from plugins.memory.memory_os.permanent_promotion import issue_token

    first = issue_token()
    second = issue_token()
    assert first.startswith("ppmt_")
    assert second.startswith("ppmt_")
    assert first != second
    assert len(first.removeprefix("ppmt_")) >= 43


def test_proposal_record_contains_required_binding_fields():
    from plugins.memory.memory_os.permanent_promotion import build_proposal_record

    proposal = build_proposal_record(
        proposal_id="ppm_0123456789abcdef0123456789abcdef",
        target_id="cry_123",
        candidate_id="cand_123",
        body="stable body",
        created_at="2026-07-10T00:00:00Z",
        channel="cli",
    )
    assert proposal["schema_version"] == "memory-os.permanent-promotion-proposal.v1"
    assert proposal["target_type"] == "permanent_memory_promotion"
    assert proposal["content_hash"]
    assert proposal["dossier_snapshot_hash"]
    assert proposal["clearance"] == {"status": "unavailable", "reason_code": "v2e_not_enabled"}


@pytest.mark.parametrize("action,target_type", [("explode", "permanent_memory_promotion"), ("approve", "candidate_cluster")])
def test_invalid_action_or_target_type_is_rejected(action, target_type):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionError, validate_action_target

    with pytest.raises(PermanentPromotionError):
        validate_action_target(action, target_type)


def test_create_proposal_appends_locked_record_and_open_snapshot(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import ProposalLedger

    ledger = ProposalLedger(tmp_path / "memory-os")
    proposal, created = ledger.create_or_get(
        target_id="cry_1", candidate_id="cand_1", body="stable body", channel="cli"
    )
    assert created is True
    assert proposal["proposal_id"].startswith("ppm_")
    assert (tmp_path / "memory-os/system/permanent_promotion_proposals.jsonl").exists()
    snapshot = (tmp_path / "memory-os/system/permanent_promotion_open.jsonl").read_text()
    assert proposal["proposal_id"] in snapshot


def test_same_content_and_evidence_open_proposal_is_idempotent(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import ProposalLedger

    ledger = ProposalLedger(tmp_path / "memory-os")
    first, first_created = ledger.create_or_get(target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli")
    second, second_created = ledger.create_or_get(target_id="cry_2", candidate_id="cand_2", body="stable", channel="cli")
    assert first_created is True
    assert second_created is False
    assert second["proposal_id"] == first["proposal_id"]


def test_terminal_proposal_is_not_reused_as_open_proposal(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import ProposalLedger

    ledger = ProposalLedger(tmp_path / "memory-os")
    first, _ = ledger.create_or_get(target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli")
    ledger.append_terminal(first["proposal_id"], "rejected")
    second, created = ledger.create_or_get(target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli")
    assert created is True
    assert second["proposal_id"] != first["proposal_id"]


def test_issue_token_stores_hash_not_raw_token_and_binds_proposal(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import ProposalLedger, TokenLedger

    proposal, _ = ProposalLedger(tmp_path / "memory-os").create_or_get(target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli")
    token = TokenLedger(tmp_path / "memory-os").issue(proposal, channel="cli")
    ledger_text = (tmp_path / "memory-os/system/owner_action_tokens.jsonl").read_text()
    assert token not in ledger_text
    assert proposal["proposal_id"] in ledger_text


def test_legacy_unknown_and_consumed_tokens_fail_closed(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionError, ProposalLedger, TokenLedger

    root = tmp_path / "memory-os"
    proposal, _ = ProposalLedger(root).create_or_get(target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli")
    tokens = TokenLedger(root)
    token = tokens.issue(proposal, channel="cli")
    for value, code in [("oa_deadbeef", "legacy_token"), ("ppmt_unknown", "token_not_found")]:
        with pytest.raises(PermanentPromotionError, match=code):
            tokens.validate(value, proposal=proposal, current_body="stable")
    tokens.consume(token)
    with pytest.raises(PermanentPromotionError, match="token_consumed"):
        tokens.validate(token, proposal=proposal, current_body="stable")


def test_expired_token_and_cross_proposal_rebinding_fail_closed(tmp_path):
    from datetime import datetime, timedelta, timezone
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionError, ProposalLedger, TokenLedger

    root = tmp_path / "memory-os"
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    proposals = ProposalLedger(root, clock=lambda: now)
    first, _ = proposals.create_or_get(target_id="cry_1", candidate_id="cand_1", body="one", channel="cli")
    second, _ = proposals.create_or_get(target_id="cry_2", candidate_id="cand_2", body="two", channel="cli")
    tokens = TokenLedger(root, clock=lambda: now)
    expired = tokens.issue(first, channel="cli", expires_at=now - timedelta(seconds=1))
    with pytest.raises(PermanentPromotionError, match="token_expired"):
        tokens.validate(expired, proposal=first, current_body="one")
    valid = tokens.issue(first, channel="cli")
    with pytest.raises(PermanentPromotionError, match="token_binding_mismatch"):
        tokens.validate(valid, proposal=second, current_body="two")


def test_content_mismatch_fails_closed(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionError, ProposalLedger, TokenLedger

    root = tmp_path / "memory-os"
    proposal, _ = ProposalLedger(root).create_or_get(target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli")
    token = TokenLedger(root).issue(proposal, channel="cli")
    with pytest.raises(PermanentPromotionError, match="content_hash_mismatch"):
        TokenLedger(root).validate(token, proposal=proposal, current_body="changed")


def test_confirm_requires_verified_permanent_promotion_binding(tmp_path):
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
    store.initialize()
    candidate = CrystallizedCandidate("cand_1", "fact", "A stable fact.", ["evt_1"])
    decision = ApprovalDecision("cand_1", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver", "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-08-01T00:00:00Z")
    service = CrystallizedMemoryService(store)
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    record_id = service.read_records("owner_approved.md")[0].frontmatter["id"]
    with pytest.raises(Exception, match="PermanentPromotionService"):
        service.confirm_provisional_record(record_id, confirmed_by="owner")


# ── Task 2/3/4 gap coverage: rollback, positive/negative token paths,
# guarded-confirm semantics, and the caller-authorization AST guard ────────


def _provisional_service(tmp_path, *, body="A stable fact.", candidate_id="cand_1"):
    """Build a store with one active provisional record; return (service, record_id)."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
    store.initialize()
    candidate = CrystallizedCandidate(candidate_id, "fact", body, ["evt_1"])
    decision = ApprovalDecision(
        candidate_id, ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
        "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-08-01T00:00:00Z",
    )
    service = CrystallizedMemoryService(store)
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    record_id = service.read_records("owner_approved.md")[0].frontmatter["id"]
    return service, record_id


def test_proposal_ledger_preserves_records_when_snapshot_replace_fails(tmp_path, monkeypatch):
    import plugins.memory.memory_os.permanent_promotion as pp

    root = tmp_path / "memory-os"
    ledger = pp.ProposalLedger(root)

    def _boom(*_a, **_k):
        raise OSError("snapshot write failed")

    monkeypatch.setattr(pp, "write_jsonl_atomic_locked", _boom)
    with pytest.raises(OSError):
        ledger.create_or_get(target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli")

    # The append-only proposal event survives even though the snapshot failed.
    events = (root / "system/permanent_promotion_proposals.jsonl").read_text().splitlines()
    assert len(events) == 1

    # Once the snapshot writer recovers, the open set is derived from the ledger
    # (idempotent — same content does not create a duplicate open).
    monkeypatch.undo()
    proposal, created = ledger.create_or_get(target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli")
    assert created is False
    snapshot = (root / "system/permanent_promotion_open.jsonl").read_text()
    assert proposal["proposal_id"] in snapshot


def test_valid_open_token_validates_then_consumes_once(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import (
        PermanentPromotionError, ProposalLedger, TokenLedger,
    )

    root = tmp_path / "memory-os"
    proposal, _ = ProposalLedger(root).create_or_get(
        target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli"
    )
    tokens = TokenLedger(root)
    token = tokens.issue(proposal, channel="cli")

    state = tokens.validate(token, proposal=proposal, current_body="stable")
    assert state["status"] == "open"

    tokens.consume(token)
    with pytest.raises(PermanentPromotionError, match="token_consumed"):
        tokens.validate(token, proposal=proposal, current_body="stable")


def test_revoked_token_fails_closed(tmp_path):
    import json
    from plugins.memory.memory_os.permanent_promotion import (
        PermanentPromotionError, ProposalLedger, TokenLedger, content_hash,
    )

    root = tmp_path / "memory-os"
    proposal, _ = ProposalLedger(root).create_or_get(
        target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli"
    )
    tokens = TokenLedger(root)
    token = tokens.issue(proposal, channel="cli")
    # Simulate an owner/system revocation event appended to the ledger.
    with tokens.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "schema_version": "memory-os.permanent-promotion-token.v1",
            "token_hash": content_hash(token), "status": "revoked",
            "updated_at": "2026-07-10T00:00:00Z",
        }, sort_keys=True) + "\n")
    with pytest.raises(PermanentPromotionError, match="token_revoked"):
        tokens.validate(token, proposal=proposal, current_body="stable")


def test_token_validation_requires_ledger_membership_not_recomputation(tmp_path):
    """Counterfactual: a well-formed but never-issued token must fail closed.

    Guards that validation is issuance-record membership — not a deterministic
    recomputation that any caller could reproduce.
    """
    from plugins.memory.memory_os.permanent_promotion import (
        PermanentPromotionError, ProposalLedger, TokenLedger,
    )

    root = tmp_path / "memory-os"
    proposal, _ = ProposalLedger(root).create_or_get(
        target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli"
    )
    tokens = TokenLedger(root)
    tokens.issue(proposal, channel="cli")  # a real token exists, but we forge another
    forged = "ppmt_" + "A" * 43
    with pytest.raises(PermanentPromotionError, match="token_not_found"):
        tokens.validate(forged, proposal=proposal, current_body="stable")


def test_confirm_rejects_free_text_confirmed_by_without_binding(tmp_path):
    from plugins.memory.memory_os.crystallized import CrystallizedApprovalError

    service, record_id = _provisional_service(tmp_path)
    with pytest.raises(CrystallizedApprovalError, match="PermanentPromotionService"):
        service.confirm_provisional_record(record_id, confirmed_by="auto_promote")


def test_direct_canonical_confirmation_rejects_arbitrary_authorization(tmp_path):
    from plugins.memory.memory_os.crystallized import CrystallizedApprovalError
    from types import SimpleNamespace

    service, record_id = _provisional_service(tmp_path)
    forged = SimpleNamespace(
        proposal_id="ppm_" + "0" * 32,
        target_id=record_id,
        token_hash="deadbeef",
    )
    with pytest.raises(CrystallizedApprovalError, match="PermanentPromotionService"):
        service.confirm_provisional_record(record_id, authorization=forged)
    assert service.find_record(record_id).frontmatter["provisional"] is True


def test_service_promotes_once_and_consumes_bound_token(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import (
        PermanentPromotionError, PermanentPromotionService,
    )

    service, record_id = _provisional_service(tmp_path)
    pps = PermanentPromotionService(service.store)

    proposed = pps.propose(record_id)
    assert proposed["status"] == "open"
    token = proposed["token"]

    approved = pps.approve(token)
    assert approved["status"] == "approved"
    assert approved["canonical_state_changed"] is True
    # Record is now permanent (provisional flag cleared), history preserved.
    fm = service.read_records("owner_approved.md")[0].frontmatter
    assert fm["provisional"] is False
    assert fm["permanent_promotion_proposal_id"] == proposed["proposal_id"]

    # Promote-once: retry returns the stable terminal result and never writes
    # canonical state twice.
    duplicate = pps.approve(token)
    assert duplicate["status"] == "approved"
    assert duplicate["canonical_state_changed"] is True


def test_service_approval_closes_inactive_target_without_confirming(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

    service, record_id = _provisional_service(tmp_path)
    promotions = PermanentPromotionService(service.store)
    proposed = promotions.propose(record_id)
    # Owner-reject → canonical_state=provisional_rejected (provisional flag kept).
    service.invalidate_provisional_record(record_id, reason="owner_rejected", invalidated_by="owner")
    result = promotions.approve(proposed["token"])
    assert result["status"] == "expired"
    # Record body/id are preserved — no deletion on the failed confirm.
    records = service.read_records("owner_approved.md")
    assert records[0].frontmatter["id"] == record_id
    assert records[0].body.strip() == "A stable fact."


def test_public_canonical_confirmation_has_no_production_callers():
    """PermanentPromotionService is the sole production confirmation owner."""
    import ast
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    sources = [
        repo_root / "plugins/memory/memory_os/crystallized.py",
        repo_root / "plugins/memory/memory_os/owner_actions.py",
        repo_root / "plugins/memory/memory_os/permanent_promotion.py",
    ]
    offenders: list[str] = []
    for src in sources:
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "confirm_provisional_record"
            ):
                offenders.append(f"{src.name}:{node.lineno}")
    assert offenders == [], (
        f"public confirm_provisional_record called in production at {offenders}"
    )


# ── V2-0.5 reviewed-defect counterfactuals ──────────────────────────────


def test_idempotent_reproposal_returns_new_raw_token_without_revoking_previous(tmp_path):
    """Raw tokens are hash-only on disk, so a reminder issues an overlapping
    token; proposal CAS, not routine revocation, prevents double decisions."""
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

    service, record_id = _provisional_service(tmp_path)
    promotions = PermanentPromotionService(service.store)

    first = promotions.propose(record_id)
    second = promotions.propose(record_id)

    assert first["proposal_id"] == second["proposal_id"]
    assert first["token"].startswith("ppmt_")
    assert second["token"].startswith("ppmt_")
    assert second["token"] != first["token"]
    proposal = promotions.proposals._states()[first["proposal_id"]]
    assert promotions.tokens.validate(first["token"], proposal=proposal, current_body="A stable fact.")["status"] == "open"
    assert promotions.tokens.validate(second["token"], proposal=proposal, current_body="A stable fact.")["status"] == "open"


def test_token_consume_is_compare_and_set_under_concurrency(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from plugins.memory.memory_os.permanent_promotion import (
        PermanentPromotionError,
        ProposalLedger,
        TokenLedger,
    )

    root = tmp_path / "memory-os"
    proposal, _ = ProposalLedger(root).create_or_get(
        target_id="cry_1", candidate_id="cand_1", body="stable", channel="cli"
    )
    tokens = TokenLedger(root)
    token = tokens.issue(proposal, channel="cli")

    def consume_once():
        try:
            tokens.consume(token)
            return "consumed"
        except PermanentPromotionError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: consume_once(), range(2)))

    assert results.count("consumed") == 1
    assert results.count("token_consumed") == 1


def test_automatic_owner_digest_origin_is_audited_and_channel_allowed(tmp_path):
    from plugins.memory.memory_os.execution_gate import execution_gate_scope_hash, start_execution_gate_envelope
    from plugins.memory.memory_os.permanent_promotion import AutomaticWriteContext, ProposalLedger
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
    store.initialize()
    scope = {"operation": "test_owner_digest_proposal", "writes": ["proposal"]}
    permit = start_execution_gate_envelope(
        store,
        lane_id="permanent_promotion_producer",
        trigger_surface="test",
        risk_class="bounded_reversible_queue",
        human_approval_required=False,
        why_no_human_approval="test automatic proposal creation only",
        scope=scope,
        boundary={"actual_unapproved_crystallized_approval": False},
    )
    context = AutomaticWriteContext(
        store=store,
        envelope_id=permit["execution_gate_envelope_id"],
        scope_hash=execution_gate_scope_hash(scope),
    )

    proposal, created = ProposalLedger(store.roots.memory_os_root).create_or_get(
        target_id="cry_1",
        candidate_id="cand_1",
        body="stable",
        channel="owner_digest",
        origin="automatic",
        write_context=context,
    )

    assert created is True
    assert proposal["channel"] == "owner_digest"
    assert proposal["origin"] == "automatic"
    assert proposal["clearance"]["status"] == "unavailable"
    assert proposal["structural_write_governance"]["permit_status"] == "valid"


def test_reconcile_recovers_confirmed_target_as_approved_after_terminal_append_crash(tmp_path, monkeypatch):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

    service, record_id = _provisional_service(tmp_path)
    promotions = PermanentPromotionService(service.store)
    proposed = promotions.propose(record_id)

    original_append = promotions.proposals.append_terminal

    def crash_before_terminal(*_args, **_kwargs):
        raise OSError("synthetic terminal append crash")

    monkeypatch.setattr(promotions.proposals, "append_terminal", crash_before_terminal)
    with pytest.raises(OSError, match="synthetic terminal append crash"):
        promotions.approve(proposed["token"])

    monkeypatch.setattr(promotions.proposals, "append_terminal", original_append)
    report = PermanentPromotionService(service.store).reconcile()
    state = promotions.proposals._states()[proposed["proposal_id"]]
    frontmatter = service.read_records("owner_approved.md")[0].frontmatter

    assert report["approved_reconcile_count"] == 1
    assert state["status"] == "approved"
    assert frontmatter["permanent_promotion_proposal_id"] == proposed["proposal_id"]


def test_reconcile_closes_genuinely_retired_target_as_expired(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

    service, record_id = _provisional_service(tmp_path)
    promotions = PermanentPromotionService(service.store)
    proposed = promotions.propose(record_id)
    service.invalidate_provisional_record(
        record_id,
        reason="resolver_ttl_expired",
        invalidated_by="test",
    )

    report = promotions.reconcile()
    state = promotions.proposals._states()[proposed["proposal_id"]]

    assert report["target_retired_close_count"] == 1
    assert state["status"] == "expired"
    assert state["reason"] == "target_retired"


def test_private_canonical_confirmation_requires_service_capability(tmp_path):
    from plugins.memory.memory_os.crystallized import CrystallizedApprovalError

    service, record_id = _provisional_service(tmp_path)
    with pytest.raises(CrystallizedApprovalError, match="write capability"):
        service._confirm_provisional_record_from_permanent_service(
            record_id,
            proposal_id="ppm_" + "2" * 32,
            capability=object(),
        )


def test_confirm_and_retirement_share_one_canonical_transition(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

    service, record_id = _provisional_service(tmp_path)
    promotions = PermanentPromotionService(service.store)
    proposed = promotions.propose(record_id)

    def confirm():
        try:
            result = promotions.approve(proposed["token"])
            return ("confirm", bool(result["canonical_state_changed"]))
        except Exception as exc:  # one canonical contender may lose fail-closed
            return ("confirm_error", str(exc))

    def retire():
        try:
            result = service.invalidate_provisional_record(
                record_id,
                reason="resolver_ttl_expired",
                invalidated_by="test",
            )
            return ("retire", bool(result["canonical_state_changed"]))
        except Exception as exc:
            return ("retire_error", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(confirm), pool.submit(retire)]
        outcomes = [future.result() for future in results]

    changed = [value for _kind, value in outcomes if value is True]
    assert len(changed) == 1
    frontmatter = service.read_records("owner_approved.md")[0].frontmatter
    assert not (
        frontmatter.get("provisional") is False
        and frontmatter.get("canonical_state") == "provisional_expired"
    )


def test_decision_intent_recovers_when_process_crashes_before_token_consume(tmp_path, monkeypatch):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService, content_hash

    service, record_id = _provisional_service(tmp_path)
    promotions = PermanentPromotionService(service.store)
    proposed = promotions.propose(record_id)
    original = promotions.tokens._consume_hash_locked

    def crash_after_intent(*_args, **_kwargs):
        raise OSError("synthetic consume crash")

    monkeypatch.setattr(promotions.tokens, "_consume_hash_locked", crash_after_intent)
    with pytest.raises(OSError, match="synthetic consume crash"):
        promotions.approve(proposed["token"])

    monkeypatch.setattr(promotions.tokens, "_consume_hash_locked", original)
    report = PermanentPromotionService(service.store).reconcile()
    proposal = promotions.proposals._states()[proposed["proposal_id"]]
    token_state = promotions.tokens._states()[content_hash(proposed["token"])]

    assert report["decision_recovery_success_count"] == 1
    assert proposal["status"] == "approved"
    assert token_state["status"] == "consumed"


@pytest.mark.parametrize(
    ("action", "kwargs", "expected_status"),
    [
        ("reject", {}, "rejected"),
        ("defer", {"until": "2026-08-01T00:00:00Z"}, "deferred"),
    ],
)
def test_nonwrite_owner_decisions_recover_after_terminal_append_crash(
    tmp_path, monkeypatch, action, kwargs, expected_status
):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

    service, record_id = _provisional_service(tmp_path)
    promotions = PermanentPromotionService(service.store)
    proposed = promotions.propose(record_id)
    original = promotions.proposals.append_terminal

    def crash_before_terminal(*_args, **_kwargs):
        raise OSError("synthetic terminal crash")

    monkeypatch.setattr(promotions.proposals, "append_terminal", crash_before_terminal)
    with pytest.raises(OSError, match="synthetic terminal crash"):
        getattr(promotions, action)(proposed["token"], **kwargs)

    monkeypatch.setattr(promotions.proposals, "append_terminal", original)
    report = PermanentPromotionService(service.store).reconcile()
    proposal = promotions.proposals._states()[proposed["proposal_id"]]

    assert report["decision_recovery_success_count"] == 1
    assert proposal["status"] == expected_status
    assert service.read_records("owner_approved.md")[0].frontmatter["provisional"] is True


def test_multiple_overlapping_tokens_still_confirm_canonical_state_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from plugins.memory.memory_os.audit import read_audit_records
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

    service, record_id = _provisional_service(tmp_path)
    promotions = PermanentPromotionService(service.store)
    first = promotions.propose(record_id)
    second = promotions.propose(record_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(promotions.approve, [first["token"], second["token"]]))

    assert {result["status"] for result in results} == {"approved"}
    records = service.read_records("owner_approved.md")
    assert records[0].frontmatter["permanent_promotion_proposal_id"] == first["proposal_id"]
    audit = [
        record for record in read_audit_records(service.store.roots.audit_path)
        if record.get("action") == "provisional_record_confirmed"
    ]
    assert len(audit) == 1


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("User: remember the raw transcript", "forbidden_raw_transcript"),
        ("Deployment credential password=DO_NOT_STORE", "forbidden_secret_material"),
    ],
)
def test_single_eligibility_gate_blocks_forbidden_permanent_content(tmp_path, body, reason):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

    service, record_id = _provisional_service(tmp_path, body=body)
    report = service.collect_permanent_promotion_eligibility()
    proposed = PermanentPromotionService(service.store).propose(record_id)

    assert report["eligible_count"] == 0
    assert report["skipped_forbidden_content_count"] == 1
    assert proposed["status"] == "ineligible"
    assert reason in proposed.get("reason_codes", [])


def test_single_eligibility_gate_blocks_duplicate_existing_permanent_body(tmp_path):
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

    service, record_id = _provisional_service(tmp_path, body="Duplicated durable fact.")
    candidate = CrystallizedCandidate(
        "cand_permanent",
        "fact",
        "Duplicated durable fact.",
        ["evt_permanent"],
    )
    decision = ApprovalDecision(
        "cand_permanent",
        ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        "owner",
        "2026-06-02T00:00:00Z",
    )
    service.write_approved_record(candidate, decision, file_name="existing_permanent.md")

    report = service.collect_permanent_promotion_eligibility()
    proposed = PermanentPromotionService(service.store).propose(record_id)

    assert report["eligible_count"] == 0
    assert report["skipped_permanent_duplicate_count"] == 1
    assert proposed == {"status": "ineligible", "reason_codes": ["permanent_duplicate"]}


# ── N1: expired-token sweep gives the token ledger a `revoked` producer and
# stops "nominally open, actually expired" tokens accumulating forever. Only
# already-expired open tokens are swept, so a still-valid older token that the
# owner may reply to remains usable. ───────────────────────────────────────────


def test_sweep_expired_revokes_only_expired_open_tokens(tmp_path):
    from datetime import datetime, timedelta, timezone

    from plugins.memory.memory_os.permanent_promotion import (
        ProposalLedger,
        TokenLedger,
        content_hash,
    )

    root = tmp_path / "memory-os"
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    proposal, _ = ProposalLedger(root, clock=lambda: now).create_or_get(
        target_id="cry_1", candidate_id="cand_1", body="one", channel="cli"
    )
    tokens = TokenLedger(root, clock=lambda: now)
    expired = tokens.issue(proposal, channel="cli", expires_at=now - timedelta(seconds=1))
    valid = tokens.issue(proposal, channel="cli", expires_at=now + timedelta(hours=48))

    report = tokens.sweep_expired(now=now)

    assert report["expired_token_swept_count"] == 1
    states = tokens._states()
    assert states[content_hash(expired)]["status"] == "revoked"
    assert states[content_hash(expired)]["reason"] == "token_expired_sweep"
    # The still-valid token is left untouched (async reply UX preserved).
    assert states[content_hash(valid)]["status"] == "open"


def test_reconcile_sweeps_expired_open_tokens(tmp_path):
    from datetime import datetime, timedelta, timezone

    from plugins.memory.memory_os.permanent_promotion import (
        PermanentPromotionError,
        PermanentPromotionService,
        content_hash,
    )

    service, record_id = _provisional_service(tmp_path)
    base = datetime(2026, 7, 10, tzinfo=timezone.utc)
    promotions = PermanentPromotionService(service.store, clock=lambda: base)
    proposed = promotions.propose(record_id)

    later = base + timedelta(hours=49)
    report = PermanentPromotionService(service.store, clock=lambda: later).reconcile()

    assert report["expired_token_swept_count"] == 1
    token_state = promotions.tokens._states()[content_hash(proposed["token"])]
    assert token_state["status"] == "revoked"
    assert token_state["reason"] == "token_expired_sweep"
    # Proposal itself stays open (owner never acted; target still provisional).
    assert promotions.proposals._states()[proposed["proposal_id"]]["status"] == "open"
    # The swept token now fails closed as revoked, not merely expired.
    proposal_state = promotions.proposals._states()[proposed["proposal_id"]]
    record = service.read_records("owner_approved.md")[0]
    with pytest.raises(PermanentPromotionError, match="token_revoked"):
        PermanentPromotionService(service.store, clock=lambda: later).tokens.validate(
            proposed["token"], proposal=proposal_state, current_body=record.body
        )


# ── N3: producer must not over-capture body beyond the digest render gate.
# render (_render_review_item) re-bounds proposed_memory to 1000 chars, so a
# 4000-char slice in the producer is dead weight that also lands in the local
# delivery ledger under raw_body_included=False. Align the producer to the gate.


def test_delivery_items_bound_proposed_memory_to_render_gate(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import (
        prepare_permanent_promotion_delivery,
        preview_permanent_promotion_delivery,
    )

    long_body = "sensitive canonical detail. " * 400  # > 4000 chars
    service, _record_id = _provisional_service(tmp_path, body=long_body)

    preview = preview_permanent_promotion_delivery(service.store)
    prepared = prepare_permanent_promotion_delivery(service.store, delivery_ref="d1")

    items = list(preview.get("items") or []) + list(prepared.get("items") or [])
    assert items, "expected at least one permanent-promotion delivery item"
    for item in items:
        assert len(item["proposed_memory"]) <= 1000
        assert len(item["summary"]) <= 1000


# ── V2-E E5: clearance receipt wiring ────────────────────────────────────────


class _FakeRootsForClearance:
    """Minimal roots that exposes the system directory for receipt writes."""

    def __init__(self, tmp_path: Path) -> None:
        self.memory_os_root = tmp_path / "memory-os"
        (self.memory_os_root / "system").mkdir(parents=True, exist_ok=True)
        self.hermes_home = tmp_path
        self.profile = "default"


def _write_clearance(roots: Any, record_id: str, verdict: str,
                     *, conflict_refs: list[str] | None = None,
                     receipt_id: str | None = None,
                     corpus_watermark: int = 0,
                     content_hash: str = "") -> str:
    """Helper: write a single active clearance receipt and return its receipt_id."""
    from plugins.memory.memory_os.clearance_receipts import (
        ClearanceReceipt, write_clearance_receipt,
    )

    rid = receipt_id or f"clr_test_{record_id}"
    ch = content_hash or f"test_hash_{record_id}"  # unique per record to avoid idempotency collision
    receipt = ClearanceReceipt(
        receipt_id=rid,
        record_id=record_id,
        content_hash=ch,
        verdict=verdict,
        conflict_refs=list(conflict_refs or []),
        corpus_watermark=corpus_watermark,
        judge_version="test_v1",
        judged_at="2026-07-11T00:00:00Z",
    )
    write_clearance_receipt(roots, receipt)
    return rid


class TestV2EClearanceWiringUnit:
    """E.1/E.2/E.3 — _resolve_clearance_for_proposal constitution matrix."""

    def test_clear_verdict_allows_automatic(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, "prov_1", "clear")
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_1", "automatic", v2e_enabled=True,
        )
        assert block is None
        assert clearance is not None
        assert clearance["status"] == "clear"
        assert clearance["receipt_id"] == "clr_test_prov_1"

    def test_clear_verdict_allows_owner(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, "prov_2", "clear")
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_2", "owner_initiated", v2e_enabled=True,
        )
        assert block is None
        assert clearance["status"] == "clear"

    def test_conflict_verdict_blocks_automatic_with_contested(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, "prov_3", "conflict", conflict_refs=["perm_A", "perm_B"])
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_3", "automatic", v2e_enabled=True,
        )
        assert block == "clearance_conflict"
        assert clearance is not None
        assert clearance["status"] == "conflict"
        assert clearance["contested"] is True
        assert set(clearance["conflict_refs"]) == {"perm_A", "perm_B"}

    def test_conflict_verdict_allows_owner_with_override(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, "prov_4", "conflict", conflict_refs=["perm_C"])
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_4", "owner_initiated", v2e_enabled=True,
        )
        assert block is None
        assert clearance["status"] == "conflict"
        assert clearance["owner_override"] is True
        assert "contested" not in clearance

    def test_unknown_verdict_blocks_automatic(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, "prov_5", "unknown")
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_5", "automatic", v2e_enabled=True,
        )
        assert block == "clearance_unknown"
        assert clearance["status"] == "unknown"

    def test_unknown_verdict_blocks_owner(self, tmp_path: Path) -> None:
        """Constitution matrix: unknown blocks both automatic AND owner."""
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, "prov_6", "unknown")
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_6", "owner_initiated", v2e_enabled=True,
        )
        assert block == "clearance_unknown"

    def test_no_receipt_blocks_both_paths(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        clearance, block = _resolve_clearance_for_proposal(
            roots, "no_such_record", "automatic", v2e_enabled=True,
        )
        assert block == "no_clearance_receipt"
        assert clearance["status"] == "unavailable"

        clearance, block = _resolve_clearance_for_proposal(
            roots, "no_such_record", "owner_initiated", v2e_enabled=True,
        )
        assert block == "no_clearance_receipt"

    def test_v2e_disabled_bypasses_all_gating(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        # Even with a conflict receipt, v2e_enabled=False returns no gating
        _write_clearance(roots, "prov_7", "conflict", conflict_refs=["perm_D"])
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_7", "automatic", v2e_enabled=False,
        )
        assert block is None
        assert clearance is None  # None → caller uses default

    def test_invalidated_receipt_treated_as_no_receipt(self, tmp_path: Path) -> None:
        """An invalidated receipt is not active — treated as missing."""
        from plugins.memory.memory_os.clearance_receipts import (
            ClearanceReceipt, write_clearance_receipt,
        )
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        receipt = ClearanceReceipt(
            receipt_id="clr_invalidated",
            record_id="prov_8",
            content_hash="test",
            verdict="clear",
            judge_version="v1",
            judged_at="2026-07-11T00:00:00Z",
            invalidated_at="2026-07-11T01:00:00Z",
            invalidated_by="entity_scoped",
        )
        write_clearance_receipt(roots, receipt)
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_8", "automatic", v2e_enabled=True,
        )
        assert block == "no_clearance_receipt"

    def test_only_active_receipt_for_specific_record_id_matches(self, tmp_path: Path) -> None:
        """Receipts for other records must not interfere."""
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, "prov_A", "conflict")
        _write_clearance(roots, "prov_B", "clear")
        # prov_C has no receipt
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_B", "automatic", v2e_enabled=True,
        )
        assert block is None
        assert clearance["status"] == "clear"


class TestV2EClearanceWiringIntegration:
    """E5 producer integration — prepare_permanent_promotion_delivery + propose."""

    def test_automatic_delivery_skips_conflict_record(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import (
            prepare_permanent_promotion_delivery,
        )
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        candidate = CrystallizedCandidate("cand_int_1", "fact", "Integration test fact.", ["evt_1"])
        decision = ApprovalDecision(
            "cand_int_1", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
            "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-09-01T00:00:00Z",
        )
        svc = CrystallizedMemoryService(store)
        svc.write_approved_record(candidate, decision, file_name="integration.md")
        record_id = svc.read_records("integration.md")[0].frontmatter["id"]

        # Write a conflict receipt for this record
        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, record_id, "conflict", conflict_refs=["perm_X"])

        # v2e_enabled=False (default): should still work (no gating)
        report_off = prepare_permanent_promotion_delivery(
            store, delivery_ref="d_off",
        )
        assert report_off["status"] in ("ok", "partial")
        # With v2e off, clearance is not checked
        assert report_off.get("clearance_blocked_count", 0) == 0

    def test_owner_propose_blocks_on_unknown(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import (
            PermanentPromotionError,
            PermanentPromotionService,
        )
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        candidate = CrystallizedCandidate("cand_own_1", "fact", "Owner test fact.", ["evt_1"])
        decision = ApprovalDecision(
            "cand_own_1", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
            "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-09-01T00:00:00Z",
        )
        svc = CrystallizedMemoryService(store)
        svc.write_approved_record(candidate, decision, file_name="owner_test.md")
        record_id = svc.read_records("owner_test.md")[0].frontmatter["id"]

        # Write an unknown receipt
        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, record_id, "unknown")

        # Owner propose with v2e enabled → blocked
        from datetime import datetime, timezone
        service = PermanentPromotionService(
            store, clock=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
            v2e_enabled=True,
        )
        with pytest.raises(PermanentPromotionError, match="clearance_unknown"):
            service.propose(record_id, origin="owner_initiated")

    def test_owner_propose_allows_clear(self, tmp_path: Path) -> None:
        from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        candidate = CrystallizedCandidate("cand_own_2", "fact", "Owner clear fact.", ["evt_1"])
        decision = ApprovalDecision(
            "cand_own_2", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
            "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-09-01T00:00:00Z",
        )
        svc = CrystallizedMemoryService(store)
        svc.write_approved_record(candidate, decision, file_name="owner_clear.md")
        record_id = svc.read_records("owner_clear.md")[0].frontmatter["id"]

        # Write a clear receipt
        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, record_id, "clear")

        from datetime import datetime, timezone
        service = PermanentPromotionService(
            store, clock=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
            v2e_enabled=True,
        )
        result = service.propose(record_id, origin="owner_initiated")
        assert result["status"] == "open"
        assert result["proposal_id"].startswith("ppm_")

    def test_owner_propose_allows_conflict_with_override(self, tmp_path: Path) -> None:
        """Owner can override a conflict verdict (owner_override flag set)."""
        from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        candidate = CrystallizedCandidate("cand_own_3", "fact", "Owner conflict fact.", ["evt_2"])
        decision = ApprovalDecision(
            "cand_own_3", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
            "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-09-01T00:00:00Z",
        )
        svc = CrystallizedMemoryService(store)
        svc.write_approved_record(candidate, decision, file_name="owner_conflict.md")
        record_id = svc.read_records("owner_conflict.md")[0].frontmatter["id"]

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, record_id, "conflict", conflict_refs=["perm_Y"])

        from datetime import datetime, timezone
        service = PermanentPromotionService(
            store, clock=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
            v2e_enabled=True,
        )
        result = service.propose(record_id, origin="owner_initiated")
        assert result["status"] == "open"
        # Verify the clearance in the proposal has owner_override
        proposal_state = service.proposals._states()[result["proposal_id"]]
        assert proposal_state["clearance"]["status"] == "conflict"
        assert proposal_state["clearance"]["owner_override"] is True

    def test_explicit_clearance_passed_by_caller_is_not_overridden(self, tmp_path: Path) -> None:
        """When caller explicitly passes clearance, don't query receipts."""
        from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        candidate = CrystallizedCandidate("cand_exp_1", "fact", "Explicit clearance fact.", ["evt_3"])
        decision = ApprovalDecision(
            "cand_exp_1", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
            "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-09-01T00:00:00Z",
        )
        svc = CrystallizedMemoryService(store)
        svc.write_approved_record(candidate, decision, file_name="explicit.md")
        record_id = svc.read_records("explicit.md")[0].frontmatter["id"]

        # Write a conflict receipt (should be ignored because caller passes explicit clearance)
        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, record_id, "conflict", conflict_refs=["perm_Z"])

        from datetime import datetime, timezone
        service = PermanentPromotionService(
            store, clock=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
            v2e_enabled=True,
        )
        result = service.propose(
            record_id, origin="owner_initiated",
            clearance={"status": "clear", "receipt_id": "explicit_override"},
        )
        assert result["status"] == "open"
        proposal_state = service.proposals._states()[result["proposal_id"]]
        assert proposal_state["clearance"]["status"] == "clear"
        assert proposal_state["clearance"]["receipt_id"] == "explicit_override"

    def test_v2e_disabled_owner_propose_no_gating(self, tmp_path: Path) -> None:
        """With v2e_enabled=False, no clearance resolution occurs."""
        from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        candidate = CrystallizedCandidate("cand_off_1", "fact", "V2E off fact.", ["evt_9"])
        decision = ApprovalDecision(
            "cand_off_1", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
            "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-09-01T00:00:00Z",
        )
        svc = CrystallizedMemoryService(store)
        svc.write_approved_record(candidate, decision, file_name="v2e_off.md")
        record_id = svc.read_records("v2e_off.md")[0].frontmatter["id"]

        # Write a conflict receipt — should be ignored when v2e_enabled=False
        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, record_id, "conflict")

        from datetime import datetime, timezone
        service = PermanentPromotionService(
            store, clock=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
            v2e_enabled=False,
        )
        result = service.propose(record_id, origin="owner_initiated")
        assert result["status"] == "open"
        # With v2e disabled, clearance is default "unavailable"
        proposal_state = service.proposals._states()[result["proposal_id"]]
        assert proposal_state["clearance"]["status"] == "unavailable"


# ── X.4: branch-by-branch poison tests ───────────────────────────────────────


def _minimal_write_context(tmp_path: Path) -> Any:
    """Build a valid AutomaticWriteContext with a real execution gate envelope."""
    from plugins.memory.memory_os.execution_gate import (
        execution_gate_scope_hash,
        start_execution_gate_envelope,
    )
    from plugins.memory.memory_os.permanent_promotion import (
        PERMANENT_PROMOTION_LANE_ID,
        PERMANENT_PROMOTION_RISK_CLASS,
        AutomaticWriteContext,
    )
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
    store.initialize()
    scope = {"operation": "test_gate_232", "test": True}
    permit = start_execution_gate_envelope(
        store,
        lane_id=PERMANENT_PROMOTION_LANE_ID,
        trigger_surface="test",
        risk_class=PERMANENT_PROMOTION_RISK_CLASS,
        human_approval_required=False,
        why_no_human_approval="test only — no human review needed",
        scope=scope,
        boundary={"actual_send": False, "actual_execute": False},
    )
    return AutomaticWriteContext(
        store=store,
        envelope_id=str(permit["execution_gate_envelope_id"]),
        scope_hash=execution_gate_scope_hash(scope),
    )


class TestV2EX4Poison:
    """X.4 — each constitution-matrix branch exercised with edge cases."""

    def test_gate_232_raises_on_automatic_with_non_clear_verdict(self, tmp_path: Path) -> None:
        """:232 gate: automatic + v2e_enabled + non-clear → raises automatic_clearance_required."""
        from plugins.memory.memory_os.permanent_promotion import (
            PermanentPromotionError,
            ProposalLedger,
        )

        ledger = ProposalLedger(tmp_path / "memory-os")
        wctx = _minimal_write_context(tmp_path)
        with pytest.raises(PermanentPromotionError, match="automatic_clearance_required"):
            ledger.create_or_get(
                target_id="cry_gate_1", candidate_id="cand_gate_1",
                body="gate test body", channel="cli", origin="automatic",
                clearance={"status": "conflict", "receipt_id": "clr_X"},
                v2e_enabled=True,
                write_context=wctx,
            )

    def test_gate_232_allows_automatic_with_clear(self, tmp_path: Path) -> None:
        """:232 gate: automatic + v2e_enabled + clear → proposal created."""
        from plugins.memory.memory_os.permanent_promotion import ProposalLedger

        ledger = ProposalLedger(tmp_path / "memory-os")
        wctx = _minimal_write_context(tmp_path)
        proposal, created = ledger.create_or_get(
            target_id="cry_gate_2", candidate_id="cand_gate_2",
            body="clear gate body", channel="cli", origin="automatic",
            clearance={"status": "clear", "receipt_id": "clr_clear_1"},
            v2e_enabled=True,
            write_context=wctx,
        )
        assert created is True
        assert proposal["clearance"]["status"] == "clear"
        assert proposal["clearance"]["receipt_id"] == "clr_clear_1"

    def test_gate_232_blocks_automatic_with_unknown(self, tmp_path: Path) -> None:
        """:232 gate: automatic + v2e_enabled + unknown → blocked."""
        from plugins.memory.memory_os.permanent_promotion import (
            PermanentPromotionError, ProposalLedger,
        )

        ledger = ProposalLedger(tmp_path / "memory-os")
        wctx = _minimal_write_context(tmp_path)
        with pytest.raises(PermanentPromotionError, match="automatic_clearance_required"):
            ledger.create_or_get(
                target_id="cry_gate_3", candidate_id="cand_gate_3",
                body="unknown gate body", channel="cli", origin="automatic",
                clearance={"status": "unknown", "receipt_id": "clr_U"},
                v2e_enabled=True,
                write_context=wctx,
            )

    def test_gate_232_bypassed_when_v2e_disabled(self, tmp_path: Path) -> None:
        """:232 gate: skipped when v2e_enabled=False regardless of verdict."""
        from plugins.memory.memory_os.permanent_promotion import ProposalLedger

        ledger = ProposalLedger(tmp_path / "memory-os")
        wctx = _minimal_write_context(tmp_path)
        # Even conflict passes when v2e is off
        proposal, created = ledger.create_or_get(
            target_id="cry_gate_4", candidate_id="cand_gate_4",
            body="v2e off body", channel="cli", origin="automatic",
            clearance={"status": "conflict", "receipt_id": "clr_off_1"},
            v2e_enabled=False,
            write_context=wctx,
        )
        assert created is True
        # Clearance stored as-is, gate not applied
        assert proposal["clearance"]["status"] == "conflict"

    def test_gate_232_bypassed_for_owner_origin(self, tmp_path: Path) -> None:
        """:232 gate: only applies to automatic origin, not owner_initiated."""
        from plugins.memory.memory_os.permanent_promotion import ProposalLedger

        ledger = ProposalLedger(tmp_path / "memory-os")
        # Owner-initiated with conflict + v2e → still allowed (gate only for automatic)
        proposal, created = ledger.create_or_get(
            target_id="cry_gate_5", candidate_id="cand_gate_5",
            body="owner conflict body", channel="cli", origin="owner_initiated",
            clearance={"status": "conflict", "receipt_id": "clr_owner", "owner_override": True},
            v2e_enabled=True,
        )
        assert created is True
        assert proposal["clearance"]["owner_override"] is True

    def test_resolve_unexpected_verdict_blocked(self, tmp_path: Path) -> None:
        """Defensive branch: a receipt with an unrecognized verdict blocks."""
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, "prov_bogus", "bogus_verdict")
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_bogus", "automatic", v2e_enabled=True,
        )
        assert block == "unexpected_verdict"
        assert clearance["status"] == "unavailable"
        assert clearance["raw_verdict"] == "bogus_verdict"

    def test_resolve_unexpected_verdict_blocks_owner_too(self, tmp_path: Path) -> None:
        """Defensive branch: unexpected verdict blocks owner path as well."""
        from plugins.memory.memory_os.permanent_promotion import (
            _resolve_clearance_for_proposal,
        )

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, "prov_bogus2", "bogus_verdict")
        clearance, block = _resolve_clearance_for_proposal(
            roots, "prov_bogus2", "owner_initiated", v2e_enabled=True,
        )
        assert block == "unexpected_verdict"

    def test_clearance_receipt_id_flows_into_proposal_record(self, tmp_path: Path) -> None:
        """Receipt ID survives the full chain: resolve → create_or_get → proposal record."""
        from plugins.memory.memory_os.permanent_promotion import (
            PermanentPromotionService,
        )
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from datetime import datetime, timezone

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        candidate = CrystallizedCandidate("cand_flow_1", "fact", "Flow-through test.", ["evt_f1"])
        decision = ApprovalDecision(
            "cand_flow_1", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
            "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-09-01T00:00:00Z",
        )
        svc = CrystallizedMemoryService(store)
        svc.write_approved_record(candidate, decision, file_name="flow_test.md")
        record_id = svc.read_records("flow_test.md")[0].frontmatter["id"]

        # Write a clear receipt with a known receipt_id
        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, record_id, "clear", receipt_id="clr_flow_known_42")

        service = PermanentPromotionService(
            store, clock=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
            v2e_enabled=True,
        )
        result = service.propose(record_id, origin="owner_initiated")
        assert result["status"] == "open"
        proposal_state = service.proposals._states()[result["proposal_id"]]
        assert proposal_state["clearance"]["status"] == "clear"
        assert proposal_state["clearance"]["receipt_id"] == "clr_flow_known_42"

    def test_conflict_receipt_refs_flow_into_proposal(self, tmp_path: Path) -> None:
        """Conflict refs survive the full chain into the proposal record."""
        from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from datetime import datetime, timezone

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        candidate = CrystallizedCandidate("cand_cfref_1", "fact", "Conflict refs test.", ["evt_cf1"])
        decision = ApprovalDecision(
            "cand_cfref_1", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
            "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-09-01T00:00:00Z",
        )
        svc = CrystallizedMemoryService(store)
        svc.write_approved_record(candidate, decision, file_name="cfref_test.md")
        record_id = svc.read_records("cfref_test.md")[0].frontmatter["id"]

        roots = _FakeRootsForClearance(tmp_path)
        _write_clearance(roots, record_id, "conflict",
                         conflict_refs=["perm_AAA", "perm_BBB"],
                         receipt_id="clr_conflict_refs_99")

        service = PermanentPromotionService(
            store, clock=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
            v2e_enabled=True,
        )
        result = service.propose(record_id, origin="owner_initiated")
        assert result["status"] == "open"
        proposal_state = service.proposals._states()[result["proposal_id"]]
        assert proposal_state["clearance"]["status"] == "conflict"
        assert proposal_state["clearance"]["owner_override"] is True
        assert set(proposal_state["clearance"]["conflict_refs"]) == {"perm_AAA", "perm_BBB"}


def test_ledger_counts_stale_open_evaluation_failure_is_reported_not_swallowed(tmp_path, monkeypatch):
    """Counterfactual (P1 #4): when the stale-open evaluation raises, the
    broad except used to swallow the exception class entirely — the count
    silently regressed to 0 while the section still looked collected. The
    failure must surface as an explicit status plus the exception class name
    (the bounded error record for this path)."""
    import json

    from plugins.memory.memory_os import crystallized as crystallized_module
    from plugins.memory.memory_os.permanent_promotion import read_permanent_promotion_ledger_counts

    system = tmp_path / "memory-os" / "system"
    system.mkdir(parents=True)
    (system / "permanent_promotion_proposals.jsonl").write_text(
        json.dumps({
            "proposal_id": "ppm_stale",
            "status": "open",
            "target_id": "cry_missing",
            "content_hash": "h1",
        }) + "\n",
        encoding="utf-8",
    )

    # Healthy baseline: the open proposal's target record does not exist, so
    # the evaluation runs and reports one genuinely stale open proposal.
    healthy = read_permanent_promotion_ledger_counts(tmp_path / "memory-os")
    assert healthy["stale_open_proposal_count"] == 1
    assert healthy["stale_open_evaluation_status"] == "ok"
    assert healthy["stale_open_evaluation_error_code"] == ""

    class ExplodingCrystallizedService:
        def __init__(self, store):
            raise RuntimeError("crystallized store unreadable")

    monkeypatch.setattr(
        crystallized_module, "CrystallizedMemoryService", ExplodingCrystallizedService
    )

    counts = read_permanent_promotion_ledger_counts(tmp_path / "memory-os")

    # The stale count silently regresses to 0 (evaluation never ran) — which
    # is exactly why the failure must be visible, never swallowed.
    assert counts["stale_open_proposal_count"] == 0
    assert counts["stale_open_evaluation_status"] == "unavailable"
    assert counts["stale_open_evaluation_error_code"] == "RuntimeError"


def test_ledger_counts_tolerate_historical_recovery_summary_missing_keys(tmp_path):
    """Counterfactual (P1 #6): a historical permanent_promotion_producer
    completion envelope whose result_summary carries
    decision_recovery_attempt_count but lacks (or None-values) the
    success/failure keys must yield ints, not an int(None) TypeError."""
    import json

    from plugins.memory.memory_os.permanent_promotion import read_permanent_promotion_ledger_counts

    system = tmp_path / "memory-os" / "system"
    system.mkdir(parents=True)
    envelopes = system / "execution_gate_envelopes.jsonl"
    envelopes.write_text(
        json.dumps({
            "stage": "completion",
            "lane_id": "permanent_promotion_producer",
            "result_summary": {"decision_recovery_attempt_count": 3},
        }) + "\n",
        encoding="utf-8",
    )

    counts = read_permanent_promotion_ledger_counts(tmp_path / "memory-os")

    assert counts["decision_recovery_attempt_count"] == 3
    assert counts["decision_recovery_success_count"] == 0
    assert counts["decision_recovery_failure_count"] == 0

    # None-valued keys (another historical row shape) must degrade to 0 too.
    envelopes.write_text(
        json.dumps({
            "stage": "completion",
            "lane_id": "permanent_promotion_producer",
            "result_summary": {
                "decision_recovery_attempt_count": None,
                "decision_recovery_success_count": None,
                "decision_recovery_failure_count": None,
            },
        }) + "\n",
        encoding="utf-8",
    )

    counts = read_permanent_promotion_ledger_counts(tmp_path / "memory-os")

    assert counts["decision_recovery_attempt_count"] == 0
    assert counts["decision_recovery_success_count"] == 0
    assert counts["decision_recovery_failure_count"] == 0


def test_ledger_counts_malformed_lines_are_suppressed_not_fatal(tmp_path):
    """Counterfactual (P3 #11): read_permanent_promotion_ledger_counts reads
    ledger files through jsonl_io.read_jsonl_result, which returns bounded
    error records for malformed/non-object lines instead of raising or
    silently dropping them. A ledger file with malformed lines mixed in
    with valid ones must: (a) still count the valid lines, (b) not raise,
    and (c) surface the suppressed-line count via
    ledger_read_suppressed_error_count so a partially-bad ledger is
    distinguishable from a verified-clean read."""
    import json

    from plugins.memory.memory_os.permanent_promotion import read_permanent_promotion_ledger_counts

    system = tmp_path / "memory-os" / "system"
    system.mkdir(parents=True)
    (system / "permanent_promotion_proposals.jsonl").write_text(
        "\n".join([
            json.dumps({"proposal_id": "ppm_valid_1", "status": "open", "target_id": "cry_1", "content_hash": "h1"}),
            "{not valid json",
            "[1, 2, 3]",
            json.dumps({"proposal_id": "ppm_valid_2", "status": "rejected"}),
        ]) + "\n",
        encoding="utf-8",
    )

    counts = read_permanent_promotion_ledger_counts(tmp_path / "memory-os")

    # Valid lines are counted despite the malformed/non-object lines sharing the file.
    assert counts["proposal_ledger_counts"]["open"] == 1
    assert counts["proposal_ledger_counts"]["rejected"] == 1
    # The malformed line and the non-object line are both bounded, suppressed errors.
    assert counts["ledger_read_suppressed_error_count"] >= 2


def test_ledger_counts_stale_open_loop_uses_index_for_multiple_proposals(tmp_path):
    """Equivalence (P3 #13): the stale-open evaluation builds a single
    id -> record index (reproducing crystallized.find_record's sorted
    file order / first-match-per-id semantics) instead of calling
    find_record() once per open proposal. With two open proposals -- one
    whose target record exists, is provisional, active, and
    content-hash-matches (fresh), and one whose target record does not
    exist at all (stale) -- the index-based lookup must still classify
    exactly one of the two as stale."""
    import json

    from plugins.memory.memory_os.permanent_promotion import (
        content_hash,
        read_permanent_promotion_ledger_counts,
    )

    service, record_id = _provisional_service(tmp_path, body="A stable fact.", candidate_id="cand_fresh")
    record = service.read_records("owner_approved.md")[0]
    fresh_hash = content_hash(record.body)

    system = tmp_path / "memory-os" / "system"
    system.mkdir(parents=True, exist_ok=True)
    (system / "permanent_promotion_proposals.jsonl").write_text(
        "\n".join([
            json.dumps({
                "proposal_id": "ppm_fresh",
                "status": "open",
                "target_id": record_id,
                "content_hash": fresh_hash,
            }),
            json.dumps({
                "proposal_id": "ppm_stale",
                "status": "open",
                "target_id": "cry_does_not_exist",
                "content_hash": "irrelevant",
            }),
        ]) + "\n",
        encoding="utf-8",
    )

    counts = read_permanent_promotion_ledger_counts(tmp_path / "memory-os")

    assert counts["open_proposal_backlog_count"] == 2
    assert counts["stale_open_proposal_count"] == 1
    assert counts["stale_open_evaluation_status"] == "ok"
    assert counts["stale_open_evaluation_error_code"] == ""


def test_reproposal_of_approved_content_raises_typed_error_and_writes_absorption_audit(tmp_path):
    # Counterfactual (analysis-doc D2): the approved branch must surface the
    # typed ``content_already_permanent`` error the sweep handler absorbs and
    # land the B6 absorption-audit row. Without the fix the branch evaluates
    # ``self.store.roots`` — an attribute ProposalLedger never had — and the
    # sweep's ``except PermanentPromotionError`` can never catch what it throws.
    import json

    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionError, ProposalLedger

    root = tmp_path / "memory-os"
    ledger = ProposalLedger(root)
    proposal, created = ledger.create_or_get(
        target_id="cry_1", candidate_id="cand_1", body="stable body", channel="cli",
    )
    assert created
    with ledger.proposals_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "proposal_id": proposal["proposal_id"],
            "status": "approved",
            "updated_at": "2026-08-05T00:00:00Z",
        }) + "\n")

    with pytest.raises(PermanentPromotionError, match="content_already_permanent"):
        ledger.create_or_get(
            target_id="cry_1", candidate_id="cand_1", body="stable body", channel="cli",
        )

    audit_path = root / "system" / "absorption_audit.jsonl"
    assert audit_path.exists()
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["schema_version"] == "memory-os.absorption_audit.v0"
    assert rows[0]["target_permanent_id"] == "cry_1"
    assert rows[0]["similarity_basis"] == "exact_content_hash_match"
