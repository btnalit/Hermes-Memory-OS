"""Tests for jev_backend — optional, default-off TypeSafe Jev structured-judge
transport (J1, docs/plans/2026-09-23-memory-os-next-phase-plan.md row J1).

No network calls anywhere in this file. The HTTP layer (urllib.request.urlopen)
is mocked; everything above it (question builders, answer parsing, credential
resolution, status-code classification, judge_noul thresholding) is exercised
for real.
"""
from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

from plugins.memory.memory_os import jev_backend


# ── Helpers ──────────────────────────────────────────────────────────────

class _FakeResponse:
    """Minimal context-manager stand-in for the object urlopen() yields."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self) -> bytes:
        return self._body


def _fake_http_error(code: int, body: dict | str = "") -> urllib.error.HTTPError:
    if isinstance(body, dict):
        payload = json.dumps(body).encode("utf-8")
    else:
        payload = str(body).encode("utf-8")
    return urllib.error.HTTPError(
        url="https://api.typesafe.ai/v1/systemone",
        code=code,
        msg="error",
        hdrs=None,
        fp=BytesIO(payload),
    )


_VALID_CONFIG = {"api_key_env_var": "TEST_TYPESAFE_KEY", "timeout_ms": 5000}


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    monkeypatch.setenv("TEST_TYPESAFE_KEY", "fake-test-key-not-real")


# ── Credential resolution — no network on missing key ────────────────────

class TestApiKeyResolution:
    def test_missing_env_var_name_fails_without_network(self, monkeypatch):
        """api_key_env_var itself unset -> llm_missing_key, zero HTTP calls."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = jev_backend.call_systemone(
                state="x",
                questions={"q": {"type": "noul", "instructions": "?"}},
                config={"api_key_env_var": ""},
            )
        assert result.failure_reason == "llm_missing_key"
        assert not mock_urlopen.called, "missing key must never reach the network"

    def test_env_var_name_set_but_not_in_environ_fails_without_network(self, monkeypatch):
        monkeypatch.delenv("TOTALLY_UNSET_TYPESAFE_VAR", raising=False)
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = jev_backend.call_systemone(
                state="x",
                questions={"q": {"type": "noul", "instructions": "?"}},
                config={"api_key_env_var": "TOTALLY_UNSET_TYPESAFE_VAR"},
            )
        assert result.failure_reason == "llm_missing_key"
        assert not mock_urlopen.called

    def test_default_env_var_name_is_typesafe_api_key(self):
        assert jev_backend.JEV_API_KEY_ENV_VAR_DEFAULT == "TYPESAFE_API_KEY"

    def test_key_present_resolves_and_reaches_network(self):
        """Counterfactual: if _resolve_api_key were broken, this would also
        report llm_missing_key even though the env var is set."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"q": {"type": "noul", "noul": 0.5}}}).encode()
            )
            result = jev_backend.call_systemone(
                state="x",
                questions={"q": {"type": "noul", "instructions": "?"}},
                config=_VALID_CONFIG,
            )
        assert mock_urlopen.called
        assert result.failure_reason == ""


class TestInvalidCallConfig:
    def test_non_numeric_timeout_fails_without_network(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = jev_backend.call_systemone(
                state="x",
                questions={"q": {"type": "noul", "instructions": "?"}},
                config={"api_key_env_var": "TEST_TYPESAFE_KEY", "timeout_ms": "not-a-number"},
            )
        assert result.failure_reason == "llm_exception"
        assert not mock_urlopen.called


# ── HTTP status-code classification ───────────────────────────────────────

class TestHttpStatusClassification:
    def test_401_maps_to_llm_missing_key(self):
        with patch("urllib.request.urlopen", side_effect=_fake_http_error(401)):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_missing_key"

    def test_429_maps_to_llm_rate_limited_not_the_malformed_request_bucket(self):
        """Throttling and a malformed request need different responses
        (back off vs fix the payload); one bucket for both hides which."""
        with patch("urllib.request.urlopen", side_effect=_fake_http_error(429)):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_rate_limited"

    def test_422_documented_maps_to_llm_http_4xx(self):
        """Docs claim malformed questions return 422."""
        with patch("urllib.request.urlopen", side_effect=_fake_http_error(422)):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_http_4xx"

    def test_400_live_verified_maps_to_llm_http_4xx(self):
        """Live probe (2026-09-23) found malformed requests actually return
        400, not the documented 422 -- both must land in the same bucket."""
        with patch("urllib.request.urlopen", side_effect=_fake_http_error(400)):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_http_4xx"

    def test_529_maps_to_explicit_overloaded_not_generic_bucket(self):
        """Counterfactual: removing the 529 special-case in
        _classify_http_status makes this fall through to llm_exception."""
        with patch("urllib.request.urlopen", side_effect=_fake_http_error(529)):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_overloaded"

    def test_undocumented_5xx_falls_back_to_llm_exception(self):
        with patch("urllib.request.urlopen", side_effect=_fake_http_error(503)):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_exception"

    def test_connection_refused_maps_to_transport_unavailable(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_transport_unavailable"

    def test_urlerror_timeout_reason_maps_to_llm_timeout(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_timeout"

    def test_bare_timeout_error_maps_to_llm_timeout(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("socket timed out")):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_timeout"

    def test_unexpected_exception_never_raises_and_maps_to_llm_exception(self):
        with patch("urllib.request.urlopen", side_effect=RuntimeError("something weird")):
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_exception"


# ── Response body parsing ──────────────────────────────────────────────────

class TestResponseParsing:
    def test_malformed_json_body_is_llm_parse_failed(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(b"{not json")
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_parse_failed"

    def test_json_array_body_is_llm_parse_failed(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(b"[1, 2, 3]")
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_parse_failed"

    def test_missing_answers_key_is_llm_empty_content(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(json.dumps({"model": "jev-1.13.0"}).encode())
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_empty_content"

    def test_successful_noul_response_parses_usage_and_model(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {"durable_fact": {"type": "noul", "noul": 0.94}},
                    "usage": {"input_tokens": 405, "output_tokens": 22},
                }).encode()
            )
            result = jev_backend.call_systemone(
                state={"candidate_body": "x"},
                questions={"durable_fact": {"type": "noul", "instructions": "?"}},
                config=_VALID_CONFIG,
            )
        assert result.failure_reason == ""
        assert result.model == "jev-1.13.0"
        assert result.usage == {"prompt_tokens": 405, "completion_tokens": 22}
        assert result.answers["durable_fact"].noul == 0.94

    def test_successful_choice_response_parses_probabilities_and_confidence(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {
                        "moment_kind": {
                            "type": "choice",
                            "choice": "transient_moment",
                            "confidence": 0.94,
                            "probabilities": {"transient_moment": 0.97, "durable_fact": 0.03},
                        }
                    },
                }).encode()
            )
            result = jev_backend.call_systemone(
                state="x",
                questions={"moment_kind": {"type": "choice", "instructions": "?", "criteria": {"a": "b"}}},
                config=_VALID_CONFIG,
            )
        answer = result.answers["moment_kind"]
        assert answer.type == "choice"
        assert answer.choice == "transient_moment"
        assert answer.confidence == 0.94
        assert answer.probabilities == {"transient_moment": 0.97, "durable_fact": 0.03}

    def test_successful_score_response_parses_legend_and_probabilities(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {
                        "durability_level": {
                            "type": "score",
                            "score": 0.08,
                            "confidence": 0.88,
                            "legend": {"0": "low", "1": "mid", "2": "high"},
                            "probabilities": {"0": 0.92, "1": 0.08, "2": 0.0},
                        }
                    },
                }).encode()
            )
            result = jev_backend.call_systemone(
                state="x",
                questions={"durability_level": {"type": "score", "instructions": "?", "criteria": ["low", "mid", "high"]}},
                config=_VALID_CONFIG,
            )
        answer = result.answers["durability_level"]
        assert answer.type == "score"
        assert answer.score == 0.08
        assert answer.confidence == 0.88
        assert answer.legend == {"0": "low", "1": "mid", "2": "high"}

    def test_malformed_answer_entry_parses_to_empty_answer_not_exception(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"q": "not_a_dict"}}).encode()
            )
            result = jev_backend.call_systemone(
                state="x", questions={"q": {"type": "noul", "instructions": "?"}}, config=_VALID_CONFIG,
            )
        assert result.failure_reason == ""
        assert result.answers["q"].type == ""
        assert result.answers["q"].noul is None


# ── Question builders ──────────────────────────────────────────────────────

class TestQuestionBuilders:
    def test_build_noul_question_shape(self):
        question = jev_backend.build_noul_question("Is this urgent?", {"true": "yes", "false": "no"})
        assert question == {
            "type": "noul",
            "instructions": "Is this urgent?",
            "criteria": {"true": "yes", "false": "no"},
        }

    def test_build_noul_question_without_criteria(self):
        question = jev_backend.build_noul_question("Is this urgent?")
        assert question == {"type": "noul", "instructions": "Is this urgent?"}

    def test_build_choice_question_bounds_255_options(self):
        criteria = {f"option_{i}": None for i in range(300)}
        question = jev_backend.build_choice_question("pick one", criteria)
        assert len(question["criteria"]) == jev_backend.MAX_CHOICE_OPTIONS

    def test_build_score_question_requires_2_to_10_levels(self):
        with pytest.raises(ValueError):
            jev_backend.build_score_question("rate it", ["only one level"])

    def test_build_score_question_bounds_at_10_levels(self):
        levels = [f"level_{i}" for i in range(20)]
        question = jev_backend.build_score_question("rate it", levels)
        assert len(question["criteria"]) == jev_backend.MAX_SCORE_LEVELS


# ── State defensive clipping (INV-5) ────────────────────────────────────────

class TestStateClipping:
    def test_long_string_state_is_clipped(self):
        long_text = "x" * 10000
        clipped = jev_backend._clip_state(long_text)
        assert len(clipped) == jev_backend._MAX_STATE_STRING_CHARS

    def test_long_dict_values_are_clipped(self):
        clipped = jev_backend._clip_state({"body": "y" * 10000})
        assert len(clipped["body"]) == jev_backend._MAX_STATE_STRING_CHARS

    def test_nested_record_shapes_are_clipped(self):
        """#97 review counterfactual: J2 sends {"record_a": {...}, ...}; the
        top-level-only clip returned nested dicts untouched, so this floor
        did nothing on that call path."""
        state = {
            "record_a": {"kind": "fact", "tags": ["t" * 50000], "body": "Y" * 50000},
            "record_b": {"kind": "fact", "tags": [], "body": "Z" * 50000},
        }
        clipped = jev_backend._clip_state(state)
        limit = jev_backend._MAX_STATE_STRING_CHARS
        assert len(clipped["record_a"]["body"]) == limit
        assert len(clipped["record_a"]["tags"][0]) == limit
        assert len(clipped["record_b"]["body"]) == limit

    def test_containers_below_the_depth_ceiling_are_dropped(self):
        deep = {"a": {"b": {"c": {"d": {"e": "x" * 50000}}}}}
        clipped = jev_backend._clip_state(deep)
        assert clipped["a"]["b"]["c"]["d"] is None

    def test_call_systemone_clips_a_j2_shaped_state_even_without_the_call_site_slice(self):
        """The floor must hold on its own: J2's state builder slices bodies to
        500 today, but the gate exists for the day that slice is lost."""
        from plugins.memory.memory_os import llm_edge_proposer

        captured = {}

        def _capture_urlopen(request, timeout=None):
            captured["body"] = request.data
            return _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"q": {"type": "noul", "noul": 0.5}}}).encode()
            )

        record = {"id": "r1", "kind": "fact", "tags_json": "[]", "body": "b" * 50000}
        state = llm_edge_proposer._build_jev_choice_state(record, record)
        state["record_a"]["body"] = "b" * 50000  # simulate a builder that stopped slicing
        with patch("urllib.request.urlopen", side_effect=_capture_urlopen):
            jev_backend.call_systemone(
                state=state,
                questions={"q": {"type": "noul", "instructions": "?"}},
                config=_VALID_CONFIG,
            )
        sent_payload = json.loads(captured["body"])
        assert len(sent_payload["state"]["record_a"]["body"]) == jev_backend._MAX_STATE_STRING_CHARS

    def test_call_systemone_clips_oversized_state_before_sending(self):
        """Counterfactual: without _clip_state in call_systemone, the full
        oversized payload would be sent to json.dumps/urlopen."""
        captured = {}

        def _capture_urlopen(request, timeout=None):
            captured["body"] = request.data
            return _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"q": {"type": "noul", "noul": 0.5}}}).encode()
            )

        with patch("urllib.request.urlopen", side_effect=_capture_urlopen):
            jev_backend.call_systemone(
                state={"candidate_body": "z" * 50000},
                questions={"q": {"type": "noul", "instructions": "?"}},
                config=_VALID_CONFIG,
            )
        sent_payload = json.loads(captured["body"])
        assert len(sent_payload["state"]["candidate_body"]) == jev_backend._MAX_STATE_STRING_CHARS


# ── judge_noul convenience wrapper ──────────────────────────────────────────

class TestJudgeNoul:
    def test_high_probability_above_threshold_is_true(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"durable_fact": {"type": "noul", "noul": 0.9}}}).encode()
            )
            result = jev_backend.judge_noul(
                question_id="durable_fact",
                instructions="is it durable?",
                criteria={"true": "yes", "false": "no"},
                state="x",
                threshold=0.5,
                config=_VALID_CONFIG,
            )
        assert result.label == "true"
        assert result.probability == 0.9
        assert result.confidence == pytest.approx(0.8, abs=1e-6)
        assert result.failure_reason == ""

    def test_low_probability_below_threshold_is_false(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"durable_fact": {"type": "noul", "noul": 0.02}}}).encode()
            )
            result = jev_backend.judge_noul(
                question_id="durable_fact",
                instructions="is it durable?",
                criteria=None,
                state="x",
                threshold=0.5,
                config=_VALID_CONFIG,
            )
        assert result.label == "false"
        assert result.probability == 0.02

    def test_threshold_is_configurable_and_respected(self):
        """probability 0.45 is 'false' at threshold 0.5 but 'true' at 0.4 --
        counterfactual for the lean/strict asymmetry fact_judge relies on."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"durable_fact": {"type": "noul", "noul": 0.45}}}).encode()
            )
            result_strict = jev_backend.judge_noul(
                question_id="durable_fact", instructions="?", criteria=None, state="x",
                threshold=0.5, config=_VALID_CONFIG,
            )
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"durable_fact": {"type": "noul", "noul": 0.45}}}).encode()
            )
            result_lean = jev_backend.judge_noul(
                question_id="durable_fact", instructions="?", criteria=None, state="x",
                threshold=0.4, config=_VALID_CONFIG,
            )
        assert result_strict.label == "false"
        assert result_lean.label == "true"

    def test_failure_propagates_with_empty_label(self):
        with patch("urllib.request.urlopen", side_effect=_fake_http_error(401)):
            result = jev_backend.judge_noul(
                question_id="durable_fact", instructions="?", criteria=None, state="x",
                config=_VALID_CONFIG,
            )
        assert result.label == ""
        assert result.confidence is None
        assert result.failure_reason == "llm_missing_key"

    def test_missing_question_id_in_answers_is_llm_parse_failed(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"some_other_id": {"type": "noul", "noul": 0.9}}}).encode()
            )
            result = jev_backend.judge_noul(
                question_id="durable_fact", instructions="?", criteria=None, state="x",
                config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_parse_failed"

    def test_non_noul_answer_type_is_llm_parse_failed(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {"durable_fact": {"type": "choice", "choice": "x"}},
                }).encode()
            )
            result = jev_backend.judge_noul(
                question_id="durable_fact", instructions="?", criteria=None, state="x",
                config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_parse_failed"

    def test_answer_with_a_noul_value_but_another_declared_type_is_rejected(self):
        """A stray noul field on an answer whose declared type is not noul
        (API drift / malformed body) must not be read as a noul judgment."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {"durable_fact": {"type": "choice", "choice": "x", "noul": 0.9}},
                }).encode()
            )
            result = jev_backend.judge_noul(
                question_id="durable_fact", instructions="?", criteria=None, state="x",
                config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_parse_failed"

    def test_out_of_range_probability_is_clamped(self):
        """Defensive clamp: a probability outside [0,1] (shouldn't happen per
        the API contract, but never trust an external response blindly)."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({"model": "jev-1.13.0", "answers": {"durable_fact": {"type": "noul", "noul": 1.5}}}).encode()
            )
            result = jev_backend.judge_noul(
                question_id="durable_fact", instructions="?", criteria=None, state="x",
                config=_VALID_CONFIG,
            )
        assert result.probability == 1.0
        assert result.confidence == 1.0


# ── judge_choice convenience wrapper (J2) ────────────────────────────────

class TestJudgeChoice:
    def test_successful_choice_returns_native_confidence_and_probabilities(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {
                        "relation_type": {
                            "type": "choice",
                            "choice": "refines",
                            "confidence": 0.94,
                            "probabilities": {"refines": 0.94, "none": 0.06},
                        }
                    },
                }).encode()
            )
            result = jev_backend.judge_choice(
                question_id="relation_type",
                instructions="pick one",
                criteria={"refines": "a", "none": "b"},
                state={"record_a": {}, "record_b": {}},
                config=_VALID_CONFIG,
            )
        assert result.choice == "refines"
        assert result.confidence == 0.94
        assert result.probabilities == {"refines": 0.94, "none": 0.06}
        assert result.failure_reason == ""

    def test_failure_propagates_with_empty_choice(self):
        with patch("urllib.request.urlopen", side_effect=_fake_http_error(401)):
            result = jev_backend.judge_choice(
                question_id="relation_type", instructions="?",
                criteria={"a": "x", "b": "y"}, state="x", config=_VALID_CONFIG,
            )
        assert result.choice == ""
        assert result.confidence is None
        assert result.failure_reason == "llm_missing_key"

    def test_missing_question_id_in_answers_is_llm_parse_failed(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {"some_other_id": {"type": "choice", "choice": "a"}},
                }).encode()
            )
            result = jev_backend.judge_choice(
                question_id="relation_type", instructions="?",
                criteria={"a": "x"}, state="x", config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_parse_failed"

    def test_non_choice_answer_type_is_llm_parse_failed(self):
        """A stray 'choice' field on an answer declared some other type
        (API drift / malformed body) must not be read as a choice judgment
        -- same-shaped guard as judge_noul's own type check."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {"relation_type": {"type": "noul", "noul": 0.9, "choice": "a"}},
                }).encode()
            )
            result = jev_backend.judge_choice(
                question_id="relation_type", instructions="?",
                criteria={"a": "x"}, state="x", config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_parse_failed"

    def test_empty_choice_string_is_llm_parse_failed(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {"relation_type": {"type": "choice", "choice": ""}},
                }).encode()
            )
            result = jev_backend.judge_choice(
                question_id="relation_type", instructions="?",
                criteria={"a": "x"}, state="x", config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_parse_failed"

    def test_choice_outside_offered_options_is_llm_parse_failed(self):
        """Counterfactual: without the criteria-membership check, a choice
        the API returns that is not one of the offered options would be
        trusted verbatim -- e.g. hallucinated or drifted vocabulary."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(
                json.dumps({
                    "model": "jev-1.13.0",
                    "answers": {"relation_type": {"type": "choice", "choice": "not_offered"}},
                }).encode()
            )
            result = jev_backend.judge_choice(
                question_id="relation_type", instructions="?",
                criteria={"a": "x", "b": "y"}, state="x", config=_VALID_CONFIG,
            )
        assert result.failure_reason == "llm_parse_failed"
        assert result.choice == ""


# ── Closed failure-reason vocabulary ─────────────────────────────────────

class TestFailureVocabulary:
    def test_jev_failure_reasons_is_superset_of_shared_vocabulary(self):
        from plugins.memory.memory_os.low_clue_recall import LLM_CALL_FAILURE_REASONS
        assert LLM_CALL_FAILURE_REASONS.issubset(jev_backend.JEV_CALL_FAILURE_REASONS)

    def test_jev_failure_reasons_includes_overloaded_and_parse_failed(self):
        assert "llm_overloaded" in jev_backend.JEV_CALL_FAILURE_REASONS
        assert "llm_parse_failed" in jev_backend.JEV_CALL_FAILURE_REASONS
