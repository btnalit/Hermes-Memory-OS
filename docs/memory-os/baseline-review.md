# Memory-OS Baseline Review

Date: 2026-05-20

This document closes the local Slice 0-16 baseline for the standalone
`Hermes-Memory-OS` repository.

## Scope

- Repository: `D:\Hermes agent manager\Hermes-Memory-OS\`
- Production host: `10.20.2.88 / YC-NAS`
- Blank validation host: `10.20.3.200`
- Current baseline: local implementation and tests only.

## Completed Capabilities

| Area | Status |
| --- | --- |
| Provider discovery | `memory-os` provider can be loaded without network or production dependencies. |
| Schema | v0 event, working, crystallized, identity manifest, and cross-profile view schemas exist. |
| Fixtures | Deterministic synthetic event, working, crystallized, and Sannai-like multi-root fixtures exist. |
| Roots | Profile-local `$HERMES_HOME/memory-os/` roots and external Sannai state roots are explicit. |
| Store | JSONL/Markdown filesystem store is the canonical source; SQLite is rebuildable index only. |
| Lifecycle | `sync_turn()` writes summary-only events through a bounded worker queue. |
| Prefetch | Bounded context reads identity summary, working summary, relationships, crystallized records, and recent event summaries. |
| Working memory | Lingering, emotional, curiosity, and attention documents support add/decay/status/trace behavior. |
| Crystallized memory | Long-term markdown records require explicit `approve_for_crystallized`. |
| Transition compatibility | Sannai legacy source scan, shadow bundle export, and shadow import are implemented. |
| CLI/doctor | Status, doctor, inspect, trace, diff, approval report, benchmark, cleanup, and migrate commands exist. |
| Benchmark | Small default benchmark and opt-in large synthetic corpus path exist. |
| Cleanup | Retention planning is dry-run first and preserves identity/crystallized records. |
| Hindsight adapter | Disabled by default; exports only public owner-approved crystallized records through an injected mock/client. |
| Gateway restart strategy | Runbook only; no restart automation was added. |
| Migrator process | Staged scan/export/import/replay/diff process is auditable and dry-run first. |
| E2E | Temp-profile vertical test covers sync turn, event, working, candidate, approval, crystallized record, and optional mocked adapter export. |

## Explicitly Not Done

- No production deployment.
- No provider switch on `10.20.2.88`.
- No production Sannai data export in this local baseline.
- No gateway restart automation.
- No real Hindsight network integration.
- No autonomous inner-drive scheduler.
- No final Sannai personality suitability validation.
- No durable queue/spool recovery after unclean process death.
- No migration apply step for production.

## Production-No-Change Rules

- Do not write to `10.20.2.88` without a separate explicit owner approval.
- Do not restart `hermes-gateway.service` or `hermes-gateway-sannai.service` during local baseline work.
- Do not switch main Hermes or Sannai to `memory-os` in production.
- Do not enable Sannai S5 from CW-019 `owner_eligible`.
- Do not write active `lingering_thoughts.json` or long-term memory from CW-019 bridge data.
- Do not export raw events, working memory, CW-019 pending candidates, private bodies, prompts, tokens, cookies, or keys to Hindsight.
- Do not delete `$HERMES_HOME/memory-os/` evidence roots during rollback; preserve them for audit.

## Slice 13-16 Diff Boundary

| Slice | Files |
| --- | --- |
| Slice 13: Hindsight Adapter Smoke | `plugins/memory/memory_os/adapters/**`, `tests/plugins/memory/test_memory_os_hindsight_adapter.py` |
| Slice 14: Gateway Restart Strategy | `docs/memory-os/gateway-restart-runbook.md`, `docs/memory-os/test-plan-10.20.3.200.md` |
| Slice 15: Migrator Process | `plugins/memory/memory_os/migrator.py`, `plugins/memory/memory_os/cli.py`, `docs/memory-os/migration-notes.md`, `tests/plugins/memory/test_memory_os_migrator.py` |
| Slice 16: End-to-End Integration Test | `plugins/memory/memory_os/inner_drive.py`, `tests/plugins/memory/test_memory_os_e2e.py` |
| Baseline closeout | `docs/memory-os/baseline-review.md`, path corrections in existing docs |

## Next Gate

The next useful gate is a 10.20.3.200 blank-host validation package:

1. Clone `https://github.com/btnalit/Hermes-Memory-OS.git`.
2. Run the local validation sequence.
3. Create an isolated temp `HERMES_HOME`.
4. Run migrate scan/export/import/replay/diff against fixture or explicitly exported shadow data.
5. Record evidence in `docs/memory-os/test-plan-10.20.3.200.md`.

Production pilot review comes after blank-host evidence, not before.
