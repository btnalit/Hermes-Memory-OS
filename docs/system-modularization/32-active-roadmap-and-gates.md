# 32 - Active Roadmap And Gates

Status: active planning index
Date: 2026-05-25
Scope: Memory-OS v0.1 test-host roadmap, remaining development queue, and
promotion gates

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

The queue below must stay consistent with those source documents and with live
`10.20.3.200` monitor evidence.

## Current Live Baseline

Latest read-only monitor evidence used for this roadmap refresh:

```text
host: 10.20.3.200
date_utc: 2026-05-25T03:14:31Z
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
session_mirror: session_count=50, covered=26, pending=24
wandering_mind: would_send_count=10
proposal_queue: candidate_count=14, pending candidate state count=13
evidence_scoring: score_count=545
crystallized_records: 0
RH-31 eval: warning, failure_count=4
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
| RH-31.0-31.3 eval harness | implemented | first deterministic scorecard exists; warning findings remain |
| RH-17 metadata/report retention helper | implemented as dry-run | no canonical paths touched; physical apply remains open |
| Hermes upgrade compatibility gate | designed and script-backed | future Hermes version upgrade still needs live run |

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

Status: first scorecard generated; attribution table added below.

Reason:

- RH-31 has warning findings, but warnings are measurement signals, not live
  behavior fixes by themselves.

Next action:

1. review the four current failures in the table below;
2. decide whether any failure maps to a real Telegram/live finding;
3. only then create a redacted fixture or a deterministic guard proposal.

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
- latest live module status shows `wandering_mind.would_send_count=10`;
- monitor checks hard send boundary but does not yet expose a clear
  would-send/silent artifact trend.

Why it matters:

- this is the planned "automatic speech" line, but v0.1 must stay at
  `would_send` only. It should produce candidate expression evidence without
  actually sending messages.

Next action:

- add monitor fields for bounded would-send/silent artifact counts if we want
  to evaluate expression behavior;
- do not enable real send.

Promotion signal:

- would-send artifacts are bounded, explainable, and sparse;
- Wandering Mind remains non-task and no-send;
- Speak Gate distinguishes no-send, would-send, and blocked send.

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
- expected marker counts are not yet compared against safe session activity.

Next action:

- select a safe session-count source before warning on missing hook markers.

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
- latest live status reports `session_count=50`, `covered_session_count=26`,
  and `pending_session_count=24`;
- latest dry-run reports `new_event_count=24`, `written_event_ids=[]`, and
  `findings=[]`;
- read-only topic-signature correlation found:
  - pending sessions: `automation_orchestration=1`, `memory_os=8`;
  - provider-captured events: `automation_orchestration=33`,
    `internet_data_collection=10`, `memory_os=53`, `comfyui_media=47`,
    `mindvideo_api=10`;
  - pending sessions did not show an `internet_data_collection` pending-only
    signal;
- no recurring SessionMirror apply is enabled.

Why it matters:

- low-clue recall and "continue yesterday" behavior depend on the event stream
  being a reasonably complete cross-entry source;
- pending sessions may explain cases where the owner expects a topic to be in
  global memory but the provider path never captured it.

Next action:

- decide whether a one-time apply is still useful as a coverage improvement,
  but do not treat it as the likely fix for the earlier
  `internet_data_collection` candidate omission;
- update monitor with pending/covered session counts before any recurring
  mirror behavior is considered.

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
| projection miss | `context_projection` | `candidate_boundary_001` | projected `active_task` headings instead of candidate-review-focused context | Potential routing/projection fixture gap; could become actionable if reproduced in live candidate/crystallized prompts | Convert to reviewed fixture or live repro before any RH-31 guard |

Decision:

```text
Do not add the first RH-31 live guard from this scorecard alone.
```

The only potentially actionable row is `candidate_boundary_001`, and it still
needs either live evidence or a reviewed fixture correction.

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
