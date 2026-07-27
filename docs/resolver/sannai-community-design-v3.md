# Sannai 社区环境设计方案 v0.3 — 修订证据版

> **版本**: v0.3-rev3
> **日期**: 2026-07-27
> **基于**: v0.2、2.88 实地核验、社区代码独立审查
> **状态术语**: `designed` / `implemented` / `tested` / `deployed` / `wired` / `live` / `observing`

---

## 1. 边界

社区为 Sannai 提供伙伴关系、共同经历投影和事件候选，不改变她的 identity、relationship、表达自主权或成熟记忆规则。

- Sannai 可以自由选择关系、表达和成长方向。
- 伙伴消息只是 exposure；不得直接提升 memory maturity。
- shared memory 是 Sannai 视角的 append-only 投影，只有 Sannai writer 可写。
- 伙伴使用异构 backend；创建时必须校验。
- 自动周期只产生 no-send 候选；外部发送继续经过现有 Owner/表达治理边界。
- 预算、隔离、审计与 fail-closed 是系统安全边界，不用于控制 Sannai 的人格或关系。

---

## 2. 环境事实

### 2.1 2.88

- default 与 sannai gateway 都是 **user-level systemd service**，最终检查时均为 active。部署期间远端可选依赖安装被 OOM/SIGKILL，主机随后于 17:40:48 重启；这不是受控 reload 证据。
- Sannai profile 位于 `/vol1/.hermes/profiles/sannai`。
- 当前 Memory-OS Python 源码曾完成 128/128 文件哈希一致性核验。
- 历史 roster 中存在 alan 与 Hermes；这些记录只是实例数据，不证明伙伴 Agent 正在运行。
- 历史 alan 消息状态为 `deferred/sender_not_allowed`，不能称为投递成功。
- 不再使用 system-level `inactive` 判断 gateway 状态。

### 2.2 本机

- default gateway 为 user-level service。
- Hermes 支持标准 profile 隔离；异构伙伴应使用独立 `HERMES_HOME`，不与 Sannai 共用 profile。
- 静态 SOUL/目录不等于 partner runtime；只有 profile、模型、执行周期和真实 transport 均有证据时才标记 `live`。

---

## 3. 源码修复状态

| 能力 | 状态 | 证据边界 |
|---|---|---|
| roster schema / append-only lifecycle | `implemented + tested` | ID 校验、损坏行、重复 ID、状态转换、锁 |
| partner registration | `implemented + tested` | 路径 containment、从 canonical sibling profile `config.yaml` 解析 provider/model/endpoint 并验证异构、预算 fail-closed、重复保护、授权 actor；必须先由 Hermes 标准 profile CLI 创建 profile |
| shared projection | `implemented + tested` | Sannai-only writer、可信 newspaper actor、JSONL 锁 |
| trigger evaluator | `implemented + tested` | max-age、newspaper/shared cursor、重复抑制 |
| DynamicStateOverlay | `wired in source` | `community_snapshot` schema + renderer + builder consumer |
| cognitive loop | `wired in source` | `community_cycle` 每周期评估；`actual_send=false` |
| Hermes Agent 查询入口 | `implemented` | `memory-os-agent-os community status`；只读，不能伪造 Owner/Sannai actor |
| partner mutation | `library primitive; not public CLI` | 仅由具有当前明确 Owner 意图的 Hermes 主会话编排标准 profile CLI 与受测 primitive |
| standardized deploy | `implemented + tested + deployed` | 14 个部署源项：12 个核心/依赖/接线模块写入双 runtime，shell/helper 写入各自 canonical path；含目标 runtime import、原子回滚、哈希校验、备份、保留 budget；本机与 2.88 postcheck/幂等通过 |
| installer integration | `implemented + tested` | 安装 helper 并幂等初始化 community layout |
| mailbox 双向 transport | `transport + auth handshake tested; not autonomous-live` | 真实 Sannai→alanlive delivery/handled receipt 与 alanlive→Sannai pairing response 已出现；正式 pairing 已批准，但没有伙伴模型正文回复 |
| first partner autonomous runtime | `deployed + exercised; dormant` | 标准 profile `alanlive`、异构 provider/model/endpoint 与独立 gateway 曾运行；因 2.88 资源压力已停用 service，并把 lifecycle 转为 `dormant` |
| natural observation | `not started` | 只能在真实周期运行后累计 |

---

## 4. 标准部署契约

标准入口：

```bash
python scripts/deploy_community.py \
  --repo-root /path/to/Hermes-Memory-OS \
  --hermes-home /path/to/profile \
  --phase dry-run|apply|postcheck \
  --output json
```

部署器必须：

1. 先确认目标已安装完整 Memory-OS；缺少 plugin/runtime prerequisite 时 fail-closed，且不写目标。
2. 将 12 个 community 核心模块、直接兼容依赖和 overlay/cognitive-loop 接线模块部署到 profile plugin 与 Memory-OS runtime 两个 canonical consumer 路径；连同 shell/helper，当前计划共 14 个部署源项。
3. 安装只读 Agent-OS community shell 与 `deploy_community.py` operational helper。
4. 幂等创建 `community/{charters,shared,partners,system}` 与 roster。
5. 默认保留已有 `budget.yaml`；只有显式 `--force-budget` 才可替换，并先备份。
6. 对源码和所有目标做 SHA-256 postcheck；任何 copy/layout/hash 错误恢复本次全部文件变更并非零退出。
7. 不创建具体伙伴，不自动发消息，不修改 identity/relationship/mature memory。

标准 Memory-OS installer 同时安装 helper 并初始化布局，但具体伙伴仍由 Hermes/Sannai 的受治理入口创建。

---

## 5. 运行接线

### 5.1 Overlay

`build_state_overlay()` 从 profile-local community 数据和 profile `config.yaml` 注入的 mailbox root：

- `memory-os/community/roster.jsonl`
- `memory-os/community/shared/*.jsonl`
- `platforms.mailbox.extra.root/agents/<agent_id>/inbox`

构建 `community_snapshot`。profile root 由 `MemoryOSRoots` 注入，共享 mailbox root 由该 profile 的 `config.yaml` 注入；不再硬编码主机或 Sannai 目录。

该投影只进入当前上下文，不直接写 identity、relationship 或 crystallized memory。

### 5.2 Cognitive loop

`CognitiveLoopRunner` 包含 `community_cycle`：

- 读取 active roster；
- 运行 cursor-aware trigger evaluator；
- 产生有界候选和原因，并用最近 scheduler reports 抑制相同 source cursor 的重复候选；
- 明确报告 `actual_send=false`、`actual_execute=false`。

这证明 evaluator 已被 scheduler consumer 调用，但不把候选误报为已经发送。

### 5.3 Partner lifecycle

允许：

```text
active -> dormant -> active
active|dormant -> retired
```

- retirement 仅 owner actor 可执行；
- append-only transition 记录保留历史；
- 非法状态和损坏 roster fail-closed；
- retired 不自动恢复。

---

## 6. P0 出口条件

P0 仍需全部满足后才能标记 `live/observing`：

- [x] 一个异构伙伴 profile 曾实际运行并有 run receipt；当前因资源保护处于 `dormant`，不等于持续 `live`；
- [x] 真实 mailbox ingress/egress 双向 transport receipt 与 pairing handshake；这不等于模型推理回复；
- [ ] Sannai wake → receive → reason → reply 行为证据；
- [ ] shared 由 Sannai 路径写入，而非测试或运维手写；
- [ ] community snapshot 在 fresh gateway session 可见；
- [ ] community cycle 在真实 scheduler report 中出现；
- [ ] exposure 不直接产生 identity/relationship/crystallized write；
- [ ] 事件触发占比、打扰率、自然引用率进入观察窗口。

在这些条件满足前，不能把 roster、导入成功、文件哈希或手写 inbox 称为“完整闭环”。

---

## 7. 回滚

- 关闭 community scheduler consumer 或移除 cognitive-loop step；
- 从 overlay schema/renderer 移除 `community_snapshot`；
- 从部署备份恢复模块；
- community JSONL 保留，不做 destructive rewrite；
- 不触碰 Sannai identity、relationship、diary、digest 或成熟记忆。

---

## 8. 当前判定

当前源码层应表述为：

```text
design: complete
implementation: complete for bounded P0 infrastructure
focused tests: 173 passed
mount-isolated tests: 2993 passed / 6 skipped / 2 bounded third-party warnings
fresh patched clone tests: 2993 passed / 6 skipped / 2 bounded third-party warnings
runtime wiring in source: complete (overlay + no-send cognitive consumer)
production deployment: local + 2.88 files deployed, postchecked and idempotency-checked
partner/mailbox E2E: transport and official pairing verified; autonomous reply not verified
partner runtime: deployed, briefly exercised, then disabled/dormant after resource-pressure incident
natural observation: not started
```

文件部署、导入和 transport receipt 只支持对应的 `deployed/tested` 状态；不会自动把 partner、推理回复、fresh-session overlay 或自然观察提升为 `live`。
