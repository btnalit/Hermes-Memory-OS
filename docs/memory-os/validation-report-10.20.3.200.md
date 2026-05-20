# Memory-OS Validation Report For `10.20.3.200`

Date: 2026-05-20

## Target

- Host alias: `hermes-media`
- Host IP: `10.20.3.200`
- Hostname: `debian`
- Repository path: `/tmp/hermes-memory-os-validation/repo`
- Commit: `f270226 Add blank-host Memory-OS smoke validation`
- Python: `Python 3.13.12`
- Git: `git version 2.53.0`

## Runtime Notes

The blank host had Python but no `pip`:

```text
/usr/bin/python3: No module named pip
```

Installed minimal Debian test dependencies:

```bash
apt-get update
apt-get install -y python3-pytest
```

Installed packages: `python3-pytest`, `python3-iniconfig`,
`python3-packaging`, `python3-pluggy`, `python3-pygments`.

## Validation Results

Full suite:

```text
python3 -m pytest -q
72 passed in 1.02s
```

Compile check:

```text
python3 -m compileall -q agent plugins scripts
passed
```

Grouped checks:

```text
test_memory_os_lifecycle.py
test_memory_os_store.py
test_memory_os_prefetch.py
test_memory_os_working.py
24 passed in 0.23s

test_memory_os_crystallized.py
test_memory_os_hindsight_adapter.py
10 passed in 0.07s

test_memory_os_migrator.py
test_memory_os_audit_benchmark_cleanup.py
21 passed in 0.23s

test_memory_os_blank_host_smoke.py
1 passed in 0.14s
```

Blank-host smoke:

```json
{
  "schema_version": "memory-os.blank_host_smoke.v0",
  "production_touched": false,
  "network_used": false,
  "gateway_restart_attempted": false,
  "e2e": {
    "event_count": 1,
    "index_event_count": 1,
    "working_item_count": 1,
    "crystallized_record_count": 1,
    "adapter_disabled_exported_count": 0,
    "adapter_enabled_exported_count": 1,
    "adapter_payload_count": 1
  },
  "migrator": {
    "scan_source_count": 9,
    "export_dry_run_wrote": false,
    "import_source_count": 9,
    "replay_events_replayed": 9,
    "replay_messages_sent": 0,
    "diff_ready_for_owner_review": true,
    "approval_state_counts": {
      "approved_for_s5_visibility": 1,
      "deferred": 2
    }
  }
}
```

## Safety Evidence

- No command was run against `10.20.2.88`.
- No production provider value was changed.
- No production gateway was restarted.
- No Telegram, mailbox, Hindsight network client, or production Sannai data was used.
- Validation used `/tmp/hermes-memory-os-validation/**` only.

## Plugin Install And Discovery Evidence

Slice 17 validated the Hermes-native plugin path on `10.20.3.200`.

Fresh temporary home:

```text
python3 scripts/install_memory_os_plugin.py --hermes-home /tmp/memory-os-blank-home
HERMES_HOME=/tmp/memory-os-blank-home hermes memory
```

Result:

```text
memory_os  (local)
```

Enabled temporary home:

```text
python3 scripts/install_memory_os_plugin.py --hermes-home /tmp/memory-os-cli-home --enable
HERMES_HOME=/tmp/memory-os-cli-home hermes memory_os status
HERMES_HOME=/tmp/memory-os-cli-home hermes memory_os doctor
```

Result:

```text
status root=/tmp/memory-os-cli-home/memory-os
doctor status=ok
```

Main `10.20.3.200` profile plugin refresh:

```text
HERMES_HOME=/root/.hermes python3 scripts/install_memory_os_plugin.py --hermes-home /root/.hermes
HERMES_HOME=/root/.hermes hermes memory_os status
systemctl --user show hermes-gateway.service -p MainPID
```

Result:

```text
root=/root/.hermes/memory-os
events=3
MainPID=423925
```

The main plugin refresh copied provider files only. It did not restart the
gateway; the PID remained unchanged.

## Provider Self-Diagnostic Tool Evidence

After adding `memory_os_status`, the plugin was refreshed on the main
`10.20.3.200` profile and the gateway was restarted to load the new provider
schema:

```text
before MainPID=423925
after  MainPID=425553
```

Controlled CLI prompt:

```text
请调用 memory_os_status 工具检查当前记忆后端，然后只回答三行：
provider=..., storage_model=..., uses_hindsight_http_api=...
```

Result:

```text
provider=memory_os
storage_model=local_filesystem_jsonl_markdown
uses_hindsight_http_api=false
```

Post-turn Memory-OS status:

```text
events=5
audit_entries=5
latest_event=evt_20260520T094221296201Z_ea9138187f
```

This proves two separate facts:

- Hermes can now expose Memory-OS self-diagnostics through the provider tool surface.
- The diagnostic turn itself was persisted by Memory-OS.

## Runtime Heartbeat Evidence

Memory-OS was refreshed on the `10.20.3.200` main profile with runtime
artifacts:

```text
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-runtime \
  --enable-runtime \
  --runtime-interval 5min
```

Installed artifacts:

```text
/root/.hermes/memory-os/bin/memory_os_heartbeat.sh
/root/.hermes/memory-os/systemd/hermes-memory-os-heartbeat.service
/root/.hermes/memory-os/systemd/hermes-memory-os-heartbeat.timer
```

Manual heartbeat on existing events:

```text
processed_event_count=8
working_item_count=8
candidate_count=8
crystallized_record_count=0
```

User systemd timer:

```text
hermes-memory-os-heartbeat.timer: enabled, active
next trigger: 5 minute interval
```

New event full-runtime check:

```text
marker=MOS_RUNTIME_FULL_20260520_1000
before heartbeat: events=9
heartbeat processed_event_count=1
after heartbeat: working_items=9, crystallized_candidates=9
crystallized_records=0
```

This validates the complete test deployment path:

```text
conversation -> event -> heartbeat -> working memory -> crystallized candidate
```

Owner approval remains the boundary for writing `crystallized/*.md`.

## Slice 21 Diagnostic Grounding Evidence

Slice 21 was validated locally and on `10.20.3.200` after the live issue where
a provider diagnostic answer mixed current Memory-OS facts with stale
Hindsight-era recall.

Local validation:

```text
python -m pytest tests/plugins/memory/test_memory_os_diagnostic_grounding.py -q
9 passed

python -m pytest -q
107 passed

python -m compileall -q agent plugins scripts
passed

git diff --check
passed
```

Remote validation directory:

```text
/tmp/hermes-memory-os-validation/slice21-diagnostic-grounding-20260520191245
```

Remote validation:

```text
python3 -m pytest tests/plugins/memory/test_memory_os_diagnostic_grounding.py -q
9 passed

python3 -m pytest -q
107 passed

python3 -m compileall -q agent plugins scripts
passed
```

The refreshed plugin was installed to the main validation profile:

```text
target=/root/.hermes/plugins/memory_os
copied_file_count=22
runtime_artifacts_installed=true
enable_requested=false
runtime_enable_requested=false
```

Provider-level diagnostic prefetch check:

```text
HAS_CURRENT_FACTS=True
HAS_INDEXED_RECALL=False
HAS_RECENT=False
HAS_OLD_HINDSIGHT_PATH=False
HAS_PROVIDER_BULLET=True
HAS_USES_HINDSIGHT_FALSE=True
HAS_CANONICAL=True
```

This proves diagnostic grounding now happens before indexed recall runs, keeps
critical runtime facts inside tight prefetch budgets, and excludes the old
`/root/.hermes/hindsight/config.json` claim from diagnostic context.

Live Telegram confirmation on the main validation gateway:

```text
time=2026-05-20 19:20-19:21 Asia/Shanghai
prompt:
  当前记忆架构是什么？
  你现在用的是什么 memory provider？
  Hindsight 现在是不是 Memory-OS 的 canonical store？
```

Observed answer facts:

```text
active provider=memory-os
canonical store=/root/.hermes/memory-os
storage model=local filesystem, JSONL + Markdown
Hindsight role=optional adapter, not canonical
hindsight_adapter_enabled=false
uses_hindsight_http_api=false
index health=healthy
events=10
working_items=10
crystallized_candidates=10
crystallized_records=0
```

Observed stale-claim result:

```text
The answer did not claim /root/.hermes/hindsight/config.json as the
Memory-OS canonical path.
```

Gateway load step on `10.20.3.200`:

```text
before main MainPID=425553
after  main MainPID=427105
sannai ActiveState=inactive, MainPID=0 before and after
```

Post-restart status:

```text
hermes memory: provider memory_os active
doctor status: ok
only warning: hindsight_adapter_disabled
events=10
working_items=10
crystallized_candidates=10
crystallized_records=0
index_health=healthy
prefetch_mode=indexed
```

Production boundary:

```text
10.20.2.88 was not contacted.
No production gateway was restarted.
No production Hindsight bank was modified.
No identity source was modified.
```

## Result

The `10.20.3.200` blank-host baseline validation passed for local unit tests,
E2E smoke, synthetic migrator flow, compile checks, grouped diagnostics, and
Hermes-native plugin install/discovery. The main profile pilot additionally
validated provider self-diagnostics, post-turn event capture, runtime heartbeat,
working memory evolution, candidate generation, runtime indexing, and
diagnostic grounding against stale Hindsight recall.

Next gate: continue the `10.20.3.200` main provider pilot using Hermes-native
plugin status and doctor commands. Sannai shadow data remains an archived
compatibility fixture, not the main pilot path.
