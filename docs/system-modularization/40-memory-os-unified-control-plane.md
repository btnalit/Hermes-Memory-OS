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
8. `32-active-roadmap-and-gates.md`
   - detailed backlog and long-form gate notes;
   - subordinate to this unified control plane for priority reading order.

If these documents conflict, resolve in this order:

```text
07 evidence -> 29/36/37/38/39 contracts -> 40 control plane -> 32 details
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
active_work_item_count=19
active_work_mapping_count=19
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

## Active Priority Order

### P0 - Commit Current Governance Baseline

Scope:

- RH-36 closure matrix enforcement and active mapping;
- RH-37 agent collaboration contract;
- RH-38 right-brain expression contract;
- RH-39 left-brain governance quality contract;
- 29 / 32 / 36 / 40 alignment;
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
  output records a SpeakGate decision and monitor fields; historical missing
  decisions remain visible as WARN until old reports age out or are separately
  accounted for;
- expression feedback backflow is not implemented.

Required before runtime:

- RightBrainExpressionEngine / Hermes-agent expression adapter contract;
- every non-silent draft passes SpeakGate;
- owner can see bounded expression content;
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
- evidence scoring is hash-derived;
- SelfEvolution can produce proposal backlog;
- feedback backflow is not closed;
- local P1-S slice 1 filters expired working out of EvidenceScoring and adds
  monitor visibility for expired scoring contamination;
- DeepReflection expired-working handling is still not fixed;
- production cadence is not mature.

Implementation order:

1. expired working filter / monitor;
2. SelfEvolution novelty and idempotency gate;
3. feature-based EvidenceScoring v2 report-only;
4. feedback backflow report-only/proposal-only;
5. approved-proposal execution-decision state design;
6. production cadence split;
7. ContextRouter / Ingress de-duplication with parity tests.

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
