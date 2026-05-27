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
| Layer 3 - Right-brain expression operations | Runtime baseline, not mature | Test-host Hermes-agent expression, outcome ledger, expression-policy apply, and first outcome-linked feedback path work; reaction volume and cadence/prompt evaluation are not mature. |
| Layer 4 - Hermes agent collaboration | Partially corrected | Hermes agent owns interaction; Memory-OS still needs stronger collaboration surfaces and fallback deprecation. |

Allowed public/internal claims:

- Memory-OS v0.1 has a real safety governance shell.
- Owner action through OwnerActionProcessor works.
- MemorySources attribution and monitor boundaries are clean.
- Approved proposals are visible and do not execute.
- Right-brain and left-brain quality systems have runtime baselines, not mature
  product closure.

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

- enabling or broadening scheduled right-brain expression delivery beyond the
  current test-host owner-configured path;
- replacing hash scoring as live scoring input;
- any new execution/apply capability after proposal approval beyond the
  current bounded `expression_policy` apply path;
- LLM judge bounded-live mode;
- owner-boundary changes;
- public product claims.

External review is optional for:

- read-only monitor fields;
- documentation reconciliation;
- local fixture repairs;
- no-behavior refactors with adequate tests.

### Gate 6 - LLM Capability Surface Registry

LLM use is not a generic Memory-OS module. Each surface must declare the host
agent/runtime owner, the Memory-OS role, the allowed mode, and the bounded live
scope before implementation.

| Surface | Owner | Memory-OS role | Current mode | May affect live behavior? | Next gate |
| --- | --- | --- | --- | --- | --- |
| Right-brain expression | Hermes agent / cron `deliver=origin` | Bounded context, expression policy, request/outcome evidence, monitor | `bounded-live` for wording or `[SILENT]` only | Yes, only owner-configured low-frequency expression text through Hermes | P1-R outcome ledger + feedback evidence |
| Low-clue recall judge | Hermes configured judge adapter | Bounded candidate metadata and report evidence | `report-only` | No | bounded-live only inside `ambiguous_recall` ranking after real evidence |
| DeepReflection reflective adapter | Future Hermes agent adapter if approved | Bounded reflection substrate, report/proposal evidence | not enabled; future `report-only` or `proposal-only` | No | contract + monitor before any LLM reflection runtime |
| Left-brain semantic advisor | Future Hermes agent/governance adapter if approved | Explain feature scores, risks, and proposal suggestions | not enabled; future `report-only` or `proposal-only` | No | cannot replace feature scoring without explicit apply gate |

Mode rules:

- `report-only`: evidence only; no state mutation.
- `proposal-only`: may create an owner-reviewed proposal; no apply.
- `bounded-live`: affects only the declared bounded surface. It cannot expand
  into route override, send/transport ownership, execution, identity write,
  crystallized write, or hidden prompt/policy mutation.

Any new module/RH that uses an LLM must add a RH-36 mapping row and fill the
29-series `llm` block. Missing declaration is a P1 contract gap.

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

Near-term work order after synthesis and the 2026-05-27 runtime
outcome-feedback baseline:

1. **P1-S feedback backflow quality**: linked-outcome quality gating is now
   live for expression feedback. Remaining P1-S work should focus on feedback
   proposal usefulness and maturity, not direct prompt/policy/cadence mutation.
2. **P1-T cadence split is no longer a WARN source**: cadence report is live,
   left-brain/context modules have module-local skip gates, and the remaining
   right-brain expression harness findings (`wandering_mind`,
   `expression_draft`, `speak_gate`) were closed through outcome/reaction-aware
   skip evidence rather than timer guessing. Further cadence work must be
   chosen from refreshed generated/skipped/error/duplicate counters.
3. **P1-Q extension only for concrete proposal kinds**: extend explicit apply
   only when a proposal kind has owner approval, OpsGate report-only evidence,
   bounded runtime target, rollback, and monitor fields.
4. **P1-P timestamp / aging quality**: keep cleaning unknown timestamps and
   aging projections so review queue maturity is not simulated by conservative
   downgrade.
5. **LLM capability surfaces**: keep right-brain expression on the Hermes-agent
   adapter path; keep recall judge / DeepReflection / left-brain semantic
   advisor report-only or proposal-only until their own gates pass.

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
- low-frequency Hermes-agent expression adapter is deployed on the test host;
- Wandering output remains deterministic inside Memory-OS, but formal
  expression wording/silence judgment can now be delegated to Hermes agent
  through the adapter;
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
  implemented; SelfEvolution can create expression-policy proposals from
  expression feedback; owner-approved `expression_policy` proposals can pass
  OpsGate report-only review and explicit apply into
  `right_brain_expression_adapter/policy.json`; automatic prompt/cadence
  mutation remains forbidden.
- right-brain expression outcome ledger is deployed on `10.20.3.200`: final
  Hermes-agent `## Response` text or `[SILENT]` is extracted from Hermes cron
  output and recorded as bounded outcome evidence with policy version and hard
  boundary fields. Latest monitor reports `right_brain_adapter_outcome_count=2`
  and PASS `right_brain_expression_outcome_recorded`.
- outcome-linked expression feedback is deployed on `10.20.3.200`: owner
  feedback can target `expression:<outcome_id>` or `expression:latest_outcome`;
  the ledger stores bounded `outcome_id`, `request_id`, and `policy_version`
  fields without raw expression body, and monitor reports
  `linked_outcome_count=1`, `outcome_feedback_count=1`,
  `latest_outcome_feedback_count=1`, and PASS
  `right_brain_expression_feedback_linked`.
- the live backflow smoke reached EvidenceScoring and SelfEvolution:
  `expression_feedback_subject_count=3`; SelfEvolution identified
  `proposal_class=expression_policy:too_mechanical` and correctly skipped a
  duplicate same-day same-signal proposal with `actual_execute=false`.

Still required before claiming mature product closure:

- owner/user feedback volume on real expression output;
- production cadence tuning separate from the test-host harness.

### P1-S - RH-39 Left-Brain Governance Quality

Owning docs:

- `39-left-brain-governance-quality-contract.md`
- `36-module-closure-matrix.md`
- `29-memory-os-module-integration-contract.md`

Current truth:

- safety governance is implemented;
- EvidenceScoring v2 is now the primary scoring path: live status reports
  `score_mode=feature_maturity_v2`, `feature_score_mode=primary`,
  `hash_score_legacy_count=0`, and legacy hash only as comparison evidence;
- deployed P1-S slice 2 adds a SelfEvolution duplicate unresolved proposal
  gate with novelty skip counters; latest monitor evidence reports
  `novelty_skipped_count=11` and `duplicate_unresolved_proposal_count=11`;
- expression feedback can enter EvidenceScoring/SelfEvolution as proposal
  evidence; direct policy/prompt/cadence mutation remains blocked;
- P1-S feedback-quality gate is live: expression feedback now carries bounded
  `outcome_id`/`request_id`/`policy_version` context into EvidenceScoring, and
  SelfEvolution requires at least one linked outcome before creating a new
  owner-facing `expression_policy` proposal. The latest targeted smoke reports
  `expression_feedback_subject_count=3`, linked `1`, unlinked `2`,
  `proposal_created=false` due same-day same-signal cadence, and
  `actual_execute=false`.
- deployed P1-S slice 1 filters expired working out of EvidenceScoring and
  adds monitor visibility for expired scoring contamination;
- last recorded 07 monitor evidence reports `expired_used_in_scoring_count=0` and PASS
  `left_brain_expired_working_not_scored`;
- latest 10.20.3.200 monitor evidence reports `feature_score_count=508`,
  `hash_score_legacy_count=0`, `legacy_hash_comparison_count=508`,
  and PASS `left_brain_feature_scoring_primary_ok`;
- latest monitor evidence reports `prototype_aligned_score_count=508`,
  `maturity_dimension_count=9`, `maturity_live_applied=false`, and PASS
  `left_brain_maturity_scoring_primary_ok`;
- latest live evidence reports `left_brain_pipeline_check.status=ok`,
  `finding_count=0`, `feature_scoring.report_only=true`,
  `execution_ticket_count=0`, and `actual_execute=false`;
- P1-S duplicate-maturity cleanup is live: active owner-actionable duplicate
  groups are `0`, follow-up duplicate groups are `0`, and the remaining
  `legacy_template_duplicate_group_count=1` is historical template noise rather
  than a current owner-agenda blocker;
- P1-S proposal-usefulness maturity check is live: pipeline check now exposes
  `proposal_quality_missing_count`,
  `expression_policy_quality_ready_count`,
  `expression_policy_quality_blocked_count`, and
  `expression_policy_unlinked_quality_count`; latest live monitor reports all
  four counts at `0` with `actual_execute=false`.
- P1-S DeepReflection proposal quality repair is live: optional
  `deep_reflection_self_evolution` proposals now include stable
  `proposal_class`, `dedupe_key`, concrete owner-readable body sections, and
  report-only `proposal_quality`; a bounded live metadata repair fixed 3
  historical DeepReflection proposals, closed 1 duplicate as
  `pressure_blocked`, and removed the
  `left_brain_proposal_quality_metadata_missing` monitor WARN.
- P1-S DeepReflection expired-working hygiene is deployed: latest
  `10.20.3.200` dry-run reports `active_working_input_count=8`,
  `expired_working_skipped_count=158`,
  `expired_working_used_in_analysis_count=0`, and monitor PASS
  `deep_reflection_expired_working_not_used`;
- P1-T cadence report is deployed on `10.20.3.200`; live monitor reports
  `module_cadence_report_visible`, `module_count=18`, `cron_job_count=2`,
  `integration_harness_member_count=11`, `split_recommended_count=11`,
  `expected_hermes_cron_missing_count=0`, `finding_count=0`,
  `generated_count=897`, `skipped_count=63`, `error_count=15`,
  `duplicate_count=22`, and `counter_coverage_count=18`;
- production cadence is not fully mature, but the previous
  `module_cadence_split_pending` WARN is closed. Remaining cadence work should
  be selected from refreshed counters and real owner/outcome volume, not from
  timer tables.
- P1-T first split is live: SelfEvolution-local cadence gating now makes a
  same-day same-signal rerun return monitor-visible `cadence_skipped=true`
  instead of generating another proposal or calling OpsGate. The cognitive loop
  still may call the module as a test-host harness. This follows the
  `10.20.2.88` lesson of module-specific cadence without copying the prototype
  timer table or moving scheduler ownership into Memory-OS.
- P1-T second split is live: EvidenceScoring now records an input fingerprint
  and skips unchanged reruns with `cadence_skipped=true`. Latest
  `10.20.3.200` smoke produced `generated_score_count=514` on the first run
  and `generated_score_count=0`, `reason=unchanged_input_fingerprint` on the
  second run; monitor PASS includes `evidence_scoring_cadence_skip_visible`.
- P1-T third split is live: OpsGate now returns a no-pending skip when called
  with `proposed_actions=[]`, records `runs.jsonl`, and does not append an empty
  report. Latest `10.20.3.200` smoke kept `report_count=58` unchanged,
  increased `run_report_count` to `1`, and monitor PASS includes
  `ops_gate_no_pending_skip_visible`.
- P1-T fourth split is live: DeepReflection now records an input fingerprint
  and skips same-day unchanged apply-mode reruns with `cadence_skipped=true`
  without writing another internal analysis artifact. Latest `10.20.3.200`
  smoke shows `first_status=ok`, `second_status=skipped`,
  `reason=unchanged_input_fingerprint`, `second_analysis_artifact_created=false`,
  and monitor-visible `cadence_skipped_count=1`.
- P1-T fifth split is live: HouseholdDigest, DigestConsolidation,
  GovernanceFeedback, and LeftBrainPipelineCheck now skip unchanged/no-new-signal
  runs, and EvidenceScoring no longer lets GovernanceFeedback mirror events
  change its input fingerprint. Latest `10.20.3.200` cycle showed
  `household_digest=skipped`, `digest_consolidation=skipped`,
  `governance_feedback=skipped`, `left_brain_pipeline_check=skipped`,
  `evidence_scoring=skipped`, and all hard boundaries false. Cadence report
  pending findings dropped from 11 to 3.
- P1-T sixth split is live: WanderingMind now records a bounded right-brain
  signal fingerprint and skips unchanged owner-facing/reaction signals.
  CognitiveLoop records downstream `expression_draft_skipped=true` and
  `speak_gate_skipped=true` instead of creating another draft/gate decision.
  Latest live evidence shows `ModuleCadence.finding_count=0`,
  `wandering_mind.skipped_count=1`, `expression_draft.skipped_count=1`,
  `speak_gate.skipped_count=1`, and no `module_cadence_split_pending` WARN.

Implementation order:

1. expired working filter / monitor for EvidenceScoring and DeepReflection;
2. SelfEvolution novelty and idempotency gate;
3. feature-based EvidenceScoring v2 primary scoring;
4. prototype-aligned maturity dimensions primary scoring;
5. left-brain pipeline checker;
6. proposal lifecycle / approved-follow-up state;
7. feedback backflow report-only/proposal-only;
8. approved-proposal execution-decision state design;
9. production cadence split after report-specific counters; SelfEvolution,
   EvidenceScoring, OpsGate, DeepReflection, HouseholdDigest,
   DigestConsolidation, GovernanceFeedback, and LeftBrainPipelineCheck
   module-local skip gates are deployed. The right-brain expression harness
   also has outcome/reaction-aware skip evidence; future split work must be
   chosen from refreshed counter evidence and owner/outcome volume;
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
- OpsGate report-only follow-up exists and the pending batch route is deployed;
- latest monitor evidence reports `pending=0`, `awaiting_ops_gate=0`,
  `ops_gate_reviewed=7`, `awaiting_explicit_execution=7`;
- execution tickets remain zero;
- the first bounded `expression_policy` proposal has a live explicit apply path
  after owner approval and OpsGate `would_allow`;
- the second concrete class, `proposal_queue_legacy_template_cleanup`, has a
  live explicit apply path. Latest test-host smoke closed 18 legacy template
  proposals, reported `non_legacy_touched_count=0`, and kept
  `execution_ticket_count=0` / `actual_execute=false`;
- generic external execution remains unimplemented.

Implemented path:

```text
approved_for_proposal
-> ops_gate_reviewed_awaiting_explicit_execution
-> explicit owner/operator apply
-> right_brain_expression_adapter/policy.json
-> right-brain expression helper consumes policy on next run
```

Next explicit cleanup path:

```text
approved proposal_queue_legacy_template_cleanup proposal
-> OpsGate would_allow
-> owner/operator explicit apply
-> pressure_block matched legacy template proposals only
-> legacy_template_cleanup_applies.jsonl evidence
```

Hard rule:

- bounded policy/config apply is allowed only for proposal kinds with an owned
  runtime target, rollback record, monitor field, owner approval, and OpsGate
  review;
- shell/service/filesystem execution still needs a separate owner/operator
  apply design and external review.
- cleanup apply must prove `non_legacy_touched_count=0`,
  `execution_ticket_created=false`, and `actual_execute=false`.

### P1-P - Timestamp / Aging Data Quality

Owning docs:

- `34-owner-review-digest-and-action-workflow.md`
- `39-left-brain-governance-quality-contract.md`

Current truth:

- new review items now have timestamp coverage;
- old unknown timestamp issues were a real aging distortion;
- Wandering Mind and SpeakGate would-send producers now write bounded
  `created_at`;
- monitor must keep `unknown_timestamp_count`, coverage ratio, and
  producer/derived/missing timestamp source distribution visible.

### P1-J - SessionMirror Entrance Completeness

Owning docs:

- `36-module-closure-matrix.md`
- `28-low-clue-recall-router-design.md`

Current truth:

- pending sessions remain: latest read-only evidence reports
  `session_count=64`, `covered_session_count=31`,
  `pending_session_count=33`, and `dry_run_new_event_count=33`;
- dry-run writes no events and reports no findings:
  `dry_run_written_event_ids_count=0`, `dry_run_findings_count=0`;
- the latest bounded source-correlation found no pending-only topic group and
  `internet_data_collection_pending_count=0` versus
  `internet_data_collection_provider_count=12`;
- current evidence does not justify one-time SessionMirror apply. Apply review
  requires a future pending-only source group that correlates with a real
  RH-28/RH-26 recall omission plus explicit owner approval.

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
- recurring owner agenda pushes bulk Review Suggested/FYI/backlog totals
  instead of only decisions and true alerts;
- recurring owner agenda asks for approval of a proposal whose visible content
  is only a generic/template title rather than a bounded concrete change,
  reason, and follow-up effect;
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
