# V3 可执行规约 — 自演化第一刀(单旋钮 min_cluster_size,复用 W1+V2)

> 目标读者:codex(在 `Hermes-Memory-OS` 仓库内执行)。
> 性质:把 W1 的"可逆-provisional-窗口-owner确认/自动回退"机制,从**记忆晶体**指向**系统自己的一个旋钮**。这是自演化层的第一刀,层是攒出来的、不是先建的。
> 纪律:复用现有机器、可逆优先、界内、全审计、INV 不破、RED-first。

## 0. 这是什么 / 不是什么

**是**:`min_cluster_size` 这一个旋钮的端到端自演化——self_evolution 提议改它 → resolver 判(可逆+非meta+界内)→ provisional 落地(即刻生效、可逆)→ V2 反馈环观察 → 窗口内 owner 确认转永久 / 否则自动回退前值。

**不是**(明确不做,避免过早泛化):
- ❌ 不建大旋钮注册表——只登记 `min_cluster_size` 一个,store 自然攒成列表。
- ❌ 不建独立 A/B 台——provisional-观察-回退 + owner 窗口确认**就是** A/B。自动化"较准"指标**延后**。
- ❌ 不建 meta-knob 框架——第一个旋钮非 meta,只要"不登记敏感旋钮"即可;meta 标记等真要碰敏感旋钮才变真机制。

## 0.1 为什么 min_cluster_size 是对的第一刀(已验)
- 单个参数 `min_cluster_size: int = 2`,全仓**仅 2 处调用点**(candidate_aggregation:204/230)。
- 纯上层(L3 candidate_aggregation)、**天生可逆**(改个 int,回退=恢复前值)、效果直接可观察(控候选聚类晋升 → V2 反馈环看得见)。

## 0.2 INV 保持
- **INV-5**:`resolve_knob` 是确定性 store 查表(无 LLM、快),不在热路径增 LLM;self_evolution 提议在离线 lane。
- **可逆**:override 永远可回退到 `prior_value`(invalidate-not-delete:override 记录留存、标回退,值复原)。
- **INV-6**:propose/enact/confirm/revert/kill 每步审计。

---

## 1. knob-override store(唯一的小新件)

```python
# plugins/memory/memory_os/knob_overrides.py  (新, 镜像 crystal provisional 生命周期, 但对象是配置值)

# 可覆盖旋钮登记表 —— 边界就在这: 没登记的旋钮 V3 够不着(底座/Hermes 旋钮永不登记)
OVERRIDABLE_KNOBS = {
    "min_cluster_size": {
        "module": "candidate_aggregation",
        "default": 2,
        "bounds": [2, 5],
        "meta": False,            # 非治理 V3 自身 → 可自调
        "scope": "upper_layer",
    },
}

# override 记录形状
# {knob, override_value, prior_value, bounds, provisional, expires_at,
#  proposed_by, approved_via("resolver"|"owner"),
#  state("active"|"confirmed"|"reverted_expired"|"reverted_owner"|"reverted_kill"), ts}

def resolve_knob(name: str, default):
    """确定性: active 且未过期的 override 用之, 否则 default。无 LLM。"""

def register_override(name, value, *, prior, proposed_by, approved_via, expires_at):
    """写 override。拒绝: 旋钮不在 OVERRIDABLE_KNOBS / value 越 bounds / 旋钮 meta=True。"""
```

**边界即 store**:`register_override` 对任何不在 `OVERRIDABLE_KNOBS` 的旋钮、或越 bounds、或 `meta=True` 的旋钮,**fail-closed 拒绝**。底座/Hermes 旋钮根本不在表里 → V3 物理上够不着。这就是"只上层、不碰底座/Hermes"的机器强制,不另写检查。

---

## 2. 接 min_cluster_size 读取(⚠ 陷阱:必须 call-time 解析)
现状:`_cluster_and_promote(... min_cluster_size: int = 2 ...)`(candidate_aggregation:204 默认参数)+ :230 使用。

**⚠ 关键陷阱:不要把 `resolve_knob()` 放进默认参数。** Python 默认参数在**函数定义时(import 时)只求值一次**——若写 `min_cluster_size: int = resolve_knob(...)`,override 改动**永远读不到**(值在 import 时冻死)。这会让整个 V3 静默失效。

**正确做法:call-time 解析(调用点或函数体内):**
```python
def _cluster_and_promote(..., min_cluster_size: int | None = None, ...):
    if min_cluster_size is None:
        min_cluster_size = resolve_knob("min_cluster_size", default=2)
# 或在 lane 入口每次调用时 resolve_knob 传入
```
**V3.1 测试必须验"改 override 后下一次调用真读到新值",专门钉这个陷阱。**

---

## 3. self_evolution 提议旋钮改动(扩现有 proposed_actions)
self_evolution 已在产 `proposed_actions`。加一个 kind:
```python
{"kind": "knob_tune", "knob": "min_cluster_size", "from": 2, "to": 3, "bounds": [2, 5]}
```
- `to` 必须界内(否则提议自身被 store 拒)。
- **第一刀的调参启发式可以很简单**(甚至占位):比如 owner-eligible backlog 大且 owner 确认率低 → 提议升 min_cluster_size 减噪。**第一刀重点是机制通,不是聪明的调参策略**——策略后面再进化。

---

## 4. 旋钮判决(比 W1 双轴更简单——别照搬 resolver_gate)
**复盘修正:resolver_gate 的 `resolver_eligible(candidate)` 吃的是 candidate(bridge_state/sensitivity/identity 信号),旋钮不是 candidate,不能直接调。而且旋钮的判决比 candidate 简单得多——别照搬。**

旋钮判决是个**新的小函数**,就三条(reversible 对配置值恒为真):
```python
def knob_override_auto_approvable(knob, to) -> bool:
    spec = OVERRIDABLE_KNOBS.get(knob)
    return (spec is not None              # 已登记(边界)
            and spec["meta"] is False     # 非 meta(不碰 V3 自身)
            and bounds_lo <= to <= bounds_hi)  # 界内
    # reversible 恒为真(回退=恢复 prior),无需判
```
真 → resolver 自动 provisional 落地;假(未登记/meta/越界)→ owner(进 digest)。min_cluster_size 2→3:自动落。**这是新函数,不是 resolver_gate 的调用。**

---

## 5. provisional 生命周期(镜像 provisional_sweep,对象是 override)
新建一个 override sweep(照 provisional_sweep 写法,no_agent lane):
```
每 sweep:
  ① TTL 到期未确认 → 回退 prior_value, state="reverted_expired", audit
  ② owner 确认 → provisional=False, 清 expires_at, state="confirmed"(永久)
  ③ owner 拒绝 → 回退 prior_value, state="reverted_owner", audit
  ④ kill switch engaged(live_guard)→ 所有 active override 回退 prior, state="reverted_kill", audit
```
- TTL 默认 7 天(与 crystal provisional 一致)。
- **回退 = 恢复 prior_value**(override 记录留存标回退,非删)。
- **kill switch 是总闸**:live_guard 一拉,所有自演化 override 立即回退到原值——系统瞬间回到"没自改过"的安全态。

---

## 6. "较准"怎么判(第一刀:owner 窗口确认 + 反馈上下文)
**第一刀不建自动 A/B 指标。** provisional override 进 #3 owner digest:
```
"min_cluster_size 2→3 · 还剩 Xd · [确认/回退]
 自改后: owner 确认率 40%→55% / backlog 1255→1100(V2 反馈环上下文)"
```
- owner 窗口内看反馈上下文,确认(转永久)或回退。**owner 窗口确认就是第一刀的验证信号**。
- 自动化"A/B 较准"指标 = 后面的事。

**复盘修正:owner-action 是新的平行函数,不是复用 crystal 版。** owner_actions.py 有 `confirm/reject_provisional_crystallized_record` 的模式,knob 版要写**平行的** `confirm/reject_provisional_knob_override`,并在三处挂接:`ACTION_TYPES` 注册表、`apply_owner_action` 分发、`_provisional_*_review_items` 加 digest 项。是镜像不是复用。

---

## 7. 守卫汇总
| 守卫 | 机制 |
|---|---|
| 越界 | register_override 拒绝 value ∉ bounds |
| 越权(碰底座/Hermes) | 旋钮不在 OVERRIDABLE_KNOBS → 拒绝(边界即 store) |
| 碰 V3 自身(meta) | meta=True 旋钮拒绝自调(第一刀无 meta 旋钮) |
| 可逆 | 回退恢复 prior_value, 永远可行 |
| 总闸 | live_guard kill switch → 全 override 回退 |
| 无 LLM 热路径 | resolve_knob 确定性查表 |
| 审计 | 每步 append_audit |

---

## 8. 复用 vs 新建
| 件 | 复用 | 新建 |
|---|---|---|
| 双轴判决 | resolver_gate 模式 | 换对象到 override |
| provisional 生命周期 | provisional_sweep 模式 | override sweep(小,镜像) |
| owner 确认/回退 digest | #3 cluster owner-action | +knob_tune 项 + 反馈上下文 |
| 反馈观察 | V2 反馈环 | — |
| kill switch | live_guard | 接 override 回退 |
| 提议 | self_evolution proposed_actions | +knob_tune kind |
| 审计 | append_audit | — |
| **knob-override store** | — | **唯一实质新件(~一两百行)** |

**绝大部分是复用 W1/V2/#3 的现成机器;唯一新件是那个小 store。**

---

## 9. 分期
| Phase | 内容 | 可独立测 |
|---|---|---|
| **V3a** | knob_overrides.py(store + resolve_knob + register_override + OVERRIDABLE_KNOBS) + 接 candidate_aggregation 2 处 | ✓ 合成 override 即可测,无需 self_evolution |
| **V3b** | self_evolution knob_tune 提议(界内)+ resolver 双轴判 → provisional override | ✓ |
| **V3c** | override sweep(TTL回退/owner确认/拒绝/kill回退)+ #3 digest knob_tune 项 + 反馈上下文 | ✓ |

V3a 先(store + 接读取,默认行为不变),V3b 接提议+判决,V3c 生命周期+露出面。

---

## 10. 测试断言(RED-first)
```
store + 边界:
V3.1  active 未过期 override → resolve_knob 返回 override; 无/过期 → default
V3.2  value 越 bounds → register_override 拒绝
V3.3  旋钮不在 OVERRIDABLE_KNOBS(模拟底座旋钮)→ 拒绝(边界机器强制)
V3.4  meta=True 旋钮 → 自调被拒, 退 owner

提议+判决:
V3.5  self_evolution 提议界内 → resolver 自动 provisional 落地(可逆+非meta+界内)
V3.6  提议越界 → 不落地

生命周期:
V3.7  provisional 过期未确认 → 回退 prior_value(min_cluster_size 回 2), audit
V3.8  owner 确认 → 永久(provisional=False), 值保持 3
V3.9  owner 拒绝 → 回退 prior, audit
V3.10 kill switch engaged → 全 active override 回退 prior, audit

端到端反证(核心):
V3.11 提议 2→3 → 自动落地 → candidate_aggregation 聚类真的用 3
      → 过期未确认 → 回退 2 → 聚类真的回到 2
      (证明: override 真生效、回退真复原)

守卫:
G.1  resolve_knob 无 LLM(INV-5)
G.2  register_override 对未登记/越界/meta 旋钮 fail-closed
```

---

## 11. 层是怎么攒出来的(前瞻,现在不做)
第一刀通了,加第二个旋钮(MAX_PER_HOUR 发言率):只是往 OVERRIDABLE_KNOBS 加一条 + 接它的读取点。store 自然长成"注册表",bounds 一个个攒。**只有当你想调一个治理 V3 自身的旋钮(resolver 双轴/kill switch/A/B 判准)时,meta 保护才需要变成真机制**——那时你已在真实旋钮上看过这套跑起来,再决定要不要加那层复杂度,心里有底。自动化 A/B 指标同理,等简单的"observe+owner确认"不够用了再上。

---

## 12. 验收(Claude 复验)
- **反证 V3.11(核心)**:提议改 min_cluster_size → 自动落地 → 聚类真用新值 → 过期回退 → 聚类真复原。override 真生效、回退真复原,两头都验。
- **边界机器强制**:未登记旋钮(模拟底座)被 register_override 拒(V3.3)——"不碰底座/Hermes"是 store 拒绝,不是文档承诺。
- **kill switch 总闸**:拉闸全 override 回退到原值(V3.10),系统秒回"没自改过"。
- **可逆铁证**:过期/拒绝/kill 后 override 记录留存(标回退)、值复原。
- **INV-5**:resolve_knob 确定性、无 LLM。
- 脊柱一致:V3 就是 W1 那套(可逆+provisional+窗口+owner确认/回退)指向旋钮。整条线 W1→V1→V2→V3 同一根脊柱。

## 13. 一句话
V3 第一刀 = 把 W1 的可逆-provisional-观察-回退,从记忆晶体指向 `min_cluster_size` 一个旋钮。唯一新件是个小 knob-override store,其余全复用。边界即 store(没登记够不着)、总闸是 kill switch(一拉全回退)、验证是 owner 窗口确认。层是攒出来的,不是先建的——这一刀通了,你就在真实旋钮上亲眼看过自演化,再决定下一个。
