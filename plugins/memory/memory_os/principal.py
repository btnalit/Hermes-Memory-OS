"""Principal resolution -- the single authority for "who is this turn from".

2026-09-23 owner ruling (P0-lite, ``docs/plans/2026-09-23-memory-os-next-phase-plan.md``
S2/S3): PR #82 (``cf80d9c``/``f334773``) introduced ``ingress.author_class``
(human/bot/unknown) to stop another agent's turn from steering the owner's
foreground task, but ``human`` is only "the host admitted a non-bot author" --
never a verified owner identity. This module adds that verification, without
touching the ``author_class`` closed set PR #82 already shipped: every call
site that used to gate on ``author_class`` must call ``resolve_principal``
instead, which folds ``author_class`` in as one of several signals.

The closed principal set is ``owner | peer_agent | other_human | system |
unknown``. ``unknown`` is deliberately still "may drive foreground control" --
it is the pre-2026-09 compatibility state for a platform nobody has
configured an owner identity for, not a rejection. Only ``owner`` and
``unknown`` may drive foreground control, owner-review replies, or working
memory/candidate admission; ``peer_agent``, ``other_human``, and ``system``
never may (see ``FOREGROUND_CONTROL_PRINCIPALS``).

No claim-code / pairing flow (owner ruling): auto-binding only reads signals
an operator already wrote into the target Hermes host's own config
(``discover_owner_identity_bindings``). This module owns that decision (P4:
"判定只在 principal.py 一处") but does not talk to disk itself for the
*runtime* decision -- ``resolve_principal`` is a pure function over its
arguments, so it can be unit-tested without a filesystem and reused by the
provider, the router, and (later) session_fact_extraction (Phase 2 P3) without
each of them re-deriving the rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ingress import (
    AUTHOR_CLASS_BOT,
    AUTHOR_CLASS_UNKNOWN,
    is_scheduled_session_id,
)

# ── Closed principal set ─────────────────────────────────────────────────
PRINCIPAL_OWNER = "owner"
PRINCIPAL_PEER_AGENT = "peer_agent"
PRINCIPAL_OTHER_HUMAN = "other_human"
PRINCIPAL_SYSTEM = "system"
PRINCIPAL_UNKNOWN = "unknown"
PRINCIPALS = frozenset(
    {PRINCIPAL_OWNER, PRINCIPAL_PEER_AGENT, PRINCIPAL_OTHER_HUMAN, PRINCIPAL_SYSTEM, PRINCIPAL_UNKNOWN}
)

# Only these two may drive foreground control, owner-review replies, or
# working-memory/candidate admission. ``unknown`` is compatibility, not
# trust: it is what an unconfigured platform resolves to, matching PR #82's
# pre-P0-lite behaviour (human/unknown could steer the foreground task).
#
# ``ingress.py`` keeps its own copy of these two literals
# (``_FOREGROUND_CONTROL_PRINCIPALS``) rather than importing this frozenset:
# this module already imports from ``ingress`` (``is_scheduled_session_id``,
# ``AUTHOR_CLASS_*``), so the reverse import would cycle. Kept in sync by
# ``test_ingress_foreground_control_principals_match_principal_module`` in
# ``tests/plugins/memory/test_memory_os_principal.py``.
FOREGROUND_CONTROL_PRINCIPALS = frozenset({PRINCIPAL_OWNER, PRINCIPAL_UNKNOWN})

# Only these two may perform an owner action (approve / reject / feedback /
# allow / bounded apply, via ``owner_actions.parse_owner_review_reply``) or see
# a live ``oa_``/``ppmt_`` action token on the owner-review surface (Phase 2
# P1, 2026-09-23 next-phase plan). Same value as ``FOREGROUND_CONTROL_PRINCIPALS``
# today, but named and owned separately: owner-action authority and
# foreground-control eligibility are different policy questions that happen to
# agree right now, and giving them one shared name would make a future
# deliberate divergence (e.g. tightening owner actions without touching
# foreground control) silently move both.
#
# ``unknown`` is allowed for the same reason as everywhere else in this
# module: on a platform the owner never configured an identity for, the
# owner's own replies resolve to ``unknown`` (compatibility, not a stranger),
# and rejecting it would lock the owner out of approving/rejecting their own
# digest. This is a deliberate trade-off, not an oversight -- an action taken
# under ``unknown`` is still recorded with that principal on the audit trail
# (see ``owner_actions.parse_owner_review_reply``), so it stays visible for a
# monitor to grade, rather than being silently indistinguishable from a
# verified owner.
OWNER_ACTION_PRINCIPALS = frozenset({PRINCIPAL_OWNER, PRINCIPAL_UNKNOWN})

# Sources whose author is the operator's own local shell/tool session.
# 2026-09-23 owner ruling: anyone who can already reach a local shell has
# higher privilege than the conversational owner gate exists to enforce, so
# these bind to owner unconditionally -- ahead of the mailbox/bot checks
# below, matching the ruling's own listed order.
LOCAL_OWNER_SOURCES = frozenset({"cli", "tui", "acp"})

# Hermes' agent-to-agent mailbox. 2026-09-23 owner ruling: a direct channel
# between agents, never owner-authenticated -- content may still be retained
# and recalled, but it must never drive foreground control, owner actions, or
# owner-attributed facts. Checked before the ``author_class`` bot test: a
# mailbox message's sender is unconditionally a peer, whatever it claims.
MAILBOX_SOURCE = "mailbox"

# Self-declared callers (the id is whatever the API client claims -- see
# roadmap evidence appendix, ``gateway/platforms/api_server.py:629-639``).
# 2026-09-23 roadmap P3: never owner, regardless of any configured
# ``owner_identities`` entry under this key -- there is no trust enumeration
# for this source yet.
API_SELF_DECLARED_SOURCES = frozenset({"api", "api_server"})

# Hermes state.db ``sessions.source`` values of machine sessions (verified on
# hermes-media 2026-09-23). Their state.db ids are date-hash ids without the
# ``cron_`` prefix the provider sees at runtime, so readers of state.db map
# these sources to ``non_primary_context`` -- one definition, shared by every
# state.db reader.
MACHINE_SESSION_SOURCES = frozenset({"cron", "subagent"})


@dataclass(frozen=True)
class PrincipalDecision:
    principal: str
    reason: str
    binding_source: str = ""


def _normalize_source(value: object) -> str:
    return str(value or "").strip().lower()


def _principal_section(config: dict[str, Any] | None) -> dict[str, Any]:
    section = config.get("principal") if isinstance(config, dict) else None
    return section if isinstance(section, dict) else {}


def _owner_identities_for(config: dict[str, Any] | None, source: str) -> list[str]:
    identities = _principal_section(config).get("owner_identities")
    identities = identities if isinstance(identities, dict) else {}
    ids = identities.get(source)
    return [str(item) for item in ids if str(item or "").strip()] if isinstance(ids, list) else []


def _binding_source_for(config: dict[str, Any] | None, source: str) -> str:
    sources = _principal_section(config).get("binding_sources")
    sources = sources if isinstance(sources, dict) else {}
    return str(sources.get(source, "") or "")


def resolve_principal(
    *,
    source: str,
    author_id: object = None,
    author_class: str = "",
    config: dict[str, Any] | None = None,
    session_id: str = "",
    non_primary_context: bool = False,
) -> PrincipalDecision:
    """Return the single principal decision for one turn/event.

    This is the only place that decides "who is this turn from" -- every call
    site that used to gate eligibility on ``ingress.author_class`` alone must
    call this instead (provider ``_note_foreground_control_turn`` /
    ``_refresh_current_task_anchor_from_query`` / ``sync_turn`` /
    ``_process_owner_review_reply_ingress``, and the router/prefetch
    plumbing that agrees with the provider).

    ``source`` is the same value the provider calls ``self.platform`` and
    ``EventEnvelope`` calls ``source`` (Hermes sets it via
    ``initialize(platform=...)``; ``"mailbox"`` is an existing literal value
    of it -- see ``event_stats._dict_source_class`` / ``prefetch.py`` /
    ``inner_drive.py``'s identical ``platform == "mailbox" or source ==
    "mailbox"`` checks). ``config`` is the full Memory-OS provider config
    (``self._config``); only its ``principal`` section is read.

    Precedence (first match wins):

    1. machine/system context (a scheduled ``cron_`` session id, or a
       non-primary Hermes agent context such as subagent/cron/flush) ->
       ``system``. Reuses ``ingress.is_scheduled_session_id`` rather than
       duplicating the session-id contract.
    2. a local source (cli/tui/acp) -> ``owner``.
    3. the mailbox source -> ``peer_agent``.
    4. a bot author (``ingress.author_class_from_host``) -> ``peer_agent``.
    5. a self-declared API source (api/api_server) -> ``other_human`` (never
       owner, regardless of any configured identity for that key).
    6. the host sent no author signal at all (``author_class ==
       "unknown"``) -> ``unknown``. This is pre-2026-09 compatibility: there
       is no per-turn identity to check against a configured list, so a
       modern host with a configured platform that stops sending an author
       degrades to compatibility rather than fail-closed.
    7. the source has a configured ``principal.owner_identities`` list ->
       ``owner`` if ``author_id`` is in it, else ``other_human``.
    8. no configured identities for this source -> ``unknown``
       (compatibility mode: today's behaviour, but visible --
       ``principal_binding_status`` reports which platforms are in this
       state so a monitor can grade it).
    """
    normalized_source = _normalize_source(source)
    if is_scheduled_session_id(session_id) or non_primary_context:
        return PrincipalDecision(PRINCIPAL_SYSTEM, "machine_session", "machine_context")
    if normalized_source in LOCAL_OWNER_SOURCES:
        return PrincipalDecision(PRINCIPAL_OWNER, "local_source", "local_source_default")
    if normalized_source == MAILBOX_SOURCE:
        return PrincipalDecision(PRINCIPAL_PEER_AGENT, "mailbox_source", "mailbox_peer_channel")
    if author_class == AUTHOR_CLASS_BOT:
        return PrincipalDecision(PRINCIPAL_PEER_AGENT, "bot_author", "")
    if normalized_source in API_SELF_DECLARED_SOURCES:
        return PrincipalDecision(PRINCIPAL_OTHER_HUMAN, "api_self_declared_author", "api_never_owner")
    if author_class == AUTHOR_CLASS_UNKNOWN:
        return PrincipalDecision(
            PRINCIPAL_UNKNOWN, "author_unknown_no_signal", _binding_source_for(config, normalized_source)
        )
    owner_ids = _owner_identities_for(config, normalized_source)
    if owner_ids:
        binding_source = _binding_source_for(config, normalized_source)
        author_id_str = str(author_id or "").strip()
        if author_id_str and author_id_str in owner_ids:
            return PrincipalDecision(PRINCIPAL_OWNER, "configured_owner_identity", binding_source)
        return PrincipalDecision(PRINCIPAL_OTHER_HUMAN, "configured_non_owner_identity", binding_source)
    return PrincipalDecision(PRINCIPAL_UNKNOWN, "platform_unconfigured_compat", "")


def principal_binding_status(
    config: dict[str, Any] | None, *, platforms: "list[str] | None" = None
) -> dict[str, dict[str, Any]]:
    """Per-platform owner-binding state, read by the monitor's principal census
    (``scripts/memory_os_3_200_monitor.py::principal_binding_summary``).

    Returns ``{platform: {"bound": bool, "binding_source": str,
    "identity_count": int}}`` for every platform mentioned in
    ``principal.owner_identities`` or ``principal.binding_sources``, plus any
    platform explicitly requested via ``platforms`` (reported unbound if
    absent from config), so the monitor can flag "platform X carried traffic
    but ``bound`` is False" without re-deriving this table.
    """
    section = _principal_section(config)
    owner_identities = section.get("owner_identities")
    owner_identities = owner_identities if isinstance(owner_identities, dict) else {}
    binding_sources = section.get("binding_sources")
    binding_sources = binding_sources if isinstance(binding_sources, dict) else {}
    all_platforms = set(owner_identities) | set(binding_sources) | {
        _normalize_source(p) for p in (platforms or ())
    }
    status: dict[str, dict[str, Any]] = {}
    for platform in sorted(all_platforms):
        ids = owner_identities.get(platform)
        ids = [str(item) for item in ids if str(item or "").strip()] if isinstance(ids, list) else []
        status[platform] = {
            "bound": bool(ids),
            "binding_source": str(binding_sources.get(platform, "") or ""),
            "identity_count": len(ids),
        }
    return status


def parse_owner_identity_args(values: "list[str] | None") -> dict[str, list[str]]:
    """Parse repeatable ``--owner-identity <platform>:<id>`` CLI values.

    Explicit flags always win over auto-discovery (installer contract).
    Malformed entries (no ``:``, empty platform, or empty id) are dropped
    rather than raising -- an install script argument typo must not crash the
    whole install; ``discover_owner_identity_bindings`` reports what it
    actually bound.
    """
    result: dict[str, list[str]] = {}
    for raw in values or []:
        text = str(raw or "")
        if ":" not in text:
            continue
        platform, _, identity = text.partition(":")
        platform = platform.strip().lower()
        identity = identity.strip()
        if not platform or not identity:
            continue
        bucket = result.setdefault(platform, [])
        if identity not in bucket:
            bucket.append(identity)
    return result


def mask_identity(value: object) -> str:
    """Mask an id for a printed report -- never the raw value (public repo, live hosts)."""
    text = str(value or "")
    if not text:
        return "(empty)"
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}{'*' * (len(text) - 4)}{text[-2:]}"


# ── Auto-discovery (install/deploy time) ────────────────────────────────
# DM-shape validators: a platform enters this table only once Hermes' own
# code has been read and confirmed a lone home-channel value is provably a
# single person's DM target. Telegram: a private (DM) chat's id equals the
# sender's user id and is always a positive integer; group/supergroup/channel
# ids are 0 or negative (confirmed 2026-09-23 against
# ``gateway/config_env.py`` home-channel wiring and
# ``plugins/platforms/telegram/adapter.py`` chat-type normalization on
# hermes-media). A platform absent from this table is never bound on a lone
# home-channel signal -- it is reported ``unverifiable`` instead (owner
# ruling: "DM-shape only where Hermes' own code defines it").
_DM_SHAPE_VALIDATORS = {
    "telegram": lambda value: value.lstrip("-").isdigit() and not value.startswith("-") and value != "0",
}

_ENV_SIGNAL_KEY_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]*)_(HOME_CHANNEL|ALLOWED_USERS|ALLOW_ALL_USERS)$")
_TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


def _read_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return env
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _read_config_yaml_home_channels(hermes_home: Path) -> dict[str, str]:
    """Best-effort ``platforms.<platform>.home_channel`` fallback from ``config.yaml``.

    Some platforms (observed: WeCom) materialize a resolved home channel into
    ``config.yaml`` rather than (only) the raw env var. Optional and silent on
    any parse failure: this is a secondary signal, and a malformed
    ``config.yaml`` must not abort discovery that ``.env`` alone could
    already answer.
    """
    path = hermes_home / "config.yaml"
    if not path.exists():
        return {}
    try:
        import yaml  # local import: keep this optional for callers that never touch config.yaml
    except ImportError:
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    platforms = loaded.get("platforms") if isinstance(loaded, dict) else None
    if not isinstance(platforms, dict):
        return {}
    result: dict[str, str] = {}
    for platform, cfg in platforms.items():
        if not isinstance(cfg, dict):
            continue
        home = cfg.get("home_channel")
        if isinstance(home, dict):
            value = str(home.get("chat_id") or home.get("user_id") or "").strip()
            if value:
                result[str(platform).strip().lower()] = value
    return result


def _candidate_platforms_from_env(env: dict[str, str]) -> set[str]:
    platforms: set[str] = set()
    for key in env:
        match = _ENV_SIGNAL_KEY_PATTERN.match(key)
        if match:
            platforms.add(match.group(1).lower())
    return platforms


def _platform_signals(
    platform: str,
    *,
    env: dict[str, str],
    config_yaml_home: dict[str, str],
    memory_os_config: dict[str, Any] | None,
) -> tuple[list[tuple[str, str]], bool]:
    prefix = platform.upper()
    home = env.get(f"{prefix}_HOME_CHANNEL", "").strip() or config_yaml_home.get(platform, "")
    allowed_raw = env.get(f"{prefix}_ALLOWED_USERS", "")
    allowed_ids = [item.strip() for item in allowed_raw.split(",") if item.strip()]
    allow_all_raw = env.get(f"{prefix}_ALLOW_ALL_USERS", "")
    allow_all = allow_all_raw.strip().lower() in _TRUTHY_ENV_VALUES
    signals: list[tuple[str, str]] = []
    if len(allowed_ids) == 1:
        signals.append(("allowed_users_single_entry", allowed_ids[0]))
    if home:
        signals.append(("home_channel", home))
    owner_review_cfg = (memory_os_config or {}).get("owner_review") if isinstance(memory_os_config, dict) else None
    if isinstance(owner_review_cfg, dict):
        channel = str(owner_review_cfg.get("channel") or "").strip().lower()
        target_ref = str(owner_review_cfg.get("target_ref") or "").strip()
        if channel == platform and target_ref:
            signals.append(("memory_os_owner_review_target", target_ref))
    return signals, allow_all


def _resolve_platform_binding(
    platform: str, signals: list[tuple[str, str]], allow_all: bool
) -> dict[str, Any]:
    """Decide one platform's auto-binding from its collected signals.

    Ruling (2026-09-23): "同一平台 >=2 个信号一致，或 1 个运维者写的主通道信号且无
    冲突 -> 自动绑定；信号互相矛盾 -> 不绑定". A lone signal binds only when it is
    the operator-written home channel *and* the platform has a verified
    DM-shape test (``_DM_SHAPE_VALIDATORS``); a lone single-entry allowlist
    without a home channel, or a home channel on a platform with no verified
    DM shape, is reported ``unverifiable`` rather than bound -- the
    conservative failure mode for an owner-trust boundary.
    """
    if allow_all:
        return {"status": "allow_all_open", "owner_identities": [], "binding_source": ""}
    if not signals:
        return {"status": "unconfigured", "owner_identities": [], "binding_source": ""}
    distinct_values = {value for _source, value in signals}
    sources = sorted({source for source, _ in signals})
    if len(distinct_values) > 1:
        return {"status": "conflict", "owner_identities": [], "binding_source": "", "signal_sources": sources}
    value = next(iter(distinct_values))
    if len(signals) >= 2:
        return {
            "status": "bound",
            "owner_identities": [value],
            "binding_source": "+".join(sources),
            "signal_sources": sources,
        }
    source = sources[0]
    if source == "home_channel":
        validator = _DM_SHAPE_VALIDATORS.get(platform)
        if validator is not None and validator(value):
            return {
                "status": "bound",
                "owner_identities": [value],
                "binding_source": "home_channel_dm_shape",
                "signal_sources": sources,
            }
    return {"status": "unverifiable", "owner_identities": [], "binding_source": "", "signal_sources": sources}


def discover_owner_identity_bindings(
    hermes_home: "str | Path",
    *,
    explicit: dict[str, list[str]] | None = None,
    memory_os_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only discovery of per-platform owner identity bindings.

    Reads only signals the operator already wrote into the target Hermes
    host's own config (``<hermes_home>/.env``, and a ``config.yaml``
    ``platforms.<platform>.home_channel`` fallback when present) -- never a
    claim-code or pairing flow (2026-09-23 owner ruling). ``explicit`` always
    wins over auto-discovery for a given platform.

    Returns ``{"bindings": {platform: {"owner_identities": [...],
    "binding_source": str}}, "report": [...]}``. ``bindings`` is meant to be
    written into ``config.json`` (``principal.owner_identities`` /
    ``principal.binding_sources``) and carries real ids -- it must never be
    printed. ``report`` entries carry only masked ids
    (``masked_identities``), a status from the closed set ``explicit`` /
    ``explicit_retained`` / ``bound`` / ``conflict`` / ``unverifiable`` /
    ``unconfigured`` / ``allow_all_open``, and the signal sources that produced the status --
    safe to print or log.
    """
    home_dir = Path(hermes_home).expanduser().resolve()
    env = _read_env_file(home_dir / ".env")
    config_yaml_home = _read_config_yaml_home_channels(home_dir)
    candidate_platforms = _candidate_platforms_from_env(env) | set(config_yaml_home)

    bindings: dict[str, dict[str, Any]] = {}
    report: list[dict[str, Any]] = []

    for platform, ids in (explicit or {}).items():
        key = _normalize_source(platform)
        normalized_ids = [str(item).strip() for item in ids if str(item or "").strip()]
        if not key or not normalized_ids:
            continue
        bindings[key] = {"owner_identities": normalized_ids, "binding_source": "explicit_owner_identity"}
        report.append(
            {
                "platform": key,
                "status": "explicit",
                "binding_source": "explicit_owner_identity",
                "identity_count": len(normalized_ids),
                "masked_identities": [mask_identity(v) for v in normalized_ids],
                "signal_sources": ["explicit_owner_identity"],
            }
        )

    # An explicit binding from an earlier install survives a later install
    # that does not repeat it. The installer rewrites this section on every
    # run, and every deploy runs the installer, so without this an operator's
    # one-time ``--owner-identity`` would silently fall back to discovery (or
    # to compatibility mode) on the next routine deploy.
    previous = (memory_os_config or {}).get("principal")
    previous = previous if isinstance(previous, dict) else {}
    previous_ids = previous.get("owner_identities") if isinstance(previous.get("owner_identities"), dict) else {}
    previous_sources = previous.get("binding_sources") if isinstance(previous.get("binding_sources"), dict) else {}
    for platform, source in previous_sources.items():
        key = _normalize_source(platform)
        ids = previous_ids.get(platform, previous_ids.get(key))
        if source != "explicit_owner_identity" or not key or key in bindings or not isinstance(ids, list):
            continue
        normalized_ids = [str(item).strip() for item in ids if str(item or "").strip()]
        if not normalized_ids:
            continue
        bindings[key] = {"owner_identities": normalized_ids, "binding_source": "explicit_owner_identity"}
        report.append(
            {
                "platform": key,
                "status": "explicit_retained",
                "binding_source": "explicit_owner_identity",
                "identity_count": len(normalized_ids),
                "masked_identities": [mask_identity(v) for v in normalized_ids],
                "signal_sources": ["previous_install_explicit_owner_identity"],
            }
        )

    for platform in sorted(candidate_platforms):
        if platform in bindings:
            continue  # explicit always wins
        signals, allow_all = _platform_signals(
            platform, env=env, config_yaml_home=config_yaml_home, memory_os_config=memory_os_config
        )
        decision = _resolve_platform_binding(platform, signals, allow_all)
        bindings[platform] = {
            "owner_identities": decision["owner_identities"],
            "binding_source": decision["binding_source"],
        }
        report.append(
            {
                "platform": platform,
                "status": decision["status"],
                "binding_source": decision["binding_source"],
                "identity_count": len(decision["owner_identities"]),
                "masked_identities": [mask_identity(v) for v in decision["owner_identities"]],
                "signal_sources": decision.get("signal_sources", []),
            }
        )

    return {"bindings": bindings, "report": report}
