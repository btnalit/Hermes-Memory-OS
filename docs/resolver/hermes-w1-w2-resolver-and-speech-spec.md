# W1 + W2 可执行规约 — Resolver 自主审批层 + 发言对 owner 放开

> **目标**：把上层"感知+判决大脑"接到两个动作面——**记忆晋升**(W1)和**发言**(W2)。
> **纪律**：复用现有机件、可逆优先、append-only audit、RED-first 测试、垂直切片、INV 不破、**ExecutionGate 全路径覆盖**。
> **代码基准**：所有字段/状态/路径以 `plugins/memory/memory_os/` 和 `plugins/modules/` 实际代码为准。

## 0. 锁定的决策(owner 已拍)

1. **可委托 LLM 自动批的分界 = 可逆性 + 敏感度双轴**：可逆 **且** 非身份/非红线 → LLM 自动批；否则 → owner。
2. **发言先只对 owner 放开**(低风险)；世界级/外发仍关。
3. **resolver 批准的晶体**：7 天 TTL 兜时间 + 并发条数 cap = **30** 兜容量(超 30 旧先清)；窗口内 owner 确认转永久，否则 invalidate-not-delete。

### 0.1 核心架构合成点(写死，不许偏离)
**deterministic 安全闸 + LLM 在闸内判。** LLM 的自主权被一道**确定性闸**框死：只有"可逆且非身份/非红线"的候选**才进入** LLM 可自动批的范围；LLM 在这个机器划定的安全信封内决定"现在批 / 仍交 owner"。这同时满足你两条价值：「能 LLM 介入就 LLM」+「机器守卫优于人工审批」。安全的根是**可逆**——resolver 做的一切都是 invalidate-not-delete + 全审计 + owner 终审，LLM 判错代价 ≤ 7 天可逆窗口。

### 0.2 INV 保持
- **INV-5(无 LLM 热路径)**：resolver 判决发生在**离线 cognitive_loop / aggregation lane**(no_agent)，**不在 prefetch 热路径**。注入端只读 provisional 晶体，不触发判决。
- **INV-1 / 可逆**：resolver 晶体是 report-class-reversible——过期/拒绝 = invalidate(标记失活)，canonical 记录不删。
- **INV-6**：approve / confirm / reject / expire / evict 每步落 audit。
- **INV-7(ExecutionGate)**：resolver 的每条自动写入必须通过 ExecutionGate permit（新 lane_id: `"resolver_auto_approve"`），`write_surface_check.py` 验证 unclassified_count=0。
- **INV-8(StructuralWriteGate)**：resolver_approved 写入走 `write_approved_record()` → `append_governed_jsonl()`，不裸写 crystallized。

### 0.3 非目标
- 不动记忆底座的 events/working/index 结构。
- 不开世界级发言(只 owner)。
- 不改 ops_gate(P3 已基本达标，W4 另做)。

---

## 1. W1 — Resolver 自主审批层

### 1.1 状态模型(扩候选状态机)
现有（代码 `crystallized.py:CrystallizedCandidate.bridge_state`）：`""` | `"inner_drive_candidate"` | `"owner_eligible"` | `"demoted"` | `"fleeting"`。
状态判定（代码 `crystallized.py:resolve_candidate_effective_state`）：最新 triage 记录覆盖原始 bridge_state。
**新增 `"resolver_approved"` 状态 + 晶体子态 `provisional=True`：**

```
candidate ──┬─[resolver_eligible 且 LLM 批]→ resolver_approved(provisional 晶体, 即刻生效/注入)
            │                                     │
            │                          ┌──────────┼───────────┬─────────────┐
            │                   [owner 确认]  [owner 拒绝]  [7d TTL 到期]  [cap>30 旧先清]
            │                          ↓          ↓            ↓             ↓
            │                       永久晶体    invalidate   invalidate    invalidate
            │                     (provisional=False)         (not delete, 审计)
            └─[非 resolver_eligible]→ owner_eligible(不变, 等 owner)
```

**关键：resolver_approved 晶体一经批准即刻生效、即刻进 prefetch 注入**——这才是"放出内驱"。7 天 TTL 是**反向安全网**，不是前置条件。owner 审从"前置"变"窗口内复核"。

### 1.2 deterministic 双轴闸(resolver_eligible)

**字段审计结果（2026-06-17，代码基准）**：

| 字段 | inner_drive 实际产出 | 说明 |
|---|---|---|
| `kind` | **始终 `"moment"`** | 单一硬编码值，不传达任何路由信息 |
| `sensitivity` | **始终 `"private"`** | 默认值，从未被覆盖；`"normal"`/`"low"` 不存在于任何生产写路径 |
| `tags` | `["inner-drive", event.kind, source_class]` | event.kind ∈ `{"conversation_turn", "memory_write"}`，source_class 始终 `"foreground"` |
| `body` | `"Remembered from event {id}: {summary}"` | 自由文本，无结构化 kind 字段 |
| `bridge_state` | `"inner_drive_candidate"` | 始终如此 |

**关键结论**：`kind` 字段不携带路由信息 → 不能用于身份/敏感度判定。双轴闸必须基于 `body` + `tags` 文本扫描 + `sensitivity`。

```python
# plugins/memory/memory_os/resolver_gate.py  (新文件, 纯确定性, 无 LLM)

# ── 身份信号检测（body + tags 文本扫描）────────────────────
IDENTITY_SIGNALS = frozenset({
    "identity", "persona", "personality", "soul", "who i am",
    "self-definition", "self definition", "i am", "我的身份",
    "我是谁", "人格", "自我定义", "红线", "约束", "边界",
    "redline", "constraint", "boundary", "永不", "永远不",
})

def _has_identity_signal(body: str, tags: list[str]) -> bool:
    """检查 body 和 tags 中是否包含身份/红线相关信号。
    
    不使用 candidate.kind：kind 始终为 "moment"（inner_drive 硬编码），
    不传达路由信息。
    """
    body_lower = (body or "").lower()
    tags_lower = [str(t).lower() for t in (tags or [])]
    combined = body_lower + " " + " ".join(tags_lower)
    return any(sig.lower() in combined for sig in IDENTITY_SIGNALS)

# 敏感度：现有字段 + 前向兼容
NON_SENSITIVE = frozenset({"normal", "low", "private"})
# "private" 是当前生产的唯一值；"normal"/"low" 为未来敏感度分层预留

def is_reversible(candidate: CrystallizedCandidate, *, store: MemoryOSStore) -> bool:
    """可逆 = 纯记忆记录，无副作用下游。"""
    return (candidate.sensitivity in NON_SENSITIVE
            and not _has_identity_signal(candidate.body, candidate.tags or [])
            and not _triggers_side_effect(candidate, store))

def resolver_eligible(candidate: CrystallizedCandidate, *, store: MemoryOSStore) -> bool:
    """候选可通过 resolver 自动审批。"""
    return (is_reversible(candidate, store=store)
            and candidate.sensitivity in NON_SENSITIVE
            and candidate.bridge_state in ("", "inner_drive_candidate"))
```

**关键改动**：
- 去除 `_kind_is_identity_adjacent()`（`kind` 不携带路由信息）
- 新增 `_has_identity_signal()` 纯基于 `body` + `tags` 文本扫描
- `resolver_eligible` 增加 `bridge_state` 过滤（只有未处理或 inner_drive 产出的候选才走 resolver）
- 增加字段审计结果块（代码基准，可验证）

### 1.3 接线：判决栈 → 真实晋升(解 orphan)

现状（代码 `candidate_aggregation.py:_cluster_and_promote` L197-292）：
1. 关键词聚类 → `cluster_key`
2. `cluster_size >= min_cluster_size(2)` → promote to `owner_eligible`
3. Index-based dedup check
**纯启发式，零 LLM 判决输入。**

`cascade_routing_policy` 和 `provisional` 消费者=0(orphan)。

**修改 `_cluster_and_promote`**：在聚类 promote 之后、写入 triage 之前，插入逐条 resolver routing：

```python
# 在现有 _cluster_and_promote 的 promote loop 内 (L258-285)，
# append_candidate_triage 之前插入 resolver routing：

for member in promote_batch:
    # 现有去重检查 (L260-273)
    dedup_hit = _check_index_dedup(store, member)
    if dedup_hit is not None:
        # ... 现有 demote 逻辑不变
        continue

    # ── 新增：resolver routing 决策 ──
    if resolver_eligible(member, store=store):
        # 读取判决栈产物
        confidence_route = _lookup_confidence_route(member, confidence_router)
        provisional_promotion = _lookup_provisional(member, provisional_module)
        # cascade_routing_policy 的 policy 给路由阈值
        routing_policy = _latest_cascade_policy(cascade_module)
        # LLM 在安全信封内判
        verdict = _resolver_verdict(
            member,
            confidence=confidence_route,
            provisional=provisional_promotion,
            routing_policy=routing_policy,
        )
        target_state = "resolver_approved" if verdict.approve else "owner_eligible"
    else:
        target_state = "owner_eligible"

    append_candidate_triage(
        store,
        candidate_id=member.candidate_id,
        action="promote",
        target_state=target_state,  # ← 动态决定
        reason=reason,
        cluster_key=cluster_key,
        execution_gate_envelope_id=envelope_id,
        now=_now,
    )
```

**关键实现点**：
- 聚类逻辑**不动**（聚类决定"是否 promote"，resolver 决定"promote 到哪个状态"）
- `_lookup_confidence_route()` / `_lookup_provisional()` / `_latest_cascade_policy()` 从 local_artifact 文件读取（shadow 模块已写入）
- `_resolver_verdict()` 整合三者做 LLM 判定（离线，no_agent）
- `cascade_routing_policy` 从 orphan 变成 routing 依据；`provisional` 的 promotion 评估成为 verdict input

### 1.4 写入 = ExecutionGate 治理写入(不裸写)

**执行前开 permit 信封**（必须，`execution_gate.py` 强制要求）：
```python
gate = start_execution_gate_envelope(
    store,
    lane_id="resolver_auto_approve",          # 新 lane
    trigger_surface="candidate_aggregation",
    risk_class="reversible_llm_auto_approval", # 新 risk_class
    human_approval_required=False,
    why_no_human_approval="resolver_eligible 双轴闸已过滤不可逆/敏感候选；7d TTL + cap30 可逆安全网；owner 终审保留",
    scope={
        "candidate_id": member.candidate_id,
        "target_state": "resolver_approved",
        "resolver_verdict": verdict,
        "provisional": True,
        "expires_at": (now + timedelta(days=7)).isoformat(),
    },
    boundary={
        "actual_crystallized_approval": True,  # 标记这是自动晶体化
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
    },
    evidence_refs=[
        f"confidence_route:{confidence_route.get('route_id', '')}",
        f"provisional:{provisional_promotion.get('promotion_id', '')}",
        f"cascade_policy:{routing_policy.get('policy_id', '')}",
    ],
)
```

resolver 批准 → `write_approved_record(candidate, decision)`，
`decision = ApprovalDecision(purpose=APPROVE_FOR_CRYSTALLIZED, reviewer="resolver", provisional=True, expires_at=now+7d, recurrence=<n>)`。
`ApprovalDecision` 增字段：`provisional: bool=False`、`expires_at: str|None=None`、`recurrence: int=0`。
晶体记录带 `provisional=True` + `resolver_approved` provenance + `execution_gate_envelope_id`。

### 1.5 TTL + cap + 驱逐 + 复发(生命周期机件)

**关键数据层区分**：
- `_demote_aged`（代码 L298-333）操作的是**候选队列**（`CrystallizedCandidate`，未晶体化），TTL 作用于 `bridge_state` 的 age
- Provisional sweep 操作的是**已晶体化记录**（已写入 crystallized .md 文件），TTL 作用于 `expires_at` 字段
- **这两个是不同的数据层**，不能复用同一个函数。Provisional sweep 需在 `crystallized_revalidator` 中新建或作为独立 lane

**新建 `provisional_sweep` lane**(no_agent，参考 `_demote_aged` 的 ExecutionGate 写法)：

```
每 tick / 每 lane:
  provisional = list_provisional_crystals()        # provisional=True 的晶体
  # ① TTL 到期
  for c in provisional:
      if now >= c.expires_at and not c.owner_confirmed:
          invalidate(c, reason="resolver_ttl_expired"); append_audit(...)
  # ② cap 驱逐(旧先清)
  live = [c for c in provisional if c.active]
  if len(live) > 30:
      for c in sorted(live, key=lambda x: x.approved_at)[: len(live)-30]:
          invalidate(c, reason="resolver_cap_evicted"); append_audit(...)
  # ③ 复发逃生阀
  for c in newly_resolver_approved:
      n = recurrence_count(c.content_hash)          # 跨周期被 LLM 反复批几次
      if n >= 3:
          escalate_to_owner_digest(c, priority="high", note="high_recurrence_confirm")
          # 可选: extend expires_at, 防好晶体空转
```
- **invalidate = not delete**(标失活，canonical 留存，可复核)。
- **复发 ≥3 → digest 高优先**：真有价值、你只是没空确认的，别让它 7 天一清永远 churn。

### 1.6 owner 确认/拒绝(复用 #3 digest + scoped action)
- provisional 晶体进 **owner-review digest**，每条带 **剩余天数倒计时** + confirm / reject。复用 #3 的 cluster owner-action(scope_hash TOCTOU 绑定、混敏 fail-closed)。
- **没有这个露出面，7 天过期 = 静默失忆**——这一步是 P2 成立的必要条件，不是可选。
- owner confirm → `provisional=False`、清 `expires_at` → 永久。
- owner reject → 立即 invalidate + audit。

### 1.7 注入端(让内驱学到的即刻可用，但标 provisional)
- provisional 晶体经 prefetch **注入**(这是"即刻生效"的落点)，但：
  - 单列/标注 `(provisional · resolver-approved · 剩 Xd)`，让读它的 agent 知道这是 LLM-批-未-owner-确认；
  - 携带 `resolver_approved` provenance；
  - 权重 ≤ owner-confirmed 晶体(排序在后，预算紧时先让位——复用 W1 之前的 budget 优先级)。

---

## 2. W2 — 发言对 owner 放开

### 2.1 改 speak_gate — 从 would-send 到真发(需新增代码路径)

**现状（代码 `speak_gate.py:evaluate_delivery` L149-179）**：
```python
if self.delivery_mode == "no-send":     # → decision="no_send"
if self.delivery_mode == "send":        # → decision="send_blocked"  ← 注意：不是真发！
# default (would-send):                # → decision="would_send", actual_send=False
```
**关键**：`delivery_mode="send"` 分支返回的是 `send_blocked`（reason: `"real_send_disabled_in_v0_1"`）。**不存在真发路径**。需要新增 `evaluate_delivery` 的 `"owner_send"` 分支或单独的 delivery 方法。

**修改方案**：

1. **新增 `delivery_mode="owner-send"`** + 真发路径：
```python
def evaluate_delivery(self, *, payload_ref, source_module, channel, reason=""):
    if self.delivery_mode == "no-send":
        return self._delivery_result(decision="no_send", ..., actual_send=False)
    if self.delivery_mode == "owner-send":
        # 确定性目标闸：校验 channel ∈ owner 通道
        owner_channel = self._resolve_owner_channel()
        if channel != owner_channel:
            return self._delivery_result(
                decision="send_blocked",
                reason=f"channel {channel} != owner_channel {owner_channel}",
                actual_send=False,
            )
        # 真发：委托 Hermes 原生 delivery
        return self._deliver_to_owner(
            payload_ref=payload_ref,
            source_module=source_module,
            channel=channel,
            reason=reason,
        )  # actual_send=True
    if self.delivery_mode == "send":
        return self._delivery_result(
            decision="send_blocked",
            reason="real_send_disabled_in_v0_1",
            actual_send=False,
        )
    # default: would-send
    ...
```

2. **`_resolve_owner_channel()`**：委托 Memory-OS 已有机制 `resolve_owner_review_channel(store)` 动态解析（代码 `owner_actions.py:1520`），不硬编码。

3. **`_deliver_to_owner()`**：通过 Hermes 原生 delivery adapter（`deliver=origin` 或对应的 channel adapter）发出。具体实现依赖 Hermes 侧已稳定的 delivery 接口。

4. **关于 `mailbox`**：`mailbox` 是 Hermes 内部网关间通信组件，**不是发言 transport**。它与左右脑表达无关——其功能仅限于 gateway 间内部消息传递。mailbox 的内容可以作为一种会话记忆来源反哺回 Memory-OS，使 Hermes 的记忆更齐全，但它不在发言路径上。

### 2.2 发言不设审批闸，但留审计反哺(P1 + P3)
- 右脑链 `wandering_mind / expression_draft / grounded_expression_judge` 的产出 → speak_gate → Hermes 原生 delivery → **owner 通道**(动态解析)。**无审批闸**(P1：发言自由)。
- 但每次发言 append_audit(说了什么、何时、哪个右脑模块发起)。这条 audit 作为一类 source 反哺右脑输入(P3：执行/发言证据成为自我来源)。
- **确定性目标闸**：deterministic 校验投递目标 ∈ owner 通道（动态匹配默认会话通道）；非 owner(世界级)→ 仍走 would-send，不发。

### 2.3 发言 → 长期记忆才走 W1(分层的关键)
发言自由，但若某次发言/互动**要沉成长期记忆晶体回注底座**——那一步走 §1 的 resolver 层(可逆+非敏感 → LLM 批 provisional；否则 owner)。**这就是你"发言不审、发言→记忆才审"的落点。**

---

## 3. 复用 vs 新建

| 件 | 复用 | 新建 |
|---|---|---|
| 状态机 | `""/"inner_drive_candidate"/"owner_eligible"/"demoted"/"fleeting"`（代码 `bridge_state`） | +`"resolver_approved"` 一档 |
| 双轴闸 | `sensitivity` + `body` + `tags` 现有字段（`kind` 始终 `"moment"`，不用于路由） | `resolver_gate.py`(纯确定性) |
| 路由 | `cascade_routing_policy` + `provisional`（现 orphan→接上） | `_resolver_verdict()` 接线 + looked-up functions |
| 写入 | `write_approved_record` + `ApprovalDecision`(+3 字段) | ExecutionGate 新 lane `"resolver_auto_approve"` |
| TTL/驱逐 | `_demote_aged` 写法参考（非复用，不同数据层） | `provisional_sweep` lane（操作已晶体化记录） |
| 可逆 | demote=invalidate-not-delete | — |
| digest | #3 cluster owner-action(scope_hash) | +倒计时字段 |
| provenance | choke-point provenance 机制 | `resolver_approved` 标记 |
| 注入 | prefetch section + budget 优先级 | provisional 标注 |
| 发言 | speak_gate 现有结构 | `delivery_mode="owner-send"` 新分支 + `_deliver_to_owner()` + owner 通道动态解析 |
| 审计 | `append_audit` | — |
| 守卫 | static_hygiene / write_surface_check / public_checkout_probe | +resolver 不变量断言 + write_surface unclassified=0 |

**规模重估**：不是"几乎全是接线"。核心接线（路由 binding）、新状态机、ExecutionGate 新 lane、provisional sweep 新 lane、speak_gate 新 delivery 分支——这些都需要新建。但每个件都是小范围、确定性优先。

---

## 4. 交付分期(垂直切片)

| Phase | 内容 | 归属 | 为什么这个顺序 |
|---|---|---|---|
| **P0(发言)** | W2：speak_gate 新增 `delivery_mode="owner-send"` + `_deliver_to_owner()` + `_resolve_owner_channel()` 动态解析 + 发言 audit | 最独立 | 低风险、体感最直接、不依赖 W1 |
| **P1(字段审计)** | Audit inner_drive 实际产出的 `kind` + `sensitivity` 值域，确定 `resolver_gate` 字段映射 | 前置依赖 | P2 依赖实际字段取值 |
| **P2(双轴闸)** | `resolver_gate.py` + `resolver_eligible` + ExecutionGate 新 lane `"resolver_auto_approve"` + 测试 | 纯确定性 | 闸过了才接写入 |
| **P3(resolver 写入+生命周期)** | `resolver_approved` 状态 + `write_approved_record(provisional)` + `provisional_sweep` lane(TTL/cap/驱逐) + ExecutionGate 集成 | 核心 | 闸+ExecutionGate 就绪后接写入 |
| **P4(路由接线)** | cascade_routing_policy + provisional → candidate_aggregation 路由 + un-orphan | 接线 | 闸+写入就绪后接判决栈 |
| **P5(digest+注入)** | #3 digest 加倒计时+confirm/reject + prefetch provisional 标注 + 复发逃生阀 | 露出面 | 必须有，否则静默失忆 |

**P0 完全独立，先发。** P1 是字段审计（前置依赖，1 小时工作量）。P2–P3 确定性优先，每步可独立测试。P4 接判决栈。P5 是 owner 复核闭环，P3 上线**必须同批**带 P5(否则 provisional 晶体没人能确认)。

---

## 5. 测试断言(RED-first，机器闸)

每条**必须在改前代码上 FAIL**(证明真接通/真咬)。

```
W2:
S0.1  speak_gate delivery_mode=owner-send + 目标=owner → 实发(非 would_send)
S0.2  目标=世界级 → 仍 would-send 不发(决策2: 只 owner)
S0.3  发言后 audit 存在(谁发/何时/哪模块)

W1 双轴闸:
R1.1  可逆 + sensitivity=private（生产唯一值） + bridge_state=inner_drive_candidate → resolver_eligible True
      注：sensitivity 实际只有 "private"，"normal"/"low" 为前向兼容占位
R1.2  body/tags 含身份信号关键词（IDENTITY_SIGNALS） → resolver_eligible False(→owner)
      注：不使用 candidate.kind（始终为 "moment"），纯 body+tags 文本扫描
R1.3  sensitivity 不在 NON_SENSITIVE → resolver_eligible False
      注：当前所有候选 sensitivity="private"∈NON_SENSITIVE，此闸对未来扩展生效
R1.4  _triggers_side_effect → resolver_eligible False

W1 写入+生命周期:
R2.1  resolver 批 → ExecutionGate permit(lane_id=resolver_auto_approve) → 晶体 provisional=True, expires_at=+7d, 即刻可注入
R2.2  owner confirm → provisional=False, 清 expires_at, 永久
R2.3  owner reject → invalidate, canonical 留存(not delete), audit
R2.4  TTL 到期未确认 → provisional sweep invalidate(reason=resolver_ttl_expired), audit
R2.5  并发=31 → 最旧 1 条被 evict(reason=resolver_cap_evicted), 留 30
R2.6  同内容跨周期被批3次 → digest 高优先 escalate

W1 路由接线(解 orphan):
R3.1  cascade_routing_policy + provisional 的 verdict 真的改变了晋升路由
      (RED: 现 candidate_aggregation 无视判决栈, 全 owner_eligible)
R3.2  非 resolver_eligible 候选 → 仍 owner_eligible(不误放)

注入:
R4.1  provisional 晶体注入时带 (provisional·剩Xd) 标注 + resolver_approved provenance
R4.2  预算紧时 provisional 排在 owner-confirmed 之后(先让位)

守卫:
G.1   resolver 写入必经 write_approved_record + ExecutionGate(write_surface_check unclassified_count=0)
G.2   resolver_eligible 是双轴闸唯一入口, 别处不得直接 set resolver_approved
G.3   反证: provisional 晶体过期/驱逐后 canonical 文件仍在(invalidate≠delete)
G.4   pytest -q 全绿 + write_surface_check.py 绿 + public_checkout_probe --strict 绿
```

---

## 6. 验收(本地全量验证)

实施验收流：本地改 → RED-first(测试在改前 FAIL) → pytest -q 全量绿 → write_surface_check.py 绿(零 unclassified) → public_checkout_probe --strict 绿 → git diff --check 绿。

反证式验证重点：
- **发言真发得出去**(S0.1：owner-send → 实发；S0.2：世界级 → blocked)。
- **判决栈结果真的改变了晋升路由**(R3.1：合成 cascade+provisional verdict，看晋升从 owner_eligible 变 resolver_approved)。
- **可逆铁证**(G.3：provisional 过期后 canonical 留存、不删除)。
- **静默失忆防护在**(P5 digest 倒计时+confirm/reject 存在，owner 窗口内复核)。
- **双轴闸是唯一入口**(G.2：别处不能绕过 resolver_gate 直接造 resolver_approved)。
- **ExecutionGate 全覆盖**(G.1：每条 resolver 写入有 envelope，write_surface unclassified_count=0)。
- INV-5：resolver 判决在离线 lane / aggregation lane，不在 prefetch 热路径。
- INV-7/INV-8：所有自动写入有 ExecutionGate + StructuralWriteGate。
- 诚实性：一切 resolver 动作可逆 + 审计 + owner 终审。LLM 判错代价 ≤ 7 天可逆窗口。

---

## 7. 总结

afferent(感知/判决)早就建好并在跑；这份规约补 efferent(动作)：
- **发言放开**：speak_gate 新增真发路径(owner-send) + 动态 owner 通道解析 + 审计反哺
- **记忆晋升接线**：判决栈(cascade_routing + provisional)解 orphan → resolver_approved 即刻生效 + 7d/cap30 可逆安全网 + owner 窗口复核 + ExecutionGate 全路径覆盖

安全的根是**可逆 + ExecutionGate**。规模：中等等级（5 个 phase，约 6-8 个文件改动），无大新建，每步可独立验证。把闷在里面的内驱,放出来。
