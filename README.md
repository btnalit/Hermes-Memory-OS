# Hermes Memory-OS

Hermes Memory-OS is a file-first memory architecture for long-running agents.
It separates raw event capture, working memory, crystallized memory, identity
sources, relationships, audit logs, diagnostics, and migration tooling.

This repository is intentionally extracted as a clean project. It does not
vendor the full Hermes agent manager source tree.

## Current Scope

The current prototype covers:

- Memory provider discovery scaffold
- v0 schema and deterministic fixtures
- profile-local root resolution
- canonical filesystem store with SQLite as rebuildable index
- prefetch context assembly
- working memory state evolution
- crystallized memory approval boundary
- runtime heartbeat from events to working memory and crystallized candidates
- diagnostic grounding for current memory-provider questions
- read-only Sannai shadow bundle export/import
- CLI diagnostic helpers, meta-audit, benchmark, and dry-run-first cleanup
- Provider self-diagnostic tool: `memory_os_status`

The v0 implementation is closed. See `docs/memory-os/v0-closeout.md` for the
final validation boundary and the observation-first next phase.

Production Hermes and Sannai migration remains a separate controlled step. The
code here is designed so validation can happen on an empty machine or shadow
bundle before touching a live server.

## Repository Layout

```text
plugins/memory/memory_os/   # Memory-OS provider and core services
agent/                      # Minimal compatibility interface used by provider tests
scripts/                    # Operator scripts
tests/                      # Focused Memory-OS tests
docs/memory-os/             # Architecture, integration, and implementation plans
```

## Run Tests

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

## Safety Defaults

- SQLite is an index, not the source of truth.
- Shadow export is read-only against legacy Hermes/Sannai state.
- Crystallized memory requires explicit owner approval.
- Cleanup is dry-run-first and never targets identity sources or crystallized records.
- Hindsight is treated as an optional adapter, not canonical storage.

## Install As A Hermes Memory Plugin

Install into a target Hermes profile home:

```bash
python3 scripts/install_memory_os_plugin.py --hermes-home "$HERMES_HOME" --install-runtime
```

Then enable it through Hermes' native config path:

```bash
HERMES_HOME="$HERMES_HOME" hermes config set memory.provider memory_os
HERMES_HOME="$HERMES_HOME" hermes memory
HERMES_HOME="$HERMES_HOME" hermes memory_os heartbeat
```

The expected discovery contract is `$HERMES_HOME/plugins/memory_os/` with
`plugin.yaml`, `__init__.py`, and `register_memory_provider()`. No system prompt
patch is required for Hermes to discover the provider.

When active, the provider exposes a read-only `memory_os_status` tool so the
agent can inspect the real Memory-OS backend instead of inferring from old
memory text. Diagnostic prefetch also suppresses historical recall for current
provider questions so stale Hindsight-era memories do not override runtime
facts.

For a full test deployment, enable the heartbeat timer on a validation host:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home "$HERMES_HOME" \
  --install-runtime \
  --enable-runtime \
  --runtime-interval 5min
```

The heartbeat advances new events into `working/*.json` and
`crystallized/candidates.jsonl`. It does not write approved crystallized records;
owner approval remains a separate boundary.

## License

MIT License. See [LICENSE](LICENSE).
