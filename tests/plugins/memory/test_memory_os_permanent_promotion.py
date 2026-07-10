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

    # Promote-once: the burned token cannot drive a second permanent write.
    with pytest.raises(PermanentPromotionError, match="token_consumed|proposal_closed"):
        pps.approve(token)


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
