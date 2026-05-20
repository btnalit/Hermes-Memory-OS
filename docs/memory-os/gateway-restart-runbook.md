# Memory-OS Gateway Restart Runbook

This runbook defines restart scope and rollback rules for Memory-OS validation.
It is documentation only for v0. No restart wrapper, hook, deployment script, or
automation is introduced by Slice 14.

## Hard Rules

- Do not restart any gateway unless the target host, profile, service name, and
  approval state are explicit.
- Never restart both main Hermes and Sannai gateways unless the owner explicitly
  approves that exact combined action.
- Production `10.20.2.88` is blocked by default. Its commands are precheck
  templates only until explicit owner approval is given in the current run.
- `10.20.3.200` is the blank validation host. It may be used for test restarts
  after Memory-OS is installed there, but it must stay separate from production.
- Rollback restores provider configuration first, then restarts only the gateway
  for the profile that was changed.
- Keep `$HERMES_HOME/memory-os/` as evidence on rollback. Do not delete it as a
  cleanup shortcut.

## Scope Matrix

| Environment | Host | Purpose | Restart Status |
| --- | --- | --- | --- |
| Local dev | this checkout | tests and provider lifecycle only | no gateway restart |
| Blank validation | `10.20.3.200` | Memory-OS install, smoke, shadow replay | allowed only after explicit validation step |
| Production main | `10.20.2.88` / YC-NAS | current main Hermes | blocked by default |
| Production Sannai | `10.20.2.88` / YC-NAS | current Sannai profile | blocked by default |

## Local Development

Local development does not restart Hermes gateways. Use local process tests:

```powershell
python -m pytest -q
python -m compileall -q agent plugins scripts
```

Provider lifecycle validation should use a temporary `HERMES_HOME` and call
`initialize()`, `sync_turn()`, `prefetch()`, and `shutdown()` through tests.

## `10.20.3.200` Blank Validation Host

This host is the first restart-capable target, but only after Memory-OS is
installed there. Keep it separate from `10.20.2.88`.

### Precheck

```bash
hostname
pwd
git -C /path/to/Hermes-Memory-OS status --short
python -m pytest -q
```

If a systemd user service exists on the blank host, capture before state:

```bash
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID --no-pager
systemctl --user show hermes-gateway-sannai.service -p ActiveState -p MainPID --no-pager
```

If services do not exist yet, record that absence and do not invent service
names. Start with local CLI/provider tests instead.

### Restart Shape

Only restart the one service tied to the profile being validated.

```bash
# main-shape validation only, if the service exists
systemctl --user restart hermes-gateway.service

# Sannai-shadow validation only, if the service exists and this profile is in scope
systemctl --user restart hermes-gateway-sannai.service
```

Capture after state immediately:

```bash
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID --no-pager
systemctl --user show hermes-gateway-sannai.service -p ActiveState -p MainPID --no-pager
```

The validation report must say which service moved, which PID changed, and
whether the other gateway stayed untouched.

## Production `10.20.2.88` Blocked Section

This section is a checklist template. Do not execute it without explicit owner
approval in the current run.

### Production Prechecks

Confirm host and profile separation:

```bash
hostname
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID --no-pager
systemctl --user show hermes-gateway-sannai.service -p ActiveState -p MainPID --no-pager
```

Expected production homes:

```text
main Hermes: HERMES_HOME=/vol1/.hermes
Sannai:      HERMES_HOME=/root/.hermes/profiles/sannai
```

Capture profile configuration without printing secrets or memory bodies:

```bash
# main provider value only
python3 - <<'PY'
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path('/vol1/.hermes/config.yaml').read_text()) or {}
print({'main_memory_provider': (cfg.get('memory') or {}).get('provider')})
PY

# Sannai provider value only
python3 - <<'PY'
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path('/root/.hermes/profiles/sannai/config.yaml').read_text()) or {}
print({'sannai_memory_provider': (cfg.get('memory') or {}).get('provider')})
PY
```

### Production Restart Approval Gate

Before any production restart, the operator must record:

```text
approved_by:
approved_at:
target_host:
target_profile: main|sannai
target_service:
reason:
rollback_provider_value:
before_pid:
```

No production action may continue if `target_service` is ambiguous.

### Production Restart Shape

Use only the target profile's gateway:

```bash
# main only
systemctl --user restart hermes-gateway.service

# Sannai only
systemctl --user restart hermes-gateway-sannai.service
```

Never run both commands in one production change unless the owner explicitly
approved restarting both gateways.

### Production After Checks

```bash
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID --no-pager
systemctl --user show hermes-gateway-sannai.service -p ActiveState -p MainPID --no-pager
```

The after report must include:

- target service active state
- before and after PID for target service
- before and after PID for non-target service
- confirmation that the non-target gateway did not restart
- current provider value for the target profile
- whether `$HERMES_HOME/memory-os/` was written

## Rollback

Rollback is profile-scoped.

Provider values:

```text
main Hermes rollback: memory.provider=hindsight
Sannai rollback: built-in only; memory.provider empty or absent unless changed later
```

Rollback sequence:

1. Stop new Memory-OS validation writes for the target profile.
2. Restore the target profile's provider value.
3. Keep `$HERMES_HOME/memory-os/` as evidence.
4. Do not replay Memory-OS events into Hindsight.
5. Restart only the target profile's gateway.
6. Capture before/after PID and provider value.
7. Write a rollback report with failure point, written event count, adapter
   export count, and any data-loss window.

## Post-v0 Automation Boundary

Automated restart wrappers, restart hooks, deployment orchestration, and
combined gateway restart tools are post-v0 work. Any future automation must
still require explicit owner approval plus before/after PID evidence.
