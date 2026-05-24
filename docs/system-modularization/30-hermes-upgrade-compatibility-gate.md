# 30 - Hermes Upgrade Compatibility Gate

Status: operational gate
Date: 2026-05-24
Scope: read-only compatibility validation before and after Hermes upgrades

## Goal

Hermes upgrades can change the external surfaces Memory-OS depends on:

- memory provider selection
- plugin loading
- shell CLI command registration
- Python import/bootstrap paths
- gateway service environment
- config behavior

Memory-OS should not rely on memory or manual spot checks after an upgrade.
This gate provides a repeatable read-only check.

## Current Entry Point Reality

On the 10.20.3.200 test host, `memory_os` is active as a Hermes memory provider,
not as a general Hermes plugin command.

Use:

```bash
hermes memory
hermes memory-os-agent-os status
hermes memory-os-agent-os doctor
hermes memory-os-agent-os modules status
```

Do not use `hermes memory_os ...` as the live natural operator path unless a
future Hermes version explicitly exposes it again.

## Read-Only Script

Local host:

```bash
python scripts/memory_os_upgrade_compat_check.py --output summary
```

Remote 10.20.3.200 test host:

```powershell
python scripts/memory_os_upgrade_compat_check.py --host hermes-media --output summary
```

JSON report:

```powershell
python scripts/memory_os_upgrade_compat_check.py --host hermes-media --output json
```

Optional explicit home:

```powershell
python scripts/memory_os_upgrade_compat_check.py `
  --host hermes-media `
  --hermes-home /root/.hermes `
  --output summary
```

The script must not:

- install or enable plugins
- restart gateway
- run heartbeat or cognitive loop
- apply cleanup
- apply shadow journals
- export to Hindsight
- read private transcripts

## Checks

The script currently probes:

```text
hermes --version
hermes memory
hermes memory-os-agent-os status
hermes memory-os-agent-os doctor
hermes memory-os-agent-os modules status
hermes memory-os-agent-os modules doctor
hermes memory-os-agent-os modules run-once --module cron_mirror --dry-run
hermes memory-os-agent-os modules validate-no-send
hermes memory-os-agent-os low-clue-recall dry-run --query "继续昨天那个"
hermes memory-os-agent-os memory-sources stats --hours 24
```

## PASS

- `hermes memory` reports active provider `memory_os`.
- shell status returns `memory-os.status.v0`.
- shell doctor has no error findings.
- modules status returns `memory-os.modules_status.v0`.
- modules doctor has no error findings.
- modules run-once is dry-run.
- modules validate-no-send reports hard boundaries false.
- low-clue recall returns bounded JSON and hard boundaries false.
- MemorySources stats reports `boundary_true_count=0`.
- MemorySources stats has no forbidden-field findings.

## WARN

- `hermes --version` is unavailable.
- optional status-tool contract entrypoints are unavailable because the active
  Hermes command registry does not expose provider subcommands.
- known `hindsight_adapter_disabled` exists without additional doctor errors.

## FAIL

- provider is not `memory_os`.
- Memory-OS runtime import fails.
- shell alias command is missing.
- modules alias command is missing.
- any hard boundary is true.
- MemorySources reports forbidden fields.
- doctor reports an error finding.
- low-clue recall exits non-zero or returns invalid JSON.

## Upgrade Procedure

Before Hermes upgrade:

1. Run the compatibility script and save the JSON report.
2. Run the normal read-only monitor and save the summary.
3. Record the Hermes version and active provider state.

After Hermes upgrade:

1. Run the compatibility script again.
2. Run the normal read-only monitor again.
3. Compare pre/post results.
4. Do not enable new modules until required checks pass.

If the compatibility script fails but canonical Memory-OS files remain intact,
do not try to fix the break by auto-enabling advanced modules. Classify the
failure by 29号 contract:

- provider/plugin/import break: P1
- boundary true or private leak: P0
- optional report-only judge unavailable: P2
- wording/format-only drift: P3

## Relation To Monitor

The upgrade script is not a replacement for
`scripts/memory_os_3_200_monitor.py`.

- Upgrade check: fast read-only probe of external Hermes interfaces.
- Monitor: ongoing operational health, counters, deltas, attribution, ingress
  matrix, and runtime trends.

Both should pass after a Hermes upgrade before the system is considered stable.
