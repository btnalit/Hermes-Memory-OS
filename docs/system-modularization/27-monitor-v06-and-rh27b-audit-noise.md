# 27 - Monitor v0.6 And RH-27b Audit Noise Control

Status: Monitor v0.6 implemented; RH-27b implemented on test host
Scope: 10.20.3.200 test-host first; production-safe defaults remain unchanged

## Purpose

The 10.20.3.200 test host is now running the Memory-OS provider, context
router, DeepReflection, the shell plugin, the heartbeat timer, and the
test-host cognitive loop. The latest read-only monitoring rounds show no hard
boundary failures, but they also show that audit growth is dominated by
heartbeat plumbing rather than meaningful cognitive activity.

This document defines two deliberately separate slices:

1. Monitor v0.6: improve read-only observability first and collect a baseline.
2. RH-27b: reduce heartbeat/decay audit noise without changing cognitive
   behavior.

The execution order matters. Monitor v0.6 must be deployed before RH-27b so
that the project has a before/after baseline for the audit-noise reduction.

## Current Evidence

Read-only inspection on 10.20.3.200 found:

```text
audit_total=2516

recent 250 audit actions:
  runtime_heartbeat       105
  write_working_document  104
  append_event             10
  inner_drive_event_processed 10
  ops_gate_report_written   4
  working_item_expired      3
  digest_daily_written      2
  digest_weekly_written     2
  evidence_scoring_run_written 2
  proposal_queue_candidate_created 2
  self_evolution_dry_run_written 2
  governance_feedback_events_written 2
  cognitive_loop_cycle_completed 2

working/lingering.json:
  total=126
  active=40
  expired=86

heartbeat.timer:
  OnUnitActiveSec=5min

cognitive-loop.timer:
  OnUnitActiveSec=6h
```

Interpretation:

- the cognitive loop is running and is not the main audit-volume source
- working/candidate counts are not currently expanding every monitor round
- the dominant audit volume comes from heartbeat and working-document writes
- most `write_working_document` records are decay-only writes
- this is observability noise, not a boundary violation

## Non-Goals

This slice does not:

- change heartbeat frequency before proving audit-noise reduction
- disable the heartbeat timer
- disable the cognitive-loop timer
- reduce or remove `working_item_expired` audit records
- change event selection, candidate eligibility, RH-12 caps, or source policy
- change DeepReflection source selection
- change context router apply behavior
- write crystallized memory
- send messages
- execute tools/actions
- write identity or relationship records
- export to Hindsight
- mutate 10.20.2.88 or any production/Sannai host

## Step 1 - Monitor v0.6

Monitor v0.6 is read-only. It must not change Memory-OS state or trigger any
runtime cycle.

Implementation status:

- implemented in `scripts/memory_os_3_200_monitor.py`
- locally verified by `tests/scripts/test_memory_os_3_200_monitor.py`
- live verified against 10.20.3.200 with no FAIL findings
- does not change heartbeat or audit write behavior

### New Data To Collect

The monitor should add:

1. Audit action breakdown.

   - total audit count
   - recent-window action distribution, default recent window: 250 records
   - delta action distribution since the previous snapshot
   - `audit_per_new_event`

2. Heartbeat state freshness.

   - read `/root/.hermes/memory-os/runtime/heartbeat_state.json`
   - collect `last_heartbeat_at`
   - collect processed event count if available
   - FAIL if heartbeat service/timer is healthy but `last_heartbeat_at` is
     older than the allowed threshold

3. Working-memory status.

   - per working document:
     - total items
     - active items
     - expired items
     - min/max/average weight
   - no working item body is printed

4. MemorySources attribution distribution.

   - record count
   - route distribution
   - selected heading distribution
   - dropped heading distribution
   - selected source class distribution
   - boundary true count
   - forbidden field count

5. Service last-result checks.

   - heartbeat service `Result` and `ExecMainStatus`
   - cognitive-loop service `Result` and `ExecMainStatus`

### Baseline Gate

After Monitor v0.6 is deployed, collect at least one 6-hour baseline window
before RH-27b is deployed.

Baseline report must include:

- audit delta by action
- heartbeat state freshness
- working active/expired counts
- MemorySources distribution
- hard boundary status

The baseline should not be interpreted as a failure just because
`runtime_heartbeat` and `write_working_document` dominate the audit delta. That
is the condition RH-27b is meant to reduce.

## Step 2 - RH-27b Audit Noise Control

RH-27b changes audit write behavior only. It must preserve runtime behavior.

Implementation status:

- implemented in `plugins/memory/memory_os/runtime.py`,
  `plugins/memory/memory_os/working.py`, and
  `plugins/memory/memory_os/store.py`
- locally verified by `tests/plugins/memory/test_memory_os_runtime.py`
- deployed to 10.20.3.200 through the test-host installer
- controlled heartbeat probe showed `total_delta=0` audit records while
  `heartbeat_state.json` refreshed successfully
- controlled cognitive-loop probe processed 10 events with
  `audit_per_processed_event=3.1`, inside the 3-5 target range
- live monitor remained WARN-only with no FAIL findings after deployment

### Keep Writing State

Every heartbeat, including no-op heartbeats, must continue to update:

```text
/root/.hermes/memory-os/runtime/heartbeat_state.json
```

The state file must contain enough bounded metadata for the monitor to prove
the heartbeat is still running, at minimum:

- `last_heartbeat_at`
- `last_attempt_at`
- `processed_event_count`
- `last_processed_event_id`
- enough existing schema fields to preserve compatibility

Audit is not the heartbeat liveness source after RH-27b. The state file and
systemd service result are.

`last_attempt_at` and `last_heartbeat_at` are intentionally separate:

- `last_attempt_at`: the timer started a heartbeat attempt
- `last_heartbeat_at`: the heartbeat completed successfully

If attempts continue but completed heartbeats become stale, monitor v0.6 should
surface the condition as a heartbeat failure signal.

### Audit Records To Keep

The runtime should continue to audit meaningful state changes:

- `append_event`
- `working_item_added`
- `crystallized_candidate_generated`
- `crystallized_candidate_queued`
- `working_item_expired`
- cognitive-loop cycle completion
- digest writes
- governance feedback writes
- proposal queue writes
- evidence scoring writes
- self-evolution dry-run writes
- DeepReflection report writes
- doctor/index warnings or failures
- heartbeat error summary
- policy skip summary
- cap defer summary

`working_item_expired` stays audited because expiry changes the operational
meaning of a working item.

Heartbeat errors are never no-ops. Any exception while reading events, writing
heartbeat state, syncing the index, or writing working memory must remain
auditable through a bounded error summary.

### Audit Records To Suppress Or Aggregate

Suppress:

- `runtime_heartbeat` when the heartbeat is no-op or decay-only
- generic `write_working_document` records when the only change is decay

Aggregate:

- policy skips within a single heartbeat into one bounded summary record
- cap deferrals within a single heartbeat into one bounded summary record

Do not write one audit record per skipped/deferred event unless a later review
explicitly decides that the volume is acceptable.

### Decay-Only Definition

A heartbeat is decay-only when all of the following are true:

- no new event was processed into Inner Drive
- no new working item was created
- no new candidate was created
- no policy skip/cap defer summary needs to be emitted
- the only write to a working document is item weight decay
- no item crosses from active to expired

If an item expires during decay, the heartbeat is no longer pure decay-only for
audit purposes; keep the `working_item_expired` audit.

### Expiry Traceability

RH-27b does not need to audit every decay step. Expiry traceability is
preserved by the `working_item_expired` audit record plus the current working
document state.

If later debugging needs more detail, add a daily bounded decay summary instead
of reintroducing per-heartbeat write noise.

### Prefetch And RH-29 Policy

Normal prefetch should not write audit records.

RH-29 `memory_sources.jsonl` is the attribution ledger for prefetch selection.
Audit should only record prefetch attribution failures or other operational
errors, not every successful prefetch.

## Success Criteria

RH-27b succeeds only if all of the following are true:

- no hard boundary turns true:
  - `actual_send=false`
  - `actual_execute=false`
  - `actual_identity_write=false`
  - `actual_relationship_write=false`
  - `actual_crystallized_approval=false`
  - `hindsight_exported=false`
- heartbeat state freshness is visible through `heartbeat_state.json`
- heartbeat timer remains active/enabled
- cognitive-loop timer remains active/enabled
- doctor remains `ok` or only has expected warnings
- index remains healthy or catches up without manual mutation
- working/candidate behavior is unchanged except for lower audit volume
- MemorySources forbidden field count remains 0
- `audit_per_new_event` moves toward the target range

Target range:

```text
audit_per_new_event: 3-5
```

This target is a practical operating range, not a reason to hide meaningful
warnings. If real cognitive activity creates more audit records, the monitor
should explain the source rather than blindly suppressing it.

## Before / After Comparison

Required comparison:

```text
T+0h:
  deploy Monitor v0.6 only

T+6h:
  collect baseline audit action delta

T+6h:
  deploy RH-27b audit noise control

T+12h:
  collect post-change audit action delta

Compare:
  runtime_heartbeat delta
  write_working_document delta
  meaningful cognitive-loop action delta
  audit_per_new_event
  boundary booleans
```

Expected result:

- `runtime_heartbeat` should no longer dominate audit deltas
- decay-only `write_working_document` should no longer dominate audit deltas
- meaningful events such as `working_item_expired`, candidate generation, and
  cognitive-loop report writes remain visible
- no monitor FAIL appears

The observation window is event-gated, not only time-gated. A baseline or
post-change comparison is strong enough only after it includes:

- at least 24 heartbeat attempts
- at least one cognitive-loop full cycle
- at least 5 new events

If the event count is too low, extend the observation window rather than
forcing an audit-per-event conclusion from a near-zero denominator.

## Audit Layering

The cognitive loop intentionally keeps two audit layers:

- step-level records, such as digest, governance feedback, proposal queue, and
  DeepReflection reports
- cycle-level records, such as `cognitive_loop_cycle_completed`

These are not considered duplicate noise. Step-level records explain what each
module did; cycle-level records prove the bounded test-host loop completed.
RH-27b targets heartbeat plumbing noise, not this layered cognitive-loop
traceability.

## Rollback

Rollback must be config/code-only and manual.

If RH-27b causes loss of observability or runtime instability:

1. restore the previous audit behavior
2. keep Monitor v0.6
3. run one monitor snapshot
4. compare boundary status and audit deltas

Do not restart production/Sannai gateways as part of this test-host rollback.

## Open Follow-Ups

- If audit volume remains high after RH-27b, consider heartbeat interval
  adjustment as a separate reviewed slice.
- If expiry debugging becomes hard, add a daily decay summary rather than
  per-heartbeat decay audit.
- If MemorySources grows too fast, implement RH-29b retention/archive before
  changing attribution content.
