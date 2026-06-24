# Hermes-Memory-OS 稳定化清单

> **性质:这不是路线图,是收口清单。做完这些 = 扎实了,然后停。没有"然后呢"。**
> 边界明确、逐项可打勾、做完即止。除"图谱完善"是唯一在建功能外,其余全是"让已有的更可靠",不加新功能、不加新模块。
> 完成后的模式切换:从「构建」→「使用 + 维护」。

## Checkbox 语义说明
本清单的 checkbox 有三种不同完成语义，按板块区分:
- **A 节**:分类决策完成即为打勾(合法空 / fail-loud / 显式降级)，**不要求全都落地代码**——只要求该 fail-loud 的落地。
- **B 节**:首次数据拉取 + 观察结论即为打勾(不要求"完美"结论)。
- **C/D/E 节**:传统意义——代码落地 + 测试通过 = 打勾。

---

## A. 静默失败审计(有限清单,不是"审一审")
> 原则:**不是每个空返回都要 fail-loud**(没数据→空段是对的)。只治一类:**"输入非空却产出 0 + 不报错"**——数据在却什么都没出来,signal 损坏/bug。

**已完成(对照,证明这一类是真的)**
- [x] 结晶文件非空却解析 0 条 → `crystallized_file_unparseable` fail-loud
- [x] L3 repo root 指向存在但非源码目录 → SystemExit fail-loud + 身份校验
- [x] 向量空/全低于阈值 → 退 FTS5 floor(显式降级,非静默)

**待审(把这几个点逐一分类:合法空 / 该 fail-loud / 该显式降级)**

每个点需确定:**信号落在哪里**(audit log? event? monitor WARN? owner finding?)。不指定落点就是"我们在代码里看了一下"——不可验证。

- [ ] **A.1 FTS5 命中空 → mtime 兜底**:确认是**显式降级**(有降级信号,不是悄悄退化)。
  - 落点候选:audit log 写 `fts5_empty_fallback_to_mtime` 记录;或 monitor 的 degraded_lane 计数。
  - 需确认:index 是否知道"自己没数据/没 rebuild"并把这个事实传递给调用方(不只是返回空列表)。

- [ ] **A.2 嵌入器 is_available=False → vector 关**:确认有**可见信号**告诉 owner"向量静默关了"。
  - 落点候选:owner digest 的 "degraded capabilities" 区段;或 monitor WARN 计数(`vector_silently_disabled`)。

- [x] **A.3 index 与 store 分叉(stale FTS,P0.1 修过)**:已覆盖 — CLI health check(_index_health_findings) + monitor contract(index_catchup_contract) 已提供充分的诊断信号。运行时 rebuild/sync 前的 fork 检测不需要额外实现。

- [x] **A.4 会话事件 safe_ref 缺字段**:设计如此 — lenient 处理(missing key→""→legacy)是正确行为,确保 0.3% legacy 事件不被静默排除。区分'key 缺失 vs 值为空'不属于'输入非空产出0'模式。

- [ ] **A.5 crystallized record frontmatter 缺关键字段**(如 provisional/expires_at):
  - 确认当前 behavior:用默认值(是什么?)?跳过该记录?跳过 + 不报错 = 静默吞。
  - 缺 `provisional` → 默认 False(偏保守,可接受) vs 缺 `expires_at` → 默认 None(永不过期,偏危险)。确认不静默误判。

**A 的完成条件**:上面 5 个点每个都归类完(合法空 / fail-loud / 显式降级),**并指定信号落点**。该 fail-loud 的落地 + 带咬测试。**做完即止——不扩展到"所有 return"。**

---

## B. 生产验证 6 项(代码信号 → 生产信号)
> 3.200 现在记忆稀疏(~2 条结晶),部分项要先 seed/用起来才能验。诚实标注哪些"现在可验"、哪些"随真实使用积累后验"。

**已确认**
- [x] V1 安装缝:L3 smoke `✅ GOVERNANCE PATH + PREFETCH RECALL VERIFIED`
- [x] V5 数据完整:3.200 实测**无污染**(0 文件,之前假设的污染不存在)
- [x] V6 免疫墙:prod probe 通过
- [x] 向量价值:3.200 真模型 benchmark +58% 跨语言召回

**待验(随真实使用积累后确认,非离散任务)**

每个待验项必须标注:**验证方法 + 观察窗口**。否则"随用确认"变成"永远不确认"。

- [ ] **V2 fact_judge 召回**(方法:拉 `verdicts.jsonl` 统计;窗口:seed 至少 20 条结晶后,观察 2 周)
  - 基线:durable 率 ~3.4%、空响应率 ~17%(此前数据)
  - 观察:durable 率是否上升、空响应率是否下降(seed 质量提升应改善两者)

- [ ] **V3 过期悬崖**(方法:查 owner digest 的"临近过期"区段 + crystallized 的 `expires_at` 分布;窗口:provisional 候选攒够 10+ 后)
  - 确认 recurrence 累加正确、digest 出"临近过期"区段
  - 确认固定日期悬崖模式(如所有 crystal 同一天到期)被 recurrence 分散规避
  - 注意:清单中的"6/24"是示例日期模式,非字面值——指"同一天集中过期"的悬崖,今天(2026-06-24)恰是此模式的实例

- [ ] **V4 prefetch**(方法:真实会话后读 prefetch 输出分段大小 + 确认 index rebuild 过后 FTS5 真排序;窗口:用 1 周后)
  - 注意:真实会话的 prefetch 输出不自动落在可查询路径;验证时可能需要临时读 log 或通过 probe 脚本间接获取
  - 确认分段未膨胀(FTS5 + vector + graph 三段各自在 cap 内)

- [ ] **会话隔离**(方法:真实会话后确认 Recent Events 段只含当前会话 session_id;窗口:跨 ≥2 个会话后)
  - 确认拼接真消失(两段会话的 recent events 无交集)
  - 确认 legacy 事件(session_id="")在 exclude_session_id="" 时被正确排除

**B 的完成条件**:已确认 4 项打勾;待验 4 项各自完成首次数据拉取 + 形成观察结论(不论好坏)——**它们的完成靠"真的用它 + 按方法观察",不是靠再写代码**。观察窗口到期后仍未满足条件 = 发现新问题,回 A 或新开 bug fix(不扩展此清单)。

---

## C. 图谱完善(唯一在建功能,本清单里唯一的"新")
> 现状对照(2026-06-24):structural_edge_proposer.py ✅、llm_edge_proposer.py ✅、graph_layer injection 管线(pipeline:shadow 写 + knob gate + resolve preview + cross-section dedup)✅。`graph_layer_injection_enabled` knob 已注册(default=False)✅。

**处于 Phase 1(shadow audit):knob 关,shadow 写,无注入。Phase 2(injection)需过质量门。**

> **New finding resolved**: edge governance gap closed — `approve_edge` / `reject_edge` owner actions implemented in `owner_actions.py` (ef10947). Edge proposal lifecycle is fully governed (propose → shadow → owner action → active).

### C.1 质量门:评估 3.200 shadow 边质量

- [ ] 读 3.200 上的 `system/graph_layer_shadow.jsonl`,评估:
  - **噪声率**:weight < 0.3 的边占比(当前 injection 已跳过,但 shadow 全量写)
  - **垃圾/误标 contradicts**:contradicts 边是否正确(两类 proposer 的 contradicts 误标率)
  - **重复边**:同一对( from_record_id, to_record_id )被多次提议的频率
  - 判定:质量差(噪声 >50% 或 contradicts 误标 >30%)→ 先修 proposer,**不硬推 injection**

### C.2 injection 开启(质量门过后)

当前代码底座已完成 4/5 + budget 覆盖=5/5:
- [x] resolve 可读预览(`_resolve_edge_target_preview()`)
- [x] 跨段去重(`seen` set via `_graph_layer_injection_lines`)
- [x] knob 默认关(`graph_layer_injection_enabled`, default=False)
- [x] shadow-eval 先过(shadow 始终写入,不依赖 knob)
- [x] **budget 感知**:已由 _fit_budget() 跨段裁剪覆盖(Related Memory 优先级 65),不需要额外实现

- [ ] 开 injection:knob 设 `graph_layer_injection_enabled=True`(3.200 上),验证 injection 行出现在 "Related Memory" 段

### C.3 量"独有贡献"

- [ ] 对比图谱注入的 record_id 集合与 Crystallized Memory 其余各段的 record_id 集合(通过 `seen` set 的去重率):
  - 方法:开 injection 后,统计 `seen` set 中因 graph injection 而新增的比例
  - 高独有贡献(>30% 新增)→ 图谱有独立价值
  - 高重叠(>90% 已被 Crystallized Memory 覆盖)→ proposer 需要调方向,或图谱价值低
  - 据此定 proposer 调不调、injection 留不留

### C.4 向量 edge proposer(图谱最后一块) — ✅ DONE

> 性质:新的 proposer(source="vector"),**不是新功能面**——它和 structural/llm proposer 共享同一条 `write_governed_edge()` → candidate edge → owner review → promote → active → injection 治理管线。只是新增一种边提议来源。

- [x] 实现 `vector_edge_proposer.py`(258 行):复用同一本地嵌入器(LocalEmbedder),cron 时对 crystallized record pairs 计算语义相似度→超过阈值则提议候选边
  - 复用 `write_governed_edge(proposed_by="vector")`——走现有 candidate→active 治理,不新开路径
  - 与 structural proposer 的去重:同一对 (from_id, to_id) 被多个 proposer 提议 → 合并(保留最强 weight)还是独立?建议合并(按 max weight),避免重复 injection
  - 阈值:初始 0.75(cosine),`vector_edge_proposer_enabled` knob 已注册(default=False,shadow-only)
- [x] 测试:向量 proposer 单元测试(`test_memory_os_vector_edge_proposer.py`) + 与 structural proposer 的去重集成测试

**C 的完成条件**:质量门过 → injection 开启(含 budget 覆盖确认) → 独有贡献量化 → 向量 proposer 落地 + 测试(✅ DONE)。Injection 底座 4/5 TODO + budget 覆盖=5/5。**图谱这层补完 = 整个系统功能面收口,之后不再加。**

---

## D. owner_actions 顺手拆(站位规则,非离散任务)

> 本条可能自然为零操作:如 C 节不触及 owner-review/edge 审批路径,则不做任何改动。**没碰到就不动,不为拆而拆。**

- [ ] 做 C(图谱)碰到 owner-review/edge 审批路径时,**把那一簇抽成模块**(本来就在测那块,零额外风险)
- [ ] 守:每次动 owner_actions ≥77 测试 PASS
- [ ] **不做大爆炸重构**(良性的大,顺手即可)

**D 的完成条件**:这是规则不是任务。**C 完成时本条自动打勾(无论是否有改动)**——零操作是合法的完成状态。

---

## E. RAGFlow 可选集成收尾(已设计未实施,非新功能)
> 性质:**墙 P0/P1 早已部署**(provenance.py 在、memory_os 无 ragflow 字面量、解耦边界守住),P2/P3 是把**桥**和**对账**补完。
> 设计规约:`docs/resolver/hermes-ragflow-p2-p3-decoupled-connector-spec.md`(2026-06-19 spec review 的 6 个缺口已在当前 spec 版本中全部解决 ✅)。
> **铁律:可选解耦——删掉整个接缝层,memory_os 全量测试照过;memory_os 内永不出现 ragflow 字面量。**

**已完成**
- [x] P0/P1 免疫墙:`is_tainted` 污点检测 + 服务边界 ack 门 + static hygiene 守卫(已部署生产、probe 通过)
  - 代码证据:`provenance.py:10` TAINTED_SOURCE_CLASSES、`approval.py:28-29` external_evidence_ack 字段、`crystallized.py` write_approved_record ack 门、`scripts/memory_os_static_hygiene_check.py:67` ragflow 字面量检查
  - 测试证据:`test_memory_os_external_evidence_immunity.py` 合成 tainted event 测试全部通过

**待实施(全没动:已确认 external_intake/adapter/owner action/对账器都不存在)**

建造顺序(按 spec):先 P2.1+P2.3(memory_os 端口,可独立测)→ P2.2(接缝桥)→ P3。

- [ ] **P2.1 `external_intake` 端口**(memory_os 内,provider-agnostic,opaque provider 字符串,无 ragflow 字面量)
  - 新文件 `plugins/memory/memory_os/external_intake.py`
  - kind=`"external_evidence_intake"`,safe_ref 驱动污点和候选创建(provenance.py 已支持)
  - ExecutionGate envelope(lane_id="external_evidence_intake", risk_class="low")
  - 测试断言:Q.1-Q.2(spec §测试断言)

- [ ] **P2.3 `approve_external_evidence` owner action**(专用 ack,普通 approve 永不自动带 ack)
  - 新 action_type,走现有 `apply_owner_action` 分发
  - **注意 CLAUDE.md 约束**:新 proposal kind 需要 bounded apply contract + rollback + monitor fields + owner-visible workflow。`approve_external_evidence` 虽然只是 ack action(非自动执行),但仍需在 `owner_actions.py` 中按约束落地。
  - 测试断言:Q.3-Q.4

- [ ] **P2.2 RAGFlow 接缝 adapter**(**memory_os 之外**,唯一出现 ragflow 处,config 默认关、HTTP、profile-scoped)
  - 位置:`plugins/seam/ragflow_evidence/`(接缝侧,不在 memory_os 内)
  - config:`$HERMES_HOME/seam/ragflow_evidence/config.json`(默认 enabled=false)
  - 单向依赖:seam → memory_os(Python import),memory_os 永不 import seam
  - 测试断言:Q.5-Q.7

- [ ] **P3 对账器**(接缝侧,抓断了污点链的洗白:高相似+近时间+无链 → owner finding)
  - P3.1 memory_os 读口:`list_recent_crystallized()` + `emit_owner_finding()`(provider-agnostic,无 ragflow)
  - P3.2/P3.3 接缝对账器 + findings 落 owner digest
  - 测试断言:Q.8-Q.10

**E 的完成条件**:四项落地 + **核心反证**:
- Q.11:删整个接缝层(`plugins/seam/ragflow_evidence/`)→ memory_os 全量 + tainted 合成测试照过
- Q.12:static hygiene 仍 0 ragflow(接缝的 ragflow 不污染 memory_os 检查)
> ⚠ E 是**可选**的:如果你不实际用 RAGFlow 检索,这节可以一直留空——墙已经立住,不接桥也不影响系统。**用得上才补,用不上就不补。**

---

## 不在本清单内的已知项(显式排除)
以下已知问题/任务**明确不做**,避免"清单打完勾还有一堆事"的错觉:

- **Windows PermissionError**(`test_memory_os_graph_layer.py` 4 failures):pre-existing,与 `index.py:91` 文件锁有关。Windows 不是生产平台(3.200/feiniu 均 Linux),暂不修。边界声明中明确:生产平台 = Linux。
- **benchmark SOTA 追踪**:不做。向量价值已通过内部 benchmark 验证(+58% 跨语言召回),不追外部 SOTA。
- **新检索模态**:不做。FTS5 + vector + graph edge 是最终组合。
- **无止境打磨**:不优化非瓶颈路径、不加"可能有用"的缓存、不为监控加监控。

---

## 边界声明(这份清单的"完"在哪)
**做完 A+B+C+D+E = 扎实了。**(E 可选:用得上 RAGFlow 才补,用不上留空也算完。) 之后:
- 功能面收口(C 图谱补完,不再加模块/功能)。
- 可靠性收口(A 静默失败治完、B 生产信号补上)。
- 进入「使用 + 维护」模式:真的用它,让记忆攒起来,在真实使用里发现真问题再修(像会话拼接那样——用出来的,不是想出来的)。

**不在这份清单里的,就是"不做":** 不追 benchmark SOTA、不加新检索模态、不为优化而优化、不无止境打磨。**清单打满勾,就是收工。**

**维护模式进入后的轻量规则**(不扩展此清单):
- Bug fix 标准:静默失败 / 数据损坏 / 生产 probe 失败 → 修。性能优化 → 仅在瓶颈实测后修。
- 判定权:owner(你)决定什么是"真实使用里发现的真问题"。
- Windows 测试:不作为 gate(生产平台 Linux),但跨平台 PR 欢迎。

## 一句话
五节、可打勾、有终点:**静默失败审计(5 个点分类完+指定信号落点)+ 生产验证(4 项随用确认+验证方法+观察窗口)+ 图谱完善(质量门→injection→独有贡献量化→向量 proposer)+ owner_actions 顺手拆(碰到再拆,零操作合法)+ RAGFlow 可选集成收尾(墙已立,spec review 6 缺口已解决,桥/对账已设计待实施,用得上才补)**。做完这些,系统从"还能加什么"切换到"已有的真可靠"。**有边界、做完即止——之后是用它、维护它,不是继续建它。**
