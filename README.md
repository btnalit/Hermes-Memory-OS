# Hermes Memory-OS

Hermes Memory-OS is a file-first memory and agent-OS runtime for long-running
Hermes agents.

It is built for one practical problem: a long-running agent should remember
stable facts, carry useful context across sessions, and run bounded reflection
or governance loops without turning every temporary guess into permanent memory
or taking actions on its own.

The design is deliberately conservative:

- canonical memory lives in profile-local files;
- SQLite is a rebuildable index, not the source of truth;
- runtime cognition and governance modules write bounded artifacts;
- owner approval remains required for crystallized memory;
- send, execute, identity writes, Hindsight export, cleanup apply, and shadow
  journal apply are off by default.

This repository is intentionally extracted as a clean project. It does not
vendor the full Hermes agent manager source tree.

## What It Solves

Memory-OS is for Hermes operators who need more than chat-window context:

- keep durable memory in inspectable profile-local files;
- keep transient work separate from approved long-term memory;
- make memory injection explainable through context routing and attribution;
- let cognitive modules run in no-send / no-execute test-host mode;
- preserve owner approval for crystallized memory and identity changes.

It is not a hosted memory service, a SaaS backend, or an auto-action framework.
The default posture is observe, report, and ask for owner approval.

## Quick Start

For a normal operator, start with the interactive installer:

```bash
export HERMES_HOME=/root/.hermes
bash scripts/install_memory_os.sh
```

For a no-send test host that enables the full observation stack:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host
```

`--test-host` also installs and enables the owner review digest through Hermes
cron by default. Hermes owns the scheduled delivery; Memory-OS only renders the
bounded review text and stable owner-action tokens.

For a conservative profile where DeepReflection and attribution are explicitly
safe/off unless later enabled:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --production-safe
```

After install:

```bash
HERMES_HOME=/root/.hermes hermes memory
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

Short operator docs:

- [Quickstart](docs/quickstart.md)
- [Configuration](docs/configuration.md)
- [Test-host monitor](docs/system-modularization/19-memory-os-3-200-monitor.md)

Owner review digests show display numbers such as `A1`, `R1`, and `F1` for
scanning only. Approval commands must use the stable token printed in the
digest, for example `memory approve oa_<token>` or `memory reject oa_<token>`.
Hermes cron owns delivery and transport; Memory-OS owns bounded digest rendering
and the owner action state machine.

## Project Status

The v0 Memory-OS provider is closed and validated. The v0.1 Agent OS work adds
portable higher-layer modules and an official-style Hermes plugin shell while
keeping the provider path authoritative.

Implemented and tested:

- `memory_os` Hermes memory provider
- local filesystem store with event, working, crystallized candidate, identity,
  relationship, audit, import, and quarantine roots
- SQLite runtime index with heartbeat catch-up
- indexed prefetch and diagnostic grounding
- `memory_os_status` tool contract for current provider/backend facts
- runtime heartbeat from events to working memory and review candidates
- dry-run-first cleanup and shadow journal ingestion
- portable L2-L4 module runtime:
  - mailbox no-send
  - household digest
  - wandering mind
  - inner drive
  - ops gate
  - proposal queue
  - evidence/scoring
  - self-evolution governor
  - speak gate
  - governance feedback bridge
  - DeepReflection baseline
- official-style `memory-os-agent-os` shell plugin:
  - `hermes memory-os-agent-os status`
  - `hermes memory-os-agent-os doctor`
  - `hermes memory-os-agent-os low-clue-recall dry-run`
  - `hermes memory-os-agent-os memory-sources last/history/stats/feedback`
  - `hermes memory-os-agent-os modules status/doctor/run-once`
  - `hermes memory-os-agent-os modules validate-no-send`
  - `hermes memory-os-agent-os modules deep_reflection preview-current/history`
  - minimal session marker hooks

See:

- `docs/memory-os/v0-closeout.md`
- `docs/system-modularization/07-validation-report-10.20.3.200.md`
- `docs/system-modularization/17-deep-reflection-runtime-design.md`
- `docs/system-modularization/19-hermes-official-plugin-compatibility.md`
- `docs/system-modularization/19-memory-os-3-200-monitor.md`
- `docs/system-modularization/30-hermes-upgrade-compatibility-gate.md`

## Architecture

Memory-OS is provider-first.

```text
Hermes memory.provider=memory_os
  -> plugins/memory/memory_os/
     -> canonical profile-local Memory-OS files
     -> rebuildable SQLite index
     -> prefetch / sync_turn / memory_os_status / heartbeat

Hermes general plugin shell
  -> plugins/memory-os-agent-os/
     -> operator-facing status/doctor aliases
     -> bounded session marker hooks
     -> no carryover injection
     -> no send / execute / identity / crystallized approval

Portable module runtime
  -> plugins/system/
  -> plugins/modules/
  -> installed under $HERMES_HOME/memory-os/runtime/python/plugins/
```

`memory_os` is not meant to be enabled as a general Hermes plugin. It is enabled
through:

```yaml
memory:
  provider: memory_os
```

`memory-os-agent-os` is the optional official-style shell plugin. It is enabled
through `plugins.enabled` for operator discoverability and shell aliases.

## Repository Layout

```text
agent/                         # Minimal Hermes compatibility surface
plugins/memory/memory_os/      # Memory-OS provider and core services
plugins/memory-os-agent-os/    # Official-style Hermes shell plugin
plugins/system/                # Module contracts and coordination primitives
plugins/modules/               # Portable L2-L4 modules
scripts/                       # Installer and operator scripts
tests/                         # Provider, runtime, module, and installer tests
docs/memory-os/                # v0 architecture and implementation records
docs/system-modularization/    # v0.1 Agent OS, RH, DR, and validation docs
```

## Install

Use a target Hermes profile home:

```bash
export HERMES_HOME=/root/.hermes
```

Recommended interactive installer:

```bash
bash scripts/install_memory_os.sh
```

The interactive installer:

- discovers existing Hermes home candidates from `HERMES_HOME`, `~/.hermes`,
  and `/root/.hermes`;
- prints current provider, shell plugin, runtime, and heartbeat timer state;
- installs/updates the `memory_os` provider as the required base component;
- asks which optional parts to install or enable:
  - `memory-os-agent-os` shell plugin
  - `memory.provider=memory_os`
  - `plugins.enabled: memory-os-agent-os`
  - portable L2-L4 system modules
  - heartbeat runtime artifacts
  - heartbeat timer
  - owner review Hermes cron helper and recurring delivery gate
  - DeepReflection preset
- delegates writes to `scripts/install_memory_os_plugin.py`;
- when enabled, creates the daily owner review job through Hermes cron
  `--script --deliver` in agent mode rather than a Memory-OS transport path;
  Hermes turns the bounded Memory-OS review brief into owner-facing wording and
  handles interaction;
- verifies provider and shell status after install;
- does not restart `hermes-gateway.service`;
- does not run cleanup apply or shadow-journal apply.

Non-interactive test-host install:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host
```

Override the owner review cron target or disable it:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host \
  --owner-review-cron-schedule "0 9 * * *" \
  --owner-review-cron-deliver telegram

HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host \
  --no-enable-owner-review-cron
```

For non-test-host installs, the owner review delivery target defaults to
`origin`, which asks Hermes cron to deliver back through Hermes' origin/home
channel semantics. `--test-host` resolves the default to `telegram` because the
`10.20.3.200` validation host uses Telegram as its owner channel.

Non-interactive production-safe install:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --production-safe
```

Advanced provider install with the Python installer. This requires the `hermes`
CLI in `PATH` when `--enable` is used:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home "$HERMES_HOME" \
  --enable \
  --install-runtime \
  --enable-runtime
```

Full Agent OS test-host install:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home "$HERMES_HOME" \
  --enable \
  --enable-shell \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --runtime-interval 5min \
  --deep-reflection-preset test-host
```

Test-host compatibility wrapper:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os_test_host.sh
```

The wrapper delegates to `scripts/install_memory_os.sh --yes --test-host`.

Production-safe DeepReflection preset:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home "$HERMES_HOME" \
  --enable \
  --enable-shell \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --deep-reflection-preset production-safe
```

Installer behavior:

- copies the `memory_os` provider to `$HERMES_HOME/plugins/memory_os/`;
- copies the `memory-os-agent-os` shell to
  `$HERMES_HOME/plugins/memory-os-agent-os/` unless `--no-install-shell` is
  passed;
- enables the provider only when `--enable` is passed;
- enables the shell only when `--enable-shell` is passed;
- writes heartbeat runtime artifacts when `--install-runtime` is passed;
- enables the user systemd heartbeat timer when `--enable-runtime` is passed;
- installs portable modules when `--install-system-modules` is passed;
- installs owner review cron helper/gate scripts and, unless disabled, enables
  the Hermes cron owner review job from the shell installer;
- keeps Memory-OS backup manifests out of `$HERMES_HOME/plugins/`; backups
  belong under `$HERMES_HOME/plugin-backups/`.

## Verify

Provider checks:

```bash
HERMES_HOME="$HERMES_HOME" hermes memory
```

`memory_os` is selected through `memory.provider`; it is not expected to appear
as a top-level `hermes memory_os ...` command on current Hermes builds.

Shell plugin checks:

```bash
HERMES_HOME="$HERMES_HOME" hermes plugins list
HERMES_HOME="$HERMES_HOME" hermes memory-os-agent-os status
HERMES_HOME="$HERMES_HOME" hermes memory-os-agent-os doctor
HERMES_HOME="$HERMES_HOME" hermes memory-os-agent-os modules status
HERMES_HOME="$HERMES_HOME" hermes memory-os-agent-os modules doctor
HERMES_HOME="$HERMES_HOME" hermes memory-os-agent-os modules run-once \
  --module cron_mirror --dry-run
HERMES_HOME="$HERMES_HOME" hermes memory-os-agent-os modules validate-no-send
```

When the shell plugin is installed under the default Hermes home, the shell
aliases also infer their home from their plugin path:

```bash
hermes memory-os-agent-os status
hermes memory-os-agent-os doctor
hermes memory-os-agent-os modules status
```

Useful operator aliases:

```bash
hermes memory-os-agent-os low-clue-recall dry-run --query "继续昨天那个"
hermes memory-os-agent-os memory-sources last
hermes memory-os-agent-os memory-sources stats --hours 24
hermes memory-os-agent-os modules deep_reflection preview-current
```

Expected plugin relationship:

```text
memory.provider = memory_os
plugins.enabled includes memory-os-agent-os
plugins.enabled does not include memory_os
```

Regression checks:

```bash
python scripts/memory_os_upgrade_compat_check.py --host hermes-media --output summary
python scripts/memory_os_3_200_monitor.py --host hermes-media --output summary
```

## DeepReflection Presets

`scripts/install_memory_os_plugin.py` supports these presets:

| Preset | Purpose |
| --- | --- |
| `production-safe` | Explicitly disabled; safe default for formal profiles. |
| `observe` | Dry-run only; creates observation artifacts without injection. |
| `auto-bounded` | Bounded deterministic carryover injection only. |
| `test-host` | Enables no-send test observation outputs such as self-evolution proposals and wandering seeds. |

The following remain disabled unless a future gate explicitly changes them:

- `working_updates_enabled`
- `llm_enabled`
- real sends
- real executes
- identity writes
- crystallized approval
- Hindsight export

## Run Tests

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

Current local baseline after the Agent OS shell installer integration:

```text
433 passed
```

## Safety Defaults

- Files are canonical; SQLite is a rebuildable index.
- Runtime heartbeat creates working items and review candidates only.
- Crystallized records require explicit owner approval.
- Diagnostic grounding is restricted to explicit current
  architecture/provider/status questions.
- DeepReflection carryover is injected only through the provider prefetch path;
  the shell plugin does not register `pre_llm_call`.
- Shell hooks write bounded audit markers only.
- Cleanup and shadow journal ingestion are dry-run-first.
- No module sends messages, executes actions, writes identity, approves
  crystallized memory, or exports to Hindsight by default.

## Monitoring

The test-host monitor is documented in
`docs/system-modularization/19-memory-os-3-200-monitor.md`.

It is read-only. It checks service health, provider status, shell plugin state,
shell aliases without explicit `HERMES_HOME`, modules alias parity, doctor
output, status-tool contract, context-router mode, low-clue recall probes,
Memory Sources attribution health, DeepReflection source-class distribution,
backup-manifest pollution, and session hook audit markers. It must not restart
services, run heartbeat catch-up, invoke hooks, force `/new`, apply cleanup,
apply shadow journals, or read private transcripts.

## License

MIT License. See [LICENSE](LICENSE).
