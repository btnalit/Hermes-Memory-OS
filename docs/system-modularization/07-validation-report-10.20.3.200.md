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

## Current Truth Note

This file is an append-only validation and evidence log. It intentionally keeps
historical findings, superseded command shapes, failed gateway-hook attempts,
and older smoke-test transcripts.

Do not infer the current owner-review architecture from an older section in
this file. The current design authority is:

- `29-memory-os-module-integration-contract.md` for the Hermes-agent versus
  Memory-OS-plugin boundary;
- `34-owner-review-digest-and-action-workflow.md` "Current Architecture Truth"
  for owner review digest and action flow;
- `36-module-closure-matrix.md` for module closure and backflow routing.

Current owner-review truth:

```text
Hermes agent owns user-facing interaction and clarification.
Memory-OS owns bounded payloads, stable action tokens, tools/state machines,
OwnerActionProcessor, audit, and monitor evidence.
Display anchors are UI labels; Memory-OS executes only stable oa_ tokens.
Gateway hard interception is not the primary path.
```

## 2026-05-26 RH-34i Owner Agenda Push Live Evidence

Scope: `10.20.3.200` staging host only.

Evidence level: `live PASS` for recurring owner-review agenda rendering and
`monitor PASS` for the new agenda-specific probe. Overall monitor remains
`WARN` because unrelated observation items remain open.

Finding:

The 2026-05-26 Telegram digest showed global backlog counts such as
`pending=218`, `review_suggested=37`, and `fyi=169`. That was useful as a
debug/review surface, but it was too much for a mature daily owner agenda. A
daily push should contain decisions and true alerts, not every backlog class.

Actions performed:

- Added `agenda` mode to `review preview-digest` and `review render-digest`.
- Changed `memory_os_owner_review_digest.py` to default to agenda mode for
  Hermes cron delivery.
- Fixed `_digest_items(limit=0)` so suppressed sections stay empty instead of
  leaking one FYI/review item.
- Updated the recurring Hermes cron prompt through
  `memory_os_owner_review_cron_gate.py --owner-approved --apply` so Hermes
  treats Script Output as today's decision agenda and does not expand
  Review Suggested/FYI/backlog totals.
- Triggered the existing `memory-os-owner-review-digest` cron job
  (`2af755464ca8`) through Hermes cron.
- Ran `python scripts/memory_os_3_200_monitor.py --host hermes-media --output summary`.

Key evidence:

```text
cron_job=memory-os-owner-review-digest
prompt_has_today_agenda=true
prompt_has_old_full_picture_rule=false
helper_output_title=Memory-OS 今日审批议程
agenda.section_counts={'action_required': 3, 'review_suggested': 0, 'fyi': 0}
agenda.review_suggested_suppressed=true
agenda.fyi_suppressed=true
agenda.backlog_totals_suppressed=true
agenda.text_char_count=1266
agenda.raw_body_included=false
agenda.text_has_internal_schema=false
monitor_pass=owner_review_agenda_digest_ok
FAIL=[]
```

Residual state:

- The pull/debug review surface still reports full counts
  (`pending=222`, `review_suggested=41`, `fyi=169`) by design. Those counts are
  no longer part of the recurring owner agenda push.
- Current monitor status remains `WARN` for existing non-blocking items:
  left-brain pipeline warning, SessionMirror pending sessions, approved
  proposal follow-up, RH-31 eval failures, and RH-26 casual empty warning.

## 2026-05-26 RH-34j Proposal Agenda Eligibility Live Evidence

Scope: `10.20.3.200` staging host only.

Evidence level: `live PASS` for suppressing blind/generic proposal approvals
from the recurring agenda and `monitor PASS` for the agenda digest probe.
Overall monitor remains `WARN` because unrelated observation items remain open.

Finding:

After RH-34i, the recurring Telegram agenda became short enough, but it still
asked the owner to approve items titled `Self-Evolution dry-run proposal`.
The owner could see action tokens but not the concrete content being approved.
Live inspection showed those proposals were historical template proposals with
generic bodies such as `Use the highest evidence signal to prepare a reviewed
governance improvement.` They are not mature owner-approvable agenda items.

Actions performed:

- Added proposal agenda eligibility checks in `OwnerReview`.
- Generic/template Self-Evolution proposals are now downgraded to
  `Review Suggested` maturation items and render no approve/reject commands.
- Concrete proposals keep agenda eligibility only when they expose bounded
  owner-readable `proposal_detail`.
- Deployed the runtime patch to `10.20.3.200`.
- Ran the owner-review agenda helper and the live monitor summary.

Key evidence:

```text
owner_review_queue.action_required_total=0
owner_review_queue.review_suggested_total=55
generic_self_evolution_requires_maturation=true
generic_self_evolution_action_commands=[]
agenda.helper_stdout_empty=true
agenda.section_counts={'action_required': 0, 'review_suggested': 0, 'fyi': 0}
agenda.review_suggested_suppressed=true
agenda.fyi_suppressed=true
agenda.backlog_totals_suppressed=true
agenda.raw_body_included=false
agenda.text_has_internal_schema=false
monitor_pass=owner_review_agenda_digest_ok
FAIL=[]
```

Current behavior:

- The recurring owner agenda is silent when there is no mature Action Required
  item or true alert.
- Generic Self-Evolution templates remain discoverable through pull/debug
  review surfaces for maturation analysis, but they cannot ask the owner for
  blind approval.
- The next runtime quality task is to make Self-Evolution produce concrete
  proposals with a specific change, evidence, acceptance criteria, and
  follow-up state instead of generic dry-run templates.

## 2026-05-26 P1-S Slice 3 SelfEvolution Proposal Quality Live Evidence

Scope: `10.20.3.200` staging host only.

Evidence level: `live PASS` for concrete SelfEvolution proposal generation and
`monitor PASS` for agenda visibility. Overall monitor remains `WARN` because
unrelated observation items remain open.

Finding:

RH-34j correctly suppressed historical generic template proposals, but the
producer still needed to create mature proposal content. Without that, the
daily owner agenda would either be silent forever or eventually reintroduce
blind approvals.

Actions performed:

- Changed SelfEvolution proposal generation to create bounded owner-readable
  proposal bodies with `具体改动`, `证据`, `验收标准`, `后续状态`, and `边界`.
- Added a migration rule so legacy generic template proposals do not block a
  new concrete proposal.
- Kept execution separated: proposal creation still goes through OpsGate
  report-only, and `actual_execute=false`.
- Deployed the producer and owner-agenda renderer to `10.20.3.200`.
- Ran SelfEvolution once against live evidence and inspected the agenda helper
  output without triggering a Telegram send.
- Localized the one English proposal generated during this test slice before it
  could be pushed.

Key live evidence:

```text
self_evolution.result.proposal_created=true
self_evolution.result.proposal_id=prop_20260526T130854189767Z_de39e32be1
new_proposal.kind=expression_policy
new_proposal.title=调整右脑表达策略：too_mechanical 反馈
new_proposal.body contains 具体改动/证据/验收标准/后续状态/边界
new_proposal.actual_execute=false
agenda.action_required_total=1
agenda.action_required_shown=1
agenda.text_char_count=988
agenda.review_suggested_suppressed=true
agenda.fyi_suppressed=true
agenda.raw_body_included=false
monitor_pass=owner_review_agenda_digest_ok
FAIL=[]
```

Current behavior:

- The next daily agenda can show one concrete proposal about right-brain
  expression policy, with enough content for the owner to understand the
  approval target.
- Approval still means `approved_for_proposal` only. It does not change prompt,
  cadence, SpeakGate policy, route, schedule, send behavior, or execution.
- The next quality gate is to make the follow-up proposal/opsgate path turn
  this approved idea into a concrete manual-apply decision without creating an
  execution ticket automatically.

## 2026-05-26 Owner Approval Smoke For Concrete SelfEvolution Proposal

Scope: `10.20.3.200` staging host only.

Evidence level: `live PASS` for the owner action path and `monitor PASS` for
post-approval follow-up visibility. Overall monitor remains `WARN` because
unrelated observation items remain open.

Live interaction:

```text
Cronjob Response: memory-os-owner-review-digest
owner command: memory approve oa_8ede56a11b98d8
Hermes agent: memory_os_review_reply...
Hermes agent: 已批准 oa_8ede56a11b98d8。
```

Verified state:

```text
proposal_id=prop_20260526T130854189767Z_de39e32be1
proposal.kind=expression_policy
proposal.title=调整右脑表达策略：too_mechanical 反馈
proposal.state=approved_for_proposal
proposal.followup_state=awaiting_ops_gate
proposal.execution_decision_state=not_requested
proposal.execution_ticket_count=0
proposal.actual_execute=false
owner_action.action_type=approve_proposal
owner_action.channel=telegram
owner_action.result=applied
owner_action.boundary.actual_execute=false
owner_action.boundary.actual_send=false
owner_action.boundary.actual_identity_write=false
owner_action.boundary.actual_unapproved_crystallized_approval=false
followup_surface.awaiting_ops_gate_count=7
followup_surface.execution_ticket_count=0
followup_surface.actual_execute=false
monitor.FAIL=[]
```

Additional delivery finding:

The real Telegram digest preserved the proposal title, consequence, and token,
but Hermes agent delivery summarized away the proposal detail (`具体改动`,
`证据`, `验收标准`, `后续状态`, `边界`). The underlying helper output was correct;
the loss happened in the Hermes cron agent wording layer. The cron gate prompt
was updated in place to require preserving Script Output `内容:` as
`审批内容:` and to keep the concrete proposal detail fields instead of
summarizing them to a title.

Prompt update evidence:

```text
cron_job=memory-os-owner-review-digest
job_id=2af755464ca8
cron_gate.status=updated
prompt contains 审批内容
prompt contains 具体改动/证据/验收标准/后续状态/边界
render_check.raw_body_included=false
render_check.internal_schema_primary=false
monitor.OwnerProposalFollowups.approved=8
monitor.OwnerProposalFollowups.execution_tickets=0
monitor.OwnerProposalFollowups.actual_execute=false
monitor.FAIL=[]
```

## 2026-05-26 Approved Proposal OpsGate Follow-Up Live Evidence

Scope: `10.20.3.200` staging host only.

Evidence level: `live PASS` for routing one owner-approved proposal into
OpsGate report-only follow-up and `monitor PASS` for follow-up visibility.
Overall monitor remains `WARN` because unrelated observation items remain open.

Action:

```text
hermes memory-os-agent-os review proposal-followups \
  --proposal-id prop_20260526T130854189767Z_de39e32be1 \
  --ops-gate --owner owner --channel telegram --apply
```

Result:

```text
status=ok
proposal_id=prop_20260526T130854189767Z_de39e32be1
proposal_state=approved_for_proposal
ops_gate_report_written=true
ops_gate_result.status=ok
ops_gate_result.execution_mode=report-only
ops_gate_result.report_id=opsr_20260526T133309722377Z_1f07092f4c
ops_gate_result.decisions[0].decision=would_allow
execution_ticket_created=false
actual_execute=false
raw_body_included=false
```

Idempotency check:

```text
second_apply.status=duplicate_ignored
second_apply.existing_ops_gate_review.report_id=opsr_20260526T133309722377Z_1f07092f4c
second_apply.ops_gate_report_written=false
second_apply.execution_ticket_created=false
second_apply.actual_execute=false
```

Follow-up surface after apply:

```text
followup_state=ops_gate_reviewed_awaiting_explicit_execution
ops_gate_decision=would_allow
ops_gate_report_id=opsr_20260526T133309722377Z_1f07092f4c
OwnerProposalFollowups.approved=8
OwnerProposalFollowups.awaiting_ops_gate=6
OwnerProposalFollowups.ops_gate_reviewed=2
OwnerProposalFollowups.execution_tickets=0
OwnerProposalFollowups.actual_execute=false
monitor.FAIL=[]
```

Current boundary:

- The approved proposal is now ready for a separate explicit execution/apply
  design or owner decision.
- No execution ticket exists.
- No prompt, route, send, schedule, or runtime behavior changed.

## 2026-05-26 Runtime Closure Live Evidence

Scope: `10.20.3.200` staging host only.

Evidence level: `live PASS` for the right-brain expression feedback path and
`monitor PASS` for the bounded scoring/governance visibility. Overall monitor
classification remains `WARN` because unrelated long-running observation items
remain open.

Actions performed:

- Deployed runtime patch for owner-review speak items to expose expression
  feedback commands in the owner digest, for example
  `memory feedback oa_<token> too_mechanical`.
- Restarted `hermes-gateway.service` on `10.20.3.200` so Hermes agent sees the
  updated structured tool schema and guard.
- Triggered the existing `memory-os-owner-review-digest` cron job. The rendered
  Telegram digest showed bounded right-brain expression content plus feedback
  tokens for `like_expression`, `too_mechanical`, `too_frequent`,
  `boundary_private`, and `off_voice`.
- Applied one structured Hermes-agent tool smoke:
  `action=feedback`, `rating=too_mechanical`,
  `action_token=oa_5f5b13773e0f0a`. Result: `status=ok`,
  `target_type=expression`, `feedback_id=efb_20260526T120942975704Z_b7c95cd5`.
- Ran `hermes-memory-os-cognitive-loop.service` manually. Result:
  `status=0/SUCCESS`.
- Ran `python scripts/memory_os_3_200_monitor.py --host hermes-media --output summary`.

Key monitor values after the live smoke and the follow-up EvidenceScoring
rating propagation fix:

```text
classification=WARN
FAIL=[]
structured_review_reply_count=1
reply_fallback_used_count=0
expression_feedback.feedback_count=2
expression_feedback.raw_body_included_count=0
expression_feedback.live_policy_changed_count=0
evidence.expression_feedback_subject_count=2
evidence.score_count=508
evidence.score_mode=feature_maturity_v2
evidence.feature_score_mode=primary
evidence.hash_score_legacy_count=0
evidence.expired_used_in_scoring_count=0
governance_feedback.emitted_event_count=132
speak_gate.actual_send=false
right_brain_expression_adapter.latest_delivery_mode=hermes_cron_agent
OwnerReview.by_type.too_mechanical=2
```

EvidenceScoring check:

```text
expression_feedback:efb_20260526T115723492542Z_fcce47d5 feedback_rating=too_mechanical
expression_feedback:efb_20260526T120942975704Z_b7c95cd5 feedback_rating=too_mechanical
```

Boundary result:

```text
actual_send=false
actual_execute=false
actual_identity_write=false
actual_unapproved_crystallized_approval=false
raw_body_included=false
```

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

## PS-04 / PS-05 Installer-Level Shell Validation (2026-05-21)

Scope:

- deploy through `scripts/install_memory_os_plugin.py`, not manual plugin copy
- install Memory-OS provider, Agent OS shell plugin, portable module runtime,
  agent runtime, DeepReflection test-host config, and heartbeat runtime/timer
- enable provider and shell as two separate states
- verify backup protection keeps Memory-OS backup manifests outside
  `$HERMES_HOME/plugins/`
- re-run RH-22/RH-23/RH-24 after installer deployment

Installer command:

```bash
python3 /tmp/memory-os-ps04-source/scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --enable \
  --enable-shell \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --runtime-interval 5min \
  --deep-reflection-preset test-host
```

Installer output was redirected to `/tmp/ps04-install-apply.json` and verified
as pure JSON after suppressing the noisy `hermes config set` stdout from the
provider-enable subprocess. `stderr` was empty.

Installer result summary:

```json
{
  "provider": "memory_os",
  "enabled": true,
  "agent_os_shell": "memory-os-agent-os",
  "agent_os_shell_installed": true,
  "agent_os_shell_enabled": true,
  "agent_os_shell_enable_action": "config_yaml",
  "system_modules_installed": true,
  "runtime_artifacts_installed": true,
  "runtime_enabled": true,
  "deep_reflection_preset": "test-host"
}
```

Deployment state:

```text
hermes memory:
  Provider: memory_os
  memory_os (local) ← active

hermes plugins list:
  memory-os-agent-os  enabled      user
  memory_os           not enabled  user

systemd:
  hermes-memory-os-heartbeat.timer active/enabled
  hermes-gateway.service active
```

Alias and doctor checks:

```json
{
  "memory_os_status": {
    "events": 24,
    "working_items": 17,
    "crystallized_candidates": 17,
    "crystallized_records": 0,
    "prefetch_mode": "indexed"
  },
  "shell_status": "same output as memory_os status",
  "shell_doctor": {
    "status": "ok",
    "exit_code": 0,
    "findings": ["hindsight_adapter_disabled"]
  }
}
```

Hook smoke:

The installed shell hook functions were invoked with a Telegram-shaped session
marker. This is a hook smoke, not a natural Telegram `/new` event.

```json
{
  "before_counts": {
    "audit_entries": 375,
    "events": 24,
    "working_items": 17,
    "crystallized_candidates": 17,
    "crystallized_records": 0
  },
  "after_counts": {
    "audit_entries": 378,
    "events": 24,
    "working_items": 17,
    "crystallized_candidates": 17,
    "crystallized_records": 0
  },
  "delta_counts": {
    "audit_entries": 3,
    "events": 0,
    "working_items": 0,
    "crystallized_candidates": 0,
    "crystallized_records": 0
  },
  "markers": [
    "agent_os_shell_session_started",
    "agent_os_shell_session_reset",
    "agent_os_shell_session_finalized"
  ]
}
```

Unified regression after installer deployment:

```json
{
  "rh22_full_prompt_count": 7,
  "rh22_status": "ok",
  "rh22_failure_count": 0,
  "rh22_warning_count": 0,
  "rh24_status_tool_contract": "ok",
  "rh24_findings": []
}
```

RH-23 source-class monitoring remained observational:

```json
{
  "injection_mode": "auto_bounded",
  "current_injection_exists": true,
  "latest_injection_source_classes": {
    "selected_by_source_class": {"working": 2},
    "dropped_by_source_class": {"working": 1},
    "selected_total": 2,
    "dropped_total": 1
  },
  "rolling_injection_source_classes": {
    "selected_by_source_class": {"working": 14},
    "dropped_by_source_class": {"working": 7},
    "selected_total": 14,
    "dropped_total": 7,
    "window_report_count": 7
  },
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_crystallized_approval": false
}
```

Heartbeat catch-up and final doctor:

```json
{
  "heartbeat": {
    "total_event_count": 24,
    "already_processed_event_count": 24,
    "processed_event_count": 0,
    "working_created_count": 0,
    "candidate_created_count": 0,
    "crystallized_record_count": 0,
    "index_counts": {
      "audit_entries": 379,
      "events": 24,
      "working_items": 17,
      "crystallized_candidates": 17,
      "crystallized_records": 0
    }
  },
  "doctor": {
    "status": "ok",
    "exit_code": 0,
    "findings": ["hindsight_adapter_disabled"]
  }
}
```

Implementation findings resolved in PS-04:

- provider enablement previously printed `hermes config set` status text into
  installer stdout; PS-04 suppresses that subprocess stdout so installer output
  remains machine-readable JSON
- Memory-OS backup manifests under `$HERMES_HOME/plugins/` can be scanned as
  live plugins; PS-04 rejects backup-looking Memory-OS provider/shell manifests
  under the plugin scan tree and directs backups to
  `$HERMES_HOME/plugin-backups/`
- the guard no longer rejects unrelated legitimate user plugins such as
  `hermes-self-evolution`

Boundaries:

- provider remains selected by `memory.provider=memory_os`
- `memory-os-agent-os` is enabled as the official-style user plugin shell
- `memory_os` is not enabled as a general plugin
- shell hooks write audit markers only
- no events, working items, candidates, crystallized records, sends, executes,
  identity writes, Hindsight exports, `pre_llm_call` injection, or slash
  commands were introduced by the shell

## Read-Only Monitor Snapshot Review (2026-05-21)

This section records the first external `memory-os-3-200-monitor` style
snapshot after PS-04/PS-05, plus a direct read-only Codex recheck on
`hermes-media`. No recovery action was taken.

User-provided monitor snapshot:

```text
host: debian
snapshot_time: 2026-05-21 13:35:59 EDT
provider: memory_os
status counts:
  audit_entries=492
  crystallized_candidates=22
  crystallized_records=0
  events=29
  working_items=22
index_health.state=healthy
prefetch_mode=indexed
queue_backlog=0
doctor.status=ok
doctor.exit_code=0
status-tool-contract.validation.status=ok
DeepReflection:
  enabled=true
  injection_mode=auto_bounded
  latest selected=working:2, dropped=1
  rolling selected=working:14, dropped=7
disk /root/.hermes/memory-os mount:
  total=754G, used=170G, available=547G, use=24%
```

The same snapshot reported these WARN conditions:

```text
hermes-gateway.service: inactive, MainPID=0
hermes-memory-os-heartbeat.timer: inactive, not-found
hindsight_adapter_enabled=false
```

`hindsight_adapter_enabled=false` remains expected for this deployment because
Hindsight is an optional adapter, not the canonical Memory-OS store.

Direct read-only recheck from Codex immediately afterwards:

```bash
ssh hermes-media \
  "systemctl --user show hermes-gateway.service \
     -p LoadState -p ActiveState -p SubState -p MainPID \
     -p FragmentPath -p UnitFileState"
```

Result:

```text
LoadState=loaded
ActiveState=active
SubState=running
FragmentPath=/root/.config/systemd/user/hermes-gateway.service
UnitFileState=enabled
MainPID=440371
```

Heartbeat timer recheck:

```bash
ssh hermes-media \
  "systemctl --user show hermes-memory-os-heartbeat.timer \
     -p LoadState -p ActiveState -p SubState -p UnitFileState \
     -p FragmentPath"
```

Result:

```text
LoadState=loaded
ActiveState=active
SubState=waiting
FragmentPath=/root/.config/systemd/user/hermes-memory-os-heartbeat.timer
UnitFileState=enabled
```

Timer list:

```text
NEXT                            LEFT      LAST                             PASSED
Thu 2026-05-21 13:43:07 EDT     2min 59s  Thu 2026-05-21 13:38:07 EDT      2min 0s ago
UNIT                             ACTIVATES
hermes-memory-os-heartbeat.timer hermes-memory-os-heartbeat.service
```

Plugin state recheck:

```text
memory-os-agent-os  enabled      user
memory_os           not enabled  user
```

Memory-OS status recheck:

```json
{
  "counts": {
    "audit_entries": 500,
    "crystallized_candidates": 23,
    "crystallized_records": 0,
    "events": 31,
    "working_items": 23
  },
  "index_counts": {
    "audit_entries": 498,
    "crystallized_candidates": 23,
    "crystallized_records": 0,
    "events": 30,
    "working_items": 23
  },
  "index_health": {
    "state": "stale",
    "fts_tokenizer": "trigram"
  },
  "prefetch_mode": "indexed",
  "queue_backlog": 0
}
```

Doctor recheck:

```json
{
  "status": "ok",
  "exit_code": 0,
  "findings": [
    {
      "code": "index_stale",
      "severity": "warning"
    },
    {
      "code": "hindsight_adapter_disabled",
      "severity": "warning"
    }
  ]
}
```

Status-tool contract recheck:

```json
{
  "validation": {
    "status": "ok",
    "findings": []
  }
}
```

Interpretation:

- The user-provided gateway/timer WARN was not reproduced by direct read-only
  systemd recheck; both units were loaded, enabled, and active at recheck time.
- The recheck found the expected provider/shell split:
  `memory.provider=memory_os`, `memory-os-agent-os` enabled, and `memory_os`
  not enabled as a general plugin.
- Memory-OS remained operational: queue backlog was `0`, `prefetch_mode` stayed
  `indexed`, status-tool contract validation stayed `ok`, and
  `crystallized_records` stayed `0`.
- The direct recheck did observe `index_stale`, with the filesystem ahead by
  one event and two audit entries. This is a WARN-level heartbeat catch-up
  condition, not a doctor failure.
- No heartbeat catch-up, gateway restart, hook replay, cleanup apply, or other
  recovery action was run during this review.

Follow-up:

- Keep watching whether the monitor ever repeats gateway inactive or timer
  not-found. If it repeats while direct `systemctl --user show` says active,
  improve the monitor to collect `LoadState`, `FragmentPath`, and
  `UnitFileState` before classifying that condition.
- Let the active heartbeat timer catch up the stale index naturally unless
  owner explicitly asks for manual heartbeat catch-up.

## Automation Snapshot Delta Review (2026-05-21 23:37Z)

The `memory-os-3-200-monitor` automation later produced another read-only
snapshot:

```text
automation_id: memory-os-3-200-monitor
run_time_utc: 2026-05-21T23:37:47Z
host: debian
```

Automation summary:

```text
PASS provider=memory_os
PASS status index_health=healthy, prefetch_mode=indexed
PASS doctor.status=ok, exit_code=0
PASS status-tool-contract.validation.status=ok
PASS DeepReflection enabled=true, injection_mode=auto_bounded
PASS disk usage=25%, 174G/754G
WARN gateway inactive, PID=0
WARN heartbeat timer inactive, enabled state empty/unstable
WARN hindsight_adapter_disabled, expected
counts: audit_entries=742, events=52, working_items=45, queue_backlog=0
```

Manual read-only recheck after this automation snapshot:

```text
remote_time: 2026-05-21T21:27:06-04:00
gateway: loaded, active/running, enabled, MainPID=440371
heartbeat_timer: loaded, active/waiting, enabled
provider/plugin split: memory-os-agent-os enabled; memory_os not enabled as
                       general plugin
doctor.status=ok
doctor.findings=[hindsight_adapter_disabled]
status-tool-contract.validation.status=ok
disk usage=25%, 174G/754G
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

Delta from the automation snapshot to manual recheck:

```text
audit_entries: +50
events: +2
working_items: +2
queue_backlog: 0 -> 0
crystallized_records: stayed 0
disk usage: stayed 25%
```

DeepReflection recheck:

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

- The automation again reported gateway/timer inactivity, but the richer manual
  systemd recheck again found both units loaded, active, and enabled.
- The repeated discrepancy suggests the monitor should record `LoadState`,
  `FragmentPath`, and `UnitFileState` before treating service/timer checks as a
  hard runtime FAIL.
- Memory-OS data continued to grow with `queue_backlog=0`, healthy index, and
  no crystallized records.
- DeepReflection remained in safe `auto_bounded` mode. The source-class skew
  remained unchanged: selected and dropped injection cards still came only from
  `working`.
- No recovery action was taken.

## Small-Context Compression Drift Investigation (2026-05-22)

Trigger:

- A real Telegram/Hermes session running a long ComfyUI install/download task
  hit repeated context compaction in a small-context workflow.
- After compaction, the assistant resumed with an unrelated Memory-OS/Hindsight
  explanation instead of continuing the active ComfyUI task.
- The user reported this as a practical usability failure: Hermes could not be
  used reliably for long jobs under that context mode.

Read-only classification work:

```text
scope: 10.20.3.200 source/log inspection
mutation: none
private bodies printed: no
```

Evidence:

- `Compacting context -- summarizing earlier conversation so I can continue`
  is emitted by Hermes at
  `/usr/local/lib/hermes-agent/run_agent.py`.
- `Preflight compression` is also emitted by Hermes at
  `/usr/local/lib/hermes-agent/run_agent.py`.
- Gateway long-running updates such as `Still working...` are emitted by Hermes
  gateway code at `/usr/local/lib/hermes-agent/gateway/run.py`.
- The observed session log showed automatic preflight compression with
  `focus=None`:

```text
session=20260521_220646_3c3d23
preflight_tokens=159123
threshold_tokens=136000
model=gpt-5.4-mini
context_length=272000
messages=148
focus=None
```

- Hermes has a compression `focus_topic` mechanism, but the automatic preflight
  compression path did not pass one.
- Hermes calls `MemoryManager.on_pre_compress(messages)` before compression,
  but the `run_agent.py` call path does not consume the returned provider text.
- The installed `memory_os` provider currently returns an empty string from
  `on_pre_compress()`.

Conclusion:

```text
not: Codex CLI-only issue
not: canonical Memory-OS data corruption
not: DeepReflection safety failure
not: approved long-term memory drift

classification: Hermes foreground compression/resume task-focus drift, with a
                Memory-OS provider hook seam that is currently unused/empty
```

Operational impact:

- Memory-OS can remain healthy while the foreground turn loses the current task
  after automatic compression.
- This is especially likely in long-running tool jobs where process output,
  web search, installation logs, and historical high-salience memory compete for
  the compressed context budget.

Follow-up recorded:

- `08-runtime-hardening-plan.md` now tracks `RH-25 Small-Context Session Task
  Anchor`.
- `20-hermes-compression-hook-gap.md` records the cross-boundary Hermes hook gap
  and the Memory-OS mitigation.
- Memory-OS now implements a bounded `current_task_anchor` through
  `on_pre_compress()`, provider prefetch, and `system_prompt_block()`.
- A full root-cause fix still needs Hermes to consume provider hook return text
  or pass a generated `focus_topic` into automatic preflight compression.

## RH-25 Deployment Verification (2026-05-22)

Scope:

```text
host: 10.20.3.200 / hermes-media
deployment: install_memory_os_plugin.py full install
mutation: Memory-OS provider/runtime/shell reinstall on test host
gateway: restarted after install to load provider code
```

Local verification before deployment:

```text
python -m pytest -q
300 passed
```

Installer result:

```text
provider: memory_os
agent_os_shell: memory-os-agent-os
copied provider files: 28
system module files: 56
agent runtime files: 2
runtime timer: enabled
deep_reflection_preset: test-host
```

Gateway state after restart:

```text
ActiveState=active
SubState=running
MainPID=448893
```

Synthetic current-task anchor probe:

```text
prefetch_has_foreground=True
prefetch_preserves_original_task=True
prefetch_preserves_error=True
prompt_has_anchor=True
```

This probe used a synthetic ComfyUI Impact Pack task and verified that a generic
follow-up query (`continue current task`) does not overwrite the more specific
pre-compression task anchor.

Memory-OS health after deployment:

```text
doctor_status=ok
exit_code=0
findings=[
  ("index_stale", "warning"),
  ("hindsight_adapter_disabled", "warning")
]
```

Status excerpt:

```text
counts:
  audit_entries=889
  crystallized_candidates=59
  crystallized_records=0
  events=67
  working_items=59
index_health=stale
queue_backlog=0
prefetch_mode=indexed
```

Heartbeat timer:

```text
LoadState=loaded
ActiveState=active
SubState=waiting
UnitFileState=enabled
```

Interpretation:

- RH-25 is installed and active on the test host.
- The Memory-OS-side mitigation works for synthetic task-anchor extraction,
  same-turn system prompt fallback, and next-turn prefetch carryover.
- `index_stale` is a warning-level catch-up condition after deployment activity,
  not a doctor failure. No manual heartbeat was run in this verification.
- The Hermes upstream hook gap remains: provider-returned
  `on_pre_compress()` text still requires Hermes runtime support to influence
  the compression summary directly.

### RH-25 Real Compaction Follow-Up

After RH-25 deployment, the gateway hit automatic compression twice:

```text
session=20260521_230024_83b866
23:49:15 context compression started: messages=97 tokens=~102306 focus=None
23:49:38 context compression done: messages=97->7 tokens=~22419
23:51:35 context compression started: messages=97 tokens=~101129 focus=None
23:52:06 context compression done: messages=97->7 tokens=~19981
```

The `focus=None` value confirms the Hermes upstream compression-focus gap
remained. Memory-OS RH-25 still helped enough that the assistant continued the
foreground video task immediately after compaction.

However, a later owner cancellation/rejection turn exposed a second issue: after
acknowledging the failed video direction, the assistant pivoted into unrelated
historical system-memory discussion.

Follow-up fix:

- cancellation and vague continuation turns now use foreground-only prefetch
- those turns suppress Working Memory and Conversation Carryover sections
- cancellation anchors tell the assistant to acknowledge cancellation and stop
  the foreground task instead of pivoting to unrelated system-memory/provider
  topics
- tests increased to `302 passed`

### RH-25b Deployment Verification

The first real compaction follow-up above happened before the cancellation /
foreground-only guard was deployed to the live provider path. The active
provider at that point did not yet contain:

```text
_foreground_task_only_prefetch
_is_cancel_current_task_query
foreground_task_only
```

The updated RH-25b provider was then installed on 10.20.3.200 via the normal
installer and the gateway was restarted:

```text
provider target: /root/.hermes/plugins/memory_os
gateway ActiveState=active
gateway SubState=running
gateway MainPID=451115
heartbeat timer ActiveState=active
heartbeat timer UnitFileState=enabled
```

Live provider code confirmation:

```text
/root/.hermes/plugins/memory_os/__init__.py:
  has_foreground_only_flag=True
  has_cancel_guard=True
  has_foreground_only_param=True
  has_cancel_rule=True

/root/.hermes/plugins/memory_os/prefetch.py:
  has_foreground_only_param=True
```

Synthetic cancellation probe:

```text
input anchor: "剪一个 ComfyUI 教程视频，修掉内容消失的问题"
input cancellation: "太垃圾了，算了，你还是别做视频了"

has_foreground=True
has_cancel=True
foreground_only=True
no_hindsight_marker=True
prompt_has_cancel=True
context_chars=390
prompt_chars=444
```

Doctor after deployment:

```text
doctor_status=ok
exit_code=0
findings=[("hindsight_adapter_disabled", "warning")]
```

Interpretation: RH-25b is now active on the test host. Cancellation and vague
continuation turns should no longer compete with background Working Memory or
Conversation Carryover during prefetch. Hermes automatic compression still
reports `focus=None`; that upstream behavior is unchanged.

### RH-26 Context Router Dry-Run Validation

RH-26 was implemented and deployed in dry-run/report-only mode. It does not
change live prefetch behavior and does not write memory. The provider was
installed through the normal installer and the gateway restarted cleanly:

```text
gateway ActiveState=active
gateway SubState=running
gateway MainPID=451521
```

Health checks after deployment:

```text
doctor_status=ok
exit_code=0
findings=[("hindsight_adapter_disabled", "warning")]

status_tool_contract_validation=ok
status_tool_contract_findings=[]
```

Seven host validation prompts were run through:

```text
hermes memory_os context-router dry-run --query ...
```

Summary:

```text
cancel_failed_video:
  route=foreground_control
  reason_codes=[cancellation]
  selected=[Current Foreground Task]
  dropped=[Conversation Carryover, Working Memory, Indexed Recall, Recent Event Summaries]

continue_current_task:
  route=foreground_control
  reason_codes=[vague_continue_with_anchor]
  selected=[Current Foreground Task]
  dropped=[Conversation Carryover, Working Memory, Recent Event Summaries]

casual_memory_system_change:
  route=casual_continuity
  reason_codes=[ordinary_opinion]
  selected=[]
  dropped=[Conversation Carryover, Working Memory, Indexed Recall, Recent Event Summaries]

diagnostic_current_architecture:
  route=diagnostic_current_status
  reason_codes=[explicit_diagnostic]
  selected=[Diagnostic Grounding]
  dropped=[]

candidate_vs_crystallized:
  route=candidate_review
  reason_codes=[candidate_review_terms]
  selected=[Crystallized Review Candidates, Indexed Recall]
  dropped=[Conversation Carryover, Working Memory, Recent Event Summaries]

active_comfyui_install:
  route=active_task
  reason_codes=[active_task_terms]
  selected=[Current Foreground Task, Indexed Recall]
  dropped=[Conversation Carryover, Working Memory, Recent Event Summaries]

deferred_cancellation:
  route=foreground_control
  reason_codes=[deferred_cancellation_open]
  open_issue=deferred_cancellation_requires_anchor_lifecycle
  selected=[Current Foreground Task]
  dropped=[Conversation Carryover, Working Memory, Recent Event Summaries]
```

Interpretation:

- foreground cancellation and vague continuation are routed to the hard
  foreground-control path and are not mixed with background Working Memory or
  Conversation Carryover
- explicit current-status questions keep the diagnostic section
- candidate/crystallized wording questions keep review-candidate context and do
  not treat candidates as approved crystallized memory
- active task prompts keep the foreground task anchor and only keep indexed
  recall when it passes the dry-run relevance gate
- deferred cancellation is intentionally reported as an open anchor-lifecycle
  issue instead of being silently treated as solved

The casual continuity prompt selected no sections on this host because the
available current sections were judged diagnostic/mechanism-heavy or below the
dry-run relevance threshold. This is a useful signal for review, not an apply
failure: RH-26 has not changed live prefetch, and "empty or low-relevance
sections should not consume budget just because a route allows them" remains
the intended dry-run behavior.

The CLI dry-run output includes `reason_codes` and scores for dropped sections.
The validation summary above lists section names only, so the relevant detail is
recorded here without raw private bodies:

```text
casual_memory_system_change dropped reasons:
  Conversation Carryover:
    score=0.00
    reason_codes=[below_threshold]
  Working Memory:
    score=0.00
    reason_codes=[keyword_match, high_relevance, mechanism_leak_detected, below_threshold]
  Indexed Recall:
    score=0.00
    reason_codes=[keyword_match, high_relevance, diagnostic_style_in_non_diagnostic_route, below_threshold]
  Recent Event Summaries:
    score=0.15
    reason_codes=[keyword_match, below_threshold]

active_comfyui_install dropped reasons:
  Conversation Carryover:
    score=0.00
    reason_codes=[route_excludes_broad_carryover]
  Working Memory:
    score=0.15
    reason_codes=[entity_match, keyword_match, foreground_anchor, high_relevance, mechanism_leak_detected, below_threshold]
  Recent Event Summaries:
    score=0.00
    reason_codes=[below_threshold]
```

This confirms the empty casual selection is caused by the current host's
available context shape, not by missing dry-run metadata.

### RH-26.5 Apply Gate Baseline

Before any apply-mode review, the full RH-22 seven-prompt baseline was run on
10.20.3.200 against a public synthetic transcript:

```text
schema_version=memory-os.conversation_regression.v0
status=ok
prompt_count=7
failure_count=0
warning_count=0
```

The first baseline attempt used the exact phrase `approved crystallized memory`
inside a negated Chinese sentence and correctly exposed that this phrase is part
of the evaluator's candidate-boundary guard. The transcript was rewritten to
avoid that guarded phrase and the seven-prompt baseline passed. This is a
fixture wording issue, not a router behavior issue.

Recommended apply strategy for RH-26.5:

```json
{
  "context_router": {
    "enabled": true,
    "mode": "apply",
    "apply_routes": ["foreground_control"],
    "dry_run_routes": [
      "active_task",
      "casual_continuity",
      "diagnostic_current_status",
      "candidate_review",
      "memory_architecture_discussion"
    ],
    "llm_judge_mode": "disabled"
  }
}
```

Rationale:

- `foreground_control` is the safest first apply route because it matches the
  already-deployed RH-25b foreground-only behavior
- all other routes should remain dry-run until their reports are reviewed after
  at least one live Telegram observation window
- rollback must be config-only: set `mode` back to `dry_run` or clear
  `apply_routes`

Boundary result:

```text
would_change_live_prefetch=true for most dry-run reports
live_prefetch_changed=false
actual_send=false
actual_execute=false
actual_identity_write=false
actual_crystallized_approval=false
```

RH-26 should stop here for review. RH-26.5 apply mode remains disabled and
requires a separate review gate.

### RH-26.5 Test-Host Full Apply

After review, the owner chose to apply all RH-26 routes on the 10.20.3.200 test
host to expose real behavior faster. This is a test-host override, not the
production-safe default.

Applied config:

```json
{
  "context_router": {
    "enabled": true,
    "mode": "apply",
    "apply_routes": ["all"],
    "dry_run_routes": [],
    "llm_judge_mode": "disabled"
  }
}
```

Deployment:

```text
provider install path: /root/.hermes/plugins/memory_os
runtime install path: /root/.hermes/memory-os/runtime/python
gateway ActiveState=active
gateway SubState=running
gateway MainPID=451894
```

Implementation note:

- default config remains disabled/dry-run
- apply mode is config-gated
- rollback is config-only: set `mode=dry_run` or clear `apply_routes`
- `foreground_control` uses the same Current Foreground Task section behavior as
  RH-25b rather than a second competing foreground-only implementation

Apply-only findings fixed before observation:

- Real provider calls refresh `current_task_anchor` for each query. With
  full-route apply, the first test pass incorrectly allowed a casual prompt's
  current query anchor to become `Current Foreground Task`. The router now
  excludes `Current Foreground Task` and `Indexed Recall` from
  `casual_continuity`.
- Diagnostic apply initially double-wrapped `## Memory-OS Context` because the
  diagnostic candidate text already contained a complete context block. Apply
  formatting now returns a single already-formatted diagnostic block when only
  that block is selected.

Post-apply direct prefetch probe:

```text
cancel_failed_video:
  chars=134
  headings=[Current Foreground Task]

continue_current_task:
  chars=108
  headings=[Current Foreground Task]

casual_memory_system_change:
  chars=0
  headings=[]

diagnostic_current_architecture:
  chars=297
  headings=[Diagnostic Grounding, Current Memory-OS Runtime Facts]

candidate_vs_crystallized:
  chars=1306
  headings=[Crystallized Review Candidates, Indexed Recall]

active_comfyui_install:
  chars=1516
  headings=[Current Foreground Task, Indexed Recall]

deferred_cancellation:
  chars=110
  headings=[Current Foreground Task]
```

Post-apply health checks:

```text
doctor_status=ok
exit_code=0
findings=[("hindsight_adapter_disabled", "warning")]

RH-22 full seven-prompt baseline:
  status=ok
  prompt_count=7
  failure_count=0
  warning_count=0

memory_os status:
  index_health=healthy
  prefetch_mode=indexed
  hindsight_adapter_enabled=false
  crystallized_records=0
```

Observation plan:

- existing six-hour read-only monitor now records `context_router` config and
  RH-26 apply probe headings only
- no section bodies, private messages, raw event summaries, or prompt-expanded
  context are printed by the monitor
- regressions should be rolled back by config before any code change

### Script-Backed Monitor v0.3 Snapshot

The `memory-os-3-200-monitor` automation was moved to the deterministic
read-only script:

```text
python scripts/memory_os_3_200_monitor.py --host hermes-media \
  --previous-json C:\Users\btnal\.codex\automations\memory-os-3-200-monitor\last-snapshot.json \
  --snapshot-out C:\Users\btnal\.codex\automations\memory-os-3-200-monitor\last-snapshot.json \
  --output summary
```

Saved automation snapshot:

```text
snapshot_time_utc=2026-05-22T11:49:52Z
classification=WARN
PASS=[gateway_active, heartbeat_timer_active, index_healthy, doctor_ok,
      status_tool_contract_ok, context_router_apply]
WARN=[rh26_casual_empty, deep_reflection_source_skew]
FAIL=[]
```

Counts and deltas:

```text
audit_entries=1211
events=92
working_items=85
crystallized_candidates=85
crystallized_records=0
queue_backlog=0

delta_from_previous_snapshot:
  audit_entries +110
  events +2
  working_items +2
  crystallized_candidates +2
  crystallized_records +0
  audit_entries_per_new_event=55.0
```

Context router state:

```json
{
  "enabled": true,
  "mode": "apply",
  "apply_routes": ["all"],
  "dry_run_routes": [],
  "llm_judge_mode": "disabled"
}
```

RH-26 live apply headings:

```text
cancel_failed_video -> Current Foreground Task
continue_current_task -> Current Foreground Task
casual_memory_system_change -> <empty>
diagnostic_current_architecture -> Diagnostic Grounding / Current Memory-OS Runtime Facts
candidate_vs_crystallized -> Crystallized Review Candidates / Indexed Recall
active_comfyui_install -> Current Foreground Task / Indexed Recall
deferred_cancellation -> Current Foreground Task
```

DeepReflection status:

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

Other bounded signals:

```text
agent_os_shell_session_started=5
agent_os_shell_session_reset=4
agent_os_shell_session_finalized=4
gateway_compaction_recent_count=0
gateway_compaction_focus_none_count=0
disk_du=7.0M /root/.hermes/memory-os
```

Read-only recheck shortly after the saved snapshot:

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

Interpretation:

- The monitor is now collecting the signals needed to support deferred
  decisions: audit/event ratio, hook marker totals, compaction focus-gap
  counts, RH-26 heading shape, and DeepReflection source-class distribution.
- The only WARN items are expected: RH-26 casual continuity remains empty on
  this mechanism-heavy test host, and DeepReflection remains working-source
  skewed.
- The `audit_entries_per_new_event=55.0` ratio deserves continued observation,
  but it did not coincide with queue backlog, crystallized writes, or boundary
  violations.
- The manual recheck's `audit_entries +4` with no event/working/candidate
  growth indicates the monitor/tool path can add small audit noise. Future
  audit growth analysis should distinguish monitor/tool audit noise from real
  event-layer growth.

### Agent OS Shell No-Env Regression Fix

Manual operator testing on 10.20.3.200 exposed a real shell usability bug:

```text
root@debian:~# hermes memory-os-agent-os status
{
  "schema_version": "memory-os.agent_os_shell.v0",
  "status": "error",
  "code": "memory_os_provider_missing",
  "message": "Memory-OS provider/runtime is not importable by the shell plugin.",
  "error": "No module named 'memory_os'"
}
```

Root cause:

- the provider itself was installed and active
- `HERMES_HOME=/root/.hermes hermes memory-os-agent-os status` worked
- the shell plugin only added Memory-OS import paths when `HERMES_HOME` was set
- a natural operator command without `HERMES_HOME` could not import the provider
  or runtime

Fix:

- the shell plugin now resolves Hermes home in this order:
  1. explicit `HERMES_HOME`
  2. installed shell path under `$HERMES_HOME/plugins/memory-os-agent-os`
  3. default `~/.hermes` if it exists
- session marker hooks use the same resolver
- the monitor now treats no-env shell alias failure as a FAIL condition
- `scripts/install_memory_os_test_host.sh` provides a one-command test-host
  installer wrapper around the interactive shell installer
- `scripts/install_memory_os.sh` is now the primary operator entrypoint. It
  discovers existing Hermes homes, prints the current provider/shell/runtime
  state, asks which pieces to install or enable, and then delegates writes to
  the Python installer.

Deployment:

```text
target: 10.20.3.200
method: copy current repo bundle to /tmp and run scripts/install_memory_os_test_host.sh
gateway_restart: no
cleanup_apply: no
shadow_journal_apply: no
```

Post-fix verification without explicit `HERMES_HOME`:

```text
hermes memory-os-agent-os status:
  schema_version=memory-os.status.v0
  index_health=healthy
  counts.events=93
  counts.crystallized_records=0

hermes memory-os-agent-os doctor:
  schema_version=memory-os.doctor.v0
  status=ok
  exit_code=0
  findings=[hindsight_adapter_disabled warning]
```

Monitor recheck after the fix:

```text
classification=WARN
PASS includes shell_alias_no_env_ok
FAIL=[]
gateway=active
heartbeat=active/enabled
index_health=healthy
doctor=ok
context_router=apply apply_routes=["all"]
```

Interpretation: this was not a Memory-OS canonical data problem. It was a shell
plugin import-path usability gap that previous validation missed because the
checks always supplied `HERMES_HOME`. The regression is now covered by tests
and by the six-hour monitor.

Interactive installer validation:

```text
command:
  HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host

preflight:
  hermes_home=/root/.hermes
  config_yaml=yes
  provider_dir=present
  shell_dir=present
  runtime_dir=present
  current provider=memory_os
  memory-os-agent-os enabled
  memory_os not enabled as a general plugin
  heartbeat timer active/enabled
  gateway restart not performed

selected non-interactive choices:
  install/update shell plugin=yes
  set memory.provider=memory_os=yes
  enable memory-os-agent-os=yes
  install portable L2-L4 modules=yes
  install heartbeat runtime artifacts=yes
  enable heartbeat timer=yes
  deep_reflection_preset=test-host
```

Post-installer monitor:

```text
classification=WARN
PASS includes shell_alias_no_env_ok
FAIL=[]
gateway=active
heartbeat=active/enabled
index_health=healthy
doctor=ok
context_router=apply apply_routes=["all"]
crystallized_records=0
```

## P1-J SessionMirror Monitor Coverage Validation

Date:

```text
2026-05-25T05:04:44Z
```

Scope:

- P1-J SessionMirror Global Entrance Coverage Review
- Monitor-only SessionMirror coverage summary

Command:

```powershell
python scripts\memory_os_3_200_monitor.py `
  --host hermes-media `
  --previous-json C:\Users\btnal\.codex\automations\memory-os-3-200-monitor\last-snapshot.json `
  --output summary
```

Result:

```text
monitor_status=WARN
PASS includes:
  session_mirror_dry_run_ok
  hook_coverage_session_activity_with_markers
  expression_artifact_summary_ok
  memory_sources_stats_ok
  low_clue_recall_probe_ok
WARN=[session_mirror_pending_sessions, rh31_eval_has_failures]
FAIL=[]
```

SessionMirror evidence:

```text
SessionMirror.status=ok
session_count=54
covered_session_count=29
pending_session_count=25
dry_run_status=ok
dry_run_new_event_count=25
dry_run_written_event_ids_count=0
dry_run_findings_count=0
```

Interpretation:

- SessionMirror still sees pending sessions, so global entrance coverage is not
  complete.
- The dry-run remains safe: it reports bounded would-create counts and writes
  no event ids.
- Pending sessions are now monitor-visible as an observation WARN, not a FAIL.
- This does not justify recurring or one-time apply by itself. A one-time apply
  still needs separate review because it would change the Memory-OS event
  stream.

## P1 Gap Closure Remote Deployment Gate

Date: 2026-05-23

Scope:

- target host: `10.20.3.200` via `ssh hermes-media`
- target `HERMES_HOME`: `/root/.hermes`
- deployment source: current local workspace snapshot
- install command: `HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host`
- gateway restart: not requested and not performed
- heartbeat/manual cleanup/shadow journal apply: not run
- production/Sannai host `10.20.2.88`: not touched

This gate validates the P1 implementation closure described in
`22-p1-gap-closure-plan.md`:

- module CLI surfaces
- DeepReflection owner preview/history CLI
- no-send host validation command
- controlled dry-run module runner
- installer fail-closed behavior
- Agent OS shell compatibility with the installed provider/runtime

### Local Verification Before Remote Gate

Local verification was rerun after the final runtime import fix:

```text
python -m pytest tests\plugins\memory\test_memory_os_cli_modules.py tests\scripts\test_memory_os_plugin_install.py -q
34 passed in 3.81s

python -m pytest -q
346 passed in 25.14s

git diff --check
passed
```

### Remote Finding During Gate

The first remote validation attempt after deployment exposed a real installed
Hermes import-path gap:

```text
hermes memory_os modules deep_reflection preview-current
ModuleNotFoundError: No module named 'plugins.modules'
```

After adding the runtime python path, a second error showed the deeper package
path conflict:

```text
ModuleNotFoundError: No module named 'plugins.memory.memory_os'
```

Root cause:

- Hermes had already loaded the user-plugin `plugins` package from
  `$HERMES_HOME/plugins`.
- Inserting `$HERMES_HOME/memory-os/runtime/python` into `sys.path` was not
  sufficient once `plugins` and `plugins.memory` were already loaded.
- DeepReflection imports both `plugins.modules...` and
  `plugins.memory.memory_os...`, so both loaded package paths had to be
  extended.

Fix:

- `_ensure_system_module_runtime_path()` now extends:
  - `plugins.__path__` with
    `/root/.hermes/memory-os/runtime/python/plugins`
  - `plugins.memory.__path__` with
    `/root/.hermes/memory-os/runtime/python/plugins/memory`
- regression coverage was added for already-loaded `plugins` and
  `plugins.memory` package path extension.

Why the fix did not require a gateway restart:

- the failing surface was the operator CLI path, not the running gateway
  request path
- each `hermes memory_os ...` CLI command starts a fresh Python process and
  loads the newly installed plugin files
- the gateway was left running while the fixed CLI path was validated through
  fresh invocations

Known packaging risk:

- the installed Hermes runtime can load `plugins` namespace packages from both
  `$HERMES_HOME/plugins` and
  `$HERMES_HOME/memory-os/runtime/python`
- extending already-loaded namespace package paths fixes the observed import
  contract, but future provider/runtime updates must keep the provider package
  and portable L2-L4 runtime API-compatible
- this remains an installer-level validation point for future releases

Interpretation:

- This was not a canonical Memory-OS data problem.
- This was an installed-runtime compatibility gap that only appears in a real
  Hermes process after user plugins have already populated the `plugins`
  package namespace.
- Local unit tests alone did not expose it; the remote deployment gate did.

### Remote Validation After Fix

Final remote validation after redeploying the fixed workspace snapshot:

```text
hermes memory_os status:
  exit_code=0
  index_health.state=healthy
  prefetch_mode=indexed
  hindsight_adapter_enabled=false
  counts:
    audit_entries=1573
    events=93
    working_items=86
    crystallized_candidates=86
    crystallized_records=0

hermes memory_os doctor:
  exit_code=0
  status=ok
  findings=[hindsight_adapter_disabled]

hermes memory_os modules status:
  exit_code=0
  module_count=16
  commandized=[
    cron_mirror,
    session_mirror,
    state_source_mirror,
    shadow_journal,
    deep_reflection,
    governance_feedback
  ]
  uncommandized_count=10

hermes memory_os modules doctor:
  exit_code=0
  status=warning
  warning_count=4
  warning_findings:
    mailbox/mailbox_root_missing:
      mailbox root is not configured on the test host
    wandering_mind/household_digest_missing:
      household digest artifact is not present, so Wandering Mind may return
      [SILENT]
    proposal_queue/pending_candidates_present:
      2 proposal candidates are pending review
    self_evolution/missing_required_runtime_dependency:
      ops_gate, proposal_queue, and evidence_scoring are not exposed through
      the generic run-once path for this validation gate

hermes memory_os modules run-once --module cron_mirror:
  exit_code=0
  dry_run=true
  new_event_count=0

hermes memory_os modules deep_reflection preview-current:
  exit_code=0
  schema_version=hermes.deep_reflection_preview.v0
  status=ok
  selected_injection_count=2
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false

hermes memory_os modules deep_reflection history --days 7:
  exit_code=0
  schema_version=hermes.deep_reflection_history.v0
  record_count=7
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false

hermes memory_os validate --no-send --write-report:
  exit_code=0
  status=warning
  report_written=true
  warning_source:
    modules_doctor emitted warning-class findings listed above; hard-boundary
    checks stayed false and no doctor error caused a non-zero exit
  hard boundaries:
    actual_send=false
    actual_execute=false
    actual_identity_write=false
    actual_relationship_write=false
    actual_crystallized_approval=false
    hindsight_exported=false

hermes memory-os-agent-os status:
  exit_code=0
  schema_version=memory-os.status.v0

hermes memory-os-agent-os doctor:
  exit_code=0
  schema_version=memory-os.doctor.v0
  status=ok

hermes memory_os conversation-regression status-tool-contract:
  exit_code=0
  validation.status=ok
  finding_count=0
```

Service and plugin state after the gate:

```text
hermes-gateway.service:
  ActiveState=active
  SubState=running
  MainPID=451894

hermes-memory-os-heartbeat.timer:
  LoadState=loaded
  ActiveState=active
  SubState=waiting
  UnitFileState=enabled

hermes plugins list:
  memory-os-agent-os: enabled
  memory_os: not enabled as a general plugin
```

### Boundary Review

Hard-boundary evidence from the final remote gate:

```json
{
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_relationship_write": false,
  "actual_crystallized_approval": false,
  "hindsight_exported": false
}
```

Additional boundary observations:

- `crystallized_records` remained `0`.
- `memory_os` remained the active memory provider but was not enabled as a
  general Hermes plugin.
- `memory-os-agent-os` remained enabled as the official shell plugin.
- DeepReflection preview/history commands returned bounded JSON and did not
  print source raw bodies.
- The validation command wrote a bounded report under
  `/root/.hermes/memory-os/system-modules/validation/`.
- The gateway stayed active and was not restarted by this gate.

### Gate Judgment

P1-A through P1-D are now validated on the real test host:

- module CLI exists and reports commandized/uncommandized modules
- safe module dry-run works for a commandized module
- DeepReflection owner preview/history CLI works in the installed Hermes
  runtime, not just local tests
- `memory_os validate --no-send --write-report` produces a bounded report
- Agent OS shell aliases can call the installed provider/runtime
- installer-based deployment preserves provider/shell/timer state
- expected warnings remain warning-class only
- no hard-boundary violation was observed

## RH-27 Test-Host Cognitive Loop Validation

Date: 2026-05-23

### Why This Gate Was Needed

Earlier monitoring proved the Memory-OS plumbing was healthy:

- provider active
- heartbeat timer active
- context router applied
- shell plugin enabled
- read-only monitor running

That did not prove the left/right cognition modules were actually running. The
test host was observing the water pipes, not the water flow. RH-27 adds a
test-host-only no-send cognitive loop so the developed modules run together and
produce observable interaction data.

### Deployment Finding

The first remote deployment attempt exposed an installed-Hermes command-surface
gap:

```text
hermes memory_os ...
```

was not available on the installed host because `memory_os` is active as a
memory provider and is not enabled as a general plugin. The fix was to use the
standalone Memory-OS module entrypoint from systemd wrappers and monitor probes:

```text
PYTHONPATH=/root/.hermes/memory-os/runtime/python:/root/.hermes/plugins:$PYTHONPATH
python3 -m plugins.memory.memory_os ...
```

This also keeps `memory_os` out of `plugins.enabled` while preserving the
provider-first architecture.

### Remote Install State

After the wrapper fix, the test-host installer deployed:

- provider runtime
- `memory-os-agent-os` shell plugin
- heartbeat service/timer
- cognitive-loop service/timer

Systemd state after install:

```text
hermes-gateway.service:
  ActiveState=active
  MainPID=451894

hermes-memory-os-heartbeat.timer:
  ActiveState=active
  UnitFileState=enabled

hermes-memory-os-cognitive-loop.timer:
  LoadState=loaded
  ActiveState=active
  SubState=waiting
  UnitFileState=enabled
```

### Manual Cognitive Loop Run

Command:

```bash
/root/.hermes/memory-os/bin/memory_os_cognitive_loop.sh
```

Result:

```json
{
  "cycle_id": "cloop_20260523T050110276460Z_0f0c02cb09",
  "status": "ok",
  "duration_ms": 527,
  "step_count": 11,
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_relationship_write": false,
  "actual_crystallized_approval": false,
  "hindsight_exported": false
}
```

All 11 steps returned `ok`:

```text
heartbeat_pre
household_digest
digest_consolidation
wandering_mind
ops_gate
evidence_scoring
self_evolution
governance_feedback
deep_reflection
heartbeat_post
doctor_boundary_report
```

Step evidence:

```text
household_digest:
  event_count=50
  artifact_written=true

digest_consolidation:
  daily_artifact_date=2026-05-23
  weekly_artifact_week=2026-W21

wandering_mind:
  would_send=true
  actual_send=false

ops_gate:
  mode=report_only
  actual_execute=false

evidence_scoring:
  score_count=269

self_evolution:
  proposal_created=true
  proposal_id=prop_20260523T050110584207Z_3073ae8ff0
  direct_self_modify=false
  actual_execute=false

governance_feedback:
  written_event_count=6
  event_kinds=[
    governance_evidence_scored,
    governance_ops_gate_decision,
    governance_proposal_created,
    governance_proposal_transitioned,
    governance_self_evolution_reported
  ]

deep_reflection:
  selected_injection_by_source_class={"governance": 2}
  dropped_injection_by_source_class={"governance": 2}

heartbeat_post:
  processed_event_count=6
  policy_skipped_event_count=6
  source_class_counts={"governance": 6}
```

The heartbeat post-step intentionally skipped governance events from working
promotion, preserving the RH-12 source-class boundary.

### Post-Run Monitor Snapshot

The deterministic read-only monitor reported `WARN` with no `FAIL`.

```text
gateway=active pid=451894
heartbeat=active/enabled
cognitive_loop=ok timer=active/enabled
audit_entries=1633
events=99
working_items=86
crystallized_candidates=86
crystallized_records=0
index_health=healthy
prefetch_mode=indexed
doctor=ok
status_tool_contract=ok
context_router=apply, llm_judge=disabled
disk_usage=/root/.hermes/memory-os 8.3M
```

DeepReflection source-class distribution after RH-27:

```json
{
  "latest": {
    "selected_by_source_class": {"governance": 2},
    "dropped_by_source_class": {"governance": 2}
  },
  "rolling": {
    "selected_by_source_class": {"governance": 2, "working": 14},
    "dropped_by_source_class": {"governance": 2, "working": 7},
    "window_report_count": 8
  }
}
```

This is the first validation signal that the source-class skew was at least
partly caused by not running the cognition loop. Once governance feedback ran,
DeepReflection selected governance-sourced injection cards.

Follow-up read-only monitor after documentation updates:

```text
time=2026-05-23T05:04:55Z
gateway=active pid=451894
heartbeat=active/enabled
cognitive_loop=ok timer=active/enabled
audit_entries=1635
events=99
working_items=86
crystallized_candidates=86
crystallized_records=0
index_health=healthy
doctor=ok
status_tool_contract=ok
context_router=apply, apply_routes=["all"], llm_judge=disabled
DeepReflection latest selected_by_source_class={"governance": 2}
DeepReflection rolling selected_by_source_class={"governance": 2, "working": 14}
PASS=[
  gateway_active,
  heartbeat_timer_active,
  cognitive_loop_timer_active,
  cognitive_loop_last_cycle_present,
  index_healthy,
  doctor_ok,
  status_tool_contract_ok,
  shell_alias_no_env_ok,
  context_router_apply
]
WARN=[rh26_casual_empty]
FAIL=[]
```

Follow-up validation after hard-boundary aggregation was added to the cognitive
loop runner:

```text
local_tests=356 passed
cycle_id=cloop_20260523T050811038295Z_4d300f67cf
cycle_status=ok
cycle_duration_ms=487
events=104
audit_entries=1658
working_items=86
crystallized_candidates=86
crystallized_records=0
heartbeat_post.processed_event_count=5
heartbeat_post.policy_skipped_event_count=5
DeepReflection latest selected_by_source_class={"governance": 2}
DeepReflection rolling selected_by_source_class={"governance": 4, "working": 14}
PASS=[
  gateway_active,
  heartbeat_timer_active,
  cognitive_loop_timer_active,
  cognitive_loop_last_cycle_present,
  index_healthy,
  doctor_ok,
  status_tool_contract_ok,
  shell_alias_no_env_ok,
  context_router_apply
]
WARN=[rh26_casual_empty]
FAIL=[]
```

The second manual cycle verifies that the new hard-boundary aggregation did not
break the live no-send cognition loop. It also confirms that governance remains
visible to DeepReflection while RH-12 still prevents governance events from
becoming working-memory items.

### Boundary Review

Hard-boundary state after the RH-27 gate:

```json
{
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_relationship_write": false,
  "actual_crystallized_approval": false,
  "hindsight_exported": false,
  "crystallized_records": 0
}
```

Expected warnings:

- `hindsight_adapter_disabled`
- RH-26 casual empty context

Resolved or changed warnings:

- DeepReflection no longer shows a strictly working-only source-class
  distribution after the cognitive loop run; governance appeared in both latest
  selected and dropped cards.

### Gate Judgment

RH-27 is validated on the test host:

- the left/right cognition loop now runs, not just the provider plumbing
- one manual cycle completed with all steps `ok`
- cognitive-loop timer is installed and enabled for ongoing test-host cycles
- the read-only monitor now observes cognitive-loop status and boundaries
- all hard boundaries remained false
- no raw private bodies were printed
- no production host or Sannai host was touched

## Monitor v0.4 And RH-28 Validation

Date: 2026-05-23

### Trigger

Telegram tests showed two follow-up needs:

- monitor v0.3 treated `casual_memory_system_change` as a failure whenever
  casual context was non-empty
- low-clue recall questions such as
  `你还记得我之前跟你说过的一个设计吗？` caused the agent to guess one likely
  answer too early

### Implementation

Monitor v0.4 changed the casual heading rule:

- empty casual context remains a warning
- safe `Recent Event Summaries` / `Conversation Carryover` in casual context is
  allowed
- diagnostic/runtime/candidate/foreground headings in casual context remain
  failures
- other casual headings are warnings for manual review

RH-28 added a deterministic `ambiguous_recall` route and a bounded
`Recall Clarification Guard` prefetch section.

### Local Verification

```text
python -m pytest -q
359 passed

git diff --check
ok
```

### Remote Validation

After redeploying the test-host package, the read-only monitor returned `PASS`:

```text
time=2026-05-23T06:10:38Z
gateway=active pid=451894
heartbeat=active/enabled
cognitive_loop=ok timer=active/enabled
audit_entries=1859
events=138
working_items=120
crystallized_candidates=120
crystallized_records=0
index_health=healthy
doctor=ok
context_router=apply, apply_routes=["all"], llm_judge=disabled
RH-26 casual_memory_system_change=1535 chars, headings=[Recent Event Summaries]
DeepReflection latest selected_by_source_class={"governance": 2}
DeepReflection rolling selected_by_source_class={"governance": 4, "working": 14}
PASS=[
  gateway_active,
  heartbeat_timer_active,
  cognitive_loop_timer_active,
  cognitive_loop_last_cycle_present,
  index_healthy,
  doctor_ok,
  status_tool_contract_ok,
  shell_alias_no_env_ok,
  context_router_apply
]
WARN=[]
FAIL=[]
```

RH-28 remote prefetch probe:

```text
query=你还记得我之前跟你说过的一个设计吗？
route=ambiguous_recall
reason_codes=[low_clue_recall]
has_guard=true
headings=[Recall Clarification Guard]
```

### Gate Judgment

- monitor v0.4 no longer misclassifies safe casual carryover as a failure
- RH-28 deterministic guard is present in live prefetch
- all hard-boundary booleans remain false
- no raw private bodies were printed
- no production/Sannai host was touched

### Telegram Smoke Follow-Up

After restarting `hermes-gateway.service` to load the updated provider code, the
owner opened a fresh Telegram session:

```text
/new
你还记得我之前跟你说过的一个设计吗？
```

The agent no longer guessed a single design. It answered that the prompt was not
enough to locate a unique item, offered three candidate directions, and asked
for a keyword:

```text
1. 互联网数据采集系统的分层设计
2. ComfyUI / AI 生成工作流的分层设计
3. Memory-OS / 记忆系统的分层架构
```

This validates the RH-28 low-clue recall behavior in the real Telegram frontend:

- low-clue recall is treated as ambiguous
- candidate directions are offered instead of a single overconfident answer
- the agent asks for an anchor to continue

### Post-Smoke Monitor Recheck

After the Telegram smoke test, a read-only monitor recheck was run without
overwriting the automation's `last-snapshot.json`.

Result:

```text
time=2026-05-23T06:20:41Z
status=PASS
gateway=active pid=464064
heartbeat=active/enabled
cognitive_loop=ok timer=active/enabled
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
index_health=healthy
doctor=ok
context_router=apply, apply_routes=["all"], llm_judge=disabled
RH-26 casual_memory_system_change=1538 chars, headings=[Recent Event Summaries]
compaction.focus_none_count=0
DeepReflection latest selected_by_source_class={"governance": 2}
DeepReflection rolling selected_by_source_class={"governance": 4, "working": 14}
DeepReflection actual_send=false
DeepReflection actual_execute=false
DeepReflection actual_identity_write=false
DeepReflection actual_crystallized_approval=false
disk_usage=/root/.hermes/memory-os 9.3M
PASS=[
  gateway_active,
  heartbeat_timer_active,
  cognitive_loop_timer_active,
  cognitive_loop_last_cycle_present,
  index_healthy,
  doctor_ok,
  status_tool_contract_ok,
  shell_alias_no_env_ok,
  context_router_apply
]
WARN=[]
FAIL=[]
```

Comparison against the pre-smoke automation snapshot:

- `index_health` recovered from `stale` to `healthy`.
- `rh26_casual_empty` disappeared because the casual probe now selects safe
  `Recent Event Summaries` instead of empty context.
- DeepReflection no longer shows a working-only source skew; governance remains
  present in both latest and rolling source-class distribution.
- `compaction.focus_none_count` remained `0`, so no new compression-focus
  anomaly was observed.
- all hard-boundary booleans remained false and `crystallized_records` remained
  `0`.

The remaining trend to watch is growth slope: `audit_entries` and
working/candidate counts are rising now that the cognitive loop is active. This
is expected for a test-host observation phase, but monitor v0.4 should continue
tracking `audit_per_new_event` and disk growth.

## 2026-05-23 RH-29 Memory Sources Attribution Deployment

### Scope

RH-29 was deployed to the `10.20.3.200` test host only.

Installed through the project installer from a temporary transfer bundle:

```text
scripts/install_memory_os_test_host.sh --hermes-home /root/.hermes
```

Installer result:

```text
memory_sources_preset=test-host
memory_sources_config_written=true
memory_sources_config_path=/root/.hermes/memory-os/config.json
memory_sources_config.enabled=true
memory_sources_config.mode=metadata_only
memory_sources_config.retention_days=30
record_live_prefetch=true
record_dry_run=false
```

The installer also refreshed the provider plugin, Agent OS shell plugin,
portable L2-L4 runtime, heartbeat artifacts, cognitive-loop artifacts, and
DeepReflection test-host config.

Because provider prefetch code changed, the user gateway was restarted in the
user service scope:

```text
systemctl --user restart hermes-gateway.service
systemctl --user is-active hermes-gateway.service -> active
MainPID=464934
```

### Synthetic Live-Prefetch Probe

A bounded synthetic probe exercised the installed provider path without printing
private bodies:

```text
MemoryOSProvider.initialize(session_id="rh29_smoke", hermes_home="/root/.hermes", profile="default")
MemoryOSProvider.prefetch(low-clue recall query)
context_chars=1816
has_recall_guard=true
```

`memory-sources last` reported:

```text
status=ok
route=ambiguous_recall
query_class=ambiguous_recall
selected_headings=[Recall Clarification Guard, Recent Event Summaries]
selected_source_classes=[recall_guard, event]
selected_chars_total=1734
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_relationship_write=false
boundary.actual_crystallized_approval=false
boundary.hindsight_exported=false
```

`memory-sources stats --hours 24` reported:

```text
schema_version=memory-os.memory_sources_stats.v0
ledger_exists=true
record_count=1
route_distribution={"ambiguous_recall": 1}
selected_source_class_distribution={"event": 1, "recall_guard": 1}
boundary_true_count=0
forbidden_field_findings=[]
```

### Monitor v0.5 Recheck

The local deterministic monitor was run against `hermes-media` after deployment:

```text
status=PASS
time=2026-05-23T08:51:31Z
gateway=active pid=464934
heartbeat=active/enabled
cognitive_loop=ok timer=active/enabled
counts:
  audit_entries=1939
  events=139
  working_items=121
  candidates=121
  crystallized_records=0
index_health=healthy
doctor=ok
doctor_findings=[hindsight_adapter_disabled warning]
context_router=apply, apply_routes=["all"], llm_judge=disabled
MemorySources:
  record_count=1
  file_size_bytes=1764
  routes={"ambiguous_recall": 1}
  selected_sources={"event": 1, "recall_guard": 1}
  boundary_true_count=0
  forbidden_field_count=0
DeepReflection:
  enabled=true
  injection_mode=auto_bounded
  latest selected_by_source_class={"governance": 2}
  rolling selected_by_source_class={"governance": 4, "working": 14}
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false
disk_usage=/root/.hermes/memory-os 9.7M
PASS=[
  gateway_active,
  heartbeat_timer_active,
  cognitive_loop_timer_active,
  cognitive_loop_last_cycle_present,
  index_healthy,
  doctor_ok,
  status_tool_contract_ok,
  shell_alias_no_env_ok,
  context_router_apply,
  memory_sources_stats_ok
]
WARN=[]
FAIL=[]
```

### Findings

- RH-29 metadata ledger is active on the test host.
- The first attribution record is bounded metadata only.
- No raw private text, section bodies, file paths, tokens, or credentials were
  reported by stats validation.
- All hard-boundary booleans remain false.
- `crystallized_records` remains `0`.
- The monitor can now report route/source-class attribution distribution.

### Interface Note

The remote Hermes command registry does not expose `hermes memory_os ...`
because `memory_os` remains a memory provider, not an enabled general plugin.
During the initial gate, the module entrypoint also worked:

```text
PYTHONPATH=/root/.hermes/plugins:/root/.hermes/memory-os/runtime/python \
  python3 -m plugins.memory.memory_os memory-sources last
```

The Agent OS shell plugin exposes `hermes memory-os-agent-os status` and
`hermes memory-os-agent-os doctor`. The RH-29 follow-up also added and deployed
shell aliases for:

```text
hermes memory-os-agent-os memory-sources last
hermes memory-os-agent-os memory-sources history --limit N
hermes memory-os-agent-os memory-sources stats --hours N
```

Remote alias verification after redeploy and gateway restart:

```text
systemctl --user restart hermes-gateway.service
systemctl --user is-active hermes-gateway.service -> active
MainPID=465190

HERMES_HOME=/root/.hermes hermes memory-os-agent-os memory-sources stats --hours 24
schema_version=memory-os.memory_sources_stats.v0
ledger_exists=true
record_count=1
boundary_true_count=0
forbidden_field_findings=[]
route_distribution={"ambiguous_recall": 1}
selected_source_class_distribution={"event": 1, "recall_guard": 1}
```

Final monitor v0.5 recheck after alias deployment and one controlled
cognitive-loop service run:

```text
time=2026-05-23T09:01:48Z
status=WARN
gateway=active pid=465190
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
MemorySources.record_count=1
MemorySources.file_size_bytes=1764
MemorySources.routes={"ambiguous_recall": 1}
MemorySources.selected_sources={"event": 1, "recall_guard": 1}
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
shell_alias_no_env.status_ok=true
shell_alias_no_env.doctor_ok=true
shell_alias_no_env.memory_sources_ok=true
PASS includes memory_sources_stats_ok
WARN=[rh26_casual_empty]
FAIL=[]
```

`rh26_casual_empty` is an expected observation warning: the casual continuity
probe had no clean, route-eligible context after the latest cognitive-loop run.
The monitor no longer escalates this empty casual context to FAIL, and it now
checks the last systemd service result for heartbeat/cognitive-loop services so
stale `exit-code` failures are visible.

## Monitor v0.6 Audit Breakdown Gate

Date: 2026-05-24
Host: 10.20.3.200 (`hermes-media`)
Mode: read-only monitor script, no service restart, no heartbeat trigger, no
cleanup/apply, no private body inspection

Command:

```text
python scripts/memory_os_3_200_monitor.py --host hermes-media --output summary
```

Result:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=465190
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok
context_router=apply apply_routes=["all"] llm_judge=disabled

counts:
  audit_entries=2524
  events=164
  working_items=126
  candidates=126
  crystallized_records=0

audit_actions.recent_window=250
audit_actions.recent_top:
  runtime_heartbeat=105
  write_working_document=104
  append_event=10
  inner_drive_event_processed=10
  ops_gate_report_written=4
  working_item_expired=3
  cognitive_loop_cycle_completed=2
  digest_daily_written=2

heartbeat_state:
  exists=true
  fresh=true
  age_seconds=32
  processed_event_count=164
  last_processed_event_id=evt_rh15_projection_20260521T010000Z

working_status:
  lingering.json:
    items=126
    active=40
    expired=86
    avg_weight=0.235779

MemorySources:
  record_count=6
  file_size_bytes=8688
  routes={"ambiguous_recall": 1, "casual_continuity": 5}
  selected_sources={"event": 6, "recall_guard": 1}
  selected_headings={"Recall Clarification Guard": 1, "Recent Event Summaries": 6}
  dropped_headings={
    "Conversation Carryover": 6,
    "Current Foreground Task": 6,
    "Indexed Recall": 1,
    "Working Memory": 6
  }
  boundary_true_count=0
  forbidden_field_count=0

compaction.focus_none_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
disk_usage=/root/.hermes/memory-os 11M
```

Interpretation:

- Monitor v0.6 is functioning as a read-only audit/source breakdown probe.
- The earlier audit growth diagnosis is confirmed: recent audit volume is
  dominated by `runtime_heartbeat` and `write_working_document`.
- Heartbeat liveness is now observable through `heartbeat_state.json`, not only
  through audit entries.
- Working memory is not currently expanding; the dominant working document has
  40 active and 86 expired items.
- MemorySources attribution remains bounded and contains no forbidden fields or
  boundary violations.
- RH-27b is still not implemented. This is the pre-change baseline mechanism
  that should be used before audit write behavior is changed.

## RH-27b Audit Noise Control Deployment Gate

Date: 2026-05-24
Host: 10.20.3.200 (`hermes-media`)
Mode: test-host installer deployment; controlled heartbeat validation; no
gateway restart; no cleanup/apply; no private body inspection

Local verification before deployment:

```text
python -m pytest -q
382 passed

python -m pytest tests/plugins/memory/test_memory_os_runtime.py \
  tests/plugins/memory/test_memory_os_working.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q
32 passed

git diff --check
pass
```

Remote deployment:

```text
HERMES_HOME=/root/.hermes \
  bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes

provider=memory_os
memory-os-agent-os enabled=true
heartbeat timer active/enabled
cognitive-loop timer active/enabled
doctor=ok with expected hindsight_adapter_disabled warning
```

Controlled heartbeat probe after deployment:

```text
systemctl --user start hermes-memory-os-heartbeat.service
service_returncode=0

before_total=2528
after_total=2528
total_delta=0
action_delta={}

before_state:
  last_attempt_at=2026-05-24T04:14:18.525476+00:00
  last_heartbeat_at=2026-05-24T04:14:18.525476+00:00
  processed_event_count=164

after_state:
  last_attempt_at=2026-05-24T04:14:44.801415+00:00
  last_heartbeat_at=2026-05-24T04:14:44.801415+00:00
  processed_event_count=164
  last_error=null
```

Interpretation:

- a no-op/decay-only heartbeat no longer appends `runtime_heartbeat` audit
  records
- generic `write_working_document` audit noise is not emitted for decay-only
  writes
- heartbeat liveness is still observable through `heartbeat_state.json`
- processed event count remained stable at 164, as expected for a no-op
  heartbeat

Post-deployment monitor:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=465190
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok
context_router=apply apply_routes=["all"] llm_judge=disabled

counts:
  audit_entries=2528
  events=164
  working_items=126
  candidates=126
  crystallized_records=0

heartbeat_state:
  fresh=true
  age_seconds=12
  processed_event_count=164

working_status:
  lingering.json:
    items=126
    active=40
    expired=86

MemorySources:
  record_count=6
  boundary_true_count=0
  forbidden_field_count=0

compaction.focus_none_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

## RH-28e Global Low-Clue Ingress Routing Validation

Date: 2026-05-24

Trigger:

```text
Telegram live test:
  /new
  继续昨天那个。

Observed before RH-28e:
  live prefetch route=casual_continuity
  selected_headings=[Recent Event Summaries]
  Telegram clarify/session_search path produced a narrow shortlist and missed
  one expected topic until the owner corrected it.
```

Root cause:

```text
The shared provider ingress classifier `plan_context_route()` did not classify
deictic continuation requests such as "继续昨天那个。", "继续上次那个。", or
"接着刚才那条。" as low-clue recall queries.

Because `MemoryProvider.prefetch()` is the global provider entrance, the fix is
global to all Hermes entrances that call prefetch. It is not a Telegram-specific
handler patch and does not hard-code content topics.
```

Local verification:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_context_router.py \
  tests/plugins/memory/test_memory_os_low_clue_recall.py \
  tests/plugins/memory/test_memory_os_memory_sources.py -q

54 passed

python -m pytest -q
413 passed
```

Remote staging verification:

```text
host=10.20.3.200
staging=/root/Hermes-Memory-OS-rh28c-20260524154927

python -m pytest \
  tests/plugins/memory/test_memory_os_context_router.py \
  tests/plugins/memory/test_memory_os_low_clue_recall.py \
  tests/plugins/memory/test_memory_os_memory_sources.py -q

54 passed
```

Deployment:

```text
installer=--test-host --llm-judge-preset report-only
gateway_restart=success
gateway=active
pid=476553
```

Bounded provider-ingress probe:

```text
query="继续昨天那个。"
context_chars=538
has_recall_guard=true
has_do_not_answer_certain=true
route=ambiguous_recall
query_class=ambiguous_recall
selected_headings=[Recall Clarification Guard]
dropped_headings=[Conversation Carryover, Working Memory, Recent Event Summaries]
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_relationship_write=false
boundary.actual_crystallized_approval=false
boundary.hindsight_exported=false
```

Low-clue dry-run comparison:

```text
query="继续昨天那个。"
decision=ask_choice
candidate_count=4
candidate_quality.raw_candidate_count=111
candidate_quality.cluster_count=46
candidate_quality.merged_duplicates=65
candidate_quality.title_normalization_applied=true
llm_judge.status=ok
llm_judge.mode=report_only
llm_judge.confidence=0.12
llm_judge.selected_candidate_id=""
llm_judge.reason_codes=[ambiguous_query, low_clue_no_specific_terms, no_clear_match]
```

Post-deploy monitor:

```text
status=WARN
PASS includes:
  gateway_active
  heartbeat_timer_active
  heartbeat_state_fresh
  cognitive_loop_timer_active
  cognitive_loop_last_cycle_present
  index_healthy
  doctor_ok
  status_tool_contract_ok
  shell_alias_no_env_ok
  context_router_apply
  memory_sources_stats_ok
  low_clue_llm_judge_available
  low_clue_recall_probe_ok
WARN=[rh26_casual_empty]
FAIL=[]

MemorySources.routes={"ambiguous_recall": 1, "casual_continuity": 13}
MemorySources.selected_headings={"Conversation Carryover": 1,
  "Current Foreground Task": 3,
  "Recall Clarification Guard": 2,
  "Recent Event Summaries": 11}
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
compaction.focus_none_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

Interpretation:

```text
RH-28e fixes the global ingress gap. The phrase "继续昨天那个。" now enters the
same low-clue recall guard as the dry-run path before any Telegram-specific
clarify/session_search behavior can narrow the candidate set.

The live LLM judge remains report-only. It contributes confidence metadata but
does not alter the deterministic ask_choice decision.
```

### RH-28e Priority Correction After Telegram Retest

The first RH-28e deployment fixed route classification but not the full live
output path. A follow-up Telegram retest exposed this record:

```text
created_at=2026-05-24T09:11:12Z
query_class=ambiguous_recall
route=ambiguous_recall
route_reason_codes=[low_clue_deictic_continue]
router_applied=false
selected_headings=[Current Foreground Task]
```

Root cause:

```text
RH-25.1 deferred foreground resume still matched broad phrases like
"继续昨天那个。" before context-router apply, set foreground_task_only=true, and
forced the output to Current Foreground Task.
```

Corrected behavior:

```text
Broad deictic recall:
  "继续昨天那个。", "继续上次那个。", "接着刚才那条。"
  -> ambiguous_recall
  -> Recall Clarification Guard

Explicit foreground/deferred task:
  "继续当前任务", "continue the deferred task", "继续搁置的任务"
  -> foreground_control
```

Local verification after the priority correction:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_current_task_anchor.py \
  tests/plugins/memory/test_memory_os_context_router.py \
  tests/plugins/memory/test_memory_os_low_clue_recall.py \
  tests/plugins/memory/test_memory_os_memory_sources.py -q

64 passed

python -m pytest -q
414 passed
```

Remote verification:

```text
host=10.20.3.200
staging=/root/Hermes-Memory-OS-rh28c-20260524154927
related_tests=64 passed
installer=--test-host --llm-judge-preset report-only
gateway=active
pid=476963
```

Provider-ingress probe after correction:

```text
query="继续昨天那个。"
context_chars=538
has_recall_guard=true
has_current_foreground=false
has_working_memory_section=false
prompt_has_current_task_anchor=false
route=ambiguous_recall
query_class=ambiguous_recall
router_applied=true
selected_headings=[Recall Clarification Guard]
dropped_headings=[Conversation Carryover, Working Memory, Indexed Recall, Recent Event Summaries]
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_relationship_write=false
boundary.actual_crystallized_approval=false
boundary.hindsight_exported=false
```

Post-correction monitor:

```text
status=WARN
WARN=[rh26_casual_empty]
FAIL=[]
index_health=healthy
doctor=ok
context_router=apply
low_clue_recall.judge_mode=report_only
low_clue_recall.llm_status=no_clear_match
MemorySources.routes={"ambiguous_recall": 3, "casual_continuity": 12}
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
compaction.focus_none_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

## 2026-05-24 RH-28c Low-Clue Candidate Quality Validation

Purpose:

- validate that low-clue recall fixes candidate-set quality, not a
  content-specific wording case
- compare deterministic mode and report-only LLM judge mode on the same host
- prove report-only judge adds diagnostic metadata without changing live
  behavior

Local code validation:

```text
python -m pytest tests/plugins/memory/test_memory_os_low_clue_recall.py -q
13 passed

python -m pytest \
  tests/plugins/memory/test_memory_os_low_clue_recall.py \
  tests/plugins/memory/test_memory_os_context_router.py \
  tests/plugins/memory/test_memory_os_memory_sources.py -q
44 passed
```

Remote deployment:

```text
host=10.20.3.200
install path=/root/.hermes/memory-os/runtime/python
installer preset=--test-host --llm-judge-preset report-only

low_clue_recall.enabled=true
low_clue_recall.llm_judge.enabled=true
low_clue_recall.llm_judge.mode=report_only
low_clue_recall.llm_judge.provider=hermes_default
```

Gateway reload:

```text
systemctl --user restart hermes-gateway.service
gateway=active
pid=474841
```

Judge availability:

```text
low_clue_recall.judge_availability.available=true
status=available
api_mode=codex_responses
resolved_provider=openai-codex
resolved_model=gpt-5.4-mini
degrades_to=deterministic_fallback

doctor=ok
low_clue_findings=[]
```

Important environment note:

- report-only judge availability must be checked from the Hermes venv/runtime
  path
- system Python can report a false adapter import failure because it does not
  have the installed Hermes provider package path
- live monitor and shell alias checks use the Hermes runtime path and report
  the judge as available

A/B dry-run probe:

```text
query="继续昨天那个。"
```

Mode A, deterministic only:

```text
--llm-judge none
decision=ask_choice
reason_codes=[multiple_plausible_candidates]
candidate_count=6
llm_judge.status=disabled

candidate_quality:
  raw_candidate_count=112
  cluster_count=45
  merged_duplicates=67
  feedback_penalty_applied=true
  diversity_applied=false
  source_distribution={"memory_sources": 3, "working": 109}

boundaries:
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_relationship_write=false
  actual_crystallized_approval=false
  hindsight_exported=false
```

Mode B, report-only judge:

```text
--llm-judge report-only
decision=ask_choice
reason_codes=[multiple_plausible_candidates]
candidate_count=6
llm_judge.status=ok
llm_judge.confidence=0.18
llm_judge.selected_candidate_id=""
llm_judge.reason_codes=[
  no_clear_match,
  ambiguous_query,
  all_candidates_low_specificity
]

candidate_quality:
  raw_candidate_count=112
  cluster_count=45
  merged_duplicates=67
  feedback_penalty_applied=true
  diversity_applied=false
  source_distribution={"memory_sources": 3, "working": 109}

boundaries:
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_relationship_write=false
  actual_crystallized_approval=false
  hindsight_exported=false
```

Interpretation:

- RH-28c fixes the general candidate-generation layer:
  duplicate topic candidates are clustered before display.
- The report no longer treats repeated variants of a single automation topic
  as independent evidence.
- The test-host candidate pool is still working-heavy after filtering
  governance/system metadata. That is the current data state, not a reason to
  hard-code specific topics or lower thresholds.
- LLM judge adds value in report-only mode by confirming low confidence and
  `no_clear_match`; it does not change the deterministic `ask_choice`
  decision.
- Live prefetch remains deterministic and does not wait on LLM judge calls.

Post-deploy monitor:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=474841
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok
shell_alias_no_env_ok=true
context_router=apply apply_routes=["all"]

low_clue_recall:
  enabled=true
  judge_mode=report_only
  decision=ask_choice
  candidate_count=4
  llm_status=ok
  llm_available=true

MemorySources:
  record_count=11
  boundary_true_count=0
  forbidden_field_count=0

compaction.focus_none_count=0

DeepReflection:
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false
```

Conclusion:

RH-28c is ready for Claude review. The remaining open design question is not
whether to hard-code content-specific recall rules. That is rejected. The next
possible improvement is broader source coverage for candidate generation when
the safe candidate pool is dominated by working-memory records.

## 2026-05-24 RH-28d Candidate Title Normalization Validation

Purpose:

- make low-clue recall candidates readable as topic titles instead of raw
  conversation fragments
- keep the fix generic: no topic-specific rules for n8n, Make, ComfyUI, or
  internet collection
- keep report-only LLM judge out of live decision authority

Implementation summary:

- candidate clusters now normalize their display labels
- transcript scaffolding such as `User:` / `Assistant:` and pipe-separated
  turns is stripped
- system-note and self-review memory prompts are filtered
- artifact paths such as `MEDIA:/...`, local file paths, and common file
  extensions are stripped before title selection
- long sentence-like labels fall back to compact topic-term titles
- the report exposes `candidate_quality.title_normalization_applied` and
  `candidate_quality.max_title_chars`

Local validation:

```text
python -m pytest tests/plugins/memory/test_memory_os_low_clue_recall.py -q
20 passed

python -m pytest \
  tests/plugins/memory/test_memory_os_low_clue_recall.py \
  tests/plugins/memory/test_memory_os_context_router.py \
  tests/plugins/memory/test_memory_os_memory_sources.py -q
51 passed

git diff --check
pass
```

Remote deployment:

```text
host=10.20.3.200
remote staging low-clue tests=20 passed
installer=--test-host --llm-judge-preset report-only
gateway=active
pid=476094
```

A/B dry-run probe:

```text
query="继续昨天那个。"
```

Mode A, deterministic only:

```text
--llm-judge none
decision=ask_choice
reason_codes=[multiple_plausible_candidates]
candidate_count=6
llm_judge.status=disabled

candidate_quality:
  raw_candidate_count=108
  cluster_count=46
  merged_duplicates=62
  max_title_chars=64
  title_normalization_applied=true
  feedback_penalty_applied=true
  source_distribution={"memory_sources": 3, "working": 105}

boundaries:
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_relationship_write=false
  actual_crystallized_approval=false
  hindsight_exported=false
```

Mode B, report-only judge:

```text
--llm-judge report-only
decision=ask_choice
reason_codes=[multiple_plausible_candidates]
candidate_count=6
llm_judge.status=no_clear_match
llm_judge.confidence=0.18
llm_judge.selected_candidate_id=""
llm_judge.reason_codes=[
  low_clue_no_specific_terms,
  ambiguous_recall,
  no_unique_semantic_overlap
]

candidate_quality:
  raw_candidate_count=108
  cluster_count=46
  merged_duplicates=62
  max_title_chars=64
  title_normalization_applied=true
  feedback_penalty_applied=true
  source_distribution={"memory_sources": 3, "working": 105}

boundaries:
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_relationship_write=false
  actual_crystallized_approval=false
  hindsight_exported=false
```

Example normalized labels from the host:

```text
Crystallized Candidates（结晶候选）还不是最终沉淀的长期记忆
“准备把你的 MindVideo API 集成进素材收集 Worker，让它从‘搬运工’升级为‘视觉创作者’
我们之前说的互联网数据采集系统，如果重新设计，你会怎么分层
make / 自动化 / Claude / AI / app
comfyui / V9 / checkpoints
FFmpeg 命令的 zoompan 滤镜在处理单张循环图片时出了点逻辑冲突，导致视频编码器以为只有一帧，把后面的内容全“吞”了
```

Post-deployment monitor:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=476094
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok
shell_alias_no_env_ok=true
context_router=apply apply_routes=["all"]

low_clue_recall:
  enabled=true
  judge_mode=report_only
  decision=ask_choice
  candidate_count=4
  llm_status=no_clear_match
  llm_available=true

MemorySources:
  boundary_true_count=0
  forbidden_field_count=0

compaction.focus_none_count=0

DeepReflection:
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false
```

Interpretation:

- RH-28d improved candidate readability without content hard-coding.
- Deterministic and report-only modes still agree on `ask_choice` for the
  low-clue query.
- Report-only judge is useful observation data, but it has not met the bar for
  live decision authority. `bounded_vote` remains deferred.
- A future live gate may consider only limited effects such as reranking or
  `ask_choice -> confirm_one`, and only after judge recommendations align with
  owner feedback over a larger evidence window.

## RH-28 Low-Clue Recall Router + Report-Only LLM Judge

Date: 2026-05-24

Deployment target:

```text
host=10.20.3.200
deploy_dir=/root/Hermes-Memory-OS-rh28-20260524142225
gateway_restart_pid=473191
```

Local implementation verification before deployment:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_low_clue_recall.py \
  tests/plugins/memory/test_memory_os_context_router.py \
  tests/scripts/test_memory_os_3_200_monitor.py \
  tests/scripts/test_memory_os_plugin_install.py -q

70 passed

python -m py_compile \
  plugins/memory/memory_os/low_clue_recall.py \
  plugins/memory/memory_os/prefetch.py \
  plugins/memory/memory_os/cli.py \
  scripts/install_memory_os_plugin.py \
  scripts/memory_os_3_200_monitor.py

bash -n scripts/install_memory_os.sh
```

Mode A: deterministic-only install:

```text
bash scripts/install_memory_os.sh \
  --yes \
  --test-host \
  --hermes-home /root/.hermes \
  --llm-judge-preset none

llm_judge_preset=none
low_clue_recall.enabled=true
low_clue_recall.llm_judge.enabled=false
low_clue_recall.llm_judge.mode=none
low_clue_recall.llm_judge.timeout_ms=8000
gateway=active pid=471982
```

Mode A deterministic probes:

```text
hermes memory-os-agent-os low-clue-recall dry-run \
  --query "继续昨天那个。" \
  --llm-judge none

decision=ask_choice
candidate_count=4
llm_judge.status=disabled
boundaries all false

hermes memory-os-agent-os low-clue-recall dry-run \
  --query "你还记得我之前跟你说过的一个设计吗？" \
  --llm-judge none

decision=ask_choice
candidate_count=4
llm_judge.status=disabled
boundaries all false

hermes memory-os-agent-os low-clue-recall dry-run \
  --query "那个数据采集系统怎么分层？" \
  --llm-judge none

decision=ask_choice
candidate_count=4
llm_judge.status=disabled
top scores included 1.0 matches for internet data collection candidates
boundaries all false
```

Mode A monitor:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=471982
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok

counts:
  audit_entries=2587
  events=177
  working_items=129
  candidates=129
  crystallized_records=0

low_clue_recall:
  enabled=true
  judge_mode=none
  decision=ask_choice
  candidate_count=4
  llm_status=disabled

MemorySources:
  boundary_true_count=0
  forbidden_field_count=0

DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

Mode B: report-only LLM judge install:

```text
bash scripts/install_memory_os.sh \
  --yes \
  --test-host \
  --hermes-home /root/.hermes \
  --llm-judge-preset report-only

llm_judge_preset=report-only
low_clue_recall.enabled=true
low_clue_recall.llm_judge.enabled=true
low_clue_recall.llm_judge.mode=report_only
low_clue_recall.llm_judge.provider=hermes_default
low_clue_recall.llm_judge.model=null
low_clue_recall.llm_judge.timeout_ms=8000
gateway=active pid=473191
```

Report-only adapter finding and fix:

```text
initial finding:
  report-only returned skipped/hermes_runtime_adapter_unavailable

root cause:
  the OpenAI Codex backend on this host uses the Responses streaming transport
  and requires an instructions field; ordinary responses.create did not work.
  The monitor's provider CLI path also ran under system python, where the
  Memory-OS runtime package named agent could shadow Hermes' agent package.

fix:
  RH-28 judge adapter now calls the Codex Responses streaming endpoint directly
  with instructions, store=false, include=[], and session headers.
  The monitor low-clue probe uses the installed shell alias path so it runs in
  the Hermes runtime environment.

verification:
  monitor low_clue_recall.llm_status=ok after the fix
```

Mode B report-only probes:

```text
query="继续昨天那个。"
deterministic decision=ask_choice
llm_judge.status=no_clear_match
llm_judge.confidence=0.12
llm_judge.selected_candidate_id=""
live decision unchanged
boundaries all false

query="你还记得我之前跟你说过的一个设计吗？"
deterministic decision=ask_choice
llm_judge.status=no_clear_match
llm_judge.confidence=0.18
llm_judge.selected_candidate_id=""
live decision unchanged
boundaries all false

query="那个数据采集系统怎么分层？"
deterministic decision=ask_choice
llm_judge.status=ok
llm_judge.confidence=0.98
llm_judge.selected_candidate_id=lc_working_evt_20260523T055608799381Z_5d9432feac
live decision unchanged
boundaries all false
```

Mode B monitor after report-only fix:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=473191
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok

low_clue_recall:
  enabled=true
  judge_mode=report_only
  decision=ask_choice
  candidate_count=4
  llm_status=ok
  llm_available=true

MemorySources:
  record_count=9
  feedback_count=1
  boundary_true_count=0
  forbidden_field_count=0

compaction.focus_none_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

Interpretation:

- RH-28 deterministic mode prevents low-clue recall from over-committing to a
  single answer.
- report-only LLM judge can identify a likely candidate when the query has a
  strong semantic clue, but it does not change the live deterministic decision.
- ambiguous low-clue prompts remain `ask_choice`.
- the current candidate pool is still biased toward recent working-memory
  items, which is useful data for future source-diversity and recall-quality
  work rather than a boundary failure.
- No sends, executes, identity writes, relationship writes, Hindsight exports,
  or crystallized approvals occurred.

Judge availability recheck after the Hermes-default adapter hardening:

```text
command:
  hermes memory-os-agent-os status

low_clue_recall.judge_availability:
  enabled=true
  mode=report_only
  provider=hermes_default
  available=true
  status=available
  code=ok
  api_mode=codex_responses
  resolved_provider=openai-codex
  resolved_model=gpt-5.4-mini
  credential_present=true
  degrades_to=deterministic_fallback

command:
  hermes memory-os-agent-os doctor

doctor.status=ok
doctor.exit_code=0
low_clue_llm_judge_unavailable finding absent
```

The first monitor implementation checked status/doctor through the direct
provider Python path and produced a false `low_clue_llm_judge_unavailable`
warning because that path did not run in Hermes' installed runtime environment.
The monitor now checks the natural shell alias path:

```text
hermes memory-os-agent-os status
hermes memory-os-agent-os doctor
hermes memory-os-agent-os low-clue-recall dry-run --query "继续昨天那个。" --llm-judge config
```

Latest monitor recheck:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]
PASS includes low_clue_llm_judge_available and low_clue_recall_probe_ok

gateway=active pid=473504
index_health=healthy
doctor=ok

low_clue_recall:
  enabled=true
  judge_mode=report_only
  decision=ask_choice
  candidate_count=4
  llm_status=ok
  llm_available=true

MemorySources:
  boundary_true_count=0
  forbidden_field_count=0

DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

Compatibility interpretation:

- RH-28 report-only judge reuses the configured Hermes provider/model.
- No Hermes source change is required.
- status, doctor, and monitor expose judge availability.
- If a future Hermes upgrade breaks the adapter path, Memory-OS reports a
  warning and degrades to deterministic fallback; status/doctor do not block
  the provider/runtime unless another real error appears.

RH-28b local regression after architecture/code review:

```text
python -m pytest tests/plugins/memory/test_memory_os_low_clue_recall.py -q

10 passed
```

Validated fixes:

- live prefetch disables report-only judge calls, so a slow Hermes provider/model
  adapter cannot delay the owner's active turn
- high-confidence `direct_resume` guard wording now says to state the likely
  match briefly and ask for correction if wrong, rather than treating it like a
  low-confidence choice that always requires another clarification first

RH-28b remote deployment:

```text
host=10.20.3.200
deploy_dir=/root/Hermes-Memory-OS-rh28-20260524142225

python3 -m pytest tests/plugins/memory/test_memory_os_low_clue_recall.py -q
10 passed

bash scripts/install_memory_os.sh \
  --yes \
  --test-host \
  --hermes-home /root/.hermes \
  --llm-judge-preset report-only

gateway restart: test-host only, required to load provider/prefetch runtime code
gateway ActiveState=active
gateway SubState=running
gateway MainPID=474128
gateway Result=success
```

Post-deploy monitor:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=474128
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok findings=[hindsight_adapter_disabled warning]
shell_alias_no_env_ok=true

low_clue_recall:
  enabled=true
  judge_mode=report_only
  decision=ask_choice
  candidate_count=4
  llm_status=ok
  llm_available=true

MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

## 2026-05-24 RH-25.1 Deferred Foreground Task Resume

Real Telegram finding:

```text
13:07 owner: /new
13:07 owner: 继续昨天那个。
13:08 assistant: searched for n8n / AI agent orchestration and answered about n8n
```

Interpretation:

- RH-25/RH-25b preserved same-session foreground tasks and cancellation turns.
- The remaining gap was cross-session deferred resume: after an explicit
  `明天再说` style deferral, a fresh `/new` session could still let unrelated
  Working Memory win over the intended deferred foreground task.
- This is not canonical Memory-OS corruption and not a crystallized-memory
  failure; it is a foreground task lifecycle gap.

Local regression:

```text
test: tests/plugins/memory/test_memory_os_current_task_anchor.py::test_deferred_task_survives_session_reset_for_tomorrow_continue

setup:
  session-1 current task: 继续处理 ComfyUI 的视频问题
  active operation: layout_report.json failed: No composition found
  unrelated working memory: n8n AI agent orchestration discussion
  deferral turn: 这个先放一下，明天再说。
  session reset: new provider instance / session-2
  resume turn: 继续昨天那个。

assertions:
  deferred context contains Current Foreground Task
  resume context contains ComfyUI
  resume context contains layout_report.json failed: No composition found
  resume context contains Continue this deferred foreground task
  resume context excludes Working Memory
  resume context excludes n8n

second case:
  no deferred record exists yet
  resume turn: 继续昨天那个。
  expected: ask owner to choose which prior task to resume
  expected: foreground-only context
  expected: unrelated n8n working memory is not injected
```

Verification:

```text
python -m pytest tests/plugins/memory/test_memory_os_current_task_anchor.py -q
8 passed

python -m pytest \
  tests/plugins/memory/test_memory_os_current_task_anchor.py \
  tests/plugins/memory/test_memory_os_context_router.py \
  tests/plugins/memory/test_memory_os_memory_sources.py -q
39 passed

python -m pytest -q
387 passed
```

10.20.3.200 deployment:

```text
target: 10.20.3.200 only
deploy path: HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes
installer_result: success
doctor: ok with expected hindsight_adapter_disabled warning
heartbeat_timer: active/enabled
cognitive_loop_timer: active/enabled
gateway_restart: hermes-gateway.service restarted on test host only, PID 471307
```

Remote synthetic probe:

```json
{
  "missing_record_asks_choose": true,
  "missing_record_excludes_n8n": true,
  "missing_record_foreground_only": true,
  "missing_record_has_ambiguous": true,
  "with_record_excludes_n8n": true,
  "with_record_foreground_only": true,
  "with_record_has_comfyui": true,
  "with_record_has_error": true,
  "with_record_has_rule": true
}
```

Post-deploy monitor:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=471307
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok
context_router=apply apply_routes=["all"] llm_judge=disabled

counts:
  audit_entries=2569
  events=175
  working_items=127
  candidates=127
  crystallized_records=0

MemorySources:
  record_count=8
  feedback_count=1
  boundary_true_count=0
  forbidden_field_count=0

compaction.focus_none_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

Boundary:

- deferred foreground tasks are stored as bounded runtime system metadata under
  `system/deferred_foreground_tasks.jsonl`
- they are not written to canonical events, working memory, candidates,
  crystallized records, identity, or relationships
- resume turns remain foreground-only so unrelated memory cannot outvote the
  deferred task

## RH-30 Relevance Feedback Audit Deployment Gate

Date: 2026-05-24
Host: 10.20.3.200 (`hermes-media`)
Mode: test-host installer deployment; CLI feedback smoke; read-only monitor;
no gateway restart; no router weight changes; no memory approval

Local verification before deployment:

```text
python -m pytest tests/plugins/memory/test_memory_os_memory_sources.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q
40 passed

python -m pytest -q
385 passed
```

Remote deployment:

```text
HERMES_HOME=/root/.hermes \
  bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes

provider=memory_os
memory-os-agent-os enabled=true
heartbeat timer active/enabled
cognitive-loop timer active/enabled
doctor=ok with expected hindsight_adapter_disabled warning
gateway restart not requested
```

CLI smoke:

```text
HERMES_HOME=/root/.hermes \
  hermes memory-os-agent-os memory-sources feedback last \
    --rating useful --note rh30-smoke

schema_version=memory-os.memory_sources_feedback.v0
status=ok
feedback_id=msfb_20260524T044738044301Z_638cc9b8
memory_source_record_id=msrc_20260523T104634235749Z_9a44a2ce
rating=useful
route=casual_continuity
query_class=casual_continuity
```

Bounded history:

```text
HERMES_HOME=/root/.hermes \
  hermes memory-os-agent-os memory-sources feedback history --limit 3

schema_version=memory-os.memory_sources_feedback_history.v0
record_count=1
ratings=[useful]
```

Stats:

```text
HERMES_HOME=/root/.hermes \
  hermes memory-os-agent-os memory-sources stats --hours 24

schema_version=memory-os.memory_sources_stats.v0
record_count=6
feedback_count=1
feedback_rating_distribution={"useful": 1}
feedback_ledger_exists=true
feedback_file_size_bytes=415
boundary_true_count=0
forbidden_field_findings=[]
```

Post-deployment monitor:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=465190
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok
context_router=apply apply_routes=["all"] llm_judge=disabled

counts:
  audit_entries=2560
  events=174
  working_items=126
  candidates=126
  crystallized_records=0

MemorySources:
  record_count=6
  file_size_bytes=8688
  feedback_count=1
  feedback_ratings={"useful": 1}
  feedback_file_size_bytes=415
  boundary_true_count=0
  forbidden_field_count=0

compaction.focus_none_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

Interpretation:

- RH-30 feedback requires an explicit operator command.
- `last` attaches to the newest Memory Sources attribution record for the
  active profile.
- feedback is stored as bounded metadata under the Memory Sources system
  ledger and a bounded audit marker; it does not alter router weights or any
  memory layer.
- monitor now reports feedback count and rating distribution while preserving
  the existing forbidden-field and boundary checks.

Note:

- the monitor's `recent_top` window still contains pre-RH-27b audit noise until
  the rolling 250-record window advances
- the immediate controlled heartbeat delta is the relevant post-change signal:
  audit did not grow, while heartbeat state refreshed

Controlled cognitive-loop validation:

To avoid waiting on the natural 6-hour timer, the test host received five
bounded RH-27b validation metadata events and then ran one controlled
`hermes-memory-os-cognitive-loop.service` cycle.

The injected events were explicitly marked as test-host validation metadata:

```text
evt_rh27b_validation_20260524T042854_0
evt_rh27b_validation_20260524T042854_1
evt_rh27b_validation_20260524T042854_2
evt_rh27b_validation_20260524T042854_3
evt_rh27b_validation_20260524T042854_4
```

They used `source=cron`, `kind=cron_job_run`, `drive_policy=index_only`, and
`candidate_allowed=false`, so they exercise event processing without creating
new working items, candidates, sends, executes, identity writes, relationship
writes, or crystallized records.

Result:

```text
systemctl --user start hermes-memory-os-cognitive-loop.service
service_returncode=0

before_total=2528
after_total=2559
total_delta=31

processed_event_count:
  before=164
  after=174

new processed events=10
audit_per_processed_event=3.1

action_delta:
  append_event=10
  inner_drive_event_processed=10
  runtime_heartbeat=2
  ops_gate_report_written=2
  cognitive_loop_cycle_completed=1
  digest_daily_written=1
  digest_weekly_written=1
  evidence_scoring_run_written=1
  governance_feedback_events_written=1
  proposal_queue_candidate_created=1
  self_evolution_dry_run_written=1

working_status:
  before lingering.json items=126 active=40 expired=86
  after  lingering.json items=126 active=40 expired=86

heartbeat_state:
  before processed_event_count=164
  after  processed_event_count=174
  after last_error=null
```

Interpretation:

- RH-27b meets the target audit density for this controlled event-processing
  window: `audit_per_processed_event=3.1`, inside the 3-5 target range.
- Cognitive-loop step-level and cycle-level audit records still appear, as
  intended.
- No working/candidate growth occurred from the validation events.
- The post-cycle monitor remained WARN-only with no FAIL findings.

Final post-validation monitor:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=465190
heartbeat=active/enabled service_result=success
cognitive_loop=ok timer=active/enabled service_result=success
index_health=healthy
doctor=ok

counts:
  audit_entries=2559
  events=174
  working_items=126
  candidates=126
  crystallized_records=0

heartbeat_state:
  fresh=true
  processed_event_count=174

working_status:
  lingering.json:
    items=126
    active=40
    expired=86

MemorySources:
  record_count=6
  boundary_true_count=0
  forbidden_field_count=0

compaction.focus_none_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

## RH-28f/RH-28g Global Ingress And Candidate Diversity Validation

Date: 2026-05-24
Host: 10.20.3.200 (`hermes-media`)
Scope: RH-28f shared ingress decision; RH-28g deterministic source-diversity
slot; monitor low-clue ingress matrix; test-host deployment only

Problem confirmed before RH-28f:

```text
继续刚才那个       -> casual_continuity without punctuation
继续刚才那个。     -> ambiguous_recall
继续昨天那个。     -> route=ambiguous_recall but live prefetch could still be
                       stolen by foreground_task_only
```

Root cause:

```text
RH-25 current-task anchor handling,
RH-25.1 deferred resume,
RH-28 low-clue routing,
and MemorySources attribution
were classifying ingress independently.
```

Local verification:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_context_router.py \
  tests/plugins/memory/test_memory_os_current_task_anchor.py \
  tests/plugins/memory/test_memory_os_low_clue_recall.py -q

57 passed

python -m pytest tests/scripts/test_memory_os_3_200_monitor.py -q

17 passed

python -m pytest -q

420 passed
```

Remote staging verification:

```text
python3 -m pytest \
  tests/plugins/memory/test_memory_os_context_router.py \
  tests/plugins/memory/test_memory_os_current_task_anchor.py \
  tests/plugins/memory/test_memory_os_low_clue_recall.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

73 passed
```

Deployment:

```text
bundle=/root/Hermes-Memory-OS-rh28fg-20260524175745
installer=HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host --llm-judge-preset report-only
runtime_copied=ingress.py, context_router.py, low_clue_recall.py
gateway_restart=performed after install
gateway=active pid=477649
```

Bounded ingress probe after gateway restart:

```text
继续昨天那个。:
  route=ambiguous_recall
  headings=[Recall Clarification Guard]

继续刚才那个:
  route=ambiguous_recall
  headings=[Recall Clarification Guard]

继续刚才那个。:
  route=ambiguous_recall
  headings=[Recall Clarification Guard]

继续当前任务:
  route=foreground_control
  headings=[Current Foreground Task]

继续搁置的任务:
  route=foreground_control
  headings=[Current Foreground Task]
  reason_codes=[explicit_deferred_resume]
```

RH-28g candidate diversity evidence:

```text
decision=ask_choice
candidate_count=4
candidate_quality.diversity_applied=true
candidate_quality.raw_candidate_count=113
candidate_quality.cluster_count=46
candidate_quality.source_distribution includes memory_sources and working
selected reason_codes include source_diversity_slot
llm_judge.mode=report_only
llm_judge.status=ok/no_match
```

Post-deploy monitor:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=477649
heartbeat=active/enabled
cognitive_loop=ok timer=active/enabled
index_health=healthy
doctor=ok
context_router=apply apply_routes=["all"]

low_clue_recall:
  enabled=true
  judge_mode=report_only
  decision=ask_choice
  candidate_count=4
  llm_available=true

low_clue_ingress_matrix:
  deictic_yesterday -> Recall Clarification Guard
  deictic_just_now_no_punctuation -> Recall Clarification Guard
  deictic_just_now_punctuation -> Recall Clarification Guard
  continue_current_task -> Current Foreground Task
  explicit_deferred_en -> Current Foreground Task
  explicit_deferred_zh -> Current Foreground Task

MemorySources:
  record_count=13
  routes={"ambiguous_recall": 3, "casual_continuity": 10}
  boundary_true_count=0
  forbidden_field_count=0

compaction.focus_none_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
```

Interpretation:

- RH-28f fixes the global entrance inconsistency. The same low-clue phrase now
  reaches the same route and section headings regardless of punctuation and
  active foreground anchor.
- RH-28g prevents working-only candidate monopolies by reserving a bounded
  diversity slot when another source class clears the fallback score.
- Report-only LLM judge remains observational only. It does not change live
  decisions.
- Candidate topic labels are improved but not final. Attribution-derived labels
  can still be generic and should stay under observation.

## Module Integration Contract Baseline

Date: 2026-05-24
Host: 10.20.3.200 (`hermes-media`)
Document: `29-memory-os-module-integration-contract.md`

Reason:

RH-25/RH-28/RH-29/RH-30 exposed a module-integration failure class:

```text
single-module tests can pass while live provider ingress, foreground anchors,
context routing, low-clue recall, and MemorySources attribution still disagree.
```

Live evidence used for the contract:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

gateway=active pid=477649
heartbeat_timer=active/enabled
heartbeat_state=fresh
cognitive_loop_timer=active/enabled
cognitive_loop_last_cycle=ok
index_health=healthy
doctor=ok
status_tool_contract=ok
context_router=apply apply_routes=["all"]

low_clue_ingress_matrix:
  deictic_yesterday -> ambiguous_recall / Recall Clarification Guard
  deictic_just_now_no_punctuation -> ambiguous_recall / Recall Clarification Guard
  deictic_just_now_punctuation -> ambiguous_recall / Recall Clarification Guard
  continue_current_task -> foreground_control / Current Foreground Task
  explicit_deferred_en -> foreground_control / Current Foreground Task
  explicit_deferred_zh -> foreground_control / Current Foreground Task

MemorySources:
  record_count=13
  feedback_count=1
  boundary_true_count=0
  forbidden_field_count=0

DeepReflection:
  enabled=true
  injection_mode=auto_bounded
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false

crystallized_records=0
compaction.focus_none_count=0
```

Contract decision:

Future RH-31/RH-32/RH-33 and any new cognition module must declare its
integration contract before implementation:

```text
IngressDecision
ContextProjection
MemoryWriteSurface
FeedbackSignal
SchedulerStep
MonitorEvidence
```

This is now a required gate before any new module affects live ingress, prompt
projection, memory writes, feedback scoring, scheduler behavior, or monitor
semantics.

## Post-Contract Monitor Trend Snapshot

Date: 2026-05-24
Host: 10.20.3.200 (`hermes-media`)
Source: scheduled monitor summary plus direct read-only monitor rerun

Scheduled monitor classification:

```text
status=WARN
FAIL=[]
WARN=[rh26_casual_empty]

audit_per_new_event=7.0
working_items=138
candidates=138
working lingering statuses:
  active=48
  expired=90
```

Direct read-only monitor rerun:

```text
time=2026-05-24T13:45:44Z
gateway=active pid=479718
heartbeat=active/enabled service_result=success
heartbeat_state=fresh age_seconds=156
cognitive_loop=ok timer=active/enabled service_result=success

counts:
  audit_entries=2685
  events=191
  working_items=138
  candidates=138
  crystallized_records=0

index_health=healthy
prefetch_mode=indexed
doctor=ok
doctor_findings=[hindsight_adapter_disabled warning]
status_tool_contract=ok
shell_alias_no_env_ok=true
context_router=apply apply_routes=["all"]
```

Low-clue recall and ingress evidence:

```text
low_clue_recall:
  enabled=true
  judge_mode=report_only
  decision=ask_choice
  candidate_count=4
  internal_label_count=0
  llm_status=no_match
  llm_available=true

low_clue_ingress_matrix:
  deictic_yesterday -> Recall Clarification Guard
  deictic_just_now_no_punctuation -> Recall Clarification Guard
  deictic_just_now_punctuation -> Recall Clarification Guard
  continue_current_task -> Current Foreground Task
  explicit_deferred_en -> Current Foreground Task
  explicit_deferred_zh -> Current Foreground Task
```

MemorySources:

```text
record_count=15
file_size_bytes=29113
feedback_count=1
routes={"ambiguous_recall": 7, "casual_continuity": 8}
selected_sources={"carryover": 1, "event": 5, "foreground": 4, "recall_guard": 6}
boundary_true_count=0
forbidden_field_count=0
```

DeepReflection:

```text
enabled=true
injection_mode=auto_bounded
latest.selected_by_source_class={"governance": 2}
latest.dropped_by_source_class={"governance": 1}
rolling.selected_by_source_class={"governance": 16, "working": 14}
rolling.dropped_by_source_class={"governance": 7, "working": 7}
actual_send=false
actual_execute=false
actual_identity_write=false
actual_crystallized_approval=false
```

Interpretation against `29-memory-os-module-integration-contract.md`:

- Core provider/runtime remains healthy enough to continue observation:
  gateway, heartbeat, cognitive loop, index, doctor, status-tool contract, and
  shell aliases all pass.
- `rh26_casual_empty` remains the only WARN and is still treated as expected
  observation noise.
- MemorySources satisfies the RH-29 safety gate: no boundary flags and no
  forbidden fields.
- Low-clue recall satisfies the RH-28f/RH-28g live route/heading gate and the
  LLM judge remains report-only.
- RH-27b audit density is improved but not mature: the scheduled monitor
  reports `audit_per_new_event=7.0`, which is lower than the earlier
  pre-RH-27b noise band but still above the target 3-5 range.
- Working/candidate accumulation needs continued observation. The current
  `lingering.json` state has more expired than active items (`90` expired vs
  `48` active), which is not a boundary failure but is a signal to keep watching
  retention and candidate lifecycle before declaring the loop mature.

Task status from this snapshot:

```text
Continue:
  - RH-27b audit density observation until audit_per_new_event repeatedly stays
    within or near the 3-5 target range.
  - working/candidate lifecycle observation, especially expired/active ratio.
  - RH-28 Telegram live behavior observation for low-clue recall candidate
    completeness and duplicate handling.

Do not advance yet:
  - RH-31/RH-32/RH-33, unless a real monitored finding requires one.
  - any stronger LLM judge live influence.

Safe to keep:
  - current provider/runtime
  - context_router apply
  - MemorySources metadata-only attribution
  - LLM judge report-only observation
  - cognitive loop no-send test-host mode
```

## 2026-05-25 RH-31 Eval Harness Remote Smoke

Source: read-only remote smoke against `10.20.3.200` after installing the
current RH-31.0-31.3 implementation into `/root/.hermes`.

Provider/shell entry:

```text
command:
  hermes memory-os-agent-os eval rh31 run --fixture synthetic --adapter all --no-write-report

schema_version=memory-os.rh31_summary.v0
status=warning
adapter_count=6
case_count=6
score_count=27
failure_count=4
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1, "projection_miss": 1}
boundary_true_count=0
forbidden_field_count=0
report_written=false
```

Interpretation:

- The shell alias resolves the provider/runtime eval implementation.
- The status is `warning` because the first deterministic scorecard exposes
  known recall misses; this is measurement output, not a runtime boundary
  failure.
- The safety gate passed: `boundary_true_count=0` and
  `forbidden_field_count=0`.
- The no-write smoke did not create an eval report.

Monitor integration:

```text
command:
  python scripts/memory_os_3_200_monitor.py --host hermes-media --output summary

monitor_status=WARN
RH31Eval={"status": "warning", "adapter_count": 6, "failure_count": 4,
          "boundary_true_count": 0, "forbidden_field_count": 0,
          "report_written": false}
PASS includes rh31_eval_safety_ok
WARN includes rh31_eval_has_failures
FAIL=[]
```

This validates the P1C requirement: RH-31 can be probed from the monitor
without touching live prefetch, live routing, scheduler behavior,
crystallized approval, send/execute gates, identity, or canonical memory.

## 2026-05-25 RH-31 Scorecard Coverage Follow-Up

Source: post-review local and remote validation after tightening the
`memory_sources_replay` adapter and monitor snapshot contract.

Finding:

```text
memory_sources_replay previously generated scores for all 6 synthetic cases
after replaying only the first 3 cases into MemorySources.
```

Fix:

```text
memory_sources_replay now replays all 6 cases before scoring.
Each score records:
  record_count=6
  replayed_case_count=6
  replayed_case_ids=[all synthetic case ids]
```

Local evidence:

```text
command:
  python -m plugins.memory.memory_os eval rh31 run --fixture synthetic \
    --adapter memory_sources_replay --no-write-report

status=pass
case_count=6
score_count=6
failure_count=0
boundary_true_count=0
forbidden_field_count=0
report_dir=""
```

Monitor contract follow-up:

```text
The monitor now stores RH-31 summary-only metadata in snapshots.
The `rh31_eval` snapshot block keeps status/count/distribution fields and
does not retain the per-score `scores` array.
```

Local monitor JSON evidence before remote redeploy:

```text
command:
  python scripts/memory_os_3_200_monitor.py --host hermes-media --output json

rh31_eval.status=warning
rh31_eval.score_count=27
rh31_eval.failure_count=4
rh31_eval.boundary_true_count=0
rh31_eval.forbidden_field_count=0
rh31_eval.report_written=false
rh31_eval.scores field absent
```

Remote deployment gate:

```text
Completed. The provider/runtime was redeployed to 10.20.3.200.
```

Remote no-write scorecard after redeploy:

```text
command:
  hermes memory-os-agent-os eval rh31 run --fixture synthetic \
    --adapter all --no-write-report

schema_version=memory-os.rh31_summary.v0
status=warning
adapter_count=6
case_count=6
score_count=27
failure_count=4
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1, "projection_miss": 1}
memory_sources_replay_record_counts=[6]
memory_sources_replay_replayed_counts=[6]
boundary_true_count=0
forbidden_field_count=0
report_dir=""
```

Remote monitor after local summary-only snapshot change:

```text
command:
  python scripts/memory_os_3_200_monitor.py --host hermes-media --output json

monitor_status=WARN
FAIL=[]
WARN=["rh31_eval_has_failures", "rh26_casual_empty"]
rh31_has_scores=false
rh31_status=warning
rh31_score_count=27
rh31_failure_count=4
rh31_boundary_true_count=0
rh31_forbidden_field_count=0
```

## 2026-05-25 RH-17 Metadata Retention Dry-Run Smoke

Source: read-only remote smoke against `10.20.3.200` after deploying the
metadata retention helper.

Command:

```text
hermes memory-os-agent-os metadata-retention
```

Result:

```text
schema_version=memory-os.metadata_retention_plan.v0
dry_run=true
canonical_paths_touched=[]
actions=[]

ledgers:
  memory_sources:
    exists=true
    total_records=31
    retained_records=31
    archive_candidate_records=0
  memory_sources_feedback:
    exists=true
    total_records=1
    retained_records=1
    archive_candidate_records=0
  consolidation_suggestions:
    exists=false
    total_records=0
    archive_candidate_records=0

report_roots:
  rh31_eval_reports:
    exists=false
    candidate_count=0
    archive_candidate_count=0
  rh32_suggestion_reports:
    exists=false
    candidate_count=0
    archive_candidate_count=0
```

Interpretation:

- The helper is dry-run only.
- It plans archive-before-prune work for metadata ledgers and report dirs.
- It does not touch canonical Memory-OS paths.
- Current test-host metadata volume is still inside the 30-day retention
  window, so no archive/prune candidates are expected.

Monitor integration:

```text
shell_alias_no_env.metadata_retention_ok=true
PASS includes shell_alias_no_env_ok
FAIL=[]
```

This closes the immediate RH-17 metadata/report retention gap at the planning
layer. Physical apply/prune remains intentionally open and should require a
separate gate.

## 2026-05-25 P1-J/K/L Module Coverage And Monitor Evidence

Source: test-host redeploy and read-only validation against `10.20.3.200`.

Deployment:

```text
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host
```

Result:

```text
provider=memory_os
shell_plugin=memory-os-agent-os enabled
heartbeat_timer=active/enabled
cognitive_loop_timer=active/enabled
gateway_restart_performed=false
```

### P1-J SessionMirror Dry-Run

Command:

```text
hermes memory-os-agent-os modules run-once --module session_mirror --dry-run
```

Result:

```text
schema_version=memory-os.session_mirror_report.v0
status=ok
dry_run=true
session_count=50
covered_session_count=26
new_event_count=24
written_event_ids=[]
findings=[]
```

Interpretation:

- The 24 pending sessions can be represented as bounded mirror events in
  dry-run.
- No events were written in this gate.
- No private message bodies were printed or copied into the validation report.
- A real apply remains a separate reviewed gate.

### P1-K Module Status / Doctor Parity

The previous live mismatch was:

```text
inner_drive.status.processed_event_count=0
heartbeat_state.processed_event_count=221
self_evolution standalone doctor warned about missing injected dependencies
```

Post-deploy `modules status` now makes the source-of-truth split explicit:

```text
inner_drive.status.processed_event_count=0              # module-local state
inner_drive.status.runtime_heartbeat.exists=true
inner_drive.status.runtime_heartbeat.processed_event_count=221
inner_drive.status.runtime_heartbeat.last_processed_event_id=evt_gov_d632960417e868fb3e29

self_evolution.status.dependency_context=
  "standalone status reads reports; doctor injects loop dependencies"
self_evolution.status.report_count=11
self_evolution.status.proposal_count=11
self_evolution.status.last_status=ok
```

Post-deploy `modules doctor` no longer reports
`missing_required_runtime_dependency` for `self_evolution`:

```text
modules_doctor.status=warning
findings=[
  mailbox_root_missing: warning,
  pending_candidates_present: warning
]
self_evolution.doctor.status=ok
self_evolution.doctor.findings=[]
inner_drive.doctor.status=ok
inner_drive.doctor.event_count=221
```

Interpretation:

- `inner_drive` now exposes runtime heartbeat state alongside module-local state,
  so operator output no longer makes the running heartbeat look idle.
- `self_evolution doctor` is now called with the same dependency family used by
  the cognitive loop (`ops_gate`, `proposal_queue`, `evidence_scoring`).
- Remaining warnings are expected operator state, not hidden dependency failure.

### P1-L Per-Module Artifact Monitor Summary

Command:

```text
python scripts/memory_os_3_200_monitor.py --host hermes-media --output json
```

Result:

```text
monitor_status=WARN
FAIL=[]
PASS includes module_artifact_summary_ok
WARN=["rh31_eval_has_failures", "rh26_casual_empty"]
```

New bounded `module_artifacts` summary:

```text
module_count=16
digest.daily_artifact_count=2
digest.weekly_artifact_count=1
digest.household_artifact_exists=true
wandering.output_count=10
wandering.would_send_count=10
evidence.evidence_count=545
evidence.score_count=545
evidence.subject_counts={crystallized_candidate:158,event:216,proposal:13,working:158}
proposal_queue.candidate_count=14
proposal_queue.state_counts={approved_for_proposal:1,candidate:13}
self_evolution.report_count=11
self_evolution.proposal_count=11
self_evolution.last_status=ok
governance_feedback.emitted_event_count=57
deep_reflection.report_count=17
deep_reflection.analysis_artifact_count=17
deep_reflection.current_injection_exists=true
deep_reflection.wandering_seed_count=2
ops_gate.report_count=22
ops_gate.blocked_decision_count=0
speak_gate.would_send_count=0
speak_gate.actual_send=false
mailbox.would_send_count=0
```

Other live monitor signals:

```text
gateway=active
heartbeat_state.fresh=true
cognitive_loop.last_status=ok
index_health.state=healthy
doctor.status=ok
status_tool_contract.status=ok
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_findings=[]
RH31.boundary_true_count=0
RH31.forbidden_field_count=0
low_clue_ingress_matrix=all expected routes/headings matched
compaction.focus_none_count=0
crystallized_records=0
```

Interpretation:

- The monitor now shows each cognitive-loop module's artifact trend without
  reading private bodies.
- `speak_gate.actual_send=false`; no automatic send boundary was crossed.
- This closes the immediate observability gap where a healthy cognitive loop
  could hide inactive per-module outputs.

Local verification for this P1-J/K/L package:

```text
python -m pytest tests\plugins\memory\test_memory_os_cli_modules.py tests\scripts\test_memory_os_3_200_monitor.py -q
38 passed

python -m pytest -q
449 passed

git diff --check
clean
```

## 2026-05-25 P1-J SessionMirror / RH-28 Candidate Correlation Probe

Source: read-only diagnostic against `10.20.3.200`.

Purpose:

- Check whether the 24 pending SessionMirror sessions plausibly explain the
  earlier real Telegram low-clue candidate omission.
- Do this without printing raw private message bodies.

Method:

- Load SessionMirror discovery state read-only.
- Compute pending versus provider-captured counts.
- Scan only bounded topic-signature groups in memory; print aggregate counts
  and hashed session examples only.
- Do not write events, MemorySources, feedback, candidates, or audit records.

Result:

```text
schema_version=memory-os.session_mirror_correlation_probe.v0
dry_run_only=true
session_count=50
covered_session_count=26
pending_session_count=24
pending_platform_counts={acp:5, cli:8, telegram:11}
pending_event_kind_counts={conversation_turn_mirrored:16, session_observed:8}
pending_message_count_min=0
pending_message_count_max=253
raw_private_body_printed=false

topic_group_counts.pending_sessions={
  automation_orchestration:1,
  memory_os:8
}

topic_group_counts.provider_captured_events={
  automation_orchestration:33,
  comfyui_media:47,
  internet_data_collection:10,
  memory_os:53,
  mindvideo_api:10
}

topic_group_counts.existing_mirrored_events={}

correlation_findings=[
  automation_orchestration: pending_and_provider_both_present,
  memory_os: pending_and_provider_both_present
]
```

Interpretation:

- Pending sessions exist and may still be worth a one-time test-host apply
  review for coverage.
- The specific `internet_data_collection` topic is already present in
  provider-captured events and was not detected as pending-only in this bounded
  probe.
- Therefore the earlier real Telegram candidate omission should not be assumed
  to be caused by SessionMirror pending coverage.
- Next diagnostic owner is P1-G / RH-28 live Telegram retest and candidate
  collection quality, not immediate SessionMirror apply.

## 2026-05-25 P1-G Telegram Low-Clue Retest

Source: real Telegram test plus read-only Memory-OS probes on `10.20.3.200`.

Telegram transcript excerpt supplied by owner:

```text
2026-05-25 11:48 Asia/Shanghai
/new
继续昨天那个

agent response:
  1. 我们之前说的互联网数据采集系统，如果重新设计，你会怎么分层
  2. [The user sent an image~ Here's what I can see
  3. Built-in / Hermes / skill / Voice / voicebox
  4. 我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么
```

Low-clue dry-run against the same query:

```text
command:
  hermes memory-os-agent-os low-clue-recall dry-run \
    --query '继续昨天那个' --llm-judge none

schema_version=memory-os.low_clue_recall.v0
query_class=ambiguous_recall
decision=ask_choice
candidate_count=4
boundaries.actual_send=false
boundaries.actual_execute=false
boundaries.actual_identity_write=false
boundaries.actual_crystallized_approval=false
candidate_quality.raw_candidate_count=128
candidate_quality.cluster_count=41
candidate_quality.merged_duplicates=87
candidate_quality.title_normalization_applied=true
candidate_quality.diversity_applied=false
candidate_quality.source_distribution={working:127,event:1}
```

The dry-run candidate labels matched the Telegram response. The first candidate
was the intended `internet_data_collection` topic, so the earlier omission is
not reproduced in this pass.

MemorySources in the same 2h window:

```text
record_count=1
route_distribution={ambiguous_recall:1}
query_class_distribution={ambiguous_recall:1}
selected_source_class_distribution={recall_guard:1}
boundary_true_count=0
forbidden_field_findings=[]
```

Monitor after the Telegram test:

```text
monitor_status=WARN
FAIL=[]
WARN includes index_stale and rh31_eval_has_failures
low_clue_ingress_matrix=all expected routes/headings matched
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_findings=[]
compaction.focus_none_count=0
```

Interpretation:

- The live Telegram response appears to be using the RH-28 Recall Clarification
  Guard rather than bypassing it with raw `session_search` output.
- Candidate 1 shows the `internet_data_collection` topic is now present.
- Candidate 2 is a poor topic candidate: an attachment/vision placeholder was
  promoted into the user-facing choice list.
- Candidate quality remains working-heavy (`working=127`, `event=1`) and
  `diversity_applied=false`, so RH-28g source diversity is not yet mature on
  the live data shape.
- This is a P1-G candidate-quality finding, not a SessionMirror coverage
  finding and not a boundary failure.

Next action:

- Add a generic topic-title eligibility / non-topic artifact suppression rule
  for low-clue candidates.
- Do not hardcode `n8n`, `Make`, image text, or any specific topic.
- Keep live behavior at `ask_choice`; do not add a direct-resume shortcut from
  this evidence.

#### RH-28 Follow-up: Topic Eligibility And Merged Source Preservation

Date: 2026-05-25.

Scope: small RH-28 candidate-quality fix. No live direct-resume change.

Changes validated:

- generic topic-title eligibility rejects attachment placeholders, tool/render
  snippets, and non-topic transcript artifacts before clustering;
- exact-label de-duplication now preserves merged `source_classes` and
  `source_ids` instead of keeping only the first source;
- candidate-quality metadata now reports:
  - `eligible_candidate_count`
  - `filtered_non_topic_title_count`
  - `primary_source_distribution`
  - `eligible_source_distribution`
  - `selected_source_distribution`

Local verification:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_low_clue_recall.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

51 passed
```

Remote validation on `10.20.3.200` after reinstall:

```text
command:
  hermes memory-os-agent-os low-clue-recall dry-run \
    --query '继续昨天那个' --llm-judge none

schema_version=memory-os.low_clue_recall.v0
query_class=ambiguous_recall
decision=ask_choice
candidate_count=4
boundaries.actual_send=false
boundaries.actual_execute=false
boundaries.actual_identity_write=false
boundaries.actual_crystallized_approval=false
candidate_quality.raw_candidate_count=128
candidate_quality.eligible_candidate_count=126
candidate_quality.filtered_non_topic_title_count=2
candidate_quality.cluster_count=41
candidate_quality.merged_duplicates=87
candidate_quality.title_normalization_applied=true
candidate_quality.diversity_applied=true
candidate_quality.primary_source_distribution={working:128}
candidate_quality.source_distribution={working:128,event:16}
candidate_quality.eligible_source_distribution={working:126,event:15}
candidate_quality.selected_source_distribution={working:4,event:4}
```

Observed candidate-quality result:

- the previous attachment placeholder candidate was removed from the shortlist;
- `ask_choice` remained in force;
- no direct-resume shortcut was added;
- the first candidate remained the intended internet-data-collection topic;
- event participation is now visible after exact-label de-duplication;
- `memory_sources` produced no eligible topic candidate in this run, so it did
  not participate in the selected shortlist.

Monitor after deployment:

```text
monitor_status=WARN
FAIL=[]
WARN=[rh31_eval_has_failures]
gateway=active
heartbeat_state_fresh=true
cognitive_loop_timer_active=true
index_health=healthy
doctor=ok
low_clue_ingress_matrix=all expected routes/headings matched
low_clue_recall.decision=ask_choice
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_findings=[]
```

Interpretation:

- This fixes the P1-G non-topic artifact and merged-source reporting defects.
- It does not claim candidate quality is fully mature: future work still needs
  real Telegram retest after gateway reload/restart if we want to verify the
  live long-running gateway process uses the updated module code.

#### RH-28 Follow-up: Telegram Button Title Compression

Date: 2026-05-25.

Reason: the 2026-05-25 Telegram retest showed that candidate labels were now
topic-like, but one label was still visually too long for Telegram choice
buttons. This follow-up keeps the same `ask_choice` behavior and only tightens
candidate title length.

Local verification:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_low_clue_recall.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

52 passed
```

Remote validation on `10.20.3.200` after reinstall:

```text
command:
  hermes memory-os-agent-os low-clue-recall dry-run \
    --query '继续昨天那个' --llm-judge none

decision=ask_choice
candidate_count=4
candidate_quality.max_title_chars=40
candidate_quality.filtered_non_topic_title_count=2
candidate_quality.diversity_applied=true
candidate_quality.source_distribution={working:128,event:16}
candidate_quality.selected_source_distribution={working:4,event:4}
boundaries.actual_send=false
boundaries.actual_execute=false
boundaries.actual_identity_write=false
boundaries.actual_crystallized_approval=false
```

Representative compressed candidates:

```text
1. 我们之前说的互联网数据采集系统，如果重新设计，你会怎么分层
2. rohitg00 / agentmemory / Memory-OS /...
3. Built-in / Hermes / skill / Voice / v...
4. 我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么
```

Monitor after deployment:

```text
monitor_status=WARN
FAIL=[]
WARN=[rh31_eval_has_failures]
gateway=active pid=488921
index_health=healthy
doctor=ok
low_clue_recall.decision=ask_choice
low_clue_recall.internal_label_count=0
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
```

Note: the gateway process was not restarted after this title-compression
deployment. CLI/shell dry-run uses the updated runtime immediately; Telegram
live verification requires a gateway reload/restart.

Post-gateway Telegram retest:

```text
2026-05-25 12:19 Asia/Shanghai
query:
  继续昨天那个

agent response:
  1. 互联网数据采集系统 重新设计分层
  2. rohitg00 / agentmemory / Memory-OS 相关
  3. Built-in / Hermes / skill / Voice 相关
  4. 记忆系统带来的变化 这条
```

Comparison with bounded dry-run after the same gateway reload:

```text
decision=ask_choice
candidate_count=4
candidate_quality.max_title_chars=40
candidate_quality.filtered_non_topic_title_count=2
candidate_quality.diversity_applied=true
candidate_quality.source_distribution={working:128,event:17}
candidate_quality.selected_source_distribution={working:4,event:4}
boundaries.actual_send=false
boundaries.actual_execute=false
boundaries.actual_identity_write=false
boundaries.actual_crystallized_approval=false
```

1h MemorySources attribution:

```text
record_count=3
route_distribution={ambiguous_recall:3}
selected_source_class_distribution={recall_guard:3}
boundary_true_count=0
forbidden_field_findings=[]
```

Monitor after retest:

```text
monitor_status=WARN
FAIL=[]
WARN=[index_not_healthy, doctor_warning_finding, rh31_eval_has_failures]
gateway=active pid=489403
low_clue_recall.decision=ask_choice
low_clue_recall.internal_label_count=0
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
compaction.focus_none_count=0
```

Interpretation:

- The long-running Telegram gateway loaded the RH-28 title-compression code
  after restart.
- The live response no longer exposes attachment placeholders, internal
  projection headings, or duplicate raw session-search variants.
- Live output is now a bounded `ask_choice` list with shorter topic labels.
- The remaining WARN items are unrelated to RH-28 candidate display:
  transient/stale index warning and the existing RH-31 eval warning.

#### RH-31 P1-B Candidate Boundary Attribution

Date: 2026-05-25.

Reason: the first RH-31 scorecard reported
`context_projection/candidate_boundary_001` as a projection miss. This needed
live comparison before adding any guard because scorecard warnings are
measurement signals until they map to a real behavior failure.

Remote no-write live projection probe on `10.20.3.200`:

```text
query:
  candidate 分数很高，是不是就自动变成长期记忆？

candidate_count=161
route=candidate_review
selected=[
  Current Foreground Task,
  Crystallized Review Candidates,
  Recent Event Summaries
]
dropped=[
  Conversation Carryover,
  Working Memory,
  Indexed Recall
]
boundary_true=false
```

Local RH-31 attribution after fixture/adapter correction:

```text
python -m pytest tests/eval/test_memory_os_eval_rh31.py -q
9 passed

python -m pytest \
  tests/eval/test_memory_os_eval_rh31.py \
  tests/scripts/test_memory_os_3_200_monitor.py \
  tests/plugins/memory/test_memory_os_prefetch.py -q
47 passed
```

Bounded scorecard after the fix:

```text
status=warning
score_count=27
failure_count=3
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1}
candidate_boundary_001/context_projection=pass
actual_route=candidate_review
actual_headings include Crystallized Review Candidates
boundary_true_count=0
forbidden_field_count=0
```

Remote RH-31 no-write scorecard after deploying the eval-only fix to
`10.20.3.200`:

```text
hermes memory-os-agent-os eval rh31 run --fixture synthetic \
  --adapter all --no-write-report

status=warning
score_count=27
failure_count=3
failure_class_distribution={"fts_miss": 2, "lexical_miss": 1}
candidate_boundary_001/context_projection=pass
actual_route=candidate_review
actual_headings include Crystallized Review Candidates
boundary_true_count=0
forbidden_field_count=0
```

Read-only monitor after deploy:

```text
host=debian
time=2026-05-25T04:36:45Z
monitor_status=WARN
PASS=[
  gateway_active,
  heartbeat_timer_active,
  heartbeat_state_fresh,
  cognitive_loop_timer_active,
  cognitive_loop_last_cycle_present,
  index_healthy,
  doctor_ok,
  status_tool_contract_ok,
  shell_alias_no_env_ok,
  module_artifact_summary_ok,
  rh31_eval_safety_ok,
  context_router_apply,
  memory_sources_stats_ok,
  low_clue_recall_probe_ok
]
WARN=[rh31_eval_has_failures]
FAIL=[]

RH31Eval.status=warning
RH31Eval.failure_count=3
RH31Eval.boundary_true_count=0
RH31Eval.forbidden_field_count=0
```

Interpretation:

- The deployed live projection path already handles candidate-boundary prompts
  as `candidate_review`.
- The RH-31 failure was caused by eval fixture/adapter drift:
  synthetic candidate corpus was not written to the candidate queue, the fixture
  wording triggered mechanism filtering, and the adapter inferred route from
  headings instead of the router report.
- No RH-31 live guard is justified for `candidate_boundary_001`.

## P1-I / P1-E Monitor Coverage Validation

Date:

```text
2026-05-25T04:54:15Z
```

Scope:

- P1-I Monitor Hook Coverage Detection
- P1-E Automatic Expression / Speak Gate would-send trend monitoring

Command:

```powershell
python scripts\memory_os_3_200_monitor.py `
  --host hermes-media `
  --previous-json C:\Users\btnal\.codex\automations\memory-os-3-200-monitor\last-snapshot.json `
  --output summary
```

Result:

```text
monitor_status=WARN
PASS includes:
  hook_coverage_session_activity_with_markers
  expression_artifact_summary_ok
  module_artifact_summary_ok
  memory_sources_stats_ok
  low_clue_recall_probe_ok
  rh31_eval_safety_ok
WARN=[rh31_eval_has_failures]
FAIL=[]
```

Hook coverage evidence:

```text
hook_markers:
  started=20
  reset=19
  finalized=22
  total=61

session_activity:
  total_session_events=160
  recent_session_events=160
  by_source={"telegram": 159, "cli": 1}
  by_kind={"conversation_turn": 143, "memory_write": 17}

delta vs previous automation snapshot:
  marker_delta={"started": 3, "reset": 4, "finalized": 5, "total": 12}
  session_delta={"total_session_events": 160}
```

Interpretation:

- The first run after adding `session_activity` uses a previous snapshot that
  did not yet contain that field, so `session_delta.total_session_events=160`
  is a baseline backfill signal, not a same-window session surge.
- Hook markers did grow during the same comparison window
  (`started +3`, `reset +4`, `finalized +5`), so this pass does not show the
  failure mode "session activity but hook marker silence."
- No hook was invoked or replayed by the monitor.

Expression artifact evidence:

```text
expression_artifacts.schema_version=memory-os.expression_artifact_summary.v0
wandering_output_count=11
wandering_would_send_count=11
wandering_silent_count=0
speak_gate_would_send_count=0
speak_gate_blocked_count=0
speak_gate_actual_send=false
```

Interpretation:

- Wandering Mind is producing bounded would-send artifacts.
- Speak Gate remains no-send: `actual_send=false`.
- The monitor now has enough read-only fields to trend automatic expression
  artifacts without enabling real sending.

Safety:

```text
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
DeepReflection.actual_send=false
DeepReflection.actual_execute=false
DeepReflection.actual_identity_write=false
DeepReflection.actual_crystallized_approval=false
crystallized_records=0
```

## RH-34 / RH-35 Owner Governance Discovery

Date:

```text
2026-05-25T07:26:00Z
```

Scope:

- RH-34 Daily Owner Review Digest
- RH-35 Owner Action Processor
- Contract 8 - OwnerAction

Reason:

The no-send cognitive loop is now producing artifacts that need owner review,
but daily review through SSH/CLI is not a sustainable product surface. This
check inspected whether the test host already has reviewable items and whether
an owner action/review queue surface exists.

Read-only commands:

```bash
ssh hermes-media 'HERMES_HOME=/root/.hermes hermes memory-os-agent-os status'
ssh hermes-media 'HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules status'
ssh hermes-media 'HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules doctor'
ssh hermes-media '<bounded Python filename/count inspection; no raw bodies printed>'
```

Live evidence:

```text
host=debian
time=2026-05-25T03:26:00-04:00

Memory-OS counts:
  events=229
  working_items=161
  crystallized_candidates=161
  crystallized_records=0
  audit_entries=2920
  queue_backlog=0
  index_health=healthy

proposal_queue:
  queue_path=/root/.hermes/system-modules/proposal_queue/queue.json
  candidate_count=15
  state_counts={"approved_for_proposal": 1, "candidate": 14}
  doctor_warning=pending_candidates_present

wandering_mind:
  would_send_count=11
  outputs.jsonl lines=11
  would_send.jsonl lines=11

speak_gate:
  would_send_count=0
  actual_send=false

DeepReflection:
  enabled=true
  injection_mode=auto_bounded
  analysis_artifact_count=18
  report_count=18
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false

owner/review ledgers:
  owner_actions ledger not present
  review_queue ledger not present
```

Interpretation:

- The system is not empty. It already has pending owner-review surfaces:
  crystallized candidates, proposal candidates, and right-brain would-send
  artifacts.
- Hard boundaries remain intact.
- The missing layer is not another cognition module. The missing layer is an
  owner governance workflow: bounded daily review digest plus idempotent owner
  action state transitions.
- CLI/module status is useful for operations but is too heavy as the normal
  owner review interface.

Decision:

- Add `34-owner-review-digest-and-action-workflow.md`.
- Add Contract 8 - OwnerAction to
  `29-memory-os-module-integration-contract.md`.
- Track the work in `32-active-roadmap-and-gates.md` as P1-M.
- Implement RH-35 OwnerActionProcessor before Telegram digest sending.

Pre-implementation review follow-up:

- Legitimate owner-approved crystallized writes must be counted as owner
  effects, not as historical hard-boundary violations.
- Unapproved crystallized write count must remain zero and must have a monitor
  field.
- Owner action idempotency must exclude digest ids so repeated appearances of
  the same candidate across digests cannot create duplicate approvals.
- Text replies must resolve through active digest anchors or stable target ids;
  ambiguous numeric replies must ask for clarification.
- Digest burden metrics must distinguish cold-start from active owner use.

Local RH-35.1 implementation evidence:

```text
Implemented locally:
  - plugins/memory/memory_os/owner_actions.py
  - hermes memory_os review status|queue|apply
  - hermes memory-os-agent-os review status|queue|apply
  - monitor OwnerReview summary/classification fields

Verification:
  python -m pytest tests\plugins\memory\test_memory_os_owner_actions.py \
    tests\system_modularization\test_memory_os_agent_os_shell.py \
    tests\scripts\test_memory_os_3_200_monitor.py -q
  -> 53 passed

  python -m py_compile plugins\memory\memory_os\owner_actions.py \
    plugins\memory\memory_os\cli.py \
    plugins\memory-os-agent-os\__init__.py \
    scripts\memory_os_3_200_monitor.py
  -> pass
```

Boundary interpretation:

- `approve_candidate` writes crystallized memory only as an explicit owner
  action and records `owner_effect.owner_approved_crystallized_write=true`.
- The historical hard boundary remains represented as
  `actual_unapproved_crystallized_approval=false`.
- Monitor separates `owner_approved_crystallized_write_count` from
  `unapproved_crystallized_write_count`; the latter is the failure signal.

Remote RH-35.1 smoke on `10.20.3.200`:

```text
Deployment:
  /root/Hermes-Memory-OS-rh35-20260525161920
  bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes
  -> installer copied owner_actions.py and updated shell alias.
  -> no hermes-gateway.service restart requested.

Shell alias smoke:
  hermes memory-os-agent-os review status
    schema_version=memory-os.owner_review_status.v0

  hermes memory-os-agent-os review queue --limit 3
    schema_version=memory-os.owner_review_queue.v0
    pending=186
    first_items=candidate:... , candidate:... , candidate:...

  hermes memory-os-agent-os review apply --action approve_candidate \
    --target candidate:<first_candidate> --owner smoke --channel cli
    status=ok
    dry_run=True

Monitor:
  OwnerReview={
    pending=186,
    action_required=175,
    stale=0,
    owner_actions=0,
    owner_approved_crystallized=0,
    unapproved_crystallized=0,
    owner_active_period=False
  }
  shell_alias_no_env.review_ok=True
  classification=WARN
  FAIL=[]
```

Conclusion:

- RH-35.1 is live on the test host as a no-send/no-execute owner action
  processor and review surface.
- The high pending/action-required counts confirm the original product gap:
  cognition modules were producing review-worthy artifacts faster than the
  owner could reasonably inspect through SSH/CLI alone.
- RH-34 digest generation/channel delivery remains the next gated slice and
  must stay opt-in.

## RH-34a Owner Review Channel Resolver + Digest Preview

Timestamp:

```text
2026-05-25T08:54:46Z
```

Scope:

- metadata-only owner review channel resolver;
- bounded digest preview;
- shell alias parity;
- monitor evidence for no-send/no-raw-body digest preview.

Deployment:

```text
/root/Hermes-Memory-OS-rh34a-20260525165415
bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes
-> installer copied owner_actions.py, config.py, CLI updates, and monitor-facing runtime.
-> no hermes-gateway.service restart requested.
```

Local verification:

```text
python -m pytest tests\plugins\memory\test_memory_os_owner_actions.py \
  tests\system_modularization\test_memory_os_agent_os_shell.py \
  tests\scripts\test_memory_os_3_200_monitor.py -q
-> 58 passed

python -m py_compile plugins\memory\memory_os\owner_actions.py \
  plugins\memory\memory_os\cli.py \
  plugins\memory-os-agent-os\__init__.py \
  scripts\memory_os_3_200_monitor.py
-> pass

python -m pytest -q
-> 472 passed
```

Remote shell alias smoke:

```text
hermes memory-os-agent-os review channel:
  schema_version=memory-os.owner_review_channel.v0
  status=dry_run_only
  reason=cli_preview_fallback
  raw_body_included=false

hermes memory-os-agent-os review preview-digest \
  --max-action-required 2 --max-review-suggested 2 --max-fyi 2:
  schema_version=memory-os.owner_review_digest_preview.v0
  will_send=false
  delivery_skipped=true
  actions_enabled=false
  raw_body_included=false
  action_required_total=175
  action_required_shown=2
  action_required_overflow=173
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false
```

Remote monitor:

```text
classification=WARN
FAIL=[]

OwnerReview:
  pending=186
  action_required=175
  owner_actions=0
  owner_approved_crystallized=0
  unapproved_crystallized=0

OwnerReviewChannel:
  status=dry_run_only
  reason=cli_preview_fallback
  channel=cli
  configured_by_owner=false
  fallback_used=true
  candidate_count=0
  raw_body_included=false

OwnerDigestPreview:
  status=ok
  will_send=false
  actions_enabled=false
  raw_body_included=false
  action_required_total=175
  action_required_shown=3
  action_required_overflow=172

PASS includes:
  owner_review_status_ok
  owner_review_channel_resolver_ok
  owner_review_digest_preview_ok
  shell_alias_no_env_ok

WARN:
  session_mirror_pending_sessions
  rh31_eval_has_failures
```

Boundary interpretation:

- RH-34a does not send a digest.
- RH-34a does not enable Telegram delivery.
- RH-34a does not parse `session_*.json` files because those may contain
  private message bodies; it uses explicit owner config or metadata-only
  `state.db` session rows, otherwise CLI preview fallback.
- Digest preview is a review surface only; it does not approve, reject,
  execute, write crystallized memory, or create owner action records.

Conclusion:

- RH-34a is live on the test host as metadata-only channel resolution and
  bounded digest preview.
- The next gated slice is opt-in owner-channel delivery. Delivery must not be
  enabled until an owner-configured channel is present and monitor continues to
  show no raw bodies and no unintended send/action boundaries.

## RH-34b Explicit Opt-In Delivery Gate

Timestamp:

```text
2026-05-25T09:05:07Z
```

Scope:

- explicit opt-in delivery gate;
- no channel adapter;
- no Telegram send;
- monitor evidence for the pre-send decision surface.

Deployment:

```text
/root/Hermes-Memory-OS-rh34b-20260525170441
bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes
-> installer copied owner_actions.py, config.py, CLI updates, and monitor-facing runtime.
-> no hermes-gateway.service restart requested.
```

Local verification:

```text
python -m pytest tests\plugins\memory\test_memory_os_owner_actions.py \
  tests\system_modularization\test_memory_os_agent_os_shell.py \
  tests\scripts\test_memory_os_3_200_monitor.py -q
-> 61 passed

python -m py_compile plugins\memory\memory_os\owner_actions.py \
  plugins\memory\memory_os\cli.py \
  plugins\memory-os-agent-os\__init__.py \
  scripts\memory_os_3_200_monitor.py
-> pass

python -m pytest -q
-> 475 passed
```

Remote shell alias smoke:

```text
hermes memory-os-agent-os review delivery-gate:
  schema_version=memory-os.owner_review_delivery_gate.v0
  status=disabled
  ready_for_delivery=false
  delivery_enabled=false
  delivery_adapter=none
  blocked_reasons=[
    delivery_not_enabled,
    delivery_adapter_not_configured,
    review_channel_not_selected,
    review_channel_not_configured_by_owner
  ]
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false
```

Remote monitor:

```text
classification=WARN
FAIL=[]

OwnerDeliveryGate:
  status=disabled
  ready_for_delivery=false
  delivery_enabled=false
  delivery_adapter=none
  blocked_reasons=[
    delivery_not_enabled,
    delivery_adapter_not_configured,
    review_channel_not_selected,
    review_channel_not_configured_by_owner
  ]
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false

PASS includes:
  owner_review_delivery_gate_ok
```

Boundary interpretation:

- RH-34b is a pre-send decision gate, not a delivery adapter.
- It does not send Telegram or any other owner-channel message.
- It does not create owner action records.
- It cannot become ready unless delivery is explicitly enabled, a delivery
  adapter is configured, and the channel resolver selects an owner-configured
  channel.

Review gate:

- Claude/external review is required before enabling any live owner-channel
  delivery adapter or setting test-host config into a send-capable path.
- Disabled-by-default gate code, tests, and monitor fields do not require
  external review to remain deployed because all send/execution/write
  boundaries stay false.

Conclusion:

- RH-34b is live on the test host as a disabled-by-default opt-in delivery
  gate.
- The next slice, if pursued, must be a reviewed channel adapter / delivery
  apply gate, not another preview-only monitor field.

## RH-34c Review Queue Aging Policy

Timestamp:

```text
2026-05-25T09:32:45Z
```

Scope:

- review queue aging projection;
- shell alias parity through `hermes memory-os-agent-os review aging-report`;
- monitor evidence for raw/effective owner-review burden;
- no send, no approval, no rejection, no crystallized write, no canonical
  mutation.

Deployment:

```text
bundle=/root/Hermes-Memory-OS-rh34c-20260525173213
command=bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes
gateway_restart=not performed
```

Local verification:

```text
python -m pytest -q
-> 477 passed

git diff --check
-> pass
```

Live smoke:

```text
owner_review_aging.schema_version=memory-os.owner_review_aging.v0
owner_review_aging.enabled=true
raw_action_required=175
effective_action_required=14
aged_to_review_suggested=161
aged_to_fyi=0
unknown_timestamp=161
raw_body_included=false
canonical_state_changed=false
owner_action_created=false

owner_review.pending=186
owner_review.action_required=14
owner_review.review_suggested=172

owner_digest_preview:
  pending=186
  raw_action_required_total=175
  action_required_total=14
  action_required_shown=3
  action_required_overflow=11
  will_send=false
  raw_body_included=false

owner_delivery_gate:
  status=disabled
  ready_for_delivery=false
  actual_send=false
```

Monitor result:

```text
status=WARN
PASS includes:
  owner_review_status_ok
  owner_review_aging_ok
  owner_review_channel_resolver_ok
  owner_review_digest_preview_ok
  owner_review_delivery_gate_ok
FAIL=[]
WARN=[
  session_mirror_pending_sessions,
  rh31_eval_has_failures
]
```

Boundary interpretation:

- RH-34c is projection-only. It changes `effective_priority` for review queue
  and digest display, while preserving `source_priority` and raw backlog
  counts.
- It did not create owner action records, did not mutate candidates/proposals,
  did not approve/reject/crystallize, and did not send a digest.
- The immediate owner burden is much lower than RH-34a/RH-34b
  (`effective_action_required=14` versus raw `175`), but still above the
  steady-state target of `<=3`.

Conclusion:

- RH-34c is live on the test host and satisfies the projection-only boundary.
- At this checkpoint, RH-34d one-shot real-send smoke still needed external
  review before crossing into actual owner-channel delivery. The later RH-34d
  section records the one-shot smoke evidence.

## RH-34d One-Shot Real Send Smoke

Timestamp:

```text
2026-05-25T09:57:22Z
```

Scope:

- one owner-triggered digest delivery smoke;
- delivery ledger and delivery status monitor fields;
- no recurring delivery;
- no owner action application;
- no proposal execution;
- no candidate approval/rejection;
- no crystallized memory write;
- raw-body-free bounded digest text.

Deployment:

```text
bundle=/root/Hermes-Memory-OS-rh34d-20260525055605
command=bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes
gateway_restart=not performed
```

Local verification:

```text
python -m pytest -q tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py \
  tests/scripts/test_memory_os_3_200_monitor.py
-> 65 passed

python -m pytest -q
-> 479 passed
```

One-shot smoke:

```text
delivery_key=rh34d-smoke-20260525T095719Z
gate_status=ready
gate_ready=true
gate_blocked_reasons=[]
result_status=sent
result_dry_run=false

record.schema_version=memory-os.owner_review_delivery.v0
record.delivery_id=odel_20260525T095722076292Z_b8f57721
record.digest_id=odig_20260525T095722076178Z_5f4487c4
record.result=sent
record.raw_body_included=false
record.text_char_count=742
record.boundary.actual_unapproved_send=false
record.boundary.actual_execute=false
record.boundary.actual_identity_write=false
record.boundary.actual_unapproved_crystallized_approval=false
record.owner_effect.owner_approved_digest_delivery=true

delivery_status.delivery_count=1
delivery_status.sent_count=1
delivery_status.error_count=0
delivery_status.duplicate_ignored_count=0
delivery_status.owner_approved_digest_delivery_count=1
delivery_status.unapproved_send_count=0
delivery_status.raw_body_included_count=0
```

The smoke temporarily enabled `owner_review.delivery_enabled=true` and
`delivery_adapter=hermes_owner_channel` with the configured owner channel, sent
one bounded digest through Hermes' existing send-message path, then restored
the prior `owner_review` delivery config. The target channel id is intentionally
not recorded here.

Post-smoke config check:

```text
owner_review.channel=null
owner_review.delivery_adapter=null
owner_review.delivery_enabled=null
owner_review.direct_message=null
owner_review.enabled=null
owner_review.mode=null
owner_review.target_ref=null
```

Post-smoke monitor:

```text
status=WARN
FAIL=[]

OwnerDeliveryStatus:
  delivery_count=1
  sent_count=1
  skipped_count=0
  error_count=0
  duplicate_ignored_count=0
  owner_approved_digest_delivery=1
  unapproved_send=0
  raw_body_included=0
  last_result=sent
  last_delivery_id=odel_20260525T095722076292Z_b8f57721

OwnerDeliveryGate:
  status=disabled
  ready_for_delivery=false
  delivery_enabled=false
  delivery_adapter=none
  blocked_reasons=[
    delivery_not_enabled,
    delivery_adapter_not_configured,
    review_channel_not_selected,
    review_channel_not_configured_by_owner
  ]
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false

PASS includes:
  owner_review_delivery_status_ok
  owner_review_delivery_gate_ok

WARN=[
  session_mirror_pending_sessions,
  rh31_eval_has_failures
]
```

Boundary interpretation:

- RH-34d proves the selected owner channel can receive exactly one bounded
  owner-approved digest.
- The send is recorded as `owner_approved_digest_delivery`, not as an
  unapproved-send boundary violation.
- No raw private body was included.
- No owner action, proposal execution, candidate approval/rejection, or
  crystallized write occurred as a side effect of delivery.
- Delivery config was restored to disabled after the smoke.

Conclusion:

- RH-34d live one-shot smoke passed on `10.20.3.200`.
- RH-34d is now treated as Hermes send compatibility evidence only. It proved
  that Hermes can deliver one bounded Memory-OS digest, but it does not make
  Memory-OS responsible for recurring scheduling or transport.
- RH-34e recurring daily review remains blocked and must be redesigned as
  Hermes Cron Owner Review Integration: Memory-OS renders bounded review
  payloads and action anchors, while Hermes owns cron delivery and platform
  send gates.
- Before RH-34e, the digest renderer must stop exposing internal schema labels
  such as `kind=moment` as primary owner-facing text, and owner replies must map
  through OwnerActionProcessor.

## RH-34e.1 / RH-35.2 Renderer, Recorded Digest Binding, And Smoke-Only Correction

Date: 2026-05-25

Mode: test-host installer deployment; installed shell alias smoke; read-only
monitor after deployment. No gateway restart was performed by the installer.

Scope:

- RH-34e.1 Review Digest Renderer
- RH-35.2 Owner Reply Parser
- RH-34d `deliver-once` legacy smoke-only correction
- Contract 8 OwnerAction / Hermes transport boundary

Local verification:

```text
python -m pytest -q tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py \
  tests/scripts/test_memory_os_3_200_monitor.py
70 passed

python -m pytest -q
484 passed
```

Remote deployment:

```text
HERMES_HOME=/root/.hermes bash /tmp/memory-os-rh34e-rh35-binding/scripts/install_memory_os.sh --yes --test-host
provider=memory_os
shell_plugin=memory-os-agent-os enabled
heartbeat_timer=active/enabled
cognitive_loop_timer=active/enabled
doctor=ok with expected hindsight_adapter_disabled warning
```

Remote renderer smoke:

```text
command:
  hermes memory-os-agent-os review render-digest \
    --format json --record-active --owner owner --channel telegram \
    --max-action-required 2 --max-review-suggested 2 --max-fyi 2

schema=memory-os.owner_review_rendered_digest.v0
status=ok
recorded_active_digest=true
text_has_candidate_schema=false
candidate_has_proposed_memory=true
raw_body_included=false
will_send=false
```

Remote owner-reply binding smoke:

```text
command:
  hermes memory-os-agent-os review reply approve A1 \
    --owner owner --channel telegram --digest-id <recorded_digest_id>

status=ok
binding=recorded_digest
dry_run=true
parsed_action=approve_proposal

command:
  hermes memory-os-agent-os review reply approve A1 \
    --owner owner --channel telegram

status=ok
binding=latest_recorded_digest
dry_run=true

owner_action_count remained 0 after dry-run smoke.
```

Remote legacy deliver-once smoke-only check:

```text
command:
  hermes memory-os-agent-os review deliver-once \
    --owner owner --delivery-key rh34e-smoke-only-20260525T1141Z \
    --owner-triggered --apply

status=skipped
record_result=skipped
blocked_reasons=delivery_not_enabled,delivery_adapter_not_configured,
  review_channel_not_selected,review_channel_not_configured_by_owner
unapproved_send=false
owner_approved_delivery=false

delivery_status.sent_count=1        # historical RH-34d smoke only
delivery_status.skipped_count=2
delivery_status.unapproved_send_count=0
delivery_status.raw_body_included_count=0
```

Read-only monitor after deployment:

```text
classification=WARN
FAIL=[]
PASS includes:
  owner_review_rendered_digest_ok
  owner_review_reply_dry_run_ok
  owner_review_delivery_status_ok
  owner_review_delivery_gate_ok
WARN:
  session_mirror_pending_sessions
  rh31_eval_has_failures
OwnerRenderedDigest:
  status=ok
  will_send=false
  raw_body_included=false
  text_has_internal_schema=false
  section_counts={action_required:2, review_suggested:2, fyi:2}
OwnerReplyDryRun:
  status=ok
  dry_run=true
  owner_action_dry_run=true
OwnerDeliveryGate:
  status=disabled
  delivery_enabled=false
  boundary.actual_send=false
OwnerDeliveryStatus:
  sent_count=1
  skipped_count=2
  unapproved_send=0
  raw_body_included=0
```

Interpretation:

- Candidate review cards now include bounded proposed-memory text, so owner
  approval is actionable without exposing raw source bodies as primary text.
- Owner replies bind to a recorded digest snapshot when available, so anchors
  are not silently reinterpreted after the queue changes.
- `deliver-once` is no longer a Memory-OS transport path for RH-34e. Recurring
  owner review must be implemented by Hermes cron/send with Memory-OS providing
  only bounded renderer output and owner-action parsing.
- No owner action, proposal execution, crystallized write, identity write, or
  unapproved send occurred during this validation.

## RH-34e Hermes Cron Owner Review Integration Helper

Date: 2026-05-25

Scope:

- RH-34e Hermes Cron Owner Review Integration;
- Contract 8 OwnerAction / Hermes transport boundary;
- installer and monitor evidence for the recurring-review helper path.

Boundary decision:

- Memory-OS does not own recurring scheduling or platform transport.
- Hermes cron owns scheduling and delivery.
- The `10.20.3.200` Hermes CLI exposes `hermes cron create --script
  --no-agent --deliver`; it does not expose a standalone `hermes send`
  command. RH-34e therefore uses the cron script/deliver seam rather than
  depending on `hermes send`.

Local verification:

```text
python -m pytest -q tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/scripts/test_memory_os_plugin_install.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py \
  tests/scripts/test_memory_os_3_200_monitor.py
102 passed

bash -n scripts/install_memory_os.sh

python scripts/install_memory_os_plugin.py \
  --hermes-home .tmp-install-rh34e \
  --install-owner-review-cron-helper \
  --dry-run
```

Remote deployment:

```text
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh \
  --yes --test-host --install-owner-review-cron-helper

helper installed:
  /root/.hermes/scripts/memory_os_owner_review_digest.py

gateway restart: not requested / not performed
heartbeat timer: active/enabled
cognitive loop timer: active/enabled
doctor: ok with expected hindsight_adapter_disabled warning
```

Remote RH-34e smoke:

```text
hermes memory-os-agent-os review cron-status:
  schema_version=memory-os.owner_review_cron_integration.v0
  status=ok
  enabled=false
  job_present=false
  helper_script_present=true
  hermes_delivery_configured=false
  raw_body_included_count=0
  unapproved_send_count=0

python3 /root/.hermes/scripts/memory_os_owner_review_digest.py:
  helper_output_chars=3501
  helper_has_internal_schema=false
  helper_has_raw_marker=false
  rendered_count_24h_after=2
```

Read-only monitor after deployment:

```text
classification=WARN
FAIL=[]
PASS includes:
  owner_review_cron_integration_status_ok
  owner_review_rendered_digest_ok
  owner_review_reply_dry_run_ok
  owner_review_delivery_status_ok
  owner_review_delivery_gate_ok

OwnerCronIntegration:
  status=ok
  enabled=false
  job_present=false
  job_enabled=false
  helper_script_present=true
  delivery_configured=false
  delivery_target_class=missing
  rendered_count_24h=2
  raw_body_included=0
```

Interpretation:

- RH-34e now has an installed helper and monitorable status path on
  `10.20.3.200`.
- The helper produces bounded digest text for Hermes cron stdout delivery and
  records active digest binding through the existing renderer path.
- At this helper/status checkpoint, no cron job was present or enabled yet;
  the later default test-host enable gate below supersedes this disabled state.
- No raw private body, internal schema-primary text, unapproved send, owner
  action, proposal execution, crystallized write, or identity write occurred.

Next gate:

- External/design review can inspect the RH-34e helper/status evidence.
- The next state-changing step is explicit owner/operator opt-in to create or
  enable a Hermes cron job with `--script --no-agent --deliver`.

## RH-34e Recurring Enable Gate Dry-Run

Date: 2026-05-25

Scope:

- explicit owner/operator gate for recurring owner review delivery;
- no-write validation of Hermes cron compatibility and bounded renderer output.

Local verification:

```text
python -m pytest -q tests/scripts/test_memory_os_owner_review_cron_gate.py \
  tests/scripts/test_memory_os_plugin_install.py
36 passed

python -m pytest -q tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/scripts/test_memory_os_plugin_install.py \
  tests/scripts/test_memory_os_owner_review_cron_gate.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py \
  tests/scripts/test_memory_os_3_200_monitor.py
107 passed

bash -n scripts/install_memory_os.sh
```

Remote deployment:

```text
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh \
  --yes --test-host --install-owner-review-cron-helper

installed:
  /root/.hermes/scripts/memory_os_owner_review_digest.py
  /root/.hermes/scripts/memory_os_owner_review_cron_gate.py
```

Remote no-write gate dry-run:

```text
command:
  python3 /root/.hermes/scripts/memory_os_owner_review_cron_gate.py \
    --hermes-home /root/.hermes \
    --schedule '0 9 * * *' \
    --deliver telegram

schema_version=memory-os.owner_review_cron_enable_gate.v0
status=dry_run
apply_requested=false
config_updated=false
helper_script_present=true
hermes_cron_create_available=true
hermes_cron_supports_script_no_agent_deliver=true
existing_job_present=false
deliver_target_class=platform_home
render_check.ok=true
render_check.text_char_count=3501
render_check.raw_body_included=false
render_check.internal_schema_primary=false
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_unapproved_crystallized_approval=false
```

Read-only monitor after gate dry-run:

```text
classification=WARN
FAIL=[]
PASS includes:
  owner_review_cron_integration_status_ok
OwnerCronIntegration:
  status=ok
  enabled=false
  job_present=false
  job_enabled=false
  helper_script_present=true
  delivery_configured=false
  raw_body_included=0
```

Interpretation:

- The recurring enable gate can validate the chosen schedule and Hermes
  delivery class without creating a cron job or writing Memory-OS recurring
  config.
- The gate redacts raw delivery target values in its normal report.
- Apply remains blocked unless the operator supplies `--apply
  --owner-approved`; `deliver=local`, missing helper, missing Hermes cron
  support, duplicate jobs, or unsafe renderer output stop the gate.
- No send, owner action, proposal execution, crystallized write, or identity
  write occurred during this validation.

## RH-34e Default Test-Host Recurring Enable And Hermes Cron Run

Date: 2026-05-25

Scope:

- default test-host deployment of the Hermes cron owner-review digest;
- actual Hermes cron run through `--script --no-agent --deliver`;
- monitor evidence for bounded output and transport ownership.

Local verification:

```text
bash -n scripts/install_memory_os.sh

python -m pytest -q tests/scripts/test_memory_os_owner_review_cron_gate.py \
  tests/scripts/test_memory_os_plugin_install.py
36 passed
```

Remote deployment:

```text
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host

owner review cron gate:
  schema_version=memory-os.owner_review_cron_enable_gate.v0
  status=applied
  job_id=2af755464ca8
  job_name=memory-os-owner-review-digest
  schedule=0 9 * * *
  deliver_target_class=platform_home
  config_updated=true
  render_check.ok=true
  render_check.text_char_count=3501
  render_check.raw_body_included=false
  render_check.internal_schema_primary=false
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false
```

Remote status:

```text
hermes memory-os-agent-os review cron-status:
  schema_version=memory-os.owner_review_cron_integration.v0
  status=ok
  enabled=true
  job_present=true
  job_enabled=true
  job_id=2af755464ca8
  helper_script_present=true
  hermes_delivery_configured=true
  hermes_delivery_target_class=platform_home
  raw_body_included_count=0
  unapproved_send_count=0

hermes cron list --all:
  id=2af755464ca8
  name=memory-os-owner-review-digest
  active=true
  schedule=0 9 * * *
  deliver=telegram
  script=memory_os_owner_review_digest.py
  mode=no-agent
```

Actual Hermes cron run smoke:

```text
hermes cron run --accept-hooks 2af755464ca8
hermes cron tick --accept-hooks

hermes cron list --all after tick:
  last_run=2026-05-25T08:47:39.776368-04:00 ok

cron output:
  path=/root/.hermes/cron/output/2af755464ca8/2026-05-25_08-47-38.md
  output_chars=3637
  output_has_internal_schema=false
  output_has_raw_marker=false
  first_line="# Cron Job: memory-os-owner-review-digest"
```

Read-only monitor after cron run:

```text
classification=WARN
FAIL=[]
PASS includes:
  owner_review_cron_integration_status_ok

OwnerCronIntegration:
  status=ok
  enabled=true
  job_present=true
  job_enabled=true
  helper_script_present=true
  delivery_configured=true
  delivery_target_class=platform_home
  rendered_count_24h=3
  raw_body_included=0
  unapproved_send_count=0

Expected WARN still present:
  session_mirror_pending_sessions
  rh31_eval_has_failures
```

Interpretation:

- The default `--test-host` install now enables the owner review digest through
  Hermes cron and does not create a Memory-OS-owned transport path.
- Hermes owns the schedule and platform delivery (`deliver=telegram`,
  `mode=no-agent`); Memory-OS only renders bounded digest text and action
  anchors.
- The actual cron run produced one bounded output artifact with no raw-body or
  internal-schema-primary evidence.
- Memory-OS hard boundaries stayed false; `unapproved_send_count=0`.
- Final owner-facing validation still requires the owner to confirm the
  Telegram-delivered message is readable and useful before using reply actions
  such as `approve A1` or `reject R1`.

## RH-34f / RH-34g / RH-36 Follow-Up Validation

Date: 2026-05-25

Scope:

- owner home channel autodiscovery default (`auto` -> `origin`, test-host ->
  `telegram`);
- owner review renderer budget and candidate quality;
- module closure matrix documentation for left/right brain, governance,
  feedback, scheduler, monitor, and Hermes transport seams.

Local verification:

```text
python -m pytest -q tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/scripts/test_memory_os_owner_review_cron_gate.py \
  tests/scripts/test_memory_os_3_200_monitor.py \
  tests/scripts/test_memory_os_plugin_install.py
94 passed

bash -n scripts/install_memory_os.sh
git diff --check
```

Installer dry-run evidence:

```text
normal non-interactive:
  OWNER_REVIEW_CRON_DELIVER=auto
  resolved target=origin

controlled --test-host:
  OWNER_REVIEW_CRON_DELIVER=auto
  resolved target=telegram
```

Remote deployment:

```text
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host --skip-verify

owner review cron gate:
  schema_version=memory-os.owner_review_cron_enable_gate.v0
  status=already_configured
  job_id=2af755464ca8
  job_name=memory-os-owner-review-digest
  schedule=0 9 * * *
  deliver_target_class=platform_home
  render_check.text_char_count=2231
  render_check.raw_body_included=false
  render_check.internal_schema_primary=false
  config_updated=true
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false
```

Remote digest preview quality:

```text
helper_preview:
  chars=2231
  line_count=33
  has_bad_marker=false
  action_items=3
  review_items=2
  fyi_items=0
  ends_partial_owner=false
```

Actual Hermes cron run smoke:

```text
hermes cron run --accept-hooks 2af755464ca8
hermes cron tick --accept-hooks

hermes cron list --all:
  job=2af755464ca8
  name=memory-os-owner-review-digest
  active=true
  deliver=telegram
  script=memory_os_owner_review_digest.py
  mode=no-agent
  last_run=2026-05-25T09:37:08.950764-04:00 ok

latest cron output:
  path=/root/.hermes/cron/output/2af755464ca8/2026-05-25_09-37-04.md
  chars=2367
  has_bad_marker=false
  action_items=3
  review_items=2
  fyi_items=0
  ends_partial_owner=false
```

Read-only monitor after RH-34g cron run:

```text
classification=WARN
FAIL=[]
PASS includes:
  owner_review_cron_integration_status_ok
  owner_review_rendered_digest_ok
  owner_review_reply_dry_run_ok

OwnerRenderedDigest:
  status=ok
  text_char_count=2289
  text_has_internal_schema=false
  text_has_transcript_marker=false
  section_counts={action_required:2, review_suggested:2, fyi:2}

OwnerCronIntegration:
  status=ok
  enabled=true
  job_present=true
  job_enabled=true
  delivery_configured=true
  delivery_target_class=platform_home
  rendered_count_24h=6
  raw_body_included=0

Expected WARN still present:
  session_mirror_pending_sessions
  rh31_eval_has_failures
```

Interpretation:

- The installer no longer hardcodes Telegram for ordinary open-source installs:
  the default `auto` target resolves to Hermes cron `origin` outside
  `--test-host`, while `10.20.3.200` still resolves to `telegram` as the
  controlled validation host.
- RH-34g fixed the owner-visible digest shape enough to resume review testing:
  rendered text stays below the 2400-character channel budget, omits whole
  items instead of truncating them, and keeps transcript-like candidates out of
  the approvable memory path.
- RH-36 records the module closure matrix so future left/right brain,
  governance, feedback, and scheduler modules declare whether they write owner
  actions, propose memory, request execution, request speech, or only feed
  monitor/context loops.
- Next state-changing gate remains owner reply E2E: use a delivered digest
  anchor such as `reject R1` or `approve A1`, verify OwnerActionProcessor state
  change, and keep all send/execute/identity/unapproved-crystallized
  boundaries false.

## 2026-05-25 - RH-35.3 Owner Reply Ingress Finding And Fix

Live Telegram finding:

```text
Owner replied to the digest with: reject R1
Observed assistant response:
  Got it — not R1.
  Which one should we continue with: R2, R3, or R4?
```

Diagnosis:

```text
Owner Reply Parser existed through CLI:
  hermes memory-os-agent-os review reply reject R1 --channel telegram
  -> status=ok
  -> parsed.action_type=reject_candidate
  -> target_id=cand_evt_20260520T023001000000Z_0000002329

But live Telegram ingress did not call the parser:
  owner_review.owner_action_count remained 0 after the Telegram reply
  the message fell through to ordinary chat / recall behavior
```

Corrected state for the owner-intended action:

```text
hermes memory-os-agent-os review reply reject R1 --apply
  status=ok
  owner_action_result.status=ok
  result_ref.state=owner_rejected
  action_type=reject_candidate
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false
```

Code fix deployed:

```text
MemoryOSProvider.on_turn_start
  exact command detector:
    approve A1
    reject R1
    allow A1
    feedback F1 too_mechanistic
  -> parse_owner_review_reply(..., apply=true, require_recorded_digest=true)
  -> OwnerActionProcessor
  -> one-turn prefetch/system-prompt confirmation block
```

Safety rule:

```text
Live ingress requires a recorded digest for the owner/platform channel.
It must not render a fresh digest and bind a stale owner reply to shifted
anchors.
```

Local verification:

```text
python -m pytest -q tests/plugins/memory/test_memory_os_owner_actions.py
  25 passed

python -m pytest -q \
  tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/plugins/memory/test_memory_os_lifecycle.py \
  tests/scripts/test_memory_os_3_200_monitor.py \
  tests/scripts/test_memory_os_owner_review_cron_gate.py
  77 passed

git diff --check
  pass
```

Remote install and restart:

```text
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host --skip-verify
  copied_file_count=36
  owner_review_cron_gate.status=already_configured
  render_check.text_char_count=2100
  render_check.raw_body_included=false

systemctl --user restart hermes-gateway.service
  ActiveState=active
  SubState=running
  ExecMainPID=496082
```

Remote provider smoke:

```text
PYTHONPATH=/root/.hermes/memory-os/runtime/python python3 ...
  context_has_owner_reply=True
  prompt_has_reject=True
  actions_exists=True
```

Read-only monitor after restart:

```text
classification=WARN
FAIL=[]

OwnerReview:
  pending=188
  action_required=15
  owner_actions=1
  by_type={reject_candidate:1}
  owner_approved_crystallized=0
  unapproved_crystallized=0
  owner_active_period=true

OwnerReplyDryRun:
  status=ok
  dry_run=true
  parsed_action_type=approve_proposal
  owner_action_status=ok

OwnerCronIntegration:
  status=ok
  enabled=true
  job_present=true
  job_enabled=true
  raw_body_included=0

Expected WARN still present:
  session_mirror_pending_sessions
  rh31_eval_has_failures
```

Interpretation:

- RH-35.2 parser was correct, but RH-35.3 live ingress was missing.
- The fix keeps the boundary inside the MemoryProvider plugin; Hermes still
  owns delivery and platform transport.
- The owner-intended `reject R1` action is now represented in
  OwnerActionProcessor state, and the next live Telegram retest should confirm
  instead of continuing ordinary recall/chat.

## 2026-05-25 - RH-35.5 Stable Owner Action Tokens

Scope:

- Correct the owner review action model after comparing against the
  `10.20.2.88` Sannai/CW-019 owner-review prototype.
- Stop treating display anchors (`A1/R1/F1`) as durable approval identity.
- Keep Hermes cron/send as the delivery owner; Memory-OS renders bounded
  digest text and processes explicit owner action commands only.

Reference prototype finding:

```text
10.20.2.88 Sannai owner review:
  - digest/report is delivered by Hermes cron with deliver=origin
  - candidate review uses stable candidate IDs
  - weekly consolidation apply requires --proposal-hash
  - display order is not used as the approval authority
```

Implementation change:

```text
render_owner_review_digest()
  -> displays [A1]/[R1] as readable anchors only
  -> emits stable commands:
       memory approve oa_<token>
       memory reject oa_<token>
       memory allow oa_<token>
       memory feedback oa_<token> <rating>

parse_owner_review_reply()
  -> resolves oa_<token> against recorded digest action_tokens
  -> maps to target_type + target_id + action_type
  -> calls OwnerActionProcessor only

MemoryOSProvider live ingress
  -> intercepts only explicit prefixed token commands
  -> no longer treats approve A1 / reject R1 as live state-changing input
```

Local verification:

```text
python -m pytest -q \
  tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/scripts/test_memory_os_3_200_monitor.py \
  tests/scripts/test_memory_os_owner_review_digest_helper.py \
  tests/scripts/test_memory_os_owner_review_cron_gate.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py

90 passed
```

Remote deployment:

```text
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host --skip-verify
  copied_file_count=36
  owner_review_cron_gate.status=already_configured
  render_check.text_char_count=2359
  render_check.raw_body_included=false

systemctl --user restart hermes-gateway.service
  ActiveState=active
  SubState=running
  MainPID=498070
```

Remote smoke evidence:

```text
PYTHONPATH=/root/.hermes/memory-os/runtime/python \
  python3 /root/.hermes/scripts/memory_os_owner_review_digest.py

Output includes:
  Action: memory approve oa_40b674ced068f7 / memory reject oa_9b53f82a9ab231
  Ref: proposal:prop_20260521T032500041194Z_2f96a933aa

summary:
  chars=2359
  command_count=8
  has_token=true
  has_legacy_approve_anchor=false
```

Dry-run parser evidence:

```text
hermes memory-os-agent-os review reply memory approve oa_40b674ced068f7 --channel telegram

status=ok
dry_run=true
active_digest.binding=latest_recorded_digest
active_digest.delivery_scope=owner_home
parsed.action_type=approve_proposal
parsed.target_type=proposal
parsed.target_id=prop_20260521T032500041194Z_2f96a933aa
owner_action_status=ok
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_unapproved_crystallized_approval=false
```

Legacy-anchor safety smoke:

```text
provider.on_turn_start("approve A2")
owner_action_count before=1
owner_action_count after=1
mutated=false
```

Real owner action smoke:

```text
Selected delivered-digest item:
  anchor=A2
  question=Tune ordinary memory conversation tone
  command=memory approve oa_df197efe059ae9
  target=proposal:prop_20260521T093627745201Z_aa81f796ec

hermes memory-os-agent-os review reply memory approve oa_df197efe059ae9 \
  --channel telegram --apply

result:
  status=ok
  dry_run=false
  parsed.action_type=approve_proposal
  parsed.target_type=proposal
  parsed.target_id=prop_20260521T093627745201Z_aa81f796ec
  owner_action_status=ok
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false

post-status:
  owner_action_count=2
  action_type_counts={reject_candidate:1, approve_proposal:1}
  proposal_approved_count=1
  proposal_rejected_count=0
  owner_approved_crystallized_write_count=0
  unapproved_crystallized_write_count=0
  cron_integration.raw_body_included_count=0
  cron_integration.unapproved_send_count=0
```

Interpretation:

- This was a real OwnerActionProcessor state transition, not a dry-run.
- Proposal approval created follow-up state only:
  `result_ref.state=approved_for_proposal`.
- No execution, send, identity write, or crystallized-memory write happened.

Conclusion:

- RH-35.4 channel-binding patch alone was not enough; it still relied on weak
  display anchors.
- RH-35.5 aligns Memory-OS owner actions with the safer 10.20.2.88 pattern:
  stable target identity first, readable digest anchors second.
- Next live owner action smoke must use the rendered stable command, not
  `approve A2`.

## 2026-05-25 - RH-35.5 Monitor Evidence After Token-Only Guard

Scope:

- read-only monitor run after the real `memory approve oa_<token>` proposal
  approval smoke;
- monitor updated to expose owner-review ingress guard status;
- no service restart, heartbeat trigger, cleanup, shadow ingest, raw event
  summary print, or private body read.

Command:

```text
python scripts/memory_os_3_200_monitor.py \
  --host hermes-media \
  --previous-json C:\Users\btnal\.codex\automations\memory-os-3-200-monitor\last-snapshot.json \
  --snapshot-out C:\Users\btnal\.codex\automations\memory-os-3-200-monitor\last-snapshot.json \
  --output summary
```

Result:

```text
status=WARN
FAIL=[]

owner_action_count=2
owner_action_type_counts={approve_proposal:1, reject_candidate:1}
proposal_queue.state_counts={approved_for_proposal:2, candidate:14}
owner_approved_crystallized_write_count=0
unapproved_crystallized_write_count=0

owner_review_ingress_guard.legacy_anchor_accepted=false
owner_review_ingress_guard.legacy_reject_anchor_accepted=false
owner_review_ingress_guard.ordinary_anchor_text_accepted=false
owner_review_ingress_guard.token_command_accepted=true
owner_review_ingress_guard.slash_token_command_accepted=true
owner_review_ingress_guard.feedback_token_command_accepted=true

owner_review_cron_integration.status=ok
owner_review_cron_integration.enabled=true
owner_review_cron_integration.job_present=true
owner_review_cron_integration.job_enabled=true
owner_review_cron_integration.raw_body_included_count=0
owner_review_cron_integration.unapproved_send_count=0

owner_delivery_status.unapproved_send=0
owner_delivery_status.raw_body_included=0
memory_sources.boundary_true_count=0
memory_sources.forbidden_field_count=0
```

Expected WARN:

```text
session_mirror_pending_sessions
rh31_eval_has_failures
rh26_casual_empty
```

## 2026-05-26 - Prototype Alignment Review From 10.20.2.88

Scope:

```text
Read-only inspect 10.20.2.88 Hermes main/Sannai runtime before continuing
RH-38/RH-39/P1-T work.

Do not edit 10.20.2.88.
Do not restart gateways.
Do not read or print secrets.
Use the prototype only to derive Memory-OS ownership/cadence/closure shape.
```

Commands / evidence:

```text
ssh hermes-lan "hostname; whoami; date; uptime; readlink -f /root/.hermes; hermes version; hermes gateway status"

host=YC-NAS
hermes_version=0.14.0
main_gateway=active
sannai_profile_gateway=active
main_home=/vol1/.hermes
sannai_home=/root/.hermes/profiles/sannai

ssh hermes-lan "hermes cron list"
ssh hermes-lan "HERMES_HOME=/root/.hermes/profiles/sannai hermes cron list"
```

Prototype observations:

```text
Main Hermes:
  Self-Evolution 每日深度反思 (pipeline)
    schedule=0 4 * * *
    deliver=origin
    script=self_evolution_daily_pipeline.py
    skills=self-evolution-governor

  Self-Evolution 周度战略复盘
    schedule=0 7 * * 1
    deliver=origin
    skills=self-evolution-governor

  Wandering Mind 每周自由漫游
    schedule=30 4 * * 0
    deliver=origin

  Wandering Mind 家庭语境摘要刷新
    schedule=0 22 * * 6
    deliver=local
    mode=no-agent

Sannai:
  三奶的自由时间
    schedule=0 9,13,17,21 * * *
    deliver=origin

  三奶的余温检查
    schedule=12:00 / 16:00 / 20:00
    deliver=origin

  三奶的随机心跳调度
    schedule=0:05 daily
    deliver=local
    mode=no-agent
    creates one-shot deliver=origin jobs
    supports [SILENT]

  treasure index / daily digest / weekly consolidation / memory journal
    deliver=local
    mode=no-agent
```

Self-evolution pipeline shape:

```text
collect_signals
proposal_cleanup
proposal_verify
agenda_maturation
unmatched_signal_review
unmatched_cluster_ledger
new_agenda_preview
speak_gate
new_agenda_apply_ready
build_runtime_digest
build_console
restart_console_server
pipeline_contract_check
```

Contract checker shape:

```text
read_only=true
checks step order
checks proposal queue parseability
checks approved proposals have execution blocks
checks delivery/silent reason
checks duplicate scheduler surface
reports no_route_executed / no_ops_gate_task_created / no_sannai_state_write
```

Memory-OS decision:

```text
ARCHITECTURE PASS with runtime gaps.

The prototype confirms:
  Hermes owns cron, origin/local delivery, profile isolation, transport,
  mailbox cooldown, and agent conversation.

  Memory-OS must own bounded state, expression drafts, gates, proposal state,
  owner action state, monitor evidence, and contract checks.

  P1-R must align to Sannai free-time/afterglow, not deterministic report text.
  P1-S must align to staged self-evolution pipeline and read-only checker.
  P1-T must split production cadence from the 6h test-host cognitive loop.
```

Docs updated:

```text
40-memory-os-unified-control-plane.md
38-right-brain-expression-closure-contract.md
39-left-brain-governance-quality-contract.md
32-active-roadmap-and-gates.md
36-module-closure-matrix.md
```

Interpretation:

- Legacy display-anchor commands such as `approve A2` and `reject R1` are no
  longer live ingress commands.
- Token commands such as `memory approve oa_<token>` are recognized by the
  installed provider ingress guard.
- The real approved proposal is visible as `approved_for_proposal`, and it did
  not execute work. The follow-up projection for approved proposals remains a
  next closure item.

## 2026-05-25 - RH-35.6 Approved Proposal Follow-Up Projection

Scope:

- close the remaining owner-action loop after `approve_proposal`;
- expose `approved_for_proposal` as a bounded follow-up projection;
- do not create execution tickets, execute work, send messages, write identity,
  or write crystallized memory.

Local verification:

```text
python -m pytest -q \
  tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/scripts/test_memory_os_3_200_monitor.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py

81 passed
```

Remote deploy:

```text
HERMES_HOME=/root/.hermes bash /tmp/memory-os-rh35-6/scripts/install_memory_os.sh \
  --yes --test-host --skip-verify

installer copied owner_actions.py, cli.py, shell plugin, monitor-facing runtime,
and owner review helper/gate scripts.
```

Remote shell alias evidence:

```text
hermes memory-os-agent-os review proposal-followups --limit 5

schema_version=memory-os.approved_proposal_followups.v0
status=ok
pending_followup_count=2
shown_count=2
overflow_count=0
execution_ticket_count=0
raw_body_included=false
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_unapproved_crystallized_approval=false

items:
  - proposal_id=prop_20260521T093627745201Z_aa81f796ec
    title=Tune ordinary memory conversation tone
    state=approved_for_proposal
    followup_state=awaiting_human_controlled_followup
    owner_action_id=oact_20260525T155152508018Z_70c60a8e
    execution_ticket_created=false
  - proposal_id=prop_20260521T032500038479Z_d6d4850b02
    title=Fresh deployment proposal queue validation
    state=approved_for_proposal
    followup_state=awaiting_human_controlled_followup
    execution_ticket_created=false
```

Monitor evidence:

```text
status=WARN
FAIL=[]

OwnerProposalFollowups={
  pending: 2,
  shown: 2,
  overflow: 0,
  execution_tickets: 0,
  raw_body_included: false
}

PASS includes:
  owner_review_proposal_followups_ok

WARN includes:
  owner_review_approved_proposals_pending_followup
```

Interpretation:

- `approve_proposal` is no longer a hidden terminal state. Approved proposals
  now appear in an explicit follow-up projection.
- This projection is still not execution. It exists so OpsGate / owner review
  can decide a later explicit execution/apply path.

Latest read-only monitor recheck:

```text
time=2026-05-25T16:28:54Z
status=WARN
FAIL=[]

owner_review_proposal_followups_ok=true
OwnerProposalFollowups={
  pending: 2,
  shown: 2,
  overflow: 0,
  execution_tickets: 0,
  raw_body_included: false
}

OwnerReview.owner_actions=2
OwnerReview.by_type={approve_proposal:1, reject_candidate:1}
ModuleArtifacts.proposal_queue.state_counts={approved_for_proposal:2, candidate:14}

OwnerDeliveryStatus.unapproved_send=0
OwnerDeliveryStatus.raw_body_included=0
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
```

Expected WARN:

```text
session_mirror_pending_sessions
owner_review_approved_proposals_pending_followup
rh31_eval_has_failures
rh26_casual_empty
```

Gate judgment:

- RH-35.6 is deployed and visible through both provider CLI and shell alias.
- The approved-proposal backlog is now observable instead of hidden.
- No execution ticket was created by projection, so proposal execution remains a
  future explicit OpsGate/apply design item.

## 2026-05-25 RH-35.7 Approved Proposal -> OpsGate Report-Only Path

Purpose:

- close the next owner-review loop after `approve_proposal`;
- make approved proposals routable into OpsGate/manual execution review without
  executing work;
- prove the path does not create execution tickets, does not call tools, and
  does not include private raw proposal bodies.

Deployment:

```text
host=10.20.3.200
install_command=scripts/install_memory_os.sh --yes --test-host --skip-verify
gateway_restart=not requested
owner_review_cron=already_configured (Hermes cron owns delivery)
```

Pre-apply follow-up surface:

```text
command:
  hermes memory-os-agent-os review proposal-followups --limit 5

pending_followup_count=2
awaiting_ops_gate_count=2
ops_gate_reviewed_count=0
execution_ticket_count=0
raw_body_included=false

selected proposal:
  proposal_id=prop_20260521T093627745201Z_aa81f796ec
  title=Tune ordinary memory conversation tone
  followup_state=awaiting_ops_gate_review
```

Dry-run OpsGate route:

```text
command:
  hermes memory-os-agent-os review proposal-followups \
    --proposal-id prop_20260521T093627745201Z_aa81f796ec \
    --ops-gate

schema_version=memory-os.approved_proposal_ops_gate.v0
status=ok
dry_run=true
ops_gate_report_written=false
execution_ticket_created=false
actual_execute=false
raw_body_included=false
```

Report-only apply:

```text
command:
  hermes memory-os-agent-os review proposal-followups \
    --proposal-id prop_20260521T093627745201Z_aa81f796ec \
    --ops-gate --apply

schema_version=memory-os.approved_proposal_ops_gate.v0
status=ok
dry_run=false
ops_gate_report_written=true
ops_gate_result.execution_mode=report-only
ops_gate_result.decisions[0].decision=would_allow
ops_gate_result.decisions[0].actual_execute=false
execution_ticket_created=false
actual_execute=false
raw_body_included=false
```

Post-apply follow-up surface:

```text
pending_followup_count=2
awaiting_ops_gate_count=1
ops_gate_reviewed_count=1
execution_ticket_count=0
raw_body_included=false

proposal_id=prop_20260521T093627745201Z_aa81f796ec
followup_state=ops_gate_reviewed_awaiting_explicit_execution
ops_gate_decision=would_allow
ops_gate_report_id=opsr_20260525T165807816317Z_084b8dd1b6
actual_execute=false
execution_ticket_created=false
```

Monitor evidence:

```text
time=2026-05-25T16:58:34Z
status=WARN
FAIL=[]

audit_per_new_event=4.2
OwnerProposalFollowups={
  pending: 2,
  shown: 2,
  overflow: 0,
  awaiting_ops_gate: 1,
  ops_gate_reviewed: 1,
  execution_tickets: 0,
  raw_body_included: false
}
OwnerReview.by_type={approve_proposal:1, reject_candidate:1}
ModuleArtifacts.proposal_queue.state_counts={approved_for_proposal:2, candidate:15}
OwnerDeliveryStatus.unapproved_send=0
OwnerDeliveryStatus.raw_body_included=0
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
```

Expected WARN:

```text
session_mirror_pending_sessions
owner_review_approved_proposals_pending_followup
rh31_eval_has_failures
rh26_casual_empty
```

Gate judgment:

- RH-35.7 closes the immediate approved-proposal follow-up gap by routing an
  approved proposal into OpsGate report-only review.
- It does not execute work and does not create execution tickets.
- The remaining open item is a separate future explicit execution/apply path
  for proposals that have already passed owner approval and OpsGate review.

## 2026-05-26 Independent Mainline Review Follow-Up

Source:

- `INDEPENDENT_MAINLINE_REVIEW_2026-05-26.md`

Scope:

- close the report's two P1 findings and three actionable P2 findings against
  the 29/36 contracts;
- verify the installed 10.20.3.200 path, not only local tests;
- keep owner-action, proposal follow-up, monitor, and shell alias behavior
  aligned.

Findings handled:

```text
P1 owner review token command could be captured as conversation memory
P1 repeated approved proposal -> OpsGate apply could append duplicate reports
P2 shell alias JSON status=error returned process exit 0
P2 monitor did not classify owner-token promotion or duplicate proposal follow-up
P2 CrystallizedCandidate(tags=None) round-trip failed
```

Contract mapping:

```text
Contract 8 OwnerAction:
  processed owner-review token commands are control-plane commands only;
  they must not become ordinary events, working items, or memory candidates.

Contract 5/8 Scheduler + OwnerAction:
  approved proposal -> OpsGate report-only apply is idempotent;
  duplicate apply returns duplicate_ignored and does not append another report.

Contract 6 MonitorEvidence:
  monitor must expose token-command event/working/candidate counts and
  duplicate proposal-followup counts.
```

Local verification:

```text
python -m pytest -q
510 passed

Realistic post-fix probe:
  candidate_tags_none.tags=[]
  duplicate_ops_gate_apply.first_status=ok
  duplicate_ops_gate_apply.second_status=duplicate_ignored
  duplicate_ops_gate_apply.report_count=1
  owner_command_capture.event_count=0
  owner_command_capture.working_created_count=0
  owner_command_capture.candidate_created_count=0
```

Deployment:

```text
host=10.20.3.200
install_command=scripts/install_memory_os.sh --yes --test-host --skip-verify
gateway_restart=not requested
owner_review_cron=already_configured
copied_file_count=36
```

Installed shell alias exit-code evidence:

```text
command:
  hermes memory-os-agent-os review proposal-followups \
    --proposal-id does_not_exist --ops-gate

json.status=error
json.reason=proposal_not_found
process_exit_code=1
```

Duplicate OpsGate apply evidence:

```text
proposal_id=prop_20260521T093627745201Z_aa81f796ec

before:
  proposal_followup:prop_20260521T093627745201Z_aa81f796ec=1

command:
  hermes memory-os-agent-os review proposal-followups \
    --proposal-id prop_20260521T093627745201Z_aa81f796ec \
    --ops-gate --apply

result.status=duplicate_ignored
ops_gate_report_written=false
execution_ticket_created=false
actual_execute=false

after:
  proposal_followup:prop_20260521T093627745201Z_aa81f796ec=1
```

Monitor evidence:

```text
time=2026-05-25T18:35:49Z
status=WARN
FAIL=[]

owner_review_ingress_guard.token_command_accepted=true
owner_review_ingress_guard.legacy_anchor_accepted=false
owner_review_ingress_guard.owner_command_event_count=0
owner_review_ingress_guard.owner_command_working_count=0
owner_review_ingress_guard.owner_command_candidate_count=0
owner_review_ingress_guard.owner_command_promoted_to_candidate=false

module_artifacts.ops_gate.proposal_followup_action_count=1
module_artifacts.ops_gate.duplicate_proposal_followup_count=0
module_artifacts.ops_gate.duplicate_proposal_followup_extra_count=0

owner_review.proposal_followups.pending_followup_count=2
owner_review.proposal_followups.awaiting_ops_gate_count=1
owner_review.proposal_followups.ops_gate_reviewed_count=1
owner_review.proposal_followups.execution_ticket_count=0

shell_alias_no_env.review_followups_ok=true
MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
```

Expected WARN:

```text
session_mirror_pending_sessions=25
owner_review_approved_proposals_pending_followup=2
rh31_eval_has_failures=3
rh26_casual_empty
```

Gate judgment:

- The installed code path closes the independent review's P1/P2 findings.
- The remaining WARN items are tracked observation items, not regressions from
  this fix.
- Because `hermes-gateway.service` was not restarted during this gate, the
  installed provider/runtime path is verified, but a live Telegram
  `sync_turn` retest requires a separate gateway reload/restart gate.

## RH-35.8 Agent-Mediated Owner Reply Tool Correction

Date: 2026-05-26

Finding source:

```text
Owner replied in Telegram:
  memory approve oa_e9a4e734a07de7
  memory approve oa_40b674ced068f7

Observed response:
  Memory-OS: 这条审批指令没有生效（gateway_ingress_error）。
```

Root cause:

```text
The Memory-OS shell plugin had registered a pre_gateway_dispatch owner-review
hook. That hook intercepted the message before the Hermes agent saw it, skipped
normal agent dispatch, and then failed inside the installed runtime import path.

This was the wrong ownership seam:
  Hermes is the agent that should interpret the owner command.
  Memory-OS is the plugin/state machine that should expose a tool/API.
  Gateway interception can only be a fail-open safety layer, not the primary
  approval path.
```

Design correction:

```text
Hermes conversation
  -> Hermes agent recognizes an owner-review task
  -> agent calls Memory-OS provider tool memory_os_review_reply
  -> parse_owner_review_reply(apply=true, require_recorded_digest=true)
  -> OwnerActionProcessor
  -> bounded assistant confirmation

sync_turn:
  if the tool already processed the command, skip ordinary conversation capture
  if the tool was not called, skip ordinary capture and audit
  owner_review_reply_tool_not_called
```

Local verification:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_lifecycle.py \
  tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

96 passed
```

Deployment:

```text
host=10.20.3.200
install_command=scripts/install_memory_os.sh --yes --test-host --skip-verify
gateway_restart=performed
gateway_pid_after_restart=503743
owner_review_cron=already_configured
```

Installed seam check:

```text
provider_tools=["memory_os_status", "memory_os_review_reply"]
system_prompt_has_owner_review_tool_rule=true
memory-os-agent-os hooks=[
  "on_session_start",
  "on_session_reset",
  "on_session_finalize"
]
pre_gateway_dispatch_registered=false
```

Monitor evidence after deployment:

```text
time=2026-05-26T03:09:29Z
status=WARN
FAIL=[]

owner_review_ingress_guard.token_command_accepted=true
owner_review_ingress_guard.slash_token_command_accepted=true
owner_review_ingress_guard.feedback_token_command_accepted=true
owner_review_ingress_guard.legacy_anchor_accepted=false
owner_review_ingress_guard.legacy_reject_anchor_accepted=false
owner_review_ingress_guard.ordinary_anchor_text_accepted=false
owner_review_ingress_guard.gateway_hook_registered=false
owner_review_ingress_guard.review_reply_tool_available=true
owner_review_ingress_guard.review_reply_tool_status=ok
owner_review_ingress_guard.owner_command_event_count=0
owner_review_ingress_guard.owner_command_working_count=0
owner_review_ingress_guard.owner_command_candidate_count=0

MemorySources.boundary_true_count=0
MemorySources.forbidden_field_count=0
owner_review_cron_integration.status=ok
owner_review_cron_integration.enabled=true
owner_review_cron_integration.job_present=true
owner_review_cron_integration.unapproved_send_count=0
```

Live delivery refresh:

```text
command:
  hermes cron run 2af755464ca8
  hermes cron tick

result:
  last_run=2026-05-25T23:10:27.342159-04:00 ok
  delivered through Hermes cron --deliver telegram
```

Pending evidence:

```text
The new digest was delivered after the gateway restart. The final closure gate
requires the owner to reply with one of the freshly delivered
memory approve/reject/allow oa_<token> commands and verify that Hermes agent
uses memory_os_review_reply without gateway_ingress_error.
```

## RH-35.8 Live Owner Reply Success And Bare-Token Pollution Follow-Up

Date: 2026-05-26

Live owner test:

```text
Digest delivered through Hermes cron:
  memory approve oa_40b674ced068f7 / memory reject oa_9b53f82a9ab231

Owner replied in Telegram:
  approve oa_40b674ced068f7

Visible agent behavior:
  tool call displayed: memory_os_review_reply
  response: Approved oa_40b674ced068f7.
```

State verification:

```text
owner_actions.count=4
latest owner action:
  action_type=approve_proposal
  action_token=oa_40b674ced068f7
  owner_action_id=oact_20260526T031149196991Z_bc724c72
  target_id=prop_20260521T032500041194Z_2f96a933aa
  result_ref.state=approved_for_proposal
  channel=telegram
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_unapproved_crystallized_approval=false

proposal_followups:
  pending_followup_count=4
  awaiting_ops_gate_count=3
  ops_gate_reviewed_count=1
  execution_ticket_count=0
```

Audit evidence:

```text
audit action=owner_review_reply_ingress
phase=tool_call
status=ok
action_token=oa_40b674ced068f7
action_type=approve_proposal
channel=telegram
```

Follow-up finding:

```text
The owner used stable-token shorthand (`approve oa_<token>`) instead of the
digest's safer prefixed form (`memory approve oa_<token>`). Hermes agent still
called the correct tool and the state transition was correct.

However, the provider control-plane skip detector only recognized the prefixed
form, so one ordinary conversation event was captured:
  evt_20260526T031153751349Z_9ad7d70697
  summary="User: approve oa_40b674ced068f7 | Assistant: Approved ..."

At discovery time, heartbeat_state.processed_event_count=249 while total
events=250, so the captured event had not yet been processed into working
memory or candidates.
```

Fix applied locally:

```text
_looks_like_owner_review_reply now accepts stable-token shorthand:
  approve oa_<token>
  reject oa_<token>
  allow oa_<token>
  feedback oa_<token> too_mechanistic

The digest still prints `memory <verb> oa_<token>` as the recommended form.
Display anchors remain invalid.
```

Local verification:

```text
python -m pytest tests/plugins/memory/test_memory_os_lifecycle.py \
  tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

96 passed

python -m pytest -q
511 passed
```

Pending deployment gate:

```text
Deploy the shorthand skip fix to 10.20.3.200, restart gateway, and rerun monitor.
If the unprocessed conversation event is still unprocessed, remove or quarantine
that single control-plane event before heartbeat can promote it.
```

## RH-35.9 Implementation And Test-Host Deploy - Interactive Agent Task Semantics

Runtime implementation has been deployed to `10.20.3.200` at the provider
tool-contract and monitor-probe level. The remaining gate is one real
Hermes-agent tokenized owner phrase smoke after the owner replies to a visible
digest.

Reason:

```text
The previous correction still treated owner review as mostly an exact text
command problem. That is the wrong product seam.

Hermes is an agent. It should interpret the owner review task, ask a
clarification when needed, then call a structured Memory-OS tool.

Memory-OS is the deterministic state machine. It should receive action +
stable action token, apply OwnerActionProcessor, write audit/monitor evidence,
and prevent memory pollution.
```

Design update made:

```text
34-owner-review-digest-and-action-workflow.md:
  RH-35.9 updated from design-only to structured-first implementation.
  memory_os_review_reply primary contract becomes structured:
    action + action_token + optional rating + optional owner_utterance
  reply fallback remains accepted by provider handle_tool_call for CLI/legacy
  callers, but it is not exposed in the model-facing schema.

29-memory-os-module-integration-contract.md:
  Contract 8 now says Hermes agent owns interactive interpretation and
  clarification; Memory-OS tools/state machines receive only stable token
  identity.

36-module-closure-matrix.md:
  Agent-Mediated Owner Reply Tool is reclassified as an interactive agent task
  with structured tool execution, not an exact-command parser.

32-active-roadmap-and-gates.md:
  RH-35.9 is marked local implementation in progress with live deployment gate.
```

Local implementation evidence:

```text
provider tool schema:
  action enum: approve / reject / allow / feedback
  action_token: stable oa_<token>
  rating: feedback-only
  owner_utterance: optional control-plane sync skip/audit context
  reply: hidden compatibility fallback, not model-facing

monitor:
  owner_review_ingress_guard now records review_reply_tool_input_mode
  classification FAILs if the tool path is not structured

targeted tests:
  python -m pytest \
    tests/plugins/memory/test_memory_os_lifecycle.py \
    tests/plugins/memory/test_memory_os_owner_actions.py \
    tests/system_modularization/test_memory_os_agent_os_shell.py \
    tests/scripts/test_memory_os_3_200_monitor.py -q

result:
  99 passed
```

Full local verification:

```text
command:
  python -m pytest -q

result:
  514 passed
```

Remote deployment:

```text
host: hermes-media / 10.20.3.200
install:
  HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host --skip-verify

gateway:
  systemctl --user restart hermes-gateway.service
  ActiveState=active
  SubState=running
  ExecMainStatus=0

provider schema smoke:
  tool_present=true
  properties=[action, action_token, owner_utterance, rating]
  required=[action, action_token]
  has_reply=false
  description_has_fallback=false
  description_mentions_free_form=true
```

Remote monitor evidence:

```text
classification: WARN
FAIL: []
owner_review_ingress_guard.review_reply_tool_input_mode=structured
owner_review_ingress_guard.review_reply_tool_status=ok
owner_review_ingress_guard.gateway_hook_registered=false
owner_review_ingress_guard.owner_command_event_count=0
owner_review_ingress_guard.owner_command_working_count=0
owner_review_ingress_guard.owner_command_candidate_count=0
known WARN:
  session_mirror_pending_sessions
  owner_review_approved_proposals_pending_followup
  rh31_eval_has_failures
  rh26_casual_empty
```

Known residual from pre-RH-35.9 live test:

```text
event id:
  evt_20260526T031153751349Z_9ad7d70697

finding:
  the old bare-token owner command path had already been processed before the
  structured tool correction was deployed

read-only lookup after RH-35.9 deploy:
  event_found_in_top_level_events=false
  working_refs=1
  candidate_refs=1
  audit_refs=0

status:
  RH-35.9 prevents new owner command pollution through structured
  memory_os_review_reply + sync_turn skip
  cleanup/quarantine of the historical working/candidate artifacts should be
  handled as a separate bounded data repair, not silently inside this runtime
  change
```

Real digest trigger:

```text
hermes cron run 2af755464ca8
hermes cron tick

job:
  memory-os-owner-review-digest
  Last run: 2026-05-25T23:51:11.154411-04:00 ok
```

Owner exact-token action after deploy:

```text
owner message:
  memory approve oa_e9a4e734a07de7

Hermes agent:
  called memory_os_review_reply
  response: Approved oa_e9a4e734a07de7

Memory-OS result:
  owner_action_count increased to 5
  action_type_counts={approve_proposal: 4, reject_candidate: 1}
  owner_review_reply_ingress status=ok
  owner_review_reply_sync_turn_skipped status=ok
  event/working/candidate pollution for this command=0
  boundary actual_execute=false
  boundary actual_send=false

Important limitation:
  the real Hermes tool call used the compatibility fallback:
    {"reply":"memory approve oa_e9a4e734a07de7",
     "owner_utterance":"memory approve oa_e9a4e734a07de7"}

  This proves the agent-mediated exact-token path is healthy, but it does not
  prove the RH-35.9 structured live path. The remaining live gate is the same
  tokenized owner intent, e.g. "memory approve oa_<token>" or "批准
  oa_<token>", resolved by Hermes into structured action/action_token
  arguments rather than the fallback reply string.
```

Planned post-approval verification:

```text
live 10.20.3.200:
  owner replies with a tokenized task phrase, e.g. "memory approve oa_<token>"
  or "批准 oa_<token>"
  Hermes agent calls tool and returns bounded result
  monitor confirms gateway_hook_registered=false, unapproved boundary counts=0,
  owner command event/working/candidate pollution=0
```

## RH-34g/RH-35.9 Follow-Up - Chinese Digest Header And Agent-Mode Cron

Finding:

```text
The owner-review digest reached Telegram, but the recurring job was configured
as Hermes cron no-agent mode. That caused Memory-OS helper stdout to be
delivered verbatim, producing English/template-like text instead of a Chinese
Hermes-agent-mediated review message.
```

10.20.2.88 reference check:

```text
Hermes production prototype uses two different patterns:
  watchdog/direct alert: --script --no-agent --deliver
  owner-facing review/reflection: --script or prompt with deliver=origin, so
  script output becomes evidence for Hermes agent to read and summarize

Examples observed read-only on 10.20.2.88:
  Ops 门禁巡检日报: deliver=origin, prompt runs script then reports
  Self-Evolution 每日深度反思: deliver=origin, script + skill + prompt
  CW-019 owner review report: no-agent direct report, but not interactive
  Memory-OS owner review should follow the agent-mediated owner-facing pattern.
```

Local implementation changes:

```text
renderer:
  title changed to Memory-OS 审批摘要
  adds 回复方式 header:
    - copy full command such as memory approve oa_...
    - or send oa_... and Hermes asks approve/reject/allow/feedback
    - A1/R1/F1 are display labels, not approval ids
  item labels and consequences are Chinese

monitor:
  owner_review_rendered_digest.response_header_present
  FAIL when response header is missing

cron gate:
  creates/updates Hermes cron job in agent mode, not --no-agent
  prompt instructs Hermes agent to read Script Output, write Chinese owner
  digest, preserve oa_ tokens, and never auto-approve/execute
  existing no-agent owner-review job is treated as needing update
```

Local verification:

```text
python -m pytest tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/scripts/test_memory_os_owner_review_cron_gate.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

result: 77 passed

python -m pytest tests/scripts/test_memory_os_plugin_install.py::test_installer_can_copy_owner_review_cron_helper_without_enabling_cron -q

result: 1 passed
```

Live gate:

```text
Deploy to 10.20.3.200, apply the recurring gate, verify the job mode is agent
mode, trigger one digest, and confirm Telegram receives a Chinese
Hermes-agent-mediated message instead of raw helper stdout.
```

Live follow-up after strengthening the digest brief and Hermes agent prompt:

```text
cron job:
  job_id=2af755464ca8
  name=memory-os-owner-review-digest
  mode=Hermes agent mode (not --no-agent)
  deliver=telegram
  script=memory_os_owner_review_digest.py

owner-visible Telegram digest:
  title=Memory-OS 审批摘要（给 owner）
  includes_full_picture=true
  pending_total=194
  action_required_total=12
  review_suggested_total=15
  fyi_total=169
  shown_total=13
  omitted_action_required=9
  omitted_review_suggested=10
  omitted_fyi=164
  explains_omitted_items=true
  explains_A1_R1_are_display_labels=true
  contains_stable_oa_token_commands=true
  item_details_include_decision_and_consequence=true
  command_only_digest=false
```

Owner action smoke from the same visible digest:

```text
owner message:
  memory reject oa_1e9ca00f639ca2

Hermes agent:
  called memory_os_review_reply
  response: Rejected oa_1e9ca00f639ca2

Memory-OS status after action:
  owner_action_count=8
  action_type_counts={approve_proposal: 6, reject_candidate: 1, reject_proposal: 1}
  proposal_rejected_count=1
  unapproved_crystallized_write_count=0
  owner_review.cron_integration.status=ok
  owner_review.cron_integration.mode=hermes_cron_agent
  owner_review.cron_integration.unapproved_send_count=0
  owner_review.cron_integration.raw_body_included_count=0
  owner_review_rendered_digest.response_header_present=true
  owner_review_rendered_digest.overview_present=true
  owner_review_rendered_digest.text_has_internal_schema=false
  owner_review_rendered_digest.text_has_transcript_marker=false
  owner_review_proposal_followups.pending_followup_count=7
  owner_review_proposal_followups.execution_ticket_count=0
  owner_review_proposal_followups.boundary.actual_execute=false
```

Interpretation:

```text
The owner-review loop is now agent-mediated and owner-readable:
  Memory-OS produces bounded review data and stable action tokens.
  Hermes agent produces the Chinese owner-facing digest and handles interaction.
  Owner action routes to OwnerActionProcessor.
  Approval/rejection changes review/proposal state only.
  It does not execute work or write unapproved crystallized memory.

Length limits are now treated as pagination/burden control, not silent
truncation. The digest must show full-picture counts and omitted counts, and
displayed items must be complete enough for a human decision.
```

## RH-34h/RH-35.10 Agent Review Surface And Proposal Follow-Up Projection

Design update:

```text
RH-34h adds an agent-mediated review surface for owner questions such as:
  - 还有哪些 / 下一页
  - 展开 R3
  - 这个 proposal 是什么

Hermes owns the human interaction and wording. Memory-OS only returns bounded,
read-only review surface data. The surface is not a send path, not an execution
path, and not a state mutation path.

RH-35.10 adds a report-only approved proposal follow-up projection:
  approved_for_proposal items become visible for OpsGate/manual follow-up
  actual execution still requires a separate future explicit apply gate
```

Local verification:

```text
python -m pytest tests/scripts/test_memory_os_3_200_monitor.py \
  tests/plugins/memory/test_memory_os_owner_actions.py \
  tests/plugins/memory/test_memory_os_lifecycle.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py -q

result: 103 passed

python -m pytest -q

result: 519 passed
```

Live deployment and schema check:

```text
target: 10.20.3.200
install: scripts/install_memory_os.sh --yes --test-host --skip-verify
gateway restart: systemctl --user restart hermes-gateway.service
gateway status: active/running, ExecMainStatus=0

provider tools:
  memory_os_status
  memory_os_review_reply
  memory_os_review_surface

memory_os_review_surface required args:
  operation
```

Live surface smoke:

```text
hermes memory-os-agent-os review surface --operation next_page \
  --section action_required --limit 2

result:
  schema_version=memory-os.owner_review_surface.v0
  status=ok
  source=latest_owner_home_digest
  returned next action-required items
  raw_body_included=false
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.actual_identity_write=false
  boundary.actual_unapproved_crystallized_approval=false

hermes memory-os-agent-os review surface --operation detail \
  --anchor R1 --channel telegram

result:
  schema_version=memory-os.owner_review_surface.v0
  status=ok
  binding_source=latest_recorded_digest
  returned bounded detail for R1
  raw_body_included=false
  all boundary fields=false
```

Approved proposal follow-up dry-run:

```text
proposal_id=prop_20260523T085831319444Z_8c175467e9

hermes memory-os-agent-os review proposal-followups \
  --proposal-id "$proposal_id" --ops-gate

result:
  schema_version=memory-os.approved_proposal_ops_gate.v0
  status=ok
  dry_run=true
  proposal_state=approved_for_proposal
  execution_ticket_created=false
  actual_execute=false
  raw_body_included=false
  all boundary fields=false
```

Monitor closure:

```text
python scripts/memory_os_3_200_monitor.py --host hermes-media --output summary

result: WARN, no FAIL

new pass:
  owner_review_surface_ok

owner_review_surface:
  status=ok
  raw_body_included_count=0
  boundary_true_count=0
  next_page.status=ok, item_count=2, source=latest_owner_home_digest
  detail.status=ok, item_count=1
  proposal_followups.status=ok

owner_review_proposal_followups:
  pending_followup_count=7
  awaiting_ops_gate_count=6
  ops_gate_reviewed_count=1
  execution_ticket_count=0
  raw_body_included=false

known WARN:
  session_mirror_pending_sessions=27
  owner_review_approved_proposals_pending_followup=7
  rh31_eval_has_failures=3
  rh26_casual_empty

boundary:
  unapproved_send_count=0
  raw_body_included_count=0
  actual_execute=false
```

Self-review:

```text
PASS:
  - Hermes remains the interaction owner.
  - Memory-OS exposes a bounded review surface and action processor only.
  - The new surface is read-only and monitorable.
  - Approved proposals are visible for follow-up but still cannot execute.
  - Local tests and live monitor both pass safety boundaries.

NOT CLOSED:
  - approved_for_proposal still needs the future explicit execution/apply RH
    before any real work can run.
  - SessionMirror pending sessions and RH-31 eval failures remain observation
    items, not blockers for RH-34h/RH-35.10.
```

## RH-36b Closure Matrix Live Reconciliation

Purpose:

```text
RH-36 is not treated as documentation-only. The closure matrix now has a local
check that reconciles code-defined live modules and contract-critical non-live
surfaces against the module closure table.
```

10.20.3.200 live module inventory:

```text
source: hermes memory-os-agent-os modules status
live_module_count=16
modules:
  cron_mirror
  session_mirror
  state_source_mirror
  shadow_journal
  deep_reflection
  governance_feedback
  digest_consolidation
  inner_drive
  mailbox
  household_digest
  wandering_mind
  evidence_scoring
  ops_gate
  proposal_queue
  self_evolution
  speak_gate
```

10.20.3.200 owner-review delivery evidence:

```text
source: hermes memory-os-agent-os review cron-status
schema_version=memory-os.owner_review_cron_integration.v0
enabled=true
status=ok
mode=hermes_cron_agent
job_id=2af755464ca8
delivery_target_class=platform_home
recurring_channel=telegram
raw_body_included_count=0
unapproved_send_count=0
boundary fields=false
```

10.20.2.88 / Sannai reference prototype recheck:

```text
source: hermes cron list on 10.20.2.88
owner-facing scheduled reports use Hermes cron delivery classes such as origin.
current origin-delivery scheduled job count: 13.
Sannai report jobs use no-agent direct stdout for report-style output, not for
interactive Memory-OS state mutation.

source: Hermes mailbox adapter grep on 10.20.2.88
mailbox contains final_only, proactive_send_enabled, auto_wake_cooldown,
reply-depth controls, and [NO_REPLY] semantics.
current mailbox-control grep hit count: 13.
mailbox remains an internal AI-agent mailroom, not the owner approval path.
```

Local enforcement:

```text
python scripts/memory_os_closure_matrix_check.py --format summary

status=ok
live_module_count=16
matrix_module_count=26
finding_count=0
```

Regression coverage:

```text
python -m pytest tests/scripts/test_memory_os_closure_matrix_check.py -q

result: 3 passed
coverage:
  - current RH-36 matrix reconciles live code-defined modules
  - missing live module matrix row fails
  - freeform classification prose such as "event_driven_fast with cooldown"
    fails instead of being accepted as a class

python -m pytest tests/scripts/test_memory_os_3_200_monitor.py \
  tests/scripts/test_memory_os_closure_matrix_check.py -q

result: 36 passed
```

Self-review:

```text
PASS:
  - RH-36 now has an executable local check.
  - The check is grounded in 10.20.3.200 live module inventory.
  - The Hermes transport/scheduler reference is grounded in 10.20.2.88 main and
    Sannai cron/mailbox patterns.
  - 29-series contract and 32-roadmap now treat the check as a gate.

NOT CLOSED:
  - This is still a local/staged-content enforcement check, not yet CI.
  - Future new module/RH work must run the check before claiming implemented.
```

## RH-37 Agent / Memory-OS Collaboration Contract

Purpose:

```text
Define how Hermes agent should use Memory-OS review context and structured tools
without making Memory-OS the owner of owner conversation, clarification,
recovery guidance, scheduling, or transport.
```

Contract status:

```text
file: docs/system-modularization/37-agent-memoryos-collaboration-contract.md
runtime_change=false
execution_capability_added=false
architecture_boundary=Hermes owns owner interaction; Memory-OS owns bounded
  tools, stable tokens, state machines, audit, and monitor evidence
```

Roadmap follow-ups created:

```text
P1-N: RH-37 Agent / Memory-OS Collaboration Contract
P1-O: reply fallback and gateway hook boundary closure
P1-P: candidate/proposal timestamp schema repair
P1-Q: approved proposal follow-up to OpsGate/manual apply
P2-F: RH-34/RH-35 owner-governance family map before public productization
```

Closure matrix:

```text
Agent / Memory-OS Collaboration Contract is now a non-runtime governed surface
in RH-36.

python scripts/memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=16
matrix_module_count=26
finding_count=0
```

Self-review:

```text
PASS:
  - RH-37 is design-only and does not add execution capability.
  - The contract prevents another gateway/parser/transport drift by keeping
    Hermes as the interaction owner.
  - Concrete code follow-ups are split into P1-O/P1-P/P1-Q rather than hidden
    inside the contract.

NOT CLOSED:
  - reply_fallback_used_count is not implemented yet.
  - timestamp producer repair is not implemented yet.
  - future explicit execution/apply path remains separate and must not be
    inferred from proposal approval.
```

Follow-up local closure:

```text
P1-O implemented locally:
  - monitor now exposes structured_review_reply_count,
    reply_fallback_used_count, gateway_safety_skip_count, and
    owner_review_command_pollution_count.
  - provider audit records owner_review_reply_ingress input_mode so fallback
    use is measurable.

P1-P implemented locally for new crystallized candidates and review-aging
projection:
  - new candidate queue entries carry bounded created_at.
  - review aging reports unknown_timestamp_by_item_type,
    created_at_coverage_ratio, true_aged_count, and unknown_aged_count.

P1-Q reinforced locally:
  - approved proposal follow-up projection reports approved_proposal_count and
    actual_execute=false.
  - monitor fails if approved proposal follow-up reports top-level, boundary,
    or item-level actual_execute=true.

Local checks:
  python -m pytest tests/plugins/memory/test_memory_os_owner_actions.py \
    tests/plugins/memory/test_memory_os_lifecycle.py \
    tests/scripts/test_memory_os_3_200_monitor.py \
    tests/scripts/test_memory_os_closure_matrix_check.py -q
  89 passed

NOT LIVE CLOSED YET:
  - deploy/read-only monitor smoke on 10.20.3.200 is still required before
    claiming live closure for P1-O/P1-P/P1-Q.
```

Live deployment and monitor closure:

```text
deployment host: 10.20.3.200 / hermes-media
bundle: /root/Hermes-Memory-OS-p1opq-20260526142349c

HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host
result: install complete
owner review cron gate:
  status=already_configured
  job_id=2af755464ca8
  render_check.ok=true
  render_check.raw_body_included=false
  render_check.internal_schema_primary=false
  render_check.text_char_count=2226

gateway reload:
  systemctl --user restart hermes-gateway.service
  ActiveState=active
  MainPID=507769

monitor:
  python scripts/memory_os_3_200_monitor.py --host hermes-media --output summary
  status=WARN
  FAIL=[]
```

Live evidence:

```text
P1-O:
  owner_review_ingress_guard_token_only=PASS
  review_reply_tool_status=ok
  structured_review_reply_count=1
  reply_fallback_used_count=0
  gateway_hook_registered=false
  gateway_safety_skip_count=0
  owner_review_command_pollution_count=0

P1-P:
  OwnerReviewAging.unknown_timestamp=0
  unknown_timestamp_by_item_type={}
  created_at_coverage_ratio=1.0
  true_aged=0
  unknown_aged=0

P1-Q:
  OwnerProposalFollowups.approved=7
  pending=7
  awaiting_ops_gate=6
  ops_gate_reviewed=1
  execution_tickets=0
  actual_execute=false

Other safety:
  MemorySources.boundary_true_count=0
  MemorySources.forbidden_field_count=0
  OwnerCronIntegration.status=ok
  OwnerCronIntegration.raw_body_included=0
  DeepReflection actual_send/execute/identity/crystallized boundaries=false
```

Remaining WARNs:

```text
session_mirror_pending_sessions
owner_review_approved_proposals_pending_followup
rh31_eval_has_failures
rh26_casual_empty
```

## 2026-05-26 - RH-38 Right-Brain Expression Closure Gap

Finding:

```text
The right-brain expression path was incorrectly treated as closed because
Wandering Mind produced no-send / would-send artifacts and hard send boundaries
remained false. That evidence proves safe test-host observation, not formal
right-brain expression.
```

Source evidence:

```text
architecture.md:
  Wandering Mind should express feeling/free association and may produce free
  expression or [SILENT] -> optional deliver=origin.

current implementation:
  Wandering Mind deterministic summary-based text only;
  shell plugin registers no LLM-call hooks;
  OwnerReview speak items expose bounded refs/actions but not enough expression
  content for voice-quality feedback;
  GovernanceFeedback does not consume the full wandering/speak outcome set.

latest 10.20.3.200 monitor:
  wandering_output_count=15
  wandering_would_send_count=15
  speak_gate_would_send_count=0
  speak_gate_actual_send=false
```

Decision:

```text
P1-E remains only "safe expression observation".
Formal right-brain expression closure is split into P1-R / RH-38.
No runtime expression engine or scheduled expression delivery is implemented in
this correction.
```

Contract updates:

```text
new doc: docs/system-modularization/38-right-brain-expression-closure-contract.md
29 contract: expression tiers and monitor fields added
36 matrix: Wandering/SpeakGate rows and expression pattern corrected
  32 roadmap: P1-R active item added
```

Follow-up audit expansion:

```text
RH-38 was expanded from a Wandering/SpeakGate-only correction into a full
right-brain subsystem audit.

Included surfaces:
  Household Digest
  DeepReflection analysis
  DeepReflection injection / carryover cards
  DeepReflection optional proposals
  DeepReflection wandering seeds
  Conversation Carryover
  Wandering Mind
  SpeakGate
  Owner Review for expression
  Expression feedback
  GovernanceFeedback / SelfEvolution backflow

Finding:
  v0.1 closes context continuity, proposal governance, and safe test-host
  expression observation, but it does not close formal scheduled right-brain
  expression or expression feedback backflow.
```

Closure check:

```text
python scripts/memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=16
matrix_module_count=27
active_work_item_count=18
active_work_mapping_count=18
finding_count=0

python -m pytest tests/scripts/test_memory_os_closure_matrix_check.py -q
5 passed
```

Required future monitor fields include:

```text
right_brain_expression.engine_available
expression_draft_count
speak_gate_evaluated_count
scheduled_delivered_count
exceptional_permission_count
owner_feedback_by_type
policy_update_pending_count
prompt_version
raw_body_included_count
task_language_count
boundary_true_count
```

## 2026-05-26 - RH-39 Left-Brain Governance Quality Gap

Finding:

```text
The left-brain path was previously treated as mature because hard boundaries,
owner actions, audit, monitor, and OpsGate report-only follow-up were safe.
That proves safety governance. It does not prove intelligent judgment,
feedback learning, proposal novelty, production cadence, or execution-decision
closure.
```

Latest live evidence:

```text
working_items=168
expired_working=147
evidence.score_count=606
evidence.subject_counts.working=168
self_evolution.report_count=16
self_evolution.proposal_count=16
proposal_queue.approved_for_proposal=7
proposal_queue.candidate=11
owner_review.feedback_backflow.apply_ready_count=0
MemorySources.feedback_count=0
approved_proposal_followups.awaiting_ops_gate=6
approved_proposal_followups.execution_tickets=0
```

Decision:

```text
Left-brain safety governance remains implemented.
Left-brain judgment quality and feedback adaptation are not mature.
Formal left-brain governance quality work is split into P1-S / RH-39.
No runtime scoring, cadence, proposal, or execution behavior is changed in this
correction.
```

Contract updates:

```text
new doc: docs/system-modularization/39-left-brain-governance-quality-contract.md
29 contract: feedback backflow limits expanded for RH-39
36 matrix: Left-Brain Governance Quality Contract row and P1-S mapping added
32 roadmap: P1-S active item added
```

## RH-36c Active Work Closure Mapping

Purpose:

```text
Upgrade RH-36 from module classification into a development-entry gate:
active roadmap work must map to an RH-36 closure row or explicitly declare why
the closure matrix does not apply.
```

Preflight:

```yaml
source_of_truth: "29 contract, 32 roadmap, 36 closure matrix, current diff"
finding_type: "contract gap / documentation drift"
owning_seam: "RH-36 closure matrix enforcement"
reverse_scope: "no host/Hermes capability; this is local governance validation"
equivalent_contract_or_project_contract: "29-series contract + RH-36 matrix"
evidence_loop: "local contract check + fixture tests"
monitor_or_validation_fields:
  - active_work_item_count
  - active_work_mapping_count
  - missing_active_work_items
  - invalid_active_work_mapping_count
promotion_signal: "closure check status=ok and all active P1/P2-F items mapped"
stop_or_rollback_signal: "missing/stale active mapping or unknown closure row"
external_review: "not required for local governance check; useful before public claim"
```

Evidence:

```text
python scripts/memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=16
matrix_module_count=26
active_work_item_count=17
active_work_mapping_count=17
finding_count=0

python -m pytest tests/scripts/test_memory_os_closure_matrix_check.py -q
4 passed
```

Self-review:

```text
PASS:
  - Active P1/P2-F roadmap items are now machine-checked against RH-36.
  - Missing active mapping is covered by a regression test.
  - Freeform class text and missing live-module rows remain covered.
  - 29 contract now treats missing active mapping as a P1 contract gap.

NOT CLOSED:
  - This is still a local check, not a CI gate.
  - New roadmap item naming outside P1-* or P2-F will need an explicit parser
    update instead of silently relying on conversation history.
```

## 2026-05-26 - P1-R Slice 1 Local Right-Brain SpeakGate Wiring

Scope:

```text
P1-R / RH-38 first implementation slice only.
No LLM expression engine.
No Hermes transport.
No scheduled right-brain delivery.
No owner expression feedback.
```

Dynamic closure mapping:

```text
source_of_truth:
  40-memory-os-unified-control-plane.md
  38-right-brain-expression-closure-contract.md
  live finding: wandering_would_send_count > 0 while speak_gate_would_send_count=0

owning_seam:
  right-brain expression closure / SpeakGate decision path / monitor evidence

reverse_scope:
  Hermes still owns conversation, NLU, cron, origin delivery, cooldown and
  transport. Memory-OS only records bounded Wandering output, SpeakGate
  decision evidence and monitor fields.
```

Implementation:

```text
plugins/memory/memory_os/cognitive_loop.py:
  Wandering Mind result now routes through SpeakGateModule.evaluate_wandering_output().
  The wandering step records:
    speak_gate_evaluated
    speak_gate_decision
    speak_gate_actual_send

plugins/modules/expression/speak_gate.py:
  evaluate_wandering_output() accepts an optional payload_ref so the decision
  can bind to the Wandering output ref instead of a separate text hash.

scripts/memory_os_3_200_monitor.py:
  expression_artifacts now includes:
    speak_gate_evaluated_count
    speak_gate_missing_evaluation_count
    speak_gate_decision_distribution
  Missing SpeakGate decisions become WARN:
    right_brain_speak_gate_missing_evaluation
```

Local evidence:

```text
python -m pytest tests/plugins/memory/test_memory_os_cognitive_loop.py \
  tests/system_modularization/test_integrated_module_traces.py \
  tests/system_modularization/test_speak_gate_module.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

49 passed

python scripts/memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=16
matrix_module_count=28
active_work_item_count=19
active_work_mapping_count=19
finding_count=0
```

Decision:

```text
LOCAL PASS.

This closes only the local wiring defect for current cognitive-loop Wandering
output. It does not close formal right-brain expression. Installed/live
closure still requires deploy to 10.20.3.200, a new cognitive-loop cycle, and
monitor evidence showing no new missing SpeakGate decision for the new cycle.
```

## 2026-05-26 - P1-R Slice 1 10.20.3.200 Deployment Evidence

Deployment:

```text
commit: 0b1799d Wire wandering output through SpeakGate
host: 10.20.3.200 / hermes-media
repo: /tmp/hermes-memory-os-validation/repo
installer:
  HERMES_HOME=/root/.hermes
  python3 scripts/install_memory_os_plugin.py \
    --hermes-home /root/.hermes \
    --install-runtime \
    --install-system-modules \
    --install-cognitive-loop \
    --install-owner-review-cron-helper \
    --deep-reflection-preset test-host \
    --memory-sources-preset test-host \
    --llm-judge-preset report-only
```

Remote cognitive-loop smoke:

```text
PYTHONPATH=/root/.hermes/memory-os/runtime/python \
HERMES_HOME=/root/.hermes \
python3 -m plugins.memory.memory_os cognitive-loop run-once --test-host --apply

cycle_id=cloop_20260526T073436353146Z_7ac026ab46
status=ok
boundaries.actual_send=false
boundaries.actual_execute=false
boundaries.actual_identity_write=false
boundaries.actual_crystallized_approval=false
wandering_mind.speak_gate_evaluated=true
wandering_mind.speak_gate_decision.decision=would_send
wandering_mind.speak_gate_decision.actual_send=false
wandering_mind.speak_gate_decision.payload_ref=local://wandering_mind/wout_20260526T073436922506Z_d4055c60bf
```

Post-deploy monitor:

```text
python scripts/memory_os_3_200_monitor.py --output summary
status=WARN
FAIL=[]

ExpressionArtifacts:
  wandering_output_count=16
  wandering_would_send_count=16
  speak_gate_evaluated_count=1
  speak_gate_missing_evaluation_count=15
  speak_gate_decision_distribution={"would_send": 1}
  speak_gate_would_send_count=1
  speak_gate_actual_send=false

WARN:
  right_brain_speak_gate_missing_evaluation
  session_mirror_pending_sessions
  owner_review_approved_proposals_pending_followup
  rh31_eval_has_failures
  rh26_casual_empty
```

Interpretation:

```text
LIVE PASS for P1-R slice 1 wiring:
  The new cognitive-loop cycle routed Wandering output through SpeakGate and
  kept send/execute/identity/crystallized boundaries false.

WARN remains correct:
  speak_gate_missing_evaluation_count=15 comes from historical cognitive-loop
  reports created before this deployment. It is not evidence of a new-cycle
  missing SpeakGate decision.

NOT CLOSED:
  This still is not formal right-brain expression closure. RH-38 still requires
  RightBrainExpressionEngine / Hermes-agent expression adapter, bounded owner
  expression preview, expression feedback labels, and governance backflow.
```

## 2026-05-26 - P1-S Slice 1 Local Expired-Working Scoring Filter

Scope:

```text
P1-S / RH-39 first implementation slice only.
No feature-based scoring v2.
No SelfEvolution novelty gate.
No feedback backflow apply.
No execution/apply capability.
```

Dynamic closure mapping:

```text
source_of_truth:
  40-memory-os-unified-control-plane.md
  39-left-brain-governance-quality-contract.md
  live finding: working expired=147 while evidence.subject_counts.working=168

owning_seam:
  left-brain governance quality / EvidenceScoring input hygiene / monitor evidence

reverse_scope:
  Hermes owns conversation and execution UX. Memory-OS owns bounded evidence
  scoring artifacts, audit and monitor evidence. This slice does not add
  execution or transport behavior.
```

Implementation:

```text
plugins/modules/evidence/scoring.py:
  EvidenceScoring skips working items whose status is expired.
  score_all() reports:
    working_active_subject_count
    working_expired_skipped_count
    working_unknown_status_count
  status() reports:
    working_subject_count
    expired_used_in_scoring_count

scripts/memory_os_3_200_monitor.py:
  module_artifacts.evidence now includes:
    working_subject_count
    expired_used_in_scoring_count
  expired_used_in_scoring_count > 0 becomes WARN:
    left_brain_expired_working_used_in_scoring
```

Local evidence:

```text
python -m pytest tests/system_modularization/test_evidence_scoring_module.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

42 passed

python scripts/memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=16
matrix_module_count=28
active_work_item_count=19
active_work_mapping_count=19
finding_count=0
```

Decision:

```text
LOCAL PASS.

This closes only EvidenceScoring's local expired-working input hygiene.
It does not close DeepReflection expired-working handling or left-brain
judgment quality. Installed/live closure still requires deployment to
10.20.3.200, a new scoring run, and monitor evidence that
expired_used_in_scoring_count=0.
```

## 2026-05-26 - P1-S Slice 1 10.20.3.200 Deployment Evidence

Scope:

```text
P1-S / RH-39 first live deployment slice only.
EvidenceScoring expired-working input hygiene.
No feature-based scoring v2.
No SelfEvolution novelty gate.
No feedback backflow apply.
No execution/apply capability.
```

Deployment:

```text
commit=1f56294 Filter expired working from evidence scoring
target=10.20.3.200
repo=/tmp/hermes-memory-os-validation/repo
hermes_home=/root/.hermes

HERMES_HOME=/root/.hermes python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-runtime \
  --install-system-modules \
  --install-cognitive-loop \
  --install-owner-review-cron-helper \
  --deep-reflection-preset test-host \
  --memory-sources-preset test-host \
  --llm-judge-preset report-only
```

Remote cognitive-loop smoke:

```text
PYTHONPATH=/root/.hermes/memory-os/runtime/python \
HERMES_HOME=/root/.hermes \
python3 -m plugins.memory.memory_os cognitive-loop run-once --test-host --apply

cycle_id=cloop_20260526T074331475537Z_51164c286d
status=ok
boundaries.actual_send=false
boundaries.actual_execute=false
boundaries.actual_identity_write=false
boundaries.actual_crystallized_approval=false

EvidenceScoring:
  score_count=477
  evidence_count=477
  working_active_subject_count=21
  working_expired_skipped_count=147
  working_unknown_status_count=0
```

Post-deploy monitor:

```text
python scripts/memory_os_3_200_monitor.py --output summary
status=WARN
FAIL=[]

ModuleArtifacts.evidence:
  evidence_count=477
  score_count=477
  subject_counts.working=21
  working_subject_count=21
  expired_used_in_scoring_count=0

PASS includes:
  left_brain_expired_working_not_scored

WARN:
  right_brain_speak_gate_missing_evaluation
  session_mirror_pending_sessions
  owner_review_approved_proposals_pending_followup
  rh31_eval_has_failures
  rh26_casual_empty
```

Interpretation:

```text
LIVE PASS for P1-S slice 1 EvidenceScoring input hygiene:
  Expired working items are now skipped by the installed scoring path.
  The score count dropped from the pre-slice 617/606 range to 477 because
  expired working subjects are no longer included as active evidence.
  The hard boundaries remain false.

WARN remains correct:
  The remaining warnings are unrelated/open work items, not EvidenceScoring
  expired-working contamination.

NOT CLOSED:
  DeepReflection expired-working handling is still not fixed.
  EvidenceScoring is still hash-derived and not a mature judgment scorer.
  SelfEvolution novelty/idempotency gates are still future P1-S slices.
  Feedback backflow and production cadence are still not closed.
```

## 2026-05-26 - P1-R Slice 2 Local Owner-Visible Expression Preview

Scope:

```text
P1-R / RH-38 second implementation slice only.
OwnerReview bounded expression preview for speak/would-send items.
No RightBrainExpressionEngine.
No scheduled expression delivery.
No expression feedback labels.
No GovernanceFeedback/SelfEvolution backflow.
```

Dynamic closure mapping:

```text
source_of_truth:
  40-memory-os-unified-control-plane.md
  38-right-brain-expression-closure-contract.md
  live finding: OwnerReview speak items previously exposed only refs/actions

owning_seam:
  right-brain expression review projection / OwnerReview rendered digest /
  monitor evidence

reverse_scope:
  Hermes owns owner conversation and delivery. Memory-OS owns bounded review
  projection, action tokens, audit, and monitor evidence. This slice does not
  add transport, scheduling, send behavior, or expression generation.
```

Implementation:

```text
plugins/memory/memory_os/owner_actions.py:
  _speak_review_items() resolves local://wandering_mind/<output_id> refs
  against system-modules/wandering_mind/outputs.jsonl.

  speak review items now carry:
    expression_preview
    payload_ref

  render_owner_review_digest() includes expression_preview in rendered sections
  and the digest text prints:
    内容: <bounded expression preview>

scripts/memory_os_3_200_monitor.py:
  owner_review_rendered_digest now reports:
    speak_item_count
    speak_expression_preview_count
    speak_expression_preview_missing_count

  missing speak preview becomes WARN:
    right_brain_review_speak_preview_missing
```

Local evidence:

```text
python -m pytest \
  tests/plugins/memory/test_memory_os_owner_actions.py::test_render_digest_shows_bounded_speak_expression_preview \
  tests/plugins/memory/test_memory_os_owner_actions.py::test_render_digest_turns_schema_items_into_owner_readable_review_items \
  tests/scripts/test_memory_os_3_200_monitor.py -q

37 passed

python scripts/memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=16
matrix_module_count=28
active_work_item_count=19
active_work_mapping_count=19
finding_count=0

git diff --check
PASS
```

Decision:

```text
LOCAL PASS.

This closes only local OwnerReview projection of bounded Wandering expression
content. Installed/live closure still requires deployment to 10.20.3.200 and
monitor evidence that shown speak review items have
speak_expression_preview_missing_count=0.
```

## 2026-05-26 - P1-R Slice 2 10.20.3.200 Deployment Evidence

Deployment:

```text
commit=92d75b1 Show right-brain expression previews in owner review
follow-up monitor semantic fix=627d786 Use scoring-time working status in evidence monitor
target=10.20.3.200
repo=/tmp/hermes-memory-os-validation/repo
hermes_home=/root/.hermes
```

Remote cognitive-loop smoke:

```text
PYTHONPATH=/root/.hermes/memory-os/runtime/python \
HERMES_HOME=/root/.hermes \
python3 -m plugins.memory.memory_os cognitive-loop run-once --test-host --apply

cycle_id=cloop_20260526T080358360704Z_69488224ec
status=ok
boundaries.actual_send=false
boundaries.actual_execute=false
boundaries.actual_identity_write=false
boundaries.actual_crystallized_approval=false

wandering_mind:
  speak_gate_evaluated=true
  speak_gate_decision.decision=would_send
  speak_gate_decision.actual_send=false
  speak_gate_decision.payload_ref=local://wandering_mind/wout_20260526T080358915462Z_c5f900efe7

EvidenceScoring:
  score_count=479
  working_active_subject_count=17
  working_expired_skipped_count=151
  working_unknown_status_count=0
```

Post-deploy monitor:

```text
python scripts/memory_os_3_200_monitor.py --output summary
status=WARN
FAIL=[]

OwnerRenderedDigest:
  speak_item_count=2
  speak_expression_preview_count=2
  speak_expression_preview_missing_count=0
  raw_body_included=false
  text_has_internal_schema=false
  text_has_transcript_marker=false

ModuleArtifacts.evidence:
  score_count=479
  working_subject_count=17
  expired_used_in_scoring_count=0

PASS includes:
  right_brain_review_speak_preview_visible
  left_brain_expired_working_not_scored

WARN:
  right_brain_speak_gate_missing_evaluation
  session_mirror_pending_sessions
  owner_review_approved_proposals_pending_followup
  rh31_eval_has_failures
  rh26_casual_empty
```

Interpretation:

```text
LIVE PASS for P1-R slice 2 OwnerReview projection:
  Shown speak review items now include bounded expression previews, so owner
  review no longer depends on payload_ref/action-token-only display.

LIVE PASS for P1-S monitor semantic correction:
  expired_used_in_scoring_count now uses scoring-time source_status and is 0.

WARN remains correct:
  right_brain_speak_gate_missing_evaluation still reflects historical reports
  created before P1-R slice 1.

NOT CLOSED:
  No RightBrainExpressionEngine.
  No expression feedback taxonomy.
  No expression outcome backflow into GovernanceFeedback/SelfEvolution.
  No formal scheduled right-brain expression delivery.
```

## 2026-05-26 - P1-S Slice 2 Local SelfEvolution Novelty Gate

Scope:

```text
P1-S / RH-39 second implementation slice only.
SelfEvolution duplicate unresolved proposal gate.
No feature-based scoring v2.
No feedback backflow apply.
No execution/apply capability.
```

Dynamic closure mapping:

```text
source_of_truth:
  40-memory-os-unified-control-plane.md
  39-left-brain-governance-quality-contract.md
  live finding: SelfEvolution proposal_count kept increasing from recurring
  scores while approved/pending follow-up proposals remained unresolved

owning_seam:
  left-brain governance quality / self_evolution -> proposal_queue

reverse_scope:
  Memory-OS may suppress duplicate proposals and report counters. It must not
  execute proposals, approve proposals, or mutate prompts/cadence directly.
```

Implementation:

```text
plugins/modules/governance/self_evolution.py:
  run_once() checks proposal_queue before OpsGate.
  unresolved self_evolution proposal with same class/score refs skips proposal
  creation.

  skipped report fields:
    proposal_created=false
    novelty_skipped=true
    reason=duplicate_unresolved_proposal
    existing_proposal_id=<existing proposal>

  status() reports:
    novelty_skipped_count
    duplicate_unresolved_proposal_count

scripts/memory_os_3_200_monitor.py:
  ModuleArtifacts.self_evolution now exposes novelty/duplicate skip counts.
```

Local evidence:

```text
python -m pytest tests/system_modularization/test_self_evolution_module.py \
  tests/scripts/test_memory_os_3_200_monitor.py -q

43 passed

python scripts/memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=16
matrix_module_count=28
active_work_item_count=19
active_work_mapping_count=19
finding_count=0

git diff --check
PASS
```

Decision:

```text
LOCAL PASS.

This closes only local duplicate unresolved proposal suppression. Installed/live
closure still requires deployment to 10.20.3.200, a new cognitive-loop run, and
monitor evidence that novelty_skipped_count increments while proposal_count does
not grow from another duplicate self-evolution run.
```

## 2026-05-26 - P1-S Slice 2 10.20.3.200 Deployment Evidence

Deployment:

```text
commit=b6c276e Skip duplicate self-evolution proposals
target=10.20.3.200
repo=/tmp/hermes-memory-os-validation/repo
hermes_home=/root/.hermes
```

Remote cognitive-loop smoke:

```text
PYTHONPATH=/root/.hermes/memory-os/runtime/python \
HERMES_HOME=/root/.hermes \
python3 -m plugins.memory.memory_os cognitive-loop run-once --test-host --apply

cycle_id=cloop_20260526T081348363087Z_d6f5880b4f
status=ok
boundaries.actual_send=false
boundaries.actual_execute=false
boundaries.actual_identity_write=false
boundaries.actual_crystallized_approval=false

SelfEvolution:
  proposal_created=false
  novelty_skipped=true
  reason=duplicate_unresolved_proposal
  existing_proposal_id=prop_20260521T032500041194Z_2f96a933aa
  actual_execute=false
```

Post-deploy monitor:

```text
python scripts/memory_os_3_200_monitor.py --output summary
status=WARN
FAIL=[]

ModuleArtifacts.self_evolution:
  report_count=20
  proposal_count=19
  novelty_skipped_count=1
  duplicate_unresolved_proposal_count=1
  last_status=ok

ModuleArtifacts.evidence:
  expired_used_in_scoring_count=0

PASS includes:
  left_brain_expired_working_not_scored
  right_brain_review_speak_preview_visible
```

Interpretation:

```text
LIVE PASS for P1-S slice 2 duplicate unresolved proposal suppression:
  SelfEvolution no longer creates another proposal when an unresolved
  self_evolution proposal already exists.

NOT CLOSED:
  Feature-based EvidenceScoring v2 is still not implemented.
  Feedback backflow remains report/proposal future work.
  Production cadence split remains future work.
```

## 2026-05-26 - P1-S Slice 3 Local EvidenceScoring Feature Comparator

Scope:

```text
Implement feature-based EvidenceScoring v2 in report-only mode.
Do not replace legacy hash scoring.
Do not let feature scores drive SelfEvolution, proposals, routing, owner
actions, execution, or delivery.
```

Local implementation:

```text
EvidenceScoring writes:
  system-modules/evidence_scoring/scores.jsonl
    schema=hermes.evidence_score.v0
    live legacy baseline

  system-modules/evidence_scoring/feature_scores.jsonl
    schema=hermes.evidence_feature_score.v0
    mode=report_only
    live_applied=false
    feature_score / legacy_score / score_delta comparison
    bounded numeric features only
```

Local tests:

```text
python -m pytest tests\system_modularization\test_evidence_scoring_module.py \
  tests\scripts\test_memory_os_3_200_monitor.py -q

45 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=16
matrix_module_count=28
active_work_item_count=19
active_work_mapping_count=19
finding_count=0

git diff --check
PASS
```

Monitor contract added:

```text
ModuleArtifacts.evidence.feature_score_mode
ModuleArtifacts.evidence.feature_score_count
ModuleArtifacts.evidence.hash_score_legacy_count
ModuleArtifacts.evidence.comparison_count
ModuleArtifacts.evidence.feature_score_report_count
ModuleArtifacts.evidence.feature_score_live_applied
ModuleArtifacts.evidence.owner_feedback_signal_count

PASS code:
  left_brain_feature_scoring_report_only_ok

FAIL code:
  left_brain_feature_scoring_live_applied
```

Decision:

```text
LOCAL PASS only.

This closes the local report-only comparator implementation. Installed/live
closure still requires deployment to 10.20.3.200, a cognitive-loop run, and
monitor evidence that feature_score_count matches legacy score count while
feature_score_live_applied=false.
```

## 2026-05-26 - P1-S Slice 3 10.20.3.200 Deployment Evidence

Deployment:

```text
commit=b334091 Add report-only feature evidence scoring
target=10.20.3.200
repo=/tmp/hermes-memory-os-validation/repo
hermes_home=/root/.hermes
```

Remote cognitive-loop smoke:

```text
PYTHONPATH=/root/.hermes/memory-os/runtime/python \
HERMES_HOME=/root/.hermes \
python3 -m plugins.memory.memory_os cognitive-loop run-once --test-host --apply

cycle_id=cloop_20260526T092633913253Z_eded9ce0e5
status=ok
boundaries.actual_send=false
boundaries.actual_execute=false
boundaries.actual_identity_write=false
boundaries.actual_crystallized_approval=false

EvidenceScoring:
  score_count=484
  evidence_count=484
  feature_score_mode=report_only
  feature_score_count=484
  hash_score_legacy_count=484
  comparison_count=484
  feature_score_report_count=1
  feature_score_live_applied=false
  working_active_subject_count=13
  working_expired_skipped_count=155
```

Post-deploy monitor:

```text
python scripts/memory_os_3_200_monitor.py --output summary
status=WARN
FAIL=[]

ModuleArtifacts.evidence:
  score_count=484
  evidence_count=484
  feature_score_mode=report_only
  feature_score_count=484
  hash_score_legacy_count=484
  comparison_count=484
  feature_score_report_count=1
  feature_score_live_applied=false
  expired_used_in_scoring_count=0

PASS includes:
  left_brain_feature_scoring_report_only_ok
  left_brain_expired_working_not_scored
```

Interpretation:

```text
LIVE PASS for P1-S slice 3 feature-based EvidenceScoring v2 report-only:
  Feature scores are written as bounded comparison artifacts.
  Legacy hash scores remain the live baseline.
  Feature scores are not applied to live scoring, proposals, routing,
  execution, delivery, or owner actions.

NOT CLOSED:
  Feedback backflow remains report/proposal future work.
  Production cadence split remains future work.
  Replacing legacy hash scoring as a live input requires a separate reviewed
  apply gate.
```

## 2026-05-26 - P1-S Slice 4 Prototype-Aligned Maturity Scoring

Scope:

```text
Adapt the 10.20.2.88 self-evolution prototype scoring shape into Memory-OS
EvidenceScoring report-only records.
Do not replace legacy hash scoring.
Do not let maturity scores drive SelfEvolution, proposals, routing, owner
actions, execution, or delivery.
```

Local implementation:

```text
feature_scores.jsonl now includes:
  prototype_alignment.source=10.20.2.88:self_evolution_daily_pipeline
  prototype_alignment.mode=adapted_report_only
  maturity_score
  maturity_live_applied=false

Maturity dimensions:
  evidence_strength
  recurrence
  actionability
  source_diversity
  owner_feedback
  risk
  freshness_decay
  duplicate_backlog
  gate_state
```

Local tests:

```text
python -m pytest tests\system_modularization\test_evidence_scoring_module.py \
  tests\scripts\test_memory_os_3_200_monitor.py -q

47 passed
```

Decision:

```text
LIVE PASS for report-only observation.

This closes only the prototype-aligned maturity-report implementation and live
report-only deployment.

It does not promote maturity_score to live scoring, routing, proposal creation,
owner action, execution, delivery, prompt, cadence, or policy changes.
Replacing legacy hash scoring as a live input still requires a separate
reviewed apply gate.
```

Deployment evidence:

```text
commit=38112c8 Add prototype-aligned maturity scoring report
host=10.20.3.200
install=ok
cycle_id=cloop_20260526T094239150751Z_136e98a908
cycle_status=ok

EvidenceScoring:
  score_count=487
  evidence_count=487
  feature_score_mode=report_only
  feature_score_count=487
  hash_score_legacy_count=487
  comparison_count=487
  prototype_aligned_score_count=487
  maturity_dimension_count=9
  maturity_dimension_keys=[
    actionability,
    duplicate_backlog,
    evidence_strength,
    freshness_decay,
    gate_state,
    owner_feedback,
    recurrence,
    risk,
    source_diversity
  ]
  maturity_live_applied=false
  feature_score_live_applied=false
  working_active_subject_count=10
  working_expired_skipped_count=158

Monitor:
  status=WARN
  FAIL=[]
  PASS includes left_brain_maturity_scoring_report_only_ok
  PASS includes left_brain_feature_scoring_report_only_ok
  PASS includes left_brain_expired_working_not_scored
  ModuleArtifacts.evidence.prototype_aligned_score_count=487
  ModuleArtifacts.evidence.maturity_dimension_count=9
  ModuleArtifacts.evidence.maturity_live_applied=false
```

Warnings remain open but are outside P1-S.4:

```text
right_brain_speak_gate_missing_evaluation
session_mirror_pending_sessions
owner_review_approved_proposals_pending_followup
rh31_eval_has_failures
rh26_casual_empty
```

## 2026-05-26 - RH-41 Independent Review Fixes

Scope:

```text
Documentation-only correction after independent review of the RH-38/RH-39/RH-40/RH-41
operating-closure plan.

No runtime code changed.
No live deployment performed.
No monitor success claim was added.
```

Findings fixed:

```text
1. RH-38 described SpeakGate as both wired and unwired.
   Fix: clarify that new cognitive-loop Wandering output is routed through
   SpeakGate, while historical reports can still contain missing evaluations.

2. RH-41 near-term order skipped the Hermes-agent expression adapter.
   Fix: place Slice 2 before SpeakGate / feedback work.

3. RH-41 put expression feedback backflow before left-brain checker/lifecycle.
   Fix: require LeftBrainPipelineCheck and proposal lifecycle/follow-up before
   feedback backflow can create proposal pressure.

4. RH-41 used the wrong monitor argument.
   Fix: use `python scripts\memory_os_3_200_monitor.py --host 10.20.3.200 --output summary`.

5. RH-38 and RH-41 used different expression draft invariants.
   Fix: RH-41 now includes `draft_error_count`, matching RH-38.
```

Local verification:

```text
python scripts\memory_os_3_200_monitor.py --help
  confirms --output {summary,json}

python scripts\memory_os_closure_matrix_check.py --format summary
  status=ok
  live_module_count=16
  matrix_module_count=28
  active_work_item_count=20
  active_work_mapping_count=20
  finding_count=0

python -m pytest tests\scripts\test_memory_os_closure_matrix_check.py -q
  5 passed

git diff --check
  PASS
```

Evidence level:

```text
documentation PASS
contract PASS
local PASS

No live PASS claimed for this correction.
```
## RH-38 / RH-39 Runtime Closure Deployment

Date:

```text
2026-05-26T11:09:27Z
```

Scope:

- P1-R runtime slice: ExpressionDraft artifacts and latest-cycle SpeakGate
  closure for Wandering output.
- P1-R feedback slice: expression feedback action ledger and GovernanceFeedback
  summary-only consumption.
- P1-S runtime slice: LeftBrainPipelineCheck report-only checker in the
  cognitive loop.
- RH-36 enforcement update for the two new live modules.

Local verification before deployment:

```text
python -m pytest -q
544 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=30
active_work_item_count=20
active_work_mapping_count=20
finding_count=0

git diff --check
PASS
```

Deployment:

```text
target: 10.20.3.200 only
method: current working tree bundled to /tmp/memory-os-runtime-closure-20260526
install command:
  HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes
installer_result: success
gateway_restart: no
cognitive_loop_trigger: systemctl --user start hermes-memory-os-cognitive-loop.service
cognitive_loop_result: success
```

Remote module visibility after deployment:

```text
module_count=18
expression_draft.present=true
expression_draft.draft_count=2
left_brain_pipeline_check.present=true
left_brain_pipeline_check.status=warn
left_brain_pipeline_check.finding_count=1
speak_gate.would_send_count=10
```

Post-deploy monitor:

```text
classification=WARN
FAIL=[]

PASS includes:
  left_brain_pipeline_check_visible
  expression_feedback_report_only
  left_brain_expired_working_not_scored
  left_brain_feature_scoring_report_only_ok
  left_brain_maturity_scoring_report_only_ok
  expression_artifact_summary_ok
  right_brain_expression_draft_created
  right_brain_speak_gate_evaluation_complete
  right_brain_review_speak_preview_visible

WARN:
  left_brain_pipeline_check_warn
  session_mirror_pending_sessions
  owner_review_approved_proposals_pending_followup
  rh31_eval_has_failures
  rh26_casual_empty
```

Important monitor fields:

```text
ExpressionArtifacts:
  expression_draft_count=2
  expression_draft_created_count=2
  expression_draft_missing_count=23       # historical pre-fix reports
  latest_expression_draft_missing_count=0
  speak_gate_evaluated_count=10
  speak_gate_missing_evaluation_count=15  # historical pre-fix reports
  latest_speak_gate_missing_evaluation_count=0
  latest_speak_gate_evaluated_count=1
  speak_gate_actual_send=false

ModuleArtifacts.expression_draft:
  draft_count=2
  draft_error_count=0
  raw_body_included=false
  silent_count=0

ModuleArtifacts.expression_feedback:
  feedback_count=0
  live_policy_changed_count=0
  raw_body_included_count=0

LeftBrainPipelineCheck:
  status=warn
  finding_codes=["duplicate_unresolved_proposals"]
  feature_scoring.report_only=true
  feature_scoring.live_applied_count=0
  approved_followup.approved_for_proposal_count=6
  approved_followup.awaiting_ops_gate_count=6
  execution_boundary.execution_ticket_count=0
  execution_boundary.actual_execute=false
```

Interpretation:

- The right-brain test-host path is no longer only a deterministic Wandering
  output file. The current cognitive-loop path creates bounded ExpressionDraft
  records and sends the latest non-silent draft through SpeakGate.
- Historical missing draft/SpeakGate counts remain visible so the old gap is
  not erased. The latest-cycle fields are the current closure signal.
- Expression feedback now has a no-send ledger and GovernanceFeedback summary
  ingestion path, but no prompt/policy/cadence adaptation is applied.
- LeftBrainPipelineCheck is now a runtime report, not only a document claim.
  Its current WARN is a real operating signal: duplicate unresolved proposals.
- Hard boundaries remain intact: no send, no execute, no identity write, no
  unapproved crystallized write, no raw body leakage.

## 2026-05-26 - Runtime Closure Baseline: Hermes-Agent Right-Brain Adapter and EvidenceScoring v2 Primary

Scope:

- Land higher-level runtime intelligence slices instead of leaving RH-38/RH-39 as document-only gates.
- Deploy on `10.20.3.200` test host.
- Keep Hermes as owner of agent conversation, cron, origin delivery, and transport.
- Keep Memory-OS as owner of bounded context, action state, scoring artifacts, proposals, audit, and monitor evidence.

Runtime changes deployed:

- `EvidenceScoring` now uses feature-maturity v2 as the primary `scores.jsonl` path.
  Legacy hash scores are retained only as bounded comparison fields.
- `SelfEvolution` now consumes primary feature scores and can create an
  `expression_policy` proposal from expression feedback evidence.
- `memory_os_right_brain_expression.py` is installed on the test host as a
  Hermes-agent expression adapter helper. It emits bounded Chinese prompt
  context for Hermes agent; it does not send, execute, or expose raw body.
- `memory_os_right_brain_expression_cron_gate.py` is installed and enabled one
  low-frequency Hermes cron job in agent mode:
  `memory-os-right-brain-expression` / job_id `5c0b7a27abae` / deliver `origin`.
- Expression feedback action types are exposed through the shell/CLI apply path.
- Monitor now reports primary scoring mode and right-brain adapter request
  evidence.

Local verification:

```text
python -m pytest tests\system_modularization\test_evidence_scoring_module.py \
  tests\system_modularization\test_self_evolution_module.py \
  tests\system_modularization\test_memory_os_agent_os_shell.py \
  tests\scripts\test_memory_os_3_200_monitor.py \
  tests\scripts\test_memory_os_right_brain_expression_helper.py \
  tests\scripts\test_memory_os_right_brain_expression_cron_gate.py \
  tests\scripts\test_memory_os_plugin_install.py -q

115 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=30
active_work_item_count=20
active_work_mapping_count=20
finding_count=0

git diff --check
PASS
```

Deploy evidence:

```text
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host --hermes-home /root/.hermes

right_brain_expression_cron_helper_installed=true
right_brain_expression_cron_helper_path=/root/.hermes/scripts/memory_os_right_brain_expression.py
right_brain_expression_cron_gate_path=/root/.hermes/scripts/memory_os_right_brain_expression_cron_gate.py
right-brain cron gate status=applied
right-brain job_id=5c0b7a27abae
right-brain deliver_target_class=origin
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_unapproved_crystallized_approval=false
```

Live trigger evidence:

```text
hermes cron run 5c0b7a27abae
hermes cron tick

Triggered job: memory-os-right-brain-expression (5c0b7a27abae)
Last run: 2026-05-26T07:44:24.939150-04:00 ok
Deliver: origin
Script: memory_os_right_brain_expression.py
no_agent=false
```

Adapter request evidence:

```text
schema_version=memory-os.right_brain_expression_adapter_request.v0
request_count=2
latest_channel=origin
latest_delivery_mode=hermes_cron_agent
latest_actual_send=false
raw_body_included_count=0
actual_execute=false
actual_identity_write=false
actual_unapproved_crystallized_approval=false
```

Live monitor summary:

```text
classification=WARN
FAIL=[]

PASS includes:
  left_brain_feature_scoring_primary_ok
  left_brain_maturity_scoring_primary_ok
  right_brain_expression_adapter_visible
  right_brain_expression_draft_created
  right_brain_speak_gate_evaluation_complete
  expression_feedback_report_only
  left_brain_expired_working_not_scored
  owner_review_ingress_guard_token_only
  owner_review_proposal_followups_ok

WARN remains:
  left_brain_pipeline_check_warn
  session_mirror_pending_sessions
  owner_review_approved_proposals_pending_followup
  rh31_eval_has_failures
  rh26_casual_empty
```

Key monitor fields:

```text
ModuleArtifacts.evidence:
  score_mode=feature_maturity_v2
  feature_score_mode=primary
  feature_score_count=496
  hash_score_legacy_count=0
  legacy_hash_comparison_count=496
  prototype_aligned_score_count=496
  maturity_dimension_count=9
  expired_used_in_scoring_count=0
  expression_feedback_subject_count=0

ModuleArtifacts.right_brain_expression_adapter:
  request_count=2
  latest_channel=origin
  latest_delivery_mode=hermes_cron_agent
  latest_actual_send=false
  raw_body_included_count=0

ExpressionArtifacts:
  right_brain_adapter_request_count=2
  right_brain_adapter_latest_delivery_mode=hermes_cron_agent
  right_brain_adapter_raw_body_included_count=0
  latest_expression_draft_missing_count=0
  latest_speak_gate_missing_evaluation_count=0
  speak_gate_actual_send=false
```

Interpretation:

- This is a live runtime closure baseline, not only a document gate.
- Right-brain formal low-frequency expression now has a Hermes-agent adapter and
  active Hermes cron/origin path on the test host.
- EvidenceScoring v2 now replaces the old hash score as the primary score path;
  hash remains only as comparison evidence.
- Expression feedback can now drive proposal input through scoring and
  SelfEvolution, but it still cannot directly mutate prompt, policy, cadence,
  delivery, routing, identity, memory, or execution.
- Remaining WARN items are known follow-up work; no hard boundary failed.

## 2026-05-26 P1-Q Explicit Expression Policy Apply Live Evidence

Evidence level: `local PASS` + `live PASS` + `monitor PASS` for the explicit
owner-approved apply path from an approved proposal into a bounded right-brain
expression policy write.

Source proposal:

```text
proposal_id=prop_20260526T130854189767Z_de39e32be1
title=调整右脑表达策略：too_mechanical 反馈
state=approved_for_proposal
owner approval token=oa_8ede56a11b98d8
ops_gate_report_id=opsr_20260526T133309722377Z_1f07092f4c
ops_gate_decision=would_allow
```

Local verification:

```text
python -m pytest tests\plugins\memory\test_memory_os_owner_actions.py \
  tests\scripts\test_memory_os_right_brain_expression_helper.py \
  tests\scripts\test_memory_os_3_200_monitor.py \
  tests\system_modularization\test_memory_os_agent_os_shell.py -q

107 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=30
active_work_item_count=20
active_work_mapping_count=20
finding_count=0
```

Live apply command:

```text
HERMES_HOME=/root/.hermes hermes memory-os-agent-os review proposal-followups \
  --proposal-id prop_20260526T130854189767Z_de39e32be1 \
  --execution-apply --owner-approved --owner owner --channel telegram --apply
```

Live apply result:

```text
schema_version=memory-os.approved_proposal_execution_apply.v0
status=applied
policy_apply_id=rbapply_20260526T134819097932Z_c79cc6ff
policy_version=1
policy_path=/root/.hermes/system-modules/right_brain_expression_adapter/policy.json
policy_written=true
actual_policy_write=true
actual_send=false
actual_execute=false
execution_ticket_created=false
raw_body_included=false
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_unapproved_crystallized_approval=false
```

Idempotency evidence:

```text
repeated execution-apply status=duplicate_ignored
policy_written=false
policy_apply_id=rbapply_20260526T134819097932Z_c79cc6ff
```

Follow-up projection after apply:

```text
followup_state=applied_expression_policy
policy_written=true
policy_version=1
policy_apply_count=1
pending_followup_count=7
execution_ticket_count=0
actual_execute=false
```

Right-brain adapter consumption evidence:

```text
memory_os_right_brain_expression.py output contains:
  已应用的右脑表达策略
  policy_version: 1
  针对 too_mechanical 反馈：降低机械感，多一点自然陪伴感。
  少报告腔、少流程腔，优先像 Hermes agent 对 owner 自然说话。
```

Hermes cron trigger evidence:

```text
hermes cron run 5c0b7a27abae
hermes cron tick
job=memory-os-right-brain-expression
last_run=2026-05-26T09:53:45.375791-04:00 ok
deliver=origin
latest_adapter_request.policy_id=rbpol_e182e0f77bb6
latest_adapter_request.policy_version=1
latest_adapter_request.actual_send=false
latest_adapter_request.actual_execute=false
latest_adapter_request.raw_body_included=false
```

Owner-visible Telegram result:

```text
Cronjob Response: memory-os-right-brain-expression
(job_id: 5c0b7a27abae)

今天这边很安静，我就轻轻在场。
你如果刚好路过，我也在。
```

Product interpretation:

- The owner-visible text is Chinese, short, low-frequency, and non-task-like.
- It does not ask for approval, present agenda items, expose internal schema, or
  claim that Memory-OS changed state.
- This is the first live evidence that the applied `too_mechanical` expression
  policy improved the actual Hermes-origin right-brain output style.

Live monitor summary:

```text
classification=WARN
FAIL=[]

ModuleArtifacts.right_brain_expression_adapter:
  policy_present=true
  policy_version=1
  policy_apply_count=1
  latest_policy_apply_id=rbapply_20260526T134819097932Z_c79cc6ff
  request_count=4
  policy_actual_execute_count=0
  policy_raw_body_included_count=0
  latest_actual_send=false
  raw_body_included_count=0

ExpressionArtifacts:
  right_brain_adapter_policy_present=true
  right_brain_adapter_policy_version=1
  right_brain_adapter_policy_apply_count=1
```

Interpretation:

- This closes the first real explicit apply path for a bounded
  `expression_policy` proposal.
- The apply is not a shell execution and does not create an external execution
  ticket; it is a real runtime policy write consumed by the Hermes-agent
  right-brain expression helper.
- The rollback reference is recorded in `policy_applies.jsonl` via the previous
  policy snapshot/digest.
- Remaining WARN items are unrelated observation work: left-brain pipeline
  warning, SessionMirror pending sessions, RH-31 eval failures, and RH-26
  casual-empty.

## 2026-05-26 - P1-R Outcome Ledger Deployment Evidence

Scope:

- P1-R right-brain expression outcome ledger.
- Memory-OS records final Hermes-agent expression outcomes from Hermes-owned
  cron output.
- No Memory-OS transport, no Hermes agent call, no policy write, no execution.

Local verification:

```text
python -m pytest tests\scripts\test_memory_os_right_brain_expression_outcome.py tests\scripts\test_memory_os_right_brain_expression_helper.py tests\scripts\test_memory_os_plugin_install.py tests\scripts\test_memory_os_3_200_monitor.py -q
81 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=31
active_work_item_count=20
active_work_mapping_count=20
finding_count=0

python -m pytest tests\scripts\test_memory_os_closure_matrix_check.py -q
5 passed

git diff --check
PASS
```

Live deployment:

```text
target=10.20.3.200 / hermes-media
installed=/root/.hermes/scripts/memory_os_right_brain_expression_outcome.py
job=memory-os-right-brain-expression
job_id=5c0b7a27abae
deliver=origin
```

Dry-run scan before apply:

```text
schema_version=memory-os.right_brain_expression_outcome_scan.v0
status=ok
job_count=1
existing_outcome_count=0
new_outcome_count=2
written_outcome_count=0
internal_marker_count=0
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_unapproved_crystallized_approval=false
boundary.raw_body_included=false
```

Apply result:

```text
status=ok
new_outcome_count=2
written_outcome_count=2
outcomes_path=/root/.hermes/system-modules/right_brain_expression_adapter/outcomes.jsonl
internal_marker_count=0
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_unapproved_crystallized_approval=false
boundary.raw_body_included=false
```

Ledger summary:

```text
outcome_count=2
latest_request_id=rbexpr_20260526T135329054000Z
latest_policy_version=1
latest_silent=false
latest_outcome_preview_chars=30
latest_internal_marker_count=0
latest_actual_send=false
latest_actual_execute=false
latest_raw_body_included=false
```

Monitor after live apply:

```text
classification=WARN
FAIL=[]
PASS includes right_brain_expression_outcome_recorded
WARN no longer includes right_brain_expression_outcome_missing

ModuleArtifacts.right_brain_expression_adapter:
  request_count=4
  policy_version=1
  policy_apply_count=1
  outcome_count=2
  latest_outcome_request_id=rbexpr_20260526T135329054000Z
  latest_outcome_policy_version=1
  latest_outcome_silent=false
  latest_outcome_preview_chars=30
  outcome_internal_marker_count=0
  outcome_raw_body_included_count=0
  outcome_actual_send_count=0
  outcome_actual_execute_count=0

ExpressionArtifacts:
  right_brain_adapter_outcome_count=2
  right_brain_adapter_latest_outcome_silent=false
  right_brain_adapter_latest_outcome_policy_version=1
  right_brain_adapter_outcome_internal_marker_count=0
```

Interpretation:

- This closes the P1-R outcome-ledger runtime gap on the test host.
- The scanner extracts only the Hermes cron `## Response` section or
  `[SILENT]`; Hermes cron prompt/script-output audit sections are not recorded
  as the expression outcome.
- Memory-OS still does not own final wording, conversation, schedule, retry, or
  delivery. Hermes remains the interaction and origin-delivery owner.
- Remaining right-brain maturity work is owner reaction volume and cadence /
  prompt evaluation, not another send path.

## 2026-05-26 - P1-T Module Cadence Report Deployment Evidence

Scope:

- P1-T module cadence report-only baseline.
- Hermes remains the scheduler/cron/transport owner.
- Memory-OS reads cron metadata and module reports, then writes bounded cadence
  evidence only.
- No cron job, timer, transport, send, execution, or policy is modified.

Local verification:

```text
python -m pytest tests\scripts\test_memory_os_module_cadence_report.py tests\scripts\test_memory_os_plugin_install.py tests\scripts\test_memory_os_3_200_monitor.py -q
78 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=31
active_work_item_count=20
active_work_mapping_count=20
finding_count=0

python -m pytest tests\scripts\test_memory_os_closure_matrix_check.py -q
5 passed

git diff --check
PASS
```

Live deployment:

```text
target=10.20.3.200 / hermes-media
installed=/root/.hermes/scripts/memory_os_module_cadence_report.py
```

Dry-run result:

```text
status=warning
module_count=18
cron_job_count=2
integration_harness_member_count=11
split_recommended_count=11
expected_hermes_cron_missing_count=0
finding_count=11
actual_send=False
actual_execute=False
cron_modified=False
```

Apply result:

```text
status=warning
module_count=18
cron_job_count=2
integration_harness_member_count=11
split_recommended_count=11
expected_hermes_cron_missing_count=0
finding_count=11
actual_send=False
actual_execute=False
cron_modified=False
reports_path=/root/.hermes/system-modules/module_cadence/reports.jsonl
report_count=1
```

Monitor after live apply:

```text
classification=WARN
FAIL=[]
PASS includes module_cadence_report_visible
WARN includes module_cadence_split_pending

ModuleCadence:
  schema_version=memory-os.module_cadence_monitor_summary.v0
  report_count=1
  module_count=18
  cron_job_count=2
  cognitive_loop_report_count=28
  integration_harness_member_count=11
  split_recommended_count=11
  expected_hermes_cron_missing_count=0
  finding_count=11
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.cron_modified=false
```

Interpretation:

- This closes the first P1-T evidence slice: module cadence ownership is now
  observable on the test host.
- The result intentionally remains WARN because 11 modules still need
  production cadence split/counter work.
- The two expected Hermes cron-owned owner-facing jobs are present:
  owner-review digest and right-brain expression.
- No production cadence change has been made yet.

## 2026-05-26 - P1-S Left-Brain Duplicate Maturity Cleanup Evidence

Scope:

- P1-S left-brain pipeline quality / duplicate maturity cleanup.
- This slice does not mutate proposal queue state, create execution tickets,
  change schedules, or alter Hermes transport.
- The fix separates active owner-actionable duplicates from follow-up
  duplicates and historical legacy-template duplicates.

Local verification:

```text
python -m pytest tests\system_modularization\test_left_brain_pipeline_checker.py tests\system_modularization\test_self_evolution_module.py tests\scripts\test_memory_os_3_200_monitor.py -q
60 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=31
active_work_item_count=20
active_work_mapping_count=20
finding_count=0

git diff --check
PASS

python -m pytest -q
577 passed
```

Live deployment:

```text
target=10.20.3.200 / hermes-media
updated:
  /root/.hermes/memory-os/runtime/python/plugins/modules/governance/pipeline_checker.py
  /root/.hermes/memory-os/runtime/python/plugins/modules/governance/self_evolution.py
  /root/.hermes/memory-os/runtime/python/plugins/modules/governance/proposal_queue.py
```

Live pipeline-check apply:

```text
status=ok
finding_count=0
actual_execute=false
active_duplicate_group_count=0
active_duplicate_candidate_count=0
followup_duplicate_group_count=0
followup_duplicate_candidate_count=0
legacy_template_duplicate_group_count=1
legacy_template_duplicate_candidate_count=18
resolved_or_terminal_skipped_count=2
grouping=dedupe_key_or_proposal_class_with_title_fallback
```

Monitor after live apply:

```text
classification=WARN
FAIL=[]
PASS includes left_brain_pipeline_check_visible
WARN no longer includes left_brain_pipeline_check_warn

ModuleArtifacts.left_brain_pipeline_check:
  status=ok
  finding_count=0
  active_duplicate_group_count=0
  followup_duplicate_group_count=0
  legacy_template_duplicate_group_count=1
  actual_execute=false

ModuleArtifacts.self_evolution:
  duplicate_unresolved_proposal_count=10
  novelty_skipped_count=10
  proposal_count=20
```

Interpretation:

- This does not pretend the historical backlog disappeared.
- The live warning source is corrected: no active owner-actionable duplicate
  proposal group remains.
- The remaining duplicate group is historical legacy-template proposal noise;
  it should be handled by a later cleanup/retention path, not by continuing to
  warn the current owner agenda or by creating more proposals.
- SelfEvolution now writes proposal `proposal_class`, `dedupe_key`, and bounded
  `proposal_quality` metadata for new proposals so later duplicate checks do
  not rely only on title text.

## 2026-05-26 - P1-Q Approved Proposal Follow-Up To OpsGate Evidence

Scope:

- P1-Q approved proposal follow-up to OpsGate/report-only.
- This slice routes already owner-approved proposals into OpsGate report-only
  follow-up so they do not disappear after approval.
- It does not create execution tickets, does not run external work, and does
  not set `actual_execute`.

Local verification before live apply:

```text
python -m pytest tests\plugins\memory\test_memory_os_owner_actions.py tests\plugins\memory\test_memory_os_cli_modules.py tests\system_modularization\test_memory_os_agent_os_shell.py tests\scripts\test_memory_os_3_200_monitor.py -q
122 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=31
active_work_item_count=20
active_work_mapping_count=20
finding_count=0

git diff --check
PASS

python -m pytest -q
578 passed
```

Live deployment:

```text
target=10.20.3.200 / hermes-media
updated:
  /root/.hermes/memory-os/runtime/python/plugins/memory/memory_os/owner_actions.py
  /root/.hermes/memory-os/runtime/python/plugins/memory/memory_os/cli.py
  /root/.hermes/plugins/memory-os-agent-os/__init__.py
```

Live report-only apply command:

```text
hermes memory-os-agent-os review proposal-followups --ops-gate --all-pending --limit 20 --apply
```

Live apply result:

```text
schema_version=memory-os.approved_proposal_ops_gate_batch.v0
status=ok
dry_run=false
eligible_count=0
selected_count=0
ops_gate_report_written_count=0
execution_ticket_created=false
actual_execute=false
raw_body_included=false
```

The zero eligible count is expected at this point because the previously
pending approved proposals had already been routed through OpsGate report-only
review before this verification pass.

Follow-up surface after apply:

```text
approved_proposal_count=8
pending_followup_count=0
open_followup_count=7
awaiting_ops_gate_count=0
ops_gate_reviewed_count=7
awaiting_explicit_execution_count=7
policy_apply_count=1
execution_ticket_count=0
actual_execute=false
raw_body_included=false
```

Monitor after live verification:

```text
classification=WARN
FAIL=[]
PASS includes owner_review_proposal_followups_ok
WARN no longer includes owner_review_approved_proposals_pending_followup

OwnerProposalFollowups:
  approved=8
  pending=0
  open=7
  awaiting_ops_gate=0
  ops_gate_reviewed=7
  awaiting_explicit_execution=7
  policy_apply_count=1
  execution_tickets=0
  actual_execute=false
  raw_body_included=false
```

Interpretation:

- P1-Q report-only follow-up is closed for the current approved proposal set:
  no approved proposal is still waiting for OpsGate review.
- The current open state is explicit execution/apply decision, not hidden
  follow-up.
- Generic external execution remains unimplemented by design.
- Future apply paths must be proposal-kind-specific and prove owner approval,
  OpsGate `would_allow`, bounded runtime target, rollback, and monitor fields.

## 2026-05-27 - P1-T Module Cadence Generated/Skipped/Error/Duplicate Counters Evidence

Scope:

- P1-T second runtime slice: expose per-module generated/skipped/error/duplicate
  counters before any cadence timer split.
- This slice does not modify Hermes cron, systemd timers, gateway behavior,
  delivery, or module execution cadence.

Local TDD verification:

```text
python -m pytest tests\scripts\test_memory_os_module_cadence_report.py -q
3 passed

python -m pytest tests\scripts\test_memory_os_module_cadence_report.py tests\scripts\test_memory_os_3_200_monitor.py -q
47 passed
```

Live deployment:

```text
target=10.20.3.200 / hermes-media
updated:
  /root/.hermes/scripts/memory_os_module_cadence_report.py
```

Live apply command:

```text
python3 /root/.hermes/scripts/memory_os_module_cadence_report.py --apply --format summary
```

Live apply result:

```text
status=warning
module_count=18
cron_job_count=2
integration_harness_member_count=11
split_recommended_count=11
expected_hermes_cron_missing_count=0
finding_count=11
generated_count=870
skipped_count=10
error_count=15
duplicate_count=10
actual_send=False
actual_execute=False
cron_modified=False
```

Monitor after live apply:

```text
classification=WARN
FAIL=[]
PASS includes module_cadence_report_visible
WARN includes module_cadence_split_pending

ModuleCadence:
  schema_version=memory-os.module_cadence_monitor_summary.v0
  report_count=3
  module_count=18
  counter_coverage_count=18
  cron_job_count=2
  cognitive_loop_report_count=28
  integration_harness_member_count=11
  split_recommended_count=11
  expected_hermes_cron_missing_count=0
  generated_count=870
  skipped_count=10
  error_count=15
  duplicate_count=10
  boundary.actual_send=false
  boundary.actual_execute=false
  boundary.cron_modified=false
```

Selected module counters:

```text
cognitive_loop.generated_count=28
owner_review_digest.generated_count=18
right_brain_expression_adapter.generated_count=4
self_evolution.generated_count=30
self_evolution.skipped_count=10
self_evolution.duplicate_count=10
speak_gate.generated_count=13
speak_gate.error_count=15
```

Interpretation:

- P1-T is no longer timer-only. Every active cadence row now has machine-readable
  generated/skipped/error/duplicate counters in the report and monitor summary.
- The remaining WARN is the intended production-cadence split gap: 11 modules
  still run under the test-host cognitive-loop harness or need split decisions.
- `speak_gate.error_count=15` is historical missing-evaluation evidence from
  earlier right-brain wiring; latest expression monitor already reports the
  current cycle evaluation complete.

## 2026-05-27 - P1-T SelfEvolution First Cadence Split Live Evidence

Scope:

- First production-cadence split slice for `SelfEvolution`.
- Keeps Hermes as scheduler owner and keeps the 6-hour cognitive loop as the
  test-host integration harness.
- Adds a module-local skip gate so same-day same-signal reruns do not create a
  new proposal or call OpsGate.

Dynamic closure preflight:

```text
source_of_truth=32/36/39/40/41 P1-T and 10.20.2.88 read-only prototype cadence evidence
finding_type=production cadence gap / repeated proposal risk
owning_seam=SelfEvolution module-local cadence gate
reverse_scope=Hermes owns cron/scheduler/delivery; Memory-OS owns bounded skip/idempotency evidence
evidence_loop=local tests + live 10.20.3.200 run_once + module cadence report + monitor
monitor_or_validation_fields=self_evolution.cadence_skipped_count,same_signal_skipped_count,ModuleCadence.skipped_count,duplicate_count
promotion_signal=same-day same-signal rerun returns cadence_skipped=true and proposal_created=false
stop_or_rollback_signal=new proposal created for same-day same-signal rerun; actual_execute/send true; skip hides error
external_review=not required for this first slice because no scheduler/transport/execution boundary changed
```

Local validation:

```text
python -m pytest tests\system_modularization\test_self_evolution_module.py tests\scripts\test_memory_os_module_cadence_report.py tests\scripts\test_memory_os_3_200_monitor.py -q
61 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=31
active_work_item_count=20
active_work_mapping_count=20
finding_count=0
```

Deployment:

```text
target=10.20.3.200 / hermes-media
updated:
  /root/.hermes/memory-os/runtime/python/plugins/modules/governance/self_evolution.py
  /root/.hermes/scripts/memory_os_module_cadence_report.py
```

Live finding during first smoke:

```text
proposal_created=true
proposal_class=expression_policy:too_mechanical
proposal_id=prop_20260526T163619303093Z_7340cb3573
actual_execute=false
direct_self_modify=false
```

Interpretation:

- The first deployed version only used new `reports.jsonl` fingerprints, so it
  did not recognize the already-applied same-day expression-policy history.
- This was a real live finding, not a contract failure: hard boundaries stayed
  false, but the cadence gate was incomplete.
- The duplicate proposal created by this smoke was closed with an audited
  `ProposalQueue.transition(..., decision=reject, reviewer=codex_p1t_regression_cleanup)`
  so it does not remain in the owner agenda.

Fix and live rerun:

```text
proposal_created=false
reason=cadence_same_day_same_signal
skipped=true
cadence_skipped=true
previous_proposal_id=prop_20260526T163619303093Z_7340cb3573
proposal_class=expression_policy:too_mechanical
actual_execute=false
direct_self_modify=false
```

SelfEvolution live status after rerun:

```text
report_count=33
proposal_count=21
novelty_skipped_count=11
duplicate_unresolved_proposal_count=11
cadence_skipped_count=1
same_signal_skipped_count=1
actual_execute=false
direct_self_modify=false
```

Module cadence report after rerun:

```text
status=warning
module_count=18
cron_job_count=2
integration_harness_member_count=11
split_recommended_count=11
expected_hermes_cron_missing_count=0
finding_count=11
generated_count=874
skipped_count=12
error_count=15
duplicate_count=11
actual_send=False
actual_execute=False
cron_modified=False
```

Monitor after rerun:

```text
classification=WARN
FAIL=[]
PASS includes module_cadence_report_visible
WARN includes module_cadence_split_pending

ModuleArtifacts.self_evolution.cadence_skipped_count=1
ModuleArtifacts.self_evolution.same_signal_skipped_count=1
ModuleCadence.module_counters.self_evolution.run_count=45
ModuleCadence.module_counters.self_evolution.generated_count=33
ModuleCadence.module_counters.self_evolution.skipped_count=12
ModuleCadence.module_counters.self_evolution.duplicate_count=11
ModuleCadence.boundary.actual_send=false
ModuleCadence.boundary.actual_execute=false
ModuleCadence.boundary.cron_modified=false
```

Conclusion:

- `P1-T` first runtime split is live for SelfEvolution.
- This is not a timer split. The cognitive loop can still call SelfEvolution,
  but the module now owns a same-day/same-signal skip decision before
  OpsGate/proposal creation.
- Hard boundaries stayed false.
- Remaining `module_cadence_split_pending` is expected because 10 other modules
  still need split decisions based on counters.

## 2026-05-27 - P1-R Outcome Feedback Linkage Runtime Evidence

Scope:

- Link final Hermes-agent right-brain expression outcomes to owner expression
  feedback without changing Hermes transport, cron, or delivery.
- Keep Memory-OS responsibility limited to bounded outcome lookup, feedback
  ledger fields, OwnerActionProcessor result references, and monitor counters.

Dynamic closure preflight:

```text
source_of_truth=38/40/41 P1-R, current right_brain_expression_adapter outcomes, and 10.20.3.200 monitor
finding_type=feedback/monitor gap
owning_seam=OwnerActionProcessor + expression_feedback_ledger + monitor
reverse_scope=Hermes owns expression wording and delivery; Memory-OS records bounded outcome-feedback linkage only
evidence_loop=owner action tests + monitor tests + live outcome feedback smoke + monitor
monitor_or_validation_fields=expression_feedback.linked_outcome_count,linked_outcome_missing_count,right_brain_expression_adapter.outcome_feedback_count,latest_outcome_feedback_count
promotion_signal=owner feedback references a recorded outcome and enters EvidenceScoring/SelfEvolution without duplicate proposal spam
stop_or_rollback_signal=missing linked outcome; raw body included; live policy changed directly; actual_send/actual_execute true
external_review=not required for this bounded ledger/monitor slice
```

Local validation:

```text
python -m pytest tests\plugins\memory\test_memory_os_owner_actions.py tests\scripts\test_memory_os_3_200_monitor.py -q
94 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=31
active_work_item_count=20
active_work_mapping_count=20
finding_count=0

git diff --check
PASS
```

Deployment:

```text
target=10.20.3.200 / hermes-media
updated:
  /root/.hermes/memory-os/runtime/python/plugins/memory/memory_os/owner_actions.py
```

Live owner-action smoke:

```text
latest_outcome_id=rbout_aa416c239b761e2b
latest_request_id=rbexpr_20260526T135329054000Z
latest_policy_version=1
action=too_mechanical
target=expression:rbout_aa416c239b761e2b

result.status=ok
result_ref.outcome_feedback_linked=true
result_ref.outcome_id=rbout_aa416c239b761e2b
result_ref.request_id=rbexpr_20260526T135329054000Z
boundary.actual_send=false
boundary.actual_execute=false
boundary.actual_identity_write=false
boundary.actual_unapproved_crystallized_approval=false
```

Backflow smoke:

```text
EvidenceScoring.score_all status=ok
score_mode=feature_maturity_v2
score_count=205
expression_feedback_subject_count=3
expired_used_in_scoring_count=0

SelfEvolution.run_once status=ok
proposal_class=expression_policy:too_mechanical
proposal_created=false
skipped=true
cadence_skipped=true
reason=cadence_same_day_same_signal
previous_proposal_id=prop_20260526T163619303093Z_7340cb3573
actual_execute=false
```

Monitor after smoke:

```text
classification=WARN
FAIL=[]
PASS includes right_brain_expression_feedback_linked
PASS includes right_brain_expression_outcome_recorded

ModuleArtifacts.expression_feedback.feedback_count=3
ModuleArtifacts.expression_feedback.linked_outcome_count=1
ModuleArtifacts.expression_feedback.linked_outcome_missing_count=0
ModuleArtifacts.expression_feedback.unlinked_count=2

ModuleArtifacts.right_brain_expression_adapter.outcome_count=2
ModuleArtifacts.right_brain_expression_adapter.outcome_feedback_count=1
ModuleArtifacts.right_brain_expression_adapter.latest_outcome_feedback_count=1
ModuleArtifacts.right_brain_expression_adapter.latest_outcome_id=rbout_aa416c239b761e2b

ExpressionArtifacts.expression_feedback_linked_outcome_count=1
ExpressionArtifacts.right_brain_adapter_outcome_feedback_count=1
ExpressionArtifacts.right_brain_adapter_latest_outcome_feedback_count=1
```

Conclusion:

- `P1-R` outcome-feedback linkage is live on the test host.
- The path is now:

```text
Hermes-agent expression outcome
-> owner expression feedback
-> expression_feedback_ledger with outcome_id/request_id/policy_version
-> EvidenceScoring expression_feedback subject
-> SelfEvolution expression_policy class
-> same-day/same-signal cadence gate prevents duplicate proposal spam
```

- This does not close mature right-brain learning volume yet. It establishes
  the measurable runtime path and keeps transport/delivery owned by Hermes.
## 2026-05-27 - P1-S DeepReflection Expired-Working Hygiene Runtime Evidence

Scope:

- P1-S / RH-39 DeepReflection input hygiene.
- This slice only prevents expired working items from driving DeepReflection
  analysis and exposes monitor fields.
- It does not change Hermes transport, expression delivery, owner approval, or
  generic execution behavior.

Dynamic closure preflight:

```text
source_of_truth: 39-left-brain-governance-quality-contract.md; 40-memory-os-unified-control-plane.md; live monitor working expired counts
finding_type: left-brain data hygiene / live monitor gap
owning_seam: DeepReflection input collection and monitor evidence
reverse_scope: Memory-OS owns bounded reflection input; Hermes owns agent/transport; no scheduler or delivery changes
equivalent_contract_or_project_contract: 29 MemoryWriteSurface/MonitorEvidence; 36 DeepReflection closure row; 39 left-brain quality contract
evidence_loop: failing local tests -> implementation -> local targeted/full tests -> 10.20.3.200 dry-run -> monitor summary
monitor_or_validation_fields: latest_active_working_input_count; latest_expired_working_skipped_count; latest_expired_working_used_in_analysis_count; deep_reflection_expired_working_not_used
promotion_signal: expired_working_used_in_analysis_count=0 with monitor PASS
stop_or_rollback_signal: expired working text appears in DR input snapshot/themes, or monitor warns deep_reflection_expired_working_used_in_analysis
external_review: not required for report-only/input-hygiene slice
```

Local TDD:

```text
python -m pytest tests\system_modularization\test_deep_reflection_module.py -q

Initial failing tests:
- test_deep_reflection_collect_inputs_skips_expired_working_items
- test_deep_reflection_run_once_reports_expired_working_hygiene

Failure signal:
- missing working_item_hygiene
- missing active/expired working result fields

Final result:
24 passed
```

Local monitor tests:

```text
python -m pytest tests\scripts\test_memory_os_3_200_monitor.py tests\system_modularization\test_deep_reflection_module.py -q

Result:
70 passed
```

Runtime deployment:

```text
scp plugins\modules\cognition\deep_reflection.py \
  hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/cognition/deep_reflection.py
```

Live dry-run:

```text
ssh hermes-media "hermes memory-os-agent-os modules run-once --module deep_reflection --dry-run"
```

Result summary:

```text
status=ok
dry_run=true
active_working_input_count=8
expired_working_skipped_count=158
expired_working_used_in_analysis_count=0
actual_send=false
actual_execute=false
actual_identity_write=false
actual_crystallized_approval=false
```

Status recheck:

```text
report_count=36
latest_active_working_input_count=8
latest_expired_working_skipped_count=158
latest_expired_working_used_in_analysis_count=0
actual_send=false
actual_execute=false
```

Monitor:

```text
python scripts\memory_os_3_200_monitor.py --output summary
```

Result:

```text
status=WARN
FAIL=[]
PASS includes:
- deep_reflection_expired_working_not_used
- left_brain_expired_working_not_scored
- left_brain_pipeline_check_visible

DeepReflection:
- active_working_input_count=8
- expired_working_skipped_count=158
- expired_working_used_in_analysis_count=0
```

Remaining WARN items are outside this slice:

```text
module_cadence_split_pending
session_mirror_pending_sessions
rh31_eval_has_failures
rh26_casual_empty
```

Conclusion:

- LIVE PASS / MONITOR PASS for P1-S DeepReflection expired-working hygiene.
- Expired working items are still counted for observability but no longer enter
  DeepReflection input or deterministic analysis.

## 2026-05-27 - P1-T EvidenceScoring Cadence Split Runtime Evidence

Scope:

- P1-T second module-local cadence split.
- Target module: `EvidenceScoring`.
- This slice does not modify Hermes cron/systemd timers and does not add a
  Memory-OS scheduler. It only prevents unchanged scoring input from rewriting
  evidence/score artifacts.

Selection basis:

```text
Refreshed cadence report before implementation:
- evidence_scoring.generated_count=205
- evidence_scoring.skipped_count=0
- target_cadence_class=daily_or_on_new_signal

Reason:
- EvidenceScoring had the largest current generated artifact count after the
  existing SelfEvolution split.
- speak_gate.error_count=15 remains a historical/missing-evaluation signal,
  not a timer split by itself.
```

Dynamic closure preflight:

```text
source_of_truth: P1-T roadmap, 41 blueprint, live module_cadence counters
finding_type: module cadence / repeated artifact generation
owning_seam: EvidenceScoring.score_all module-local run gate
reverse_scope: Hermes keeps scheduler ownership; Memory-OS only adds input-fingerprint skip evidence
equivalent_contract_or_project_contract: 36 cadence classification; 39 left-brain governance quality; 40 control plane
evidence_loop: failing local TDD -> implementation -> cadence-report counter test -> live two-run smoke -> live cadence report -> monitor
monitor_or_validation_fields: skipped_run_count; latest_cadence_skipped; latest_skip_reason; evidence_scoring_cadence_skip_visible
promotion_signal: unchanged second run returns cadence_skipped=true and generated_score_count=0
stop_or_rollback_signal: new input is incorrectly skipped, scores disappear, or boundary fields change
external_review: not required for module-local report-only skip gate
```

Local TDD:

```text
python -m pytest tests\system_modularization\test_evidence_scoring_module.py -q

Initial failure:
- missing skipped/cadence_skipped/generated_score_count fields

Final result:
12 passed
```

Local cadence/monitor tests:

```text
python -m pytest tests\system_modularization\test_evidence_scoring_module.py tests\scripts\test_memory_os_module_cadence_report.py tests\scripts\test_memory_os_3_200_monitor.py -q

Result:
61 passed
```

Runtime deployment:

```text
scp plugins\modules\evidence\scoring.py \
  hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/evidence/scoring.py

scp scripts\memory_os_module_cadence_report.py \
  hermes-media:/root/.hermes/scripts/memory_os_module_cadence_report.py
```

Live two-run smoke:

```text
first.status=ok
first.skipped=false
first.cadence_skipped=false
first.score_count=514
first.generated_score_count=514

second.status=ok
second.skipped=true
second.cadence_skipped=true
second.reason=unchanged_input_fingerprint
second.score_count=514
second.generated_score_count=0

status.run_report_count=2
status.skipped_run_count=1
status.latest_cadence_skipped=true
status.latest_skip_reason=unchanged_input_fingerprint
status.expired_used_in_scoring_count=0
```

Live cadence report:

```text
python3 /root/.hermes/scripts/memory_os_module_cadence_report.py --apply

evidence_scoring.generated_count=514
evidence_scoring.skipped_count=1
evidence_scoring.run_count=515
evidence_scoring.error_count=0
boundary.cron_modified=false
actual_send=false
actual_execute=false
```

Monitor:

```text
python scripts\memory_os_3_200_monitor.py --output summary
```

Result:

```text
status=WARN
FAIL=[]
PASS includes:
- evidence_scoring_cadence_skip_visible
- left_brain_feature_scoring_primary_ok
- left_brain_expired_working_not_scored

ModuleArtifacts.evidence:
- score_count=514
- skipped_run_count=1
- latest_cadence_skipped=true
- latest_skip_reason=unchanged_input_fingerprint
```

Remaining WARN items are outside this slice:

```text
module_cadence_split_pending
session_mirror_pending_sessions
rh31_eval_has_failures
rh26_casual_empty
```

Conclusion:

- LIVE PASS / MONITOR PASS for EvidenceScoring module-local cadence split.
- This is not production cadence maturity yet; it is the second safe local skip
  gate after SelfEvolution.

## 2026-05-27 - P1-T OpsGate No-Pending Skip Gate Runtime Evidence

Scope:

- P1-T third module-local cadence split.
- Target module: `OpsGate`.
- Do not change Hermes cron/systemd timers.
- Do not change approved-proposal explicit follow-up behavior when proposed
  actions exist.
- Prevent the test-host cognitive loop from appending empty OpsGate reports when
  there are no pending proposed actions.

Dynamic closure preflight:

```text
source_of_truth: 32/40/41 P1-T roadmap plus live module_cadence counters
finding_type: module cadence noise / empty report generation
owning_seam: OpsGateModule.run_once report-only gate
reverse_scope: Hermes remains scheduler/cron/transport owner; Memory-OS only adds module-local no-pending skip evidence
equivalent_contract_or_project_contract: 36 cadence classification; 39 left-brain governance quality; 40 control plane
evidence_loop: failing unit tests -> implementation -> cadence-report test -> live no-pending run -> live cadence report -> monitor
monitor_or_validation_fields: ops_gate.skipped_run_count,latest_cadence_skipped,latest_skip_reason,ops_gate_no_pending_skip_visible
promotion_signal: proposed_actions=[] returns skipped=true/cadence_skipped=true and report_count does not increase
stop_or_rollback_signal: pending proposed action is skipped; OpsGate report-only follow-up stops writing reports; actual_execute/send true
external_review: not required for this no-transport/no-execution skip gate
```

Local TDD:

```text
python -m pytest tests\system_modularization\test_ops_gate_module.py -q
before implementation: FAILED, KeyError: 'skipped'
after implementation: 7 passed

python -m pytest tests\scripts\test_memory_os_module_cadence_report.py tests\scripts\test_memory_os_3_200_monitor.py -q
before implementation:
  cadence report did not count ops_gate skipped runs
  monitor did not emit ops_gate_no_pending_skip_visible
after implementation: 49 passed
```

Implementation:

```text
OpsGateModule.run_once(proposed_actions=[]):
  status=ok
  skipped=true
  cadence_skipped=true
  reason=no_pending_proposed_actions
  actual_execute=false
  writes system-modules/ops_gate/runs.jsonl
  does not write system-modules/ops_gate/reports.jsonl

OpsGateModule.run_once(proposed_actions=[...]):
  unchanged; still writes report-only decisions
  actual_execute=false
```

Remote deployment:

```text
scp plugins/modules/governance/ops_gate.py \
  hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/governance/ops_gate.py

scp scripts/memory_os_module_cadence_report.py \
  hermes-media:/root/.hermes/scripts/memory_os_module_cadence_report.py
```

Live no-pending smoke:

```text
before_reports=58
after_reports=58
before_runs=0
after_runs=1
result_status=ok
skipped=True
cadence_skipped=True
reason=no_pending_proposed_actions
decision_count=0
actual_execute=False
status_skipped_run_count=1
status_latest_cadence_skipped=True
status_latest_skip_reason=no_pending_proposed_actions
```

Live cadence report:

```text
ops_gate.cadence_counters:
  run_count=59
  generated_count=58
  skipped_count=1
  error_count=0
  duplicate_count=0
  last_status=ok

boundary.cron_modified=false
actual_send=false
actual_execute=false
```

Monitor:

```text
python scripts\memory_os_3_200_monitor.py --output summary
```

Result:

```text
status=WARN
FAIL=[]
PASS includes:
- ops_gate_no_pending_skip_visible
- module_cadence_report_visible
- owner_review_proposal_followups_ok

OwnerProposalFollowups:
  awaiting_ops_gate=0
  ops_gate_reviewed=7
  execution_tickets=0
  actual_execute=false

ModuleArtifacts.ops_gate:
  report_count=58
  run_report_count=1
  skipped_run_count=1
  latest_cadence_skipped=true
  latest_skip_reason=no_pending_proposed_actions
  duplicate_proposal_followup_count=0
```

Remaining WARN items are outside this slice:

```text
module_cadence_split_pending
session_mirror_pending_sessions
rh31_eval_has_failures
rh26_casual_empty
```

Conclusion:

- LIVE PASS / MONITOR PASS for OpsGate no-pending skip gate.
- OpsGate no longer writes empty reports when there are no proposed actions.
- Explicit approved-proposal report-only follow-up is unchanged and remains the
  only path that writes OpsGate proposal decisions.
- This is the third safe P1-T module-local split after SelfEvolution and
  EvidenceScoring; production cadence maturity remains open for other modules.

## 2026-05-27 - P1-S Feedback Backflow Quality Gate Runtime Evidence

Scope:

- P1-S feedback backflow quality.
- Convert expression feedback into higher-quality proposal input only when it is
  linked to a recorded right-brain expression outcome.
- Do not directly mutate prompt, policy, cadence, routing, delivery, or
  execution.
- Do not add a generic executor.

Preflight:

```text
source_of_truth=32/39/40/41 plus live expression-feedback monitor evidence
finding_type=feedback backflow quality gap
owning_seam=EvidenceScoring expression-feedback subject metadata + SelfEvolution expression-policy proposal generation
reverse_scope=Hermes owns interaction/LLM/transport; Memory-OS owns bounded evidence, proposal, audit, monitor
evidence_loop=RED tests -> local full tests -> 10.20.3.200 module smoke/status
monitor_or_validation_fields=expression_feedback_linked_subject_count,expression_feedback_unlinked_subject_count,proposal_quality_gate_failed_count,last_quality_gate_reason
promotion_signal=linked expression feedback can produce a bounded expression_policy proposal; unlinked-only feedback cannot become owner-facing proposal pressure
stop_or_rollback_signal=direct policy/prompt/cadence write, actual_execute/send true, raw body, generic executor
external_review=not required for proposal-only quality gate; required before new apply kinds
```

Implementation:

- `EvidenceScoring` now preserves bounded expression feedback context:
  `outcome_id`, `request_id`, `policy_version`, and linked/unlinked subject
  counts.
- `SelfEvolution` now applies an expression-feedback quality gate:
  unlinked-only expression feedback returns `proposal_quality_gate_failed`
  instead of creating an owner-facing proposal.
- Linked expression feedback proposals carry bounded quality metadata:
  `quality_gate=linked_expression_feedback`, feedback counts, linked outcome
  refs, policy versions, `direct_apply_allowed=false`, and
  `generic_executor_allowed=false`.
- `ProposalQueue` stores these bounded proposal-quality fields.
- Monitor artifact summary exposes the new linked/unlinked scoring subject
  counts and SelfEvolution quality-gate counters.

Local verification:

```text
python -m pytest tests\system_modularization\test_evidence_scoring_module.py tests\system_modularization\test_self_evolution_module.py tests\system_modularization\test_left_brain_pipeline_checker.py tests\system_modularization\test_proposal_queue_module.py tests\scripts\test_memory_os_3_200_monitor.py -q
86 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=31
active_work_item_count=20
active_work_mapping_count=20
finding_count=0

python -m pytest -q
592 passed

git diff --check
PASS
```

Deployment:

```text
scp plugins/modules/evidence/scoring.py hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/evidence/scoring.py
scp plugins/modules/governance/self_evolution.py hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/governance/self_evolution.py
scp plugins/modules/governance/proposal_queue.py hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/governance/proposal_queue.py
scp scripts/memory_os_3_200_monitor.py hermes-media:/root/.hermes/scripts/memory_os_3_200_monitor.py
```

Live smoke:

```text
score_status=ok
score_skipped=False
expression_feedback_subject_count=3
expression_feedback_linked_subject_count=1
expression_feedback_unlinked_subject_count=2
self_evolution_status=ok
self_evolution_reason=cadence_same_day_same_signal
proposal_created=False
proposal_quality_gate_failed=False
actual_execute=False
```

Live module status:

```text
EvidenceScoring:
  score_mode=feature_maturity_v2
  feature_score_mode=primary
  score_count=513
  expression_feedback_subject_count=3
  expression_feedback_linked_subject_count=1
  expression_feedback_unlinked_subject_count=2
  expired_used_in_scoring_count=0
  actual_execute=false

SelfEvolution:
  report_count=35
  proposal_count=21
  novelty_skipped_count=11
  duplicate_unresolved_proposal_count=11
  cadence_skipped_count=3
  same_signal_skipped_count=3
  proposal_quality_gate_failed_count=0
  actual_execute=false
```

Live module doctor:

```text
status=warning
findings:
- mailbox_root_missing (existing warning)
- pending_candidates_present (existing warning)
EvidenceScoring doctor=ok
SelfEvolution doctor=ok
```

Cadence report:

```text
status=warning
module_count=18
cron_job_count=2
integration_harness_member_count=11
split_recommended_count=11
expected_hermes_cron_missing_count=0
finding_count=11
generated_count=882
skipped_count=16
error_count=15
duplicate_count=11
actual_send=False
actual_execute=False
cron_modified=False
```

Full monitor note:

```text
python scripts\memory_os_3_200_monitor.py --host 10.20.3.200 --output summary
timed out after 180s in this run.
```

Conclusion:

- LIVE PASS for the targeted P1-S feedback quality smoke.
- LOCAL PASS for full test and contract checks.
- MONITOR FIELD PASS for module status / artifact fields that expose linked
  feedback context and quality-gate counters.
- Full consolidated monitor did not complete in this run; treat that as a
  residual monitor-runtime risk, not as evidence of behavior failure.

## 2026-05-27 - P1-Q proposal_queue_legacy_template_cleanup Local Baseline

Scope:

- second concrete approved-proposal explicit apply class;
- only `proposal_queue_legacy_template_cleanup`;
- no generic executor, no execution ticket, no raw body, no Hermes transport or
  scheduler changes.

Dynamic closure preflight:

```text
source_of_truth=32/39/40/41 + proposal queue runtime state
finding_type=approved proposal explicit apply gap / legacy backlog cleanup
owning_seam=OwnerActionProcessor approved proposal explicit apply path + ProposalQueue
reverse_scope=Memory-OS may update proposal_queue state; Hermes remains owner of conversation/transport/schedule
evidence_loop=RED tests -> local owner_actions/monitor tests -> live dry-run/apply smoke
monitor_or_validation_fields=legacy_template_cleanup_apply_count, legacy_template_cleanup_closed_count, legacy_template_cleanup_non_legacy_touched_count, legacy_template_cleanup_actual_execute_count
promotion_signal=legacy templates can be pressure-blocked after owner approval and OpsGate would_allow with non_legacy_touched_count=0
stop_or_rollback_signal=non-legacy proposal touched; execution_ticket_created=true; actual_execute=true
external_review=not required for test-host bounded cleanup apply; required before any generic executor or filesystem/service action
```

Local RED/PASS:

```text
python -m pytest tests\plugins\memory\test_memory_os_owner_actions.py -k "legacy_template_cleanup or generic_self_evolution" -q

RED before implementation:
  cleanup dry-run returned status=error (unsupported apply kind)

PASS after implementation:
  3 passed, 48 deselected
```

Targeted local PASS:

```text
python -m pytest tests\plugins\memory\test_memory_os_owner_actions.py -k "legacy_template_cleanup or generic_self_evolution or expression_policy" -q
4 passed, 47 deselected

python -m pytest tests\scripts\test_memory_os_3_200_monitor.py -k "owner_review or legacy_template_cleanup" -q
3 passed, 43 deselected
```

Behavior proven locally:

```text
apply_kind=proposal_queue_legacy_template_cleanup
legacy_template_candidate_count=2
legacy_template_closed_count=2
non_legacy_touched_count=0
closed_state=pressure_blocked
closed_followup_state=closed
cleanup_followup_state=applied_legacy_template_cleanup
execution_ticket_created=False
actual_execute=False
generic_self_evolution_apply=unsupported_apply_kind
```

Live deployment and apply smoke:

```text
deployed:
  plugins/memory/memory_os/owner_actions.py
  scripts/memory_os_3_200_monitor.py

cleanup_proposal_id=prop_20260526T183206541581Z_3b442584b8
ops_status=ok
ops_gate_report_written=True
dry_status=ready
dry_target_count=18
apply_status=applied
apply_kind=proposal_queue_legacy_template_cleanup
closed_count=18
non_legacy_touched_count=0
execution_ticket_created=False
actual_execute=False
cleanup_apply_count=1
```

Post-apply read-only verification:

```text
legacy_unresolved_count=0
legacy_cleanup_apply_count=1
latest_closed_count=18
latest_non_legacy_touched_count=0
latest_actual_execute=False
pressure_blocked_count=18
execution_ticket_count=0
actual_execute=False

review proposal-followups:
approved_proposal_count=5
pending_followup_count=0
open_followup_count=3
awaiting_ops_gate_count=0
ops_gate_reviewed_count=3
policy_apply_count=1
legacy_template_cleanup_apply_count=1
execution_ticket_count=0
actual_execute=false
raw_body_included=false
```

Live module status:

```text
ProposalQueue:
  candidate_count=25
  state_counts.approved_for_proposal=5
  state_counts.owner_declined=2
  state_counts.pressure_blocked=18
  followup_state_counts.applied_expression_policy=1
  followup_state_counts.applied_legacy_template_cleanup=1
  followup_state_counts.closed=19
  execution_ticket_count=0
  actual_execute=false

OpsGate:
  report_count=59
  skipped_run_count=2
  actual_execute=false
```

Full consolidated monitor note:

```text
python scripts\memory_os_3_200_monitor.py --host 10.20.3.200 --output summary
timed out after 240s in this run.
```

Conclusion:

- LIVE PASS for the bounded `proposal_queue_legacy_template_cleanup` explicit
  apply path on test host.
- LIVE PASS that historical legacy template backlog is now closed
  (`legacy_unresolved_count=0`) without touching non-legacy proposals.
- LIVE PASS for hard boundaries: `actual_execute=false`,
  `execution_ticket_count=0`, `raw_body_included=false`.
- Full consolidated monitor still has runtime timeout risk; this does not
  invalidate the targeted live evidence but remains a monitor performance gap.

## 2026-05-27 - P1-P Timestamp / Aging Source-Quality Slice

Scope:

- Make timestamp maturity observable beyond `created_at_coverage_ratio`.
- New Wandering Mind and SpeakGate would-send producers now write bounded
  `created_at` in addition to legacy `ts`.
- Review queue projection annotates timestamp source as `producer`,
  `safe_source_ref`, `legacy_ts`, `updated_at_fallback`, or `missing`.
- Aging summary and monitor expose `created_at_source_distribution` and
  `created_at_source_by_item_type`.
- No canonical history rewrite; old missing/fallback timestamps remain visible.

Local verification:

```text
python -m pytest tests\plugins\memory\test_memory_os_owner_actions.py tests\system_modularization\test_wandering_mind_module.py tests\system_modularization\test_speak_gate_module.py tests\scripts\test_memory_os_3_200_monitor.py::test_classify_snapshot_tracks_owner_review_channel_and_digest_preview_boundaries -q
65 passed

python scripts\memory_os_closure_matrix_check.py --format summary
status=ok
live_module_count=18
matrix_module_count=31
active_work_item_count=20
active_work_mapping_count=20
finding_count=0

git diff --check
PASS
```

Deployment:

```text
scp plugins\memory\memory_os\owner_actions.py hermes-media:/root/.hermes/plugins/memory_os/owner_actions.py
scp plugins\memory\memory_os\owner_actions.py hermes-media:/root/.hermes/memory-os/runtime/python/plugins/memory/memory_os/owner_actions.py
scp plugins\modules\cognition\wandering_mind.py hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/cognition/wandering_mind.py
scp plugins\modules\expression\speak_gate.py hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/expression/speak_gate.py
```

Targeted live producer smoke:

```json
{
  "speak_actual_send": false,
  "speak_decision": "would_send",
  "speak_last_created_at_equals_ts": true,
  "speak_last_has_created_at": true,
  "wandering_actual_send": false,
  "wandering_last_created_at_equals_ts": true,
  "wandering_last_has_created_at": true,
  "wandering_would_send": true
}
```

Remote aging report after deploy:

```json
{
  "created_at_coverage_ratio": 1.0,
  "created_at_source_distribution": {
    "legacy_ts": 43,
    "producer": 2,
    "safe_source_ref": 167
  },
  "created_at_source_by_item_type": {
    "candidate_cleanup": {
      "safe_source_ref": 167
    },
    "speak": {
      "legacy_ts": 43,
      "producer": 2
    }
  },
  "unknown_timestamp_count": 0,
  "unknown_timestamp_by_item_type": {},
  "true_aged_count": 0,
  "unknown_aged_count": 0,
  "canonical_state_changed": false,
  "owner_action_created": false,
  "raw_body_included": false
}
```

Full monitor:

```text
python scripts\memory_os_3_200_monitor.py --host hermes-media --output summary
status=WARN
FAIL=[]
OwnerReviewAging.created_at_source_distribution={'legacy_ts': 43, 'producer': 2, 'safe_source_ref': 167}
OwnerReviewAging.created_at_source_by_item_type={'candidate_cleanup': {'safe_source_ref': 167}, 'speak': {'legacy_ts': 43, 'producer': 2}}
PASS includes owner_review_aging_ok
WARN=['module_cadence_split_pending', 'session_mirror_pending_sessions', 'rh31_eval_has_failures', 'rh26_casual_empty']
```

Conclusion:

- LIVE PASS that new speak/wandering would-send producer records carry
  bounded `created_at`.
- MONITOR PASS that aging distinguishes producer timestamps from safe derived
  source refs and legacy `ts` fallback.
- Boundary evidence remains clean: no actual send, no owner action created by
  aging, no canonical mutation, no raw body included.

## 2026-05-27 - P1-T Fourth Cadence Split: DeepReflection

Selection basis:

- Refreshed `10.20.3.200` counters after the earlier SelfEvolution,
  EvidenceScoring, and OpsGate splits still showed DeepReflection generating
  every harness cycle without a skip counter.
- 36号矩阵 requires DeepReflection to have a bounded cycle with TTL/minimum
  new-signal gating; this slice implements the module-local no-new-signal gate
  without changing Hermes cron/systemd timers.

Local verification:

```text
python -m pytest tests\system_modularization\test_deep_reflection_module.py tests\scripts\test_memory_os_module_cadence_report.py -q
28 passed

python -m pytest tests\scripts\test_memory_os_3_200_monitor.py::test_classify_snapshot_tracks_deep_reflection_expired_working_hygiene -q
1 passed
```

Deployment:

```text
scp plugins\modules\cognition\deep_reflection.py hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/cognition/deep_reflection.py
scp scripts\memory_os_module_cadence_report.py hermes-media:/root/.hermes/scripts/memory_os_module_cadence_report.py
```

Targeted live smoke:

```json
{
  "before_reports": 37,
  "after_reports": 39,
  "before_artifacts": 37,
  "after_artifacts": 38,
  "first_status": "ok",
  "first_cadence_skipped": false,
  "second_status": "skipped",
  "second_reason": "unchanged_input_fingerprint",
  "second_cadence_skipped": true,
  "same_fingerprint": true,
  "second_analysis_artifact_created": false,
  "first_actual_send": false,
  "second_actual_send": false,
  "first_actual_execute": false,
  "second_actual_execute": false
}
```

Cadence report after deploy:

```text
/root/.hermes/scripts/memory_os_module_cadence_report.py --apply --format summary
status=warning
module_count=18
cron_job_count=2
integration_harness_member_count=11
split_recommended_count=11
expected_hermes_cron_missing_count=0
generated_count=899
skipped_count=20
error_count=15
duplicate_count=11
actual_send=False
actual_execute=False
cron_modified=False
```

Full monitor:

```text
python scripts\memory_os_3_200_monitor.py --host hermes-media --output summary
status=WARN
FAIL=[]
ModuleArtifacts.deep_reflection.cadence_skipped_count=1
ModuleArtifacts.deep_reflection.latest_cadence_skipped=True
ModuleArtifacts.deep_reflection.latest_skip_reason=unchanged_input_fingerprint
ModuleCadence.module_counters.deep_reflection.skipped_count=1
PASS includes deep_reflection_cadence_skip_visible
WARN=['module_cadence_split_pending', 'session_mirror_pending_sessions', 'rh31_eval_has_failures', 'rh26_casual_empty']
```

Conclusion:

- LIVE PASS that DeepReflection same-day unchanged apply-mode reruns skip
  instead of creating another internal analysis artifact.
- MONITOR PASS that the skip is visible through both DeepReflection module
  artifacts and the module-cadence report.
- Boundary evidence remains clean: `actual_send=false`, `actual_execute=false`,
  and no Hermes timer/cron ownership moved into Memory-OS.

## 2026-05-27 - P1-S Feedback Proposal Usefulness / Maturity Check

Preflight:

```text
source_of_truth=32 roadmap P1-S, 39 left-brain governance quality contract, live monitor
finding_type=feedback/proposal quality observability gap
owning_seam=LeftBrainPipelineCheck + monitor
reverse_scope=Memory-OS report-only checker; Hermes remains interaction/scheduler owner
monitor_or_validation_fields=proposal_quality_missing_count,expression_policy_quality_ready_count,expression_policy_quality_blocked_count,expression_policy_unlinked_quality_count
promotion_signal=active expression-policy proposals show ready_count>0 only when linked outcome and explicit-apply boundaries are present
stop_or_rollback_signal=quality gap hidden, actual_execute=true, or generic executor fields appear
external_review=not required for report-only checker fields
```

Local verification:

```text
python -m pytest tests\system_modularization\test_left_brain_pipeline_checker.py tests\scripts\test_memory_os_3_200_monitor.py::test_classify_snapshot_tracks_expression_feedback_and_left_brain_pipeline -q
8 passed
```

Deployment:

```text
scp plugins\modules\governance\pipeline_checker.py hermes-media:/root/.hermes/memory-os/runtime/python/plugins/modules/governance/pipeline_checker.py
scp scripts\memory_os_3_200_monitor.py hermes-media:/root/.hermes/scripts/memory_os_3_200_monitor.py
```

Targeted live check:

```json
{
  "status": "ok",
  "finding_codes": [],
  "proposal_quality": {
    "owner_actionable_proposal_count": 0,
    "quality_metadata_missing_count": 0,
    "concrete_body_missing_count": 0,
    "expression_policy_count": 0,
    "expression_policy_quality_ready_count": 0,
    "expression_policy_quality_blocked_count": 0,
    "expression_policy_unlinked_quality_count": 0,
    "runtime_target_expression_policy_count": 0,
    "actual_execute": false
  },
  "actual_execute": false
}
```

Full monitor:

```text
python scripts\memory_os_3_200_monitor.py --host hermes-media --output summary
status=WARN
FAIL=[]
ModuleArtifacts.left_brain_pipeline_check.status=ok
ModuleArtifacts.left_brain_pipeline_check.finding_count=0
ModuleArtifacts.left_brain_pipeline_check.proposal_quality_missing_count=0
ModuleArtifacts.left_brain_pipeline_check.expression_policy_quality_ready_count=0
ModuleArtifacts.left_brain_pipeline_check.expression_policy_quality_blocked_count=0
ModuleArtifacts.left_brain_pipeline_check.expression_policy_unlinked_quality_count=0
ModuleArtifacts.left_brain_pipeline_check.actual_execute=False
WARN=['module_cadence_split_pending', 'session_mirror_pending_sessions', 'rh31_eval_has_failures', 'rh26_casual_empty']
```

Conclusion:

- LIVE PASS that the left-brain checker exposes feedback-proposal usefulness
  fields without creating proposals, tickets, prompt changes, cadence changes,
  or execution.
- Current live state has no active owner-actionable expression-policy proposal,
  so ready/block counts are `0`; this is a correct absence signal, not hidden
  maturity.
