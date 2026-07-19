# Hermes-Memory-OS 优化路线图 v2

> **版本**：v2.1
>
> **更新日期**：2026-07-19
>
> **运行时基线提交**：`520f1becc46e1e26a57e154b4ea5ae22a6dba9c1`
>
> **本次文档更新起点**：`a5c1c0481f886e586bf6f6f3f38997c6a6843086`
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

## 2. v1 → v2 的主要变化

v1 是 BC 修复周期结束后的代码加固清单，重点是 Monitor、JSONL、状态机和重复逻辑。v2 保留这些正确方向，但作出以下升级：

- 用当前生产基线替换 `eaf718c / 2601 passed / 13 skipped` 的历史快照；
- 区分“代码完成、已部署、运行时采用、自然观察、证据成熟、允许晋级”六个阶段；
- 将生产部署从默认完整覆盖改为“变更清单备份 + 定向同步 + 哈希验证”；
- 将 MemorySources、State Overlay、Recall Plan、Review Agenda、Lane Status 纳入一条认知伙伴主线；
- 将 V2/V3/Recall 自然证据成熟度置于任何 apply/promotion 之前；
- 用分类化 skip/warning 门替代易腐化的固定数量基线；
- 将 closure matrix 公共检出覆盖从“长线择机”提升为防回归基础设施；
- 保留时间解析、natural row、错误码与状态机收敛任务，但增加迁移兼容和行为等价要求。

---

## 3. 当前生产基线

### 3.1 源码与测试

| 项目 | 当前证据 |
|---|---|
| 生产运行时代码基线 | `520f1becc46e1e26a57e154b4ea5ae22a6dba9c1` |
| 路线图 v2.1 文档更新起点 | `a5c1c0481f886e586bf6f6f3f38997c6a6843086` |
| 完整隔离测试 | `2620 passed / 6 skipped / 4 warnings` |
| fresh-clone 完整测试 | `2620 passed / 6 skipped / 4 warnings` |
| Write Surface | `unclassified_count=0` |
| Import Cycle | `cycle_count=0` |
| Static Hygiene | PASS |
| Closure Matrix | 因公共检出缺内部 matrix/roadmap 而 skipped，仍需修复 |

完整测试必须在私有 mount namespace 中把临时目录 bind mount 到 `/root/.hermes`。仅设置临时 `HERMES_HOME` 不足以隔离生产状态。

### 3.2 生产运行状态

| 能力 | 状态 | 说明 |
|---|---|---|
| Memory-OS Provider | **active** | canonical store 为 `/root/.hermes/memory-os` |
| Index | **healthy** | SQLite 仅为可重建索引，不是权威源 |
| MemorySources | **自然观察中** | `enabled=true`、`metadata_only`、不记录 query/prompt/正文 |
| State Overlay | **已部署** | open thread 去重、latest-effective task 已修复 |
| Recall Plan | **shadow** | 已产生自然 observation；不改变 live prefetch 输出 |
| Review Agenda v2 | **apply_canary** | 仍受精确 revision/token/target 门约束 |
| Lane Status | **最小收敛完成** | Monitor/Dashboard/cron contract 已统一 |
| Full Monitor artifact | **自动刷新** | daily no-agent 原子刷新，Dashboard 使用同一 artifact |
| V2 | **观察中/未解冻** | `v2_exposure_schema_era_unhealthy` 仍是当前唯一 Monitor FAIL |
| V3 | **准入阻塞** | Seed/Wandering 继续等待自然证据；synthesis/outlet/expression 关闭 |

### 3.3 已完成的 P0–P2 闭环

- P0：恢复 metadata-only MemorySources 自然观察；不回填历史、不记录正文。
- P1：修复 State Overlay 重复 open thread 和 latest-effective task；清理测试/孤儿 cron。
- P1：增加 canonical full-Monitor artifact 原子刷新，消除 Dashboard 使用 stale 历史快照形成的多真相。
- P2：Recall facade 已穿透 Context Router apply 路径；shadow 可检索和记观察账本，但不 format、不注入 live section。
- P2：Review Agenda 进入 bounded canary；Lane Status 最小权威视图进入 Monitor/Dashboard。
- 发布证据：生产定向部署、Gateway 重载、自然记录、完整测试、fresh clone、commit、push 已完成。

上述完成项不等于 V2/V3/Recall 已毕业；自然观察窗口仍需继续积累。

---

## 4. 状态与证据模型

每个路线图条目必须分别记录以下状态，不得用一个“完成”覆盖全部阶段：

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
|---|---|
| `planned` | 只有方案，没有代码 |
| `implemented` | 代码完成，尚未部署 |
| `deployed` | 文件已同步，运行进程不一定采用 |
| `observing` | 运行时已采用，正在积累自然证据 |
| `ready_for_owner_review` | 证据门满足，等待 Owner 决策 |
| `blocked` | 被依赖、证据或治理边界阻塞 |
| `graduated` | 通过 Owner/治理门并进入目标模式 |
| `retired` | 已停用，历史只作为审计证据 |

**适用范围**：上述 8 值枚举约束的是每个具体条目（下文 R1–R6 中每条 `- [ ]`/`- [x]` 清单项及其子小节），不是 R1–R6 顶层小节标题。顶层标题的“状态”是对该阶段内多个条目的聚合概述，允许使用描述性组合标签（如 `partially_implemented` 表示阶段内部分条目已 `deployed`/`observing`、其余仍 `planned`；`foundation_deployed` 表示基础子项已 `deployed` 并进入自然观察、更高阶子项仍 `planned`）。聚合标签不得替代具体条目自身的枚举状态——排查某阶段真实进度时，以条目状态为准，顶层标签仅作导航摘要。

每项还必须写明：

```text
dependency:
owner_boundary:
rollback:
monitor_fields:
falsifier:
```

**禁止的完成信号**：本地 pytest 通过、部署脚本退出码为 0、手工补写证据、一次 fast probe PASS、配置文件中开关为 true。

---

## R1 — 自然证据与毕业门（当前最高优先级）

**状态**：`observing`

### R1.1 V2 Exposure 自然观察

**现状**：metadata-only MemorySources 已恢复，但 V2 仍未满足自然周期、观察天数和连续压力门。（V2-A/B/C/D 为 `exposure_rollup.py`/`crystallized.py`/`knob_overrides.py`/`contested_pairs.py` 中已定义的 V2 exposure 分级代号，此处沿用，不在本文重新定义。）

**继续执行**：

- [ ] 只让 `memory-os-exposure-rollup` 在计划时间自然运行；手工运行和 legacy unmarked 行永不计入 natural credit。
- [ ] 从恢复观察后的第一条非 skipped、最终版本 `natural_cron` rollup 起算新的有效窗口。
- [ ] 观察 schema-era classified ratio、attribution gaps、rollup lag、conservation failures 和连续预算压力。
- [ ] V2-A 达到自然周期门后，仅提交“是否进入 bounded canary”的 Owner review，不自动解冻 V2-C/D。
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
- [ ] 建立 must-recall golden set 和 critical-omission 检测，不以“selected 数量更多”作为质量指标。
- [ ] 验证 forced-current-source、重复抑制、旧正文 revalidation、cooldown escape、短 ID、CJK、mixed-script 和 adversarial approval identity。
- [ ] shadow 全路径保持 `retrieve_called=true`、`format_called=false`、live bytes 与关闭 facade 时完全一致。
- [ ] 在 shadow 中生成 Gap Note candidate，但只记录 metadata-only `reason_codes/counts/would_render`，不保存提示正文、不改变 live bytes。
- [ ] Gap Note 第一阶段只消费本次 Recall Plan 中的 `owner_conflict_requires_clarification` 与 `stale_task_revision`；已被权威排序解决的 lower-authority conflict 不提示。
- [ ] 普通 freshness、repeat-without-revision 时长和 attribution gap 只有在当前 selected object 具备对象级来源/revision/时间证据后才可进入 Gap Note；全局 Exposure gap 保持 Monitor-only。
- [ ] 达到零关键遗漏、权威/新鲜度无越权、自然样本充分后，才提出 bounded apply canary；Gap Note 随同该 canary 开放，不另开全局输出 Phase。

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

**状态**：`partially_implemented`

### R2.1 单一运行真相

已完成：canonical full-Monitor artifact、daily refresh、Dashboard freshness contract、core/optional/no-agent cron 分类。

后续：

- [ ] Monitor、Dashboard、status tool 和 Lane Status 使用同一 typed read model；保留 desired-vs-observed 两平面，禁止新增第三个权威账本。
- [ ] full Monitor artifact 携带明确 `generated_at`、source HEAD/runtime digest、monitor version 和 producer receipt。
- [ ] artifact 超 freshness contract 时 Dashboard 明确 stale，不回退到更旧但“看起来更绿”的快照。
- [ ] full Monitor runtime 从当前超目标状态降到目标内，不能通过跳过检查或读取 stale cache 达标。

### R2.2 生产部署双 Profile

**默认生产路径：targeted deployment**

```text
inspect
→ exact change manifest
→ backup affected files
→ targeted sync repo → runtime + plugin + scripts
→ production import/hash verification
→ separate Gateway reload boundary
→ natural live verification
→ commit
→ fresh-clone full suite
→ push last
```

**clean-host/full installer qualification** 只用于新主机或明确的兼容性验收：

- [ ] `deploy_memory_os.py plan → preflight → dry-run → apply → postcheck → report` 在 clean-host fixture/host 验证。
- [ ] 不把 clean-host WARN 描述为 production PASS。
- [ ] 不在有宿主定制的生产主机默认运行 full installer。
- [ ] 故障注入必须使用可回滚 fixture 或专用验证主机；不得临时破坏当前 canonical production ledger。

### R2.3 CI 与隔离

当前仓库没有 `.github/`，CI 尚未落地。

- [ ] GitHub Actions 在 push/PR 跑 mount-isolated full pytest。
- [ ] 同时运行 import cycle、write surface、static hygiene、public checkout probe `--strict`、`git diff --check`。
- [ ] 加 clean checkout/fresh clone job，禁止读取开发机真实 `/root/.hermes`。
- [ ] 用稳定 skip ID/reason allowlist 替代固定 skip 数；门禁为 `unknown_skip_count=0`。
- [ ] 新增未知 warning 失败；项目自有 warning 必须为 0；第三方 warning 只允许有界 allowlist。

### R2.4 Closure Matrix 公共检出

- [ ] 提供最小公开 fixture 或 public contract，使基础 closure matrix 在 GitHub checkout 中真实运行。
- [ ] 私有 matrix 只能增加覆盖，不能决定公共基础门是否执行。
- [ ] `internal_docs_missing` 可以作为信息，但不得继续让核心 gate 永久 skipped。

### R2.5 Gitignored/私有资产备份

- [ ] 明确 `docs/internal-memory-os/` 每类文件是“必须备份”还是“可重建/可丢弃”。
- [ ] 必须保留的内容进入私有 remote、加密异机备份或定期 bundle。
- [ ] 公共行为契约不得只存在于 gitignored 私有文档。

---

## R3 — 语义收敛与防漂移

**状态**：`planned`

### R3.1 时间戳语义统一

当前仍存在多份 `parse_timestamp` / `_parse_datetime` / `_parse_dt`。

先建立语义矩阵，再抽公共 helper：

| 维度 | 必须明确 |
|---|---|
| `Z` 后缀 | 接受并归一 UTC |
| naive datetime | fail-closed 或明确补 timezone，不得模块间不同 |
| 空值/非法值 | 返回 None 或 error record，按调用域定义 |
| date-only | 是否允许 |
| 微秒省略 | 排序语义一致 |
| timezone offset | 归一化后比较 |

- [ ] 公共实现放入 `plugins/memory/memory_os/timeutil.py` 或与 JSONL 契约一致的共享模块。
- [ ] 每个迁移模块先补等价 fixture，再替换调用。
- [ ] 旧格式生产行必须继续可读。
- [ ] TTL/aging 测试优先注入 clock，禁止用裸 `datetime.now()` 掩盖日期腐化。

### R3.2 natural row 视图统一

当前 natural 过滤仍分散在：

- `plugins/memory/memory_os/exposure_rollup.py`
- `plugins/memory/memory_os/v3_seed_evidence.py`
- `plugins/memory/memory_os/v3_wandering.py`
- `scripts/memory_os_monitor_dashboard_snapshot.py`

- [ ] 提供共享 `is_natural(row)`、`natural_rows(rows)`、`latest_natural_row(rows)` 和按日期 independent-LWW 视图。
- [ ] manual、legacy、natural 三值语义用常量/类型封闭。
- [ ] 生产者、准入门、Monitor 和 Dashboard 共用相同实现或版本化等价契约。
- [ ] 增加 natural→manual、manual→natural、legacy→natural、同日重复和迟到行反事实测试。

### R3.3 错误码注册表

- [ ] 将裸字符串错误码迁移为模块级常量和版本化语义注册表。
- [ ] 每个错误码记录 producer、consumer、production severity、clean-host severity 和 recoverability。
- [ ] hygiene 使用 AST/registry 检测生产裸字符串，不要求测试 fixture 和文档中的合法字面量为零。
- [ ] 未注册码进入 bounded `unknown_error_code`，不能静默成为新语义。

### R3.4 JSONL 鲁棒性与错误预算

- [ ] 对 `jsonl_io.read_jsonl_result` 及关键消费者增加 property-based/fuzz fixtures：截断行、BOM、混合编码、非对象 JSON、超长行。
- [ ] 任何输入不得导致主循环崩溃；error records 必须有界。
- [ ] 不允许“捕获异常后硬零”伪装为 collected。
- [ ] 对旧生产账本做只读兼容探针。

---

## R4 — 统一状态机（消除整类缺陷）

**状态**：`planned`

### R4.1 SectionStatus 契约

定义统一采集状态：

```text
collected | unavailable
```

不变量：

- status 永远存在；
- unavailable 时 error_code 永远非空；
- collected 时计数字段齐全；
- 缺键/错误类型必须降级 unavailable，不能读成健康零；
- suppressed errors 必须进入 Monitor 可见计数。

优先使用 typed phase API，而不是通过 AST 检查源码中 `warn.append` 的行序：

```text
CollectedSnapshot
→ ClassifiedSnapshot
→ EnvironmentEscalatedSnapshot
→ FinalMonitorSnapshot
```

后阶段 API 不允许重新写入前阶段状态。

### R4.2 Proposal / Token 状态机

- [ ] 先从生产旧行和当前代码盘点真实状态集合，不按文档猜测状态名。
- [ ] 定义 proposal 与 token 独立迁移表、terminal states 和 revoke/expire cascade。
- [ ] action-time 校验绑定 Owner 实际看到的 exact revision/content hash。
- [ ] 非法迁移记录 error record，不写新状态。
- [ ] 旧状态行具备明确迁移/兼容规则。

### R4.3 Trigger provenance 状态机

- [ ] 类型封闭：`natural_cron | manual | legacy_unmarked`。
- [ ] legacy 仅可观察，不能获得 natural credit。
- [ ] manual 不能通过调用参数伪造 natural envelope。
- [ ] trigger provenance 进入 Monitor、Dashboard 和 graduation evidence 的同一 typed view。

---

## R5 — 认知伙伴演进主线

**状态**：`foundation_deployed`

### R5.1 Continuity：持续跟随

目标：系统知道“我们现在一起在做什么”，而不只是检索历史文本。

- [x] State Overlay open-thread 去重。
- [x] latest-effective current task，避免 completed/cancelled/superseded 任务复活。
- [ ] 为 current task、open thread、recent decision 定义 freshness 和 stale degradation。
- [ ] 跨压缩、跨重启、跨 session 验证“安全恢复标记”不被后续 updater 重写成错误继续指令。
- [ ] capability map 和 material index 从空占位演进为可重建 read model；不得成为新权威源。

### R5.2 Relevance：懂得轻重

目标：记忆价值来自选择质量，而不是注入数量。

- [x] Recall Plan shadow 和 metadata-only observation。
- [x] authority/freshness matrix、重复和 conflict telemetry。
- [ ] must-recall golden set 与日常 omission detector。
- [ ] 评估 selected/suppressed 的对象级原因，不只看聚合计数。
- [ ] bounded apply canary 只对明确 route/profile 生效，具备即时回滚。
- [ ] canary 期间比较任务完成度、Owner 重解释次数、错误唤起和重复注入，而不是只比较召回率。

#### R5.2.1 Gap Note：有界的不确定性披露

**状态**：`planned`；依附 R1.2 Recall conflict/freshness shadow → apply-canary，不新增独立 Phase。

目标：系统不仅带回它知道的内容，也对与当前召回直接相关的冲突、过期和证据边界作出一行诚实说明，避免“上下文看起来完整，实际已经陈旧或互相矛盾”。

**第一阶段可直接使用的信号**：

- `owner_conflict_requires_clarification`：同一 `claim_key` 下最高权威记忆仍互相冲突；
- `stale_task_revision`：State Overlay task revision 落后于当前 effective task；
- session duplicate 只可表达“本次会话没有找到更新 revision”，不得据此声称现实长期没有变化。

**暂不进入用户提示的信号**：

- 普通 `freshness` 在 retriever producer 尚未完整提供对象级时间/来源前，只能用于 shadow 观测；
- Exposure attribution gap 当前是全局/窗口聚合指标，不代表本次 selected object 缺来源，继续保持 Monitor-only；
- “六周无新数据”等持续时长结论必须有对象级 `source_updated_at`、revision 与稳定实体绑定，不能从 session injection ledger 推断。

**建议数据流**：

```text
Recall Plan
→ build_recall_gap_note_candidate(plan)
→ structured reason_codes/counts/would_render
→ shadow metadata-only observation
→ apply-canary bounded renderer
→ 最多一行自然提示
```

**约束与验收**：

- [ ] Shadow 只记录 reason code、计数和 would-render；不持久化 claim/query/source body 或最终提示正文。
- [ ] 只有 `apply_canary` 可以渲染；shadow/off 均保持 live prefetch 字节不变。
- [ ] Gap Note 计入 Recall Facade 总预算，最多一行、最多一个合并提示，不在预算外追加。
- [ ] 不暴露 `claim_key`、`shadow_finding`、`trigger_class` 等内部机制词汇。
- [ ] 严格区分“系统没有找到近期更新”和“现实没有更新”；禁止从证据缺失推导现实事实。
- [ ] 只提示当前 query/selected set 直接相关的 gap；不得把全局 Monitor 告警机械附加到每个答案。
- [ ] lower-authority conflict 已由仲裁解决，不产生 Gap Note；只有未解决的 Owner-level conflict 才提示澄清。
- [ ] 示例文案使用确定性模板，不调用热路径 LLM、不新增采集面、不写 canonical memory。
- [ ] 不新增独立 `--explain` 开关或 shadow-finding 人类可读渲染路线；现有结构化 findings 继续作为内部审查证据。
- [ ] 覆盖无 gap、单 conflict、stale task、多 gap 合并、预算不足、shadow output-neutral、metadata-only 和 facade fail-open 反事实测试。

示例语义：

> 关于这项状态，我找到的记录可能已经过期，近期变化可能尚未进入记忆。

> 关于这一点，现有高权威记忆仍有冲突，建议以当前来源再确认一次。

### R5.3 Restraint：克制和分寸

- [x] Low-clue recall 与 bounded judge availability。
- [x] metadata-only MemorySources，不复制原话或私密正文。
- [ ] 模糊线索优先给方向或最小澄清，不强行选一个答案。
- [ ] Owner 连续否定后停止猜测；不把反复猜测当主动性。
- [ ] 不把 candidate、provisional、模型置信度或沉默当 Owner approval。
- [ ] 当前对话明确要求优先于历史 task anchor、proposal、digest 或 reflection。

### R5.4 Review Partnership：替 Owner 收敛，而不是制造 backlog

- [x] Review Agenda bounded canary。
- [x] raw → latest-effective → agenda → shown identity 对齐检查。
- [ ] 持续验证 terminal target、stale token、empty cluster、duplicate revision 不进入展示。
- [ ] 记录 Owner 对 digest 的 useful/irrelevant/too-frequent 等真实反馈。
- [ ] 减负只能通过抑制噪音，不能通过自动决定 Owner-required action。

### R5.5 Warmth & Proactivity：温度与主动性

目标：主动性来自长期理解和合适时机，不来自固定人设或强制输出。

- [ ] V3 Seed 自然证据成熟前保持 inference/output 关闭。
- [ ] Wandering 准入后允许 `entries=[]`；零想法、零表达是健康结果。
- [ ] 区分模型 requested intent 与系统 realized fate：只有真实 delivery receipt 才能记为 shared。
- [ ] 主动表达必须有 privacy boundary、frequency cap、quiet window、Owner feedback 和一键 mute/revoke。
- [ ] expression/outlet/synthesis 分阶段开放，不能因 Seed ready 一次性全部开启。
- [ ] 用 Owner 的真实感受评估“有帮助、太机械、不像我、太频繁、越过私密边界”，不让模型自评温度。

**毕业原则**：先成为可靠、安静、懂轻重的伙伴，再逐步获得主动表达能力。

---

## R6 — 性能与长期维护

**状态**：`planned`

### R6.1 Seed Evidence 增量化

- [ ] `run_v3_seed_evidence_cycle` 从全量百万行读取迁移到 offset/cursor 增量读取。
- [ ] 利用现有 `source_offset_start/end`，保留重建和回放路径。
- [ ] 用 10 万行 fixture 对比全量/增量结果完全等价，并记录耗时、峰值内存和 fallback。

### R6.2 Monitor 性能

- [ ] 为每个 section 记录 runtime budget 和 cache/read path。
- [ ] valid fresh cache 必须允许昂贵 reader 被 monkeypatch 为 raise 后仍成功；0 是合法 cached value。
- [ ] cache 与 live computation 增加 deterministic parity 测试。
- [ ] 不能通过减少检查范围、吞错误或延长 stale 窗口伪装性能改善。

### R6.3 稳定化证据自动生成

- [ ] 自动生成测试 delta、skip reason、warning classification、静态门和 staged diff digest。
- [ ] 稳定化清单只记录经工具验证的输出，避免手写基线漂移。
- [ ] 生成器不得修改 canonical memory、Owner state 或生产账本。

---

## 阶段验收矩阵

| 阶段 | 进入条件 | 退出条件 | 禁止动作 |
|---|---|---|---|
| R1 自然证据 | 运行时已采用配置/代码 | 自然窗口满足且 falsifier 未命中 | 手工补证、回填成熟度 |
| R2 运行真相 | canonical artifact 已存在 | Dashboard/Monitor/status 同源且 CI 真运行 | 新建平行权威账本 |
| R3 语义收敛 | 等价 fixture 完整 | 单一实现、旧数据兼容、消费者一致 | 机械合并不同语义 helper |
| R4 状态机 | 当前状态盘点完成 | 非法状态结构上不可写、旧行可读 | 直接重写历史账本 |
| R5 认知伙伴 | 基础 shadow/canary 已部署 | Owner 反馈与自然质量门满足 | 自动身份/关系写入、强制主动表达 |
| R6 性能 | 行为基线可复现 | 等价且资源改善有实测证据 | 用 stale cache/少检查伪装加速 |

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

## 近期执行顺序

### 现在执行

1. 保持 P0–P2 当前部署不变，积累 V2、V3 和 Recall 自然证据。
2. 建立 Recall must-recall golden set、route-by-route shadow coverage 和 Gap Note metadata-only shadow candidate。
3. 落地 GitHub Actions、mount-isolated full test 和分类化 skip/warning 门。
4. 让公共 closure matrix 不再因内部文档缺失而 skipped。
5. 清理两个项目自有 warning：ambient roots fallback 和 deprecated knob 迁移。

### 自然门满足后

6. 提交 Recall bounded apply-canary 提案；不得直接全局 apply。
7. 评估 Review Agenda canary 的 Owner 减负和错误抑制质量。
8. 评估 V3 Seed admission；仍不自动开放 synthesis/outlet/expression。

### 后续独立工作包

9. 时间戳语义矩阵与分模块迁移。
10. natural row typed view 收敛。
11. SectionStatus 与 Monitor typed pipeline。
12. Proposal/token 显式状态机。
13. Seed Evidence 增量化与 Monitor 性能优化。

---

## 最终成功标准

Memory-OS v2 路线图完成时，不以“代码更多”作为成功，而以以下结果衡量：

- Hermes 能稳定接续当前任务，极少复活旧任务或要求 Owner 重复解释；
- Recall 在不越权、不漏关键记忆的前提下减少重复和无关上下文；
- Gap Note 能在当前记忆过期或高权威结论冲突时作出一行有界提示，同时不把“没有找到更新”误说成“现实没有变化”；
- Review Surface 让 Owner 看到更少但更有效的项目；
- Monitor、Dashboard、status 和 scheduler 对运行事实没有互相矛盾的说法；
- V2/V3 的每次毕业都由自然证据和 Owner 边界驱动，不由手工回填或模型自评驱动；
- 系统可以主动，但也能长期保持安静；温度来自长期理解和真实反馈，而不是固定话术；
- Memory-OS 成为整个 Hermes 系统中负责记忆、连续性和分寸感的伙伴，而不是一个独立的记忆工具。
