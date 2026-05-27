# RH-39 Left-Brain Governance Quality Contract

Date: 2026-05-26

Status: design gate plus deployed data-hygiene, duplicate-suppression, feature-score primary scoring v2, prototype-aligned maturity scoring, expression-feedback proposal input, agenda-candidate maturation, and report-only pipeline-check slices.

Current implementation state:

- P1-S slice 1 is implemented and deployed on `10.20.3.200`:
  EvidenceScoring skips expired working items by default.
- P1-S slice 2 is implemented and deployed on `10.20.3.200`: SelfEvolution skips duplicate
  unresolved self-evolution proposals and reports novelty skip counts.
- P1-S slice 3/4 are superseded by the 2026-05-26 runtime closure baseline:
  EvidenceScoring v2 now writes `scores.jsonl` with
  `score_source=feature_maturity_v2`, `feature_score_mode=primary`, and
  `hash_score_legacy_count=0`. Legacy hash scores remain only as bounded
  comparison fields (`legacy_hash_score`, `legacy_hash_comparison_count`).
- P1-S expression-feedback input is implemented: expression feedback ledger
  records become scoring subjects, and SelfEvolution can create an
  `expression_policy` proposal when the feedback is linked to a recorded
  right-brain expression outcome. This still does not directly change prompt,
  cadence, policy, delivery, or execution.
- P1-S MemorySources-feedback input is implemented: RH-30
  `memory_sources_feedback` records become scoring subjects and GovernanceFeedback
  summary-only events. Corrective, source-linked feedback can create a
  `memory_sources_policy` proposal for owner review. Useful/non-corrective
  feedback remains evidence and does not create proposal pressure.
- P1-S MemorySources-feedback collection surface is implemented on
  `10.20.3.200`: Hermes agent can call
  `memory_os_review_surface(operation=memory_sources_feedback_context)` to read
  the latest bounded MemorySources attribution context and stable feedback
  tokens, then call structured `memory_os_review_reply` only after owner intent.
  The surface is read-only; it does not write feedback, route changes, prompt
  changes, policy changes, or proposals by itself. The monitor emits
  `memory_sources_feedback_volume_missing` while this collection surface is
  ready but live `MemorySources.feedback_count=0`, and switches to
  `memory_sources_feedback_volume_present` once real feedback exists.
- P1-S agenda-candidate maturation is implemented and deployed on
  `10.20.3.200`: SelfEvolution now records every selected signal as a bounded
  `agenda_candidate` with maturity fields, quality gate, runtime target,
  promotion status, and block reason before it can be promoted into a proposal.
  Created proposals carry the source `agenda_candidate_id` and
  `agenda_maturity_gate`; blocked, duplicate, and same-day signals are visible
  without creating owner agenda pressure.
- P1-S agenda trace checking is implemented and deployed on `10.20.3.200`:
  `left_brain_pipeline_check` reports `agenda_trace_missing_count` and warns
  with `proposal_agenda_trace_missing` when an owner-actionable non-legacy
  proposal has `proposal_quality` but lacks `agenda_candidate_id`,
  `agenda_maturity_gate`, or `agenda_promotion_status`.
- 2026-05-26 live smoke on `10.20.3.200` proved the owner/Hermes interaction
  path, not only SSH/CLI: a rendered speak item exposed
  `memory feedback oa_<token> too_mechanical`, a structured
  `memory_os_review_reply` call recorded `too_mechanical` feedback for
  `target_type=expression`, and the next cognitive-loop run exposed it in
  EvidenceScoring/GovernanceFeedback monitor fields.
- EvidenceScoring status and the 10.20.3.200 monitor can now expose whether
  expired working evidence still appears in scoring output and whether
  feature scoring is the primary scoring path.
- P1-S pipeline-check slice is implemented and deployed on `10.20.3.200`:
  cognitive loop writes `left_brain_pipeline_check/latest.json`; monitor reports
  `left_brain_pipeline_check.status`, `finding_count`, `actual_execute`, and
  duplicate maturity buckets.
- P1-S duplicate-maturity cleanup is implemented and deployed on
  `10.20.3.200`: pipeline check now distinguishes owner-actionable active
  duplicates from follow-up duplicates and historical template duplicates.
  Current live evidence reports `status=ok`, `finding_count=0`,
  `active_duplicate_group_count=0`, `followup_duplicate_group_count=0`, and
  `legacy_template_duplicate_group_count=1`.
- P1-S proposal-usefulness maturity check is implemented and deployed on
  `10.20.3.200`: pipeline check now reports
  `proposal_quality_missing_count`,
  `expression_policy_quality_ready_count`,
  `expression_policy_quality_blocked_count`, and
  `expression_policy_unlinked_quality_count`. It only checks
  owner-actionable non-legacy proposals and remains report-only
  (`actual_execute=false`). Latest live monitor reports all four counts at `0`,
  meaning no active expression-policy proposal is currently waiting for owner
  approval and no quality gap is hidden.
- P1-S DeepReflection proposal quality repair is implemented and deployed on
  `10.20.3.200`: optional `deep_reflection_self_evolution` proposals now write
  stable `proposal_class`, `dedupe_key`, concrete owner-readable body sections,
  and report-only `proposal_quality`. A bounded live metadata repair fixed 3
  historical DeepReflection proposals and closed 1 duplicate as
  `pressure_blocked`; latest monitor reports `left_brain_pipeline_check.status=ok`,
  `finding_count=0`, and `proposal_quality_missing_count=0`.
- This replaces legacy hash scoring as the primary scoring path. It does not
  implement automatic prompt/policy/cadence apply, production cadence, or
  execution apply.
- Live `10.20.3.200` deployment evidence shows the installed scoring path no
  longer uses expired working as active scoring subjects.
- Latest live monitor after that smoke reports
  `expression_feedback_subject_count=2`, `expression_feedback.feedback_count=2`,
  `governance_feedback.emitted_event_count=135`, `structured_review_reply_count=1`,
  and `reply_fallback_used_count=0`.
- The follow-up EvidenceScoring rating propagation fix is live on
  `10.20.3.200`: expression feedback evidence and maturity dimensions now carry
  `feedback_rating=too_mechanical` instead of `unknown`.
- The 2026-05-27 feedback-quality gate is live on `10.20.3.200`:
  EvidenceScoring exposes `expression_feedback_linked_subject_count` and
  `expression_feedback_unlinked_subject_count`; SelfEvolution rejects
  unlinked-only feedback as `proposal_quality_gate_failed` instead of creating
  owner-facing proposal pressure. Targeted live smoke reports
  `expression_feedback_subject_count=3`, linked `1`, unlinked `2`,
  same-day same-signal skip, and `actual_execute=false`.

## Why This Exists

The left-brain governance chain now has a real safety loop:

```text
events / working / candidates
-> digest / evidence / proposal / self-evolution / governance feedback
-> owner review
-> OwnerActionProcessor
-> audit / monitor
```

That loop is safe, but it is not yet a mature judgment loop. Evidence scoring
is deterministic and reproducible, owner mutation is gated, and execution is
blocked by design. Those properties are good. They do not prove that scoring,
proposal generation, feedback backflow, or production cadence are meaningful.

This document separates:

- left-brain safety governance: implemented;
- left-brain judgment quality: not mature;
- left-brain feedback adaptation: not closed;
- left-brain operational cadence: still test-host biased.

## Dynamic Closure Preflight

```yaml
source_of_truth:
  - docs/system-modularization/29-memory-os-module-integration-contract.md
  - docs/system-modularization/32-active-roadmap-and-gates.md
  - docs/system-modularization/36-module-closure-matrix.md
  - docs/system-modularization/07-validation-report-10.20.3.200.md
  - current 10.20.3.200 monitor evidence
finding_type: "contract gap / judgment-quality gap / feedback-backflow gap"
owning_seam: "left-brain governance quality: evidence scoring, self-evolution, feedback backflow, working expiry, proposal follow-up, cadence"
reverse_scope: "Hermes owns conversation and execution UX; Memory-OS owns bounded governance evidence, proposal state, owner action state, OpsGate report-only review, and monitor evidence"
equivalent_contract_or_project_contract: "29-series contract + RH-36 closure matrix + RH-37 agent collaboration"
evidence_loop: "unit/integration tests, RH-36 closure check, 10.20.3.200 monitor, scorecard comparison, owner-visible follow-up surface"
monitor_or_validation_fields:
  - left_brain_scoring.mode
  - left_brain_scoring.feature_score_count
  - left_brain_scoring.hash_score_legacy_count
  - left_brain_scoring.expired_used_in_scoring_count
  - left_brain_scoring.owner_feedback_signal_count
  - left_brain_scoring.memory_sources_feedback_subject_count
  - left_brain_scoring.memory_sources_feedback_linked_subject_count
  - left_brain_scoring.memory_sources_feedback_corrective_subject_count
  - left_brain_scoring.feature_score_live_applied
  - left_brain_scoring.comparison_count
  - left_brain_scoring.prototype_aligned_score_count
  - left_brain_scoring.maturity_dimension_count
  - left_brain_scoring.maturity_live_applied
  - self_evolution.novelty_skipped_count
  - self_evolution.duplicate_unresolved_proposal_count
  - left_brain_pipeline_check.active_duplicate_group_count
  - left_brain_pipeline_check.followup_duplicate_group_count
  - left_brain_pipeline_check.legacy_template_duplicate_group_count
  - left_brain_pipeline_check.memory_sources_policy_quality_ready_count
  - left_brain_pipeline_check.memory_sources_policy_quality_blocked_count
  - left_brain_pipeline_check.memory_sources_policy_unlinked_quality_count
  - left_brain_pipeline_check.agenda_trace_missing_count
  - feedback_backflow.consumed_count
  - feedback_backflow.apply_ready_count
  - approved_proposal_followups.awaiting_ops_gate_count
  - approved_proposal_followups.ops_gate_reviewed_count
  - approved_proposal_followups.execution_ticket_count
  - cadence.generated_count
  - cadence.skipped_no_new_signal_count
promotion_signal: "feature-based scoring is report-only compared against legacy hash scoring, self-evolution duplicate proposal creation is suppressed, expired working is not used as active evidence, and feedback backflow can create owner-reviewed proposals without direct live mutation"
stop_or_rollback_signal: "scoring drives live action without owner review; proposal approval creates execution tickets; feedback directly changes routing/prompt/cadence; expired working dominates scoring; repeated unresolved proposals keep being created"
external_review: "required before replacing legacy scoring as live input or before adding any execution/apply capability"
```

## Current Evidence

The earlier 10.20.3.200 monitor exposed the data-quality gap that motivated
P1-S slice 1:

```text
working_items=168
expired=147
evidence.score_count=606
evidence.subject_counts.working=168
evidence.expired_used_in_scoring_count=not available before P1-S slice 1
self_evolution.report_count=16
self_evolution.proposal_count=16
proposal_queue.approved_for_proposal=7
proposal_queue.candidate=11
owner_review.feedback_backflow.apply_ready_count=0
MemorySources.feedback_count=0
approved_proposal_followups.awaiting_ops_gate=6
approved_proposal_followups.execution_tickets=0
```

This means:

- the hard safety layer is working;
- the judgment layer is still weak;
- feedback has not become a real governance input;
- approved proposals are visible, but many still need follow-up;
- execution remains correctly blocked.

P1-Q live follow-up correction on `10.20.3.200`:

```text
owner_review.proposal_followup_batch.schema=memory-os.approved_proposal_ops_gate_batch.v0
dry_run=false
eligible_count=0
execution_ticket_created=false
actual_execute=false

approved_proposal_followups.approved=8
approved_proposal_followups.pending=0
approved_proposal_followups.open=7
approved_proposal_followups.awaiting_ops_gate=0
approved_proposal_followups.ops_gate_reviewed=7
approved_proposal_followups.awaiting_explicit_execution=7
approved_proposal_followups.policy_apply_count=1
approved_proposal_followups.execution_tickets=0
approved_proposal_followups.actual_execute=false
```

This means the P1-Q runtime gap is no longer "approved proposals are waiting
for OpsGate review." The current state is narrower: generic approved proposals
are visible after OpsGate report-only review and wait for a separate explicit
execution/apply decision. That decision path must stay proposal-kind-specific
and must not become a generic executor.

P1-S slice 1 deployment evidence on `10.20.3.200`:

```text
commit=1f56294 Filter expired working from evidence scoring
cycle_id=cloop_20260526T074331475537Z_51164c286d
cycle_status=ok
evidence.score_count=477
evidence.evidence_count=477
evidence.working_active_subject_count=21
evidence.working_expired_skipped_count=147
evidence.working_unknown_status_count=0

monitor_status=WARN
monitor_FAIL=[]
monitor.ModuleArtifacts.evidence.working_subject_count=21
monitor.ModuleArtifacts.evidence.expired_used_in_scoring_count=0
monitor.PASS includes left_brain_expired_working_not_scored
```

This is a live PASS for the EvidenceScoring expired-working hygiene slice only.
It does not close DeepReflection expired-working handling or left-brain
judgment quality.

Follow-up correction:

```text
commit=627d786 Use scoring-time working status in evidence monitor

Evidence records now store source_status for working subjects at scoring time.
expired_used_in_scoring_count now means "scored while expired", not "the item
expired after the score was written".

post-correction monitor:
  status=WARN
  FAIL=[]
  ModuleArtifacts.evidence.working_subject_count=17
  ModuleArtifacts.evidence.expired_used_in_scoring_count=0
  PASS includes left_brain_expired_working_not_scored
```

## Left-Brain Chain

```text
Provider / Ingress / Context Router
-> MemorySources attribution / RH-30 feedback
-> Inner Drive / Working / Candidates
-> Digest / Evidence Scoring / Proposal Queue
-> Self-Evolution / Governance Feedback / DeepReflection
-> Owner Review / OwnerActionProcessor / OpsGate report-only
```

The chain is valid only if each stage keeps its role:

- scoring ranks bounded evidence, not decisions;
- self-evolution proposes, not applies;
- feedback records signals, not live mutations;
- owner actions mutate only through OwnerActionProcessor;
- OpsGate review is report-only until a separate explicit execution gate.

## Findings

### 1. Evidence Scoring Is Reproducible, Not Meaningful

Current scoring uses a deterministic hash-derived score. This is useful for
stable fixtures and replayability, but it does not encode:

- repeated signal strength;
- owner feedback;
- source diversity;
- recency;
- risk;
- proposal state;
- eval finding severity;
- active vs expired working status.

Contract rule:

```text
Legacy hash scoring may remain as deterministic baseline.
Any claim of intelligent evidence scoring requires feature-based score reports
and a comparison against the legacy baseline before live use.
```

P1-S slice 3:

```text
EvidenceScoring now writes a separate report-only feature score artifact:

  system-modules/evidence_scoring/feature_scores.jsonl

Feature records use schema hermes.evidence_feature_score.v0 and include:

  mode=report_only
  live_applied=false
  feature_score
  legacy_score
  score_delta
  evidence_refs
  bounded numeric features

Legacy scores remain in scores.jsonl with schema hermes.evidence_score.v0.
SelfEvolution still reads legacy scores; feature scores are not a live input.
```

Local evidence:

```text
python -m pytest tests/system_modularization/test_evidence_scoring_module.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

45 passed

python scripts/memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=16
matrix_module_count=28
active_work_item_count=19
active_work_mapping_count=19
finding_count=0

git diff --check
PASS
```

Live deployment evidence:

```text
commit=b334091 Add report-only feature evidence scoring
cycle_id=cloop_20260526T092633913253Z_eded9ce0e5
cycle_status=ok

EvidenceScoring:
  score_count=484
  evidence_count=484
  feature_score_mode=report_only
  feature_score_count=484
  hash_score_legacy_count=484
  comparison_count=484
  feature_score_report_count=1
  feature_score_live_applied=false
  working_active_subject_count=13
  working_expired_skipped_count=155

Monitor:
  status=WARN
  FAIL=[]
  PASS includes left_brain_feature_scoring_report_only_ok
  PASS includes left_brain_expired_working_not_scored
```

P1-S slice 4:

```text
The report-only feature score is now prototype-aligned with the 10.20.2.88
self-evolution pipeline shape. It stays in feature_scores.jsonl and adds:

  maturity_score
  prototype_alignment.source=10.20.2.88:self_evolution_daily_pipeline
  prototype_alignment.mode=adapted_report_only
  maturity_live_applied=false

Maturity dimensions:

  evidence_strength
  recurrence
  actionability
  source_diversity
  owner_feedback
  risk
  freshness_decay
  duplicate_backlog
  gate_state

This maps the prototype's maturity_score / evidence_strength /
evidence_count / qualified_evidence_count / actionable_qualified_count /
observation_days / trigger_rule / approved_pending_execution pattern into
bounded Memory-OS evidence reports.
```

Local evidence:

```text
python -m pytest tests/system_modularization/test_evidence_scoring_module.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

47 passed
```

Live deployment evidence:

```text
commit=38112c8 Add prototype-aligned maturity scoring report
cycle_id=cloop_20260526T094239150751Z_136e98a908
cycle_status=ok

EvidenceScoring:
  score_count=487
  evidence_count=487
  feature_score_mode=report_only
  feature_score_count=487
  hash_score_legacy_count=487
  comparison_count=487
  prototype_aligned_score_count=487
  maturity_dimension_count=9
  maturity_live_applied=false
  feature_score_live_applied=false
  working_active_subject_count=10
  working_expired_skipped_count=158

Monitor:
  status=WARN
  FAIL=[]
  PASS includes left_brain_maturity_scoring_report_only_ok
  PASS includes left_brain_feature_scoring_report_only_ok
  PASS includes left_brain_expired_working_not_scored
```

This is a live PASS for report-only prototype-aligned maturity reporting only.
It does not replace legacy hash scoring as a live input.

### 2. Self-Evolution Can Create Proposal Backlog

Self-Evolution currently uses the top evidence scores to create proposal
candidates. Without novelty, idempotency, and unresolved-proposal checks, it can
turn stable recurring evidence into repeated proposals.

Contract rule:

```text
Self-Evolution must not create a new proposal when the same proposal class,
same score refs, or same unresolved target already exists.
```

P1-S slice 2:

```text
SelfEvolution now checks proposal_queue before calling OpsGate.
If an unresolved self_evolution proposal already exists for the same class or
score refs, it writes a report with:

  proposal_created=false
  novelty_skipped=true
  reason=duplicate_unresolved_proposal
  existing_proposal_id=<existing proposal>

status() reports:
  novelty_skipped_count
  duplicate_unresolved_proposal_count
```

Live deployment evidence:

```text
commit=b6c276e Skip duplicate self-evolution proposals
cycle_id=cloop_20260526T081348363087Z_d6f5880b4f
self_evolution.proposal_created=false
self_evolution.novelty_skipped=true
self_evolution.reason=duplicate_unresolved_proposal
self_evolution.existing_proposal_id=prop_20260521T032500041194Z_2f96a933aa

monitor.ModuleArtifacts.self_evolution:
  proposal_count=19
  report_count=20
  novelty_skipped_count=1
  duplicate_unresolved_proposal_count=1
```

This is a live PASS for duplicate unresolved proposal suppression only. It does
not close feature-based scoring, feedback backflow, or production cadence.

P1-S slice 3:

```text
SelfEvolution no longer creates owner-facing template proposals such as
"Self-Evolution dry-run proposal".

New proposals must render bounded owner-readable content:

  具体改动
  证据
  验收标准
  后续状态
  边界

Legacy generic proposals do not block new concrete proposals. They remain
visible only as review/maturation artifacts and must not ask the owner for
blind approval.
```

Live deployment evidence:

```text
new_proposal.kind=expression_policy
new_proposal.title=调整右脑表达策略：too_mechanical 反馈
new_proposal.actual_execute=false
owner_agenda.action_required=1
owner_agenda.text_char_count=988
owner_agenda.review_suggested_suppressed=true
owner_agenda.fyi_suppressed=true
owner_agenda.raw_body_included=false
monitor.FAIL=[]
```

This is a live PASS for concrete proposal generation and agenda eligibility.
It still does not mean the proposal is executed; approval only moves it to
OpsGate/manual follow-up.

### 3. Feedback Backflow Is Not Closed

Feedback ledgers exist, but feedback is not yet a first-class input to
GovernanceFeedback, scoring, DeepReflection, or SelfEvolution.

Contract rule:

```text
Owner feedback may become bounded governance evidence and proposal input.
It must not directly mutate routing, prompt text, cadence, or delivery policy.
```

### 4. Expired Working Must Not Drive Active Judgment

Expired working items are expected as retention/decay state. They should not
carry the same weight as active working memory in evidence scoring or
reflection.

P1-S slice 1:

```text
EvidenceScoring now skips working items whose status is expired.
It reports working_active_subject_count, working_expired_skipped_count,
working_unknown_status_count, working_subject_count, and
expired_used_in_scoring_count.
```

Contract rule:

```text
Scoring and reflection must either filter expired working by default or mark it
with explicit low-weight / historical status. Monitor must expose expired usage.
```

### 5. Ingress And Context Router Must Not Drift

Ingress owns hard entry-turn classification. Context Router may select and
budget context sections, but it should not become a second independent ingress
classifier.

Contract rule:

```text
New hard-route or low-clue classification markers belong in ingress.py.
Context Router may preserve compatibility checks only with parity tests and a
deprecation path.
```

### 6. Approved Proposal Follow-Up Is Visible But Not Finished

Approval moves a proposal to `approved_for_proposal`, and the follow-up surface
keeps `execution_ticket_count=0`. That is safe. It is not the final execution
workflow.

Contract rule:

```text
approved_for_proposal
-> ops_gate_reviewed_awaiting_explicit_execution
-> awaiting_owner_execution_decision
-> applied / rejected / snoozed
```

The last execution decision gate is future work and must require explicit
owner/operator action.

### 7. Production Cadence Is Not The Test-Host Cognitive Loop

The 6-hour cognitive loop is an integration harness. It should not become the
long-term production cadence for every left-brain module.

Contract rule:

```text
Each left-brain module must expose generated / skipped / errored counts and a
module-local novelty or idempotency gate before being called production cadence
ready.
```

## Closure Claims

Allowed claims today:

```text
left-brain safety governance: implemented
owner-action mutation path: implemented
proposal approval safety: implemented
OpsGate report-only follow-up: implemented
bounded expression-policy apply: implemented for owner-approved + OpsGate-reviewed proposals
```

Forbidden claims today:

```text
left-brain intelligent scoring: v2 primary scoring implemented, not yet proven mature
left-brain feedback learning: expression feedback can create proposal input, not direct adaptation
self-evolution quality loop: not mature
production cadence: not mature
generic proposal-to-execution operations: not implemented
```

Current explicit apply boundary:

- `expression_policy` proposals can be applied after owner approval and OpsGate
  `would_allow` into
  `system-modules/right_brain_expression_adapter/policy.json`;
- this is a bounded policy write consumed by the right-brain expression helper,
  not shell/service execution;
- apply records are appended to `policy_applies.jsonl` with rollback evidence;
- `actual_execute`, `actual_send`, identity write, and unapproved
  crystallized approval remain false.
- `proposal_queue_legacy_template_cleanup` is the second explicit apply class:
  it is allowed only for `kind=proposal_queue_cleanup` plus
  `proposal_class` or `dedupe_key=proposal_queue_legacy_template_cleanup`;
  after owner approval and OpsGate `would_allow`, it may close matched legacy
  template proposals by setting them to `pressure_blocked` and appending
  `legacy_template_cleanup_applies.jsonl`.
- Legacy cleanup is not a generic proposal executor. It must not touch
  concrete proposals with quality fields/classes, must not create execution
  tickets, and must report `non_legacy_touched_count=0`.

## Prototype-Informed Runtime Plan

Read-only inspection of `10.20.2.88` shows the mature left-brain pattern is a
staged Hermes cron pipeline, not one permanent all-module loop.

Observed self-evolution pipeline:

```text
collect_signals
-> proposal_cleanup
-> proposal_verify
-> agenda_maturation
-> unmatched_signal_review
-> unmatched_cluster_ledger
-> new_agenda_preview
-> speak_gate
-> new_agenda_apply_ready
-> build_runtime_digest
-> build_console
-> restart_console_server
-> pipeline_contract_check
```

Observed contract checker properties:

- read-only checker;
- validates required step order;
- validates proposal queue parseability;
- checks approved proposals have execution blocks;
- checks forced delivery is not silent when reportable reasons exist;
- detects approved-pending-execution, stale pending, duplicate scheduler
  surface, and digest/proposal count mismatch;
- reports hard boundaries such as no route executed, no ops-gate task created,
  and no Sannai state write.

Observed proposal state properties:

- proposal records carry `maturity_score`, evidence counts, observation days,
  trigger rule, approval block, execution block, timestamps, and verification
  method;
- approved proposals are not execution by themselves;
- stale / deferred / approved-pending-execution are visible states, not hidden
  text in a report.

Memory-OS must not copy the prototype pipeline step-for-step. The prototype is
a single self-evolution governor. Memory-OS has multiple interacting modules
and needs a generalized governance pipeline:

```text
signals / events / working / candidates
-> feature evidence and maturity reports
-> module-local skip / novelty / duplicate gates
-> proposal lifecycle and follow-up state
-> read-only OpsGate / contract checker
-> owner-reviewed proposal or manual apply gate
-> feedback backflow as evidence
```

Memory-OS implementation synthesis:

1. `P1-S.5` - Left-brain pipeline checker:
   - add a read-only Memory-OS pipeline consistency report for evidence,
     proposal, governance feedback, OpsGate, owner review, and cadence;
   - classify hard failure vs warning like the prototype checker;
   - do not execute or create tickets.
2. `P1-S.6` - Proposal lifecycle fields:
   - ensure proposals have approval block, execution/follow-up block,
     timestamps, verification method, and terminal/stale state;
   - make approved-pending-follow-up visible in monitor and review surface.
3. `P1-S.7` - Module-local cadence counters:
   - each left-brain module reports generated/skipped/error/duplicate counts;
   - skip/no-new-signal is a valid result, not a failure.
4. `P1-S.8` - Feedback backflow:
   - MemorySources, owner-review, expression feedback, and delivery outcomes
     become bounded governance evidence;
   - they may only produce owner-reviewed proposals, not direct prompt/routing
     or cadence changes.
5. `P1-T` - Production cadence split:
   - keep the 6-hour cognitive loop as test-host integration harness;
   - define Hermes cron classes for owner-origin, local/no-agent, monitor-poll,
     and on-demand/manual apply.
   - first runtime split is implemented: SelfEvolution adds a module-local
     cadence gate that skips same-day same-signal reruns after processing,
     without creating new proposals, without calling OpsGate again, and without
     changing Hermes cron.

Do not promote P1-S from primary scoring to direct live execution, routing, or
policy/prompt/cadence apply until the pipeline checker is green, proposal
lifecycle fields are complete, and an external review approves the apply
boundary.

## Implementation Order

Do not replace live behavior in one step. The safe path is:

1. expired working filter / monitor;
2. SelfEvolution novelty and idempotency gate;
3. feature-based EvidenceScoring v2 as the primary scoring path;
4. prototype-aligned maturity dimensions as the primary score explanation;
5. left-brain pipeline checker in report-only mode;
6. proposal lifecycle/follow-up fields;
7. feedback backflow into GovernanceFeedback in report-only/proposal-only mode;
8. approved proposal execution-decision state design;
9. production cadence split with generated/skipped/error fields; first slice,
   SelfEvolution-local cadence skip, is deployed and is not a timer change;
10. ContextRouter/Ingress de-duplication with parity tests.

Each step must update RH-36 mapping, monitor fields, and 07 evidence before it
can be called closed.
