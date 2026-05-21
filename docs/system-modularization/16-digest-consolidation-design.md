# Digest And Consolidation Mapping

Date: 2026-05-21

## Purpose

Define RH-13: the generic equivalent of Sannai daily digest and weekly
consolidation, without copying Sannai private persona, thresholds, owner-review
language, or identity policy.

The goal is continuity, not automatic long-term belief formation.

```text
Memory-OS events / working / candidates / evidence
  -> bounded daily digest artifact
  -> weekly consolidation proposal or candidate
  -> owner review
  -> only later, approved crystallized memory
```

Digest and consolidation make prior activity visible and reviewable. They must
not bypass Proposal Queue, Speak Gate, or crystallized approval.

## Non-Goals

RH-13 does not:

- read raw full session transcripts when bounded Memory-OS records exist
- write approved crystallized records
- write identity or relationship memory
- approve proposals
- send messages
- execute actions
- replace Governance Feedback Bridge
- copy Sannai private growth policy
- enable recurring production schedules

## Dependencies

RH-13 depends on committed RH-12 Inner Drive Mirror Compatibility:

```text
fd6ebe8 Add inner drive mirror eligibility policy
```

Reason:

- mirror events must be classified before any digest/consolidation output can
  influence working memory or candidate queues
- unknown event kinds must remain `index_only`
- cron/state/session metadata must not become owner-facing facts by default

RH-13 also assumes the existing v0.1 module boundaries:

- Speak Gate records `would_send` only; `actual_send=false`
- Evidence/Scoring writes one evidence and one score per collected subject
- Proposal Queue approval is proposal-only and not crystallized approval
- SQLite is a rebuildable index, not canonical memory

## Time Boundary Policy

Digest and consolidation windows are profile-local.

Defaults:

```text
time_zone: UTC
daily_window: 00:00:00 through 23:59:59.999999 in profile_tz
weekly_window: ISO week, Monday 00:00:00 through Sunday 23:59:59.999999 in profile_tz
```

The profile may override `time_zone`, but the resolved timezone must be recorded
inside every digest and consolidation artifact.

Window assignment:

- normal events are assigned by `event.created_at` converted to `profile_tz`
- digest artifact dates are the profile-local window date, not host-local date
- weekly artifact ids use ISO year and ISO week in `profile_tz`
- cross-midnight conversations are split by event timestamp; a future session
  bridge may add a continuity ref across the split, but RH-13 does not merge
  day windows

Late-arriving events:

- if an event for the current open daily window arrives before finalization, it
  can be included in that open digest
- if an event arrives for a past finalized daily window, RH-13 does not rewrite
  that past digest by default
- the late event is eligible for the current day's `late_arrival` group and for
  weekly consolidation over its original event timestamp window
- audit records `late_arrival_count` and affected source refs

This keeps daily digest artifacts stable while preserving the event stream as
the canonical source for later weekly selection.

## Input Surfaces

Allowed input surfaces:

| Input | Allowed fields | Forbidden fields |
| --- | --- | --- |
| Memory-OS events | event id, kind, source class, summary, tags, safe refs, timestamps | raw private body beyond bounded event summary |
| Working memory | item id, kind, text, source refs, intensity/weight | private identity body |
| Crystallized candidates | candidate id, kind, source refs, bridge state, approval state | approved long-form body unless already public to Memory-OS |
| Proposal Queue | candidate id, title, state, source refs, approval purpose | raw private proposal body in status/report output |
| Evidence/Scoring | score id, subject ref, subject kind, score, evidence refs, explanation ref | raw hidden chain-of-thought or transcript body |
| Governance feedback | bounded summary, artifact refs, state | hidden instructions or action commands |

Digest/consolidation should prefer Memory-OS summaries and refs over source
files. SessionMirror and StateSourceMirror exist to convert source files into
bounded events before RH-13 sees them.

## Output Surfaces

RH-13 may write:

- local digest artifacts under the module root
- Memory-OS audit records
- proposal queue candidates for owner review
- crystallized candidates with `approved=false`
- optional summary-only Memory-OS events if needed for selector continuity

RH-13 must not write:

- approved crystallized records
- identity memory
- relationship memory
- real delivery records
- Hindsight canonical records
- raw session transcripts

Recommended artifact layout:

```text
$HERMES_HOME/system-modules/digest_consolidation/
  daily/YYYY-MM-DD.json
  weekly/YYYY-Www.json
  provenance/YYYY-MM-DD.jsonl
```

Artifacts are profile-local.

## Daily Digest

Daily digest is a bounded summary of what Memory-OS already knows.

It should group by source class and event kind:

```text
foreground conversation
mirrored conversation
memory writes
working memory changes
crystallized candidates
proposal/governance state
cron/session/state-source observations
tool/action failures
```

Each group stores:

- count
- selected refs
- dropped count
- top bounded summaries
- source class
- digest policy
- earliest/latest timestamp

The daily digest is not a belief. It is a reviewable index card.

Example shape:

```json
{
  "schema_version": "hermes.digest.daily.v0",
  "profile": "default",
  "date": "2026-05-21",
  "groups": [
    {
      "source_class": "foreground",
      "event_kind": "conversation_turn",
      "selected_count": 5,
      "dropped_count": 12,
      "refs": ["event:evt_1", "working:lingering_1"],
      "summary": "Foreground conversation produced several unresolved memory-system questions.",
      "candidate_allowed": true
    }
  ],
  "actual_send": false,
  "actual_approve": false
}
```

## Event Retention Across Digest Levels

`dropped_count` never means forgotten.

Daily digest selection is a bounded presentation layer:

```text
selected_count = records shown in that daily card
dropped_count  = eligible records not shown in that daily card
```

Dropped records stay in the Memory-OS event stream and remain eligible for
later selectors, weekly consolidation, search, evidence/scoring, and owner
review.

Weekly consolidation read scope:

```text
primary: daily digest artifacts for the target week
expanded: Memory-OS event stream filtered by the target weekly window
supporting: current proposal/candidate/evidence state by refs
forbidden: raw full session transcripts
```

The weekly pass may re-select records that were dropped by a daily digest. This
prevents a daily budget limit from becoming permanent memory loss.

## Weekly Consolidation

Weekly consolidation reads daily digest artifacts, Memory-OS events in the
target weekly window, plus current candidate and proposal state. It does not
re-open raw sessions.

It can produce:

- a local weekly consolidation artifact
- one or more Proposal Queue candidates
- one or more unapproved crystallized candidates

It cannot produce:

- approved crystallized memory
- identity changes
- send attempts
- direct self-modification

Default rule:

```text
daily digest -> weekly consolidation -> candidate/proposal -> owner review
```

No weekly result becomes canonical long-term memory until owner approval.

## Source-Class Policy

| Source class | Daily digest | Weekly candidate default | Notes |
| --- | --- | --- | --- |
| foreground conversation | include | allowed when source refs are meaningful | highest continuity value |
| memory write | include | allowed with provenance | preserves memory() mutation trail |
| mirrored conversation bounded summary | include | allowed with lower weight | never raw transcript |
| cron metadata | include as operational state | not allowed by default | can inform attention, not owner facts |
| session metadata-only | include as coverage state | not allowed by default | counts/platform only |
| state-source hash/mtime | include as state change | not allowed by default | candidate only if allowlisted semantic summary exists |
| governance feedback | include bounded section | proposal-only by default | RH-14 writes queryable feedback |
| tool/action failure | include | allowed as operational learning candidate | must route through Ops-Gate/Proposal Queue |
| runtime/index/audit | normally exclude | not allowed | prevents self-referential noise |

Unknown source class defaults to digest-only with no candidate.

## Candidate Creation Rules

Digest/consolidation may create a candidate only when all conditions hold:

```text
bounded summary exists
source refs exist
source class allows candidates
not a duplicate of an active candidate/proposal
not identity or relationship memory
not raw private body
not generated only from operational metadata
```

Candidate record must include:

- candidate id
- digest/consolidation artifact ref
- source event refs
- source class counts
- evidence refs when available
- selected/dropped counts
- hash of the artifact that produced it
- `crystallized_approved=false`

Candidate volume cap:

```text
max_candidates_per_week: 5
```

The default cap is profile-configurable, but it must exist. If more candidate
groups qualify:

- rank by source-class priority, owner relevance, evidence support, freshness,
  and unresolved proposal state
- merge compatible lower-priority groups under a shared semantic subject
- defer the remainder without deleting their refs
- write `deferred_candidate_count` and deferred refs to audit/provenance

This prevents a weekly consolidation run from flooding owner review.

## Evidence/Scoring Interaction

Evidence/Scoring v0.1 creates one score per collected subject:

```text
events + working items + proposal queue items + crystallized candidates
```

This is explainable, but raw score volume is not a digest priority by itself.

RH-13 must group scores before using them:

- by subject kind
- by source class
- by artifact/proposal state
- by recency window
- by evidence refs

Digest/consolidation should use score data as support, not as an automatic
promotion rule. A high score may help a candidate explanation, but it must not
approve or crystallize anything.

## Continuity Selector Interaction

Daily digest and weekly consolidation artifacts provide bridge-friendly context
for RH-11.

Rules:

- selector reads digest summaries, not full artifacts by default
- fresh digest summaries get bounded bridge seed slots
- active proposal/consolidation items rank above stale reports
- rejected/expired consolidation candidates stay searchable but normally not
  selected
- diagnostic grounding remains authoritative for provider/runtime questions

## Inner Drive Interaction

Digest events are not normal emotional events.

Default policy:

```text
digest_daily_written       -> evidence_only
digest_weekly_written      -> evidence_only
consolidation_candidate    -> candidate_surface
owner_attention_needed     -> low_weight attention
```

Digest/consolidation must not create lingering/emotional/curiosity items by
itself. If a future profile wants that behavior, it must be explicit and
profile-local.

## Governance Feedback Interaction

RH-13 and RH-14 are adjacent but separate.

RH-13:

- condenses Memory-OS continuity into digest/consolidation artifacts
- may create review candidates/proposals

RH-14:

- returns governance decisions, proposal transitions, and self-evolution
  outcomes to Memory-OS as summary-only events

If RH-13 reads governance state, it reads bounded summaries and artifact refs
only. It must not trigger Speak Gate or wake a session.

## Idempotency

Daily digest idempotency key:

```text
profile + date + selected source refs hash + digest schema version
```

Weekly consolidation idempotency key:

```text
profile + ISO week + daily digest refs hash + weekly event source refs hash + consolidation schema version
```

Proposal/candidate dedup key:

```text
semantic_subject + candidate_kind + canonical source ref set
```

Canonical source ref set:

- use a set, not a list
- sort refs before hashing
- ignore duplicate refs
- include only stable refs such as event ids, digest artifact ids, evidence ids,
  score ids, and proposal ids

Semantic subject:

- a bounded deterministic label for the thing being proposed
- examples:
  - `memory_os_runtime_diagnostics`
  - `telegram_session_continuity`
  - `cron_failure_backpressure`
  - `owner_review_backlog`
- must not contain private body text

Dedup behavior:

- same semantic subject and same candidate kind updates or skips an existing
  active candidate, even when source refs only partially overlap
- fully identical canonical source ref sets are exact duplicates
- partial overlap with same semantic subject appends provenance to the existing
  candidate and writes audit action `candidate_updated_via_overlap`
- different semantic subjects may create separate candidates even if some
  source refs overlap

Example:

```text
candidate A:
  subject=memory_os_runtime_diagnostics
  refs={event_1,event_2,event_3}

candidate B:
  subject=memory_os_runtime_diagnostics
  refs={event_2,event_3,event_4}

result:
  update A with event_4 provenance; do not create B
```

Repeated runs should update or skip the same artifact rather than append
duplicates.

## Failure And Atomicity

Digest/consolidation writes must be transactional at the artifact level.

Required file write sequence:

```text
write artifact.tmp
flush/fsync where available
atomic rename to final artifact path
write provenance/audit after final artifact exists
```

Failure behavior:

- no partial final artifact should remain
- `.tmp` files can be reported by doctor and safely removed or retried by an
  operator command
- failed attempts write audit with failure reason when audit is available
- malformed source records are skipped into the digest provenance with
  `parse_error_count`; one bad source record must not abort the whole day unless
  the artifact cannot be written safely
- retry starts from canonical Memory-OS sources and existing completed
  artifacts, not from partial output

## Artifact Accumulation

RH-13 does not physically prune digest/consolidation artifacts. That belongs to
RH-17 Retention And Compaction.

Default v0.1 behavior:

- keep daily artifacts indefinitely
- keep weekly artifacts indefinitely
- expose artifact counts through status/doctor
- warn if artifact count or total artifact bytes crosses configurable
  thresholds
- never delete digest artifacts automatically in RH-13

RH-17 may later archive or compact old digest artifacts, but must preserve
provenance and auditability.

## Dry-Run / Apply Equivalence

Dry-run is a review contract.

The would-write payload produced by dry-run must match apply output except for
explicitly excluded runtime fields:

- `generated_at`
- wall-clock execution duration
- temporary file path
- audit attempt id

Acceptance requires a byte-equivalence test over canonicalized JSON:

```text
dry_run would_write artifact
apply final artifact
canonicalize by removing allowed volatile fields
hashes must match
```

If dry-run and apply disagree, apply must fail closed.

## Runtime Validation Workflow

After any RH-13 run that writes artifacts, candidates, proposals, or audit:

```bash
HERMES_HOME=/root/.hermes hermes memory_os heartbeat --max-events 100
HERMES_HOME=/root/.hermes hermes memory_os doctor
```

Expected result:

- doctor status `ok`, except known warnings such as disabled optional Hindsight
- no index mismatch remains after catch-up
- no queue backlog
- no actual send
- no actual approve
- no crystallized approval

## Tests And Acceptance

Required local tests:

- daily digest reads Memory-OS events and working summaries, not raw sessions
- daily digest groups by source class and event kind
- weekly consolidation reads daily digest artifacts plus target-window
  Memory-OS events, not raw full sessions
- weekly consolidation creates proposal/candidate only, never approved records
- source-class policy blocks cron/session/state metadata from owner facts
- candidate creation is idempotent across repeated runs
- candidate dedup uses semantic subject plus order-independent source ref set
- score grouping prevents score-count explosion from becoming candidate spam
- daily/weekly windows use profile timezone and stable ISO week boundaries
- weekly consolidation can re-select events dropped from daily digest
- digest artifact write is atomic and leaves no partial final artifact
- digest artifact accumulation is reported but not pruned in RH-13
- weekly candidate creation respects `max_candidates_per_week`
- dry-run and apply artifacts are byte-identical after canonicalizing volatile
  fields
- digest/consolidation events classify as `evidence_only` or
  `candidate_surface` for Inner Drive
- Sannai-shaped fixture identity hash remains unchanged
- status/doctor never print private bodies

Required `10.20.3.200` dry-run:

- run against current `default` profile
- no `--apply` until local tests pass
- dry-run reports selected/dropped refs and would-write counts
- Memory-OS event count does not change during dry-run
- working/candidate/proposal counts do not change during dry-run
- after apply is approved later, heartbeat catch-up plus doctor is run

## Open Questions

None blocking for RH-13 design.

Implementation should still confirm the exact command names and artifact root
when the module code is introduced.
