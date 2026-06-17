# V1 可执行规约 — 闭合右脑表达环(事件驱动自发发言 + ≤5/小时限流)

> 目标读者：codex（在 `Hermes-Memory-OS` 仓库内执行）。
> 性质：W2 把发言闸开到了 owner，V1 让右脑**真的对 owner 自发开口**——生成→判定→owner-send 端到端跑通，事件驱动，限流。
> 纪律：复用现有机件、发言不设审批闸但限流+审计、纯确定性限流、RED-first 测试、INV 不破。

## 0. 锁定决策(owner 已拍)

- **触发 = 纯事件驱动**(不再 weekly 定时)。
- **发言上限 = ≤5 条/小时**(滚动窗口)。有话好好说、慢慢说。
- 发言**不设审批闸**(P1)；审批只在"发言→长期记忆晶体"那步(已由 W1 resolver 层处理)。
- 范围仅上层；不碰记忆底座、不碰 Hermes agent。

## 0.1 现状(已验，codex 复核)
- ✅ owner-send 投递机件齐：`evaluate_expression_draft / evaluate_wandering_output` 钩子在；`_deliver_to_owner`、`_resolve_owner_channel → resolve_owner_review_channel(store)` 动态解析在；channel_mismatch 拦非 owner、无 store send_blocked。
- ⚠ 当前唯一调用是宿主观测测试档(`channel="origin"`, `delivery_tier="test_host_observation"`)——**不是生产自发表达触发**。
- ⚠ 触发是 `weekly_wandering`(定时)，**非事件驱动**。
- ⚠ **无任何限流**。
- ⚠ wandering 仍 `_record_would_send`——生产路径要确保走 `_deliver_to_owner` 而非 would_send 残留。

**所以 V1 = 加 3 件 + 清 1 件**：事件驱动触发、≤5/h 限流、走真 owner 通道；清 would_send 残留。机件不新建。

---

## 1. 事件驱动触发(替 weekly)

### 1.1 触发点
在 cognitive_loop 每 tick(或新 event 到达)时，跑一条**自发表达评估**：

```
new qualifying events?
  → 右脑生成候选表达(wandering_mind / expression_draft, 复用现有生成器)
  → grounded_expression_judge 判定(值不值得说 / grounded / 非噪声 —— 复用现有判官)
  → 若判定"说" 且 限流未满
        → speak_gate.evaluate_*(channel=<resolved owner_channel>, delivery_tier="spontaneous_owner")
        → owner-send → _deliver_to_owner → owner
  → 否则 silent(记审计, 不发)
```

### 1.2 质量过滤交给现有判官，不另立白名单
**不新增"哪类 event 才触发"的白名单**——让 `grounded_expression_judge` 当唯一质量门(它本就在判表达 grounded/值得说)。事件驱动只意味着"有新 event 时跑这条评估"，是否真说由判官 + 限流决定。避免又造一层规则把内驱规则化(P1 反面)。

### 1.3 通道走动态解析(非测试档)
生产自发表达用 `channel = _resolve_owner_channel()`(W2 已建的 `resolve_owner_review_channel`)，`delivery_tier="spontaneous_owner"`——**不是** `channel="origin"` 那个 `test_host_observation` 测试档。世界级仍走 `send`(disabled)，不发。

---

## 2. ≤5/小时限流(纯确定性)

### 2.1 滚动窗口限流器
```python
# plugins/modules/expression/speak_rate_limit.py  (新文件, 纯确定性)
MAX_PER_HOUR = 5
WINDOW_SECONDS = 3600

def under_speak_limit(deliveries: list[dict], now: datetime) -> bool:
    """滚动 60 分钟窗口内成功 owner-send < 5 则放行。"""
    cutoff = now - timedelta(seconds=WINDOW_SECONDS)
    recent = [d for d in deliveries
              if d.get("decision") == "delivered"
              and _parse_ts(d.get("ts")) > cutoff]
    return len(recent) < MAX_PER_HOUR
```
- 计数源 = 现有 `deliveries.jsonl`(owner-send 成功记录)——**复用现成日志，不新建状态**。
- 滚动 60 分钟窗口(非固定整点桶，更准)。

### 2.2 超限行为
超限 → **不发**，记审计 `decision="rate_limited"` + reason + 被压表达的 judge 分。
- v0 取简单：超限直接 drop + 审计(不积压队列)。
- 可选(后续)：保留窗口内 judge 分最高的 1 条顺延下窗——但 v0 先不做，避免积压复杂度。

### 2.3 限流在 send 前、judge 后
顺序：judge 判"说" → 限流检查 → 放行才 `_deliver_to_owner`。限流是**发言阀**不是质量门，judge 仍照常跑(被限的也留 judge 记录，喂 §4 反哺)。

---

## 3. 端到端 + 清 would_send 残留

- 生产自发路径**必须**走 `owner-send → _deliver_to_owner`，不得落 `_record_would_send`。
- `would_send` 仅保留给 disabled 的世界级 `send` 模式(决策2，世界级未开)。
- cognitive_loop 把测试观测档(`test_host_observation`)与生产自发档(`spontaneous_owner`)分开——测试档可留作 doctor 自检，生产档走真投递。

---

## 4. 发言不审批、但限流 + 审计反哺(P1 + P3)

- 发言**无审批闸**(P1)：judge + 限流是仅有的两道闸，都不是"人审"。
- 每次发言/静默/限流 append_audit(说了什么 / 何时 / 哪个右脑模块 / judge 分 / 限流状态)。
- 该 audit 经 feedback_bridge 反哺右脑输入(W2 已接 speak_gate delivery audit 回流)——**为 V2(反馈环)预留接口**：发言记录成为"我说过什么"的 source。

---

## 5. 复用清单

| 件 | 复用 | 新建 |
|---|---|---|
| 生成器 | wandering_mind / expression_draft | — |
| 质量门 | grounded_expression_judge | — |
| owner-send 投递 | speak_gate `_deliver_to_owner` + owner-send 模式 | — |
| 通道动态解析 | `_resolve_owner_channel` / `resolve_owner_review_channel` | — |
| 投递日志 | `deliveries.jsonl` | — |
| 审计反哺 | feedback_bridge speak audit 回流 | — |
| **事件驱动触发** | cognitive_loop tick | 自发表达评估步 |
| **限流** | `deliveries.jsonl` 计数 | `speak_rate_limit.py`(纯确定性) |

**核心仍是接线 + 一个确定性限流文件。**

---

## 6. 交付分期

| Phase | 内容 |
|---|---|
| **V1a** | `speak_rate_limit.py`(滚动窗口 ≤5/h) + 测试。纯确定性，独立可测。 |
| **V1b** | cognitive_loop 加事件驱动自发表达评估步：生成→judge→限流→owner-send(`spontaneous_owner` 档, 真 owner 通道)。 |
| **V1c** | 清 would_send 残留：生产路径断言走 `_deliver_to_owner`；测试观测档与生产档分离。 |
| **V1d** | weekly_wandering 处置：保留作低频兜底，还是停用(事件驱动已覆盖)？建议保留为周级兜底、降权，不与事件驱动重复发。 |

---

## 7. 测试断言(RED-first)

```
限流:
V1.1  窗口内已 5 条 delivered → under_speak_limit False(第6条不发, 记 rate_limited)
V1.2  窗口内 4 条 → True(第5条放行)
V1.3  5 条中有过期(>60min)的 → 过期不计, 放行
V1.4  rate_limited 的表达仍留 judge 记录(喂反哺)

事件驱动 + 端到端:
V1.5  新 qualifying event + judge 判"说" + 限流未满
      → owner-send delivered(channel=resolved owner_channel, 非 origin 测试档)
      (RED: 现 weekly 触发 + 测试档, 不会因 event 自发发到 owner)
V1.6  judge 判"不说" → silent, 不发, 记审计
V1.7  生产自发路径走 _deliver_to_owner, 不落 _record_would_send(清残留断言)
V1.8  channel != resolved owner_channel(世界级) → send_blocked(决策2)

不破坏:
V1.9  发言无审批闸: 不引入任何 owner-approval 前置(P1)
```

---

## 8. 微决策(基本已锁，剩两个小点)

1. **超限处置**:v0 直接 drop+审计(推荐) vs 保留最高分顺延下窗。建议 v0 drop，简单。
2. **weekly_wandering 去留**:停用 vs 降权保留作周级兜底。建议保留+降权，事件驱动为主、周级兜底防"长期没 event 时彻底沉默"。

确认这两点(或采纳建议)，codex 即可按 V1a→V1d 切片做。

---

## 9. 验收(Claude 复验重点)

- **反证 V1.5**:合成一个 qualifying event → 看是否真因 event 自发发到 owner(非定时、非测试档)。
- **限流真咬**:第 6 条被 rate_limited，窗口滚动后恢复。
- **清残留**:生产自发路径 0 条落 would_send。
- **通道动态**:发到 resolved owner_channel，世界级 send_blocked。
- **P1 守住**:发言路径无 owner-approval 前置。
- 朝 V3 的脊柱一致性：V1 仍是"确定性闸(judge+限流)+ 无人审 + 全审计"，与 W1 resolver 模式同源。
