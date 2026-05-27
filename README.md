# Hermes Memory-OS

Hermes Memory-OS is a file-first memory and governance runtime for long-running
Hermes agents.

It gives a Hermes profile durable memory, bounded cognition modules, owner
review, right-brain expression feedback, and operational monitor evidence
without making Memory-OS the owner of conversation, transport, or scheduling.
Hermes remains the host agent. Memory-OS provides bounded state, stable action
tokens, helper scripts, audit, and monitor evidence.

## What This Project Is

Memory-OS is for operators who want an inspectable memory substrate for Hermes:

- profile-local canonical files instead of opaque hosted storage;
- rebuildable SQLite indexes for search and prefetch;
- working memory separated from owner-approved crystallized memory;
- attribution and feedback ledgers for memory-source quality;
- owner-visible approval and feedback loops through Hermes;
- module cadence, proposal follow-up, and right-brain expression evidence;
- safe bounded apply paths for explicitly supported proposal kinds.

It is not a standalone chat server, a SaaS memory service, or a generic
executor. External sends, user conversation, cron delivery, channel selection,
origin/local routing, and natural-language interaction belong to Hermes.

## Quick Start

Install into an existing Hermes profile:

```bash
git clone <this-repo-url>
cd Hermes-Memory-OS
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --operational
```

`--operational` is the normal open-source install path. It installs and enables:

- the `memory_os` Hermes memory provider;
- the `memory-os-agent-os` Hermes shell plugin;
- portable Memory-OS runtime modules;
- heartbeat runtime;
- the current cognitive-loop integration harness;
- seven Hermes cron jobs for owner review, right-brain expression, monitor
  reports, feedback prompts, and proposal follow-up.

The installer auto-detects the owner-facing Hermes channel from
`$HERMES_HOME/channel_directory.json`. Telegram is used only when Telegram is
the configured owner channel. Other installs can resolve to Discord, Signal,
Slack, Matrix, or another configured platform. Background jobs use
`deliver=local` with no agent where appropriate; right-brain expression uses
Hermes `deliver=origin`.

Interactive install is also available:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh
```

Conservative install without the operational cron set:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --production-safe
```

Install helpers but do not enable recurring cron jobs:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --operational \
  --no-enable-owner-cron-onboarding
```

The installer does not restart `hermes-gateway.service`.

## What Gets Scheduled

The operational preset creates or verifies this Hermes cron set:

| Job | Deliver | Agent | Purpose |
| --- | --- | --- | --- |
| `memory-os-owner-review-digest` | owner channel | yes | sends only approval items and real alerts to the owner |
| `memory-os-right-brain-expression` | `origin` | yes | low-frequency right-brain expression through Hermes |
| `memory-os-module-cadence-report` | `local` | no | records module generated/skipped/error/duplicate counters |
| `memory-os-right-brain-expression-outcome` | `local` | no | records expression outcomes for feedback linkage |
| `memory-os-proposal-followups-opsgate` | `local` | no | routes approved proposals through OpsGate/report-only follow-up |
| `memory-os-expression-feedback-request` | owner channel | yes | asks for tokenized right-brain expression feedback |
| `memory-os-memory-sources-feedback-request` | owner channel | yes | asks for tokenized MemorySources feedback |

Hermes owns the scheduler, transport, retry behavior, origin/local routing, and
agent wording. Memory-OS owns the helper outputs, tokens, state transitions,
audit, and monitor fields.

## Verify

After install:

```bash
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes plugins list
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules status
```

Expected relationship:

```text
memory.provider = memory_os
plugins.enabled includes memory-os-agent-os
plugins.enabled does not include memory_os
```

`memory_os` is selected through `memory.provider`. It should not be enabled as a
general Hermes plugin.

Useful operator checks:

```bash
HERMES_HOME=/root/.hermes hermes memory-os-agent-os memory-sources stats --hours 24
HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules validate-no-send
```

## Owner Interaction

Owner review and feedback happen in the normal Hermes conversation channel. The
owner should not need a root shell to approve Memory-OS items.

Digest labels such as `A1`, `R1`, and `F1` are display-only list numbers. The
durable identity is the printed `oa_` action token.

Examples of owner utterances:

```text
memory approve oa_<token>
memory reject oa_<token>
memory apply oa_<token>
memory feedback oa_<token> too_mechanistic
memory feedback oa_<token> like_expression
```

Hermes interprets the owner utterance, asks follow-up questions when ambiguous,
and calls the structured Memory-OS review tool. Memory-OS applies only stable
tokens through the owner action state machine.

Approving a proposal does not execute work. It moves the proposal into
human-controlled follow-up. Only proposal kinds with a bounded runtime target,
rollback, monitor fields, and an explicit apply token can be applied.

## Safety Model

Memory-OS keeps these boundaries by default:

- no direct platform sends from Memory-OS;
- no external execution;
- no identity writes without explicit owner-approved path;
- no unapproved crystallized memory writes;
- no Hindsight export;
- no cleanup or shadow-journal apply without a separate gate.

Canonical data lives under the Hermes profile. SQLite indexes are rebuildable.
Review, feedback, and apply operations are audited.

## Architecture

```text
Hermes agent
  owns conversation, LLM interaction, cron, delivery, origin/local routing,
  clarification, transport, retry, and channel adapters

Memory-OS provider
  owns profile-local canonical memory, indexes, prefetch, sync_turn,
  working memory, crystallized candidates, and audit

Memory-OS Agent OS shell
  exposes operator status, doctor, module, feedback, and review tools

Portable modules
  produce bounded artifacts: evidence scores, proposals, expression drafts,
  cadence reports, feedback signals, and OpsGate reports

OwnerActionProcessor
  is the state-changing entry point for approve, reject, feedback, allow,
  and bounded apply actions
```

## Repository Layout

```text
agent/                         Minimal Hermes compatibility surface
plugins/memory/memory_os/      Memory-OS provider and core services
plugins/memory-os-agent-os/    Hermes shell plugin and review tools
plugins/system/                Module contracts and coordination primitives
plugins/modules/               Portable cognition/governance/expression modules
scripts/                       Installer, monitor, cron helpers, validation
tests/                         Provider, module, installer, and monitor tests
docs/                          Public operator docs
```

Normal users should start with [docs/quickstart.md](docs/quickstart.md) and
[docs/configuration.md](docs/configuration.md). Internal development notes and
validation history are intentionally excluded from the public upload.

## Development

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the main test suite:

```bash
python -m pytest -q
```

Installer and closure checks:

```bash
python -m pytest tests/scripts/test_memory_os_plugin_install.py \
  tests/scripts/test_memory_os_owner_cron_onboarding.py -q
git diff --check
```

Before changing scheduler, owner review, feedback, installer, module closure,
or live monitor behavior, verify the owning interface and run the relevant
checks. Internal closure-matrix documents are not part of the public upload.
Do not rely on conversation history as the source of truth.

## Current Maturity

The operational baseline has live validation evidence:

- operational installer path completed;
- seven Hermes cron jobs present and enabled;
- owner channel auto-detected from `channel_directory.json`;
- monitor status `PASS` with no WARN/FAIL at the latest recorded validation;
- owner-approved crystallized memory, feedback ledger, proposal follow-up, and
  bounded expression policy apply have live evidence.

This does not mean Memory-OS is a generic autonomous executor. New proposal
kinds require their own bounded apply contract, rollback, monitor fields, and
owner-visible workflow.

## License

MIT License. See [LICENSE](LICENSE).
