# Memory-OS V3 Inner-Life Runbook

## Scope and invariant

V3 is implemented entirely inside Memory-OS. It does **not** patch Hermes Agent core. The hard boundary is:

```text
V2 canonical memory → bounded BodyStatePacket → isolated no-tool inference
→ private TTL journal → deterministic synthesis/outlet gates
→ SpeakGate or Proposal Intake only
```

V3 private thoughts are not canonical memory, are not retrieval documents, and are not owner-visible merely because they exist.

## Rollout state

| Stage | Function | Default |
|---|---|---|
| R0 | Disable legacy CognitiveLoopRunner jobs | disabled/fail-closed |
| R1 | Collect approved non-task seed evidence | cron active, observational |
| R2 | Body packet, private journal, query trace, fate CAS, TTL sweep | infrastructure active; no model required |
| R3 | Private wandering inference | `wandering_enabled=false` |
| R4 | Synthesis admission | `synthesis_admission_enabled=false` |
| R5 | Would-share/actual expression | `outlet_shadow_enabled=false`, `expression_enabled=false` |

The installed R3 lane is safe while disabled: it exits before model input. There is no catch-up behavior.

### Where the V3 lanes are scheduled

The V3 lanes no longer own individual Hermes cron jobs. They run as member
lanes of grouped tick jobs, each still behind its own ExecutionGate permit:

| Lane | Tick job | Effective cadence |
|---|---|---|
| `v3_seed_evidence` (R1) | `memory-os-tick-daily` | once per UTC calendar day |
| `v3_wandering` (R3) | `memory-os-tick-evidence` | every 6h |
| `v3_journal_sweep` (R2 TTL sweep) | `memory-os-tick-daily` | daily |

`v3_seed_evidence` uses `due_policy="calendar"` rather than an elapsed
interval, because it emits one record per `natural_date` and reports
`consecutive_valid_day_count` — elapsed gating could drift it across a UTC day
boundary and skip or double-count a day.

To hold a single V3 lane without disabling the whole tick, add its registry key
to `$HERMES_HOME/memory-os/system/cron_lane_disabled.json`. Disabling the tick
job itself would also stop its unrelated co-tenant lanes.

## No-session Hermes adapter

`v3_ephemeral_adapter.py` launches `v3_ephemeral_worker.py` in the Hermes Agent virtualenv with an isolated `PYTHONPATH`. The worker uses the existing `agent.auxiliary_client.call_llm` route with:

- current provider/model configuration;
- configured credential pools and fallback policy;
- `tools=[]`;
- no `AIAgent` construction;
- no session DB, memory retrieval, hooks, trajectory, gateway capture, cron-output capture, or delivery path.

The adapter requires an explicitly injected `v3_inner_life.host_agent_root`; it never guesses a host path or reads one from ambient environment state. It rejects responses when the actual model cannot be mapped uniquely to the approved primary/fallback route snapshot.

## Private stores

| Store | Purpose | Public payload rule |
|---|---|---|
| `memory-os/system/wandering_journal.jsonl` | thought records and query traces | never emit thought body or provenance refs |
| `memory-os/system/v3_body_packet_manifests.jsonl` | provenance-only snapshot manifests | no packet body |
| `memory-os/system/v3_wandering_runs.jsonl` | aggregate attempt status | no thought body or source refs |
| `memory-os/system/v3_journal_sweep_status.json` | sweep health | exactly `cycle_status` |

Installer writes `memory-os/private_backup_exclusions.json`. Backup implementations must consume this contract and exclude the journal and body manifests from normal backup payloads.

## Journal semantics

- Ingestion is whole-batch fail-closed.
- Terminal fate is ingestor-owned; model-supplied terminal state cannot win.
- Journal-to-journal provenance is resolved to canonical V2 roots.
- Maximum lineage hops is mandatory and enforced.
- Queries append a body-free query trace before returning results. If trace persistence fails, no result is returned.
- Expired pending thoughts are physically removed. Shared/proposed records and query traces are not deleted by pending TTL sweep.
- Manifest rows are reverse-retained only while journal records depend on them.

## R4 synthesis

Synthesis consumes private journal entries, not raw session logs. Deterministic admission precedes ingestion:

1. minimum input count;
2. minimum canonical-root diversity;
3. blocked/sensitive-source rejection;
4. reusable-insight assertion;
5. semantic-distance threshold via an injected evaluator;
6. lineage-hop cap.

The model may abstain with `{"entries":[]}`. Empty output removes the per-run body manifest.

## R5 outlet

`v3_outlet.py` supports two modes:

- `shadow`: computes aggregate would-share/would-propose results and does not mutate fate or deliver;
- `active`: atomically claims the requested outlet, then routes:
  - `share` through `ExpressionDraftModule → SpeakGateModule` only;
  - `propose` through `CrystallizedMemoryService.append_candidate_queue` only.

Terminal fate is receipt-driven. A delivery/candidate receipt mismatch cannot produce `shared` or `proposed`. If the external side effect succeeds but terminal journaling fails, the entry remains `claimed` for reconciliation rather than being falsely closed.

## Activation prerequisites

Do not enable R3–R5 until all are true:

- R1 seed-evidence gate reports `activation_ready=true` for the required observation window;
- `host_agent_root` points to a tested Hermes Agent checkout with its venv;
- live no-session probe succeeds and session/debug/trajectory/outbox counts are unchanged;
- journal TTL, entry-size, lineage-hop, attempt-window, quiet-hour, and char-budget knobs are all positive and explicit;
- R4 has an injected semantic-distance evaluator;
- R5 shadow metrics meet configured caps/cooldown/diversity/duplicate thresholds;
- owner explicitly approves each activation step.

Recommended order:

1. enable R3 only;
2. confirm R3 stays inside the boundary — no canonical V2 write, no owner-visible surface, no session/trajectory/outbox drift — via `wandering_journal.jsonl` query traces and `v3_journal_sweep_status.json` `cycle_status`; confirm TTL sweep removes only expired pending thoughts and never touches shared/proposed records or query traces;
3. enable R4 synthesis admission;
4. enable R5 shadow only;
5. enable actual expression last.

Rollback is one-way and reversible: set the relevant feature flag to `false`; do not delete canonical V2 memory. R0 legacy-loop disable remains independent.
