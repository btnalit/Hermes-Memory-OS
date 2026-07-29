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

## 待办

BC 代码评审（对 `abcce26` 的 15 项发现）已全部完成：P0×3（BD）、P1×4（BE）、
P2×3（BF）、P3×5（BG）。

BJ 待办的"9 项 Windows 本地 pre-existing 测试失败诊断"已由 BK 完成：7/9 为真实代码/测试缺陷，
已修复；2/9（pytest_policy skip-count）诊断为本机环境伪影，非项目代码缺陷，不修复。

当前遗留：
1. 四个 helper-completion 兄弟 WARN 码的 clean-host 分类表注册（视 `deploy_memory_os.py` 是否
   接入 cron onboarding 决定是否需要，BJ 记录）。
2. `install_memory_os_plugin.py` 五处 `str(path.relative_to(...))` 与本次修复的
   `plan_deployment()` 同一模式，当前无触发路径，暂不改动（BK 记录）。
3. `shell_alias_no_env()` 的 22 条 CLI 探针命令并行执行（`ThreadPoolExecutor`）对同一
   `HERMES_HOME` 文件/SQLite 状态的一般性并发风险——无实测复现、无并发单测覆盖，记录为已知
   残留风险（BM 记录，`review_reply` 使用假 token 探针本身已确认安全）。

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
