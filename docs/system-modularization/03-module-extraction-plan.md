# Module Extraction Plan

Date: 2026-05-20

## Strategy

Extract modules by behavior and contracts, not by production file layout.

Sannai is excluded from public module extraction. The module system must remain
compatible with Sannai's profile boundary, but it must not package her private
identity, diary, curation, heartbeat, or owner-review surfaces as reusable
modules.

Each extraction slice should produce:

- one installable module skeleton
- one manifest
- one status command
- one doctor command
- one no-send or dry-run execution path
- local tests
- a `10.20.3.200` validation command

## Phase 0: Freeze Evidence

Goal: keep the production observation as an audit record without turning it
into runtime dependency.

Tasks:

- Maintain this document set.
- Keep production source snapshots private and git-ignored.
- Add synthetic or redacted fixtures only.
- Record every hidden dependency discovered during extraction.

Acceptance:

- No raw production body or secret appears in the public repo.
- Module boundaries are documented before code moves.

## Phase 1: Infrastructure Modules

These modules create the installable shell and safe I/O surfaces.

### messaging/mailbox

Sources:

```text
plugins/platforms/mailbox/adapter.py
plugins/platforms/mailbox/plugin.yaml
scripts/mailbox_status.py
mailbox tests and backup docs
```

Target:

```text
module: messaging/mailbox
default: receive/status only, send disabled
depends: Hermes platform loader, profile config, optional Memory-OS event sink
```

Acceptance:

- installable on `10.20.3.200`
- `status` shows mailbox roots without private bodies
- `doctor` catches missing roots and delivery-enabled surprises
- test mode records `would_send` instead of sending

## Phase 2: Independent Perception Modules

These modules can run before the governance subsystem because they depend
mostly on Memory-OS read/write surfaces and scheduler coordination.

### context/household_digest

Sources:

```text
generate_household_digest.py
household_digest_gate_entry.py
state/warming/household_digest.md
Family Room cron jobs
```

Target:

```text
module: context/household_digest
default: local summary generation
depends: MemoryOSReadView, optional cross-profile read policy
```

Acceptance:

- can generate a digest from synthetic Memory-OS events
- can run with no cross-profile access
- emits summary events or local artifact refs only

### cognition/wandering_mind

Sources:

```text
Wandering Mind cron jobs
state/wandering/
household digest inputs
right-brain prompt contract
```

Target:

```text
module: cognition/wandering_mind
default: no-send
depends: MemoryOSReadView, scheduler, optional household_digest
```

Acceptance:

- reads bounded summaries, not raw production state
- output is free-form text or `[SILENT]`
- does not write proposals or agenda
- can write an event/candidate in the test profile
- delivery remains `would-send` unless explicitly enabled

### cognition/inner_drive

Sources:

```text
Memory-OS WorkingMemoryService
Memory-OS events / working / candidates
synthetic fixtures
redacted compatibility observations from private profiles, if needed
```

Target:

```text
module: cognition/inner_drive
default: enabled on 10.20.3.200 test profile, no-send
depends: Memory-OS events/working/candidates, ScheduleCoordinator
```

Acceptance:

- Lingering / Emotional / Curiosity / Attention evolve from real test events
- trace explains why each working item exists
- heartbeat is idempotent
- reads events and writes only working state, candidates, audit, and module-local state
- no Telegram/mailbox send
- no identity write
- defers cleanly if another heartbeat/index operation owns the lock

Sannai-specific heartbeat and curation code is not part of this extraction. It
can be used only to define compatibility tests and private-adapter
requirements.

## Phase 3: Governance Subsystem

These modules are tightly coupled and should be designed/reviewed as one
governance subsystem, even if implemented in separate commits.

### governance/ops_gate

Sources:

```text
ops_gate_runner.py
ops_gate_daily_audit.py
ops_weekly_review.py
state/ops-gate/
```

Target:

```text
module: governance/ops_gate
default: report-only
depends: MemoryOSWriteSink, scheduler
```

Acceptance:

- records decision/audit events
- can evaluate a synthetic action boundary
- does not execute production actions in test mode
- status reports last audit and current gate health

### governance/proposal_queue

Sources:

```text
state/evolution/proposal_queue.yaml
state/evolution/agenda_candidates.yaml
skill scripts/proposal_router.py
skill scripts/agenda_maturation.py
```

Target:

```text
module: governance/proposal_queue
default: local queue only
depends: MemoryOSReadView, MemoryOSWriteSink, owner review policy
```

Acceptance:

- can create, defer, reject, and approve test candidates
- maps existing CW-019-style states without conflating them with crystallized
  approval
- writes queue state profile-locally

### governance/self_evolution

Sources:

```text
self_evolution_daily_pipeline.py
hermes-self-evolution bridge plugin
self-evolution-governor skill scripts
state/evolution/
/vol1/1000/hermes-self-evolution/ as historical reference
```

Target:

```text
module: governance/self_evolution
default: dry-run/report-only
depends: ops_gate, proposal_queue, evidence/scoring, scheduler
```

Acceptance:

- produces runtime digest from real signals, not hard-coded focus items
- no direct self-modification
- proposals pass through proposal queue
- speak decisions pass through speak gate
- status identifies stale digest and missing dependencies

Use `/vol1/1000/hermes-self-evolution/` for lessons about installer shape,
plugin bridge, demo fixtures, and governance pipeline structure. Do not treat
its deployment-specific assumptions as final Memory-OS module APIs.

### evidence/scoring

Sources:

```text
signals.jsonl
score_explanations/
unmatched_signal_review.*
pipeline evidence JSON
```

Target:

```text
module: evidence/scoring
default: evidence write only
depends: MemoryOSReadView, MemoryOSWriteSink
```

Acceptance:

- every score points to evidence refs
- no score is accepted without an explanation record
- scoring can be replayed against fixtures

## Phase 4: Expression Gate

### expression/speak_gate

Sources:

```text
self-evolution-governor/scripts/speak_gate.py
agenda speak decisions
delivery cron behavior
```

Target:

```text
module: expression/speak_gate
default: would-send only
depends: proposal_queue, MemoryOSReadView, DeliverySink
```

Acceptance:

- distinguishes no-send, would-send, and send
- Sannai-style ordinary self-memory prompts do not trigger system reports
- Wandering Mind remains non-task
- diagnostic mode remains profile-configured

## Slice Order

```text
Phase 1 - Infrastructure
  Slice 22: System module contracts and audit docs
  Slice 23: Module manifest/lifecycle scaffold
  Slice 24: mailbox no-send module

Phase 2 - Independent perception/cognition
  Slice 25: household_digest module
  Slice 26: wandering_mind module
  Slice 27: inner_drive runtime module

Phase 3 - Governance subsystem, reviewed as one unit
  Slice 28: ops_gate module
  Slice 29: proposal_queue module
  Slice 30: evidence/scoring module
  Slice 31: self_evolution module

Phase 4 - Expression
  Slice 32: speak_gate module

Phase 5 - Integration
  Slice 33: test-host integrated module suite
```

The order may change if observation on `10.20.3.200` exposes a more urgent
bug, but production migration remains out of scope.

## Stop Conditions

Stop the current slice and ask for review if:

- a module needs real outbound delivery
- a module needs production write access
- a module needs identity edits
- a module cannot be tested without raw private bodies
- a production path appears in reusable runtime code
- dependencies require changing Hermes core behavior beyond plugin discovery
