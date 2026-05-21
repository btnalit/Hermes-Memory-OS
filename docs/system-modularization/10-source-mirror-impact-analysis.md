# Source Mirror Coverage Architecture And Impact Analysis

Date: 2026-05-21

## Purpose

Clarify whether `CronMirror + SessionMirror/SourceMirror + StateSourceMirror`
is already the current design, how it fits the existing Memory-OS chain, and
what must be protected before implementing it.

This document also records the corrected direction: source coverage is not an
optional future topic. It is a Runtime Hardening gap that must be filled so
Memory-OS can cover the same classes of entrypoints that the old Sannai memory
contract proved were important.

## Current Design State

The current documented design was only partly in this shape before this
correction.

Already formalized:

- `CronMirror` is documented in
  `09-cronmirror-event-coverage-design.md`.
- `CronMirror` is scoped as a read-only mirror of Hermes cron execution facts.

Now required as part of Runtime Hardening:

- `SessionMirror` / `SourceMirror` for profile sessions and platform entry
  coverage.
- `StateSourceMirror` for allowlisted deterministic state writers.

Correct interpretation:

```text
Runtime Hardening must produce a pluginized source coverage family.
CronMirror is one scanner in that family, not the whole feature.
SessionMirror and StateSourceMirror are required to close the coverage gap.
```

## Existing Memory-OS Chain

The current Memory-OS provider chain is:

```text
foreground conversation
  -> MemoryProvider.prefetch()
  -> model response
  -> MemoryProvider.sync_turn()
  -> Memory-OS event: kind=conversation_turn
  -> runtime heartbeat
  -> InnerDriveEngine.process_event()
  -> working memory update
  -> crystallized candidate queue
  -> owner approval required before crystallized record
```

The current memory tool hook is:

```text
Hermes memory() add
  -> MemoryProvider.on_memory_write()
  -> Memory-OS event: kind=memory_write
```

This hook is a compatibility mirror into Memory-OS. It must not be treated as a
license to delete or rewrite Hermes built-in memory surfaces. Memory-OS remains
the external provider and canonical Memory-OS store; it does not make Hindsight
or legacy memory files canonical.

The runtime heartbeat processes canonical Memory-OS events regardless of source
as long as they use the standard event envelope. That is the shared integration
point for mirror modules.

## Proposed Mirror Family

The mirror family is a generic public mechanism. It learns from Sannai's old
coverage model, but it must not copy Sannai private persona, prompts, identity,
or owner-review policy into reusable modules.

This distinction matters:

```text
Allowed:
  make cron/session/state coverage a portable Memory-OS feature
  let future Sannai migration use the same generic modules

Not allowed:
  make Sannai's private continuity system a public module
  embed Sannai-specific identity, diary, or prompt bodies in product code
```

### CronMirror

Purpose:

- mirror Hermes cron execution facts
- make scheduled work visible as Memory-OS events

Reads:

- `cron/jobs.json`
- `cron/output/{job_id}/*.md`

Writes:

- Memory-OS events with `source=cron`
- Memory-OS audit
- mirror state for idempotency

Must not:

- trigger cron
- edit jobs
- enable memory inside cron
- embed raw prompt/output bodies
- send messages

### SessionMirror / SourceMirror

Purpose:

- mirror session-level facts for entrypoints that do not pass through provider
  `sync_turn`, predate provider deployment, or need compatibility replay
- cover Hermes profile sessions the same way Sannai's old overlay could see
  cron sessions
- support CLI, Telegram, WeCom, Weixin, other gateway sessions, and cron agent
  sessions as source classes

Reads:

- profile-local `state.db` sessions/messages when available
- profile-local `session_*.json` files as fallback or corroboration
- bounded safe session headers and selected last-turn text
- message counts, tool counts, platform, timestamps, session id

Writes:

- Memory-OS events such as `session_observed` or
  `conversation_turn_mirrored`
- Memory-OS audit
- mirror state for idempotency

Must not:

- mirror raw private conversation bodies by default
- duplicate provider-captured foreground turns
- treat mirrored sessions as owner-approved crystallized memory
- cross profile boundaries

Key behavior:

- use `state.db` as the primary session timeline when available
- use `session_*.json` as fallback/corroboration
- if a session was already captured by provider `sync_turn`, mark it covered
  and skip event duplication
- if a session was not captured by provider, write a bounded-summary mirror
  event
- if a session belongs to a cron agent run, preserve `platform=cron` and source
  refs so runtime can distinguish scheduled memories from foreground chat
- empty session roots are healthy on blank hosts

Metadata-only events are not enough for session coverage. The old Sannai
recent-events bridge used bounded last user/assistant snippets to preserve
continuity. The generic module should do the same without storing full raw
transcripts:

```text
body_policy=bounded_summary
summary includes clipped last relevant exchange
hashes preserve provenance for dedup
full transcript body is not embedded
```

### StateSourceMirror

Purpose:

- mirror stable state-source changes that are not normal conversations
- preserve provenance for digests, journals, candidates, proposals, reports,
  and other deterministic state writers

Reads:

- configured allowlisted state files
- file metadata, hashes, mtime, line counts, bounded headers
- optional safe summaries for explicitly allowlisted public-ish artifacts

Writes:

- Memory-OS events such as `state_source_changed`
- Memory-OS audit
- mirror state for idempotency

Must not:

- read identity bodies by default
- mutate identity
- auto-approve crystallized records
- treat CW-019 candidates as approved memory
- export private bodies

Key behavior:

- use an allowlist, not broad directory scanning
- use hash-based idempotency
- represent candidate-like files as candidate surfaces only
- let future private adapters add Sannai-specific state mappings with owner
  approval, while the public module remains generic

## Whole-Chain View

The complete safe chain should be:

```text
Entry source
  -> provider path OR mirror path
  -> Memory-OS event stream
  -> runtime heartbeat
  -> working memory / candidates
  -> evidence and scoring
  -> proposal queue / ops-gate
  -> speak gate would-send only unless explicitly enabled
```

Provider path:

```text
CLI / Telegram / WeCom / Weixin foreground turn
  -> provider sync_turn()
  -> conversation_turn event
```

Mirror path:

```text
Hermes cron output
  -> CronMirror
  -> cron_job_run event

Hermes session not covered by provider
  -> SessionMirror
  -> session_observed or conversation_turn_mirrored event

Stable state file changed
  -> StateSourceMirror
  -> state_source_changed event
```

The provider path and mirror path converge only at the event stream. They must
not call each other.

This preserves the existing Memory-OS functions:

- provider `sync_turn` remains the first-class foreground capture path
- `on_memory_write()` remains the compatibility hook for Hermes memory tool
  writes
- mirror modules fill gaps without replacing those hooks
- runtime heartbeat processes all event sources through the same working and
  candidate path

## Impact On Existing Memory-OS Features

### Event Stream

Expected impact:

- more event sources and kinds
- better provenance for cron, session, and state activity

Risk:

- duplicate events if SessionMirror mirrors provider-captured sessions
- noisy events if state files are mirrored too often

Required guard:

- every mirror needs a deterministic dedup key
- SessionMirror must skip or mark sessions already captured by provider events
- StateSourceMirror must use hash-based idempotency

### Mirror Runtime State Recovery

Mirror state files are an optimization, not the source of truth.

Expected state files:

```text
$HERMES_HOME/memory-os/runtime/cron_mirror_state.json
$HERMES_HOME/memory-os/runtime/session_mirror_state.json
$HERMES_HOME/memory-os/runtime/state_source_mirror_state.json
```

If a state file is missing or corrupt:

1. mark the scan as `rebuild_state_required`
2. rebuild the seen set from existing Memory-OS events by reading their
   `safe_ref.dedup_key`, `source_ref`, source hash, and source revision
3. write a repaired state file atomically
4. run the current scan using the rebuilt seen set

If the event stream does not contain enough source refs to rebuild a key, the
mirror may produce a duplicate only in operator-approved dry-run or repair
mode. Normal recurring scans must fail closed rather than append uncertain
duplicates.

### Working Memory

Expected impact:

- inner-drive can see scheduled and state-derived signals
- lingering/emotional/curiosity/attention can evolve from more than foreground
  chat

Risk:

- working memory can become dominated by low-value cron/status events

Required guard:

- mirror events must carry source and kind tags
- heartbeat/inner-drive should be able to weight or filter mirror event kinds
- high-volume state files need caps

### Crystallized Candidates

Expected impact:

- mirror events may produce candidates with clear provenance

Risk:

- raw cron/session/state facts could be mistaken for approved memory

Required guard:

- mirror events stay `promotion_state=raw`
- candidates are queued only as candidates
- crystallized records still require explicit `approve_for_crystallized`

### Prefetch

Expected impact:

- future recall can include scheduled work and state provenance

Risk:

- diagnostic answers or user-facing context may include stale mirrored facts

Required guard:

- diagnostic grounding remains authoritative for provider/runtime facts
- mirror events should be summarized and bounded
- no raw bodies enter prefetch by default

### Hindsight Adapter

Expected impact:

- none by default

Risk:

- mirrored raw events could leak to Hindsight if adapter boundaries weaken

Required guard:

- Hindsight adapter continues to refuse raw events, working memory, and
  candidates
- only owner-approved crystallized records are exportable

### Module System

Expected impact:

- mirror modules become Runtime Hardening modules
- status/doctor can explain coverage by source class

Risk:

- ModuleBus/heartbeat/index scheduling can contend if all mirrors run at once

Required guard:

- each mirror uses ScheduleCoordinator
- status/doctor report lock contention and skipped scans
- first deployment stays operator-triggered, not timer-driven

## Compatibility With Original Documents

The mirror family must preserve the following existing documented rules:

- Memory-OS is the L1 canonical store for Memory-OS records.
- SQLite is a rebuildable index, not source of truth.
- Identity files are not automatic write targets.
- Crystallized records require owner approval.
- Hindsight is optional adapter only, not canonical.
- Sannai is a compatibility constraint, not a public extraction target.
- Delivery remains no-send by default in v0.1.
- 10.20.2.88 production is out of scope for implementation.

Nothing in the mirror family should weaken these rules.

## Sannai Compatibility Lessons

The old Sannai system proves that scheduled work can be covered, but it does so
through private profile-specific surfaces:

- cron sessions
- computed recent-events overlay
- memory journal
- daily digest
- treasure index
- quiet moments
- heartbeat lingering candidates

Public Memory-OS modules should learn from that shape without copying it.

Required compatibility position:

```text
Sannai private contract remains private.
Public mirrors provide generic source coverage.
Future Sannai migration can use public mirrors.
Private adapters may map Sannai-specific files with owner approval.
```

Functional target:

```text
If a blank Hermes host installs Memory-OS modules:
  foreground provider writes are captured
  cron runs are mirrored
  profile sessions outside provider capture are mirrored
  allowlisted state-source changes are mirrored

If Sannai later migrates:
  she can use the same generic mirror modules
  private identity/persona logic stays private
  old coverage classes remain represented in Memory-OS events
```

## Required Implementation Gates

The mirror family can be implemented as separate pluginized scanners under one
source coverage concept. Each scanner needs its own tests and status/doctor
surface.

1. CronMirror
   - cron jobs and output roots
   - bounded header parsing
   - execution fact event shape
   - idempotency keys

2. SessionMirror / SourceMirror
   - exact session roots and `state.db` behavior
   - covered platforms
   - provider duplicate detection
   - event shapes
   - bounded-summary and body redaction policy
   - idempotency keys

3. StateSourceMirror
   - allowlisted file classes
   - excluded identity/private files
   - hash and mtime behavior
   - summary policy
   - candidate-only rules for CW-019-like files

4. Chain interaction
   - heartbeat weighting/filtering for mirror events
   - prefetch visibility rules
   - index behavior
   - status/doctor output

## Recommended Decision

Implement the coverage family in order, keeping each scanner pluginized and
independently verifiable:

```text
RH-05 CronMirror
  -> execution facts only

RH-09 SessionMirror / SourceMirror
  -> session and platform source coverage

RH-10 StateSourceMirror
  -> stable state source coverage
```

This keeps the current Memory-OS functions intact while closing the actual
coverage gap. The goal is functional completeness, not a partial cron-only
mirror.
