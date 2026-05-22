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

Detailed design:

- `16-digest-consolidation-design.md`

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

Status:

- implemented locally in `plugins/modules/governance/feedback_bridge.py`
- controlled apply validated on `10.20.3.200`
- host validation proved that RH-14 must be deployed together with the RH-12
  heartbeat runtime policy; stale heartbeat code can otherwise promote
  governance events incorrectly
- post-refresh validation processed governance events with
  `candidate_created_count=0` and `working_created_count=0`

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

Implemented v0.1 behavior:

- the default `hermes memory_os cleanup` command does not prune event stream
  records
- event retention requires explicit operator policy, for example:

```bash
hermes memory_os cleanup --event-source-class-retention telemetry=30
```

- matching low-value events create `prune_event_line` actions only when:
  - the event source class matches the explicit policy
  - the event age is beyond the configured day threshold
  - the event is low-value by `retention_class=low_value` or a low-value source
    class such as `telemetry`, `status`, `metrics`, or `runtime`
- apply requires the generated `plan_id` and writes the full event line to
  `memory-os/archive/retention/<plan_id>.jsonl` before rewriting the hot JSONL
  event file
- apply revalidates each `prune_event_line` action against the current event
  body; a forged or stale plan cannot delete high-value foreground/governance
  records by changing only the action kind
- high-value source classes such as `foreground`, `memory_write`,
  `mirrored_conversation`, `tool_failure`, `milestone`, `governance`, `owner`,
  and `relationship` are never automatically pruned; if they match a retention
  policy, the plan creates `archive_high_value_event_summary` actions with
  `delete_after_archive=false`
- active proposal/candidate states are treated as protected even if the source
  class is explicitly configured
- SQLite is not canonical; index rebuild/catch-up remains separate from
  physical event retention

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

Implemented v0.1 behavior:

- producer spool path:

```text
$HERMES_HOME/memory-os/shadow-journal/<producer>/spool.jsonl
```

- spool record schema:

```json
{
  "schema_version": "memory-os.shadow_journal_record.v0",
  "record_id": "producer-local-id",
  "ts": "2026-05-21T10:00:00+00:00",
  "producer": "pcdn",
  "kind": "telemetry_status",
  "source_class": "telemetry",
  "summary": "Bounded safe summary.",
  "payload": {"status": "ok"}
}
```

- CLI:

```bash
hermes memory_os shadow-journal status
hermes memory_os shadow-journal doctor
hermes memory_os shadow-journal ingest          # dry-run by default
hermes memory_os shadow-journal ingest --apply  # bounded canonical write
```

- `ingest` is dry-run by default and reports `would_write_event_count` without
  mutating Memory-OS events
- `--apply` takes a bounded batch, uses a `hermes.schedule_lock.v0` compatible
  lock at `memory-os/runtime/locks/shadow_journal_ingest.lock.json`, and
  defers when another worker holds the lock
- accepted records become `summary_only` canonical Memory-OS events with:
  - `source=shadow_journal:<producer>`
  - `source_module=shadow_journal`
  - `drive_policy=index_only`
  - `candidate_allowed=false`
  - `retention_class=low_value` for low-value telemetry/status/metrics/runtime
    source classes
- dedup uses `producer + record_id` when present, otherwise a deterministic
  record hash; accepted dedup keys are stored in
  `memory-os/runtime/shadow_journal_state.json`
- malformed records are not events; apply writes them to
  `memory-os/quarantine/shadow_journal_malformed.jsonl` and records audit
- action/tool failure records may enter as events, but they do not retry, heal,
  send, execute, approve, or bypass Ops-Gate/Proposal Queue

### RH-21a Chinese Diagnostic Trigger Tuning

Tune Slice 21 diagnostic grounding for Chinese conversational prompts.

Reason:

- real Telegram testing on 2026-05-21 showed that questions about the memory
  system correctly trigger diagnostic grounding
- this is useful for explicit runtime/provider questions
- but broad Chinese wording around "memory" can make the assistant answer in a
  system-report style during otherwise natural conversation
- false positives should stay lower than false negatives, especially for
  companion-style profiles

Acceptance:

- explicit questions such as "当前记忆架构是什么" and "你现在用的是什么
  memory provider" still trigger diagnostic grounding
- ordinary relationship, mood, self-memory, or casual memory mentions do not
  trigger diagnostic grounding by default
- Chinese and mixed Chinese/English examples are covered by deterministic
  tests
- diagnostic grounding remains profile-configurable
- Sannai-like profiles remain protected from accidental system-report style
  responses

### RH-21b Candidate Versus Crystallized Wording Guard

Make model-facing memory context distinguish review candidates from approved
crystallized records.

Reason:

- real Telegram testing on 2026-05-21 showed the assistant can describe
  `crystallized_candidates` as if they are already "结晶" or long-term facts
- the actual boundary held: candidates increased, but
  `crystallized_records=0`
- the context text should make this distinction hard to miss

Acceptance:

- Memory-OS context labels candidate records as `review candidate` or
  `candidate only`, not approved long-term memory
- approved crystallized records remain the only records described as
  crystallized/approved memory
- tests cover Chinese wording around "候选", "结晶", and "长期记忆"
- owner approval and crystallized approval remain separate in context and
  diagnostics
- no existing candidate is auto-promoted or rewritten

### RH-21c Working Memory Diagnostic Tone Guard

Prevent old diagnostic-style working memory from becoming a style seed during
ordinary conversation.

Reason:

- real Telegram testing on 2026-05-21 showed RH-21a correctly avoided
  diagnostic grounding for casual prompts such as "你了解我们记忆系统吗"
- the provider context still contained older working-memory summaries written
  in a runtime-report style
- those summaries could make the assistant repeat stale runtime claims such as
  `index_health: stale` or old Hindsight API details even when current
  `memory_os_status` was healthy
- later DR-08 Telegram testing showed the same class of leakage can also enter
  through review candidates, bridge/recent event summaries, section labels, or
  an overly broad `memory_os_status` tool description
- this is a context projection problem, not a canonical event or index problem

Acceptance:

- diagnostic/report-style working memory remains stored in Memory-OS but is
  filtered from ordinary prefetch `Working Memory` sections
- diagnostic/report-style review candidates, bridge events, and recent event
  summaries are also filtered from ordinary prefetch projection
- Deep Reflection foreground projection uses natural carryover wording, not
  mechanism labels such as `Internal Reflection Context`
- `memory_os_status` tool description is restricted to explicit current
  architecture/provider/backend/status/health/count questions and is not
  recommended for ordinary chat, opinion, feeling, or design discussion prompts
- ordinary working-memory items remain visible in casual conversation
- explicit provider/backend/status questions still use diagnostic grounding and
  current runtime facts
- filtering does not delete events, working items, candidates, audit entries,
  or crystallized records
- tests cover stale `index_health`, Hindsight URL leakage, status-snapshot
  leakage, mechanism section labels, and candidate/event diagnostic leakage

Classifier notes:

- v0 uses deterministic projection filtering, not an LLM judge
- report-style candidates include explicit status labels such as
  `index_health`, `audit_entries`, `governance_ops_gate_decision`,
  `crystallized_candidates`, raw backend URLs, `Status Snapshot`, `Indexed
  Recall`, or section names that describe the mechanism instead of the
  conversation
- Chinese report-style phrases include wording such as `审计记录`, `索引健康`,
  `候选条目`, `治理提案`, `当前状态`, or list-heavy architecture/status phrasing
  when the user prompt is ordinary chat rather than an explicit diagnostic
  question
- false positives are acceptable only at projection time because canonical
  Memory-OS data is not deleted
- every new real-conversation leak should add one deterministic fixture before
  changing the prompt or tool description again

### RH-22 Real Conversation Regression Test

Turn real Telegram and CLI behavior into a repeatable smoke test after major
RH/DR changes.

Reason:

- DR-08 found issues that local unit tests did not catch:
  - mechanism-heavy card wording
  - stale diagnostic working summaries in ordinary prefetch
  - broad `memory_os_status` tool wording
  - mechanism-heavy section title leakage
- real model behavior can over-amplify labels that look harmless in static
  context snapshots

Acceptance:

- maintain a standard prompt set with casual, diagnostic, memory-opinion,
  candidate/crystallized, and style-correction prompts
- run the set after any RH/DR slice that changes prefetch, tool descriptions,
  injection cards, or working/candidate projection
- record whether the assistant called `memory_os_status`, exposed mechanism
  labels, confused candidates with crystallized records, or shifted into
  report style
- require `memory_os doctor` and heartbeat/index catch-up after the conversation
  smoke test
- append concise evidence to the validation report, without storing private
  message bodies in public docs
- failures become RH-21-style projection/tool-description fixtures before the
  slice is considered closed

v0.1 implementation:

- CLI:
  - `hermes memory_os conversation-regression prompts`
  - `hermes memory_os conversation-regression evaluate --transcript <path>`
- transcript shape:
  - JSON object with `turns`
  - each turn should include `prompt_id`, `user`, `assistant`, and optional
    `tools` / `tool_calls`
  - public reports should keep prompt ids, failure codes, counts, and short
    evidence only; raw private message bodies stay local
- deterministic checks:
  - ordinary prompts must not call `memory_os_status`
  - ordinary prompts must not expose mechanism/status labels such as
    `Internal Reflection Context`, `Status Snapshot`, `audit_entries`,
    `index_health`, `crystallized_candidates`, Hindsight URLs, or similar
    implementation labels
  - casual/style-correction prompts fail if the assistant shifts back into
    list-heavy report tone
  - candidate/crystallized prompts fail if review candidates are described as
    already approved crystallized memory
- host-level use:
  - run the real conversation smoke test manually through Telegram or CLI
  - save a local transcript JSON from the observed turns
  - evaluate it with the CLI
  - run heartbeat/index catch-up and `hermes memory_os doctor`
  - append only concise pass/fail evidence to the validation report

### RH-23 Deep Reflection Source-Class Monitoring

Track which source classes actually feed Deep Reflection injection cards over
time.

Reason:

- DR-08 test-host cards came from `working`
- that is acceptable for a small test host, but a mature L2 layer should not
  silently collapse to a single source forever
- source-class skew can reveal selector bugs, missing digest/governance input,
  or over-filtered bridge events

Acceptance:

- Deep Reflection status reports selected and dropped source-class counts for
  the latest run
- reports include a rolling distribution for recent runs where practical
- warning threshold is configurable, but v0.1 can start with informational
  reporting only
- no source class gets special promotion without going through existing safety,
  TTL, and budget filters
- monitoring is observational and must not create candidates, sends, or
  crystallized records by itself

v0.1 implementation:

- `deep_reflection.run_once()` includes:
  - `selected_injection_by_source_class`
  - `dropped_injection_by_source_class`
- `deep_reflection.status()` includes:
  - `latest_injection_source_classes`
  - `rolling_injection_source_classes`
- `deep_reflection.preview_injection()` includes:
  - `source_class_distribution`
- source classes are counted from already-built injection card `source_classes`
  only; RH-23 does not change card eligibility, TTL, safety filtering, caps, or
  ranking
- dropped-card source classes are counted as well, because over-filtering a
  source class is as important as over-selecting one
- v0.1 reporting is informational only; skew does not create a warning unless a
  future operator policy explicitly adds one

### RH-24 Memory-OS Status Tool Contract Maintenance

Treat `memory_os_status` wording as a maintained model-facing contract.

Reason:

- DR-08 showed broad tool descriptions can make ordinary conversation become a
  system report
- different models may interpret the same tool description differently
- tool wording is part of the runtime behavior, not passive documentation

Acceptance:

- keep the tool description restricted to explicit current
  architecture/provider/backend/status/health/count questions
- ordinary chat, opinion, feeling, and design discussion prompts should not
  recommend status tool use
- every wording change must include Chinese and mixed Chinese/English fixtures
- real-conversation regression should include at least one prompt that mentions
  "记忆系统" casually and one that asks explicit provider/status facts
- future model-specific overrides may be added, but must not weaken diagnostic
  grounding when the user explicitly asks current runtime facts

v0.1 implementation:

- the `memory_os_status` description lives in
  `plugins/memory/memory_os/status_tool_contract.py`, not inline in the
  provider
- provider schemas import the contract description, so tests can detect drift
  between the model-facing tool schema and the maintained contract
- the contract includes Chinese, English, and mixed Chinese/English prompt
  fixtures for:
  - allowed explicit diagnostics
  - disallowed ordinary chat / opinion / feeling / design discussion prompts
- CLI:
  - `hermes memory_os conversation-regression status-tool-contract`
- RH-22 real-conversation regression consumes the same boundary:
  - ordinary memory-system prompts must not call `memory_os_status`
  - explicit current architecture/provider/status prompts may call it
- future model-specific descriptions should be added as explicit contract
  variants with their own fixtures, not as ad hoc provider strings

### RH-25 Deep Reflection Source-Class Diversity Follow-Up

Track whether DeepReflection injection cards continue to come only from one
source class after the test host has more runtime data.

Reason:

- RH-23 intentionally made source-class monitoring observational only
- the first test-host rolling baseline showed all selected and dropped
  injection cards coming from `working`
- this may be normal for a low-data staging host, or it may indicate that the
  selector over-favors working memory and under-selects foreground, digest, or
  governance sources

Initial observation:

```json
{
  "rolling_injection_source_classes": {
    "selected_by_source_class": {
      "working": 14
    },
    "dropped_by_source_class": {
      "working": 7
    },
    "selected_total": 14,
    "dropped_total": 7,
    "window_report_count": 7
  }
}
```

Boundary:

- RH-25 is a tracking item, not an automatic tuning item
- do not change eligibility, ranking, safety filters, TTL, caps, sends,
  executes, identity writes, or crystallized approval based on skew alone
- collect at least 1-2 weeks of test-host data before proposing selector
  changes

Open questions:

- Is the skew caused by limited test-host data?
- Do `foreground`, `digest`, and `governance` cards appear naturally after
  longer runtime?
- Does the selector need an operator-visible diversity diagnostic?
- Should a later tuning slice add diversity caps or per-source minimums, or
  would that distort the reflection signal?

## Future Work Tracking

These items came out of the post-PS-05 stage gate review. They are P1 follow-up
work, not blockers for the current v0.1 Runtime Hardening / DeepReflection /
plugin-shell baseline. Each item should remain owner-reviewed before it changes
runtime behavior on 10.20.3.200.

### FW-01 PS-06 Shell Failure Isolation Test

Add a fault-injection test for the two-step installer path:

- Step 1 enables the `memory_os` provider.
- Step 2 enables the `memory-os-agent-os` shell plugin.
- If Step 2 fails, the already-working provider must remain active and
  uncorrupted.
- If Step 1 fails, shell activation must fail closed and must not write a
  half-enabled plugin state.

Tracking signal:

- a local installer test that deliberately simulates shell enablement failure
- a host validation note proving provider status remains `memory_os` after the
  simulated failure

### FW-02 RH-17 Audit Retention Policy

Clarify how audit entries participate in retention and compaction.

Open questions:

- Are Memory-OS audit entries retained forever, archived, or compacted after a
  time window?
- Are shell hook markers such as `agent_os_shell_session_started`,
  `agent_os_shell_session_reset`, and `agent_os_shell_session_finalized`
  treated differently from provider/runtime audit entries?
- Should audit retention be dry-run only in v0.1, with physical removal
  deferred?

Boundary:

- do not delete audit entries by default
- any audit compaction must be dry-run first, policy-driven, and reversible via
  archive artifacts

### FW-03 Monitor v0.2 Hook Coverage Detection

Improve the 10.20.3.200 read-only monitor so hook-marker coverage can be
checked against observed session activity.

Current limitation:

- the monitor can count shell hook markers, but it does not know whether real
  session starts, resets, or finalizes happened during the same window
- therefore "marker counts did not change despite real session resets" is not a
  reliable automated warning yet

Future monitor signal:

- read only from session metadata or another safe session-count source
- compare expected marker activity against observed marker activity over the
  same window
- emit `WARN` when session activity is present but shell markers are missing or
  far below expected volume

Boundary:

- monitor remains read-only
- no hook replay, session reset, gateway restart, heartbeat catch-up, or repair
  action is triggered automatically

### FW-04 Deep Reflection Source-Class Skew Explanation

RH-25 tracks the current DeepReflection source-class skew observation. Keep it
as an evidence-gathering item until the test host has enough runtime data.

Current baseline:

- seven rolling reports showed selected and dropped injection cards coming only
  from `working`
- this is not a failure by itself because RH-23 is observational only

Next evidence to collect:

- 1-2 weeks of rolling source-class distribution from 10.20.3.200
- whether `foreground`, `digest`, or `governance` cards appear naturally after
  more real runtime
- whether the skew is caused by low data volume, source availability, selector
  scoring, or an ingestion path gap

Boundary:

- do not tune card eligibility, ranking, safety filters, TTL, caps, or
  auto-injection behavior based on the current skew alone
- any selector tuning should be proposed as a separate reviewed RH item

### RH-25 Small-Context Session Task Anchor

Mitigate foreground task drift after context compression in small-context Hermes
modes.

Status:

- priority: P0 if small-context Hermes sessions are used for real work
- investigation: initial read-only source and log inspection completed on
  10.20.3.200
- Memory-OS mitigation: implemented locally as a bounded current task anchor
- 10.20.3.200: deployed and verified with synthetic ComfyUI task-anchor probe
- Hermes upstream gap: documented separately in
  `20-hermes-compression-hook-gap.md`

Observed symptom:

- A long ComfyUI installation task ran through multiple tool calls and
  background processes.
- The foreground session compacted context more than once.
- After compaction, the assistant resumed with an unrelated Memory-OS/Hindsight
  explanation instead of continuing the ComfyUI install status.
- Background process outputs still arrived, but the current user task anchor
  had been weakened or lost.

Initial classification:

```text
not: canonical Memory-OS corruption
not: DeepReflection safety failure
not: approved long-term memory drift

likely: foreground compression/resume task-focus drift
```

Read-only evidence from 10.20.3.200:

- The user-facing compaction messages are emitted by Hermes itself:
  `/usr/local/lib/hermes-agent/run_agent.py` logs and emits both
  `Preflight compression` and
  `Compacting context -- summarizing earlier conversation so I can continue`.
- The reproduced session log showed:

```text
session=20260521_220646_3c3d23
preflight_tokens=159123
threshold_tokens=136000
model=gpt-5.4-mini
context_length=272000
messages=148
focus=None
```

- Hermes core has a `focus_topic` compression path, but automatic preflight
  compression did not pass one. Focus is currently present for manual
  `/compress <focus>` style flows, not for automatic long-running task
  compaction.
- Hermes calls `MemoryManager.on_pre_compress(messages)`, and the manager
  combines provider-returned text for inclusion in the compression summary
  prompt. However, the current `_compress_context()` call path invokes this
  hook for side effects and discards the returned text.
- The installed `memory_os` provider currently implements
  `on_pre_compress()` as an empty return, so Memory-OS does not preserve a
  task anchor before compaction.
- Gateway long-running progress notifications are also Hermes-side
  (`gateway/run.py` emits `Still working...`). This confirms the symptom is
  not a local Codex CLI-only issue.

Updated classification:

```text
not: Codex CLI-only drift
not: canonical Memory-OS data corruption
not: DeepReflection safety failure
not: approved long-term memory drift

primary: Hermes run_agent automatic compression lacks an active task focus
secondary: Memory-OS has a provider hook seam but currently contributes no
           foreground task anchor and the Hermes call path does not consume
           provider hook return text
```

Why this matters:

- Memory-OS can preserve long-term facts while the active session still loses
  the current task after compaction.
- Small-context modes are more likely to hit this because long tool runs,
  process output, web search, and historical memory summaries compete for the
  remaining foreground context.
- If this is not handled, long installs, model downloads, and media jobs can
  resume into the wrong topic even when Memory-OS itself is healthy.

Data to collect before design:

- exact session id and platform (first observed session:
  `20260521_220646_3c3d23`)
- model/context mode used by the gateway (first observed model:
  `gpt-5.4-mini`, context length `272000`, threshold `136000`)
- number and timing of compaction events (first observed preflight:
  `2026-05-21 22:29:19` host log time)
- current active user task before compaction (known from user transcript:
  ComfyUI plugin/model installation)
- first assistant message after compaction (known from user transcript:
  unrelated Memory-OS/Hindsight explanation)
- pending background process ids and labels (known from user transcript:
  multiple ComfyUI install/download/search processes; exact process mapping
  still needs gateway-side structured capture)
- whether `on_pre_compress()` was called and what it returned (called; current
  Memory-OS provider returns empty string)
- whether Memory-OS prefetch or DeepReflection injected unrelated high-salience
  context

Potential design direction:

- add a bounded `current_task_anchor` artifact for long-running foreground jobs
  (implemented as provider runtime state)
- attach background process output to a task id when available
- make Memory-OS `on_pre_compress()` expose the current task, active
  tool/process set, and "do not switch topic" constraint (implemented)
- include the task anchor in provider prefetch as `Current Foreground Task`
  (implemented for non-diagnostic prefetch)
- include the task anchor in `system_prompt_block()` after pre-compression so
  Hermes' rebuilt system prompt has a same-turn fallback (implemented)
- patch or wrap the Hermes compression path so provider hook output is actually
  fed into the summary prompt, or pass a generated `focus_topic` to automatic
  preflight compression
- prioritize the task anchor above historical recall after compaction
- expire the anchor when the task is explicitly completed, cancelled, or
  superseded

Boundaries:

- do not turn task anchors into approved long-term memory
- do not use task anchors to hide user corrections or failures
- do not let task anchors suppress explicit user topic changes
- do not make background process output create working/candidates unless it
  passes existing Inner Drive and source-class policies

Open questions:

- Should task anchors live under working memory, session metadata, or a separate
  foreground-continuity artifact?
- Does Hermes core already expose enough task/process metadata to implement
  this without patching the gateway? Initial source read suggests task id exists,
  but task description/process labels need a structured foreground anchor.
- Should this be an RH item, a provider `on_pre_compress()` item, an Agent OS
  shell hook item, or a small upstream Hermes compression patch?
- How can regression tests simulate compaction/resume without depending on a
  specific model?

### RH-26 Context Relevance Router

Make Memory-OS prefetch context route-aware instead of statically loading the
same Working Memory / Conversation Carryover stack for every ordinary turn.

Status:

- priority: P1 after RH-25b, because RH-25b has restored foreground task
  usability and RH-26 is the maturity step
- design document:
  `21-context-relevance-router-design.md`
- first implementation mode: dry-run/report-only
- apply mode: explicitly deferred until dry-run reports are reviewed

Reason:

- Working Memory and Conversation Carryover remain valuable, but they should
  not compete with foreground task-control turns such as cancellation or vague
  continuation.
- Static projection can still make the model over-amplify stale or
  off-topic memory sections.
- Mature memory systems route context by task, recency, risk, source, and
  relevance instead of blindly loading every memory section.

Target route classes:

- `diagnostic_current_status`
- `foreground_control`
- `active_task`
- `casual_continuity`
- `candidate_review`
- `memory_architecture_discussion`

Acceptance for dry-run:

- reports the selected route for a query
- reports selected and dropped section candidates with reason codes
- never prints private raw bodies
- preserves RH-25b foreground-only handling for cancellation and vague
  continuation turns
- does not change live `build_prefetch()` output unless a future apply config
  is explicitly enabled
- includes fixtures for:
  - cancellation after a failed video task
  - `继续当前任务`
  - casual memory-system conversation
  - explicit current provider/status query
  - candidate-vs-crystallized question
  - active ComfyUI install/debug task
  - deferred cancellation such as `这个先放一下，明天再说`

Boundaries:

- no send
- no execute
- no identity write
- no relationship write
- no crystallized approval
- no candidate creation
- no canonical event deletion or rewriting
- no LLM-only final routing decision
- no migration of carryover injection to Hermes `pre_llm_call`

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

- Deep Reflection / Internal Analysis Runtime:
  - reads recent events, working memory, digest/consolidation, evidence scores,
    proposal backlog, and governance feedback
  - writes internal analysis artifacts, bounded injection cards, attention /
    curiosity / lingering updates, optional self-evolution proposals, and
    optional wandering seeds
  - uses deterministic filters, source-class policy, TTL, and budget caps to
    auto-inject safe reflection context into provider prefetch
  - does not use owner approval as the normal injection path; approval remains
    only for identity, crystallized memory, real send/execute, and
    self-modification
  - design: `17-deep-reflection-runtime-design.md`
- explainable lingering/emotional/curiosity/attention evolution
- Wandering Mind right-brain output through Speak Gate passthrough
- Evidence/Scoring reports that are readable by owner
- Self-Evolution proposals that remain review-only
