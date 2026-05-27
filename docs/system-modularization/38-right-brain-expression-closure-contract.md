# RH-38 Right-Brain Expression Closure Contract

Date: 2026-05-26

Status: design gate plus deployed ExpressionDraft, SpeakGate wiring, owner-preview, expression-feedback ledger, and Hermes-agent expression adapter slices.

Current implementation state:

- P1-R slice 1 is deployed on the `10.20.3.200` test host: cognitive loop
  Wandering output now creates bounded `ExpressionDraft` records and routes the
  latest non-silent draft through SpeakGate.
- P1-R slice 2 is deployed on `10.20.3.200`: OwnerReview resolves Wandering
  `payload_ref` values into bounded `expression_preview` text so the owner can
  judge a would-send draft by content, not only by token/reference.
- Monitor summary now exposes `expression_draft_count`,
  `latest_expression_draft_missing_count`, `speak_gate_evaluated_count`,
  `latest_speak_gate_missing_evaluation_count`, and
  `speak_gate_decision_distribution`.
- Monitor summary now also exposes speak review preview coverage:
  `speak_item_count`, `speak_expression_preview_count`, and
  `speak_expression_preview_missing_count`.
- P1-R feedback slice is deployed as a no-send ledger path:
  expression feedback actions such as `too_mechanical` write
  `expression_feedback_ledger.jsonl`; GovernanceFeedback consumes these as
  summary-only governance events without changing live policy.
- P1-R owner/Hermes interaction slice is deployed on `10.20.3.200`: speak
  review items render bounded expression content plus stable expression
  feedback tokens. A live structured `memory_os_review_reply` tool call with
  `action=feedback`, `rating=too_mechanical`, and token
  `oa_5f5b13773e0f0a` recorded
  `efb_20260526T120942975704Z_b7c95cd5` for `target_type=expression`.
- P1-R Hermes-agent expression adapter is deployed on `10.20.3.200`: Memory-OS
  emits bounded context through `memory_os_right_brain_expression.py`, Hermes
  cron runs it in agent mode, and Hermes owns final wording, silence judgment,
  origin delivery, and interaction. The adapter records
  `memory-os.right_brain_expression_adapter_request.v0` with all hard boundary
  fields false.
- P1-R outcome ledger is deployed on `10.20.3.200`:
  `memory_os_right_brain_expression_outcome.py` scans Hermes cron output,
  extracts only the final `## Response` expression or `[SILENT]`, and records
  bounded `memory-os.right_brain_expression_outcome.v0` evidence. It does not
  call Hermes, send, execute, or write policy.
- This does not apply policy/prompt/cadence changes automatically. Such changes
  still require expression feedback -> governance/SelfEvolution proposal ->
  owner/OpsGate apply. Outcome-linked feedback now carries bounded
  `outcome_id`, `request_id`, and `policy_version` fields so owner reaction
  volume can be measured.
- Current live monitor still reports historical missing draft/SpeakGate counts
  from older cognitive-loop reports, but latest-cycle evidence reports
  `latest_expression_draft_missing_count=0` and
  `latest_speak_gate_missing_evaluation_count=0`.
- Latest live monitor after the outcome-feedback smoke reports
  `expression_feedback_count=3`, `linked_outcome_count=1`,
  `linked_outcome_missing_count=0`, `outcome_feedback_count=1`,
  `expression_feedback_subject_count=3`, `structured_review_reply_count=2`,
  `reply_fallback_used_count=0`, PASS
  `right_brain_expression_feedback_linked`, and no FAIL findings.
- P1-R reaction-volume surface is deployed on `10.20.3.200`:
  `memory_os_review_surface(operation=expression_feedback_context)` exposes the
  latest right-brain outcome, bounded preview, existing feedback counts, and
  stable feedback tokens for `like_expression`, `too_mechanical`,
  `too_frequent`, `boundary_private`, `off_voice`, and `mute_period`. Hermes
  still owns the conversation; Memory-OS only provides bounded context and
  tokenized state transitions. A live token smoke for the existing
  `too_mechanical` outcome returned `duplicate_ignored` with all hard
  boundaries false.
- Latest live outcome scan records `outcome_count=2`, latest
  `policy_version=1`, `latest_outcome_silent=false`,
  `outcome_internal_marker_count=0`, `outcome_raw_body_included_count=0`,
  `outcome_actual_send_count=0`, and `outcome_actual_execute_count=0`.
- P1-R reaction-volume monitor classification is implemented: recorded
  outcomes with fewer than 3 linked owner feedback records emit WARN
  `right_brain_expression_reaction_volume_thin`; 3 or more linked feedback
  records emit PASS `right_brain_expression_reaction_volume_sufficient`. The
  latest live monitor reports `outcome_count=2`, `outcome_feedback_count=1`,
  WARN `right_brain_expression_reaction_volume_thin`, and no FAIL findings.
- EvidenceScoring now preserves expression feedback labels in the left-brain
  maturity dimensions; the live feedback records show
  `feedback_rating=too_mechanical` rather than `unknown`.

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
  - right_brain_expression.adapter_request_count
  - right_brain_expression.adapter_delivery_mode
  - right_brain_expression.outcome_count
  - right_brain_expression.outcome_internal_marker_count
  - right_brain_expression.latest_outcome_policy_version
  - right_brain_expression.latest_outcome_silent
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
external_review: "required before broadening scheduled expression beyond the current test-host owner-configured path or adding new LLM bounded-live surfaces"
```

## Current Evidence

The current code and monitor support a safe observation path plus a test-host
formal expression baseline:

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
- Owner review can list speak/would-send items and P1-R slice 2 renders
  bounded expression previews for shown Wandering payload refs. Live monitor
  reports `speak_item_count=2`, `speak_expression_preview_count=2`, and
  `speak_expression_preview_missing_count=0`.
- Governance feedback consumes deployed expression feedback summaries; final
  Hermes-agent outcomes and one owner reaction are now linked in the ledger.
  The remaining gap is reaction volume and cadence/prompt evaluation, not
  outcome recording itself.
- The Hermes-agent adapter is now a real runtime path, not only a contract:
  `hermes cron run memory-os-right-brain-expression` executes the helper in
  agent mode (`--script`, no `--no-agent`), deliver target `origin`, and writes
  adapter request evidence without raw body or direct send from Memory-OS.

Therefore v0.1 should be described as:

```text
right-brain observation shell: implemented
formal low-frequency Hermes-agent expression path: implemented on test host
expression feedback -> proposal -> owner approve -> OpsGate report-only
  -> explicit expression_policy apply: implemented on test host (policy_version=1)
expression outcome ledger: implemented on test host
outcome -> owner feedback linkage: implemented on test host
owner reaction volume / cadence evaluation: still thin and not mature
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
| SpeakGate | Decide whether an expression draft is silent, scheduled-allowed, blocked, would-send observation, or exceptional permission-required. | P1-R slice 1 routes new cognitive-loop Wandering output through `SpeakGateModule.evaluate_wandering_output()` and records evaluated/missing decision monitor fields. Historical reports can still contain Wandering artifacts without SpeakGate decisions. | Mandatory decision for every non-silent expression draft. | The current gap is not initial wiring or outcome recording; it is real owner reaction volume, cadence/prompt evaluation, and production cadence. Historical missing evaluations remain evidence of the old wiring, not the current new-cycle path. |
| Owner Review for expression | Let the owner judge expression quality and exceptional send permission. | Owner review resolves shown speak/would-send payload refs into bounded expression previews and action tokens. Final Hermes-agent outcomes can now be referenced by `expression:<outcome_id>` or `expression:latest_outcome` and are resolved before owner-action idempotency. | Show bounded expression preview, why it appeared, delivery tier, and stable token if action is needed. | The remaining gap is not preview visibility or outcome linkage; it is accumulating enough real owner reaction volume to judge policy/prompt/cadence quality. |
| Expression feedback | Convert owner judgment into bounded evidence. | Expression quality labels and owner/Hermes feedback tokens are deployed; records are written to `expression_feedback_ledger.jsonl`, now with optional `outcome_id`, `request_id`, `policy_version`, and monitor-visible linked/missing counts. | `like`, `too_mechanical`, `too_frequent`, `boundary_private`, `off_voice`, `mute_period` into expression feedback ledger; no raw expression body is copied into the feedback record. | Feedback can now drive an owner-reviewed `expression_policy` proposal and explicit policy apply. The remaining gap is reaction volume and cadence/prompt evaluation, not raw feedback capture or linkage. |
| GovernanceFeedback / SelfEvolution backflow | Turn expression outcomes into policy/prompt/frequency proposals. | GovernanceFeedback consumes expression feedback as bounded evidence; EvidenceScoring now counts outcome-linked expression feedback subjects; SelfEvolution identifies `expression_policy:too_mechanical` and same-day same-signal cadence-gates duplicate proposals. One expression policy has been explicitly applied to `right_brain_expression_adapter/policy.json` on the test host. | Bounded governance events and owner-reviewed proposals only, followed by OpsGate report-only review and explicit apply for proposal kinds with a bounded runtime target. | Owner reaction volume and cadence/prompt evaluation are still thin; the measurable path exists, but mature expression learning needs more real feedback and policy evaluation. |

The current right-brain chain is therefore:

```text
event summaries
-> household digest
-> deterministic Wandering output
-> SpeakGate decision for new cognitive-loop output
-> would-send / blocked / silent observation artifact
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

Tier 2 is implemented as a test-host baseline, not yet a mature product loop.
The current deployed path is:

```text
Memory-OS bounded context + expression policy
-> Hermes cron agent turn (`deliver=origin`)
-> Hermes agent final wording or [SILENT]
-> owner-visible low-frequency expression
```

What remains open is the closure evidence after delivery: final expression
outcome ledger, owner reaction/feedback volume, and module-level cadence
reporting. Memory-OS still must not own platform transport or conversation
recovery.

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

### Hermes-Agent LLM Capability Design

Right-brain expression uses LLM capability through Hermes agent, not through a
Memory-OS-owned model runtime. The active contract is:

| Capability surface | LLM owner | Memory-OS role | Mode | Allowed output | Forbidden output |
| --- | --- | --- | --- | --- | --- |
| `right_brain_expression` | Hermes agent / host runtime | Provide bounded context, policy, source refs, and record adapter request/outcome evidence | `bounded-live` for expression wording only | short expression text or `[SILENT]` | execute, route, approve, write memory/identity, expose raw body |
| `deep_reflection_reflective_adapter` | Future Hermes agent adapter if approved | Provide bounded reflection substrate and store report/proposal evidence | `report-only` or `proposal-only` | analysis, carryover seed, proposal candidate | direct context injection, identity write, policy write, send |
| `low_clue_recall_judge` | Hermes configured judge adapter | Provide bounded candidate titles/metadata | `report-only`; future `bounded-live` only inside `ambiguous_recall` ranking | duplicate/merge/rank/title advice | hard ingress override, direct resume, approval, send/execute/write |
| `left_brain_semantic_advisor` | Future Hermes agent/governance adapter if approved | Provide bounded score evidence and receive explanation/proposal suggestions | `report-only` or `proposal-only` | explanation, risk notes, proposal suggestion | replace auditable feature scoring, mutate proposal state, execute |

Mode definitions:

- `report-only`: LLM output is written as evidence and cannot change live state.
- `proposal-only`: LLM output may create an owner-reviewed proposal, but cannot
  apply the change.
- `bounded-live`: LLM output affects only the declared bounded surface. For
  right-brain expression that means wording or `[SILENT]`; it does not include
  transport, approval, execution, memory write, route override, or policy write.

Required monitor fields for every LLM surface:

```text
llm_surface
llm_owner
mode
request_count
latest_status
fallback_count
raw_body_included_count
actual_send
actual_execute
actual_identity_write
actual_unapproved_crystallized_approval
bounded_live_scope
```

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

## Prototype-Informed Runtime Plan

Read-only inspection of `10.20.2.88` shows the production-like right-brain
shape already exists in Hermes/Sannai:

- Sannai fixed free-time jobs run at `09:00`, `13:00`, `17:00`, and `21:00`
  with `deliver=origin`.
- Sannai afterglow checks run at `12:00`, `16:00`, and `20:00` with
  `deliver=origin`.
- Sannai random heartbeat is generated by a profile-local no-agent script,
  creates one-shot `deliver=origin` jobs, and treats `[SILENT]` as a valid
  outcome.
- Profile-local background maintenance uses `deliver=local` / no-agent scripts
  for treasure index, daily digest, weekly consolidation proposal, and memory
  journal.

Memory-OS must not copy this profile-specific behavior directly. Sannai is a
companion profile with its own voice, cadence, and relationship contract.
Memory-OS needs a profile-agnostic right-brain expression substrate:

```text
bounded memory view
-> Hermes-agent expression prompt or bounded expression adapter
-> ExpressionDraft(text_preview, source_refs, feeling_tags, risk_flags, silence_reason)
-> SpeakGate decision
-> Hermes origin delivery only when scheduled/owner-configured
-> ExpressionFeedbackLedger
-> GovernanceFeedback / SelfEvolution proposal
-> owner approve/apply gate
```

Implementation slices:

Completed baseline slices:

1. `P1-R.3` - Expression draft surface:
   - create a bounded `ExpressionDraft` artifact;
   - support `[SILENT]` as first-class output;
   - no execution tools, no raw private body, no owner-visible send.
2. `P1-R.4` - Hermes-agent expression adapter:
   - use Hermes as the interaction/LLM owner;
   - Memory-OS supplies bounded context and stores the draft;
   - Memory-OS does not become the conversation agent.
3. `P1-R.5` - SpeakGate mandatory decision:
   - every non-silent draft gets `scheduled_allowed`,
     `scheduled_blocked`, `would_send`, or `permission_requested`;
   - monitor reports missing decisions as P1.
4. `P1-R.6` - Owner feedback and backflow:
   - `like`, `too_mechanical`, `too_frequent`, `boundary_private`,
     `off_voice`, and `mute_period` become expression feedback records;
   - feedback may only produce prompt/policy/frequency proposals.
5. `P1-R.7` - Scheduled expression opt-in:
   - borrow Sannai's ownership boundary, not its exact schedule or voice;
   - Hermes cron/origin owns schedule and delivery;
   - Memory-OS provides bounded stdout/draft state and monitor evidence.

Current runtime has produced a Hermes-origin expression on the test host without
boundary violations, recorded the final outcome, and linked one owner feedback
record to that outcome. Do not call Tier 2 mature until owner reaction volume
and cadence/prompt evaluation evidence are sufficient.

## Roadmap Placement

This becomes P1-R in the active roadmap:

```text
P1-R - Right-Brain Expression Closure Contract And Implementation Plan
```

P1-R has completed the first runtime outcome-feedback baseline. The next work
item is reaction volume and cadence evaluation: collect more real owner
feedback on Hermes-agent outcomes and verify policy/prompt/cadence proposals
remain useful, bounded, and non-duplicative without reimplementing Hermes
transport.
