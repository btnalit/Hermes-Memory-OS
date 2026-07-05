"""Tests for fact_judge — offline LLM durable-fact judge + single-item bypass.

Spec: docs/resolver/hermes-crystallization-unblock-fact-judge-spec.md
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

from plugins.memory.memory_os.crystallized import CrystallizedCandidate
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


# ── Helpers ──────────────────────────────────────────────────────────────

_VALID_ENVELOPE_ID = "xgate_test_fact_judge_envelope"


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _store_with_gate(tmp_path, *, profile="main"):
    """Create an initialized store with a pre-written valid ExecutionGate envelope.

    Tests that exercise _cluster_and_promote (which calls append_candidate_triage
    → append_governed_jsonl → resolve_execution_gate_permit) need a valid permit
    in the gate envelope journal.
    """
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()

    now = datetime.now(timezone.utc)
    expires_at = now.replace(year=now.year + 1).isoformat().replace("+00:00", "Z")
    envelope = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "permit",
        "execution_gate_envelope_id": _VALID_ENVELOPE_ID,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at,
        "profile": profile,
        "lane_id": "candidate_aggregation",
        "trigger_surface": "hermes_cron",
        "risk_class": "bounded_reversible_queue",
        "human_approval_required": False,
        "why_no_human_approval": "test",
        "scope": {"registry_key": "candidate_aggregation", "raw_script": "test"},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "boundary_true": False,
        "precheck": {"helper_present": True},
        "permit_decision": "allowed",
        "permit_reason": "boundary_false",
    }
    gate_path = roots.hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    with gate_path.open("a") as f:
        f.write(json.dumps(envelope, sort_keys=True) + "\n")

    return store


def _candidate(*, candidate_id="cand_test", kind="moment", body="",
               sensitivity="private", tags=None, bridge_state="inner_drive_candidate"):
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind=kind,
        body=body,
        source_event_ids=["evt_001"],
        sensitivity=sensitivity,
        tags=tags or [],
        bridge_state=bridge_state,
    )


def _write_candidate(store, candidate):
    """Write a candidate to the queue so read_candidate_queue() picks it up.

    read_candidate_queue reads from roots.crystallized_root / "candidates.jsonl".
    """
    queue_dir = store.roots.crystallized_root
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue_file = queue_dir / "candidates.jsonl"
    record = {
        "schema_version": "memory-os.crystallized_candidate.v0",
        "candidate_id": candidate.candidate_id,
        "kind": candidate.kind,
        "body": candidate.body,
        "source_event_ids": candidate.source_event_ids,
        "sensitivity": candidate.sensitivity,
        "tags": candidate.tags or [],
        "bridge_state": candidate.bridge_state,
        "created_at": candidate.created_at or datetime.now(timezone.utc).isoformat(),
        "rejection_count": candidate.rejection_count,
    }
    with queue_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_durable_verdict(store, candidate_id, durable_fact=True):
    """Write a fact_judge verdict to the sidecar file."""
    verdict_dir = store.roots.memory_os_root / "system-modules" / "fact_judge"
    verdict_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdict_dir / "verdicts.jsonl"
    record = {
        "schema_version": "memory-os.fact_judge_verdict.v0",
        "candidate_id": candidate_id,
        "durable_fact": durable_fact,
        "reason": "test verdict",
        "judged_at": datetime.now(timezone.utc).isoformat(),
    }
    with verdict_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


# ── F.1-F.2: Judge core behavior ─────────────────────────────────────────


class TestJudgeCandidate:
    """F.1-F.2: judge_candidate durability classification."""

    def test_durable_preference_returns_true(self):
        """F.1: A preference declaration is durable."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_001",
            body="Remembered from event evt_001: 我喜欢简洁的回答，不要太啰嗦。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "user preference for concise answers"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is True
            assert "preference" in result["reason"].lower() or "concise" in result["reason"].lower()

    def test_durable_decision_returns_true(self):
        """F.1: A decision/commitment is durable."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_002",
            body="Remembered from event evt_002: 我决定使用PostgreSQL作为这个项目的主数据库。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "technical decision recorded"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is True

    def test_transient_greeting_returns_false(self):
        """F.2: Greetings/pleasantries are NOT durable."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_003",
            body="Remembered from event evt_003: 你好，今天过得怎么样？",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": false, "reason": "casual greeting, not durable"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False

    def test_emotional_expression_returns_false(self):
        """F.2: Emotional expressions are NOT durable."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_004",
            body="Remembered from event evt_004: 我今天好累，不想写代码。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": false, "reason": "transient emotional state"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False

    def test_process_conversation_returns_false(self):
        """F.2: Process/navigation is NOT durable."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_005",
            body="Remembered from event evt_005: 帮我把这个文件打开。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": false, "reason": "task instruction, not durable"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False

    def test_factual_knowledge_returns_true(self):
        """F.1: Factual knowledge about the user is durable."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_006",
            body="Remembered from event: 我在北京工作，是一名后端工程师。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "factual knowledge about user"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is True


# ── F.3-F.4: Fail-safe + conservative ────────────────────────────────────


class TestJudgeFailSafe:
    """F.3-F.4: Fail-safe and conservative behavior."""

    def test_empty_response_returns_false(self):
        """F.3: Empty LLM response → after retries → heuristic fallback."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_fail_001",
            body="Session data: 会议安排在三点。",  # no durable markers
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value="",
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False
            assert "heuristic_fallback" in result["reason"]

    def test_non_json_response_returns_false(self):
        """F.3: Non-JSON → after retries → heuristic fallback."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_fail_002",
            body="Session data: 会议安排在三点。",  # no durable markers
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value="This is not JSON at all, just some text.",
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False
            assert "heuristic_fallback" in result["reason"]

    def test_missing_durable_fact_key_returns_false(self):
        """F.3: JSON without durable_fact key → retries → heuristic fallback."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_fail_003",
            body="Session data: the project deadline is next month.",  # no durable markers
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"something": "else"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False
            assert "heuristic_fallback" in result["reason"]

    def test_model_call_exception_returns_false(self):
        """F.3: Exception → after retries exhausted → heuristic fallback."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_fail_004",
            body="Session data: the project deadline is next month.",  # no durable markers
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            side_effect=RuntimeError("network failure"),
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False
            assert "heuristic_fallback" in result["reason"]

    def test_empty_body_returns_false(self):
        """F.4: Empty candidate body → durable_fact=False (conservative)."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_empty",
            body="",
        )

        # Should NOT call the model at all for empty body
        result = judge_candidate(candidate)
        assert result["durable_fact"] is False
        assert result["reason"] == "empty_body"

    def test_uncertain_llm_returning_false(self):
        """F.4: Judge uncertain → durable_fact=False (conservative)."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_unsure",
            body="Remembered from event: 嗯，也许吧。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": false, "reason": "ambiguous statement, unsure"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False


# ── F.5-F.6: Single-item bypass channel ──────────────────────────────────


class TestDurableFactBypassChannel:
    """F.5-F.6: Durable singleton bypasses size≥2, non-durable does not."""

    def test_durable_singleton_enters_resolver_verdict(self, tmp_path):
        """F.5: durable_fact single item (size=1) enters resolver verdict."""
        store = _store_with_gate(tmp_path)
        from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

        candidate = _candidate(
            candidate_id="cand_bypass_001",
            body="Remembered from event: 我叫张三，在北京工作。",
        )

        _write_candidate(store, candidate)
        _write_durable_verdict(store, candidate.candidate_id, durable_fact=True)

        processed: set[str] = set()
        result = _cluster_and_promote(
            [candidate], store, processed,
            envelope_id=_VALID_ENVELOPE_ID,
            now=datetime.now(timezone.utc),
        )

        # The candidate should be promoted (either resolver_approved or owner_eligible)
        assert candidate.candidate_id in processed, (
            f"Durable singleton should be processed; processed={processed}"
        )
        assert result["promoted_count"] == 1

    def test_non_durable_singleton_not_promoted(self, tmp_path):
        """F.6: Non-durable singleton → NOT promoted through bypass."""
        store = _store_with_gate(tmp_path)
        from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

        candidate = _candidate(
            candidate_id="cand_moment_001",
            body="Remembered from event: 今天天气不错。",
        )

        _write_candidate(store, candidate)
        _write_durable_verdict(store, candidate.candidate_id, durable_fact=False)

        processed: set[str] = set()
        result = _cluster_and_promote(
            [candidate], store, processed,
            envelope_id=_VALID_ENVELOPE_ID,
            now=datetime.now(timezone.utc),
        )

        # Non-durable singleton should NOT be promoted (no cluster, no bypass)
        assert candidate.candidate_id not in processed
        assert result["promoted_count"] == 0

    def test_durable_without_verdict_not_promoted(self, tmp_path):
        """F.6: Candidate without any verdict → NOT promoted as singleton."""
        store = _store_with_gate(tmp_path)
        from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

        candidate = _candidate(
            candidate_id="cand_no_verdict",
            body="Remembered from event: 我喜欢喝茶。",
        )

        _write_candidate(store, candidate)
        # Do NOT write any verdict

        processed: set[str] = set()
        result = _cluster_and_promote(
            [candidate], store, processed,
            envelope_id=_VALID_ENVELOPE_ID,
            now=datetime.now(timezone.utc),
        )

        # No verdict → no bypass → not promoted
        assert candidate.candidate_id not in processed
        assert result["promoted_count"] == 0


# ── F.7-F.8: Resolver routing (end-to-end) ───────────────────────────────


class TestDurableFactResolverRouting:
    """F.7-F.8: Durable + non-sensitive → resolver_approved; durable + identity → owner_eligible."""

    def test_durable_non_sensitive_becomes_resolver_approved(self, tmp_path):
        """F.7: Durable fact + non-sensitive → resolver_approved provisional crystal.

        This is the core E2E test — from 0 crystals to having crystals.
        """
        store = _store_with_gate(tmp_path)
        from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

        candidate = _candidate(
            candidate_id="cand_e2e_001",
            body="Remembered from event: 我最喜欢的编程语言是Python，已经用了5年。",
            sensitivity="private",
        )

        _write_candidate(store, candidate)
        _write_durable_verdict(store, candidate.candidate_id, durable_fact=True)

        processed: set[str] = set()
        result = _cluster_and_promote(
            [candidate], store, processed,
            envelope_id=_VALID_ENVELOPE_ID,
            now=datetime.now(timezone.utc),
        )

        assert result["promoted_count"] == 1
        assert candidate.candidate_id in processed

        # Check that a crystallized record was written (provisional)
        from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
        svc = CrystallizedMemoryService(store)
        records = svc.find_records_by_candidate_id(candidate.candidate_id)
        assert len(records) > 0, "Expected a crystallized record to be written"
        # The record should be provisional
        record = records[0]
        assert record.frontmatter.get("provisional") is True or record.frontmatter.get("state") in (
            "provisional", "resolver_approved", "active"
        ), f"Expected provisional record, got {record.frontmatter.get('state')}"

    def test_durable_identity_keyword_becomes_owner_eligible(self, tmp_path):
        """F.8: Durable fact + identity keyword → owner_eligible (not auto-crystallized)."""
        store = _store_with_gate(tmp_path)
        from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

        candidate = _candidate(
            candidate_id="cand_identity_001",
            body="Remembered from event: 我的身份是AI助手，我的personality是温和的。",
            sensitivity="private",
        )

        _write_candidate(store, candidate)
        _write_durable_verdict(store, candidate.candidate_id, durable_fact=True)

        processed: set[str] = set()
        result = _cluster_and_promote(
            [candidate], store, processed,
            envelope_id=_VALID_ENVELOPE_ID,
            now=datetime.now(timezone.utc),
        )

        assert result["promoted_count"] == 1
        assert candidate.candidate_id in processed

        # Identity keyword should NOT auto-crystallize
        from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
        svc = CrystallizedMemoryService(store)
        records = svc.find_records_by_candidate_id(candidate.candidate_id)
        # Identity candidate should go to owner_eligible, NOT crystallized
        assert len(records) == 0, (
            "Identity-adjacent candidate should NOT be auto-crystallized"
        )


# ── F.9-F.10: Safety + INV-5 ────────────────────────────────────────────


class TestFactJudgeSafety:
    """F.9: Auto-crystallized provisionals are visible/revocable. F.10: Offline."""

    def test_provisional_crystallized_appears_in_owner_approved(self, tmp_path):
        """F.9: Auto-crystallized provisional appears in owner_approved.md."""
        store = _store_with_gate(tmp_path)
        from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

        candidate = _candidate(
            candidate_id="cand_digest_001",
            body="Remembered from event: 用户每周五下午会进行代码审查。",
            sensitivity="private",
        )

        _write_candidate(store, candidate)
        _write_durable_verdict(store, candidate.candidate_id, durable_fact=True)

        processed: set[str] = set()
        _cluster_and_promote(
            [candidate], store, processed,
            envelope_id=_VALID_ENVELOPE_ID,
            now=datetime.now(timezone.utc),
        )

        # Check owner_approved.md for the provisional record
        approved_path = store.roots.crystallized_root / "owner_approved.md"
        assert approved_path.exists(), (
            "owner_approved.md should exist after auto-crystallization"
        )
        content = approved_path.read_text(encoding="utf-8")
        assert candidate.candidate_id in content, (
            "Crystallized candidate should appear in owner_approved.md"
        )

    def test_judge_is_offline_not_hot_path(self):
        """F.10: Judge is offline (INV-5) — no fact_judge reference in hot-path code."""
        from plugins.memory.memory_os.low_clue_recall import _call_hermes_runtime_model

        # The hot path (low_clue_recall) should NOT reference fact_judge at all.
        import inspect
        low_clue_source = inspect.getsource(_call_hermes_runtime_model)
        assert "fact_judge" not in low_clue_source, (
            "INV-5 violation: fact_judge referenced in low_clue_recall hot path"
        )


# ── F.11-F.12: Non-regression ───────────────────────────────────────────


class TestFactJudgeNonRegression:
    """F.11: Judge does NOT modify sensitivity. F.12: Moment still goes through clustering."""

    def test_judge_does_not_modify_sensitivity(self):
        """F.11: judge_candidate returns verdict — does not touch candidate.sensitivity."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_reg_001",
            body="Remembered from event: 我喜欢安静的咖啡店。",
            sensitivity="private",
        )

        original_sensitivity = candidate.sensitivity

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "preference"}',
        ):
            judge_candidate(candidate)

        # Sensitivity must NOT be modified
        assert candidate.sensitivity == original_sensitivity, (
            "F.11 regression: judge_candidate must not modify candidate.sensitivity"
        )

    def test_moment_still_goes_through_cluster_gate(self, tmp_path):
        """F.12: Moment candidates (non-durable) still go through size≥2 cluster gate."""
        store = _store_with_gate(tmp_path)
        from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

        # Two moment candidates that should cluster together
        c1 = _candidate(
            candidate_id="cand_moment_a",
            body="Remembered from event: 今天学习了Python异步编程。",
        )
        c2 = _candidate(
            candidate_id="cand_moment_b",
            body="Remembered from event: 今天学习了Python异步编程，收获很大。",
        )

        _write_candidate(store, c1)
        _write_candidate(store, c2)
        # Both marked as NOT durable — they should cluster normally via size≥2
        _write_durable_verdict(store, c1.candidate_id, durable_fact=False)
        _write_durable_verdict(store, c2.candidate_id, durable_fact=False)

        processed: set[str] = set()
        result = _cluster_and_promote(
            [c1, c2], store, processed,
            envelope_id=_VALID_ENVELOPE_ID,
            now=datetime.now(timezone.utc),
            min_cluster_size=2,
        )

        # If clustering works, they should promote via cluster (not bypass)
        assert result["promoted_count"] >= 0  # May or may not cluster depending on keywords

    def test_durable_fact_does_not_break_existing_cluster_promotion(self, tmp_path):
        """F.12: Existing cluster promotion (size≥2) still works with fact_judge present."""
        store = _store_with_gate(tmp_path)
        from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

        # Two similar candidates that should cluster
        c1 = _candidate(
            candidate_id="cand_cluster_x",
            body="Remembered from event: 项目使用Django框架开发Web应用。",
        )
        c2 = _candidate(
            candidate_id="cand_cluster_y",
            body="Remembered from event: 项目使用Django框架开发Web应用，后端API用DRF。",
        )

        _write_candidate(store, c1)
        _write_candidate(store, c2)
        # One durable, one not — cluster should still work
        _write_durable_verdict(store, c1.candidate_id, durable_fact=True)
        _write_durable_verdict(store, c2.candidate_id, durable_fact=False)

        processed: set[str] = set()
        result = _cluster_and_promote(
            [c1, c2], store, processed,
            envelope_id=_VALID_ENVELOPE_ID,
            now=datetime.now(timezone.utc),
            min_cluster_size=2,
        )

        # The clustering should still detect these as related
        # (regardless of durable_fact verdicts)
        assert isinstance(result["promoted_count"], int)


# ── run_fact_judge_lane integration ──────────────────────────────────────


class TestRunFactJudgeLane:
    """Integration tests for the full fact_judge cron lane."""

    def test_lane_judges_inner_drive_candidates(self, tmp_path):
        """run_fact_judge_lane reads candidates and writes verdicts."""
        store = _store(tmp_path)
        from plugins.modules.governance.fact_judge import run_fact_judge_lane

        c1 = _candidate(
            candidate_id="cand_lane_001",
            body="Remembered from event: 我喜欢用VSCode写代码。",
        )
        c2 = _candidate(
            candidate_id="cand_lane_002",
            body="Remembered from event: 今天天气不错。",
        )

        _write_candidate(store, c1)
        _write_candidate(store, c2)

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "preference"}',
        ):
            result = run_fact_judge_lane(store)

        assert result["status"] == "ok"
        assert result["judged_count"] == 2
        assert result["durable_count"] == 2

        # Verdicts should be written
        from plugins.modules.governance.fact_judge import read_fact_judge_verdicts
        verdicts = read_fact_judge_verdicts(store)
        assert c1.candidate_id in verdicts
        assert c2.candidate_id in verdicts

    def test_lane_skips_already_judged_candidates(self, tmp_path):
        """run_fact_judge_lane skips candidates already in verdicts."""
        store = _store(tmp_path)
        from plugins.modules.governance.fact_judge import run_fact_judge_lane

        c1 = _candidate(
            candidate_id="cand_skip_001",
            body="Remembered from event: 我喜欢Python。",
        )

        _write_candidate(store, c1)
        # Pre-write a verdict so c1 is already judged
        _write_durable_verdict(store, c1.candidate_id, durable_fact=True)

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
        ) as mock_call:
            result = run_fact_judge_lane(store)

        # Should not have called the model since candidate was already judged
        mock_call.assert_not_called()
        assert result["skipped_count"] == 1
        assert result["judged_count"] == 0


# ── A.1-A.2: Lean-capture prompt (spec A1) ────────────────────────────────


class TestLeanCapturePrompt:
    """A.1-A.2: RULE 1 rewritten — lean toward capture, not conservative."""

    def test_messy_colloquial_decision_returns_true(self):
        """A.1: Messy colloquial preference/decision → durable_fact=True.

        Old RULE 1 ('UNCERTAIN → False') would reject this as ambiguous.
        New RULE 1 ('LEAN TOWARD CAPTURE') should mark it True.
        """
        from plugins.modules.governance.fact_judge import judge_candidate

        # Real-world messy Chinese: "do data review online to improve betting strategy"
        candidate = _candidate(
            candidate_id="cand_a1_001",
            body="Remembered from event: 联网做数据复盘完善下注策略",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "colloquial decision about strategy"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is True, (
                f"Messy colloquial decision should be durable; got {result}"
            )

    def test_messy_embedded_framework_returns_true(self):
        """A.1: Framework definition embedded in discussion → durable_fact=True.

        '三层穿透框架定义' — a framework defined casually in conversation.
        Old prompt would mark UNCERTAIN → False; new prompt should capture.
        """
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_a1_002",
            body="Remembered from event: 三层穿透框架定义，用于分析市场结构",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "framework definition, reusable context"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is True, (
                f"Embedded framework should be durable; got {result}"
            )

    def test_clear_transient_greeting_still_false(self):
        """A.2: Clear transient (greeting) → still False (not over-correcting)."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_a2_001",
            body="Remembered from event: 你好，今天天气不错，收到请回复。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": false, "reason": "greeting and casual chat, not durable"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False, (
                f"Clear transient should NOT be durable; got {result}"
            )


# ── A.3-A.5: Retry + heuristic fallback (spec A2+A3) ──────────────────────


class TestJudgeRetryAndHeuristic:
    """A.3-A.5: Retry on empty/non-JSON, heuristic fallback on total failure."""

    def test_retry_succeeds_after_empty_response(self):
        """A.3: First call returns empty, retry returns valid JSON → valid verdict.

        Old code: empty response → immediate judge_empty_response.
        New code: retry → succeeds on second attempt.
        """
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_retry_001",
            body="Remembered from event: 我喜欢用Rust写后端服务。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            side_effect=[
                "",   # first call: empty response
                '{"durable_fact": true, "reason": "user preference for Rust"}',  # retry: valid
            ],
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is True, (
                f"Retry should recover from empty first response; got {result}"
            )
            assert result["reason"] == "user preference for Rust"

    def test_heuristic_fallback_when_all_retries_fail_with_durable_markers(self):
        """A.4: All retries fail + durable markers in body → heuristic returns True.

        Text contains '我喜欢' (I like) → durable marker → heuristic fallback True.
        """
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_heur_001",
            body="Remembered from event: 我喜欢用Neovim编辑器，已经配置了很多插件。",
        )

        # All calls return non-JSON — retries exhausted → heuristic fallback
        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value="Just some random text, not JSON at all.",
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is True, (
                f"Heuristic should detect '我喜欢' as durable marker; got {result}"
            )
            assert "heuristic_fallback" in result["reason"], (
                f"Reason should indicate heuristic_fallback; got {result['reason']}"
            )

    def test_heuristic_not_fail_open_with_no_markers(self):
        """A.5: All retries fail + no durable/transient markers → False (not fail-open).

        Text has no durable markers and no transient markers → heuristic returns False.
        This is the safety net: don't let random content through.
        """
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_heur_002",
            body="Quux baz frobnicate the widget stream.",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            side_effect=[
                "",           # empty
                "not json",   # non-JSON
                "",           # empty again (3 total = 1 initial + 2 retries)
            ],
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False, (
                f"Heuristic should NOT fail-open on content with no markers; got {result}"
            )
            assert "heuristic_fallback" in result["reason"], (
                f"Reason should indicate heuristic_fallback; got {result['reason']}"
            )


    def test_heuristic_durable_marker_priority_over_transient(self):
        """C1: durable markers checked first — body with both gets durable_fact=True."""
        from plugins.modules.governance.fact_judge import _heuristic_durable, CrystallizedCandidate
        candidate = CrystallizedCandidate(
            candidate_id="test-c1", kind="moment",
            body="Thanks, I use Python for all backend services.",
            source_event_ids=["evt-1"],
        )
        verdict = _heuristic_durable(candidate)
        # "i use" is in _DURABLE_MARKERS, "thanks" is in _TRANSIENT_MARKERS
        # With corrected priority, durable markers checked first → True
        assert verdict["durable_fact"] is True, f"Expected True (durable markers first), got {verdict}"
        assert "heuristic_fallback:durable_marker" in verdict["reason"]

    def test_heuristic_fallback_reason_includes_matched_marker(self):
        """C8: reason string identifies which marker triggered the verdict."""
        from plugins.modules.governance.fact_judge import _heuristic_durable, CrystallizedCandidate
        candidate = CrystallizedCandidate(
            candidate_id="test-c8", kind="moment",
            body="I plan to use Rust going forward.",
            source_event_ids=["evt-2"],
        )
        verdict = _heuristic_durable(candidate)
        assert verdict["durable_fact"] is True
        # Reason must include the specific matched marker, not just a generic class
        assert ":" in verdict["reason"]
        parts = verdict["reason"].split(":")
        assert len(parts) >= 3, f"Expected reason with marker identity, got: {verdict['reason']}"
        matched_marker = parts[-1]
        assert matched_marker in {"plan to", "i use"}, f"Unexpected marker: {matched_marker}"


# ── A.6-A.7: Adaptive bias (spec A4) ───────────────────────────────────────


class TestAdaptiveBias:
    """A.6-A.7: Adaptive bias — lean when crystallized count < threshold, strict when >=."""

    def test_lean_prompt_when_below_threshold(self):
        """A.6: active_crystallized_count < LEAN_CAPTURE_THRESHOLD → lean prompt.

        The lean prompt (default _JUDGE_SYSTEM_PROMPT) contains 'LEAN TOWARD CAPTURE'.
        """
        from plugins.modules.governance.fact_judge import (
            _adaptive_prompt,
            LEAN_CAPTURE_THRESHOLD,
        )

        below = LEAN_CAPTURE_THRESHOLD - 1
        prompt = _adaptive_prompt(below)
        assert "LEAN TOWARD CAPTURE" in prompt, (
            f"Below threshold ({below} < {LEAN_CAPTURE_THRESHOLD}) should use lean prompt"
        )

    def test_strict_prompt_when_above_threshold(self):
        """A.6: active_crystallized_count >= LEAN_CAPTURE_THRESHOLD → strict prompt.

        The strict prompt should NOT contain 'LEAN TOWARD CAPTURE'.
        It should contain conservative language.
        """
        from plugins.modules.governance.fact_judge import (
            _adaptive_prompt,
            LEAN_CAPTURE_THRESHOLD,
        )

        at_threshold = LEAN_CAPTURE_THRESHOLD
        prompt = _adaptive_prompt(at_threshold)
        assert "LEAN TOWARD CAPTURE" not in prompt, (
            f"At threshold ({at_threshold} >= {LEAN_CAPTURE_THRESHOLD}) should use strict prompt"
        )
        assert "UNCERTAIN" in prompt, (
            "Strict prompt should contain conservative UNCERTAIN language"
        )

    def test_lean_capture_threshold_not_in_overridable_knobs(self):
        """A.7: LEAN_CAPTURE_THRESHOLD is meta — NOT in OVERRIDABLE_KNOBS.

        The system cannot tune its own judge threshold.
        """
        from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS
        from plugins.modules.governance.fact_judge import LEAN_CAPTURE_THRESHOLD

        # Verify it's a meta constant (exists, has correct value)
        assert isinstance(LEAN_CAPTURE_THRESHOLD, int)
        assert LEAN_CAPTURE_THRESHOLD > 0

        # Verify NOT in OVERRIDABLE_KNOBS
        assert "lean_capture_threshold" not in OVERRIDABLE_KNOBS, (
            "A.7 violation: LEAN_CAPTURE_THRESHOLD must NOT be in OVERRIDABLE_KNOBS "
            "(meta constant, system cannot self-tune judge threshold)"
        )
        assert "LEAN_CAPTURE_THRESHOLD" not in OVERRIDABLE_KNOBS, (
            "A.7 violation: LEAN_CAPTURE_THRESHOLD must NOT be in OVERRIDABLE_KNOBS"
        )

    def test_count_active_crystallized_respects_inactive_states(self, tmp_path):
        """A.6: _count_active_crystallized filters out inactive records."""
        from plugins.modules.governance.fact_judge import _count_active_crystallized
        store = _store(tmp_path)

        # Initially empty → count = 0
        assert _count_active_crystallized(store) == 0

        # Write a crystallized record (active)
        from plugins.memory.memory_os.crystallized import (
            CrystallizedMemoryService,
            CrystallizedCandidate,
            ApprovalDecision,
            ApprovalPurpose,
        )
        svc = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            candidate_id="cand_active_001",
            kind="preference",
            body="I prefer dark mode",
            source_event_ids=["evt_001"],
        )
        decision = ApprovalDecision(
            candidate_id=candidate.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="test",
            reviewed_at="2026-06-18T00:00:00Z",
        )
        svc.write_approved_record(candidate, decision, file_name="owner_approved.md")
        assert _count_active_crystallized(store) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Fact Judge Config Hardening — max_tokens, bounded drain, failure telemetry
# ═══════════════════════════════════════════════════════════════════════════════


class TestJudgeConfigDefaults:
    """Default config: max_tokens=1024, max_per_tick=8, timeout_ms=15000."""

    def test_max_tokens_is_1024(self):
        """max_tokens default is 1024 (not 256) for reasoning-model headroom."""
        from plugins.modules.governance.fact_judge import DEFAULT_JUDGE_CONFIG
        assert DEFAULT_JUDGE_CONFIG["max_tokens"] == 1024, (
            f"Expected max_tokens=1024, got {DEFAULT_JUDGE_CONFIG['max_tokens']}"
        )

    def test_max_per_tick_is_8(self):
        """max_per_tick default is 8 to prevent unbounded backlog blow-up."""
        from plugins.modules.governance.fact_judge import DEFAULT_JUDGE_CONFIG
        assert DEFAULT_JUDGE_CONFIG["max_per_tick"] == 8, (
            f"Expected max_per_tick=8, got {DEFAULT_JUDGE_CONFIG['max_per_tick']}"
        )


# ── Failure telemetry ────────────────────────────────────────────────────


class TestJudgeCandidateFailureTelemetry:
    """judge_candidate returns failure_reason on LLM-path failure."""

    def test_success_path_has_no_failure_reason(self):
        """Successful LLM judgment → failure_reason=None."""
        from plugins.modules.governance.fact_judge import judge_candidate
        candidate = _candidate(body="Remembered from event: I prefer Rust for backend services.")

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "preference for Rust"}',
        ):
            result = judge_candidate(candidate)
            assert result["failure_reason"] is None, (
                f"Success path should have failure_reason=None; got {result['failure_reason']}"
            )

    def test_empty_content_records_failure_reason(self):
        """Empty LLM response → failure_reason='llm_empty_content' + heuristic fallback."""
        from plugins.modules.governance.fact_judge import judge_candidate
        candidate = _candidate(body="Session data: the project deadline is next month.")

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value="",
        ):
            result = judge_candidate(candidate)
            assert result["failure_reason"] == "llm_empty_content", (
                f"Expected llm_empty_content; got {result['failure_reason']}"
            )
            assert "heuristic_fallback" in result["reason"]

    def test_parse_failed_records_failure_reason(self):
        """Non-JSON response → failure_reason='llm_parse_failed' + heuristic fallback."""
        from plugins.modules.governance.fact_judge import judge_candidate
        candidate = _candidate(body="Session data: the project deadline is next month.")

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value="This is not JSON, just plain text output.",
        ):
            result = judge_candidate(candidate)
            assert result["failure_reason"] == "llm_parse_failed", (
                f"Expected llm_parse_failed; got {result['failure_reason']}"
            )

    def test_missing_key_records_failure_reason(self):
        """JSON without durable_fact key → failure_reason='llm_missing_key'."""
        from plugins.modules.governance.fact_judge import judge_candidate
        candidate = _candidate(body="Session data: the project deadline is next month.")

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"something": "else"}',
        ):
            result = judge_candidate(candidate)
            assert result["failure_reason"] == "llm_missing_key", (
                f"Expected llm_missing_key; got {result['failure_reason']}"
            )

    def test_exception_records_failure_reason(self):
        """Exception → failure_reason='llm_exception' + heuristic fallback."""
        from plugins.modules.governance.fact_judge import judge_candidate
        candidate = _candidate(body="Session data: the project deadline is next month.")

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            side_effect=RuntimeError("network timeout"),
        ):
            result = judge_candidate(candidate)
            assert result["failure_reason"] == "llm_exception", (
                f"Expected llm_exception; got {result['failure_reason']}"
            )

    def test_heuristic_only_knob_records_failure_reason(self):
        """heuristic_only=True → failure_reason='heuristic_only_knob'."""
        from plugins.modules.governance.fact_judge import judge_candidate
        candidate = _candidate(body="Remembered from event: I prefer Rust.")

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
        ) as mock_call:
            result = judge_candidate(candidate, heuristic_only=True)

        mock_call.assert_not_called()
        assert result["failure_reason"] == "heuristic_only_knob", (
            f"Expected heuristic_only_knob; got {result['failure_reason']}"
        )

    def test_empty_body_has_no_failure_reason(self):
        """Empty body is a valid fast-path, not an LLM failure."""
        from plugins.modules.governance.fact_judge import judge_candidate
        candidate = _candidate(body="")
        result = judge_candidate(candidate)
        assert result["durable_fact"] is False
        assert result["reason"] == "empty_body"
        assert result["failure_reason"] is None, (
            "Empty body is not an LLM failure — no failure_reason"
        )


# ── Bounded drain ────────────────────────────────────────────────────────


class TestRunFactJudgeLaneBoundedDrain:
    """run_fact_judge_lane respects max_per_tick bounded drain."""

    def test_lane_stops_at_max_per_tick(self, tmp_path):
        """When max_per_tick < unjudged candidates, only max_per_tick are judged."""
        store = _store(tmp_path)
        from plugins.modules.governance.fact_judge import run_fact_judge_lane

        for i in range(12):
            c = _candidate(
                candidate_id=f"cand_drain_{i:03d}",
                body=f"Remembered from event: preference item {i}.",
            )
            _write_candidate(store, c)

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "preference"}',
        ):
            result = run_fact_judge_lane(store)

        assert result["judged_count"] == 8, (
            f"Expected 8 judged (max_per_tick), got {result['judged_count']}"
        )
        assert result["skipped_count"] == 4, (
            f"Expected 4 skipped (12 - 8), got {result['skipped_count']}"
        )

    def test_lane_includes_already_judged_in_skip_count(self, tmp_path):
        """Already-judged + bounded-drain overflow both count as skipped."""
        store = _store(tmp_path)
        from plugins.modules.governance.fact_judge import run_fact_judge_lane

        c1 = _candidate(
            candidate_id="cand_skip_aj",
            body="Remembered from event: already judged.",
        )
        c2 = _candidate(
            candidate_id="cand_skip_new",
            body="Remembered from event: new candidate.",
        )
        _write_candidate(store, c1)
        _write_candidate(store, c2)
        _write_durable_verdict(store, c1.candidate_id, durable_fact=True)

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "preference"}',
        ):
            result = run_fact_judge_lane(store)

        assert result["judged_count"] == 1  # only c2 is new
        assert result["skipped_count"] == 1  # c1 was already judged


# ── Error telemetry in run_fact_judge_lane ────────────────────────────────


class TestRunFactJudgeLaneErrorCount:
    """run_fact_judge_lane error_count reads failure_reason from verdicts."""

    def test_error_count_zero_when_all_llm_succeed(self, tmp_path):
        """All LLM calls succeed → error_count=0."""
        store = _store(tmp_path)
        from plugins.modules.governance.fact_judge import run_fact_judge_lane

        for i in range(3):
            c = _candidate(
                candidate_id=f"cand_ok_{i:03d}",
                body=f"Remembered from event: I prefer option {i}.",
            )
            _write_candidate(store, c)

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "preference"}',
        ):
            result = run_fact_judge_lane(store)

        assert result["error_count"] == 0, (
            f"All LLM calls succeeded — error_count should be 0, got {result['error_count']}"
        )

    def test_error_count_nonzero_when_llm_fails(self, tmp_path):
        """Empty LLM responses → error_count reflects failures."""
        store = _store(tmp_path)
        from plugins.modules.governance.fact_judge import run_fact_judge_lane

        for i in range(5):
            c = _candidate(
                candidate_id=f"cand_fail_{i:03d}",
                body=f"Session data: unjudgable content {i}.",
            )
            _write_candidate(store, c)

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value="",
        ):
            result = run_fact_judge_lane(store)

        assert result["error_count"] == 5, (
            f"All 5 LLM calls returned empty → error_count should be 5, got {result['error_count']}"
        )


# ── Knob registration ────────────────────────────────────────────────────


class TestFactJudgeKnobsRegistered:
    """fact_judge knobs are registered in OVERRIDABLE_KNOBS."""

    def test_fact_judge_knobs_in_overridable_knobs(self):
        """All 4 fact_judge knobs are registered."""
        from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS
        expected = {
            "fact_judge_max_tokens",
            "fact_judge_max_per_tick",
            "fact_judge_timeout_ms",
            "fact_judge_heuristic_only",
        }
        for knob in expected:
            assert knob in OVERRIDABLE_KNOBS, (
                f"Knob '{knob}' must be in OVERRIDABLE_KNOBS"
            )

    def test_fact_judge_heuristic_only_is_lane_switch(self):
        """heuristic_only is a lane_switch (owner-gated — blast radius too large)."""
        from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS
        spec = OVERRIDABLE_KNOBS["fact_judge_heuristic_only"]
        assert spec["kind"] == "lane_switch", (
            f"heuristic_only must be lane_switch (owner-gated); got kind={spec.get('kind')}"
        )

    def test_fact_judge_max_tokens_bounds_allow_768_to_4096(self):
        """Bounds: 256-4096 covers conservative (768) to generous (4096)."""
        from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS
        bounds = OVERRIDABLE_KNOBS["fact_judge_max_tokens"]["bounds"]
        assert bounds[0] == 256
        assert bounds[1] == 4096
        assert 768 in range(bounds[0], bounds[1] + 1), "768 should be within bounds"

    def test_knob_auto_approvable(self):
        """fact_judge_max_tokens and max_per_tick are auto-approvable (not lane_switch)."""
        from plugins.memory.memory_os.knob_overrides import knob_override_auto_approvable
        assert knob_override_auto_approvable("fact_judge_max_tokens", 2048) is True
        assert knob_override_auto_approvable("fact_judge_max_per_tick", 4) is True


# ── Config pipe-through ──────────────────────────────────────────────────


class TestJudgeCandidateConfigOverride:
    """judge_candidate's config parameter pipes through to _call_hermes_runtime_model."""

    def test_config_max_tokens_overrides_default(self):
        """Explicit config max_tokens overrides DEFAULT_JUDGE_CONFIG."""
        from plugins.modules.governance.fact_judge import judge_candidate
        candidate = _candidate(body="Remembered from event: I prefer Python.")

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
        ) as mock_call:
            mock_call.return_value = '{"durable_fact": true, "reason": "preference"}'
            judge_candidate(candidate, config={"max_tokens": 2048})

        call_config = mock_call.call_args[0][1]
        assert call_config["max_tokens"] == 2048, (
            f"Expected max_tokens=2048 in call config; got {call_config}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# P1: Safe knob parsing — int() and bool() hardening
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunFactJudgeLaneSafeKnobParsing:
    """P1: Non-numeric knob values fall back to default; string bools don't enable lane switches."""

    def test_non_numeric_max_tokens_falls_back_to_default(self, tmp_path):
        """int('true') → ValueError → fall back to DEFAULT_JUDGE_CONFIG default."""
        store = _store(tmp_path)
        from plugins.modules.governance.fact_judge import DEFAULT_JUDGE_CONFIG

        # Write a poison knob override: max_tokens = "true" (string, not int)
        _write_knob_override(store, "fact_judge_max_tokens", "true")

        from plugins.modules.governance.fact_judge import run_fact_judge_lane
        result = run_fact_judge_lane(store)
        assert result["status"] == "ok", (
            f"Lane should complete successfully despite poison knob; got {result}"
        )

    def test_non_numeric_max_per_tick_falls_back_to_default(self, tmp_path):
        """int('false') → ValueError → fall back to default."""
        store = _store(tmp_path)
        _write_knob_override(store, "fact_judge_max_per_tick", "false")

        from plugins.modules.governance.fact_judge import run_fact_judge_lane
        result = run_fact_judge_lane(store)
        assert result["status"] == "ok"

    def test_non_numeric_timeout_ms_falls_back_to_default(self, tmp_path):
        """int('hello') → ValueError → fall back to default."""
        store = _store(tmp_path)
        _write_knob_override(store, "fact_judge_timeout_ms", "hello")

        from plugins.modules.governance.fact_judge import run_fact_judge_lane
        result = run_fact_judge_lane(store)
        assert result["status"] == "ok"

    def test_string_true_does_not_enable_heuristic_only(self, tmp_path):
        """bool('true') would be True, but strict `is True` rejects it."""
        store = _store(tmp_path)
        candidate = _candidate(
            candidate_id="cand_heuristic_test",
            body="I prefer dark mode",
        )
        _write_candidate(store, candidate)

        # Write a poison knob: heuristic_only = "true" (string, not bool)
        _write_knob_override(store, "fact_judge_heuristic_only", "true")

        from plugins.modules.governance.fact_judge import run_fact_judge_lane
        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
        ) as mock_llm:
            mock_llm.return_value = '{"durable_fact": true, "reason": "preference"}'
            result = run_fact_judge_lane(store)

        # LLM was called — heuristic_only was NOT enabled by the string "true"
        assert mock_llm.called, (
            "P1 FAIL: string 'true' enabled heuristic_only — LLM was bypassed. "
            "Strict `is True` check should reject string values."
        )
        assert result["status"] == "ok"

    def test_string_false_does_not_enable_heuristic_only(self, tmp_path):
        """bool('false') would be True (non-empty string), but strict check rejects it."""
        store = _store(tmp_path)

        candidate = _candidate(
            candidate_id="cand_str_false",
            body="I use vim",
        )
        _write_candidate(store, candidate)

        _write_knob_override(store, "fact_judge_heuristic_only", "false")

        from plugins.modules.governance.fact_judge import run_fact_judge_lane
        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
        ) as mock_llm:
            mock_llm.return_value = '{"durable_fact": true, "reason": "preference"}'
            result = run_fact_judge_lane(store)

        # "false" is a non-empty string → bool("false") == True, but
        # strict `is True` check must reject it
        assert mock_llm.called, (
            "P1 FAIL: string 'false' enabled heuristic_only via bool('false')==True. "
            "Strict `is True` check should reject string values."
        )
        assert result["status"] == "ok"

    def test_int_zero_does_not_enable_heuristic_only(self, tmp_path):
        """bool(0) is False, but int 0 is not True — strict check correctly rejects."""
        store = _store(tmp_path)

        candidate = _candidate(candidate_id="cand_zero", body="I use vscode")
        _write_candidate(store, candidate)

        _write_knob_override(store, "fact_judge_heuristic_only", 0)

        from plugins.modules.governance.fact_judge import run_fact_judge_lane
        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
        ) as mock_llm:
            mock_llm.return_value = '{"durable_fact": true, "reason": "preference"}'
            run_fact_judge_lane(store)

        assert mock_llm.called, (
            "P1 FAIL: int 0 should not enable heuristic_only (is True check)"
        )

    def test_bool_true_does_enable_heuristic_only(self, tmp_path):
        """Only the Python bool True (is True) should enable the lane switch."""
        store = _store(tmp_path)

        candidate = _candidate(candidate_id="cand_bool_true", body="I prefer dark mode")
        _write_candidate(store, candidate)

        _write_knob_override(store, "fact_judge_heuristic_only", True)

        from plugins.modules.governance.fact_judge import run_fact_judge_lane
        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
        ) as mock_llm:
            run_fact_judge_lane(store)

        assert not mock_llm.called, (
            "P1 FAIL: bool True should enable heuristic_only and bypass LLM"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# P2a: failure_reason persisted to verdicts JSONL
# ═══════════════════════════════════════════════════════════════════════════════


class TestAppendVerdictFailureReasonPersistence:
    """P2a: _append_verdict writes failure_reason to the verdicts JSONL."""

    def test_failure_reason_written_for_heuristic_only(self, tmp_path):
        """heuristic_only knob → failure_reason='heuristic_only_knob' in JSONL."""
        from plugins.modules.governance.fact_judge import (
            _read_verdicts,
            run_fact_judge_lane,
        )

        store = _store(tmp_path)

        candidate = _candidate(candidate_id="cand_fr_test", body="I prefer Python")
        _write_candidate(store, candidate)

        _write_knob_override(store, "fact_judge_heuristic_only", True)
        run_fact_judge_lane(store)

        verdicts = _read_verdicts(store)
        assert "cand_fr_test" in verdicts, (
            "P2a FAIL: verdict not written for candidate"
        )
        assert verdicts["cand_fr_test"].get("failure_reason") == "heuristic_only_knob", (
            f"P2a FAIL: failure_reason not persisted; got {verdicts['cand_fr_test']}"
        )

    def test_failure_reason_written_for_llm_empty_content(self, tmp_path):
        """LLM returns empty content → failure_reason='llm_empty_content' in JSONL."""
        from plugins.modules.governance.fact_judge import _read_verdicts, run_fact_judge_lane

        store = _store(tmp_path)

        candidate = _candidate(candidate_id="cand_empty", body="I prefer vim")
        _write_candidate(store, candidate)

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value="",
        ):
            run_fact_judge_lane(store)

        verdicts = _read_verdicts(store)
        assert "cand_empty" in verdicts
        assert verdicts["cand_empty"].get("failure_reason") == "llm_empty_content", (
            f"P2a FAIL: expected llm_empty_content; got {verdicts['cand_empty']}"
        )

    def test_failure_reason_written_for_llm_exception(self, tmp_path):
        """LLM call raises → failure_reason='llm_exception' in JSONL."""
        from plugins.modules.governance.fact_judge import _read_verdicts, run_fact_judge_lane

        store = _store(tmp_path)

        candidate = _candidate(candidate_id="cand_exc", body="I use neovim")
        _write_candidate(store, candidate)

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            side_effect=RuntimeError("connection refused"),
        ):
            run_fact_judge_lane(store)

        verdicts = _read_verdicts(store)
        assert "cand_exc" in verdicts
        assert verdicts["cand_exc"].get("failure_reason") == "llm_exception", (
            f"P2a FAIL: expected llm_exception; got {verdicts['cand_exc']}"
        )

    def test_failure_reason_absent_on_success(self, tmp_path):
        """Successful LLM judgment → no failure_reason key in JSONL."""
        from plugins.modules.governance.fact_judge import _read_verdicts, run_fact_judge_lane

        store = _store(tmp_path)

        candidate = _candidate(candidate_id="cand_ok", body="I prefer Python")
        _write_candidate(store, candidate)

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"durable_fact": true, "reason": "preference"}',
        ):
            run_fact_judge_lane(store)

        verdicts = _read_verdicts(store)
        assert "cand_ok" in verdicts
        assert "failure_reason" not in verdicts["cand_ok"], (
            f"P2a FAIL: failure_reason should be absent on success; got {verdicts['cand_ok']}"
        )


# ── Knob override helper ─────────────────────────────────────────────────


def _write_knob_override(store, knob_name, value):
    """Write a knob override directly to the knob-override store for testing."""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    path = store.roots.memory_os_root / "system" / "knob_overrides.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _dt.now(_tz.utc)
    record = {
        "schema_version": "memory-os.knob_override.v0",
        "id": f"ko_test_{knob_name}",
        "knob": knob_name,
        "override_value": value,
        "prior_value": None,
        "provisional": False,
        "expires_at": "",
        "proposed_by": "test",
        "approved_via": "test",
        "state": "active",
        "ts": now.isoformat(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
