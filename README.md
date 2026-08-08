# Hermes Memory-OS

<p align="center">
  <img width="1180" alt="Hermes Memory-OS" src="https://github.com/user-attachments/assets/e923d0df-5f2c-4ea8-b0b5-7569fab5d6d8" />
</p>

<p align="center">
  <strong>Memory that can remember, doubt, forget — and eventually dream.</strong>
</p>

<p align="center">
  A complete, file-first memory and cognition runtime for long-running
  <a href="https://github.com/NousResearch/hermes-agent">Hermes Agent</a> profiles —
  with a self-tending memory graph and a governed right-brain module.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg" /></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB.svg" />
  <img alt="Storage: local first" src="https://img.shields.io/badge/Storage-local--first-2E8B57.svg" />
  <img alt="Governance: owner controlled" src="https://img.shields.io/badge/Governance-owner--controlled-6A5ACD.svg" />
</p>

Hermes Memory-OS gives a long-running agent more than a larger context window.
It gives the agent an inspectable memory lifecycle: experiences enter working
memory, evidence is accumulated, contradictions stay visible, durable beliefs
must clear governance gates, and every important transition remains auditable.

Hermes remains the host. It owns conversation, tools, scheduling, transport,
retry, and channel delivery. Memory-OS owns bounded memory state, retrieval,
cognition artifacts, approval state machines, and operational evidence.

## Why Memory-OS

Most agent memory systems answer one question: **what should be retrieved?**
Memory-OS also asks:

- Should this experience become a durable belief at all?
- What evidence supports it, and what contradicts it?
- Is it provisional, contested, superseded, or permanent?
- Can the owner inspect, reject, or correct it through the normal agent channel?
- Which memories belong together — and can those relationships strengthen with
  use and fade when never used?
- Can the system forget without turning forgetting into a failure?
- Can an agent have thoughts that are not tasks, reports, or alerts?

That last question defines the right-brain module: a governed space that can
associate freely, remain silent, share a thought, or let it disappear — without
quietly rewriting what the system believes.

## A Complete Agent Memory & Cognition Stack

Memory-OS is not a single retrieval plugin. It is a layered Agent OS with a
memory kernel, multiple retrieval lanes, cognition modules, evidence and truth
checks, owner governance, safe self-evolution, expression control, and an
operational control plane.

| System layer | What it includes |
| --- | --- |
| **Memory kernel** | Canonical file store, working memory, provisional memory, crystallized memory, permanent promotion, retention, cleanup, audit, migration, and append-only lifecycle receipts. |
| **Recall engine** | FTS5, vector recall, dynamic memory graph, entity graph, temporal recall, state-overlay recall, optional Hindsight recall, low-clue routing, unified recall facade, and source attribution. |
| **Evidence & truth** | Source gating, provenance and taint checks, evidence scoring, fact judge, confabulation detection, contradiction lanes, contested-pair projections, clearance receipts, and crystallized-memory revalidation. |
| **Context intelligence** | Bounded prefetch, context routing, memory projection, state overlay, session/cron/state mirrors, session fact extraction, abstraction distillation, digest consolidation, household digest, and symbolic offloading. |
| **Cognition system** | Inner Drive, Deep Reflection, Imagination Loop, Wandering Mind, cognitive-loop orchestration, cadence control, and bounded module coordination. |
| **Governance & evolution** | Candidate aggregation and review, confidence routing, provisional lifecycle, proposal queue, OpsGate, live guards, reversible knob overrides, A/B evaluation, migration control, feedback bridge, and Self-Evolution Governor. |
| **Expression system** | Expression drafts, grounded-expression judge, Speak Gate, rolling rate limits, right-brain sharing, outcome capture, deduplication, and owner feedback. |
| **Operations & safety** | ExecutionGate, StructuralWriteGate, cron registry and adapters, owner action tokens, no-send mailbox boundary, installer, phased deploy wrapper, health probes, audit monitors, and read-only dashboard. |

These layers are composable and profile-local. Modules can remain disabled,
shadowed, report-only, or no-send until their evidence and owner gates permit a
stronger mode.

## Core Capabilities in Depth

### Living memory, not a transcript archive

- Profile-local canonical files remain the source of truth.
- Working memory is separated from owner-approved crystallized memory.
- Provisional records pass evidence, clearance, stability, and owner gates
  before becoming permanent.
- Contradictory memories remain visible through contested projections instead
  of being silently overwritten.
- Evidence increments, absorption audits, superseded state, provenance, and
  sensitivity-aware fail-closed rules make belief changes explainable.
- Rebuildable SQLite indexes provide speed without becoming the authority.

### Hybrid retrieval with a deterministic floor

- SQLite FTS5 full-text search.
- Optional local vector similarity through `sentence-transformers`.
- Bounded one-hop expansion through the dynamic memory graph (next section).
- Reciprocal Rank Fusion across enabled lanes.
- Unicode-boundary and permanent-memory fallbacks when richer lanes return no
  result.
- Every optional lane is knob-gated and can degrade safely to pure FTS5.

### A memory graph that grows, reinforces, and forgets on its own

Memory-OS maintains a dynamic relationship graph over canonical memory. Edges
are advisory derived projections — they never cross owner-gated boundaries, so
the graph governs itself end-to-end without adding review burden:

- **Automatic growth.** Structural analysis, provenance links, and a bounded
  LLM proposer create edges that become active immediately; wrong edges are
  eliminated by usage signals, not human review.
- **Evidence-tiered birth weights.** An explicit reference (0.70) outweighs a
  shared source event (0.55), lexical similarity (0.45), and mere temporal
  proximity (0.35); LLM-proposed edges scale with stated confidence. No edge
  is born saturated.
- **Anchor-driven injection.** Retrieval anchors — crystallized memory
  prioritized over event noise, with CJK-aware query fallbacks and
  task-anchor supplementation — expand one bounded hop into a
  "Related Memory" context section: top edges by weight plus deterministic
  exploration slots, so young edges still get a chance to prove themselves.
- **Reinforcement with an honest ledger.** Every edge encounter is recorded
  with a closed outcome set; only an edge that was actually shown to the
  agent is reinforced (multiplicative and asymptotic, so no edge pins itself
  at a hard cap).
- **Designed forgetting.** Active edges unused for 60 days are invalidated —
  bounded per round and guarded against mass die-off. A shrinking graph is
  expected maintenance, not an incident.

### Owner governance through Hermes

- Review digests arrive in the owner-facing Hermes channel.
- Stable `oa_...` action tokens survive re-rendering and retries.
- Approve, reject, feedback, and bounded apply operations pass through one
  audited state machine.
- Approval is not execution: only proposal kinds with an explicit target,
  rollback, monitor evidence, and apply contract can change runtime state.
- A read-only dashboard exposes health and evidence without adding hidden write
  controls.

### A right brain with the freedom not to perform

- Portable cognition modules produce evidence, proposals, reflection artifacts,
  expression drafts, cadence reports, and feedback signals.
- A wandering journal holds associations, interpretations, and claim-like
  insights without forcing every thought to become a task or a memory.
- The wandering prompt defines boundaries, not a destination. A cycle with no
  output is complete and healthy.
- Thoughts may quietly disappear, become governed synthesis candidates, or be
  shared as inner monologue.
- Sharing has a maximum rate and cooldown, but no quota, catch-up send,
  reworded resend, or emergency lane.
- Owner inspection is allowed and visible: querying the journal writes a small
  `{queried_at, scope}` trace instead of observing invisibly.
- Memory-OS never sends directly to Telegram, Discord, Signal, Slack, Matrix,
  or another platform. Hermes owns delivery.
- Right-brain expression is bounded by Hermes delivery, content deduplication,
  outcome capture, and no-send validation.

### Optional Hindsight substrate

Hindsight can be adopted as a governed derived projection while local files
remain authoritative. Raw conversation turns are not exported by default.
Retain, retract, advisory recall, and reflection each have separate controls,
and the projection ledger remains auditable.

## The Right-Brain Module

The right brain is deliberately different from an autonomous task loop. Its
purpose is not to optimize output volume. Its purpose is to give the agent a
bounded place for non-instrumental thought while keeping durable belief changes
fully governed.

| Principle | Behavior |
| --- | --- |
| Direction stays open | The wandering prompt gives boundaries and seeds, but no required direction or success criterion. Producing nothing is a normal result. |
| Three depths of thought | `association` holds fragments and free associations; `interpretation` explores meaning; `claim` is a belief-like statement that must enter the governed synthesis path. |
| Three possible fates | A thought may be annihilated, proposed, or shared. Annihilation is the default and is not treated as failure. |
| Dreams do not bypass evidence | A `claim` can become memory only as a `derivation="synthesis"` candidate with complete provenance, then clearance, stability, and owner gates. |
| Expression has a ceiling, not a quota | Rate and cooldown knobs may limit sharing. There is no minimum frequency, catch-up send, reworded resend, or emergency channel. |
| Observation leaves a trace | The journal is not proactively shared, but the owner may inspect it. A query writes a lightweight `{queried_at, scope}` trace: the door may open, but never invisibly. |
| Forgetting is a right | Expired thoughts disappear quietly. Monitoring may count annihilation for operations, but must not score it as good, bad, or anomalous. |
| Disabled until earned | `wandering_enabled` defaults to `false`. Activation follows the memory evidence gate and a 30-day coexistence period before rhythm knobs are reconsidered. |

In one sentence: **give her boundaries, not direction; dreams must pass gates,
thoughts may vanish; the door may open, but opening it leaves a trace; whether
she speaks is hers to decide.**

## Quick Start

### Requirements

- Linux host with an existing Hermes Agent profile
- Python 3.11+
- `git`
- `systemctl --user` for timer-based runtime loops; cron fallback remains
  available where user systemd is unavailable

### Install the operational profile

```bash
git clone https://github.com/btnalit/Hermes-Memory-OS.git
cd Hermes-Memory-OS

HERMES_HOME=/root/.hermes \
  bash scripts/install_memory_os.sh --yes --operational --hindsight auto
```

`--operational` installs and enables:

- the `memory_os` Hermes memory provider;
- the `memory-os-agent-os` shell plugin;
- heartbeat and cognitive-loop runtime integration;
- portable cognition, governance, and expression modules;
- the 8-job `active-closure` Hermes cron profile (22 governed lanes grouped into 4 tick jobs plus 4 owner-facing jobs);
- owner-channel discovery from `channel_directory.json`;
- post-install verification that fails loudly when core components are missing.

The installer does **not** restart `hermes-gateway.service`.

### Choose an install posture

| Preset | Intended use | Notable behavior |
| --- | --- | --- |
| `--operational` | Normal full installation | Enables the operational cognition preset, runtime loops, and `active-closure` automation. |
| `--production-safe` | Conservative non-interactive rollout | Keeps core runtime integration but explicitly disables DeepReflection. |
| `--test-host` | Disposable or isolated validation host | Enables the complete test-host surface for integration checks. |

Examples:

```bash
# Conservative install with Hindsight disabled.
HERMES_HOME=/root/.hermes \
  bash scripts/install_memory_os.sh --yes --production-safe --hindsight off

# Install helpers and runtime, but do not create recurring Hermes jobs.
HERMES_HOME=/root/.hermes \
  bash scripts/install_memory_os.sh --yes --operational \
  --no-enable-owner-cron-onboarding

# Preview without writing.
HERMES_HOME=/root/.hermes \
  bash scripts/install_memory_os.sh --yes --operational --dry-run
```

For all options:

```bash
bash scripts/install_memory_os.sh --help
```

## Deployment Wrapper

`scripts/deploy_memory_os.py` separates rollout into `plan`, `preflight`,
`dry-run`, `apply`, and post-install checks. A gateway restart requires both
`--allow-restart` and an explicit restart command.

```bash
# Fresh profile, local apply on the target host.
python scripts/deploy_memory_os.py \
  --hermes-home /root/.hermes \
  --profile fresh \
  --phase apply \
  --mode production-safe \
  --hindsight off

# Existing profile, remote dry-run before any write.
python scripts/deploy_memory_os.py \
  --host hermes-media \
  --remote-repo-root /opt/Hermes-Memory-OS \
  --hermes-home /root/.hermes \
  --profile upgrade \
  --phase dry-run \
  --mode operational \
  --hindsight auto
```

Automated rollout defaults the low-clue LLM judge to bounded active voting with
the current Hermes provider/model. Select `--llm-judge-preset report-only` for
observation only, or `--llm-judge-preset none` to disable it.

## Automation Profiles

The default `active-closure` profile contains **8 Hermes cron jobs** scheduling
**22 governed lanes**.

Scheduling and governance are separate concerns. A *lane* is the unit of
governance: it opens its own ExecutionGate permit, carries its own risk class,
and writes its own completion evidence. A *job* is only the Hermes scheduling
surface. Lanes are grouped into shared "tick" jobs so the cron surface stays
small without merging any governance boundary.

| Job | Schedule | Lanes |
| --- | --- | --- |
| `memory-os-tick-derived` | `2,17,32,47 * * * *` | index sync, event stats refresh, state overlay refresh, entity index refresh |
| `memory-os-tick-governance` | `7,37 * * * *` | proposal follow-up OpsGate, clearance cycle |
| `memory-os-tick-evidence` | `12 * * * *` | fact judge, candidate aggregation, session fact extraction, L3 probe verification, Hindsight health probe, V3 wandering |
| `memory-os-tick-daily` | `5 0 * * *` | exposure rollup, V3 seed evidence, V3 journal sweep, working-memory cleanup, state-source mirror, Hindsight advisory digest |
| `memory-os-owner-review-digest` | `0 9 * * *` | owner review digest |
| `memory-os-memory-sources-feedback-request` | `30 10 * * *` | memory-source feedback |
| `memory-os-expression-feedback-request` | `0 5 * * 0` | expression feedback |
| `memory-os-full-monitor-refresh` | `30 2 * * *` | full monitor snapshot |

A tick fires at its fastest member's cadence; every other member is gated by
its own `due_interval_minutes` and skipped until due, so a weekly lane sharing
a daily tick still runs weekly. Interval-gated lanes also catch up after
downtime, which fixed-time per-lane cron could not do.

Tick jobs run with `deliver=local` and no agent. Owner-facing jobs stay
one-per-job — each renders a distinct owner message through its own agent
prompt and channel — and resolve the configured owner channel through Hermes.

The `full` profile adds one optional job: module cadence reporting.

Enable it explicitly:

```bash
HERMES_HOME=/root/.hermes \
  python scripts/install_memory_os_plugin.py \
  --run-owner-cron-onboarding \
  --owner-cron-owner-approved \
  --owner-cron-profile full
```

Switching an upgraded host back to `active-closure` pauses known optional jobs;
it does not delete them.

## Verify the Installation

```bash
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes plugins list
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules validate-no-send
```

Expected provider/plugin relationship:

```text
memory.provider = memory_os
plugins.enabled includes memory-os-agent-os
plugins.enabled does not include memory_os
```

`memory_os` is selected as a provider. It is not enabled as a general Hermes
plugin.

## Owner Interaction

The owner acts through the normal Hermes conversation, not a root shell.
Display labels such as `A1`, `R1`, and `F1` are transient; the durable identity
is the printed `oa_...` token.

```text
memory approve oa_<token>
memory reject oa_<token>
memory apply oa_<token>
memory feedback oa_<token> too_mechanistic
memory feedback oa_<token> like_expression
```

Hermes interprets the utterance and handles clarification. Memory-OS receives a
structured action and applies it idempotently through `OwnerActionProcessor`.

## Read-Only Dashboard

Generate and serve a bounded snapshot on port `3693`:

```bash
python scripts/memory_os_monitor_dashboard_snapshot.py \
  --hermes-home /root/.hermes \
  --profile main \
  --output monitor_dashboard/snapshot.generated.js

python scripts/serve_memory_os_monitor_dashboard.py \
  --host 0.0.0.0 \
  --port 3693 \
  --snapshot-hermes-home /root/.hermes \
  --snapshot-profile main \
  --snapshot-interval-seconds 60
```

Install it as a system service when appropriate:

```bash
sudo python scripts/install_memory_os_monitor_dashboard_service.py \
  --repo-root /opt/Hermes-Memory-OS \
  --hermes-home /root/.hermes \
  --profile main \
  --host 0.0.0.0 \
  --port 3693 \
  --python-bin /usr/bin/python3 \
  --enable
```

The dashboard is presentation-only. It has no approve, apply, execute, or send
controls.

## Architecture

```mermaid
flowchart TD
    H["Hermes Agent<br/>conversation · tools · cron · delivery"]
    I["Ingress & Source Gate<br/>events · mirrors · external evidence"]
    K["Memory Kernel<br/>working · provisional · crystallized · permanent"]
    R["Recall Engine<br/>FTS5 · vector · memory graph · entity graph · temporal · overlays"]
    X["Context Intelligence<br/>routing · projection · distillation · digests"]
    C["Cognition System<br/>Inner Drive · Deep Reflection · Imagination"]
    RB["Right-Brain Module<br/>Wandering Mind · journal · synthesis · sharing"]
    E["Evidence & Truth<br/>scoring · provenance · fact judge · contradiction"]
    G["Governance & Evolution<br/>clearance · proposals · OpsGate · owner actions"]
    O["Expression System<br/>draft · grounded judge · Speak Gate · rate limit"]
    M["Operations & Safety<br/>execution gates · cron · monitor · audit"]

    H --> I --> K
    K --> R --> H
    K --> X --> C --> RB
    RB --> E --> G --> K
    RB --> O -->|"Hermes-owned delivery"| H
    M -. "permits · receipts · health" .-> I
    M -. "permits · receipts · health" .-> G
    M -. "permits · receipts · health" .-> O
```

### Boundary summary

| Hermes owns | Memory-OS owns |
| --- | --- |
| Conversation and clarification | Canonical memory and rebuildable indexes |
| LLM/tool execution | Candidate, clearance, and stability state |
| Cron scheduler and retry | Bounded helper outputs and execution envelopes |
| Platform adapters and delivery | Owner action tokens and audited transitions |
| Origin/local channel routing | Monitor fields, receipts, and projection ledgers |

## Safety Defaults

- No direct platform sends from Memory-OS.
- No arbitrary external execution.
- No identity writes without an explicit owner-approved path.
- No unapproved crystallized-memory writes.
- No raw-turn Hindsight retain by default.
- No proposal apply without a bounded target and rollback contract.
- Sensitive mixed-scope candidate clusters fail closed.
- A lane that produces no output records why, from a closed set of reason
  codes — "no eligible input" and "processing failed" are never
  indistinguishable.
- Canonical files remain authoritative; derived indexes and substrates are
  rebuildable or retractable.
- Optional lanes are disabled, report-only, shadowed, or knob-gated until their
  promotion evidence exists.

## Repository Layout

```text
memory_os_agent/               Minimal Hermes compatibility surface
plugins/memory/memory_os/      Provider, lifecycle, retrieval, governance
plugins/memory-os-agent-os/    Hermes shell plugin and owner-review tools
plugins/system/                Runtime contracts and coordination primitives
plugins/modules/
  cognition/                   Inner Drive, Deep Reflection, Imagination,
                               Wandering Mind
  context/                     Distillation, consolidation, digests, offloading
  evidence/                    Evidence scoring and confabulation detection
  expression/                  Drafts, grounded judge, Speak Gate, rate limits
  governance/                  Candidate, truth, proposal, migration,
                               self-evolution, live-guard modules
  messaging/                   No-send mailbox boundary
scripts/                       Install, deploy, cron, monitor, and validation tools
monitor_dashboard/             Read-only operational dashboard
tests/                         Provider, module, installer, and monitor tests
docs/                          Public operator documentation
```

Start with [Quickstart](docs/quickstart.md) and
[Configuration](docs/configuration.md). Internal plans, audit notes, resolver
work, and validation history are intentionally excluded from the public
repository.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Contract and public-checkout checks:

```bash
python scripts/memory_os_import_cycle_check.py --repo-root .
python scripts/memory_os_write_surface_check.py
python scripts/memory_os_static_hygiene_check.py
python scripts/memory_os_public_checkout_probe.py --source head --strict
python scripts/memory_os_public_checkout_probe.py --source working-tree --strict
git diff --check
```

Do not treat a local test as live deployment evidence. Scheduler, owner-channel,
installer, monitor, and delivery changes require verification through their real
Hermes seam before they are described as live.

## License

MIT. See [LICENSE](LICENSE).
