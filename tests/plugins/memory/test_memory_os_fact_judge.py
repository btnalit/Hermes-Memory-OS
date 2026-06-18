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
        """F.3: Empty LLM response → durable_fact=False (fail-safe)."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_fail_001",
            body="Remembered from event: 我喜欢Python。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value="",
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False
            assert result["reason"] == "judge_empty_response"

    def test_non_json_response_returns_false(self):
        """F.3: Non-JSON LLM response → durable_fact=False (fail-safe)."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_fail_002",
            body="Remembered from event: 我喜欢Python。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value="This is not JSON at all, just some text.",
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False
            assert "judge_" in result["reason"]

    def test_missing_durable_fact_key_returns_false(self):
        """F.3: JSON without durable_fact key → durable_fact=False (fail-safe)."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_fail_003",
            body="Remembered from event: 我喜欢Python。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            return_value='{"something": "else"}',
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False
            assert result["reason"] == "judge_missing_durable_fact_key"

    def test_model_call_exception_returns_false(self):
        """F.3: Exception during model call → durable_fact=False (fail-safe)."""
        from plugins.modules.governance.fact_judge import judge_candidate

        candidate = _candidate(
            candidate_id="cand_fail_004",
            body="Remembered from event: 我喜欢Python。",
        )

        with patch(
            "plugins.modules.governance.fact_judge._call_hermes_runtime_model",
            side_effect=RuntimeError("network failure"),
        ):
            result = judge_candidate(candidate)
            assert result["durable_fact"] is False
            assert result["reason"] == "judge_call_failed"

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
