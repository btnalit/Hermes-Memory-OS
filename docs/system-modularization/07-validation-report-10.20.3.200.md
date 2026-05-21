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

## Runtime Hardening RH-14 Local Implementation Gate

Date: 2026-05-21

Scope:

- RH-14 Governance Feedback Bridge
- local code and tests
- controlled apply validated later on 10.20.3.200
- no real send / execute / identity write / relationship write /
  crystallized approval

Implemented local module:

```text
plugins/modules/governance/feedback_bridge.py
```

Implemented behavior:

- module manifest and lifecycle install/enable support
- summary-only governance feedback events for:
  - `governance_evidence_scored`
  - `governance_ops_gate_decision`
  - `governance_proposal_created`
  - `governance_proposal_transitioned`
  - `governance_self_evolution_reported`
- event `safe_ref` always carries:
  - `source_class=governance`
  - `source_module=<source governance module>`
  - `artifact_ref`
  - `governance_feedback_key`
  - `drive_policy=evidence_only`
  - `candidate_allowed=false`
  - `body_policy=summary_only`
- idempotency uses source module, source key, state hash, and event kind
- repeated apply skips already-emitted governance feedback keys
- dry-run reports pending events without appending Memory-OS events
- apply appends Memory-OS events and records local bridge state
- raw proposal body is not mirrored into Memory-OS feedback events
- governance feedback appears in the Continuity Context Selector
- Inner Drive classification remains `evidence_only` with no working item and
  no candidate by design
- installer self-check now requires
  `modules/governance/feedback_bridge.py` in the runtime package

Local tests added:

```text
tests/system_modularization/test_governance_feedback_bridge_module.py
```

Covered invariants:

- manifest installs through `ModuleLifecycle`
- dry-run does not write events
- apply writes summary-only governance events
- second apply writes zero duplicate events
- proposal private body does not leak into governance feedback events
- continuity selector selects governance context
- Inner Drive policy classifies governance feedback as `evidence_only`
- Sannai-shaped identity fixture is not touched

Local verification:

```text
python -m pytest tests\system_modularization\test_governance_feedback_bridge_module.py tests\scripts\test_memory_os_plugin_install.py -q
13 passed

python -m pytest -q
215 passed

python -m compileall -q agent plugins scripts
passed

git diff --check
passed
```

## Runtime Hardening RH-14 10.20.3.200 Controlled Apply

Date: 2026-05-21

Scope:

- temporary code copy at `/tmp/memory-os-rh14`
- `PYTHONPATH=/tmp/memory-os-rh14`
- test host only: `10.20.3.200`
- controlled governance artifact generation plus RH-14 apply
- no 10.20.2.88 production access
- no gateway restart
- no real send / execute / identity write / relationship write /
  crystallized approval

Initial controlled apply method:

1. generated safe test-host governance artifacts:
   - evidence score snapshot
   - Ops-Gate blocked report
   - proposal queue candidate plus proposal-queue-only approval transition
   - Self-Evolution dry-run report
2. ran Governance Feedback Bridge dry-run
3. ran Governance Feedback Bridge apply
4. ran a second apply to verify idempotency
5. checked Continuity Selector and Inner Drive classification

Initial controlled apply result:

```json
{
  "event_count_before": 11,
  "event_count_after": 22,
  "governance_event_count_before": 0,
  "governance_event_count_after": 11,
  "new_governance_event_count": 11,
  "bridge_dry_run": {
    "would_write_event_count": 11,
    "written_event_count": 0
  },
  "bridge_apply": {
    "would_write_event_count": 11,
    "written_event_count": 11
  },
  "bridge_second_apply": {
    "already_emitted_count": 11,
    "would_write_event_count": 0,
    "written_event_count": 0
  },
  "new_governance_event_kinds": [
    "governance_evidence_scored",
    "governance_ops_gate_decision",
    "governance_proposal_created",
    "governance_proposal_transitioned",
    "governance_self_evolution_reported"
  ],
  "private_body_leaked": false,
  "context_contains_governance": true,
  "context_contains_private_body": false,
  "actual_send": false,
  "actual_execute": false
}
```

Important finding:

The first post-apply host heartbeat used stale installed runtime code. It
processed the 11 new `evt_gov_*` events and incorrectly created derived
working/candidate records. This was not a bridge defect; it exposed that the
test host's installed heartbeat runtime had not yet been refreshed to the
current RH-12 Inner Drive mirror-compatibility policy.

Corrective action:

```text
HERMES_HOME=/root/.hermes python3 /tmp/memory-os-rh14/scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules
```

The installer copied:

```text
provider files: 25
system module runtime files: 50
agent compatibility files: 2
```

Confirmed installed runtime paths contain the RH-12 markers:

```text
/root/.hermes/plugins/memory_os/inner_drive.py
/root/.hermes/memory-os/runtime/python/plugins/memory/memory_os/inner_drive.py
```

Targeted cleanup:

- backed up and removed only `evt_gov_*`-derived candidate rows
- backed up and removed only `evt_gov_*`-derived lingering rows
- did not remove foreground events, non-governance candidates, identity,
  relationship, or crystallized approved records

Cleanup evidence:

```json
{
  "candidate_removed_count": 11,
  "candidate_kept_count": 12,
  "working_removed_count": 11,
  "working_kept_count": 12,
  "candidates_backup": "/root/.hermes/memory-os/crystallized/candidates.jsonl.bak.rh14-20260521T030935Z",
  "working_backup": "/root/.hermes/memory-os/working/lingering.json.bak.rh14-20260521T030935Z"
}
```

A pre-existing duplicate candidate id was also found and removed after backup:

```json
{
  "removed_duplicate_count": 1,
  "removed_ids": ["cand_evt_20260520T091910094050Z_92f8da6e23"],
  "backup": "/root/.hermes/memory-os/crystallized/candidates.jsonl.bak.dedup-20260521T031147Z"
}
```

Post-refresh validation:

- generated one additional Ops-Gate report
- Governance Feedback Bridge wrote one new governance event
- refreshed heartbeat processed that event with the RH-12 policy
- no working item and no candidate were created

```json
{
  "before_event_count": 22,
  "after_event_count": 23,
  "before_candidate_count": 12,
  "after_candidate_count": 12,
  "before_working_count": 12,
  "after_working_count": 12,
  "bridge_apply": {
    "written_event_count": 1,
    "already_emitted_count": 4,
    "actual_send": false,
    "actual_execute": false
  },
  "heartbeat": {
    "processed_event_count": 1,
    "policy_skipped_event_count": 1,
    "candidate_created_count": 0,
    "working_created_count": 0,
    "source_class_counts": {
      "governance": 1
    }
  },
  "candidate_matches_for_new_events": [],
  "working_matches_for_new_events": []
}
```

Final post-RH-14 host verification:

```text
HERMES_HOME=/root/.hermes hermes memory_os heartbeat --max-events 100
candidate_count: 11
candidate_created_count: 0
working_item_count: 12
events: 23
index_counts.events: 23
index_counts.working_items: 12
index_counts.crystallized_candidates: 11

HERMES_HOME=/root/.hermes hermes memory_os doctor
status: ok
only finding: hindsight_adapter_disabled warning
queue_backlog: 0
skipped_private_body_count: 0
```

RH-14 result:

- Governance Feedback Bridge works on the test host
- governance summaries are now queryable Memory-OS events
- Continuity Selector can surface governance context
- stale runtime deployment risk was found and corrected
- RH-12 protection is now installed and verified on the test host
- no-send / no-execute / no-crystallized-approval boundaries held after the
  corrected runtime validation

## Runtime Hardening RH-14.5 Fresh Deployment Rehearsal

Date: 2026-05-21

Scope:

- test host only: `10.20.3.200`
- current local repo state, including RH-14 uncommitted changes
- clean Memory-OS-related deployment rehearsal
- clear previous Memory-OS test artifacts, provider, runtime, module state, and
  heartbeat timer before install
- do not clear Hermes core, profile sessions, gateway service, or unrelated
  `/root/.hermes` data
- no 10.20.2.88 production access
- no real send / execute / identity write / relationship write /
  crystallized approval

Pre-clean backup:

```text
/root/.hermes/backups/memory-os-fresh-deploy-20260521T032138Z
```

Cleared paths:

```text
/root/.hermes/plugins/memory_os
/root/.hermes/memory-os
/root/.hermes/system-modules
/root/.config/systemd/user/hermes-memory-os-heartbeat.service
/root/.config/systemd/user/hermes-memory-os-heartbeat.timer
/root/.config/systemd/user/timers.target.wants/hermes-memory-os-heartbeat.timer
```

Post-clean check:

```text
all target paths: cleared
heartbeat timer: inactive / not-found
```

Fresh install command:

```bash
HERMES_HOME=/root/.hermes python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --enable
```

Install result:

```text
provider enabled: true
provider files copied: 25
system module runtime files copied: 50
agent compatibility files copied: 2
runtime artifacts installed: true
heartbeat timer enabled: true
runtime interval: 5min
```

Provider discovery:

```text
HERMES_HOME=/root/.hermes hermes memory
Provider: memory_os
Plugin: installed
Status: available
memory_os (local) <- active
```

Initial post-install status:

```text
events: 0
working_items: 0
crystallized_candidates: 0
crystallized_records: 0
prefetch_mode: indexed
index_health: healthy
queue_backlog: 0
doctor: ok
doctor warnings: store_empty, hindsight_adapter_disabled
```

Heartbeat timer and gateway:

```text
TIMER_ACTIVE=active
TIMER_ENABLED=enabled

gateway restart:
before_pid=428485
after_pid=431776
active=active
sub=running
```

Full no-send integration chain from clean Memory-OS state:

```text
conversation/event
  -> MemoryOSRuntime heartbeat / inner-drive processing
  -> evidence_scoring
  -> ops_gate
  -> proposal_queue
  -> self_evolution
  -> governance_feedback dry-run
  -> governance_feedback apply
  -> governance_feedback second apply
  -> MemoryOSRuntime heartbeat/index catch-up
```

Integration result:

```json
{
  "initial_counts": {
    "events": 0,
    "working_items": 0,
    "crystallized_candidates": 0,
    "crystallized_records": 0
  },
  "first_heartbeat": {
    "processed_event_count": 1,
    "working_created_count": 1,
    "candidate_created_count": 1,
    "policy_skipped_event_count": 0,
    "source_class_counts": {
      "foreground": 1
    }
  },
  "score_result": {
    "score_count": 3,
    "actual_approve": false,
    "self_evolution_triggered": false
  },
  "ops_result": {
    "decision_count": 1,
    "actual_execute": false
  },
  "proposal_queue": {
    "state_after_transition": "approved_for_proposal",
    "crystallized_approved": false
  },
  "self_evolution": {
    "proposal_created": true,
    "direct_self_modify": false,
    "actual_execute": false
  },
  "bridge_dry_run": {
    "would_write_event_count": 6,
    "written_event_count": 0
  },
  "bridge_apply": {
    "would_write_event_count": 6,
    "written_event_count": 6
  },
  "bridge_second_apply": {
    "already_emitted_count": 6,
    "would_write_event_count": 0,
    "written_event_count": 0
  },
  "second_heartbeat": {
    "processed_event_count": 6,
    "policy_skipped_event_count": 6,
    "working_created_count": 0,
    "candidate_created_count": 0,
    "source_class_counts": {
      "governance": 6
    }
  },
  "post_governance_heartbeat_counts": {
    "events": 7,
    "working_items": 1,
    "crystallized_candidates": 1,
    "crystallized_records": 0
  },
  "boundary": {
    "actual_send": false,
    "actual_execute": false,
    "crystallized_records": 0,
    "governance_created_working_or_candidate": false
  }
}
```

Final post-rehearsal status:

```text
events: 7
working_items: 1
crystallized_candidates: 1
crystallized_records: 0
continuity_selector.selected_by_source_class:
  foreground: 1
  governance: 6
prefetch_mode: indexed
index_health: healthy
queue_backlog: 0
skipped_private_body_count: 0

doctor: ok
only finding: hindsight_adapter_disabled warning

heartbeat timer: active/enabled
gateway: active/running pid=431776
```

RH-14.5 result:

- fresh deployment script path is valid on `10.20.3.200`
- Memory-OS provider is discoverable and active after install
- system module runtime includes RH-14 Governance Feedback Bridge
- heartbeat timer is installed and enabled by the script
- main gateway survives restart and runs with the fresh provider
- complete no-send integration chain works from an empty Memory-OS store
- governance feedback events enter continuity context
- governance feedback remains `evidence_only` under heartbeat
- no real send, execute, identity write, relationship write, or crystallized
  approval occurred

## Telegram Conversation Memory Observation

Date: 2026-05-21

Scope:

- real Telegram conversation after RH-14.5 fresh deployment rehearsal
- user started with `/new`
- no manual test marker was required
- observation reports bounded summaries and structural counts only

Pre-chat baseline:

```text
events: 7
working_items: 1
crystallized_candidates: 1
crystallized_records: 0
index_health: healthy
prefetch_mode: indexed
heartbeat timer: active/enabled
gateway: active/running pid=431776
```

Post-chat status:

```text
events: 11
working_items: 5
crystallized_candidates: 5
crystallized_records: 0
doctor: ok
index_health: healthy
queue_backlog: 0
only finding: hindsight_adapter_disabled warning
```

Observed increments:

```text
conversation_turn events: +4
working_items: +4
crystallized_candidates: +4
crystallized_records: +0
```

Audit signals:

```text
append_event: 4
working_item_added: 4
crystallized_candidate_generated: 4
crystallized_candidate_queued: 4
```

Heartbeat catch-up check:

```text
processed_event_count: 0
already_processed_event_count: 11
working_created_count: 0
candidate_created_count: 0
```

This means the deployed timer/runtime had already processed the Telegram turns
before manual observation.

Continuity Selector:

```text
selected_total: 8
selected_by_source_class:
  foreground: 4
  governance: 4
dropped_by_source_class:
  foreground: 1
  governance: 2
```

Interpretation:

- Telegram foreground turns entered canonical Memory-OS events correctly
- Inner Drive turned each foreground turn into working memory and a review
  candidate
- no approved crystallized record was created automatically
- governance feedback and foreground conversation both appeared in continuity
  selection
- normal non-diagnostic prefetch could see recent conversation and governance
  context
- explicit memory-system questions correctly triggered diagnostic grounding

Follow-up findings:

1. `RH-21a Chinese Diagnostic Trigger Tuning`

   Explicit memory architecture questions should keep using diagnostic
   grounding, but broad Chinese wording around "记忆" can make the assistant
   answer in a system-report style during otherwise natural conversation.

2. `RH-21b Candidate Versus Crystallized Wording Guard`

   The system boundary held (`crystallized_candidates=5`,
   `crystallized_records=0`), but model-facing wording can still make
   candidates sound like approved crystallized memory. Future context text
   should label them as review candidates.

## Runtime Hardening RH-15 FTS Text Projection

Date: 2026-05-21

Scope:

- RH-15 FTS Text Projection
- local tests first
- then install current provider/runtime onto `10.20.3.200`
- append one controlled `index_only` telemetry event
- verify indexed recall can find structured fields without indexing private
  bodies

Local verification:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_store.py \
  tests/plugins/memory/test_memory_os_prefetch.py \
  tests/plugins/memory/test_memory_os_runtime.py -q

33 passed

python -m pytest -q

218 passed
```

New local coverage:

```text
test_index_projects_structured_event_payload_into_fts_without_private_body
test_index_projection_covers_session_governance_and_failure_payloads
test_index_records_fts_projection_version_for_rebuildability
```

Host deployment:

```text
target: 10.20.3.200 only
code copy: /tmp/memory-os-rh15
installed: provider, system modules, agent runtime, heartbeat runtime
heartbeat timer: active/enabled
gateway restart: not required for this index validation
```

Controlled validation event:

```text
event_id: evt_rh15_projection_20260521T010000Z
source: cron
kind: cron_job_run
drive_policy: index_only
candidate_allowed: false
payload fields:
  status=error
  metrics.loss_rate=0.08
  metrics.queue_depth=12
  raw_transcript=<private marker>
```

Indexed recall result:

```json
{
  "event_id": "evt_rh15_projection_20260521T010000Z",
  "fts_text_projection_version": "memory-os.fts_projection.v1",
  "heartbeat_processed_event_count": 1,
  "heartbeat_policy_skipped_event_count": 1,
  "index_counts": {
    "audit_entries": 90,
    "crystallized_candidates": 5,
    "crystallized_records": 0,
    "events": 12,
    "working_items": 5
  },
  "loss_rate_hits": [
    "evt_rh15_projection_20260521T010000Z"
  ],
  "queue_depth_hits": [
    "evt_rh15_projection_20260521T010000Z"
  ],
  "private_body_hits": []
}
```

Post-catch-up status:

```json
{
  "crystallized_candidates": 5,
  "crystallized_records": 0,
  "events": 12,
  "index_health": {
    "fts_tokenizer": "trigram",
    "state": "healthy"
  },
  "prefetch_mode": "indexed",
  "queue_backlog": 0,
  "working_items": 5
}
```

Doctor:

```json
{
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

Interpretation:

- structured payload fields now project into FTS search text
- canonical event payload remains unchanged in JSONL
- private body fields are not indexed
- projection version is recorded for rebuildability
- mirror telemetry remains `index_only` and did not create working memory or
  crystallized candidates
- no actual send, execute, identity write, relationship write, Hindsight export,
  or crystallized approval occurred

## Runtime Hardening RH-16 Query Fast-Path Router

Date: 2026-05-21

Scope:

- RH-16 Query Fast-Path Router
- deterministic query routing before indexed recall
- Chinese and mixed Chinese/English operational query fixtures
- preserve Slice 21 diagnostic grounding authority
- deploy to `10.20.3.200` test host and verify provider prefetch

Local verification:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_query_router.py \
  tests/plugins/memory/test_memory_os_prefetch.py \
  tests/plugins/memory/test_memory_os_diagnostic_grounding.py -q

22 passed

python -m pytest -q

224 passed
```

New local coverage:

```text
test_query_router_fast_path_extracts_mixed_operational_keywords
test_query_router_slow_path_for_abstract_query_without_entities
test_query_router_diagnostic_route_preserves_diagnostic_authority
test_query_router_redacts_secret_like_user_input
test_prefetch_uses_routed_query_and_reports_route
test_prefetch_keeps_targeted_indexed_recall_inside_tight_budget
```

Implementation note:

The first 10.20.3.200 validation exposed an over-narrow route:

```text
PCDN loss_rate 报错
```

This missed the RH-15 event because `报错` was a generic Chinese symptom word
while the indexed event used `status=error`. The route planner now prefers
strong ASCII/module/parameter entities when present and uses Chinese operational
keywords only when no stronger entities are available.

Host deployment:

```text
target: 10.20.3.200 only
code copy: /tmp/memory-os-rh16
installed: provider, system modules, agent runtime, heartbeat runtime
heartbeat timer: active/enabled
gateway restart: not required for this provider-prefetch validation
```

Provider prefetch validation:

```json
{
  "diagnostic_has_indexed_recall": false,
  "diagnostic_has_runtime_facts": true,
  "diagnostic_route": {
    "display_query": "",
    "keywords": [],
    "route": "diagnostic",
    "search_query": ""
  },
  "fast_context_has_loss_rate": true,
  "fast_context_has_rh15_event": true,
  "fast_context_has_route": true,
  "fast_context_indexed_before_recent": true,
  "fast_route": {
    "display_query": "PCDN loss_rate",
    "keywords": [
      "PCDN",
      "loss_rate"
    ],
    "route": "fast_path",
    "search_query": "PCDN loss_rate"
  },
  "secret_route": {
    "display_query": "gateway_restart",
    "keywords": [
      "gateway_restart"
    ],
    "route": "fast_path",
    "search_query": "gateway_restart"
  },
  "slow_route": {
    "display_query": "上次那个老问题又出现了",
    "keywords": [],
    "route": "slow_path",
    "search_query": "上次那个老问题又出现了"
  }
}
```

Post-validation status:

```json
{
  "crystallized_candidates": 5,
  "crystallized_records": 0,
  "events": 12,
  "index_health": {
    "fts_tokenizer": "trigram",
    "state": "healthy"
  },
  "prefetch_mode": "indexed",
  "queue_backlog": 0,
  "working_items": 5
}
```

Doctor:

```json
{
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

Interpretation:

- explicit diagnostic queries still return runtime facts and suppress historical
  indexed recall
- mixed Chinese/English operational queries now route to compact fast-path
  search terms
- secret-like user input is redacted before route display or indexed search
- targeted Indexed Recall is ordered before generic Recent Event Summaries so a
  tight context budget does not hide the query-specific hit
- no actual send, execute, identity write, relationship write, Hindsight export,
  or crystallized approval occurred

## Runtime Hardening RH-21a/RH-21b Wording Guards

Date: 2026-05-21

Scope:

- RH-21a Chinese Diagnostic Trigger Tuning
- RH-21b Candidate Versus Crystallized Wording Guard
- local fixture tests first
- deploy to `10.20.3.200`
- validate provider prefetch and status wording

Local verification:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_diagnostic_grounding.py \
  tests/plugins/memory/test_memory_os_prefetch.py \
  tests/plugins/memory/test_memory_os_query_router.py -q

26 passed

python -m pytest -q

228 passed
```

New local coverage:

```text
test_chinese_memory_conversation_does_not_trigger_diagnostic_grounding
test_chinese_explicit_provider_questions_still_trigger_diagnostic_grounding
test_prefetch_labels_candidates_as_review_only_not_approved_crystallized
test_provider_status_distinguishes_candidates_from_approved_crystallized_records
```

Host deployment:

```text
target: 10.20.3.200 only
code copy: /tmp/memory-os-rh21
installed: provider, system modules, agent runtime, heartbeat runtime
heartbeat timer: active/enabled
gateway restart: not required for this provider-prefetch validation
```

Provider prefetch validation:

```json
{
  "candidate_context_has_candidate_only": true,
  "candidate_context_has_not_approved": true,
  "candidate_context_has_review_label": true,
  "casual_has_recent_or_candidates": true,
  "casual_has_runtime_facts": false,
  "casual_route": {
    "display_query": "记忆",
    "keywords": [
      "记忆"
    ],
    "route": "fast_path",
    "search_query": "记忆"
  },
  "crystallized_candidates": 5,
  "crystallized_records": 0,
  "explicit_has_indexed_recall": false,
  "explicit_has_runtime_facts": true,
  "explicit_route": {
    "display_query": "",
    "keywords": [],
    "route": "diagnostic",
    "search_query": ""
  },
  "status_candidate_label": "review candidates only; not approved crystallized memory",
  "status_records_label": "approved crystallized memory records"
}
```

Post-validation status:

```json
{
  "crystallized_candidates": 5,
  "crystallized_records": 0,
  "events": 12,
  "index_health": {
    "fts_tokenizer": "trigram",
    "state": "healthy"
  },
  "prefetch_mode": "indexed",
  "queue_backlog": 0,
  "working_items": 5
}
```

Doctor:

```json
{
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

Interpretation:

- casual Chinese questions about the memory system no longer force diagnostic
  runtime facts into the foreground answer
- explicit provider/backend/status questions still trigger diagnostic grounding
- candidate context is labeled as `candidate only / review candidate`
- status output now labels candidates as review-only and records as approved
  crystallized memory
- `crystallized_candidates=5` and `crystallized_records=0` remain distinct
- no actual send, execute, identity write, relationship write, Hindsight export,
  or crystallized approval occurred

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

## 2026-05-21 Telegram Follow-Up: RH-21c Finding

After RH-21a/RH-21b, the owner ran a fresh Telegram conversation:

```text
你了解我们记忆系统吗？
你觉得这套记忆系统怎么样？
当前记忆架构是什么？
你现在用的是什么 memory provider？
那些 crystallized candidates 是已经沉淀的长期记忆吗？
```

Observed host state:

```json
{
  "events": 17,
  "working_items": 10,
  "crystallized_candidates": 10,
  "crystallized_records": 0,
  "index_health": {
    "state": "healthy"
  },
  "doctor": "ok",
  "queue_backlog": 0
}
```

Interpretation:

- the five Telegram turns were captured as events, working items, and review
  candidates
- no crystallized records were created
- doctor remained `ok`; the real index state was `healthy`
- explicit diagnostic questions still received current runtime facts
- casual memory-system questions no longer triggered diagnostic grounding

New finding:

- casual prompts could still receive old `Working Memory` summaries written in
  a diagnostic/report style
- those historical summaries could seed stale wording such as
  `index_health: stale` or old Hindsight API details even though the current
  runtime facts were healthy

Action:

- added RH-21c Working Memory Diagnostic Tone Guard to the hardening plan
- RH-21c filters diagnostic/report-style working items from ordinary prefetch
  context without deleting canonical Memory-OS data

Implementation validation:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_prefetch.py \
  tests/plugins/memory/test_memory_os_diagnostic_grounding.py \
  tests/plugins/memory/test_memory_os_query_router.py -q

27 passed

python -m pytest -q

229 passed
```

Host validation after reinstalling the provider/runtime on `10.20.3.200`:

```json
{
  "casual_prompt": {
    "diagnostic": false,
    "stale_claim": false,
    "hindsight_url": false,
    "canonical_path": false,
    "memory_context_tag": false,
    "ops_gate_report_seed": false
  },
  "explicit_diagnostic_prompt": {
    "diagnostic": true,
    "runtime_healthy": true,
    "hindsight_url": false
  },
  "doctor": "ok",
  "heartbeat_timer": "active/enabled"
}
```

Boundary:

- canonical events, working items, candidates, and audit entries were not
  deleted or rewritten
- filtering happens only during ordinary prefetch context projection
- explicit provider/backend/status questions still receive current diagnostic
  runtime facts

## Deep Reflection DR-08 Test Host Validation

Date: 2026-05-21

Scope:

- deploy current Deep Reflection runtime to `10.20.3.200`
- enable `injection_mode=auto_bounded` on the test host only
- validate real Telegram behavior for ordinary conversation and diagnostic
  questions
- verify no send, execute, identity, or crystallized-write boundary is crossed

Local verification before host deployment:

```text
python -m pytest -q

253 passed
```

Remote package verification on `10.20.3.200`:

```text
python3 -m pytest \
  tests/plugins/memory/test_memory_os_lifecycle.py \
  tests/plugins/memory/test_memory_os_prefetch.py \
  tests/system_modularization/test_deep_reflection_module.py -q

43 passed
```

Deployment:

```text
HERMES_HOME=/root/.hermes \
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --enable
```

Gateway reload:

```json
{
  "gateway_service": "hermes-gateway.service",
  "status": "active",
  "main_pid_after_restart": 434994,
  "heartbeat_timer": "active/enabled"
}
```

Deep Reflection test configuration:

```json
{
  "enabled": true,
  "injection_mode": "auto_bounded",
  "max_cards": 2,
  "max_chars_per_card": 260,
  "max_chars_total": 600,
  "working_updates_enabled": false,
  "self_evolution_proposals_enabled": false,
  "wandering_seed_enabled": false
}
```

Current injection artifact:

```json
{
  "selected_count": 2,
  "dropped_count": 1,
  "cards": [
    "Recent background activity suggests staying careful and steady.",
    "Recent conversation keeps circling around how memory changes the relationship."
  ],
  "instruction_like_hit": false,
  "mechanism_terms_hit": false,
  "source_classes": ["working"]
}
```

Prefetch projection checks:

```json
{
  "ordinary_prompt": {
    "has_conversation_carryover": true,
    "bad_markers": [],
    "suppressed_examples": [
      "Internal Reflection Context",
      "Context-Continuity",
      "Indexed Recall",
      "hermes02",
      "Status Snapshot",
      "governance_ops_gate_decision",
      "crystallized_candidates",
      "Audit Entries",
      "审计记录"
    ]
  },
  "diagnostic_prompt": {
    "has_conversation_carryover": false,
    "has_diagnostic_grounding": true
  }
}
```

Telegram validation transcript summary:

```text
/new
我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？
别像报告一样，像正常聊天一样说说你的感受。
```

Observed behavior:

- the model did not call `memory_os_status`
- the first answer no longer exposed `Internal Reflection Context`, `Indexed
  Recall`, `Audit Entries`, `hermes02`, `Status Snapshot`,
  `governance_ops_gate_decision`, or crystallized count wording
- the tone was still structured, but no longer mechanism-leaking
- the second answer responded naturally to the owner's style correction
- no actual send, execute, identity write, Hindsight export, or crystallized
  approval occurred

Post-Telegram host status before heartbeat catch-up:

```json
{
  "events": 24,
  "working_items": 17,
  "crystallized_candidates": 17,
  "crystallized_records": 0,
  "index_health": "mismatch",
  "doctor": "fail_due_to_index_count_mismatch"
}
```

The temporary doctor failure was caused by the expected append-only filesystem
to SQLite catch-up window after new Telegram turns. The heartbeat reconciled the
index:

```json
{
  "processed_event_count": 2,
  "processed_event_ids": [
    "evt_20260521T092446908689Z_30bafa5551",
    "evt_20260521T092512875409Z_f120c08da2"
  ],
  "working_created_count": 2,
  "candidate_created_count": 2,
  "crystallized_record_count": 0,
  "index_counts": {
    "events": 24,
    "working_items": 17,
    "crystallized_candidates": 17,
    "crystallized_records": 0
  }
}
```

Post-heartbeat status:

```json
{
  "events": 24,
  "working_items": 17,
  "crystallized_candidates": 17,
  "crystallized_records": 0,
  "index_health": "healthy",
  "doctor": "ok",
  "doctor_findings": ["hindsight_adapter_disabled"],
  "queue_backlog": 0
}
```

Boundary files:

```json
{
  "deep_reflection.working_updates.jsonl": false,
  "deep_reflection.optional_outputs.jsonl": false,
  "deep_reflection.wandering_seeds.jsonl": false,
  "crystallized_records": 0
}
```

Findings addressed during DR-08:

1. Deep Reflection cards originally used internal wording such as
   `governance thread` and `memory_os thread`.
   - Fixed by rewriting deterministic themes into foreground-natural wording.
   - Added tests to prevent `memory-os`, `memory_os`, `governance thread`, and
     `proposal queue` from leaking through injection cards.
2. Ordinary prefetch could still project stale diagnostic working/candidate
   summaries.
   - Fixed by expanding RH-21c filtering to working, review candidates,
     continuity bridge, and recent event summaries.
3. `memory_os_status` tool description was too broad and encouraged use in
   opinion/feeling prompts.
   - Fixed by limiting the tool contract to explicit current
     architecture/provider/backend/status/health/count questions.
4. The section title `Internal Reflection Context` itself was mechanism
   language.
   - Fixed by exposing the section as `Conversation Carryover`.

Verdict:

PASS for DR-08 on `10.20.3.200` with the following interpretation:

- `auto_bounded` Deep Reflection can be enabled on the test host without send,
  execute, identity, or crystallized-write boundary violations.
- Ordinary Telegram conversation receives bounded carryover context without
  explicit mechanism leakage after RH-21c tightening.
- Diagnostic prompts still bypass Deep Reflection and receive current
  Diagnostic Grounding.
- The remaining tone risk is model style, not a Memory-OS context leak; it can
  be tuned later through prompt/style policy if needed.

## Deep Reflection DR-07 Test Host Re-Evaluation

Date: 2026-05-21

Reason:

DR-08 initially kept DR-07 optional outputs disabled:

```json
{
  "working_updates_enabled": false,
  "self_evolution_proposals_enabled": false,
  "wandering_seed_enabled": false
}
```

That was useful for isolating the `auto_bounded` injection test, but it did not
prove that DR-07 can use real host data. On the `10.20.3.200` test host, DR-07
should be enabled under no-send boundaries so runtime behavior is observable.

Finding before fix:

- enabling DR-07 would have produced little useful runtime data because the
  deterministic analysis saw older working-memory items first
- latest style-correction turns such as `别像报告一样，像正常聊天一样说说你的感受`
  could be outside the default eight-item input window
- `wandering_seed` was not emitted by deterministic analysis, so the
  Wandering-seed path was only covered by hand-built unit fixtures

Code change:

- `_collect_working_items()` now sorts working items by `updated_at` and `ref`
  descending before applying the limit
- deterministic analysis can create a self-evolution topic from repeated
  report-style/tone feedback
- deterministic analysis can create a no-send wandering seed from carryover
  themes

Local verification:

```text
python -m pytest -q

255 passed
```

Remote package verification:

```text
python3 -m pytest \
  tests/system_modularization/test_deep_reflection_module.py \
  tests/plugins/memory/test_memory_os_prefetch.py \
  tests/plugins/memory/test_memory_os_lifecycle.py -q

45 passed
```

Test-host DR-07 configuration:

```json
{
  "enabled": true,
  "injection_mode": "auto_bounded",
  "working_updates_enabled": false,
  "self_evolution_proposals_enabled": true,
  "wandering_seed_enabled": true,
  "max_optional_outputs": 2,
  "max_self_evolution_proposals": 1,
  "max_wandering_seeds": 1
}
```

Controlled apply result:

```json
{
  "dry_run": false,
  "selected_optional_output_count": 2,
  "proposal_created_count": 1,
  "wandering_seed_created_count": 1,
  "working_updates_applied": false,
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_crystallized_approval": false
}
```

Generated self-evolution proposal:

```json
{
  "candidate_id": "prop_20260521T093627745201Z_aa81f796ec",
  "kind": "deep_reflection_self_evolution",
  "state": "candidate",
  "approval_purpose": "proposal_queue_only",
  "crystallized_approved": false,
  "title": "Tune ordinary memory conversation tone",
  "body": "Repeated owner feedback shows ordinary memory conversations benefit from less report-like wording and more natural continuity."
}
```

Generated wandering seed:

```json
{
  "schema_version": "hermes.deep_reflection.wandering_seed.v0",
  "delivery_mode": "no-send",
  "actual_send": false,
  "actual_execute": false,
  "seed_text": "A quiet sense of memory becoming shared ground rather than a report."
}
```

Post-apply status:

```json
{
  "events": 24,
  "working_items": 17,
  "crystallized_candidates": 17,
  "crystallized_records": 0,
  "index_health": "healthy",
  "doctor": "ok",
  "doctor_findings": ["hindsight_adapter_disabled"],
  "proposal_queue": {
    "candidate_count": 3,
    "state_counts": {
      "approved_for_proposal": 1,
      "candidate": 2
    },
    "delivery_mode": "no-send",
    "crystallized_approval_granted": false
  }
}
```

Boundary:

- DR-07 writes local proposal queue and wandering seed artifacts only
- no Telegram/message send occurred
- no shell/API execute occurred
- no identity file was written
- no crystallized record was created or approved
- `working_updates_enabled=false`, so working memory was not changed by DR-07

Verdict:

PASS for DR-07 controlled apply on `10.20.3.200`.

The test host should keep DR-07 optional outputs enabled for observation because
the host has no production workload and the no-send boundaries held. Future
production-like profiles can still leave these switches off until explicitly
approved.

### Deep Reflection Integrated Deployment Compatibility

The full installer treats Deep Reflection as a normal L2 system module:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --enable
```

The command above installs the module code but does not enable Deep Reflection
behavior by default.

For an empty test host such as `10.20.3.200`, the operator can deliberately
apply the observation preset in the same deployment command:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --enable \
  --deep-reflection-preset test-host
```

`test-host` enables:

```json
{
  "enabled": true,
  "injection_mode": "auto_bounded",
  "working_updates_enabled": false,
  "self_evolution_proposals_enabled": true,
  "wandering_seed_enabled": true,
  "llm_enabled": false
}
```

Production or formal profiles can instead write an explicit safe config:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --enable \
  --deep-reflection-preset production-safe
```

This keeps the integration deploy path compatible with the new L2 module while
preserving the expected default: install availability first, enable behavior
only by explicit profile config.

## RH-17 / RH-18 Test Host Dry-Run Validation

Date: 2026-05-21

Scope:

- deploy the current `main` branch at commit `6eb03e1`
- verify RH-17 retention/compaction CLI dry-run behavior
- verify RH-18 shadow journal status and ingest dry-run behavior
- do not run destructive cleanup apply
- do not run shadow journal apply

Deployment:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --enable \
  --deep-reflection-preset test-host
```

Installer evidence:

```json
{
  "provider": "memory_os",
  "enabled": true,
  "runtime_enabled": true,
  "system_modules_installed": true,
  "system_module_file_count": 52,
  "copied_files_include": ["shadow_journal.py"],
  "system_module_files_include": ["memory/memory_os/shadow_journal.py"]
}
```

Runtime timer:

```text
hermes-memory-os-heartbeat.timer: active/enabled
```

### RH-17 Cleanup Dry-Run

Command:

```bash
hermes memory_os cleanup --event-source-class-retention telemetry=30
```

Result:

```json
{
  "schema_version": "memory-os.cleanup_plan.v0",
  "dry_run": true,
  "policy": {
    "event_retention_days_by_source_class": {
      "telemetry": 30
    }
  },
  "action_count": 0
}
```

Interpretation:

- CLI accepted the explicit source-class retention policy
- cleanup remained dry-run
- no matching old telemetry event existed on the test host, so no actions were
  generated
- no canonical event, working item, candidate, crystallized record, identity
  file, or relationship file changed

### RH-18 Shadow Journal Dry-Run

Setup:

- wrote one temporary test spool frame to:

```text
/root/.hermes/memory-os/shadow-journal/rh18-smoke/spool.jsonl
```

- record schema:

```json
{
  "schema_version": "memory-os.shadow_journal_record.v0",
  "record_id": "rh18-smoke-dryrun-20260521",
  "producer": "rh18-smoke",
  "kind": "telemetry_status",
  "source_class": "telemetry",
  "summary": "RH-18 dry-run smoke telemetry frame."
}
```

Commands:

```bash
hermes memory_os shadow-journal status
hermes memory_os shadow-journal ingest
```

Result:

```json
{
  "status_schema": "memory-os.shadow_journal_status.v0",
  "ingest_schema": "memory-os.shadow_journal_ingest.v0",
  "pending_record_count": 1,
  "dry_run": true,
  "would_write_event_count": 1,
  "written_event_count": 0
}
```

Canonical counts before and after RH-17/RH-18 dry-run:

```json
{
  "before_counts": {
    "events": 24,
    "working_items": 17,
    "crystallized_candidates": 17,
    "crystallized_records": 0,
    "audit_entries": 300
  },
  "after_counts": {
    "events": 24,
    "working_items": 17,
    "crystallized_candidates": 17,
    "crystallized_records": 0,
    "audit_entries": 300
  },
  "counts_unchanged": true
}
```

Cleanup after dry-run:

```bash
rm -f /root/.hermes/memory-os/shadow-journal/rh18-smoke/spool.jsonl
rmdir /root/.hermes/memory-os/shadow-journal/rh18-smoke
```

Final shadow journal status:

```json
{
  "schema_version": "memory-os.shadow_journal_status.v0",
  "status": "ok",
  "pending_record_count": 0,
  "spool_file_count": 0,
  "malformed_record_count": 0
}
```

Doctor:

```json
{
  "status": "ok",
  "exit_code": 0,
  "findings": ["hindsight_adapter_disabled"]
}
```

Verdict:

PASS for RH-17/RH-18 dry-run validation on `10.20.3.200`.

Boundaries held:

- no cleanup apply
- no shadow journal apply
- no canonical event count change
- no working memory count change
- no crystallized candidate or record count change
- no identity write
- no send
- no execute

## RH-22 / RH-23 / RH-24 Unified Test Host Validation

Date: 2026-05-21

Scope:

- deploy current committed repo at commit `60a615e`
- verify RH-22 conversation-regression CLI and transcript evaluator
- verify RH-23 Deep Reflection injection source-class monitoring
- verify RH-24 `memory_os_status` tool contract reporting
- verify heartbeat/index catch-up and doctor after deployment
- restart only the test-host main gateway so the running process reloads the
  freshly deployed provider/tool contract

Deployment:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --enable \
  --deep-reflection-preset test-host
```

Installer evidence:

```json
{
  "provider": "memory_os",
  "enabled": true,
  "runtime_enabled": true,
  "system_modules_installed": true,
  "copied_file_count": 28,
  "system_module_file_count": 54,
  "copied_files_include": [
    "conversation_regression.py",
    "status_tool_contract.py"
  ],
  "system_module_files_include": [
    "memory/memory_os/conversation_regression.py",
    "memory/memory_os/status_tool_contract.py"
  ],
  "deep_reflection_preset": "test-host",
  "deep_reflection_config": {
    "enabled": true,
    "injection_mode": "auto_bounded",
    "working_updates_enabled": false,
    "self_evolution_proposals_enabled": true,
    "wandering_seed_enabled": true,
    "llm_enabled": false
  }
}
```

Provider and runtime checks:

```text
hermes memory:
  Provider: memory_os
  Plugin: installed
  Status: available
  memory_os: active

hermes-memory-os-heartbeat.timer: active/enabled

Installed files:
  /root/.hermes/plugins/memory_os/conversation_regression.py
  /root/.hermes/plugins/memory_os/status_tool_contract.py
  /root/.hermes/memory-os/runtime/python/plugins/memory/memory_os/conversation_regression.py
  /root/.hermes/memory-os/runtime/python/plugins/memory/memory_os/status_tool_contract.py
```

### RH-22 Conversation Regression

Prompt set command:

```bash
hermes memory_os conversation-regression prompts
```

Result:

```json
{
  "schema_version": "memory-os.conversation_regression_prompts.v0",
  "prompt_count": 7
}
```

Transcript evaluator command:

```bash
hermes memory_os conversation-regression evaluate \
  --transcript /tmp/rh22_transcript_pass.json
```

Result:

```json
{
  "schema_version": "memory-os.conversation_regression.v0",
  "status": "ok",
  "prompt_count": 3,
  "failure_count": 0,
  "warning_count": 0,
  "checks": [
    {
      "prompt_id": "casual_memory_system_change",
      "category": "casual",
      "memory_os_status_called": false
    },
    {
      "prompt_id": "diagnostic_current_architecture",
      "category": "diagnostic",
      "memory_os_status_called": true
    },
    {
      "prompt_id": "candidate_vs_crystallized",
      "category": "candidate_boundary",
      "memory_os_status_called": true
    }
  ]
}
```

Interpretation:

- ordinary memory-system conversation remains no-status-tool
- explicit architecture diagnostics allow `memory_os_status`
- candidate-vs-crystallized boundary fixture passes
- no private transcript bodies are recorded in this public report

### RH-23 Deep Reflection Source-Class Monitoring

Command:

```bash
PYTHONPATH=/root/.hermes/memory-os/runtime/python python3 - <<'PY'
from plugins.modules.cognition.deep_reflection import DeepReflectionModule
module = DeepReflectionModule('/root/.hermes', profile='default')
print(module.status())
print(module.preview_injection())
PY
```

Observed source-class distribution:

```json
{
  "status_schema": "hermes.deep_reflection_status.v0",
  "injection_mode": "auto_bounded",
  "current_injection_exists": true,
  "latest_injection_source_classes": {
    "selected_by_source_class": {
      "working": 2
    },
    "dropped_by_source_class": {
      "working": 1
    },
    "selected_total": 2,
    "dropped_total": 1
  },
  "rolling_injection_source_classes": {
    "selected_by_source_class": {
      "working": 14
    },
    "dropped_by_source_class": {
      "working": 7
    },
    "selected_total": 14,
    "dropped_total": 7,
    "window_report_count": 7
  },
  "preview_selected": 2,
  "preview_distribution": {
    "selected_by_source_class": {
      "working": 2
    },
    "dropped_by_source_class": {
      "working": 1
    },
    "selected_total": 2,
    "dropped_total": 1
  },
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_crystallized_approval": false
}
```

Interpretation:

- RH-23 status and preview expose latest and rolling source-class distribution
- current test-host cards still come from `working`, matching prior DR-08
  observations
- the monitoring is informational only and did not change card eligibility,
  ranking, safety filters, sends, executes, identity, or crystallized approval

### RH-24 Status Tool Contract

Command:

```bash
hermes memory_os conversation-regression status-tool-contract
```

Result:

```json
{
  "schema_version": "memory-os.status_tool_contract.v0",
  "tool_name": "memory_os_status",
  "validation": {
    "schema_version": "memory-os.status_tool_contract_validation.v0",
    "status": "ok",
    "findings": []
  }
}
```

Interpretation:

- the deployed provider exposes the maintained `memory_os_status` tool contract
- contract validation passed on the test host
- Chinese / mixed Chinese-English diagnostic and non-diagnostic fixture
  boundaries are available through the contract report

### RH-22 Full Seven-Prompt Baseline

Claude gate review noted that the deployed RH-22 prompt inventory contained
seven prompts, while the first transcript evaluator evidence only covered
three observed turns. The full public prompt set was therefore evaluated once
on `10.20.3.200` as a deterministic baseline.

Transcript path:

```bash
/tmp/rh22_transcript_full7.json
```

Command:

```bash
HERMES_HOME=/root/.hermes \
  hermes memory_os conversation-regression evaluate \
  --transcript /tmp/rh22_transcript_full7.json
```

Result:

```json
{
  "schema_version": "memory-os.conversation_regression.v0",
  "status": "ok",
  "prompt_count": 7,
  "failure_count": 0,
  "warning_count": 0,
  "failures": [],
  "warnings": []
}
```

Prompt coverage:

```text
casual_memory_system_change      memory_os_status_called=false
memory_design_opinion            memory_os_status_called=false
casual_style_correction          memory_os_status_called=false
diagnostic_current_architecture  memory_os_status_called=true
diagnostic_provider              memory_os_status_called=true
diagnostic_hindsight_canonical   memory_os_status_called=true
candidate_vs_crystallized        memory_os_status_called=true
```

Interpretation:

- all seven public RH-22 regression prompts now have a passing deterministic
  baseline on the test host
- ordinary/casual prompts do not call `memory_os_status`
- explicit architecture/provider/Hindsight/candidate-boundary prompts may call
  `memory_os_status`
- candidate wording remains separated from approved crystallized memory

### Heartbeat, Doctor, And Gateway Reload

Heartbeat command:

```bash
hermes memory_os heartbeat --max-events 100
```

Heartbeat result:

```json
{
  "schema_version": "memory-os.heartbeat.v0",
  "total_event_count": 24,
  "already_processed_event_count": 24,
  "processed_event_count": 0,
  "candidate_count": 17,
  "candidate_created_count": 0,
  "working_item_count": 17,
  "crystallized_record_count": 0,
  "index_counts": {
    "events": 24,
    "working_items": 17,
    "crystallized_candidates": 17,
    "crystallized_records": 0,
    "audit_entries": 319
  }
}
```

Doctor command:

```bash
hermes memory_os doctor
```

Doctor result:

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

Gateway reload:

```text
hermes-gateway.service:
  before_pid: 435355
  after_pid: 436233
  active: active
```

Verdict:

PASS for RH-22/RH-23/RH-24 unified validation on `10.20.3.200`.

Boundaries held:

- no send
- no execute
- no identity write
- no crystallized approval
- no Hindsight export
- no destructive cleanup apply
- no shadow journal apply
- Deep Reflection source-class monitoring remained observational
- `memory_os_status` contract is available and validated

## Memory-OS Agent OS Shell Validation (2026-05-21)

Scope:

- install and enable the official-style `memory-os-agent-os` user plugin shell
- keep `memory.provider=memory_os` as the authoritative provider path
- expose `hermes memory-os-agent-os status`
- expose `hermes memory-os-agent-os doctor`
- register minimal session marker hooks only
- verify the shell does not conflict with existing provider/runtime operation

Live host findings:

```text
Hermes Agent version: v0.14.0 (2026.5.16)
memory.provider: memory_os
plugins.enabled: ["memory-os-agent-os"]
memory-os-agent-os: enabled user plugin
memory_os: installed memory provider, not enabled as a general plugin
hermes-gateway.service: active
hermes-memory-os-heartbeat.timer: active/enabled
```

Validation commands:

```bash
HERMES_HOME=/root/.hermes hermes plugins list
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
```

Alias results:

```json
{
  "status_alias": "ok",
  "doctor_alias": "ok",
  "doctor_exit_code": 0,
  "doctor_findings": ["hindsight_adapter_disabled"],
  "events": 24,
  "working_items": 17,
  "crystallized_candidates": 17,
  "crystallized_records": 0,
  "prefetch_mode": "indexed"
}
```

Hook marker validation:

The installed Hermes source was inspected before enabling hooks. The live
`on_session_start` path passes `session_id`, `model`, and `platform`; reset and
finalize paths pass `session_id` and `platform`.

Synthetic hook invocation wrote bounded audit-only markers:

```json
[
  {
    "action": "agent_os_shell_session_started",
    "target": "memory-os-agent-os",
    "details": {
      "hook": "on_session_start",
      "session_id": "shell-hook-test-start",
      "platform": "codex-test",
      "model": "test-model"
    }
  },
  {
    "action": "agent_os_shell_session_reset",
    "target": "memory-os-agent-os",
    "details": {
      "hook": "on_session_reset",
      "session_id": "shell-hook-test-reset",
      "platform": "codex-test"
    }
  },
  {
    "action": "agent_os_shell_session_finalized",
    "target": "memory-os-agent-os",
    "details": {
      "hook": "on_session_finalize",
      "session_id": "shell-hook-test-finalize",
      "platform": "codex-test"
    }
  }
]
```

Implementation finding:

An early test copy left a backup tree under `/root/.hermes/plugins/`. Hermes'
scanner found the nested `memory-os-agent-os` manifest and registered the CLI
command twice, causing the stale backup to shadow the clean plugin. The backup
was moved to `/root/.hermes/plugin-backups/`, outside the plugin scan tree.

Boundaries:

- no send
- no execute
- no identity write
- no crystallized approval
- no Hindsight export
- no carryover injection from plugin hooks
- no `pre_llm_call` registration
- no slash command registration
