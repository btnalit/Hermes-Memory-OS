# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hermes Memory-OS is a file-first memory and governance runtime that plugs into Hermes agents as a `memory_os` provider. It manages profile-local canonical memory, owner review/approval workflows, governed automatic lanes, and monitor evidence — without owning conversation, transport, or scheduling (those remain Hermes' domain).

## Build & Test Commands

```bash
# Install dev dependencies (Python 3.11+ required)
python -m pip install -e ".[dev]"

# Run full test suite
python -m pytest -q

# Run a single test file
python -m pytest -q tests/plugins/memory/test_memory_os_owner_actions.py

# Run a single test by keyword
python -m pytest -q -k "test_approve_candidate"

# Static checks (run before committing)
python scripts/memory_os_import_cycle_check.py --repo-root .
python scripts/memory_os_write_surface_check.py
python scripts/memory_os_static_hygiene_check.py
python scripts/memory_os_public_checkout_probe.py --source working-tree --strict
git diff --check

# Remote probes (require SSH access to configured hosts)
python scripts/memory_os_cron_adapter_probe.py --host hermes-media --output json
python scripts/memory_os_boundary_runtime_probe.py --host hermes-media --output json
python scripts/memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
python scripts/memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output summary
```

Tests live under `tests/plugins/memory/` (core/provider) and `tests/scripts/` (scripts/integration). Test files mirror source modules 1:1 by naming convention.

## Architecture

Hermes is the host agent. Memory-OS is a governed plugin with these layers:

### Core Provider (`plugins/memory/memory_os/`)

- **`__init__.py`** — `MemoryOSProvider`: the main entry point. Hermes calls `initialize` → `prefetch` (read context) → `sync_turn` (write summary-only events to the event queue). Owner-review commands are excluded from turn sync to avoid contaminating memory.
- **`runtime.py`** — `MemoryOSRuntime.heartbeat()`: drives the main processing loop — event queue → working memory decay → candidate generation → index sync → SessionMirror auto-apply. Wrapped in an ExecutionGate `runtime_heartbeat_core` envelope.
- **`cognitive_loop.py`** — `CognitiveLoopRunner.run_once()`: orchestrates portable modules, signal collection, memory projection, and left-brain advisor runs. Each step is ExecutionGate-wrapped.
- **`owner_actions.py`** — `OwnerActionProcessor`: the state-changing entry point. Processes `approve`, `reject`, `feedback`, `allow`, and bounded `apply` actions via stable `oa_` tokens generated in owner digests. High-risk transitions (crystallized writes, revoke/demote/delete, identity writes, external sends) are permanently owner-gated.
- **`execution_gate.py`** — per-execution machine permit system. Creates permit envelopes (`permit_id`, `lane_id`, `risk_class`, `scope`, `boundary`), validates scope, records completion postcheck. Applied to heartbeat, cognitive loop, and cron helpers.
- **`structural_write_gate.py`** — `append_governed_jsonl()`: gates all automatic JSONL writes through ExecutionGate permits. The `write_surface_check.py` script enforces `unclassified_count=0` across the codebase.

**Important naming distinction**: `execution_gate.py` is the *runtime* ExecutionGate (machine permit for automatic work). `plugins/modules/governance/ops_gate.py` is the *proposal* OpsGate (report-only follow-up review of proposals). These are different systems — don't confuse them.

### Memory & Retrieval Layer

- **`store.py`** — file-first primitives: JSONL append/read, atomic JSON writes, quarantine handling.
- **`index.py`** — SQLite index for search and prefetch. Rebuildable from canonical files — never treat the index as the source of truth.
- **`roots.py`** — resolves profile/platform paths (`HERMES_HOME`, `memory-os/` subdirectories).
- **`prefetch.py`** — assembles context for Hermes from task anchor, runtime facts, context router hints, low-clue recall, memory sources, and substrate provider facts.
- **`context_router.py`** — provides context route hints for prefetch decisions.
- **`session_mirror.py`** — bounded session import lane. Owner-graduated (via `approve_session_mirror_apply`), then auto-applied by heartbeat with per-run session caps and platform allowlists. Append-only, no crystallized/policy/identity writes.
- **`crystallized.py`** — owner-approved canonical memory. Candidates require explicit owner approval before becoming crystallized. Supports candidate triage (promote/demote/fleeting/discard) with auto-demote TTL.
- **`jsonl_io.py`** / **`state_source_mirror.py`** — shared IO contract for JSONL and state file operations. Produces bounded `error_record` counters for malformed data. New write paths should use these rather than ad-hoc helpers.
- **`task_anchor.py`** — active task anchor detection for topic-switch handling.
- **`low_clue_recall.py`** — low-clue recall support using judge availability checks.

### Substrate Providers (`plugins/memory/memory_os/substrates/`)

Provider-neutral abstraction for governed recall from external memory systems:

- **`base.py`** — abstract contracts: `SubstrateSnapshot`, `GroundingFact` (always `advisory_only=True`, `authority_class="derived_projection"`).
- **`local_artifact.py`** — `LocalArtifactProvider`: the **primary authority**. Local canonical facts always outrank external substrate facts.
- **`hindsight.py`** — `GovernedHindsightSubstrate`: optional derived projection from Hindsight. Retain restricted to crystallized/owner-approved sources only; recall is advisory; reflect is off-hot-path and produces bounded candidates only. LocalArtifact is always primary.
- **`router.py`** — `SubstrateRouter`: routes queries across configured substrates with priority ordering.
- **`ledger.py`** — append-only substrate operation ledgers for audit.
- **`projection.py`** — substrate-level projection helpers.

### Projection & Advisor Layer (left-brain governance)

- **`signal_source_registry.py`** + **`signal_collectors.py`** — metadata-only signal inventory and collection. Must never capture raw message bodies or secrets.
- **`memory_projection.py`** — `collect_and_project_signals()`: projects normalized signals into `memory_projections.jsonl` with compaction. ExecutionGate + StructuralWriteGate gated.
- **`left_brain_advisor.py`** — produces owner-visible findings from projection data. Report-only — findings go to the owner review surface, not to automatic apply.
- **`metadata_retention.py`** — metadata retention and compaction policies.
- **`graph_layer.py`** / **`structural_edge_proposer.py`** / **`llm_edge_proposer.py`** — graph-based memory structure with canonical edges, governance, and weight normalization (active development area).

### Portable Modules (`plugins/modules/`)

Organized by domain: `cognition/`, `context/`, `evidence/`, `expression/`, `governance/`, `messaging/`. Each module exposes `run_once`/`status`/`doctor` entry points and produces bounded artifacts. Modules are called through the cognitive loop, not independently, and their writes must go through StructuralWriteGate. Key governance modules include `candidate_review.py`, `proposal_queue.py`, `ops_gate.py` (proposal OpsGate, not runtime ExecutionGate), `crystallized_revalidator.py`, `ground_truth_miner.py` (reversible labels), and `live_guard.py`.

### Scripts (`scripts/`)

- **Install/deploy**: `install_memory_os.sh` (safe, no gateway restart), `deploy_memory_os.py` (phased: `plan` → `preflight` → `dry-run` → `apply` → `postcheck` → `report`)
- **Monitor**: `memory_os_3_200_monitor.py` (production full monitor), `memory_os_monitor.py` (neutral entrypoint)
- **Cron helpers**: `memory_os_execution_gate_runner.py` (per-cron ExecutionGate wrapper, sets `MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID`), owner digest, proposal follow-up, right-brain expression helpers
- **Validation**: `write_surface_check.py`, `import_cycle_check.py`, `static_hygiene.py`, `public_checkout_probe.py`

### Agent Surface (`agent/`)

Minimal Hermes compatibility glue. `MemoryProvider` base class and provider registration. Must not carry governance state.

## Key Design Rules

### Gate System
- **ExecutionGate**: every automatic execution must open a permit envelope, validate scope/risk_class/boundary, and record completion postcheck.
- **StructuralWriteGate**: every automatic JSONL append must be classified through a permit. `write_surface_check.py` enforces `unclassified_count=0`.
- **OwnerGate**: crystallized writes, revoke/demote/delete, identity/relationship writes, route/score authority, Hindsight store mutation, and external sends are permanent human-trust boundaries.
- **ResolverGate**: validates owner-channel or execution-token authority before apply. Self-declared `--owner-approved` is not valid authority.

### File-First Design
Canonical data lives as JSONL files under `$HERMES_HOME/memory-os/`. SQLite indexes are rebuildable — never treat the index as the source of truth. Key paths: `events/`, `working/`, `candidates/`, `crystallized/`, `system/` (owner actions, execution gate envelopes, proposal ledgers, memory projections, hindsight curation decisions), `system-modules/` (module outputs like advisor reports, reversible labels).

### No Silent Failures
Broad `except Exception` must record bounded error records (`error_record` schema: component, operation, error_code, severity, recoverable). Silent pass on live write paths is forbidden. The monitor aggregates suppressed error counts per component.

### Evidence Levels (never conflate)
- `fast_probe_pass` — cron/gate health (seconds)
- `live_monitor_pass` — full production health (target ≤180s)
- `clean_host_warn` — compatibility host WARNs are expected (target ≤240s)
- `local_pass` — pytest suite
- `deploy_pass` — installer/deploy wrapper success
Fast probe PASS is not a substitute for full live monitor PASS.

### Cron Profile
Default is `active-closure` (2 jobs: `memory-os-owner-review-digest` + `memory-os-proposal-followups-opsgate`). The `full` profile adds optional expression/cadence/feedback jobs. On upgraded hosts, active-closure onboarding pauses (does not delete) known optional jobs. The monitor classifies paused optional jobs as known optional rather than unregistered drift.

### Owner Actions
Display anchors (`A1`, `R1`, `F1`) in digests are UI labels only. The durable identity is the `oa_` action token. Owner approval moves a proposal into human-controlled follow-up — it does not execute work. Only proposal kinds with a bounded runtime target, rollback, monitor fields, and an explicit apply token can be applied.

## File Modification Guidelines
- `owner_actions.py` and `memory_os_3_200_monitor.py` are large files; make minimal targeted changes only. Do not split them for line-count reasons or create facade-only abstractions.
- New proposal kinds require their own bounded apply contract, rollback, monitor fields, and owner-visible workflow before they can be applied.
- Do not add cross-import chains between governance modules (advisor → projection → collectors → owner_actions → session_mirror is forbidden).
- Internal docs under `docs/internal-memory-os/` are gitignored and excluded from GitHub main. Do not use them as the sole source of truth for public-facing changes. The canonical public documentation is in `docs/` (non-internal).
- The two known deployment hosts are `hermes-media` (10.20.3.200, production live closure) and `hermes-feiniu` (10.20.2.66, clean-host compatibility smoke). Do not describe clean-host results as equivalent to production.

## Development Process (mandatory)

### Stabilization Checklist — Required Before & After Every Task

**Before starting work**, read `docs/resolver/hermes-memory-os-stabilization-checklist.md` once — at minimum the latest section and Section W (经验教训). This is not optional. The checklist records every repair cycle and the mistakes that made each one take multiple rounds. Skipping it guarantees repeating those mistakes.

**After completing work** (all tests pass, ready to push), update the checklist:
- Add a new section documenting: what was fixed, root cause, counterfactual coverage, test count delta, final test count
- Append the commit range and a one-line summary to the "一句话" footer
- This is not a nice-to-have — it is part of the definition of "done"

### Repair Rules (from Section W — applied to EVERY change)

These five rules were extracted from a cycle where three patches passed code review but introduced five regressions. They apply to every change, no exceptions:

1. **Read the full function before modifying it.** Diff hunks are not enough — you must understand all branches, all default-parameter paths, and all return sites in the function you are touching.
2. **Grep test files for the symbols you are changing.** String constants, function signatures, path patterns — if you change it, grep for it in tests. A test that monkeypatches the old string is a test you just broke.
3. **Every fix gets a counterfactual test.** Ask: "If my fix were absent, what would go wrong?" — then write that as a test. The test must FAIL without your fix and PASS with it.
4. **Default parameters must never be traps.** If `param=None` causes data loss, crash, or silent skip on any path, it is not an optional parameter — it is a landmine. Give it a safe default or remove the default.
5. **Grep the whole project for the same bug pattern.** Found a defect in one file → grep all files for the same pattern → fix or document every occurrence.

### Beyond the Pointed-Out Problem — Trace the Whole Call Chain

When asked to fix "X is not Y", do not stop at making X become Y. Trace every consumer of X: what else on the same call path has the same class of defect? Use `codegraph_explore` to read the full call chain before declaring completion.

Examples of what this catches:
- "CLI status is not O(1)" → cache `continuity_selector` AND check `_index_health_findings` AND check `_index_health_summary` → all four data paths, not just the one flagged
- "audit records are not visible" → fix read visibility AND check sort order → consumers using `[-N:]` depend on correct ordering

### Definition of Done — Self-Verification Before Push

Before claiming "X is fixed" or pushing, do these in order:

1. **Enumerate sub-items.** "O(1) CLI status" = counts + summaries + continuity_selector + index_health. List them. Verify each one.
2. **Run the counterfactual.** If your fix were absent, would existing tests catch the bug? If not, add the test.
3. **Reverse review.** Read your diff as if you were the reviewer whose job is to find gaps. What did you not touch that looks related? Why?
4. **Run full test suite.** Never push after running only the tests you added or modified.

### Tests Verify "Did", Not "Didn't Miss"

A passing test suite proves that the behaviors you implemented work correctly. It does NOT prove you implemented all necessary behaviors. The only defense against omissions is the self-verification checklist above — tests cannot verify the absence of missing work.
