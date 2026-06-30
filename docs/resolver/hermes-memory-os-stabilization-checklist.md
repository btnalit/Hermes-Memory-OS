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

- [x] **A.1 FTS5 命中空 → mtime 兜底**:确认为**显式降级**(有降级信号,不是悄悄退化)。 — **DONE** `945835a`
  - 落点:`prefetch._indexed_lines()` 写入 `fts5_empty_on_query` error_record (warn severity, recoverable)
  - 已确认:index 的 FTS5 空命中通过结构化 error_record 传递给调用方,monitor 可通过 `error_observability` 拾取

- [x] **A.2 嵌入器 is_available=False → vector 关**:确认有**可见信号**告诉 owner"向量静默关了"。 — **DONE** `b215339` + `64d648c` + `e208209`
  - 落点:`_tool_status_report()` 和 `build_status_report()` 均暴露 `vector_available: bool`
  - monitor 的 `host_capability_contract` 可拾取此字段
  - `install_memory_os.sh` 自动检测 gateway Python venv 并安装 `sentence-transformers` (`728cec7`)

- [x] **A.3 index 与 store 分叉(stale FTS,P0.1 修过)**:已覆盖 — CLI health check(_index_health_findings) + monitor contract(index_catchup_contract) 已提供充分的诊断信号。运行时 rebuild/sync 前的 fork 检测不需要额外实现。

- [x] **A.4 会话事件 safe_ref 缺字段**:设计如此 — lenient 处理(missing key→""→legacy)是正确行为,确保 0.3% legacy 事件不被静默排除。区分'key 缺失 vs 值为空'不属于'输入非空产出0'模式。

- [x] **A.5 crystallized record frontmatter 缺关键字段**(如 provisional/expires_at): — **DONE** `04a7604`
  - 确认当前 behavior:`write_approved_record()` 中 `provisional=True` 且 `expires_at` 为空 → 直接 `raise ValueError`
  - 缺 `provisional` → 默认 False(偏保守,可接受) / 缺 `expires_at` → ValueError(不再静默永不过期)
  - 落点:write-time 验证,不写入文件

**A 的完成条件**:上面 5 个点每个都归类完(合法空 / fail-loud / 显式降级),**并指定信号落点**。该 fail-loud 的落地 + 带咬测试。**做完即止——不扩展到"所有 return"。** ✅ A 节全部完成

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

> **New finding resolved**: edge governance gap closed — `approve_edge` / `reject_edge` owner actions implemented in `owner_actions.py` (`ef10947`). Edge proposal lifecycle is fully governed (propose → shadow → owner action → active).

### C.1 质量门:评估 3.200 shadow 边质量

- [x] 脚本就绪:`scripts/memory_os_graph_shadow_analyzer.py` — **DONE** `10e5340`
  - 支持 `--hermes-home`, `--json`
  - 报告噪声率(weight<0.3)、contradicts 误标率、重复边、relation 分布、质量门 pass/fail
  - Graceful handling:无文件 exit 1,解析错误 exit 2
- [ ] 读 3.200 上的 `system/graph_layer_shadow.jsonl`,评估:
  - **噪声率**:weight < 0.3 的边占比(当前 injection 已跳过,但 shadow 全量写)
  - **垃圾/误标 contradicts**:contradicts 边是否正确(两类 proposer 的 contradicts 误标率)
  - **重复边**:同一对( from_record_id, to_record_id )被多次提议的频率
  - 判定:质量差(噪声 >50% 或 contradicts 误标 >30%)→ 先修 proposer,**不硬推 injection**
  - **当前状态**:3.200 仅 2 条结晶记录,shadow 文件尚未产出 — 需积累更多结晶后评估

### C.2 injection 开启(质量门过后)

当前代码底座已完成 5/5:
- [x] resolve 可读预览(`_resolve_edge_target_preview()`)
- [x] 跨段去重(`seen` set via `_graph_layer_injection_lines`)
- [x] knob 默认关(`graph_layer_injection_enabled`, default=False)
- [x] shadow-eval 先过(shadow 始终写入,不依赖 knob)
- [x] **budget 感知**:已由 _fit_budget() 跨段裁剪覆盖(Related Memory 优先级 65),不需要额外实现

- [x] 开 injection:knob 设 `graph_layer_injection_enabled=True`(3.200 上) — **DONE** (via `register_override`, 2026-06-24)
  - 验证 injection 行出现在 "Related Memory" 段 — 需积累更多结晶和边后验证

### C.3 量"独有贡献"

- [ ] 对比图谱注入的 record_id 集合与 Crystallized Memory 其余各段的 record_id 集合(通过 `seen` set 的去重率):
  - 方法:开 injection 后,统计 `seen` set 中因 graph injection 而新增的比例
  - 高独有贡献(>30% 新增)→ 图谱有独立价值
  - 高重叠(>90% 已被 Crystallized Memory 覆盖)→ proposer 需要调方向,或图谱价值低
  - 据此定 proposer 调不调、injection 留不留
  - **当前状态**:需更多结晶数据后评估

### C.4 向量 edge proposer(图谱最后一块) — ✅ DONE

> 性质:新的 proposer(source="vector"),**不是新功能面**——它和 structural/llm proposer 共享同一条 `write_governed_edge()` → candidate edge → owner review → promote → active → injection 治理管线。只是新增一种边提议来源。

- [x] 实现 `vector_edge_proposer.py`(258 行):复用同一本地嵌入器(LocalEmbedder),cron 时对 crystallized record pairs 计算语义相似度→超过阈值则提议候选边
  - 复用 `write_governed_edge(proposed_by="vector")`——走现有 candidate→active 治理,不新开路径
  - 与 structural proposer 的去重:同一对 (from_id, to_id) 被多个 proposer 提议 → 合并(保留最强 weight)还是独立?建议合并(按 max weight),避免重复 injection
  - 阈值:初始 0.75(cosine),`vector_edge_proposer_enabled` knob 已注册(default=False,shadow-only)
- [x] 测试:向量 proposer 单元测试(`test_memory_os_vector_edge_proposer.py`) + 与 structural proposer 的去重集成测试
- [x] 3.200 上 `vector_edge_proposer_enabled=True` — **DONE** (via `register_override`, 2026-06-24)
- [x] 3.200 上 `sentence-transformers` 已安装到 gateway venv,`vector_available=True` — **DONE** (`728cec7`)

**C 的完成条件**:质量门过 → injection 开启(含 budget 覆盖确认) → 独有贡献量化 → 向量 proposer 落地 + 测试(✅ DONE)。Injection 底座 5/5。**图谱这层补完 = 整个系统功能面收口,之后不再加。**

C.1 质量数据和 C.3 独有贡献量化依赖真实使用积累;代码底座全部就绪。

---

## D. owner_actions 顺手拆(站位规则,非离散任务)

> 本条可能自然为零操作:如 C 节不触及 owner-review/edge 审批路径,则不做任何改动。**没碰到就不动,不为拆而拆。**

- [x] C 节(图谱)已触及 owner-review/edge 审批路径 — `approve_edge`/`reject_edge` 已实现在 `owner_actions.py` 内,遵循现有模式,未抽模块(最小化改动)
- [x] owner_actions 测试 ≥77 PASS (全量 1525 PASS)
- [x] **不做大爆炸重构**(良性的大,顺手即可)

**D 的完成条件**:这是规则不是任务。**C 完成时本条自动打勾(无论是否有改动)**——零操作是合法的完成状态。 ✅ D 节完成

### D.1 已知设计取舍(化妆级,不做)

- **`candidate_aggregation.py` bypass 在 cluster 之后执行**:`durable-fact single-item bypass`(L477-628)在 cluster 循环(L288-630)之后执行,而非之前。当前顺序:cluster 先跑 → 跳过 singleton(len < min_cluster_size=2) → bypass 再跑 → singleton 过。更优雅顺序:bypass 先跑 → singleton 直接过 → cluster 再跑 → 非 singleton 过。**判定:有意设计,非 bug。** Knob `min_cluster_size` bounds [2,5] 明确排除 1,bypass 是补救性例外通道(走完整 resolver verdict 路径,非直接批准)。当前顺序导致的 `processed_ids` 逻辑复杂化是结构冗余,非正确性问题。**处置:不做。** 下次动 owner_actions/aggregation 重构时顺手调整顺序即可。

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

## F. 记忆质量 · 源头治理(新增, 按 hermes-memory-os-source-gate-quality-spec.md 实施)

> **第一性根因**: 会话记录(event)被默认等同于记忆候选 — `conversation_turn → candidate_allowed=default=True`(inner_drive.py:105),每轮对话自动够格成永久记忆。碎片是这个源头默认造出来的,下游 fact_judge/resolver/owner 门槛在**抗洪**而非**精筛**。
> 性质:**可靠性修复, 非新功能。** 核心动作: `candidate_allowed` 从 `True`(每轮必记)翻转为"基于内容判断" — 记录与记忆分离。
> 纪律:不新建模块、不破 fact_judge"只判断"契约、不在热路径调 LLM(INV-5)、复用现成标记/机制、治理(可逆/审计/owner)贯穿。
> 规约:`docs/resolver/hermes-memory-os-source-gate-quality-spec.md`(内部规划文档, 未入 git — 已对比 HEAD ef648e2 代码 + 3.200 环境审查, 8 项关切已纳入)

### F.0 规约审查结论(2026-06-25)

对比代码库 HEAD ef648e2 + 3.200 环境审查规约, 发现 8 项关切(F1-F8), 均已纳入规约修正:
- **F1 (HIGH)**: `_TRANSIENT_MARKERS` 当前仅 15 个 token(全部问候/确认), 不足以覆盖中文过程碎片 → 两层扩展(层 A 精确子串 30-50+ 中文标记 + 层 B 句式正则)
- **F2 (HIGH)**: recurrence 有两条 bump 路径 — 自动 near-duplicate(对 moment 恒 0) + owner 手动 renew(有效)。S1 不依赖 recurrence 自动递增
- **F3 (MEDIUM)**: `_turn_summary` 格式 `"User: ... | Assistant: ..."` → `_is_obvious_fragment` 必须对 User/Assistant 段分别检测
- **F4 (MEDIUM)**: S2 TTL 写入链已追踪(`_cluster_and_promote` → `write_approved_record` → `provisional_sweep`)
- **F5 (MEDIUM)**: S1 信号模型收敛为被动信任(时间驱动, 单一模型), 不采纳 recurrence/印证
- **F6 (LOW)**: `classify_event_for_inner_drive` 零测试覆盖 → 阶段〇先建测试地基
- **F7 (LOW)**: 部署兼容性确认 — 纯函数变更, 通过 Hermes 模块调度器进入(非 cron, heartbeat 频率由 Hermes 配置决定), 不依赖特定部署环境, 对所有 Hermes 实例通用
- **F8 (LOW)**: 新 knob 边界已定义(`auto_promote_enabled`, `auto_promote_min_age_days`, `moment_provisional_ttl_days`)

### F.1 阶段〇: 测试地基 ✅

- [x] **创建 `tests/plugins/memory/test_memory_os_inner_drive.py`** — `2b1791d`
  - 覆盖 `classify_event_for_inner_drive` 现有 7 种 event kind 分支 (G.0 基础契约)
  - 确保后续碎片逻辑在测试地基上实施, 非在无覆盖代码上叠加
  - 结果: 40 条断言 (25 基线 + 15 G 系列), 全部 PASS

### F.2 阶段一: 源头确定性门 + moment 短 TTL ✅ (`01e0e8a`)

**源头门 (`classify_event_for_inner_drive`, inner_drive.py)**:
- [x] **F.2.1 default 翻转**: `conversation_turn` 分支 `candidate_allowed` 从 `default=True` 改为 `not _is_obvious_fragment(event.summary)`
  - `candidate_explicit` 显式指定优先(保留现有入口)
  - fail-safe: 判不准就放行(allowed=True)
  - `skip_reason` 写 `"source_gate:obvious_fragment"`(复用现有字段)
- [x] **F.2.2 `_is_obvious_fragment(summary)` 实现**:
  - 层 A: CJK 子串匹配(两级: 强标记无条件 / 弱标记仅短段) + Latin 词边界正则（拆为 strong/weak）
  - 层 B 句式正则: 拆为 strong（过程/命令）和 weak（确认/应答），strong 任一段命中即挡，weak 只在两段都 weak 时挡
  - User/Assistant 段分别检测: 正则提取 `User: (.*?) \| Assistant: (.*)`
  - ⚠️ **F.2.2 原版设计缺陷**: 原始"任一碎片 → 整体判 fragment"对 user/assistant 不对称——assistant 简短应答（"好的""ok"）不应该让 user 的技术决定被错杀。已修正为两阶段: Phase 1 Strong（任一段→挡）+ Phase 2 Weak（两段都 weak 才挡）。详见"已完成新增项 — 源头门不对称修正"。
  - 冷启动模式从通用中文/英文过程标记起步, 不硬编码特定环境假设
- [x] **F.2.3 G 系测试(15 条, 核心反证 G.X 攻防验证)**:
  - G.1-G.6 全部 PASS, G.X 禁用源门→碎片穿过→反证成立

**moment 短 TTL (crystallized.py)**:
- [x] **F.2.4 `write_approved_record` per-kind TTL 覆写**:
  - `candidate.kind == "moment"` 且 `decision.provisional` → cap `expires_at` 不超过 `moment_provisional_ttl_days`(默认 3 天)
  - 使用 `min(upstream_expiry, moment_cap)` — 保留上游更短 TTL(如已过期)
  - 非 moment 类型使用常规 TTL(默认 7 天)
  - `provisional_sweep` 现有逻辑不变(不区分类型, moment 更短 TTL 自然生效)
  - ⚠️ **后续修正**: `write_approved_record` 中的 TTL cap 已移除 — owner 显式批准的 `expires_at` 应原样保留。Cap 属于 auto-promote 路径（自动晋升时截断），不属于 owner-approval 路径。详见"已完成新增项 — TTL cap 重定位"。

**配置 (knob_overrides.py)**:
- [x] **F.2.5 注册 3 个新 knob 到 `OVERRIDABLE_KNOBS`**:
  - `auto_promote_enabled`: lane_switch, default=True, allowed=[True,False]
  - `auto_promote_min_age_days`: threshold, default=7, bounds=[3,30], ab_metric="promotion_rate"
  - `moment_provisional_ttl_days`: threshold, default=3, bounds=[1,14], ab_metric="moment_ttl_days"

### F.3 阶段二: 被动信任自动晋升 ✅ (`a78ac4c`)

- [x] **F.3.1 自动晋升触发逻辑**: `auto_promote_provisional_records()` in CrystallizedMemoryService
  - 遍历 `list_provisional_records()` 的 active provisional
  - 检查 `approved_at` 距今 ≥ `auto_promote_min_age_days`(默认 7 天)
  - `canonical_state` 非 `provisional_rejected`(owner 否决过的不晋升)
  - 达标 → `confirm_provisional_record`(现成操作, provisional=False 清 expires_at)
  - knob `auto_promote_enabled=False` → 不晋升(knob 可逆)
  - `dry_run=True` 仅计数不执行
- [x] **F.3.2 S 系测试(7 条, 核心反证 S.X 攻防验证)**:
  - S.1: provisional 多轮未否决 + 存活超 N 天 → 自动晋升 permanent【核心】
  - S.2: owner 否决过 → `list_provisional_records` 已排除, 不晋升(可拦)
  - S.3: `auto_promote_enabled=False` → 不晋升(knob 可逆)
  - S.X: 不调用 auto_promote → 保持 provisional → 反证成立(攻防)
  - dry_run 计数不执行 / 混合年龄正确计数
  - 治理: `confirm_provisional_record` 写 audit 事件, permanent 仍可 invalidate

### F.4 阶段三(可选): fact_judge 精修

- [ ] **F.4.1 fact_judge prompt 微调**: 更明确拒隐性碎片(它本就在判 durable, 只是强化 transient 识别)
- [ ] **F.4.2 层 B 句式模式持续扩展**: 从 `skip_reason` audit 日志驱动迭代新碎片模式

**F 的完成条件**: 阶段〇(测试地基) → 阶段一(F.2.1-2.5 全部打勾 + 全量测试 PASS + G.X 攻防验证通过 + 静态检查 PASS) → 阶段二(F.3.1-3.2 打勾 + S.X 攻防验证) → 阶段三可选。**做完阶段二 = F 打勾。**

---

## 不在本清单内的已知项(显式排除)
以下已知问题/任务**明确不做**,避免"清单打完勾还有一堆事"的错觉:

- ~~**Windows PermissionError**(`test_memory_os_graph_layer.py` 4 failures)~~ → **已修复**（见"已完成新增项"），`_atomic_replace_index()` 使用 `shutil.copy2` + `unlink` 回退方案
- **benchmark SOTA 追踪**:不做。向量价值已通过内部 benchmark 验证(+58% 跨语言召回),不追外部 SOTA。
- **新检索模态**:不做。FTS5 + vector + graph edge 是最终组合。
- **无止境打磨**:不优化非瓶颈路径、不加"可能有用"的缓存、不为监控加监控。
- **install_memory_os.sh 新增的临时脚本 (`memory_os_stabilization_deploy_verify.sh`)**:已删除 (`01367f3`),部署走现有 `install_memory_os.sh` + `deploy_memory_os.py`。

---

## 已完成新增项(稳定化冲刺中实际修复)

以下问题在冲刺过程中发现并修复,不在原清单但属于"让已有的更可靠"范畴:

- [x] **`vector_available` 返回 Python `None` 而非 `False`** — `64d648c`: `bool()` 包装
- [x] **`build_status_report()` 缺少 `vector_available` 字段** — `e208209`:与 `_tool_status_report()` 对齐
- [x] **`memory_os_3_200_monitor.py` 硬编码 `--host hermes-media`** — `6cad1dd`:本地优先,`--host` 可选
- [x] **`install_memory_os` 包安装到系统 Python 而非 gateway venv** — `728cec7`:自动检测 gateway Python,新增 `--target-python`
- [x] **确定性召回地板 (Deterministic Recall Floor v4)** — `e9a3bde`:三项增强,全部落在 `prefetch.py`:
  1. **地板匹配打分** (`_tokenize_for_floor_match` + `_floor_match_score`):纯 Unicode 边界分词 + 子串匹配,零外部依赖,不依赖 FTS5/向量模型/网络/LLM。当 `degradation_level=2`(FTS5+vector 双零命中,query 非空)时按 floor_match_score 降序排列,替代纯 mtime 排序
  2. **关键词表清理 + 停用词过滤** (`_FAST_PATH_STOP_WORDS`):删除 6 个项目术语(提案/治理/证据等),新增 10 个通用内容词(原因/方法/配置/命令等),9 个疑问/功能词作为停用词从 fast_path 过滤至 slow_path。`set_fast_path_keywords()` + `config.py` `fast_path_keywords` 键提供用户级覆盖
  3. **Permanent 核心基线**:降级时所有 permanent 条目按 recurrence 降序排列,确保高频核心记忆在 cap 后存活。仅重排不扩 cap(MAX_PERMANENT=15)
  - `_crystallized_lines()` 返回类型 `list[str]` → `tuple[list[str], int]` 携带 `degradation_level`,section header 动态标注"deterministic floor recall"/"recent — no query match"
  - 已知局限(已入中期路线图):地板仅在 FTS5 返回零命中时触发;FTS5 返回低质量非零命中时被跳过。中期方案:地板作为第三条 lane 进入 RRF 并行融合(`_rrf_union(fts_ids, vec_ids, floor_ids)`)

- [x] **代码审查修复 (8 findings from v4 review)** — `0790984`:针对 v4 实现的全面代码审查(8 angles × 6 candidates → verify → 8 confirmed),全部修复(3 文件,+58/-24):
  1. **(HIGH) `subprocess.TimeoutExpired` 未捕获** → `install_memory_os_plugin.py` 4 个 except 子句均增加 `TimeoutExpired`(与 `CalledProcessError` 是兄弟类,非子类),防止 pip install 超时时 installer 崩溃
  2. **(HIGH) 降级 section header 破坏 source_class + budget priority** → `_section_source_class()` + `_budget_keep_priority()` 用 `title.split(" (")[0]` 去掉括号标注后缀再匹配,降级数据不再被误标为 "other" 或降优先级
  3. **(MEDIUM) 降级路径双重文件读取** → `_floor_match_score` 新增可选 `body_cache` 参数,`_crystallized_lines()` 降级时预读所有 body 一次供排序+主循环共用,消灭 2N 次 I/O
  4. **(MEDIUM) `_check_vector_available()` 语义与 `LocalEmbedder.is_available()` 不一致** → CLI 的 `vector_available` 加注释标注为 import-only(非 model load),区分于 provider 的全量 embedder 就绪检查
  5. **(LOW) `plan_query_route()` 每次 prefetch 调用 3 次** → 加 `@functools.lru_cache(maxsize=4)`,`set_fast_path_keywords()` 中 `cache_clear()` 保证覆盖即时生效
  6. **(LOW) `PERMANENT_BASELINE_N=5` 死常量** → 删除未使用的常量,注释准确描述实际行为(sort by recurrence desc + MAX_PERMANENT cap)
  7. **(LOW) `_floor_match_score()` O(N×T×B) 无文档** → docstring 增加复杂度说明及适用场景(仅真降级路径,生产 N 小,body 几 KB)
  8. **(LOW) `_FAST_PATH_CHINESE_KEYWORDS` 与 `_CHINESE_TOPIC_KEYWORDS` 关键字集分歧** → 注释说明两者服务不同目的(查询路由 vs 话题切换检测),分歧是刻意设计

- [x] **INV-5 核心场景反证测试** — `d04f2ab` + 修复:`d04f2ab` 的原版核心反证测试被证实为**假反证**(TRAP-04 升级版——带测试、测试 PASS、但测试不咬):
  - **假反证根因(双重抵消)**:(1)20 条记录 ≤ MAX_TOTAL=20 → cap 永不截断;(2)target 先写(id 字母序最小)→ recurrence sort `(-recurrence=0, rid)` 在 level>=1 时天然把 target 排最前,地板逻辑完全被绕过。验证:禁用地板子串打分 → 测试仍然 PASS。
  - **修复(代码层)**:`prefetch.py:1249` `degradation_level >= 1` → `degradation_level == 1`,recurrence sort 不再覆盖 level=2 的地板文件排序
  - **修复(测试层)**:重写核心反证测试——30 条噪声先写(id 小、mtime 新)+ 3 条 target 后写(id 大、mtime 老),共 33 条 > MAX_TOTAL=20。mtime 排序和 rid 排序都把 target 排末尾(位 30-32),只有地板子串匹配能把它们拉进前 15。新增断言 4(target 排在噪声前,地板真把它推上去了)+ 断言 6(rid 位置反证 ≥30)
  - **验证**:禁用地板逻辑 → 测试 FAIL ✓;启用地板逻辑 → 测试 PASS ✓
  - 其他 5 条辅助测试不变(`test_floor_match_score_*`, `test_tokenize_for_floor_match_*`, `test_deterministic_floor_recall_header_annotation`)
  - 注:这是系统化调试的铁律例证——不是"测试 PASS=安心",而是"你能确认移掉被测逻辑后测试必然红吗?"

- [x] **代码审查修复 #1-#10（Part A, 8 文件）** — 对稳定化冲刺 `a2ba341..bedbd81` 的 8 角度审查,10 个发现全部修复:
  - **#1 datetime TypeError**: `crystallized.py` 两处 `except ValueError` → `except (ValueError, TypeError)`,预防 `datetime.fromisoformat` 对非标准格式抛出 TypeError
  - **#2 auto_promote 死代码**: `cognitive_loop.py` `_provisional()` 中接入 `auto_promote_provisional_records()` 调用链
  - **#3 ValueError→专用异常**: `crystallized.py:100` `raise ValueError` → `raise CrystallizedApprovalError`
  - **#4 provisional 写入门**: `crystallized.py` `confirm_provisional_record` 添加 StructuralWriteGate 检查
  - **#5 source gate 正则边界**: `inner_drive.py:95` `(\s+the)?` → `(\s+the\b)?` 加词边界,防止误匹配 "therapy"/"theme"
  - **#6 source gate 行锚定**: `inner_drive.py:97` 模式末尾加锚定
  - **#7 edge owner_effect 时序**: `owner_actions.py` 将 `owner_approved_edge=True` 移到 result 检查之后
  - **#8 edge 存在性验证**: `owner_actions.py` edge action 增加 index 查询
  - **#9 silent except**: `prefetch.py` 两处 `except Exception` 添加 `build_error_record` 记录
  - **#10 severity 规范**: `prefetch.py` `severity="warn"` → `severity="warning"`（canonical 值）
  - 3 文件变动的轻量修复,无架构变更

- [x] **默认配置修复（Part B, 6 项）** — 调查发现 4 个核心 cron + 2 个核心模块在默认安装中处于禁用/暂停状态,导致认知循环断裂:
  - **cognitive_loop 默认启用**: `install_memory_os.sh` default 从 `"no"` 翻转为 `"yes"`（与部署核心保障 spec D1 对齐）
  - **deep_reflection 默认启用**: manifest `"enabled": True` + `install_memory_os_plugin.py` production-safe preset + DEEP_REFLECTION_CONFIG_DEFAULTS
  - **speak_gate 默认启用**: manifest `"enabled": True`（would-send 模式,不实际发送,仅记录决策）
  - **active-closure cron 扩展 5→9**: `memory_os_owner_cron_onboarding.py` 新增 `candidate_aggregation`, `fact_judge`, `expression_feedback_request`, `memory_sources_feedback_request`
  - 测试更新: `test_memory_os_owner_cron_onboarding.py` (5→9), `test_memory_os_plugin_install.py` (5→9 + `enabled: False→True`), `test_deep_reflection_module.py` (`enabled: False→True`)

- [x] **部署核心保障 spec 审查 + D1** — Opus 4.8 编写的 `hermes-memory-os-deployment-core-guarantee-spec.md`:
  - 逐行对照 `install_memory_os.sh` 源码验证,所有声明准确
  - 确认两层启用架构:系统层(shell installer → systemd/cron timers) vs 模块层(Python manifests)
  - D1 已应用: `cognitive_loop` 默认 `"yes"`（核心三件套:heartbeat + cognitive_loop + index-sync 全部默认开）
  - D2（`deploy_verify_core` 部署后验证 guard）已实施: is-active + is-enabled 双查,非 systemd 环境降级 WARN,框线错误摘要到 stderr,尊重 `--skip-verify`。D2 结构烟雾测试已添加（`test_d2_verify_install_fail_loud_structure`）
  - D3（preset 显式 `ENABLE_COGNITIVE_LOOP=1`）由 D1 覆盖,冗余但可做防御性加固

- [x] **TTL cap 重定位** — F.2.4 实现的 TTL cap 被从 `write_approved_record` 移除:
  - 根因: cap 在 owner-approval 路径截断了 owner 显式批准的 TTL(7d→3d, 10d→3d),导致 `test_memory_os_owner_actions.py` 2 个测试失败
  - 修复: cap 从 `crystallized.py:108-120` 移除,owner 显式批准的 `expires_at` 原样保留
  - Cap 属于 auto-promote 路径（`auto_promote_provisional_records` 自动晋升时截断）,不属于 owner-approval 路径
  - 设计原则: owner 显式批准的 TTL 是 human-trust boundary,不应被自动 cap 覆盖

- [x] **Windows PermissionError 修复（graph_layer 4 测试）** — `_atomic_replace_index()`:
  - 根因: Windows SQLite 打开文件时不带 `FILE_SHARE_DELETE`,当测试持有连接时 `os.replace` 失败
  - 修复: `index.py` 新增 `_atomic_replace_index()` helper,在 Windows `PermissionError` 时回退到 `shutil.copy2` + `src.unlink()`
  - 生产平台(Linux)不受影响;修复确保 Windows 开发/测试环境可用
  - 原在"不在本清单"中标注为"暂不修",现已修复并从排除列表移除

- [x] **sprint 引入的测试断言修复（3 测试）**:
  - **self_evolution ×2**: sprint 新增 `auto_promote_min_age_days` + `moment_provisional_ttl_days` 到 OVERRIDABLE_KNOBS → bounded knob 3→5 → ops_gate 报告 4→6 → 断言更新
  - **knob_ab_eval ×1**: sprint 新增 2 个含 `ab_metric` 的 knob → 全局路径读取计数膨胀 + `status()` 未传 `_store_root` → 修复 `_store_root=self.hermes_home`
  - 注: 这些失败在 sprint commit `01e0e8a` 已存在,非本会话引入;但按 systematic-debugging 原则追根因修复

- [x] **源头门不对称修正（F.2.2 设计缺陷）** — Opus 4.8 审查发现:
  - **误杀链**: `"User: 我决定用PostgreSQL做主库 | Assistant: 好的"` — user 陈述技术决定,assistant 回"好的"（weak marker）→ 原逻辑"任一段碎片→整轮挡"错杀了 user 的知识
  - **根因**: F.2.2 的"任一碎片→整体 fragment"对 user/assistant 不对称——知识几乎总在 user 段,assistant 简短应答是正常对话结构。源头错杀 = 下游 fact_judge 无机会兜底
  - **修复**: Latin markers 拆为 strong（19 个过程词）和 weak（5 个确认词）；Layer B regex 拆为 strong（10 个过程模式）和 weak（4 个确认模式）；新增 `_segment_is_weak_fragment()` 单段判定 helper
  - **新逻辑**: Phase 1 Strong（过程/命令,任一段→挡,不变）+ Phase 2 Weak（确认词,只在两段都 weak 或整轮极短时才挡）
  - **受影响的测试**: `test_g6_assistant_fragment_in_substantive_turn`（`False`→`True`，核心修复）+ `test_g6_user_fragment_in_substantive_turn`（`False`→`True`）+ 新增 2 个 CJK weak marker 场景测试
  - **验证**: inner_drive 42/42 PASS, G.X 反证仍成立

- [x] **9 测试失败 → 0** — 最终测试: **1582 passed, 0 failed, 3 skipped**（全量通过,零失败）
  - 静态检查全部通过（`write_surface_check.py`, `import_cycle_check.py`, `static_hygiene_check.py`）
  - **后续**: 源头门不对称修正新增 2 测试 → **1584 passed, 0 failed, 3 skipped**
- [x] **compaction stability F10 回归修复 (C2×_capture_turn_operations anchor 破坏)** — `128199d`: C2 anchor 持久化 + `_capture_turn_operations` rebuild 交互导致 resumed deferred-task anchor 丢失 "response rule: Continue this deferred foreground task"。新增 `_is_owner_action_anchor()` helper + guard + `prefetch.py` `_current_task_anchor_lines` `[:6]` 截断修复。A.17 对抗验证 (无 guard FAIL / 有 guard PASS)。
- [x] **compaction stability F11 Windows embedder guard + response rule 裁剪** — `3a1b360`: win32 上 embedder 返回 unavailable 防 segfault; response/compression rule 永不被裁剪。1617 passed / 8 skipped / 0 failed。

---

## 边界声明(这份清单的"完"在哪)
**做完 A+B+C+D+E+F+G+H+I+J+K+L = 扎实了。**(E 可选:用得上 RAGFlow 才补,用不上留空也算完 — 但需显式记录留空决定。) F 节是可靠性修复(非新功能), 做完阶段二 = F 打勾; 阶段三可选。G 节跨会话召回已完成。H 节是双机诊断确认的可靠性修复(非新功能)。I 节是跨会话连续性补缺(维护,非新功能), 已完成。J 节是 prefetch 预算优先级修正(latent fix,维护), 已完成。K 节是 foreground_only 保留 Last Session, 已完成。L 节是跨会话 zombie 锚点修复(维护,非新功能), 已完成。之后:
- 功能面收口(C 图谱补完,不再加模块/功能)。
- 可靠性收口(A 静默失败治完、B 生产信号补上)。
- 进入「使用 + 维护」模式:真的用它,让记忆攒起来,在真实使用里发现真问题再修(像会话拼接那样——用出来的,不是想出来的)。

**不在这份清单里的,就是"不做":** 不追 benchmark SOTA、不加新检索模态、不为优化而优化、不无止境打磨。**清单打满勾,就是收工。**

**维护模式进入后的轻量规则**(不扩展此清单):
- Bug fix 标准:静默失败 / 数据损坏 / 生产 probe 失败 → 修。性能优化 → 仅在瓶颈实测后修。
- 判定权:owner(你)决定什么是"真实使用里发现的真问题"。
- Windows 测试:不作为 gate(生产平台 Linux),但跨平台 PR 欢迎。

**当前进度 (2026-06-30)**:
- **A 节**:5/5 ✅ 全部完成
- **B 节**:4/8 (4 已确认 + 4 待使用积累后验证)
- **C 节**:代码底座 5/5 + 向量 proposer ✅;质量数据需积累后评估
  - 图谱 V2 架构设计完成 (`memory-os-graph-layer-v2-architecture.md`):entity 索引底座 + 关联性/治理性双出口,0% 实施
- **D 节**:✅ 完成(零操作合法)
- **E 节**:P0/P1 ✅;P2/P3 可选,未实施
- **F 节**:阶段〇+一+二已完成(3/4, F.4 可选精修未实施)
- **G 节**:跨会话记忆召回 ✅
- **H 节**:embedder=0 + candidate_aggregation 全部修复 ✅
- **I 节**:Last Session Anchor ✅ (`ea47ec0` — 会话结束 foreground 摘要,补跨会话连续性缺口)
  - I.2.6 附注: `_budget_keep_priority` 初始值 15, J 节修正为 62 (`eef05ba`)
- **J 节**:Prefetch 预算优先级修正 ✅ (`eef05ba` — Last Session 15→62, 翻转 vs Crystallized 相对顺序, latent fix)
- **K 节**:foreground_only Last Session 保留 ✅ (`2c23838` — foreground_only 无条件 append Last Session, 补"继续"场景丢失时序上下文缺口)
- **L 节**:Zombie Active Task Anchor 修复 ✅ (`d19d2df` + `8627ec8` — 三层防御: on_session_end tombstone + 24h 年龄门 + 跨会话 marker; 代码审查 5 findings 全部修复)
- **compaction stability**:阶段一 C1+C2 ✅ + CR 修复 F1-F9 ✅ + 回归修复 F10-F11 ✅
- **向量解耦**:设计文档已复核修正(3 处事实错误更正),D-BUG~D5 全部未实施(0%)
- **图谱路线图** (`memory-os-graph-layer-roadmap.md`):已删除 — V2 架构文档已取代,原"DDL-only"声明已过时
- **最终测试**: 1661 passed, 8 skipped, 0 failed (140 测试文件,4 目录)
- **静态检查**:全部通过 ✅

- [x] **H.1 ① embedder=0 修复** — `648718c`: `memory_os_index_sync.py` 在创建 index 后设置 `index._embedder = LocalEmbedder()`，覆盖 `sync_from_store`（增量）和 `try_rebuild_from_store`（全量）两条路径。embedder 不可用时 graceful degrade 维持 FTS5。

- [x] **H.2 ② candidate_aggregation 三处设计缺陷修复** — `2c59c3f` + `d3c1fe7`:
  - H.2.1 `already_triaged` terminal-only（只排除 rejected/demoted/discarded，promote 后的 owner_eligible 14 天未处理可重新进入 pending）
  - H.2.2 index 读取候选时调用 `resolve_candidate_effective_state()`（不再全显示原始 bridge_state）
  - H.2.3 compact 无条件触发（不依赖本轮 triage 结果）
  - 后续强化 (`d3c1fe7`): effective state 贯穿所有 pipeline stage、`seen_cids` tracker、`absorbed` terminal 状态、`inf-age` guard（CR findings after narrowing）

- [x] **time-rot 修复（speak expression preview 测试）** — `ba5d6a1`: 3 个测试的 `output_record["ts"]` 和 `would_send["ts"]` 从硬编码 `2026-05-26` 改为 `datetime.now(timezone.utc).isoformat()`。与 `54ad9d2` 同一模式 — 31 天前的硬编码日期被 digest 时间窗口过滤导致 IndexError。同时修复 `test_render_digest_shows_bounded_speak_expression_preview`、`test_render_digest_hides_transcript_like_speak_expression_preview`、`test_allow_speak_once_sends_once_when_explicit_delivery_enabled`。

---

## H. 候选与索引可靠性修复（双机实地诊断发现，2026-06-26）

> **性质**: 可靠性修复，非新功能。代码 trace + 10.20.2.66/3.200 双机验证确认根因。
> **规约**: `docs/resolver/hermes-memory-os-embedder-demote-sweep-specs.md`（gitignored，本地诊断文档）。
> **纪律**: 最小化改动、不改 governance 管线、不新增抽象层、测试覆盖。

### H.1 ① embedder=0 — cron index_sync 嵌入器缺失

- [x] **H.1.1 `memory_os_index_sync.py`** — 创建 index 后、rebuild/sync 前，设置 `index._embedder = LocalEmbedder()` — **DONE** `648718c`
  - 复用 provider 路径同款 `LocalEmbedder` + `is_available` 判断，不新建
  - graceful degrade: embedder 不可用 → 维持 FTS5，依赖 P0.2 guard 不清空已有 embedding
  - 修复同时覆盖 `sync_from_store`（增量）和 `try_rebuild_from_store`（全量）两条路径
- [ ] **H.1.2 验收**: E.1 memory_embeddings > 0（核心）、E.2 graceful degrade、E.3 跨语言召回、E.X 反证
  - 代码底座就绪（`648718c`），验收需在 3.200 上观察 `memory_os_index_sync.py` 运行后 `memory_embeddings` 表行数

**H.1 的完成条件**: H.1.1 打勾 ✅ + E.1-E.X 攻防全部 PASS（代码底座就绪，验收待 3.200 部署后观察）。

### H.2 ② candidate_aggregation — 三处设计缺陷

**根因已通过逐行代码 trace + 6/1 候选完整时间线还原确认**（详见 specs doc 第二节）。

- [x] **H.2.1 line 116 `already_triaged` 无差别永久排除**（🔴 高） — **DONE** `2c59c3f` + `d3c1fe7`
  - 问题: `pending = [c for c in candidates if c.candidate_id not in already_triaged]` — promote 后的候选和 demote 后的候选**同等待遇**，都从 pending 永久消失
  - 后果: 候选被 promote 到 `owner_eligible` 后，即使 owner 永不处理，`_demote_aged` 永远看不到它。需重新评估长期未处理的 `owner_eligible` 候选
  - 修复: `already_triaged` 改为 terminal-only（只排除 `rejected`/`demoted`/`discarded`），promote 后的 `owner_eligible` 候选在 14 天未处理后重新进入 pending → 可被 demote
  - 后续强化 (`d3c1fe7`): effective state 贯穿所有 stage、`seen_cids` tracker 防重复、`absorbed` terminal 状态、`inf-age` guard

- [x] **H.2.2 SQLite index 不应用 triage 覆盖**（🟡 中） — **DONE** `2c59c3f`
  - 问题: 读 `candidates.jsonl` 原始 `bridge_state`，不调用 `resolve_candidate_effective_state()`。10.20.2.66 上 113 条全显示 `inner_drive_candidate`，但其中 112 条已被 triage
  - 修复: `_index_crystallized_candidates()` 读取 triage 记录并调用 `resolve_candidate_effective_state()`，index 显示有效状态而非原始 bridge_state
  - 测试: 现有 `test_candidate_aggregation_logic.py` 覆盖有效状态逻辑

- [x] **H.2.3 compact 触发条件耦合 triage**（🟡 低） — **DONE** `2c59c3f`
  - 问题: `if promote_results["promoted_count"] + demote_results["demoted_count"] > 0:` → 一轮无 triage → compact 不跑
  - 修复: compact 改为无条件触发（每次 aggregation 都执行），不依赖本轮 triage 结果。`compact_candidate_queue` 本身逻辑正确（通过 `resolve_candidate_effective_state` 正确识别需归档的候选）

**H.2 的完成条件**: H.2.1 + H.2.2 + H.2.3 全部打勾 ✅ + 各自测试 PASS + 全量回归 PASS。**H.2 完成 (**`2c59c3f` + `d3c1fe7`**)**

---

## G. 跨会话记忆召回（读写分离修补时序断口）

> **性质**: 不碰结晶管道，不改 governance。**只加一段 prefetch 读出面** — 从 candidates.jsonl 取 source-gate 签名 + events JSONL 取摘要，跨会话注入时标记 "跨会话·待结晶"。
> **纪律**: 一函数 + 一行调用 + knob 注册 + 测试。无新存储、无新管道、无 schema 变更。

### G.1 新增 "Recent Cross-Session" prefetch 段

- [x] **G.1.1 prefetch.py** — `42d2ed9` ✅: 新增 `_recent_cross_session_lines(store, *, session_id, max_items=5, max_age_hours=48)`
  - 读 `candidates.jsonl` → 提取 `source_event_ids` 作为 source-gate 签名集
  - 读 `store.read_events()` → 过滤: (a) event_id 在签名集中 (b) 非当前 session (c) 在 `max_age_hours` 内
  - 按 ts 降序、cap `max_items`、每条标记 `[跨会话·待结晶·{N}h前]`
  - knob `recent_cross_session_enabled=False` → 返回 `[]`
  - 失败不阻断: candidates.jsonl 不存在 / 事件全空 / JSON 解析失败 → 返回 `[]` + error_record
- [x] **G.1.2 prefetch.py `_build_prefetch_sections()`** — `42d2ed9` ✅: Continuity Bridge 和 Conversation Carryover 之间加一行 `_append_section(sections, "Recent Cross-Session", _recent_cross_session_lines(...))`
- [x] **G.1.3 knob 注册** (`knob_overrides.py`) — `42d2ed9` ✅: 3 个新 knob
  - `recent_cross_session_enabled`: lane_switch, default=True, allowed=[True, False]
  - `recent_cross_session_max_age_hours`: threshold, default=48, bounds=[6, 168]
  - `recent_cross_session_max_items`: threshold, default=5, bounds=[1, 10]
- [x] **G.1.4 seen 去重** (`prefetch.py`) — `5970744` ✅: Continuity Bridge 与 Recent Cross-Session 共享 `seen` set
  - `_continuity_bridge_lines()` 加 `seen` 参数，注入后写 event ID 到 seen
  - `_recent_cross_session_lines()` 加 `seen` 参数，注入前检查 seen，注入后写 seen
  - `_build_prefetch_sections()` 传递 seen 到两段
  - 解决: cron/mailbox/governance 事件同时满足两段条件时 → 只注入一次
  - 两段各自保留独立职责: Bridge = 源类多样性，Recent = 内容质量过滤

### G.2 测试

- [x] **G.2.1 单元测试** (`tests/plugins/memory/test_memory_os_prefetch.py`):
  - 跨会话事件在候选签名中 → 被召回（`[跨会话·待结晶·Nh前]` marker）
  - 当前会话事件 → 被排除
  - candidates.jsonl 不存在 → 空段不抛异常
  - 超过 `max_age_hours` 的事件 → 被排除
  - `recent_cross_session_enabled=False` → 空段
- [x] **G.2.2 反证测试**: session_id 空守卫 + knob 禁用守卫 → 跨会话事件不可见 → 反证成立 ✅
- [x] **G.2.3 全量回归** (初始): 1591 passed, 0 failed, 3 skipped (G 节 +6 测试) ✅
- [x] **G.2.4 seen 去重回归** (`5970744`): 1591 passed, 0 failed, 3 skipped + 静态检查全绿 ✅

**G 的完成条件**: G.1 全部打勾 ✅ + G.2 测试全部 PASS ✅ + 全量测试零回归 ✅ + 静态检查 PASS ✅。**G 节完成 (`42d2ed9` + `5970744`)。**

---

## I. Last Session Anchor（会话结束 foreground 摘要，跨会话连续性补缺）

> **性质**: 维护——补"上一个会话做了什么"这个缺失的 foreground 摘要。不是新功能扩张，是补跨会话连续性的可靠性缺口。
> **规约**: `docs/resolver/hermes-memory-os-last-session-anchor-spec.md`（gitignored，本地设计文档）。
> **纪律**: 确定性提取（复用 `_looks_like_operation_context`，INV-5）、JSONL append（同 `active_task_anchor` 模式）、prefetch 注入不带"待结晶"标记（陈述事实语气）、fail-open。

### I.1 根因

系统有 Working Memory（会话内衰减）、Task Anchor（会话内跨 compaction）、Continuity Bridge（cron/governance 系统事件）、Recent Cross-Session（≤48h 跨会话事件，但每条标记 `[跨会话·待结晶]`）、Crystallized（长期权威）——**但没有一个能回答"上一个会话做了什么"**。agent 问"上一轮"只能从 Recent Cross-Session 的"待结晶"标记内容猜，而"待结晶"标记让最近内容显得比更早的已固化内容**更不可信**（逆向激励）。

### I.2 实现

**生成（`__init__.py`）**:
- [x] **I.2.1** `_last_session_anchor_path(roots)` + `_last_session_anchor_record(*, session_id, foreground_summary, ended_at)` — JSONL schema（`session_id`/`ended_at`/`foreground_summary`/`schema_version`）
- [x] **I.2.2** `_extract_foreground_session_summary(messages)` — 确定性 1-3 行摘要提取，复用 `_looks_like_operation_context`（同 task anchor 的 marker 匹配器），无 LLM/网络（INV-5）。逻辑：user 消息首行作主题 + assistant/tool 中检测到的操作行 + 最后一条实质性 assistant 作结论 → ≤3 行。无 user 交互且无 substantive assistant → 返回 `""`（空会话不写锚）
- [x] **I.2.3** `on_session_end(messages)` — 替换原 no-op：提取摘要 → 非空则写 `last_session_anchor.jsonl`（JSONL append）+ `self._audit("last_session_anchor_recorded", ...)`

**注入（`prefetch.py`）**:
- [x] **I.2.4** `_last_session_lines(store, *, session_id, seen)` — 读 `last_session_anchor.jsonl`，选 `ended_at` 最大的非当前会话锚，格式化 `"- 上一次会话({N}h前): {_redact(summary)}"`（陈述事实语气，无"待结晶"标记）。文件不存在/JSON 坏行/ended_at 解析失败/空 foreground → 返回 `[]`（fail-open）
- [x] **I.2.5** `_build_prefetch_sections` — 在 Continuity Bridge 之后、Recent Cross-Session 之前插入 `### Last Session` 段
- [x] **I.2.6** 注册：`_section_source_class` → `"last_session"`、`_budget_keep_priority` → 15（介于 Identity Memory 10 和 Continuity Bridge 20 之间；**后于 J 节修正为 62，见 `eef05ba`**）、`write_surface_check` → `working_state_anchor_persistence`

### I.3 测试（21 条，`test_memory_os_last_session_anchor.py`）

- [x] **A.1** 有 foreground 内容 → `last_session_anchor.jsonl` 写入【核心】
- [x] **A.2** 空会话/纯系统事件 → 不写锚
- [x] **A.3** 提取路径无 LLM/网络（INV-5，AST 验证：只调用 `_clip`/`_content_text`/`_looks_like_operation_context`）
- [x] **A.4** 新会话 prefetch → `### Last Session` 段注入【核心】
- [x] **A.5** 多个历史会话 → 取最近非当前
- [x] **A.6** 当前会话自己的锚不被注入
- [x] **A.7** Last Session 段不含"待结晶"标记
- [x] **A.8** `seen` 去重 marker 写入
- [x] **A.9** ClawBot 场景回归：会话1分析 Group L → 会话2问"上一轮"→ 命中 Group L【核心场景】
- [x] **A.X** 禁 `on_session_end` 写锚 → A.1/A.4 必 FAIL（攻防）
- [x] **A.Z** 验证注入行不含 `跨会话·待结晶`，只含 `上一次会话`（攻防）
- [x] **边界**: 空消息、纯 tool 消息、list-based content、JSONL 坏行、多会话最近优先

### I.4 验证

- [x] 新功能测试: 21/21 PASS
- [x] 攻防验证: A.X（禁写→无注入）✅ + A.Z（无待结晶标记）✅ + A.Y（取最近非当前）✅
- [x] 全量回归: **1638 passed, 8 skipped, 0 failed**（139 测试文件，4 目录）
- [x] 静态检查: `write_surface_check` PASS（0 unclassified）+ `import_cycle_check` PASS（0 cycles）
- [x] Commit: `ea47ec0`（4 files, +646 lines）

**I 的完成条件**: I.2 全部打勾 ✅ + I.3 测试全部 PASS ✅ + I.4 全量回归零失败 ✅ + 静态检查 PASS ✅。**I 节完成 (`ea47ec0`)。**

---

---

## J. Prefetch 预算优先级修正（Last Session vs Crystallized 矛盾，latent fix）

> **性质**: 维护——修正 `_budget_keep_priority` 表中一处与设计目的矛盾的优先级设置。不是新功能，是让已有机制在边界条件下行为正确。
> **规约**: `docs/resolver/hermes-memory-os-prefetch-priority-fix-spec.md`（gitignored，本地设计文档）。
> **纪律**: 一行常量改动（15→62），不动注入顺序、不动召回逻辑、不动确定性地板、不动 seen 去重。

### J.1 根因

Last Session Anchor 的设计目的是"问'上一轮'时，最近会话锚是时序权威，要压过更早的已固化 Crystallized 旧内容"。但 `_budget_keep_priority` 表中 **Last Session(15) 远低于 Crystallized Memory(60)** —— `_fit_sections_budget` 在预算紧张时按优先级升序裁段，Last Session 是第二批被砍的，而 Crystallized 远在其后。

生产环境（3.200）`prefetch_char_budget` 默认 20000（config.py）/ 安装器最低 5500，典型 prefetch 输出 ~2000-4000 字符，drop 循环几乎不触发——**此 bug 在生产上是 latent（潜在的），非 active（活跃的）**。触发条件是显式调低预算、未来 Crystallized Memory 大幅增长、或低配/测试环境。但优先级表的不一致是客观代码缺陷，不因其当前不触发而消失。

### J.2 实现

- [x] **J.2.1** `_budget_keep_priority` — `"Last Session": 15` → `"Last Session": 62`（`eef05ba`）
  - 62 > 60（Crystallized Memory）：翻转 Last Session vs Crystallized 这一对的相对顺序
  - 62 < 105（Current Foreground Task）：当前任务仍最高保护级
  - 62 < 65（Related Memory）：不扰动其他段的相对关系
  - 不改注入顺序（独立于预算优先级）、不改 `_fit_sections_budget` 逻辑

### J.3 测试（5 条，`test_memory_os_prefetch.py`）

- [x] **P.1** `_budget_keep_priority("Last Session") == 62 > 60 == _budget_keep_priority("Crystallized Memory")`【核心】
- [x] **P.2** 预算紧张（Last Session + Crystallized，只够一个）→ 保留 Last Session，砍 Crystallized【核心场景】
- [x] **P.3** `_budget_keep_priority("Last Session") == 62 < 105 == _budget_keep_priority("Current Foreground Task")`
- [x] **P.4** 预算充足 → 两段都注入
- [x] **P.X** monkeypatch 优先级回 15 → Last Session 被砍，Crystallized 存活（反证攻防）

### J.4 验证

- [x] 新功能测试: 5/5 PASS
- [x] 攻防验证: P.X（回退到 15 → Last Session 先被砍）✅
- [x] 全量回归: **1643 passed, 8 skipped, 0 failed**（+5 tests，零回归）
- [x] 静态检查: `write_surface_check` PASS（0 unclassified）+ `import_cycle_check` PASS（0 cycles）
- [x] Commit: `eef05ba`（2 files, +112/-2 lines）

**J 的完成条件**: J.2 全部打勾 ✅ + J.3 测试全部 PASS ✅ + J.4 全量回归零失败 ✅ + 静态检查 PASS ✅。**J 节完成 (`eef05ba`)。**

---

## K. foreground_only 模式保留 Last Session（"继续"场景丢失时序上下文）

> **性质**: 维护——修正 `foreground_task_only=True` 时 prefetch 输出只含 Current Foreground Task、排除 Last Session 的缺口。不是新功能，一行改动。
> **规约**: `docs/resolver/hermes-memory-os-l3-followups-spec.md`（gitignored，本地设计文档）。
> **纪律**: 无条件 append（`_last_session_lines` 在无锚时返回 `[]` 天然安全），不动 ingress 分类链、不动 `_build_prefetch_sections` 正常路径。

### K.1 根因

L3 体感验证发现：有 active anchor 时说"继续"→ Last Session 丢失。根因追踪（经 `ingress.py` 分类链实测）：

- "继续" ∈ `_CURRENT_TASK_CONTINUE_MARKERS` → `classify_ingress` 返回 `intent="continue_current_task"`, `foreground_task_only=True`
- `_refresh_current_task_anchor_from_query:867` 设 `self._foreground_task_only_prefetch = True`
- `prefetch.py:233` `foreground_task_only` 分支只用 `current_task_section`（单段 Current Foreground Task）构建输出，**Last Session 不在其中，被整段排除**

**澄清（初版规约的根因分析与代码实测不一致）**：`"上次做到哪了"` 本身不触发 `foreground_only`——ingress 分类实测返回 `unclassified`，走正常全段 prefetch。L3-3 中 `"上次做到哪了"` 的 Last Session 丢失（如果发生的）根因是旧优先级 bug（Last Session 15 < Crystallized 60，已在 J 节修复），而非 foreground_only 排除。

### K.2 实现

- [x] **K.2.1** `prefetch.py:233` — `foreground_task_only` 分支内追加一行（`2c23838`）:
  ```python
  if foreground_task_only and current_task_section:
      _append_section(
          current_task_section, "Last Session",
          _last_session_lines(store, session_id=session_id, seen=None),
      )
      context = _fit_budget(_format(current_task_section), budget_chars)
  ```
  - `seen=None`：foreground_only 下只有两段（Current Foreground Task + Last Session），无跨段重复可能
  - 无条件注入：`_last_session_lines` 在无锚时返回 `[]`，`_append_section` 自动跳过空列表（fail-open）
  - 覆盖四种 foreground_only 触发 intent：`continue_current_task` / `explicit_deferred_resume` / `defer_current_task` / `cancellation`——皆受益于 1 行时序上下文
  - 零新函数、零新 import、零新正则

### K.3 测试（5 条，`test_memory_os_prefetch.py`）

- [x] **Q.1** `foreground_only=True` + 有 Last Session 锚 → Last Session 保留注入【核心】
- [x] **Q.2** 无 `last_session_anchor.jsonl` → `foreground_only` 仍正常返回 Current Task，不报错（fail-open）
- [x] **Q.3** `foreground_only=False` 正常路径 → Last Session 仍在正常位置，不被扰动
- [x] **Q.4** 预算紧张 + `foreground_only` → Current Foreground Task 存活（优先级 105 > 62）
- [x] **Q.X** monkeypatch 移除 `foreground_only` 分支的 Last Session append → Q.1 必 FAIL（反证攻防）

### K.4 验证

- [x] 新功能测试: 5/5 PASS
- [x] 攻防验证: Q.X（移除 append → Last Session 消失）✅
- [x] prefetch 全量: 66/66 PASS（+5 tests，零回归）
- [x] 全量回归: **1648 passed, 8 skipped, 0 failed**（+5 tests，零回归）
- [x] 静态检查: `write_surface_check` PASS（0 unclassified）+ `import_cycle_check` PASS（0 cycles）
- [x] Commit: `2c23838`（2 files, +189 lines）

**K 的完成条件**: K.2 打勾 ✅ + K.3 测试全部 PASS ✅ + K.4 全量回归零失败 ✅ + 静态检查 PASS ✅。**K 节完成 (`2c23838`)。**

---

## L. Zombie Active Task Anchor 修复（跨会话记忆污染，2026-06-30）

> **性质**: 维护——修复 `active_task_anchor.jsonl` 中已完成会话的活跃锚点从未被标记为完成（tombstone），导致新会话恢复旧锚点、造成"记忆混淆"的 bug。不是新功能，三层防御加固已有锚点生命周期。
> **纪律**: 三层防御（tombstone + age gate + marker）、append-only JSONL 语义不变、新增 13 个确定性测试（无 LLM 依赖）、代码审查 5 findings 全部修复。最小化改动: 仅 `__init__.py`（77 行变更）+ 测试文件。

### L.1 根因

用户发现新会话的 `Current Foreground Task` 仍显示 12 小时前的旧任务（"安装 ComfyUI 并配置 IPAdapter 插件"），同一旧 session 同时出现在 `Current Foreground Task` 和 `Last Session` 两个段中。

追踪定位到 `__init__.py`:
1. `on_session_end` 写入 `last_session_anchor.jsonl`，但从未 tombstone `active_task_anchor.jsonl` 中的活跃记录——`status` 永远保持 `"active"`
2. `_read_latest_active_task_anchor` 在 `initialize` 时读取 `active_task_anchor.jsonl`，遇到 `status="active"` 就恢复——不检查该锚点是否属于已结束的会话
3. append-only JSONL 语义下，"最新记录胜出"意味着只有显式写 tombstone 才能改变状态

### L.2 三层防御

| 层 | 位置 | 机制 | 防御场景 |
|---|------|------|---------|
| L1 | `on_session_end:527` | 会话结束时 tombstone 活跃锚点（`status=completed`），在 foreground guard **之前**执行 | 正常会话结束 |
| L2 | `_read_latest_active_task_anchor:1090` | `max_age_hours=24` 年龄门：超时拒绝；损坏时间戳 + age gate 活跃 → 拒绝 | 会话异常退出，tombstone 未执行 |
| L3 | `_read_latest_active_task_anchor:1106` | 跨会话标记 `[跨会话恢复, {N}h前/{N}m前, 原会话: {session_id}]` 注入到恢复的锚点 | L1/L2 都失效时的透明性兜底 |

**关键设计决策**:
- [x] **L.2.1** tombstone 在 `on_session_end` 的 foreground guard **之前**执行（CR finding #1）: 纯系统/工具会话无 user foreground → 不会写 `last_session_anchor.jsonl`，但仍需清理活跃锚点
- [x] **L.2.2** 时间戳解析只做一次，age gate 和 marker 块复用同一 `created_at`（CR finding #3）
- [x] **L.2.3** 子小时锚点显示分钟级标签（`5m前` 而非 `1h前`，CR finding #2）
- [x] **L.2.4** 损坏时间戳 + `max_age_hours > 0` → 拒绝（fail-safe），无 age gate → 仍恢复（backward-compatible fail-open，CR finding #4）
- [x] **L.2.5** 模块级常量 `ANCHOR_RECOVERY_MAX_AGE_HOURS = 24`（CR finding #5）
- [x] **L.2.6** `initialize` 中显式清空 `self._current_task_anchor = ""`（防御性初始化）

### L.3 测试（13 条，`test_memory_os_zombie_anchor_fix.py`）

**Layer 1 — Tombstone**:
- [x] `test_on_session_end_writes_completed_tombstone`: 会话结束后 `active_task_anchor.jsonl` 最新记录 `status=completed`【核心】
- [x] `test_new_session_does_not_recover_completed_anchor`: 会话 B 不恢复会话 A 的已完成锚点【核心】
- [x] `test_on_session_end_tombstones_without_foreground`: 纯 tool 消息会话仍触发 tombstone（CR regression）

**Layer 2 — Age Gate**:
- [x] `test_read_latest_active_task_anchor_rejects_old_anchor`: 48h-old 锚点 + `max_age_hours=24` → 拒绝
- [x] `test_read_latest_active_task_anchor_accepts_recent_anchor`: 1h-old 锚点 + `max_age_hours=24` → 恢复
- [x] `test_read_latest_active_task_anchor_default_no_age_limit`: `max_age_hours=0`（默认）→ 无年龄限制，兼容旧行为
- [x] `test_unparseable_timestamp_rejected_with_age_gate`: 损坏时间戳 + age gate → 拒绝（CR regression）
- [x] `test_unparseable_timestamp_recovered_without_age_gate`: 损坏时间戳 + 无 age gate → fail-open 恢复（CR regression）

**Layer 3 — Cross-session Marker**:
- [x] `test_cross_session_recovery_adds_marker`: 不同会话恢复 → `[跨会话恢复, Xh前, 原会话: {id}]` 标记
- [x] `test_same_session_recovery_no_marker`: 同一会话恢复 → 无标记

**Integration + Edge Cases**:
- [x] `test_end_to_end_zombie_prevention`: 会话 A 完成 → 会话 B 无僵尸锚点【端到端】
- [x] `test_on_session_end_noop_when_no_active_anchor`: 无活跃锚点时 `on_session_end` 不崩溃
- [x] `test_multiple_session_ends_dont_stack_tombstones`: 多次 `on_session_end` 调用不损坏锚点文件

### L.4 代码审查（5 findings，全部修复）

| # | 严重度 | 位置 | 问题 | 修复 |
|---|--------|------|------|------|
| 1 | 🔴 高 | `on_session_end:530` | tombstone 在 foreground guard **之后**，纯系统/工具会话 silent skip | 将 `_clear_active_task_anchor()` 移到 guard 之前 |
| 2 | 🟡 中 | `:1108` | `<1h` 锚点显示为 `1h前` 而非 `Xm前` | 添加分钟分支：`<60min → Xm前` |
| 3 | 🟡 中 | `:1080-1084` | `created_at` 被解析两次 | 单次解析，复用变量 |
| 4 | 🔴 高 | `:1088` | 损坏时间戳 + age gate 活跃 → 放行而非拒绝 | 损坏时间戳 + `max_age_hours>0` → `return ""` |
| 5 | 🟢 低 | 模块级 | `24` 作为裸魔法数字 | 提取为 `ANCHOR_RECOVERY_MAX_AGE_HOURS` |

### L.5 验证

- [x] 新功能测试: 13/13 PASS（`test_memory_os_zombie_anchor_fix.py`）
- [x] 相关测试回归: 80/80 PASS（`test_memory_os_current_task_anchor.py` 42 + `test_memory_os_last_session_anchor.py` 21 + `test_memory_os_prefetch.py` 17）
- [x] 全量回归: **1661 passed, 8 skipped, 0 failed**（140 测试文件，4 目录）
- [x] 静态检查: `write_surface_check` PASS（0 unclassified）+ `import_cycle_check` PASS（0 cycles）
- [x] Commits: `d19d2df`（3-layer defense）+ `8627ec8`（code review hardening），已推送 origin/main

**L 的完成条件**: L.2 全部打勾 ✅ + L.3 测试全部 PASS ✅ + L.4 5 findings 全部修复 ✅ + L.5 全量回归零失败 ✅ + 静态检查 PASS ✅。**L 节完成 (`d19d2df` + `8627ec8`)。**

### L.6 教训

1. **JSONL append-only 的"最新记录胜出"是双刃剑**: 必须显式写 tombstone 改变状态。忘记 tombstone = 僵尸永存。Memory-OS 中其他地方可能有同类问题
2. **`on_session_end` 被 foreground guard 保护导致"静默跳过"是设计 smell**: 清理代码不应该被业务条件保护。CR finding #1 是此模式的直接后果
3. **代码审查的价值**: finding #1（tombstone 错位）和 #4（损坏时间戳放行）如果遗漏，修复是不完整的

---

## 一句话
十三节、可打勾、有终点

