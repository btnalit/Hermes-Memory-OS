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
- **`runtime.py`** — `MemoryOSRuntime.heartbeat()`: drives the main processing loop — SessionMirror auto-apply **first** (its events are read by the same cycle — a deliberate latency win, not isolation) → event read + stats cache → candidate generation → working memory decay/prune → state write → index sync. Wrapped in an ExecutionGate `runtime_heartbeat_core` envelope.
- **`cognitive_loop.py`** — `CognitiveLoopRunner.run_once()`: orchestrates portable modules, signal collection, memory projection, and left-brain advisor runs. Four steps open explicit ExecutionGate envelopes (ground_truth_miner, memory_projection, left_brain_advisor, spontaneous_expression); the remaining steps rely on module-internal governance surfaces (StructuralWriteGate etc.).
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
- **Graph memory layer** — "graph_layer" is a feature/source-class name, **not a module**: there is no `graph_layer.py`. Edge *birth* is five proposer steps in the cognitive loop (`structural_edge_proposer.py`, `llm_edge_proposer.py`, `vector_edge_proposer.py`, `edge_provenance.py`, `llm_contradiction_lane.py`); every proposer except the contradiction lane emits `active` directly — the 2026-08-06 owner ruling abolished per-edge review; wrong edges are demoted by weight feedback, with `reject_edge` kept as an owner correction tool, not an approval gate. The contradiction lane alone emits `candidate`, drained by the sixth cognitive-loop step `edge_promotion.py` — **not a birth step** but the backlog auto-activation channel: weight-ordered activation (25/run) plus a 30-day TTL to `invalidated`. Edge *lifecycle* lives in `edge_weights.py` (evidence-tiered birth priors; llm edges `0.45 + 0.30 × confidence`; vector edges are the documented exception — born at raw cosine similarity, no upper clamp) and `edge_weight_feedback.py` (hit reinforcement `w += 0.12 × (1 − w)`; 60-day idle forgetting → `invalidated`, ≤50/run, watermark `max(created_at, last_hit, first_injection_at)`). Edge *injection* lives in `prefetch.py` (`_graph_layer_shadow_lines`: anchors → one bounded hop → 6 exploit + 2 explore slots → "Related Memory") with the closed-outcome shadow ledger `system/graph_layer_shadow.jsonl`. Architecture positioning and loop-closure status: `docs/architecture.md`.

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
- **StructuralWriteGate**: every automatic JSONL append must be classified through a permit. `write_surface_check.py` enforces `unclassified_count=0`. **One structural exception**: the per-turn prefetch path runs inside Hermes' request, not inside a cron envelope, so it has no permit to spend. Writes there are classified through the `report_only_*` allowlist route instead (`prefetch.py::_record_substrate_shadow_recall`, `_record_graph_layer_shadow`, `_record_continuity_freshness` — see `ALLOWED_WRITE_SURFACES`). Do not "fix" such a write by opening an envelope on the hot path: that puts gate bookkeeping in the user's latency path and violates INV-5's spirit. Classify it report-only, keep it append-bounded, and give it a signature-dedup so a per-turn path cannot grow unboundedly.
- **OwnerGate**: crystallized writes, revoke/demote/delete, identity/relationship writes, route/score authority, Hindsight store mutation, and external sends are permanent human-trust boundaries.
- **ResolverGate**: validates owner-channel or execution-token authority before apply. Self-declared `--owner-approved` is not valid authority.

### File-First Design
Canonical data lives as JSONL files under `$HERMES_HOME/memory-os/`. SQLite indexes are rebuildable — never treat the index as the source of truth. Key paths: `events/`, `working/`, `candidates/`, `crystallized/`, `system/` (owner actions, execution gate envelopes, proposal ledgers, memory projections, hindsight curation decisions), `system-modules/` (module outputs like advisor reports, reversible labels).

### No Silent Failures
Broad `except Exception` must record bounded error records (`error_record` schema: component, operation, error_code, severity, recoverable). Silent pass on live write paths is forbidden. The monitor aggregates suppressed error counts per component.

**A gate whose vocabulary drifts from its producer's checks nothing, silently.** When a check hardcodes a set of class/kind/type names, those names must be validated against what the producer actually emits — ideally by a test that enumerates the producer's vocabulary rather than one fixture value. Live example: `exposure_rollup._memory_source_has_attribution_gap` gates on `attributable_classes = {crystallized, working, entity_graph, indexed_recall, vector, hindsight}`, but `prefetch._section_source_class` emits `indexed`, `graph_layer`, `substrate_recall`, `event`, `candidate`… — four of the six configured names have no producer anywhere in the project. Measured consequence on production: the gate counts 69 attribution gaps and silently skips 1093. Its test fixture hardcodes `source_class: "crystallized"`, so twelve of thirteen real classes were never exercised. **Corollary**: when a metric's coverage is wrong, widening it makes the number worse before it makes the system better — never "fix" a FAIL by narrowing what is measured (see the roadmap's rule against buying green status). *(Fixed in CC: `ATTRIBUTABLE_SOURCE_CLASSES` / `NON_ATTRIBUTABLE_SOURCE_CLASSES` plus `prefetch.SECTION_SOURCE_CLASS_BY_TITLE` lifted to module scope so a guard test can assert both directions — every producer class is classified, and no configured name lacks a producer. The producer vocabulary was a function-local dict, invisible to every test; that invisibility is what let the drift exist.)*

**A check nothing can satisfy retroactively needs an era boundary — and an empty gated set must report no-sample, never pass.** Some contracts cannot be met by old records even in principle: an attribution gap in an already-written disclosure row can never be filled, because the disclosure happened and the IDs were never captured. Gating on those rows means no amount of correct new code ever clears the FAIL. The pattern (`legacy_unmarked_rollup_count`, and now `ATTRIBUTION_SCHEMA_VERSION` / `legacy_unattributed_record_count`) is: mark records written by the fixed producer, judge only marked records, and surface unmarked ones as *debt* — still counted in the all-history view, classified rather than erased. **The trap this opens is worse than the original bug**: on deploy day nothing carries the marker, so the gated set is empty, the count is 0, and it reports PASS — green bought by narrowing the measurement. So an empty gated set must report `healthy_no_sample` (a PASS-class value that says on its face there is no sample) and keep any dependent unfreeze gate frozen until real marked traffic exists. Prove the boundary widened coverage rather than hid a failure by measuring both: CC's corrected vocabulary finds 129 gapped natural rows where the old one found 69.

**Architectural firewall tests may scan source text, not just imports — reword the comment, never weaken the firewall.** `test_x3_exposure_firewall::test_prefetch_ranking_not_contaminated_by_exposure` greps `prefetch.py`'s full source for `exposure_rollup` / `selected_count` / `exposure_rollup_lag`, so even a comment naming the audit layer fails it. That bluntness is deliberate: it enforces that prefetch ranking can never read exposure data. When a legitimately one-way change (producer writes IDs → audit reads them, no import, no data dependency) trips it, the fix is to describe the contract without naming the module. Relaxing an architectural test to accommodate a comment trades a real invariant for a cosmetic one. It also shows why targeted test runs are insufficient: all ten new attribution tests passed while this failed — only the full suite caught it.

### Completion Is Not Output
Helper completion is judged from the ExecutionGate envelope, which records **that a lane ran** — never that it *produced* anything. A lane that legitimately has nothing to do and a lane that is broken both close a clean envelope, so the envelope alone cannot tell them apart. Three verified instances of this shape:

- `low_clue_recall._call_hermes_runtime_model` returns `""` on *any* failure, indistinguishably from a successful empty answer. On production 22 of the last 80 `fact_judge` calls were `llm_empty_content` (27.5%). Never propagate that bare `""` as success — `plugins/modules/governance/fact_judge.py` is the reference for doing it correctly (retry loop, typed `failure_reason`, deterministic fallback). *(The caller sweep in CD found and fixed two propagators: `clearance_cycle`'s per-pair judge fell through every empty reply to a constant `"clear"` — now fail-closed to `judge_unavailable` when zero pairs were actually judged — and `llm_contradiction_lane` silently `continue`d on `""` — now a typed `llm_empty_content` error record. The same sweep exposed that the contradiction lane's prompt template had unescaped braces and crashed on the first pair: the loop had never been executed by any test.)*
- `session_mirror` ran 637 times with 0 findings while its backlog grew (1574 → 1575). Its selection is pure head-of-queue (`platform_filtered[:limit]`, self-admitted in a code comment), so a stuck head starves the tail forever. Never copy that selection pattern; use a durable processed-fingerprint set so the backlog drains. *(Fixed in CD: scan orders never-imported sessions first — the signal derives from mirrored events, so it survives `_rebuild_state()` — and `auto_apply_graduated_session_mirror` records every exit's reason in `system/session_mirror_auto_apply_last_run.json`.)*
- `exposure_rollup` has two no-write exits that leave **byte-identical** evidence: the benign `if not new_records: skipped=True` return, and the `source_cursor_not_found` error return when compaction removed the cursor. Both leave `exposure_rollup.jsonl` *and* `exposure_rollup_snapshot.json` untouched, so from the artifacts alone a permanently-broken lane looks exactly like an idle one. Distinguishing them required reading the source and hand-probing the cursor against `memory_sources.jsonl`. *(Fixed in CD: every run now records a `last_run` block in the snapshot with a closed outcome set — produced / no_new_records / source_cursor_not_found / legacy_source_cursor_missing / write_failed — surfaced by `exposure_monitor_stats` and the monitor's ledger-state INFO entry.)*

**Therefore**: any lane that produces no output must record *why* in a durable artifact, using a closed set of documented reason codes, so a reader can separate "no eligible input" from "input existed but processing failed" **without re-running anything or reading the source**. Per-run production counters (inputs scanned / eligible / processed / produced, plus failures keyed by reason) are part of the lane's contract, not optional telemetry. `continuity.py`'s freshness ledger (transition dedup plus an explicit `unknown` counter) is the pattern to copy. Note that a metric which is merely *computed and reported* does not close this gap: `exposure_rollup_lag_hours` was returned by `exposure_monitor_stats` for months while never graded into PASS/WARN/FAIL, alerting nobody. *(It now rides the `v2_exposure_rollup_ledger_state` INFO entry — deliberately ungraded, because an idle upstream inflates lag benignly; the `last_run` outcome beside it is what disambiguates.)*

**Audit "does this metric have a reader?" by hand, not by text match — a grep counts *talking about* X as *using* X.** A full audit of `exposure_monitor_stats`'s 31 returned keys found 9 with no production reader, but the tool's first version was wrong in both directions and each error is easy to repeat. **False positive**: `exposure_rollup_lag_hours` looked like it had a reader in `memory_os_3_200_monitor.py` — every hit was a *comment* naming it as a known-unread metric. Filter whole-line comments before believing a hit. **False negative**: excluding the producer file hides keys consumed *internally*; `telemetry_degraded_count`, `initial_natural_cycle_count`, `production_observation_days` and `budget_pressure_streak_days` all look orphaned but drive `freeze_reasons`/`schema_health` inside `exposure_rollup.py`, and those *are* read. Two findings worth remembering: `schema_era_classified_ratio` is the `0.6506→0.7018` figure repeatedly cited as evidence of data maturity, and no code read it — a number can be load-bearing in argument while feeding no decision. And `legacy_unmarked_rollup_count`, cited as the precedent for the attribution era boundary, had no production reader either: a pattern can be right in design and still fail on visibility, so copy its structure without inheriting that gap. *(Closed in CD: every `exposure_monitor_stats` key now has an explicit disposition — graded / info / internal / component — pinned by a key-set census test in `test_memory_os_phase1_observability.py`, so a future key must be triaged at birth. The census also caught `attribution_gap_count`, an unread duplicate alias the hand audit itself had missed because its name is a substring of three read keys; it and the misnamed `schema_era_natural_record_count` were deleted.)*

### LLM Integration — Reuse, Never Rebuild
Memory-OS does not own model credentials, clients, or provider selection. It borrows Hermes'. Before adding any model call, use the existing seam:

- **`low_clue_recall._call_hermes_runtime_model(prompt, config) -> str`** is the single entry point, and **`_extract_json_object`** is the response parser. Both are imported across module boundaries by existing callers (`plugins/modules/governance/fact_judge.py`); that private cross-module import is deliberate and precedented — keep new callers consistent with it rather than inventing a wrapper or a second client.
- Provider resolution lives in `_resolve_hermes_default_runtime`, which imports `hermes_cli.config.load_config` and `hermes_cli.runtime_provider.resolve_runtime_provider`, falling back through `HERMES_AGENT_ROOT` then `/usr/local/lib/hermes-agent` on `sys.path`. Provider id is `hermes_default`; api modes are `chat_completions` / `codex_responses` / `anthropic_messages`. Do not add a provider, a credentials path, or an SDK dependency.
- **`fact_judge.py` is the reference implementation for a governed LLM lane.** Copy its shape: bounded config (`timeout_ms` 15000, `max_tokens` 1024), a retry loop, typed failure values (`llm_exception`, `llm_empty_content`, `llm_parse_failed`, `llm_missing_key`), a deterministic non-LLM fallback, and a `failure_reason` on the report. See **Completion Is Not Output** for why the bare `""` return must never be treated as success.
- Per-lane limits are knobs registered in `OVERRIDABLE_KNOBS` (`knob_overrides.py`), named `<lane>_max_tokens` / `<lane>_max_per_tick` / `<lane>_timeout_ms`.
- **INV-5: no LLM on the hot path.** Model calls belong in offline cron lanes only — never in prefetch, `sync_turn`, or heartbeat. Always bound the *input* too: a single production session message has been measured at 975,665 characters against a 1024-token reply budget, so unbounded input is a guaranteed failure, not an edge case.

### Evidence Levels (never conflate)
- `fast_probe_pass` — cron/gate health (seconds)
- `live_monitor_pass` — full production health (target ≤180s)
- `clean_host_warn` — compatibility host WARNs are expected (target ≤240s)
- `local_pass` — pytest suite
- `deploy_pass` — installer/deploy wrapper success
Fast probe PASS is not a substitute for full live monitor PASS.

### Cron Profile

`cron_registry.py` holds **two tables**, and the distinction is load-bearing:

- **Lanes** (`MEMORY_OS_CRON_LANES`, 23) — the governance identity: `lane_id`, `raw_script`, `helper_kind` (risk class), boundary contract. One ExecutionGate envelope per lane per run. This never collapses.
- **Groups** (`MEMORY_OS_CRON_GROUPS`, 9) — the Hermes scheduling surface: what `hermes cron create` actually creates.

Default profile `active-closure` installs **8 Hermes cron jobs** covering 22 lanes (`module_cadence_report` is full-profile only; `clearance_cycle` was activated and `state_source_mirror` registered on 2026-08-06 — the exclusion intent record is `cron_registry.ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS`):

| Group job | Schedule | Members |
|---|---|---|
| `memory-os-tick-derived` | `2,17,32,47 * * * *` | event_stats_refresh, index_sync, state_overlay_refresh, entity_index_refresh |
| `memory-os-tick-governance` | `7,37 * * * *` | proposal_followups_opsgate (+ clearance_cycle when enabled) |
| `memory-os-tick-evidence` | `12 * * * *` | hindsight_health_probe, fact_judge, candidate_aggregation, l3_probe_verification, v3_wandering, session_fact_extraction |
| `memory-os-tick-daily` | `5 0 * * *` | exposure_rollup, v3_seed_evidence, v3_journal_sweep, working_cleanup, hindsight_advisory_digest |
| `memory-os-owner-review-digest` | `0 9 * * *` | owner_review_digest |
| `memory-os-memory-sources-feedback-request` | `30 10 * * *` | memory_sources_feedback_request |
| `memory-os-expression-feedback-request` | `0 5 * * 0` | expression_feedback_request |
| `memory-os-full-monitor-refresh` | `30 2 * * *` | full_monitor_refresh |

Rules that follow from this:

- Tick minutes are **staggered** (`:02/:17/:32/:47`, `:07/:37`, `:12`, `00:05`) so no two group jobs start in the same minute. Aligned expressions (`*/15`, `*/30`, `0 * * * *`) all fire at `:00`, which reintroduces exactly the same-minute contention on `execution_gate_index.json` that consolidation exists to remove. Staggering changes no lane's cadence.
- A group's cron cadence is its **finest** member's. Each lane keeps its own effective rate via `due_interval_minutes`; `scripts/memory_os_cron_group_runner.py` skips members that aren't due. Adding a lane means adding it to a group, **not** creating a cron job.
- **Adding a lane touches six places.** ① the `cron_registry.py` lane def; ② that group's `member_keys`; ③ `knob_overrides.py` if it has knobs; ④ `install_memory_os_plugin.py` — both a `SOURCE_*` constant and an entry in `_write_operational_helper_scripts`, which enumerates helpers individually (miss this and `owner_cron_onboarding` returns `blocked`, creating **zero** jobs, because it requires every group member's helper to exist under `<hermes_home>/scripts/`); ⑤ `memory_os_3_200_monitor.py::ERROR_RECORD_EMITTING_COMPONENTS` if the lane emits `error_record`s; ⑥ regenerating the deployed registry snapshot (next bullet). Do **not** add it to `LEGACY_PER_LANE_CRON_JOBS` — that table lists only pre-consolidation standalone jobs already present on onboarded hosts so onboarding can pause them as a rollback path; a lane born inside a tick never had one, and an entry there would tell onboarding to pause a job that never existed. `write_surface_check.py` needs nothing as long as writes go through `append_governed_jsonl` / `append_candidate_queue`.
- **Registering a new lane is not enough to make it run on a host — the installed registry snapshot must be regenerated, and forgetting is SILENT.** `cron_group_runner._load_group` prefers `<hermes_home>/memory-os/system/memory_os_cron_registry.json` and returns the snapshot's `member_keys` without falling back to the compiled-in registry whenever that member list is non-empty. So on an already-onboarded host a newly registered lane is simply absent from its tick: no `unknown_registry_key`, no error record, no WARN — the tick closes a clean envelope having never invoked it. (`execution_gate_runner._load_spec` *does* fall back to the compiled-in registry, so the failure is specifically at group-membership resolution, not permit issuance.) Regenerating the snapshot is owned by `install_memory_os_plugin.py` and `memory_os_owner_cron_onboarding.py`; treat it as a required deployment step for any lane addition, and verify the new `lane_id` appears in the snapshot post-deploy rather than assuming registration sufficed.
- `due_policy="calendar"` exists for date-partitioned lanes (`v3_seed_evidence`), which must run at most once per UTC day rather than on elapsed time.
- **The monitor's completion-freshness window must come from the lane's `due_interval_minutes`, never from the group job's cron expression** — deriving it from the schedule collapses a weekly lane sharing a daily tick to a 54h window and reports it permanently stale.
- Owner-facing lanes keep dedicated single-member jobs: each renders a distinct owner message with its own agent prompt and deliver channel. `full_monitor_refresh` stays alone because it is the heavyweight (≤180s) monitor and would block co-tenants.
- Per-lane disable lives in `<hermes_home>/memory-os/system/cron_lane_disabled.json` (owners lost per-job disable granularity to grouping). Honoured by both the tick runner and the monitor.
- Legacy pre-consolidation per-lane jobs are listed in `LEGACY_PER_LANE_CRON_JOBS` and classified `known_optional` / `superseded_by_group_tick`. Onboarding **pauses, never deletes** them — that is the rollback path. `classify_hermes_cron_jobs` exists in three places (`hermes_cron_adapter.py`, `plugins/seam/.../cron_adapter.py`, and an embedded fallback in `memory_os_3_200_monitor.py`); the seam copy is what production reads, so any change must be applied to all three.
- Nothing except `memory_os_owner_cron_onboarding.py` may create Memory-OS cron jobs. `install_memory_os.sh` and `deploy_l3_probe.py --apply` used to create per-lane jobs directly and would double-run a lane that a tick now owns.
- **A raw job count is not a drift signal.** On the production host the 8 registered group jobs appear as **7 enabled + 1 owner-disabled**, alongside the **19 paused** legacy per-lane jobs — 26 Memory-OS entries in total. Always compare against the registry *plus* the enabled/disabled/paused classification, never against the documented job count alone. Reading "26 jobs vs the documented 8" as drift is a false alarm that has already been raised once.
- **A lane being idle is not a lane being broken, and the reverse also holds.** `exposure_rollup` correctly wrote nothing for three days because its upstream `memory_sources.jsonl` gained no rows in that window — its cursor was verified still at the head. Before treating a stale artifact as a defect, check whether *eligible input existed*; before treating a fresh envelope as health, check whether *output was produced*.

The `full` profile adds `module_cadence_report`. On upgraded hosts, active-closure onboarding pauses (does not delete) known optional jobs. The monitor classifies paused optional jobs as known optional rather than unregistered drift.

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
- **Widening a predicate silently changes every counter that shares it.** `_memory_source_has_attribution_gap` has three call sites; era-scoping only the one that drives FAIL left `all_history_attribution_gap_count` (778 → 844) and `rolling_7d_attribution_gap_count` running the newly-wider predicate unannounced. Both turned out to be report-only, so no alert appeared — but that was luck, not design, and it was verified only after the fact. **Before widening any shared predicate, grep every call site and ask of each: does this number feed a WARN/FAIL, and who reads it?** The same sweep found the mirror defect: two new counters were returned by `exposure_monitor_stats` and read by nothing, so the debt they measured existed for no one.

### Definition of Done — Self-Verification Before Push

Before claiming "X is fixed" or pushing, do these in order:

1. **Enumerate sub-items.** "O(1) CLI status" = counts + summaries + continuity_selector + index_health. List them. Verify each one.
2. **Run the counterfactual.** If your fix were absent, would existing tests catch the bug? If not, add the test.
3. **Reverse review.** Read your diff as if you were the reviewer whose job is to find gaps. What did you not touch that looks related? Why?
4. **Run full test suite.** Never push after running only the tests you added or modified.

### Tests Verify "Did", Not "Didn't Miss"

A passing test suite proves that the behaviors you implemented work correctly. It does NOT prove you implemented all necessary behaviors. The only defense against omissions is the self-verification checklist above — tests cannot verify the absence of missing work.
