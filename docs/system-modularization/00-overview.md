# Hermes System Modularization Overview

Date: 2026-05-20

## Position

Memory-OS v0 solved the L1 memory-layer modularization problem. It can be
installed as a Hermes memory provider, discovered by a blank Hermes host, and
validated on `10.20.3.200` without touching production.

The next architecture problem is broader: the rest of the Hermes operating
system is not yet equally portable.

```text
Current asymmetry:
  Memory-OS                     installable module
  Wandering Mind                production cron / prompt / state shape
  Self-Evolution Governor       skill scripts + cron + state files
  Evidence and scoring          governor-owned artifacts
  Ops-Gate / Proposal Queue     scripts + YAML state + cron output
  mailbox                       platform plugin plus local state conventions
  household digest              scripts + cron + state files
```

This means an empty Hermes host can now get the memory layer, but it cannot yet
install the full cognition, governance, mailbox, and expression stack as a
coherent product.

## Read-Only Audit Basis

The initial assessment was collected from `10.20.2.88 / YC-NAS` on
2026-05-20 using read-only SSH inspection.

Observed facts:

- Main Hermes runs from `/vol1/.hermes/hermes-agent`.
- Main profile home is `/vol1/.hermes`.
- Sannai gateway uses a separate profile home:
  `/vol1/.hermes/profiles/sannai`.
- Main and Sannai gateways are separate user services.
- Existing higher-layer systems are spread across cron jobs, skill scripts,
  gateway plugins, profile scripts, and state directories.
- The production worktree is dirty and includes local-only additions and
  backups, so it is not a clean distributable source of truth.
- A previous Self-Evolution modularization attempt exists at
  `/vol1/1000/hermes-self-evolution/`. It is useful as reference material, but
  it is not the whole target architecture.

No production files were modified, no gateways were restarted, and no private
session bodies or secrets were copied into this repository.

## Goal

Create a portable Hermes system architecture where a blank host can install:

```text
L0 infrastructure adapters
L1 Memory-OS
L2 cognition modules
L3 governance modules
L4 expression and delivery modules
```

The result should be usable on `10.20.3.200` before any production migration is
considered.

## Non-Goals

- Do not replace `10.20.2.88` production systems during v0.1.
- Do not copy production cron jobs verbatim as the final design.
- Do not modularize Sannai's private personality/growth system. Public modules
  only need to be compatible with her profile boundary.
- Do not make a system prompt patch the integration mechanism.
- Do not let test modules send Telegram or mailbox messages by default.
- Do not write production Hindsight, production identity sources, or production
  Sannai state.
- Do not commit copied production snapshots, raw sessions, prompts, private
  bodies, tokens, cookies, or API keys.

## Target Module Families

```text
plugins/
├── memory/
│   └── memory_os/
├── cognition/
│   ├── inner_drive/
│   └── wandering_mind/
├── governance/
│   ├── self_evolution/
│   ├── ops_gate/
│   └── proposal_queue/
├── evidence/
│   └── scoring/
├── messaging/
│   └── mailbox/
├── context/
│   └── household_digest/
└── expression/
    └── speak_gate/
```

The directory names above are conceptual package families. The exact physical
layout can follow Hermes' plugin loader constraints, but the lifecycle and
interfaces must remain explicit.

## Key Architectural Correction

The higher-level systems must not remain "things that only live on
`10.20.2.88`". They should become installable modules with:

- manifest metadata
- dependency declarations
- enable / disable lifecycle
- status and doctor commands
- dry-run or no-send mode
- per-profile config
- profile-local data roots
- upgrade-safe data retention

Memory-OS remains the shared L1 substrate. Higher layers depend on Memory-OS
through narrow read and write interfaces instead of reading arbitrary production
paths.

## End-to-End Trace

This trace is the reference shape for v0.1. Individual modules may be disabled,
but the call order and boundaries should remain recognizable.

Example: a user sends a normal foreground message.

```text
1. gateway receives user message
2. active memory provider prefetches bounded context from Memory-OS
3. foreground model replies
4. Memory-OS sync_turn appends a user/assistant event
5. ModuleBus publishes event_available(profile)
6. next heartbeat tick acquires ScheduleCoordinator lock
7. inner_drive reads new event summaries
8. inner_drive updates working memory
9. inner_drive may create crystallized candidates
10. evidence/scoring may attach explainable evidence refs
11. proposal_queue may pick up eligible governance candidates
12. governance feedback writes summary-only Memory-OS events for proposal,
    ops-gate, scoring, and self-evolution outcomes
13. continuity context selector may expose bounded governance context on later
    foreground turns
14. speak_gate evaluates whether anything would be said
15. DeliverySink records would_send only in v0.1
16. audit records module decisions and lock outcomes
```

Example: weekly Wandering Mind run.

```text
1. scheduler triggers cognition/wandering_mind
2. wandering_mind checks household_digest dependency through ModuleBus
3. ScheduleCoordinator acquires wandering_mind weekly lock
4. wandering_mind reads recent events, working summary, approved crystallized
5. output is either free-form text or [SILENT]
6. MemoryOSWriteSink writes an event or candidate
7. DeliverySink records would_send only unless explicitly enabled
8. audit records dependency health, output mode, and no-send result
```

Memory-OS carries data. ModuleBus and ScheduleCoordinator carry runtime control
signals. Do not overload Memory-OS into a control plane.

## Governance Feedback Loop

The left-brain governance stack must be visible to future memory and
conversation turns without becoming self-modifying or noisy.

Required loop:

```text
Memory-OS events
  -> evidence/scoring
  -> ops_gate / proposal_queue / self_evolution
  -> summary-only governance feedback events
  -> continuity context selector / owner review
  -> approved crystallized memory only after explicit approval
```

Governance reports, evidence scores, ops-gate decisions, and proposal
transitions are not just local artifacts. They are also memory-relevant facts
about what the system considered, deferred, blocked, or proposed.

Boundary:

- governance feedback may append summary-only Memory-OS events
- governance feedback may add bounded context for later sessions
- governance feedback may create proposal/candidate surfaces
- governance feedback must not directly write identity, relationship memory, or
  approved crystallized records
- governance feedback must not become hidden instructions to the foreground
  model
- governance feedback must not pull private Sannai state into the main
  evolution loop

## Sannai Boundary

Sannai is not a public moduleization target for this project.

Her existing private continuity, identity, heartbeat, and curation surfaces are
treated as compatibility constraints:

- module code must preserve profile isolation
- module code must not require Sannai-private files
- module code must not emit Sannai messages by default
- module code must not write Sannai identity or long-term memory
- future Sannai integration, if any, must be an owner-approved private adapter

This keeps the public architecture reusable while respecting that Sannai is a
private deployment, not product scaffolding.

## Document Set

```text
docs/system-modularization/
├── 00-overview.md
├── 01-plugin-architecture.md
├── 02-existing-system-audit.md
├── 03-module-extraction-plan.md
├── 04-migration-path.md
└── 05-validation-on-3.200.md
```

This document set is the v0.1 system-modularization plan. It extends the
Memory-OS v0 closeout; it does not reopen the v0 memory-provider work.
