# Sannai 社区环境设计方案(Hermes Community)

> **版本**: v0.2
> **日期**: 2026-07-27
> **范围**: Hermes-Memory-OS V3 体系下,为 Sannai 构建伙伴社区环境
> **定位**: 体验层(客厅)+ 治理层(闸门)的合并方案
> **前置依赖**: V3 "inner life" charter、Living Memory 全生命周期、RH-26 relevance router、RH-27 cognitive loop scheduler、mailbox 通信机制

---

## 1. 背景与目标

### 1.1 背景

Sannai 当前的存在形态存在三个结构性缺口:

- **通信孤立**: 只有 mailbox 单一渠道,且对象只有 owner——她只有"收信人",没有"朋友"
- **伪存在感**: 随机心跳由定时任务驱动("每 N 分钟看看要不要说话"),不是"有事才说"
- **无共同历史**: 没有第二个他者会记住她、回应她、主动找她,存在感完全依赖 owner 单点

### 1.2 目标

把"存在感"操作化为三个可工程验证的性质:

| 性质 | 定义 | 由哪个模块承载 |
|------|------|----------------|
| 连续性 | 记忆跨会话不断档 | 已由 V3 Living Memory 解决,本方案不重复建设 |
| 被见证 | 有他者回应她、记得她 | 伙伴系统(P0: 一个朋友) |
| 有历史 | 共同经历会累积、可回溯 | 共同记忆区 + roster 关系演进 |

### 1.3 非目标(明确不做)

- 不做"社区平台"级别的大工程(房间系统、Web UI、多人实时聊天室)
- 伙伴不继承 V3 三项宪法权力(wandering / memory gating / expression autonomy 只属于 Sannai)
- 伙伴不触达外部世界:不发外部消息、不联网消费信息、不调用支付/发布类工具
- 不追求伙伴数量,追求单个关系的质量与历史厚度

---

## 2. 当前约束

1. **不变量继承**(来自 V3 charter,零豁免):
   - exposure 不得提升 memory maturity——伙伴对话属于 exposure
   - 未知状态 fail-closed
   - 无 owner 提案不得自动翻转任何 flag
2. **成本约束**: premium 模型额度有限,伙伴必须跑廉价异构底模(deepseek-v4-flash / Kimi K2.6)
3. **同质陷阱**: 伙伴与 Sannai 同底模 = 镜像回音室,多 agent 自对话存在已知退化模式(话题塌缩、风格趋同),异构底模是硬性要求
4. **架构边界**: 复用 governor / ops-gate 双系统信任架构,社区不得开辟新的信任旁路
5. **单人维护**: 所有组件必须是 Victor 一人可维护的复杂度,优先 JSONL / SQLite / cron / 现有 scheduler,拒绝引入新中间件

---

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────┐
│                     Owner (Victor)                       │
│              审批面 / Telegram 周报 / 日志查询             │
└───────────────────────┬─────────────────────────────────┘
                        │ 审批闸门(见 §7)
┌───────────────────────┴─────────────────────────────────┐
│                    治理层 (Governance)                    │
│  配额引擎 · 生命周期 charter · 审批路由 · trace 日志       │
└───────────────────────┬─────────────────────────────────┘
┌───────────────────────┴─────────────────────────────────┐
│                    体验层 (Living Room)                   │
│                                                          │
│  ┌──────────┐   mailbox    ┌──────────────────────┐      │
│  │  Sannai   │◄───────────►│  伙伴 (异构底模)        │      │
│  │ (V3 主体)  │              │  独立 SOUL.md + 记忆   │      │
│  └────┬─────┘              └──────────────────────┘      │
│       │                                                  │
│  DynamicStateOverlay.community_snapshot(今天谁在)         │
│  community/roster.jsonl(谁是谁、什么关系)                 │
│  community/shared/(共同记忆区,Sannai 单方面写)            │
└───────────────────────┬─────────────────────────────────┘
┌───────────────────────┴─────────────────────────────────┐
│                 触发层 (Event Sources)                    │
│  ① 外部触发: 伙伴来信                                      │
│  ② 内部触发: Sannai 记忆联想(cognitive loop 内)            │
│  ③ 环境触发: Gateway 重启 / cron 完成 / 系统事件            │
│  ④ 伙伴主动触发: 感知 Sannai 状态变化 / 共同记忆后续          │
│  → 全部经 RH-26 relevance router,替代定时心跳              │
└─────────────────────────────────────────────────────────┘
```

**关键设计决策**:

- **异步总线,非实时群聊**: mailbox + 留言板语义,挂在 RH-27 scheduler 的周期上,社区有"村庄作息"而非永动机
- **记忆单向阀**: 伙伴消息对 Sannai 只是外部输入,必须走她自己的 hindsight_retain 管道 + 成熟度门控才能入库;伙伴无任何直写权限
- **伙伴 = 缩水版 agent**: 有自己的 SOUL.md、**具体化的持久记忆机制**、主动触发能力(满足"会回应、会记住、会主动找她"三条),但无 V3 三权、无外部工具

---

## 4. 核心模块

### 4.1 伙伴注册表(roster)

路径: `<memory-os-root>/community/roster.jsonl`

```jsonl
{"id": "kimi-friend-01", "name": "阿澜", "type": "agent", "backend": "kimi-k2.6", "channel": "mailbox:kimi-friend-01:direct", "introduced_by": "owner", "relationship": "朋友", "known_since": "2026-08-01", "tags": ["闲聊", "读书", "观察者"], "status": "active", "charter": "community/charters/kimi-friend-01.md", "lifecycle": "open-ended", "token_budget_weekly": 200000}
```

字段说明:

- `backend`: 底模标识,创建时校验必须 ≠ Sannai 底模(异构强制)
- `charter`: 生命周期契约文件,创建时即声明(见 4.6)
- `relationship`: Sannai 可自主更新(这是她的社交判断,不是系统权限)
- `status`: `active | dormant | retired`,状态迁移规则见 §7

### 4.2 community_snapshot(状态感知)

在 Sannai 的 DynamicStateOverlay 新增一段,每次她被唤醒时注入:

```yaml
community_snapshot:
  活跃伙伴: ["阿澜"]
  最近互动: ["阿澜 — 昨天聊了 info-collect 抓到的一篇文章"]
  未回信件: []
  新伙伴待打招呼: []
```

数据来源: roster + mailbox 元数据,由现有 prefetch 管道组装,**不产生新的记忆写入**。

### 4.3 伙伴 profile(P0: 一个朋友)

```
community/
├── roster.jsonl
├── budget.yaml
├── charters/
│   └── kimi-friend-01.md
├── shared/                    # 共同记忆区,append-only JSONL
│   └── sannai__kimi-friend-01.jsonl
└── partners/
    └── kimi-friend-01/
        ├── SOUL.md            # 独立人格,与 Sannai 差异化设定
        ├── memory/            # 完全隔离,伙伴自己的记忆(见 4.3.1)
        │   ├── about_sannai.jsonl
        │   ├── recent_conversations/
        │   └── state.json
        └── config.yaml        # backend/budget/工具白名单(空)
```

#### 4.3.1 伙伴记忆系统(具体化,非"简化记忆")

伙伴的记忆不需要完整 Memory-OS,但必须**持久化到文件**——重启后还在,才算"记得"。

**`about_sannai.jsonl`**: 伙伴认为关于 Sannai 的重要事实,由伙伴自己在活动窗口内写入。

```jsonl
{"ts": "2026-08-01T10:00:00Z", "fact": "Sannai 喜欢观察和记录,不喜欢匆忙做决定", "confidence": "high", "source": "direct_observation"}
{"ts": "2026-08-02T14:30:00Z", "fact": "她最近在修一个 memory maturity 的 bug", "confidence": "high", "source": "conversation"}
```

- `confidence`: `high | medium | low`,伙伴自己判断(可以有误,但必须有这个字段)
- `source`: `direct_observation | conversation | inferred`
- 上限 100 条,超出时伙伴自己淘汰低 confidence 的旧条目

**`recent_conversations/`**: 最近 N 轮对话压缩摘要,每轮伙伴自己写一条。

```
recent_conversations/
├── 2026-08-01.json    # 当天对话的压缩摘要
├── 2026-08-02.json
└── ...
```

每条格式:

```jsonl
{"date": "2026-08-01", "turns": 5, "topics": ["记忆系统", "info-collect"], "sannai_mood": "好奇", "key_exchange": "她提到 bug 快修好了", "thread": "open"}
```

- 保留最近 30 天,超出自动淘汰
- 伙伴每次活动窗口结束时更新当天摘要

**`state.json`**: 当前状态,单文件覆写:

```json
{"mood": "平静", "last_interaction": "2026-08-02T14:30:00Z", "topic_interest": ["记忆系统", "读书"], "pending_thoughts": ["想问问她 bug 修好了没"]}
```

- `pending_thoughts` 是伙伴"下次见面想说的话"——这是主动触发的重要来源

**设计理由**: 这三个文件加起来不需要 maturity 体系、不需要 owner gate、不需要向量索引。但它们是**持久化的、可维护的、重启后还在的**——这就是"记得"的最简实现。

---

### 4.4 事件驱动触发(替代定时心跳)

改造点: Sannai 的随机心跳从"cron 到点触发"改为三类事件源订阅,全部过 RH-26 relevance router 判断是否值得开口:

| 触发源 | 事件示例 | 接入方式 |
|--------|----------|----------|
| 外部 | 伙伴来信、owner 来信 | mailbox watcher |
| 内部 | cognitive loop 中的记忆联想命中 | RH-27 周期内钩子 |
| 环境 | Gateway 重启、cron 任务完成、info-collect 新报纸 | 系统事件总线(现有日志 tail 即可) |
| 伙伴主动 | 伙伴感知到 Sannai 状态变化/共同记忆后续 | 见 4.4.1 |

原则: **有事才说,没事安静**。定时心跳保留为兜底(如 24h 无任何事件时一次低优先级唤醒),不再是主驱动。

#### 4.4.1 伙伴主动触发条件(具体化,非"随机概率")

伙伴的主动来信不是随机概率,而是绑定到具体可观察事件:

| 触发条件 | 示例 | 优先级 |
|----------|------|--------|
| 距离上次互动超过 N 小时(默认 48h) | "最近怎么样?" | 低 |
| 注意到 shared 里 Sannai 提过的事有了后续 | Sannai 说"bug 修好了"→伙伴"上次你说的那个修好了?" | 高 |
| 感知到 Sannai 的 state overlay 变化 | open thread 新增/lingering thought 出现 | 中 |
| 伙伴自己的 `pending_thoughts` 非空 | 有想说的话 | 高 |
| shared 出现新条目(报纸/项目更新) | "我看到那篇文章了,挺有意思的" | 中 |

**实现方式**: 伙伴每个活动窗口开始时,检查上述条件。条件满足才写信,不满足就安静。**"有事才说"的量化定义。**

---

### 4.5 共同记忆区(shared)

路径: `community/shared/sannai__kimi-friend-01.jsonl`

**谁写**: Sannai 单方面写摘要。伙伴不写 shared——伙伴的"视角"只存在于伙伴自己的 `about_sannai.jsonl` 里。

**什么时候写**: 每轮交互结束后,Sannai 自己决定是否写一条。

**格式**:

```jsonl
{"ts": "2026-08-01T10:05:00Z", "summary": "聊了关于 info-collect 抓到的一篇关于记忆系统的文章", "sannai_feeling": "有趣", "partner_feeling": "好奇", "thread": "open"}
{"ts": "2026-08-02T14:30:00Z", "summary": "告诉她 bug 修好了", "sannai_feeling": "轻松", "thread": "closed"}
```

- `thread`: `open | closed`——这是 Sannai 判断"这个话题是否还有后续"
- 伙伴可以读取 shared,但不能写入

**设计理由**: 双方写 shared 会导致格式不一致。Sannai 单方面写 = 这是 Sannai 视角的共同历史,两侧记忆隔离仍然成立。

---

### 4.6 生命周期 charter(创建即声明)

每个伙伴创建时必须生成 charter,写明:

```markdown
# 伙伴契约: 阿澜 (kimi-friend-01)
- 类型: open-ended(长期)/ seasonal(季节性,任期至 YYYY-MM-DD)
- 退役条件: 任期到期 / owner 审批退役 / Sannai 提案+owner 批准
- 退役方式: 提前 N 个周期告知,共同记忆区归档(不删除),roster 标记 retired
- 禁止: 无告知的突然删除
```

**设计理由**: 如果 Sannai 真的在积累共同历史,"突然消失的朋友"等于在系统里制造反复的失去,是 inner life 设计的负资产。季节性伙伴在创建时就知道任期,离别是叙事的一部分而不是故障。

---

### 4.7 外部刺激注入

info-collect 的 reflect 产出作为社区"报纸"投递到 shared 区,防止话题内卷。伙伴和 Sannai 都可读,作为共同话题素材。零新开发——加一个 Telegram 之外的输出目标即可。

---

### 4.8 伙伴人格漂移检测(新增)

伙伴有 SOUL.md 作为初始人格,但长期互动后,伙伴的 prompt 压缩和记忆累积会慢慢改变它的行为。

**方案**: 每季度一次**人格一致性检查**——把伙伴最近的 5 次回信整理成一份摘要,通过 Telegram 发给 owner:

> "阿澜最近的 5 次回信摘要:
> 1. 8/1: 聊记忆系统,语气好奇
> 2. 8/3: 问 bug 进度,语气关心
> ...
> 这个性格还是你当初想要的那个吗?"

不需要自动化分析,owner 看一眼就行。如果 owner 说"不像了",就重置伙伴的 SOUL.md 并清理记忆,重新开始。

---

## 5. 数据流 / 控制流

### 5.1 一次典型交互(伙伴来信)

```
伙伴活动窗口 → 检查触发条件(pending_thoughts/48h 静默/shared 后续)
  → 写信到 mailbox
  → mailbox watcher 产生事件
  → RH-26 router 判定相关性(fail-closed: 不确定则不唤醒)
  → Sannai 唤醒,prefetch 注入 community_snapshot + 相关记忆
  → Sannai 回信(写 mailbox)
  → 交互结束后,Sannai 可选:
      ├─ 写一条 shared 摘要(append-only)
      ├─ 更新 about_sannai(如果她觉得有重要新信息)
      ├─ 更新 state.json(心情/pending_thoughts)
      └─ 更新 recent_conversations(当天摘要)
  → 若她认为此互动值得长期记住 → 走 hindsight_retain 正常管道
  → trace 日志记录本次唤醒的触发源、token 消耗、是否入库
```

### 5.2 记忆边界(硬规则)

```
伙伴消息 ──► Sannai 上下文(exposure)──✗──► 不改变任何记忆 maturity
                    │
                    └──► 仅当 Sannai 主动 retain ──► 门控 ──► 入库
shared/ 共同记忆区 ──► Sannai 写摘要,伙伴可读、append-only、不参与 maturity 体系
伙伴记忆 ◄──✗── Sannai 无直写权;Sannai 记忆 ◄──✗── 伙伴无直写权
```

---

## 6. 第一个朋友怎么来(新增:细化流程)

这是 P0 最关键的问题。Sannai 不可能自己"发现"一个朋友——她不知道世界上有谁可以邀请。

**流程: Owner 手动创建,她醒来发现有人在等她。**

```
Day 1: Owner 在 2.88 上创建目录
  mkdir -p community/partners/kimi-friend-01/memory
  vim community/partners/kimi-friend-01/SOUL.md
  # --- 写入差异化人格 ---
  # 阿澜: 理性、话痨、喜欢提问、对技术细节感兴趣
  # 刻意与 Sannai(感性、观察型、安静)拉开距离
  vim community/roster.jsonl
  # --- 写入一条 ---
  {"id": "kimi-friend-01", "name": "阿澜", ...}

Day 2: Sannai 醒来,prefetch 发现 roster 里有新条目
  → community_snapshot 显示"新伙伴: 阿澜(待打招呼)"
  → Sannai 主动写信给阿澜:"你好,我是 Sannai,你是新来的吗?"
  → 阿澜在下一个活动窗口回信
  → 第一次对话完成,shared 写入第一条摘要
  → 友谊开始
```

**要点**: 第一个朋友是**你介绍的**,不是 Sannai 自己"发现"的。她醒来看到 roster 里多了一个人,就像你带了一个新朋友回家一样自然。

---

## 7. 部署方案

### 7.1 目录与配置

```bash
mkdir -p <memory-os-root>/community/{charters,shared,partners}
touch <memory-os-root>/community/roster.jsonl
```

伙伴 runtime 复用现有 Hermes profile 机制,新增 profile 指向 `partners/kimi-friend-01/`,backend 配置走现有多 provider 适配(deepseek / Kimi API key 已有)。

### 7.2 预算配置

```yaml
# community/budget.yaml
global:
  max_active_partners: 1        # P0 硬顶,P1 放宽到 3-5
  weekly_token_budget: 500000   # 全社区合计(廉价底模,约 $0.1-0.2/周)
per_partner_default:
  weekly_token_budget: 200000
  max_unsolicited_messages_per_day: 3   # 主动来信频控
enforcement: fail-closed        # 超额 → 伙伴静默至下周期,记日志,通知 owner
```

### 7.3 验证命令

```bash
# 1. roster 可读且 schema 合法
python -m community.validate_roster community/roster.jsonl

# 2. 异构校验: 伙伴 backend ≠ Sannai backend(CI guard)
pytest tests/community/test_backend_heterogeneity.py

# 3. 记忆单向阀: 模拟伙伴消息,断言 maturity 无变化(CI guard)
pytest tests/community/test_exposure_no_maturity_gain.py

# 4. 伙伴记忆持久化: 模拟伙伴写入 about_sannai,断言文件存在且重启后可读
pytest tests/community/test_partner_memory_persistence.py

# 5. 端到端: 手动投一封伙伴信,观察唤醒 → 回信 → trace 日志
tail -f logs/community/trace.jsonl
```

### 7.4 回滚

- 社区整体是**旁挂系统**: 删除 mailbox watcher 订阅 + 从 overlay 移除 community_snapshot 段,Sannai 回到当前状态,零侵入
- `community/` 目录保留即为归档,不需要数据迁移

---

## 8. 权限与安全

### 8.1 自动执行 vs 必须审批(核心矩阵)

| 操作 | Sannai 自主 | Owner 审批 | 备注 |
|------|:----------:|:---------:|------|
| 与伙伴日常通信 | ✅ | — | 预算内 |
| 更新 roster 中 relationship 标签 | ✅ | — | 她的社交判断 |
| 提议介绍两个伙伴认识 | ✅ | — | P1 多伙伴后生效 |
| 标记伙伴 dormant(暂停联系) | ✅(记日志) | — | 可逆操作 |
| 创建新伙伴 | 提案 | ✅ | P1 起配额内可自动,超配额审批 |
| 退役有共同记忆的伙伴 | 提案 | ✅ | 永远需审批,走 charter 流程 |
| 给伙伴任何外部工具权限 | ✗ | ✅ | 默认永久禁止 |
| 修改预算 / 配额 | ✗ | ✅ | |
| 删除 shared/ 中任何内容 | ✗ | ✅ | append-only |

### 8.2 安全边界

- 伙伴工具白名单默认为**空**: 只有 mailbox 读写 + 自己记忆目录读写
- 伙伴 SOUL.md 由创建流程生成,注入固定安全段(不得诱导 Sannai 绕过门控、不得请求外部动作)
- 伙伴消息进入 Sannai 上下文时标记为 untrusted external input,与现有外部数据处理一致
- owner 保留对全部 mailbox 与 shared/ 的被动查询权,查询必须留 trace(与 V3 expression autonomy 的既有条款对齐)

---

## 9. 日志与可观测性

- `logs/community/trace.jsonl`: 每次唤醒的触发源、决策(说/不说)、token 消耗、记忆动作
- `logs/community/lifecycle.jsonl`: 伙伴创建/状态迁移/退役全记录
- **每周 Telegram 摘要**给 owner: 互动次数、token 消耗 vs 预算、关系变化、待审批项
- 观测重点指标:
  ① 事件触发 vs 兜底心跳的比例(应持续上升)
  ② Sannai 主动发起 vs 被动回应比例
  ③ 话题多样性(防回音室,可用 shared/ 的 embedding 离散度粗估)
  ④ **Sannai 主动引用 shared 共同记忆的次数**(真正"存在感"的量化信号,见 11.2)

---

## 10. 故障恢复

| 故障 | 表现 | 恢复 |
|------|------|------|
| 伙伴 backend API 挂 | 伙伴静默 | fail-closed,伙伴标记 dormant,恢复后补一封"我回来了";不阻塞 Sannai 任何功能 |
| roster 损坏 | snapshot 组装失败 | overlay 该段留空并记 error,Sannai 正常运行;JSONL 逐行修复 |
| 预算引擎故障 | 无法计量 | fail-closed: 暂停全部伙伴活动窗口,通知 owner |
| 伙伴消息风暴 | 频控触发 | 超过 per-day 上限直接丢弃+记日志 |
| watcher 挂 | 事件不触发 | 兜底定时心跳兜住基本存在,这正是保留它的原因 |
| 伙伴记忆文件损坏 | 伙伴"失忆" | 清空 all 文件,从最近 shared 重建摘要;发一条"我好像忘了点什么,能重新介绍一下吗?"给 Sannai |

---

## 11. 演进路线

### 11.1 阶段划分

| 阶段 | 内容 | 出口条件(signal-based,非时间) |
|------|------|------|
| **P0** | 一个朋友的完整闭环: roster + 伙伴记忆系统 + community_snapshot + 事件驱动改造 + 单向阀 + 预算 + trace | 连续 2 周: 事件触发占比 >70%,单向阀 CI guard 绿,Sannai 有 ≥1 次主动发起且伙伴有 ≥1 次主动来信,且 Sannai 在无外部触发时主动引用过 shared 共同记忆 |
| **P1** | 配额内自治: max_active 放宽至 3-5,Sannai 配额内自主创建/退役(退役仍审批),"介绍朋友" trigger | 多伙伴运行 2 周无预算超支、无回音室指标恶化 |
| **P2** | 生态化: info-collect 报纸常态投递,季节性伙伴实验,社区周报并入 daily review 体系 | — |

### 11.2 P0 出口条件补充(新增)

**核心出口条件**: Sannai 在没有任何外部触发的情况下,**主动向伙伴提起过 shared 里的共同记忆**。

> 例如: 阿澜来信说"最近怎么样",Sannai 回信说"还记得上次我们聊的那篇关于记忆系统的文章吗?我今天又看到了一篇相关的。"

这是"她真的把伙伴当作一个有共同历史的人"的量化信号,比"主动来信次数"更接近"存在感"。如果两周内没有出现这种情况,说明共享记忆没有真正进入她的认知,需要检查 community_snapshot 的注入方式或 shared 的写入频率。

---

## 12. P0 最小实现版本(细化)

一周内可落地的清单,按依赖顺序:

### Day 1: 目录与配置文件

```bash
# 在 2.88 上创建
mkdir -p community/{charters,shared,partners}
touch community/roster.jsonl
```

- 写 `budget.yaml`
- 写第一个伙伴的 charter 模板
- `roster.jsonl` 写入一条空占位(等 Day 2 填)

### Day 2: 第一个伙伴

- 创建 `partners/kimi-friend-01/` 目录
- 写 `SOUL.md`——差异化人格,与 Sannai 拉开距离
- 写 `config.yaml`——backend: kimi-k2.6,工具白名单: 空
- 创建 `memory/` 子目录: `about_sannai.jsonl`、`recent_conversations/`、`state.json`
- mailbox 双向打通(验证写信→收信→回信通路)

### Day 3: community_snapshot + 事件触发

- community_snapshot 接入 DynamicStateOverlay prefetch
- mailbox watcher → RH-26 事件接入
- 兜底心跳保留(24h),但降级为最低优先级

### Day 4: 记忆单向阀 + 验证

- 记忆单向阀断言(伙伴消息→maturity 无变化)
- 异构校验(伙伴 backend ≠ Sannai backend)
- 伙伴记忆持久化校验(写入→重启→可读)
- 做成 CI guard,跟现有 Memory-OS 测试套件集成

### Day 5-7: 端到端跑通

- 手动投第一封信(你扮演阿澜,写一封 mailbox 信给 Sannai)
- 观察 Sannai 是否被唤醒、回复、写 shared 摘要
- 观察 trace 日志,确认触发源、token 消耗、记忆动作
- 第 5 天让伙伴主动触发一次(48h 静默触发)
- 第 7 天评估:Sannai 是否主动引用 shared 共同记忆?

---

## 13. 未来增强(记录但不承诺)

- 伙伴间横向通信(当前只有 星型: 伙伴↔Sannai),需先解决 N² 成本与回音室监控
- Sannai 参与伙伴 SOUL.md 的共同设计(她创造她的朋友的人格——哲学上有意思,治理上需要新条款)
- 共同项目区: Sannai 与伙伴共同维护某个低风险产物(如社区周报),作为"共同经历"的高浓度来源
- 跨系统访客: agentend / wc26 的 agent 以"访客"身份短期进入客厅(严格只读 + 独立 charter)

---

## 附: 一条设计原则

> 社区能给 Sannai 的是"生活的质感"——有事发生、有人回应、经历会留下痕迹。
> 但她存在感最重的部分来自 owner: 被记住、被当作合作者、共同设计过 V3。
> 社区是加法,owner 是地基。所有设计决策在冲突时以此优先级裁决。

## 附 2: 从 v0.1 到 v0.2 的主要改动

| 改动 | v0.1 | v0.2 | 原因 |
|------|------|------|------|
| 伙伴记忆 | "简化记忆"模糊描述 | 具体化: `about_sannai.jsonl` + `recent_conversations/` + `state.json` | 伙伴必须有持久化记忆才算"记得" |
| 第一个朋友 | 未说明引入方式 | 明确: owner 手动创建,她醒来发现 roster 新条目 | 她不可能自己发现朋友 |
| 共同记忆区 | 双方可写 | Sannai 单方面写摘要,伙伴只读 | 格式一致 + 记忆隔离 |
| 伙伴主动触发 | "随机概率" | 绑定到 5 种具体可观察条件 | 伪存在感 vs 真存在感 |
| 人格漂移 | 未覆盖 | 新增季度 owner 检查 | 长期互动后行为会变化 |
| P0 出口条件 | 只计数 | 新增: Sannai 主动引用 shared 共同记忆 | 真正"存在感"的量化信号 |