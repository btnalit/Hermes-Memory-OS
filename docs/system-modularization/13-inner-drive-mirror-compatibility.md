# Inner Drive Mirror Compatibility

Date: 2026-05-21

## Purpose

Prevent Entry/Source Mirror expansion from flooding or corrupting the existing
Inner Drive runtime.

Current Inner Drive is a small v0.1 runtime. It is correct for the current
Memory-OS event volume, but it must not be exposed to high-volume mirror events
without an event eligibility policy.

## Current Implementation Reality

Current Memory-OS runtime behavior:

```text
MemoryOSRuntime.heartbeat()
  -> read all events
  -> process every unprocessed event
  -> InnerDriveEngine.process_event(event)
  -> write lingering working item
  -> append crystallized candidate
```

Current module behavior:

```text
InnerDriveRuntimeModule.run_once()
  -> read profile events
  -> process every unprocessed event
  -> write lingering working item
  -> append crystallized candidate
```

Current `InnerDriveEngine.process_event()` does not yet distinguish:

- foreground conversation events
- cron execution facts
- mirrored session summaries
- state-source changed events
- candidate/evidence surface changes
- tool/system/runtime events

This means the current implementation is not yet safe to connect directly to
the full mirror family at production-like volume.

## Compatibility Problem

If CronMirror, SessionMirror, and StateSourceMirror all write events, a naive
Inner Drive heartbeat would turn everything into lingering/candidate records.

Bad outcomes:

- `cron_job_run` status events become "important memories"
- state file mtime/hash changes become emotional/lingering items
- CW-019-like candidate files recursively create new candidates
- digest/proposal artifacts create duplicate candidates for the same source
- working memory becomes dominated by operational noise
- owner review backlog grows from source coverage instead of meaningful
  continuity

This would break the Memory-OS value proposition even if the mirror modules are
individually safe.

## Required Event Policy

Every event entering Inner Drive must be classified before processing.

Recommended policy fields:

```json
{
  "source_class": "owner | assistant | cron | mailbox | room | file | tool | system | state",
  "drive_policy": "eligible | low_weight | index_only | evidence_only | candidate_surface | ignore",
  "drive_weight": 0.0,
  "working_targets": ["lingering", "attention"],
  "candidate_allowed": false
}
```

These may live in `safe_ref`, tags, or a future event metadata object. The
important part is the behavior, not the exact storage key.

## Initial Policy Matrix

| Event kind/source | Inner Drive default |
| --- | --- |
| `conversation_turn` from provider foreground | eligible |
| `memory_write` add from memory tool | eligible, low/medium weight |
| `conversation_turn_mirrored` from uncovered session | eligible if bounded-summary and not duplicate |
| `session_observed` metadata-only | index_only |
| `cron_job_run` execution fact | index_only or low_weight attention, no candidate |
| `state_source_changed` digest/journal | low_weight or evidence_only |
| `journal_card_observed` | eligible, bounded weight |
| `candidate_surface_changed` | evidence_only, no recursive candidate |
| CW-019-like quiet/candidate file | candidate_surface, no working identity, no crystallized candidate |
| `runtime_heartbeat` / module audit / index events | ignore for Inner Drive |
| tool/system operational event | evidence_only or ignore |

Default rule:

```text
Unknown event kinds are index_only, not eligible.
```

This is conservative and prevents new mirror event kinds from silently changing
working memory.

## Candidate Generation Rules

Inner Drive may create candidates only when:

- event has `candidate_allowed=true`, or
- event kind is explicitly allowlisted by the Inner Drive policy

Candidate generation must be disabled for:

- cron execution metadata
- raw state-source mtime/hash changes
- candidate-surface changes
- existing proposal/candidate artifacts
- audit/runtime/index events

This prevents recursive candidate inflation.

## Working Memory Rules

Working memory updates must be target-specific:

```text
lingering:
  user-facing, relationship, unresolved, meaningful session summaries

emotional:
  explicit affective signal or owner/agent relationship context

curiosity:
  exploration-worthy question or open thread

attention:
  operationally relevant but non-emotional state, including some cron/state refs
```

Not every event belongs in `lingering`.

## Volume And Backpressure

Mirror events can arrive in batches. Inner Drive must have source-level caps:

```text
max_events_per_run
max_events_per_source_class
max_candidates_per_run
max_candidates_per_day
max_working_items_per_kind
```

When a cap is hit:

- write audit
- leave unprocessed events pending or mark them as skipped by policy
- do not silently drop without evidence

## Idempotency And Dedup

Existing processed-event id tracking is necessary but not sufficient.

Mirror compatibility also needs semantic dedup:

- SessionMirror dedups by session id + content hash/source revision
- StateSourceMirror dedups by source path + content hash
- Inner Drive dedups candidates by source event id and candidate semantic key

This avoids duplicate candidates when a source is mirrored through more than
one path.

## Prefetch And Context Interaction

Inner Drive output must not make diagnostic or runtime answers stale.

Rules:

- diagnostic grounding still suppresses historical recall for provider/runtime
  questions
- operational mirror events should not dominate normal prefetch
- selector should expose selected/dropped records
- working items generated from mirror events should preserve source class

## Sannai Compatibility

When Sannai migrates, this policy keeps her old behavior safe:

- cron/free-time session summaries can become continuity signals
- quiet/candidate surfaces remain evidence/candidate-only
- diary/digest/journal state can contribute bounded context
- identity/persona bodies are not automatically rewritten
- no mirror event can force S5 or public expression

This is how Memory-OS can support Sannai's full coverage without copying her
private growth policy into the public module.

## Required Tests Before Enabling Mirror Events

Add tests before any mirror module writes are processed by Inner Drive:

- `cron_job_run` does not create a crystallized candidate by default
- metadata-only `session_observed` does not create lingering by default
- bounded `conversation_turn_mirrored` can create one low/medium working item
- `candidate_surface_changed` never creates another candidate
- unknown event kinds are `index_only`
- source caps prevent a batch of cron/state events from dominating a run
- Sannai-shaped fixture keeps identity hashes unchanged

## Implementation Gate

Do not enable recurring Mirror -> Heartbeat -> InnerDrive processing until:

```text
event eligibility policy exists
candidate allowlist exists
source caps exist
unknown kind default is conservative
tests cover mirror event classes
```

Operator-triggered dry-run scanning may be implemented earlier, but applying
mirror events into the runtime heartbeat loop requires this gate.
