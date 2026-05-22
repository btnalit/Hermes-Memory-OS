# RH-26 Context Relevance Router Design

## Purpose

RH-26 defines a controlled relevance router for Memory-OS prefetch context.

The goal is not to remove Working Memory or Conversation Carryover. The goal is
to stop treating them as fixed prompt sections for every ordinary turn, and to
make Memory-OS decide which context sections are actually useful for the current
foreground turn.

RH-25b fixed the urgent small-context drift case:

```text
cancellation / vague continuation turn -> Current Foreground Task only
ordinary turn                           -> existing Memory-OS context stack
```

RH-26 is the next maturity step:

```text
ordinary turn -> route by turn type, current task, source class, relevance,
                 freshness, risk, and budget
```

The first implementation must be dry-run/report-only. It should show what would
have been included or dropped, without changing live prompt injection. Apply
mode comes only after 10.20.3.200 data and review show the router is safer than
the current fixed assembly.

## Why This Exists

Working Memory and Conversation Carryover are useful:

- Working Memory keeps active facts, user preferences, task clues, and recent
  important state available.
- Conversation Carryover gives cross-session and post-compression continuity,
  especially from DeepReflection's bounded carryover cards.
- Indexed Recall retrieves older specific records when the current query asks
  for them.

The failure mode is not that these layers are wrong. The failure mode is static
projection:

```text
current turn: "算了，别做视频了"
static context: Working Memory + Conversation Carryover mention Memory-OS /
                Hindsight / governance status
model behavior: pivots into unrelated system-memory discussion
```

This is a context-selection problem. The canonical Memory-OS data may be correct
while the prompt assembly is still too broad for the turn.

## Related External Patterns

These references are not blueprints to copy, but they validate the direction:

- MemGPT frames long-lived agents as a virtual context-management problem over
  multiple memory tiers, not as a single ever-growing prompt:
  <https://arxiv.org/abs/2310.08560>
- Generative Agents combine memory stream, reflection, and dynamic retrieval to
  plan behavior:
  <https://arxiv.org/abs/2304.03442>
- LangGraph's memory guide explicitly warns that long histories can distract
  models with stale or off-topic content, and separates short-term thread state
  from long-term memory:
  <https://langchain-5e9cc07a.mintlify.app/oss/python/concepts/memory>
- Letta memory blocks use labels, descriptions, and limits so an agent can know
  what a block is for:
  <https://docs.letta.com/guides/core-concepts/memory/memory-blocks>
- Zep ranks time-aware facts and summaries, and recommends grounding responses
  in relevant facts rather than relying only on high-level summaries:
  <https://help.getzep.com/v2/facts>
- Recent active-memory research treats working memory management as an action
  or active cognitive workspace problem, not passive retrieval:
  <https://arxiv.org/abs/2510.12635>

The Memory-OS design should preserve its own boundaries while adopting the
shared lesson: context should be selected, routed, and bounded.

## Design Principle

The router is a gate in front of prompt projection, not a memory writer.

```text
canonical data stays complete
router decides what is visible this turn
router never approves, sends, executes, crystallizes, or edits identity
```

The LLM may eventually assist with relevance scoring, but it must not be the
only decision maker. RH-26 starts deterministic.

## Non-Goals

RH-26 must not:

- delete, rewrite, or compact canonical Memory-OS records
- weaken RH-25b foreground-only handling for cancellation or vague continuation
  turns
- make DeepReflection cards bypass their safety filters
- allow an LLM judge to decide final inclusion by itself
- create working items, candidates, proposals, sends, executes, identity
  writes, relationship writes, or crystallized approvals
- read private raw transcripts beyond existing safe summaries
- change live prefetch behavior in the first dry-run/report slice
- move carryover injection from provider prefetch to Hermes `pre_llm_call`

## Existing Context Sections

Current `build_prefetch()` assembles sections in this rough order:

```text
Current Foreground Task
Identity Memory
Continuity Bridge
Conversation Carryover
Working Memory
Relationship Memory
Crystallized Review Candidates
Crystallized Memory
Indexed Recall
Recent Event Summaries
```

RH-26 treats each of these as a section candidate with:

- `section_name`
- `source_class`
- `text`
- `char_cost`
- `risk_flags`
- `freshness`
- `relevance_score`
- `include_decision`
- `reason_codes`

The initial router can operate at section level. A later version may operate at
item/card level inside Working Memory and Conversation Carryover.

## Turn-Type Routes

The router first classifies the current turn. Deterministic route rules run
before relevance scoring.

### Route: `diagnostic_current_status`

Trigger:

- explicit current provider/backend/status/health/count questions
- existing RH-21/RH-24 diagnostic patterns

Context:

```text
Diagnostic Grounding only
Current Memory-OS Runtime Facts only
historical recall suppressed
```

Reason:

- current runtime facts should not compete with stale historical claims

### Route: `foreground_control`

Trigger:

- cancellation or rejection: `算了`, `别做`, `停止`, `cancel`, `stop`, `abort`
- vague continuation with existing anchor: `继续`, `继续当前任务`, `continue`

Context:

```text
Current Foreground Task only
```

Reason:

- RH-25b safety rule. The user is controlling the foreground task, not asking
  for memory background.

This route must remain hard-coded and must not be overridden by LLM relevance
scoring.

### Route: `active_task`

Trigger:

- concrete task, install, fix, test, analyze, deploy, render, debug, download,
  or inspect request
- current foreground anchor exists and the query refers to a concrete task

Context:

```text
Current Foreground Task
task-relevant Working Memory items
task-relevant Indexed Recall if query has entities
Recent Event Summaries only if source matches the task
```

Normally exclude:

- broad Conversation Carryover
- diagnostic-style memory-system summaries
- review candidates unless the task asks for candidates

Reason:

- task work needs active facts, not relationship drift or system-report tone.

### Route: `casual_continuity`

Trigger:

- ordinary conversation, opinion, feeling, design discussion, or "你觉得..."
- no explicit current runtime/provider/status request
- no active tool task that needs foreground control

Context:

```text
Conversation Carryover
top ordinary Working Memory items
Relationship Memory if available and safe
Current Foreground Task only if still relevant
```

Normally exclude:

- diagnostic grounding
- status/count facts
- candidates unless explicitly asked
- stale runtime facts

Reason:

- this is where continuity should feel natural, not like a report.

### Route: `candidate_review`

Trigger:

- user asks about candidates, crystallized memory, long-term memory, review
  queue, or whether something is already approved

Context:

```text
Crystallized Review Candidates
Crystallized Memory
Current Foreground Task if relevant
Diagnostic runtime counts only when explicitly asked
```

Reason:

- candidate-vs-crystallized wording must remain explicit.

### Route: `memory_architecture_discussion`

Trigger:

- user asks how Memory-OS is designed, whether the architecture is good, or how
  memory layers relate
- not a current provider/status question

Context:

```text
Conversation Carryover
Working Memory filtered for ordinary design discussion
Indexed Recall for architecture/design terms if relevant
```

Normally exclude:

- current status counts unless explicitly asked
- old Hindsight URLs
- stale index-health statements

Reason:

- architecture discussion benefits from continuity, but not runtime status
  leakage.

## Deterministic Relevance Scoring

Dry-run v0 should use cheap deterministic signals:

```text
score = entity_overlap
      + keyword_overlap
      + foreground_task_overlap
      + source_class_bonus
      + freshness_bonus
      + explicit_route_bonus
      - diagnostic_style_penalty
      - mechanism_leak_penalty
      - stale_runtime_penalty
```

Initial candidate weights:

```text
entity_overlap:           +0.30 per shared entity, capped at +0.60
keyword_overlap:          +0.15 per shared keyword, capped at +0.45
foreground_task_overlap:  +0.50 when section overlaps current anchor
source_class_bonus:       route-dependent
freshness_bonus:          +0.10 for recent foreground/task events
explicit_route_bonus:     +0.75 for sections explicitly required by route
diagnostic_style_penalty: -0.80
mechanism_leak_penalty:  -0.80
stale_runtime_penalty:   -0.60
```

The exact numbers are starting values for reports, not a claim of optimality.
They should be stored in code as named constants so tests can reason about
decisions.

## Section Inclusion Policy

Dry-run reports should output:

```json
{
  "schema_version": "memory-os.context_router.v0",
  "mode": "dry_run",
  "route": "active_task",
  "query_redacted": "安装 ComfyUI Impact Pack",
  "budget_chars": 2200,
  "selected_sections": [
    {
      "section": "Current Foreground Task",
      "char_cost": 340,
      "score": 1.0,
      "reason_codes": ["required_by_route", "foreground_anchor"]
    }
  ],
  "dropped_sections": [
    {
      "section": "Conversation Carryover",
      "score": 0.1,
      "reason_codes": ["route_excludes_broad_carryover"]
    }
  ],
  "risk_flags": [],
  "would_change_live_prefetch": true
}
```

The dry-run report must not include private raw bodies. It may include section
names, reason codes, scores, source classes, and redacted snippets bounded to a
small preview length.

## Budget Policy

The router should allocate budget by route.

Initial defaults:

```text
foreground_control:
  Current Foreground Task: 100%

diagnostic_current_status:
  Diagnostic Grounding: 100%

active_task:
  Current Foreground Task: up to 35%
  task-relevant Working Memory: up to 30%
  Indexed Recall: up to 25%
  Recent Event Summaries: up to 10%

casual_continuity:
  Conversation Carryover: up to 45%
  ordinary Working Memory: up to 35%
  Relationship Memory: up to 20%

candidate_review:
  Review Candidates / Crystallized: up to 70%
  Foreground / Carryover: up to 30%

memory_architecture_discussion:
  Conversation Carryover: up to 35%
  ordinary Working Memory: up to 35%
  Indexed Recall: up to 30%
```

These are caps, not minimums. Empty or low-relevance sections should not consume
budget just because a route allows them.

## LLM Judge Policy

RH-26 v0 does not use an LLM judge.

Future optional mode:

```text
context_router_judge_mode:
  disabled       # default
  report_only    # LLM judge runs, but cannot affect selected context
  bounded_vote   # LLM may veto low-confidence sections, deterministic gates remain final
```

Allowed LLM judge question:

```text
Given the current user turn and a redacted memory section, is this section
helpful for answering the turn without changing topic?
Return: useful / not_useful / risky, plus one short reason code.
```

Forbidden LLM judge authority:

- final inclusion when deterministic hard route excludes a section
- deciding whether secrets are safe
- approving candidates or crystallized memory
- changing identity, relationship, send, execute, or proposal state
- weakening RH-25b foreground-only behavior

If the judge is unavailable, the router must behave as if judge mode is
disabled.

## Implementation Plan

### DRY-00 Documentation Gate

Files:

- `docs/system-modularization/21-context-relevance-router-design.md`
- `docs/system-modularization/08-runtime-hardening-plan.md`

Acceptance:

- design is reviewed before code
- RH-26 is recorded as dry-run first
- no live prefetch behavior changes in this gate

### RH-26.1 Router Data Model

Files:

- create `plugins/memory/memory_os/context_router.py`
- create `tests/plugins/memory/test_memory_os_context_router.py`

Public seam:

```python
def plan_context_route(query: str, *, current_task_anchor: str | None = None) -> dict[str, Any]:
    ...

def route_context_sections(
    query: str,
    *,
    sections: list[ContextSection],
    current_task_anchor: str | None = None,
    budget_chars: int,
    mode: str = "dry_run",
) -> ContextRouterReport:
    ...
```

Acceptance:

- cancellation and vague continuation route to `foreground_control`
- explicit provider/status questions route to `diagnostic_current_status`
- concrete ComfyUI/install/debug tasks route to `active_task`
- casual "你觉得这套记忆系统怎么样" routes to `casual_continuity`
- candidate/crystallized questions route to `candidate_review`
- no private bodies in reports

### RH-26.2 Section Candidate Extraction

Files:

- modify `plugins/memory/memory_os/prefetch.py`
- test in `tests/plugins/memory/test_memory_os_context_router.py`

Approach:

- keep existing section builders
- add an internal helper that builds section candidates before final formatting
- preserve existing `build_prefetch()` output unless `context_router_mode` is
  explicitly enabled

Acceptance:

- existing prefetch tests still pass
- dry-run report can show what each existing section would score
- no behavior change for default provider prefetch

### RH-26.3 CLI Dry-Run

Files:

- modify `plugins/memory/memory_os/cli.py`
- tests in existing CLI test module, or add a focused context-router CLI test

Command shape:

```text
hermes memory_os context-router dry-run --query "继续当前任务"
hermes memory_os context-router dry-run --query "你觉得这套记忆系统怎么样"
```

Acceptance:

- prints JSON report
- reports route, selected/dropped sections, reason codes, budget
- does not print raw private bodies
- can run on 10.20.3.200 without mutating Memory-OS data

### RH-26.4 Host Validation On 10.20.3.200

Run dry-run reports for prompts from real findings:

```text
1. "太垃圾了，算了，你还是别做视频了"
2. "继续当前任务"
3. "我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？"
4. "当前记忆架构是什么？"
5. "那些 crystallized candidates 是已经沉淀的长期记忆吗？"
6. "帮我继续安装 ComfyUI 插件"
7. "这个先放一下，明天再说"
```

Acceptance:

- prompts 1 and 2 select foreground-only
- prompt 3 selects casual continuity without diagnostic status sections
- prompt 4 selects diagnostic current runtime facts
- prompt 5 selects candidate/crystallized sections with review-only wording
- prompt 6 selects active-task sections
- prompt 7 is reported as an open deferred-cancellation case, not silently
  treated as perfect

### RH-26.5 Apply Gate

No apply mode until:

- Claude/user review passes the dry-run reports
- 10.20.3.200 has at least one real small-context session after RH-26 dry-run
- RH-22 conversation regression still passes
- doctor is `ok`
- no-send/no-execute/no-identity/no-crystallized boundaries remain true

When apply is enabled, it must be controlled by config:

```json
{
  "context_router": {
    "enabled": true,
    "mode": "apply",
    "llm_judge_mode": "disabled"
  }
}
```

Default remains disabled or dry-run.

## Test Matrix

Required tests:

```text
test_router_routes_cancellation_to_foreground_control
test_router_routes_vague_continue_to_foreground_control_when_anchor_exists
test_router_routes_explicit_status_to_diagnostic
test_router_routes_casual_memory_opinion_to_casual_continuity
test_router_routes_candidate_question_to_candidate_review
test_router_active_task_drops_unrelated_hindsight_working_memory
test_router_casual_continuity_keeps_ordinary_carryover
test_router_report_redacts_secrets
test_router_default_does_not_change_build_prefetch_output
test_router_dry_run_cli_does_not_write_store
```

Host-level validation:

```text
hermes memory_os context-router dry-run --query ...
hermes memory_os conversation-regression evaluate --transcript ...
hermes memory_os doctor
```

## Open Questions For Review

1. Should RH-26 start as section-level routing only, or item-level routing
   inside Working Memory immediately?
2. Should deferred cancellation (`明天再说`, `等下`, `这个先放一下`) be part of
   RH-26, or remain RH-25.1?
3. Should diagnostic-style filtering stay as a hard penalty, or should
   diagnostic sections be impossible outside diagnostic routes?
4. Should `memory_architecture_discussion` be separate from
   `casual_continuity`, or is that too many routes for v0?
5. Should apply mode require a new RH review after dry-run, or can the same
   slice include apply behind a disabled config?

## Recommended Decision

Proceed with RH-26.1 through RH-26.4 only.

Do not implement apply mode yet. The first deliverable should be a read-only
router report that proves Memory-OS can distinguish:

- foreground task control
- active task work
- casual continuity
- current diagnostic/status questions
- candidate/crystallized review questions

This lets us improve Working Memory maturity without weakening the current
Memory-OS safety boundary.
