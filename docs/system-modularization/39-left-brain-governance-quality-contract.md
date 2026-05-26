# RH-39 Left-Brain Governance Quality Contract

Date: 2026-05-26

Status: design gate; no runtime implementation in this document.

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
  - self_evolution.novelty_skipped_count
  - self_evolution.duplicate_unresolved_proposal_count
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

The latest 10.20.3.200 monitor shows no hard failure but exposes quality gaps:

```text
working_items=168
expired=147
evidence.score_count=606
evidence.subject_counts.working=168
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

### 2. Self-Evolution Can Create Proposal Backlog

Self-Evolution currently uses the top evidence scores to create proposal
candidates. Without novelty, idempotency, and unresolved-proposal checks, it can
turn stable recurring evidence into repeated proposals.

Contract rule:

```text
Self-Evolution must not create a new proposal when the same proposal class,
same score refs, or same unresolved target already exists.
```

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
```

Forbidden claims today:

```text
left-brain intelligent scoring: not implemented
left-brain feedback learning: not closed
self-evolution quality loop: not mature
production cadence: not mature
proposal-to-execution operations: not implemented
```

## Implementation Order

Do not replace live behavior in one step. The safe path is:

1. expired working filter / monitor;
2. SelfEvolution novelty and idempotency gate;
3. feature-based EvidenceScoring v2 in report-only mode;
4. feedback backflow into GovernanceFeedback in report-only/proposal-only mode;
5. approved proposal execution-decision state design;
6. production cadence split with generated/skipped/error fields;
7. ContextRouter/Ingress de-duplication with parity tests.

Each step must update RH-36 mapping, monitor fields, and 07 evidence before it
can be called closed.
