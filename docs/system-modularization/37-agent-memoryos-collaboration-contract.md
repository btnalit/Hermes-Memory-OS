# 37 - Agent / Memory-OS Collaboration Contract

Status: design contract; no new execution capability
Date: 2026-05-26
Scope: Hermes agent interaction with Memory-OS review, proposal, feedback, and
context surfaces

## Purpose

Memory-OS is now able to produce owner-review digests, action tokens, bounded
review surfaces, and auditable owner actions. The next risk is not missing
state machinery. The risk is treating Hermes agent as a rigid tool caller
instead of the interactive partner that should help the owner understand and
act on Memory-OS output.

This document defines that collaboration boundary.

It does not add execution capability. It defines how Hermes should read,
explain, ask, suggest, and call existing Memory-OS tools without taking over
owner decisions.

## Preflight

```yaml
source_of_truth:
  - 29-memory-os-module-integration-contract.md
  - 32-active-roadmap-and-gates.md
  - 36-module-closure-matrix.md
  - 07-validation-report-10.20.3.200.md
finding_type: contract gap
owning_seam: agent collaboration / owner review / Memory-OS tool surface
reverse_scope: Hermes owns owner interaction; Memory-OS owns bounded tools,
  state machines, audit, and monitor evidence
equivalent_contract_or_project_contract: 29-series contract plus RH-36 closure
  matrix
evidence_loop: design reconciliation and future live owner-review smoke
monitor_or_validation_fields:
  - review_reply_tool_input_mode
  - reply_fallback_used_count
  - gateway_hook_registered
  - owner_review_surface_ok
  - raw_body_included_count
  - boundary_true_count
promotion_signal: Hermes can answer owner review questions with bounded
  context, ask when ambiguous, and call structured Memory-OS tools only after a
  definite owner intent
stop_or_rollback_signal: Memory-OS replaces Hermes conversation with gateway
  interception, rigid parsing, transport ownership, or automatic decisions
external_review: recommended before changing model-facing tool schema or live
  owner-review behavior
```

## Boundary

Hermes agent owns:

- natural-language owner interaction;
- deciding when to ask for clarification;
- explaining Memory-OS review items in the owner's language;
- making non-binding suggestions to the owner;
- selecting and calling Memory-OS tools when intent is definite;
- user-visible acknowledgement and recovery guidance.

Memory-OS owns:

- bounded review context;
- stable action tokens;
- deterministic state machines;
- OwnerActionProcessor;
- audit, attribution, monitor, and validation evidence;
- hard no-send/no-execute/no-unapproved-crystallization boundaries.

## How Hermes Reads Review Context

Hermes should use bounded Memory-OS surfaces before answering review questions:

| Owner question | Preferred Memory-OS surface | Boundary |
| --- | --- | --- |
| "还有哪些 / 下一页" | `memory_os_review_surface` with `next_page` | read-only |
| "展开 R3 / 这个是什么" | `memory_os_review_surface` with `detail` | read-only |
| "这个 proposal 后续是什么" | proposal follow-up review surface | report-only unless explicit apply gate |
| "我刚才批了什么" | owner action/review status surface | read-only summary |
| "这个能执行吗" | OpsGate/manual follow-up surface | report-only until explicit execution apply |

Hermes should not infer private details from raw session files or Memory-OS
internal ledgers. If a bounded surface cannot answer the owner question, Hermes
must say what is missing and ask a narrow follow-up.

## How Hermes Explains Owner Questions

Hermes may translate Memory-OS artifacts into human language:

- what the item is;
- why Memory-OS surfaced it;
- what approving/rejecting/allowing/marking feedback will do;
- what it will not do;
- what evidence is available;
- what remains uncertain.

Hermes must keep the distinction clear:

```text
approve candidate -> owner-approved crystallized memory
approve proposal  -> approved follow-up only, not execution
allow speak once  -> one expiring permission ticket, not default sending
feedback mark     -> feedback ledger first, not live tuning
```

## Suggestions Are Not Decisions

Hermes may propose an action to the owner when the bounded review context is
sufficient:

```text
建议: reject, because this proposal is duplicate of an already approved
follow-up and approving it would add no new execution path.
```

But Hermes must not apply that suggestion unless the owner gives a definite
action. Suggested wording should preserve owner control:

```text
我建议 reject。你可以回 "reject" 或直接使用这条 token 命令。
```

Hermes must not batch-approve, batch-reject, or change Memory-OS state from its
own judgment.

## Structured Tool Calls

Primary owner-action calls use structured fields:

```yaml
tool: memory_os_review_reply
action: "<approve | reject | allow | feedback>"
action_token: "oa_<stable token>"
rating: "<useful | irrelevant | too_mechanistic | missing_context | overconfident | needs_specific_recall | null>"
owner_utterance: "<optional bounded owner text for audit/debug>"
```

Rules:

- `action_token` is the executable identity.
- Display anchors such as `A1/R1/F1` are visual labels only.
- The model-facing tool schema should not expose text-first `reply` as the
primary path. Compatibility fallback may exist for old CLI/tool callers, but it
must be monitored and deprecated.
- If Hermes cannot resolve a stable token from the visible digest or bounded
review surface, it must ask a clarification instead of calling the action tool.

## When Hermes Must Ask

Hermes must ask a clarification when:

- the owner gives a bare token without action and the action is not obvious;
- the owner gives an action without a resolvable stable token;
- multiple visible review items could match;
- the target token is stale, already acted, or missing from the recorded digest;
- the requested action would imply execution, deletion, identity write, or
  route tuning rather than review-state change;
- the owner asks for a batch action without a bounded batch review surface;
- the bounded review context is insufficient to explain the consequence.

## When Memory-OS Must Stay Report-Only

Memory-OS surfaces are report-only when:

- the output is analysis, scorecard, monitor trend, or proposal explanation;
- the item is an approved proposal follow-up before an explicit OpsGate/manual
  execution apply gate;
- the owner gives feedback that has not passed a later bounded apply gate;
- an LLM judge contributes classification, dedupe, or ranking evidence in
  report-only mode;
- a gateway/provider hook sees an owner-review command but the Hermes agent did
  not call the structured tool.

Report-only output may be shown, summarized, or logged. It must not mutate live
state except for its own bounded evidence ledger.

## Forbidden Patterns

- Memory-OS directly owns owner conversation.
- Gateway pre-dispatch hooks become the primary owner-action path.
- Memory-OS accepts display anchors such as `approve A1` as durable identity.
- Hermes calls Memory-OS with no stable token and relies on Memory-OS to guess.
- Approval causes execution.
- Feedback immediately changes live routing or scoring.
- Agent suggestions mutate state without owner confirmation.
- Raw private transcript bodies appear in review context.

## Monitor And Follow-Up Requirements

The following follow-ups are required before this contract can be called mature:

| Follow-up | Required signal |
| --- | --- |
| reply fallback deprecation | `reply_fallback_used_count`, structured-call count, fallback stop threshold |
| gateway hook safety boundary | monitor proves gateway hook is safety-only and not the primary owner-action path |
| candidate/proposal timestamps | producer-created `created_at`, `unknown_timestamp_count` trend |
| approved proposal follow-up | owner-visible follow-up surface and explicit apply gate, `actual_execute=false` |
| RH-34/RH-35 family map | readable owner-governance subsystem map before public productization |

## Acceptance For RH-37

RH-37 is complete when:

- this contract is linked from the 29-series contract;
- the roadmap lists RH-37 and its follow-up tasks;
- RH-36 classifies the collaboration contract as a governed surface;
- no runtime behavior changes are claimed from this document alone.

Code changes for the follow-ups must be done as separate P1/P2 work items with
their own preflight, tests, monitor fields, and live evidence where applicable.
