# Memory-OS Codex Tasks

Date: 2026-06-04

Task start baseline: `dd2b07b788dba4b4dcee3a51189c8d1f32040424`

Current P0 deployed baseline: `b4ae2c548f4440af00067a8b422bdcedd4a8dd25`

Purpose: turn the second-round stability audit into executable Codex work.

Source of truth:

- `TECH_DEBT_REPORT.md`
- `V1_STABILIZATION_PLAN.md`
- `HERMES_GOVERNANCE_PLAN.md`
- `V1_CURRENT_BASELINE.md`
- `docs/internal-memory-os/00-control/54-58-host-capability-projection-autonomy-roadmap-20260603.md`

Current P0 status:

- P0-001 baseline summary is tracked in `V1_CURRENT_BASELINE.md`.
- P0-002 cron enabled-state consistency is implemented, pushed, deployed to
  3.200/2.66, and 2.66 active-closure onboarding has paused known optional
  Memory-OS cron jobs.
- P0-003 permanent boundary sentinels are implemented and tested.
- P0-004 dual-host evidence was refreshed after deployment.
- P0-005 fast probe now has cron and boundary/runtime probe entrypoints, both
  live-validated on 3.200 and 2.66, and both are wired into
  `deploy_memory_os.py` postcheck/apply sequencing. Remaining follow-up is
  full-monitor performance optimization, not deploy sequencing.

## 0. Execution Rules For Codex

Every task below must follow the same closure rule:

```text
Do not close a task with weaker evidence than the evidence that found it.
```

Before implementation, Codex must record a task-local anchor:

```yaml
anchor:
  purpose: "<why this slice matters>"
  significance: routine | strategic
  goal: "<machine-checkable outcome>"
  acceptance_gates: ["<commands, live monitor checks, or schema checks>"]
  forbidden_done_signals: ["<weak signals that do not count>"]
```

Default constraints:

- Do not open 58 high-risk authority lanes.
- Do not write, delete, demote, or retain real Hindsight records.
- Do not write crystallized memory.
- Do not change route/score authority.
- Do not write identity or relationship state.
- Do not send external messages.
- Do not restart Hermes gateways unless the user separately authorizes that scope.
- Do not delete cron jobs to make checks pass; pause/disable through the declared onboarding path.

Evidence levels must be named explicitly:

```text
local PASS
integration PASS
deploy PASS
monitor PASS
live PASS
clean-host WARN with FAIL=[]
```

## 1. P0 Required Work

P0 tasks are blockers before new autonomy or authority work. They repair current
measurement and deployment consistency so later changes are not built on a false
green state.

### P0-001 - Baseline And Gate Freeze

Owner seam: roadmap / release-visible documentation / validation gates

Problem:

- Internal docs are ignored by Git.
- The current stable baseline is spread across local audit docs, ignored
  internal evidence docs, and live monitor output.

Goal:

- Preserve a current tracked baseline that future Codex tasks can read without
  relying only on ignored internal documents.

Implementation:

1. Add or update a tracked current-baseline summary.
2. Include:
   - code head;
   - active hosts and evidence roles;
   - active-closure cron profile;
   - current enabled low-risk lanes;
   - explicitly closed high-risk surfaces;
   - current required validation commands.
3. Link ignored internal evidence docs as supporting evidence, not the only
   source of truth.

Acceptance gates:

```text
git status --short --branch
python -m pytest -q
python scripts\memory_os_static_hygiene_check.py
python scripts\memory_os_write_surface_check.py
```

Forbidden done signals:

- "Docs updated" without listing the current baseline head.
- Evidence available only in ignored files.

### P0-002 - Active-Closure Cron Enabled-State Consistency

Owner seam: Hermes cron adapter / onboarding / monitor

Problem:

- 10.20.2.66 previously had active-closure registry with 2 Memory-OS jobs, but
  all 7 known Memory-OS cron jobs remained enabled.
- Monitor previously proved the active registry jobs were wrapped, but did not
  flag enabled known optional jobs outside the active registry.

Goal:

- The monitor must detect this state, and upgraded hosts must converge optional
  Memory-OS jobs to paused when the selected profile is `active-closure`.

Implementation:

1. Add monitor fields:
   - `enabled_known_optional_outside_active_registry_count`
   - `enabled_known_optional_outside_active_registry_jobs`
   - `active_registry_job_count`
   - `enabled_memory_os_job_count`
2. Classification:
   - production/live profile: FAIL unless a deliberate full profile is active;
   - clean-host profile: WARN, classified, `FAIL=[]`.
3. Add tests:
   - registry has 2 active jobs and optional jobs enabled -> classified
     WARN/FAIL;
   - registry has 2 active jobs and optional jobs paused -> PASS;
   - full profile has 7 expected wrapped jobs -> PASS.
4. Run active-closure onboarding on 2.66 only when that deployment/apply step is
   explicitly authorized.

Acceptance gates:

```text
python -m pytest -q tests\scripts\test_memory_os_3_200_monitor.py tests\scripts\test_memory_os_owner_cron_onboarding.py tests\scripts\test_memory_os_cron_adapter_probe.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output json
```

Closure:

- 3.200: active registry count matches enabled Memory-OS jobs for
  `active-closure`.
- 2.66: optional jobs are paused by active-closure onboarding, or monitor emits
  a classified clean-host WARN naming them.

Current closure evidence:

```text
3.200 deployed_head=b4ae2c548f4440af00067a8b422bdcedd4a8dd25
3.200 cron_adapter_probe status=ok active_registry_job_count=2 enabled_memory_os_job_count=2 enabled_known_optional_outside_active_registry_count=0
3.200 live monitor PASS WARN=[] FAIL=[]

2.66 deployed_head=b4ae2c548f4440af00067a8b422bdcedd4a8dd25
2.66 active-closure onboarding already_configured; known optional Memory-OS jobs paused
2.66 cron_adapter_probe status=ok active_registry_job_count=2 enabled_memory_os_job_count=2 enabled_known_optional_outside_active_registry_count=0
2.66 clean-host monitor WARN FAIL=[]
```

Forbidden done signals:

- Only checking registry count.
- Only checking wrapper count.
- Treating `memory_os_known_optional` classification as proof that enabled
  optional jobs are harmless.

### P0-003 - Permanent Boundary Regression Sentinels

Owner seam: StructuralWriteGate / monitor / owner action resolver

Problem:

- The project now has several low-risk automatic lanes. A future task could
  accidentally treat low-risk graduation as authority expansion.

Goal:

- Every validation run continues to prove that high-risk surfaces are closed.

Implementation:

1. Keep monitor fields for:
   - crystallized writes;
   - Hindsight writes/deletes/demotions;
   - route/score authority writes;
   - identity/relationship writes;
   - external sends;
   - unbounded autonomous acting.
2. Add a compact regression test that fails if any current low-risk lane reports
   a high-risk actual action.
3. Ensure any new low-risk lane declares forbidden outputs and monitor fields
   before implementation.

Acceptance gates:

```text
python -m pytest -q tests\plugins\memory tests\scripts\test_memory_os_3_200_monitor.py
python scripts\memory_os_write_surface_check.py
```

Forbidden done signals:

- Passing unit tests without monitor fields.
- Allowing a lane to claim safety by convention rather than by explicit
  forbidden-output counters.

### P0-004 - Current Dual-Host Evidence Refresh

Owner seam: deploy smoke / monitor evidence

Problem:

- 3.200 and 2.66 have different roles. A single "PASS" summary hides whether a
  result is production-live or clean-host compatibility.

Goal:

- Every P0/P1 slice must record the two-host status in the correct evidence
  level.

Implementation:

1. For docs-only tasks, state that no live evidence was refreshed.
2. For deploy/runtime tasks, collect:
   - 3.200 live monitor;
   - 2.66 clean-host monitor;
   - deployed head from both hosts;
   - any classified WARN list.
3. Do not claim 2.66 production-equivalent closure unless a later task
   explicitly changes that role.

Acceptance gates:

```text
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output json
```

Forbidden done signals:

- "Dual-host PASS" without separating production-live from clean-host WARN.
- Local tests as a substitute for a deployed finding.

### P0-005 - Fast Probe And Monitor Performance Budget

Owner seam: monitor / deploy smoke / scheduler evidence

Problem:

- Full monitor remains valid, but it is too heavy to be the only audit loop.
- Recent live runs took roughly two minutes on 3.200 and could exceed three
  minutes on 2.66.
- Scheduler/cron regressions should be caught by a small probe before invoking
  the full monitor.

Goal:

- Establish a fast-probe layer that can be run on every deploy/audit slice
  before the full monitor.

Current fast probes:

```text
python scripts\memory_os_cron_adapter_probe.py --hermes-home /root/.hermes --hermes-bin hermes --output json
python scripts\memory_os_boundary_runtime_probe.py --hermes-home /root/.hermes --output json
```

Required follow-up:

1. Keep `memory_os_cron_adapter_probe.py` as the fast cron/registry/wrapper
   probe.
2. Keep `memory_os_boundary_runtime_probe.py` as the fast boundary/runtime
   probe for permanent high-risk counters and ExecutionGate/StructuralWriteGate
   health.
3. `deploy_memory_os.py` postcheck/apply must run both probes before the full
   monitor path and classify either probe failure as deploy failure.
4. Monitor performance budget:
   - fast probe target: seconds-scale, P0/P1 deploy smoke should use this
     first;
   - full production monitor target: return within 180 seconds;
   - clean-host full monitor target: return within 240 seconds;
   - a full monitor timeout is a monitor-performance finding until the fast
     probes show runtime boundary or cron state failure.
5. Use full monitor after fast probes for live runtime closure, broad monitor
   changes, scheduler behavior changes, or any finding originally discovered by
   full monitor.

Acceptance gates:

```text
python scripts\memory_os_cron_adapter_probe.py --hermes-home /root/.hermes --hermes-bin hermes --output json
python scripts\memory_os_boundary_runtime_probe.py --hermes-home /root/.hermes --output json
python scripts\deploy_memory_os.py --phase postcheck --profile upgrade --mode operational --hindsight auto --hermes-home /root/.hermes --output json
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output summary
```

Forbidden done signals:

- Treating a fast probe as a replacement for live monitor when the finding came
  from full monitor.
- Treating a slow full monitor timeout as proof that the underlying runtime is
  broken without a smaller probe.

## 2. P1 Hardening Work

P1 tasks reduce fragility in the current architecture. They should be executed
as vertical slices with behavior-preserving tests.

### P1-001 - Shared JSONL And State IO Contract

Owner seam: persistence/write surface

Problem:

- `_read_jsonl`, `_append_jsonl`, and `_write_jsonl` are implemented many times.

Goal:

- Create one shared IO contract for Memory-OS JSONL/state files without
  weakening StructuralWriteGate classification.

Implementation:

1. Add `plugins.memory.memory_os.jsonl_io` or equivalent.
2. Support:
   - bounded JSONL read;
   - append with parent creation;
   - atomic JSON write;
   - latest-record read;
   - malformed-line handling;
   - optional quarantine/error record.
3. Migrate report-only modules first.
4. Migrate critical writer paths only after tests prove no write-surface
   regression.

Current slice:

- `plugins.memory.memory_os.jsonl_io` exists with `read_jsonl`,
  `latest_jsonl_record`, `append_jsonl`, `write_jsonl`, and
  `write_json_atomic`.
- First report-only migrations are limited to `imagination_loop` and
  `symbolic_offloader`.
- Critical owner/session/projection paths are intentionally untouched in this
  slice.

Acceptance gates:

```text
python -m pytest -q tests\scripts\test_memory_os_write_surface_check.py tests\plugins\memory
python scripts\memory_os_write_surface_check.py
python scripts\memory_os_static_hygiene_check.py
```

Stop signal:

- Any migration causes `unclassified_count > 0`.

### P1-002 - Break Core Import Cycle

Owner seam: module boundaries / read models

Problem:

Current detected cycle:

```text
left_brain_advisor
-> memory_projection
-> signal_collectors
-> owner_actions
-> session_mirror
-> owner_actions
```

Goal:

- Core Memory-OS modules import without cycles.

Current slice:

- Added `scripts/memory_os_import_cycle_check.py`.
- Added neutral `read_model_paths.py` for owner action and SessionMirror apply
  ledger paths.
- Removed the core cycle through `signal_collectors` and `session_mirror`;
  current check reports `cycle_count=0`.

Implementation:

1. Add neutral path/read-model modules:
   - `owner_action_read_model.py`
   - `session_mirror_contracts.py`
   - `projection_paths.py`
2. Make collectors depend on neutral readers, not full owner action state
   machine.
3. Make `owner_actions` read advisor/projection output through neutral report
   readers.
4. Add an import-cycle check script and test.

Acceptance gates:

```text
python -m pytest -q tests\plugins\memory\test_memory_os_owner_actions.py tests\plugins\memory\test_memory_os_session_mirror.py tests\scripts\test_memory_os_3_200_monitor.py
python scripts\memory_os_import_cycle_check.py
```

Stop signal:

- Fix depends on function-local imports that only hide the cycle.

### P1-003 - Owner Action Module Split

Owner seam: owner review / resolver / action ledger

Problem:

- `owner_actions.py` is a 6000+ line god module.

Goal:

- Preserve behavior while separating token resolution, digest surface, state
  transitions, ledgers, policy adapters, and Hindsight curation decisions.

Implementation order:

1. Extract token parser/resolver.
2. Extract ledger read/write helpers.
3. Extract owner review read model and digest surface.
4. Extract state machine.
5. Extract policy apply adapters.
6. Extract Hindsight curation decision ledger.
7. Keep `owner_actions.py` as a compatibility facade during the split.

Acceptance gates:

```text
python -m pytest -q tests\plugins\memory\test_memory_os_owner_actions.py
python -m pytest -q tests\system_modularization\test_memory_os_agent_os_shell.py
python scripts\memory_os_write_surface_check.py
```

Stop signal:

- Any high-risk owner action changes behavior during extraction.

### P1-004 - Monitor Modularization

Owner seam: monitor / remote probe / classifier schema

Problem:

- `scripts/memory_os_3_200_monitor.py` mixes SSH probe, embedded remote script,
  snapshot schema, classifiers, and output rendering.

Goal:

- Keep the public CLI compatible while separating probe, snapshot, classifiers,
  and renderer.

Implementation:

1. Add neutral `scripts/memory_os_monitor.py`.
2. Keep `memory_os_3_200_monitor.py` as compatibility wrapper.
3. Move remote probe into a module that accepts `hermes_home`.
4. Move classifiers into focused classifier modules.
5. Preserve JSON output schema.

Acceptance gates:

```text
python -m pytest -q tests\scripts\test_memory_os_3_200_monitor.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output json
```

Stop signal:

- A monitor refactor changes PASS/WARN/FAIL semantics without an explicit test.

### P1-005 - Install/Deploy Profile Single Source

Owner seam: installer / deploy / onboarding config

Problem:

- Defaults such as `owner_cron_profile=active-closure` appear in shell,
  Python, onboarding, deploy, README, and docs.

Goal:

- One profile resolver owns install/deploy/onboarding defaults.

Implementation:

1. Add a Python `InstallProfile` or JSON schema.
2. Shell installer calls Python resolver rather than duplicating defaults.
3. Deploy wrapper accepts explicit `--owner-cron-profile`.
4. Add snapshot tests for operational/test/full profiles.

Acceptance gates:

```text
python -m pytest -q tests\scripts\test_memory_os_plugin_install.py tests\scripts\test_memory_os_deploy.py tests\scripts\test_memory_os_owner_cron_onboarding.py
rg -n "/ 7 jobs|seven-node|historical seven" README.md docs scripts
```

Stop signal:

- Adding another hardcoded default to make one path pass.

### P1-006 - Exception And Error Record Contract

Owner seam: runtime degradation / logging / monitor

Problem:

- Broad `except Exception` handlers are common and not all have monitor-visible
  error records.

Goal:

- Recoverable errors remain bounded, but silent suppression becomes visible.

Implementation:

1. Define `MemoryOSErrorRecord`.
2. Convert runtime, projection, session mirror, prefetch, and monitor-sensitive
   catches to emit bounded error records.
3. Add monitor fields:
   - `suppressed_error_count`
   - `degraded_component_count`
   - recent bounded error codes.
4. Keep raw bodies/secrets out of error records.

Acceptance gates:

```text
python -m pytest -q tests\plugins\memory tests\scripts\test_memory_os_3_200_monitor.py
python scripts\memory_os_static_hygiene_check.py
```

Stop signal:

- Error records include raw prompt/body/secret content.

### P1-007 - Cognitive Loop Step Registry

Owner seam: cognitive loop / monitor required-step proof

Problem:

- The cognitive loop is a fixed 29-step list without a declarative step
  contract.

Goal:

- Required/optional/profile-specific step status is registry-derived and cannot
  be lost by serializer changes.

Implementation:

1. Add `CognitiveStepSpec` registry.
2. Each step declares:
   - `step_id`
   - required/optional;
   - profile condition;
   - dependency;
   - failure policy;
   - monitor code.
3. Monitor derives required steps from registry.

Acceptance gates:

```text
python -m pytest -q tests\plugins\memory\test_memory_os_cognitive_loop*.py tests\scripts\test_memory_os_3_200_monitor.py
```

Stop signal:

- Required step lists remain duplicated between runner and monitor.

### P1-008 - Clean-Host Test Runner Hygiene

Owner seam: deployment verification

Problem:

- 2.66 does not have pytest, so clean-host verification relies on deploy smoke,
  cognitive loop, and monitor.

Goal:

- Provide a portable way to run focused tests on clean hosts without polluting
  system Python.

Implementation:

1. Add a deployable test-runner option using a project-local venv or bundled
   lightweight dependency cache.
2. Keep it opt-in.
3. Do not require system package installation by default.

Acceptance gates:

```text
python -m pytest -q tests\scripts\test_memory_os_deploy.py
```

Live acceptance only if authorized:

```text
focused pytest or equivalent smoke runs on 10.20.2.66
```

Stop signal:

- Modifying global Python packages on clean-host by default.

## 3. P2 Optimization Work

P2 tasks improve maintainability and operator ergonomics after P0/P1 are under
control.

### P2-001 - Terminology And Glossary Cleanup

Goal:

- Reduce confusion among OpsGate, ExecutionGate, ResolverGate, StructuralWriteGate,
  LeftBrainPipelineCheck, LeftBrainAdvisor, MemoryProjection, and Hindsight
  governance.

Acceptance gates:

```text
rg -n "OpsGate|ExecutionGate|LeftBrainPipelineCheck|LeftBrainAdvisor" README.md docs plugins scripts
```

Output:

- A tracked glossary section or document.
- Monitor summaries use current product names; historical lane names remain only
  in evidence notes.

### P2-002 - Monitor Dashboard Operator View

Goal:

- Show P0/P1 gate state in one operator-facing snapshot:
  - production live status;
  - clean-host WARN state;
  - active cron profile;
  - optional enabled outside registry count;
  - high-risk boundary counters;
  - active low-risk lane status.

Acceptance gates:

```text
python -m pytest -q tests\scripts\test_memory_os_monitor_dashboard_snapshot.py
```

### P2-003 - Documentation Tracking Strategy

Goal:

- Keep internal ignored evidence useful without making GitHub main lose the
  current story.

Options:

- track concise public-safe summaries;
- keep detailed internal evidence ignored;
- add an evidence index with hashes and local paths.

Acceptance gates:

```text
git status --short --branch
```

### P2-004 - Neutral Monitor Naming

Goal:

- Migrate daily use from `memory_os_3_200_monitor.py` to neutral
  `memory_os_monitor.py` while preserving compatibility.

Acceptance gates:

```text
python scripts\memory_os_monitor.py --host hermes-media --monitor-profile live --output json
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json
```

### P2-005 - Static Debt Budget

Goal:

- Track large files, duplicate helpers, broad exceptions, and import cycles as
  bounded debt budgets.

Acceptance gates:

```text
python scripts\memory_os_static_hygiene_check.py
```

Suggested budgets after P1:

- `owner_actions.py` under 2500 lines or facade-only.
- monitor compatibility wrapper under 500 lines.
- core import cycle count = 0.
- unclassified write surfaces = 0.

## 4. Recommended Execution Order

```text
P0-001 Baseline And Gate Freeze
P0-002 Active-Closure Cron Enabled-State Consistency
P0-003 Permanent Boundary Regression Sentinels
P0-004 Current Dual-Host Evidence Refresh
P1-001 Shared JSONL And State IO Contract
P1-002 Break Core Import Cycle
P1-003 Owner Action Module Split
P1-004 Monitor Modularization
P1-005 Install/Deploy Profile Single Source
P1-006 Exception And Error Record Contract
P1-007 Cognitive Loop Step Registry
P1-008 Clean-Host Test Runner Hygiene
P2 items after P0/P1 health is green
```

## 5. Codex Handoff Template

Use this template when starting each implementation thread:

```text
Task:
  id:
  source_of_truth:
  owning_seam:
  exact_goal:
  files_expected:
  forbidden_changes:
  local_gates:
  live_gates:
  rollback_or_stop:
```

No task is complete until the result states:

```text
changed files
tests run
monitor/live evidence if applicable
residual risk
whether docs were tracked or internal-only
```
