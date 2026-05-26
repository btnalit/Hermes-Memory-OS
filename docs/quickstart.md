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

Interactive install:

```bash
bash scripts/install_memory_os.sh
```

No-send test-host install:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host
```

The test-host preset installs the owner review helper and enables the daily
owner review digest through Hermes cron by default. Use
`--no-enable-owner-review-cron` if you want the helper installed but no recurring
delivery job. Outside `--test-host`, the installer resolves the default owner
review delivery target to Hermes cron `origin` rather than hardcoding Telegram.
Hermes owns the scheduled delivery, platform transport, and final owner-facing
wording in agent mode; Memory-OS only renders the bounded review brief and
processes owner actions.

Production-safe install:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --production-safe
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
- optional owner review digest helper/gate under `$HERMES_HOME/scripts/`; the
  test-host preset enables the daily Hermes cron job unless explicitly disabled

Backups belong under `$HERMES_HOME/plugin-backups/`, not under
`$HERMES_HOME/plugins/`.

## 5. Safety Defaults

Memory-OS does not automatically send messages, execute external actions, write
identity, approve crystallized memory, export to Hindsight, apply cleanup, or
apply shadow journals.

Test-host mode enables observation loops. It does not enable real sends,
executes, identity writes, or crystallized approvals.

## 6. Owner Review Commands

Owner review digests use short display anchors such as `A1`, `R1`, and `F1` to
make the list readable. Those anchors are not durable approval identities.

The safest reply is to use the stable token printed on the digest item:

```text
memory approve oa_<token>
memory reject oa_<token>
memory allow oa_<token>
memory feedback oa_<token> too_mechanistic
```

Hermes is the interactive agent. If you reply with natural phrasing such as
`approve A1`, Hermes may resolve `A1` from the current visible digest and call
the Memory-OS review tool with the matching stable `oa_` token. If the target
is not unambiguous, Hermes should ask you to clarify instead of guessing.

Memory-OS itself does not execute display anchors. `A1/R1/F1` are UI labels
only; the plugin/state-machine layer applies only stable `oa_` action tokens.
A proposal approval only marks the proposal as approved for human-controlled
follow-up; it does not execute work.
