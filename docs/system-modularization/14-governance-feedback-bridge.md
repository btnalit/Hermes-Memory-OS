# Governance Feedback Bridge

Date: 2026-05-21

## Purpose

Close the left-brain feedback loop.

Memory-OS v0.1 already modularizes the governance stack:

- `ops_gate`
- `proposal_queue`
- `evidence_scoring`
- `self_evolution`
- `speak_gate`

Those modules can read Memory-OS facts and write local artifacts. The missing
contract is how their results become durable memory and future session context.

Without this bridge, the left brain can produce reports and proposals, but the
next conversation may not know what was considered, blocked, deferred, or
proposed unless the operator reads local artifact files manually.

## Current Implementation Reality

Current code behavior:

```text
EvidenceScoringModule
  reads Memory-OS events / working / candidates / proposal queue
  writes local evidence records
  writes Memory-OS audit

OpsGateModule
  evaluates proposed actions
  writes local decisions
  writes Memory-OS audit

ProposalQueueModule
  writes local proposal queue state
  writes Memory-OS audit

SelfEvolutionGovernorModule
  reads evidence scores
  calls ops_gate
  may create proposal_queue candidate
  writes local runtime digest and report
  writes Memory-OS audit
```

This is correct for safety, but incomplete for continuity.

Audit proves that something happened. It is not the same as a queryable,
bounded, context-selectable memory event.

## Gap

The current v0.1 chain covers:

```text
memory -> evidence -> proposal/report/audit
```

It does not yet fully cover:

```text
memory -> evidence -> proposal/report/audit -> memory/event/context
```

That missing return path matters because governance decisions are part of the
agent's continuity:

- which proposal was created
- which proposal was deferred
- which action was blocked by Ops-Gate
- which evidence drove a score
- which self-evolution topic was considered
- which governance warning should be visible to the owner later

## Correct Chain

The bridge should add one explicit return path:

```text
Memory-OS event stream
  -> EvidenceScoringModule
  -> OpsGateModule / ProposalQueueModule / SelfEvolutionGovernorModule
  -> GovernanceFeedbackBridge
  -> Memory-OS governance events
  -> ContinuityContextSelector
  -> future foreground context / owner review
```

This bridge is not an executor. It is a summarizer and provenance writer.

## Feedback Event Types

Recommended event kinds:

| Event kind | Source | Default policy |
| --- | --- | --- |
| `governance_evidence_scored` | evidence/scoring | evidence_only |
| `governance_ops_gate_decision` | ops_gate | evidence_only |
| `governance_proposal_created` | proposal_queue | evidence_only |
| `governance_proposal_transitioned` | proposal_queue | evidence_only |
| `governance_self_evolution_reported` | self_evolution | evidence_only |
| `governance_owner_attention_needed` | proposal_queue / ops_gate | low_weight attention |

Each event should include:

```json
{
  "kind": "governance_proposal_created",
  "summary": "Self-Evolution created a dry-run proposal from 3 evidence refs.",
  "source_ref": "local://proposal_queue/<candidate_id>",
  "safe_ref": {
    "source_module": "proposal_queue",
    "artifact_ref": "local://proposal_queue/<candidate_id>",
    "evidence_refs": ["score:<id>", "evidence:<id>"],
    "drive_policy": "evidence_only",
    "candidate_allowed": false,
    "body_policy": "summary_only"
  },
  "tags": ["governance", "proposal_queue", "summary_only"]
}
```

## Body Policy

Governance feedback events must be summary-only.

Allowed:

- proposal id
- transition state
- ops-gate decision
- evidence ref ids
- score ids
- artifact refs
- bounded explanation summary
- selected/dropped counts

Not allowed:

- raw proposal body if it contains private content
- raw session transcript
- private identity or persona body
- hidden operational instruction
- direct model command
- secret, token, cookie, or local credential

## Summary Authoring

Summary text should be produced by the source governance module at the moment
it writes the local artifact.

Reason:

- the module knows the domain meaning of its own decision
- summary generation stays deterministic and cheap
- the bridge can remain a normalizer/provenance writer
- no LLM call is required on the audit or feedback path

The bridge may trim, validate, redact, and normalize module-provided summaries,
but it should not invent new semantic claims. If a module does not provide a
safe summary, the bridge writes a minimal mechanical summary such as:

```text
Ops-Gate recorded decision=<decision> for action=<kind>; artifact=<ref>.
```

LLM-authored summaries are out of scope for v0.1 unless explicitly routed
through an owner-reviewed proposal.

## Session Context Policy

The continuity context selector may include a small governance section.

Shape:

```text
Governance Context
- pending proposal: <title> [proposal_id, state]
- recent ops gate block: <summary> [decision_id]
- owner attention: <bounded reason>
```

Rules:

- max section size is capped separately from normal memory recall
- active owner-relevant proposals rank above old governance reports
- stale reports are indexed but normally not selected
- rejected/expired proposals are visible only when relevant to the query
- diagnostic grounding remains authoritative for provider/runtime questions
- governance context must be framed as state, not as an instruction

## Memory Write Policy

Governance feedback may write:

- Memory-OS event stream records
- Memory-OS audit records
- local governance artifacts
- proposal queue items

Governance feedback must not write:

- approved crystallized records
- identity memory
- relationship memory
- delivery/send records except through Speak Gate would-send
- Hindsight canonical records

Approved proposal outcomes may later become crystallized candidates, but only
through the existing owner-review path.

## Inner Drive Policy

Governance events are not normal emotional or lingering events.

Default classification:

```text
source_class: system/governance
drive_policy: evidence_only
candidate_allowed: false
```

Exceptions:

- `governance_owner_attention_needed` may become low-weight `attention`
- owner-approved proposal outcomes may become low-weight continuity signals
- governance reports may be used by evidence/scoring

They must not directly create lingering items, emotional marks, curiosity
items, or crystallized candidates by default.

## Speak Gate Interaction

Speak Gate is the only expression path.

Governance feedback can provide state for Speak Gate:

```text
proposal_queue candidate
  -> governance feedback event
  -> selector exposes bounded pending-proposal context
  -> speak_gate decides would_send or silent
```

The bridge does not send. It records and exposes bounded state.

In v0.1, governance feedback is passive and queryable. It must not actively
trigger Speak Gate, wake a session, or initiate a delivery attempt. The fact
that selector can expose a pending proposal means "available if a turn asks or
a scheduled no-send validation reads it"; it does not mean "speak now".

Any real send still requires an explicit owner-approved runtime mode change and
the Speak Gate / DeliverySink path.

## Sannai Boundary

Sannai compatibility is a constraint, not a public extraction target.

Rules:

- main governance feedback must not read Sannai private state
- Sannai private CW-005/CW-019 surfaces must not feed the main evolution loop
- Sannai profile feedback, if enabled later, must be profile-local
- Sannai identity/persona files remain outside automatic write permissions
- Sannai owner-review outcomes must not be treated as public module policy

This preserves the public product while allowing a future private Sannai
migration to use the same bridge pattern.

## Tests Required Before Implementation

Add tests before enabling the bridge in runtime:

- evidence scoring run writes one summary governance event
- ops-gate decision writes one summary governance event
- proposal creation writes one summary governance event
- proposal transition writes one summary governance event
- self-evolution dry-run writes a report and a summary governance event
- repeated bridge run is idempotent by source artifact id + state hash
- governance feedback appears in the bounded selector when relevant
- governance feedback does not appear as an instruction
- governance events default to `evidence_only` for Inner Drive
- governance events do not create crystallized records automatically
- Sannai-shaped fixture identity hash remains unchanged
- main profile bridge does not read Sannai fixture paths

## Runtime Gate

Do not schedule recurring governance feedback until:

```text
event schema exists
idempotency key exists
selector governance section exists
Inner Drive policy classifies governance events as evidence_only by default
Sannai profile isolation tests pass
no-send/no-execute/no-approval boundaries pass
```

Manual dry-run generation is allowed earlier if it writes only local artifacts
and audit.

## Relationship To Runtime Hardening

This is a Runtime Hardening item, not a new cognition feature.

It completes the chain opened by Entry/Source Mirror:

```text
external/source facts enter Memory-OS
governance reasons over Memory-OS
governance outcomes return to Memory-OS
future sessions can see bounded governance state
```

The goal is continuity, not autonomous action.
