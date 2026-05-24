# Memory-OS Configuration

This page lists the small set of operator-facing switches. Most implementation
details live in `docs/system-modularization/`.

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
| `--production-safe` | formal or cautious profile | provider and shell install path with DeepReflection and attribution kept safe/off |
| `--test-host` | isolated test host | enables heartbeat, cognitive loop, Memory Sources metadata, and no-send observation presets |

Optional preset flags:

```bash
--deep-reflection-preset none|production-safe|observe|auto-bounded|test-host
--memory-sources-preset none|production-safe|test-host
--llm-judge-preset none|report-only|bounded-vote
```

`--llm-judge-preset report-only` reuses the existing Hermes provider/model
configuration. If the adapter becomes unavailable after a Hermes upgrade,
Memory-OS should report degraded judge availability and continue with the
deterministic guard path.

## Runtime Loops

Heartbeat:

```bash
--install-runtime --enable-runtime --runtime-interval 5min
```

Test-host cognitive loop:

```bash
--install-cognitive-loop --enable-cognitive-loop --cognitive-loop-interval 6h
```

The cognitive loop is for isolated test-host observation. It remains no-send and
no-execute.

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
