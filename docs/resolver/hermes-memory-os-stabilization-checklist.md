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

### 按 Section W 第 5 条扫同类模式，查出保留策略登记缺口（本轮补上）+ 一个既有缺陷

`metadata_retention.py:62-75` **已经**为两个同类 report-only shadow 账本
（`graph_layer_shadow`、`substrate_recall_shadow`）登记了保留策略。
新账本不登记就会无限增长而兄弟被清理——已补登记，共用同一个 `shadow_retention_days`。

**登记之后还差一步，差了就是"登记了但永久空转"**：`_record_created_at()` 只认
`created_at` / `ts` / `timestamp` 三个键。本模块原本把时间写成 `recorded_at`，
于是每条记录都被判为"没有时间戳" → 永远 `retained_records` → 登记形同虚设。
已改名为 `created_at`，并在字段旁写明这个名字是承重的。

**顺带查实两个兄弟账本今天就有这个缺陷**（Section W 第 5 条的"修掉**或记录**每一处"）：
`graph_layer_shadow` 的记录写的是 `recorded_at`，`substrate_recall_shadow` 的记录
**根本没有任何时间字段**——两者都已登记保留策略，但**都永远不会老化**。
**本轮选择记录而不修**：修它等于让两个从未被剪过的生产账本首次开始进入归档计划，
是超出批次 C 范围的行为变更，应当单独决策。已登记为待办第 9 项。

（实测：`_record_created_at({"recorded_at": ...})` → `None`；
`_record_created_at({"created_at": ...})` → 正常解析。）

### 反事实覆盖

**8 项全部 revert→FAIL→restore→PASS 实测**：
naive 时间戳分级（2 个测试同时红）、None≠stale、接线调用本身
（byte-identical 半边会退化成 `assert 0 == 1`）、`max_age_hours=0`
（改成 24 立即 `assert 24 == 0`）、write-surface 登记（门 `pass`→`fail`）、
状态迁移去重（5 轮写 5 行而非 1 行）、保留策略登记（`StopIteration`）、
`created_at` 字段名（改回 `recorded_at` 立即 `assert 2 == 1`）。

> **第 8 项的第一版测试是坏的，值得记下来。** 它的 fixture **手写** `created_at`，
> 于是生产代码把字段改名后测试照样通过——**它测的是 retention 读得对不对，
> 不是生产代码写得对不对**。改为用真实的 `build_continuity_freshness_record()`
> 产出记录后才真正钉住。这正是第 8.0 条的同一个毛病换了个位置出现：
> 手写 fixture 等于把"我以为它写什么"当成"它写什么"。
>
> 修正过程中还踩了一个自己造的坑：记录的 `created_at` 是**分级发生的时间**，
> 不是被分级任务的年龄。第一版把两者当成一个，于是两条记录的 `created_at` 都是
> `now`，谁都不满 45 天。

**目标反事实**（一条测试钉死整个设计）：
`test_continuity_grades_stale_task_without_changing_live_prefetch_output` ——
过期对象被判 STALE **且 live prefetch 输出逐字节不变**。两半都必须断言：
只断言 byte-identical 的话，钩子静默 no-op 也会通过，所以同一测试同时断言账本确实写了。
基线取"同一次调用但把钩子 monkeypatch 成 no-op"，**不是**第二次 live 调用——
`build_prefetch` 内嵌 `{age_h}h前` 等 now 派生文本，两次 live 调用可能因与 continuity
无关的原因不同。

### 完成前复核查出的一处自己的错误陈述（已更正）

**「全仓没有任何生产代码产出 `stale_task_revision`」是错的**——该说法来自方案 §4.1，
本节初稿原样沿用，并写进了 commit message、PR 正文与两处 docstring。
实测 `recall_arbitration.py:86` **就在产出这个字符串**。已逐处更正。

正确说法需要四个限定，缺一个都会让后来者误判：

1. 它以 **`"reason"`** 为键，而 `gap_note.build_gap_note_candidate` 读 **`"code"`**
   ——**结构上** gap_note 看不见它，与它是否运行无关。
2. 语义不同：判的是 STATE_OVERLAY 对象的 `task_revision` 与当前修订号**不相等**
   （identity 比对），**不是**年龄。
3. 默认配置下**休眠**：`config.py:53` 的 `recall_arbitration.mode = "off"`，
   于是 facade 根本不构造、`build_recall_plan` 从不运行。
4. 它的用途是 **suppression**（`suppressed.append(finding); continue`，丢弃该对象）
   ——**正是本裁定为 continuity 否决的那个行为**。

所以两者是互补而非重复：**arbitration 按修订号相等性抑制，本模块按年龄披露。**
已在 `STALE_TASK_REVISION_REASON_CODE` 上写明这四条，
并登记为 **D 必须显式选择渲染哪一个**，而不是假设只有一个来源。

**顺带纠正一处遗漏**：本节与方案 §4.2 原先只列了两个生产时效过滤器（7 天 / 48 小时），
`recall_arbitration` 的 freshness guard 是**第三个**（默认 `shadow`，且 mode=off 时休眠）。
已补入。

**并已核实 advisor 提出的 revision 单调性疑虑不成立**：`recall_arbitration:85`
对 `task_revision` 只做**相等性**比较，没有任何消费者把它当锚点计数使用。
因此 `revision`（＝账本行号，生产里因 `_supersede_active_anchors()` 先写墓碑行
而每次锚点写入递增 2 以上）出现跳号是无害的——它在本模块里只作为签名的身份成分。
本节的测试直接写行、未经过墓碑路径，这一点如实声明。

### 测试数量

3035 → **3071 passed / 13 skipped / 0 failed**（+36：continuity 单元 +15、prefetch 接线 +20、保留策略 +1）。

> **口径声明**：3071 是本 worktree 实测；**3035 是推断而非实测**
> （3071 − 本轮新增 36，并与批次 B 当日记录的 3035 相互印证），未在 `main` 上重跑基线。

### 门

import cycle（`cycles: []`）/ write surface（`unclassified_count=0`）/ static hygiene
（含 compileall）/ public checkout probe `--strict` exit 0 / `git diff --check`
及 `git diff --check origin/main...HEAD`（按区间，非仅工作区）—— 全过。

> **关于 BY 记录的 Windows MAX_PATH 伪影**：本 worktree 的 `compileall` 子项通过，
> 但这**只说明本 worktree 路径够短**（BY 已诊断该问题按路径长度触发，目标路径 261 字符
> 超 260 上限一个字符）。**不构成"该问题已消失"的结论。**

### 未验证项（如实声明）

- **仅 `local_pass`。未部署 3.200**：按方案第 7 节裁定，`/opt` 同步与部署验证
  在整条 C→D→E 链落地后一次性做。因此本节**没有** `live_monitor_pass` 证据。
- 分级只覆盖 `current_task`；open_threads / recent_decisions / capability_map
  的分级路径有单元覆盖但无生产数据流（见上文第 3 条，已登记原因）。
- 新账本 `system/continuity_freshness.jsonl` 尚无 monitor 字段与保留/压实策略。
  按状态迁移去重后体积有界，但**长期无压实**这一点未验证，登记为待办。

---

## CA — Owner 报告「关键事实漏失」的实测定位 + 三项并行修复（2026-08-04）

Owner 原话：「我发现很多"关键事实"没存入记忆，导致召回漏掉了一些。」
本节记录**实测定位**（含两处推翻本会话自己论断的证据）与随之做的三项修复。

### 定位结论：不是一个 bug，是三个独立成因

| | 位置 | 性质 |
|---|---|---|
| **① 捕获截断** | `__init__.py:1828` `_turn_summary` = `_clip(user,140)` + `_clip(assistant,140)`，**硬编码，全仓无 knob**；正文只以 `user_sha256`/`assistant_sha256` 落盘 | 事件层只有 280 字 |
| **② 无事实抽取** | `inner_drive.py:294` `body=f"Remembered from event {event.id}: {event.summary}"` | 候选正文就是那 280 字加前缀；①不修这里也拿不到更多 |
| **③ 候选在召回里几乎不可见** | `prefetch.py` `_should_include_candidates` | 查询不含 `candidate/crystallized/候选/结晶/沉淀/长期记忆/审查队列/待审` 就 `return []`，**与相关性无关** |

`runtime.py:111` 的候选生成读的是 `store.read_events()`，即那 280 字事件——所以①②③在一条链上。

### 3.200 只读核实推翻了本会话两个论断（这是本节最重要的部分）

| 本会话先前的断言 | 生产实测 |
|---|---|
| ">140 字永久不可恢复（只剩哈希）" | **错。** 完整正文durable 存在 `/root/.hermes/sessions/*.json`——**468 个文件 / 136MB**，单条消息内容最长 **975,665 字**；抽样会话 68 条消息中 31 条超 140 字 |
| "cron lane 里 LLM 抽取结构上不可能（无可抽取对象）" | **错。** 正文在磁盘上，off-hot-path 完全读得到 |

**教训**：第一个论断是从"本仓库没有反查映射"推出"系统层不可恢复"——**跨系统边界的否定结论不能只用本仓库证据**。
第二个论断是把"热路径禁 LLM（INV-5）"这条约束**惯性延伸**到了 off-hot-path，
而它成立的前提（抽取必须发生在 `sync_turn`）在第一个论断被推翻时就死了。

### 生产规模（实测硬数字，供 3.200 复核对账）

- 事件：**3815** 条，其中 `conversation_turn` **1982** 条、`conversation_turn_mirrored` **539** 条。
- 截断率：**助手侧 67.3%（1333/1982）**、**用户侧 19.0%（377/1982）**（以 `_clip` 的 `...` 尾标判定）。
- `session_mirror`：**637 次 apply 运行、累计 `finding_count` = 0**；
  `auto_apply_max_sessions_per_run: 1`，最近一次 `candidate_session_count: 1575` / `selected_session_count: 1`。
- 镜像事件实际内容形如
  `Session … mirrored; last_user=nihao; last_assistant=你好呀 👋 …`，**最长 259 字**
  ——即 136MB 会话数据每个会话只产出约 160 字的"最后一条消息预览"。
- **选择仍是纯队头**：`session_mirror.py` 的 `selected_sessions = platform_filtered[:limit]`
  （代码注释自陈 "Selection is otherwise pure head-of-queue"）。批次 BY 只修了"被拒会话饿死后队"
  那一半，**一般性队头偏置未修** → 1575 积压按 1/run 永远排不空。

### 本轮做了什么（三项并行，文件互斥，各自独立 worktree）

1. **③ 候选相关性下限**（`prefetch.py`）。**没有删那个关键词门**——已核实它是**刻意的权威分层**
   （测试用「这些结晶候选和长期记忆有什么关系？」并断言输出带
   `candidate only / not approved crystallized memory` 标签）。改为：magic-word 路径**行为逐字不变**，
   新增相关性路径 `_extract_query_tokens` + `_record_body_score >= 2`。
   阈值取 2 有实测依据：`_tokenize_for_floor_match` 会把 `"what's"` 切出单字符 token `"s"`
   从而几乎匹配任何正文；`_extract_query_tokens` 的 CJK 侧发无过滤重叠 bigram，阈值取 1 时
   「我们什么时候开会？」会靠语法 bigram「什么」匹上无关候选。
2. **F `recall_golden` 接线**（`recall_golden.py` / `cli.py` + seed fixture）。
   裁决由"倾向删除"反转为保留——它是①唯一的度量仪器。**同时查出 authority 维度是死代码**，
   见方案 §3.3；hit/miss 那一半经反事实实测为真。
3. **`continuity_freshness` monitor 可见性 + 并发单测**（`memory_os_3_200_monitor.py` / `tests/scripts/`）。
   **刻意不引入任何新 WARN 码**（全走 `pass`/`info`），因此
   `CLEAN_HOST_WARN_CLASSIFICATIONS` 无需注册——避开了待办 1 那个坑
   （未注册 WARN 码在 clean host 会落 `clean_host_warn_unclassified` 即 **FAIL**）。
   账本缺失被显式判为 `continuity_freshness_ledger_absent_healthy`（**缺失是正常健康态**，
   因为状态迁移去重意味着没有 stale 就不写）。

### 整合评审纠正的一处 agent 报告错误

第 1 项的 agent 报告称候选段"可能挤掉 `Recent Event Summaries`(80) / `Indexed Recall`(90)"——**方向说反了**。
`_budget_keep_priority` docstring 明写 "Higher value means survive budget pressure longer"，
而 `_next_budget_drop_index` 升序排序后丢 `candidates[0]`，**即数字小的先被淘汰**。
`Crystallized Review Candidates` = 50 会在 60/65/80/90 **之前**被丢，
所以**未批准候选挤不掉已批准/已索引内容**——方向是安全的那一边。
**记在这里以免后来者去"修"一个不存在的问题。**

### 顺带查出的一条真缺陷（未修，登记）

`cli.py::_check_vector_available()` **急切 import `sentence_transformers`/`torch`**，
导致单次 `status`/`doctor` 调用耗时 **17–29 秒**。
`shell_alias_no_env()` 并发跑 22 条 CLI 探针 → 这**很可能就是待办 3 那个生产 flake 的成因**
（BY.3 记录过一次 `shell_alias_no_env_failed` 重跑不复现）。
本轮未修（超出该 agent 白名单），登记为待办。

### 并发测试的诚实声明

`shell_alias_no_env` **不是模块属性**——它在 `_remote_probe_script()` 的嵌入式字符串里
（第 5368–8471 行是一整个 `r'''` 串，经 subprocess 执行），不可 import；本沙箱也没有 `hermes`。
因此测的是两件可达的事：22 条探针在 `hermes` 确定缺失时并发命中 `except OSError`
且无跨 future 串号；以及 17 条真实只读 CLI 探针在 workers=1 与 workers=4 下结果一致。
**未发现竞态**（futures 模式无线程间共享可变状态）。
`status`/`doctor` 因上述 17–29 秒延迟被排除在并发命令集外——如实声明，这不是全覆盖。

### ①的设计（已定案，未实现）

**①是一条按 `fact_judge` 模板建的新 cron lane，不是新 LLM 集成，也不扩 `session_mirror` 的 charter。**

复用既有机制（Owner 明确要求"别重复造车"，已查证）：
- `low_clue_recall._call_hermes_runtime_model(prompt, config)` + `_extract_json_object`，
  `provider="hermes_default"` → 经 `hermes_cli.config.load_config` +
  `resolve_runtime_provider` **直接用 Hermes 自己配置的模型**
  （支持 `chat_completions` / `codex_responses` / `anthropic_messages`）。
  **已有两个先例**：`llm_edge_proposer.py`、`plugins/modules/governance/fact_judge.py`
  ——跨模块导入这两个私有函数是既定模式，照做即可，**且刻意不改 `low_clue_recall.py`**
  （那还顺便避开与批次 E 的文件冲突）。
- 失败处理**照抄 `fact_judge`**：重试 + 具名 failure_reason
  （`llm_exception` / `llm_empty_content` / `llm_parse_failed` / `llm_missing_key`）
  + **回落确定性启发式**。**绝不继承** `_call_hermes_runtime_model` 裸返回 `""` 的行为——
  否则会造出第二个"637 次运行 0 findings"的静默 lane。
  （这也作废了"确定性 vs LLM"的二选一：房子里的做法是 LLM 主路 + 确定性兜底。）
- 限额走 knob（`*_max_tokens` / `*_max_per_tick` / `*_timeout_ms`），注册进 `OVERRIDABLE_KNOBS`。
- cron 接入：2 行 shim `from memory_os_execution_gate_runner import main`，
  注册进 `cron_registry.py` 的 lane 表并**挂进既有 group**（按 CLAUDE.md：加 lane 不是加 cron job）。
- **写入可走 `append_governed_jsonl`**——它跑在 ExecutionGate envelope 下，
  这点比批次 C 干净（C 在 prefetch 热路径无 envelope，只能走 allowlist 登记）。

**必须避开的两个已知坑**：
1. **不得照搬纯队头选择**，否则 1575 积压永远排不空——新 lane 最容易继承的 bug。
2. `fact_judge` 默认 `max_tokens=1024` / `timeout_ms=15000` 对一条 97 万字消息远远不够
   → 必须分块/选段 + per-tick 上限，**不能"把会话喂进去"**。

**与③配套**：①产候选、③让候选能被召回；单做任一件效果都打折。

### 测试与门

3071 → **3089 passed / 13 skipped / 0 failed**（+18）。
分段实测：两份整合时 3083（recall_golden +8、候选下限 +4），并入 monitor 那份后 3089（+6）。
import cycle（`cycles: []`）/ write surface（`unclassified_count=0`, surface_count 154）/
static hygiene（含 compileall）/ public checkout probe `--strict` /
`git diff --check origin/main...HEAD`（按区间）—— 全过。

### 未验证项（如实声明）

- **仅 `local_pass`。三项均未部署 3.200**——按 Owner 裁定，部署在全部任务完成后统一执行。
- seed golden set 是示例性的，未绑定真实捕获数据；在真实库上非标记项的命中结果未验证。
- 相关性下限对**生产规模**数据的行为未验证（本地测试都是近空库 + 2200 字宽预算）。
- ①未实现。

### CA.1 — 按本节文档对 3.200 的完整只读核对与复盘（2026-08-04）

**全程只读**：无部署、无重启、无写入。C 仍未部署（按 Owner 裁定全部完成后统一部署）。

#### 与文档一致（4 项，逐条实测）

| 断言 | 实况 |
|---|---|
| `deployed_head` = `01356df` | manifest `01356df3a52a…`、`active_runtime_path=/opt/Hermes-Memory-OS`；`/opt` HEAD 同值且工作树干净——**manifest 与 `/opt` 本次无漂移** |
| C 未部署 | 三角互证：`continuity_freshness.jsonl` 不存在、live `prefetch.py` 中 `_record_continuity_freshness` 出现 0 次、`/opt` 停在 C 之前 |
| 8 job / tick 错开 / legacy 暂停不删 | **26 = 7 enabled + 19 paused**；`2,17,32,47`、`7,37`、`12`、`5 0` 逐字一致；第 8 个 `expression-feedback-request` 为 Owner 刻意停用 |
| lane 停用有审计记录 | `memory-os.cron_lane_disabled.v1`，`expression_feedback_request` 的 actor=owner / 2026-07-28 / reason 已填 |

#### Full Monitor 基线已变化：97/6/1 → **102 PASS / 5 WARN / 1 FAIL**

FAIL 仍只有 `v2_exposure_schema_era_unhealthy`。
**口径声明**：本次 monitor **由本整合分支发起，非主机已部署的 `01356df`**，
差别至少含本轮新增的 `continuity_freshness_ledger_absent_healthy`（PASS）
——与 BY.1 记录的同类口径问题一致，比较时须扣除。
runtime 181.197s / 目标 180s → `full_monitor_runtime_over_target` 仍 WARN。

#### 文档漂移 1（好的方向）：LLM 判断器已恢复

BY.1 记的「`low_clue_llm_judge_unavailable` WARN，OpenAI 额度耗尽」**已过期**：
本次 `low_clue_llm_judge_available` 在 **PASS** 列。
独立佐证：`system-modules/fact_judge/verdicts.jsonl` 643 行，最近 80 次
`failure_reason` 分布 **`none: 58` / `llm_empty_content: 22`** —— 通路可用（72.5%），
但**约 27.5% 返回空**。
**这实测验证了待办 12（①）的设计决定**：若①继承 `_call_hermes_runtime_model`
裸返回 `""`，约四分之一的抽取会静默产出空。照抄 `fact_judge` 的重试 + 具名
failure_reason + 确定性兜底**不是保守，是必需**。

#### 文档漂移 2：那个唯一 FAIL —— 我最初的诊断也是错的（已于同日修正，见 CA.2）

BY.1（本清单 L2070-2072）称该 FAIL「数据成熟度驱动，**实测正在推进**：
rollup lag 74.4h→26.5h、schema-era 分类率 0.6506→0.7018」。
我当时反驳为「`exposure_rollup` 停产，lag 只会重涨，'正在推进'不成立」。
（附带纠正：此处原文把该说法也记到"路线图 P1-4"名下，**属误引**——
路线图只在 L218/L291 要求"继续观察 lag/attribution/conservation"，并未声称正在推进；
且它 L107 早已正确写明唯一 FAIL 是 `v2_exposure_schema_era_unhealthy`。）

**双方都错，且错在同一个轴上**：monitor 里**根本不存在 lag 门控**。
`grep -n "exposure_rollup_lag" scripts/memory_os_3_200_monitor.py` 零命中；
`exposure_rollup_lag_hours` 只由 `exposure_monitor_stats()` 计算并上报，
**从未进入 PASS/WARN/FAIL 判定**。拿 lag 论证 FAIL 是否推进，无论方向都无意义。

真正的 FAIL 与根因见 CA.2。此处仅保留方法教训：
**在用某个指标论证结论之前，先 grep 它是否真的被门控。**
一个"被计算并上报"的指标不等于一个"会告警"的指标。

BY.1 那句话里**真正需要推翻的不是"正在推进"，而是"数据成熟度驱动"**：
CA.2 实测该 FAIL 的唯一驱动因素是 `schema_era_attribution_gap_count = 69`，
而它是一个**代码缺陷**（`working` 段落从不填 `source_ids`），不是成熟度不足。
**再等多久都不会自己好。** 一个佐证：BY.1 记的分类率是 `0.6506→0.7018`，
本次实测仍是 **0.7018**，一位不差——那条曲线早已停住。

#### 本次核对最重要的结论：一个反复出现的缺陷模式

**系统观测"跑过了"，不观测"产出了"。** 三个独立实例同型：

| 实例 | 被观测到 | 未被观测到 |
|---|---|---|
| `exposure_rollup` | envelope 完整关闭 | **两条"不产出"退出路径的证据完全相同**：`if not new_records` 的良性跳过（L141）与 `source_cursor_not_found` 的永久错误（L128-138），都在开 envelope 前 return，都不写 jsonl、也不写 snapshot |
| `session_mirror` | 637 次 apply 运行 | 累计 `finding_count` = 0（且积压 1574→1575 在涨） |
| `_call_hermes_runtime_model` | 调用返回 | 返回 `""` 与成功不可区分（实测 27.5% `llm_empty_content`） |

monitor 的 helper completion 只判 envelope，**`completion ≠ output`**，因此
三者皆无告警。`exposure_rollup` 这一行尤其说明问题：它其实**已经**在 report 里
写了 `skipped=True`，但那个 report 只返回给调用方、不落盘，于是从产物侧
**一个永久坏掉的 lane 与一个正常空转的 lane 长得一模一样**——本轮要区分它们，
不得不读源码 + 手工把游标拿去和 `memory_sources.jsonl` 比对（见 CA.2）。

批次 C 的账本设计（状态迁移去重 + `unknown_grade_count` 计数器）刚好是这个模式的
反面——**那不是巧合，应当推广为通例**。已登记为待办 14，并已写入 CLAUDE.md
新增小节 **“Completion Is Not Output”**（含"不产出必须落盘写明原因码"的硬要求）。

#### 本次核对中我自己的两次误报（方法教训，须记）

1. **「26 个 cron job 而文档说 8」** —— 错。截断了输出 + 未把 19 个 paused legacy 计入。
   8 注册 − 1 Owner 停用 = 7 enabled，文档准确。
2. **「`working_cleanup`/`hindsight_advisory_digest` 4 天没跑 = monitor 漏报」** —— 错。
   两者 `due_interval_minutes=10080`（**7 天**），4 天 < 7 天，**不该判 stale**，
   `stale=0` 是正确的。而且这恰好证明 CLAUDE.md 警告的那个陷阱
   （用 group cron 表达式推导窗口会把周 lane 误报 stale）**生产里正确避开了**。

**两次都是"先报警、后核实"。** 与本会话早先那三次（方案 §4.1 的错误说法、
臆造批次 G、">140 不可恢复"）是同一个毛病：**结论跑在证据前面**。
在这份清单里，报警和核实之间必须隔一次 grep。

---

### CA.2 — 待办 15 结案 + 那个唯一 FAIL 的真实根因（2026-08-04，只读实测）

CA.1 把待办 15 留成"不许猜"的开放项：`exposure_rollup` 每天开 envelope 却不追加账本行，
**"无新合格数据"与"静默失败"对处置的要求完全相反**。本节把它查到底，
结论是**两个假设都不成立，答案是第三种**，并顺带定位到那个唯一 FAIL 的真实根因。

#### 一、读源码：`exposure_rollup` 有两条"不产出"退出路径

`plugins/memory/memory_os/exposure_rollup.py::run_exposure_rollup_cycle`：

| 位置 | 条件 | 行为 | 性质 |
|---|---|---|---|
| L141-143 | `if not new_records` | `skipped=True` 直接 return | **良性**，按设计不写 |
| L128-138 | `_latest_source_cursor` 返回 `source_cursor_not_found` | `status="error"` 直接 return | **永久失败** |

两条**都在开 envelope 之前 return**，因此 jsonl 与 snapshot **都不写**
（snapshot 写在 L309-326，且是 `except Exception: pass` 的 best-effort）。
这解释了实测现象：两个文件 mtime 完全相同、都停在 `2026-08-02 00:05:18 +0800`。
**证据侧无法区分**——这就是待办 14 那个模式的教科书实例。

`source_cursor_not_found` 的危险性值得单记：`_latest_source_cursor` 是 fail-closed 的，
一旦压缩把游标记录从 `memory_sources.jsonl` 移除，之后**每一次运行都会走同一条错误路径、
永远不产出**，而 lag 只会单调增长。

#### 二、判别式实测：游标仍在队首 ⇒ 良性空转

只读探针（远端 `python3`，不落任何文件）：

```
memory_sources.jsonl   rows: 988   mtime 2026-08-01T15:51:08 (+0800)
  最后一条 created_at : 2026-08-01T07:51:08.673109Z
  最后一条 record_id  : msrc_20260801T075108673109Z_4d466577
exposure_rollup.jsonl  rows: 16
  最后一行 window_end            : 2026-08-01T16:05:18.054652Z
  最后一行 source_offset_end     : 988
  最后一行 source_cursor_record_id: msrc_20260801T075108673109Z_4d466577
  ⇒ 游标命中 index 987 / 988 ⇒ new_records = 0
```

**结论：走 L141 良性分支，非缺陷。** `source_offset_end = 988` 等于源文件总行数，
游标就是最后一条记录，上游自 `08-01T07:51Z` 起零增长 —— lane 没有输入可处理。
**待办 15 结案。**

#### 三、纠正我自己在 CA.1 里的错误：monitor 根本没有 lag 门控

CA.1（以及路线图 P1-4）都在用 `exposure_rollup_lag_hours` 论证那个 FAIL 是否推进。
`grep -n "exposure_rollup_lag" scripts/memory_os_3_200_monitor.py` → **零命中**。
该指标只由 `exposure_monitor_stats()` 计算并上报，**从不进入 PASS/WARN/FAIL**。
**用一个不被门控的指标论证告警状态，方向对错都无意义。**
教训并入待办 14：**"被计算并上报"≠"会告警"，引用指标前先 grep 它是否真的被判定。**

#### 四、那么那个唯一 FAIL 到底是什么：`working` 段落缺归因

远端实测 `exposure_monitor_stats()`：

```
schema_era_health                    = FAIL
schema_era_attribution_gap_count     = 69      ← 唯一驱动因素
schema_era_conservation_failure_count= 0
telemetry_degraded_count             = 0
conservation_total_passes            = True
schema_era_natural_record_count      = 170
schema_era_classified_ratio          = 0.7018
exposure_rollup_lag_hours            = 68.0    （不被门控，仅供参考）
```

`schema_era_health` 的判定是 `FAIL if schema_gap or conservation_failures or
telemetry_degraded_count`（L473-475），后两项皆 0 ⇒ **FAIL 完全由 69 个归因缺口驱动**。

再按 `source_class` 分组（只读探针，复用 `_memory_source_has_attribution_gap` 同一判据）：

| source_class | bucket | 缺口段落数 | 有归因段落数 |
|---|---|---|---|
| `working` | dropped | **41** | 0 |
| `working` | selected | **28** | 0 |
| `crystallized` | dropped | 0 | 83 |
| `crystallized` | selected | 0 | 50 |

**69 个缺口 100% 集中在 `working`，且 `working` 从无一次填对；`crystallized` 133 段零缺口。**
即 prefetch 披露工作记忆时报了 `chars`/`count` > 0，却从不填 `source_ids`。

同一缺陷的另一面：`_extract_record_ids_from_section`（L80-86）只接受
`crystallized:` / `candidate:` 前缀，所以 `working` 记录**即使填了 ID 也不会被分类** ——
这正是 `classified_ratio = 0.7018`（≈30% 处理了但分类不到）的来源。两个数字同源。

**未修，登记为待办 16。** 修前必须先定的设计问题：工作记忆记录的规范 ID 前缀是什么
（新增 `working:`？），以及归因补齐后 `classified_ratio`/`conservation` 语义是否需同步调整。
这一条与"关键事实漏失"同源——都在 prefetch 披露侧，是批次 C 的邻接面。

#### 五、继续追下去：那个门本身只覆盖 2/13 个类，静默跳过 1093 个缺口

顾问指出"prefetch 有 bug"只是三种读法之一，还须排除"`working` 本无可引用身份"
与"该段落是聚合视图"。按 CLAUDE.md「Beyond the Pointed-Out Problem」把调用链读完，
结论是第一种成立，**但同时发现了一个更大的问题**。

**可引用性已确证**（否决"本无身份"读法）：`_working_lines` 逐条遍历单个 item，
手上同时握着 `path.stem` 与 item；item 有 `id`（`working.py:350`）；
规范引用格式 `working:<stem>:<id>` 已在 `deep_reflection.py:639` 生产使用，
`working:` 前缀在 `v3_body_packet.py:21` 的允许前缀表内，`low_clue_recall.py:478` 也在产出。
`_working_lines` 只是签名仍为 `list[str]`，而 `_crystallized_lines` 早已扩成三元组带 ID。

**更大的问题**：`section_source_ids` 在 `_build_prefetch_sections` 内**只有一个赋值点**
（`prefetch.py:614`，crystallized 专属）。于是逐类实测（3.200 只读，复用生产同一判据）：

| source_class | 有 ID | 无 ID | 是否被 `attributable_classes` 统计 |
|---|---:|---:|---|
| `crystallized` | **133** | 0 | ✅ |
| `working` | 0 | **69** | ✅（**唯一驱动 FAIL 的那 69 个**） |
| `last_session` | 0 | 162 | ❌ 静默跳过 |
| `foreground` | 0 | 145 | ❌ |
| `identity` | 0 | 133 | ❌ |
| `state_overlay` | 0 | 133 | ❌ |
| `bridge` | 0 | 133 | ❌ |
| `substrate_recall` | 0 | 133 | ❌ |
| `event` | 0 | 115 | ❌ |
| `other` | 0 | 66 | ❌ |
| `indexed` | 0 | 46 | ❌ |
| `diagnostic` | 0 | 22 | ❌ |
| `candidate` | 0 | 5 | ❌ |

**被门统计的缺口 69，被静默跳过的 1093。** 原因是 `attributable_classes`
（`exposure_rollup.py:509` 硬编码）里 `entity_graph` / `indexed_recall` / `vector` /
`hindsight` **四个名字全项目无任何生产者**，而生产者实际发出的是
`indexed` / `graph_layer` / `substrate_recall` / `event` / `candidate` ——
**名字对不上，门就静默失效**。该集合无任何测试引用，测试夹具还把
`source_class` 写死成 `"crystallized"`，所以这 12 个类从未被测试触达。

**由此得到本节最重要的一句**：只补 `working` 的 ID 会让
`schema_era_attribution_gap_count` 归零、`schema_era_health` 转 PASS、**monitor 变绿**，
而 1093 个真实缺口继续不可见——**靠缩小度量范围换来的绿色**，正是路线图 L43
明令禁止的。故 16b 必须先于或同时于 16a；修 16b 会让 FAIL 数字先变大，那是正确方向。

#### 六、方法记账

本节做对的地方是**先读源码把"不产出"的所有退出路径穷举出来，再设计判别式实测**，
而不是从现象直接推断。CA.1 的错误恰恰相反：拿一个没验证过是否被门控的指标去论证结论。
**顺序是——穷举分支 → 设计判别式 → 取证 → 才下结论。**

**但本节自己又犯了一次同样的错，须记。** §4 定位到"69 个缺口全在 `working`"之后，
我直接把根因写成"prefetch 有 bug"并把修法写成"新增 `working:` 前缀"——
**跳过了"这份测量有几种读法"这一步**。至少还有两种：`working` 本无可引用身份
（则该类根本不该在 `attributable_classes` 里）、或该段落是聚合视图（无 1:1 记录可列）。
`working` 是 **0/69 从未填过**，而"实现了但有 bug"通常表现为"有时填有时不填"——
这个 0 本身就是要求换读法的信号，我当时没读出来。
经顾问点出后按 CLAUDE.md「Beyond the Pointed-Out Problem」把调用链读完，
才发现真正的量级问题（1093 个静默跳过）与那个"修了反而变绿"的陷阱。
**教训：定位到根因不是终点；须再问一次"同一组测量还能怎么解释"，
并且必须验证修法在物理上是否可能（`working` 到底有没有 ID）。**
本会话这已是第六次"结论跑在证据前面"。

（3.200 全程只读：无部署、无重启、无写入。批次 C 仍未部署，按 Owner 要求全部任务完成后统一部署。）

**遗留清理项**：3.200 的 `/tmp` 下有 4 个历史遗留克隆目录
（`hmos-fresh-clone-QQ82NL`、`Hermes-Memory-OS-community-commit-clone`、
`Hermes-Memory-OS-community-clean2`、`Hermes-Memory-OS-community-clean`），
系早前会话的探针残留。本轮只记录未删除（生产主机上的删除动作需 Owner 确认）。

---

### CB — ①会话事实抽取 lane 实现（2026-08-04，未部署）

关闭待办 12。`sync_turn` 只把 `_turn_summary` 的每侧 140 字符摘要写进事件队列，
`inner_drive.py:294` 又从那个已截断的摘要构造候选体，因此**任何写在消息第 140 字符
之后的持久事实永远进不了记忆**——这正是 Owner 报告的"关键事实漏失"的 A 类成因。
完整消息体在主机上以原始会话转录形式留存，故新增一条**离线** cron lane 去回收它们。

#### 落地文件

新增 `plugins/modules/cognition/session_fact_extraction.py`（核心）、
`scripts/memory_os_session_fact_extraction_lane.py`（lane helper，CLI/env 契约照
`memory_os_fact_judge_lane.py`）、`scripts/memory_os_cron_session_fact_extraction_gate.py`
（2 行 gate shim）、两个测试文件。
改 `cron_registry.py`（lane def + `tick_evidence` 成员，lane 数 21→22，
active-closure 覆盖 19→20 条，**不新增 cron job**）、`knob_overrides.py`（6 个 knob）、
`test_memory_os_cron_registry.py`（派生 job 数断言仍为 8，lane 数 19→20）。
`write_surface_check.py` **无需改动**：本 lane 的写入全部走既有
`append_governed_jsonl` / `append_candidate_queue` 包装，`surface_count` 保持 154、
`unclassified_count=0`（已实跑确认，非推断）。

#### 关键设计决定

- **只处理 >140 字符的消息**（`MESSAGE_ELIGIBILITY_THRESHOLD_CHARS`，注释绑定到
  `_turn_summary` 的 clip 长度）。≤140 的消息本就完整存活，重抽是纯重复劳动。
  这条把语料裁掉一大半，是"有界"的主要来源。
- **先脱敏再判长度**，与 `_turn_summary` 的 redact-then-clip 同序；脱敏后的文本才
  送 LLM。这一点比 `inner_drive` 更需要：后者的候选来自**已脱敏的 140 字摘要**，
  而本 lane 读的是**原始转录体**。
- **持久指纹账本**（`system-modules/session_fact_extraction/processed_sessions.jsonl`，
  指纹 = 文件名+size+mtime）+ **最新未处理优先**。**刻意不照搬**
  `session_mirror` 的纯队头选择（`platform_filtered[:limit]`，其代码注释自承偏置）,
  否则积压永远排不空（待办 13）。
- **三重有界**：每 tick 最多 2 个会话、每会话最多 20 条合格消息、最多 5 条事实；
  每条消息送模型前截到 4000 字符（生产实测单条消息可达 97 万字符，而回复预算
  `max_tokens=1024`——不设输入上界必然失败）。合格性筛选**放在每会话消息上限之前**，
  避免一串短"好的/谢谢"把实质消息挤出窗口。
- **只产出未批准候选**，走既有 `append_candidate_queue`；从不结晶、不批准、不外发；
  对会话文件**只读**。

#### LLM 复用（不重复造车）

照 `fact_judge` 模板：同样从 `low_clue_recall` 私有导入
`_call_hermes_runtime_model` / `_extract_json_object`，provider `hermes_default`，
同样的重试循环与**分类失败码**（`llm_exception` / `llm_empty_content` /
`llm_parse_failed` / `llm_missing_key`），以及**fail-closed** 的确定性回退
（仅在命中 `_DURABLE_MARKERS` 时产出，绝不无条件产出）。
`_call_hermes_runtime_model` 任何失败都返回 `""` 且与成功不可区分，生产实测
`llm_empty_content` 占比 27.5%——**绝不继承那个裸 `""`**。

#### 产出可观测性：本 lane 是待办 14 的正面样板

每次运行都落盘 `runs.jsonl`，含
`sessions_scanned / sessions_eligible / sessions_processed /
sessions_skipped_already_processed / messages_considered /
messages_eligible_over_threshold / facts_extracted / candidates_written /
llm_calls / llm_failures_by_reason / fallback_used_count`，
外加封闭原因码集 `SKIPPED_REASON_CODES`
（`sessions_dir_absent` / `no_session_files_found` / `no_unprocessed_sessions`）。
**三条 skip 路径全部在 return 之前写 run report**，因此
"无合格输入" / "有输入但模型失败" / "有输入且产出了" 三者**从产物即可区分，
不必重跑、不必读源码**——正是 CA.2 §5 指出 `exposure_rollup` 缺的那件事。

#### 整合评审中我改掉的两个缺陷（子 agent 未发现，均补了反事实测试）

1. **`candidate_id` 含 mtime → 活跃会话每次追加都产生重复候选。**
   原实现 `material = f"{fingerprint}|{message_index}|{fact_text}"`，而指纹含 mtime。
   会话被追加 → 指纹变 → 会话重新入选（这是**设计意图**）→ 未变的第 0 条消息被重抽 →
   因指纹已变而**得到新的 candidate_id** → 绕开 `append_candidate_queue` 的
   candidate_id 去重（`crystallized.py:1116`）→ 候选队列被同一事实反复灌入，
   且每个副本都是 resolver 可自动批准的。
   改为 `f"{session_id}|{message_index}|{fact_text}"`（三者跨追加均稳定）。
   反事实实测：还原旧实现后队列 3 行而非 2 行（`assert 3 == 2`），已确认会失败。
2. **`sessions_skipped_already_processed` 重复扣减。**
   原式 `sessions_scanned - sessions_eligible - _unreadable_count(...)`，而
   `sessions_scanned = len(pairs)`，`_discover_session_files` **已经**把 stat 失败的
   文件排除在 `pairs` 之外——再扣一次即重复扣减，且 `max(...,0)` 把负数夹掉、
   掩盖了症状。改为 `sessions_scanned - sessions_eligible`，并删掉随之失去调用方的
   `_unreadable_count`。反事实实测：还原旧式后报 0 而非 1（`assert 0 == 1`），已确认会失败。

#### 全量测试套件另外抓出 3 个回归（子 agent 只跑了定向测试，全部漏掉）

子 agent 的定向测试全绿（38/38），但**全量套件 3 failed**。这正是
「Definition of Done — 绝不在只跑自己新增/改动的测试后就推送」那条规则的实证。
三者全部落在**子 agent 白名单之外的文件**，它无权修（已在其报告中如实上报了相邻风险，
但没预见到这三处会 FAIL）：

1. `test_error_record_emitting_components_constant_matches_source` ——
   新组件名 `session_fact_extraction` 发了 `error_record` 却未登记进
   `memory_os_3_200_monitor.py::ERROR_RECORD_EMITTING_COMPONENTS`。
   该测试**从源码正则反推真实发射者清单**再比对常量，所以"新增发射者却不分类"
   会响亮失败而不是静默扩大盲区——设计得很好，正好抓到我们。已按字典序补入。
   注：该常量同时喂给 `_error_record_component_coverage`，而
   `unaggregated_component_count` 本就 > 0（headline 聚合只覆盖 runtime /
   memory_projection / session_mirror / prefetch 四个），是一个诚实的盲区计量而非门；
   已确认无测试钉住其具体数值（只断言 `> 0` 与自一致），故补入是安全且更诚实的。
2. `test_installer_can_run_owner_cron_onboarding_with_auto_channel`（`blocked` ≠ `applied`）
3. `test_installer_can_run_full_owner_cron_profile_when_requested`（`0` ≠ `9` 个 job）

2、3 同一个根因：`memory_os_owner_cron_onboarding.py:222-225` 要求
**group 的每一个成员 helper 都必须存在于 `<hermes_home>/scripts/`**
（其代码注释写明理由：「a group tick whose helper is absent would fail that lane on
every tick with no install-time signal」）。而 `install_memory_os_plugin.py`
的 `_write_operational_helper_scripts` 是**逐个列举**源文件的，新 lane 的两个脚本
不在其中 ⇒ 安装后 helper 缺失 ⇒ onboarding 直接 blocked ⇒ 一个 job 都不建。
已补 `SOURCE_SESSION_FACT_EXTRACTION_LANE` / `_GATE` 两个常量与 copy map 两项。
（`plugins/` 树是整体拷贝的，故模块文件本身无需登记；已核实
`_validate_system_module_source` 只是源树抽检清单，不是拷贝清单。）

**这三处的反事实就是它们本身**：三个测试在修复前实测 FAIL、修复后 PASS，
无需再另写——既有守卫已经承担了反事实职责。

**由此补一条"新增 lane 的登记清单"**（Section W 规则 5：同类问题全项目排查）。
加一条 lane 至少要动：① `cron_registry.py` lane def；② 该 group 的 `member_keys`；
③ `knob_overrides.py`（若有 knob）；④ `install_memory_os_plugin.py` 的
`SOURCE_*` 常量 + `_write_operational_helper_scripts` copy map；
⑤ `memory_os_3_200_monitor.py::ERROR_RECORD_EMITTING_COMPONENTS`（若发 error_record）；
⑥ 部署时重新生成 registry 快照。
**不需要**动 `LEGACY_PER_LANE_CRON_JOBS`——已核实该表只登记**合并前**就存在于
已 onboarding 主机上的旧单 lane job（用于 pause 而非删除，是回滚路径）；
新 lane 直接诞生在 `tick_evidence` 内，从未有过独立 job，加进去是惰性条目
且会误导 onboarding 去 pause 一个从不存在的 job。子 agent 这个判断是对的（已复核）。
**也不需要**动 `write_surface_check.py`（已实跑确认 `surface_count` 仍 154、
`unclassified_count=0`）。

另补一条**脱敏防漂移测试**：断言本 lane 的 `_SECRET_PATTERNS` 与
`memory_os.__init__._TASK_SECRET_PATTERNS` 的正则字符串逐条相等。
两者当前完全一致（同 4 条、同序）；该测试的作用是——若日后规范集新增一条模式，
这里**失败**而不是静默漏掉那一类秘密（本 lane 读原始转录，脱敏不得弱于捕获路径）。

#### 生产形状已实测核对（不是假设）

子 agent 自陈"会话文件形状未对生产核实"。已核实：
`session_mirror.py:306` 的 `sessions_root` 就是 `hermes_home / "sessions"`、
`:613` glob 的就是 `session_*.json`，与本 lane 一致；3.200 上该 glob 命中 **141 个**
文件，顶层键含 `messages`/`platform`/`session_id`，`messages[0]` 含 `content`/`role`
——**与实现假设完全一致**。（同目录另有 42 个 `2026*.jsonl` 新格式与若干
`request_dump_*.json` 错误转储，两者都不匹配该 glob，与 `session_mirror` 自身口径相同。）

**排空速率**（据此可算，非估计）：`tick_evidence` cron 为每小时，
lane `due_interval_minutes=360` ⇒ 每天 4 次 × 每次 2 个会话 = **8 个/天**，
141 个文件约需 **18 天**排空。最新优先意味着召回价值立刻开始体现；
若要更快，`session_fact_extraction_max_sessions_per_tick` 可直接调大（上界 20）。

#### 部署要求（**遗漏则静默失效**，须写进统一部署清单）

`cron_group_runner._load_group` **优先读**
`<hermes_home>/memory-os/system/memory_os_cron_registry.json`，且只要快照里该 group 的
`member_keys` 解析出非空成员就**直接返回、不回退**编译内注册表。
已 onboarding 的主机上，快照里 `tick_evidence` 仍是旧的 5 个成员 ⇒
**新 lane 根本不会被 tick 调用，且没有 `unknown_registry_key`、没有 error record、
没有 WARN**——tick 照常关闭一个干净的 envelope，只是从未执行它。
（`execution_gate_runner._load_spec` 确实会回退到编译内注册表，所以失效点精确地
在 group 成员解析，而非 permit 签发；子 agent 报的"会报 `unknown_registry_key`"
不准确，实际比那更隐蔽。）
⇒ **统一部署时必须重新生成该快照**（归口
`install_memory_os_plugin.py` / `memory_os_owner_cron_onboarding.py`），
并**在部署后核对快照里确有 `session_fact_extraction`**，不得假定注册即生效。
已同步写入 CLAUDE.md cron 小节。

#### 测试与门

- 新增 20 个测试（`test_memory_os_session_fact_extraction.py` 17 +
  `test_memory_os_session_fact_extraction_lane.py` 3，均为子 agent 所写）
  ＋ 整合评审中我补的 3 个（两个反事实 + 脱敏防漂移）= **+23**。
  CB.1 又补 3 个（延后可重试、延后有界、账本保留可老化）⇒ 本节合计 **+26**。
- **3089 → 3115 passed / 13 skipped / 0 failed（最终一跑全绿）。**
  数字对得上：3089 + 26 = 3115。
- 四门全过：`write_surface_check`（`surface_count` 154 不变、`unclassified_count=0`）、
  `import_cycle_check`（`cycle_count=0`）、`static_hygiene`、
  `public_checkout_probe --strict`（`PASS`）；**空白检查按推送区间**
  （`git diff --check origin/main...HEAD`）干净，非逐提交；无 CRLF。
- 中途两次全量跑各有 1 个**环境性**失败，均已隔离证伪、与本批改动无关，如实记下：
  ① `test_completion_append_and_sidecar_are_idempotent_under_concurrency`
  （`PermissionError`，已知 Windows 文件锁 flake，单独重跑即 PASS）；
  ② `test_t2_2_5_gate_fails_closed_when_fts_query_errors`
  （`sqlite3.OperationalError: unable to open database file`）——
  单独重跑 PASS、同一 `--basetemp` 单跑 PASS、整文件 64 个全 PASS；
  是 OS 资源错误而非断言失败，且 graph_layer 的 FTS 门与本批所改的
  `session_fact_extraction`/`metadata_retention` 无任何调用关系。
  **换全新 basetemp 重跑后 3115 全绿，证实成因是该次运行累积的 3863 个临时目录**
  ——不是回归。（教训：不要用"它是 flake"收尾，要换掉可疑变量再跑一次拿到绿。）
- **环境注记**：本机 C: 盘在此期间被占满（98G/99G），触发 ENOSPC 一度使 shell
  不可用（连工具自身的输出文件都创建不了）。非本会话造成（本会话产物 <1MB）。
  处置：清掉 pytest 残留后把测试临时目录改到 D: 盘（`TMPDIR` + `--basetemp`）。
- 证据级别：**仅 `local_pass`**。未部署、未在 3.200 上跑过本 lane。

#### CB.1 — 顾问复审又抓出 3 处（含一个会让整条 lane 失去意义的缺陷）

`f4a3ccf` 提交后请顾问复审，抓出 3 处我逐行评审时漏掉的问题。第一处严重：
**它会让 lane 在自己最可能的失败模式下永久丢失事实——正是 lane 存在的理由。**

**1（严重）：LLM 失败后仍把会话指纹记为已处理 ⇒ 事实永久丢失。**
`newly_processed_fingerprints.append(fingerprint)` 原本在**每会话循环末尾无条件执行**
（在每消息循环之外）。于是模型不可用的那一 tick：每条消息 `llm_empty_content` →
`has_durable_fact=False` → 0 候选 → **会话仍被标记已处理、此后永不重访**
（除非文件本身变化）。而生产实测该失败率是 **27.5%**——不是边缘情况。

同时暴露出与回退策略的耦合：`_heuristic_extract_fact` 用
`_clip(message_text, 500)` 当"事实"，是当时唯一挡在"模型故障"与"全丢"之间的东西。
但**这个耦合是我在派单里指定照抄 `fact_judge` 才带进来的，是我的指令错了**：
`fact_judge` 判的是"已存在内容"的一个**布尔**，marker 启发式是合理的降级答案；
本 lane 必须**生成**一条摘要，而**没有任何启发式能做摘要**。
marker 命中的 500 字符原文切片不是"恢复出的事实"，
它恰恰是本 lane 要消除的那种截断。更糟的是 `_DURABLE_MARKERS` 里含 **`"用"`**
（实测确认），几乎任何长中文消息都含它 ⇒ 该门几乎必然命中，而非罕见命中；
且候选 `bridge_state` 在 `RESOLVER_ELIGIBLE_BRIDGE_STATES` 内 ⇒
这些原文切片可被 resolver 自动提升为**临时结晶**。这是治理问题，不只是噪声。

**改法（两半必须一起改，顾问明确指出"不许只改一半"）**：
- **失败即延后，绝不臆造**：LLM 失败返回
  `reason="llm_unavailable_extraction_deferred"`、不产候选；删除
  `_heuristic_extract_fact` 与 `_DURABLE_MARKERS` 导入。
- **延后有界**：指纹账本增加 `status`（`processed` / `deferred` / `abandoned`）
  与 `attempt`；只有 `processed`/`abandoned` 是**终态**、才抑制重跑。
  `MAX_EXTRACTION_ATTEMPTS=3` 之后记 `abandoned`——**终态但与 `processed` 可区分**，
  使"放弃"在账本里看得见，而不是长得像成功。
  （若无此上限，一条永远解析失败的消息会每 tick 重复占用预算、饿死其他会话。）
- 新增计数器 `sessions_deferred_llm_failure` / `sessions_abandoned_after_max_attempts`
  ——否则"模型故障"与"这批确实没事实"都读作 `facts_extracted=0`。
- 反事实实测（还原为无条件指纹）：
  `assert 0 == 1`（延后未被记录）与 `assert False`（永不放弃）**双双失败**，已确认。

**2：两个新账本重复了待办 9 的老毛病。**
指纹账本原本写 `processed_at`，而 `metadata_retention._record_created_at()`
只认 `created_at`/`ts`/`timestamp` ⇒ 每条都被判"无时间戳" ⇒ **永久 `retained_records`**。
且两个账本**根本没在 `metadata_retention` 注册**（未注册＝对保留计划不可见＝无界增长）。
增长不是理论问题：被追加的会话**按设计**会产生新指纹，故活跃会话每 tick 加一行，
而 `read_processed_session_fingerprints` 每次运行都读整个文件。
已改为 `created_at` 并把两个账本都注册进 `metadata_retention_plan`。
反事实实测（改回 `processed_at`）：`assert None is not None` 失败，已确认；
且该测试**经真实生产者取证**（断言的是 lane 实跑写出的行，不是手写夹具）。

**3：推送前的空白检查必须按推送区间做，而非逐提交。**
我此前每次提交只跑了 `git diff --cached --check`，而 CI 检查的是整个推送区间
（记忆条目 `ci-whitespace-gate-checks-pushed-range` 记的就是这条）。已按区间复核。

**方法记账**：这三处我逐行读完 785 行仍然漏掉。第 1 处漏掉的原因值得记——
我把注意力放在"这段代码做了什么"，而没问"**LLM 失败时这段代码做什么**"。
`fingerprint_outcomes` 的赋值点在循环末尾、语法上毫不显眼，
但它与失败路径的交互决定了整条 lane 有没有意义。
**教训：读一个有外部依赖的循环时，必须专门再走一遍"依赖失效"那条路径。**

#### 下游治理事实（须 Owner 知情，本轮不改）

候选 `bridge_state="inner_drive_candidate"`，是既有受治理路径（与 `inner_drive` 同）。
但该值在 `resolver_gate.py:33` 的 `RESOLVER_ELIGIBLE_BRIDGE_STATES` 内，因此
`candidate_aggregation` 的 resolver 自动批准**可以**把这些候选提升为**临时**
（provisional）结晶记录，条件是通过 `is_reversible`（无身份信号、非敏感、无副作用）。
本 lane 自身从不结晶；但"LLM 从原始转录抽出的事实"经此路径可在无 Owner 逐条批准的
情况下进入临时结晶态。**这是既有设计的既有行为，不是本 lane 新增的**，
但因为本 lane 的来源是原始转录而非已脱敏摘要，性质上比 `inner_drive` 更值得 Owner
明示确认是否接受。

**CB.1 之后此项风险已显著下降**：删除臆造回退后，候选体**只可能**是 LLM 产出的摘要，
不再可能是 marker 命中的 500 字符原文切片。原先那条路径才是真正的问题所在——
`_DURABLE_MARKERS` 含 `"用"`，模型故障期间几乎每条长中文消息都会变成一条
原文切片候选，且同样 resolver 可自动提升。现在模型故障只会**延后**，不产候选。
剩余待 Owner 裁定的只有一个干净问题：**"LLM 从原始转录摘出的事实"
是否可以像 `inner_drive` 候选一样被 resolver 自动提升为临时结晶**，
还是应当为本 lane 引入一个不在 `RESOLVER_ELIGIBLE_BRIDGE_STATES` 内的新 `bridge_state`
以强制逐条 Owner 批准。**本轮不改，等 Owner 裁定。**

---

### CC — 修复 16a/16b：归因契约（2026-08-04，未部署）

关闭待办 16。Owner 裁定：**resolver 保持自动提升，尽量减少人工介入** ⇒
①的候选 `bridge_state` **不改**，`RESOLVER_ELIGIBLE_BRIDGE_STATES` 不新增成员。
该裁定已记录，本节不再讨论。

#### 两个缺陷各自的修法

**16b：门的词表与生产者词表不匹配 ⇒ 静默失效。**
`exposure_rollup._memory_source_has_attribution_gap` 原本硬编码
`{crystallized, working, entity_graph, indexed_recall, vector, hindsight}`，
其中**后四个全项目无任何生产者**；而生产者
（`prefetch._section_source_class`）实发的是 `indexed` / `graph_layer` /
`event` / `candidate` / `substrate_recall` 等。名字对不上，那几类就从不被检查。

改法不是"补几个名字"，而是**让不匹配变成可测**：
- 生产者词表提升为模块级常量 `SECTION_SOURCE_CLASS_BY_TITLE` +
  `SECTION_SOURCE_CLASS_FALLBACK`（原先是函数内局部 dict，**任何测试都看不见它**，
  这正是漂移能存在的原因）。
- 门侧拆成两个显式集合：`ATTRIBUTABLE_SOURCE_CLASSES`（6 个）与
  `NON_ATTRIBUTABLE_SOURCE_CLASSES`（11 个，**逐类写明豁免理由**）。
- 守卫测试 `test_attributable_source_classes_cover_the_producer_vocabulary`
  断言两件事：生产者能发出的每个类都被显式分类（漏分类＝静默不检查），
  且契约里**没有无生产者的死名字**（死名字＝该类检查静默为空）。
  两个方向都断言，才能同时挡住原缺陷和未来新增段落。

**豁免的 11 类及理由**（派生/聚合视图，无 1:1 规范记录可引，
要求 `source_ids` 是**不可满足**而非"未满足"）：
`foreground`（任务锚点，派生态）、`recall_guard`（固定守卫串，自带合成标记）、
`identity`（整文件片段）、`state_overlay`（跨记录聚合）、`bridge`（连续性桥，派生）、
`last_session`（会话摘要，派生）、`carryover`（深省卡，派生）、
`relationship`（整文件片段）、`substrate_recall`（**按契约就是
`advisory_only` / `authority_class="derived_projection"`**，见 `substrates/base.py`）、
`diagnostic`（诊断接地，派生）、`other`（未映射标题，定义上未知）。

**16a：生产者只为 crystallized 一个类填 ID。**
`section_source_ids` 在 `_build_prefetch_sections` 内**只有一个赋值点**
（crystallized 专属），其余段落一律落到 `_section_metadata` 的空 `{}` 分支。
已为 `working` / `candidate` / `event` / `indexed` / `graph_layer` 五个类补齐：
- `working` → `working:<file_stem>:<item_id>`（规范格式已在
  `deep_reflection.py:639` 生产使用，前缀在 `v3_body_packet.py:21` 允许表内）
- `candidate` → `candidate:<candidate_id>`
- `event` → `event:<event_id>`
- `indexed` / `graph_layer` → `<record_type>:<record_id>`
- 并扩 `_extract_record_ids_from_section` 的前缀白名单
  （原只认 `crystallized:`/`candidate:`，所以 `working` **即使填了 ID 也无法分类**
  ——这正是 `classified_ratio = 0.7018` 的同源解释）

**实现方式选择**：用**可选出参** `source_ids: list[str] | None = None`，
而非改返回类型。理由：`_event_lines` / `_graph_layer_shadow_lines` 被测试直接导入
并断言其列表返回值，改签名会连带打破多个测试文件；而 `seen` 与 `error_records`
本来就是本文件既有的同款可选出参惯例。
**代价与对策**：可选出参正是 Section W 规则 4 说的那种"陷阱默认值"——
调用方忘了传就静默无归因。所以真正的护栏不是签名而是
**结果级测试** `test_real_prefetch_leaves_no_attribution_gap`：
跑一次真实 prefetch，断言产出的披露记录零缺口，
且**显式断言 working/event/candidate 三类确实出现**（否则测试会空过）。
反事实实测：删掉任一 `source_ids=` 实参 ⇒ 该测试与端到端那条**双双失败**，已确认。

#### 关键设计问题：为什么必须有"归因纪元"边界

只修生产者**永远清不掉那个 FAIL**。门是对**全部自然行**算缺口的，
而 3.200 上那 69 个有缺口的行**全都是自然行**——它们已经写入、
披露动作已经发生、ID 当时就没被采集，**无法追溯补齐**。

故引入 `memory_sources.ATTRIBUTION_SCHEMA_VERSION`
（`memory-os.memory_sources_attribution.v1`），新记录带此标记；
门**只对带标记的记录**判定归因健康，未带标记的自然行计入
`legacy_unattributed_record_count` 并继续留在
`all_history_attribution_gap_count` 里（**不是抹掉，是分类为债务**）。
这与同文件既有的 `legacy_unmarked_rollup_count`（处理 `trigger_class`
出现之前写的 rollup 行）**是同一个模式、同一个理由**，不是新发明。

#### 诚实护栏：不许"清零即变绿"

上一步有个显而易见的滥用空间：部署当天所有旧行都成了"债务"、
带标记的行为 0 ⇒ 缺口 0 ⇒ 报 PASS。**那就是靠缩小度量换绿色**，
正是待办 16 自己警告的事。故加：
- 当存在自然行但**归因纪元为空**时，`schema_era_health` 报
  **`healthy_no_sample`**（monitor 早已把它当 PASS 值收下，见 `:1389`，
  但字面上写明"没有样本"），**不报 PASS**；
- 同时追加 freeze reason `attribution_era_no_sample`，
  **clearance 在出现真实归因流量前不得解冻**。

#### 实测投影（3.200 只读，无部署）

用新判据在生产数据上跑一遍（本地重实现判据，不落任何文件）：

| | 值 |
|---|---|
| 总行 / 自然行 | 988 / 170 |
| 归因纪元行（部署前） | **0**（预期） |
| **旧**：`schema_era_attribution_gap_count` | **69 → FAIL** |
| **新**：`schema_era_attribution_gap_count` | **0** |
| **新**：`legacy_unattributed_record_count` | **170** |
| **新**：`schema_era_health` | **`healthy_no_sample`**（非 PASS） |
| **新**：freeze reason | `attribution_era_no_sample` |

**覆盖面是升了不是降了**（这条最关键，用来证明不是"买绿"）：
把**新**词表套到全部自然行上会命中 **129 行**（旧词表只有 69 行）。
新被检查到的段落：`event` 115、`indexed` 46、`candidate` 5
（`working` 69 原本就在检查内）。也就是说 CA.2 记的"静默跳过 1093 个段落"
在按行折算后确实存在，且现在这些类**已进入检查范围**——
只是那批行属于修复前、无法追溯，故落入债务侧。
（`substrate_recall` 的 133 个段落现在**明确豁免**，理由是它按契约就是
`advisory_only` 的派生投影，不是本地规范记录的引用——这比原先"名字对不上所以
碰巧不检查"诚实得多。）

**部署后的预期演进**：FAIL 立即转为 `healthy_no_sample`（不是 PASS），
clearance 保持冻结；随新流量产生带标记记录，`attribution_era_record_count` 上升，
届时**任何一条新记录漏归因都会重新 FAIL**。这是把一个"永远红且无人能修"的门，
换成一个"当前干净、且能真正检出新缺陷"的门。

#### 一个额外收获：注释也能触发架构防火墙

`test_x3_exposure_firewall::test_prefetch_ranking_not_contaminated_by_exposure`
**不只查 import，它扫 `prefetch.py` 的源文本**，禁止出现
`exposure_rollup` / `selected_count` / `exposure_rollup_lag` 三个串
（X.3：曝光数据不得回流进 prefetch 排序）。我写的解释性注释里写了
`exposure_rollup.ATTRIBUTABLE_SOURCE_CLASSES`，于是全量套件把它抓出来了。

本次改动**没有**新增 import、也没有数据依赖——归因是
"生产者写 ID → 审计侧读 ID"的**单向**关系。所以正确处置是**改注释、
保留防火墙**，而不是放宽那条测试。为了迁就一句注释去削弱一条架构测试，
是明显划不来的交易。已在三处注释中改为"审计侧"的说法并注明为何不点名。

（也再次印证：只跑自己新加的测试是不够的。这条是全量套件抓出来的，
新增的 10 个归因测试全绿也不会发现它。）

#### 测试与门

新增 `tests/plugins/memory/test_memory_os_attribution_contract.py`（10 个）：
词表双向守卫、每个可归因类都有可识别前缀、提取器认 `working:`/`event:`、
非规范 ID 仍被忽略、`working` 无 ID 即缺口、豁免类无 ID 不算缺口、
映射是唯一真源（含降级后缀）、新记录带纪元标记、
**真实 prefetch 零缺口（含防空过断言）**、端到端纪元内且干净。
另在 `test_memory_os_phase1_observability.py` 新增
`test_pre_attribution_era_gaps_are_surfaced_as_debt_not_gated`。

**改了 3 个既有测试的夹具**（保持原意，非削弱断言）：两个 `natural-anchor`
与一个 `natural-good` 都代表"当前纪元的健康记录"，故补上 `attribution_schema`
标记——否则它们会落到"无样本"侧，而它们的原意正是"健康且可解冻"。

**3115 → 3126 passed / 13 skipped / 0 failed（+11）**，数字对得上：
归因契约 10 + phase1 纪元债务 1。四门全过；`surface_count` 154 不变、
`unclassified_count=0`；空白检查按推送区间干净。

本轮全量套件因本机环境（C: 盘曾占满、后台进程被回收）分三段前台跑完，
三段均为最终代码状态、无过期分段：
`tests/plugins` 2086、`tests/scripts`+`seam`+`system_modularization` 1015、
`tests/ev*` 25 —— 合计 3126。

证据级别：**仅 `local_pass`**，未部署。**部署要点**：本节改的是判据与生产者，
不新增 lane，无需重生成 cron 注册快照；但 `memory_sources` 记录格式新增了
`attribution_schema` 字段，部署后应确认新写入的行确实带该字段
（否则门会一直停在 `healthy_no_sample`，而那正是"没有样本"的诚实读数）。

#### CC.1 — 复审：把"被我加宽的东西"的下游全查一遍

顾问复审提的三点，全部属同一类——**我加宽了判据，但没查判据的所有消费者**。
这正是 CLAUDE.md"越过被指出的问题、追整条调用链"那条规则的适用场景，
而我第一轮只查了自己**故意改的**那两个数。

**① `_memory_source_has_attribution_gap` 有三个调用点，我只给其中一个套了纪元。**
`all_history_gap`（全量 `ms_records`）与 `rolling_gap`（近 7 天）现在也在跑
**6 类**判据而非原来的**实际 2 类**，数字必然上涨——而我的投影脚本只算了
`schema_era` 一个。已补测（3.200 只读）：

| 计数器 | 旧 | 新 | 是否触发告警 |
|---|---|---|---|
| `schema_era_attribution_gap_count`（**唯一 FAIL 驱动**）| 69 | **0** | FAIL→清除 |
| `all_history_attribution_gap_count` | 778 | **844** | **否**，`info` 专用（Fix 2c 明写"绝不单独驱动 FAIL/WARN"）|
| `rolling_7d_attribution_gap_count` | 3 | **3**（不变）| **否**，**全 monitor 无任何引用** |
| `migration_debt_attribution_gap_count` | 709 | **844** | 否，同为 `info` |

结论：**本次部署不引入任何新的 WARN/FAIL**，只让 INFO 侧的债务数字更诚实
（+66 行，正是原先被静默跳过的那批）。`rolling_7d` 恰好不变，因为近 7 天只有 5 行。
另注：`rolling_7d_attribution_gap_count` **算了但没人读**，与
`exposure_rollup_lag_hours` 是同一个既有毛病，**本节未修**，登记为待办 17。

**② 新计数器"算了但没人读" —— 已修。**
`legacy_unattributed_record_count` / `attribution_era_record_count` 原本只是
被 `exposure_monitor_stats` 返回。远程与本地探针都是**整字典**透传
（`:5565`、`:4691`，无白名单），所以它们进得了快照——**但 monitor 不读**，
于是那 170 行债务与"有多少真实归因证据"这两个数**对任何读者都不存在**。
这正是我刚写进 CLAUDE.md 的反模式。已让它们搭既有 INFO 通道
（`v2_exposure_all_history_migration_debt`，天然就是"可见但绝不驱动 FAIL/WARN"），
并把 `legacy_unattributed_record_count > 0` 加入该 INFO 的触发条件——
否则当债务是**唯一**信号时（迁移债务为 0），整条 INFO 根本不发出。
反事实实测：去掉该触发条件 ⇒ 测试报 `StopIteration`（条目压根不存在），已确认。

**③ 三段式 `working:a:b` ID 从未走过 rollup 循环。**
已查：`_extract_record_ids_from_section` **无跨文件消费者**，
`exposure_rollup.py` 内**没有任何 `split(":")`/`partition(":")`**，
三个使用点（`:261`、`:269`、`:315`）一律把 ID 当**不透明键**用
（`id_classification[rid] = ...`、`selected_rids.update(...)`、`sorted(...)`）。
故三段式 ID 与 `indexed`/`graph_layer` 的 `<record_type>:<record_id>` 均安全，
**无需改动**。

**未采纳的一条**：`substrate_recall`（133 段）的豁免是全节最可能被质疑的判断，
但它有 `substrates/base.py` 的 `advisory_only` / `derived_projection` 契约依据，
且已写明理由，保持豁免。

**方法记账**：三点全是"消费者未审计"。我把 `ATTRIBUTABLE_SOURCE_CLASSES`
从实际 2 类扩到 6 类时，只想着"这样才检得全"，没想到
**同一个判据还被两个报告口径共用**。
**教训：加宽一个判据前，先 grep 它的全部调用点，并对每个调用点问
"这个数字变大了会不会触发告警、以及谁在读它"。**

#### CC.2 — 待办 17：给滚动窗口一个读者，并把 31 个键全查一遍

本节是**第一次按新流程做的**：写代码 → 全量套件 + 四门 → **顾问复审** → 折叠 → **才提交一次**。
此前 CB.1 与 CC.1 都是"先提交、后复审"，于是复审抓到的每一处都变成又一个补救提交
（`f4a3ccf`→`6b34976`、`47a077a`→`c261072`）。这是流程错误，不是手误。
折叠已完成：6 个提交合为 3 个，且折叠前后内容逐字节一致（`git diff --stat` 为空）。

**修法判定：`rolling_7d_attribution_gap_count` 定为 INFO，不给它单独的 WARN。**
待办 17 原本列了两条路。选 INFO 的理由是**它作为告警是冗余的**：
`schema_era_attribution_gap_count` 已经对**归因纪元内任意一条**有缺口的记录
无时间界地 FAIL，所以"近 7 天有缺口"必然已经被那条 FAIL 覆盖，
再加一个 WARN 只是更弱的重复告警。滚动窗口真正提供的是**诊断价值**——
一个 schema-era FAIL 到底是**正在退化**还是**纪元内的历史债务**。
所以给它读者（`v2_exposure_attribution_recent_window`，INFO），但不给它分级。

**顺带修掉一个我自己刚引入的语义错误**：`rolling_gap` 原先**没有**做纪元过滤。
若不改，生产者修好后的**头 7 天**里，它会因为窗口内还有修复前的旧行而报出缺口，
而生产者其实是正确的——一个"当前是否正在退化"的滚动信号，
用无法归因的历史行是答不出来的。已改为对 `rolling_era_records` 计数，
并新增 `rolling_7d_attribution_era_record_count` 作为分母：
**0 缺口 / 0 记录 是"近期没有归因流量"，不是"近期很干净"**。
反事实实测：改回 `rolling_records` ⇒ 断言 `1 == 0` 失败；
去掉 monitor 那段 INFO ⇒ `StopIteration`。两条都实测确认。

#### 31 个键的读者普查（待办 17 的第二半）

写脚本枚举 `exposure_monitor_stats` **真实返回**的键（调用函数取键，不解析源码），
再全项目扫 503 个文件找读者。**关键教训在于这个审计工具本身先给了我错答案。**

第一版把**注释里的提及**也算成"有读者"，于是 `exposure_rollup_lag_hours`
显示为"有生产读者"——而它在 monitor 里的两次出现**全是我自己刚写的注释**
（把它当作"已知无人读的指标"举例）。加上"跳过纯注释行"的过滤后，结论翻转。
**一个用文本匹配判断"有没有读者"的工具，会把谈论 X 误判为使用 X。**

修正后的准确结论：

| 分类 | 数量 | 说明 |
|---|---|---|
| 有生产读者 | 15 | 含本次新加的两个滚动键 |
| 仅测试断言 | 9 | 生产侧无消费者 |
| 仅文档提及 | 3 | |
| 任何地方都无读者 | 4 | |

**但要注意我这个审计的第二个局限**：它排除了生产者文件本身，
所以**内部消费**的键会被误判为孤儿。实测核对后，以下 4 个**并非孤儿**——
它们在 `exposure_rollup.py` 内部驱动 `freeze_reasons` / `schema_health`（`:542-558`），
而那两个是有读者的：`telemetry_degraded_count`、`initial_natural_cycle_count`、
`production_observation_days`、`budget_pressure_streak_days`。

**扣除内部消费后，真正"算了却无人分级、无人读"的键**（登记为待办 18）：

- **`schema_era_classified_ratio`** —— 最值得注意的一个。**这正是 BY.1 当作
  "数据成熟度"证据引用的那个 `0.6506→0.7018`**。它被计算、被写进快照、
  被写进本文档，但**没有任何代码读它、更没有分级**。
  一个被当作论据反复引用的数字，其实从未进入任何判定。
- **`exposure_rollup_lag_hours`** —— CLAUDE.md 早已记载它"从不分级"，本次确认无误
  （且我的审计工具一度把它误判为有读者，见上）。
- **`legacy_unmarked_rollup_count`** —— **这条最讽刺：我在 CC 节用它作为
  "把不可追溯的旧行分类为债务"的先例来论证归因纪元边界的正当性，
  而它自己也没有生产读者。**先例在**设计**上成立（分类而非抹除），
  但在**可见性**上同样不合格。反过来说，本次的
  `legacy_unattributed_record_count` 已经比它所仿照的先例更好——那个有读者。
- 其余：`cumulative_selected` / `cumulative_dropped_by_rank` /
  `cumulative_dropped_by_budget` / `cumulative_eligible` /
  `exposure_rollup_records_total` / `rolling_7d_natural_record_count` /
  `schema_era_natural_record_count` / `latest_window_start` / `latest_window_end`。
  这些多为快照上下文性质，未必都需要分级，但需要**逐个明确定性**，
  不能继续停在"算了不用"。

#### 新流程第一次见效：复审在提交前抓到一个真缺陷

这是本会话第一次**在提交前**跑顾问复审，它当场抓到一处——而且正是我整个会话
一直在记录的那个形状：**两种不同状态留下完全相同的证据**。

我给新 INFO 条目的守卫是**存在性**判断 `if v2_exposure:`。但采集失败时
`v2_exposure` **并不是空的**，它是 `{"schema_era_health": "unavailable",
"error_code": ...}`（`:4697`/`:4714` 两条填充路径都这么写，
`test_memory_os_3_200_monitor.py:526` 还钉了这个形状）——**truthy**。
于是条目照发，三个 `.get(...) or 0` 全取 0，
monitor 就会公布 `rolling_7d_attribution_gap_count: 0`、
`rolling_7d_attribution_era_record_count: 0`，
**与「近期确实很干净」的输出逐字节相同**，而实际上探针根本没跑成。
采集失败另有 WARN 上报，但这条 INFO 是在**把默认值当测量值发布**。

对照就在我这段代码上方：`v2_exposure_all_history_migration_debt` 用的是
**值守卫**（`migration_debt_gap_count > 0 or ...`），所以采集失败时它正确地保持沉默。
我偏离了近邻的既有约定。

已改为守卫「采集是否**成功**」（无 `error_code` 且 health 不在
`{unavailable, unavailable_remote_projection}`）。脚本外独立复验：
修前 `INFO entry emitted on collection FAILURE: True`，修后 `False`。
并补测试断言三件事：采集失败不发条目、失败本身仍有 WARN（沉默不等于整体沉默）、
**采集成功但近期确实为 0 时仍要发**——否则「沉默」与「测得 0」就分不开了。

**这正是把复审移到提交前的全部意义**：同一处缺陷，按旧流程会变成又一个补救提交。

**另记一处已知不一致**（顾问指出，非阻塞，登记在待办 18）：
`rolling_7d_attribution_gap_count` 现在是**纪元域**，而
`rolling_7d_natural_record_count` 仍是**自然域**。谁把这两个当成
「缺口/分母」配对使用就会算出错的比率。本次新增的
`rolling_7d_attribution_era_record_count` 才是正确分母。

#### CC.2 测试与门

**3127 → 3130 passed / 13 skipped / 0 failed（+3）**：纪元过滤（phase1）、
monitor INFO、以及复审抠出的采集失败静默各一。分三段前台跑：`tests/plugins` 2087、
`tests/scripts`+`seam`+`system_modularization` 1018、`tests/ev*` 25 = 3130。
四门全过，`surface_count` 154 不变、`unclassified_count=0`，空白检查干净。
（计数溯源：CC 节记的 3126 是 `47a077a` 时的状态；CC.1 的 monitor 测试使其成为 3127。）
证据级别：**仅 `local_pass`**，未部署、未推送。

**本节不修这批**——那是独立范围，且每个都需要单独的定性判断
（该分级、该进 INFO、还是该删）。**故意不做**，登记为待办 18，
而不是顺手扩大改动面。

## CD — 残留待办一轮清扫：18/14/11/9/13/10/2 七项关闭 + 3 部分关闭（2026-08-04）

按待办表的优先级顺序（18 → 14 → 11 → 9 → 13 → 10 → 2/3），每项独立反事实
（revert→FAIL→restore→PASS 全部实测）。顺链另抓出两个未登记的真缺陷（见 CD.2）。

### CD.1 待办 18 —— `exposure_monitor_stats` 孤儿键逐个定性

不套统一处理，逐键裁定（graded / info / internal / component / 删除）：

- **`schema_era_classified_ratio`**（优先项）→ **INFO**，新条目
  `v2_exposure_classification_coverage`。刻意不分级：累计比率混合修复前后的
  rollup，结构上就动得慢，没有证据支撑的阈值。**None 不得压成 0.0**——
  无样本发布 0.0 会读成"覆盖率灾难"，条目改为不发（与采集失败守卫同一条
  不造零规则）。
- **`exposure_rollup_lag_hours` / `latest_window_start` / `latest_window_end` /
  `exposure_rollup_records_total`** → **INFO**，新条目
  `v2_exposure_rollup_ledger_state`。lag 刻意不分级——上游安静时 lag 良性增长
  （待办 15 实测过的形状），分级必然在安静周误报；「跑没跑」已有
  helper-completion freshness 分级，「为什么没产出」由 CD.2 的 last_run 回答。
  `snapshot_status` 随行，防止空快照的 lag=0.0 读成"新鲜"。
- **`legacy_unmarked_rollup_count`** → 并入既有 **migration-debt INFO** 条目
  （它就是 rollup 侧的迁移债务），并成为该条目的独立触发条件之一。
- **`rolling_7d_natural_record_count`** → 并入 **recent-window INFO** 条目，
  注明是自然域流量体量、不是纪元域缺口的分母（CC.2 登记的域错配就此有了
  就地说明）；natural−era 差值顺便成为部署后验证信号（新行未打
  `attribution_schema` 时该差值不归零——正是 S266 登记的静默陷阱的探测器）。
- **四个 `cumulative_*`** → 定性为 `conservation_total_passes` 的 **component**：
  只在 all-history conservation 破裂（它们的诊断时刻）时随 migration-debt 条目
  发布分解，平时不刷屏。
- **`schema_era_natural_record_count`** → **删除**。名字撒谎（算的是全史自然行，
  不是纪元域），且恒等于 `attribution_era_record_count +
  legacy_unattributed_record_count`（两者都已 INFO 可见）。零读者经重新 grep 确认。
- **census 门**：`test_exposure_monitor_stats_key_census_every_key_has_a_disposition`
  钉死整个键集与每键定性——未来新增键必须先定性才能过测试，
  "算了没人读"不能再无声出生。
- **census 意外收获**：抓到 **`attribution_gap_count`** ——一个全项目零引用的
  `all_history_attribution_gap_count` 重复别名，**手工审计（CC.2）自己也漏掉了它**，
  因为它的名字是三个有读者键的子串。已删除。方法教训追加：子串键名会骗过
  逐键 grep，census 的键集等值断言不会。

### CD.2 待办 14 —— completion ≠ output：三个实例全部闭合

- **`exposure_rollup`**：两条字节相同的不产出退出路径（良性跳过 /
  `source_cursor_not_found`）现在每次运行都往快照写 `last_run` 块——
  封闭原因码集合 `{produced, no_new_records, source_cursor_not_found,
  legacy_source_cursor_missing, write_failed}` + 本次 new_records 数 +
  trigger_class。读者不重跑、不读源码即可区分"无输入"与"永久坏死"。
  经 `exposure_monitor_stats`（`last_run_outcome/at/new_records` 三键，
  census 已定性 info）进入 CD.1 的 ledger-state INFO 条目。旧快照无该块时
  如实报 `unrecorded`，不造真结果。写入放在 envelope 之外是刻意的：
  观测产物必须恰好在出事的那几条路径上存活，网关失败路径本身仍留在
  permit 审计轨迹里（代码注释已写明理由）。
- **`session_mirror`**：`auto_apply_graduated_session_mirror` 的每条退出
  （policy_not_active / no_matching_pending_session / execution_gate_blocked /
  produced / produced_zero / blocked）现在原子写
  `system/session_mirror_auto_apply_last_run.json`（定长状态文件，非账本，
  写面已登记 `session_mirror_auto_apply_last_run_state`，155/155）。
  未跑 scan 的路径**省略 counters 而不是填零**。monitor 对该文件的采集接线
  **显式不做**（与 BV 记录的 recall_facade 采集接线同类，留待下一次 monitor 批次）。
- **`_call_hermes_runtime_model` 裸 `""` 全调用方清查**（6 个生产调用方）：
  fact_judge、session_fact_extraction、llm_edge_proposer 本就正确；
  **`clearance_cycle` 是真缺陷**——逐对跳过使"每次调用都空回"的死判官
  对每条 provisional 记录**恒返回 `clear`**，恰是该函数 docstring 明令禁止的
  常量裁决；改为计数 `pairs_evaluated`，有配对却零判定时 fail-closed 返回
  `unknown/judge_unavailable`（沿用 C3 词表，不新增枚举值；部分判定仍可 clear，
  测试钉住两侧）。**`llm_contradiction_lane` 的 `""` 裸 continue** 改为记
  `llm_empty_content` error_record（与其异常路径对称）。
- **顺链意外收获（本节最重）**：给 contradiction lane 写空回复反事实时，
  测试在**到达 LLM 调用之前**就崩了——`CLAIM_EXTRACTION_PROMPT` 的 JSON 示例
  **大括号未转义**，`.format()` 对第一个配对就抛 KeyError 且无人捕获。
  即：**该 lane 只要找到候选对就必崩，从未在生产上成功跑过判定循环**，
  而全套件此前没有任何测试触达这个循环（clearance_cycle 早就用
  `__BODY_A__` replace 风格躲开了同一个坑——同一族缺陷在隔壁文件早有人踩过）。
  已转义并留注释 + 该反事实测试即回归门。全项目扫描：`llm_edge_proposer`
  的模板转义正确，无同类。

### CD.3 待办 11 —— `_check_vector_available` 不再执行 torch

`importlib.import_module("sentence_transformers")` 改
`importlib.util.find_spec()`（spec 查找不执行包）+ 进程级缓存。
status/doctor 单次 17–29 秒的成本归零；`shell_alias_no_env` 22 条并发探针
每条都省掉这段载入窗口（待办 3 的疑似成因）。反事实用爆炸 loader
（find_spec 返回 spec、create/exec 即炸）证明探测"知道装了"而"从不执行"；
stdout 污染守卫测试迁移到新机制，语义不变。

### CD.4 待办 9 —— 两个 shadow 账本可老化（forward-only）

选低爆炸半径的修法 A：两个 writer 补 `created_at`
（`graph_layer_shadow` 保留 `recorded_at` 给既有读者；
`substrate_recall_shadow` 原本无任何时间字段）。历史行仍不可老化——
**这是 owner 决策，刻意不做**（修法 B 会让两个从未剪过的生产账本立即
整体进入归档计划）。反事实经真实 producer 构造（吸取
counterfactuals-must-use-real-producer 教训）+ 未来时钟跑 plan：
两账本各 1 条 archive_candidate、archive action 成对出现；revert 后
恒 retained。确认无 signature-dedup 依赖整条记录（不会因新增时变字段
导致无界增长）。

### CD.5 待办 13 —— session_mirror 一般性队头偏置

机制查实：发现序按 session id / 文件名稳定排序，而 `dedup_key` 含
`content_sha256`——**活跃会话每次内容变化都以新 dedup_key 重回队头位置**，
配 per-run 上限后队尾永不露头（637 次运行、积压 1574→1575 的成因形状）。
修法：`platform_filtered` 稳定排序，**从未被本 lane 导入过的会话优先**；
"导入过"信号从 mirrored 事件的 `safe_ref.session_id` 派生
（与 BY 拒绝修复同一理由：存 state 的信号会在 `_rebuild_state()` 时无声消失，
测试专门断言删掉 state 文件后排序仍成立）。已导入会话的新内容版本仍会导入，
只是排在积压之后。事件账本从每次 scan 读两遍合并为一遍
（`_provider_captured_session_ids` 增加可选参数复用）。

### CD.6 待办 10 —— recall_golden authority 维度从死代码到真实现

- `matched_source_ref` 不再从期望值抄——从**实际命中的 section** 派生
  （`build_prefetch_section_candidates` 的 `metadata.source_ids`）；
  `matched_authority` = 该 section 的 `source_class`（词表即
  `prefetch.SECTION_SOURCE_CLASS_BY_TITLE`）。hit/miss 语义逐字不动
  （仍判预算后文本——agent 实际看到的东西；归因用 section 结构，二者分开判）。
- `classify_evaluation_item` 补齐语义：期望了 authority/source_ref 而披露
  **无归因可验** → `context_insufficient`（原先无分支可达）；**验证过且不符**
  → `source_authority_issue`（原先结构性不可达——反事实实测旧代码对
  错误 source_ref 期望返回 "hit"，因为比较的两边是同一个回声值）。
- **`min_score` 删除而非实现**：披露面不存在逐 section 分数，字段只能永远
  是死重量。loader 改为忽略未知键（生产主机上已部署的 golden 文件带着
  `min_score`，观测仪器不应因 schema 漂移崩溃），种子 fixture 同步清理。
- §3.3 退出条件「hit/miss/authority 报告」三项至此全部真实。

### CD.7 待办 2 + 待办 3（部分）

- 待办 2：`install_memory_os_plugin.py` 五处报告字段
  `str(path.relative_to(...))` → `.as_posix()`（与 BK 修 `plan_deployment()`
  同病同修）。反事实在本机（Windows）实测：revert 后嵌套路径含反斜杠即红。
- 待办 3：并发单测覆盖确认已由 CB 批次落地（并发归因 + 并发/串行基线
  一致性两测）；疑似根因（每条 CLI 探针 17–29s 的 torch 载入放大争用窗口）
  已由 CD.3 修除。**不宣称并发风险归零**——判定为已缓解 + 有覆盖，
  生产复核留给下一次部署后的 Full Monitor 观察，届时如再现再升级。

### CD.8 待办 8 登记更新（未开工，如实）

仪器侧本轮补齐：`session_fact_extraction` lane 已实现（CB，待部署）、
`recall_golden` 三维度已全部真实（CD.6）。A（没入库）/B（入库没召回）
分离分析仍需两件事：部署后的生产数据 + owner 提供的具体漏失实例。
不猜测、不预写修复。

### CD 反事实覆盖

12 条新增反事实测试全部 revert→FAIL→restore→PASS 实测（census 键集、
migration-debt 扩展、ledger-state、classification-coverage、recent-window
体量键、run-outcome 三态、死判官 fail-closed、空回复 error_record、
爆炸 loader、shadow 老化、队头排序 + rebuild 存活、authority 三测、
posix 清单）。另有 2 条守卫型（采集失败不发新 INFO 条目、缓存单次探测）。

### CD.R 独立复审与处置（提交后复审，fold 回同一提交）

独立复审 agent 对 `28dbf8a..4dd64b6` 的结论：无 Critical、3 Important、3 Minor，
"With fixes"。逐条核实后的处置：

1. **快照 `status` 与 `last_run.outcome` 矛盾（两处）——半接受**。
   write_failed 路径成立且已修：该路径 ledger append 没发生，快照的
   `latest_window_*` 描述了 ledger 中不存在的窗口，硬编码 `"ok"` 是双重撒谎，
   改为按 `report["status"]` 取值，反事实实测（revert 后断言
   `'ok' == 'error'` 红）。第二处（`_record_last_run_outcome` 的
   `setdefault` 保留旧 status）**推回**：那是有意语义——`status` 描述
   快照内容可用性（ok/empty/error），不是 lane 健康度；produced 后
   cursor 错误留下的 "ok"+`source_cursor_not_found` 是自洽组合
   （"累计数据有效；最近一次运行失败"）。语义已写进 helper docstring，
   并新增 produced→压缩→cursor 错误的实测断言把这对组合钉死。
2. **session_mirror last-run 文件无 monitor 读者——推回**：
   CD.2 与待办 14 更新中已显式登记"monitor 采集接线显式不做，
   与 BV 的 recall_facade 接线同类"；复审要求的"explicit stated follow-up"
   在复审前已存在。
3. **monitor 测试文件拼接错位——接受已修**：CD 的测试插入点误落在
   `test_attribution_recent_window_stays_silent_when_collection_failed`
   函数体中间，其 remote-projection / quiet-zero 两块被缝进新测试尾部
   （断言仍全部执行，无覆盖损失，但 docstring 与函数体不符）。
   纯代码搬移归位。**流程教训**：在测试文件中段插入时必须先读到
   函数真正的结尾，"看见一个完整断言块"不等于"看见函数结束"。
4. **Minor（原子性不对称）——接受**：`_record_last_run_outcome` 改用
   `write_json_atomic`（与 session_mirror 的同类 recorder 对齐；消除
   monitor 并发读到半写快照的窗口），新写面登记
   `exposure_rollup_last_run_snapshot_state`。其余 Minor 均为 pre-existing
   格式问题，不动。

### CD 测试与门

**3130 → 3153 passed / 13 skipped / 0 failed（+23，单次全量前台跑，11m27s）**，
增量与新增测试逐文件对账吻合（census 1、monitor 4、rollup 4、clearance 1、
contradiction 1、cli 2、shadow-aging 1、session_mirror 2、recall_golden 6、
installer 1）。复审处置 fold 后受影响三文件定向重跑 260 passed，
全量复跑 **3153 passed / 13 skipped / 0 failed**（8m58s，计数不变——
处置只加断言、搬移代码，不增测试函数）。
四门全过：import cycle 无环、write surface **154→156** /
`unclassified_count=0`（新登记 `session_mirror_auto_apply_last_run_state`、
`exposure_rollup_last_run_snapshot_state`）、static hygiene pass、
public checkout probe --strict exit 0、`git diff --check` 干净。
证据级别：**仅 `local_pass`**，未部署、未推送。

## CE — 核心开关守护：升级自动开、安装预设纠偏、断流探测器（2026-08-05）

Owner 指令：安装/升级脚本要保证核心功能自动打开、核心定时任务配置注册齐全；
外部对接可选项另说。审计后按三层收口（cron 注册链核查后判定已有兜底，见末段）。

### CE.1 翻转来源实锤：`production-safe` 预设本身就写 `enabled: False`

审计直接找到了 CD.E 断流的最可能翻转来源——不是"意外洗键"，而是**有意的
预设**：`MEMORY_SOURCES_PRESETS["production-safe"]["enabled"] = False`，
且有既有测试 `..._preset_is_explicitly_off` 把它钉死为设计。而
test-host / operational 两个预设都是 True——**唯独"生产安全"预设让生产
观测链全盲**。"safe" 的正确含义在 `mode=metadata_only`（永不含原文），
不在关掉记录器。已翻转预设并反转该测试语义
（`..._preset_enables_metadata_only`，docstring 记录 CE 裁定）。

### CE.2 升级自动开 + 归一化洗键根除

- `_ensure_config_defaults`（每次 install/upgrade 必经）新增**唯一一个**
  自动纠偏：`memory_sources.enabled` False→True。刻意只此一个——带
  shadow→apply 毕业管治的模式（context_router / recall_arbitration /
  owner_review …）**报告不翻**（`core_mode_report`），自动翻会绕过毕业管治；
  外部对接（hindsight / v3）不动。
- **顺链抓到并修掉一个真回归途径**：该函数原走 `load_config→save_config`
  往返，归一化会**剥离 schema 外的键**（其他安装步骤刚写入的 `preset`
  标记被洗掉——新增测试当场以 KeyError 复现）。改为 `_read_json_config`
  直读直写。这与 CD.E 的"配置重写翻开关"同族——**config 的 load→save
  往返本身就是键清洗器**。全项目余 3 处 `save_config` 调用点
  （cli.py:326 hindsight adoption、__init__.py:823、installer:1687）
  登记为待逐个核查的观察项，不在本轮扩面。

### CE.3 status 暴露记录器状态 + monitor 双检查

- `build_status_report` 新增 `memory_sources_recording`
  块（enabled/raw_enabled/mode）——开关状态首次有了可被 monitor 读到的面。
- monitor 新增两个 WARN 码（均注册 clean-host 分类、
  `production_behavior=fail_if_production`，沿 BD.1 机制生产升级 FAIL）：
  - `memory_sources_recording_disabled`：生产上记录器被关即红
    （CD.E 那四天的形状，今后活不过一次 monitor）；
  - `memory_sources_disclosure_outage`：**断流签名**——stats 窗口
    （24h）内零披露而同窗口内存在 provider 捕获的对话事件。事件时间戳
    由 correlation probe 顺手带出（`latest_conversation_turn_ts`，
    同 writer 统一 isoformat，分类端解析比较不做字符串比较——BF.3 教训），
    旧快照无该块时按值守卫静默（不造零、不误报）。
    "安静≠坏"的对偶有测试钉住：对话在窗口外、或披露正常时不告警。

### cron 注册链核查结论（不改代码）

- 快照重生成已由 install/onboarding 归口（CB 部署要求，CD.D 端到端证实）；
- job 缺失/漂移已有兜底：per-lane helper-completion freshness（due 窗口内
  必 WARN）、unregistered drift 分类、owner_review 专项 job missing 检查——
  核心 group job 消失最迟一个 due 周期内可见；
- onboarding 创建 job 保持 owner-gated（`--owner-approved` 经 ResolverGate），
  deploy 不自动创建——这是边界不是缺口。

### CE 反事实覆盖与测试

新文件 `test_memory_os_core_switch_guard.py` 6 测 + 预设语义测试反转，
revert 三源文件实测 5 红 1 绿（绿的一个是守卫型负向断言，天然非反事实）。
`preset` 洗键回归由既有 `..._llm_judge_active_config` 测试以 KeyError
复现、修后转绿。

### CE 测试与门

定向 281 passed（monitor/cli/runtime/install/guard 五文件）+ 四门全过
（import cycle / write surface 156 不变 unclassified 0 / static hygiene /
public checkout probe --strict）、`git diff --check` 干净。
全量 **3158 passed / 13 skipped / 1 failed**——唯一失败为
`test_execution_gate_runner_serializes_parallel_sidecar_updates`，
已登记在案的并发环境 flake（与本批改动无调用关系），隔离重跑
整文件 11 passed + 单测 passed，判定非回归。
证据级别：`local_pass`；monitor 双检查的 `live_monitor_pass` 待下一次
统一部署后取得。

## CF — 生产首个 FAIL 的根因修复：无溯源候选与聚合 lane 崩溃（2026-08-05）

CE 部署后的 Full Monitor 出现新 FAIL
`execution_gate_memory_os_cron_helper_completion_error`（lane =
`candidate_aggregation`，12:12Z 起 rc=1 无 helper 报告）。手动复现拿到实锤：
`CrystallizedApprovalError: crystallized records require source_event_ids`。

### 根因链（三层，各自都是真缺陷）

1. **产出侧**：`session_fact_extraction` 首跑写入的 5 个候选
   `source_event_ids=[]`——事实来自会话而非事件，CB 实现时留空。但结晶
   写门在**所有**批准路径（含 Owner）都要求非空溯源 ⇒ 这些事实**永远
   无法结晶**，缺陷在候选出生时就注定。
2. **通道侧**：sfe 候选带 durable_fact 裁决，走聚合 lane 的
   durable-fact 单条 bypass 被 resolver 自动批准——自动批准一个结构上
   不可能写入的候选，唯一可能的结局就是撞门。
3. **隔离侧**：`_write_resolver_provisional` 失败后 re-raise 无人接住，
   单个坏候选把整条聚合 tick 打崩（rc=1），且每次 due 都在同一候选上
   重复崩——**队头卡死家族的聚合版**：一个坏候选永久饿死其后所有候选。

### 修复（三层各修 + 反事实）

- **产出侧**：lane 为每个产出事实的会话惰性铸造一个
  `session_fact_extracted` 溯源事件（每会话每 tick 一个、metadata-only、
  `candidate_allowed=False` 防止 heartbeat 二次造候选——形制照
  session_mirror 事件），事件**先于**候选写入（反序会造出无锚候选），
  所有该会话事实候选共享引用。溯源链自此完整：crystallized → event → session。
- **通道侧**：`_resolver_verdict` 头部新增资格判定——空 `source_event_ids`
  即 `approve=False / missing_source_event_ids`，三条通道（cluster、
  durable bypass、no_keyword singleton）一处全覆盖，候选改道 owner review。
- **隔离侧**：新 `_try_write_resolver_provisional` 边界——写失败记
  `provisional_write_failed` error_record（进 lane 报告的
  `suppressed_error_count`，monitor error observability 既有读者）、
  候选 triage 为 `owner_eligible`、tick 继续。
  `_write_resolver_provisional` 内部的 failed envelope 闭合语义保持不变。
- **语义变更测试更新**：既有
  `test_resolver_write_exception_records_failure_completion` 原钉"写异常
  必须冒顶"，按新契约反转为"必须不冒顶 + failed 完成记录仍在 +
  error_record 上报"（断言集为旧测试的严格超集减去传播）。

### 生产处置（部署后实测更正原方案）

**原拟"demote + 清指纹重抽"经查证不可行，如实更正**：
`append_candidate_queue` 写时按 `candidate_id` 去重（crystallized.py，
锁内成员检查），而 sfe 的 id 由 (session_id, message_index, fact_text)
稳定派生——重抽产出的同 id 新行会被去重拒绝，旧的空溯源行永远是队列身份。
且 demote 属 OwnerGate 永久边界（BR 刚堵过伪造 demote），不可自授权。

**实际处置（全部在治理面内）**：CF 部署后手动触发一次聚合 lane
（gate helper，正常 envelope）——lane 不再崩（status ok、envelope ok），
全部存量 sfe 候选（含部署前后续 tick 又产出的 2 条，共 7 条）被资格门
安全改道 **owner_eligible**，同 tick 还恢复了对其他积压候选的正常
resolver 批准。存量候选的终局处置留给 owner 三选一：
digest 里 reject（累积 3 次自动 demote）／owner 权威 demote（之后
compact 会归档 demoted 行）／对 agent 直接口述这些事实走正常捕获链
重新入库（新对话事件 → 带完整溯源的新候选）。

### CF 部署与生产验证（2026-08-05）

- 备份 `memory-os-pre-cf-20260805T162127Z.tar.gz`（45M，excl. WAL/SHM——
  上一次备份被活跃 `db-wal` 打断的教训）；`/opt` ff `9ac2c79 → d08dc90`；
  deploy production-safe apply 全程 `fail=[]`。
- 手动聚合 tick：`status ok`、envelope `ok`、7 条 sfe 候选全部
  `owner_eligible` triage——三层修复生产实证。
- Full Monitor 首跑出现瞬时 `doctor_not_ok` + `index_not_healthy_in_production`
  （采集撞上 16:12Z tick 与手动 lane 的索引写；status 随即报 healthy、
  原样复跑不复现——待办 3/BY.3 同族瞬时争用，如实登记不改判）。
  复跑 **100 PASS / 4 已知 WARN / 0 FAIL**。
- 证据级别：`deploy_pass` + `live_monitor_pass`（0 FAIL）。

### CF 反事实覆盖与测试

4 条新反事实全部 revert→FAIL 实测且失败模式各自精确（verdict 反转、
生产同款 CrystallizedApprovalError、TypeError、空 source_event_ids）+
1 条语义反转测试。定向 102 passed（聚合两文件 + sfe 两文件 + 新文件），
四门全过。**全量首跑抓到定向漏网的一个真回归**：新的
`candidate_aggregation` error_record 发射点未登记
`ERROR_RECORD_EMITTING_COMPONENTS`（守卫测试
`..._constant_matches_source` 当场红，即该登记的现成反事实）——
再一次证明"定向绿≠全量绿"（BV/CC 同款教训）。登记后
monitor 文件 235 passed，全量 3162+1 → **3163 passed / 13 skipped**。

## CH — 图谱层+Overlay+V3 前置十项单批修复 W0–W9（2026-08-06，提交 `1f65fde..`）

Owner 决策：不分批——全部修完一次提交合并部署验证。审计与方案见
DEEP_ANALYSIS 第 11–13 节（图谱 E1–E7、Overlay S1–S6、任务表 W0–W9），
本节只记根因、修法、反事实与实测更正。全程严格 TDD（每项反事实先红后绿）。

### 修复十项（根因 → 修法）

1. **W0/E7 边状态迁移易失**（二次审查新发现）：`transition_edge_state`
   只写 SQLite，`index_sync` 每 30 分钟 clear+全量重投影 → owner 的
   approve/reject 最多存活 30 分钟。修：迁移前把整行更新记录追加进
   `graph/edges.jsonl`（canonical-first；投影 last-writer-wins per edge_id
   由守卫测试钉死）；`roots` 设为必需关键字（可选默认=非耐久迁移的地雷，
   W 规则 4）。反事实：迁移后跑 sync/rebuild 状态必须保持（无修复必红实测）。
2. **W1/E2+E3 去重超穿+队头配对偏置**：proposer 侧 `query_edges limit=1000`
   被 2118 存量超穿（生产 769 冗余行/36%，周产出 78% 为原样重提）；配对
   `order by created_at` 升序+200 对截断永远只嚼最老 ~20 条记录。修：
   `write_governed_edge` 成为唯一去重权威（structural 无向配对级、其余
   三元组级、无 limit）；**structural 收回 refines/contradicts 提名权**
   （词元重叠只证相关不证语义——refines 占 91% 的毛球根源），相似度/共享
   溯源一律 co_occurs；配对改未建边记录优先稳定序（per-proposer 覆盖判定）。
   3 条旧测试按新词表反转（T2.1.1/T2.1.2/T2.1.8）。
3. **W2 存量压缩**：`memory_os_graph_edges_compaction.py`——按三元组
   keep-earliest、其余经 W0 机制转 invalidated（G3 不删）、默认 dry-run、
   幂等、apply 落 `system/graph_edges_compaction_report.json`。
4. **W3/E1 审批断链**：全库无 candidate→owner_eligible 路径而 digest 只查
   owner_eligible → owner 从未见过边审批项（旧测试直接调 transition 走通
   状态机=fixture 词表陷阱）。修：新增 `edge_promotion` 认知循环步骤
   （每轮 top-10 by weight 晋升 + 30 天 TTL 有界作废）；digest 改 top-10+
   待审计数+批量语法；approve_edge/reject_edge 支持逗号批量（全部存在才
   过校验，单 id 返回形状不变）；**词表双向守卫**把
   `EDGE_STATE_TRANSITIONS`/`EDGE_REVIEW_DIGEST_STATE`/`PROMOTION_*_STATE`/
   `GRAPH_INJECTION_EDGE_STATE` 四方常量绑死——"消费者查询无人生产的状态"
   不可再静默复发。
5. **W4 溯源边**：`edge_provenance` 步骤从 source_event_ids 挖
   event→crystallized evidence_for auto-active 边（元数据结晶时已过
   OwnerGate；方向使 event 锚点一跳可达结晶目标——shadow 账本月命中 4 次
   的根源是图里只有结晶↔结晶边）；注入侧对非 crystallized 目标不落
   `[unresolved:]` 兜底（事件被 retention 清理属可容忍悬挂）。
6. **W5/E4 llm 通道死亡一个月（根因与预判不同，如实更正）**：非 wrapper
   env 问题——`43da529`（6/18 agent/→memory_os_agent/ 改名）后 /opt 检出
   残留 `agent/__pycache__` 空壳目录成为 **namespace 包**，被 provider ABC
   探测缓存进 sys.modules，此后 hermes_cli 的 `import agent.portal_tags`
   永远命中幽灵包（namespace 动态 `__path__` 收不进 regular 包）。修：
   resolver 回退分支驱逐 `__file__ is None` 的幽灵缓存后重试（真宿主包
   永不驱逐），任何主机的残留壳目录免疫；三个 proposer step 包装器透传
   reason/code/计数（skipped 不见原因=拖一个月才发现的直接原因）。
   反事实：幽灵包生产同款机制复现，先红后绿。
7. **W6 观测面**：monitor 新增 `v2_graph_governance_state` INFO（五个图谱
   步骤 status/reason/counters；旧报告不捏造测量）+
   `v2_output_knob_override_state` INFO + `v2_output_knob_override_expired`
   WARN（E5：注入 knob 07-01 静默过期无人知晓）+ collection_failed WARN；
   两个新 WARN 码注册 `CLEAN_HOST_WARN_CLASSIFICATIONS`（BJ 教训），
   测试含注册断言。
8. **W7/S1-S3+S6 Overlay 陈旧缓存族**：快路径无条件用缓存而 live 锚点只在
   慢路径被读（docstring "or stale" 撒谎；retriever 同款被 shadow 掩盖）。
   修：live 锚点覆盖 active_projects 一节（其余 section 保持缓存，O(1)
   不变），投影抽单一生产者 `extract_task_anchor_line` +
   `override_active_projects_with_live_anchor`，覆盖时中和
   task_revision/task_source_at/task_record_id；S6（owner 决策）：
   casual_continuity 路由排除 Memory State Overlay（路由屏蔽前台任务，
   Overlay 不得开侧门——该泄漏今日已在发生，非修复引入）。反事实两条：
   缓存空+live 非空→含锚点；**缓存旧 A+live B→必须 B**（防"仅填空"蒙混）。
9. **W8/S4-S5 quiet gate fail-open**：前台判定读同一陈旧缓存且读取失败
   放行漫游；生产 `wandering_enabled` 已 true、唯一拦截是
   activation_evidence_ready 自动计算值（R4 复查日 09-05 硬前置）。修：
   改读耐久台账 `read_effective_current_task` + fail-closed
   （task_state_unreadable 判"在忙"）+ 24h 有界年龄防僵尸锚点反向压制。
   `evaluate_v3_quiet_gate` 此前**零测试覆盖**，本批 4 条反事实为第一道防线。
10. **W9/E6 实体抽取质量**：24 实体中 21 个为 path/url/uuid/ip 碎片。修：
    `INDEXABLE_ENTITY_CLASSES` 只收 proper_noun（classify 词表保持，未来类
    显式 opt-in）；`entity_index_enabled` 保持开启（生产 config 显式
    `require_shared_entity: true`——关停即冻死 V3 激活门）。8 条旧测试按
    新词表反转（附带修正 fixture 句首大写被贪婪并入专名的共享失配）。

### 全量首跑抓到的漏网（BV/CC/CF 同款教训第四次应验）

定向全绿后全量首跑 2 failed：W9 的索引过滤**静默改变了共享谓词**——
`_looks_like_operation_context` 用 `extract_entities` 判"动作词+具体目标"，
需要的是引用**探测**语义（path/URL/UUID 正是证据）而非入索引资格。修：
`extract_entities` 显式 `classes` 参数 + `REFERENCE_DETECTION_CLASSES`，
三个调用方清查各归其位（entity_index/index 走索引默认，operation gate
显式探测集）。正是 W 规则"改共享谓词前 grep 每个调用点"的又一实例。

### 测试与门

- 新增反事实/守卫测试 **41 条**（graph_layer 8、edge_promotion 11、
  edge_provenance 4、compaction 4、low_clue 幽灵包 1、cognitive census+
  reason 2、monitor 2、state_overlay 4、context_router 1、wandering 4、
  entity 1），全部先红后绿实测；语义反转旧测试 12 条。
- 四门全过（import_cycle / write_surface 163 面 0 未分类 / static_hygiene /
  public_checkout_probe PASS）+ `git diff --check` 干净。
- 全量复跑（最终集成态）：**3233 passed / 13 skipped / 0 failed**。

### 部署要求（见 DEEP_ANALYSIS §13.2a 部署清单）

要点：①删除主机幽灵目录 `/opt/Hermes-Memory-OS/agent/`（仅剩 __pycache__）
及 runtime 布局同名残留;②compaction 先 dry-run 核对（预期 332 组/769 行）
再 apply;③手动触发一次 cognitive loop 验证 llm 复活/新步骤产出;
④Full Monitor **预期新增 `v2_output_knob_override_expired` WARN**（E5 的
告警终于响，owner 决策注入续期前持续存在，预期而非回归），0 FAIL 为准。

### CH 部署与生产验证（2026-08-06，实测）

- CI（dispatch run 31127471450，分支 push/PR 事件未触发 run 的原因未查明，
  用 workflow_dispatch 手动拉起）success;PR #34 merge 合入 main `92db7c6`。
- 备份 `memory-os-pre-ch-20260806T202748Z.tar.gz`（54M，excl. WAL/SHM）;
  `/opt` ff `968b120 → 92db7c6`。
- **幽灵目录实测两处并清除**：`/opt/Hermes-Memory-OS/agent/`（仅
  __pycache__）与 **`~/.hermes/memory-os/runtime/python/agent/`** —— 后者
  正是 systemd wrapper PYTHONPATH 首位路径，进一步坐实 E4 根因链。
- deploy production-safe 五阶段全绿（preflight/dry-run pass、apply applied、
  六探针全 pass、postcheck pass，`fail=[]` 全程）。
- compaction：dry-run 与审计数字**精确一致**（332 组/769 行，账本已长到
  2154），apply `invalidated_count=769 / failed=0`，幂等复核 0/0。
- 手动 cognitive loop（20:41Z）：**llm_edge_proposer 复活**（status ok，
  不再 llm_runtime_unavailable）;structural 为新记录建边 61 条
  （record_count 25→32，去偏置生效）;**edge_provenance 首轮产出 30 条
  跨层溯源边**;edge_promotion 晋升 10 + TTL 作废 100（candidate 1415）;
  整体 warning 与部署前同源（left_brain_advisor，既有）。
- Full Monitor 首跑 101 PASS / 6 WARN / 1 FAIL（`shell_alias_no_env_failed`
  —— 待办 3 记载的部署窗口瞬时争用，**第二次实测同模式**）;原样复跑
  **0 FAIL / 5 WARN**：`v2_output_knob_override_expired`（本批预期新告警，
  E5）+ 4 项既有家族（suppressed_errors、helper disabled/boundary 两兄弟、
  runtime_over_target）;agenda digest WARN 随复跑消失（apply 窗口采集
  碰撞家族又一例）。
- 证据级别：`deploy_pass` + `live_monitor_pass`（0 FAIL）。
- 待观察（非阻塞）：下一期 owner digest 应出现 Pending Edge Review
  （top-10 + 批量语法）;branch push/PR 未自动触发 CI 的原因待下次遇到
  再查（dispatch 路径可用，实测为 GitHub Actions 服务端瞬时故障——两次
  dispatch run 被分配 runner 后零 step 挂 15 分钟被判死取消，重试自愈）。

### CH.2 —— S6 终局：状态层百分之百原样注入（owner 决策，2026-08-06）

部署当晚 owner 追问 S6 触发机制后确认：首版实现（casual 路由整段排除
Overlay）**砍粗了** —— casual_continuity 是兜底默认路由（无任务/诊断/
候选/低线索信号的消息全部落入），整段排除让这些消息丢失全部状态层，
抑制面远大于泄漏面（泄漏面只有前台任务内容一节）。owner 原话两句本为
一体：「该默认抑制就该抑制」+「关键是看怎么样优化精确的自动选路」，
首版只执行了前半句。

演进：①整段排除（部署过，存活数小时）→ ②精确化为仅抑制 active_projects
一节（TDD 完成、未部署）→ ③owner 终局裁定「**状态层百分之百原样注入，
S6 降为观察项。状态层是整个记忆系统的精髓，活起来最重要的东西**」——
撤销一切路由抑制。

最终形态：所有路由（含 casual 兜底）下 Overlay 全部节完整注入,Active 为
W7 live 覆盖后的实时锚点;闲聊上下文携带前台任务内容为已知观察项。
`suppress_active_projects` helper 随之删除（不留死代码）;
`_state_overlay_lines` 的 `query` 参数保留为路由感知演进入口。
反事实守卫：`test_s6_final_overlay_injects_fully_on_every_route` 三路由
断言全注入——任何人重新引入路由抑制必先红此测试并经 owner 再决策;
router 级整段排除的撤销由
`test_w7_s6_casual_continuity_does_not_exclude_overlay_section` 钉住。
教训：**兜底默认路由上的排除规则,影响面是"全部未识别流量"而非该路由
字面语义**——在 default 分支上做减法前必须先量化落入 default 的流量占比。

### CH.3 —— 图谱治理模型重构:全自动生长 + 动态遗忘(owner 决策,2026-08-06)

Owner 追问后裁定:「这个不是自己生成图谱按匹配注入自动逐层展开才对的吗?
每次要我去审批就不对了。动态图谱应该是动态去更新关系的…不是永远记忆
不需要人工介入才对」。W3 的审批模型(candidate→owner_eligible→digest
审批)与动态图谱本性相悖 — 边是派生投影(advisory),不触碰任何
OwnerGate 永久边界,错误的边应由使用信号淘汰而非人工把关。澄清:注入侧
本就是匹配分层有界的(锚点驱动一跳展开、8 条/220 字符/去重,depth=2
机制已备),无上下文爆炸问题;要改的只是治理模型。

四个落地件(全部 TDD,先红后绿):

- **R1 全类型 auto-active**:三个 proposer + provenance 产出直接 active;
  llm 的 `_REVIEW_REQUIRED_TYPES` 清空(取代旧 §6/G4/T2.3.2 需审契约 —
  contradicts 的下游消费 crystallization_gate 只产 owner 可见标记,自动
  生效不执行任何动作)。词表+源码级守卫防回退。
- **R2 晋升通道 → 自动激活通道**:`PROMOTION_TARGET_STATE` 改 `active`,
  source 扩为 (candidate, owner_eligible)(清空 legacy 态,不留孤儿),
  25/轮按权重分批消化存量(约 1300 条,一次性放闸会把旧 refines 毛球
  灌进注入池),30 天 TTL 清尾。
- **R3 digest 边审批区段废除**:「Pending Edge Review」整段删除,
  `EDGE_REVIEW_DIGEST_*` 词表常量删除;`reject_edge`(含批量)保留为
  owner 纠错工具,永不主动推送。随删的 error_record 发射点由
  `ERROR_RECORD_EMITTING_COMPONENTS` census 守卫当场抓到并同步注销
  (双向守卫再立一功)。
- **R4 权重反馈闭环**(「动态更新关系」的本体,新模块
  `edge_weight_feedback.py` + 认知循环步骤):注入命中
  (graph_layer_shadow 真实生产)→ 边 weight +0.05(cap 1.0,新
  `index.update_edge_weight` 走 W0 同款 canonical-first 持久化,重投影
  后保持);active 边 60 天无命中 → invalidated(遗忘,每轮上限 50)。
  两道防误杀:遗忘水位取 max(created_at, last_hit, **闭环首跑时间**)
  ——"60 天无命中"从开始记录命中之日起算,防上线首日屠杀存量;
  shadow 账本不存在(注入从未活跃)时不执行遗忘 — 无命中数据 ≠ 边无
  价值。Durable state:`system/edge_weight_feedback_state.json`
  (cursor + per-edge last_hit),闭环 outcome 封闭原因码。
- **R5 注入开启**(部署步骤):`graph_layer_injection_enabled` 置 true
  无过期(owner 本段话即授权),monitor 的 knob 过期 WARN 随之消失。

词表双向守卫更新为新拓扑:proposer→active(直接)、backlog→自动激活、
active→注入消费+反馈遗忘、invalidated 终态;digest 不再是任何边状态的
消费者(census 断言 `EDGE_REVIEW_DIGEST_STATE` 不复存在)。

### CH.4 —— E8 锚点管线失效:图谱注入"无感"的最后一公里(2026-08-07)

Owner 部署后实测"完全没感觉到动态图谱注入",三层诊断(全部生产实锤):

1. **测试话术走 casual 兜底路由且无检索命中** — 04:01-04:17Z 三次
   prefetch 的 selected 段无 Indexed Recall → FTS 零命中 → 锚点空 →
   图谱一跳展开无起点(匹配才注入的设计行为,非故障)。
2. **E8(真缺陷):锚点管线对中文对话结构性失效**。
   `plan_query_route` 的 `entities or chinese_keywords` 短路 — query 含
   任何拉丁词时中文实词整体丢弃;派生出的多词 search_query 在 FTS AND
   语义下断崖式 0 命中(实测 'Memory-OS Hermes':两词单查各 5 命中,
   AND 交集 0;'审批 闭环' 同样 0)。双重作用 → 锚点恒空 → **shadow
   月命中仅 4 条、历史 1019 次 prefetch 仅 19.5% 有 FTS 命中的根因**。
   修复:`_collect_anchor_ids` 增加有界回退(派生词逐词并集 + 中文
   关键词表补词;词 ≤6/每词 limit 3/锚点 ≤5),**不碰全局共享的
   plan_query_route 谓词**(W 规则:改共享谓词前全面 grep;Indexed
   Recall 的派生行为不变,中文丢词的通用改进另议)。4 条反事实
   (AND 回退/中文补词/直接命中不回退/有界)先红后绿。
**CH.4 部署与端到端验证(2026-08-07 实测)**:E8(PR #40 `6d68955`)+
E8b 结晶优先(PR #41 `cf98f48`)+ E8b 回退双段补钉(PR #42 `41e6054`),
三段 CI dispatch success、deploy apply+postcheck 全绿。生产复验驱动的
两次补钉:①E8 后锚点 0→5 但清一色 event(FTS 通用命中被事件量级淹没,
'审批'/'Memory-OS'/'Hermes' top8 全 event;边密度在结晶层)→ E8b
index.search 加 record_type 过滤+锚点双段;②主查询双段皆 0(AND 失效
同样打击限定段)走逐词回退而回退无限定段 → 补钉回退双段独立池。
**最终端到端实证**:同一条此前 0 锚点的中文 query → 锚点
[cry×2, evt×3] → **Related Memory 段出现**,真实展开 2 条相关记忆。
全量 3246 passed / 13 skipped。附带观察:一条边目标显示
[unresolved:cry_...](指向已不在现役的结晶记录)— 属既有 fallback
设计,权重反馈遗忘或 reject_edge 可清理,不阻塞。
**E8c(owner 重启后复验,06:30Z 实锤)**:锚点命中、查到边、shadow
落账(月来首次新行),但目标恰好已被 Indexed/Crystallized 段展示 →
跨段去重静默吃光注入行 → Related Memory 恒空。小图谱阶段检索命中集
与一跳邻居集高度重叠,静默去重让图谱贡献永远隐形。修(PR #44
`0798c2a`):去重命中降级为 ↺ 短关系行(只含关系+id 引用,≤160 字符)
——「已展示记忆间的关联」是图谱独有信息。端到端终验:两条不同中文
query 的 Related Memory 均出现(完整行+↺ 行混合)。全量 3247 passed。
**Gateway 需再重启一次以加载 E8b/E8c(时机归 owner)。**

3. ~~Gateway 24 天未重启~~ **实测更正(owner 指出后复查)**:初判把主机上
   无关测试容器的 s6 监督进程误认作 gateway——真实 gateway 进程为
   `/usr/local/lib/hermes-agent/venv/.../gateway run`,owner 重启有效
   (复查时 etime 40 分钟),runtime 布局 prefetch.py 带 W7 标记 —— 今日
   新代码**已加载**。教训:**监督进程的 etime 不是被监督进程的 etime**,
   判断进程年龄必须找到真实子进程,不能拿 supervisor/wrapper 凑数。
   E8 部署后需再重启一次 gateway 以加载(时机归 owner)。

**CH.3 部署与生产验证(2026-08-07 03:26Z 实测)**:PR #38 → main
`766d797`(CI dispatch success);deploy apply+postcheck 全绿;
`graph_layer_injection_enabled` override 写入
(`ko_20260807T032634339954Z_2ead5a8827`,无过期,
approved_via=owner-decision-2026-08-06-dynamic-graph-auto-injection,
resolve 实测 True)。手动 loop 首轮:**edge_promotion 自动激活 25 条**
(backlog 1274 递减中,TTL 100)、**edge_weight_feedback outcome=
reinforced**(消化 4 条 shadow 命中记录、32 条边加权、0 误杀 — 防误杀
水位实证)。Full Monitor **0 FAIL / 5 WARN**,且
`v2_output_knob_override_expired` WARN 消失(E5 告警闭环:过期→告警→
owner 决策→续期→告警解除,全链路走通)。全量测试 3240 passed /
13 skipped(首跑抓到 1 条漏改的 vector candidate 断言 — 第五次
"定向绿≠全量绿")。证据级别:`deploy_pass` + `live_monitor_pass`。

**CH.2 部署与验证（同日）**：PR #36 → main `1580cc0`,CI dispatch
success;`/opt` ff `92db7c6 → 1580cc0`,deploy apply+postcheck 全绿
（`fail=[]`）;Full Monitor **0 FAIL / 6 WARN**。新出现的
`casual_context_needs_review` WARN **不是回归**：它是既有 RH26 casual
上下文契约探针——SAFE 集合外的段落 WARN、FORBIDDEN 四段
（Current Foreground Task/Diagnostic/Runtime Facts/Candidates）才 FAIL。
S6 撤销后 Overlay 段出现在 casual 探针输出 → WARN,**这正是"S6 降为
观察项"的机械载体**（monitor 每期替 owner 盯着,硬泄漏 FAIL 防线仍在）。
owner 若日后决定静音：把 "Memory State Overlay" 加进
`SAFE_CASUAL_HEADINGS` 即可。其余 5 WARN 与 CH 部署时相同
（knob 过期预期告警 + 4 既有家族）。全量 3234 passed / 13 skipped。

## 待办

**图谱遗忘潮预期落点：2026-10-06 前后（CJ 登记,2026-08-07）。**
first_injection_at=2026-08-07 起算 60 天,过密图谱（refines 为主,重归一后
0.45 档 1009 条）将开始被 R4 分批作废（每轮 ≤50,`forget_eligible_backlog`
显示积压）——**预期且可取的瘦身,不是故障**。真告警只有一个:
`invalidated_never_hit_count` 持续走高 = 探索位轮转覆盖不足（饿死信号）。
届时另核 09:55Z 失控 disable 行来源（CJ 节,owner 确认是否本人所写）。

**Indexed Recall 的 router 二审问题（CK 登记 → 当日按历史数据裁定:维持
现状,不修）**：owner 追问「历史数据能否立刻下结论」— 能。全史 1030 条
披露行实测:Indexed 非空出现 303 次,选入 160(52.8%);丢弃 143 中
route_excludes 123(旧版路由规则,已不在现行代码)、风险码击杀 53(防
泄漏正常工作)、**词表 below_threshold 仅 18(6%)**;近期切片(08-01 起,
E8b 后)选入 14/词表否决 1/风险 0 — 当前流量下几乎不存在。6% 不构成
放宽 casual 防线的理由。对照:同账本 Related Memory 全史仅出现 1 次
(CK 的必要性一个数字说明)。若未来 agent 体验反例出现可凭同一账本重查。

**V3 激活复查日：~~2026-09-05~~ → 顺延至 2026-09-12（owner 批准 2026-08-14，
按同一"不许无日期搁置"规则记录成因）。**
标准不变：届时 `v3_seed_evidence_snapshot.activation_evidence_ready=True` 且
Full Monitor 0 FAIL → 开启 R4（`wandering_enabled=true` 影子观察 14 天再评
R5）；若仍 ready=False → 记录中断原因并再设一个**明确的新日期**。

**顺延成因（2026-08-14 实测，不是"没到时候"而是有具体断点）**：
`activation_evidence_ready=False`，历史最长连续有效日 **6/30**
（2026-08-05→08-10），`valid_day_count=17`、`invalid_day_count=11`。
断点是 **08-11 整天无自然日行**——该日的 `v3_seed_evidence` 运行在
`2026-08-12T06:53` 落 `execution_status=error`（sannai 迁移窗口，与 CO 节
main 心跳停摆、CP 节选择压力连击重置同源）。08-12 起重新计数，因此 30 连
续日最早在 **~2026-09-11** 达成，复查日取其后一日。
注意 `consecutive_valid_day_count` 取的是**历史最长**连击而非当前连击，
故单次断档不会永久重置进度。

**V7 影子→实操毕业（逐组件 owner 决策，随时可启动）**：五个影子治理生产者
已在生产持续产出并被聚合端消费（见 CI 节），毕业按 owner 信号阶梯逐组件
推进——当前仅 `retractable_label_miner` 攒满 20 个 owner 批准达
owner_approved_apply 档。

BC 代码评审（对 `abcce26` 的 15 项发现）已全部完成：P0×3（BD）、P1×4（BE）、
P2×3（BF）、P3×5（BG）。

BJ 待办的"9 项 Windows 本地 pre-existing 测试失败诊断"已由 BK 完成：7/9 为真实代码/测试缺陷，
已修复；2/9（pytest_policy skip-count）诊断为本机环境伪影，非项目代码缺陷，不修复。

当前遗留：
1. ~~四个 helper-completion 兄弟 WARN 码的 clean-host 分类表注册~~ —— **BY 已关闭**，且实测
   比原记录更严重：未注册的 WARN 码在 clean-host 会落 `clean_host_warn_unclassified` 即 **FAIL**，
   与 `deploy_memory_os.py` 是否接入 cron onboarding 无关。五个码（含 BY 新增的
   `..._disabled_without_audit_record`）全部按 `warn_if_production` 注册，生产行为不变。
2. ~~`install_memory_os_plugin.py` 五处 `str(path.relative_to(...))` 与本次修复的
   `plan_deployment()` 同一模式，当前无触发路径，暂不改动（BK 记录）。~~ ——
   **CD 已修**（五处全改 `.as_posix()`，Windows 本机反事实实测）。
3. `shell_alias_no_env()` 的 22 条 CLI 探针命令并行执行（`ThreadPoolExecutor`）对同一
   `HERMES_HOME` 文件/SQLite 状态的一般性并发风险（BM 记录，`review_reply` 使用假 token
   探针本身已确认安全）。**BY.3 首次拿到实测复现**：BY 部署后紧接着跑的那次 Full Monitor
   出现 `shell_alias_no_env_failed`（FAIL，08-02 快照里该项为 PASS 且无 false 键），
   同一次运行还带 `full_monitor_runtime_over_target`；随即原样重跑**不复现**
   （`shell_alias_no_env_ok` 回到 PASS、false 键为空），且逐条手工复现探针条件
   （12 条 CLI 命令、不带 env 前缀）全部 rc=0。判定为**主机负载下的瞬时争用**，
   非 BY 引入的回归——但这条待办从此不再是"无实测复现"。
   **CD 部分关闭**：并发单测覆盖已由 CB 批次落地（并发归因 + 并发/串行基线
   一致性）；疑似成因（每条 CLI 探针 17–29s 的急切 torch 载入，见待办 11）
   已由 CD.3 修除。保留观察点：下一次部署后的 Full Monitor 如再现
   `shell_alias_no_env_failed` 再升级，否则视为关闭。
4. ~~owner 无法拒绝 session_mirror 导入审批~~ —— **BY 已关闭**（owner 决策：reject + defer 都做）。
5. ~~在 3.200 补写 `expression_feedback_request` 的停用审计记录~~ —— **BY.3 已写入并验证**
   （见 BY.3 节）。`reason` 字段刻意**没有编造原始停用理由**：主机上从来没有记录过它，
   现文案如实写明"owner 2026-08-02 决定保持停用 / 原始理由未知 / 本条为补记不改变运行状态"，
   owner 可随时替换该文本。
6. ~~`deploy_memory_os.py --timeout` 默认 60s < 自身 compat 门实测 63s~~ —— **BY.2 已修**。
7. ~~**`system/continuity_freshness.jsonl` 无 monitor 字段**~~ —— **CA 已关闭**。
   新增 `continuity_freshness_summary()` + `classify_snapshot` 分支 + 中文摘要行，
   **不引入新 WARN 码**（全走 `pass`/`info`），账本缺失显式判为
   `continuity_freshness_ledger_absent_healthy`。保留策略已在 BZ 登记。
8. **关键事实未入库导致召回漏项**（Owner 2026-08-04 提出，**只登记未开工**——
   「后续要仔细分析」是排序指令）。指 Memory-OS 的写入链
   `sync_turn` → candidate → owner 批准 → crystallized 漏掉了本该留存的事实。

   **开工第一步是分离两种成因，因为修法相反**：

   | | 成因 | 检验 |
   |---|---|---|
   | **A. 没入库** | 写入链丢了它 | 在 `events/` `candidates.jsonl` `crystallized/` 里 grep——**不在** |
   | **B. 入库了但没召回** | 检索/排序/权威分层漏了它 | grep——**在**，但 prefetch 不返回 |

   Owner 措辞"没存入记忆"指向 A，但"召回漏掉了"与 B 同样相容；分不清就动手，
   有一半概率修错另一半系统。若确为 A，写入链有三个独立丢弃点须分别量化：
   `sync_turn` 是 **summary-only** 的（最上游、最易漏——事实没进事件摘要，此后整条链
   都不可能有它）、candidate 未生成、候选停在候选态未获批准（→ 召回权威层级低）。

   **这一条改变了批次 F 的性质**：`recall_golden` 正是测量召回漏项的仪器，
   删除决定不再独立——见接线闭环方案 §3.3 末尾。
   **CD.8 状态更新**：仪器侧已齐（session_fact_extraction 已实现待部署、
   recall_golden 三维度已全部真实）；A/B 分离分析仍待部署后的生产数据
   与 owner 提供的具体漏失实例，不预写修复。
9. ~~**两个既有 report-only shadow 账本已登记保留策略但永远不会老化**~~ ——
   **CD.4 已修（forward-only）**：两个 writer 补 `created_at`，新记录正常老化；
   历史行仍不可老化，处置留 owner 决策（修法 B 会让两个从未剪过的生产账本
   立即整体进入归档计划）。原始记录保留备查（BZ 查出）。
   `metadata_retention._record_created_at()` 只认 `created_at`/`ts`/`timestamp`，而
   `graph_layer_shadow` 的记录写 `recorded_at`、`substrate_recall_shadow` 的记录
   **没有任何时间字段** → 两者的每条记录都被判"无时间戳" → 永久 `retained_records`。
   **本轮刻意只记录不修**：修它等于让两个从未被剪过的生产账本首次进入归档计划，
   属超出批次 C 范围的行为变更，需单独决策。修法二选一：给两个 writer 补
   `created_at`（只影响新记录，历史行仍不可老化），或让 `_record_created_at` 兼容
   `recorded_at`（立即覆盖历史行，影响更大）。
10. ~~**`recall_golden` 的 authority 维度是死代码**~~ —— **CD.6 已修**：
    matched_source_ref/matched_authority 从实际命中 section 派生、
    `source_authority_issue` 与 `context_insufficient` 均可达且经反事实实测、
    `min_score` 删除（无生产者）+ loader 容忍未知键。§3.3 三项退出条件全部真实。
    原始诊断保留备查（CA 查出）。
    `evaluate_recall` 的 `matched_source_ref` 从**期望值**抄，`matched_authority` 从不赋值，
    `authority_class`/`min_score` 从不被读，`"context_insufficient"` 无分支返回。
    后果：方案 §3.3 的退出条件「hit/miss/**authority** 报告」只满足前两项，
    **不得据现状声称该项达标**。hit/miss 经反事实实测为真。
11. ~~**`cli.py::_check_vector_available()` 急切 import `sentence_transformers`/`torch`**~~
    —— **CD.3 已修**：`find_spec` + 进程缓存，status/doctor 不再执行 torch；
    爆炸 loader 反事实钉死"从不执行"。（CA 查出。）单次 `status`/`doctor` 耗时 **17–29 秒**；而
    `shell_alias_no_env()` 并发跑 22 条 CLI 探针——**很可能是待办 3 那个生产 flake 的成因**。
    这条同时也是 `full_monitor_runtime_over_target` 的候选成因之一。
    修法方向：把 vector 可用性探测改为惰性/缓存，不在 `status`/`doctor` 路径上加载模型。
12. ~~**①会话事实抽取 lane 未实现**~~ —— **已实现（CB 节），但未部署**。
    按 `fact_judge` 模板建成新 cron lane，复用 `_call_hermes_runtime_model`；
    两个坑都已避开（持久指纹账本 + 最新优先，而非 `session_mirror` 的纯队头；
    三重有界 + 每条消息 4000 字符入参上限）。
    **剩余动作只有部署**，且有一个静默失效点必须照做：统一部署时须重新生成
    `memory-os/system/memory_os_cron_registry.json` 快照，否则
    `cron_group_runner._load_group` 会返回旧的 `tick_evidence` 成员并
    **无任何报错地跳过本 lane**（详见 CB 节"部署要求"）。
13. ~~**`session_mirror` 一般性队头偏置未修**~~ —— **CD.5 已修**：
    从未导入的会话优先（稳定排序），信号从 mirrored 事件派生、
    经删 state 重建测试证明存活；活跃会话不再以新内容版本反复霸占队头。
    （CA 实测；机制查实为 dedup_key 含 content_sha256 + 稳定发现序。）
14. ~~**monitor 只观测"跑过了"，不观测"产出了"**~~ —— **CD.2 已修**：
    exposure_rollup 快照 `last_run` 封闭原因码（monitor INFO 可见）、
    session_mirror auto-apply 每条退出落盘原因、`_call_hermes_runtime_model`
    六个调用方清查（clearance 死判官恒 clear 改 fail-closed、contradiction lane
    空回复记 `llm_empty_content`，顺链修掉后者从未被触达的模板必崩缺陷）。
    session_mirror last-run 文件的 monitor 采集接线显式不做（登记，与 BV 的
    recall_facade 接线同类）。原始诊断保留备查（CA.1 查出）。
    helper completion 只判 ExecutionGate envelope，`completion ≠ output`。三个同型实例：
    `exposure_rollup` 的两条不产出退出路径（良性跳过 / `source_cursor_not_found`
    永久错误）在产物侧证据完全相同；`session_mirror` 637 次运行 findings=0 且积压在涨；
    `_call_hermes_runtime_model` 返回 `""` 与成功不可区分（实测 27.5%）。
    修法方向：为有产出契约的 lane 增加"本次产出行数/新增记录数"信号，
    completion 与 production 分别判定；**不产出时必须落盘写明封闭原因码**，
    使读者不重跑、不读源码即可区分"无合格输入"与"处理失败"。批次 C 账本的
    状态迁移去重 + `unknown_grade_count` 正是这个模式的反面，**应推广为通例**。
    已写入 CLAUDE.md 新增小节 “Completion Is Not Output”。
15. ~~**`exposure_rollup` 跑了却不产出**~~ —— **已诊断结案，属良性空转，非缺陷**（CA.2）。
    游标实测仍在队首（`msrc_20260801T075108673109Z_4d466577`，index 987/988）⇒
    `new_records = 0` ⇒ 走 L141 `skipped=True` 良性分支，**按设计不写任何文件**。
    上游 `memory_sources.jsonl` 自 `2026-08-01T07:51:08Z` 起零增长，故 lane 无输入可处理。
    **未落入 `source_cursor_not_found` 那条永久错误路径**（该路径仍是真实风险，
    压缩一旦移除游标记录即永久静默失败，已并入待办 14 的产出可观测性要求）。
    附带纠正：本条原文（以及路线图 P1-4）都在用 lag 论证，而 monitor 中**并不存在
    lag 门控**，`exposure_rollup_lag_hours` 只计算上报、从不参与判定。
16. ~~**那个唯一 FAIL 的真实根因，以及"修了它反而更糟"的陷阱**~~ —— **CC 已修复关闭**
    （16a + 16b 一并修，词表双向守卫 + 归因纪元边界 + `healthy_no_sample` 诚实护栏；
    实测投影：69→0 缺口、170 债务、覆盖面 69→129 行，**升而非降**）。
    以下为原始诊断记录，保留备查（CA.2 §4-§6 实测）。
    **这是代码缺陷、不是数据成熟度问题——再等多久都不会自己好**（BY.1 记的分类率
    `0.6506→0.7018`，本次实测仍精确为 `0.7018`，曲线早已停住）。
    FAIL 码是 `v2_exposure_schema_era_unhealthy`，由 `schema_era_attribution_gap_count = 69`
    单独驱动（conservation 与 telemetry 均为 0，`conservation_total_passes = True`）。
    拆成两条独立缺陷，**且修复顺序有强约束**：

    **16a：prefetch 只为 `crystallized` 一个类填 `source_ids`。**
    `_build_prefetch_sections` 里 `section_source_ids` 只有**一个赋值点**
    （`prefetch.py:614`，`section_source_ids[cryst_header] = cryst_ids`），
    其余段落一律走 `_section_metadata` 的空 `{}` 分支。实测印证：
    `crystallized` 133 段**全部有 ID**，其他 12 个 content-bearing 类**一个都没有**。
    `working` 并非"有时漏"而是 **0/69 从未填过**。
    可行性已核实（否则本条无从修）：`_working_lines` **逐条遍历单个 item**，
    手上同时握着 `path.stem` 与 item，而 item 有 `id` 字段（`working.py:350`），
    且规范引用格式 `working:<stem>:<id>` **已在生产代码中使用**
    （`deep_reflection.py:639`；`working:` 前缀亦在 `v3_body_packet.py:21`
    的 `_ALLOWED_SEED_PREFIXES` 内，`low_clue_recall.py:478` 也在产出它）。
    差别只是 `_crystallized_lines` 被扩展成返回三元组带 ID，而 `_working_lines`
    的签名至今只返回 `list[str]`。
    配套还需扩 `_extract_record_ids_from_section`（只认 `crystallized:`/`candidate:`），
    否则 `working` 即使填了 ID 仍无法分类——这也是 `classified_ratio = 0.7018` 的同源解释。

    **16b：`attributable_classes` 有 4 个死名字，导致该门只覆盖 2/13 个实际类。**
    `exposure_rollup.py:509` 硬编码
    `{crystallized, working, entity_graph, indexed_recall, vector, hindsight}`，
    而 `_section_source_class`（`prefetch.py:663-684`）实际产出的是
    `indexed` / `graph_layer` / `substrate_recall` / `event` / `candidate` / …
    —— **`entity_graph`、`indexed_recall`、`vector`、`hindsight` 四个名字全项目无任何生产者**
    （已 grep 确认；`memory_sources.py:516` 的 `source_class` 直接取自上述映射）。
    实测 3.200：门统计到 **69** 个缺口，**静默跳过 1093 个**同样 content-bearing 且无 ID 的段落。
    其中至少 4 类是**明确可引用**的（`candidate` 5、`indexed` 46、`event` 115、
    `substrate_recall` 133 = 299），因为它们的前缀本就在既有 ID 约定里
    （`candidate:` 甚至已被 `_extract_record_ids_from_section` 接受）；
    余下 `foreground`/`last_session`/`identity`/`state_overlay`/`bridge`/`diagnostic`/`other`
    是否属"派生聚合视图、本就不该要求归因"**需逐类裁定**，不得一刀切。
    该集合是函数内硬编码字面量、**无任何测试引用**；而测试夹具
    （`test_memory_os_phase1_observability.py:18` 的 `_section`）把
    `source_class` 写死成 `"crystallized"`，所以 12 个类与 4 个死名字**从未被测试触达**。

    **顺序约束（本条最重要的一句）**：若只修 16a，
    `schema_era_attribution_gap_count` 归零 → `schema_era_health` 转 PASS →
    monitor 变绿，而 **1093 个真实缺口继续不可见**。
    那是**靠缩小度量范围换来的绿色**，正是路线图 L43「不为获得绿色状态而隐藏真实 FAIL」
    禁止的事。**16b 必须先于或同时于 16a 处理**，且修 16b 会让 FAIL 数字先变大——
    这是正确方向，不是回归。
    与"关键事实漏失"同源——都发生在 prefetch 披露侧，属批次 C 的邻接面。

17. ~~**`rolling_7d_attribution_gap_count` 算了但没人读**~~ —— **CC.2 已修复关闭**
    （定为 INFO 而非 WARN：schema-era 门已无时间界地 FAIL，再加 WARN 是更弱的重复告警；
    并补做纪元过滤 + 分母键，完成 31 个键的读者普查）。原始诊断保留备查：
    `exposure_monitor_stats` 计算并返回它，但**全 monitor 无任何引用**——
    既不判 PASS/WARN/FAIL，也不进 INFO，对任何读者都不存在。
    与既有的 `exposure_rollup_lag_hours` 是**同一个毛病**（CLAUDE.md 已记
    "a metric which is merely computed and reported does not close this gap"）。
    实测当前值 3（新旧判据下均为 3，近 7 天仅 5 行自然行，故本次加宽未改变它）。
    修法有两条路，需先定性质：**要么**给它一个分级（近 7 天出现归因缺口
    理应是 WARN——它是"当前是否正在退化"的唯一滚动信号，比 `all_history`
    的历史债务更有行动价值）；**要么**明确它只是 INFO 并让它进 INFO 通道。
    不可继续留在"算了不用"的状态。同类排查建议一并做：
    grep `exposure_monitor_stats` 返回字典的**每个键**，确认都有读者
    ——CC.1 已用这个方法查出两个新键无读者并当场修掉，
    但**未对既有键做全面普查**。

18. ~~**`exposure_monitor_stats` 仍有一批键"算了却无人分级、无人读"**~~ ——
    **CD.1 已修**：逐键定性（3 个新 INFO 条目 + component 定性 + 2 键删除），
    census 测试钉死键集，未来键必须先定性；census 另抓到手工审计漏掉的
    未读别名 `attribution_gap_count`（子串键名骗过逐键 grep）。
    原始清单保留备查（CC.2 普查查出）。
    扣除内部驱动 `freeze_reasons`/`schema_health` 的 4 个（`telemetry_degraded_count`、
    `initial_natural_cycle_count`、`production_observation_days`、
    `budget_pressure_streak_days`）后，真正的孤儿键：
    - **`schema_era_classified_ratio`** —— **BY.1 当作"数据成熟度"证据引用的那个
      `0.6506→0.7018` 就是它**，却从未被任何代码读取、更未分级。
      一个被反复当作论据的数字，其实从未进入任何判定。**优先处理这条。**
    - **`exposure_rollup_lag_hours`** —— CLAUDE.md 早有记载，本次确认无读者。
    - **`legacy_unmarked_rollup_count`** —— CC 节把它当作"债务分类"先例来论证
      归因纪元边界，而它自己也无生产读者：设计上成立，可见性上不合格。
      （反过来说，本次的 `legacy_unattributed_record_count` 已优于其先例。）
    - **`rolling_7d_natural_record_count`** —— 且注意它与 `rolling_7d_attribution_gap_count`
      **域已经不同**（前者自然域、后者纪元域），配对当「缺口/分母」用会算出错的比率；
      正确分母是 CC.2 新增的 `rolling_7d_attribution_era_record_count`。
    - `cumulative_selected` / `cumulative_dropped_by_rank` / `cumulative_dropped_by_budget` /
      `cumulative_eligible` / `exposure_rollup_records_total` /
      `schema_era_natural_record_count` /
      `latest_window_start` / `latest_window_end`。
    每个都需单独定性（该分级 / 该进 INFO / 该删），不宜一次性套同一处理。
    **方法提醒**：别用纯文本匹配判断"有没有读者"——CC.2 的审计工具第一版把
    **注释里的提及**算成读者，导致 `exposure_rollup_lag_hours` 被误判为"有读者"，
    而那两处命中全是新写的注释。必须过滤纯注释行。

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
  8 项反事实 revert→FAIL→restore→PASS。3035 → **3071 passed / 13 skipped / 0 failed**（+36），
  四门全过。**仅 `local_pass`，未部署 3.200**（按方案裁定等 C→D→E 整链）。
  完成前复核查出并更正自己的一处错误陈述：「全仓无 `stale_task_revision` 生产者」是错的
  （沿用方案 §4.1），`recall_arbitration.py:86` 就在产出它——但以 `"reason"` 为键
  （gap_note 读 `"code"`，结构上看不见）、语义是修订号不相等而非年龄、默认
  `mode="off"` 休眠、用途是 suppression。两者互补，且 **D 因此多一个必须显式做的选择**。
  另补记 `recall_arbitration` freshness guard 是**第三个**生产时效过滤器。
  同一轮复核按 Section W 第 5 条扫出保留策略登记缺口：新账本已登记进
  `metadata_retention`（与两个兄弟 shadow 账本同 `shadow_retention_days`），
  并把记录时间字段从 `recorded_at` 改名 `created_at`——`_record_created_at()` 只认
  `created_at`/`ts`/`timestamp`，不改名就是"登记了但永久空转"。
  **顺带查实两个兄弟账本今天就有这个缺陷**（`graph_layer_shadow` 写 `recorded_at`、
  `substrate_recall_shadow` 完全无时间字段 → 都永远不老化），刻意只记录不修
  （修它等于让两个从未被剪的生产账本首次进入归档计划），见待办第 9 项。
  最终 8 项反事实、**3071 passed / 13 skipped / 0 failed**（+36）。
- `f40a746..`（CA，本节）：Owner 报告「关键事实漏失」的实测定位 + 三项并行修复。
  **定位为三个独立成因**：`_turn_summary` 140 字硬截断（正文只落哈希）、
  `inner_drive.py:294` 无事实抽取（候选正文就是那 280 字）、
  `_should_include_candidates` 关键词门使未批准候选**与相关性无关地**不可见。
  **3.200 只读核实推翻本会话两个论断**：完整正文durable 在 `/root/.hermes/sessions/`
  （468 文件/136MB，单条最长 975,665 字）故 >140 可恢复；off-hot-path LLM 抽取因此可行
  ——教训是"跨系统边界的否定结论不能只用本仓库证据"，以及不要把热路径约束（INV-5）
  惯性延伸到 off-hot-path。**生产规模**：助手侧 **67.3%**、用户侧 **19.0%** 的轮次被截断；
  `session_mirror` **637 次运行累计 findings=0**、每会话只产约 160 字"最后一条消息预览"、
  且选择仍是**纯队头**故 1575 积压永远排不空。
  三项修复：③候选相关性下限（**不删那个刻意的权威门**，magic-word 路径行为逐字不变，
  新增 `_record_body_score >= 2` 相关性路径，阈值 2 有实测依据）；
  F `recall_golden` **裁决反转为保留并接线**（它是①唯一的度量仪器），
  **但查出其 authority 维度是死代码**，§3.3 退出条件只满足 hit/miss 两项；
  `continuity_freshness` monitor 可见性（**刻意不引入新 WARN 码**，避开 clean-host
  未注册即 FAIL 的坑）+ 并发单测（未发现竞态，但查出
  `cli.py::_check_vector_available()` 急切 import torch 致 `status` 耗时 17–29 秒，
  **很可能是待办 3 生产 flake 的成因**，已登记未修）。
  整合评审纠正了 agent 报告里说反的预算优先级方向（候选段 50 是**最先被淘汰**的，
  挤不掉已批准内容）。①设计定案：按 `fact_judge` 模板建新 cron lane、
  复用 `_call_hermes_runtime_model`（Hermes 自身模型，已有两个先例），未实现。
  3071 → **3089 passed / 13 skipped / 0 failed**（+18），四门全过；
  **仅 `local_pass`，三项均未部署 3.200**（按 Owner 裁定全部完成后统一部署）。
- `（CA.1，本节）`：按 CA 节逐条对 3.200 做**只读**核对与复盘（无部署/重启/写入）。
  **4 项与文档一致**（`deployed_head=01356df` 且 manifest 与 `/opt` 本次无漂移；
  C 未部署经三角互证；26 job = 7 enabled + 19 paused 且 tick 分钟逐字一致；
  lane 停用审计记录完整）。**Full Monitor 基线由 97/6/1 变为 102 PASS / 5 WARN / 1 FAIL**
  （本次由整合分支发起而非已部署的 `01356df`，须扣除本轮新增的 PASS 码——与 BY.1 同一口径问题）。
  **两处文档漂移**：① BY.1 记的「LLM 判断器因额度耗尽 WARN」已过期，现为 PASS，
  `fact_judge` 最近 80 次 `none:58 / llm_empty_content:22` 佐证通路可用但约 27.5% 返回空
  ——**实测验证了待办 12 必须照抄 `fact_judge` 的失败处理而非继承裸 `""`**；
  ② 路线图 P1-4 的「唯一 FAIL 正在推进」**当前不成立**——`exposure_rollup` 08-01/02/03
  每天开 envelope 但只有 08-01 产出账本行（**此条的诊断在 CA.2 被推翻，见下**）。
  由此得出本轮最重要的结论并登记为待办 14：**系统观测"跑过了"，不观测"产出了"**
  （`exposure_rollup` / `session_mirror` 637 次 0 findings / `_call_hermes_runtime_model`
  返回 `""` 三个同型实例），而批次 C 账本的迁移去重 + unknown 计数器正是其反面，应推广。
  **另如实记下本次我自己的两次误报**（「26 vs 8」、「周 lane 4 天未跑 = 漏报」），
  两次都是结论跑在证据前面——与本会话早先三次同一个毛病。
- `（CA.2，本节）`：查结待办 15，并**推翻 CA.1 自己对那个 FAIL 的诊断**（3.200 全程只读）。
  先穷举 `run_exposure_rollup_cycle` 的两条"不产出"退出路径（L141 良性跳过 /
  L128 `source_cursor_not_found` 永久失败，**两者都在开 envelope 前 return，证据侧不可区分**），
  再据此设计判别式实测：游标 `msrc_20260801T075108673109Z_4d466577` 命中 index 987/988
  ⇒ `new_records = 0` ⇒ **走良性分支，非缺陷；上游 `memory_sources.jsonl` 自 08-01T07:51Z 零增长**。
  **待办 15 结案。** 同时纠正 CA.1 与路线图共同的方法错误：**monitor 中不存在 lag 门控**
  （`grep exposure_rollup_lag` 零命中），`exposure_rollup_lag_hours` 只计算上报、从不判定，
  拿它论证 FAIL 推进与否方向对错都无意义。
  **那个唯一 FAIL 的真实根因随之定位**：码为 `v2_exposure_schema_era_unhealthy`，
  由 `schema_era_attribution_gap_count = 69` **单独驱动**（conservation / telemetry 均 0）；
  按 `source_class` 分组后 **69 个缺口 100% 在 `working`**（dropped 41 + selected 28），
  `crystallized` 133 段零缺口——prefetch 披露工作记忆时报了 `chars`/`count` 却从不填
  `source_ids`；且 `_extract_record_ids_from_section` 只认 `crystallized:`/`candidate:` 前缀，
  故 `working` 即使填了 ID 也无法分类，这正是 `classified_ratio = 0.7018` 的同源解释。
  再按顾问提示追完调用链，发现**量级远大于此**：`section_source_ids` 全函数
  **只有一个赋值点**（`prefetch.py:614`，crystallized 专属），而
  `attributable_classes`（`exposure_rollup.py:509`）里 `entity_graph`/`indexed_recall`/
  `vector`/`hindsight` **四个名字全项目无生产者**，生产者实发的是
  `indexed`/`graph_layer`/`substrate_recall`/`event`/`candidate` —— 名字对不上，门就静默失效。
  实测：**门统计 69 个缺口，静默跳过 1093 个**（其中 `candidate`/`indexed`/`event`/
  `substrate_recall` 共 299 个是明确可引用的）。该集合无测试引用，夹具还把
  `source_class` 写死成 `crystallized`，12 个类从未被测试触达。
  **由此得出关键约束并拆成待办 16a/16b：只补 `working` 的 ID 会让 FAIL 归零、monitor 变绿，
  而 1093 个真实缺口继续不可见——那是靠缩小度量范围换来的绿色**（路线图 L43 明令禁止），
  故 16b 必须先于或同时于 16a，且修 16b 会让 FAIL 数字先变大，那是正确方向。
  可行性亦已确证：`working:<stem>:<id>` 规范引用格式已在 `deep_reflection.py:639` 生产使用。
  方法教训两条：**穷举分支 → 设计判别式 → 取证 → 才下结论**；以及"被计算并上报"≠"会告警"。
  **另记我在本节自己又犯了第六次"结论跑在证据前面"**：§4 定位到 69 全在 `working` 后
  直接写成"prefetch 有 bug + 新增 `working:` 前缀"，跳过了"这份测量有几种读法"，
  而 `0/69 从未填过`本身就是要求换读法的信号。
- `（CB，本节）`：实现①会话事实抽取 lane，关闭待办 12（**仅 `local_pass`，未部署**）。
  新增 `plugins/modules/cognition/session_fact_extraction.py` + lane helper + 2 行 gate shim
  + 2 个测试文件；改 `cron_registry.py`（lane 21→22，`tick_evidence` 成员，active-closure
  覆盖 19→20，**不新增 cron job**）、`knob_overrides.py`（6 个 knob）、
  `install_memory_os_plugin.py`、`memory_os_3_200_monitor.py`。
  设计要点：**只处理 >140 字符的消息**（≤140 本就完整存活，绑定 `_turn_summary` 的 clip）、
  先脱敏再判长度、持久指纹账本 + 最新未处理优先（**刻意不照搬 `session_mirror` 的纯队头**）、
  三重有界 + 每条消息 4000 字符入参上限（生产单条消息可达 97 万字符）、
  只产出未批准候选。LLM 全程照 `fact_judge`：同一私有导入、分类失败码、fail-closed 回退，
  **绝不继承那个裸 `""`**。每次运行落盘 11 项产出计数器 + 封闭 `SKIPPED_REASON_CODES`，
  三条 skip 路径**都在 return 前写 run report** ⇒ 本 lane 是待办 14 的正面样板。
  **整合评审我改掉子 agent 的 2 个缺陷**（均补反事实并实测确认会失败）：
  ① `candidate_id` 含 mtime ⇒ 活跃会话每次追加都绕开
  `append_candidate_queue` 的去重、把同一事实反复灌入候选队列（旧实现实测 3 行 vs 应为 2 行）；
  ② `sessions_skipped_already_processed` 重复扣减 stat 失败数（旧式实测报 0 而应为 1）。
  **全量套件另抓出 3 个回归，全在子 agent 白名单之外**：新组件未登记进
  `ERROR_RECORD_EMITTING_COMPONENTS`；以及安装器 `_write_operational_helper_scripts`
  逐个列举 helper、漏登记 ⇒ onboarding 直接 `blocked`、**一个 job 都不建**（0 vs 9）。
  由此补出"新增 lane 的六处登记清单"并写入 CLAUDE.md
  （含"不需要动 `LEGACY_PER_LANE_CRON_JOBS`"的理由，已复核子 agent 该判断为对）。
  **另核实并记下一个静默失效点**：`cron_group_runner._load_group` 优先读已安装的 registry
  快照且**成员非空就不回退**，故已 onboarding 主机上新 lane 会**无任何报错地不被 tick 调用**
  ——统一部署必须重新生成快照并事后核对；子 agent 报的"会报 `unknown_registry_key`"不准确，
  实际比那更隐蔽。生产形状已实测核对（3.200 上 `session_*.json` 命中 141 个，
  `messages[0]` 含 `content`/`role`，与实现假设一致），排空速率 8 个/天 ⇒ 约 18 天。
  3089 → **3115 passed / 13 skipped / 0 failed**（+26，含 CB.1 的 3 个），四门全过，
  空白检查按推送区间干净。
- `（CB.1，本节）`：顾问复审①又抓出 3 处，第一处**会让整条 lane 失去意义**：
  **LLM 失败后仍无条件把会话指纹记为已处理 ⇒ 那些事实永久丢失**
  （`newly_processed_fingerprints.append` 在每会话循环末尾、每消息循环之外）。
  生产实测 `llm_empty_content` 占 27.5%，是常态而非边缘；而"丢事实"正是本 lane 要消除的缺陷。
  并暴露出**我派单指令本身的错误**：我让照抄 `fact_judge` 的确定性回退，
  但 fact_judge 判的是"已存在内容"的布尔，本 lane 要**生成**摘要，**没有启发式能做摘要**；
  marker 命中的 500 字符原文切片不是恢复出的事实，恰是本 lane 要消除的截断，
  且 `_DURABLE_MARKERS` 含 `"用"`（实测），模型故障期几乎每条长中文消息都会变成
  这种切片候选，还都是 resolver 可自动提升为**临时结晶**的 —— 治理问题，不只是噪声。
  **两半一起改**：失败即**延后不臆造**（删除 `_heuristic_extract_fact`）；
  指纹账本增加 `status`（`processed`/`deferred`/`abandoned`）与 `attempt`，
  仅终态抑制重跑，`MAX_EXTRACTION_ATTEMPTS=3` 后记 `abandoned`
  （终态但与成功可区分，使"放弃"看得见），并新增两个延后计数器。
  第二处：两个新账本**重复了待办 9** —— 原写 `processed_at`（`_record_created_at` 不认）
  且**根本未在 `metadata_retention` 注册** ⇒ 永久 `retained_records` + 对保留计划不可见；
  已改 `created_at` 并双双注册。第三处（流程）：空白检查须按**推送区间**做而非逐提交。
  三条反事实均实测确认会失败（`assert 0 == 1` / `assert False` / `assert None is not None`），
  且保留那条**经真实生产者取证**（断言 lane 实跑写出的行，不是手写夹具）。
  另重写 4 个原本断言"臆造行为"的测试，并删掉 `heuristic_only`（它命名的 knob 从不存在）。
  3089 → **3115 passed / 13 skipped / 0 failed**（+26），四门全过。
  **方法记账**：这 3 处我逐行读完 785 行仍全部漏掉。第一处漏因值得记——
  我问的是"这段代码做什么"，而没问"**依赖失效时**它做什么"。
  `fingerprint_outcomes` 的赋值点语法上毫不显眼，但它与失败路径的交互决定整条 lane 有无意义。
  **教训：读一个有外部依赖的循环，必须把"依赖失效"那条路径当成独立的一遍来走。**
- `（CC，本节）`：修复并关闭待办 16（16a + 16b）。Owner 裁定
  **resolver 保持自动提升、尽量减少人工介入** ⇒ ①候选的 `bridge_state` 不改。
  **16b：门的词表与生产者词表不匹配 ⇒ 静默什么都不检查。**
  硬编码的 6 个名字里**后 4 个全项目无生产者**，而生产者实发的
  `indexed`/`graph_layer`/`event`/`candidate`/`substrate_recall` 全不在表内
  ⇒ 生产实测：**统计 69 个缺口、静默跳过 1093 个段落**。改法不是补名字，
  而是**让不匹配可测**：生产者词表提升为模块级 `SECTION_SOURCE_CLASS_BY_TITLE`
  （原为函数内局部 dict，**任何测试都看不见**，这正是漂移能存在的原因），
  门侧拆为 `ATTRIBUTABLE_SOURCE_CLASSES`(6) 与
  `NON_ATTRIBUTABLE_SOURCE_CLASSES`(11，逐类写明豁免理由)，
  守卫测试**双向断言**：每个生产者类都被分类 + 契约里无死名字。只断言一个方向抓不到本缺陷。
  **16a：生产者只有一个赋值点（crystallized 专属）**，其余段落一律落空 `{}`，
  `working` 是 0/69。已为 `working`/`candidate`/`event`/`indexed`/`graph_layer`
  五类补齐 ID，并扩 `_extract_record_ids_from_section` 前缀白名单
  （原只认 `crystallized:`/`candidate:`，所以 `working` **填了也无法分类**——
  与 `classified_ratio=0.7018` 同源）。用**可选出参**而非改返回类型，
  因 `_event_lines`/`_graph_layer_shadow_lines` 被测试直接断言返回值，
  且 `seen`/`error_records` 本就是本文件既有惯例；但可选出参正是规则 4 的陷阱默认值，
  故真护栏是**结果级测试**（真实 prefetch 零缺口 + 显式断言三类确实出现以防空过），
  反事实实测：删任一 `source_ids=` 实参 ⇒ 双双失败。
  **关键设计：必须有归因纪元边界。** 门对全部自然行算缺口，
  而那 69 个有缺口的行**全是自然行**、已写入、**无法追溯补 ID** ⇒
  只修生产者永远清不掉 FAIL。故新记录带 `ATTRIBUTION_SCHEMA_VERSION`，
  门只判带标记的记录，未带标记者计入 `legacy_unattributed_record_count`
  并仍留在 `all_history_attribution_gap_count`（**分类为债务，不是抹掉**），
  与同文件 `legacy_unmarked_rollup_count` 同模式同理由。
  **该边界开了个比原缺陷更坏的口子**：部署当天无人带标记 ⇒ 缺口 0 ⇒ 报 PASS，
  那就是靠缩小度量买绿。故加诚实护栏：纪元为空时报 **`healthy_no_sample`**
  （monitor `:1389` 早已当 PASS 值收下，但字面写明"无样本"）而非 PASS，
  并追加 freeze reason `attribution_era_no_sample`，clearance 在出现真实归因流量前不解冻。
  **3.200 只读投影实测**：988 行/170 自然行/0 纪元行；
  旧 69→FAIL，新 0 缺口 + 170 债务 + `healthy_no_sample` + 冻结。
  **覆盖面是升的**：新词表套全部自然行命中 **129 行**（旧 69），
  新纳入检查的是 `event` 115、`indexed` 46、`candidate` 5 个段落；
  `substrate_recall` 的 133 个现在**明确豁免**（按契约就是 `advisory_only`
  派生投影），比原先"名字碰巧对不上所以不检查"诚实。
  **额外收获**：X.3 防火墙**扫源文本不只扫 import**，我的解释性注释里写了
  `exposure_rollup` 就被全量套件抓出。本改动无 import、无数据依赖（归因是单向），
  故**改注释、保留防火墙**——为迁就一句注释削弱架构测试是划不来的交易。
  也再次印证：新增的 10 个测试全绿也发现不了它，**只跑自己加的测试不够**。
  3115 → **3126 passed / 13 skipped / 0 failed**（+11），四门全过，
  `surface_count` 154 不变。因本机 C: 盘曾占满、后台进程被回收，
  全量套件分三段前台跑完（2086 + 1015 + 25 = 3126），三段均为最终代码状态。
- `（CC.1，本节）`：顾问复审提三点，**全是"我加宽了判据但没审计它的消费者"**。
  ① `_memory_source_has_attribution_gap` 有**三个**调用点，我只给驱动 FAIL 那个套了纪元；
  另两个（`all_history` 全量、`rolling_7d` 近 7 天）也在跑新的 6 类判据。
  已 3.200 只读补测：`all_history` **778→844**、`rolling_7d` **3→3 不变**、
  `migration_debt` 709→844、`schema_era` **69→0**。四者中**只有 schema_era 驱动 FAIL**，
  另三个均为 `info` 专用或无人引用 ⇒ **本次部署不引入任何新 WARN/FAIL**。
  但"没出事"是运气不是设计，且是事后才验证的。
  ② **新加的两个计数器算了却没人读** —— 探针整字典透传（`:5565`/`:4691`，无白名单）
  所以它们进得了快照，**但 monitor 不读**，那 170 行债务对任何读者都不存在，
  正是我刚写进 CLAUDE.md 的反模式。已让其搭既有 INFO 通道，
  并把 `legacy_unattributed_record_count > 0` 加入触发条件——
  否则债务是唯一信号时整条 INFO 不发出；反事实实测 `StopIteration`，已确认。
  ③ 三段式 `working:a:b` ID 安全：`_extract_record_ids_from_section` 无跨文件消费者，
  `exposure_rollup.py` 内无任何 `split(":")`，三个使用点全把 ID 当不透明键。
  另登记**待办 17**：`rolling_7d_attribution_gap_count` 算了没人读（与
  `exposure_rollup_lag_hours` 同病），并建议对 `exposure_monitor_stats`
  返回字典的每个键做一次"有无读者"普查——本节只查了自己新加的两个。
  **教训：加宽一个共用判据前，先 grep 全部调用点，逐个问"这数字变大会不会告警、谁在读"。**
- `（CC.2，本节）`：修复关闭待办 17，并**第一次按新流程执行**——
  写代码 → 全量套件 + 四门 → **顾问复审** → 折叠 → **才提交一次**。
  此前 CB.1/CC.1 都是"先提交、后复审"，复审抓到的每处都变成又一个补救提交
  （`f4a3ccf`→`6b34976`、`47a077a`→`c261072`），这是流程错误不是手误。
  **折叠已做**：6 个提交合为 3 个，折叠前后内容逐字节一致。
  **待办 17 定为 INFO 而非 WARN**，理由：`schema_era_attribution_gap_count`
  已对纪元内任意一条缺口记录**无时间界地 FAIL**，再加 WARN 只是更弱的重复告警；
  滚动窗口的真实价值是**诊断**（FAIL 是正在退化还是纪元内历史债务），故给读者不给分级。
  **顺带修掉我自己刚引入的语义错误**：`rolling_gap` 原先没做纪元过滤，
  若不改，生产者修好后头 7 天会因窗口内仍有旧行而报缺口，而生产者其实正确；
  已改为对 `rolling_era_records` 计数，并加 `rolling_7d_attribution_era_record_count`
  作分母——**0 缺口 / 0 记录是"近期无归因流量"，不是"近期干净"**。
  两条反事实均实测：改回 `rolling_records` ⇒ `1 == 0` 失败；去掉 INFO ⇒ `StopIteration`。
  **31 个键读者普查**（待办 17 第二半）：15 有生产读者 / 9 仅测试 / 3 仅文档 / 4 全无。
  **最重要的教训来自审计工具自己先给了错答案**：第一版把**注释里的提及**算成读者，
  于是 `exposure_rollup_lag_hours` 显示"有读者"，而那两处命中**全是我刚写的注释**
  （把它当"已知无人读"举例）。过滤纯注释行后结论翻转。
  第二个局限：排除生产者文件会漏掉**内部消费**，实测核对后
  `telemetry_degraded_count` 等 4 个并非孤儿（内部驱动 `freeze_reasons`/`schema_health`）。
  两条值得记的发现：**`schema_era_classified_ratio` 正是 BY.1 当作"数据成熟度"
  证据的 `0.6506→0.7018`，却无任何代码读取、更未分级**——一个数字可以在论证里承重、
  却不参与任何判定；**`legacy_unmarked_rollup_count`（我用来论证纪元边界正当性的先例）
  自己也无生产读者**，设计成立而可见性不合格，反过来说本次的
  `legacy_unattributed_record_count` 已优于其先例。余下孤儿键登记为**待办 18**，
  故意不在本节顺手扩大改动面。另修复我在上一轮编辑中弄坏的一处文档段落
  （item 17 插入时吞掉了"（原 4、5 两项"的段首，导致后半段被焊接到 17 末尾）。
  **新流程第一次就见效**：提交前的顾问复审当场抓到一处真缺陷——我给新 INFO 条目的
  守卫写的是 `if v2_exposure:`（存在性），但采集失败时它是
  `{"schema_era_health": "unavailable", "error_code": ...}`——**truthy**，
  于是条目照发、三个 `.get(...) or 0` 全取 0，
  **与「近期确实很干净」的输出逐字节相同**，而探针其实根本没跑成。
  这正是本会话一直在记录的那个形状（两种状态留下相同证据），
  而近邻的 migration_debt 条目用的是**值守卫**、本来就是对的，是我偏离了既有约定。
  已改为守卫「采集是否成功」；脚本外独立复验：修前 `True`、修后 `False`。
  **同一处缺陷按旧流程会变成又一个补救提交。**
  另记：`rolling_7d_attribution_gap_count` 已是纪元域而
  `rolling_7d_natural_record_count` 仍是自然域，配对当「缺口/分母」会算错，
  正确分母是新增的 `rolling_7d_attribution_era_record_count`（登记在待办 18）。
  3127 → **3130 passed / 13 skipped / 0 failed**（+3），四门全过。
- `28dbf8a..（CD，本节）`：残留待办一轮清扫，按优先级 18→14→11→9→13→10→2/3 七项
  关闭 + 一项部分关闭。18：孤儿键逐个定性（3 个新 INFO 条目 + component 定性 +
  删 2 键），census 测试钉死键集使"算了没人读"不能再无声出生，且当场抓到
  手工审计漏掉的未读别名 `attribution_gap_count`（子串键名骗过逐键 grep）。
  14：exposure_rollup 每次运行落盘 `last_run` 封闭原因码（两条字节相同的
  不产出退出从此可区分）、session_mirror auto-apply 每条退出落盘原因
  （无 scan 的路径省略 counters 而非填零）、`_call_hermes_runtime_model`
  六个调用方清查——clearance_cycle 死判官恒 `clear` 改 fail-closed
  `judge_unavailable`，contradiction lane 空回复记 `llm_empty_content`；
  **顺链抓到未登记真缺陷**：contradiction lane 的 prompt 模板大括号未转义，
  找到候选对就必崩 KeyError，该循环此前从未被任何测试触达。
  11：`_check_vector_available` 改 `find_spec`+缓存，status/doctor 不再执行
  torch（17–29s 归零，待办 3 疑似成因随之消除）。9：两个 shadow 账本
  writer 补 `created_at`（forward-only，历史行留 owner）。13：session_mirror
  改"从未导入优先"稳定排序，信号从 mirrored 事件派生、删 state 重建后仍存活，
  活跃会话不再以新内容版本反复霸占队头。10：recall_golden authority 维度
  真实现（归因从实际命中 section 派生，`source_authority_issue`/
  `context_insufficient` 均可达；`min_score` 删除 + loader 容忍未知键）。
  2：安装器五处 `.as_posix()`（Windows 本机反事实实测）。
  12 条反事实全部 revert→FAIL→restore→PASS。3130 → **3153 passed /
  13 skipped / 0 failed**（+23，逐文件对账吻合），四门全过
  （write surface 154→156 / unclassified 0）。提交后独立复审：无 Critical，
  3 Important 中 1 修（write_failed 时快照 status 不再谎报 ok）、2 推回
  （status 语义有意、monitor 接线已显式登记），拼接错位的测试归位，
  recorder 改原子写；全部 fold 回同一提交。仅 `local_pass`，未部署、未推送。

### CD.D — 统一部署 3.200 并端到端验证（2026-08-05）

PR #19 合并为 `53880cd` 后统一部署（含此前未部署的 BZ/CA/CB/CC/CD 全部批次）。

- `/opt` 由 `01356df` ff 到 `53880cd`；数据备份
  `/root/.hermes/backups/memory-os-pre-cd-20260805T065914Z.tar.gz`（49M，源 325M）。
- `deploy_memory_os.py` production-safe：preflight / apply / postcheck 全程
  `fail=[]`，manifest 绑定 `53880cd`，四探针 pass，未重启 Gateway。
  **工具坑**：Git Bash 下 `/opt/...`、`/root/.hermes` 参数被 MSYS 路径转换改写成
  `D:/Git/...` 导致首跑 preflight 假失败——须带 `MSYS_NO_PATHCONV=1`。
- **陷阱①（cron 快照）闭合并端到端证实**：apply 重新生成
  `memory_os_cron_registry.json`，`tick_evidence` 成员 5→6 含
  `session_fact_extraction`；部署后第一个 `:12` tick（07:12Z）lane 即首跑：
  **141 会话扫描 / 处理 2（per-tick 上限）/ 提取 5 事实 / 写 5 候选**，
  envelope 有效、boundary 全 false、raw_body_included=false。
  CB.1 的关键修复在生产第一跑兑现：40 次 LLM 调用 19 次 `llm_empty_content`
  （**47.5%**，比 fact_judge 的 27.5% 实测更差），2 个会话正确
  `sessions_deferred_llm_failure`、0 个被错标已处理——事实未丢失。
- 安装拷贝 sha 与 `/opt` 逐字节一致（owner_actions / exposure_rollup /
  session_mirror / recall_golden / cli 五文件抽验）；runtime 布局 fresh import：
  `EXPOSURE_ROLLUP_RUN_OUTCOMES`、`_record_auto_apply_last_run`、
  `RecallEvaluationItem.expected_authority`、`find_spec` 探测全部在线。
- **Full Monitor live：0 FAIL / 4 WARN（全部已知家族）**，159.996s < 180s 目标。
  对比 BY.3 基线（97 PASS / 6 WARN / 1 FAIL）：唯一长期 FAIL
  `v2_exposure_schema_era_unhealthy` 按 16a 纪元边界设计转为
  `healthy_no_sample` 类 PASS（170 自然行全为 pre-marker，era 集为空），
  `attribution_era_no_sample` 在 freeze_reasons、清算闸门保持冻结——
  绿色来自诚实无样本申报，不是靠缩小度量（16b 教训的正确形状）。
  `shell_alias_no_env_ok` 部署后首跑即 PASS（待办 3 观察点首个数据点，
  BY.3 时同位置曾 FAIL）。
- 生产实测 CD 各新键：`schema_era_classified_ratio 0.7018`（与 CA.2 一致，
  待新 rollup 推动）、`all_history_attribution_gap_count 844`、
  `legacy_unmarked_rollup_count 8`、`rolling_7d natural 5 / era 0`、
  `last_run_outcome "unrecorded"`（旧快照的诚实 legacy 标记，
  明日 00:05Z daily tick 后应转真实 outcome）；census 32 键、
  两个已删键确认不在。
- **陷阱②（attribution_schema）如实登记为未闭合**：近 7 天 5 条自然行
  全部无标记——prefetch 是 Gateway 进程内路径，**新生产者代码待 Gateway
  重载才生效**（沿 BT/BY 边界不擅自重启）。在那之前 `healthy_no_sample`
  即设计内状态；重载后 `rolling_7d_natural − rolling_7d_era` 归零
  即为闭合信号（CD.1 把该差值设计为部署验证信号，正为此刻）。
- 证据级别：**`deploy_pass` + `live_monitor_pass`（0 FAIL）**。
- `53880cd..（CD.D，本节）`：统一部署 3.200——preflight/apply/postcheck 全 `fail=[]`，
  manifest 绑定 `53880cd`；cron 快照重生成、`session_fact_extraction` 部署后
  第一个 tick 首跑即产出（141 扫描/2 处理/5 事实/5 候选，19 次 llm_empty_content
  全部正确 defer 不丢失）；Full Monitor **0 FAIL / 4 已知 WARN**、160s 达标，
  长期唯一 FAIL 按纪元边界设计转 `healthy_no_sample` 且清算闸门保持冻结；
  attribution_schema 端到端验证如实登记为待 Gateway 重载。
  证据级别 `deploy_pass` + `live_monitor_pass`。纯文档记录。
- `（CE，本节）`：核心开关守护三层收口——`production-safe` 预设翻转
  （它是唯一让披露记录器全黑的预设，翻转来源实锤）、升级路径自动重开
  `memory_sources.enabled`（毕业管治模式只报告不翻）、`_ensure_config_defaults`
  改直读直写根除 load→save 归一化洗键（新测试以 KeyError 当场复现该回归）、
  monitor 新增 `memory_sources_recording_disabled` + `memory_sources_disclosure_outage`
  两红线（CD.E 那四天的形状今后活不过一次 monitor）。cron 注册链核查为已有
  兜底，不改。6+1 反事实实测，四门全过。
- `（CF，本节）`：CE 部署后 monitor 抓到的生产 FAIL 根因三层修复——
  sfe 候选出生即无溯源（结晶写门在所有批准路径都会拒，事实永远无法结晶）、
  durable bypass 自动批准结构上不可能写入的候选、写失败 re-raise 让单个
  坏候选每个 due tick 重复打崩整条聚合 lane（队头卡死的聚合版）。
  修：惰性铸造 `session_fact_extracted` 溯源事件（先于候选写入）、
  `_resolver_verdict` 溯源资格门（三通道一处覆盖）、
  `_try_write_resolver_provisional` 隔离边界（error_record + owner review 改道）。
  4 反事实 revert 全红实测 + 1 语义反转测试更新。存量候选处置经实测更正：
  重抽被写时 id 去重挡死、demote 属 OwnerGate——实际以资格门改道
  owner review 收口（7 条全部 owner_eligible，lane 复活并恢复批准积压），
  终局三选一留 owner。部署后 Full Monitor 复跑 100 PASS / 0 FAIL。

### CD.E — 披露断流四天的根因、修复与归因链首次全绿（2026-08-05）

部署验证的最后一步（等待 Gateway 重载后的首条真实流量）暴露了一个**部署之外
的既有生产缺陷**：owner 08-04/08-05 明明在与 agent 对话（事件链正常），而
`memory_sources.jsonl` 停在 988 行 / `2026-08-01T07:51Z`——**披露写入断流四天**。

**根因链（备份考古 + 代码机制互证）**：

1. `config.json.bak.20260609`：`memory_sources.enabled: true`（988 行披露的来源时代）；
2. 07-14 的两个 v3 备份里已是 `false`——v3 启用操作期间被 config 重写翻掉，
   **不是 owner 明示决策**；
3. 但披露一直写到 08-01：provider 的 config 在 `initialize` 时**读一次并缓存**
   （`__init__.py:111`），6 月启动的 Gateway 老进程带着 true 的内存副本继续写；
4. **08-01 07:51 ≈ 一次 Gateway 重启**——false 生效，披露即断，且
   `_record_memory_sources` 的开关短路是**无记录静默跳过**（配置性静默，
   与 backlog 14 的缺陷性静默同形不同义——正因如此四天无人察觉）；
5. **CA.2 的误判须更正**：当时把 exposure_rollup 四天空转归因"上游安静、
   良性空转"。上游不是安静，是被关掉了。教训：判定"上游无输入是良性"之前，
   必须先核对输入端的启用开关与最近一次进程重启时间——"没有数据"与
   "数据被配置关掉"在下游产物上不可区分，正是 completion-is-not-output
   的配置变体。

**修复（owner 授权）**：备份
`config.json.bak.memory-sources-reenable-20260805T103918Z` 后经
`save_config` 归一化把 `enabled` 翻回 `true`（注意签名是
`save_config(values, hermes_home)`，首次调用参数顺序写反报
TypeError——工具坑记录）。owner 再次重启 Gateway 使缓存刷新。

**端到端闭合证据（陷阱②关闭）**：重启后 owner 首条对话即产出第 989 行披露：
`attribution_schema = memory-os.memory_sources_attribution.v1`、6 个 section
中可归因两类（event/indexed）均带 `source_ids`、派生类按 16b 词表正确豁免。
`exposure_monitor_stats` 实测：**`schema_era_health = PASS`（era 记录 1 / 缺口 0）
——该门自诞生以来第一次靠真实样本与零缺口变绿**（此前要么 FAIL 69 缺口、
要么 healthy_no_sample）；`attribution_era_no_sample` 从 freeze_reasons 消失，
剩余两项时间性冻结（observation_days 22.3/30、budget_pressure_streak 0/7）
按设计推进；legacy 债务 170 仍如实可见。

**残留观察项**：`rolling_7d_natural(6) − rolling_7d_era(1) = 5` 为断流期前旧行，
随窗口滚动应归零；`session_fact_extraction` 首跑 `llm_empty_content` 47.5%
（高于 fact_judge 的 27.5% 实测）——defer 机制正确兜住无事实丢失，
但主机模型服务质量值得关注。
- `（CD.E，本节）`：查实并修复披露断流四天——7 月 v3 配置操作把
  `memory_sources.enabled` 翻成 false，config 进程级缓存把生效推迟到 08-01
  的 Gateway 重启，CA.2 的"上游安静"实为"上游被关"；owner 授权翻回 true
  并重启后，首条对话即写出带 `attribution_schema` 的披露行，
  **`schema_era_health` 历史首次靠真实样本 PASS**（era 1 / 缺口 0）。纯配置
  修复 + 文档记录。

### CG — 深度拆解文档审计 + 十项真实缺陷修复批次（2026-08-05）

**审计**：`docs/resolver/HERMES_MEMORY_OS_DEEP_ANALYSIS.md`（基线 ae4180b）约 35 条
声明对 HEAD `9254bf1` 逐条 re-grep 复核：推翻 1 条（§6.4 信封竞态——envelope_id
仅同调用栈传递 + ScheduleCoordinator 排他锁，无第二消费者）、半真 4 条（M10 的
provenance 半句已被 `_load_events` 缓存修复；C1 步骤数 37–40；D5 实为 9 写点；
D8 实为 5/8 态 + 游离 `shadow_bundle`）、其余确认，其中 4 项比文档更严重
（D2 爆炸半径、M2 sync 抹平、D13 二次方重写、M6×M10 相乘）。更正已内联标注回文档。

**修复批次（file-disjoint，一个 PR）**：

1. **D2** `permanent_promotion.create_or_get` approved 分支 `self.store.roots`
   AttributeError——1734 行清扫 handler 只捕 `PermanentPromotionError`，typed
   error 在 raise 前先炸穿透，形成"同一记录每次清扫重复崩溃"（CF 的聚合版同形）；
   B6 吸收审计从未成功写过。修：`_write_absorption_audit` 直收 root Path。
2. **M2** entity_index 三层漂移：DDL 无 class/weight 列、`_ensure_column` 不含、
   `_index_entities` 只插 6 列——rebuild 后 `query_related_records` 静默 []，且
   **sync_from_store 每次清空重填把已治好的权重抹平回默认**（文档漏掉的路径）。
   修三处 + 查询失败改 logger.warning（不再纯静默）。守卫测试用**真实生产者**
   （rebuild_from_store）建库，另 pin 存量 6 列库的就地迁移。
3. **M6** 隔离区重复膨胀：坏行每次 `read_events` 都重复隔离 + 双审计追加，与
   prefetch 多扫相乘。修：sha256 签名去重 sidecar（封顶 500、原子写、首见才落账）。
4. **M9** `hermes send` 无超时：加 `_HERMES_SEND_TIMEOUT_SECONDS=120` + typed
   `hermes_send_timeout`（rc=124）；全库 subprocess.run 清扫确认其余站点均有
   超时，唯 `deploy_clean_host._import_probe` 补 60s + 合成 CompletedProcess。
5. **M3** 清关失效引擎：`watermark=0` 全量重放 + 事件恒无 entity_set →
   每周期 conservative_full 失效全部回执（无限重判）。修：**逐回执窗口化**
   （回执自带的 `corpus_watermark` 即水位的持久居所，无需新状态文件）+
   `_emit_corpus_change_event` 传 frontmatter，实体集经下沉到
   clearance_receipts 的共享收集器统一词表（词表漂移教训的正向应用）。
   clearance_cycle 激活前置条件就此关闭。
6. **M8** 非原子快照写清扫：contested_pairs（自称 Atomic 实非）、exposure_rollup、
   **cron_registry 快照（M1 相邻——torn write 直接打断组解析）**、cron_mirror、
   memory_projection summary、cli 验证报告，六处收敛到 jsonl_io 原子原语。
7. **speak_gate** 两处 `open("a")` → `append_jsonl_locked`。
8. **M10** prefetch 每 turn 2-3 次全量事件扫描 → 单趟读 + `events=None` 参数
   下传三个区块（默认自读，无参数陷阱）。
9. **D13** journal 查询痕迹：每查询**全文件重写**且 trace 永不清扫 → 改持锁纯
   追加 + trace 带 record_type/schema_version，retention 按 30 天窗口回收
   （含存量 `{queried_at, scope}` 遗留形状——分类而非搁置）。
10. **M7** `action_required_count` 硬编码 0 占位删除（指标出生即 triage）；
    cognitive_loop 死赋值 `signal_collection_result` 删除——但**步骤本身是
    monitor required step，两次采集职责不同**（裸=健康证据/带信封=治理写），
    不可删步骤，文档原"可删"判断已更正。
    另：recall_golden 评估预算 4000→2200 对齐生产（R10）、ragflow 桩过时自述
    更正（T3）、CLAUDE.md 心跳顺序与"每步信封"两处描述改为与代码一致（C1/C2）。

**本轮新教训（反事实回归实录）**：M3 的共享收集器把 `sqlite3.connect` 带上了
新调用路径——**connect 会把不存在的库创建成 0 字节文件**，而
`owner_actions.py:6313` 有 exists-guard 的 schema 初始化，二者叠加打破了
digest 干跑"零写盘"不变量。目标测试全绿、只有全量套件抓到
（`test_one_shot_dry_run_with_eligible_permanent_item_writes_nothing`）。
修：读意图的 sqlite 连接必须先 `Path(index_path).exists()`。
再证 W 条"永远跑全量套件"不可省。

**反事实覆盖**：12 条新测试全部完成 HEAD 红验证（cp 备份还原法，无一 vacuous）；
4 处 trace 形状断言 + 1 处 fail-closed monkeypatch 目标随实现同步更新；
10 处新写面原语在 `ALLOWED_WRITE_SURFACES` 重新分类（3 处旧形状键更替）。
四道静态门 + `git diff --check` 全绿。

**测试计数**：3163 → **3175 passed**（+12 反事实）+ 13 skipped，全量套件
10m27s 零失败。分析文档本体已按修复结果二次更新（已修项标 ✅、开放项如实
保留）并经 owner 授权 `git add -f` 纳入仓库跟踪。

### CG 部署与生产验证（2026-08-06）

- PR #25 CI 双 `verify` pass（7m22s/7m16s）后合并为 `eadef89`，远程分支已删。
- 备份 `memory-os-pre-cg-20260806T013931Z.tar.gz`（48M，excl. WAL/SHM）；
  `/opt` ff `d08dc90 → eadef89`（连带补上未部署的纯文档 PR #24），工作树干净。
- `deploy_memory_os.py` production-safe upgrade（`--timeout 300` +
  `MSYS_NO_PATHCONV=1`，两个已知坑均按 CD.D 记录预防）：preflight 30 pass /
  0 warn / 0 fail，dry-run pass，**apply=applied、postcheck=pass**（compat
  复检 30/0/0），六探针全 pass（cron_adapter / boundary_runtime / llm_judge /
  manifest write+status / projection refresh）。**未重启 Gateway**。
- 部署核验：manifest `deployed_head=eadef89`；owner_actions / index /
  clearance_receipts / store / wandering_journal 五文件 sha 与 `/opt` 逐字节
  一致（`verify-3200-deployed-commit` 规程）。
- **Full Monitor（live）：101 PASS / 5 WARN / 0 FAIL**。四条 WARN 属已知集
  （suppressed_errors、owner 停用 lane 的 completion_disabled +
  boundary_unobserved、Windows/SSH 发起的 runtime_over_target 183-186s）；
  第五条 `casual_context_needs_review`（casual 探针渲染出 Memory State
  Overlay + Conversation Carryover）经主机 monitor_artifacts 考古证实
  **08-04/08-05 每日产物中已存在**——部署前既有、数据驱动，两个区块均不在
  本批次改动面。**0 FAIL，无部署引入回归**。
- 顺带实测更正一则：生产 `prefetch_char_budget=20000`（preflight 实测），
  不是代码默认 2200——R10 的"对齐生产"严格说是"对齐代码默认"；golden 评估
  走默认路径，与主机配置无关，修复结论不变，但表述以此为准。
- 证据级别：`deploy_pass` + `live_monitor_pass`（0 FAIL）。
- `（CG 部署，本节）`：CI 过 → 合并 PR #25 → 备份 + ff + production-safe
  部署全绿 → 五文件 sha 核验 → Full Monitor 101/5/0，唯一新面孔 WARN 经
  产物考古证实部署前已存在——十项修复批次生产落地，零回归。
- `（CG，本节）`：深度拆解文档 35 条声明逐条审计（推翻 1、半真 4、4 项加重）
  并把十项真实缺陷一次修复：D2 崩溃循环、M2 三层漂移+sync 抹平、M6 隔离膨胀、
  M9/探针超时、M3 逐回执水位+实体归因（清关激活前置关闭）、M8 六处原子写、
  speak_gate 加锁、M10 单趟扫描、D13 追加化+trace 回收、M7 占位删除；
  12 反事实全部红验证，全量套件曾抓到 connect 创库回归——全量不可省的再证明。

### CH — 开放项路线图执行：M1 探测器 + 反漂移钉批 + 死代码清理 + 部署（2026-08-06）

审计遗留开放项经两设计代理 + Opus 顾问对抗复核成 PR-A/B/C 路线图后一次执行。
顾问推翻三个初稿预设（T2 补 monitor 分支会**压掉现行 WARN**=买绿、RRF 改
list 是热路径伪修复、M1 runner 侧产物有 8-runner 并写与 dev-vs-host 代际
误报——改探针主机侧零写入）。

**PR #27（M1）**：快照成员漂移探测器——探针主机侧对比部署快照 vs 已安装
注册表（同代际，本地未部署 lane 永不误报），精确镜像 `_load_group` 解析
（快照胜出仅当 ≥1 成员可解析；319 行"成员在表 spec 缺失被静默丢弃"同判
漂移；组缺失/空表/全不可解析=回退非漂移）。WARN
`cron_registry_snapshot_member_drift` 点名 lane_ids；不可判→INFO no-sample
（空门集不买 PASS）。10 测（9 HEAD 红）。

**PR #28（钉批，零行为变更）**：T1 双写入器键集守卫（经真实生产者建记录；
completion 键集严格相等实证；permit 缺口钉成
`RUNNER_OMITTED_PERMIT_KEYS={scope_hash,evidence_refs}`）；T2 seam↔adapter
全字典相等 + monitor 第三副本**钉为有意分歧**（retired→known_optional 注入
+ 适配器计数覆盖优先级）；T4 `_like_hits` 兜底（空结果与 sqlite Error 双触发）
首次覆盖 + prefetch 意图注释；R1 `RECALL_TYPE_DISPOSITION` census（hindsight
retriever 实为 probe_only——recall_probe 在用，审计"零引用"有误）；D8
MIGRATOR_STATES 补游离 `shadow_bundle` + 赋值 census（HEAD 红实证）；D5
promotion_state 只写 raw census；RRF docstring 撒谎修正（set 语义钉）；
speak_gate 调用方**按符号枚举**（v3 glob 曾让 cognitive_loop 隐身数月——
拒绝扩 glob 与 API 提升，防 attributable_classes 同病）。19 测。

**PR #29（清理，owner 签字）**：删 SchemaRegistry / CrystallizedFrontmatter
（fixtures 改产裸 dict，7 消费点更新）/ CrossProfileView / restraint.py+测试
（v24 verify 清单同步），净 −353/+51。**实施期改判**：D9
InnerDrive.run_once 从删除降级为注释诚实化——它是 system_modularization
套件的模块总线契约测试宿主（322 行专属 + 集成 trace 在用），撒谎的是
"[DEPRECATED]" 注释本身；D10 llm_enabled 恒 False 注明；D11 计划报告加
`executor_wired: false` 自述。

**PR #30（M1 跟进）**：探测器生产首跑命中 `clearance_cycle`——机制判断正确
但意图误判（**文档化延迟激活与遗忘重生成在成员表层面结构同形**）。修：
`ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS` 从 onboarding 脚本移居 cron_registry
（**运行时树只带 plugins 不带 scripts/——实测探针 sys.path 永远导不到
onboarding**，注册表是探针可达的唯一单源），探针把缺失拆成
silently_missing（WARN）与 documented_exclusions_absent（可见不评级）。
反事实精确复刻生产快照形状。

**部署（039596e）**：备份 50M（首跑撞活跃 tick 写入,
`--warning=no-file-changed` 重试并 8310 条目验证）；preflight 首跑
`shell_doctor_command_failed` 瞬时争用（直接复跑 doctor status:ok，
preflight 复跑 30/0/0——CF"瞬时 doctor"同族第三例）；apply/postcheck/
六探针全绿×2 轮。**最终 Full Monitor：102 PASS / 5 已知 WARN / 0 FAIL**，
`cron_registry_snapshot_member_parity_ok` 新 PASS 首跑即绿；
`owner_review_agenda_digest_unavailable` 上轮 WARN 复跑不复现（采集碰撞，
计第四例瞬时争用）。

**测试计数**：3175 → 3190（PR-A +10、PR-B +19、PR-C −15、PR-D +1）+ 13
skipped。工具坑一则：worktree 根的部署临时 json 被 `git add -A` 卷入提交，
amend + force-with-lease 修复——临时产物随手删，别等收尾。
- `（CH，本节）`：开放项路线图四 PR 落地——M1 快照漂移探测器（含生产首跑
  误报的注册表单源修正）、19 钉反漂移批、死代码净删 302 行（D9 经实证改判
  文档化）、全部部署 3.200 并 Full Monitor 102/5/0 收口；探测器新 PASS
  首跑即绿，瞬时争用家族添两例（doctor preflight、agenda 采集）。

### CI — 七项 owner 决策执行（2026-08-06）

owner 对 P3 清单逐项拍板后一批执行。两项前提在实施中被生产数据修正。

1. **clearance_cycle 激活**：先证 `sweep_unavailable_open_proposals_on_flag_flip`
   **零生产调用方**（onboarding 注释担心的"激活连坐回收 9 个开放提案"不可能
   发生）→ 从 `ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS` 删除，骑既有 tick_governance
   job（无独立 job）。两处钉住延迟语义的测试同步反转；parity 反事实改用
   monkeypatch 合成排除（随真实集缩减而存活）。
2. **prefetch 预算右尺寸**：生产实测最近 100 条披露 p50≈4.6k / p90≈7.9k /
   max 9,297 字符——20000 是从未起约束作用的前优化残留，且**就是
   DEFAULT_CONFIG 代码默认**（CG 的 R10"对齐生产默认 2200"对齐错了对象：
   2200 只是 config 加载彻底失败的内联兜底）。改 DEFAULT_CONFIG=12000
   （max×1.29 余量），recall_golden 直接 import 常量永不再漂；主机
   config.json 显式 20000 随部署改 12000（生效需 Gateway 重启）。
3. **hindsight retriever 留用验证**：31 专属测试绿 + recall probe
   `--type hindsight` 端到端跑通（空库正确空返回）+ 生产 substrate 路径
   monitor 常绿——可选对接启用路径健康。
4. **external_state_roots 落地**：白名单增设 `state:owner_memory_md` /
   `state:owner_user_md`（生产唯一真实状态根 `<home>/memories` 只有这两个
   文件，原白名单全是 Sannai 型 artifact——指根会镜像到零）；config 增
   `external_state_roots` 键 + provider 接线（原 CLI-only）；新增
   `state_source_mirror` 日频 lane（tick_daily 骑行，六触点齐）；反事实证
   元数据只读（文件正文任何位置不得出现）+ 空配置诚实报
   state_root_count=0。
5. **D14 前提被生产推翻**：五个影子生产者经认知循环 systemd timer 一直在
   跑（candidate_review 2264 决策、router 2264 路由全 mid 段、cascade 336
   提案、provisional 672 runs 且 would_promote_count:0 为诚实无产出），
   聚合端三处消费真实数据。原审计把"未 live-apply"误读为"未运行"——
   分析文档 D14 行已更正。真正的"开"是 V7 逐组件毕业（见待办）。
6. **V3 复查日期制**：连续 4/30 天（中断 11 次），复查日 2026-09-05 写入
   待办，含标准与"顺延必须带新日期"条款。
7. EXTERNAL_EVIDENCE 枚举按 owner 决定搁置（census 已钉 reserved）。

**测试计数**：3190 → **3192 passed**（+镜像 owner-files 反事实、+helper 空配置
诚实报告）+ 13 skipped；lane 计数钉测改为注册表推导（22 active / 8 jobs——
手写排除集正是它自己警告的漂移病，已消除）。四门全绿。
- `（CI，本节）`：七项 owner 决策一批执行——清关激活（先证 sweep 零调用方）、
  预算 20000→12000（生产实测 max 9.3k；CG 的 R10 对齐错对象一并更正）、
  hindsight 启用路径验证、external_state_roots 全链路落地（新 lane + 白名单
  两类 + config 键）、D14 前提被生产推翻（影子生产者一直在跑——审计把
  未 live-apply 误读为未运行）、V3 复查日 2026-09-05 制度化、枚举搁置。

**CI 部署与生产验证（2026-08-06，`2214f9d`）**：备份 47M + config 双备份后
apply 全绿（compat 30/0/0，六探针 pass，未重启 Gateway）；快照重生成实证
tick_governance 收进 clearance_cycle、tick_daily 收进 state_source_mirror，
parity 探测器 PASS 双确认。**镜像首跑写 2 事件**（MEMORY.md/USER.md），抽查
纯元数据零正文泄漏；空配置→诚实 state_root_count=0。**清关首周期 09:37
自然 cron 触发**，1.2s 完成信封干净：`invalidated: 0` 是 **M3 逐回执水位
修复的生产实证**（旧代码此处全量重失效），E9 收 8 条未判 provisional 全判
`unknown/candidate_unindexed`——C3 基建退避类 typed 原因（待 index_sync
收录后经失效自然重入），非 LLM 故障。主机 config：budget 12000 +
external_state_roots 已写入（**budget 对 prefetch 生效需 Gateway 重启**，
时机归 owner；镜像 lane 每跑 fresh 进程读 config 已即时生效）。
**终验 Full Monitor：102 PASS / 5 已知 WARN / 0 FAIL**；apply 窗口的
rendered+agenda digest 双 unavailable 复跑双双回 PASS——瞬时争用家族第
五、六例（apply 安装窗口采集碰撞）。

- **CH**（2026-08-06）：图谱层+Overlay+V3 前置十项单批修复 W0–W9——
  边迁移持久化地基（E7）、写入口去重+refines 收权+配对去偏置、存量压缩、
  candidate→owner_eligible 晋升通道+词表双向守卫（E1 断链闭合）、溯源边、
  幽灵 namespace agent 包驱逐（llm 死亡一个月的真根因）、knob 过期 WARN、
  Overlay live 锚点覆盖+S6 路由抑制、quiet gate fail-closed、实体碎片过滤;
  新增测试 41 条全部先红后绿，全量 3233 passed / 13 skipped。

### CJ — 图谱注入质量三题 + 顾问评审三缺陷（2026-08-07，PR #46/#47 → `9d295b0`）

owner 三问（开关默认 False / 边目标可读性 / 内容话题相关性）核查后判定
1、3 为真问题、2 半真（↺ stub 打裸 ID）。按 owner 要求上 Opus 顾问评审，
顾问确认三修法并挖出三个更深的前置缺陷，按 S1→S2→S3 依赖序单批落地。

**顾问挖出的三缺陷（全部代码核实）**：
- **F1 方向未归一（正确性）**：`query_edges` 匹配 `from OR to`，渲染无条件
  取 `to_record_id` —「X→锚点」边把锚点自己当"关联记忆"展示（几乎必然已
  被结晶段展示 → 永远 stub），depends_on 方向读反。四处同改：seen 判定、
  预览目标、seen.add、**source_ids 披露归属**（只改渲染不改归属=归属造假）。
- **F2 shadow 一份文件两种语义**：v0 在 knob 门之前落账，「查到边」=「注入
  命中」— knob 关闭期的边照样被 R4 强化、last_hit 照样刷新。
- **F3 update_edge_weight 饱和说谎**：权重已在目标值时返回真值 dict，R4 计
  reinforced — 生产首轮报的「反馈加权 32 条」全部是 no-op（全 1.0 出生下
  强化从未发生过）。

**S1 — 方向归一+中文行文法**：`- 「锚点预览12字」方向短语:邻居正文预览
(已列出·关联度 w)`；方向敏感短语表 module 级（producer 词表双向守卫）；
去重命中降级 60 字符正文短预览（=结晶段同一正文精确前缀，零歧义对齐键，
取代 ↺+裸 ID — 其它区段不显示 record_id，裸 ID 阅读方对不上号）；
`[unresolved:id]` 删除（诊断归 shadow outcome，裸 ID 只诱导编造引用）；
同 (锚点,邻居) 多边聚合一行；批量结晶解析一次扫描（替换热路径最坏 16 次
全量 glob）；事件端点经调用方 events 缓存解析（溯源边邻居可读）。行总长
最坏 220+2（`_clip` 省略号,与其他段同规）。

**S2 — shadow v1 + R4 真实口径**：写入移到渲染后，每边 injected + 封闭
outcome 八值（emitted_full/emitted_stub/below_weight_floor/target_inactive/
non_crystallized_target/unresolved/not_selected/knob_disabled），anchor_ids
入行（方向类缺陷从此可在生产数据回溯测量）；R4 只认 injected=True（缺字段
历史行按旧语义）；遗忘守卫 `shadow_exists`→`first_injection_at`（v0 守卫在
「从未展示过任何东西」的时期照样放行遗忘 — 正是它要防的屠杀；v0 state 按
schema 判别保守迁移，v1 空值是真实信号不回落）；`update_edge_weight` no-op
返回 `weight_update_noop` + 0.005 最小增量（防乘性强化在 cap 附近刷
canonical 行 — index_sync 每 30 分钟全量重投影该文件）；新计数
already_saturated（饱和命中仍刷新 last_hit,高频饱和边不得被遗忘处决）/
skipped_not_injected / invalidated_never_hit（饿死信号）/
forget_eligible_backlog（遗忘潮可见性）。

**S3 — 分层出生权重+探索位+默认翻转+监控+重归一**：
- 出生权重按**证据强度**分层（edge_weights.py,双向守卫钉死）:显式引用
  0.70/共享事件源 0.55/词面相似 0.45/仅时间邻近 0.35/溯源 0.70;llm
  `0.45+0.30×confidence`（confidence 本已采集、写入时被硬编码 1.0 丢弃 —
  复用而非重建）;vector=真实相似度。全部 <1.0 且 ≥ 注入下限 0.3
  （weight==1.0 从此可判定为未迁移遗留行）。R4 强化改乘性
  `w+=0.12×(1−w)`,cap 不可达渐近线。
- **探索位与分层同批（顾问:单发分层比现状更糟）**：全 1.0 时新边靠
  created_at 轮换还能进来;分层后排序固化,弱边永无展示→永无命中→60 天
  被判「无命中」处决（自我实现遗忘,生产密度约 110 边/结晶记录抢 8 名额）。
  候选取数 32,注入位=top-6 按权重+2 探索位按天确定性轮转（crc32,内建
  hash() 对字符串带盐不可用;无随机数热路径可复现）;落选 not_selected 落账。
- P1 默认翻 True：**resolve_knob 用调用点传入的 default,注册表仅元数据 —
  两处必须同翻**（只改注册表运行时零变化）。监控判据 expired→
  `effective≠expected`（旧判据两个方向都错:resolver 只让 state=='active'
  过期,confirmed 过期后仍生效→假警;翻转后真正危险态是一条 active 的
  override_value=False,expired 判据结构上看不见）;effective 从部署
  resolver 本体取值+一致性守卫测试（镜像重实现即词表漂移成因）。新增
  `v2_graph_injection_shadow_state` INFO（7 天 v1 行/outcome 分布,零样本
  healthy_no_sample 不买绿）。
- 重归一脚本（dry-run 默认/--apply/幂等/W0 持久/纪元报告含迁移全表）。

**部署与生产验证（2026-08-07,hermes-media,deploy_pass+live_monitor_pass）**：
apply 全绿×2;两份 provider 拷贝 grep 双确认;重归一 dry-run 计划=基线
完全吻合（1090 条:legacy 语义 811=refines 807+contradicts 4、词面 198+
共享事件 9=co_occurs 207、llm 33、溯源 39、零 unknown）→ apply 1090/1090
零失败 → 幂等复跑 0;非 invalidated 饱和边归零。直连探针实证新行文法
（「Remembered...」其证据为:...关联度 0.70,无 ID/↺/unresolved,shadow v1
injected/outcome 正确）。**R4 生产实证:被注入边 0.70→0.736（乘性）,
injected=False 边保持 0.70（F2 过滤）,knob_disabled 12 边零强化**。

**验证挖出三件事（definition of "仔细"）**：
1. **失控 disable 行**:账本存在 09:55Z 手工风格追加的
   `override_value:false` 行（id 后缀 `_disable`,ts 格式非 producer 产,
   来源不明）,把 owner 裁定的永久注入静默关了 4.5 小时 —
   **新 mismatch WARN 首个生产 run 就抓到它**（旧 expired 判据结构上看不
   见此形态）。按 owner 既定裁定经正规 register_override 恢复 True。
2. **S3.1 双层白名单剥计数**:run-once 实测 R4 四个新计数被 loop step
   包装器固定键集剥掉,监控采集端 `_edge_fields` 是第二层同病白名单 —
   两层漏任何一层,计数对读者即不存在（「计算了却无人读」的镜像:算了却
   传不出去）。修+端到端双白名单守卫（真实包装器输出喂真实采集器）。
3. **S3.2 归属纪元 v1→v2**:Full Monitor 冒出 `v2_exposure_schema_era_
   unhealthy` FAIL,定位到一条 09:51Z 的 v1 纪元内自然行（Related Memory
   已展示 596 字符而 source_ids 空 — F1 之前的 graph 归属缺口）。纪元门按
   全纪元计 gap → 永久 FAIL 且无法追溯补齐。v1「归属完备」宣称被生产证伪,
   按既有纪元边界模式升级 v2:v1 行整体降为已分类债务（all_history 保留,
   分类而非抹除）,零 v2 样本走既有 healthy_no_sample+冻结护栏;反事实
   （字面 v1 行）经 cp 回退实证无 bump 必红。测试全部符号引用常量,零漂移。

终验 Full Monitor:**102 PASS / 4 已知 WARN / 0 FAIL**（mismatch WARN 随
恢复清除,era FAIL 随 v2 清除,shell_alias 瞬时家族复跑自愈）。**Gateway
重启后新行文法才进真实对话**（时机归 owner）。预告:以
first_injection_at=2026-08-07 起算,首波大规模遗忘潮预期落点 **2026-10-06
前后** — 过密图谱(refines 为主)的预期瘦身,监控看 forget_eligible_backlog,
不是故障;invalidated_never_hit 持续走高才是探索轮转覆盖不足的真告警。

**测试计数**:3233 → **3267 passed** + 13 skipped（+34:F1 方向/聚合/预览
批量/E8c 升级/shadow v1 各分支/R4 五反事实/出生权重双向守卫/探索位轮转/
重归一三连/knob 双向/监控 mismatch+resolver 一致性+shadow 采集/双白名单
端到端/纪元 v1 债务化）。四静态门全绿,CI 三 run 全 success（push/PR 事件
触发本轮自行恢复）。

- **CJ**（2026-08-07）：图谱注入质量三题+顾问三缺陷单批落地——F1 方向归一
  +中文行文法（锚点预览+方向短语+邻居正文,已列出短预览取代 ↺ 裸 ID）、
  shadow v1 injected/outcome+R4 真实命中口径+遗忘守卫换轨、出生权重按证据
  分层+乘性强化+探索位反饿死+存量 1090 条重归一、knob 默认翻 True+监控
  effective≠expected 判据（首个生产 run 抓到失控 disable 行）、双层白名单
  剥计数修复、归属纪元 v1→v2（完备性宣称被生产证伪）;全量 3267/13,
  终验 102/4/0。

### CK — router 弱谓词二审否决图谱段（2026-08-07 深夜,Hermes agent 亲测反馈）

owner 转达 agent 真实体验:shadow 活跃(23 边/4 关系/带权重)但上下文无
Related Memory 段。agent 自诊「cry_xxx 触发 mechanism_leak 扣 0.80」——
**细节不对但结论对**:`_MECHANISM_PATTERNS` 并不匹配 cry_,旧行真正死因
是纯零分(ASCII 实体不可能与中文 query 相交、固定中文词表匹配不上)
below_threshold。且 agent 看到的是**旧渲染器**输出:gateway 23:44(CST)
才重启,其引用的 `_resolve_edge_target_preview` 在 S1 已删除。

**结构性缺陷(新行文法也逃不掉的那部分)**:图谱段相关性由锚点机制在
上游用真实查询词建立(FTS 命中一跳,含 E8b 中文回退),router 的固定词表
是更弱的谓词 — 让它重新裁决 = 「FTS 命中、词表盲区、整段否决」,锚点
机制白干。修复:`_score_section` 给 `source_class=='graph_layer'` 且非空
文本 +0.35(`graph_anchor_provenance` 独立 reason code)。不豁免三样:
风险码(-0.80 仍击杀泄漏行,0.35-0.80<0.30 反事实钉住)、路由排除
(ambiguous_recall/diagnostic 照旧)、预算排序。**刻意不含 indexed**:
casual 兜底路由下词表不匹配的 Indexed 内容不免票是被
`test_casual_continuity_report_selects_safe_carryover_without_mechanism_
working` 钉住的既有强度 — 实现首版含 indexed 被该测试当场拦下,按
「不放宽既有测试迁就新改动」裁决收窄;indexed 的同族问题(FTS 命中被
词表二审否决)是否也修,归 owner 单独裁决(待办)。

**CK 部署与生产实证(2026-08-07,`5a5e246`)**:apply 全绿,两份拷贝
grep 确认;casual 路由真实数据实证 Related Memory 入选 score 0.5、
reason_codes 含 graph_anchor_provenance;召回澄清型 query 走
ambiguous_recall 仍按设计整段排除;无锚点命中的 query 诚实无段。
Indexed 裁决所依据的历史账本数据(1030 行/303 次/词表否决 18=6%/近期
1/15)见待办存档。全量 3270 passed / 13 skipped。

- **CK**(2026-08-07):router 弱谓词二审否决图谱段 — agent 亲测反馈定位,
  graph_anchor_provenance +0.35(不豁免风险码/路由排除/预算,反事实
  钉住);indexed 按历史生产数据裁定维持现状;生产实证 casual 路由
  Related Memory 入选带溯源码;全量 3270/13。

### CL — 锚点入口:词表盲区双字词回退 + 任务锚补位（2026-08-08,agent 建议触发）

CK 上线后 owner 实测仍不命中(「连 sannai 都无法召回」),agent 给出三条
建议。逐条生产实测后三分处理:

**先反省(两条都记入教训)**:①入口词表瓶颈 E8 时已见,两次以「共享谓词
归 owner 裁决」冻结 — 对中文为主的系统这是主干道不是支线,优先级判错;
②更根本:历轮端到端验证 query 恰好都含词表词(「记忆/图谱进展」),
**验证样本自带幸存者偏差**,入口豁口在自家探针里永不显形。教训:验证
集必须包含设计边界外的输入(词表外话题、非 ASCII 实体、空锚点场景)。

**生产实测三条 query 三种死法(agent 词表理论只覆盖其一)**:
- `sannai 经常提的动态图谱` → fast_path 实体命中 5 锚点(全事件)但
  **0 边** — 且结晶限定 FTS 为 0:正文扫描发现 2 条含 sannai 的结晶
  记录**均为 active:False**(07-27 撤销),FTS 不返回是**正确行为**。
  24 条事件提及 vs 0 条活跃结晶 + 1 条当日新候选(16:36 事实抽取产出,
  队列待审)→ **图谱的空是诚实的空,洞在采集/审批层不在图谱层**。
- `动态图谱现在活起来了吗`/`注入的效果如何` → slow_path 整句 0 锚点,
  但单词直搜各 5 命中且**结晶层有货**(图谱×3/动态×1/注入×3,含当日
  新结晶)— 词表盲区是此类的真瓶颈(agent ①方向正确)。

**agent 三建议的三分处理**:
- ① 扩词表 → **采纳但换更好的实现**:不动共享词表(fast_path 路由
  谓词维持冻结),在 `_collect_anchor_ids` 回退层从 query 本身派生
  CJK 双字词组(`_cjk_query_bigrams`:停用字断窗+滑窗+cap 8,unicode61
  逐字分词下双字短语可命中)。词表从此不再是锚点入口的硬约束 — 比
  加 6 个词根治:任何新话题词都自带入口。
- ② 权重按关系类型必进/分层 → **不采纳**:0.3 下限是安全底线不是
  准入线(准入=权重排序 top6+探索位),出生权重已按证据强度分层;
  顾问此前明确否决关系类型排序(refines 占比偏斜会直接放大成注入
  偏斜)。
- ③ task anchor 补锚点 → **采纳**:query 锚点不足 5 时,从当前任务锚
  文本派生词(ASCII 实体+双字词组,≤3 词、每词双段 limit 2)补位,
  query 锚点保序在前;拿满 5 个不稀释(反事实钉住)。

**CL 部署与生产实证(2026-08-08,`b0db8bf`)**:apply 全绿,两份拷贝
grep×3 确认。三条原败例端到端起死回生 — `动态图谱现在活起来了吗`
0→5 锚点(结晶 2)→2 边→router 入选;`注入的效果如何` 0→5 锚点
(结晶 4)→20 边→入选;全新非词表话题`探索位的轮转设计` 5 锚点→
11 边→入选。**验证 query 全部刻意取自词表外**(幸存者偏差教训当轮
落实)。全量 3274 passed / 13 skipped。

- **CL**(2026-08-08):锚点入口双字词回退+任务锚补位 — agent 建议三分
  处理(①采纳换根治实现②不采纳并说明③采纳);sannai 判明为采集层
  诚实空(owner 指示搁置);三原败例生产起死回生,验证集自此必含
  设计边界外输入;全量 3274/13。

### CM — 文档对齐 + 架构定性文档(2026-08-10,docs-only)

触发:owner 与外部模型(gpt-5.6)的架构评审对话。对其全部具体结论逐条
源码核实(强化系数 0.12、6+2 探索位、出生先验分层、60 天÷每轮 50 遗忘、
出生状态、反馈桥——全部命中,无一虚构),但补两处定性修正:①图谱回路
生产上未满一整圈(强化刚进入自然积累,遗忘潮从未发生);②governance
是横穿三个数据面的控制面,不是五环之一。

**出入修复(每条均 grep 实证)**:

- CLAUDE.md:85 引用不存在的 `graph_layer.py` — 实为特性/source-class 名:
  边出生=6 个认知循环步骤,生命周期=`edge_weights`/`edge_weight_feedback`,
  注入=prefetch `_graph_layer_shadow_lines` + shadow 账本。重写为准确清单,
  含出生状态事实(structural/llm/vector/provenance 生即 active——owner
  决策 2026-08-06;矛盾 lane 生即 candidate,由 edge_promotion 积压通道
  按权重自动激活——初稿误写"过 owner 审",审核修正,见下)。
- README「Automatic growth」漏 vector proposer 与矛盾 lane 例外 — 补齐
  (四路提议信号+矛盾例外;矛盾边激活路径初稿误写 owner 批准,审核
  修正为积压自动激活,见下)。
- docs/README.md 引用五个仓库根目录状态文档(`V1_CURRENT_BASELINE.md`
  等)全部不存在于任何检出 — 死引用清除,换 architecture.md 条目。

**新增 `docs/architecture.md`(公开文档)**:Governed Living Memory
Architecture 定性 — 治理脊柱(四 Gate+证据审计)为控制面横穿
Memory/Cognition/Graph 三个数据面;六回路清单(Loop #0 观察元回路+
记忆/认知/图谱/自进化/表达)各附契约位置与生产闭环状态表(图谱
partial:出生/检索/注入/命中账本已实证,强化自然积累刚起步,首个
自然遗忘潮预期 2026-10,遗忘后再繁殖 by construction 从未运行);
三条一级原则(Execution is not Evidence / Repetition is not
Convergence / 反馈在生产改变未来行为才算闭环);LoopSpec 明确
docs-only 并给出分布式契约映射表(cron lane/ExecutionGate/last_run/
feedback bridge——禁止 runtime 注册表);Deferred by design 四项
(Edge Explanation View 只做既有账本投影、能投影的状态不许持久化、
时间性边字段推迟到有消费者、图谱里程碑只观察不干预)。
roadmap 增 §16 同步收录后续架构优化规划。

**新公开文档的三处登记联动(险些漏掉——探针对 `docs/*.md` 做集合精确
相等)**:`.gitignore` 白名单 `!docs/architecture.md`(docs/*.md 默认
ignore,漏了则 working-tree 探针经 `git ls-files --exclude-standard`
根本看不到新文件)+ `memory_os_public_checkout_probe.py::PUBLIC_DOCS`
+ 探针测试的硬编码期望清单。此外 head-source 探针测试用工作树脚本对照
HEAD 归档,故**必须一次提交后再跑全量**,否则该测试必然红——这属于
"加公开文档触多处登记"模式,同 cron lane 六处登记一族。

除上述登记外无行为代码变更;反事实测试不适用(docs-only),替代验证=
每条文档声明以 grep/源码通读证实(W 规则 2 的文档版);全量套件提交后
跑通确认基线不动。

**CM 审核修正(同日,PR #54 合并前 code-review,11 项发现)**:

初稿三条治理声明与代码相反,全部逐条源码复核后修正——教训:**"文档版
W 规则 2"必须覆盖治理声明本身,不只覆盖模块名与数字**;声明一个 gate
存在,要 grep 到那个 gate 的实施代码才算实证:

- **矛盾 lane 并无 owner 审批门**(初稿在 CLAUDE.md/README/architecture.md
  三处写"须 owner 批准才 active")。`edge_promotion.py` 文档字符串明载
  2026-08-06 owner 裁定废除逐边审核;candidate/owner_eligible 按权重自动
  激活(25/run),30 天 TTL 转 invalidated;错误边由权重反馈降权,
  `reject_edge` 仅为 owner 纠错工具。三处均改为"积压通道有界、按权重、
  非即时激活"。
- **vector 边可生而饱和**:`weight=round(sim,4)` 无上限钳制
  (edge_weights.py 自载"vector 例外")。"No edge is born saturated"
  改为明示 vector 例外。
- **edge_promotion 不是出生步骤**:从不建边,只做状态迁移。CLAUDE.md
  "六步出生"改为"五个 proposer 出生 + edge_promotion 积压激活通道"。

architecture.md 另修四处:≠ 链补 Authority≠Execution 解释句;Loop 2
生产闭环注明认知循环 runner 为 opt-in installer wrapper 非默认 cron
lane;loop-contract 表 last_run 覆盖注明是逐 lane retrofit(当前约 6/23,
是新 lane 的契约而非既有全覆盖);矛盾段落同步。

登记面收口:`.gitignore` 补 `!docs/V3_INNER_LIFE_RUNBOOK.md`(PUBLIC_DOCS
六成员中唯一无负项者,靠 tracked 豁免存活,一旦 untracked 即静默丢失);
`static_hygiene_check` 的探针调用补 `--source working-tree --strict`
(原先探针 main 非 strict 恒返 0,该子检查结构上不可能失败)+ argv
反事实断言;探针测试改 `sorted(PUBLIC_DOCS)` 消除第三份手工清单
(登记从三处降为两处)。缓解发现:常量三处复写无同步守卫 → roadmap
§16.6(触发条件驱动)。

- `b20491e..(PR#54 CM)`:文档对齐+架构定性 — `graph_layer.py` 死引用与
  docs/README 死链清除,README 图谱段补全信号清单;新增
  docs/architecture.md(治理控制面定性+六回路生产闭环状态+docs-only
  优化路线),roadmap §16;新公开文档登记联动(gitignore 白名单/
  probe PUBLIC_DOCS/测试)。审核修正:矛盾边实为积压自动激活非 owner
  审批、vector 例外、edge_promotion 非出生步骤;static_hygiene 探针
  调用补 strict。基线 3274/13 不动。

### CN — P0–P2 批次：profile 归属主线化 + reason-code 覆盖补全 + Loop Health View + 版本门 + 召回评测类别（2026-08-13，`3ca848d` → merge `2b70e57`，PR #55）

**触发**：3.200 迁入 sannai 成为 main+sannai 双 profile 主机后，owner 发现
ExecutionGate 记录 profile 归属错误（主机上自打了本地 M 补丁）；同批处理
owner 转来的五项使用发现（reason-code 覆盖、Loop 视图、召回评测、版本
失真、边界债务——最后一项 P3 按 owner 指示缓做）。

**修了什么**：
1. **P0-A profile 归属**：runner 本地 `_resolve_profile`（stdlib-only 保持）+
   `--profile` 参数，优先级 显式 > `HERMES_PROFILE` > profiles/<name> 形 home
   推导 > default；冲突 fail-closed 且**写 blocked permit**
   （`profile_home_conflict`）——主机侧建议的“不写 permit 直接退出”正是
   No Silent Failures 反模式，已纠正；runner 向 helper 子进程注入解析后的
   `HERMES_PROFILE`；`roots.resolve_profile_name` 插件侧孪生（等价守卫测试
   钉死）+ `from_hermes_home` 空 profile 时 home 形状推导；清扫约 20 个脚本
   （含 `v3_wandering` 硬编码 `profile="default"`）；agent-os `_resolve_profile`
   补推导。**根因升级**：grep 证实 profile 是 8+ 处读者的过滤键
   （feedback_bridge/scoring/deep_reflection/provider `__init__:1433`），
   写读不一致会静默丢记录，不只是审计错。legacy right_brain ×2 与 dashboard
   安装器保留宿主校准默认（注释豁免）。
2. **P0-B 版本单一真源**：pyproject 0.1.0→0.2.1（v0.2.0 Release 早已存在）；
   新增 `memory_os_version_consistency_check.py`，CI tag push 断言。
3. **P1-C reason-code 覆盖**：Explore 盘点 23 lane 实测 6 FULL/10 PARTIAL/
   7 NONE；新增 `lane_last_run.py` 标准产物（`system/lane_last_run/<id>.json`，
   封闭原因集、原子覆写、fail-open），接线 15 条 lane；最讽刺一类是“码已
   写好只 print 不落盘”（hindsight ×2、memory_sources 的 skip_reason 锁在
   cron 从不传的 `--status-json` 后）；fact_judge status 硬编码 "ok"
   （error_count>0 照样报干净）已修；full_monitor_refresh 崩溃路径 finally
   删临时文件不留痕已修；l3_probe 产物迁出 OS temp；working_cleanup 顺带
   修 `/root/.hermes` 硬编码。**护栏**：`LANE_LAST_RUN_EVIDENCE` census
   双向钉死 + 源码扫描守卫（声明 lane_last_run 的 lane 必须真调用
   `record_lane_last_run`——防词表绿），新 lane 出生即定性。
4. **P2-D Loop Health View**：`loop_health_view.py` 纯投影（八环分组、状态
   封闭集 attention/active/idle/no_evidence、新鲜度按 lane 自身
   `due_interval_minutes`）+ CLI + monitor 内嵌探针 `lane_last_run` 节 +
   `classify_snapshot` INFO-only 条目 `lane_last_run_state`（失败已由
   helper-completion 分级，此处只解释为何没产出，避免重复告警）。
5. **P2-E 召回评测仪器**：golden query 加 `category`
   （`RECOMMENDED_CASE_CATEGORIES` 14 类），报告加
   `by_category`/`by_classification`/`metrics`（wrong_memory_injection、
   authority_violation、context_insufficient）；陈旧注入/诚实无答案语义由
   类别约定承载；50 真实 case 采集流程入模块 docstring（数据被生产 gate）。

**反事实覆盖**：P0-A 三条 revert→FAIL（`''=='sannai'`、`'default'=='sannai'`、
`'ok'=='permit_blocked'`）→restore→PASS 实测；接线测试断言修复前不存在的
产物文件；注入指标用真实生产者写入晶体后负例命中验证。

**过程教训**：①改 prompt 脚本 docstring 断行撞了安装测试的整句断言
（'Hermes agent owns the owner interaction'）——grep 测试符号时 docstring
整句也算符号；②census 源码扫描测试的 `parents[2]` 层级数错一层
（tests/plugins/memory 深三层），FileNotFoundError 当场暴露；③本节最初
误编号 CM——与 PR #54 的 docs-only CM 节撞名，拉取合并后才暴露：编号
前必须先对齐 origin/main 的清单，不能只看本地工作副本。

**部署提醒**：合并部署 3.200 后覆盖主机本地 M，须 hash 核对三份副本
（source repo、/root/.hermes/plugins/memory_os、sannai runtime）；registry
snapshot 无需重生成（本批未增 lane，census 表不进 snapshot）；manifest
刷新单独处理。

**测试计数**：3274 → **3324 passed** / 13 skipped（+50）；四静态门 + closure
matrix + `git diff --check` 全绿；import cycle 0；write surface unclassified 0。

- `b20491e..3ca848d(PR#55 CN)`:P0–P2 批次 — profile 归属主线化(冲突写
  blocked permit,runner 注入解析后 HERMES_PROFILE,替换 3.200 本地 M)、
  lane_last_run 封闭原因码接线 15 lane + census 双向护栏、Loop Health View
  纯投影 + monitor INFO、版本门 0.2.1、召回评测 category/注入指标;全量
  3274→3324/13。

### CN 部署与生产验证（2026-08-14，main+sannai 双 profile）

- PR #55 CI 双 `verify` pass 后合并 `2b70e57`，随 docs 提交 `f33b0cd` 对齐；
  `/opt` ff `c9db477 → f33b0cd`，本地 M 补丁丢弃（备份
  `/root/runner.local-m.20260814T012035Z.py.bak`）。数据备份：main 66M +
  sannai 23M（`/root/memory-os-pre-cn-*.tar.gz`；sannai 首次 tar 遇
  file-changed 静默中断，重跑成功——备份必须显式核验产物存在）。
- `deploy_memory_os.py` production-safe upgrade **×2 home**：main 全绿
  （preflight/dry-run/apply/postcheck pass + 三探针 pass + manifest
  `deployed_head=f33b0cd`）；sannai 全绿 + 唯一 WARN `llm_judge_probe=
  ambiguous`（bounded_vote/gpt-5.6-luna 对低线索探针 query 裁 `ask_choice`
  ——sannai 历史浅，属合理裁决非故障）。
- hash 核验：runner ×3（/opt、main scripts、sannai scripts）、roots ×4
  （含 `/root/.hermes/plugins/memory_os` 活体副本）全一致；
  `lane_last_run.py`/`loop_health_view.py` 两 home 就位。
- **归属实测（本批核心）**：sannai 裸 env（只传 HERMES_HOME）跑
  event_stats_refresh → permit/completion 均 `profile=sannai`、lane_last_run
  落盘 `stats_refreshed`；冲突注入（HERMES_PROFILE=default + sannai home）
  → rc=2、blocked permit `profile_home_conflict`（requested=default/
  derived=sannai）；main 同 lane `profile=default` 不变；**运行时核心写入方
  同样生效**——sannai 日志里 `runtime_heartbeat_core` 01:27 前标
  default、01:38 起标 sannai（`from_hermes_home` 推导落地）。
- 布局修复一处：sannai home 有迁移遗留嵌套树 `plugins/memory/`（半份仓库
  结构拷贝，缺 agent/memory_os_agent 包），裸跑 helper 时劫持 import 根
  致崩；cron 因 wrapper 注入 PYTHONPATH 幸免。已移开为
  `plugins/memory.MIGRATION-ARTIFACT-20260814T*`（可逆）。
- 新观测面生产落地：部署后一个 tick 内 main 4 条 / sannai 5+ 条 lane 写出
  `system/lane_last_run/*.json`；`memory_os_loop_health_view.py` 两 home
  渲染正常（memory/cognition/self_evolution=active，低频环 no_evidence
  属日/周节奏未到，非故障）。
- **遗留发现（考古证实全部先于本次部署，08-12 sannai 迁入起）**：
  ① `heartbeat_state_stale`——**main 的 runtime_heartbeat_core 自
  2026-08-12T05:26 起停摆**（此前每 ~5min），仅部署期间被动跑了一次；
  sannai 心跳每 5min 连续。判定：gateway（Aug13 重启）的 Memory-OS 心跳
  被迁移接到了 sannai，main 的自动处理（候选生成/衰减/镜像 auto-apply）
  实际停转 ~2 天，**需宿主侧 gateway 接线决策**（双 profile 心跳并行或
  轮转）。② `v2_exposure_schema_era_unhealthy`——纪元门 FAIL=10 缺口，
  实测**全部**为 `graph_layer`(7)/`indexed`(3) 的 selected 段无
  source_ids，时间 08-07~08-12 = CJ/CL 图谱注入上线后首批真实入选段：
  纪元门按设计抓到了新注入路径的归因缺陷，待修（prefetch 图谱/indexed
  段 source_ids 填充）。③ `probe_script_timeout`——full monitor 探针
  300s 内跑不完（08-12 起夜间产物 257→300s，历史 183-186s），判定为
  sannai 共存负载，两次原样复跑均 300.0s 复现，非 flake 非本批回归。
- 证据级别：`deploy_pass` ×2（main+sannai）。`live_monitor_pass` **未取得**
  ——被先存 `probe_script_timeout` 挡住，产物考古（08-12/08-13 夜间同型
  FAIL）证实与本批无关；恢复 live PASS 需先解决遗留 ①③。
- `2b70e57+f33b0cd 部署（CN 部署,本节）`:双 home production-safe 全绿,
  归属三向实测通过(sannai 正标/冲突拒绝/main 不变),心跳核心写入方同步
  生效;暴露迁移期三项先存问题(main 心跳停摆/图谱注入归因缺口/监控超时)
  移交宿主与图谱工作流。

### CO — 三项迁移期遗留修复：per-profile systemd 单元 + 规范 source-id 前缀(纪元 v3) + 探针预算（2026-08-14，PR #56 → `3db959e`，双 home 已部署验证）

**owner 对 ① 的推测完全正确**：定时心跳是单例进程冲突，定时任务需要多
profile 适配。

**① main 心跳停摆(根因实抓)**：心跳由 systemd **用户级** timer 驱动
（`hermes-memory-os-heartbeat.timer` 5min → `python3 -m
plugins.memory.memory_os heartbeat`，父进程 `systemd --user`——系统级
`list-timers` 查不到,这就是首轮排查扑空的原因）。安装器写**固定名**单元
→ 多 profile 主机谁最后部署谁赢：08-12 迁移把 ExecStart 指到 sannai,
main 心跳 05:26 起死亡;CN 部署时 main apply 曾于 01:33 短暂夺回(当日
孤立心跳的成因),sannai apply 又抢走。**修复**：profiles/<name> 形 home
生成带后缀单元 + crc32 确定性 OnBootSec 错峰(周期不变);根 home 保留旧
名。install.sh 探测与 monitor 内嵌单元检查同步后缀感知。**部署实测**：
四单元并存各指其主,main 心跳恢复 3-5min 节律,`heartbeat_state_fresh`
转 PASS。
**② 图谱/索引段归因缺口**：生产者用存储层类型名拼 source_ids
(`crystallized_record:`/`crystallized_candidate:`),安全白名单与审计分类
词表只认规范前缀(`crystallized:`/`candidate:`) → ID 写入前被静默滤空
——CC 记载的"生产者与门词表漂移"第三例;CJ/CL 注入上线首批真实入选段
全部落成 v2 纪元缺口(10 行)。**修复**：`prefetch._canonical_source_id`
归一 + 词表守卫测试双向钉死(含 index 写入端 record_type 源扫描);既有
graph 测试原钉着从未过过滤器的错误格式,已改并加过滤器往返断言;
`ATTRIBUTION_SCHEMA_VERSION` v2→v3(按 v1→v2 先例,v2 行降为已分类债务,
空 v3 纪元 healthy_no_sample 不买绿)。**部署实测**：
`v2_exposure_schema_era_healthy` 转 PASS。
**③ 监控探针 300s 硬顶**：`collect_snapshot` 调 `_run_probe` 从不传
timeout → caller 声明 480/600s 也在精确 300.0s 被杀。**修复**：探针预算
= max(300, caller−30s);`full_monitor_refresh` 声明自身包络(测试伪
monitor 该参数 required——旧 wrapper 不传即失败,内建反事实)。**部署
实测**：314.6s / 301.9s 两次完整跑完,probe_script_timeout 消失,余
`runtime_over_target` WARN(诚实,主机容量项)。

**部署后新观察(非本批引入,已定性)**：①心跳复活消化两日积压 + monitor
自身 22 条 CLI 探针写 audit 的自致负载,使 `index_not_healthy(_in_
production)`/`doctor_not_ok` 在监控窗口内振荡出现——sync tick 即自愈
(lane_last_run 实录 `synced`/drift=0,audit 增速 6 分钟内从 ~百/10min
降到 +5),已平息;②`shell_alias_no_env_failed` 本轮 2/2 复现——BY.3
"无实测复现"观察点升级为"sannai 共存负载下可复现",与 runtime_over_
target 同根(容量),移交 owner 决策(nice/限流/错峰或接受 WARN)。
仲裁者=次日 02:30 夜间产物(③修复已生效)。

**V2/V3 毕业核查(owner 问"观察期够了吧")**：V2 观察期**已达标**
(31/30 天、自然周期 15/3),解冻剩两条:纪元健康(本批已修,待 v3 流量
转真 PASS)+ `budget_pressure_streak 0/7`(要连续 7 天真实预算压力,
数据驱动等不来即没有);V3 **不够**——30 连续有效日要求下最长 6 天,
08-11 自然日行缺失(迁移日 00:05 tick 未产出)断档,08-12 重算,最早
~09-11 达标;09-05 复查日按裁定应记录成因并顺延明确新日期。

**登记未修**：`memory_os_upgrade_compat_check.py` 的 cognitive_loop_timer
探测是静态固定名(informational,required=False),profile home 下显示的
是 default 单元状态——后缀感知留待下次触碰该文件时顺手(只减不增)。

**测试计数**：3324 → **3332 passed** / 13 skipped(+8);四静态门全绿;
四项反事实 revert→FAIL(词表测试 ImportError 级)→restore→PASS 实测。

- `2b70e57..3db959e(PR#56 CO)`:三项迁移遗留一次收口 — systemd 单元
  per-profile 化(main 心跳复活实测)、source-id 规范前缀归一+纪元 v3
  (era FAIL 清除)、探针预算接线(314s 完整跑通);V2 观察期达标唯剩
  压力 streak,V3 需重攒 30 日;全量 3332/13。

### CP — 多 profile 清扫收尾 + V2C 解冻门重定义(owner 裁定) + 跨面 census（2026-08-14，PR #57 → `f553204`，双 home 已部署验证）

**owner 追问**"定时任务的多 profile 适配，是不是要看全部定时任务和自动化
部署/更新脚本" → 按 Rule 5 全面清扫；同轮 owner 裁定 V2C 压力门重定义。

**① 清扫结果**。宿主全量盘点(只读)：systemd 用户级 12 单元(4 个
Memory-OS timer 已 per-profile 化、全部 enabled)、系统级仅 dashboard、
gateway 2 进程 env 正确、main cron 22 / sannai cron 19 条**零跨 profile
路径污染**、main 表内 3 条 sannai 命名任务系有意的主链协同报告(脚本均
在、无硬编码)、其余 6 个 profile 无 Memory-OS cron。修掉三处残留:
dashboard 安装器 `--service-name` **默认值**固定(装第二个 profile 会静默
覆盖第一个单元,与 CO 同类)、compat 探测固定单元名(profile home 上显示的
是 default 的状态)、l3 探针 temp 日志秒级同名(两 profile 的 evidence tick
同在 :12 分,同秒互相覆盖诊断)。
**硬编码 `/root/.hermes` 22 处逐条定性、全部良性**:5 处文档/被检测的禁用
字面量、1 处生产目标探测启发式(sannai home 为其子串故照样命中)、13 处
`--hermes-home` 可覆盖默认值、3 处 CI 挂载隔离目标。**核心运转链无硬编码
home**;监控默认 main 由 owner 裁定为当前可接受(它本就吃 `--hermes-home`)。

**② V2C 解冻门重定义(owner 裁定)**。门要求 `dropped_by_budget>0` 连续 7
天,而生产实测该计数器**从未非零过一次**(全部自然 rollup 行),同期
`dropped_by_rank` 持续累积——当前 `prefetch_char_budget` 下每段 rank 上限
总是先绑死,字节预算永远不是约束。**门在等一个该配置结构上无法产生的
信号:不是"还没到",是不可达**(与纪元边界前的归因 FAIL 同型)。
owner 裁定:判据扩为真实**选择压力**(budget 或 rank),而非调低生产预算
制造旧信号(路线图禁止为移动指标改行为)。含义确有改变(证明"稀缺下行为
正确"而非"**字节**稀缺下"),属知情取舍。实现要点:
`budget_pressure_streak_days` **退休而非改义**(键义静默变宽正是本项目
反复付代价的漂移)→ `selection_pressure_streak_days`;新增
`budget_pressure_day_count`/`rank_pressure_day_count` **保留"字节压力从未
发生"的证据**;键 census 已更新。反事实:rank-only 压力在裁定后计数、
旧代码 KeyError;零丢弃日仍打断连击(扩宽的谓词不得恒真)。
**部署前预演 = 部署后实测 = 1/7**(main;sannai 2/7),因 08-05→08-10 已有
**连续 6 天**真实排序压力,随后 sannai 迁移窗口(08-11/08-12)无自然 rollup
行重置连击——与 V3 断档同源。**可达性由历史证明,不是假设**。
附带:纪元 v3 生效后 `schema_era_health` 从 FAIL 转 `healthy_no_sample`、
`attribution_era_no_sample` 仍在 freeze_reasons 中——诚实护栏按设计工作,
未用缩小度量换绿。

**③ 跨面 census(Advisor 建议)**。`profiles/<name>` 形状推导已散在**八处**
(gate runner、roots、插件安装器、monitor 内嵌探针、compat 探测、dashboard
安装器、l3 日志 slug、agent-os),此前只有 runner↔roots 两处互钉。新增一张
行为表钉死八处(含"仅父目录为 profiles 才算"的边界),bash 那份用源码扫描
守住——防的正是本轮清扫这一类的下一次漂移。

**部署后实测**:双 home apply/postcheck 全绿;4 个 timer 全 enabled;双心跳
流动且错峰(07:02 default / 07:03 sannai);两个 profile 独立印证
`budget_days=0`。

**测试计数**:3332 → **3341 passed** / 13 skipped(+9);四静态门全绿;
三组反事实 revert→FAIL→restore→PASS。全量另有 1 个已知 flaky
(`test_execution_gate_runner_serializes_parallel_sidecar_updates`,隔离
复跑 3/3 通过,本轮未触及该路径,memory 已有登记)。

- `3db959e..f553204(PR#57 CP)`:多 profile 清扫收尾(dashboard 单元默认名/
  compat 探测/l3 日志三处残留 + 22 处硬编码路径逐条定性全良性)、V2C 压力
  门按 owner 裁定重定义为选择压力(旧键退休、证据保留、1/7 可达性经历史
  证明)、八处 home 形状推导 census 钉死;全量 3341/13。

### 通用范式：可逆闭环四要件（owner 2026-08-14 定调，前置于所有新 lane 设计）

owner 的原则一句话：**只有真正永久记忆／永久固化才需要 owner 审批**，其余
一律走自动化闭环、但底线门栏守住。这不是新规则，是把 owner 已经做过几次的
减负闭环抽象出来——以后新 lane 直接照抄，不要每次重新发明，更不要每次多问
owner 一遍。

**判据(两行决策表)**：这个动作是否写入永久层(crystallized／identity／
policy／外发)？是 → owner 门控；否 → **不得产生 owner 决策**。

**四要件**：
1. **可逆层自动通行**——够可逆(append-only／summary-only／可降级)就默认放行，
   不设逐条审批。
2. **owner 保留纠正动词**——reject/排除名单/降级，是"事后纠正"而非"事前门"。
3. **纠正必须真的生效**——纠正环缺失时不得引用先例(候选侧此前 prefetch 绕过
   终态投影、被否决的候选照样浮现，就是这条的反面教材)。
4. **越界自冻结**——任何 `actual_*` 边界为真即自动降级/冻结该 lane
   (照抄 proposal 自动路由的首次违界降级)。

**已有实例(三例，形状一致)**：
- **图谱边**(2026-08-06 owner 裁定)：废除逐边审批，proposer 直接产 active，
  错边由权重反馈降级，`reject_edge` 保留为纠正动词。
- **候选降级准入**(CQ 节)：候选以 candidate 权威直接进召回，结晶层仍 owner
  门控，owner reject 经排除快照真正生效。
- **session_mirror 平台范围**(CQ 节)：退休"逐次批准即 lane 范围"的旧语义，
  改默认导入 + owner 排除名单；纠正环(拒绝指纹永不复导)本就存在。
  **owner 2026-08-14 确认直接启用**：knob 默认 True(注册表与 resolve_knob
  调用点同时翻转,有守卫测试钉住两处不漂移),knob 退居回滚路径。

**反面教材记这一条**：owner 十次批准 session_mirror，每次批的是摘要里的一条
具体会话，系统却把那条会话的平台当成整条 lane 的范围、且只认最新一笔——
于是 08-10 批的那条恰是 subagent，lane 范围变成 `["subagent"]`，本机零匹配，
1510 条待办全跳过。**把 owner 的单条批准读成全局范围，会让 owner 越批越窄。**

### CQ — 开源上手泳道 + 候选降级准入 + session_mirror 范围退休（2026-08-14，PR #58）

三股改动一批：①开源可上手性（空白机泳道／console 入口／脚本索引／版本门）；
②**待办 8**（凭证与部署事实召回不回来）按 owner 降级准入裁定成环；
③session_mirror 平台范围语义退休。①与②③相互独立，合在一批是因为都在
"给 owner 减负、给外部使用者降门槛"这条线上。

#### 待办 8 的根因：三个真缺陷 + 一个被误当成缺陷的设计事实

owner 的原话是"我明明给了 GitHub 密匙或者交代 cloudflare 密匙或者具体部署
事实，老是记不起具体细节或者不会去召回记录然后核对现状"。3.200 实测做了
A/B 分离——**事实确实在库里**（events 与 candidates 都有），是召回侧三处独立
缺陷叠加把它们挡在外面：

1. **无纠正环**：prefetch 直接读 `candidates.jsonl` 原始行，绕过终态投影——
   owner 否决过的候选照样浮现。这正是"可逆闭环四要件"第 3 条的反面：
   **纠正动词存在，但纠正不生效，就不配引用降级准入先例**。
2. **队首偏置**：旧实现 `[:5]` 只对**队首五行**打分。生产队列 258 行，一条
   完全相关但到得晚的候选**永远不可达**——与 session_mirror 那条
   "stuck head starves the tail" 同形。改为全量打分后按分排序取前 5
   （`sorted` 稳定，同分保持队列序）。
3. **同义词不匹配**：owner 说"密钥"、记录里写"秘钥／凭证／token／api key"，
   分词后零交集。新增 `_expand_query_tokens` 覆盖六组
   （密钥类／部署类／主机类／账号类／配置类／域名类）。

**第四项不是缺陷，是设计事实**：事件是 `summary_only` 的，密钥**值从未入库**
（这是对的，不该改）。所以召回能给的只有 `safe_ref` 指针 + 摘要。为此
`_event_lines` 对命中生存状态话题的行追加
`[以现状为准:此为当时摘要,使用前请核对当前状态; 原始会话 <session_id>]`——
把 owner 那句"**以现状为准**"写进召回文本本身，而不是指望模型自己想起来核对。

#### 降级准入的两半：准入放开，纠正必须真的咬得住

owner 裁定走**更激进的降级准入**：候选以 candidate 权威直接进召回（行首明写
`candidate only / review candidate; not approved crystallized memory:`），
结晶层仍 owner 门控。相应地 reject 必须真的生效，否则就是四要件第 3 条的
反面教材。实现：`candidate_aggregation` 在 lane 末尾发布
`candidate_recall_exclusion` 排除快照，prefetch 每轮读它（**缺失时 fail-open**
退回裁定前行为，即照出未过滤队列行，而不是把候选召回整个静音）。

**纠正延迟**：排除快照与 `compact_candidate_queue` 由**同一条** lane 发布
（`candidate_aggregation`，`due_interval_minutes=360`），所以权威路径的上界是
**≤6h**；owner 的 reject 另走即时增量写，**当场生效**（见下节，这一条是复审
时才补实的）。

#### 复审补修：两个"纠正动词其实没咬住"的洞（本 PR 自身缺陷）

合并前追链发现，我在 PR 描述里写的"owner reject 即时写入不等 tick"**是假的**。
两个洞，第二个更糟：

1. **`add_candidate_recall_exclusion` 是死代码**。函数写好了、docstring 明标
   "immediate (owner reject path)"、**零调用点**。单条 reject 之所以还能生效，
   靠的是 `read_effective_candidates` 内部对 `owner_actions.jsonl` 的第二次
   独立读取（`reject_candidate` → `owner_closed` → terminal），即 ≤6h 的权威
   路径。**能用，但不是我声称的即时。**
2. **`reject_candidate_cluster` 根本到不了排除集——不是延迟，是永远不生效**。
   簇拒绝只写**一条** owner action：`target_type` 是 `candidate_cluster`（不是
   `candidate`），成员 id 在 `result_ref.member_candidate_ids` 里，而
   `_TERMINAL_CANDIDATE_ACTIONS` 只有三个单条动词。所以即时路径和权威路径
   **两条都结构性地看不见它**。反事实实测坐实：修复前
   `read_effective_candidates` 的 terminal 集合对簇拒绝是**空集**。

**为什么必须现在修**：降级准入之前候选只在魔法词下浮现，这个洞基本不可见；
**是我这次改动把它变成了会咬人的洞**。而且面对 258 条队列，owner 最可能伸手
去按的恰恰是**批量拒绝**——最省力的那个动词，正好是唯一不生效的那个。

**三处修复**：①`read_effective_candidates` 增加簇动词一跳（从 `result_ref`
取成员 id）；②`reject_candidate` 调 `_exclude_from_recall_now` 即时写；
③`reject_candidate_cluster` 对全部成员即时写。

**权威跳必须先有，不是锦上添花**：lane 每次发布的是**完整集合**，凡权威推不
出来的 id 都会在下一轮被覆盖抹掉。只做②③而不做①的话，owner 的簇拒绝会
**先生效、然后在 ≤6h 后悄悄失效**——比"一开始就没生效"更坏，因为它会先骗过
验证。第三个反事实测试专门钉这一条。

**即时写是 fail-open 的**：`_exclude_from_recall_now` 吞异常并记 error_record，
因为 owner 的决定绝不能因为一个派生投影文件写不进去而失败；丢了增量只是退回
≤6h 权威路径，是延迟损失不是正确性损失。

**生产实测影响为 0**：双 profile 的 `owner_actions.jsonl` 里至今**没有任何一条
簇动作**，所以这是潜伏洞不是正在发生的故障——按上次 `_TERMINAL_STATES` 的教训，
先量再说，不夸大。

**相关性下限用实测定的，不是拍的**：`RELEVANCE_FLOOR_MIN_SCORE = 2`。
`_extract_query_tokens` 的 CJK 侧发的是重叠 bigram 且无停用词表，单个共享
bigram 常是纯语法噪声——实测查询「我们什么时候开会？」仅靠共享的「什么」
就对一条无关候选打到 1 分；真正的话题重叠可靠地 ≥2（共享「日本旅行」打 4）。
同理没有改用 `_tokenize_for_floor_match`：它在标点边界发单字符 token
（"what's" → "s"），对**硬**门是灾难——实测「What's the weather forecast for
tomorrow?」靠一个游离的 "s" 就能匹配。

#### 顾问完整复审：一项阻塞 + 两项须处置，全部以证据关闭

owner 要求"CI 通过后调用顾问对全部改动做完整审查，审查通过才可合并"。

- **阻塞项：新准入平台（telegram＝私人对话）的脱敏覆盖**。查证结论是
  **不成立**——`test_session_mirror_apply_is_bounded_by_platform_and_redacts_secrets`
  真的把 `api_key=sk-sessionmirror-UNIQUE-…` 喂进完整 apply 路径，再把**写出
  的事件**读回来断言 `"sk-sessionmirror-UNIQUE" not in serialized` 且
  `"[REDACTED]" in serialized`——是对产物的**缺席断言**，不是对
  `secret_redaction_applied` 标志位的自证。
  但顾问这一问本身指出了我的一个思维错误，记下来：
  **我把"可逆"当成了风险上限，而信息流风险不是可逆性问题**——事件写进去了，
  脱敏漏了就是漏了，append-only 不能把泄露还原回去。四要件适用于**决策**
  可逆性，不适用于**信息流**。
- **范围哈希跨部署边界**：无暴露面。签发点（`session_mirror.py:312`）与
  校验点（`:1234`）读的是**同一个 policy 字典**，同一次
  `auto_apply_graduated_session_mirror` 调用内完成，同进程同代码版本；permit
  `require_fresh=True, require_unused=True` 单次使用。不存在"旧代码签发、新
  代码校验"的在途信封；进程中途被杀只会让 permit 过期未消费。
- **`_candidate_lines` 热路径成本**：实测见下。不能只对别处要求测量而对自己
  的改动免测。

#### 热路径实测（生产形状，真产出器造夹具）

258 行队列（生产 main 实际深度，用 `append_candidate_queue` 真产出器构造）：

| 查询形状 | 中位 | p95 |
|---|---|---|
| 魔法词（旧代码也读队列，成本未变） | 5.4ms | 8.6ms |
| 中文话题查询（**新增成本**） | 6.1ms | 12.0ms |
| 英文话题查询（新增成本） | 5.1ms | 10.8ms |
| 无可用 token（须短路） | 0.007ms | 0.011ms |

其中 `read_candidate_queue` 约 3ms、排除快照读 0.06ms。**基线要说清**：旧实现
对非魔法词查询**直接返回、一次文件都不读**，所以这 6ms 是真新增，不是搬运。
无 token 时在读盘前短路，未退化。Windows 开发机数据，Linux 生产更快。

**队列不是无界的**（这一条查证后才敢写）：`candidate_aggregation` 每 ≤6h 跑
`compact_candidate_queue`，7 天保留窗 + demoted/fleeting/absorbed **立即归档**，
所以深度稳定在"7 天流量 + owner 待审积压"。生产实测 258 行中仅 **29 行**早于
7 天窗——258 已接近稳态，不是增长曲线的早期点。**唯一无界维度是
`owner_eligible` 行**（按设计不论多老都保留），成本随该积压线性增长
（1000 行实测 17ms）。**要盯的是积压，不是队列本身**。

#### session_mirror：范围退休 + 容量算术

退休"逐次批准即 lane 范围、且只认最新一笔"的旧语义，改为默认导入 +
owner 排除名单（`platform_denylist`，config 严格白名单里注册过才不会被静默
丢弃——这一条踩过）。knob `session_mirror_admit_all_platforms` 经 owner
2026-08-14 确认**直接默认 True**；注册表元数据默认与 `resolve_knob` 调用点
活默认**必须同时翻转**，有守卫测试钉住两处不漂移（注册表的 `default` 只是
元数据，真正生效的是调用点传的值——这是本项目已知的陷阱形状）。

**容量算术（owner 该知道明天的量）**：1510 条积压一次性变为合格，但速率上限
是 `min(配置, 批准)` = **每轮 1 条**，心跳约 5 分钟一轮 → **约 288 条/天**，
积压约 **5 天**排空。不是洪峰，是稳定细流；但事件摄入会有一个 288/天的台阶。

#### 一处已登记的潜在分歧（本轮不改，实测影响为 0）

`candidate_aggregation._TERMINAL_STATES` 只有 3 个状态，权威表
`TERMINAL_CANDIDATE_STATES` 有 10 个——是本项目"词表漂移"形状的又一份拷贝。
**但生产实测受影响行数为 0**，且它与 `compact_candidate_queue` 的归档规则
（同样是那 3 个终态立即归档）是一致的，不是笔误。故登记为潜在分歧而非缺陷，
不在本轮扩大改动面。我此前一度把它说成"被否决的候选会被推回给你"——
**那是我说过头了，实测把它纠正掉了**，记在此处以免下次又凭形状下结论。

#### 测试与门

**3365 passed** / 13 skipped，本轮新增 **23 个测试函数**（候选降级准入 9、
开源上手契约 6、session_mirror 4、复审补修的纠正环 4）。四静态门全绿。

**门在这一轮抓了我三次，三次都是真失败**，记下来是因为它们证明这些门不是
装饰：①`write_surface_check` `unclassified_count 0→1`——排除快照写面未登记；
②同一个门第二次 `0→1`——`_exclude_from_recall_now` 的 error_record 追加是**新
写面**，我加完修复没登记；③`ERROR_RECORD_EMITTING_COMPONENTS` 守卫测试——新
增的 error_record 发射组件未在 monitor 侧分类（CLAUDE.md"加 lane 要动六处"
里的第⑤处，这次是加纠正环也踩到）。**第②③两次都是定向测试全绿、全量套件
才抓到的**，再次印证"只跑自己改的测试"不够。

三处纠正环修复各有反事实：还原到修复前，
`test_owner_reject_stops_recall_immediately_without_waiting_for_the_lane`、
`test_cluster_reject_stops_recall_for_every_member_immediately`、
`test_cluster_reject_survives_the_lane_full_republish` 全部 FAIL（其中簇拒绝
那两条的 terminal 集合是**空集**，坐实"结构性看不见"而非"延迟"），恢复后
全部 PASS。另加一条 `test_dry_run_reject_previews_without_touching_recall`
钉住 `apply=False` 预览不得改召回。

- `f553204..(PR#58 CQ)`：开源上手三件套（空白机泳道／`memory-os` console
  入口／95 脚本八组索引）、待办 8 三缺陷成环（纠正环＋按分排序＋同义词，
  外加"以现状为准"现状核对标记）、session_mirror 范围语义退休并按 owner
  确认直接启用；顾问完整复审三项以证据关闭；热路径实测 6.1ms/12.0ms p95
  并证明队列有界；**合并前追链又补修 owner reject 的两个空转洞**（死代码的
  即时路径 + 簇拒绝永不生效），全量 3365/13。

### CQ 部署与生产验证（2026-08-14，main+sannai 双 profile，`a7515c1`）

- `/opt/Hermes-Memory-OS` ff `bb99fac → a7515c1`；`deploy_memory_os.py`
  production-safe upgrade ×2 home：main **全绿**（preflight/dry-run/apply/
  postcheck + 三探针全 pass，`warn=[] fail=[]`）；sannai 全绿 + 唯一
  `llm_judge_probe=ambiguous`——**与 CN 节记录的是同一条已知 WARN**（sannai
  历史浅，低线索探针裁 `ask_choice` 属合理裁决），非本批回归。
- manifest 双 home `deployed_head=a7515c1`，`profile_id` 分别 `default`/
  `sannai`（归属仍正确）。三文件 ×3 副本（/opt + 两个 home 活体
  `plugins/memory_os`）**9 个 md5 全一致**——代码确实是活的，不是只更新了
  checkout。
- 未再做全量数据备份：当日上午 CN 部署的 main 66M + sannai 23M 尚在，且本批
  **不写任何 canonical 数据**（只新增一个派生投影文件 + 读路径逻辑，无迁移）。
  避免同日堆第三份 143M 备份。

#### 部署后验证抓到一个真缺陷：标记挂在了不应答查询的那一半

**生产实测（main）**：候选召回本身成立——`GitHub 部署密钥放在哪里` /
`cloudflare 的凭证是怎么配置的` 两条查询各浮现 **5 条候选行**，同义词组
按设计工作（密钥→凭证/秘钥/token/key/credential，配置→config/settings）。
队列已由 258 降到 148/150 行，**compact 按 7 天保留窗正常工作**，与"258 已
接近稳态"的判断一致。排除快照文件尚不存在（lane 未到点），fail-open 生效、
excluded=0，正是设计的降级行为。

**但 `以现状为准` 标记渲染数为 0。** 追下去：`_live_state_marker` 本身没
问题（最近 400 条事件里命中 41 条），问题是它**只挂在 event 行**，而
event 选择是**近期/会话范围，不是查询范围**。于是 owner 问"GitHub 密钥"
时，真正应答的候选行与 indexed 行**一条标记都没有**——**指令被满足在不
应答查询的那条路径上，缺席在应答查询的那条上**。

**修复**：抽出 `_live_state_marker_for(text, session_id)` 共享核；候选行
的指针取 `provenance.session_id`（生产实测 150 行中 **131 行**有该字段，
其余降级为"只给指令不给指针"而非丢标记）；indexed 行只给指令半段——那里
没有可解析的会话指针，为一条披露提示去做第二次查表就是把 I/O 放上每轮
热路径，而字符串判断本身零 I/O。标记范围不变（仍只对漂移易感话题词生效，
不装饰普通召回）。全量 **3368 passed**/13（+3，其中 2 条反事实
revert→FAIL→restore→PASS）。

#### 方法记账：同一轮里两次"探针参数错误差点导致假结论"

① 首次生产 prefetch 探针 `budget_chars=2200`，输出里候选段整段消失——
**真实配置是 `prefetch_char_budget=12000`**，2200 下候选段是被预算/排序
挤掉的，不是没产出；按 12000 复跑即 5 条。② 验证标记时用
`safe_ref.session_id` 当 `session_id` 传给 `build_prefetch`，但事件选择匹配
的是**事件自身**的会话（镜像事件的 safe_ref 指向的是**原始**会话，两者不
是一个东西），于是又得到一个假零。

**教训**：本会话此前已因"prefetch 探针漏传 index 参数"得到过一次假零
（当时也是查证后才没报成缺陷）。**探针参数写错的失败模式，长得和真缺陷
一模一样**——都是"该有的东西没出现"。所以生产探针出现负结果时，先证明
探针本身能在已知正例上出正结果，再谈缺陷。这一条已第三次触发，按同一形状
记死。

#### 已知未完成（不在本批，属架构问题）

标记里写的"原始会话 `<id>`"**目前没有任何东西能打开它**——指针指向一个
不可达的地方，是半个功能。owner 2026-08-14 澄清了完整意图：**分层深入**
——注入层只放紧凑摘要以减少无谓占用，需要细节时顺指针**回调原始历史对话**
读完再与现实核对、**以现实为准**。这需要一个"按 session_id 取回话history"
的可调用面，其归属（编排层注入／provider 方法／CLI／Hermes 侧工具）是待定
的架构决定，另议。

### CR — 注入诚实化 + 分层深入闭环（2026-08-14，PR #60）

owner 实测反馈定性："Hermes agent 看到高度匹配的摘要的部分不完整以为就是
事实，而且不会召回看具体的会话内容去比对现状"。双 profile 真实注入审计
（真实预算 12000/20000、带 index）逐字证实，并多出一层：

- **碎片看起来像完整事实**：最相关行恰好切在承重点——URL 切一半
  （`https://github.c...`）、路径切在要害（`scripts/.en...`，真实是
  `.env`）、时刻表切在最后一个数字（`09:00、13:00、17:00、21.`）。裸 `...`
  无法区分"事实到此为止"和"事实在此被截断"。
- **40%（main）/51%（sannai）预算烧在零相关 floor 填充上**：floor 模式
  20 条上限 + score-0 照收 + 同一事实重复注入 9 遍。
- **全文 0 个以现状为准标记**：#58 只盖 event 行，而 event 段全是治理噪音；
  #59 补的候选/indexed 标记当时未部署。

#### 层1：注入诚实化（纯 prefetch）

- **floor 模式重定义**：score-0 直接排除（floor 自己的注释早就写着
  "query-aware fallback, not a universal recall"）、上限 20→5、合并两类按
  分排序（相关性是 floor 唯一准入标准，permanent/provisional 保留位不适用）、
  **允许空段**——空比 4000 字零相关垃圾好。FTS 命中模式的 20/15/5 上限
  不变（有守卫测试钉住不外溢）。
- **注入去重**：规范化正文前 120 字为键，同文只注一次。
- **诚实截断** `_clip_annotated`：被切的行结尾 `…[片段N/M字]`——agent 一眼
  知道这是碎片、外面还有多少。零 I/O。
- **应答查询的段放宽**：候选 180→320、indexed 220→320、event 220→320
  （event 存储侧本来只有 ~296 字上限，二次裁剪是纯损失）。预算头寸来自
  floor 砍掉的 ~3000 字。

#### 层2：分层深入的读半边 `memory_os_session_recall`

第 4 个 provider 工具（接缝现成，零宿主管道）。四条治理性质各有测试：

- **读边界强制脱敏**：state.db 正文是 session_mirror 写事件前脱敏对象的
  未脱敏源头；返回原文=在读取时刻绕过边界，且是提示注入可利用的外泄面
  （"去核实会话 X"→凭证进上下文）。以现状为准让脱敏零成本：agent 需要的
  是对话语境，值必须拿现实核对。反事实测试把真密钥喂进 state.db 断言输出
  缺席。
- **有界**：max 40 条/600 字/条/12000 字总量 + offset/has_more 分页；
  超额请求被钳制而非满足。
- **落台账 + fail-open**：`system/session_transcript_reads.jsonl`（
  report_only 写面已注册；**metadata_retention 已登记**——顾问抓的，
  continuity_freshness 的注释原话就是"unregistered ledger grows without
  bound"，且有 ages-out 测试用真产出器行钉住 created_at 字段名）。
- **读不设 owner 门**：按两行决策表，读不写永久层 → 不得产生 owner 决策。

**三方互认闭环**：标记文本写明动词（`原始会话 <id> 可用
memory_os_session_recall 调取`）；system_prompt_block 新增 Layered Recall
Rule 教协议（`[片段N/M字]`=截断、高匹配≠完整、取回后以现实为准）；工具
description 教边界（历史快照、必须核对现状、普通聊天勿用）。

#### 顾问预检抓到的三项（合并前处置）

1. **gateway 常驻进程 vs 磁盘代码**（阻塞"部署验证通过"的说法）：
   `oneshot.py` 在 gateway 进程内 `from run_agent import AIAgent`，provider
   模块随首会话导入后被模块缓存持有。生产 gateway 今日 15:13 重启、早于
   19:09 的 a7515c1 部署——**交互路径（prefetch/工具/系统提示）吃到新代码
   需要 gateway 重启**；systemd 心跳/cron 是新进程不受影响。历史印证：
   memory 里 V2-0.5 "code green, host-side reply-tool/hook gap" 同型。
   部署后如实报告"重启后生效"，不得声称"部署验证通过"。
2. **脱敏从设计声明升级为实测**：部署后对真实含凭证会话跑
   `read_session_transcript`，断言真值缺席（对齐 #58 telegram 项的标准）。
3. **复测口径**：截断计数要同时数 `...` 与 `[片段`，否则 after 侧漏计。

**测试计数**：3368 → **3387 passed** / 13 skipped（+19：注入诚实 9、
transcript 10）。四静态门全绿。层1 反事实 8 项 revert→FAIL→restore→PASS
（唯一双向通过的是钉"FTS 模式上限不变"的守卫，本该如此）。

#### CR 部署与生产验证（2026-08-14，main+sannai 双 home，`e458a8a`）

- `/opt` ff `a7515c1 → e458a8a`；production-safe apply ×2 home 全绿
  （`fail=[]`）；manifest 双 home `deployed_head=e458a8a`、profile 归属正确；
  3 文件 ×3 副本 9 哈希一致。
- **注入复测（同查询同预算，前后对比）**：
  - main：floor 段 **4038→0 字**（score-0 全排除、空段省略）、标记 **0→5**
    （2 条带工具名指针）、总注入 10220→**6615**、无未标注截断。
  - sannai：floor **4469→0**、总注入 8765→**4450**。剩余 2 条旧式 `...`
    是**存储侧**的（sync_turn 写入时 140 字裁剪自带省略号），注入层已完整
    展示存储摘要——属存储宽度议题，非注入缺陷。
  - sannai 标记 0 条属正确：浮现的候选是闲聊时刻，不含漂移话题词。
- **脱敏从声明升级为测量**：raw state.db 扫出 main 19 / sannai 5 个密钥形
  值，4 会话取回 **0 泄露**；其中 3 会话无 [REDACTED] 是 40 条窗口挡的而非
  脱敏挡的——于是**直接翻页到含密钥的第 73 条**：`leaked=False,
  [REDACTED]=True`，脱敏在正主消息上实测咬住。生产 messages 表无
  `created_at`（用 `timestamp`），列名容错解析按设计工作。
- **新进程端到端**（真 agent venv py311 + 真活体插件副本）：4 工具注册、
  system_prompt_block 含 Layered Recall Rule 并点名工具、真实会话
  `handle_tool_call` 取回 ok=2 条；读台账双 home 各落 3 行。
- **llm_judge_probe warn（本轮 main 也 ambiguous）成因良性**：judge 对故意
  模糊的探针查询裁 `ask_choice/no_clear_match`——floor 收紧后垃圾上下文变
  少，judge 更诚实了。后续若持续可调探针预期，不是缺陷。
- **遗留（宿主级，待 owner）**：gateway 进程内持有 provider 模块缓存，
  **交互路径吃到 #58/#59/#60 需 gateway 重启**（今日 15:13 的重启早于全部
  三次部署）。systemd 心跳/cron 均新进程、已生效。
- 证据级别：`deploy_pass` ×2 + 新进程功能实测；`live_monitor_pass` 未跑
  （下个 02:30 定时刷新覆盖）。

- `f5a3487..e458a8a（PR#60 CR）`：注入诚实化（floor 重定义/去重/诚实截断/
  应答段放宽）+ 分层深入读半边 `memory_os_session_recall`（脱敏/有界/台账/
  无 owner 门）+ 三方互认（标记点名工具、说明书教协议、description 教边界）；
  双 home 部署复测 floor 归零、标记上线、脱敏实测咬住；全量 3387/13。

### CS — 图谱注入位关系感知：语义边优先于同源共现（2026-08-14，PR #61）

owner 反馈图谱注入"还没活起来"。shadow 账本量化（main，376 行 8847 条边
决策）三个成因：①**59% 产出是已列出存根**（emitted_stub 1223 >
emitted_full 844）——结晶 floor 20 条把 `seen` 塞满，图谱邻居全被降级；
**CR 的 floor 修复已顺带解决**（复测 5 行 4 全预览）。②**边池 79% 是
co_occurs**（6967/8847）：同一场会话抽取物互连，语义弱但出生权重高
（均值 0.7+），纯权重排序把 6 个 exploit 位全给它们；真正有价值的语义边
（refines/evidence_for/contradicts/depends_on 合计 21%）抢不到位。
③锚点预览「相关记忆」泛化标签=被 resolver 驱逐记录的 index 残行——登记
观察不动。

**修复（②，选择侧不碰出生/权重/反馈闭环——2026-08-06 裁定）**：exploit 位
语义边优先按权重占位，co_occurs 只填语义稀缺剩下的位；explore 轮转保持
类型盲（反饿死不变）。0.50 的 refines 现在能挤掉 0.90 的 co_occurs。

**注入模块自动匹配普查**（owner 问）：Indexed(FTS5)/结晶(FTS+向量+floor
按分)/候选(#58 按查询打分+同义词)/图谱(锚点来自查询 FTS)全部查询驱动；
**故意不按查询**的只有事件段（连续性）与 Overlay（任务状态）。

**gateway 已由 owner 重启**：main 自查报告可见 Layered Recall Rule 注入，
#58/#59/#60 交互路径实证生效。报告另暴露一个新发现登记待诊断：main
profile 的**自指污染**——建造期元讨论（架构/治理/测试）充满记忆库，FTS
什么查询都命中它们；sannai 无此问题，属建造期遗产非机制缺陷，先测量占比
再定治理。

**测试计数**：3387 → **3390 passed** / 13 skipped（+3）；反事实
revert→2 FAIL→restore→PASS（语义稀缺守卫双向通过，钉不变路径）。
