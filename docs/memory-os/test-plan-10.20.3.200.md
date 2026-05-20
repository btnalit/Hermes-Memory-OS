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
python3 scripts/memory_os_blank_host_smoke.py \
  --base-dir /tmp/hermes-memory-os-validation/smoke
```

If the blank host has Python but no `pip`, install the minimal Debian test
runner instead and run from the repo root:

```bash
apt-get update
apt-get install -y python3-pytest
python3 -m pytest -q
python3 scripts/memory_os_blank_host_smoke.py \
  --base-dir /tmp/hermes-memory-os-validation/smoke
```

Evidence:

```text
host:
commit:
python_version:
pytest_result:
blank_host_smoke_result:
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
python3 scripts/memory_os_blank_host_smoke.py \
  --base-dir /tmp/hermes-memory-os-validation/smoke
```

Success criteria:

- provider initializes under supplied `HERMES_HOME`
- event stream writes summary-only records
- SQLite can be deleted and rebuilt from filesystem truth
- prefetch respects budget and redaction
- working memory evolves without writing crystallized memory
- blank-host smoke completes without network, gateway, Telegram, mailbox, or
  production dependencies

## Phase B.5: Hermes Plugin Install And Discovery

This phase validates the plugin installation/discovery path on `10.20.3.200`.
It is separate from Sannai shadow data compatibility.

Use a fresh temporary Hermes home:

```bash
cd /tmp/hermes-memory-os-validation/repo
rm -rf /tmp/memory-os-blank-home
python3 scripts/install_memory_os_plugin.py --hermes-home /tmp/memory-os-blank-home
HERMES_HOME=/tmp/memory-os-blank-home hermes memory
```

Expected:

- `memory_os` appears under installed memory plugins.
- Status is `available`.
- No gateway restart occurs.
- No production host is contacted.

To enable for the real `10.20.3.200` main profile pilot:

```bash
HERMES_HOME=/root/.hermes python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-runtime \
  --enable-runtime \
  --runtime-interval 5min
HERMES_HOME=/root/.hermes hermes config set memory.provider memory_os
HERMES_HOME=/root/.hermes hermes memory
systemctl --user restart hermes-gateway.service
```

Rollback preserves evidence:

```bash
cp /root/.hermes/config.yaml.memory-os-pilot-*.bak /root/.hermes/config.yaml
systemctl --user restart hermes-gateway.service
```

Runtime heartbeat validation:

```bash
HERMES_HOME=/root/.hermes hermes memory_os heartbeat --max-events 100
HERMES_HOME=/root/.hermes hermes memory_os status
systemctl --user status hermes-memory-os-heartbeat.timer --no-pager
```

Expected:

- `working_items` increases after new events are processed.
- `crystallized_candidates` increases after new events are processed.
- `crystallized_records` remains `0` until owner approval.
- `hermes-memory-os-heartbeat.timer` is enabled and active on `10.20.3.200`.

## Phase B.6: Runtime SQLite/FTS Indexer

This phase validates Slice 20 after implementation. It follows the design in
`docs/memory-os/slice-20-runtime-indexer-design.md`.

Local test subset before remote deployment:

```bash
python3 -m pytest \
  tests/plugins/memory/test_memory_os_store.py \
  tests/plugins/memory/test_memory_os_runtime.py \
  tests/plugins/memory/test_memory_os_prefetch.py \
  tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py \
  -q
```

Runtime validation on the `10.20.3.200` main profile:

```bash
HERMES_HOME=/root/.hermes hermes memory_os heartbeat --max-events 100
HERMES_HOME=/root/.hermes hermes memory_os status
HERMES_HOME=/root/.hermes hermes memory_os doctor
```

Expected:

- `index_counts.events` catches up after heartbeat.
- A second heartbeat does not duplicate indexed rows.
- Doctor distinguishes `index_missing`, `index_stale`, and mismatch findings.
- Prefetch uses indexed mode when the index is healthy.
- If the DB is missing or rebuilding, prefetch reports degraded filesystem mode
  instead of silently pretending to meet the indexed SLO.
- FTS tokenizer status reports `trigram` when available, otherwise
  `fts_tokenizer_degraded`.
- No production host, production gateway, production Hindsight bank, or identity
  source file is modified.

Optional Slice 20 benchmark:

```bash
HERMES_HOME=/root/.hermes hermes memory_os benchmark --records 100000 --large-opt-in
```

Record indexed prefetch, degraded prefetch, and full rebuild timing separately
in the validation report.

## Phase B.7: Diagnostic Grounding

This phase validates Slice 21 after implementation. It targets the observed
live issue where a diagnostic answer can mix current Memory-OS facts with stale
Hindsight recall.

Local test subset before remote deployment:

```bash
python3 -m pytest tests/plugins/memory/test_memory_os_diagnostic_grounding.py -q
```

Runtime validation on the `10.20.3.200` main profile:

```bash
HERMES_HOME=/root/.hermes hermes memory_os status
HERMES_HOME=/root/.hermes hermes memory_os doctor
```

Then ask the main Telegram gateway diagnostic prompts such as:

```text
当前记忆架构是什么？
你现在用的是什么 memory provider？
Hindsight 现在是不是 Memory-OS 的 canonical store？
```

Expected:

- Answer names `memory_os` as the active provider.
- Answer identifies `$HERMES_HOME/memory-os` or `/root/.hermes/memory-os` as
  the canonical Memory-OS store.
- Answer says Hindsight is optional adapter only when disabled, not canonical.
- Answer does not cite `/root/.hermes/hindsight/config.json` as the Memory-OS
  canonical path.
- Answer does not describe Hindsight HTTP API as the active Memory-OS storage
  path when `uses_hindsight_http_api=false`.
- Diagnostic grounding remains user-facing only; background heartbeat,
  inner-drive, crystallized candidate generation, migrator replay, and
  benchmarks are unaffected.

Sannai policy check, if the profile exists on the validation host:

```text
ordinary self-memory prompt:
  should not trigger diagnostic grounding

explicit system-diagnostic prompt:
  may trigger diagnostic grounding only if profile policy allows it
```

Do not connect Sannai shadow data, production Hindsight, or production
gateways for this phase.

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
python3 scripts/memory_os_blank_host_smoke.py \
  --base-dir /tmp/hermes-memory-os-validation/smoke
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
- synthetic shadow flow in `memory_os_blank_host_smoke.py` reaches diff report
  without production data

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
blank-host smoke JSON output
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
