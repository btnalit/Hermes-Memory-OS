# Memory-OS 模块地图

审计日期: 2026-06-04

Historical first-round audit baseline: `1ed4ef414f9d4a46eb363cbc09e4964622508938`

Current P0 deployed baseline: `799b69d25d4d679e2d38a6d97e2f31c3f361db01`

说明: 本文按工程职责划分模块，不按 Python package 物理目录逐行罗列。状态以当前 HEAD 和 live/read-only 证据为准；README、install help、monitor 或 live 证据不一致处单独标注为 drift。

## 1. 顶层目录职责

| 路径 | 职责 | 审计判断 |
| --- | --- | --- |
| `agent/` | Hermes Agent OS 集成、plugin entry、provider 注册 | host-facing glue，不应承载 Memory-OS 治理状态机 |
| `plugins/memory/memory_os/` | Memory-OS 核心 runtime、provider、gates、projection、owner action | 核心系统边界 |
| `plugins/modules/` | portable cognition/context/evidence/expression/governance/messaging modules | 通过 cognitive loop 或 scripts 调用，写面需受 gate 管理 |
| `plugins/memory-os-agent-os/` | Agent OS sidecar/plugin metadata | 插件化安装适配层 |
| `scripts/` | install、deploy、monitor、cron onboarding、gate runner、helper jobs | live 闭环和 ops 入口，风险较高 |
| `tests/` | unit/integration/system tests | 当前相关定向测试 PASS |
| `docs/internal-memory-os/` | 内部规划和证据文档 | 被 `.gitignore` 忽略，不进入 GitHub main |

## 2. 核心运行层

| 模块 | 主要入口 | 读 | 写 | Gate | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| `__init__.py` | `MemoryOSProvider.initialize/prefetch/sync_turn/system_prompt_block` | config, store, index, memory sources | summary event queue | provider boundary | live 使用中 |
| `runtime.py` | `MemoryOSRuntime.heartbeat` | events, working, candidates, index | working/candidates/index, heartbeat evidence | ExecutionGate `runtime_heartbeat_core` | live 使用中 |
| `cognitive_loop.py` | `CognitiveLoopRunner.run_once` | module artifacts, system state | cognitive reports, module outputs | step-level ExecutionGate | live 使用中 |
| `execution_gate.py` | `start_execution_gate_envelope`, `resolve_execution_gate_permit`, `complete_execution_gate_envelope` | envelope ledger | envelope ledger | 自身为执行许可原语 | live 使用中 |
| `structural_write_gate.py` | `append_governed_jsonl` | permit resolver | governed JSONL append | ExecutionGate permit hard input | live 使用中 |
| `cron_registry.py` | registry snapshot helpers | cron specs | registry snapshot | cron onboarding | live 使用中，已支持 profile/subset |
| `hermes_cron_adapter.py` | Hermes cron discovery/update | Hermes host cron surface | Hermes cron config | host adapter | live 使用中 |
| `deployment_runtime_manifest.py` | manifest helpers | deploy env | deployment manifest | deploy wrapper | live 使用中 |
| `host_capability_probe.py` | host probe | Hermes layout/capabilities | capability report | cognitive loop | live 使用中 |

## 3. 记忆和检索层

| 模块 | 主要职责 | 风险 |
| --- | --- | --- |
| `store.py` | file-first memory store primitives | 中，所有状态落盘基础 |
| `index.py` | Memory-OS index/retrieval support | 中，影响 recall |
| `roots.py` | profile/platform path resolution | 中，部署和数据路径基础 |
| `config.py` | Memory-OS config | 中，边界和路径配置 |
| `context_router.py` | context route hints | 中，影响 prefetch |
| `prefetch.py` | context preparation | 中，影响 host prompt context |
| `low_clue_recall.py` | low clue recall support | 低中 |
| `memory_sources.py` | memory source evidence | 低中 |
| `session_mirror.py` | bounded session mirror apply | 中高，当前已毕业为自动写 lane |
| `task_anchor.py` | active task anchor | 低中 |
| `system_state.py` | system state helpers | 中 |

## 4. 投影和左脑治理层

| 模块 | 主要入口 | 输出 | 边界 |
| --- | --- | --- | --- |
| `signal_source_registry.py` | source registry | source inventory | metadata-only source 定义 |
| `signal_collectors.py` | collector functions | normalized signals | 不保存 raw body/secret |
| `memory_projection.py` | `collect_and_project_signals` | `memory_projections.jsonl`, summary, compaction | ExecutionGate + StructuralWriteGate |
| `left_brain_advisor.py` | `run_left_brain_advisor` | advisor report/findings | owner-visible, no direct apply |
| `metadata_retention.py` | metadata retention/compaction | compacted metadata | retention policy |
| `hindsight.py` | governed Hindsight substrate/projection | shadow/active substrate evidence | 不拥有 Hindsight store 写入 |

当前 live 轻量证据:

| 环境 | projection_count | advisor_reports | latest_findings | Hindsight curation findings |
| --- | ---: | ---: | ---: | ---: |
| 10.20.3.200 | 266 | 26 | 12 | 2 |
| 10.20.2.66 | 215 | 21 | 13 | 0 |

## 5. Owner governance 层

| 模块 | 主要职责 | 关键写面 | 边界 |
| --- | --- | --- | --- |
| `owner_actions.py` | owner action token、state transition、ledger | owner_actions, proposal, feedback, hindsight curation decisions | 高风险动作入口 |
| `approval.py` | approval helpers | approval artifacts | owner-approved only |
| `session_mirror.py` | owner-approved smoke 和 graduated auto apply | apply governance | bounded, append-only |
| `feedback.py` | owner feedback data | feedback ledger | 中 |
| `digests.py` | digest/render helpers | digest artifacts | user-visible channel adapter |

高风险 state transition:

- `approve_candidate`: 可写 crystallized，必须 owner-approved。
- `revoke/demote/delete`: 不可逆或高风险，只能 owner。
- `apply_proposal`: 会改变运行策略或状态，必须按 proposal kind 分层。
- `allow_speak_once`: 对外发送边界，必须 owner。
- `approve_session_mirror_apply`: 只批准 bounded SessionMirror token/scope。
- `retain/reject/demote_hindsight_curation`: 当前只写 Memory-OS decision ledger，不写 Hindsight store。

## 6. Portable modules

### Cognition

| 文件 | 类 | 入口 | 职责 |
| --- | --- | --- | --- |
| `plugins/modules/cognition/deep_reflection.py` | `DeepReflectionModule` | `run_once/status/doctor` | deep reflection evidence |
| `plugins/modules/cognition/imagination_loop.py` | `ImaginationLoopModule` | `run_once/status/doctor` | imagination loop |
| `plugins/modules/cognition/inner_drive.py` | `InnerDriveRuntimeModule` | `run_once/status/doctor` | inner drive runtime |
| `plugins/modules/cognition/wandering_mind.py` | `WanderingMindModule` | `run_once/status/doctor` | non-task right-brain cadence |

### Context

| 文件 | 类 | 入口 | 职责 |
| --- | --- | --- | --- |
| `plugins/modules/context/abstraction_distillation.py` | `AbstractionDistillationModule` | `distill/status/doctor` | abstraction distillation |
| `plugins/modules/context/digest_consolidation.py` | `DigestConsolidationModule` | `status/doctor` | digest consolidation |
| `plugins/modules/context/household_digest.py` | `HouseholdDigestModule` | `status/doctor` | household digest |
| `plugins/modules/context/symbolic_offloader.py` | `SymbolicOffloaderModule` | `status/doctor` | symbolic offload |

### Evidence

| 文件 | 类 | 入口 | 职责 |
| --- | --- | --- | --- |
| `plugins/modules/evidence/confabulation.py` | `ConfabulationDetectorModule` | `run_once/status/doctor` | confabulation detection |
| `plugins/modules/evidence/scoring.py` | `EvidenceScoringModule` | `status/doctor` | feature/evidence scoring |

### Expression

| 文件 | 类 | 入口 | 职责 |
| --- | --- | --- | --- |
| `plugins/modules/expression/expression_draft.py` | `ExpressionDraftModule` | `status/doctor` | expression draft |
| `plugins/modules/expression/grounded_expression_judge.py` | `GroundedExpressionJudge` | `run_once/status/doctor` | grounded expression and left-brain map |
| `plugins/modules/expression/speak_gate.py` | `SpeakGateModule` | `status/doctor` | speak gate, should not bypass owner boundary |

### Governance

| 文件 | 类 | 入口 | 职责 |
| --- | --- | --- | --- |
| `plugins/modules/governance/candidate_review.py` | `CandidateReviewModule`, `FeaturePreRouter` | `status/doctor` | candidate review |
| `plugins/modules/governance/cascade_routing_policy.py` | `CascadeRoutingPolicyModule` | `status/doctor` | cascade route policy shadow |
| `plugins/modules/governance/confidence_router.py` | `ConfidenceRouterModule` | `status/doctor` | confidence routing |
| `plugins/modules/governance/crystallized_revalidator.py` | `CrystallizedRevalidatorModule` | `evaluate/run_once/status/doctor` | crystallized revalidation |
| `plugins/modules/governance/feedback_bridge.py` | `GovernanceFeedbackBridgeModule` | `run_once/status/doctor` | feedback bridge |
| `plugins/modules/governance/ground_truth_miner.py` | `GroundTruthMinerModule` | `run_once/status/doctor` | reversible labels |
| `plugins/modules/governance/judge_calibration.py` | `JudgeCalibrationMonitor` | `evaluate/status/doctor` | judge calibration |
| `plugins/modules/governance/live_guard.py` | `LiveGuardRegistry` | registry | live guard rules |
| `plugins/modules/governance/migration_controller.py` | `MigrationControllerModule` | `evaluate/status/doctor` | migration governance |
| `plugins/modules/governance/ops_gate.py` | `OpsGateModule` | `run_once/status/doctor` | proposal ops-gate, not runtime ExecutionGate |
| `plugins/modules/governance/pipeline_checker.py` | `LeftBrainPipelineCheckModule` | `run_once/status/doctor` | legacy left-brain pipeline check |
| `plugins/modules/governance/proposal_queue.py` | `ProposalQueueModule` | `status/doctor` | proposal queue |
| `plugins/modules/governance/provisional.py` | `ProvisionalModule` | `status/doctor` | provisional governance |
| `plugins/modules/governance/self_evolution.py` | `SelfEvolutionGovernorModule` | `run_once/status/doctor` | self evolution governor |
| `plugins/modules/governance/shadow_recall.py` | `ShadowRecallModule` | `status/doctor` | shadow recall |

### Messaging

| 文件 | 类 | 入口 | 职责 |
| --- | --- | --- | --- |
| `plugins/modules/messaging/mailbox.py` | `MailboxNoSendModule` | `status/doctor` | mailbox observation/no-send boundary |

## 7. Script 和运维入口

| 脚本 | 职责 | 风险 |
| --- | --- | --- |
| `scripts/install_memory_os.sh` | safe install/provider/module/cron enable | 高，安装边界 |
| `scripts/deploy_memory_os.py` | local/remote deploy with preflight/dry-run/apply/postcheck | 高，live 变更 |
| `scripts/memory_os_3_200_monitor.py` | production/clean-host monitor | 高，闭环证据来源 |
| `scripts/memory_os_owner_cron_onboarding.py` | Hermes cron onboarding | 高，调度边界 |
| `scripts/memory_os_execution_gate_runner.py` | per-cron ExecutionGate wrapper | 高，自动执行入口 |
| `scripts/write_surface_check.py` | direct write surface classifier | 中高，写面边界 |
| `scripts/static_hygiene.py` | repo static hygiene | 中 |
| `scripts/memory_os_owner_review_digest.py` | owner digest helper | 中高，owner-visible surface |
| `scripts/memory_os_owner_review_gate.py` | owner review gate helper | 中高 |
| `scripts/memory_os_proposal_followups_opsgate.py` | proposal follow-up ops-gate | 中 |
| `scripts/memory_os_right_brain*.py` | right-brain digest/prompt helpers | 中 |
| `scripts/memory_os_module_cadence.py` | module cadence helper | 中 |
| `scripts/memory_os_feedback_prompt.py` | feedback prompt helper | 中 |

## 8. 当前工程状态摘要

稳定基线:

- GitHub/local/remote HEAD: `799b69d25d4d679e2d38a6d97e2f31c3f361db01`。
- 10.20.3.200 和 10.20.2.66 均对齐该 HEAD。
- 10.20.3.200 live monitor PASS，`WARN=[]`，`FAIL=[]`。
- 10.20.2.66 clean-host monitor WARN，`FAIL=[]`。
- 双机 fast cron probe PASS: active registry=2, enabled Memory-OS jobs=2,
  optional outside active registry=0。

当前 drift:

- 默认 cron profile 已收敛到 `active-closure`，README/install help、onboarding、
  monitor 和 live enabled-state 已与 2-job active registry 对齐。

## 9. 模块化判断

模块划分总体是健康的:

- provider 层和 host 边界分离清楚。
- ExecutionGate 和 StructuralWriteGate 已经成为真正 runtime 原语，而不是散落 helper 里的日志。
- projection/advisor 层没有直接接管 Hindsight 或外部发送。
- portable modules 大多通过 cognitive loop 进入系统，而不是各自隐式写生产状态。

需要继续收敛的地方:

- `ops_gate.py` 和 `execution_gate.py` 名称容易混淆，应在 docs/tests 中持续强调前者是 proposal OpsGate，后者是 runtime ExecutionGate。
- cron profile 需要单一 source of truth，不能 README、onboarding、monitor、install help 各说一套。
- reversible labels 的 owner-action refresh 已有定向测试覆盖，但还需要持续观察 live label renewal。
- ignored internal docs 如果继续作为治理事实来源，需要有可导出的 release evidence 或 tracked summary。
