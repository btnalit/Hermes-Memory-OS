# P0–P2 Cognitive Partner Closure Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Restore natural V2/V3 observation and close the minimum semantic-integrity, review-agenda, recall-shadow, and operational-truth gaps without widening Owner approval, identity, delivery, execution, or permanent-memory authority.

**Architecture:** Keep canonical Memory-OS stores unchanged except for explicitly authorized metadata-only natural observations. Repair rebuildable views at their producer/read-model seams, keep Recall/Agenda changes shadow or canary until evidence gates pass, and converge operational status through existing Monitor/Dashboard consumers rather than adding another canonical store.

**Tech Stack:** Python 3.11, pytest, JSONL/JSON projections, Hermes cron, systemd user timers, Memory-OS ExecutionGate/StructuralWriteGate.

---

## Frozen boundaries

- Never auto-approve or write permanent crystallized memory.
- Never write identity/relationship or execute external actions.
- V3 synthesis/outlet/expression remain disabled.
- Manual/test probes never count as natural evidence.
- No Hermes gateway restart without separate explicit authorization.
- Source changes follow RED → GREEN → full suite → governance gates → independent review → local commit → targeted production deploy → production verification. Remote push remains last and is unnecessary unless source changes are made and all production gates pass.

## Task 1 — P0 metadata-only natural observation

**Files:**
- Production config: `/root/.hermes/memory-os/config.json`
- Source readers: `plugins/memory/memory_os/config.py`, `memory_sources.py`, `__init__.py`
- Tests: existing MemorySources/config tests

1. Trace whether config is loaded per prefetch or at provider initialization.
2. Back up production config.
3. Change only `memory_sources.enabled: false → true`; preserve metadata-only, no-body, live-prefetch and retention settings.
4. Verify loaded config and provider boundary flags without generating a fake natural cycle.
5. Record the first future non-skipped scheduled rollup as the new observation-window candidate; do not rewrite legacy rows.

## Task 2 — P1 State Overlay semantic integrity

**Files:**
- Modify: `plugins/memory/memory_os/state_overlay.py`
- Possibly modify shared latest-effective task helper only if inspection proves divergent semantics.
- Test: `tests/plugins/memory/test_memory_os_state_overlay.py`
- Test: `tests/scripts/test_memory_os_state_overlay_refresh.py`

1. Add RED fixture with duplicate last-session objects and assert one effective open-thread item.
2. Add RED fixture where a later completed/cancelled/superseded task record defeats an earlier active row.
3. Implement the smallest shared dedupe/latest-effective fix.
4. Verify source refs and order remain deterministic.

## Task 3 — P1 scheduler noise cleanup

**Files/state:**
- `/root/.hermes/cron/jobs.json` (backup first)
- Hermes cron jobs identified by stable IDs after a fresh list

1. Re-list jobs and re-identify placeholder `claim job`/`w` entries by exact shape.
2. Back up jobs.json.
3. Remove only confirmed active test placeholders.
4. Pause expression-feedback request while expression source is disabled and no unresolved feedback item requires it.
5. Re-list all Memory-OS jobs and prove core jobs remain enabled with unchanged schedules.

## Task 4 — P1 fresh full-Monitor truth in Dashboard

**Files:**
- Modify: `scripts/memory_os_3_200_monitor.py` and/or `scripts/memory_os_monitor_dashboard_snapshot.py` only after tracing current artifact ownership.
- Tests: `tests/scripts/test_memory_os_3_200_monitor.py`, `tests/scripts/test_memory_os_monitor_dashboard_snapshot.py`

1. Add RED fixture showing Dashboard chooses a stale historical artifact while a newer live artifact exists.
2. Define one freshness-bound artifact selection contract; do not run the 195-second monitor inside every dashboard request.
3. Ensure a successful live monitor run can atomically publish the current artifact and Dashboard selects it.
4. Preserve explicit stale status when no fresh artifact exists.

## Task 5 — P2 Recall Plan shadow

**Files:**
- `plugins/memory/memory_os/recall_arbitration.py`
- `plugins/memory/memory_os/prefetch.py`
- `plugins/memory/memory_os/recall_facade.py`
- `tests/plugins/memory/test_memory_os_recall_arbitration.py`

1. Verify `mode=shadow` is output-byte-neutral and produces metadata-only observation evidence.
2. Add/retain forced-current-source, duplicate-ID, stale-body, cooldown escape, mixed-script and short-ID controls required by governance review.
3. Enable master `recall_arbitration.mode=shadow` only if observation producer and Monitor/status consumer are both real.
4. Do not enable apply globally; canary remains frozen unless zero-omission and authority/freshness evidence pass.

## Task 6 — P2 Review Agenda canary gate

**Files:**
- Existing owner-review/read-effective-candidate paths in `plugins/memory/memory_os/owner_actions.py`, candidate clusters/triage readers, Monitor/Dashboard tests.

1. Compare raw → latest-effective → agenda → shown identities.
2. RED fixtures: duplicate candidate ID/body revisions, terminal target, empty cluster, stale token, deferred cooldown.
3. Require action-time resolution to bind the exact revision reviewed.
4. Keep `review_agenda_v2_mode=shadow` unless every blocker is green; otherwise expose a bounded canary only to current-owner Telegram surface with rollback.

## Task 7 — P2 minimum Lane Status convergence

**Files:**
- Existing cron registry/catalog, installed registry snapshot, Monitor and Dashboard consumers.

1. Inventory package registry, installed active-subset manifest, actual cron jobs, timers, ExecutionGate receipts and artifact freshness.
2. Add one typed read-model function/view consumed by Monitor and Dashboard; preserve desired-vs-observed state.
3. RED fixtures for missing installed manifest, paused required job, extra retired job, stale artifact and scheduler/output mismatch.
4. Do not create a new canonical ledger.

## Task 8 — Verification and release

1. Targeted tests for every RED/GREEN task.
2. Full suite in private mount-isolated clean checkout.
3. Write-surface, closure matrix, static hygiene, import-cycle and public-checkout gates.
4. Freeze exact staged diff hash and run independent BLOCKER/HIGH review.
5. Local checkpoint commit only after review.
6. Back up affected production files and targeted deploy all independent copies/scripts.
7. Production-import, installed-script, Dashboard/Monitor and scheduler verification; no canonical data mutation except authorized metadata observation.
8. Gateway reload remains a separate Owner authorization boundary.
