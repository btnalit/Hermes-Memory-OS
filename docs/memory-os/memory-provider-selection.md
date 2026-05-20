# Hermes Memory-OS Provider 选择与 v0 验证方案

日期：2026-05-20

本文开启一条新的 `memory-os` 工程线，不纳入旧的 cowork 看板、旧 proposal queue 或旧 agenda 体系。父级总方案见 `docs/memory-os/architecture.md`；本文只负责 L1 记忆层的 provider 选型、v0 schema 和验证边界。下一步只允许进入本地代码原型；任何生产环境变更都需要重新明确授权。

## 结论

推荐新建 Hermes memory provider：`memory-os`。

核心判断：

- 不直接把 Hindsight 改造成总记忆系统。
- 不把现有任一 provider 当成五层记忆的唯一真源。
- `memory-os` 自己维护本地、可审计、profile-local 的五层记忆源。
- Hindsight 保留为可选语义索引 / reflect 后端，只接收 owner 审批后的 crystallized memory。
- Holographic 是最适合作为本地 provider 实现参考的现有代码方向，但不能只是改名复用。
- OpenViking 和 ByteRover 的架构思路有参考价值，但不适合作为 v0 核心依赖。

一句话架构：

```text
Hermes provider interface
  -> memory-os provider
     -> $HERMES_HOME/memory-os/ 作为真实源
     -> SQLite 作为索引
     -> audit JSONL 作为审计
     -> optional Hindsight adapter 作为审批后语义索引
```

## 范围

本文件要解决：

- provider 对比和选型。
- 最终 Memory-OS 架构。
- `10.20.3.200` 空白 Hermes 服务器验证计划。
- v0 schema。
- 禁改 `10.20.2.88` 生产环境规则。

本文件不做：

- 不迁移生产记忆。
- 不修改生产 Hindsight、bank、strategy、profile、gateway、cron、mailbox。
- 不在旧看板上开任务。
- 不实现代码原型。
- 不设计完整 inner-drive engine，只给它预留读写接口。

## 依据

当前实现仓库：

- `D:\Hermes agent manager\Hermes-Memory-OS\`

Hermes provider 接口依据以下官方文档复核；旧 Hermes 源码树不再作为本项目实现路径。

联网复核资料：

- Hermes memory provider developer guide: https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin/
- Hermes provider comparison: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers/
- Honcho Hermes memory integration: https://hermes-agent.nousresearch.com/docs/user-guide/features/honcho/
- Hindsight Hermes integration: https://hindsight.vectorize.io/sdks/integrations/hermes
- Holographic technical discussion: https://hindsight.vectorize.io/guides/2026/04/21/guide-hermes-agent-holographic-memory-technical-deep-dive
- OpenViking architecture: https://docs.openviking.ai/en/concepts/01-architecture
- ByteRover Hermes integration: https://docs.byterover.dev/autonomous-agents/hermes

`10.20.2.88` 生产只读快照，采集时间 2026-05-20：

```text
Host: YC-NAS
Hermes memory provider: hindsight
Built-in memory: always active
Hindsight plugin: installed and available
Installed plugins: byterover, hindsight, holographic, honcho, mem0, openviking, retaindb, supermemory
Production repo: /vol1/.hermes/hermes-agent is dirty and behind origin/main
```

以上线上信息只通过只读命令采集，没有修改生产环境。

## Hermes Provider 接口判断

Hermes 已经有合适的接入点，不需要绕过系统另起一套外部守护进程。Memory provider 是 single-select plugin，位置为：

```text
plugins/memory/<name>/
```

`memory-os` v0 需要用到的 provider 生命周期：

| 接口 | v0 用途 |
| --- | --- |
| `initialize(session_id, hermes_home=...)` | 确定当前 profile 的存储根目录。 |
| `get_tool_schemas()` / `handle_tool_call(...)` | 暴露显式记忆工具，例如 status/search/approve。 |
| `system_prompt_block()` | 注入很小的记忆契约说明。 |
| `prefetch(query)` | 每轮对话前注入有预算限制的记忆上下文。 |
| `queue_prefetch(query)` | 预热下一轮检索缓存。 |
| `sync_turn(user, assistant)` | 回合结束后异步写事件摘要。 |
| `on_session_end(messages)` | 会话结束时 flush 和提取候选记忆。 |
| `on_pre_compress(messages)` | 压缩前保留候选摘要，避免上下文丢失。 |
| `on_memory_write(action, target, content)` | 镜像内置记忆写入事件，但不直接改内置文件。 |
| `shutdown()` | 关闭 SQLite、后台线程和 adapter。 |

硬约束：

- 必须使用 `hermes_home`，不能硬编码 `~/.hermes`。
- `is_available()` 不能做网络调用。
- `sync_turn()` 不能阻塞前台对话。
- provider CLI 可以通过 `cli.py` 注册，不需要改 Hermes core。

## Provider 对比

| Provider | 优点 | 对 Memory-OS 的风险 | 结论 |
| --- | --- | --- | --- |
| Hindsight | 生产已在用；支持 recall、retain、reflect；可 cloud/local；知识图谱和综合反思能力强。 | auto-retain / 全回合摄入容易污染真源；schema 不是五层记忆；reflect 不能替代 owner 审批。 | 保留为可选语义索引和 reflect adapter。不要当 Memory-OS 真源。 |
| Holographic | 本地 SQLite；无外部服务；profile-scoped；依赖少；有 trust scoring 和本地检索参考价值。 | 记忆模型不是五层架构；HRR/trust 不是 owner-approval 边界。 | 最适合作为本地 provider 实现参考。不能直接改名。 |
| Honcho | 用户 / 关系建模强；有 session-scoped context 和 peer 隔离；dialectic reasoning 成熟。 | 结论生成太主动，容易模糊身份和关系边界；不够可审计。 | 未来可做 relationship adapter，不做 v0 core。 |
| OpenViking | 文件系统内容 + 独立索引、L0/L1/L2 分层加载、session commit 都很像我们需要的思想。 | 需要额外服务 / runtime；taxonomy 和 Hermes Memory-OS 不一致。 | 作为内容 / 索引分离和渐进检索参考，不做 v0 依赖。 |
| ByteRover | agent-curated tree、后台 curation、pre-compression flush 值得参考。 | 依赖 `brv` CLI 和外部 curation 语义；不是我们的 schema 和审批门禁。 | 参考 `on_pre_compress` 思路，不做 v0 core。 |
| Mem0 | 成熟的 hosted extraction / memory 方案。 | 云依赖、提取不透明、owner-governed 本地真源不强。 | v0 不采用。 |
| RetainDB | 混合检索、memory types、compression 思路有价值。 | 云依赖和产品 schema 较重。 | v0 不采用。 |
| Supermemory | context fencing 和多 container 思路有价值。 | 需要 API key；云依赖；不适合做本地真源。 | v0 不采用。 |

## 最终架构

```text
Hermes active memory provider
  -> plugins/memory/memory-os/

Memory-OS canonical store
  -> $HERMES_HOME/memory-os/
     filesystem records + SQLite index + append-only audit

Optional semantic adapter
  -> Hindsight local/cloud
     only owner-approved crystallized records

Reference ideas
  -> Holographic: local provider / SQLite / small tool surface
  -> OpenViking: content and index separation, progressive loading
  -> ByteRover: pre-compression extraction timing
```

工程理由：

- Hermes provider 生命周期刚好覆盖事件写入、预取、压缩前保存、会话结束总结。
- 五层记忆是产品和治理契约，不是某个检索后端能直接替代的。
- 本地真源便于审计、备份、diff、profile 隔离和 owner 审批。
- Hindsight 很有价值，但更适合作为审批后语义索引，而不是原始流水或工作记忆总账。
- 这条路线不会破坏 `10.20.2.88` 现有 Hindsight 生产状态。

## 层级映射

```text
L4 Expression
  通过 prefetch/system_prompt_block 读取 bounded view。

L3 Decision
  读取 working + crystallized summaries。
  不通过 Memory-OS v0 写 proposal 或 agenda。

L2 Cognition
  Inner-drive engine 写 working memory 和候选 events。
  Governor 可读 audit / crystallized。

L1 Memory
  Memory-OS provider 拥有 events、working、crystallized、relationship views、identity manifest、index、audit。

L0 Infrastructure
  Hermes provider lifecycle、cron、mailbox、gateway、filesystem、SQLite、optional Hindsight adapter。
```

## v0 存储根

根目录使用当前 profile 的 `hermes_home`：

```text
$HERMES_HOME/memory-os/
├── config.json
├── events/
│   └── YYYY-MM/
│       └── YYYY-MM-DD.jsonl
├── working/
│   ├── lingering.json
│   ├── emotional.json
│   ├── curiosity.json
│   └── attention.json
├── crystallized/
│   ├── moments.md
│   ├── insights.md
│   ├── stories.md
│   └── wandering/
├── identity/
│   └── manifest.json
├── relationships/
│   ├── owner.md
│   ├── hermes.md
│   └── peers.md
├── index/
│   └── memory_os.db
└── audit/
    └── write_audit.jsonl
```

说明：

- `identity/manifest.json` 只放指针、checksum、保护状态，不复制身份正文。
- 受保护身份文件继续留在现有受保护位置，由 owner 控制。
- `memory_os.db` 是索引和查询加速器，不是真源。
- `write_audit.jsonl` 记录所有写入、拒绝、审批、adapter 导出。

## v0 Event Schema

每条事件是一行 JSONL：

```json
{
  "schema_version": "memory-os.event.v0",
  "id": "evt_20260520_132937_01H...",
  "ts": "2026-05-20T13:29:37+08:00",
  "profile": "sannai",
  "source": "telegram|mailbox|cron|wandering|inner_drive|manual",
  "kind": "conversation_turn|system_observation|memory_write|reflection|wandering_output",
  "summary": "Short safe summary for retrieval.",
  "safe_ref": {
    "session_id": "optional-session-id",
    "message_ids": ["optional"],
    "path": "optional-relative-safe-path"
  },
  "tags": ["memory-os", "owner-approved-candidate"],
  "sensitivity": "public|private|sensitive|secret",
  "body_policy": "summary_only|redacted|full_local",
  "hashes": {
    "body_sha256": "optional"
  },
  "promotion_state": "raw|working|candidate|approved|rejected|expired"
}
```

默认规则：

- `sync_turn()` 只写 `summary_only` 事件。
- v0 默认不保存完整原始对话。
- 若未来需要 full local capture，必须是 profile-local config 的显式开关，且仍不得导出到 Hindsight。

## v0 Working Memory Schema

`working/*.json` 统一结构：

```json
{
  "schema_version": "memory-os.working.v0",
  "updated_at": "2026-05-20T13:30:00+08:00",
  "items": []
}
```

单个 item：

```json
{
  "id": "wrk_01H...",
  "kind": "lingering|emotional|curiosity|attention",
  "status": "active|settled|expired",
  "created_at": "2026-05-20T13:30:00+08:00",
  "updated_at": "2026-05-20T13:30:00+08:00",
  "expires_at": "2026-05-27T13:30:00+08:00",
  "source_event_id": "evt_20260520_132937_01H...",
  "text": "Bounded working-memory statement.",
  "tags": ["owner", "memory-os"],
  "weight": 0.65,
  "decay": {
    "half_life_hours": 72,
    "last_decay_at": "2026-05-20T13:30:00+08:00"
  }
}
```

边界：

- `weight` 只代表 working memory 的显著性，不代表任务价值评分。
- 三奶 companion 表达不使用 ops/proposal 评分语言。
- 治理评分如果需要，必须放在独立命名空间，不能混入 companion working memory。

## v0 Crystallized Memory Schema

crystallized memory 用 Markdown + frontmatter：

```markdown
---
schema_version: memory-os.crystallized.v0
id: cry_01H...
kind: moment
created_at: 2026-05-20T13:40:00+08:00
approved_by: owner
approved_at: 2026-05-20T13:45:00+08:00
source_event_ids:
  - evt_20260520_132937_01H...
tags:
  - memory-os
sensitivity: private
hindsight_indexed: false
---

Agent-rewritten memory text goes here.
```

规则：

- 写入 crystallized memory 必须经过 owner 审批。
- 审批后由 agent 用自己的语言重写，而不是机械复制原始事件。
- 只有审批后的 crystallized record 才允许导出给 Hindsight adapter。
- 导出后必须写 `hindsight_indexed: true` 和 audit 记录。
- Wandering Mind 可以写 `crystallized/wandering/`，但不能写 proposal、agenda 或任务报告。

## Identity 与 Relationship

Identity memory：

- `identity/manifest.json` 只存指针、hash、保护状态。
- provider 不能自动修改受保护身份文件。
- 身份更新是 owner 手动动作，不是 v0 自动记忆写入。
- 任何身份变更都要先通过单独审批。

Relationship memory：

- `relationships/*.md` 可以由 agent 维护，但必须在限定文件内。
- 关系更新必须引用 source event id。
- relationship memory 不能推导或覆盖 identity memory。
- 前台对话只读取 bounded relationship summary，不读取完整 private event stream。

## 读写规则

默认写入：

| Hook | v0 行为 |
| --- | --- |
| `sync_turn(user, assistant)` | 异步追加安全 event envelope；默认无完整 transcript。 |
| `on_pre_compress(messages)` | 压缩前提取候选摘要。 |
| `on_session_end(messages)` | flush pending event summary 和 working-memory candidate。 |
| `on_memory_write(action, target, content)` | 只镜像允许的 built-in memory write 为事件，不回写内置文件。 |
| explicit tool call | 暴露 `memory_os_remember`、`memory_os_search`、`memory_os_status`、approval helper。 |

默认读取：

| 调用方 | 读取范围 |
| --- | --- |
| 前台对话 | working summaries + relationships + 最近已审批 crystallized entries。 |
| reflection / inner-drive | 最近 events + working memory。 |
| Wandering Mind | 最近一周 event summaries + crystallized + working summaries。 |
| identity-sensitive flow | identity manifest + approved crystallized entries。 |

## 生产禁改规则

`10.20.2.88` 是生产环境。本阶段只允许只读观察。

允许：

- `hermes memory`
- `hermes config get ...`
- `systemctl --user status ...`
- 有限行数的 `journalctl` 读取
- `git status`、`git log`、`git diff --stat`
- `ls`、`stat`、`find` 元数据读取
- 读取非 secret 的代码和文档

禁止，除非重新得到明确授权：

- `hermes memory setup`
- `hermes config set`
- 编辑 `/vol1/.hermes/**`
- restart / stop / start 任何生产服务
- 安装包或升级依赖
- `git pull`、`git reset`、`git checkout`、`git clean`
- 修改 Hindsight bank、strategy、API URL、local daemon mode、retention policy
- `chattr`、`chmod`、`chown`、`rm`、`mv` 或写入式 `cp`
- 把 secret、API key、session body、private prompt、原始对话全文写入文档或回复

如果 schema 设计确实需要生产样本，只能采集 metadata 或脱敏摘要，并记录使用的只读命令。

## 10.20.3.200 空白机验证计划

目标：在全新 Hermes 服务器上验证 Memory-OS，不触碰生产。

### Phase A：空白基线

1. 确认 `10.20.3.200` 没有复制 `10.20.2.88` 的 `/vol1/.hermes` 状态。
2. 安装用于原型验证的 Hermes source baseline。
3. 创建测试 profile，例如 `memoryos-test`。
4. 运行 `hermes memory`，确认没有生产 credential，没有生产 bank。

### Phase B：本地 provider 安装

1. 从本地 prototype 安装 `plugins/memory/memory-os/`。
2. 跑 provider unit tests 和 Hermes memory-provider E2E tests。
3. 只在测试 profile 设置 `memory.provider: memory-os`。
4. 运行 `hermes memory` 和 `hermes memory-os status`。
5. 确认 `$HERMES_HOME/memory-os/` 只在测试 profile 下生成。

### Phase C：行为验证

1. 通过 CLI 和 gateway 路径发送 synthetic conversations。
2. 确认 `events/YYYY-MM/YYYY-MM-DD.jsonl` 写入安全 event envelope。
3. 确认默认不保存原始全文 transcript。
4. 确认 `prefetch(query)` 在预算内返回 bounded context。
5. 确认 `on_pre_compress(messages)` 能写候选摘要。
6. 用 fake clock 验证 working memory decay。
7. 确认 crystallized write 需要 approval marker。
8. 确认 Wandering Mind 可读 summary，但不会写 proposal 或 agenda。

### Phase D：可选 Hindsight adapter 验证

1. Hermes active provider 仍保持 `memory-os`。
2. Hindsight 只配置在 Memory-OS adapter config 内。
3. 导出一条 owner-approved crystallized record。
4. 确认 Hindsight recall 能查到该记录。
5. 确认未审批 events 和 working-memory drafts 不会导出。
6. 关闭或破坏 Hindsight adapter 配置，确认 Memory-OS 本地功能仍可用。

### Phase E：故障验证

1. malformed JSONL 行会被隔离，不导致 provider 崩溃。
2. SQLite index 缺失时可从 filesystem records 重建。
3. SQLite locked 时退化为 append-only 写入和延迟索引。
4. disk full / permission denied 时 provider 给出 status，不产生半写 corrupt record。
5. Hindsight 不可用时 optional adapter disabled，真源不受影响。
6. prompt budget 超限时按 layer priority 截断 prefetch。

## v0 Prototype 验收标准

代码原型只有满足以下条件才算通过：

- `memory-os` 能作为 Hermes memory provider 激活，不改 Hermes core。
- 所有存储都在 `$HERMES_HOME/memory-os/`，profile-local。
- `sync_turn()` 异步执行，不阻塞前台回复。
- event JSONL、working JSON、crystallized Markdown、audit JSONL、SQLite index 都按预期创建。
- provider status CLI 能显示 root path、schema version、index health、pending adapter exports、last write time。
- Hindsight 是 optional adapter，不能意外成为 canonical store。
- `10.20.2.88` 生产环境保持未修改。

## 初始代码形态

建议原型文件结构：

```text
plugins/memory/memory_os/
├── __init__.py
├── plugin.yaml
├── cli.py
├── README.md
├── store.py
├── schema.py
├── index.py
├── prefetch.py
├── approval.py
├── adapters/
│   └── hindsight.py
└── tests/
```

建议实现顺序：

1. `schema.py` 和 filesystem store。
2. event append 和 audit append。
3. provider lifecycle 和 `memory_os_status`。
4. bounded `prefetch`。
5. working-memory files。
6. crystallized approval helper。
7. optional Hindsight adapter。

## 进入代码前的问题

进入代码原型前建议先确认：

- v0 原型先跑 `memoryos-test`，还是直接面向 `sannai` profile 做本地测试？
- Hindsight export 是 v0 就做，还是 v0.1 等本地真源稳定后再做？
- `identity/manifest.json` v0 只做指针，还是同时记录 owner-approved identity hash？
- 原始 transcript capture 是 v0 完全没有，还是保留一个默认关闭、测试专用的本地选项？
