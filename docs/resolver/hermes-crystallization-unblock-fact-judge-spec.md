# 结晶解封可执行规约 — 离线 LLM 耐久事实判官 + 单次晋升通道

> 目标读者: codex（在 `Hermes-Memory-OS` 仓库内执行）。
> 性质: 解封结晶停滞（159 候选 : 0 结晶）。根因经代码 ground-check 修正：**只有一道闸**（size≥2 聚类），不是两道。修法: 离线 LLM 判官做一件事——分叉"耐久事实 vs moment"——耐久事实给单次晋升通道绕过 size≥2，喂进早已建好的 W1 resolver 路自动结晶。
> 纪律: 复用现成 judge 框架 + resolver 路、判官离线（不破 INV-5）、可逆、RED-first。判官少做一件事 = 少一个准确度依赖。

## 0. 锁定决策（owner 已拍）

- **方案 A**: 判官只做 `durable_fact` 分类一件事，不碰敏感度。
- **判官保守起步**: 先求精度（只放明确的耐久事实），召回后续调。判官一松 = digest 里要撤的多。
- **B 留作后手**: 如果上线后发现身份关键词匹配太漏、owner 天天在 digest 里撤敏感自动结晶——那时再上 B（判官加语义敏感检测 + `identity_sensitive` 新值挡 resolver）。没出现就别提前加复杂度。

## 0.1 根因（已 ground-check，修正了原版的敏感度假闸诊断）

- ✅ **W1 resolver 自动批路已在** `candidate_aggregation:294-360`: `_resolver_verdict` → `resolver_approved` → `start_resolver_auto_approve_envelope` → provisional crystal。**整条路通的，只是没料喂到。**
- ✅ `inner_drive_candidate` **进**聚类逻辑（line 233: `bridge_state in ("", "inner_drive_candidate")`），不是隔离死路。
- ✅ LLM 判官框架现成: `_call_hermes_runtime_model` / `_extract_json_object`（low_clue_recall.py）——prompt→调模型→解析 JSON。
- ⚠ **唯一的闸（size≥2）**: `_cluster_and_promote:247` `if len(members) < min_cluster_size: continue` → singleton 全跳过，到不了 resolver verdict。
- ⚠ 根因: `process_event` 把**所有**事件候选打 `inner_drive_candidate`，事实和 moment 不分 → 几乎永远是 singleton → 全被 size≥2 挡下。

### 0.1.1 纠正: 敏感度不是第二道闸

原诊断称"private 敏感度挡住 resolver"。代码 `resolver_gate.py:28`：

```python
NON_SENSITIVE = frozenset({"normal", "low", "private"})
```

**`"private"` 在 `NON_SENSITIVE` 里。** `is_reversible` 对 `sensitivity="private"` 返回 `True`（除非命中 `_has_identity_signal` 的身份关键词）。所以 Gate ② 不存在——只有 size≥2 一道闸。身份关键词匹配（`_has_identity_signal`）是对明显 PII 的独立兜底，不是 sensitivity 驱动的。

这意味着: 判官标敏感度对 resolver gate 零影响。判官只做 durable_fact 一件事——少做一件事 = 少一个准确度依赖。

### 0.2 修法（简化后）

**判官认出"耐久事实" → 给它单次晋升通道（绕过 size≥2）→ 喂进现成的 resolver 路** → 非敏感自动结晶、敏感的退 owner。判官只负责"这是不是值得永久记的事实"这一件事。

敏感度不管（`_has_identity_signal` 关键词匹配兜明显 PII），安全感来自三层兜底: ① 身份关键词匹配 ② provisional 7d TTL ③ owner digest 可见可撤。

---

## 1. 离线 LLM 判官（新模块，复用 judge 框架）

```python
# plugins/modules/governance/fact_judge.py（新，离线 cron lane）
# 复用 _call_hermes_runtime_model / _extract_json_object 模式

def judge_candidate(candidate, config) -> dict:
    """对一个 inner_drive_candidate 判: 是否耐久事实。

    返回 {"durable_fact": bool, "reason": str}
    """
```

- **职责单一**: 只判"是不是耐久事实（偏好/决定/事实性知识，值得永久记）vs moment/闲聊（寒暄/过程性/情绪流露/琐事）"。
- **不碰敏感度**: 原 `sensitivity="private"` 不动。身份 PII 已有 `_has_identity_signal` 关键词兜底。
- **离线**: 挂 cron lane（新 `fact_judge` lane），**不在热路径，不破 INV-5**。
- **保守 = 高精度起步**: 判官对 durable_fact 拿不准就判 `False`（宁可漏结晶、不误结晶噪声）。偏好/决定/明确事实 → `True`；闲聊/寒暄/情绪/过程性 → `False`。
- **fail-safe**: 判官失败/空响应/非 JSON → 候选**不动**（保持现状，不误结晶）。

### 1.1 判官 prompt 设计原则

- 明确 durable_fact 的定义: 偏好声明、决策记录、事实性知识、用户明确要求记住的内容。
- 明确 NOT durable: 寒暄、过程性对话、情绪流露（"今天好累"）、纯信息传递（"帮我查 X"）、无结论的讨论过程。
- 引导保守: "If uncertain whether this is a durable fact, answer False. Only mark True when clearly a lasting preference, decision, or factual knowledge."

## 2. 判官 verdict 落到候选

判官把 verdict 写回候选:
- 加标记 `durable_fact=True`（tag 或专用字段）供 aggregation 识别。
- moment/闲聊（`durable_fact=False`）→ **不动**，留在内驱 demote lane（现状对它对）。
- sensitivity 不碰，保持原值 `"private"`。

## 3. 单次晋升通道（给耐久事实绕过 size≥2）

`_cluster_and_promote` 在现有聚类循环后加一段:

```python
# 现有: for cluster_key, members in clusters.items():
#           if len(members) < min_cluster_size: continue
# 加: durable_fact 候选单独成"伪簇"进 resolver verdict，不受 size 闸约束

for c in candidates_for_promote:
    if _is_durable_fact(c):           # 判官标记
        _run_resolver_verdict_for([c])  # 单次进 resolver verdict（复用现成路）
# 其余仍走 size>=2 聚类（moment 不变）
```

- **只对 durable_fact 开口**: 非事实 singleton 仍不晋升（不泛滥）。
- 进 resolver verdict 后，**复用现成的 §0.1 那条 W1 路**: 非敏感 → `resolver_approved` provisional crystal；敏感 → `owner_eligible`。

## 4. resolver 选择性（已建，只是终于有料）

`_resolver_verdict` → `resolver_eligible`:
- 非敏感 + 耐久事实 → **resolver 自动批 → provisional crystal**（可逆、7d TTL、capped 30）。
- 身份关键词命中 → `owner_eligible`（owner 只看这部分残余）。
**这一步零新代码，W1 早建好，本规约只是把料喂对。**

## 5. 安全（三层兜底，无需判官管敏感度）

| 风险 | 兜底 |
|---|---|
| 判官误判"事实"（把 moment 当事实结晶） | provisional 可逆 + TTL 7d 自动回退 + owner digest 可见可撤 |
| 判官漏判"事实"（该记的没记） | 候选仍在队列，后续聚类可能成对晋升 |
| 身份 PII 漏过关键词 | `_has_identity_signal` 已有 20+ 关键词；provisional 可撤；7d TTL |
| 语义敏感（健康/情绪）漏过关键词 | provisional 可见可撤 + 7d 自动过期；风险低且可逆 |
| 判官故障 | fail-safe: 候选不动，不误结晶 |
| 热路径 LLM | 判官离线 cron，INV-5 不破 |
| 结晶泛滥 | resolver 仍按敏感度筛 + provisional capped 30 + TTL 7d |
| 判官过度松 → digest 大量撤 | 判官保守起步（§1 设计原则）；上线后监控 `_provisional_crystallized_review_items` 数量 |

## 6. 复用 vs 新建

| 件 | 复用 | 新建 |
|---|---|---|
| **resolver 自动批→crystal** | candidate_aggregation 294-360（W1，已建） | — |
| LLM judge 调用 | `_call_hermes_runtime_model` / `_extract_json_object` | fact_judge 的 prompt + 解析 |
| provisional 生命周期 | W1 + override_sweep | — |
| owner digest | 现成（`_provisional_crystallized_review_items`） | — |
| 聚类晋升 | `_cluster_and_promote` | +durable_fact 单次通道 |
| 身份 PII 兜底 | `_has_identity_signal`（resolver_gate.py） | — |
| cron lane | cron_registry | +fact_judge lane |

**新东西: 一个离线判官模块（只判 durable_fact）+ 单次通道一段。resolver / provisional / digest / 身份兜底全复用。**

## 7. 分期

| Phase | 内容 |
|---|---|
| **F1** | fact_judge 模块（复用 judge 框架）: 判 durable_fact；保守 + fail-safe；挂 cron lane |
| **F2** | verdict 落候选（durable_fact 标记）+ aggregation 单次通道 |
| **F3** | 端到端: durable 非敏感 → resolver_approved provisional crystal；durable 敏感 → owner；非 durable → 不动 |

## 8. 测试断言（RED-first）

```
判官:
F.1  judge_candidate 用 mock runner: 耐久事实（偏好/决定/事实性知识）→ durable_fact=True
F.2  闲聊/寒暄/过程性对话/情绪流露 → durable_fact=False
F.3  判官空响应/非JSON/故障 → 候选不动（fail-safe，不误结晶）
F.4  判官拿不准 → durable_fact=False（保守: 宁可漏、不误结晶）

单次通道:
F.5  durable_fact 单条（size=1）→ 进 resolver verdict（绕过 size≥2）
F.6  非 durable singleton → 不晋升（不泛滥）

resolver 选择性（复用 W1）:
F.7  durable + 非敏感 → resolver_approved provisional crystal（端到端: 0 结晶→有结晶）
F.8  durable + 身份关键词命中 → owner_eligible（owner 只看残余）

安全 + 可逆:
F.9  自动结晶的 provisional 进 owner digest 可见可撤
F.10 判官离线（INV-5: 不在热路径）

不回归:
F.11 判官不修改 candidate.sensitivity（保持原值 "private"）
F.12 moment 候选仍走 size≥2 聚类（行为不变）
```

## 9. 诚实限制

- **判官准确度决定召回/精度**: 漏判事实 = 漏结晶（但候选仍在队列，后续可能聚类成对）；误判事实 = 噪声结晶（但 provisional + 可逆 + TTL 兜底）。先求精度。
- **判官是唯一节流阀**: size≥2 不拦 durable_fact 之后，判官的 precision 直接决定 digest 里 owner 要撤多少。保守起步。
- **先解封，再调准**: 目标是从 0 结晶变成"非敏感事实自动结晶"——哪怕每天只有 2-3 条。judge 精度后续迭代上调。

## 10. 监控指标（上线后必看）

| 指标 | 含义 | 健康范围 |
|------|------|---------|
| `durable_fact_count` per run | 判官每次标注多少耐久事实 | 初期 1-5/run |
| `provisional_crystallized_count` | 每天自动结晶多少 | 初期 1-3/day |
| `owner_revoked_provisional_count` | owner 撤了多少自动结晶 | 0（理想）；>3/day = 判官太松 |
| `provisional_expired_count` | TTL 到期自动回退了多少 | 正常，预期该有 |

## 11. 验收（Claude 复验）

- **反证 F.7（核心）**: 一条对话耐久事实（非敏感）→ 判官 durable_fact → 单次进 resolver → **resolver_approved provisional crystal**。这是从"0 结晶"变"有结晶"的铁证。
- **不泛滥（F.6）**: 非事实 singleton 不晋升。
- **判官只做一件事（F.11）**: sensitivity 不变。
- **保守 + fail-safe（F.4/F.3）**: 拿不准不动、故障不动。
- **可逆 + INV-5（F.9/F.10）**: provisional 可撤、判官离线。
- **resolver 路零改动复验**: 确认 294-360 那条 W1 路被正确喂到、不是另起炉灶。

## 12. B 计划（记录，不实施）

如果上线后发现:
- 身份关键词匹配太漏 → 语义敏感内容（健康/情绪/隐私）频繁自动结晶
- owner 天天在 digest 里撤 > 5 条/day

则启动 B:
1. 判官加语义敏感检测（`sensitivity: "identity_sensitive"`）
2. 新增 `"identity_sensitive"` 到 resolver_gate 的**排除名单**（不在 `NON_SENSITIVE` 中，`is_reversible` 返回 `False`）
3. 效果: 判官标语义敏感 → resolver 挡 → 退 owner_eligible

**没出现就别建。** 我们这一路反复学的就是这个教训。

## 13. 一句话

结晶停滞的根因是**一道闸**（size≥2）: 对话候选全是 singleton，聚不成对，到不了早已建好的 resolver 自动批路。修法: **离线 LLM 判官做一件事——分叉耐久事实——给它单次晋升通道，喂进现成的 W1 路**。判官少做一件事（不管敏感度），少一个准确度依赖。非敏感事实自动结晶（可逆），owner 不逐条审。新东西只有判官 + 单次通道。先解封，再调准。
