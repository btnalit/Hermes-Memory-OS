# P3: Resolver 写入 + 临时生命周期 — 设计规范

> **状态**：已批准（2026-06-17）
> **父规范**：`docs/resolver/hermes-w1-w2-resolver-and-speech-spec.md` §1.4–1.6
> **前驱**：P0（speak_gate owner-send）、P1（字段审计）、P2（resolver_gate + ExecutionGate 通道）

**目标**：构建写入机件，使 resolver 批准的候选成为 `provisional=True` 的已结晶记录，以及管理其 7 天 TTL + 30 条上限生命周期的 sweep 通道。

**架构**：三层 — 批准原语（`ApprovalDecision` 扩展）→ 写入机件（`write_approved_record` 临时处理 + ExecutionGate 集成）→ 生命周期（`provisional_sweep` 模块）。P3 包含最小路由（`_resolver_verdict` 带有 `resolver_eligible` + 简单 LLM 调用），使阶段端到端可测试。完整的 `cascade_routing_policy`/`provisional` 集成推迟到 P4。

---

## 1. 组件

### 1.1 `approval.py` — 对 `ApprovalDecision` 的 3 个新字段

**文件**：`plugins/memory/memory_os/approval.py`

向冻结数据类添加三个字段：

```python
@dataclass(frozen=True)
class ApprovalDecision:
    candidate_id: str
    purpose: ApprovalPurpose
    reviewer: str
    reviewed_at: str
    note: str = ""
    source_state: str = ""
    provisional: bool = False        # NEW — True for resolver-approved records
    expires_at: str | None = None    # NEW — ISO timestamp, +7d from approval
    recurrence: int = 0              # NEW — count of times same content approved
```

**破坏性变更风险评估**：低。所有现有调用者使用关键字参数；新的带默认值的关键字参数是向后兼容的。`ApprovalDecision` 冻结数据类上的 25 个调用者无需为新字段更新（默认值保持现有行为）。

### 1.2 `crystallized.py` — `write_approved_record` 写入临时前端元数据

**文件**：`plugins/memory/memory_os/crystallized.py`  
**方法**：`CrystallizedMemoryService.write_approved_record()`（第 58 行）

修改：当 `decision.provisional=True` 时，向前端元数据添加三个新键：

```python
frontmatter = {
    # ... existing fields ...
    "bridge_state": candidate.bridge_state or decision.source_state,
}
# NEW: provisional fields
if decision.provisional:
    frontmatter["provisional"] = True
    frontmatter["expires_at"] = decision.expires_at or ""
    frontmatter["recurrence"] = decision.recurrence
```

`approved_by: "resolver"` 已经通过传递 `reviewer="resolver"` 的现有 `decision.reviewer` 字段工作。无需显式的 `approved_by` 更改。

### 1.3 `crystallized.py` — 新方法：`invalidate_provisional_record()`

**文件**：`plugins/memory/memory_os/crystallized.py`  
**类**：`CrystallizedMemoryService`

遵循与 `revoke_record()` / `demote_record()` 相同的 invalidate-not-delete 模式：

```python
def invalidate_provisional_record(
    self,
    record_id: str,
    *,
    reason: str,          # "resolver_ttl_expired" | "resolver_cap_evicted"
    invalidated_by: str = "provisional_sweep",
    now: datetime | None = None,
) -> dict[str, Any]:
```

行为：
- 在 crystallized `.md` 文件中定位记录
- 将 `canonical_state` 设置为匹配 `reason`（`"provisional_expired"` 或 `"provisional_cap_evicted"`）
- 添加 `invalidated_at`、`invalidated_by`、`invalidation_reason` 字段
- 追加审计条目
- 保留 `provisional: true` 和 `expires_at` 字段（记录留存，不删除）
- **注意**：不使边缘失效（与针对所有者操作的 `revoke_record` 不同）—— 临时记录没有边缘。

**必需的 `INACTIVE_CANONICAL_STATES` 扩展**（`crystallized.py` 第 18 行）：
```python
# 现有：
INACTIVE_CANONICAL_STATES = {"owner_revoked", "revoked", "demoted"}
# 扩展为：
INACTIVE_CANONICAL_STATES = {"owner_revoked", "revoked", "demoted",
                              "provisional_expired", "provisional_cap_evicted"}
```
没有这个更改，`is_active_crystallized_frontmatter()` 会将已过期/已驱逐的记录视为活跃。

### 1.4 `crystallized.py` — 新方法：`confirm_provisional_record()`

**文件**：`plugins/memory/memory_os/crystallized.py`  
**类**：`CrystallizedMemoryService`

```python
def confirm_provisional_record(
    self,
    record_id: str,
    *,
    confirmed_by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
```

行为：
- 将 `provisional` 设置为 `false`（移除临时标记）
- 清除 `expires_at` 字段
- 如果存在，将 `canonical_state` 从 `"provisional"` 恢复为 `"active"`
- 添加 `confirmed_at`、`confirmed_by` 字段
- 追加审计条目

### 1.5 新查询方法：`list_provisional_records()`

**文件**：`plugins/memory/memory_os/crystallized.py`  
**类**：`CrystallizedMemoryService`

```python
def list_provisional_records(self) -> list[dict[str, Any]]:
```

返回所有具有 `provisional=True` 且 `canonical_state` 未过期/未驱逐的活跃记录。`provisional_sweep` 使用此方法查找其操作目标。

### 1.6 `resolver_gate.py` — 新：`_resolver_verdict()`（P3 最小版）

**文件**：`plugins/memory/memory_os/resolver_gate.py`

```python
def _resolver_verdict(
    candidate: CrystallizedCandidate,
    *,
    store: MemoryOSStore,
) -> dict[str, Any]:
    """P3 minimal: resolver_eligible gate + simple LLM verdict.

    The LLM only sees candidates that pass the deterministic gate.
    Full cascade_routing_policy/provisional integration in P4.
    """
    if not resolver_eligible(candidate, store=store):
        return {"approve": False, "reason": "failed_resolver_gate"}

    # LLM call within the safety envelope
    # Simple prompt: "Should this memory be auto-approved as provisional?"
    # Returns {"approve": bool, "reason": str}
    ...
```

**关键**：`_resolver_verdict` 的存在使得 P3 可端到端测试。调用者（`candidate_aggregation`）不需要知道门控已完成而判决是桩。

### 1.7 `candidate_aggregation.py` — Resolver routing 注入

**文件**：`plugins/modules/governance/candidate_aggregation.py`  
**函数**：`_cluster_and_promote()`（第 197–292 行）

在 `_cluster_and_promote` 的 promote 循环内的重复数据删除检查（第 260–273 行）之后、`append_candidate_triage`（第 274 行）之前插入 resolver routing：

```python
for member in promote_batch:
    # Existing dedup check (lines 260-273) — UNCHANGED
    dedup_hit = _check_index_dedup(store, member)
    if dedup_hit is not None:
        # ... existing demote logic unchanged ...
        continue

    # ── NEW: Resolver routing ──
    verdict = _resolver_verdict(member, store=store)
    if verdict.get("approve"):
        target_state = "resolver_approved"
        # Open ExecutionGate permit for the crystallized write
        envelope = start_resolver_auto_approve_envelope(
            store,
            candidate_id=member.candidate_id,
            sensitivity=member.sensitivity,
            has_identity_signal=_has_identity_signal(member.body, member.tags or []),
            bridge_state=member.bridge_state,
        )
        # Write the approved record as provisional
        now = datetime.now(timezone.utc)
        decision = ApprovalDecision(
            candidate_id=member.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=now.isoformat(),
            note=verdict.get("reason", ""),
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(days=7)).isoformat(),
            recurrence=0,  # P5 will compute actual recurrence
        )
        crystallized_service.write_approved_record(
            member, decision, file_name="owner_approved.md"
        )
        complete_execution_gate_envelope(
            store,
            envelope_id=envelope["execution_gate_envelope_id"],
            lane_id=RESOLVER_AUTO_APPROVE_LANE,
            execution_status="completed",
            postcheck={"crystallized_write": "success"},
        )
    else:
        target_state = "owner_eligible"

    # Existing append_candidate_triage call — CHANGED: dynamic target_state
    append_candidate_triage(
        store,
        candidate_id=member.candidate_id,
        action="promote",
        target_state=target_state,  # ← was hardcoded "owner_eligible"
        reason=reason,
        cluster_key=cluster_key,
        execution_gate_envelope_id=envelope_id,
        now=_now,
    )
```

### 1.8 `provisional_sweep.py`（新文件）

**文件**：`plugins/modules/governance/provisional_sweep.py`

独立模块，拥有自己的清单、`run_once`、`status`、`doctor` 入口点。遵循 `crystallized_revalidator.py` 模块结构。

清单：

```python
def provisional_sweep_manifest() -> dict[str, Any]:
    return {
        "name": "provisional_sweep",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "execution_gate"],
        },
        "provides": {
            "commands": ["status", "doctor", "run_once"],
            "writes": ["local_artifact.provisional_sweep_runs"],
        },
        "defaults": {"enabled": True},
    }
```

`ProvisionalSweepModule.run_once()`：

```python
def run_once(self, *, store: MemoryOSStore) -> dict[str, Any]:
    """Run one tick: TTL expiry → cap eviction → recurrence detection."""
    service = CrystallizedMemoryService(store)
    records = service.list_provisional_records()
    now = datetime.now(timezone.utc)

    # 1. TTL expiry
    expired = 0
    for r in records:
        expires_at = r.get("expires_at", "")
        if expires_at and _parse_iso(expires_at) <= now:
            if not r.get("owner_confirmed"):
                service.invalidate_provisional_record(
                    r["id"], reason="resolver_ttl_expired"
                )
                expired += 1

    # 2. Cap eviction (oldest first, keep 30)
    evicted = 0
    active = [r for r in records if _is_active_provisional(r)]
    if len(active) > 30:
        active.sort(key=lambda r: r.get("approved_at", ""))
        for r in active[:len(active) - 30]:
            service.invalidate_provisional_record(
                r["id"], reason="resolver_cap_evicted"
            )
            evicted += 1

    # 3. Recurrence detection (mark for P5 digest escalation)
    escalated = _detect_recurrence(active)

    return {
        "provisional_total": len(records),
        "expired_count": expired,
        "evicted_count": evicted,
        "escalated_count": len(escalated),
        ...
    }
```

### 1.9 ExecutionGate 集成

**无新增**。P2 已添加：
- `execution_gate.py` 中的 `RESOLVER_AUTO_APPROVE_LANE = "resolver_auto_approve"`
- `execution_gate.py` 中的 `start_resolver_auto_approve_envelope()`
- `execution_gate.py` 中的 `RESOLVER_AUTO_APPROVE_RISK_CLASS = "reversible_llm_auto_approval"`

P3 使用这些现有原语。所有写入通过 `write_approved_record`（现有门控路径）或 `invalidate_provisional_record`（遵循与 `revoke_record`/`demote_record` 相同的 .md 重写模式，这些已在范围外）。`write_surface_check`：无新分类（无新 JSONL 写入目标）。

---

### 1.10 `canonical_state` 值矩阵

| 场景 | `canonical_state` | `provisional` | `expires_at` | INACTIVE？ |
|---|---|---|---|---|
| 新建临时记录 | `"active"`（默认） | `true` | `now+7d` | 否 |
| TTL 过期 | `"provisional_expired"` | `true`（保留） | 原值（保留） | **是** |
| 上限驱逐 | `"provisional_cap_evicted"` | `true`（保留） | 原值（保留） | **是** |
| Owner 确认（P5） | `"active"`（默认） | `false` | 已清除 | 否 |
| Owner 拒绝（P5） | `"provisional_rejected"` | `true`（保留） | 原值（保留） | **是** |

`INACTIVE_CANONICAL_STATES` 值（最终）：`{"owner_revoked", "revoked", "demoted", "provisional_expired", "provisional_cap_evicted", "provisional_rejected"}`。`"provisional_rejected"` 在 P3 中预留但未使用（P5 添加 owner-reject 操作时使用）。

---

## 2. 数据流

```
candidate_aggregation._cluster_and_promote
  └─ promote loop (per member)
       ├─ _check_index_dedup (existing)
       ├─ _resolver_verdict(member)       ← NEW: gate + LLM
       ├─ [if approve] start_resolver_auto_approve_envelope  ← P2
       ├─ [if approve] write_approved_record(provisional=True) ← MODIFIED
       ├─ [if approve] complete_execution_gate_envelope       ← P2
       └─ append_candidate_triage(target_state=dynamic)      ← MODIFIED

cognitive_loop (tick)
  └─ provisional_sweep.run_once()
       ├─ list_provisional_records      ← NEW query
       ├─ TTL expiry → invalidate_provisional_record  ← NEW
       ├─ Cap eviction → invalidate_provisional_record ← NEW
       └─ Recurrence detection → mark escalated       ← NEW (signal only, P5 acts)
```

---

## 3. 文件映射

| 文件 | 操作 | 目的 |
|---|---|---|
| `plugins/memory/memory_os/approval.py` | **修改** | 添加 `provisional`、`expires_at`、`recurrence` 字段到 `ApprovalDecision` |
| `plugins/memory/memory_os/crystallized.py` | **修改** | `write_approved_record` 写入临时前端元数据；新方法：`invalidate_provisional_record`、`confirm_provisional_record`、`list_provisional_records` |
| `plugins/memory/memory_os/resolver_gate.py` | **修改** | 添加 `_resolver_verdict()`（P3 最小版，门控 + 简单 LLM） |
| `plugins/modules/governance/candidate_aggregation.py` | **修改** | 将 resolver routing 插入 `_cluster_and_promote` promote 循环 |
| `plugins/modules/governance/provisional_sweep.py` | **创建** | 新模块：清单、`run_once`、`status`、`doctor`、TTL/上限/复发 |
| `tests/plugins/memory/test_memory_os_crystallized.py` | **修改** | 测试临时写入、invalidate、confirm、list |
| `tests/plugins/memory/test_memory_os_resolver_gate.py` | **修改** | 测试 `_resolver_verdict`（门控 FAIL → 拒绝，PASS → LLM 调用） |
| `tests/system_modularization/test_provisional_sweep_module.py` | **创建** | 测试 TTL 过期、上限驱逐、复发检测 |
| `tests/plugins/memory/test_candidate_aggregation_logic.py` | **修改** | 测试 resolver routing 注入（动态 target_state） |
| `tests/plugins/memory/test_memory_os_approval.py` | **修改** | 测试新 `ApprovalDecision` 字段默认值 |

---

## 4. 测试断言（RED-first）

```
P3 范围内：
R2.1  resolver verdict approve → crystallized record written with provisional=True,
      expires_at=now+7d, approved_by="resolver", bridge_state="resolver_approved"
R2.3  TTL expired + not owner_confirmed → invalidate(reason=resolver_ttl_expired),
      canonical_state="provisional_expired", record retained (not deleted)
R2.4  active provisionals > 30 → oldest evicted(reason=resolver_cap_evicted),
      canonical_state="provisional_cap_evicted", count drops to 30
R2.5  list_provisional_records() returns active provisional records only
      (excludes those in INACTIVE_CANONICAL_STATES)
R2.6  Non-resolver-eligible candidate → still routes to owner_eligible (not approved)
R2.7  write_approved_record with provisional=True sets provisional+expires_at;
      with provisional=False (default) does NOT add provisional keys
R2.8  INACTIVE_CANONICAL_STATES contains provisional_expired + provisional_cap_evicted
      (is_active_crystallized_frontmatter returns False for these)

P5 范围内（所有者操作，不在 P3 中测试）：
R2.2a owner confirm → provisional=False, expires_at cleared, confirmed_at set
R2.2b owner reject → invalidate, canonical_state="provisional_rejected", audit exists

守卫：
G.1   All resolver writes go through write_approved_record + ExecutionGate
      (write_surface_check unclassified_count=0)
G.2   resolver_eligible is the only path to resolver_approved
      (no other code path sets bridge_state="resolver_approved")
G.3   Invalidated provisional records persist in crystallized .md files
      (invalidate ≠ delete)
```

---

## 5. 边界与非目标

**在范围内（P3）：**
- `ApprovalDecision` 字段扩展
- `write_approved_record` 临时前端元数据写入
- `invalidate_provisional_record` + `confirm_provisional_record` 方法
- `list_provisional_records` 查询
- `_resolver_verdict`（最小：门控 + LLM 安全调用）
- `candidate_aggregation` 中的 Resolver routing 注入（动态 target_state）
- `provisional_sweep` 模块（TTL + 上限驱逐 + 复发标记）
- 所有操作的 ExecutionGate 包装

**不在范围内（P4）：**
- 完整的 `cascade_routing_policy` 集成（在 `_resolver_verdict` 中查找）
- 完整的 `provisional` 模块集成（在 `_resolver_verdict` 中查找）
- 路由阈值来自 cascade 策略

**不在范围内（P5）：**
- 带有倒计时的 Owner 摘要
- Prefetch 临时注入 + 权重排序
- 复发逃生阀（摘要升级 + 延长 expires_at）
- Owner confirm/reject 操作 UI

---

## 6. INV 合规性

- **INV-5（无 LLM 热路径）**：`_resolver_verdict` 从 `candidate_aggregation`（离线通道）而非 prefetch 调用
- **INV-7（ExecutionGate）**：所有 resolver 写入通过 `start_resolver_auto_approve_envelope` 打开许可
- **INV-8（StructuralWriteGate）**：`write_approved_record` 通过现有门控 `.md` 写入路径
- **INV-1（可逆）**：所有临时操作使用 invalidate-not-delete；canonical 记录留存
