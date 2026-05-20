# Existing System Audit

Date: 2026-05-20

Source host: `10.20.2.88 / YC-NAS`

Mode: read-only SSH inspection.

## Boundary

This audit records structure and metadata only. It intentionally omits private
session bodies, private prompts, raw memory contents, secrets, tokens, cookies,
and API keys.

No production files were changed. No gateway or cron service was restarted.

## Runtime Topology

Observed production topology:

| Surface | Evidence |
| --- | --- |
| Hermes version | `v0.14.0 (2026.5.16)` |
| Project root | `/vol1/.hermes/hermes-agent` |
| Main HERMES_HOME | `/vol1/.hermes` |
| Sannai HERMES_HOME | `/vol1/.hermes/profiles/sannai` |
| Main gateway | `hermes-gateway.service` |
| Sannai gateway | `hermes-gateway-sannai.service` |
| Other active service | `hermes-memory-watchdog.service` |
| Main platform bridge | WhatsApp bridge spawned by main gateway |
| Sannai live heartbeat | `scripts/sannai_cloud_heartbeat_live.py` process observed |

Main and Sannai already have profile separation at the service level. A module
system must preserve this and must not assume one global state root.

## Worktree Condition

The production Hermes checkout is not a clean distributable source:

- tracked files are modified
- many local-only scripts and backup directories exist
- mailbox platform code is untracked in the observed checkout
- several systems live under `/vol1/.hermes/scripts`, outside the agent repo
- skill code and plugin bridge code are split across different roots

Conclusion: production is a source of behavior and evidence, not a package to
copy directly.

## Existing Plugin-Like Surfaces

### mailbox platform

Observed:

```text
/vol1/.hermes/hermes-agent/plugins/platforms/mailbox/plugin.yaml
/vol1/.hermes/hermes-agent/plugins/platforms/mailbox/adapter.py
/vol1/.hermes/hermes-agent/scripts/mailbox_status.py
```

The manifest identifies `mailbox-platform` as `kind: platform`. This is a real
plugin-shaped component, but it does not yet represent the full module lifecycle
needed by the portable system: install, enable, disable, status, doctor,
no-send, and profile-local dependency checks.

### hermes-self-evolution bridge

Observed:

```text
/vol1/.hermes/plugins/hermes-self-evolution/plugin.yaml
/vol1/.hermes/plugins/hermes-self-evolution/__init__.py
/vol1/.hermes/plugins/hermes-self-evolution/README.md
```

The manifest declares an `on_session_start` hook. Its own README describes it
as a runtime context bridge for `runtime_digest.md`, not the governor itself.

Conclusion: this is a bridge plugin, not a complete Self-Evolution module.

## Skill And Script Surfaces

### Self-Evolution Governor

Observed:

```text
/vol1/.hermes/skills/dogfood/self-evolution-governor/SKILL.md
/vol1/.hermes/skills/dogfood/self-evolution-governor/scripts/*.py
/vol1/.hermes/scripts/self_evolution_daily_pipeline.py
/vol1/1000/hermes-self-evolution/
```

The skill defines metacognition, self-positioning, signal collection, proposal
feedback, agenda maturation, and speak-gate behavior. It maintains artifacts
such as:

```text
signals.jsonl
self_agenda.yaml
proposal_queue.yaml
evolution_journal.md
agenda_candidates.yaml
runtime_digest.md
score_explanations/
```

Current coupling:

- skill instructions
- cron jobs
- direct state file conventions
- script-level orchestration
- runtime digest injection bridge

Target extraction: split into governance/evidence modules with Memory-OS read
and write sinks instead of direct global state assumptions.

Reference project:

`/vol1/1000/hermes-self-evolution/` is a previous self-contained
Self-Evolution modularization attempt. It includes `setup.sh`, a plugin bridge,
skill package, pipeline script, demo state files, and architecture/tuning docs.
Use it as design input for packaging and setup ergonomics, not as the complete
target for the current full-system architecture.

### Ops-Gate

Observed:

```text
/vol1/.hermes/scripts/ops_gate_runner.py
/vol1/.hermes/scripts/ops_gate_daily_audit.py
/vol1/.hermes/scripts/ops_weekly_review.py
/vol1/.hermes/state/ops-gate/
```

Current role:

- execution gate result collection
- daily audit report
- weekly review report
- watchdog state and pipeline outputs

Target extraction: `governance/ops_gate` with explicit action-boundary checks,
report-only mode, and no production mutation in test installs.

### Wandering Mind And Household Digest

Observed cron surfaces:

```text
Wandering Mind · 每周自由漫游
Wandering Mind 家庭语境摘要刷新
Family Room 低频回顾
Family Room 每日摘要
```

Observed script/state surfaces:

```text
/vol1/.hermes/scripts/generate_household_digest.py
/vol1/.hermes/scripts/household_digest_gate_entry.py
/vol1/.hermes/state/wandering/
/vol1/.hermes/state/warming/household_digest.md
```

Current coupling:

- cron schedules
- household digest state
- production delivery mode for weekly wandering
- right-brain prompt contract distributed outside Memory-OS

Target extraction: `cognition/wandering_mind` plus `context/household_digest`,
both reading bounded Memory-OS summaries. Delivery remains no-send by default.

### Sannai Inner/CW-019 Surfaces

Observed:

```text
/vol1/.hermes/hermes-agent/scripts/sannai_cloud_heartbeat_live.py
/vol1/.hermes/hermes-agent/scripts/sannai_cloud_heartbeat_shadow.py
/vol1/.hermes/hermes-agent/scripts/sannai_lingering_state.py
/vol1/.hermes/scripts/sannai_curation/*.py
/vol1/.hermes/state/sannai/
/vol1/.hermes/profiles/sannai/scripts/*.py
```

Current role:

- lingering state
- heartbeat windows
- owner review reports
- memory journal and digest generation
- weekly consolidation proposals
- profile-local Sannai scheduling

Target: compatibility only.

Sannai is private deployment state, not a public moduleization target. These
surfaces should not be extracted into reusable packages by default. They may
inform compatibility tests for profile isolation, no-send behavior, and owner
approval boundaries, but public modules must not depend on Sannai-specific
identity, diary, heartbeat, or curation files.

## Main Cron Inventory

Selected relevant main-profile jobs:

| Job | Deliver | Current role |
| --- | --- | --- |
| Self-Evolution daily pipeline | origin | Governor reflection and runtime digest |
| Self-Evolution weekly review | origin | Strategy review |
| Wandering Mind weekly free wandering | origin | Right-brain expression |
| Wandering Mind household digest refresh | local | Context preparation |
| Ops daily audit | origin | Gate report |
| Ops weekly review | origin | Gate review |
| CW-019 owner review report | origin | Sannai candidate review report |
| CW-019 nightly generation | local | Sannai inner candidate window |
| Sannai consolidation report | origin | Long-term memory gate report |
| Family Room low-frequency review | local | Cross-profile/context review |
| Family Room daily summary | local | Cross-profile/context summary |

Risk: several jobs currently use `deliver=origin`, which means a portable test
module must default to `no-send` or `would-send` to avoid accidental outbound
messages.

## Sannai Cron Inventory

Selected Sannai-profile jobs:

| Job | Deliver | Current role |
| --- | --- | --- |
| 三奶的自由时间 | origin | Scheduled front-facing expression |
| random heartbeat | local | Profile-local heartbeat |
| afterglow checks | origin | Follow-up expression checks |
| treasure index refresh | local | Local index refresh |
| daily digest | local | Daily experience digest |
| weekly consolidation proposal | local | Memory consolidation proposal |
| memory journal refresh | local | Event-card journal |

Risk: these jobs are identity/personality-sensitive and should not be treated
as generic module defaults. They can inform interfaces, not define them.

Decision: Sannai jobs are not v0.1 module extraction targets. They remain
private compatibility constraints.

## State Roots

Observed state families:

```text
/vol1/.hermes/state/evolution/
/vol1/.hermes/state/ops-gate/
/vol1/.hermes/state/wandering/
/vol1/.hermes/state/warming/
/vol1/.hermes/state/sannai/
/vol1/.hermes/profiles/sannai/
```

Reusable modules should not read these paths directly. They should read through
profile-local config or Memory-OS views.

## Audit Conclusion

Claude's architecture concern is correct.

Memory-OS is portable. The rest of the Hermes cognition/governance/expression
stack is only partially plugin-shaped and remains tied to production-specific
cron, scripts, state roots, and skill instructions.

The next v0.1 work should be system modularization, starting from module
contracts and no-send test-host validation, not production migration.
