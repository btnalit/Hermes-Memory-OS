# Hermes-Memory-OS 稳定化检查清单

> **重建说明（2026-07-18）**：原清单文件随本地检出目录被意外清空而丢失（连同未推送的本地提交
> `48da55a`）。本文件为重建版，并自此从 gitignore 中移出、纳入 git 跟踪，随仓库推送到
> GitHub，避免再次丢失。BD 之前的历史周期只保留压缩摘要（详情已不可恢复）；自 BD 起恢复
> 完整记录格式。
>
> 使用规则（与 CLAUDE.md 一致）：**每次任务开工前**至少读最新一节与 Section W；**每次任务
> 完成后**（全量测试通过、准备提交时）新增一节记录：修了什么、根因、反事实覆盖、测试数量
> 变化、最终测试数，并在文末"一句话"追加提交区间与单行摘要。这是 definition of done 的一部分。

---

## Section W — 经验教训（每次改动都适用的五条修复规则）

提炼自一次"三个补丁通过代码评审却引入五个回归"的周期，无一例外地适用于所有改动：

1. **改函数前先读完整个函数。** 只看 diff hunk 不够——必须理解所有分支、所有默认参数路径、
   所有 return 点。
2. **grep 测试文件里你要改的符号。** 字符串常量、函数签名、路径模式——改了什么就 grep 什么。
   monkeypatch 旧字符串的测试就是你刚刚改坏的测试。
3. **每个修复配一个反事实测试。** 问"如果我的修复不存在会坏什么"，把答案写成测试；该测试
   必须在无修复时 FAIL、有修复时 PASS（用 revert→fail→restore→pass 实际验证）。
4. **默认参数不许是陷阱。** 若 `param=None` 会在任何路径上导致数据丢失、崩溃或静默跳过，
   它就不是可选参数而是地雷——给安全默认值或去掉默认。
5. **全项目 grep 同类缺陷模式。** 在一个文件发现缺陷 → grep 所有文件找同一模式 → 修掉或
   记录每一处。

补充纪律（同样强制）：

- **顺着调用链修完整。** 被指出"X 不是 Y"时，不要只把 X 改成 Y——追每个 X 的消费者，
  同一调用路径上是否有同类缺陷。
- **推送前自检四步。** 枚举子项 → 跑反事实 → 反向评审自己的 diff → 跑全量测试
  （绝不允许只跑自己新增/修改的测试就推送）。
- **测试只证明"做了的是对的"，不证明"没漏做"。** 防遗漏的唯一手段是上面的自检清单。

---

## 历史周期压缩摘要（原始详情随 2026-07-18 目录清空丢失）

- **A–AB 稳定化阶段（28 项）与 AC–AH 收尾（6 项）**：2026-07-17 前完成，含 Windows 本机
  全量测试兼容（fcntl/dir-fsync 阻断修复，见提交 `2c01ba8`）。当时基线 2561→2570 passed。
- **BB.6-2**：trigger_class 触发出处门控——`run_v3_seed_evidence_cycle` 依据
  `MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID` 环境变量（防伪造，非参数）为 daily_record 打
  `natural_cron`/`manual` 标记；30 天 activation gate 只认 natural_cron；
  `legacy_unmarked_day_count` 单列老行。镜像 `exposure_rollup.py` Fix 3 的同语义门控。
- **BC.1**：living_memory_promotion 生产远端账本采集缺口——`read_permanent_promotion_ledger_counts`
  迁移到 `plugins/memory/memory_os/permanent_promotion.py`（远端主机可达层）；新增
  `living_memory_promotion_probe()` SSH 探针；`summarize_living_memory_promotion` 增加
  `ledger_counts`/`ledger_collection_error` 参数与 `ledger_state_collection_status` 字段；
  WARN 代码 `living_memory_promotion_ledger_state_collection_failed` 注册 `fail_if_production`。
- **BC.2**：v3_seed_evidence activation gate 记录来源鉴别（与 BB.6-2 同一族修复的收口）。
- 以上工作最终推送为 GitHub 提交 `abcce26`（fix(memory-os): close two remote/manual-trigger
  monitoring blind spots）。
- **丢失周期**：BC 代码评审（对 `abcce26` 的 diff 评审）发现 15 项问题（P0×3、P1×4、P2×3、
  P3×5），三项 P0 曾修复为本地提交 `48da55a`（含 4 个反事实测试，2574 passed），随目录清空
  丢失，已在下面 BD 节重做。

---

## BD — BC 代码评审 P0 三项重做（2026-07-18，提交 `074be97`）

基于全新克隆（`abcce26`）重做丢失的三项 P0 修复。修复语义沿用丢失周期已定的决策
（记录于 claude-mem observations 2455–2486）。

### BD.1 monitor WARN 在生产升级循环之后追加（BC 评审 #1）

- **根因**：`classify_snapshot` 中 Living Memory V2-0 不变量块（含
  `living_memory_promotion_ledger_state_collection_failed` WARN 追加）位于
  clean-host/production WARN 分类升级循环**之后**，导致该代码虽注册了
  `fail_if_production`，生产远端账本采集失败却永远只 WARN 不 FAIL——生产契约是死代码。
- **修复**：将分类升级循环整体移到所有 WARN 追加之后、status 计算之前（现位于函数末尾）。
  此位置保证之后任何新增 WARN 都自动被升级循环消费，比逐个挪 WARN 更稳健。
- **同模式清扫（规则 5）**：同块内 `living_memory_promotion_unavailable` 有完全相同的顺序
  缺陷，随整块移动一并修复。该代码未注册分类表，clean-host 下 malformed section 现在会正确
  产生 `clean_host_warn_unclassified` FAIL（与所有 `*_unavailable` 兄弟码一致；真实采集路径
  不可达此分支）。
- **反事实**：revert monitor → 2 个新测试 FAIL；restore → 该文件 188 passed。
- **新测试**：`tests/scripts/test_memory_os_3_200_monitor.py` ——
  `test_production_living_memory_ledger_collection_failure_escalates_to_fail`（生产 FAIL 断言）、
  `test_clean_host_living_memory_ledger_collection_failure_stays_classified_warn`
  （clean-host 保持 expected_clean_host 分类）。

### BD.2 digest 去重不看 trigger_class（BC 评审 #2）

- **根因**：`run_v3_seed_evidence_cycle` 的同日 rebuild_digest 命中即 skip。手动先跑某天 D，
  cron 再跑同输入被 skip → 该天永远没有 natural_cron 行，永久无法计入 30 天 activation
  gate——一次无害手动操作打断 streak。
- **修复**：digest 命中时计算 `natural_provenance_upgrade`（本次为 natural_cron 且旧行非
  natural_cron，含 legacy 无字段行）——为真则不 skip、走正常写入路径；manual→manual、
  cron→cron、cron→manual 仍 skip（手动永不覆盖/降级已记录的 natural 出处）。
- **反事实**：仅 revert 此 hunk → `test_manual_then_natural_cron_same_day_upgrades_provenance_instead_of_skipping`
  FAIL（skipped 断言）；restore → PASS。
- **新测试**：`tests/plugins/memory/test_memory_os_v3_seed_evidence.py` ——
  上述升级测试 + `test_natural_cron_then_manual_same_day_still_skips`（锁定反向仍 skip）。

### BD.3 natural 过滤在 last-writer-wins 归并之后（BC 评审 #3，与 BD.2 同根）

- **根因**：`build_v3_seed_evidence_snapshot` 先对**全部行**做 last-writer-wins 得
  `latest_by_date`，再过滤出 natural_cron 行。迟到的 manual/backfill 行（更新的 created_at）
  在归并中顶掉 natural 行后被过滤掉 → 已计入 streak 的 natural 天消失，已达成的
  `activation_evidence_ready` 静默回退，关闭 wandering 准入。
- **修复**：`natural_by_date` 改为仅对 `trigger_class == "natural_cron"` 行做**独立**
  last-writer-wins；`latest_by_date`（全行）继续供给 `invalid_day_count`、
  `latest_natural_date`、`legacy_unmarked_day_count`（有意保留全行口径）。
- **反事实**：仅 revert 此 hunk → `test_snapshot_later_manual_row_cannot_evict_natural_day`
  与 `test_snapshot_30_day_natural_streak_survives_interleaved_manual_rows` 双 FAIL；
  restore → 全过。
- **同模式检查（规则 5）**：`exposure_rollup.py`（BB.6-2 引用的兄弟实现）按日直接对
  natural_cron 行求和，无 latest-row 归并、无 digest skip，两个缺陷均不存在。

### BD 验证结论

- 全量测试：**2579 passed, 8 skipped**（基线 2573 + 6 新测试）。
- 静态门：import cycle pass / write surface `unclassified_count=0` / static hygiene pass /
  public checkout probe `--strict` PASS / `git diff --check` 干净。
- 证据级别：`local_pass`（本机 pytest）。生产远端（hermes-media live monitor）验证未做，
  部署后需跑 `memory_os_3_200_monitor.py --host hermes-media --monitor-profile live`。

---

## 待办 — BC 代码评审遗留项（P1–P3，尚未重做）

### P1 — 静默假阴性 / 监控崩溃

| # | 位置 | 问题 | 修法 |
|---|------|------|------|
| 4 | `permanent_promotion.py:2049` | 裸 `except` 吞异常，`stale_open_evaluation_status` 全仓库无消费者：stale-open 评估失败时计数停在 0、状态仍 "collected"，真实 stale 提案零信号漏报（违反 No Silent Failures） | `classify_snapshot` 消费该状态（unavailable → WARN，复用 BD.1 修好的升级通道）；except 记 bounded error_record |
| 5 | `memory_os_3_200_monitor.py:1235` | 本地分支读账本无 try/except（read_text 在 try 外）：损坏/非 UTF-8 文件让整个本地 monitor 崩溃，而远端同场景只 WARN | 本地调用包 try/except，降级为 ledger_collection_error，与远端对称 |
| 6 | `permanent_promotion.py:2062` | `int(latest_recovery.get(...))` 缺 `or 0`（邻行有）：历史 result_summary 缺 success_count 键 → `int(None)` TypeError → 经 #5 的无保护路径崩掉 monitor [PLAUSIBLE] | 补 `or 0`，与 #5 一起修 |
| 7 | `v3_wandering.py:202` | 种子数据选取只看 valid 不看 trigger_class:门开后手动行仍供给真实 wandering 数据——BC.2 要关的风险在门下一层敞开 | 行过滤加 `trigger_class == "natural_cron"`（与快照门控同语义） |

### P2 — 潜伏性缺陷

| # | 位置 | 问题 | 修法 |
|---|------|------|------|
| 8 | `v3_seed_evidence.py:308` | 计数不对称：valid 的 manual 天从所有桶消失（实测复现）；manual 跑今天会推进 latest_natural_date 掩盖 cron 停摆 | 加 manual_day_count 或统一口径 |
| 9 | `memory_os_3_200_monitor.py:1234` | 三参数全 None 的隐式第四路径：无 status 键、硬零占位（Section W 规则 4 默认参数陷阱；现有测试已走此路径） | 末分支改无条件 else 置 unavailable |
| 10 | `v3_seed_evidence.py:274` | created_at 字符串比较在微秒省略边界上字典序≠时间序，可能选错"最新修订"→ 错的 trigger_class 进门控 | 改用时间戳解析比较 |

### P3 — 清理类

| # | 位置 | 问题 |
|---|------|------|
| 11 | `permanent_promotion.py:1952` | 搬入函数重复实现同模块已有的 parse_timestamp/content_hash/jsonl_io.read_jsonl（三处一行级替换，顺带修掉 _events 静默丢坏行） |
| 12 | `v3_seed_evidence.py:61` | trigger_class 判定与 `exposure_rollup.py:114` 逐字重复，抽共享 helper（如 `execution_gate.resolve_trigger_class()`）防漂移重开伪造风险 |
| 13 | `permanent_promotion.py:2039` | stale-open 循环 O(proposals × crystallized 文件数) 全量扫描，每周期含 SSH 端；先建 id→record 索引 |
| 14 | `memory_os_3_200_monitor.py:4384` | 第三份手抄的子探针消费块 + 错误字段名第三种变体；抽 `_consume_remote_probe()` 并统一 error_code 命名 |
| 15 | `monitor_dashboard_snapshot.py:1003` | dashboard 取物理最后一行不看 trigger_class，与门控后计数显示矛盾（纯展示层） |

注：行号以 `074be97` 时点为准，后续修复会漂移；按符号/语义定位为准。

---

## 一句话

- （BD 之前的条目随原文件丢失，区间散见上方历史摘要；最后已推送提交为 `abcce26`。）
- `abcce26..074be97`：BC 评审 P0 三项重做——monitor WARN 分类循环移至函数末尾恢复
  fail_if_production 生产契约；digest 去重加 provenance upgrade（manual/legacy→cron 不再
  skip）；natural_by_date 改独立 last-writer-wins 防迟到 manual 行顶掉 natural 天。
  2579 passed / 8 skipped，静态门全过。
