# 28 - RH-28 Low-Clue Recall Router Design

Status: implemented and validated on 10.20.3.200 in deterministic and report-only modes
Date: 2026-05-24
Scope: test-host first; production-safe defaults unchanged

## Goal

RH-28 generalizes the first low-clue recall guard from document 24 and the
RH-25.1 `继续昨天那个` finding into a small routing layer for underspecified
recall requests.

The goal is not to make Memory-OS guess better. The goal is to make Memory-OS
avoid overconfident recall when the owner gives too little identifying
information.

Target behavior:

```text
low-clue query -> collect bounded candidates -> score confidence/margin
              -> answer directly only when confidence is high
              -> otherwise ask the owner to choose
              -> record the selected clarification as feedback metadata
```

## Why This Exists

Two real Telegram findings created the need:

1. `你还记得我之前跟你说过的一个设计吗？`

   Before RH-28 v0, the assistant guessed one design too early. After the
   deterministic guard, it offered several likely directions and asked for an
   anchor.

2. `/new` then `继续昨天那个。`

   Before RH-25.1, the assistant could continue the latest recalled topic
   (`n8n`) instead of the intended deferred foreground task. RH-25.1 now:

   - resumes an explicitly deferred foreground task when one exists
   - asks for a choice when no deferred task was recorded

These are the same class of problem:

```text
the user supplied a deictic reference, but not a stable referent
```

Examples:

- `继续昨天那个`
- `继续上次那个`
- `那个设计`
- `刚才那个`
- `按之前的来`
- `你还记得我之前说的那个方案吗`

The system must not treat "most recent" as "certainly intended."

## External Reference Synthesis

This design is a synthesis, not an implementation-equivalence claim.

### Conversational Search Clarification

Conversational search literature treats underspecified or ambiguous queries as
a mixed-initiative problem: the system should ask clarification questions when
the user's information need is not identifiable. IBM's DialDoc work frames the
task as selecting the next clarification question from conversation context and
retrieved passages.

Source:

- https://arxiv.org/abs/2112.07308

Design lesson:

- ambiguity should trigger clarification, not a confident single answer
- candidates should be grounded in retrieved evidence, not invented

### Zero-Shot Clarification

Zero-shot clarification work argues that open-domain systems cannot rely on
training data covering every possible query and topic. It proposes constrained
clarification generation with templates and facets.

Source:

- https://arxiv.org/abs/2301.12660

Design lesson:

- do not build an infinite keyword list
- use a small set of query-shape detectors plus structured candidate facets
- template-based questions are acceptable for v0 because they are predictable

### Negative Feedback And Candidate Selection

Clarification based on negative feedback uses previous "no" answers to improve
the next question and reduce user effort.

Source:

- https://arxiv.org/abs/2107.05760

Design lesson:

- a user selecting option 2 or rejecting an option is useful metadata
- this feedback should be recorded as a bounded signal, not as long-term memory

### Agent Memory Context Hierarchy

LangGraph/LangChain memory docs distinguish semantic, episodic, and procedural
memory and note that relevant examples/memories need their own retrieval logic.
Letta's context hierarchy distinguishes always-in-context memory blocks,
searchable files, archival memory, and external RAG.

Sources:

- https://docs.langchain.com/oss/python/concepts/memory
- https://docs.letta.com/guides/core-concepts/memory/context-hierarchy

Design lesson:

- low-clue recall should search candidate metadata across memory layers
- it should not load every possible memory body into context
- small, important, high-confidence anchors can be foreground; large history
  stays searchable

### ChatGPT Memory Controls

OpenAI describes saved memories and reference chat history as separate
mechanisms, with user control, manageability, and top-of-mind prioritization.

Source:

- https://help.openai.com/en/articles/8590148-memory-in-chatgpt

Design lesson:

- a mature memory system uses relevance and recency, not blind injection
- owner-visible source attribution and feedback are important
- Memory-OS should keep owner approval stricter than ChatGPT: feedback can tune
  recall behavior, but it must not auto-approve crystallized memory

## Current 10.20.3.200 Reality Check

Read-only check on 2026-05-24:

```text
gateway=active
heartbeat=active/enabled
cognitive_loop=active/enabled
index_health=healthy
doctor=ok with expected hindsight_adapter_disabled warning
context_router=apply
apply_routes=["all"]
llm_judge=disabled
memory_sources.enabled=true
memory_sources.mode=metadata_only
memory_sources.retention_days=30
MemorySources record_count=9
MemorySources feedback_count=1
MemorySources boundary_true_count=0
MemorySources forbidden_field_findings=[]
RH-26 casual empty context remains expected WARN
```

Implications:

- RH-28 should stay deterministic first.
- RH-28 can rely on RH-29 Memory Sources and RH-30 feedback metadata.
- RH-28 must not require LLM judge mode.
- RH-28 must not assume Memory-OS can directly control Hermes `session_search`.
  It can only constrain Memory-OS prefetch and provide candidate/clarification
  instructions to the model.
- The correct public CLI entry on the test host is the shell alias
  `hermes memory-os-agent-os ...`; `hermes memory_os ...` is not a general
  plugin command on this install.

## Non-Goals

RH-28 does not:

- add a Top-of-Mind tier
- add a task stack
- change canonical events
- change working memory
- create candidates
- approve crystallized records
- write identity or relationship memory
- send messages
- execute actions
- export to Hindsight
- require LLM judge mode
- call Hermes `session_search` from provider code in v0
- read or print raw private message bodies

## Design Decision

RH-28 should be a confidence-based low-clue recall router.

It has four layers:

1. low-clue detection
2. bounded candidate collection
3. confidence and margin decision
4. clarification feedback

This is better than a large keyword table because only layer 1 uses a small
query-shape detector. The actual content comes from candidate metadata.

## Layer 1 - Low-Clue Detection

The detector classifies query shape, not topic.

Trigger when the query contains:

- deictic reference: `那个`, `那个设计`, `上次那个`, `昨天那个`, `刚才那个`
- vague continuation: `继续那个`, `继续昨天那个`, `继续上次那个`
- vague recall: `还记得我之前说过的`, `之前那个方案`
- low entity count: no concrete project/tool/file/source/entity beyond the
  deictic phrase

Do not trigger when the query has a clear anchor:

- `继续 ComfyUI 的 layout_report 问题`
- `互联网数据采集系统怎么分层`
- `那些 crystallized candidates 是长期记忆吗`
- `当前 Memory-OS 架构是什么`

Initial output:

```json
{
  "route": "ambiguous_recall",
  "reason_codes": ["low_clue_recall", "deictic_reference"],
  "query_has_explicit_entity": false
}
```

## Layer 2 - Bounded Candidate Collection

RH-28 should build candidate options from metadata only. It must not print
private bodies or raw conversation turns.

Candidate sources, in priority order:

1. Deferred foreground task metadata.

   Path:

   ```text
   $HERMES_HOME/memory-os/system/deferred_foreground_tasks.jsonl
   ```

   Use when query resembles `继续昨天那个` or `继续上次那个`.

2. Memory Sources attribution records.

   Path:

   ```text
   $HERMES_HOME/memory-os/system/memory_sources.jsonl
   ```

   Use route, selected headings, source classes, created_at, and safe source
   ids. Do not use section bodies.

3. RH-30 feedback ledger.

   Path:

   ```text
   $HERMES_HOME/memory-os/system/memory_sources_feedback.jsonl
   ```

   Use ratings such as `useful`, `irrelevant`, `missing_context`, and future
   `clarification_selected` only as ranking hints.

4. Working memory metadata.

   Use kind, source_class, safe ids, and bounded non-private summaries already
   allowed in normal prefetch. Do not expose raw body.

5. Indexed recall metadata.

   Use safe event summaries and source ids. Do not print raw bodies.

6. Candidate/crystallized metadata.

   Candidates may appear as review-only options. They must never be described
   as approved long-term memory.

Candidate schema:

```json
{
  "candidate_id": "lcr_...",
  "title": "n8n 与智能体协作方案",
  "source_class": "event",
  "source_ref": "evt_...",
  "route": "casual_continuity",
  "created_at": "2026-05-24T05:31:17Z",
  "signals": {
    "deferred_anchor": false,
    "explicit_entity_overlap": 0,
    "freshness": 0.72,
    "feedback_boost": 0.1,
    "memory_source_recent": true
  }
}
```

Allowed candidate fields:

- title
- source_class
- safe source id
- route
- created_at
- score parts
- reason codes

Forbidden candidate fields:

- raw user prompt
- raw assistant response
- private message body
- raw file path
- secret/token/cookie
- private body hash

## Layer 3 - Confidence And Margin Decision

Initial deterministic scoring:

```text
score =
  deferred_anchor_bonus
  + explicit_entity_overlap
  + route_match_bonus
  + freshness_score
  + useful_feedback_bonus
  + same_session_bonus
  - rejected_feedback_penalty
  - mechanism_heavy_penalty
```

Suggested v0 thresholds:

```text
direct_resume:
  top_score >= 0.80
  and top_score - second_score >= 0.25
  and candidate has deferred_anchor or explicit entity overlap

confirm_one:
  top_score >= 0.65
  and top_score - second_score >= 0.20
  and no hard safety boundary applies

ask_choice:
  2-4 candidates exist
  and direct_resume condition is false

ask_keyword:
  fewer than 2 safe candidates exist
```

Response policies:

Direct resume:

```text
Continue the selected foreground task. Keep foreground-only if the query was a
vague continuation.
```

Confirm one:

```text
你是指「X」吗？如果是，我接着讲；如果不是，给我一个关键词。
```

Ask choice:

```text
你是指下面哪个？
1. X
2. Y
3. Z

回我编号就行。
```

Ask keyword:

```text
我现在没有足够线索确定你指哪个。给我一个关键词、项目名、时间点或文件名。
```

## Layer 4 - Feedback

When the owner selects an option, RH-28 should write an RH-30 feedback record.

Suggested new ratings:

- `clarification_selected`
- `clarification_rejected`
- `missing_candidate`

This remains feedback metadata. It must not:

- change router weights immediately
- create working memory
- create candidates
- approve crystallized records

Future scoring can use this metadata only after enough observations exist.

## LLM Role

LLM judge is not part of v0 apply.

Installer-facing decision:

- the Memory-OS installer may offer an optional LLM judge prompt during plugin
  installation
- default: disabled
- provider/model source: reuse the existing Hermes provider/model
  configuration
- no model or API key is hard-coded in Memory-OS
- no API key is written to Memory-OS config, audit, MemorySources, or docs

Suggested operator prompt:

```text
Enable LLM judge for low-clue recall? [none/report-only/bounded-vote] [none]
```

Allowed first enablement:

```text
mode=report-only
provider=hermes_default
model=null
```

`bounded-vote` must require explicit owner selection and must not be implied by
`--test-host`.

Allowed future report-only uses:

- compress option titles for readability
- cluster 10+ candidates into 2-4 groups
- propose a clarification question from already selected candidate facets

Forbidden uses:

- invent candidates
- override foreground-control rules
- decide that a candidate is approved long-term memory
- auto-select a candidate when deterministic score says ask choice
- use raw private bodies as ranking evidence

Failure behavior:

- if the Hermes provider/model is unavailable, RH-28 falls back to the
  deterministic decision
- report-only failures are logged as bounded metadata, not surfaced as memory
  facts
- bounded-vote must fail closed to deterministic behavior

Initial config shape:

```json
{
  "low_clue_recall": {
    "llm_judge": {
      "enabled": false,
      "mode": "report_only",
      "provider": "hermes_default",
      "model": null,
      "temperature": 0,
      "timeout_ms": 8000,
      "max_tokens": 160,
      "max_candidates": 4,
      "on_error": "deterministic_fallback"
    }
  }
}
```

Installer requirements:

- `production-safe`: write explicit disabled config
- interactive install: ask the optional LLM judge question above
- `--test-host`: may enable deterministic RH-28, but must not enable
  `bounded-vote` by default
- `--llm-judge-preset none|report-only|bounded-vote` is implemented by
  `scripts/install_memory_os.sh` and `scripts/install_memory_os_plugin.py`
- `report-only` can be used on 10.20.3.200 to collect judge quality without
  changing live answers

Current installer status on 2026-05-24:

- `scripts/install_memory_os.sh` exposes `--llm-judge-preset`
- `scripts/install_memory_os_plugin.py` writes `low_clue_recall` config for
  `none`, `report-only`, and `bounded-vote`
- `none` enables deterministic RH-28 and disables the LLM judge
- `report-only` reuses Hermes' configured provider/model through a bounded
  runtime-provider adapter
- `bounded-vote` is accepted as config but is deliberately skipped by RH-28
  runtime logic until a later apply gate
- if Hermes changes its provider/model internals and the adapter can no longer
  resolve or call the model, RH-28 degrades to deterministic fallback and
  status/doctor/monitor surface a warning instead of blocking Memory-OS

Monitor requirements after RH-28.2:

- configured `llm_judge_mode`
- bounded low-clue probe decision/candidate count
- report-only judge status and reason codes
- provider status/doctor include non-network judge availability metadata
- monitor performs the live report-only probe when report-only is configured
- provider/model availability failures must be WARN, not FAIL, as long as
  deterministic fallback remains intact

For report-only, live decision changes must remain `0` by design.

## 10.20.3.200 A/B Validation Matrix

The test host validated both disabled and report-only LLM judge modes before
any owner-facing behavior change is considered.

### Mode A - Deterministic Only

Config:

```json
{
  "low_clue_recall": {
    "enabled": true,
    "llm_judge": {
      "enabled": false,
      "mode": "none"
    }
  }
}
```

Purpose:

- prove RH-28 works without an LLM dependency
- establish the baseline candidate list, score, decision, and response shape
- verify no extra cost, no judge timeout, and no provider dependency

Required evidence:

- local tests pass
- 10.20.3.200 dry-run output for all validation prompts
- monitor reports `llm_judge_mode=none`
- `llm_judge_call_count=0`
- boundary true count remains zero

2026-05-24 result:

```text
llm_judge_preset=none
gateway=active pid=471982
monitor status=WARN
FAIL=[]
WARN=[rh26_casual_empty]
low_clue_recall.enabled=true
low_clue_recall.judge_mode=none
low_clue_recall.decision=ask_choice
low_clue_recall.llm_status=disabled
boundary_true_count=0
forbidden_field_count=0
```

### Mode B - LLM Judge Report-Only

Config:

```json
{
  "low_clue_recall": {
    "enabled": true,
    "llm_judge": {
      "enabled": true,
      "mode": "report_only",
      "provider": "hermes_default",
      "model": null,
      "temperature": 0,
      "timeout_ms": 8000,
      "max_tokens": 160,
      "max_candidates": 4,
      "on_error": "deterministic_fallback"
    }
  }
}
```

Purpose:

- compare judge recommendations against deterministic decisions
- measure timeout/error rate
- inspect whether judge improves option wording or ranking
- prove judge cannot change live prefetch behavior in report-only mode

Required evidence:

- same validation prompts as Mode A
- deterministic decision and live prefetch output are unchanged from Mode A
- judge metadata includes recommendation, confidence, reason, and candidate ids
  only
- no raw private body appears in judge input/output records
- `llm_judge_call_count > 0`
- `llm_judge_changed_decision_count=0`
- boundary true count remains zero

2026-05-24 result:

```text
llm_judge_preset=report-only
gateway=active pid=473191
monitor status=WARN
FAIL=[]
WARN=[rh26_casual_empty]
low_clue_recall.enabled=true
low_clue_recall.judge_mode=report_only
low_clue_recall.decision=ask_choice
low_clue_recall.llm_status=ok
boundary_true_count=0
forbidden_field_count=0
```

Report-only adapter note:

```text
The first remote run exposed that Hermes' OpenAI Codex provider on this host
requires the Responses streaming shape with an explicit instructions field.
RH-28 now uses a bounded Codex Responses streaming call for report-only judge
metadata. It does not use `hermes -z`, because that path can create ordinary
conversation events and is not acceptable for read-only judge probes.
```

### Mode C - Bounded Vote, Future Gate Only

Mode C is not part of the first implementation.

It can be considered only after Mode B has enough clean data.

Allowed upgrade:

```text
ask_choice -> confirm_one
```

Forbidden upgrade:

```text
ask_choice -> direct_resume
```

Reason:

- direct resume is the highest-risk behavior and should remain deterministic
  unless there is an explicit deferred foreground anchor or explicit entity
  overlap
- LLM judge can make the UX smoother by proposing a likely option, but it must
  not remove owner choice for ambiguous recall

### Comparison Report

For each validation prompt, collect:

```json
{
  "prompt_id": "continue_yesterday_no_record",
  "mode": "deterministic_only",
  "deterministic_decision": "ask_choice",
  "deterministic_top_candidate": "lcr_...",
  "candidate_count": 4,
  "llm_judge_mode": "none",
  "llm_recommendation": null,
  "llm_confidence": null,
  "changed_live_behavior": false,
  "boundary_true_count": 0,
  "forbidden_field_count": 0
}
```

Mode B adds:

```json
{
  "llm_judge_mode": "report_only",
  "llm_recommendation": "lcr_...",
  "llm_confidence": 0.72,
  "llm_reason_code": "candidate_title_matches_deictic_context",
  "changed_live_behavior": false
}
```

Pass criteria:

- Mode A and Mode B live behavior are unchanged
- Mode B judge metadata is useful enough to inspect
- no private body leakage
- no timeout/error rate above the configured threshold
- no boundary mutation

## Implementation Slices

### RH-28.1 Candidate Data Model And Scoring

Files:

- create `plugins/memory/memory_os/low_clue_recall.py`
- test `tests/plugins/memory/test_memory_os_low_clue_recall.py`

Acceptance:

- identifies low-clue query shapes
- does not trigger on explicit entity queries
- ranks candidates by deterministic score
- chooses `direct_resume`, `confirm_one`, `ask_choice`, or `ask_keyword`
- no private fields in candidate output

### RH-28.2 Prefetch Integration

Files:

- modify `plugins/memory/memory_os/prefetch.py`
- modify `plugins/memory/memory_os/context_router.py`
- test `tests/plugins/memory/test_memory_os_context_router.py`

Acceptance:

- `ambiguous_recall` route can include a bounded candidate-choice section
- no body leakage
- existing RH-25.1 deferred foreground control remains stronger than
  low-clue recall
- existing RH-26 route tests still pass

### RH-28.3 CLI Dry-Run

Files:

- modify `plugins/memory/memory_os/cli.py`
- shell alias continues to delegate through `memory-os-agent-os`

Command:

```text
hermes memory-os-agent-os low-clue-recall dry-run --query "继续昨天那个"
```

Acceptance:

- prints JSON with query route, candidates, scores, decision, and reason codes
- does not print raw private bodies
- can run on 10.20.3.200 without state mutation

### RH-28.4 LLM Judge Report-Only

Files:

- modify `plugins/memory/memory_os/low_clue_recall.py`
- modify `plugins/memory/memory_os/config.py`
- modify `scripts/install_memory_os.sh`
- modify `scripts/install_memory_os_plugin.py`
- modify `scripts/memory_os_3_200_monitor.py`

Acceptance:

- installer can offer optional `none|report-only|bounded-vote`
- default remains disabled
- report-only reuses Hermes provider/model configuration
- if Hermes provider/model config is unavailable, install must still support
  deterministic-only mode and must not leave a half-enabled judge
- no raw private bodies are sent to the judge
- judge output is stored only as bounded metadata
- report-only cannot change the deterministic decision
- monitor reports call/error/timeout counts
  `llm_judge_changed_decision_count=0`

### RH-28.5 Test-Host A/B Validation

Run on `10.20.3.200`:

```text
/new
继续昨天那个。

/new
你还记得我之前跟你说过的一个设计吗？

/new
继续 ComfyUI 的 layout_report 问题。
```

Expected:

- no-record `继续昨天那个` asks for a choice
- ambiguous design recall offers options
- explicit ComfyUI query continues directly
- monitor remains WARN-only
- MemorySources records the route and selected headings
- boundary true count remains zero
- Mode A (deterministic only) and Mode B (LLM judge report-only) are both
  deployed and tested
- Mode B produces judge metadata but does not change live behavior

## Validation Prompts

Use these as RH-28 regression prompts:

```text
1. 继续昨天那个。
   expected: ask choice unless a deferred anchor exists

2. 继续上次那个。
   expected: ask choice unless a deferred anchor exists

3. 你还记得我之前跟你说过的一个设计吗？
   expected: candidate options or keyword request

4. 继续 ComfyUI 的 layout_report 问题。
   expected: direct active-task continuation

5. 那个数据采集系统怎么分层？
   expected: internet/data-collection candidate wins or ask confirm if ambiguous

6. 当前 Memory-OS 架构是什么？
   expected: diagnostic_current_status, not ambiguous recall

7. 那些 crystallized candidates 是长期记忆吗？
   expected: candidate_review, not ambiguous recall
```

## Self-Review

### Against External References

- Mixed-initiative search: RH-28 asks for clarification when the query is
  under-specified instead of over-answering.
- Zero-shot clarification: RH-28 uses templates and candidate facets, not an
  unbounded learned classifier.
- Negative feedback: RH-28 records clarification choices as feedback metadata.
- Context hierarchy: RH-28 uses metadata first and does not load every memory
  body.
- ChatGPT Memory: RH-28 follows relevance and owner-control lessons without
  weakening Memory-OS approval boundaries.

### Against 10.20.3.200

- `context_router=apply` remains live. RH-28 deterministic mode and
  report-only judge mode were both tested on the host.
- MemorySources is already enabled and has safe route/source metadata to build
  on.
- RH-30 feedback exists but only has one record; therefore feedback should be a
  weak signal, not a hard routing control.
- `rh26_casual_empty` remains expected WARN; RH-28 must not lower thresholds
  just to avoid empty casual context.
- Provider CLI on this host is exposed through `memory-os-agent-os`; RH-28 CLI
  examples use that shell path.

### Gaps And Risks

1. Hermes `session_search` is outside Memory-OS provider control.

   RH-28 can inject guard/candidate instructions, but the model may still call
   session_search. The guard must therefore focus on response shape:
   "ask choice unless confident."

2. Candidate titles can be too generic.

   v0 should prefer source-derived titles with route/source metadata, and
   should ask for a keyword when titles are not distinguishable.

3. Feedback can self-reinforce.

   RH-30 feedback should only be a small boost until enough records exist.
   Selected once does not mean always intended.

4. A task stack remains out of scope.

   RH-25.1 stores the latest deferred foreground task only. RH-28 should not
   silently become task-stack infrastructure.

5. LLM judge can improve UX, but it adds a new dependency.

   The plan therefore requires an A/B test:
   deterministic-only first, then report-only with Hermes provider/model reuse.
   Report-only must not change live behavior. Bounded-vote remains a later
   gate and can only upgrade `ask_choice` to `confirm_one`, never to
   `direct_resume`.

6. Installer support is implemented, but remains opt-in.

   Current installers support `--llm-judge-preset none|report-only|bounded-vote`.
   The `none` preset is deterministic. `report-only` may call the configured
   Hermes provider/model, but it cannot change the deterministic decision.
   `bounded-vote` is stored as config only and is skipped by RH-28 runtime code.

7. Live prefetch must not block on report-only judge calls.

   RH-28b keeps report-only judging available through CLI and monitor probes,
   but the live `Recall Clarification Guard` uses deterministic ranking only.
   This preserves the optional judge as an observability tool while ensuring a
   slow or broken Hermes provider/model adapter cannot delay the owner's active
   turn.

8. High-confidence candidates should not sound like low-confidence choices.

   When deterministic scoring returns `direct_resume`, the guard may state the
   likely match briefly and ask for correction if wrong. Lower-confidence
   routes still ask the owner to choose from bounded options.

## Final Decision

Proceed with RH-28 as a low-clue recall router, not as a larger memory
architecture change.

Implementation status:

```text
RH-28.1: deterministic candidate model + scoring + tests implemented.
RH-28.2: prefetch guard integration implemented behind low_clue_recall config.
RH-28.3: provider CLI and shell alias dry-run implemented.
RH-28.4: report-only LLM judge config/installer support implemented.
RH-28.5: 10.20.3.200 deterministic and report-only validation completed.
RH-28b: live prefetch disables report-only judge calls and direct-resume guard
        wording no longer over-asks for clarification; deployed on
        10.20.3.200 with post-deploy monitor WARN-only / FAIL=[].
```
