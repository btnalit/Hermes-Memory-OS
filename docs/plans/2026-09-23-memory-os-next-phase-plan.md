# Hermes Memory-OS 下一阶段规划（定稿 v2，2026-09-23）

**范围**：① 权限主体模型 ② 收敛冲刺 ③ LLM 调用面 + Jev ④ 图谱增强（参考 supermemory）
**依据**：2026-09-22/23 对 hermes-media（main + sannai）的只读实测与五路代码审计；与顾问（Fable）三轮对抗式评审后定稿。所有"现状"均为已验证事实，"目标/计划"为提案，二者分开写。

---

## 0. 一页结论

- **四项工作有依赖链，不是并列清单。** 图谱弱的主因是**语义边供给断了**（LLM 边生产线 08-16 起 100% 空回复，与 `-900k` 同源），不是"节点不够"。所以 **L（调用面）排第一**；事实类产出必须知道"是谁说的"，所以 **P（主体）第二**；**C（收敛普查 + 冻结门）与 L 同批**，防止下一个模块又变成半接线状态。
- **图谱增强在冻结期内只做一件 supermemory 式的事**：`updates` 关系 + "只注入较新者"（latest-wins）。第三层"事实层"（supermemory 的 Memory 层）**不排期**，列出重新进入的条件。
- **Jev 这类结构化判官作为"可选开启的模块"接入**（owner 裁定 2026-09-23），默认关闭，排在 L1 统一调用面之后；不做离线回放。
- 裁定已全部完成（§8）；部署推迟到全部落地后统一进行。

---

## 1. 现状（已验证）

| 维度 | 事实 |
|---|---|
| 主体 | `EventEnvelope` 无作者字段；`owner_actions` 核心层不校验调用者（`owner_id` 只是标签 "owner"）；`session_mirror` 把 `role=="user"` 一律当主人；Hermes **没有逐条消息作者**，只有会话级 `sessions.user_id`（群内按发送者分会话才可靠）；Hermes 没有 owner 概念。**sannai 没有宿主级人类白名单**，群里任何人类都能驱动它的前台控制 |
| LLM | 手写三套 wire，其中 codex 分支绕过 Hermes 剥别名 → 400 → 吞成 `""`。受害：llm_edge_proposer（08-16 起 100/100 空）、fact_judge、clearance、判官探针。Hermes `agent.auxiliary_client.call_llm(task=None, …)` 已实测：同步、cron 进程可安全导入（0.22s）、`task=None` 无插件发现/无用量副作用、经 `_wire_model_identity` 剥 `-900k`；**但有 provider 回退链**——记忆文本可能被发给主人从未授权的 provider |
| 事实抽取 | `session_fact_extraction` 只读 `session_*.json`，而 Hermes 自 5–6 月起**只写 `state.db`** → 该 lane 的输入源是死的；且这些 JSON 无作者 |
| 图谱 | 节点=结晶记录（main 约 25–47 条有效 / sannai 57）+ 事件；active 边 7531 / 4119，co_occurs 84% / 87%；crystallized 端点 96% / 82% 已失活（无级联失活）；选槽先于存活解析（`target_inactive` 约 8%）；**crystallized 从未发生 supersede**（所有失活来自 provisional_sweep）；main 6317 条 active co_occurs 的 bigram Dice 中位 0.38、q90 0.61，**≥0.85 的近逐字对仅 313 对（5%）**（1 小时内 50、跨会话 263；≥0.95 仅 3 对），sannai ≥0.85 仅 29 对——这些"同一内容的两份"会被一起注入；主人评分 30 天 0 条——**当前没有任何"有用性"信号**；shadow 账本 15MB 无尺寸门 |
| 生命周期 | 23 lane 大多健康；已知问题：sannai `full_monitor_refresh` 6 周零产出、retention compaction 未接生产、55C/55G 要求已退役 source、sannai 右脑 disabled≠retired、entity_index 双路径、l3_probe 孤儿、symbolic_offloader/mailbox 仅 CLI、两 profile 图谱 knob 不一致；账本无尺寸门（shadow 15MB / candidate_triage 13.8MB / v3_seed_edges_daily 28MB） |

---

## 2. 领域模型（只补必要的）

**主体**
- `Author{platform, author_id, author_name, is_bot}`：每一轮、每个事件都有（可为空）。
- `Principal ∈ {owner, peer_agent, other_human, system, unknown}`：由 `principal.resolve_principal()` **唯一**给出。
- 主人身份：Memory-OS 配置 `principal.owner_identities`，**按平台分别列出**（telegram / wecom / weixin …；只写 telegram 会把主人的 wecom 轮判成 `other_human`）。开源项目的部署脚本按三层自动绑定（owner 裁定：只用宿主上已有的信号，不做认领码），每条绑定都记录 `binding_source`：
  1. **本地源**（cli / tui / acp）= owner（owner 已裁定 2026-09-23：能上本机 shell 的人本就拥有更高权限）。
  2. **显式参数** `--owner-identity <platform>:<id>`（可重复）永远优先。
  3. **自动发现**：从运维者已经写过的宿主配置里取"私聊形态"的证据——`<PLATFORM>_HOME_CHANNEL`（Telegram 私聊 chat id = user id）、只含一个 id 的 `<PLATFORM>_ALLOWED_USERS`、Hermes 配对库里唯一的已批准用户、Memory-OS owner digest 的显式投递目标。同一平台 ≥2 个信号一致，或 1 个运维者写的主通道信号且无冲突 → 自动绑定；信号互相矛盾 → 不绑定并在安装报告里列出。群聊与 `api` 平台（自报作者）永远不能作为证据。本机实测：main 的 Telegram 主通道 = 私聊白名单唯一 id（两信号一致）；sannai 只有主通道一个信号；两边都没有配对记录。
  - 某平台没有任何可用信号 → 不绑定；若该平台存在非主人会话，生产 monitor FAIL，提示里直接写明两种补法：部署参数 `--owner-identity <platform>:<id>`，或在 Hermes 里为该平台配置 `<PLATFORM>_HOME_CHANNEL`（下次部署自动发现）。
- `resolve_principal` 输入是 **source + user_id**，不只 user_id，需要一张 source→principal 映射表：本地源（cli/tui/acp）→ owner；**`mailbox` → `peer_agent`**（owner 已裁定 2026-09-23：mailbox 是 agent 之间的直接通信通道，不做主人认证——信件可作为信息保留检索，但永远不驱动前台控制、owner action 或主人事实；sannai 的 41 个 mailbox 会话中 40 个来自 main 上的 `hermes` agent）。
- 不变量：
  - **P1** 只有 `owner` 可驱动前台控制、owner action、事实写入资格。未配置白名单时为兼容态（=今天行为），但生产 monitor 会报出来（§3 P0-lite）。
  - **P2** 持久事件带 `author`/`principal` schema 字段（era 边界，不回填）。
  - **P3** `api` 平台的作者一律非 owner（它是调用方自报的；暂不建 trust 枚举）。
  - **P4** 判定只在 `principal.py` 一处。

**图谱关系（冻结期新增一个）**
- `updates`（新→旧）：较新记录取代较旧记录的"现行性"。index 派生 `is_latest`（可重建，非规范），注入时一对里只注入较新者。
- 两个生产者、两种语义，用 `proposed_by` 区分：
  - 确定性（structural）：只能识别"重述/重复"（高 Dice 且同 kind）；
  - LLM（L1 之后，llm_edge_proposer 的闭集标签）：才能识别真正的"改口"（例如"住北京→搬到东京"字面相似度很低）。
- **不改任何记录、不加层、不设逐边 owner 门**（沿用 08-06 裁定）；改变结晶记录现行性仍然只能通过 owner action。

---

## 3. 阶段计划与 PR 清单

> 每个 PR 都遵守项目的完成定义：读 checklist → 反事实测试 → 全量测试 → 五道门 → checklist 新节。表中"裁定"=需要你拍板。

### Phase 0（本周）
| PR | 目的 | 改动面 | 验收 | 裁定 |
|---|---|---|---|---|
| D0 | 推送并部署 DJ（`f2607b8`+`cf80d9c`） | 两 profile deploy + 重启两个网关 | DJ.8 七项；`cancelled ∧ author_class=bot` = 0；Telegram 群会话 `author_class=unknown` 占比≈0 | 是（推送/部署） |

### Phase 1a（W1–2）：解冻 + 主体入口 + 普查
| PR | 目的 | 改动面 | 验收 | 裁定 |
|---|---|---|---|---|
| L0 | 双探针（spike，不合并） | host `/tmp` 脚本，用后删除 | ① 正常调用 `response.model` 为裸 slug `gpt-5.6-luna`；② 故意传坏 model，记录异常类型与**实际应答的 provider**（是否跨 provider 回退） | 否 |
| L1 | 调用面迁移到 `call_llm` | `low_clue_recall._call_hermes_runtime_model`（对外契约不变）+ 新增 `…_result()` typed 结果；fact_judge 等报告 | 失败一律 fail-closed（`llm_transport_unavailable` / `llm_http_4xx` / `llm_timeout` / `llm_empty_content`）；显式 timeout；**显式固定 provider/model**（取自 `_resolve_hermes_default_runtime`，不走 auto 发现链——显式 provider 时 Hermes 只在付费/配额/429 类错误才跨 provider，鉴权/校验错误不跨）；`route_info` 与 `response.model` 进每条 lane 报告；旧 wire 仅在 `llm_transport=legacy_wire` knob 下可达，恒 WARN，下个版本删除；**生产**：llm_edge_proposer `llm_call_ok_count>0`、clearance 判定对数>0、fact_judge `llm_empty_content`<5%（基线 27.5%）；应答 model≠主模型时计 `llm_route_unexpected` → WARN，**记录但不丢弃**（丢弃保护不了已发出的文本，只会把容量回退变成与空回复无法区分的 lane 停摆） | 否 |
| P0-lite | 主人白名单（入口层，按平台 + source 映射） | `principal.py`（含 source 映射表）；ingress 前台控制、owner-review 回复入口改用 `resolve_principal`；installer/deploy：`--owner-identity` 参数 + §2 的自动发现规则（结果与证据写进安装报告）；monitor | 群会话 `ingress_foreground_control_skipped>0`；未配置 ∧ **存在非主人 `user_id` 的会话（含私聊；main 实测有 44 个非主人 Telegram 私聊会话）** → live FAIL / clean-host WARN；否则 INFO | 否（规则已定；安装报告里核对绑定结果） |
| C0 | lane 契约普查 + 冻结门（含原 L2） | 新测试 `test_lane_contract_census.py`：关联已有的 23 lane 表、29 个 loop 步、knob `module` 标签、monitor 组件集，外加声明式 `reads/produces` 小表（路径一律经 accessor）；不在表内即 FAIL = 冻结门。monitor 三条新分级：**输入源新鲜度**、**输出有读者或显式 `report_only`**、**追加账本尺寸门**；LLM lane 连续失败轮数作为"lane 存活"计数器 | 覆盖 23 lane + 29 步；**当前生产上先报出 SFE `input_stale`**（证明门是活的）；尺寸门报出 shadow / candidate_triage / v3_seed_edges | 否 |

### Phase 1b（W3–4）：收敛 + 图谱卫生
| PR | 目的 | 改动面 | 验收 | 裁定 |
|---|---|---|---|---|
| C1 | sannai monitor 6 周零产出 | 只读定位（cron list / 日志 / 快照成员）后修；artifact 年龄按 profile 分级 | 两 profile artifact 新鲜 | 否 |
| C2+C3 | compaction 接生产 + 55C/55G 退役豁免 | tick-daily 成员（六处清单）；monitor 谓词改为"压缩新鲜度 vs 文件增长"；55C/55G 按 `legacy_right_brain_archive.lifecycle` 做 era 豁免 | 两 profile 0 FAIL，且没有"靠历史残留过关"的项 | 否 |
| SFE | 事实抽取换输入源 | `session_fact_extraction` 读 `state.db`，经 `resolve_principal`（source + `sessions.user_id`）过滤非主人；绊线 INFO：群会话 key 没有 user 后缀的占比；注意 `sessions.started_at` 是 epoch 数值，按 ISO 字符串比较会静默返回空 | `skipped_non_owner>0`；新会话有产出；`input_stale` 解除 | 否 |
| G0 | 图谱卫生 + 新颖度指标 | 孤儿边级联失活（有界/轮）；选槽前做存活过滤；shadow 尺寸门；shadow 行增 `session_ref`（哈希）与**新颖度**（注入邻居的词项不在锚点/query 中的占比） | `target_inactive`≈0；shadow 字节数受门；新颖度进 monitor（INFO，先建基线） | 否 |
| 退役 | C4/6/7/8 合一个 PR | sannai 右脑补退役；l3_probe、symbolic_offloader/mailbox 去留；两 profile knob 对齐 | 无常驻 warning | **是** |

### Phase 2（W5–6）：主体模型补全
| PR | 目的 | 改动面 | 验收 | 裁定 |
|---|---|---|---|---|
| P2 | 事件带作者 | `EventEnvelope.author/principal` + `principal_schema_version` era 边界；所有 producer 填写 | 新事件 100% 带 principal；空样本报 `healthy_no_sample`；`legacy_unattributed` 只降不升 | 否 |
| P3 | session_mirror 主体过滤 | 行内已有 `user_id` | 镜像里没有 peer 来源 | 否 |
| P1 | owner action 核心层自检 | `owner_actions` 最小改动：入口 `parse_owner_review_reply` 接 principal 并自检（权威在权威模块内）；`review_surface` 对非主人隐去 `oa_` token | 非主人调用被拒并落 audit | 否 |

### Phase 3（W7+）：图谱增强 + 评测 + 可选判官模块
| PR | 目的 | 改动面 | 验收 | 裁定 |
|---|---|---|---|---|
| PR-G1 | `updates` + latest-wins（supermemory 最小落地） | structural proposer 新增 `updates`（Dice ≥ θ_high ∧ 同 kind，方向按 `created_at` 由新指旧），**分支优先于 co_occurs**（同一对只出一条边；现有代码先判 co_occurs 即返回）；对存量 active 对做有界回填（否则老重复对永远不会触发）；出生即 active；`_graph_layer_shadow_lines` 对 updates 对只注入较新者，outcome `superseded_by_newer`；index 派生 `is_latest`；θ_high=0.85 是"近逐字"起点，0.5–0.85 区间留给 L1 之后 llm_edge_proposer 闭集 prompt 的 `updates` 标签（同一机制的第二个生产者，不另开 PR） | 注入批次中 updates 对 = 0；main 7 天内 `superseded_by_newer>0`（sannai 允许 `healthy_no_sample`）；`updates` 日出生量有界；新颖度不降 | **是**（词表 + θ_high） |
| G4 | 图谱回放评测集 | 从 shadow 账本抽中文 query | 新颖度 / `superseded_by_newer` / `target_inactive` 基线与回归 | 否 |
| J1 | 可选判官后端模块（Jev 等） | 在 L1 的 typed 结果接口之上加一个判官后端选择点：`judge_backend` 取值 `hermes_default` 或 `typesafe_jev`，默认 `hermes_default`；Jev 后端是独立文件、默认关闭；统一判定结果 `{label, confidence, failure_reason}`；key 沿用 Hindsight 惯例——配置只存环境变量名 `api_key_env_var`，key 放在 Hermes 的 `~/.hermes/.env`（`TYPESAFE_API_KEY`），并在 CLAUDE.md 登记为凭证例外；适用 lane：fact_judge（是/否）、low-clue 候选选择、clearance 矛盾判定；抽取/生成类 lane 不适用 | 默认关闭时零行为变化；开启后 lane 报告带 `backend`、判定与置信度；Jev 失败时 typed 回落到 `hermes_default` 并计数 | 否（已裁定为可选模块） |

---

## 4. 明确不排期（以及重新进入的条件）

| 项 | 为什么现在不做 | 重新进入条件 |
|---|---|---|
| G2 事实层（supermemory 的 Memory 层） | 需要新增存储、生命周期和 LLM 成本；生产者（SFE）今天输入是死的；作者不可得 | L1 + SFE 换源 + P2 完成；主人归属的事实候选稳定产出 ≥14 天；**在语义边供给恢复之后**，新颖度仍显示图谱邻居多数不提供新内容（否则"新颖度低"只是 LLM 生产线死亡的回声）；另写独立规划 |
| G3 画像快照（static/dynamic） | 冻结期不开新模块 | G2 进入之后 |
| 在某条 lane 上**默认开启** Jev | Jev 发布才一周；模块本身已排期（J1，默认关闭） | 主人在具体 lane 上手动开启并观察一段时间后再议默认值 |
| co_occurs 排除实验 | 本系统"命中=被注入"，量尺是机械的；30 天主人评分为 0，14 天测不出有用性 | 出现真实的有用性信号（主人评分或可靠的使用代理） |
| 原 G1（crystallized supersedes 边） | 生产上从未发生过 supersede | — |
| 按 chat/session 隔离前台锚点 | 会破坏会话轮换的跨会话连续性；真因是非主人会话，已由主体模型处理 | — |

---

## 5. 验证与监控总表

| 信号 | 所属 | 性质 |
|---|---|---|
| `author_class`/`principal` 分布，`unknown` 占比 | D0 / P0-lite / P2 | 验收 + 绊线 |
| 未配置白名单 ∧ 有群流量 | P0-lite | 生产 FAIL |
| LLM lane 连续失败轮数、`response.model`、`llm_route_unexpected` | L1 / C0 | 分级 |
| 输入源新鲜度、输出读者、账本尺寸 | C0 | 分级（冻结门） |
| `target_inactive`、新颖度、`superseded_by_newer`、updates 出生量 | G0 / PR-G1 / G4 | 基线 → 分级 |
| 群会话 key 无 user 后缀占比 | SFE / P3 | INFO 绊线 |

---

## 6. 风险

1. **`call_llm` 是 Hermes 私有 API，auto 模式会跨 provider 回退。** 缓解：显式固定 provider/model（只剩配额/429 类跨 provider）；L0② 实测应答方；`response.model` 进报告，非主模型应答计 WARN。
2. **会话级作者依赖"群内按发送者分会话"这一 Hermes 配置。** 缓解：绊线 INFO；配置一变立刻可见。
3. **白名单配错会锁死主人自己的前台控制。** 缓解：部署时显式传入 + 确认；兼容态可回退；monitor 显示启用状态。
4. **范围蔓延。** 缓解：C0 冻结门是对我们自己的约束；PR-G1 是冻结期唯一的图谱新语义，它加的是一种关系，不是一层。
5. **没有"有用性"信号。** 这意味着图谱的一切改进，目前只能证明"没坏"和"给了检索之外的内容"（新颖度），不能证明"更有用"。这一点要如实承认，不能拿注入量充当成效。

---

## 7. 讨论记录（顾问三轮，关键改判）

| 议题 | 初稿 | 改判 | 依据 |
|---|---|---|---|
| SFE 复活验收 | L1 后 `facts_extracted>0` | 先换输入源到 `state.db` | `session_*.json` 自 5–6 月停写，且无作者 |
| 主体白名单时机 | Phase 2 | P0-lite 提前到 Phase 1a | sannai 无宿主人类白名单 |
| L1 回退 | import 失败回退旧 wire | 全部 fail-closed，旧 wire 仅 knob 可达 | 按 api_mode 分支等于持有 provider 知识；旧 wire 正是吞 400 的路径 |
| C0 形态 | 每表加 `contract` 散文字段 | 普查测试 + 三条分级 | 散文字段会漂移；真实故障都是路径/新鲜度级 |
| 图谱主杠杆 | 更多节点（事实层） | 恢复语义边供给 + 卫生 + latest-wins | co_occurs 按构造就是 FTS 的冗余投影；语义候选几乎全被注入，瓶颈在供给 |
| co_occurs 实验 | 14 天排除实验 | 撤销，改用新颖度 | 命中=被注入，量尺是机械的；主人评分 0 条 |
| G1 | crystallized supersedes 边 | 改为 `updates` + latest-wins | crystallized 从未发生过 supersede；生产里有 313 对（main）/29 对（sannai）近逐字重复被一起注入 |
| Jev | JudgeBackend + 影子双判官 → 顾问建议只做离线回放 | 可选开启的判官模块（J1，默认关闭），不做回放 | owner 裁定：保证以后能以可选模块接入即可 |
| L1 路由异常 | 应答非主模型即丢弃 | 显式固定 provider，异常只计 WARN | 显式 provider 仅配额/429 跨 provider；丢弃挡不住已发出的文本 |
| 主人身份 | 只配 telegram | 按平台 + source 映射 | main 有 wecom/weixin 私聊、55 个本地会话、sannai 41 个 mailbox 会话 |
| 开源部署的主人绑定 | 部署时手填 id | 三层：本地源 → 显式参数 → 宿主配置自动发现；不做认领码 | owner 指出开源项目不能要求每个部署者手填；认领码太复杂，已有信号足够 |
| mailbox | 待定 system / peer_agent | peer_agent，不做主人认证 | owner 裁定：mailbox 是 agent 直接通信通道 |

---

## 8. 裁定状态

**已裁定（2026-09-23）**
- 本地源（cli / tui / acp）默认 = owner。
- 其他通道的主人绑定：按 §2 三层规则自动完成，只用宿主已有信号，不做认领码。
- `mailbox` 来源 = `peer_agent`，不做主人认证。
- PR-G1 `updates` 阈值 θ_high 起点 0.85（近逐字），0.5–0.85 区间留给 LLM 标签。
- Jev 这类判官：作为可选开启的模块接入（J1，默认关闭）；不做离线回放。
- 退役清单：`l3_probe_verification` 保留并登记为 watchdog；`plugins/modules/messaging/mailbox.py` 与 `plugins/modules/context/symbolic_offloader.py` 删除；两 profile 统一开启 `vector_edge_proposer` 与 `entity_index`（sannai 重建），`contradiction_lane` 两边保持关闭至 L1 之后。
- DJ（PR #82）：推送 → 独立 agent review（FIX-FIRST，5 项已修）→ 通过即合并 main。
- **部署推迟**：合并后不部署；等本轮规划全部落地后统一部署到 3.200 做实际验证（DJ.8 验收随那次部署执行）。
- Hermes 里没有配置主通道的平台不自动绑定主人。

**下一步**
- 下次会话从 Phase 1a 开始（L0 探针、L1 调用面、P0-lite 主人绑定、C0 普查）；Phase 0 的 D0 部署并入最终统一部署。

## 9. 证据附录（关键行号与数字）

- 事故：DG 后 33 条 cancelled，30 条误判（peer 22 / delegation 4 / 粘贴 3 / 否定 1）。
- LLM：`low_clue_recall.py:1101-1342`（三套 wire）；Hermes `agent/auxiliary_client.py::call_llm`、`agent/transports/codex.py:585`、`codex_responses_adapter.py:54`。
- 图谱：`prefetch.py:2576-2931`（选槽顺序）、`structural_edge_proposer.py:29-35,164-186`（co_occurs 门）、`edge_weight_feedback.py:9`（命中=被注入）、`crystallized.py:640-686`。
- 主体：`session_mirror.py:1167-1216`、`session_fact_extraction.py:587,800-889`、`owner_actions.py:3037-3182`、`schema.py:50-89`；Hermes `gateway/platforms/api_server.py:629-639`（自报作者）。
- supermemory：Document/Memory 二分；`updates/extends/derives`；`version/parentMemoryId/rootMemoryId/isLatest/isForgotten`；`forgetAfter`；`isStatic` 画像；抽取模型闭源；基准数字在不同版本 README 间自相矛盾，不作证据。
- Jev：`POST /v1/systemone`，`jev-1.13.0`，2026-09-15 发布，无私有化部署文档，需要 API key（顾问未能独立核实，属来源声称）。
