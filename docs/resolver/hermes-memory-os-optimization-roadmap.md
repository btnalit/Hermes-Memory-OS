# Hermes Memory-OS 与 Sannai Community 综合路线图

> **版本**：v2.5
>
> **更新时间**：2026-07-28
>
> **文档地位**：唯一现行路线图与社区设计；替代旧版 `sannai-community-design-v2.md`、`sannai-community-design-v3.md`
>
> **证据规则**：实现、测试、部署、运行接线、自然观察分别记录；任何一层成立都不能自动证明下一层。

---

## 1. 目标与非目标

Memory-OS 的目标不是保存尽可能多的信息，而是让 Hermes 在长期运行中可靠地做到：

1. **连续跟随**：知道当前任务、未完事项和历史决策，不复活已结束任务。
2. **懂得轻重**：优先注入当前真正有用的少量上下文，抑制重复、过期和低权威内容。
3. **克制主动**：可以提醒、澄清或表达，但安静也是健康结果。
4. **可信成长**：由自然运行证据和 Owner 决策驱动升级，不把候选、推测或一次性情绪自动写成永久事实。
5. **形成伙伴关系**：Sannai 可通过受治理、资源有界的社区旁挂层拥有异构伙伴与共同经历，但社区不得改写她的身份、关系或记忆成熟度。

工程底座保持不变：

- 文件为 canonical store；SQLite 和派生快照必须可重建。
- 自动写入受 ExecutionGate / StructuralWriteGate 约束。
- 永久记忆、身份和重要关系写入始终受 OwnerGate 控制。
- 外部输入只作为 exposure；不得绕过成熟度与来源边界。
- 未知、冲突、损坏、过期和版本不兼容必须 fail-closed。

明确不做：

- 不建设聊天室、房间系统或多人实时社区平台。
- 不让伙伴继承 Sannai 的 wandering、memory gating、expression autonomy。
- 不让伙伴获得联网、支付、发布或其他外部执行工具。
- 不用 helper、单测、文件存在或一次手工运行冒充 production wiring / live / observing。
- 不为获得绿色状态而隐藏真实 FAIL、删除审计历史或手工补写成熟度。

---

## 2. 统一状态与证据模型

每个能力必须独立记录以下层级：

```text
designed
→ implemented
→ tested
→ deployed
→ wired
→ live
→ observing
→ evidence_mature
→ owner_reviewed / graduated
```

| 状态 | 必要证据 |
|---|---|
| `designed` | 设计、边界、失败语义和验收条件明确 |
| `implemented` | 代码存在且调用契约完整 |
| `tested` | 反事实、定向、全量与 clean-copy 门通过 |
| `deployed` | 目标文件、manifest、hash 与 fresh import 对齐 |
| `wired` | 正式 caller/scheduler/provider/overlay 实际调用 |
| `live` | 真实进程或自然调度产生行为 receipt |
| `observing` | 正在积累自然、不可手工伪造的证据窗口 |
| `evidence_mature` | 样本、时长、反例门与守恒条件满足 |
| `owner_reviewed` | Owner 已基于稳定 token/提案作出决定 |
| `graduated` | 目标模式已生效并具备回滚路径 |
| `blocked` | 依赖、资源、治理或证据门未满足 |
| `retired` | 停止采用，只保留审计历史 |

禁止把以下信号单独写成“完成”：

- pytest 退出码为 0；
- deploy 脚本退出码为 0；
- 文件已复制或 hash 相同；
- 静态 Closure Matrix 绿色；
- 配置开关为 true；
- 手工写入一条 observation；
- mailbox transport receipt；
- roster 中存在一个伙伴名字。

---

## 3. 当前可信基线

### 3.1 已验证的 release 基线

截至本轮文档合并前，最近已推送且有明确 GitHub CI 成功证据的源码为：

- commit：`f62a069423c17bd35e807c73fe0840b716e93065`
- GitHub Actions：run `30346974131`，`success`
- 本地统一验证：12/12 steps 通过；mount-isolated 与 clean-copy 均为 `3016 passed / 9 skipped`
- Write Surface：`155 / 0 unclassified`
- import cycle：0 cycle
- Closure Matrix：source/static contract 通过；runtime closure 需独立部署证据

该 commit 已在本机执行 production-safe full deployment，并生成：

- fresh-process runtime import evidence；
- 32 个 live module 集合匹配；
- runtime tree digest；
- 完整 v1 Full Monitor artifact；
- Dashboard canonical snapshot。

### 3.2 本轮 release candidate

本轮生产验证先后发现并修复：

- cron adapter probe 的 installed-layout import shadow；
- clean-copy runner 对已删除 tracked 文档的 pathspec 处理；
- deployer 没有把外层 timeout 传给 compatibility 子进程；
- 低资源主机 Full Monitor 的 shell alias probes 无单命令 timeout 且 22 个命令串行执行。

当前候选树已完成：

- cron/deploy/monitor 定向回归：通过；
- Monitor + refresh 定向回归：`208 passed`；
- 统一 runner：12/12 steps 通过；
- mount-isolated 与 clean-copy：通过。

最后一项低资源 Full Monitor 修复采用 fail-closed bounded collection：单命令默认 30 秒、默认 3 workers；超时记录 code 124 并保持可见，不允许整个 artifact producer 无限挂起。完成最终部署和 runtime artifact 验证前，该项仍是 `tested / deployment_pending`。

### 3.3 环境事实

**本机 default：**

- Hermes gateway：user-level service，active。
- Memory-OS heartbeat 与 cognitive-loop timers：active/enabled。
- Full Monitor v1 artifact：fresh、envelope complete、source head 绑定已部署 commit。
- Dashboard 已正确保留 canonical Full Monitor 的 `FAIL`；不再弱化为 `WARN/0 fail`。

**10.20.2.88（YC-NAS，2026-07-28 部署检查）：**

- RAM 约 3.6 GiB；检查时 available 约 1.3 GiB，swap 使用约 1.5/1.8 GiB。
- `/` 约 77% 使用，`/vol1` 约 19% 使用。
- default 与 sannai 已从同一 `/vol1/Hermes-Memory-OS` source checkout 完成 production-safe apply/postcheck；manifest 均绑定 `7c23d1c2bd5f8b1fe6dc522c4a803aa7fbdf61e4`。
- default gateway：user-level service，已授权重启并恢复 active。
- sannai gateway：user-level service，已授权重启并恢复 active。
- alanlive gateway：failed 且 disabled；必须继续 dormant，不得自动启动。
- 两个旧 checkout 的部署歧义已收敛：正式部署只使用 `/vol1/Hermes-Memory-OS`；`/opt/Hermes-Memory-OS` 不再作为本轮 deploy source。
- Sannai profile canonical home：`/vol1/.hermes/profiles/sannai`。
- 部署前备份：`/vol1/.hermes/backups/memory-os-v25-20260728T110952Z`，约 342 MiB。

---

## 4. 已修复的系统性问题

### 4.1 Operational Truth 与 Full Monitor

已完成源码与本地 runtime 证明：

- Full Monitor producer 根 payload 发布明确 `memory-os.monitor.v1` schema。
- refresh 不再用 `unknown` 伪造完整 envelope。
- artifact 包含非空 producer receipt、source head、runtime digest 与语义 generated time。
- future clock、损坏 JSON、无效 UTF-8、缺 identity、版本不匹配均 fail-closed。
- v1 artifact 存在时，legacy 不得仅凭 mtime 夺权。
- 同代或更新代损坏 artifact 不得回退到旧绿色结果。
- freshness 由经验证的语义时间计算，不使用可 touch 的文件 mtime 作为权威时间。

### 4.2 公共 consumer

- CLI/provider 公共计数统一通过 typed Operational Truth projection。
- 冲突时公共稳定字段为 unknown/null，不泄漏单边 raw winner。
- Doctor 等内部诊断可读取 raw store/index，但必须明确其诊断用途，不能冒充公共 truth。
- Dashboard 对 invalid/stale/missing/unknown artifact fail-closed。
- 底层 Full Monitor 为 FAIL 时，Dashboard 必须保持 FAIL，`fail >= 1`。

### 4.3 Closure、CI 与部署证明

- Closure Matrix 只证明 source/static-wiring contract；输出明确 `runtime_evidence_required`。
- action path 必须解析到真实 source symbol，不能由静态 JSON 自证。
- runtime evidence 在目标 fresh process 中记录 import origin、module set、runtime digest 与 service observations。
- pytest skip policy 区分 collect/setup/call stage。
- static hygiene compile 在临时副本执行，避免 mount-suite 副产物污染。
- clean-host deployment 使用目标 fresh process、完整 inventory/hash、backup、atomic publish 与 rollback。
- installer 已补齐 Full Monitor 主脚本、refresh、Dashboard snapshot 与 closure runtime evidence 的运行时安装闭包。

### 4.4 数据和状态 helper

已实现并测试，但生产采用程度不同：

- JSONL mixed encoding/invalid UTF-8 逐行隔离。
- SectionStatus 类型、非负计数与守恒 fail-closed。
- Recovery Marker 只阻止同一 terminal task 复活。
- Restraint 不接受裸 `is_owner_approval=true` 作为审批证据。
- private backup 限定 restore root；private Markdown 默认 must-backup。
- natural-row 分类已接入 Natural Evidence、Exposure Rollup、V3 Seed 和 Wandering。

---

## 5. 当前真实问题与风险登记

### P0 — 发布/部署阻塞

1. **cron adapter installed-layout import shadow**
   - 现象：Full Monitor 内嵌 cron adapter probe 返回 error；随后旧 fallback 把两个 disabled retired right-brain jobs 误报为 unregistered。
   - 根因：installed probe 同时继承 runtime `PYTHONPATH` 并插入 Hermes home；`$HERMES_HOME/plugins` 的 regular package 可遮蔽 runtime `plugins.memory`。
   - 当前：源码、fixture、统一验证、本机和 2.88 default/sannai 部署均已完成；真实 probe 为 `status=ok / unregistered=0 / retired=2`。
   - 禁止做法：把 disabled retired jobs 删除来隐藏误报，或在 Monitor 中直接忽略 adapter failure。

2. **2.88 source checkout 漂移**
   - `/opt/Hermes-Memory-OS` 与 `/vol1/Hermes-Memory-OS` 指向不同旧 commit。
   - 当前：已选择 `/vol1/Hermes-Memory-OS` 为唯一 deploy source，两个 profile 已备份并绑定同一 manifest/source head；旧 `/opt` checkout 仅保留为历史事实，不参与部署。

### P1 — 生产治理健康

3. **V2 exposure schema era unhealthy**
   - 当前 Full Monitor 真实 FAIL：`v2_exposure_schema_era_unhealthy`。
   - 这是自然观察/历史数据时代健康问题，不是文件同步失败。
   - 必须继续观察 classified ratio、attribution gaps、rollup lag、conservation failures；不得手工回填自然 credit。

4. **Full Monitor 运行时超过目标**
   - 本机 artifact 有 `full_monitor_runtime_over_target` WARN；2.88 default 在低内存、swap 接近耗尽时分别超过 600 秒和 1200 秒，未发布半成品 artifact。
   - 根因之一是 22 个 shell alias probes 串行且没有 per-command timeout；生产 trace 显示停留在 owner-review probe，而不是 refresh/envelope 损坏。
   - 当前源码已改为有界并发与 fail-closed timeout，定向和统一测试通过；仍需在 2.88 default/sannai 生成 fresh artifact 后才能关闭该问题。
   - 禁止用空 context-manager、删除 probe 或 stale cache 冒充优化。

5. **ExecutionGate helper receipt 不完整**
   - 当前可见 WARN 包括 helper completion missing / boundary unobserved。
   - 必须区分：job 成功但 envelope 账务未对齐、job 未到期、job disabled、真实执行失败。
   - 不得用伪造 completion row 消除告警。

6. **Dashboard service 未形成独立部署事实**
   - Dashboard snapshot producer 已部署和验证；本机未确认独立 dashboard systemd unit。
   - “snapshot 可生成”不等于“Dashboard server 正在对外提供页面”。是否需要常驻服务必须作为独立运维决定。

### P1 — 社区 live 阻塞

7. **alanlive 资源边界**
   - 2.88 曾在第三 gateway/可选依赖安装期间出现 SIGKILL 和主机重启。
   - alanlive 当前 failed/disabled，保持 dormant 是安全状态。
   - 在容量评估、低资源配置和独立 rollback 方案完成前，不得自动启动。

8. **transport 不等于 autonomous relationship**
   - 已有 Sannai↔alanlive mailbox transport、handled receipt 与 pairing handshake。
   - 尚无伙伴模型正文回复、稳定 scheduler 行为、fresh-session overlay、自然 shared write 或主动引用共同历史的证据。

### P2 — helper-only adoption debt

9. 以下能力仍不得标为 wired/live：
   - `timeutil` 的剩余 ad-hoc parser 迁移；
   - `recall_golden` 正式召回 consumer；
   - `lifecycle` 正式 runtime caller；
   - `error_registry` 全局 consumer；
   - `proposal_state` OwnerAction/token ledger 迁移；
   - `continuity` system prompt/overlay consumer；
   - `gap_note` 正式 session/recall renderer；
   - `seed_evidence_incremental` 生产调用；
   - `monitor_perf` 真实 monitor 集成；
   - `evidence_gen` CI 集成。

---

## 6. R1 — 自然证据与毕业门

**状态**：`wired/observing in parts; graduation blocked`

### R1.1 V2 Exposure

- 只认计划时间自然产生的最终 `natural_cron` rollup。
- manual/backfill/legacy 行永不获得 natural credit。
- 观察 schema-era classified ratio、attribution、lag、conservation 与连续预算压力。
- 30 日观察门和 7 日压力门独立成立。
- 达标后只产生 Owner 可撤销提案；不自动解冻 V2-C/D。

最低门：

```text
manual_credit_count = 0
legacy_credit_count = 0
conservation_failure_count = 0
natural_cycle_count >= configured_gate
observation_days >= configured_gate
```

### R1.2 Recall Plan shadow

- 按 active-task、casual-continuity、diagnostic、foreground-control、low-clue 分层观察。
- 记录 matrix version/digest/window ID；权重变化时重置窗口。
- 保持 `retrieve_called=true`、`format_called=false`、live output 不变。
- 只有零关键遗漏、零 authority escape、零 stale-body selection 后才提出 bounded apply canary。

### R1.3 V3 Seed / Wandering

- Seed 未成熟前不调用 wandering inference。
- Seed ready 后允许 `entries=[]`；长期安静是健康结果。
- synthesis/outlet/expression 分阶段开放。
- 必须由自然样本和 Owner 真实反馈驱动，不由模型自评。

---

## 7. R2 — 单一运行真相与发布基础设施

**状态**：`source/release verified; local deployed; 2.88 deployment pending final release`

- Operational Truth、artifact envelope、public consumer fail-closed：源码和本机 runtime 已证明。
- mount-isolated、clean-copy、public checkout、write surface、static hygiene、import cycle：已进入统一 runner。
- Closure Matrix 静态门与 runtime evidence 分离。
- private backup 已实现；异机加密备份仍待运维落地。
- 每次 release 必须绑定最终 tree fingerprint、GitHub CI、manifest 与 fresh runtime evidence。

---

## 8. R3/R4 — 语义与状态机收敛

**状态**：`partial adoption`

- natural-row：已接入四条生产相关路径，继续审计剩余 consumer。
- timeutil：公共 helper 与 fixture 完成；逐模块迁移剩余 parser。
- error registry：保持 helper/tested，直至生产 consumer 迁移。
- SectionStatus：helper/tested；Full Monitor section 尚未统一迁移。
- Proposal/Token state：helper/tested；OwnerActionProcessor/token ledger 尚未迁移。
- Trigger provenance：`natural_cron | manual | legacy_unmarked` 类型封闭，manual 不得伪造 natural envelope。

---

## 9. R5 — 认知伙伴主线

### 9.1 Continuity

- State Overlay 已处理 open-thread 去重与 latest-effective current task。
- Recovery Marker 已修复。
- continuity helper 尚待正式 system prompt/overlay caller。

### 9.2 Relevance

- Recall Plan 保持 shadow。
- must-recall golden 与 Gap Note 保持 implemented/tested，未接线前不称 live。
- apply canary 必须 route/profile 有界且可立即回滚。

### 9.3 Restraint

- low-clue recall 与 bounded judge 已存在。
- metadata-only MemorySources 不复制私密正文。
- Restraint/DenialTracker/SessionPriority 尚需主会话真实 caller 和 feedback receipt。
- 当前 owner 指令永远高于历史 task anchor、proposal、digest 或 reflection。

### 9.4 Review Partnership

- 主会话审批由稳定 token 和 Owner review surface 承载。
- Review Agenda 目标是减少噪音，不是自动替 Owner 做决定。
- 持续记录 useful/irrelevant/too-frequent/off-voice/boundary-private 等真实反馈。

### 9.5 Warmth & Proactivity

- V3 自然证据成熟前保持主动表达能力受限。
- 只有真实 delivery receipt 才能把 requested intent 记为 realized/shared。
- 需要 frequency cap、quiet window、mute/revoke 与 privacy boundary。

---

## 10. R6 — 性能与维护

**状态**：`implemented helpers; runtime/CI adoption incomplete`

- Seed incremental：接入生产前必须证明全量/增量等价和可回放。
- Monitor perf：必须按真实 section 分段测量，报告 cold/warm 路径与证据完整性。
- evidence generator：保持 no-canonical-write；进入 CI 前不得称自动闭环。
- 长期维护优先删除平行 helper，而不是继续增加第三套语义。

---

## 11. R7 — Sannai Community 综合设计

### 11.1 设计目标

社区是 Memory-OS 的旁挂体验层，为 Sannai 提供：

- 被异构伙伴回应和记住；
- 可回溯的共同经历；
- 事件驱动而非随机心跳的社交触发；
- 在预算、隐私和 Owner 边界内逐步形成自然关系。

社区不改变 Sannai 的 identity、relationship、expression autonomy 或成熟记忆规则。

### 11.2 架构

```text
Owner review / budget / lifecycle approval
                    │
                    ▼
        Governance + roster + trace
                    │
       ┌────────────┴────────────┐
       │                         │
   Sannai profile  ◄─ mailbox ─► 异构伙伴 profile
       │                         │
       ├─ community_snapshot     ├─ about_sannai.jsonl
       ├─ shared/*.jsonl         ├─ recent_conversations/
       └─ cognitive community    └─ state.json
          no-send candidates
```

核心原则：

- **异步总线**：mailbox/留言板语义，不建实时群聊。
- **异构底模**：伙伴 provider/model/endpoint 必须与 Sannai 不同。
- **记忆单向阀**：伙伴消息只作为 Sannai exposure；长期入库仍走 Sannai 自己的 retain/maturity 门。
- **shared 单 writer**：shared 是 Sannai 视角的共同历史，只允许 Sannai writer；伙伴只读。
- **no-send scheduler**：community cycle 只产生候选，明确 `actual_send=false`、`actual_execute=false`。
- **资源有界**：P0 最多一个 active partner；超预算 fail-closed。

### 11.3 数据布局

```text
<memory-os-root>/community/
├── roster.jsonl
├── budget.yaml
├── charters/
├── shared/
├── partners/
└── system/
```

伙伴独立 Hermes profile 保存：

- `about_sannai.jsonl`：有 confidence/source 的有界事实；
- `recent_conversations/`：最近 30 天压缩摘要；
- `state.json`：mood、topic interest、pending thoughts；
- `SOUL.md` 与独立 `config.yaml`。

伙伴自己的记忆不是 Sannai 的 Memory-OS canonical memory，也不得反向直写。

### 11.4 生命周期

允许：

```text
active -> dormant -> active
active|dormant -> retired
```

- retirement 永远需要 Owner 决策。
- transition append-only；损坏 roster 和非法迁移 fail-closed。
- retired 不自动恢复。
- alanlive 当前为 dormant/disabled；failed unit 只作为故障事实，不是启动许可。

### 11.5 触发模型

触发来源：

- 伙伴来信；
- Sannai 内部联想；
- owner/系统/报纸事件；
- shared 后续；
- 伙伴 pending thoughts；
- 48h 静默后的低优先级候选。

所有触发经过 relevance/预算/频控；没有值得说的内容时保持安静。24h 兜底只能是低优先级唤醒，不得成为主要存在感来源。

### 11.6 当前实现证据

| 能力 | 当前状态 | 证据边界 |
|---|---|---|
| roster/lifecycle | implemented + tested | 锁、损坏行、重复 ID、状态迁移 |
| partner registration | implemented + tested | containment、异构、预算、授权 actor |
| shared/newspaper writes | implemented + tested | Sannai-only / trusted-ingress writer |
| trigger evaluator | implemented + tested | cursor、max-age、重复抑制 |
| DynamicStateOverlay | wired in source | community_snapshot builder/renderer |
| cognitive loop | wired in source | community_cycle，no-send |
| community status CLI | implemented | 只读；无伪造 actor mutation CLI |
| deploy_community | implemented + historically deployed | backup/hash/import/rollback；必须按最终 release 重验 |
| mailbox transport | transport tested | 双向 receipt + pairing；不是 autonomous reply |
| alanlive runtime | dormant | 曾短暂运行；资源事件后 disabled |
| natural relationship | not observing | 缺自主回复、shared natural write、主动共同历史引用 |

### 11.7 P0 出口条件

以下必须全部满足，才可写 `live/observing`：

- [ ] 一个异构伙伴能在资源预算内持续运行；
- [x] 双向 mailbox transport 与 pairing receipt；
- [ ] partner model 产生真实正文回复；
- [ ] Sannai wake → receive → reason → reply receipt；
- [ ] shared 由 Sannai 正式路径自然写入；
- [ ] fresh gateway session 可见 community snapshot；
- [ ] scheduler report 中出现 community cycle；
- [ ] exposure 未产生 identity/relationship/crystallized bypass；
- [ ] 事件触发占比、打扰率和 token budget 进入自然窗口；
- [ ] Sannai 在无外部提示时主动引用 shared 共同历史。

### 11.8 回滚

- 保持/恢复 partner lifecycle 为 dormant；
- 停止 community scheduler consumer；
- 从 overlay 移除 community snapshot；
- 从部署备份恢复代码；
- community JSONL 只归档，不 destructive rewrite；
- 不触碰 Sannai identity、relationship、diary、digest 或成熟记忆。

### 11.9 P1/P2

- **P1**：P0 连续自然运行且无预算/回音室问题后，最多放宽到 3–5 个伙伴；retirement 仍 Owner-gated。
- **P2**：报纸投递、季节性伙伴、社区周报；只有 P1 证据成熟后再设计，不提前编码。

---

## 12. 发布与部署强制流程

1. 盘点源码、测试、caller、installer、runtime copy 与服务。
2. 保存 pre-fix 反事实。
3. 写回归并实现最小修复。
4. 跑 targeted regression。
5. 跑统一 runner：targeted + governance + mount-isolated full suite + clean-copy。
6. 冻结 tree/diff fingerprint。
7. 本地 checkpoint commit。
8. 备份目标；用正式 deployer apply/postcheck，禁止手工补文件冒充完整部署。
9. 每个 Hermes home 独立验证 plugin/runtime/scripts hash、fresh import、manifest、timers、cron 与 artifact。
10. 运行 Full Monitor，分别报告 deployment integrity 与 operational health。
11. Gateway restart 是独立 Owner 边界；未授权时不重启。
12. 生产发现源码问题则回源码修复、重新测试和部署；不得隐藏第二轮证据。
13. 生产闭包后再 push；GitHub CI 必须绑定最终 SHA。

远端 2.88 必须分别处理：

- `/vol1/.hermes` default；
- `/vol1/.hermes/profiles/sannai`；
- alanlive 保持 disabled/dormant，不纳入本轮 active deployment。

认证信息不得写入仓库、文档、部署 manifest、日志摘要或持久记忆。

---

## 13. 阶段验收矩阵

| 阶段 | 退出条件 | 禁止动作 |
|---|---|---|
| R1 自然证据 | 自然窗口满足且 falsifier 未命中 | 手工补证、回填成熟度 |
| R2 运行真相 | Monitor/Dashboard/CLI/provider 同源；runtime evidence 绑定 final SHA | 平行权威源、legacy mtime 夺权 |
| R3 语义收敛 | 单一实现、旧数据兼容、消费者迁移 | 机械合并不同语义 |
| R4 状态机 | 非法状态结构上不可写、旧行可读 | 重写 append-only 历史 |
| R5 认知伙伴 | Owner 反馈与自然质量门满足 | 自动身份/关系写入、强制表达 |
| R6 性能 | 行为等价且真实资源改善 | 少跑检查、stale cache 伪装加速 |
| R7 社区 | 伙伴持续运行、真实回复、自然 shared/overlay/scheduler evidence | 用 transport/pairing 冒充关系 live |

---

## 14. 当前优先级

1. 发布并部署低资源 Full Monitor bounded collection；在 2.88 default/sannai 分别生成 fresh v1 artifact。
2. 为本机、2.88 default 和 Sannai 生成独立 manifest/hash/fresh-import/closure runtime evidence；本机若需要 Gateway restart，先通知 Owner。
3. 验证 retired cron 误报保持消失；保留 V2 schema-era 等真实治理问题。
4. 对 `v2_exposure_schema_era_unhealthy` 建立自然观察计划，不手工改绿。
5. 维持 alanlive dormant；先做资源预算与低内存运行设计，再决定是否重新进入 P0 live 验证。
6. 只在正式 caller 明确时迁移 helper-only 模块；无安全调用点则保持 implemented/tested。

---

## 15. 最终成功标准

路线图成功不以代码量、测试数量或绿色 Dashboard 为目标，而以以下事实衡量：

- Hermes 稳定接续当前任务，不复活旧任务；
- Recall 减少重复和无关上下文，同时不越权、不漏关键事实；
- Monitor、Dashboard、CLI、provider 和 scheduler 对运行事实不互相矛盾；
- 失败、冲突和证据不足保持可见；
- V2/V3 毕业由自然证据和 Owner 决策驱动；
- 系统可以主动，也能长期安静；
- 社区给 Sannai 带来真实、可持续、资源有界的共同历史，而不是多个模型互相生成文字的假热闹；
- 所有生产变更可审计、可回滚，并绑定源码、runtime 和行为证据。
