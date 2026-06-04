# Memory-OS 风险登记册

审计日期: 2026-06-04

Historical first-round audit baseline: `1ed4ef414f9d4a46eb363cbc09e4964622508938`

Current P0 deployed baseline: `b4ae2c548f4440af00067a8b422bdcedd4a8dd25`

严重度定义:

- P0: 已造成生产越权、数据损坏、外部发送或安全事故。
- P1: 会阻塞下一阶段上线或让 live evidence 结论不可信。
- P2: 真实风险存在，但有边界、可回滚或尚未打开高风险面。
- P3: 工程卫生、文档漂移、可观测性或长期维护风险。

## 1. 风险总览

| ID | 严重度 | 状态 | 风险 |
| --- | --- | --- | --- |
| R-001 | P1 | Closed | 10.20.3.200 部署后 projection freshness 曾失败，复测已 PASS |
| R-002 | P1 | Closed | 10.20.2.66 clean-host monitor 曾超时，复测 WARN 且 `FAIL=[]` |
| R-003 | P1 | Closed | active-closure cron profile 代码、README/install、monitor 和 live enabled-state 已收敛 |
| R-004 | P2 | Watch | reversible label renewal 定向测试已 PASS，3.200 已有 active labels，继续观察 TTL/renewal |
| R-005 | P2 | Open | owner-review backlog 和 review_suggested 噪音可能影响真实治理负载 |
| R-006 | P2 | Open | Hindsight curation 容易被误读为已作用于 Hindsight store |
| R-007 | P2 | Open | proposal_followup_auto_route 仍停在 limited_auto |
| R-008 | P2 | Open | 自动执行和 projection ledger 增长，需要 retention 策略继续覆盖 |
| R-009 | P3 | Open | internal docs 被 `.gitignore` 忽略，代码和证据 source of truth 容易分叉 |
| R-010 | P3 | Open | 2.66 缺少 pytest，clean-host 远端验证弱于 3.200 |
| R-011 | P3 | Watch | metadata-only collectors 必须持续防 raw body/secret 泄露 |
| R-012 | P3 | Watch | 58 高风险 authority lane 尚未打开，但需防止误开 |
| R-013 | P2 | Watch | full monitor 过重；fast probes 已进入 deploy sequencing，仍需性能优化 |

## 2. 详细风险

### R-001: 3.200 部署后 projection freshness 曾失败

严重度: P1

状态: Closed

原始证据:

- 早先运行 3.200 live monitor 时出现 `FAIL: memory_projection_stale_after_deploy`。
- 当时 deploy manifest 晚于 latest projection，说明部署后 projection 尚未自然刷新。

复测证据:

- Historical evidence HEAD: `1ed4ef4`。
- Current P0 deployed HEAD: `b4ae2c548f4440af00067a8b422bdcedd4a8dd25`。
- `python scripts\memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output json`
- 结果: `PASS`，`WARN=[]`，`FAIL=[]`。
- monitor pass item: `memory_projection_online`，`fresh_after_deploy=true`，projection_count=304。
- deployment manifest: `deployed_at=2026-06-04T04:28:20Z`。
- latest projection: `created_at=2026-06-04T04:30:26Z`。

结论:

- 这是部署后自然 cognitive-loop/projection 尚未完成导致的时间窗口，不是 projection 链路断裂。

后续建议:

- deploy postcheck 文档应说明: 若刚部署后立刻 monitor，projection freshness 需要等待或触发一轮 cognitive-loop 后再判定。

### R-002: 2.66 clean-host monitor 曾超时

严重度: P1

状态: Closed

原始证据:

- 早先运行 2.66 clean-host monitor 超时，未取得有效 PASS/WARN/FAIL 结论。

复测证据:

- 当前 HEAD: `1ed4ef4`，远端 git clean。
- `python scripts\memory_os_3_200_monitor.py --host hermes-feiniu --monitor-profile clean-host --output json`
- 结果: `WARN`，`FAIL=[]`。
- WARN 均为 clean-host 分类项，包括 expression/context-router/feedback-volume/optional-component pending。
- monitor pass item: `memory_projection_online`，`fresh_after_deploy=true`，projection_count=233。
- deployment manifest: `deployed_at=2026-06-04T04:28:56Z`。
- latest projection: `created_at=2026-06-04T04:30:27Z`。

结论:

- 2.66 当前可作为 clean-host compatibility / monitor smoke 证据，但仍不能描述为生产 live closure host。

### R-003: active-closure cron profile 口径和 enabled-state 漂移

严重度: P1

状态: Closed

证据:

- `scripts/memory_os_owner_cron_onboarding.py` 支持 `--cron-profile active-closure|full`，默认 `active-closure`。
- README、installer help、onboarding、monitor、tests 已统一为 active-closure 默认 2 个必需 job；`full` profile 保留 7 个 optional-capable job。
- 3.200 与 2.66 当前均已部署 `b4ae2c548f4440af00067a8b422bdcedd4a8dd25`。
- 3.200 active registry=2，enabled Memory-OS jobs=2。
- 2.66 active-closure onboarding 已暂停 known optional Memory-OS jobs，enabled Memory-OS jobs=2。
- 双机 `memory_os_cron_adapter_probe.py` 均为 `status=ok` 且 `enabled_known_optional_outside_active_registry_count=0`。

已避免的影响:

- 用户和审计者不再需要从 7-job 旧口径推断默认安装。
- monitor expected set 从 active registry/live scheduled set 派生。

关闭条件:

- README、install script、onboarding、monitor 和 tests 对默认 profile 与 full profile 口径一致。
- 3.200 和 2.66 都能证明 Memory-OS-owned cron jobs 通过 gate wrapper。
- known optional jobs 在 active-closure 下被 paused 或 monitor-classified。

后续:

- 保留 R-013，继续处理 full monitor 性能和 fast probe 分层。

### R-004: reversible label renewal 和 TTL 继续观察

严重度: P2

状态: Watch

证据:

- HEAD `1ed4ef4` 继承 ground truth miner renewal 修复。
- 本地定向测试覆盖 `test_ground_truth_miner_refreshes_expired_label_from_new_owner_action` 并 PASS。
- 当前本地相关定向测试总结果: `177 passed`。
- 3.200 当前已观察到 active reversible labels。
- 2.66 clean-host 没有 label 输入，label count 为 0，符合角色预期。

影响:

- 代码和 fixture 层已闭合，但 live label renewal 仍需要真实 owner-action 流量观察。

建议动作:

1. 在 3.200 观察一次 expired label 被新 owner action 合法刷新。
2. monitor 增加 label renewal 计数或最近 renewal 证据。

关闭条件:

- live evidence 出现合法 renewal。
- monitor 能区分 new label、renewed label、retracted label、expired label。

### R-005: owner-review backlog 和 digest 噪音

严重度: P2

状态: Watch

证据:

- 3.200 owner-review surface 显示 pending 量级较高，review_suggested 和 FYI overflow 存在。
- cap 和 FYI 聚合已经存在，但 backlog 本身仍存在。

影响:

- 虽然系统不增加人工审批边界，但 owner digest 噪音过多会让关键审批被埋没。
- 低风险 lane 毕业节奏可能被 backlog 干扰。

建议动作:

1. 为 owner digest 增加 backlog health 指标。
2. 区分 `approval_required`、`review_suggested`、`FYI aggregated`。
3. 对 low-risk informational findings 设 retention/aging 策略。

关闭条件:

- monitor 能显示 owner burden 指标。
- digest 中关键审批和 FYI 聚合分层清晰。

### R-006: Hindsight curation 容易被误读为已作用于 Hindsight store

严重度: P2

状态: Open

证据:

- 57-B 支持 `retain/reject/demote_hindsight_curation` owner-gated 决策。
- 代码边界是 `actual_hindsight_write=false` 和 `actual_hindsight_delete=false`。
- 当前只是 Memory-OS governance decision ledger。

影响:

- 用户可能以为 Hindsight 已被真实清理或降级。
- 后续若接 Hindsight store apply，容易跳过 owner-gated 高风险设计。

建议动作:

1. owner digest 和 evidence 文档持续标注 advisory-only。
2. Hindsight store apply 必须另开 lane，且 owner-gated。
3. monitor 增加 `hindsight_actual_write_count` 应始终为 0，直到明确开启。

关闭条件:

- 文档、monitor、owner digest 均清楚区分 suggestion、decision ledger、actual store mutation。

### R-007: proposal_followup_auto_route 仍停在 limited_auto

严重度: P2

状态: Open

证据:

- 当前规划保留 proposal_followup_auto_route 为 `limited_auto`。
- full_auto 仍等待真实样本量、Wilson 下界和 kind coverage。

影响:

- 自动化负载收敛还没有完成。
- 但该边界保守是合理的，不构成越权。

建议动作:

1. 继续采集 eligible proposal 和 owner agreement。
2. 样本量和 coverage 达标后再 graduation。
3. graduation 前保持 owner-visible evidence。

关闭条件:

- 达成既定样本阈值和 Wilson/kind coverage。
- limited_auto 到 full_auto 的 promotion 有 live evidence 和 rollback signal。

### R-008: 自动执行和 projection ledger 增长

严重度: P2

状态: Open

证据:

- 10.20.3.200 projection_count=304。
- 10.20.2.66 projection_count=233。
- projection 有 compaction/retention 逻辑，但所有 ledgers 的留存策略需要持续验证。

影响:

- 长期运行后文件增长会影响 monitor、digest、startup、scan 成本。
- 历史审计证据不可直接删除，只能 archive/compact。

建议动作:

1. 建立 ledger retention map。
2. 对 high-volume skip/no-op envelope 做聚合保留。
3. monitor 增加 ledger size 和 compaction health。

关闭条件:

- 每个高频 ledger 都有 retention 或 archive 策略。
- monitor 能对超阈值文件给出 WARN。

### R-009: internal docs 被 `.gitignore` 忽略

严重度: P3

状态: Open

证据:

- `docs/internal-memory-os/` 文档本地更新，但不进入 GitHub tracked commit。
- 多个 closure/evidence 事实只存在本地内部文档中。

影响:

- GitHub main 无法完整复现治理决策历史。
- 跨会话或跨机器可能出现 code/evidence drift。

建议动作:

1. 保留 internal docs 作为本地工作日志。
2. 为每个重要 closure 生成 tracked summary 或 release evidence digest。
3. deploy manifest 中记录 closure doc hash 或 evidence snapshot。

关闭条件:

- 代码仓库中有可追溯的 tracked architecture/evidence summary。

### R-010: 2.66 缺少 pytest

严重度: P3

状态: Open

证据:

- 2.66 远端验证多次依赖 deploy script、cognitive-loop、clean-host monitor。
- 系统 Python 无 pytest。

影响:

- clean-host 无法直接复跑完整 targeted suite。
- 本地和 2.66 环境差异可能被延后发现。

建议动作:

1. 不强制在 2.66 装全量开发依赖，避免污染。
2. 提供 hermetic test runner 或 portable venv/cache。
3. 至少保证 focused smoke 能跑。

关闭条件:

- 2.66 能运行项目定义的最小 clean-host test bundle，或文档明确替代证据边界。

### R-011: metadata-only collectors 的 raw body/secret 边界

严重度: P3

状态: Watch

证据:

- 当前 live monitor 对 projection boundary 和 payload coverage 已通过。
- 53/55 以后 source 数量增长到 26，未来继续扩展时风险增加。

影响:

- 新 collector 可能误把消息正文、secret、token、私密配置投影进 Memory-OS。

建议动作:

1. collector schema 中强制 `metadata_only=true` 和 disallowed field scan。
2. monitor 保留 raw body/secret/boundary true scan。
3. 新 source 必须带 fixture test。

关闭条件:

- 每个 source 有 schema fixture。
- live monitor 持续证明 raw body/secret projection 为 0。

### R-012: 58 高风险 authority lane 防误开

严重度: P3

状态: Watch

证据:

- 用户已明确 58 暂不开。
- 当前高风险面仍关闭。

影响:

- 后续工程推进中如果把 route/score、identity、crystallized auto write、Hindsight store mutation 混入低风险 lane，会破坏治理边界。

建议动作:

1. 在 roadmap 和 monitor 中保留 58 disabled assertion。
2. 新 lane 必须标 risk class 和 owner boundary。
3. 任何 authority write 都需要单独 owner-gated plan。

关闭条件:

- 58 前置审计完成，所有 P1/P2 open risk 收敛。

### R-013: full monitor 过重，需要 fast probe 和性能预算

严重度: P2

状态: Open

证据:

- 3.200 full monitor 可返回 PASS，但耗时约两分钟。
- 2.66 full monitor 曾出现超时，后续 clean-host monitor 复跑 WARN/FAIL=[]。
- cron enabled-state 已可用 `memory_os_cron_adapter_probe.py` 快速证明。
- permanent boundary counters 和 Gate 基础健康已可用
  `memory_os_boundary_runtime_probe.py` 快速证明；双机 live probe
  当前均为 `status=ok`。

影响:

- 未来每次 scheduler/cron 小修都跑 full monitor，会拖慢闭环。
- full monitor 超时可能被误判为运行时故障。

建议动作:

1. `deploy_memory_os.py` postcheck/apply runs `memory_os_cron_adapter_probe.py`
   as the fast cron probe.
2. `deploy_memory_os.py` postcheck/apply runs
   `memory_os_boundary_runtime_probe.py` as the fast boundary/runtime probe.
3. Full monitor performance budget:
   - production full monitor target <= 180s;
   - clean-host full monitor target <= 240s;
   - timeout is a monitor-performance finding unless fast probes show runtime
     boundary or cron-state failure.

当前收口:

- fast cron probe 和 fast boundary/runtime probe 都进入 V1 runbook / deploy sequencing。
- full monitor 仍作为最终 live/clean-host 证据，但不再是所有小切片唯一闭环。

Remaining watch item:

- full monitor performance optimization and timeout classification remain P1/P2
  engineering debt, but deploy sequencing is closed.

## 3. 下一轮建议

进入更深代码审计前，建议先做基线修复轮:

1. 解决 R-013，补 fast probe / full monitor 性能预算。
2. 观察并关闭 R-004。
3. 保持双机 monitor 作为 live evidence gate。
4. 再进入第二轮专项审计:
   - cron/scheduler gate audit
   - write surface and ledger retention audit
   - owner action state machine audit
   - projection collector privacy audit
   - Hindsight governance boundary audit

当前不建议开启 58。
