# Hermes Memory-OS Governance Plan

Date: 2026-06-04

Task start baseline: `dd2b07b788dba4b4dcee3a51189c8d1f32040424`

Current P0 deployed baseline: `799b69d25d4d679e2d38a6d97e2f31c3f361db01`

Purpose: define the governance structure for Memory-OS V1 hardening and future
autonomy work.

## 1. Governance Intent

Memory-OS is allowed to become self-operating only where the action is bounded,
auditable, reversible, and machine-gated. It must not become a silent owner of
Hermes scheduling, Hermes transport, Hindsight storage, high-risk memory
authority, identity, relationship, route/score authority, or external sends.

The product target is:

```text
automatic execution is not black-box
owner review is reserved for irreversible / external / authority-expanding work
low-risk process lanes graduate by evidence
unsafe or stale lanes demote automatically
```

## 2. Current Governance Layers

### ExecutionGate

Purpose: per-execution machine permit.

Applies to:

- heartbeat automatic work;
- Memory-OS cron helper execution;
- SessionMirror bounded apply;
- reversible labels;
- MemoryProjection and advisor automatic writes;
- future low-risk automatic lanes.

Required evidence:

```text
permit_id
lane_id
risk_class
trigger
scope
allowed
boundary=false
expires_at
consumed_at
completion_status
postcheck
```

### StructuralWriteGate

Purpose: prevent unclassified automatic writes.

Applies to:

- JSONL append sites;
- report/advisor/projection writes;
- reversible lane writes;
- future automatic writer surfaces.

Rule:

```text
No new automatic direct JSONL append may land without a classified write surface
and a declared governance path.
```

### ResolverGate

Purpose: validate owner-channel or execution-token authority before apply.

Applies to:

- owner action tokens;
- SessionMirror production apply;
- future owner-gated apply lanes.

Rule:

```text
Self-declared --owner-approved or arbitrary approval_ref is not authority.
```

### OwnerGate

Purpose: permanent human trust boundary.

Always owner-gated:

```text
crystallized memory write
crystallized revoke / demote / delete
identity or relationship write
route / score authority expansion
Hindsight curation apply against the real Hindsight store
third-party or public external send
unbounded autonomous acting
```

### MonitorGate

Purpose: classify runtime evidence and prevent false green closure.

Required monitor distinctions:

```text
production live PASS
clean-host WARN with FAIL=[]
local PASS
deploy PASS
monitor PASS
architecture PASS
```

Monitor-only evidence can prove safety plumbing. It cannot prove a user-visible
owner loop unless the artifact reaches the owner channel or the normal product
surface.

### HostCapabilityGate

Purpose: keep Memory-OS plugin-friendly as Hermes evolves.

Memory-OS should adapt through capability probes and host adapters, not by
forking or taking ownership of host scheduling/transport.

Required host evidence:

```text
host_id
hermes_home_ref
profile_id
deployed_head
deployed_at
cron capability
schema capability
profile capability
memory provider capability
owner channel capability
tool/MCP capability
```

## 3. Current Lane State

### Active Low-Risk Lanes

| Lane | State | Boundary |
| --- | --- | --- |
| `session_mirror_auto_apply` | graduated bounded heartbeat apply | append-only, one bounded scope, no crystallized/Hindsight/route/send |
| `proposal_followup_auto_route` | limited_auto process routing | follow-up/report-only, no apply/policy/send |
| `reversible_labels` | governed automatic lane | TTL/source-scoped append-only label, retract by append-only record |
| `memory_projection` | automatic metadata projection | metadata-only/redacted, StructuralWriteGate-bound |
| `left_brain_advisor` | automatic advisory report | advisor/review surface only |
| `hindsight_governance_suggestions` | report-only / owner-visible suggestion | no Hindsight mutation |

### Active Cron Profile

Default profile:

```text
active-closure
```

Expected active Memory-OS cron jobs:

```text
owner_review_digest
proposal_followups_opsgate
```

Known optional jobs may exist for the `full` profile, but under active-closure
they must be paused or at least monitor-classified if still enabled on an
upgraded host.

## 4. P0 Governance Policy

P0 is mandatory before new lanes or authority work.

### P0 Policy 1 - Evidence Cannot Be False Green

If registry says only active-closure jobs are active but cron still enables
known optional Memory-OS jobs, monitor must surface it.

Required fields:

```text
active_registry_job_count
enabled_memory_os_job_count
enabled_known_optional_outside_active_registry_count
enabled_known_optional_outside_active_registry_jobs
```

### P0 Policy 2 - Permanent Boundary Counters Stay Visible

Every live/deploy monitor must continue to expose high-risk actual-action
counters, even when they are zero.

Required zero surfaces:

```text
unapproved_or_automatic_crystallized_write_count
actual_hindsight_write_count
actual_hindsight_delete_count
actual_route_score_write_count
actual_identity_relationship_write_count
actual_external_send_count
unbounded_autonomous_action_count
```

Owner-approved crystallized writes are tracked separately. They are not a P0
boundary violation when they are backed by an owner-channel action token and
append-only audit evidence.

### P0 Policy 3 - Host Roles Stay Separate

Current role split:

```text
10.20.3.200 = production live closure host
10.20.2.66 = clean-host compatibility / deploy / monitor smoke host
```

Do not describe 2.66 as equivalent production live closure unless a later task
explicitly changes the evidence contract.

## 5. P1 Governance Policy

P1 hardening is about making current governance maintainable.

### P1 Policy 1 - Deep Modules Over Cross-Imports

Governance modules should depend on neutral contracts, not each other:

```text
owner action read model
session mirror contracts
projection paths
capability contracts
lane specs
```

Forbidden pattern:

```text
advisor -> projection -> collectors -> owner_actions -> session_mirror -> owner_actions
```

### P1 Policy 2 - One IO Contract

All automatic JSONL/state writes should move toward a shared IO primitive while
preserving StructuralWriteGate classification.

### P1 Policy 3 - Monitor Is A Product Contract

Monitor classifiers are not debug helpers. They are product safety contracts.

Therefore:

- probe schema must be stable;
- classifier outputs must be tested;
- summary labels must not hide WARN/FAIL cause;
- live and clean-host profiles must not be collapsed.

### P1 Policy 4 - Exceptions Must Become Bounded Evidence

Recoverable errors may degrade or skip work. They must not disappear.

Required error record fields:

```text
code
severity
component
operation
recoverable
details_bounded
created_at
```

Forbidden:

- raw prompt/body content in error records;
- secrets;
- silent pass in live write paths.

## 6. P2 Governance Policy

P2 work improves usability and maintenance after P0/P1 health is stable.

Allowed P2 improvements:

- glossary and concept cleanup;
- neutral monitor CLI naming;
- operator dashboard clarity;
- static debt budgets;
- public-safe tracked summaries;
- clean-host test ergonomics.

P2 work must not expand authority or hide monitor detail.

## 7. Promotion And Demotion Rules

### Low-Risk Lane Promotion

A low-risk lane may graduate only if all are true:

```text
ExecutionGate permit integrity passes
StructuralWriteGate classification passes for automatic writes
Projection/advisor evidence is fresh after deploy or cycle
boundary violation count = 0
forbidden output counters = 0
owner burden does not increase
rollback/demotion path exists
monitor field exists before promotion
```

### Low-Risk Lane Auto-Demotion

Any of the following demotes the lane to gated/report-only:

```text
one boundary violation
one owner disagreement in limited_auto
one missing permit on automatic write
one stale post-deploy artifact used as live evidence
one forbidden output counter > 0
freshness or monitor classification missing
```

### High-Risk Surface Promotion

High-risk surfaces do not inherit low-risk graduation evidence.

Each requires:

```text
separate lane document
owner-channel action token
ResolverGate proof
ExecutionGate proof
append-only audit
rollback or compensation plan
live smoke after explicit authorization
```

## 8. Codex Implementation Governance

Every Codex implementation task must state:

```text
task id
source of truth
owning seam
files expected to change
forbidden files or surfaces
local gates
deploy/live gates
rollback or stop signal
```

Implementation order:

```text
1. read source of truth and current diff
2. write task anchor
3. add or update the narrowest regression test
4. implement the slice
5. run local gates
6. run deploy/live gates only if the task requires and authorization exists
7. update docs/evidence with correct evidence level
```

Do not close by:

- compile-only success;
- skipped tests;
- monitor-only evidence for owner-visible flow;
- local-only evidence for deployed finding;
- green monitor that does not include the field that found the risk;
- disabling a gate to make the result pass.

## 9. Rollback And Stop Rules

### Cron

Rollback:

- active-closure can pause optional jobs;
- full profile can re-enable known optional jobs by explicit profile.

Stop:

- any enabled unknown Memory-OS cron job;
- any active job not wrapped by ExecutionGate;
- optional jobs enabled outside active registry without classification.

### Owner Actions

Rollback:

- append-only compensation or new decision record;
- never delete historical owner actions to hide a bad state.

Stop:

- forged token accepted;
- consumed token reused;
- expired token accepted;
- scope mismatch accepted.

### Projection / Advisor

Rollback:

- archive/ignore stale projection records;
- regenerate fresh projection/advisor artifacts.

Stop:

- raw body included;
- boundary true;
- missing source scope;
- stale artifact used as post-deploy live proof.

### Hindsight

Rollback:

- current allowed state has no real Hindsight mutation.

Stop:

- any real Hindsight write/delete/demote without separate owner-gated lane.

### External Send

Rollback:

- not applicable for current V1 because automatic external send is forbidden.

Stop:

- any `actual_send=true` outside an explicitly authorized external-send lane.

## 10. V1 Governance Exit Criteria

V1 governance is stable when:

```text
P0 tasks are closed
3.200 live monitor PASS WARN=[] FAIL=[]
2.66 clean-host monitor WARN allowed, FAIL=[]
active-closure cron registry and enabled-state are aligned or classified
fast cron probe PASS on both hosts
core import cycle count = 0
write surface unclassified_count = 0
unapproved/automatic high-risk boundary counters remain zero
owner action resolver tests pass
monitor classifier tests pass
```

After this point, Memory-OS can resume low-risk lane work such as bounded mirror
expansion or candidate aggregation. 58 high-risk authority lanes remain closed
until separately designed and reviewed.
