# Memory-OS 技术债与稳定性审计报告

审计日期: 2026-06-04

Task start code baseline: `dd2b07b788dba4b4dcee3a51189c8d1f32040424`

Current P0 deployed baseline: `64a00bcb06cee85f0cac1fcb5bf813dd2eece2bf`

审计范围:

- 重复实现
- 循环依赖
- 异常处理
- 配置混乱
- 日志缺口
- 测试缺口
- 硬编码
- 脆弱调用链
- AI 快速迭代留下的架构漂移

## 1. 当前证据

| 检查 | 结果 |
| --- | --- |
| targeted stability tests | `301 passed` |
| full pytest | `988 passed` |
| static hygiene | PASS |
| write surface check | PASS, `surface_count=99`, `unclassified_count=0` |
| 10.20.3.200 live monitor | PASS, `WARN=[]`, `FAIL=[]` |
| 10.20.2.66 clean-host monitor | WARN, `FAIL=[]` |
| 10.20.3.200 cron registry | active-closure 2 jobs |
| 10.20.3.200 legacy optional cron jobs | paused |
| 10.20.2.66 cron registry | active-closure 2 jobs |
| 10.20.2.66 legacy optional cron jobs | paused by active-closure onboarding |
| fast cron probe on both hosts | `status=ok`, active registry=2, enabled Memory-OS jobs=2, optional outside registry=0 |
| fast boundary/runtime probe | live `status=ok` on both hosts |

结论: 当前代码基线不是红灯。V1 风险主要来自维护性、配置漂移和 monitor 漏报，而不是已观察到的越权写或测试失败。

## 2. 高优先级发现

### TD-001: Clean-host enabled optional cron jobs 已修复，保留 fast-probe 任务

严重度: Closed / follow-up P1 for fast probe budget

证据:

- 10.20.2.66 曾经 `memory_os_cron_registry.json` 只有 active-closure 两项:
  - `owner_review_digest`
  - `proposal_followups_opsgate`
- 但 `/root/.hermes/cron/jobs.json` 里 7 个 Memory-OS cron jobs 仍全部 `enabled=True`。
- monitor 当时仍返回 clean-host WARN 且 `FAIL=[]`，并给出 `execution_gate_memory_os_cron_wrapped_ok expected=2 wrapped=2`。

修复:

- `hermes_cron_adapter.py` / monitor 已增加:
  - `active_registry_job_count`
  - `enabled_memory_os_job_count`
  - `enabled_known_optional_outside_active_registry_count`
  - `enabled_known_optional_outside_active_registry_jobs`
- production live profile 对 known optional outside active registry 升级为
  FAIL；clean-host profile 给出分类 WARN。
- `10.20.2.66` 已运行 active-closure onboarding，known optional
  Memory-OS jobs 被非破坏性 pause，而不是删除。
- 双机 fast cron probe 均返回 `status=ok`，`enabled_known_optional_outside_active_registry_count=0`。

剩余影响:

- full monitor 仍偏重，不适合作为每个小切片的唯一闭环。
- 需要把 fast cron probe 和 boundary/runtime probe 固化为 deploy/audit
  前置小探针。

后续建议:

- 继续使用 `memory_os_cron_adapter_probe.py` 作为 fast cron probe。
- 使用 `memory_os_boundary_runtime_probe.py` 作为 fast boundary/runtime probe，
  覆盖永久边界计数和 gate health。
- 为 full monitor 定义性能预算和超时处理规则。

### TD-002: 核心治理链存在循环依赖

严重度: P1

证据:

AST import graph 检出一个核心循环:

```text
left_brain_advisor
-> memory_projection
-> signal_collectors
-> owner_actions
-> session_mirror
-> owner_actions
```

具体导入点:

- `left_brain_advisor.py:12` imports `memory_projection_records_path`
- `memory_projection.py:12` imports `collect_signal_sources`
- `signal_collectors.py:12` imports `owner_actions_path`
- `signal_collectors.py:14` imports `session_mirror_apply_records_path`
- `session_mirror.py:104` and `session_mirror.py:1024` import `read_owner_action_records`
- `owner_actions.py:3467`, `3575`, `6974` import SessionMirror/LeftBrain read helpers

影响:

- 当前通过函数内延迟 import 维持可运行，但模块边界已经互相穿透。
- 后续拆分 owner action、projection 或 Hindsight curation 时，容易出现 import-time 崩溃、fixture 顺序依赖或隐藏 side effect。

建议:

- 把 path helpers/read-only projections 移到中立 read model 模块。
- 禁止 `owner_actions` 直接依赖 advisor/projection/session_mirror 的实现类。
- 增加 import-cycle test。

### TD-003: `owner_actions.py` 和 `memory_os_3_200_monitor.py` 是明显 god module

严重度: P1

证据:

| 文件 | 行数 | 典型职责 |
| --- | ---: | --- |
| `plugins/memory/memory_os/owner_actions.py` | 6730 | token parsing、owner surface、state transition、feedback、proposal apply、Hindsight curation、policy writes、render helpers |
| `scripts/memory_os_3_200_monitor.py` | 6353 | SSH probe、remote script、snapshot build、所有 classifier、summary render、profile-specific policy |

其中:

- `memory_os_3_200_monitor.py::_remote_probe_script` 约 2458 行。
- `memory_os_3_200_monitor.py::classify_snapshot` 约 1888 行。
- `owner_actions.py::_apply_state_transition` 约 179 行，但周围依赖大量同文件私有 helper。

影响:

- 每次治理边界变更都要修改巨型文件，review 成本高。
- 监控分类和远程采集耦合，导致小 monitor 规则变更也可能影响 SSH probe 或 summary。
- owner action 的读模型、渲染、写 ledger、状态机混在一起，增加误触高风险边界的概率。

建议:

- `owner_actions` 拆成 parser、surface/read model、state transitions、ledger writers、policy apply adapters。
- monitor 拆成 remote probe、snapshot schema、classifiers、summary renderer。
- 每次拆分保持行为测试不变，先搬移再改逻辑。

## 3. 中优先级发现

### TD-004: JSONL 和状态文件 helper 重复实现

严重度: P2

证据:

AST 扫描显示:

- `_read_jsonl` 约 30 个定义。
- `_append_jsonl` 约 22 个定义。
- `_write_jsonl` 约 9 个定义。
- `_timestamp`、`_stable_id`、`_false_boundary`、`_clip`、`_dedupe` 等也分散实现。

影响:

- malformed JSONL、空行、权限错误、atomic write、quarantine 策略不一致。
- write surface check 已能分类 direct append，但没有统一写入语义。

建议:

- 新增或收敛到 `plugins.memory.memory_os.jsonl` / `storage` utility。
- 公共 helper 支持 append、read、latest、atomic write、quarantine、bounded read。
- 先迁移低风险 report-only modules，再迁移 owner/state-critical surfaces。

### TD-005: broad `except Exception` 数量偏高

严重度: P2

证据:

AST 扫描检出 69 处 broad exception handler，集中在:

- `runtime.py`
- `prefetch.py`
- `session_mirror.py`
- `low_clue_recall.py`
- `owner_actions.py`
- `memory_os_3_200_monitor.py`
- `shadow_journal.py`

影响:

- 有些地方会降级为 report-only 或继续运行，这是正确的容错方向。
- 但没有统一错误码、审计路径和 monitor classification，会把真实数据损坏变成不可见降级。

建议:

- 给 runtime/projection/session_mirror/prefetch 建统一 `error_record` schema。
- 禁止 silent `except Exception: pass` 出现在 live state write path。
- monitor 统计 `suppressed_error_count` 和最近错误码。

### TD-006: write surface allowlist 过于字符串化

严重度: P2

证据:

`scripts/memory_os_write_surface_check.py` 用大量形如:

```text
file::function::append_jsonl_call::expression
```

的字符串作为 allowlist key。

影响:

- 小型重命名、提取函数或表达式改写会导致 allowlist 失效。
- 开发者可能为通过检查而新增分类，而不是先理解写面风险。

建议:

- 保留当前检查作为防线。
- 增加稳定 `write_surface_id` 注解或 registry，使重构不必改一大串 AST 表达式 key。
- high-risk writer 必须关联 ExecutionGate/OwnerGate/StructuralWriteGate 之一。

### TD-007: 配置默认值分散

严重度: P2

证据:

同一类默认值分布在:

- `scripts/install_memory_os.sh`
- `scripts/install_memory_os_plugin.py`
- `scripts/memory_os_owner_cron_onboarding.py`
- `scripts/deploy_memory_os.py`
- README / quickstart / configuration docs

例子:

- `owner_cron_profile=active-closure`
- heartbeat/cognitive-loop interval
- LLM judge preset
- Hindsight mode
- owner channel / deliver defaults

影响:

- 这次 cron profile 已经出现过代码、README、dashboard、live evidence 不同频的问题。
- 之后加 V1 install profile 或 production preset 时，容易再次漂移。

建议:

- 建立 `install_profile.schema.json` 或 Python `InstallProfile` 数据源。
- shell installer 只负责参数解析和调用 Python profile resolver。
- deploy wrapper 显式支持 `--owner-cron-profile`，即使默认仍为 active-closure。

### TD-008: monitor 仍是 3.200 命名和 `/root/.hermes` 假设

严重度: P2

证据:

- 脚本名仍是 `memory_os_3_200_monitor.py`。
- embedded remote probe 中硬编码 `/root/.hermes`。
- README 和 docs 里仍以 `hermes-media` 为示例 host。

影响:

- 作为 production monitor 已经承担 3.200 和 2.66 双 profile，但命名和路径仍是历史 host 口径。
- 后续第三台 host 或非 root Hermes home 会增加分支逻辑。

建议:

- 保留兼容入口，新增中性入口 `memory_os_monitor.py`。
- remote probe 接收 hermes_home/profile 参数，不在 embedded script 内写死。
- 把 probe output schema 固定，summary renderer 不直接依赖 host 名。

### TD-008A: full monitor 过重，缺少分层 fast probe

严重度: P1/P2

证据:

- 3.200 full monitor 可运行并返回 PASS，但耗时约两分钟。
- 2.66 clean-host full monitor 曾出现超时，后续复跑 WARN/FAIL=[]。
- 当前 cron enabled-state 已可用 `memory_os_cron_adapter_probe.py` 快速证明。
- 当前 permanent boundary counters 和 Gate 基础健康可用
  `memory_os_boundary_runtime_probe.py` 快速证明。

影响:

- 每个 scheduler/cron/doc 口径修复都跑 full monitor 会拖慢审计。
- full monitor 超时可能被误读为运行时失败，而不是监控自身性能债。

建议:

1. 保留 full monitor 作为最终 live/clean-host 证据。
2. fast cron probe 用于部署后第一层 cron/registry/wrapper 检查，并在
   `deploy_memory_os.py` postcheck/apply 序列中运行。
3. fast boundary/runtime probe 用于 permanent boundary counters 和
   Gate health 检查，并在 `deploy_memory_os.py` postcheck/apply 序列中运行。
4. 在 deploy/runbook 中写明哪些任务必须升级到 full monitor。

性能预算:

- fast probes: seconds-scale first pass;
- production full monitor: target <= 180s;
- clean-host full monitor: target <= 240s;
- full monitor timeout is classified as monitor-performance debt unless the
  fast probes show an actual cron/runtime boundary failure.

### TD-009: cognitive loop 是固定顺序巨链，缺少 step registry 合同

严重度: P2

证据:

`CognitiveLoopRunner._step_functions` 固定列出 29 个步骤。`_run_step` 对每步 broad catch 后继续，报告 step status。

影响:

- 这保证了“一个步骤失败不拖垮整轮”，方向正确。
- 但新增/删除步骤没有声明依赖、required/optional、profile 条件、freshness 期望。
- 之前已出现 report bounded 截断尾部 step 的证据缺口。

建议:

- 引入 `CognitiveStepSpec`，字段包括 `required`, `profile`, `depends_on`, `failure_policy`, `monitor_code`。
- monitor required steps 从 registry 派生，不靠散落常量。

### TD-010: CLI/script 输出和日志风格不统一

严重度: P3

证据:

- 多数 scripts 直接 `print(json.dumps(...))`。
- prompts 也通过 print 输出 human-facing text。
- systemd/cron helper、monitor、installer 对 stdout/stderr 的语义不完全一致。

影响:

- Cron agent mode、local mode、monitor JSON mode 混用时，错误边界不够统一。
- 后续自动部署收集日志时，需要逐脚本适配。

建议:

- 定义 script output contract:
  - JSON report mode
  - owner message mode
  - silent/no-op mode
  - agent prompt mode
- 每个 helper 明确输出 channel 和 schema。

## 4. 低优先级和结构漂移

### TD-011: 旧概念与新概念并存

严重度: P3

例子:

- `OpsGateModule` 与 runtime `ExecutionGate` 名称相似但职责不同。
- `LeftBrainPipelineCheckModule` 与 `LeftBrainAdvisor` 并存。
- `V7/L4/53/54-58` 文档阶段名和代码模块名交叉。
- 10.20.2.88 原型名、3.200 live host 名和产品化 Memory-OS 名并存。

影响:

- 新维护者容易误把 report-only OpsGate 当 ExecutionGate。
- 文档审计时容易把历史证据当当前 closure。

建议:

- 在 V1 docs 中维护一张 glossary。
- 所有 monitor summary 使用当前产品名，历史 lane 只放到 evidence section。

### TD-012: internal docs 被 ignore，tracked 文档和本地证据容易分叉

严重度: P3

证据:

- `docs/internal-memory-os/` 被 `.gitignore` 忽略。
- 第一轮审计产物当前也是 untracked。

影响:

- GitHub main 无法完整复现闭环证据。
- 跨 session 审计需要重新查本地 ignored 文档。

建议:

- V1 前至少保留 tracked summary:
  - current architecture baseline
  - current risk register
  - current live evidence pointer

### TD-013: 2.66 缺 pytest 仍是 ops 验证债

严重度: P3

影响:

- 2.66 clean-host 只能用 deploy script、cognitive-loop、monitor smoke 闭合。
- 无法在目标环境跑同一组 targeted tests。

建议:

- 提供 portable minimal test runner 或 pinned venv cache。
- 不强制污染系统 Python。

## 5. 没有发现的高风险问题

本轮未发现:

- 自动写 crystallized 长期记忆。
- Hindsight store 真实 retain/reject/demote apply。
- route/score authority 打开。
- identity/relationship 写入。
- 外部消息自动发送。
- 未分类 write surface。
- 当前本地测试失败。
- 3.200 live monitor FAIL。

## 6. 总体判断

Memory-OS 当前功能闭环已经比较完整，V1 最大问题不是“缺门禁”，而是“门禁和证据长得太快，核心实现开始变成大文件和互相引用的网”。

V1 稳定化应该优先做三件事:

1. 修 monitor 漏口，尤其是 enabled optional cron outside active registry。
2. 拆核心循环依赖和巨型 owner/monitor 文件。
3. 把 JSONL、配置默认值、错误记录收敛成共享 contract。
