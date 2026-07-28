# Hermes-Memory-OS 优化路线图 v2

> **版本**：v2.4（源码统一验证通过，生产部署待验证）
>
> **更新日期**：2026-07-27
>
> **修复前源码基线 HEAD**：`3ef422e330f99271c58a65874c2bee016907c9f4`；本版修复尚未提交，最终 HEAD 以统一测试后的单次提交为准
>
> **运行时基线**：部署 manifest 与 Full Monitor artifact 曾出现 source/provenance 漂移；本版部署前不声明与源码 HEAD 一致
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

## 2. v2.4 审查修正

v2.3 把“新增 helper + helper 单测 + 文件同步”错误升级为 `completed / deployed / runtime_adopted`。v2.4 撤销该推断，并按证据层重新标注：

- 第一批生产真相、artifact envelope、consumer conflict、Closure Matrix、pytest policy、static hygiene 与 clean-host provenance 的实质缺陷已进入源码修复；**统一测试、提交、部署和 fresh-process 证据尚未完成**。
- `timeutil.py`、`lifecycle.py`、`proposal_state.py`、`continuity.py`、`gap_note.py`、`seed_evidence_incremental.py`、`monitor_perf.py`、`evidence_gen.py` 等若没有真实 caller/CI/Monitor 接线，只能标为 `implemented`，不能标为 `runtime_adopted`。
- `natural_row.py` 已开始接入 Natural Evidence、Exposure Rollup、V3 Seed 与 Wandering；这仍不等于所有生产自然证据路径已迁移。
- SectionStatus、Recovery Marker、Restraint、private backup 与 clean-host deploy 的 fail-closed 语义已修正；运行态采用仍须部署后验证。
- R2–R6 顶层 `completed` 全部撤销。后续只允许用代码、测试、部署、fresh-process 行为、自然证据分别证明对应层级。

---

## 3. 当前生产基线

### 3.1 源码与测试

| 项目 | 当前证据 |
|------|----------|
| 修复前源码基线 | `3ef422e330f99271c58a65874c2bee016907c9f4` |
| 历史完整隔离测试 | `2993 passed / 6 skipped / 2 bounded warnings`（仅绑定旧树） |
| 历史 CI | run `30256247567` success（仅绑定 `3ef422e`） |
| Write Surface | 本版 `surface_count=155, unclassified_count=0` |
| Import Cycle | 本版 `module_count=170, cycle_count=0` |
| Static Hygiene | 本版 pass；compileall 为 release-fatal |
| Closure Matrix | static contract pass；`closure_status=runtime_evidence_required`，不冒充 runtime closure |
| GitHub Actions | 本版待单次 push 后重新验证 |
| 生产部署 | 本版未部署；历史文件/哈希证据不得继承 |

### 3.2 生产运行状态

| 能力 | 状态 | 说明 |
|------|------|------|
| Memory-OS Provider | **last-known active** | canonical store 为 `/root/.hermes/memory-os`；本版部署后重验 |
| Index | **last-known healthy** | SQLite 仅为可重建索引；部署后重验 |
| MemorySources | **last-known observing** | `metadata_only` 边界保留；fresh observation 待部署后重验 |
| State Overlay | **历史已部署** | 本版未部署，不能继承 runtime hash |
| Recall Plan | **last-known shadow** | 历史 observation 不证明本版 runtime adopted |
| Review Agenda v2 | **last-known apply_canary** | Owner/token 边界不因本版修复而自动变更；部署后重验 |
| Lane Status | **source repaired / runtime unverified** | Shared Operational Truth 公共投影已修；消费者与新 artifact 待部署验证 |
| SectionStatus | **implemented，未证明 Monitor adopted** | helper 已 fail-closed；真实 Monitor section 尚未统一迁移 |
| Continuity | **implemented，未证明 projection adopted** | helper/单测不等于 system prompt/overlay caller |
| Gap Note | **implemented，未证明 shadow caller** | candidate/render helper 存在；自然 observation 待证 |
| Full Monitor artifact | **source verified / runtime pending** | 真实 producer→refresh→reader→Dashboard clean-host E2E 已通过；生产 fresh artifact 待部署 |
| V2 | **last-known observing / 未解冻** | fresh Monitor 才能确认当前失败集合 |
| V3 | **准入保持阻塞** | 不因源码整改自动解冻；synthesis/outlet/expression 继续关闭 |

### 3.3 分批整改状态（不等同 runtime closure）

**第一批（基础设施收口）**：
- 🛠 Shared Operational Truth — CLI/provider 公共计数在 conflict/invalid artifact 时不再输出单边 winner；待部署验证
- 🛠 Monitor artifact envelope — v1 schema、必需 identity、future-clock fail-closed、v1 优先于 legacy；待真实 refresh
- ✅ Closure Matrix — 公共必需 surfaces 无条件执行，关键 action path 解析到真实 symbol；runtime closure 仍明确待 deployment evidence
- 🛠 pytest policy — skip allowlist 绑定 `collect/setup/call` 阶段；setup fixture 不得伪装 call skip
- 🛠 static hygiene — compileall 失败不再被降为 informational
- ⏳ 生产部署 — 尚未执行本版部署；旧 SHA-256 同步证据不能证明新代码已运行

**第二批（实现层，不等同运行采用）**：
- `timeutil.py`、`recall_golden.py`、`natural_evidence.py`、`lifecycle.py`、`session_approval.py` 均需逐项证明 caller 与行为层；其中 Natural Evidence 已复用 shared natural-row 分类，其余未接线项保持 `implemented`。

**第三批（部分接线）**：
- Natural-row 分类已接入 Natural Evidence、Exposure Rollup、V3 Seed/Wandering。
- JSONL mixed-encoding 改为逐行隔离并产出 `jsonl_invalid_utf8`，不再使主 reader 崩溃。
- Error Registry 与 Proposal/Token state machine 未证明生产 caller，保持 `implemented`。

**第四批（helper 层）**：SectionStatus 已修为缺键、类型错、数量不守恒时 fail-closed；Continuity、Gap Note、增量 Seed、Monitor Perf、Evidence Gen 未有 caller/CI/真实时延证据者均保持 `implemented`。

**第五批（安全语义修复）**：clean-host probe 已绑定 source/target 实际 import origin，并加入原子发布/失败回滚；private backup 新增独立 manifest/restore 校验；Recovery Marker 只阻止同一 terminal task 复活，不阻塞新任务；Restraint 不再接受裸 `is_owner_approval=True` 作为审批证据。源码统一测试已通过，部署验证仍待执行。

### 3.4 本版统一源码验证

- 顶层命令：`python3 scripts/memory_os_v24_final_verify.py --repo-root . --python /usr/bin/python3 --report <outside-repo-report>`
- 定向回归：`216 passed, 5 skipped`
- mount-isolated 全量：`3015 passed, 9 skipped`
- clean-copy + 临时 Git checkout 全量：`3015 passed, 9 skipped`
- import cycle、Write Surface、Static Hygiene、public checkout、Closure Matrix、wheel build：全部通过
- 验证前后 source/clean tree fingerprint 均稳定；该结论只证明源码与 clean checkout，不证明已部署、已接线或正在 observing

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

**状态**：`implemented / source_verified / deployment_pending`

### R2.1 单一运行真相

- [x] Shared Operational Truth — CLI/provider/Dashboard 公共投影与 conflict/invalid fail-closed 回归通过；生产 consumer receipt 待部署
- [x] full Monitor artifact envelope — identity/schema/future-clock/legacy precedence 与真实 producer clean-host E2E 通过；生产 fresh artifact 待部署
- [x] stale/invalid/future artifact 不得回退到更旧但“看起来更绿”的快照；反事实通过
- [x] desired-vs-observed 两平面保留

### R2.2 生产部署双 Profile

**默认生产路径：targeted deployment**（已验证 5 次）

- [x] `deploy_clean_host.py` neutral import-origin probe、read-only preflight、atomic apply、target digest postcheck 与 rollback fixture 通过
- [x] 定向部署路径：inspect → backup → sync → hash verify → commit → clone full suite → push
- [ ] clean-host fixture 在专用主机验证（不用于有定制生产主机）

### R2.3 CI 与隔离

- [x] GitHub Actions 在 push/PR 跑 mount-isolated full pytest（旧 baseline 已成功）
- [x] import cycle、write surface、static hygiene、public checkout probe、`git diff --check` 本版统一验证通过
- [x] 分类化 skip/warning 门通过 mount-isolated policy report 验证
- [x] skip allowlist 源码已绑定 `collect/setup/call` stage、nodeid、reason、bounded count

### R2.4 Closure Matrix 公共检出

- [x] 公共 contract 已补齐 15 个必需 surface
- [x] 必需 label 不再依赖私有 docs；关键 `current_action_path` 必须解析到真实 source symbol
- [x] public contract gate `status=ok` 仅表示 source/static-wiring contract 有效；`closure_status=runtime_evidence_required` 明确禁止把静态绿色升级成 runtime closure
- [x] `memory_os_closure_runtime_evidence.py` 生成 fresh-process origin、runtime tree digest、module set 与 service observation 的原子证据 artifact；待部署阶段实际生成并验证
- [x] `internal_docs_missing` 仅为 info 且核心 gate 不 skipped；public/clean-copy 反事实通过

### R2.5 Gitignored/私有资产备份

- [x] `private_backup.py` — must_backup / rebuildable / discardable 三级分类；private Markdown 默认 must_backup
- [x] source manifest、原子单文件复制、目标及 fresh restore-root 独立 hash 校验回归通过
- [ ] 必须保留的内容进入私有 remote、加密异机备份或定期 bundle

---

## R3 — 语义收敛与防漂移

**状态**：`partially_adopted`

### R3.1 时间戳语义统一

- [x] 公共实现 `plugins/memory/memory_os/timeutil.py` — `parse_utc()`、`format_utc()`、`safe_compare()`、`age_seconds()` 等
- [x] 26 个等价 fixture，覆盖 Z 后缀、时区偏移、无时区拒绝、小数秒、空值、越界
- [x] 向后兼容别名：`parse_timestamp()`、`parse_dt()`
- [ ] 剩余生产模块逐一迁移并删除 ad-hoc parser；完成前不得称“时间语义统一”

### R3.2 natural row 视图统一

- [x] 共享 natural-row API 已实现
- [ ] 已接入 Natural Evidence、Exposure Rollup、V3 Seed/Wandering；其余生产 consumer 待审计

### R3.3 错误码注册表

- [x] 12 个内置错误码与注册表 helper 已实现
- [ ] 生产 consumer 尚未统一迁移；未接线前 registry 不能作为全局错误语义证据

### R3.4 JSONL 鲁棒性与错误预算

- [x] fuzz/回归用例已扩充并通过统一执行
- [x] 主 JSONL reader 对 invalid UTF-8 逐行隔离并记录 `jsonl_invalid_utf8`

### R3.5 第二/三批 adoption ledger

- [x] `session_approval` 已通过 `system_prompt_block()` 进入正式会话提示路径
- [x] `jsonl_io` 是既有 reader 使用面的鲁棒性增强，不计作新增 runtime wiring
- [ ] `recall_golden`、`lifecycle`、`error_registry` 与 `proposal_state` 当前为 implemented/tested helper；在真实 caller 迁移前不标 wired/live

---

## R4 — 统一状态机（消除整类缺陷）

**状态**：`implemented_helpers / production_adoption_partial`

### R4.1 SectionStatus 契约

- [x] `section_status.py` typed helper 已实现
- [x] 缺失键、类型错误、分类数量不守恒和 final key 缺失均 fail-closed
- [ ] Full Monitor 各真实 section 尚未迁移到该 typed pipeline

### R4.2 Proposal / Token 状态机

- [x] `proposal_state.py` helper 与转换矩阵已实现
- [ ] OwnerActionProcessor/token ledger 未迁移；不得把 helper transition 视为生产权威状态机

### R4.3 Trigger provenance 状态机

- [x] `natural_evidence.py` 已复用 shared `natural_row.classify_row()`
- [x] 类型封闭：`natural_cron | manual | legacy_unmarked`
- [x] legacy 仅可观察，不能获得 natural credit
- [x] manual 不能通过调用参数伪造 natural envelope

---

## R5 — 认知伙伴演进主线

**状态**：`mixed: live_core + implemented_helpers + observing`

### R5.1 Continuity：持续跟随

- [x] State Overlay open-thread 去重
- [x] latest-effective current task，避免 completed/cancelled/superseded 任务复活
- [x] `continuity.py` FreshnessGrade helper 已实现
- [ ] Continuity helper 尚未证明被 system prompt/overlay 生产 caller 采用
- [x] Recovery Marker 已修为只防同一 terminal task 复活，不阻塞不同新任务
- [ ] capability map 和 material index 从空占位演进为可重建 read model；不得成为新权威源

### R5.2 Relevance：懂得轻重

- [x] Recall Plan shadow 和 metadata-only observation
- [x] authority/freshness matrix、重复和 conflict telemetry
- [x] must-recall golden set 与 Gap Note helper 已实现
- [ ] 两者尚无正式召回/会话 consumer；不得标 wired/live
- [ ] bounded apply canary 只对明确 route/profile 生效，具备即时回滚
- [ ] canary 期间比较任务完成度、Owner 重解释次数、错误唤起和重复注入，而不是只比较召回率

### R5.3 Restraint：克制和分寸

- [x] Low-clue recall 与 bounded judge availability
- [x] metadata-only MemorySources，不复制原话或私密正文
- [x] `restraint.py` helper 已实现；裸 `is_owner_approval=True` 已降为 unverified claim
- [x] helper policy 编码“模糊线索优先方向/最小澄清、连续 3 次否定后暂停 24h”
- [ ] 上述行为尚未通过主会话 caller 与真实反馈 receipt 证明
- [x] CandidateEvaluation 仅接受结构化 `ApprovalDecision` 作为 approval 证据
- [ ] Restraint/DenialTracker/SessionPriority 仍需接入真实低线索与会话路径
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

**状态**：`implemented_helpers / no_runtime_or_ci_adoption_evidence`

### R6.1 Seed Evidence 增量化

- [x] `seed_evidence_incremental.py` 与 equivalence helper 已实现
- [ ] `run_v3_seed_evidence_cycle()` 仍需接入增量 reader 并通过全量/增量生产等价验证
- [x] 保留全量重建和回放路径

### R6.2 Monitor 性能

- [x] `monitor_perf.py` helper 与 cache parity fixture 已实现
- [ ] 必须用真实 Full Monitor 路径测时；空 context-manager 单测不构成性能证据

### R6.3 稳定化证据自动生成

- [x] `evidence_gen.py` helper 已实现
- [x] 生成器不得修改 canonical memory、Owner state 或生产账本
- [ ] 自动集成到 CI；在此之前不得称“证据自动生成闭环”

---

## R7 — Hermes Community（伙伴社区生态）

**状态**：`implemented + tested + deployed; live blocked`。基础设施、标准部署、overlay 与 no-send cognitive consumer 已接入源码；本机和 2.88 文件部署/postcheck/幂等已通过。异构伙伴 `alanlive` 曾运行并完成真实 mailbox transport + pairing handshake，但因 2.88 资源压力已停用并转为 `dormant`；伙伴模型回复、fresh-session overlay、scheduler 行为和自然观察尚未完成，不能标为 `live`。

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

**2026-07-27 修复证据**：

- partner ID containment、损坏 roster、重复 ID、append-only lifecycle、异构 backend 与 budget fail-closed 已有 adversarial tests；
- shared writer 限定为 Sannai，newspaper writer 限定为可信 ingress；
- trigger 增加 max-age 与 cursor，避免旧 shared/newspaper 无限重放；
- `community_snapshot` 已进入 DynamicStateOverlay schema/renderer/builder；
- `community_cycle` 已进入现有 cognitive loop，但维持 `actual_send=false`；
- `deploy_community.py` 支持 dry-run/apply/postcheck；12 个模块写入双 runtime，shell/helper 写入各自 canonical path，共 14 个部署源项；并包含目标 runtime import、备份、完整回滚、保留 owner budget 与哈希验证；
- `memory-os-agent-os community` 只提供只读 status；伙伴 mutation 不暴露可伪造 actor 的公共 CLI；
- write-surface gate 已登记 shared/newspaper 写入面。

**最终验证证据（2026-07-27）**：

- focused community/deploy/runtime：`173 passed`；
- mount-isolated 当前工作树与 fresh patched clone：均为 `2993 passed / 6 skipped / 2 bounded third-party warnings`；
- write-surface：`155 surfaces / 0 unclassified`；
- 本机与 2.88：apply/postcheck/第二次幂等通过，目标 runtime fresh-process import 通过；
- 真实 mailbox：Sannai→alanlive delivery/handled receipt、alanlive→Sannai pairing response、官方 pairing approval 均已验证；
- 资源边界：伙伴 gateway 增加后，2.88 可选依赖安装被 SIGKILL，主机随后于 17:40:48 重启。为保护核心服务，`alanlive` service 已 disable/stop，roster lifecycle 已转为 `dormant`。因此这不是 autonomous-live 证据。

以上证明 bounded infrastructure、部署完整性、真实双向 transport 和认证握手；伙伴推理回复、长期在线和自然关系样本仍必须由后续生产 receipt 证明。

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
| P0：一个朋友的完整闭环 | P1 | `blocked` — 源码、部署、异构 profile、双向 transport 与 pairing 已验证；2.88 资源不足，伙伴已 dormant。自主模型回复、shared 自然写入和观察出口尚待 receipt |
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