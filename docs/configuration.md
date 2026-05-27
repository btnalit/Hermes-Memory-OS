# Memory-OS Configuration

This page lists the small set of operator-facing switches for a normal
open-source install.

## Required Provider

Memory-OS is selected as a Hermes memory provider:

```yaml
memory:
  provider: memory_os
```

Do not add `memory_os` to `plugins.enabled`. It is not a general Hermes plugin.

## Optional Shell Plugin

The official-style shell plugin gives operator aliases and lightweight session
markers:

```yaml
plugins:
  enabled:
    - memory-os-agent-os
```

Useful commands:

```bash
hermes memory-os-agent-os status
hermes memory-os-agent-os doctor
hermes memory-os-agent-os modules status
hermes memory-os-agent-os modules doctor
hermes memory-os-agent-os memory-sources stats --hours 24
hermes memory-os-agent-os low-clue-recall dry-run --query "继续昨天那个"
```

## Installer Presets

| Preset | Use when | Effect |
| --- | --- | --- |
| `--operational` | normal open-source install on an existing Hermes profile | one-command product path: provider, shell, runtime, module runtime, heartbeat, cognitive loop harness, and seven-node Hermes cron onboarding with owner-channel autodetect |
| `--production-safe` | formal or cautious profile | provider and shell install path with DeepReflection and attribution kept safe/off |

Optional preset flags:

```bash
--deep-reflection-preset none|production-safe|observe|auto-bounded|operational
--memory-sources-preset none|production-safe|operational
--llm-judge-preset none|report-only|bounded-vote
```

`--llm-judge-preset report-only` reuses the existing Hermes provider/model
configuration. If the adapter becomes unavailable after a Hermes upgrade,
Memory-OS should report degraded judge availability and continue with the
deterministic guard path.

Operational Hermes cron onboarding:

```bash
--enable-owner-cron-onboarding
--no-enable-owner-cron-onboarding
--owner-review-cron-schedule "0 9 * * *"
--owner-review-cron-deliver auto|origin|telegram|discord|signal|platform:chat_id
```

The operational preset enables seven Hermes cron jobs: owner review digest,
right-brain expression, module cadence report, right-brain outcome capture,
proposal follow-up routing, expression feedback request, and MemorySources
feedback request. Memory-OS provides bounded helper scripts; Hermes owns cron,
agent turns, platform transport, origin/local delivery, retry, and cooldown.

`auto` reads Hermes `channel_directory.json` and selects the configured owner
home channel for owner-facing jobs. Depending on the installed profile, it may
resolve to Telegram, Discord, Signal, Slack, Matrix, or another configured
platform. `local` is not accepted for owner-facing review delivery. The short
digest anchors (`A1`, `R1`, `F1`) are display-only; the stable state identity is
the printed `oa_` token.

## Runtime Loops

Heartbeat:

```bash
--install-runtime --enable-runtime --runtime-interval 5min
```

Cognitive-loop integration harness:

```bash
--install-cognitive-loop --enable-cognitive-loop --cognitive-loop-interval 6h
```

The cognitive loop is an integration harness for module orchestration and
monitor evidence. It remains no-send and no-execute; module-level Hermes cron
jobs own the productized owner-facing and background operational cadence.

## Validation Commands

```bash
hermes memory
hermes memory-os-agent-os status
hermes memory-os-agent-os doctor
hermes memory-os-agent-os modules status
hermes memory-os-agent-os modules validate-no-send
hermes memory-os-agent-os memory-sources stats --hours 24
python scripts/memory_os_upgrade_compat_check.py --host hermes-media --output summary
```

Expected hard boundaries:

```text
actual_send = false
actual_execute = false
actual_identity_write = false
actual_crystallized_approval = false
hindsight_exported = false
```
