# 40 - Memory-OS Unified Control Plane

Date: 2026-05-26

Status: active entrypoint.

Purpose: provide one readable control document for Memory-OS current truth,
hard gates, active priorities, and closure claims. This document exists because
the project now has many correct but scattered contracts. The evidence ledger
remains `07-validation-report-10.20.3.200.md`; this document is the operating
map.

## Document Authority

Use this hierarchy:

1. `40-memory-os-unified-control-plane.md`
   - human entrypoint;
   - current status summary;
   - active priority order;
   - which hard gate applies to each workstream.
2. `07-validation-report-10.20.3.200.md`
   - append-only evidence ledger;
   - live / monitor / deployment / smoke evidence;
   - not a roadmap.
3. `29-memory-os-module-integration-contract.md`
   - top-level module integration contract;
   - owns cross-module boundaries, bug handling, feedback, scheduler,
     monitor, owner action, and host-agent boundary principles.
4. `36-module-closure-matrix.md`
   - closure matrix and local enforcement gate;
   - every live module, contract-critical surface, and active work item must
     map here.
5. `37-agent-memoryos-collaboration-contract.md`
   - Hermes agent and Memory-OS collaboration boundary;
   - owner-facing interaction belongs to Hermes agent, Memory-OS provides
     bounded tools/state/evidence.
6. `38-right-brain-expression-closure-contract.md`
   - formal right-brain expression gate;
   - prevents treating `would-send/no-send` observation as full expression
     closure.
7. `39-left-brain-governance-quality-contract.md`
   - left-brain governance quality gate;
   - prevents treating safety governance as intelligent judgment maturity.
8. `41-operating-closure-implementation-blueprint.md`
   - implementation-level blueprint for the next operating-closure stage;
   - names module seams, key code files, tests, monitor fields, live gates,
     stop signals, and promotion criteria.
9. `32-active-roadmap-and-gates.md`
   - detailed backlog and long-form gate notes;
   - subordinate to this unified control plane for priority reading order.

If these documents conflict, resolve in this order:

```text
07 evidence -> 29/36/37/38/39 contracts -> 40 control plane -> 41 blueprint -> 32 details
```

Then update the stale document in the same change.

## Current Truth

Memory-OS has four layers. Only the first is currently closed.

| Layer | Current state | Claim allowed today |
| --- | --- | --- |
| Layer 1 - Safety governance | Closed on test host | Hard boundaries, owner action, audit, monitor, and Hermes transport boundary are working. |
| Layer 2 - Intelligent judgment | Not mature | EvidenceScoring and SelfEvolution are safe, but scoring quality and proposal novelty are not mature. |
| Layer 3 - Right-brain expression operations | Not closed | Test-host would-send observation exists; formal scheduled expression and expression feedback backflow do not. |
| Layer 4 - Hermes agent collaboration | Partially corrected | Hermes agent owns interaction; Memory-OS still needs stronger collaboration surfaces and fallback deprecation. |

Allowed public/internal claims:

- Memory-OS v0.1 has a real safety governance shell.
- Owner action through OwnerActionProcessor works.
- MemorySources attribution and monitor boundaries are clean.
- Approved proposals are visible and do not execute.
- Right-brain and left-brain quality systems are design-gated, not mature.

Forbidden claims:

- full right-brain expression closure;
- intelligent evidence scoring;
- feedback learning loop;
- production cadence maturity;
- proposal-to-execution operations;
- public/product-ready Memory-OS.

## Hard Gates

### Gate 1 - Dynamic Closure Preflight

Before non-trivial work, answer:

```yaml
source_of_truth:
finding_type:
owning_seam:
reverse_scope:
equivalent_contract_or_project_contract:
evidence_loop:
monitor_or_validation_fields:
promotion_signal:
stop_or_rollback_signal:
external_review:
```

If a change touches live behavior, installer/deploy, scheduler, owner review,
retrieval/routing, feedback, monitor, eval, or human interaction, this preflight
is mandatory.

### Gate 2 - Host / Prototype Ownership

Before implementing scheduling, transport, delivery, conversation, approval,
execution, or platform interaction, check:

```text
Does Hermes already own this?
Does 10.20.2.88 / Sannai already solve this pattern?
Is Memory-OS integrating with that owner, or reimplementing it?
```

Default boundary:

```text
Hermes owns conversation, cron, origin delivery, platform transport, and user
interaction.
Memory-OS owns bounded memory state, review surfaces, action tokens,
OwnerActionProcessor, audit, monitor, and proposal/report evidence.
```

### Gate 3 - RH-36 Closure Matrix

Run before claiming implementation or closure:

```powershell
python scripts\memory_os_closure_matrix_check.py --format summary
```

The expected current baseline is:

```text
status=ok
live_module_count=16
matrix_module_count=28
active_work_item_count=20
active_work_mapping_count=20
finding_count=0
```

Any new `P1-*`, `P2-F`, module, scheduler, review surface, feedback surface,
or contract-critical tool must have an RH-36 mapping.

### Gate 4 - Evidence Level

Do not collapse evidence types:

| Claim | Minimum evidence |
| --- | --- |
| local behavior | unit/integration test |
| installed behavior | installer or CLI smoke |
| Telegram/gateway behavior | real or realistic live smoke |
| monitor behavior | monitor field plus fixture or real run |
| architecture claim | contract + mapping + evidence |
| production readiness | repeated live evidence plus promotion/stop signals |

Every live/deployed finding must close with live or realistic integration
evidence, not local-only tests.

### Gate 5 - External Review

External review is required before:

- enabling scheduled right-brain expression delivery;
- replacing hash scoring as live scoring input;
- any execution/apply capability after proposal approval;
- LLM judge bounded-live mode;
- owner-boundary changes;
- public product claims.

External review is optional for:

- read-only monitor fields;
- documentation reconciliation;
- local fixture repairs;
- no-behavior refactors with adequate tests.

## 10.20.2.88 Prototype Reference, Not Blueprint

Every runtime change in P1-R/P1-S must be checked against the live Hermes
prototype before implementation. The prototype is not a design blueprint to
copy. It is evidence for:

- which layer already owns scheduling, delivery, profiles, channels, and
  mailbox backpressure;
- which operating patterns have survived real use;
- which failure classes Memory-OS should monitor before it claims maturity.

Memory-OS must synthesize a better module system from this evidence, not port
the prototype script chain one-for-one.

Read-only prototype evidence from `10.20.2.88` on 2026-05-26:

| Prototype capability | Observed owner | Memory-OS implication |
| --- | --- | --- |
| Main Hermes and Sannai run as separate `HERMES_HOME` / profile gateways. | Hermes profile system | Memory-OS must not invent profile isolation. It should stay profile-local and expose bounded state/tools per profile. |
| Owner-facing reports and right-brain expression use Hermes cron with `deliver=origin`. | Hermes cron / origin delivery | Memory-OS provides bounded stdout/drafts; Hermes owns schedule, delivery, retry, platform channel, and cooldown. |
| Background maintenance uses `deliver=local` or no-agent scripts. | Hermes cron / local jobs | Memory-OS module maintenance should be local/no-agent where possible, not chatty owner reports. |
| Sannai free-time and afterglow jobs are origin-delivered expression tasks. | Hermes agent / Sannai profile | Formal right-brain expression should be a low-frequency Hermes-agent expression path, not deterministic Memory-OS report text. |
| Sannai random heartbeat schedules one-shot origin jobs and allows `[SILENT]`. | Profile-local scheduler helper + Hermes cron | Memory-OS right-brain expression needs silence as a first-class outcome and must avoid per-message owner approval for normal scheduled expression. |
| Self-Evolution daily pipeline runs ordered steps: collect signals, cleanup/verify proposals, maturation, unmatched review, candidate preview, speak gate, apply-ready, digest, contract check. | Self-evolution-governor scripts + Hermes cron | Memory-OS should model left-brain production as staged module pipelines with generated/skipped/error counts, not one permanent 6h all-modules loop. |
| Self-Evolution contract checker is read-only and validates proposal queue, approved-pending-execution, delivery/silent reason, duplicate scheduler surface, and hard boundaries. | Prototype contract checker | Memory-OS monitor should classify pipeline consistency separately from business quality and expose approved follow-up gaps as WARN, not execute work. |
| Proposal records carry `maturity_score`, evidence counts, observation days, trigger rule, approval block, execution block, timestamps, and verification fields. | Prototype proposal queue | Memory-OS P1-S maturity dimensions are correctly report-only today; promotion requires a separate apply gate and proposal lifecycle fields. |
| mailbox backpressure is handled by Hermes mailbox/cooldown rules. | Hermes mailbox | Memory-OS must only read bounded mailbox/backpressure state; it must not reimplement mailbox transport. |

Design synthesis for Memory-OS:

1. **Host layer**: Hermes owns conversation, cron, origin/local delivery,
   profile isolation, mailbox cooldown, platform retry, and user-facing
   recovery. Memory-OS must not reimplement these.
2. **Memory substrate**: Heartbeat / Inner Drive / SessionMirror / StateMirror
   keep bounded event, working, candidate, index, and mirror state complete.
3. **Context projection**: ContextRouter, Low-Clue Recall, Carryover,
   DeepReflection injection, and MemorySources decide what the agent sees and
   why, with attribution and feedback.
4. **Left-brain governance**: EvidenceScoring, Digest Consolidation,
   ProposalQueue, SelfEvolution, GovernanceFeedback, and OpsGate produce
   evidence, proposals, and report-only follow-up. They must not execute.
5. **Right-brain expression**: Household Digest, DeepReflection seeds,
   Wandering/ExpressionDraft, and SpeakGate produce non-task expression or
   `[SILENT]`, then Hermes may deliver only under owner-configured cadence.
6. **Owner governance**: ReviewQueue, Aging, Renderer, ReviewSurface,
   ReviewReplyTool, OwnerActionProcessor, and the cron helper make human
   decisions visible, actionable, idempotent, and auditable.
7. **Evidence/retention layer**: RH-31 eval, monitor, retention, and RH-36
   matrix prove what is working, what is only observed, and what is blocked.

Near-term work order after synthesis:

1. **P1-R.3/P1-R.4**: create Memory-OS `ExpressionDraft` and Hermes-agent
   expression adapter. This is not Sannai free-time copied into Memory-OS; it
   is a generic bounded right-brain draft interface that any profile can use.
2. **P1-R.5/P1-R.6**: route every non-silent draft through SpeakGate and record
   expression feedback. This closes the current Wandering/SpeakGate gap.
3. **P1-S.5/P1-S.6**: build a Memory-OS read-only pipeline checker and proposal
   lifecycle fields. This borrows the prototype checker principle, not its
   script sequence.
4. **P1-Q**: move approved proposals into explicit follow-up / OpsGate
   visibility without creating execution tickets.
5. **P1-T**: split production cadence by module class using Hermes cron as the
   scheduler owner and Memory-OS counters as maturity evidence.

Forbidden shortcut:

```text
Do not implement a Memory-OS-owned scheduler, transport, platform channel,
mailbox, or conversation agent to close any of the above gaps.
```

## Active Priority Order

### P0 - Commit Current Governance Baseline

Scope:

- RH-36 closure matrix enforcement and active mapping;
- RH-37 agent collaboration contract;
- RH-38 right-brain expression contract;
- RH-39 left-brain governance quality contract;
- 29 / 32 / 36 / 40 / 41 alignment;
- 07 evidence updates;
- closure matrix check script and tests.

Gate:

```powershell
git status --short
python scripts\memory_os_closure_matrix_check.py --format summary
python -m pytest tests\scripts\test_memory_os_closure_matrix_check.py -q
git diff --check
```

Do not include `INDEPENDENT_MAINLINE_REVIEW_2026-05-26.md`.

### P1-R - RH-38 Right-Brain Expression Closure

Owning docs:

- `38-right-brain-expression-closure-contract.md`
- `36-module-closure-matrix.md`
- `29-memory-os-module-integration-contract.md`

Current truth:

- safe would-send observation exists;
- formal expression engine does not exist;
- Wandering output is deterministic;
- P1-R slice 1 is deployed on `10.20.3.200`: new cognitive-loop Wandering
  output creates bounded ExpressionDraft records and records SpeakGate
  decisions; monitor distinguishes historical missing counts from
  latest-cycle closure counts;
- P1-R slice 2 is deployed on `10.20.3.200`: owner review resolves Wandering
  `payload_ref` values into bounded expression previews so speak review items
  can be judged by content;
- last recorded 07 monitor evidence reports `speak_expression_preview_missing_count=0` and
  PASS `right_brain_review_speak_preview_visible`;
- expression feedback ledger and GovernanceFeedback summary backflow are
  implemented; policy/prompt adaptation is not.

Required before runtime:

- RightBrainExpressionEngine / Hermes-agent expression adapter contract;
- every non-silent draft passes SpeakGate;
- deploy owner-visible bounded expression content and monitor preview coverage;
- expression feedback labels exist;
- GovernanceFeedback/SelfEvolution consume outcomes only as proposal evidence;
- monitor fields exist.

### P1-S - RH-39 Left-Brain Governance Quality

Owning docs:

- `39-left-brain-governance-quality-contract.md`
- `36-module-closure-matrix.md`
- `29-memory-os-module-integration-contract.md`

Current truth:

- safety governance is implemented;
- evidence scoring still uses legacy hash scores for live consumers, but P1-S
  slice 3 is deployed as a report-only feature-score comparator and P1-S
  slice 4 is deployed as a 10.20.2.88 prototype-aligned maturity dimension
  report;
- deployed P1-S slice 2 adds a SelfEvolution duplicate unresolved proposal
  gate with novelty skip counters; last recorded 07 monitor evidence reports
  `novelty_skipped_count=1` and `duplicate_unresolved_proposal_count=1`;
- feedback backflow is not closed;
- deployed P1-S slice 1 filters expired working out of EvidenceScoring and
  adds monitor visibility for expired scoring contamination;
- last recorded 07 monitor evidence reports `expired_used_in_scoring_count=0` and PASS
  `left_brain_expired_working_not_scored`;
- last recorded 07 monitor evidence reports `feature_score_count=487`,
  `hash_score_legacy_count=487`, `comparison_count=487`,
  `feature_score_live_applied=false`, and PASS
  `left_brain_feature_scoring_report_only_ok`;
- last recorded 07 monitor evidence reports P1-S.4 `prototype_aligned_score_count=487`,
  `maturity_dimension_count=9`, `maturity_live_applied=false`, and PASS
  `left_brain_maturity_scoring_report_only_ok`;
- latest live evidence reports `left_brain_pipeline_check.status=warn`,
  `finding_count=1`, `feature_scoring.report_only=true`,
  `execution_ticket_count=0`, and `actual_execute=false`; the WARN finding is
  `duplicate_unresolved_proposals`.
- DeepReflection expired-working handling is still not fixed;
- production cadence is not mature.

Implementation order:

1. expired working filter / monitor;
2. SelfEvolution novelty and idempotency gate;
3. feature-based EvidenceScoring v2 report-only;
4. prototype-aligned maturity dimensions report-only;
5. left-brain pipeline checker;
6. proposal lifecycle / approved-follow-up state;
7. feedback backflow report-only/proposal-only;
8. approved-proposal execution-decision state design;
9. production cadence split;
10. ContextRouter / Ingress de-duplication with parity tests.

### P1-O - Owner Review Fallback / Gateway Boundary

Owning docs:

- `37-agent-memoryos-collaboration-contract.md`
- `29-memory-os-module-integration-contract.md`

Current truth:

- structured `memory_os_review_reply` path exists;
- fallback must remain visible and deprecated by evidence;
- gateway hook is safety-only, not normal approval path.

Gate:

- model-facing schema must not expose legacy `reply`;
- fallback use must be counted;
- gateway safety skips must not become normal user-facing errors;
- Telegram owner-token smoke required for live claim.

### P1-Q - Approved Proposal Follow-Up

Owning docs:

- `34-owner-review-digest-and-action-workflow.md`
- `36-module-closure-matrix.md`
- `39-left-brain-governance-quality-contract.md`

Current truth:

- `approved_for_proposal` is visible;
- OpsGate report-only follow-up exists;
- execution tickets remain zero;
- final owner execution decision state is not implemented.

Allowed next step:

```text
approved_for_proposal
-> ops_gate_reviewed_awaiting_explicit_execution
-> awaiting_owner_execution_decision
-> applied / rejected / snoozed
```

No execution capability without a separate owner/operator apply gate and
external review.

### P1-P - Timestamp / Aging Data Quality

Owning docs:

- `34-owner-review-digest-and-action-workflow.md`
- `39-left-brain-governance-quality-contract.md`

Current truth:

- new review items now have timestamp coverage;
- old unknown timestamp issues were a real aging distortion;
- monitor must keep `unknown_timestamp_count` and coverage ratio visible.

### P1-J - SessionMirror Entrance Completeness

Owning docs:

- `36-module-closure-matrix.md`
- `28-low-clue-recall-router-design.md`

Current truth:

- pending sessions remain;
- dry-run shows would-generate bounded events;
- no apply until pending sessions correlate with real recall omissions and
  owner approves apply.

### Observation Queue

These remain observation or measurement, not immediate feature work:

- P1-C DeepReflection / carryover source-class and leakage observation;
- RH-31 eval findings;
- audit density and retention;
- MemorySources feedback volume;
- Hermes upgrade compatibility.

## Stop Signals

Stop and redesign if any of these happen:

- `actual_send=true` outside owner-configured Hermes delivery;
- `actual_execute=true` before explicit execution apply gate;
- raw body appears in public/owner review/monitor surfaces;
- Memory-OS implements platform transport or cron semantics instead of Hermes;
- feedback directly mutates prompt/routing/cadence/scoring;
- right-brain text becomes task/proposal/agenda language;
- scoring begins driving live behavior before report-only comparison;
- SelfEvolution creates repeated unresolved proposals;
- expired working dominates scoring/reflection;
- 36 closure check fails.

## Work Rule

No new feature should start from conversation memory alone.

Before implementation:

1. identify the active row in this document;
2. confirm owning contract;
3. confirm RH-36 mapping;
4. define evidence loop and monitor fields;
5. implement the narrowest slice;
6. update 07 with evidence;
7. update this document if status or priority changed.
