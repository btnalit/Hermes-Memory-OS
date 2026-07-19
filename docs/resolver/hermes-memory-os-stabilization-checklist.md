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

## 待办

BC 代码评审（对 `abcce26` 的 15 项发现）已全部完成：P0×3（BD）、P1×4（BE）、
P2×3（BF）、P3×5（BG）。当前无遗留待办。

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
