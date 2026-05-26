# 36 - Module Closure Matrix

Date: 2026-05-25

Status: active contract supplement.

Purpose: make every left-brain, right-brain, memory, expression, scheduler, and
owner-review module declare how its outputs close. This document exists because
RH-34 showed that "modules are running" is not enough; each module must also say
whether the owner sees anything, whether an action is required, which gate owns
that action, and how the result feeds back into Memory-OS.

## Rules

- Ordinary conversation does not require owner approval.
- Scheduled owner review digest delivery is pre-authorized by configuration and
  Hermes cron; it is not per-message approval.
- State-changing actions require explicit owner action or a separate apply gate.
- Memory-OS does not own platform transport. Hermes owns cron delivery and
  platform adapters.
- `mailbox` is an AI-agent mailroom/status surface, not an owner channel.
- Monitor-only evidence is not closure for owner-actionable artifacts.
- Feedback first enters a ledger/evidence surface. It must not mutate live
  routing, memory, identity, or proposal state without a later bounded apply
  gate.

## Reference Patterns From Hermes Main / Sannai

Read-only reference checks on the `10.20.2.88` Hermes host show mature patterns
that Memory-OS should integrate with instead of reimplementing:

- Owner-facing scheduled messages use Hermes cron delivery such as
  `deliver=origin`. Main Hermes uses this for daily/weekly owner reports and
  Sannai uses it for free-time / afterglow checks.
- Internal state refresh, index, journal, and pipeline jobs use `deliver=local`
  or `no_agent` script jobs. These jobs may write local artifacts but do not
  message the owner.
- Hermes cron already owns delivery semantics: script stdout is the payload,
  empty stdout can be silent, and `[SILENT]` belongs to Hermes cron/mailbox
  delivery contracts rather than Memory-OS transport code.
- Hermes mailbox is an AI-agent mailroom with controls such as `final_only`,
  `proactive_send_enabled`, `auto_wake_cooldown`, reply-depth review, and
  `[NO_REPLY]`. It is not an owner review channel and should not be used as the
  Memory-OS approval surface.
- Sannai memory curation separates autonomous proposals from owner-reviewed
  state changes: she may propose, but major memory/identity/provider changes
  require owner review.

These references define the default boundary for Memory-OS:

```text
owner-facing delivery -> Hermes cron / origin / platform adapter
internal processing   -> local or no-agent script with monitor evidence
state change          -> OwnerActionProcessor or explicit apply gate
```

## Closure Classification Fields

Every new module, RH slice, scheduler, or review artifact should declare these
two fields before implementation:

| Field | Values | Meaning |
| --- | --- | --- |
| `delivery_class` | `none` | No owner-visible delivery. |
| `delivery_class` | `owner_origin` | Owner-visible scheduled delivery through Hermes cron/platform semantics such as `origin`, `telegram`, or explicit platform target. Memory-OS must only provide bounded payload. |
| `delivery_class` | `internal_local` | Internal local job or artifact path. No owner message. |
| `delivery_class` | `no_agent_script` | Pure script/no-agent cron style. Script stdout/status is the artifact; Hermes owns optional delivery. |
| `delivery_class` | `hermes_mailbox_internal` | AI-agent mailroom path only. Not an owner governance surface. |
| `state_change_class` | `none` | No state change beyond declared artifacts. |
| `state_change_class` | `monitor_only` | Produces evidence, counters, reports, or scorecards only. |
| `state_change_class` | `context_projection` | Affects prompt/context visibility only; must use ContextProjection and attribution. |
| `state_change_class` | `candidate_review` | Produces memory candidates that require owner review before crystallized write. |
| `state_change_class` | `proposal_review` | Produces proposals that require owner approval before follow-up and never execute by approval alone. |
| `state_change_class` | `feedback_ledger` | Records owner/model feedback as evidence; live tuning requires a later bounded apply gate. |
| `state_change_class` | `expression_feedback` | Records owner feedback and delivery outcomes about right-brain expression quality; prompt/cadence/policy changes require later proposal/apply gates. |
| `state_change_class` | `speak_permission` | Produces or consumes one-shot speech permission; does not enable default sending. |
| `state_change_class` | `retention_metadata` | Archives/prunes metadata only; canonical memory is out of scope. |

If a module does not fit one of these values, it is not ready to implement.
Add the missing class to this document first.

## Cadence Classes

RH-27 currently runs a test-host cognitive loop every 6 hours and a runtime
heartbeat every 5 minutes. That proves the full loop can run, but it is not the
final cadence contract for every module. Each module should also declare one of
these cadence classes:

| cadence_class | Meaning | Default expectation |
| --- | --- | --- |
| `event_driven_fast` | Runs frequently to ingest new conversation/events and keep runtime state fresh. | 5 minutes on test host; no-op runs update state but should not spam audit. |
| `cycle_each` | Runs once per cognitive-loop cycle because downstream modules depend on fresh output. | Every cognitive-loop cycle, currently 6 hours on test host. |
| `daily_once` | Runs at most once per local day even if the cognitive loop runs more often. | Should be idempotent and skip if today's artifact exists. |
| `weekly_once` | Runs at most once per local week. | Should be idempotent and skip if this week's artifact exists. |
| `owner_daily` | Owner-facing digest or review delivery. | Hermes cron owns schedule and delivery, typically daily owner-local morning. |
| `on_demand` | Runs only from CLI, owner action, eval, monitor, or explicit gate. | No background run unless another scheduler calls it. |
| `monitor_poll` | Read-only observation / summary. | Monitor cadence; no writes except its own snapshot outside Memory-OS canonical state. |
| `disabled_until_opt_in` | Capability exists but is not scheduled until explicit owner/operator opt-in. | Must expose dry-run/status before enablement. |

Cadence rules:

- A module running in the 6-hour cognitive loop may still be internally gated as
  `daily_once` or `weekly_once`. The loop may call it, but the module should
  skip rather than duplicate artifacts.
- Owner-facing delivery cadence belongs to Hermes cron. Memory-OS should not
  create its own timer or transport loop.
- No cadence may imply approval. Approval is a separate owner action or apply
  gate.
- If a module has no new inputs, it should prefer a bounded skipped/no-op status
  over repeated audit/report growth.
- Any future cadence change must update monitor fields and promotion/stop
  signals in the roadmap before being called an observation period.

## Module Matrix

| Module | Reads | Writes | Owner action? | May speak? | Gate | Feedback / backflow |
| --- | --- | --- | --- | --- | --- | --- |
| Heartbeat / Inner Drive | events, index, working state | working items, crystallized candidates, audit | candidate approval only when candidate is owner-readable | no | MemoryWriteSurface, OwnerActionProcessor | approved/rejected candidates feed candidate scoring and future consolidation |
| Household Digest | recent events / working summaries | household digest artifact | no direct action | no | scheduler + monitor | feeds Wandering Mind and DeepReflection inputs |
| Digest Consolidation | events, candidates, proposal state | daily/weekly digest artifacts, candidate/proposal hints | candidate/proposal only if emitted into review queue | no | OwnerActionProcessor for emitted items | recurring stable facts can become better candidates; stale signals feed retention |
| Wandering Mind | household digest, safe recent state | wandering output, expression drafts, would-send artifacts | no owner action for ordinary scheduled expression; exceptional proactive-send permission only | possible through Hermes origin after SpeakGate and owner-configured cadence | SpeakGate, RH-38, Hermes transport | expression feedback and ignored/delivered trends feed speak policy and review burden |
| Speak Gate | expression payloads, proposal queue, expression policy | scheduled-expression / would-send / blocked-send / silent decisions | `allow_speak_once` only for out-of-policy proactive sends | only via Hermes after scheduled config or one-shot permission | SpeakGate + RH-38 + Hermes delivery | blocked/allowed/delivered/feedback counts feed expression tuning |
| DeepReflection | working, digest, governance, proposal/evidence summaries | carryover cards, analysis, optional proposals, optional wandering seeds | split by output type | only wandering seeds indirectly | ContextProjection, Proposal approval, SpeakGate | source-class distribution, selected/dropped classes, optional output outcomes |
| Ops Gate | operational proposals / policies | allow/block reports | approved proposals may be routed into report-only OpsGate review; never execution | no | OpsGate + explicit execution command | approved/rejected proposal classes influence future governance |
| Proposal Queue | proposal candidates, legacy owner-review inputs | proposal queue state | approve/reject proposal | no | OwnerActionProcessor | approval creates follow-up state only; rejection downranks similar deterministic class |
| Evidence Scoring | events, candidates, proposals, working items | evidence scores | no direct owner action | no | monitor/eval | score distribution informs candidate/proposal ranking, not direct approval |
| Self-Evolution | evidence scores, proposal queue, runtime findings | self-evolution digest, proposal candidates | approve/reject proposal | no | Proposal approval + OpsGate | accepted proposals become human-controlled follow-up, not auto execution |
| Governance Feedback | module reports, proposal/evidence/speak state | governance events / feedback bridge records | no direct action | no | monitor + feedback ledger | turns module outcomes into bounded events for future reflection and scoring |
| Conversation Carryover | current conversation / DR cards | projected context section | no | no | RH-26/RH-28 ContextProjection | MemorySources attribution and RH-30 feedback tune relevance later |
| Context Router / Low-Clue Recall | query, ingress decision, memory/index/source metadata | context sections and recall clarification guard | no | no | IngressDecision + ContextProjection | owner correction/feedback feeds RH-30/RH-28 guards after apply gate |
| MemorySources Attribution | live prefetch metadata | attribution JSONL | feedback only | no | FeedbackSignal | useful/irrelevant/too_mechanistic feedback informs later bounded routing changes |
| RH-31 Eval Harness | fixture corpus, safe adapters | scorecards and eval reports | no | no | Eval/monitor | failures become fixtures or findings only after live/owner evidence |
| Metadata Retention | metadata ledgers/reports | archives/pruned metadata | no | no | retention policy | controls growth; never deletes canonical memory |
| Owner Review Queue / Aging | candidates, proposals, speak items, owner actions | review projection, effective priority | no by itself | no | OwnerAction Contract | reduces burden; does not approve/reject/close canonical targets |
| Review Digest Renderer | review queue, aging, bounded candidate/proposal text | owner-readable digest text and active digest binding | no by itself | configured digest delivery only | Export eligibility + Hermes cron | owner readability and response burden feed renderer limits |
| Agent-Mediated Review Surface | latest owner-home digest, review queue, proposal follow-ups | bounded read-only page/detail/follow-up reports | no | no | ContextProjection for owner review + no-write boundary | lets Hermes agent answer "下一页/展开/还有哪些" without Memory-OS owning conversation |
| Agent / Memory-OS Collaboration Contract | 29-series contract, owner-review surfaces, Hermes agent interaction findings | design contract only | no | no | RH-37 + Host-Agent Boundary Principle | defines how Hermes reads/explains/suggests/asks/calls structured tools without transferring owner decision authority to Memory-OS |
| Right-Brain Expression Closure Contract | architecture right-brain principles, Wandering/SpeakGate evidence, Hermes origin delivery constraints | design contract only | no | no | RH-38 + SpeakGate + Hermes origin delivery | separates test-host observation from formal scheduled expression and defines expression feedback backflow |
| Left-Brain Governance Quality Contract | evidence scoring, self-evolution, feedback, working expiry, proposal follow-up, cadence evidence | design contract only | no | no | RH-39 + FeedbackSignal + SchedulerStep + OwnerAction | separates safety governance from judgment quality, feedback learning, and production cadence maturity |
| Agent-Mediated Owner Reply Tool | live owner message, visible digest context, provider platform, recorded digest binding | OwnerActionProcessor request + bounded tool result | yes, only after Hermes resolves a definite action + stable `oa_` token | no | recorded digest + OwnerActionProcessor | lets Hermes agent complete interactive owner review tasks through structured `memory_os_review_reply`; stable action tokens feed durable owner-action state |
| Owner Reply Parser | owner command text, recorded digest action-token binding | parsed action request | yes, through processor only | no | OwnerActionProcessor | applies approve/reject/feedback/allow as auditable state transitions |
| OwnerActionProcessor | parsed owner actions, target state | owner action ledger, approved crystallized records, proposal state, feedback ledger, speak ticket | yes | no | MemoryWriteSurface / Proposal / Feedback / Speak permission | durable owner choices feed candidates, proposals, RH-30 feedback, and monitor |
| Owner Review Hermes Cron Helper | preview/render commands | bounded stdout for Hermes cron | no | configured digest delivery only | Hermes cron, export eligibility | delivery success/failure and text quality feed monitor and renderer improvements |
| Cron / Session / State Mirrors | Hermes cron/session/state metadata | bounded events or mirror status | no | no | explicit run-once/apply gate | improves entrance/event completeness; never owner facts by itself |
| Mailbox | Hermes mailroom roots | mailbox status/would-send metadata | no | internal AI-agent communication only | Hermes mailroom controls | anti-loop / pause / cooldown evidence; not owner digest transport |

## Classification Overlay

This overlay makes the closure expectation easier to audit than the full matrix:

| Module | delivery_class | state_change_class | cadence_class | Current action path |
| --- | --- | --- | --- | --- |
| Heartbeat / Inner Drive | none | candidate_review | event_driven_fast | candidates must become owner-readable before approval |
| Household Digest | internal_local | monitor_only | cycle_each | feeds other modules; no owner action |
| Digest Consolidation | internal_local | candidate_review / proposal_review | daily_once + weekly_once | emitted candidates/proposals enter review queue |
| Wandering Mind | owner_origin / none | expression_feedback / speak_permission / monitor_only | disabled_until_opt_in / daily_once / cycle_each | Tier 1 test-host observation is would-send only; Tier 2 scheduled expression needs RH-38; exceptional proactive send needs speak permission |
| Speak Gate | owner_origin / none | expression_feedback / speak_permission / monitor_only | on_demand / cycle_each | every non-silent expression draft must receive a SpeakGate decision; one-shot allow only through owner action |
| DeepReflection | none | context_projection / proposal_review / speak_permission / monitor_only | cycle_each | output type determines route; TTL/minimum-signal gates live in the action path |
| Ops Gate | none | proposal_review / monitor_only | cycle_each | approval creates follow-up state, never execution |
| Proposal Queue | none | proposal_review | on_demand + cycle_each | approve/reject through OwnerActionProcessor; cycle status is monitor-only |
| Evidence Scoring | none | monitor_only | cycle_each | score evidence only; skip/no-op when unchanged |
| Self-Evolution | none | proposal_review | daily_once / cycle_each | emits proposals only; production prefers daily/weekly while test host may dry-run per cycle |
| Governance Feedback | none | feedback_ledger / monitor_only | cycle_each | feeds later reflection/scoring |
| Conversation Carryover | none | context_projection | on_demand | attribution + feedback only; runs per prefetch |
| Context Router / Low-Clue Recall | none | context_projection | on_demand | owner correction feeds feedback ledger before apply |
| MemorySources Attribution | none | feedback_ledger | on_demand | feedback evidence only; live prefetch attribution |
| RH-31 Eval Harness | internal_local | monitor_only | on_demand / monitor_poll | scorecard/finding only |
| Metadata Retention | internal_local | retention_metadata | on_demand | metadata archive/prune only; scheduling requires a separate gate |
| Owner Review Queue / Aging | none | monitor_only | owner_daily / monitor_poll | priority projection only |
| Review Digest Renderer | owner_origin | monitor_only | owner_daily | renders bounded digest, display anchors, and stable action tokens through Hermes cron |
| Agent-Mediated Review Surface | none | context_projection / monitor_only | on_demand | read-only pagination/detail/follow-up data for Hermes agent |
| Agent / Memory-OS Collaboration Contract | none | none | on_demand | design gate only; no runtime mutation |
| Right-Brain Expression Closure Contract | none | none | on_demand | design gate only; no runtime mutation; blocks formal expression claims until Tier 2 path exists |
| Left-Brain Governance Quality Contract | none | none | on_demand | design gate only; no runtime mutation; blocks intelligent-governance claims until scoring, feedback, novelty, expiry, proposal follow-up, and cadence gates exist |
| Agent-Mediated Owner Reply Tool | none | candidate_review / proposal_review / feedback_ledger / speak_permission | on_demand | Hermes resolves natural owner intent to a structured action token; requires recorded digest; processor owns mutation |
| Owner Reply Parser | none | none | on_demand | parses only; processor owns mutation |
| OwnerActionProcessor | none | candidate_review / proposal_review / feedback_ledger / speak_permission | on_demand | sole mutation path for owner actions |
| Owner Review Hermes Cron Helper | owner_origin | monitor_only | owner_daily | bounded stdout for Hermes cron |
| Cron / Session / State Mirrors | internal_local / no_agent_script | monitor_only | on_demand / monitor_poll | run-once/apply gates only |
| Mailbox | hermes_mailbox_internal | monitor_only | event_driven_fast | internal AI-agent anti-loop evidence only with Hermes cooldown/backpressure |

## Current Test-Host Cadence Snapshot

Current `10.20.3.200` implementation:

```text
runtime heartbeat timer: every 5 minutes
cognitive-loop timer: every 6 hours
cognitive-loop step order:
  heartbeat_pre
  household_digest
  digest_consolidation
  wandering_mind
  ops_gate
  evidence_scoring
  self_evolution
  governance_feedback
  deep_reflection
  heartbeat_post
  doctor_boundary_report
owner review digest: Hermes cron, daily at 09:00 test-host time
```

This snapshot is intentionally conservative for test-host coverage. It is not a
claim that every module should permanently run every 6 hours. The target
direction is:

- keep heartbeat fast and low-noise;
- keep the full cognitive loop as the integration test harness;
- add module-local idempotency / skip gates so daily and weekly modules do not
  duplicate artifacts just because the loop ran;
- keep owner-facing review delivery on Hermes cron;
- keep expensive or state-changing analysis behind explicit cadence and monitor
  thresholds.


## Closure Patterns

### Owner Review Digest Delivery

```text
review queue / aging projection
-> Review Digest Renderer
   - turns artifacts into owner-readable questions/actions/reasons/consequences
   - records display anchors such as A1/R1/F1 for readability only
   - records stable action tokens for executable owner commands
   - marks configured recurring delivery output as delivery_binding.scope=owner_home
   - never sends and never mutates target state
-> Owner Review Hermes Cron Helper
   - wraps renderer output as bounded stdout
   - records active digest binding with the configured Hermes delivery channel
   - emits empty stdout when there is nothing meaningful to deliver
   - does not call platform transport
-> Hermes cron / platform adapter
   - owns schedule, origin/platform delivery, retry/cooldown, and output files
-> Owner Reply Parser
   - maps stable action tokens back to the recorded digest binding
-> OwnerActionProcessor
   - performs the only state-changing action
```

This split is mandatory. The renderer decides what the owner can understand;
the helper provides a portable Hermes cron payload; Hermes delivers; the parser
and processor close the action loop.

### Owner Reply Ingress

```text
owner command in primary platform ("memory approve oa_<token>", "批准 oa_<token>")
-> Hermes agent interprets it as a Memory-OS approval task
   - uses stable action tokens from the visible digest
   - treats display anchors as visual labels, not preferred commands
   - asks a clarification when the requested target or action is ambiguous
-> memory_os_review_reply provider tool
   - receives structured action + stable action token
   - requires a recorded digest for the owner/platform or owner-home channel
   - does not render a fresh digest for live binding
-> Owner Reply Parser
-> OwnerActionProcessor
-> bounded assistant confirmation from the tool result
-> sync_turn control-plane skip
   - processed token command is not appended as conversation event
   - heartbeat must not promote it into working memory or candidates
```

This is the live ingress counterpart to the CLI parser. Without it, Hermes
delivers a correct digest but the owner's reply can fall through into ordinary
chat. The provider tool must execute only stable action tokens. Exact tokenized
commands such as `memory approve oa_<token>` or `approve oa_<token>` remain a
compatibility fallback, but the primary product path is the Hermes agent
resolving the owner's interactive request and calling a structured tool.
Display anchors (`A1/R1/F1`) are not approval identity. They are only UI labels
that the agent may map to a token when the visible digest context is definite.
This follows the
10.20.2.88 Sannai pattern where review apply is bound to stable candidate ids
or proposal hashes, not shifting message positions. Anything else remains
ordinary conversation or clarification.

### Memory Candidate

```text
module emits candidate
-> review queue
-> renderer shows stable proposed memory text
-> owner approve/reject
-> OwnerActionProcessor
-> crystallized record only on approve_candidate
-> MemorySources / candidate scoring / monitor backflow
```

Transcript-like candidates do not enter the approvable path directly. They
become cleanup/FYI signals until consolidation turns them into a stable memory
statement.

### Proposal

```text
module emits proposal
-> proposal_queue
-> review queue / digest
-> owner approve/reject proposal
-> approved_for_proposal state or downranked class
-> approved-proposal follow-up projection
-> explicit proposal-followups --ops-gate preview
-> optional proposal-followups --ops-gate --apply writes OpsGate report only
   - repeated apply returns duplicate/already-reviewed evidence
   - no duplicate OpsGate report for the same proposal_followup action_id
-> no execution until a separate explicit execution command
```

`approved_for_proposal` is not execution and is not yet an execution ticket. It
must surface through a follow-up projection so accepted proposals do not become
a hidden backlog, while actual execution remains a separate explicit command.
The projection itself is monitor/review evidence: it reads proposal queue
state, emits bounded follow-up items, and must keep `actual_execute=false` and
`execution_ticket_count=0`. The `--ops-gate --apply` path may add report-only
OpsGate evidence and move the follow-up state to
`ops_gate_reviewed_awaiting_explicit_execution`; it still must not create an
execution ticket or run tools.

### Expression / Proactive Send

```text
Tier 1 test-host observation:
  wandering/DR seed proposes expression
  -> would-send / blocked / silent artifact
  -> no actual send

Tier 2 scheduled right-brain expression:
  bounded memory view
  -> RightBrainExpressionEngine / Hermes agent expression adapter
  -> expression draft
  -> SpeakGate scheduled-expression decision
  -> owner-configured low-frequency Hermes origin delivery
  -> owner feedback ledger

Tier 3 exceptional proactive send:
  expression draft outside scheduled policy
  -> owner allow_speak_once
  -> one expiring permission ticket
  -> Hermes owns actual transport
```

Ordinary conversation, configured daily digest, and owner-configured scheduled
right-brain expression do not require per-message approval. Exceptional
proactive sends still require one-shot permission.

The current v0.1 test-host implementation closes Tier 1 only. It must not be
described as formal right-brain expression closure until RH-38's draft,
SpeakGate, delivery, feedback, and monitor contracts are implemented.

### Mailbox Internal Communication

```text
peer agent writes mailbox letter
-> Hermes mailbox adapter applies anti-loop controls
   final_only
   proactive_send_enabled
   auto_wake_cooldown
   reply_depth_exceeded / reply_depth_review_capped
   [NO_REPLY]
-> reply is written back through mailbox when allowed
-> mailbox status/monitor exposes cooldown/backpressure/failure
```

Mailbox is for Hermes-internal / peer-agent communication. It is not a
Memory-OS owner-review channel, not a left/right brain cognition module, and
not a shortcut around Hermes cron delivery. If a future module needs owner
review, it must use the owner review path above, not mailbox.

### Context / Recall

```text
ingress decision
-> context router / low-clue recall
-> projected bounded context
-> MemorySources attribution
-> owner feedback ledger
-> future bounded apply gate may adjust routing
```

### Analysis / Monitor

```text
module writes analysis/report
-> monitor/eval evidence
-> roadmap gate or FYI digest
-> no owner action unless promoted into a candidate/proposal/feedback item
```

## Cadence Transitions

Cadence changes are state changes in the scheduler contract, even when the
module code is unchanged.

| Transition | Required gate |
| --- | --- |
| `disabled_until_opt_in -> owner_daily` | explicit owner/operator config, Hermes cron gate, bounded renderer output, monitor fields, rollback by disabling the cron job/config |
| `disabled_until_opt_in -> cycle_each` | test-host preset or explicit design review; production default remains disabled unless owner approves |
| `cycle_each -> daily_once` | module-local idempotent skip/report, monitor showing skipped vs generated counts |
| `cycle_each -> weekly_once` | week-keyed idempotency, monitor showing weekly artifact count and no duplicate generation |
| `monitor_poll -> scheduled apply` | separate apply gate; monitor-only status is not enough |
| `on_demand -> recurring` | schedule, delivery class, state-change class, monitor field, rollback, and owner burden impact must be declared first |

## Production Cadence Target Snapshot

The current test-host loop is intentionally broad. A mature production profile
should converge toward this shape:

| Module group | Production cadence target |
| --- | --- |
| Heartbeat / Inner Drive | fast event-driven heartbeat, no-op audit suppressed, state freshness monitored |
| Household Digest | daily or low-frequency cycle, skipped when no meaningful new event volume exists |
| Digest Consolidation | daily digest once per day and weekly consolidation once per week |
| Wandering Mind / Expression | owner-configured low-frequency Hermes origin delivery or no-send/would-send observation; no uncontrolled frequent sending |
| DeepReflection | bounded cycle with TTL and minimum new-signal gate; no repeated identical injection/report churn |
| Ops / Evidence / Governance | cycle-based in test host, but skip/no-op when inputs have not changed; proposal approval remains owner-controlled |
| Self-Evolution | daily or weekly proposal review cadence, not repeated proposal spam every cycle |
| Owner Review Digest | owner daily through Hermes cron; one digest per owner/window |
| Eval / Retention / Mirrors | on-demand or explicitly scheduled local/no-agent jobs with monitor evidence |

Production cadence is not implemented merely by changing timer intervals. Each
module needs idempotency and monitor evidence for generated/skipped/errored
states.

## Closure Matrix Violations

Use this severity guide during design review, code review, and release review:

| Violation | Severity | Required response |
| --- | --- | --- |
| New module/RH has no delivery/state/cadence classification | P1 | Block implementation or merge until RH-36 is updated. |
| Module sends through platform transport directly instead of Hermes | P0/P1 | Stop live rollout; redesign as Hermes integration. |
| Owner-actionable artifact has no owner-visible review/action path | P1 | Block promotion beyond monitor-only status. |
| Frontend mutates candidate/proposal/feedback/speak/crystallized state directly | P0/P1 | Route through OwnerActionProcessor and add regression evidence. |
| Cadence changes without generated/skipped/error monitor fields | P1 | Add monitor/evidence before observation claims. |
| Wrong class but no live boundary violation | P2 | Correct docs/tests before next related feature. |

Enforcement is design-review and staged-content review, backed by the
29-series integration contract and the RH-36b local check below.

## RH-36b Closure Matrix Enforcement

The local enforcement check is:

```text
scripts/memory_os_closure_matrix_check.py
```

What it checks:

- all code-defined live modules from `memory_os.cli._module_definitions()` map
  to a row in the RH-36 Classification Overlay;
- non-live but contract-critical surfaces such as MemorySources, RH-31 eval,
  OwnerActionProcessor, review renderer, review surface, owner reply tool, and
  Hermes cron helper also have rows;
- active `P1-*` roadmap items and `P2-F` map to Classification Overlay rows
  or provide a `not_applicable` reason;
- `delivery_class`, `state_change_class`, and `cadence_class` contain known
  machine-readable class values, not freeform prose;
- failures return a non-zero exit code.

Current live reconciliation:

```text
10.20.3.200 modules status:
  live_module_count=16
  modules:
    cron_mirror
    session_mirror
    state_source_mirror
    shadow_journal
    deep_reflection
    governance_feedback
    digest_consolidation
    inner_drive
    mailbox
    household_digest
    wandering_mind
    evidence_scoring
    ops_gate
    proposal_queue
    self_evolution
    speak_gate

closure matrix check:
  status=ok
  live_module_count=16
  matrix_module_count=27
  active_work_item_count=18
  active_work_mapping_count=18
  finding_count=0
```

Reference prototype recheck:

```text
10.20.2.88 Hermes main / Sannai:
  owner-facing scheduled reports use Hermes cron delivery such as origin;
  Sannai owner review reports use no-agent direct stdout only for report-style
  output, not interactive Memory-OS state mutation;
  mailbox adapter contains final_only, proactive_send_enabled,
  auto_wake_cooldown, reply_depth controls, and [NO_REPLY] semantics;
  mailbox remains an internal AI-agent mailroom, not the owner approval path.
```

Enforcement rule:

- any new module/RH that changes module behavior, owner review, scheduling,
  delivery, context projection, persistence, feedback, or monitor evidence must
  pass this check before it is called implemented;
- if the check fails because a new module does not fit an existing class, RH-36
  must be updated first, then the check and tests must pass.

## Active Work Closure Mapping

RH-36c adds a second enforcement layer: active roadmap work cannot live only in
conversation history or a planning paragraph. Every active `P1-*` item and the
public productization item `P2-F` must map to one or more rows in the
Classification Overlay, or explicitly state why RH-36 does not apply. This is a
development gate, not a progress claim.

| Work item | Closure rows | not_applicable_reason | Validation note |
| --- | --- | --- | --- |
| P1-B | RH-31 Eval Harness | | Eval failures are measurement signals until mapped to live evidence or owner-approved redacted fixtures. |
| P1-C | DeepReflection; Conversation Carryover; Context Router / Low-Clue Recall | | DR/carryover may affect context projection, proposal review, or speak permission depending on output type. |
| P1-D | Governance Feedback; Self-Evolution | | LLM/governance analysis remains feedback/proposal evidence, not live tuning. |
| P1-E | Wandering Mind; Speak Gate | | Would-send artifacts and one-shot permission remain governed by speak gate closure. |
| P1-F | Heartbeat / Inner Drive; Metadata Retention | | Audit density and working expiry are runtime/write-surface observation and metadata-retention concerns. |
| P1-G | Context Router / Low-Clue Recall; MemorySources Attribution | | Live Telegram candidate-quality findings must close through context projection plus attribution evidence. |
| P1-H | MemorySources Attribution | | Feedback collection volume remains feedback-ledger evidence until a bounded apply gate exists. |
| P1-I | Cron / Session / State Mirrors | | Hook coverage detection is monitor-only evidence over entrance/mirror state. |
| P1-J | Cron / Session / State Mirrors; Context Router / Low-Clue Recall | | Pending session coverage must correlate with recall behavior before any apply path. |
| P1-K | not_applicable | Module status/doctor truthfulness is a CLI presentation parity task over existing rows; it adds no new module or closure class. | If it changes module behavior, add the affected row before implementation. |
| P1-L | Household Digest; Wandering Mind; Evidence Scoring; Self-Evolution; Governance Feedback; DeepReflection | | Per-module artifact summaries expose monitor-only outputs from cognitive-loop modules. |
| P1-M | Review Digest Renderer; Agent-Mediated Review Surface; Agent-Mediated Owner Reply Tool; OwnerActionProcessor; Owner Review Hermes Cron Helper | | Owner review must stay Hermes-mediated and processor-mutated. |
| P1-N | Agent / Memory-OS Collaboration Contract | | Contract-only gate for Hermes agent and Memory-OS collaboration. |
| P1-O | Agent-Mediated Owner Reply Tool; Owner Reply Parser; OwnerActionProcessor | | Fallback and gateway-hook closure protects the structured owner-action path. |
| P1-P | Heartbeat / Inner Drive; Proposal Queue; Wandering Mind; Owner Review Queue / Aging | | Producers and review projections must carry bounded timestamps for aging. |
| P1-Q | Ops Gate; Proposal Queue; Agent-Mediated Review Surface; OwnerActionProcessor | | Approved proposal follow-up stays visible and report-only until explicit execution apply exists. |
| P1-R | Wandering Mind; Speak Gate; DeepReflection; Governance Feedback; Self-Evolution; Right-Brain Expression Closure Contract | | Formal right-brain expression is not closed by test-host would-send observation; RH-38 must define draft, gate, delivery, feedback, and proposal backflow before runtime expression delivery. |
| P1-S | Evidence Scoring; Self-Evolution; Governance Feedback; Proposal Queue; Ops Gate; Heartbeat / Inner Drive; Left-Brain Governance Quality Contract | | Left-brain safety governance is closed, but judgment quality, feedback learning, expired-working hygiene, proposal novelty, approved-proposal execution decision, and production cadence are not mature. |
| P2-F | Review Digest Renderer; Agent-Mediated Review Surface; Agent-Mediated Owner Reply Tool; OwnerActionProcessor; Owner Review Hermes Cron Helper; Agent / Memory-OS Collaboration Contract | | Public material must explain the owner-governance subsystem without expanding Memory-OS transport or execution ownership. |

The local check validates this table against
`docs/system-modularization/32-active-roadmap-and-gates.md`. Missing mappings,
stale mappings, unknown closure rows, and `not_applicable` rows without a reason
are P1 contract gaps.

## Stop Signals

- A module produces action-worthy artifacts but has no owner-visible review
  surface or monitor field.
- A frontend mutates candidate/proposal/feedback/speak/crystallized state
  without OwnerActionProcessor.
- A module sends through platform transport directly instead of Hermes.
- A transcript/event excerpt is presented as approvable long-term memory.
- A proposal approval executes work.
- Feedback immediately changes live routing without a bounded apply gate.
- Monitor cannot distinguish generated, shown, acted, skipped, stale, and error
  states for owner-facing artifacts.
