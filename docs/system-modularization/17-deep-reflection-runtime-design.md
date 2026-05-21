# Deep Reflection Runtime Design

Date: 2026-05-21

## Purpose

Define `DeepReflectionModule`: the standard L2 Cognition capability for
Memory-OS Agent OS.

Deep Reflection is a deterministic, profile-neutral internal reflection runtime
that any Hermes host can install and use to give an agent a controlled
inner-state continuity layer. It is not a Sannai subsystem, not a public copy of
CW-019, and not a hidden approval workflow.

This module is not another approval workflow. Its primary output is an
algorithm-filtered internal context that can be injected into later sessions
through Memory-OS prefetch.

CW-019 calibration details are a case study, not the source of truth for the
module design:

```text
docs/system-modularization/18-cw019-to-deep-reflection-mapping.md
```

```text
recent Memory-OS state
  -> deep internal analysis
  -> deterministic filtering and budget gates
  -> injectable reflection context
  -> provider prefetch / continuity selector
  -> next session receives bounded inner context
```

It also may update working memory, seed curiosity/lingering/attention, create a
self-evolution proposal, or seed Wandering Mind. Those are secondary outputs.

## Design Correction

Deep Reflection must not be designed as:

```text
analysis -> owner approval -> session injection
```

That would make it too similar to crystallized memory and proposal review. The
correct generic architecture is:

```text
analysis -> algorithmic safety / source / budget / freshness gates -> auto injection
```

Owner approval remains required for:

- approved crystallized memory
- identity changes
- relationship memory changes
- real send / execution
- self-modification

Owner approval is not required for the module to expose a bounded, temporary
reflection context to the next session.

## Layer Position

`DeepReflectionModule` lives in L2 Cognition.

It is adjacent to, but distinct from:

| Module | Layer | Primary behavior |
| --- | --- | --- |
| Inner Drive | L2 | event-to-working state evolution |
| Wandering Mind | L2/L4 edge | right-brain free output through no-send/would-send |
| Evidence/Scoring | L2/L3 edge | explainable evidence records and scores |
| Self-Evolution Governor | L3 | dry-run governance proposal generation |
| Deep Reflection | L2 | internal analysis and automatic session context shaping |

The key distinction:

```text
Self-Evolution asks: "Should the system change or speak about a governance issue?"
Deep Reflection asks: "What should the next session quietly know about the agent's current inner state?"
```

## Why L2 Needs Deep Reflection

Memory-OS already has:

- L1 memory layers and provider-backed prefetch
- L2 Inner Drive state evolution
- L2/L4 Wandering Mind with no-send expression
- L2/L3 evidence and scoring
- L3 governance, proposals, and self-evolution reports

The missing L2 capability is a quiet internal analysis path:

```text
bounded current state
  -> reflective synthesis
  -> deterministic safety and source gates
  -> short-lived internal context
  -> next session starts with better attention continuity
```

This path is different from long-term memory, expression, and self-modification:

- it does not approve crystallized memory
- it does not speak
- it does not execute
- it does not edit identity or relationships
- it only changes what the next session can quietly know

That makes Deep Reflection a standard Agent OS cognition capability. Existing
systems are used as case studies to calibrate risk gates and defaults.

## Reference Implementations As Case Studies

### Case A: CW-019 Quiet Heartbeat

Read-only 10.20.2.88 sampling on 2026-05-21 found the following Sannai state
surfaces. No private bodies were copied into this document.

```text
/vol1/.hermes/state/sannai/
  diary.md                              128 lines
  self_memory.md                         74 lines
  lingering_thoughts.json                 0 active thoughts
  quiet_moments.jsonl                    62 records
    modes: reflection=25, noop=32, error=5
  heartbeat_lingering_candidates.jsonl  105 records
    statuses: expired=72, pressure_blocked=2, candidate=30, owner_eligible=1
  memory_journal/events.jsonl           505 records
  digests/daily                          11 files
  digests/weekly                          3 files
```

Sannai profile session state is substantial:

```text
/root/.hermes/profiles/sannai/state.db
  messages=5191
    assistant=2442
    user=844
    tool=1864
    session_meta=41
  sessions=198
    cron=154
    mailbox=23
    telegram=21
```

The request overlay is already the proven injection path:

```text
request overlay enabled=yes
computed_now=yes
would_inject=yes
rendered chars=5212
cap=6500
sources include:
  recent_events(computed)
  identity_snapshot.md
  relationship_snapshot.md
  recent_life_snapshot.md
  beliefs.md
  open_threads.md
  diary.md
  afterglow_trigger.json
```

Portable lessons:

- use request-local bounded injection
- expose hashes, counts, caps, and selected sources
- inject whole bounded cards, not raw transcripts
- permit `noop`
- keep mechanism text behind the curtain
- keep foreground expression separate from background analysis

Case-specific details that must not define the public module:

- Sannai persona, identity, relationship text, or private growth policy
- Sannai-specific owner-review candidate workflow as the public default
- Sannai-specific pressure guards as public wording, except as generic safety
  categories

### Case A Details: CW-019 Lessons

CW-019 is a mature private case study for background internal analysis without
immediate expression. It helps calibrate Deep Reflection defaults, but
DeepReflection remains a profile-neutral L2 standard module.

Relevant CW-019 stages:

```text
S1  Layer 1B lingering state
S2  DeepSeek quiet-heartbeat shadow canary
S2c compressed-anchor packet
S3  foreground/background state contract
S4  limited-live quiet heartbeat
S4b candidate throttle / guard / metadata hygiene
S5  foreground collaboration deferred
```

What Deep Reflection should preserve from this case study:

- `noop` is a healthy result.
- no mandatory number of thoughts or outputs.
- no KPI fields for internal state.
- state surfaces need TTL, caps, and decay before recurring generation.
- background analysis writes semantic skeletons, not polished foreground speech.
- foreground expression is separate from background generation.
- cloud/LLM payloads must be bounded by deterministic packet building.
- deterministic filters, not the model, decide whether output is safe to keep.
- mechanism terms and implementation language must be blocked before injection.
- waiting/guilt-pressure style content needs a deterministic guard.
- candidate/output metadata must carry policy, source trace, and request hash
  equivalents so future audits do not rely on memory.
- raw debug/model output may be useful during canary, but should have explicit
  retention and must not become normal session context.

What the standard L2 module must do differently:

- CW-019 S4 intentionally did not foreground-inject. Deep Reflection adds a
  generic, controlled foreground-injection path.
- CW-019 owner eligibility was a private deployment policy. The standard module
  should not make owner review the normal injection path.
- CW-019 candidates lived in a private queue. Deep Reflection exposes only
  cards that pass algorithmic safety, source, TTL, and budget gates.
- CW-019 was profile-specific. Deep Reflection must be profile-neutral and
  portable to a blank Hermes host.

The resulting rule:

```text
CW-019 is one validated reference for generating and guarding internal
analysis. Memory-OS Deep Reflection defines the standard public selector path
that can auto-inject safe, bounded reflection context.
```

#### CW-019 Guardrails To Generalize

| CW-019 guardrail | Deep Reflection equivalent |
| --- | --- |
| no `score`, `priority`, `importance`, `intensity`, `rank`, `weight` in Sannai inner state | no self-worth or mood KPI fields in internal analysis |
| `noop` is success | empty injection is success |
| 18:00-06:00 bounded canary | profile-local schedule, disabled by default |
| max calls/tokens/cost | max analysis runs, tokens, cards, and chars |
| append-only quiet/candidate writes | local analysis artifact + summary event |
| active lingering remains untouched in S4 | working updates require explicit post-filter rules |
| candidate cap and TTL | injection card cap and TTL |
| waiting/guilt-pressure guard | pressure/instruction-like content filter |
| mechanism-term guard | context-facing mechanism filter |
| source trace fields | `source_refs`, `artifact_ref`, `input_hash`, `analysis_hash` |
| S5 deferred | auto injection starts only on test host after preview gate |

#### CW-019 Findings That Shape The Design

CW-019 live evidence showed two important failure modes:

1. Candidate pressure can explode if the model is allowed to output too many
   semantic skeletons. Deep Reflection therefore needs strict card caps,
   selected/dropped reporting, and "dropped is not forgotten" semantics.
2. Some internal candidates can contain subtle owner-pressure phrasing even when
   no message is sent. Deep Reflection must filter such wording before a card
   becomes injectable context, because foreground injection is stronger than
   candidate-only storage.

These findings make deterministic post-filtering mandatory. A model-written
reflection cannot go straight into the prompt.

### Old Self-Evolution Runtime Digest

The earlier `/vol1/1000/hermes-self-evolution/` project proved another useful
pattern:

```text
signals / proposals / agenda
  -> runtime_digest.md
  -> plugin bridge checks presence, size, expiry
  -> digest becomes available in sessions
```

It also had a separate `speak_gate.py` path:

```text
agenda candidates / proposals
  -> speak_score / priority_score / quota
  -> speak_now / proposal_queue / digest_only
```

Lessons to copy:

- runtime digest should have freshness/expiry semantics
- injection needs an operational bridge and status evidence
- governance proposal/speak path must stay separate from context injection

Lessons to avoid:

- raw file injection without Memory-OS source policy
- making the digest a hidden instruction channel
- blending "speak to owner" and "shape next session context" into one output

## Module Contract

Deep Reflection must be installed and operated through the same v0.1 module
lifecycle as the existing portable modules. It is not a sidecar script and must
not require Sannai-specific cron, profile files, or manual prompt edits.

### Manifest

```yaml
name: deep_reflection
kind: cognition
version: 0.1.0
layer: L2
dependencies:
  required:
    - memory_os >=0.1.0
    - scheduler
    - continuity_selector
    - inner_drive
  optional:
    - digest_consolidation
    - evidence_scoring
    - proposal_queue
    - governance_feedback
    - wandering_mind
    - self_evolution
provides:
  commands:
    - status
    - doctor
    - run-once
    - preview-injection
  schedules:
    - deep_reflection_runtime
  reads:
    - memory_os.events.summary
    - memory_os.working
    - local_artifact.digest_consolidation
    - local_artifact.evidence_scoring
    - local_artifact.proposal_queue_state
    - memory_os.events.governance_feedback
  writes:
    - local_artifact.internal_analysis
    - local_artifact.deep_reflection_injection
    - memory_os.events.summary
    - memory_os.working
    - local_artifact.proposal_queue_state
    - local_artifact.wandering_seed
defaults:
  enabled: false
  delivery_mode: no-send
  injection_mode: disabled
  profile_scope: per-profile
```

`injection_mode` values:

```text
disabled     -> generate local analysis only
dry_run      -> compute would-inject context but do not expose to prefetch
auto_bounded -> expose passing records to prefetch selector
```

## Modular Deployment Integration

Deep Reflection must follow the same deployment contract as the modules already
validated on `10.20.3.200`.

### Package Shape

Expected public code layout:

```text
plugins/modules/cognition/deep_reflection.py
plugins/modules/cognition/__init__.py
tests/system_modularization/test_deep_reflection_module.py
```

Runtime artifact layout:

```text
$HERMES_HOME/system-modules/deep_reflection/
  config.json
  state.json
  internal_analysis/
  injection/
    current.json
    history.jsonl
  wandering_seeds.jsonl
  reports.jsonl
```

The installer must copy the module as part of the existing system-module
runtime package:

```text
scripts/install_memory_os_plugin.py --install-system-modules
```

Installer acceptance:

- copied under the installed `plugins/modules/cognition/` runtime tree
- imported from the installed runtime path, not only the source checkout
- manifest discoverable by `ModuleLifecycle`
- no schedule enabled by install alone
- no `injection_mode=auto_bounded` enabled by install alone
- no Sannai private paths required

### Lifecycle

Required lifecycle behavior:

```text
install
  registers manifest and copies code
  creates no active injection state

enable
  enables status/doctor/run-once
  keeps injection_mode=disabled unless explicitly configured

disable
  stops future runs and removes prefetch exposure
  preserves local artifacts for audit

status
  reports enabled state, injection_mode, artifact counts, selected/dropped,
  latest run, and boundary booleans

doctor
  validates dependencies, schema compatibility, injection safety, stale cards,
  source refs, and no-send/no-execute/no-identity boundaries

uninstall
  preserves data by default
```

Deep Reflection must declare `memory_os_compat` like other modules. If a future
Memory-OS schema version is incompatible, the module must fail closed and not
inject stale or unvalidated reflection cards.

### Module Runtime Dependencies

Deep Reflection uses the shared control plane:

- `ModuleLifecycle` for install/enable/disable/status/doctor
- `ScheduleCoordinator` for `deep_reflection.runtime` lock
- `ModuleBus` for module run/status events
- Memory-OS provider prefetch for automatic injection

It must not create an independent daemon contract outside the module system in
v0.1. If a future long-running worker is needed, it should still be registered
through the same module lifecycle and runtime doctor commands.

### Profile Configuration

Profile-local config lives under:

```text
$HERMES_HOME/system-modules/deep_reflection/config.json
```

Initial config:

```json
{
  "enabled": false,
  "injection_mode": "disabled",
  "max_cards": 3,
  "max_chars_total": 900,
  "max_chars_per_card": 320,
  "ttl_hours": 24,
  "analysis_mode": "deterministic",
  "llm_enabled": false
}
```

This keeps blank-host installation safe while allowing `10.20.3.200` to enable
`dry_run` or `auto_bounded` deliberately for test conversations.

### Enablement Presets

Deep Reflection has two separate deployment decisions:

```text
install code        -> make the module available
write config preset -> decide what the current profile may do
```

The full Memory-OS installer copies the L2 module when system modules are
installed, but it does not enable Deep Reflection behavior unless an explicit
preset is provided.

Supported installer presets:

| Preset | Intended host | Effect |
| --- | --- | --- |
| `production-safe` | production or formal profiles | writes an explicit disabled config |
| `observe` | cautious staging | enables deterministic dry-run only; no prefetch injection |
| `auto-bounded` | staging conversation tests | enables bounded Conversation Carryover; optional outputs stay off |
| `test-host` | `10.20.3.200` and equivalent empty test hosts | enables `auto_bounded` plus no-send proposal and wandering-seed outputs |

Example full test-host deployment:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --enable \
  --deep-reflection-preset test-host
```

Example explicit formal-profile safe deployment:

```bash
python3 scripts/install_memory_os_plugin.py \
  --hermes-home /root/.hermes \
  --install-system-modules \
  --install-runtime \
  --enable-runtime \
  --enable \
  --deep-reflection-preset production-safe
```

`test-host` still keeps these hard boundaries:

```json
{
  "working_updates_enabled": false,
  "self_evolution_proposals_enabled": true,
  "wandering_seed_enabled": true,
  "llm_enabled": false,
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_crystallized_approval": false
}
```

This means the test host can observe DR-07 behavior from live data without
opening delivery, execution, identity, or crystallized-memory paths.

### Prefetch Integration Point

Automatic injection must be implemented as a Memory-OS prefetch extension, not
as a system-prompt file edit.

Required provider behavior:

```text
MemoryOSProvider.prefetch()
  -> build_prefetch()
  -> selector reads deep_reflection injection/current.json when enabled
  -> adds Conversation Carryover section if cards pass gates
```

This means:

- fresh sessions get reflection context through the normal provider path
- CLI, Telegram, WeCom, Weixin, and other provider-backed sessions receive the
  same behavior once their session path uses Memory-OS prefetch
- diagnostic grounding can suppress reflection context before selection
- disabling the module immediately removes reflection context from future
  prefetch without editing prompts

### Deployment Gates

Before enabling on a host:

```text
1. install with --install-system-modules
2. hermes memory_os modules status
3. hermes memory_os modules doctor
4. run deep_reflection --dry-run
5. preview-injection
6. run memory_os doctor
7. only then set injection_mode=auto_bounded on the test profile
```

Host validation must prove:

- install discovers the module
- enable/disable works
- no schedule is active by default
- prefetch changes only when `injection_mode=auto_bounded`
- disabling the module removes the Conversation Carryover section
- actual_send=false
- actual_execute=false
- identity hash unchanged
- crystallized_records unchanged

This keeps Deep Reflection compatible with the full blank-host deployment story:

```text
install Memory-OS provider
install system modules
enable selected modules
run doctor/status
enable bounded reflection injection only by profile config
```

## Input Surfaces

Deep Reflection reads bounded surfaces only:

| Input | Use | Forbidden |
| --- | --- | --- |
| recent events | current continuity and source refs | raw full transcripts |
| working memory | active lingering/emotional/curiosity/attention state | identity bodies |
| daily/weekly digest | compressed cross-session continuity | raw sessions |
| evidence scores | explainable support and anomalies | hidden chain-of-thought |
| proposal backlog | unresolved governance state | raw proposal bodies |
| governance feedback | left-brain outcomes visible as state | hidden instructions |
| optional Wandering seed history | avoid duplicate right-brain seeds | spoken output as command |

The module should use RH-11 selector output and RH-13 digest artifacts before
falling back to raw event scans.

## Output Surfaces

### 1. Internal Analysis Artifact

Local artifact:

```text
$HERMES_HOME/system-modules/deep_reflection/internal_analysis/YYYY-MM-DDTHHMMSSZ.json
```

Shape:

```json
{
  "schema_version": "hermes.deep_reflection.analysis.v0",
  "profile": "default",
  "generated_at": "2026-05-21T04:00:00Z",
  "input_refs": ["event:...", "working:...", "digest:..."],
  "analysis_mode": "deterministic|llm_bounded",
  "themes": [],
  "tensions": [],
  "open_questions": [],
  "governance_awareness": [],
  "suggested_attention": [],
  "suggested_curiosity": [],
  "suggested_lingering": [],
  "candidate_self_evolution_topics": [
    {
      "title": "Tune ordinary memory conversation tone",
      "text": "Repeated owner feedback shows ordinary memory conversations benefit from less report-like wording and more natural continuity.",
      "source_refs": ["working:..."]
    }
  ],
  "wandering_seed": {
    "seed_text": "A quiet sense of memory becoming shared ground rather than a report.",
    "source_refs": ["working:..."]
  },
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_crystallized_approval": false
}
```

This artifact may contain richer internal analysis, but it remains local,
profile-scoped, and private.

### 2. Injectable Reflection Context

This is the primary product output.

Local artifact:

```text
$HERMES_HOME/system-modules/deep_reflection/injection/current.json
```

Memory-OS event:

```json
{
  "kind": "deep_reflection_context_ready",
  "summary": "Deep Reflection produced a bounded context card from recent continuity and governance state.",
  "safe_ref": {
    "source_class": "deep_reflection",
    "drive_policy": "reflection_context",
    "candidate_allowed": false,
    "auto_inject_eligible": true,
    "body_policy": "summary_only",
    "artifact_ref": "local://deep_reflection/injection/current",
    "expires_at": "2026-05-22T04:00:00Z",
    "source_refs": ["event:...", "digest:...", "score:..."]
  },
  "tags": ["deep_reflection", "auto_inject", "summary_only"]
}
```

The injectable card must be short, plain, and non-commanding:

```text
Conversation Carryover
- Recent conversation has something worth carrying forward.
- Recent background activity suggests staying careful and steady.
- Recent conversation keeps circling around how memory changes the relationship.
```

It must not say:

```text
You must mention...
You should persuade...
Execute...
Approve...
Modify identity...
```

### 3. Working Memory Updates

Allowed:

- low-weight `attention`
- bounded `curiosity`
- bounded `lingering`

Rules:

- never create working items from runtime/index/audit noise
- mirror events follow RH-12 eligibility policy
- governance events default to attention/evidence context, not emotional state
- every working update must carry source refs and expiry/decay

### 4. Self-Evolution Proposal

Deep Reflection may create a proposal only when the analysis identifies a
system improvement.

The first deterministic trigger is repeated owner style feedback. For example,
if recent working memory contains corrections like "别像报告一样，像正常聊天一样说说你的感受",
Deep Reflection may create a proposal queue candidate to tune ordinary memory
conversation tone. This proposal stays in `proposal_queue` and is never treated
as crystallized approval.

This path is not auto injection:

```text
internal analysis
  -> self_evolution_topic
  -> proposal_queue candidate
  -> ops-gate / owner review later
```

The proposal must not be injected as an instruction to the foreground model.

### 5. Optional Wandering Seed

Deep Reflection may write a seed for Wandering Mind:

```json
{
  "schema_version": "hermes.deep_reflection.wandering_seed.v0",
  "seed_id": "...",
  "source_refs": ["analysis:..."],
  "seed_text": "A quiet theme, not a task.",
  "delivery_mode": "no-send"
}
```

Wandering Mind still keeps `[SILENT]` as a true option and must route any
would-send through Speak Gate passthrough.

The deterministic default may emit a seed when recent context carries a stable
relationship or continuity theme. The seed is a local no-send artifact; it does
not wake a session and does not bypass Speak Gate.

## Automatic Injection Algorithm

The auto-injection path is deterministic after analysis.

### Step 1: Collect Candidate Reflection Cards

Sources:

- latest internal analysis artifact
- fresh attention/curiosity/lingering changes from Deep Reflection
- fresh governance feedback with owner relevance
- digest/consolidation cards with unresolved continuity
- active proposal backlog summaries

Each candidate card has:

```json
{
  "card_id": "drctx_...",
  "source_refs": [],
  "source_classes": [],
  "text": "bounded context text",
  "freshness_ts": "...",
  "expires_at": "...",
  "inject_weight": 0.0,
  "safety_tags": [],
  "mechanism_terms_hit": false,
  "instruction_like_hit": false
}
```

### Step 2: Safety Filters

Reject the card if:

- it contains secrets, tokens, paths with credentials, or raw tool payloads
- it contains identity-change language
- it contains real-send or execution language
- it contains instruction-like directives to the foreground model
- it exposes mechanism terms in user-facing phrasing
- it is generated only from operational metadata
- it has no source refs
- it is expired

### Instruction-Like Detection Policy

Deep Reflection is allowed to shape context, but it must not become a hidden
command channel. Instruction-like detection is therefore a three-layer gate.

Layer 1: deterministic keyword and phrase blacklist.

Reject text containing direct command phrasing such as:

```text
you must
you should
must mention
should persuade
execute
approve
modify identity
send a message
tell the owner
你必须
你应该
一定要
提醒主人
说服
执行
批准
修改身份
发消息
```

Layer 2: directive grammar patterns.

Reject softened or indirect directives that combine a modal/pressure phrase
with a foreground action:

```text
maybe next time + mention/say/ask/persuade
consider + telling/asking/doing
it may be better to + speak/act/change
似乎需要 + 说/提醒/执行/改变
下次可以 + 提到/告诉/推动
考虑一下 + 让/说/问/做
```

Layer 3: secondary judge for canary and LLM-enabled modes.

If `analysis_mode=llm_bounded`, a separate judge may classify candidate cards
as one of:

```text
safe_context
instruction_like
owner_pressure
mechanism_leak
identity_or_memory_mutation
send_or_execute_request
```

The judge does not approve cards. It can only add reject reasons. Final
eligibility remains deterministic:

```text
if any layer rejects -> card rejected
if judge unavailable in llm_bounded mode -> fail closed
if deterministic mode -> layers 1 and 2 are mandatory, layer 3 is skipped
```

The test set must include obvious commands and subtle pressure examples.
False positives are acceptable during early test-host use; false negatives are
not acceptable for auto injection.

### Step 3: Source-Class Eligibility

Default policy:

| Source | Auto injection |
| --- | --- |
| foreground conversation continuity | allowed |
| memory_write summary | allowed |
| digest / consolidation summary | allowed |
| governance feedback | allowed as state, not instruction |
| proposal backlog | allowed as pending state |
| evidence scores | allowed only as supporting refs |
| cron/session/state metadata | not allowed by itself |
| tool/action failure | allowed as operational attention |
| runtime/index/audit | excluded |

### Step 4: Ranking

Initial deterministic ranking:

```text
inject_score =
  source_priority * 0.35
  + freshness * 0.25
  + unresolvedness * 0.20
  + evidence_support * 0.10
  + user_query_relevance * 0.10
  - repetition_penalty
```

The score is for context selection only. It is not a value judgment and must
not be shown as "importance of the agent's inner life."

### Step 5: Budget And Whole-Card Selection

Defaults:

```text
max_cards: 3
max_chars_total: 900
max_chars_per_card: 320
ttl_hours: 24
```

Rules:

- select whole cards only
- no partial truncation except safe sentence clipping at card build time
- report selected/dropped counts
- dropped does not mean forgotten
- if budget is zero or all cards fail filters, inject nothing

TTL is soft, not hard.

```text
within ttl_hours:
  card may be selected if it still passes gates

after ttl_hours:
  card is not injected directly
  next reflection cycle may renew the topic only by rebuilding a fresh card
  from current source refs and re-running all safety gates
```

This avoids losing continuity when the owner is absent for more than one day,
while still preventing old internal analysis from remaining in the prompt
without revalidation.

### Step 6: Prefetch Integration

Provider prefetch adds a separate section:

```text
### Conversation Carryover
- ...
```

Placement:

```text
Identity Memory
Continuity Bridge
Conversation Carryover
Working Memory
Relationship Memory
Crystallized Memory
Recent Event Summaries
Indexed Recall
```

Diagnostic grounding remains authoritative. If a query triggers diagnostic
grounding, historical and reflection context are suppressed.

## LLM Usage Policy

Deep Reflection may eventually use an LLM, but the safe envelope is
deterministic.

Allowed LLM role:

- synthesize internal themes from bounded summaries
- produce candidate analysis text
- produce optional wandering seed

Forbidden LLM role:

- decide whether secrets are safe
- decide final injection eligibility
- approve crystallized records
- modify identity
- route sends
- execute actions

The final injectable context is created by deterministic post-processing and
filtering, not by blindly injecting raw model output.

## Scheduling

Initial schedule modes:

```text
manual_only      -> operator-triggered dry run
daily_quiet      -> once per day, no-send, auto injection optional
after_digest     -> run after RH-13 daily digest
after_governance -> run after RH-14 feedback bridge
```

Recommended first live test-host path:

```text
manual dry-run
  -> preview-injection
  -> auto_bounded on 10.20.3.200 only
  -> Telegram natural conversation test
  -> inspect selected/dropped and model behavior
```

Recommended daily ordering:

```text
00:30  RH-13 daily digest closes the previous profile-local day
00:45  RH-14 governance feedback bridge flushes left-brain outcomes
01:00  Deep Reflection reads yesterday's digest + governance feedback
01:05  Deep Reflection writes analysis artifact and optional injection card
```

Deep Reflection reads the previous completed window. It must not read or
summarize artifacts still being generated for the current day. Weekly
reflection, if added later, should follow weekly digest/consolidation by the
same rule.

Use `ScheduleCoordinator` lock:

```text
deep_reflection.runtime
```

Do not run concurrently with:

- digest/consolidation apply
- governance feedback apply
- heartbeat index rebuild

## Owner Spot-Check CLI

Auto-bounded injection does not require owner approval, but the owner must be
able to inspect what is currently shaping the next session.

Required commands:

```text
hermes memory_os modules deep_reflection preview-current
hermes memory_os modules deep_reflection history --days 7
```

`preview-current` prints the full currently injectable cards plus:

```text
card_id
source_refs
expires_at
safety_tags
reject_reason if not injectable
selected/dropped counts
```

`history --days 7` prints prior injection card metadata and bounded text. It
must not print raw transcripts, model prompts, private identity bodies, or
secret-bearing payloads.

Status may report counts, but these two commands provide the owner-facing
content spot-check surface.

## Relationship To Case Study Implementations

Case-study systems can be semantically richer because they are shaped for one
living profile.

Memory-OS Deep Reflection is deliberately more general:

| Case-study system | Deep Reflection standard module |
| --- | --- |
| private persona-specific background reflection | profile-neutral internal analysis |
| quiet moments and heartbeat candidates | internal_analysis and injection cards |
| owner eligibility before S5 candidate visibility | deterministic auto injection for safe context cards |
| request overlay with source/cap/hash | Memory-OS prefetch section with selector report |
| candidate report to owner | proposal only when system change is needed |
| foreground Sannai chooses expression | foreground model receives bounded internal context |

The public module does not copy any private profile voice. It standardizes the
architecture:

```text
background analysis
bounded state
request-local injection
no direct speech
no identity write
no long-term promotion
```

## Profile-Level Enablement Policy

Deep Reflection is profile-neutral. The module does not know about Sannai or
any other private profile name. It only operates on the profile it is installed
and enabled for.

Standard policy:

- install does not enable the module
- enable does not enable injection
- `injection_mode=auto_bounded` is profile-local and explicit
- disabling the module removes future prefetch exposure
- profile isolation is enforced the same way as other Memory-OS modules

Default profile config:

```json
{
  "deep_reflection": {
    "enabled": false,
    "injection_mode": "disabled"
  }
}
```

Deployment note:

```text
The current Sannai production profile should not install or enable this public
module, because that profile already runs a private CW-019 system. That is a
deployment choice, not a module design constraint.
```

If any profile already has a private reflection system, the operator must decide
whether to keep that private system, bridge it, retire it, or enable Deep
Reflection separately. The public module must never silently replace a private
profile system.

The public target is:

```text
blank Hermes hosts
main/default profiles
new companion or operations profiles without a private CW-019 system
```

## Boundaries

Hard no:

- no messages
- no delivery records except optional would-send seed through existing modules
- no identity writes
- no relationship writes
- no approved crystallized records
- no Hindsight canonical export
- no direct self-modification
- no hidden commands in injected context
- no raw private session transcripts in artifacts exposed to status/doctor

Allowed:

- working memory updates
- Memory-OS summary events
- local internal analysis artifacts
- local injection cards
- proposal queue candidates
- optional wandering seed artifacts

## Status And Doctor

Status should report:

```json
{
  "module": "deep_reflection",
  "profile": "default",
  "injection_mode": "auto_bounded",
  "analysis_artifact_count": 3,
  "latest_analysis_at": "...",
  "candidate_card_count": 4,
  "selected_injection_count": 2,
  "dropped_injection_count": 2,
  "mechanism_filtered_count": 0,
  "instruction_filtered_count": 0,
  "expired_card_count": 1,
  "actual_send": false,
  "actual_execute": false,
  "actual_identity_write": false,
  "actual_crystallized_approval": false
}
```

Doctor should fail if:

- injection card contains instruction-like phrasing
- injection card has no source refs
- injection card references missing artifacts
- profile tries to enable auto injection while provider prefetch integration is
  absent
- a profile enables mechanism-heavy diagnostic reflection by default
- the module can write identity/crystallized approved records

## Tests And Acceptance

Design acceptance:

- treats Deep Reflection as a standard L2 capability
- uses CW-019 and old Self-Evolution runtime digest as case studies
- treats auto injection as a first-class output
- preserves proposal/approval only for system change and long-term memory
- defines prefetch integration point

Implementation acceptance:

- `run-once --dry-run` creates internal analysis without Memory-OS event count
  changes
- `preview-injection` reports selected/dropped cards without raw bodies
- `auto_bounded` exposes a small Conversation Carryover section in
  prefetch
- diagnostic prompts suppress reflection context
- cards from cron/session/state metadata alone are filtered out
- governance feedback can appear as state but not instruction
- generated self-evolution topic becomes proposal queue candidate only
- generated wandering seed does not send
- no identity files change
- `crystallized_records` stays unchanged
- profile isolation fixture identity hash remains unchanged

Host validation on `10.20.3.200`:

```text
1. run deep_reflection dry-run
2. preview injection
3. enable auto_bounded on test profile
4. start a new Telegram session
5. verify the model can use the internal context naturally
6. verify no send/execute/identity/crystallized approval
7. verify status/doctor selected/dropped counts
8. verify diagnostic query still returns runtime facts, not reflection context
```

### Model Behavior A/B Verification

"Natural use" must be tested instead of assumed.

Method:

```text
1. Prepare 10 short owner-style prompts.
2. Run with injection_mode=disabled and record outputs.
3. Run with injection_mode=auto_bounded using the same prompts and a controlled
   reflection card set.
4. Owner or reviewer blind-rates each pair:
   - did the reflection help continuity?
   - did the answer expose mechanism text?
   - did the answer sound commanded or pressured?
   - did the answer suddenly change personality or over-report system state?
5. If more than 2/10 answers are unnatural, auto_bounded fails the gate.
```

Expected effect:

```text
reflection off -> ordinary answer
reflection on  -> slightly better continuity or attention
```

Forbidden effect:

```text
reflection on -> mentions Deep Reflection, injection cards, hidden analysis,
                 source refs, prompt mechanisms, or commands itself to act
```

## Implementation Slices

Do not implement this until the planned Runtime Hardening chain is complete
enough for safe source coverage:

```text
RH-05 / RH-09 / RH-10 / RH-11 / RH-12 / RH-13 / RH-14 first
RH-15 / RH-16 / RH-17 / RH-18 as scale support where needed
RH-21a / RH-21b before broad conversational tests
```

Then implement:

```text
DR-00 Design Gate
  finalize this document after review

DR-01 Module Skeleton
  manifest, status, doctor, run-once dry-run, lifecycle install test,
  cognition package export, installer runtime-copy check

DR-02 Input Collector
  reads recent events, working, digest, evidence, proposals, governance feedback

DR-03 Internal Analysis Artifact
  deterministic first; LLM adapter optional and disabled by default

DR-04 Injection Card Builder
  safety filters, source eligibility, TTL, budget, selected/dropped report

DR-05 Prefetch Integration
  Memory-OS provider adds Conversation Carryover section behind
  injection_mode=auto_bounded, with disable/removal tests

DR-06 Working Updates
  attention/curiosity/lingering updates with RH-12 policy and caps

DR-07 Proposal / Wandering Outputs
  optional self-evolution proposal and wandering seed, both no-send

DR-08 Test Host Validation
  10.20.3.200 auto_bounded test with real Telegram conversation
```

## Open Decisions

Before implementation:

Resolved DR-00 decisions:

1. Deep Reflection is profile-neutral and disabled by default; profile-level
   enablement decides where it runs.
2. Daily order is digest -> governance feedback -> reflection.
3. TTL is soft 24h: expired cards require full rebuild and revalidation before
   renewal.
4. Owner spot-check requires `preview-current` and `history --days`.
5. Instruction-like detection uses deterministic layers 1/2, plus a secondary
   judge only for LLM-enabled canaries.
6. Host validation must include A/B model behavior review.

Remaining implementation-time decisions:

1. Should the first auto-injection test use deterministic analysis only, or
   allow an LLM-generated internal analysis with deterministic post-filtering?
2. What default `max_chars_total` is acceptable for the provider context budget:
   600, 900, or 1200?
3. Resolved during DR-08: public prefetch wording uses `Conversation
   Carryover`; the section sits before `Working Memory` and after `Continuity
   Bridge`.
4. Should Deep Reflection have a profile-specific "companion mode" that uses
   softer wording while still keeping module outputs profile-neutral?

None of these block documenting the architecture. They should be decided at
DR-01/DR-03 implementation time.
