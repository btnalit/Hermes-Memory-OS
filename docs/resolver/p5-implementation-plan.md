# P5: Digest + Injection — Implementation Plan

**Goal:** Connect provisional crystallized records to the owner review surface so they don't silently expire after 7 days. Owner sees countdown timers, can confirm/reject, and prefetch annotates provisional records. Recurrence ≥3 escalates priority.

**Architecture:** 3 files changed. New `_provisional_crystallized_review_items` generator feeds the owner review queue. New `target_type` + `action_type`s allow owner confirm/reject through existing action pipeline. Prefetch `_crystallized_lines` sorts permanent-first and annotates provisional with `(provisional·剩Xd)`.

**Files:** `crystallized.py` (2 small changes), `owner_actions.py` (new generator + wiring), `prefetch.py` (sort + annotate), 2 test files

---

## Context

P0-P4 are complete. Provisional records (P3) are written with `provisional=True` + `expires_at=+7d` and auto-expired by `provisional_sweep`. But owners have NO visibility into them — they silently vanish. P5 closes this loop.

### Key existing infrastructure (reused, not rebuilt)

| What | Where | How P5 uses it |
|------|-------|---------------|
| `CrystallizedMemoryService.list_provisional_records()` | `crystallized.py:432` | Data source for review items |
| `CrystallizedMemoryService.confirm_provisional_record()` | `crystallized.py:364` | Owner confirm → permanent |
| `CrystallizedMemoryService.invalidate_provisional_record()` | `crystallized.py:283` | Owner reject → inactive (needs `"owner_rejected"` reason added) |
| `_review_actions(target_type, target_id)` | `owner_actions.py:4467` | Generates action tokens + targets |
| `_find_crystallized_record(store, record_id)` | `owner_actions.py:5413` | Validates record exists |
| `_bounded_text(value, limit)` | `owner_actions.py:7529` | Text clipping |
| `_priority_sort_key(priority)` | `owner_actions.py:7438` | Queue sorting (existing) |
| `apply_owner_action()` | `owner_actions.py:2176` | Single-action dispatch |
| `_closed_targets()` | `owner_actions.py:7118` | Filters already-processed targets |
| `_budget_keep_priority` | `prefetch.py:1439` | Section-level budget priority (unchanged) |
| `is_active_crystallized_frontmatter()` | `crystallized.py:523` | Active record filter |
| `INACTIVE_CANONICAL_STATES` | `crystallized.py:18` | Inactive states set |

### What does NOT need changing

- **provisional_sweep.py** — recurrence detection already works; P5 reads recurrence from the provisional record set itself (not from sweep output)
- **cognitive_loop.py** — no new step needed; digest generation is CLI/trigger-driven
- **write_surface_check.py** — no new write surfaces (confirm/reject use existing tmp+replace pattern, not `path.open("a")`)
- **cli.py** — existing `owner-review reply` and `owner-review apply` commands work for new action types via the verb mapping

---

## Task 1: Extend `crystallized.py` — owner_rejected state

**File:** `plugins/memory/memory_os/crystallized.py`

Two small changes:

**1a.** Add `"owner_rejected"` to the `state_map` in `invalidate_provisional_record` (line 306-309):

```python
state_map = {
    "resolver_ttl_expired": "provisional_expired",
    "resolver_cap_evicted": "provisional_cap_evicted",
    "owner_rejected": "provisional_rejected",
}
```

**1b.** Add `"provisional_rejected"` to `INACTIVE_CANONICAL_STATES` (line 18-21) and remove the P5 TODO comment:

```python
INACTIVE_CANONICAL_STATES = {
    "owner_revoked", "revoked", "demoted",
    "provisional_expired", "provisional_cap_evicted",
    "provisional_rejected",
}
```

Also update `confirm_provisional_record` (line 399-401) to also reset `"provisional_rejected"` state:

```python
if frontmatter.get("canonical_state") in (
    "provisional_expired", "provisional_cap_evicted", "provisional_rejected",
):
    frontmatter["canonical_state"] = "active"
```

---

## Task 2: Add constants and target mapping in `owner_actions.py`

**File:** `plugins/memory/memory_os/owner_actions.py`

**2a.** Add to `ACTION_TYPES` set (line ~148):
```python
"confirm_provisional_crystallized_record",
"reject_provisional_crystallized_record",
```

**2b.** Add to `TERMINAL_ACTIONS_BY_TARGET_TYPE` (line ~166):
```python
"provisional_crystallized_record": {
    "confirm_provisional_crystallized_record",
    "reject_provisional_crystallized_record",
},
```

**2c.** Add prefix mapping in `_normalize_target` (line ~7135):
```python
"pcrystal": "provisional_crystallized_record",
"provisional-crystallized": "provisional_crystallized_record",
"provisional_crystallized_record": "provisional_crystallized_record",
```

**2d.** Add inference branch in `_normalize_target` (after the expression feedback branch):
```python
if action_type in {"confirm_provisional_crystallized_record", "reject_provisional_crystallized_record"}:
    return "provisional_crystallized_record", value
```

---

## Task 3: Add validation + state transition + verb mapping

**File:** `plugins/memory/memory_os/owner_actions.py`

**3a.** `_validate_action_target` (line ~2822) — add before `return ""` at end:
```python
if action_type in {"confirm_provisional_crystallized_record", "reject_provisional_crystallized_record"}:
    if target_type != "provisional_crystallized_record":
        return "invalid_provisional_crystallized_record_target"
    service = CrystallizedMemoryService(store)
    found = service.find_record(target_id)
    if found is None:
        return "provisional_crystallized_record_not_found"
    if found.frontmatter.get("provisional") is not True:
        return "provisional_crystallized_record_not_provisional"
    if not is_active_crystallized_frontmatter(found.frontmatter):
        canon = found.frontmatter.get("canonical_state", "active")
        return f"provisional_crystallized_record_already_{canon}"
```

**3b.** `_apply_state_transition` (line ~2595) — add handlers before final `return {}`:
```python
if action_type == "confirm_provisional_crystallized_record":
    result = CrystallizedMemoryService(store).confirm_provisional_record(
        target_id, confirmed_by=str(record["owner_id"]),
    )
    record["owner_effect"]["owner_confirmed_provisional"] = True
    return {"record_id": target_id, "canonical_state_changed": result.get("canonical_state_changed", False)}

if action_type == "reject_provisional_crystallized_record":
    result = CrystallizedMemoryService(store).invalidate_provisional_record(
        target_id, reason="owner_rejected", invalidated_by=str(record["owner_id"]),
    )
    record["owner_effect"]["owner_rejected_provisional"] = True
    return {"record_id": target_id, "canonical_state_changed": result.get("canonical_state_changed", False)}
```

**3c.** `_owner_action_type_from_reply` (line ~5172) — add before `return ""`:
```python
if verb in ("approve", "confirm") and target_type == "provisional_crystallized_record":
    return "confirm_provisional_crystallized_record"
if verb == "reject" and target_type == "provisional_crystallized_record":
    return "reject_provisional_crystallized_record"
```

**3d.** `_reply_verb_matches_action_type` (line ~5203) — add branches for the new action types.

**3e.** `_review_actions` (line ~4467) — add before `return []`:
```python
if target_type == "provisional_crystallized_record":
    return [
        _review_action("confirm", "confirm_provisional_crystallized_record", target_type, target_id),
        _review_action("reject", "reject_provisional_crystallized_record", target_type, target_id),
    ]
```

---

## Task 4: Create `_provisional_crystallized_review_items` generator

**File:** `plugins/memory/memory_os/owner_actions.py`

Insert new function before `_created_at_with_source` (~line 3844). The function:

1. Reads `CrystallizedMemoryService(store).list_provisional_records()`
2. Computes body content hashes for recurrence detection (≥3 same hash → escalate)
3. For each record not in `closed`, computes `remaining_days` from `expires_at`
4. Priority: recurrence≥3 OR ≤3d remaining → `action_required`; ≤5d → `review_suggested`; else `fyi`
5. Summary includes `(剩Xd)` countdown + `⚠high-recurrence(Nx)` if applicable
6. Generates confirm/reject action tokens via `_review_actions`
7. Returns list of `schema_version: "memory-os.review_item.v0"` items with fields: `review_item_id`, `target_type`=`"provisional_crystallized_record"`, `target_id`, `source_module`=`"crystallized_memory"`, `priority`, `summary`, `provisional_body`, `expires_at`, `remaining_days`, `recurrence_count`, `action_tokens`, `action_targets`, etc.

Full implementation in the task — key pattern matches `_candidate_review_items`.

---

## Task 5: Wire generator into queue reports

**File:** `plugins/memory/memory_os/owner_actions.py`

**5a.** In `owner_review_queue_report` (~line 2153), after the last `items.extend(...)`:
```python
items.extend(_provisional_crystallized_review_items(store, closed))
```

**5b.** In `owner_review_aging_report` (~line 1515), after the last `items.extend(...)`:
```python
items.extend(_provisional_crystallized_review_items(store, closed))
```

---

## Task 6: Prefetch annotation + sorting in `_crystallized_lines`

**File:** `plugins/memory/memory_os/prefetch.py`

Replace `_crystallized_lines` (line 877-906) with version that:

1. Parses `provisional`, `expires_at`, `recurrence` from each record's frontmatter
2. Splits into `permanent_lines` (provisional≠True) and `provisional_entries` list
3. For provisional: computes `days_remaining`, builds annotated line:
   ```
   - {filename}/{kind}: (provisional·剩{d}d){recurrence_marker} {body}
   ```
   where `recurrence_marker` = ` ⚠high-recurrence` if recurrence ≥3
4. Sorts provisional entries by `expires_at` ascending (closest expiry first)
5. Returns `permanent_lines + sorted_provisional_lines`

Use `·` (middle dot) for the `·` character. Unicode `剩` = `剩`.

---

## Task 7: Tests

### File: `tests/plugins/memory/test_memory_os_owner_actions.py`

**7a.** `test_provisional_crystallized_review_items_generates_queue_items` — creates a provisional record, calls generator, asserts item has correct fields, action tokens, countdown

**7b.** `test_provisional_review_items_priority_based_on_expiry` — creates records with 2d and 10d expiry, asserts correct priority escalation

**7c.** `test_provisional_review_items_recurrence_escalation` — creates 3 records with identical body, asserts all get `action_required` + recurrence=3

**7d.** `test_confirm_provisional_through_owner_action` — creates provisional record, calls `apply_owner_action(action_type="confirm_provisional_crystallized_record", ...)`, asserts provisional=False + confirmed_by set

**7e.** `test_reject_provisional_through_owner_action` — creates provisional record, calls `apply_owner_action(action_type="reject_provisional_crystallized_record", ...)`, asserts canonical_state="provisional_rejected"

**7f.** `test_reject_provisional_sets_provisional_rejected_state` — directly calls `invalidate_provisional_record(reason="owner_rejected")`, verifies state and INACTIVE_CANONICAL_STATES

### File: `tests/plugins/memory/test_memory_os_prefetch.py`

**7g.** `test_crystallized_lines_annotates_provisional_with_countdown` — creates provisional record, calls `_crystallized_lines`, asserts `provisional·剩` marker present

**7h.** `test_crystallized_lines_sorts_permanent_before_provisional` — creates one permanent + one provisional, asserts permanent line appears first

---

## Task 8: Full verification

```bash
python -m pytest tests/plugins/memory/test_memory_os_owner_actions.py -v -k "provisional"
python -m pytest tests/plugins/memory/test_memory_os_prefetch.py -v -k "crystallized_lines"
python -m pytest tests/plugins/memory/ -q
python scripts/memory_os_write_surface_check.py
python scripts/memory_os_static_hygiene_check.py
python scripts/memory_os_public_checkout_probe.py --source working-tree --strict
git diff --check
```

---

## Implementation Order

Tasks 1 and 6 are independent (different files). Task 1 can be first (no deps). Tasks 2-5 form a sequential chain within `owner_actions.py`. Task 7 comes last.

1. Task 1: crystallized.py changes (owner_rejected state)
2. Task 2: owner_actions.py constants + target mapping
3. Task 3: owner_actions.py validation + transition + verb mapping
4. Task 4: owner_actions.py generator function
5. Task 5: owner_actions.py wire into queue reports
6. Task 6: prefetch.py annotation + sorting
7. Task 7: tests
8. Task 8: full verification + commit

---

## Spec Assertions Covered

| Assertion | Where |
|-----------|-------|
| R2.2 owner confirm → provisional=False, permanent | Task 3b + 7d |
| R2.3 owner reject → invalidate, audit | Task 1 + 3b + 7e |
| R2.6 recurrence ≥3 → digest high priority | Task 4 + 7c |
| R4.1 provisional injected with (provisional·剩Xd) | Task 6 + 7g |
| R4.2 budget priority: provisional after permanent | Task 6 + 7h |
| G.4 pytest -q all green + write_surface check | Task 8 |
