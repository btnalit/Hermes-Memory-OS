# Memory-OS Migration Notes

This document defines the v0 migration process for moving legacy Hermes/Sannai
memory shapes into a Memory-OS shadow profile. The process is staged,
auditable, and dry-run first.

## Safety Rules

- Production `10.20.2.88` is read-only unless the owner explicitly approves a
  later pilot.
- Scan and export never modify source files.
- Shadow import writes only to the target profile's `$HERMES_HOME/memory-os/`.
- Replay never sends owner messages, Telegram messages, mailbox messages, or
  Hindsight adapter exports.
- CW-019 `owner_eligible` maps to Memory-OS visibility approval only. It does
  not create approved crystallized memory.
- Identity sources remain in their legacy protected locations. Memory-OS records
  pointers and checksums; it does not create a second SOUL source of truth.

## States

| State | Purpose | Writes |
| --- | --- | --- |
| `scan_only` | Read legacy source metadata, hashes, counts, and CW-019 status counts. | none |
| `redacted_bundle` | Build a transport bundle without private bodies by default. | bundle output path only |
| `shadow_import` | Import a bundle into a non-production shadow profile. | target `$HERMES_HOME/memory-os/**` only |
| `shadow_replay` | Re-read imported events and prove no delivery/export side effects. | audit only when `--apply` is used |
| `diff_report` | Compare source report and target store for owner review. | none |
| `owner_review` | Human checkpoint before any pilot apply step. | none |
| `approved_apply` | Reserved for a future owner-approved production pilot. | not implemented in v0 |
| `rollback_ready` | Preserve evidence and return provider config to the prior state. | runbook only in v0 |

## Commands

Scan legacy metadata:

```powershell
hermes memory-os migrate scan `
  --profile sannai `
  --hermes-home <legacy-profile-home> `
  --state-root <legacy-state-root> `
  --dry-run
```

Export a redacted shadow bundle:

```powershell
hermes memory-os migrate export-shadow `
  --profile sannai `
  --hermes-home <legacy-profile-home> `
  --state-root <legacy-state-root> `
  --redacted `
  --out <bundle-path>
```

Import into a shadow profile. The command is dry-run by default; actual shadow
import requires `--apply`.

```powershell
hermes memory-os migrate import-shadow `
  --bundle <bundle-path> `
  --profile sannai-shadow `
  --hermes-home <shadow-profile-home> `
  --apply
```

Replay the shadow import with all outward effects disabled:

```powershell
hermes memory-os migrate replay `
  --profile sannai-shadow `
  --hermes-home <shadow-profile-home> `
  --no-adapter-export `
  --apply
```

Generate the owner-review diff:

```powershell
hermes memory-os migrate diff `
  --source-report <bundle-path>\manifest.json `
  --target-root <shadow-profile-home>\memory-os
```

## Owner Review Checklist

Before a production pilot, the owner should review the `diff_report` and confirm:

- `source_count` equals `imported_count`.
- `schema_errors` is empty.
- `skipped_private_body_count` is expected for the selected bundle mode.
- `approval_state_mapping.owner_eligible` is
  `approved_for_s5_visibility`, not crystallized approval.
- `crystallized_count` is zero unless a later explicit approval slice created
  records.
- `would_write_paths` are limited to the shadow target root and known bundle
  path.

## Rollback Boundary

v0 rollback is configuration and evidence preservation, not deletion:

1. Stop new Memory-OS validation writes for the profile.
2. Restore the previous memory provider config.
3. Keep `$HERMES_HOME/memory-os/` as evidence.
4. Do not replay Memory-OS events into Hindsight.
5. Run `hermes memory-os doctor` on the evidence root before any later retry.
