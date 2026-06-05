# Memory-OS 技术债与稳定性审计报告

审计日期: 2026-06-05

当前审计基线: `be9e4077996ef04c84bbef6b9ee24a266fd4cbc1`

本轮状态:

- 本地 checkout: `main...origin/main [behind 1]`
- 未跟踪目录: `design_handoff_memory_os_monitor/`，本轮未触碰
- 10.20.3.200 `/opt/Hermes-Memory-OS`: 已回退到同一 commit
- 10.20.2.66 `/opt/Hermes-Memory-OS`: 已回退到同一 commit
- 本轮未提交、未推送、未重启 gateway

## 审计锚点

```text
source_of_truth:
  current git HEAD, TECH_DEBT_REPORT.md, V1_STABILIZATION_PLAN.md,
  scripts/memory_os_3_200_monitor.py live/clean-host output,
  import-cycle/write-surface/static-hygiene checks
finding_type:
  stability debt, monitor/live drift, config debt, test/release gap
owning_seam:
  monitor, scheduler/cron, execution/write gate, public checkout release gate,
  JSONL/state IO, host capability/config
reverse_scope:
  stay inside Memory-OS plugin/adapter surfaces; do not take over Hermes host scheduler
equivalent_contract_or_project_contract:
  active-closure cron registry, ExecutionGate envelope, StructuralWriteGate,
  monitor PASS/WARN/FAIL classifier, public checkout probe
evidence_loop:
  local tests/static gates + remote fast probes + remote full monitor
monitor_or_validation_fields:
  import cycle count, write surface count, public checkout probe fields,
  cron registry counts, boundary counters, index health, projection freshness
promotion_signal:
  3.200 live monitor PASS and 2.66 clean-host WARN with FAIL=[] after fixes
stop_or_rollback_signal:
  production monitor FAIL, unclassified write surface, import cycle regression,
  high-risk boundary counter > 0
external_review:
  required before live apply/restart/high-risk lane; not required for this docs-only audit
```

## 1. 当前证据

| 检查 | 当前结果 |
| --- | --- |
| Git HEAD | `be9e4077996ef04c84bbef6b9ee24a266fd4cbc1` |
| focused stability tests | `127 passed` |
| full pytest | `1004 passed` |
| static hygiene | PASS |
| import cycle check | PASS, `cycle_count=0`, `module_count=92` |
| write surface check | PASS, `surface_count=98`, `unclassified_count=0` |
| public checkout probe, `head --strict` | PASS, but no import-smoke coverage |
| public checkout probe, `working-tree --strict` | PASS, but no import-smoke coverage |
| 10.20.3.200 fast cron probe | OK, active registry=2, enabled Memory-OS jobs=2, naked=0 |
| 10.20.3.200 fast boundary/runtime probe | OK, permanent boundary counters safe |
| 10.20.3.200 live monitor | FAIL: `index_not_healthy_in_production`; WARN includes `index_not_healthy`, `doctor_warning_finding` |
| 10.20.2.66 fast cron probe | OK, active registry=2, enabled Memory-OS jobs=2, naked=0 |
| 10.20.2.66 fast boundary/runtime probe | OK, permanent boundary counters safe |
| 10.20.2.66 clean-host monitor | WARN, `FAIL=[]`; warnings are classified clean-host gaps |

结论:

当前代码本地质量门是绿的，执行门禁和写面门禁在 fast probe 层是绿的，但生产 3.200 full monitor 不是绿灯。V1 不能再沿用旧的 production PASS 口径；当前必须把 `index_not_healthy_in_production` 当作 V1 首要稳定性风险。

## 2. P1 发现

### TD-001: 3.200 生产 monitor 当前 FAIL，fast probe 与 full monitor 存在证据落差

严重度: P1

证据:

- 3.200 fast cron probe: `status=ok`，active registry=2，enabled Memory-OS jobs=2，naked jobs=0。
- 3.200 fast boundary/runtime probe: `status=ok`，永久边界计数未越权。
- 3.200 full live monitor: FAIL `index_not_healthy_in_production`，index health state 为 `stale`，doctor finding 包含 `index_stale`。

影响:

- deploy/postcheck/fast probe 可以证明 cron、ExecutionGate、边界计数没有明显破口，但不能证明完整生产健康。
- 如果后续只用 fast probe 作为上线闭环，会漏掉 index freshness / doctor health 这类慢路径问题。
- 当前生产基线不能标记为 overall PASS。

建议:

- 增加 post-deploy index catch-up contract: 定义 heartbeat 等待窗口、最大等待时长、失败分类、重跑 monitor 的固定流程。
- 将 index freshness 从“偶发 monitor 红灯”变成有明确输入输出的 probe 或 monitor subcheck。
- 修复前，所有 V1 文档必须写明 3.200 full monitor 当前 FAIL。

### TD-002: 文档和事实基线漂移

严重度: P1

证据:

- 旧版 `TECH_DEBT_REPORT.md` / `V1_STABILIZATION_PLAN.md` 仍写上一轮 baseline。
- 旧版证据仍把 3.200 production monitor 写成 PASS。
- 当前回退基线是 `be9e4077996ef04c84bbef6b9ee24a266fd4cbc1`，full tests 为 `1004 passed`，3.200 monitor 当前 FAIL。

影响:

- Codex 后续任务会错误地从“生产绿灯”出发，导致继续开新 lane 或做低优先级重构。
- 旧文档会掩盖当前 3.200 index stale 风险。

建议:

- tracked/public-safe 文档必须以当前 commit 和当前 monitor 输出为准。
- internal ignored docs 只能作为辅助证据，不能覆盖当前 live monitor。

### TD-003: public checkout probe 缺少 import-smoke，发布门只能证明文件筛选，不能证明可导入

严重度: P1/P2

证据:

- `scripts/memory_os_public_checkout_probe.py --source head --strict` PASS。
- `scripts/memory_os_public_checkout_probe.py --source working-tree --strict` PASS。
- 输出只覆盖 public docs allowlist、required public files、private docs absent；没有验证核心模块 import。

影响:

- 之前已经回退过“拆分太多导致风险”的状态；仅凭 checkout probe PASS 无法证明 clean checkout 可导入 owner/monitor/neutral entrypoint。
- GitHub main 的发布安全仍依赖本地全量 pytest，而不是 public checkout 自身契约。

建议:

- 给 public checkout probe 增加 import-smoke:
  - `plugins.memory.memory_os.owner_actions`
  - `plugins.memory.memory_os.session_mirror`
  - `scripts.memory_os_3_200_monitor`
  - neutral monitor entrypoint
- import-smoke 必须在 head 和 working-tree 两种 source 下都可运行或明确 skip 分类。

### TD-004: 生产健康闭环缺少“快探针 -> full monitor”的分层合同

严重度: P1/P2

证据:

- 本轮 remote fast probes 两台都 OK。
- 3.200 full monitor 仍 FAIL。
- 2.66 clean-host full monitor WARN 且 `FAIL=[]`。

影响:

- fast probe 适合秒级发现 cron/gate 破口；full monitor 负责生产健康。
- 当前 runbook 容易把二者混用，导致 fast probe 绿灯被误读为 live PASS。

建议:

- 固化证据等级:
  - fast probe PASS: cron/gate/boundary 局部 PASS。
  - full monitor PASS: live health PASS。
  - clean-host WARN: 安装兼容状态，不代表 production PASS。
- deploy/audit 脚本输出必须显式标注证据等级。

## 3. P2 发现

### TD-005: God module 仍是主要维护性风险，但不应再次机械拆分

严重度: P2

证据:

| 文件 | 当前行数 | 风险 |
| --- | ---: | --- |
| `plugins/memory/memory_os/owner_actions.py` | 7280 | owner digest、token/ledger、state transition、proposal、Hindsight curation、read helpers 混合 |
| `scripts/memory_os_3_200_monitor.py` | 6684 | SSH probe、snapshot、classifier、summary、profile policy 混合 |
| `plugins/memory/memory_os/cli.py` | 3323 | CLI parser、dispatch、diagnostics、host defaults 混合 |
| `plugins/modules/cognition/deep_reflection.py` | 1779 | module logic 与 persistence/report 交织 |
| `plugins/memory/memory_os/signal_collectors.py` | 1399 | source collection、projection shaping、host assumptions 交织 |

影响:

- 真实风险不只是“文件大”，而是多个边界在一个文件里共享私有 helper。
- 大拆分已经证明容易引入新断点；继续按行数拆会伤害闭环。

建议:

- 暂停机械拆分。
- 只允许围绕真实契约做小提取:
  - monitor: remote probe runner、classifier table、summary renderer。
  - owner actions: read-only surface reader、ledger writer、state transition adapter。
- 每次提取必须保持旧 CLI/API 入口兼容，并用 full tests + import-cycle check 证明。

### TD-006: JSONL/state helper 重复实现，错误语义不一致

严重度: P2

证据:

AST 扫描:

```text
_read_jsonl      27
_append_jsonl    20
_write_jsonl      7
_read_json        3
_write_json       2
_write_state     10
_timestamp        7
_stable_id        7
_clip            10
_false_boundary   5
```

影响:

- malformed JSONL、partial write、empty line、permissions、atomic write、quarantine 语义会随模块不同而不同。
- write surface check 可以防“未分类写面”，但不能统一“写入失败应该如何降级、如何记账、如何监控”。

建议:

- 以 `jsonl_io` / `state_io` contract 做逐步迁移。
- 先迁移 report-only/read-only surfaces；owner ledger、session mirror、proposal queue 等关键写面最后迁移。
- 迁移时保留 StructuralWriteGate 分类能力。

### TD-007: broad exception 偏多，错误可观测性不足

严重度: P2

证据:

AST 扫描:

```text
BROAD_EXCEPTION_TOTAL 67
BARE_EXCEPTION_TOTAL 0
SILENT_PASS_TOTAL 5
```

集中位置:

```text
plugins/memory/memory_os/cli.py                         10
plugins/memory/memory_os/low_clue_recall.py              9
plugins/memory/memory_os/prefetch.py                     6
plugins/memory/memory_os/cleanup.py                      5
plugins/memory/memory_os/runtime.py                      4
plugins/memory/memory_os/shadow_journal.py               4
plugins/modules/cognition/deep_reflection.py             4
plugins/memory/memory_os/owner_actions.py                3
plugins/memory/memory_os/session_mirror.py               3
plugins/memory/memory_os/cron_mirror.py                  3
```

影响:

- 容错本身是对的，但如果错误只被吞掉或局部降级，monitor 无法区分“正常无数据”和“读写失败”。
- 对自运营系统来说，静默降级会制造“看似闭环，实际少跑了一段”的风险。

建议:

- 建统一 `error_record` schema: `component`, `operation`, `error_code`, `severity`, `recoverable`, `path`, `ts`。
- monitor 增加 suppressed/degraded error counters。
- live write path 禁止 silent `except Exception: pass`。

### TD-008: 配置和路径硬编码仍然偏重

严重度: P2

证据:

```text
HARDCODE_ROOT_TOTAL      56
  scripts/memory_os_3_200_monitor.py  51
HARDCODE_OPT_TOTAL        1
HOST_REF_TOTAL            7
ACTIVE_CLOSURE_TOTAL     10
HERMES_HOME_REF_TOTAL    67
```

另外，本地直接运行 fast probes 时不支持 `--host`:

```text
memory_os_cron_adapter_probe.py: error: unrecognized arguments: --host hermes-media
memory_os_boundary_runtime_probe.py: error: unrecognized arguments: --host hermes-media
```

影响:

- 3.200/2.66/clean-host 口径容易散落在脚本默认值和 monitor 分类里。
- Hermes 升级或 host layout 变化时，Memory-OS 需要改多处硬编码。
- fast probe 需要手写 SSH 包装，不如 full monitor 一样可用 `--host`。

建议:

- 建 `HostRuntimeProfile` / `HostCapabilityProbe` 作为配置入口。
- fast probes 支持 `--host`、`--remote-repo-root` 或由 deploy wrapper 统一调用。
- 保留 `/root/.hermes` 默认，但必须显示来源和 override。

### TD-009: owner-review backlog 和 digest 噪音风险仍需预算化

严重度: P2

证据:

3.200 monitor 输出中 owner review pending 规模较大，示例包括:

- pending owner review 总量约 414。
- `action_required` 约 3。
- `fyi` / `review_suggested` 占大头。

影响:

- 当前系统目标是减少人工盯流程，只保留关键边界。
- 如果 FYI/review_suggested 长期堆积，owner digest 会重新变成噪音队列。

建议:

- 定义 owner burden budget:
  - action_required 上限。
  - FYI 每周期 cap。
  - 同 source 聚合。
  - stale review item retention。
- monitor 输出 owner burden trend，而不是只看 pending 总数。

### TD-010: clean-host 与 production 的验收语义仍需分离

严重度: P2

证据:

- 2.66 clean-host monitor 本轮为 WARN 且 `FAIL=[]`。
- WARN 包含 `memory_projection_stale_after_deploy`、optional component absent、feedback volume pending 等。

影响:

- clean-host WARN 是兼容性证据，不是生产健康证据。
- 如果文档把 2.66 WARN 当成“功能已闭环”，会误导后续上线判断。

建议:

- 所有报告都写清:
  - 3.200 live PASS/FAIL = 生产闭环。
  - 2.66 clean-host WARN/FAIL = 安装/兼容闭环。
- clean-host WARN 必须分类，但不应阻止 production 方向的修复优先级。

### TD-011: prototype / host 命名泄漏，插件化边界仍需收敛

严重度: P2/P3

证据:

- `scripts/memory_os_3_200_monitor.py` 以 host 编号命名。
- 代码和脚本中仍有 `hermes-media`、`10.20`、`prototype_aligned_score` 等 host/prototype 词汇。

影响:

- Memory-OS 作为 Hermes plugin 的可迁移性下降。
- 新 host 或 Hermes 升级时，适配成本不透明。

建议:

- 保留兼容 entrypoint，不做破坏性重命名。
- 新增 neutral entrypoint / profile naming，并逐步把 docs/runbook 改成 neutral profile。

### TD-012: write surface allowlist 仍然字符串化

严重度: P2/P3

证据:

- `memory_os_write_surface_check.py` 当前 PASS，`surface_count=98`，`unclassified_count=0`。
- allowlist 以 file/function/expression 风格定位 direct append/write。

影响:

- 小型重命名或表达式改写会造成噪音。
- 开发者可能为了过 gate 添加 allowlist，而不是先明确风险等级和补偿语义。

建议:

- 保留现有 gate。
- 增加 risk class / contract tag 元数据，让 allowlist 从字符串豁免升级为写面合同。

## 4. 已关闭或当前健康的风险

### Import cycle

当前状态: PASS

证据:

```text
python scripts\memory_os_import_cycle_check.py --repo-root .
status=pass cycle_count=0 module_count=92
```

说明:

- 旧文档中“核心循环依赖”不能再作为当前 open bug。
- 仍要保留 regression gate，防止下一轮小提取重新引入循环。

### StructuralWriteGate / direct write surface

当前状态: PASS

证据:

```text
python scripts\memory_os_write_surface_check.py
status=pass surface_count=98 unclassified_count=0
```

说明:

- 当前未观察到未分类 direct JSONL append。
- 该 gate 不能替代错误语义、owner boundary 或 production monitor。

### 永久边界 fast probe

当前状态: fast probe OK

证据:

- 双机 `memory_os_boundary_runtime_probe.py` 远端执行均 `status=ok`。
- route/score、identity、external send、unapproved crystallized 等永久边界计数未越权。

说明:

- 这是局部边界证据，不等于 3.200 full live monitor PASS。

## 5. 不建议做的事

- 不继续机械拆 `owner_actions.py` 或 `memory_os_3_200_monitor.py`。
- 不为了让 monitor 变绿而删除、pause 或绕过生产 cron。
- 不把 fast probe PASS 写成 live monitor PASS。
- 不开启 58 高风险 authority lane。
- 不在没有 live smoke 的情况下宣称生产闭环已恢复。
- 不在本轮审计里重启 gateway 或修改远端状态。

## 6. 建议修复顺序

1. P1: 处理 3.200 `index_not_healthy_in_production`，建立 index catch-up contract。
2. P1: 修正文档基线，确保所有 tracked baseline 指向 `be9e407...` 和当前 monitor 事实。
3. P1/P2: public checkout probe 增加 import-smoke。
4. P1/P2: 固化 fast probe 与 full monitor 的证据分层。
5. P2: fast probes 增加 `--host` 或统一远端 wrapper。
6. P2: JSONL/state IO contract 逐步迁移。
7. P2: broad exception 统一 error_record 与 monitor counters。
8. P2: HostRuntimeProfile / HostCapabilityProbe 收敛路径和 host 默认。
9. P2: owner burden budget 与 digest retention。
10. P3: neutral naming / prototype vocabulary cleanup。

## 7. 本轮审计运行命令

```text
git rev-parse HEAD
git status --short --branch
python -m pytest -q tests\scripts\test_memory_os_public_checkout_probe.py tests\scripts\test_memory_os_import_cycle_check.py tests\scripts\test_memory_os_write_surface_check.py tests\scripts\test_memory_os_3_200_monitor.py
python -m pytest -q
python scripts\memory_os_import_cycle_check.py --repo-root .
python scripts\memory_os_write_surface_check.py
python scripts\memory_os_static_hygiene_check.py
python scripts\memory_os_public_checkout_probe.py --source head --strict
python scripts\memory_os_public_checkout_probe.py --source working-tree --strict
python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output summary
```
