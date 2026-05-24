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

Production-safe install:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --production-safe
```

The installer does not restart `hermes-gateway.service`.

## 3. Verify

```bash
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes memory_os status
HERMES_HOME=/root/.hermes hermes memory_os doctor
HERMES_HOME=/root/.hermes hermes plugins list
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
```

Expected state:

```text
memory.provider = memory_os
memory-os-agent-os = enabled general plugin
memory_os = not enabled as a general plugin
doctor.status = ok
```

## 4. What Gets Installed

- `memory_os` provider under `$HERMES_HOME/plugins/memory_os/`
- optional `memory-os-agent-os` shell plugin under
  `$HERMES_HOME/plugins/memory-os-agent-os/`
- optional portable module runtime under
  `$HERMES_HOME/memory-os/runtime/python/`
- optional heartbeat and cognitive-loop systemd user units under
  `$HERMES_HOME/memory-os/systemd/`

Backups belong under `$HERMES_HOME/plugin-backups/`, not under
`$HERMES_HOME/plugins/`.

## 5. Safety Defaults

Memory-OS does not automatically send messages, execute external actions, write
identity, approve crystallized memory, export to Hindsight, apply cleanup, or
apply shadow journals.

Test-host mode enables observation loops. It does not enable real sends,
executes, identity writes, or crystallized approvals.
