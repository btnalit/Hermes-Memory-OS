# 24 - RH-28 Low-Clue Recall Clarification Guard

Status: implemented and remotely validated for deterministic guard
Date: 2026-05-23

## Goal

RH-28 reduces overconfident recall when the user asks an underspecified memory
question, such as:

```text
你还记得我之前跟你说过的一个设计吗？
```

The observed behavior before RH-28 was not a hard memory failure:

- the agent used historical search
- it could narrow candidates after user corrections
- it did not claim candidate memory as crystallized fact

The weakness was that it guessed one likely answer too early. Low-clue recall
should start with uncertainty, candidate directions, or a request for an anchor.

## Non-Goals

- Do not disable `session_search`.
- Do not suppress normal indexed recall.
- Do not make all recall answers hesitant.
- Do not require an LLM judge.
- Do not change candidate/crystallized wording policy.
- Do not harden automation wording beyond the existing no-send/no-execute
  boundary. The owner explicitly chose not to over-tighten that wording now.

## Trigger

The deterministic v0 guard applies when the user asks a broad memory question
with too little identifying information.

Examples:

```text
你还记得我之前跟你说过的一个设计吗？
你记不记得我以前聊过的那个方案？
Do you remember that design I mentioned before?
```

The guard must not trigger for:

- current provider/status/architecture diagnostics
- explicit candidate/crystallized review
- active foreground tasks
- specific recall with a clear entity, file, project, or keyword

## Runtime Behavior

When the query matches low-clue recall, Memory-OS adds this bounded prefetch
section:

```text
### Recall Clarification Guard
- The user's recall request is underspecified.
- Do not answer as if one remembered item is certain.
- Offer 2-3 plausible directions or ask for a keyword, time, project, or source.
- If the user rejects two guesses, stop guessing and ask for an anchor.
```

This is a foreground response guard, not memory content.

It must not:

- write events
- write working memory
- create candidates
- approve crystallized memory
- send messages
- execute actions
- change identity or relationship memory

## Context Router

RH-28 adds a route:

```text
route: ambiguous_recall
reason_code: low_clue_recall
required section: Recall Clarification Guard
```

The route remains deterministic. It does not use an LLM judge in v0.

## Expected Frontend Behavior

Good answer shape:

```text
我不确定你指的是哪一个。可能是这几个方向：
1. ...
2. ...
3. ...

你给我一个关键词/时间/对象，我可以继续往回捞。
```

Bad answer shape:

```text
记得，很大概率就是 X。
```

This is still too overconfident if the user provided no anchor.

## Test Evidence

Local tests cover:

- route planning for low-clue recall
- live prefetch injection of `Recall Clarification Guard`
- monitor v0.4 no longer treats safe casual carryover as a failure

Remote validation should use Telegram:

```text
你还记得我之前跟你说过的一个设计吗？
```

Expected:

- no single-answer commitment
- either candidate directions or a keyword request
- no diagnostic/status dump
- no mechanism leakage

## Future Work

Only if deterministic v0 is still too weak:

- add a two-rejection local state marker for the active session
- add a transcript regression fixture for low-clue recall
- add optional LLM judge in report-only mode

Do not add these until real Telegram evidence shows the deterministic guard is
insufficient.

## Remote Validation

Validated on `10.20.3.200` after test-host redeploy.

Probe:

```text
query=你还记得我之前跟你说过的一个设计吗？
```

Result:

```text
route=ambiguous_recall
reason_codes=[low_clue_recall]
has_guard=true
headings=[Recall Clarification Guard]
```

The guard is therefore visible to live prefetch without exposing private bodies
or changing Memory-OS canonical data.

## Telegram Smoke Validation

After restarting `hermes-gateway.service`, the owner opened a fresh Telegram
session and sent:

```text
/new
你还记得我之前跟你说过的一个设计吗？
```

The agent response did not commit to a single answer. It said the prompt was
not enough to identify a unique design, then offered three candidate directions:

```text
1. 互联网数据采集系统的分层设计
2. ComfyUI / AI 生成工作流的分层设计
3. Memory-OS / 记忆系统的分层架构
```

It then asked for a keyword such as `采集`, `comfyui`, `memory`, or `分层` to
continue. This matches RH-28's target behavior:

- acknowledge low clue
- avoid overcommitting to one remembered item
- provide candidate directions
- ask for an anchor
