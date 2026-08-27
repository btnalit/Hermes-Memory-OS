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

## Optional Remote Embedding and Reranking

The open-source core keeps external model services optional and disabled by
default. No model-serving or ML dependency is required by the core package.

A deployment may provide an OpenAI-compatible embedding endpoint for online
vector queries and a small `/rerank` endpoint for post-retrieval display
ranking. The embedding endpoint must return `data[].embedding`; the reranker
must return `results[]` entries with `index` and `relevance_score` (or `score`).

The embedding endpoint is configured through the reversible `vector_embedder_endpoint`
knob. When it is empty, the existing local embedder behavior is preserved. The
`vector_embedder_model` and `vector_embedder_device` knobs remain deployment
owned; the endpoint may represent a remote GPU or CPU service. Batch/index-sync
callers continue using the local path unless the deployment explicitly adds a
separate batch adapter.

The optional reranker is configured under `memory_reranker` and remains
fail-open to the original RRF result:

```json
{
  "memory_reranker": {
    "enabled": false,
    "mode": "disabled",
    "provider": "http",
    "endpoint": "",
    "model": "",
    "candidate_limit": 12,
    "rerank_candidate_limit": 12,
    "output_limit": 5,
    "timeout_ms": 12000,
    "fallback": "rrf"
  }
}
```

When enabled, the reranker receives only the query and bounded candidate text
from the existing retrieval result, and reorders the current crystallized-memory
candidates only — it does not change FTS5, vector retrieval, RRF semantics,
deduplication, context routing, canonical memory, graph state, candidate state,
or approval state. It does replace the crystallized-section truncation policy:
the pre-existing MAX_TOTAL=20 record cap is bypassed, and the section is capped
at `memory_reranker.output_limit` (default 5) instead. Provider failure,
timeout, invalid JSON, or empty results return the original RRF path and
restore the MAX_TOTAL=20 cap.

Keep service addresses, model paths, credentials, and profile-specific values
outside the public repository. The production overlay should be applied by the
operator after installing or upgrading the open-source core.

## Installer Presets

| Preset | Use when | Effect |
| --- | --- | --- |
| `--operational` | normal open-source install on an existing Hermes profile | one-command product path: provider, shell, runtime, module runtime, heartbeat, cognitive loop harness, and active-closure Hermes cron onboarding with owner-channel autodetect |
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
--owner-cron-profile active-closure|full
--owner-review-cron-schedule "0 9 * * *"
--owner-review-cron-deliver auto|origin|telegram|discord|signal|platform:chat_id
```

The operational preset defaults to `--owner-cron-profile active-closure`, which
creates **8 Hermes cron jobs** scheduling **22 governed lanes**.

`cron_registry.py` keeps two tables, and the split is load-bearing:

- **Lanes** (`MEMORY_OS_CRON_LANES`) — the governance identity: `lane_id`,
  helper script, `risk_class`, boundary contract. Every lane opens its own
  ExecutionGate permit and writes its own completion evidence on every run.
- **Groups** (`MEMORY_OS_CRON_GROUPS`) — the Hermes scheduling surface, i.e.
  what `hermes cron create` actually creates.

Consolidating lanes into shared tick jobs reduces the cron surface without
merging any governance boundary.

| Job | Schedule | Member lanes |
| --- | --- | --- |
| `memory-os-tick-derived` | `2,17,32,47 * * * *` | `event_stats_refresh`, `index_sync`, `state_overlay_refresh`, `entity_index_refresh` |
| `memory-os-tick-governance` | `7,37 * * * *` | `proposal_followups_opsgate`, `clearance_cycle` |
| `memory-os-tick-evidence` | `12 * * * *` | `hindsight_health_probe`, `fact_judge`, `candidate_aggregation`, `l3_probe_verification`, `v3_wandering`, `session_fact_extraction` |
| `memory-os-tick-daily` | `5 0 * * *` | `exposure_rollup`, `v3_seed_evidence`, `v3_journal_sweep`, `working_cleanup`, `state_source_mirror`, `hindsight_advisory_digest` |
| `memory-os-owner-review-digest` | `0 9 * * *` | `owner_review_digest` |
| `memory-os-memory-sources-feedback-request` | `30 10 * * *` | `memory_sources_feedback_request` |
| `memory-os-expression-feedback-request` | `0 5 * * 0` | `expression_feedback_request` |
| `memory-os-full-monitor-refresh` | `30 2 * * *` | `full_monitor_refresh` |

Tick minutes are staggered so no two group jobs start in the same minute.

Per-lane cadence is preserved by `due_interval_minutes` rather than by cron: a
tick fires at its fastest member's rate and skips members that are not yet due.
Date-partitioned lanes use `due_policy="calendar"` instead, so they run at most
once per UTC day and cannot drift across a day boundary.

Adding a new lane means adding it to a group — **not** creating a cron job.

See `cron_registry.py` for the authoritative list.

That is the current automatic closure chain: owner-visible decisions remain in
the normal Hermes owner channel, while safe proposal follow-up routing is
report-only/OpsGate process motion. Runtime heartbeat and the cognitive-loop
timer handle sensing, projection, advisor reports, and low-risk lane evidence.

`--owner-cron-profile full` additionally creates the optional module cadence
report job. That job is a product surface, not a prerequisite for the
active-closure logic chain. On upgraded hosts, active-closure onboarding pauses
known optional Memory-OS cron jobs instead of deleting them. Running the `full`
profile restores the optional cron surface when it is intentionally needed.
Paused optional jobs are classified as known optional rather than unregistered
drift.

Upgrading from a pre-consolidation host is non-destructive: the old per-lane
jobs (`memory-os-index-sync`, `memory-os-working-cleanup`, …) are **paused, not
deleted**, and are classified `superseded_by_group_tick`. Re-enabling them and
disabling the group ticks is the rollback path, so their gate wrapper scripts
stay installed on purpose.

To stop one lane without stopping its whole tick, list its registry key in
`$HERMES_HOME/memory-os/system/cron_lane_disabled.json`. The tick runner skips
it and the monitor reports it as disabled rather than as missing evidence.

Memory-OS provides bounded helper scripts; Hermes owns cron, agent turns,
platform transport, origin/local delivery, retry, and cooldown.

The approval boundary is trust-boundary based, not process-step based. Memory-OS
may automate reversible/report-only workflow such as signal collection,
shadow scoring, proposal creation, proposal follow-up routing, OpsGate
report-only review, stale/duplicate queue closure, digest rendering, and
owner-channel delivery. Owner approval remains required for crystallized writes,
revoke/demote/delete, route/score authority, identity/relationship writes,
third-party or public external sends, unbounded autonomous acting, and any
specific lane graduation that removes per-item owner approval from an
apply-capable path. In particular, `apply_proposal` is a boundary action, while
safe proposal follow-up routing is not.

SessionMirror is a data-ingress lane. A production apply is fail-closed until an
owner-home digest approval records `approve_session_mirror_apply`. That approval
graduates the bounded lane, not each individual session: after graduation, the
runtime heartbeat may automatically import at most the approved
`auto_apply_max_sessions_per_run` sessions per run from the approved platform
allowlist. SessionMirror still writes only bounded `conversation_turn_mirrored`
events, never crystallized memory, policy, identity, route/score authority, or
external sends.

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
| `--hindsight auto` | normal upgrade path | adopts a new `$HERMES_HOME/hindsight/config.json` into Memory-OS shadow mode, preserves an already-active Memory-OS Hindsight adoption for the same provider bank, and leaves Hindsight disabled when no legacy config exists |
| `--hindsight off` | fresh open-source install or conservative profile | writes an explicit disabled Hindsight substrate config |
| `--hindsight adopt` | controlled migration where Hindsight must already exist | fails if the legacy Hindsight config is absent |
| `--hindsight active` | controlled live cutover after operator approval | adopts the provider bank with `retain_enabled=true`, `recall_mode=active`, and `reflect_enabled=true`; recall remains advisory and LocalArtifact-first |
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
python scripts/memory_os_cron_adapter_probe.py --host hermes-media --output json
python scripts/memory_os_boundary_runtime_probe.py --host hermes-media --output json
python scripts/memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
python scripts/memory_os_public_checkout_probe.py --source head --strict
python scripts/memory_os_public_checkout_probe.py --source working-tree --strict
```

Evidence labels are intentionally separate: fast probe PASS proves cron/gate
health, while the full monitor owns live production health. A WARN/`FAIL=[]`
full monitor must not be described as a clean live PASS unless the WARN is
separately accepted and documented.

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
