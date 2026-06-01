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

Do not select Hermes' direct Hindsight provider when running Memory-OS:

```yaml
memory:
  provider: memory_os
```

`memory.provider: hindsight` is a different, ungoverned Hermes provider path and
is not the Memory-OS integration path.

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
configuration and is the default for automated installs. The resolved provider
and model are checked dynamically at judge-call time, so changing the Hermes
default model is picked up without writing a Memory-OS model override. If the
adapter becomes unavailable after a Hermes upgrade or model change, Memory-OS
reports degraded judge availability and continues with the deterministic guard
path. The default judge response budget is sized for reasoning models that may
emit `reasoning_content` before final JSON.

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

## Optional Governed Hindsight Substrate

Hindsight is an optional Memory-OS substrate provider. It is not selected through
Hermes `memory.provider=hindsight`, and Memory-OS does not reuse or fork the
Hermes Hindsight plugin. Memory-OS keeps `memory.provider=memory_os` selected
and, when configured, connects to Hindsight through its own governed client.

Installer modes:

| Mode | Use when | Effect |
| --- | --- | --- |
| `--hindsight auto` | normal upgrade path | adopts an existing `$HERMES_HOME/hindsight/config.json` into Memory-OS shadow mode; leaves Hindsight disabled when no legacy config exists |
| `--hindsight off` | fresh open-source install or conservative profile | writes an explicit disabled Hindsight substrate config |
| `--hindsight adopt` | controlled migration where Hindsight must already exist | fails if the legacy Hindsight config is absent |
| `--hindsight wizard` | future guided setup | currently deferred; no live enablement |

Config keys live under `substrate_providers.hindsight`:

```json
{
  "substrate_providers": {
    "hindsight": {
      "enabled": false,
      "adoption_source": "none",
      "api_url": "",
      "bank_id": "",
      "api_key_env_var": "HINDSIGHT_API_KEY",
      "retain_enabled": false,
      "recall_mode": "off",
      "reflect_enabled": false,
      "allowed_retain_sources": ["crystallized", "owner_approved"],
      "reject_raw_turns": true
    }
  }
}
```

The legacy `hindsight_adapter_enabled` flag is compatibility-only. The effective
configuration source is `substrate_providers.hindsight`.

Governance rules:

- Retain accepts only `crystallized`, `owner_approved`, or explicitly distilled
  records. Raw turns and working transcript bodies are refused.
- Hindsight is a derived projection of Memory-OS canonical data. Retain and
  retract/invalidate events are recorded in append-only ledgers; stale
  projection counts are monitor stop signals.
- Recall is deterministic from Memory-OS' perspective and is recorded as
  advisory `derived_projection` evidence with `substrate_snapshot_id`.
- LocalArtifact remains primary authority. Hindsight facts must never outrank
  local crystallized or owner-approved facts, even in active recall mode.
- Reflect is disabled by default, off the hot path, and never writes canonical
  memory directly. When explicitly enabled and applied, Hindsight reflect output
  is queued only as a bounded crystallized candidate for owner review.
- The global live guard kill switch forces optional external substrates
  disabled.

Operator commands:

```bash
hermes memory-os-agent-os hindsight status
hermes memory-os-agent-os hindsight adopt --dry-run
hermes memory-os-agent-os hindsight retain-pending --dry-run
hermes memory-os-agent-os hindsight retract --record-id <id> --reason demoted --dry-run
hermes memory-os-agent-os hindsight reflect --query "..." --dry-run
hermes memory-os-agent-os review reply "memory revoke oa_<token>" --apply
```

Automated deployment wrapper:

```bash
python scripts/deploy_memory_os.py \
  --host hermes-media \
  --remote-repo-root /opt/Hermes-Memory-OS \
  --hermes-home /root/.hermes \
  --profile upgrade \
  --phase dry-run \
  --mode operational \
  --hindsight auto
```

The wrapper exposes `plan`, `preflight`, `dry-run`, `apply`, and `postcheck`
phases. It does not restart Hermes unless explicitly invoked with
`--allow-restart` and `--restart-command`.

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
hindsight_substrate.no_raw_retained = true
hindsight_substrate.recall_llm_triggered = false
hindsight_substrate.reflect_off_hot_path = true
hindsight_substrate.projection_stale_count = 0
hindsight_substrate.local_first_authority_preserved != false
hindsight_substrate.external_authoritative_count = 0
```
