# RH-38 Right-Brain Expression Closure Contract

Date: 2026-05-26

Status: design gate plus first local wiring slice.

Current implementation state:

- P1-R slice 1 is deployed on the `10.20.3.200` test host: cognitive loop
  Wandering output now records a SpeakGate decision for every result that
  contains an output.
- Monitor summary now exposes `speak_gate_evaluated_count`,
  `speak_gate_missing_evaluation_count`, and
  `speak_gate_decision_distribution`.
- This does not implement a RightBrainExpressionEngine, scheduled expression
  delivery, owner expression feedback, or governance backflow.
- Current live monitor still reports historical missing SpeakGate evaluations
  from older cognitive-loop reports; new-cycle evidence shows the wiring works.

## Why This Exists

The Memory-OS architecture defines Wandering Mind as right-brain expression:
it should express feeling and free association, not tasks, proposals, agenda,
or KPI work. It also describes a path where Wandering Mind may produce free
expression or `[SILENT]`, then optionally deliver through Hermes origin.

The current v0.1 implementation does not close that product loop. It closes a
safer test-host observation loop:

```text
bounded summaries
-> deterministic wandering text
-> would-send artifact
-> no actual send
-> owner may allow one exceptional payload
```

That is useful safety evidence, but it is not the same as formal right-brain
expression. Treating it as complete would erase the original right-brain
product requirement.

## Dynamic Closure Preflight

```yaml
source_of_truth:
  - docs/memory-os/architecture.md
  - docs/system-modularization/29-memory-os-module-integration-contract.md
  - docs/system-modularization/32-active-roadmap-and-gates.md
  - docs/system-modularization/36-module-closure-matrix.md
  - current 10.20.3.200 monitor evidence
finding_type: "contract gap / architecture drift"
owning_seam: "right-brain expression, SpeakGate, Hermes origin delivery, expression feedback"
reverse_scope: "Hermes owns agent conversation, origin delivery, cron, cooldowns, and transport; Memory-OS owns bounded memory view, expression draft state, gate evidence, feedback ledger, and policy proposals"
equivalent_contract_or_project_contract: "29-series contract + RH-36 closure matrix + RH-37 agent collaboration"
evidence_loop: "contract check, unit/integration tests, 10.20.3.200 monitor, owner-visible expression smoke only after explicit opt-in"
monitor_or_validation_fields:
  - right_brain_expression.engine_available
  - right_brain_expression.draft_count
  - right_brain_expression.silent_count
  - right_brain_expression.speak_gate_evaluated_count
  - right_brain_expression.scheduled_delivered_count
  - right_brain_expression.exceptional_permission_count
  - right_brain_expression.feedback_by_type
  - right_brain_expression.policy_update_pending_count
  - right_brain_expression.prompt_version
promotion_signal: "formal expression path has bounded drafts, every non-silent draft has a SpeakGate decision, owner can see/feedback expression content, and hard boundaries remain false"
stop_or_rollback_signal: "actual_send without owner-configured scheduled expression; private raw body in draft/review; task/proposal/agenda language in right-brain text; feedback cannot be traced back to policy/proposal"
external_review: "required before enabling scheduled right-brain expression delivery"
```

## Current Evidence

The current code and monitor support a safe observation path only:

- Wandering Mind currently emits deterministic text from recent event summaries.
- The shell plugin deliberately does not register LLM-call hooks.
- SpeakGate has `evaluate_wandering_output()`.
- P1-R slice 1 wires cognitive loop Wandering output through SpeakGate and
  records monitor fields for evaluated and missing decisions.
- Live test-host evidence after deployment: one new cognitive-loop cycle
  produced a `speak_gate_decision.decision=would_send` with all hard
  boundaries false.
- Existing live monitor evidence still includes historical missing SpeakGate
  evaluations from older reports.
- Owner review can list speak/would-send items, but v0.1 mostly shows bounded
  references and action tokens, not enough expression content for owner quality
  judgment.
- Governance feedback currently consumes evidence / ops / proposal /
  self-evolution outcomes, not full wandering/speak feedback outcomes.

Therefore v0.1 should be described as:

```text
right-brain observation shell: implemented
formal right-brain expression closure: not implemented
```

## Right-Brain Subsystem Audit

Right-brain closure is not only the Wandering Mind module. It is the whole
association / expression / carryover chain. Each output has a different closure
route and must not be flattened into `would-send`.

| Surface | Intended core function | Current implementation evidence | Correct closure route | Current gap |
| --- | --- | --- | --- | --- |
| Household Digest | Build a bounded recent-state substrate for association and reflection. | `HouseholdDigestModule.build_digest()` writes a local digest from event summaries. | Internal input artifact plus monitor evidence; no owner action by itself. | No quality feedback loop for "digest too narrow / too mechanical"; downstream expression quality cannot yet point back to digest quality. |
| DeepReflection analysis | Slow association over working, digest, governance, evidence, and proposal state. | `DeepReflectionModule.run_once()` writes deterministic internal analysis; `llm_enabled=false`. | Analysis artifact and monitor evidence only. It must not become memory, identity, or instructions by itself. | Formal right-brain behavior is still deterministic and mechanism-heavy; no LLM/Hermes-agent reflective adapter exists. |
| DeepReflection injection / carryover cards | Project bounded continuity into future conversation context. | `build_injection_cards()` writes `deep_reflection.injection.v0` and current injection history. | ContextProjection with RH-26/RH-28 routing, MemorySources attribution, and mechanism-leakage monitor. | This is context continuity, not expression. It can help ordinary chat but does not close right-brain free-expression delivery. |
| DeepReflection optional proposal | Turn reflection findings into self-evolution proposals. | `emit_optional_outputs()` can create proposal queue candidates when enabled. | Proposal review: owner approve/reject, then approved-proposal follow-up; no execution by approval alone. | This route is left-brain governance, not expression. It must stay separate from right-brain text delivery. |
| DeepReflection wandering seed | Seed future associative expression without sending. | `emit_optional_outputs()` can append `deep_reflection.wandering_seed.v0`; live evidence shows seed counts, but seeds are not consumed by a formal expression engine. | Input to RightBrainExpressionEngine, then SpeakGate, then scheduled/exceptional expression route. | Seed production exists, but seed consumption is not wired into Wandering/SpeakGate formal expression closure. |
| Conversation Carryover | Preserve bounded conversational continuity. | Prefetch projects carryover / DR cards into context and RH-29 records sources. | ContextProjection plus MemorySources and RH-30 feedback. | Carryover is not owner-visible expression and must not be counted as right-brain delivery. |
| Wandering Mind | Generate non-task free association / feeling expression or silence. | `WanderingMindModule.run_once()` currently builds deterministic text from the latest event summary and records would-send artifacts with `actual_send=false`. | RightBrainExpressionEngine output draft; every non-silent draft must pass SpeakGate. | Current module is a safe deterministic draft shell, not a real right-brain expression engine. |
| SpeakGate | Decide whether an expression draft is silent, scheduled-allowed, blocked, would-send observation, or exceptional permission-required. | `SpeakGateModule.evaluate_wandering_output()` exists, but the cognitive loop currently calls Wandering Mind directly and does not route every Wandering output through SpeakGate. | Mandatory decision for every non-silent expression draft. | Live monitor shows Wandering would-send artifacts while SpeakGate would-send remains zero, proving the formal decision path is not closed. |
| Owner Review for expression | Let the owner judge expression quality and exceptional send permission. | Owner review can surface speak/would-send items and action tokens. | Show bounded expression preview, why it appeared, delivery tier, and stable token if action is needed. | Payload refs / action tokens alone are not enough to judge "voice"; expression content feedback is missing. |
| Expression feedback | Convert owner judgment into bounded evidence. | `allow_speak_once` exists; expression quality labels do not. | `like`, `too_mechanical`, `too_frequent`, `boundary_private`, `off_voice`, `mute_period` into expression feedback ledger. | No real expression feedback ledger or feedback-to-policy proposal path exists. |
| GovernanceFeedback / SelfEvolution backflow | Turn expression outcomes into policy/prompt/frequency proposals. | GovernanceFeedback consumes evidence, ops, proposal, and self-evolution outcomes; it does not currently consume full wandering/speak outcomes. | Bounded governance events and owner-reviewed proposals only. | Expression outcomes cannot yet improve prompt, cadence, or SpeakGate policy. |

The current right-brain chain is therefore:

```text
event summaries
-> household digest
-> deterministic Wandering output
-> wandering would-send artifact
-> no actual send
```

The intended formal chain is:

```text
bounded memory view
+ household digest
+ DeepReflection wandering seed
+ expression policy / feedback aggregates
-> RightBrainExpressionEngine or Hermes-agent expression adapter
-> expression draft
-> SpeakGate decision
-> Hermes origin delivery when scheduled/allowed
-> owner-visible content and expression feedback
-> GovernanceFeedback / SelfEvolution proposal
-> owner approve/apply gate
```

Any claim of "right-brain closure" must name which route is closed:

- context continuity;
- internal reflection;
- proposal governance;
- test-host expression observation;
- scheduled expression delivery;
- exceptional proactive permission;
- expression feedback backflow.

## Expression Tiers

### Tier 1 - Test-Host Observation

Purpose:

```text
Prove bounded right-brain artifacts can be generated without sending.
```

Rules:

- default on `10.20.3.200` test host;
- no actual transport send;
- writes bounded output / would-send / blocked / silent artifacts;
- monitor counts artifacts and hard boundaries;
- owner may inspect exceptional payloads but this is not the normal expression
  product path.

This is the current P1-E closure level.

### Tier 2 - Scheduled Right-Brain Expression

Purpose:

```text
Let Hermes express low-frequency right-brain thoughts through owner-configured
origin delivery.
```

Rules:

- explicit owner/operator opt-in is required;
- cadence is low-frequency and owner-configured;
- Hermes owns cron, origin delivery, transport, cooldown, platform UI, and
  natural-language interaction;
- Memory-OS provides a bounded memory view and stores structured expression
  draft / gate / feedback evidence;
- ordinary scheduled expression does not require per-message owner approval;
- SpeakGate must evaluate every non-silent draft before delivery;
- actual delivery must be through Hermes origin/home channel, not a Memory-OS
  transport implementation;
- delivery does not execute work, write identity, write crystallized memory, or
  create proposals by itself.

Tier 2 is not implemented yet.

### Tier 3 - Exceptional Proactive Send

Purpose:

```text
Handle out-of-policy or unusual proactive expression payloads.
```

Rules:

- requires `allow_speak_once`;
- the permission ticket expires and matches one payload reference;
- this never enables default sending;
- feedback on the result must enter expression feedback, not hidden prompt
  text.

This is partially implemented as owner action / speak permission, but not yet
connected to a full expression feedback loop.

## RightBrainExpressionEngine Contract

Future implementation must not turn Wandering Mind into a task agent.

Inputs:

- bounded memory view;
- household digest;
- optional DeepReflection wandering seed;
- expression policy and owner feedback aggregates;
- no raw private body;
- no execution tools.

Outputs:

```yaml
schema_version: memory-os.expression_draft.v0
draft_id:
created_at:
text:
feeling_tags:
source_refs:
risk_flags:
silence_reason:
prompt_version:
raw_body_included: false
actual_send: false
actual_execute: false
actual_identity_write: false
actual_unapproved_crystallized_approval: false
```

Allowed implementation owners:

- Hermes agent / host LLM may generate the expression text from bounded input.
- Memory-OS may call a bounded expression adapter only if RH-37 is satisfied
  and the adapter cannot execute, send, or mutate state.
- Memory-OS stores drafts and evidence; Hermes owns conversation and delivery.

Forbidden:

- proposal/agenda/task language in right-brain output;
- automatic identity or crystallized memory writes;
- hidden prompt mutation from feedback;
- raw transcript body in draft or owner review;
- Memory-OS-owned recurring transport.

## SpeakGate Closure

Every expression draft must end in one of:

```text
silent
scheduled_allowed
scheduled_blocked
would_send_observation
exceptional_permission_required
exceptional_allowed_once
```

Required invariant:

```text
expression_draft_count
  == silent_count
   + speak_gate_evaluated_count
   + draft_error_count
```

For non-silent drafts:

```text
non_silent_draft_count == speak_gate_evaluated_count
```

Any missing SpeakGate decision is a P1 closure gap.

## Owner Review And Feedback

Owner review must show enough bounded expression content to judge voice quality.
It must not show only `payload_ref`.

Minimum owner-visible fields:

- bounded expression preview;
- why the item is shown;
- source module;
- delivery tier;
- suggested action;
- consequence;
- stable action token when an owner action is needed.

Expression feedback actions:

```text
like
too_mechanical
too_frequent
boundary_private
off_voice
mute_period
```

These actions write an `expression_feedback_ledger` or equivalent bounded
FeedbackSignal. They do not directly change live prompts, cadence, routing, or
delivery. Policy changes must become proposals and go through owner review /
apply gates.

## Backflow

Expression outcomes must feed governance as bounded evidence:

```text
drafted
silent
scheduled_allowed
scheduled_blocked
exceptional_permission_requested
exceptional_allowed_once
delivered
ignored
owner_feedback
expired
```

GovernanceFeedback and SelfEvolution may use these outcomes to propose:

- prompt version changes;
- expression frequency changes;
- SpeakGate policy changes;
- owner burden adjustments;
- source-class budget changes.

They must not apply those changes automatically.

## Monitor Contract

Do not claim formal right-brain expression closure without these fields:

- `right_brain_llm_available`
- `expression_draft_count`
- `expression_silent_count`
- `speak_gate_evaluated_count`
- `scheduled_delivered_count`
- `exceptional_permission_count`
- `owner_feedback_by_type`
- `policy_update_pending_count`
- `prompt_version`
- `expression_raw_body_included_count`
- `expression_task_language_count`
- `expression_boundary_true_count`

Test-host would-send observation remains useful, but it is not a substitute
for this monitor contract.

## Roadmap Placement

This becomes P1-R in the active roadmap:

```text
P1-R - Right-Brain Expression Closure Contract And Implementation Plan
```

P1-R must complete design and monitor contract before any runtime expression
engine or scheduled expression delivery is implemented.
