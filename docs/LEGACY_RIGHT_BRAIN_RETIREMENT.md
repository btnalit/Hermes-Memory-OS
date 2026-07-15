# Legacy Right-Brain Retirement Runbook

## Scope

This retirement covers the legacy execution lane:

- `wandering_mind`
- `grounded_expression_judge`
- `spontaneous_expression`
- `memory-os-right-brain-expression`
- `memory-os-right-brain-expression-outcome`

It does **not** delete the legacy implementation. Deletion is a separate change
that may happen only after V3 has a stable production observation period.

## Retirement contract

After retirement:

1. The three legacy steps are absent from the active cognitive-loop step list.
2. A literal `legacy_cognitive_loop_enabled=true` cannot reactivate them after
   any retirement marker exists. Invalid or partial manifests fail closed for
   execution while status remains an explicit integrity error.
3. Legacy cron specs are absent from the active Memory-OS cron registry and
   onboarding cannot recreate them. Existing jobs must be paused before the
   retirement operation and may then be removed from the scheduler.
4. `wandering_mind_state` and `wandering_mind_cadence` are absent from active
   signal collection and MemoryProjection.
5. Legacy cadence/dashboard items are excluded from active health surfaces.
6. Existing legacy right-brain module files, including the old wandering output,
   expression draft/judge/gate/adapter ledgers, the canonical
   `memory-os/system/speak_permission_tickets.jsonl` ledger, legacy
   speak-permission module history, and DeepReflection wandering seeds, are
   moved through a recoverable pending manifest into a timestamped read-only
   archive. The manifest contains hashes and counts, not private bodies.
7. Any recreation of the live legacy path, archive hash drift, writable archive
   file, or enabled legacy cron is a monitor failure.
8. Archived bodies must not enter retrieval, index, prefetch, V3 seed evidence,
   delivery, or ordinary backups.

## Operator procedure

Always back up production config and artifacts before apply.

```bash
python3 scripts/memory_os_retire_legacy_right_brain.py \
  --hermes-home ~/.hermes
```

The default is dry-run. Apply only after confirming:

- `legacy_cognitive_loop_enabled` is not literal JSON `true`;
- both legacy cron jobs are paused;
- the reported archive inventory is bounded and contains no raw body in the
  report.

```bash
python3 scripts/memory_os_retire_legacy_right_brain.py \
  --hermes-home ~/.hermes \
  --apply
```

Verify:

```bash
python3 scripts/memory_os_retire_legacy_right_brain.py \
  --hermes-home ~/.hermes \
  --status
```

Required result:

```text
lifecycle=retired
status=ok
post_cutoff_file_count=0
post_cutoff_jsonl_record_count=0
enabled_legacy_cron_count=0
archive_hash_mismatch_count=0
archive_writable_file_count=0
archive_writable_directory_count=0
manifest_writable=false
raw_body_included=false
```

## Historical audit boundary

The retirement manifest is the active audit surface. The archive itself is
owner-controlled, read-only evidence and is not a live Memory-OS source.
Monitoring may expose only lifecycle, counts, timestamps, hashes/integrity, and
zero-growth status. It must not expose archived text.

## Final deletion gate

Do not delete legacy execution code or the archive until all of the following
are independently verified:

- V3 private wandering has completed the required seed-evidence period;
- V3 retention and provenance gates have stable production evidence;
- the live legacy path has remained absent throughout the observation period;
- no active source, cron, dashboard, monitor, test, or adapter depends on the
  legacy execution contract;
- the owner explicitly approves deletion as a separate irreversible change.
