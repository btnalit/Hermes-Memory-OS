# 26 - RH-29 Memory Sources Attribution Design

Status: implemented on test host; 24-hour observation gate open
Date: 2026-05-23

## Goal

RH-29 adds a bounded Memory Sources attribution ledger for live prefetch builds.

The purpose is to answer:

```text
What memory/context sources were made visible to the model for this turn, and
why?
```

This is observability first. It must not change model behavior.

## Why This Comes First

RH-26 and RH-28 improved context relevance, but they still leave an operator
gap: after a Telegram turn, the owner can observe the answer but cannot easily
inspect which Memory-OS sources shaped that answer without rerunning probes.

RH-29 creates the evidence layer needed before relevance feedback, top-of-mind
scoring, or consolidation suggestions can be responsibly implemented.

## Non-Goals

- Do not change `build_prefetch()` output.
- Do not create or modify events.
- Do not create or modify working memory.
- Do not create candidates.
- Do not approve crystallized records.
- Do not write identity or relationship memory.
- Do not add LLM relevance judgment.
- Do not print or persist raw private prompts or section bodies.
- Do not add a Top-of-Mind tier.
- Do not depend on Hermes `pre_llm_call`.

## Query Class

RH-29 must not introduce a new query classifier.

Initial rule:

```text
query_class = RH-26 route
```

Examples:

- `foreground_control`
- `active_task`
- `casual_continuity`
- `diagnostic_current_status`
- `candidate_review`
- `memory_architecture_discussion`
- `ambiguous_recall`

Reason:

- RH-26 already owns deterministic route classification.
- A second query classifier would create drift and explainability gaps.
- If route-level classes are too coarse, that should be handled by future
  route refinement, not by a parallel RH-29 classifier.

If route is unavailable:

- record `query_class="unknown"`
- record reason `route_unavailable`
- do not record raw query text as fallback

## Write Frequency

The initial version writes one attribution record per live prefetch build.

This includes:

- Telegram turns
- CLI/gateway turns that call provider prefetch
- synthetic validation probes only when explicitly run through the live prefetch
  path

It does not include:

- dry-run context router reports unless explicitly requested
- monitor-only RH-26 heading probes, unless a future flag records them
- DeepReflection internal run-only cycles

Reason:

- per-prefetch attribution is the correct unit for answering "what context was
  visible to the model?"
- sampling before we know growth behavior would hide the very signal we need

First gate:

- 24 hours on `10.20.3.200`, not 7 days
- monitor reports:
  - record count delta
  - file size delta
  - records per event
  - route distribution
  - source-class distribution
  - dropped reason-code distribution

If the 24-hour gate is clean, continue observing without blocking other work.
If growth is noisy, tune retention/sampling before adding RH-30.

## Storage

Path:

```text
$HERMES_HOME/memory-os/system/memory_sources.jsonl
```

One JSON object per line.

This ledger is system metadata, not canonical memory.

It is intentionally outside:

- `events`
- `working`
- `crystallized_candidates`
- `crystallized_records`
- `identity`
- `relationships`

## Relationship To Audit

Audit and Memory Sources serve different purposes.

Audit:

- canonical system fact stream
- records that something happened
- used for governance, debugging, and traceability

Memory Sources:

- prefetch-level attribution ledger
- records what context sections were made visible for a specific model turn
- used for explainability, feedback attachment, and router tuning

Rules:

- RH-29 must not duplicate every attribution record into canonical audit.
- A coarse audit entry may record that Memory Sources attribution is enabled or
  failed, but not every prefetch.
- Memory Sources records must not feed working memory, candidates, or
  crystallized records.

## Record Schema

Draft schema:

```json
{
  "schema_version": "memory-os.memory_sources.v0",
  "record_id": "msrc_20260523T061234123456Z_ab12cd34",
  "created_at": "2026-05-23T06:12:34.123456Z",
  "profile": "default",
  "query_class": "ambiguous_recall",
  "route": "ambiguous_recall",
  "route_reason_codes": ["low_clue_recall"],
  "prefetch_mode": "indexed",
  "context_router_mode": "apply",
  "selected": [
    {
      "heading": "Recall Clarification Guard",
      "source_class": "guard",
      "source_ids": [],
      "chars": 312,
      "score": null,
      "reason_codes": ["required_by_route"]
    }
  ],
  "dropped": [
    {
      "heading": "Working Memory",
      "source_class": "working",
      "count": 3,
      "score": 0.0,
      "reason_codes": ["below_threshold"]
    }
  ],
  "selected_chars_total": 312,
  "dropped_count_total": 3,
  "boundary": {
    "actual_send": false,
    "actual_execute": false,
    "actual_identity_write": false,
    "actual_relationship_write": false,
    "actual_crystallized_approval": false,
    "hindsight_exported": false
  }
}
```

Required fields:

- `schema_version`
- `record_id`
- `created_at`
- `profile`
- `query_class`
- `route`
- `selected`
- `dropped`
- `selected_chars_total`
- `boundary`

Forbidden fields:

- raw user prompt
- raw assistant response
- private message body
- transcript excerpt
- section body
- raw screenshot path
- private file path
- cookies
- tokens
- credentials

## Safe Source IDs

Allowed source ids:

- event id
- working item id
- candidate id
- crystallized record id
- digest id
- reflection card id
- governance feedback id
- proposal id
- foreground task anchor id when one exists
- synthetic guard id such as `guard:recall_clarification`

Forbidden source ids:

- raw file paths
- raw message ids if they can be joined to private body outside Memory-OS
- raw private body hashes
- full transcript hashes
- screenshot paths
- browser profile paths
- cookie/session ids
- provider request ids containing sensitive traces
- secrets or credentials

Rule:

If a source id is not clearly safe, omit it and keep only source class, heading,
chars, score, and reason codes.

## CLI

Initial commands:

```text
hermes memory_os memory-sources last
hermes memory_os memory-sources history --limit 20
hermes memory_os memory-sources stats --hours 24
```

Shell plugin aliases should forward to the same provider CLI:

```text
hermes memory-os-agent-os memory-sources last
hermes memory-os-agent-os memory-sources history --limit 20
hermes memory-os-agent-os memory-sources stats --hours 24
```

Output rules:

- default output is bounded JSON
- no section bodies
- no raw prompts
- include counts, headings, source classes, chars, scores, and reason codes
- `last` reads newest record for the active profile

If no record exists:

- return status `warning`
- code `memory_sources_empty`
- exit code `0` for status/history commands

## Monitor v0.5 Additions

Monitor should collect:

- ledger exists
- latest record timestamp
- record count delta
- file size
- route distribution
- query class distribution
- selected source-class distribution
- dropped reason-code distribution
- average selected chars
- hard-boundary booleans from latest record

Expected WARN:

- ledger absent before RH-29 deployment
- no records yet immediately after install
- source-class skew on early test-host data

FAIL:

- record contains forbidden private fields
- record contains raw prompt/body/section text
- latest boundary boolean is true
- ledger grows without retention/archive metadata after first observation gate

## Retention

Default RH-29 retention:

- keep hot attribution records for 30 days
- archive-before-prune older records
- do not delete canonical Memory-OS data
- do not prune feedback records that reference a retained attribution record
  without first preserving an aggregate link

For the first implementation:

- implement retention policy metadata and monitor reporting
- automatic prune may be a separate RH-29b if needed
- after 24 hours, inspect actual growth before enabling prune

## 24-Hour Test-Host Gate

The first observation gate is 24 hours, not 7 days.

Required evidence:

- Memory Sources ledger exists
- latest record is generated from real live prefetch
- no forbidden fields
- no raw private text
- source classes match selected prefetch headings
- monitor v0.5 reports route/source-class distribution
- `crystallized_records=0` unless owner explicitly approves a record
- hard-boundary booleans remain false
- file growth is acceptable

Decision after 24 hours:

- if clean: continue to RH-30 design or implement CLI feedback
- if noisy but safe: tune retention/sampling/report shape
- if unsafe: disable attribution writing by config and inspect

## Configuration

Default production-safe config:

```json
{
  "memory_sources": {
    "enabled": false
  }
}
```

Test-host config:

```json
{
  "memory_sources": {
    "enabled": true,
    "mode": "metadata_only",
    "retention_days": 30,
    "record_live_prefetch": true,
    "record_dry_run": false
  }
}
```

Installer behavior:

- `scripts/install_memory_os.sh --production-safe` writes the explicit
  production-safe off config.
- `scripts/install_memory_os.sh --test-host` writes the metadata-only test-host
  config.
- `scripts/install_memory_os_test_host.sh` inherits `--test-host`, so it enables
  RH-29 observation without an extra flag.
- The Python installer exposes `--memory-sources-preset production-safe|test-host`
  for non-interactive deployments.

## Boundaries

RH-29 must preserve:

- no send
- no execute
- no identity write
- no relationship write
- no crystallized approval
- no Hindsight export
- no canonical deletion or rewriting
- no production/Sannai mutation during test-host rollout

## Acceptance Criteria

Local:

- unit tests for record schema
- tests for forbidden field stripping
- tests for safe source id filtering
- tests for CLI last/history/stats
- tests for disabled config
- tests proving prefetch output remains unchanged

Remote:

- deploy to `10.20.3.200`
- enable test-host metadata-only mode
- restart gateway only if provider code path requires it
- trigger at least one real Telegram prefetch
- verify `memory-sources last`
- run monitor v0.5
- update `07-validation-report-10.20.3.200.md`

Remote gate status:

- deployed to `10.20.3.200` through the test-host installer
- `memory_sources` test-host config written to `/root/.hermes/memory-os/config.json`
- user gateway restarted to load provider prefetch code
- synthetic live-prefetch probe created one bounded attribution record
- `hermes memory-os-agent-os memory-sources stats --hours 24` verified through
  the official shell alias
- monitor v0.5 returned expected `WARN` only (`rh26_casual_empty`), with no
  FAIL items
- `boundary_true_count=0`
- `forbidden_field_findings=[]`
- 24-hour growth/shape observation remains open

## Recommendation

Implement RH-29 before RH-30/RH-32/RH-33.

Do not wait 7 days for the first signal. Run a 24-hour gate, then decide from
actual growth and source distribution whether feedback audit can start.
