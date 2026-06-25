# 记忆质量 · 源头治理完整规约(第一性版)

> 第一性原则:**会话记录(event)全保留 ≠ 每条都成为永久记忆。** 碎片不是下游产生的,是源头默认"每轮对话都够格当记忆"造出来的。**在源头掐断,后面整条链不需要补救。**
> 核心动作:`candidate_allowed` 默认从 `True`(每轮必记)翻转为"基于内容判断"——记录与记忆分离。
> 纪律:不新建模块、不破 fact_judge"只判断"契约、不在热路径调 LLM(INV-5)、复用现成标记/机制、治理(可逆/审计/owner)贯穿。
> 全部经六段完整调用链核实(HEAD ef648e2)。
> 
> **审查修订 (2026-06-25):** 对比代码库 HEAD ef648e2 和 3.200 环境，发现 8 项关切 (F1-F8)，均已纳入下文。关键修正: `_TRANSIENT_MARKERS` 当前仅覆盖问候/确认，需扩展中文过程模式才实现规格声称的"碎片大头在此掐断"; recurrence 有两条 bump 路径 (自动 near-duplicate + owner 手动 renew); S1 信号模型已收敛为被动信任(时间驱动); 完整 TTL 写入链已追踪。

---

## 0. 完整调用链(六段核实,作为规约地基)

```
① sync_turn(__init__.py)              每轮对话 → event(kind=conversation_turn, summary=User|Assistant截断拼接)
                                       → _enqueue          【记录:全记,留痕/审计/session_search ✓ 不动】
② heartbeat 主循环(runtime.py:90)    for event in pending: process_event(event)
③ process_event(inner_drive.py:48)   decision = classify_event_for_inner_drive(event)  ← 纯函数, 仅 event, 无 store/LLM
   ├─ if working_kind → working.add_item                  【working memory:独立分支, 不受 candidate 影响】
   └─ if candidate_allowed → candidate(kind=moment, body="Remembered from event X")
   ★ classify: conversation_turn → candidate_allowed = default=True   ← 碎片源头在此
④ append_candidate_queue(runtime.py:98)   → candidates.jsonl
⑤ run_fact_judge_lane(fact_judge.py:249)  离线 LLM lane, 读 candidate → judge durable → 写 verdict
                                            "Does NOT mutate candidates — only writes verdicts"
⑥ aggregation(cluster + resolver_gate)    → write_approved_record → owner_approved.md(provisional)
                                            → owner confirm(唯一晋升)→ permanent
```

**核实确认的五个事实**:
1. ① event 全记,留痕完整 —— 会话记录该全,**不动**。
2. ③ working 与 candidate 是**两条独立分支** —— 关 candidate 不伤近期记忆。
3. ③ 碎片源头 = `conversation_turn → candidate_allowed=default=True`,且 classify 是**纯函数(无 store/无 LLM)** —— 源头只能做确定性判断。
4. ⑤ fact_judge 是**纯判断器(有 LLM, 离线 lane, 不 mutate)**。
5. ③ 源头门与 ⑤ fact_judge 是**漏斗两个不同阶段, 不重叠**(前者管"进不进队列", 后者管"进了判 durable")。

**根因一句话**:你设计的 fact_judge / resolver / owner 多道门槛之所以"没用",是因为碎片在源头③被 `default=True` 全放进漏斗,下游门槛在**抗洪**而非**精筛**。源头默认翻转,碎片大头不进漏斗,门槛回归本职。

---

## 1. 设计:三层分离 + 两道门(确定性源头 / 语义 fact_judge)

### 层一 · 记录(event)—— 不动
- 对话轮继续全部写入 event(①),留痕/审计/session_search 完整。
- **"会话记录"是全的**,这是历史与可追溯,不该删。

### 层二 · 源头粗门(③ classify, 确定性)—— 翻转默认 + 确定性碎片识别 ★核心
**位置**:`classify_event_for_inner_drive`,`conversation_turn` 分支(inner_drive.py)。

**改动**:`candidate_allowed` 从 `_candidate_allowed(candidate_explicit, default=True)` 改为:
```python
if kind == "conversation_turn":
    # 显式指定优先(保留现有 candidate_explicit 入口)
    if isinstance(candidate_explicit, bool):
        allowed = candidate_explicit
    else:
        # 默认翻转:确定性碎片识别,明显碎片不进候选队列
        allowed = not _is_obvious_fragment(event.summary)   # 默认不再恒 True
    return InnerDriveEventDecision(
        working_kind="lingering",          # working 照常, 近期记忆不丢
        candidate_allowed=allowed,
        skip_reason="" if allowed else "source_gate:obvious_fragment",  # 复用现有 skip_reason
        ...
    )
```

**`_is_obvious_fragment(summary)` —— 确定性, 复用 + 扩展 fact_judge 同源标记**:

**当前 `_TRANSIENT_MARKERS`(fact_judge.py:45-49) 仅 15 个 token,全为基本问候/确认:**
```python
"谢谢", "收到", "hello", "thanks", "open", "show me",
"天气", "今天", "hi", "bye", "再见", "好的",
"ok", "明白了", "知道了", "不用谢"
```
**不足以覆盖规格声称的过程性中文碎片("更新部署看看"、"验证结果如何"等)。** 需要扩展。

**扩展策略(两层, 从窄到宽)**:
1. **层 A — 精确子串匹配(复用+扩展, `_TRANSIENT_MARKERS` 同源):** 基础问候/确认标记追加到 `_TRANSIENT_MARKERS` 中(保持 fact_judge 受益), 约 30-50 个中文过程短标记。
2. **层 B — 句式模式匹配(仅 `_is_obvious_fragment` 使用, 不放入 fact_judge 提示词):** 简短过程/确认句式的正则匹配, 如:
   - 纯信息请求: `"看看.*(状态|情况|部署|日志)"`、`"查一下.*"`
   - 过程确认: `"试试|感觉一下|感受一下|体验一下"`、`"好不好|行不行|对不对"`
   - 纯导航/指令: `"打开.*(页面|文件|项目)"`、`"帮我.*(查|找|搜索)"`
   - 单字/极短输入: 含实体但无实质语义, 如 `"嗯"`、`"好"`、`"继续"`
   - 英文简短指令: `"show"`、`"check"`、`"run"`、`"build"`

**命中逻辑**: 层 A 精确标记命中 OR 层 B 句式命中 → `_is_obvious_fragment=True`。
**只做减法(挡明显碎片), 不做语义提炼**(那是纯函数做不到的, 交层三)。
**fail-safe**: 判不准就放行(allowed=True)→ 交给层三 fact_judge 兜底, 源头宁可漏挡不可错杀(不丢可能有价值的)。
**冷启动**: 层 A/B 初始模式从 3.200 现有 `owner_approved.md` 的 moment 体量观测中反向提取,上线后以 skip_reason audit 日志驱动迭代。

**`_turn_summary` 格式影响**(F3):
`_turn_summary(user_content, assistant_content)` 输出格式为 `"User: <clip180> | Assistant: <clip180>"`。`_is_obvious_fragment` 必须对**用户部分**和**助手部分**分别检测,因为:
- 一条微不足道的用户消息嵌入在实质性助手回复旁边(用户部分碎片) → 不应因助手部分有实质内容而放过
- 一条实质性用户消息 + 一条纯确认助手消息(助手部分碎片) → 不应因用户部分有实质而放过
- 实现: 正则提取 `User: (.*?) \| Assistant: (.*)` 两组, 分别对 user_segment / assistant_segment 运行检测, **任一**碎片 → 整体判 fragment → 不进候选

**为什么放这里**:最早、最便宜的拦截点;确定性正是纯函数能力范围;碎片大头(过程性片段)在此被掐断, 根本不进 candidates.jsonl → 不进 fact_judge / aggregation / 不结晶 / 不堆积。

### 层三 · 语义细判(⑤ fact_judge, LLM)—— 隐性碎片兜底, 不动契约
- 看似内容、实则无知识的对话(确定性挡不住的),由 fact_judge 现有 LLM 判 transient → 不结晶。
- **fact_judge 保持"只判断不 mutate"** —— 不新增职责、不产 distilled_body、不改 body。它继续只产 verdict。
- 与层二**不重叠**:层二挡"明显碎片"(确定性, 便宜, 大头), 层三挡"隐性碎片"(语义, LLM, 少数)。漏斗两级, 各管一类。

---

## 2. 沉淀:自动晋升(修正 recurrence 对 moment 覆盖不足)

**S0 为什么 recurrence 对 moment 覆盖不足**(F2 修正):
- recurrence 通过**两条路径**递增:
  1. `_match_existing_provisional`(candidate_aggregation.py:844) → FTS5 近重复命中 → `_cluster_and_promote` bump recurrence。moment body 来自 `_turn_summary`(对话摘要, 各不同),FTS5 近重复几乎永不命中 → **自动 recurrence 对 moment 恒 0**。
  2. `bump_recurrence_and_renew`(crystallized.py:472) → **owner 显式 renew 操作**(`owner_actions.py` 中的 `renew_provisional` 动作)。此路径**手动有效**但非自动。
- 结论: 自动 recurrence 对 moment 是空设计(路径 1 恒 0), 手动 recurrence 可行(路径 2 但需 owner 介入)。S1 需替代信号, 不依赖 recurrence 自动递增。

**S1 改用被动信任驱动(时间信号, 收敛为单一模型)**(F5):
- 选择**选项 1 — 被动信任**: 同一 provisional 被 owner 多轮未否决 + 存活超 `auto_promote_min_age_days` 天 → 达标。
- **不采纳选项 2(独立印证/recurrence)** — recurrence 对 moment 恒 0(见 S0),无法作为信号。
- 信号源: `list_provisional_records()`(crystallized.py:565) → 遍历 active provisional, 检查:
  - `confirmed_at` 或 `approved_at` 距今 ≥ `auto_promote_min_age_days`(默认 7 天)
  - `canonical_state` 非 `provisional_rejected`(owner 否决过的不晋升)
- 达标 → `confirm_provisional_record`(现成, provisional=False 清 expires_at) → permanent。
- knob `auto_promote_enabled`(lane_switch, 默认 True)、`auto_promote_min_age_days`(bounds [3, 30], 默认 7, ab_metric="promotion_rate")。
- **治理不破**: 可逆(invalidate)、审计(provisional_record_confirmed 事件)、owner 可拦/可撤。把"默认不晋升"改成"稳定够了默认晋升, owner 可拦" —— 符合"机器守卫优于人工审批"。

**S2 moment 短 TTL**(确定能做, 立刻见效, F4 追踪完整写入链):
- **TTL 设置点**: `CrystallizedMemoryService.write_approved_record()`(crystallized.py:63),在 `if decision.provisional:` 分支(第 97 行)。
- **完整写入链**: ⑥ `_cluster_and_promote`(candidate_aggregation.py) 构造 `ApprovalDecision(..., provisional=True, expires_at=<TTL>)` → ⑥ `resolver_gate` → ⑥ `write_approved_record` → `owner_approved.md`。
- **实施**: 在 `write_approved_record` 中, 当 `candidate.kind == "moment"` 且 `decision.provisional` 时,**覆写** `expires_at` 使用 knob `moment_provisional_ttl_days`(默认 3 天), 非 moment 类型使用常规 TTL(默认 7 天或其他)。
- 现有 `provisional_sweep`(provisional_sweep.py:58-113) 处理 active provisional 的 TTL 过期,**不区分类型** — moment 更短的 TTL 自然生效, 不需要修改 sweep 逻辑。
- knob `moment_provisional_ttl_days`(bounds [1, 14], 默认 3, ab_metric="moment_ttl_days")。

---

## 3. 修复后的记忆流

```
对话轮 → event(全记, 留痕 ✓)
   ↓ ③ 源头粗门(确定性): 明显碎片? → 是 → 只留 working, 不进候选【碎片大头在此掐断】
                                  → 否 → 进 candidates.jsonl
   ↓ ⑤ fact_judge(语义): 隐性碎片/非durable? → 是 → 不结晶
                                            → 否 → 进 aggregation
   ↓ ⑥ aggregation + resolver → provisional(短TTL, S2)
   ↓ owner 多轮未否决 + 存活够久(S1) → 自动晋升 permanent(可逆/审计/owner可拦)
→ 记忆库 = 真正值得记的, permanent 自然长, provisional 不堆积 → recall 不碎片
```

**会话记录(event)全的, 记忆(candidate→结晶)是选的。** 两道门各挡确定性/语义碎片, 漏斗回归精筛。

---

## 4. 测试断言(RED-first, 核心反证须攻防验证会咬)

**F6 — 测试基础设施**: `classify_event_for_inner_drive` 当前无独立测试覆盖(CodeGraph: ⚠️ no covering tests found)。实施 P0: 先创建 `tests/plugins/memory/test_memory_os_inner_drive.py`, 覆盖 `classify_event_for_inner_drive` 的现有 7 种 event kind 分支, 然后引入 `_is_obvious_fragment` 的 G.1-G.5 测试。确保新碎片逻辑有测试地基, 不是架在无覆盖代码上。**

```
源头门(层二, 确定性):
G.0  classify_event_for_inner_drive 基本契约: conversation_turn→candidate_allowed=True(不破坏现有行为) 【P0 基础测试】
G.1  明显碎片("更新部署看看")→ candidate_allowed=False → 不进 candidates.jsonl, working 仍有【核心】
G.2  含知识对话("我决定用PostgreSQL")→ candidate_allowed=True → 进队列
G.3  candidate_explicit=True 显式指定 → 覆盖默认(保留现有入口)
G.4  判不准的对话 → fail-safe 放行(allowed=True), 不错杀
G.5  working 分支不受影响:碎片仍进 working memory(近期记忆不丢)
G.6  _is_obvious_fragment 对 User | Assistant 分别检测, 任一碎片 → 整体判 fragment 【F3】

语义门(层三, fact_judge 不变):
J.1  fact_judge 仍只产 verdict, 不 mutate candidate(契约不破)
J.2  隐性碎片(无 transient marker 但 LLM 判无知识)→ durable=False → 不结晶

沉淀(S):
S.1  provisional owner 多轮未否决 + 存活超 N 天 → 自动晋升 permanent【核心】
S.2  owner 否决过 → 不晋升(可拦)
S.3  auto_promote_enabled=False → 不晋升(knob 可逆)

反证(攻防, 移除逻辑→必须 FAIL):
G.X  移除源头门(_is_obvious_fragment 恒返回 False)→ 碎片重进 candidates.jsonl → G.1 必 FAIL
S.X  移除自动晋升 → permanent 不增长 → S.1 必 FAIL
治理:
T.1  自动晋升的 permanent 仍可 invalidate(可逆)
T.2  源头门决策(skip_reason)/ 晋升 / 降级全程 audit 可追溯
```
**G.1 + S.1 必须攻防验证(破坏逻辑→测试真红), 不重蹈"假反证"。**

## 5. 复用 vs 新建(贯彻"复用优于新建")
| 件 | 复用现成 | 新建 |
|---|---|---|
| 源头门挂载点 | `classify_event_for_inner_drive` + `skip_reason`(现有) | `_is_obvious_fragment` 判断 + 层 B 句式模式 |
| 碎片标记 | `_TRANSIENT_MARKERS`(fact_judge 现有, 同源, 层 A 扩展) | 层 B 正则句式(仅 `_is_obvious_fragment` 内部) |
| 显式覆盖入口 | `candidate_explicit`(现有) | — |
| working 分支 | `working.add_item`(现有, 不动) | — |
| 语义判断 | fact_judge LLM(现有, 不动契约) | — |
| 晋升动作 | `confirm_provisional_record`(现有) | 被动信任触发逻辑(time-based) |
| provisional TTL | `provisional_sweep.run_once()`(现有, 不改) | `write_approved_record` 中 per-kind TTL 覆写 |
| 配置 | knob lane_switch 机制(现有) | 3 个新 knob(边界见下) |

**F8 — 新 knob 边界定义**:
| Knob | 类型 | 默认 | 边界 | ab_metric |
|---|---|---|---|---|
| `auto_promote_enabled` | lane_switch | True | [True, False] | — |
| `auto_promote_min_age_days` | threshold | 7 | [3, 30] | promotion_rate |
| `moment_provisional_ttl_days` | threshold | 3 | [1, 14] | moment_ttl_days |

全部三个 knob 需注册到 `OVERRIDABLE_KNOBS`(knob_overrides.py:21)。`auto_promote_enabled` 为 lane_switch → owner-gated(不可 auto-approve)。两个 threshold knob 可通过 `knob_override_auto_approvable` 检查。均为 `meta=False`、`scope="upper_layer"`。

**F7 — 3.200 环境兼容性确认**:
- `classify_event_for_inner_drive` 通过 `runtime.py` heartbeat → `InnerDriveEngine.process_event()` 在 3.200 的 `active-closure` cron profile 中运行。
- 模块包装器 `InnerDriveRuntimeModule`(enabled=False) 不影响核心 classify 路径 — 这是独立关注点。
- 新增 `_is_obvious_fragment` 是纯函数(仅读 event.summary + 标记表), 不增加 I/O/网络/LLM 调用。
- `skip_reason` 字段已存在于 `InnerDriveEventDecision` dataclass 和 audit append 流程中。
- 3.200 部署: 通过 `active-closure` profile 的 cron runner(hourly heartbeat)进入, 改 `classify_event_for_inner_drive`(纯函数), 零摩擦。

## 6. 分阶段(基于现状, 确定能做的先)

- **阶段〇(测试地基, 零业务变更)**: 创建 `tests/plugins/memory/test_memory_os_inner_drive.py`, 覆盖 `classify_event_for_inner_drive` 现有 7 种 event kind 分支(G.0 基础契约)。确保后续碎片逻辑变更在测试地基上实施, 而非在无覆盖代码上叠加。【F6】
- **阶段一(立刻, 零风险, 确定性)**: 层二源头门(default 翻转 + `_is_obvious_fragment` 层 A 精确标记扩展 + 层 B 句式匹配) + S2 moment 短 TTL(per-kind TTL 覆写在 `write_approved_record`)。**碎片大头当场掐断, provisional 堆积立刻缓解, 不依赖 LLM。** 层 A/B 冷启动模式从 3.200 `owner_approved.md` 现有 moment 观测反向提取, 上线后用 `skip_reason` audit 日志驱动迭代。【F1/F3/F4】
- **阶段二(沉淀)**: S1 被动信任自动晋升(time-based, 从 `list_provisional_records` 读 active provisional, 检查 `approved_at` + `auto_promote_min_age_days`)。**permanent 长起来。** 不依赖 recurrence(对 moment 恒 0, 空设计)。【F2/F5】
- **阶段三(精修, 可选)**: 层三 fact_judge 隐性碎片兜底的 prompt 微调(它本就在判 durable, 只是更明确拒隐性碎片)。层 B 句式模式从 audit 日志持续扩展。S1 多信号增强(如在阶段二时间信号稳定后引入印证信号)。

## 7. 一句话(审查修订版, F1-F8 已纳入)

**第一性根因不变**: 会话记录(event)被默认等同于记忆候选——`conversation_turn → candidate_allowed=default=True`, 每轮对话都自动够格成永久记忆, 碎片是这个源头默认造出来的, 下游 fact_judge/resolver/owner 门槛在抗洪而非精筛。

**修复(经 8 项审查关切修正)**:
- **① 源头(③ classify)翻转默认**: 记录与记忆分离——event 全记不动(留痕/审计), candidate_allowed 改为确定性内容判断。
- **_is_obvious_fragment 两层标记**: 层 A 精确子串(扩展 `_TRANSIENT_MARKERS` 至 30-50+ 中文过程标记, fact_judge 同源受益) + 层 B 句式正则(仅 `_is_obvious_fragment` 内部, 过程/导航/确认/极短输入)。【F1】
- **User/Assistant 分别检测**: 提取 `_turn_summary` 的 User/Assistant 段, 任一碎片 → 整体判 fragment。【F3】
- **fail-safe**: 判不准就放行 → fact_judge 兜底, 源头宁可漏挡不可错杀。
- **② 沉淀改用被动信任**: `confirm_provisional_record` 现成操作 + 存活时间信号(≥ `auto_promote_min_age_days` 天 + 未被 owner 否决 → 自动晋升)。不依赖 recurrence 自动递增(对 moment 恒 0, 空设计)。【F2/F5】
- **③ moment 短 TTL**: `write_approved_record` 中 per-kind TTL 覆写(moment 用 `moment_provisional_ttl_days=3`, 非 moment 用常规 TTL), `provisional_sweep` 现成机制不变。【F4】
- **④ 测试地基先于业务变更**: 先覆盖 `classify_event_for_inner_drive` 的现有契约(G.0), 再引入碎片逻辑。【F6】
- **⑤ 3.200 零摩擦**: `classify_event_for_inner_drive` 纯函数变更, 通过 `active-closure` profile hourly heartbeat 进入, 无 I/O/网络/LLM 新增。【F7】
- **⑥ 新 knob 边界明确**: `auto_promote_enabled`(lane_switch), `auto_promote_min_age_days`([3,30]), `moment_provisional_ttl_days`([1,14])。【F8】

**碎片在源头掐断, 后面整条链不需补救——你设计的门槛回归精筛本职。全程复用现成、不新建模块、不破 fact_judge 契约、不破 INV-5、治理贯穿。**
