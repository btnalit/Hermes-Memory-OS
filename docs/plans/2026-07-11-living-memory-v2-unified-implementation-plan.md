# Living Memory V2.2.2 · 稳定化与后续落地计划

- 日期：2026-07-11
- 需求源：`docs/resolver/living-memory-v2-unified-spec.md`
- 审计基线：`eab6ed7`
- 执行顺序：S0 稳定化 → V2-E → V2-A → V2-B；V2-C/D 保持冻结
- 提交纪律：每个任务独立提交；先留下 RED/poison 证据，再提交 GREEN；不 squash

## 1. Task anchor（执行期间只读）

```yaml
anchor:
  purpose: "让 Living Memory 只把永久晋升交给 owner，其他生命周期自运营；同时保持 Memory-OS 底座与 Hermes 宿主的插件化边界。"
  significance: strategic
  goal: "S0 与 E/A/B 的规定证据闸全部通过，永久晋升无旁路，非永久状态不主动请求人工，真实 owner 通道完成一次 propose-to-permanent 闭环。"
  acceptance_gates:
    - "focused pytest + full pytest (no -x)"
    - "memory_os_static_hygiene_check.py"
    - "write-surface unclassified == 0"
    - "import-cycle check"
    - "full live monitor >= 3 consecutive scheduled PASS cycles"
    - "real owner-channel approve smoke"
  forbidden_done_signals:
    - "直接调用函数通过，却未运行 monitor 内嵌子进程"
    - "仅把 cron 改名以掩盖真实 Memory-OS 所有权"
    - "只使用 unique tmp，却没有保护 read-modify-write 临界区"
    - "monitor-only 或 CLI-only 代替真实 owner 通道"
    - "local tests 代替部署后的重叠 cron 周期证据"
    - "削弱或跳过边界、poison、全量测试来获得 PASS"
```

## 2. Dynamic-closure preflight

```text
source_of_truth: living-memory-v2-unified-spec.md + eab6ed7 current code + 3.200 read-only cron/output evidence
finding_type: monitor gap + scheduler ownership drift + concurrent persistence bug + host-boundary debt
owning_seam: monitor subprocess bootstrap / Hermes cron registry adapter / ExecutionGate sidecar writer / host delivery adapter
reverse_scope: Memory-OS owns domain state and structured reports; Hermes owns cron, channel, send, reply ingress; RAGFlow remains external-evidence seam
equivalent_contract_or_project_contract: unified spec §1-§4 + 29-series module integration contract + cron registry snapshot
evidence_loop: clean-env subprocess / parallel runner repro / onboarding dry-run / deployed scheduled cycles / real owner-channel smoke
monitor_or_validation_fields: bootstrap stage+reason, registered/naked/unregistered cron counts, gate completion/index counts, owner hard-zero fields
promotion_signal: S0 local+integration PASS, then owner-authorized apply and live PASS
stop_or_rollback_signal: bootstrap still cascades FAIL; duplicate cron; any lost index entry; boundary guard regression; nonpromotion owner delivery > 0
external_review: required before cron apply, any host capability apply, v2e flag flip, and live owner-channel smoke
```

## 3. 已确认事实与决策

1. `owner_review_ingress_guard_summary()` 同时存在 import-layout 风险和未注入 `_hermes_home` 的子进程变量错误；异常被 catch 后，默认值被分类器放大成 4 个功能 FAIL。
2. `memory-os-hindsight-health-probe` 与 `memory-os-ragflow-readonly-evidence-probe` 在线上均 enabled 且最近运行成功，但不在 active registry snapshot。
3. Hindsight 是 Memory-OS 内建 substrate，健康探针应注册；RAGFlow 是 provider-specific external-evidence seam，把它写进 core registry 会破坏 provider-agnostic CI，因此采用 seam/宿主改名迁移。
4. proposal-followups 的历史失败来自多个 runner 竞争同一 `.execution_gate_index.json.tmp`。2026-07-11 08:00、09:30、10:30 的输出均为同一 `os.replace` FileNotFoundError；最近一次成功只说明问题间歇出现，不能结案。
5. 单纯使用不同 tmp 文件只能消除 FileNotFoundError，仍会发生 lost update；必须锁住完整 read-modify-write。

## 4. Stage S0 · 稳定化前置闸

### S0.1 Monitor 内嵌 owner ingress 探测

目标：让 monitor 通过与生产安装一致的 clean-env 子进程真实观测工具能力，并把 bootstrap 失败与功能失败分开。

RED-first：

- 在 `tests/scripts/test_memory_os_3_200_monitor.py` 增加 clean-env 子进程 fixture：仅提供安装所需环境，不继承开发 checkout 的 `PYTHONPATH`。
- poison A：保留子进程内 `_hermes_home` 自由变量，断言出现单一 bootstrap error，禁止出现 4 个 capability FAIL。
- poison B：移除正确 import root，断言 stage=`import`、capability=`unobserved`。
- GREEN 断言：tool available、status=`ok`、input mode=`structured`、structured count=1、事件/working/candidate 污染均为 0。

实现：

- 抽出最小的 child-env builder；`HERMES_HOME` 只从 env 读取一次。
- import roots 按安装布局显式构造并去重，子进程回报 bounded module-origin class，不泄露敏感路径。
- 报告增加 `probe_status: ok|bootstrap_error`、`bootstrap_stage`、`bootstrap_reason_code`。
- classifier 仅在 `probe_status=ok` 时判断 capability；bootstrap error 单独 FAIL 一次。

验收：focused pytest → monitor 脚本实际子进程 → full local gates。

建议提交：`fix(monitor): isolate owner ingress probe bootstrap failures`

### S0.2 Cron 所有权与 registry 收敛

目标：所有 Memory-OS-owned cron 均由 registry/onboarding 管理；provider-specific seam job 不伪装成 Memory-OS core job。

RED-first：

- registry test 要求 Hindsight health spec 存在、read-only/no-agent、默认 `33 * * * *`，且进入 active-closure snapshot。
- onboarding dry-run test 要求生成/识别 Hindsight job，不重复创建。
- poison：在 `plugins/memory/memory_os/` 引入 `ragflow` 字面量必须继续失败。
- monitor fixture 同时包含 registered Hindsight 与 renamed external-evidence job，断言 unregistered-like=0、external job 不计入 Memory-OS expected/wrapped。
- migration fixture 覆盖已有 job id，断言不会同时保留两个 enabled job。

实现：

- `cron_registry.py` 新增 `hindsight_health_probe`，`wrapper_script == raw_script`，标注 no-agent/read-only、不要求 boundary report。
- onboarding 增加 schedule 参数并把 key 纳入 active closure；现有同名 job 走原位 edit。
- 在 Hermes/seam 部署层把 RAGFlow job 改为 `external-evidence-ragflow-readonly-probe`，可见 wrapper 改为 `external_evidence_ragflow_readonly_probe.sh`；wrapper 继续调用现有 read-only Python probe，provider 配置与 secret file 仍留宿主。
- create-verify-pause-old 仅在 Hermes CLI 不支持原位 edit 时使用；先确认新 job 一次成功，再 pause 旧 job。

验收：registry/onboarding/monitor tests → onboarding dry-run report → 外部审查 → apply → `hermes cron list --all` 与各一次成功输出。

回滚：恢复旧 job id/name/wrapper 并 pause 新 job；不删除历史输出。

建议提交：

- `fix(cron): register hindsight health probe`
- `fix(seam): classify ragflow probe as external evidence job`

### S0.3 ExecutionGate sidecar 并发安全

目标：重叠 cron 不崩溃、不丢 permit/completion index 更新。

RED-first：

- 在 `tests/scripts/test_memory_os_execution_gate_runner.py` 启动至少 8 个并行 runner，共用同一 `HERMES_HOME`。
- 用 barrier/helper delay 让进程同时进入 index 更新；当前实现必须稳定复现非零退出或 index 丢项。
- GREEN：全部 returncode=0，journal JSONL 可解析，index 含全部 envelope id，每个 completion_count=1。
- poison：只换 unique tmp、不加临界区锁时，lost-update 断言必须失败。
- crash fixture：锁内写 tmp 后异常，旧 index 仍可读，下次运行可恢复；遗留 tmp 可安全忽略/清理。

实现：

- 使用 `.execution_gate_index.json.lock` 做跨进程排他锁，覆盖 read/merge/write/replace 全过程。
- 每次写使用同目录唯一 tmp；flush + fsync 后 `os.replace`。Windows 测试使用进程内锁或项目已有的明确 fallback，但 Linux 生产必须是进程锁。
- 锁等待有界；超时返回结构化 gate-infrastructure error，绝不运行 helper 后假报成功。
- journal 仍是审计源；sidecar 只作 O(1) 投影，可由 journal reconcile 重建。

验收：parallel regression 重复 20 次 → full local gates → 外部审查/部署 → 覆盖 3 个重叠计划周期；检查 traceback=0、index/journal 对账=0 差异。

回滚：恢复 runner 版本；sidecar 可从 append-only journal 重建，禁止删 journal。

建议提交：`fix(gate): serialize execution sidecar updates across cron processes`

### S0.4 Memory-OS / Hermes host boundary 清债

目标：core 不再选择通道或执行 `hermes send`，同时 CI 能抓到语义等价旁路。

RED-first：

- static poison fixtures 分别加入 subprocess/exec `hermes send`、通道优先级选择、host onboarding import、直接 channel-directory 访问，均必须 exit 1。
- static poison 还要覆盖 Hermes cron create/edit/help、`hermes --version` 与 core 内 host capability subprocess；不得以 blanket 禁止 `subprocess` 代替语义检查。
- host adapter contract test：Memory-OS prepare/preview 只返回结构化 payload，dry-run 零写入、零发送。
- current legacy code 在迁移前应触发新增 guard，证明 guard 不是摆设。

实现：

- 将 legacy channel resolver、delivery adapter 消费、one-shot send、`hermes_cron_adapter` 的 host job/command 能力和 `host_capability_probe` 的 Hermes 命令探测移到 Hermes agent plugin/host adapter。
- Memory-OS 只保留 prepare/preview/ack/apply_owner_action、domain ledgers、cron 领域规格与 capability report schema。
- 切换按“宿主接管 → 双读/影子对账 → 一个完整 monitor 周期 legacy_calls=0 → 删除 legacy → CI 上锁”执行，不做大爆炸替换。
- guard 使用 AST/调用语义加窄范围 literal checks；不要全局禁止普通 `subprocess`。

验收：static poison → public contract tests → owner digest render dry-run → full local gates。

建议提交：`refactor(memory): move owner delivery transport to hermes host adapter`

### S0.5 Owner ingress 真实闭环

目标：owner 在正常外部通信通道回复 token，由 Hermes agent 理解并调用结构化 tool；Memory-OS 只处理动作。`pre_gateway_dispatch` 必须保持未注册，避免底座抢占上层对话。

步骤：

1. host onboarding/capability dry-run，保存脱敏报告；确认 agent 可见 `memory_os_review_reply`。
2. 外部审查与 owner 授权后，仅对必要的宿主能力执行 apply。
3. monitor 验证 structured tool 正常、`pre_gateway_dispatch` 未注册、safety-only `pre_tool_call` 仍阻断 terminal/execute_code 旁路、污染硬零。
4. 创建一条专用、可回滚的 permanent promotion 测试提案。
5. owner 在真实主通道回复 approve token；验证 proposal/token/action/permanent 账本链与 delivery acknowledgement。
6. 验证非永久事项没有产生 owner review item。

停止信号：错误通道、fallback parsing、`pre_gateway_dispatch` 被注册、重复动作、任何自动永久晋升、任何 nonpromotion delivery 均立即停止并回滚本次 host capability 变更。

建议提交：如仅部署/证据则不制造代码提交；需要 host adapter 修复时独立提交。

## 5. Stage V2-E · Clearance receipts

开工条件：S0.1-S0.5 全绿。S0 前只允许新增本地 RED fixture/设计，不允许翻旗。

任务顺序：

1. E1 pair source：eligible candidate/provisional × active permanent，复用现有 judge。
2. E2 receipt journal/snapshot：三态、watermark、checked entities、judge version、幂等键。
3. E3 invalidation：`changed_entity_set` 覆盖 add/update/supersede/retire/revoke；相关变更同时使旧 clear/conflict receipt 失效；无法归实体时 conservative full。
4. E4 bounded rejudge：oldest-first、预算耗尽保持 unknown。
5. E5 producer wiring：仅 clear 创建普通 proposal；conflict→contested；unknown→retry。
6. E6 `run_clearance_cycle(now)`：幂等、零调度、零发送、结构化报告。
7. E7 flag flip：automatic 与 owner initiated 均无 unknown bypass；supersession 留给 V2-B 明示协议。
8. E8 monitor/live：失效数、队列深度、oldest age；不产生 owner item。

每项先实现 spec 的 E.1-E.8/X.4 poison，再写最小 GREEN。每个任务独立提交。

## 6. Stage V2-A · Exposure telemetry

1. canonical record id 归因闭合。
2. 裸 append 写点加锁并注册。
3. 先按 record id 对跨 lane pre-budget 集合 union/dedup，再按 `selected > dropped_by_budget > dropped_by_rank` 做唯一分类与守恒对账。
4. 证明 exposure 不提升 maturity/eligibility。
5. 测量 prefetch p50/p95；超预算 fail-open。

验收：A.1-A.4、X.3、`eligible == selected + dropped_by_budget + dropped_by_rank`，且集合无交集。

## 7. Stage V2-B · Dossier 与 owner 体验

1. dossier 富化，缺失字段显式 unavailable。
2. owner_assertion 快道仍需 clear；conflict 只能产生显式 supersession proposal。
3. supersession 使用 operation_id 与 reconcile，证明 crash 后全成或全不成。
4. rejected resurrection 使用真实 evidence increment 谓词。
5. 双路径 stability 与 absorption audit。
6. Hermes 提供 `channel_attestation`；Memory-OS 只做 policy 判定与 receipt 绑定，不解析通道。
7. 敏感度矩阵覆盖 allow/summary-only/forbidden-permanent；认证凭据、密钥/access token、OTP 与证件号/账户号等高风险第三方身份标识在资格门直接拒绝，monitor/stdout 禁正文。
8. 真实通道 dossier→approve 冒烟。

验收：B.1-B.10、F.1-F.4、X.7，加 supersession crash/reconcile 与 attestation expiry poison。

## 8. 每阶段统一验收与发布

本地：

1. focused tests，保存 RED 与 GREEN 命令/结果。
2. 全量 pytest，不带 `-x`，不改测试来迁就实现。
3. static hygiene、write-surface、import-cycle 项目闸。
4. `git diff --check`、秘密/生成物/无关文件审计。

集成与 live：

1. 隔离副本/安装布局 smoke。
2. 外部审查通过后才 apply。
3. 生产备份后部署，记录版本与回滚点。
4. full live monitor 连续 3 个计划周期 PASS；用户可操作能力还必须经过真实通道。
5. 每项证据显式标为 local / integration / live / monitor / architecture PASS。

Git：

- 每任务只提交自身文件；保留用户已有 dirty/untracked 文件。
- 用户明确要求前不 push、不 apply、不重启。
- 推送前核对 ignore 与 staged 内容；GitHub 是唯一同步通道。
