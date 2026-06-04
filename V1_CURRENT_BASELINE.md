# Memory-OS V1 Current Baseline And P0 Evidence

Date: 2026-06-04

Task start code head: `dd2b07b788dba4b4dcee3a51189c8d1f32040424`

Current P0 deployed code head: `799b69d25d4d679e2d38a6d97e2f31c3f361db01`

Purpose: keep the current V1 stabilization baseline visible in a tracked,
public-safe file so future implementation work does not rely only on ignored
internal evidence or local-only audit notes.

## Source Documents

- `CODEX_TASKS.md`
- `TECH_DEBT_REPORT.md`
- `V1_STABILIZATION_PLAN.md`
- `HERMES_GOVERNANCE_PLAN.md`
- `docs/internal-memory-os/00-control/54-58-host-capability-projection-autonomy-roadmap-20260603.md`

## Host Roles

| Host | Role | Evidence Level |
| --- | --- | --- |
| `10.20.3.200` / `hermes-media` | production live closure host | live PASS required |
| `10.20.2.66` / `hermes-feiniu` | clean-host compatibility / deploy / monitor smoke | WARN allowed, `FAIL=[]` required |

Do not describe `10.20.2.66` as production-equivalent live closure unless a
later task explicitly changes the evidence contract.

## Active Cron Profile

Current default profile:

```text
active-closure
```

Expected active Memory-OS registry jobs:

```text
owner_review_digest
proposal_followups_opsgate
```

Known optional Memory-OS cron jobs may exist on upgraded hosts. Under
`active-closure`, they must either be paused by onboarding or surfaced by the
monitor as `enabled_known_optional_outside_active_registry_*`.

## Permanent High-Risk Boundaries

Current P0/P1 work must not open these surfaces:

```text
crystallized memory write without owner gate
Hindsight retain / delete / demote apply against the real store
route / score authority write
identity / relationship write
external send
unbounded autonomous acting
```

Low-risk lanes may only remain live when their forbidden-output counters stay
zero and monitor/owner-action sentinels continue to fail on boundary expansion.

## P0-001 Baseline And Gate Freeze

Status: closed locally by this tracked baseline file.

This file records:

- task start code head;
- host roles;
- active-closure cron profile;
- permanent high-risk boundaries;
- local gates;
- dual-host evidence.

Forbidden done signal avoided: evidence is no longer available only in ignored
internal docs.

## P0-002 Active-Closure Cron Enabled-State Consistency

Status: implemented, deployed, and validated.

New monitor fields:

```text
active_registry_job_count
enabled_memory_os_job_count
enabled_known_optional_outside_active_registry_count
enabled_known_optional_outside_active_registry_jobs
```

Classification contract:

- production/live profile: active registry outside optional enabled jobs are
  production FAIL via `fail_if_production`;
- clean-host profile: the same condition is a classified WARN, not a silent
  PASS and not `clean_host_warn_unclassified`.

Live evidence:

```text
10.20.3.200:
  code_head=799b69d25d4d679e2d38a6d97e2f31c3f361db01
  monitor_profile=live
  status=PASS
  WARN=[]
  FAIL=[]

10.20.2.66:
  code_head=799b69d25d4d679e2d38a6d97e2f31c3f361db01
  active-closure onboarding=already_configured
  monitor_profile=clean-host
  status=WARN
  FAIL=[]
  WARN does not include enabled optional Memory-OS cron jobs after onboarding.
```

Read-only cron state observed during this task:

```text
10.20.3.200 registry:
  owner_review_digest
  proposal_followups_opsgate

10.20.3.200 enabled Memory-OS jobs:
  memory-os-owner-review-digest
  memory-os-proposal-followups-opsgate

10.20.2.66 registry:
  owner_review_digest
  proposal_followups_opsgate

10.20.2.66 clean-host state:
  legacy optional Memory-OS jobs were paused by active-closure onboarding:
    memory-os-right-brain-expression
    memory-os-module-cadence-report
    memory-os-right-brain-expression-outcome
    memory-os-expression-feedback-request
    memory-os-memory-sources-feedback-request
```

No cron jobs were deleted to make checks pass.

Fast cron probe evidence after deployment and 2.66 onboarding:

```text
python scripts\memory_os_cron_adapter_probe.py --hermes-home /root/.hermes --hermes-bin hermes --output json

10.20.3.200:
  status=ok
  active_registry_job_count=2
  enabled_memory_os_job_count=2
  enabled_known_optional_outside_active_registry_count=0
  memory_os_owned_expected_count=2
  memory_os_owned_wrapped_count=2
  memory_os_owned_naked_count=0

10.20.2.66:
  status=ok
  active_registry_job_count=2
  enabled_memory_os_job_count=2
  enabled_known_optional_outside_active_registry_count=0
  memory_os_owned_expected_count=2
  memory_os_owned_wrapped_count=2
  memory_os_owned_naked_count=0
```

## P0-003 Permanent Boundary Regression Sentinels

Status: implemented and validated.

Regression coverage now includes:

- monitor-level sentinel for low-risk lanes that report actual execute, policy
  write, send, identity write, route/score live apply, unapproved
  crystallized write, or cognitive-loop boundary true;
- owner-action sentinel for Hindsight curation decisions proving
  `actual_hindsight_write/delete/demote=false`, `actual_route_score_write=false`,
  `actual_send=false`, and `advisory_only=true`.

## P0-004 Dual-Host Evidence Refresh

Status: refreshed for this task.

Local / integration gates:

```text
python -m pytest -q tests\scripts\test_memory_os_3_200_monitor.py tests\plugins\memory\test_memory_os_hermes_cron_adapter.py tests\scripts\test_memory_os_cron_adapter_probe.py tests\plugins\memory\test_memory_os_owner_actions.py
  -> 210 passed

python -m pytest -q
  -> 992 passed

python scripts\memory_os_write_surface_check.py
  -> status=pass, surface_count=99, unclassified_count=0

python scripts\memory_os_static_hygiene_check.py --repo-root .
  -> status=pass

git diff --check
  -> PASS
```

Live / clean-host gates:

```text
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
  -> PASS, WARN=[], FAIL=[]

python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output summary
  -> WARN, FAIL=[]
```

Current full monitor caveat:

- full monitor remains valid evidence, but it is heavy enough that future audit
  slices should run fast probes first;
- `memory_os_cron_adapter_probe.py` is the current fast cron probe;
- a separate fast boundary/runtime probe remains open in `CODEX_TASKS.md`.

## Current Residual P1/P2 Work

The following remain open and should be handled after P0:

- shared JSONL/state IO contract;
- core import-cycle check and neutral read models;
- owner action module split;
- monitor modularization;
- install/deploy profile single source;
- exception/error record contract;
- cognitive loop step registry;
- clean-host focused test runner hygiene.
- fast boundary/runtime probes and monitor performance budget.
