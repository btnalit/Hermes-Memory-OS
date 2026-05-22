# Memory-OS 10.20.3.200 Monitor

This document records the read-only Codex automation used to watch the
`10.20.3.200` Memory-OS test host after the v0.1 Runtime Hardening and
DeepReflection baseline.

The monitor is an operational smoke check, not a controller. It must not
restart services, run heartbeat catch-up, run cleanup apply, ingest shadow
journals, mutate profile files, or print private bodies.

## Automation

Name:

```text
memory-os-3-200-monitor
```

Schedule:

```text
Every 6 hours
```

Local workspace:

```text
D:\Hermes agent manager\Hermes-Memory-OS
```

Remote target:

```text
ssh hermes-media
```

`hermes-media` is the test host alias for `10.20.3.200`.

## Read-Only Checks

The monitor should collect only metadata and bounded status reports:

```bash
systemctl --user is-active hermes-gateway.service
systemctl --user show hermes-gateway.service -p MainPID --value
systemctl --user is-active hermes-memory-os-heartbeat.timer
systemctl --user is-enabled hermes-memory-os-heartbeat.timer
systemctl --user list-timers hermes-memory-os-heartbeat.timer --no-pager
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes plugins list
HERMES_HOME=/root/.hermes hermes memory_os status
HERMES_HOME=/root/.hermes hermes memory_os doctor
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
HERMES_HOME=/root/.hermes hermes memory_os conversation-regression status-tool-contract
python3 - <<'PY'
# Read /root/.hermes/memory-os/config.json and report only
# context_router.enabled/mode/apply_routes/dry_run_routes/llm_judge_mode.
PY
PYTHONPATH=/root/.hermes/memory-os/runtime/python python3 - <<'PY'
# Run RH-26 apply probes for the seven public validation prompts and report
# only prompt id, context character count, and selected section headings.
# Do not print section bodies or previews.
PY
PYTHONPATH=/root/.hermes/memory-os/runtime/python \
  python3 -m plugins.modules.cognition.deep_reflection status \
  --hermes-home /root/.hermes \
  --profile default
find /root/.hermes/plugins -mindepth 2 -name plugin.yaml \
  | grep -E 'memory_os|memory-os-agent-os' \
  | grep -E 'bak|backup|old|bad' || true
grep -R '"action": "agent_os_shell_session_' /root/.hermes/memory-os/audit \
  | tail -20
du -sh /root/.hermes/memory-os /root/.hermes/system-modules
```

The DeepReflection status command is allowed because it is a local metadata
read. It must not use `run-once`, `apply`, or any command that creates events,
working items, proposals, wandering seeds, sends, executes, identity writes, or
crystallized records.

The plugin-list and shell-alias checks are read-only PS-04 health probes. They
verify that the provider remains provider-selected while the official-style
Agent OS shell is discoverable through Hermes' plugin system.

The hook-marker query is read-only. It may count or show bounded audit metadata
for `agent_os_shell_session_started`, `agent_os_shell_session_reset`, and
`agent_os_shell_session_finalized`, but it must not trigger `/new`, invoke
hooks, or create new audit entries.

The RH-26 apply probe is read-only. It may call `build_prefetch` locally and
report which section headings would be present for the public validation
prompts. It must not print selected section bodies, previews, raw event
summaries, private transcript text, or prompt-expanded context.

## Expected Healthy Snapshot

A normal monitor pass should be treated as PASS when:

- `hermes-gateway.service` is `active`
- `hermes-memory-os-heartbeat.timer` is `active` and `enabled`
- heartbeat timer appears in `systemctl --user list-timers`
- `hermes memory` reports active provider `memory_os`
- `hermes plugins list` reports `memory-os-agent-os` as `enabled`
- `hermes plugins list` reports `memory_os` as `not enabled` as a general
  plugin
- `hermes memory-os-agent-os status` delegates successfully
- `hermes memory-os-agent-os doctor` has `status=ok`
- `memory_os status` reports `prefetch_mode=indexed`
- `memory_os doctor` has `status=ok`
- the only expected doctor warning is `hindsight_adapter_disabled`
- `status-tool-contract` validation is `ok`
- `context_router` config matches the intended test-host mode
- RH-26 apply probes show expected section headings for the seven public
  validation prompts
- no backup-looking Memory-OS provider/shell plugin manifests are present under
  `$HERMES_HOME/plugins/`
- DeepReflection reports `mode=auto_bounded` on the test host
- DeepReflection boundary booleans remain false:
  - `actual_send=false`
  - `actual_execute=false`
  - `actual_identity_write=false`
  - `actual_crystallized_approval=false`

WARN conditions:

- index health is temporarily `stale`
- the doctor shows non-destructive warnings other than
  `hindsight_adapter_disabled`
- DeepReflection source-class distribution remains skewed to one class
  for observation only
- shell hook marker counts do not change for a long period despite real
  session resets; this can indicate that Hermes hook dispatch is not reaching
  the shell, but it is not an automatic recovery condition
- RH-26 casual continuity probes return empty context on a host that lacks clean
  casual carryover; this is a review signal, not a hard failure
- disk usage grows unexpectedly but no hard limit is crossed
- a simple `is-active` service probe reports inactive, but a follow-up
  `systemctl --user show` probe reports `LoadState=loaded`,
  `ActiveState=active`, and `UnitFileState=enabled`; this should be recorded as
  a monitor-probe discrepancy before treating it as a runtime failure

FAIL conditions:

- gateway inactive
- heartbeat timer inactive or disabled
- heartbeat timer is active but absent from `list-timers`
- active memory provider is not `memory_os`
- `memory-os-agent-os` is missing or not enabled in `hermes plugins list`
- `memory_os` appears enabled as a general plugin
- `memory-os-agent-os` status or doctor alias fails
- doctor returns an error
- status tool contract validation fails
- RH-26 apply probes select mechanism-heavy sections for casual prompts or
  include background sections for cancellation/continue prompts
- backup-looking Memory-OS provider/shell plugin manifests exist under
  `$HERMES_HOME/plugins/`
- any boundary boolean becomes true
- crystallized records increase without an explicit owner approval gate
- monitor output contains private bodies, raw transcripts, prompts, secrets, or
  tokens

## Latest Manual Baseline

The latest manual monitor-equivalent snapshot after RH-22/RH-23/RH-24
deployment:

```json
{
  "gateway_active": "active",
  "gateway_pid": "436233",
  "heartbeat_timer_active": "active",
  "heartbeat_timer_enabled": "enabled",
  "heartbeat_timer_listed": true,
  "memory_provider": "memory_os",
  "plugins": {
    "memory-os-agent-os": "enabled user plugin",
    "memory_os": "not enabled general plugin"
  },
  "memory_status": {
    "events": 24,
    "working_items": 17,
    "crystallized_candidates": 17,
    "crystallized_records": 0,
    "audit_entries": 322,
    "prefetch_mode": "indexed",
    "index_health": "healthy",
    "hindsight_adapter_enabled": false
  },
  "doctor": {
    "status": "ok",
    "exit_code": 0,
    "expected_warning": "hindsight_adapter_disabled"
  },
  "shell_alias": {
    "status": "ok",
    "doctor": "ok"
  },
  "status_tool_contract": {
    "validation": "ok"
  },
  "deep_reflection": {
    "mode": "auto_bounded",
    "current": true,
    "latest_selected_by_source_class": {
      "working": 2
    },
    "latest_dropped_by_source_class": {
      "working": 1
    },
    "rolling_selected_by_source_class": {
      "working": 14
    },
    "rolling_dropped_by_source_class": {
      "working": 7
    }
  },
  "plugin_scan_tree": {
    "memory_os_backup_manifest_under_plugins": false,
    "memory_os_agent_os_backup_manifest_under_plugins": false
  },
  "agent_os_shell_hooks": {
    "markers_seen": [
      "agent_os_shell_session_started",
      "agent_os_shell_session_reset",
      "agent_os_shell_session_finalized"
    ],
    "audit_only": true
  }
}
```

## Latest Automation Snapshot And Recheck

Automation snapshot:

```text
automation: memory-os-3-200-monitor
run_time_utc: 2026-05-21T23:37:47Z
host: debian
```

Automation-reported PASS:

```text
provider=memory_os
memory_os status index_health=healthy
prefetch_mode=indexed
hindsight_adapter_enabled=false
doctor.status=ok
status-tool-contract.validation.status=ok
DeepReflection enabled=true
DeepReflection injection_mode=auto_bounded
disk /root/.hermes/memory-os use=25%
```

Automation-reported WARN:

```text
hermes-gateway.service inactive, PID=0
hermes-memory-os-heartbeat.timer inactive, enabled state empty/unstable
hindsight_adapter_disabled expected warning
```

Automation counts:

```text
audit_entries=742
events=52
working_items=45
queue_backlog=0
```

Manual read-only recheck after the automation snapshot:

```text
recheck_time_remote: 2026-05-21T21:27:06-04:00
gateway: LoadState=loaded, ActiveState=active, SubState=running,
         UnitFileState=enabled, MainPID=440371
heartbeat timer: LoadState=loaded, ActiveState=active, SubState=waiting,
                 UnitFileState=enabled
provider/plugin split: memory-os-agent-os enabled, memory_os not enabled as a
                       general plugin
doctor: status=ok, expected hindsight_adapter_disabled warning only
status-tool-contract: validation.status=ok, findings=[]
disk: 25%, 174G/754G
```

Manual recheck counts:

```text
audit_entries=792
events=54
working_items=47
crystallized_candidates=47
crystallized_records=0
queue_backlog=0
index_health=healthy
index_counts.audit_entries=791
```

DeepReflection manual recheck:

```json
{
  "enabled": true,
  "injection_mode": "auto_bounded",
  "latest_injection_source_classes": {
    "selected_by_source_class": {"working": 2},
    "dropped_by_source_class": {"working": 1},
    "selected_total": 2,
    "dropped_total": 1
  },
  "rolling_injection_source_classes": {
    "window_report_count": 7,
    "selected_by_source_class": {"working": 14},
    "dropped_by_source_class": {"working": 7},
    "selected_total": 14,
    "dropped_total": 7
  },
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_crystallized_approval": false
}
```

Interpretation:

- Memory-OS grew between snapshots without queue backlog:
  `events +2`, `working_items +2`, and `audit_entries +50` from the automation
  snapshot to the manual recheck.
- `crystallized_records` remained `0`.
- DeepReflection remained safe but still source-class skewed to `working`.
- The gateway/timer WARN was not reproduced by the richer manual systemd
  recheck. If this repeats, the monitor should collect `LoadState`,
  `FragmentPath`, and `UnitFileState` before final FAIL classification.

## Optimization Decision Signals

These signals decide when to revisit currently deferred enhancement choices.
They are tracking inputs, not automatic triggers.

### DeepReflection Working Updates

Current state:

```text
working_updates_enabled=false
```

Keep it disabled while:

- DeepReflection cards come only from `working`
- source-class skew remains unexplained
- RH-22 real-conversation regression has not been rerun after a behavior change

Consider an owner-reviewed canary only after:

- `actual_send=false`, `actual_execute=false`, `actual_identity_write=false`,
  and `actual_crystallized_approval=false` remain stable over multiple monitor
  windows
- queue backlog stays `0`
- `doctor.status=ok`
- source-class distribution includes more than only `working`, or the
  working-only skew is explained by data rather than selector bias
- the canary writes are capped and separately visible in status/doctor

Track:

- working item growth rate per day
- how many working items are created by heartbeat versus DeepReflection
- whether working items from mirrored/governance sources affect ordinary chat
  tone

### LLM Internal Analysis Canary

Current state:

```text
llm_enabled=false
```

Do not enable until deterministic DeepReflection has enough baseline data.

Track before deciding:

- repeated rejected/dropped deterministic cards caused by weak synthesis
- owner-visible cases where deterministic analysis misses obvious continuity
- RH-22 and status-tool-contract stability
- instruction-like filter rejection rate
- whether LLM judge availability would fail closed cleanly

Canary requirement:

- local-only or test-host-only
- no direct injection without the same deterministic post-filters
- no working updates, sends, executes, identity writes, or crystallized approval
  from LLM output

### Carryover Budget / `max_chars_total`

Current position:

```text
do not expand until real conversation regression stays clean
```

Track:

- selected card count
- dropped card count
- drop reasons by budget versus safety filter
- ordinary conversation tone regressions
- mechanism label leakage
- candidate/crystallized wording mistakes

Consider a small budget increase only if:

- useful cards are repeatedly dropped only because of budget
- RH-22 full prompt set stays clean
- Telegram smoke tests remain natural
- no diagnostic/report style leaks into ordinary chat

### Source-Class Diversity / RH-25

Current baseline:

```text
selected=working:14
dropped=working:7
window_report_count=7
```

Track:

- selected and dropped cards by `foreground`, `digest`, `governance`, `cron`,
  `state_source`, and `working`
- whether digest/governance data exists but is never selected
- whether source-class filtering is too strict or source ingestion is missing

Decision rule:

- do not tune diversity from the first seven windows
- collect at least 1-2 weeks of distribution data
- propose a separate RH item before changing ranking, caps, or minimum slots

### Audit Retention / RH-17 Follow-Up

Current observation:

```text
audit_entries grew from 742 to 792 between automation snapshot and manual
recheck while events grew from 52 to 54
```

Track:

- audit entries per day
- audit entries per event
- shell hook marker count
- monitor-generated audit count, if any
- disk usage of `/root/.hermes/memory-os`

Decision rule:

- no audit deletion by default
- if audit growth becomes noisy, design dry-run archive/compaction first
- hook markers should remain audit-only and should not become events/working
  items/candidates

### Service And Monitor Reliability

Track:

- automation `is-active` result
- direct `systemctl --user show` state
- `FragmentPath`
- `UnitFileState`
- gateway `MainPID`
- timer `list-timers` visibility

Decision rule:

- if automation repeatedly reports inactive/not-found while direct recheck
  reports loaded/active/enabled, improve the monitor probe before treating it
  as runtime instability
- if both automation and direct recheck show inactive/disabled, treat it as a
  real runtime WARN/FAIL and ask owner before recovery

## Boundaries

The monitor is not allowed to:

- restart `hermes-gateway.service`
- run `hermes memory_os heartbeat`
- run cleanup apply
- run shadow journal apply
- run DeepReflection `run-once`
- invoke session hooks or force `/new`
- inspect raw private sessions or prompts
- export to Hindsight
- mutate `10.20.2.88` or any production/Sannai host

If a FAIL condition appears, the monitor should report it and stop. Recovery
actions remain manual and owner-approved.
