# Hermes Cron 任务归类合并方案（2026-07-30）

> 状态：**已实施**（2026-07-31）。实施记录见稳定化清单 BS 节。
> 结论：**19 个 Hermes cron job → 8 个**（4 个分组 tick + 4 个 owner 面向作业），
> 治理粒度（lane / ExecutionGate envelope）保持 21 条不变。
>
> 落地与本提案的差异：
> - §5 R1 实算后确认受影响的是 **4 条 lane**（不止 working_cleanup 与
>   hindsight_advisory_digest，还有 candidate_aggregation 与 fact_judge），已按 lane
>   `due_interval_minutes` 取窗口并保留原 schedule 回退路径。
> - §6 R2 落地时发现 `classify_hermes_cron_jobs` 有**三份**拷贝（memory 适配器、seam 适配器、
>   monitor 内嵌 fallback），生产读的是 seam 那份，三份已全部同步。
> - 另外发现两处仍在直接创建 per-lane job（`install_memory_os.sh`、`deploy_l3_probe.py`），
>   会与 group tick 双跑，已分别删除与改为 fail-closed。
> - §7 的 `execution_gate_index.json` 无裁剪缺陷本次一并修复（`prune_sidecar_index`），
>   未另开工单。

---

## 1. 现状（以代码为准，非文档）

`plugins/memory/memory_os/cron_registry.py` 注册 **21** 条 spec；
`scripts/memory_os_owner_cron_onboarding.py:55` 排除 2 条
（`module_cadence_report` 永久排除、`clearance_cycle` 延后激活），
因此 active-closure 实际创建 **19 个 Hermes cron job**。

> ⚠️ `CLAUDE.md` 写的 "active-closure（10 jobs）" 是**过期文档**，与代码不符。
> 本方案落地时须一并修正。

每个 job 的结构完全一致：

```
Hermes cron job
  └─ scripts/memory_os_cron_<key>_gate.py      ← 5 行 shim
       └─ memory_os_execution_gate_runner.py --registry-key <key>
            ├─ 写 permit 记录   (execution_gate_envelopes.jsonl + index.json)
            ├─ subprocess.run(helper)          ← 真正干活
            └─ 写 completion 记录 (同上两个文件)
```

**关键观察：19 个 job 共用同一个入口** `memory_os_execution_gate_runner.py`，
差异仅在 `--registry-key`。所以"合并"不需要重写任何 helper，
只需要在 runner 之上加一层按组遍历的 tick。

### 1.1 全量作业清单

| # | key | schedule | 次/天 | deliver | agent | 语义类别 |
|---|---|---|---|---|---|---|
| 1 | `event_stats_refresh` | `7,22,37,52 * * * *` | 96 | local | no | 派生视图 |
| 2 | `index_sync` | `*/30 * * * *` | 48 | local | no | 派生视图 |
| 3 | `state_overlay_refresh` | `17,47 * * * *` | 48 | local | no | 派生视图 |
| 4 | `entity_index_refresh` | `25,55 * * * *` | 48 | local | no | 派生视图 |
| 5 | `proposal_followups_opsgate` | `*/30 * * * *` | 48 | local | no | 治理队列 |
| 6 | `hindsight_health_probe` | `33 * * * *` | 24 | local | no | 探针 |
| 7 | `fact_judge` | `0 */4 * * *` | 6 | local | no | 判断 |
| 8 | `candidate_aggregation` | `0 */6 * * *` | 4 | local | no | 候选流水线 |
| 9 | `l3_probe_verification` | `0 */6 * * *` | 4 | local | no | 探针 |
| 10 | `v3_wandering` | `17 */6 * * *` | 4 | local | no | V3 自然通道 |
| 11 | `exposure_rollup` | `5 0 * * *` | 1 | local | no | 日界汇总 |
| 12 | `v3_seed_evidence` | `15 0 * * *` | 1 | local | no | 日界证据 |
| 13 | `v3_journal_sweep` | `30 3 * * *` | 1 | local | no | 维护 |
| 14 | `working_cleanup` | `0 3 * * 0` | 0.14 | local | no | 保留期清理 |
| 15 | `hindsight_advisory_digest` | `20 2 * * 0` | 0.14 | local | no | 周报 |
| 16 | `owner_review_digest` | `0 9 * * *` | 1 | **owner** | **yes** | owner 面向 |
| 17 | `memory_sources_feedback_request` | `30 10 * * *` | 1 | **owner** | **yes** | owner 面向 |
| 18 | `expression_feedback_request` | `0 5 * * 0` | 0.14 | **owner** | **yes** | owner 面向 |
| 19 | `full_monitor_refresh` | `30 2 * * *` | 1 | **owner** | no | 重量级探针 |
| — | `module_cadence_report` | （full profile 专用） | — | local | no | 报表 |
| — | `clearance_cycle` | `*/10 * * * *`（延后） | — | local | no | 治理队列 |

**合计 336.4 次/天**，每次派生 2 个 Python 进程（runner + helper）。

---

## 2. 为什么必须合并：不是审美问题，是已存在的故障面

### 2.1 同分钟并发争锁（实测）

按上表 schedule 展开一天的触发时刻：

```
00:00 → 5 个 job 同时触发：proposal_followups_opsgate, candidate_aggregation,
                            fact_judge, index_sync, l3_probe_verification
12:00 → 同上 5 个
06:00 / 18:00 → 4 个
（周日 03:00 另有 working_cleanup 加入）
```

这 5 个进程会同时对**同一个文件**做"独占加锁 → 全量读 → 全量重写 → fsync"：

- `execution_gate_envelopes.jsonl`（追加，尚可）
- `execution_gate_index.json`（**全量 JSON 重写**，`memory_os_execution_gate_runner.py:330`）

锁超时 `SIDECAR_LOCK_TIMEOUT_SECONDS = 15.0`（同文件 :33）。
一旦超时抛 `ExecutionGateInfrastructureError("sidecar_lock_timeout")` → runner 返回 **3**，
该 lane 当次执行**不产生 completion 记录** → 被 monitor 记为
`helper_completion_missing`。

这是一条**随数据量增长必然恶化**的路径：index.json 每条 envelope 一个 entry、
**无任何裁剪逻辑**（见 §7），当前约 336 entry/天。合并后同分钟并发降为 1，
争锁面直接消失。

### 2.2 作业数量本身的成本

19 条 job 意味着 19 份 schedule 要在 Hermes 侧维护、19 个 5 行 shim 脚本要部署、
onboarding 要逐个 upsert、monitor 要逐个分类。新增一条 lane 就要新增一个 job，
这个线性增长是本次要打断的。

---

## 3. 设计核心：把"治理身份"和"调度面"拆成两张表

当前 `MemoryOSCronSpec` 把两件事**揉在一个 dataclass** 里：

| 字段 | 属于 | 合并后 |
|---|---|---|
| `key` / `lane_id` / `raw_script` / `helper_kind` / `requires_boundary_report` | **治理身份**（ExecutionGate permit、boundary、risk_class） | **保持 1:1，21 条不变** |
| `name` / `wrapper_script` / `schedule_arg` / `deliver_role` / `prompt_ref` / `no_agent` | **Hermes 调度面** | **合并，21 → 8** |

**这是整个方案的支点**：只合并调度面，治理粒度一条不动。
ExecutionGate 每 lane 仍写自己的 permit + completion，
`lane_id` / `risk_class` / `boundary` 语义零变化，
下游（monitor、dashboard、StructuralWriteGate 的 scope 校验）几乎不受影响。

### 3.1 建议的数据结构

```python
@dataclass(frozen=True)
class MemoryOSCronLaneSpec:          # 治理身份，21 条
    key: str
    raw_script: str
    lane_id: str
    helper_kind: str
    requires_boundary_report: bool
    # ── 新增 ──
    group_key: str                   # 归属分组
    due_policy: str                  # "interval" | "calendar"
    due_interval_minutes: int        # 有效节奏；**monitor 新鲜度窗口的唯一来源**
    calendar_anchor: str             # due_policy=="calendar" 时的 "HH:MM"（可选 dow）
    timeout_seconds: int             # 单 member 超时上限

@dataclass(frozen=True)
class MemoryOSCronGroupSpec:         # Hermes 调度面，8 条
    key: str
    name: str                        # 真正创建的 Hermes job 名
    wrapper_script: str
    schedule_arg: str
    deliver_role: str
    prompt_ref: str
    no_agent: bool
    member_keys: tuple[str, ...]
```

### 3.2 向后兼容：`memory_os_cron_specs()` 保留为派生视图

保留现有函数签名，让每条 lane 的 `name` / `wrapper_script` / `schedule_arg`
**从其 group 派生**。这样：

- `classify_hermes_cron_jobs()` 里的 `specs_by_name`（`hermes_cron_adapter.py:89`）
  自然按 name 去重 → `memory_os_owned_expected_count` = **8**，符合实际；
- `_execution_gate_helper_completion_summary()` 的 `specs_by_lane`
  （`memory_os_3_200_monitor.py:7173`）仍有 **21** 个 entry，
  每个指向自己所属 group 的 job name，并新增携带 `due_interval_minutes`。

注册快照 schema 升到 `memory-os.cron_registry.v1`，同时输出 `specs`（派生，兼容）
与 `groups`（新增）两个数组。

---

## 4. 分组方案

### 4.1 本地 lane → 4 个 tick

| Group | Hermes job | schedule | 成员（due 策略） |
|---|---|---|---|
| **G1 派生视图** | `memory-os-tick-derived` | `2,17,32,47 * * * *` | `event_stats_refresh`(15m)、`index_sync`(30m)、`state_overlay_refresh`(30m)、`entity_index_refresh`(30m) |
| **G2 治理队列** | `memory-os-tick-governance` | `7,37 * * * *` | `proposal_followups_opsgate`(30m)、`clearance_cycle`(10m，**仍延后**) |
| **G3 判断与探针** | `memory-os-tick-evidence` | `12 * * * *` | `hindsight_health_probe`(1h)、`fact_judge`(4h)、`candidate_aggregation`(6h)、`l3_probe_verification`(6h)、`v3_wandering`(6h) |
| **G4 日界与维护** | `memory-os-tick-daily` | `5 0 * * *` | `exposure_rollup`(**calendar** 00:05)、`v3_seed_evidence`(**calendar** 00:05)、`v3_journal_sweep`(24h)、`working_cleanup`(7d)、`hindsight_advisory_digest`(7d) |

分组依据是**语义类别**（可解释、失败影响面同质），
group 的 cron 周期取组内最细成员的节奏，
组内各成员用 `due_policy` 还原自己的有效节奏。

> G2 若维持 `clearance_cycle` 延后状态，`*/30` 即可；
> 将来激活 `clearance_cycle` 时把 G2 调到 `*/10`，
> `proposal_followups_opsgate` 靠 `due_interval_minutes=30` 自动隔次跳过。
> **激活 clearance_cycle 从"新建一个 job"变成"翻一个 lane 开关"**——
> 这正是拆表带来的收益。

### 4.2 due 策略：为什么需要两种

只有 elapsed（`interval`）一种是不够的。已逐个核对 helper 语义：

| lane | 语义 | 结论 |
|---|---|---|
| `exposure_rollup` | `run_exposure_rollup_cycle` docstring：*"Reads memory_sources records since the last **watermark**. Idempotent: same window re-run produces zero-side-effect skip."* | **水位线驱动、幂等**，漂移无害。仍锚定 00:05 只为保持既有观感 |
| `v3_seed_evidence` | 产出 `natural_date` 日记录，暴露 `valid_day_count` / `consecutive_valid_day_count`，CLI 有 `--target-date` | **按日分区**。漏一天或跨日重复会污染"连续有效天数"→ **必须 calendar 锚定** |
| `working_cleanup` | `age_days > RETENTION_DAYS`，纯年龄判定 | elapsed 即可 |
| `hindsight_advisory_digest` | 只写 `generated_at` / `expires_at`，无日期分区 | elapsed 即可 |
| `v3_journal_sweep` | **未核实**：仅 grep 了 thin-wrapper 脚本（零命中），未读底层模块。`exposure_rollup` 正是"脚本是壳、语义在 `plugins/` 模块里"的先例 | 暂按 elapsed，**P1 实施时须确认底层模块是否按日分区** |

所以 `due_policy` 必须支持 `calendar`，但**实际只有 `v3_seed_evidence` 强制需要**。
其余成员用 `interval` —— 好处是**宕机后自动补跑**（下一 tick 发现已过期就执行），
而当前的固定时刻 cron 会直接漏掉这一次。

### 4.3 owner 面向作业：保持 1:1，不合并

`owner_review_digest` / `memory_sources_feedback_request` /
`expression_feedback_request` 三条 `no_agent=False`，
各自有独立的 deliver 渠道与 agent prompt（onboarding.py:86-99 三段不同的中文 prompt），
输出是**直接发给 owner 的一条消息**。合并会把多条 owner 消息揉成一条、
prompt 互相污染——这是 owner 体验边界，不能为了减 job 数牺牲。

`full_monitor_refresh` 虽是 `no_agent=True`，但目标运行时长 ≤180s，
是全量 monitor。放进任何 tick 都会让该 tick 长期占用并阻塞同组成员，**保持独立**。

### 4.4 收益

| 指标 | 现状 | 合并后 |
|---|---|---|
| Hermes cron job 数 | **19** | **8** |
| shim 脚本数 | 19 | 8 |
| cron 触发次数/天 | 336 | **172** |
| helper 实际执行次数/天 | 336 | 336（**不减**，工作量不变） |
| 同分钟最大并发进程 | **5** | **3**（每小时 :00，09:00 为 4） |
| index.json 重写次数/天 | 672 | **672（不减）** —— 合并不改变每 lane 两次落盘；真正的收益是并发争锁消失。无界增长是另一个缺陷，见 §7 |
| 新增一条 lane 的代价 | 新建 job + shim + schedule 参数 | 往 group 里加一行 |

---

## 5. 阻断性前置条件（不做就会打崩生产 monitor）

### R1（阻断）新鲜度窗口必须改为按 lane 取

`scripts/memory_os_3_200_monitor.py:7546`

```python
def _helper_completion_freshness_window(schedule):
    interval = _cron_schedule_interval(str(schedule or ""))
    return max(interval * 2 + grace, minimum)     # minimum = 12h
```

两处调用（:7469、:7481）传入的都是 `_cron_schedule_display(cron_job)`，
即**该 lane 所属 cron job 的 schedule**。

按本方案的分组实算（已用上述公式逐条验证），**4 条 lane 的窗口会塌缩**：

| lane | 现窗口 | 合并后窗口 | 后果 |
|---|---|---|---|
| `working_cleanup`（7d） | 342h | **54h** | **永久 stale** |
| `hindsight_advisory_digest`（7d） | 342h | **54h** | **永久 stale** |
| `candidate_aggregation`（6h） | 18h | **12h** | 略晚即误报 |
| `fact_judge`（4h） | 14h | **12h** | 略晚即误报 |

前两条是必然常亮的生产 WARN；后两条是边界收窄后的偶发误报。
（`index_sync` 12h→12h 不变，因为已被 12h 下限兜住。）

**必须改为**：窗口取自 lane 自己的 `due_interval_minutes`
（calendar 策略则按其周期），而非 group 的 cron 表达式。
这不是可选清理，是合并的前置条件。

### R2（阻断）19 个旧 job 名必须显式分类

合并后 `memory_os_cron_specs()` 的 `name` 变成 group 名，
于是 `known_specs_by_name`（`hermes_cron_adapter.py:90`）**不再认识**
`memory-os-index-sync` 这类旧名字。已升级主机上残留的旧 job 会掉进
`name.startswith("memory-os-")` 分支 → `unregistered_like`
→ monitor 报 `execution_gate_memory_os_cron_unregistered_like_job`（FAIL）。

这与 `cron_registry.py:11-32` 已经踩过的坑**完全同型**（当时是 sannai
community 脚本掉进 `external_unmanaged`）。
**必须新增 `LEGACY_PER_LANE_CRON_JOB_NAMES` 常量**，把这 19 个旧 name
归入 `known_optional` / `retired_legacy` 桶，并写明退役理由。

---

## 6. 其余风险与对策

| # | 风险 | 对策 |
|---|---|---|
| **R3** | tick 执行时间可能超过 tick 周期，导致重叠双跑 | group 级**非阻塞**文件锁；抢不到锁则以显式 `skipped_overlap` 状态退出 0。**不允许静默 pass**（No Silent Failures），须落一条可被 monitor 看见的计数 |
| **R4** | `subprocess.run`（runner:114）**当前无 timeout**。1:1 时一个 hang 只拖垮一条 lane，合并后拖垮整组 | 每 member 强制 `timeout_seconds`；超时记 completion（`execution_status="timeout"`）后继续下一个成员。**这是合并的硬性要求，不是附赠优化** |
| **R5** | 单 lane 停用能力丢失。当前 owner 停一个 Hermes job = 停一条 lane；monitor 靠 `cron_job.enabled is False`（:7446）识别 | 新增 lane 级停用状态文件，tick runner 与 monitor 同时读取；monitor 的 `disabled` 分类改为「group job disabled **或** lane 在停用名单」 |
| **R6** | `trigger_surface` 若被改写会破坏 natural_cron 溯源 | **已核实**：`resolve_trigger_class()`（`execution_gate.py:25-39`）只读环境变量 `MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID`，与 job 数量无关。tick runner 逐 member 设置该变量即可保持 `natural_cron`。**permit 的 `trigger_surface` 必须保持字面量 `"hermes_cron"`**，不得"顺手清理"成 `hermes_cron_group` |
| **R7** | 组内某成员失败中断整组 | 逐 member `try/except` + 独立 completion 记录；组退出码做聚合，单成员非零不终止后续成员 |

---

## 7. 顺带发现的相关缺陷（建议单独修，不并入本次范围）

**`execution_gate_index.json` 无任何裁剪机制。**

`memory_os_execution_gate_runner.py:330 _update_sidecar_index()` 每次
permit / completion 都做一次「加锁 → 全量读 → 全量重写 → fsync」，
而全项目 grep 不到该文件的 prune / compact / retain 逻辑
（`plugins/memory/memory_os/execution_gate.py` 内零命中）。

entry 数按每 envelope 一条**无上限增长**：当前 336 条/天 ≈ 12 万条/年，
重写成本 O(N)，与 §2.1 的 15 秒锁超时叠加。

合并**不降低**该文件的写入次数（每 lane 仍是 permit + completion 两次），
只消除同分钟并发争锁；**无界增长完全不受影响**。
建议独立开一个「envelope index 保留期 + 压实」的修复。

---

## 8. 落地分期

| 阶段 | 内容 | 可独立验证 |
|---|---|---|
| **P0** | 仅做 R1（新鲜度按 lane）+ R2（旧 job 名分类常量）。此时行为不变，纯属加固 | 全量 pytest；反事实测试：把某 lane 的 due 设为 7d、job schedule 设为日频，无 P0 时该 lane 被判 stale |
| **P1** | 注册表拆表（lane spec / group spec）、快照 schema v1、`memory_os_cron_specs()` 派生兼容视图 | `test_memory_os_cron_registry.py`、`test_memory_os_hermes_cron_adapter.py` |
| **P2** | 新增 `scripts/memory_os_cron_group_runner.py`（复用 `run_registry_key()`）+ 4 个 group shim；实现 due 判定、组锁(R3)、超时(R4)、失败隔离(R7)、批量落盘 | `test_memory_os_execution_gate_runner.py` + 新增 group runner 测试 |
| **P3** | onboarding 改为按 group upsert；旧 19 个 per-lane job 走 `_pause_known_optional_cron_jobs` **暂停而非删除** | `test_memory_os_owner_cron_onboarding.py` |
| **P4** | 部署 3.200，跑 full monitor 要求 `live_monitor_pass` | `memory_os_3_200_monitor.py --monitor-profile live` |

### 回滚

P3 只**暂停**旧 job，不删除。回滚 = 重新启用 19 个旧 job + 停用 4 个 group job，
helper 脚本与 lane 注册表全程未动，回滚后行为与今天完全一致。

### 受影响测试面（12 个文件）

`tests/plugins/memory/`：`test_memory_os_cron_registry.py`、
`test_memory_os_hermes_cron_adapter.py`、`test_memory_os_legacy_right_brain_retirement.py`、
`test_memory_os_audit_arbitration.py`、`test_memory_os_entity_graph.py`

`tests/scripts/`：`test_memory_os_owner_cron_onboarding.py`（cron 相关断言最密集）、
`test_memory_os_3_200_monitor.py`、`test_memory_os_cron_adapter_probe.py`、
`test_memory_os_execution_gate_runner.py`、`test_memory_os_monitor_dashboard_snapshot.py`、
`test_memory_os_plugin_install.py`、`test_memory_os_state_overlay_refresh.py`

近期已把硬编码 job 集合改成 registry 派生断言，多数应能自动适配；
`test_memory_os_owner_cron_onboarding.py` 需要按 group 重写预期。

### 文档同步

`CLAUDE.md` 的 "Cron Profile — 默认 active-closure（10 jobs）" 与实际的 19 条不符，
落地时须一并更正为分组后的 8 条并列出分组表。

---

## 9. 一句话

把 `MemoryOSCronSpec` 拆成「lane 治理身份（21 条不变）」与「group 调度面（8 条）」两张表，
用一个复用 `run_registry_key()` 的 tick runner 按组遍历、按 lane 开 envelope，
**Hermes job 19 → 8、同分钟并发 5 → 3**（见下方「实测修正」）；
前提是先做掉 R1（monitor 新鲜度改按 lane 取）与 R2（旧 job 名显式分类），
否则合并当天生产 monitor 就会 WARN 常亮 + FAIL。


---

## 10. 实测修正（2026-07-31，3.200 部署后）

**本文与实施提交里「同分钟并发 5 → 1」的说法是错的，实际是 5 → 3。**

四个 tick 的 cron 表达式在整点重叠：`tick-derived`(`*/15`)、`tick-governance`(`*/30`)、
`tick-evidence`(`0 * * * *`) 都命中 `:00`，因此**每小时整点仍有 3 个 group runner 同时启动**
（09:00 加上 owner-review-digest 是 4 个）。3.200 部署日志独立佐证了这一点：
三个 tick 均在 `2026-07-31 20:00:56 CST` 由真实 scheduler 同秒触发。

### 影响评估

比合并前有改善但**未消除**：

- 并发进程 5 → 3（09:00 为 4）
- 更关键的是 `execution_gate_index.json` 现在有 `prune_sidecar_index()` 上限 2000 条，
  单次重写成本从「随 envelope 无上限增长」变成有界 O(2000)，
  这才是 §2.1 那条 15 秒锁超时路径真正被拆掉的原因——不是靠并发降为 1。

### 后续修复（**已实施**，2026-07-31）

把三个 tick 的分钟错开，彻底消除整点碰撞，且不改变任何 lane 的有效节奏
（各 lane 节奏由 `due_interval_minutes` 决定，与 tick 落在哪一分钟无关）：

| Group | 原 | 现 |
|---|---|---|
| `tick-derived` | `*/15 * * * *` | `2,17,32,47 * * * *` |
| `tick-governance` | `*/30 * * * *` | `7,37 * * * *` |
| `tick-evidence` | `0 * * * *` | `12 * * * *` |

`tick-daily`(`5 0 * * *`) 与四个 owner 作业未动。

**实测结果：同分钟最大并发 3 → 1，触发次数保持 172/天不变。**
至此 §4.4 表格里最初写的「并发 1」才真正成立。

改动面：`MEMORY_OS_CRON_GROUPS.default_schedule`、onboarding 参数默认值、
`install_memory_os_plugin.py` 传参、公开文档四张表。测试断言已改为**从注册表派生**
（不再写字面 schedule），并新增两条不变量：

- `test_no_two_group_jobs_start_in_the_same_minute` —— 任意两个 group job 不得同分钟启动。
- `test_every_tick_fires_at_least_as_often_as_its_fastest_installed_lane` ——
  错开只许动分钟、不许动频率；比较对象是 active-closure **实际安装**的 lane，
  因此 `clearance_cycle`(10min，延后中) 不会误伤 `tick-governance`(30min)，
  但一旦有人激活它却没加快该 tick，这条会立刻失败。
