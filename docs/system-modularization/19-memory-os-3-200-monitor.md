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

The automation should call the deterministic read-only monitor script:

```powershell
python scripts/memory_os_3_200_monitor.py `
  --host hermes-media `
  --previous-json C:\Users\btnal\.codex\automations\memory-os-3-200-monitor\last-snapshot.json `
  --snapshot-out C:\Users\btnal\.codex\automations\memory-os-3-200-monitor\last-snapshot.json `
  --output summary
```

The script should collect only metadata and bounded status reports:

```bash
systemctl --user is-active hermes-gateway.service
systemctl --user show hermes-gateway.service -p MainPID --value
systemctl --user show hermes-memory-os-heartbeat.timer \
  -p LoadState -p ActiveState -p SubState -p UnitFileState \
  -p Result -p ExecMainStatus --no-pager
systemctl --user show hermes-memory-os-heartbeat.service \
  -p LoadState -p ActiveState -p SubState -p UnitFileState \
  -p Result -p ExecMainStatus --no-pager
systemctl --user list-timers hermes-memory-os-heartbeat.timer --no-pager
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes plugins list
PYTHONPATH=/root/.hermes/memory-os/runtime/python:/root/.hermes/plugins \
  HERMES_HOME=/root/.hermes python3 -m plugins.memory.memory_os status
PYTHONPATH=/root/.hermes/memory-os/runtime/python:/root/.hermes/plugins \
  HERMES_HOME=/root/.hermes python3 -m plugins.memory.memory_os doctor
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
hermes memory-os-agent-os status
hermes memory-os-agent-os doctor
hermes memory-os-agent-os memory-sources stats --hours 24
hermes memory-os-agent-os metadata-retention
hermes memory-os-agent-os low-clue-recall dry-run \
  --query "继续昨天那个。" \
  --llm-judge none
hermes memory-os-agent-os eval rh31 run \
  --fixture synthetic \
  --adapter all \
  --no-write-report
PYTHONPATH=/root/.hermes/memory-os/runtime/python:/root/.hermes/plugins \
  HERMES_HOME=/root/.hermes python3 -m plugins.memory.memory_os \
  conversation-regression status-tool-contract
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
journalctl --user -u hermes-gateway.service --since "6 hours ago" --no-pager -o cat
python3 - <<'PY'
# Read /root/.hermes/memory-os/audit/write_audit.jsonl and report only
# action-count metadata: total count, recent-window action distribution,
# and action deltas since the previous local snapshot.
PY
python3 - <<'PY'
# Read /root/.hermes/memory-os/runtime/heartbeat_state.json and report
# only liveness metadata: last_heartbeat_at, freshness, processed count,
# and last processed event id.
PY
python3 - <<'PY'
# Read /root/.hermes/memory-os/working/*.json and report only item counts,
# active/expired status counts, and bounded weight statistics.
# Do not print working item bodies.
PY
du -sh /root/.hermes/memory-os /root/.hermes/system-modules
```

The DeepReflection status command is allowed because it is a local metadata
read. It must not use `run-once`, `apply`, or any command that creates events,
working items, proposals, wandering seeds, sends, executes, identity writes, or
crystallized records.

The plugin-list and shell-alias checks are read-only PS-04 health probes. They
verify that the provider remains provider-selected while the official-style
Agent OS shell is discoverable through Hermes' plugin system.

The shell-alias probe must include the natural operator path without
`HERMES_HOME`. The shell plugin is expected to infer the default Hermes home
from its installed plugin path. If this fails, the shell is not usable even if
provider commands work with an explicit environment variable.

The hook-marker query is read-only. It may count or show bounded audit metadata
for `agent_os_shell_session_started`, `agent_os_shell_session_reset`, and
`agent_os_shell_session_finalized`, but it must not trigger `/new`, invoke
hooks, or create new audit entries.

The RH-26 apply probe is read-only. It may call `build_prefetch` locally and
report which section headings would be present for the public validation
prompts. It must not print selected section bodies, previews, raw event
summaries, private transcript text, or prompt-expanded context.

The v0.6 monitor tracks trend signals that can support future decisions:

- count deltas since the previous snapshot:
  - `audit_entries`
  - `events`
  - `working_items`
  - `crystallized_candidates`
  - `crystallized_records`
- `audit_entries_per_new_event`
- audit action breakdown:
  - total audit count
  - recent-window action distribution
  - action deltas since the previous snapshot
- heartbeat state freshness from `heartbeat_state.json`
- working-memory status:
  - per document total items
  - active / expired counts
  - min / max / average weight
- shell hook marker totals for started/reset/finalized markers
- gateway compaction count in the last six hours
- `focus=None` count in compression logs
- RH-26 section-heading anomalies
- Memory Sources record count, file size, route distribution, selected
  source-class distribution, selected/dropped heading distribution, boundary
  true count, and forbidden field findings
- RH-31 eval no-write probe:
  - `schema_version`
  - status (`pass` / `warning` / `fail`)
  - adapter count
  - case count
  - score count
  - failure count
  - failure-class distribution
  - boundary true count
  - forbidden field count
  - source-class distribution
  - no report directory written during monitor smoke
  - full per-score details are stripped before local snapshot write; use the
    explicit RH-31 CLI for score-level review
- RH-28 low-clue recall config and a bounded probe summary:
  - deterministic decision
  - candidate count
  - configured judge mode
  - report-only judge status when enabled
  - `ok`, `no_clear_match`, `no_match`, and `no_selection` all mean the judge
    adapter was reachable; only unavailable/error states should become judge
    availability warnings
  - report-only judge availability warning when the adapter degrades to
    deterministic fallback
  - no candidate labels or private bodies in monitor output
- RH-28f low-clue ingress matrix:
  - `继续昨天那个。`
  - `继续刚才那个`
  - `继续刚才那个。`
  - `继续当前任务`
  - `continue the deferred task`
  - `继续搁置的任务`
  - reports only route, expected route, section headings, and character count
- DeepReflection source-class skew
- heartbeat/cognitive-loop service last `Result` and `ExecMainStatus`

The previous snapshot is local to the Codex automation directory. It is not
written to the remote Hermes host and does not contain private bodies.

## Decision Gates Supported By The Monitor

The monitor supports promotion decisions, but it is not itself the decision
maker. Promotion gates are defined in
`29-memory-os-module-integration-contract.md`.

Current monitor-supported gates:

- core runtime can advance only when gateway, heartbeat, doctor, index,
  status-tool contract, and shell alias checks have no FAIL
- RH-27b audit-noise control can advance when the post-change window includes
  at least 24 heartbeats and at least 5 new events, with
  `audit_entries_per_new_event` near the 3-5 target range
- RH-26/RH-28 ingress and context routing can advance only when the RH-26
  heading probes and RH-28f low-clue ingress matrix match expected routes and
  headings
- RH-29 MemorySources can advance only when `boundary_true_count=0`,
  forbidden-field findings are empty, and ledger growth remains explainable
- RH-30 feedback can be collected immediately, but it must not become a strong
  ranking signal until enough explicit owner feedback exists
- RH-31 eval harness can advance only when the no-write monitor probe returns
  `memory-os.rh31_summary.v0`, boundary true count is 0, forbidden field count
  is 0, and any adapter failures are treated as scorecard findings rather than
  runtime failures
- LLM judge report-only mode can remain enabled while deterministic fallback is
  active; bounded-live use requires a separate future gate
- RH-31/RH-32/RH-33 must first fill the module declaration in the 29号 contract
  and add any missing monitor fields before implementation

## Expected Healthy Snapshot

A normal monitor pass should be treated as PASS when:

- `hermes-gateway.service` is `active`
- `hermes-memory-os-heartbeat.timer` is `active` and `enabled`
- heartbeat timer appears in `systemctl --user list-timers`
- `heartbeat_state.json` exists and has a fresh `last_heartbeat_at`
- `hermes memory` reports active provider `memory_os`
- `hermes plugins list` reports `memory-os-agent-os` as `enabled`
- `hermes plugins list` reports `memory_os` as `not enabled` as a general
  plugin
- `hermes memory-os-agent-os status` delegates successfully
- `hermes memory-os-agent-os doctor` has `status=ok`
- `hermes memory-os-agent-os status` and `doctor` also work without an
  explicit `HERMES_HOME` when the shell is installed under the default Hermes
  home
- `hermes memory-os-agent-os memory-sources stats --hours 24` also works
  without an explicit `HERMES_HOME`
- `hermes memory-os-agent-os modules status` also works without an explicit
  `HERMES_HOME`, proving the shell plugin exposes the provider module operator
  entrypoint
- `memory_os status` reports `prefetch_mode=indexed`
- `memory_os doctor` has `status=ok`
- the only expected doctor warning is `hindsight_adapter_disabled`
- `status-tool-contract` validation is `ok`
- `context_router` config matches the intended test-host mode
- if RH-28 report-only judge is enabled, status/doctor expose judge
  availability and the monitor reports `low_clue_llm_judge_available`
- RH-28f ingress probes route broad deictic recall phrases to
  `ambiguous_recall` with `Recall Clarification Guard`, while explicit current
  or deferred task phrases remain `foreground_control` with
  `Current Foreground Task`
- RH-28h ingress probes confirm `Recall Clarification Guard` includes the
  tool-aware contract that prevents raw `session_search` or other tool results
  from creating a competing unclustered shortlist
- RH-28i low-clue recall probes report `internal_label_count=0`, proving that
  internal route or projection names are not exposed as candidate titles
- RH-28j title normalization preserves distinctive entity terms in low-clue
  candidate labels; this is covered by regression tests rather than raw monitor
  title output
- RH-26 apply probes show expected section headings for the seven public
  validation prompts
- count deltas are present after the first script-backed run
- audit action deltas are present after the first script-backed run
- working active/expired status counts are present
- gateway compaction and `focus=None` counts are reported as bounded integers
- no backup-looking Memory-OS provider/shell plugin manifests are present under
  `$HERMES_HOME/plugins/`
- DeepReflection reports `mode=auto_bounded` on the test host
- DeepReflection boundary booleans remain false:
  - `actual_send=false`
  - `actual_execute=false`
  - `actual_identity_write=false`
  - `actual_crystallized_approval=false`
- Memory Sources reports schema `memory-os.memory_sources_stats.v0`,
  `boundary_true_count=0`, no forbidden field findings, feedback count,
  feedback rating distribution, and feedback ledger size

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
- `focus=None` appears in compression logs; this confirms the known Hermes
  automatic compression focus gap remains
- audit growth per new event is high enough to warrant review, but no boundary
  violation appears
- RH-28 report-only judge is configured but unavailable; this is a warning
  only when deterministic fallback remains active and status/doctor otherwise
  stay healthy
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
- `memory-os-agent-os` status or doctor only works with explicit
  `HERMES_HOME` but fails through the natural operator command
- `memory-os-agent-os memory-sources stats` fails through the natural operator
  command
- `memory-os-agent-os modules status` fails through the natural operator
  command
- doctor returns an error
- status tool contract validation fails
- RH-26 apply probes select mechanism-heavy sections for casual prompts or
  include background sections for cancellation/continue prompts
- RH-28 ambiguous recall probes select `Recall Clarification Guard` but the
  guard is missing the tool-aware contract, reported as
  `low_clue_guard_contract_missing`
- RH-28 low-clue candidates contain internal route or projection names, reported
  as `low_clue_internal_candidate_label`
- backup-looking Memory-OS provider/shell plugin manifests exist under
  `$HERMES_HOME/plugins/`
- any boundary boolean becomes true
- Memory Sources attribution contains forbidden fields, private text, or any
  true hard-boundary flag
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

## v0.3 Script-Backed Trend Snapshot

The deterministic monitor script produced the following saved automation
snapshot:

```text
snapshot_time_utc=2026-05-22T11:49:52Z
host=debian
classification=WARN
```

PASS:

```text
gateway_active
heartbeat_timer_active
index_healthy
doctor_ok
status_tool_contract_ok
context_router_apply
```

WARN:

```text
rh26_casual_empty
deep_reflection_source_skew
```

FAIL:

```text
none
```

Status counts:

```text
audit_entries=1211
events=92
working_items=85
crystallized_candidates=85
crystallized_records=0
queue_backlog=0
index_health=healthy
prefetch_mode=indexed
```

Trend deltas from the previous saved snapshot:

```text
audit_entries +110
events +2
working_items +2
crystallized_candidates +2
crystallized_records +0
audit_entries_per_new_event=55.0
```

Interpretation:

- The host remained healthy and the only WARN items were expected observation
  signals.
- The `audit_entries_per_new_event=55.0` ratio is high enough to keep tracking,
  but it did not correspond to boundary violations, queue backlog, or
  crystallized writes.
- Events, working items, and candidates moved together by `+2`, which is
  consistent with real foreground/runtime activity rather than uncontrolled
  recursive growth.
- `crystallized_records` stayed `0`.

Shell hook marker totals:

```text
agent_os_shell_session_started=5
agent_os_shell_session_reset=4
agent_os_shell_session_finalized=4
```

These are totals, not expected-coverage assertions. The monitor still does not
infer whether a real session reset occurred without a corresponding marker.

Compression signal:

```text
gateway_compaction_recent_count=0
gateway_compaction_focus_none_count=0
```

No new automatic compression focus-gap signal appeared in this monitor window.

RH-26 live apply probe headings:

```text
cancel_failed_video -> Current Foreground Task
continue_current_task -> Current Foreground Task
casual_memory_system_change -> <empty>
diagnostic_current_architecture -> Diagnostic Grounding / Current Memory-OS Runtime Facts
candidate_vs_crystallized -> Crystallized Review Candidates / Indexed Recall
active_comfyui_install -> Current Foreground Task / Indexed Recall
deferred_cancellation -> Current Foreground Task
```

This matches the intended full-route test-host apply shape:

- cancellation and vague continuation stay foreground-only
- diagnostic questions expose diagnostic context
- candidate/crystallized questions get candidate-review and indexed recall
- active task prompts keep the foreground task plus task-relevant indexed
  recall
- casual continuity remains empty on this host because the available context is
  still mechanism-heavy

DeepReflection remained safe:

```text
enabled=true
injection_mode=auto_bounded
latest_selected_by_source_class=working:2
latest_dropped_by_source_class=working:1
rolling_selected_by_source_class=working:14
rolling_dropped_by_source_class=working:7
actual_send=false
actual_execute=false
actual_identity_write=false
actual_crystallized_approval=false
```

A read-only manual recheck shortly after the saved snapshot reported:

```text
recheck_time_utc=2026-05-22T11:56:26Z
audit_entries=1215
events=92
working_items=85
crystallized_candidates=85
crystallized_records=0
delta_vs_saved_snapshot:
  audit_entries +4
  events +0
  working_items +0
  crystallized_candidates +0
```

This recheck is useful because it shows the monitor probe itself can add small
audit noise without advancing events, working memory, candidates, or
crystallized records. Future audit-growth review should separate monitor/tool
audit noise from real event-layer growth.

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

### RH-26 Casual Context Classification / Monitor v0.4

Initial RH-26 monitor rules treated `casual_memory_system_change` as expected
empty context. After RH-27 enabled the cognitive loop, safe recent summaries can
appear for casual conversation. That is useful carryover, not a failure by
itself.

v0.4 classification:

- `casual_memory_system_change` with no headings: `WARN` as
  `rh26_casual_empty`
- `casual_memory_system_change` with `Recent Event Summaries` or
  `Conversation Carryover`: acceptable
- `casual_memory_system_change` with `Diagnostic Grounding`,
  `Current Memory-OS Runtime Facts`, `Current Foreground Task`, or
  `Crystallized Review Candidates`: `FAIL`
- other casual headings such as `Working Memory`: `WARN` for manual review

The monitor still does not print section bodies or private summaries.

Remote validation:

```text
time=2026-05-23T06:10:38Z
RH-26 casual_memory_system_change=1535 chars, headings=[Recent Event Summaries]
status=PASS
FAIL=[]
WARN=[]
```

Post-smoke recheck:

```text
time=2026-05-23T06:20:41Z
status=PASS
index_health=healthy
RH-26 casual_memory_system_change=1538 chars, headings=[Recent Event Summaries]
compaction.focus_none_count=0
DeepReflection latest selected_by_source_class={"governance": 2}
DeepReflection rolling selected_by_source_class={"governance": 4, "working": 14}
audit_entries=1871
events=139
working_items=121
crystallized_candidates=121
crystallized_records=0
delta_from_previous_snapshot:
  audit_entries=+112
  events=+12
  working_items=+21
  candidates=+21
  audit_per_new_event=9.333
FAIL=[]
WARN=[]
```

Interpretation:

- safe casual carryover should now be treated as a positive signal that the
  cognitive loop has produced usable recent summaries
- `index_health=healthy` means the earlier stale warning was transient
- DeepReflection source-class skew is no longer strictly working-only after
  RH-27; governance appears in latest and rolling distributions
- audit and candidate growth should remain a trend metric, not an immediate
  failure, unless growth becomes unbounded or disk usage becomes material

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
