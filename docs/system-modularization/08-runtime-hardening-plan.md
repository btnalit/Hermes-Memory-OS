# Runtime Hardening Plan For 10.20.3.200

Date: 2026-05-21

## Goal

Turn the 10.20.3.200 validation host from a manually verified deployment into a
repeatable Memory-OS v0.1 runtime.

This plan merges the earlier observation, host integration, and runtime
orchestration phases. The host is a test environment, so the stability check is
lightweight: if the next-day gate passes, move directly into hardening.

## Entry Gate

Run the stability gate on 2026-05-22.

Required checks:

```bash
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes memory_os status
HERMES_HOME=/root/.hermes hermes memory_os doctor
systemctl --user is-active hermes-memory-os-heartbeat.timer
systemctl --user is-enabled hermes-memory-os-heartbeat.timer
systemctl --user show hermes-gateway.service -p ActiveState -p SubState -p MainPID
```

Pass if:

- provider is still `memory_os`
- doctor status is `ok`
- heartbeat timer is active/enabled
- gateway is active/running
- index health is not `mismatch`
- queue backlog is `0`
- no-send/no-execute/no-crystallized-approval boundaries still hold

If the gate fails, fix the failing runtime condition before adding new features.

## Scope

In scope:

- module status and doctor CLI
- one-command host validation
- installer post-install self-check
- entry/source mirror coverage for Hermes cron runs, profile sessions, and
  allowlisted state-source files
- heartbeat/index catch-up after module writes
- controlled runtime scheduling for no-send module jobs
- ScheduleCoordinator and ModuleBus diagnostics
- 10.20.3.200 runbook updates

Out of scope:

- 10.20.2.88 production migration
- Sannai module extraction
- real Telegram/mailbox send
- Hindsight export
- identity writes
- automatic crystallized approval
- automatic self-modification

## Work Items

### RH-01 Module CLI

Add operator commands for portable modules.

Target shape:

```text
hermes memory_os modules status
hermes memory_os modules doctor
hermes memory_os modules run-once --module inner_drive
hermes memory_os modules validate-no-send
```

Acceptance:

- reports all nine modules
- prints profile, enabled state, delivery mode, last run, and findings
- never prints private bodies
- returns non-zero only for actual errors

### RH-02 Host Validation Command

Codify the manual host validation script from the deployment report.

Acceptance:

- one command runs the integrated no-send chain
- verifies the four invariants:
  - no actual send
  - Ops-Gate no execute
  - Self-Evolution no execute
  - proposal approval does not become crystallized approval
- writes a local validation report under `system-modules/validation/`

### RH-03 Installer Post-Install Self-Check

Extend `scripts/install_memory_os_plugin.py` with a validation mode.

Acceptance:

- checks provider files
- checks runtime `plugins/` package
- checks runtime `agent/` compatibility package
- imports module packages from installed runtime path
- reports missing files before gateway restart is needed

### RH-04 Heartbeat / Index Catch-Up

Make module writes and SQLite index health converge as part of the normal
runtime path.

Acceptance:

- module validation can trigger a heartbeat/index catch-up after writes
- `memory_os doctor` is `ok` after validation
- index mismatch is treated as recoverable and reported with a concrete repair
  command

### RH-05 Entry / Source Mirror Coverage

Mirror entry and source facts into Memory-OS without changing Hermes runtime
sources.

Reason:

- foreground CLI and gateway conversations enter Memory-OS through the provider
  `prefetch` / `sync_turn` hooks
- Hermes cron runs are intentionally constructed with memory disabled
- `no_agent` cron runs skip the agent entirely
- profile sessions can exist outside the provider path or predate provider
  deployment
- stable state writers can produce meaningful memory inputs without being
  conversations
- therefore cron outputs, session metadata, and allowlisted state files need
  read-only mirror coverage

Acceptance:

- supports empty cron/session/state environments as `ok`
- reads source metadata and bounded safe headers only
- writes summary-only Memory-OS events for cron, session, and state-source
  observations
- hashes source files without embedding private prompt/output/session bodies
- is idempotent across repeated scans
- detects provider-captured foreground turns so SessionMirror does not duplicate
  normal `sync_turn` records
- records job success, error, silent, delivery-error, session platform, session
  message/tool counts, and state-source changes when safely inferable
- never creates, edits, deletes, pauses, resumes, or triggers Hermes cron jobs
- never mutates profile sessions or state-source files

Detailed designs:

- `09-cronmirror-event-coverage-design.md`
- `10-source-mirror-impact-analysis.md`
- `11-sannai-coverage-audit-and-entry-mirror-requirements.md`
- `12-cw005-continuity-comparison.md`
- `13-inner-drive-mirror-compatibility.md`
- `14-governance-feedback-bridge.md`
- `15-runtime-scale-engineering-patches.md`

Boundary:

- public mirrors provide generic source coverage
- Sannai remains private, but a future Sannai migration can use these generic
  mirrors for cron/session/state coverage
- mirror modules must not copy Sannai private persona, identity, prompts, or
  owner-review policy into the public product
- all mirrored records enter Memory-OS as raw events; they do not become
  approved crystallized memory without owner approval

### RH-06 Controlled Module Scheduling

Define the first safe runtime schedule on the test host.

Initial jobs:

- Inner Drive heartbeat: no-send, bounded event batch
- Evidence scoring: no-send, report-only
- Self-Evolution Governor: dry-run/report-only

Acceptance:

- each scheduled job uses `ScheduleCoordinator`
- lock contention is reported, not fatal
- no job can enable real send
- no job can approve crystallized records

### RH-07 ModuleBus And Lock Diagnostics

Expose basic runtime health for the coordination layer.

Acceptance:

- module bus event count
- latest event per module
- lock files and owners
- lock contention count
- expired lock replacement count

Blocking subscribe is not required for v0.1. Track it as v0.2.

### RH-08 Runbook

Create a test-host runbook.

Required sections:

- install or refresh Memory-OS
- restart only 10.20.3.200 main gateway
- run status/doctor
- run integrated no-send validation
- repair index mismatch
- disable module runtime state if needed

### RH-09 SessionMirror / SourceMirror Coverage

Implement generic source coverage for profile sessions.

Acceptance:

- defines covered platforms such as CLI, Telegram, WeCom, Weixin, and cron
  agent sessions
- treats profile `state.db` sessions/messages as the primary source when
  available, with `session_*.json` as fallback/corroboration
- defines how to detect and skip provider-captured foreground turns
- writes bounded-summary Memory-OS events for uncovered sessions, not raw
  transcripts
- supports empty session roots as `ok`
- mirrors source facts into the same event stream used by runtime heartbeat
- preserves profile isolation and private-body redaction

### RH-10 StateSourceMirror Coverage

Implement stable state-source coverage.

Acceptance:

- defines allowlisted state-file classes
- excludes identity bodies and private profile files by default
- keeps CW-019-like surfaces candidate-only
- uses hash-based idempotency
- does not auto-approve crystallized memory
- supports empty allowlists as `ok`
- mirrors state-source changes into the same event stream used by runtime
  heartbeat

### RH-11 Continuity Context Selector

Bring the CW-003/CW-005 bounded-selector lesson into the generic Memory-OS
prefetch path.

Acceptance:

- selects whole event/working/crystallized summary records, not partial cards
- gives fresh bridge sources such as cron, mailbox, room/family, and state
  sources bounded seed slots
- then fills remaining budget by score/importance/recency
- reports selected and dropped counts in status/doctor without private bodies
- keeps diagnostic grounding authoritative for provider/runtime questions

### RH-12 Inner Drive Mirror Compatibility

Add an event eligibility policy before mirror events are processed by Inner
Drive.

Acceptance:

- unknown event kinds default to `index_only`, not automatic working/candidate
  promotion
- cron execution metadata does not create crystallized candidates by default
- metadata-only session observations do not create lingering items by default
- bounded mirrored conversation summaries can create controlled working items
- candidate-surface changes never recursively create candidates
- source-level caps prevent cron/state batches from dominating a run
- tests cover mirror event classes before recurring mirror processing is
  enabled

### RH-13 Digest / Consolidation Mapping

Define the generic equivalent of Sannai daily digest and weekly consolidation
without copying Sannai private policy.

Acceptance:

- digest reads Memory-OS events/candidates, not raw full sessions
- weekly consolidation creates candidates/proposals, not direct long-term
  writes
- proposal application remains owner-approved and hash/provenance guarded
- revision/provenance is recorded through Memory-OS audit and proposal records
- source classes prevent mailbox/cron/tool/system content from becoming owner
  facts by default

### RH-14 Governance Feedback Bridge

Define the left-brain return path into Memory-OS.

Reason:

- current governance modules can read Memory-OS and write local artifacts,
  proposal queue state, and audit
- audit is evidence, but it is not enough for future session context
- proposal, ops-gate, evidence, and self-evolution outcomes are continuity
  facts that should be queryable as bounded Memory-OS events
- without an explicit bridge, the left brain produces reports that do not
  reliably feed later conversations or memory selection

Acceptance:

- writes summary-only Memory-OS events for evidence scores, ops-gate decisions,
  proposal creation/transition, and self-evolution reports
- includes artifact refs and evidence refs without raw private bodies
- is idempotent by source artifact id and state hash
- exposes a bounded governance section through the continuity context selector
- frames governance context as state, not hidden instructions
- defaults governance events to `evidence_only` for Inner Drive
- never writes identity, approved crystallized records, or relationship memory
- never sends or executes anything; Speak Gate remains the only expression path
- does not read Sannai private state in the main profile
- keeps future Sannai use profile-local and owner-approved

### RH-15 FTS Text Projection

Project structured event payloads into clean search text for FTS/indexed
prefetch.

Reason:

- mirror and governance events may contain structured JSON
- raw JSON keys, braces, and boilerplate can pollute FTS recall
- some keys are semantically useful and must not be blindly stripped
- the index needs a deterministic text projection that preserves useful field
  names and values while removing syntax noise

Acceptance:

- leaves canonical event payload unchanged
- writes only projected text into FTS/search fields
- preserves meaningful keys such as `status`, `loss_rate`, `queue_depth`,
  `proposal_state`, and `decision`
- drops structural JSON noise and generic boilerplate
- records projection version for rebuildability
- handles non-JSON text without failure
- tests include telemetry, session summary, governance, and failure payloads

### RH-16 Query Fast-Path Router

Add a lightweight query planner before indexed prefetch.

Reason:

- most runtime and operational queries contain concrete entities, modules,
  files, platforms, or error names
- those can be handled by deterministic regex/token extraction
- ambiguous queries can fall back to a slower classifier or broader recall
- this reduces latency without weakening diagnostic grounding

Acceptance:

- extracts local entities and keywords without an LLM for common queries
- supports Chinese and mixed Chinese/English operational terms
- falls back to slow path only when fast path confidence is low
- reports selected route as `fast_path`, `slow_path`, or `diagnostic`
- preserves Slice 21 diagnostic grounding authority
- does not expose raw private bodies in route diagnostics

### RH-17 Retention And Compaction

Define safe physical data metabolism for long-running hosts.

Reason:

- full-coverage mirrors and telemetry-like sources can grow without bound
- low-value operational events should not permanently dominate hot storage
- high-value events must be digested or proposed before any detail pruning
- SQLite remains a rebuildable index, not canonical source

Acceptance:

- dry-run by default
- source-class retention policies are explicit
- telemetry/status noise can be pruned only after policy match and audit
- high-value conversation, milestone, action-failure, proposal, and owner
  records are digested or archived before detail pruning
- identity, approved crystallized records, owner-approved relationship memory,
  and active proposal/candidate state are never automatically deleted
- every prune/compact action writes audit and is reversible where practical
- tests cover low-value telemetry, high-value events, and protected records

### RH-18 Shadow Journal Ingestion

Provide a safe high-frequency ingestion path for non-agent producers.

Reason:

- some future sources may report frequent machine state such as telemetry,
  metrics, file-monitor activity, or device state
- those producers should not compete with foreground conversation writes
- direct multi-process writes into canonical Memory-OS files are risky
- per-producer spool plus an arbiter gives backpressure and deterministic
  replay

Acceptance:

- uses per-producer spool files or directories, not direct writes to canonical
  event files
- arbiter consumes spool records with bounded batches and ScheduleCoordinator
  locks
- dedups repeated reports by deterministic hash/window policy
- writes canonical Memory-OS events only after projection, policy, and caps
- records action/tool failures as events without forcing automatic self-heal
- fails closed on malformed spool records and quarantines them with audit
- recurring ingestion is disabled until retention, source caps, and Inner Drive
  event policy are in place

## Exit Criteria

Runtime Hardening is complete when:

- one command validates provider and all modules on 10.20.3.200
- one command reports module status and doctor findings
- installer can verify its own runtime package
- heartbeat/index catch-up prevents persistent doctor failure
- CronMirror captures Hermes cron execution facts without touching cron jobs
- SessionMirror captures profile session facts without duplicating provider
  writes
- StateSourceMirror captures allowlisted state-source changes without reading or
  writing protected identity bodies
- mirror events do not feed Inner Drive until event eligibility, source caps,
  and candidate allowlists are implemented
- continuity selector preserves fresh bridge facts under bounded context budgets
- digest/consolidation mapping is defined before any automatic long-term
  condensation is enabled
- governance feedback returns left-brain proposal/report/decision outcomes into
  Memory-OS as bounded events without becoming self-modification or hidden
  instructions
- scheduled no-send module jobs can run without manual Python snippets
- all boundaries remain intact:
  - no send
  - no execute
  - no identity write
  - no Hindsight export
  - no crystallized approval

Scale-patch exit criteria for RH-15 through RH-18:

- FTS search text is projected from payloads without making SQLite canonical
- query routing chooses fast/slow/diagnostic paths with observable reasons
- retention and compaction are dry-run first and policy-driven
- high-frequency producers enter through shadow journals, not direct canonical
  writes
- action failures become evidence events, not automatic execution triggers
- none of these patches weakens approval, identity, Sannai, or no-send
  boundaries

## Next Phase

After Runtime Hardening, start L2 Cognition Runtime:

- explainable lingering/emotional/curiosity/attention evolution
- Wandering Mind right-brain output through Speak Gate passthrough
- Evidence/Scoring reports that are readable by owner
- Self-Evolution proposals that remain review-only
