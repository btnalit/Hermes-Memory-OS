# Hermes Compression Hook Gap And Memory-OS Task Anchor

## Purpose

This document records a foreground task-continuity failure observed on the
10.20.3.200 Hermes test host, the root-cause split between Hermes runtime
compression and Memory-OS adaptation, and the Memory-OS-side mitigation.

The issue is not a long-term memory corruption. Memory-OS can remain healthy
while the active foreground task drifts after Hermes automatic context
compression.

## Observed Failure

A real Telegram/Hermes session ran a long ComfyUI install/download task under a
small-context model configuration. The turn involved multiple tool calls,
background processes, download output, and repeated progress notifications.

After automatic context compaction, the assistant resumed with an unrelated
Memory-OS/Hindsight explanation rather than continuing the active ComfyUI
installation task.

The practical impact was severe: Hermes became unreliable for long-running
workflows in small-context mode.

## Evidence From 10.20.3.200

Read-only source and log inspection found:

- `Compacting context -- summarizing earlier conversation so I can continue`
  is emitted by Hermes runtime code at
  `/usr/local/lib/hermes-agent/run_agent.py`.
- `Preflight compression` is also emitted by Hermes runtime code.
- `Still working...` progress messages are emitted by Hermes gateway code at
  `/usr/local/lib/hermes-agent/gateway/run.py`.
- The observed session log showed automatic preflight compression with no focus:

```text
session=20260521_220646_3c3d23
preflight_tokens=159123
threshold_tokens=136000
model=gpt-5.4-mini
context_length=272000
messages=148
focus=None
```

## Root-Cause Split

```text
not: Codex CLI-only drift
not: canonical Memory-OS data corruption
not: DeepReflection safety failure
not: approved long-term memory drift

primary: Hermes automatic preflight compression lacks an active task focus
secondary: Memory-OS previously had no current task anchor contribution
```

There are two separate facts:

1. Hermes supports a `focus_topic` path for focused compression, but automatic
   preflight compression did not pass a focus topic.
2. Hermes calls `MemoryManager.on_pre_compress(messages)`, and the memory
   provider contract says returned text can preserve important information, but
   the observed `run_agent.py` call path invoked the hook without consuming the
   returned text.

That second point is a Hermes hook implementation gap. A Memory-OS provider can
now return a task anchor, but Hermes must consume the return value for the
anchor to influence the compression summary directly.

## Memory-OS Mitigation

Memory-OS now provides a bounded foreground task anchor:

- `MemoryOSProvider.on_pre_compress(messages)` extracts the latest user task and
  recent tool/process context after that task.
- The anchor is redacted, bounded, and labeled as a foreground task-continuity
  aid.
- The anchor is stored only as provider runtime state, not as approved long-term
  memory.
- `system_prompt_block()` includes the current anchor so a rebuilt system prompt
  after compression can still see it.
- `prefetch()` passes the anchor into the Memory-OS context as the first
  non-diagnostic section: `Current Foreground Task`.

This mitigation helps in two places:

- next-turn prefetch can re-anchor the conversation after drift
- same-turn compression can see the anchor through the rebuilt Memory-OS system
  prompt after `on_pre_compress()` updates provider runtime state

It does not fully replace a Hermes runtime fix because the compression summary
itself still cannot use provider-returned anchor text until Hermes consumes the
hook return value.

## Anchor Lifecycle

RH-25 intentionally uses the simplest lifecycle that preserves foreground
continuity without turning the anchor into memory:

- `on_pre_compress(messages)` rebuilds the anchor from the latest concrete user
  task and the recent tool/process context that follows it.
- `prefetch(query)` may refresh the anchor from a new concrete user query.
- Vague continuation queries do not overwrite the existing anchor. Examples:
  `continue`, `resume`, `继续`, `继续当前任务`, `继续刚才的任务`.
- A different concrete user task can replace the current anchor.
- The anchor is provider runtime state. It is not persisted across provider
  restart and is not written to events, working memory, candidates,
  crystallized records, identity, or relationships.

This means RH-25 favors "do not lose the active job during compaction" over
"remember every prior foreground job." That is deliberate.

## Known Limitation

RH-25 maintains one current foreground anchor, not a task stack.

Example unresolved multi-task case:

```text
1. owner asks: install ComfyUI plugins
2. owner asks: also check Memory-OS doctor
3. owner asks: did the ComfyUI install finish?
```

The current implementation may replace the ComfyUI anchor with the Memory-OS
doctor task when step 2 is concrete enough. A future RH-25.1 could add a
bounded recent-task list or anchor stack, but this is intentionally deferred
until real usage proves the need.

Implementation status:

```text
local tests: 300 passed
10.20.3.200 deployment: installed via install_memory_os_plugin.py
gateway: restarted and active
synthetic task-anchor probe: passed
doctor: ok, warning-only findings
```

Synthetic probe assertions:

```text
prefetch_has_foreground=True
prefetch_preserves_original_task=True
prefetch_preserves_error=True
prompt_has_anchor=True
```

## Boundaries

The task anchor must not:

- become a crystallized record
- write identity or relationship memory
- create working items or candidates by itself
- hide failures, user corrections, or tool errors
- suppress an explicit user topic change
- include secrets, tokens, API keys, passwords, or raw private bodies

It is a foreground continuity aid, not a belief, not long-term memory, and not a
self-modification path.

## Suggested Hermes Upstream Issue

Title:

```text
MemoryProvider.on_pre_compress() return value is collected but not used by automatic context compression
```

Minimal issue body:

```text
Hermes documents MemoryProvider.on_pre_compress(messages) as returning text
that can be included in the compression summary prompt.

MemoryManager.on_pre_compress() also combines provider return values.

However, run_agent._compress_context() calls:

    self._memory_manager.on_pre_compress(messages)

without consuming the returned text. As a result, memory providers cannot
preserve task anchors or provider-extracted context before automatic preflight
compression discards middle turns.

Observed impact:
- long-running Telegram/Gateway task
- automatic preflight compression
- focus=None
- current task drifted after compaction

Suggested fix:
- capture provider_context = self._memory_manager.on_pre_compress(messages)
- feed provider_context into the compression summary prompt, or convert it into
  a focus_topic / compression guidance section
- add a regression test proving provider-returned text appears in the summary
  prompt during automatic preflight compression
```

## Suggested Hermes Enhancement

Automatic preflight compression should have a default focus source. Possible
sources:

1. provider-returned `on_pre_compress()` anchor
2. latest user request
3. latest active tool/process label
4. manual `/compress <focus>` argument when present

Memory-OS recommends using provider-returned anchor text first because it is
deterministic, cheap, and already bounded by the provider.

## Temporary Workaround

Before long-running jobs in small-context mode, the owner can start with an
explicit foreground anchor:

```text
当前任务: ComfyUI 插件安装。
压缩后继续这个任务。
后台进程完成后只汇总: 成功 / 失败 / 重试。
不要切回 Memory-OS / Hindsight 历史话题。
```

This is only a workaround. The Memory-OS anchor and Hermes hook fix are the
durable path.
