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
| **default gateway** | ✅ **active**（PID 2257747，自 09:13，555MB） |
| **sannai gateway** | ✅ **active**（PID 2258391，自 09:16，391MB） |
| **dashboard** | ❌ **inactive** |
| Memory-OS monitor dashboard | ✅ 运行中（PID 4457，自 7/19） |
| WhatsApp bridge | ❌ 不可用（localhost:3000 连接失败） |
| sannai systemd timers | ✅ heartbeat + cognitive-loop 仍在运行 |
| Mailbox | ✅ sannai 收件箱 143 封，hermes 收件箱 148 封 |

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

### 调整 1：P0 前置条件 — 先部署新 Memory-OS，再验证 mailbox

Gateway 已经在线，不需要恢复。但 sannai 的 Memory-OS 是旧版，需要先部署 batch 1-5：

```
Day 0: 部署最新 Memory-OS（batch 1-5）到 sannai profile
         → 备份现有 plugin 目录
         → 定向同步本机 repo 到 2.88 的 sannai plugin 目录
         → 验证 import 可导入
         → 不重启 gateway（user-level 重启需要 owner 确认）
         → 验证 mailbox 双向通信
```

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

### Phase 0：部署新 Memory-OS（✅ 已完成）

1. ✅ 备份 sannai 现有 plugin 目录
2. ✅ 定向同步本机 repo 最新代码到 2.88 的 sannai plugin 目录
3. ✅ 验证 `from plugins.memory.memory_os import ...` 可导入
4. ✅ 验证 mailbox 双向通信
5. ✅ 确认 sannai 状态正常

### Phase 1：社区基础设施（✅ 已完成）

1. ✅ `community/` 目录结构 + roster + budget + charter 模板
2. ✅ 社区模块实现（community.py / partner_create / community_shared / community_triggers / community_snapshot）
3. ✅ 标准化部署脚本（deploy_community.py）
4. ✅ 35 个测试全部通过，已推送到 GitHub

### Phase 2：第一个伙伴（✅ 已完成）

1. ✅ 阿澜（alan）注册到 roster，关系：小伙伴
2. ✅ Hermes 注册到 roster，关系：大总管
3. ✅ 第一封信已投递到 Sannai 收件箱
4. ✅ mailbox 通道已配置，allowed_senders 已更新
5. ✅ 阿澜的 channel 已配置，Sannai 可以回信

### Phase 3：观察与迭代（进行中）

1. ⏳ 等待 Sannai 下次心跳处理来信
2. ⏳ 观察事件触发 vs 兜底心跳比例
3. ⏳ 观察 Sannai 是否主动引用 shared 记忆

---

## 实际部署状态（2026-07-27）

| 组件 | 本地 | 2.88 (sannai) |
|------|------|---------------|
| community.py | ✅ | ✅ |
| partner_create.py | ✅ | ✅ |
| community_shared.py | ✅ | ✅ |
| community_triggers.py | ✅ | ✅ |
| community_snapshot.py | ✅ | ✅ |
| deploy_community.py | ✅ | ✅ |
| Roster | 阿澜 + Hermes | 阿澜 + Hermes |
| Budget | — | max_active: 3 |
| Channel dir | — | 含 alan:direct_sannai |
| Mailbox | 阿澜 inbox 就绪 | 阿澜的信已投递 |

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