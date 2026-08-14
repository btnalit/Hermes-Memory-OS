# `scripts/` — what is in here and what you would ever run

95 files live here. Almost none of them are meant for a human to run
directly, and none of them are needed to *try* Memory-OS — for that see the
blank-machine lane in the top-level README.

This index exists because a flat directory of 95 operational scripts is
unreadable to a newcomer and to an AI agent asked to "deploy this". The
categories below are the map; the rule of thumb is that **you only ever
invoke Group 1**.

---

## Group 1 — Things a human or an agent actually invokes

| Script | Purpose |
| --- | --- |
| `memory_os_blank_host_smoke.py` | Self-contained blank-machine validation. Builds a throwaway profile, drives the real provider end to end, touches nothing existing. **Start here.** |
| `install_memory_os.sh` | The one-command installer for a host with an existing Hermes profile (`--operational` / `--production-safe` / `--test-host`). |
| `deploy_memory_os.py` | Phased deploy wrapper (`plan` → `preflight` → `dry-run` → `apply` → `postcheck`), local or over SSH. Runs the compatibility gate before writing. |
| `memory_os_monitor.py` | Neutral monitor entrypoint. |
| `memory_os_3_200_monitor.py` | The full production monitor (heavyweight; target ≤180s). |
| `memory_os_loop_health_view.py` | Read-only projection: which production loops are active / idle / need attention. |
| `install_memory_os_monitor_dashboard_service.py` + `serve_memory_os_monitor_dashboard.py` | Optional read-only dashboard. |

The CLI itself (`memory-os …` after `pip install`, or
`hermes memory-os-agent-os …` on a host) covers status, doctor, review,
recall evaluation and the other 30+ subcommands — prefer it over scripts.

## Group 2 — Cron lane wrappers and gates (~20 files)

`memory_os_cron_*.py` — one thin wrapper per registered cron lane or tick
group, plus the ExecutionGate runner. **Created and invoked by Hermes cron**,
never by hand. Adding a lane means editing
`plugins/memory/memory_os/cron_registry.py` and this set together (see
CLAUDE.md "Cron Profile" for the six places a lane touches).

## Group 3 — Lane helpers and owner-facing renderers (~35 files)

The bodies behind Group 2: `*_lane.py`, `*_helper.py`, `*_digest.py`,
`*_prompt.py`, `*_refresh.py`. They run under an ExecutionGate permit with
`HERMES_HOME` supplied by the runner. Running one by hand is legitimate for
debugging but is not part of any normal workflow.

## Group 4 — Contract gates (CI)

`memory_os_import_cycle_check.py`, `memory_os_write_surface_check.py`,
`memory_os_static_hygiene_check.py`, `memory_os_public_checkout_probe.py`,
`memory_os_closure_matrix_check.py`, `memory_os_version_consistency_check.py`,
`memory_os_upgrade_compat_check.py` — run by CI and by `deploy_memory_os.py`.
Contributors run them locally before pushing (see the top-level README's
Development section).

## Group 5 — Probes and diagnostics

`*_probe*.py`, `memory_os_graph_shadow_analyzer.py`,
`memory_os_overlay_data_probe.py`, `memory_os_recall_probe.py` — read-only
investigation tools. Safe to run; they answer "what does production actually
look like right now".

## Group 6 — Repair tools (rare, deliberate)

| Script | When |
| --- | --- |
| `memory_os_clearance_snapshot_rebuild.py` | The derived clearance snapshot went stale; rebuilds it from the append-only ledger and **fails loudly** if it is still stale afterwards. |
| `memory_os_queue_consolidated_candidate.py` | Operator helper for closing the owner-approved crystallization loop by hand. |
| `memory_os_smoke_record_cleanup.py` | Removes smoke-test records that leaked into a real store. |
| `cleanup_expired_working.py` | Prunes expired working-memory items (also a cron lane). |
| `memory_os_upgrade_evidence_compare.py` | Compares pre/post Hermes-upgrade evidence. |
| `memory_os_export_shadow.py` | Read-only shadow bundle export (also exposed as the `export-shadow` CLI subcommand). |

## Group 7 — Completed one-time migrations (kept for old data, never rerun)

These fixed a specific historical data condition. A fresh install never
needs them; they are retained because a host carrying pre-fix data still
might. Each states its own applied-context in its docstring.

| Script | Fixed |
| --- | --- |
| `memory_os_v24_final_verify.py` | One-shot verification of the v2.4 corrective release. |
| `memory_os_graph_edges_compaction.py` | 769 redundant graph edge rows (W2/E2). |
| `memory_os_graph_edge_weight_renormalization.py` | Legacy saturated edge weights, all born at 1.0 (P3, 2026-08-07). |
| `memory_os_candidate_backfill_409.py` | The ~409 inner-drive candidate backlog. |
| `memory_os_retire_legacy_right_brain.py`, `memory_os_community_retirement.py` | Retirement of superseded subsystems; shipped by the installer, so **do not delete**. |

## Group 8 — Test/CI infrastructure

`memory_os_mount_isolated_pytest.py` (mount-isolated full suite),
`memory_os_pytest_policy.py`, `install_memory_os_test_host.sh`.
