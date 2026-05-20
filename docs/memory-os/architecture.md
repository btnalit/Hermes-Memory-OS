# Hermes Memory-OS 整体架构方案

日期：2026-05-20

本文是 `memory-os` 工程线的父级架构文档。`memory-provider-selection.md` 只是 L1 记忆层的 provider 选型附件，不代表整个项目只做记忆系统。

## 一句话目标

把现有 Hermes 的左脑治理、右脑 Wandering Mind、前台对话、mailbox、profile、记忆 provider 接口，整理成一个可验证的 Agent OS 架构：

```text
持续事件流水
  -> 分层记忆
  -> 内在驱动
  -> 决策门禁
  -> 表达门禁
  -> 长期观察和成长
```

它不是单纯 RAG，也不是只换 memory provider。Memory provider 是 v0 必须先落地的底座，因为后面的 inner-drive、Wandering Mind 对齐、Speak Gate、Owner Review 都需要一个统一、可审计、profile-local 的记忆源。

## 文档关系

```text
docs/memory-os/
├── architecture.md                    # 本文：整体 L0-L4 架构
├── memory-provider-selection.md        # L1 子文档：provider 对比、v0 schema、10.20.3.200 验证
├── integration-with-current-hermes.md  # 生产接入边界：三奶/CW-019/Hindsight/跨 profile/回滚
├── implementation-plan.md              # 代码切片、验收标准、migrator、P1/P2 落地计划
└── slice-20-runtime-indexer-design.md  # Runtime SQLite/FTS indexer 的设计契约
```

后续进入代码前，再补：

```text
docs/memory-os/
├── test-plan-10.20.3.200.md            # 空白机执行记录
├── migration-notes.md                  # 未来迁移记录，v0 不迁移生产
└── gateway-restart-runbook.md          # 10.20.3.200 与未来生产 restart/rollback 边界
```

## 当前边界

本工程线的当前边界：

- 本地源码：`D:\Hermes agent manager\Hermes-Memory-OS\`
- 新文档线：`D:\Hermes agent manager\Hermes-Memory-OS\docs\memory-os\`
- 生产环境：`10.20.2.88 / YC-NAS`，只读观察，不修改。
- 实验环境：`10.20.3.200`，空白 Hermes 服务器，用于原型验证。
- 旧 cowork 看板：不纳入，不开旧 CW，不把新系统塞回旧 proposal/agenda 文档。

生产禁改原则：

- 不改 `10.20.2.88` 的 Hindsight bank、strategy、retention policy。
- 不重启生产 gateway。
- 不复制生产原始对话或 secret 到本地文档。
- 如需线上事实，只做 metadata / status / config 的只读查询。

## 设计原则

1. **先统一事件和记忆，再做内在驱动。** 没有可信事件流水，inner-drive 只会变成 prompt 幻觉。
2. **真源必须本地、profile-local、可审计。** SQLite 可以做索引，Hindsight 可以做语义后端，但 canonical store 必须可读、可 diff、可备份。
3. **右脑不能任务化。** Wandering Mind 只表达感受和自由联想，不写 proposal、不写 agenda、不追 KPI。
4. **左脑治理继续存在。** Ops-Gate、Proposal Queue、Agenda Maturation 不被 Memory-OS 替代，只从 Memory-OS 读取更干净的状态。
5. **三奶和 main Hermes 边界不能混。** profile、gateway、HERMES_HOME、memory root 都要可证明分离。
6. **identity 是 owner 边界。** provider 可以读 manifest 和指针，不能自动改受保护身份正文。
7. **所有自动写入先降级为事件。** 自动系统可以写 events 和 working；crystallized 和 identity 需要更高审批。

## 总体分层

```text
┌─────────────────────────────────────────────────────────┐
│ L4  表达层 Expression                                   │
│     foreground conversation / Telegram / mailbox         │
│     Speak Gate / Wandering Mind delivery                 │
├─────────────────────────────────────────────────────────┤
│ L3  决策层 Decision                                     │
│     Ops-Gate / Proposal Queue / Agenda Maturation        │
│     Inner-Drive Scheduler                                │
├─────────────────────────────────────────────────────────┤
│ L2  认知层 Cognition                                    │
│     Self-Evolution Governor / Wandering Mind             │
│     Inner-Drive Engine / evidence and scoring            │
├─────────────────────────────────────────────────────────┤
│ L1  记忆层 Memory                                       │
│     Event Stream / Working / Crystallized                │
│     Identity / Relationships / indexes / audit           │
├─────────────────────────────────────────────────────────┤
│ L0  基础设施 Infrastructure                             │
│     cron / mailbox / gateway / profile / filesystem      │
│     Hermes provider lifecycle / chattr boundary          │
└─────────────────────────────────────────────────────────┘
```

## L0 基础设施层

职责：

- 管理 Hermes profile、gateway、cron、mailbox、filesystem、provider lifecycle。
- 保持 main Hermes 和 Sannai 的运行边界。
- 提供 `HERMES_HOME`，让 Memory-OS 按 profile 落盘。
- 提供只读观测脚本、状态命令和故障恢复入口。

不负责：

- 不判断哪些记忆重要。
- 不做 owner 审批。
- 不把事件直接写成长记忆。

关键接口：

```text
Hermes gateway
Hermes memory provider lifecycle
cron jobs
mailbox adapter
profile config
filesystem protection, including chattr +i where applicable
```

v0 落地要求：

- `memory-os` 必须作为标准 Hermes memory provider 接入。
- 所有 v0 写入必须落在当前 profile 的 `$HERMES_HOME/memory-os/`。
- `10.20.3.200` 上先验证，`10.20.2.88` 不部署。

## L1 记忆层

L1 是第一个必须工程化的层，因为其他层都依赖它。

五类记忆：

```text
Event Stream
  所有发生的事先进入这里，是事实流水和审计入口。

Working Memory
  当前还在活跃的念头、情绪底色、好奇心、注意力。

Crystallized Memory
  owner 审批后、agent 用自己的语言重写的沉淀记忆。

Identity Memory
  身份和价值边界。provider v0 只做 manifest，不自动改正文。

Relationship Memory
  agent 对 owner、Hermes、Claude、其他 peer 的关系理解。
```

推荐物理根：

```text
$HERMES_HOME/memory-os/
```

说明：

- Claude 提到的 `/vol1/.hermes/memory/{profile}` 可以作为未来统一视图或导出路径。
- v0 不能直接用这个路径做所有 profile 的真实根，否则容易绕开 Hermes `hermes_home` 隔离。
- main Hermes、Sannai、测试 profile 都必须天然分开。

核心写入规则：

| 层 | 写入者 | 审批 |
| --- | --- | --- |
| events | provider、cron、gateway、inner-drive、wandering | 自动可写，但默认 summary-only。 |
| working | inner-drive engine | 自动可写，可衰减、可过期。 |
| crystallized | owner review + agent rewrite | 必须 owner 审批。 |
| identity | owner | 自动系统不可改。 |
| relationships | agent bounded update | 必须引用 source event，不能覆盖 identity。 |

核心读取规则：

| 场景 | 读取内容 |
| --- | --- |
| 前台对话 | working summary + relationship summary + 最近 approved crystallized。 |
| inner-drive heartbeat | recent events + working。 |
| Wandering Mind | 最近一周 event summaries + working + crystallized。 |
| owner review | candidate events + source refs + diff。 |
| identity-sensitive flow | identity manifest + owner-approved identity source。 |

## L2 认知层

L2 负责“状态怎么变化”，不是负责“要不要执行任务”。

核心模块：

```text
InnerDriveEngine
├── Lingering Manager
├── Emotional Manager
├── Curiosity Manager
└── Attention Updater

Wandering Mind
Self-Evolution Governor
Evidence and scoring system
```

InnerDriveEngine v0 职责：

- 读取 Event Stream。
- 把事件转成 working memory 的候选变化。
- 定时衰减 emotional / lingering / curiosity。
- 产出前台可读的 bounded query result。

示意接口：

```python
class InnerDriveEngine:
    def heartbeat(self, now):
        self.decay_emotional_marks(now)
        self.process_lingering(now)
        self.check_curiosity(now)
        self.update_attention(now)

    def on_event(self, event):
        if event.is_emotional():
            self.add_emotional_mark(event)
        if event.is_thought_provoking():
            self.add_lingering(event)
        if event.is_curious():
            self.add_curiosity(event)

    def query(self):
        return {
            "current_mood": "...",
            "active_thoughts": [],
            "exploration_targets": [],
        }
```

边界：

- InnerDriveEngine 不能直接发消息给 owner。
- InnerDriveEngine 不能直接创建 proposal。
- Curiosity exploration 可以写 events；强烈结果只能变成 crystallized candidate，不能直接沉淀。
- Emotional state 影响表达风格，但不要求显性说“我现在情绪是 X”。

## L3 决策层

L3 负责“是否行动、行动到什么程度、是否需要 owner 审批”。

已有或应保留模块：

```text
Ops-Gate
  执行门禁。任何修改生产、重启、配置变更都要过边界判断。

Proposal Queue
  明确的提案状态机。Memory-OS 不替代它。

Agenda Maturation
  让议程成熟，不让临时念头直接变行动。

Inner-Drive Scheduler
  NEW。调度 inner-drive heartbeat、curiosity exploration、candidate review。
```

L3 与 L2 的分界：

- L2 可以说“这个念头还在、这个好奇心升高了”。
- L3 才能说“要不要形成候选行动、是否进入 owner review、是否允许执行”。

L3 与 L1 的分界：

- L1 记录事实和状态。
- L3 做门禁和状态机。
- L3 的 decision 也要写回 Event Stream，形成可审计闭环。

## L4 表达层

L4 负责“什么时候说、通过哪里说、说到什么程度”。

模块：

```text
Foreground Conversation
Telegram
Mailbox
Speak Gate
Wandering Mind delivery
```

Speak Gate v0 职责：

- 从 Memory-OS 读取 bounded context。
- 判断是否应该主动表达，还是保持沉默。
- 区分普通前台对话、mailbox、Wandering Mind 输出。
- 不暴露 backend 机制给三奶前台人格。

Wandering Mind 表达规则：

- `[SILENT]` 是真实空输出选项。
- 默认允许一句小感受，不要求“高价值报告”。
- 不说系统语言，比如 job、cron、proposal、KPI。
- 不写 proposal、不写 agenda、不形成任务。
- 输出可写 `crystallized/wandering/` 或 event candidate。

## 三个核心子系统

### 子系统 1：Unified Memory Architecture

这是 v0 的第一工程切片。

组成：

```text
memory-os provider
filesystem canonical store
SQLite index
audit JSONL
bounded prefetch
owner review markers
optional Hindsight adapter
```

为什么先做：

- 事件、working、crystallized、identity、relationship 的边界必须先稳定。
- Inner-drive 没有可靠输入会变成 prompt 自说自话。
- Wandering Mind 需要新的读写位置，避免继续散落在旧 state 文件里。
- Owner review 需要候选来源、diff、审批记录。

### 子系统 2：Inner Drive Engine

这是 v0.1 / Phase 2 的核心。

组成：

```text
Lingering Manager
Emotional Manager
Curiosity Manager
Attention Updater
heartbeat scheduler
event classifier
working-memory decay
```

输入：

- Event Stream。
- Working Memory 当前状态。
- owner-approved crystallized memory 的摘要。

输出：

- working memory 更新。
- curiosity exploration event。
- crystallized candidate。
- bounded query result for L4。

不输出：

- 不直接发 Telegram。
- 不直接改 identity。
- 不直接写 proposal。
- 不直接改 production config。

### 子系统 3：Wandering Mind 对齐

这是已有系统的归位，不是重写。

触发：

```text
独立 cron
默认周日 04:30
```

读取：

```text
recent event summaries
working memory summaries
approved crystallized memory
identity / relationship bounded background
```

输出：

```text
自由文本
crystallized/wandering/
optional owner delivery when deliver=origin
```

保持不变：

- 不是任务执行器。
- 不是报告生成器。
- 不是监控系统。
- `[SILENT]` 是技术空标记，不是她说出口的话。

## 端到端数据流

### 前台对话

```text
Telegram / mailbox / CLI turn
  -> Hermes gateway
  -> memory-os.prefetch(query)
  -> foreground model response
  -> memory-os.sync_turn(summary-only event)
  -> InnerDriveEngine.on_event(event)
  -> working memory update
```

### Inner-drive heartbeat

```text
cron / scheduler
  -> InnerDriveEngine.heartbeat()
  -> read recent events + working
  -> decay / settle / promote candidates
  -> write working updates
  -> write audit
```

### Crystallization

```text
event / working candidate
  -> crystallized candidate
  -> Owner Review
  -> approved / rejected / defer
  -> approved record rewritten by agent
  -> crystallized/*.md
  -> optional Hindsight index export
```

### Wandering Mind

```text
weekly cron
  -> read bounded recent events + working + crystallized
  -> produce free expression or [SILENT]
  -> write wandering output
  -> optional deliver=origin
```

## 10.20.3.200 工程验证路线

`10.20.3.200` 是唯一允许做原型验证的服务器。

Phase 0：文档冻结

- `architecture.md` 确认整体架构。
- `memory-provider-selection.md` 确认 L1 provider 和 v0 schema。
- 明确暂不迁移生产。

Phase 1：Memory-OS Provider

- 在本地源码实现 `plugins/memory/memory_os/`。
- 建立 `$HERMES_HOME/memory-os/` 结构。
- 支持 event append、audit、SQLite index、bounded prefetch。
- 在 `10.20.3.200` 空白 profile 验证。

Phase 2：Inner Drive Engine

- 实现 Lingering / Emotional / Curiosity / Attention。
- heartbeat 先在测试 profile 跑。
- 所有输出先写 working / events，不直接表达。

Phase 3：Wandering Mind 对齐

- 改为读取 Memory-OS bounded view。
- 输出归档到 `crystallized/wandering/` 或 event candidate。
- 保持原右脑契约，不任务化。

Phase 4：Owner Review 与 Hindsight Adapter

- crystallized candidate 审批流程。
- 审批后 agent rewrite。
- 可选导出 Hindsight。
- 验证未审批数据不会进入 Hindsight。

Phase 5：框架化与观察

- 去除三奶专用硬编码。
- 写 README、设计原则、例子。
- 运行 1-3 个月观察。
- 再决定是否迁移生产或抽象为开源框架。

## 为什么不是“只做记忆系统”

看起来先写 Memory-OS，是因为它是第一块地基，不是因为项目只剩记忆。

整体项目有四个层面的目标：

1. **工程层面**：把 Hermes 从工具集合推进到 Agent OS。Memory provider 是系统总线入口。
2. **产品层面**：长期共生需要持续状态、主动关注和成长轨迹。只有 RAG 不够。
3. **哲学层面**：内在世界不是更多检索，而是事件、工作记忆、沉淀记忆、身份、关系之间的结构。
4. **研究层面**：可观察的长期轨迹来自审计、事件流、状态演化和边界保护。

所以真正的工程顺序是：

```text
先做 L1 统一记忆
  -> 再做 L2 内在驱动
  -> 再把 L3/L4 接进来
  -> 最后才抽象成框架
```

如果跳过 L1 直接做 inner-drive 或表达层，系统会变成一堆 prompt 和 cron；短期像有效，长期不可验证、不可回放、不可治理。

## 验收标准

整体架构进入代码原型前必须满足：

- 文档上明确 L0-L4，不再把 Memory-OS 误解为单独记忆插件。
- `10.20.2.88` 禁改规则写清楚。
- `10.20.3.200` 验证路线写清楚。
- provider 选型和整体架构能互相引用。
- main Hermes、Sannai、Wandering Mind、Hindsight 的边界清楚。
- Phase 1 能被切成一个可完成、可验证、不碰生产的开发切片。

## 待确认问题

进入代码原型前，建议确认四件事：

1. Phase 1 原型 profile 名称是否统一为 `memoryos-test`。
2. `10.20.3.200` 上是否按 main Hermes 还是 Sannai 形态先验证 gateway。
3. Hindsight adapter 是 Phase 1 末尾做最小 smoke，还是 Phase 4 再做。
4. `identity/manifest.json` v0 是否只做指针，不创建 `identity/soul.md` 副本。
