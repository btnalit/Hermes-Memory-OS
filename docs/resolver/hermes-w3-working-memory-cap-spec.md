# W3 可执行规约 — 工作记忆容量治理

> **目标**：修复工作记忆衰减/清理机制的 BUG 和设计缺陷，用 per-kind top-N cap bound 存储，而非靠全局猛衰减让 companion 忘得更快。
> **纪律**：BUG 修在根上（字段语义分离）、设计改成按重要性 cap（不按年龄）、RED-first 测试、INV 不破、StructuralWriteGate 全路径覆盖。
> **代码基准**：`plugins/memory/memory_os/working.py`、`plugins/memory/memory_os/schema.py`、`plugins/memory/memory_os/inner_drive.py`、`plugins/modules/cognition/deep_reflection.py`、`plugins/memory/memory_os/prefetch.py`、`plugins/memory/memory_os/runtime.py`、`plugins/memory/memory_os/cognitive_loop.py`。

## 0. 背景：dc954aa 的三个设计缺陷

| # | 级别 | 问题 | 证明 |
|---|------|------|------|
| 1 | 🔴 BUG | `decay_items` 每 tick 将 `updated_at` 刷成 `current_ts`，毁了 `deep_reflection.py:645` 和 `prefetch.py:824` 的 `sorted(by updated_at)` 近因排序 | `deep_reflection.py:645`: `sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True)[:limit]`；`prefetch.py:824`: `candidates.sort(key=lambda x: x[0].get("updated_at", ""), reverse=True)` |
| 2 | 🟠 设计 | 无 per-kind top-N cap，用全局猛衰减（half_life=12h, expire=0.25）治积压 → 按年龄删、而非按重要性保留 | 代码中 grep `top.n\|max_items\|item_cap` 空；`conversation_turn` (weight=0.6) 19h 过期清空，昨天的情绪语境消失 |
| 3 | 🟠 设计 | 4 类统一衰减参数 | `emotional`/`curiosity`/`lingering`/`attention` 自然时间尺度不同，一刀切 12h 太粗 |
| 4 | 🟡 健壮 | grace 注释站不住（audit 同步写入，无异步 flush）+ 从 `updated_at` 算 grace 依赖脆弱隐式不变量 | `prune_expired_items` 注释声称"24h grace ensures audit flush"但 `decay_items:128` 的 audit 是同步的 |
| 5 | 🟡 根因 | 若积压来自过度产生而非消费不足，猛衰减只是掩盖症状 | `inner_drive.classify_event_for_inner_drive` 几乎所有 event kind 都产生 working item，无 per-run 产生上限 |

## 1. 锁定的决策（owner 已拍）

1. **BUG 修在根上**：衰减记账用独立字段 `last_decayed_at`，`updated_at` 还原为真正的内容近因。
2. **按重要性 cap，不按年龄**：每类 top-N by weight，cap bound 存储；回退过猛的全局衰减参数；用 cap 兜底而非靠遗忘。
3. **Per-kind 衰减参数**：emotional / curiosity / lingering / attention 各自独立 half-life。
4. **`expired_at` 字段**：过期时刻独立记录，grace 从它算，不再依赖 `updated_at` 的隐式不变量。

### 1.1 INV 保持
- **INV-9（近因字段语义）**：`updated_at` 仅在 item 内容变更时更新（add / text 更新）。衰减 tick 不碰 `updated_at`。
- **INV-10（衰减独立记账）**：衰减公式需要的"上次计算时间"存于 `last_decayed_at`；新建 item 时 `last_decayed_at` 为 null（等价于 `created_at` 作为首次衰减起点）。
- **INV-11（cap 不主动删）**：cap 触发时按 weight 升序淘汰，落 audit `working_item_evicted`。cap 仅在 add_item 时检查——不主动扫描清理。
- **INV-12（expired_at 不可变）**：`expired_at` 在 item 首次标记 `status="expired"` 时设置，之后永不变。grace 从它算。
- **INV-13（向后兼容）**：读取时 `last_decayed_at` 缺失 → fallback `updated_at`（旧数据兼容）；`expired_at` 缺失且 `status="expired"` → fallback `updated_at`（旧数据兼容）。

## 2. 字段模型变更

### 2.1 WorkingItem（schema.py）

```python
@dataclass(frozen=True)
class WorkingItem:
    id: str
    kind: str
    status: str           # "active" | "expired"
    created_at: str       # ISO 8601 — 首次创建时刻，不变
    updated_at: str       # ISO 8601 — 最后内容变更时刻（add / text 更新），衰减不碰
    text: str
    source_event_id: str
    tags: list[str]
    weight: float         # 当前衰减后权重
    last_decayed_at: str = ""   # NEW: 上次衰减计算时刻；空串=从未衰减（首次衰减从 created_at 起算）
    expired_at: str = ""        # NEW: 标记 expired 的时刻；空串=未过期
```

### 2.2 文档 schema_version

WORKING_SCHEMA_VERSION 从 `"memory-os.working.v0"` 升到 `"memory-os.working.v1"`。读取兼容 v0（自动补全新字段的默认值）。

## 3. Per-kind 参数表（模块级常量）

```python
# working.py 模块级常量，替代统一的 DEFAULT_HALF_LIFE_HOURS

WORKING_KIND_PARAMS: dict[str, dict[str, float]] = {
    "lingering":  {"half_life_hours": 18.0, "max_items": 50, "expire_below": 0.10},
    "emotional":  {"half_life_hours": 48.0, "max_items": 30, "expire_below": 0.05},
    "curiosity":  {"half_life_hours": 24.0, "max_items": 30, "expire_below": 0.08},
    "attention":  {"half_life_hours": 6.0,  "max_items": 20, "expire_below": 0.10},
}

# 向后兼容：旧调用方不传 half_life_hours 时从这里取默认
# 可在未来被 knob override 覆盖
```

**参数说明**：
- `half_life_hours`：衰减半衰期。值越大忘得越慢。
- `max_items`：per-kind 容量上限。超出时按 weight 升序淘汰。
- `expire_below`：weight 低于此值时标记 `status="expired"`。

**设计理由**：
- `emotional` 半衰期最长（48h）——情绪显著性是持续信号，不该 19h 清空。
- `attention` 半衰期最短（6h）——瞬时注意力天然短暂。
- `lingering` 是产出最多的类（inner_drive 默认输出），cap=50 兜容量。
- `max_items` 加总 = 130 条，远低于之前的 217 条积压，且有界。

## 4. BUG 修复：decay_items 字段语义分离

### 4.1 衰减公式改为从 last_decayed_at 起算

```python
# working.py:decay_items — 关键变更

def decay_items(self, kind, *, now=None, half_life_hours=None, expire_below=None, audit_write=True):
    # ...
    current = _datetime(now)
    current_ts = current.isoformat()
    params = WORKING_KIND_PARAMS[kind]
    effective_half_life = half_life_hours if half_life_hours is not None else params["half_life_hours"]
    effective_expire_below = expire_below if expire_below is not None else params["expire_below"]
    
    for raw_item in document["items"]:
        item = _item_from_dict(raw_item)
        if item.status != "active":
            continue
        
        # ── 衰减时间起点：last_decayed_at > updated_at（首次）= created_at ──
        decay_base_str = item.last_decayed_at or item.updated_at or item.created_at
        decay_base = datetime.fromisoformat(decay_base_str)
        elapsed_hours = max(0.0, (current - decay_base).total_seconds() / 3600.0)
        decayed_weight = item.weight * pow(0.5, elapsed_hours / effective_half_life)
        
        new_status = "expired" if decayed_weight < effective_expire_below else "active"
        
        updated = WorkingItem(
            # ... 其他字段不变 ...
            updated_at=item.updated_at,          # ← 不碰！保留原始内容近因
            weight=decayed_weight,
            last_decayed_at=current_ts,           # ← NEW：记录本次衰减时刻
            expired_at=(current_ts if new_status == "expired" and not item.expired_at else item.expired_at),
            #                                                      ↑ NEW：首次过期时设置，之后不变
        )
```

### 4.2 add_item 初始值

```python
def add_item(self, kind, text, ...):
    item = WorkingItem(
        # ...
        created_at=timestamp,
        updated_at=timestamp,
        last_decayed_at="",    # 从未衰减，首次衰减从 created_at 起算
        expired_at="",         # 未过期
    )
```

### 4.3 受影响消费端的验证

| 消费端 | 文件:行 | 用 `updated_at` 做什么 | 修复后是否仍正确 |
|--------|---------|----------------------|-----------------|
| deep_reflection working item 选择 | `deep_reflection.py:645` | `sorted(by updated_at, reverse=True)[:limit]` → 选最近更新的 N 条 | ✅ 正确——`updated_at` 现在 = 内容最后变更时刻 |
| prefetch working context 注入 | `prefetch.py:824` | `candidates.sort(by updated_at, reverse=True)` → 最新优先 | ✅ 正确——同上 |
| trace_working_item | `working.py:209` | 返回 `asdict(item)` | ✅ 被动返回，不依赖字段语义 |
| status_summary | `working.py:194` | 读 weight/status | ✅ 不涉及 `updated_at` |

## 5. 设计修复：Per-kind top-N cap

### 5.1 add_item 时 cap 检查

```python
# working.py — add_item 方法新增 cap 逻辑

def add_item(self, kind, text, *, source_event_id="", tags=None, weight=1.0, now=None):
    self._validate_kind(kind)
    params = WORKING_KIND_PARAMS[kind]
    max_items = int(params["max_items"])
    
    # ... 创建 item（现有逻辑）...
    
    document = self.read_document(kind)
    document["items"].append(asdict(item))
    
    # ── Top-N cap: 超出 max_items 时按 weight 升序淘汰 ──
    if len(document["items"]) > max_items:
        # 按 weight 升序排：最低的在前面
        sorted_items = sorted(document["items"], key=lambda i: i["weight"])
        overflow = sorted_items[:len(document["items"]) - max_items]
        for evicted_raw in overflow:
            evicted = _item_from_dict(evicted_raw)
            self._audit("working_item_evicted", "ok", {
                "item_id": evicted.id, "kind": kind,
                "reason": "cap_overflow", "weight": evicted.weight,
                "max_items": max_items,
            })
        document["items"] = sorted_items[len(document["items"]) - max_items:]
    
    document["updated_at"] = timestamp
    self.store.write_working_document(kind, document)
    self._audit("working_item_added", "ok", {"item_id": item.id, "kind": kind})
    return item
```

**关键行为**：
- Cap 仅在新 item 加入时触发——不主动扫描。
- 淘汰按 weight 升序：最不重要的先走。
- 同一 weight 时：`created_at` 更早的先走（稳定排序）。
- 每次淘汰落 `working_item_evicted` audit。

### 5.2 prune_expired_items 保留（作为双兜底）

Cap 是主容量控制手段，prune 保底清理长期过期无人关注的 item。参数调整：
- `DEFAULT_PRUNE_MIN_AGE_HOURS` 从 24h → 72h（cap 已兜容量，prune 只需清真正的垃圾）
- grace 从 `expired_at` 计算（见 §6）

## 6. 健壮修复：expired_at 字段 + grace 逻辑修正

### 6.1 expired_at 设置

- `decay_items`：status 从 `"active"` 变为 `"expired"` 时，设置 `expired_at = current_ts`。
- `expired_at` 一旦设置，永不变（INV-12）。
- 读取旧数据时（v0 schema，无 `expired_at`）：`status="expired"` 且 `expired_at` 为空 → fallback 到 `updated_at`。

### 6.2 prune_expired_items grace 从 expired_at 算

```python
def prune_expired_items(self, kind, *, now=None, min_age_hours=DEFAULT_PRUNE_MIN_AGE_HOURS, audit_write=True):
    # ...
    for raw_item in document["items"]:
        item = _item_from_dict(raw_item)
        if item.status != "expired":
            kept.append(raw_item)
            continue
        
        # ── Grace 从 expired_at 起算（fallback updated_at 兼容旧数据）──
        expiry_base_str = item.expired_at or item.updated_at
        try:
            expiry_dt = datetime.fromisoformat(expiry_base_str)
        except (ValueError, TypeError):
            kept.append(raw_item)
            continue
        age_hours = (current - expiry_dt).total_seconds() / 3600.0
        if age_hours >= min_age_hours:
            # ... prune ...
```

### 6.3 删除误导注释

原注释：
```
# 24h grace period ensures audit records are written before the item is gone.
```
替换为：
```
# 24h grace period: keep expired items long enough for owner-facing
# surfaces (digests, prefetch) to observe the expiry before removal.
```

## 7. 根因调查：working item 产生端

### 7.1 调查项

| # | 调查点 | 文件 | 方法 |
|---|--------|------|------|
| 1 | inner_drive 每次 heartbeat 产生的 working item 数量是否有上限 | `runtime.py:91-103`, `inner_drive.py:48-89` | `max_events` 控制处理事件数，但每个 processed event 都无条件产生 working item（无 per-run 产生 cap） |
| 2 | 连续多 turn 是否产生语义重复的 lingering item | `inner_drive.py:99-105` | `conversation_turn` 总是产生 lingering item，无去重逻辑 |
| 3 | deep_reflection 的 update_working_memory 是否有 per-run cap | `deep_reflection.py:378` | `max_working_updates` 默认=3，**已有限量** |
| 4 | 是否存在"同语义 topic 短时重复产生"的情况 | `inner_drive.py:48-89` | 无 dedup——连续 3 个 conversation_turn 产生 3 条 independent lingering item |

### 7.2 调查结论（不在本次修改范围，记录供后续）

- inner_drive 是主要产生源：每个 `conversation_turn` / `memory_write` 无条件产生 1 条 working item。
- `runtime.heartbeat` 的 `max_events`（默认 100）是唯一边界——但 100 个事件 = 最多 100 条新 working item。
- `max_events_per_source_class`（默认 20）进一步限制——但 `foreground` 类仍是 20 条/run。
- **结论**：产生端有 per-run 边界但无总量边界、无去重。加 cap（§5）是当前最直接的 bound 手段。产生端去重可后续讨论。

## 8. 回退过猛的全局衰减

### 8.1 参数对照

| 参数 | 旧（dc954aa） | 新（W3） | 理由 |
|------|-------------|---------|------|
| `lingering.half_life_hours` | 12（统一） | 18 | conversation_turn 的 0.6 weight 在 18h 后 = 0.3，仍 active |
| `lingering.expire_below` | 0.25（统一） | 0.10 | 降低过期门槛，配合 cap=50 |
| `emotional.half_life_hours` | 12（统一） | 48 | 情绪显著性应长期保留 |
| `emotional.expire_below` | 0.25（统一） | 0.05 | 更低门槛 |
| `attention.half_life_hours` | 12（统一） | 6 | 注意力应快速衰减 |
| `DEFAULT_PRUNE_MIN_AGE_HOURS` | 24 | 72 | cap 已兜容量，prune 降级为深度清理 |

### 8.2 向后兼容

`decay_items` 的 `half_life_hours` 和 `expire_below` 参数仍接受显式传入（测试用）。不传时取 `WORKING_KIND_PARAMS[kind]` 的默认值。

## 9. 受影响的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `plugins/memory/memory_os/schema.py` | 修改 | `WorkingItem` 新增 `last_decayed_at`、`expired_at` 字段；`WORKING_SCHEMA_VERSION` → v1 |
| `plugins/memory/memory_os/working.py` | 重写核心逻辑 | per-kind 参数表；`decay_items` 字段语义分离；`add_item` 加 cap；`prune_expired_items` 改用 `expired_at` |
| `plugins/memory/memory_os/runtime.py` | 微调 | heartbeat decay 调用不再传 `audit_write=False` 硬编码（改用 per-kind 默认），prune 参数调整 |
| `plugins/memory/memory_os/cognitive_loop.py` | 微调 | `_working_decay` 适配新参数 |
| `tests/plugins/memory/test_memory_os_working.py` | 大幅扩展 | 覆盖：字段语义分离、cap 淘汰、per-kind 参数、expired_at 逻辑、向后兼容 v0→v1 |
| `tests/plugins/memory/test_memory_os_schema.py` | 新增 | v0/v1 兼容读取测试 |

## 10. 测试要点

### 10.1 BUG 修复验证
- `test_decay_does_not_touch_updated_at`：衰减后 `updated_at` 保持原始值
- `test_decay_sets_last_decayed_at`：衰减后 `last_decayed_at` = current_ts
- `test_decay_uses_last_decayed_at_for_elapsed`：连续两次衰减，第二次从 `last_decayed_at` 起算
- `test_new_item_has_empty_last_decayed_at`：新建 item 的 `last_decayed_at` = ""
- `test_deep_reflection_sorting_preserved_after_decay`：衰减后 deep_reflection 仍能按 `updated_at` 正确排序
- `test_prefetch_sorting_preserved_after_decay`：衰减后 prefetch 仍能按 `updated_at` 正确排序

### 10.2 Cap 验证
- `test_add_item_below_cap_no_eviction`：未超 max_items 不触发淘汰
- `test_add_item_exceeds_cap_evicts_lowest_weight`：超出 cap 时淘汰 weight 最低的
- `test_add_item_cap_tiebreaker_uses_created_at`：同 weight 时淘汰更早的
- `test_cap_eviction_writes_audit`：淘汰落 `working_item_evicted` audit
- `test_cap_only_triggers_on_add`：cap 仅在 add_item 时触发，不主动扫描

### 10.3 Per-kind 参数验证
- `test_emotional_half_life_is_48h`：emotional 默认半衰期 48h
- `test_attention_half_life_is_6h`：attention 默认半衰期 6h
- `test_lingering_cap_is_50`：lingering max_items = 50

### 10.4 expired_at 验证
- `test_expired_at_set_on_first_expiry`：首次过期时 `expired_at` = current_ts
- `test_expired_at_unchanged_on_second_decay`：已过期 item 再次衰减，`expired_at` 不变
- `test_prune_uses_expired_at_for_grace`：prune grace 从 `expired_at` 算
- `test_prune_fallback_to_updated_at_for_v0_data`：无 `expired_at` 的旧数据 fallback `updated_at`

### 10.5 向后兼容验证
- `test_read_v0_document_auto_fills_new_fields`：读取 v0 schema 文档时 `last_decayed_at`/`expired_at` 自动补默认值
- `test_decay_on_v0_item_uses_updated_at_as_base`：对无 `last_decayed_at` 的 v0 item 衰减，从 `updated_at` 起算

## 11. 不做的事

- ❌ 不在本次改动中为 inner_drive 加入 working item 去重逻辑（需另行讨论）。
- ❌ 不改变 `prune_expired_items` 的"真删除"语义（仍走 invalidate-not-delete 风格的用户可见 audit）。
- ❌ 不将 cap 做成可被 knob override 的动态参数（可在后续加入 `WORKING_KIND_PARAMS` 到 `OVERRIDABLE_KNOBS`）。
- ❌ 不拆分 `working.py` 文件。

---

> **执行入口**：此规约 → `writing-plans` 出实现计划 → 实现。
> **关联规约**：W1+W2 (`hermes-w1-w2-resolver-and-speech-spec.md`)、P3 (`p3-resolver-write-provisional-sweep-design.md`)。
