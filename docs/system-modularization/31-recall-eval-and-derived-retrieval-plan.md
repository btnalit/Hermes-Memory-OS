# 31 - Recall Evaluation And Derived Retrieval Plan

Status: proposal for multi-party review; no implementation authority
Date: 2026-05-25
Scope: RH-31 planning only. This document does not change live behavior,
provider configuration, Memory-OS storage, router weights, scheduler steps, or
Hermes deployment state.

## Goal

Define a reviewable RH-31 plan for measuring Memory-OS recall failures and
adding deterministic relevance guards only when the evidence shows they are
needed.

This plan also records which lessons from agentmemory are useful as methodology
and which parts must stay out of Memory-OS because they conflict with the
canonical-file, owner-approved, profile-local Memory-OS route.

## Source Documents

This plan is constrained by:

- `07-validation-report-10.20.3.200.md`
- `08-runtime-hardening-plan.md`
- `29-memory-os-module-integration-contract.md`

External reference inspected for methodology only:

- `D:\Hermes agent manager\agentmemory-main`

Agentmemory is not a proposed dependency, provider, service, storage layer, or
runtime component for Memory-OS.

## Current Baseline From 07

The 10.20.3.200 test host has a usable Memory-OS baseline:

- provider is `memory_os`;
- gateway, heartbeat, cognitive loop, index, doctor, status-tool contract, and
  shell alias checks are healthy enough for continued observation;
- MemorySources has no boundary findings and no forbidden-field findings;
- low-clue ingress matrix matches expected route and heading behavior;
- DeepReflection remains no-send/no-execute/no-identity/no-crystallized-write;
- `crystallized_records=0`;
- expected WARN noise remains, especially `rh26_casual_empty`;
- audit density and working/candidate lifecycle still need observation;
- RH-31/RH-32/RH-33 should not advance without a real monitored finding or a
  review-approved evaluation result.

The implication for RH-31:

```text
RH-31 may design measurement and report-only analysis now.
RH-31 must not silently add new live routing, retrieval, scoring, or write
behavior before evaluation proves the failure class and the contract is filled.
```

## Current Roadmap Constraint From 08

The post-RH-28 roadmap says the next low-cost memory relevance work is:

1. RH-29 Memory Sources Attribution
2. RH-30 Relevance Feedback Audit
3. apply the module integration contract
4. RH-31 recall eval harness and baseline scorecard
5. RH-31 deterministic relevance guards only from scorecard-backed real findings
6. RH-32 consolidation suggestions, no approval
7. RH-33 top-of-mind scoring only

The important narrowing is:

```text
RH-31 is not "add vector search".
RH-31 is "find the recall failure class, then add the smallest deterministic
guard that fixes the real class".
```

The explicit deferrals still hold:

- no standalone Top-of-Mind tier;
- no LLM-only relevance decisions;
- no automatic crystallized approval;
- no automatic canonical deletion or rewriting.

## Contract Constraint From 29

Any RH-31 work must pass the module integration contract before implementation.

Hard rules that apply here:

- no second classifier for cancellation, vague continue, explicit deferred
  resume, low-clue recall, or diagnostic status routing;
- no direct prompt injection outside ContextProjection;
- no MemorySources or feedback ledger record becomes canonical memory;
- no score becomes owner approval;
- no candidate becomes crystallized memory without owner approval;
- LLM judge cannot override hard ingress routes;
- monitor evidence must be read-only, bounded, and private-body safe;
- local unit tests are insufficient if the failure crosses
  provider -> prefetch -> MemorySources -> monitor.

## External Reference Assessment

Agentmemory has useful retrieval and observability ideas:

- adapter-based eval runners;
- grep or substring baseline as an honesty anchor;
- small, fast internal benchmark corpora;
- dated scorecards and NDJSON reports;
- BM25 plus vector plus graph plus RRF as a possible retrieval structure;
- session diversification;
- hot/warm/cold style access scoring as a display or ranking signal;
- viewer/waterfall diagnostics as read-only operator UX inspiration.

It must not be absorbed as implementation:

- agentmemory is TypeScript plus iii-engine; Memory-OS is Python plus
  canonical local files plus rebuildable SQLite;
- its "0 external DBs" claim still depends on iii-engine primitives and KV
  state;
- the iii console/KV model conflicts with Memory-OS' readable, diffable,
  backupable profile-local source of truth;
- its broad tool surface is not appropriate for Hermes default context;
- historical security advisories include viewer XSS, remote shell script
  execution, default 0.0.0.0 binding, unauthenticated mesh sync, export path
  traversal, and incomplete privacy redaction.

Therefore RH-31 may reuse methodology, not code:

```text
re-derive in Python against Memory-OS files and SQLite;
do not import agentmemory;
do not run iii-engine;
do not switch memory.provider;
do not expose agentmemory tools to Hermes.
```

## RH-31 Decision

RH-31 should be named:

```text
Recall Failure Evaluation And Deterministic Relevance Guards
```

It has two stages:

1. Build an evaluation harness that identifies where recall fails.
2. Add deterministic guards only for failure classes proven by that harness or
   by live monitor evidence.

Derived vector/graph/RRF retrieval is an optional later branch, not the default
RH-31 path.

## Failure Taxonomy

Every recall miss or bad recall should be classified before a fix is chosen.

| Failure class | Meaning | Owning seam | Example fix class |
| --- | --- | --- | --- |
| `ingress_miss` | Same prompt shape enters different route by punctuation, platform, or foreground state. | `ingress.py` | shared deterministic ingress rule |
| `projection_miss` | Right source exists but ContextProjection drops or buries it. | `prefetch.py`, `context_router.py` | route budget or section cap change |
| `source_selection_miss` | MemorySources shows useful source class but candidate pool ignores it. | `memory_sources.py`, `low_clue_recall.py` | source diversity or negative feedback guard |
| `candidate_title_miss` | Candidate exists but title is generic, internal, or loses the identifying entity. | `low_clue_recall.py` | title/entity salience guard |
| `lexical_search_miss` | Canonical summary contains answer but FTS/projection cannot retrieve it. | `index.py`, FTS text projection | projection/tokenization fix |
| `semantic_gap` | Lexical retrieval fails but semantic/graph retrieval would recover the answer. | derived index layer | report-only vector/RRF branch |
| `diagnostic_pollution` | Runtime/status question receives stale historical memory. | diagnostic grounding | hard diagnostic suppression fix |
| `boundary_leak` | Private body, profile-crossing, candidate-as-approved, or identity leak appears. | relevant contract | stop/fix before features continue |
| `mechanism_leak` | Casual/companion answer exposes internal route/module language. | context projection and response guard | projection suppression or wording guard |
| `freshness_miss` | Stale memory beats fresh foreground/state facts. | router and runtime facts | freshness/source-class guard |

No RH-31 fix is valid until it names one row in this table or adds a reviewed
new row.

## Evaluation Harness

### Purpose

The eval harness is not only a leaderboard.

Its job is to answer:

```text
Did recall fail because retrieval could not find the fact, because the router
dropped it, because diagnostics suppressed it, because low-clue handling was
ambiguous, because freshness was wrong, or because a boundary correctly blocked
the answer?
```

### Evaluation Levels

RH-31 evaluation has two distinct levels.

Level 1 is context-quality evaluation:

- runs deterministic adapters;
- inspects `build_prefetch()` and related metadata;
- measures route, heading, selected source, dropped source, budget, forbidden
  field, and boundary behavior;
- does not claim to measure final model answers.

Level 2 is answer-quality audit:

- runs a bounded model-in-the-loop probe only after Level 1 exposes a case that
  cannot be judged from context alone;
- checks whether the model response overcommits, leaks mechanism language,
  treats candidates as approved memory, or ignores clarification discipline;
- is report-only and cannot change routing, memory writes, or live decisions.

This distinction is mandatory because several safety failures are answer
failures, not context failures. For example, a context adapter can prove that
`Recall Clarification Guard` was selected, but it cannot prove that the model
asked a good clarification question. It can prove that candidate text was
present, but it cannot prove the model avoided calling it approved memory.

RH-31 baseline scorecards must label each metric as:

```text
context_metric
answer_metric
performance_metric
```

The first approved RH-31 slice may ship context-quality evaluation only, but it
must not report answer-quality metrics as if they were measured.

### Proposed Location

Future implementation should use a new isolated tree:

```text
eval/memory_os/
eval/memory_os/runner/
eval/memory_os/adapters/
eval/memory_os/data/
eval/reports/memory-os-rh31/
docs/benchmarks/memory-os/
```

Reports should be gitignored unless explicitly promoted to a dated scorecard.
The repository `.gitignore` must include `eval/reports/` before any RH-31
runner writes local reports. Promoted scorecards belong under
`docs/benchmarks/memory-os/` and must be explicitly reviewed before staging.

### Required Adapters

| Adapter | Reads | Purpose |
| --- | --- | --- |
| `grep` | synthetic canonical summaries | honesty baseline |
| `memory_os_fts` | rebuildable SQLite FTS | current indexed recall |
| `context_projection` | `build_prefetch()` output | actual model-visible context |
| `low_clue_candidates` | low-clue candidate collector | ambiguous/deictic recall quality |
| `memory_sources_replay` | MemorySources metadata fixtures | attribution and source diversity |
| `diagnostic_grounding` | runtime fact fixtures | stale-history suppression |
| `future_hybrid_report_only` | derived embeddings/edges when approved | optional semantic gap measurement |
| `future_answer_audit` | bounded model responses when approved | answer-quality verification |

The first RH-31 approval package, covering Slices 31.0 through 31.3, should
build the first six deterministic adapters before any hybrid retrieval work.
Do not defer `low_clue_candidates` or `memory_sources_replay` into a later
feature gate unless reviewers explicitly split the implementation for workload
reasons; they are part of the baseline measurement surface. `future_answer_audit`
is a later report-only adapter and is required only when reviewers need
answer-quality evidence for a failure class such as `mechanism_leak` or
`candidate_approved_confusion`.

### Required Corpora

The corpus must be Memory-OS-specific. Agentmemory's `coding-agent-life-v1`
shape may inspire the harness, but its Rust CLI sessions do not test the
Memory-OS problem.

### Corpus Source And Weighting

Synthetic fixtures are necessary for safety and repeatability, but they are not
enough.

Before the first baseline scorecard, RH-31 should run a read-only inventory of
the current 10.20.3.200 evidence surfaces:

- MemorySources route distribution;
- MemorySources selected and dropped source-class distribution;
- feedback rating distribution;
- low-clue recall report shape;
- context-router heading probes;
- audit action distribution;
- working active/expired counts;
- candidate count and source distribution;
- monitor WARN/FAIL history.

The inventory must not read private bodies and must not run heartbeat,
cognitive loop, cleanup, shadow-journal apply, Hindsight export, or service
restart.

Fixture weights should then be assigned in two bands:

| Band | Purpose | Weight source |
| --- | --- | --- |
| frequency band | high-frequency real routes and misses | read-only inventory and MemorySources records |
| risk band | low-frequency but high-severity boundaries | contract-defined P0/P1 safety classes |

This prevents the scorecard from proving only dramatic safety cases while
under-testing ordinary lexical or projection misses.

### Online-Finding To Fixture Loop

Every live finding that affects recall quality must enter the eval loop before
it is considered closed:

```text
live monitor finding or owner correction
-> bounded evidence record
-> owner-approved redaction if real private content is needed
-> synthetic or redacted fixture
-> regression case in eval corpus
-> scorecard delta
-> guard proposal only if threshold is met
```

If the finding can be represented synthetically, use a synthetic fixture. If the
finding depends on real phrasing, real profile separation, or real miss shape,
create a separate owner-approved redacted package. Real private transcripts are
not copied into the repository.

Required fixture families:

1. Diagnostic grounding:
   - stale provider claims;
   - Hindsight-as-canonical false claims;
   - index health and heartbeat state questions;
   - expected source is current runtime facts, not historical recall.

2. Low-clue and deictic recall:
   - `继续昨天那个。`
   - `接着刚才那条`
   - `不是这个，另一个`
   - missing deferred record case;
   - active foreground anchor case.

   Low-clue gold labels must live in a reviewable label file. They are product
   decisions, not pure retrieval facts. If the team later decides a phrase
   should resume rather than ask, the label must be changed through review
   instead of silently counted as a regression.

3. Foreground task control:
   - cancellation;
   - defer current task;
   - explicit deferred resume;
   - unrelated working memory present and tempting.

4. Candidate versus crystallized:
   - review candidate exists;
   - approved crystallized record does not exist;
   - answer must not call candidate approved memory.

5. Profile isolation:
   - main and Sannai-like fixture roots;
   - cross-profile query attempt;
   - explicit read view versus forbidden direct read.

6. Mechanism leak:
   - casual companion prompt mentioning memory;
   - model-visible context must not force system-report style;
   - route names and section headings are not user topics.

7. Retrieval difficulty:
   - Chinese and mixed Chinese/English entities;
   - product/project/file anchors;
   - old but still relevant decisions;
   - multiple sessions with similar topics.

8. Privacy and forbidden fields:
   - synthetic Bearer token;
   - synthetic OpenAI project-key-shaped placeholder, never a real key;
   - synthetic `ghs_*` or `ghu_*`;
   - raw path/prompt/body fields;
   - expected output excludes all forbidden values.

9. Feedback and correction:
   - owner says "not this";
   - selected candidate should not become permanent success;
   - negative feedback should be visible only as metadata/report signal.

No corpus item may use real private transcripts unless a separate owner-approved
redaction package is created.

### Metrics

Context metrics:

- route accuracy;
- heading accuracy;
- selected source-class accuracy;
- dropped-section reason accuracy;
- diagnostic stale-history injection count;
- boundary true count;
- forbidden-field count;
- private body/path/token exposure count;
- prompt char budget and dropped-section reasons.

Retrieval metrics:

- Recall@K
- Precision@K
- MRR
- source-class diversity
- session diversity
- profile correctness
- answerable versus should-clarify classification

Answer metrics:

- candidate-as-approved confusion count;
- mechanism leak count;
- low-clue overcommit count;
- correction affordance present count;
- inappropriate direct-answer count for should-clarify cases.

Performance metrics:

- RH-31 may record wall-clock duration for eval runs as descriptive metadata.
- RH-31 synthetic/in-memory eval must not be used as latency evidence for real
  runtime scale.
- Real latency and rebuild claims must come from the Slice 20 benchmark path,
  especially the opt-in large benchmark, not from RH-31 synthetic corpora.

### Report Artifacts

Each eval run should produce:

```text
eval/reports/memory-os-rh31/<run-id>/summary.json
eval/reports/memory-os-rh31/<run-id>/scores.ndjson
eval/reports/memory-os-rh31/<run-id>/failure_cases.ndjson
eval/reports/memory-os-rh31/<run-id>/source_distribution.json
eval/reports/memory-os-rh31/<run-id>/scorecard.md
```

`failure_cases.ndjson` must include:

```json
{
  "case_id": "low_clue_zh_001",
  "query": "继续昨天那个。",
  "expected_class": "should_clarify",
  "actual_route": "ambiguous_recall",
  "actual_headings": ["Recall Clarification Guard"],
  "failure_class": null,
  "boundary_true": false,
  "forbidden_field_count": 0,
  "notes": ["example only; synthetic fixture"]
}
```

Reports must not contain raw private bodies or real tokens.

## Temporary Action Thresholds

These thresholds are provisional and may be changed by review, but RH-31 needs
explicit defaults so "evidence-based" has an entry condition.

### Guard Threshold

A deterministic guard may be proposed when all of these are true:

- the failure maps to a taxonomy row;
- the failure is not a correct boundary block;
- the proposed guard has an owning contract seam;
- local or fixture evidence reproduces it;
- the guard has a monitor field or report field that proves its effect.

At least one of these volume conditions must also be true:

- the failure class is at least 15% of non-boundary misses in the baseline
  scorecard;
- the failure appears in at least 5 cases across at least 2 fixture families;
- the failure is reproduced from a live monitor finding or explicit owner
  correction;
- the failure is P0/P1 under `29-memory-os-module-integration-contract.md`,
  regardless of frequency.

### Vector Or Graph Threshold

The derived hybrid branch may be proposed only when all of these are true:

- `semantic_gap` is at least 20% of retrieval misses after projection and FTS
  fixes are considered;
- there are at least 10 `semantic_gap` cases across at least 3 fixture
  families;
- report-only semantic or graph retrieval recovers the expected source in top
  5 for at least 60% of those `semantic_gap` cases;
- context, boundary, forbidden-field, and diagnostic metrics do not regress;
- Slice 20 benchmark evidence exists for rebuild/query cost at a realistic
  scale;
- reviewers explicitly approve RH-31H.

### Model-In-The-Loop Threshold

An answer audit may be proposed when either of these is true:

- context metrics pass but reviewers cannot determine whether the user-facing
  answer is safe or useful;
- a failure class is inherently answer-level, such as mechanism leak,
  candidate-as-approved wording, low-clue overcommit, or missing correction
  affordance.

Answer audit remains report-only. It cannot be used as a live router or
approval mechanism.

## Deterministic Guard Policy

RH-31 guards are allowed only when a failure is supported by:

- an eval fixture;
- a live monitor finding;
- a MemorySources feedback record; or
- a reproduced integration test.

Allowed guard families:

- route-specific source caps;
- entity/title salience preservation;
- source diversity slot adjustments;
- negative feedback downrank for low-clue candidates;
- diagnostic stale-history suppression;
- mechanism-label suppression for casual routes;
- freshness tie-breakers;
- CJK and mixed-language token/entity extraction improvements.

Forbidden guard patterns:

- topic-specific hardcodes such as `n8n`, `ComfyUI`, or `Make`;
- a second ingress keyword table outside `ingress.py`;
- LLM judge override of cancellation, foreground control, diagnostic, or
  approval boundaries;
- selected-by-router treated as successful use;
- feedback silently changing live routing without an apply gate;
- exposing route names, section headings, or metadata labels as user-facing
  recall topics.

## Optional Derived Retrieval Branch

Hybrid retrieval is not RH-31's default path.

It may enter a later report-only branch only if the eval shows:

1. the expected fact is present in canonical Memory-OS summaries;
2. current FTS/projection cannot retrieve or surface it;
3. semantic or graph retrieval retrieves it in a controlled adapter;
4. safety metrics do not regress;
5. latency and rebuild cost are acceptable;
6. the branch is approved after review.

If approved, the implementation constraints are:

- use only derived tables such as `memory_embeddings` and `memory_edges`;
- derive all rows from canonical profile-local files;
- deletion of SQLite must not delete memory;
- full rebuild must restore equivalent derived rows;
- no vector/graph table may become canonical memory;
- no cross-profile index by default;
- no Hindsight export;
- no iii-engine;
- no live prefetch change in the first implementation;
- RRF and reranker output are report-only until a later apply gate.

The branch should be named:

```text
RH-31H derived hybrid retrieval report-only
```

so it cannot be confused with the core RH-31 guard plan.

## Read-Only Operator Diagnostics

An operator dashboard is useful, but RH-31 should not start with a web viewer.

The first operator surface should be report artifacts and bounded CLI:

```text
hermes memory-os-agent-os eval rh31 run --fixture synthetic --adapter all
hermes memory-os-agent-os eval rh31 summary --latest
hermes memory-os-agent-os eval rh31 failures --latest --class projection_miss
```

All commands are proposed only. If implemented later, they must be read-only
with respect to canonical memory and must not run heartbeat, cognitive loop,
cleanup, shadow journal apply, Hindsight export, or service restarts.

Operator entry must follow Contract 1 and Contract 6 in
`29-memory-os-module-integration-contract.md`:

- the provider/runtime command implementation is the source of truth;
- the `memory-os-agent-os` shell plugin may expose the natural operator path,
  but it must only parse and delegate to the provider/runtime command;
- the shell plugin must not reimplement RH-31 eval logic or read report files
  with a separate parser;
- a no-env shell smoke test is required for any exposed operator path;
- the monitor must include a bounded probe for eval command availability if the
  command is exposed on the live test host;
- if RH-31 remains developer-only, the document and monitor must say so rather
  than leaving a half-documented shell path.

## Module Integration Declaration

```yaml
module:
  name: rh31_recall_eval_relevance_guards
  status: proposed
  owner_file: docs/system-modularization/31-recall-eval-and-derived-retrieval-plan.md
  purpose: identify recall failure classes and add deterministic relevance guards only when evidence proves a real failure

contracts:
  ingress_decision:
    affects_ingress: no for eval harness; yes only for future reviewed guards
    ingress_decisions: consumes existing IngressDecision
    hard_routes: must not override cancellation, foreground_control, explicit_deferred_resume, or diagnostic_current_status
    fallback_when_unmatched: downstream context router

  context_projection:
    affects_prefetch: no for eval harness; maybe for future reviewed guards
    section_headings:
      - Recall Clarification Guard
      - Current Foreground Task
      - Diagnostic Grounding
      - Working Memory
      - Indexed Recall
      - Conversation Carryover
    source_classes: fixture-defined and MemorySources-derived metadata only
    reason_codes: must reuse or extend context_router reason codes with tests
    budget_policy: report selected and dropped chars; no unbounded bodies
    memory_sources_required: yes for projection-affecting guards

  memory_write_surface:
    writes:
      - surface: eval_report
        path_or_store: eval/reports/memory-os-rh31/<run-id>/
        schema_version: memory-os.rh31_eval_report.v0
        body_policy: bounded_summary
        owner_approval_required: no
        append_only: no
        retention: >
          gitignored local report artifact; keep latest 20 runs or 30 days hot
          by default; promoted scorecards require explicit review
      - surface: optional_test_host_eval_report
        path_or_store: $HERMES_HOME/memory-os/system/eval/rh31/
        schema_version: memory-os.rh31_eval_report.v0
        body_policy: bounded_summary
        owner_approval_required: no
        append_only: yes
        retention: >
          bounded metadata report only; keep latest 20 runs or 30 days hot,
          archive-before-prune if cleanup is implemented, never delete canonical
          memory

  feedback_signal:
    emits_feedback: no
    consumes_feedback: report-only in first implementation
    feedback_types:
      - memory_sources_feedback
      - low_clue_correction_metadata
    allowed_effect: failure attribution and future guard proposal
    forbidden_effect: automatic memory approval, identity write, relationship write, hidden prompt injection, or live route override

  scheduler_step:
    scheduled: no
    mode: off
    trigger: explicit operator command only
    lock: not needed for local eval; required if test-host report path is written
    failure_isolation: eval failure must not affect provider, prefetch, heartbeat, or gateway
    audit_actions: none for local eval; bounded audit marker only if a future test-host operator command writes a report

  monitor_evidence:
    monitor_fields:
      - rh31.latest_run_status
      - rh31.failure_class_distribution
      - rh31.boundary_true_count
      - rh31.forbidden_field_count
      - rh31.route_accuracy
      - rh31.heading_accuracy
    pass:
      - eval run completes
      - boundary_true_count is 0
      - forbidden_field_count is 0
      - no live behavior changed
    warn:
      - insufficient fixture volume
      - expected failure class found but no guard proposed yet
      - semantic_gap found but hybrid branch not approved
    fail:
      - private body/token/path appears in report
      - eval command writes canonical memory
      - eval changes router/provider behavior
      - LLM judge changes hard route
    boundary_booleans:
      - actual_send
      - actual_execute
      - actual_identity_write
      - actual_relationship_write
      - actual_crystallized_approval
      - hindsight_exported
    forbidden_field_checks:
      - raw_prompt
      - prompt
      - body
      - raw_body
      - transcript
      - token
      - secret
      - cookie
      - file_path
      - path

  llm:
    uses_llm: none for context baseline; report-only for optional answer audit or judge comparison
    provider_source: Hermes configured provider only if explicitly enabled in report-only mode
    timeout_ms: 1500
    fallback: deterministic adapter result
    can_override_hard_route: no

  rollback:
    config_only: yes
    command_or_file: disable rh31 eval/report-only config or remove generated eval reports; canonical files are untouched

  tests:
    local:
      - read-only inventory parser tests
      - eval adapter unit tests
      - fixture corpus validation
      - forbidden-field report scan
    integrated:
      - provider -> build_prefetch -> context_router -> MemorySources replay
      - low-clue candidate adapter against synthetic fixtures
      - diagnostic grounding adapter against stale-history fixtures
      - optional answer audit on synthetic prompts when answer metrics are claimed
    remote:
      - 10.20.3.200 read-only eval smoke after review
      - monitor confirms no boundary or forbidden-field findings
```

## Implementation Slices For Future Review

These slices are not approved by this document. They are the proposed order if
reviewers approve RH-31 implementation later.

Approval split:

```text
31.0 through 31.3 are measurement infrastructure and may be reviewed as the
first approval package.

31.4 and later cover adapters beyond the first six deterministic baseline
adapters. They require either a read-only inventory finding, a baseline
scorecard finding, or an explicit reviewer decision that the additional adapter
is needed for a specific measurement gap.

31.6 deterministic guards, 31.7 answer audit, and 31H hybrid retrieval each
require their own gate.
```

### Slice 31.0 - Read-Only Baseline Inventory

Files to create:

- `eval/memory_os/runner/inventory.py`
- `tests/eval/test_memory_os_eval_inventory.py`

Acceptance:

- reads only bounded metadata surfaces;
- reports route/source/feedback/audit/working/candidate distributions;
- reuses the current monitor collector/schema where possible, or emits an
  explicit `memory-os.rh31_inventory.v0` field mapping to the monitor fields;
- must not create a second, conflicting monitor schema or definition for
  gateway, heartbeat, cognitive loop, MemorySources, low-clue, shell alias,
  boundary, or forbidden field health;
- does not read private bodies;
- does not run heartbeat, cognitive loop, cleanup, shadow-journal apply,
  Hindsight export, or service restart;
- produces fixture-weight recommendations for Slice 31.2.

### Slice 31.1 - Eval Harness Skeleton

Files to create:

- `eval/memory_os/runner/types.py`
- `eval/memory_os/runner/score.py`
- `eval/memory_os/runner/run.py`
- `tests/eval/test_memory_os_eval_runner.py`

Acceptance:

- runs against an in-memory synthetic corpus;
- writes `summary.json`, `scores.ndjson`, and `failure_cases.ndjson`;
- has no dependency on Hermes live home;
- does not write Memory-OS canonical files.

### Slice 31.2 - Memory-OS Fixture Corpus

Files to create:

- `eval/memory_os/data/rh31_synthetic/questions.jsonl`
- `eval/memory_os/data/rh31_synthetic/corpus.jsonl`
- `eval/memory_os/data/rh31_synthetic/expected.jsonl`
- `tests/eval/test_memory_os_eval_fixtures.py`

Acceptance:

- covers all required fixture families listed above;
- uses synthetic or redacted data only;
- includes adversarial forbidden-field samples;
- fixture validation fails if a real-looking secret appears;
- fixture weights are derived from Slice 31.0 frequency and risk bands;
- low-clue gold labels are stored in a reviewable label file.

### Slice 31.3 - Baseline Adapters

Files to create:

- `eval/memory_os/adapters/grep.py`
- `eval/memory_os/adapters/memory_os_fts.py`
- `eval/memory_os/adapters/context_projection.py`
- `eval/memory_os/adapters/low_clue_candidates.py`
- `eval/memory_os/adapters/memory_sources_replay.py`
- `eval/memory_os/adapters/diagnostic_grounding.py`
- `tests/eval/test_memory_os_eval_adapters.py`
- `tests/eval/test_memory_os_eval_low_clue.py`
- `tests/eval/test_memory_os_eval_memory_sources.py`

Acceptance:

- grep baseline runs without SQLite;
- FTS adapter rebuilds from fixture canonical files;
- context projection adapter calls the public `build_prefetch()` seam;
- low-clue cases distinguish `ask_choice`, `direct_resume`, and overcommit;
- MemorySources replay measures source diversity without raw private bodies;
- diagnostic adapter proves stale historical recall is suppressed;
- metadata-derived internal labels are rejected as user-facing recall topics;
- negative feedback is report-only and cannot alter canonical memory;
- the baseline scorecard labels every metric as context, answer, or
  performance;
- answer metrics are marked unmeasured unless Slice 31.7 is approved.

### Slice 31.4 - Additional Adapter Extensions

Gate:

- applies only to adapters beyond the first six deterministic baseline
  adapters;
- requires Slice 31.0 or 31.3 evidence that the additional adapter is needed, or
  an explicit reviewer decision.

Files to create:

- none by default;
- future files must declare whether they measure context, retrieval, answer, or
  performance before implementation.

Acceptance:

- no first-six deterministic adapter may be moved out of Slice 31.3 without a
  documented reviewer split decision;
- additional adapters remain read-only and report-only until their own promotion
  gate is accepted.

### Slice 31.5 - First Scorecard

Files to create:

- `docs/benchmarks/memory-os/YYYY-MM-DD-rh31-baseline.md`

Acceptance:

- reports adapter comparison and failure class distribution;
- reports corpus weights and separates frequency band from risk band;
- states whether the next fix should target ingress, projection, low-clue
  candidates, FTS projection, diagnostics, or a future hybrid branch;
- does not recommend vector/RRF unless `semantic_gap` meets the temporary
  threshold or reviewers amend the threshold.

### Slice 31.6 - Deterministic Guard Proposal

Files to create or modify only after the first scorecard identifies a real
failure:

- owning implementation file from the failure taxonomy;
- focused regression tests at the public seam;
- `07-validation-report-10.20.3.200.md` evidence update after deployment, if
  deployed to the test host.

Acceptance:

- the failure meets the temporary guard threshold or a reviewed amended
  threshold;
- guard fixes the measured failure;
- no hardcoded topic-specific patch;
- no boundary regression;
- monitor can explain the changed behavior.

### Slice 31.7 - Model-In-The-Loop Answer Audit

This slice is explicitly conditional.

Gate:

- requires an answer-level failure class, or a context-pass / answer-uncertain
  scorecard result;
- requires reviewer approval before any model call is added to the eval path.

Files to create:

- `eval/memory_os/adapters/future_answer_audit.py`
- `tests/eval/test_memory_os_eval_answer_audit.py`

Acceptance if approved:

- runs only against synthetic or owner-approved redacted prompts;
- uses bounded report-only model calls;
- records answer-level metrics separately from context metrics;
- cannot alter Memory-OS routing, memory writes, feedback, or approval;
- fails closed to "answer audit unavailable" without blocking context eval.

### Slice 31H - Derived Hybrid Retrieval Report-Only

This slice is explicitly conditional.

It is blocked unless Slice 31.5 shows `semantic_gap` meeting the temporary
vector/graph threshold and reviewers approve the branch.

Acceptance if approved:

- derived embedding/edge rows rebuild from canonical files;
- report-only RRF comparison exists;
- Slice 20 benchmark evidence exists for realistic rebuild/query cost;
- no live prefetch behavior changes;
- no new default model tools;
- no external server or iii-engine.

## Promotion Gates

Before the first approval package, limited to 31.0 through 31.3:

- this document is reviewed;
- the module integration declaration is accepted or amended;
- reviewers agree that RH-31 starts with eval and failure attribution, not
  hybrid retrieval;
- reviewers accept that the first scorecard measures context quality unless
  Slice 31.7 is separately approved;
- `eval/reports/` is gitignored and any promoted report path is explicitly
  reviewed;
- the bounded CLI path is either declared developer-only or has provider/runtime
  source-of-truth, shell delegation, no-env shell smoke, and monitor probe
  acceptance defined.

Before 31.4 or any later adapter beyond the first six deterministic adapters:

- Slice 31.0 or 31.3 shows the adapter is needed, or reviewers explicitly
  approve it for a specific measurement gap;
- the adapter declares whether it measures context, retrieval, answer, or
  performance.

Before any deterministic guard:

- the failure meets the temporary guard threshold or a reviewed replacement
  threshold;
- the online-finding to fixture loop is complete when the trigger came from
  live behavior;
- a monitor or report field can prove the guard worked.

Before RH-31H:

- `semantic_gap` meets the temporary vector or graph threshold;
- Slice 20 performance evidence exists;
- reviewers approve the separate branch.

Before local merge:

- eval tests pass;
- forbidden-field scan passes;
- no canonical Memory-OS files are written by eval;
- `git diff --check` passes.

Before 10.20.3.200 execution:

- command is read-only or writes only bounded eval reports;
- rollback is config-only or report deletion only;
- expected monitor outcome is documented.

After any 10.20.3.200 execution:

- run read-only monitor;
- boundary booleans remain false;
- forbidden-field count remains 0;
- provider/runtime status remains healthy;
- validation report receives evidence if behavior or operator expectations
  changed.

## Review Questions

Reviewers should answer these before any implementation:

1. Should RH-31 be limited to eval and deterministic guards, with hybrid
   retrieval split into RH-31H only if data proves `semantic_gap`?
2. Which fixture families are required for the first baseline scorecard?
3. Are synthetic Sannai-like fixtures acceptable, or is an owner-approved
   redacted package needed for profile-boundary tests?
4. What scorecard threshold is enough to justify a guard?
5. What scorecard threshold is enough to justify derived vector/RRF work?
6. Should eval reports live only in the repository, or may a future operator
   command write bounded reports under `$HERMES_HOME/memory-os/system/eval/`?
7. Should any RH-31 output be exposed through the `memory-os-agent-os` shell
   plugin, or remain developer-only until after the first scorecard?
8. Are the temporary guard, vector/graph, and answer-audit thresholds acceptable
   as defaults for the first scorecard?
9. Which online findings must be converted into fixtures before the first guard
   proposal can be reviewed?
10. Should answer-quality audit stay fully developer-only until at least one
    context scorecard is reviewed?

## Anti-Patterns

The following block RH-31:

- starting with vector search before failure attribution;
- presenting context-only eval as answer-quality eval;
- claiming synthetic eval latency as production-scale performance evidence;
- importing agentmemory code or adding iii-engine;
- changing `memory.provider`;
- broadening Hermes default MCP/tool context;
- adding a new live router classifier outside `ingress.py`;
- adding an LLM judge that changes hard decisions;
- treating MemorySources feedback as memory approval;
- writing eval cases from real private transcripts without explicit redaction;
- freezing low-clue gold labels without a reviewable label file;
- closing a live recall finding without converting it into a fixture or
  documenting why it cannot be reproduced;
- adding a dashboard that can edit memory, approve memory, delete memory, or
  invoke runtime actions.

## Final Decision

RH-31 should proceed, if reviewers approve, as a measurement-first plan:

```text
Build Memory-OS-specific evals, classify recall failures, then add the smallest
deterministic guard backed by evidence.
```

Agentmemory contributes useful methodology, but not code, service architecture,
storage model, or default tool surface.

Derived hybrid retrieval remains possible only as a later report-only branch
after the eval proves a semantic retrieval gap.

## Implementation Evidence - RH-31.0 through RH-31.3

Date: 2026-05-25

Implemented scope:

- Slice 31.0 read-only inventory:
  - `eval/memory_os/runner/inventory.py`
  - emits `memory-os.rh31_inventory.v0`
  - reports bounded route/source/feedback/audit/working/candidate metadata
  - maps its fields back to existing monitor concepts instead of inventing a
    second health schema
- Slice 31.1 eval harness skeleton:
  - `eval/memory_os/runner/run.py`
  - `eval/memory_os/runner/score.py`
  - writes `summary.json`, `scores.ndjson`, `failure_cases.ndjson`,
    `source_distribution.json`, and `scorecard.md`
  - supports `--no-write-report` for monitor smoke
- Slice 31.2 synthetic fixture corpus:
  - `eval/memory_os/data/rh31_synthetic/questions.jsonl`
  - `eval/memory_os/data/rh31_synthetic/corpus.jsonl`
  - `eval/memory_os/data/rh31_synthetic/expected.jsonl`
  - synthetic/redacted only; no private body fixture
- Slice 31.3 first deterministic adapters:
  - `grep`
  - `memory_os_fts`
  - `context_projection`
  - `low_clue_candidates`
  - `memory_sources_replay`
  - `diagnostic_grounding`

Operator path:

```text
hermes memory_os eval rh31 run --fixture synthetic --adapter all
hermes memory_os eval rh31 summary
hermes memory_os eval rh31 failures --class projection_miss
hermes memory-os-agent-os eval rh31 run --fixture synthetic --adapter all
```

Monitor path:

```text
hermes memory-os-agent-os eval rh31 run \
  --fixture synthetic \
  --adapter all \
  --no-write-report
```

The shell plugin delegates to the provider/runtime implementation. It does not
read reports directly and does not reimplement eval logic.

Installation path:

- `install_system_modules` now copies the top-level `eval/` package into
  `$HERMES_HOME/memory-os/runtime/python/eval`.
- This is required because installed provider CLI imports the eval harness from
  the runtime Python path.

Retention:

- `eval/memory_os/runner/retention.py` provides a dry-run report retention
  plan for `eval/reports/memory-os-rh31/`.
- It reports which old eval runs would be archived/pruned while keeping
  canonical Memory-OS paths untouched.
- Broad RH-17 retention for MemorySources, feedback ledgers, and future
  suggestion reports remains separate.

Boundary status:

- RH-31.0-31.3 are report-only.
- They do not alter live prefetch, live routing, scheduler behavior,
  crystallized approval, send/execute gates, identity, or canonical memory.

Remote smoke on `10.20.3.200`:

```text
time=2026-05-24T17:58:24Z
command=hermes memory-os-agent-os eval rh31 run --fixture synthetic --adapter all --no-write-report

schema_version=memory-os.rh31_summary.v0
status=warning
adapter_count=6
case_count=6
score_count=27
failure_count=4
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1, "projection_miss": 1}
boundary_true_count=0
forbidden_field_count=0
report_written=false
retention.reports_root=/root/eval/reports/memory-os-rh31
retention.would_archive_or_prune=[]
```

The warning status is expected for the first scorecard: RH-31 is measuring
known recall misses, not declaring the runtime unhealthy. The safety gate is
the boundary/forbidden-field count, both of which stayed at zero.

Remote monitor integration smoke:

```text
command=python scripts/memory_os_3_200_monitor.py --host hermes-media --output summary

monitor_status=WARN
PASS includes:
  rh31_eval_safety_ok
  shell_alias_no_env_ok
  context_router_apply
  memory_sources_stats_ok
  low_clue_recall_probe_ok

WARN includes:
  rh31_eval_has_failures

FAIL=[]
RH31Eval={
  "status": "warning",
  "adapter_count": 6,
  "failure_count": 4,
  "boundary_true_count": 0,
  "forbidden_field_count": 0,
  "report_written": false
}
```

## First Scorecard Decision

Date: 2026-05-25

Command:

```text
python -m plugins.memory.memory_os eval rh31 run --fixture synthetic --adapter all
```

Result:

```text
run_id=rh31_20260524T183908544131Z
status=warning
adapter_count=6
case_count=6
score_count=27
failure_count=4
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1, "projection_miss": 1}
boundary_true_count=0
forbidden_field_count=0
report_dir=eval/reports/memory-os-rh31/rh31_20260524T183908544131Z
```

Failure records:

```text
grep/mechanism_noise_001 -> lexical_miss
memory_os_fts/diagnostic_grounding_001 -> fts_miss
memory_os_fts/mechanism_noise_001 -> fts_miss
context_projection/candidate_boundary_001 -> projection_miss
```

Guard decision:

- Do not add the first RH-31 live guard from this scorecard alone.
- The failures are useful measurement signals, but they are not yet a reviewed
  live finding.
- The `candidate_boundary_001` projection miss may indicate either a fixture
  expectation issue or an active-task route priority issue; it needs a reviewed
  fixture/live reproduction before any routing guard is added.
- The FTS/lexical misses support improving fixtures and measurement coverage,
  not adding broad wording guards.

## Post-Review Coverage Fix - MemorySources Replay

Date: 2026-05-25

Review finding:

```text
memory_sources_replay previously replayed only the first 3 synthetic cases but
emitted pass/fail scores for all 6 cases.
```

Contract decision:

- `memory_sources_replay` remains a ledger-safety adapter, not a per-answer
  quality adapter.
- It must replay every case it scores.
- Every score includes bounded replay metadata:
  - `record_count`
  - `replayed_case_count`
  - `replayed_case_ids`
- It must not write canonical memory and must keep `boundary_true_count=0` and
  `forbidden_field_count=0`.

Local post-fix smoke:

```text
command:
  python -m plugins.memory.memory_os eval rh31 run --fixture synthetic \
    --adapter memory_sources_replay --no-write-report

status=pass
case_count=6
score_count=6
failure_count=0
record_count=6
replayed_case_count=6
boundary_true_count=0
forbidden_field_count=0
report_dir=""
```

Full scorecard after the fix remains a warning because the existing
measurement misses are still present:

```text
command:
  python -m plugins.memory.memory_os eval rh31 run --fixture synthetic \
    --adapter all --no-write-report

status=warning
adapter_count=6
case_count=6
score_count=27
failure_count=4
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1, "projection_miss": 1}
boundary_true_count=0
forbidden_field_count=0
report_dir=""
```

Guard decision remains unchanged: do not add the first RH-31 live guard from
this scorecard alone.

## Post-Review Monitor Snapshot Fix

Date: 2026-05-25

Review finding:

```text
The monitor's JSON snapshot retained the full RH-31 `scores` list. This was
acceptable at 27 scores but would grow with fixture expansion and automation
memory snapshots.
```

Contract decision:

- The monitor may run the RH-31 no-write probe.
- The monitor snapshot must retain only summary fields:
  - `schema_version`
  - `status`
  - `adapter_count`
  - `case_count`
  - `score_count`
  - `failure_count`
  - `failure_class_distribution`
  - `boundary_true_count`
  - `forbidden_field_count`
  - `report_written`
  - `source_distribution`
- Score-level details remain available through the explicit provider or shell
  CLI and generated eval reports when intentionally written.
- Monitor snapshots must not retain `scores`.

Local monitor JSON smoke after the fix:

```text
rh31_eval.status=warning
rh31_eval.score_count=27
rh31_eval.failure_count=4
rh31_eval.boundary_true_count=0
rh31_eval.forbidden_field_count=0
rh31_eval.report_written=false
rh31_eval contains no scores field
```

Remote 10.20.3.200 smoke after redeploy:

```text
command:
  hermes memory-os-agent-os eval rh31 run --fixture synthetic \
    --adapter all --no-write-report

status=warning
adapter_count=6
case_count=6
score_count=27
failure_count=4
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1, "projection_miss": 1}
memory_sources_replay_record_counts=[6]
memory_sources_replay_replayed_counts=[6]
boundary_true_count=0
forbidden_field_count=0
report_dir=""
```

Remote monitor smoke after redeploy:

```text
monitor_status=WARN
FAIL=[]
WARN=["rh31_eval_has_failures", "rh26_casual_empty"]
rh31_has_scores=false
rh31_status=warning
rh31_score_count=27
rh31_failure_count=4
rh31_boundary_true_count=0
rh31_forbidden_field_count=0
```

RH-17 metadata retention support:

- `plugins/memory/memory_os/metadata_retention.py` adds
  `memory-os.metadata_retention_plan.v0`.
- CLI:

```text
hermes memory_os metadata-retention
hermes memory-os-agent-os metadata-retention
```

- The helper is dry-run only and covers:
  - MemorySources JSONL
  - MemorySources feedback JSONL
  - future consolidation suggestion JSONL
  - RH-31 eval report directories
  - future RH-32 suggestion report directories
- The helper reports archive-before-prune actions and keeps
  `canonical_paths_touched=[]`.

Remote RH-17 metadata-retention smoke on `10.20.3.200`:

```text
command=hermes memory-os-agent-os metadata-retention

schema_version=memory-os.metadata_retention_plan.v0
dry_run=true
canonical_paths_touched=[]
actions=[]
memory_sources.total_records=31
memory_sources.archive_candidate_records=0
memory_sources_feedback.total_records=1
memory_sources_feedback.archive_candidate_records=0
consolidation_suggestions.exists=false
rh31_eval_reports.exists=false
rh32_suggestion_reports.exists=false
```

The no-env monitor alias check now includes `metadata-retention` and reports
`metadata_retention_ok=true` on the test host.

## P1-B Attribution - candidate_boundary_001

Date: 2026-05-25

Finding under review:

```text
context_projection/candidate_boundary_001 -> projection_miss
reported actual_route=active_task
reported headings=[
  Current Foreground Task,
  Working Memory,
  Indexed Recall,
  Recent Event Summaries
]
```

Root cause:

- The synthetic fixture had a `source_class="candidate"` document, but
  `synthetic_store()` only wrote corpus documents as events and working items.
  It did not populate `crystallized_candidates/candidates.jsonl`, so the live
  prefetch surface for `Crystallized Review Candidates` was absent in the eval
  fixture.
- The candidate fixture text used the phrase `crystallized candidates`, which
  is intentionally treated as mechanism/diagnostic-style wording in the
  projection filter. That made the candidate body unsuitable for testing
  user-facing candidate review projection.
- The `context_projection` adapter inferred `actual_route` from projected
  headings. Because `Current Foreground Task` was selected by score, the adapter
  reported `active_task` even though the router itself classified the query as
  `candidate_review`.

Fix:

- `synthetic_store()` now writes `source_class="candidate"` documents to the
  candidate review queue as synthetic `CrystallizedCandidate` records.
- The `candidate_boundary_001` corpus text now uses user-facing candidate queue
  wording instead of mechanism-heavy `crystallized candidates` wording.
- The `context_projection` adapter records the actual router route from
  `build_context_router_report()` instead of deriving it from headings.

Local evidence after the fix:

```text
python -m pytest tests/eval/test_memory_os_eval_rh31.py -q
9 passed

python -m pytest \
  tests/eval/test_memory_os_eval_rh31.py \
  tests/scripts/test_memory_os_3_200_monitor.py \
  tests/plugins/memory/test_memory_os_prefetch.py -q
47 passed
```

Bounded scorecard evidence after the fix:

```text
status=warning
score_count=27
failure_count=3
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1}
boundary_true_count=0
forbidden_field_count=0

candidate_boundary_001/context_projection:
  status=pass
  actual_route=candidate_review
  actual_headings=[
    Current Foreground Task,
    Working Memory,
    Crystallized Review Candidates,
    Indexed Recall,
    Recent Event Summaries
  ]
```

Remote live no-write projection check on `10.20.3.200`:

```text
query="candidate 分数很高，是不是就自动变成长期记忆？"
candidate_count=161
route=candidate_review
selected=[
  Current Foreground Task,
  Crystallized Review Candidates,
  Recent Event Summaries
]
dropped=[
  Conversation Carryover,
  Working Memory,
  Indexed Recall
]
boundary_true=false
```

Remote RH-31 no-write scorecard after deploying the eval-only fix to
`10.20.3.200`:

```text
hermes memory-os-agent-os eval rh31 run --fixture synthetic \
  --adapter all --no-write-report

status=warning
score_count=27
failure_count=3
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1}
boundary_true_count=0
forbidden_field_count=0

candidate_boundary_001/context_projection:
  status=pass
  actual_route=candidate_review
  actual_headings=[
    Current Foreground Task,
    Working Memory,
    Crystallized Review Candidates,
    Indexed Recall,
    Recent Event Summaries
  ]
  failure_class=null
```

Remote read-only monitor after deploy:

```text
time=2026-05-25T04:36:45Z
monitor_status=WARN
WARN=[rh31_eval_has_failures]
FAIL=[]
RH31Eval.status=warning
RH31Eval.failure_count=3
RH31Eval.boundary_true_count=0
RH31Eval.forbidden_field_count=0
```

Decision:

- `candidate_boundary_001` was an eval fixture/attribution bug, not a live
  ContextProjection regression.
- Do not add an RH-31 live guard for this case.
- The remaining first-scorecard warning items are measurement signals:
  lexical/FTS misses only.
