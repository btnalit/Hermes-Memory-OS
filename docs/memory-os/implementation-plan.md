# Hermes Memory-OS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `memory-os` Hermes memory provider prototype that can run on `10.20.3.200`, validate against an empty profile and Sannai shadow data, and stay rollback-safe for later production integration.

**Architecture:** Implement `memory-os` as a standard Hermes memory provider under `plugins/memory/memory_os/`. The provider owns a profile-local `$HERMES_HOME/memory-os/` canonical store, a rebuildable SQLite index, bounded prefetch, working/crystallized memory files, shadow import, migrator tooling, and a disabled-by-default Hindsight adapter.

**Tech Stack:** Python, Hermes `MemoryProvider` ABC, JSONL, Markdown frontmatter, SQLite, pytest, Hermes CLI plugin registration, `10.20.3.200` isolated validation.

---

## Preconditions

- Do not modify `10.20.2.88` production during this plan.
- Do not restart production gateways during this plan.
- Do not enable Sannai S5, write active `lingering_thoughts.json`, or write long-term memory from CW-019 data.
- Work against the standalone Memory-OS repo: `D:\Hermes agent manager\Hermes-Memory-OS\`.
- Keep docs under `D:\Hermes agent manager\Hermes-Memory-OS\docs\memory-os\`.
- If implementation happens in a git worktree later, run `git status --short --branch` before edits.

## Source Files To Create

Target source root:

```text
D:\Hermes agent manager\Hermes-Memory-OS\
```

Provider files:

```text
plugins/memory/memory_os/
├── __init__.py              # MemoryProvider lifecycle, tool routing, prompt block
├── plugin.yaml              # Provider metadata for discovery/status display
├── cli.py                   # memory-os CLI commands
├── config.py                # config defaults and validation
├── ids.py                   # stable IDs for events, working items, crystallized records
├── fixtures.py              # deterministic synthetic records shared by tests and benchmarks
├── roots.py                 # profile-local and multi-root resolver
├── schema.py                # dataclasses / validation / version registry
├── store.py                 # filesystem canonical store and atomic writes
├── index.py                 # SQLite index and rebuild logic
├── prefetch.py              # bounded retrieval and formatting
├── working.py               # lingering/emotional/curiosity/attention operations
├── crystallized.py          # owner-approved markdown records
├── approval.py              # approval states and CW-019 bridge states
├── migrator.py              # shadow import, dry-run migration, compatibility reports
├── audit.py                 # write audit and meta-audit ledger
├── benchmark.py             # synthetic benchmark helpers
├── cleanup.py               # quarantine/retention cleanup, dry-run first
├── inner_drive.py           # minimal event -> working/candidate engine surface for E2E validation
└── adapters/
    ├── __init__.py
    └── hindsight.py         # disabled-by-default semantic export smoke
```

Test files:

```text
tests/plugins/memory/test_memory_os_schema.py
tests/plugins/memory/test_memory_os_fixtures.py
tests/plugins/memory/test_memory_os_roots.py
tests/plugins/memory/test_memory_os_store.py
tests/plugins/memory/test_memory_os_lifecycle.py
tests/plugins/memory/test_memory_os_prefetch.py
tests/plugins/memory/test_memory_os_working.py
tests/plugins/memory/test_memory_os_crystallized.py
tests/plugins/memory/test_memory_os_migrator.py
tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py
tests/plugins/memory/test_memory_os_hindsight_adapter.py
tests/plugins/memory/test_memory_os_e2e.py
tests/scripts/test_memory_os_export_shadow.py
```

Docs/runbooks:

```text
docs/memory-os/test-plan-10.20.3.200.md
docs/memory-os/migration-notes.md
docs/memory-os/gateway-restart-runbook.md
docs/memory-os/slice-20-runtime-indexer-design.md
```

## Implementation Slices

### Slice 0: Scaffold And Discovery

**Purpose:** Create a minimal provider that Hermes can discover without touching storage.

**Files:**

- Create: `plugins/memory/memory_os/__init__.py`
- Create: `plugins/memory/memory_os/plugin.yaml`
- Create: `tests/plugins/memory/test_memory_os_lifecycle.py`

**Steps:**

- [x] Add `MemoryOSProvider(MemoryProvider)` with `name == "memory-os"`, `is_available() == True`, empty tool list, empty `prefetch`, no-op `sync_turn`, and `shutdown`.
- [x] Add `plugin.yaml` with provider description and no external dependency.
- [x] Add a discovery test that calls `plugins.memory.load_memory_provider("memory_os")` or the actual discovery name accepted by Hermes.
- [x] Run:

```powershell
cd "D:\Hermes agent manager\Hermes-Memory-OS"
python -m pytest tests/plugins/memory/test_memory_os_lifecycle.py -q
```

**Acceptance:**

- Provider loads through Hermes memory discovery.
- `is_available()` performs no network or filesystem writes.
- Test passes without requiring `HERMES_HOME` to exist.

### Slice 1: Schema

**Purpose:** Define stable v0 records before any store writes.

**Files:**

- Create: `plugins/memory/memory_os/schema.py`
- Create: `plugins/memory/memory_os/ids.py`
- Test: `tests/plugins/memory/test_memory_os_schema.py`

**Scope:**

- `EventEnvelope`
- `WorkingDocument`
- `WorkingItem`
- `CrystallizedFrontmatter`
- `IdentityManifest`
- `CrossProfileView`
- `SchemaRegistry`
- `ValidationError`

**Steps:**

- [x] Write failing tests for valid event, invalid missing fields, unknown schema version, and JSON round-trip.
- [x] Implement dataclasses or typed dict validation with explicit `schema_version` constants:

```text
memory-os.event.v0
memory-os.working.v0
memory-os.crystallized.v0
memory-os.identity_manifest.v0
memory-os.cross_profile_view.v0
```

- [x] Add ID helpers for `evt_`, `wrk_`, `cry_`, `audit_`, `view_`.
- [x] Add registry helpers: `current_write_version(kind)` and `can_read(kind, version)`.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_schema.py -q
```

**Acceptance:**

- Invalid records fail closed with actionable error messages.
- Old/unknown schema versions are rejected unless explicitly listed as read-compatible.
- ID helpers create sortable, prefix-scoped IDs.
- No filesystem writes occur in schema tests.

### Slice 1.5: Synthetic Fixtures

**Purpose:** Create deterministic Memory-OS fixture builders before index, prefetch, working-memory, benchmark, and E2E tests start duplicating data setup.

**Files:**

- Create: `plugins/memory/memory_os/fixtures.py`
- Test: `tests/plugins/memory/test_memory_os_fixtures.py`

**Scope:**

- deterministic event factory
- deterministic working item factory
- deterministic crystallized frontmatter factory
- Sannai-like multi-root fixture layout builder
- synthetic corpus generator for 1k/10k/100k event benchmark runs

**Steps:**

- [x] Write tests that two fixture runs with the same seed produce identical IDs, timestamps, and summaries.
- [x] Write tests that different seeds produce different IDs while preserving valid schema.
- [x] Write tests that the Sannai-like fixture creates profile files and state files under separate roots.
- [x] Implement fixture builders that return schema objects or plain dicts accepted by `schema.py`.
- [x] Implement `generate_event_corpus(count, seed, profile)` as a generator so large benchmarks do not need to hold every record in memory.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_fixtures.py tests/plugins/memory/test_memory_os_schema.py -q
```

**Acceptance:**

- Fixture output is deterministic across processes for the same seed.
- Generated records pass `schema.py` validation.
- Sannai fixture mirrors the multi-root shape without copying production data.
- Slice 4, Slice 6, Slice 7, Slice 11, and Slice 16 tests reuse this module instead of creating separate ad hoc test data.

### Slice 2: P1 Multi-Root Resolver

**Purpose:** Resolve the current profile's Memory-OS root while acknowledging existing Hermes/Sannai multi-root reality.

**Files:**

- Create: `plugins/memory/memory_os/roots.py`
- Test: `tests/plugins/memory/test_memory_os_roots.py`

**Rules:**

- Canonical Memory-OS root is always `$HERMES_HOME/memory-os/`.
- Existing identity/state sources can live outside that root and are referenced by manifest.
- Sannai production shape is expected:

```text
HERMES_HOME=/root/.hermes/profiles/sannai
state root=/vol1/.hermes/state/sannai
```

**Steps:**

- [x] Implement `MemoryOSRoots.from_hermes_home(hermes_home, profile=None, external_state_roots=None)`.
- [x] Resolve these paths:
  - `memory_os_root`
  - `events_root`
  - `working_root`
  - `crystallized_root`
  - `identity_manifest_path`
  - `relationships_root`
  - `index_path`
  - `audit_path`
  - `imports_root`
  - `quarantine_root`
- [x] Implement `IdentitySource` entries for external `SOUL.md`, `MEMORY.md`, `USER.md`, and state files.
- [x] Add tests for temporary profile, main profile, Sannai multi-root fixture, and path traversal rejection.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_roots.py -q
```

**Acceptance:**

- No code assumes `/vol1/.hermes/memory/{profile}` as canonical store.
- All Memory-OS writes stay under `$HERMES_HOME/memory-os/`.
- External identity/state files are read references only.
- `..`, absolute override, and cross-profile write roots are rejected.

### Slice 3: Store And Atomic Writes

**Purpose:** Implement canonical filesystem store and append-only audit-safe writes.

**Files:**

- Create: `plugins/memory/memory_os/store.py`
- Create: `plugins/memory/memory_os/audit.py`
- Test: `tests/plugins/memory/test_memory_os_store.py`

**Scope:**

- Directory initialization.
- Atomic JSON writes via temp file + replace.
- Event JSONL append.
- Working JSON write/read.
- Crystallized markdown append/read.
- Audit JSONL append.
- Quarantine malformed input.

**Steps:**

- [x] Write tests that initialize a temp `$HERMES_HOME` and assert the expected directory tree.
- [x] Write tests for event append path `events/YYYY-MM/YYYY-MM-DD.jsonl`.
- [x] Write tests for malformed JSONL quarantine during read.
- [x] Implement store functions without SQLite dependency.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_store.py -q
```

**Acceptance:**

- Store creates only `$HERMES_HOME/memory-os/**`.
- Event append is append-only and preserves existing lines.
- Atomic JSON write never leaves partial target files on failure.
- Malformed lines are recorded in audit/quarantine and do not crash full reads.

### Slice 4: SQLite Index

**Purpose:** Add a rebuildable index for search/status without making SQLite the true source.

**Files:**

- Create: `plugins/memory/memory_os/index.py`
- Test: extend `tests/plugins/memory/test_memory_os_store.py`

**Scope:**

- `events`
- `working_items`
- `crystallized_records`
- `audit_entries`
- optional FTS table for summaries/text.

**Steps:**

- [x] Write tests that index records from filesystem and then delete/rebuild `memory_os.db`.
- [x] Implement schema creation with WAL fallback if the project helper is available.
- [x] Implement `rebuild_from_store(store)`.
- [x] Implement count/status query helpers.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_store.py -q
```

**Acceptance:**

- Deleting SQLite does not lose memory records.
- Rebuild count matches filesystem records.
- Locked or missing DB degrades to store-only writes and emits audit status.

### Slice 5: Provider Lifecycle

**Purpose:** Wire store/index into Hermes `MemoryProvider` lifecycle.

**Files:**

- Modify: `plugins/memory/memory_os/__init__.py`
- Create: `plugins/memory/memory_os/config.py`
- Test: `tests/plugins/memory/test_memory_os_lifecycle.py`

**Scope:**

- `initialize(session_id, hermes_home=...)`
- `system_prompt_block()`
- `get_config_schema()`
- `save_config(values, hermes_home)`
- `sync_turn(...)`
- `on_session_end(...)`
- `on_pre_compress(...)`
- `on_memory_write(...)`
- `shutdown()`

**Steps:**

- [x] Test initialization uses `hermes_home` argument rather than global home.
- [x] Test `sync_turn()` enqueues summary-only event and returns quickly.
- [x] Test bounded queue full behavior: `sync_turn()` does not block, drops the new item, and writes a best-effort `sync_turn_dropped` audit record.
- [x] Test worker exception behavior: the worker catches the exception, writes `worker_error` audit, and continues processing later queued items.
- [x] Test restart limitation explicitly: v0 does not recover unflushed in-memory queue items after unclean process death; clean `shutdown()` must flush best effort.
- [x] Test shutdown flushes worker queue and closes index.
- [x] Implement a single background worker with bounded queue.
- [x] Add config defaults:

```text
capture_policy=summary_only
prefetch_char_budget=2200
hindsight_adapter_enabled=false
allow_full_local_capture=false
```

- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_lifecycle.py tests/run_agent/test_memory_provider_init.py -q
```

**Acceptance:**

- `initialize()` creates store only under the provided `hermes_home`.
- `sync_turn()` foreground overhead target is p95 < 20ms in unit benchmark.
- Queue full behavior is explicit: v0 drops the newest sync item instead of blocking the foreground path, and writes a best-effort audit record.
- Worker failures are contained: an exception in one item does not stop the worker loop, and the failure is auditable.
- Unclean process death can lose in-memory queued items in v0; durable queue/spool recovery is explicitly deferred to a later slice/version.
- Full transcript capture is disabled by default.
- `on_memory_write()` mirrors allowed writes as events only; it does not edit built-in memory files.

### Slice 6: Prefetch

**Purpose:** Provide bounded, layer-prioritized memory context.

**Files:**

- Create: `plugins/memory/memory_os/prefetch.py`
- Modify: `plugins/memory/memory_os/__init__.py`
- Test: `tests/plugins/memory/test_memory_os_prefetch.py`

**Priority order:**

```text
identity manifest summary
working summary
relationship summary
recent approved crystallized
recent event summaries
```

**Steps:**

- [x] Write tests for budget truncation, layer ordering, secret/private body exclusion, and empty store.
- [x] Implement `build_prefetch(query, budget_chars, store, index)`.
- [x] Format output with a stable header:

```text
## Memory-OS Context
```

- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_prefetch.py -q
```

**Acceptance:**

- Prefetch never prints raw transcripts by default.
- Output stays within configured budget.
- Relationship/working/crystallized order is deterministic.
- Empty store returns `""`.

### Slice 7: Working Memory

**Purpose:** Implement working memory operations for lingering, emotional, curiosity, and attention.

**Files:**

- Create: `plugins/memory/memory_os/working.py`
- Test: `tests/plugins/memory/test_memory_os_working.py`

**Steps:**

- [x] Add tests for adding active items, deterministic decay with fake clock, expiry, and status summary.
- [x] Implement `WorkingMemoryService`.
- [x] Keep scoring language limited to salience: `weight`, `decay`, `status`.
- [x] Add `trace_working_item(id)` support for future CLI.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_working.py -q
```

**Acceptance:**

- `weight` never becomes ops/proposal scoring.
- Expired items remain traceable through audit.
- Engine-facing APIs do not send messages and do not write crystallized memory.

### Slice 8: Crystallized Memory And Approval

**Purpose:** Implement owner-approved long-term memory records.

**Files:**

- Create: `plugins/memory/memory_os/crystallized.py`
- Create: `plugins/memory/memory_os/approval.py`
- Test: `tests/plugins/memory/test_memory_os_crystallized.py`

**Steps:**

- [x] Test that unapproved candidates cannot write crystallized records.
- [x] Test approved records include source event IDs, approval metadata, sensitivity, and `hindsight_indexed=false`.
- [x] Test `owner_eligible` from CW-019 does not equal crystallized approval.
- [x] Implement markdown frontmatter read/write.
- [x] Implement approval purpose enum:

```text
approve_for_visibility
approve_for_working
approve_for_crystallized
reject
defer
```

- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py -q
```

**Acceptance:**

- Crystallized writes require explicit `approve_for_crystallized`.
- CW-019 bridge states are preserved and not upgraded automatically.
- Approved records are auditable back to source events.

### Slice 9: P1 Transition Compatibility

**Purpose:** Let Memory-OS read existing Hermes/Sannai file shapes without taking ownership of them.

**Files:**

- Create: `plugins/memory/memory_os/migrator.py`
- Extend: `plugins/memory/memory_os/roots.py`
- Create: `scripts/memory_os_export_shadow.py`
- Test: `tests/plugins/memory/test_memory_os_migrator.py`
- Test: `tests/scripts/test_memory_os_export_shadow.py`

**Compatibility targets:**

```text
SOUL.md
memories/MEMORY.md
memories/USER.md
diary.md
self_memory.md
lingering_thoughts.json
quiet_moments.jsonl
heartbeat_lingering_candidates.jsonl
digests/daily/
```

**Steps:**

- [x] Build fixtures that mirror Sannai's multi-root shape without copying production content.
- [x] Implement `scan_legacy_sources(roots)`.
- [x] Implement `scripts/memory_os_export_shadow.py` as a read-only bundle exporter for `10.20.2.88` or any local fixture root.
- [x] Add exporter options:
  - `--profile sannai`
  - `--hermes-home <path>`
  - `--state-root <path>`
  - `--out <path>`
  - `--include-private-bodies`
  - `--exclude-secrets` default true
  - `--dry-run`
- [x] Implement `import_shadow_bundle(..., dry_run=True)`.
- [x] Preserve source status for CW-019 candidates.
- [x] Emit `import_report.json`.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_migrator.py -q
```

**Acceptance:**

- Dry-run reports would-write paths and record counts without writing.
- Shadow export is read-only against source roots and never writes inside production `HERMES_HOME` or `/vol1/.hermes/state/sannai`.
- For owner-approved Sannai export, private Sannai memory/state bodies may be included with `--include-private-bodies`; API keys, `.env`, credentials, raw session databases, and unrelated secrets remain excluded.
- Import writes only into `$HERMES_HOME/memory-os/imports/**` and canonical Memory-OS store for the test profile.
- No legacy source file is modified.
- `owner_eligible` remains visibility-only.

### Slice 10: CLI, Meta-Audit, And Doctor

**Purpose:** Add operator diagnostics before any remote validation.

**Files:**

- Create: `plugins/memory/memory_os/cli.py`
- Extend: `plugins/memory/memory_os/audit.py`
- Test: `tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py`

**CLI commands:**

```text
hermes memory-os status
hermes memory-os doctor
hermes memory-os inspect <event_id>
hermes memory-os trace <working_id|candidate_id>
hermes memory-os diff --since <time> --until <time>
hermes memory-os approval-report
hermes memory-os export-shadow --dry-run
```

**Meta-audit scope:**

- schema drift
- root drift
- index drift
- missing identity source
- skipped private body count
- Hindsight adapter disabled/enabled proof
- queue backlog
- last write age

**Steps:**

- [x] Test status and doctor do not print private bodies.
- [x] Test inspect/trace require explicit include-private flag for body output.
- [x] Test meta-audit detects index count mismatch and missing identity source.
- [x] Implement CLI functions as thin wrappers over services.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py -q
```

**Acceptance:**

- `doctor` exits non-zero for hard failures and zero for warnings.
- Private text is excluded by default.
- Meta-audit can be attached to `10.20.3.200` validation evidence.

### Slice 11: Benchmark Harness

**Purpose:** Prove v0 performance targets before remote validation.

**Files:**

- Create: `plugins/memory/memory_os/benchmark.py`
- Test: `tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py`

**Benchmarks:**

```text
sync_turn enqueue p95
event append p95
prefetch warm/cold over synthetic 1k/10k/100k events
SQLite rebuild over synthetic events
working decay over synthetic items
status command latency
```

**Steps:**

- [x] Implement deterministic synthetic data generator.
- [x] Implement benchmark command with JSON output.
- [x] Add a small unit test that runs a tiny benchmark under 1k records.
- [x] Keep large 100k benchmark opt-in, not default CI.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py -q
```

**Acceptance:**

- Tiny benchmark is stable in unit tests.
- Large benchmark command can be run on `10.20.3.200`.
- Benchmark report includes pass/fail against SLO from `integration-with-current-hermes.md`.

### Slice 12: Cleanup And Retention

**Purpose:** Define cleanup as safe, dry-run-first maintenance rather than ad hoc deletion.

**Files:**

- Create: `plugins/memory/memory_os/cleanup.py`
- Extend: `plugins/memory/memory_os/cli.py`
- Test: `tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py`

**Cleanup targets:**

- old imports
- quarantine entries
- expired working items
- stale benchmark artifacts
- incomplete temp files

**Steps:**

- [x] Implement `cleanup_plan(store, now, policy)` returning actions without executing.
- [x] Implement `apply_cleanup(store, plan, require_confirmed_plan_id=True)`.
- [x] Test dry-run output and guarded apply.
- [x] Ensure cleanup never deletes identity sources or crystallized records.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py -q
```

**Acceptance:**

- Cleanup is dry-run by default.
- Apply requires a generated plan id.
- Cleanup writes audit records for every action.
- Crystallized and identity files are not cleanup targets.

### Slice 13: Hindsight Adapter Smoke

**Purpose:** Prove adapter boundary without making Hindsight canonical.

**Files:**

- Create: `plugins/memory/memory_os/adapters/hindsight.py`
- Test: `tests/plugins/memory/test_memory_os_hindsight_adapter.py`

**Steps:**

- [x] Test adapter disabled by default.
- [x] Test unapproved event and working draft are refused.
- [x] Test approved crystallized record can produce an export payload.
- [x] Mock Hindsight client; do not call network.
- [x] Mark exported record with `hindsight_indexed=true` only after success.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_hindsight_adapter.py -q
```

**Acceptance:**

- Adapter cannot export raw events, working memory, CW-019 pending candidates, or private bodies.
- Adapter failure leaves canonical store unchanged except audit.
- Hindsight remains optional and disabled unless explicitly configured.

### Slice 14: P1 Gateway Restart Strategy

**Purpose:** Create a production-safe restart and rollback plan before any live pilot.

**Files:**

- Create: `docs/memory-os/gateway-restart-runbook.md`
- Create: `docs/memory-os/test-plan-10.20.3.200.md`

**Steps:**

- [x] Document `10.20.3.200` restart commands separately from `10.20.2.88`.
- [x] Document production restart prechecks, but mark them blocked until explicit owner approval.
- [x] Include before/after checks:

```bash
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID --no-pager
systemctl --user show hermes-gateway-sannai.service -p ActiveState -p MainPID --no-pager
```

- [x] Include rollback provider values:
  - main: `memory.provider=hindsight`
  - Sannai: built-in only unless changed later
- [x] Include "never restart both gateways unless explicitly approved."
- [x] State explicitly that v0 writes a runbook only. Automated restart wrappers, restart hooks, or deployment orchestration are post-v0 work and must not be introduced in this slice.

**Acceptance:**

- Runbook distinguishes local test restart, `10.20.3.200` restart, and production restart.
- Production section is blocked by default.
- Main/Sannai restart scopes are explicit.
- No code path is added that can restart a gateway automatically.
- Any future automation must still require explicit owner approval and before/after PID evidence.

### Slice 15: Migrator Process

**Purpose:** Define and implement migration as staged, auditable dry-run first process.

**Files:**

- Extend: `plugins/memory/memory_os/migrator.py`
- Extend: `plugins/memory/memory_os/cli.py`
- Create: `docs/memory-os/migration-notes.md`
- Test: `tests/plugins/memory/test_memory_os_migrator.py`

**Migrator states:**

```text
scan_only
redacted_bundle
shadow_import
shadow_replay
diff_report
owner_review
approved_apply
rollback_ready
```

**Migrator commands:**

```text
hermes memory-os migrate scan --profile sannai --dry-run
hermes memory-os migrate export-shadow --redacted --out <path>
hermes memory-os migrate import-shadow --bundle <path> --profile sannai-shadow
hermes memory-os migrate replay --profile sannai-shadow --no-adapter-export
hermes memory-os migrate diff --source-report <path> --target-root <path>
```

**Steps:**

- [x] Implement scan-only metadata report.
- [x] Implement redacted bundle export.
- [x] Implement shadow import into test profile.
- [x] Implement replay with adapter disabled.
- [x] Implement diff report covering source count, imported count, skipped private bodies, schema errors, approval state mapping, and would-write paths.
- [x] Add tests that use fixture data and prove no source mutation.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_migrator.py -q
```

**Acceptance:**

- Migrator never mutates source during scan/export.
- Shadow import never marks crystallized approved.
- Replay never sends messages and never exports Hindsight.
- Diff report is sufficient for owner review before production pilot.

### Slice 16: End-to-End Integration Test

**Purpose:** Prove the Memory-OS components work together as a vertical flow after the individual slices are implemented.

**Files:**

- Create: `plugins/memory/memory_os/inner_drive.py`
- Test: `tests/plugins/memory/test_memory_os_e2e.py`

**Scenario:**

```text
sync_turn
  -> event JSONL append
  -> InnerDriveEngine processes event
  -> working memory update
  -> candidate generation
  -> owner approval
  -> crystallized markdown write
  -> optional Hindsight adapter export with mocked client
```

**Steps:**

- [x] Build an E2E fixture using `fixtures.py` and a temporary `$HERMES_HOME`.
- [x] Initialize `MemoryOSProvider` with adapter disabled.
- [x] Call `sync_turn()` and flush the worker.
- [x] Assert the event exists in filesystem store and index.
- [x] Run a minimal `InnerDriveEngine.process_event(event)` that creates a working item and a crystallized candidate. This engine surface is for Memory-OS validation only; autonomous scheduler behavior remains outside v0.
- [x] Apply `approve_for_crystallized` through the approval service.
- [x] Assert crystallized markdown is written with source event IDs and approval metadata.
- [x] Enable a mocked Hindsight adapter and export only the approved crystallized record.
- [x] Assert raw events, working items, and unapproved candidates are refused by the adapter.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_e2e.py -q
```

**Acceptance:**

- The full vertical path passes in a temp profile without gateway, cron, Telegram, mailbox, or production dependencies.
- Adapter export is mocked and disabled by default.
- The E2E test does not send messages, restart services, touch `10.20.2.88`, or read production Sannai data.
- The test proves component integration, not final Sannai personality quality; Sannai suitability still requires shadow replay.

### Slice 17: Plugin Install And Hermes Discovery

**Purpose:** Make Memory-OS installable as a Hermes user memory provider on a blank `$HERMES_HOME` without patching Hermes prompts or copying files by hand.

**Files:**

- Create: `scripts/install_memory_os_plugin.py`
- Modify: `plugins/memory/memory_os/plugin.yaml`
- Modify: `plugins/memory/memory_os/cli.py`
- Test: `tests/scripts/test_memory_os_plugin_install.py`
- Update: `README.md`

**Hermes discovery contract:**

```text
$HERMES_HOME/plugins/memory_os/
├── plugin.yaml
├── __init__.py              # exposes register_memory_provider()
├── cli.py                   # importable before provider package is preloaded
└── *.py                     # provider implementation
```

Hermes detects user-installed memory providers by scanning
`$HERMES_HOME/plugins/<name>/__init__.py` for `register_memory_provider` or
`MemoryProvider`. Activation remains Hermes-native:

```bash
HERMES_HOME=/path/to/home hermes config set memory.provider memory_os
HERMES_HOME=/path/to/home hermes memory
```

**Steps:**

- [x] Add an installer script that copies `plugins/memory/memory_os` into `$HERMES_HOME/plugins/memory_os`.
- [x] Exclude `__pycache__`, `.pyc`, and `.pyo` artifacts from installed plugin files.
- [x] Keep provider enablement explicit via `--enable`; no gateway restart is performed by the installer.
- [x] Align `plugin.yaml` name with the Hermes provider config key: `memory_os`.
- [x] Make `cli.py` importable as `_hermes_user_memory.memory_os.cli` before the provider package has been loaded.
- [x] Add tests for install shape, dry-run behavior, plugin name, and fresh-process CLI import.
- [x] Run:

```powershell
python -m pytest tests/scripts/test_memory_os_plugin_install.py -q
python -m pytest tests/plugins/memory/test_memory_os_lifecycle.py tests/scripts/test_memory_os_plugin_install.py -q
```

**Acceptance:**

- A blank Hermes profile discovers Memory-OS through `hermes memory` after installation.
- Discovery uses Hermes' native memory plugin mechanism, not a system prompt patch.
- The installer does not touch production, restart gateways, or create Memory-OS runtime data until the provider is enabled and used.
- Plugin CLI import does not depend on a prior `discover_memory_providers()` call in the same Python process.

### Slice 18: Provider Self-Diagnostic Tool

**Purpose:** Let a Hermes agent inspect the active Memory-OS provider through the memory plugin interface instead of guessing from stale built-in memory or Hindsight records.

**Files:**

- Modify: `plugins/memory/memory_os/__init__.py`
- Test: `tests/plugins/memory/test_memory_os_lifecycle.py`
- Update: `README.md`

**Tool:**

```text
memory_os_status
```

The tool is read-only and returns:

```json
{
  "provider": "memory_os",
  "provider_name": "memory-os",
  "status": "active",
  "canonical_store": "$HERMES_HOME/memory-os",
  "storage_model": "local_filesystem_jsonl_markdown",
  "event_count": 0,
  "hindsight_adapter_enabled": false,
  "hindsight_role": "optional_adapter_only_not_canonical",
  "uses_hindsight_http_api": false,
  "body_policy": "summary_only"
}
```

**Steps:**

- [x] Add `memory_os_status` to `get_tool_schemas()`.
- [x] Implement `handle_tool_call("memory_os_status", ...)`.
- [x] Return storage facts, counts, source/kind counters, index counts, and adapter state without raw private bodies.
- [x] Add a regression test proving the status tool reports local filesystem storage and does not mention Hindsight API URLs.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_lifecycle.py -q
python -m pytest -q
```

**Acceptance:**

- A Hermes agent can call `memory_os_status` when asked what memory backend is active.
- The tool reports `provider=memory_os`, `storage_model=local_filesystem_jsonl_markdown`, and `uses_hindsight_http_api=false`.
- The tool does not expose raw private bodies.
- The solution stays inside the memory provider plugin interface; it does not patch system prompts.

### Slice 19: Runtime Heartbeat Deployment

**Purpose:** Make a deployed Memory-OS profile complete enough for validation: provider writes events, heartbeat advances unprocessed events into working memory and crystallized candidate queue, and a user systemd timer can keep it running.

**Files:**

- Create: `plugins/memory/memory_os/runtime.py`
- Modify: `plugins/memory/memory_os/crystallized.py`
- Modify: `plugins/memory/memory_os/cli.py`
- Modify: `scripts/install_memory_os_plugin.py`
- Test: `tests/plugins/memory/test_memory_os_runtime.py`
- Extend: `tests/scripts/test_memory_os_plugin_install.py`

**Runtime flow:**

```text
event JSONL
  -> hermes memory_os heartbeat
  -> InnerDriveEngine.process_event(event)
  -> working/lingering.json
  -> crystallized/candidates.jsonl
  -> runtime/heartbeat_state.json
```

**Important boundary:** heartbeat creates candidates only. It does not write
approved crystallized records. `crystallized/*.md` still requires explicit
`approve_for_crystallized`.

**Steps:**

- [x] Add `MemoryOSRuntime.heartbeat(max_events=100)`.
- [x] Persist processed event IDs in `memory-os/runtime/heartbeat_state.json`.
- [x] Add `crystallized/candidates.jsonl` queue helpers.
- [x] Add `hermes memory_os heartbeat --max-events N`.
- [x] Extend `memory_os status` counts with `crystallized_candidates`.
- [x] Extend installer with `--install-runtime`, `--enable-runtime`, and `--runtime-interval`.
- [x] Generate heartbeat wrapper plus systemd user service/timer artifacts.
- [x] Add tests proving heartbeat is idempotent and moves new events to working + candidates.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_runtime.py tests/scripts/test_memory_os_plugin_install.py -q
python -m pytest -q
```

**Acceptance:**

- After provider writes events, heartbeat increases `working_items` and `crystallized_candidates`.
- Running heartbeat twice does not duplicate already processed events.
- The deployed validation host can enable an active `hermes-memory-os-heartbeat.timer`.
- `crystallized_records` stays `0` until owner approval is explicitly applied.

### Slice 20: Runtime SQLite/FTS Indexer

**Purpose:** Make the SQLite index a runtime-maintained derived index instead of
only a manual full-rebuild artifact. The filesystem remains canonical; SQLite
accelerates prefetch, status, doctor, and benchmark.

**Design Doc:**

- `docs/memory-os/slice-20-runtime-indexer-design.md`

**Files:**

- Modify: `plugins/memory/memory_os/index.py`
- Modify: `plugins/memory/memory_os/runtime.py`
- Modify: `plugins/memory/memory_os/prefetch.py`
- Modify: `plugins/memory/memory_os/cli.py`
- Modify: `plugins/memory/memory_os/benchmark.py`
- Test: `tests/plugins/memory/test_memory_os_store.py`
- Test: `tests/plugins/memory/test_memory_os_runtime.py`
- Test: `tests/plugins/memory/test_memory_os_prefetch.py`
- Test: `tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py`

**Runtime flow:**

```text
provider sync_turn
  -> canonical event JSONL
  -> hermes memory_os heartbeat
  -> working memory and candidate queue
  -> incremental SQLite/FTS index
  -> indexed prefetch and doctor health
```

**Review items resolved by the design doc:**

- P0 heartbeat interruption idempotency: transaction plus unique record ids and
  record hashes.
- P0 mismatch detection: explicit healthy/stale/mismatch algorithm.
- P0 crystallized Markdown indexing: frontmatter/body parser, FTS content, and
  mtime/size invalidation.
- P1 rebuild concurrency: staging DB plus atomic replace while readers use the
  old DB.
- P1 Chinese tokenizer: FTS5 trigram preferred, unicode61 fallback reported as
  degraded.
- P1 audit strategy: metadata-first, non-FTS audit indexing with capped
  heartbeat work.
- P1 WAL policy: PASSIVE checkpoint with FULL/TRUNCATE escalation.
- P1 vector/graph extension: reserved derived tables only, no v0 writes.
- P2 multi-profile isolation, schema migration, tests, and degraded prefetch
  behavior.

**Steps:**

- [x] Add failing tests for incremental event indexing and idempotent replay.
- [x] Add `index_source_state`, row hashes, and transactional incremental
      indexing.
- [x] Add index health classification and doctor findings for missing, stale,
      and mismatch.
- [x] Add crystallized Markdown body parser and candidate queue indexing.
- [x] Add FTS tables with tokenizer probe and active-tokenizer reporting.
- [x] Wire heartbeat to run incremental index after working/candidate updates.
- [x] Add full rebuild staging and atomic replace.
- [x] Add prefetch indexed path with degraded filesystem fallback.
- [x] Add WAL checkpoint escalation policy.
- [x] Add per-profile, migration, and benchmark coverage.
- [x] Run:

```powershell
python -m pytest tests/plugins/memory/test_memory_os_store.py tests/plugins/memory/test_memory_os_runtime.py tests/plugins/memory/test_memory_os_prefetch.py tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py -q
python -m pytest -q
```

**Acceptance:**

- `hermes memory_os heartbeat` indexes newly written events into SQLite.
- Running heartbeat twice is idempotent.
- Deleting `memory-os/index/memory_os.db` does not lose memory and can be
  recovered by rebuild.
- Doctor distinguishes `index_missing`, `index_stale`, and mismatch findings.
- Prefetch uses SQLite/FTS when healthy and reports degraded filesystem mode
  when not.
- Chinese search is trigram-backed when supported and explicitly degraded when
  not.
- Crystallized approved Markdown records are parsed into rows and FTS; candidate
  queue remains separate.
- Rebuild does not block live reads when an old DB exists.
- WAL is bounded by checkpoint policy.
- 100k opt-in benchmark records rebuild, indexed prefetch, and degraded
  prefetch timings.
- No production host, production gateway, production Hindsight bank, or identity
  source file is modified.

## Validation Sequence

Run after slices complete:

```powershell
cd "D:\Hermes agent manager\Hermes-Memory-OS"
python -m pytest -q
python -m compileall -q agent plugins scripts
git diff --check
```

Remote validation on `10.20.3.200` is a later execution step and must be recorded in `docs/memory-os/test-plan-10.20.3.200.md`.

## P1/P2 Coverage Matrix

| Item | Slice |
| --- | --- |
| P1 multi-root destination | Slice 2 |
| P1 transition compatibility | Slice 9 |
| P1 gateway restart strategy | Slice 14 |
| P2 meta-audit | Slice 10 |
| P2 benchmark | Slice 11 |
| P2 cleanup | Slice 12 |
| Migrator process | Slice 15 |
| Synthetic shared fixtures | Slice 1.5 |
| Worker resilience boundary | Slice 5 |
| Read-only Sannai shadow export | Slice 9 |
| Gateway restart automation deferred | Slice 14 |
| Full vertical E2E flow | Slice 16 |
| Blank Hermes plugin install/discovery | Slice 17 |
| Provider self-diagnostic tool | Slice 18 |
| Runtime heartbeat deployment | Slice 19 |
| Runtime SQLite/FTS indexer | Slice 20 |
| Slice 20 P0 interruption idempotency | Slice 20 design + implementation |
| Slice 20 P0 mismatch detection | Slice 20 design + implementation |
| Slice 20 P0 crystallized Markdown indexing | Slice 20 design + implementation |
| Slice 20 P1 rebuild concurrency | Slice 20 design + implementation |
| Slice 20 P1 Chinese tokenizer | Slice 20 design + implementation |
| Slice 20 P1 audit index strategy | Slice 20 design + implementation |
| Slice 20 P1 WAL checkpoint fallback | Slice 20 design + implementation |
| Slice 20 P1 vector/graph extension space | Slice 20 design |
| Slice 20 P2 multi-profile isolation | Slice 20 design + implementation |
| Slice 20 P2 schema migration | Slice 20 design + implementation |
| Slice 20 P2 test matrix | Slice 20 design + implementation |
| Slice 20 P2 degraded prefetch | Slice 20 design + implementation |

## Execution Gate

Do not start code until this plan is reviewed. First implementation target should be Slice 0 through Slice 3 only; that gives a discoverable provider, schema, roots, and canonical store without prefetch, working memory, crystallization, adapter, or remote validation risk.

After Slice 0-3 baseline is accepted, the next bounded target should be Slice 1.5 plus Slice 4-6 only. Stop again before Slice 7 because working memory begins affecting inner-drive semantics.
