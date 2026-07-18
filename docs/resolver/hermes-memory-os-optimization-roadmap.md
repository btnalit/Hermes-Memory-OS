# Hermes-Memory-OS 后续优化路线图（收敛 / 加固 / 统一状态机）

> 编写背景（2026-07-19）：BC 代码评审 15 项（P0×3 / P1×4 / P2×3 / P3×5）已全部关闭
> （见稳定化清单 BD/BE/BF/BG 节，最终基线 2601 passed / 13 skipped，HEAD `eaf718c`）。
> 本文档是修复周期的收官交接：把四轮修复中暴露出的**系统性模式**整理成后续优化方向，
> 按优先级分阶段，每阶段给出可机检的验收门。执行时沿用 Section W 五规则与
> "主会话验证收尾、子智能体按模型匹配并行修复"的调度规范。

---

## R1 — 生产证据闭环（最高优先级，先于一切重构）

**动机**：BD→BG 四轮共 31 个新测试全部是 `local_pass` 证据级别。其中多项修复
（BD.1 升级循环顺序、BE.1/BE.2 账本采集降级、BF.2 无来源标记、BG.4 探针 fallback）
的**存在意义就是生产远端行为**，本地测试只能证明逻辑、不能证明部署形态。

- [ ] 部署当前 main（`eaf718c`+）到 hermes-media（10.20.3.200），走
      `deploy_memory_os.py` 完整 phased 流程（plan→preflight→dry-run→apply→postcheck→report）。
- [ ] 跑 `memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary`，
      验收：`live_monitor_pass`，且 living_memory_promotion section 报
      `ledger_state_collection_status == "collected"`（证明 BC.1/BE 链路真实采集）。
- [ ] 跑 hermes-feiniu clean-host profile，验收：所有 WARN 均落在
      `CLEAN_HOST_WARN_CLASSIFICATIONS` 注册表内（无 `clean_host_warn_unclassified`）。
- [ ] 故障注入一次：远端临时改坏一个账本文件 → live monitor 必须产出
      `living_memory_promotion_ledger_state_collection_failed_in_production` FAIL 而非崩溃
      （BD.1+BE.2 的生产反事实）。恢复后复跑 PASS。
- [ ] 在稳定化清单补一节记录以上证据（评级从 local_pass 升为 live_monitor_pass）。

**禁止的完成信号**：fast_probe PASS、本地 pytest 通过、部署脚本 exit 0。

## R2 — 加固（防回归基建）

**动机**：本周期暴露了三类"环境性脆弱"：目录清空丢提交、测试日期腐化（BE.5）、
本机 skip 口径漂移（8→13，BE 验证结论）。

- [ ] **CI**：GitHub Actions 跑全量 pytest + 四项静态门（import cycle / write surface /
      hygiene / public checkout probe --strict），push 与 PR 均触发。验收：badge 绿；
      故意提交一个坏行 CI 变红。CI 同时固化"公共检出"的 skip 口径基线（13 skipped），
      漂移即可见。
- [ ] **日期腐化清扫**（Section W 规则 5 的全仓应用）：grep 所有测试 fixture 中的硬编码
      历史日期（`datetime(202`），凡与真实时钟 aging/TTL 逻辑相交的（BE.5 同类），改锚
      `datetime.now()` 或注入时钟。验收：把系统时间假想快进 90 天（`freezegun` 或
      env 注入）全量仍绿。
- [ ] **jsonl 读取模糊测试**：对 `jsonl_io.read_jsonl_result` 与其消费者
      （BG.1 后的 ledger 读取、seed evidence、session mirror）补 property-based 坏输入
      测试（截断行、混合编码、超长行、BOM、非对象 JSON）。验收：任何输入不崩溃，
      error_records 有界。
- [ ] **gitignored 资产备份纪律**：`docs/internal-memory-os/` 等仍是"目录清空即永久丢失"。
      建立私有备份 remote 或定期 `git bundle`+异机存放；稳定化清单已入库（BD 周期教训），
      内部文档同样处理或明示可丢。
- [ ] **已知告警清零**：crystallized.py:772 `auto_promote_enabled` → `permanent_proposal_enabled`
      迁移收尾；knob_overrides.py:472 ambient roots fallback 警告消除。验收：全量测试
      0 warnings。

## R3 — 收敛（去重复，防漂移）

**动机**：BG.2（trigger_class 判定）证明了"逐字重复的语义代码必然漂移"。同类重复仍存：

- [ ] **时间戳解析统一**：全仓至少有 `parse_timestamp`（permanent_promotion）、
      `_parse_datetime`（v3_seed_evidence）、`_parse_dt`（owner_actions）等多份同语义
      ISO 解析器（BF.3 清扫时逐一确认过语义）。抽到 `jsonl_io` 或新的 `timeutil` 单点，
      各模块改引用；BG.2 式同对象防漂移测试。
- [ ] **natural_cron 视图统一**：目前"只认 natural 行"的语义散在三处独立实现——
      快照 `natural_by_date` 独立 LWW（BD.3+BF.3）、wandering 种子行过滤（BE.4）、
      dashboard latest 行选取（BG.5）。抽共享的 `natural_rows(daily_rows)` /
      `latest_natural_row(daily_rows)` 视图函数进 v3_seed_evidence，三个消费者共用。
      验收：三处只剩一份过滤逻辑 + 防漂移测试。
- [ ] **错误码注册表**：`remote_probe_field_missing` / `ledger_state_not_supplied` /
      `missing_from_collected_counts` / `*_collection_failed` / `*_unavailable` 等错误码
      现在是散落的字符串字面量。收敛为模块级常量 + 一份错误码语义清单（何时出现、
      谁消费、生产行为），monitor 分类表引用常量而非裸字符串。验收：grep 裸字符串
      错误码为零；写错常量名变成 ImportError 而非静默新码。
- [ ] **monitor summarize_* 模式收敛**：不拆文件（CLAUDE.md 红线），但各 section 的
      "占位 dict → 采集 → 状态标记"模式可以共享一个小骨架（见 R4 的 SectionStatus），
      消除 BF.2 类"分支链漏路径"再次出现的土壤。

## R4 — 统一状态机（消除整类缺陷）

**动机**：BE.1（缺 status 键读成健康）、BF.2（隐式第四路径）、BG.4（error_code=None
静默）是**同一类缺陷的三次出现**：状态用零散字符串+可缺失的键表达，无统一契约。
逐个修是打地鼠，统一状态机是拆机器。

- [ ] **SectionStatus 契约**：定义单一采集状态机并应用到 monitor 每个 section：
      `collected | unavailable`，且不变量为——status 键**永远存在**；
      `unavailable` 时 `*_error_code` **永远非空**；`collected` 时各计数字段**永远齐全**
      （缺键即降级 unavailable，BE.1 的 setdefault 防御推广为通例）。
      用一个 `make_section(placeholder, collector)` 骨架函数承载，分支链消失。
      验收：结构性测试遍历快照所有 section 断言不变量；BF.2 类缺陷在骨架层面不可能写出。
- [ ] **分类流水线固化**：BD.1 把升级循环移到函数末尾靠的是"位置纪律"。固化为显式
      四阶段流水线 `collect → warn/fail 归集 → clean-host/production 升级 → status 定级`，
      并加结构性守卫测试：断言 `classify_snapshot` 源码中升级循环之后没有任何
      `warn.append` / `fail.append`（AST 或行序检查），让 BD.1 类回归在测试层被锁死。
- [ ] **提案/令牌状态机显式化**：`open/deciding/approved/rejected/deferred/revoked/expired`
      与 token `open/consumed/revoked/expired` 的合法迁移目前隐含在 owner_actions 各处理
      分支里。写出显式迁移表（dict[状态, set[后继]]）+ 校验 helper，owner_actions 写入前
      校验，配迁移矩阵测试（合法全过、非法全拒）。验收：任何非法迁移落 error_record
      而非静默写入。
- [ ] **trigger_class 三值封闭**：`natural_cron | manual | 缺失(legacy)` 的三值语义现在
      靠注释维系。在 resolve_trigger_class 旁定义常量与 `is_natural(row)` 判定，禁止新代码
      直接比对字符串字面量（hygiene check 可加 grep 规则）。

## R5 — 长线（择机）

- [ ] **seed evidence 增量化**：`run_v3_seed_evidence_cycle` 每日全量
      `read_memory_source_records(limit=1_000_000)` 再窗口过滤。改按 offset 游标增量读
      （daily_record 已存 source_offset_start/end，基建现成）。验收：等价性测试 +
      大账本（10万行）耗时对比。
- [ ] **closure-matrix 公共检出覆盖**：5 个因 `docs/internal-memory-os/` 缺失而 skip 的
      测试，评估是否可用最小 fixture 副本在公共检出跑起来，缩小 8/13 口径差。
- [ ] **稳定化清单自动化**：每周期的"测试数 delta / 静态门结果"由脚本生成追加，减少
      手写口径错误（BD 节的 2579/8 与后来实测 2570+1F/13 的口径混乱不再发生）。
- [ ] **监控看板一致性巡检**：dashboard 各字段与 monitor 分类口径的一致性（BG.5 修了
      seed evidence 一处；用同一份 natural 视图后可写一个"看板字段 ↔ 门控口径"映射表
      做巡检测试）。

---

## 执行原则（沿用既定规范）

1. 顺序：R1 必须最先（生产证据），R2 其次（防回归基建），R3/R4 可并行拆包
   （文件不重叠 + 可独立验证才拆；模型匹配 haiku/sonnet；主会话统一复核全量+静态门+提交）。
2. 每项改动走 Section W 五规则；行为改变配反事实测试（revert→fail→restore→pass 实证），
   纯重构配等价性+防漂移测试。
3. 每完成一个 R 阶段，在稳定化清单加节记录（BH、BI、……），"一句话"追加提交区间。
4. R4 动 owner_actions 时记住红线：最小定向修改，不拆大文件，不加治理模块交叉 import，
   OwnerGate 权限边界不放宽。

## 当前基线快照（交接时点）

- HEAD：`eaf718c`（fix 链）/ `c156bd1`（含清单）；远端 GitHub main 同步。
- 全量：2601 passed / 13 skipped / 2 warnings（本机公共检出口径）。
- 静态门：四项全绿；write surface unclassified_count=0。
- 证据级别：全部 local_pass —— R1 是下一步的全部理由。
