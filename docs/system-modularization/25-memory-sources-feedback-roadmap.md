# 25 - Memory Sources, Feedback, And Low-Cost Relevance Roadmap

Status: design draft for review
Date: 2026-05-23

## Goal

This document turns the ChatGPT Memory reverse-engineering discussion and the
current Memory-OS RH-26/RH-28 evidence into a low-cost implementation roadmap.

The goal is not to build a new memory architecture. The goal is to add the
highest-leverage pieces that improve observability, owner control, and context
relevance without creating another complex tier.

Recommended scope:

1. Memory Sources attribution
2. Relevance Feedback audit
3. RH-26/RH-28 deterministic relevance guards
4. Auto consolidation suggestions, no approval
5. Top-of-Mind scoring only

Explicitly deferred:

- Top-of-Mind tier
- LLM-only routing decisions
- automatic crystallized approval
- automatic deletion or rewriting of canonical memory
- hidden send/execute behavior

## External Reference Scan

This is a design synthesis, not a claim of implementation equivalence.

### OpenAI ChatGPT Memory

OpenAI describes ChatGPT Memory as using both saved memories and chat history.
Saved memories are intended for high-level preferences and details, while chat
history can be referenced when relevant. OpenAI also exposes Memory Sources that
let users see what information informed a personalized response and mark sources
as relevant or not relevant. OpenAI states that ChatGPT does not search history
on every request; it looks for relevant context only when likely useful.

Design lesson for Memory-OS:

- source attribution is useful even before behavior changes
- owner feedback on source relevance is a low-cost control surface
- memory should be used when relevant, not blindly loaded every turn

Sources:

- https://help.openai.com/en/articles/8590148-memory-in-chatgpt-faq

### MemGPT / Letta

MemGPT frames agent memory as virtual context management across memory tiers.
The key lesson is not to copy its exact architecture, but to keep the boundary
between fast in-context memory and larger out-of-context memory explicit.
Letta's public docs continue this direction with core memory, archival memory,
and context hierarchy concepts.

Design lesson for Memory-OS:

- keep tier boundaries explicit
- prefer routing and paging over loading every available memory
- do not add another tier unless the current tiers cannot express the behavior

Sources:

- https://arxiv.org/abs/2310.08560
- https://docs.letta.com/

### RAG And Source Attribution

The RAG paper identifies provenance and updateability as open problems for
knowledge-intensive generation and introduces retrieval over explicit
non-parametric memory. Later RAG/source-attribution work points in the same
direction: retrieved context should be traceable enough to debug and evaluate.

Design lesson for Memory-OS:

- every injected memory section should carry a source class, origin id, route,
  score, and reason codes
- the monitor should track source distribution over time
- source bodies do not need to be printed to gain observability

Sources:

- https://arxiv.org/abs/2005.11401

### Zep / Temporal Graph Memory

Zep emphasizes dynamic synthesis from conversations and business data while
maintaining historical relationships. Its graph model is heavier than we need
now, but its distinction between raw episodes, facts, and temporal validity is
relevant.

Design lesson for Memory-OS:

- keep raw canonical events separate from projected facts/candidates
- source lineage should point back to a raw episode/event where possible
- temporal freshness should be metadata, not hidden prompt wording

Sources:

- https://arxiv.org/abs/2501.13956
- https://help.getzep.com/v2/understanding-the-graph

### Mem0

Mem0 focuses on extracting, consolidating, and retrieving salient information
from ongoing conversations, with production constraints such as latency and
token cost. Its practical lesson is that selective memory beats full-context
loading.

Design lesson for Memory-OS:

- consolidation should first produce suggestions or candidates
- token budget should be treated as a routing constraint
- evaluation should track both quality and cost/growth

Sources:

- https://arxiv.org/abs/2504.19413
- https://docs.mem0.ai/platform/overview

### LangGraph / Deep Agents Memory

LangGraph/Deep Agents document file-backed persistent memory, user-scoped
isolation, read-only versus writable memory, and background consolidation.

Design lesson for Memory-OS:

- profile isolation remains non-negotiable
- background consolidation is useful, but write permissions must be explicit
- a consolidation agent or job should be report-first before it can mutate any
  durable layer

Sources:

- https://docs.langchain.com/oss/python/deepagents/memory

### A-MEM / Agentic Memory

A-MEM argues that basic storage and retrieval are not enough, and proposes
dynamic organization using structured note attributes, tags, links, and memory
evolution. This is relevant but should be down-scoped for Memory-OS v0.1.

Design lesson for Memory-OS:

- structured attributes and links are useful
- full dynamic memory evolution is too heavy for the current phase
- low-cost scoring and suggestion reports are the right first step

Sources:

- https://arxiv.org/abs/2502.12110

## Current Memory-OS Position

Already present:

- canonical event stream
- working memory
- review candidates
- crystallized records with owner boundary
- DeepReflection injection cards
- RH-23 source-class monitoring
- RH-26 context router
- RH-28 low-clue recall guard
- RH-27 test-host cognitive loop

Observed gaps:

- the system can tell selected headings but does not yet persist a compact
  per-turn Memory Sources ledger
- the owner has no first-class feedback path for "this injected context was
  useful / irrelevant / too mechanism-heavy"
- deterministic route guards are improving but still need incremental fixtures
  from real Telegram behavior
- consolidation exists as module behavior, but owner-facing suggestion reports
  are not yet the main artifact
- top-of-mind behavior is useful, but a new tier would add too much surface area

## Ranking By Benefit / Cost

### 1. RH-29 Memory Sources Attribution

Priority: highest

Why first:

- low risk
- high debugging value
- no behavior change required
- directly supports monitor, validation reports, and public materials

Implementation shape:

- add a bounded `memory_sources` metadata record for each live prefetch build
- store metadata only, not raw section bodies
- include:
  - timestamp
  - profile
  - route
  - query hash or bounded query class, not raw private prompt
  - selected section headings
  - source classes
  - source ids where safe
  - character counts
  - scores
  - reason codes
  - dropped section summary counts
  - boundary booleans
- write to:
  - `$HERMES_HOME/memory-os/system/memory_sources.jsonl`
  - or another system metadata file outside canonical events

Non-goals:

- do not change prefetch content
- do not write events, working, candidates, crystallized, identity, or
  relationship records
- do not expose raw private prompts or bodies

Acceptance:

- `hermes memory_os memory-sources last`
- `hermes memory_os memory-sources history --limit N`
- monitor reads aggregate source distribution from the metadata ledger
- Telegram smoke can be debugged by source headings without printing content

### 2. RH-30 Relevance Feedback Audit

Priority: second

Why second:

- owner feedback is one of the cheapest ways to improve routing later
- it should collect evidence before changing weights
- it matches ChatGPT Memory Sources feedback without copying ChatGPT's closed
  implementation

Implementation shape:

- add a CLI-only feedback command first:

```text
hermes memory_os memory-sources feedback last --rating useful
hermes memory_os memory-sources feedback last --rating irrelevant
hermes memory_os memory-sources feedback last --rating too-mechanistic
hermes memory_os memory-sources feedback last --rating missing-context
```

- write audit-only metadata:
  - feedback id
  - referenced memory source record id
  - rating
  - optional owner note
  - timestamp

Initial ratings:

- `useful`
- `irrelevant`
- `too_mechanistic`
- `missing_context`
- `overconfident`
- `needs_specific_recall`

Non-goals:

- do not automatically change router weights
- do not automatically promote or demote memory
- do not create crystallized records
- do not infer owner feedback from ordinary conversation without an explicit
  command or explicit future Telegram affordance

Acceptance:

- feedback command can attach to last source record
- feedback appears in bounded history
- monitor reports feedback counts by rating
- no live behavior changes in RH-30

### 3. RH-31 Deterministic Relevance Guard Expansion

Priority: third

Why third:

- RH-26/RH-28 are already effective
- the correct next move is small real-finding-based guards, not a general LLM
  relevance judge

Implementation shape:

- add only guards backed by real Telegram transcripts or validation prompts
- each guard must define:
  - trigger
  - route
  - selected sections
  - forbidden sections
  - expected answer shape
  - regression fixture

Candidate guard families:

- low-clue recall, already RH-28
- candidate/crystallized review, keep existing wording boundary
- foreground cancellation/deferred task, continue observing before RH-25.1
- diagnostic/status questions, allow diagnostic grounding only when explicit
- active task debugging, prioritize foreground and task-indexed recall

Non-goals:

- no broad wording guard for every automation phrase
- no LLM judge by default
- no hidden suppression of useful context

Acceptance:

- new guard only lands with a failing fixture or real transcript evidence
- RH-22/RH-26 validation prompts still pass
- monitor can explain route changes through reason codes

### 4. RH-32 Auto Consolidation Suggestions, No Approval

Priority: fourth

Why fourth:

- useful for controlling growth and duplicate candidates
- higher risk than attribution/feedback because it can influence what becomes
  candidate-worthy
- should remain proposal/report-only at first

Implementation shape:

- add a report command:

```text
hermes memory_os consolidation suggest --days 7 --limit 20
```

- output suggestion categories:
  - duplicate candidates
  - stale working items
  - mechanism-heavy working items that should be downranked in casual routes
  - repeated stable facts that may deserve owner review
  - candidate conflicts
  - expired or low-use DeepReflection cards

Write target:

- suggestion report under system modules:
  `$HERMES_HOME/memory-os/system-modules/consolidation/reports.jsonl`

Non-goals:

- no automatic crystallized approval
- no canonical deletion
- no automatic working-memory pruning in the first version
- no identity/relationship mutation

Acceptance:

- dry-run report only
- bounded previews only
- explicit counts and reason codes
- no changes to canonical data
- owner can later choose which suggestions become proposals

### 5. RH-33 Top-of-Mind Scoring Only

Priority: fifth

Why fifth:

- top-of-mind behavior is valuable
- a new top-of-mind tier is too complex now
- scoring can approximate the benefit without creating a new storage layer

Implementation shape:

- add optional `top_of_mind_score` to router candidate metadata
- compute score from existing metadata:
  - route match
  - recent successful use
  - owner `useful` feedback
  - repeated retrieval success
  - freshness
  - source class policy
  - negative feedback penalties
  - diagnostic-style penalty for casual routes
- score is used only inside RH-26 ranking and reports

Non-goals:

- no new persistent top-of-mind memory tier
- no always-in-context top-of-mind block
- no cross-profile sharing
- no owner-invisible strong injection

Acceptance:

- dry-run report shows `top_of_mind_score`
- apply remains disabled until reports are reviewed
- no new storage layer
- no change to crystallized approval policy

## Proposed Delivery Order

### RH-29: Memory Sources Attribution

Deliver first.

Scope:

- metadata ledger
- CLI last/history
- monitor aggregation
- tests
- 10.20.3.200 validation

Review gate:

- verify no raw bodies
- verify no behavior change
- verify source distribution matches RH-26 prefetch headings

### RH-30: Relevance Feedback Audit

Deliver second.

Scope:

- feedback command
- audit-only feedback ledger
- monitor feedback counts
- no weight changes

Review gate:

- verify explicit owner action required
- verify feedback does not mutate router behavior yet

### RH-31: Deterministic Relevance Guards

Deliver continuously, one guard at a time.

Scope:

- only real finding-backed guards
- no general LLM judge
- regression fixtures

Review gate:

- each guard must include a before/after transcript or fixture

### RH-32: Consolidation Suggestions

Deliver after enough monitor and feedback data exists.

Scope:

- report-only duplicate/stale/conflict suggestions
- no approval or deletion

Review gate:

- verify suggestions are useful and not noisy
- verify no canonical mutation

### RH-33: Top-of-Mind Scoring

Deliver last among this group.

Scope:

- scoring only
- no new tier
- dry-run first

Review gate:

- compare router selection with and without scoring
- confirm no hidden strong injection

## Monitoring Additions

Monitor v0.5 should eventually include:

- `memory_sources_records_delta`
- selected source classes over time
- selected route distribution
- average selected context chars
- dropped reason-code distribution
- owner feedback counts by rating
- top-of-mind score distribution, only after RH-33
- consolidation suggestion counts, only after RH-32

Expected WARN:

- no feedback records yet
- no top-of-mind scores before RH-33
- source distribution temporarily skewed on test host

FAIL:

- memory source record includes raw body/private text
- feedback mutates crystallized/identity/relationship memory
- source attribution hides hard-boundary booleans
- top-of-mind scoring creates a new implicit tier without review

## Boundaries

All five slices must preserve:

- no send
- no execute
- no identity write
- no relationship write
- no crystallized approval
- no Hindsight export
- no production/Sannai mutation
- no raw private body printing in monitor or CLI default output
- canonical data remains complete; projection/routing can change visibility

## Recommendation

Start with RH-29 only.

Reason:

- it is the cheapest high-signal addition
- it makes later feedback and scoring evidence-based
- it does not change live model behavior
- it strengthens public materials by showing exactly what Memory-OS injected
  without exposing private content

Do not start RH-32 or RH-33 before RH-29/RH-30 have produced real data.
