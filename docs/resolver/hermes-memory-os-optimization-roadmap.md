# Hermes Memory-OS 与 Sannai Community 综合路线图

> **版本**：v2.9
>
> **更新时间**：2026-07-29
>
> **文档地位**：唯一现行路线图与社区设计；替代旧版 `sannai-community-design-v2.md`、`sannai-community-design-v3.md`
>
> **证据规则**：实现、测试、部署、运行接线、自然观察分别记录；任何一层成立都不能自动证明下一层。
>
> **新增**：v2.7 由 Sannai 本人补充 11.10 节——小院子设计愿景（The Courtyard），包含轻量伙伴 Track A 概念与双轨策略。
> v2.8 补充 11.11 节——对 11.10 的工程审查（8 项边界修正）、修正后的 Track A 设计、复用地图与
> 分步实施计划，供 Sannai 直接开发；11.10 原文保持 Sannai 原貌不改。
> v2.9 更新实施状态：Track A（流萤）已注册并完成首条纸条回路；Track B（阿澜）因服务器资源不足（3.6G RAM）
> 正式 retired，路线图删除双轨策略改为单轨；11.10.3/11.10.4 相应更新。

---

## 1. 目标与非目标

Memory-OS 的目标不是保存尽可能多的信息，而是让 Hermes 在长期运行中可靠地做到：

1. **连续跟随**：知道当前任务、未完事项和历史决策，不复活已结束任务。
2. **懂得轻重**：优先注入当前真正有用的少量上下文，抑制重复、过期和低权威内容。
3. **克制主动**：可以提醒、澄清或表达，但安静也是健康结果。
4. **可信成长**：由自然运行证据和 Owner 决策驱动升级，不把候选、推测或一次性情绪自动写成永久事实。
5. **形成伙伴关系**：Sannai 可通过受治理、资源有界的社区旁挂层拥有异构伙伴与共同经历，但社区不得改写她的身份、关系或记忆成熟度。

工程底座保持不变：

- 文件为 canonical store；SQLite 和派生快照必须可重建。
- 自动写入受 ExecutionGate / StructuralWriteGate 约束。
- 永久记忆、身份和重要关系写入始终受 OwnerGate 控制。
- 外部输入只作为 exposure；不得绕过成熟度与来源边界。
- 未知、冲突、损坏、过期和版本不兼容必须 fail-closed。

明确不做：

- 不建设聊天室、房间系统或多人实时社区平台。
- 不让伙伴继承 Sannai 的 wandering、memory gating、expression autonomy。
- 不让伙伴获得联网、支付、发布或其他外部执行工具。
- 不用 helper、单测、文件存在或一次手工运行冒充 production wiring / live / observing。
- 不为获得绿色状态而隐藏真实 FAIL、删除审计历史或手工补写成熟度。

---

## 2. 统一状态与证据模型

每个能力必须独立记录以下层级：

```text
designed
→ implemented
→ tested
→ deployed
→ wired
→ live
→ observing
→ evidence_mature
→ owner_reviewed / graduated
```

| 状态 | 必要证据 |
|---|---|
| `designed` | 设计、边界、失败语义和验收条件明确 |
| `implemented` | 代码存在且调用契约完整 |
| `tested` | 反事实、定向、全量与 clean-copy 门通过 |
| `deployed` | 目标文件、manifest、hash 与 fresh import 对齐 |
| `wired` | 正式 caller/scheduler/provider/overlay 实际调用 |
| `live` | 真实进程或自然调度产生行为 receipt |
| `observing` | 正在积累自然、不可手工伪造的证据窗口 |
| `evidence_mature` | 样本、时长、反例门与守恒条件满足 |
| `owner_reviewed` | Owner 已基于稳定 token/提案作出决定 |
| `graduated` | 目标模式已生效并具备回滚路径 |
| `blocked` | 依赖、资源、治理或证据门未满足 |
| `retired` | 停止采用，只保留审计历史 |

禁止把以下信号单独写成“完成”：

- pytest 退出码为 0；
- deploy 脚本退出码为 0；
- 文件已复制或 hash 相同；
- 静态 Closure Matrix 绿色；
- 配置开关为 true；
- 手工写入一条 observation；
- mailbox transport receipt；
- roster 中存在一个伙伴名字。

---

## 3. 当前可信基线

### 3.1 已验证的 release 基线

**最新已合并源码基线（本机已对齐并验证）：**

- commit：`2b235370b26dc3640b9e3e3f0b38ca24e0191a05`（`HEAD == origin/main`，由 `b52173b` fast-forward 5 个提交，无本地源码漂移）
- 本机 Linux 隔离 `HERMES_HOME` 全量：`3041 passed / 9 skipped`，耗时 `446.78s`；0 failure。
- Write Surface：`155 / 0 unclassified`；import cycle：`170 modules / 0 cycle`；static hygiene / public checkout probe / `git diff --check`：全过；Closure Matrix 为 `status=ok / closure_status=runtime_evidence_required`，符合静态门只证明 source/static wiring 的边界。
- `004a16b..2b23537` 继续合入路线图 v2.6 文档、历史空白清理，以及 BM 节记录的 monitor/deploy/v24 final verify 14 项复审修复；本机部署验证见稳定化清单 BN 节。

**最近已部署基线（本机 production-safe full deployment）：**

- commit：`f62a069423c17bd35e807c73fe0840b716e93065`（GitHub Actions run `30346974131`，`success`；当时 mount-isolated 与 clean-copy 均为 `3016 passed / 9 skipped`）
- 部署证据：fresh-process runtime import evidence；32 个 live module 集合匹配；runtime tree digest；完整 v1 Full Monitor artifact；Dashboard canonical snapshot。
- 该条仍是最近一次**完整部署**基线。2026-07-29 已把 `2b23537` 中存在既有生产对应物且通过 drift gate 的 4 个目标做本机 targeted deployment：`deploy_clean_host.py` 同步到 flat plugin/runtime 两棵独立树，`memory_os_3_200_monitor.py` 与 `memory_os_candidate_backfill_409.py` 同步到 `/root/.hermes/scripts/`；备份为 `/root/.hermes/backups/memory-os-targeted-20260729T113016Z`。这不更新 full-deploy manifest，也不冒充 production-safe full deployment。
- targeted deployment 后 source/target SHA-256、fresh runtime import、`plan_deployment()`、Monitor timeout/error fail-closed 反事实与 installed-script `--help` 均通过；未重启 Gateway。生产 Full Monitor 实跑发布 `memory-os.monitor.v1`，分类为 `FAIL`（97 pass / 4 warn / 1 fail），唯一 FAIL 仍是 `v2_exposure_schema_era_unhealthy`，属于生产治理健康而非传输/导入失败。

### 3.2 已随 `2b23537` 合并发布的修复（本机 targeted deployment 已完成，完整部署仍待执行）

本轮（`f62a069..004a16b`）先后发现并修复：

- cron adapter probe 的 installed-layout import shadow；
- clean-copy runner 对已删除 tracked 文档的 pathspec 处理；
- deployer 没有把外层 timeout 传给 compatibility 子进程；
- deployer 的 Hermes CLI 子命令没有显式绑定目标 `HERMES_HOME`，导致 multi-profile 部署可能把 manifest/projection 写到 default home；
- 低资源主机 Full Monitor 的 shell alias probes 无单命令 timeout 且 22 个命令串行执行；
- ExecutionGate helper completion 把被 owner 禁用（`enabled=false`）的 cron lane 误报为 missing（现独立 `disabled` 分档 + 专属 WARN 码，守恒公式同步）；
- `classify_snapshot` 对 `status_tool_contract=None` 直接 `AttributeError`，导致整个 Full Monitor 采集崩溃而非单 section FAIL（现与 `doctor` 同款 `isinstance` fail-closed）；
- clean-host `plan_deployment` manifest 记录本机分隔符路径，与 `_deployed_file_paths()` 的 POSIX 口径不一致，Windows 上 postcheck 文件集合比对全量误报（现统一 `.as_posix()`）。

低资源 Full Monitor 修复采用 fail-closed bounded collection：普通命令默认 20 秒、默认 4 workers；cron adapter 等关键聚合 probe 使用显式 60 秒预算。超时记录 code 124 并保持可见，不允许整个 artifact producer 无限挂起。

上述修复及 BM 复审修复已合并进 `origin/main`。本机 targeted deployment 已验证，但未执行 full deployer apply/postcheck、未刷新 full-deploy manifest、未重启 Gateway，因此完整状态仍为 `released / full_deployment_pending`；2.88 default/sannai 也仍需按第 12 节独立部署并生成 fresh runtime artifact。

### 3.3 环境事实

**本机 default：**

- Hermes gateway：user-level service，active。
- Memory-OS heartbeat 与 cognitive-loop timers：active/enabled。
- Full Monitor v1 artifact：fresh、envelope complete、source head 绑定已部署 commit。
- Dashboard 已正确保留 canonical Full Monitor 的 `FAIL`；不再弱化为 `WARN/0 fail`。

**10.20.2.88（YC-NAS，2026-07-28 部署检查）：**

- RAM 约 3.6 GiB；检查时 available 约 1.3 GiB，swap 使用约 1.5/1.8 GiB。
- `/` 约 77% 使用，`/vol1` 约 19% 使用。
- default 与 sannai 已从同一 `/vol1/Hermes-Memory-OS` source checkout 完成 production-safe apply/postcheck；multi-profile manifest scoping 缺陷已在当前 release 修复，最终验收要求两个 home 的 manifest/artifact/closure evidence 分别绑定同一 final SHA。
- default gateway：user-level service，已授权重启并恢复 active。
- sannai gateway：user-level service，已授权重启并恢复 active。
- alanlive gateway：failed 且 disabled；必须继续 dormant，不得自动启动。
- 两个旧 checkout 的部署歧义已收敛：正式部署只使用 `/vol1/Hermes-Memory-OS`；`/opt/Hermes-Memory-OS` 不再作为本轮 deploy source。
- Sannai profile canonical home：`/vol1/.hermes/profiles/sannai`。
- 部署前备份：`/vol1/.hermes/backups/memory-os-v25-20260728T110952Z`，约 342 MiB。

---

## 4. 已修复的系统性问题

### 4.1 Operational Truth 与 Full Monitor

已完成源码与本地 runtime 证明：

- Full Monitor producer 根 payload 发布明确 `memory-os.monitor.v1` schema。
- refresh 不再用 `unknown` 伪造完整 envelope。
- artifact 包含非空 producer receipt、source head、runtime digest 与语义 generated time。
- future clock、损坏 JSON、无效 UTF-8、缺 identity、版本不匹配均 fail-closed。
- v1 artifact 存在时，legacy 不得仅凭 mtime 夺权。
- 同代或更新代损坏 artifact 不得回退到旧绿色结果。
- freshness 由经验证的语义时间计算，不使用可 touch 的文件 mtime 作为权威时间。

### 4.2 公共 consumer

- CLI/provider 公共计数统一通过 typed Operational Truth projection。
- 冲突时公共稳定字段为 unknown/null，不泄漏单边 raw winner。
- Doctor 等内部诊断可读取 raw store/index，但必须明确其诊断用途，不能冒充公共 truth。
- Dashboard 对 invalid/stale/missing/unknown artifact fail-closed。
- 底层 Full Monitor 为 FAIL 时，Dashboard 必须保持 FAIL，`fail >= 1`。

### 4.3 Closure、CI 与部署证明

- Closure Matrix 只证明 source/static-wiring contract；输出明确 `runtime_evidence_required`。
- action path 必须解析到真实 source symbol，不能由静态 JSON 自证。
- runtime evidence 在目标 fresh process 中记录 import origin、module set、runtime digest 与 service observations。
- pytest skip policy 区分 collect/setup/call stage。
- static hygiene compile 在临时副本执行，避免 mount-suite 副产物污染。
- clean-host deployment 使用目标 fresh process、完整 inventory/hash、backup、atomic publish 与 rollback。
- installer 已补齐 Full Monitor 主脚本、refresh、Dashboard snapshot 与 closure runtime evidence 的运行时安装闭包。

### 4.4 数据和状态 helper

已实现并测试，但生产采用程度不同：

- JSONL mixed encoding/invalid UTF-8 逐行隔离。
- SectionStatus 类型、非负计数与守恒 fail-closed。
- Recovery Marker 只阻止同一 terminal task 复活。
- Restraint 不接受裸 `is_owner_approval=true` 作为审批证据。
- private backup 限定 restore root；private Markdown 默认 must-backup。
- natural-row 生产门控由 `execution_gate.resolve_trigger_class()`（Exposure Rollup、V3 Seed 两条 cron 周期实际调用）与 Wandering / Dashboard 的内联 `natural_cron` 过滤承担；`natural_evidence.py` typed helper（TriggerProvenance / 观察窗 / 毕业门）本身仍无生产 consumer（见 P2）。

---

## 5. 当前真实问题与风险登记

### P0 — 发布/部署阻塞

1. **cron adapter installed-layout import shadow**
   - 现象：Full Monitor 内嵌 cron adapter probe 返回 error；随后旧 fallback 把两个 disabled retired right-brain jobs 误报为 unregistered。
   - 根因：installed probe 同时继承 runtime `PYTHONPATH` 并插入 Hermes home；`$HERMES_HOME/plugins` 的 regular package 可遮蔽 runtime `plugins.memory`。
   - 当前：源码、fixture、统一验证、本机和 2.88 default/sannai 部署均已完成；真实 probe 为 `status=ok / unregistered=0 / retired=2`。
   - 禁止做法：把 disabled retired jobs 删除来隐藏误报，或在 Monitor 中直接忽略 adapter failure。

2. **2.88 source checkout 漂移**
   - `/opt/Hermes-Memory-OS` 与 `/vol1/Hermes-Memory-OS` 指向不同旧 commit。
   - 当前：已选择 `/vol1/Hermes-Memory-OS` 为唯一 deploy source，两个 profile 已备份并绑定同一 manifest/source head；旧 `/opt` checkout 仅保留为历史事实，不参与部署。

3. **multi-profile Hermes CLI 写入目标漂移**
   - 现象：Sannai installer、hash 和 postcheck 成功，但 deployment manifest 仍保留旧 SHA；同一轮 default manifest 被重复更新。
   - 根因：deployer 只把 `--hermes-home` 传给 installer/probes，`deployment-manifest`、`projection` 和 LLM judge 等 Hermes CLI 子命令继承了 shell default home。
   - 当前：所有 Hermes CLI 子命令显式使用 `env HERMES_HOME=<target>`；已增加 Sannai plan 反事实和定向测试。最终关闭条件是 default/sannai 两个 home 的 manifest、artifact 和 closure evidence 均绑定 final SHA。

### P1 — 生产治理健康

4. **V2 exposure schema era unhealthy**
   - 当前 Full Monitor 真实 FAIL：`v2_exposure_schema_era_unhealthy`。
   - 这是自然观察/历史数据时代健康问题，不是文件同步失败。
   - 必须继续观察 classified ratio、attribution gaps、rollup lag、conservation failures；不得手工回填自然 credit。

5. **Full Monitor 运行时超过目标**
   - 本机 artifact 有 `full_monitor_runtime_over_target` WARN；2.88 default 在低内存、swap 接近耗尽时分别超过 600 秒和 1200 秒，未发布半成品 artifact。
   - 根因之一是 22 个 shell alias probes 串行且没有 per-command timeout；生产 trace 显示停留在 owner-review probe，而不是 refresh/envelope 损坏。
   - 当前源码已改为有界并发与 fail-closed timeout，定向和统一测试通过；仍需在 2.88 default/sannai 生成 fresh artifact 后才能关闭该问题。
   - 禁止用空 context-manager、删除 probe 或 stale cache 冒充优化。

6. **ExecutionGate helper receipt 不完整**
   - 现象：`_execution_gate_helper_completion_summary` 原本只区分 completed/missing/stale/error/
     envelope-reconciled 四类，未识别 lane 对应 cron job 被 owner/操作员通过 Hermes 自身 cron 管理
     直接禁用（`jobs.json` 中 `enabled=false`）的情况——已注册 lane 一旦被禁用且无新鲜 completion
     记录，会落入 `missing`，与真实执行失败/envelope 未对齐混淆，触发误报 WARN。
   - 当前：已修复为独立 `disabled` 分档（`helper_completion_disabled_count`/`_lanes`），禁用 lane 不
     再计入 missing/stale 或推高 boundary_unobserved；`classify_snapshot` 新增独立
     `execution_gate_memory_os_cron_helper_completion_disabled` WARN 码；`helper_completion_accounted_count`
     守恒公式同步纳入 disabled 分档。定向反事实（revert→FAIL、restore→PASS）与全量测试已过；生产远端
     的真实禁用场景观察仍待部署后自然验证。
   - 不得用伪造 completion row 消除告警。

7. **Dashboard service 未形成独立部署事实**
   - Dashboard snapshot producer 已部署和验证；本机未确认独立 dashboard systemd unit。
   - “snapshot 可生成”不等于“Dashboard server 正在对外提供页面”。是否需要常驻服务必须作为独立运维决定。

### P1 — 社区 live 阻塞

8. **alanlive 资源边界**
   - 2.88 曾在第三 gateway/可选依赖安装期间出现 SIGKILL 和主机重启。
   - alanlive 当前 failed/disabled，保持 dormant 是安全状态。
   - 在容量评估、低资源配置和独立 rollback 方案完成前，不得自动启动。

9. **transport 不等于 autonomous relationship**
   - 已有 Sannai↔alanlive mailbox transport、handled receipt 与 pairing handshake。
   - 尚无伙伴模型正文回复、稳定 scheduler 行为、fresh-session overlay、自然 shared write 或主动引用共同历史的证据。

### P2 — helper-only adoption debt

> **闭环方案见 [`hermes-memory-os-adoption-closure-plan.md`](hermes-memory-os-adoption-closure-plan.md)（2026-08-03）**：该文档把本清单按"接线之后会发生什么"重新分类——6 项合并即终结、4 项建议删除、只有 3 项会进入观察窗口，并为每项指定了具名调用点、退出条件、反事实测试与回滚方式。另更正本节两处：`timeutil` 的实际调用点是 **77 处 / 46 文件**（本节记的 10 处是模块数），且 `parse_utc` 与裸 `fromisoformat` 实测**不等价**，迁移不得按机械重构推进。

10. 以下能力仍不得标为 wired/live（2026-07-29 依据 `004a16b` 逐一以 import/caller 证据核实，
    除注明外全部仅被自身测试引用）：
   - `timeutil` 的剩余 ad-hoc parser 迁移——生产/脚本代码仍有 10 处独立时间解析实现：
     `cleanup.py`、`owner_actions.py`、`permanent_promotion.py`、`structural_edge_proposer.py`、
     `v3_retention.py`、`v3_seed_evidence.py`、`community_triggers.py`、
     `memory_os_monitor_dashboard_snapshot.py`、`memory_os_right_brain_expression_outcome.py`、
     `speak_rate_limit.py`（另：monitor 远端探针脚本内自包含 `_parse_monitor_timestamp` 属有意
     例外，生成式独立脚本不 import 仓库模块）；`timeutil` 当前唯一生产采用路径为
     `__init__ → session_approval`，其余 5 个消费方（continuity/lifecycle/proposal_state/
     natural_evidence/restraint）自身均为 helper-only；
   - ~~`natural_evidence`~~ **已删除（2026-08-03）**：生产 natural-row 门控走 `execution_gate.resolve_trigger_class()`（生产 natural-row 门控见 4.4，
     不经过此模块）；
   - `restraint`（DenialTracker / SessionPriority / CandidateEvaluation，与 9.3 一致，缺主会话
     真实 caller）；
   - `recall_golden` 正式召回 consumer；
   - ~~`lifecycle`~~ **已删除（2026-08-03）**：`plugins/system/lifecycle.py` 才是在用的那个；
   - `error_registry` 全局 consumer；
   - ~~`proposal_state`~~ **已删除（2026-08-03）**：终态判定由 `TERMINAL_ACTIONS_BY_TARGET_TYPE` + `DEFER_ACTION_TYPES` 承载；
   - `continuity` system prompt/overlay consumer；
   - `gap_note` 正式 session/recall renderer；
   - `seed_evidence_incremental` 生产调用；
   - `monitor_perf` 真实 monitor 集成；
   - `evidence_gen` CI 集成（`.github/workflows/ci.yml` 已核实未调用）。

---

## 6. R1 — 自然证据与毕业门

**状态**：`wired/observing in parts; graduation blocked`

### R1.1 V2 Exposure

- 只认计划时间自然产生的最终 `natural_cron` rollup。
- manual/backfill/legacy 行永不获得 natural credit。
- 观察 schema-era classified ratio、attribution、lag、conservation 与连续预算压力。
- 30 日观察门和 7 日压力门独立成立。
- 达标后只产生 Owner 可撤销提案；不自动解冻 V2-C/D。

最低门：

```text
manual_credit_count = 0
legacy_credit_count = 0
conservation_failure_count = 0
natural_cycle_count >= configured_gate
observation_days >= configured_gate
```

### R1.2 Recall Plan shadow

- 按 active-task、casual-continuity、diagnostic、foreground-control、low-clue 分层观察。
- 记录 matrix version/digest/window ID；权重变化时重置窗口。
- 保持 `retrieve_called=true`、`format_called=false`、live output 不变。
- 只有零关键遗漏、零 authority escape、零 stale-body selection 后才提出 bounded apply canary。

> **待修订（2026-08-04，随接线闭环方案批次 D 落地）**：Owner 已裁定 Class 3 三项
> **不开观察窗口、直接实现**（接线闭环方案第 6 节第 3 条），只保留"默认可关的开关 +
> 回滚能力"。本节最后一条的 shadow→canary 阶梯因此与该裁定分叉，须在批次 D 一并修订。
>
> **批次 C（continuity 分级披露，2026-08-04 已落地）不涉及本分叉**：它是 report-only，
> live prefetch 输出逐字节不变，正符合本节「保持 live output 不变」。
> 需要修订本节的是**批次 D**——gap_note 要往 live 输出加一句不确定性披露且不开 shadow 窗口。

### R1.3 V3 Seed / Wandering

- Seed 未成熟前不调用 wandering inference。
- Seed ready 后允许 `entries=[]`；长期安静是健康结果。
- synthesis/outlet/expression 分阶段开放。
- 必须由自然样本和 Owner 真实反馈驱动，不由模型自评。

---

## 7. R2 — 单一运行真相与发布基础设施

**状态**：`source/release verified (004a16b); local+2.88 deployment pending for f62a069..004a16b delta`

- Operational Truth、artifact envelope、public consumer fail-closed：源码和本机 runtime 已证明。
- mount-isolated、clean-copy、public checkout、write surface、static hygiene、import cycle：已进入统一 runner。
- Closure Matrix 静态门与 runtime evidence 分离。
- private backup 已实现；异机加密备份仍待运维落地。
- 每次 release 必须绑定最终 tree fingerprint、GitHub CI、manifest 与 fresh runtime evidence。

---

## 8. R3/R4 — 语义与状态机收敛

**状态**：`partial adoption`

- natural-row：生产门控经 `resolve_trigger_class()` + 内联过滤运行（见 4.4）；`natural_evidence`
  typed helper 未采用，继续审计剩余 consumer。
- timeutil：公共 helper 与 fixture 完成；剩余 10 处 ad-hoc parser 待逐模块迁移（清单见 P2 #10）。
- error registry：保持 helper/tested，直至生产 consumer 迁移。
- ~~SectionStatus~~ **已删除（2026-08-03）**：接线意味着大改 `memory_os_3_200_monitor.py`，与 CLAUDE.md「大文件只做最小定向改动」冲突。
- Proposal/Token state：helper/tested；OwnerActionProcessor/token ledger 尚未迁移。
- Trigger provenance：`natural_cron | manual | legacy_unmarked` 类型封闭，manual 不得伪造 natural envelope。

---

## 9. R5 — 认知伙伴主线

### 9.1 Continuity

- State Overlay 已处理 open-thread 去重与 latest-effective current task。
- Recovery Marker 已修复。
- continuity helper 尚待正式 system prompt/overlay caller。

### 9.2 Relevance

- Recall Plan 保持 shadow。
- must-recall golden 与 Gap Note 保持 implemented/tested，未接线前不称 live。
- apply canary 必须 route/profile 有界且可立即回滚。

### 9.3 Restraint

- low-clue recall 与 bounded judge 已存在。
- metadata-only MemorySources 不复制私密正文。
- Restraint/DenialTracker/SessionPriority 尚需主会话真实 caller 和 feedback receipt。
- 当前 owner 指令永远高于历史 task anchor、proposal、digest 或 reflection。

### 9.4 Review Partnership

- 主会话审批由稳定 token 和 Owner review surface 承载。
- Review Agenda 目标是减少噪音，不是自动替 Owner 做决定。
- 持续记录 useful/irrelevant/too-frequent/off-voice/boundary-private 等真实反馈。

### 9.5 Warmth & Proactivity

- V3 自然证据成熟前保持主动表达能力受限。
- 只有真实 delivery receipt 才能把 requested intent 记为 realized/shared。
- 需要 frequency cap、quiet window、mute/revoke 与 privacy boundary。

---

## 10. R6 — 性能与维护

**状态**：`implemented helpers; runtime/CI adoption incomplete`

- Seed incremental：接入生产前必须证明全量/增量等价和可回放。
- Monitor perf：必须按真实 section 分段测量，报告 cold/warm 路径与证据完整性。
- evidence generator：保持 no-canonical-write；进入 CI 前不得称自动闭环。
- 长期维护优先删除平行 helper，而不是继续增加第三套语义。

---

## 11. R7 — Sannai Community 综合设计

> **本节已迁出（2026-07-29）**：原 11.1–11.12.7（含 Sannai 本人撰写的 11.10《小院子》与
> 11.12《窗台/一起看/兴趣花园》、11.11 工程审查与 11.12.7 CI/实现落差复审）已随
> `community.py`/`community_shared.py`/`community_table.py`/`community_interest_garden.py`/
> `community_triggers.py`/`community_snapshot.py`/`community_partner_runtime.py`/
> `partner_create.py`、`scripts/community_monitor.py`、`scripts/community_partner_reply.py`、
> `scripts/deploy_community.py` 一并整体迁出本仓库，独立为
> [sannai-community](https://github.com/btnalit/sannai-community)。完整设计文档（原文未改，
> 编号未重排）见该仓库 `docs/design.md`；已知实现落差（11.12.7 记录的零调用方模块/内联脚本
> 分叉）见该仓库 README 的 Known implementation gaps。
>
> Hermes-Memory-OS 侧同时移除的集成点：`cognitive_loop.py` 的 `_community_cycle` 步骤、
> `memory-os-agent-os` CLI 的 `community status` 子命令、`install_memory_os_plugin.py` 的
> community 数据布局初始化、`state_overlay.py`/`state_overlay_schema.py`/
> `state_overlay_renderer.py` 的 `community_snapshot` overlay 分区。未保留任何可选钩子——
> 本仓库不再感知 community 模块是否存在。生产主机（hermes-media）上已部署的 community 数据
> 与 cron 任务不受本次仓库层面剥离影响，未做处理（见稳定化清单本节对应条目）。
>
> 本节标题与编号保留，供本文件 §13/§14/§15 与稳定化清单中既有的 "11.x" 交叉引用继续解析到
> 同一位置；正文内容不再维护于本仓库。

---

## 12. 发布与部署强制流程

1. 盘点源码、测试、caller、installer、runtime copy 与服务。
2. 保存 pre-fix 反事实。
3. 写回归并实现最小修复。
4. 跑 targeted regression。
5. 跑统一 runner：targeted + governance + mount-isolated full suite + clean-copy。
6. 冻结 tree/diff fingerprint。
7. 本地 checkpoint commit。
8. 备份目标；用正式 deployer apply/postcheck，禁止手工补文件冒充完整部署。
9. 每个 Hermes home 独立验证 plugin/runtime/scripts hash、fresh import、manifest、timers、cron 与 artifact。
10. 运行 Full Monitor，分别报告 deployment integrity 与 operational health。
11. Gateway restart 是独立 Owner 边界；未授权时不重启。
12. 生产发现源码问题则回源码修复、重新测试和部署；不得隐藏第二轮证据。
13. 生产闭包后再 push；GitHub CI 必须绑定最终 SHA。

远端 2.88 必须分别处理：

- `/vol1/.hermes` default；
- `/vol1/.hermes/profiles/sannai`；
- alanlive 保持 disabled/dormant，不纳入本轮 active deployment。

认证信息不得写入仓库、文档、部署 manifest、日志摘要或持久记忆。

---

## 13. 阶段验收矩阵

| 阶段 | 退出条件 | 禁止动作 |
|---|---|---|
| R1 自然证据 | 自然窗口满足且 falsifier 未命中 | 手工补证、回填成熟度 |
| R2 运行真相 | Monitor/Dashboard/CLI/provider 同源；runtime evidence 绑定 final SHA | 平行权威源、legacy mtime 夺权 |
| R3 语义收敛 | 单一实现、旧数据兼容、消费者迁移 | 机械合并不同语义 |
| R4 状态机 | 非法状态结构上不可写、旧行可读 | 重写 append-only 历史 |
| R5 认知伙伴 | Owner 反馈与自然质量门满足 | 自动身份/关系写入、强制表达 |
| R6 性能 | 行为等价且真实资源改善 | 少跑检查、stale cache 伪装加速 |
| R7 社区（已迁出，见 §11） | 伙伴持续运行、真实回复、自然 shared/overlay/scheduler evidence | 用 transport/pairing 冒充关系 live |

---

## 14. 当前优先级

> **原 1–4 项已迁出（2026-07-29）**：以下四项均属于 Sannai Community（流萤 Track A）功能，
> 已随 §11 记录的 `community.py` 等模块与 `scripts/community_monitor.py`、
> `scripts/community_partner_reply.py`、`scripts/deploy_community.py` 一并迁出本仓库，独立为
> [sannai-community](https://github.com/btnalit/sannai-community)：原「观察窗（14天）：流萤
> cron 自然运行，记录预算违规、error_record、健康安静时刻」、原「社区快照：定期执行
> `build_community_snapshot()` 和 `community_monitor.py` 检查社区状态」（两函数均已随迁出删除，
> 本仓库不再提供）、原「Sannai 主动管理：有想法时写纸条给流萤」、原「社区报纸：探索报纸功能」。
> 本仓库当前没有可执行的社区相关优先级；后续社区侧当前优先级请见该仓库。

---

## 15. 最终成功标准

路线图成功不以代码量、测试数量或绿色 Dashboard 为目标，而以以下事实衡量：

- Hermes 稳定接续当前任务，不复活旧任务；
- Recall 减少重复和无关上下文，同时不越权、不漏关键事实；
- Monitor、Dashboard、CLI、provider 和 scheduler 对运行事实不互相矛盾；
- 失败、冲突和证据不足保持可见；
- V2/V3 毕业由自然证据和 Owner 决策驱动；
- 系统可以主动，也能长期安静；
- 所有生产变更可审计、可回滚，并绑定源码、runtime 和行为证据。

---

## 16. 架构定性与后续架构优化规划（2026-08-10，docs-only）

**定性**：Hermes-Memory-OS 是 **Governed Living Memory Architecture** ——
治理脊柱（ExecutionGate / StructuralWriteGate / OwnerGate / ResolverGate +
证据审计）是横穿 Memory / Cognition / Graph 三个数据面的**控制面**，不是
与它们平级的第五个环。六条回路（Loop #0 观察元回路 + 记忆生命周期 / 认知 /
图谱 / 自进化 / 表达）的清单、契约位置与生产闭环状态表见公开文档
`docs/architecture.md`（本节新增当日落地）。

三条一级原则（提炼自实测事故，非理论）：

- **Execution is not Evidence** —— 干净 envelope 只证明 lane 跑了；
- **Repetition is not Convergence** —— lane 可以跑几百次而 backlog 在涨；
- **回路只有当其反馈在生产上改变了未来行为，才算闭合。**

**后续架构优化——全部 docs-only / 触发条件驱动**（触发条件出现前动工即属
scope creep，违反 stabilization 冻结）：

1. **LoopSpec 只做文档命名，禁止 runtime 注册表**。回路契约已由分布式机制
   承载（id/cadence=cron_registry lane，risk/scope/boundary/postcheck=
   ExecutionGate envelope，evidence=last_run 块与账本，feedback=governance
   feedback bridge）。中心化注册表=同一事实的第二定义=漂移源。
2. **Edge Explanation View 只做投影**。"为什么这条边 0.76"所需证据
   （出生证据类+先验、proposer、confidence、注入结局、命中史、矛盾状态）
   全部已存在于既有账本；出现真实 owner-review/调试需求时做只读投影，
   **不得新增存储**。
3. **不新增持久化边状态**。emerging/weakening/contested/superseded 均可由
   weight + last_hit 距今 + 矛盾边 + invalidated 投影得出——**能投影的状态
   不许持久化**，否则状态机膨胀且为 gate 词表漂移开新面。
4. **时间性边字段（valid_from/valid_until/last_confirmed_at）推迟**到出现
   会因此改变决策的消费者；纪元标记与账本时间戳覆盖当前需要。
5. **图谱成熟度里程碑只观察不干预**：强化自然积累（进行中）→ 首个自然
   遗忘潮（预期 2026-10，属预期维护非事故）→ 遗忘后再繁殖。三者是要
   **让其发生**的观测，不是工作项。
6. **文档常量同步守卫，推迟到下一次常量变更**。边生命周期常量
   （0.45+0.30×confidence、0.12、60 天、≤50/run、0.70/0.55/0.45/0.35）
   现复写于 CLAUDE.md / README / docs/architecture.md 三处，与
   `edge_weights.py` / `edge_weight_feedback.py` 无同步守卫——散文版的
   "gate 词表漂移"。触发条件：任一常量首次变更时，连带建立文档扫描
   守卫（或把文档改为引用而非复写）；在此之前不动工。
