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
- disk usage grows unexpectedly but no hard limit is crossed

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
