# A3 可执行规约 — lane 开关(布尔钮,owner-gated,复用 V3 override 系统)

> 目标读者:codex(在 `Hermes-Memory-OS` 仓库内执行)。
> 性质:把"lane 开关"纳入 V3 的 governed override 系统——布尔钮、owner-gated、可逆、审计、kill 兜底。完成 V3 愿景最后一块(阈值 ✓A1 / A/B ✓A2 / lane 开关 = A3)。
> 纪律:勾真实运行时闸点(不造统一 enabled)、owner-gated(blast radius 大)、复用 V3 生命周期、安全 lane 先行、RED-first。

## 0. 锁定方向
- A3 = lane 开关类钮,完成 V3 愿景;A1/A2 已落。
- **owner-gated**:lane 开关 blast radius 大(整模块上下线),即便可逆也**一律走 owner,不 resolver-auto、不 A/B**(模块开 vs 关是大实验,owner 决定)。
- **价值定位(诚实)**:A3 不是"系统自动翻 lane"(太险),是把 lane 开关**纳入受治理/审计/可逆/kill 兜底的 override 系统**——取代散落的 ad-hoc config 改动。autonomy 不是目标,governance 一致性才是。

## 0.1 现状(已 ground-check)
- ⚠ **无统一 enabled 运行时闸**:manifest `"enabled": False` 多为默认元数据,非统一运行时 gate。cognitive_loop 步骤来自 `_step_functions`。
- ✅ **真正运行时读的开关 = config-enable 模式**:`low_clue_recall.enabled` / `hindsight_adapter_enabled` / `diagnostic_grounding_enabled`,经 `config.get` 在运行时 gate(__init__.py:132/636/668)。**这些是最干净的可门控点。**
- ✅ V3 override 系统全在:OVERRIDABLE_KNOBS(现都是 int+bounds)、resolve_knob(call-time)、register_override(边界 fail-closed)、override_sweep(TTL/cap/kill)、owner confirm/reject、confirm_override、可逆。
- ⚠ 现钮全是 **int+bounds** 类型 → A3 要扩**布尔钮类型**。

**A3 = 扩布尔钮类型 + 勾一个安全 config-enable lane 的运行时闸 + owner-gated 路由,复用 V3 其余全部。**

## 0.2 INV 保持
- INV-5:resolve_knob 确定性查表;lane 闸点 call-time 读,无 LLM。
- 可逆:lane 开关回退=恢复 default enabled 态。
- 边界即 store:只登记的 lane 可门控;关键/meta lane 不登记→够不着。

---

## 1. 布尔钮类型(扩 OVERRIDABLE_KNOBS)
现钮 `{default:int, bounds:[lo,hi]}`。lane 开关钮换一种:
```python
"lane_low_clue_recall_enabled": {
    "module": "low_clue_recall",
    "default": False,            # 当前 config 默认(codex 对齐真实默认)
    "kind": "lane_switch",       # ← 新类型标记
    "allowed": [True, False],    # 布尔, 取代 bounds
    "meta": False,               # 非治理 V3 自身
    "scope": "upper_layer",
    "ab_metric": None,           # lane 开关不 A/B
},
```
- `register_override` / `resolve_knob` 处理布尔:校验 value ∈ allowed(取代 bounds 范围检查)。
- `resolve_knob("lane_low_clue_recall_enabled", default=<config值>)` 返回布尔。

## 2. 勾真实运行时闸点(第一个安全 lane)
**推荐第一刀:`low_clue_recall`**(config-enable、运行时读、非关键、非 meta、可逆)。其运行时 enable 检查改成**也查 override**:
```python
# 原: enabled = bool(config.get("low_clue_recall",{}).get("enabled"))
# 改: config 值作 default, override 可覆盖(call-time)
cfg_default = bool((config.get("low_clue_recall") or {}).get("enabled"))
enabled = resolve_knob("lane_low_clue_recall_enabled", default=cfg_default)
```
- **第一刀只勾这一个 lane**,证布尔 lane 开关机制通,再扩。
- **不碰**:关键门禁(ops_gate / resolver_gate / speak_gate)、meta lane(knob_ab_eval / override_sweep / kill switch / self_evolution 自身)——这些不登记进 OVERRIDABLE_KNOBS,边界即 store 挡住。

> lane 选择可换:`diagnostic_grounding` / `hindsight_adapter` 同样是干净 config-enable 点。codex 与 owner 确认第一个 lane 取哪个;机制一致。

## 3. owner-gated 路由(lane 开关永不 resolver-auto)
`knob_override_auto_approvable` 对 `kind=="lane_switch"` **一律返回 False → 退 owner**:
```python
def knob_override_auto_approvable(knob, to) -> bool:
    spec = OVERRIDABLE_KNOBS.get(knob)
    if spec is None or spec.get("meta"): return False
    if spec.get("kind") == "lane_switch":
        return False              # ← blast radius 大, 永远 owner 决定
    # 阈值钮: 界内才自动(A1/A2 原逻辑)
    return _within_bounds(spec, to)
```
- lane 开关提议 → 进 owner digest,owner 确认才生效;不经 A/B、不 resolver-auto。
- self_evolution 可提议 lane 开关(若有信号),但**只走 owner 路径**。

## 4. 生命周期(完全复用 V3)
- override 上线即生效(provisional)、可逆(回退恢复 default enabled 态)。
- owner 确认→永久 / 拒绝或过期→回退。
- **kill switch 总闸**:拉闸,lane 开关 override 回退→恢复 default enabled 态(系统回到"没改过 lane"的安全态)。
- override_sweep 已处理这些;lane 开关 override 与阈值 override 走同一 sweep(回退逻辑通用:恢复 prior/default)。

## 5. 复用 vs 新建
| 件 | 复用 | 新建 |
|---|---|---|
| store/resolve_knob/register/sweep/可逆/kill | V3 全套 | 布尔类型处理(allowed 取代 bounds) |
| owner confirm/reject/digest | V3 | lane 开关项 |
| 自动批判决 | knob_override_auto_approvable | +lane_switch→owner 分支 |
| lane 运行时闸 | low_clue_recall config-enable 点 | call-time 查 override |
| 边界即 store | register_override | — |

**新东西极少:布尔类型 + 一个 lane 闸点 + 一行 owner 路由。其余全复用。**

## 6. 分期
| Phase | 内容 |
|---|---|
| **A3a** | 布尔钮类型(allowed/lane_switch kind)+ register_override/resolve_knob 处理布尔 |
| **A3b** | knob_override_auto_approvable 加 lane_switch→owner 分支 |
| **A3c** | 勾 low_clue_recall 运行时闸点(call-time 查 override)+ owner digest lane 项 |

A3a 先(类型)→ A3b(路由)→ A3c(接真 lane)。

## 7. 测试断言(RED-first)
```
布尔类型:
A3.1  lane_switch 钮 register_override 接受 True/False、拒绝非布尔/非 allowed
A3.2  resolve_knob 返回布尔; 无 override 时返回 config default

owner-gated 路由(核心):
A3.3  lane_switch 钮 → knob_override_auto_approvable 返回 False(永退 owner)
A3.4  阈值钮(min_cluster_size)仍按界内自动(A3 不破 A1/A2)
A3.5  lane 开关提议 → 进 owner digest, 不 resolver-auto、不 A/B

真 lane 生效:
A3.6  override lane_low_clue_recall_enabled=True → low_clue_recall 运行时真启用
      override=False → 真停用; 无 override → 用 config default(端到端反证)

边界 + 可逆 + kill:
A3.7  关键/meta lane(如 ops_gate)未登记 → register_override 拒(边界即 store)
A3.8  lane override 回退 → 恢复 config default 态
A3.9  kill switch → lane override 回退恢复 default
```

## 8. 诚实限制
- **owner-gated,非自治**:lane 开关一律 owner 决定,A3 给的是"受治理的可逆 lane 切换",不是"系统自动翻 lane"。
- **先证一个 lane**(low_clue_recall);其余 lane 逐个登记扩。
- **不 A/B**:模块开 vs 关是大实验,第一刀不做;owner 判。

## 9. 验收(Claude 复验)
- **反证 A3.6(核心)**:override lane=True/False → low_clue_recall 运行时真启停;无 override 用 config default。
- **owner-gated(A3.3/A3.5)**:lane 开关永退 owner,不 resolver-auto。
- **不破 A1/A2(A3.4)**:阈值钮仍自动。
- **边界(A3.7)**:关键/meta lane 未登记、够不着。
- **kill+可逆(A3.8/A3.9)**:回退恢复 default、kill 总闸。
- 脊柱一致:lane 开关复用 V3 的可逆+provisional+owner+kill,只是钮变布尔、路由强制 owner。

## 10. 一句话
A3 把 lane 开关纳入 V3 的 governed override 系统:扩布尔钮类型、勾一个安全 config-enable lane(low_clue_recall)的真实运行时闸、lane 开关一律 owner-gated(blast radius 大,不 resolver-auto 不 A/B)、复用 V3 的可逆/provisional/kill。完成 V3 愿景最后一块。诚实说:这是受治理的可逆 lane 切换,不是自动翻 lane——owner 仍是 lane 的决策者,A3 给的是治理一致性(审计/可逆/kill),不是 autonomy。
