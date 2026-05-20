# Plugin Architecture

Date: 2026-05-20

## Design Rule

Do not modularize by copying production scripts one-for-one.

The module boundary is the stable contract:

```text
plugin manifest
  -> dependency checks
  -> profile-local config
  -> lifecycle commands
  -> status / doctor
  -> Memory-OS read/write interfaces
  -> delivery disabled by default
```

Production cron jobs and scripts are implementation evidence, not the final
public API.

## Manifest Contract

Each module should provide a manifest equivalent to:

```yaml
name: wandering_mind
kind: cognition
version: 0.1.0
layer: L2
description: Free-form right-brain reflection over bounded Memory-OS views.

dependencies:
  required:
    - memory_os >=0.1.0
    - scheduler
  optional:
    - household_digest
    - delivery_sink

provides:
  commands:
    - status
    - doctor
    - run-once
  schedules:
    - weekly_wandering
  writes:
    - memory_os.events
    - memory_os.crystallized_candidates
  reads:
    - memory_os.events.summary
    - memory_os.working.summary
    - memory_os.crystallized.approved_summary

defaults:
  enabled: false
  delivery_mode: no-send
  profile_scope: per-profile

memory_os_compat:
  min_version: 0.1.0
  max_version: 0.2.x
  schema_versions:
    event: ["v0", "v1"]
    working: ["v0"]
    crystallized: ["v0"]
```

The exact YAML keys can change after implementation, but every module needs the
same information.

## Lifecycle

Required lifecycle operations:

```text
install
  Copy code and register manifest. Must not start schedules automatically unless
  the operator passes an explicit enable flag.

enable
  Enable module for one profile. Validate dependencies first.

disable
  Stop schedules/hooks for one profile. Preserve data by default.

status
  Show enabled state, last run, dependency health, write roots, and delivery
  mode without printing private bodies.

doctor
  Validate config, dependencies, missing state, stale state, permissions, and
  no-send boundaries.

run-once
  Execute one dry-run/no-send cycle for validation.

uninstall
  Remove module code/registration only. Preserve profile data unless the
  operator explicitly requests a named data cleanup plan.
```

## Config And Data Separation

The plugin code is replaceable. The profile data is not.

```text
code:
  Hermes plugin/module package

config:
  $HERMES_HOME/config.yaml or profile-local module config

data:
  $HERMES_HOME/memory-os/
  $HERMES_HOME/state/<module>/
  profile-local mailbox/message roots where applicable
```

Rules:

- Do not hard-code `/vol1/.hermes` in reusable module code.
- Do not assume main and Sannai share one home.
- Do not store canonical memory outside the active profile's Memory-OS root.
- Upgrading module code must not delete data.
- Disabling a module must stop runtime behavior but keep evidence for review.

## Shared Interfaces

### MemoryOSReadView

```text
recent_events(limit, filters)
working_summary(kinds)
crystallized_summary(kinds)
identity_manifest()
relationship_summary(subjects)
candidate_summary(filters)
```

The read view returns bounded summaries and source references, not raw private
conversation bodies by default.

### MemoryOSWriteSink

```text
append_event(kind, summary, source_ref, tags)
update_working(kind, item)
create_candidate(kind, evidence_refs, proposed_body)
append_audit(action, status, details)
```

Writes must be profile-local. Approved crystallized records and identity files
remain outside automatic module write permissions.

### DeliverySink

```text
would_send(channel, payload_ref, reason)
send(channel, payload_ref)
```

`send` is disabled by default in v0.1. Test-host validation should use
`would_send` audit records unless the owner explicitly enables real delivery.

### ModuleBus

Memory-OS is the data layer, not the runtime control plane. Modules also need a
small coordination surface:

```text
module.discovered(name, version, profile)
module.health_changed(name, state, reason)
module.config_reloaded(profile, changed_keys)
module.event_available(profile, event_ref)
module.disabled(name, reason)
```

v0.1 can implement this as profile-local JSONL state plus status readers. The
interface is still explicit so modules do not poll arbitrary state paths or
infer dependency health from memory records.

### ScheduleCoordinator

Scheduled modules must coordinate long-running work:

```text
acquire_lock(resource_id, owner, ttl)
release_lock(resource_id, owner)
defer_if_running(resource_id, owner)
record_lock_contention(resource_id, owner)
```

v0.1 can use profile-local file locks. Locks are required for:

- Memory-OS heartbeat
- inner-drive runtime
- household digest rebuild
- Wandering Mind run
- governance pipeline
- index rebuild

Failed lock acquisition must degrade to defer/retry, not partial writes.

## Dependency Direction

```text
L4 expression  -> L3 decision -> L2 cognition -> L1 Memory-OS -> L0 runtime
```

Allowed:

- L2 writes events, working state, and candidates.
- L3 evaluates whether a candidate can become a proposal or action.
- L4 decides whether and where a message would be delivered.

Not allowed:

- L2 bypassing L3/L4 to send messages.
- L2 writing identity.
- L4 editing memory state directly except through explicit event records.
- Any module making Hindsight canonical storage.

## Schema Compatibility

Modules must declare the Memory-OS and schema versions they can read and write.

Startup behavior:

```text
1. module loader reads memory_os_compat from the manifest
2. Memory-OS reports current store and schema versions
3. incompatible module refuses to start and writes audit
4. compatible module with unknown newer fields starts read-only on those fields
5. fully compatible module starts normally
```

Memory-OS upgrade behavior:

```text
1. run module.compatibility_check for enabled modules
2. disable incompatible modules before they run
3. write audit for each disabled module
4. emit owner/operator alert through status/doctor
```

Default rule: modules may ignore unknown fields while reading, but they must
not write records using schema versions outside their manifest range.

## Module Classes

| Class | Examples | Default runtime mode |
| --- | --- | --- |
| Cognition | inner-drive, wandering-mind | enabled only on test profile, no-send |
| Governance | self-evolution, ops-gate, proposal-queue | dry-run or report-only |
| Evidence | scoring, signal collection | write evidence records only |
| Messaging | mailbox | receive/read allowed, send disabled by default |
| Context | household digest | local summary generation |
| Expression | speak-gate | would-send audit by default |

## Private Profile Compatibility

Some real deployments contain private profile systems that should not become
public modules. Sannai is the current example.

Portable modules may support private profiles through compatibility adapters,
but the public module contract must not depend on:

- private identity files
- private diary or memory bodies
- private heartbeat policies
- private owner-review decisions
- private prompt/personality text

Compatibility checks are allowed:

- profile-local root separation
- read/write boundary validation
- no-send enforcement
- owner-approval boundary checks
- redacted fixture replay

Extraction is not allowed unless explicitly approved for a private adapter.

## Status Contract

Every module status should answer:

- Is the module installed?
- Is it enabled for this profile?
- Which dependencies are available?
- Which schedules/hooks are active?
- What was the last run time and status?
- Which profile-local roots does it read/write?
- Is delivery disabled, simulated, or enabled?
- Are there private-body redaction guarantees?

## Doctor Contract

Every doctor should detect:

- missing required dependency
- stale state
- invalid config
- hard-coded production path
- unexpected delivery enablement
- cross-profile write attempt
- missing Memory-OS root
- Memory-OS schema or module compatibility mismatch
- lock contention or stale module lock
- private body exposure in status output
- schedule configured without module enablement

## Packaging Boundary

The public repository should contain reusable module code and docs. Private
production snapshots are allowed for analysis but must stay outside GitHub.

If a module needs a production-derived fixture, create a redacted synthetic
fixture or schema-only sample.
