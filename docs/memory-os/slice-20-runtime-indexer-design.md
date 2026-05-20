# Slice 20 Runtime SQLite/FTS Indexer Design

Date: 2026-05-20

Review input: MOS-SLICE20-001

## Purpose

Slice 20 turns the existing rebuildable SQLite index into a runtime-maintained
derived index. The canonical source remains the profile-local filesystem under
`$HERMES_HOME/memory-os/`. SQLite is only a query accelerator and diagnostic
surface. Deleting `memory-os/index/memory_os.db` must never delete memory.

This slice follows Slice 19:

```text
provider sync_turn
  -> event JSONL
  -> runtime heartbeat
  -> working memory and crystallized candidate queue
  -> runtime SQLite/FTS incremental index
  -> status, doctor, prefetch acceleration
```

## Current State Before Slice 20

The repo already has:

- `plugins/memory/memory_os/index.py`: full SQLite rebuild from filesystem
  store.
- `plugins/memory/memory_os/runtime.py`: heartbeat that advances unprocessed
  events into working memory and crystallized candidates.
- `plugins/memory/memory_os/prefetch.py`: bounded file-backed context assembly.
- `plugins/memory/memory_os/cli.py`: `status`, `doctor`, `benchmark`, `cleanup`,
  `heartbeat`, and migration diagnostics.

The missing production shape is:

- heartbeat-triggered incremental indexing;
- doctor-grade stale vs mismatch detection;
- FTS-backed prefetch with an explicit degraded fallback;
- rebuild concurrency behavior;
- WAL checkpoint policy.

## Non-Negotiable Principles

1. Filesystem records are canonical.
2. SQLite can be deleted and rebuilt.
3. Indexing is per profile, not global.
4. Prefetch must keep working without SQLite, but that mode is degraded.
5. Owner-approved crystallized records stay separate from candidates.
6. The indexer must never write identity source bodies.
7. Hindsight remains an optional adapter, not the canonical index.

## Scope

In scope:

- Incremental indexing for events, working items, crystallized candidates,
  crystallized records, and audit metadata.
- FTS5 keyword search for events, working items, and approved crystallized
  bodies.
- Full rebuild into a staging DB followed by atomic replacement.
- Index health diagnostics and doctor findings.
- Runtime integration through `hermes memory_os heartbeat`.
- Small tests plus opt-in 100k benchmark.

Out of scope:

- Vector embeddings generation.
- Graph relationship inference.
- Automatic approval of crystallized memory.
- Cross-profile indexing.
- Production migration on `10.20.2.88`.

## P0 Decisions

### 1. Heartbeat Interruption Idempotency

Slice 20 uses both transaction consistency and record-level idempotency.

For each source batch:

```sql
BEGIN IMMEDIATE;
-- insert or update derived rows
-- update index_source_state high-water mark
COMMIT;
```

Rules:

- `events.id`, `working_items.id`, `crystallized_records.id`, and
  `audit_entries.id` remain unique keys.
- Each indexed row stores `source_path`, `source_offset`, and `record_hash`.
- Replaying the same source span is safe. If the same record id and same
  `record_hash` already exists, the indexer skips or no-ops it.
- If the same record id appears with a different `record_hash`, doctor reports
  `index_content_mismatch` and the next safe action is full rebuild.
- High-water marks are updated in the same transaction as indexed rows.
- Crash before commit means no rows and no high-water mark are advanced.
- Crash after commit means both rows and high-water marks are advanced.

Acceptance:

- Simulated crash before commit causes the next heartbeat to index the same
  span once.
- Simulated replay after commit does not duplicate rows.
- Same id with different content hash becomes a mismatch, not a silent update.

### 2. Index Mismatch Detection

Doctor reports three index states:

```text
healthy   - index matches the filesystem snapshot at its high-water marks
stale     - filesystem has newer canonical records the index has not caught up to
mismatch  - indexed data conflicts with canonical records and requires rebuild
```

Detection algorithm:

1. Build a filesystem manifest for each canonical source file:
   `path`, `size`, `mtime_ns`, `line_count`, `first_record_id`,
   `last_record_id`, and hashes for the five most recent records.
2. Read `index_source_state` from SQLite:
   `source_path`, `source_size`, `source_mtime_ns`, `indexed_offset`,
   `indexed_line_count`, `first_record_id`, `last_record_id`, and recent
   hashes.
3. Classify:

| Condition | Finding | Severity |
| --- | --- | --- |
| DB missing | `index_missing` | warning |
| Filesystem has records beyond `indexed_offset` | `index_stale` | warning |
| Indexed count is lower than filesystem count only because of newer appended records | `index_stale` | warning |
| Indexed count is greater than filesystem count | `index_count_mismatch` | error |
| SQLite references a missing source file | `index_orphan_source` | error |
| Last indexed record id conflicts with source snapshot at that offset | `index_tail_mismatch` | error |
| Any fixed recent sample hash differs | `index_content_mismatch` | error |

Append races are treated as stale, not mismatch. Mismatch is only emitted when
the index contradicts canonical content that was already within its own
committed high-water mark.

Acceptance:

- A newly appended event after the last heartbeat is `index_stale`, not error.
- Manual SQLite row corruption is `index_content_mismatch`.
- Deleting the DB is `index_missing` warning and triggers rebuild availability.

### 3. Crystallized Markdown Indexing

Crystallized records are Markdown files with repeated frontmatter/body records.

Parser contract:

```text
---
schema_version: memory-os.crystallized.v0
id: cry_...
kind: moment
created_at: ...
approved_by: owner
approved_at: ...
source_event_ids:
  - evt_...
tags:
  - ...
sensitivity: private
hindsight_indexed: false
---
Agent-rewritten approved body.
```

Rules:

- Each frontmatter fence opens one record.
- The body is the text after the closing fence until the next opening fence or
  EOF.
- Required indexed fields:
  `id`, `schema_version`, `kind`, `created_at`, `approved_by`, `approved_at`,
  `source_event_ids`, `tags`, `sensitivity`, `hindsight_indexed`,
  `file_name`, `record_ordinal`, `body_hash`, `body_snippet`.
- FTS includes: `kind`, `tags`, `file_name`, `source_event_ids`, and the
  approved Markdown body.
- Attachments or image paths mentioned in Markdown are indexed as plain text
  references only. Slice 20 does not dereference or hash external attachments.
- A changed Markdown `mtime_ns` or `size` invalidates all indexed records for
  that file and reparses the whole file in one transaction.
- Schema versions other than `memory-os.crystallized.v0` are skipped into
  quarantine diagnostics and do not block event indexing.

Acceptance:

- Multiple records in one Markdown file index as separate rows.
- Editing an approved Markdown body changes `body_hash` and refreshes FTS.
- Candidate queue entries are indexed separately from approved Markdown records.

## P1 Runtime Policies

### 4. Rebuild Concurrency

Full rebuild never writes directly into the live DB.

Process:

```text
memory_os.db                  # live DB used by readers
memory_os.rebuild.<pid>.db    # staging DB
memory_os.db.broken.<ts>      # quarantined DB when corruption is detected
```

Rules:

- Rebuild opens a snapshot of filesystem inputs at rebuild start.
- Rebuild writes the complete index into a staging DB.
- Prefetch and status continue reading the old live DB during rebuild.
- `sync_turn` and heartbeat continue writing canonical files.
- After the staging DB passes count and sample checks, `os.replace()` swaps it
  over the live DB.
- Events appended after the rebuild snapshot are not lost; the next incremental
  heartbeat sees them as stale tail records and indexes them.
- If no live DB exists during rebuild, prefetch uses degraded filesystem mode
  with a smaller result set.

Acceptance:

- Concurrent prefetch during rebuild returns either old indexed results or
  degraded filesystem results, never an exception.
- A new event written during rebuild appears after the next heartbeat.

### 5. Chinese FTS5 Tokenizer Decision

Slice 20 v0 uses FTS5 `trigram` when available.

Reason:

- `unicode61` is reliable but weak for Chinese phrase search.
- External jieba tokenization is a later quality upgrade and would add a runtime
  dependency.
- ICU tokenizer availability is not guaranteed on blank Hermes hosts.
- `trigram` gives acceptable mixed Chinese/English substring matching without
  introducing a new service.

Startup behavior:

1. Probe `CREATE VIRTUAL TABLE ... USING fts5(content, tokenize='trigram')`.
2. If supported, set `fts_tokenizer=trigram`.
3. If unsupported, fall back to `unicode61` and mark doctor finding
   `fts_tokenizer_degraded`.

Acceptance:

- Chinese query strings can match Chinese event summaries in the default
  validation environment.
- Doctor reports the active tokenizer.
- If trigram is unavailable, Memory-OS keeps running and reports degraded search
  quality.

### 6. Audit Index Strategy

Audit is append-only metadata, not a recall hot path.

Rules:

- Audit rows are stored in `audit_entries` with metadata columns:
  `id`, `ts`, `action`, `status`, `target`, `details_hash`, `source_path`,
  `source_offset`.
- Raw `details_json` may be stored for diagnostics but is not included in FTS.
- Heartbeat indexes audit after events, working, candidates, and crystallized
  records.
- A heartbeat may cap audit indexing with `audit_max_lines_per_heartbeat`; any
  remainder is `index_stale` warning, not a hard failure.
- Full rebuild indexes audit metadata after the main memory tables. If audit
  indexing fails, the main memory index can still be usable with a warning.

Acceptance:

- Large audit files do not block event/working/crystallized indexing.
- Doctor distinguishes `audit_index_stale` from main index corruption.

### 7. WAL Checkpoint Fallback

SQLite uses WAL when available.

Policy:

- After each successful heartbeat index transaction, run
  `PRAGMA wal_checkpoint(PASSIVE)`.
- Track `checkpoint_busy_count` in `index_runtime_state`.
- If `checkpoint_busy_count >= 3`, run `PRAGMA wal_checkpoint(FULL)`.
- If WAL file size exceeds `wal_truncate_threshold_mb` (default `100`), run
  `PRAGMA wal_checkpoint(TRUNCATE)`.
- If checkpointing fails, index writes still count as successful but doctor
  reports `wal_checkpoint_degraded`.

Acceptance:

- Repeated busy passive checkpoints escalate to FULL.
- Oversized WAL escalates to TRUNCATE.
- Checkpoint failure does not corrupt or delete canonical files.

### 8. Vector And Graph Extension Space

Slice 20 does not implement vectors or graph recall, but v0 schema keeps a
non-blocking extension path.

Reserved tables:

```sql
CREATE TABLE IF NOT EXISTS memory_embeddings (
  record_type TEXT NOT NULL,
  record_id TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding BLOB NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (record_type, record_id, embedding_model)
);

CREATE TABLE IF NOT EXISTS memory_edges (
  edge_id TEXT PRIMARY KEY,
  from_record_type TEXT NOT NULL,
  from_record_id TEXT NOT NULL,
  to_record_type TEXT NOT NULL,
  to_record_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  weight REAL NOT NULL,
  created_at TEXT NOT NULL,
  source_event_id TEXT
);
```

Rules:

- Slice 20 creates these tables but writes no embeddings or inferred graph
  edges.
- Future vector/graph work must be additive and derived from canonical files.
- No future vector/graph table may become canonical memory.

## P2 Implementation Constraints

### 9. Multi-Profile Isolation

The indexer is a per-profile singleton over one `MemoryOSRoots` instance.

```text
/root/.hermes/memory-os/index/memory_os.db              # main profile
/root/.hermes/profiles/sannai/memory-os/index/...       # sannai profile
```

Rules:

- No cross-profile DB.
- No cross-profile rebuild.
- No shared lock file across profiles.
- Cross-profile views, if present, are canonical files in the producing or
  consuming profile and are indexed only inside that profile.

Acceptance:

- Rebuilding one profile does not touch another profile's `memory-os/index`.

### 10. Schema Migration Policy

SQLite schema version is derived, so rebuild is the default migration.

Rules:

- Store `index_schema_version` in `PRAGMA user_version` and in
  `index_metadata`.
- Compatible additive changes may use in-place `ALTER TABLE`.
- Any change to FTS tokenizer, row identity, source state semantics, or hash
  algorithm requires full rebuild.
- If migration fails, quarantine the old DB and rebuild from filesystem.
- Canonical file schema migration is a separate process and is not performed by
  the indexer.

Acceptance:

- A version mismatch triggers either deterministic in-place migration or full
  rebuild.
- Failed migration leaves canonical files untouched.

### 11. Test Matrix

Required Slice 20 tests:

| Test | Expected behavior |
| --- | --- |
| Incremental event indexing | N new events become N indexed rows after heartbeat. |
| Incremental idempotency | Replaying the same source span creates no duplicate rows. |
| Crash before commit | Next heartbeat completes indexing without duplicates. |
| Crash after row write before HWM | Transaction rollback or idempotent replay prevents duplicates. |
| Full rebuild equivalence | Rebuilt DB returns the same counts and search hits as incremental DB. |
| Mismatch detection | Manual row corruption produces `index_content_mismatch`. |
| Stale detection | Appended canonical event produces `index_stale`, not error. |
| Crystallized parsing | Markdown frontmatter/body records index into rows and FTS. |
| Candidate queue indexing | `candidates.jsonl` is indexed separately from approved records. |
| Concurrent read during rebuild | Prefetch does not fail while staging DB rebuilds. |
| Chinese FTS | Chinese phrase/substrings match in trigram mode. |
| WAL checkpoint escalation | Busy passive checkpoints escalate under configured threshold. |
| Per-profile isolation | Rebuild for profile A does not touch profile B. |
| 100k benchmark | Opt-in benchmark records rebuild and query timings. |

### 12. Prefetch Fallback And Degraded Mode

Filesystem fallback is allowed, but it is not treated as normal performance.

Rules:

- Normal mode: prefetch uses SQLite/FTS and falls back to canonical file snippets
  only for missing sections.
- Degraded mode: if SQLite is missing, corrupt, locked, or rebuilding with no
  old DB, prefetch reads bounded recent filesystem records only.
- Degraded mode must:
  - use a smaller result cap;
  - set `prefetch_mode=degraded_filesystem`;
  - add doctor finding `prefetch_degraded`;
  - trigger or recommend background rebuild.
- Degraded mode is not expected to meet normal p95 latency SLO on 100k events.

Acceptance:

- Prefetch still returns safe bounded context when DB is missing.
- Status/doctor clearly show degraded mode.
- Benchmark reports indexed prefetch and degraded prefetch separately.

## Proposed Tables

Core tables:

```text
index_metadata
index_runtime_state
index_source_state
events
events_fts
working_items
working_items_fts
crystallized_candidates
crystallized_records
crystallized_records_fts
audit_entries
memory_embeddings
memory_edges
```

Minimum `index_source_state` fields:

```text
source_path
source_kind
source_size
source_mtime_ns
indexed_offset
indexed_line_count
first_record_id
last_record_id
recent_hashes_json
last_indexed_at
```

## Implementation Order

1. Add failing tests for incremental event indexing and idempotent replay.
2. Add `index_source_state`, row hashes, and transactional incremental indexing.
3. Add `index health` classification and doctor findings.
4. Add crystallized Markdown body parser and candidate queue indexing.
5. Add FTS tables with tokenizer probe.
6. Wire heartbeat to run incremental index after working/candidate updates.
7. Add full rebuild staging and atomic replace.
8. Add prefetch indexed path with degraded filesystem fallback.
9. Add WAL checkpoint policy.
10. Add per-profile, migration, and benchmark coverage.

## Slice 20 Acceptance

- `hermes memory_os heartbeat` indexes newly written events into SQLite.
- Running heartbeat twice is idempotent.
- Deleting `memory-os/index/memory_os.db` does not lose memory and can be
  recovered by rebuild.
- Doctor distinguishes missing, stale, and mismatch.
- Prefetch uses SQLite/FTS when healthy and reports degraded mode when not.
- Chinese search is trigram-backed when supported and explicitly degraded when
  not.
- Crystallized approved Markdown records are parsed into rows and FTS; candidate
  queue remains separate.
- Rebuild does not block live reads when an old DB exists.
- WAL is bounded by checkpoint policy.
- 100k opt-in benchmark records rebuild, indexed prefetch, and degraded prefetch
  timings.
- No production host, production gateway, production Hindsight bank, or identity
  source file is modified.

## References

- Chroma WAL pruning:
  <https://cookbook.chromadb.dev/core/advanced/wal-pruning/>
- Chroma WAL architecture:
  <https://www.trychroma.com/engineering/wal3>
- SQLite FTS5:
  <https://www.sqlite.org/fts5.html>
- SQLite WAL:
  <https://www.sqlite.org/wal.html>
- Letta archival memory:
  <https://docs.letta.com/guides/ade/archival-memory>
