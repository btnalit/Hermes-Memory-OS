# Hermes 上层系统梳理 — 架构 / 调用链 / 接线诊断

> 基线：记忆底座(events / candidates / crystallized / working / index / prefetch)已稳定，本文只梳理**其上的上层系统**。
> 体检三原则：
> **P1** 右脑发言不该被限制/工程化规则化——否则失去内在驱动价值。
> **P2** 中间环节能 LLM 介入就 LLM 分层处理；只有**转成长期记忆晶体、回注记忆底座**的才需人审。
> **P3** 任务执行门禁不阻止，但全程构成审计留证据，反哺左右脑/相关模块形成"来源"。

---

## 0. 一句话核心判断

**上层是一个建得极完整的"感知 + 判决大脑"，却几乎没接运动神经。** cognitive_loop 每 tick 跑 33 步（代码：`cognitive_loop.py:_step_functions`）、算出海量判决(证据评分、置信路由、候选评审、法官校准、级联路由、临时决定、grounded 表达判定、自演化……)，**几乎全部写进 `local_artifact.*` 后断头**。真正的三个动作面由**另一套无视这些判决的路径**喂：

| 动作面 | 该被谁驱动 | 实际被谁驱动 | 病 |
|---|---|---|---|
| 发言 | 右脑表达 → 直接发 | → speak_gate `would-send` + `send` 分支也是 `send_blocked` | **单墙堵死（P1 违背）；mailbox 是内部网关通信组件，非发言通道** |
| 记忆晋升 | LLM 判决栈分层 → 残余给 owner | 启发式 → 一律 `owner_eligible` | **判决栈建好却脱线(P2 违背)** |
| 执行 | report-only + 审计 + 反哺 | ops_gate report-only + feedback_bridge | **基本对(P3 最接近达标)** |

**"全闷死在里面"的真相不是缺件、不是单个门禁高，是：智能算出来了，没接到动作上。** 所以修复**绝大部分是接线，不是新建**。

---

## 1. 上层模块全景(30 个，按四类审批 × 左右脑归位)

### 1.1 右脑(生成/表达)— 内在驱动源
| 模块 | 读 | 写 | 调度 | 状态 |
|---|---|---|---|---|
| `inner_drive` | events / working | crystallized_candidates / working | inner_drive_heartbeat | **live**，产候选 |
| `wandering_mind` | events / household_digest | wandering_output / **module_bus.would_send** | weekly_wandering | live 但 **→ would_send** |
| `deep_reflection` | events / working | injection / digest / analysis | deep_reflection_runtime | live(report-only；carryover 已修) |
| `imagination_loop` | eval.v7_simulated | imagination_loop | …_shadow | shadow |
| `expression_draft` | events / household_digest | expression_draft | 无 | live in loop |
| `grounded_expression_judge` | right_brain_expression / evidence | grounded_expression_judge | …_shadow | live in loop，判完**没人发** |
| `speak_gate` | events / proposal_queue | **speak_gate_would_send** | 无 | **enabled=False，`delivery_mode="would-send"`；注意 `delivery_mode="send"` 分支也返回 `send_blocked`（代码 `evaluate_delivery` L157-163），需要新增真发路径** |

### 1.2 transport(发言出口)
| 模块 | 读 | 写 | 状态 |
|---|---|---|---|
| `speak_gate` | events / proposal_queue | **speak_gate_would_send** | **enabled=False，would-send only** |

> **注意**：`mailbox` 不在此列。`mailbox` 是 Hermes **内部网关间通信**组件，与左右脑表达无关。它的功能是让 Hermes 不同 gateway 之间传递内部消息，属于纯粹的内部通信基础设施。它可以作为会话记忆的一种来源反哺回 Memory-OS，但那只是记忆完整性的补充——mailbox 本身不是发言通道。

### 1.3 左脑(分析/治理)— 判决栈
| 模块 | 读 | 写 | 消费者 | 状态 |
|---|---|---|---|---|
| `evidence/scoring` | events/working/crystallized | audit / evidence_scoring | 多 | **live**，judgment 源头 |
| `confidence_router` | evidence_scoring | confidence_router | candidate_review / shadow_recall / cascade | shadow，live in loop |
| `candidate_review` | confidence_router | candidate_review | judge_calibration / provisional / **owner_actions** | shadow，live in loop |
| `judge_calibration` | candidate_review / ground_truth | judge_calibration | cascade_routing_policy | shadow |
| `cascade_routing_policy` | confidence_router / judge_calibration | cascade_routing_policy | **0 消费者** | **ORPHAN** |
| `provisional` | candidate_review | provisional | **0 消费者** | **ORPHAN** |
| `shadow_recall` | confidence_router / recall_miss | shadow_recall | — | shadow |
| `ground_truth_miner` | audit | ground_truth_miner | judge_calibration / migration | shadow |
| `crystallized_revalidator` | crystallized / events | crystallized_revalidator | — | shadow |
| `migration_controller` | ground_truth / imagination | migration_controller | — | shadow |
| `confabulation_detector` | evidence_scoring | confabulation_detector | — | shadow |
| `pipeline_checker` | proposal_queue / evidence | left_brain_pipeline_check | — | live in loop |
| `proposal_queue` | events / candidates | audit / proposal_queue_state | self_evolution / speak_gate | live |
| `self_evolution` | evidence / proposal_queue | audit / digest / proposal_queue | — | **dry-run/report-only** |
| `ops_gate` | events / module_health | audit / ops_gate_report | feedback_bridge | **report-only**(P3 对) |
| `feedback_bridge` (governance_feedback) | expression_feedback_ledger / memory_sources_feedback | **events.summary** / audit | 回注事件流 | **live + apply(反哺在!)** |

### 1.4 context(记忆塑形)
`household_digest` / `digest_consolidation` / `symbolic_offloader` / `abstraction_distillation` — 给上层喂浓缩上下文，基本 live/shadow 混合，非动作面，本轮不展开。

### 1.5 真实记忆晋升路径(**独立于 loop，关键**)
`candidate_aggregation` lane：`read_candidate_queue` + **启发式 cluster** → `owner_eligible`。
**它不读上面任何判决栈产物**——晋升只靠关键词/cluster 启发式，算出来的 LLM 判决一概无视。

**候选状态机（实际代码 `crystallized.py:CrystallizedCandidate.bridge_state`）**：
当前合法值：`""` | `"inner_drive_candidate"` | `"owner_eligible"` | `"demoted"` | `"fleeting"`
状态流转（`candidate_aggregation.py:_cluster_and_promote`）：聚类关键词匹配 → `owner_eligible`（等 owner approve）；TTL 过期 → `demoted`；无决策内容 → `fleeting`。**没有** LLM 自动批准的中间状态。

### 1.6 ExecutionGate — 方案必须接入的强制许可系统

**这是原方案完全遗漏的架构约束。** Memory-OS 的 `execution_gate.py` 要求**每次自动执行**都需要开 permit 信封（`permit_id`、`lane_id`、`risk_class`、`scope`、`boundary`），完成后记录 postcheck。`StructuralWriteGate` 要求每次自动 JSONL 写入都必须分类通过 permit。

**resolver_approved 的写入必须经过 ExecutionGate**：
- 需要新增 lane_id（如 `"resolver_auto_approve"`）
- 需要定义 risk_class（建议 `"reversible_llm_auto_approval"`）
- boundary 字段必须设 `actual_crystallized_approval=True`（记录"这是自动批准"）
- scope 需要绑定 cascade_routing_policy 的 verdict + provisional 的 promotion 评估作为依据

**speak_gate 真发同样需要**：delivery 到 Hermes 原生层后，Hermes 侧的发出去身就是一次执行——但目前代码中 `speak_gate` 的 `actual_send` 永远是 `False`。



---

## 2. 调用链

### 2.1 live 主环(cognitive_loop，每 tick 顺序跑 30 步)
```
heartbeat → working_decay → household_digest → digest_consolidation
→ wandering_mind → ops_gate → evidence_scoring
→ [判决栈] confidence_router → candidate_review → judge_calibration
          → shadow_recall → provisional → cascade_routing_policy
→ imagination_loop → confabulation_detector → ground_truth_miner
→ crystallized_revalidator → migration_controller → abstraction_distillation
→ grounded_expression_judge → self_evolution
→ structural_edge_proposer → crystallization_gate → llm_edge_proposer
→ left_brain_pipeline_check → host_capability_probe → signal_collection
→ memory_projection → left_brain_advisor → governance_feedback(apply)
```

### 2.2 断头处(智能算完 → 没接到动作)
```
判决栈(confidence/review/judge/cascade/provisional)
    │  全算完，写 local_artifact.*
    ↓
  ╳ 断头：candidate_aggregation 不读它们 ╳
    ↓
真实晋升：启发式 → owner_eligible → 等 owner(1255:2)

右脑表达(wandering/expression/grounded_judge)
    │  生成 + 判定都做了
    ↓
  ╳ 墙：speak_gate(would-send) ╳（注：mailbox 是内部网关通信组件，非发言通道）
    ↓
  would_send.jsonl(谁都发不出去)

执行(ops_gate report-only) → audit → governance_feedback → 回注 events  ✓ 这条通
```

**这张图就是答案**：afferent(感知/判决)极发达，efferent(动作)几乎断。两个动作面(发言、记忆晋升)的智能与动作之间各有一道断头。

---

## 3. 三原则诊断

### P1 — 发言自由：**违背，墙在 speak_gate**
- `speak_gate` enabled=False、"v0.1 records would-send only, real send disabled"。
- 右脑把表达**生成了**(expression_draft)、**判定了**(grounded_expression_judge)，到出口被 `speak_gate` 挡回 `would_send.jsonl`。
- **注意**：`mailbox` **不是发言出口**——它是 Hermes 内部网关间通信组件，与右脑表达无直接关系。之前的"双层墙"诊断是对 mailbox 功能的误解。真实的发言路径是：右脑 → speak_gate → Hermes 原生 delivery（通过动态匹配的 owner 通道发出）。mailbox 的作用仅限于 gateway 间内部消息传递，可以作为会话记忆的一种反哺来源，但不是发言通道。
- **修法**：speak_gate `delivery_mode` 从 would-send 改真发 + enabled=True（对 owner 通道）。Owner 通道由 Hermes gateway 的默认会话通道**动态解析**（如 `channel_directory.json`），不硬编码。Hermes 本身支持通过参数定义匹配默认会话通道——这在之前的设计中已有考虑。发言不设审批闸——审批只在"发言→晶体"那步(见 P2)。

### P2 — LLM 分层 + 只有回注晶体才人审：**违背，但中间层整套已建好，只是脱线**
- 你要的"LLM 审批中间层"= `confidence_router → candidate_review → judge_calibration → cascade_routing_policy → provisional`，**这整套 live 跑在每 tick**，算的正是"这条候选该不该过、该谁审、路由到哪档"。
- 但 `cascade_routing_policy`(路由大脑)和 `provisional`(LLM 临时批准)**消费者 = 0**，纯 orphan；真实晋升 `candidate_aggregation` 启发式 → `owner_eligible`，**完全无视判决栈**。
- 结果：候选状态机只有 `candidate ↔ owner_eligible ↔ demoted ↔ fleeting`——**没有 `llm_approved` / `resolver_approved` 这一档**，所有东西路由给你 → 1255:2。
- **修法(主要接线 + 一档新状态)**：
  1. 给候选状态机加一档 `resolver_approved`(LLM 批准)；
  2. 把 `cascade_routing_policy` 的路由结果**接进** `candidate_aggregation`——它来决定每条候选走 `resolver_approved`(LLM 自动批，可逆)还是 `owner_eligible`(残余给你)；
  3. `provisional` 的 LLM 临时决定接成 `resolver_approved` 的依据；
  4. **安全靠可逆**：LLM 批准的晶体走 demote=invalidate-not-delete(合 INV)+ 全审计 + 你保留终审 demote 权——LLM 判错不是灾难。这正是你"机器守卫优于人工审批"该落到记忆层却还没落的那一档。
- **分界(可委托 LLM vs 留你)建议按可逆性 + 敏感度双轴**：可逆且非身份/非红线 → LLM 自动批；不可逆或身份级/红线 → owner。cascade_routing_policy 已经在算 routing，把这条判据喂进去即可。

### P3 — 执行不拦但审计反哺：**最接近达标**
- `ops_gate` 默认 `execution_mode="report-only"`——不硬拦，记 decision + 写 audit。✓
- `feedback_bridge`(governance_feedback)live + apply，把治理结论(含 ops_gate_report、expression_feedback、memory_sources_feedback)**回注 events.summary**——反哺在。✓
- **唯一缺口**：确认反哺的"来源"真的喂回了**左右脑**(不只是回事件流自审)。即 ops_gate 的执行证据是否进了 inner_drive / wandering 的输入、形成"我做过什么"的自我来源。这一条做实，P3 就闭环。
- **修法(小接线)**：把 ops_gate_report / 执行 audit 作为一类 source 接进右脑(inner_drive/wandering 读)和左脑判决栈的输入，让"执行留下的证据"成为内驱的素材。

---

## 4. 接线问题清单(按收益排)

| # | 问题 | 类型 | 原则 | 收益 |
|---|---|---|---|---|
| W1 | 判决栈 ↔ 真实晋升脱线：cascade_routing_policy/provisional 0 消费者，candidate_aggregation 纯启发式 | 脱线 + 缺一档状态 | P2 | **最高**，直接解 1255:2、放出内驱 |
| W2 | 发言墙：speak_gate `would-send` 挡死右脑表达；`send` 分支也返回 `send_blocked`（代码 `evaluate_delivery` L157-163） | 需新增真发路径 | P1 | 高，右脑表达从"算了白算"变能发 |
| W3 | grounded_expression_judge 判完表达没人发(orphan 出口) | 脱线 | P1 | 高，跟 W2 一起接 |
| W4 | 执行证据未反哺左右脑(只回事件流自审) | 接线不全 | P3 | 中，补成自我来源闭环 |
| W5 | self_evolution dry-run：governor 提议永不自落地 | 门禁高 | P2 | 中，可逆 agenda 项可走 resolver 自落地 |
| W6 | 大量 shadow 模块产 artifact 互相喂、几个终端 orphan | 观察过剩 | — | 低，先别清，W1 接通后重估哪些 shadow 该转 live |
| **W7** | **ExecutionGate 未覆盖 resolver 写入路径**：resolver_approved 晶体写入需要新 lane_id + risk_class + boundary，当前 execution_gate.py 无此分类 | **架构强制要求** | P2 | 阻塞级，不解决 W1 无法上线 |
| **W8** | **resolver_gate 双轴闸字段映射不匹配**：代码中 `CrystallizedCandidate.kind` 无 `"identity"`/`"soul"`/`"redline"` 等值，需要基于实际 inner_drive 产出的 kind 重新设计映射 | 字段假设错误 | P2 | 高，设计级修正 |

---

## 5. 修复次序(垂直切片，先通动作面)

> **代码验证基准**：以下每一步都需要通过 `python -m pytest -q` 全量绿 + `python scripts/memory_os_write_surface_check.py` 绿 + `python scripts/memory_os_public_checkout_probe.py --source working-tree --strict` 绿。

1. **W2+W3 先做(发言放开)**：最独立、最低风险、体感最直接。
   - speak_gate `evaluate_delivery()` 需新增**真发路径**（当前 `delivery_mode="send"` 返回 `send_blocked`，不是真发）
   - 真发通过 Hermes 原生 delivery 接入 owner 通道（动态解析自 `resolve_owner_review_channel()`）
   - grounded_expression_judge 判过的接出口。发言无审批闸。
   - 每次发言 append_audit（作为右脑反哺素材）
2. **W8(双轴闸字段映射)**：基于实际代码的 `CrystallizedCandidate.kind` 和 `sensitivity` 取值，重新设计 `resolver_eligible` 判定。**必须在 W1 接线之前做**。
3. **W7(ExecutionGate 新 lane)**：新增 `resolver_auto_approve` lane + risk_class + boundary。`write_surface_check.py` 验证 unclassified_count=0。
4. **W1(记忆晋升接线)**：加 `resolver_approved` 状态 + cascade_routing_policy 接进 candidate_aggregation + 可逆/审计/owner 终审。这是放出内驱的主闸。
   - **注意**：`candidate_aggregation._cluster_and_promote()` 是批量聚类 → 需要在聚类后插入逐条 routing 决策
   - Provisional sweep 操作的是**晶体化后的记录**（不同于 `_demote_aged` 操作的候选队列），需要新建或在 `crystallized_revalidator` 中扩展
5. **W4(执行反哺)**：ops_gate 证据接进左右脑输入,补 P3 自我来源闭环。
6. **W5(自演化自落地)**：可逆 agenda 走 resolver 自落地，owner 只留不可逆。
7. **W6 重估**：上面通了之后，再看哪些 shadow 模块该转 live、哪些 orphan 该删。

**核心心法**：这套系统的智能**已经建好并在跑**，缺的是把它接到三个动作面。别再加感知/判决模块，把现有的接通——发言放开、判决栈接上晋升、执行证据反哺。**afferent 够了,补 efferent。**

---

## 6. 要你拍板的决策点

1. **P2 分界**：可委托 LLM 自动批的候选，按"可逆性 + 敏感度双轴"划(可逆且非身份/红线 → LLM)，还是你想换判据?
2. **发言放开的范围**：先只对 owner 放开(低风险)，还是 owner + 世界级一起放?(建议先 owner)
3. **resolver_approved 的可逆窗口**：LLM 批准的晶体保留多久"可无条件 demote"窗口给你复核?
4. 验收我按老规矩:接线改完，反证"判决栈结果真的改变了晋升路由"、"发言真的发得出去"、"执行证据真的进了右脑输入"——从干净克隆全量验。

确认 1–3 后，我可以把 W1/W2 落成和前两份同规格的可执行规约给 codex。
