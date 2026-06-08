# TASK ANCHOR — candidate_aggregation lane

**冻结区 · 不可协商 · 越界必须发 ANCHOR_CHANGE_REQUEST 升级**
**Last verified: 2026-06-08 · Backfill executed · All anchors hold**

## Invariants

| ID | Rule | Why |
|---|---|---|
| A1 | `crystallized` = owner approval. Never auto-crystallize, never auto-approve. Any → crystallized write only via owner_actions. | INV-2 |
| A2 | `actual_crystallized_approval` / `actual_send` / `actual_execute` / `actual_policy_write` / `route_score_write` / `identity_write` / `relationship_write` / `hindsight_write` — all must remain `false`. | Permanent trust boundary |
| A3 | Append-only, invalidate-not-delete. Demote/discard/fleeting = append status record. Never delete any candidate. | INV-3 |
| A4 | This lane changes queue state only: `candidate ↔ owner_eligible ↔ demoted ↔ fleeting`. Never touches crystallized layer. | Scope boundary |
| A5 | Heuristics (frequency, keywords, working-memory patterns) drive **presentation only** (→ owner_eligible). Never drive crystallization. "Appears N times" is never a crystallization reason — only a "worth owner looking at" reason. | INV-2 enforcement |
| A6 | All automated writes must go through `StructuralWriteGate.append_governed_jsonl` with a valid `ExecutionGate` envelope (resolved via `resolve_execution_gate_permit`). No envelope = no write. | Governance |
| A7 | No cron bypass outside conversation loop. Must connect into existing `cognitive_loop` / `ExecutionGate` / `monitor` framework. | 56-lane discipline |

## Enforcement

1. **Pre-merge**: code review must verify all A1-A7. No PR merged without explicit anchor compliance check.
2. **Runtime**: monitor must surface `boundary_true_count` for the lane. Any non-zero value triggers investigation.
3. **Post-hoc**: `write_surface_check` must classify every new write surface; `unclassified_count` must stay at 0.

## Execution evidence (2026-06-08)

Backfill `memory_os_candidate_backfill_409.py --apply --confirm-backfill`:

| Invariant | Evidence |
|-----------|----------|
| A1 ✅ | 0 crystallized writes; all 431 triage actions go to `candidate_triage.jsonl` |
| A2 ✅ | `actual_crystallized_approval = false` verified post-backfill |
| A3 ✅ | `candidate_triage.jsonl` append-only (431 lines); `candidates.jsonl` untouched (431 lines) |
| A4 ✅ | Only `action=promote` (→owner_eligible) and `action=fleeting` (→fleeting) |
| A5 ✅ | Promote target is `owner_eligible`, never crystallized; `'希望'` keyword drives presentation |
| A6 ✅ | Lane: append_candidate_triage() → append_governed_jsonl() with ExecutionGate envelope (scope_hash, envelope_id); Backfill/operator: append_governed_jsonl() with allow_owner_action_without_envelope=True (classified exemption) |
| A7 ✅ | Lane registered via `cron_registry.json`; no `--no-gate` bypass |

**Backfill numbers**: 430 fleeting tagged, 1 promoted to owner_eligible, 0 no_action, 0 crystallized.

Detailed evidence in `01-design-v1.md` §⚡ Execution evidence.

## Escalation

If any implementation step would violate A1–A7:

**STOP. Send ANCHOR_CHANGE_REQUEST with:**
- Which anchor(s) would be violated
- What the implementation needs that the anchor blocks
- Why existing alternatives are insufficient
- Owner decides to relax or reject

**Do not silently cross.** Silence is consent to the anchor, not to the violation.
