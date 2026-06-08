# 00 — Requirements: candidate_aggregation lane (56 路线)

Date: 2026-06-08
Status: requirements (stage 1/6)
Author: Hermes agent (with TASK ANCHOR from owner)

## 0. TASK ANCHOR（冻结 · 不可协商）

See `TASK_ANCHOR.md` in this directory. In summary:

- **INV-2**: crystallized = owner only. No auto-crystallize, no auto-approve.
- **7 actual_* boundaries**: all must remain `false`.
- **append-only**: invalidate-not-delete.
- **Heuristics drive presentation only** (→owner_eligible), never crystallization.
- **All writes via StructuralWriteGate + ExecutionGate envelope**.
- **No cron bypass**: must route through existing cognitive_loop / ExecutionGate / monitor.

## 1. Background

### 1.1 Current state (diagnosis)

| Metric | Value |
|---|---|
| Total candidates | 412 |
| bridge_state=inner_drive_candidate | 409 (99.3%) |
| bridge_state=owner_eligible | 2 |
| bridge_state=crystallized | 1 |
| auto_approve | 0 (architecture prevents it) |
| Auto triage/promotion | 0 (nonexistent) |
| Retention/compaction | 0 (append-only, no cap) |

### 1.2 Root cause (four facets of one gap)

1. **Write-end too loose**: `inner_drive` classifier writes candidates even for pure chat (no decision content). 409 items are mostly 5/20-21 self-test chatter.
2. **No retention**: `crystallized.py` has `append_candidate_queue` and `read_candidate_queue` but no `compact`, `prune`, or `age-out`. Queue grows unbounded.
3. **No auto triage**: `scripts/memory_os_queue_consolidated_candidate.py` correctly promotes to `owner_eligible` (`actual_crystallized_approval=False`), but it's an operator-only `argv main` tool — no cron, no monitor, no scheduler integration.
4. **Backlog visible but not actionable**: `candidate_queue_pressure` (55-D) shows `pending_candidate_count` as a number, but no pipeline renders those items into a bachable owner review batch.

### 1.3 Existing correct primitives (build on, don't bypass)

- `scripts/memory_os_queue_consolidated_candidate.py` — promote to `owner_eligible`, never crystallize. Reuse its promote path.
- `ExecutionGate` — envelope-based permit/completion for all bounded operations.
- `StructuralWriteGate.append_governed_jsonl` — governed write surface.
- `owner_actions.py` — owner-triggered crystallization via `OwnerActionProcessor`.

## 2. Scope

### IN scope (3.1–3.6 of TASK)

| Item | What | Boundary |
|---|---|---|
| 3.1 | Lane body: cluster+promote, demote/age-out, tag-fleeting | queue-state writes only |
| 3.2 | inner_drive write gate: no-decision → fleeting/no-persist | inner_drive candidate creation |
| 3.3 | Candidate queue retention/compaction | archive-not-delete, bounded |
| 3.4 | One-time backfill script for 409 backlog | operator-scoped, terminates in owner batch |
| 3.5 | cognitive_loop wiring + write_surface_check + monitor | envelope lifecycle |
| 3.6 | Shadow mode → limited_auto graduation | evidence-based, Wilson-scored |

### OUT of scope (explicitly excluded)

- Any `actual_crystallized_approval=true` path (never automated)
- Candidate deletion (append-only)
- Separate cron bypassing cognitive_loop
- Changing existing `owner_actions.py` crystallization path
- LLM on hot inference path (deterministic clustering only)

## 3. Evidence criteria

### 3.1 Primary guard (one metric to watch)

```
actual_crystallized_approval = false  (MUST be invariant)
```

Every operation in this lane must verify this post-condition. If any operation produces `true`, the implementation is wrong.

### 3.2 Secondary evidence

| Criterion | Evidence |
|---|---|
| 409 backlog triaged | File evidence of batch operations; pending_candidate_count drops |
| Retention active | Compaction archive exists; candidate queue size bounded |
| Write surface clean | write_surface_check: unclassified=0 |
| Lane ExecutionGate-bound | envelope records show permit+completion for every tick |
| monitor visible | candidate_aggregation status in monitor output |
| Tests green | Full pytest suite + test for new lane |
| Owner burden bounded | No unexpected crystallized records; owner digests show actionable batches |

## 4. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Clustering heuristic promotes noise | Shadow mode first; compare batch vs owner actual decisions |
| inner_drive write gate catches real patterns | Use "fleeting" tag rather than discard; reversible |
| Retention age-out loses signal | Archive-not-delete; retention policy configurable |
| cognitive_loop wiring breaks existing lanes | Separate lane_id; no shared state mutation |

## 5. Dependencies

- `crystallized.py`: `append_candidate_queue`, `read_candidate_queue`, candidate data model
- `scripts/memory_os_queue_consolidated_candidate.py`: promote-to-owner_eligible path
- `memory_os_execution_gate_runner.py`: ExecutionGate envelope lifecycle
- `cron/jobs.py` or `cognitive_loop`: scheduler tick for lane execution
- `write_surface_check`: write classification
- Monitor 55-D: `candidate_queue_pressure` projection

## 6. Previous related work

- 55-D `candidate_queue_pressure` monitor projection — adds `pending_candidate_count` to monitor output
- `memory_os_queue_consolidated_candidate.py` — promote helper (operator-only)
- `owner_actions.py` — owner-triggered crystallization path
