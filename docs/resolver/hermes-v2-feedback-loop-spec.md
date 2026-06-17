# V2 可执行规约(修订版) — 闭合反馈环(自身活动反哺 + 防自反螺旋)

> 修订说明:前版有三处事实错误(引用了不存在的 `provenance.py` / `is_tainted` / `event.provenance` 字段——那是没落地的 choke-point 规约里"要创建"的东西)。本版改用代码里**真实存在的 `safe_ref["source_class"]` 机制**,并据实修正 mailbox / decay 的"复用"误判。

## 0. 锁定决策(owner 已拍,不变)
1. 防螺旋 = `self_activity` **完全排除出表达触发**。
2. 四条流:发言 / resolver 决策 / ops_gate / mailbox。
3. mailbox 只反哺信箱真实对话。

## 0.1 现状(已据代码核实,修正前版)
- ✅ `feedback_bridge` 已反哺 ops_gate + 发言 → `events.summary`,经 `_to_event` 写入,**source_class 现硬编码为 `"governance"`**(feedback_bridge.py:505)。
- ✅ `EventEnvelope`(schema.py)**无 provenance 字段**;`source_class` 存在 **`safe_ref` dict** 里。
- ✅ `_right_brain_eligible_events`(wandering_mind ~305-315)**已读 `safe_ref.get("source_class")`**,且**已排除 `source in {memory_os, governance_feedback, self_evolution, cognitive_loop}`**——**所谓"潜在螺旋"已被 source-name 排除挡住,前版夸大了**。
- ❌ `provenance.py` / `is_tainted` / `TAINTED_SOURCE_CLASSES` **不存在**(choke-point 没落地)→ 前版 §3/V2.4 作废。
- ❌ mailbox 是裸脚手架(`enabled:False`,仅 inbox/outbox 目录,**零对话摄取**)→ V2c 阻塞。
- ❌ 事件级 decay/cap 不存在(`_working_decay` 是 WorkingItem 级)→ V2d 是新建非复用。
- ❌ resolver audit → feedback_bridge 的管道不存在 → V2b 是新接线。

**修正后 V2 = 给反哺流打 self_activity 标(safe_ref)+ 一行排除 + 接 resolver 流 + 新建事件级有界;mailbox 暂缓。**

---

## 1. 防螺旋闸(脊柱,V2a)— 比前版简单,大半已在

### 1.1 用真实机制:safe_ref["source_class"] = "self_activity"
**不创建 provenance.py。** self_activity 标存进 `safe_ref`(既有机制,_to_event 已在写、eligibility 已在读)。

### 1.2 排除点(一行,加在既有过滤器)
`_right_brain_eligible_events` 已读 `source_class`,只需加一行排除:
```python
# wandering_mind._right_brain_eligible_events (~310, source_class 已解析)
if source_class == "self_activity":
    continue          # ← 新增:自身活动不作表达触发
```
- 现有按 source-name 排 `governance_feedback` 仍留;新增按 **source_class 排 self_activity**——**更鲁棒**(不管源名叫什么,凡标了自身活动都挡)。这是前版"按 source_class 比按 source-name 健壮"的正确落点。
- **注:双重过滤无害。** self_activity 事件从 feedback_bridge 写入时,`source == "governance_feedback"`,会被第 311 行既有的 `source` 过滤**也**拦住。加上 `source_class` 排除后变成双保险——一条绊不住另一条也拦。**不算 bug,两个过滤都留着。**

### 1.3 可见不可触发(不变)
inner_drive / deep_reflection 仍 `read_events()` 读得到 self_activity 事件(学习素材);只有 wandering 表达触发的 eligibility 排除它。

---

## 2. 给反哺流打 self_activity 标(V2a + V2b)

### 2.1 _to_event 参数化 source_class(接口小改)
现 `_to_event`(feedback_bridge.py:505)硬编码 `"source_class": "governance"`。改成接受参数:
```python
def _to_event(record, *, source_class="governance", subtype=None):
    safe_ref = {"source_class": source_class, ...}
    if subtype: safe_ref["self_activity_subtype"] = subtype
```
- **调用点仅一处** (`_collect_events:249`),改动安全。
- **但影响 7 个 collector**:每个 collector 的 record dict 里需带 `source_class`/`subtype` 字段,由 `_to_event` 读取。发言/ops_gate 两条流是**类别变更** (`"governance"`→`"self_activity"`),需同步更新测试断言中的 `source_class` 期望值。

### 2.2 四条流的标(发言/ops 补标,resolver 新接)
| 流 | 源 | 状态 | source_class | subtype |
|---|---|---|---|---|
| 发言 | deliveries.jsonl | 已反哺,**改标** | self_activity | speech |
| ops_gate | ops_gate_report | 已反哺,**改标** | self_activity | execution |
| resolver | W1 audit(approved/confirmed/rejected/ttl_expired/cap_evicted) | **新接管道** | self_activity | resolver |
| mailbox | 信箱真实对话 | **暂缓**(§4) | self_activity | mailbox |

### 2.3 resolver 流新接线(V2b 主体)
resolver 决策现写在 audit(provisional_sweep / crystallized.invalidate/confirm / owner_actions),**但 feedback_bridge._collect_events 不读它**。新增一个 collector:从 resolver audit 取 approved/confirmed/rejected/ttl_expired/cap_evicted → `_to_event(source_class="self_activity", subtype="resolver")`。这是内驱最该吃的料:"我自动批的,哪些 owner 确认/拒/过期"。

### 2.4 inner_drive 分类 ripple(必处理)
改 source_class "governance"→"self_activity" 后,inner_drive 的 `_source_class()` 可能把它判 "other"。**确保 (a) inner_drive 仍读得到(read_events 返回全部,不受影响),(b) `_source_class()` 认得 self_activity(加一个映射,别让它落 "other" 影响决策逻辑)。** 这是 V2.2"可见"的落地保证。

**精确插入点** (`inner_drive.py:_source_class`,~193 行,`source_class` 变量已解析):
```python
source_class = str(safe_ref.get("source_class", "")).lower()
# ↓ 新增:在 source_module 检查之前,self_activity 优先级最高
if source_class == "self_activity":
    return "self_activity"
```
- 放在 **source_module 检查之前**(第 195 行之前),避免被 `source_module == "ops_gate"` 之类误匹配成 `"governance"`。
- 返回 `"self_activity"` 后,`select_events_for_inner_drive` 自动获得 self_activity 维度的 per-source-class cap(默认 50 条),**也是 V2d 有界的天然落点**——不用另建计数机制。

---

## 3. ~~provenance / choke-point 区分~~(作废)
前版 §3 基于不存在的 `is_tainted`/choke-point,**整节删除**。self_activity 仅触发本规约的 eligibility 排除,无 choke-point 可串。
> 前瞻:若将来 choke-point(RAGFlow 那份)真落地,届时需保证 is_tainted 不把 self_activity 误判——但**那是 choke-point 落地时的事,不在 V2 范围**。

---

## 4. mailbox 对话筛(V2c)— 暂缓,记依赖
**mailbox 当前是裸脚手架**(enabled:False,无消息摄取/无 message.kind/无对话流)。**没有对话可筛 → V2c 现在无法实现。**
- **依赖**:V2c 的前置是 mailbox 真的摄取信箱真实对话(message ingestion + kind 枚举)。这是一块独立的 mailbox 建设,不在 V2 反馈环范围。
- **处置**:V2c 从本批移出,标为 **blocked-on-mailbox-ingestion**。等 mailbox 能摄取真实对话了,再用确定性 kind 白名单筛(只 owner↔agent 真对话,排心跳/ping/ack)→ self_activity:mailbox。
- 不影响其余三条流;V2 先把发言/ops/resolver 三条闭上。

---

## 5. 事件级有界(V2d)— 新建,非复用
**不存在事件级 decay/cap**(`_working_decay` 是 WorkingItem 级,aging 是 owner-review 级)。V2d 是**新建**:
- events.summary 中 self_activity 事件 **cap**(条数/占比上限,超了旧先汰),防淹外部 event。
- **实现选型:读侧 cap,非写侧。** JSONL 追加模型下,写侧计数需全量读取→代价等同读侧,且写侧过滤会丢数据(不可逆)。读侧在 `select_events_for_inner_drive` 已有 per-source-class cap 先例——V2.4 让 `_source_class()` 返回 `"self_activity"` 后,自动纳入该 cap 体系。如需更精细的"自身活动占比上限",可在该函数内加 self_activity 专项百分比闸。
- **不另建计数机制**,复用 `select_events_for_inner_drive` 的 `source_counts` 字典(inner_drive.py:159)。

---

## 6. 复用 vs 新建(据实)
| 件 | 真复用 | 新建 |
|---|---|---|
| 反哺骨架/sink | feedback_bridge / events.summary | — |
| source_class 机制 | **safe_ref**(非 provenance.py) | — |
| 排除点 | `_right_brain_eligible_events`(已读 source_class) | +1 行 self_activity 排除 |
| 打标 | _to_event | 参数化 source_class+subtype |
| 发言/ops 流 | 已反哺 | 改标 |
| resolver 流 | audit 已有数据 | **新 collector 接 feedback_bridge** |
| inner_drive 分类 | _source_class() | 加 self_activity 映射 |
| 事件级有界 | ~~working_decay~~(不适用) | **新建读侧 cap(复用 select_events_for_inner_drive)** |
| mailbox | — | **暂缓(无摄取)** |

---

## 7. 分期(修订)
| Phase | 内容 | 状态 |
|---|---|---|
| **V2a** | safe_ref self_activity 标 + _to_event 参数化 + `_right_brain_eligible_events` 一行排除 + 发言/ops 改标 + inner_drive `_source_class` 映射 | 可做 |
| **V2b** | resolver audit → feedback_bridge 新 collector(self_activity:resolver) | 可做 |
| **V2d** | 事件级 self_activity cap/汰(新建) | 可做 |
| ~~V2c~~ | mailbox 对话筛 | **暂缓:blocked-on-mailbox-ingestion** |

V2a 先(闸 + 既有流改标),V2b 接 resolver,V2d 有界。V2c 等 mailbox 建设。

---

## 8. 测试断言(RED-first,修正字段路径)
```
防螺旋(核心):
V2.1  safe_ref.source_class="self_activity" 的事件 → _right_brain_eligible_events 排除 → wandering 不触发
      (RED: 加排除行前, self_activity 事件能进 eligible)
V2.2  inner_drive read_events() 仍返回该事件 + _source_class() 认得 self_activity(非 "other")
V2.3  端到端: 发一条言 → 反哺(self_activity) → 下一 tick 不因它触发新表达

打标:
V2.4  _to_event(source_class="self_activity", subtype="resolver") → safe_ref 正确带标+subtype
V2.5  发言/ops 流改标后 source_class 从 "governance" → "self_activity"
V2.6  resolver collector: approved/rejected/ttl_expired/cap_evicted 各产一条 self_activity:resolver 事件

有界:
V2.7  self_activity 超 cap → select_events_for_inner_drive 按 source_class cap 汰旧(读侧,复用既有 per-source-class 上限); 外部 event 不被淹

(删除前版 V2.4 is_tainted 断言——infra 不存在)
```

---

## 9. 验收(Claude 复验)
- **反证 V2.3**:发言 → 反哺 → 下一 tick 不因自身发言触发新表达。
- **可见不可触发两面**:inner_drive 读得到(V2.2)、wandering 触发不了(V2.1)。
- **字段路径对**:全走 `safe_ref["source_class"]`,无 `event.provenance`、无 provenance.py。
- **resolver 流真接通**:audit → feedback_bridge → events.summary 带 self_activity:resolver。
- **inner_drive 不被改标打懵**:_source_class 认得新类。
- **V2c 正确暂缓**,不假装实现一个没有摄取源的 mailbox 筛。

## 10. 一句话
修订后 V2 更小更实:**用真实的 safe_ref 机制打 self_activity 标 + 一行排除(防螺旋,大半已在)+ 接 resolver 流 + 新建事件级有界**。mailbox 暂缓(无摄取源)。脊柱不变:内驱看得见自己做了什么、学得到,但嘴不对着自己打转。
