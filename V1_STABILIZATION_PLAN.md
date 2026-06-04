# Memory-OS V1 稳定化计划

日期: 2026-06-04

Task start code baseline: `dd2b07b788dba4b4dcee3a51189c8d1f32040424`

Current P0 deployed baseline: `64a00bcb06cee85f0cac1fcb5bf813dd2eece2bf`

## 1. V1 目标

V1 的目标不是继续开新 authority lane，而是把已经打开的自运营闭环变成可维护、可部署、可观测的稳定产品基线。

V1 成功标准:

- 生产 3.200 live monitor PASS。
- clean-host 2.66 monitor WARN 且 `FAIL=[]`，WARN 全部分类。
- active-closure cron registry、实际 enabled jobs、monitor 期望一致。
- 核心 Memory-OS 模块没有 import cycle。
- 高风险 owner action 状态机有清晰模块边界。
- monitor、installer、cron、projection 的配置默认值来自单一 contract。
- JSONL 写入和读取有共享工具和统一错误语义。

非目标:

- 不开启 58 高风险 authority lane。
- 不把 Hindsight curation 直接应用到 Hindsight store。
- 不自动写 crystallized memory。
- 不重写 Hermes scheduler/transport。
- 不做大而全的重构。每个切片都要可单独验证。

## 2. 阶段顺序

### V1-0: 基线冻结

目的: 防止稳定化过程中继续漂移。

动作:

- 把当前第二轮审计结果作为 V1 输入。
- 更新 tracked 或 release-visible 的 current baseline summary。
- 标记 internal ignored docs 只能作为辅助证据，不能单独作为 V1 source of truth。

验收:

```text
python -m pytest -q
python scripts\memory_os_static_hygiene_check.py
python scripts\memory_os_write_surface_check.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output json
```

### V1-1: Active-Closure Cron 一致性和 monitor 漏口

优先级: P1

当前状态: Closed at `64a00bcb06cee85f0cac1fcb5bf813dd2eece2bf`

问题:

- 2.66 曾经 registry 是 active-closure 2 jobs，但旧 optional jobs 仍 enabled。
- monitor 曾经只证明 active registry jobs wrapped，没有提示 enabled optional jobs outside active registry。

动作:

1. monitor 增加:
   - `enabled_known_optional_outside_active_registry_count`
   - `enabled_known_optional_outside_active_registry_jobs`
   - classification: production FAIL 或 WARN，clean-host WARN。
2. onboarding report 增加 paused optional job summary，并在 monitor 中读取最近一次 onboarding evidence。
3. 2.66 跑一次 active-closure onboarding apply，确认 optional jobs paused。
4. tests:
   - registry 2 + optional enabled => WARN/FAIL 分类。
   - registry 2 + optional paused => PASS。
   - full profile => 7 expected wrapped。

验收:

```text
python -m pytest -q tests\scripts\test_memory_os_3_200_monitor.py tests\scripts\test_memory_os_owner_cron_onboarding.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output json
```

关闭条件:

- 3.200 active-closure registry=2，optional paused。
- 2.66 optional paused，或 monitor 明确 WARN。

当前闭环证据:

```text
3.200 deployed_head=64a00bcb06cee85f0cac1fcb5bf813dd2eece2bf
3.200 cron_adapter_probe status=ok active_registry_job_count=2 enabled_memory_os_job_count=2 enabled_known_optional_outside_active_registry_count=0
3.200 monitor PASS WARN=[] FAIL=[]

2.66 deployed_head=64a00bcb06cee85f0cac1fcb5bf813dd2eece2bf
2.66 active-closure onboarding paused known optional Memory-OS jobs
2.66 cron_adapter_probe status=ok active_registry_job_count=2 enabled_memory_os_job_count=2 enabled_known_optional_outside_active_registry_count=0
2.66 clean-host monitor WARN FAIL=[]
```

### V1-1A: Fast Probe 和 monitor 性能预算

优先级: P1/P2

问题:

- full monitor 是最终证据，但运行偏重。
- scheduler/cron 小修应先用 fast probe 证明 registry/wrapper/enabled-state，再升级到 full monitor。

当前 fast probes:

```text
python scripts\memory_os_cron_adapter_probe.py --hermes-home /root/.hermes --hermes-bin hermes --output json
python scripts\memory_os_boundary_runtime_probe.py --hermes-home /root/.hermes --output json
```

动作:

1. 把 cron adapter probe 纳入 deploy/audit runbook 和
   `deploy_memory_os.py` postcheck/apply 序列。
2. 把 boundary/runtime probe 纳入 deploy/audit runbook 和
   `deploy_memory_os.py` postcheck/apply 序列:
   - permanent high-risk counters;
   - ExecutionGate basic health;
   - StructuralWriteGate basic health.
3. 为 full monitor 定义性能预算和超时分类:
   - fast probe: seconds-scale first pass;
   - production full monitor: target <= 180s;
   - clean-host full monitor: target <= 240s;
   - full monitor timeout is monitor-performance debt unless fast probes show
     cron/runtime boundary failure.

当前证据:

- `memory_os_cron_adapter_probe.py`: 3.200 / 2.66 均 `status=ok`。
- `memory_os_boundary_runtime_probe.py`: 3.200 / 2.66 均 `status=ok`。

验收:

```text
python scripts\memory_os_cron_adapter_probe.py --hermes-home /root/.hermes --hermes-bin hermes --output json
python scripts\memory_os_boundary_runtime_probe.py --hermes-home /root/.hermes --output json
python scripts\deploy_memory_os.py --phase postcheck --profile upgrade --mode operational --hindsight auto --hermes-home /root/.hermes --output json
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output summary
```

### V1-2: JSONL / state IO contract 收敛

优先级: P1/P2

问题:

- `_read_jsonl`、`_append_jsonl`、`_write_jsonl` 到处重复。
- malformed / partial write / empty line / quarantine 语义不一致。

动作:

1. 新增共享模块，例如 `plugins.memory.memory_os.jsonl_io`。
2. 提供:
   - `read_jsonl(path, *, limit=None, quarantine=False)`
   - `append_jsonl(path, record, *, ensure_parent=True)`
   - `write_json_atomic(path, data)`
   - `latest_jsonl_record(path)`
3. 先迁移 report-only modules。
4. 再迁移 owner/projection/session_mirror critical path。
5. write surface check 适配共享 writer，不降低分类能力。

验收:

```text
python -m pytest -q tests\scripts\test_memory_os_write_surface_check.py
python scripts\memory_os_write_surface_check.py
python -m pytest -q tests\plugins\memory tests\system_modularization
```

关闭条件:

- 重复 `_read_jsonl/_append_jsonl` 数量显著下降。
- malformed JSONL 处理有统一测试。

### V1-3: 拆核心 import cycle

优先级: P1

问题:

当前核心循环:

```text
owner_actions <-> session_mirror
owner_actions -> left_brain_advisor -> memory_projection -> signal_collectors -> owner_actions
```

动作:

1. 新建中立 read-model/path 模块:
   - `owner_action_read_model.py`
   - `session_mirror_contracts.py`
   - `projection_paths.py`
2. `signal_collectors` 只依赖 read model/path，不依赖完整 `owner_actions`。
3. `session_mirror` 只依赖 owner action read model，不依赖 owner action state machine。
4. `owner_actions` 不直接 import advisor/projection implementation，只读 neutral report reader。

验收:

```text
python -m pytest -q tests\plugins\memory\test_memory_os_owner_actions.py tests\plugins\memory\test_memory_os_session_mirror.py
python -m pytest -q tests\scripts\test_memory_os_3_200_monitor.py
```

新增检查:

```text
python scripts\memory_os_import_cycle_check.py
```

关闭条件:

- core Memory-OS package import cycle count = 0。
- 既有 owner action/session mirror/projection tests PASS。

### V1-4: Owner action 模块分层

优先级: P1/P2

问题:

`owner_actions.py` 同时承担 token parser、digest surface、state transition、policy apply、feedback、Hindsight decision、ledger writer。

动作:

按行为不变拆分:

| 新模块 | 职责 |
| --- | --- |
| `owner_action_tokens.py` | token parse/resolve |
| `owner_review_surface.py` | pending item/read model/digest anchors |
| `owner_action_state_machine.py` | state transitions |
| `owner_action_ledgers.py` | append/read ledgers |
| `owner_policy_apply.py` | memory sources/deep reflection/right-brain policy writes |
| `hindsight_curation_actions.py` | advisory decision ledger only |

验收:

```text
python -m pytest -q tests\plugins\memory\test_memory_os_owner_actions.py
python -m pytest -q tests\system_modularization\test_memory_os_agent_os_shell.py
python scripts\memory_os_write_surface_check.py
```

关闭条件:

- `owner_actions.py` 变成 facade 或低于 2500 行。
- 高风险 action 对应测试不减少。

### V1-5: Monitor 拆分

优先级: P2

问题:

`memory_os_3_200_monitor.py` 太大，remote probe、snapshot、classifier、summary、profile policy 全在一起。

动作:

拆为:

| 模块 | 职责 |
| --- | --- |
| `monitor_remote_probe.py` | SSH/local probe |
| `monitor_snapshot.py` | snapshot schema |
| `monitor_classifiers/` | owner, cron, projection, left-brain, v7, expression |
| `monitor_summary.py` | Chinese summary/render |
| `memory_os_monitor.py` | 新中性 CLI |

保留 `memory_os_3_200_monitor.py` 作为兼容 wrapper。

验收:

```text
python -m pytest -q tests\scripts\test_memory_os_3_200_monitor.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output json
```

关闭条件:

- 原 CLI 输出 schema 不变。
- remote probe 不再硬编码 `/root/.hermes`。

### V1-6: 配置默认值单一来源

优先级: P2

问题:

install/deploy/onboarding/docs 各自维护 profile 默认值。

动作:

1. 定义 `InstallProfile`:
   - mode
   - owner_cron_profile
   - llm_judge_preset
   - memory_sources_preset
   - deep_reflection_preset
   - hindsight_mode default
   - heartbeat/cognitive intervals
2. shell installer 调 Python resolver 输出 argv。
3. deploy wrapper 增加 `--owner-cron-profile`。
4. docs 从同一表生成或至少加 consistency test。

验收:

```text
python -m pytest -q tests\scripts\test_memory_os_plugin_install.py tests\scripts\test_memory_os_deploy.py
rg -n "seven-node|/ 7 jobs|seven Hermes" README.md docs scripts
```

关闭条件:

- 默认值不再在 4 个入口手写。
- operational/test-host/production-safe profile 有快照测试。

### V1-7: 异常处理和日志 contract

优先级: P2

问题:

69 处 broad exception handler。部分合理，部分缺少可观测错误码。

动作:

1. 定义 `MemoryOSErrorRecord`:
   - code
   - severity
   - component
   - operation
   - recoverable
   - details_bounded
2. runtime/prefetch/session_mirror/projection 用统一错误记录。
3. monitor 增加 suppressed/degraded error counters。
4. 禁止 live state write path silent pass。

验收:

```text
python -m pytest -q tests\plugins\memory tests\system_modularization
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json
```

关闭条件:

- broad exception 数量下降，剩余都有注释或 error record。

### V1-8: Cognitive loop step registry

优先级: P2/P3

动作:

- 引入 `CognitiveStepSpec`。
- required tail steps 从 registry 派生。
- 每个 step 声明 failure policy。
- monitor required steps 不再复制硬编码列表。

验收:

```text
python -m pytest -q tests\plugins\memory\test_memory_os_cognitive_loop*.py tests\scripts\test_memory_os_3_200_monitor.py
```

关闭条件:

- 新增/删除 step 必须改 registry 和测试，不能只改 list。

## 3. V1 放行门槛

V1 前必须满足:

```text
python -m pytest -q
python scripts\memory_os_static_hygiene_check.py
python scripts\memory_os_write_surface_check.py
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output json
```

并且:

- 3.200: PASS, `WARN=[]`, `FAIL=[]`
- 2.66: WARN allowed, `FAIL=[]`, all WARN classified
- import cycle count = 0 for core Memory-OS package
- enabled optional cron outside active registry count = 0 on production, classified on clean-host
- write surface unclassified count = 0

## 4. 风险控制

稳定化期间禁止:

- 开启 58 authority lanes。
- 扩大 Hindsight store 写权限。
- 增加 external send 自动化。
- 重启 Hermes gateway，除非用户单独授权。
- 用删除 cron jobs 代替 pause/disable。

每个切片必须保留 rollback:

- cron: full profile 可恢复 optional jobs。
- owner actions: ledger append-only，不改历史 token。
- monitor: 保留旧 CLI wrapper。
- JSONL IO: 分批迁移，write surface check 每步过。

## 5. 建议执行顺序

1. V1-1A fast probe / monitor 性能预算。
2. V1-2 JSONL IO contract。
3. V1-3 import cycle。
4. V1-4 owner action 分层。
5. V1-5 monitor 拆分。
6. V1-6 配置单一来源。
7. V1-7 异常/日志 contract。
8. V1-8 cognitive loop registry。

完成 V1-1 到 V1-3 后，再评估是否需要进入第三轮专项审计。
