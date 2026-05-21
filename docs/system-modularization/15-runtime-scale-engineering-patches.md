# Runtime Scale Engineering Patches

Date: 2026-05-21

## Purpose

Integrate useful engineering ideas from an external V2.0 memory-system proposal
without replacing the Memory-OS architecture.

The proposal is valuable as a scale and performance layer. It is not a new
source of truth for Memory-OS.

Memory-OS keeps these invariants:

- profile-local event files are canonical Memory-OS records
- SQLite is a rebuildable index, not canonical storage
- events keep source class, drive policy, candidate policy, and approval state
- identity and approved crystallized records are protected
- Hindsight remains optional adapter only
- no-send/no-execute is the default for v0.1 modules
- Sannai private policy is not copied into public modules

## What To Absorb

### 1. FTS Text Projection

External idea:

```text
Payload Flattening
```

Memory-OS adaptation:

```text
FTS Text Projection
```

Use deterministic projection to turn structured event payloads into clean
search text. The projection is for indexing only. It must not rewrite canonical
event payloads.

Important correction:

Do not blindly strip JSON keys. Some keys are real semantics:

- `status`
- `loss_rate`
- `queue_depth`
- `platform`
- `proposal_state`
- `decision`
- `error_code`

The projection should remove syntax noise while preserving meaningful field
names and values.

Example:

```json
{
  "producer": "pcdn",
  "status": "error",
  "metrics": {"loss_rate": 0.08, "retry": 3}
}
```

Projected text:

```text
producer pcdn status error metrics loss_rate 0.08 retry 3
```

The event payload stays unchanged.

## 2. Query Fast-Path Router

External idea:

```text
Heuristic Fast-Path Router
```

Memory-OS adaptation:

```text
Query Fast-Path Router
```

Most user questions contain concrete retrieval anchors:

- module names
- provider names
- platforms
- event kinds
- command names
- file names
- error codes
- dates
- mixed Chinese/English operational phrases

Those should use deterministic keyword/entity extraction first. Slow-path
intent classification is only needed when the query is abstract or lacks
anchors.

Required routes:

```text
diagnostic:
  provider/runtime/memory architecture questions
  must preserve Slice 21 diagnostic grounding behavior

fast_path:
  concrete entities, modules, files, platforms, dates, error names

slow_path:
  ambiguous "上次那个问题" style queries
```

The route decision should be visible in status/debug output without printing
private memory bodies.

## 3. Retention And Compaction

External idea:

```text
Sieve & Compaction
```

Memory-OS adaptation:

```text
Retention And Compaction
```

The useful point is physical metabolism. Full-coverage memory can grow
forever if no retention policy exists.

The rejected point is direct automatic deletion as a default behavior.

Memory-OS retention must be policy-based:

| Source class | Default behavior |
| --- | --- |
| telemetry/status noise | dry-run prune candidate |
| runtime heartbeat/index events | compact or drop after audit policy |
| action failure | keep or digest before pruning |
| conversation turn | digest/archive before detail pruning |
| owner facts | protected |
| approved crystallized records | protected |
| identity/relationship memory | protected |
| active proposals/candidates | protected |

High-value events should go through digest/consolidation or proposal review
before detail pruning.

Retention must produce:

- dry-run report
- selected record counts
- dropped/protected counts
- source-class breakdown
- audit event
- rebuild instructions for indexes

## 4. Shadow Journal Ingestion

External idea:

```text
Shadow Journaling
```

Memory-OS adaptation:

```text
Shadow Journal Ingestion
```

This is useful for future high-frequency non-agent producers:

- telemetry
- metrics
- file monitors
- device state
- script status
- tool execution reports

They should not write directly to canonical Memory-OS event files.

Recommended flow:

```text
producer
  -> per-producer spool file / spool directory
  -> arbiter reads bounded batch
  -> dedup and source policy
  -> FTS projection
  -> canonical Memory-OS event
  -> audit
```

Spool records are not memory until the arbiter accepts them.

Malformed records go to quarantine and audit.

## 5. Failure Back-Propagation

External idea:

```text
tool/action failures automatically become state for self-healing
```

Memory-OS adaptation:

```text
Action failures become evidence events.
```

Failures should be captured because they are valuable continuity data:

- tool failed
- cron failed
- shell command failed
- API returned an error
- gateway action was blocked

But they must not force automatic self-heal or automatic execution.

Correct path:

```text
failure observed
  -> action_failure event
  -> evidence/scoring
  -> proposal_queue or ops_gate
  -> owner review / speak_gate no-send
```

This keeps self-repair explainable and gated.

Writer ownership:

```text
ActionOutcomeCollector
```

Failure capture should not be scattered through every module. The preferred
v0.1+ shape is a small ActionOutcomeCollector helper/module that normalizes
execution outcomes from action-capable modules:

- Ops-Gate proposed action outcomes
- Speak Gate / DeliverySink send or would-send outcomes
- mailbox delivery outcomes
- cron/script execution outcomes
- tool/API/shell execution outcomes, when the caller exposes a safe result

The action-capable module remains responsible for its own local decision and
audit record. ActionOutcomeCollector is responsible only for converting the
safe result summary into a Memory-OS `action_failure` or `action_result` event.

Rules:

- do not record raw stderr/stdout by default
- record status, action kind, target ref, error class, bounded message, and
  artifact refs
- do not retry, heal, send, or execute
- route every future repair through evidence/scoring, proposal queue, and
  Ops-Gate
- if no collector is installed, modules may continue writing audit only

## What Not To Absorb

### SQLite As Canonical Stream

Rejected.

Memory-OS canonical records remain event files and protected memory files.
SQLite can be hot storage and index, but it must be rebuildable from source.

### Classless Event Model

Rejected.

Memory-OS needs event classes and policies:

- `source_class`
- `drive_policy`
- `candidate_allowed`
- `promotion_state`
- `approval_state`

Without them, Inner Drive would confuse telemetry, cron, tool logs,
conversation, and owner memory.

### Direct Automatic Self-Healing

Rejected.

A failure event can inform self-evolution. It cannot bypass Ops-Gate,
Proposal Queue, owner review, or Speak Gate.

### Default Physical Delete

Rejected.

Retention is dry-run first. Protected records are never automatically deleted.

## Relationship To Runtime Hardening

These are later Runtime Hardening items:

```text
RH-15 FTS Text Projection
RH-16 Query Fast-Path Router
RH-17 Retention And Compaction
RH-18 Shadow Journal Ingestion
```

They should start after the structural Runtime Hardening chain is in place:

```text
Entry/Source Mirror
  -> Continuity Context Selector
  -> Inner Drive event policy
  -> Digest/Consolidation
  -> Governance Feedback Bridge
```

Reason:

Scale patches optimize and protect a complete system. They should not distract
from making the entry, continuity, and feedback loops complete first.

## Implementation Gates

Do not enable recurring high-frequency ingestion until:

- source caps exist
- retention policy exists
- Inner Drive event eligibility exists
- FTS projection is deterministic
- malformed record quarantine exists
- shadow journal state can recover from crash/restart

Do not enable automatic compaction until:

- dry-run reports are reviewed
- protected record classes are tested
- archive/digest output is owner-visible
- audit and rollback instructions exist

Do not enable slow-path LLM query routing until:

- fast-path route is correct for diagnostic/runtime questions
- private-body redaction is tested
- cost and latency are observable

## Summary

The external proposal is useful as an engineering hardening layer:

```text
search text projection
query routing
retention/compaction
high-frequency spool ingestion
failure event capture
```

It does not replace Memory-OS:

```text
layered memory
event policy
owner approval
profile isolation
module lifecycle
no-send/no-execute boundaries
```

Use it as scale discipline, not as architecture replacement.
