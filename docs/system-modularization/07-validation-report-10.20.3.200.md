# Memory-OS v0.1 Module Validation Report For 10.20.3.200

Date: 2026-05-21

## Target

- Host alias: `hermes-media`
- Host IP: `10.20.3.200`
- Hostname: `debian`
- User: `root`
- Hermes home: `/root/.hermes`
- Deployment repository: `/tmp/hermes-memory-os-validation/repo`
- Deployment commit: `ac7873d Package agent compatibility runtime`

This validation targets the `10.20.3.200` staging Hermes host only. It does not
touch `10.20.2.88`.

## Deployment Summary

Memory-OS v0.1 modules were deployed to the existing main staging profile.

Installed surfaces:

- provider plugin: `/root/.hermes/plugins/memory_os`
- runtime heartbeat artifacts: `/root/.hermes/memory-os/bin` and
  `/root/.hermes/memory-os/systemd`
- portable module runtime package:
  `/root/.hermes/memory-os/runtime/python/plugins`
- agent compatibility package:
  `/root/.hermes/memory-os/runtime/python/agent`
- profile-local module registry and state:
  `/root/.hermes/system-modules`

The install command did not request provider enablement because the staging
host already had `memory.provider=memory_os`.

```bash
HERMES_HOME=/root/.hermes \
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-runtime \
  --install-system-modules
```

Installer result:

```text
provider files copied: 22
system module runtime files copied: 45
agent runtime files copied: 2
runtime artifacts installed: true
runtime enabled by this command: false
provider enabled by this command: false
```

## Pre-Install Discovery

Before the v0.1 module deployment, the host already reported Memory-OS as the
active Hermes memory provider:

```text
Provider: memory_os
Plugin: installed
Status: available
Active plugin: memory_os (local)
```

Existing plugin location:

```text
/root/.hermes/plugins/memory_os
```

Existing canonical store:

```text
/root/.hermes/memory-os
```

## Host Test Evidence

Remote repository was reset to the deployment commit:

```text
49a5f66 Install portable system modules runtime
66d1d66 Harden module review evidence
65283d6 Add would-send speak gate module
```

After fixing the missing runtime `agent` compatibility package, final deployment
used:

```text
ac7873d Package agent compatibility runtime
```

Remote test subset:

```text
python3 -m pytest tests/scripts/test_memory_os_plugin_install.py tests/system_modularization -q
76 passed in 0.46s
```

The same test subset had passed locally before deployment:

```text
76 passed in 3.71s
```

Local full suite before deployment:

```text
python -m pytest -q
176 passed in 12.04s
python -m compileall -q agent plugins scripts
passed
git diff --check
passed
```

## Runtime Import Finding And Fix

The first host import attempt showed a real packaging gap:

```text
ModuleNotFoundError: No module named 'agent'
```

Cause:

- `--install-system-modules` copied `plugins/`
- module imports eventually loaded `plugins.memory.memory_os.__init__`
- that provider package imports `agent.memory_provider`
- the runtime package did not include `agent/`

Fix:

- installer now copies `agent/__init__.py` and `agent/memory_provider.py` to
  `$HERMES_HOME/memory-os/runtime/python/agent`
- regression coverage added to `tests/scripts/test_memory_os_plugin_install.py`

Fixed in commit:

```text
ac7873d Package agent compatibility runtime
```

## Module Lifecycle Validation

The host validation script imported modules from:

```text
PYTHONPATH=/root/.hermes/memory-os/runtime/python
```

Detected event profile:

```json
{"default": 11}
```

The following modules were installed through `ModuleLifecycle` and enabled for
profile `default`:

```text
mailbox: no-send
household_digest: no-send
wandering_mind: no-send
inner_drive: no-send
ops_gate: no-send
proposal_queue: no-send
evidence_scoring: no-send
self_evolution: no-send
speak_gate: would-send
```

This only writes profile-local module state. It does not start schedules and
does not enable real send.

## Integrated No-Send Flow

Host-level module validation ran the following path:

```text
Memory-OS events
-> household_digest
-> wandering_mind
-> speak_gate.evaluate_wandering_output()
-> inner_drive
-> ops_gate
-> proposal_queue
-> speak_gate proposal check before owner review
-> proposal_queue owner approve for proposal-only
-> speak_gate proposal check after owner review
-> evidence_scoring
-> self_evolution dry-run proposal
```

Key result:

```json
{
  "profile": "default",
  "household_digest": {"event_count": 11},
  "wandering_mind": {"would_send": true, "actual_send": false},
  "wandering_delivery": {"decision": "would_send", "actual_send": false},
  "inner_drive": {"processed_event_count": 1, "actual_send": false},
  "ops_gate": {"status": "warning", "decision_count": 1, "actual_execute": false},
  "proposal_before_approval": {"decision": "no_send", "actual_send": false},
  "proposal_after_approval": {"decision": "would_send", "actual_send": false},
  "evidence_scoring": {"score_count": 36, "actual_approve": false},
  "self_evolution": {
    "status": "ok",
    "proposal_created": true,
    "direct_self_modify": false,
    "actual_execute": false
  }
}
```

Validated invariants:

```json
{
  "no_actual_send": true,
  "ops_gate_no_execute": true,
  "self_evolution_no_execute": true,
  "proposal_approval_not_crystallized": true
}
```

## Memory-OS Doctor

After module validation, `memory_os doctor` initially reported an index count
mismatch because the module run wrote working/candidate/audit artifacts after
the previous index pass.

Recovery action:

```bash
HERMES_HOME=/root/.hermes hermes memory_os heartbeat --max-events 100
```

Post-heartbeat doctor:

```json
{
  "schema_version": "memory-os.doctor.v0",
  "status": "ok",
  "exit_code": 0,
  "findings": [
    {
      "code": "hindsight_adapter_disabled",
      "severity": "warning"
    }
  ]
}
```

The Hindsight warning is expected because Hindsight is disabled as an optional
adapter and is not canonical storage.

Post-validation status:

```text
events: 11
working_items: 12
crystallized_candidates: 12
crystallized_records: 0
queue_backlog: 0
prefetch_mode: indexed
index_health: healthy after heartbeat recovery
```

## Gateway Restart

The running gateway needed a single restart to load the refreshed provider code.
Only the `10.20.3.200` main staging gateway was restarted.

```text
before: ActiveState=active, SubState=running, MainPID=427105
after:  ActiveState=active, SubState=running, MainPID=428485
```

Post-restart memory discovery:

```text
Provider: memory_os
Plugin: installed
Status: available
Active plugin: memory_os (local)
```

Post-restart doctor:

```text
status: ok
only finding: hindsight_adapter_disabled warning
```

## Safety Boundaries

Confirmed:

- no command touched `10.20.2.88`
- no real Telegram/mailbox send occurred
- no Hindsight export occurred
- no crystallized record was approved or written
- no identity source was modified
- no production gateway was restarted
- only `10.20.3.200` staging `hermes-gateway.service` was restarted

## Stability Gate

`10.20.3.200` is a test host, not a production staging environment. There is no
business workload to observe for one or two weeks. The stability gate is a
single next-day check.

Run on 2026-05-22:

```bash
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes memory_os status
HERMES_HOME=/root/.hermes hermes memory_os doctor
systemctl --user is-active hermes-memory-os-heartbeat.timer
systemctl --user is-enabled hermes-memory-os-heartbeat.timer
systemctl --user show hermes-gateway.service -p ActiveState -p SubState -p MainPID
```

Pass criteria:

- `hermes memory` still reports provider `memory_os` active.
- `memory_os doctor` returns `status=ok`.
- `memory_os status` reports no index mismatch and no queue backlog.
- heartbeat timer is active and enabled.
- gateway service is active/running.
- no actual-send, actual-execute, identity-write, Hindsight export, or
  crystallized approval boundary is violated.

If this gate passes, move directly into Runtime Hardening. Do not wait for a
long observation period.

## Runtime Hardening RH-05 Dry-Run

Date: 2026-05-21

Scope:

- RH-05 CronMirror only
- no plugin refresh on `/root/.hermes`
- no gateway restart
- no `--apply`
- no cron job mutation
- no Memory-OS event write

Method:

The current local working tree was copied to `/tmp/memory-os-rh05` on
`hermes-media` and executed with `PYTHONPATH=/tmp/memory-os-rh05`. This avoided
installing the uncommitted CronMirror code into the live Hermes plugin tree.

Pre-check:

```text
host: debian
memory_os_root: present
installed cron_mirror.py: missing
Hermes CLI cron-mirror command: not installed yet
```

CronMirror dry-run result:

```json
{
  "status": "ok",
  "job_count": 0,
  "output_file_count": 0,
  "new_event_count": 0,
  "dry_run": true,
  "written_event_ids": []
}
```

Status and doctor:

```text
cron_mirror status: ok
cron_mirror doctor: ok
pending_output_count: 0
state_rebuilt: false
findings: []
```

Side-effect check:

```text
/root/.hermes/memory-os/runtime/cron_mirror_state.json: absent
memory-os audit grep cron_mirror: no entries
Memory-OS events: 11
working_items: 12
index_health: healthy
queue_backlog: 0
```

Interpretation:

RH-05 CronMirror is safe to dry-run on `10.20.3.200`. The host currently has no
cron output files to mirror, so this validates empty-environment behavior and
the no-write dry-run boundary. It does not yet validate `--apply` or non-empty
cron output handling on the host.

## Runtime Hardening RH-09 Dry-Run

Date: 2026-05-21

Scope:

- RH-09 SessionMirror only
- no plugin refresh on `/root/.hermes`
- no gateway restart
- no `--apply`
- no `state.db` write
- no Memory-OS event write

Method:

The current local working tree was copied to `/tmp/memory-os-rh09` on
`hermes-media` and executed with `PYTHONPATH=/tmp/memory-os-rh09`. This avoided
installing the uncommitted SessionMirror code into the live Hermes plugin tree.

Pre-check:

```text
state.db: present
/root/.hermes/sessions: 45 files
installed session_mirror.py: missing
```

SessionMirror status:

```json
{
  "status": "ok",
  "session_count": 22,
  "covered_session_count": 9,
  "pending_session_count": 13,
  "state_db_present": true,
  "sessions_root_present": true,
  "state_rebuilt": false,
  "findings": []
}
```

SessionMirror doctor:

```json
{
  "status": "ok",
  "findings": []
}
```

SessionMirror dry-run result:

```json
{
  "status": "ok",
  "session_count": 22,
  "covered_session_count": 9,
  "new_event_count": 13,
  "dry_run": true,
  "state_rebuilt": false,
  "written_event_ids": [],
  "findings": []
}
```

Side-effect check:

```text
/root/.hermes/memory-os/runtime/session_mirror_state.json: absent
memory-os audit grep session_mirror: no entries
Memory-OS events: 11
working_items: 12
index_health: healthy
queue_backlog: 0
```

Interpretation:

RH-09 SessionMirror can read the test host's session surfaces in read-only mode
and can identify uncovered sessions without writing events, state, or audit
records. The dry-run found 13 sessions that would be mirrored by an apply run,
but apply remains blocked until the mirror family and RH-12 Inner Drive
eligibility policy are in place.

## Runtime Hardening RH-10 Dry-Run

Date: 2026-05-21

Scope:

- RH-10 StateSourceMirror only
- no plugin refresh on `/root/.hermes`
- no gateway restart
- no `--apply`
- no state-source file mutation
- no Memory-OS event write

Method:

The current local working tree was copied to `/tmp/memory-os-rh10` on
`hermes-media` and executed with `PYTHONPATH=/tmp/memory-os-rh10`. This avoided
installing the uncommitted StateSourceMirror code into the live Hermes plugin
tree.

Pre-check:

```text
installed state_source_mirror.py: missing
/root/.hermes/memory-os/runtime/state_source_mirror_state.json: absent
```

Actual host dry-run with no configured state roots:

```json
{
  "status": "ok",
  "state_root_count": 0,
  "source_count": 0,
  "new_event_count": 0,
  "dry_run": true,
  "state_rebuilt": false,
  "written_event_ids": [],
  "findings": []
}
```

Synthetic allowlisted `/tmp` state-root dry-run:

```json
{
  "status": "ok",
  "state_root_count": 1,
  "source_count": 2,
  "new_event_count": 2,
  "dry_run": true,
  "state_rebuilt": false,
  "written_event_ids": [],
  "findings": []
}
```

Side-effect check:

```text
/root/.hermes/memory-os/runtime/state_source_mirror_state.json: absent
memory-os audit grep state_source_mirror: no entries
synthetic body grep under /root/.hermes/memory-os: no entries
Memory-OS events: 11
working_items: 12
index_health: healthy
queue_backlog: 0
```

Interpretation:

RH-10 StateSourceMirror supports a blank/no-allowlist host as healthy and can
identify allowlisted state-source changes without writing events, state, audit,
or source bodies during dry-run. Apply remains blocked until RH-12 Inner Drive
eligibility policy is in place.

## Runtime Hardening RH-11 Dry-Run

Date: 2026-05-21

Scope:

- RH-11 Continuity Context Selector only
- no plugin refresh on `/root/.hermes`
- no gateway restart
- no mirror `--apply`
- no Memory-OS event write
- no heartbeat / Inner Drive processing of mirror events

Method:

The current local working tree was copied to `/tmp/memory-os-rh11` on
`hermes-media` and executed with `PYTHONPATH=/tmp/memory-os-rh11`. This avoided
installing uncommitted selector code into the live Hermes plugin tree.

Actual host selector status:

```json
{
  "schema_version": "memory-os.continuity_selector.v0",
  "selected_total": 8,
  "dropped_total": 3,
  "selected_by_source_class": {
    "foreground": 8
  },
  "dropped_by_source_class": {
    "foreground": 3
  },
  "seed_slots": {
    "foreground": 2,
    "cron": 1,
    "mailbox": 1,
    "room_family": 1,
    "state_source": 1,
    "governance": 1
  },
  "max_records": 8
}
```

Actual host doctor selector parity:

```text
doctor.meta_audit.continuity_selector matched status.continuity_selector
```

Actual host prefetch check:

```json
{
  "chars": 3836,
  "has_recent": true,
  "has_bridge": false,
  "has_diagnostic": false
}
```

The actual host currently has only foreground Memory-OS events, so no
`Continuity Bridge` section is expected on the real host yet.

Synthetic `/tmp` bridge scenario:

```json
{
  "has_bridge": true,
  "has_cron": true,
  "has_state": true,
  "cron_before_working": true,
  "selector": {
    "selected_total": 8,
    "dropped_total": 4,
    "selected_by_source_class": {
      "cron": 1,
      "foreground": 6,
      "state_source": 1
    },
    "dropped_by_source_class": {
      "foreground": 4
    }
  }
}
```

Side-effect check:

```text
synthetic bridge/working markers grep under /root/.hermes/memory-os: no entries
Memory-OS events: 11
working_items: 12
index_health: healthy
queue_backlog: 0
```

Interpretation:

RH-11 exposes selected/dropped selector counts through status and doctor without
private bodies, keeps diagnostic grounding separate, and preserves bridge seed
facts ahead of noisy working memory in bounded prefetch contexts. No mirror
events were applied and no heartbeat/Inner Drive mirror processing was enabled.

## Runtime Hardening RH-12 Local Review Gate

Date: 2026-05-21

Scope:

- RH-12 Inner Drive Mirror Compatibility only
- local tests only
- no 10.20.3.200 host execution
- no mirror `--apply`
- no recurring Mirror -> Heartbeat -> InnerDrive enablement

Implemented local policy:

```text
conversation_turn                   -> lingering + candidate
memory_write                         -> lingering + candidate
conversation_turn_mirrored bounded   -> low-weight lingering only by default
session_observed                     -> index_only
cron_job_run                         -> index_only
candidate_surface_changed            -> no recursive candidate
unknown event kind                   -> index_only
```

The runtime and the module now report:

```text
policy_skipped_event_count
policy_skipped_event_ids
cap_deferred_event_count
cap_deferred_event_ids
source_class_counts
working_created_count
candidate_created_count
```

Local verification:

```text
python -m pytest tests/plugins/memory/test_memory_os_runtime.py \
  tests/system_modularization/test_inner_drive_runtime_module.py \
  tests/plugins/memory/test_memory_os_e2e.py -q

16 passed
```

Covered invariants:

- `cron_job_run` does not create working memory or crystallized candidates.
- metadata-only `session_observed` does not create lingering.
- bounded `conversation_turn_mirrored` can create controlled low-weight working
  memory without creating a candidate by default.
- `candidate_surface_changed` does not recursively create candidates.
- unknown event kinds default to `index_only`.
- source caps can defer excess cron/state-class events while still allowing a
  foreground event through the same run.
- existing E2E owner approval and Hindsight boundaries still pass locally.

Interpretation:

RH-12 was reviewed and committed locally before RH-13 design work started:

```text
fd6ebe8 Add inner drive mirror eligibility policy
```

This keeps RH-13 dependent on a committed Inner Drive eligibility policy instead
of an implicit or unreviewed working-tree change.

## Pre-RH-13 Clarifications

Claude's RH-12 review raised two questions before RH-13.

### Why `proposal_after_approval.actual_send` Stays `false`

`proposal_after_approval.decision=would_send` means Speak Gate would allow the
approved proposal to be expressed. It does not mean a transport send happened.

The v0.1 Speak Gate code has no real DeliverySink call path. It always returns
`actual_send=false` in delivery decisions, and `delivery_mode=send` is explicitly
reported as `send_blocked` / doctor error:

```text
delivery_mode=no-send    -> decision=no_send, actual_send=false
delivery_mode=would-send -> decision=would_send, actual_send=false
delivery_mode=send       -> decision=send_blocked, actual_send=false
```

So the boundary is code-level, not just configuration-level. Owner approval in
Proposal Queue can change a Speak Gate decision from `no_send` to `would_send`,
but v0.1 still has no path that performs real Telegram, mailbox, or other
delivery.

### Why `evidence_scoring.score_count=36`

Evidence/Scoring v0.1 uses a one-subject / one-evidence / one-score snapshot
model. `score_count` is the number of collected subjects, not a multi-dimension
score matrix.

For the host validation run:

```text
11 Memory-OS events
12 working-memory items
1 proposal_queue item
12 crystallized candidates
= 36 scored subjects
```

Each subject gets exactly one evidence record and one score record. This is
simple and explainable, but RH-13 must avoid treating raw score volume as a
digest priority signal by itself. Digest/consolidation should group and cap
subjects by source class, freshness, proposal state, and evidence refs before
creating any candidate or proposal.

### Normal Post-Module Validation Step

Module writes can temporarily outrun the SQLite index. Runtime validation should
treat heartbeat catch-up plus doctor as the default post-module check:

```bash
HERMES_HOME=/root/.hermes hermes memory_os heartbeat --max-events 100
HERMES_HOME=/root/.hermes hermes memory_os doctor
```

This turns index catch-up from an ad-hoc repair into the standard verification
path after module runs that write working, candidates, audit, or governance
artifacts.

## Runtime Hardening RH-13 Local Implementation Gate

Date: 2026-05-21

Scope:

- RH-13 Digest / Consolidation Mapping
- local code and tests
- no 10.20.3.200 plugin install in this local gate
- no recurring schedule enablement
- no real send / execute / identity write / crystallized approval

Implemented local module:

```text
plugins/modules/context/digest_consolidation.py
```

Implemented behavior:

- module manifest and lifecycle install/enable support
- profile-local config at `system-modules/digest_consolidation/config.json`
- default `time_zone=UTC`, profile override supported
- daily digest window assignment by event timestamp converted to profile time
- late-arrival group using event timestamp plus safe `arrived_at` metadata
- daily digest artifact write through tmp-file + fsync + atomic rename
- weekly consolidation over ISO week windows
- weekly expanded read scope includes Memory-OS events for the target week, so
  daily dropped events remain visible
- operational metadata source classes (`cron`, `state`, `session`) are digest
  visible but do not create owner-review candidates by default
- candidate dedup key uses `semantic_subject + candidate_kind + canonical
  source ref set`
- overlapping weekly candidates update existing proposal queue items through
  `candidate_updated_via_overlap` provenance instead of creating duplicates
- weekly candidate creation is capped by `max_candidates_per_week` (default 5)
- dry-run and apply artifacts are byte-identical for deterministic payloads
- status/doctor report artifact accumulation, but RH-13 does not prune artifacts
- installer self-check now treats `modules/context/digest_consolidation.py` as
  part of the required system module runtime package

Local tests added:

```text
tests/system_modularization/test_digest_consolidation_module.py
```

Covered invariants:

- manifest installs through `ModuleLifecycle`
- profile timezone daily window works
- late arrivals do not rewrite past digests
- daily apply artifact matches dry-run would-write payload
- candidate dedup key is order-independent and scoped by semantic subject
- weekly consolidation reselects events that daily digest dropped
- weekly consolidation creates at most 5 candidates by default
- overlapping semantic subjects update the existing candidate
- cron/state/session metadata do not become owner facts
- weekly dry-run and apply artifacts match
- artifact accumulation reports warning only; no pruning occurs in RH-13
- Sannai-shaped identity fixture is not touched

Self-review result:

```text
No actual_send=True path found.
No actual_approve=True path found.
No crystallized approved record write path found.
No identity/SOUL write path found.
No subprocess/systemctl/network transport path added.
```

Local verification:

```text
python -m pytest -q
210 passed

python -m compileall -q agent plugins scripts
passed

git diff --check
passed
```

## Runtime Hardening RH-13 10.20.3.200 Dry-Run

Date: 2026-05-21

Scope:

- RH-13 Digest / Consolidation dry-run only
- temporary code copy at `/tmp/memory-os-rh13`
- `PYTHONPATH=/tmp/memory-os-rh13`
- no install into `/root/.hermes/plugins`
- no gateway restart
- no recurring schedule enablement
- no apply

Method:

```text
copy /tmp/hermes-memory-os-validation/repo -> /tmp/memory-os-rh13
overlay RH-13 context module files into the temp copy
run DigestConsolidationModule directly against HERMES_HOME=/root/.hermes
```

Dry-run result:

```json
{
  "profile": "default",
  "event_count_before": 11,
  "event_count_after": 11,
  "module_root_exists_before": false,
  "module_root_exists_after": false,
  "daily": {
    "dry_run": true,
    "would_write_group_count": 0,
    "selected_count": 0,
    "dropped_count": 0,
    "late_arrival_count": 0,
    "actual_send": false,
    "actual_approve": false
  },
  "weekly": {
    "dry_run": true,
    "expanded_event_count": 11,
    "candidate_suggestion_count": 0,
    "deferred_candidate_count": 0,
    "forbidden_sources": ["raw_full_session_transcripts"],
    "actual_send": false,
    "actual_approve": false
  }
}
```

Interpretation:

- daily target date `2026-05-21` had no matching profile-local events, so the
  daily dry-run produced an empty digest card
- weekly target `2026-W21` re-read the Memory-OS event stream and saw all 11
  current events
- dry-run did not create `/root/.hermes/system-modules/digest_consolidation`
- Memory-OS event count stayed `11 -> 11`
- no working item, candidate, proposal, send, execute, identity, or
  crystallized approval path was triggered

Post-dry-run doctor:

```text
status: ok
only finding: hindsight_adapter_disabled warning
queue_backlog: 0
```

## Residual Items For Runtime Hardening

1. ModuleBus v0.1 remains append/read JSONL; no blocking subscribe API yet.
2. Runtime supervisor for automatic schema re-check and owner alert is still out
   of scope.
3. The staging host now has module state under `/root/.hermes/system-modules`;
   future deployments should treat that as profile-local evidence, not code.
4. Module writes can temporarily outrun the SQLite index. Runtime hardening
   should make heartbeat/index catch-up part of the normal validation path.

## Verdict

PASS for `10.20.3.200` full plugin deployment and no-send module validation.

The next step is the 2026-05-22 Stability Gate. If it passes, enter Runtime
Hardening on the test host. Production migration remains out of scope.
