# Memory-OS 与现有 Hermes 集成方案

日期：2026-05-20

本文补齐 `architecture.md` 和 `memory-provider-selection.md` 没写清楚的生产接入问题。它的目标不是现在迁移生产，而是先把现有 Hermes、三奶、CW-019、Hindsight、Wandering Mind 和跨 profile 流的边界写清楚，避免 v0 原型跑通后才发现无法接入真实系统。

## 结论

1. v0 继续只在 `10.20.3.200` 空白机验证，不修改 `10.20.2.88` 生产。
2. 新增 `Sannai Shadow Import / Replay` 阶段，用三奶生产数据的只读快照在 `10.20.3.200` 做影子验证。
3. identity 采用选项 B：SOUL 保留原位置，Memory-OS 只通过 `identity/manifest.json` 引用和校验，不创建 canonical 副本。
4. CW-019 owner review v1 不被 v0 替代；Memory-OS approval 是未来统一审批模型，先桥接、后收敛。
5. 跨 profile 访问必须通过显式 read view / mailbox event，不允许一个 profile 直接读写另一个 profile 的私有 memory-os 根。
6. Hindsight 切换必须分 profile、分阶段、可回滚；Sannai 和 main Hermes 不能同时切。

## 当前生产事实

只读复核时间：2026-05-20 13:49 CST。

生产 host：

```text
10.20.2.88 / YC-NAS
```

memory provider：

```text
main Hermes:
  HERMES_HOME=/vol1/.hermes
  memory.provider=hindsight

Sannai:
  HERMES_HOME=/root/.hermes/profiles/sannai
  memory.provider=(none, built-in only)
```

三奶关键文件现状：

```text
/root/.hermes/profiles/sannai/SOUL.md
/root/.hermes/profiles/sannai/memories/MEMORY.md
/root/.hermes/profiles/sannai/memories/USER.md
/vol1/.hermes/state/sannai/diary.md
/vol1/.hermes/state/sannai/self_memory.md
/vol1/.hermes/state/sannai/lingering_thoughts.json
/vol1/.hermes/state/sannai/quiet_moments.jsonl
/vol1/.hermes/state/sannai/heartbeat_lingering_candidates.jsonl
```

这说明现在的三奶已经是多根结构：profile identity 在 `/root/.hermes/profiles/sannai`，动态状态在 `/vol1/.hermes/state/sannai`。Memory-OS 不能假设所有身份和状态天然在一个目录里。

## 集成原则

- **不把生产当测试环境。** 任何写入、迁移、provider 切换都先在 `10.20.3.200` 验证。
- **不复制未审批的行为为长记忆。** 现有 CW-019 candidate、quiet moment、diary 都先进入 event/candidate，不直接 crystallize。
- **不破坏三奶前台独立性。** backend shadow replay 不改变三奶前台人格，也不让她知道机制细节。
- **不让 main 和 Sannai 混写。** 跨 profile 只能用显式 view 或 mailbox/event 协议。
- **不自动改 identity。** SOUL、MEMORY、USER、values 一类身份文件由 owner 控制。
- **Hindsight 保持手动 curated 方向。** 不恢复 auto-retain，不把 raw transcript 或 working draft 导入 Hindsight。

## 三奶现有数据迁移策略

### 决策

v0 不迁移生产。新增一个 `Phase 1b: Sannai Shadow Import / Replay`，在 `10.20.3.200` 上验证 Memory-OS 能理解真实三奶数据形态。

这解决两个问题：

- 空 profile 只能证明架构能跑，不能证明适合三奶。
- 直接在生产 dry-run 虽然只读，也会让验证路径贴近生产风险。

### 三阶段验证

| 阶段 | 环境 | 数据 | 目标 |
| --- | --- | --- | --- |
| Phase 1a | `10.20.3.200` | `memoryos-test` 空 profile | 验证 provider 生命周期、schema、索引、prefetch、audit。 |
| Phase 1b | `10.20.3.200` | 三奶只读 shadow bundle | 验证真实三奶文件映射、candidate 导入、bounded view、inner-drive replay。 |
| Phase 1c | `10.20.2.88` | 生产 metadata only | 只跑只读评估报告，不写 memory-os，不切 provider。 |

### Shadow bundle 规则

shadow bundle 是一次性测试输入，不是迁移结果。

建议路径：

```text
10.20.3.200:
$HERMES_HOME/memory-os/imports/sannai-shadow-YYYYMMDD-HHMMSS/
├── manifest.json
├── source/
│   ├── profile/SOUL.md
│   ├── profile/memories/MEMORY.md
│   ├── profile/memories/USER.md
│   └── state/
│       ├── diary.md
│       ├── self_memory.md
│       ├── lingering_thoughts.json
│       ├── quiet_moments.jsonl
│       ├── heartbeat_lingering_candidates.jsonl
│       └── digests/daily/
└── import_report.json
```

copy 规则：

- 需要 owner 明确批准后才复制正文。
- 默认不复制 raw session body、private prompt、secret、API key。
- 如果只需要结构验证，可以生成 redacted bundle：保留 path、mtime、size、hash、schema shape，不保留正文。
- shadow bundle 中的 `SOUL.md` 只是测试输入，不是 Memory-OS 新的 canonical identity。
- 导出脚本只能做 `stat` + sequential file read + checksum，不允许持有生产写锁、`flock`、rename、truncate、chmod/chattr 或任何 source mutation。
- shadow validation 接受 bundle 是 T0 时间点快照；如果生产在导出后继续写入，source hash drift 只说明快照不代表当前生产状态，不影响 import/replay 验证结论。

### 映射规则

| 现有文件 | Memory-OS 映射 | 备注 |
| --- | --- | --- |
| `SOUL.md` | `identity/manifest.json` source pointer + checksum | 不复制为 canonical identity。 |
| `memories/MEMORY.md` | `identity/manifest.json` pointer + optional crystallized candidate refs | 不自动拆成长记忆。 |
| `memories/USER.md` | `relationships/owner.md` candidate refs + manifest pointer | 需要 owner review。 |
| `diary.md` | `events` + `crystallized/moments.md` candidates | 不自动 approved。 |
| `self_memory.md` | `relationships/hermes.md` 或 `crystallized/insights.md` candidates | 需要人工审查语气和边界。 |
| `lingering_thoughts.json` | `working/lingering.json` | 保留状态但不主动表达。 |
| `quiet_moments.jsonl` | `events` | 保留 `source=CW-019`。 |
| `heartbeat_lingering_candidates.jsonl` | `events` + approval candidates | 保留原 CW-019 status。 |
| `digests/daily/` | `events` 或 `crystallized` candidates | 只导入摘要，不展开 raw source。 |

### Shadow replay 验收

Phase 1b 通过条件：

- import report 能列出导入文件、hash、记录数、跳过原因。
- Memory-OS 能从 shadow bundle 生成 event/working/candidate，不生成 approved crystallized。
- prefetch 能在 budget 内返回三奶相关 bounded context。
- owner review backlog 数量与源候选数量可对账。
- inner-drive replay 只更新 working/candidate，不发消息、不写 identity、不导出 Hindsight。

shadow suitability 验证不等于 production migration approval。它只能证明 Memory-OS 能处理三奶式数据形态、schema 兼容、inner-drive 在 shadow 数据上的行为可观察、owner review backlog 可对账；不能证明 production provider 切换、前台人格、mailbox/gateway 集成或 restart 风险已经安全。

下一阶段的 shadow observation 允许：

- 在 `10.20.3.200` shadow profile 上运行 inner-drive 观察。
- 观察 working memory 演化、prefetch 输出、owner review backlog、doctor/inspect/trace/diff、benchmark、cleanup/retention。

下一阶段禁止：

- shadow profile 发送任何消息。
- shadow 数据回流 production。
- shadow approval 影响 production CW-019。
- shadow profile 启用 S5。
- shadow 验证通过后直接切 production provider。
- shadow profile 连接生产 Hindsight bank 或真实 production Hindsight client。

## Identity 物理位置决策

### 决策：选项 B

SOUL 保留在原 profile 位置；Memory-OS 只通过 `identity/manifest.json` 引用。

生产形态：

```text
/root/.hermes/profiles/sannai/SOUL.md          # canonical identity source
/root/.hermes/profiles/sannai/memories/*.md    # built-in profile memory
$HERMES_HOME/memory-os/identity/manifest.json  # pointer + checksum + protection metadata
```

不采用选项 A 的原因：

- 把 SOUL 搬进 `memory-os/identity/` 会制造双源迁移风险。
- 旧 Hermes prompt builder、gateway、mailbox、cron 仍然按 profile 文件加载身份。
- chattr / owner protection 的边界应该保护身份源，不应该被 provider 重构绕开。

### Manifest schema

```json
{
  "schema_version": "memory-os.identity_manifest.v0",
  "profile": "sannai",
  "identity_sources": [
    {
      "kind": "soul",
      "path": "/root/.hermes/profiles/sannai/SOUL.md",
      "sha256": "redacted-or-recorded",
      "size": 8535,
      "mtime": "2026-05-19T23:26:23+08:00",
      "owner_controlled": true,
      "memory_os_writable": false
    }
  ],
  "last_checked_at": "2026-05-20T13:49:22+08:00"
}
```

规则：

- Memory-OS 可以检测 checksum drift，但不能自动修正 identity。
- identity drift 只能生成 event 和 owner review item。
- shadow replay 中复制的 SOUL 是 fixture，不改变生产 source-of-truth 决策。
- inner-drive 如果产生 identity 相关建议，只能写 audit event 或 owner review candidate；不能写 production identity source，也不能写 shadow copy 当作 canonical identity。
- 如果未来 owner 决定给 SOUL 加 `chattr +i`，Memory-OS 不需要改设计，只更新 manifest 的 protection metadata。

## CW-019 与 Memory-OS Approval 的关系

### 决策

CW-019 owner review v1 是现有系统的审批入口，v0 不替代它。

Memory-OS approval 是未来统一审批模型，但 v0 只做桥接：

```text
CW-019 candidate
  -> Memory-OS event/candidate mirror
  -> no crystallized write
  -> no S5 enablement
  -> no lingering_thoughts write
```

### 状态映射

| CW-019 status | Memory-OS 映射 | 含义 |
| --- | --- | --- |
| `candidate` | `approval_state=pending` | 等待 owner review。 |
| `owner_eligible` | `approval_state=approved_for_s5_visibility` | 只表示未来 S5 可见，不等于 crystallized approval。 |
| `owner_declined` | `approval_state=rejected` | 不进入 working/crystallized。 |
| `owner_defer` | `approval_state=deferred` | 保留候选，不升级。 |

关键边界：

- `owner_eligible` 不是 long-term memory approval。
- Memory-OS 如果要写 crystallized，需要单独的 `approve_crystallize` 或等价显式审批。
- 现有 pending candidates 不能在导入时自动升级。
- CW-019 的“观察-only / 不写 active lingering / 不写 long-term memory”边界继续有效。

### 过渡路线

Phase 1b：

- 导入 CW-019 candidates 到 shadow Memory-OS。
- 保留原 status。
- 生成对账报告：source count、pending、eligible、declined、deferred、expired。

Phase 2：

- Inner-drive 可读取 CW-019 event/candidate mirror。
- 仍不写 `lingering_thoughts.json` 或 crystallized。

Phase 4：

- 设计统一 owner review CLI/UI。
- 让 Memory-OS approval 支持不同审批目的：
  - `approve_for_visibility`
  - `approve_for_working`
  - `approve_for_crystallized`
  - `reject`
  - `defer`

Production migration：

- 只有当统一审批模型通过 shadow replay 和 owner review 对账后，才考虑替代 CW-019 v1。
- shadow profile 中的任何 approval 都是 shadow-local evidence，不会自动继承到 production migration。
- production migration 前必须重新确认 approval purpose；`approve_for_visibility`、`approve_for_working`、`approve_for_crystallized` 仍然是不同审批目的。
- shadow inner-drive 可以读取 CW-019 mirror 产生 shadow-local working/candidate 状态，但这些状态不能反向写入 production CW-019，也不能影响下一轮 production owner review。

## 跨 Profile 数据流

### 问题

Memory-OS 必须 profile-local，但现有系统有合理跨 profile 流：

```text
main Hermes -> Sannai mailbox
Sannai -> main Hermes mailbox
Wandering Mind(main) -> reads Sannai household digest
```

不能用“完全隔离”否定这些流，也不能让 profile 直接互相读私有根。

### 决策：显式 View + Event 协议

跨 profile 只有两种合法路径：

1. **Mailbox/Event write**：一个 profile 给另一个 profile 发消息，接收方把它作为自己的 event。
2. **Read View export**：生产方生成 bounded read view，消费方只读这个 view。

禁止：

- main 直接读取 Sannai `$HERMES_HOME/memory-os/events/`。
- Sannai 直接写 main `$HERMES_HOME/memory-os/working/`。
- Wandering Mind 读取 Sannai private event stream。

### Read View schema

```json
{
  "schema_version": "memory-os.cross_profile_view.v0",
  "view_id": "view_sannai_household_digest_20260520",
  "producer_profile": "sannai",
  "consumer_profile": "main",
  "scope": "household_digest",
  "created_at": "2026-05-20T06:00:00+08:00",
  "expires_at": "2026-05-27T06:00:00+08:00",
  "source_refs": ["evt_...", "cry_..."],
  "body_policy": "summary_only",
  "path": "shared_views/sannai/household_digest.md"
}
```

### 现有流映射

| 现有流 | Memory-OS v0 映射 |
| --- | --- |
| Hermes 主实例给三奶写信 | main 写 outbound mailbox event；Sannai 收到后写 Sannai event。 |
| 三奶给 Hermes 叔叔留言 | Sannai 写 outbound mailbox event；main 收到后写 main event。 |
| Wandering Mind 读 household_digest | Sannai 导出 `shared_views/sannai/household_digest.md`；main 只读 view。 |
| main evolution loop 观察 Sannai metadata | 只读 metadata view，不读 Sannai state body。 |

## Hindsight 切换与回滚

### 当前状态

- main Hermes 生产使用 Hindsight。
- Sannai 当前 built-in only。
- 过去 Hindsight auto-retain 曾造成污染，因此当前策略必须保持 manual-curated。

### 切换顺序

```text
memoryos-test on 10.20.3.200
  -> Sannai shadow profile on 10.20.3.200
  -> optional Hindsight adapter smoke on 10.20.3.200
  -> production read-only dry report on 10.20.2.88
  -> Sannai production pilot, if explicitly approved
  -> main Hermes production pilot, later and separately
```

不允许：

- main 和 Sannai 同时切。
- 一步把 Hindsight 从 active provider 改成 Memory-OS。
- 为了测试 adapter 恢复 Hindsight auto-retain。
- shadow Hindsight adapter smoke 只能使用 disabled-by-default 配置或 mock/isolated client；不得连接生产 Hindsight bank、生产 API key、生产 bank id 或 main Hermes Hindsight 配置。

### Quiet Window Export Rule

当前 shadow validation 不要求 quiet window。真实 production migration 时，最终 shadow bundle 必须在 quiet window 内导出，避免 T0 快照和切换时 production 当前状态之间出现不可自动恢复的数据丢失窗口。

quiet window 定义：

- Sannai 后台心跳暂停。
- 三奶前台对话 paused，gateway 不路由新消息。
- CW-019 candidate generation paused。
- 持续时间至少 10 分钟，覆盖一个完整 cron tick。

quiet window 操作顺序：

1. owner 明确批准 quiet window。
2. 暂停 Sannai cron jobs、前台路由和 CW-019 generation。
3. 记录 `pause_window_id`、开始时间、目标 profile、目标服务、当前 PID、当前 provider。
4. 执行 final export。
5. 导出后重新计算所有 source hash，确认 manifest hash 与生产源一致。
6. resume cron jobs、前台路由和 CW-019 generation。
7. 写 production audit event：`quiet_window_used`、`exported_at`、`bundle_id`、hash check result、resume result。

如果导出后 source hash drift：

- shadow validation：可接受，bundle 是 T0 快照。
- production migration：不允许继续切换；必须重新进入 quiet window 并重新导出 final bundle。

### 切换前备份

切换任何生产 profile 前必须有：

```text
config.yaml backup
.env secret presence inventory, not secret values
hermes memory status snapshot
Hindsight bank stats/config snapshot, no memory bodies
profile file hash manifest
Memory-OS empty-root backup or absence proof
gateway PID and HERMES_HOME snapshot
```

### 回滚策略

如果切换失败：

1. 停止 Memory-OS 新写入入口。
2. 恢复 `memory.provider` 到切换前值：
   - main: `hindsight`
   - Sannai: `(none, built-in only)`，除非切换前已有 provider。
3. 保留 `$HERMES_HOME/memory-os/` 作为 evidence，不删除。
4. 不把 Memory-OS event 回灌 Hindsight。
5. 重启范围只限被切 profile 的 gateway，并记录 before/after PID。
6. 生成 rollback report：失败点、丢失窗口、已写 event 数、是否有 adapter export。

### 数据丢失处理

- Memory-OS event JSONL 是切换期间的本地真源。
- 回滚后这些 event 不自动丢弃，也不自动导入旧 provider。
- 如果需要补录，走 owner review + explicit replay，不做自动 backfill。

## Backup 与 Recovery

### Backup 单元

每个 profile 独立备份：

```text
$HERMES_HOME/memory-os/
profile identity sources hash manifest
profile config snapshot
optional Hindsight adapter config, secret values excluded
```

建议 backup artifact：

```text
memory-os-backup-<profile>-YYYYMMDD-HHMMSS/
├── files.tar.zst
├── sqlite.backup
├── manifest.sha256
├── restore_plan.md
└── backup_report.json
```

### SQLite 损坏恢复

原则：SQLite 是索引，不是真源。

恢复流程：

1. 停止该 profile 的 Memory-OS 写入。
2. 保存损坏的 `memory_os.db` 到 quarantine。
3. 从 filesystem records 重建：
   - `events/**/*.jsonl`
   - `working/*.json`
   - `crystallized/**/*.md` frontmatter
   - `relationships/*.md` frontmatter/source refs
   - `audit/write_audit.jsonl`
4. 校验 record count、hash、last event id。
5. 重新启用写入。

### 文件误删恢复

- `events` 丢失：从最新 backup 恢复；缺失窗口只能从 session/mailbox/cron source 做人工 backfill，不自动合成。
- `working` 丢失：可从 recent events 重建近似状态，但必须标记 `reconstructed=true`。
- `crystallized` 丢失：必须从 backup 恢复；不能由模型重新生成当作原记录。
- `identity` source 丢失：Memory-OS 进入 blocked；只能由 owner 从 profile backup 恢复。
- `audit` 丢失：系统进入 degraded，不允许 production migration 继续。

### 灾难恢复准则

- 先恢复 identity source，再恢复 Memory-OS。
- 先恢复 events/crystallized，再重建 index。
- 恢复后先跑 `memory-os doctor`，再允许 prefetch。
- Hindsight adapter 不参与灾难恢复的真源判断。

## Inner-Drive Scheduler 与 Engine 边界

两者不是同一个模块。

```text
L0 cron / service timer
  -> L3 Inner-Drive Scheduler
     -> checks policy, caps, quiet hours, profile permissions
     -> calls L2 InnerDriveEngine
        -> computes state transitions
        -> writes working/events through L1 store
```

Engine：

- 纯状态演化逻辑。
- 不知道 cron。
- 不知道 Telegram/mailbox。
- 不决定是否表达。
- 可用 fake clock 做单元测试。

Scheduler：

- 决定什么时候调用 Engine。
- 设置 batch size、time budget、profile target、quiet hours。
- 记录 skipped / blocked / executed decision event。
- 不能自己修改 working memory，必须通过 Engine。

## Schema Evolution Policy

原则：read many, write current。

规则：

- 新代码必须能读取当前版本和前一稳定版本。
- event JSONL append-only，不原地改历史行。
- 破坏性 schema 变更必须写 migrator 和 dry-run report。
- SQLite index 可以随时删除重建，不需要数据迁移承诺。
- `schema_version` 升级必须写 audit event。
- 旧记录迁移输出新记录时，保留 `migrated_from` 和原始 record hash。

版本文件：

```text
$HERMES_HOME/memory-os/schema_registry.json
```

示例：

```json
{
  "current_write_versions": {
    "event": "memory-os.event.v0",
    "working": "memory-os.working.v0",
    "crystallized": "memory-os.crystallized.v0"
  },
  "read_compatible_versions": {
    "event": ["memory-os.event.v0"],
    "working": ["memory-os.working.v0"],
    "crystallized": ["memory-os.crystallized.v0"]
  }
}
```

## v0 Performance SLO

初始目标，不是最终 benchmark：

| 路径 | 目标 |
| --- | --- |
| `sync_turn()` 前台返回开销 | p95 < 20ms，只做 enqueue。 |
| event append worker | p95 < 100ms，不含 LLM 提取。 |
| `prefetch(query)` warm path | p95 < 200ms at 100k events。 |
| `prefetch(query)` cold path | p95 < 800ms at 100k events。 |
| SQLite rebuild | 100k events < 60s on 10.20.3.200 baseline。 |
| working decay heartbeat | < 5s for 10k working items。 |
| status command | < 1s without deep scan。 |

如果达不到：

- 先降级 prefetch 数量。
- 再启用 cached view。
- 不牺牲 sync_turn 前台延迟。

## Observability 与 Debugging

v0 CLI 不只需要 `status`，还需要最小诊断面。

```text
hermes memory-os status
hermes memory-os doctor
hermes memory-os inspect <event_id>
hermes memory-os trace <working_id|candidate_id>
hermes memory-os diff --since <time> --until <time>
hermes memory-os rebuild-index --dry-run
hermes memory-os approval-report
hermes memory-os export-shadow --profile sannai --dry-run
```

命令边界：

- 默认不打印正文，只打印摘要、hash、状态和 source refs。
- 打印 private body 需要显式 `--include-private`，生产默认禁止。
- `trace` 必须显示一个 lingering/candidate 从 event 到 working 到 approval 的完整生命周期。
- `diff` 用于比较两个时间点的 working/crystallized/index/audit 变化。

## 测试 Profile 的局限性

`memoryos-test` 的成功只证明结构正确，不证明它适合三奶。

因此验收要分两类：

```text
Core correctness:
  空 profile 可验证。

Sannai suitability:
  必须用 shadow import/replay 验证。
```

`memoryos-test` 通过条件：

- provider 可以安装、激活、读写、关闭。
- schema 和 index 不损坏。
- prefetch 有预算。
- failure tests 可恢复。

不代表：

- inner-drive 语气适合三奶。
- relationship memory 解释正确。
- Wandering Mind 读写边界自然。
- owner review backlog 压力可接受。

这些必须在 `Sannai Shadow Import / Replay` 后单独判断。

## Wandering Mind Profile 归属

### 决策

v0 保持 Wandering Mind 在 main profile，不搬到 Sannai，也不新建第三 profile。

理由：

- 当前 Wandering Mind 已作为 main Hermes 的右脑子系统存在。
- 直接搬到 Sannai 会把右脑机制和三奶前台人格混在一起。
- 第三 profile 会增加 mailbox、cron、identity、权限复杂度，不适合 v0。

v0 读取方式：

```text
main Wandering Mind
  -> reads main memory-os bounded view
  -> reads Sannai exported household_digest read view
  -> never reads Sannai private event stream directly
```

未来如果要独立 profile：

- 必须先定义其 identity。
- 必须定义它与 main/Sannai 的 mailbox 和 read-view 权限。
- 不能作为 v0 附带工作。

## Production Dry-Run Report

进入任何生产试点前，先做只读 dry-run report。

报告内容：

```text
profile roots
memory provider current state
identity source paths and hashes
state file inventory
CW-019 candidate status counts
cross-profile view candidates
estimated import record counts
schema validation errors
private/body fields skipped count
Hindsight adapter disabled proof
would-write paths, all under test output only
```

禁止：

- 不创建 `$HERMES_HOME/memory-os/`。
- 不改 config。
- 不重启 gateway。
- 不导出 Hindsight。
- 不打印正文。

## 覆盖审核问题

| 审核项 | 本文处理 |
| --- | --- |
| P0-1 三奶迁移路径 | `Sannai Shadow Import / Replay`，v0 不迁移生产。 |
| P0-2 chattr / identity 路径冲突 | 选项 B：SOUL 保留原位置，manifest 指针。 |
| P0-3 CW-019 approval 关系 | v1 保留，Memory-OS 先桥接，区分 visibility 和 crystallized approval。 |
| P1-4 跨 profile 流 | read view + mailbox/event protocol。 |
| P1-5 Hindsight 切换/回滚 | 分 profile 渐进切换和 rollback report。 |
| P1-6 Backup/Recovery | profile-level backup、SQLite rebuild、identity blocked recovery。 |
| P1-7 Scheduler vs Engine | Scheduler=L3，Engine=L2。 |
| P1-8 Schema versioning | read many/write current，migrator 和 schema_registry。 |
| P2-9 Performance | v0 SLO。 |
| P2-10 Observability | status/doctor/inspect/trace/diff/rebuild/approval/export-shadow。 |
| P3-11 测试 profile 局限 | 明确 core correctness 与 Sannai suitability 分开。 |
| P3-12 Wandering Mind profile | v0 留 main，通过 Sannai exported view 读取。 |

## 进入代码前的更新决策

1. Phase 1 profile：使用 `memoryos-test`，只验证 core correctness。
2. Phase 1b：增加 `sannai-shadow` profile 或 shadow import fixture，验证 Sannai suitability。
3. `10.20.3.200` 先按 main Hermes 简单形态验证 provider，再做 Sannai shadow 形态。
4. Hindsight adapter：Phase 1 末尾只做 disabled-by-default smoke；完整 integration 放 Phase 4。
5. identity manifest：v0 只做 pointer + checksum + protection metadata，不创建 `identity/soul.md` canonical 副本。
