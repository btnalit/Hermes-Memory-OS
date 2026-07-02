# Task P2.3 Report — approve_external_evidence Owner Action

## Status: DONE

## Commit
After writing this report, the commit will contain:
- `plugins/memory/memory_os/owner_actions.py` — 6 edits
- `tests/plugins/memory/test_memory_os_external_evidence_owner_action.py` — new test file (5 tests)

## Changes Made

### 1. ACTION_TYPES set (line ~149)
Added `"approve_external_evidence"` to the set of known action types.

### 2. TERMINAL_ACTIONS_BY_TARGET_TYPE (line ~173)
Added `"approve_external_evidence"` to the `"candidate"` entry alongside `approve_candidate` and `reject_candidate`.

### 3. _normalize_target (line ~7693)
Extended the existing `approve_candidate`/`reject_candidate` check to include `approve_external_evidence`, mapping it to `"candidate"` target type.

### 4. _validate_action_target (line ~3056)
Added validation block for `approve_external_evidence`:
- Rejects non-existent candidates (`candidate_not_found`)
- Rejects non-tainted candidates (`candidate_not_tainted`)
- Rejects candidates without resolvable external ref (`external_evidence_ref_unresolved`)

### 5. _apply_state_transition (line ~2724)
Added branch before `approve_candidate` that creates an `ApprovalDecision` with `external_evidence_ack=True` and the resolved `acked_external_ref`. The `acked_external_ref` is sourced from `reply_context` (stored in `record["action_context"]["acked_external_ref"]` via `_attach_owner_reply_context`), falling back to the candidate's own external ref.

### 6. _attach_owner_reply_context (line ~3698)
Added pass-through for `acked_external_ref` from `reply_context` into `record["action_context"]["acked_external_ref"]`.

## Test Results
- All 5 new tests: PASS
- Full regression: 1693 passed, 8 skipped

## Static Checks
- write_surface: 0 unclassified (PASS)
- import_cycle: 0 cycles (PASS)
- static_hygiene: all PASS

## Design Verification
- **P0 wall intact**: `_ensure_crystallized_approval` still enforces `external_evidence_ack=True` and ref matching. The P0 wall was not modified.
- **Ordinary `approve_candidate` unchanged**: It never sets `external_evidence_ack`, so tainted candidates are still blocked by the P0 wall.
- **No `ragflow` literals** in `plugins/memory/memory_os/`
