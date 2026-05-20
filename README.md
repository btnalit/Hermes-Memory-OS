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
- read-only Sannai shadow bundle export/import
- CLI diagnostic helpers, meta-audit, benchmark, and dry-run-first cleanup

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

## License

No license has been selected yet.
