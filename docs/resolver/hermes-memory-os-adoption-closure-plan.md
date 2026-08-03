# Hermes Memory-OS 接线闭环方案（Adoption Closure Plan）

> **它要回答的问题**：Owner 的原话是「每个大模块最好闭环都卡在观察了吧？」
>
> 实测结论：**不是**。R1 确实卡在观察（自然证据门，自己会走完）；R3/R4、R5.1–5.3、R6
> 卡的是**没人接线**——已实现、有测试、生产 importer 为 0 的 helper。观察会自己结束，
> 接线不会：它没有日期、没有 owner，可以永远躺着。
>
> 本文档只覆盖 R3/R4、R5.1–5.3、R6。R2 按 Owner 决定降级（3.200 作测试环境验证即可，
> 不追 2.88 全量部署）。R1 不在范围内。
>
> 立项日期：2026-08-03。基线：`5d49e1c`（生产运行 `01356df`）。

---

## 0. 结论先行

13 个待处理项按**接线之后会发生什么**分类，而不是按 R 编号：

| 类 | 含义 | 数量 | 合并即终结？ |
|---|---|---|---|
| **1** | 内部迁移，Owner 看不到任何变化 | 2 | ✅ |
| **2** | 工具/CI，零运行时风险 | 4 | ✅ |
| **3** | 改变 Owner 可见行为 → 必须走 shadow → canary → apply | 3 | ❌ 会转成观察项 |
| **4** | 建议删除而不是接线 | 4 | ✅（删除即终结） |

**headline：6 项合并即终结、4 项删除即终结，只有 3 项会进入观察窗口——而那 3 项恰好都动
recall 输出，那里的观察是正确纪律，不是拖延。**

这句话必须放在最前面而不是脚注：如果方案读起来是「接线 13 个」，一个月后其中 3 个进了
30 天窗口，同样的挫败感会原样复发，而且是这份文档造成的。

**结构性修正：把"删除"设为默认，接线需要论证。** 路线图 R6 自己写着「长期维护优先删除平行
helper，而不是继续增加第三套语义」，而这批 helper 之所以累积，正是因为"接线"被默认了。
把默认反过来，是唯一能防止复发的一条。

**已知依赖，不在本方案内**：R5.5（Warmth/Proactivity）依赖 R1 自然证据成熟，本方案全部
做完它也不会闭环。

---

## 1. 每项的最低字段要求

一个条目如果没有**具名调用点**（`file:symbol`，不是"prefetch 那条路径"），它就还没有被规划过——
这种含糊正是 backlog 形成的方式。因此每项必须写全：

具名调用点 / 类别 / Owner 会看到什么变化 / 退出条件 / 反事实测试 / 回滚方式。

---

## 2. Class 1 — 内部迁移，合并即终结

### 2.1 `timeutil` → 77 个 ad-hoc 解析点

- **具名调用点**：77 处 `datetime.fromisoformat(...)`，分布在 46 个文件
  （`cleanup.py` / `clearance_cycle.py` / `cli.py` / `crystallized.py` / `execution_gate.py` /
  `exposure_rollup.py` / `knob_overrides.py` / … 完整清单以
  `grep -rn fromisoformat --include=*.py plugins/ scripts/ | grep -v timeutil.py` 为准）。
- **类别**：1
- **Owner 可见变化**：无（前提是等价，见下）。

> ⚠️ **「行为等价」是假设，已被实测证伪，不得按机械重构推进。**
> 路线图记的是「10 处 ad-hoc parser」，那是**模块数**；实际调用点是 **77 个 / 46 文件**。
> 且 `parse_utc` 与裸 `fromisoformat` 语义不同：
>
> | 输入 | 裸 `fromisoformat` | `timeutil.parse_utc` |
> |---|---|---|
> | `2026-08-03T00:00:00`（无时区） | naive datetime | **`None`** |
> | `''` / 非法串 | 抛 `ValueError` | **`None`** |
> | `2026-08-03T00:00:00+08:00` | 保留 +08:00 | 归一化为 UTC |
>
> 直接替换会让**接受无时区戳的调用点静默跳过记录**（`None` 被当成"没有时间"），
> 以及让依赖 `ValueError` 分支的调用点改变控制流。BF 已经在 `created_at` 归并上踩过
> 微秒边界的同类坑。

- **退出条件**：77 处全部迁移；`grep` 剩余 `fromisoformat` 仅存在于 `timeutil.py`
  与生成式远端探针脚本（后者按 BL 记录属有意例外，不 import 仓库模块）。
- **反事实测试**：**每个调用点一个差分测试**——同一组输入分别喂旧解析与
  `parse_utc`，断言结果一致；不一致的站点必须显式选择 `allow_naive=True` 或保留旧行为，
  并在代码注释里写明为什么。**不允许用一句"这是重构"覆盖全部 77 处。**
- **回滚**：逐文件迁移、逐文件可回滚；不做一次性大改。
- **建议**：**接线**。但**按文件分批**，每批独立 PR，不追求一次做完。

### 2.2 `error_registry` → `build_error_record`

- **具名调用点**：`plugins/memory/memory_os/jsonl_io.py:build_error_record`
  （全项目 error_record 的唯一构造点）。
- **类别**：1
- **Owner 可见变化**：无。
- **退出条件**：`build_error_record` 产出的 error_record **字段形状逐字节不变**，
  仅增加"该 code 是否已注册"的旁路校验；monitor 的 `error_observability` 聚合口径不变。
- **反事实测试**：注册表缺失某 code 时，`build_error_record` 仍产出合法记录
  （fail-open，不得因为未注册就吞掉错误）；已注册 code 的输出与迁移前逐字段相同。
- **回滚**：单文件 revert。
- **建议**：**接线**。前提是先确认注册表是现有 code 集合的**超集**——这一步没做之前不要动。

---

## 3. Class 2 — 工具 / CI，零运行时风险

### 3.1 `seed_evidence_incremental`

- **具名调用点**：`plugins/memory/memory_os/v3_seed_evidence.py` 的读取路径。
- **类别**：2
- **关键事实**：模块自带 `verify_incremental_equivalence()`。路线图写的准入条件
  「接入生产前必须证明全量/增量等价和可回放」**是它自己能自证的**——
  所以这是一个 test-and-wire 项，**从来就不是观察项**。
- **退出条件**：等价性测试在真实 seed 数据上通过并进 CI。
- **反事实测试**：构造一份全量/增量不等价的 fixture，断言 `verify_incremental_equivalence`
  报不等价（否则这个门是摆设）。
- **回滚**：读取路径保留全量分支，一个开关切回。
- **建议**：**接线**。

### 3.2 `monitor_perf`

- **具名调用点**：`scripts/memory_os_3_200_monitor.py` 现有的运行时测量
  （已经在产出 `full_monitor_runtime_over_target` WARN，说明**存在真实消费者**）。
- **类别**：2
- **Owner 可见变化**：monitor 报告多出分段耗时；WARN 判据不变。
- **退出条件**：现有内联测量迁移到 `RuntimeBudget`/`track_runtime`，
  且 `full_monitor_runtime_over_target` 的触发条件**逐条不变**。
- **反事实测试**：迁移后同一份耗时输入仍产出相同的 WARN/不 WARN 结论。
- **回滚**：单文件 revert。
- **建议**：**接线**（把已有内联实现换成 helper，属于 R6 说的"删除平行语义"方向）。
- **注意**：`memory_os_3_200_monitor.py` 是大文件，按 CLAUDE.md 只做最小定向改动。

### 3.3 `recall_golden`

- **具名调用点**：新增 CLI 子命令（`plugins/memory/memory_os/cli.py`），可选 CI job。
- **类别**：2
- **Owner 可见变化**：无（离线评估工具，不进热路径）。
- **退出条件**：CLI 可对 golden set 跑出 hit/miss/authority 报告。
- **反事实测试**：故意劣化一条 recall 结果，断言评估分数下降。
- **回滚**：删子命令。
- **建议**：**接线**，但**优先级最低**——它是 R1.2 的度量工具，
  在 Recall Plan 还是 shadow 的阶段价值有限。

### 3.4 `evidence_gen`

- **具名调用点**：`.github/workflows/ci.yml`（路线图已核实当前未调用）。
- **类别**：2
- **退出条件**：CI 调用且保持 no-canonical-write。
- **反事实测试**：断言它在 CI 环境下不写 canonical 路径。
- **建议**：**接线**。

---

## 4. Class 3 — 改变 Owner 可见行为，会转成观察项

> 这三项接线后**不会立刻闭环**，会进入 shadow → canary → apply 阶梯。
> 这是本方案里唯一会产生新观察窗口的部分，Owner 需要预期到这一点。

### 4.1 `gap_note`

- **具名调用点**：`prefetch.py` 的 recall plan 组装处 + Recall Facade。
- **类别**：3
- **Owner 可见变化**：最终形态是 recall 里**最多一句**"我这里证据不足/可能过期"。
- **阶梯**：metadata-only shadow（只记 candidate，不渲染）→ apply-canary 才允许渲染
  （路线图 R1.2 与 Gap Note 章节已规定，模块 docstring 本身就是这条阶梯）。
- **退出条件**：shadow 期零 authority escape、零 stale-body selection 后，才提 canary。
- **反事实测试**：shadow 模式下断言 live 输出**逐字节不变**（BV 已经踩过
  `apply_canary` 静默恢复输出改写的坑，必须钉死）。
- **回滚**：kill switch，且**必须 fail-closed**（BV 教训：文件缺失不得默认 True）。
- **建议**：**接线到 shadow**。

### 4.2 `continuity`

- **具名调用点**：`prefetch.py` 上下文组装 + `state_overlay.py`。
- **类别**：3
- **关键事实**：实测 `prefetch.py` / `state_overlay.py` **没有任何 freshness/stale_after 逻辑**
  （只有注释提到 stale）。所以这**不是替换内联实现，是新增能力**——
  风险高于 timeutil/monitor_perf 那类迁移。
- **Owner 可见变化**：过期的 current task / open thread 不再被当作当前上下文呈现。
  这会**改变 Hermes 看到的东西**，即改变回答。
- **退出条件**：shadow 期证明"被判 stale 而隐藏的对象"里没有实际仍然有效的关键事实。
- **反事实测试**：构造一个刚过 `stale_after` 但仍是当前任务的对象，
  断言 shadow 记录它、但 live 输出不变。
- **回滚**：开关切回"不做 staleness 过滤"。
- **建议**：**接线到 shadow**，排在 `gap_note` 之后。

### 4.3 `restraint`

- **具名调用点**：`plugins/memory/memory_os/__init__.py`（`MemoryOSProvider` 主会话路径）
  + `low_clue_recall.py`。
- **类别**：3
- **⚠️ 规模警告：这项比另外两项贵好几倍，不能在方案里跟它们并列一行。**
  - `DenialTracker` 是**纯 dataclass，没有 store 绑定、没有持久化**。
  - 现有内联近似物 `MemoryOSProvider._consecutive_topic_switch_count` 是
    **进程内实例状态，重启即丢**。
  - 所以"接线 restraint"实际分解为：**决定跨会话拒绝状态存在哪里** →
    新增状态文件 → 写入走 StructuralWriteGate → 才谈接线 → 才谈 shadow 观察。
- **Owner 可见变化**：连续被否定 N 次后系统**停止猜测**（这正是要的效果，
  但也意味着它会在某些场合不再给答案）。
- **退出条件**：先出**状态持久化的 Owner 决策**（见第 6 节），再谈接线。
- **回滚**：开关切回"永不暂停猜测"。
- **建议**：**先拆出持久化决策，本轮不接线**。

---

## 5. Class 4 — 建议删除而不是接线（待 Owner 决策）

> 前两项按 CLAUDE.md 的明文规则不该接，理由不是"没空"，是"接了违反既定约束"。

### 5.1 `proposal_state`

- **接线意味着**：迁移 `OwnerActionProcessor` / token ledger 的状态处理，
  即**大改 `owner_actions.py`**。
- **冲突的规则**：CLAUDE.md —
  「`owner_actions.py` 和 `memory_os_3_200_monitor.py` 是大文件，**只做最小定向改动**。
  不要为了行数拆分，也不要创建 facade-only 抽象。」
- **现状**：owner action 的终态判定已由 `TERMINAL_ACTIONS_BY_TARGET_TYPE` +
  `DEFER_ACTION_TYPES` 承载并且**刚在 BY 里被扩展和测试过**，工作正常。
- **建议**：**删除**。`ProposalStage`/`TokenStage` 是第三套语义，
  正是 R6 说要优先删掉的"平行 helper"。

### 5.2 `SectionStatus`

- **接线意味着**：统一迁移 Full Monitor 的 section 状态 → 大改
  `memory_os_3_200_monitor.py`。
- **冲突的规则**：同上。
- **建议**：**删除**。

### 5.3 `natural_evidence`

- **实测**：生产的 natural-row 门控**已经在跑，而且不经过这个模块**——
  走的是 `execution_gate.resolve_trigger_class()`，由 `exposure_rollup.py:111` 调用
  （`v3_seed_evidence.py` 共用同一个）。BG 那轮把 trigger_class 判定抽成
  `resolve_trigger_class()` 正是为了防漂移。
- **也就是说**：`natural_evidence` 是一套**已经有生产替代实现**的平行语义，
  接线等于把跑得好好的东西换成第二套。
- **建议**：**删除**。这是 R6「优先删除平行 helper」最典型的一例。

### 5.4 `lifecycle`（`plugins/memory/memory_os/lifecycle.py`）

- **实测**：仓库里有**两个** `lifecycle.py`。`plugins/system/lifecycle.py`
  **已接线**（`plugins/system/__init__.py:5` 导入 `DoctorReport` / `ModuleLifecycle` /
  `ModuleStatus`）；而 `plugins/memory/memory_os/lifecycle.py` 的生产 importer 是 **0**。
- **注意**：本项在初次统计时被误记为"有 1 个 importer"，实为 grep 命中了同名的另一个模块。
  **同名模块使 caller 统计天然容易出错**，这本身就是删除它的理由之一。
- **建议**：**删除**。已经有一个在用的同名同职责模块。

---

## 6. 需要 Owner 拍板的三件事

1. **Class 4 四项删还是留？**（建议：删。留着就是继续养第三套语义。
   其中 `natural_evidence` 与 `lifecycle` 更明确——它们各自都**已经有一个在生产里跑的替代实现**。）
2. **`restraint` 的跨会话拒绝状态存在哪里？**
   候选：`<hermes_home>/memory-os/system/` 下新增状态文件（file-first，与现有约定一致）。
   这个决定不做，restraint 无法开始。
3. **Class 3 三项要不要现在就开 shadow？**
   开了就会产生新的观察窗口。如果现在不想再多一个"在观察"的东西，
   可以只做 Class 1/2（6 项，全部合并即终结），把 Class 3 押后。

---

## 7. 建议执行顺序

前提：**每一项都是独立 PR，都要过全量测试 + 四道静态门 + 反事实测试**
（CLAUDE.md 的 definition of done 不因为"这是接线工作"而降级）。

| 批次 | 内容 | 为什么这个顺序 |
|---|---|---|
| **A** | `error_registry`、`monitor_perf`、`seed_evidence_incremental`、`evidence_gen` | 零 Owner 可见风险，合并即终结，先把"能关的关掉" |
| **B** | `timeutil` 分文件迁移（每批一个 PR，带差分测试） | 77 点最大但可切片；错误会被差分测试当场抓住 |
| **C** | Class 4 四项执行删除（若 Owner 同意） | 减少语义面，越早越省后续维护；`natural_evidence`/`lifecycle` 各自已有生产替代实现 |
| **D** | `gap_note` → shadow，`continuity` → shadow | 开始产生观察数据 |
| **E** | `restraint`（持久化决策做完之后） | 依赖第 6 节第 2 项 |
| **F** | `recall_golden` | Recall Plan 仍在 shadow 时价值有限 |

做完 A+B+C：**10 项终结，路线图上"没接线"这一类清零**，剩下的只有 D/E 产生的
3 个真观察项 + R1。那时"卡在观察"才是对整个系统的准确描述。

---

## 8. 复发防护

1. **删除是默认，接线要论证。** 新 helper 进仓库时，PR 必须写明具名生产调用点，
   或者标注"仅工具/仅测试"并接受它随时可能被删。
2. **"已实现待接线"不是一个允许长期存在的状态。** 任何 helper 在合并后
   N 个周期仍无生产 importer，进入 Class 4 复审。
3. **测试数不等于进展。** 本轮实测：测试数 2561 → 3159，而这批模块
   （1722 行以上、全部有测试）生产 importer 全是 0。写 helper + 写测试在计分板上是可见进展，
   接线之前对 Owner 价值是 0。

---

## 9. 本文档的事实基础（实测，非文档转述）

- 生产 importer 实测（`grep` 生产代码，排除测试与模块自身）：
  `continuity` 0、`restraint` 0、`recall_golden` 0、`gap_note` 0、`error_registry` 0、
  `monitor_perf` 0、`proposal_state` 0、`seed_evidence_incremental` 0、`natural_evidence` 0、
  `lifecycle`（memory_os 的那个）0。合计 **1722 行以上、全部有测试、零生产调用**。
- `fromisoformat` 调用点实测：**77 处 / 46 文件**（路线图记的"10 处"是模块数）。
- `parse_utc` 与裸 `fromisoformat` 的语义差异：实测三类不等价（见 2.1 表）。
- `prefetch.py` / `state_overlay.py` 无 freshness/stale_after 实现 → `continuity` 属新增能力。
- `DenialTracker` 无持久化；内联近似物为 `MemoryOSProvider._consecutive_topic_switch_count`
  （进程内状态，重启即丢）。
- `restraint` 已 import `timeutil` —— helper 相互调用、无一够到生产，
  这个模式本身就是问题的证据。
- `natural_evidence` 的生产替代实现确认存在：`execution_gate.resolve_trigger_class()`，
  由 `exposure_rollup.py:111` 调用。
- `lifecycle` 有同名双模块：`plugins/system/lifecycle.py`（已接线）与
  `plugins/memory/memory_os/lifecycle.py`（零 importer）。初次统计曾因此误报，
  已用 grep 复核纠正——与 memory 里记的"CodeGraph 边要 grep 复核"同一类教训。

---

## 10. 本文件的跟踪状态（务必先读）

`.gitignore:43` 有 `docs/resolver/*`，因此**本目录下的新文件默认不被 git 跟踪**。
同目录的路线图与稳定化清单是当初被显式 `git add -f` 才纳入跟踪的——
稳定化清单的文件头明确记录了它"曾随目录清空而丢失，自此从 gitignore 中移出、纳入跟踪"。

本文件首次提交时正是踩了同一个坑：`git add -A` 静默跳过它，只有路线图那条指针进了 main，
导致指针悬空、文档随 worktree 删除而丢失，本文件为**重建版**。

因此：**要长期保留本文件，必须**
`git add -f docs/resolver/hermes-memory-os-adoption-closure-plan.md`。
在这个仓库里，新增 `docs/resolver/` 文档时永远先跑一次
`git check-ignore -v <新文件名>`（对**新文件名**，不是对同目录已跟踪的旧文件——
后者已被跟踪，检查它得不到有意义的结论）。
