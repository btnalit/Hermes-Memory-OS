# P1 Gap Closure Plan

Date: 2026-05-23

## Goal

Close the real implementation gaps found during the post-RH-26 project audit
before adding new cognition features.

The audit found no P0 boundary break, but it did find that several documented
runtime-hardening promises are not implemented yet. This document is the
execution contract for closing those gaps. It is intentionally stricter than a
future-work list: each P1 item below must have a command path, tests, and a
validation signal before it can be marked done.

## Current Finding

`python -m pytest -q` currently passes for the implemented code, but passing
tests do not prove that every documented commitment exists. The missing pieces
are mostly operator surfaces and install failure isolation:

- RH-01 promised a module CLI, but `hermes memory_os modules ...` does not
  exist.
- DR design promised DeepReflection owner preview/history commands, but only
  Python methods exist.
- RH-02 and RH-06 promised a commandized host validation and controlled module
  scheduling path, but production-like validation still depends on monitor
  scripts and manual Python probes.
- The safe installer can still express invalid intent combinations, such as
  enabling the shell when shell installation was explicitly skipped.
- PS-06 shell failure isolation is tracked, but not yet tested.

## Boundaries

These closure slices must not weaken the already validated safety boundaries:

- no send
- no execute
- no identity write
- no relationship write
- no crystallized approval
- no Hindsight export
- no private raw body printing
- no production or Sannai mutation
- no Hermes core patching

10.20.3.200 validation is allowed only after local tests pass and only when the
user explicitly asks for deployment or remote verification.

## P1-A Module CLI

### Problem

`08-runtime-hardening-plan.md` defines:

```text
hermes memory_os modules status
hermes memory_os modules doctor
hermes memory_os modules run-once --module inner_drive
hermes memory_os modules validate-no-send
```

The actual provider CLI does not register a `modules` subcommand.

### Implementation Shape

Add a module CLI under `plugins/memory/memory_os/cli.py` without changing the
existing provider-level command names.

Required commands:

```text
hermes memory_os modules status
hermes memory_os modules doctor
hermes memory_os modules run-once --module <module> --dry-run
hermes memory_os modules validate-no-send
```

Allowed module names for the first implementation:

```text
cron_mirror
session_mirror
state_source_mirror
shadow_journal
deep_reflection
governance_feedback
digest_consolidation
```

Modules that are not safely commandized yet must appear in status as
`available=false` with a reason, not disappear from the report.

### Files

- Modify: `plugins/memory/memory_os/cli.py`
- Add if needed: `plugins/memory/memory_os/module_registry.py`
- Test: `tests/plugins/memory/test_memory_os_cli_modules.py`

### Acceptance

- `modules status` prints a bounded JSON report with:
  - module id
  - source package
  - commandized availability
  - enabled/config state when safely available
  - last known dry-run or validation signal when available
- `modules doctor` returns exit code `0` when only optional or uncommandized
  modules are missing, and non-zero only for real errors.
- `modules run-once` is dry-run by default and rejects apply unless the module
  already has an explicit safe apply path.
- `modules validate-no-send` reports the no-send/no-execute/no-crystallized
  invariants without printing private bodies.
- Existing commands such as `hermes memory_os status`, `doctor`, `heartbeat`,
  `context-router`, and mirror commands keep their current behavior.

### Local Verification

```bash
python -m pytest tests/plugins/memory/test_memory_os_cli_modules.py -q
python -m pytest -q
git diff --check
```

## P1-B DeepReflection Owner Preview CLI

### Problem

`17-deep-reflection-runtime-design.md` requires owner spot-check commands:

```text
hermes memory_os modules deep_reflection preview-current
hermes memory_os modules deep_reflection history --days 7
```

The runtime has a `preview_injection()` method, but no CLI route.

### Implementation Shape

Implement DeepReflection commands under the `modules deep_reflection` namespace:

```text
hermes memory_os modules deep_reflection preview-current
hermes memory_os modules deep_reflection history --days <N>
```

The commands must report only bounded card metadata and bounded card text that
already passed DeepReflection safety filters. They must not print source raw
bodies, private transcripts, source previews, or full event summaries.

### Files

- Modify: `plugins/memory/memory_os/cli.py`
- Modify only if the public method is insufficient:
  `plugins/modules/cognition/deep_reflection.py`
- Test: `tests/system_modularization/test_deep_reflection_cli.py`

### Acceptance

- `preview-current` returns the current active injection/carryover card if one
  exists, otherwise a clean `no_active_card` status.
- `history --days N` returns bounded artifacts for the requested window.
- Missing DeepReflection runtime/config returns a warning status, not a Python
  traceback.
- Output includes safety boundary fields:
  - `actual_send=false`
  - `actual_execute=false`
  - `actual_identity_write=false`
  - `actual_crystallized_approval=false`

### Local Verification

```bash
python -m pytest tests/system_modularization/test_deep_reflection_cli.py -q
python -m pytest -q
git diff --check
```

## P1-C Host Validation Command And Controlled Runner

### Problem

RH-02 and RH-06 require one-command validation and controlled scheduling. The
current heartbeat path processes canonical events and index catch-up, but it
does not commandize the full host validation chain or expose a safe module
runner for digest/governance/reflection jobs.

### Implementation Shape

Add a provider CLI command that can be run locally or on 10.20.3.200:

```text
hermes memory_os validate --profile default --no-send --write-report
```

The first version should be a validation runner, not a background scheduler.
It should call safe report/dry-run surfaces and produce one bounded JSON report
under:

```text
$HERMES_HOME/memory-os/system-modules/validation/
```

Required validation sections:

- provider status and doctor summary
- module status and doctor summary
- no-send integrated chain summary
- DeepReflection status summary when enabled
- context router config and bounded probe summary when enabled
- hard-boundary booleans

Controlled module runner:

```text
hermes memory_os modules run-once --module <module> --dry-run
```

This is the P1 scope. Recurring scheduling changes remain out of scope until
the dry-run runner is stable.

### Files

- Modify: `plugins/memory/memory_os/cli.py`
- Add if needed: `plugins/memory/memory_os/validation.py`
- Add if needed: `plugins/memory/memory_os/module_registry.py`
- Test: `tests/plugins/memory/test_memory_os_validation_cli.py`
- Test: `tests/system_modularization/test_module_run_once_cli.py`

### Acceptance

- `validate --no-send --write-report` writes a report and returns non-zero only
  when a real boundary or doctor error occurs.
- The report includes the four original no-send invariants:
  - no actual send
  - Ops-Gate no execute
  - Self-Evolution no execute
  - proposal approval does not become crystallized approval
- The report also includes the later hard boundaries:
  - no identity write
  - no relationship write
  - no Hindsight export
- `run-once --module <module> --dry-run` does not mutate canonical memory unless
  the target module's existing dry-run implementation already writes explicit
  audit attempts by design.
- `run-once --module <module> --apply` is rejected for modules without a
  reviewed apply path.

### Local Verification

```bash
python -m pytest tests/plugins/memory/test_memory_os_validation_cli.py -q
python -m pytest tests/system_modularization/test_module_run_once_cli.py -q
python -m pytest -q
git diff --check
```

## P1-D Installer Fail-Closed And PS-06 Fault Isolation

### Problem

The safe shell installer has two dependency issues:

- `--no-install-shell` can still lead to shell enablement intent, which may
  write `plugins.enabled: ["memory-os-agent-os"]` when the shell was explicitly
  skipped.
- When selected actions require the `hermes` command but `hermes` is missing
  from `PATH`, the shell wrapper warns but can still continue into a partial
  file-copy install.

PS-06 also requires a test that proves shell enablement failure does not corrupt
the already-working provider, and provider enablement failure does not enable
the shell.

### Implementation Shape

Update `scripts/install_memory_os.sh` so invalid combinations fail before the
Python installer is invoked:

- if `INSTALL_SHELL=0`, force `ENABLE_SHELL=0` unless an existing shell plugin
  directory is present and the user explicitly opts into enabling that existing
  shell
- if `ENABLE_PROVIDER=1`, `ENABLE_SHELL=1`, or verification is required,
  `hermes` must be present before mutation starts
- dry-run may report missing `hermes`, but a real install that needs `hermes`
  must fail closed before copying files

Update `scripts/install_memory_os_plugin.py` tests to cover:

- shell enablement failure after provider enablement keeps the provider config
  unchanged
- provider enablement failure prevents shell enablement
- `--no-install-shell --enable-shell` is rejected or normalized to no shell
  enablement before mutation

### Files

- Modify: `scripts/install_memory_os.sh`
- Modify if needed: `scripts/install_memory_os_plugin.py`
- Test: `tests/scripts/test_memory_os_plugin_install.py`
- Test if needed: `tests/scripts/test_install_memory_os_shell_wrapper.py`

### Acceptance

- No install mode writes `plugins.enabled: ["memory-os-agent-os"]` unless the
  shell plugin is installed or already present and explicitly enabled.
- Missing `hermes` fails closed before file copies for any non-dry-run action
  that requires Hermes config writes or verification.
- Step 2 shell failure leaves Step 1 provider state intact.
- Step 1 provider failure prevents Step 2 shell activation.
- The existing blank-host smoke remains passing.

### Local Verification

```bash
bash -n scripts/install_memory_os.sh
bash -n scripts/install_memory_os_test_host.sh
python -m pytest tests/scripts/test_memory_os_plugin_install.py -q
python scripts/memory_os_blank_host_smoke.py
python -m pytest -q
git diff --check
```

## Remote Validation Gate

Only after all local P1 slices pass and the user asks for host validation:

```bash
ssh hermes-media
```

Run on 10.20.3.200:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --test-host
HERMES_HOME=/root/.hermes hermes memory_os modules status
HERMES_HOME=/root/.hermes hermes memory_os modules doctor
HERMES_HOME=/root/.hermes hermes memory_os validate --no-send --write-report
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
```

Expected:

- provider remains `memory_os`
- shell remains enabled as `memory-os-agent-os`
- `memory_os` is not added to `plugins.enabled` as a general plugin
- doctor is `ok` except expected warnings such as `hindsight_adapter_disabled`
- hard-boundary booleans remain false
- no private bodies are printed
- gateway restart is not part of the validation unless the user explicitly asks

## Work Order

1. Implement P1-D first. Installer fail-closed behavior protects every later
   validation step and open-source user path.
2. Implement P1-A module CLI status/doctor next. This creates the operator
   surface needed by validation.
3. Implement P1-B DeepReflection preview/history under the module CLI.
4. Implement P1-C validation command and dry-run module runner.
5. Run the full local verification set.
6. Stop for staged-content review before commit.
7. Deploy to 10.20.3.200 only after local review and explicit user approval.

## Local Implementation Status

Updated: 2026-05-23

Local implementation is complete for the P1 closure set:

- P1-A module CLI:
  - `hermes memory_os modules status`
  - `hermes memory_os modules doctor`
  - `hermes memory_os modules run-once --module <module>`
  - `hermes memory_os modules validate-no-send`
- P1-B DeepReflection owner preview CLI:
  - `hermes memory_os modules deep_reflection preview-current`
  - `hermes memory_os modules deep_reflection history --days <N>`
- P1-C host validation command and controlled dry-run runner:
  - `hermes memory_os validate --no-send --write-report`
  - dry-run module runner for first safe commandized modules
- P1-D installer fail-closed and PS-06 fault isolation:
  - missing shell cannot be enabled when shell installation is skipped
  - existing shell can be enabled without reinstalling it
  - shell enablement failure does not corrupt provider enablement
  - provider enablement failure prevents shell activation
  - shell wrapper checks for `hermes` before non-dry-run actions that require
    Hermes config writes or post-install verification

Local verification:

```bash
python -m pytest tests/scripts/test_memory_os_plugin_install.py tests/plugins/memory/test_memory_os_cli_modules.py -q
python -m pytest -q
bash -n scripts/install_memory_os.sh
bash -n scripts/install_memory_os_test_host.sh
python scripts/memory_os_blank_host_smoke.py
git diff --check
```

Remote validation on `10.20.3.200` was run after explicit owner approval and
is recorded below.

## Remote Implementation Validation Status

Updated: 2026-05-23

Scope:

- target host: `10.20.3.200` via `ssh hermes-media`
- target `HERMES_HOME`: `/root/.hermes`
- install path: current workspace snapshot deployed through
  `scripts/install_memory_os.sh --yes --test-host`
- no gateway restart was requested or performed as part of this gate

Remote finding fixed during the gate:

- The first remote validation attempt showed that
  `hermes memory_os modules deep_reflection preview-current` and
  `history --days 7` failed with `ModuleNotFoundError` in the installed Hermes
  process.
- Root cause: Hermes had already loaded the user-plugin `plugins` package from
  `$HERMES_HOME/plugins`, so inserting
  `$HERMES_HOME/memory-os/runtime/python` into `sys.path` was not enough for
  `plugins.modules` or `plugins.memory.memory_os` imports.
- Fix: `_ensure_system_module_runtime_path()` now also extends already-loaded
  `plugins.__path__` and `plugins.memory.__path__` with the installed
  Memory-OS runtime package paths.
- Regression coverage: `test_installed_cli_extends_loaded_plugins_package_path`
  verifies the loaded-package path extension.

Why this did not require a gateway restart:

- the failing surface was the operator CLI path, and each `hermes memory_os ...`
  command starts a fresh Python process that loads the newly installed plugin
  files
- the running gateway was not exercising the new module CLI path during this
  gate
- therefore the fix could be validated through fresh CLI invocations while
  leaving `hermes-gateway.service` running

Known risk:

- the installed Hermes process can have package namespaces loaded from more
  than one root: `$HERMES_HOME/plugins` and
  `$HERMES_HOME/memory-os/runtime/python`
- extending loaded namespace package paths fixes the current import contract,
  but future runtime/provider changes must keep the provider package and
  portable module runtime API-compatible
- this is now covered for the observed namespace case, but it remains a
  packaging compatibility area to watch during installer-level validation

Remote validation result:

```text
hermes memory_os status:
  exit_code=0
  index_health.state=healthy
  prefetch_mode=indexed
  counts:
    audit_entries=1573
    events=93
    working_items=86
    crystallized_candidates=86
    crystallized_records=0

hermes memory_os doctor:
  exit_code=0
  status=ok
  findings=[hindsight_adapter_disabled]

hermes memory_os modules status:
  exit_code=0
  module_count=16
  commandized=[
    cron_mirror,
    session_mirror,
    state_source_mirror,
    shadow_journal,
    deep_reflection,
    governance_feedback
  ]

hermes memory_os modules doctor:
  exit_code=0
  status=warning
  warning_count=4
  warning_findings:
    mailbox/mailbox_root_missing:
      mailbox root is not configured on the test host
    wandering_mind/household_digest_missing:
      household digest artifact is not present, so Wandering Mind may return
      [SILENT]
    proposal_queue/pending_candidates_present:
      2 proposal candidates are pending review
    self_evolution/missing_required_runtime_dependency:
      ops_gate, proposal_queue, and evidence_scoring are not exposed through
      the generic run-once path for this validation gate

hermes memory_os modules run-once --module cron_mirror:
  exit_code=0
  dry_run=true
  new_event_count=0

hermes memory_os modules deep_reflection preview-current:
  exit_code=0
  schema_version=hermes.deep_reflection_preview.v0
  status=ok
  selected_injection_count=2
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false

hermes memory_os modules deep_reflection history --days 7:
  exit_code=0
  schema_version=hermes.deep_reflection_history.v0
  record_count=7
  actual_send=false
  actual_execute=false
  actual_identity_write=false
  actual_crystallized_approval=false

hermes memory_os validate --no-send --write-report:
  exit_code=0
  status=warning
  report_written=true
  warning_source:
    modules_doctor emitted warning-class findings listed above; hard-boundary
    checks stayed false and no doctor error caused a non-zero exit
  hard boundaries:
    actual_send=false
    actual_execute=false
    actual_identity_write=false
    actual_relationship_write=false
    actual_crystallized_approval=false
    hindsight_exported=false

hermes memory-os-agent-os status:
  exit_code=0

hermes memory-os-agent-os doctor:
  exit_code=0
  status=ok

hermes memory_os conversation-regression status-tool-contract:
  exit_code=0
  validation.status=ok
  finding_count=0

systemd user units:
  hermes-gateway.service: active/running, MainPID=451894
  hermes-memory-os-heartbeat.timer: loaded, active, waiting, enabled

hermes plugins list:
  memory-os-agent-os: enabled
  memory_os: not enabled as a general plugin
```

Remote gate judgment:

- P1-A through P1-D are deployable on the test host.
- The shell plugin can import the installed Memory-OS provider/runtime through
  both direct shell aliases and provider-owned CLI paths.
- The new module CLI and validation command preserve the hard no-send,
  no-execute, no-identity-write, no-relationship-write, no-crystallized-approval,
  and no-Hindsight-export boundaries.
- Remaining warnings are expected warning-class states, not hard-boundary
  failures.

## Self Review

### Spec Coverage

| Requirement | Covered By |
| --- | --- |
| RH-01 module CLI | P1-A |
| DR preview-current/history CLI | P1-B |
| RH-02 host validation command | P1-C |
| RH-06 controlled module runner | P1-C |
| installer dependency fail-closed | P1-D |
| PS-06 shell failure isolation | P1-D |
| no-send/no-execute/no-crystallized boundaries | P1-C and Remote Validation Gate |
| no private body printing | P1-A, P1-B, P1-C, Remote Validation Gate |

### Placeholder Scan

This plan does not rely on unresolved placeholder markers for P1 acceptance.
Items outside P1 are explicitly out of scope rather than hidden as placeholders.

### Risk Review

- The module CLI can accidentally become a broad orchestration surface. The
  acceptance criteria keep apply rejected unless a module already has a reviewed
  apply path.
- The validation command can accidentally print private details. The report
  must use bounded metadata and summaries only.
- The installer can still leave copied files if a low-level filesystem copy
  succeeds and a later non-Hermes action fails. P1-D specifically targets config
  fail-closed behavior and shell/provider activation isolation; physical copied
  files are acceptable only when they are not enabled and do not corrupt the
  active runtime.
- Recurring scheduling remains intentionally out of scope. The P1 target is
  commandized dry-run/run-once first, not a new automatic scheduler.

### Current Judgment

This document turned the audit findings into a bounded implementation plan and
now records local completion of P1-A through P1-D. The remaining gate is host
validation on `10.20.3.200`, which is intentionally not run automatically from
this local implementation pass.
