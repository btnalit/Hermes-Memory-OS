# Memory-OS Architecture: A Governed Living Memory

Memory-OS is easiest to misread as a collection of features: recall lanes, a
memory graph, cron jobs, review digests. This document states what it actually
is at the top level, so that future changes are judged against the right
frame.

> **Memory-OS is not an autonomous loop system. It is a governed loop
> system.** Every feedback loop in it closes *through* gates, and some
> transitions are permanently reserved for the human owner. That is not
> unfinished autonomy — it is the design.

## The four planes

Three data planes, crossed by one control plane:

```text
                 OWNER / OPERATIONAL TRUTH
                          ▲
                          │  Loop #0: observation & owner governance
                          ▼
                ┌───────────────────────┐
                │   Governance spine    │
                │  ExecutionGate        │
                │  StructuralWriteGate  │
                │  OwnerGate            │
                │  ResolverGate         │
                │  evidence & audit     │
                └───────────┬───────────┘
                            │  (crosses every plane below)
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   Memory plane       Cognition plane       Graph plane
   event → working    reflection            edge birth
   → candidate        imagination           weight & priors
   → crystallized     inner drive           inject & reinforce
   → recall           self-evolution        forget
        │                   │                   │
        └───────────────────┴───────────────────┘
                            │
                            ▼
                   feedback events → next cycle
```

The governance spine is not one plane among peers and not a post-hoc review
step. It is a **topological property of every loop**: the write path of each
plane passes through a gate before it lands, and the highest-risk transitions
(crystallized writes, revoke/demote/delete, identity and relationship writes,
external sends) never leave the OwnerGate regardless of how mature the
automatic lanes become.

The compressed form of the design:

> **Autonomy inside boundaries, authority outside them.**

And the chain of non-equivalences the gates enforce:

```text
Thought ≠ Memory ≠ Truth ≠ Authority ≠ Execution ≠ Success ≠ Evidence ≠ Maturity
```

A thought does not automatically become a memory; a memory does not
automatically become truth; truth does not confer authority to act; an
execution is not proof of success; success once is not evidence of health;
and evidence today is not maturity. Each `≠` is a gate, a ledger, or an owner
decision.

## The loop inventory

Memory-OS runs six feedback loops. Naming them here is deliberate — and
**docs-only** (see "The loop contract is distributed" below).

### Loop #0 — Observation & owner governance (the meta-loop)

```text
runtime → monitor → operational truth → owner digest
       → owner decision → owner action → feedback event → runtime
```

This loop's job is to determine whether the other loops are actually alive.
It exists because the project has repeatedly measured the gap between "a lane
ran" and "a lane worked": lanes that ran hundreds of times with zero output,
no-write exits that were byte-identical to healthy idleness, empty LLM
replies counted as success. Loop #0 is why every lane must record *why* it
produced nothing, from a closed set of reason codes, in a durable artifact.

### Loop 1 — Memory lifecycle

```text
experience → event → working → candidate → evidence
          → crystallized/permanent → recall → new experience
```

Crystallization is owner-gated, permanently.

### Loop 2 — Cognition

```text
memory state → reflection / imagination / inner drive
            → derived artifacts → evidence & proposals
            → governance → memory state
```

Orchestrated by the cognitive loop runner; every step closes an ExecutionGate
envelope or runs under a module-internal governance surface.

### Loop 3 — Graph (the living memory graph)

```text
edge proposal (structural / llm / vector / provenance / contradiction)
  → evidence-tiered birth weight → active
  → retrieval candidate → ranked + exploration slots
  → really injected? → shadow ledger (closed outcome set)
  → hit → reinforce → future ranking
  → long idle → invalidated (bounded per run, never deleted)
```

The edge lifecycle is automatic, but edges never acquire the power to cross
owner boundaries: they are advisory derived projections. A contradiction
claim — the heaviest thing an edge can assert — is born as a review candidate
and activates only through owner approval.

### Loop 4 — Self-evolution

```text
runtime signals → evaluate → proposal → gate → bounded change
              → observe → feedback event → next proposal
```

Proposals do not self-apply. Apply requires a bounded contract, rollback,
monitor fields, and explicit owner authority.

### Loop 5 — Expression

```text
thought → draft → grounded judge → speak gate → delivery outcome
       → owner feedback → feedback event → memory
```

What was said, and how it landed, feeds back into memory — but sending is a
permanent OwnerGate boundary.

## Architecture-closed is not production-closed

Two different claims, never to be conflated:

- **Architecture-closed**: the code path for the full cycle exists and is
  tested.
- **Production-closed**: the loop has been observed completing its cycle on
  production, and its feedback has measurably changed future behavior.

Three principles follow, extracted from measured incidents rather than
theory:

> **Execution is not evidence.** A clean envelope proves a lane ran, never
> that it produced anything.
>
> **Repetition is not convergence.** A lane can run hundreds of times while
> its backlog grows.
>
> **A loop is not closed until its feedback changes future behavior in
> production.**

Honest status as of 2026-08:

| Loop | Architecture | Production closure |
|---|---|---|
| #0 Observation | closed | closed — drives real owner decisions daily |
| 1 Memory lifecycle | closed | closed — full path exercised on production |
| 2 Cognition | closed | closed — steps run under envelopes with reason-coded outcomes |
| 3 Graph | closed | **partial** — birth, retrieval, injection, and hit-ledger observed; reinforcement is in early natural accumulation; the first natural forgetting wave is expected around 2026-10 (60 days after first real injection) and the repopulation-after-forgetting half of the cycle has, by construction, never yet run |
| 4 Self-evolution | closed | partial — propose/observe closed; apply is rare by design |
| 5 Expression | closed | partial — draft/judge/gate ledgers active; feedback runs at weekly cadence, so closure evidence accrues slowly |

A shrinking graph when the first forgetting wave arrives is **expected
maintenance, not an incident**.

## The loop contract is distributed, deliberately

One could imagine a central `LoopSpec` registry — id, cadence, boundaries,
evidence, feedback — as a first-class runtime object. Memory-OS already has
every one of those fields; they live in the mechanisms that enforce them:

| Loop-contract field | Where it already lives |
|---|---|
| id | cron lane id (`cron_registry.py`) |
| cadence | `due_interval_minutes` / `due_policy` per lane |
| risk / scope / boundary | ExecutionGate permit envelope |
| postcheck | ExecutionGate completion record |
| evidence / outcome | per-lane `last_run` blocks, ledgers, monitor sections |
| feedback | governance feedback bridge → memory events |

The contract is **distributed on purpose**. Reifying it into a central
runtime abstraction would create a second definition of facts the gate system
already owns — two sources of truth, drift between them, and a new
maintenance surface — for zero behavioral gain. The loop names in this
document are the whole abstraction. **Do not build a LoopSpec engine.**

## Deferred by design

Ideas that are directionally right and deliberately not built. Each has a
trigger condition; before that condition is met, building it is scope creep.

1. **Edge explanation view** ("why is this edge 0.76?"). All the evidence
   already exists — birth evidence kind and prior, proposer identity,
   confidence, injection outcomes, hit history, contradiction status. What is
   missing is only a *projection* that assembles it per edge. Build it as a
   read-only view over existing ledgers when a real debugging or owner-review
   need appears. It needs no new storage, and must not get any.
2. **Additional edge states** (`emerging`, `weakening`, `contested`,
   `superseded`). Every one of these is already expressible as a projection
   over existing data (weight + time since last hit + contradiction edges +
   `invalidated`). The rule: **a state that can be projected must not be
   persisted.** Persisting it would grow the state machine and create a new
   vocabulary for gates to drift against.
3. **Temporal edge fields** (`valid_from`, `valid_until`,
   `last_confirmed_at`). Deferred until a consumer exists that would make a
   different decision because of them. Era markers and ledger timestamps
   cover current needs.
4. **Graph maturity milestones** — not work items, but observations to let
   happen: natural reinforcement accumulation (in progress), the first
   natural forgetting wave (~2026-10), and repopulation after forgetting.
   The correct action for each is to watch the ledgers, not to intervene.

## What this architecture refuses to be

The gates are not scaffolding awaiting removal as the system matures. The
most dangerous design for a long-lived cognitive system is the one where:

```text
what it thinks = what it believes = what it permanently remembers
             = what it may act on
```

Memory-OS takes those equals signs apart on purpose. The system may form its
own internal history — but it cannot promote its internal history into
real-world authority on its own. That constraint is not a limit on the
architecture. It is the reason the architecture is allowed to keep running.
