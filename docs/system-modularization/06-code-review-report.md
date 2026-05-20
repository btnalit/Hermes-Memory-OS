# Memory-OS v0.1 Module Code Review Report

Review ID: MOS-V01-CODE-REVIEW-001
Date: 2026-05-20
Scope: `cf24f0f..65283d6`
Current HEAD: `65283d6 Add would-send speak gate module`
Review mode: local code-level review before Claude review and 10.20.3.200 full plugin deployment test

## Verdict

PASS for Claude review, not yet PASS for deployment.

No blocking code-level issue was found in the v0.1 modularization slice. The reviewed code keeps the intended boundaries:

- no real outbound delivery
- no production host mutation
- no identity writes
- no automatic crystallized approval
- no direct self-modification
- no real gateway restart or service operation

This review does not replace the next gate: full deployment and integrated runtime validation on `10.20.3.200`.

Post-review note: Claude's meta-review requested stronger evidence before deployment. This report now includes an evidence appendix and the codebase includes a legacy import idempotency fix plus local integrated trace tests. These additions are intended to strengthen the pre-deployment review package; they still do not replace the `10.20.3.200` host-level deployment gate.

## Reviewed Commits

```text
65283d6 Add would-send speak gate module
0b89e6c Add dry-run self-evolution governor
fa3ce66 Add explainable evidence scoring module
34eb730 Add local proposal queue module
1a0425a Add report-only ops gate module
4d48df6 Add portable module baseline
```

## Reviewed Areas

System scaffold:

- `plugins/system/contracts.py`
- `plugins/system/bus.py`
- `plugins/system/scheduler.py`
- `plugins/system/lifecycle.py`

Portable modules:

- `plugins/modules/messaging/mailbox.py`
- `plugins/modules/context/household_digest.py`
- `plugins/modules/cognition/wandering_mind.py`
- `plugins/modules/cognition/inner_drive.py`
- `plugins/modules/governance/ops_gate.py`
- `plugins/modules/governance/proposal_queue.py`
- `plugins/modules/evidence/scoring.py`
- `plugins/modules/governance/self_evolution.py`
- `plugins/modules/expression/speak_gate.py`

Tests:

- `tests/system_modularization/*`

Docs:

- `docs/system-modularization/*`
- `docs/memory-os/v0.1-module-map.md`
- `docs/memory-os/v0.1-observation-and-integration-plan.md`
- `README.md`

## Findings

No unresolved P0/P1/P2 blocking findings.

One review finding was accepted and fixed during evidence hardening:

- `ProposalQueueModule.import_legacy_candidate()` is now idempotent for repeated legacy imports. A repeated import returns the existing candidate, writes a skipped-import audit entry, and does not append a duplicate queue item.

## Boundary Checks

### Outbound Delivery

PASS.

`mailbox`, `wandering_mind`, and `speak_gate` only write would-send artifacts. Reviewed paths consistently report `actual_send: false`.

`ModuleLifecycle.enable()` refuses `delivery_mode="send"` unless explicitly passed `allow_send=True`, and module doctors still report real send as an error for v0.1.

### Production Mutation

PASS.

Global risk search did not find real execution paths such as:

- `subprocess`
- `systemctl`
- `requests`
- `socket`
- broad destructive filesystem calls

`OpsGateModule` blocks production-like targets including:

- `10.20.2.88`
- `/vol1/.hermes`
- `/root/.hermes`
- `gateway.service`

### Identity Protection

PASS.

No reviewed module writes identity source files. Sannai-shaped fixture tests assert that private identity fixture hashes do not change.

### Crystallized Approval Boundary

PASS.

`ProposalQueueModule` maps owner decisions only to proposal queue states. Even `approve` becomes `approved_for_proposal`, while `crystallized_approved` remains `false`.

`InnerDriveRuntimeModule` may create crystallized candidates, but it does not approve or materialize crystallized records.

### Self-Evolution Boundary

PASS.

`SelfEvolutionGovernorModule` is dry-run/report-only. It writes a local digest/report, sends proposed action intent through Ops-Gate, and creates a proposal only through Proposal Queue when Ops-Gate returns `would_allow`.

It does not directly edit code, config, identity, gateways, or production files.

### Sannai Compatibility

PASS for current local test scope.

Each module family has a Sannai-shaped fixture test that checks non-mutation of the private fixture surface. This validates the intended compatibility constraint: Sannai is not extracted as a module target, but the modules must not break or assume her private structure.

## Residual Risks

These are not blockers for Claude review, but should remain explicit before 10.20.3.200 deployment.

1. The review is local and code-level only. It proves boundaries in code and tests, not runtime deployment behavior on `10.20.3.200`.
2. ModuleBus v0.1 is an append/read JSONL coordination log. It does not yet provide a blocking subscription API; modules that need coordination must poll/read the log or use lifecycle/scheduler calls.
3. The local integrated trace tests prove the vertical code path, but not service installation, config discovery, host permissions, or gateway interaction on `10.20.3.200`.

## Claude Meta-Review Appendix

This appendix addresses the eight evidence requests from Claude's meta-review.

### 1. Risk Search Method

Method: grep-style static search with `rg`, plus manual line-level review of all module and scaffold files. This is not a full AST import/data-flow analyzer.

Risk search command:

```powershell
rg -n "actual_send\s*[:=]\s*True|subprocess|systemctl|requests|socket|shutil|rmtree|unlink\(|Remove-Item|rm -rf|10\.20\.2\.88|/vol1|/root/\.hermes|telegram_send|mailbox_send|identity_write|crystallized_approved\s*[:=]\s*True|approved_for_crystallized" plugins\modules plugins\system tests\system_modularization
```

Write-surface review command:

```powershell
rg -n "write_text|\.open\(|append_audit|append_candidate_queue|create_candidate|transition\(|actual_send|would_send|delivery_mode" plugins\modules plugins\system
```

Result: the only destructive-looking file operation found in the reviewed scaffold was `path.unlink()` inside `ScheduleCoordinator.release_lock()`, scoped to profile-local lock files under `system-modules/locks`. No network client, process execution, service restart, or production mutation path was found in reviewed module code.

### 2. Module Acceptance Samples

The following samples were generated locally from a temporary Memory-OS root with synthetic events. Bodies and private content are omitted.

| Module | Status sample | Doctor sample | Run-once / action sample |
| --- | --- | --- | --- |
| `mailbox` | `delivery_mode=no-send` | warning `mailbox_root_missing` on empty fixture | `hermes.delivery_would_send.v0`, `actual_send=false` |
| `household_digest` | artifact path exists after run | `status=ok`, `event_count=3` | `hermes.household_digest_result.v0`, `event_count=3` |
| `wandering_mind` | `delivery_mode=no-send` | `status=ok` with digest/events | `would_send=true`, `actual_send=false` |
| `inner_drive` | `event_count=3`, `processed_event_count=0` before run | `status=ok` | `processed_event_count=3`, candidates written, `actual_send=false` |
| `ops_gate` | `actual_execute=false` | warning before first report | blocked sample production send, `actual_execute=false` |
| `proposal_queue` | `candidate_count=1`, `delivery_mode=no-send` | warning `pending_candidates_present` | candidate state `candidate`, `crystallized_approved=false` |
| `evidence_scoring` | `score_count=0` before run | warning before scoring | `score_count=10`, `actual_approve=false`, `self_evolution_triggered=false` |
| `self_evolution` | `direct_self_modify=false`, `actual_execute=false` | warning before digest | dry-run creates proposal through queue, `direct_self_modify=false`, `actual_execute=false` |
| `speak_gate` | `delivery_mode=would-send`, `actual_send=false` | `status=ok` | `decision=would_send`, `actual_send=false` |

### 3. ModuleBus And ScheduleCoordinator Evidence

Tests:

- `test_module_bus_persists_profile_local_events_without_private_bodies`
- `test_schedule_coordinator_uses_ttl_locks_and_reports_contention`
- `test_lifecycle_installs_manifest_and_reports_disabled_status`
- `test_lifecycle_enable_and_disable_are_profile_local`

Coverage:

- `ModuleBus.publish()` writes `module.discovered` and `module.health_changed` style events.
- `ModuleBus.read_events(profile=...)` returns profile-local events and avoids private body fields.
- `ScheduleCoordinator.acquire_lock()` allows the first holder, reports contention for a second holder, and replaces expired locks.
- Crash recovery is represented by TTL expiry and `expired_replaced`; there is no separate process monitor in v0.1.

### 4. End-To-End Trace Tests

Local integrated trace tests now exist:

- `test_integrated_user_message_trace_stays_reviewed_and_no_send`
- `test_integrated_wandering_mind_trace_routes_expression_through_speak_gate`

These tests cover:

- event stream -> household digest -> inner drive -> evidence scoring -> self-evolution proposal -> proposal queue owner approval -> speak gate would-send decision
- household digest -> Wandering Mind output -> Speak Gate expression decision

They are local integration tests. The later `10.20.3.200` gate must still validate install/enable/status/doctor and runtime behavior on the blank Hermes host.

### 5. Sannai Fixture Content

The Sannai-shaped fixture is synthetic, not production private data. It includes:

- `SOUL.md`
- `memories/MEMORY.md`
- `memories/USER.md`
- external state root with `diary.md`
- `self_memory.md`
- `lingering_thoughts.json`
- `quiet_moments.jsonl`
- `heartbeat_lingering_candidates.jsonl`
- `digests/daily/2026-05-20.md`

Fixture builder:

- `plugins/memory/memory_os/fixtures.py::build_sannai_multi_root_fixture`

Compatibility tests assert:

- private fixture `SOUL.md` mtime/hash surface is unchanged
- no `system-modules` directory is created under the Sannai-shaped private root
- module actions remain scoped to the main/test profile root

Covered module families:

- household digest
- Wandering Mind
- Inner Drive
- Ops-Gate
- Proposal Queue
- Evidence / Scoring
- Self-Evolution
- Speak Gate

Mailbox has no direct Sannai fixture test because v0.1 mailbox has no Memory-OS store dependency and only writes profile-local would-send records; lifecycle profile-locality covers the shared scaffold.

### 6. Schema Compatibility Implementation

Implemented:

- manifest-level `memory_os_compat` parsing
- min/max Memory-OS version checks
- readable schema-version checks
- lifecycle doctor error on incompatible Memory-OS version
- lifecycle doctor warning for unknown readable schema versions
- enable refusal when compatibility has errors

Tests:

- `test_module_manifest_parses_lifecycle_and_memory_os_compatibility`
- `test_module_manifest_reports_incompatible_memory_os_version`
- `test_module_manifest_reports_read_only_for_unknown_schema_versions`
- `test_lifecycle_doctor_reports_schema_incompatibility`

Not implemented in v0.1:

- automatic owner alert on Memory-OS upgrade
- automatic module re-check daemon

Those require a host-level runtime supervisor and belong to the `10.20.3.200` deployment gate or a later runtime slice.

### 7. Wandering Mind And Speak Gate Decision

Decision: Option C, Speak Gate passthrough for Wandering Mind.

Meaning:

- Wandering Mind remains an L2 cognition module that can produce `[SILENT]` or a right-brain output artifact.
- Wandering Mind may record a local no-send/would-send candidate artifact for observability, but that artifact is not external delivery.
- Any expression that leaves the cognition layer must pass through `SpeakGateModule.evaluate_wandering_output()`.
- `[SILENT]` remains a true no-send result.
- Non-silent Wandering Mind output can become a Speak Gate `would_send` decision, still with `actual_send=false` in v0.1.

Evidence:

- `test_speak_gate_keeps_wandering_mind_non_task`
- `test_integrated_wandering_mind_trace_routes_expression_through_speak_gate`

### 8. Import Idempotency Decision

Decision: fix now.

Implemented behavior:

- legacy imports compute a stable `legacy_import_key`
- repeated imports with the same legacy source/identity return the existing candidate
- the queue length does not grow on repeated import
- first import writes `proposal_queue_legacy_candidate_imported`
- repeated import writes `proposal_queue_legacy_candidate_import_skipped`

Regression test:

- `test_proposal_queue_legacy_import_is_idempotent`

## Verification Evidence

Original verification commands run after the Slice 32 commit:

```text
python -m pytest tests\system_modularization -q
65 passed in 2.77s
```

Fresh verification commands run after the Claude meta-review hardening patch:

```text
python -m pytest tests\system_modularization\test_integrated_module_traces.py tests\system_modularization\test_proposal_queue_module.py -q
9 passed in 1.71s
```

```text
python -m pytest tests\system_modularization -q
68 passed in 3.77s
```

```text
python -m compileall -q agent plugins scripts
exit 0
```

```text
python -m pytest -q
175 passed in 12.64s
```

```text
git diff --check
exit 0
```

Pre-commit workspace check after hardening:

```text
git status --short
 M plugins/modules/governance/proposal_queue.py
 M tests/system_modularization/test_proposal_queue_module.py
?? docs/system-modularization/06-code-review-report.md
?? tests/system_modularization/test_integrated_module_traces.py
```

## Next Gate

Recommended next step:

1. Claude reviews this report plus the v0.1 module diff.
2. If Claude finds no blocker, prepare a 10.20.3.200 full plugin deployment plan.
3. Deploy on `10.20.3.200` only.
4. Validate install/enable/status/doctor for all modules.
5. Run integrated no-send flow before enabling any live expression path.

Production `10.20.2.88` remains out of scope for this gate.
