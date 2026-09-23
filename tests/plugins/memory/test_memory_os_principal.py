"""Principal resolution (P0-lite, 2026-09-23): the single authority for
"who is this turn from", and the read-only host-config discovery that binds
an owner identity per platform without a claim-code / pairing flow.

PR #82 (cf80d9c/f334773) introduced ``ingress.author_class``
(human/bot/unknown) to stop another agent's turn from steering the owner's
foreground task, but "human" only means "the host admitted a non-bot
author" -- never a verified owner identity. Every counterfactual below
targets one row of the ``resolve_principal`` decision table or one
auto-discovery rule; ids used are placeholders (never real account ids --
this repo is public).
"""
from __future__ import annotations

import json

import pytest

from plugins.memory.memory_os import ingress
from plugins.memory.memory_os.config import load_config, save_config
from plugins.memory.memory_os.principal import (
    API_SELF_DECLARED_SOURCES,
    FOREGROUND_CONTROL_PRINCIPALS,
    LOCAL_OWNER_SOURCES,
    MAILBOX_SOURCE,
    OWNER_ACTION_PRINCIPALS,
    PRINCIPAL_OTHER_HUMAN,
    PRINCIPAL_OWNER,
    PRINCIPAL_PEER_AGENT,
    PRINCIPAL_SYSTEM,
    PRINCIPAL_UNKNOWN,
    discover_owner_identity_bindings,
    mask_identity,
    parse_owner_identity_args,
    principal_binding_status,
    resolve_principal,
)

_OWNER_ID = "1000000001"
_OTHER_HUMAN_ID = "2000000002"
_PEER_BOT_ID = "3000000003"


def _config(owner_identities=None, binding_sources=None):
    return {
        "principal": {
            "owner_identities": owner_identities or {},
            "binding_sources": binding_sources or {},
        }
    }


# ── resolve_principal: decision table ───────────────────────────────────


@pytest.mark.parametrize("source", sorted(LOCAL_OWNER_SOURCES))
def test_local_sources_resolve_to_owner(source):
    """Counterfactual: without the local-source rule a `cli`/`tui`/`acp`
    session with no configured owner_identities falls through to
    ``platform_unconfigured_compat`` (unknown) instead of owner -- the ruling
    is that local shell access already implies higher trust than the
    conversational gate, not merely compatibility."""
    decision = resolve_principal(source=source, author_id=_OWNER_ID, author_class="human", config={})
    assert decision.principal == PRINCIPAL_OWNER
    assert decision.reason == "local_source"


def test_local_source_overrides_a_bot_author_flag():
    """Documents the deliberate precedence: source-based rules (local,
    mailbox) are checked before author_class. Without this, a host that
    (incorrectly) flags a CLI turn as a bot would demote it to peer_agent."""
    decision = resolve_principal(source="cli", author_id=_OWNER_ID, author_class="bot", config={})
    assert decision.principal == PRINCIPAL_OWNER


def test_mailbox_source_resolves_to_peer_agent_never_owner():
    """Counterfactual: without the mailbox rule, a mailbox message from a
    non-bot author on an unconfigured platform would resolve to
    ``unknown`` (compat-allowed) instead of ``peer_agent`` -- letting an
    agent-to-agent channel drive foreground control / owner actions."""
    decision = resolve_principal(source="mailbox", author_id=_OWNER_ID, author_class="human", config={})
    assert decision.principal == PRINCIPAL_PEER_AGENT
    assert decision.reason == "mailbox_source"


def test_mailbox_source_ignores_configured_owner_identity():
    """Owner ruling: mailbox is never owner-authenticated, even if the
    sender's id happens to be listed as the platform's owner identity."""
    config = _config(owner_identities={MAILBOX_SOURCE: [_OWNER_ID]})
    decision = resolve_principal(source="mailbox", author_id=_OWNER_ID, author_class="human", config=config)
    assert decision.principal == PRINCIPAL_PEER_AGENT


def test_bot_author_resolves_to_peer_agent():
    """Counterfactual: without this rule, a bot author on a platform with no
    owner_identities configured would fall through to `unknown` (compat)."""
    decision = resolve_principal(source="telegram", author_id=_PEER_BOT_ID, author_class="bot", config={})
    assert decision.principal == PRINCIPAL_PEER_AGENT
    assert decision.reason == "bot_author"


@pytest.mark.parametrize("source", sorted(API_SELF_DECLARED_SOURCES))
def test_api_platforms_never_resolve_to_owner_even_when_configured(source):
    """P3: the id is self-declared by the caller. Counterfactual: without
    this rule, configuring `owner_identities` for "api"/"api_server" (an
    operator mistake, since these keys should never be configured) would let
    any caller claim ownership merely by sending that id."""
    config = _config(owner_identities={source: [_OWNER_ID]})
    decision = resolve_principal(source=source, author_id=_OWNER_ID, author_class="human", config=config)
    assert decision.principal == PRINCIPAL_OTHER_HUMAN
    assert decision.reason == "api_self_declared_author"


def test_configured_owner_identity_matches_owner():
    config = _config(owner_identities={"telegram": [_OWNER_ID]})
    decision = resolve_principal(source="telegram", author_id=_OWNER_ID, author_class="human", config=config)
    assert decision.principal == PRINCIPAL_OWNER
    assert decision.reason == "configured_owner_identity"


def test_configured_platform_non_owner_human_is_other_human():
    """Counterfactual: without checking membership, any human author on a
    configured platform would resolve to owner -- the whole point of
    configuring owner_identities is to distinguish the owner from other
    humans admitted by the host."""
    config = _config(owner_identities={"telegram": [_OWNER_ID]})
    decision = resolve_principal(source="telegram", author_id=_OTHER_HUMAN_ID, author_class="human", config=config)
    assert decision.principal == PRINCIPAL_OTHER_HUMAN
    assert decision.reason == "configured_non_owner_identity"


def test_unconfigured_platform_is_unknown_compat():
    """Compatibility mode: today's pre-P0-lite behaviour (human/unknown may
    steer foreground control) must survive for a platform nobody bound."""
    decision = resolve_principal(source="wecom", author_id=_OWNER_ID, author_class="human", config={})
    assert decision.principal == PRINCIPAL_UNKNOWN
    assert decision.reason == "platform_unconfigured_compat"


def test_author_unknown_no_signal_is_unknown_even_on_configured_platform():
    """Counterfactual: without this rule, a host that stops sending author
    info on an otherwise-configured platform would fall through to the
    owner_identities membership check with an empty id and always resolve to
    other_human (fail-closed) instead of the documented compat fallback."""
    config = _config(owner_identities={"telegram": [_OWNER_ID]})
    decision = resolve_principal(source="telegram", author_id=None, author_class="unknown", config=config)
    assert decision.principal == PRINCIPAL_UNKNOWN
    assert decision.reason == "author_unknown_no_signal"


def test_scheduled_session_id_is_system():
    """Counterfactual: without reusing ingress.is_scheduled_session_id, a
    cron session's owner-DM platform would resolve the cron prompt as
    ``owner`` and let it recover/tombstone the owner's foreground anchor."""
    decision = resolve_principal(
        source="telegram", author_id=_OWNER_ID, author_class="human", config={}, session_id="cron_job1_20260101"
    )
    assert decision.principal == PRINCIPAL_SYSTEM
    assert decision.reason == "machine_session"


def test_non_primary_context_is_system():
    """Counterfactual: without this flag, a Hermes subagent/cron/flush
    context (agent_context != primary) with a human author would resolve to
    owner and be allowed to write the owner's foreground state."""
    decision = resolve_principal(
        source="telegram", author_id=_OWNER_ID, author_class="human", config={}, non_primary_context=True
    )
    assert decision.principal == PRINCIPAL_SYSTEM


def test_explicit_flag_binding_source_is_visible_via_config():
    """Explicit --owner-identity bindings are just a config entry with
    binding_source="explicit_owner_identity" -- resolve_principal surfaces
    whatever binding_source the config records."""
    config = _config(
        owner_identities={"telegram": [_OWNER_ID]},
        binding_sources={"telegram": "explicit_owner_identity"},
    )
    decision = resolve_principal(source="telegram", author_id=_OWNER_ID, author_class="human", config=config)
    assert decision.principal == PRINCIPAL_OWNER
    assert decision.binding_source == "explicit_owner_identity"


def test_source_is_normalized_case_and_whitespace():
    config = _config(owner_identities={"telegram": [_OWNER_ID]})
    decision = resolve_principal(source=" Telegram ", author_id=_OWNER_ID, author_class="human", config=config)
    assert decision.principal == PRINCIPAL_OWNER


def test_resolve_principal_never_returns_outside_closed_set():
    cases = [
        dict(source="cli", author_class="human"),
        dict(source="mailbox", author_class="human"),
        dict(source="telegram", author_class="bot"),
        dict(source="api", author_class="human"),
        dict(source="telegram", author_class="unknown"),
        dict(source="telegram", author_class="human"),
        dict(source="telegram", author_class="human", session_id="cron_x_1"),
    ]
    for kwargs in cases:
        decision = resolve_principal(config={}, author_id=None, **kwargs)
        assert decision.principal in {
            PRINCIPAL_OWNER,
            PRINCIPAL_PEER_AGENT,
            PRINCIPAL_OTHER_HUMAN,
            PRINCIPAL_SYSTEM,
            PRINCIPAL_UNKNOWN,
        }


# ── Vocabulary drift guard (CLAUDE.md: "a gate whose vocabulary drifts from
# its producer's checks nothing, silently") ─────────────────────────────


def test_ingress_foreground_control_principals_match_principal_module():
    """ingress.py keeps its own copy of the two allowed principal literals
    (cannot import principal.py -- that would cycle, since principal.py
    imports from ingress.py). Counterfactual: if principal.py's set changed
    (e.g. adding a new principal value) without updating ingress.py's copy,
    classify_ingress would silently gate on stale vocabulary."""
    assert ingress._FOREGROUND_CONTROL_PRINCIPALS == FOREGROUND_CONTROL_PRINCIPALS
    assert FOREGROUND_CONTROL_PRINCIPALS == {PRINCIPAL_OWNER, PRINCIPAL_UNKNOWN}


def test_owner_action_principals_is_exactly_owner_and_unknown():
    """P1 (2026-09-23 next-phase plan, Phase 2): owner_actions.py self-checks
    against this constant for both parse_owner_review_reply and
    owner_review_surface_report. Pin its exact membership so a future edit
    cannot silently widen (or narrow) who may perform/see an owner action."""
    assert OWNER_ACTION_PRINCIPALS == {PRINCIPAL_OWNER, PRINCIPAL_UNKNOWN}
    assert PRINCIPAL_PEER_AGENT not in OWNER_ACTION_PRINCIPALS
    assert PRINCIPAL_OTHER_HUMAN not in OWNER_ACTION_PRINCIPALS
    assert PRINCIPAL_SYSTEM not in OWNER_ACTION_PRINCIPALS
    assert "" not in OWNER_ACTION_PRINCIPALS


# ── principal_binding_status ─────────────────────────────────────────────


def test_principal_binding_status_reports_bound_and_unbound():
    config = _config(
        owner_identities={"telegram": [_OWNER_ID]},
        binding_sources={"telegram": "home_channel_dm_shape", "wecom": "conflict"},
    )
    status = principal_binding_status(config)
    assert status["telegram"] == {"bound": True, "binding_source": "home_channel_dm_shape", "identity_count": 1}
    assert status["wecom"] == {"bound": False, "binding_source": "conflict", "identity_count": 0}


def test_principal_binding_status_includes_requested_platforms_even_if_absent():
    """Counterfactual: without unioning in the `platforms` argument, a
    platform with zero config traces (never examined) would be
    indistinguishable from one this function was never asked about."""
    status = principal_binding_status({}, platforms=["telegram"])
    assert status["telegram"] == {"bound": False, "binding_source": "", "identity_count": 0}


def test_principal_binding_status_empty_config_is_empty():
    assert principal_binding_status(None) == {}
    assert principal_binding_status({}) == {}


# ── mask_identity ─────────────────────────────────────────────────────────


def test_mask_identity_never_leaks_full_value():
    masked = mask_identity(_OWNER_ID)
    assert masked != _OWNER_ID
    assert masked.startswith(_OWNER_ID[:2])
    assert masked.endswith(_OWNER_ID[-2:])
    assert "*" in masked


def test_mask_identity_short_value_fully_masked():
    assert mask_identity("ab") == "**"
    assert mask_identity("") == "(empty)"


# ── parse_owner_identity_args ────────────────────────────────────────────


def test_parse_owner_identity_args_basic():
    parsed = parse_owner_identity_args(["telegram:1000000001", "cli:root"])
    assert parsed == {"telegram": ["1000000001"], "cli": ["root"]}


def test_parse_owner_identity_args_accumulates_repeats_for_same_platform():
    parsed = parse_owner_identity_args(["telegram:1000000001", "telegram:2000000002"])
    assert parsed == {"telegram": ["1000000001", "2000000002"]}


def test_parse_owner_identity_args_dedupes_exact_repeat():
    parsed = parse_owner_identity_args(["telegram:1000000001", "telegram:1000000001"])
    assert parsed == {"telegram": ["1000000001"]}


@pytest.mark.parametrize("bad", ["no-colon-here", "telegram:", ":1000000001", ""])
def test_parse_owner_identity_args_drops_malformed_entries(bad):
    """Counterfactual: without dropping malformed entries, a CLI typo
    (missing colon, empty platform, or empty id) would either raise (crashing
    the whole install) or silently bind an empty-string platform/id."""
    assert parse_owner_identity_args([bad]) == {}


def test_parse_owner_identity_args_none_is_empty():
    assert parse_owner_identity_args(None) == {}


# ── config.py normalization (principal.owner_identities / binding_sources) ─


def test_config_load_default_principal_section(tmp_path):
    config = load_config(tmp_path)
    assert config["principal"] == {"owner_identities": {}, "binding_sources": {}}


def test_config_save_and_reload_principal_roundtrip(tmp_path):
    save_config(
        {
            "principal": {
                "owner_identities": {"Telegram": [_OWNER_ID, _OWNER_ID], "cli": ["root"]},
                "binding_sources": {"Telegram": "home_channel_dm_shape"},
            }
        },
        tmp_path,
    )
    config = load_config(tmp_path)
    # platform keys normalized to lowercase; ids deduped, order preserved
    assert config["principal"]["owner_identities"] == {"telegram": [_OWNER_ID], "cli": ["root"]}
    assert config["principal"]["binding_sources"] == {"telegram": "home_channel_dm_shape"}


def test_config_normalization_drops_non_list_owner_identities():
    """Counterfactual: without the isinstance(ids, list) guard, a
    hand-edited config.json with a string value would either crash
    resolve_principal's membership check or silently coerce to something
    unintended (e.g. `in "some string"` substring semantics)."""
    from plugins.memory.memory_os.config import _merge_principal_config

    merged = _merge_principal_config({"owner_identities": {"telegram": "not-a-list"}})
    assert merged["owner_identities"] == {}


def test_config_normalization_drops_empty_and_blank_ids():
    from plugins.memory.memory_os.config import _merge_principal_config

    merged = _merge_principal_config({"owner_identities": {"telegram": ["", "  ", _OWNER_ID]}})
    assert merged["owner_identities"] == {"telegram": [_OWNER_ID]}


def test_config_normalization_drops_platform_with_no_surviving_ids():
    from plugins.memory.memory_os.config import _merge_principal_config

    merged = _merge_principal_config({"owner_identities": {"telegram": []}})
    assert merged["owner_identities"] == {}


def test_config_normalization_ignores_non_dict_input():
    from plugins.memory.memory_os.config import _merge_principal_config

    assert _merge_principal_config("not-a-dict") == {"owner_identities": {}, "binding_sources": {}}
    assert _merge_principal_config(None) == {"owner_identities": {}, "binding_sources": {}}


def test_config_normalization_unknown_top_level_keys_ignored():
    """Bounded/typed: only owner_identities and binding_sources survive."""
    from plugins.memory.memory_os.config import _merge_principal_config

    merged = _merge_principal_config({"owner_identities": {}, "binding_sources": {}, "unexpected_key": "value"})
    assert set(merged.keys()) == {"owner_identities", "binding_sources"}


# ── discover_owner_identity_bindings: real .env producer, no shortcuts ───


def _write_env(hermes_home, lines):
    (hermes_home / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_discover_binds_via_two_agreeing_signals(tmp_path):
    """main/telegram production shape: home channel == the single allowlist
    entry. Counterfactual: without treating >=2 agreeing signals as
    sufficient, this would fall through to the single-signal DM-shape path
    (which happens to also pass for Telegram, but must not be the only way
    two independently-configured operator signals agreeing gets honoured)."""
    _write_env(tmp_path, [f"TELEGRAM_HOME_CHANNEL={_OWNER_ID}", f"TELEGRAM_ALLOWED_USERS={_OWNER_ID}"])
    result = discover_owner_identity_bindings(tmp_path)
    entry = result["bindings"]["telegram"]
    assert entry["owner_identities"] == [_OWNER_ID]
    assert entry["binding_source"] == "allowed_users_single_entry+home_channel"
    report = next(r for r in result["report"] if r["platform"] == "telegram")
    assert report["status"] == "bound"
    assert _OWNER_ID not in report["masked_identities"][0]


def test_discover_binds_via_home_channel_dm_shape_alone(tmp_path):
    """sannai/telegram production shape: home channel only, no allowlist.
    Counterfactual: without the DM-shape validator, a lone home-channel
    signal on Telegram would be reported unverifiable and never bind."""
    _write_env(tmp_path, [f"TELEGRAM_HOME_CHANNEL={_OWNER_ID}"])
    result = discover_owner_identity_bindings(tmp_path)
    entry = result["bindings"]["telegram"]
    assert entry["owner_identities"] == [_OWNER_ID]
    assert entry["binding_source"] == "home_channel_dm_shape"


def test_discover_lone_home_channel_on_unverified_platform_is_unverifiable(tmp_path):
    """Counterfactual: without gating on the DM-shape validator table, a lone
    WeCom-style (email-shaped, non-numeric) home channel would bind on no
    stronger evidence than "an operator wrote something here"."""
    _write_env(tmp_path, ["WECOM_HOME_CHANNEL=admin@example.com"])
    result = discover_owner_identity_bindings(tmp_path)
    entry = result["bindings"].get("wecom", {"owner_identities": []})
    assert entry["owner_identities"] == []
    report = next(r for r in result["report"] if r["platform"] == "wecom")
    assert report["status"] == "unverifiable"


def test_discover_lone_single_entry_allowlist_without_home_channel_is_unverifiable(tmp_path):
    """Conservative interpretation of the ruling ("1 个运维者写的主通道信号"
    names the home channel specifically): a lone allowlist entry with no home
    channel does not bind on its own."""
    _write_env(tmp_path, [f"TELEGRAM_ALLOWED_USERS={_OWNER_ID}"])
    result = discover_owner_identity_bindings(tmp_path)
    entry = result["bindings"]["telegram"]
    assert entry["owner_identities"] == []
    report = next(r for r in result["report"] if r["platform"] == "telegram")
    assert report["status"] == "unverifiable"


def test_discover_conflicting_signals_do_not_bind(tmp_path):
    """Counterfactual: without the distinct-value check, disagreeing signals
    (an operator changed the home channel but left a stale allowlist entry)
    would silently bind on whichever signal happened to be read last."""
    _write_env(tmp_path, [f"TELEGRAM_HOME_CHANNEL={_OWNER_ID}", f"TELEGRAM_ALLOWED_USERS={_OTHER_HUMAN_ID}"])
    result = discover_owner_identity_bindings(tmp_path)
    entry = result["bindings"]["telegram"]
    assert entry["owner_identities"] == []
    report = next(r for r in result["report"] if r["platform"] == "telegram")
    assert report["status"] == "conflict"


def test_discover_no_signals_is_unconfigured(tmp_path):
    _write_env(tmp_path, ["UNRELATED_KEY=value"])
    result = discover_owner_identity_bindings(tmp_path)
    assert result["bindings"] == {}
    assert result["report"] == []


def test_discover_allow_all_users_blocks_binding_even_with_home_channel(tmp_path):
    """Counterfactual: without checking ALLOW_ALL_USERS, a platform that
    admits everyone would still bind on its home channel alone, silently
    treating "anyone allowed" as "the owner is known"."""
    _write_env(
        tmp_path,
        [f"TELEGRAM_HOME_CHANNEL={_OWNER_ID}", "TELEGRAM_ALLOW_ALL_USERS=true"],
    )
    result = discover_owner_identity_bindings(tmp_path)
    entry = result["bindings"]["telegram"]
    assert entry["owner_identities"] == []
    report = next(r for r in result["report"] if r["platform"] == "telegram")
    assert report["status"] == "allow_all_open"


def test_discover_explicit_flag_wins_over_conflicting_auto_signals(tmp_path):
    """Counterfactual: without checking `explicit` first and skipping
    auto-discovery for that platform, an explicit --owner-identity would be
    silently overwritten by (or merged confusingly with) a conflicting
    auto-discovered signal on the same platform."""
    _write_env(tmp_path, [f"TELEGRAM_HOME_CHANNEL={_OTHER_HUMAN_ID}", f"TELEGRAM_ALLOWED_USERS={_OTHER_HUMAN_ID}"])
    result = discover_owner_identity_bindings(tmp_path, explicit={"telegram": [_OWNER_ID]})
    entry = result["bindings"]["telegram"]
    assert entry["owner_identities"] == [_OWNER_ID]
    assert entry["binding_source"] == "explicit_owner_identity"
    report = next(r for r in result["report"] if r["platform"] == "telegram")
    assert report["status"] == "explicit"


def test_discover_memory_os_owner_review_target_is_a_signal(tmp_path):
    """A configured Memory-OS owner-review delivery target on the same
    platform, agreeing with the home channel, is a second signal (>=2
    agreeing signals binds even without a verified DM shape)."""
    _write_env(tmp_path, [f"WECOM_HOME_CHANNEL={_OWNER_ID}"])
    memory_os_config = {"owner_review": {"channel": "wecom", "target_ref": _OWNER_ID}}
    result = discover_owner_identity_bindings(tmp_path, memory_os_config=memory_os_config)
    entry = result["bindings"]["wecom"]
    assert entry["owner_identities"] == [_OWNER_ID]
    assert "memory_os_owner_review_target" in entry["binding_source"]


def test_discover_config_yaml_home_channel_fallback(tmp_path):
    """Some platforms (observed: WeCom) materialize home_channel into
    config.yaml rather than .env. Counterfactual: without this fallback, a
    platform whose only trace is config.yaml would report unconfigured."""
    (tmp_path / "config.yaml").write_text(
        "platforms:\n  wecom:\n    enabled: true\n    home_channel:\n      chat_id: admin@example.com\n",
        encoding="utf-8",
    )
    result = discover_owner_identity_bindings(tmp_path)
    report = next(r for r in result["report"] if r["platform"] == "wecom")
    # unverifiable (no DM-shape validator for wecom), but NOT unconfigured --
    # the signal was found via config.yaml.
    assert report["status"] == "unverifiable"
    assert "home_channel" in report["signal_sources"]


def test_discover_masks_ids_in_report_never_prints_raw(tmp_path):
    _write_env(tmp_path, [f"TELEGRAM_HOME_CHANNEL={_OWNER_ID}", f"TELEGRAM_ALLOWED_USERS={_OWNER_ID}"])
    result = discover_owner_identity_bindings(tmp_path)
    report_text = json.dumps(result["report"])
    assert _OWNER_ID not in report_text
    # bindings (never printed by callers) legitimately carries the raw id
    assert result["bindings"]["telegram"]["owner_identities"] == [_OWNER_ID]


def test_discover_missing_env_file_is_unconfigured_not_an_error(tmp_path):
    result = discover_owner_identity_bindings(tmp_path)
    assert result == {"bindings": {}, "report": []}
