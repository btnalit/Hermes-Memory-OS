# Sannai 社区环境设计方案 v0.3 — 环境适配版

> **版本**: v0.3
> **日期**: 2026-07-27
> **基于**: v0.2 + 2026-07-27 实地调研
> **定位**: 针对 YC-NAS (10.20.2.88) 实际环境的优化方案

---

## 环境现状（2026-07-27 实地调研）

### 硬件

| 项 | 值 |
|------|------|
| 主机 | YC-NAS |
| RAM | 3.6 GiB（可用 1.2 GiB） |
| Swap | 1.8 GiB（几乎用满） |
| 根分区 | 6.1G（77% 已用） |
| `/vol1` | 224G（19% 已用，约 181G 可用） |
| 连续运行 | 8 天 |

### 服务状态

| 服务 | 状态 |
|------|------|
| **default gateway** | ❌ **inactive** |
| **sannai gateway** | ❌ **inactive** |
| **dashboard** | ❌ **inactive** |
| Memory-OS monitor dashboard | ✅ 运行中（PID 4457，自 7/19） |
| WhatsApp bridge | ❌ 不可用（localhost:3000 连接失败） |
| sannai systemd timers | ✅ heartbeat + cognitive-loop 仍在运行 |

### Sannai 记忆系统版本

| 项 | 值 |
|------|------|
| Memory-OS 插件数 | 60 个 `.py` 文件 |
| **batch 1-5 新模块** | ❌ **全部缺失**（section_status、continuity、gap_note 等均无） |
| crystallized candidates | 24 条 |
| memory_journal | 1038 条事件卡 |
| treasure_index | ✅ 存在 |
| digests | ✅ daily + weekly |
| state overlay | ✅ identity、beliefs、capability、diary、lingering_thoughts 完整 |
| memory_edges | ❌ 无图谱边 |
| entity_index | ❌ 无实体索引 |
| 源码仓库 HEAD | `2da64e784`（旧版本，非最新优化版） |

### 关键发现

1. **两个 gateway 都 inactive** — mailbox 通信的前提条件不满足，需要先恢复 gateway
2. **Sannai 的 Memory-OS 是旧版** — 60 个文件但全是 batch 1-5 之前的版本
3. **Sannai 的本地 curation 管线完好** — identity、beliefs、diary、journal、treasure、digest 全部在
4. **WhatsApp 挂了** — 社区周报需要走 Telegram
5. **资源紧张** — 3.6GiB 跑两套 gateway + 两套 Memory-OS + 伙伴压力很大

---

## 对 v0.2 设计的优化调整

### 调整 1：P0 前置条件 — 先恢复 gateway，再部署新 Memory-OS

社区依赖 mailbox 通信，mailbox 依赖 gateway。所以 P0 的 Day 0 应该是：

```
Day 0: 恢复 default gateway + sannai gateway
         → 部署最新 Memory-OS（batch 1-5）到 sannai profile
         → 验证 mailbox 双向通信
```

没有 gateway，社区不存在。

### 调整 2：伙伴不跑在 2.88 上，跑在本机（10.20.2.66 或本机）

2.88 只有 3.6GiB RAM，再跑一个异构底模的伙伴 agent 会直接压垮。建议：

- **伙伴的 profile 和 gateway 跑在本机（54GiB RAM 的机器）**
- 伙伴通过 mailbox 跨机通信到 2.88 上的 sannai
- 伙伴的 memory 目录存在本机，不占 2.88 的磁盘

这样 2.88 只需要恢复 sannai gateway + 一个 Memory-OS，不需要额外资源。

### 调整 3：利用 Sannai 现有的 curation 管线，不重复造

v0.2 设计了一个新的 `community_snapshot` 段。但 sannai 已经有：

- `identity_snapshot.md` → 可以在里面加一行 `community: 阿澜(朋友)`
- `lingering_thoughts.json` → 伙伴相关的心事自然出现在这里
- `memory_journal` → 与伙伴的互动可以进入 journal
- `digests/daily/` → 与伙伴的互动自动出现在 daily digest 里

**建议**：不要新建 `community_snapshot` 段，而是把伙伴信息注入她已有的 overlay 字段。她醒来时自然知道"阿澜是谁"。

### 调整 4：伙伴记忆更轻量

2.88 资源紧张，伙伴的记忆系统应该尽可能简单：

- 伙伴的 `about_sannai.jsonl` → 上限从 100 降到 **50 条**
- `recent_conversations/` → 保留从 30 天降到 **14 天**
- 不做向量索引，不做 embedding，纯 JSONL

### 调整 5：部署方式不是 git pull，是定向同步

2.88 上没有 `/opt/Hermes-Memory-OS` 仓库，sannai 的 plugin 目录在 `/vol1/.hermes/profiles/sannai/plugins/memory_os/`。部署方式：

- 从本机 repo 定向同步到 2.88 的 sannai plugin 目录
- 部署前备份现有 plugin 目录
- 部署后验证 `from plugins.memory.memory_os import ...` 可导入
- 不重启 gateway（因为 gateway 当前 inactive，先恢复再看）

### 调整 6：社区周报走 Telegram，不走 WhatsApp

WhatsApp 挂了，社区周报应该通过 Telegram 发送。本机已经有 Telegram 通道，可以直接用 `hermes send` 发到你的 Telegram。

---

## 实际路线图

### Phase 0：恢复基础设施（1-2 天）

1. 恢复 sannai gateway
2. 部署最新 Memory-OS（batch 1-5）到 sannai profile
3. 验证 mailbox 双向通信
4. 确认 sannai 状态正常

### Phase 1：第一个朋友（在本机部署伙伴）

1. 在本机创建伙伴 profile（Kimi K2.6 底模）
2. 配置 mailbox 跨机通信（本机 ↔ 2.88）
3. Sannai 醒来发现 roster 有新人
4. 第一次对话：你好，我是 Sannai

### Phase 2：观察与迭代

1. 观察事件触发 vs 兜底心跳比例
2. 观察 Sannai 是否主动引用 shared 记忆
3. 根据实际情况调整频控和触发条件

---

## 总结

| 对比项 | v0.2（通用设计） | v0.3（环境适配） |
|--------|-----------------|-----------------|
| 伙伴运行位置 | 2.88 上 | **本机（54GiB）**，跨机 mailbox 通信 |
| community_snapshot | 新建 overlay 段 | **注入现有 overlay**（identity_snapshot + lingering_thoughts） |
| 伙伴记忆容量 | 100 条 / 30 天 | **50 条 / 14 天**（资源优化） |
| 部署方式 | git pull | **定向同步**（本机→2.88） |
| 周报通道 | 未指定 | **Telegram**（WhatsApp 不可用） |
| 前置条件 | 无 | **恢复 gateway + 部署新 Memory-OS** |