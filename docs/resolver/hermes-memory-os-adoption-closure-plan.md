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

| 类 | 含义 | 数量 | 状态 |
|---|---|---|---|
| **1** | 内部迁移（`timeutil`，已缩小范围） | 1 | 待做 |
| **2** | 工具/CI（`recall_golden`） | 1 | 待做，优先级最低 |
| **3** | 直接实现（Owner 决定不开观察窗口） | 3 | 待做，**这才是有产品价值的真活** |
| **4** | 删除 | **8** | ✅ 全部已删 |

**headline（2026-08-03 实测修正）：13 项里 **8 项是删除**，真正要做的只剩
`timeutil` 迁移 + 3 项功能实现 + 1 个低优先级工具。**

> ⚠️ **本节初版的分类是错的，修正过程本身是这份文档最重要的教训。**
> 初版说「6 项合并即终结」，是**看模块接口 + 查有没有人 import** 归的类，
> **没有读实现**。逐项读实现后，原 Class 1/2 的 6 项里有 **4 项当场塌成删除**：
>
> | 模块 | 接口看起来 | 实现真相 |
> |---|---|---|
> | `error_registry` | 接到 `build_error_record` 即可 | 注册表运行时为空（`register_error_code` 从未被调用）；severity 已在每个调用点传；`clean_host_severity` 与 monitor 的 `CLEAN_HOST_WARN_CLASSIFICATIONS` 重复；两处 code 是 `type(exc).__name__` 动态生成，无法预注册 |
> | `monitor_perf` | 迁移 monitor 的运行时测量 | **够不着要测的东西**：耗时全在远端探针里，那是自包含 raw 字符串脚本、按 BL 记录有意不 import 仓库模块。本地接上只等于把 `time.monotonic()` 换成 `perf_counter()` |
> | `seed_evidence_incremental` | 增量读，避免全量扫描 | **它不是增量的**：先 `read_jsonl(path)` 读整个文件再切片，I/O 与全量读相同；且消费方 `v3_seed_evidence.py:158` 需要全部记录 |
> | `evidence_gen` | 接进 CI | `build_test_delta` 接的是**已解析好的字典**，不解析 pytest 输出。缺的解析器才是真正的活 |
>
> **推论(已写入第 8 节)**：一个从来没被调用过的 helper，等于**没有任何人验证过它的前提**——
> 它自己的测试只验证它的内部逻辑对不对，不验证它能不能用在这个架构上。
> 因此默认预期应是"**大概率不适用**"，只有读实现才能推翻。

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
- **范围已缩小（2026-08-03 抽样 8 处后）**：并非 77 处一视同仁。
  - **严格改进、应迁移**：形如 `.replace("Z","+00:00")` 后 `fromisoformat`
    （`clearance_cycle.py:178/818/854`）与 `.astimezone(timezone.utc)`
    （`cleanup.py:602`）——`parse_utc` 内部做的正是这两件事，迁移后行为一致且更短。
  - **必须单独处理**：用户输入的时间参数（`cli.py:930/931` 的 `--since`/`--until`），
    用户合法地会输入无时区值，`parse_utc` 会返回 `None`。这些站点要么显式
    `allow_naive=True`，要么保留原实现，并在注释写明原因。

> **批次 B 执行结果（2026-08-03）——范围比预想更小，但查出一个真 bug。**
>
> 差分测试（先测、后改）发现 `parse_utc` 与它要替换的内联实现有 **4 处分歧**，其中一处是崩溃级：
>
> | 输入 | 内联实现（生产在跑） | 修复前的 `parse_utc(allow_naive=True)` |
> |---|---|---|
> | `2026-08-03T04:05:06`（无时区） | tz-aware UTC | **naive** ← 与 aware 相减即 `TypeError` |
> | `2026-08-03`（仅日期） | 午夜 UTC | `None` |
> | `2026-08-03T04:05`（无秒） | 正常 | `None` |
> | `2026-08-03 04:05:06`（空格分隔） | tz-aware | naive |
>
> **裁定**：`allow_naive=True` 返回 naive 是 `timeutil` 的**契约违反**——docstring 明写
> 「a timezone-aware datetime in UTC」，且所有内联副本都强制转 UTC。已修复：无偏移且
> `allow_naive=True` 时附加 `timezone.utc`。**正则的严格性保留不放宽**（拒绝仅日期/无秒
> 是治理时间戳解析器应有的严格）。
>
> 既有测试 `test_naive_allowed` 原本断言 `tzinfo is None`——**它钉住的正是这个 bug**。
> 这是第 8.0 条的活标本：一个从未被调用的 helper，它的测试只验证它自己的假设。已刻意更新。
>
> **⚠️ 常设隐患（独立于本次迁移，供后续会话）**：`parse_utc` 拒绝仅日期与无秒时间戳。
> 任何目前接受这两种格式的调用点，一旦迁移过来就会**静默开始丢记录**。
> 已用 `test_parse_utc_is_deliberately_stricter_than_fromisoformat` 钉死为契约。
>
> **实际迁移范围：31 处里只迁了 1 处。** 按裁定「逐站点追溯输入是否机器生成，追不到就踢出」：
> - ✅ `execution_gate.py:_record_created_at` —— `created_at` 由本模块自己在 478/517 行
>   以 `now.isoformat().replace("+00:00","Z")` 写入，**完整追溯到机器写入者**，已迁移。
> - ❌ `v3_retention.py:_parse_datetime`（`item["expires_at"]`）、
>   `task_state.py:_parse_timestamp`（`record["updated_at"|"created_at"]`）——
>   本轮**追不到确定的写入者**，按裁定踢出本批。不是"不能迁"，是"没验证过就不迁"。
> - 其余 28 处出于以下原因不在范围内：`try` 包住的不止解析、或接受用户输入、或会撞上严格性分歧。
>   **「迁完 31 处」不是目标。**

- **建议**：**先迁移"严格改进"子集**，按文件分批、每批独立 PR 带差分测试；
  用户输入类站点单独一批并逐个判断。不追求 77 处全清。

### 2.2 ~~`error_registry`~~ → 已删除（见 5.5）

见第 5.5 节的删除依据。

---

## 3. Class 2 — 工具 / CI，零运行时风险

### ~~`seed_evidence_incremental`~~ → 已删除（见 5.6）  <!-- was 3.1 `seed_evidence_incremental` -->

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

### ~~`monitor_perf`~~ → 已删除（见 5.7）  <!-- was 3.2 `monitor_perf` -->

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
- **建议（2026-08-03 修订）**：**倾向删除，而不是无限期排队。**
  一个没有 CI 消费者的 golden-set 评估器，正是本轮已经删掉四次的那个模式
  （`evidence_gen` 同型：工具建好了、没有调用方、也没人打算建调用方）。
  与其永远挂在"批次 F"，不如按删除默认处理；真需要时再连同 CI job 一起作为新功能建。
  **待 Owner 一句话确认。**

> **✅ 裁决已改为「保留并接线」，已执行（2026-08-04）。**
>
> 推翻"倾向删除"的理由不是"以后可能有用"，而是 Owner 提出「很多关键事实没存入记忆，
> 导致召回漏掉了一些」之后，**它成了唯一能度量那件事的仪器**：捕获链的任何修复都需要
> "哪些事实该被召回、实际召回了没有"的可复跑前后对比，而这正是它的功能。
> 上一条自己写着"真需要时再连同 CI job 一起作为新功能建"——这就是那个"真需要"。
>
> 已接线：`run_golden_set_report()` + CLI 子命令 `recall-golden run`
> + 一份 seed golden set（含两条 >140 字截断的 before/after 标记项，
> **刻意标注为"今天预期 FAIL"**，是捕获修复的前后基准）。
>
> **⚠️ 但本节原写的退出条件「跑出 hit/miss/authority 报告」只满足三分之二。**
> 接线时读实现查出 **authority 维度是死代码**：
> - `evaluate_recall` 里 `matched_source_ref = expected.source_ref if matched else ""`
>   ——从**期望值**抄的，不是从实际匹配推导，于是
>   `classify_evaluation_item` 的 `source_authority_issue` 分支**从真实输出永远不可达**
>   （只有手搓 `RecallEvaluationItem` 的单测能进去）。
> - `matched_authority` 声明了但 `evaluate_recall` 从不赋值，恒为 `""`。
> - `GoldenResult.authority_class` / `min_score` 声明在 schema 里但评估器从不读。
> - `classify_evaluation_item` docstring 列的 `"context_insufficient"` 无任何分支返回。
>
> **hit/miss 那一半是真的**（反事实实测：经真实生产写入路径建一条 crystallized 记录 →
> `recall_rate == 1.0`，删掉记录文件 → 降为 `0.0`；未删时观察到 `assert 1 == 0`）。
> 本轮**只接线、不修这些死代码**（超出"给它一个消费者"的范围），已登记为稳定化清单待办。
> 因此**不得据此声称退出条件已满足**——authority 那一项仍未达标。

### ~~`evidence_gen`~~ → 已删除（见 5.8）  <!-- was 3.4 `evidence_gen` -->

- **具名调用点**：`.github/workflows/ci.yml`（路线图已核实当前未调用）。
- **类别**：2
- **退出条件**：CI 调用且保持 no-canonical-write。
- **反事实测试**：断言它在 CI 环境下不写 canonical 路径。
- **建议**：**接线**。

---

## 4. Class 3 — 改变 Owner 可见行为，会转成观察项

> 这三项接线后**不会立刻闭环**，会进入 shadow → canary → apply 阶梯。
> 这是本方案里唯一会产生新观察窗口的部分，Owner 需要预期到这一点。

> **实现层核实结论（2026-08-03，扫描后）**：三项**全部可行**，且比原估计更清楚：
> `gap_note` 输入只是普通 dict（`plan["findings"][].code`），不需要 prefetch 重建结构；
> `restraint` **比原估计便宜**——否定信号已存在（`low_clue_recall.py:593` 的
> `_recent_correction_signal()` 已在 live recall 里驱动 `correction_active`），
> 缺的只是把它接到 `DenialTracker` 并持久化；
> `continuity` 中等成本——overlay 对象已带时间戳（`state_overlay.py:281` 的
> `last_updated`/`ts`），缺的是到 `ContinuityObject` 的字段映射，不是从头产出数据。

### 4.1 `gap_note` — **被上游阻塞，须排在 `continuity` 之后（2026-08-03 实测）**

> **前置检查结果：前提不成立，但不是删除——是顺序排反了。**
> - `prefetch.py` **根本没有 `findings` 结构**。
> - 全仓**没有任何生产代码**产出 `owner_conflict_requires_clarification`
>   或 `stale_task_revision` —— 而 `ELIGIBLE_REASON_CODES` 只认这两个。
>
> 也就是说 `gap_note` 是个**渲染器**，它要渲染的信号还没人产出。
> 照原计划先接它，等于接一个永远渲染不出东西的组件（与 `evidence_gen`
> 「已建好的那 20% 最容易的部分」同型）。
>
> **解开方式**：`stale_task_revision` 正是 4.2 的 `continuity` 要产出的东西。
> 因此顺序改为 **`continuity` → `gap_note`**。
> `owner_conflict_requires_clarification` 需要冲突检测，本轮无生产者，
> 可先只支持 stale 一路，冲突一路留待日后。

### 4.1b `gap_note` 原始条目（存档）

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

### 4.2 `continuity` — **设计已定案（2026-08-03）：只分级披露，不做过滤**

> **裁定**：`continuity` **计算新鲜度等级并把它披露出去**；
> **既有的 `cutoff`/`recency` 过滤器一律不动**
> （`state_overlay.py:264,286` 的 7 天窗口、`prefetch.py:2002,2019` 的 48 小时窗口）。
> `DEFAULT_STALE_AFTER` 从"闸门"降格为"**分级刻度**"。
>
> **⚠️ 更正本文档 4.2 初版的一处错误说法。** 初版写「`prefetch.py`/`state_overlay.py`
> 没有任何 freshness/stale_after 逻辑，所以这是新增能力」——**这是错的**。
> 生产**早有**时效过滤，只是写作 `cutoff`/`recency` 而非 `stale_after`，
> 初版的 grep 因此漏掉了。`continuity` 因而是**替换/补充既有逻辑**，不是新增能力。
>
> **为什么不做过滤（三条，任何一条都足够）：**
> 1. **两套阈值模型不兼容，而生产那套是经过实测的。** `DEFAULT_STALE_AFTER` 的
>    1 小时 / 2 小时是按"会话内"模型写的，本系统不用这个模型。
>    把 open_thread 的 7 天换成 2 小时是 **84 倍的上下文缩减**，没有人要求过；
>    叠加在既有过滤之上也只会更少。两种做法都等于拿**未经验证的常量**改线上行为。
> 2. **它把 `gap_note` 从死项变成可用。** `continuity` 产出 `stale_task_revision`，
>    正是 `gap_note` 缺的那个上游生产者。分级而非过滤，把两个卡住的条目接成一条能跑的链。
> 3. **它符合本项目一贯的治理立场**——让事情**可见**，而不是**静默丢弃**。
>    过滤掉的上下文不留任何痕迹供 Owner 检查；一个等级 + 一行披露留得下。
>
> **这不是把"观察"偷偷放回来。** Owner 否决的是**等待窗口**（"等够 N 天才准上线"）。
> 分级并经 `gap_note` 呈现给 Owner 的组件，**第一天就是 live 且起作用的**。
> 与 `gap_note` 那条「kill switch ≠ 观察门」是同一个区分。
>
> **给后续会话的告诫**：不要"顺手把活干完"去接上过滤器。上面三条就是不接的理由。

**实现时必须处理的四个静默失败陷阱：**

1. **naive 时间戳会让整个功能空转。** `age_seconds()` 调 `parse_utc` 用默认
   `allow_naive=False`，naive 输入 → `None` → 永远 UNKNOWN → 永远不 stale。
   须逐调用点决定是否传 `allow_naive=True`（该参数的契约刚在批次 B 修好），
   并**为 UNKNOWN 路径写测试**，否则静默空转就藏在这里。
2. **`current_task_is_stale()` 在 `current_task is None` 时返回 `True`**——
   **"不存在"不等于"过期"**。直接喂给披露层，Owner 每开一个新会话都会看到
   "你的任务信息可能已过期"。None 必须按 UNKNOWN 处理。
3. **诊断记录是一次自动 JSONL 写入**，必须走 StructuralWriteGate，
   否则 `write_surface_check` 会以 `unclassified_count > 0` 失败。
4. **目标反事实（一条测试钉死整个设计决策）**：
   一个已过 `stale_after` 的对象**被判为 STALE**，
   **且 live prefetch 输出逐字节不变**。

> **批次 C 执行结果（2026-08-04，已实现）——三处方案与实测不符，逐条记明。**
>
> **(1) 数据源不是 overlay。** 方案 4.2 前言写「overlay 对象已带时间戳
> （`state_overlay.py:281` 的 `last_updated`/`ts`）」。实测：`OverlayEntry` 只有
> `text`/`source`/`source_kind`，**没有任何时间字段**。281 行读到的候选时间戳在
> `_read_open_threads_from_candidates` 内部用完即丢（296 行只返回
> `(summary, candidate_id)`）。**overlay 投影里没有任何可分级的东西。**
> 真正的源是 `task_state.read_effective_current_task()`：它投影出 `revision`
> （账本行号即修订号）与 `source_at`，且 `created_at` 由
> `_active_task_anchor_record` 以 `.isoformat().replace("+00:00","Z")` 机器写入，
> **写入者可完整追溯**（正是批次 B 裁定要求的条件）。
> `stale_task_revision` 这个码名与它的 `revision` 字段本来就是对应的。
>
> **(2) trap #3 的「必须走 StructuralWriteGate」在这条路径上做不到，已改为 allowlist 登记。**
> `append_governed_jsonl` 要求一个有效且未使用的 ExecutionGate permit，而 prefetch 是
> Hermes **每轮**调用的热路径，**不存在 envelope** → 每次调用都 `StoreError`
> → 诊断记录永远写不出来。那正是 trap #3 想防的静默失败，照字面执行会亲手制造它。
> 备选方案（改从 heartbeat 写，那里有 envelope）会丢掉「本次 recall 看到了什么」这个
> 唯一让它有诊断价值的性质。
> **实际做法**：`append_jsonl_locked` + 在 `ALLOWED_WRITE_SURFACES` 登记为
> `report_only_continuity_freshness`，与同文件里两个既有的 report-only shadow 写
> （`_record_substrate_shadow_recall`、`_record_graph_layer_shadow`）**同一契约**。
> trap #3 的**目的**（`unclassified_count=0`）由此满足，实测 write surface 门
> `status=pass / unclassified_count=0`；删掉这条登记则该门立刻 FAIL（已实测）。
> **记在这里而不只是记在代码注释里**：本项目一贯把「文档说 A、代码做 B」当缺陷。
>
> **(3) 只做 `current_task`，open_threads 明确不在 C 范围内。**
> 理由不是没空：open-thread 的时间戳按 (1) 在 overlay 里根本不存在，
> 而候选的 7 天窗口按本节裁定**不许动**。因此 `active_open_threads()` /
> `stale_open_threads()` 在 C 之后**仍然是零生产调用**——按第 8 节这正是要防的模式，
> 所以在此显式登记原因，而不是让它们静默地继续躺着。
> 若日后要分级 open_threads，前置工作是让 `OverlayEntry` 携带时间戳，那是独立一项。
>
> **另外两条实现期决定：**
>
> - **账本记录状态迁移，不记轮次。** 反向评审时发现：`current_task` 的 `stale_after`
>   是 1 小时，而任务锚点**只在意图切换时重写**（defer/resume/cancel/新任务），
>   于是同一个任务连做超过 1 小时后，**每一轮 prefetch 都会追加一行**——热路径上无界增长。
>   改为按 `(session_id, object_id, revision, grade, unknown_count)` 签名去重：
>   一个状态一行。`session_id` 刻意进签名——新会话看到同一个过期对象是新事实，
>   也是「答案变差时定位到哪个会话」的抓手。
> - **`max_age_hours=0` 必须硬编码。** 该参数**本身就是一个生产时效过滤器**：任何正值
>   都会让读取对过期锚点返回 `None`，于是分级只能看到已经通过过滤的东西、永远无法与它
>   不一致，整条 lane 变成装饰。已用测试在调用边界上断言 `max_age_hours == 0`，
>   而不是只靠"分级结果对了"间接推断。
>
> **与 R1.2 的关系（配套要求）**：C **不违反** R1.2——R1.2 要求
> 「保持 live output 不变」，而 C 正是 report-only、live 输出逐字节不变。
> 需要修订 R1.2 的是 **D**（gap_note 要往 live 输出加一句话且不开 shadow 窗口）。
> 已在路线图 R1.2 就地标注该修订待 D 落地。
>
> **D 的接点已探明**：`recall_facade.py:116` 的 `build_recall_plan(...,
> current_task_revision=task_revision)` **已经**把当前任务修订号带进 recall plan
> （由 `prefetch.py:634` 以同一个 `max_age_hours=0` 读出），但那个 plan
> **没有 `findings` 键**（它的键是 `suppressed` / `shadow_findings` / `conflicts`）。
> D 的活就是把 C 产出的 finding 挂进去让 gap_note 渲染，不需要新建结构。
>
> ### ⚠️ 更正 4.1 的一处事实错误（2026-08-04 完成前复核查出）
>
> **4.1 写的「全仓没有任何生产代码产出 `owner_conflict_requires_clarification`
> 或 `stale_task_revision`」——后半句是错的。** `recall_arbitration.py:86` 就在产出
> `stale_task_revision`。本节初稿与批次 C 的 commit message、PR 正文、两处 docstring
> 都原样沿用了这个错误说法，均已更正。
>
> **正确说法需要四个限定，缺一个都会让后来者误判**（一个 grep 这个码的人会先撞见 86 行）：
>
> 1. 它以 **`"reason"`** 为键，而 `gap_note.build_gap_note_candidate` 读 **`"code"`**
>    —— **结构上** gap_note 看不见它，与它是否运行无关。
> 2. 语义不同：判的是 STATE_OVERLAY 对象的 `task_revision` 与当前修订号**不相等**
>    （identity 比对），**不是年龄**。
> 3. 默认配置下**休眠**：`config.py:53` 的 `recall_arbitration.mode = "off"`
>    → facade 不构造 → `build_recall_plan` 从不运行。
> 4. 它的用途是 **suppression**（丢弃该对象）——**正是本节裁定为 continuity 否决的行为**。
>
> 因此两者互补而非重复：**arbitration 按修订号相等性抑制，continuity 按年龄披露。**
> **这给 D 增加了一个必须显式做的决定**：gap_note 的同名码此后有两个可能来源、
> 语义不同、字段名不同——D 必须选，不能假设只有一个。
>
> **并因此纠正本节前文的一处遗漏**：生产时效过滤器不止两个。除 7 天与 48 小时窗口外，
> `recall_arbitration` 的 freshness guard 是**第三个**（默认 `shadow`；`mode=off` 时休眠）。
> "不动既有过滤器"这条裁定同样覆盖它。

### 4.2b `continuity` 原始条目（存档）

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

## 5. Class 4 — 删除（Owner 已拍板：四项直接删，**已执行**）

> Owner 决定（2026-08-03）：**四项直接删**。已执行——4 个模块 + 4 个专属测试文件，
> 共 1119 行源码移除；删除前实测四者的非测试 importer 均为 0，
> 其余测试文件里的同名出现全部核实为巧合（局部变量 / 测试方法名 / JSON 字段 / 配置键），
> 无一是模块导入。
>
> 前两项按 CLAUDE.md 的明文规则本来就不该接，理由不是"没空"，是"接了违反既定约束"。

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

### 5.5 `error_registry` — 删除（原 Class 1，实测重分类）

四条独立理由，任何一条都足够：注册表运行时为空（`register_error_code` 从未被调用，
方案原本写的前提「注册表须是现有 code 集合的超集」不是未满足而是**反过来了**）；
`severity`/`recoverable` 已在每个调用点传递，注册表要么重复它们（两个真相来源 → 漂移，
正是 BR 在 `classify_hermes_cron_jobs` 三份拷贝上踩的坑）要么取代它们（24 处重构，
远超 Class 1「Owner 无可见变化」）；`clean_host_severity` 与
`CLEAN_HOST_WARN_CLASSIFICATIONS` 重复且后者生产在用；两处 code 为
`type(exc).__name__` 动态生成，集合开放、无法预注册。

### 5.6 `seed_evidence_incremental` — 删除（原 Class 2）

**它不是增量的**：`read_seed_evidence_incremental()` 先 `read_jsonl(path)` 读整个文件
再切片，I/O 成本与全量读相同。且预期消费方 `v3_seed_evidence.py:158` 拿到 `existing`
后要 `existing + [daily_record]` 建整体快照，**需要全部记录**，没有局部读的用武之地。
模块自带的 `verify_incremental_equivalence()` 能自证等价——因为两边本来就是同一个全量读。

### 5.7 `monitor_perf` — 删除（原 Class 2）

**够不着它要测的东西。** 全部采集在 `_run_probe(host, _remote_probe_script(...))` 一次调用里，
而 `_remote_probe_script()` 返回的是 **raw 字符串字面量**——一个自包含、只 import 标准库的
生成式脚本，按 BL 记录**有意不 import 仓库模块**。因此 `monitor_perf` 无法进入真正耗时的地方；
在本地包住整个调用，只等于把 `time.monotonic()` 换成 `perf_counter()`，零收益。
分段计时若要做，应当在探针字符串内部用标准库实现，与本模块无关。

### 5.8 `evidence_gen` — 删除（原 Class 2）

`build_test_delta(before, after)` 接收的是**已解析好的字典**（含 `total`/`failed`/`passed`），
本身只是 20 行集合运算；它**不解析 pytest 输出**。要进 CI 必须先写一个 pytest 输出解析器——
那才是真正的工作量，而本模块是其中最容易的一小部分。现有做法（稳定化清单每轮手写测试增量）
一直有效。属"新功能"而非"接线"，按删除默认处理。

---

## 6. Owner 决策（2026-08-03，已拍板）

1. **Class 4 四项 → 直接删除。** ✅ 已执行（见第 5 节）。
2. **`restraint` 跨会话拒绝状态 → 存文件，不进记忆库的表。**
   Owner 曾提议在现有记忆库里加一张表；**不采用**，理由是硬规则而非偏好：
   CLAUDE.md 明确「canonical 数据是 JSONL，**SQLite 索引可重建、永远不是真相来源**」。
   拒绝状态是 **Owner 的决定**而非派生数据，放进可重建索引里，一次 rebuild 就抹掉——
   这与 BY 里 session_mirror 拒绝**刻意不写进 SessionMirror state** 是同一个理由
   （`_rebuild_state()` 从事件重建，会让被拒会话复活）。
   落点：`<hermes_home>/memory-os/system/restraint_denials.json`，写入走 StructuralWriteGate，
   与 `cron_lane_disabled.json` 同等待遇。
3. **Class 3 三项 → 不开观察窗口，直接实现。**
   Owner 要的是本轮闭环。需要区分两件被叫作同一个名字的东西：
   **观察窗口**（等够 N 天才准上线）——**取消**；
   **默认可关的开关 + 回滚能力**——**保留**，它不需要等待，只是出事能立刻关掉。

   三项风险不同，实现时按此对待：

   | | 性质 | 直接上线的风险 |
   |---|---|---|
   | `gap_note` | **加**一句不确定性披露 | 低——加了什么一眼可见 |
   | `restraint` | 连续被否定后**停止猜测** | 中——Owner 会立刻察觉 |
   | `continuity` | **隐藏**过期上下文 | **高——它是减法，悄悄少给的东西看不见** |

   因此 `continuity` 必须附带**「本次隐藏了什么」的可查记录**。
   这不是观察门，是诊断能力：答案变差时能当场定位，否则只会表现为"Hermes 好像变笨了"。

   **配套要求**：路线图 R1.2 明文规定 Recall Plan 走 shadow→canary。直接实现就必须
   同步修订 R1.2，否则文档说 A、代码做 B——本项目一贯把这种分叉当缺陷。

---

## 6b. 原始待决问题（存档）

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

| 批次 | 内容 | 状态 |
|---|---|---|
| **A** | 删除 `error_registry`、`monitor_perf`、`seed_evidence_incremental`、`evidence_gen` | ✅ 已合并（PR #15，原计划是接线这四项，实测后全部改为删除） |
| **B** | `timeutil`：修 `allow_naive` 契约违反 + 迁移 1 处已追溯站点 | ✅ 已合并（PR #16，`09c9629`；31 处里只迁 1 处，其余按裁定不迁） |
| **C** | **`continuity`：只分级披露、不过滤**（见 4.2） | ✅ 已实现（3035→3071 passed，+36；8 项反事实实测；四门全过） |
| **D** | `gap_note`：渲染 C 产出的 `stale_task_revision` | 待做，**依赖 C（C 已落地，接点见 4.2 末）** |
| **E** | `restraint`：接 `low_clue_recall.py:593` 的 `_recent_correction_signal` → `DenialTracker` → `restraint_denials.json` | 待做 |
| **F** | `recall_golden`：CLI 子命令 + seed golden set | ✅ **已保留并接线**（裁决反转，见 3.3）。**但 authority 维度是死代码，退出条件只满足 hit/miss 两项** |

**部署时机**：3.200 的 `/opt` 同步与部署验证**在整条 C→D→E 链落地后一次性做**，
不逐批部署。删除类改动单独部署没有可验证的行为变化，反而多几轮风险窗口。
C 已落地但**尚未部署**，按此裁定等 D、E。

A、B、C 完成后：**10 项已终结**（8 项删除 + timeutil 修复与定向迁移 + continuity 分级披露）。
剩余 **D→E**（gap_note 披露 → restraint 克制），外加待确认删除的 `recall_golden`。

这比初版方案设想的小得多——因为大部分"待接线"其实是不该接。
**初版说「6 项合并即终结」，实测后其中 4 项是删除**；
真正有产品价值的活自始至终只有这三项。

---

## 8. 复发防护

0. **接线前必须先验证该 helper 自身的前提能否成立——这是每项的必做步骤，不是某一条的附注。**
   本轮 6 个"该接线"的条目里有 4 个一碰实现就塌成删除。原因是分类只看了接口
   和"有没有人 import 它"，没读实现。一个从未被调用的 helper，
   **没有任何人验证过它的假设**；它自己的测试只证明内部逻辑自洽。
   默认预期应为"大概率不适用"。
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
