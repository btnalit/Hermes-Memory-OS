"""V2-0 permanent-promotion public contract tests (Task 1)."""
from __future__ import annotations

import re

import pytest


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
    with pytest.raises(Exception, match="proposal authorization"):
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
    with pytest.raises(CrystallizedApprovalError, match="proposal authorization"):
        service.confirm_provisional_record(record_id, confirmed_by="auto_promote")


def test_confirm_authorization_target_mismatch_is_rejected(tmp_path):
    from plugins.memory.memory_os.crystallized import CrystallizedApprovalError
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionAuthorization

    service, record_id = _provisional_service(tmp_path)
    wrong = PermanentPromotionAuthorization(
        proposal_id="ppm_" + "0" * 32, target_id="cry_wrong_target", token_hash="deadbeef",
    )
    with pytest.raises(CrystallizedApprovalError, match="target mismatch"):
        service.confirm_provisional_record(record_id, authorization=wrong)


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


def test_confirm_inactive_record_fails_closed_evidence_increment(tmp_path):
    from plugins.memory.memory_os.crystallized import CrystallizedApprovalError
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionAuthorization

    service, record_id = _provisional_service(tmp_path)
    # Owner-reject → canonical_state=provisional_rejected (provisional flag kept).
    service.invalidate_provisional_record(record_id, reason="owner_rejected", invalidated_by="owner")
    auth = PermanentPromotionAuthorization(
        proposal_id="ppm_" + "0" * 32, target_id=record_id, token_hash="deadbeef",
    )
    with pytest.raises(CrystallizedApprovalError, match="evidence_increment_unavailable"):
        service.confirm_provisional_record(record_id, authorization=auth)
    # Record body/id are preserved — no deletion on the failed confirm.
    records = service.read_records("owner_approved.md")
    assert records[0].frontmatter["id"] == record_id
    assert records[0].body.strip() == "A stable fact."


def test_all_confirm_provisional_record_callers_pass_authorization():
    """Every production caller of confirm_provisional_record must bind an
    authorization object. This is the AST guard for D-3 (Task 4)."""
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
                if "authorization" not in {kw.arg for kw in node.keywords}:
                    offenders.append(f"{src.name}:{node.lineno}")
    assert offenders == [], (
        f"confirm_provisional_record called without authorization= at {offenders}"
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


def test_confirm_is_idempotent_only_for_same_permanent_proposal(tmp_path):
    from plugins.memory.memory_os.crystallized import CrystallizedApprovalError
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionAuthorization

    service, record_id = _provisional_service(tmp_path)
    first = PermanentPromotionAuthorization(
        proposal_id="ppm_" + "1" * 32,
        target_id=record_id,
        token_hash="first",
    )
    second = PermanentPromotionAuthorization(
        proposal_id="ppm_" + "2" * 32,
        target_id=record_id,
        token_hash="second",
    )

    applied = service.confirm_provisional_record(record_id, authorization=first)
    duplicate = service.confirm_provisional_record(record_id, authorization=first)
    assert applied["canonical_state_changed"] is True
    assert duplicate["canonical_state_changed"] is False
    with pytest.raises(CrystallizedApprovalError, match="different permanent proposal"):
        service.confirm_provisional_record(record_id, authorization=second)


def test_confirm_and_retirement_share_one_canonical_transition(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionAuthorization

    service, record_id = _provisional_service(tmp_path)
    authorization = PermanentPromotionAuthorization(
        proposal_id="ppm_" + "3" * 32,
        target_id=record_id,
        token_hash="token",
    )

    def confirm():
        try:
            result = service.confirm_provisional_record(record_id, authorization=authorization)
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
    assert proposed == {"status": "ineligible", "reason_codes": [reason]}


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
