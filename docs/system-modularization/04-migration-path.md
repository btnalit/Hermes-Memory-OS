# Migration Path

Date: 2026-05-20

## Position

This is not a production migration plan. It is a path for turning production
behavior into portable modules and proving them on `10.20.3.200`.

Production cutover is a later gate.

Sannai private systems are not migration targets in this plan. They are
compatibility constraints only.

## Stages

### Stage 1: Private Source Snapshot

Allowed:

- read-only `ssh`, `rsync`, or `scp` from `10.20.2.88`
- copy source files and non-secret config needed for analysis
- keep snapshots outside this public repo

Not allowed:

- no production file writes
- no gateway restart
- no cron change
- no raw session/private memory body in GitHub

Output:

- public module map
- private source notes
- list of hidden dependencies

### Stage 2: Contract Extraction

For each subsystem, define:

- manifest
- dependencies
- profile config
- state roots
- read interfaces
- write interfaces
- schedules
- delivery mode
- status/doctor checks

Output:

- module skeleton
- synthetic fixtures
- tests against public interfaces

### Stage 3: Test Host Install

Install the module on `10.20.3.200` with:

```text
enabled=false or no-send=true by default
profile-local config only
Memory-OS as canonical memory
Hindsight disabled unless explicitly mocked
```

Output:

- status evidence
- doctor evidence
- no-send run evidence
- weekly observation entry

### Stage 4: Shadow Comparison

Compare module output against production-like behavior without writing back to
production.

Examples:

- generated digest shape
- candidate counts
- gate decisions
- status warnings
- runtime digest freshness
- private-profile compatibility checks

Rules:

- comparisons use metadata and redacted summaries
- shadow approvals never become production approvals
- shadow candidates never affect production CW-019
- Sannai private state remains outside public module migration

### Stage 5: Production Gate Draft

Only after `10.20.3.200` proves stability:

- write a dedicated production gate document
- define quiet window needs, if any
- define rollback
- define backup and restore
- define exact one-module cutover
- get owner approval

## Rollback Model

Module disable must be enough for test-host rollback:

```text
disable schedule/hook
keep data
keep audit
keep Memory-OS files
restore previous provider/config only if that was changed
```

Production rollback is not exercised in v0.1 because production cutover is out
of scope.

## Data Rules

Code can be upgraded or removed. Data is preserved.

Default uninstall:

- removes module registration
- stops schedules/hooks
- leaves state and Memory-OS records intact

Data cleanup requires a separate dry-run-first cleanup plan.

## Quiet Window Rule

Quiet windows are not required for the v0.1 test-host work.

They become relevant only for future production migration when a final
consistent snapshot is needed. At that stage:

- pause the affected production schedules/gateway path after owner approval
- export the final snapshot
- verify source hashes are stable
- resume production
- write a production audit event

This rule is documented now to avoid confusing shadow validation with final
production migration.

## Production Non-Interference

During v0.1:

- `10.20.2.88` is evidence-only
- `10.20.3.200` is the integration host
- public GitHub receives reusable code and redacted docs only
- private snapshots stay local
