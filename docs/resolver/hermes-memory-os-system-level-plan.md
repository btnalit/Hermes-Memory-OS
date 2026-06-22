# Hermes-Memory-OS 系统级规划 v4(基于 3.200 生产实测)

> 性质:对 ~42K 行现有代码的系统级勘察 + 3.200 生产探针 + 优先级规划。
> v4 变更:**3.200 完整探针后修订**——P0 区分"可验"与"数据不足",P1 开发不受生产数据稀疏阻塞,新增数据完整性发现。
> 核心判断不变:**系统已在成熟位置,但生产验证回路滞后于构建速度。** 补充:**生产验证数据不足不等于新功能不能开发——纯工程项(图谱 injection/向量检索)本地可写可测,P0 门控的是生产开关,不是代码。**

## 0. 系统现状(诚实勘察)

| 维度 | 状态 |
|---|---|
| 规模 | ~42K 行(memory_os 34K + governance 7.7K),132 测试文件,**1438 测试** |
| 治理脊柱 | 完整:fail-closed、append-only audit、invalidate-not-delete、resolver/owner-ack、污点墙、自进化 |
| 自主面 | 14 条 cron lane(digest/right_brain/fact_judge/candidate_aggregation/index_sync/working_cleanup/l3_probe…) |
| 近期落地 | 结晶解封→召回修复→门禁索引→免疫墙→安装硬化→过期悬崖,**全 RED-first + 反证** |
| 图谱 | structural+llm proposer ✅、crystallization_gate 查矛盾 ✅、query_edges API ✅、**prefetch 注入已禁用(Phase 1 shadow-only,返回 [],图谱对 agent 检索贡献=0)** ❌ |
| 向量 | memory_embeddings 表空(脚手架);共享嵌入器未建 |

### 0.1 3.200 生产实测(2026-06-22)

```
gateway=active pid=60562, heartbeat=active/enabled, cognitive_loop=warning
crystallized_records=2 (owner_approved.md: preference, probe_test.md: probe)
candidates=1374, crystallized_records_index=2
edges_total=1 (co_occurs, proposed_by=llm, state=active)
edge: cry_20260527T102137… → cry_20260610T074613… (后者 FTS 有但磁盘无——stale index)
embeddings=0, graph_layer_shadow.jsonl=DOES NOT EXIST
verdicts.jsonl=DOES NOT EXIST, expiring_provisional.json=[]
provisional=0, expired_provisional=0, total_recurrence=0
index healthy (trigram, 15 tables), prefetch_mode=indexed
Related Memory section: ZERO entries (injection disabled in code)
Monitor: 99 PASS / 2 WARN / 1 FAIL (execution_gate_cron_helper_completion_error, 已存在)
"1|" 污染: 无 (0 files affected)
```

**核心发现:系统在生产中几乎未被"喂饱"。** 2 条结晶、0 条 provisional、1 条边——governance 基础设施全部健康(monitor 99 PASS),但没有足够的记忆体量来触发计划中假设的"过期悬崖""召回 gap""图谱 shadow"等场景。这不是系统缺陷,而是它还没被真正使用。

**但这不是阻塞 P1 开发的理由。** P1a 图谱 injection 的 5 个 TODO 是纯工程——本地写、本地测、用本地测试数据验证,不需要等 3.200 攒结晶。P1b 向量检索同理——代码能写,测试能跑。P0 门控的是"生产开关打开",不是"代码能不能写"。

**结论:成熟、重测试、治理领先。不缺功能,缺"它在 3.200 上真为你所用"的确认。生产数据不足阻塞了 P0 部分验证项,但不阻塞 P1 开发推进。**

## P0(最高,开新功能前必做):闭合生产验证回路
**理由:这一路每刀"代码验证通过、真实效果待观察"。在产生代码信号,缺生产信号。按你"信号驱动推进",这是当前最该补的信号。**

**P0 vs P1 关系:P0 验证项阻塞的是"生产开关打开",不是"代码开发"。P1a/P1b 的工程实现可以与 P0 并行推进——代码在本地写、用本地测试数据验证;P0 生产信号达标后再开生产开关。**

| # | 验证项 | 怎么验 | 状态 | 不通的后果 |
|---|---|---|---|---|
| V1 | **安装缝**:provider 真被宿主加载? | 3.200 跑安装,看 `Smoke test: PASS` | **待验** | 不通→前面所有刀从没在热路径跑过 |
| V2 | **fact_judge 召回**:durable 率 3.4%→?空响应 17%→? | 拉 verdicts.jsonl 统计 | ⚠️ **数据不足**(verdicts.jsonl 不存在,系统只有 2 条结晶,fact_judge 没有足够输入) | 需先 seed 更多结晶+provisonal 记忆后重新评估 |
| V3 | **过期悬崖**:recurrence 开始累加?digest 出"临近过期"区段? | 看 owner digest + confirm 重要几条 | ⚠️ **数据不足**(0 provisional,0 recurrence,无过期数据) | 需先有 provisional 记忆才能验证过期悬崖机制 |
| V4 | **prefetch**:真实会话 Crystallized 真落预算?FTS5 真排序? | 真实会话(非探针)测分段 + 确认 index rebuild 过 | **待验**(index 健康,FTS5 trigram 正常,需真实会话验证) | index=None→纯 mtime,优化没生效 |
| V5 | **数据完整**:`1\|` 污染文件 | 扫描 + 修复 | ✅ **无污染**(0 files affected,原假设有 3 个污染文件) | — |
| V6 | **免疫墙**:prod probe | 现有 probe | ✅ **已通过**(持续观察) | — |
| V7 | **图谱 shadow log**:边质量 + 独有贡献 | 拉 log→统计分布→抽样评估→算 graph_unique | ⚠️ **数据不足**(graph_layer_shadow.jsonl 不存在,只有 1 条边,2 条结晶产生的唯一 pair) | 需 P1a engineering 完成后,开启 injection shadow→积累边数据→再评估。当前无数据可评 |

**P0 交付物**:一份 3.200 生产健康报告。**V1/V4 可直接验;V2/V3/V7 需先 seed 记忆(owner 审批 ≥10-20 条结晶+provisional)才有数据可验。** 这不阻塞 P1 开发——P1a/P1b 工程实现可并行推进。

### P0.1 数据完整性发现(stale FTS index)

**发现**:FTS5 索引中存在 `cry_20260610T074613005735Z_c06c0df327e1`,但磁盘上无对应 crystallized 文件。这是 index 与 canonical store 不一致——违反"文件优先、索引可重建"原则。

- **修复**:在 3.200 上运行 `index rebuild`(`rebuild_from_store`)清理 stale 记录
- **优先级**:低(不影响功能,但应在 P0 交付前修复)
- **根因**:待查——可能是不完整写入或手动删除文件后未重建索引

## P1(检索增强,分两路独立推进)
**理由:图谱和向量是两条独立路径,共享一个本地嵌入器,但图谱推送零新依赖可以先跑。P1a 工程实现不受 3.200 数据稀疏影响——本地可写可测;生产开关待 P0 门控。**

### P1a(优先,零新依赖):图谱推送启用 —— 从 shadow 升级到 injection
**当前状态:structural + llm proposer 产出 candidate edges ✅、crystallization_gate 在 cognitive_loop 查 contradicts ✅、query_edges API 完成 ✅。但 `_graph_layer_shadow_lines`(prefetch.py:1102) 处于 Phase 1 shadow-only——写 `graph_layer_shadow.jsonl` audit log 后 `return []`,图谱边不进入 agent 记忆上下文。图谱对检索贡献=0。**

#### Step 0(真门,不是形式):拉 3.200 上已有的 shadow log 评估边质量

**⚠️ 3.200 实测:graph_layer_shadow.jsonl 不存在。** 原因:只有 2 条结晶 → 1 条边 → shadow log 从未被写入(没有足够 pair 触发 `_record_graph_layer_shadow`)。**这门当前无数据可过。**

**但不阻塞 engineering 推进。** 评估路径:
1. **短期**(本地):用本地测试数据(≥10 条结晶)跑 cognitive loop → 产生边 → 检查 shadow log 输出 → 人工评估边质量
2. **中期**(3.200):seed 更多结晶记忆后,shadow log 自然积累 → 再拉 log 做生产评估
3. **门**:边质量达标(人工抽样通过)→ 开 injection;不达标 → 先修 proposer

#### Step 1(load-bearing 指标):量图谱去重后的"独有贡献"

**⚠️ 3.200 实测:无足够数据可量。** 但方法论不变:

逻辑:
- `Crystallized Memory` 段已按 FTS5 相关性注入结晶记录(permanent ≤15 + provisional ≥5)
- `Related Memory`(图谱)注入的是"与 anchor 通过边相连的结晶"
- **最相关的往往也最相连——重叠会很高**

所以真正要量的不是"图谱注入了多少条",而是:

> **图谱注入了哪些 Crystallized Memory 里没有的记录?——"独有贡献"数**

怎么量(本地测试即可,不依赖 3.200):
1. 准备 ≥20 条结晶记录(本地测试数据)
2. 对每条 query,跑 `_crystallized_lines` 拿到 Crystallized Memory 段的 record_id 集合
3. 对每条 query,跑 `query_edges(anchor_ids)` 拿到图谱段的 record_id 集合
4. 算 `graph_unique = graph_records - crystallized_records`——图谱独有贡献
5. 统计 `graph_unique / graph_records` 比例 + 抽样看独有贡献的语义相关性

**这个指标串联 P1a 和 P1b 的决策:**

```
独有贡献高(图谱补了 >30% 新记录,且语义相关)
  → 图谱注入边际价值大, P1a 值得, 可能直接堵上召回 gap
  → P1b 向量都省了

独有贡献低(相连≈相关, 全重叠, <10% 新记录或新记录不相关)
  → 图谱注入边际价值小, FTS5+图谱仍漏召回
  → gap 可能还在语义层, 反而支持 P1b 向量
```

**这就是"信号驱动"——量出来,两步都有了依据,不是猜。**

#### Step 2(5 个 TODO,按序做,本地可全测)

**纯工程项,不需要 3.200 数据:**
1. **Edge target→可读内容**:当前 edge 存的是 `record_id`(hash),需 resolve 为人类可读的 body preview
2. **跨段去重**:同一条记忆不能同时出现在 Related Memory + Crystallized Memory 两个段(Step 1 离线量过,这里是运行时保证)
3. **预算感知**:graph section 纳入 prefetch budget(当前 `Related Memory` 优先级=65,位于 Crystallized(60) 和 Events(80) 之间)
4. **Config gate 默认关**:`graph_layer_injection_enabled` knob(和 vector 一样 lane_switch,默认 False)
5. **上线**:3.200 开 injection,monitor 观察 agent 行为变化——**这是唯一需要 3.200 的步骤,且前提是 Step 0 边质量达标 + Step 1 独有贡献达标**

**为什么 P1a 优先于 P1b:**
- **零新依赖**(不装 ONNX/不拉模型,纯工程)
- **复用已有 edge 数据**(structural + llm proposer 已在 cron 跑)
- **补的是"图谱没推送"的 gap**,不是"缺语义"的 gap——这两个 gap 不同,图谱推送可能已经能解决部分召回问题
- **P1a 和 P1b 的决策被"独有贡献"数串联**——量出来,两步都有了依据
- P0 生产数据(独有贡献)可能显示图谱推送就够,省掉 130MB 嵌入器

### P1b(证据门控):共享本地嵌入器 + 向量检索 + 向量 edge proposer
**理由 + 红线:按你路线图"先量 gap 再建引擎"。图谱推送(P1a)落地后再评估:是否还有 FTS5 漏 + 图谱边也连不上的语义召回 gap?**

**同样:P1b 代码可以并行开发(本地测试),证据门控的是生产开关。**

- **Phase 0 门控(必过):P1a 独有贡献数据 + 剩余 gap 评估**——P1a Step 1 的"独有贡献"数出来之后:图谱推送落地后,是否还有真实案例——agent 漏召回一条语义相关结晶,FTS5 漏了 + 图谱边也没连上?
  - **有(实测)** → 建嵌入器(一举两得:检索 union + 向量 edge proposer 替代 llm_edge_proposer 降成本)。
  - **无** → 图谱推送可能就够,省掉 130MB 依赖。**停在 Phase 0 不亏。**
- 若过门(顺序):
  1. 本地嵌入器(onnx bge-small ~130MB,无 torch,**零按次费用**)+ `is_available` 降级。
  2. 向量检索(hybrid FTS5 union,规约 `hermes-hybrid-retrieval-vector-fts5-union-spec.md` 已写,含前置门控)——FTS5 是确定性地板,向量可降级。
  3. 向量 edge proposer(图谱最后一块,复用同一嵌入器,**可能反而减少 llm_edge_proposer 的 LLM 成本**)。
- **守 INV-5**:FTS5/符号召回是确定性地板,向量/图谱是可降级 enrichment。
- **共享本地嵌入器**:向量检索 + 向量 edge proposer 共用一个 ONNX 模型,零额外依赖。`memory_embeddings` 表已存在(index.py:363,scaffold,空表),接管线即可。
- **生产开关**:`vector_retrieval_enabled` knob(lane_switch,默认 False),P0 门控达标后才能开。

## 横切(持续,不占独立周期)
### A. 韧性:静默失败审计
过期悬崖暴露的"静默丢弃"是一类不是孤例。fail-loud 解析器已落(D.10),但审一遍其他静默路径:空命中、嵌入器静默失败、edge 查询空…**原则:所有"该有东西却没有"的地方,要么 fail-loud(error_record/finding)、要么有明确降级语义,不静默吞。** P0 生产数据会暴露还有哪些静默面。

### B. owner_actions 机会主义拆分(非紧急,但控制平面单点需守)
**经勘察:它是"良性的大"——302 个符号、零模块级可变状态、低耦合(1.3 互调/函数)、77 测试覆盖。问题只是扁平难导航,不是纠缠或正确性风险。但它是系统唯一的 owner-review 控制平面——approve/reject/feedback/allow/apply 全经此文件。**
- **不做大爆炸重构**(重构能跑的代码=零功能收益 + 隐 bug 风险)。
- **守**:每次动 owner_actions 必须 ≥77 测试 PASS,owner-review 相关 spec 测试优先跑。这是控制平面,不是普通模块。
- **顺手拆**:下次为某功能本来就要动 owner_actions 时(RAGFlow owner-ack / 向量碰 owner 路径 / 图谱 edge 审批),把那一簇抽成模块。本来就在测那块,零额外风险。
- **拆分策略(预声明,不现在执行)**:
  - 按 **proposal kind** 切:`_apply_confirm_provisional_knob_override` → `knob_actions.py`; expression feedback → `expression_actions.py`
  - 按 **delivery** 切:`deliver_owner_review_digest_once` + 相关 → `digest_delivery.py`
  - 保持 `owner_actions.py` 作为 facade re-export 兼容层(所有外部调用者不感知)
  - **不在没有功能变更的时候拆**(零功能收益 + 隐 bug 风险)
- **触发信号**:哪天反复找不到东西 / merge 冲突 / 动一处怕碰别处——那时再专门拆(因无可变全局态,按主题切 + re-export 保兼容,风险也低)。

## 不做 / 明确边界
- ❌ 不做 owner_actions 大爆炸重构(良性的大,顺手即可)。
- ❌ gap 未实测达标前不**开启**向量检索生产开关(代码可以写、可以本地测)。守红线的是开关,不是开发。
- ❌ 不为单机 `1\|` 污染建自动修复机制(且 3.200 实测无污染)。
- ❌ 向量/图谱不进确定性决策路径(守 INV-5);不为功能请外部大模型(嵌入器本地零费用)。
- ❌ 不追 benchmark SOTA;治理层是护城河,检索增强不稀释它。

## 优先级总览
```
P0   生产验证回路(V1/V4 可验; V2/V3/V7 需 seed 记忆)  ← 并行推进, 不阻塞 P1 开发
P0.1 修复 stale FTS index (rebuild_from_store)           ← 低优先级, P0 交付前做
       ↓
P1a  图谱推送启用(shadow→injection)   ← 5 个 TODO 本地可写可测, Step 0/1 本地测试→达标后 3.200 开 injection
       ↓ 独有贡献高→注入; 低→图谱边际价值小, 支持 P1b
P1b  向量+图谱(证据门控)             ← 代码可并行开发本地测, 生产开关待 P1a 独有贡献数据 + P0 达标
横切A 静默失败审计                     ← P0 副产品, 持续
横切B owner_actions 顺手拆            ← 非紧急但控制平面单点, 动到那块时顺手, 守 ≥77 测试 + 预声明拆分策略
```

## 关键区分:P0 门控 vs P1 开发

| | P0 生产验证 | P1 工程开发 |
|---|---|---|
| **依赖** | 3.200 生产数据 | 本地测试数据 |
| **阻塞因素** | V2/V3/V7 需 seed ≥10 条结晶 | 无阻塞,可立即开始 |
| **门控目标** | 生产开关(能不能开 injection/vector) | 代码正确性(功能能不能跑) |
| **时机** | 与 P1 并行推进 | 现在就做 |

**P0 验证数据不足不是 P1 开发的阻塞器。两个轨道并行:开发轨道写代码+本地测试,生产轨道 seed 记忆→积累数据→验证。交汇点在"生产开关打开",不在"代码开始写"。**

## 一句话
系统已在成熟、治理领先的位置(1438 测试、治理脊柱完整)。3.200 生产探针确认:基础设施健康但记忆体量稀疏(2 条结晶)。**P0 生产验证和 P1 工程开发并行推进**——P0 验证项中 V2/V3/V7 需先 seed 记忆,V1/V4 可直接验;P1a 图谱 injection 5 个 TODO 零新依赖本地可测,P1b 向量代码可并行开发。**生产数据不足阻塞的是"开关打开",不是"代码开发"——不要混淆两者。** owner_actions 是良性的大但控制平面单点,顺手拆即可。**别让构建速度甩开验证速度——这是这套系统现在唯一真正的风险。**
