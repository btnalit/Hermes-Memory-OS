# CW-019 Case Study And Deep Reflection Calibration Notes

Date: 2026-05-21

## Purpose

Record CW-019 as one validated case study for calibrating Deep Reflection.

Deep Reflection is the standard L2 Cognition capability for Memory-OS Agent OS.
CW-019 is not its parent system and not its source of truth. It is a mature
private implementation that provides useful metadata, failure modes, and
engineering constraints for sanity-checking public defaults.

Boundary:

- No private Sannai body text is copied into this document.
- All live data cited here is metadata/counts observed read-only on
  `10.20.2.88`.
- Profile-level enablement is a deployment decision. Current Sannai production
  should keep its private CW-019 system, but the public module is designed
  without Sannai-specific branching.

## Evidence Sources

Local reference documents in the parent Hermes manager workspace:

```text
docs/cowork/cw-019-sannai-cloud-l4-design.md
docs/cowork/cw-019-sannai-cloud-l4-requirements.md
docs/cowork/cw-019-sannai-cloud-l4-tasks.md
docs/cowork/cw-019-sannai-cloud-l4-audit.md
docs/cowork/evolution-observation-20260516.md
docs/cowork/evolution-observation-20260518.md
docs/cowork/evolution-observation-20260520.md
```

Live read-only surfaces:

```text
/vol1/.hermes/state/sannai/quiet_moments.jsonl
/vol1/.hermes/state/sannai/heartbeat_lingering_candidates.jsonl
/vol1/.hermes/state/sannai/lingering_thoughts.json
/vol1/.hermes/hermes-agent/scripts/sannai_cloud_heartbeat_live.py
/vol1/.hermes/hermes-agent/scripts/sannai_cloud_heartbeat_shadow.py
/vol1/.hermes/hermes-agent/scripts/sannai_lingering_state.py
```

## Live Metadata Snapshot

Read-only sample on 2026-05-21:

```json
{
  "quiet_moments": {
    "total": 62,
    "modes": {
      "noop": 32,
      "reflection": 25,
      "error": 5
    },
    "candidate_records_appended_sum": 64,
    "candidate_records_skipped_sum": 44,
    "candidate_records_pressure_blocked_sum": 0,
    "candidate_records_deduped_sum": 0
  },
  "heartbeat_lingering_candidates": {
    "total": 105,
    "statuses": {
      "expired": 72,
      "pressure_blocked": 2,
      "candidate": 30,
      "owner_eligible": 1
    },
    "cw": {
      "CW-019-S4": 33,
      "CW-019-S4b": 72
    },
    "candidate_policy": {
      "s4b": 40,
      "missing_or_legacy": 65
    },
    "with_expiry": 64,
    "with_source_trace": 32,
    "active_reviewable": 30,
    "owner_eligible": 1
  },
  "lingering_thoughts": {
    "active_thoughts": 0
  }
}
```

Interpretation:

- `noop` is common and healthy.
- Reflection produces sparse useful material, not constant output.
- Candidate accumulation was real before S4b; caps and pressure guards were
  necessary.
- Owner eligibility is rare by design and does not imply long-term memory.
- The active lingering surface stayed untouched during S4/S4b.

## Case-Study Runtime Mechanics To Preserve

| Case-study mechanic | Evidence | Deep Reflection default |
| --- | --- | --- |
| `noop` is success | 32/62 quiet records were `noop` | empty injection is success |
| bounded night window | S4/S4b uses 18:00-06:00 Asia/Shanghai | profile-local schedule, disabled by default |
| max 8 calls/window and 12 calls/day | CW-019 S4 requirement | max analysis runs per schedule window |
| max 100k prompt tokens/call | CW-019 S4 requirement | deterministic budget before any LLM call |
| candidate live cap 32 | CW-019 candidate lifecycle | injection candidates capped before selection |
| candidate TTL 7 days | CW-019 candidate lifecycle | analysis artifacts may persist; injection cards use shorter soft TTL |
| per-reflection candidate cap 2 | S4b implementation/tests | max cards generated per run should start at 3 or less |
| per-day candidate cap 10 | S4b implementation/tests | max new injection candidates/day should be capped |
| pressure wording guard | R9 + two retroactively blocked rows | instruction/pressure filters mandatory |
| mechanism-term guard | CW-019 prompt/test guard | mechanism leak filter mandatory |
| source trace fields | S4b source_session_ids, source_platforms, request hash | `source_refs`, `artifact_ref`, `input_hash`, `analysis_hash` |
| owner review is dry-run first | owner review-v1 | spot-check CLI is required before broad enablement |
| foreground injection deferred | S5 disabled | auto injection only on test host after preview gate |

## Public Defaults Calibrated Against Case-Study Data

### Module Defaults

```json
{
  "enabled": false,
  "injection_mode": "disabled",
  "analysis_mode": "deterministic",
  "llm_enabled": false,
  "delivery_mode": "no-send"
}
```

Rationale:

- CW-019 proved background reflection can run safely only after staged gates.
- Standard L2 install should never activate injection by default.

### Injection Defaults

```json
{
  "max_cards": 3,
  "max_chars_total": 900,
  "max_chars_per_card": 320,
  "ttl_hours": 24,
  "ttl_mode": "soft_renew",
  "max_new_cards_per_run": 3,
  "max_new_cards_per_day": 10
}
```

Rationale:

- CW-019 S4b reduced candidate burst from up to 32 to at most 10/day.
- Deep Reflection injects into foreground context, which is stronger than
  candidate-only storage, so injected cards should be fewer than candidate
  backlog capacity.
- 24h soft TTL keeps next-session continuity fresh while allowing renewal only
  after a new reflection cycle revalidates source refs and safety gates.

### Source Policy Defaults

| Source | Public Deep Reflection treatment |
| --- | --- |
| foreground conversation continuity | allowed |
| digest/consolidation | preferred input |
| governance feedback | allowed as state, not instruction |
| evidence scores | support refs only |
| proposal backlog | pending-state summary only |
| cron/session/state metadata | not enough by itself |
| runtime/index/audit diagnostics | excluded from injection cards |
| identity/relationship bodies | not read or rewritten |

## Prompt Generalization Rules

CW-019 prompt text is not copied directly into the public module. The standard
prompt must be profile-neutral.

Keep:

- `noop` as a valid result.
- strict JSON or structured output.
- "do not speak to the owner" boundary.
- "do not mention files, schemas, heartbeat, prompts, or mechanism" boundary.
- semantic skeleton output, not polished user-facing speech.
- bounded source packet, not raw transcripts.

Remove from the standard prompt:

- profile-specific names, private voices, and relationship-specific language.
- owner/companion relationship assumptions.
- treasure, diary, art, or private identity references from any case study.
- CW-019/S4/S5 labels from model-facing text.

Public prompt intent:

```text
Analyze the bounded profile state and produce short internal context cards.
Do not command the foreground model.
Do not send messages.
Do not modify identity or long-term memory.
Return noop if no safe card should be created.
```

## Safety Gate Mapping

| CW-019 guard | Public implementation |
| --- | --- |
| waiting/guilt-pressure guard | owner-pressure and relationship-pressure filter |
| mechanism-term block | mechanism leak filter for injection cards |
| no KPI terms | reject self-worth/importance/rank/intensity language |
| no active lingering write in S4 | working updates disabled until DR-06 |
| no long-term memory write | no crystallized approval path |
| no foreground send | no-send, optional wandering seed only |
| review report is read-only | `preview-current` and `history --days` |
| dry-run before apply | `run-once --dry-run` and `preview-injection` before auto_bounded |

## What To Generalize From The Case Study

Generalize:

- background internal analysis as a separate L2 cognition process
- bounded source packet construction
- append-only/local artifact auditability
- deterministic post-filtering
- card caps, daily caps, TTL, selected/dropped reporting
- noop as healthy
- source trace and hashes
- owner spot-check surface

Do not generalize:

- Sannai persona text
- Sannai private relationship memory
- Sannai-specific owner eligibility queue
- Sannai S5 foreground collaboration semantics
- private CW-005/CW-019 curation paths
- DeepSeek-specific provider assumption as a default requirement

## Calibrated DR Implementation Inputs

DR-01 should start from these known-good constraints:

```text
profile_scope: per-profile
default enabled: false
default injection_mode: disabled
first run mode: dry-run only
first analysis mode: deterministic
first LLM mode: disabled
max cards: 3
max chars total: 900
max chars per card: 320
soft ttl: 24h
max new cards per run: 3
max new cards per day: 10
required source refs: yes
instruction-like filters: mandatory
mechanism leak filters: mandatory
owner-pressure filters: mandatory
preview-current command: mandatory
history --days command: mandatory
```

## DR-00 Checklist

Before DR-01 code:

- [x] `17-deep-reflection-runtime-design.md` frames Deep Reflection as a
      standard L2 capability, not a CW-019 shadow.
- [x] profile-level enable/disable is documented without Sannai-specific
      module branching.
- [x] instruction-like detection layers are documented.
- [x] daily schedule order is digest -> governance feedback -> reflection.
- [x] owner spot-check CLI is documented.
- [x] A/B model behavior validation is documented.
- [x] soft TTL renewal is documented.
- [x] this mapping document is reviewed against live CW-019 metadata.

## Resulting Design Position

CW-019 is evidence that quiet internal analysis can exist without speech,
long-term-memory promotion, identity edits, or active foreground writes.

Deep Reflection standardizes the broader Agent OS capability:

```text
safe, bounded, temporary internal context can enter Memory-OS prefetch
without owner approval, after deterministic gates
```

Everything stronger than that still routes through the existing owner-approved
paths: crystallized memory, identity, relationship memory, send, execute, and
self-modification.
