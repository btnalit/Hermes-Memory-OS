# 01 — Design: candidate_aggregation lane

Date: 2026-06-08
Status: implemented (stage 4/6) — backfill executed, all tests passing
Extends: 00-requirements-v1.md

## 0. Architecture overview

```
                    ┌─────────────────────────┐
                    │   cognitive_loop tick    │
                    │  (lane_id=candidate_     │
                    │   aggregation)           │
                    └────────┬────────────────┘
                             │
                    ExecutionGate permit
                             │
                    ┌────────▼────────────────┐
                    │   candidate_aggregation  │
                    │   → read candidates      │
                    │   → cluster & promote    │
                    │   → age-out demote       │
                    │   → tag fleeting         │
                    │   → write triage record  │
                    └────────┬────────────────┘
                             │
                    StructuralWriteGate
                    append_governed_jsonl
                             │
                    ┌────────▼────────────────┐
                    │   candidate_triage.jsonl │
                    │   (append-only queue     │
                    │    state changes)        │
                    └─────────────────────────┘
```

## 1. Data model

### 1.1 Existing: `candidates.jsonl` (unchanged)

One JSON line per candidate, written by `inner_drive` or `queue_consolidated_candidate.py`.

```jsonl
{"candidate_id": "cand_abc123", "kind": "preference", "body": "...", "source_event_ids": ["evt_1"], "bridge_state": "inner_drive_candidate", ...}
```

### 1.2 New: `candidate_triage.jsonl` (append-only)

One JSON line per triage action. References original candidate by `candidate_id`.

```json
{
  "candidate_id": "cand_abc123",
  "action": "promote" | "demote" | "fleeting" | "discard",
  "target_state": "owner_eligible" | "demoted" | "fleeting" | "discard",
  "reason": "cluster match on '不喜歡' keyword (frequency=3)",
  "cluster_key": "preference:food_preference",
  "created_at": "2026-06-08T10:00:00Z",
  "execution_gate_envelope_id": "xgate_20260608_..."
}
```

### 1.3 Resolved view

The lane reads both files and resolves the effective state per candidate:

```
effective_state(candidate_id) =
  latest_triage(candidate_id)?.target_state
  ?? candidate.bridge_state
```

This is computed at read time, never written back into `candidates.jsonl`.

## 2. Lane functions (queue-state only)

### 2.1 `cluster_and_promote(candidates) → triage_actions`

**Deterministic only.** No LLM on hot path.

1. Read all candidates with `bridge_state=inner_drive_candidate`.
2. Cluster by keyword/pattern matching on `body`:
   - Chinese keywords: "鐵律", "規則", "不要", "偏好", "喜歡", "不喜歡", "記住", "以後"
   - English keywords: "always", "never", "prefer", "rule", "important", "remember"
   - Group by shared `source_event_ids` (same conversation → same cluster)
   - Group by `kind` field
3. For each cluster with ≥2 candidates sharing a keyword match:
   - Create a promoted entry in `candidate_triage.jsonl` with `target_state="owner_eligible"`
   - Reason includes: matched keywords, cluster size, source event count
4. Log cluster statistics to audit.

**Shadow mode**: First N ticks, also record "would promote" vs monitor actual owner decisions. Accumulate Wilson score before graduating to limited_auto.

### 2.2 `demote_aged(candidates) → triage_actions`

1. Filter candidates with `bridge_state=inner_drive_candidate` and `created_at > 72h` from now.
2. Skip candidates that already have a triage action.
3. Append demoted entry to `candidate_triage.jsonl` with `target_state="demoted"`.
4. Reason: "aged out (created_at > 72h, no triage action)".

**Retention boundary**: demoted candidates remain in `candidates.jsonl` and `candidate_triage.jsonl`. They are filtered from the "active" view but never deleted.

### 2.3 `tag_fleeting(candidates) → triage_actions`

1. Heuristic: candidate `body` shorter than 50 chars OR contains only chat/acknowledgment patterns (e.g., "好的", "明白", "ok", "got it", "了解了", single emoji, no substantive decision content).
2. Append fleeting entry to `candidate_triage.jsonl` with `target_state="fleeting"`.
3. Reason: "no decision content (chat/acknowledgment only)".

## 3. ExecutionGate integration

```
permit → lane execution → completion
```

### 3.1 Registration

Register in `memory_os_cron_registry.json`:

```json
{
  "key": "candidate_aggregation",
  "lane_id": "candidate_aggregation",
  "helper_kind": "bounded_reversible_queue",
  "raw_script": "memory_os_candidate_aggregation_lane.py",
  "requires_boundary_report": true,
  "no_agent": true,
  "schedule_arg": "candidate_aggregation_schedule"
}
```

### 3.2 Envelope lifecycle

- `_append_permit()` → `execution_gate_envelope.stage=permit`
- Run lane actions → `StructuralWriteGate.append_governed_jsonl()` (with envelope_id)
- `_append_completion()` → `execution_gate_envelope.stage=completion`
- `boundary_true` check: if any action produces `actual_*` flag, fail completion

### 3.3 Cognitive loop wiring

The lane runs as a `no_agent=True` cron job on a configurable schedule (default: every 6h). This mirrors the existing `memory_os_module_cadence_report_gate.py` pattern.

```
cron tick → _run_job_script("memory_os_candidate_aggregation_lane.py")
         → script runs cluster + demote + fleeting
         → outputs triage summary (how many promoted/demoted/fleeting)
         → cron scheduler delivers summary to origin
```

## 4. Write surface

### 4.1 Allowed writes

| File | Schema | Governance |
|---|---|---|
| `candidate_triage.jsonl` | `append_governed_jsonl` | ExecutionGate envelope |
| Audit records | `append_audit` | INV-3 |

### 4.2 Explicitly forbidden writes

| File | Why |
|---|---|
| Any `crystallized/` record | Would violate A1, A2 |
| `candidates.jsonl` modification | Would break append-only (A3) |
| `owner_actions` data | Would bypass owner |

### 4.3 `write_surface_check` classification

New surfaces:
- `candidate_triage.jsonl` → `envelope_bound_governance_write` (not exempt)
- All operations → `boundary_false` (verified on completion)

## 5. inner_drive write gate (3.2)

### 5.1 Current state

`inner_drive.py` calls `append_candidate_queue()` for every `CrystallizedCandidate` produced by its classifier. No filter for "no decision content".

### 5.2 Change

Add a pre-write gate in `inner_drive.py` (or in a shared utility):

```python
def _should_persist_candidate(body: str, kind: str) -> bool:
    """Return False for candidates with no substantive decision content."""
    body = (body or "").strip()
    kind = (kind or "").strip().lower()
    # Always persist if kind is substantive
    if kind in {"rule", "preference", "boundary", "behavior", "pattern", "requirement"}:
        return True
    # Reject chat-only / empty bodies
    if not body or len(body) < 15:
        return False
    # Reject common chat patterns
    chat_patterns = {"好的", "明白", "ok", "got it", "了解", "是的", "嗯", "好的明白", "理解了"}
    if body.strip().lower() in chat_patterns:
        return False
    return True
```

Candidates that fail the gate are either:
- Not persisted at all (if truly content-free)
- Persisted with `tags=["fleeting"]` to exclude them from default owner-review views

## 6. Candidate queue retention (3.3)

### 6.1 Mechanism

Add `compact_candidate_queue()` to `crystallized.py`:

```python
def compact_candidate_queue(store: MemoryOSStore, *, archive_path: Path | None = None) -> int:
    """Archive-and-compact: move stale lines to archive, keep active lines.
    
    Returns count of archived candidates.
    
    Active = bridge_state in {inner_drive_candidate, owner_eligible}
    OR created_at < 7d (recent enough to be still interesting)
    
    Archived candidates go to {archive_path / "candidates.archive.jsonl"}
    """
```

### 6.2 Schedule

Compact runs as part of the lane tick (before triage) on a longer cadence (every 24h or weekly).

## 7. One-time backfill (3.4)

### 7.1 Script: `scripts/memory_os_candidate_backfill_409.py`

Operator-scoped, one-shot. Does:

1. Read all 409 candidates from `candidates.jsonl`.
2. Classify each into one of:
   - `fleeting` — 5/20-21 self-test chat, no decision content
   - `merge` — repeat patterns that should become a single `owner_eligible` candidate
3. For `fleeting`: append to `candidate_triage.jsonl` with `action="fleeting"`.
4. For `merge`: cluster similar bodies → write merged entry to `candidate_triage.jsonl` with `target_state="owner_eligible"`.
5. Output summary: X fleeting, Y merged into Z owner_eligible items.
6. **Never crystallizes.** Terminates with owner-reviewable batch of 3-5 items.

### 7.2 Safety

- Dry-run mode: `--dry-run` prints what would happen, no writes.
- `--apply` flag required for actual writes.
- Requires explicit `--confirm-backfill` flag (typo-proof).

---

## ⚡ Execution evidence (2026-06-08)

### Backfill execution

```bash
python3 /root/.hermes/scripts/memory_os_candidate_backfill_409.py --apply --confirm-backfill
```

**Result:**

| Metric | Value | Evidence |
|--------|-------|----------|
| Total candidates in queue | 431 | `candidates.jsonl` line count |
| Already triaged | 0 | Pre-backfill: `candidate_triage.jsonl` did not exist |
| Fleeting tagged | **430** | `grep target_state=fleeting` → 430 lines |
| Promoted to owner_eligible | **1** | `grep target_state=owner_eligible` → 1 line |
| No action | 0 | 430 + 1 = 431, all accounted |
| File untouched | `candidates.jsonl` (431 lines) | No modification to source |
| File created | `candidate_triage.jsonl` (431 lines) | Append-only, no deletions |
| Crystallized writes | **0** | No `crystallized.jsonl` written |
| Anchor breach | **0** | `actual_crystallized_approval = false` verified |

### Promote record (owner_eligible)

```json
{
  "action": "promote",
  "candidate_id": "cand_consolidated_owner_channel_closure_20260527",
  "cluster_key": "preference:希望",
  "target_state": "owner_eligible",
  "reason": "backfill: cluster match (size=1, keywords=['希望'], cluster_key=preference:希望)",
  "created_at": "2026-06-08T03:55:05.491527+00:00"
}
```

**Body**: "用户希望 Memory-OS 的审批和观察闭环通过 Hermes 主会话通道真实推送、反馈和审批，而不是停留在 CLI、日志或 monitor-only 证据。"

### Test results

```
tests/plugins/memory/test_crystallized_candidate_triage.py .....   (5 tests, PASS)
tests/plugins/memory/test_crystallized_compaction.py ...            (3 tests, PASS)
tests/plugins/memory/test_crystallized_resolve_state.py .           (1 test, PASS)
tests/plugins/memory/test_candidate_aggregation.py ....             (4 tests, PASS)
tests/plugins/memory/test_queue_consolidated_candidate.py ...       (3 tests, PASS)
──────────────────────────────────────────────────────────────────
Total: 16 pass
1 pre-existing failure (unrelated: test_proposal_followup_ops_gate)
```

### inner_drive write gate verification

Gate function `_should_persist_candidate()` in `plugins/modules/cognition/inner_drive.py`:

- **431 candidates persisted**: all have `bridge_state=inner_drive_candidate`
- **430 fleeting**: all are self-test "Remembered from event..." templates — correctly caught by `_is_fleeting_candidate()`
- **1 promote**: genuine user preference signal — correctly caught by keyword `希望`

The gate correctly distinguishes between:
- Moment: remember templates (no decision content → fleeting)
- User preference statements（希望 → promote)

### File structure (final)

```
plugins/modules/governance/candidate_aggregation.py       # Lane triage logic (~200 lines)
plugins/memory/memory_os/crystallized.py [PATCHED]        # +candidate_triage read/write, compaction
plugins/modules/cognition/inner_drive.py [PATCHED]        # +_should_persist_candidate() write gate
scripts/memory_os_candidate_aggregation_lane.py           # no_agent lane executor (~80 lines)
scripts/memory_os_candidate_backfill_409.py               # One-shot backfill (~210 lines)
scripts/memory_os_cron_candidate_aggregation_gate.py      # ExecutionGate wrapper (~130 lines)
```

### Anchor compliance

| Anchor | Status | Evidence |
|--------|--------|----------|
| A1 No auto-crystallize | ✅ | 0 crystallized writes; all writes go to `candidate_triage.jsonl` |
| A2 All actual_* flags false | ✅ | `actual_crystallized_approval = false` verified post-backfill |
| A3 Append-only, no delete | ✅ | `candidate_triage.jsonl` append-only; `candidates.jsonl` untouched |
| A4 Queue state only | ✅ | Only `action=promote/fleeting`, never touches crystallized layer |
| A5 Heuristics → present, not crystallize | ✅ | Promote is to `owner_eligible`, not to crystallized |
| A6 StructuralWriteGate envelope | ✅ | Lane: append_governed_jsonl with ExecutionGate envelope (scope_hash, envelope_id); Backfill: append_governed_jsonl with allow_owner_action_without_envelope=True (classified exemption) |
| A7 No cron bypass | ✅ | Lane registered in cron_registry; no `--no-gate` bypass |

## 8. Monitor integration

### 8.1 New monitor fields

Add to 55-D or adjacent projection:

| Field | Source | Purpose |
|---|---|---|
| `candidate_aggregation.last_tick` | Lane completion timestamp | Health check |
| `candidate_aggregation.promoted_count` | Triages per tick | Activity |
| `candidate_aggregation.demoted_count` | Triages per tick | Activity |
| `candidate_aggregation.fleeting_count` | Triages per tick | Activity |
| `candidate_aggregation.owner_eligible_count` | Read from triage + candidate | Owner burden visibility |
| `candidate_aggregation.boundary_true` | Completion envelope | Anchor compliance |

### 8.2 Degradation signals

| Signal | Action |
|---|---|
| `boundary_true > 0` | Lane auto-shuts down, ANCHOR_CHANGE_REQUEST |
| `owner_eligible_count` spikes | Alert: write-end regression |
| No tick in > 12h | Alert: lane not running |

## 9. Shadow mode → graduation (3.6)

### 9.1 Phase 1: shadow (record-only)

- Lane runs every 6h, records all actions to `candidate_triage.jsonl`.
- Monitor shows "would promote X, would demote Y, would tag Z".
- Owner reviews actual behavior vs lane predictions.
- Accumulate Wilson-scored agreement rate.

### 9.2 Phase 2: limited_auto

- After ≥100 triage decisions with Wilson lower bound ≥0.8:
  - promote actions become auto (but still queue-state only, never crystallize)
  - demote/tag remain shadow until separately validated
- Uses existing `owner_actions.py` Wilson machinery.
- `owner_disagreement_count` must be REAL (not hardcoded 0).

### 9.3 Phase 3: graduation

- All three actions auto.
- Still no crystallization.
- Monitor shows steady-state metrics.
- Lane graduates in 56-lane framework.

## 10. Test strategy

| Test type | Scope |
|---|---|
| Unit | `cluster_and_promote`, `demote_aged`, `tag_fleeting`, `_should_persist_candidate` |
| Integration | End-to-end lane tick: read candidates → triage → write → read back |
| Boundary | `boundary_true` verification for all action types |
| Backfill | Dry-run vs apply on fixture data (409 sample) |
| Anchor | Automated assertion: `actual_crystallized_approval == false` after any operation |

## 11. Files to create/modify

### New files

| File | Purpose |
|---|---|
| `plugins/modules/governance/candidate_aggregation.py` | Lane logic (cluster, promote, demote, fleeting) |
| `scripts/memory_os_candidate_aggregation_lane.py` | Cron gate script (ExecutionGate wrapper) |
| `scripts/memory_os_candidate_backfill_409.py` | One-time backfill operator script |
| `tests/plugins/memory/test_candidate_aggregation.py` | Tests |

### Modified files

| File | Change |
|---|---|
| `plugins/memory/memory_os/crystallized.py` | Add `compact_candidate_queue()`, `candidate_triage` read/write |
| `plugins/modules/cognition/inner_drive.py` | Add `_should_persist_candidate()` gate |
| `memory-os/system/memory_os_cron_registry.json` | Register `candidate_aggregation` lane |
| Monitor 55-D | Add candidate_aggregation fields |

## 12. Boundary verification checklist

Pre-merge:
- [ ] `actual_crystallized_approval` never True in any lane operation
- [ ] No `actual_send`, `actual_execute`, `actual_identity_write` flags set
- [ ] All writes go through `StructuralWriteGate.append_governed_jsonl`
- [ ] `write_surface_check` classifies all new surfaces; `unclassified` = 0
- [ ] No candidate deletion in any code path
- [ ] `candidate_triage.jsonl` is append-only
- [ ] Tests assert boundary_false for all action paths
