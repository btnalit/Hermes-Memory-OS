# 34 - Owner Review Digest And Action Workflow

Status: RH-35.1 OwnerActionProcessor, RH-34a metadata-only channel resolver
and digest preview, RH-34b Memory-OS export eligibility gate, RH-34c review
queue aging policy, RH-34d one-shot Hermes send compatibility smoke, RH-34e.1
Review Digest Renderer, RH-35.2 Owner Reply Parser, RH-34e Hermes Cron Owner
Review Integration, RH-35.8 agent-mediated owner reply tool, and RH-35.9
structured owner-review tool contract are deployed on `10.20.3.200`. RH-34e is
Hermes-owned recurring delivery, not a Memory-OS-owned transport. The test-host
installer now enables the Hermes cron owner-review digest by default in agent
mode; Memory-OS only renders a bounded review brief, display anchors, stable
action tokens, and parser/processor state transitions. Hermes owns the final
Chinese wording and interactive owner conversation.
Date: 2026-05-25
Scope: RH-34 Daily Owner Review Digest, RH-35 Owner Action Processor, and the
owner-facing governance loop needed to make Memory-OS usable without daily SSH
operations.

## Current Architecture Truth

This section is the current owner-review design authority. Later sections
preserve historical findings and superseded slices.

Current flow:

```text
Memory-OS modules produce candidates / proposals / speak-permission items
-> Owner review queue + aging projection
-> Review Digest Renderer creates owner-readable bounded digest text
-> Hermes cron delivers the digest through the owner/home channel
-> Hermes agent handles the owner's interactive reply
   - resolves natural phrasing from visible digest context when unambiguous
   - asks a clarification when the target or action is ambiguous
   - calls memory_os_review_reply with structured action + stable oa_ token
-> Memory-OS OwnerActionProcessor applies the deterministic state transition
-> audit / monitor / feedback surfaces record the result
```

Boundary:

- Hermes owns user-facing interaction, clarification, acknowledgement, platform
  delivery, retry/cooldown, and channel semantics.
- Memory-OS owns bounded digest content, stable action tokens, review tools,
  OwnerActionProcessor state changes, audit, monitor, and no-send/no-execute
  boundaries.
- Display anchors (`A1/R1/F1`) are UI labels. Hermes may use them as
  context clues; Memory-OS tools/state machines execute only stable `oa_`
  action tokens.
- Gateway pre-dispatch or provider lifecycle hooks are safety nets only. They
  may prevent memory pollution, but they must not be the primary owner-action
  path or surface user-visible `gateway_ingress_error` for valid review tasks.
- `memory_os_review_reply` is structured-first in RH-35.9:
  `action + action_token + optional rating + optional owner_utterance` is the
  only model-facing agent tool contract. The provider still accepts hidden
  `reply` fallback inputs for CLI/legacy compatibility, but `reply` is not
  exposed in the model-facing schema.

## Problem

Memory-OS now produces meaningful artifacts:

- crystallized review candidates;
- proposal queue candidates;
- wandering / speak-gate would-send artifacts;
- DeepReflection cards and carryover;
- evidence scores, governance feedback, and self-evolution dry-run proposals;
- monitor WARN/FYI trend signals.

The current system exposes most of this through CLI, status JSON, module
artifacts, and monitor reports. That is useful for engineering, but too heavy
for normal owner use. If the owner must SSH into the host and run CLI commands
to review every candidate or proposal, the system will accumulate artifacts
without feedback.

This is a product-level gap, not only a CLI gap:

```text
cognition modules produce artifacts
-> artifacts need owner review
-> owner has no low-friction daily review channel
-> review queue grows
-> feedback does not return to memory routing / scoring
```

## Live Evidence

Read-only inspection of `10.20.3.200` on 2026-05-25 showed:

```text
counts:
  events=229
  working_items=161
  crystallized_candidates=161
  crystallized_records=0

proposal_queue:
  candidate_count=15
  state_counts={"approved_for_proposal": 1, "candidate": 14}

wandering_mind:
  would_send_count=11

speak_gate:
  would_send_count=0
  actual_send=false

DeepReflection:
  analysis_artifact_count=18
  report_count=18
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false

existing owner/review ledgers:
  no owner_actions ledger
  no review_queue ledger
```

Interpretation:

- The system is generating review-worthy artifacts.
- Hard boundaries are intact.
- There is no owner-facing state machine that turns review into durable state
  transitions and feedback.

## RH-34 - Daily Owner Review Digest

Purpose:

Generate a bounded owner review brief on an owner-configured schedule and
channel. The digest is a review frontend, not a free-form proactive agent
message.

### Boundary Correction - 2026-05-25

Review of the production Hermes prototype on `10.20.2.88` showed that Hermes
already owns the owner-channel transport and schedule layer, and separately
owns an internal AI-agent mailroom/mailbox layer:

- `send_message_tool` and `hermes send` route through Hermes platform adapters;
- `hermes cron --deliver` owns scheduled delivery to home channels;
- the mailbox/mailroom adapter is for AI-agent-to-AI-agent communication and
  already enforces internal anti-spam / anti-loop controls such as
  `final_only`, `proactive_send_enabled`, `no_reply_marker`,
  `auto_wake_cooldown`, `owner_pause_file`, and thread/room rate limits.

Therefore Memory-OS must not grow a parallel recurring delivery system.

Correct ownership:

```text
Memory-OS:
  - select review-worthy items
  - render bounded owner-review payloads
  - prove raw-body-free / eligible-for-owner-review
  - map owner replies to OwnerActionProcessor actions
  - record audit/monitor evidence

Hermes:
  - schedule jobs
  - choose and deliver to the configured owner channel
  - apply platform send adapters, cooldowns, rate limits, and no-reply/final-only gates
  - handle delivery errors and home-channel configuration
  - keep AI-agent mailroom/mailbox controls separate from owner-channel delivery
```

RH-34d's real-send smoke remains useful as a compatibility proof that Hermes'
existing send path can deliver a bounded Memory-OS digest. It is not the
production architecture for recurring review delivery.

Joy/agent phrasing may be used later to turn bounded review JSON into a more
natural digest, but it must consume only Memory-OS-provided bounded payloads
and may not approve, execute, crystallize, or mutate state.

### Cognitive Output Closure Map

The left-brain and right-brain modules should not all be treated as one generic
"review item" stream. Each output type needs a specific closure path:

| Output type | Producing modules | Approval / review path | Feedback backflow |
| --- | --- | --- | --- |
| Execution proposal | `ops_gate`, `proposal_queue`, `evidence_scoring`, `self_evolution`, DeepReflection optional proposals | OwnerActionProcessor `approve_proposal` / `reject_proposal`; approval creates a proposal/execution-ticket state only, never execution | proposal class weighting, governance feedback, future OpsGate decisions |
| Expression / proactive-send policy item | `wandering_mind`, `speak_gate`, DeepReflection wandering seeds | Ordinary conversation and configured digest delivery do not need per-message approval. Only out-of-policy proactive sends or externally visible expression requests may require an owner action such as `allow_speak_once`. Hermes owns actual transport. | speak policy trend, wandering seed scoring, review burden |
| Long-term memory candidate | `inner_drive`, `digest_consolidation`, DeepReflection optional candidate output, `self_evolution`, proposal-derived candidates | OwnerActionProcessor `approve_candidate` / `reject_candidate`; only approval may create a crystallized record | candidate scoring, MemorySources, RH-30 feedback aggregation |
| Context / reflection injection | Conversation Carryover, DeepReflection carryover cards | No per-card approval in v0; bounded by RH-26/RH-28 projection, MemorySources attribution, and monitor warnings | relevance feedback, source-class distribution, future bounded router changes |
| Analysis / monitor evidence | DeepReflection analysis, evidence scoring, module artifact summaries, monitor WARN/FYI trends | No approval; operator/owner review may create feedback or future work items | roadmap gates, monitor thresholds, review digest FYI |

DeepReflection outputs are explicitly split:

- carryover cards -> context projection only, no owner approval in v0;
- analysis artifacts -> monitor/evidence only;
- optional proposals -> proposal approval path;
- wandering seeds -> expression policy / proactive-send gate;
- optional memory candidates -> candidate approval path.

Candidate review items must carry `source_module` metadata where available.
The renderer should explain the source in owner-readable language, for example:

```text
Suggested because Inner Drive saw this pattern repeatedly.
Suggested because DeepReflection summarized a recurring trend.
Suggested because Self-Evolution produced a dry-run improvement candidate.
```

This source label helps the owner judge the item without exposing raw private
message bodies or internal implementation fields as the primary text.

### Mailbox / Mailroom Boundary

The Memory-OS `mailbox` module is not a left-brain or right-brain cognition
module. It is also not the owner review delivery channel. It is a
transport-adjacent status surface for Hermes' internal AI-agent
mailroom/mailbox communication path.

Rules:

- `mailbox` does not approve, reject, execute, crystallize, or create feedback;
- it may expose internal mailroom would-send / blocked-send / loop-control
  status metadata;
- it must not be treated as the owner digest transport or owner approval path;
- Hermes cron / send-message / platform adapters own owner-channel delivery;
- Hermes mailbox/mailroom owns AI-agent-to-AI-agent anti-spam, anti-loop,
  final-only, pause, no-reply marker, cooldown, and rate-limit behavior.

### Current Closure Gap

The deployed test host proves the cognition loop is producing artifacts, but
owner governance is not yet closed:

```text
crystallized_candidates=161
crystallized_records=0
review_queue.pending=186
raw_action_required=175
effective_action_required=14 after aging
owner_actions=0 before real owner-action testing
```

This means the modules are not "done" from the owner perspective. They are
running, bounded, and observable, but most action-worthy outputs are still
inside Memory-OS until three missing pieces are completed:

1. RH-34e.1 Review Digest Renderer - turn artifacts into owner-readable
   questions, suggested actions, reasons, consequences, display anchors, and
   stable action tokens.
2. RH-35.2/RH-35.5/RH-35.8 Owner Reply Parser and provider tool - map explicit token commands such as
   `memory approve oa_<token>` or `memory reject oa_<token>` to
   OwnerActionProcessor through the Hermes agent tool path, without frontend
   mutation or gateway hard interception.
3. RH-34e Hermes Cron Owner Review Integration - let Hermes schedule and
   deliver the bounded digest through the owner-configured channel.

Priority:

```text
Renderer first: without readable items, sending is useless.
Reply parser second: without action parsing, reading is not governance.
Hermes cron integration third: without the first two, recurring delivery just
creates noise; with them, it becomes the daily owner review loop.
```

### RH-34f - Owner Home Channel Autodiscovery

Finding:

`10.20.3.200` accepts `hermes cron create --deliver telegram`, but open-source
users may use another Hermes frontend. The installer must not hardcode Telegram
for every deployment.

Hermes evidence:

```text
hermes cron create --help:
  --deliver DELIVER  Delivery target: origin, local, telegram, discord,
                     signal, or platform:chat_id
```

Decision:

- Memory-OS does not implement platform delivery discovery itself.
- The shell installer uses `--owner-review-cron-deliver auto` by default.
- `auto` resolves to `telegram` only for the controlled `--test-host` preset.
- `auto` resolves to `origin` for ordinary non-interactive installs, so Hermes
  owns origin/home-channel delivery semantics.
- Interactive installs can choose `origin`, `telegram`, `discord`, `signal`, or
  an explicit `platform:chat_id`.
- `local` remains blocked for owner review because it is not owner-channel
  delivery.
- The recurring enable gate rejects unresolved `auto`; the shell installer must
  resolve it before apply.

Stop signal:

- installer creates an owner review cron job with `deliver=telegram` on a
  non-test-host install without explicit owner/operator selection;
- recurring enable gate accepts `deliver=auto` without resolving it;
- owner review delivery uses `local`;
- Memory-OS parses private session bodies to infer a channel.

### RH-34g - Digest Renderer Budget And Candidate Quality

Finding:

The first Telegram-delivered digest proved transport, but the message was too
long and the final review item was truncated by the owner-facing channel. It
also showed transcript-like candidate text such as `User: ... | Assistant: ...`
as an approvable long-term memory candidate, which is not a good owner review
surface.

Decision:

- Default digest limits are tightened to `3` Action Required, `2` Review
  Suggested, and `2` FYI items unless overridden.
- RH-34i supersedes this for recurring owner push delivery: the default Hermes
  cron helper uses `agenda` mode and pushes only Action Required decisions plus
  true alerts. Review Suggested and FYI remain available through pull-based
  review/debug surfaces, not daily Telegram noise.
- Rendered owner-review text has a smaller Telegram-safe budget and must omit
  whole items rather than cut an item in the middle.
- Transcript-like crystallized candidates are downgraded to FYI
  `candidate_cleanup` signals. They are not shown as `approve/reject` memory
  candidates until a consolidation step turns them into a stable memory
  statement.
- Candidate cleanup FYI items expose source module and reason, not raw
  transcript bodies.

Stop signal:

- rendered digest truncates inside a review item;
- transcript/event excerpts appear as owner-approvable long-term memory;
- digest primary text is dominated by internal labels or raw conversation
  snippets;
- `text_has_internal_schema=true`, `raw_body_included=true`, or
  `unapproved_send_count>0`.

### RH-34i - Owner Agenda Push Mode

Finding:

The 2026-05-26 Telegram digest showed `pending=218`,
`review_suggested=37`, and `fyi=169` in the recurring owner message. That was
correct for an operator/debug review surface, but wrong for a mature daily
owner agenda. It made the push channel carry backlog anxiety instead of the few
items that actually need owner action.

Prototype reference:

10.20.2.88 uses Hermes cron `deliver=origin` for owner-facing reports and
keeps bulk intake/generation/local maintenance in `deliver=local` or no-agent
pipelines. Memory-OS should follow the separation, not push all queue classes
to the owner every day.

Decision:

- The recurring Hermes cron helper defaults to `agenda` mode.
- `agenda` mode renders Action Required decisions and future true alerts only.
- Review Suggested and FYI are pull surfaces: owner/Hermes can ask
  `还有哪些`, `下一页`, `查看建议项`, or use the review surface tool.
- Ops/debug summaries may still show pending/review/FYI totals, but they must
  not be the default recurring owner push.
- If agenda mode has no Action Required or true alert content, helper stdout is
  empty so Hermes cron stays silent.

Stop signal:

- recurring owner digest includes bulk pending/review/FYI totals as the primary
  message;
- recurring owner digest sends only suggested/FYI content with no decision or
  true alert;
- helper uses test/debug limits as the default product agenda.

### RH-34j - Proposal Agenda Eligibility

Finding:

The first RH-34i Telegram agenda became shorter but still showed three
`Self-Evolution dry-run proposal` items. The owner could see commands but could
not see what was being approved. Live inspection showed these were historical
template proposals with generic bodies such as "Use the highest evidence signal
to prepare a reviewed governance improvement." They are not mature approval
items.

Decision:

- A proposal can enter the recurring owner agenda only when it has bounded,
  owner-readable content: what changes, why it changes, and what follow-up
  means.
- Generic/template SelfEvolution proposals are downgraded to Review Suggested
  maturation items and have no approve/reject action commands in the rendered
  review item.
- Concrete proposals render a bounded `proposal_detail` line so Hermes can
  explain the actual proposal, not just its title.
- Hermes cron agent delivery must preserve the proposal detail as approval
  content. If Script Output includes `内容:` with `具体改动`, `证据`,
  `验收标准`, `后续状态`, or `边界`, the delivery prompt must not summarize it
  down to only a title and action token.
- Raw/private/transcript-looking proposal bodies are not shown as details.

Stop signal:

- recurring owner agenda asks owner to approve a proposal whose visible content
  is only a generic title;
- template SelfEvolution proposals remain `Action Required`;
- proposal details include raw transcript/private body text.

### RH-34a - Owner Review Channel Resolver

The digest must not hardcode Telegram as the only owner review channel.
Telegram is the current test-host owner channel, but open-source users may use
CLI, Web, Slack, WhatsApp, WeCom, Matrix, or another Hermes entrance.

After the boundary correction, the resolver is not a transport chooser. It is a
metadata-only readiness reporter and installer aid. It should prefer Hermes'
existing owner/home-channel configuration and never bypass Hermes delivery
configuration.

The resolver reports a review target using metadata only:

```text
explicit owner config
-> Hermes home-channel / cron delivery metadata
-> owner-verified default review channel metadata
-> safe CLI/dashboard-only fallback
```

It must not read private message bodies to choose the channel.

Resolver inputs:

- explicit Memory-OS owner review config;
- Hermes profile id and owner id;
- session metadata from SessionMirror / Hermes sessions;
- platform availability;
- direct-message versus group/channel flag;
- last owner-authenticated activity timestamp;
- previous digest delivery success/failure metadata.

Resolver output:

```yaml
schema_version: memory-os.owner_review_channel.v0
status: selected | dry_run_only | unresolved | disabled
reason:
profile:
owner_id:
channel: telegram | cli | web | slack | whatsapp | wecom | matrix | unknown
target_ref:
direct_message: true | false
last_owner_activity_at:
configured_by_owner: true | false
fallback_used: true | false
```

Selection rules:

- explicit config always wins if it points to an available, owner-verified
  channel;
- Hermes home-channel / cron delivery metadata should be reused before
  inventing Memory-OS-specific channel selection;
- direct owner conversation metadata may suggest a channel, but automatic send
  still requires explicit owner config or Hermes cron delivery config;
- group/channel delivery is disabled by default and must be explicitly enabled;
- if multiple owner direct channels are active, pick the configured default; if
  there is no default, generate a digest preview but do not send;
- if no safe channel is resolved, digest generation may continue in dry-run, but
  delivery is skipped and monitor reports `review_channel_unresolved`.

This keeps the product portable:

```text
same review queue + same OwnerActionProcessor
different owner channel frontend
```

Initial mode:

```yaml
enabled: false
mode: dry_run
channel: cli
schedule: daily
raw_body: false
max_action_required: 3
max_review_suggested: 5
max_fyi: 5
actions_enabled: false
```

Implementation note:

- RH-34a resolves owner review channels from explicit owner config or
  metadata-only Hermes `state.db` session rows.
- It intentionally does not parse `session_*.json` files because those files
  may contain private message bodies.
- If no safe metadata channel is found, it falls back to CLI preview and
  reports `status=dry_run_only`.

Daily owner surfaces:

| Surface | Contents | Owner burden rule |
| --- | --- | --- |
| Recurring agenda push | Action Required approvals/rejections and true alert items only | target <= 3 items/day; no backlog totals unless they are themselves an alert |
| Pull review surface | Review Suggested, additional Action Required pages, item detail, and expansion commands | owner/Hermes asks for it explicitly |
| Ops/debug summary | FYI trends, backlog counts, monitor totals, source skew, audit density | manual/weekly operator surface, not the default owner push |

Overflow strategy:

- rank Action Required by urgency and age;
- show the top `max_action_required`;
- include action-required overflow in agenda wording only when there are more
  decisions to process;
- do not silently drop overflow;
- stale overflow becomes monitor WARN, not more digest spam.

Owner absence strategy:

- no action for 3 days: mark items stale and keep them in the queue;
- no action for 7 days: monitor reports `review_queue_stale_owner_attention`;
- no automatic approval, rejection, execution, or send is allowed because the
  owner is absent.

Interaction v0:

- text based in the owner conversation;
- no Telegram inline keyboard requirement for v0;
- each digest item gets a short owner-facing anchor, for example `[A1]`
  for action-required items, `[R2]` for review-suggested items, and `[F1]`
  for feedback targets;
- anchors are display-only; they are not approval identity;
- every executable item also gets stable action tokens, for example
  `memory approve oa_<token>` and `memory reject oa_<token>`;
- Hermes agent should resolve interactive owner replies to a structured
  `action + action_token` tool call; provider text parsing is compatibility
  fallback and pollution guard, not the primary interaction path;
- if a reply cannot be resolved against a recorded digest action token or a
  reviewed stable target id, the processor must ask for clarification and must
  not guess;
- examples:
  - `memory approve oa_<token>`
  - `memory reject oa_<token>`
  - `memory feedback oa_<token> too_mechanistic`
  - `memory allow oa_<token>`
  - `snooze item_003 7d`

Boundaries:

- digest send is disabled by default;
- enabling digest send is a separate owner config decision;
- automatic channel selection can select only an owner-verified channel;
- digest content is bounded metadata and summaries only;
- digest does not print raw private message bodies;
- digest does not approve, reject, execute, send arbitrary content, or write
  crystallized memory by itself.

### RH-34b - Memory-OS Export Eligibility Gate

The gate is a Memory-OS export eligibility surface, not a channel adapter and
not a Hermes transport replacement.

It exists so Memory-OS can answer:

```text
Is this digest safe and eligible to be handed to Hermes for owner review?
```

It does not send anything and does not schedule anything. It reports `ready`,
`blocked`, or `disabled`.

Gate inputs:

- `owner_review.delivery_enabled`;
- `owner_review.channel`;
- `owner_review.target_ref`;
- owner channel resolver output;
- digest preview output;
- raw-body and boundary booleans.

Required conditions for `status=ready`:

- delivery is explicitly enabled by owner config;
- the channel resolver returns `status=selected`;
- the selected channel is configured by owner;
- digest preview contains no raw body;
- digest preview itself did not set `will_send=true`;
- all boundary booleans remain false.

Default state:

```yaml
owner_review:
  delivery_enabled: false
  delivery_adapter: none  # legacy one-shot smoke compatibility field
```

Default report:

```yaml
schema_version: memory-os.owner_review_delivery_gate.v0
status: disabled
ready_for_delivery: false
blocked_reasons:
  - delivery_not_enabled
  - delivery_adapter_not_configured  # applies to RH-34d one-shot smoke only
boundary:
  actual_send: false
  actual_execute: false
  actual_identity_write: false
  actual_unapproved_crystallized_approval: false
```

The deployed RH-34b/RH-34d code still reports `delivery_adapter` because the
one-shot smoke used it to call Hermes' existing send path. RH-34e recurring
integration should not add another Memory-OS delivery adapter; it should expose
a bounded render command for Hermes cron.

Claude / external review gate:

- required before enabling real owner-channel delivery on `10.20.3.200`;
- required before adding or wiring a channel adapter that can actually send;
- not required for disabled-by-default gate code, fixture tests, or monitor
  fields that keep `actual_send=false`.

### RH-34c - Review Queue Aging Policy

Live evidence from RH-34a/RH-34b showed:

```text
review_queue.pending=186
review_queue.action_required=175
digest_preview.action_required_shown=2 or 3
digest_preview.action_required_overflow=172 or 173
```

This is not a boundary failure. It is an owner-burden failure mode:

```text
If the first digest says "3 shown, 172 waiting",
the owner will not realistically review the queue.
```

Purpose:

Reduce cold-start review overload before enabling owner-channel delivery.
The aging policy changes digest/review priority projection only. It does not
approve, reject, delete, archive, execute, send, crystallize, or mutate the
underlying candidate/proposal/speak target state.

Core rule:

```text
aging changes "what is shown first"
aging does not decide "what is true"
aging does not close owner-review items
```

Initial deterministic policy:

| Item age / condition | Display priority | Notes |
| --- | --- | --- |
| new or recently refreshed, <= 7 days | Action Required | normal review surface |
| older than 7 days and no owner action | Review Suggested | still visible, lower burden |
| older than 30 days and no owner action | FYI / backlog trend | not a rejection |
| unknown timestamp | Review Suggested | conservative; do not hide |
| explicit owner-pinned or fresh monitor WARN | Action Required | future extension |

Implementation shape:

- compute `effective_priority` while building review queue / digest preview;
- preserve original `source_priority`;
- add `aging_reason` and `age_days` where known;
- never remove the item from `review queue`;
- expose raw and aged counts side by side.

Example fields:

```yaml
schema_version: memory-os.owner_review_aging.v0
enabled: true
raw_action_required_count: 175
effective_action_required_count:
aged_to_review_suggested_count:
aged_to_fyi_count:
unknown_timestamp_count:
oldest_action_required_age_days:
raw_body_included: false
canonical_state_changed: false
owner_action_created: false
```

Monitor fields:

- `review_aging.raw_action_required_count`
- `review_aging.effective_action_required_count`
- `review_aging.aged_to_review_suggested_count`
- `review_aging.aged_to_fyi_count`
- `review_aging.unknown_timestamp_count`
- `review_aging.raw_body_included`
- `review_aging.canonical_state_changed`
- `review_aging.owner_action_created`

Promotion signal:

- preview Action Required count becomes owner-reviewable without hiding the
  total backlog;
- aged items remain visible through queue/status/history;
- no owner action is created by aging;
- no canonical memory/proposal/speak state changes;
- monitor shows raw versus effective counts.

Stop signal:

- aging removes or closes a review item;
- aging changes candidate/proposal/speak canonical state;
- aging creates owner action records;
- aging hides backlog counts or overflow counts;
- digest no longer exposes that a backlog exists.

Implementation evidence:

```text
Local:
  python -m pytest -q
  -> 477 passed
  git diff --check
  -> pass

Remote test host:
  deployed to 10.20.3.200 with install_memory_os.sh --test-host
  gateway restart: not performed
```

Live smoke after deployment:

```text
owner_review_aging.schema_version=memory-os.owner_review_aging.v0
owner_review_aging.enabled=true
raw_action_required=175
effective_action_required=14
aged_to_review_suggested=161
aged_to_fyi=0
unknown_timestamp=161
raw_body_included=false
canonical_state_changed=false
owner_action_created=false

digest_preview:
  pending=186
  raw_action_required_total=175
  action_required_total=14
  action_required_shown=3
  action_required_overflow=11
  review_suggested_total=172
  will_send=false
  raw_body_included=false

delivery_gate:
  status=disabled
  ready_for_delivery=false
  actual_send=false
```

Interpretation:

- RH-34c reduced the first-digest owner burden from an unreviewable
  `action_required=175 / overflow=172+` to an effective
  `action_required=14 / overflow=11`.
- The raw backlog remains visible through `raw_action_required_count=175` and
  `pending=186`.
- The reduction is projection-only. It did not approve, reject, send, execute,
  crystallize, create owner action records, or mutate canonical memory.
- Because `effective_action_required=14` is still higher than the steady-state
  target of `<=3`, RH-34d can proceed only as a one-shot smoke after external
  review; recurring RH-34e remains blocked.

### RH-34d - One-Shot Real Send Smoke

The owner explicitly requires one visible real send test before calling the
delivery path usable. This is valid, but it must be a one-shot smoke, not daily
delivery.

Purpose:

Prove that the selected owner channel can receive exactly one bounded digest
message that the owner can see, while preserving opt-in and auditability.

Preconditions:

- RH-34c aging policy has reduced the first digest to a reviewable slice or has
  clearly shown the remaining burden;
- owner has explicitly configured the review channel and target;
- delivery gate reports `status=ready`;
- digest preview remains raw-body-free;
- external review has approved the live-send gate;
- owner explicitly triggers a one-shot smoke command.

Out of scope:

- recurring daily delivery;
- Telegram inline keyboard actions;
- automatic send from cognitive loop;
- free-form AI-generated notification text;
- group/channel delivery unless explicitly enabled by owner config.

Owner-approved send semantics:

The historical default remains "no send". RH-34d already produced one
owner-triggered compatibility proof through Hermes' existing send path. After
the 2026-05-25 boundary correction, the Memory-OS `deliver-once` command is
legacy smoke-only: it may record a bounded compatibility/smoke ledger entry,
but it must not call transport. Recurring and future real delivery must be
owned by Hermes cron/send.

Historical owner-approved send evidence remains distinguishable from
unapproved sends:

```yaml
owner_effect:
  owner_approved_digest_delivery: true
boundary:
  actual_unapproved_send: false
```

Do not treat a legitimate one-shot smoke as a hard-boundary violation. Do treat
any send without the delivery gate, owner config, and smoke command as a hard
failure.

Minimum delivery ledger:

```yaml
schema_version: memory-os.owner_review_delivery.v0
delivery_id:
digest_id:
owner_id:
channel:
target_ref:
mode: one_shot_smoke
created_at:
result: sent | dry_run | blocked | error | smoke_only
owner_effect:
  owner_approved_digest_delivery: true | false
boundary:
  actual_unapproved_send: false
  actual_execute: false
  actual_identity_write: false
  actual_unapproved_crystallized_approval: false
raw_body_included: false
```

Monitor fields:

- `digest_delivery.count_24h`
- `digest_delivery.last_result`
- `digest_delivery.owner_approved_send_count`
- `digest_delivery.unapproved_send_count`
- `digest_delivery.error_count`
- `digest_delivery.raw_body_included_count`

Historical RH-34d acceptance:

- one visible owner-channel message is received by the owner;
- delivery ledger records exactly one sent smoke;
- monitor reports owner-approved send count separately;
- `unapproved_send_count=0`;
- digest content remains bounded and raw-body-free;
- no owner action, proposal execution, or crystallized write occurs because of
  the send.

Current legacy smoke-only acceptance:

- `review deliver-once --owner-triggered --apply` does not call transport;
- result is `smoke_only`;
- ledger includes `legacy_smoke_only_use_hermes_cron`;
- `sent_count` does not increase;
- `unapproved_send_count=0` and `raw_body_included_count=0`.

Stop signal:

- the smoke sends more than one message;
- message goes to an unresolved, group, or non-owner target;
- delivery text includes raw private body;
- delivery bypasses `review delivery-gate`;
- delivery creates or applies owner actions automatically;
- monitor cannot distinguish owner-approved send from unapproved send.

Implementation:

- `plugins/memory/memory_os/owner_actions.py` owns the one-shot send state
  machine:
  - `owner_review_deliveries.jsonl` records the delivery ledger;
  - `review delivery-status` summarizes sent/skipped/error/duplicate counts;
  - historical RH-34d used `review deliver-once --owner-triggered --apply`
    for exactly one compatibility smoke;
  - current `review deliver-once` is legacy smoke-only and returns
    `legacy_smoke_only_use_hermes_cron` instead of calling transport;
  - `delivery_key` prevents repeated smoke records for the same smoke;
  - RH-34e recurring delivery must invoke Hermes cron/send with a bounded
    Memory-OS-rendered payload, not Memory-OS transport code.
- `plugins/memory/memory_os/cli.py` and the `memory-os-agent-os` shell alias
  expose `review delivery-status` and legacy `review deliver-once`.
- `scripts/memory_os_3_200_monitor.py` records delivery status separately from
  the delivery gate:
  - `owner_approved_digest_delivery_count`;
  - `unapproved_send_count`;
  - `raw_body_included_count`;
  - `sent_count`, `skipped_count`, `error_count`, `duplicate_ignored_count`.

Local verification:

```text
python -m pytest -q tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py \
  tests/scripts/test_memory_os_3_200_monitor.py
70 passed

python -m pytest -q
484 passed
```

Remote one-shot smoke on `10.20.3.200`:

```text
gate_status=ready
gate_ready=true
gate_blocked_reasons=[]
result_status=sent
result_dry_run=false
record.result=sent
record.raw_body_included=false
record.text_char_count=742
record.boundary.actual_unapproved_send=false
record.boundary.actual_execute=false
record.boundary.actual_identity_write=false
record.boundary.actual_unapproved_crystallized_approval=false
record.owner_effect.owner_approved_digest_delivery=true
delivery_status.sent_count=1
delivery_status.owner_approved_digest_delivery_count=1
delivery_status.unapproved_send_count=0
delivery_status.raw_body_included_count=0
```

The smoke temporarily enabled `owner_review.delivery_enabled=true` and
`delivery_adapter=hermes_owner_channel` with the configured owner channel,
then restored the prior config. Post-smoke monitor shows:

```text
OwnerDeliveryStatus.sent_count=1
OwnerDeliveryStatus.error_count=0
OwnerDeliveryStatus.unapproved_send=0
OwnerDeliveryStatus.raw_body_included=0
OwnerDeliveryGate.status=disabled
OwnerDeliveryGate.ready_for_delivery=false
OwnerDeliveryGate.delivery_enabled=false
```

Interpretation:

- RH-34d proves Hermes' existing send path can receive and deliver one bounded
  Memory-OS digest.
- It does not enable recurring delivery and does not make Memory-OS the owner
  of scheduling or transport.
- It does not create owner actions, approve candidates, execute proposals, or
  write crystallized memory.
- RH-34e remains blocked until external review accepts this evidence.

Post-boundary-correction smoke-only behavior:

```text
Current code:
  review deliver-once --owner-triggered --apply
  -> no transport call from Memory-OS
  -> records smoke-only/skipped compatibility evidence depending on gate state
  -> recurring delivery must use Hermes cron/send

Remote check on 10.20.3.200 with delivery gate disabled:
  status=skipped
  blocked_reasons=delivery_not_enabled,delivery_adapter_not_configured,
    review_channel_not_selected,review_channel_not_configured_by_owner
  sent_count remained 1 (historical smoke only)
  unapproved_send_count=0
  raw_body_included_count=0
```

### RH-34e - Hermes Cron Owner Review Integration

Recurring daily delivery is the product-facing end state of RH-34, but it must
be implemented through Hermes cron / Hermes delivery, not through a
Memory-OS-owned scheduler or transport.

Purpose:

Expose a Memory-OS review payload command that Hermes cron can call and deliver
through the configured owner channel.

Required prerequisites:

- RH-34c aging policy is deployed and monitor shows raw versus effective
  burden;
- RH-34d one-shot smoke proves Hermes can deliver one bounded Memory-OS digest;
- external review accepted the smoke as transport compatibility evidence;
- owner explicitly enables a Hermes cron delivery job, approves installer
  creation of that job, or uses the controlled test-host preset that enables
  the reviewed Hermes cron integration by default;
- Memory-OS export eligibility gate reports `status=ready`;
- digest preview remains bounded and raw-body-free;
- monitor can distinguish generated, skipped, delivered, and failed review
  payloads without raw bodies.

Correct integration shape:

```text
Hermes cron job:
  schedule: owner-selected daily window
  deliver: Hermes owner/home channel
  mode: agent mode, not --no-agent
  script:
    memory_os_owner_review_digest.py
  prompt:
    read Script Output, write the owner-facing digest in Chinese, preserve
    stable oa_ action tokens, do not approve or execute automatically

Memory-OS:
  helper calls review preview-digest and render-digest
  returns a bounded agenda brief and machine-readable anchors on stdout
  returns empty stdout for no meaningful content
  does not call send_message_tool in the recurring path
```

The integration must use Hermes cron `--script --deliver` in agent mode. This
matches the 10.20.2.88 pattern where scripts produce evidence and Hermes
agent applies prompt/skill judgment before speaking to the owner. `--no-agent`
is only appropriate for watchdog-style direct alerts, not owner-review
governance. Memory-OS therefore installs a helper script, a status command, and
a recurring enable gate. The interactive installer asks before enabling the
job. The test-host preset enables it by default because `10.20.3.200` is the
controlled integration host; `--no-enable-owner-review-cron` is the explicit
opt-out.

Delivery rules:

- Hermes cron sends at most one digest per owner per schedule window;
- Memory-OS returns an empty/silent result when no action-required or true
  alert content exists. Review Suggested and FYI content are pull/ops surfaces,
  not the default recurring owner push;
- Memory-OS returns blocked/skipped when the export eligibility gate is not
  ready;
- Memory-OS returns blocked/skipped if RH-34c aging reports an unsafe or
  unbounded burden state;
- never send raw private bodies;
- never execute, approve, reject, crystallize, or mutate owner action state
  because a digest was generated or delivered;
- Hermes, not Memory-OS, owns delivery retry/cooldown/platform failure
  semantics.
- quiet hours are absolute no-send periods. If the configured schedule falls
  inside quiet hours, the Hermes cron schedule should not run. If it does run,
  Memory-OS may return `skipped_quiet_hours`.
- v0 supports a single configured owner per host. Multi-owner schedules,
  per-owner quiet hours, and per-owner channel preferences are RH-34f scope.
- each generated review payload creates one new `digest_id`. Hermes delivery
  ids are external transport evidence and must not be used as OwnerAction
  idempotency keys.

Recurring integration ledger:

```yaml
schema_version: memory-os.owner_review_cron_integration.v0
digest_id:
owner_id:
mode: recurring_daily
scheduled_for:
created_at:
result: rendered | skipped_empty | skipped_gate_blocked | skipped_quiet_hours | error
hermes_cron_job_id:
hermes_delivery_target_class:
owner_effect:
  owner_approved_digest_delivery: false
boundary:
  actual_unapproved_send: false
  actual_execute: false
  actual_identity_write: false
  actual_unapproved_crystallized_approval: false
raw_body_included: false
```

Implementation checkpoint (2026-05-25 local + test host):

- `scripts/memory_os_owner_review_digest.py` is installed to
  `$HERMES_HOME/scripts/memory_os_owner_review_digest.py` only when the
  installer is run with `--install-owner-review-cron-helper` or the interactive
  owner selects it.
- `scripts/memory_os_owner_review_cron_gate.py` is installed with the helper.
  It is the explicit opt-in gate for recurring delivery and is safe by default
  because it dry-runs unless `--apply --owner-approved` are both supplied.
- The helper does not send messages. It calls
  `hermes memory-os-agent-os review preview-digest` and then
  `review render-digest --format text --bounded --record-active`, writing only
  the bounded review brief to stdout for Hermes cron. Hermes injects that
  stdout into the agent prompt and the agent writes the final owner-facing
  Chinese digest.
- If there is no action-required, review-suggested, or FYI content, the helper
  exits successfully with empty stdout so Hermes has nothing meaningful to
  deliver.
- `review cron-status` reports
  `memory-os.owner_review_cron_integration.v0` through both provider CLI and
  `memory-os-agent-os` shell alias.
- `scripts/memory_os_3_200_monitor.py` reads `review cron-status` and reports
  the owner cron integration without printing digest bodies.
- The shell installer copies the helper/gate and, unless disabled by
  `--no-enable-owner-review-cron` or production-safe mode, creates the Hermes
  cron job through the recurring enable gate.

Recurring enable gate rules:

- `--schedule` and `--deliver` are required so the owner/operator explicitly
  chooses the review window and Hermes delivery target.
- reports redact the raw delivery target and expose only a delivery target
  class;
- `--apply` is rejected unless `--owner-approved` is also present;
- `deliver=local` is rejected because it is not an owner-channel delivery;
- the gate checks Hermes cron support for `--script` and `--deliver`;
- the gate checks bounded renderer output before apply and blocks raw-body or
  internal-schema-primary text;
- apply creates or updates the Hermes cron job in agent mode and updates
  Memory-OS recurring config, but Memory-OS still does not call platform
  transport directly.

Remote evidence on `10.20.3.200`:

```text
test-host installer:
  HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host
  owner_review_cron_gate.status=applied
  job_id=2af755464ca8
  job_name=memory-os-owner-review-digest
  schedule=0 9 * * *
  deliver_target_class=platform_home
  config_updated=true
  render_check.text_char_count=2231
  render_check.raw_body_included=false
  render_check.internal_schema_primary=false
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false

review cron-status:
  schema_version=memory-os.owner_review_cron_integration.v0
  status=ok
  enabled=true
  job_present=true
  job_enabled=true
  job_id=2af755464ca8
  helper_script_present=true
  hermes_delivery_configured=true
  hermes_delivery_target_class=platform_home
  raw_body_included_count=0
  unapproved_send_count=0

Hermes cron:
  job=2af755464ca8 [active]
  deliver=telegram
  script=memory_os_owner_review_digest.py
  mode=no-agent (superseded by RH-34g/RH-35.9 follow-up; recurring owner
  review now uses Hermes agent mode)
  last_run=2026-05-25T09:37:08.950764-04:00 ok
  output=/root/.hermes/cron/output/2af755464ca8/2026-05-25_09-37-04.md
  output_chars=2367
  output_has_bad_marker=false
  output_action_items=3
  output_review_items=2
  output_ends_partial_owner=false

monitor:
  OwnerCronIntegration.status=ok
  enabled=true
  job_present=true
  job_enabled=true
  helper_script_present=true
  delivery_configured=true
  delivery_target_class=platform_home
  rendered_count_24h=6
  raw_body_included=0
  unapproved_send_count=0
  OwnerRenderedDigest.text_char_count=2289
  OwnerRenderedDigest.text_has_internal_schema=false
  OwnerRenderedDigest.text_has_transcript_marker=false

recurring enable gate dry-run:
  schema_version=memory-os.owner_review_cron_enable_gate.v0
  status=dry_run
  apply_requested=false
  helper_script_present=true
  hermes_cron_create_available=true
  hermes_cron_supports_agent_script_deliver=true
  existing_job_present=false
  deliver_target_class=platform_home
  render_check.ok=true
  render_check.raw_body_included=false
  render_check.internal_schema_primary=false
  config_updated=false
```

Interpretation:

- RH-34e now has an installed, enabled Hermes cron owner-review job on the
  controlled test host.
- The default test-host install path proves the full deploy path: install
  helper/gate, validate bounded render output, create the Hermes cron job,
  update Memory-OS recurring config, and keep Memory-OS out of platform
  transport.
- A manual `hermes cron run` plus scheduler tick produced one bounded output
  file through Hermes cron with no raw body, transcript marker, internal-schema
  primary text, or mid-item truncation.
- The remaining owner-facing state-changing evidence is an owner-reply action
  test after the owner confirms the delivered digest text is understandable.

Monitor fields:

- `hermes_cron_integration.enabled`
- `hermes_cron_integration.job_present`
- `hermes_cron_integration.last_result`
- `hermes_cron_integration.next_run_at`
- `hermes_cron_integration.rendered_count_24h`
- `hermes_cron_integration.skipped_count_24h`
- `hermes_cron_integration.error_count_24h`
- `hermes_cron_integration.raw_body_included_count`
- `hermes_cron_integration.unapproved_send_count`
- `hermes_cron_integration.hermes_delivery_configured`

Promotion signal:

- Hermes cron exists and calls Memory-OS review rendering through the installed
  shell alias;
- one daily digest is delivered by Hermes in the configured window;
- Memory-OS does not directly call transport in the recurring path;
- no duplicate daily digest is sent for the same owner/window;
- owner can act on at least one item from the digest through
  OwnerActionProcessor;
- stale/backlog counts improve or remain bounded;
- `unapproved_send_count=0`;
- `raw_body_included_count=0`;
- no proposal execution or crystallized write happens as a side effect of
  delivery.

Stop / rollback signal:

- more than one digest is sent in a schedule window;
- Memory-OS directly sends recurring digest instead of returning payload to
  Hermes cron;
- any digest is rendered for delivery while export eligibility gate is not
  ready;
- delivery goes to a non-owner or group target without explicit owner config;
- raw private body is included;
- delivery failure repeats for two consecutive windows;
- owner reports the digest is noisy or unhelpful;
- monitor cannot prove whether a digest was sent, skipped, or failed.

Rollback:

- config-only rollback:
  disable or remove the Hermes cron job and set
  `owner_review.recurring_delivery_enabled=false`;
- keep preview, channel resolver, delivery gate, and CLI review surfaces
  available;
- preserve Memory-OS render/integration ledgers and Hermes cron delivery
  evidence for audit.

### RH-34e.1 - Review Digest Renderer

Purpose:

Turn internal review artifacts into owner-readable action briefs.

The RH-34d smoke proved transport but exposed that raw review items such as
`Candidate kind=moment; source_events=1; sensitivity=private` are not usable
daily review copy. The renderer must convert review queue items into bounded
human-actionable cards.

Each rendered item should include:

- short title;
- why this needs review;
- recommended actions;
- what each action changes;
- display anchor such as `[A1]` or `[R2]`, plus stable action-token
  commands such as `memory approve oa_<token>`;
- safe source class and confidence metadata only when useful.

Renderer must not:

- show raw private message bodies;
- expose implementation-only labels as the primary text (`kind=moment`,
  `source_events=1`, etc.);
- let an LLM invent actions or target ids;
- collapse approval/rejection consequences into vague prose.

Joy/agent phrasing may rewrite only the bounded renderer payload. It must not
read canonical private records directly and must not create new owner actions.

Implementation checkpoint (2026-05-25 local + test host):

- `render_owner_review_digest()` returns
  `memory-os.owner_review_rendered_digest.v0`.
- Each rendered item includes `anchor`, `question`, `suggested_action`,
  `reason`, `consequence`, `source_module`, `target_type`, and `target_id`.
- Candidate review items also include bounded `proposed_memory_text` so the
  owner can judge what would become long-term memory. This is the derived
  candidate text, not raw source-message body replay.
- `preview-digest` text now uses the same owner-readable rendering; bounded
  JSON still keeps safe target metadata for automation.
- `review render-digest --format text|json` is exposed through provider CLI and
  shell alias. `--record-active --channel <channel>` writes a bounded active
  digest snapshot for reply binding on the owner channel that received it.
- Local tests prove the renderer removes primary schema labels such as
  `Candidate kind=`, `source_events=`, and `sensitivity=` from owner-facing
  text while preserving raw-body-free bounded metadata.
- Remote shell smoke on `10.20.3.200` proved
  `review render-digest --record-active --channel telegram` returns
  `memory-os.owner_review_rendered_digest.v0`, writes an active digest
  snapshot, includes bounded candidate proposed-memory text, and keeps
  `text_has_internal_schema=false`.

### RH-35.2 - Owner Reply Parser

Purpose:

Map owner replies in the review channel back to OwnerActionProcessor.

Scope correction from the `10.20.2.88` Sannai prototype:

- Sannai review reports do not rely on shifting display numbers as approval
  identity. Candidate review uses stable candidate ids, and consolidation
  apply requires a proposal hash.
- Memory-OS must follow the same principle. `A1/R1/F1` are display anchors
  only. They are not durable approval authority.
- Owner-facing action commands must carry a stable action token derived from
  target type, target id, and action type.

Flow:

```text
owner command ("memory approve oa_<token>", "memory reject oa_<token>")
-> recorded/active digest action-token lookup
-> stable target id + action type
-> OwnerActionProcessor
-> idempotent ledger/state transition
-> feedback backflow / monitor evidence
```

Rules:

- frontend handlers may parse text, but only OwnerActionProcessor may mutate
  owner action state;
- if an action token is missing, stale, or ambiguous, ask for clarification;
- duplicate replies must be idempotent;
- approval of proposals must not execute them;
- feedback remains a ledger signal until a later bounded apply gate.

Implementation checkpoint (2026-05-25 local + test host, superseded by
RH-35.5 below):

- `parse_owner_review_reply()` parses `approve A1`, `reject R2`,
  `allow A1`, and `feedback F1 too_mechanistic` style replies against a
  recorded active digest when available. The parser accepts `--digest-id`; if
  omitted it uses the latest recorded digest for the owner/channel before
  falling back to a current preview.
- Parser output is `memory-os.owner_review_reply.v0`.
- Successful replies call `apply_owner_action()` only; frontend parsing does
  not mutate candidate/proposal/feedback/speak state directly.
- Missing or stale anchors, or an unknown digest id, return
  `needs_clarification` and create no owner action.
- `review reply ... --apply` is exposed through provider CLI and shell alias.
- Local tests cover recorded-digest binding after queue changes, dry-run
  approval, applied approval, feedback routing, unknown-anchor clarification,
  and shell parser parity.
- Remote shell smoke on `10.20.3.200` proved `review reply approve A1
  --digest-id <recorded>` binds to `recorded_digest`, while reply without
  `--digest-id` binds to `latest_recorded_digest`; both remained dry-run and
  created no owner action.

### RH-35.3 - Provider Owner Reply Ingress (Superseded As Primary Path)

Live finding on 2026-05-25:

```text
Owner replied in Telegram: reject R1
Assistant answered as ordinary chat: "Got it - not R1. Which one should we
continue with: R2, R3, or R4?"
```

Root cause:

- RH-35.2 existed only as CLI/shell alias and was not wired into the live
  provider turn path.
- Hermes correctly delivered the digest through cron, but the owner reply
  entered the normal chat conversation and was interpreted by the model before
  Memory-OS could apply the OwnerActionProcessor path.

Fix:

```text
MemoryProvider.on_turn_start(message)
-> exact owner-review command detector
-> parse_owner_review_reply(..., apply=true, require_recorded_digest=true)
-> OwnerActionProcessor
-> prefetch/system_prompt confirmation block for the current turn
```

Rules:

- only explicit prefixed owner-review command shapes are intercepted:
  `memory approve oa_<token>`, `memory reject oa_<token>`,
  `memory allow oa_<token>`, or
  `memory feedback oa_<token> too_mechanistic`;
- live ingress requires a recorded digest for the owner/channel and must not
  fall back to a freshly rendered digest;
- ordinary chat and low-clue recall are not affected;
- OwnerActionProcessor remains the sole state mutation path;
- if the recorded digest or action token is missing, Memory-OS returns a
  clarification instruction instead of guessing.

Implementation checkpoint (superseded by RH-35.8 as the primary live path):

- `MemoryOSProvider.on_turn_start()` now performs the owner-reply ingress
  check before provider prefetch.
- `parse_owner_review_reply()` gained `require_recorded_digest` for live
  ingress safety while preserving CLI preview behavior.
- The provider returns a short owner-review prefetch/system-prompt block so the
  assistant confirms the action instead of continuing ordinary conversation.
- A successfully processed token command is a control-plane message. `sync_turn`
  must skip ordinary conversation capture for that turn, so heartbeat cannot
  promote the command text into working memory or a new candidate.
- This display-anchor ingress model is superseded by RH-35.5. Current live
  ingress requires stable token commands and treats plain `reject R1` style
  text as ordinary conversation.

Architecture correction on 2026-05-26:

Hermes is an agent, not just a gateway transport. A valid owner command such as
`memory approve oa_<token>` should be interpreted by the Hermes agent as a
Memory-OS approval task, then completed by calling a Memory-OS provider tool.
The gateway and provider lifecycle hooks are not the normal state-mutation
surface.

New rule:

```text
owner command in chat
-> Hermes agent
-> memory_os_review_reply provider tool
-> parse_owner_review_reply(..., apply=true, require_recorded_digest=true)
-> OwnerActionProcessor
-> bounded assistant confirmation from the tool result
```

The provider may still guard against ordinary-memory pollution: if a token
command reaches `sync_turn` without a successful tool result, Memory-OS skips
conversation capture and records `owner_review_reply_tool_not_called`. It does
not silently approve the action through lifecycle hooks.

Gateway pre-dispatch owner-review interception is explicitly not the primary
path. It must not skip normal agent dispatch, and any user-visible
`gateway_ingress_error` for a valid review command is a P1 ingress regression.

### RH-35.8 - Agent-Mediated Owner Reply Tool

Purpose:

Expose owner review application as a model-facing Memory-OS provider tool so
Hermes can complete approval tasks through its normal agent loop.

Tool:

```text
memory_os_review_reply({
  "action": "approve" | "reject" | "allow" | "feedback",
  "action_token": "oa_<token>",
  "rating": "useful|irrelevant|too_mechanistic|missing_context|overconfident|needs_specific_recall",  # feedback only
  "owner_utterance": "<latest owner message, optional audit/debug context>"
})

Compatibility fallback:
memory_os_review_reply({ "reply": "memory approve oa_<token>" })
memory_os_review_reply({ "reply": "approve oa_<token>" })
```

Rules:

- Hermes is the interactive agent. It interprets owner intent, asks a short
  clarification when the target is ambiguous, and calls this tool only after it
  has a definite `action` and stable `oa_` token;
- the digest should print stable token commands such as
  `memory <verb> oa_<token>` for copy/paste safety; those token commands are
  the primary owner-facing apply input;
- display anchors such as `A1/R1/F1` are visual labels only. If the owner uses
  one anyway, Hermes may clarify or resolve from visible context, but the
  Memory-OS tool/state-machine layer still receives only the stable token;
- reject ordinary chat, messages that merely mention a token, display anchors
  with no unambiguous current digest mapping, or broad approval language without
  a resolvable `oa_` token;
- require a recorded digest binding and never render a fresh digest to apply a
  live action;
- call only `parse_owner_review_reply()` and OwnerActionProcessor;
- never send, execute work, write identity, or approve crystallized memory
  without the matching owner action token;
- processed token commands are control-plane messages and must not become
  conversation events, working-memory items, or candidates.

Monitor evidence:

- `owner_review_ingress_guard.review_reply_tool_available=true`;
- `owner_review_ingress_guard.review_reply_tool_status=ok`;
- `owner_review_ingress_guard.gateway_hook_registered=false`;
- token commands accepted by the detector, legacy anchors rejected, and
  ordinary token mentions rejected;
- owner command event/working/candidate counts remain zero.

Follow-up live finding on 2026-05-25:

```text
Owner replied in Telegram: approve A3
Memory-OS owner reply ingress ran, but returned
reason=anchor_not_found_in_current_digest.
```

Root cause:

- Hermes cron delivered the digest to Telegram, but the helper recorded the
  active digest under the fallback `cli` channel.
- Live ingress correctly used the Telegram provider channel, so it resolved an
  older Telegram digest without `A3`.

Fix:

- The recurring cron gate writes `owner_review.recurring_delivery_channel`,
  derived from the Hermes `--deliver` target unless explicitly overridden.
- The digest helper records active digest bindings against that configured
  delivery channel instead of falling back to the CLI preview channel.
- Provider live ingress tries the current provider channel first, then the
  configured recurring delivery channel, and only retries on missing digest or
  missing anchor. It still refuses freshly rendered fallback digests in live
  mode.

Rule:

- A reply action token must bind to the digest as delivered to the owner
  channel, not to the latest CLI/operator preview.

### RH-35.9 - Interactive Agent Task Semantics

Finding:

The first RH-35.8 correction still leaned too heavily on exact text commands.
That was a seam mistake. Hermes is an agent, not a passive command router.
Owner review should behave like an interactive task:

```text
owner says: "memory approve oa_<token>" or "批准 oa_<token>"
-> Hermes agent understands the task from the tokenized visible digest
-> if ambiguous, Hermes asks a clarification
-> if definite, Hermes calls memory_os_review_reply(action, action_token, ...)
-> Memory-OS applies the deterministic OwnerActionProcessor state transition
-> Hermes reports the bounded result back to the owner
```

Boundary:

- Hermes owns natural-language interpretation, clarification, and user-facing
  task execution.
- Memory-OS owns durable state: digest bindings, action tokens, parser
  compatibility, OwnerActionProcessor, audit, and monitor evidence.
- Gateway hooks are safety-only and must not be the primary execution path.
- Provider lifecycle hooks may prevent memory pollution but must not mutate live
  owner state without a tool call or CLI/API command.

Implementation:

1. Change `memory_os_review_reply` from a text-first tool to a structured
   action tool with `action`, `action_token`, optional `rating`, and optional
   `owner_utterance`.
2. Keep hidden `reply` handling inside `handle_tool_call()` as a compatibility
   fallback for non-model callers, but do not expose it in the model-facing
   tool schema.
3. Update the provider system prompt block so Hermes knows when to call the
   tool and when to ask a clarification.
4. Keep display anchors (`A1/R1/F1`) as UI labels only. The owner-facing digest
   prints stable token commands, and the tool receives only stable `oa_` tokens.
5. Keep `sync_turn` pollution guard for token-like control-plane replies that
   were not successfully processed; this is a safety net, not the main action
   path.
6. Add monitor evidence for structured tool availability and a live owner smoke
   where a tokenized owner phrase resolves through the agent to a structured
   tool call.

Implementation checkpoint:

- Local code implements the structured provider tool schema and compatibility
  fallback.
- The model-facing schema exposes only `action`, `action_token`, `rating`, and
  `owner_utterance`; `reply` remains accepted by `handle_tool_call()` as a
  non-model compatibility path.
- The monitor owner-review ingress probe uses structured tool arguments and
  records `review_reply_tool_input_mode=structured`.
- Targeted local verification on 2026-05-26:
  `python -m pytest tests/plugins/memory/test_memory_os_lifecycle.py
  tests/plugins/memory/test_memory_os_owner_actions.py
  tests/system_modularization/test_memory_os_agent_os_shell.py
  tests/scripts/test_memory_os_3_200_monitor.py -q` -> `99 passed`.
- Full local verification on 2026-05-26: `python -m pytest -q` -> `514
  passed`.
- Test-host deployment on 2026-05-26 refreshed the provider runtime and
  restarted `hermes-gateway.service`.
- Remote provider schema smoke on `10.20.3.200` reported
  `properties=["action","action_token","owner_utterance","rating"]`,
  `required=["action","action_token"]`, `has_reply=false`, and
  `description_has_fallback=false`.
- Remote monitor reported `owner_review_ingress_guard.review_reply_tool_input_mode=structured`,
  `review_reply_tool_status=ok`, `gateway_hook_registered=false`, and
  owner-command event/working/candidate counts all `0`.
- A real Hermes cron digest was triggered with
  `hermes cron run 2af755464ca8` followed by `hermes cron tick`; the job last
  run was `ok`. The remaining smoke is the owner replying with a tokenized
  phrase such as `memory approve oa_<token>` or `批准 oa_<token>` and Hermes
  agent resolving it to the structured tool call.
- The owner then replied with the exact token command
  `memory approve oa_e9a4e734a07de7`. Hermes agent called
  `memory_os_review_reply` successfully and Memory-OS applied
  `approve_proposal` with no memory pollution and no boundary violation. The
  session log shows this real call still used the compatibility `reply`
  fallback, so it does not close the structured live-agent gate.

Acceptance:

- `approve oa_<token>` and `memory approve oa_<token>` still work.
- Display anchors such as `A1/R1/F1` are not the recommended owner apply
  input. If the owner sends an anchor-only phrase, Hermes must not pass the
  anchor as identity; it should clarify unless it can resolve the current
  visible digest to one stable `oa_` token.
- ordinary chat that mentions a display anchor or an `oa_` token does not mutate
  state and does not become memory pollution.
- no gateway-level `gateway_ingress_error` is visible to the owner for valid
  review tasks.
- all state mutation still goes through OwnerActionProcessor.

### RH-34g/RH-35.9 Follow-Up - Chinese Agent-Mediated Digest

The recurring owner review digest is owner-facing, so it must not be a raw
script/watchdog notification. The correct recurring job is Hermes agent mode:

```text
Hermes cron --script memory_os_owner_review_digest.py --deliver <owner-target>
  prompt: read Script Output, write Chinese owner digest, preserve oa_ tokens,
          ask/clarify interactively later, never auto-approve or execute
```

Memory-OS helper output is a bounded review brief, not the final user copy.
The renderer still includes a Chinese fallback header so direct smoke output is
understandable:

```text
回复方式：
- 直接复制完整命令，例如：memory approve oa_...
- 也可以只回复 oa_...，Hermes 会继续问你要 approve/reject/allow/feedback。
- A1/R1/F1 只是列表编号，不是审批 ID。
```

The owner-facing digest is page one of a review surface, not a lossy dump.
Length limits exist to prevent Telegram/owner-channel flooding and owner
burden, but they must be expressed as pagination rather than truncation:

- show full-picture counts before item details;
- show `shown` and `omitted` counts by priority class;
- never cut a displayed item mid-sentence;
- each displayed action item must say what it is, what the owner is deciding,
  and what approve/reject/allow changes;
- omitted items are explicitly deferred to later digest pages or an
  owner-requested expansion path, not silently hidden.

Hermes agent-mode delivery must not collapse the digest into command-only
lists. Stable `memory approve oa_...` / `memory reject oa_...` commands are
required, but they are the action handles attached to an owner-readable item,
not the whole item.

Monitor treats this as a contract:

- `owner_review_rendered_digest.response_header_present=true` is required;
- `owner_review_rendered_digest.overview_present=true` is required;
- missing response header is a FAIL;
- missing full-picture overview is a FAIL;
- recurring owner review jobs created by the gate must be agent mode, and
  existing no-agent owner-review jobs are updated by the gate.

### RH-34h - Agent Review Surface Pagination And Detail

Owner review is conversational. Hermes agent owns the human interaction:

- "还有哪些";
- "下一页";
- "展开 R3";
- "这个 proposal 是什么";
- "这条允许后会发生什么".

Memory-OS must not become the conversational agent. It provides a bounded,
read-only review surface that Hermes can call while continuing the
conversation in the owner's language.

Contract:

```text
owner asks for more/detail
-> Hermes agent interprets intent
-> Memory-OS review surface tool returns bounded page/detail data
-> Hermes agent explains in owner language
-> no state changes unless owner later gives a stable oa_ action token
```

Rules:

- `next_page`, `page`, and `detail` are read-only;
- no send, execute, identity write, or crystallized approval;
- no raw private bodies;
- display anchors (`A1/R1/F1`) may be used only as references to the latest
  recorded digest context;
- stable `oa_` tokens remain the only action identity;
- omitted items are paginated, not lost;
- Hermes asks clarifying questions if the requested anchor/detail is not in
  the latest owner-home digest.

Acceptance:

- `memory_os_review_surface(operation=next_page)` returns omitted review items
  from the latest owner-home digest offsets without mutating state;
- `memory_os_review_surface(operation=detail, anchor=R3)` returns a bounded
  explanation payload for that displayed item when present, or
  `needs_clarification` when not present;
- monitor observes the review surface through summary-only fields:
  operation status, item count, source, boundary count, and raw-body count;
  Hermes owns final wording and user clarification.

Implementation checkpoint:

- provider tool `memory_os_review_surface` is exposed alongside
  `memory_os_review_reply`;
- shell alias supports `review surface --operation ...`;
- monitor records `owner_review_surface.status`,
  `raw_body_included_count`, `boundary_true_count`, and operation summaries;
- no monitor snapshot stores expanded item text.

Stop signals:

- a pagination/detail request applies an owner action;
- Memory-OS sends a message directly;
- detail output includes raw transcript/private body;
- anchor-only text becomes state identity without resolving to a stable token.

### RH-35.4 - Delivered Digest Binding v2

Live architecture correction:

The `channel` string is not the ownership boundary. It is only one possible
transport label. Hermes may deliver owner review through `telegram`, `slack`,
`origin`, or another owner-home target while the provider sees a different
live platform label. Owner reply binding therefore must be based on a recorded
delivered digest binding, not on a hardcoded platform name.

Binding model:

```text
Hermes cron deliver target
-> Memory-OS helper render-digest --record-active
-> rendered digest record with delivery_binding.scope=owner_home
-> owner explicit memory command with stable action token
-> latest owner-home digest containing that action token
-> OwnerActionProcessor
```

Rules:

- `delivery_binding.scope=owner_home` is recorded only for the configured
  recurring Hermes cron delivery channel;
- CLI/operator previews remain `scope=channel` and must not become the live
  owner-home binding;
- live ingress still requires a recorded digest and never renders a fresh
  digest to apply an owner action;
- exact owner commands remain required, but they use stable action tokens,
  not display anchors;
- ordinary chat mentioning `A1` or `A3` is not intercepted.

Implementation checkpoint:

- `render_owner_review_digest()` records `delivery_binding` metadata with
  `scope`, `channel`, `recurring_delivery_channel`, and
  `deliver_target_class`.
- `parse_owner_review_reply()` resolves the stable action token against the
  latest recorded `owner_home` digest containing that token.
- Provider live ingress can therefore accept a reply from one platform while
  binding it to the latest owner-home digest delivered by Hermes.
- Local tests cover `origin` owner-home delivery with a Telegram live provider,
  proving the fix is not Telegram-specific.

### RH-35.5 - Stable Owner Action Tokens

Live finding on 2026-05-25:

```text
Owner replied in Telegram: approve A2
The system still depended on channel/digest timing and a display anchor.
```

Root cause:

- `A1/R1/F1` are presentation anchors. They are useful for scanning, but they
  are not stable approval identities.
- A natural chat message can mention an anchor, and the same anchor can point
  to a different target after a new digest.
- The 10.20.2.88 Sannai prototype already solved this class of problem by
  requiring stable candidate ids or proposal hashes for state-changing apply.

Stable identity model:

```text
render digest item
-> display anchor A1/R1/F1 for readability only
-> action token oa_<hash(action_type,target_type,target_id)>
-> owner asks Hermes to approve/reject/allow/feedback the item
-> Hermes resolves the request to action + oa_<token>
-> recorded digest token lookup inside Memory-OS
-> OwnerActionProcessor
```

Rules:

- `A1/R1/F1` must never be the durable approval identity.
- The provider/tool layer executes only stable `oa_` action tokens.
- Hermes should prefer the stable token commands printed in the digest. If an
  owner sends anchor-only phrasing anyway, Hermes must clarify or resolve it to
  exactly one current visible stable token before calling Memory-OS.
- ordinary text containing anchors must not mutate Memory-OS state.
- CLI/operator workflows may still inspect anchors in bounded JSON, but live
  owner actions use stable action tokens.
- Tokens are bounded, non-secret references; they do not expose raw body.

Implementation checkpoint:

- Renderer now includes `action_tokens` and `action_commands` per actionable
  item and shows stable commands in the owner-facing text.
- Parser can resolve action tokens from recorded digests and maps them to the
  target id/action type before calling `OwnerActionProcessor`.
- Provider fallback parsing recognizes token command shapes only, reducing
  false positives in ordinary chat. The primary product path after RH-35.9 is
  structured agent tool execution, not lifecycle interception.
- Monitor owner-reply dry-run now derives a real action command from the
  rendered digest before testing parser health.

## RH-35 - Owner Action Processor

Purpose:

Convert owner actions from Telegram/CLI/future dashboard into idempotent,
auditable state transitions.

Owner action is the only path for:

- approving a crystallized candidate;
- rejecting a crystallized candidate;
- approving a proposal for later execution consideration;
- rejecting a proposal;
- marking relevance feedback;
- granting an exceptional one-shot proactive-send permission if that feature is
  enabled later.

Owner action is not required for:

- normal replies in an owner-started conversation;
- configured daily review digest delivery after explicit opt-in;
- right-brain thoughts appearing as bounded digest content or conversation
  context;
- monitor/FYI summaries that do not mutate state.

Initial action types:

| Action | State transition | Downstream effect | Hard boundary |
| --- | --- | --- | --- |
| `approve_candidate` | candidate pending -> owner_approved -> crystallized record | index refresh, candidate closed, approval audit | owner action required; idempotent |
| `reject_candidate` | candidate pending -> owner_rejected | candidate closed, negative scoring signal | canonical event/audit retained |
| `mark_feedback` | MemorySources / answer source -> feedback ledger | RH-30 signal for route/source quality | not long-term memory approval |
| `approve_proposal` | proposal candidate -> approved_for_proposal -> follow-up projection | may be manually executed later through OpsGate and a separate explicit apply command | approval does not execute |
| `reject_proposal` | proposal candidate -> owner_declined | similar deterministic proposal class downweighted | does not delete proposal evidence |
| `allow_speak_once` | out-of-policy proactive-send item -> one-shot permission ticket | exactly one bounded send opportunity outside the default policy | does not enable default send or approve future speech |

Approved proposal follow-up:

- Current v0 state transition is `candidate -> approved_for_proposal`.
- `approved_for_proposal` means the owner allows the proposal to enter a
  human-controlled follow-up surface. It is not an execution ticket yet and it
  must not call tools, send messages, mutate files, or change runtime config by
  itself.
- The approved-proposal follow-up projection makes accepted proposals visible
  without creating execution tickets. It can be consumed by OpsGate or an owner
  review digest, but actual execution still requires a separate explicit
  execution/apply command.
- Monitor evidence must keep `proposal_approved_count`, proposal state counts,
  and any future execution-ticket count separate.

Implementation checkpoint (RH-35.6):

- `review proposal-followups` returns
  `memory-os.approved_proposal_followups.v0`.
- It reads proposal queue items in `approved_for_proposal`, joins the matching
  `approve_proposal` owner action when available, and emits bounded follow-up
  items.
- It is read-only: `execution_ticket_count=0`, `actual_execute=false`, and no
  proposal/body raw text is emitted.
- Monitor exposes `OwnerProposalFollowups` and WARNs when approved proposals
  are pending follow-up, so approved items cannot silently disappear after the
  owner says yes.

Implementation checkpoint (RH-35.7):

- `review proposal-followups --proposal-id <proposal_id> --ops-gate` returns
  `memory-os.approved_proposal_ops_gate.v0` and previews the exact bounded
  OpsGate proposed action for an already `approved_for_proposal` item.
- `review proposal-followups --proposal-id <proposal_id> --ops-gate --apply`
  writes an OpsGate report-only record for that approved proposal. It is an
  explicit owner/operator apply path into the execution gate, not execution.
- The shell alias exposes the same path:

```bash
hermes memory-os-agent-os review proposal-followups --proposal-id <proposal_id> --ops-gate
hermes memory-os-agent-os review proposal-followups --proposal-id <proposal_id> --ops-gate --apply
```

- The shell alias must preserve provider CLI exit semantics. A bounded JSON
  error such as `proposal_not_found` must exit non-zero through
  `hermes memory-os-agent-os ...`; the Hermes plugin handler therefore exits
  explicitly instead of relying on Hermes core to inspect returned integers.
- The applied result must keep `execution_ticket_created=false`,
  `actual_execute=false`, and `raw_body_included=false`.
- Follow-up projection then moves the item from `awaiting_ops_gate_review` to
  `ops_gate_reviewed_awaiting_explicit_execution`. That state means "reviewed
  by OpsGate report-only"; it still does not authorize any tool execution.
- Repeating `--ops-gate --apply` for the same already reviewed proposal must be
  idempotent: return duplicate/already-reviewed evidence and do not append a
  second OpsGate report for the same `proposal_followup:<proposal_id>` action.

Implementation checkpoint (RH-35.10):

Hermes agent may help the owner inspect approved proposals and, after explicit
owner/operator intent, route one proposal into OpsGate report-only review.
This is still not execution.

```text
owner asks what to do with an approved proposal
-> Hermes agent calls read-only proposal follow-up surface
-> Hermes explains next step and asks whether to route to OpsGate
-> owner explicitly asks to route that proposal
-> Memory-OS writes one OpsGate report-only record
-> proposal follow-up state becomes ops_gate_reviewed_awaiting_explicit_execution
-> actual execution remains unavailable until a future explicit execution RH
```

Rules:

- read-only inspection can be agent-mediated;
- report-only OpsGate routing requires explicit owner/operator intent;
- OpsGate routing keeps `actual_execute=false`;
- OpsGate routing keeps `execution_ticket_created=false`;
- future real execution must be a separate RH with a separate execution
  contract, rollback path, monitor fields, and external review.

Idempotency:

```text
idempotency_key = owner_id + target_type + target_id + action_type
```

`digest_id` and `review_item_id` are evidence and UI-context fields. They are
not part of the idempotency key because the same target may appear in multiple
digests. The state machine must also check the target state before applying the
action; a candidate that is no longer pending cannot be approved again.

If the same key appears again:

- do not repeat the state transition;
- return the existing `owner_action_id`;
- record `duplicate_action_ignored_count` for monitor.

Proposal similarity v0:

Use deterministic grouping only:

```text
same source module + same proposal kind
```

Do not use an LLM to infer proposal similarity in v0.

Feedback thresholding:

- `useful`, `irrelevant`, and `too_mechanistic` are ledger facts first;
- they do not directly rewrite prompt projection weights in v0;
- later bounded adjustments require a separate review gate and threshold table
  in the RH-30 design.

## Feedback Back Into The Entrance

Owner actions must feed the next turn through declared contracts, not by hidden
prompt injection.

Feedback path:

```text
OwnerActionProcessor
-> owner_actions / feedback ledger
-> FeedbackSignal aggregation
-> RH-26 / RH-28 / RH-29 / RH-30 evidence
-> future bounded apply gate
-> next ingress/context projection behavior
```

Per-action feedback effects:

| Owner action | Immediate state effect | Feedback signal | Live routing effect in v0 |
| --- | --- | --- | --- |
| approve_candidate | crystallized record through owner-approved path | positive stable-memory signal | crystallized can be retrieved normally after index refresh |
| reject_candidate | candidate closed, canonical evidence retained | negative candidate-quality signal | no immediate route weight change |
| mark useful | feedback ledger on MemorySources / answer source | positive attribution signal | no immediate route weight change |
| mark irrelevant | feedback ledger on source/query_class/route | negative attribution signal | no immediate route weight change |
| mark too_mechanistic | feedback ledger with mechanism penalty class | mechanism-style quality signal | no immediate route weight change |
| approve_proposal | proposal approved for later manual execution consideration | positive proposal-kind signal | no execution; no route change |
| reject_proposal | proposal declined | negative deterministic proposal-class signal | no immediate route weight change |
| allow_speak_once | exceptional one-shot permission ticket | expression policy signal | only matching proactive-send item can consume ticket |

Initial v0 policy:

- owner feedback updates ledgers and monitor summaries immediately;
- crystallized approval updates the approved memory surface immediately because
  it is an explicit owner approval action;
- proposal approval updates only proposal state, not execution state;
- route weights, low-clue candidate ranking, and top-of-mind scoring remain
  unchanged until a later apply gate.

Future bounded apply can use aggregated signals only when:

- enough owner feedback exists for the relevant route/source class;
- monitor can show before/after outcome;
- hard boundaries remain false;
- the apply decision is reviewed under Contract 4 - FeedbackSignal and
  Contract 8 - OwnerAction.

One-shot proactive-send definition:

- `allow_speak_once` is not normal message approval. It is an exception for a
  bounded proactive-send item that falls outside the configured owner-channel
  delivery policy.
- v0 may record `allow_speak_once` tickets but must not enable real send unless
  the owner explicitly enables digest/action send support;
- a ticket is consumed by one matching `speak_gate` payload reference or expires
  by TTL;
- it never changes the default speak gate mode or creates a requirement that
  ordinary agent replies need owner approval.

## Data Surfaces

Minimum v0 files:

```text
system/owner_actions.jsonl
system/review_items.jsonl
```

Optional later split:

```text
system/feedback_ledger.jsonl
system/crystallization_approvals.jsonl
system/proposal_action_ledger.jsonl
system/speak_permission_tickets.jsonl
```

Owner action record:

```yaml
schema_version: memory-os.owner_action.v0
owner_action_id:
idempotency_key:
action_type:
target_type:
target_id:
owner_id:
channel: telegram | cli | dashboard
created_at:
result: applied | duplicate_ignored | rejected | error
result_ref:
boundary:
  actual_send: false
  actual_execute: false
  actual_identity_write: false
  actual_unapproved_crystallized_approval: false
owner_effect:
  owner_approved_crystallized_write: "<true only for explicit approve_candidate>"
```

The old hard boundary stays false for legitimate owner approvals. Monitor must
count owner-approved crystallized writes separately from unapproved
crystallized writes. Any crystallized write without a matching
OwnerActionProcessor record is a hard failure.

Review item record:

```yaml
schema_version: memory-os.review_item.v0
review_item_id:
target_type:
target_id:
source_module:
priority: action_required | review_suggested | fyi
status: pending | acted | snoozed | stale | closed
created_at:
updated_at:
stale_after:
snoozed_until:
summary:
safe_source_ids:
raw_body_included: false
```

Snoozed items return to `pending` after `snoozed_until` and can appear in a
later digest if still eligible.

## Contract Mapping

RH-34 / RH-35 touches:

- Contract 3 - MemoryWriteSurface;
- Contract 4 - FeedbackSignal;
- Contract 6 - MonitorEvidence;
- new Contract 8 - OwnerAction.

No module may mutate candidate, proposal, feedback, speak permission, or
crystallized approval state directly from owner-facing commands. It must go
through OwnerActionProcessor.

## Monitor Evidence

Required monitor fields before observation:

```text
review_channel.status
review_channel.reason
review_channel.channel
review_channel.configured_by_owner
review_channel.fallback_used
review_channel.raw_body_included
delivery_gate.status
delivery_gate.ready_for_delivery
delivery_gate.delivery_enabled
delivery_gate.delivery_adapter
delivery_gate.blocked_reasons
delivery_gate.boundary
digest_preview.will_send
digest_preview.actions_enabled
digest_preview.raw_body_included
digest_preview.boundary
digest_preview.overflow
review_queue.pending_count
review_queue.action_required_count
review_queue.review_suggested_count
review_queue.fyi_count
review_queue.stale_count
review_queue.overflow_count
owner_actions.count_24h
owner_actions.by_type
owner_actions.duplicate_action_ignored_count
owner_actions.error_count
owner_actions.owner_approved_crystallized_write_count
owner_actions.unapproved_crystallized_write_count
candidate_approved_count
candidate_rejected_count
proposal_approved_count
proposal_rejected_count
feedback_by_rating
crystallized_created_by_owner_action
digest_generated_count
digest_sent_count
digest_boundary_true_count
digest_burden.action_required_per_digest
digest_burden.owner_response_latency_hours
digest_burden.action_completion_rate
digest_burden.owner_active_period
feedback_backflow.by_action_type
feedback_backflow.by_route
feedback_backflow.by_source_class
feedback_backflow.apply_ready_count
```

Digest burden target:

- Action Required <= 3/day in steady state;
- stale_count should not grow for more than 7 days without a WARN;
- completion rate target >= 80% during an owner active period.

Owner active period:

- active only after the owner has at least one review action in the previous
  7 days;
- before that point, completion-rate fields are reported as cold-start
  observation, not as FAIL;
- stale or unsafe delivery conditions can still WARN/FAIL during cold start.

Retention:

- digest, review item, and owner action ledgers follow RH-17 metadata
  retention;
- retention is archive-before-prune and never deletes canonical memory,
  audit, or crystallized records.

## Implementation Order

Do not implement Telegram sending first.

Recommended sequence:

1. RH-35 OwnerActionProcessor data model and idempotent state transitions.
   - Implemented locally in `plugins/memory/memory_os/owner_actions.py` and
     deployed on `10.20.3.200`.
2. CLI dry-run/preview for review queue and owner action application.
   - Implemented through `hermes memory_os review ...` and the
     `memory-os-agent-os review ...` shell alias; live shell smoke passed on
     `10.20.3.200`.
3. Monitor fields for review queue, owner actions, and burden.
   - Implemented in the deterministic `memory_os_3_200_monitor.py` probe and
     fixture tests; live monitor reports `OwnerReview` without FAIL.
4. RH-34 digest generator dry-run, no send.
   - Implemented as `review preview-digest`; it produces bounded metadata and
     text preview only, with `will_send=false`.
5. Digest preview through shell alias.
   - Implemented as `hermes memory-os-agent-os review channel` and
     `hermes memory-os-agent-os review preview-digest`; live shell smoke passed
     on `10.20.3.200`.
6. Explicit opt-in delivery gate.
   - Implemented as `hermes memory-os-agent-os review delivery-gate`; live
     smoke passed on `10.20.3.200` with `status=disabled` and
     `actual_send=false`.
7. RH-34c review queue aging policy.
8. RH-34d one-shot real-send smoke with external review and owner trigger.
9. RH-34e recurring daily digest delivery only after owner enables it, the
   one-shot smoke succeeds, and external review approves the recurring delivery
   gate.

RH-35.1/RH-34a/RH-34b/RH-34c provide the shared state machine, bounded
queue/status reports, digest preview, channel resolver evidence, opt-in
delivery gate evidence, aging projection, dry-run/apply CLI, and monitor
evidence. RH-34d adds one owner-triggered channel delivery smoke only. It does
not implement Telegram buttons, recurring delivery, or default proactive sends.

Pre-aging test-host evidence:

```text
review status schema=memory-os.owner_review_status.v0
review queue pending=186, action_required=175
dry-run approve_candidate status=ok, dry_run=True
monitor OwnerReview owner_actions=0, unapproved_crystallized=0
```

RH-34a test-host evidence:

```text
review channel:
  schema=memory-os.owner_review_channel.v0
  status=dry_run_only
  reason=cli_preview_fallback
  raw_body_included=false

review preview-digest --max-action-required 2 --max-review-suggested 2 --max-fyi 2:
  schema=memory-os.owner_review_digest_preview.v0
  will_send=false
  delivery_skipped=true
  actions_enabled=false
  raw_body_included=false
  action_required_total=175
  action_required_shown=2
  action_required_overflow=173
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false

monitor:
  OwnerReviewChannel.status=dry_run_only
  OwnerDigestPreview.status=ok
  OwnerDigestPreview.will_send=false
  OwnerDigestPreview.raw_body_included=false
  PASS includes owner_review_channel_resolver_ok
  PASS includes owner_review_digest_preview_ok
```

RH-34b test-host evidence:

```text
review delivery-gate:
  schema=memory-os.owner_review_delivery_gate.v0
  status=disabled
  ready_for_delivery=false
  delivery_enabled=false
  delivery_adapter=none
  blocked_reasons=[
    delivery_not_enabled,
    delivery_adapter_not_configured,
    review_channel_not_selected,
    review_channel_not_configured_by_owner
  ]
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false

monitor:
  OwnerDeliveryGate.status=disabled
  OwnerDeliveryGate.ready_for_delivery=false
  OwnerDeliveryGate.delivery_enabled=false
  PASS includes owner_review_delivery_gate_ok
```

## Acceptance

Local:

- unit tests for idempotency;
- candidate approve/reject transition tests;
- proposal approve/reject transition tests;
- feedback action tests;
- no raw-body review item tests;
- monitor fixture tests.

Remote test-host:

- `10.20.3.200` dry-run digest preview produces bounded JSON/text;
- `10.20.3.200` delivery gate reports disabled/blocked/ready with boundary
  booleans and no actual send;
- owner action dry-run reports exactly what would change;
- applied action tests use test candidates/proposals only;
- monitor shows owner action fields without FAIL;
- historical hard boundaries remain false; explicit owner-approved
  crystallized writes are counted through `owner_effect` and matched
  OwnerActionProcessor records.

Stop signals:

- digest includes raw private body;
- digest is sent to a non-owner, unresolved, group, or non-configured channel;
- owner action applies twice for one idempotency key;
- proposal approval triggers actual execution;
- feedback is treated as long-term memory approval;
- speak once enables default sending;
- monitor cannot distinguish pending/stale/acted review items.
