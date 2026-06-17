# A1+A2 可执行规约(修订版) — 多旋钮 + 分层真实结果 A/B 自验证

> 修订说明:前版有事实错误(称 `_cluster_and_promote` 是纯函数、override_sweep 有 confirm 决策点、A1 读取点"已就绪")。更关键——C6/C7 逼出一个更干净的设计:**用按簇大小分层的真实 owner 结果做 A/B,而非重跑 shadow 算反事实**,直接去掉"带估计的 A/B"那个 hand-wave。

## 0. 锁定决策(不变)
- A1(多旋钮)+ A2(A/B 自验证)合并;A3 之后;C 增量清。
- **A/B 方式修正**:min_cluster_size 这个钮用**分层真实结果**(见 §2),比并行重跑 shadow 更准更简单。并行 shadow 重跑那条路留给"重跑才能评"的钮(如评分权重),那时才接 C。**先把这个钮用最干净的工具证通。**

## 0.1 现状(已 ground-check,修正前版)
- ⚠ **C1**:`_cluster_and_promote` **有副作用**(append_candidate_triage / processed_ids.add / 写晋升),**不是纯函数**。可抽出的是聚类判定逻辑(cluster_key + `len(members) < min_cluster_size`),抽取要排副作用。
- ⚠ **C2/C3**:`MAX_PER_HOUR`(speak_rate_limit:12,模块常量)、`MAX_PROVISIONAL`(provisional_sweep:89,局部)**都未接 resolve_knob**,要照 min_cluster_size 的 sentinel+param 模式接,**不是"已就绪"**。
- ⚠ **C4**:provisional_sweep:82-83 / 105-106 有**两处静默 `except: pass`**(违反无静默失败)。A1 要碰这文件,顺手用 build_error_record 修。
- ⚠ **C5**:override_sweep **没有 confirm 决策点**(只 TTL/cap/kill);owner confirm 走 owner_actions,`revert_override` 在 knob_overrides。A/B 自动确认需**新增 `confirm_override()`**(镜像 revert_override)。
- ⚠ **C6**:晋升记录**不带 cluster_size** → A/B 分层需新增这个字段。
- ✅ V3 机器全在;边界即 store、call-time、invalidate-not-delete、kill 兜底均验证坚实。
- 📍 路径修正(C8):speak_rate_limit 在 `plugins/modules/expression/`,非 governance。

---

## 1. A1 — 多旋钮(sentinel+param 接,显式)

```python
OVERRIDABLE_KNOBS = {
    "min_cluster_size": {... 已有, +"ab_metric": "stratified_confirm_rate" ...},
    "max_speak_per_hour": {"module": "expression/speak_rate_limit", "default": 5,
                           "bounds": [1, 12], "meta": False, "scope": "upper_layer", "ab_metric": None},
    "max_provisional":    {"module": "provisional_sweep", "default": 30,
                           "bounds": [10, 100], "meta": False, "scope": "upper_layer", "ab_metric": None},
}
```
- **speak_rate_limit(C2)**:`under_speak_limit` 加 `max_per_hour: int | None = None`,函数体内 `if max_per_hour is None: max_per_hour = resolve_knob("max_speak_per_hour", default=5, **kwargs)`(**sentinel 模式,绝不放默认参数**)。:38 用解析后的值。
- **provisional_sweep(C3)**::89 `MAX_PROVISIONAL = resolve_knob("max_provisional", default=30, ...)`(局部变量,call-time,需把 store root 传进来)。
- **顺手修 C4**:把 :82-83 / :105-106 的 `except: pass` 换成 `build_error_record()`(照 override_sweep 写法)——A1 既然碰这文件,把这个预存的静默失败一并清掉。
- 两新钮 `meta:False`、`ab_metric:None` → **先走 owner-confirm**,A/B 等各自指标定义后再纳入。
- **命名(M4)**:`max_provisional`(crystal provisional cap)与 override 自己的 `MAX_OVERRIDES`(override cap)是两个不同的 30,别混。

---

## 2. A2 — 分层真实结果 A/B(min_cluster_size 一个钮,真数据无估计)

### 2.1 关键洞见:不用重跑 shadow,用真实结果分层
前版想"重跑聚类算反事实"——但反事实的 delta 集**没有 owner 数据**(估计 gap)。**更干净的做法:按簇大小分层现有的真实晋升结果。**

⚠ **X 来自 `override.prior_value`,不是 `default`**(F4)。可能有链式 override(default=2→3 已确认,新 override 3→4):此时 prior=3、overide=4,收紧丢掉 size==3 的簇。始终读 override 记录的 `prior_value` 字段,不用 knob spec 的 `default`。

min_cluster_size 从 X 调到 X+1(收紧)= **丢掉大小恰为 X 的簇**。这些簇在当前值下**晋升过、被 owner 审过**——**我们有它们的真实裁决!** 所以:

```
丢掉的那层(size==X)的 owner 确认率 vs 保留层(size>=X+1)的确认率:
  size==X 层确认率 明显更低 → 丢掉它们(收紧)更好 → A/B 较准, auto-confirm
  size==X 层确认率 明显更高 → 丢掉它们更差 → auto-revert
  差距不清晰 / 观测不足 → 退 owner 窗口
```
**这是真数据,不是估计。** 收紧方向的 delta 恰好是"审过的、有裁决的"那批。

### 2.2 不对称:收紧能 A/B,放松退 owner(C7 诚实)
- **收紧(X→X+1)**:delta = size==X 的簇,审过 → **真数据 A/B**。
- **放松(X→X-1)**:delta = size==X-1 的簇,当前值从不晋升 → **从没被 owner 看过 → 无数据 → 退 owner**。
诚实写明:**放松方向无法 A/B,一律退 owner**;A/B 自治只对收紧方向生效。这不是缺陷,是数据现实——放松是"引入没见过的东西",本就该 owner 把关。

### 2.3 cluster_size 字段(C6,新增小管道)
`_cluster_and_promote` 晋升时,把 `cluster_size=len(members)` 写进晋升记录(owner_eligible candidate / 带到 crystal),让 owner 裁决能按簇大小分组。这是 A/B 的数据前提。

### 2.4 决策落点(C5,明确)
**新增 `confirm_override()`**(knob_overrides,镜像 revert_override:追加一条 `state="confirmed"` + `provisional=False` + 清 `expires_at` 的记录到 store JSONL)。与 owner 手动确认走不同路径(F2):

| 路径 | 调用者 | 函数 | 写方式 |
|---|---|---|---|
| Owner 手动确认 | owner_actions | `_apply_confirm_provisional_knob_override` | `append_governed_jsonl`(structural write gate) |
| A/B 自动确认 | knob_ab_eval | `confirm_override()` (新) | 直接 `path.open("a")` 追加 JSONL(镜像 revert_override) |

`confirm_override()` 也要在 `write_surface_check.py` 加分类条目 `"knob_override_store"`(F1,照 register/revert 两个已有条目)。

**新模块 `knob_ab_eval.py`**(no_agent lane,在 cognitive_loop 中于 override_sweep 之前跑):
```
对每个 active、有 ab_metric、收紧方向(override_value > prior_value)的 override:
  分层算 size==prior 层 vs size>=override 层的 owner 确认率
  够 margin 且 够观测 → confirm_override()(auto-confirm)
  反向够 margin → revert_override(reason="ab_reverted")
  否则 → 不动, 落回 override_sweep 的 TTL/owner 路径
```

⚠ **数据溯源路径(F3):三表 join,非单表查询。**
1. `candidate_triage.jsonl` 或 `crystallized.jsonl` — 晋升记录带 `cluster_size` 字段(C6)
2. `owner_actions.jsonl` — owner 裁决,用 `target_id` 关联到 triage/crystallized 记录的 id
3. knob_ab_eval 执行:按 `target_id` 把 owner 裁决 join 回晋升记录 → 按 `cluster_size` 分组 → 算每层确认率

**`cluster_size` 不直接在 owner_action 记录里**,需要 join。knob_ab_eval 负责这条 join 链,不期望 owner_action 带 cluster_size。

override_sweep **不改 confirm 逻辑**(它没有也不该有);A/B 的 confirm/revert 由 knob_ab_eval 主动调。**抽 C1 纯逻辑**:把 `_cluster_and_promote` 的"哪些簇够大晋升"判定抽成纯 helper `promotable_clusters(candidates, threshold)`,供 live promote 与(若将来重跑型钮需要)A/B 共用——但 min_cluster_size 的 A/B 走 §2.1 分层,**当前不需要重跑**。

### 2.5 节奏 + 观测口径(M2,明确)
- **节奏**:每 cognitive_loop tick 跑一次 knob_ab_eval(override_sweep 之前)。
- **观测累积**:窗口内所有相关晋升的 owner 裁决,累积非抽样。
- **min_observations 口径** = **owner 裁决数**(确认+拒绝),不是簇数也不是候选数。每层需 >= AB_MIN_OBS 条裁决才判。

---

## 3. meta 保护:边界即 store(M1 修正)
**修正前版说法**:AB_MARGIN / AB_MIN_OBS / ab_metric 选择是模块常量,**不在 OVERRIDABLE_KNOBS** → `register_override` 物理拒绝任何不在字典的 knob,`self_evolution._knob_tune_proposals` 只遍历 OVERRIDABLE_KNOBS、**永远看不到它们**。所以保护它们的是**边界即 store**(比 meta 标记更强、更物理),不是 meta-skip。

**A/B 参数第一刀默认值(F5):**
```python
# plugins/modules/governance/knob_ab_eval.py (模块常量, 不在 OVERRIDABLE_KNOBS)
AB_MARGIN = 0.15    # 确认率差 >= 15pp 才判(保守起步)
AB_MIN_OBS = 5      # 每层至少 5 条 owner 裁决(确认+拒绝)才判
```
两个值都是保守起步——宁可退 owner 也不冒进。后续 owner 观察 A/B 行为后可手动调(直接改代码,不进 knob store)。

- 测试钉死:这些常量不在 OVERRIDABLE_KNOBS;构造"提议改 AB_MARGIN"→ register_override 抛错。
- meta 标记仍保留给"将来登记进来、但不可自调"的钮(_knob_tune_proposals:508 的 `if spec.get("meta"): continue` 已就绪)。

---

## 4. C 连接(诚实修正)
min_cluster_size 用分层真实结果,**不重跑 shadow → 这个钮不消费 shadow 格**,所以**这一刀不接 C**。前版"一箭双雕接 C"对这个钮是错的。**并行 shadow 重跑那条路(才能把 shadow 变 A/B 台、接 C)适用于"重跑才能评"的钮**(如评分权重 X 下重算打分),等加那类钮再上。诚实分清:不同钮用不同 A/B 工具,min_cluster_size 的最佳工具是分层、不是重跑。

---

## 5. 复用 vs 新建(修正)
| 件 | 复用 | 新建 |
|---|---|---|
| store/resolve_knob/register/边界/kill/可逆 | V3 | A1 加 2 钮(sentinel 接) |
| revert_override | knob_overrides | — |
| owner confirm 逻辑 | owner_actions confirm | **confirm_override()(镜像,供 A/B 自动确认)** |
| owner 裁决数据 | owner_action 记录 | **按 cluster_size 分组读取** |
| 晋升记录 | _cluster_and_promote | **+cluster_size 字段** |
| A/B 评估 | — | **knob_ab_eval.py(分层真数据)** |
| 聚类判定纯化 | _cluster_and_promote | **抽 promotable_clusters 纯 helper** |
| 静默失败修复 | override_sweep build_error_record | **修 provisional_sweep 两处(C4)** |

---

## 6. 分期
| Phase | 内容 |
|---|---|
| **A1** | 加 2 钮 sentinel 接(C2/C3)+ 修 provisional_sweep 静默 except(C4)+ cluster_size 字段(C6) |
| **A2a** | knob_ab_eval 分层真数据评估(纯)+ confirm_override(C5) |
| **A2b** | knob_ab_eval 接 cognitive_loop(override_sweep 前)+ 收紧 auto-confirm/revert / 放松+不清晰退 owner |

---

## 7. 测试断言(RED-first)
```
A1:
A1.1  max_speak_per_hour override 生效(sentinel call-time, 非默认参数冻死)
A1.2  max_provisional override 生效
A1.3  C4: provisional_sweep 异常走 error record 非静默 pass

A2 分层 A/B(核心, 真数据):
A2.1  晋升记录带 cluster_size(C6)
A2.2  收紧 X→X+1: size==X 层确认率明显低于保留层 → auto-confirm(真数据)
A2.3  收紧: size==X 层确认率明显高 → auto-revert
A2.4  放松 X→X-1: 无 delta 数据 → 一律退 owner(不自动)
A2.5  观测不足(每层 < AB_MIN_OBS 裁决)→ 退 owner, 不冒进
A2.6  confirm_override 清 expires_at + 标 confirmed(镜像 owner confirm)

meta 边界即 store(关键):
A2.7  AB_MARGIN 不在 OVERRIDABLE_KNOBS; 提议改它 → register_override 抛错
A2.8  self_evolution._knob_tune_proposals 永不产出 A/B 参数提议

可逆兜底:
A2.9  A/B confirm/revert 后 override 记录留存; kill switch 仍全回退
```

---

## 8. 诚实限制
- **真数据 A/B 只对收紧方向**;放松方向无 delta 数据 → 退 owner(§2.2)。
- **先证在 min_cluster_size 一个钮**;A1 两钮先 owner-confirm。
- **不接 C**(这个钮不重跑 shadow);C 连接留给重跑型钮。
- A/B 仍非放开自治:够清晰才拍板,不清晰/放松/观测不足退 owner;kill 仍总闸;一切可逆。

---

## 9. 验收(Claude 复验)
- **反证 A2.2/A2.3**:构造 size==X 层确认率高/低 → 看 auto-confirm/revert 真触发、用真 owner 数据。
- **不对称对(A2.4)**:放松方向一律退 owner,不冒进。
- **观测不足保守(A2.5)**:裁决不够不拍板。
- **meta 边界即 store(A2.7 关键)**:系统提议改自己的 A/B 判准 → register_override 物理拒绝。系统不能把自己的 A/B 放水。
- **C4 修了**:provisional_sweep 无静默失败。
- **可逆+kill 仍在(A2.9)**。

## 10. 一句话
修订后用**按簇大小分层的真实 owner 结果**做 A/B(收紧方向 delta 恰好审过、有真裁决),**去掉了"带估计"的 hand-wave**;放松方向无数据 → 诚实退 owner。决策落在新 knob_ab_eval(override_sweep 前),新增 confirm_override 镜像。meta 保护是边界即 store(比标记更强):A/B 判准不在自可调集,系统物理上改不了自己的 A/B。这个钮不重跑 shadow 故不接 C——C 留给重跑型钮。顺手修了 provisional_sweep 两处静默失败。
