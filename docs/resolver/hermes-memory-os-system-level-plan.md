# Hermes-Memory-OS 系统级规划 v5(基于 3.200 生产实测 + Opus 4.8 审查)

> 性质:对 ~42K 行现有代码的系统级勘察 + 3.200 生产探针 + 优先级规划。
> v5 变更(Opus 4.8 审查):① P1b 和 P1a 同权——混合检索是基线能力,该无条件建,门控的是默认开关不是代码存在;② "独有贡献"在合成数据上只验机制不验价值,真实评估需 seed 后的生产数据;③ P0.1 stale FTS 要查根因(一致性 bug,会复发),挂横切 A;④ 补充 56→0 provisional 环境重置发现,区分"代码测过"与"生产验证过"。
> 核心判断:系统已在成熟位置。**生产数据不足阻塞的是开关打开,不是代码开发。混合检索和图谱 injection 作为 lifelong-memory 基线能力该无条件建——config-gated 默认关,本地验证正确性+可降级+不回归。门是"正确性门"(本地永远可达),不是"需不需要门"(每个部署自己决策)。**

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

**核心发现:系统在生产中几乎未被"喂饱"。** 2 条结晶、0 条 provisional、1 条边——governance 基础设施全部健康(monitor 99 PASS),但没有足够的记忆体量来触发计划中假设的"过期悬崖""召回 gap""图谱 shadow"等场景。

**额外发现:环境疑似被重置。** `invalidate-not-delete` 原则下,过期 provisional 应保留 expired 记录(标记 invalidated_at,不物理删除)。但 3.200 上 provisional=0 且 expired_provisional=0——如果此前有 56 条 provisional 自然过期,应该有 56 条 expired 记录留下。两者同时为 0 意味着环境被清理/重置过,不是自然演化。**这意味着之前对过期悬崖修复、免疫墙的验证,针对的是一个已不存在的状态;当前稀疏状态下,这些修复在生产中尚未被重新验证。代码测过 ≠ 生产验证过。**

**这不阻塞 P1 开发。** P1a 图谱 injection 和 P1b 向量检索是 lifelong-memory 开源框架的**基线能力**,该无条件建——本地可写可测,config-gated 默认关。门是"正确性门"(代码对不对、可不可降级、回不回归),本地永远可达;不是"需不需要门"(每个部署根据自己的数据自己决定开不开)。

**结论:成熟、重测试、治理领先。不缺功能,缺"它在 3.200 上真为你所用"的确认。混合检索和图谱注入作为基线能力该建——别让一台几乎没数据的测试机当路线图裁判。**

## P0(最高,开功能前必做):闭合生产验证回路
**理由:这一路每刀"代码验证通过、真实效果待观察"。在产生代码信号,缺生产信号。**

**P0 vs P1 关系:P0 验证项阻塞的是"生产开关打开",不是"代码开发"。P1a/P1b 作为基线能力该无条件建——代码在本地写、用本地测试数据验证正确性;P0 生产信号达标后再开生产开关。**

| # | 验证项 | 怎么验 | 状态 | 不通的后果 |
|---|---|---|---|---|
| V1 | **安装缝**:provider 真被宿主加载? | 3.200 跑安装,看 `Smoke test: PASS` | **待验** | 不通→前面所有刀从没在热路径跑过 |
| V2 | **fact_judge 召回**:durable 率 3.4%→?空响应 17%→? | 拉 verdicts.jsonl 统计 | ⚠️ **数据不足**(verdicts.jsonl 不存在,需 seed ≥10 条结晶+provisional) | 代码测过,生产待验证 |
| V3 | **过期悬崖**:recurrence 累加?digest 出"临近过期"区段? | 看 owner digest + confirm 重要几条 | ⚠️ **数据不足**(0 provisional,0 recurrence。此前 56 条已随环境重置消失,非自然演化) | 代码测过,生产待重新验证 |
| V4 | **prefetch**:真实会话 Crystallized 真落预算?FTS5 真排序? | 真实会话(非探针)测分段 + 确认 index rebuild 过 | **待验**(index 健康,FTS5 trigram 正常,需真实会话验证) | index=None→纯 mtime,优化没生效 |
| V5 | **数据完整**:`1\|` 污染文件 | 扫描 + 修复 | ✅ **无污染**(0 files affected) | — |
| V6 | **免疫墙**:prod probe | 现有 probe | ✅ **已通过**(持续观察;此前验证针对已重置环境,当前状态需重新确认) | — |
| V7 | **图谱 shadow log**:边质量 + 独有贡献 | 拉 log→统计分布→抽样评估→算 graph_unique | ⚠️ **数据不足**(graph_layer_shadow.jsonl 不存在,只有 1 条边) | 需 P1a engineering 完成后,seed 结晶→积累边数据→再评估 |

**P0 交付物**:一份 3.200 生产健康报告。**V1/V4 可直接验;V2/V3/V7 需先 seed 记忆(owner 审批 ≥10-20 条结晶+provisional)才有数据可验。** 这不阻塞 P1 开发。

### P0.1 数据完整性:stale FTS index(需查根因,非仅清理)

**发现**:FTS5 索引中存在 `cry_20260610T074613005735Z_c06c0df327e1`,但磁盘上无对应 crystallized 文件。

**这不是一次性清理问题——是 index 与 canonical store 分叉,违反"文件优先、索引可重建"原则。** 需要回答:为什么分叉?

可能根因:
1. 文件被手动删除但未触发 index 同步(删文件操作没走 governed 路径)
2. 不完整写入:文件写到一半崩溃,index 已提交但磁盘未 flush
3. index rebuild 从来只建不删(增量追加模式,stale 记录累积)

**处理**:
- **短期**:rebuild_from_store 清理当前 stale 记录
- **根因**(挂横切 A):审查所有删除/无效化路径——`invalidate-not-delete` 走的是 mark invalidated_at,物理删除走什么路径?有没有对应的 index 清理?如果 `rebuild_from_store` 是唯一清理 stale 的手段,那它就是"周期性全量重建"而非"增量同步"——这是设计选择还是遗漏?
- **优先级**:低(不影响当前功能,但会复发;在 P0 交付前至少 rebuild + 记录根因分析)

## P1(检索增强,两路平行推进)
**理由:图谱 injection 和向量检索都是 lifelong-memory 开源框架的基线能力——该无条件建,config-gated 默认关。两者共享一个本地嵌入器,但图谱推送零新依赖可先完成。**

**关键纠正(v5):P1b 和 P1a 同权——都是"该建"的基线能力。门是"正确性门"(代码对、可降级、不回归),本地永远可达;不是"需不需要门"(那是每个部署基于自己数据自己决策的开关)。**

### P1a(优先,零新依赖):图谱推送启用 —— 从 shadow 升级到 injection
**当前状态:structural + llm proposer 产出 candidate edges ✅、crystallization_gate 在 cognitive_loop 查 contradicts ✅、query_edges API 完成 ✅。但 `_graph_layer_shadow_lines`(prefetch.py:1102) 处于 Phase 1 shadow-only——写 `graph_layer_shadow.jsonl` audit log 后 `return []`,图谱边不进入 agent 记忆上下文。图谱对检索贡献=0。**

#### Step 0(生产门):拉 3.200 上已有的 shadow log 评估边质量

**⚠️ 3.200 实测:graph_layer_shadow.jsonl 不存在。** 原因:只有 2 条结晶 → 1 条边 → shadow log 从未被写入。**这门当前无生产数据可过,但不阻塞 engineering。**

评估分两阶段:
1. **本地**(现在):用本地测试数据(≥20 条结晶)跑 cognitive loop → 产生边 → 检查 shadow log → 人工评估边质量 → 验证机制正确
2. **3.200**(seed 后):seed ≥10-20 条结晶→边积累→拉 log 做生产评估

**门:边质量达标(人工抽样通过)→ 开 injection;不达标 → 先修 proposer,不硬推。**

#### Step 1(load-bearing 指标):量图谱去重后的"独有贡献"

**机制验证 vs 价值验证(重要区分):**

- **本地合成数据上量**:验证机制 work——图谱注入正常、cross-section dedup 生效、edge target 解析正确、预算不超。回答"代码对不对"。
- **真实数据上量(seed 后 3.200)**:评估价值——图谱在真实人类记忆的连接结构里到底补了多少新信息。回答"图谱在真实使用里值不值"。

**合成数据上的"独有贡献"数不能单独决定 P1b 的价值判断。** 真实记忆的连接结构合成数据造不出来——合成数据上的重叠率 ≠ 真实使用中的重叠率。

方法:
1. 准备 ≥20 条结晶记录(本地测试数据,多样化 topic)
2. 对每条 query,跑 `_crystallized_lines` 拿到 Crystallized Memory 段的 record_id 集合
3. 对每条 query,跑 `query_edges(anchor_ids)` 拿到图谱段的 record_id 集合
4. 算 `graph_unique = graph_records - crystallized_records`——图谱独有贡献
5. 统计 `graph_unique / graph_records` 比例 + 抽样看独有贡献的语义相关性

**这个指标的作用**(在本地合成数据上):
```
独有贡献 >0(机制正常,去重生效)
  → 图谱 injection 代码正确,可开生产开关(待生产边质量+预算验证)
  → 不等于"图谱在真实使用中有价值"——那需要 seed 后的生产数据

独有贡献 =0(全重叠,相连=相关)
  → 图谱 injection 边际价值可能小,但代码本身没问题
  → 不影响 P1b 建设——混合检索是基线能力
  → 真实价值评估等 seed 后生产数据

独有贡献异常(去重失效,同一条记录出现在两段)
  → bug,修
```

**P1a 和 P1b 的关系(修正):两个都是基线能力,该平行建设。图谱 injection 优先完成(零新依赖);向量检索平行推进。独有贡献影响的是"每个部署的默认开关推荐",不是"P1b 建不建"。**

#### Step 2(5 个 TODO,按序做,本地可全测)

1. **Edge target→可读内容**:当前 edge 存的是 `record_id`(hash),需 resolve 为人类可读的 body preview
2. **跨段去重**:同一条记忆不能同时出现在 Related Memory + Crystallized Memory 两个段
3. **预算感知**:graph section 纳入 prefetch budget(当前 `Related Memory` 优先级=65,位于 Crystallized(60) 和 Events(80) 之间)
4. **Config gate 默认关**:`graph_layer_injection_enabled` knob(lane_switch,默认 False,owner 审批后开)
5. **上线**:3.200 开 injection,monitor 观察——前提:Step 0 边质量达标 + 本地正确性验证通过

**为什么 P1a 优先于 P1b(工程顺序,非价值顺序):**
- **零新依赖**(不装 ONNX/不拉模型,纯工程)
- **复用已有 edge 数据**(structural + llm proposer 已在 cron 跑)
- 图谱 injection 完成后,可以积累生产边数据——这些数据反过来为 P1b 的向量 edge proposer 提供对比基线

### P1b(平行,证据门控开关):共享本地嵌入器 + 向量检索 + 向量 edge proposer
**混合检索(FTS5 + 向量 RRF union)是 lifelong-memory 开源框架的基线能力——该无条件建,config-gated 默认关。**

**门控的是默认开关,不是代码存在。** 正确性门(本地永远可达):代码对、可降级、不回归。每个部署基于自己的数据和需求,自己决定开不开。

- **本地开发**(现在,不等 P1a):
  1. 本地嵌入器(onnx bge-small ~130MB,无 torch,**零按次费用**)+ `is_available` 降级
  2. 向量检索(hybrid FTS5 union,规约 `hermes-hybrid-retrieval-vector-fts5-union-spec.md` 已写)——FTS5 是确定性地板,向量可降级
  3. 向量 edge proposer(图谱最后一块,复用同一嵌入器,**可能反而减少 llm_edge_proposer 的 LLM 成本**)
  4. Knob 注册:`vector_retrieval_enabled`(lane_switch,默认 False)+ `vector_edge_proposer_enabled`(lane_switch,默认 False)
  5. 测试:12 项断言(含 knob 集成测试 W.10/W.11/W.12)
- **守 INV-5**:FTS5/符号召回是确定性地板,向量/图谱是可降级 enrichment
- **共享本地嵌入器**:向量检索 + 向量 edge proposer 共用一个 ONNX 模型,零额外依赖。`memory_embeddings` 表已存在(index.py:363,scaffold,空表),接管线即可
- **生产开关决策**(每个部署自己决定,不是代码仓库替部署决定):
  - **默认关**:`vector_retrieval_enabled` = False
  - **开启条件**(建议,非强制):P1a injection 已开 + owner 已 seed 足够记忆 + 存在 FTS5+图谱都漏召回的实测案例 + 部署有 ≥130MB 磁盘
  - **不开启也合理**:图谱 injection 已补上召回 gap,向量边际价值小;或部署磁盘受限
- **P1a 图谱 injection 优先完成,可以为 P1b 开关决策提供更多信号**,但不是 P1b 建设的前置条件

## 横切(持续,不占独立周期)
### A. 韧性:静默失败审计(含 P0.1 stale index 根因)
过期悬崖暴露的"静默丢弃"是一类不是孤例。fail-loud 解析器已落(D.10),但审一遍其他静默路径:空命中、嵌入器静默失败、edge 查询空、**index 与 canonical store 分叉(P0.1)**…**原则:所有"该有东西却没有"的地方,要么 fail-loud(error_record/finding)、要么有明确降级语义,不静默吞。**

**P0.1 stale FTS index 挂入此处:**
- 审查所有物理删除/无效化路径 → 确认每个路径都有对应的 index 同步
- 如果 `rebuild_from_store` 是唯一清理 stale 的手段 → 文档化这是"周期性全量重建"设计,不是增量同步;或补齐增量清理
- 加 monitor 检查:定期对比 FTS index count vs disk record count,发现分叉→error_record

### B. owner_actions 机会主义拆分(非紧急,但控制平面单点需守)
**经勘察:它是"良性的大"——302 个符号、零模块级可变状态、低耦合(1.3 互调/函数)、77 测试覆盖。问题只是扁平难导航,不是纠缠或正确性风险。但它是系统唯一的 owner-review 控制平面——approve/reject/feedback/allow/apply 全经此文件。**
- **不做大爆炸重构**(重构能跑的代码=零功能收益 + 隐 bug 风险)
- **守**:每次动 owner_actions 必须 ≥77 测试 PASS,owner-review 相关 spec 测试优先跑
- **顺手拆**:下次为某功能本来就要动 owner_actions 时,把那一簇抽成模块
- **拆分策略(预声明,不现在执行)**:
  - 按 **proposal kind** 切:`_apply_confirm_provisional_knob_override` → `knob_actions.py`; expression feedback → `expression_actions.py`
  - 按 **delivery** 切:`deliver_owner_review_digest_once` + 相关 → `digest_delivery.py`
  - 保持 `owner_actions.py` 作为 facade re-export 兼容层
  - **不在没有功能变更的时候拆**

## 不做 / 明确边界
- ❌ 不做 owner_actions 大爆炸重构(良性的大,顺手即可)
- ❌ **不因 3.200 数据稀疏推迟 P1b 建设**——混合检索是基线能力,该无条件建。门控的是开关,不是代码
- ❌ 不让合成数据上的"独有贡献"数单独决定 P1b 开关推荐——真实价值评估靠生产数据
- ❌ 不对 stale FTS index 只做 rebuild 不查根因——这是一致性 bug,会复发
- ❌ 不为 `1\|` 污染建自动修复机制(且 3.200 实测无污染)
- ❌ 向量/图谱不进确定性决策路径(守 INV-5);不为功能请外部大模型(嵌入器本地零费用)
- ❌ 不追 benchmark SOTA;治理层是护城河,检索增强不稀释它

## 优先级总览
```
P0   生产验证回路(V1/V4 可验; V2/V3/V7 需 seed)     ← 与 P1 并行推进
P0.1 stale FTS 根因(rebuild + 查分叉原因)              ← 短期 rebuild,根因挂横切 A
       ↓
P1a  图谱 injection(shadow→injection)   ← 5 TODO 本地可测,零新依赖,先完成
P1b  向量检索 + 向量 edge proposer      ← 基线能力,平行建设,本地可测,config-gated 默认关
       ↓ 两者都完成后,生产开关决策:基于 seed 后的生产数据,各部署自己决定
横切A 静默失败审计(含 P0.1 stale index 根因)   ← 持续
横切B owner_actions 顺手拆                        ← 非紧急,动到那块时顺手
```

## 关键区分总结

| | 代码开发 | 生产开关 |
|---|---|---|
| **P1a 图谱 injection** | ✅ 无条件建(基线能力,零新依赖) | 边质量 + 去重 + 预算验证通过 → 开 |
| **P1b 向量检索** | ✅ 无条件建(基线能力,本地嵌入器) | 正确性 + 可降级 + 不回归验证通过,部署自定 |
| **门性质** | 正确性门(代码对/可降级/不回归),本地永远可达 | 部署决策门(我的数据需要吗?),每个部署自己答 |
| **"独有贡献"角色** | 验机制(去重生效/注入正常),不影响建不建 | 给信号(图谱补了多少),影响开关推荐,不决定代码存在 |
| **3.200 角色** | 不影响开发(本地写,本地测) | 验证环境,不是路线图裁判 |

## 一句话
系统已在成熟、治理领先的位置(1438 测试、治理脊柱完整)。3.200 生产探针确认:基础设施健康但记忆体量稀疏,环境疑似被重置(56→0 provisional 非自然演化)。**混合检索和图谱 injection 作为 lifelong-memory 开源框架的基线能力,该无条件建——config-gated 默认关,正确性门本地永远可达。别让一台几乎没数据的测试机决定路线图上有什么代码。** owner_actions 是良性的大但控制平面单点,顺手拆即可。stale FTS index 是一致性 bug,需查根因而非仅清理。**代码测过 ≠ 生产验证过——当前稀疏状态下,过期悬崖修复和 fact_judge 召回在生产中尚未被重新验证。**
