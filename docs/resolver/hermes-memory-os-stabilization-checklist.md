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

## BE — BC 代码评审 P1 四项重做（2026-07-18，提交 `e6629a6..efcc202`）

沿用丢失周期已定语义重做四项 P1（BD 之后的遗留项 #4–#7），另含一项全量红灯阻断的
顺带修复（BE.5）。

### BE.1 stale-open 评估失败被裸 except 吞掉且状态无消费者（BC 评审 #4）

- **根因**：`read_permanent_promotion_ledger_counts` 的 stale-open 评估循环包在
  `except Exception: stale_open_evaluation_status = "unavailable"` 里——异常类型被丢弃
  （违反 No Silent Failures），且该状态全仓库无消费者：评估失败时
  `stale_open_proposal_count` 停在 0、section 仍报 `ledger_state_collection_status ==
  "collected"`，真实 stale 提案被静默漏报为"已验证的零"。
- **修复**：except 捕获 `stale_open_evaluation_error_code = type(exc).__name__`（本路径的
  有界错误记录）并随返回 dict 输出；`classify_snapshot` Living Memory 块消费该状态
  （unavailable → WARN `living_memory_stale_open_evaluation_unavailable`，value 为
  error_code）；分类表注册 `expected_clean_host` + `fail_if_production`（复用 BD.1 移到
  函数末尾的升级通道）。
- **第四路径防御（规则 4）**：`summarize_living_memory_promotion` 在
  `ledger_state_collection_status == "collected"` 时对缺失的
  `stale_open_evaluation_status` 键 setdefault 为 "unavailable"（error_code
  `missing_from_collected_counts`）——版本偏斜远端插件返回的旧 counts dict 不可能把
  "缺键"读成"评估健康"。未采集路径不受影响：remote 失败由更强的
  ledger-collection-failed WARN 覆盖；三参数全 None 的硬零占位路径是 P2 #9 既有缺口，
  超出本次范围，本次新字段在该路径与 status 键一同缺失、不新增隐式路径。
- **反事实**：revert 插件 hunk → 插件测试 FAIL（KeyError）；revert monitor 三处 hunk →
  3 个 monitor 测试 FAIL；restore → 全过。
- **新测试**：`tests/plugins/memory/test_memory_os_permanent_promotion.py::`
  `test_ledger_counts_stale_open_evaluation_failure_is_reported_not_swallowed`；
  `tests/scripts/test_memory_os_3_200_monitor.py` ——
  `test_production_living_memory_stale_open_evaluation_unavailable_escalates_to_fail`、
  `test_clean_host_living_memory_stale_open_evaluation_unavailable_stays_classified_warn`、
  `test_summarize_collected_counts_missing_stale_open_evaluation_status_never_reads_ok`
  （镜像 BD.1 的生产/clean-host 测试对）。

### BE.2 本地账本读取无保护，损坏文件崩掉整个本地 monitor（BC 评审 #5）

- **根因**：`summarize_living_memory_promotion` 本地分支直接
  `section.update(read_permanent_promotion_ledger_counts(...))`——损坏/非 UTF-8 账本文件
  的 UnicodeDecodeError 直接崩掉整个本地 monitor run，而远端同场景只降级为 WARN。
- **修复**：本地调用包 try/except，失败置 `ledger_state_collection_status =
  "unavailable"` + `ledger_state_collection_error_code = type(exc).__name__`，与远端
  `ledger_collection_error` 路径完全对称，走 BD.1 的 WARN/升级通道。
- **反事实**：revert → 新测试以 UnicodeDecodeError 崩溃 FAIL；restore → PASS。
- **新测试**：`tests/scripts/test_memory_os_3_200_monitor.py::`
  `test_summarize_living_memory_promotion_local_ledger_read_failure_does_not_crash`
  （真实写入非 UTF-8 字节的账本文件，非 monkeypatch）。

### BE.3 历史 result_summary 行缺键 → int(None) TypeError（BC 评审 #6）

- **根因**：`recovery_success_count` / `recovery_attempt_count` 的
  `int(latest_recovery.get(...))` 在 latest_recovery 为真但键缺失/为 None 的历史
  envelope 行上抛 TypeError（邻行 failure_count 已有 `or 0`），并经 #5 的无保护路径
  崩掉 monitor。
- **修复**：两处 int() 内补 `(... or 0)`，保留原 `if latest_recovery else ...` 回退结构
  （不重复前一会话被 revert 的"删 or 0"方向）。
- **规则 5 清扫**：多行感知扫描全仓 `int(...get(...))` 无回退模式——除本函数两处外，
  monitor 脚本命中均在 `_optional_int`/`_to_int` 安全转换内部；`owner_actions.py`
  rendered_counts（进程内构造恒为 int）与 `inner_drive.py` `_source_cap`（config 形状）
  为同语法不同可达性，不经历史文件行可达 None，记录不改。
- **反事实**：revert → 新测试 TypeError FAIL；restore → PASS。
- **新测试**：`tests/plugins/memory/test_memory_os_permanent_promotion.py::`
  `test_ledger_counts_tolerate_historical_recovery_summary_missing_keys`
  （缺键与 None 值两种历史行形状）。

### BE.4 种子行选取只看 valid 不看 trigger_class（BC 评审 #7）

- **根因**：`collect_seed_inputs_from_store` 行过滤只要求 `valid is True`——activation
  gate 打开后，更晚的 valid 手动行会成为真实 wandering 的种子来源，BC.2 在门上关掉的
  手动注入风险在门下一层敞开。
- **修复**：行过滤加 `item.get("trigger_class") == "natural_cron"`（与快照门控同语义；
  legacy 无字段行同样排除）。
- **与问题陈述的差异**：wandering 两个测试文件现有用例并无写 daily 行的 fixture（全仓库
  仅 v3_seed_evidence 测试写该文件，且不经过 `collect_seed_inputs_from_store`），
  无需按预期更新既有 fixture。
- **同模式检查（规则 5）**：`memory_os_monitor_dashboard_snapshot.py` 取物理最后一行
  不看 trigger_class——即 P3 #15（纯展示层），维持待办不动。
- **反事实**：revert → 两个新测试双 FAIL（seeds 来自 manual 行 / manual-only 仍产出）；
  restore → 全过。
- **新测试**：`tests/plugins/memory/test_memory_os_v3_wandering.py` ——
  `test_collect_seed_inputs_uses_latest_natural_cron_row_not_later_manual_row`、
  `test_collect_seed_inputs_manual_or_legacy_only_rows_yield_no_seed_inputs`。

### BE.5 顺带修复：digest 渲染测试日期腐化（非 P1 范围，全量红灯阻断）

- **现象**：`test_permanent_items_render_with_raw_token_only_in_ephemeral_delivery` 在
  未改动基线上自 2026-07-18T00:00Z 起 FAIL——fixture 固定 `now = 2026-07-10`，而
  `render_owner_review_digest` 内部 `_apply_review_aging` 用真实 `datetime.now()`
  （aging_action_required_days=7）：wall clock 越过 7 天阈值后条目从 action_required
  降级隐藏，token 断言落空。
- **修复**：fixture 改锚定真实时钟（同文件 `test_ppmt_owner_reply_...` 的既有写法），
  条目年龄恒为 0，测试不再随日期腐化。
- **验证**：stash 全部改动后该测试在干净基线上仍 FAIL（证明与本次四项修复无关）；
  修复后单测与全量均过。

### BE 验证结论

- 全量测试：**2579 passed, 0 failed, 13 skipped**。本机当日干净基线（`e6629a6`）实测为
  2570 passed / 1 failed（即 BE.5 日期腐化）/ 13 skipped；本次 +8 新测试 +1 修复。
- 基线口径说明：BD 记录的 2579/8 与本机当日实测不一致，属环境态差异非回归——5 个
  closure-matrix 测试在公共检出（无 gitignored `docs/internal-memory-os/`）下按设计
  skip，另有 3 个环境条件测试本环境未收集。
- 静态门：import cycle pass / write surface `unclassified_count=0` / static hygiene pass /
  public checkout probe `--strict` PASS（exit 0）/ `git diff --check` 干净。
- 证据级别：`local_pass`（本机 pytest）。生产远端（hermes-media live monitor）验证未做，
  部署后需跑 `memory_os_3_200_monitor.py --host hermes-media --monitor-profile live`。

---

## BF — BC 代码评审 P2 三项重做（2026-07-18，提交 `e72f2c1..069484a`）

沿用评审既定修法重做三项 P2（BE 之后的遗留项 #8–#10）。

### BF.1 快照计数不对称：valid 的 manual 天从所有桶消失（BC 评审 #8）

- **根因（a）**：`build_v3_seed_evidence_snapshot` 中一个"全部行都是 manual 且 valid"的日期
  不落任何计数桶——非 natural（正确）、非 invalid（它是 valid）、非 legacy（它有
  trigger_class）——直接从快照消失（BC 评审实测复现）。
- **根因（b）**：`latest_natural_date = max(latest_by_date)`（全行口径）——manual 跑今天会
  推进该字段，新鲜度监控看不到 cron 已停摆。
- **消费者普查（决定统一口径的依据）**：`latest_natural_date` 全仓库仅两个消费者——
  `monitor_dashboard_snapshot.py:1009`（纯展示字符串）与
  `test_memory_os_v3_seed_evidence.py:447`（该 fixture 下新旧口径同值）；
  `memory_os_3_200_monitor.py`、wandering（只读 activation_evidence_ready）、seed CLI helper
  均不消费。无消费者依赖全行口径的正确性 → 采用统一修法。
- **修复**：`latest_natural_date` 改为仅对 `natural_by_date` 求 max（cron 真实新鲜度，
  无 natural 行时为空串）；新增 `latest_recorded_date = max(latest_by_date)` 保留全行
  展示口径；新增 `manual_day_count`：`latest_by_date` 中无 natural_cron 行（不在
  `natural_by_date`）且 latest 行**有** trigger_class 的日期数。与
  `legacy_unmarked_day_count`（保持既有定义：latest 行缺 trigger_class 字段的日期）
  构成无 natural 覆盖日期的完整二分——任何日期不可能同时漏出两桶（源码内注释记录该分区）。
- **反事实**：仅 revert 快照返回口径 → 4 个新测试 FAIL（manual-only 天 KeyError、分区
  KeyError、latest_natural_date 被 manual 推进、空行口径）；restore → 全过。
- **新测试**：`tests/plugins/memory/test_memory_os_v3_seed_evidence.py` ——
  `test_valid_manual_only_day_is_counted_in_manual_day_count`、
  `test_manual_and_legacy_days_partition_without_fallthrough`、
  `test_manual_run_today_does_not_advance_latest_natural_date`、
  `test_snapshot_no_rows_has_empty_freshness_fields`。

### BF.2 monitor 三参数全 None 的隐式第四路径（BC 评审 #9）

- **根因**：`summarize_living_memory_promotion` 的分支链
  `if memory_os_root ... elif ledger_counts ... elif ledger_collection_error ...` 在三参数
  全 None 时静默保留硬零占位且**没有** `ledger_state_collection_status` 键——对任何不
  防御性检查键存在的消费者与"健康的已验证零"不可区分（Section W 规则 4 默认参数陷阱）。
- **修复**：末分支改无条件 `else`：置 `ledger_state_collection_status = "unavailable"` +
  `ledger_state_collection_error_code = "ledger_state_not_supplied"`（新错误码常量，
  docstring 与源码内注释记录语义：标记"section 构建时无任何账本来源"）。
  classify_snapshot 对此发 `living_memory_promotion_ledger_state_collection_failed`
  WARN（生产升级 FAIL）——这是有意的诚实行为。
- **真实调用方核查**：`collect_snapshot` 本地路径恒设 `memory_os_root`，远端路径恒设
  `ledger_counts`（探针 ok）或 `ledger_collection_error`（探针失败/字段缺失）——所有真实
  路径必供三参数之一，新 else 在生产不可达；若可达即是本修复要暴露的静默零缺陷本身。
- **既有 fixture 核查**：仅 2 个测试无账本参数调用该函数
  （`test_summarize_living_memory_promotion_counts_only_registered_target_types`、
  `test_summarize_flags_nonpromotion_living_memory_delivery`），均为 target-type 计数
  单测、不断言账本状态也不喂 classify_snapshot，语义不是"账本已采集且健康"，无需修改；
  classify 侧 fixture 均用 `_living_memory_promotion_section` 字面 dict，不经此函数。
- **反事实**：revert else → 新测试 KeyError FAIL；restore → PASS。
- **新测试**：`tests/scripts/test_memory_os_3_200_monitor.py::`
  `test_summarize_with_no_ledger_source_reports_ledger_state_not_supplied`
  （unavailable + 错误码 + WARN + 生产 FAIL 全链断言）。

### BF.3 created_at 字符串比较在微秒省略边界选错"最新修订"（BC 评审 #10）

- **根因**：快照两处 last-writer-wins 归并（`latest_by_date` 与 BD.3 `natural_by_date`）
  用 `str(created_at) >= str(previous)` 比较——微秒省略时字典序≠时间序
  （`"...T10:00:00.500000Z" < "...T10:00:00Z"`，`.` 排在 `Z` 前，实际却更晚），可能选错
  最新修订 → 错的 trigger_class/valid 进 activation gate。
- **修复**：抽单一 helper `_created_at_is_at_least()` 供**两处**归并共用（防漂移）：
  双方都可解析（复用 `_parse_datetime`）→ 按 datetime `>=` 比较（保留同刻后写者胜的
  tie 语义）；任一解析失败 → 回退原字符串比较（稳定、docstring 记录）。
- **同模式清扫（规则 5）**：全仓 grep created_at/时间戳字符串比较——真正的
  "latest-revision 选取"字符串比较仅此两处。其余命中均为排序/展示且后果有界，不改：
  `owner_actions.py:8915`（已用 `_parse_dt` 解析，安全）；`permanent_promotion.py:349`
  （pending 提案交付顺序，非修订选取，同秒混合格式仅影响顺序不丢数据）；
  `candidate_clusters.py:91/132/182`、`owner_actions.py:531/5229`、
  `owner_channel_adapter.py:236`、`wandering_journal.py:159`、`working.py:92`、
  `deep_reflection.py:647`（展示/迭代/淘汰排序，同秒边界只影响次序）；
  `v3_outlet.py:125`（`max` 作用于已解析 datetime，安全）。
- **反事实**：仅 revert 两处比较为字符串 → 2 个边界测试 FAIL（回退语义测试按设计仍过，
  锁定与旧行为一致）；restore → 全过。
- **新测试**：`tests/plugins/memory/test_memory_os_v3_seed_evidence.py` ——
  `test_snapshot_latest_revision_survives_microsecond_omission_boundary`（全行归并）、
  `test_snapshot_natural_merge_survives_microsecond_omission_boundary`（natural 归并）、
  `test_snapshot_unparseable_created_at_falls_back_to_string_comparison`（回退语义锁定）。

### BF 验证结论

- 全量测试：**2587 passed, 13 skipped**（BE 基线 2579 + 8 新测试）。
- 静态门：import cycle pass / write surface `unclassified_count=0` / static hygiene pass /
  public checkout probe `--strict` PASS / `git diff --check` 干净。
- 证据级别：`local_pass`（本机 pytest）。生产远端（hermes-media live monitor）验证未做，
  部署后需跑 `memory_os_3_200_monitor.py --host hermes-media --monitor-profile live`。
  注意：部署本次 monitor 改动后，任何无账本来源构建的 living_memory_promotion section
  会开始如实报 WARN/FAIL——这是暴露既有静默零，不是回归。

---

## BG — BC 代码评审 P3 五项清理（2026-07-19，提交 `54aea76..eaf718c`）

BC 评审 15 项至此全部完成（P0×3 → BD，P1×4 → BE，P2×3 → BF，P3×5 → 本节）。
本轮采用并行多智能体执行（4 个文件互不重叠的工作包，按复杂度匹配模型），主会话
统一复核 diff、跑全量与静态门。

### BG.1 搬入函数重复实现模块已有 helper；`_events` 静默丢坏行（BC 评审 #11）

- **修复**：`read_permanent_promotion_ledger_counts` 的本地 `_events` 改走
  `jsonl_io.read_jsonl_result`（有界 error records 契约）——坏行/非对象行不再静默消失，
  以新计数字段 `ledger_read_suppressed_error_count` 随返回 dict 输出；整文件读失败
  （`jsonl_read_error`）保留原抛出语义，调用方（本地 summarize / SSH 探针）仍整体降级
  unavailable+error_code 而非把硬零当已采集。本地 `_parse_ts` 删除、3 处调用点改用模块级
  `parse_timestamp`（语义逐字节等价，多出的 astimezone 为 no-op）；内联 sha256 改用模块级
  `content_hash()`（同定义，模块内 8+ 处已用）。
- **反事实**：临时删除计数字段 → 新测试 KeyError FAIL；恢复 → 68/68 过。
- **新测试**：`tests/plugins/memory/test_memory_os_permanent_promotion.py::`
  `test_ledger_counts_malformed_lines_are_suppressed_not_fatal`（坏行+非对象行+有效行混合）。

### BG.2 trigger_class 判定逐字重复（BC 评审 #12）

- **修复**：`execution_gate.resolve_trigger_class()` 共享 helper（防伪造理由收进
  docstring：只认 OS 环境变量 `MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID`，不认调用参数；
  运行时读取，monkeypatch 与逐进程门控均正常）；`v3_seed_evidence.py` 与
  `exposure_rollup.py` 两处改用之。
- **新测试**：`tests/plugins/memory/test_memory_os_execution_gate.py` ——
  设值/未设/空串三态各一（锁空串按 falsy 读 manual 的既有边界），外加同对象断言
  `v3_seed_evidence.resolve_trigger_class is exposure_rollup.resolve_trigger_class is
  execution_gate.resolve_trigger_class`（未来若重新引入本地拷贝即 FAIL，防漂移）。

### BG.3 stale-open 循环 O(proposals × crystallized 文件数)（BC 评审 #13）

- **修复**：循环前一次性建 `record_index: dict[id, CrystallizedRecord]`，精确复刻
  `find_record` 语义（sorted glob 文件序 + 文件内文档序 + 同 id 首见胜 + 空 id 短路
  None）；每提案的 provisional/active/content-hash 检查保持在循环体内；索引构建在既有
  try 块内，异常仍走 unavailable+error_code。
- **等价性**：既有 stale-open 测试全数不改通过；新增
  `test_ledger_counts_stale_open_loop_uses_index_for_multiple_proposals`
  （双开放提案：一 fresh 一 stale → count==1，status ok）。

### BG.4 子探针消费块手抄重复与错误字段命名变体（BC 评审 #14）

- **实况澄清（与评审条目的差异）**：全文件与历史（abcce26/074be97）核查均只有 **2** 份
  真正的探针消费块（v2 / lm）；评审所称"第三份"实为错误形状的第三个产生点——本地
  `if not host:` 分支从捕获异常构造同形输出（无 ok/error_code 可消费，结构上不可走
  helper），维持原样。lm 侧 `ledger_state_collection_error_code` 即"命名第三变体"。
- **修复**：抽 `_consume_remote_probe(raw, probe_key) -> (payload | None, error_code)`，
  两份消费块统一改写；各 section 输出字段名与形状零漂移（既有 193 个 monitor 测试
  不改全过）。
- **有意行为改进（已标记评审）**：探针值为 dict 但 ok 非 True 且无可用 error_code 的
  （生产不可达、原先无测试）路径，旧代码静默产出 error_code=None，新 helper 统一回退
  `"remote_probe_field_missing"`——符合 No Silent Failures，新测试锁定。
- **新测试**：helper 五态直测（ok 载荷 / ok=False 带码 / 键缺失 / 非 dict / dict 无码）
  + `test_collect_snapshot_remote_probe_field_present_but_not_dict_is_not_silent`。

### BG.5 dashboard latest 行不看 trigger_class（BC 评审 #15）

- **修复**：`_v3_seed_evidence_snapshot` 的 `latest` 改取**最后一条 natural_cron 行**
  （reversed 首匹配，无则空 dict）——latest_* 展示字段与旁列的门控计数口径一致，
  manual/backfill/legacy 行不再进入展示；防御性强转全保留。
- **反事实**：revert → natural 后跟 manual 行的测试 FAIL（错取 manual 行）；restore → 过。
- **新测试**：`tests/scripts/test_memory_os_monitor_dashboard_snapshot.py` ——
  `test_v3_seed_evidence_latest_fields_use_only_natural_cron_rows`、
  `test_v3_seed_evidence_latest_fields_empty_when_no_natural_cron_rows`。

### BG 验证结论

- 全量测试：**2601 passed, 13 skipped**（BF 基线 2587 + 14 新测试：BG.1×1 + BG.2×4 +
  BG.3×1 + BG.4×6 + BG.5×2）。主会话亲跑复核，非仅子智能体自述。
- 静态门：import cycle pass / write surface `unclassified_count=0` / static hygiene pass /
  public checkout probe `--strict` PASS / `git diff --check` 干净。
- 证据级别：`local_pass`。生产远端 live monitor 验证仍待部署后执行。

---

## P0–P2 观测/看板闭环收尾（2026-07-19，提交 `520f1be`）

- **背景**：`5128316` 起草的优化路线图 v1 标出 P0–P2 三档缺口——Recall Facade shadow 未真正
  output-neutral、State Overlay 同摘要跨会话/候选重复、Dashboard `fullMonitor` 新鲜度阈值与实际
  每日 02:30 刷新节奏脱节、Lane Status 未把 state-overlay-refresh/entity-index-refresh/
  full-monitor-refresh 计入核心契约。实施计划见 `docs/plans/2026-07-19-p0-p2-cognitive-partner-closure.md`
  （其中 Task 1 MemorySources 配置开关、Task 3 调度器清理、Task 6 Review Agenda canary 为生产
  配置/cron 状态操作，本仓库无对应源码 diff，不在本节验证范围内——本节只覆盖有源码变更、
  可用测试锁定的部分）。

- **P0/P2 · Recall Facade shadow 并非真正 output-neutral**：`_build_prefetch_sections()` 原逻辑在
  非 `apply_canary` 模式下仍会用 STATE_OVERLAY/INDEXED_FTS 子集结果调用 `facade.format_context()`，
  非空时把结果追加进**实时** prefetch 的 "Recall Facade (unified)" section——shadow 模式因此并未
  保持输出中立，会悄悄改变实时输出字节。修复：只有 `apply_canary` 才格式化并追加实时 section；
  其余模式下 `facade.retrieve()` 仍执行（写入 metadata-only Recall Plan 观测），但绝不进入实时
  prefetch。
  - **反事实**：还原旧分支 → `test_shadow_facade_observes_without_adding_live_prefetch_section` FAIL
    （shadow 输出与 baseline 不再字节相等）；恢复 → 该测试与新增的
    `test_context_router_apply_still_runs_shadow_facade_without_changing_live_bytes`、
    `test_apply_canary_facade_may_add_live_prefetch_section` 三个测试全过。

- **P1 · State Overlay 跨会话/候选重复开放线索**：`build_state_overlay()` 逐会话/候选追加
  `open_threads` 时不去重，同一 `foreground_summary`（或候选 summary）在多个 last_session 之间、
  或与 `candidates.jsonl` 重叠时会重复入表。修复：加 `open_thread_keys` casefold 集合，同键只保留
  首次遇到的一条（会话已按新→旧排列，"首次遇到"即最新一条）。
  - **反事实**：删除去重集合 → 新增的
    `test_build_overlay_deduplicates_identical_open_threads_across_sessions`、
    `test_build_overlay_deduplicates_session_and_candidate_open_thread` 两个测试 FAIL（重复条目）；
    恢复 → 过。

- **P1 · Dashboard `fullMonitor` 新鲜度阈值与真实节奏脱节**：新增
  `scripts/memory_os_full_monitor_refresh.py`——用临时文件 + `_validated_payload()` 校验
  classification 后原子 `os.replace()` 发布 monitor 快照，保留最近 `keep_artifacts` 份；
  monitor 子进程返回码 0/2 都视为成功（2 = 治理观测门 FAIL，是有效证据而非执行失败），其余
  返回码才 raise。`cron_registry.py` 注册 `full_monitor_refresh` 规格（`no_agent=True`，
  `deliver_role=owner`）；`memory_os_monitor_dashboard_snapshot.py` 的
  `FULL_MONITOR_STALE_SECONDS` 从写死 3600 改为 `30 * 3600`——对齐每日 02:30 刷新加调度抖动余量，
  1 小时阈值会让仪表盘一天里大半时间显示假 stale。
  - **反事实**：`test_full_monitor_daily_artifact_stays_fresh_within_cadence_grace`（25h 新鲜）
    在旧 3600s 阈值下会 FAIL；`test_full_monitor_stale_artifact_flags_stale` 改为 31h 过期用例
    验证阈值仍能正确触发。`test_refresh_publishes_valid_fail_classification_without_alerting`、
    `test_refresh_fails_loudly_when_monitor_does_not_create_valid_artifact` 锁定新脚本的
    fail-open/fail-loud 边界；`test_full_monitor_refresh_is_registered_as_read_only_self_wrapper`
    锁定 cron spec 形状。

- **P2 · Lane Status 缺三项 cron 且 no_agent 误判为 agent 工作**：`CORE_MEMORY_OS_CRON` 补入
  state-overlay-refresh/entity-index-refresh/full-monitor-refresh，`OPTIONAL_MEMORY_OS_CRON` 收纳
  已停用功能对应的 expression-feedback-request（继续算核心会造成假 WARN）。`_cron_job_snapshot()`
  原先只要 `agent_value is None` 就用 `deliver not in {"local","none",""}` 推断，`no_agent=True` 但
  走 discord/telegram 投递的自包含 wrapper 会被误判成"agent 工作"——修复为先查 `no_agent` 字段。
  - **反事实**：新增的 `test_no_agent_origin_job_is_not_misclassified_as_agent_work`、
    `test_state_overlay_and_entity_index_are_part_of_core_monitor_contract`、
    `test_expression_feedback_is_optional_when_expression_is_disabled` 三个测试锁定新契约；
    既有 `test_dashboard_snapshot_maps_read_only_evidence_without_writing_reports` 的核心/可选
    计数断言从 7/1 同步改为 9/2（既有测试更新，非新增）。

### P0–P2 验证结论

- 全量测试：**2613 passed, 13 skipped**（BG 基线 2601 + 12 新测试：Recall shadow×3、State
  Overlay 去重×2、full_monitor_refresh 脚本×2、cron 注册×1、Dashboard Lane Status×4；skipped
  数不变）。本会话亲跑复核（Windows 本地检出），非仅子智能体自述。
- 静态门：import cycle pass（146 modules / 0 cycles）/ write surface `unclassified_count=0`
  （146/146 已分类）/ static hygiene pass（closure matrix、compileall、diff_check、
  host boundary、provider-agnostic、public checkout probe 均 pass）/ `git diff --check` 干净。
- 证据级别：`local_pass`。下方 BH 节记录的 fresh-clone 隔离检出点数字
  （`2620 passed / 6 skipped / 4 warnings`）属独立证据类别（mount-isolated 全新检出环境），
  与本节本地数字口径不同，互不矛盾。生产侧 Task 1/3/6（MemorySources 配置开关、cron 状态、
  Review Agenda canary）为生产操作，未随本次源码验证覆盖。

---

## BH — 优化路线图升级为 v2（2026-07-19，文档变更）

- **背景**：原 `hermes-memory-os-optimization-roadmap.md` 仍停留在 BC 修复收尾时点，基线为
  `eaf718c / 2601 passed / 13 skipped`，默认完整部署到历史远程主机，且主要覆盖代码加固，
  未纳入 P0–P2 已落地的 MemorySources、State Overlay、Recall Plan、Review Agenda、Lane Status
  和认知伙伴演进主线（P0–P2 源码修复周期见上一节，提交 `520f1be`）。
- **更新**：路线图升级为 v2，基线更新至 `520f1be`；新增六阶段证据模型、自然观察/晋级门、
  targeted production deployment、mount namespace 测试隔离、分类化 skip/warning 门、公共
  closure matrix、认知伙伴五维演进和近期执行顺序。
- **治理边界**：文档明确手工/legacy 证据不计自然成熟度；Recall 保持 shadow；V3 Seed ready
  前不调用 wandering inference；永久记忆、身份/关系、外部发送和执行仍受 OwnerGate 控制。
- **验证**：本次仅修改公共 Markdown 文档和本稳定化清单，不改变代码、生产配置、账本、cron
  或 Gateway。验证以 `git diff --check`、旧基线/必要章节扫描和文档交叉引用检查为准；代码
  基线沿用提交 `520f1be` 已完成的源码及 fresh-clone 全量 `2620 passed / 6 skipped / 4 warnings`。

---

## BH.1 — 路线图状态枚举澄清（2026-07-19，提交 `95e51f1`，文档变更）

- **背景**：BH 引入的路线图 v2 在 Section 4 定义了封闭的 8 值状态枚举，但 R2（部分实现）与
  R5（基础已部署）两个聚合标题用了枚举外的标签，构成自相矛盾。
- **更新**：明确该枚举只约束 checklist **条目**本身；R1–R6 是聚合小结标题，允许用枚举术语
  组合而成的描述性标签。同时为 R1.1 引用的 V2-A/B/C/D 代号补一行指向真实定义处
  （`exposure_rollup.py`/`crystallized.py`/`knob_overrides.py`/`contested_pairs.py`，代号本身
  不在路线图文档中重复定义）。
- **验证**：仅修改 `hermes-memory-os-optimization-roadmap.md` 4 行；不改变代码、生产配置、
  账本、cron 或 Gateway，`git diff --check` 干净。

---

## BI — 路线图 v2.1 纳入 Gap Note（2026-07-19，文档变更）

- **背景**：Owner 确认 GBrain 可吸收的最高价值内核是 Gap Note——系统不仅返回它知道的，也要
  对本次召回直接相关的未解决冲突、过期状态和证据边界作一行诚实提示；独立 explain/debug
  渲染项明确不纳入路线图。
- **源码核对**：当前 `a5c1c04` 已有按 `claim_key` 生成的 conflict、`stale_task_revision`、
  session injection ledger 和 Exposure attribution gap，但成熟度不同：Owner-level conflict 与
  stale task 可直接作为 candidate；session duplicate 不具备长期时长；普通 freshness 尚缺完整
  producer 赋值；Exposure gap 是全局聚合而非当前 selected-object 事实。
- **更新**：路线图升至 v2.1；R1.2 增加 metadata-only Gap Note shadow candidate 和零误报/零正文
  持久化门；R5.2.1 定义结构化数据流、第一阶段信号、延期信号、预算/文案/相关性边界与反事实
  测试；近期顺序和最终成功标准同步纳入。
- **治理边界**：shadow/off 保持 output-neutral；只有 Recall `apply_canary` 可渲染；不从“没有找到
  更新”推导“现实没有变化”；全局 Monitor attribution gap 不机械附加到答案；不新增热路径 LLM、
  采集面、canonical 写入或独立 `--explain` 路线。
- **验证范围**：仅修改两个公共 Markdown 文档，不修改代码、生产配置、账本、cron、runtime、
  plugin 或 Gateway。按文档变更发布门执行 `git diff --check`、契约/引用扫描、mount-isolated 全量、
  静态治理门和提交后 fresh-clone 全量。

---

## BJ — ExecutionGate helper completion 漏判 disabled job 为 missing（2026-07-29）

- **背景**：应 Owner 要求，依据 `docs/resolver/hermes-memory-os-optimization-roadmap.md`（v2.5，
  基线 `b52173b`）Section 5 的"当前真实问题与风险登记"逐条核对代码。P1 #6"ExecutionGate helper
  receipt 不完整"是唯一一条未被后续提交标记为"已完成"的条目，文本明确要求区分四类状态：
  envelope 账务未对齐（reconciled）、未到期（not_due）、job disabled、真实执行失败（error）。
  核对 `scripts/memory_os_3_200_monitor.py` 的 `_execution_gate_helper_completion_summary()`
  （该函数与调用它的 `execution_gate_cron_summary()` 实际定义在 `_remote_probe_script()` 生成的
  远端探针脚本字符串内，本仓库内只有这一份实现，非重复代码）后确认：前三类均已实现，唯独
  `job disabled` 完全没有被检查——函数从未读取 `jobs.json` 的 `enabled` 字段。
- **根因**：memory-os 只读取 `jobs.json`（Hermes 自身 cron 子系统所有），并不拥有其 enable/disable
  写入路径；owner 可通过 Hermes 原生 cron 管理随时禁用任意已注册 job（包括 active-closure 10 个
  核心 job 之一），与 `memory_os_owner_cron_onboarding.py` 的 `_pause_known_optional_cron_jobs()`
  （只暂停不在当前 profile operational spec 集合内的可选 job）是两条独立路径。已注册 lane 若被
  外部禁用且无新鲜 completion 记录，会落进 `missing`，与真实执行失败/envelope 未对齐混淆——不算
  伪造，但确实产生假 WARN，且 `_execution_gate_helper_completion_summary()` 此前完全没有直接单元
  测试（唯一覆盖是 `tests/plugins/memory/test_memory_os_audit_arbitration.py` 里两个反事实测试）。
- **修复**：每个 lane 在判定 missing/stale 前先查其 cron job 的 `enabled`；`enabled is False` 时归入
  独立 `disabled` 分档（`helper_completion_disabled_count`/`_lanes`），不进入 missing/stale，也不推高
  `boundary_unobserved`（禁用 job 本就不产生 boundary 证据，不应与"reconciled 但缺 boundary 证明"
  混为一谈）。`helper_completion_accounted_count` 守恒公式同步纳入 disabled 分档（原公式
  `completed+missing+reconciled` 现补 `+disabled`，否则守恒断言会在 disabled>0 时失真）。
  `classify_snapshot` 新增独立 WARN 码 `execution_gate_memory_os_cron_helper_completion_disabled`。
- **同类扫查（规则 5）**：确认全文件仅此一处"expected lane → missing/stale/completed"分类循环
  （`grep "\.append(lane)"` 唯一 6 处命中均在同一函数内）；另确认 `helper_completion_missing` /
  `_stale` / `_error` / `helper_boundary_unobserved` 四个既有兄弟码均未注册进
  `CLEAN_HOST_WARN_CLASSIFICATIONS`——核对 `deploy_memory_os.py`/`memory_os_public_checkout_probe.py`
  均不调用 `memory_os_owner_cron_onboarding.py`，clean-host 标准路径下 `specs_by_lane` 恒为空，这组
  WARN 码在 clean-host 不可达，因此新码沿用兄弟码的现状不注册，属有意一致（非本次遗漏）。
- **反事实**：`git stash` 暂存仅源码改动（保留新/改测试）后跑
  `tests/plugins/memory/test_memory_os_audit_arbitration.py` +
  `tests/scripts/test_memory_os_3_200_monitor.py` 相关子集 → 4 处新增/改动断言 FAIL
  （`KeyError: 'helper_completion_disabled_count'`/`'_lanes'`、`StopIteration`）；`git stash pop`
  恢复源码 → 7 passed。
- **新测试**：`test_execution_gate_disabled_job_is_not_reported_as_missing`、
  `test_execution_gate_disabled_job_with_no_last_status_is_still_disabled_not_missing`
  （`test_memory_os_audit_arbitration.py`，直接单测 `_execution_gate_helper_completion_summary`）、
  `test_classify_snapshot_warns_on_memory_os_cron_helper_disabled_completion`
  （`test_memory_os_3_200_monitor.py`，锁定 `classify_snapshot` 新 WARN 码且断言不再误落
  `helper_completion_missing`）；既有 `test_execution_gate_fresh_reconcile_is_degraded_and_accounted`
  的守恒断言同步补 `+ helper_completion_disabled_count`。
- **验证结论**：
  - 定向：`test_memory_os_3_200_monitor.py` + `test_memory_os_audit_arbitration.py` 全量
    **218 passed**。
  - 全量：**3013 passed / 9 failed / 13 skipped**（Windows 本机检出，纯 `python -m pytest -q`，
    非 mount-isolated）。9 项失败（`test_memory_os_deploy_clean_host.py` 路径分隔符/子进程解析×3、
    `test_deploy_community.py` 回滚断言×1、`test_memory_os_full_monitor_refresh.py` 端到端×1、
    `test_memory_os_mount_isolated_pytest.py` 路径断言×1、`test_memory_os_pytest_policy.py`
    skip-count 断言×2）经 `git stash` 验证在未改动的 `b52173b` 上原样复现，与本次改动无关，属
    Windows 本地 `local_pass` 与 Linux mount-isolated/clean-copy 口径差异（路线图 §3.1 的
    `3016 passed / 9 skipped` 来自后者），非本次引入的回归，未修复，留作独立跟进项。
  - 静态门：import cycle pass（170 modules / 0 cycles）/ write surface `unclassified_count=0`
    （155/155 已分类）/ static hygiene pass（含 closure matrix、provider-agnostic、public checkout
    probe）/ public checkout probe `--strict` PASS / `git diff --check` 干净。
  - 证据级别：`local_pass`（本次改动的定向验证）；全量数字口径为 Windows 本地非隔离运行，不等价
    于 mount-isolated 或生产 live monitor 证据。
- **文档同步**：路线图 P1 #6 条目更新为已修复状态描述，注明生产远端真实禁用场景观察仍待部署后
  自然验证（不手工回填）。
- **已知遗留（非本次修复范围，供下一周期参考）**：
  1. 上述 9 项 Windows 本地测试失败（与本次改动无关，需独立诊断）。
  2. `helper_completion_missing`/`_stale`/`_error`/`helper_boundary_unobserved` 四个既有 WARN 码
     未注册进 `CLEAN_HOST_WARN_CLASSIFICATIONS`（当前因 clean-host 不可达而非缺陷，但若未来
     `deploy_memory_os.py` 接入 cron onboarding 则需要一并注册）。
  3. 本文件自 `f99062c`（Gap Note roadmap v2.1）起，到本节之前的数十个提交（R7 Sannai Community
     全部功能、batch 4/5 helper 模块、多轮 monitor/deploy 修复等）未追加对应稳定化记录——这是历史
     遗留的流程缺口，非本节引入，本节不做追溯补写，仅如实记录缺口存在。

---

## BK — 9 项 Windows 本地 pre-existing 测试失败诊断与修复（2026-07-29）

- **背景**：BJ 节记录的全量测试留下 9 项 Windows 本地失败，Owner 选择将其作为下一周期目标。
  逐项复现并追根因，而不是批量假设"环境问题"或批量跳过。

### 真实代码缺陷（已修复，4 项）

- **`plan_deployment()` 相对路径分隔符与 `_deployed_file_paths()` 不一致**
  （`plugins/memory/memory_os/deploy_clean_host.py`）：`plan_deployment()` 用
  `str(relative)` 记录 `files_to_copy`/`files_to_skip`，Windows 下产出反斜杠路径；同文件的
  `_deployed_file_paths()`（`postcheck_deploy()` 用于比较"应部署"与"实际部署"文件集合）已用
  `.as_posix()`。两者口径不一致意味着 `postcheck_deploy()` 在 Windows 上对**任何**文件都会同时
  误报"target missing deployed file"和"target contains stale file"——不是测试断言口径问题，是
  跨主机 manifest/postcheck 比对的真实缺陷。修复：`plan_deployment()` 改用 `.as_posix()`，与
  `_deployed_file_paths()` 对齐。
  - **反事实**：`git stash` 暂存仅此文件改动 → `TestPlanDeployment::test_plan_with_files`、
    `TestFullPipeline::test_pipeline`、`TestFullPipeline::test_postcheck_detects_target_hash_drift`
    三个测试 FAIL（`assert ['plugins\\a.py'] == ['plugins/a.py']` 等）；恢复 → 10 passed。

- **`classify_snapshot()` 对 `status_tool_contract` 为 `None` 时崩溃**
  （`scripts/memory_os_3_200_monitor.py`）：`contract = snapshot.get("status_tool_contract", {})`
  的 `{}` 默认值只在键缺失时生效；`collect_snapshot()` 中该字段由
  `contract.get("validation") if isinstance(contract, dict) else contract` 构造，探针返回
  `{"_error": ...}`（无 "validation" 键）时该字段被显式写入 `None`——键存在但值为 `None`，默认值
  从未触发。随后 `contract.get("status")` 对 `None` 调用 `.get()` 抛 `AttributeError`，导致
  `collect_snapshot()` 整体崩溃（`e2e` 测试实测："monitor process exited 1"，不是任何一个 section
  的孤立 FAIL，而是整个 Full Monitor 采集中断）。同一函数 12 行前的 `doctor` 字段已用
  `doctor_raw = snapshot.get("doctor"); doctor = doctor_raw if isinstance(doctor_raw, dict) else {}`
  正确处理同类风险——`status_tool_contract` 是唯一没跟上这个防护模式的兄弟字段。修复：`contract`
  改用与 `doctor` 完全一致的 `isinstance` 防护。
  - **规则 5 同类扫查**：对 `classify_snapshot()` 内其余 33 处 `snapshot.get(key, {})` 站点逐一核查
    是否存在同一"键存在值为 None"风险——除 `status_tool_contract` 外，其余站点的来源要么是恒返回
    dict 的辅助函数（如 `system_show()`、`compaction_stats()`、`expression_artifact_summary()`
    等专用 summary 函数)，要么消费方用 truthy 检查（`if x:`，`None` 天然为假，不会崩溃）或显式
    `isinstance` 守护——非假设性结论，逐个函数定义核实后确认无第二例。
  - **反事实**：`git stash` 暂存仅此文件改动 → 新增
    `test_classify_snapshot_treats_null_status_tool_contract_as_failed_not_a_crash` FAIL
    （`AttributeError: 'NoneType' object has no attribute 'get'`，与生产实际崩溃报错完全一致）；
    恢复 → PASS；`tests/scripts/test_memory_os_full_monitor_refresh.py::
    test_real_monitor_refresh_reader_and_dashboard_contract_end_to_end`（原始失败用例，调用真实
    monitor 子进程）随之由 FAIL 转 PASS。

- **`test_deploy_community.py` 用正斜杠字面量匹配 `str(Path)`**：
  `test_apply_rolls_back_every_changed_file_on_copy_failure` 的 `flaky_copy` monkeypatch 用
  `"runtime/python" in str(target_path)` 判断注入失败时机，Windows 下 `str(target_path)` 是反斜杠，
  条件永不成立，注入的复制失败从未触发，测试断言"回滚"实际验证的是从未失败的正常路径。修复：改用
  `target_path.as_posix()`。纯测试修复，不涉及 `scripts/deploy_community.py` 生产逻辑。
  - **反事实**：原始失败即为此断言（`assert 'applied' == 'fail'`）；改用 `.as_posix()` 后
    11 passed。

- **`test_memory_os_mount_isolated_pytest.py` 用 `Path` 构造目标主机（Linux `unshare` 命名空间）
  侧的解释器路径**：3 处测试用 `Path("/venv/bin/python")` 构造 `build_namespace_command()` 的
  `python` 入参；`build_namespace_command()` 的执行目标永远是 Linux `unshare`/`mount --bind`
  命名空间（生产/CI 主机），与运行 pytest 的宿主机 OS 无关，因此该入参代表的是目标端路径而非本机
  路径。用平台相关的 `pathlib.Path` 构造它，在 Windows 宿主机上会被错误规范化为反斜杠。修复：改用
  `pathlib.PurePosixPath`——不依赖宿主机平台，永远保持正斜杠，与函数实际语义对齐。纯测试修复。
  - **反事实**：原始失败为 `test_command_uses_explicit_paths_not_ambient_configuration` 的
    `assert [...] == [...]`（`\venv\bin\python` != `/venv/bin/python`）；改用 `PurePosixPath` 后
    4 passed。

### 环境伪影（已诊断，未修复；非项目代码缺陷）

- **`test_memory_os_pytest_policy.py` 两项 skip-count 断言（`assert 2 == 1`）**：追根因发现是
  本机 pytest 在 `%TEMP%`（`C:\Users\btnal\AppData\Local\Temp`）路径下对同一测试文件重复收集两次，
  分别产出 `C:\Users\...` 和 `C:\Documents and Settings\...`（Windows 遗留兼容 junction，
  `os.path.realpath()` 证实两者指向同一物理路径）两种字符串形式的 nodeid——用**不引入 memory-os
  任何代码**的最小复现（裸 `python -m pytest --collect-only -q <file>`，指向 `%TEMP%` 下的临时文件）
  证实该重复收集在 vanilla pytest 层面即可复现；同一文件放在 `D:\` 盘下则只收集一次。这是本机
  pytest 版本（8.4.2）/ Python 3.13.7 与本机 `%TEMP%` 路径别名交互产生的环境伪影，不是
  `memory_os_pytest_policy.py` 的计数逻辑缺陷，也未在其他任何测试路径中观察到。未做修复：
  1) 修复方式若是"按 nodeid/reason 去重计数"，等于假设"同一 skip 事件可能被重复报告"为正常情况，
     可能掩盖未来真实的重复执行缺陷；2) 该缺陷的根因完全在项目代码之外（pytest 内部 rootdir/nodeid
     计算 + 本机临时目录别名），修复应落在环境或 pytest 版本层面，不应为了讨好本机而改动生产测试
     契约。这两个测试本身正确；只在本机这一特定环境下才会失败。

### 记录但不修复的同类模式（规则 5 扫查产物）

- `scripts/install_memory_os_plugin.py` 的 `copied_files`/`agent_os_shell_files`/
  `system_module_files`/`agent_runtime_files`/`eval_runtime_files`（5 处）与本节修复的
  `plan_deployment()` 用的是同一 `str(path.relative_to(...))` 模式，理论上在 Windows 上也会产出
  反斜杠。当前没有测试以分隔符敏感方式断言这些字段（现有断言都是 `"__pycache__" in path` 式子串
  检查，分隔符无关），且该安装脚本的实际执行环境始终是生产 Linux 主机——不存在当前会触发的失败，
  按"不为不会发生的场景添加防御代码"原则暂不改动，此处仅记录以备将来该脚本获得 Windows 执行路径时
  参考。

### BK 验证结论

- 定向：`test_memory_os_deploy_clean_host.py`（10 passed）+ `test_deploy_community.py`
  （11 passed）+ `test_memory_os_full_monitor_refresh.py`（原失败用例转 passed）+
  `test_memory_os_mount_isolated_pytest.py`（4 passed）+ `test_memory_os_3_200_monitor.py` +
  `test_memory_os_audit_arbitration.py` 全部通过；`test_memory_os_pytest_policy.py` 两项按上述
  结论保持环境相关失败（未修复，已诊断记录）。
- 全量：**3021 passed / 2 failed / 13 skipped**（BJ 基线 3013 passed/9 failed + 8 新增/改动测试；
  2 failed 精确对应上述"环境伪影"结论的两个 pytest_policy 用例，其余 7 项此前失败的用例全部转
  passed，与逐项定向验证结果一致）。
- 静态门：import cycle pass（170 modules / 0 cycles）/ write surface `unclassified_count=0`
  （155/155）/ static hygiene pass / public checkout probe `--strict` PASS /
  `git diff --check` 干净。
- 证据级别：`local_pass`（Windows 本地，非 mount-isolated）。

---

## BL — 路线图 v2.6：基线刷新 + P2 债务清单以 caller 证据核实（2026-07-29，文档变更）

- **背景**：`004a16b` 经 Owner 亲手 fast-forward 合并进 `origin/main`（CI run #29 success），
  远端工作分支已删除。Owner 要求审查路线图文档并用 codegraph 对照实际代码。
- **方法**：codegraph（主检出索引，先把主检出从 `a5c1c04` fast-forward 到 `004a16b` 使索引对齐）
  文件级 dependents + `codegraph_callers`，每个影响结论的边再用 grep import 语句复核。
- **发现与修订**（均已写入路线图 v2.6）：
  - §3.1/3.2 基线过期：最新 CI 验证源码已是 `004a16b`（本地 Windows 全量 3021/2 env/13，
    CI run #27/#28/#29 全绿），且相对 `f62a069` 新增三项修复（BJ/BK）未列入。改为"最新已合并
    基线（未部署）"与"最近已部署基线 `f62a069`"两层分述，保持 release ≠ deployed 边界；
    低资源 bounded collection 状态 `tested/deployment_pending` → `released/deployment_pending`。
  - §5 P2 #10 helper 债务清单逐项以 import/caller 证据核实：原 10 项全部属实（仅测试引用），
    但清单漏了两个同类债务——`natural_evidence`（typed provenance/观察窗/毕业门 helper，仅测试
    引用；生产 natural-row 门控实际由 `execution_gate.resolve_trigger_class()` 在 exposure_rollup/
    v3_seed_evidence 两条 cron 周期中承担 + wandering/dashboard 内联过滤）与 `restraint`
    （DenialTracker/SessionPriority，仅测试引用）。两项已补入。
  - `timeutil` 债务量化：生产/脚本代码剩余 10 处 ad-hoc 时间解析实现（cleanup、owner_actions、
    permanent_promotion、structural_edge_proposer、v3_retention、v3_seed_evidence、
    community_triggers、monitor_dashboard_snapshot、right_brain_expression_outcome、
    speak_rate_limit；远端探针自包含 `_parse_monitor_timestamp` 属有意例外）；`timeutil` 唯一
    生产采用路径为 `__init__ → session_approval`。原文"当前仍存在多份"改为可证伪的具体清单。
  - §4.4/§8 "natural-row 分类已接入 Natural Evidence、…"措辞失真（natural_evidence helper 并无
    生产 consumer），改为指明真实生产实现位置。
  - §14 优先级 1 更新：发布已完成，仅剩部署。
- **工具经验（并入 Section W 精神）**：codegraph 索引在主检出大幅落后又快进后会残留过期依赖边
  ——本次三条 "used by" 边（restraint←cognitive_loop、monitor_perf←deploy_clean_host/
  deploy_community、continuity←natural_evidence 的生产侧）经 grep 证伪。任何影响结论的
  codegraph 边必须用 grep/Read 复核后才能写入文档或据此改代码。
- **验证**：仅修改两个公共 Markdown 文档；不改代码、生产配置、账本、cron 或 Gateway。
  `git diff --check` 干净；代码基线沿用 `004a16b`（CI run #29 success；本地全量与静态门见 BK）。

### BL.1 — 全树历史尾随空白清理（CI 新分支全树检查暴露）

- **背景**：`docs-roadmap-v2-6` 作为**新分支**首次 push 时，CI 的 whitespace 步骤因
  `github.event.before` 为全零而走空树 fallback——对**整棵 HEAD 树**执行 `git diff --check`，
  翻出 5 个历史遗留文件的尾随空白/EOF 空行（`install_memory_os_plugin.py` ×10 行、
  `memory_os_candidate_backfill_409.py` ×1、`test_verify_crystallized_lines_fix.py` ×3、
  `test_candidate_compact_atomic.py` 与 `test_memory_os_crystallized.py` EOF 空行）。这些文件
  本轮文档提交并未触碰；此前所有 push 都有 before-SHA，只查推送区间，因此债务从未暴露。
- **修复**：纯空白清理（全部违规行都是仅含空白的缩进行或 EOF 空行，无字符串内空白风险）；
  修后本地空树全树 `git diff --check` exit 0——今后任何新分支首次 push 不再因此失败。
  选择清债而非改 workflow：全树无空白错误本就是仓库既有标准（第 12 节发布门），fallback
  行为在树干净的前提下是合理防线。
- **验证**：`py_compile` 两个脚本通过；三个被触碰测试文件全量 52 passed；空树 vs 工作树
  `git diff --check` exit 0。

---

## BM — 落地代码复审：monitor/deploy/v24_final_verify 14 项发现修复（2026-07-29）

- **背景**：对已落地的 roadmap v2.6 代码（`523b895` 之后的 monitor.py/deploy_memory_os.py 等）
  跑 `/code-review`，产出 14 项发现（2 项 CRITICAL）。先用 advisor 核实修复方案（发现原计划的
  rh26 修复会把"崩溃"换成"静默 PASS"，同类缺陷，且 `#5` 的猜测范围过大——advisor 建议先枚举
  哪些 snapshot 字段真的有 `None` 触发路径，再决定要不要补防护），再逐项落地。
- **P0（CRITICAL，均已修复）**：
  1. `rh26_probe()`/`low_clue_ingress_matrix()` 探针失败时返回裸 dict（`{"_error":...}`），
     `classify_snapshot` 对应两处消费点用 `list(...)`/逐项 `.get()` 处理，取到 dict 的 keys
     后逐项 `AttributeError` 崩溃整个 classify_snapshot。修复：两个探针函数改为返回单元素
     list；`classify_snapshot` 两处消费点加 `isinstance(x, list)` 防护 **并**显式识别
     `_error` 条目产出 `rh26_probe_unavailable`/`low_clue_ingress_matrix_unavailable` FAIL 码
     ——只加 isinstance 防护会把"崩溃"换成"零异常、零 FAIL 的静默 PASS"（advisor 指出的同类
     缺陷，等价于 #8）。反事实：临时还原两处均实测崩溃/静默通过，恢复后 FAIL。
  2. `_execution_gate_helper_completion_summary()` 的 disabled-job 分支在读取 completion
     record **之前** 就 `continue`，导致一个先记录了 `postcheck_boundary_true=True` 或
     `execution_status!=ok` 、后被禁用的 cron job，其证据被静默丢弃（`classify_snapshot` 对
     这两个计数器是无条件硬 FAIL，行为从"抓真实治理边界违规"退化为"永远不会触发"）。修复：
     record 提到 disabled 判断之前读取；disabled 分支若有 record，只吸收 `error`/
     `boundary_true` 两项证据，不计入 `completed`/`stale`/`not_due`，不动
     `boundary_observed`/`unobserved`/`not_required`（守恒公式 `expected = completed +
     missing + reconciled + disabled` 不受影响）。反事实：还原后 `helper_boundary_true_count`
     从预期 1 变 0，恢复后回到 1。
- **P1（高优先级，均已修复）**：
  3. `_memory_os_known_cron_specs()` 只覆盖 `RETIRED_MEMORY_OS_CRON_SCRIPTS`（wrapper 名），
     未覆盖 `cron_registry.py` 的 `RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES` 里另外两个 legacy
     raw 脚本名，未迁移到 wrapper 名的主机会重新触发 `unregistered_like` FAIL（本次 P0
     "分类 retired cron fallback" 修复本要解决的确切问题）。修复：补 legacy raw 名对应的
     `retired-legacy:` 条目；`"name"` 字段用脚本文件名本身（而非空字符串），避免与
     `known_specs_by_name` 里可能存在的空 name job 碰撞（advisor 指出的坑）。端到端测试：
     写入带 legacy raw 脚本名的 `jobs.json`，验证 `execution_gate_cron_summary()` 分类为
     `known_optional`、`memory_os_like_unregistered_count == 0`。
  4. `deploy_memory_os.py` 的 `_build_commands()` 给 4 个本地 hermes CLI 调用加
     `["env", "HERMES_HOME=...", ...]` argv 前缀期望有真实 `env` 可执行文件，本地
     （非 SSH）路径下 `subprocess.run(argv)` 无 shell，本机（含本仓库 Windows 开发机）无
     `env` 时会 `FileNotFoundError`。修复：`_run_command()` 识别该前缀自行解析为
     `env=os.environ.copy()` + 剥离前缀后的 argv，不依赖真实 `env` 二进制；SSH 路径
     （`_ssh_wrap` 拼成远端 shell 命令行）不受影响，仍由远端主机真实 `env` 执行。同时把
     4 处重复的前缀字面量合并成 `env_prefix` 局部变量。反事实：还原后本地路径捕获到未剥离
     的 `["env", "HERMES_HOME=...", "hermes", ...]`（会尝试执行不存在的 "env"）。
  5. 同一 `_run_command()` 的 `subprocess.run(argv, timeout=timeout)` 无 `try/except`，若外层
     timeout 早于 compat 脚本内部 `--timeout` 预算触发，`TimeoutExpired` 会未捕获地崩溃
     `deploy_memory_os()`，而不是走既有的、分类后的 postcheck-fail 结果。修复：捕获
     `TimeoutExpired` 返回 `exit_code=124` 的结构化 dict（与 monitor.py 的 `run()` helper
     同款约定）。反事实：还原后复现 `subprocess.TimeoutExpired` 未捕获崩溃。
  6. `_run_probe()`（把整份探针脚本经 SSH/本地子进程执行的顶层驱动）本身没有 timeout——
     生成脚本内部的逐命令 timeout 只界定单条命令，SSH 连接本身挂起时仍可无限阻塞，与本次
     "逐命令加 timeout" 的 fail-closed 主张矛盾。修复：加 `timeout_seconds` 参数（默认复用
     既有的 `FULL_MONITOR_MIN_CALLER_TIMEOUT_SECONDS=300`），捕获 `TimeoutExpired` 返回
     `{"_probe_timeout": True, ...}`；`collect_snapshot()` 检测到该标记后**显式短路**为
     `FAIL` + `probe_script_timeout` 码，不把近乎空的 dict 送进未经验证的
     `summarize_*`/`classify_snapshot` 调用链（advisor：这个假设必须用测试验证，不能只靠
     分析）——测试证实 `render_chinese_summary()` 对该短路结果也能正常渲染，不崩溃。
- **P2（已修复/已确认无需修复，逐项列出）**：
  7. `compaction_stats()`/`hook_marker_counts()` 沿用共享默认 20s timeout（本次 roadmap
     为 22 条 shell_alias 命令引入），在大型生产 `memory-os/audit` 树上可能超时，静默把
     `recent_count`/`total` 报成 0 而不产出任何 WARN/FAIL。修复：仅这两处显式传
     `timeout_seconds=60`（与已有的 `_execution_gate_cron_adapter_probe_summary` 60s 先例
     一致），不改动共享默认值本身（其余调用点的超时预算不在本次问题范围内）。
  8. `find_rh26_heading_anomalies`/`_probe_summary` 等消费点 `classify_snapshot()` 里约 45
     处 `snapshot.get("x", {})` 无 isinstance 防护——**逐一排查后确认**：整份生成脚本最终
     JSON 组装处（`scripts/memory_os_3_200_monitor.py` 尾部 `print(json.dumps({...}))`）只有
     `status_tool_contract` 一处会产出显式 `None`（`contract.get("validation")` 缺 key 时），
     其余字段要么直接来自恒返回 dict 的函数（`shell_alias_no_env()` 等），要么是嵌套 dict
     字面量的子字段（已有独立防护）。`classify_snapshot` 也仅被本文件的 `collect_snapshot()`
     和测试直接调用，从未对磁盘 JSON（`--snapshot-out`/`--previous-json`）重新分类。
     `status_tool_contract` 已在 BK 修复。**结论：无需补充改动**——为不存在触发路径的字段
     补 isinstance 防护属于"不为不会发生的场景加防御代码"应避免的范畴；记录以备将来该组装
     逻辑改动时复核。
  9. `test_memory_os_audit_arbitration.py` 4 处（原报告误写"行 454"，实际在 32/52/79/107 行）
     与 `test_memory_os_3_200_monitor.py` 3 处，用 `.split('\nstatus = load_json_cmd', 1)`
     切出探针脚本的"仅函数定义"前缀。实测：该字面量确实不再匹配 `shell_alias_no_env()` 内部
     （本次 roadmap 改造为 dict+ThreadPoolExecutor 后，序列赋值形式已消失），而是巧合匹配到
     脚本尾部约 32KB 之外一处无关的顶层调用赋值——该赋值恰好仍是"所有函数定义结束/所有顶层
     调用开始"的正确分界点，只是全靠字面量巧合而非显式标记，未来重构任一函数都可能使其失配，
     届时 `.split(...)[0]` 会退化为返回整份脚本，`exec()` 在单测里跑出真实 subprocess 调用。
     修复：在 `_remote_probe_script()` 该分界点前插入显式哨兵注释
     `# ---begin-probe-invocations---`，7 处测试改用该哨兵切分；新增测试断言哨兵在生成脚本
     中只出现一次。
  10. `memory_os_v24_final_verify.py` 的 `initialize_clean_git()` 用
      `(source_root / path).exists()` 过滤 `git ls-files` 结果，但随后的 `git add -f` 以
      `cwd=repo_root`（`copy_clean_tree()` 过滤后的副本）运行——一个被
      `IGNORED_COPY_PARTS`（如 `build/`）排除出副本、但仍是 git 已跟踪文件的路径，会通过
      `source_root` 存在性检查却在 `repo_root` 里找不到，`git add -f` 报 "pathspec did not
      match any files" 崩溃。当前仓库 `git ls-files` 确认无实际触发（advisor：仍应直接修，
      这是谓词用错了对象而非投机式加固）。修复：谓词改测 `repo_root`。反事实：还原后新增
      测试实测复现 `CalledProcessError: ... 'git' 'add' '-f' ... returned non-zero exit
      status 128`，恢复后通过。
  11. `review reply memory approve oa_deadbeef`（`shell_alias_no_env()` 22 条并行 CLI 探针之
      一，本次 roadmap 由串行改 `ThreadPoolExecutor` 并行）用的是不存在的假 token。跟踪
      `owner_actions.py` 确认：未匹配到任何 token 时在到达任何状态变更代码前就以
      `action_token_not_found_in_recorded_digest` 早返回，不写 ledger、不产生副作用——这条
      特定探针命令本身是安全的只读探针。22 条命令并发对同一 `HERMES_HOME` 文件/SQLite 状态
      的一般性并发风险（无实测复现、无并发单测覆盖）记录为已知残留风险，不在本轮修复范围。
- **验证**：
  - 定向：`test_memory_os_3_200_monitor.py` + `test_memory_os_audit_arbitration.py` +
    `test_memory_os_deploy.py` + `test_memory_os_v24_final_verify.py` 全部通过（含新增 14
    个反事实测试，其中 5 个用 revert→fail→restore→pass 实测验证：rh26 静默 PASS、rh26 崩溃、
    disabled-job 证据丢失、deploy env 前缀、deploy TimeoutExpired、v24 pathspec 崩溃）。
  - 全量：**3035 passed / 2 failed / 13 skipped**（BK 基线 3021 passed + 本轮新增 14 项测试；
    2 failed 精确对应 BK 记录的 pytest_policy skip-count 环境伪影，与本次改动无关）。
  - 静态门：import cycle pass（170 modules / 0 cycles）/ write surface
    `unclassified_count=0`（155/155）/ static hygiene pass / public checkout probe
    `--strict` PASS / `git diff --check` 干净。
  - 证据级别：`local_pass`（Windows 本地）。

---

## BN — 本机对齐 `origin/main`、targeted deployment 与生产验证（2026-07-29）

- **源码对齐**：`/opt/Hermes-Memory-OS` 从 `b52173b` fast-forward 5 个提交到
  `2b235370b26dc3640b9e3e3f0b38ca24e0191a05`；结束时 `HEAD == origin/main`。
- **源码门禁**：命令级隔离 `HERMES_HOME` 的 Linux 全量为 **3041 passed / 9 skipped / 0 failed**
  （446.78s）；write surface `155/155`、`unclassified_count=0`；import cycle `170 modules / 0 cycle`；
  static hygiene/public checkout/diff check 全过；Closure Matrix 为 `status=ok`、
  `closure_status=runtime_evidence_required`。
- **部署类别**：遵守默认 GitHub 更新的 targeted-update 边界，没有运行 full deployer apply、没有
  刷新 full-deploy manifest、没有重启 Gateway。覆盖前逐目标要求生产文件与 `b52173b` 对应 source
  baseline 字节一致；备份目录为
  `/root/.hermes/backups/memory-os-targeted-20260729T113016Z`。
- **实际同步**：
  - `deploy_clean_host.py` → flat production plugin 与 internal runtime 两棵独立树；
  - `memory_os_3_200_monitor.py`、`memory_os_candidate_backfill_409.py` → `/root/.hermes/scripts/`；
  - 同步后 4 个目标 SHA-256 均与 `2b23537` source 相等并清理相关 `__pycache__`。
- **明确保留/未扩展**：`/root/.hermes/scripts/install_memory_os_plugin.py` 在 drift gate 中确认含既有
  production-local 差异，且本轮 upstream 只改该文件尾随空白，因此未覆盖；
  `scripts/deploy_memory_os.py` 与 `scripts/memory_os_v24_final_verify.py` 在当前 runtime installer map
  中没有对应目标，未额外创建文件。`embedder.py`、`index.py`、`vector_edge_proposer.py` 两棵生产树
  hash 保持相同，未触碰 canonical data、cron、timer、配置或 Gateway。
- **部署后行为验证**：
  - internal runtime fresh import origin 指向
    `/root/.hermes/memory-os/runtime/python/plugins/memory/memory_os/deploy_clean_host.py`；
    `plan_deployment()` probe 通过；
  - installed Monitor `--help`、py_compile、timeout→结构化 marker、rh26/low-clue probe error→显式 FAIL
    的反事实均通过；candidate backfill 只运行 `--help`，未进入任何写路径；
  - 生产 Full Monitor 直接实跑输出有效 `memory-os.monitor.v1`，退出码 2、分类
    **FAIL（97 pass / 4 warn / 1 fail）**。唯一 FAIL 为既有
    `v2_exposure_schema_era_unhealthy`；WARN 为 suppressed prefetch error、一个 owner-disabled
    expression-feedback helper、两个 helper boundary 未观察及 low-clue LLM judge empty response。
- **结论**：targeted deployment integrity 通过；production governance closure 仍不绿色。不得把后者
  误判为文件同步/导入失败，也不得手工补写自然证据改绿。

---

## BO — CI 修复：benchmark SLO 测试在 mount-isolated runner 下抖动（2026-07-29）

- **触发**：GitHub Actions `Run mount-isolated full suite with policy gate` 步骤报
  `test_tiny_benchmark_uses_synthetic_corpus_and_reports_slo` 的
  `assert report["pass"] is True` 失败（`report["pass"] is False`），其余
  3036 passed / 13 skipped，仅此一项 FAIL。
- **根因**：该测试对 `run_benchmark()` 做单次墙钟测量并硬性断言全部 6 项 SLO
  （`plugins/memory/memory_os/benchmark.py` 的 `DEFAULT_SLO`）都达标。CI 实际跑在
  `scripts/memory_os_mount_isolated_pytest.py` 的 `unshare --mount` 隔离命名空间内、
  且运行在共享 GitHub Actions runner 上，二者叠加带来的墙钟抖动足以偶发压过
  20–500ms 级别的阈值。本地（Windows，非隔离）15/15 次重跑全部通过，证实非功能性
  回归而是环境抖动。历史同款失败已出现过两次（2026-07-04 修复、2026-07-05 复发，
  当时均未定位根因，仅靠重跑/其他改动掩盖）。
- **修复**：仅改测试（`tests/plugins/memory/test_memory_os_audit_benchmark_cleanup.py`
  的 `test_tiny_benchmark_uses_synthetic_corpus_and_reports_slo`），不改
  `DEFAULT_SLO` 或 `run_benchmark()` 生产语义——`benchmark_report()`/CLI `benchmark`
  命令的阈值是唯一面向 owner 的真实性能诊断口径，放宽会削弱其对真实回归的检测力，
  且确认当前无自动化 monitor 消费该 `pass` 字段做门禁。测试改为最多 3 次尝试，
  每次用独立子目录（`tmp_path / f"attempt-{n}"`）跑全新 store 避免事件数在重试间
  累积失真，任一次 `pass=True` 即提前退出；若 3 次全部未达标则保留最后一次结果，
  断言照常 FAIL 并把 `slo_checks` 附在断言消息里，让下次复发能直接看到具体超标的
  指标与幅度，而不是像本次一样只能从 CI 日志反推。
- **反事实覆盖**：本修复是纯粹的测试抗抖动改造，不存在"缺了它就应该 FAIL 的功能代码路径"
  ——无法为"抖动是否被容忍"写出会在无修复时确定性 FAIL、有修复时确定性 PASS 的反事实
  （抖动本身不可复现）。缓解手段是有界重试 + 失败诊断信息，留痕于此以便下次复发时
  快速判断是否为同一根因。
- **测试数量变化**：无新增/删除测试，`assert` 数量不变；仅测试体内部逻辑从单次测量改为
  有界重试循环。全量本地（Windows）**3035 passed / 2 failed / 13 skipped**——2 个 FAIL 为
  `test_memory_os_pytest_policy.py` 的 `skip_count` 断言，经 `git stash` 验证在改动前后
  同样失败，属 BK/BM 记录的既有 Windows 本机 `%TEMP%` 环境伪影，与本次改动无关、CI
  （Linux）不会触发。import cycle（170 modules / 0 cycle）、write surface
  （155/155，`unclassified_count=0`）、static hygiene、`git diff --check` 全过。
- **结论**：CI FAIL 已修复为对墙钟抖动免疫；生产 benchmark SLO 语义未被削弱。

---

## BP — 复审 Sannai v2.9 提交（11.12 窗台/一起看/兴趣花园）：CI 修复 + 落差记录（2026-07-29）

- **触发**：用户要求同步 GitHub 最新提交并审查 `docs/resolver/hermes-memory-os-optimization-roadmap.md`
  的最新 Sannai 提交（`0897e5b` "11.12 小院子的新角落"、`609bc40` "社区通路全部测试通过"）。
  同步后本地 GitHub Actions `Memory-OS CI` 对这两个提交均为 FAIL。
- **根因**（两项 CI FAIL）：
  1. `write_surface_check`：新增的 `community_table.py`、`community_partner_runtime.py`
     （11.11.3 记录的"唯一净新增模块"，本次复审确认零调用方零测试）、
     `scripts/community_partner_reply.py` 共新增 8 处直接文件写入
     （`open(..., "a")` / `atomic_json_replace_call`），未在 `ALLOWED_WRITE_SURFACES`
     登记，`unclassified_count` 从 0 变为 8。
  2. `partner_create.py::create_partner()` 的 embedded_mode 分支加入后，非 embedded 分支的
     错误文案从 `"partner profile config required"` 改为
     `"partner profile config required in non-embedded mode"`（用于区分 embedded 缺
     `backend_info` 与非 embedded 缺 `partner_config_path` 两种失败），但
     `test_create_partner_requires_real_partner_profile_config` 断言未同步更新——文案改动
     合理，测试是陈旧的。
- **修复**：
  1. 8 处写入按既有先例逐一登记分类（`community_partner_private_runtime_state`/
     `_notes_log`/`_replies_log`、`community_table_bounded_shared_surface`），其中
     `scripts/community_partner_reply.py` 对 `sannai__{pid}.jsonl` 的直写单独标注为
     `community_shared_projection_cron_direct_ungoverned_duplicate`（见下方落差 #4/#6）。
  2. 测试断言同步为新文案。
  3. 顺带修复：`community_table.py`、`community_interest_garden.py`、
     `scripts/community_partner_reply.py`、`scripts/community_monitor.py` 中处理中文内容的
     `open()`/`write_text()`/`read_text()` 调用普遍缺失显式 `encoding="utf-8"`（依赖 locale
     默认编码），与项目既有约定不一致，全部补齐。
- **反事实覆盖**：CI 修复两项均有直接反事实——revert 8 处分类登记 → `write_surface_check`
  确定性 FAIL（`unclassified_count=8`）；revert 测试文案 → 确定性 FAIL（旧文案 assertion）；
  均已用 `git stash` 实测验证 revert→FAIL、restore→PASS。`encoding="utf-8"` 修复本身
  **无法**构造反事实——本机（Windows）与 CI（Linux）的 `locale.getpreferredencoding(False)`
  均已是 UTF-8，revert 后新增的往返测试仍然 PASS（已用 `git stash` 实测确认），判定同 BO
  记录的"无法反事实"类修复，纯 portability 加固，非行为回归。
- **实现落差记录**（仅记录，未改动，详见路线图 11.12.7）：`community_table.py`/
  `community_interest_garden.py`/`community_partner_runtime.py` 三个模块零调用方、零测试，
  实际跑在 cron 上的 `scripts/community_partner_reply.py` 是内联重写的独立副本——
  `_extract_topics()` 关键词集合已分叉；11.12.1 文档承诺的"每人每小时 ≤5 条"限流只存在于
  未被调用的 `community_table.py` 里，脚本的 `_write_table()` 无限流；脚本对
  `sannai__{pid}.jsonl` 的直写绕开了 `community_shared.write_shared_memory()` 的
  `actor=="sannai"` 门控。三处均未改动——`scripts/community_partner_reply.py` 是零测试覆盖、
  模块级代码 import 时即执行生产 config/roster 读取的自包含 cron 脚本，本次复审不具备验证
  该部署契约改动的宿主环境条件，属于"不动，只记录"。另确认 `community_snapshot.py` 新增的
  `unread_partner_replies`/`partner_reply_breakdown` 用两个语义无关的计数器相减（回复行数 −
  sannai_says.jsonl 读取游标），当前无消费者读取，尚未造成误导，未修——真正修复需要新增
  "回复已读游标"，属功能缺口而非 bug。
- **测试数量变化**：新增 5 个测试（`tests/plugins/memory/test_memory_os_community_table_and_interest_garden.py`，
  覆盖此前零测试的 `community_table.py`/`community_interest_garden.py` 往返 + 限流边界）。
  全量本地（Windows）**3039 passed / 3 failed / 13 skipped**——3 个 FAIL 均为既有环境伪影：
  2 个是 BK/BM 记录的 `test_memory_os_pytest_policy.py` skip-count 断言（经 stash 对照验证
  revert 后同样失败，与本次改动无关）；1 个是
  `test_execution_gate_runner_serializes_parallel_sidecar_updates`，全量套件下因并发资源
  争用（复审期间本机同时在跑 Edit 工具调用）偶发 FAIL，单独重跑与 stash 对照均 100% PASS，
  非本次改动引入的回归。import cycle（173 modules / 0 cycle）、write surface
  （163/163，`unclassified_count=0`）、static hygiene、public checkout probe（PASS）、
  `git diff --check` 全过。
- **附加发现（推送后从真实 GHA 复现，非本地可预见）**：分支推送后 push 事件触发的 CI 独立
  报了第三个 FAIL——`Reject whitespace errors in pushed range` 步骤，因为这是全新分支，
  `PUSH_BEFORE_SHA` 为全零，工作流回退为对空树 diff，暴露了 `community_partner_runtime.py`
  中原 Sannai 提交自带的 6 处行尾空白（非本次改动引入）——与 BL.1 记录的"新分支空树 fallback
  暴露历史文件尾随空白"同一根因。本地 `git diff --check` 此前只查未提交 diff（对 HEAD），未
  复现此路径；改用 `git diff --check "$(git hash-object -t tree /dev/null)" HEAD` 精确复现
  CI 命令后确认全仓库只有这 6 处，逐一清理（纯空白，`ast.parse`/`import` 验证无语义变化）。
  同一提交下 pull_request 触发的 CI（正确对 `main` 做 diff）已先于此发现独立跑 PASS，验证了
  两项核心修复在真实 Linux CI 上有效。
- **结论**：两项 CI FAIL（write surface、测试断言）+ 一项推送后发现的 CI FAIL（行尾空白）
  已修复；顺带加固字符编码一致性并为两个此前零覆盖模块补测试；三处实现落差（模块脱节、
  限流缺失、治理门控被绕开）与一处语义存疑指标已如实记入路线图 11.12.7，留待后续按记录中的
  两个方案之一收口，本次不重构生产部署契约。

---

## BQ — 将 community 模块整体迁出为独立仓库 sannai-community（2026-07-29）

- **触发**：用户要求把 Sannai 的社区功能（community）从 Hermes-Memory-OS 完整剥离，独立为新建的
  GitHub 仓库 `btnalit/sannai-community`，使 Hermes-Memory-OS 不再包含该模块；文档与自动化部署
  一并剥离。
- **调查结论**：community 模块对核心代码的耦合极浅——8 个模块文件（`community.py`、
  `community_shared.py`、`community_table.py`、`community_interest_garden.py`、
  `community_triggers.py`、`community_snapshot.py`、`community_partner_runtime.py`、
  `partner_create.py`）只依赖 `jsonl_io.py` 的少数工具函数（该文件本身零内部依赖，纯 stdlib，
  可整体 vendor）；`community_monitor.py`/`community_partner_reply.py`/`deploy_community.py`
  三个脚本零仓库内部 import，完全自包含。真正的集成点只有 4 处：`cognitive_loop.py` 的
  `_community_cycle` 步骤、`memory-os-agent-os` CLI 的 `community status` 子命令、
  `install_memory_os_plugin.py` 的 community 数据布局初始化、以及此前未被列入初始范围、经复核
  新发现的第 4 处——`state_overlay.py`/`state_overlay_schema.py`/`state_overlay_renderer.py`
  的 `community_snapshot` overlay 分区（`_community_inbox_dir` 辅助函数一并确认零其他调用方）。
  另确认 `partner_create.py` 未被任何 CLI 命令直接调用（只被测试和 `deploy_community.py` 引用），
  不构成额外集成点。
- **新仓库**：`sannai-community`（用户已建好的空仓库）首次提交把 8 个模块 + 2 个脚本（自包含，
  未改动）+ 一份整体 vendor 的 `jsonl_io.py` 组织为独立可安装包（`sannai_community/` 扁平包，
  相对导入不变，故模块本身零改动；仅脚本/测试的绝对 import 路径需要改写）；5 个 community 专属
  测试文件随迁（导入路径改写为 `sannai_community.*`），本地 59 passed。第二次提交把路线图
  `docs/resolver/hermes-memory-os-optimization-roadmap.md` §11（11.1–11.12.7，含 Sannai 本人
  撰写的 11.10《小院子》与 11.12《窗台/一起看/兴趣花园》）原文不改、编号不重排地迁为该仓库
  `docs/design.md`，README 记录已知实现落差（零调用方模块、cron 脚本内联分叉、
  `unread_partner_replies` 语义缺口——原样携带，未在迁移中"顺手修复"）。
- **Hermes-Memory-OS 侧移除**（本仓库，无残留钩子——不保留可选 import 接口，符合仓库既有的
  反 facade 抽象原则）：
  1. 删除 8 个模块文件、3 个脚本（含 `scripts/deploy_community.py`——其
     `COMMUNITY_MODULES` 清单混合了核心文件如 `cognitive_loop.py`/`state_overlay*.py`/
     `jsonl_io.py`/`cron_registry.py`/`legacy_right_brain_retirement.py`，未原样移植到新仓库，
     只删除；部署自动化随本次剥离退役，生产主机 hermes-media 上已部署的数据/cron 不受影响，
     未做处理）。
  2. `cognitive_loop.py`：移除 `_community_cycle` 方法与其步骤注册；连带清理仅供其使用的
     `hashlib` import。
  3. `plugins/memory-os-agent-os/__init__.py`：移除 `_ALLOWED_ALIASES` 的 `"community"`、
     `community` 子命令解析器与分发分支、`_community_command` 函数体。
  4. `scripts/install_memory_os_plugin.py`：移除 `SOURCE_COMMUNITY_DEPLOY`、
     `_initialize_community_layout` 函数与调用点、安装报告字典的 `community_layout`/
     `community_deploy` 键。
  5. `scripts/memory_os_write_surface_check.py`：移除 8 条 `community_*` 分类登记（保留
     其间穿插的 `execution_gate.py`/`runtime.py` 两条，未误删）。
  6. `state_overlay.py`/`state_overlay_schema.py`/`state_overlay_renderer.py`：移除
     `community_snapshot` overlay 分区的构建代码、schema 字段与 `to_dict()` 键、渲染器标签与
     `_SHORT_SECTIONS` 归属；连带清理仅供 `_community_inbox_dir` 使用的 `yaml` import。
  7. 删除 6 个 community 专属测试文件（`test_memory_os_community.py`、
     `test_memory_os_community_features.py`、`test_memory_os_community_hardening.py`、
     `test_memory_os_community_table_and_interest_garden.py`、`test_memory_os_partner_create.py`、
     `tests/scripts/test_deploy_community.py`）；修剪 2 个混合测试文件——
     `test_memory_os_cognitive_loop.py`（移除 community 相关 import、
     `test_community_cycle_deduplicates_persisted_candidate_reports` 整个测试函数、步骤名列表
     里的 `"community_cycle"` 一项、以及两条 `steps["community_cycle"]` 断言）与
     `test_memory_os_agent_os_shell.py`（移除 `community` 子命令解析断言片段）。
     `test_memory_os_community_hardening.py` 中的 `test_state_overlay_includes_community_projection`
     未随文件整体迁移——它验证的正是本次移除的 overlay 集成点，在新旧两个仓库都无处安放，直接
     删除，不迁移。
  8. 路线图文档：§11 标题与编号保留（供 §13/§14/§15 与本清单已有的 "11.x" 交叉引用继续解析），
     正文替换为迁移说明；仅删除 §15 中已过期的 community 相关一条结论（"社区给 Sannai 带来..."）；
     §13 的 R7 验收矩阵行、§14 当前优先级均保持不变，不臆造新内容替换（这两节涉及的是历史验收
     记录与优先级快照，删除或改写超出本次剥离范围）。本清单"待办"原第 4、5 两项（Track A
     模块落差、`unread_partner_replies` 语义缺口）随代码迁出，标注已随 BQ 迁移。
- **反事实覆盖**：`git grep -ril "community"`（大小写不敏感）在改动后的 Python 源文件中返回
  零命中，确认无残留引用会在 import 时报错；write surface check 的
  `allowed_count == surface_count`（151/151）确认没有留下指向已删除文件的失效分类条目
  （若漏删会在此处 FAIL，而非 `unclassified_count`，因为该项由 AST 扫描现存文件生成）。
- **测试数量变化（有意减少，非回归）**：全量本地（Windows）**3039 → 2968 passed** / 2 failed
  / 13 skipped——净减少 71，对应 6 个整体迁出的测试文件 + 2 个混合文件的定向裁剪；2 项 FAIL
  与 BK/BM/BO/BP 记录的同一 `test_memory_os_pytest_policy.py` skip-count 本机 `%TEMP%` 环境
  伪影一致，非本次改动引入。import cycle（165 modules / 0 cycle，此前 173）、write surface
  （151/151，`unclassified_count=0`，此前 163/163）、static hygiene、public checkout probe
  （`--strict`，`fail: []`）、`git diff --check` 全过。
- **未做的事**：未处理 hermes-media 生产主机上已部署的 community 数据/cron（按用户明确要求，
  本次只做仓库层面剥离）；未尝试修复 BP/11.12.7 记录的既有实现落差（原样迁移，随
  sannai-community README 一并携带）；`deploy_community.py` 未移植到新仓库（其模块清单混合
  核心文件，按旧仓库安装布局硬编码路径，移植等于重写一个未经验证的部署脚本，超出本次范围）。

## BR — 全项目审查（6 轮不变量切片）与整体修复（2026-07-30）

- **触发**：对 `47bbc13` 之后的整个项目做代码审查。首轮只覆盖了最后一次提交的 diff，遂按
  **不变量**（而非目录）重新切片，补做 5 轮横切审查：ExecutionGate 覆盖、无声失败/
  error_record、OwnerGate/ResolverGate 授权、治理 import 拓扑 + substrate 权威、
  手工维护的并行注册表。共 28 项发现，按文件所有权分 8 个互不重叠的包修复。
- **共同根因**：绝大多数发现是同一形状——**检查通过 ≠ 不变量成立**。`write_surface_check`
  在仓库内保证 `unclassified_count=0`，但写入面可以留在主机上；`import_cycle_check` 查环
  不查方向；多个测试断言的是自己手工维护的列表而非从单一真相源推导，列表漂移时照样绿。
- **已修（按严重度）**：
  1. **所有者授权绕过（安全，已实测复现）**：`owner_actions.py` 的 `_surface_action_token_map`
     从当前实时状态重算令牌，使 `require_recorded_digest=True` 对 `revoke_crystallized`/
     `demote_crystallized` 失效——仅凭一条 crystallized 记录的 `id` 即可离线算出
     `oa_<sha256(...)[:14]>` 并撤销该记录，全程无摘要投递。修复期间另发现**更严重的变体**：
     即使存在已记录摘要（生产常态，`binding == "latest_recorded_digest"`），伪造仍然成功——
     只按 `digest_not_found` 收口会在真实生产状态下留洞。改为按风险类**默认拒绝**（动作类型
     与目标类型都必须低风险），并删除 `token_match` 回退中重复的 `_surface_action_token_map`
     二次查找（否则刚被拒绝的令牌会被重新放行）。`apply_proposal`/`proposal` 经评估保留为
     digest-optional（已需 owner 批准 + OpsGate would_allow + 3 种受限 kind + 40 bit 提案 id
     后缀，且不在 CLAUDE.md 的 OwnerGate 永久边界清单内）。
  2. **ExecutionGate 许可证泄漏 ×2**：`runtime.py` heartbeat 中途抛异常则 envelope 永久悬空
     （已复现：1 条 permit、0 条 completion）；`cognitive_loop.py` 三条 lane 委托模块零异常
     保护。均按同文件既有正确范式（`spontaneous_expression_delivery`）在两个分支都收口。
  3. **substrate 自称权威**：`substrates/router.py` 仅凭 fact 自报的 `authority_class` 授予
     一级权威，不校验 `provider == "local_artifact"`。改为结构性校验并将伪造 fact 排除出
     返回集（检测遥测仍从未过滤的 `raw_facts` 计算，避免"丢掉内容就丢掉告警"）。
  4. **cron 注册表漂移（真实安装缺失）**：`ACTIVE_CLOSURE_CRON_KEYS` 与 dashboard 的
     core/optional 名单是 `MEMORY_OS_CRON_SPECS` 的手抄副本，`clearance_cycle` 从未被加入，
     全新 active-closure 安装**根本不会创建该 cron**。改为从注册表推导 + 显式声明有意排除。
     **`clearance_cycle` 本次仍不安装，但改为按名字显式排除并写明理由（延后启用）**：本次同
     一批改动修好了 `append_terminal(detail=...)`，使 `sweep_unavailable_open_proposals_on_flag_flip`
     （会**撤销**未决提案，就在 `clearance_cycle.py` 内）从"每次必抛 TypeError"变为真正可执行；
     若同时创建该 cron，等于让两条从未真正跑过的路径在 3.200 上同时上线，出问题无法归因。
     dashboard 侧同步标为 OPTIONAL（否则会对"我们故意不装的任务"永久报 missing_core WARN），
     并加了一条测试锁死两者一致性。**启用方式：删掉排除集里那一行即可**；漂移防护不受影响，
     新注册的 spec 仍不可能被静默漏掉。本次的关键区别是——遗漏必须是一个**决定**，而不是意外。
  5. **StateOverlay section 注册表六处重复**：改为从 `StateOverlay` dataclass 字段推导
     （`OVERLAY_SECTION_FIELDS`），标签/子集在 import 时断言穷尽；另发现并消除了第 7 处
     未被记录的内联副本。序列化输出键序逐字不变。
  6. **错误可见性**：`index.py` 构造 error_record 后丢弃不写（唯一一处）→ 改为经
     `append_audit` 落盘；`clearance_cycle.py` 追加缺字段记录且 `status` 恒为 `ok` → 改用
     `build_error_record` 并区分"部分失败/整批失败"；`session_mirror.py` 两处静默
     `except: continue` → 记录并经 `doctor()` 暴露。
  7. **community 主机侧退役**：`47bbc13` 只移除了仓库、没有反向操作，`_copy_tree` 是纯增量，
     已部署主机上的模块/数据目录/`deploy_community.py` 会永久残留。按
     `legacy_right_brain_retirement.py` 范式新增 `scripts/memory_os_community_retirement.py`
     （幂等、归档而非删除、dry-run 证明零写入、两阶段提交 + SHA256 完整性校验 + 写锁），
     并把 `community_monitor.py`/`community_partner_reply.py` 加入
     `RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES`（否则残留 cron 落入 `external_unmanaged` 而对
     monitor 完全不可见）。**未在任何主机执行**，是否执行由 owner 决定。
  8. **公开文档漂移**：路线图 §14「当前优先级」仍以现在时指示运维执行
     `build_community_snapshot()` 与 `community_monitor.py`（均已删除），§13 仍把 R7 社区
     列为在跑阶段——已改为迁出说明并保留原文，指向 sannai-community。
  9. **pytest 版本漂移（红→绿）**：`test_memory_os_pytest_policy.py` 两处断言把随 pytest
     版本变化的 `skip_count` 当作不变量（8.4.2/Windows 下单个 module-level skip 计为 2）。
     改为断言真正的不变量（collect 阶段 skip 全部被判为 unknown、`status=fail`、returncode
     非 0），而非附带计数。这两个失败是 BQ 记录的既有伪影，本节将其真正修复。
- **交接期间自查发现的两个额外问题**（3 个 agent 因额度中断，由主会话接手完成）：
  - `append_terminal(detail=...)` 根本不接受 `detail` 参数（`permanent_promotion.py:485-495`），
    旧代码每次 sweep 都抛 `TypeError`，被宽 `except` 吞掉并写入畸形记录，函数还返回硬编码
    `status: "ok"`——即 `sweep_unavailable_open_proposals_on_flag_flip` **从未成功清扫过任何
    提案**。这是"无声失败"不变量的教科书式印证。
  - 包切分本身引入一处跨包回归：`test_memory_os_plugin_install.py` 里硬编码 `== 19` 与 19 个
    job 名字面量（cron 注册表的第 4、5 份副本）属于 F 包白名单，而改变数量的是 E1 包，E1
    无权修它。**教训：按文件所有权切包时，行为变更与其测试可能不在同一个包里。**
- **反事实覆盖**：每项修复均有"撤销修复即失败"的测试并经实际验证（本轮统一改用仓库外文件
  复制回退，不用 `git stash`——8 个 agent 共享同一 worktree 时 stash 栈跨 worktree 共享，
  裸 `pop` 可能恢复他人暂存内容）。关键新增：envelope 账本在错误路径上必须有 completion
  记录（旧测试只断言 audit 与 heartbeat_state，从不读 `execution_gate_envelopes.jsonl`）；
  伪造 fact 必须被排除出 `facts`（旧测试只断言违规标志位翻转）；新增 cron spec 未分类必须
  测试失败；error_record 发射组件必须全部登记（从源码推导 30 个发射者）。
- **测试与静态门**：全量本地（Windows）2968 passed / **2 failed** → **3023 passed / 0 failed**
  / 13 skipped（+55，563s），**本仓库首次全绿**。静态门全过：import cycle 0 环、write surface
  `unclassified_count=0`、static hygiene、public checkout probe `--strict`（exit 0）、
  `git diff --check`。
- **未做的事（明确记录，非遗漏）**：
  - `oa_` 令牌密钥化（纵深防御）未实施：需向 `_action_token` 贯穿 `roots`（约 45 处，单点
    遗漏会导致 digest cron 与 gateway **静默**产生不一致令牌）、令牌格式被 4 个白名单外文件的
    正则锁定、且失败策略需要 `error_registry` 错误码与 monitor 字段。已实测的攻击面已由第 1
    项完全关闭；未做半迁移。
  - monitor 11 个组件的 snapshot 采集未接线（这些组件根本没有 snapshot payload，接线属于对
    大型生产 monitor 的采集改造且无法离线验证）。改为把缺口**显式化且可测**：新增
    `component_coverage.unaggregated_components`，并用从源码推导发射者清单的测试防止新增
    发射者继续静默扩大盲区。
  - `_configured_mailbox_root` 在 `signal_collectors.py` 与 `plugins/modules/messaging/mailbox.py`
    逐字重复：合并需要从 portable module 反向 import memory_os 核心，越过模块边界，故有意
    接受重复并在此登记。
  - `error_registry.py` 零注册错误码（所有 code 经 `unregistered_error_code(...)` 落到
    `production_severity="unknown"`）；`candidate_aggregation.py` 三处
    `start_resolver_auto_approve_envelope` 后的写入无异常保护（与第 2 项同类，白名单外未修）。
  - 主机侧：未触碰 hermes-media / hermes-feiniu。

## BS — Hermes cron 归类合并：19 job → 8 group tick（2026-07-31）

### 做了什么

把 `MemoryOSCronSpec` 拆成两张表，只合并调度面、不动治理粒度：

- **lane 表**（`MEMORY_OS_CRON_LANES`，21 条）＝ 治理身份：`lane_id` / `raw_script` /
  `helper_kind` / boundary 契约。每 lane 每次运行仍开自己的 ExecutionGate envelope。
- **group 表**（`MEMORY_OS_CRON_GROUPS`，9 条）＝ Hermes 调度面，真正被
  `hermes cron create` 创建的东西。

`MEMORY_OS_CRON_SPECS` 是两表的 join，`name`/`wrapper_script`/`schedule_arg` 从 group 派生，
因此既有消费者全部无改动继续工作，唯一可见差异是多条 spec 共享同一个 `name`。

active-closure：**19 个 Hermes cron job → 8 个**（19 条 lane 不变）。
新增 `scripts/memory_os_cron_group_runner.py` + 4 个 tick shim。

### 根因（为什么必须合并，不是审美问题）

按 schedule 实算一天的触发时刻：**00:00 与 12:00 各有 5 个 job 同时触发**
（proposal_followups / candidate_aggregation / fact_judge / index_sync / l3_probe），
5 个进程同时对 `execution_gate_index.json` 做「独占加锁 → 全量读 → 全量重写 → fsync」，
锁超时 15s。超时即 `ExecutionGateInfrastructureError("sidecar_lock_timeout")` → runner 返回 3
→ 该 lane 当次无 completion 记录 → monitor 记 `helper_completion_missing`。
合并后触发次数 336/天 → 172/天。
**并发数更正（2026-07-31 部署后实测）：是 5 → 3，不是最初写的 5 → 1。**
三个 tick 的 cron 表达式在整点重叠（`*/15`、`*/30`、`0 * * * *` 都命中 `:00`），
每小时整点仍有 3 个 group runner 同时启动（09:00 为 4 个）；3.200 日志显示三者
在 `2026-07-31 20:00:56 CST` 同秒触发。真正拆掉 15 秒锁超时风险的是
`prune_sidecar_index()` 把单次重写成本从无上限增长压成有界 O(2000)，而非并发降为 1。
错开三个 tick 的分钟即可彻底消除碰撞且不影响任何 lane 节奏——见方案文档 §10，未实施。

### 阻断性前置条件（两条，先做才安全）

**R1 — monitor 新鲜度窗口必须按 lane 取。**
`_helper_completion_freshness_window()` 原本取 cron **job** 的 schedule。分组后用公式实算，
**4 条 lane 的窗口会塌缩**：working_cleanup 342h→54h、hindsight_advisory_digest 342h→54h
（两条必然永久 stale）、candidate_aggregation 18h→12h、fact_judge 14h→12h（略晚即误报）。
改为取 lane 自己的 `due_interval_minutes`，缺失/0/非法值回退到原 schedule 行为（绝不产生 0 窗口）。

**R2 — 19 个旧 per-lane job 名必须显式分类。**
分组后 spec.name 变成 group 名，`known_specs_by_name` 不再认识 `memory-os-index-sync` 这类
旧名字 → 落入 `unregistered_like` → monitor FAIL
`execution_gate_memory_os_cron_unregistered_like_job`，每台已升级主机都会红。
新增 `LEGACY_PER_LANE_CRON_JOBS`，归入 `known_optional` + `superseded_by_group_tick`。

### 顺调用链发现的同类缺陷（Section W 第 5 条的产出）

1. **`classify_hermes_cron_jobs` 有三份拷贝。** 只修 `hermes_cron_adapter.py` 不解决生产问题——
   `memory_os_cron_adapter_probe.py` 导入的是 `plugins/seam/hermes_memory_os/cron_adapter.py`，
   而 monitor 优先读该 probe；monitor 自身还有一份内嵌 fallback。三份全部同步修复。
2. **`memory_os_monitor_dashboard_snapshot.py` 的 CORE/OPTIONAL 集合会重叠。**
   `tick_evidence` 同时含 core 成员（fact_judge）与 optional 成员（l3_probe_verification），
   同一 job 名会既算 missing_core 又算 optional_paused。改为「任一成员 core ⇒ 整个 job core」。
3. **两处仍在直接创建 per-lane job，会导致 lane 双跑：**
   `install_memory_os.sh` 自建 `memory-os-working-cleanup`（已删除，onboarding 是唯一创建者）；
   `deploy_l3_probe.py --apply` 自建 `memory-os-l3-probe-verification`（改为 fail-closed
   `superseded_by_group_tick`，并删掉随之失效的 apply 主体与两个孤儿函数）。
4. **`execution_gate_index.json` 无任何裁剪**（独立缺陷，本次一并修）：每次 permit/completion
   全量重写，entry 按 envelope 无上限增长（约 336/天 ≈ 12 万/年）。新增
   `prune_sidecar_index()` 保留最新 2000 条；安全性依据是 `execution_gate.py` 已有
   lookup-miss 时从 JSONL 全量重建的恢复路径。正在写入的 envelope 永不被淘汰。

### 一并加固

- `subprocess.run` 原本**没有 timeout**。1:1 时一个 hang 只拖垮一条 lane，合并后拖垮整组。
  新增每 member `timeout_seconds`，超时记 `execution_status="timeout"` / returncode 124 后继续下一个成员。
- group 级**非阻塞**锁：抢不到锁以显式 `skipped_overlap` 退出 0，不静默 pass。
- 成员失败隔离：逐 member try/except + 独立 completion，单成员非零不终止后续成员。
- lane 级停用 `cron_lane_disabled.json`（补回分组后 owner 丢失的单 lane 停用能力），
  tick runner 与 monitor 同时读取；文件损坏时 fail-open，绝不静默停掉受治理的 lane。
- `due_policy="calendar"`：`v3_seed_evidence` 按 `natural_date` 分区并暴露
  `consecutive_valid_day_count`，elapsed 门控可能跨 UTC 日界漂移导致漏算/重算，故按日锚定。
  逐个核对过其余 lane：`exposure_rollup` 是水位线驱动且幂等、`working_cleanup` 纯年龄判定，
  均可用 elapsed。
- `trigger_surface` 保持字面量 `"hermes_cron"`：已核实 `resolve_trigger_class()` 只读环境变量
  `MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID`，tick runner 逐 member 设置该变量，natural_cron 溯源不受影响。

### 反事实覆盖

- R1：weekly lane 落在日频 group 时不得判 stale（无修复时窗口 54h → FAIL）。
- R2：遗留 per-lane job 必须 `unregistered_like == 0`（无修复时为 2 → monitor FAIL）。
- 超时：member `timeout_seconds=1` + sleep 30 的 stub，必须得到 status=timeout/returncode=124
  且后续成员仍执行（无 timeout 支持时该 member 会正常返回 0）。
- 重叠：预先持有 group 锁，必须得到 `skipped_overlap` 且**不产生任何 envelope**。
- 隔离：前一个成员 exit 9，后一个成员仍须 ok 且两条 completion 都在。
- due 门控：30 分钟 lane 在 15 分钟 tick 上必须隔次运行；`due_interval_minutes=0`
  不得退化为「每 tick 都跑」（回退为日频）。
- calendar：同一 UTC 日内第二次 tick 必须 `already_ran_today`；未到 anchor 必须
  `before_calendar_anchor`。
- v0 快照回填：旧快照无 due 元数据时必须回填 lane 表的值，不得得到 0（否则 tick 永远 due、
  monitor 永远 stale）。
- 裁剪：正在写入的 envelope 即使时间戳最旧也不得被淘汰。
- 双跑：`deploy_l3_probe.run_apply()` 必须 blocked 且不产生 jobs.json。

R1/R2 的 revert→FAIL→restore→PASS 已实际验证。

### 测试与门禁

3023（BR 基线）→ **3058 passed / 13 skipped / 0 failed**，净 +35。
新增 `tests/scripts/test_memory_os_cron_group_runner.py`（14 项），
另在 `test_memory_os_l3_probe_repo_root.py` 补 2 项双跑守卫。
四项静态门全过：import_cycle / write_surface（unclassified=0）/ static_hygiene / public_checkout_probe。

### 回滚

onboarding 只**暂停**旧 19 个 per-lane job，不删除。回滚 = 重新启用旧 job + 停用 8 个 group job；
lane 注册表与 helper 脚本全程未动，回滚后行为与合并前一致。

**旧 per-lane gate shim 是回滚基础设施，故意保留、不删除。** 被暂停的旧 job 其 `script` 字段
指向 `memory_os_cron_<lane>_gate.py`，删掉这些 shim 会让回滚（重新启用旧 job）直接失败。
因此 `_write_execution_gate_assets()` 只写当前 group 的 wrapper、不清理旧 shim，
`install_memory_os.sh` 也继续安装 `memory_os_cron_working_cleanup_gate.py`——
这一条是有意为之，不是清理遗漏。只有旧 job **创建逻辑**被移除
（`install_memory_os.sh` 的自建 cron 块、`deploy_l3_probe.py --apply`），
因为那才是导致 lane 双跑的部分。

### 未做 / 残留

- 尚未部署到 3.200，`live_monitor_pass` 未取得——本次仅 `local_pass` + 静态门。
- `v3_journal_sweep` 的底层模块未逐行核实是否按日分区，暂按 elapsed（1440 min）处理；
  若后续确认按日分区，改成 `due_policy="calendar"` 即可，无需动结构。

---

## BT — 3.200 定向部署结果与部署后发现（2026-07-31）

BS 的 cron 合并已由 3.200 主机执行定向部署（非 full deploy）并验证。**BS 遗留的
「未部署、live_monitor_pass 未取得」一项就此关闭**，但闭环仍未全绿，原因与本次改动无关。

### 已取得的生产证据

- 生产 cron registry 升级为 `memory-os.cron_registry.v1`，19 active lane specs / 8 groups。
- 三个 tick（derived / governance / evidence）由**真实 Hermes scheduler** 于
  `2026-07-31 20:00:56 CST` 自然触发并返回 ok；组内未到期 lane 正确返回 `skipped_not_due`——
  **due gating 在生产上得到验证，不是重复执行**。`tick-daily` 已启用，首个自然窗口为每日 00:05。
- 旧 per-lane job 按设计**暂停而非删除**，回滚路径保留。
- Unregistered Memory-OS jobs = 0、naked jobs = 0、active cron helper completion missing = 0
  —— R2（旧 job 名分类）与 R1（新鲜度按 lane）在生产数据上均未触发误报。
- 63 个目标文件与 GitHub HEAD 字节级一致，配置文件未被改动，备份可校验。

### Monitor 仍 FAIL，但与本次改动无关

唯一 FAIL 是 `v2_exposure_schema_era_unhealthy`。已核对 `memory_os_3_200_monitor.py`：
该码由 `snapshot["v2_exposure_monitor"]["schema_era_health"] == "FAIL"` 驱动，
判定的是自然生产记录里的 schema-era 归因缺口 / 守恒断裂 / 遥测退化，
与 cron 调度面无耦合。生产数据：观测 17.4/30 天、schema-era 分类率 0.6506、
归因缺口 66、exposure rollup 滞后 67.9h、**守恒失败 0**、下游 clearance 正确冻结。
滞后 67.9h ≈ 2.8 天，早于本次部署时点，属既有数据成熟度问题。

### 部署后发现（未修复，登记为待办）

**installed-layout import shadow 又出现一例，且是一类而非孤例。**

`deploy_l3_probe.py` 在生产副本上从中立工作目录执行时报
`ModuleNotFoundError: No module named 'plugins.memory'`：它无条件把
`Path(__file__).resolve().parents[1]` 插入 `sys.path`，在安装布局下该路径是
`$HERMES_HOME`，其 `plugins/` 目录会遮蔽 memory-os runtime 命名空间。
主机侧已只在生产副本加 runtime bootstrap（未推开源仓库），因此**仓库缺陷仍在**，
且生产上多出一处有记录的本地覆盖。

按 Section W 第 5 条全项目 grep 同一模式，`scripts/` 下**共 4 个脚本**有硬顶层
`from plugins.*` 导入 + 无条件 REPO_ROOT 插入、且缺少 29 个兄弟脚本都有的
runtime 回退分支：

- `deploy_l3_probe.py`（已在生产暴露）
- `memory_os_blank_host_smoke.py`
- `memory_os_export_shadow.py`
- `memory_os_queue_consolidated_candidate.py`

（`memory_os_cron_group_runner.py` 与 `memory_os_execution_gate_runner.py` 虽也无显式
runtime 插入，但两者都是「快照优先 + try/except 软失败」，不受影响，无需改动。）

修复方式与 `memory_os_exposure_rollup.py` 等既有脚本一致：条件判断 repo 布局，
否则回退 `$HERMES_HOME/memory-os/runtime/python`。修完后生产可撤掉本地覆盖。

这与路线图早先记录的「cron adapter installed-layout import shadow」是同一类缺陷。

### 两处刻意未扩大的边界（主机侧决定，非本次改动遗漏）

1. **未重启 Gateway**：当前 Gateway 仍是 7/29 启动的进程。cron 与 timer 都是新进程，
   fresh-process provider 导入也已验证，因此 cron 合并确实生效；但不能宣称旧 Gateway
   PID 内的模块缓存已重新加载。
2. **未执行 Community 数据归档迁移**：代码层已退休，`/root/.hermes/memory-os/community/`
   数据仍原地保留，无 `community_retirement.json` manifest。归档会移动用户数据，
   不在本次部署授权范围内。

---

## BU — BT 两项发现的修复（2026-07-31）

BT 登记的两项部署后发现全部修完。

### 1. tick 分钟错开：同分钟并发 3 → 1

BS 最初宣称的「并发 5 → 1」实际只做到 5 → 3（BT 已更正）。根因是三个 tick 的
cron 表达式在整点重叠（`*/15`、`*/30`、`0 * * * *` 全部命中 `:00`）。

现错开为 `2,17,32,47` / `7,37` / `12`（`tick-daily` 与四个 owner 作业未动）。
**实测同分钟最大并发 3 → 1，触发次数保持 172/天不变**——错开只动分钟不动频率，
各 lane 的有效节奏本就由 `due_interval_minutes` 决定，与 tick 落在哪一分钟无关。

测试断言全部改为**从注册表派生**（不再写字面 schedule），并新增两条不变量：

- `test_no_two_group_jobs_start_in_the_same_minute`
- `test_every_tick_fires_at_least_as_often_as_its_fastest_installed_lane`
  —— 比较对象是 active-closure **实际安装**的 lane。写这条时它先失败了一次：
  `clearance_cycle` 声明 10min 而 `tick-governance` 是 30min。但该 lane 处于延后状态、
  并不安装，所以正确口径是「已安装成员」。这条同时成为激活 `clearance_cycle` 时的绊线——
  届时若不把该 tick 提速会立即失败。

### 2. installed-layout import shadow：4 个脚本

`deploy_l3_probe.py`、`memory_os_blank_host_smoke.py`、`memory_os_export_shadow.py`、
`memory_os_queue_consolidated_candidate.py` 全部改为与 29 个兄弟脚本一致的条件式
bootstrap：仓库布局下用 repo root，否则回退 `$HERMES_HOME/memory-os/runtime/python`。

**BT 里「共 4 个」的说法要修正**：那是用宽松启发式扫出来的。改用严格正则复扫后，
无条件插入 `parents[1]` 的其实是 7 个，另外 3 个是
`deploy_memory_os.py`、`install_memory_os_plugin.py`、`memory_os_boundary_runtime_probe.py`。
这 3 个**只从仓库检出运行、不随安装分发到主机**，`parents[1]` 就是 repo root，
因此现状是正确的，未改动。

同时发现最初判为「缺回退」的 `memory_os_candidate_aggregation_lane.py`、
`memory_os_fact_judge_lane.py`、`memory_os_ragflow_readonly_probe.py` 其实都没问题——
前两个直接指向 runtime root（安装布局专用），第三个用的是条件式但检查的是
`plugins/seam/external_evidence`。**是我的检测式过严产生了假阳性，不是它们有缺陷。**

新增 `tests/scripts/test_memory_os_installed_layout_imports.py`（5 项）：

- 两条静态不变量：已分发脚本不得无条件插入 `parents[1]`；
  且**豁免是被验证的而非被断言的**——从 `install_memory_os_plugin.py` 自己的
  `SOURCE_* = REPO_ROOT / "scripts" / "x.py"` 声明里读出「已分发集合」，
  那 3 个仓库侧工具一旦开始被分发，测试立刻失败。
- 端到端：在真实遮蔽布局（`$HERMES_HOME/plugins/` 无 `memory/` 子包 +
  `memory-os/runtime/python/plugins/` 放真包）下从中立 cwd 执行脚本，
  断言不再出现 `No module named 'plugins.memory'`。
- **反事实**：把旧 bootstrap 塞回脚本副本，断言同一夹具**确实**能复现该报错——
  否则前一条可能只是因为夹具根本没遮蔽而空过。

端到端断言刻意只判「遮蔽错误消失」，不判 returncode 0：这些脚本会继续导入更深的
memory-os 包，需要 Hermes agent runtime（`agent` / `memory_os_agent`），CI 无此依赖，
属既有环境限制。能走到那一步本身就证明 `plugins.memory` 已解析成功。

修复后生产可撤掉 `deploy_l3_probe.py` 的本地覆盖，漂移归零。

### 测试与门禁

3058 → **3066 passed / 13 skipped / 0 failed**（净 +8：installed-layout 6 项 + cron 不变量 2 项）。五项静态门全过。

### BU.1 — CI 红：该测试在 CI 上是**空过**的（同日修复）

BU 的 installed-layout 测试本机全绿，CI 却红在反事实那条：
`assert "No module named 'plugins.memory'" in ''` —— stderr 是**空的**，
即塞回旧 bootstrap 也没报错。

根因：**CI 跑 `pip install -e '.[dev]'`**（`.github/workflows/ci.yml:28`），
仓库以 editable 方式装进 site-packages，于是 `plugins` **无论脚本怎么摆弄 sys.path
都能导入**。本机没装 editable，所以复现不出来。

这意味着不只是反事实那条会挂——**正向那条在 CI 上同样是空过的**：
它"通过"是因为 editable install 提供了 `plugins`，而不是因为 bootstrap 修对了。
一条恒绿却什么都不证明的测试，比一条红的更危险。

修复：子解释器加 `-S -E` 隔离。`-S` 跳过 site-packages（editable install 就在那儿），
`-E` 忽略 `PYTHON*` 环境变量；`HERMES_HOME` 不是 `PYTHON*` 前缀所以照常传入，
再配合中立 cwd 让仓库检出也不可见。

三点加固，防止再次空过：

1. **新增前置条件测试** `test_installed_layout_fixture_is_isolated_from_ambient_packages`：
   断言在该隔离下 `import plugins.memory` **必须失败**。若哪天隔离失效，
   这条会带着明确信息先挂，而不是让整个文件静默空过。
2. **正向断言改为positive**：不再只判"遮蔽报错不存在"（这也可能是脚本更早就死了），
   改判 traceback 里出现 `$HERMES_HOME/memory-os/runtime/python/plugins/` 路径——
   能走进 runtime 树里的模块，才证明确实从那里解析。
3. **本机用一次性 venv 复刻 CI 条件验证**（`pip install -e .` + pytest）：
   确认 editable install 下 `plugins.memory` 确实可被环境直接导入、`-S -E` 能切断它；
   并把**上一版测试文件**放进该 venv 跑，复现出与 CI 完全一致的失败，
   新版 6 项全过。验证完删除 venv。

教训：**跨环境的测试必须验证自己的前置条件**。本机能复现 ≠ CI 能复现；
当测试依赖"某模块不可导入"时，那个"不可导入"本身就是必须断言的前提。

---

## BV — 对 `6273e8b` 的代码评审与修复（2026-07-31）

本机对齐 GitHub 后发现 `6273e8b`（keep recall and onboarding lanes live）尚未被任何评审节
覆盖——清单最后一条记录停在 `3dbbb9b..HEAD`（BU.1）。逐项复审得 13 项发现：修 10 项、
有意保留 1 项、显式记录不做 2 项。

### 0. 该提交打破了 Windows 本机全绿基线，且推送前未被发现

评审前实测基线：3077 passed / **1 failed** / 13 skipped，唯一失败的就是它自己新增的
`test_execution_gate_asset_install_is_idempotent_in_installed_layout`——
`assert stat().st_mode & 0o100` 在 Windows 上恒为 0（`chmod` 的执行位在 Windows 无效，
`st_mode` 实测 `0o100666`）。CI 是 Linux 故绿、本机红，与 BU.1 的「CI 空过、本机绿」
**互为镜像**，同属"跨环境测试不验证自己的前提"。BR 刚拿到的「首次全绿」被这一条打掉。
改为 `_assert_executable_bit()`，`os.name == "nt"` 时跳过（沿用本文件已有的 nt 分支惯例）。

**这首先是一条流程发现，不只是可移植性疏忽**：一条本机必红的测试被推送上了 main，
说明 Definition of Done 第 4 步（"绝不允许只跑自己新增/修改的测试就推送"）在本次没有执行，
或只在 Linux 一侧执行。本清单存在的意义正是记录这类流程缺口——`st_mode` 的技术解释是次要的。

### 1. `apply_canary` 上「关闭开关过期 = 静默恢复输出改写」（最重一项）

本提交把 `prefetch_facade_enabled` 的解析默认值从 `False` 翻成 `True`，理由是「durable mode
才是权威，不该被临时 override 的过期拖死」。这对 `shadow` 成立——它是 output-neutral 的，
只落 metadata-only 的 Recall Plan。

但 `apply_canary` **会往 live prefetch 追加 `Recall Facade (unified)` 段**
（`prefetch.py:636`）。而 `resolve_knobs` 对 active + provisional + **已过期** 的记录是
`continue` 跳过、回落到调用方默认值（`knob_overrides.py:491`）。于是在 `mode=apply_canary`
的主机上，Owner 挂的一条 provisional `false` 关闭开关一旦到期——无文件写入、无重启、
无任何 Owner 动作——输出改写就静默恢复。**这正是本提交所修 bug 的镜像**；它自己的
`test_expired_false_kill_switch_reenables_without_file_change` 断言的就是这个"到期即恢复"，
只是仅覆盖了 `shadow`。

新增 `_recall_facade_switch_default(mode)`：`shadow → True`（保住观测车道，即本提交本意），
`apply_canary → False`（输出改写必须有显式且未过期的正向授权）。该默认值一并纳入缓存指纹，
防止跨模式串用缓存。生产 3.200 当前为 `shadow`，本项无生产行为影响。

### 2. kill switch 的存储路径自行拼装 = fail-open

`__init__.py` 手工拼 `roots.memory_os_root/"system"/"knob_overrides.jsonl"`，绕开
`_override_store_path()`。两者一旦分叉，`stat()` 抛 `FileNotFoundError` → 旧代码直接
`resolved = True` 返回，**根本不调用解析器**，即 Owner 的 kill switch 被无视。
一个未被强制的耦合，失败方向却是 fail-open——治理开关最不能容忍的方向。

改为走新增的公开访问器 `knob_overrides.override_store_path()`，并**删掉「文件不存在 →
直接 True」的短路**：文件不存在只是「没有 override」，答案仍须由解析器套用默认值给出
（`_validate_recall_facade_override_store` 相应改为容忍不存在的 store，否则会把
"无 override" 误判成校验失败而 fail-closed，反向踩坑）。

### 3. 两个抑制错误计数器不走项目的 `error_record` 契约

`_recall_facade_init_errors` 全仓库**只写不读**，注释却写着 "recorded as suppressed count
for monitor visibility"——不实。`_recall_facade_knob_errors` 只出现在 status，
而 monitor 对 `recall_facade` 零命中。同一特性里相邻的 `prefetch.py:640` 反而是对的
（`build_error_record(component="prefetch_facade", ...)` 汇入 `suppressed_error_count`）。

本次：两个计数器都在 status 暴露（新增 `init_error_count`）、修正不实注释。
**monitor 接线有意未做**并登记为遗留——新增一个 WARN 码需要分类表注册 +
`fail_if_production` 判定 + clean-host 分档，属独立一轮；与 BR 记录的
「monitor 11 组件采集接线」同族缺口。

### 4. status 无法区分「被 Owner 关掉」与「mode 本来就 off」

`kill_switch_enabled` 在 `mode=off` 时同样渲染 `false`，读起来像「有人把车道杀了」；
`effective_enabled` 则是它的纯重复字段。新增 `mode_live` 让两种状态可分辨，
`effective_enabled` 改为显式合取。（`effective_enabled` 在构造上仍与 `kill_switch_enabled`
数值相等，真正消歧的是 `mode_live`；该字段属已落地 schema，未删。）

### 5. `_roots is None` 分支污染 init 哨兵

该分支把 `_recall_facade_initialized` 置 True。哨兵语义是「构造已跑过」，在这里置真会让
roots 事后注入之后 facade **永久返回 None**——一个哨兵表达两件事（Section W 规则 4）。
已去掉置真。

### 5.1 缓存的 facade 会被以另一个 arbitration mode 交付出去

顺着第 5 项的调用链继续查出来的：`RetrieverFacade` 在**构造时**固化
`_arbitration_mode`，而 `_recall_facade_initialized` 会在重新应用模式之前短路返回缓存对象。
于是 `shadow` 下构造好的 facade 会被交给 `apply_canary` 的调用方（反之亦然），
**跑的车道与 config 声明的不一致**。实测复现：翻转 mode 后拿到的对象
`_arbitration_mode` 仍是 `shadow`。

（本次为 `apply_canary` 引入的按模式取默认值已让 *开关缓存* 在模式翻转时失效——
`default_enabled` 是指纹的一部分——但 *facade 对象* 本身不受该指纹保护，是独立的一条。）

新增 `_recall_facade_mode` 记录构造时的模式，两处 `initialized` 短路都加上模式一致判断。

**5.1 的修复自身引入了一个新暴露，在合并前自审中发现并修掉**：原实现里
`self._recall_facade` 一生只赋值一次（`initialized` 置真后永不重建），所以"半注册状态"
不可能被观察到；加了模式变更重建之后，`self._recall_facade` 会被**就地替换**，而另一线程
可能正持着上一次构造留下的 `initialized=True` 在锁外读它——于是读到一个尚未 register 完
的 facade。改为先构建到局部变量、注册完成后再按 `facade → mode → initialized` 的顺序发布
（模式先于哨兵，保证看到 `initialized=True` 的读者不会读到过期模式）。
教训：**给一个"只写一次"的字段加上重建路径，等于把它变成共享可变状态**，
原本成立的免锁读假设会随之失效。

### 6. onboarding 的 wrapper 分支无覆盖

`_write_execution_gate_assets` 有**两处** `_copy_asset_if_distinct` 调用（runner 循环 +
group tick wrapper 分支），而新测试传 `specs=[]`，只跑到第一处。反事实实测：把 wrapper
那处改回 `shutil.copy2`，全套仍绿。新增
`test_group_tick_wrapper_install_is_idempotent_in_installed_layout` 覆盖第二处——
反事实下 Windows 报 `PermissionError [WinError 32]`、Linux 报 `SameFileError`，
同一个自我复制缺陷。

### 7. 150ms 到期测试是墙钟 flaky

`test_expired_false_kill_switch_reenables_without_file_change` 的 150ms 窗口要覆盖一次
治理 JSONL 写入 + provider 构造 + `stat` + 全量 `read_text` + 反向重扫，才轮到**第一条**
断言。在产生过 BO 抖动的 mount-isolated GHA runner 上过窄；一旦超时，解析回落到新默认值
`True`，`assert ... is None` 直接失败。窗口放宽到 3s，sleep 由实测已耗时反推。

### 8. 有意保留：严格校验取全账本口径

`_validate_recall_facade_override_store` 对**任意**坏行/非 dict 记录抛错，包括与本旋钮
无关的记录；而解析器自己的 `_read_jsonl` 是**静默跳过**的。这条不对称真实存在，
但**保留 fail-closed**：坏行无法归属到具体旋钮，把它当治理存储损坏比静默跳过更安全；
且改它等于推翻本提交刚落地的 `test_malformed_json_kill_switch_store_fails_closed`。
已在 docstring 写明这是有意与解析器不同，可见性由第 3 项兜底。

### 9. 记录不做：缓存的热路径前提弱于其自述

`prefetch()` 在 `_ensure_recall_facade()` 之前**已经**有两次未缓存的全账本 `resolve_knob()`
（`lane_low_clue_recall_enabled`、`session_scoped_recent_events`）。为省下第三次读而引入
~90 行缓存机制（stat 指纹 + RLock + 到期追踪 + 严格校验 + 路径重复 + fail-open 分支），
其热路径理由因此**明显弱于自述**——缓存确实省掉了每次 prefetch 的一次读，
但"governed file I/O 不能上热路径"这个前提在同一函数里已经被违反两次。
`resolve_knobs()` 本就是为「一次读、N 个旋钮」而存在，
把三者合并会把热路径 I/O 从 2 次降到 1 次，并顺带删掉缓存、锁与第 2 项的路径重复。
**本次未做**：这是对热路径的设计改动、牵涉另外两个旋钮各自的既有测试，应单独一轮。

### 反事实覆盖

第 1、2、5、5.1、6 项各用 revert→fail→restore→pass 实测：

- 去掉 `_recall_facade_switch_default` 的模式判别（恒 True）→
  `test_expired_false_kill_switch_does_not_reenable_output_mutating_canary` FAIL。
- 恢复手工拼路径 + 「文件缺失→True」短路 →
  `test_kill_switch_is_read_from_the_resolver_owned_store_path` FAIL。
- 恢复 `_roots is None` 的哨兵置真 →
  `test_roots_injected_after_a_rootless_call_still_builds_the_facade` FAIL。
- 去掉两处模式一致判断 →
  `test_cached_facade_is_not_served_under_a_different_arbitration_mode` FAIL
  （报出交付的是 `shadow` facade）。
- wrapper 分支改回 `shutil.copy2` → 新增的 wrapper 测试 FAIL。

（过程教训：第 5.1 项的第一次反事实是**假通过**——patch 脚本因缩进前缀互为子串而
`assert count == 1` 中断、根本没改文件，测试自然仍绿。反事实必须确认补丁真的落了盘，
否则"通过"证明的是补丁没生效，不是修复没必要。）

另修掉该测试类原有**两条空过测试**：裸 `MemoryOSProvider()` 的 `_roots is None` 会在任何
mode/knob 逻辑之前返回，`test_facade_initialized_once_and_cached` 断言的是 `None is None`，
`test_facade_returns_none_when_knob_disabled` 从未走到旋钮、其 docstring
（"Default: prefetch_facade_enabled=False"）在本提交后已是错的。两条均补注 roots 与 mode
后才真正成立，后者改名为 `test_facade_returns_none_when_no_durable_mode_configured`
（覆盖"config 完全不提这条车道"，与已有的显式 `mode: off` 用例区分）。

### 同类模式全项目扫描（Section W 规则 5）

- 手工拼 `knob_overrides.jsonl` 路径：仅 `knob_overrides.py` 自身（属主）与
  `memory_os_vector_retrieval_benchmark.py:489`（写自建 fixture store，非 watcher），无同类缺陷。
- 测试里断言执行位：仅本次修正的一处。
- 亚秒级 sleep/到期：另两处（`test_memory_os_legacy_right_brain_retirement.py:347`、
  `test_memory_os_monitor_perf.py:23`）失败方向安全——前者断言 writer **仍被阻塞**，
  机器越慢越成立。

### 测试与门禁

3077 passed + 1 failed → **3085 passed / 13 skipped / 0 failed**（净 +7 测试：prefetch 6 + onboarding 1，
另修好 1 条 Windows 红）。五项静态门全过：import cycle 165 模块 / 0 环、
write surface 154/154 unclassified 0、static hygiene、public checkout probe --strict exit 0、
`git diff --check` 干净。

---

## BW — 接手 WIP checkpoint `192e056`：套件隔离修复 + Owner 写入权威收口（2026-08-01）

`5bf0022`/`192e056` 两个提交以 WIP 身份推上 main，自述「完整套件 3015 passed / 102 errors，
错误集中在 `tests/system_modularization/`，代表性测试单独跑过，建议先查共享根因」。
本节接手该 checkpoint。

### 0. 102 个 error 是**一个**根因，不是 102 个缺陷（P0）

`tests/system_modularization/test_memory_os_agent_os_shell.py` 的
`_clear_imported_memory_os_modules()` 从 `sys.modules` 弹掉 `plugins`、`plugins.memory`、
`plugins.memory.memory_os`，**却把它们已导入的子模块留在原地**。这不是「没导入」而是一个洞：

- `from plugins.memory.memory_os.crystallized import X` 仍然成功（叶子模块在缓存里）；
- `import plugins.memory.memory_os.crystallized as x` 却失败——该字节码走
  `IMPORT_NAME`（fromlist 为空）拿到重新导入的**裸** `plugins`，再 `IMPORT_FROM memory`
  做 `getattr(plugins, "memory")`，而新父包上没有这个属性，`sys.modules['plugins.memory']`
  的兜底也已被弹掉 → `ImportError: cannot import name 'memory' from 'plugins'`。

本提交新增的 `tests/conftest.py` 恰好在**每条测试的 setup**里跑这两行（第 24 行 `from`
成功、第 28 行 `import ... as` 失败），于是**排在该文件之后的每条测试**全部 error。
这也解释了为什么代表性测试单独跑是绿的——它从来不是那些测试的缺陷。

三个环境独立复现同一条结论：

| 环境 | 结果 |
|---|---|
| GitHub Actions（Linux，`192e056`） | 3011 passed / 13 skipped / **102 errors** |
| 交接方 Linux 隔离全量 | 3015 passed / 9 skipped / **102 errors** |
| 本机 Windows 全量（修复前基线） | 3010 passed / **1 failed** / 13 skipped / **102 errors** |

**并纠正交接说明的两点**：① 该 checkpoint 的 GitHub CI 是**红的**（run 30697011570，
`verify: failure`）——交接方本机 `gh` 未登录故未能核验，不是「未知」而是「已失败」；
② 交接清单未提到的**第 4 条本机失败**：
`test_write_capability_imports_are_restricted_to_governed_production_callers`
用正斜杠字面量比对 Windows 原生分隔符，与 BK 记录的同一类缺陷（改 `.as_posix()`）。
又一条本机必红的测试被推上 main，DoD 第 4 步再次未执行——与 BV 第 0 节同族的流程发现。

修法不是「把弹出的名字补全」：**全量清除会把类身份也换掉**——其他测试文件在 collection 期
已绑定 `CrystallizedMemoryService` 等类对象，重新导入会产生第二份副本，
`monkeypatch.setattr(类, ...)` 就会打在没人使用的对象上，**失败方式从响亮变成静默**。
改为 autouse fixture 在每条测试前后**快照并还原模块对象本身**（而非清名字），
`sys.path` 一并还原；删除 `_clear_imported_memory_os_modules()` 本体，避免再被调用。

### 1. Owner 写入权威两份实现，跑在生产上的是弱的那份（P1）

`owner_actions.py` 与 `crystallized.py` 各有一份 `_validate_consumed_owner_write_context`。
查实：**`owner_actions` 那份没有任何 caller（死代码）**，真正守生产永久写的是
`crystallized` 那份，而它是两份里**弱的**——相对 `owner_actions` 版本缺了四项：

1. 不校验 context 的 `source` 属于 recorded digest（`recorded_digest` /
   `latest_recorded_digest` / `latest_owner_home_digest`）；
2. 不校验 `action_type` 属于 canonical-write 白名单；
3. 不校验 token hash 是完整 SHA-256（长度 64）；
4. 消费账本比对时**不比 `action_token_hash`**，且用的是另一个字段
   （`owner_write_context_id` 而非 `reply_ingress_id`）。

新增 `plugins/memory/memory_os/owner_write_authority.py`：只依赖 roots/store/JSONL 原语，
不 import `owner_actions`/`crystallized`（两者反过来 import 它），
**不导出任何永久写 capability 单例**。两份重复实现全部删除，
`owner_actions` 与 `crystallized` 同走这一份。顺带把
`OWNER_CANONICAL_WRITE_ACTION_TYPES`、两个 ledger path helper、`_safe_channel`
也收敛为单一定义（`owner_actions` 以 import 别名保留原有模块内名字，调用点零改动）。
import cycle 门：166 模块 / 0 环。

### 2. 测试授权由「全局默认给」改为「显式申请」（P1）

原 `tests/conftest.py` 用 autouse fixture 给**全仓库每条测试**发永久写权威——
一个丢了 Owner 绑定的生产 caller 照样能全绿，因为 fixture 悄悄补上了它没能自证的授权。
改为具名 fixture `crystallized_test_write_authority`，默认 fail-closed；
实测确定需要它的 **21 个文件**各加一行 module 级 `pytestmark` 声明。

值得记录的是**哪些文件不需要**：`test_memory_os_external_evidence_owner_action.py`、
`test_memory_os_candidate_clusters.py` 等 Owner ingress/安全用例在去掉全局授权后**依然全绿**，
证明它们本来就走真实 recorded-digest 路径，不靠 fixture 补授权。
另加 `test_canonical_write_authority_fixture_is_opt_in_rather_than_autouse()` 钉住
「这条 fixture 不得再变回 autouse」——否则文件里那两条 fail-closed 用例会开始因错误的原因通过。

### 3. `approve_external_evidence` 出现在每条候选上（P1）

两处缺陷叠加，交接说明只猜到后一半：

- `_review_actions()` 的 candidate 分支**无条件**塞进 `approve_external_evidence`；
- `_digest_item()` 按**白名单**重建 bounded item，名单里没有 `external_review_eligible`
  → 走该渲染路径时标记丢失，于是**真·tainted 候选反而掉进普通候选分支**。

两处都修。关键证据：修掉前一处之后，既有的
`test_approve_external_evidence_crystallizes_tainted_candidate` **立刻失败**——
说明它此前一直**因为那个无条件 token 才通过**，从未真正走到
`external_review_eligible` 分支。这是一条真实的生产缺陷：在 `_digest_item` 渲染路径上，
tainted 候选拿到的是 `approve_candidate`，而普通 approve 对 tainted 候选是被拒的
（`test_ordinary_approve_cannot_approve_tainted_candidate`），即 Owner 在该路径上
**根本无法批准 tainted 候选**（fail-closed，非越权，但治理面是坏的）。
新增两条**精确集合**断言（而非 `in`/`not in`），双向覆盖：普通候选
`== {approve_candidate, reject_candidate}`、tainted 候选
`== {approve_external_evidence, reject_candidate}`。

### 4. `candidate_cluster` 移出 `LIVING_MEMORY_TARGET_TYPES` 是对的，但漏了一份拷贝（P1）

结论：**移除正确**。该集合现在只剩 `crystallized_record` /
`provisional_crystallized_record` / `permanent_memory_promotion`——全是**已写入的记录级**目标；
而 candidate_cluster 是「提议写入」，与 `candidate` 同类，
**`candidate` 从来就不在这个集合里**。旧的 membership 才是不一致的那个。

但 `scripts/memory_os_3_200_monitor.py` 里那份**内嵌 fallback 拷贝**仍列着
`candidate_cluster`。该 fallback 只在 provider 不可导入时生效（clean host、远程探针），
所以它**不会报错**，只会让同一条 item 在不同主机上被分到不同类——比报错更坏。
已同步并新增 `test_monitor_living_memory_fallback_matches_owner_actions()` 用 AST 取出
字面量与真集合逐一比对，钉死漂移。（同 CLAUDE.md 记载的
`classify_hermes_cron_jobs` 三份拷贝同族风险。）

### 5. 对 `192e056` 全部 27 个文件的 caller/adoption/security 复审（另 5 项发现）

不只看最后改动的 owner_actions/crystallized，逐个生产文件复审得：

1. **`scripts/memory_os_candidate_backfill_409.py` 已被打断**——本提交把
   `append_candidate_triage()` 改为空 envelope 即 `PermissionError`，docstring 写着
   「operator backfill 必须开显式 governed envelope」，但仓库里唯一的 operator backfill
   脚本没同步改：`--apply` 现在必崩。补 `--execution-gate-envelope-id`
   （env 默认 `MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID`，与仓库既有 6 个脚本同一惯例）
   并在 apply 前显式 fail-closed 返回 2，实测无 envelope → exit 2、有 envelope → exit 0。
2. **`crystallization_gate._gate_error_result()` 与同函数其余路径 error_record 形状打架**——
   前者 `{"code": ...}`、后者 `{"error_code": ...}`，同一个 `error_records` 字段两种形状；
   当前消费者只读 `status` 故未崩，但下一个迭代记录的消费者会在**恰好是失败的那些路径**上
   读不到 `error_code`。统一为 `{candidate_id, error_code, component}`，新增双路径精确集合断言。
3. **`read_candidate_queue()` 静默丢弃 schema 非法行**——能解析成 JSON 但不是可用候选的行
   被 `continue` 掉且不记 error record。而聚合车道只在「读到错误」时跳过队列压缩，
   压缩是全量重写：这类行会先被静默丢弃、再被下一次压缩**永久抹掉**，全程无痕。
   四个校验分支各补 `error_record`（含 component/operation/severity/recoverable）。
4. **被拒的 canonical write 授权不留任何痕迹**——该路径用 `persist_error=False`，
   这本身是对的（不能让未授权调用方往 owner-action 账本里追加），但它同时意味着
   伪造 token 的探测**在任何地方都不可见**。改为在 audit 通道记一条
   `owner_canonical_write_authorization_rejected`（有界字段，绝不记 token 本体），
   既保住 `read_owner_action_records(...) == []` 这条既有不变量，又留下证据。
5. **`_resolver_candidate_gate_result()` 对每条候选都跑**——含被判 reject 的，
   每次开两个 sqlite 连接 + 一次 FTS 查询，而其结果只在 approve 分支被读。
   三处改为按 `verdict.get("approve")` 惰性求值，行为不变。

### 有意未做（登记）

- `scripts/memory_os_blank_host_smoke.py` 被本提交从「永久写」改为「provisional 写 +
  probe capability」（因为永久写现在需要 recorded digest）。这是**必要的**，但
  blank-host smoke 因此**不再覆盖永久 canonical write 路径**——登记为覆盖缺口，
  补齐需要 smoke 自建完整 recorded digest，属独立一轮。
- `execution_gate._rebuild_gate_index_from_records()` 现在 `del records` 忽略入参、
  改为持锁重读账本，函数名与签名已名不副实；且它在**每次 permit resolve 成功后**都被调用，
  即每次 resolve 多一次全账本读 + 索引全量重写。BS/BT 记录过
  `execution_gate_index.json` 的 15 秒锁争用，虽已由 `prune_sidecar_index()`（保留 2000 条）
  与 BU 的 tick 错峰把同分钟并发压到 1，仍登记为需要观察的热路径成本。

### 反事实覆盖

- 关掉 `restore_memory_os_import_state` 的 autouse →
  `test_installed_runtime_import_leaves_no_hole_in_the_real_plugins_package` FAIL，
  且暴露出比「洞」更坏的一种状态：`sys.modules["plugins"]` 指向 `tmp_path` 里的**假树**。
- 去掉 `_review_actions` 的无条件 external token → 既有
  `test_approve_external_evidence_crystallizes_tainted_candidate` FAIL（见第 3 节）。
- 未声明 `crystallized_test_write_authority` 的永久写 →
  `CrystallizedApprovalError`，由带 `require_explicit_crystallized_capability` 的两条既有
  用例 + 新增的 opt-in 钉子用例共同守住。
- `_gate_error_result` 形状统一后，两条既有断言旧形状的用例立刻 FAIL 并已同步
  （Section W 规则 2 的现场：改了什么就 grep 什么）。

### 测试与门禁

修复前（`192e056`，本机 Windows）3010 passed / 1 failed / 102 errors / 13 skipped
→ 修复后 **3119 passed / 13 skipped / 0 failed / 0 errors**。
五项静态门全过：import cycle 166 模块 / 0 环、write surface 153/153 unclassified 0、
static hygiene、public checkout probe --strict exit 0、`git diff --check` 干净；
closure matrix `status=ok`。GitHub CI 对最终提交全绿（full suite + 五门 + 空白门）。

### clean clone + 全新 venv 门：查出两条既有环境缺口

按交接要求做了 exact-commit clean clone + `pip install -e ".[dev]"` 全新 venv 全量，
**首次跑出 15 failed**——两条都与本轮改动无关，是这道门本身该抓的东西：

1. **`pyproject.toml` 的 dev 依赖在 Windows 上不完整（已修）**。
   Windows 没有系统 tz 数据库，`zoneinfo.ZoneInfo("UTC")` 直接抛
   `ZoneInfoNotFoundError`；`plugins/modules/context/digest_consolidation.py` 顶层
   `from zoneinfo import ZoneInfo`，于是全新 venv 里 15 条测试中的 14 条挂掉
   （digest_consolidation 10 条 + modules doctor 连带 3 条 + deep_reflection 1 条）。
   本机之前一直绿是因为系统 Python 恰好装了 `tzdata 2025.3`，CI 绿是因为 Linux 有系统库——
   **两个环境都在替这条缺失依赖兜底**，只有全新 venv 会暴露它。
   已加 `tzdata; sys_platform == "win32"` 到 dev extras，实测 14 条全部转绿。
   （未动运行时 `dependencies = []`：生产两台主机都是 Linux；但需记住
   digest_consolidation 在 Windows 运行时同样会炸。）
2. **`test_isolated_worker_executes_without_session_or_delivery_files` 在全新 venv 下必红（未修，登记）**。
   该测试 `os.symlink(sys.executable, host/"venv"/"bin"/"python")`，
   在 venv 里 `sys.executable` 是 `.venv/Scripts/python.exe`，符号链接到 venv 布局之外后
   丢掉 `pyvenv.cfg` 上下文，子进程于是导不到 editable 装的 `plugins` → `returncode != 0`
   → `ephemeral_worker_failed`。系统 Python 与 Linux CI 均无此问题。
   文件不在本轮 diff 内，属既有跨环境假设缺口（与 BU.1「CI 空过、本机绿」、
   BV 第 0 节「本机红、CI 绿」同族：**测试不验证自己的运行前提**）。

修掉第 1 条后 clean-clone 全新 venv 的剩余失败为 **1 条**，即上述第 2 条。

---

## BX — 每日 owner 审批议程：口径撒谎、翻页错位、审批项不可读（2026-08-01）

owner 从生产 3.200 的 `memory-os-owner-review-digest` 收到的真实推送：

> 今日需决定 1 项（共 25 项，另有 24 项未展示）
> [A25] 是否批准 SessionMirror 的受限生产导入 lane 毕业，并执行一次真实 smoke？
> …fingerprint 相关字段…
> 批准命令：`memory approve oa_d40…` 拒绝命令：`memory reject oa_d40…`

owner 的三条反馈：**看不懂在批什么**、**第一条永远是这条**、**真实的那些看不到**。
本节把三条都追到源码，并确认它们是**同一条链**上的三个缺陷。

### 0. 先复现，再动手（本轮唯一一次「先证据后设计」）

用 24 条 `provisional_crystallized_record` + 1 条 `session_mirror_apply` 构造 fixture
调 `owner_review_digest_preview(digest_mode="agenda")`，逐字复现了生产文案：

| 量 | 值 |
|---|---|
| `counts.action_required_total` | 25（**未过滤**队列） |
| `counts.action_required_shown` | 1 |
| `counts.visible_action_required_total` | 1（**过滤后**，真正可投递的） |
| `overflow.action_required` | 0（正确，可投递项没有溢出） |
| 展示锚点 | **A25** ← 与生产一致 |
| 表头 | 「需要你决定 25 项；本条展示 1 项，未展示 24 项」← 与生产一致 |

结论：A1–A24 **全部是投递链路结构上永远送不出去的项**，不是「今天没排上」。

### 1. 表头统计的是与 section 不同的人群（P0，「真实的看不到」的真身）

`_assemble_living_memory_delivery_items()` 把 `LIVING_MEMORY_TARGET_TYPES` 里的
非 promotion 项从**每一次投递渲染**中移除——这是 `39d1f2e`（Living Memory V2-0 rev-2）
Task 7 有意引入的 delivery choke point，且被 monitor 硬约束
（`living_memory_owner_delivery_nonpromotion_count>0` 直接 fail）。**所以正确修法不是放开过滤**，
放开会当场打红生产 monitor。

真正的缺陷是 `_rendered_overview_lines()` 用 `action_required_total`（未过滤）当分母，
而 section 来自过滤后的列表：于是每天告诉 owner「有 25 项要你决定、24 项没展示」，
而那 24 项 owner 在这个渠道里**永远等不到、也本来就不需要决定**
（provisional 的 `confirm` 早已是 disabled no-op，到期自动失效，成熟的另走永久记忆提案）。

改为按 section 实际来源的人群计数（`visible_action_required_total`，缺失时回落到原
字段以兼容旧记录），并新增一行**如实披露**被过滤的 backlog 及其去向。
按 Section W 第 5 条全项目扫同一模式，`review_suggested_total` 有**完全相同**的缺陷
（同样未过滤、同样被 stale 抑制影响），一并修掉；`fyi_total` 本就基于 visible，无需改。

### 2. 「下一页」按计数翻页，翻进另一份列表（P0，与第 1 条是同一 bug 的另一半）

`_surface_offsets(operation="next_page")` 用 `counts.action_required_shown` 当偏移量，
而 `owner_review_surface_report()` 的 `raw_items` 是**未过滤**队列：
议程展示了 A25，偏移量却是 1 → 翻页返回 **A2**，一条 owner 从没见过的项，
同时 **A1 被静默跳过**。表头还在教 owner 回复「下一页」——广告出来的逃生口是坏的。

改为**按 `review_item_id` 身份续页**（与 `_repeat_decision_item_count` 同一把钥匙，
抽出共享 helper `_rendered_digest_review_item_ids()`），并保留 `offsets` 字段的既有语义
（回填「本页之前已处理掉多少条」），避免消费者读到裸 0 误以为没跳过。
旧记录没有 `review_item_id` 时回落到计数路径。

> Section W 第 2 条当场兑现：grep 到既有
> `test_review_surface_next_page_uses_latest_owner_home_digest_offsets` 断言
> `offsets["action_required"] == 2`。若不回填该字段，这条测试会红——而且它红得有道理。

### 3. 审批项不可读 + 广告了一个不存在的动作（P1，「看不懂」的真身）

`_session_mirror_apply_review_items()` 的 summary/reason 是
`fingerprint=smfp_…; max_sessions=1`——**这不是任何人能做的决定**。
而 `_safe_pending_session()` 早就产出了为展示而生的
`metadata_or_redacted_summary` 面（已裁剪、已脱敏、`raw_private_body_printed=False`）：
platform / message_count / tool_count / 脱敏摘要。改为渲染它，并按
`external_review_eligible` 同款教训在 `_digest_item()` 里显式携带
`pending_session_preview`——否则会在有界拷贝处被静默丢弃、退回 fingerprint 文案。

另：`session_mirror_apply` 在 `_review_actions()` 里**只有 approve**，
`TERMINAL_ACTIONS_BY_TARGET_TYPE` 也只认 `approve_session_mirror_apply`；
生产推送里那条「拒绝命令 `memory reject oa_…`」是 **cron agent prompt 自己补出来的**
（prompt 的示例写着 `memory approve oa_... / memory reject oa_...`，教会了模型凑对称）。
该命令必被拒绝。这正是 `_review_actions()` 里那条注释警告过的反模式
（「列出 owner 做不到的动作，只会教会 owner 忽略这个界面」）——只是这次发生在上一层。
prompt 改为**只许照抄 Script Output 实际列出的命令**，并明说「只支持批准就直说」。

### 4. 未修、留作 owner 决策的一项

session_mirror 项的身份是 `production_bounded:{stable_scope_id}`，由**首个 pending 会话的
fingerprint** 派生；且该 target_type **没有 reject 动作**。即：owner 目前没有任何方式说
「别再问了」。给它加 `reject_/defer_session_mirror_apply` 需要新的 owner action 类型、
终态注册、handler 与回滚契约（CLAUDE.md：新动作须自带有界 apply 契约），
属于治理面扩张，不在本次「修好每日摘要」的范围内，**记为待办第 4 项**由 owner 定夺。

### 5. 完成前复审抓到的第三次同类实例（出在自己身上）

披露行初稿写的是「…；想看可回复：**查看临时记忆**」。但 `owner_review_surface_report()`
的 operation 只有 `overview / page / next_page / detail / proposal_followups /
expression_feedback_context / memory_sources_feedback_context`——**没有任何一个
只返回被过滤掉的 provisional 记录**。这正是本节修的两个缺陷的同一形状
（表头广告一条到不了的路 / prompt 广告一个不存在的动词），只是这次是自己写的第三次。
改为**只披露、不邀请**：保留「到期自动失效，成熟的会另走永久记忆提案来问你」，
删掉回复引导，并加一条测试把该契约钉住（`"查看临时记忆" not in text`）。

### 6. 可投递项归零时议程静默——既有行为，未被本次改动影响

`memory_os_owner_review_digest.py` 的 `_has_meaningful_content()` 在 agenda 模式下以
`counts.action_required_shown > 0` 为门槛。owner 一旦批准/清掉那唯一一条可投递项，
该值归零、脚本不输出、cron 保持静默——**即使 `nondeliverable_living_memory_total` 仍是 24**。
这是 provisional 本就不需要 owner 决策的正确结果。需要说明的是：
`action_required_shown` 一直取自**过滤后**的 section，本次只动了表头分母，
**没有改动这条静默门槛**——静默行为在本次修复前后完全一致，不是新引入的变化。

### 7. `counts` 同时保留两种口径的下游风险已扫

`counts` 里 `action_required_total`（未过滤，25）与 `visible_action_required_total`
（可投递，1）并存，`_bounded_delivery_digest` 也一并记账。风险是下游若用
`action_required_total - action_required_shown` 当「隐藏项数」会重犯本节的错。
全项目 grep `_total.*-.*_shown`：命中仅 `_rendered_overview_lines()` 内那三处，
均已改用修正后的口径；`memory_os_3_200_monitor.py` 与
`memory_os_monitor_dashboard_snapshot.py` **没有**该算式。风险关闭。

### 8. 合并前自审又抓到一处「静默跳过一项」——同族缺陷，出在第 2 条的修复里

第 2 条改成按身份续页后，`next_offsets` 仍写作 `start + len(selected)`。
`next_offsets` 是**调用方回填给后续 `page` 的游标**（`__init__.py` 工具 schema 明示 offset），
而该算式只在「已展示项恰好连续排在最前」时成立。本例恰恰相反：唯一被展示的
session_mirror 项排在**最后**（idx 24），于是 start=1、selected=3 → 游标 4，
后续 `page(offset=4)` 返回 `cry_04`，**把从未展示过的 `cry_03` 静默跳过**——
与本节第 2 条修的缺陷是同一个（「广告出来的续页路径会漏项」），只是这次漏在修复自身里。
改为「落在**实际返回的最后一项**之后」（`chosen[-1][0] + 1`）。
反事实实测：还原该行 → `assert ['cry_04'] == ['cry_03']` FAIL，恢复 → PASS。
既有 `offsets == 2` 断言不受影响（该场景已展示项本就在最前，两种算法同值）。

### 反事实覆盖

新增 11 条测试（10 条 `test_memory_os_owner_digest_agenda.py` + 1 条 cron gate prompt）。
用 `git checkout main -- plugins scripts`（保留测试、只回滚代码）**实测**
revert→fail→restore→pass：**8 条在无修复时 FAIL**——表头口径、backlog 披露、
不再广告翻页、身份续页、续页游标不漏项、session 可读性、preview 有界拷贝存活、
cron prompt 不编命令。另 3 条是回归护栏，设计上前后都应绿：计数回落路径、
「不提供做不到的动作」、披露行不邀请无路由回复（该行本就是本次新增，故在 main 上恒真）。

### 测试数量

修复前 3119 passed / 13 skipped（BW 收尾基线）→ 修复后 **3130 passed / 13 skipped / 0 failed**
（+11）。四道静态门全过：import cycle / write surface `unclassified_count=0` /
static hygiene / public checkout probe（strict），`git diff --check` 干净。

### 未验证项（如实声明）

本轮**只有本机 pytest 与静态门证据**（`local_pass`）。未跑 3.200 `live_monitor_pass`、
未跑 clean-host、未部署。文案改动的最终呈现还经过 Hermes cron agent 改写，
真实推送效果需下一次 09:00 议程或一次 `deliver-once` 才能确认。

---

## BY — session_mirror reject/defer + cron lane 停用审计（2026-08-02）

收网评审后 owner 指定开发待办第 4、5 两项（第 6 项 `oa_` 密钥化明确不做）。

### 待办 4 — owner 无法拒绝 session_mirror 导入审批

owner 只有 approve 一个选项，「别再问了」无法表达。owner 决策：**reject + defer 都做**。

两者语义不同，实现路径也不同：

- **reject = 这个会话别导入**。照现有 `closed` 机制按 target 关闭即可——但**只做这一步是错的**。
  `SessionMirror.scan()` 的选择是纯队头（`platform_filtered[:limit]`，无任何排除状态），
  于是被拒绝的会话每次 scan 仍在队头、`return []` 短路，**后面所有会话被永久饿死**，
  而且 lane 一旦毕业，真正被导入的还是这个被拒绝的会话。所以排除必须由
  `session_mirror.py` 自己认账：新增 `_owner_rejected_fingerprints()`，从 owner action 账本
  读回 `reject_session_mirror_apply` 的 fingerprint 并过滤 `new_sessions`，
  新增 `skipped_by_owner_rejection_count` 保持可见（不静默跳过）。
  **刻意不写进 SessionMirror state**：`_rebuild_state()` 从事件重建，存那里的拒绝会在下一次
  state 修复时无声消失、被拒会话复活。账本是 append-only 且从不由事件重建。
  读取路径复用既有的 `read_jsonl(owner_actions_path(...))`（session_mirror 早已这么读，
  不 import owner_actions 模块，无环）。
- **defer = 整条 lane 安静一阵**。**不能**用关闭 target 表达——`target_id` 由队头会话 fingerprint
  派生，换一个会话就是新 target，owner 立刻又被问。改为 lane 级判定
  `_session_mirror_lane_deferred()`，照搬 `defer_candidate_cluster` 的既有契约
  （`deferred_until`、默认 7 天、过期自动重开）。

顺链改到的地方：action 类型集合、`TERMINAL_ACTIONS_BY_TARGET_TYPE`、
`_closed_targets` 的 defer 过期判定抽成 `DEFER_ACTION_TYPES`（漏登记 = 永久关闭而非暂停）、
idempotency 的过期 defer 重发、action_type→target_type 映射、
`_owner_action_type_from_reply`、`_reply_verb_matches_action_type`、`_review_actions`、
校验与 effect handler、owner 可见文案两处（例句原本只显示 approve 一条、后果说明只讲批准）。

`_session_mirror_apply_review_items` 的 `lane_deferred` **故意设为必填关键字参数**（Section W
第 4 条）：它有两个调用方（digest 组装、aging report），给默认值就会漏掉一个、让被 owner
静音的项在另一个面继续出现。实测这个决定当场生效——改完两个调用方都以 TypeError 报错而非静默跳过。

安全边界复核：三处 apply 路径（`cli.py:2084`、`session_mirror.py:115/1004`）都硬比对
`approve_session_mirror_apply`，因此 reject/defer 记录**结构上不可能**授权一次导入；
两个新类型也未加入 `DIGEST_OPTIONAL_SURFACE_ACTION_TYPES`，仍需 recorded digest 绑定。

### 待办 5 — cron lane 停用没有审计痕迹

生产实况：`memory-os-expression-feedback-request`（active-closure 8 个 job 之一）在 Hermes job
层 `enabled=false`，而 `cron_lane_disabled.json` **根本不存在**——停用绕开了文档化的 per-lane
机制，主机上没有任何地方记录原因。owner 决策：**保持停用，但补正式审计记录**。

- `cron_lane_disabled.json` 升 v1：新增 `{"lanes": {key: {reason, actor, disabled_at}}}` 形状，
  两种旧形状（裸 list、`disabled_lane_keys` 包装）继续解析并回落为空审计字段。
  新增 `read_lane_disable_records()` / `build_lane_disable_state()`；
  `read_disabled_lane_keys()` 改为它的派生。**"损坏文件不停用任何 lane"这一失败方向保持不变**。
- `memory_os_cron_group_runner.py` 里的**第二份拷贝**同步（Section W 第 5 条）。
  反事实实测：不同步的话，一旦 owner 记了原因、keys 挪到 `lanes` 下，旧解析器就读不到，
  **审计动作本身会把停用的 lane 重新跑起来**。
- monitor：`helper_completion_disabled_records` 带出 source/reason/actor/disabled_at；
  新增「停用但无原因」独立信号 `helper_completion_disabled_undocumented_count` 与 WARN 码
  `execution_gate_memory_os_cron_helper_completion_disabled_without_audit_record`。
  状态可能是对的，但「对且无解释」在下次复审时与漂移不可区分。

### 顺手关闭待办 1（比原记录严重）

按 Section W 第 5 条扫同类模式时查实：**未注册的 WARN 码在 clean-host 会被判
`clean_host_warn_unclassified`，那是 FAIL 不是 WARN**。原记录以为要不要注册取决于
`deploy_memory_os.py` 是否接入 cron onboarding，实际无关——任何 clean host 上只要有 lane
被停用/stale/尚未跑过，monitor 就会因为这个红。五个码全部注册，
一律 `warn_if_production`：**只修 clean-host，绝不把现有生产 WARN 升级成 FAIL**
（生产当前正在 WARN 的 `..._disabled` 与 `..._boundary_unobserved` 行为不变）。

### 反事实覆盖

7 项全部 revert→FAIL→restore→PASS 实测通过：scan 排除过滤、`DEFER_ACTION_TYPES` 过期重开、
lane defer 静音、group runner v1 形状、monitor 未登记停用追踪、clean-host WARN 注册、
reply verb 映射。

### 测试与门

3130 → **3148 passed / 13 skipped / 0 failed**（+18）。
import cycle / write surface（unclassified 0）/ public checkout probe --strict / `git diff --check`
全过。`static_hygiene` 的 `compileall` 子项在本 worktree 内 FAIL，经定位为 **Windows MAX_PATH
环境伪影**：该检查把源码绝对路径镜像到临时 `pycache_prefix` 下，worktree 路径较长导致
目标 261 字符、超 260 上限一个字符；换短 prefix 后 `compileall` exit 0，全部文件正常编译，
非代码缺陷（主检出与 Linux CI 不受影响）。

BY 自身仅 `local_pass`（在 PR #10，未合并故未部署）。但本轮顺带关闭了收网评审查出的
**发布→部署缺口**，见下。

### BY.1 — 3.200 补上 BW(#8) + BX(#9) 部署（2026-08-03）

收网评审查实：生产 `deployed_head=5bf0022`，**BW 与 BX 合并后从未部署**，
owner 每天 09:00 收到的仍是 BX 之前的渲染（口径撒谎、翻页跳项、`smfp_…`）；
且 manifest 声明的 `active_runtime_path=/opt/Hermes-Memory-OS` 停在 `192e056`——
即 BW 接手前那个 CI 红的 WIP commit，谁从该路径部署就会推上已知坏树。

已处理：

- `/opt/Hermes-Memory-OS` 由 `192e056` fast-forward 到 `54296ea`（工作树干净，纯 ff）。
- 备份 `/root/.hermes/backups/memory-os-pre-bw-bx-20260803T042836Z`（21M，
  含 plugins / runtime / scripts 三棵已部署代码树与旧 manifest）。
- `deploy_memory_os.py --mode production-safe --profile upgrade` 走完
  plan → preflight → dry-run → apply：`fail=[]`，
  pass 含 apply_applied / postcheck_pass / deployment_manifest_write_pass /
  cron_adapter_probe_pass / boundary_runtime_probe_pass。**未加 `--allow-restart`，Gateway 未重启。**
- 部署后核验：live runtime `owner_actions.py` sha 前 16 位 `e43ed37c369748ba`，
  与仓库 `54296ea` 逐字节一致；`pending_session_preview` 命中 4（BX 到位）、
  `owner_write_authority.py` 存在（BW 到位）；manifest `deployed_head=54296ea`；
  fresh-process import 指向 runtime 树。
- Full Monitor（live，**从 BY worktree 的 monitor 脚本发起**，非主机上已部署的
  `54296ea` 版；差别是前者多一条 BY 新增的 WARN 码）：**98 PASS / 7 WARN / 1 FAIL**，
  唯一 FAIL 仍是 `v2_exposure_schema_era_unhealthy`，与本次部署无关（数据成熟度驱动，
  实测正在推进：rollup lag 74.4h→26.5h、schema-era 分类率 0.6506→0.7018、
  observation_days 19.7/30、conservation failures 0）。

  与 08-02 部署前快照（99 PASS / 4 WARN / 1 FAIL）逐条对齐后，三条新增 WARN 全部有解释、
  **无一是本次部署引入的回归**：

  1. `..._disabled_without_audit_record` —— BY 自己新增的码，且它**在真实生产数据上一次命中**
     就是 item 5 要抓的那个状态（`memory-os-expression-feedback-request` 在 Hermes job 层
     停用、无任何原因记录）。属预期。
  2. `full_monitor_runtime_over_target` —— 本次从 Windows 经 SSH 发起，非主机 cron 路径，
     墙钟本就更长；路线图 §5-5 已登记的既有 WARN。
  3. `low_clue_llm_judge_unavailable` —— **PASS→WARN 的那一条**（`low_clue_llm_judge_available`
     在 08-02 是 PASS，PASS 计数 99→98 由它贡献）。经 owner 确认：**OpenAI 额度耗尽**，
     非功能故障。判断器配置完好（`enabled=true`、`mode=bounded_vote`，实测解析到
     `gpt-5.6-luna`/`openai-codex`），只是调用发不出去 → `status="skipped"`，
     而 monitor 的判定是「status 不在 {error, skipped} 才算 available」，于是把
     "额度不足导致未调用" 与 "判断器不可用" 合并成同一个 WARN。
     **登记为 monitor 语义弱点**（外部额度/主动跳过/真故障三者不可区分），非本次部署缺陷。

**部署过程中发现一个仓库缺陷（未修，登记）**：`deploy_memory_os.py` 的 `--timeout` 默认 60s，
而它自己的第一道 compat 门 `memory_os_upgrade_compat_check.py` 在 3.200 上实测需 **63s**，
于是默认参数下 `--phase preflight` 必然失败，且错误码是 **`compat_json_invalid`**——
把"超时被截断"报成"JSON 非法"，指向完全错误的方向。本次以 `--timeout 300` 绕过。
修法应是默认值调高 + 超时与 JSON 解析失败分别报码。

### BY.2 — 修 BY.1 登记的 deployer 超时缺陷（2026-08-03）

两个独立缺陷，一个体感一个误导：

1. **默认预算低于自身第一道门的实测成本。** `--timeout` 默认 60s，而
   `memory_os_upgrade_compat_check.py` 在 3.200 实测 **63s**，于是**默认参数下
   `--phase preflight` 必然失败**。低配主机更慢（2.88 约 3.6GiB RAM 且吃 swap）。
   抽出 `DEFAULT_COMMAND_TIMEOUT_SECONDS = 300` 并用于函数签名、`_run_command`、
   argparse 三处。这是**上限不是等待**——提前结束的命令不受影响。
2. **「没给出答案」被报成「答案格式不对」。** `_classification_failures()` 只判
   `json` 是不是 dict，于是超时（exit 124）、崩溃、真·JSON 非法三种情况全部落
   `compat_json_invalid`，把运维指向完全错误的方向。改为分三档：
   `compat_timed_out`（带 `hint` 明说要调 `--timeout`）、`compat_command_failed`（带 exit_code）、
   `compat_json_invalid`（仅当命令成功但输出不可解析）。`124` 抽成 `_TIMEOUT_EXIT_CODE`。

**按 Section W 第 5 条全项目扫同类模式，查出这不是孤例**——`_classify_llm_judge_probe`、
`_classify_cron_adapter_probe`、`_classify_boundary_runtime_probe` 三个探针分类器
**完全相同的缺陷**（只判 payload 形状、不看 exit_code），超时同样被报成 `..._json_invalid`。
抽 `_probe_transport_fault()` 三处统一修。另三处
（`_classify_install`、`_run_memory_projection_refresh`、`_classify_deployment_manifest`）
本来就先判 exit_code，**已正确，未动**。

向后兼容：`exit_code` 缺省取 0（＝无传输故障证据），既有不带 exit_code 的调用与测试行为不变；
探针输出正常但内容不合格时，原有 `..._json_invalid` 判定原样保留。

反事实：4 项 revert→FAIL→restore→PASS（超时/JSON 分档、默认值下限、崩溃码、探针同族修复）。

### BY.3 — BY 部署到 3.200 并端到端验证（2026-08-03）

PR #10 合并为 `01356df` 后部署。

- `/opt/Hermes-Memory-OS` ff 到 `01356df`；备份
  `/root/.hermes/backups/memory-os-pre-by-20260803T082748Z`（21M）。
- **刻意不带 `--timeout` 跑 `--phase apply`**，用来在生产上验 BY.2：preflight 通过、
  全程 `fail=[]`、`apply_applied` / `postcheck_pass` / manifest / 两个探针全 pass。
  这在 BY.2 之前是不可能的（默认 60s < compat 门 63s，preflight 必失败）。未重启 Gateway。
- 部署后 fresh-process import 核验：`session_mirror_apply` 终态动作为
  `['approve…','defer…','reject…']` 三条；`DEFER_ACTION_TYPES` 两条齐全；
  `LANE_DISABLE_STATE_SCHEMA_VERSION = memory-os.cron_lane_disabled.v1`；
  主机侧 group runner 已能解析 `lanes`。manifest `deployed_head=01356df`。
- **补写 lane 停用审计记录**（待办 5）：用主机上刚部署的 `build_lane_disable_state()` 生成，
  保证 schema 与运行时一致；读回校验通过。
- **端到端验证 item 5**：Full Monitor 的
  `helper_completion_disabled_undocumented_count` 由 **1 → 0**，
  `..._disabled_without_audit_record` WARN 消失，而
  `helper_completion_disabled_count` 仍为 1、`helper_completion_disabled_records` 带出
  source/reason/actor/disabled_at —— 即"lane 依然是停用的，但从此有据可查"，正是该项的目标。

最终生产状态：**97 PASS / 6 WARN / 1 FAIL**，唯一 FAIL 仍是
`v2_exposure_schema_era_unhealthy`（数据成熟度驱动，与本次无关）。
本次 monitor 由主检出跑，**代码与主机已部署版本同为 `01356df`**。

部署后紧接着的第一次 monitor 曾出现第二条 FAIL `shell_alias_no_env_failed`，
原样重跑不复现、手工逐条复现探针条件全 rc=0，判定为主机负载下的瞬时争用，
详见待办第 3 项（该项首次拿到实测复现）。

---

## BZ — 接线闭环批次 C：continuity 只分级披露、不过滤（2026-08-04）

> **记录位置说明**：接线闭环方案的批次 A（删除四个平行 helper，PR #14/#15）与批次 B
> （`timeutil` 契约修复 + 1 处定向迁移，PR #16）**没有在本清单立节**，其执行记录写在
> `docs/resolver/hermes-memory-os-adoption-closure-plan.md` 的 §2.1、§5.5–5.8、§7 里。
> 本节起恢复在本清单立节。

### 背景与裁定

`continuity.py` 是零生产调用的 helper（1722 行零调用那批之一）。Owner 裁定：
**计算新鲜度等级并披露出去；既有的 `cutoff`/`recency` 过滤器一律不动**
（`state_overlay.py:264,286` 的 7 天窗口、`prefetch.py:2002,2019` 的 48 小时窗口）。
`DEFAULT_STALE_AFTER` 从"闸门"降格为"分级刻度"——它的 1h/2h 是按"会话内"模型写的，
把 open_thread 的 7 天换成 2 小时是 84 倍上下文缩减，等于拿未验证常量改线上行为。

### 修了什么

1. **两个静默失败陷阱**（方案 4.2 预先登记，实现时逐条兑现）：
   - `age_seconds()` 调 `parse_utc` 用默认 `allow_naive=False`，**naive 输入 → `None`
     → 永远 UNKNOWN → 永远不 stale**：整条 lane 会在它唯一要分级的记录上静默空转。
     改为 `allow_naive=True`。**判据不是"宽松些"而是同路径一致性**：
     `task_state._parse_timestamp`（拥有同一条记录的模块）自己就把 naive 强制转 UTC，
     严格解析会让两者对同一输入给出不同答案。`parse_utc` 仍拒绝仅日期/无秒
     （批次 B 钉死的常设隐患），那类记录落 UNKNOWN 且**被计数**，不静默丢。
   - `current_task_is_stale()` 在 `current_task is None` 时返回 `True`——
     **"不存在"不等于"过期"**。新增 `current_task_grade()`，None → UNKNOWN。
     不修的话，Owner 每开一个没有锚点的新会话都会被告知"你的任务信息可能已过期"。
2. **新增能力**：`build_current_task_continuity_object()`（canonical 记录 → 可分级对象）、
   `build_continuity_findings()`（产出 `stale_task_revision`）、
   `build_continuity_recall_plan()`（gap_note 可直接消费的形状）、
   `build_continuity_freshness_record()`（report-only 诊断记录）、
   `continuity_freshness_signature()`（状态迁移去重）。
3. **接线**：`prefetch.py::_record_continuity_freshness()`，在 `build_prefetch` 所有
   early-return **之前**调用，故四条路径（diagnostic grounding / foreground-only /
   router-apply / normal）覆盖一致。kill switch `lane_continuity_freshness_enabled`
   注册为 `lane_switch`（永不自动批准）、**默认 True**——Owner 取消的是等待窗口，
   不是关断能力。
4. **测试刻意更新**：`test_stale_current_task` 原本断言
   `current_task_is_stale() is True  # None is stale`——**它钉住的是 bug 不是契约**，
   与批次 B 的 `test_naive_allowed` 同型。已改为 `test_absent_current_task_is_not_stale`
   并在 docstring 写明为什么反转。

### 根因（为什么这两个陷阱能存在）

第 8.0 条的又一个标本：一个从未被调用的 helper，**没有任何人验证过它的前提**。
它自己的测试只证明内部逻辑自洽，于是把作者的假设（"没有任务≈任务过期"、
"时间戳一定带偏移"）当契约钉住了。这是本轮 6 个"该接线"里第 5、6 个实测被推翻的假设。

### 三处方案与实测不符（已回写方案 §4.2）

1. **数据源不是 overlay。** 方案写「overlay 对象已带时间戳（`state_overlay.py:281`）」，
   实测 `OverlayEntry` 只有 `text`/`source`/`source_kind`，**没有任何时间字段**——
   281 行读到的候选时间戳在 296 行只返回 `(summary, candidate_id)` 时被丢掉。
   真正的源是 `task_state.read_effective_current_task()`（投影 `revision` + `source_at`，
   且 `created_at` 由 `_active_task_anchor_record` 机器写入、写入者可完整追溯）。
2. **trap #3「必须走 StructuralWriteGate」在这条路径上做不到。**
   `append_governed_jsonl` 要求有效 ExecutionGate permit，而 prefetch 是每轮热路径、
   **无 envelope** → 每次 `StoreError` → 诊断永远写不出来，**照字面执行会亲手制造
   trap #3 想防的静默失败**。改为 `append_jsonl_locked` + `ALLOWED_WRITE_SURFACES`
   登记 `report_only_continuity_freshness`，与同文件两个既有 report-only shadow 写同契约；
   trap #3 的目的（`unclassified_count=0`）由此满足。**已同 PR 回写方案**，
   因为本项目把"文档说 A、代码做 B"当缺陷。
3. **只做 `current_task`。** open_threads 的时间戳按第 1 条在 overlay 里不存在，
   候选 7 天窗口按裁定不许动，故 `active_open_threads()`/`stale_open_threads()`
   在 C 之后**仍是零生产调用**——按第 8 节这正是要防的模式，已在方案里显式登记原因，
   而不是让它们静默躺着。

### 反向评审自己的 diff 抓到的一处真缺陷

`current_task` 的 `stale_after` 是 1 小时，而任务锚点**只在意图切换时重写**
（defer/resume/cancel/新任务）。于是同一任务连做超过 1 小时后，**每一轮 prefetch
都会向账本追加一行**——热路径上无界增长。改为按
`(session_id, object_id, revision, grade, unknown_count)` 签名只记**状态迁移**。
`session_id` 刻意进签名：新会话看到同一个过期对象是新事实，也是"答案变差时定位到
哪个会话"的抓手。读取失败时签名返回 `None`（＝未知 → 照写）：丢一行重复是便宜的失败，
静默跳过那条解释答案变差的记录不是。

### 顺着调用链查出的 D 接点

`prefetch.py:634` 早就以同一个 `max_age_hours=0` 读出当前任务，并把 `revision` 经
`recall_facade.py:116` 的 `build_recall_plan(..., current_task_revision=...)` 送进
recall plan——**但那个 plan 没有 `findings` 键**。也就是说修订号一直在流动、
从来没人判它是否过期。D 的活是把 C 的 finding 挂进去，不需要新建结构。

### 反事实覆盖

**6 项全部 revert→FAIL→restore→PASS 实测**：
naive 时间戳分级（2 个测试同时红）、None≠stale、接线调用本身
（byte-identical 半边会退化成 `assert 0 == 1`）、`max_age_hours=0`
（改成 24 立即 `assert 24 == 0`）、write-surface 登记（门 `pass`→`fail`）、
状态迁移去重（5 轮写 5 行而非 1 行）。

**目标反事实**（一条测试钉死整个设计）：
`test_continuity_grades_stale_task_without_changing_live_prefetch_output` ——
过期对象被判 STALE **且 live prefetch 输出逐字节不变**。两半都必须断言：
只断言 byte-identical 的话，钩子静默 no-op 也会通过，所以同一测试同时断言账本确实写了。
基线取"同一次调用但把钩子 monkeypatch 成 no-op"，**不是**第二次 live 调用——
`build_prefetch` 内嵌 `{age_h}h前` 等 now 派生文本，两次 live 调用可能因与 continuity
无关的原因不同。

### 测试数量

3035 → **3070 passed / 13 skipped / 0 failed**（+35：continuity 单元 +15、prefetch 接线 +20）。

### 门

import cycle（`cycles: []`）/ write surface（`unclassified_count=0`）/ static hygiene
（含 compileall，本 worktree 未复现 BY 的 Windows MAX_PATH 伪影）/ public checkout probe
`--strict` exit 0 / `git diff --check` —— 全过。

### 未验证项（如实声明）

- **仅 `local_pass`。未部署 3.200**：按方案第 7 节裁定，`/opt` 同步与部署验证
  在整条 C→D→E 链落地后一次性做。因此本节**没有** `live_monitor_pass` 证据。
- 分级只覆盖 `current_task`；open_threads / recent_decisions / capability_map
  的分级路径有单元覆盖但无生产数据流（见上文第 3 条，已登记原因）。
- 新账本 `system/continuity_freshness.jsonl` 尚无 monitor 字段与保留/压实策略。
  按状态迁移去重后体积有界，但**长期无压实**这一点未验证，登记为待办。

---

## 待办

BC 代码评审（对 `abcce26` 的 15 项发现）已全部完成：P0×3（BD）、P1×4（BE）、
P2×3（BF）、P3×5（BG）。

BJ 待办的"9 项 Windows 本地 pre-existing 测试失败诊断"已由 BK 完成：7/9 为真实代码/测试缺陷，
已修复；2/9（pytest_policy skip-count）诊断为本机环境伪影，非项目代码缺陷，不修复。

当前遗留：
1. ~~四个 helper-completion 兄弟 WARN 码的 clean-host 分类表注册~~ —— **BY 已关闭**，且实测
   比原记录更严重：未注册的 WARN 码在 clean-host 会落 `clean_host_warn_unclassified` 即 **FAIL**，
   与 `deploy_memory_os.py` 是否接入 cron onboarding 无关。五个码（含 BY 新增的
   `..._disabled_without_audit_record`）全部按 `warn_if_production` 注册，生产行为不变。
2. `install_memory_os_plugin.py` 五处 `str(path.relative_to(...))` 与本次修复的
   `plan_deployment()` 同一模式，当前无触发路径，暂不改动（BK 记录）。
3. `shell_alias_no_env()` 的 22 条 CLI 探针命令并行执行（`ThreadPoolExecutor`）对同一
   `HERMES_HOME` 文件/SQLite 状态的一般性并发风险（BM 记录，`review_reply` 使用假 token
   探针本身已确认安全）。**BY.3 首次拿到实测复现**：BY 部署后紧接着跑的那次 Full Monitor
   出现 `shell_alias_no_env_failed`（FAIL，08-02 快照里该项为 PASS 且无 false 键），
   同一次运行还带 `full_monitor_runtime_over_target`；随即原样重跑**不复现**
   （`shell_alias_no_env_ok` 回到 PASS、false 键为空），且逐条手工复现探针条件
   （12 条 CLI 命令、不带 env 前缀）全部 rc=0。判定为**主机负载下的瞬时争用**，
   非 BY 引入的回归——但这条待办从此不再是"无实测复现"。仍缺并发单测覆盖。
4. ~~owner 无法拒绝 session_mirror 导入审批~~ —— **BY 已关闭**（owner 决策：reject + defer 都做）。
5. ~~在 3.200 补写 `expression_feedback_request` 的停用审计记录~~ —— **BY.3 已写入并验证**
   （见 BY.3 节）。`reason` 字段刻意**没有编造原始停用理由**：主机上从来没有记录过它，
   现文案如实写明"owner 2026-08-02 决定保持停用 / 原始理由未知 / 本条为补记不改变运行状态"，
   owner 可随时替换该文本。
6. ~~`deploy_memory_os.py --timeout` 默认 60s < 自身 compat 门实测 63s~~ —— **BY.2 已修**。
7. **`system/continuity_freshness.jsonl` 无 monitor 字段与压实策略**（BZ 登记）。
   状态迁移去重后体积有界，但没有 monitor 可见性，也没有
   `memory_projection` 那样的 compaction。C→D→E 链部署前应一并处理。
8. **关键事实未入库导致召回漏项**（Owner 2026-08-04 提出，接线闭环方案 §4.4 已登记，
   **只登记未开工**）。开工第一步是分离"没入库"与"入库了但没召回"两种成因——
   前者是捕获率问题（`sync_turn` summary-only 丢弃 / candidate 未生成 / 停在候选态），
   后者是检索缺陷，修法相反。**并且这一条改变了批次 F 的性质**：
   `recall_golden` 正是测量召回漏项的仪器，删除决定不再独立，见方案 §4.4 末段。

（原 4、5 两项——BP 记录的 Track A 模块/脚本落差与 `unread_partner_replies` 语义缺口——已随
BQ 的 community 模块整体迁出本仓库，不再是本仓库待办；债务记录随代码一并迁至
sannai-community 仓库 README。）

---

## 一句话

- （BD 之前的条目随原文件丢失，区间散见上方历史摘要；最后已推送提交为 `abcce26`。）
- `abcce26..074be97`：BC 评审 P0 三项重做——monitor WARN 分类循环移至函数末尾恢复
  fail_if_production 生产契约；digest 去重加 provenance upgrade（manual/legacy→cron 不再
  skip）；natural_by_date 改独立 last-writer-wins 防迟到 manual 行顶掉 natural 天。
  2579 passed / 8 skipped，静态门全过。
- `e6629a6..efcc202`：BC 评审 P1 四项重做——stale-open 评估失败记 error_code 并由
  classify_snapshot 消费（unavailable → WARN，fail_if_production 升级）；本地账本读取
  包 try/except 与远端降级对称；recovery 计数补 `or 0` 防历史行 int(None)；wandering
  种子行过滤加 natural_cron 门控。另修 digest 渲染测试日期腐化。2579 passed /
  0 failed / 13 skipped（本机当日基线 2570+1F/13，口径见 BE 验证结论），静态门全过。
- `e72f2c1..069484a`：BC 评审 P2 三项重做——快照加 manual_day_count 补齐无 natural
  覆盖日期分区、latest_natural_date 改 natural-only（cron 真实新鲜度）并新增
  latest_recorded_date 保留全行展示口径；monitor 三参数全 None 隐式第四路径改无条件
  else 置 unavailable（错误码 ledger_state_not_supplied）；created_at 归并比较改时间戳
  解析（微秒省略边界）并抽共享 helper。2587 passed / 13 skipped，静态门全过。
- `54aea76..eaf718c`：BC 评审 P3 五项清理——ledger 读取走 jsonl_io 契约并计数坏行；
  trigger_class 判定抽 execution_gate.resolve_trigger_class() 防漂移；stale-open 循环
  建 id→record 索引去 O(P×F)；探针消费抽 _consume_remote_probe() 统一 fallback；
  dashboard latest 行改 natural_cron-only。BC 评审 15 项全部关闭。2601 passed /
  13 skipped，静态门全过。
- `eaf718c..520f1be`：P0–P2 观测/看板闭环收尾——Recall Facade shadow 改为真正 output-neutral
  （仅 apply_canary 才追加实时 section）；State Overlay 跨会话/候选开放线索去重；新增
  `memory_os_full_monitor_refresh.py` 原子发布每日 Monitor 快照，Dashboard `fullMonitor` 新鲜度
  阈值对齐每日 02:30 节奏（3600s→30*3600s）；Lane Status 核心/可选 cron 契约补齐三项并修
  no_agent 误判为 agent 工作。2613 passed / 13 skipped（本地），静态门全过。
- `520f1be..7e4e2ea`：将优化路线图从 BC 代码加固清单升级为生产闭环与认知伙伴
  演进路线图 v2；更新当前基线、证据成熟度、targeted deploy、隔离 CI、语义/状态机收敛和
  Continuity/Relevance/Restraint/Review/Warmth 五维伙伴主线。仅文档变更，无运行时行为修改。
- `7e4e2ea..95e51f1`：路线图 v2 状态枚举澄清为仅约束 checklist 条目本身，R1–R6 聚合标题允许
  组合式描述性标签；为 R1.1 的 V2-A/B/C/D 代号补一行指向真实源码定义处。仅文档变更。
- `a5c1c04..（Gap Note roadmap v2.1 文档变更）`：将有界不确定性披露纳入 R1.2/R5.2；先以
  metadata-only shadow candidate 观察 Owner-level conflict 与 stale task，随 Recall apply-canary
  才允许一行预算内渲染；全局 attribution gap、无对象级 freshness 和长期重复时长不冒充答案盲区；
  明确不引入独立 explain/debug 路线。仅文档变更。
- `b52173b..（BJ，本节）`：ExecutionGate helper completion 补 disabled 分档——lane 对应 cron job
  被禁用（`enabled=false`）时不再误落 `helper_completion_missing`，改记独立
  `helper_completion_disabled_count`/`_lanes`，`classify_snapshot` 新增对应 WARN 码，守恒公式同步
  更新；`_execution_gate_helper_completion_summary()` 首次获得直接单测。定向 218 passed；全量
  3013 passed / 9 failed（Windows 本地 pre-existing，经 stash 验证与本次改动无关）/ 13 skipped，
  静态门全过。另记录：本文件自 `f99062c` 起数十个提交未追加稳定化记录的历史流程缺口。
- `4c43f05..（BK，本节）`：诊断并修复 BJ 记录的 9 项 Windows 本地测试失败中的 7 项——
  `plan_deployment()` 相对路径改 `.as_posix()`（与 `_deployed_file_paths()` 对齐，修复
  `postcheck_deploy()` 跨主机文件集合比对失真）；`classify_snapshot()` 的 `status_tool_contract`
  补齐 `doctor` 同款 `isinstance` 防护，修复 `None` 触发的 `collect_snapshot()` 整体崩溃（e2e 测试
  验证由崩溃转 PASS）；两处测试用正斜杠字面量匹配 Windows 原生分隔符字符串的假设修正
  （`test_deploy_community.py` 用 `.as_posix()`、`test_memory_os_mount_isolated_pytest.py` 用
  `PurePosixPath` 构造目标端路径）；`test_memory_os_deploy_clean_host.py` 三处硬编码
  `/usr/bin/python3` 改 `sys.executable`。剩余 2 项（pytest_policy skip-count）诊断为本机
  `%TEMP%`/Documents-and-Settings-junction 触发的 vanilla pytest 收集重复，非项目代码缺陷，
  记录不修复。全量 3021 passed / 2 failed（精确为上述两项环境伪影）/ 13 skipped，静态门全过。
- `004a16b..（BL，本节）`：路线图升 v2.6——基线刷新到已合并的 `004a16b`（release ≠ deployed 两层
  分述）；P2 helper 债务清单以 caller 证据逐项核实并补入 `natural_evidence`、`restraint` 两项漏记；
  `timeutil` 债务量化为 10 处具体 ad-hoc parser；natural-row 生产实现位置纠偏；另记录 codegraph
  过期依赖边须经 grep 复核的工具经验。仅文档变更。BL.1 补充：CI 新分支空树 fallback 暴露 5 个
  历史文件的尾随空白/EOF 空行，纯空白清债（52 passed / compile ok / 空树全树 diff --check 干净）。
- `523b895..（BM，本节）`：`/code-review` 复审已落地的 roadmap v2.6 代码，14 项发现（2 CRITICAL）
  经 advisor 核实修复方案后全部处理——rh26/low_clue_ingress 探针失败改显式 FAIL（而非只加
  isinstance 防护换成静默 PASS）；disabled cron job 不再丢失已记录的 boundary_true/error 证据；
  retired cron fallback 补齐 legacy raw 脚本名（非空 name 防碰撞）；deploy 本地 env 前缀不再依赖
  真实 `env` 二进制；deploy/`_run_probe` 补 TimeoutExpired 捕获与显式短路 FAIL；
  compaction_stats/hook_marker_counts 显式加长 timeout；探针脚本 def/调用分界点补显式哨兵注释
  （4+3 处测试改用哨兵切分）；`memory_os_v24_final_verify.py` pathspec 存在性谓词改测正确的树。
  另确认 2 项无需改动（classify_snapshot 其余 ~45 处 `.get()` 无真实 None 触发路径；
  `review_reply` 假 token 探针本身安全）。5 项用 revert→fail→restore→pass 实测验证。全量
  3021→**3035 passed** / 2 failed（同 BK 环境伪影）/ 13 skipped，静态门全过。
- `2b23537..（BN，本节）`：本机 checkout 对齐 `origin/main`；Linux 隔离全量 **3041 passed /
  9 skipped / 0 failed**，治理静态门全过。通过 drift gate 与备份后 targeted-sync 4 个既有生产目标，
  fresh import/哈希/反事实通过；Full Monitor 实跑为 97 pass / 4 warn / 1 fail，唯一 FAIL 仍是
  `v2_exposure_schema_era_unhealthy`。未 full deploy、未改 manifest、未重启 Gateway、未触碰 canonical data。
- `3361dcc..（本节）`：路线图升 v2.8——对 Sannai 的 11.10 小院子设计做工程审查，新增 11.11 节：
  8 项边界修正（partner 回复移出 shared/ 保持单 writer、轻量不豁免异构三判、soul.md 为 Owner
  边界、伙伴可见面收窄为 sannai_says+自身目录、回复仅 exposure、lightfriend 入 roster、Track A
  证据不折算 11.7、允许安静不回复）；修正后数据布局与交互流、复用地图（唯一净新增模块
  `community_partner_runtime.py`）、6 步实施计划（每步含反事实测试要求）与独立 Track A 出口
  条件；第 14 节优先级追加第 7 项。11.10 原文保持 Sannai 原貌不改。仅文档变更，无运行时行为修改。
- `8c3a28f..（BO，本节）`：修复 GitHub CI FAIL——`test_tiny_benchmark_uses_synthetic_corpus_and_reports_slo`
  在 mount-isolated runner（`unshare --mount` + 共享 GHA runner）下墙钟抖动导致
  `report["pass"]` 偶发 False（本地 15/15 次重跑全过，非功能回归，历史已复发两次）；
  测试改为最多 3 次独立 tmp 子目录重试、任一次达标即通过，仍未达标则保留最后一次结果
  并把 `slo_checks` 附在断言消息里；未改 `DEFAULT_SLO`/`run_benchmark()` 生产语义。
  无新增/删除测试，全量 3035 passed / 2 failed（同 BK/BM 既有 Windows `%TEMP%` 环境伪影，
  经 stash 对照验证与本次改动无关）/ 13 skipped，静态门全过。
- `609bc40..（BP，本节）`：复审 Sannai v2.9 提交（11.12 窗台/一起看/兴趣花园）——修复三项
  GitHub CI FAIL（`write_surface_check` 新增 8 处写入未登记；`partner_create` 测试断言旧
  错误文案；推送后从真实 GHA 复现的 `community_partner_runtime.py` 6 处行尾空白，新分支
  空树 fallback 触发，同 BL.1 根因）；顺带补齐 4 个文件缺失的 `encoding="utf-8"`（无法反事实，纯 portability）；
  新增 5 个测试覆盖此前零测试的 `community_table.py`/`community_interest_garden.py`；
  记录（不重构）3 处实现落差——`community_partner_runtime.py`/`community_table.py`/
  `community_interest_garden.py` 零调用方、实际 cron 路径是内联重写副本，导致限流约束缺失、
  shared 写入门控被绕开、`_extract_topics` 关键词分叉——写入路线图 11.12.7；另确认
  `community_snapshot.py` 新增的 `unread_partner_replies` 字段计算语义无关的两个计数器，
  当前无消费者，未修。全量本地（Windows）3032→**3039 passed** / 3 failed（2 个同 BK/BM
  既有 skip-count 环境伪影 + 1 个全量套件下资源争用偶发 FAIL、隔离重跑 100% PASS，均经
  stash 对照验证与本次改动无关）/ 13 skipped，静态门全过（import cycle 173/0、write
  surface 163/163、static hygiene、public checkout probe、git diff --check）。
- `b89e9c4..（BQ，本节）`：Sannai 社区功能整体迁出为独立仓库
  [sannai-community](https://github.com/btnalit/sannai-community)——8 个模块文件、3 个脚本、
  路线图 §11 设计文档随迁；Hermes-Memory-OS 侧移除 4 处集成点（cognitive_loop 步骤、CLI 子
  命令、installer 数据布局初始化、state_overlay 三文件的 community_snapshot 分区），零残留
  钩子。生产主机数据/cron 未处理（按范围要求）。全量本地（Windows）3039→**2968 passed**
  （有意减少 71，对应 6 个整体迁出的测试文件 + 2 个混合文件定向裁剪，非回归）/ 2 failed（同
  BK/BM/BO/BP 既有 skip-count 环境伪影）/ 13 skipped，静态门全过（import cycle 165/0、write
  surface 151/151、static hygiene、public checkout probe --strict、git diff --check）。
- `47bbc13..（BR，本节）`：全项目审查改按**不变量**切片（ExecutionGate / 无声失败 /
  OwnerGate 授权 / import 拓扑 + substrate 权威 / 并行注册表），28 项发现分 8 个文件互斥包
  修复。最重一项为**已实测复现的所有者授权绕过**——`oa_` 是无密钥确定性哈希，仅凭记录 id
  即可离线伪造 revoke/demote 并绕过 `require_recorded_digest`（且在"已存在摘要"的生产常态下
  同样成立），改为按风险类默认拒绝；另修 ExecutionGate 许可证泄漏 ×2、substrate 自称权威、
  cron 注册表漂移（`clearance_cycle` 从未被安装）、StateOverlay 六处 section 副本、4 处错误
  可见性缺口、community 主机退役机制 + 公开文档漂移。顺带查实
  `sweep_unavailable_open_proposals_on_flag_flip` 因 `append_terminal(detail=...)` 参数不存在
  而**从未成功清扫过**。全量本地（Windows）2968 passed / 2 failed → **3023 passed / 0 failed**
  / 13 skipped（+55），**首次全绿**；静态门全过（import cycle 0 环、write surface
  unclassified 0、static hygiene、public checkout probe --strict exit 0、git diff --check）。
  `oa_` 密钥化、monitor 11 组件采集接线、主机侧退役执行均**有意未做**并在 BR 节登记原因。
- `38fa4e0..HEAD`：Hermes cron 归类合并——`MemoryOSCronSpec` 拆为 lane 治理身份（21 条不变）
  与 group 调度面（9 条），active-closure **19 个 cron job → 8 个**，新增
  `memory_os_cron_group_runner.py` 按 due 门控逐 member 开自己的 ExecutionGate envelope。
  实测动因：00:00/12:00 各有 5 个 job 同时争 `execution_gate_index.json` 的 15 秒锁
  （合并后触发 336/天→172/天；并发 5→**3** 而非最初所写的 5→1，见方案文档 §10 实测修正）。两条阻断前置先行：monitor 新鲜度改按 lane
  `due_interval_minutes` 取（否则 4 条 lane 窗口塌缩、2 条永久 stale）、旧 19 个 per-lane job
  名显式归入 `superseded_by_group_tick`（否则每台升级主机 monitor FAIL）。顺链修掉
  `classify_hermes_cron_jobs` 的**三份**拷贝、dashboard CORE/OPTIONAL 集合重叠、
  `install_memory_os.sh` 与 `deploy_l3_probe.py` 两处会导致 lane 双跑的自建 job，
  并补上 helper subprocess timeout、group 非阻塞锁、成员失败隔离、lane 级停用，
  以及独立缺陷 `execution_gate_index.json` 无裁剪（新增 `prune_sidecar_index`，保留 2000 条）。
  3023 → **3058 passed / 13 skipped / 0 failed**（+35），静态门全过。
  未部署 3.200，`live_monitor_pass` 未取得。
- `4d4ea17..HEAD`：3.200 定向部署结果登记（BT）+ 自我更正。BS 的「未部署、
  live_monitor_pass 未取得」关闭：三个 tick 由真实 scheduler 于 20:00:56 CST 自然触发返回 ok、
  组内未到期 lane 正确 `skipped_not_due`（due gating 生产验证通过），unregistered/naked/
  helper-completion-missing 均为 0。**更正 BS 与实施提交里「同分钟并发 5→1」的错误说法——
  实际是 5→3**（三个 tick 的 cron 表达式在整点重叠），真正拆掉 15 秒锁超时风险的是
  `prune_sidecar_index()` 把重写成本压成有界 O(2000)；错开 tick 分钟可彻底消除碰撞，
  方案文档 §10 给出建议但未实施。Monitor 唯一 FAIL `v2_exposure_schema_era_unhealthy`
  已核对代码确认由生产观测数据成熟度驱动、与 cron 调度面无耦合。新登记待办：
  `scripts/` 下 4 个脚本的 installed-layout import shadow（已在生产触发一次，
  目前靠主机本地覆盖绕过，仓库缺陷未修）。纯文档，无代码改动。
- `fe53dd3..HEAD`：BT 两项发现全部修复（BU）。① tick 分钟错开为
  `2,17,32,47` / `7,37` / `12`，**实测同分钟最大并发 3 → 1、触发次数保持 172/天不变**，
  至此 BS 最初宣称的「并发 1」才真正成立；测试断言改为从注册表派生并新增两条不变量
  （不得同分钟启动、错开不得降低频率，后者以 active-closure 实际安装的 lane 为口径，
  同时作为激活 `clearance_cycle` 的绊线）。② 4 个脚本的 installed-layout import shadow
  改为条件式 bootstrap（仓库布局用 repo root，否则回退 runtime root），新增
  `test_memory_os_installed_layout_imports.py`：静态不变量 + 端到端遮蔽复现 +
  **反事实**（塞回旧 bootstrap 必须复现 `No module named 'plugins.memory'`），
  且豁免名单从安装器自身的 `SOURCE_*` 声明读出、被验证而非被断言。
  同时更正 BT 里「共 4 个」的说法——严格复扫是 7 个无条件插入，其余 3 个是
  仅从仓库运行、不随安装分发的工具，现状正确未动；另有 3 个此前误判为缺陷的其实是
  检测式假阳性。3058 → **3065 passed / 13 skipped / 0 failed**，静态门全过。
- `3dbbb9b..HEAD`：修 BU 的 CI 红（BU.1）。installed-layout 测试在 CI 上**空过**——
  CI 的 `pip install -e '.[dev]'` 让 `plugins` 无视 sys.path 即可导入，
  于是反事实无法失败、正向断言也不成立（本机未装 editable 故复现不出）。
  子解释器改用 `-S -E` 隔离（`-S` 切 site-packages 即 editable install，
  `-E` 切 `PYTHON*` 变量而保留 `HERMES_HOME`），新增前置条件测试断言隔离本身有效，
  正向断言由"无遮蔽报错"改为"traceback 出现 runtime 树路径"。
  已用一次性 venv 复刻 CI 条件验证：旧版在其中复现出与 CI 一致的失败、新版 6 项全过。
  3065 → **3066 passed / 13 skipped / 0 failed**，五项静态门全过。
- `6273e8b..（BV，本节）`：对 `6273e8b` 的代码评审与修复，12 项发现修 9 项。最重一项是
  **`apply_canary` 上「关闭开关过期即静默恢复输出改写」**——该提交把解析默认值翻成 `True`
  以救活 `shadow` 观测车道，但 `apply_canary` 会往 live prefetch 追加
  `Recall Facade (unified)` 段，于是 provisional `false` 一到期就无声恢复输出改写，
  正是它所修 bug 的镜像；改为按模式取默认值（`shadow → True`、`apply_canary → False`）。
  另修：kill switch 路径自行拼装 + 「文件缺失→直接 True」的 **fail-open**（改走
  `override_store_path()` 且不再短路）；`_recall_facade_init_errors` 只写不读且注释不实；
  status 无法区分「被 Owner 关掉」与「mode 本来 off」（新增 `mode_live`）；
  `_roots is None` 污染 init 哨兵致 roots 后注入后永久返回 None；缓存的 facade 会被以
  另一个 arbitration mode 交付（对象构造时固化模式，`initialized` 短路先于模式判断）；
  onboarding wrapper 分支零覆盖（反事实实测可回退）；150ms 到期测试墙钟 flaky。
  **并查实该提交把 Windows 本机全绿基线打破了**——它自己新增的 onboarding 测试断言
  `st_mode & 0o100`，在 Windows 恒为 0，CI（Linux）绿而本机红，与 BU.1 互为镜像；
  这首先是一条流程发现（本机必红的测试被推上 main，DoD 第 4 步未执行）。
  有意保留 1 项（严格校验的全账本 fail-closed 口径），
  显式记录不做 2 项（monitor 对 `recall_facade` 的采集接线；`prefetch()` 三个旋钮合并为一次
  `resolve_knobs()` 以真正消除热路径重复读）。3077 passed + 1 failed →
  **3085 passed / 13 skipped / 0 failed**（净 +7），五项静态门全过。
- `192e056..（BW，本节）`：接手 WIP checkpoint。**102 个 error 是一个根因**——
  shell 测试从 `sys.modules` 弹掉 `plugins`/`plugins.memory` 却留下已导入的子模块，
  于是 `from ... import` 成功而 `import ... as` 在 `getattr(plugins, "memory")` 上炸，
  新增的 autouse conftest 恰好每条测试 setup 都跑这行，排在其后的测试全灭；
  改为快照/还原**模块对象本身**（清名字会换掉类身份，把响亮失败变成静默错patch）。
  GitHub CI 对该 commit 已是红的（run 30697011570），交接方 `gh` 未登录故未核验；
  另修交接未提到的第 4 条本机失败（正斜杠字面量比 Windows 分隔符，同 BK）。
  Owner 写入权威两份实现中**跑在生产上的是弱的那份**（不验 recorded-digest source /
  不验 action 白名单 / 不验 token hash 长度 / 消费比对不含 `action_token_hash`），
  统一抽到 `owner_write_authority.py`（只依赖 roots/store/JSONL，无 capability 单例）。
  测试授权由全局 autouse 改为 21 个文件显式声明，Owner ingress/安全用例去掉授权后依然全绿。
  `approve_external_evidence` 两处缺陷：`_review_actions` 无条件发放 +
  `_digest_item` 白名单丢掉 `external_review_eligible`，导致**真 tainted 候选反而走普通分支**
  （既有测试此前一直因无条件 token 而假通过）。`candidate_cluster` 移出
  `LIVING_MEMORY_TARGET_TYPES` 判定为正确（集合只应含已写入的记录级目标，
  `candidate` 从来不在其中），但 monitor 内嵌 fallback 拷贝未同步、已修并以 AST 比对钉死。
  27 文件复审另得 5 项：backfill 脚本被新 fail-closed 契约打断（已补 envelope 参数）、
  gate error_record 两种形状、`read_candidate_queue` 静默丢弃 schema 非法行（会被压缩永久抹掉）、
  被拒授权无任何痕迹（补 audit）、gate 对 reject 候选也跑（改惰性）。
  3010 passed + 1 failed + 102 errors → **3119 passed / 13 skipped / 0 failed / 0 errors**，
  五项静态门 + closure matrix 全过。有意未做 2 项（blank-host smoke 不再覆盖永久写路径；
  `_rebuild_gate_index_from_records` 每次 resolve 全账本重读的热路径成本）。
- `2d40c12..（BX，本节）`：每日 owner 审批议程三缺陷同源修复。owner 反馈「看不懂在批什么 /
  第一条永远是这条 / 真实的看不到」——先用 24 provisional + 1 session_mirror 的 fixture
  逐字复现生产文案（A25、「25 项 / 未展示 24 项」），确认 A1–A24 是被
  `_assemble_living_memory_delivery_items()` 结构性挡在投递之外的项。**该过滤是
  `39d1f2e` 有意引入且被 monitor 硬约束的 delivery choke point，放开会当场打红生产**，
  故修口径而非修过滤：表头改按 section 实际来源人群计数（`visible_*`，缺失回落旧字段），
  并新增一行如实披露被过滤 backlog 的去向；按 Section W 第 5 条扫出
  `review_suggested_total` 同款缺陷一并修。「下一页」原用 `action_required_shown` 当偏移量
  索引进**未过滤**列表（展示 A25 却返回 A2、静默跳过 A1），改为按 `review_item_id` 身份续页
  并回填 `offsets` 既有语义（grep 到既有测试断言 `offsets==2`，Section W 第 2 条当场兑现）。
  session_mirror 审批项文案由 `fingerprint=smfp_…` 改为渲染 `_safe_pending_session()`
  早已备好的脱敏展示面，并在 `_digest_item()` 显式携带 `pending_session_preview`
  （与 `external_review_eligible` 同款丢弃陷阱）。另修 cron agent prompt 的对称示例——
  它教会模型给只有 approve 的项补出 `memory reject oa_…`，那条命令必被拒绝。
  11 条新测试，实测 revert→fail→restore→pass 有 8 条反事实。自审两次抓到同族缺陷出在
  修复自身：① 披露行广告了一条无 operation 可路由的回复（「查看临时记忆」），改为只披露不邀请；
  ② 身份续页后 `next_offsets` 仍用 `start + len(selected)`，在「已展示项排在最后」这一
  正是本例的形状下会让后续 `page` 静默跳过 `cry_03`，改为落在实际返回的最后一项之后。
  两处都补了测试钉住。
  3119 → **3130 passed / 13 skipped / 0 failed**，四道静态门全过。
  仅 `local_pass`：未跑 3.200 live monitor、未部署。
  留 1 项待 owner 决策：session_mirror 审批目前无 reject/defer（待办第 4 项）。
- `54296ea..（BY，本节）`：收网评审后按 owner 指定开发待办第 4、5 两项（第 6 项 `oa_` 密钥化
  明确不做）。**第 4 项最重的一点不是加两个 action 类型，而是查实 reject 若只关闭 target 会
  饿死整条队列**——`SessionMirror.scan()` 选择是纯队头且无排除状态，被拒会话每次仍在队头、
  短路返回，后面所有会话永不出现，lane 毕业后真正导入的还是它；排除因此下沉到
  `session_mirror.py` 自己的 `_owner_rejected_fingerprints()`，且**刻意读 owner action 账本
  而非写进 state**（`_rebuild_state()` 从事件重建，存 state 的拒绝会在修复时无声消失）。
  defer 则不能按 target 关闭（`target_id` 随队头 fingerprint 变，换个会话又问一遍），
  改为 lane 级判定并照搬 `defer_candidate_cluster` 的 `deferred_until`/7 天/过期重开契约；
  `_closed_targets` 的过期判定抽成 `DEFER_ACTION_TYPES`（漏登记 = 永久关闭而非暂停）。
  `lane_deferred` 设为必填关键字参数，当场把两个调用方炸成 TypeError 而非静默漏改。
  第 5 项 `cron_lane_disabled.json` 升 v1 带 reason/actor/disabled_at，两种旧形状继续解析，
  「损坏文件不停用任何 lane」的失败方向不变，**group runner 的第二份拷贝同步**
  （否则记录原因这个动作本身会把停用的 lane 重新跑起来），monitor 新增「停用但无原因」
  独立 WARN 码。顺手关闭待办 1 并更正其严重性：**未注册 WARN 码在 clean-host 是 FAIL
  不是 WARN**，与 deploy 是否接入 onboarding 无关；五个码一律按 `warn_if_production` 注册，
  不把现有生产 WARN 升级成 FAIL。7 项反事实全部 revert→FAIL→restore→PASS 实测。
  3130 → **3148 passed / 13 skipped / 0 failed**（+18），四道静态门全过；
  `static_hygiene` 的 compileall 在本 worktree 内 FAIL 已定位为 Windows MAX_PATH 伪影
  （镜像路径 261 字符超 260 一个字符，换短 prefix 后 exit 0），非代码缺陷。
- `（BY.1，本节）`：3.200 补上 BW(#8)+BX(#9) 部署——收网评审查实生产 `deployed_head=5bf0022`、
  两个已合并周期从未部署，owner 每日议程一直是坏渲染；且 manifest 声明的
  `active_runtime_path=/opt` 停在 CI 红的 `192e056`。`/opt` ff 到 `54296ea`、备份后
  `deploy_memory_os.py` production-safe 走完 apply（`fail=[]`、未重启 Gateway），
  部署后 owner_actions sha 与 `54296ea` 逐字节一致、manifest 已绑定；
  Full Monitor **98 PASS / 7 WARN / 1 FAIL**，唯一 FAIL 仍是与本次无关的
  `v2_exposure_schema_era_unhealthy`（且实测在推进：lag 74.4h→26.5h）。
  新登记一个仓库缺陷：`deploy_memory_os.py --timeout` 默认 60s < 自身 compat 门实测 63s，
  默认参数下 preflight 必失败，且错误码 `compat_json_invalid` 把超时误报成 JSON 非法。
- `（BY.2，本节）`：修 BY.1 登记的 deployer 超时缺陷。两件事：`--timeout` 默认 60s 抽成
  `DEFAULT_COMMAND_TIMEOUT_SECONDS = 300`（自身 compat 门在 3.200 实测 63s，默认参数下
  preflight 必失败；低配主机更慢，且这是上限不是等待）；`_classification_failures()` 把
  超时/崩溃/真·JSON 非法三种情况分成 `compat_timed_out`（带调 `--timeout` 的 hint）、
  `compat_command_failed`、`compat_json_invalid`，不再把"没给出答案"报成"答案格式不对"。
  **按 Section W 第 5 条扫出这不是孤例**——三个探针分类器（llm_judge / cron_adapter /
  boundary_runtime）完全相同的缺陷，抽 `_probe_transport_fault()` 一并修；另三处本就先判
  exit_code，已正确未动。`exit_code` 缺省取 0 保证既有调用行为不变。
  4 项反事实 revert→FAIL→restore→PASS。3148 → **3159 passed / 13 skipped / 0 failed**（+11）。
- `01356df`（BY.3，本节）：BY 合并后部署 3.200 并端到端验证。**刻意不带 `--timeout` 跑 apply**
  以在生产上验证 BY.2——preflight 通过、全程 `fail=[]`，这在修复前不可能。部署后核验
  session_mirror 三条终态动作、`DEFER_ACTION_TYPES`、lane disable v1 schema 均在线；
  用主机上刚部署的 `build_lane_disable_state()` 补写 `expression_feedback_request` 停用审计记录
  （**未编造原始理由**，如实写明未知 + 本条为补记）。item 5 端到端成立：
  `..._disabled_undocumented_count` **1 → 0**、对应 WARN 消失，而 `..._disabled_count` 仍为 1
  且 records 带出 reason/actor/disabled_at。最终 **97 PASS / 6 WARN / 1 FAIL**，
  唯一 FAIL 仍是 `v2_exposure_schema_era_unhealthy`。另：部署后首次 monitor 的
  `shell_alias_no_env_failed` 重跑不复现，为待办第 3 项并发争用风险的首个实测实例。
- `87e3ce8..`（BZ，本节）：接线闭环批次 C —— continuity **只分级披露、不过滤**。
  修两个静默失败陷阱：`age_seconds` 的 `allow_naive=False` 让 naive 戳永远 UNKNOWN、
  永远不 stale（判据是与 `task_state._parse_timestamp` 的同路径一致性，不是"宽松些"）；
  `current_task_is_stale()` 对 `None` 返回 `True` 把"不存在"当"过期"（新增
  `current_task_grade()`，None→UNKNOWN）。产出 `stale_task_revision` ——
  gap_note 那两个 eligible 码此前**全仓无生产者**，C 就是缺的那个上游。
  接线在 `build_prefetch` 所有 early-return 之前，覆盖四条路径；kill switch
  `lane_continuity_freshness_enabled` 为 `lane_switch`、默认 True（取消的是等待窗口，
  不是关断能力）。**三处方案与实测不符已回写方案 §4.2**：overlay 投影里根本没有时间戳
  （`OverlayEntry` 只有 text/source/source_kind）；trap #3 的 StructuralWriteGate 在
  无 envelope 的每轮热路径上会每次 `StoreError`、亲手制造它要防的静默失败，改为
  `ALLOWED_WRITE_SURFACES` 登记 `report_only_continuity_freshness`；open_threads
  明确不在 C 范围并登记原因。反向评审自查出一处真缺陷：stale 锚点会让账本**每轮追加一行**，
  改为按签名只记状态迁移。顺链查出 D 的接点——`recall_facade` 早已把 `current_task_revision`
  送进 recall plan，但那个 plan 没有 `findings` 键。
  6 项反事实 revert→FAIL→restore→PASS。3035 → **3070 passed / 13 skipped / 0 failed**（+35），
  四门全过。**仅 `local_pass`，未部署 3.200**（按方案裁定等 C→D→E 整链）。
