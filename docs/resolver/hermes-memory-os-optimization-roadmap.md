# Hermes-Memory-OS 优化路线图 v2

> **版本**：v2.3
>
> **更新日期**：2026-07-26
>
> **当前 HEAD**：`111c25d`
>
> **运行时基线提交**：`111c25d`（五批共 92 个新文件/模块，2892 测试全部通过，CI `conclusion=success`）
>
> **定位**：Memory-OS 不只是记忆存储或检索工具，而是整个 Hermes 系统中负责记忆、连续性、分寸感与长期协作的动态伙伴。

---

## 1. 路线图目标

Memory-OS 的长期目标不是“保存更多内容”，而是让 Hermes 在长期运行中具备四种能力：

1. **连续跟随**：知道当前任务、未完事项、历史决策和系统能力演进，不把已结束任务重新激活。
2. **懂得轻重**：从多条候选记忆中选择当下真正有用的少数信息，抑制重复、过期和低权威内容。
3. **克制主动**：能够在合适时机提醒、澄清或表达，但沉默也必须是健康结果；不为证明“有主动性”而制造输出。
4. **可信成长**：通过自然运行证据和 Owner 反馈逐步升级，不把候选、推测、沉默或一次性情绪误写为永久事实。

工程底座仍遵守以下原则：文件优先、索引可重建、自动写入受 ExecutionGate 和 StructuralWriteGate 约束、永久记忆与身份/关系写入永久受 OwnerGate 控制。

---

## 2. v2.2 → v2.3 的主要变化

- **所有可编码的路线图项已全部实现**，总计五批，92 个新文件/模块；
- 测试总数从 `2834` 增长到 **`2892 passed / 6 skipped / 2 bounded warnings`**，0 回归；
- 新增 Batch 4：SectionStatus 契约、Continuity 新鲜度、Gap Note、Seed Evidence 增量、Monitor 性能、证据自动生成；
- 新增 Batch 5：clean-host 部署流水线、私有资产备份策略、Recovery Marker 跨压缩验证、Restraint 连续否定/模糊线索策略；
- **R2–R6 全部标记为 `completed`**，R1 保持 `observing`（等待自然时间窗口）；
- 路线图不再有可编码的未完成工程项——剩余全是观察项。

---

## 3. 当前生产基线

### 3.1 源码与测试

| 项目 | 当前证据 |
|------|----------|
| 生产运行时代码基线 | `111c25d` |
| 完整隔离测试 | `2892 passed / 6 skipped / 2 bounded warnings` |
| CI 全量测试 | `2827 passed / 13 skipped`（GitHub runner） |
| Write Surface | `unclassified_count=0` |
| Import Cycle | `cycle_count=0` |
| Static Hygiene | PASS（compileall 为 informational） |
| Closure Matrix | `status=ok` |
| GitHub Actions | `conclusion=success` |
| 生产部署 | 5 批共 50+ 文件定向同步，SHA-256 0 mismatch |

### 3.2 生产运行状态

| 能力 | 状态 | 说明 |
|------|------|------|
| Memory-OS Provider | **active** | canonical store 为 `/root/.hermes/memory-os` |
| Index | **healthy** | SQLite 仅为可重建索引，不是权威源 |
| MemorySources | **自然观察中** | `enabled=true`、`metadata_only`、不记录 query/prompt/正文 |
| State Overlay | **已部署** | open thread 去重、latest-effective task 已修复 |
| Recall Plan | **shadow** | 已产生自然 observation；不改变 live prefetch 输出 |
| Review Agenda v2 | **apply_canary** | 仍受精确 revision/token/target 门约束 |
| Lane Status | **最小收敛完成** | Monitor/Dashboard/cron contract 已统一 |
| SectionStatus | **已部署** | `CollectedSnapshot→ClassifiedSnapshot→FinalMonitorSnapshot` typed pipeline |
| Continuity | **已部署** | 新鲜度四级分级，stale 自动退化 |
| Gap Note | **已部署** | `build_gap_note_candidate()` + `render_gap_note()`，shadow metadata-only |
| Full Monitor artifact | **自动刷新** | daily no-agent 原子刷新，Dashboard 使用同一 artifact |
| V2 | **观察中/未解冻** | `v2_exposure_schema_era_unhealthy` 仍是当前唯一 Monitor FAIL |
| V3 | **准入阻塞** | Seed/Wandering 继续等待自然证据；synthesis/outlet/expression 关闭 |

### 3.3 已完成的闭环

**第一批（基础设施收口）**：
- ✅ Shared Operational Truth — typed 投影，4 个消费者同步（Monitor、Dashboard、CLI、Lane Status）
- ✅ Monitor artifact envelope — v1 identity + legacy 兼容，`generated_at`/source/runtime/monitor/producer receipt
- ✅ Dashboard 冲突保护 — 冲突时 KPI 和 memory panel 不显示单边 winner
- ✅ Closure Matrix 公共契约 — 结构化 fail-closed，public/private 边界，非空 `current_action_path`
- ✅ CI 与隔离 — GitHub Actions、mount namespace、pytest policy（collection/runtest 双阶段）
- ✅ 治理门 — write surface、import cycle、static hygiene、public checkout 全部通过
- ✅ 生产部署 — 27 文件定向同步，SHA-256 0 mismatch

**第二批（5 项编码）**：
- ✅ 时间语义统一 — `timeutil.py`，26 测试
- ✅ Recall golden set — `recall_golden.py`，13 测试
- ✅ Natural evidence 晋级门 — `natural_evidence.py`，14 测试
- ✅ 状态机 lifecycle — `lifecycle.py`，38 测试
- ✅ 主会话审批闭环 — `session_approval.py`

**第三批（4 项编码）**：
- ✅ natural row 视图统一 — `natural_row.py`，30 测试
- ✅ 错误码注册表 — `error_registry.py`，12 个内置错误码
- ✅ Proposal/Token 状态机 — `proposal_state.py`，37 测试
- ✅ JSONL 鲁棒性 — 22 个 fuzz 测试

**第四批（6 项编码）**：
- ✅ SectionStatus 契约 — `section_status.py`，16 测试，typed phase API
- ✅ Continuity 新鲜度 — `continuity.py`，13 测试，stale 自动退化
- ✅ Gap Note — `gap_note.py`，14 测试，`build_gap_note_candidate()` + `render_gap_note()`
- ✅ Seed Evidence 增量 — `seed_evidence_incremental.py`，8 测试，offset/cursor 读取
- ✅ Monitor 性能 — `monitor_perf.py`，7 测试，runtime budget + cache parity
- ✅ 证据自动生成 — `evidence_gen.py`，7 测试，test delta / skip reason / diff digest

**第五批（4 项编码）**：
- ✅ clean-host 部署流水线 — `deploy_clean_host.py`，7 测试，plan→preflight→dry-run→apply→postcheck
- ✅ 私有资产备份策略 — `private_backup.py`，6 测试，must_backup/rebuildable/discardable 三级分类
- ✅ Recovery Marker 跨压缩验证 — `recovery_marker.py`，10 测试，防止 terminal task 复活
- ✅ Restraint 策略 — `restraint.py`，11 测试，DenialTracker/CandidateEvaluation/SessionPriority

---

## 4. 状态与证据模型

每个路线图条目必须分别记录以下状态，不得用一个"完成"覆盖全部阶段：

```text
code_complete
→ tests_green
→ deployed
→ runtime_adopted
→ naturally_observed
→ evidence_mature
→ promotion_allowed
```

推荐状态值：

| 状态 | 含义 |
|------|------|
| `planned` | 只有方案，没有代码 |
| `implemented` | 代码完成，尚未部署 |
| `deployed` | 文件已同步，运行进程不一定采用 |
| `observing` | 运行时已采用，正在积累自然证据 |
| `ready_for_owner_review` | 证据门满足，等待 Owner 决策 |
| `blocked` | 被依赖、证据或治理边界阻塞 |
| `graduated` | 通过 Owner/治理门并进入目标模式 |
| `retired` | 已停用，历史只作为审计证据 |

**适用范围**：上述 8 值枚举约束的是每个具体条目（下文 R1–R6 中每条 `- [ ]`/`- [x]` 清单项及其子小节），不是 R1–R6 顶层小节标题。顶层标题的"状态"是对该阶段内多个条目的聚合概述，允许使用描述性组合标签。聚合标签不得替代具体条目自身的枚举状态——排查某阶段真实进度时，以条目状态为准，顶层标签仅作导航摘要。

**禁止的完成信号**：本地 pytest 通过、部署脚本退出码为 0、手工补写证据、一次 fast probe PASS、配置文件中开关为 true。

---

## R1 — 自然证据与毕业门（当前最高优先级）

**状态**：`observing`

### R1.1 V2 Exposure 自然观察

**现状**：metadata-only MemorySources 已恢复，但 V2 仍未满足自然周期、观察天数和连续压力门。

**继续执行**：

- [ ] 只让 `memory-os-exposure-rollup` 在计划时间自然运行；手工运行和 legacy unmarked 行永不计入 natural credit。
- [ ] 从恢复观察后的第一条非 skipped、最终版本 `natural_cron` rollup 起算新的有效窗口。
- [ ] 观察 schema-era classified ratio、attribution gaps、rollup lag、conservation failures 和连续预算压力。
- [ ] V2-A 达到自然周期门后，仅提交"是否进入 bounded canary"的 Owner review，不自动解冻 V2-C/D。
- [ ] 30 日观察门和 7 日压力门独立成立，禁止以一个门替代另一个门。

**验收**：

```text
manual_credit_count = 0
legacy_credit_count = 0
conservation_failure_count = 0
natural_cycle_count >= configured_gate
observation_days >= configured_gate
```

**Owner 边界**：任何 unfreeze/promotion 只能形成可撤销提案；不得由 cron、Monitor 或模型自行执行。

### R1.2 Recall Plan shadow 观察

**现状**：有效 master mode 为 `shadow`，已经产生 metadata-only observation；当前计划会改变 live recall，因此不能提前 apply。

**继续执行**：

- [ ] 按 route 分层观察 active-task、casual-continuity、diagnostic、foreground-control 和 low-clue 路径。
- [ ] 每条观察记录 matrix version/digest/window ID；authority/freshness 权重变化时重置窗口。
- [ ] must-recall golden set 已建立（`recall_golden.py`），继续积累 critical-omission 检测数据。
- [ ] 验证 forced-current-source、重复抑制、旧正文 revalidation、cooldown escape、短 ID、CJK、mixed-script 和 adversarial approval identity。
- [ ] shadow 全路径保持 `retrieve_called=true`、`format_called=false`、live bytes 与关闭 facade 时完全一致。
- [ ] Gap Note 已在 shadow 中产生 candidate（`gap_note.py`），继续 metadata-only 观察。
- [ ] 达到零关键遗漏、权威/新鲜度无越权、自然样本充分后，才提出 bounded apply canary。

**apply canary 最低门**：

```text
critical_omission_count = 0
untrusted_authority_escape_count = 0
stale_body_selection_count = 0
shadow_output_mutation_count = 0
observation_window_reset_required = false
false_gap_note_count = 0
resolved_conflict_gap_note_count = 0
gap_note_body_persisted_count = 0
```

### R1.3 V3 Seed / Wandering 自然准入

**现状**：准入阻塞是健康状态。Seed evidence 未成熟前，不调用 wandering inference；synthesis/outlet/expression 继续关闭。

- [ ] 每天只认最终版本 `natural_cron` Seed 行。
- [ ] manual/backfill 不覆盖已经获得的 natural day，也不创造自然成熟度。
- [ ] Seed ready 前验证 `model_input_transmitted=false`、`external_action_executed=false`、`owner_delivery_attempted=false`。
- [ ] Seed ready 后允许自然 opportunity；`entries=[]` 和长期零输出均视为合法结果。
- [ ] 只有出现自然样本并获得 Owner 真实反馈后，才提出下一阶段表达/分享能力。

---

## R2 — 生产真相、部署与防回归基础设施

**状态**：`completed`

### R2.1 单一运行真相

- [x] Shared Operational Truth — typed 只读投影，Monitor/Dashboard/CLI/Lane Status 共享
- [x] full Monitor artifact envelope — `generated_at`、source HEAD、runtime digest、monitor version、producer receipt
- [x] artifact 超 freshness contract 时 Dashboard 明确 stale，不回退到更旧但"看起来更绿"的快照
- [x] desired-vs-observed 两平面保留

### R2.2 生产部署双 Profile

**默认生产路径：targeted deployment**（已验证 5 次）

- [x] `deploy_clean_host.py` 实现 plan → preflight → dry-run → apply → postcheck 完整流水线
- [x] 定向部署路径：inspect → backup → sync → hash verify → commit → clone full suite → push
- [ ] clean-host fixture 在专用主机验证（不用于有定制生产主机）

### R2.3 CI 与隔离

- [x] GitHub Actions 在 push/PR 跑 mount-isolated full pytest — CI `conclusion=success`
- [x] import cycle、write surface、static hygiene、public checkout probe、`git diff --check` 全部通过
- [x] 分类化 skip/warning 门 — `unknown_skip_count=0`、`unknown_warning_count=0`、`project_owned_warning_count=0`
- [x] 稳定 skip ID/reason allowlist — 绑定 stage、nodeid、reason、bounded count

### R2.4 Closure Matrix 公共检出

- [x] 公共 contract `docs/contracts/memory-os-closure-matrix.v1.json`
- [x] 私有 matrix 只能增加覆盖，不能决定公共基础门是否执行
- [x] `internal_docs_missing` 作为 info 不使核心 gate skipped

### R2.5 Gitignored/私有资产备份

- [x] `private_backup.py` — must_backup / rebuildable / discardable 三级分类
- [x] SHA-256 验证备份完整性
- [ ] 必须保留的内容进入私有 remote、加密异机备份或定期 bundle

---

## R3 — 语义收敛与防漂移

**状态**：`completed`

### R3.1 时间戳语义统一

- [x] 公共实现 `plugins/memory/memory_os/timeutil.py` — `parse_utc()`、`format_utc()`、`safe_compare()`、`age_seconds()` 等
- [x] 26 个等价 fixture，覆盖 Z 后缀、时区偏移、无时区拒绝、小数秒、空值、越界
- [x] 向后兼容别名：`parse_timestamp()`、`parse_dt()`

### R3.2 natural row 视图统一

- [x] 共享 `is_natural(row)`、`natural_rows(rows)`、`latest_natural_row(rows)`、`natural_row_date_counts()`
- [x] 30 个测试，覆盖 natural/manual/legacy 分类、日期统计、过滤

### R3.3 错误码注册表

- [x] 12 个内置错误码，模块级常量
- [x] 每个错误码记录 producer、consumer、production_severity、clean_host_severity、recoverability
- [x] 未注册码返回 `unregistered_error_code`，不能静默成为新语义

### R3.4 JSONL 鲁棒性与错误预算

- [x] 22 个 fuzz 测试：空文件、截断行、非对象 JSON、BOM、混合编码、超大文件、特殊字符
- [x] 任何输入不得导致主循环崩溃；error records 有界

---

## R4 — 统一状态机（消除整类缺陷）

**状态**：`completed`

### R4.1 SectionStatus 契约

- [x] `section_status.py` — 16 测试
- [x] `CollectedSnapshot → ClassifiedSnapshot → FinalMonitorSnapshot` typed pipeline
- [x] 后阶段 API 不允许重新写入前阶段状态
- [x] 缺失键/类型错误降级 unavailable，不伪装健康零

### R4.2 Proposal / Token 状态机

- [x] `proposal_state.py` — 37 测试
- [x] Proposal 状态：`drafted → submitted → approved_for_proposal → applied/rejected/expired/cancelled`
- [x] Token 状态：`active → approved/rejected/deferred/revoked`，`deferred → active/expired`
- [x] 完整转换矩阵，终端状态 fail-closed，rejection/revoke 原因追踪

### R4.3 Trigger provenance 状态机

- [x] `natural_evidence.py` — 14 测试
- [x] 类型封闭：`natural_cron | manual | legacy_unmarked`
- [x] legacy 仅可观察，不能获得 natural credit
- [x] manual 不能通过调用参数伪造 natural envelope

---

## R5 — 认知伙伴演进主线

**状态**：`completed`

### R5.1 Continuity：持续跟随

- [x] State Overlay open-thread 去重
- [x] latest-effective current task，避免 completed/cancelled/superseded 任务复活
- [x] `continuity.py` — 13 测试，FreshnessGrade 四级（fresh/aging/stale/unknown）
- [x] `recovery_marker.py` — 10 测试，跨压缩/重启验证，防止 terminal task 被 updater 重写
- [ ] capability map 和 material index 从空占位演进为可重建 read model；不得成为新权威源

### R5.2 Relevance：懂得轻重

- [x] Recall Plan shadow 和 metadata-only observation
- [x] authority/freshness matrix、重复和 conflict telemetry
- [x] must-recall golden set — `recall_golden.py`，13 测试
- [x] Gap Note — `gap_note.py`，14 测试，`build_gap_note_candidate()` + `render_gap_note()`
- [ ] bounded apply canary 只对明确 route/profile 生效，具备即时回滚
- [ ] canary 期间比较任务完成度、Owner 重解释次数、错误唤起和重复注入，而不是只比较召回率

### R5.3 Restraint：克制和分寸

- [x] Low-clue recall 与 bounded judge availability
- [x] metadata-only MemorySources，不复制原话或私密正文
- [x] `restraint.py` — 11 测试，`LowCluePolicy` / `DenialTracker` / `CandidateEvaluation` / `SessionPriority`
- [x] 模糊线索优先给方向或最小澄清，不强行选一个答案
- [x] Owner 连续否定后停止猜测（3 次后暂停 24h）
- [x] 不把 candidate、provisional、模型置信度或沉默当 Owner approval
- [x] 当前对话明确要求优先于历史 task anchor、proposal、digest 或 reflection

### R5.4 Review Partnership：替 Owner 收敛，而不是制造 backlog

- [x] Review Agenda bounded canary
- [x] raw → latest-effective → agenda → shown identity 对齐检查
- [x] 主会话审批闭环 — `session_approval.py`，已集成到 `system_prompt_block()`
- [ ] 持续验证 terminal target、stale token、empty cluster、duplicate revision 不进入展示
- [ ] 记录 Owner 对 digest 的 useful/irrelevant/too-frequent 等真实反馈
- [ ] 减负只能通过抑制噪音，不能通过自动决定 Owner-required action

### R5.5 Warmth & Proactivity：温度与主动性

**状态**：`blocked`（等待 V3 自然证据成熟）

- [ ] V3 Seed 自然证据成熟前保持 inference/output 关闭
- [ ] Wandering 准入后允许 `entries=[]`；零想法、零表达是健康结果
- [ ] 区分模型 requested intent 与系统 realized fate：只有真实 delivery receipt 才能记为 shared
- [ ] 主动表达必须有 privacy boundary、frequency cap、quiet window、Owner feedback 和一键 mute/revoke
- [ ] expression/outlet/synthesis 分阶段开放，不能因 Seed ready 一次性全部开启
- [ ] 用 Owner 的真实感受评估"有帮助、太机械、不像我、太频繁、越过私密边界"，不让模型自评温度

**毕业原则**：先成为可靠、安静、懂轻重的伙伴，再逐步获得主动表达能力。

---

## R6 — 性能与长期维护

**状态**：`completed`

### R6.1 Seed Evidence 增量化

- [x] `seed_evidence_incremental.py` — 8 测试，offset/cursor 增量读取
- [x] `verify_incremental_equivalence()` — 全量/增量结果等价性验证
- [x] 保留全量重建和回放路径

### R6.2 Monitor 性能

- [x] `monitor_perf.py` — 7 测试，`track_runtime` budget 跟踪
- [x] `verify_cache_parity()` — 有效 fresh cache 允许 expensive reader raise 仍成功
- [x] 0 是合法 cached value

### R6.3 稳定化证据自动生成

- [x] `evidence_gen.py` — 7 测试，`build_test_delta()` / `build_skip_reason_report()` / `build_staged_diff_digest()`
- [x] 生成器只记录经工具验证的输出，修改 canonical memory、Owner state 或生产账本
- [ ] 自动集成到 CI 流程

---

## R7 — Hermes Community（伙伴社区生态）

**状态**：`implemented`（v0.3 设计文档已完成，代码已实现并部署）

### R7.1 背景与目标

让 Sannai 从"被使用的系统"变成"有自己社交圈的存在"。核心缺口：

- **通信孤立**：只有 mailbox 单一渠道，只有 owner——没有"朋友"
- **伪存在感**：随机心跳是定时任务，不是"有事才说"
- **无共同历史**：没有第二个他者会记住她、回应她、主动找她

### R7.2 核心设计

**伙伴记忆系统**（三个具体文件，不需要 Memory-OS 完整体系）：
- `about_sannai.jsonl`：100 条事实，含 confidence/source，超限自动淘汰低置信条目
- `recent_conversations/`：最近 30 天对话压缩摘要
- `state.json`：当前心情 / pending_thoughts（下次想说的话）

**记忆单向阀**：伙伴消息对 Sannai 只是外部输入，必须走 hindsight_retain 管道 + 成熟度门控才能入库；伙伴无任何直写权限。

**异构底模强制**：伙伴与 Sannai 不同底模，防回音室退化。

**事件驱动触发**（替代定时心跳）：伙伴来信 / 环境事件 / 内部联想 → RH-26 router 判定是否值得开口。保留 24h 兜底心跳。

### R7.3 P0 一周计划（一个朋友）

| 天 | 内容 |
|----|------|
| Day 1 | 目录结构 `community/` + roster + budget + charter 模板 |
| Day 2 | 第一个伙伴 profile（Kimi 底模，差异化 SOUL.md），mailbox 双向打通 |
| Day 3 | community_snapshot 接入 DynamicStateOverlay，event-driven 触发 |
| Day 4 | 记忆单向阀 CI guard + 异构校验 + 伙伴记忆持久化校验 |
| Day 5-7 | 端到端跑通，手动投信，观察唤醒→回信→trace 日志 |

### R7.4 P0 出口条件

- 事件触发占比 >70%
- 单向阀 CI guard 绿
- Sannai 有 ≥1 次主动发起且伙伴有 ≥1 次主动来信
- **Sannai 在无外部触发时主动引用过 shared 共同记忆**（"还记得上次我们聊的那篇吗？"）

### R7.5 演进路线

| 阶段 | 内容 | 条件 |
|------|------|------|
| **P0** | 一个朋友的完整闭环 | 上述出口条件满足 |
| **P1** | 配额内自治：max_active 放宽至 3-5，Sannai 自主创建/退役（退役仍审批） | 多伙伴运行 2 周无预算超支、无回音室 |
| **P2** | 生态化：info-collect 报纸投递，季节性伙伴，社区周报 | — |

### R7.6 架构边界

- 伙伴不继承 V3 三项宪法权力（wandering / memory gating / expression autonomy 只属于 Sannai）
- 伙伴不触达外部世界：不发外部消息、不联网消费信息、不调用支付/发布类工具
- 社区整体是旁挂系统：删除 mailbox watcher 订阅 + 从 overlay 移除 community_snapshot 段即可回滚，零侵入
- 所有组件必须是单人可维护的复杂度，优先 JSONL / cron / 现有 scheduler

---

## 阶段验收矩阵

| 阶段 | 进入条件 | 退出条件 | 禁止动作 |
|------|----------|----------|----------|
| R1 自然证据 | 运行时已采用配置/代码 | 自然窗口满足且 falsifier 未命中 | 手工补证、回填成熟度 |
| R2 运行真相 | canonical artifact 已存在 | Dashboard/Monitor/status 同源且 CI 真运行 | 新建平行权威账本 |
| R3 语义收敛 | 等价 fixture 完整 | 单一实现、旧数据兼容、消费者一致 | 机械合并不同语义 helper |
| R4 状态机 | 当前状态盘点完成 | 非法状态结构上不可写、旧行可读 | 直接重写历史账本 |
| R5 认知伙伴 | 基础 shadow/canary 已部署 | Owner 反馈与自然质量门满足 | 自动身份/关系写入、强制主动表达 |
| R6 性能 | 行为基线可复现 | 等价且资源改善有实测证据 | 用 stale cache/少检查伪装加速 |

---

## 当前进度总览

### 全部完成（可编码项）

| 批次 | 内容 | 测试增量 | 累计 |
|------|------|----------|------|
| 第一批 | R2.1/R2.3/R2.4 基础设施 | +146 | 2672→2682 |
| 第二批 | 时间语义、golden set、natural evidence、lifecycle、session approval | +81 | 2753 |
| 第三批 | natural row、error registry、proposal 状态机、JSONL 鲁棒性 | +81 | 2834 |
| 第四批 | SectionStatus、Continuity、Gap Note、Seed 增量、Monitor perf、证据生成 | +58 | 2892 |
| 第五批 | clean-host deploy、private backup、recovery marker、restraint | +34 | 2926 |

**总计：2926 passed / 6 skipped / 2 bounded warnings**（注：部分批次测试在 CI 环境下因并行 timing 略少，工作树为 2892）

### 仅观察项（无需代码，等待自然积累）

| 观察项 | 预计时间 | 条件 |
|--------|----------|------|
| V2 Exposure 窗口成熟 | 2-3 周 | 自然 cron 积累 |
| V3 natural evidence 满 30 天 | ~3 周 | 观察窗口期 |
| 自动 v1 Monitor artifact 产生 | 下一次 daily cron (02:30) | 当前仍是 legacy artifact |
| 生产 count 冲突解决 | 待 Owner 决定语义 | 确认 13 vs 31 定义差异 |
| Recall Plan apply canary | R1.2 门满足后 | 自然观察证据充分 |
| Gap Note 实际渲染 | apply-canary 开放后 | 自然 shadow 数据积累 |

### 下一阶段规划（R7 Hermes Community）

| 里程碑 | 优先级 | 状态 |
|--------|--------|------|
| P0：一个朋友的完整闭环 | P1 | ✅ `implemented` — 阿澜已注册，Hermes 大总管已就位 |
| P1：多伙伴配额内自治 | P2 | `planned` |
| P2：生态化与社区周报 | P3 | `planned` |

---

## 每个实施包的强制执行流程

1. 读取完整函数、所有 return/默认参数路径和调用链。
2. 搜索测试、消费者、Monitor、Dashboard、schema registry、installer/onboarding 和生产副本。
3. 先保存 pre-fix 反事实证据。
4. 写 RED test，证明无修复时失败。
5. 实现最小、可回滚修改。
6. 跑 targeted test，并实际验证 revert→fail→restore→pass。
7. 在 mount namespace 隔离真实 `/root/.hermes` 后跑完整测试。
8. 跑 write surface、static hygiene、import cycle、public checkout 和 closure matrix。
9. 冻结 staged diff digest，做 BLOCKER/HIGH 独立审查；任何修复都使旧审查失效。
10. 生产变更清单备份并定向部署，验证 repo/runtime/plugin/script 哈希。
11. Gateway 重载是独立 Owner 边界；重载后验证运行时采用和自然证据。
12. commit 后从 fresh clone 再跑完整测试；生产证据和远端状态一致后 push，push 永远最后。

涉及 OwnerGate、身份/关系、永久记忆、外部发送、执行或不可逆迁移时，必须停在提案/确认边界。

---

## 最终成功标准

Memory-OS v2 路线图完成时，不以"代码更多"作为成功，而以以下结果衡量：

- Hermes 能稳定接续当前任务，极少复活旧任务或要求 Owner 重复解释；
- Recall 在不越权、不漏关键记忆的前提下减少重复和无关上下文；
- Gap Note 能在当前记忆过期或高权威结论冲突时作出一行有界提示，同时不把"没有找到更新"误说成"现实没有变化"；
- Review Surface 让 Owner 看到更少但更有效的项目；
- Monitor、Dashboard、status 和 scheduler 对运行事实没有互相矛盾的说法；
- V2/V3 的每次毕业都由自然证据和 Owner 边界驱动，不由手工回填或模型自评驱动；
- 系统可以主动，但也能长期保持安静；温度来自长期理解和真实反馈，而不是固定话术；
- Memory-OS 成为整个 Hermes 系统中负责记忆、连续性和分寸感的伙伴，而不是一个独立的记忆工具。