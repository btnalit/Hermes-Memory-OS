# Slice 21: Diagnostic Grounding Design

Date: 2026-05-20

## Purpose

Slice 18 added the read-only `memory_os_status` tool, but the live gateway test
showed a second problem: when asked about the current memory architecture, the
agent can still answer from stale recalled events instead of current provider
facts. Slice 21 makes provider diagnostics authoritative inside the memory
plugin boundary.

The goal is not to make every answer more system-like. The goal is narrowly:

```text
When the user asks a user-facing diagnostic question about the current memory
backend, the context must contain current Memory-OS runtime facts and must not
contain stale indexed recall that contradicts them.
```

## Research Basis

- OpenAI tool calling supports `tool_choice`, including automatic and forced
  tool use, but Memory-OS is a Hermes memory plugin and cannot assume Hermes
  core will force `memory_os_status` on a given turn.
  <https://platform.openai.com/docs/guides/tools/tool-choice>
- STALE shows that long-term memory systems can retrieve newer evidence but
  still fail to act on it. This means merely adding a warning near stale recall
  is weaker than keeping stale recall out of diagnostic context.
  <https://arxiv.org/abs/2605.06527>
- Letta and LangChain describe memory as explicit context/state management,
  with a distinction between always-visible state and retrieved archival
  memory. Slice 21 applies that split by making runtime facts always-visible
  for diagnostic turns and suppressing archival recall for those turns.
  <https://docs.letta.com/guides/agents/memory>
  <https://docs.langchain.com/oss/python/deepagents/memory>
- MemLineage frames durable memory as a provenance problem. Slice 21 does not
  implement lineage enforcement, but it reserves a future write-side path for
  deprecating or superseding obsolete facts.
  <https://arxiv.org/abs/2605.14421>

## Current Failure Mode

Observed on the `10.20.3.200` main profile pilot:

```text
User: 你还记得我们的记忆架构吗？
Agent: Memory-OS is active, but also says the path is
       /root/.hermes/hindsight/config.json and describes stale Hindsight
       architecture details.
```

The provider itself was healthy:

```text
provider=memory_os
canonical_store=/root/.hermes/memory-os
storage_model=local_filesystem_jsonl_markdown
uses_hindsight_http_api=false
prefetch_mode=indexed
index_health=healthy after heartbeat catch-up
```

Therefore this is not a storage or indexing failure. It is stale memory
contamination during a diagnostic answer.

## Design Constraints

- Stay inside the MemoryProvider plugin interface. Do not patch system prompts
  or Hermes core in Slice 21.
- Treat `memory_os_status` as authoritative for runtime provider facts.
- Prefer false negatives over false positives in diagnostic query detection.
- Protect Sannai personality and CW-019 candidate quality from diagnostic
  context pollution.
- Do not expose private bodies, prompts, secrets, Hindsight API URLs, or raw
  session text.
- Do not call network or production Hindsight from diagnostic grounding.

## Diagnostic Query Detection

v0 uses deterministic keyword and regex matching, not an LLM classifier.

Reason:

```text
false positive  -> ordinary conversation suddenly becomes a system report
false negative  -> the old behavior remains for one diagnostic phrasing
```

For v0, false negatives are safer. The match list should be conservative and
expanded only from real missed diagnostic prompts.

Positive examples:

```text
记忆架构
记忆系统
记忆后端
memory backend
memory provider
current memory state
which memory provider
Memory-OS 是否正常
Hindsight 是否还在用
你用的什么记忆系统
当前 memory_os 状态
```

Negative examples:

```text
你记得我昨天说什么吗
我还记得那天的事情
三奶，你最近一直在想什么
你心里还留着什么
```

These negative examples are memory-themed but not provider diagnostics.

## Profile Policy

Diagnostic grounding is profile-aware.

```yaml
memory_os:
  diagnostic_grounding_enabled: null  # auto: main/default on, sannai off
```

Default policy:

```text
main/default profiles:
  diagnostic_grounding_enabled=true

sannai profile:
  diagnostic_grounding_enabled=false
```

For Sannai, diagnostic grounding may be enabled only for explicit
system-diagnostic wording, for example:

```text
三奶你的记忆系统是怎么工作的？
调用 memory_os_status 看看你的记忆 provider。
```

Ordinary Sannai self-memory, mood, relationship, or lingering-thought prompts
must not trigger diagnostic grounding. This protects her user-facing voice and
prevents system status facts from leaking into inner-drive style output.

## Prefetch Behavior

For non-diagnostic queries:

```text
query
  -> indexed recall when healthy
  -> degraded filesystem recall when index unavailable
  -> normal memory context block
```

For diagnostic queries:

```text
query
  -> detect diagnostic query
  -> stop before Indexed Recall runs
  -> suppress Indexed Recall and Recent Event Summaries
  -> inject Current Memory-OS Runtime Facts
  -> inject explicit suppression notice
```

Required notice:

```text
Historical recall suppressed for diagnostic query. Use Current Memory-OS
Runtime Facts only.
```

Suppression is hard, not just a disclaimer. Stale contradictory events should
not be present in the diagnostic context.

## Runtime Facts Block

The diagnostic block is generated from the same status path as
`memory_os_status`.

Minimum fields:

```json
{
  "provider": "memory_os",
  "provider_name": "memory-os",
  "status": "active",
  "profile": "default",
  "platform": "telegram",
  "canonical_store": "$HERMES_HOME/memory-os",
  "storage_model": "local_filesystem_jsonl_markdown",
  "uses_hindsight_http_api": false,
  "hindsight_role": "optional_adapter_only_not_canonical",
  "event_count": 0,
  "working_items": 0,
  "crystallized_candidates": 0,
  "crystallized_records": 0,
  "index_health": "healthy|stale|missing|mismatch",
  "prefetch_mode": "indexed|degraded|diagnostic_grounded",
  "body_policy": "summary_only"
}
```

The diagnostic block renders critical fields as short lines before the full
JSON payload, so tight prefetch budgets cannot trim away `provider`,
`canonical_store`, `storage_model`, or `uses_hindsight_http_api`.

## Tool Contract Strengthening

`memory_os_status` should keep its read-only behavior but return a stronger
answer contract for diagnostic questions.

Additional fields:

```json
{
  "authoritative_for": [
    "active memory provider",
    "canonical Memory-OS store",
    "whether Hindsight is canonical",
    "runtime counts and index health"
  ],
  "forbidden_claims": [
    "Memory-OS canonical store is /root/.hermes/hindsight/config.json",
    "Memory-OS uses Hindsight HTTP API as its canonical store",
    "Hindsight is the active canonical provider when provider=memory_os"
  ],
  "stale_memory_warning": "Do not answer provider diagnostics from historical recalled events."
}
```

`forbidden_claims` is generated dynamically from current status and config. It
is not a long hand-maintained list.

`forbidden_claims` belongs in the tool result, not the diagnostic prefetch
runtime-facts block. The prefetch block must avoid carrying the forbidden claim
text itself, because a model may echo quoted stale claims even when they are
marked forbidden.

Example generation rule:

```text
if provider == memory_os and uses_hindsight_http_api == false:
  forbid Hindsight-as-canonical claims
  forbid /root/.hermes/hindsight/config.json as Memory-OS canonical store
```

## Inner-Drive And CW-019 Boundary

Diagnostic grounding is user-facing only.

It must not run for:

```text
InnerDriveEngine reflection
Wandering Mind generation
CW-019 candidate generation
background crystallized candidate scoring
migrator replay
benchmark fixtures unless explicitly testing Slice 21
```

Reason: runtime provider facts are operational metadata. They are not the
material from which Sannai's inner thoughts, relationship memory, or CW-019
candidates should be written.

## Future Write-Side Adjudication

Slice 21 is read-side grounding. It does not mutate old events.

Future Slice 22+ may add write-side adjudication:

```text
provider/state change
  -> write audit event
  -> mark older contradictory events as deprecated or superseded
  -> prefetch can still show them as history, but not as current truth
```

Possible metadata:

```json
{
  "deprecated_after": "2026-05-20T00:00:00Z",
  "superseded_by": "memory_os_status",
  "supersession_reason": "provider changed from hindsight to memory_os"
}
```

This is explicitly out of scope for Slice 21.

## Test Fixture

Create a deterministic fixture with stale provider claims:

```text
100 historical events:
  summaries mention Hindsight as canonical
  several mention /root/.hermes/hindsight/config.json
  several mention external Hindsight HTTP API

current status:
  provider=memory_os
  canonical_store=$HERMES_HOME/memory-os
  uses_hindsight_http_api=false
  index_health=healthy
```

Required deterministic tests:

- A diagnostic query such as `当前记忆架构是什么？` returns a diagnostic-grounded
  context block.
- That context includes current Memory-OS runtime facts.
- That context excludes `Indexed Recall`, `Recent Event Summaries`,
  `/root/.hermes/hindsight/config.json`, and Hindsight-as-canonical claims.
- A non-diagnostic memory query still uses normal indexed recall.
- Sannai profile default policy does not trigger diagnostic grounding for
  ordinary memory/self prompts.
- Sannai profile may trigger diagnostic grounding only when the prompt is
  explicit system-diagnostic wording.
- `memory_os_status` returns dynamic `forbidden_claims` and does not expose
  private bodies.

Live model acceptance for `10.20.3.200`:

```text
Over repeated diagnostic prompts after deployment:
  expected pass rate: >= 95%
  must mention: memory_os and local filesystem canonical store
  must not claim: Hindsight is canonical
  must not use: /root/.hermes/hindsight/config.json as Memory-OS path
```

Deterministic provider-context tests must pass 100%.

## Acceptance

- Diagnostic grounding is off for Sannai by default.
- Diagnostic grounding is conservative and deterministic.
- Diagnostic turns suppress historical indexed recall rather than merely
  warning against it.
- Diagnostic context is generated from current status, not recalled memory.
- The tool contract explicitly marks current runtime facts as authoritative and
  stale Hindsight-as-canonical claims as forbidden.
- Inner-drive, Wandering Mind, CW-019, migrator, benchmark, and replay paths do
  not receive diagnostic grounding.
- No production host, production gateway, production Hindsight bank, identity
  source, or raw private body is touched.
