# 34 - Owner Review Digest And Action Workflow

Status: RH-35.1 OwnerActionProcessor, RH-34a metadata-only channel resolver
and digest preview, RH-34b Memory-OS export eligibility gate, RH-34c review
queue aging policy, and RH-34d one-shot Hermes send compatibility smoke are
deployed on `10.20.3.200`; RH-34e is redirected to Hermes Cron Owner Review
Integration, not a Memory-OS-owned recurring transport.
Date: 2026-05-25
Scope: RH-34 Daily Owner Review Digest, RH-35 Owner Action Processor, and the
owner-facing governance loop needed to make Memory-OS usable without daily SSH
operations.

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
   questions, suggested actions, reasons, consequences, and stable anchors.
2. RH-35.2 Owner Reply Parser - map replies such as `approve A1` or
   `reject R2` to OwnerActionProcessor without frontend mutation.
3. RH-34e Hermes Cron Owner Review Integration - let Hermes schedule and
   deliver the bounded digest through the owner-configured channel.

Priority:

```text
Renderer first: without readable items, sending is useless.
Reply parser second: without action parsing, reading is not governance.
Hermes cron integration third: without the first two, recurring delivery just
creates noise; with them, it becomes the daily owner review loop.
```

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

Daily digest sections:

| Section | Contents | Owner burden rule |
| --- | --- | --- |
| Action Required | candidate approvals, proposal approvals, out-of-policy proactive-send exceptions, monitor WARN needing owner judgment | target <= 3 items/day |
| Review Suggested | high-scoring candidates, repeated stable facts, feedback opportunities, eval finding candidates | target <= 5 items/day |
| FYI / Trends | module output counts, would-send trends, source-class skew, stale counts, audit density | no action required |

Overflow strategy:

- rank Action Required by urgency and age;
- show the top `max_action_required`;
- include `overflow_count`;
- do not silently drop overflow;
- stale overflow becomes monitor WARN, not more digest spam.

Owner absence strategy:

- no action for 3 days: mark items stale and keep them in the queue;
- no action for 7 days: monitor reports `review_queue_stale_owner_attention`;
- no automatic approval, rejection, execution, or send is allowed because the
  owner is absent.

Interaction v0:

- text/number based in the owner conversation;
- no Telegram inline keyboard requirement for v0;
- each digest item gets a short owner-facing anchor, for example `[A1]`
  for action-required items, `[R2]` for review-suggested items, and `[F1]`
  for feedback targets;
- anchor replies are bound to the latest active digest for this owner/channel;
  sending a newer digest retires older numeric anchors;
- owner commands may also use the full stable target id when acting on an
  older item;
- if a reply cannot be resolved against the active digest or a stable target
  id, the processor must ask for clarification and must not guess;
- examples:
  - `approve A1`
  - `approve cand_123`
  - `reject R2`
  - `reject cand_124`
  - `feedback F1 too_mechanistic`
  - `feedback msrc_456 too_mechanistic`
  - `approve-proposal prop_001`
  - `reject-proposal prop_002`
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
- owner explicitly enables a Hermes cron delivery job or approves installer
  creation of that job;
- Memory-OS export eligibility gate reports `status=ready`;
- digest preview remains bounded and raw-body-free;
- monitor can distinguish generated, skipped, delivered, and failed review
  payloads without raw bodies.

Correct integration shape:

```text
Hermes cron job:
  schedule: owner-selected daily window
  deliver: Hermes owner/home channel
  command:
    hermes memory-os-agent-os review render-digest \
      --format text --bounded --record-active --channel <owner-channel>

Memory-OS:
  returns bounded text and machine-readable anchors
  returns exit/status codes for empty/skipped/blocked/error
  does not call send_message_tool in the recurring path
```

Delivery rules:

- Hermes cron sends at most one digest per owner per schedule window;
- Memory-OS returns an empty/silent result when no action-required,
  review-suggested, or meaningful FYI content exists;
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
- stable anchor such as `[A1]`, `[R2]`, or a full target id;
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

Flow:

```text
owner reply ("approve A1", "reject R2", "feedback F1 too_mechanistic")
-> recorded/active digest anchor lookup
-> stable target id + action type
-> OwnerActionProcessor
-> idempotent ledger/state transition
-> feedback backflow / monitor evidence
```

Rules:

- frontend handlers may parse text, but only OwnerActionProcessor may mutate
  owner action state;
- if an anchor is missing, stale, or ambiguous, ask for clarification;
- duplicate replies must be idempotent;
- approval of proposals must not execute them;
- feedback remains a ledger signal until a later bounded apply gate.

Implementation checkpoint (2026-05-25 local + test host):

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
| `approve_proposal` | proposal candidate -> approved_for_proposal -> execution ticket | may be manually executed later through OpsGate | approval does not execute |
| `reject_proposal` | proposal candidate -> owner_declined | similar deterministic proposal class downweighted | does not delete proposal evidence |
| `allow_speak_once` | out-of-policy proactive-send item -> one-shot permission ticket | exactly one bounded send opportunity outside the default policy | does not enable default send or approve future speech |

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
