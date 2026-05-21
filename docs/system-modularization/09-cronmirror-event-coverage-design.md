# CronMirror Event Coverage Design

Date: 2026-05-21

## Goal

Bring Hermes cron execution facts into Memory-OS while preserving Hermes as the
owner of cron scheduling and delivery.

CronMirror is a read-only mirror. It does not replace Hermes cron, does not
change jobs, and does not trigger or deliver anything. Its only job is to scan
Hermes cron metadata and output files, then append summary-only Memory-OS events
that make scheduled activity visible to working memory, diagnostics, and later
owner review.

## Why This Is Needed

Foreground Hermes conversations enter Memory-OS through the normal provider
path:

```text
AIAgent.run_conversation
  -> MemoryManager.prefetch_all()
  -> MemoryProvider.prefetch()
  -> MemoryManager.sync_all()
  -> MemoryProvider.sync_turn()
```

That covers CLI and gateway conversations when the active profile has
`memory.provider=memory_os`.

Hermes cron is different.

From the local Hermes source:

- `cron/jobs.py` stores jobs in `~/.hermes/cron/jobs.json`
- `cron/jobs.py` stores outputs in `~/.hermes/cron/output/{job_id}/{timestamp}.md`
- `cron/scheduler.py` has a `no_agent` branch that never constructs `AIAgent`
- the normal cron LLM branch constructs `AIAgent(..., platform="cron",
  skip_memory=True, ...)`

So both cron paths bypass the external memory provider:

```text
Hermes cron agent job
  -> AIAgent(... skip_memory=True, platform="cron")
  -> no MemoryManager
  -> no Memory-OS provider sync_turn

Hermes cron no_agent job
  -> run script
  -> save output
  -> no AIAgent
  -> no MemoryManager
  -> no Memory-OS provider sync_turn
```

This is intentional in Hermes core because cron prompts and detached scheduled
work can corrupt user-facing memory if blindly injected into the normal memory
tool path. Memory-OS should respect that decision and add a safer mirror layer
instead of forcing provider memory back on inside cron.

## Read-Only Host Probe

Target host:

```text
10.20.3.200 / hermes-media
HERMES_HOME=/root/.hermes
```

Read-only probe on 2026-05-21:

```text
Memory-OS status:
  status: available
  root: /root/.hermes/memory-os
  events: 11
  working_items: 12
  crystallized_candidates: 12
  crystallized_records: 0
  queue_backlog: 0
  prefetch_mode: indexed
  index_health: healthy

Cron state:
  /root/.hermes/cron exists
  /root/.hermes/cron/jobs.json absent
  /root/.hermes/cron/output exists
  output job dir count: 0
  .tick.lock exists
```

Interpretation:

- the current test host has no configured Hermes cron jobs
- an empty cron environment must be a normal `ok` state
- CronMirror must not require `jobs.json` to exist
- tests need fixtures for both empty and populated cron directories

## Existing Sannai Coverage On 10.20.2.88

Read-only probe on the old production host confirmed that Sannai cron was
already "covered", but not through the external memory provider. Its coverage
is a profile-specific memory-contract pipeline.

Observed Sannai profile state:

```text
Host: 10.20.2.88 / YC-NAS
Sannai profile home: /root/.hermes/profiles/sannai
Sannai cron jobs: 10
Sannai cron output files: 857
Recent Sannai session files: source=cron sessions present
Request overlay: recent_events(computed) exists and would inject
```

The old Sannai coverage has three layers:

1. Cron session coverage
   - normal Sannai agent cron jobs run as `platform=cron`
   - Hermes stores cron sessions under the Sannai profile session root
   - the Sannai memory contract computes `recent_events` from those sessions
   - those computed events are injected into the Sannai request overlay

2. Script-state coverage
   - `no_agent` jobs write deterministic state files, not provider memory
   - examples include `memory_journal/events.jsonl`, daily digests,
     treasure index, and weekly consolidation proposals
   - those state files become later overlay or digest inputs

3. CW-019 quiet/candidate coverage
   - the live heartbeat process writes `quiet_moments.jsonl` and
     `heartbeat_lingering_candidates.jsonl`
   - these are backend candidate surfaces only
   - they are not long-term memory writes, not S5 delivery, and not identity
     updates

Design consequence:

- CronMirror is not the whole source coverage feature
- CronMirror covers execution facts from Hermes cron metadata and output files
- session-derived coverage belongs to `SessionMirror` / `SourceMirror`
- state-file coverage belongs to `StateSourceMirror`
- the full Runtime Hardening target is the three-part mirror family:
  `CronMirror + SessionMirror/SourceMirror + StateSourceMirror`
- this mirrors the old Sannai coverage pattern as a public, generic mechanism
  that Sannai can later use during migration without copying private persona
  or identity logic into the public modules
- all Sannai-compatible mirrors must keep the old invariants: no private body
  export, no identity writes, no automatic crystallized approval, no S5, and no
  production mutation

## Scope

In scope:

- scan `cron/jobs.json` if present
- scan `cron/output/{job_id}/*.md` if present
- derive run metadata from output file path, mtime, size, hash, and safe headers
- append Memory-OS events for newly observed cron outputs
- write Memory-OS audit entries for mirror scans
- expose CLI/status/doctor evidence for operator checks

Out of scope:

- creating, editing, pausing, resuming, deleting, or triggering cron jobs
- changing Hermes cron scheduler behavior
- enabling memory inside cron `AIAgent`
- delivery to Telegram, WeCom, Weixin, mailbox, or any other channel
- embedding raw cron prompts, scripts, stdout, stderr, or full output body
- parsing secrets from cron output
- production host `10.20.2.88`
- copying Sannai's private profile-specific request overlay or memory contract
  into the public module
- reading or exporting private Sannai session bodies
- treating CW-019 quiet moments or candidates as approved crystallized memory

## Coverage Matrix

| Entry | Current provider coverage | CronMirror target |
| --- | --- | --- |
| CLI conversation | provider `sync_turn` | no extra mirror |
| Telegram conversation | provider `sync_turn` | no extra mirror |
| WeCom conversation | provider `sync_turn` | no extra mirror |
| Weixin conversation | provider `sync_turn` | no extra mirror |
| Other gateway conversation | provider `sync_turn` | no extra mirror |
| Hermes cron LLM job | bypassed by `skip_memory=True` | mirror output metadata |
| Hermes cron `no_agent` job | no agent exists | mirror output metadata |
| Cron/session history outside provider path | profile-local session store | SessionMirror target |
| Script-written state files | profile-specific state writers | StateSourceMirror target |
| CW-019-like quiet/candidate files | backend candidate surfaces | StateSourceMirror target, candidate-only |
| Memory-OS heartbeat timer | Memory-OS runtime audit | no cron mirror |
| Portable module scheduled job | future module runtime | module audit, not Hermes cron |

## Event Shape

CronMirror appends standard Memory-OS event envelopes.

```json
{
  "schema_version": "memory-os.event.v0",
  "source": "cron",
  "kind": "cron_job_run",
  "summary": "Cron job <job_id or name> wrote output; mode=<agent|no_agent|unknown>; status=<ok|error|silent|unknown>.",
  "safe_ref": {
    "job_id": "...",
    "job_name": "...",
    "output_relpath": "cron/output/<job_id>/<timestamp>.md",
    "output_mtime": "...",
    "output_size": 1234,
    "mode": "agent | no_agent | unknown",
    "status": "ok | error | silent | unknown",
    "deliver": "...",
    "last_run_at": "...",
    "last_status": "...",
    "last_delivery_error_present": false
  },
  "tags": ["memory-os", "cron", "cron_job_run"],
  "sensitivity": "private",
  "body_policy": "summary_only",
  "hashes": {
    "output_sha256": "...",
    "job_metadata_sha256": "..."
  },
  "promotion_state": "raw"
}
```

The event must not include:

- full prompt
- full response
- script body
- stdout/stderr body
- raw secrets
- delivery destination body beyond stable non-secret identifiers already present
  in safe job metadata

## Status Inference

Cron output files are markdown documents produced by Hermes core. They may
contain headers such as:

```text
# Cron Job: <name>
**Job ID:** <id>
**Run Time:** <time>
**Mode:** no_agent (script)
**Status:** silent (empty output)
```

CronMirror may parse only bounded header lines. It must stop before prompt,
response, error body, script output, or arbitrary markdown content.

Recommended inference order:

1. job metadata from `jobs.json`, if the job still exists
2. safe headers from the output document
3. filename, mtime, and size
4. fallback `unknown`

Specific cases:

- `# Cron Job: ... (FAILED)` -> `status=error`
- header `**Status:** silent (...)` -> `status=silent`
- metadata `last_status=ok` for the matching job and latest run -> `status=ok`
- metadata `last_delivery_error` present -> `last_delivery_error_present=true`
- absent `jobs.json` or removed job -> keep `job_id`, set `job_name=""`,
  `mode=unknown`, `status=unknown`

## Idempotency

CronMirror must be safe to run repeatedly.

Dedup key:

```text
cron_output::<job_id>::<output_filename>::<output_sha256>
```

State file:

```text
$HERMES_HOME/memory-os/runtime/cron_mirror_state.json
```

State shape:

```json
{
  "schema_version": "memory-os.cron_mirror_state.v0",
  "seen_outputs": {
    "cron_output::<job_id>::<filename>::<sha256>": {
      "event_id": "...",
      "indexed_at": "..."
    }
  },
  "last_scan_at": "..."
}
```

If the output file changes after being indexed, the hash changes and CronMirror
may append a new event. This should be rare because Hermes writes output through
an atomic replace path.

State recovery:

- `cron_mirror_state.json` is rebuildable from Memory-OS events that carry the
  cron dedup key and source hash
- if the state file is missing or corrupt, CronMirror must rebuild it before
  applying a scan
- if rebuild cannot prove whether an output was already mirrored, recurring
  scans fail closed and report `rebuild_state_incomplete`
- operator-triggered repair may choose to append a replacement event, but that
  is not the default runtime behavior

## Empty Environment Behavior

An empty cron environment is expected on a blank host.

```text
jobs.json missing
output/ present but empty
```

Doctor result:

```json
{
  "status": "ok",
  "job_count": 0,
  "output_file_count": 0,
  "pending_output_count": 0
}
```

It should not warn unless:

- `cron/` cannot be read
- `output/` exists but is malformed in a way that prevents scanning
- Memory-OS store cannot append events

## CLI Shape

Add Memory-OS CLI commands:

```text
hermes memory_os cron-mirror status
hermes memory_os cron-mirror doctor
hermes memory_os cron-mirror scan --dry-run
hermes memory_os cron-mirror scan --apply
```

Default behavior:

- `scan` defaults to dry-run
- `--apply` is required to write events
- status/doctor never print raw cron output bodies

Example dry-run output:

```json
{
  "schema_version": "memory-os.cron_mirror_report.v0",
  "status": "ok",
  "job_count": 0,
  "output_file_count": 0,
  "new_event_count": 0,
  "dry_run": true
}
```

## Runtime Integration

CronMirror can run as part of Runtime Hardening after the stability gate.

Recommended order:

1. implement local fixtures and tests
2. validate `scan --dry-run` on 10.20.3.200
3. validate `scan --apply` on an isolated temporary `HERMES_HOME`
4. apply on 10.20.3.200 only after the dry-run report is clean
5. run `hermes memory_os heartbeat --max-events 100`
6. run `hermes memory_os doctor`

Do not add a systemd timer for CronMirror in the first implementation. The first
implementation should be operator-triggered so event shape and scan behavior can
be reviewed before recurring execution.

## Test Plan

Unit fixtures:

- no `cron/jobs.json`, empty `cron/output/`
- one agent cron output with job metadata
- one `no_agent` silent output
- one failed cron output
- output for removed job
- repeated scan does not duplicate events
- changed output hash creates a new event
- raw output body is not embedded in event summary or safe_ref

Integration tests:

- Memory-OS store append path receives `cron_job_run` events
- heartbeat processes cron events into working/candidates without special cases
- index sync records `source=cron` and `kind=cron_job_run`
- doctor reports empty cron environment as `ok`

Host validation on 10.20.3.200:

```bash
HERMES_HOME=/root/.hermes hermes memory_os cron-mirror status
HERMES_HOME=/root/.hermes hermes memory_os cron-mirror doctor
HERMES_HOME=/root/.hermes hermes memory_os cron-mirror scan --dry-run
```

Expected current host result:

```text
status=ok
job_count=0
output_file_count=0
new_event_count=0
dry_run=true
```

## Acceptance Criteria

CronMirror is accepted when:

- it proves why Hermes cron is outside provider coverage
- it treats empty cron state as normal
- it mirrors both agent cron and `no_agent` cron outputs
- it is idempotent
- it never exposes raw cron bodies
- it never mutates Hermes cron state
- it writes only Memory-OS events/audit when `--apply` is explicit
- it can be run safely on 10.20.3.200 after dry-run review

## Open Decisions Before Implementation

1. Whether `job_metadata_sha256` should hash the whole sanitized job metadata or
   only a fixed allowlist.
   - recommendation: fixed allowlist

2. Whether removed-job outputs should keep only `job_id` or also parse the name
   from the markdown title.
   - recommendation: parse bounded title line, still hash output file

3. Whether the first implementation should include a timer.
   - recommendation: no timer in first implementation; add timer only after
     operator-triggered validation

4. Whether CronMirror should inspect old output files from before Memory-OS
   deployment.
   - recommendation: yes for 10.20.3.200 if present, but cap the first scan and
     require dry-run review; no production scan in this phase
