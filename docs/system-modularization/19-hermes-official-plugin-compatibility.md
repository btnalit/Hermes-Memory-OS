# Hermes Official Plugin Compatibility

This document compares Memory-OS against the official Hermes plugin surfaces
and records the v0.1 compatibility decision for the portable Agent OS modules.

It is a decision record, not an implementation spec. The goal is to fit Hermes'
official plugin model where it helps operator discoverability without weakening
the Memory-OS runtime boundaries that have already been validated on
`10.20.3.200`.

## Live Host Probe

The official docs are necessary but not sufficient for implementation. The
`10.20.3.200` test host currently runs:

```text
Hermes Agent v0.14.0 (2026.5.16)
Project: /usr/local/lib/hermes-agent
Update state: 653 commits behind the upstream docs/source snapshot
```

Read-only probes on that host showed:

- `hermes plugins list` discovers the current `memory_os` directory as a user
  plugin with status `not enabled`
- `memory.provider` is still `memory_os`
- `plugins` config is absent (`plugins: None`)
- `hermes memory_os ...` commands are available
- `hermes memory --help` lists bundled official providers but not the custom
  `memory_os` provider
- `PluginContext` in the installed source supports:
  - `register_hook`
  - `register_cli_command`
  - `register_command`
  - `register_skill`
  - `inject_message`
- installed tests confirm `pre_llm_call` hook returns are collected as context
  and routed into the user message

Interpretation:

- the provider works through the memory-provider path even though the flat
  user plugin directory also appears in `hermes plugins list`
- `plugins.enabled` must not be required for the Memory-OS provider itself
- the future shell plugin must use a separate name (`memory-os-agent-os`) so it
  does not collide with the existing flat `memory_os` provider directory
- implementation must be verified against the installed host source before
  relying on upstream documentation details

## Official Plugin Surfaces

Hermes has several extension surfaces. The important distinction for Memory-OS
is:

| Surface | Official selection model | Memory-OS relevance |
| --- | --- | --- |
| Memory provider | single active provider via `memory.provider` | Memory-OS L1 provider |
| General plugin | multi-select via `plugins.enabled` | Optional shell for Agent OS modules |
| Hooks | registered by a general plugin | lightweight session markers only in v0.1 |
| CLI / slash commands | registered by a general plugin | optional aliases/wrappers only |
| Skills | registered by a general plugin | future explicit read path, not v0.1 |

Official Hermes docs explicitly separate memory providers from general plugins.
Memory providers are selected through `memory.provider`; general plugins are
opt-in through `plugins.enabled`.

## Current Memory-OS Shape

Memory-OS currently has two layers:

```text
L1 Memory Provider
  plugins/memory/memory_os/
  -> installed to $HERMES_HOME/plugins/memory_os/
  -> selected by memory.provider=memory_os
  -> owns prefetch, sync_turn, memory_os_status, heartbeat/index contracts

L2-L4 Agent OS System Modules
  plugins/modules/
  plugins/system/
  -> installed to $HERMES_HOME/memory-os/runtime/python/
  -> state under $HERMES_HOME/system-modules/
  -> operated by Memory-OS lifecycle/runtime commands
```

The provider layer already matches the official provider model in spirit:
exactly one memory backend is active, and Hermes chooses it through
`memory.provider`.

On the current test host, the provider is installed as a flat user plugin
directory:

```text
$HERMES_HOME/plugins/memory_os/
```

That makes it visible to `hermes plugins list`, but it is not enabled through
`plugins.enabled`. This is a live-host compatibility fact, not the desired
control plane for L2-L4 Agent OS modules.

The L2-L4 modules are not official general plugins. They are Memory-OS system
modules with their own manifest, lifecycle, schedule coordination, no-send
delivery boundaries, and profile-local state.

That difference is intentional for v0.1. The module runtime needs stricter
cross-module policy than the generic plugin allow-list provides:

- no send by default
- no execute by default
- no identity write
- no crystallized approval
- no Hindsight export
- profile-local module state
- RH-12 Inner Drive eligibility policy
- DeepReflection injection safety filters and caps

## Gap Matrix

| Area | Current state | Official gap | v0.1 decision |
| --- | --- | --- | --- |
| Memory provider discovery | `memory.provider=memory_os` | none for L1 provider | keep |
| Agent OS module discovery | Memory-OS lifecycle only | not visible in `hermes plugins list` | add thin shell later |
| Official enable/disable | installer + module lifecycle | no `plugins.enabled` gate for shell | add one shell plugin |
| CLI | `hermes memory_os ...` | not registered by a general plugin | keep old commands; shell may add aliases |
| Context injection | `MemoryProvider.prefetch()` | official `pre_llm_call` can also inject | keep provider as sole injection path |
| Session hooks | heartbeat/runtime handles batch work | official hooks can observe sessions | use minimal marker hooks only |
| Skills | none | official `register_skill()` exists | future explicit read path only |

## Decision: Thin Official Shell, Not Module Rewrite

v0.1 should add at most one official general plugin shell:

```text
memory-os-agent-os
```

The shell is a bridge between Hermes' official plugin UX and the existing
Memory-OS runtime. It must not reimplement the runtime or split modules into
individual general plugins.

The shell may:

- make Agent OS presence visible in `hermes plugins list`
- provide status/doctor aliases
- provide safe operator CLI wrappers
- register minimal session marker hooks
- point users to the Memory-OS provider and module runtime state

The shell must not:

- inject DeepReflection carryover through `pre_llm_call`
- duplicate `MemoryProvider.prefetch()` output
- send messages
- execute actions
- write identity
- approve crystallized records
- export to Hindsight
- mutate module state outside existing lifecycle APIs
- bypass RH-12 / DeepReflection safety policies

## Why Not Convert Every Module Into A Plugin

Converting each module into a separate official plugin is premature.

It would create independent plugin-level toggles for cognition, governance,
messaging, and expression, but it would also spread one tested runtime into
many Hermes loading boundaries. That increases the risk of:

- inconsistent module startup order
- duplicated source ingestion
- hook-based working-memory mutations that bypass RH-12
- unclear send/execute ownership
- broken test-host deployment scripts
- more complicated rollback

v0.1 keeps one runtime and one shell.

v0.2 can split the shell only if real users need plugin-level selective enable:

```text
memory-os-core
memory-os-cognition
memory-os-governance
memory-os-expression
```

The trigger for splitting is real operational need, such as "enable governance
but disable DeepReflection at the official plugin layer." It is not a code
organization preference.

## Decision 1: Carryover Injection Path

Official Hermes plugins can use `pre_llm_call` to return a context block before
the LLM loop. Memory-OS deliberately keeps Conversation Carryover in:

```text
MemoryProvider.prefetch()
```

Reason:

- Memory-OS owns memory injection policy
- diagnostic suppression already lives in the provider prefetch path
- RH-21a/RH-21b/RH-21c guards are validated on the prefetch path
- DeepReflection card safety, TTL, budget, and wording filters are validated
  there
- hook injection would make double injection easy

Hard rule:

If a future version moves carryover to `pre_llm_call`, the provider's
DeepReflection carryover must first be disabled. There must be one and only one
automatic carryover injection source.

v0.1 thin shell therefore does not register `pre_llm_call`.

## Decision 2: Plugin Name And CLI Compatibility

Official shell plugin name:

```text
memory-os-agent-os
```

Existing commands remain authoritative:

```bash
hermes memory_os status
hermes memory_os doctor
hermes memory_os heartbeat
hermes memory_os conversation-regression ...
```

The shell may provide aliases such as:

```bash
hermes memory-os-agent-os status
hermes memory-os-agent-os doctor
```

Those aliases must be wrappers over the existing commands. They must not become
the only supported path during v0.x.

Compatibility rule:

- no v0.x script should be forced to migrate from `hermes memory_os ...`
- documentation may introduce shell aliases as optional operator convenience
- validation must still exercise the existing Memory-OS CLI commands

## Decision 3: User-Installed, Not Bundled

v0.1 shell is user-installed:

```text
$HERMES_HOME/plugins/memory-os-agent-os/
```

It is enabled through:

```yaml
plugins:
  enabled:
    - memory-os-agent-os
```

Reason:

- Memory-OS is not an upstream Hermes bundled plugin
- the project needs independent release cadence
- test-host deployment already uses a repository installer
- bundled plugin status would require upstream Hermes integration and review

Future upstream bundling can be considered after the shell stabilizes.

## Decision 4: Two-Step Installation

Full Memory-OS Agent OS deployment has two independent switches:

```text
Step 1: Memory provider
  install memory_os provider
  set memory.provider=memory_os

Step 2: Agent OS shell
  install memory-os-agent-os general plugin
  add memory-os-agent-os to plugins.enabled
```

If only Step 1 is enabled:

- Memory-OS remains a working provider
- `prefetch`, `sync_turn`, `memory_os_status`, heartbeat, and module runtime can
  still work
- Hermes official plugin UI will not show the Agent OS shell
- `hermes plugins list` may still show the flat `memory_os` provider directory
  as `not enabled` on Hermes v0.14.0; this is not a failure and must not be
  "fixed" by adding `memory_os` to `plugins.enabled`

If only Step 2 is enabled:

- the shell must fail closed
- status should report `memory_os_provider_missing`
- no module runtime should run
- no hooks should mutate state

Installer direction:

- the repository installer may offer a one-command path that performs both
  steps
- provider enablement and shell enablement should still be reported separately
- failure in Step 2 must not disable or corrupt an already-working provider
- failure in Step 1 must prevent shell runtime activation

## Decision 5: Session Hooks Vs Heartbeat

Hooks are real-time session markers. Heartbeat is batch cognition.

v0.1 shell hook minimum:

```yaml
on_session_start:
  purpose:
    - write bounded audit/session marker
    - include session_id, platform, profile, timestamp
  forbidden:
    - prefetch
    - working memory evolution
    - candidate creation

on_session_reset:
  purpose:
    - write bounded reset marker
    - mark current session boundary for later continuity analysis
  forbidden:
    - delete working memory
    - rewrite past events
    - force carryover

on_session_finalize:
  purpose:
    - write bounded finalize marker
    - optionally request small heartbeat catch-up only if it stays non-blocking
  forbidden:
    - heavy digest/consolidation
    - DeepReflection run_once
    - send/execute/identity/crystallized writes
```

If the optional finalize catch-up is implemented, its limit must be explicit:

```yaml
optional_heartbeat_catch_up:
  max_events: 5
  timeout_ms: 200
  on_timeout: silent_skip_with_audit
  on_failure: silent_skip_with_audit
  must_not_block_session_finalize_return: true
```

If these limits cannot be met on the live host, v0.1 must omit finalize
catch-up and write only the bounded marker.

Hooks not registered in v0.1:

```text
pre_llm_call
post_llm_call
pre_tool_call
post_tool_call
pre_gateway_dispatch
```

v0.1 also does not register slash commands through `register_command`.
Operators should use:

```bash
hermes memory_os <command>
hermes memory-os-agent-os <command>  # optional shell alias after PS work
```

Slash commands such as `/memory-status` or `/carryover-preview` are deferred to
v0.2 if real users ask for in-session operator shortcuts.

Reason:

- the gateway turn path must stay light
- hook code must not bypass RH-12 event eligibility
- hook code must not become a hidden execution path
- MemoryProvider remains the owner of memory prefetch and turn capture
- heartbeat remains the owner of digestion and index catch-up

## Future Skill Path

Official plugins can register skills. Memory-OS should reserve this as a future
explicit read path, not v0.1 automatic injection.

Possible future skills:

```text
memory-os:deep-reflection-recent
memory-os:runtime-status
memory-os:governance-brief
```

Use case:

```text
Owner: "你最近有什么没说出来的想法？"
Agent: explicitly reads memory-os:deep-reflection-recent
```

This should not replace provider prefetch. It is a user-invoked or
model-invoked explicit view into current bounded artifacts.

## DeepReflection Configuration Notes

The official shell does not change current DeepReflection defaults.

Current guidance:

- keep `working_updates_enabled=false`
- keep LLM internal analysis behind a separate canary gate
- avoid the term `companion mode`
- use `profile-aware reflection policy` for future profile-specific behavior
- adjust `max_chars_total` only with RH-22 conversation regression evidence

Reason:

- RH-23 currently shows source-class skew toward `working`
- enabling working updates too early can reinforce that skew
- LLM analysis introduces a new trust and cost boundary
- "companion" suggests a product category; Memory-OS is an Agent OS cognition
  runtime

`profile-aware reflection policy` is only a naming decision in this document.
Its semantics should be defined in a future revision of
`17-deep-reflection-runtime-design.md` before any such mode is implemented.

## Implementation Phase

This document closes the compatibility decision. The initial shell
implementation was added after this decision record under
`plugins/memory-os-agent-os/`.

Proposed future slices:

```text
PS-01 Shell skeleton (implemented)
  - plugin.yaml
  - __init__.py with register(ctx)
  - status/doctor only
  - Memory-OS provider/runtime remains authoritative

PS-02 Minimal session hooks (implemented)
  - on_session_start marker
  - on_session_reset marker
  - on_session_finalize marker
  - no heartbeat catch-up in the initial implementation
  - markers write bounded Memory-OS audit entries only

PS-03 CLI aliases (implemented for status/doctor)
  - hermes memory-os-agent-os status
  - hermes memory-os-agent-os doctor
  - wrappers only; hermes memory_os remains authoritative

PS-04 Installer integration (implemented)
  - provider enablement and shell enablement reported separately
  - Step 2 failure cannot corrupt Step 1 provider
  - Step 1 failure prevents shell activation
  - installer copies `memory-os-agent-os` by default
  - `--enable-shell` adds `memory-os-agent-os` to `plugins.enabled`
  - installer output remains pure JSON even when provider enablement calls
    `hermes config set`
  - backup-looking Memory-OS provider/shell manifests are rejected under
    `$HERMES_HOME/plugins/`; backups belong under
    `$HERMES_HOME/plugin-backups/`

PS-05 10.20.3.200 validation (completed)
  - verify against the installed Hermes source, not only the website docs
  - run RH-22/RH-23/RH-24 checks
  - verify no duplicate carryover injection
  - verify `memory.provider=memory_os`
  - verify `memory-os-agent-os` is enabled as a user plugin shell
  - verify `memory_os` is not enabled as a general plugin
  - verify heartbeat timer and gateway remain active
  - verify shell hook smoke writes audit markers only
```

The installed Hermes source was inspected before PS-02. The live hook call
sites pass `session_id`, `model`, and `platform` for `on_session_start`; gateway
reset/finalize paths pass `session_id` and `platform`. Profile is not available
in the installed hook kwargs, so the initial shell marker writes to the active
`HERMES_HOME` Memory-OS audit only and does not attempt profile-specific state
mutation.

Implementation note: a test deployment initially left a backed-up copy of the
shell under `/root/.hermes/plugins/`. Hermes' plugin scanner found the nested
manifest and loaded a duplicate command. The backup was moved outside the
plugin scan tree. Future installer work should keep backups under
`$HERMES_HOME/plugin-backups/`, not under `$HERMES_HOME/plugins/`.

PS-04 installer work now enforces that rule for backup-looking Memory-OS
provider/shell manifests while allowing unrelated legitimate user plugins under
`$HERMES_HOME/plugins/`.

PS-05 validation on `10.20.3.200` was run through the installer path, not by
manual shell plugin copy. The validation confirmed:

- `hermes memory` shows `memory_os` as the active provider
- `hermes plugins list` shows `memory-os-agent-os` enabled and `memory_os` not
  enabled as a general plugin
- `hermes memory-os-agent-os status` and `doctor` delegate cleanly to the
  provider CLI
- RH-22 full seven-prompt regression passes
- RH-23 source-class monitoring remains observational
- RH-24 status-tool contract validation passes
- heartbeat catch-up and doctor end at `status=ok` with only the expected
  `hindsight_adapter_disabled` warning

## Validation Plan For A Future Shell

Before enabling a shell plugin on `10.20.3.200`:

1. Install provider only and confirm existing baseline:
   - `hermes memory`
   - `hermes memory_os status`
   - `hermes memory_os doctor`
   - heartbeat timer active/enabled
2. Install shell plugin without enabling:
   - `hermes plugins list` shows `memory-os-agent-os` as not enabled
   - no hooks run
   - provider behavior unchanged
3. Enable shell plugin:
   - `plugins.enabled` contains `memory-os-agent-os`
   - shell status aliases work
   - existing `hermes memory_os ...` commands still work
4. Run no-send integration checks:
   - RH-22 full seven-prompt regression
   - RH-23 source-class status
   - RH-24 status tool contract
   - `memory_os doctor`
5. Verify boundaries:
   - `actual_send=false`
   - `actual_execute=false`
   - `actual_identity_write=false`
   - `actual_crystallized_approval=false`
   - no Hindsight export
   - no duplicate Conversation Carryover section

## Non-Goals

v0.1 shell work must not:

- rewrite Memory-OS provider discovery
- move carryover into `pre_llm_call`
- split modules into many official plugins
- rename existing CLI commands
- force `plugins.enabled` for the memory provider itself
- enable DeepReflection working updates
- enable LLM internal analysis
- introduce real send or execute paths
- touch `10.20.2.88` or Sannai production state

## Final Decision

Memory-OS should remain a provider-first Agent OS.

The official Hermes plugin system should be used as a thin operator-facing shell
around the existing runtime, not as a replacement for the runtime. This gives
users standard Hermes plugin discovery and enablement while preserving the
validated Memory-OS safety model.
