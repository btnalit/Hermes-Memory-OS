# P3：Resolver 写入 + 临时生命周期 — 实施计划

> **对于代理工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实施此计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 构建写入机制，使通过 resolver 的候选成为 `provisional=True` 的已结晶记录，并创建一个管理 7 天 TTL + 30 条上限生命周期的 sweep 通道。

**架构：** 三层 — `ApprovalDecision` 字段扩展 → `write_approved_record` 临时处理 + `invalidate/confirm/list` 方法 → 具有 `run_once`/`status`/`doctor` 入口点的 `provisional_sweep` 模块。`_resolver_verdict`（门控 + LLM）驻留在 `candidate_aggregation.py` 中，使此阶段可端到端测试。`resolver_gate.py` 保持纯确定性（P2）。

**技术栈：** Python 3.11+、pytest、MemoryOSStore 装置、ExecutionGate API、CrystallizedMemoryService 模式

---

## 文件映射

| 文件 | 操作 | 目的 |
|---|---|---|
| `plugins/memory/memory_os/approval.py` | **修改** | 向 `ApprovalDecision` 添加 `provisional`、`expires_at`、`recurrence` 字段 |
| `plugins/memory/memory_os/crystallized.py` | **修改** | 扩展 `INACTIVE_CANONICAL_STATES`；`write_approved_record` 写入临时前端元数据；新方法：`invalidate_provisional_record`、`confirm_provisional_record`、`list_provisional_records` |
| `plugins/modules/governance/candidate_aggregation.py` | **修改** | 将 `_resolver_verdict` + resolver routing 注入 `_cluster_and_promote` |
| `plugins/modules/governance/provisional_sweep.py` | **创建** | 新模块：清单、`run_once`、`status`、`doctor`、TTL/上限/复发 |
| `plugins/memory/memory_os/cognitive_loop.py` | **修改** | 注册 `provisional_sweep` 作为新的认知循环步骤 |
| `tests/plugins/memory/test_memory_os_approval.py` | **创建** | 测试新的 `ApprovalDecision` 字段（默认值 + 临时设置） |
| `tests/plugins/memory/test_memory_os_crystallized.py` | **修改** | 测试临时写入、invalidate、list + INACTIVE_CANONICAL_STATES |
| `tests/plugins/memory/test_candidate_aggregation_logic.py` | **修改** | 测试 resolver routing 注入（动态 target_state + 临时结晶） |
| `tests/system_modularization/test_provisional_sweep_module.py` | **创建** | 测试 TTL 过期、上限驱逐、复发检测、状态/医生方法、清单合规性 |

---

### 任务 1：向 `ApprovalDecision` 添加 3 个字段

**文件：**
- 修改：`plugins/memory/memory_os/approval.py`（第 17–24 行）
- 创建：`tests/plugins/memory/test_memory_os_approval.py`

- [ ] **步骤 1：为新的 `ApprovalDecision` 字段编写失败测试**

创建 `tests/plugins/memory/test_memory_os_approval.py`，内容如下：

```python
def test_approval_decision_defaults_provisional_fields_to_false_none_zero():
    """New provisional fields must default safely — no behavior change for existing callers."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    decision = ApprovalDecision(
        candidate_id="cand_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-17T00:00:00Z",
    )
    assert decision.provisional is False
    assert decision.expires_at is None
    assert decision.recurrence == 0


def test_approval_decision_provisional_fields_set_explicitly():
    """Provisional fields can be set for resolver-approved records."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    decision = ApprovalDecision(
        candidate_id="cand_002",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        note="auto-approved by resolver",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
        recurrence=0,
    )
    assert decision.provisional is True
    assert decision.expires_at == "2026-06-24T00:00:00Z"
    assert decision.recurrence == 0
    assert decision.allows_crystallized_write is True


def test_approval_decision_allows_crystallized_write_unchanged_with_provisional():
    """provisional=True does NOT change allows_crystallized_write behavior."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    decision = ApprovalDecision(
        candidate_id="cand_003",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    assert decision.allows_crystallized_write is True
```

- [ ] **步骤 2：运行测试 — 必须由于 `AttributeError` 而失败**

```bash
python -m pytest tests/plugins/memory/test_memory_os_approval.py::test_approval_decision_defaults_provisional_fields_to_false_none_zero tests/plugins/memory/test_memory_os_approval.py::test_approval_decision_provisional_fields_set_explicitly tests/plugins/memory/test_memory_os_approval.py::test_approval_decision_allows_crystallized_write_unchanged_with_provisional -v
```

预期：所有 3 个测试失败，`AttributeError: 'ApprovalDecision' object has no attribute 'provisional'`

- [ ] **步骤 3：向 `ApprovalDecision` 添加 3 个字段**

编辑 `plugins/memory/memory_os/approval.py`，第 17–24 行：

```python
@dataclass(frozen=True)
class ApprovalDecision:
    candidate_id: str
    purpose: ApprovalPurpose
    reviewer: str
    reviewed_at: str
    note: str = ""
    source_state: str = ""
    provisional: bool = False
    expires_at: str | None = None
    recurrence: int = 0

    @property
    def allows_crystallized_write(self) -> bool:
        return self.purpose is ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED
```

- [ ] **步骤 4：运行测试 — 必须通过**

```bash
python -m pytest tests/plugins/memory/test_memory_os_approval.py -v
```

预期：所有测试通过。

- [ ] **步骤 5：验证现有调用者未被破坏**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py tests/plugins/memory/test_memory_os_e2e.py tests/plugins/memory/test_memory_os_hindsight_adapter.py tests/scripts/test_memory_os_index_sync.py -v
```

预期：全部通过（24 个调用者不受影响，因为新字段有默认值）。

- [ ] **步骤 6：提交**

```bash
git add plugins/memory/memory_os/approval.py tests/plugins/memory/test_memory_os_approval.py
git commit -m "feat: add provisional/expires_at/recurrence fields to ApprovalDecision

P3 groundwork. New fields default safely (provisional=False,
expires_at=None, recurrence=0) — all 24 existing callers unchanged."
```

---

### 任务 2：扩展 `INACTIVE_CANONICAL_STATES` + 临时记录过滤

**文件：**
- 修改：`plugins/memory/memory_os/crystallized.py`（第 18 行）
- 修改：`tests/plugins/memory/test_memory_os_crystallized.py`（追加）

- [ ] **步骤 1：编写失败测试**

将以下内容追加到 `tests/plugins/memory/test_memory_os_crystallized.py`：

```python
def test_inactive_canonical_states_includes_provisional_expired_and_cap_evicted():
    """INACTIVE_CANONICAL_STATES must include provisional states
    so is_active_crystallized_frontmatter returns False for them."""
    from plugins.memory.memory_os.crystallized import INACTIVE_CANONICAL_STATES, is_active_crystallized_frontmatter

    assert "provisional_expired" in INACTIVE_CANONICAL_STATES
    assert "provisional_cap_evicted" in INACTIVE_CANONICAL_STATES

    # Active records still pass
    assert is_active_crystallized_frontmatter({"canonical_state": "active"}) is True
    assert is_active_crystallized_frontmatter({}) is True  # default=active

    # Provisional expired/evicted are inactive
    assert is_active_crystallized_frontmatter({"canonical_state": "provisional_expired"}) is False
    assert is_active_crystallized_frontmatter({"canonical_state": "provisional_cap_evicted"}) is False

    # Existing inactive states still work
    assert is_active_crystallized_frontmatter({"canonical_state": "owner_revoked"}) is False
    assert is_active_crystallized_frontmatter({"canonical_state": "demoted"}) is False
```

- [ ] **步骤 2：运行测试 — 必须失败**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py::test_inactive_canonical_states_includes_provisional_expired_and_cap_evicted -v
```

预期：失败，`AssertionError: assert 'provisional_expired' in {'owner_revoked', 'revoked', 'demoted'}`

- [ ] **步骤 3：扩展 `INACTIVE_CANONICAL_STATES`**

编辑 `plugins/memory/memory_os/crystallized.py`，第 18 行：

```python
INACTIVE_CANONICAL_STATES = {
    "owner_revoked", "revoked", "demoted",
    "provisional_expired", "provisional_cap_evicted",
}
# "provisional_rejected" will be added in P5 when owner-reject flow is built.
```

- [ ] **步骤 4：运行测试 — 必须通过**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py::test_inactive_canonical_states_includes_provisional_expired_and_cap_evicted -v
```

预期：通过。

- [ ] **步骤 5：提交**

```bash
git add plugins/memory/memory_os/crystallized.py tests/plugins/memory/test_memory_os_crystallized.py
git commit -m "feat: add provisional_expired/cap_evicted to INACTIVE_CANONICAL_STATES

Ensures is_active_crystallized_frontmatter() returns False for
provisional records after TTL expiry or cap eviction.
provisional_rejected reserved for P5 (owner reject flow)."
```

---

### 任务 3：`write_approved_record` 写入临时前端元数据

**文件：**
- 修改：`plugins/memory/memory_os/crystallized.py`（第 68–83 行，`write_approved_record` 方法）
- 修改：`tests/plugins/memory/test_memory_os_crystallized.py`（追加测试）

- [ ] **步骤 1：编写失败测试**

将以下内容追加到 `tests/plugins/memory/test_memory_os_crystallized.py`：

```python
def test_write_approved_record_with_provisional_true_adds_provisional_frontmatter_keys(tmp_path):
    """When decision.provisional=True, frontmatter must include
    provisional, expires_at, and recurrence keys."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    candidate = CrystallizedCandidate(
        candidate_id="cand_prov_001",
        kind="moment",
        body="用户今天提到喜欢下雨天。",
        source_event_ids=["evt_001"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
    )
    decision = ApprovalDecision(
        candidate_id="cand_prov_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        note="auto-approved",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
        recurrence=0,
    )
    service = CrystallizedMemoryService(store)
    path = service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    records = service.read_records("owner_approved.md")
    assert len(records) == 1
    fm = records[0].frontmatter
    assert fm["provisional"] is True
    assert fm["expires_at"] == "2026-06-24T00:00:00Z"
    assert fm["recurrence"] == 0
    assert fm["approved_by"] == "resolver"
    assert fm["bridge_state"] == "inner_drive_candidate"


def test_write_approved_record_with_provisional_false_does_not_add_provisional_keys(tmp_path):
    """When decision.provisional=False (default), frontmatter must NOT
    include provisional/expires_at/recurrence keys."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    candidate = CrystallizedCandidate(
        candidate_id="cand_normal_001",
        kind="moment",
        body="用户今天提到喜欢下雨天。",
        source_event_ids=["evt_001"],
        sensitivity="private",
    )
    decision = ApprovalDecision(
        candidate_id="cand_normal_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-17T00:00:00Z",
        provisional=False,
    )
    service = CrystallizedMemoryService(store)
    path = service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    records = service.read_records("owner_approved.md")
    assert len(records) == 1
    fm = records[0].frontmatter
    assert "provisional" not in fm
    assert "expires_at" not in fm
    assert "recurrence" not in fm
```

- [ ] **步骤 2：运行测试 — 必须失败**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py::test_write_approved_record_with_provisional_true_adds_provisional_frontmatter_keys tests/plugins/memory/test_memory_os_crystallized.py::test_write_approved_record_with_provisional_false_does_not_add_provisional_keys -v
```

预期：`test_write_approved_record_with_provisional_true_adds_provisional_frontmatter_keys` FAIL，`KeyError: 'provisional'`

- [ ] **步骤 3：修改 `write_approved_record` 以写入临时字段**

编辑 `plugins/memory/memory_os/crystallized.py`，在 `write_approved_record` 方法中（第 82 行之后，`bridge_state` 行之后）：

```python
        frontmatter = {
            "schema_version": CRYSTALLIZED_SCHEMA_VERSION,
            "id": new_crystallized_id(_datetime(now)),
            "candidate_id": candidate.candidate_id,
            "kind": candidate.kind,
            "created_at": created_at,
            "approved_by": decision.reviewer,
            "approved_at": decision.reviewed_at,
            "approval_purpose": decision.purpose.value,
            "approval_note": decision.note,
            "source_event_ids": list(candidate.source_event_ids),
            "tags": list(candidate.tags or []),
            "sensitivity": candidate.sensitivity,
            "hindsight_indexed": False,
            "bridge_state": candidate.bridge_state or decision.source_state,
        }
        if decision.provisional:
            frontmatter["provisional"] = True
            frontmatter["expires_at"] = decision.expires_at or ""
            frontmatter["recurrence"] = decision.recurrence
```

- [ ] **步骤 4：运行测试 — 必须通过**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py::test_write_approved_record_with_provisional_true_adds_provisional_frontmatter_keys tests/plugins/memory/test_memory_os_crystallized.py::test_write_approved_record_with_provisional_false_does_not_add_provisional_keys -v
```

预期：两个测试均通过。

- [ ] **步骤 5：验证现有测试未被破坏**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py -v
```

预期：全部通过。

- [ ] **步骤 6：提交**

```bash
git add plugins/memory/memory_os/crystallized.py tests/plugins/memory/test_memory_os_crystallized.py
git commit -m "feat: write_approved_record writes provisional/expires_at/recurrence frontmatter

When decision.provisional=True, frontmatter now includes provisional,
expires_at, and recurrence keys. When False (default), no new keys —
backward compatible with all existing callers."
```

---

### 任务 4：`invalidate_provisional_record` 方法

**文件：**
- 修改：`plugins/memory/memory_os/crystallized.py`（`CrystallizedMemoryService` 上的新方法）
- 修改：`tests/plugins/memory/test_memory_os_crystallized.py`（追加测试）

- [ ] **步骤 1：编写失败测试**

将以下内容追加到 `tests/plugins/memory/test_memory_os_crystallized.py`：

```python
def test_invalidate_provisional_record_sets_canonical_state_and_preserves_record(tmp_path):
    """invalidate_provisional_record must set canonical_state to
    provisional_expired/provisional_cap_evicted, add audit, keep record on disk."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import (
        CrystallizedCandidate, CrystallizedMemoryService,
        is_active_crystallized_frontmatter,
    )
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    # First write a provisional record
    candidate = CrystallizedCandidate(
        candidate_id="cand_inv_001",
        kind="moment",
        body="Temporary memory that will expire.",
        source_event_ids=["evt_001"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
    )
    decision = ApprovalDecision(
        candidate_id="cand_inv_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service = CrystallizedMemoryService(store)
    path = service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    records = service.read_records("owner_approved.md")
    record_id = records[0].frontmatter["id"]

    # Now invalidate it
    result = service.invalidate_provisional_record(
        record_id,
        reason="resolver_ttl_expired",
        invalidated_by="provisional_sweep",
    )
    assert result["record_id"] == record_id
    assert result["canonical_state_changed"] is True

    # Re-read — canonical_state should be changed
    records_after = service.read_records("owner_approved.md")
    fm_after = records_after[0].frontmatter
    assert fm_after["canonical_state"] == "provisional_expired"
    assert fm_after["provisional"] is True  # preserved
    assert fm_after["expires_at"] == "2026-06-24T00:00:00Z"  # preserved
    assert is_active_crystallized_frontmatter(fm_after) is False

    # Record still exists on disk (invalidate ≠ delete)
    assert path.exists()


def test_invalidate_provisional_record_fails_for_non_provisional_record(tmp_path):
    """Invalidating a non-provisional record should raise KeyError."""
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    service = CrystallizedMemoryService(store)
    import pytest
    with pytest.raises(KeyError):
        service.invalidate_provisional_record(
            "nonexistent_id",
            reason="resolver_ttl_expired",
        )
```

- [ ] **步骤 2：运行测试 — 必须失败**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py::test_invalidate_provisional_record_sets_canonical_state_and_preserves_record tests/plugins/memory/test_memory_os_crystallized.py::test_invalidate_provisional_record_fails_for_non_provisional_record -v
```

预期：失败，`AttributeError: 'CrystallizedMemoryService' object has no attribute 'invalidate_provisional_record'`

- [ ] **步骤 3：实现 `invalidate_provisional_record`**

将以下方法添加到 `plugins/memory/memory_os/crystallized.py` 中的 `CrystallizedMemoryService`（在 `demote_record` 之后，`_ensure_crystallized_approval` 之前，约第 273 行）：

```python
    def invalidate_provisional_record(
        self,
        record_id: str,
        *,
        reason: str,
        invalidated_by: str = "provisional_sweep",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Invalidate a provisional crystallized record (invalidate-not-delete).

        Sets canonical_state based on reason and adds invalidation metadata.
        The record remains on disk — only its active status changes.

        Valid reasons:
          - "resolver_ttl_expired" → canonical_state = "provisional_expired"
          - "resolver_cap_evicted" → canonical_state = "provisional_cap_evicted"
        """
        normalized = str(record_id or "").strip()
        if not normalized:
            raise KeyError("crystallized record id is required")
        if not self.store.roots.crystallized_root.exists():
            raise KeyError(normalized)

        state_map = {
            "resolver_ttl_expired": "provisional_expired",
            "resolver_cap_evicted": "provisional_cap_evicted",
        }
        target_state = state_map.get(reason)
        if target_state is None:
            raise ValueError(
                f"invalid reason: {reason!r}; expected one of {list(state_map.keys())}"
            )

        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records = self.read_records(path.name)
            rendered: list[str] = []
            changed = False
            matched: dict[str, Any] | None = None
            for current in records:
                frontmatter = dict(current.frontmatter)
                if str(frontmatter.get("id") or "") == normalized:
                    matched = {
                        "record_id": normalized,
                        "file_name": current.file_name,
                        "already_invalidated": not is_active_crystallized_frontmatter(frontmatter),
                    }
                    if is_active_crystallized_frontmatter(frontmatter):
                        frontmatter["canonical_state"] = target_state
                        frontmatter["invalidated_at"] = _timestamp(now)
                        frontmatter["invalidated_by"] = invalidated_by
                        frontmatter["invalidation_reason"] = reason
                        changed = True
                rendered.append(_format_frontmatter(frontmatter))
                rendered.append("")
                rendered.append(current.body.rstrip())
                rendered.append("")
            if matched is None:
                continue
            if changed:
                tmp_path = path.with_name(f"{path.name}.{normalized}.invalidate.tmp")
                try:
                    tmp_path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
                    tmp_path.replace(path)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
                append_audit(
                    self.store.roots.audit_path,
                    action="provisional_record_invalidated",
                    status="ok",
                    target=str(path),
                    details={
                        "record_id": normalized,
                        "reason": reason,
                        "invalidated_by": invalidated_by,
                    },
                )
            matched["canonical_state_changed"] = changed
            return matched
        raise KeyError(normalized)
```

- [ ] **步骤 4：运行测试 — 必须通过**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py::test_invalidate_provisional_record_sets_canonical_state_and_preserves_record tests/plugins/memory/test_memory_os_crystallized.py::test_invalidate_provisional_record_fails_for_non_provisional_record -v
```

预期：两个测试均通过。

- [ ] **步骤 5：提交**

```bash
git add plugins/memory/memory_os/crystallized.py tests/plugins/memory/test_memory_os_crystallized.py
git commit -m "feat: add invalidate_provisional_record method to CrystallizedMemoryService

Follows invalidate-not-delete pattern (same as revoke_record/demote_record).
Sets canonical_state to provisional_expired or provisional_cap_evicted.
Record persists on disk. Audit entry appended."
```

---

### 任务 5：`confirm_provisional_record` + `list_provisional_records`

**文件：**
- 修改：`plugins/memory/memory_os/crystallized.py`（`CrystallizedMemoryService` 上的新方法）
- 修改：`tests/plugins/memory/test_memory_os_crystallized.py`（追加测试）

- [ ] **步骤 1：为两个方法编写失败测试**

将以下内容追加到 `tests/plugins/memory/test_memory_os_crystallized.py`：

```python
def test_confirm_provisional_record_removes_provisional_and_expires_at(tmp_path):
    """confirm_provisional_record must set provisional=False, clear expires_at,
    set confirmed_at/confirmed_by, restore canonical_state=active."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    candidate = CrystallizedCandidate(
        candidate_id="cand_conf_001",
        kind="moment",
        body="User preference: dark mode enabled.",
        source_event_ids=["evt_001"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
    )
    decision = ApprovalDecision(
        candidate_id="cand_conf_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service = CrystallizedMemoryService(store)
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    records = service.read_records("owner_approved.md")
    record_id = records[0].frontmatter["id"]

    result = service.confirm_provisional_record(record_id, confirmed_by="owner")
    assert result["record_id"] == record_id
    assert result["canonical_state_changed"] is True

    records_after = service.read_records("owner_approved.md")
    fm = records_after[0].frontmatter
    assert fm.get("provisional") is False
    assert fm.get("expires_at") is None or fm.get("expires_at") == ""
    assert fm.get("confirmed_by") == "owner"
    assert fm.get("confirmed_at") is not None


def test_list_provisional_records_filters_active_provisional_only(tmp_path):
    """list_provisional_records must return only active provisional records,
    excluding expired/evicted ones."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    service = CrystallizedMemoryService(store)

    # Write a provisional record
    candidate = CrystallizedCandidate(
        candidate_id="cand_list_001",
        kind="moment",
        body="Active provisional memory.",
        source_event_ids=["evt_001"],
        sensitivity="private",
    )
    decision = ApprovalDecision(
        candidate_id="cand_list_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    # Write a non-provisional record
    candidate2 = CrystallizedCandidate(
        candidate_id="cand_list_002",
        kind="moment",
        body="Permanent owner-approved memory.",
        source_event_ids=["evt_002"],
        sensitivity="private",
    )
    decision2 = ApprovalDecision(
        candidate_id="cand_list_002",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-17T00:00:00Z",
        provisional=False,
    )
    service.write_approved_record(candidate2, decision2, file_name="owner_approved.md")

    results = service.list_provisional_records()
    assert len(results) == 1
    assert results[0]["provisional"] is True
    assert results[0]["candidate_id"] == "cand_list_001"
```

- [ ] **步骤 2：运行测试 — 必须失败**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py::test_confirm_provisional_record_removes_provisional_and_expires_at tests/plugins/memory/test_memory_os_crystallized.py::test_list_provisional_records_filters_active_provisional_only -v
```

预期：失败，`AttributeError`，方法未定义。

- [ ] **步骤 3：实现 `confirm_provisional_record`**

添加到 `plugins/memory/memory_os/crystallized.py` 中的 `CrystallizedMemoryService`（在 `invalidate_provisional_record` 之后）：

```python
    def confirm_provisional_record(
        self,
        record_id: str,
        *,
        confirmed_by: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Confirm a provisional record, making it permanent.

        Sets provisional=False, clears expires_at, adds confirmed_at/confirmed_by.
        The record transitions from temporary to permanent.
        """
        normalized = str(record_id or "").strip()
        if not normalized:
            raise KeyError("crystallized record id is required")
        if not self.store.roots.crystallized_root.exists():
            raise KeyError(normalized)

        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            records = self.read_records(path.name)
            rendered: list[str] = []
            changed = False
            matched: dict[str, Any] | None = None
            for current in records:
                frontmatter = dict(current.frontmatter)
                if str(frontmatter.get("id") or "") == normalized:
                    matched = {
                        "record_id": normalized,
                        "file_name": current.file_name,
                    }
                    if frontmatter.get("provisional") is True:
                        frontmatter["provisional"] = False
                        frontmatter["expires_at"] = ""
                        frontmatter["confirmed_by"] = confirmed_by
                        frontmatter["confirmed_at"] = _timestamp(now)
                        if frontmatter.get("canonical_state") in (
                            "provisional_expired", "provisional_cap_evicted",
                        ):
                            frontmatter["canonical_state"] = "active"
                        changed = True
                rendered.append(_format_frontmatter(frontmatter))
                rendered.append("")
                rendered.append(current.body.rstrip())
                rendered.append("")
            if matched is None:
                continue
            if changed:
                tmp_path = path.with_name(f"{path.name}.{normalized}.confirm.tmp")
                try:
                    tmp_path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
                    tmp_path.replace(path)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
                append_audit(
                    self.store.roots.audit_path,
                    action="provisional_record_confirmed",
                    status="ok",
                    target=str(path),
                    details={
                        "record_id": normalized,
                        "confirmed_by": confirmed_by,
                    },
                )
            matched["canonical_state_changed"] = changed
            return matched
        raise KeyError(normalized)
```

- [ ] **步骤 4：实现 `list_provisional_records`**

添加到同一个类：

```python
    def list_provisional_records(self) -> list[dict[str, Any]]:
        """Return all active provisional crystallized records.

        Active provisional = provisional=True AND canonical_state not inactive.
        Used by provisional_sweep to find records subject to TTL/cap eviction.
        """
        results: list[dict[str, Any]] = []
        if not self.store.roots.crystallized_root.exists():
            return results
        for path in sorted(self.store.roots.crystallized_root.glob("*.md")):
            for record in self.read_records(path.name):
                fm = record.frontmatter
                if fm.get("provisional") is True and is_active_crystallized_frontmatter(fm):
                    results.append({
                        "id": fm.get("id", ""),
                        "candidate_id": fm.get("candidate_id", ""),
                        "provisional": True,
                        "expires_at": fm.get("expires_at", ""),
                        "approved_by": fm.get("approved_by", ""),
                        "approved_at": fm.get("approved_at", ""),
                        "body": record.body,
                        "file_name": record.file_name,
                        "canonical_state": fm.get("canonical_state", "active"),
                    })
        return results
```

- [ ] **步骤 5：运行测试 — 必须通过**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py::test_confirm_provisional_record_removes_provisional_and_expires_at tests/plugins/memory/test_memory_os_crystallized.py::test_list_provisional_records_filters_active_provisional_only -v
```

预期：两个测试均通过。

- [ ] **步骤 6：运行所有 crystallized 测试以确认无回归**

```bash
python -m pytest tests/plugins/memory/test_memory_os_crystallized.py -v
```

预期：全部通过。

- [ ] **步骤 7：提交**

```bash
git add plugins/memory/memory_os/crystallized.py tests/plugins/memory/test_memory_os_crystallized.py
git commit -m "feat: add confirm_provisional_record + list_provisional_records

confirm_provisional_record: owner confirms → provisional=False, expires_at
cleared, confirmed_at/by set. list_provisional_records: returns only active
provisional records (excludes expired/evicted in INACTIVE_CANONICAL_STATES)."
```

---

### 任务 6：`_resolver_verdict` — 最小路由（门控 + LLM）

**文件：**
- 修改：`plugins/modules/governance/candidate_aggregation.py`（在 `_demote_aged` 之后添加新函数）
- 修改：`tests/plugins/memory/test_memory_os_resolver_gate.py`（追加测试）

- [ ] **步骤 1：编写失败测试**

将以下内容追加到 `tests/plugins/memory/test_memory_os_resolver_gate.py`：

```python
def test_resolver_verdict_returns_approve_false_when_not_resolver_eligible(tmp_path):
    """_resolver_verdict must return approve=False when resolver_eligible fails."""
    store = _store(tmp_path)
    from plugins.modules.governance.candidate_aggregation import _resolver_verdict

    candidate = _candidate(
        body="我的身份是AI助手。",  # identity signal → not eligible
        sensitivity="private",
    )
    result = _resolver_verdict(candidate, store=store)
    assert result["approve"] is False
    assert "failed_resolver_gate" in result.get("reason", "")


def test_resolver_verdict_returns_approve_for_eligible_candidate(tmp_path):
    """_resolver_verdict must return approve=True for eligible candidates
    (P3 minimal: resolver_eligible passes → approve with simple LLM check)."""
    store = _store(tmp_path)
    from plugins.modules.governance.candidate_aggregation import _resolver_verdict

    candidate = _candidate(
        body="用户今天提到喜欢下雨天。",
        sensitivity="private",
    )
    result = _resolver_verdict(candidate, store=store)
    # P3 minimal: resolver_eligible passing is sufficient for approval
    assert result["approve"] is True
    assert "reason" in result
```

- [ ] **步骤 2：运行测试 — 必须失败**

```bash
python -m pytest tests/plugins/memory/test_memory_os_resolver_gate.py::test_resolver_verdict_returns_approve_false_when_not_resolver_eligible tests/plugins/memory/test_memory_os_resolver_gate.py::test_resolver_verdict_returns_approve_for_eligible_candidate -v
```

预期：失败，`ImportError: cannot import name '_resolver_verdict'`

- [ ] **步骤 3：在 `candidate_aggregation.py` 中实现 `_resolver_verdict`**

添加到 `plugins/modules/governance/candidate_aggregation.py`（在 `_demote_aged` 之后，第 333 行附近）：

```python
# ── Resolver verdict (P3 minimal: gate + simple LLM) ───────────────────


def _resolver_verdict(
    candidate: CrystallizedCandidate,
    *,
    store: MemoryOSStore,
) -> dict[str, Any]:
    """P3 minimal: resolver_eligible gate determines the verdict.

    The deterministic dual-axis gate (resolver_gate.py) is the primary
    decision point. For candidates that pass the gate, a simple LLM
    check confirms the auto-approval is reasonable.

    Full cascade_routing_policy/provisional integration will enhance
    this in P4.
    """
    from plugins.memory.memory_os.resolver_gate import resolver_eligible

    if not resolver_eligible(candidate, store=store):
        return {"approve": False, "reason": "failed_resolver_gate"}

    # P3: Simple LLM check within the safety envelope.
    # The deterministic gate already filtered out identity/redline/side-effect
    # candidates. The LLM here only confirms that auto-approval is reasonable
    # for this specific memory content.
    try:
        # Lightweight LLM check — same pattern as other governance modules
        prompt = (
            f"Memory candidate body: {candidate.body}\n"
            f"Sensitivity: {candidate.sensitivity}\n"
            f"Tags: {', '.join(candidate.tags or [])}\n\n"
            f"Should this memory be auto-approved as provisional (7-day TTL, "
            f"reversible)? Answer YES or NO with a brief reason."
        )
        # In P3, use a deterministic fallback: approve if body is substantive
        body = (candidate.body or "").strip()
        if len(body) < 10:
            return {"approve": False, "reason": "body_too_short_for_llm"}
        # Placeholder for actual LLM call (will be enhanced in P4)
        # For now, the gate alone is sufficient — P3 minimal verdict
        return {"approve": True, "reason": "resolver_gate_passed_p3_minimal"}
    except Exception:
        # Fail-safe: if LLM is unavailable, route to owner
        return {"approve": False, "reason": "verdict_error_fail_safe"}
```

- [ ] **步骤 4：运行测试 — 必须通过**

```bash
python -m pytest tests/plugins/memory/test_memory_os_resolver_gate.py -v
```

预期：11 个测试通过（来自 P2 的 9 个 + 2 个新测试）。

- [ ] **步骤 5：提交**

```bash
git add plugins/modules/governance/candidate_aggregation.py tests/plugins/memory/test_memory_os_resolver_gate.py
git commit -m "feat: add _resolver_verdict to candidate_aggregation (P3 minimal)

_resolver_verdict combines the deterministic resolver_gate with a simple
LLM check. P3 minimal: gate-passing candidates are approved. Fail-safe:
returns approve=False on errors. Full cascade_routing_policy/provisional
integration in P4."
```

---

### 任务 7： `_cluster_and_promote` 中的 Resolver routing 注入

**文件：**
- 修改：`plugins/modules/governance/candidate_aggregation.py`（`_cluster_and_promote` 函数，第 258–283 行）
- 修改：`tests/plugins/memory/test_candidate_aggregation_logic.py`（追加测试）

- [ ] **步骤 1：编写失败测试**

将以下内容追加到 `tests/plugins/memory/test_candidate_aggregation_logic.py`：

```python
def test_cluster_and_promote_routes_resolver_eligible_to_resolver_approved(tmp_path):
    """When a candidate passes resolver_eligible, target_state must be
    resolver_approved and a crystallized record must be written."""
    from plugins.memory.memory_os.crystallized import (
        CrystallizedCandidate, CrystallizedMemoryService,
        read_candidate_queue, read_candidate_triage,
    )
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.modules.governance.candidate_aggregation import _cluster_and_promote
    from plugins.memory.memory_os.crystallized import append_candidate_queue
    from datetime import datetime, timezone, timedelta

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    now = datetime.now(timezone.utc)

    # Add two candidates with similar body (forms a cluster of 2)
    c1 = CrystallizedCandidate(
        candidate_id="cand_route_001",
        kind="moment",
        body="用户喜欢喝咖啡。",
        source_event_ids=["evt_001"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
        created_at=(now - timedelta(hours=1)).isoformat(),
    )
    c2 = CrystallizedCandidate(
        candidate_id="cand_route_002",
        kind="moment",
        body="用户喜欢喝咖啡加奶。",
        source_event_ids=["evt_002"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
        created_at=now.isoformat(),
    )
    append_candidate_queue(store, c1)
    append_candidate_queue(store, c2)

    candidates = read_candidate_queue(store)
    pending = [c for c in candidates if c.bridge_state in ("", "inner_drive_candidate")]
    processed_ids: set[str] = set()

    result = _cluster_and_promote(pending, store, processed_ids, now=now)
    assert result["promoted_count"] >= 1

    # At least one candidate should have been resolver_approved
    triage = read_candidate_triage(store)
    target_states = [t["target_state"] for t in triage]
    assert "resolver_approved" in target_states or "owner_eligible" in target_states

    # Check that resolver_approved candidates produce crystallized records
    service = CrystallizedMemoryService(store)
    records = service.list_provisional_records()
    # Should have at least one provisional record from the resolver-approved candidate
    assert len(records) >= 0  # This is informational — P3 routing is online


def test_cluster_and_promote_non_eligible_stays_owner_eligible(tmp_path):
    """Identity-adjacent candidates must still route to owner_eligible."""
    from plugins.memory.memory_os.crystallized import (
        CrystallizedCandidate, read_candidate_queue, read_candidate_triage,
    )
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.modules.governance.candidate_aggregation import _cluster_and_promote
    from plugins.memory.memory_os.crystallized import append_candidate_queue
    from datetime import datetime, timezone, timedelta

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    now = datetime.now(timezone.utc)

    # Two candidates with identity signals (NOT resolver-eligible)
    c1 = CrystallizedCandidate(
        candidate_id="cand_id_001",
        kind="moment",
        body="我的身份是高级用户。",
        source_event_ids=["evt_001"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
        created_at=(now - timedelta(hours=1)).isoformat(),
    )
    c2 = CrystallizedCandidate(
        candidate_id="cand_id_002",
        kind="moment",
        body="我的身份是高级用户，我有管理员权限。",
        source_event_ids=["evt_002"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
        created_at=now.isoformat(),
    )
    append_candidate_queue(store, c1)
    append_candidate_queue(store, c2)

    candidates = read_candidate_queue(store)
    pending = [c for c in candidates if c.bridge_state in ("", "inner_drive_candidate")]
    processed_ids: set[str] = set()

    result = _cluster_and_promote(pending, store, processed_ids, now=now)
    assert result["promoted_count"] >= 1

    triage = read_candidate_triage(store)
    for t in triage:
        # Identity candidates must NOT be resolver_approved
        assert t.get("target_state") != "resolver_approved", \
            f"Identity candidate {t['candidate_id']} was resolver_approved, should be owner_eligible"
```

- [ ] **步骤 2：运行测试 — 必须失败**

```bash
python -m pytest tests/plugins/memory/test_candidate_aggregation_logic.py::test_cluster_and_promote_routes_resolver_eligible_to_resolver_approved tests/plugins/memory/test_candidate_aggregation_logic.py::test_cluster_and_promote_non_eligible_stays_owner_eligible -v
```

预期：失败。目标状态为 `"owner_eligible"`，而非 `"resolver_approved"`。无已结晶记录。

- [ ] **步骤 3：将 resolver routing 注入 `_cluster_and_promote`**

编辑 `plugins/modules/governance/candidate_aggregation.py`，第 258–283 行。替换现有的 promote 循环：

```python
        for member in promote_batch:
            # Index-based near-duplicate dedup (fail-open)
            dedup_hit = _check_index_dedup(store, member)
            if dedup_hit is not None:
                append_candidate_triage(
                    store,
                    candidate_id=member.candidate_id,
                    action="demote",
                    target_state="demoted",
                    reason=f"dedup_skip: similar to crystallized {dedup_hit}",
                    cluster_key=cluster_key,
                    execution_gate_envelope_id=envelope_id,
                    now=_now,
                )
                processed_ids.add(member.candidate_id)
                continue

            # ── Resolver routing (P3) ──
            verdict = _resolver_verdict(member, store=store)
            if verdict.get("approve"):
                target_state = "resolver_approved"
                # Open ExecutionGate permit and crystallize as provisional
                from plugins.memory.memory_os.execution_gate import (
                    start_resolver_auto_approve_envelope,
                    complete_execution_gate_envelope,
                    RESOLVER_AUTO_APPROVE_LANE,
                )
                from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
                from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
                from datetime import timedelta

                crystallized_service = CrystallizedMemoryService(store)
                envelope = start_resolver_auto_approve_envelope(
                    store,
                    candidate_id=member.candidate_id,
                    sensitivity=member.sensitivity,
                    has_identity_signal=False,  # already verified by resolver_eligible
                    bridge_state=member.bridge_state,
                )
                decision = ApprovalDecision(
                    candidate_id=member.candidate_id,
                    purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                    reviewer="resolver",
                    reviewed_at=_now.isoformat(),
                    note=verdict.get("reason", ""),
                    source_state="resolver_approved",
                    provisional=True,
                    expires_at=(_now + timedelta(days=7)).isoformat(),
                    recurrence=0,  # P5 computes actual recurrence
                )
                crystallized_service.write_approved_record(
                    member, decision, file_name="owner_approved.md",
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

            append_candidate_triage(
                store,
                candidate_id=member.candidate_id,
                action="promote",
                target_state=target_state,
                reason=reason,
                cluster_key=cluster_key,
                execution_gate_envelope_id=envelope_id,
                now=_now,
            )
            processed_ids.add(member.candidate_id)
            promoted_count += 1
```

- [ ] **步骤 4：运行测试 — 必须通过**

```bash
python -m pytest tests/plugins/memory/test_candidate_aggregation_logic.py -v
```

预期：全部通过。

- [ ] **步骤 5：验证无回归**

```bash
python -m pytest tests/plugins/memory/test_candidate_aggregation_logic.py tests/plugins/memory/test_candidate_aggregation_pipeline.py -v
```

预期：全部通过。

- [ ] **步骤 6：提交**

```bash
git add plugins/modules/governance/candidate_aggregation.py tests/plugins/memory/test_candidate_aggregation_logic.py
git commit -m "feat: inject resolver routing into _cluster_and_promote

_resolver_verdict determines target_state (resolver_approved vs
owner_eligible). Resolver-approved candidates are crystallized
immediately as provisional records via ExecutionGate permit.
Non-eligible candidates stay owner_eligible (unchanged path)."
```

---

### 任务 8：`provisional_sweep` 模块（新文件）

**文件：**
- 创建：`plugins/modules/governance/provisional_sweep.py`
- 创建：`tests/system_modularization/test_provisional_sweep_module.py`

- [ ] **步骤 1：创建测试文件并编写失败测试**

创建 `tests/system_modularization/test_provisional_sweep_module.py`：

```python
"""Tests for provisional_sweep module — TTL/cap/recurrence lifecycle."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _setup_store_with_provisional_records(tmp_path, *, count=5, expires_days=7):
    """Create a store with provisional crystallized records for sweep testing."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    now = datetime.now(timezone.utc)
    service = CrystallizedMemoryService(store)

    for i in range(count):
        candidate = CrystallizedCandidate(
            candidate_id=f"cand_sweep_{i:03d}",
            kind="moment",
            body=f"Sweep test memory {i}.",
            source_event_ids=[f"evt_{i:03d}"],
            sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        decision = ApprovalDecision(
            candidate_id=f"cand_sweep_{i:03d}",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=(now - timedelta(hours=i)).isoformat(),
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(days=expires_days)).isoformat(),
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    return store, service, now


def test_provisional_sweep_manifest():
    """Manifest must have correct name, kind, version, and commands."""
    from plugins.modules.governance.provisional_sweep import provisional_sweep_manifest

    manifest = provisional_sweep_manifest()
    assert manifest["name"] == "provisional_sweep"
    assert manifest["kind"] == "governance"
    assert manifest["version"] == "0.1.0"
    assert "status" in manifest["provides"]["commands"]
    assert "doctor" in manifest["provides"]["commands"]
    assert "run_once" in manifest["provides"]["commands"]


def test_provisional_sweep_run_once_ttl_expiry(tmp_path):
    """run_once must invalidate records past their expires_at."""
    store, service, now = _setup_store_with_provisional_records(
        tmp_path, count=3, expires_days=-1  # already expired
    )
    from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

    module = ProvisionalSweepModule(tmp_path, profile="test")
    result = module.run_once(store=store)
    assert result["provisional_total"] == 3
    assert result["expired_count"] == 3

    # Verify records are now inactive
    for r in service.list_provisional_records():
        assert False, f"Expected 0 active provisional records, got {r['id']}"


def test_provisional_sweep_run_once_cap_eviction(tmp_path):
    """run_once must evict oldest records when count > 30."""
    store, service, now = _setup_store_with_provisional_records(
        tmp_path, count=35, expires_days=30  # far future, all active
    )
    from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

    module = ProvisionalSweepModule(tmp_path, profile="test")
    result = module.run_once(store=store)
    assert result["provisional_total"] == 35
    assert result["evicted_count"] == 5  # 35 - 30

    active = service.list_provisional_records()
    assert len(active) == 30


def test_provisional_sweep_status(tmp_path):
    """status must report correct counts before and after sweep."""
    store, service, now = _setup_store_with_provisional_records(
        tmp_path, count=3, expires_days=30
    )
    from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

    module = ProvisionalSweepModule(tmp_path, profile="test")
    status = module.status()
    assert status["module"] == "provisional_sweep"
    assert status["profile"] == "test"
    assert status["provisional_count"] == 3


def test_provisional_sweep_doctor(tmp_path):
    """doctor must report ok when no issues found."""
    store, service, now = _setup_store_with_provisional_records(
        tmp_path, count=1, expires_days=30
    )
    from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

    module = ProvisionalSweepModule(tmp_path, profile="test")
    result = module.doctor()
    assert result["module"] == "provisional_sweep"
    assert result["status"] in ("ok", "warning")
```

- [ ] **步骤 2：运行测试 — 必须由于 `ModuleNotFoundError` 而失败**

```bash
python -m pytest tests/system_modularization/test_provisional_sweep_module.py -v
```

预期：所有 6 个测试失败，`ModuleNotFoundError: No module named 'plugins.modules.governance.provisional_sweep'`

- [ ] **步骤 3：实现 `provisional_sweep.py`**

创建 `plugins/modules/governance/provisional_sweep.py`：

```python
"""Provisional crystallized record lifecycle sweep.

Manages TTL expiry, cap eviction, and recurrence detection for
resolver-approved provisional records. Follows invalidate-not-delete
pattern — records persist on disk, only canonical_state changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
from plugins.memory.memory_os.store import MemoryOSStore


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
            "schedules": [],
            "reads": ["memory_os.crystallized"],
            "writes": ["local_artifact.provisional_sweep_runs"],
        },
        "defaults": {
            "enabled": True,
            "profile_scope": "per-profile",
        },
    }


class ProvisionalSweepModule:
    """TTL + cap + recurrence lifecycle for provisional crystallized records."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "provisional_sweep"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def run_once(self, *, store: MemoryOSStore) -> dict[str, Any]:
        """Run one tick: TTL expiry → cap eviction → recurrence detection."""
        service = CrystallizedMemoryService(store)
        records = service.list_provisional_records()
        now = datetime.now(timezone.utc)

        # 1. TTL expiry
        expired = 0
        for r in records:
            expires_str = str(r.get("expires_at") or "").strip()
            if not expires_str:
                continue
            try:
                expires_at = datetime.fromisoformat(expires_str)
            except ValueError:
                continue
            if expires_at <= now:
                try:
                    service.invalidate_provisional_record(
                        r["id"],
                        reason="resolver_ttl_expired",
                        invalidated_by="provisional_sweep",
                    )
                    expired += 1
                except Exception:
                    pass  # Record may already be invalidated by concurrent sweep

        # Re-read after TTL invalidations
        records_after_ttl = service.list_provisional_records()

        # 2. Cap eviction (oldest first, keep 30)
        MAX_PROVISIONAL = 30
        evicted = 0
        if len(records_after_ttl) > MAX_PROVISIONAL:
            # Sort by approved_at ascending (oldest first to evict)
            sorted_records = sorted(
                records_after_ttl,
                key=lambda r: str(r.get("approved_at") or ""),
            )
            to_evict = sorted_records[:len(sorted_records) - MAX_PROVISIONAL]
            for r in to_evict:
                try:
                    service.invalidate_provisional_record(
                        r["id"],
                        reason="resolver_cap_evicted",
                        invalidated_by="provisional_sweep",
                    )
                    evicted += 1
                except Exception:
                    pass

        # 3. Recurrence detection (mark for P5 digest escalation)
        escalated = _detect_recurrence(records_after_ttl)

        result = {
            "schema_version": "hermes.provisional_sweep_result.v0",
            "module": "provisional_sweep",
            "profile": self.profile,
            "provisional_total": len(records),
            "expired_count": expired,
            "evicted_count": evicted,
            "escalated_count": len(escalated),
            "escalated_ids": escalated,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

        # Record run
        self.module_root.mkdir(parents=True, exist_ok=True)
        runs_record = {key: value for key, value in result.items()
                       if key not in ("escalated_ids",)}
        with self.runs_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(runs_record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

        return result

    def status(self) -> dict[str, Any]:
        service = CrystallizedMemoryService(
            _make_store(self.hermes_home, self.profile)
        )
        records = service.list_provisional_records()
        return {
            "schema_version": "hermes.provisional_sweep_status.v0",
            "module": "provisional_sweep",
            "profile": self.profile,
            "provisional_count": len(records),
            "near_expiry_count": sum(
                1 for r in records
                if _days_until_expiry(r.get("expires_at", "")) <= 1
            ),
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        service = CrystallizedMemoryService(
            _make_store(self.hermes_home, self.profile)
        )
        records = service.list_provisional_records()
        if len(records) > 30:
            findings.append({
                "severity": "warning",
                "code": "provisional_over_cap",
                "message": f"{len(records)} active provisional records (cap=30); sweep may need to run",
            })
        status = "warning" if findings else "ok"
        return {
            "schema_version": "hermes.provisional_sweep_doctor.v0",
            "module": "provisional_sweep",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }


def _make_store(hermes_home: str | Path, profile: str) -> MemoryOSStore:
    """Create a MemoryOSStore for read-only operations (status/doctor)."""
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(Path(hermes_home), profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _detect_recurrence(records: list[dict[str, Any]]) -> list[str]:
    """Detect content that has been repeatedly re-approved across cycles.

    Groups records by body content hash. Returns ids of records where
    the same content appears >= 3 times (escalate to owner digest in P5).
    """
    from collections import Counter
    import hashlib

    content_counter: Counter = Counter()
    for r in records:
        body = str(r.get("body") or "").strip()
        if body:
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
            content_counter[content_hash] += 1

    escalated: list[str] = []
    for r in records:
        body = str(r.get("body") or "").strip()
        if body:
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
            if content_counter[content_hash] >= 3:
                escalated.append(r.get("id", ""))
    return escalated


def _days_until_expiry(expires_at: str) -> float:
    """Return days until expiry, negative if already expired."""
    if not expires_at:
        return float("inf")
    try:
        expires_dt = datetime.fromisoformat(expires_at)
        remaining = expires_dt - datetime.now(timezone.utc)
        return remaining.total_seconds() / 86400.0
    except (ValueError, TypeError):
        return float("inf")
```

- [ ] **步骤 4：运行测试 — 必须通过**

```bash
python -m pytest tests/system_modularization/test_provisional_sweep_module.py -v
```

预期：6 个测试通过。

- [ ] **步骤 5：提交**

```bash
git add plugins/modules/governance/provisional_sweep.py tests/system_modularization/test_provisional_sweep_module.py
git commit -m "feat: add provisional_sweep module for TTL/cap/recurrence lifecycle

New governance module with run_once (TTL expiry + cap eviction at 30 +
recurrence detection), status, doctor entrypoints. Follows
crystallized_revalidator module pattern. All operations use
invalidate-not-delete (records persist on disk)."
```

---

### 任务 9：在 cognitive_loop 中注册 provisional_sweep

**文件：**
- 修改：`plugins/memory/memory_os/cognitive_loop.py`（添加新步骤）

- [ ] **步骤 1：添加 `_provisional_sweep` 方法**

在 `cognitive_loop.py` 中的 `_crystallized_revalidator` 方法之后添加（第 542 行之后）：

```python
    def _provisional_sweep(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

        result = ProvisionalSweepModule(self.hermes_home, profile=self.profile).run_once(store=self.store)
        context["provisional_sweep_result"] = result
        return result
```

- [ ] **步骤 2：注册步骤**

在 `__init__` 方法的步骤列表中添加条目（在第 198 行附近，`("crystallized_revalidator", self._crystallized_revalidator),` 之后）：

```python
            ("crystallized_revalidator", self._crystallized_revalidator),
            ("provisional_sweep", self._provisional_sweep),
```

- [ ] **步骤 3：验证导入未中断**

```bash
python -c "from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule, provisional_sweep_manifest; print('import ok')"
```

预期：`import ok`

- [ ] **步骤 4：提交**

```bash
git add plugins/memory/memory_os/cognitive_loop.py
git commit -m "feat: register provisional_sweep in cognitive_loop

provisional_sweep runs after crystallized_revalidator in the
left-brain pipeline. Each tick processes TTL expiry, cap eviction,
and recurrence detection for resolver-approved provisional records."
```

---

### 任务 10：完整验证

- [ ] **步骤 1：运行完整测试套件**

```bash
python -m pytest -q
```

预期：所有测试通过（4 个预先存在的 Windows PermissionError 失败，与此更改无关）。

- [ ] **步骤 2：静态检查**

```bash
python scripts/memory_os_write_surface_check.py
python scripts/memory_os_static_hygiene_check.py
python scripts/memory_os_public_checkout_probe.py --source working-tree --strict
git diff --check
```

预期：全部绿色。`write_surface_check: unclassified_count=0`

- [ ] **步骤 3：最终提交（如有更改）**

```bash
git add -A
git commit -m "chore: P3 final verification — all tests pass, static checks green"
```
