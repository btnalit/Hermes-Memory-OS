# 33 - Development Process Retrospective

Status: active process record
Date: 2026-05-25
Scope: Memory-OS v0.1 development process, dynamic closure failures, and the
operator workflow that should guide future RH/module work.

## Purpose

This document records what the Memory-OS development process taught us. It is
not a feature design. It is a process hardening record for future Codex work.

The project showed strong implementation velocity, but it also exposed a
repeatable weakness: local implementation and local tests often moved faster
than the live feedback loop. Several issues were only corrected after real
Telegram usage, the `10.20.3.200` monitor, and owner review forced the system
back to the actual runtime path.

The goal of this document is to preserve the lessons before they fade into
general "be careful" advice.

## What Worked Well

### Real Test Host Pressure

The `10.20.3.200` host was not a demo environment. It exposed real runtime
issues that local tests did not catch:

- shell-plugin import path problems after installation;
- foreground task drift during small-context compression;
- live Telegram low-clue recall behavior diverging from dry-run assumptions;
- monitor fields missing for real promotion decisions;
- SessionMirror pending coverage that was invisible until monitor support was
  added;
- RH-31 eval findings that were measurement issues rather than live bugs.

This validated the principle that Memory-OS cannot be judged by unit tests
alone. The real contract is:

```text
provider -> ingress -> prefetch -> context router -> MemorySources -> monitor
-> live operator behavior
```

### Boundary Discipline

The system stayed conservative while new modules were added:

- no automatic send;
- no automatic execute;
- no identity write;
- no crystallized approval without owner;
- no Hindsight export by default;
- MemorySources and RH-31 reports stayed bounded and forbidden-field clean.

This was the strongest part of the project. Even when behavior quality was
wrong, the hard safety boundaries generally remained intact.

### Contract Emergence

The project eventually produced durable governance artifacts:

- `29-memory-os-module-integration-contract.md`
- `32-active-roadmap-and-gates.md`
- `19-memory-os-3-200-monitor.md`
- `07-validation-report-10.20.3.200.md`

These documents turned scattered RH items into a managed system:

- 29 defines the module contracts.
- 32 keeps the active queue visible.
- 19 defines the monitor evidence surface.
- 07 records live evidence and deployment proof.

### Monitor Maturity

The monitor evolved from a health check into a development steering surface.
It now tracks:

- gateway, heartbeat, doctor, index, and status-tool contract;
- cognitive loop status and boundaries;
- audit density and action distribution;
- module artifacts;
- MemorySources attribution and forbidden-field checks;
- RH-31 eval summary;
- hook coverage;
- automatic expression artifacts;
- SessionMirror coverage.

This made "observe" a real engineering state instead of a waiting period.

### Finding-To-Fixture Discipline

Later RH-28 and RH-31 work improved the closure process:

- live findings were first assigned to the owning live module;
- scorecard failures were treated as measurement signals until backed by live
  evidence;
- topic-specific hardcoding was rejected;
- fixes were moved toward generic ingress, projection, source diversity, or
  monitor evidence.

## Process Failures

### Contracts Arrived Too Late

Several modules were implemented before their integration contract was clear.
This caused repeated priority conflicts:

- RH-25 current task anchor;
- RH-26 context router;
- RH-28 low-clue recall;
- RH-29 MemorySources attribution;
- RH-31 eval harness.

The cost was not just rework. The cost was unclear ownership: when live
behavior failed, the system had to rediscover whether the problem belonged to
ingress, projection, write surfaces, feedback, scheduler, monitor, or eval.

Future rule:

```text
No new module, RH, scheduler step, live decision path, or LLM judge mode starts
without a contract row and monitor signal.
```

### Local PASS Was Overvalued

Multiple issues passed local tests but failed the real path:

- Telegram low-clue recall surfaced candidate-quality failures.
- Session search and recall guard interactions were not covered by dry-run
  alone.
- RH-31 initially reported a candidate-boundary miss that was actually fixture
  and adapter drift.

Future rule:

```text
Local tests prove implementation. They do not prove live behavior.
```

Any bug that was found through Telegram, monitor, installer, systemd, or the
deployed shell path must close with a comparable live or integration signal.

### Observation Gates Were Sometimes Time-Only

Early plans sometimes said "observe for 24h" or "observe for 7 days" without
enough event-volume and stop/promotion criteria.

This delayed action without improving knowledge.

Future rule:

```text
An observation gate must define:
- elapsed time, if relevant;
- minimum event volume;
- PASS/WARN/FAIL signals;
- promotion signal;
- stop/fix signal.
```

### Monitor Lagged Behind Features

The project repeatedly added monitor fields after the feature was already live:

- audit density after cognitive loop noise;
- module artifacts after scheduler activation;
- expression artifacts after Wandering Mind was producing would-send outputs;
- hook coverage after shell hooks existed;
- SessionMirror coverage after pending sessions mattered.

Future rule:

```text
If a feature needs observation, monitor fields are part of the feature, not a
follow-up polish item.
```

### External Review Was Sometimes Used At The Wrong Layer

Claude review was useful for design, boundary, and apply decisions. It was less
useful when used as a substitute for local diagnosis or live evidence.

Future rule:

Use external review for:

- apply decisions;
- live behavior changes;
- owner-boundary changes;
- architecture contracts;
- public-facing claims.

Do not block read-only monitor improvements on external review when the local
contract, tests, and live read-only evidence are already clear.

### Task Queue Drifted

Before `32-active-roadmap-and-gates.md`, planned work lived across many docs:

- `08` runtime hardening;
- `23` cognitive loop;
- `25` memory sources roadmap;
- `28` low-clue recall;
- `29` contract;
- `31` eval harness.

Important items such as automatic expression, LLM judge observation, session
injection, and SessionMirror coverage became easy to forget.

Future rule:

```text
The active roadmap is the visible queue. If a task is not in the roadmap, it is
not an active task.
```

## Dynamic Closure Protocol

Use this protocol for future Memory-OS work and for other complex long-running
projects.

### 1. Identify The Finding Type

Classify the work before editing:

| Type | Meaning | Required closure |
| --- | --- | --- |
| Live behavior finding | User-facing behavior was wrong in Telegram/CLI/gateway | live or realistic integration repro plus regression |
| Contract gap | A module lacks declared read/write/decision/monitor ownership | contract update before implementation |
| Monitor gap | Behavior exists but cannot be observed safely | monitor field plus classification rule |
| Eval finding | Scorecard reports failure | fixture/adapter attribution before live guard |
| Installer/deploy finding | Installed path fails or diverges from local path | installed-path validation |
| Documentation drift | Docs promise behavior not present in code/live | reconciliation update |

### 2. Map The Owning Contract

Every finding must map to exactly one owning fix path:

- IngressDecision
- ContextProjection
- MemoryWriteSurface
- FeedbackSignal
- SchedulerStep
- MonitorEvidence
- HermesUpgradeCompatibility

A finding may be mentioned in multiple documents, but the fix must have one
owner.

### 3. Build A Feedback Loop

Use the smallest loop that matches the finding:

| Finding source | Minimum loop |
| --- | --- |
| pure code behavior | focused unit or public-interface test |
| provider/prefetch behavior | provider integration test |
| monitor classification | monitor fixture test plus real read-only run |
| installed shell path | installed CLI/shell command on test host |
| Telegram behavior | real Telegram retest or owner-supplied transcript plus matching dry-run |
| scheduler behavior | completed cycle plus monitor evidence |

Do not close with a weaker loop than the one that found the issue.

### 4. Implement The Smallest Owning Fix

Prefer fixing the seam over duplicating guards in callers.

Examples:

- same phrase routes differently: fix IngressDecision;
- output differs from route report: fix ContextProjection;
- candidate leaks as approved memory: fix MemoryWriteSurface;
- owner correction reinforces bad shortlist: fix FeedbackSignal;
- scheduler runs but cannot be observed: fix MonitorEvidence;
- installed shell path fails: fix installer/shell import seam.

### 5. Update Evidence

For Memory-OS, a closed P1 should normally update:

- code and tests;
- owning design or contract doc;
- `07-validation-report-10.20.3.200.md` if live/test-host evidence changed;
- `32-active-roadmap-and-gates.md` if status or next action changed.

### 6. Decide Whether External Review Is Needed

Claude or another reviewer is most valuable when the next action changes live
state or public claims.

Ask for review before:

- one-time apply;
- recurring scheduler/apply enablement;
- LLM judge bounded-live mode;
- any owner-boundary relaxation;
- public documentation claims that depend on interpretation.

Do not require external review before:

- read-only monitor fields;
- local fixture repair;
- documentation reconciliation;
- no-behavior refactors with tests.

## Codex Process Changes

This retrospective led to three operator-level changes:

1. Add a global AGENTS section for dynamic closure.
2. Add a Codex skill named `evidence-driven-dynamic-closure`.
3. Enable that skill in Codex config.

The skill should trigger on:

- complex bug fixes;
- live behavior drift;
- module/RH work;
- monitor/eval/installer changes;
- any task where "local pass" may not equal "live pass."

## Success Criteria For The New Process

The process is working when:

- a new RH/module starts with contract and monitor ownership;
- live findings are not closed with local-only tests;
- observation gates include event volume and stop signals;
- roadmap state stays current;
- external review is used at real apply/boundary decision points;
- fewer issues are discovered only after owner frustration in Telegram.

## What Not To Do

- Do not turn this into heavy ceremony for tiny edits.
- Do not block read-only monitor improvements on external review.
- Do not replace live evidence with more documentation.
- Do not let the active roadmap become a second implementation plan.
- Do not add topic-specific hardcodes to close generic recall problems.

## Current Decision

Adopt the dynamic closure protocol as the default Memory-OS development style.
Use it in future work before adding RH-32, RH-33, LLM judge bounded-live mode,
recurring mirror apply, or public claims about system maturity.
