# CW-005 Continuity Comparison

Date: 2026-05-21

## Purpose

Compare the existing Sannai CW-005/CW-003 continuity design with the modular
Memory-OS direction, so the public Memory-OS system preserves the useful
coverage and continuity behavior without copying Sannai-private identity or
persona logic.

## Source Documents

Reference documents:

- `_context/07_cw005_curation_design.md`
- `docs/cowork/cw-003-v5-event-journal.md`
- `docs/hermes-memory-contract.md`
- `docs/memory-os/architecture.md`
- `docs/system-modularization/11-sannai-coverage-audit-and-entry-mirror-requirements.md`

## CW-005 / CW-003-V5 Pattern

The old Sannai system proved a complete continuity pattern:

```text
raw entry source
  -> event card journal
  -> bounded overlay selector
  -> daily digest
  -> weekly consolidation proposal
  -> owner-approved long-term update
```

Key properties:

- entry sources are source-aware: cron, Telegram, mailbox, family-room,
  treasure-vault, diary
- event cards are small complete records, not raw transcripts
- overlay selector chooses whole cards and does not cut cards mid-body
- recent bridge sources get a chance to survive the budget
- daily digest reads event cards and diary, not raw full sessions
- weekly proposal is pending owner review, not automatic long-term memory
- apply is manual and hash-guarded
- identity, relationship, beliefs, and open threads are separate surfaces
- dynamic overlay is request-local and bounded; it does not churn the stable
  prompt manifest
- source allowlists prevent wandering/journal or unrelated state from being
  accidentally consumed

## Memory-OS Mapping

| CW-005 concept | Memory-OS modular equivalent |
| --- | --- |
| raw session / cron / mailbox / treasure source | Entry/Source Mirror family |
| event card journal | Memory-OS Event Stream with source/kind/provenance |
| recent-events overlay selector | Memory-OS prefetch/context selector |
| daily digest | digest/consolidation module writing events or candidates |
| weekly consolidation proposal | Proposal Queue + Evidence/Scoring |
| manual apply with proposal hash | Ops-Gate + owner-approved crystallized write |
| identity / relationship / beliefs / open_threads snapshots | Identity/Relationship/Crystallized views, owner bounded |
| revision log | Memory-OS audit + proposal/crystallized provenance |
| source allowlist | mirror source classes and module manifests |
| request-local overlay | provider prefetch/runtime context block |

This confirms the architecture direction:

```text
Memory-OS should not be only a provider.
Memory-OS should be the reusable version of the full continuity chain.
```

## What The Current Memory-OS Already Covers

Already implemented or designed:

- provider capture for foreground conversations
- provider `on_memory_write()` capture for `memory()` `add`
- event stream
- working memory
- crystallized candidates
- owner-approved crystallized records
- Hindsight adapter boundary
- runtime heartbeat from events into working/candidates
- module lifecycle, status, doctor, no-send boundaries
- Entry/Source Mirror direction for cron/session/state coverage

These pieces replace the Sannai-specific "raw source to event journal" and
"candidate to owner review" foundations with a portable profile-local system.

## Gaps Found By CW-005 Comparison

### Gap 1: Context Selector Parity

CW-003-v5 had an explicit selector:

- bridge seed pass for fresh cron/mailbox/family sources
- importance fill pass
- whole-card cap
- no partial card truncation
- status/runtime parity

Memory-OS prefetch must eventually expose the same class of guarantees. A
generic query/ranked recall is not enough for continuity. The selector needs to
protect recent bridge facts from being crowded out by older high-ranked cards.

Required Memory-OS behavior:

```text
context selector reads event/working/crystallized summaries
bridge sources receive bounded seed slots
selected records are whole records
dropped count is observable
status/doctor can explain selected vs dropped
```

Initial bridge seed algorithm:

```text
1. Build source buckets from eligible whole records:
   owner/foreground, cron, mailbox, room/family, state-source, governance.

2. Reserve a small seed budget before global ranking:
   - foreground/owner continuity: up to 2 records
   - cron: up to 1 record
   - mailbox: up to 1 record
   - room/family: up to 1 record
   - state-source: up to 1 record
   - governance: up to 1 record

3. Within each bucket, choose by:
   freshness first, then importance score, then deterministic event id.

4. If a bucket is empty, return its slot to the global fill pool.

5. Fill the remaining budget by score/importance/recency across all eligible
   whole records.

6. Never cut a selected record mid-card. If a card does not fit, drop it and
   record the drop reason.
```

These numbers are v0.1 defaults, not Sannai policy. Profiles may tune them
later, but the implementation must always report selected and dropped counts by
source class.

### Gap 2: Daily/Weekly Consolidation Mapping

CW-005 had daily digest and weekly proposal as separate stages. Memory-OS has
events, working, candidates, scoring, proposal queue, and crystallized memory,
but the exact generic "digest/consolidation" module is not yet formalized.

Required Memory-OS behavior:

```text
digest module reads event stream, not raw full sessions
weekly consolidation produces proposals/candidates
owner approval is required before crystallized writes
revision/provenance is recorded in audit
```

### Gap 3: Source-Aware Memory Ingestion

CW-005 and `hermes-memory-contract.md` explicitly distinguish owner,
mailbox, cron, tool, and system sources. Memory-OS mirror events must preserve
that source class so future USER/relationship/identity writes do not confuse
mailbox or cron content with owner facts.

Required Memory-OS behavior:

```text
event.source_class = owner | mailbox | cron | tool | system | file | room
owner facts are not inferred from mailbox/cron by default
tool/system facts do not become personal memory automatically
```

### Gap 4: Continuity Across Reset / Compression

`hermes-memory-contract.md` includes continuity summaries for reset,
compression, and session split. Entry mirrors cover sources, but they do not by
themselves create prior-session continuity summaries.

Required Memory-OS behavior:

```text
session end / reset / compression can create a bounded continuity event
child sessions can read the prior continuity event
old transcripts remain searchable but are not stuffed into context
```

### Gap 5: Memory Tool Mutation Provenance

Current Memory-OS mirrors `memory()` `add` into an event. CW-005's source-aware
ingestion direction implies full mutation provenance should eventually include
hash-only events for `replace` and `remove`.

Required Memory-OS behavior:

```text
memory add -> content bounded summary + hash
memory replace -> old/new hash refs, no full body required
memory remove -> target/hash ref, no full body required
```

## What Must Not Be Copied From Sannai

The reusable Memory-OS modules must not copy:

- Sannai identity/persona body
- Sannai SOUL, private diary, or owner-specific relationship text
- Sannai-specific growth policy
- CW-019 private thresholds as public defaults
- Sannai prompt language or front-end personality

The reusable system should copy only the architecture:

```text
source-aware entry coverage
bounded event cards
selector budget rules
digest/consolidation stages
owner approval before crystallization
profile-local isolation
```

## Updated Functional Target

After Runtime Hardening and continuity mapping, a blank Hermes host with
Memory-OS installed should have:

```text
foreground provider capture
cron execution mirror
profile session mirror
allowlisted state-source mirror
bounded continuity selector
heartbeat into working memory
candidate generation
evidence/scoring
proposal queue
owner-approved crystallized memory
no-send speak gate by default
```

This is the generalized version of the memory continuity that only Sannai had
before.

## Design Consequence

Entry/Source Mirror closes the coverage gap.

Context Selector + Digest/Consolidation closes the continuity gap.

Both are needed for the claim:

```text
Memory-OS is a full-coverage continuous memory system,
portable to a blank Hermes host.
```
