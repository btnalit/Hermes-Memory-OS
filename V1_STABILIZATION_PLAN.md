# Memory-OS V1 稳定化计划

日期: 2026-06-05

当前 V1 基线: `be9e4077996ef04c84bbef6b9ee24a266fd4cbc1`

当前状态:

- local tests/static gates: PASS
- 10.20.3.200 fast probes: PASS
- 10.20.3.200 full live monitor: FAIL, `index_not_healthy_in_production`
- 10.20.2.66 clean-host monitor: WARN, `FAIL=[]`

## 1. V1 目标

V1 的目标不是继续开新 authority lane，而是把已经打开的 Memory-OS 自运营闭环变成可维护、可部署、可观测、可回归的稳定产品基线。

V1 成功标准:

- 3.200 production live monitor PASS，`WARN=[]` 或 WARN 均有明确生产可接受分类。
- 2.66 clean-host monitor WARN 且 `FAIL=[]`，所有 WARN 都是安装/空环境兼容分类。
- fast probe 和 full monitor 的证据等级清楚，不混用。
- active-closure cron registry、实际 enabled jobs、wrapper/envelope 覆盖一致。
- import-cycle check 持续 `cycle_count=0`。
- write surface check 持续 `unclassified_count=0`。
- public checkout probe 能证明 required files、private docs filtering、核心 import-smoke。
- JSONL/state IO、host profile、error record 逐步收敛到统一 contract。

非目标:

- 不开启 58 高风险 authority lane。
- 不把 Hindsight curation 直接应用到 Hindsight store。
- 不自动写 crystallized memory。
- 不接管 Hermes host scheduler/transport。
- 不继续为了降行数机械拆文件。
- 不用 local tests 或 fast probe 代替 3.200 full live monitor。

## 2. 当前阻塞

### BLOCKER: 3.200 production index health 当前红灯

证据:

```text
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
FAIL: index_not_healthy_in_production
WARN: index_not_healthy, doctor_warning_finding
```

判断:

- 这不是代码本地测试问题，full pytest 已 PASS。
- 这不是 cron wrapper 或永久边界问题，fast probes 已 PASS。
- 这是 production monitor 层的 index freshness / doctor health 问题。

V1 进入下一批功能闭环前，必须先处理或明确分类这个红灯。

## 3. 阶段顺序

### V1-0: 基线冻结与文档同步

优先级: P1

目的:

防止后续 Codex 任务继续沿用旧 baseline / 旧 production PASS 证据。

动作:

1. 将 tracked baseline 文档更新为 `be9e4077996ef04c84bbef6b9ee24a266fd4cbc1`。
2. 明确 local PASS、fast probe PASS、live monitor FAIL 的差异。
3. 保留 internal ignored docs 作为辅助证据，但不能让它们覆盖当前 live monitor。

验收:

```text
rg -n "<stale-baseline-patterns>" TECH_DEBT_REPORT.md V1_STABILIZATION_PLAN.md
git diff --check
```

关闭条件:

- 旧基线和旧 PASS 口径不再出现在 tracked V1 docs。

### V1-1: Production index catch-up contract

优先级: P1

问题:

3.200 fast probes 通过，但 full live monitor FAIL `index_not_healthy_in_production`。当前系统缺少“部署后 index/doctor 何时必须恢复健康”的明确合同。

动作:

1. 定义 index catch-up 规则:
   - deploy/apply 后等待哪些 heartbeat 或 index sync 事件。
   - 最大等待时长。
   - stale 的 WARN/FAIL 分界。
   - clean-host 与 production 的不同分类。
2. 增加或扩展 index probe:
   - 输出 `state`, `age_seconds`, `last_index_ts`, `last_event_ts`, `doctor_findings`。
   - 可被 deploy postcheck 和 monitor 复用。
3. monitor 分类必须保守:
   - production stale 仍 FAIL，除非有明确 bounded catch-up 状态和时间预算。
   - clean-host 空环境可 WARN，但必须分类。
4. 3.200 跑一次真实 full monitor 验收。

验收:

```text
python -m pytest -q tests\scripts\test_memory_os_3_200_monitor.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output summary
```

关闭条件:

- 3.200 live monitor PASS，或 production index stale 仍 FAIL 但有明确根因和下一个修复任务。
- 不允许用禁用 index check、删除 evidence、暂停必要 cron 的方式关闭。

### V1-2: Fast probe 与 full monitor 证据分层

优先级: P1/P2

问题:

fast cron/boundary probes 能快速证明局部 gate，但不能证明完整生产健康。当前 runbook 和脚本缺少统一证据等级。

动作:

1. 给 fast probes 增加远端调用 ergonomics:
   - 支持 `--host hermes-media/hermes-feiniu`；或
   - 在 deploy wrapper 中提供统一远端 probe 命令。
2. deploy/audit output 标注:
   - `fast_probe_pass`
   - `live_monitor_pass`
   - `clean_host_warn`
3. 对 full monitor 增加性能预算:
   - production target <= 180s。
   - clean-host target <= 240s。
   - timeout 单独分类为 monitor performance debt。

验收:

```text
python scripts\memory_os_cron_adapter_probe.py --host hermes-media --output json
python scripts\memory_os_boundary_runtime_probe.py --host hermes-media --output json
python scripts\memory_os_cron_adapter_probe.py --host hermes-feiniu --output json
python scripts\memory_os_boundary_runtime_probe.py --host hermes-feiniu --output json
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
```

若不实现 `--host`，必须在 runbook 中给出等价 SSH wrapper，并由测试或 docs check 覆盖。

### V1-3: Public checkout import-smoke

优先级: P1/P2

问题:

当前 public checkout probe PASS 只证明 public/private 文件筛选，不证明 clean checkout 能导入核心模块。

动作:

1. 扩展 `scripts/memory_os_public_checkout_probe.py`。
2. 增加 import-smoke targets:
   - `plugins.memory.memory_os.owner_actions`
   - `plugins.memory.memory_os.session_mirror`
   - `plugins.memory.memory_os.execution_gate`
   - `scripts.memory_os_3_200_monitor`
   - neutral monitor entrypoint
3. 输出 schema 增加:
   - `import_smoke_ok`
   - `import_smoke_failures`
4. 失败时 public checkout probe 必须 FAIL，而不是只在 pytest 中发现。

验收:

```text
python -m pytest -q tests\scripts\test_memory_os_public_checkout_probe.py
python scripts\memory_os_public_checkout_probe.py --source head --strict
python scripts\memory_os_public_checkout_probe.py --source working-tree --strict
```

### V1-4: JSONL/state IO contract 收敛

优先级: P2

问题:

当前 `_read_jsonl/_append_jsonl/_write_state` 等 helper 分散，错误语义不一致。

动作:

1. 定义 `jsonl_io` / `state_io` contract:
   - read with malformed handling。
   - append with parent creation。
   - atomic JSON write。
   - latest record。
   - quarantine / error record。
2. 先迁移 report-only modules。
3. 再迁移 low-risk lanes。
4. 最后迁移 owner ledger / SessionMirror / proposal queue 等关键写面。
5. write surface check 适配共享 writer，不降低 `unclassified_count=0` 防线。

验收:

```text
python -m pytest -q tests\scripts\test_memory_os_write_surface_check.py
python scripts\memory_os_write_surface_check.py
python -m pytest -q tests\plugins\memory tests\system_modularization
```

关闭条件:

- 重复 IO helper 数量下降。
- malformed JSONL 行为有 fixture 测试。
- critical write path 迁移前后有回归测试。

### V1-5: Exception/error observability contract

优先级: P2

问题:

当前 broad `except Exception` 有 67 处，silent pass 有 5 处。容错需要保留，但不能静默吞掉 live path 错误。

动作:

1. 定义 `error_record` schema:
   - `component`
   - `operation`
   - `error_code`
   - `severity`
   - `recoverable`
   - `path`
   - `ts`
2. runtime/projection/session_mirror/prefetch 先接入。
3. monitor 增加:
   - `suppressed_error_count`
   - `recent_error_codes`
   - `live_write_error_count`
4. 禁止 live write path 出现 silent pass。

验收:

```text
python -m pytest -q tests\plugins\memory tests\scripts\test_memory_os_3_200_monitor.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
```

### V1-6: Host runtime profile / capability probe

优先级: P2

问题:

路径、host、Hermes home、active-closure 默认散落在 monitor、installer、cron、CLI 中。

动作:

1. 定义 `HostRuntimeProfile`:
   - host alias。
   - repo root。
   - hermes home。
   - hermes binary。
   - monitor profile。
   - clean-host vs production mode。
2. 将 monitor、deploy、cron onboarding、fast probes 的默认值收敛到同一 resolver。
3. 保留现有 CLI 参数作为 override。
4. 输出 profile source，避免隐藏默认值。

验收:

```text
python -m pytest -q tests\scripts\test_memory_os_3_200_monitor.py tests\scripts\test_memory_os_owner_cron_onboarding.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output summary
```

### V1-7: God module 小切片收敛，不做机械拆分

优先级: P2/P3

问题:

`owner_actions.py`、`memory_os_3_200_monitor.py`、`cli.py` 仍然过大，但上次过度拆分已经带来风险。

原则:

- 不以行数为目标。
- 不改外部入口。
- 不做跨层抽象。
- 只提取已经有多个调用方或真实变化点的 seam。

候选小切片:

1. monitor remote probe runner。
2. monitor classifier table / reason catalog。
3. owner review read-only surface reader。
4. owner ledger append/read helper。
5. CLI host/profile resolver。

验收:

```text
python -m pytest -q
python scripts\memory_os_import_cycle_check.py --repo-root .
python scripts\memory_os_write_surface_check.py
python scripts\memory_os_static_hygiene_check.py
```

### V1-8: Owner burden budget

优先级: P2

问题:

owner review pending 规模偏大，FYI/review_suggested 容易把“关键人工边界”重新变成流程噪音。

动作:

1. 定义 digest budget:
   - `action_required` cap。
   - FYI cap。
   - 同 source 聚合。
   - stale item retention。
2. monitor 增加 owner burden trend:
   - pending total。
   - action_required count。
   - FYI/review_suggested count。
   - stale count。
3. 不降低永久边界:
   - route/score。
   - external send。
   - identity/relationship。
   - crystallized write/revoke/demote/delete。

验收:

```text
python -m pytest -q tests\plugins\memory\test_memory_os_owner_actions.py tests\scripts\test_memory_os_3_200_monitor.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
```

## 4. Codex 任务拆分

### P1-001: 修复或分类 3.200 index health 红灯

目标:

让 3.200 full live monitor 不再在 `index_not_healthy_in_production` 上无解释失败。

验收:

- 3.200 live monitor PASS；或
- 保持 FAIL，但输出根因、catch-up window、下一修复点，且文档不再宣称 PASS。

### P1-002: public checkout import-smoke

目标:

让 GitHub/public checkout probe 能发现 clean checkout import regression。

验收:

- public checkout probe schema 增加 import-smoke 字段。
- head/working-tree strict 均 PASS。

### P1-003: fast probe 远端 ergonomics

目标:

不再要求人工手写 SSH 命令跑 cron/boundary fast probes。

验收:

- `--host` 可用，或 deploy wrapper 提供等价命令。
- 双机 probe PASS。

### P2-004: JSONL/state IO contract 第一批迁移

目标:

降低重复 helper 和错误语义分裂。

验收:

- report-only modules 迁移。
- write surface PASS。
- malformed fixture PASS。

### P2-005: error_record 第一批接入

目标:

让 broad exception 降级变成可观测事件。

验收:

- runtime/projection/session_mirror 至少一条路径接入。
- monitor 输出 suppressed/degraded error counters。

### P2-006: HostRuntimeProfile

目标:

收敛 3.200/2.66/root/hermes-home/defaults。

验收:

- monitor/deploy/probe 输出 profile source。
- 现有 CLI 参数兼容。

### P2-007: owner burden budget

目标:

降低 owner digest 噪音，不改变永久人工边界。

验收:

- monitor 输出 owner burden trend。
- digest 同 source 聚合有测试。

## 5. V1 总验收

V1 总验收命令:

```text
python -m pytest -q
python scripts\memory_os_static_hygiene_check.py
python scripts\memory_os_import_cycle_check.py --repo-root .
python scripts\memory_os_write_surface_check.py
python scripts\memory_os_public_checkout_probe.py --source head --strict
python scripts\memory_os_public_checkout_probe.py --source working-tree --strict
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output summary
```

V1 不能关闭的情况:

- 3.200 production monitor 仍 FAIL 且无明确 root cause / catch-up contract。
- public checkout probe 不能证明 import-smoke。
- write surface 出现 unclassified write。
- import cycle count > 0。
- 永久边界 counters 出现越权。
- owner digest budget 通过丢弃 high-risk action_required 实现。

## 6. 当前不要做

- 不开启 58。
- 不自动 apply Hindsight retain/reject/demote。
- 不自动写 crystallized memory。
- 不为了通过 monitor 而 pause active-closure 必要 cron。
- 不大拆 owner/monitor。
- 不把 2.66 clean-host WARN 当成 3.200 production PASS。
