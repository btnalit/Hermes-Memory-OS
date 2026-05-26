# 32 - Active Roadmap And Gates

Status: active planning index
Date: 2026-05-25
Scope: Memory-OS v0.1 test-host roadmap, remaining development queue, and
promotion gates

Current entrypoint:

```text
docs/system-modularization/40-memory-os-unified-control-plane.md
```

Use `40` as the first human-readable control document for current truth,
priority order, and hard gates. This `32` document remains the detailed active
roadmap and long-form backlog notes.

## Purpose

This document is the visible task queue for Memory-OS after RH-31. It does not
replace the module integration contract in
`29-memory-os-module-integration-contract.md`; it makes the current work queue
readable in one place.

It exists because the work is now spread across many documents:

- module extraction and v0.1 modules: `00` through `06`
- runtime hardening and future work: `08`
- digest / governance / reflection designs: `14`, `16`, `17`
- cognitive-loop scheduler: `23`
- memory sources, feedback, and relevance roadmap: `25`
- MemorySources attribution: `26`
- monitor and audit-noise control: `27`
- low-clue recall router: `28`
- module integration contract: `29`
- Hermes upgrade gate: `30`
- recall eval harness: `31`
- live evidence: `07`
- agent/Memory-OS collaboration contract: `37`

The queue below must stay consistent with those source documents and with live
`10.20.3.200` monitor evidence.

## Current Live Baseline

Latest read-only monitor evidence used for this roadmap refresh:

```text
host: 10.20.3.200
date_utc: 2026-05-25T04:36:45Z
classification: WARN
FAIL: none

gateway: active
heartbeat_state: fresh
cognitive_loop.latest_status: ok
index_health: healthy
doctor: ok, expected hindsight_adapter_disabled warning only
status-tool contract: ok
shell alias no-env: ok
context_router: apply, apply_routes=["all"]
low_clue_recall: enabled, deterministic mode, ask_choice probe ok
low_clue_llm_judge: disabled, deterministic fallback active
low_clue_ingress_matrix: expected routes/headings matched
MemorySources: boundary_true_count=0, forbidden_field_findings=[]
DeepReflection: enabled, auto_bounded, boundaries false
DeepReflection optional outputs: self_evolution_proposals_enabled=true,
  wandering_seed_enabled=true, working_updates_enabled=false
module status inventory: 16 modules visible
wandering_mind: would_send_count=11
proposal_queue: candidate_count=15, pending candidate state count=14
evidence_scoring: score_count=560
crystallized_records: 0
RH-31 eval: warning, failure_count=3 after P1-B attribution fix
OwnerReviewChannel: dry_run_only, cli preview fallback, raw_body=false
OwnerDigestPreview: ok, will_send=false, raw_body=false
OwnerDeliveryGate: disabled, ready_for_delivery=false, actual_send=false
```

This means the system is healthy enough to continue development, but not all
planned modules are mature enough for promotion.

## Status Terms

| Status | Meaning |
| --- | --- |
| implemented | Code exists and local tests cover the intended public seam. |
| test-host active | Enabled or scheduled on `10.20.3.200`. |
| observing | Running safely, but the promotion signal is not mature yet. |
| planned | Design exists, but implementation should not start until gates are met. |
| blocked | A required contract, monitor field, or evidence source is missing. |
| deferred | Explicitly not part of the current v0.1 slice. |
| superseded | Replaced by a newer contract or RH item; kept only for history. |
| deprecated | Still present but should not be used for new implementation. |

## Roadmap Maintenance Rule

This document must be kept current whenever a new RH/module changes priority,
status, monitor gates, or validation evidence. This is an operating rule, not
an executable P1 work item.

Maintenance signal:

- every active item has a source document, status, monitor signal, and next
  action.

Stop signal:

- a new module starts without appearing in this roadmap and the 29号 contract
  table.

## Implemented Baseline

These are not the remaining queue, but future work depends on them.

| Area | Current state | Evidence / gate |
| --- | --- | --- |
| Memory-OS provider | implemented and deployed | provider active as `memory_os`, status/doctor ok |
| Shell plugin | implemented and deployed | `memory-os-agent-os` status/doctor/modules/memory-sources/eval/metadata-retention alias checks pass |
| Installer | implemented, test-host capable | provider + shell + heartbeat + cognitive-loop presets exist |
| Module CLI P1 closure | implemented | modules status/doctor/run-once/validate-no-send and DeepReflection preview/history exposed |
| RH-25/RH-25.1 foreground task anchor | implemented | compression/deferred resume probes pass; boundaries false |
| RH-26 context router | implemented and applied | seven heading probes monitored |
| RH-27 cognitive loop | implemented and scheduled on test host | latest cycle `ok`, boundaries false |
| RH-27b audit noise control | implemented | no-op heartbeat no longer writes audit; still observing density trend |
| RH-28 low-clue recall | implemented | deterministic guard, report-only LLM judge path, ingress matrix |
| Mirror family | implemented, operator-triggered | cron/session/state/shadow status and dry-run/apply commands exist; recurring apply is not enabled |
| RH-29 MemorySources attribution | implemented | ledger stats, forbidden-field and boundary checks pass |
| RH-30 relevance feedback audit | implemented | feedback ledger exists; current feedback volume is low |
| RH-31.0-31.3 eval harness | implemented | first deterministic scorecard exists; P1-B projection miss attributed to fixture/adapter bug; warning findings remain lexical/FTS measurement signals |
| RH-17 metadata/report retention helper | implemented as dry-run | no canonical paths touched; physical apply remains open |
| Hermes upgrade compatibility gate | designed and script-backed | future Hermes version upgrade still needs live run |
| RH-34/RH-35 owner governance | RH-35.1 + RH-34a/b/c/d + RH-34e.1 + RH-35.2/35.5/35.8 + RH-34e/f/g live on test host | owner action processor, review queue/status/apply CLI, channel resolver, digest preview, export eligibility gate, aging projection, one-shot Hermes send compatibility smoke, owner-readable renderer, stable action-token parser, agent-mediated `memory_os_review_reply` tool, Hermes cron recurring delivery, portable owner channel defaults, and bounded digest quality checks are deployed; Memory-OS renders bounded text and exposes tools/state, Hermes owns delivery and agent interaction |
| RH-36 module closure matrix | documented and locally enforced | left/right brain, governance, feedback, scheduler, monitor, owner-review, and Hermes transport seams are listed with reads/writes, owner-action behavior, speech behavior, gates, and backflow; the matrix now includes delivery/state-change/cadence classification fields, renderer/helper/Hermes delivery split, mailbox-internal scope, cadence transitions, production cadence targets, active roadmap closure mapping, RH-38 right-brain expression closure, RH-39 left-brain governance quality, and violation severity rules aligned with `10.20.2.88` main/Sannai cron and mailbox patterns; `scripts/memory_os_closure_matrix_check.py` reconciles code-defined live modules, contract-critical non-live surfaces, and active `P1-*`/`P2-F` work items against RH-36 and currently reports `status=ok`, `live_module_count=16`, `matrix_module_count=28`, `active_work_item_count=19`, `active_work_mapping_count=19`, `finding_count=0` |
| RH-37 Agent / Memory-OS collaboration contract | design contract active; no new execution capability | defines how Hermes agent reads bounded Memory-OS review context, explains owner questions, suggests without deciding, asks when ambiguous, and calls structured tools only after definite owner intent; follow-up implementation remains split into P1 items below |

## Full Documentation-to-Code-to-Live Reconciliation

This section records items recovered by scanning the full document set against
local code and current `10.20.3.200` evidence. These are the items most likely
to disappear if the roadmap only tracks recent RH work.

| Item | Document promise | Code state | Live state | Gap / next action |
| --- | --- | --- | --- | --- |
| v0.1 portable modules | `03` and `06` define mailbox, household_digest, wandering_mind, inner_drive, ops_gate, proposal_queue, evidence_scoring, self_evolution, speak_gate | all are importable and visible through `modules status` | most run through cognitive loop or expose status only | keep them as individual contract rows, not only as "cognitive loop" aggregate |
| Mirror family | `09`, `10`, and RH-18 define cron/session/state/shadow coverage | cron/session/state/shadow commands and tests exist | status ok; session_mirror has 24 pending sessions; dry-run would generate 24 bounded events and write none | verify whether pending sessions correlate with RH-28 candidate omissions before deciding on one-time SessionMirror apply |
| DeepReflection optional outputs | `17` allows working updates, self-evolution proposal, and wandering seed as secondary outputs | implemented and tested | proposals/seeds enabled; working updates disabled | monitor optional output counts explicitly before promoting analysis behavior |
| Automatic expression | `03`, `06`, and `23` require Wandering Mind through Speak Gate, no-send/would-send only | implemented and tested | `wandering_mind.would_send_count=10`; `speak_gate.would_send_count=0` | add monitor trend for would-send/silent artifacts if expression becomes an evaluation focus |
| Per-module monitor evidence | `23` asks for deltas for evidence scores, proposal states, digest counts, DR counts, wandering artifacts, governance events | data exists in module artifacts/status | monitor now reports `module_artifacts` summary with digest/wandering/evidence/proposal/self-evolution/governance/DR/ops/speak/mailbox fields | continue trend observation through scheduled monitor |
| Module status parity | P1 closure made module CLI visible | `modules status/doctor` exists | inner_drive now shows runtime heartbeat source-of-truth; self_evolution doctor injects dependencies and reports ok | keep module-local versus runtime-authoritative fields explicit |
| LLM judge | `28` supports deterministic-first with report-only/bounded future modes | adapter path exists | current config has judge disabled (`mode=none`) | do not claim report-only judge data exists for the current live config until it is explicitly enabled and monitored |

## Active P1 Queue

P1-A is intentionally not used for a work item. It is reserved by the Roadmap
Maintenance Rule above so the queue does not treat maintenance as feature
progress.

### P1-B - RH-31 Failure Attribution And Fixture Loop

Status: first scorecard generated; `candidate_boundary_001` attribution
completed.

Reason:

- RH-31 has warning findings, but warnings are measurement signals, not live
  behavior fixes by themselves.

Next action:

1. keep the remaining lexical/FTS warnings as measurement signals;
2. do not create a live guard from `candidate_boundary_001`;
3. only create future fixtures or guards when a scorecard failure maps to live
   evidence or an owner-approved redacted fixture.

Finding flow:

- live Telegram behavior issues are owned first by the relevant live RH item
  such as P1-G/RH-28;
- if the issue can be safely redacted, add an RH-31 fixture with the same
  finding id;
- RH-31 synthetic failures remain measurement signals unless live evidence or
  owner-approved redacted fixtures prove the same failure class.

Promotion signal:

- a failure has live evidence or an owner-approved redacted fixture;
- boundary and forbidden-field counts remain zero;
- monitor can explain the route/source change.

Stop signal:

- a broad guard is proposed from scorecard output alone;
- a topic-specific hardcode appears.

### P1-C - DeepReflection / Conversation Carryover Session Injection

Source:

- `17-deep-reflection-runtime-design.md`
- `08-runtime-hardening-plan.md`
- `23-test-host-cognitive-loop-scheduler.md`

Status:

- implemented;
- `injection_mode=auto_bounded` active on `10.20.3.200`;
- monitor shows `current_injection_exists=true`;
- latest source class is governance; rolling source classes include
  governance and working;
- all hard boundaries remain false.

Why it matters:

- this is the main "session injection" capability: bounded Conversation
  Carryover can shape the next turn without becoming identity, crystallized
  memory, or hidden commands.

Next action:

- continue collecting source-class distribution and natural conversation
  behavior;
- run or refresh the DeepReflection A/B behavior review only after the first
  threshold window below is met.

Promotion signal:

- at least 7 days of scheduled monitor evidence after the last DR behavior
  change, or at least 30 live MemorySources records involving ordinary
  conversation after that change;
- at least 10 DeepReflection injection history records in the same window;
- selected/dropped source classes are explainable;
- no mechanism text leaks into ordinary answers;
- `actual_send=false`, `actual_execute=false`, `actual_identity_write=false`,
  `actual_crystallized_approval=false`.

Stop signal:

- injected context appears as a command, mechanism report, identity statement,
  or approved long-term memory.

### P1-D - Observation-Driven LLM / Governance Analysis

Source:

- `03-module-extraction-plan.md`
- `17-deep-reflection-runtime-design.md`
- `23-test-host-cognitive-loop-scheduler.md`
- `29-memory-os-module-integration-contract.md`

Status:

- DeepReflection internal analysis is active in auto-bounded mode;
- self-evolution is dry-run/report-only inside the cognitive loop;
- governance feedback is running as a bounded scheduler step;
- proposal queue and evidence scoring write artifacts but do not execute,
  send, or approve memory.
- latest live module status shows `evidence_scoring.score_count=545`,
  `proposal_queue.candidate_count=14`, `self_evolution.report_count=11`,
  and one `deep_reflection_self_evolution` proposal candidate.

Why it matters:

- this is the planned "start analyzing observed data" line. It is not a single
  model call; it is the governed path:

```text
events / working / digest / governance feedback
-> DeepReflection / self_evolution / evidence scoring
-> bounded analysis artifacts, proposals, injection cards, or would-send seeds
-> no direct execution, send, identity write, or crystallized approval
```

Next action:

- add a compact monitor summary for analysis artifact counts if the current
  cognitive-loop status is not enough to explain growth;
- keep LLM use in report-only or deterministic post-filtered modes unless a
  separate bounded-live gate is approved.

Promotion signal:

- analysis artifacts correlate with observed events and remain bounded;
- proposal/evidence outputs are readable and no-send;
- monitor can show counts without raw bodies.

Stop signal:

- analysis output becomes hidden instruction text, direct self-modification, or
  live action approval.

### P1-E - Automatic Expression / Speak Gate Would-Send Observation

Source:

- `00-overview.md`
- `01-plugin-architecture.md`
- `03-module-extraction-plan.md`
- `06-code-review-report.md`
- `23-test-host-cognitive-loop-scheduler.md`

Status:

- `wandering_mind` and `speak_gate` modules exist;
- tests prove would-send artifacts and `actual_send=false`;
- cognitive loop includes `wandering_mind`;
- latest live module status shows `wandering_mind.would_send_count=11`;
- monitor now exposes `expression_artifacts` with Wandering Mind output,
  would-send, silent/block, Speak Gate would-send/block, and
  `speak_gate_actual_send` fields.

Why it matters:

- this is the test-host safety observation line for expression artifacts. It
  proves bounded no-send / would-send evidence, not the full right-brain
  expression product.

Current limitation:

- P1-E does not close formal right-brain expression. It does not provide a real
  RightBrainExpressionEngine, does not guarantee every non-silent Wandering
  output is evaluated by SpeakGate, does not show enough expression content for
  owner voice-quality feedback, and does not feed expression feedback into
  governance/self-evolution. That work is split into P1-R / RH-38.

Next action:

- continue observing expression-artifact deltas through the scheduled monitor;
- do not enable real send.

Promotion signal:

- would-send artifacts are bounded, explainable, and sparse;
- Wandering Mind remains non-task and no-send;
- Speak Gate distinguishes no-send, would-send, and blocked send.

Do not promote:

- P1-E must not be promoted to "formal expression closure". It can only
  promote to "safe expression observation" until RH-38 is implemented.

Stop signal:

- `actual_send=true`;
- would-send records include private bodies or become pressure/notification
  spam.

### P1-F - RH-27 / RH-27b Runtime Density And Working Expiry Observation

Status:

- cognitive loop is active and latest cycle is `ok`;
- no-op heartbeat noise is reduced;
- current working state is skewed toward expired items:
  `active=32`, `expired=126`;
- this is not a hard failure, but it is a growth/retention signal.

Next action:

- continue event-gated observation for audit density;
- add a follow-up only if `audit_per_new_event` repeatedly exceeds 10 from
  plumbing noise or expired working items keep growing without retention story.

Promotion signal:

- enough event volume to compute audit density;
- target `audit_per_new_event` remains near 3-5 after meaningful events.

Stop signal:

- heartbeat stale;
- cognitive loop missing or error;
- boundary true;
- unbounded working/audit growth.

### P1-G - RH-28 Live Telegram Candidate Quality Observation

Status:

- RH-28f/g fixed shared ingress and deterministic source diversity;
- monitor probes pass;
- P1-J bounded topic-signature correlation did not show the specific
  `internet_data_collection` topic as pending-only, so the earlier real
  Telegram candidate omission should not be assumed to be caused by
  SessionMirror pending coverage;
- 2026-05-25 real Telegram retest for `继续昨天那个` produced a bounded
  four-item clarification list through Recall Guard; candidate 1 was the
  intended `internet_data_collection` topic, but candidate 2 was a non-topic
  attachment/vision placeholder;
- matching dry-run showed `candidate_quality.source_distribution={working:127,
  event:1}` and `diversity_applied=false`;
- 2026-05-25 follow-up fixed generic topic-title eligibility and exact-label
  source preservation:
  - `filtered_non_topic_title_count=2`
  - `diversity_applied=true`
  - `source_distribution={working:128,event:16}`
  - `selected_source_distribution={working:4,event:4}`
  - `decision=ask_choice`
  - boundaries all false;
- 2026-05-25 follow-up tightened Telegram choice labels to
  `max_title_chars=40` while preserving `ask_choice` and boundary safety;
- post-gateway Telegram retest showed the live response now returns concise
  topic labels:
  - `互联网数据采集系统 重新设计分层`
  - `rohitg00 / agentmemory / Memory-OS 相关`
  - `Built-in / Hermes / skill / Voice 相关`
  - `记忆系统带来的变化 这条`
  with no attachment placeholders, internal projection headings, or duplicate
  raw session-search variants;
- `memory_sources` did not produce an eligible topic candidate in that run,
  so candidate quality still needs live observation rather than a maturity
  claim;
- real Telegram still remains the highest-value validation path for candidate
  wording, duplicate merging, and owner correction flow.

Next action:

- retest `继续昨天那个` through real Telegram after gateway reload/restart when
  a live-process verification is needed;
- continue observing whether `memory_sources` can produce eligible topic
  candidates or whether its contribution should remain attribution-only;
- convert repeated failures into RH-31 fixtures before writing any new guard.

Promotion signal:

- low-clue prompts ask for a bounded choice instead of guessing;
- candidates are deduplicated, non-internal, and source-diverse;
- owner correction does not reinforce the same wrong shortlist.

Stop signal:

- raw `session_search` results bypass Recall Clarification Guard;
- internal labels such as route names or projection headings appear as user
  topics;
- attachment placeholders, tool-render snippets, or other non-topic artifacts
  appear as user-facing recall choices.

### P1-H - RH-30 Feedback Collection Volume

Status:

- feedback ledger exists;
- current monitor shows one `useful` feedback record.

Next action:

- collect more explicit feedback before using it for scoring;
- consider a future Telegram feedback affordance only after it is declared in
  the 29号 contract and monitored.

Promotion signal:

- enough explicit positive and negative feedback to evaluate ranking effects.

Stop signal:

- feedback mutates memory, candidates, crystallized records, identity, or
  router weights without an apply gate.

### P1-I - Monitor Hook Coverage Detection

Source:

- `08-runtime-hardening-plan.md` FW-03
- `19-memory-os-3-200-monitor.md`

Status:

- hook marker totals are monitored;
- monitor reads bounded session-activity event metadata and compares session
  activity deltas against hook-marker deltas.

Next action:

- continue observing whether scheduled snapshots ever produce
  `hook_markers_missing_for_session_activity`.

Promotion signal:

- monitor can distinguish "no session activity" from "session activity but no
  hook markers."

Stop signal:

- monitor reads private session bodies or tries to replay hooks.

### P1-J - SessionMirror Global Entrance Coverage Review

Source:

- `09-cronmirror-event-coverage-design.md`
- `10-source-mirror-impact-analysis.md`
- `29-memory-os-module-integration-contract.md`

Status:

- `session_mirror` is implemented and commandized;
- latest live monitor reports `session_count=54`, `covered_session_count=29`,
  and `pending_session_count=25`;
- latest dry-run monitor summary reports `dry_run_new_event_count=25`,
  `dry_run_written_event_ids_count=0`, and `dry_run_findings_count=0`;
- read-only topic-signature correlation found:
  - pending sessions: `automation_orchestration=1`, `memory_os=8`;
  - provider-captured events: `automation_orchestration=33`,
    `internet_data_collection=10`, `memory_os=53`, `comfyui_media=47`,
    `mindvideo_api=10`;
  - pending sessions did not show an `internet_data_collection` pending-only
    signal;
- no recurring SessionMirror apply is enabled.
- monitor now exposes the P1-J coverage summary and treats pending sessions as
  WARN observation rather than FAIL.

Why it matters:

- low-clue recall and "continue yesterday" behavior depend on the event stream
  being a reasonably complete cross-entry source;
- pending sessions may explain cases where the owner expects a topic to be in
  global memory but the provider path never captured it.

Next action:

- continue scheduled monitor observation of pending/covered counts;
- use the monitor trend to decide whether a separate one-time SessionMirror
  apply review is worth asking Claude to inspect;
- do not treat P1-J as the likely fix for the earlier
  `internet_data_collection` candidate omission.

Promotion signal:

- pending sessions are explained as either intentionally skipped or safely
  mirrored as bounded summary events;
- no raw private body enters public reports or MemorySources.

Stop signal:

- SessionMirror duplicates provider-captured turns;
- mirrored events become approved memory, identity, or send/execute triggers.

### P1-K - Module Status / Doctor Truthfulness Parity

Source:

- `22-p1-gap-closure-plan.md`
- `29-memory-os-module-integration-contract.md`

Status:

- `modules status` exposes all 16 modules;
- several v0.1 modules run only through cognitive loop and are not generic
  `run-once` commands;
- latest live status shows both `inner_drive.processed_event_count=0`
  (module-local state) and
  `inner_drive.runtime_heartbeat.processed_event_count=221`
  (runtime heartbeat source of truth);
- standalone `self_evolution` status now states its dependency context, and
  `modules doctor` injects `ops_gate`, `proposal_queue`, and
  `evidence_scoring` dependencies before calling `self_evolution.doctor`;
- latest live `modules doctor` has only expected warning findings:
  `mailbox_root_missing` and `pending_candidates_present`.

Why it matters:

- operator-facing status must not make a running subsystem look idle or broken;
- this is a documentation/diagnostic gap before it is a runtime bug.

Next action:

- keep the split visible in operator output and 07 validation evidence;
- do not promote self-evolution runtime maturity from standalone status alone;
  use cognitive-loop report count and module doctor together.

Promotion signal:

- module status, cognitive-loop status, and monitor summary tell the same story
  without needing private knowledge of call paths.

Stop signal:

- monitor marks a healthy loop as PASS while module doctor has an unclassified
  error, or module status hides a real failure.

### P1-L - Per-Module Cognitive Loop Artifact Monitor Parity

Source:

- `23-test-host-cognitive-loop-scheduler.md`
- `29-memory-os-module-integration-contract.md`

Status:

- cognitive loop itself is active and latest cycle is `ok`;
- module artifact data exists for digest, wandering, ops gate, evidence,
  self-evolution, governance feedback, DeepReflection, and proposal queue;
- monitor now reports a compact `module_artifacts` table:
  digest daily/weekly counts, wandering output/would-send counts, evidence
  counts, proposal states, self-evolution reports/proposals, governance events,
  DeepReflection artifacts, ops gate reports, speak gate send boundary, and
  mailbox would-send count.

Next action:

- continue trend observation through the scheduled monitor;
- use `module_artifacts` as the per-module evidence surface before claiming a
  cognition module is mature.

Promotion signal:

- the monitor can show which cognitive-loop modules are producing artifacts
  without reading private bodies.

Stop signal:

- a module is claimed as active only because the cycle is active, while its own
  artifact count is missing, stale, or unbounded.

### P1-M - Owner Review Digest And Action Workflow

Source:

- `34-owner-review-digest-and-action-workflow.md`
- `29-memory-os-module-integration-contract.md` Contract 8 - OwnerAction

Status:

- RH-35.1 deployed on `10.20.3.200`: owner action data model, idempotent
  processor, review queue/status/apply CLI, shell alias parity, and monitor
  summary fields;
- RH-34a deployed on `10.20.3.200`: metadata-only owner review channel
  resolver, bounded digest preview, shell alias parity, and monitor fields;
- RH-34b deployed on `10.20.3.200`: explicit opt-in delivery gate, shell alias
  parity, and monitor fields;
- RH-34c deployed on `10.20.3.200`: review queue aging projection, shell alias
  parity, and monitor fields;
- live shell-alias smoke and monitor evidence collected on `10.20.3.200`;
- RH-34d deployed on `10.20.3.200`: one owner-triggered real-send smoke,
  delivery ledger, delivery status CLI/shell alias parity, and monitor fields;
- RH-34d is reclassified as Hermes send compatibility evidence only, not the
  production recurring delivery architecture;
- RH-34e.1 deployed on `10.20.3.200`: review digest renderer turns internal review
  artifacts into owner-readable questions/actions/reasons/consequences with
  anchors, source-module context, and bounded proposed-memory text for
  candidate approvals;
- RH-35.2 deployed on `10.20.3.200`: owner reply parser initially mapped
  `approve A1`, `reject R2`, `allow A1`, and `feedback F1 too_mechanistic`
  style replies to OwnerActionProcessor without frontend state mutation;
  RH-35.5 supersedes this display-anchor command style with stable action
  tokens.
- RH-35.3 provider owner-reply ingress was deployed but is now superseded as
  the primary live path. The 2026-05-26 live Telegram test exposed
  `gateway_ingress_error` when a pre-gateway hook intercepted the owner command
  before the Hermes agent could act. The corrected path is RH-35.8.
- RH-34d `deliver-once` is reduced to legacy smoke-only in code; RH-34e must
  use Hermes cron/send for real recurring delivery;
- RH-34e minimum Hermes Cron Owner Review Integration is deployed on
  `10.20.3.200`: the Memory-OS cron helper script is installable under
  `$HERMES_HOME/scripts`, `review cron-status` is available through provider
  CLI and shell alias, and monitor reports OwnerCronIntegration;
- RH-34e recurring enable gate is implemented and installed with the helper:
  it validates schedule/delivery target, Hermes cron `--script --deliver`
  agent-mode support, duplicate job state, and bounded render output; apply is
  blocked unless explicitly owner/operator approved;
- RH-34e recurring owner-channel daily review is enabled on the controlled
  `10.20.3.200` test host by the test-host installer default. RH-34g follow-up
  changes the recurring job from direct `--no-agent` delivery to Hermes
  agent-mode cron (`--script --deliver`) so Hermes can write Chinese
  owner-facing text from the bounded Memory-OS review brief. Memory-OS must not
  own the recurring scheduler/transport.
- RH-34f deployed: the installer no longer hardcodes Telegram for ordinary
  installs. `--owner-review-cron-deliver auto` resolves to `telegram` only for
  `--test-host` and to Hermes cron `origin` otherwise; interactive installs can
  choose an explicit Hermes delivery target.
- RH-34g deployed: rendered owner-review digest text is whole-item bounded
  below the Telegram-safe budget and transcript-like candidates are downgraded
  to cleanup/FYI instead of approvable long-term memory.
- RH-34g/RH-35.9 wording follow-up: rendered digest text now includes a
  Chinese response header (`回复方式`) that explains stable `oa_` token usage and
  says `A1/R1/F1` are display labels only. Monitor now fails if the rendered
  digest lacks this response header.
- RH-34g/RH-35.9 live follow-up: the recurring owner-review Telegram digest
  now runs through Hermes agent mode and includes a Chinese full-picture
  overview, shown/omitted counts, complete item meanings, consequences, and
  stable `memory approve/reject/allow oa_...` commands. Monitor requires both
  `response_header_present=true` and `overview_present=true`. A real owner
  reply `memory reject oa_1e9ca00f639ca2` was processed by Hermes through
  `memory_os_review_reply` as `reject_proposal`; `actual_execute=false`,
  `unapproved_send_count=0`, and `raw_body_included_count=0`.
- RH-34h/RH-35.10 deployed and monitor-observed: owner requests such as
  "下一页", "还有哪些", and "展开 R3" belong to Hermes agent interaction and use
  a bounded read-only Memory-OS review surface. Monitor reports
  `owner_review_surface_ok`, `raw_body_included_count=0`, and
  `boundary_true_count=0`. Approved proposals can be inspected and routed into
  OpsGate report-only review after explicit owner/operator intent, but real
  execution remains a separate future execution/apply RH.
- RH-35.5 deployed and monitor-observed on `10.20.3.200`: owner-facing commands now use stable
  `memory <verb> oa_<token>` action tokens derived from target type, target id,
  and action type. `A1/R1/F1` are display anchors only, following the
  10.20.2.88 Sannai pattern of candidate ids / proposal hashes for review
  apply. Live ingress no longer intercepts plain `approve A1` style text.
  Monitor reports `legacy_anchor_accepted=false` and
  `token_command_accepted=true`.
- Real owner action smoke applied `memory approve oa_<token>` for A2 through
  OwnerActionProcessor. The proposal moved to `approved_for_proposal`; no work
  executed.
- RH-35.6 deployed and monitor-observed on `10.20.3.200`: `review proposal-followups` projects
  `approved_for_proposal` items into a bounded follow-up surface with
  `execution_ticket_count=0` and `actual_execute=false`.
- RH-35.7 implements the next explicit apply path:
  `review proposal-followups --proposal-id <proposal_id> --ops-gate --apply`
  writes an OpsGate report-only record for an approved proposal. It keeps
  `execution_ticket_created=false` and `actual_execute=false`; execution still
  requires a separate future explicit execution/apply command.
- 2026-05-26 independent mainline review follow-up: successfully processed
  owner-review token commands are now control-plane only and must not be
  captured/promoted as ordinary conversation events, working memory, or
  candidates; repeated approved-proposal OpsGate apply must return
  duplicate/already-reviewed evidence instead of appending duplicate OpsGate
  reports.
- RH-35.8 deployed on `10.20.3.200`: `memory_os_review_reply` is a model-facing
  Memory-OS provider tool. Hermes agent should use it for owner review tasks.
  The next correction, RH-35.9, changes the tool contract from text-first
  command parsing to structured `action + action_token` calls so Hermes can
  behave like an interactive agent: resolve unambiguous digest context, ask when
  ambiguous, and call Memory-OS only with stable `oa_` token identity. Gateway
  pre-dispatch owner-review interception is removed from the shell plugin and
  monitor now expects `gateway_hook_registered=false`,
  `review_reply_tool_available=true`, and `review_reply_tool_status=ok`.
  `sync_turn` skips token commands that were processed by the tool; if the
  tool was not called, it records `owner_review_reply_tool_not_called` and
  still prevents ordinary memory pollution.
- RH-35.9 is deployed on `10.20.3.200` at the provider/tool-contract level:
  the provider tool schema is structured-first (`action + action_token +
  optional rating + optional owner_utterance`). The hidden `reply` fallback is
  kept in `handle_tool_call()` for CLI/legacy callers, but is not exposed in
  the model-facing schema.
  The monitor owner-review ingress probe now requires structured tool input
  and reports `review_reply_tool_input_mode=structured`, gateway hook disabled,
  and owner command pollution counts at `0`. One real Hermes-agent owner phrase
  smoke using a tokenized digest command is still the remaining gate before
  calling the interactive-agent path fully closed. Display anchors are not the
  recommended apply input.
- RH-36 documented: all currently known left/right brain and governance modules
  have a closure path that says whether they generate owner actions, speech
  requests, direct context feedback, proposals, candidates, or monitor-only
  evidence.

Reason:

- The cognitive loop now produces review-worthy artifacts, but the owner-facing
  daily review and approval flow is missing.
- CLI/status output is a debugging surface, not a sustainable owner workflow.
- From the owner perspective, the loop is still not closed until a readable
  digest renderer, owner reply parser, and Hermes cron/send integration are in
  place. Monitor-only visibility is engineering evidence, not owner
  governance.

Live evidence:

```text
crystallized_candidates=161
crystallized_records=0
proposal_queue.candidate_count=15
proposal_queue.state_counts={"approved_for_proposal": 1, "candidate": 14}
wandering_mind.would_send_count=11
owner_actions ledger: 0 records after dry-run smoke
review queue: pending=186, action_required=175
monitor OwnerReview: unapproved_crystallized=0, owner_actions=0
review_channel: status=dry_run_only, reason=cli_preview_fallback, raw_body=false
digest_preview: status=ok, will_send=false, raw_body=false, action_required_total=175
delivery_gate: status=disabled, ready_for_delivery=false, delivery_enabled=false, actual_send=false
burden finding: action_required=175, overflow=172-173; first digest would overwhelm owner
RH-34d smoke:
  delivery_key=rh34d-smoke-20260525T095719Z
  result=sent
  sent_count=1
  owner_approved_digest_delivery_count=1
  unapproved_send_count=0
  raw_body_included_count=0
  post_smoke_delivery_gate=disabled
RH-34e helper/status:
  cron_status=ok
  recurring_enabled=true
  cron_job_present=true
  cron_job_enabled=true
  job_id=2af755464ca8
  helper_script_present=true
  hermes_delivery_configured=true
  hermes_delivery_target_class=platform_home
  helper_output_chars=3501
  helper_has_internal_schema=false
  helper_has_raw_marker=false
  monitor OwnerCronIntegration.status=ok
RH-34e enable gate dry-run:
  status=dry_run
  apply_requested=false
  helper_script_present=true
  hermes_cron_supports_agent_script_deliver=true
  existing_job_present=false
  deliver_target_class=platform_home
  render_check.raw_body_included=false
  render_check.internal_schema_primary=false
RH-34e default deploy / cron run:
  installer_gate_status=applied
  job_name=memory-os-owner-review-digest
  schedule=0 9 * * *
  deliver=telegram
  cron_last_run=2026-05-25T08:47:39.776368-04:00 ok
  output_chars=3637
  output_has_internal_schema=false
  output_has_raw_marker=false
  config_updated=false
RH-34f installer default:
  non_test_host_auto_target=origin
  test_host_auto_target=telegram
  gate_rejects_auto=true
  gate_rejects_local=true
RH-34g redeploy / cron run:
  gate_status=already_configured
  render_check_text_char_count=2231
  helper_preview_chars=2231
  helper_preview_has_bad_marker=false
  latest_cron_output_chars=2367
  latest_cron_output_has_bad_marker=false
  latest_cron_output_action_items=3
  latest_cron_output_review_items=2
  latest_cron_output_ends_partial_owner=false
  monitor OwnerRenderedDigest.text_char_count=2289
  monitor OwnerRenderedDigest.text_has_internal_schema=false
  monitor OwnerRenderedDigest.text_has_transcript_marker=false
  monitor OwnerCronIntegration.status=ok
```

Next action:

1. keep RH-34a/RH-34b/RH-34c/RH-34d in observation through scheduled monitor;
2. get external review on RH-34d smoke evidence as a compatibility smoke, not
   as approval for Memory-OS-owned recurring delivery;
3. observe the enabled Hermes cron job through monitor and owner-visible
   Telegram receipt; verify one owner/window behavior and config-only rollback;
4. run the next owner-reply action smoke only with the rendered stable command
   (`memory approve oa_<token>` or `memory reject oa_<token>`), not with
   display anchors such as `approve A1`;
5. keep RH-35.6 in monitor observation. Approved proposals must stay visible as
   follow-up items with `execution_ticket_count=0`; actual execution still
   requires a separate explicit execution/apply command;
6. keep CLI preview as the fallback owner surface;
7. keep `mailbox` classified as internal AI-agent mailroom evidence, not a
   left-brain or right-brain cognition module, not an owner digest channel, and
   not an approval path.

Promotion signal:

- owner action state transitions are idempotent;
- channel resolver can explain selected/dry-run/unresolved status without
  reading private bodies;
- digest preview is bounded, no-send, no-action, and raw-body-free;
- delivery gate is disabled by default and reports ready only after explicit
  opt-in prerequisites are satisfied;
- review aging reports raw/effective burden separately and reduced the deployed
  first digest from `raw_action_required=175` to `effective_action_required=14`
  without mutating or hiding backlog;
- one-shot send smoke proved Hermes can deliver one bounded Memory-OS digest,
  with `unapproved_send_count=0` and `raw_body_included_count=0`;
- review digest renderer produces owner-readable action briefs;
- candidate approval cards show bounded proposed-memory text;
- owner replies can be parsed into OwnerActionProcessor calls with recorded
  digest action-token binding and ambiguity protection;
- legacy `deliver-once` returns smoke-only and does not call transport;
- Hermes Cron Owner Review Integration is deployed as RH-34e and must continue
  proving one digest per owner/window, skipped/error outcomes, and rollback by
  disabling the Hermes cron job plus Memory-OS recurring flag. On the test
  host, recurring delivery is enabled by the installer default;
- digest preview contains bounded summaries and no raw bodies;
- rendered digest text stays within budget, does not truncate items, and does
  not show transcript-like candidates as approvable memory;
- open-source installer defaults use Hermes origin/home delivery semantics or
  an explicit owner-selected target, not a Telegram hardcode;
- monitor reports pending/stale/action/error counts;
- feedback backflow is visible as aggregation, not immediate route mutation;
- proposal approval does not execute;
- approved proposal follow-up projection is visible and reports
  `execution_ticket_count=0`;
- approved proposals can be routed through OpsGate report-only review with
  `ops_gate_reviewed_count` visible and `execution_ticket_count=0`;
- owner-review token commands show `event_count=0`, `working_count=0`, and
  `candidate_count=0` in monitor/integration evidence;
- OpsGate reports contain no duplicate `proposal_followup:<proposal_id>`
  action ids after repeated apply attempts;
- candidate approval creates crystallized records only through explicit owner
  action.
- unapproved crystallized write count remains zero, while owner-approved
  crystallized writes are counted separately with matching owner action records;
- digest burden metrics distinguish cold-start from active owner use.

Stop signal:

- digest includes raw private body;
- digest contains transcript markers or internal schema labels in primary
  owner-facing text;
- digest exceeds the owner-channel budget or truncates inside an item;
- digest sends to an unverified, unresolved, group, or non-owner channel;
- delivery gate reports ready before explicit opt-in and owner channel config;
- delivery gate or delivery adapter sets `actual_send=true` without external
  review and owner opt-in;
- aging closes, rejects, approves, or hides review items instead of changing
  display priority only;
- one-shot smoke sends more than one message or monitor cannot distinguish
  owner-approved send from unapproved send;
- recurring daily delivery starts before RH-34c/RH-34d review gates pass,
  before renderer/reply-parser are usable, or without explicit owner opt-in;
- Memory-OS implements a parallel recurring transport/scheduler instead of
  handing bounded digest output to Hermes cron/send-message;
- recurring daily delivery sends duplicate digests in one schedule window;
- any owner action bypasses OwnerActionProcessor;
- duplicate owner actions mutate the same target twice;
- crystallized memory is written without a matching owner action record;
- proposal approval causes actual execution;
- approved proposals disappear from monitor/review surfaces after approval;
- approved proposal follow-up projection creates execution tickets;
- approved proposal OpsGate routing creates execution tickets or sets
  `actual_execute=true`;
- feedback is treated as crystallized approval;
- speak-once enables default sending.
- Memory-OS tool/state-machine layer accepts display anchors such as
  `approve A1` as executable identity instead of requiring a resolved stable
  `oa_` token. Hermes may resolve anchors from visible context before calling
  the tool; Memory-OS itself must not execute anchors.

### P1-N - RH-37 Agent / Memory-OS Collaboration Contract

Source:

- `37-agent-memoryos-collaboration-contract.md`
- `29-memory-os-module-integration-contract.md`
- `36-module-closure-matrix.md`

Status:

- design contract active;
- no new execution capability;
- RH-36 classifies the collaboration contract as a governed non-runtime
  surface.

Reason:

- owner-review flow now works, but Hermes agent must be treated as an
  interactive partner rather than a rigid tool consumer;
- Memory-OS should expose bounded context, stable tokens, and structured tools,
  while Hermes owns explanation, clarification, recovery guidance, and owner
  conversation.

Next action:

1. use RH-37 as the preflight contract for every owner-review / review-surface /
   `memory_os_review_reply` change;
2. do not add execution capability from RH-37 itself;
3. implement the concrete P1 follow-ups below as separate slices.

Promotion signal:

- Hermes can read bounded review context, explain owner-visible consequences,
  suggest without deciding, ask when ambiguous, and call structured tools only
  after definite owner intent.

Stop signal:

- Memory-OS replaces Hermes agent with gateway interception, rigid language
  parsing, platform-facing recovery UX, or automatic decisions.

### P1-O - Reply Fallback And Gateway Hook Boundary Closure

Status: deployed on `10.20.3.200`; monitor structured owner-review ingress
probe passes. A fresh owner-visible Telegram reply smoke can still be repeated
on demand, but it was not required to close this monitor/gateway slice.

Reason:

- `reply` fallback exists for CLI/legacy paths, but the model-facing path should
  be structured `action + action_token + rating`;
- gateway hooks must be safety-only pollution guards, not the normal owner
  approval path.

Implemented local slice:

- monitor tracks `reply_fallback_used_count`,
  `structured_review_reply_count`, gateway safety skips, and owner-review
  command pollution;
- model-facing schema remains structured `action + action_token + rating`
  while `reply` remains a counted legacy/CLI fallback;
- gateway hook remains safety-only and must not be the normal approval path.

Next action:

1. continue watching live `structured_review_reply_count` versus
   `reply_fallback_used_count`;
2. repeat an owner-visible Telegram token action if Hermes agent interaction
   behavior changes again;
3. deprecate fallback only after structured live use stays stable.

Stop signal:

- a valid owner-review action requires gateway pre-dispatch interception to
  succeed;
- fallback use is invisible to monitor.

### P1-P - Candidate / Proposal Timestamp Schema Repair

Status: deployed on `10.20.3.200`; live monitor reports
`unknown_timestamp=0` and `created_at_coverage_ratio=1.0` for the current
review queue projection.

Reason:

- RH-34c aging found `unknown_timestamp=161`, which means much of the first
  aging reduction came from missing producer metadata rather than true age.

Implemented local slice:

- new crystallized candidate queue entries receive bounded `created_at`;
- review queue projection can derive candidate display time from safe source
  refs when needed;
- aging summary and monitor expose `unknown_timestamp_count`,
  `unknown_timestamp_by_item_type`, `created_at_coverage_ratio`,
  `true_aged_count`, and `unknown_aged_count`.

Next action:

1. extend the same producer rule to any remaining proposal/speak producers
   when their next write path is touched;
2. keep old missing timestamps visible instead of rewriting canonical data.

Stop signal:

- aging maturity is claimed while unknown timestamp remains the dominant review
  queue reason.

### P1-Q - Approved Proposal Follow-Up To OpsGate / Manual Apply

Status: deployed on `10.20.3.200`; monitor reports approved proposal follow-up
visibility with `execution_tickets=0` and `actual_execute=false`. Real
execution apply remains future work.

Reason:

- approving a proposal creates `approved_for_proposal`;
- approved proposals must stay visible to the owner/Hermes agent and may enter
  OpsGate report-only review, but execution still requires a separate explicit
  apply gate.

Implemented local slice:

- approved proposal follow-up summaries expose approved counts and
  `actual_execute=false`;
- monitor fails if top-level, boundary, or item-level proposal follow-up sets
  `actual_execute=true`;
- OpsGate follow-up remains report-only and idempotent.

Next action:

1. design future manual execution/apply separately with explicit owner/operator
   intent, monitor fields, rollback, and external review.

Stop signal:

- proposal approval creates execution tickets or sets `actual_execute=true`;
- approved proposals disappear from review/monitor surfaces after approval.

### P1-R - RH-38 Right-Brain Expression Closure

Status: design gate added; P1-R slice 1 deployed on `10.20.3.200` with WARN-only
monitor evidence.

Source:

- `docs/memory-os/architecture.md`
- `docs/system-modularization/36-module-closure-matrix.md`
- `docs/system-modularization/38-right-brain-expression-closure-contract.md`
- live `10.20.3.200` monitor expression evidence

Reason:

- the architecture says Wandering Mind should express feeling/free association
  and may produce free expression or `[SILENT]`;
- the current v0.1 implementation closes only no-send / would-send
  observation, not formal right-brain expression;
- `wandering_mind.would_send_count` exists;
- P1-R slice 1 routes cognitive-loop Wandering output through SpeakGate and
  exposes evaluated/missing decision monitor fields;
- live evidence shows the new cycle created one SpeakGate decision while older
  reports still account for historical missing decisions;
- expression content review, expression feedback, and
  governance/self-evolution backflow are not closed.

Required design work:

1. define `RightBrainExpressionEngine` as a bounded expression adapter or
   Hermes-agent-mediated path, with no execution tools and no raw private body;
2. keep the right-brain subsystem split by route: Household Digest input,
   DeepReflection analysis/injection/proposal/seed, Conversation Carryover,
   Wandering expression draft, SpeakGate decision, OwnerReview feedback, and
   GovernanceFeedback/SelfEvolution backflow;
3. define three expression tiers:
   `test_host_observation`, `scheduled_right_brain_expression`, and
   `exceptional_proactive_send`;
4. require every non-silent expression draft to pass SpeakGate
   - local slice 1 covers current cognitive-loop Wandering output only;
5. make owner review show bounded expression content, not only payload refs;
6. add expression feedback types: `like`, `too_mechanical`, `too_frequent`,
   `boundary_private`, `off_voice`, `mute_period`;
7. route expression outcomes into GovernanceFeedback / SelfEvolution as
   proposals, not direct prompt/cadence mutation;
8. add monitor fields listed in RH-38 before claiming observation or closure.

Promotion signal:

- expression drafts are bounded and non-task;
- every non-silent draft has a SpeakGate decision;
- owner can see and feedback expression content;
- expression feedback can produce owner-reviewed prompt/policy/frequency
  proposals;
- Hermes owns delivery and all hard boundaries remain false.

Stop signal:

- actual send happens without owner-configured scheduled expression;
- raw private body appears in expression draft/review;
- right-brain text becomes task/proposal/agenda language;
- feedback directly mutates prompts, cadence, routing, or delivery.

### P1-S - RH-39 Left-Brain Governance Quality

Status: design gate added; P1-S slice 1 deployed on `10.20.3.200` with
WARN-only monitor evidence and no hard failures.

Source:

- `docs/system-modularization/39-left-brain-governance-quality-contract.md`
- `docs/system-modularization/36-module-closure-matrix.md`
- latest 10.20.3.200 monitor evidence

Reason:

- left-brain safety governance is implemented, but intelligent judgment is not
  mature;
- EvidenceScoring currently uses deterministic hash-derived scores, which are
  replayable but not meaningful importance/risk/feedback scores;
- SelfEvolution can create proposal backlog from recurring scores without a
  novelty/idempotency/cadence gate;
- feedback ledgers exist, but feedback is not yet consumed as first-class
  GovernanceFeedback / scoring / reflection input;
- deployed P1-S slice 1 filters expired working from EvidenceScoring and adds
  monitor visibility for expired scoring contamination;
- expired working handling in DeepReflection is still not fixed;
- approved proposals are visible and safe, but execution-decision state remains
  future work.

Latest slice-1 evidence:

- commit: `1f56294 Filter expired working from evidence scoring`;
- remote cognitive loop: `cloop_20260526T074331475537Z_51164c286d`,
  status `ok`;
- EvidenceScoring now reports `working_active_subject_count=21`,
  `working_expired_skipped_count=147`, `working_unknown_status_count=0`;
- monitor reports `expired_used_in_scoring_count=0` and PASS
  `left_brain_expired_working_not_scored`;
- monitor remains WARN because of unrelated/open observation items:
  right-brain historical SpeakGate gaps, SessionMirror pending sessions,
  approved proposal follow-up, RH-31 eval warnings, and RH-26 casual-empty.

Required design work:

1. define feature-based EvidenceScoring v2 in report-only mode before replacing
   legacy hash scoring;
2. add SelfEvolution novelty/idempotency gates for unresolved proposals and
   repeated score refs;
3. route MemorySources / owner / expression feedback into GovernanceFeedback as
   bounded evidence only;
4. filter or explicitly downweight expired working in scoring and reflection;
5. keep approved proposal follow-up visible while designing a separate
   execution-decision gate;
6. split production cadence from the test-host cognitive-loop integration
   harness;
7. reduce ContextRouter/Ingress classification duplication through parity tests
   and a deprecation path.

Promotion signal:

- feature scoring reports compare against legacy scores without changing live
  behavior;
- duplicate/unresolved SelfEvolution proposals are skipped and counted;
- expired working usage is visible and no longer treated as active evidence;
- feedback backflow can produce owner-reviewed proposals without direct live
  mutation;
- approved proposals reach explicit execution-decision visibility without
  creating execution tickets.

Stop signal:

- scoring starts driving live action before owner review;
- proposal approval creates execution tickets or `actual_execute=true`;
- feedback directly mutates routing, prompt, cadence, or delivery;
- expired working dominates scoring/reflection;
- repeated unresolved proposals continue to be created.

## Active P2 Queue

### P2-A - RH-17 Physical Retention Apply

Status:

- dry-run helper implemented;
- latest dry-run had `action_count=0` and `canonical_paths_touched=[]`.

Do not implement physical prune until metadata/report archive candidates exist
and the dry-run output has been reviewed.

### P2-B - RH-32 Consolidation Suggestions

Status: planned/deferred.

Only start after deterministic suggestion contract, retention story, and enough
real feedback/monitor data exist.

Hard boundary:

- suggestions only;
- no automatic approval, deletion, crystallized write, or canonical prune.

### P2-C - RH-33 Top-Of-Mind Scoring Only

Status: planned/deferred.

Blocked until:

- `successful_use` is defined without equating it to "selected by router";
- feedback volume and MemorySources data are sufficient;
- dry-run score reports exist.

### P2-D - Deferred Task Stack / Multi-Task Anchor

Status: deferred.

Current design intentionally tracks one current foreground task and the latest
explicitly deferred foreground task. Do not add a stack until repeated real
deferred-resume failures justify it.

### P2-E - Hermes Upgrade Live Validation

Status:

- compatibility gate exists;
- full live validation waits for the next Hermes version such as v0.15.0.

### P2-F - Public Productization Pass

Status: started but not mature.

Remaining work:

- clean-machine install validation;
- short user-facing configuration guide;
- RH-34/RH-35 owner-governance family map that groups the sub-RH history into
  digest, action processor, renderer, reply tool, review surface, Hermes cron,
  aging, and proposal-follow-up responsibilities;
- public material drafts explaining the problem Memory-OS solves;
- avoid turning research logs into the first user entry point.

## Explicitly Deferred / Do Not Start Yet

- real outbound send from Speak Gate;
- production/Sannai enablement;
- bounded-live LLM judge;
- LLM-only routing;
- automatic crystallized approval;
- automatic identity or relationship writes;
- automatic canonical deletion;
- vector/RRF/graph retrieval branch before RH-31 proves a semantic gap;
- RH-32 or RH-33 before feedback and retention evidence matures.

## RH-31 First Failure Attribution Table

Source report:

```text
eval/reports/memory-os-rh31/rh31_20260524T183908544131Z
status=warning
failure_count=4
boundary_true_count=0
forbidden_field_count=0
```

| Failure | Adapter | Case | What failed | Current interpretation | Next action |
| --- | --- | --- | --- | --- | --- |
| lexical miss | `grep` | `mechanism_noise_001` | baseline lexical search found no match | Weak baseline / fixture coverage signal, not a live bug | Do not add guard; review whether fixture expects lexical recall or should be baseline-negative |
| FTS miss | `memory_os_fts` | `diagnostic_grounding_001` | indexed search found no hit | Diagnostic grounding should come from current runtime facts, not historical FTS alone | Do not tune live route; keep diagnostic adapter as projection/status-path check |
| FTS miss | `memory_os_fts` | `mechanism_noise_001` | indexed search found no hit | Mechanism-heavy casual noise should not necessarily be retrievable | Treat as measurement signal; no live guard |
| projection miss | `context_projection` | `candidate_boundary_001` | eval reported `active_task` headings instead of candidate-review-focused context | Attributed to fixture/adapter bug: candidate corpus was not written to candidate queue, fixture wording was mechanism-heavy, and adapter inferred route from headings | Fixed fixture and adapter; no live guard |

Decision:

```text
Do not add the first RH-31 live guard from this scorecard alone.
```

P1-B attribution update:

```text
candidate_boundary_001 was an eval fixture/adapter attribution bug:
  - synthetic candidate documents did not populate the candidate queue;
  - fixture wording used mechanism-heavy "crystallized candidates" text;
  - context_projection inferred actual_route from headings instead of the
    router report.

After the fix:
  context_projection/candidate_boundary_001 = pass
  actual_route = candidate_review
  actual_headings include Crystallized Review Candidates
  failure_count = 3
  failure_class_distribution = {"fts_miss": 2, "lexical_miss": 1}
  boundary_true_count = 0
  forbidden_field_count = 0

10.20.3.200 no-write live projection already selected
Crystallized Review Candidates for the same public query, so no live guard is
justified.
```

## Immediate Next Work

Recommended next sequence:

1. Keep this roadmap committed and treat it as the active queue.
2. Use the RH-31 attribution table to decide whether `candidate_boundary_001`
   deserves a reviewed fixture.
3. Continue live Telegram testing for RH-28 candidate quality.
4. Add monitor fields for would-send/silent artifacts only if automatic
   expression behavior becomes the next evaluation focus.
5. Do not start RH-32/RH-33 until their gates in this document and the 29号
   contract are satisfied.
