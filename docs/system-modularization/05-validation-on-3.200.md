# Validation On 10.20.3.200

Date: 2026-05-20

## Purpose

`10.20.3.200` is the staging host for proving that a blank Hermes machine can
install Memory-OS plus higher-level modules without inheriting production-only
assumptions.

## Baseline

Required before module validation:

```bash
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes memory_os status
HERMES_HOME=/root/.hermes hermes memory_os doctor
systemctl --user status hermes-memory-os-heartbeat.timer --no-pager
```

Expected:

- provider is `memory_os`
- canonical store is `/root/.hermes/memory-os`
- Hindsight is optional adapter only
- doctor has no errors
- index health is healthy
- heartbeat is active when runtime integration is enabled

## Module Validation Template

For each module:

```text
1. install module
2. run status
3. run doctor
4. run one dry-run or no-send cycle
5. inspect Memory-OS events/audit/working/candidate outputs
6. verify no outbound delivery occurred
7. record evidence in an observation report
```

Every module slice also follows:

```text
extract
  read production/reference evidence and write public module contract

implement
  build module against the contract with local tests

integrate
  install on 10.20.3.200, run no-send validation, and record evidence
```

## Global No-Send Rule

All expression-capable modules must default to no-send.

Applies to:

- mailbox
- Wandering Mind
- Self-Evolution reports
- Speak Gate

Sannai-specific behaviors are not installed as public modules during this
validation plan. Any private compatibility adapter would need a separate
owner-approved gate.

Allowed output in v0.1:

```text
events
working memory
crystallized candidates
audit
would-send records
local status reports
```

Disallowed output in v0.1 without explicit owner approval:

```text
Telegram send
mailbox send
production Hindsight write
identity write
approved crystallized record write
production config write
production gateway restart
```

## Validation Gates

### Gate A: Module Installs

Pass if:

- manifest is discoverable
- dependency checks are deterministic
- status/doctor run without private body output
- disabling the module leaves no active schedule/hook

### Gate B: Module Runs No-Send

Pass if:

- run writes only allowed Memory-OS surfaces
- `would-send` is audit-only
- repeated run is idempotent or intentionally appends a new event
- doctor stays clean after the run

### Gate C: Integrated Suite

Pass if:

- Memory-OS heartbeat, inner-drive, wandering, evidence, and speak gate can
  coexist on the test profile
- module dependencies are visible from status
- failure in one module does not corrupt Memory-OS canonical files
- disabling one module stops its schedules/hooks without deleting data

### Gate D: Sannai Compatibility

Sannai is not installed as a public module, but modules must prove they can
coexist with a Sannai-shaped private profile boundary.

Pass if:

- running a module in the main profile does not change a sibling
  `sannai-shape` fixture profile
- enabling a module in a `sannai-shape` fixture keeps all expression paths in
  `would_send` mode
- identity fixture hashes such as `SOUL.md` remain unchanged after module runs
- module status and doctor never print private fixture bodies
- no module requires Sannai-private files to start

### Gate E: Concurrency

Pass if:

- two scheduled modules contending for the same resource use
  ScheduleCoordinator locks
- at least one module succeeds or both defer cleanly
- failed lock acquisition records `lock_contention_count`
- no partial Memory-OS write is produced after lock contention
- doctor reports contention without treating a clean defer as corruption

### Gate F: Uninstall Data Protection

Pass if:

- install module, run it, then uninstall it
- module registration and schedules/hooks are removed
- profile data, Memory-OS records, audit, candidates, and working state remain
  intact
- reinstall can read preserved module data
- destructive data cleanup requires a separate dry-run-first plan

## Observation Report

Weekly report path:

```text
docs/memory-os/observation-10.20.3.200-YYYY-WW.md
```

Record:

- module versions
- enabled modules
- status summary
- doctor summary
- event count trend
- working item trend
- candidate count trend
- audit count trend
- no-send delivery count
- failures and follow-up slices

Do not record raw private bodies.

## First Practical Sequence

Recommended sequence after this plan:

```text
1. Keep Memory-OS v0 observation running.
2. Implement module manifest/lifecycle scaffold locally.
3. Install scaffold on 10.20.3.200.
4. Port mailbox as no-send/status-first module.
5. Port household_digest as local context module.
6. Port Wandering Mind with Memory-OS bounded read view.
7. Enable generic inner-drive runtime on the test profile only.
8. Port governance/evidence modules as one reviewed subsystem.
9. Port Speak Gate after governance outputs exist.
```

This keeps the test host useful without making production migration the hidden
main task.
