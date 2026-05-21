# Sannai Coverage Audit And Entry Mirror Requirements

Date: 2026-05-21

## Scope

This is a read-only audit of the existing Sannai memory coverage on
`10.20.2.88 / YC-NAS`, used to validate the Memory-OS Entry/Source Mirror
design.

No production files were modified. No services were restarted. No cron jobs
were triggered. No private session bodies, prompts, identity bodies, or secrets
were copied into this repository.

## Live Facts

Host and service boundary:

```text
Host: 10.20.2.88 / YC-NAS
Main Hermes HERMES_HOME: /vol1/.hermes
Sannai HERMES_HOME: /root/.hermes/profiles/sannai
Main gateway service: hermes-gateway.service, active/running
Sannai gateway service: hermes-gateway-sannai.service, active/running
Hermes version: v0.14.0 (2026.5.16)
```

Sannai memory provider state:

```text
Built-in memory: always active
External provider: none
memory.provider: ""
memory.dynamic_state_overlay.enabled: true
```

This means Sannai's current coverage is not provided by Hindsight or a Hermes
external memory provider. It is provided by built-in memory plus a private
dynamic overlay and state pipeline.

## Current Sannai Coverage Sources

### 1. Profile Sessions

Sannai has two session surfaces:

```text
/root/.hermes/profiles/sannai/state.db
/root/.hermes/profiles/sannai/sessions/session_*.json
```

Observed `state.db` metadata:

```text
sessions table: 193 rows
sessions by source:
  cron: 151
  mailbox: 21
  telegram: 21

messages table: 5142 rows
messages by role:
  assistant: 2419
  tool: 1849
  user: 835
  session_meta: 39
```

Observed session JSON metadata:

```text
session_*.json files: 286
recent sample includes platforms:
  cron
  telegram
  mailbox
  curator
```

Important conclusion:

```text
SessionMirror must treat state.db as the primary session source.
session_*.json can be a fallback or corroborating source.
```

If SessionMirror only scans `session_*.json`, it may miss or mis-order the
canonical session timeline that Hermes stores in `state.db`.

SQLite read rule:

```text
SessionMirror must open state.db read-only:
  file:<profile>/state.db?mode=ro

It must not request write access, run migrations, checkpoint WAL, vacuum, or
hold long transactions. If the gateway is writing concurrently, SessionMirror
may accept a small freshness lag instead of blocking the gateway. A failed
read because the database is momentarily busy should be reported as a deferred
scan, not as a reason to mutate or restart Hermes.
```

Implementation must confirm the target host's SQLite journal mode before
enabling recurring scans. WAL mode permits concurrent readers and writers; if a
host uses a stricter mode, SessionMirror stays operator-triggered until the
read behavior is proven safe.

### 2. Sannai Cron

Sannai profile cron:

```text
cron jobs: 10
cron output files: 858
```

Observed job classes:

- foreground-like agent cron:
  - free time
  - afterglow checks
  - random heartbeat one-shot
- script/no-agent cron:
  - random heartbeat scheduler
  - treasure index refresh
  - daily digest
  - weekly consolidation proposal
  - memory journal refresh

Main profile also contains Sannai-related cron jobs:

- Wandering Mind weekly run
- household digest refresh
- Sannai weekly consolidation report
- CW-019 owner review report
- CW-019 nightly candidate window

Important conclusion:

```text
CronMirror covers execution facts.
SessionMirror covers agent cron session memory.
StateSourceMirror covers no-agent script outputs that become state.
```

Cron output metadata alone is not enough to reproduce old Sannai coverage.

### 3. Dynamic Request Overlay

Sannai's config contains a dynamic state overlay with these source classes:

```text
state_dir: /vol1/.hermes/state/sannai
recent_events_sessions_dir: /vol1/.hermes/profiles/sannai/sessions
recent_events_treasure_dir: /vol1/1000/小宝贝的宝库
recent_events_family_state_dir: /vol1/.hermes/state/family-room
```

Overlay source set:

- `state.json`
- `recent_events(computed)`
- `identity_snapshot.md`
- `relationship_snapshot.md`
- `recent_life_snapshot.md`
- `beliefs.md`
- `open_threads.md`
- `capability_map.md`
- `treasure_index.md`
- `diary.md`
- `afterglow_trigger.json`
- `self_memory.md` and `relationship_memory.md` currently configured with cap
  `0`, so they exist but are not injected directly
- `lingering_thoughts.json` exists but is not injected in the current status

Observed request overlay:

```text
enabled: yes
computed_now: yes
would_inject: yes
journal_exists: yes
journal_behind_sources: no
fallback_active: no
```

Important conclusion:

```text
The old coverage is an overlay builder, not just a memory store.
Memory-OS should not recreate the private Sannai overlay.
It should capture the same source classes into the generic event stream.
```

### 4. Memory Journal And Digests

Sannai state root:

```text
/vol1/.hermes/state/sannai
```

Observed important state surfaces:

```text
memory_journal/events.jsonl: 491 lines
digests/daily: 11 files
digests/weekly: 3 files
treasure_index.md: present
diary.md: present
quiet_moments.jsonl: present
heartbeat_lingering_candidates.jsonl: present
```

The existing journal builder reads recent treasure files, sessions, and
family-room state, then appends event cards to
`memory_journal/events.jsonl`. The request overlay prefers that journal when it
is fresh; otherwise it falls back to recent sessions, treasure, and family
state.

Important conclusion:

```text
StateSourceMirror must support allowlisted structured state sources.
It must not be a broad directory mirror.
```

### 5. CW-019 Quiet And Candidate Surfaces

Observed CW-019 surfaces:

```text
quiet_moments.jsonl
heartbeat_lingering_candidates.jsonl
_cw019_s4_live/raw_debug/
```

These surfaces are backend-only candidate evidence. They are not active
long-term memory and they are not crystallized approval.

Important conclusion:

```text
StateSourceMirror may mirror CW-019-like surfaces as candidate/evidence events.
It must never upgrade them to working identity, crystallized records, or send.
```

## Coverage Chain In The Old Sannai System

The old Sannai chain looks like this:

```text
gateway / cron / mailbox / curator
  -> state.db sessions + messages
  -> session_*.json files
  -> memory_journal refresh reads sessions/treasure/family
  -> memory_journal/events.jsonl
  -> daily/weekly digest builders
  -> dynamic request overlay
  -> next Sannai foreground or cron prompt
```

For CW-019:

```text
recent sessions + quiet windows
  -> live heartbeat
  -> quiet_moments.jsonl
  -> heartbeat_lingering_candidates.jsonl
  -> owner review/report surfaces
```

This proved the required product behavior:

```text
scheduled work and side-channel state can become part of continuity
without making every cron run write directly to long-term memory
```

## Translation To Memory-OS Modules

### Provider Path

Already covered by Memory-OS:

```text
foreground provider turn
  -> sync_turn()
  -> conversation_turn event
  -> heartbeat
  -> working memory / candidates
```

Current `on_memory_write()` also mirrors Hermes `memory()` tool `add` writes
into Memory-OS as `memory_write` events.

Potential remaining gap:

```text
memory() replace/remove are currently not mirrored as events.
```

This is not a blocker for Entry Mirror, but should be tracked if full memory
mutation provenance becomes required.

### CronMirror

Generic module position:

```text
Hermes cron metadata/output
  -> CronMirror
  -> cron_job_run event
```

Purpose:

- execution proof
- status/error/silent/delivery-error visibility
- not semantic memory by itself

### SessionMirror / SourceMirror

Generic module position:

```text
state.db sessions/messages
  -> SessionMirror
  -> session_observed or conversation_turn_mirrored event

session_*.json fallback
  -> SessionMirror
  -> session_observed or conversation_turn_mirrored event
```

Required behavior:

- state.db is the primary source when available
- session JSON is fallback or corroboration
- support CLI, Telegram, WeCom, Weixin, mailbox, cron, and future gateway
  platforms
- detect provider-captured sessions and skip duplicate mirror writes
- for sessions not captured by provider, create bounded summary events similar
  to the old Sannai recent-events bridge
- preserve source refs, platform, session id, message count, tool count, and
  hashes

The bounded summary policy is important. Metadata-only events do not provide
the old "会话记忆" behavior. Full raw bodies are too broad. The correct default
is:

```text
body_policy=bounded_summary
store a clipped summary of the last relevant user/assistant exchange
hash raw content for dedup/provenance
do not store full transcript bodies
```

### StateSourceMirror

Generic module position:

```text
allowlisted state source
  -> StateSourceMirror
  -> state_source_changed / journal_card_observed / candidate_surface_changed event
```

Required behavior:

- allowlist source classes; do not broad-scan profile roots
- support journals, digests, proposals, reports, candidate JSONL, treasure
  index, family-room summaries, and similar structured state writers
- exclude identity bodies by default
- for identity-like files, support checksum/manifest only unless explicitly
  approved
- keep candidate-like files as candidate/evidence surfaces only

## Missing Items Found By This Audit

### Gap 1: state.db must be first-class

Earlier SourceMirror wording mentioned session files but not `state.db`. This
would be incomplete. The current design must say:

```text
state.db sessions/messages first
session_*.json fallback
```

### Gap 2: bounded session summaries are required

If SessionMirror writes only metadata, it will not reproduce the old Sannai
continuity behavior. It needs bounded summaries for uncovered sessions.

### Gap 3: CronMirror is not enough

Cron output tells us that a job ran. It does not preserve what the cron agent
experienced or said. Agent cron memory comes from sessions, not output files.

### Gap 4: StateSourceMirror needs source classes, not paths only

The old system has different semantics for journals, digests, candidates,
identity snapshots, relationship snapshots, and diary tails. The generic module
should use source classes with policies, not just a path allowlist.

### Gap 5: memory tool mutation provenance is partial

`on_memory_write()` currently mirrors `add` only. This is acceptable for v0
provider compatibility, but full provenance may need hash-only events for
`replace` and `remove`.

## Non-Breaking Placement

The mirrors must sit at the entry/source boundary:

```text
external Hermes source
  -> mirror scanner
  -> Memory-OS event stream
```

They must not sit inside:

- Memory-OS prefetch
- inner-drive working-memory writer
- crystallized approval writer
- Hindsight adapter
- speak gate

This placement preserves the already-developed Memory-OS behavior:

- provider remains canonical foreground capture
- event stream remains the common source of truth
- heartbeat remains the only automatic working/candidate advancement
- crystallized records still require owner approval
- Hindsight remains optional adapter only
- delivery remains disabled unless explicitly enabled

## Updated Runtime Hardening Requirement

Runtime Hardening should include the full Entry/Source Mirror set:

```text
RH-05 CronMirror
RH-09 SessionMirror / SourceMirror
RH-10 StateSourceMirror
```

This is not an expansion into Sannai-private modularization. It is a generic
coverage feature that Sannai can later use during migration.

## Acceptance Requirements

Entry/Source Mirror work is acceptable only if:

- blank hosts with no cron/session/state sources report `ok`
- populated hosts mirror without mutating source files
- provider-captured sessions are not duplicated
- uncovered sessions become bounded-summary events
- state sources are allowlisted and classed
- identity bodies are not mirrored by default
- CW-019-like candidate files remain candidate/evidence only
- mirror events enter normal heartbeat/index/prefetch paths without special
  side effects
- status and doctor never print private bodies
