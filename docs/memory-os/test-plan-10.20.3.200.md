# Memory-OS Test Plan For `10.20.3.200`

`10.20.3.200` is the blank validation host for Memory-OS. This plan validates
the system before any production action on `10.20.2.88`.

## Goals

- Prove Memory-OS can run as an isolated project.
- Validate provider lifecycle, schemas, store, index, prefetch, working memory,
  crystallized approval, shadow import, diagnostics, benchmark, cleanup, and
  Hindsight adapter smoke.
- Validate restart scope only on the blank host after service names are known.
- Produce evidence that can be reviewed before any production pilot.

## Non-Goals

- Do not modify `10.20.2.88`.
- Do not restart production gateways.
- Do not switch production provider values.
- Do not export raw sessions, private prompts, API keys, or secrets.
- Do not enable Hindsight auto-retain.

## Phase A: Repository And Runtime

```bash
hostname
git clone https://github.com/btnalit/Hermes-Memory-OS.git
cd Hermes-Memory-OS
python3 --version
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

Evidence:

```text
host:
commit:
python_version:
pytest_result:
```

## Phase B: Empty `memoryos-test` Profile

Use a disposable home on `10.20.3.200`:

```bash
export HERMES_HOME=/tmp/hermes-memory-os-validation/main
rm -rf "$HERMES_HOME"
mkdir -p "$HERMES_HOME"
python3 -m pytest tests/plugins/memory/test_memory_os_lifecycle.py -q
python3 -m pytest tests/plugins/memory/test_memory_os_store.py -q
python3 -m pytest tests/plugins/memory/test_memory_os_prefetch.py -q
python3 -m pytest tests/plugins/memory/test_memory_os_working.py -q
```

Success criteria:

- provider initializes under supplied `HERMES_HOME`
- event stream writes summary-only records
- SQLite can be deleted and rebuilt from filesystem truth
- prefetch respects budget and redaction
- working memory evolves without writing crystallized memory

## Phase C: Owner Approval And Adapter Smoke

```bash
python3 -m pytest tests/plugins/memory/test_memory_os_crystallized.py -q
python3 -m pytest tests/plugins/memory/test_memory_os_hindsight_adapter.py -q
```

Success criteria:

- `owner_eligible` does not become crystallized approval
- crystallized writes require `approve_for_crystallized`
- Hindsight adapter is disabled by default
- adapter exports only public owner-approved crystallized records
- adapter uses a mock client and does not call the network

## Phase D: Sannai Shadow Bundle

The production export step is read-only and must be run from a separately
approved operator action. Private Sannai bodies may be included if owner
approved, but secrets remain excluded.

Expected bundle import location on `10.20.3.200`:

```text
$HERMES_HOME/memory-os/imports/sannai-shadow-YYYYMMDD-HHMMSS/
```

Validation commands after a bundle is available:

```bash
python3 -m pytest tests/plugins/memory/test_memory_os_migrator.py -q
python3 scripts/memory_os_export_shadow.py \
  --profile sannai \
  --hermes-home /path/to/sannai/profile-copy \
  --state-root /path/to/sannai/state-copy \
  --out /tmp/sannai-shadow-bundle \
  --dry-run
```

Success criteria:

- dry-run reports would-copy paths without writing output
- source hashes are unchanged before and after dry-run
- CW-019 `owner_eligible` maps to S5 visibility only, not crystallized approval
- shadow import never writes identity or production roots

## Phase E: Diagnostics, Benchmark, Cleanup

```bash
python3 -m pytest tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py -q
```

Optional large benchmark:

```bash
python3 - <<'PY'
from pathlib import Path
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.benchmark import BenchmarkConfig, run_benchmark
roots = MemoryOSRoots.from_hermes_home(Path('/tmp/hermes-memory-os-validation/bench'), profile='memoryos-test')
store = MemoryOSStore(roots)
store.initialize()
print(run_benchmark(store, BenchmarkConfig(record_count=100000, seed=1, profile='memoryos-test', large_opt_in=True)))
PY
```

Success criteria:

- status and doctor omit private bodies by default
- meta-audit can be attached to validation evidence
- cleanup is dry-run-first
- cleanup never targets identity sources or crystallized records
- 100k benchmark is opt-in and recorded separately

## Phase F: Blank-Host Restart Smoke

Run only if a Hermes gateway service exists on `10.20.3.200`.

Precheck:

```bash
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID --no-pager
systemctl --user show hermes-gateway-sannai.service -p ActiveState -p MainPID --no-pager
```

Restart only the service tied to the profile under test:

```bash
systemctl --user restart hermes-gateway.service
```

After check:

```bash
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID --no-pager
systemctl --user show hermes-gateway-sannai.service -p ActiveState -p MainPID --no-pager
```

Success criteria:

- target gateway active state is healthy
- target PID changes or restart is otherwise explained by systemd
- non-target gateway PID does not change
- no command is run against `10.20.2.88`

## Evidence Package

Attach these to the validation report:

```text
commit
pytest output
compileall output
doctor/meta-audit output
benchmark report
shadow import report, if run
before/after PID output, if restart smoke is run
```

## Promotion Gate

Production remains blocked until the owner explicitly approves a named target:

```text
target_host: 10.20.2.88
target_profile: main|sannai
target_service:
provider_change:
rollback_provider_value:
approved_by:
approved_at:
```

Without that record, no production restart or provider switch is allowed.
