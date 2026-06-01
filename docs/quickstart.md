# Memory-OS Quickstart

This is the shortest path for installing and verifying Memory-OS on an existing
Hermes profile.

## 1. Choose A Hermes Home

Use the Hermes profile you want Memory-OS to manage:

```bash
export HERMES_HOME=/root/.hermes
```

The installer can discover common homes, but setting `HERMES_HOME` keeps the
target explicit.

## 2. Install

One-command operational install for an existing Hermes profile:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --operational \
  --hindsight auto
```

This installs and enables the Memory-OS provider, the Hermes Agent OS shell,
the portable runtime, heartbeat, the current cognitive loop harness, and the
seven-node Hermes cron operational set. Owner-facing cron jobs use Hermes
`channel_directory.json` autodiscovery, so Telegram is selected only when it is
the configured owner channel. Right-brain expression uses `deliver=origin`, and
background maintenance jobs use `deliver=local` / no-agent.

Interactive install:

```bash
bash scripts/install_memory_os.sh
```

Use `--no-enable-owner-cron-onboarding` if you want helper scripts installed
but no recurring jobs. Hermes owns scheduled delivery, platform transport, and
final owner-facing wording in agent mode; Memory-OS only renders bounded briefs,
tokens, state transitions, audit, and monitor evidence.

Production-safe install:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --production-safe \
  --hindsight off
```

Hindsight adoption is explicit. Use `--hindsight off` for a fresh open-source
install. Use `--hindsight auto` when an existing Hermes profile already has a
Hindsight config and you want Memory-OS to adopt it into governed shadow mode.
The direct Hermes `memory.provider=hindsight` path is not used by Memory-OS.
Hindsight, when enabled, is a Memory-OS governed substrate with raw-turn retain
disabled and recall kept advisory.

Automated deployment wrapper examples:

```bash
# Fresh host, local execution on the target:
python scripts/deploy_memory_os.py \
  --hermes-home /root/.hermes \
  --profile fresh \
  --phase apply \
  --mode production-safe \
  --hindsight off

# Existing Hermes + Hindsight host, remote orchestration:
python scripts/deploy_memory_os.py \
  --host hermes-media \
  --remote-repo-root /opt/Hermes-Memory-OS \
  --hermes-home /root/.hermes \
  --profile upgrade \
  --phase dry-run \
  --mode operational \
  --hindsight auto
```

The installer does not restart `hermes-gateway.service`.

## 3. Verify

```bash
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes plugins list
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules status
```

Expected state:

```text
memory.provider = memory_os
memory-os-agent-os = enabled general plugin
memory_os = not enabled as a general plugin
doctor.status = ok
```

Current Hermes builds select Memory-OS through `memory.provider=memory_os`.
They do not need to expose `hermes memory_os ...` as a top-level command.

## 4. What Gets Installed

- `memory_os` provider under `$HERMES_HOME/plugins/memory_os/`
- optional `memory-os-agent-os` shell plugin under
  `$HERMES_HOME/plugins/memory-os-agent-os/`
- optional portable module runtime under
  `$HERMES_HOME/memory-os/runtime/python/`
- optional heartbeat and cognitive-loop systemd user units under
  `$HERMES_HOME/memory-os/systemd/`
- optional Memory-OS Hermes cron onboarding under `$HERMES_HOME/scripts/`; the
  operational preset creates the seven-node cron set unless explicitly disabled

Backups belong under `$HERMES_HOME/plugin-backups/`, not under
`$HERMES_HOME/plugins/`.

## 5. Safety Defaults

Memory-OS does not automatically send messages, execute external actions, write
identity, approve crystallized memory, export to Hindsight, apply cleanup, or
apply shadow journals.

The operational preset enables runtime loops and Hermes cron jobs, but it does
not enable direct Memory-OS sends, external execution, identity writes, or
unapproved crystallized approvals.

## 6. Owner Review Via Hermes Agent

Owner review digests use short display anchors such as `A1`, `R1`, and `F1` to
make the list readable. Those anchors are not durable approval identities.

The normal path is conversational: reply in the same Hermes channel where the
digest appears. Hermes interprets your intent, asks when ambiguous, and calls
Memory-OS with structured `memory_os_review_reply` arguments. Memory-OS does
not require a root shell command for owner approval.

Stable-token owner utterance examples:

```text
memory approve oa_<token>
memory reject oa_<token>
memory allow oa_<token>
memory feedback oa_<token> too_mechanistic
```

The corresponding agent tool call is structured, for example:

```yaml
tool: memory_os_review_reply
arguments:
  action: feedback
  action_token: oa_<token>
  rating: too_mechanistic
```

Hermes is the interactive agent. If you reply with natural phrasing such as
`approve A1`, Hermes may resolve `A1` from the current visible digest and call
the Memory-OS review tool with the matching stable `oa_` token. If the target
is not unambiguous, Hermes should ask you to clarify instead of guessing.

Memory-OS itself does not execute display anchors. `A1/R1/F1` are UI labels
only; the plugin/state-machine layer applies only stable `oa_` action tokens.
A proposal approval only marks the proposal as approved for human-controlled
follow-up; it does not execute work.

Shell/CLI paths are operator/debug fallbacks only. They are not the owner-facing
approval workflow.
