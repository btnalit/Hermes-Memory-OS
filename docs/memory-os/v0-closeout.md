# Memory-OS v0 Closeout

Date: 2026-05-20

This document closes the Memory-OS v0 implementation stage.

## Scope Closed

Memory-OS v0 now covers the complete validation loop:

```text
provider install/discovery
  -> sync_turn event capture
  -> filesystem canonical store
  -> runtime heartbeat
  -> working memory and crystallized candidate queue
  -> SQLite/FTS runtime index
  -> indexed prefetch
  -> provider self-diagnostics
  -> diagnostic grounding against stale recall
```

## Final Slice

Slice 21 closes the last known v0 correctness gap: provider diagnostic answers
must use current Memory-OS runtime facts, not stale Hindsight-era recall.

Validated behavior:

- diagnostic questions suppress indexed recall before `index.search()` runs
- current runtime facts are injected from the same path as `memory_os_status`
- tight prefetch budgets keep `provider`, `canonical_store`, `storage_model`,
  and `uses_hindsight_http_api`
- `forbidden_claims` remain in the tool contract but are not inserted into the
  prefetch context as text to repeat
- Sannai profile defaults diagnostic grounding off
- non-user-facing paths can disable diagnostic grounding explicitly

## Validation Evidence

Local:

```text
python -m pytest -q
107 passed

python -m compileall -q agent plugins scripts
passed

git diff --check
passed
```

`10.20.3.200`:

```text
python3 -m pytest -q
107 passed

python3 -m compileall -q agent plugins scripts
passed

main gateway loaded refreshed plugin
memory_os active
doctor status ok
index health healthy
```

Live Telegram confirmation:

```text
provider=memory-os
canonical_store=/root/.hermes/memory-os
storage_model=local filesystem JSONL + Markdown
Hindsight=optional adapter, not canonical
uses_hindsight_http_api=false
```

## Boundaries Kept

- `10.20.2.88` production was not contacted during Slice 21 implementation.
- No production gateway was restarted.
- No production Hindsight bank was modified.
- No identity source was modified.
- Sannai gateway was not started or restarted.
- Crystallized records remain owner-approval only.

## What Stops Here

Do not add more v0 features by default. The next stage is observation, not
expansion.

Recommended next phase:

```text
run Memory-OS on 10.20.3.200 main profile for 1-2 weeks
collect real diagnostic, recall, heartbeat, index, and doctor evidence
only open v0.1 work from observed issues
```

## Explicitly Not Included In v0

- production provider migration
- production Sannai migration
- autonomous production inner-drive scheduling
- Hindsight export to a real production bank
- write-side stale-memory adjudication
- vector or graph retrieval
- production rollback rehearsal
