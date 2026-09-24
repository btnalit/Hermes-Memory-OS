"""Optional, default-off TypeSafe "Jev" structured-judgment backend.

Jev (https://docs.typesafe.ai/) is a hosted "System One" judgment model
reached over a single HTTP endpoint, ``POST https://api.typesafe.ai/v1/systemone``.
Unlike the free-text chat-completion seam in ``low_clue_recall.py``, Jev
takes typed *questions* -- noul (yes/no probability), choice (pick one of up
to 255 options), score (rate against 2-10 ordered levels) -- each carrying
``instructions`` + ``criteria`` describing exactly what the judgment means.
This module is the ONLY place in Memory-OS that knows Jev's wire format.

Status: OPTIONAL, DEFAULT OFF (owner ruling 2026-09-23, next-phase plan
rows J1/J2, ``docs/plans/2026-09-23-memory-os-next-phase-plan.md``). No lane
calls this module unless it explicitly opts in via its own
``<lane>_judge_backend`` knob -- see ``plugins/modules/governance/fact_judge.py``
(J1, native noul) and ``plugins/memory/memory_os/llm_edge_proposer.py`` (J2,
native choice) for the two wired callers. Importing this module has zero
side effects and makes zero network calls; nothing here runs unless a
caller invokes one of its functions.

INV-5: like every LLM-shaped call in this codebase, this backend belongs in
an offline cron lane only -- never on the hot path (prefetch / sync_turn /
heartbeat).

Credential handling follows the Hindsight substrate convention (see
``substrates/hindsight.py`` / ``adapters/hindsight.py``): config carries
only the environment-variable NAME (``api_key_env_var``, default
``"TYPESAFE_API_KEY"``); the value itself lives in Hermes' ``~/.hermes/.env``
on a host and is read at call time from ``os.environ``, falling back to
Hermes' own reader ``hermes_cli.config.get_env_value`` for processes whose
environment was not built from ``.env`` (see ``_hermes_env_value``). This module never
accepts a raw key string in config, never logs it, and never includes it in
any returned/report field.

Transport: stdlib ``urllib.request`` only (matches
``adapters/hindsight.py``'s ``HindsightHttpClient``) -- no new SDK/HTTP
dependency. No provider special-casing lives in the general call_llm seam
(``low_clue_recall.py``); Jev is a wholly separate wire in its own file, per
the owner's instruction that the two never mix.

Docs consulted 2026-09-23: https://docs.typesafe.ai/ , /api.md ,
/introduction/quickstart.md , /concepts/state.md , /primitives.md ,
/primitives/noul.md , /primitives/choice.md , /confidence.md , /models.md ,
/primitives/advanced.md , /sdk/python/api/retries.md . Live-verified against
the real endpoint with a handful of synthetic calls. One documented-vs-live
discrepancy found: the
docs claim a malformed question returns HTTP 422; live, it returned HTTP 400
with the same ``{"detail": {"error_type": ..., "message": ...}}`` error
envelope. Both fold into the generic 4xx bucket below, so this does not
affect correctness -- recorded here as a verified-live fact overriding the
doc claim.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .low_clue_recall import LLM_CALL_FAILURE_REASONS, _hermes_host_import_scope

# ── Wire constants ───────────────────────────────────────────────────────
JEV_API_URL_DEFAULT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL_DEFAULT = "jev-latest"
JEV_API_KEY_ENV_VAR_DEFAULT = "TYPESAFE_API_KEY"
JEV_BACKEND_NAME = "typesafe_jev"

# Closed failure-reason set for this backend. Reuses the shared transport
# vocabulary (low_clue_recall.LLM_CALL_FAILURE_REASONS) where it fits, plus
# two Jev-specific additions the shared set has no slot for:
#   - "llm_overloaded": HTTP 529 ("Overloaded"), documented by TypeSafe as a
#     distinct condition -- callers should treat it like a rate limit
#     (backoff), not fold it into a generic 4xx/5xx bucket.
#   - "llm_parse_failed": the HTTP call succeeded but the response body was
#     not valid JSON, lacked an "answers" object, or lacked our question id.
#     This is the *transport* layer's parse failure (response envelope), not
#     a caller's answer-semantics failure -- kept distinct from fact_judge's
#     own like-named vocabulary for the same reason _call_diagnostics keeps
#     low_clue_recall's llm_missing_key separate from fact_judge's.
JEV_CALL_FAILURE_REASONS = frozenset(
    LLM_CALL_FAILURE_REASONS | {"llm_overloaded", "llm_rate_limited", "llm_parse_failed"}
)

# Defensive input bound (INV-5 corollary: always bound the input,
# independent of what a caller already clipped -- see CLAUDE.md's "a single
# production session message has been measured at 975,665 characters"
# note). Callers such as fact_judge additionally clip upstream; this is a
# second, independent floor so this module is safe standing alone.
_MAX_STATE_STRING_CHARS = 4000
_MAX_STATE_ITEMS = 20
_MAX_STATE_DEPTH = 4
_MAX_INSTRUCTIONS_CHARS = 2000

MAX_CHOICE_OPTIONS = 255
MIN_SCORE_LEVELS = 2
MAX_SCORE_LEVELS = 10


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit]


def _clip_state(state: Any, _depth: int = 0) -> Any:
    """Independent defensive bound on the ``state`` payload (INV-5).

    Recurses: J2 sends ``{"record_a": {"kind", "tags", "body"}, ...}``, and a
    top-level-only clip let a nested body through untouched. Every string at
    any depth is clipped and every collection truncated; containers nested
    deeper than ``_MAX_STATE_DEPTH`` are dropped rather than sent unbounded.
    """
    if isinstance(state, str):
        return _clip(state, _MAX_STATE_STRING_CHARS)
    if isinstance(state, (dict, list, tuple)) and _depth >= _MAX_STATE_DEPTH:
        return None
    if isinstance(state, dict):
        return {
            str(key): _clip_state(value, _depth + 1)
            for key, value in list(state.items())[:_MAX_STATE_ITEMS]
        }
    if isinstance(state, (list, tuple)):
        return [_clip_state(value, _depth + 1) for value in list(state)[:_MAX_STATE_ITEMS]]
    return state


# ── Typed answer / call result shapes ───────────────────────────────────

@dataclass(frozen=True)
class JevAnswer:
    """Raw parsed answer for one question -- before any caller-specific
    label/threshold derivation. ``type`` mirrors the API's own answer type
    (noul/choice/score)."""

    type: str = ""
    noul: float | None = None
    choice: str | None = None
    score: float | None = None
    legend: dict[str, str] | None = None
    probabilities: dict[str, float] | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class JevCallResult:
    """Typed result of one ``/v1/systemone`` call. Never raises -- every
    failure (missing key, network, HTTP status, malformed response) is
    represented here instead of raising or returning an indistinguishable
    empty value (see CLAUDE.md "Completion Is Not Output").

    ``answers`` is the raw ``{question_id: JevAnswer}`` map on success.
    """

    answers: dict[str, JevAnswer] | None = None
    failure_reason: str = ""
    detail: str = ""
    model: str | None = None
    latency_ms: float | None = None
    usage: dict[str, int] | None = None
    backend: str = JEV_BACKEND_NAME


# ── Native question builders (noul / choice / score) ────────────────────

def build_noul_question(instructions: str, criteria: dict[str, str] | None = None) -> dict[str, Any]:
    """Build a native ``noul`` (yes/no probability) question.

    Per https://docs.typesafe.ai/primitives/noul.md, ``criteria`` is
    optional and only needs ``true``/``false`` boundary descriptions.
    """
    question: dict[str, Any] = {"type": "noul", "instructions": _clip(instructions, _MAX_INSTRUCTIONS_CHARS)}
    if criteria:
        question["criteria"] = {
            "true": _clip(criteria.get("true"), _MAX_INSTRUCTIONS_CHARS),
            "false": _clip(criteria.get("false"), _MAX_INSTRUCTIONS_CHARS),
        }
    return question


def build_choice_question(instructions: str, criteria: dict[str, str | None]) -> dict[str, Any]:
    """Build a native ``choice`` question. Max 255 options (silently bounded,
    not raised -- an over-long option map is a caller bug, not a runtime
    failure worth crashing an offline lane over)."""
    bounded_options = list(criteria.items())[:MAX_CHOICE_OPTIONS]
    return {
        "type": "choice",
        "instructions": _clip(instructions, _MAX_INSTRUCTIONS_CHARS),
        "criteria": {
            str(option): (_clip(description, _MAX_INSTRUCTIONS_CHARS) if description else None)
            for option, description in bounded_options
        },
    }


def build_score_question(instructions: str, levels: list[str]) -> dict[str, Any]:
    """Build a native ``score`` question. Requires 2-10 ordered levels."""
    bounded_levels = [str(level) for level in levels][:MAX_SCORE_LEVELS]
    if len(bounded_levels) < MIN_SCORE_LEVELS:
        raise ValueError(
            f"score question requires {MIN_SCORE_LEVELS}-{MAX_SCORE_LEVELS} levels, got {len(bounded_levels)}"
        )
    return {
        "type": "score",
        "instructions": _clip(instructions, _MAX_INSTRUCTIONS_CHARS),
        "criteria": bounded_levels,
    }


# ── Answer parsing (all three primitives) ────────────────────────────────

def _parse_answer(raw: Any) -> JevAnswer:
    if not isinstance(raw, dict):
        return JevAnswer()
    answer_type = str(raw.get("type") or "")
    probabilities_raw = raw.get("probabilities")
    probabilities = (
        {str(k): float(v) for k, v in probabilities_raw.items() if isinstance(v, (int, float))}
        if isinstance(probabilities_raw, dict)
        else None
    )
    legend_raw = raw.get("legend")
    legend = {str(k): str(v) for k, v in legend_raw.items()} if isinstance(legend_raw, dict) else None
    noul_raw = raw.get("noul")
    score_raw = raw.get("score")
    confidence_raw = raw.get("confidence")
    return JevAnswer(
        type=answer_type,
        noul=float(noul_raw) if isinstance(noul_raw, (int, float)) else None,
        choice=str(raw.get("choice")) if raw.get("choice") is not None else None,
        score=float(score_raw) if isinstance(score_raw, (int, float)) else None,
        legend=legend,
        probabilities=probabilities or None,
        confidence=float(confidence_raw) if isinstance(confidence_raw, (int, float)) else None,
    )


# ── Credentials + limits ─────────────────────────────────────────────────

def _import_hermes_get_env_value() -> Any:
    from hermes_cli.config import get_env_value

    return get_env_value


def _hermes_env_value(env_var: str) -> tuple[str, str]:
    """Read ``env_var`` through Hermes' own credential reader,
    ``hermes_cli.config.get_env_value`` (``os.environ``, then
    ``<HERMES_HOME>/.env``) -- the same call Hermes' ``web_search_provider``
    uses for third-party keys. Called, never modified: Memory-OS owns no
    ``.env`` parser of its own.

    Needed because not every process that runs a Jev lane has ``.env`` in
    its environment: Hermes cron children do (the scheduler builds their env
    from it), but the cognitive-loop systemd launcher only exports
    ``HERMES_HOME``/``PYTHONPATH``, so ``llm_edge_proposer`` saw no key there.

    Returns ``(value, detail)``. ``detail`` names why no value came back and
    never contains the value itself.
    """
    with _hermes_host_import_scope(_import_hermes_get_env_value) as (get_env_value, import_detail):
        if get_env_value is None:
            return "", _clip(f"hermes_env_loader_unavailable: {import_detail}", 160)
        try:
            value = str(get_env_value(env_var) or "").strip()
        except Exception as exc:
            # Type name only: a message from a credential reader is not
            # something to copy into a report.
            return "", f"hermes_env_loader_failed: {type(exc).__name__}"
    if not value:
        return "", "not_in_environ_or_hermes_env"
    return value, ""


def _resolve_api_key(config: dict[str, Any]) -> tuple[str, str, str]:
    """Returns ``(api_key, failure_reason, detail)``; ``failure_reason`` is
    ``""`` on success. Makes NO network call -- a missing key must be a typed
    ``llm_missing_key`` with zero HTTP activity. ``detail`` separates "the
    key is not configured" from "Hermes' reader could not be loaded" without
    ever carrying the key.

    ``os.environ`` is checked first so a process that already has the key
    (Hermes cron children) never imports ``hermes_cli``; only a miss falls
    through to :func:`_hermes_env_value`."""
    env_var = str(config.get("api_key_env_var") or JEV_API_KEY_ENV_VAR_DEFAULT).strip()
    if not env_var:
        return "", "llm_missing_key", "api_key_env_var not configured"
    key = str(os.environ.get(env_var) or "").strip()
    if key:
        return key, "", ""
    key, detail = _hermes_env_value(env_var)
    if not key:
        return "", "llm_missing_key", detail
    return key, "", ""


def _call_limits(config: dict[str, Any]) -> float | None:
    """Timeout in seconds, or ``None`` if not numeric -- the caller must
    return a typed failure, never raise."""
    try:
        return max(float(config.get("timeout_ms") or 8000) / 1000.0, 0.1)
    except (TypeError, ValueError):
        return None


def _classify_http_status(status_code: int) -> str:
    """Map an HTTP status to the closed JEV_CALL_FAILURE_REASONS set.

    401 -> llm_missing_key (bad/rejected credential); 529 -> llm_overloaded
    (explicit, not folded into a generic bucket -- TypeSafe's own docs treat
    it as distinct from 4xx/429); 429 -> llm_rate_limited (back off -- an
    operator must be able to tell "we are being throttled" from "our request
    is malformed" without re-running anything); any other 4xx (400 observed
    live, 422 documented) -> llm_http_4xx; anything else (undocumented 5xx) ->
    llm_exception, the same generic fallback low_clue_recall's classifier
    uses for cases outside its documented contract.
    """
    if status_code == 401:
        return "llm_missing_key"
    if status_code == 529:
        return "llm_overloaded"
    if status_code == 429:
        return "llm_rate_limited"
    if 400 <= status_code < 500:
        return "llm_http_4xx"
    return "llm_exception"


# ── Transport: POST /v1/systemone ────────────────────────────────────────

def call_systemone(
    *,
    state: Any,
    questions: dict[str, dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> JevCallResult:
    """Call ``POST /v1/systemone`` with one or more typed questions.

    Never raises. ``config`` keys: ``api_url``, ``model``,
    ``api_key_env_var``, ``timeout_ms``. A missing/blank API key resolves
    before any network activity (``llm_missing_key``, zero calls made).
    """
    effective = config or {}

    api_key, key_failure, key_detail = _resolve_api_key(effective)
    if key_failure:
        return JevCallResult(failure_reason=key_failure, detail=key_detail)

    timeout_s = _call_limits(effective)
    if timeout_s is None:
        return JevCallResult(failure_reason="llm_exception", detail="invalid_call_config: timeout_ms")

    api_url = str(effective.get("api_url") or JEV_API_URL_DEFAULT)
    model = str(effective.get("model") or JEV_MODEL_DEFAULT)

    payload = {"state": _clip_state(state), "model": model, "questions": questions}
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        return JevCallResult(
            failure_reason="llm_exception",
            detail=_clip(f"payload_not_json_serializable: {exc}", 160),
        )

    request = urllib.request.Request(
        api_url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            latency_ms = round((time.monotonic() - start) * 1000.0, 1)
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.monotonic() - start) * 1000.0, 1)
        try:
            detail_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail_body = ""
        return JevCallResult(
            failure_reason=_classify_http_status(exc.code),
            detail=_clip(f"HTTP {exc.code}: {detail_body}", 200),
            latency_ms=latency_ms,
        )
    except urllib.error.URLError as exc:
        latency_ms = round((time.monotonic() - start) * 1000.0, 1)
        reason_text = str(getattr(exc, "reason", exc)).lower()
        reason = "llm_timeout" if "timed out" in reason_text or "timeout" in reason_text else "llm_transport_unavailable"
        return JevCallResult(failure_reason=reason, detail=_clip(f"URLError: {exc.reason}", 160), latency_ms=latency_ms)
    except TimeoutError:
        latency_ms = round((time.monotonic() - start) * 1000.0, 1)
        return JevCallResult(failure_reason="llm_timeout", detail="socket_timeout", latency_ms=latency_ms)
    except Exception as exc:  # defensive only -- this transport must never raise
        latency_ms = round((time.monotonic() - start) * 1000.0, 1)
        return JevCallResult(
            failure_reason="llm_exception",
            detail=_clip(f"{type(exc).__name__}: {exc}", 160),
            latency_ms=latency_ms,
        )

    try:
        parsed = json.loads(body) if body.strip() else None
    except json.JSONDecodeError:
        return JevCallResult(failure_reason="llm_parse_failed", detail="response_not_json", latency_ms=latency_ms)
    if not isinstance(parsed, dict):
        return JevCallResult(failure_reason="llm_parse_failed", detail="response_not_object", latency_ms=latency_ms)

    raw_answers = parsed.get("answers")
    if not isinstance(raw_answers, dict) or not raw_answers:
        return JevCallResult(
            failure_reason="llm_empty_content",
            detail="no_answers_in_response",
            model=str(parsed.get("model") or "") or None,
            latency_ms=latency_ms,
        )

    answers = {str(key): _parse_answer(value) for key, value in raw_answers.items()}

    usage_raw = parsed.get("usage")
    usage: dict[str, int] | None = None
    if isinstance(usage_raw, dict):
        usage = {}
        for source_key, dest_key in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
            value = usage_raw.get(source_key)
            try:
                if value is not None:
                    usage[dest_key] = int(value)
            except (TypeError, ValueError):
                pass
        usage = usage or None

    return JevCallResult(
        answers=answers,
        model=str(parsed.get("model") or model) or None,
        latency_ms=latency_ms,
        usage=usage,
    )


# ── Convenience: single-noul-question judgment ───────────────────────────

@dataclass(frozen=True)
class JevJudgmentResult:
    """Unified judgement shape for a single native noul (yes/no) question.

    ``label`` is ``"true"``/``"false"`` after thresholding, ``""`` on
    failure -- callers must never treat an empty label as a "false" answer.

    ``confidence`` is DERIVED, not native: TypeSafe's own docs state noul
    answers carry no confidence field (only choice/score do, because
    confidence there collapses a multi-option probability distribution).
    We derive an analogous 0..1 certainty from the noul probability's
    distance from 0.5 (``2 * |p - 0.5|``), matching the docs' own framing
    that concentration vs. a flat distribution is what confidence measures.
    """

    label: str = ""
    confidence: float | None = None
    probability: float | None = None
    failure_reason: str = ""
    detail: str = ""
    backend: str = JEV_BACKEND_NAME
    model: str | None = None
    latency_ms: float | None = None
    usage: dict[str, int] | None = None


def judge_noul(
    *,
    question_id: str,
    instructions: str,
    criteria: dict[str, str] | None,
    state: Any,
    threshold: float = 0.5,
    config: dict[str, Any] | None = None,
) -> JevJudgmentResult:
    """Ask one native noul question and derive a thresholded true/false label.

    Never raises. On any failure, ``failure_reason`` is set (drawn from
    ``JEV_CALL_FAILURE_REASONS``) and ``label``/``confidence``/``probability``
    stay at their empty defaults -- callers must treat that as "fall back",
    never as a false answer.
    """
    question = build_noul_question(instructions, criteria)
    result = call_systemone(state=state, questions={question_id: question}, config=config)
    if result.failure_reason:
        return JevJudgmentResult(
            failure_reason=result.failure_reason,
            detail=result.detail,
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
        )

    answer = (result.answers or {}).get(question_id)
    if answer is None or answer.type != "noul" or answer.noul is None:
        return JevJudgmentResult(
            failure_reason="llm_parse_failed",
            detail=f"missing_or_non_noul_answer_for:{question_id}",
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
        )

    probability = max(0.0, min(1.0, answer.noul))
    confidence = round(abs(probability - 0.5) * 2.0, 4)
    label = "true" if probability >= threshold else "false"
    return JevJudgmentResult(
        label=label,
        confidence=confidence,
        probability=probability,
        failure_reason="",
        model=result.model,
        latency_ms=result.latency_ms,
        usage=result.usage,
    )


# ── Convenience: single-choice-question judgment (J2) ────────────────────

@dataclass(frozen=True)
class JevChoiceResult:
    """Unified judgement shape for a single native choice (pick-one) question.

    ``choice`` is the selected option -- guaranteed to be one of *criteria*'s
    keys on success (see the wire-contract check in :func:`judge_choice`) --
    or ``""`` on failure. Callers must never treat an empty choice as a
    valid selection.

    ``confidence`` is NATIVE here (unlike :class:`JevJudgmentResult`'s
    derived value for noul): per https://docs.typesafe.ai/primitives/choice.md
    the choice primitive returns confidence directly, reflecting how
    concentrated the returned probability distribution is over the offered
    options ("a single peak on one option means high confidence").
    """

    choice: str = ""
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    legend: dict[str, str] | None = None
    failure_reason: str = ""
    detail: str = ""
    backend: str = JEV_BACKEND_NAME
    model: str | None = None
    latency_ms: float | None = None
    usage: dict[str, int] | None = None


def judge_choice(
    *,
    question_id: str,
    instructions: str,
    criteria: dict[str, str | None],
    state: Any,
    config: dict[str, Any] | None = None,
) -> JevChoiceResult:
    """Ask one native choice question and return the selected option.

    Never raises. On any failure, ``failure_reason`` is set (drawn from
    ``JEV_CALL_FAILURE_REASONS``) and ``choice``/``confidence`` stay at
    their empty defaults -- callers must treat that as "fall back", never
    as a valid selection.

    Two wire-contract checks, mirroring the same-shaped guards in
    :func:`judge_noul` for its own primitive: the declared answer ``type``
    must be exactly ``"choice"`` (a stray ``choice`` field on an answer
    declared some other type must not be read as a choice judgment), and
    the returned ``choice`` must be one of *criteria*'s own keys -- Jev's
    own closed option set for this question, not a caller-specific
    vocabulary, so this check stays generic. Both violations are
    ``llm_parse_failed``.
    """
    question = build_choice_question(instructions, criteria)
    result = call_systemone(state=state, questions={question_id: question}, config=config)
    if result.failure_reason:
        return JevChoiceResult(
            failure_reason=result.failure_reason,
            detail=result.detail,
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
        )

    answer = (result.answers or {}).get(question_id)
    if answer is None or answer.type != "choice" or not answer.choice:
        return JevChoiceResult(
            failure_reason="llm_parse_failed",
            detail=f"missing_or_non_choice_answer_for:{question_id}",
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
        )
    if answer.choice not in question["criteria"]:
        return JevChoiceResult(
            failure_reason="llm_parse_failed",
            detail=_clip(f"choice_outside_offered_options:{answer.choice}", 200),
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
        )

    return JevChoiceResult(
        choice=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        legend=answer.legend,
        failure_reason="",
        model=result.model,
        latency_ms=result.latency_ms,
        usage=result.usage,
    )
