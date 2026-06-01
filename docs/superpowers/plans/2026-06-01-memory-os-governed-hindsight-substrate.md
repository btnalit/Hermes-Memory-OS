# Governed Hindsight Substrate for Memory-OS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hindsight an optional, governed Memory-OS substrate: existing Hermes Hindsight installs are adopted into Memory-OS control safely, while ordinary open-source installs keep Hindsight off until an operator enables it.

**Architecture:** Hermes keeps owning the host runtime, platform transport, one external `MemoryProvider` slot, built-in `MEMORY.md` / `USER.md`, `session_search`, and `context.engine`. Memory-OS remains the selected external provider (`memory.provider=memory_os`) and owns the governance layer, canonical store, substrate routing, LocalArtifact-first recall, Hindsight retain/recall/reflect policy, projection coherence, monitor evidence, and rollback gates. Hindsight is never used through Hermes' direct `memory.provider=hindsight` path in production Memory-OS mode; Memory-OS connects to Hindsight itself through a governed substrate client and treats Hindsight as an advisory derived projection of approved canonical state, never as an authority above local crystallized/owner-approved facts.

**Tech Stack:** Python 3.11+, Hermes Agent 0.15.x `MemoryProvider`, Memory-OS JSON config under `$HERMES_HOME/memory-os/config.json`, optional Hindsight HTTP/local client config under `$HERMES_HOME/hindsight/config.json`, Bash installer, pytest, `hermes memory-os-agent-os` shell command.

---

## Preflight Record

```yaml
source_of_truth:
  - docs/memory-os-hermes-integration-boundary-design-v3.md
  - docs/memory-os-substrate-provider-interface-design-v2.md
  - docs/configuration.md
  - Hermes Agent 0.15.1/0.15.2 source: agent/memory_provider.py, agent/context_engine.py, agent/memory_manager.py
  - live read-only evidence from hermes-media 10.20.3.200 on 2026-06-01
finding_type: integration/deployment contract gap
owning_seam:
  - Hermes memory.provider external provider slot
  - Memory-OS MemorySubstrateProvider contract and router config
  - Memory-OS installer adoption path
  - Memory-OS automated deployment orchestration path
  - Memory-OS monitor and upgrade compatibility checks
reverse_scope: adapt host runtime; do not fork Hermes; do not use Hermes direct Hindsight provider as the active provider
equivalent_contract_or_project_contract:
  - docs/memory-os-substrate-provider-interface-design-v2.md §7 retain/recall/reflect
  - docs/memory-os-substrate-provider-interface-design-v2.md §8 projection consistency
  - this plan's MemorySubstrateProvider implementation contract
evidence_loop:
  - local pytest for config, substrate, installer, CLI, monitor
  - local pytest for deployment plan/preflight/dry-run/apply/postcheck classification
  - read-only upgrade compatibility check
  - deployed shadow/adopt smoke before active recall
monitor_or_validation_fields:
  - deploy_phase
  - deploy_profile
  - preflight_compat_status
  - install_dry_run_status
  - postcheck_compat_status
  - restart_requested
  - rollback_hint
  - substrate_providers.hindsight.enabled
  - substrate_snapshot_id
  - retain_source_class
  - no_raw_retained
  - raw_retained_count
  - retract_count
  - recall_mode
  - recall_triggered_by
  - recall_llm_triggered
  - local_first_authority_preserved
  - fallback_triggered_count
  - reflect_enabled
  - reflect_hot_path_count
  - projection_stale_count
  - kill_switch_forced_disabled
  - legacy_provider_was_hindsight
user_visible_surface: Hermes operator CLI and owner review digest only when owner-facing action is explicitly enabled; Hindsight substrate evidence is operator-facing until owner-approved promotion
deployed_smoke: read-only status/doctor + dry-run adopt + shadow recall on hermes-media; no service restart until owner approves
promotion_signal: local tests PASS, deployment dry-run PASS, upgrade compat PASS, ledger-derived raw_retained_count=0, projection_stale_count=0, Hindsight bank passes pollution scan, shadow recall has bounded coverage without monitor FAIL
stop_or_rollback_signal: deploy preflight FAIL in upgrade profile, install dry-run FAIL, postcheck compat FAIL, raw turn retention detected, direct provider still active after Memory-OS enablement, Hindsight health failure without deterministic fallback, secret printed in report, doctor error finding
external_review: before installer default change; before enabling active Hindsight recall on any live host
```

## Current Facts To Preserve

- Hermes 0.15 allows only one external memory provider at a time. Memory-OS must stay in that slot as `memory.provider=memory_os`.
- Built-in Hermes `MEMORY.md` and `USER.md` are separate from the external provider and remain active when `memory_enabled` / `user_profile_enabled` are true.
- Hermes `context.engine` is also a single active engine, currently `compressor` on `hermes-media`; it can coexist with Memory-OS but is not a second memory provider.
- Hermes 0.15.1 wraps recalled memory as `authoritative reference data`; Memory-OS output must therefore carry its own advisory/provenance/confidence language instead of relying on the host to mark recall as non-authoritative.
- Hermes direct Hindsight provider has an `auto_retain` path that can retain conversation turns. Memory-OS must not activate this direct provider in production governed mode.
- Live `hermes-media` state on 2026-06-01: Hermes `v0.15.1`, `memory.provider=memory_os`, `context.engine=compressor`, built-in memory enabled, Hindsight config present with `auto_retain=false`, Memory-OS doctor/status OK, upgrade compatibility check PASS.
- V2 requires LocalArtifact to remain the precision-first primary recall source. Hindsight recall is always `advisory_only=true` and `authority_class=derived_projection`, including after promotion from `shadow` to `active`.
- V2 §8 requires retain to have a retract/invalidate counterpart. When `crystallized_revalidator` demotes a crystallized record or an owner revokes approval, the corresponding Hindsight projection must be marked invalid within the configured coherence window.
- Monitor booleans must be derived from ledger/audit records. Fields such as `no_raw_retained`, `recall_llm_triggered`, and `reflect_off_hot_path` cannot be hard-coded assertions.
- Automated deployment needs two compatibility profiles: `upgrade` requires preflight compatibility before apply; `fresh` allows pre-install provider mismatch but requires post-install compatibility to pass.

## Non-Goals

- Do not fork Hermes Agent.
- Do not make `memory.provider=hindsight` part of the Memory-OS production path.
- Do not write raw session transcripts, raw events, tool outputs, cron chatter, mailbox chatter, or unapproved candidates into Hindsight.
- Do not enable reflect on the hot path.
- Do not let Hindsight outrank local crystallized or owner-approved Memory-OS artifacts.
- Do not add Mem0, TemporalGraph, or another external substrate implementation in this slice; the generic seam must be ready for them, but Hindsight is the only non-local external implementation here.
- Do not restart live Hermes services as part of implementation tests.
- Do not make automated deployment restart Hermes by default. Restart requires an explicit operator flag and an explicit restart command.
- Do not print Hindsight API keys, tokens, cookies, private config, or raw memory bodies in CLI reports.

## File Map

- `plugins/memory/memory_os/config.py`: add substrate config normalization and defaults.
- `plugins/memory/memory_os/substrates/__init__.py`: new substrate package exports.
- `plugins/memory/memory_os/substrates/base.py`: provider-neutral protocols and dataclasses for capability, health, facts, snapshots, and operation records.
- `plugins/memory/memory_os/substrates/ledger.py`: append-only substrate operation ledger used by monitor and upgrade checks.
- `plugins/memory/memory_os/substrates/local_artifact.py`: LocalArtifact recall provider backed by canonical/crystallized Memory-OS records; primary authority for precision-first recall.
- `plugins/memory/memory_os/substrates/projection.py`: projection reference and invalidation helpers for derived substrates.
- `plugins/memory/memory_os/substrates/hindsight.py`: governed Hindsight config, client, retain/recall/reflect facade, health, redaction helpers.
- `plugins/memory/memory_os/substrates/router.py`: capability router and deterministic fallback status.
- `plugins/memory/memory_os/adapters/hindsight.py`: keep export-only behavior; delegate safe payload building to the governed substrate where useful.
- `plugins/modules/governance/crystallized_revalidator.py`: trigger Hindsight projection invalidation when canonical records are demoted or owner approval is revoked.
- `plugins/modules/governance/live_guard.py`: expose kill-switch state to substrate creation.
- `plugins/memory/memory_os/cli.py`: add `hindsight` subcommands and improve doctor semantics.
- `plugins/memory/memory_os/__init__.py`: expose substrate status in `memory_os_status`; do not inject active Hindsight recall until configured.
- `plugins/memory/memory_os/prefetch.py`: record Hindsight shadow recall metadata only when configured; keep live prompt injection local/deterministic unless promoted.
- `scripts/install_memory_os.sh`: add `--hindsight auto|off|adopt|wizard`.
- `scripts/install_memory_os_plugin.py`: adopt legacy Hermes Hindsight config into Memory-OS config without enabling direct Hermes Hindsight provider.
- `scripts/deploy_memory_os.py`: automate plan/preflight/dry-run/apply/postcheck around the installer and compatibility gate, locally or through SSH.
- `scripts/memory_os_upgrade_compat_check.py`: add read-only Hindsight substrate/adoption checks.
- `scripts/memory_os_3_200_monitor.py`: add provider/capability evidence fields.
- `docs/configuration.md`, `README.md`, `docs/quickstart.md`: document default off, adoption, wizard, and rollout gates.
- Tests:
  - `tests/plugins/memory/test_memory_os_hindsight_adapter.py`
  - `tests/plugins/memory/test_memory_os_substrate_base.py`
  - `tests/plugins/memory/test_memory_os_substrate_ledger.py`
  - `tests/plugins/memory/test_memory_os_local_artifact_provider.py`
  - `tests/plugins/memory/test_memory_os_projection_coherence.py`
  - `tests/plugins/memory/test_memory_os_hindsight_substrate_config.py`
  - `tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py`
  - `tests/plugins/memory/test_memory_os_substrate_router.py`
  - `tests/plugins/memory/test_memory_os_prefetch.py`
  - `tests/scripts/test_memory_os_plugin_install.py`
  - `tests/scripts/test_memory_os_deploy.py`
  - `tests/scripts/test_memory_os_upgrade_compat_check.py`
  - `tests/scripts/test_memory_os_3_200_monitor.py`
  - `tests/system_modularization/test_module_contracts.py`

---

## Review Amendments Integrated

This revision makes the external review feedback part of the implementation contract:

- **Projection coherence is required.** Hindsight retain must have an invalidate/retract path tied to canonical demotion and owner revocation.
- **Monitor fields are derived.** Safety booleans must be computed from substrate ledger records, not written as constants.
- **LocalArtifact stays primary.** Hindsight can be enabled and even promoted to active injection, but it remains advisory and cannot outrank local crystallized or owner-approved facts.
- **Provider keys are provider-neutral.** Config, status, and monitor use `substrate_providers.<provider>` with Hindsight as the first external provider implementation.
- **INV-6 / INV-8 are explicit.** Retain/recall/reflect/retract records carry `substrate_snapshot_id`, and the global kill switch forces every optional external substrate disabled.
- **Legacy keys converge.** `hindsight_adapter_enabled` becomes a compatibility input only; the effective source of truth is `substrate_providers.hindsight.*`.
- **Deployment is automated and classified.** The installer remains the low-level file/config writer; `scripts/deploy_memory_os.py` becomes the orchestration layer that runs plan, preflight, dry-run install, apply, and postcheck with distinct `fresh` and `upgrade` compatibility profiles.

## Implementation Closeout Gates

These are blocking implementation checks before the feature can be called complete:

- **All demotion/revoke paths invalidate projections.** The implementation must enumerate every public path that can demote crystallized state or revoke owner approval, including `crystallized_revalidator` and owner CLI/action handlers. Each path must either call the Hindsight projection invalidation hook after the canonical state transition succeeds, or explicitly prove that it cannot affect Hindsight-projected records.
- **Authority violations are FAIL, not telemetry.** `local_first_authority_preserved=false` or `external_authoritative_count>0` must classify as monitor/compat FAIL and stop promotion.
- **Stale projections are FAIL.** `projection_stale_count>0` must classify as monitor/compat FAIL and block active recall promotion.
- **Reflect promotion remains deferred.** Task 7 only permits reflect output as advisory, non-canonical evidence. Converting reflect output into candidates needs a later owner-gated slice with its own tests and monitor fields.

---

### Task 0: Establish Provider-Neutral Substrate Contract, Ledger, LocalArtifact, Snapshot, and Kill Switch

**Files:**
- Create: `plugins/memory/memory_os/substrates/base.py`
- Create: `plugins/memory/memory_os/substrates/ledger.py`
- Create: `plugins/memory/memory_os/substrates/local_artifact.py`
- Modify: `plugins/memory/memory_os/substrates/__init__.py`
- Test: `tests/plugins/memory/test_memory_os_substrate_base.py`
- Test: `tests/plugins/memory/test_memory_os_substrate_ledger.py`
- Test: `tests/plugins/memory/test_memory_os_local_artifact_provider.py`

- [ ] **Step 1: Write provider-neutral contract tests**

Create `tests/plugins/memory/test_memory_os_substrate_base.py`:

```python
from plugins.memory.memory_os.substrates.base import (
    GroundingFact,
    ProviderHealth,
    SubstrateSnapshot,
)


def test_grounding_fact_defaults_to_advisory_and_snapshot_bound():
    fact = GroundingFact(
        provider="hindsight",
        capability="recall",
        body_summary="approved fact",
        confidence=0.6,
        provenance="hindsight_recall",
        source_event_refs=["cmem_1"],
        substrate_snapshot_id="hindsight:bank:v7",
    )

    assert fact.advisory_only is True
    assert fact.authority_class == "derived_projection"
    assert fact.recall_llm_triggered is False
    assert fact.to_monitor_dict()["substrate_snapshot_id"] == "hindsight:bank:v7"


def test_local_fact_can_be_canonical_authority():
    fact = GroundingFact(
        provider="local_artifact",
        capability="recall",
        body_summary="owner approved local fact",
        confidence=0.95,
        provenance="crystallized",
        source_event_refs=["cmem_2"],
        substrate_snapshot_id="local:canonical:v12",
        advisory_only=False,
        authority_class="local_canonical",
    )

    assert fact.authority_class == "local_canonical"
    assert fact.advisory_only is False


def test_provider_health_reports_kill_switch_disabled():
    health = ProviderHealth(
        provider="hindsight",
        status="disabled",
        capabilities=[],
        reason="kill_switch_enabled",
        kill_switch_forced_disabled=True,
    )

    assert health.to_monitor_dict()["kill_switch_forced_disabled"] is True


def test_snapshot_id_is_stable_for_same_inputs():
    left = SubstrateSnapshot(provider="hindsight", source_ref="bank", version="7")
    right = SubstrateSnapshot(provider="hindsight", source_ref="bank", version="7")

    assert left.snapshot_id == right.snapshot_id
    assert left.snapshot_id.startswith("hindsight:")
```

- [ ] **Step 2: Write ledger derivation tests**

Create `tests/plugins/memory/test_memory_os_substrate_ledger.py`:

```python
from plugins.memory.memory_os.substrates.ledger import (
    SubstrateOperationLedger,
    derive_substrate_monitor_fields,
)


def test_monitor_fields_are_derived_from_operation_records(tmp_path):
    ledger = SubstrateOperationLedger(tmp_path / "substrate_operations.jsonl")
    ledger.append(
        {
            "provider": "hindsight",
            "operation": "retain",
            "source_class": "crystallized",
            "raw_body_included": False,
            "substrate_snapshot_id": "hindsight:bank:v1",
        }
    )
    ledger.append(
        {
            "provider": "hindsight",
            "operation": "recall",
            "recall_llm_triggered": False,
            "substrate_snapshot_id": "hindsight:bank:v1",
        }
    )
    ledger.append(
        {
            "provider": "hindsight",
            "operation": "reflect",
            "phase": "async",
            "substrate_snapshot_id": "hindsight:bank:v1",
        }
    )

    fields = derive_substrate_monitor_fields(ledger.read_all(), provider="hindsight")

    assert fields["retain_count"] == 1
    assert fields["raw_retained_count"] == 0
    assert fields["no_raw_retained"] is True
    assert fields["recall_llm_triggered"] is False
    assert fields["reflect_hot_path_count"] == 0
    assert fields["reflect_off_hot_path"] is True


def test_monitor_fields_fail_closed_when_raw_retain_is_recorded(tmp_path):
    ledger = SubstrateOperationLedger(tmp_path / "substrate_operations.jsonl")
    ledger.append(
        {
            "provider": "hindsight",
            "operation": "retain",
            "source_class": "raw_turn",
            "raw_body_included": True,
            "substrate_snapshot_id": "hindsight:bank:v2",
        }
    )

    fields = derive_substrate_monitor_fields(ledger.read_all(), provider="hindsight")

    assert fields["raw_retained_count"] == 1
    assert fields["no_raw_retained"] is False
```

- [ ] **Step 3: Write LocalArtifact primary tests**

Create `tests/plugins/memory/test_memory_os_local_artifact_provider.py`:

```python
from plugins.memory.memory_os.substrates.local_artifact import LocalArtifactProvider


class FakeStore:
    def __init__(self):
        self.records = [
            {
                "record_id": "cmem_1",
                "summary": "Apollo budget is owner approved",
                "source_event_refs": ["evt_1"],
                "state": "crystallized",
                "owner_approved": True,
                "version": "4",
            }
        ]

    def iter_crystallized_records(self):
        return iter(self.records)


def test_local_artifact_provider_returns_canonical_fact():
    provider = LocalArtifactProvider(FakeStore())

    facts = provider.recall("Apollo budget", consumer="grounded_expression")

    assert facts[0].provider == "local_artifact"
    assert facts[0].authority_class == "local_canonical"
    assert facts[0].advisory_only is False
    assert facts[0].confidence == 1.0
```

- [ ] **Step 4: Run tests to confirm they fail**

Run:

```bash
python -m pytest \
  tests/plugins/memory/test_memory_os_substrate_base.py \
  tests/plugins/memory/test_memory_os_substrate_ledger.py \
  tests/plugins/memory/test_memory_os_local_artifact_provider.py \
  -q
```

Expected: FAIL because the files do not exist.

- [ ] **Step 5: Implement provider-neutral base types**

Create `plugins/memory/memory_os/substrates/base.py`:

```python
"""Provider-neutral substrate contracts for governed Memory-OS recall."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SubstrateSnapshot:
    provider: str
    source_ref: str
    version: str

    @property
    def snapshot_id(self) -> str:
        return f"{self.provider}:{self.source_ref}:v{self.version}"


@dataclass(frozen=True)
class GroundingFact:
    provider: str
    capability: str
    body_summary: str
    confidence: float
    provenance: str
    source_event_refs: list[str]
    substrate_snapshot_id: str
    consumer: str = ""
    advisory_only: bool = True
    authority_class: str = "derived_projection"
    recall_llm_triggered: bool = False
    confab_flagged: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_monitor_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "capability": self.capability,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "consumer": self.consumer,
            "advisory_only": self.advisory_only,
            "authority_class": self.authority_class,
            "recall_llm_triggered": self.recall_llm_triggered,
            "confab_flagged": self.confab_flagged,
            "substrate_snapshot_id": self.substrate_snapshot_id,
            "source_event_ref_count": len(self.source_event_refs),
        }


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    status: str
    capabilities: list[str]
    reason: str = ""
    kill_switch_forced_disabled: bool = False
    substrate_snapshot_id: str = ""

    def to_monitor_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "capabilities": list(self.capabilities),
            "reason": self.reason,
            "kill_switch_forced_disabled": self.kill_switch_forced_disabled,
            "substrate_snapshot_id": self.substrate_snapshot_id,
        }


class MemorySubstrateProvider(Protocol):
    name: str

    def health(self) -> ProviderHealth:
        ...

    def recall(self, query: str, *, consumer: str) -> list[GroundingFact]:
        ...
```

- [ ] **Step 6: Implement append-only operation ledger**

Create `plugins/memory/memory_os/substrates/ledger.py`:

```python
"""Append-only substrate operation ledger for derived monitor evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SubstrateOperationLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
        return records


def derive_substrate_monitor_fields(records: list[dict[str, Any]], *, provider: str) -> dict[str, Any]:
    provider_records = [record for record in records if record.get("provider") == provider]
    retain_records = [record for record in provider_records if record.get("operation") == "retain"]
    recall_records = [record for record in provider_records if record.get("operation") == "recall"]
    reflect_records = [record for record in provider_records if record.get("operation") == "reflect"]
    retract_records = [record for record in provider_records if record.get("operation") in {"retract", "invalidate"}]
    raw_retain_records = [
        record
        for record in retain_records
        if record.get("raw_body_included") is True
        or str(record.get("source_class") or "") in {"raw", "raw_turn", "conversation_turn", "event", "working"}
    ]
    hot_reflect_records = [record for record in reflect_records if record.get("phase") == "hot_path"]
    latest_snapshot = ""
    for record in reversed(provider_records):
        latest_snapshot = str(record.get("substrate_snapshot_id") or "")
        if latest_snapshot:
            break
    return {
        "provider": provider,
        "retain_count": len(retain_records),
        "raw_retained_count": len(raw_retain_records),
        "no_raw_retained": len(raw_retain_records) == 0,
        "retract_count": len(retract_records),
        "recall_count": len(recall_records),
        "recall_llm_triggered": any(bool(record.get("recall_llm_triggered")) for record in recall_records),
        "reflect_count": len(reflect_records),
        "reflect_hot_path_count": len(hot_reflect_records),
        "reflect_off_hot_path": len(hot_reflect_records) == 0,
        "substrate_snapshot_id": latest_snapshot,
    }
```

- [ ] **Step 7: Implement LocalArtifact provider**

Create `plugins/memory/memory_os/substrates/local_artifact.py`:

```python
"""Local canonical artifact substrate.

This provider is the precision-first source. Optional external substrates such
as Hindsight can supplement it, but cannot outrank its canonical facts.
"""

from __future__ import annotations

from typing import Any

from .base import GroundingFact, ProviderHealth, SubstrateSnapshot


class LocalArtifactProvider:
    name = "local_artifact"

    def __init__(self, store: Any) -> None:
        self.store = store

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            status="ok",
            capabilities=["recall"],
            substrate_snapshot_id=SubstrateSnapshot(self.name, "canonical", "current").snapshot_id,
        )

    def recall(self, query: str, *, consumer: str) -> list[GroundingFact]:
        terms = {part.casefold() for part in str(query or "").split() if part.strip()}
        facts: list[GroundingFact] = []
        for record in self.store.iter_crystallized_records():
            summary = str(record.get("summary") or "")
            if terms and not any(term in summary.casefold() for term in terms):
                continue
            version = str(record.get("version") or "current")
            facts.append(
                GroundingFact(
                    provider=self.name,
                    capability="recall",
                    body_summary=summary,
                    confidence=1.0,
                    provenance="crystallized",
                    source_event_refs=[str(item) for item in record.get("source_event_refs", [])],
                    substrate_snapshot_id=SubstrateSnapshot(self.name, "canonical", version).snapshot_id,
                    consumer=consumer,
                    advisory_only=False,
                    authority_class="local_canonical",
                )
            )
        return facts
```

- [ ] **Step 8: Export base contract types**

Modify `plugins/memory/memory_os/substrates/__init__.py`:

```python
"""Governed optional memory substrates for Memory-OS."""

from .base import GroundingFact, MemorySubstrateProvider, ProviderHealth, SubstrateSnapshot
from .local_artifact import LocalArtifactProvider

__all__ = [
    "GroundingFact",
    "LocalArtifactProvider",
    "MemorySubstrateProvider",
    "ProviderHealth",
    "SubstrateSnapshot",
]
```

Task 2 extends this export list with Hindsight.

- [ ] **Step 9: Run base/local tests**

Run:

```bash
python -m pytest \
  tests/plugins/memory/test_memory_os_substrate_base.py \
  tests/plugins/memory/test_memory_os_substrate_ledger.py \
  tests/plugins/memory/test_memory_os_local_artifact_provider.py \
  -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add plugins/memory/memory_os/substrates tests/plugins/memory/test_memory_os_substrate_base.py tests/plugins/memory/test_memory_os_substrate_ledger.py tests/plugins/memory/test_memory_os_local_artifact_provider.py
git commit -m "feat: add memory substrate contract and local artifact provider"
```

---

### Task 1: Add Governed Hindsight Substrate Config

**Files:**
- Modify: `plugins/memory/memory_os/config.py`
- Create: `tests/plugins/memory/test_memory_os_hindsight_substrate_config.py`

- [ ] **Step 1: Write default-off config tests**

Create `tests/plugins/memory/test_memory_os_hindsight_substrate_config.py`:

```python
from plugins.memory.memory_os.config import load_config, save_config


def test_hindsight_substrate_defaults_to_disabled(tmp_path):
    config = load_config(tmp_path)

    hindsight = config["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is False
    assert hindsight["adoption_source"] == "none"
    assert hindsight["retain_enabled"] is False
    assert hindsight["recall_mode"] == "off"
    assert hindsight["reflect_enabled"] is False
    assert hindsight["reject_raw_turns"] is True
    assert hindsight["allowed_retain_sources"] == ["crystallized", "owner_approved"]
    assert hindsight["projection_coherence_window_seconds"] == 300
    assert hindsight["legacy_auto_retain_observed_disabled"] is False
    assert hindsight["effective_config_source"] == "substrate_providers.hindsight"


def test_hindsight_substrate_save_merges_known_values(tmp_path):
    save_config(
        {
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "adoption_source": "hermes_hindsight_config",
                    "api_url": "http://127.0.0.1:8888",
                    "bank_id": "memory-os",
                    "retain_enabled": True,
                    "recall_mode": "shadow",
                    "reflect_enabled": False,
                    "legacy_provider_was_hindsight": True,
                    "legacy_auto_retain_observed_disabled": True,
                }
            }
        },
        tmp_path,
    )

    hindsight = load_config(tmp_path)["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is True
    assert hindsight["recall_mode"] == "shadow"
    assert hindsight["reflect_enabled"] is False
    assert hindsight["api_key"] == ""
    assert hindsight["api_key_env_var"] == "HINDSIGHT_API_KEY"
    assert hindsight["legacy_auto_retain_observed_disabled"] is True


def test_legacy_hindsight_adapter_enabled_is_not_effective_source(tmp_path):
    save_config(
        {
            "hindsight_adapter_enabled": True,
            "substrate_providers": {
                "hindsight": {
                    "enabled": False,
                    "recall_mode": "off",
                }
            },
        },
        tmp_path,
    )

    config = load_config(tmp_path)

    assert config["hindsight_adapter_enabled"] is True
    assert config["substrate_providers"]["hindsight"]["enabled"] is False
    assert config["substrate_providers"]["hindsight"]["effective_config_source"] == "substrate_providers.hindsight"
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run:

```bash
python -m pytest tests/plugins/memory/test_memory_os_hindsight_substrate_config.py -q
```

Expected: FAIL because `substrate_providers` does not exist yet.

- [ ] **Step 3: Add normalized config defaults**

In `plugins/memory/memory_os/config.py`, extend `DEFAULT_CONFIG`:

```python
"substrate_providers": {
    "hindsight": {
        "enabled": False,
        "adoption_source": "none",
        "api_url": "",
        "bank_id": "",
        "api_key": "",
        "api_key_env_var": "HINDSIGHT_API_KEY",
        "retain_enabled": False,
        "recall_mode": "off",
        "reflect_enabled": False,
        "allowed_retain_sources": ["crystallized", "owner_approved"],
        "reject_raw_turns": True,
        "legacy_provider_was_hindsight": False,
        "legacy_auto_retain_observed_disabled": False,
        "projection_coherence_window_seconds": 300,
        "effective_config_source": "substrate_providers.hindsight",
        "pollution_scan_status": "unknown",
    },
},
```

Add this merge helper:

```python
def _merge_substrate_providers_config(value: Any) -> dict[str, Any]:
    default = json.loads(json.dumps(DEFAULT_CONFIG["substrate_providers"]))
    if not isinstance(value, dict):
        return default
    hindsight_value = value.get("hindsight")
    if isinstance(hindsight_value, dict):
        hindsight = dict(default["hindsight"])
        for key in hindsight:
            if key in hindsight_value:
                hindsight[key] = hindsight_value[key]
        if hindsight["adoption_source"] not in {"none", "hermes_hindsight_config", "wizard", "manual"}:
            hindsight["adoption_source"] = "none"
        if hindsight["recall_mode"] not in {"off", "shadow", "active"}:
            hindsight["recall_mode"] = "off"
        if not isinstance(hindsight.get("projection_coherence_window_seconds"), int):
            hindsight["projection_coherence_window_seconds"] = 300
        if hindsight["projection_coherence_window_seconds"] < 1:
            hindsight["projection_coherence_window_seconds"] = 300
        if "legacy_auto_retain_hardened" in hindsight_value and "legacy_auto_retain_observed_disabled" not in hindsight_value:
            hindsight["legacy_auto_retain_observed_disabled"] = bool(hindsight_value.get("legacy_auto_retain_hardened"))
        hindsight["effective_config_source"] = "substrate_providers.hindsight"
        if not isinstance(hindsight.get("allowed_retain_sources"), list):
            hindsight["allowed_retain_sources"] = ["crystallized", "owner_approved"]
        hindsight["allowed_retain_sources"] = [
            str(item)
            for item in hindsight["allowed_retain_sources"]
            if str(item) in {"crystallized", "owner_approved", "distilled"}
        ] or ["crystallized", "owner_approved"]
        default["hindsight"] = hindsight
    return default
```

Call it from `_merge_known`:

```python
merged["substrate_providers"] = _merge_substrate_providers_config(merged.get("substrate_providers"))
```

Add the config schema entry:

```python
{
    "key": "substrate_providers",
    "description": "Optional governed memory substrates such as Hindsight",
    "default": DEFAULT_CONFIG["substrate_providers"],
},
```

- [ ] **Step 4: Run config tests**

Run:

```bash
python -m pytest tests/plugins/memory/test_memory_os_hindsight_substrate_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/memory_os/config.py tests/plugins/memory/test_memory_os_hindsight_substrate_config.py
git commit -m "feat: add governed hindsight substrate config"
```

---

### Task 2: Implement Governed Hindsight Substrate Facade

**Files:**
- Modify: `plugins/memory/memory_os/substrates/__init__.py`
- Create: `plugins/memory/memory_os/substrates/hindsight.py`
- Modify: `plugins/memory/memory_os/adapters/hindsight.py`
- Test: `tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py`
- Test: `tests/plugins/memory/test_memory_os_hindsight_adapter.py`

- [ ] **Step 1: Write facade safety tests**

Create `tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py`:

```python
import pytest

from plugins.memory.memory_os.adapters.hindsight import HindsightExportRefused
from plugins.memory.memory_os.substrates.hindsight import (
    GovernedHindsightConfig,
    GovernedHindsightSubstrate,
)


class FakeClient:
    def __init__(self):
        self.retained = []
        self.recalled = []
        self.reflected = []

    def retain(self, payload):
        self.retained.append(payload)
        return {"ok": True, "id": "h1"}

    def recall(self, *, bank_id, query, budget, max_tokens):
        self.recalled.append(
            {"bank_id": bank_id, "query": query, "budget": budget, "max_tokens": max_tokens}
        )
        return {"items": [{"text": "grounded memory", "score": 0.7, "source": "hindsight"}]}

    def reflect(self, *, bank_id, query, budget):
        self.reflected.append({"bank_id": bank_id, "query": query, "budget": budget})
        return {"summary": "synthesized belief", "grounding": ["h1"]}


def test_disabled_substrate_is_unavailable():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=False),
        client=FakeClient(),
    )

    assert substrate.health().status == "disabled"
    assert substrate.recall("memory", consumer="test") == []


class FakeLiveGuard:
    def __init__(self, enabled):
        self.enabled = enabled

    def kill_switch_enabled(self, name):
        return self.enabled


def test_global_kill_switch_forces_hindsight_disabled():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", recall_mode="shadow"),
        client=FakeClient(),
        live_guard=FakeLiveGuard(True),
    )

    health = substrate.health()

    assert health.status == "disabled"
    assert health.reason == "kill_switch_enabled"
    assert health.kill_switch_forced_disabled is True
    assert substrate.recall("memory", consumer="test") == []


def test_retain_rejects_raw_source_class():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", retain_enabled=True),
        client=FakeClient(),
    )

    with pytest.raises(HindsightExportRefused, match="raw"):
        substrate.retain_payload(
            {
                "schema_version": "memory-os.hindsight_export.v0",
                "record_id": "evt_1",
                "text": "raw turn",
                "source_event_ids": ["evt_1"],
                "metadata": {"source_class": "raw_turn"},
            }
        )


def test_retain_accepts_approved_summary_payload():
    client = FakeClient()
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", retain_enabled=True),
        client=client,
    )

    result = substrate.retain_payload(
        {
            "schema_version": "memory-os.hindsight_export.v0",
            "record_id": "cmem_1",
            "text": "approved summary",
            "source_event_ids": ["evt_1"],
            "metadata": {"source_class": "crystallized"},
        }
    )

    assert result["ok"] is True
    assert client.retained[0]["metadata"]["source_class"] == "crystallized"


def test_recall_shadow_returns_grounding_facts_without_hot_path_llm():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", recall_mode="shadow"),
        client=FakeClient(),
    )

    facts = substrate.recall("continue yesterday", consumer="low_clue_recall")

    assert facts[0].provider == "hindsight"
    assert facts[0].body_summary == "grounded memory"
    assert facts[0].confidence == 0.7
    assert facts[0].authority_class == "derived_projection"
    assert facts[0].advisory_only is True
    assert facts[0].recall_llm_triggered is False
    assert facts[0].substrate_snapshot_id.startswith("hindsight:bank:")


def test_reflect_is_disabled_until_explicitly_enabled():
    client = FakeClient()
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", reflect_enabled=False),
        client=client,
    )

    assert substrate.reflect("what do I believe?", consumer="owner")["status"] == "disabled"
    assert client.reflected == []
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```bash
python -m pytest tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py -q
```

Expected: FAIL because `substrates/hindsight.py` does not exist.

- [ ] **Step 3: Add substrate package exports**

Modify `plugins/memory/memory_os/substrates/__init__.py`:

```python
"""Governed optional memory substrates for Memory-OS."""

from .base import GroundingFact, MemorySubstrateProvider, ProviderHealth, SubstrateSnapshot
from .hindsight import GovernedHindsightConfig, GovernedHindsightSubstrate
from .local_artifact import LocalArtifactProvider

__all__ = [
    "GovernedHindsightConfig",
    "GovernedHindsightSubstrate",
    "GroundingFact",
    "LocalArtifactProvider",
    "MemorySubstrateProvider",
    "ProviderHealth",
    "SubstrateSnapshot",
]
```

- [ ] **Step 4: Implement the governed facade**

Create `plugins/memory/memory_os/substrates/hindsight.py`:

```python
"""Governed Hindsight substrate for Memory-OS.

This module deliberately does not activate Hermes' direct Hindsight memory
provider. It treats Hindsight as a derived projection under Memory-OS control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..adapters.hindsight import HindsightExportRefused
from .base import GroundingFact, ProviderHealth, SubstrateSnapshot


class HindsightSubstrateClient(Protocol):
    def retain(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def recall(self, *, bank_id: str, query: str, budget: str, max_tokens: int) -> dict[str, Any]:
        ...

    def reflect(self, *, bank_id: str, query: str, budget: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class GovernedHindsightConfig:
    enabled: bool = False
    adoption_source: str = "none"
    api_url: str = ""
    bank_id: str = ""
    api_key: str = ""
    api_key_env_var: str = "HINDSIGHT_API_KEY"
    retain_enabled: bool = False
    recall_mode: str = "off"
    reflect_enabled: bool = False
    allowed_retain_sources: list[str] = field(default_factory=lambda: ["crystallized", "owner_approved"])
    reject_raw_turns: bool = True
    recall_budget: str = "mid"
    recall_max_tokens: int = 1200
    legacy_provider_was_hindsight: bool = False
    legacy_auto_retain_observed_disabled: bool = False
    pollution_scan_status: str = "unknown"

    @property
    def snapshot_id(self) -> str:
        source_ref = self.bank_id or "unconfigured"
        return SubstrateSnapshot("hindsight", source_ref, "current").snapshot_id

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "GovernedHindsightConfig":
        data = value if isinstance(value, dict) else {}
        allowed = data.get("allowed_retain_sources")
        if not isinstance(allowed, list):
            allowed = ["crystallized", "owner_approved"]
        return cls(
            enabled=bool(data.get("enabled")),
            adoption_source=str(data.get("adoption_source") or "none"),
            api_url=str(data.get("api_url") or ""),
            bank_id=str(data.get("bank_id") or ""),
            api_key=str(data.get("api_key") or ""),
            api_key_env_var=str(data.get("api_key_env_var") or "HINDSIGHT_API_KEY"),
            retain_enabled=bool(data.get("retain_enabled")),
            recall_mode=str(data.get("recall_mode") or "off"),
            reflect_enabled=bool(data.get("reflect_enabled")),
            allowed_retain_sources=[str(item) for item in allowed],
            reject_raw_turns=bool(data.get("reject_raw_turns", True)),
            recall_budget=str(data.get("recall_budget") or "mid"),
            recall_max_tokens=int(data.get("recall_max_tokens") or 1200),
            legacy_provider_was_hindsight=bool(data.get("legacy_provider_was_hindsight")),
            legacy_auto_retain_observed_disabled=bool(
                data.get("legacy_auto_retain_observed_disabled")
                or data.get("legacy_auto_retain_hardened")
            ),
            pollution_scan_status=str(data.get("pollution_scan_status") or "unknown"),
        )


class GovernedHindsightSubstrate:
    name = "hindsight"

    def __init__(
        self,
        config: GovernedHindsightConfig,
        *,
        client: HindsightSubstrateClient | None = None,
        live_guard: Any | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.live_guard = live_guard

    def _kill_switch_enabled(self) -> bool:
        if self.live_guard is None:
            return False
        checker = getattr(self.live_guard, "kill_switch_enabled", None)
        if checker is None:
            return False
        return bool(checker(self.name) or checker("all_substrates"))

    def health(self) -> ProviderHealth:
        if self._kill_switch_enabled():
            return ProviderHealth(
                provider=self.name,
                status="disabled",
                capabilities=[],
                reason="kill_switch_enabled",
                kill_switch_forced_disabled=True,
                substrate_snapshot_id=self.config.snapshot_id,
            )
        if not self.config.enabled:
            return ProviderHealth(provider=self.name, status="disabled", capabilities=[])
        if not self.config.bank_id:
            return ProviderHealth(
                provider=self.name,
                status="misconfigured",
                reason="bank_id_missing",
                capabilities=[],
                substrate_snapshot_id=self.config.snapshot_id,
            )
        if self.client is None:
            return ProviderHealth(
                provider=self.name,
                status="unavailable",
                reason="client_missing",
                capabilities=[],
                substrate_snapshot_id=self.config.snapshot_id,
            )
        capabilities = ["retain"]
        if self.config.recall_mode in {"shadow", "active"}:
            capabilities.append("recall")
        if self.config.reflect_enabled:
            capabilities.append("reflect")
        return ProviderHealth(
            provider=self.name,
            status="ok",
            capabilities=capabilities,
            substrate_snapshot_id=self.config.snapshot_id,
        )

    def retain_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._kill_switch_enabled():
            return {"ok": False, "status": "disabled", "reason": "kill_switch_enabled"}
        if not self.config.enabled or not self.config.retain_enabled:
            return {"ok": False, "status": "disabled"}
        source_class = str((payload.get("metadata") or {}).get("source_class") or "")
        if source_class not in set(self.config.allowed_retain_sources):
            raise HindsightExportRefused(f"Hindsight retain refused for source_class={source_class or 'raw'}")
        if self.config.reject_raw_turns and source_class in {"raw", "raw_turn", "conversation_turn", "event", "working"}:
            raise HindsightExportRefused("Hindsight retain refused for raw source")
        if self.client is None:
            return {"ok": False, "status": "unavailable", "reason": "client_missing"}
        payload.setdefault("metadata", {})["substrate_snapshot_id"] = self.config.snapshot_id
        return self.client.retain(payload)

    def recall(self, query: str, *, consumer: str) -> list[GroundingFact]:
        if self._kill_switch_enabled():
            return []
        if not self.config.enabled or self.config.recall_mode == "off" or self.client is None:
            return []
        response = self.client.recall(
            bank_id=self.config.bank_id,
            query=query,
            budget=self.config.recall_budget,
            max_tokens=self.config.recall_max_tokens,
        )
        items = response.get("items", []) if isinstance(response, dict) else []
        facts: list[GroundingFact] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("summary") or "").strip()
            if not text:
                continue
            facts.append(
                GroundingFact(
                    provider=self.name,
                    capability="recall",
                    body_summary=text,
                    confidence=float(item.get("score") or item.get("confidence") or 0.5),
                    provenance="hindsight_recall",
                    source_event_refs=[str(item.get("source") or "")],
                    substrate_snapshot_id=self.config.snapshot_id,
                    consumer=consumer,
                    advisory_only=True,
                    authority_class="derived_projection",
                    recall_llm_triggered=False,
                )
            )
        return facts

    def reflect(self, query: str, *, consumer: str) -> dict[str, Any]:
        if self._kill_switch_enabled():
            return {"provider": self.name, "capability": "reflect", "status": "disabled", "reason": "kill_switch_enabled"}
        if not self.config.enabled or not self.config.reflect_enabled:
            return {"provider": self.name, "capability": "reflect", "status": "disabled"}
        if self.client is None:
            return {"provider": self.name, "capability": "reflect", "status": "unavailable"}
        response = self.client.reflect(bank_id=self.config.bank_id, query=query, budget=self.config.recall_budget)
        return {
            "provider": self.name,
            "capability": "reflect",
            "status": "ok",
            "consumer": consumer,
            "advisory_only": True,
            "provenance": "reflect_synthesized",
            "substrate_snapshot_id": self.config.snapshot_id,
            "response": response,
        }
```

- [ ] **Step 5: Update existing export adapter to tag governed source class**

In `plugins/memory/memory_os/adapters/hindsight.py`, update `build_export_payload()` metadata:

```python
"metadata": {
    "source_class": "crystallized",
    "candidate_id": str(record.frontmatter.get("candidate_id", "")),
    "approved_by": str(record.frontmatter.get("approved_by", "")),
    "approved_at": str(record.frontmatter.get("approved_at", "")),
    "sensitivity": str(record.frontmatter.get("sensitivity", "")),
},
```

Update the expected payload in `tests/plugins/memory/test_memory_os_hindsight_adapter.py`.

- [ ] **Step 6: Run Hindsight tests**

Run:

```bash
python -m pytest tests/plugins/memory/test_memory_os_hindsight_adapter.py tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add plugins/memory/memory_os/substrates plugins/memory/memory_os/adapters/hindsight.py tests/plugins/memory/test_memory_os_hindsight_adapter.py tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py
git commit -m "feat: add governed hindsight substrate facade"
```

---

### Task 3: Add Hindsight CLI Status, Doctor, and Dry-Run Adoption

**Files:**
- Modify: `plugins/memory/memory_os/cli.py`
- Test: `tests/system_modularization/test_memory_os_agent_os_shell.py`
- Test: `tests/plugins/memory/test_memory_os_hindsight_substrate_config.py`

- [ ] **Step 1: Write CLI tests for default off and dry-run adopt**

Append tests to `tests/system_modularization/test_memory_os_agent_os_shell.py`:

```python
def test_hindsight_status_reports_optional_off(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_status_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    report = hindsight_status_report(store)

    assert report["schema_version"] == "memory-os.hindsight_substrate_status.v0"
    assert report["enabled"] is False
    assert report["status"] == "optional_not_configured"
    assert report["direct_hermes_provider_active"] is False


def test_hindsight_adopt_dry_run_reads_legacy_config_without_secrets(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_adopt_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    legacy_dir = tmp_path / "hindsight"
    legacy_dir.mkdir()
    (legacy_dir / "config.json").write_text(
        '{"api_url":"http://127.0.0.1:8888","bank_id":"hermes","apiKey":"SECRET","auto_retain":false}',
        encoding="utf-8",
    )

    report = hindsight_adopt_report(store, apply=False)

    assert report["schema_version"] == "memory-os.hindsight_adopt.v0"
    assert report["dry_run"] is True
    assert report["detected"]["bank_id"] == "hermes"
    assert "SECRET" not in str(report)
    assert report["planned_config"]["recall_mode"] == "shadow"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```bash
python -m pytest tests/system_modularization/test_memory_os_agent_os_shell.py::test_hindsight_status_reports_optional_off tests/system_modularization/test_memory_os_agent_os_shell.py::test_hindsight_adopt_dry_run_reads_legacy_config_without_secrets -q
```

Expected: FAIL because reports do not exist.

- [ ] **Step 3: Add report functions**

In `plugins/memory/memory_os/cli.py`, add:

```python
def hindsight_status_report(store: MemoryOSStore) -> dict[str, Any]:
    config = load_config(store.roots.hermes_home)
    substrate = (config.get("substrate_providers") or {}).get("hindsight") or {}
    enabled = bool(substrate.get("enabled"))
    substrate_monitor = _hindsight_substrate_monitor(store)
    return {
        "schema_version": "memory-os.hindsight_substrate_status.v0",
        "enabled": enabled,
        "status": "configured" if enabled else "optional_not_configured",
        "adoption_source": str(substrate.get("adoption_source") or "none"),
        "bank_id": str(substrate.get("bank_id") or ""),
        "api_url_configured": bool(substrate.get("api_url")),
        "api_key_configured": bool(substrate.get("api_key") or os.environ.get(str(substrate.get("api_key_env_var") or ""))),
        "retain_enabled": bool(substrate.get("retain_enabled")),
        "recall_mode": str(substrate.get("recall_mode") or "off"),
        "reflect_enabled": bool(substrate.get("reflect_enabled")),
        "direct_hermes_provider_active": _direct_hermes_provider_active(store.roots.hermes_home),
        "legacy_provider_was_hindsight": bool(substrate.get("legacy_provider_was_hindsight")),
        "legacy_auto_retain_observed_disabled": bool(substrate.get("legacy_auto_retain_observed_disabled")),
        "substrate_monitor": substrate_monitor,
    }


def _hindsight_substrate_monitor(store: MemoryOSStore) -> dict[str, Any]:
    from .substrates.ledger import SubstrateOperationLedger, derive_substrate_monitor_fields
    from .substrates.projection import ProjectionLedger, derive_projection_coherence

    operation_ledger = SubstrateOperationLedger(store.roots.memory_os_root / "system" / "substrate_operations.jsonl")
    projection_ledger = ProjectionLedger(store.roots.memory_os_root / "system" / "projection_ledger.jsonl")
    operation_fields = derive_substrate_monitor_fields(operation_ledger.read_all(), provider="hindsight")
    projection_fields = derive_projection_coherence(projection_ledger.read_all(), provider="hindsight")
    shadow = _latest_substrate_shadow_recall(store)
    return {
        **operation_fields,
        **projection_fields,
        "local_first_authority_preserved": shadow.get("local_first_authority_preserved") if shadow else None,
        "external_authoritative_count": shadow.get("external_authoritative_count") if shadow else 0,
    }


def _latest_substrate_shadow_recall(store: MemoryOSStore) -> dict[str, Any]:
    path = store.roots.memory_os_root / "system" / "substrate_recall_shadow.jsonl"
    if not path.exists():
        return {}
    latest: dict[str, Any] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                latest = value
    return latest


def _direct_hermes_provider_active(hermes_home: Path) -> bool:
    config_path = hermes_home / "config.yaml"
    if not config_path.exists():
        return False
    try:
        import yaml

        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    return str(memory.get("provider") or "") == "hindsight"


def hindsight_adopt_report(store: MemoryOSStore, *, apply: bool = False) -> dict[str, Any]:
    legacy_path = store.roots.hermes_home / "hindsight" / "config.json"
    detected: dict[str, Any] = {"exists": legacy_path.exists()}
    planned = {
        "enabled": False,
        "adoption_source": "none",
        "api_url": "",
        "bank_id": "",
        "retain_enabled": False,
        "recall_mode": "off",
        "reflect_enabled": False,
        "legacy_provider_was_hindsight": False,
        "legacy_auto_retain_observed_disabled": False,
    }
    if legacy_path.exists():
        raw = json.loads(legacy_path.read_text(encoding="utf-8"))
        detected = {
            "exists": True,
            "api_url_configured": bool(raw.get("api_url")),
            "bank_id": str(raw.get("bank_id") or ""),
            "auto_retain": bool(raw.get("auto_retain")),
            "api_key_configured": bool(raw.get("apiKey")),
        }
        planned.update(
            {
                "enabled": True,
                "adoption_source": "hermes_hindsight_config",
                "api_url": str(raw.get("api_url") or ""),
                "bank_id": str(raw.get("bank_id") or ""),
                "retain_enabled": False,
                "recall_mode": "shadow",
                "reflect_enabled": False,
                "legacy_provider_was_hindsight": False,
                "legacy_auto_retain_observed_disabled": raw.get("auto_retain") is False,
            }
        )
    if apply:
        from .config import save_config

        save_config({"substrate_providers": {"hindsight": planned}}, store.roots.hermes_home)
    return {
        "schema_version": "memory-os.hindsight_adopt.v0",
        "dry_run": not apply,
        "detected": detected,
        "planned_config": planned,
        "secret_policy": "secrets redacted; apiKey is not printed",
    }
```

- [ ] **Step 4: Wire CLI subcommands**

In `memory_os_command`, add subparser support:

```python
hindsight = subparsers.add_parser("hindsight")
hindsight_sub = hindsight.add_subparsers(dest="hindsight_command")
hindsight_sub.add_parser("status")
adopt = hindsight_sub.add_parser("adopt")
adopt.add_argument("--apply", action="store_true")
```

In command dispatch:

```python
if args.command == "hindsight":
    if args.hindsight_command == "status":
        print(json.dumps(hindsight_status_report(store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.hindsight_command == "adopt":
        print(json.dumps(hindsight_adopt_report(store, apply=bool(args.apply)), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
```

- [ ] **Step 5: Change doctor semantics**

In `meta_audit()`, replace the current unconditional warning:

```python
if not bool(load_config(store.roots.hermes_home).get("hindsight_adapter_enabled")):
    findings.append(_finding("hindsight_adapter_disabled", "warning", "Hindsight adapter is disabled."))
```

with:

```python
hindsight_status = hindsight_status_report(store)
if hindsight_status["enabled"] and not hindsight_status["bank_id"]:
    findings.append(_finding("hindsight_substrate_misconfigured", "error", "Hindsight substrate is enabled but bank_id is missing."))
```

- [ ] **Step 6: Run CLI tests**

Run:

```bash
python -m pytest tests/system_modularization/test_memory_os_agent_os_shell.py tests/plugins/memory/test_memory_os_hindsight_substrate_config.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add plugins/memory/memory_os/cli.py tests/system_modularization/test_memory_os_agent_os_shell.py tests/plugins/memory/test_memory_os_hindsight_substrate_config.py
git commit -m "feat: expose governed hindsight operator commands"
```

---

### Task 4: Implement Installer Adoption Modes

**Files:**
- Modify: `scripts/install_memory_os.sh`
- Modify: `scripts/install_memory_os_plugin.py`
- Test: `tests/scripts/test_memory_os_plugin_install.py`

- [ ] **Step 1: Write installer tests**

Append to `tests/scripts/test_memory_os_plugin_install.py`:

```python
def test_installer_hindsight_off_leaves_substrate_disabled(tmp_path):
    from scripts.install_memory_os_plugin import install_plugin
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / "home"
    report = install_plugin(hermes_home=home, hindsight_mode="off")

    assert report["hindsight_mode"] == "off"
    hindsight = load_config(home)["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is False


def test_installer_hindsight_auto_adopts_existing_legacy_config_without_printing_secret(tmp_path):
    from scripts.install_memory_os_plugin import install_plugin
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / "home"
    legacy = home / "hindsight"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(
        '{"api_url":"http://127.0.0.1:8888","bank_id":"hermes02","apiKey":"SECRET","auto_retain":false}',
        encoding="utf-8",
    )

    report = install_plugin(hermes_home=home, hindsight_mode="auto")

    serialized = json.dumps(report, ensure_ascii=False)
    assert "SECRET" not in serialized
    assert report["hindsight_adoption"]["status"] == "adopted_shadow"
    hindsight = load_config(home)["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is True
    assert hindsight["bank_id"] == "hermes02"
    assert hindsight["recall_mode"] == "shadow"
    assert hindsight["retain_enabled"] is False
    assert hindsight["reflect_enabled"] is False


def test_installer_hindsight_auto_without_config_stays_disabled(tmp_path):
    from scripts.install_memory_os_plugin import install_plugin
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / "home"
    report = install_plugin(hermes_home=home, hindsight_mode="auto")

    assert report["hindsight_adoption"]["status"] == "not_configured"
    assert load_config(home)["substrate_providers"]["hindsight"]["enabled"] is False
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```bash
python -m pytest tests/scripts/test_memory_os_plugin_install.py::test_installer_hindsight_off_leaves_substrate_disabled tests/scripts/test_memory_os_plugin_install.py::test_installer_hindsight_auto_adopts_existing_legacy_config_without_printing_secret tests/scripts/test_memory_os_plugin_install.py::test_installer_hindsight_auto_without_config_stays_disabled -q
```

Expected: FAIL because `hindsight_mode` is not accepted.

- [ ] **Step 3: Extend Python installer signature and adoption helper**

In `scripts/install_memory_os_plugin.py`, add argument to `install_plugin()`:

```python
hindsight_mode: str = "auto",
```

Add helper:

```python
def _configure_hindsight_substrate(hermes_home: Path, *, mode: str, dry_run: bool) -> dict[str, Any]:
    if mode not in {"auto", "off", "adopt", "wizard"}:
        raise SystemExit("--hindsight must be one of: auto, off, adopt, wizard")
    if mode in {"off", "wizard"}:
        return {"status": "disabled" if mode == "off" else "wizard_deferred", "mode": mode}
    legacy_path = hermes_home / "hindsight" / "config.json"
    if not legacy_path.exists():
        if mode == "adopt":
            raise SystemExit("Cannot adopt Hindsight: existing hindsight/config.json not found")
        return {"status": "not_configured", "mode": mode}
    raw = json.loads(legacy_path.read_text(encoding="utf-8"))
    planned = {
        "enabled": True,
        "adoption_source": "hermes_hindsight_config",
        "api_url": str(raw.get("api_url") or ""),
        "bank_id": str(raw.get("bank_id") or ""),
        "api_key": "",
        "api_key_env_var": "HINDSIGHT_API_KEY",
        "retain_enabled": False,
        "recall_mode": "shadow",
        "reflect_enabled": False,
        "legacy_provider_was_hindsight": False,
        "legacy_auto_retain_observed_disabled": raw.get("auto_retain") is False,
    }
    if not dry_run:
        from plugins.memory.memory_os.config import save_config

        save_config({"substrate_providers": {"hindsight": planned}}, hermes_home)
    return {
        "status": "adopted_shadow",
        "mode": mode,
        "detected": {
            "api_url_configured": bool(raw.get("api_url")),
            "bank_id": str(raw.get("bank_id") or ""),
            "auto_retain": bool(raw.get("auto_retain")),
            "api_key_configured": bool(raw.get("apiKey")),
        },
        "planned_config": {key: value for key, value in planned.items() if key != "api_key"},
    }
```

Call it before returning the report:

```python
hindsight_adoption = _configure_hindsight_substrate(hermes_home, mode=hindsight_mode, dry_run=dry_run)
```

Add to the report:

```python
"hindsight_mode": hindsight_mode,
"hindsight_adoption": hindsight_adoption,
```

- [ ] **Step 4: Add CLI parser flag**

In `scripts/install_memory_os_plugin.py` parser:

```python
parser.add_argument("--hindsight", choices=["auto", "off", "adopt", "wizard"], default="auto")
```

Pass `hindsight_mode=args.hindsight` into `install_plugin()`.

- [ ] **Step 5: Add shell installer flag**

In `scripts/install_memory_os.sh`, add:

```bash
HINDSIGHT_MODE="auto"
```

Usage text:

```text
  --hindsight MODE             auto|off|adopt|wizard. Default: auto.
                                auto adopts an existing Hindsight config into
                                Memory-OS shadow mode; no config stays off.
```

Argument parsing:

```bash
--hindsight)
  HINDSIGHT_MODE="${2:?missing --hindsight value}"
  shift 2
  ;;
```

Installer args:

```bash
args+=("--hindsight" "${HINDSIGHT_MODE}")
```

- [ ] **Step 6: Run installer tests**

Run:

```bash
python -m pytest tests/scripts/test_memory_os_plugin_install.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/install_memory_os.sh scripts/install_memory_os_plugin.py tests/scripts/test_memory_os_plugin_install.py
git commit -m "feat: adopt existing hindsight configs into memory-os"
```

---

### Task 4A: Add Automated Deployment Orchestrator and Compatibility Profiles

**Files:**
- Create: `scripts/deploy_memory_os.py`
- Create: `tests/scripts/test_memory_os_deploy.py`
- Modify: `docs/internal-memory-os/01-contracts/30-hermes-upgrade-compatibility-gate.md`
- Modify: `docs/quickstart.md`

- [ ] **Step 1: Write deployment plan and classification tests**

Create `tests/scripts/test_memory_os_deploy.py`:

```python
import json

from scripts.deploy_memory_os import (
    classify_deploy_report,
    deploy_memory_os,
    render_deploy_plan,
)


def test_plan_phase_includes_hindsight_and_no_restart_by_default(tmp_path):
    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="production-safe",
        hindsight_mode="auto",
        phase="plan",
        profile="fresh",
    )

    rendered = render_deploy_plan(report)

    assert report["schema_version"] == "memory-os.deploy.v0"
    assert report["phase"] == "plan"
    assert report["profile"] == "fresh"
    assert report["restart_requested"] is False
    assert "--hindsight auto" in rendered
    assert "--production-safe" in rendered
    assert "SECRET" not in json.dumps(report, ensure_ascii=False)


def test_upgrade_profile_blocks_apply_when_preflight_compat_fails(tmp_path):
    def fake_runner(argv, *, host=None, timeout=30):
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {"pass": [], "warn": [], "fail": [{"code": "memory_provider_not_memory_os"}]},
                    }
                ),
                "stderr": "",
            }
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="apply",
        profile="upgrade",
        run_command=fake_runner,
    )

    classification = classify_deploy_report(report)

    assert report["preflight"]["status"] == "fail"
    assert report["apply"]["status"] == "blocked"
    assert {"code": "preflight_compat_failed"} in classification["fail"]


def test_fresh_profile_allows_preinstall_provider_mismatch_but_requires_postcheck(tmp_path):
    calls = []

    def fake_runner(argv, *, host=None, timeout=30):
        calls.append(tuple(argv))
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command and len(calls) == 1:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {"pass": [], "warn": [], "fail": [{"code": "memory_provider_not_memory_os"}]},
                    }
                ),
                "stderr": "",
            }
        if "install_memory_os.sh" in command:
            is_dry_run = "--dry-run" in command
            return {
                "exit_code": 0,
                "stdout": json.dumps({"schema_version": "memory-os.install.v0", "dry_run": is_dry_run}),
                "stderr": "",
            }
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {"pass": [{"code": "memory_provider_active"}], "warn": [], "fail": []},
                    }
                ),
                "stderr": "",
            }
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="production-safe",
        hindsight_mode="off",
        phase="apply",
        profile="fresh",
        run_command=fake_runner,
    )

    classification = classify_deploy_report(report)

    assert report["preflight"]["status"] == "warn_expected_for_fresh"
    assert report["apply"]["status"] == "applied"
    assert report["postcheck"]["status"] == "pass"
    assert classification["fail"] == []


def test_remote_plan_uses_ssh_without_printing_secret(tmp_path):
    report = deploy_memory_os(
        repo_root=tmp_path,
        remote_repo_root="/opt/Hermes-Memory-OS",
        host="hermes-media",
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="adopt",
        phase="plan",
        profile="upgrade",
    )

    assert report["host"] == "hermes-media"
    assert report["commands"]["install_apply"][0] == "ssh"
    assert "--hindsight adopt" in render_deploy_plan(report)
    assert "/opt/Hermes-Memory-OS/scripts/install_memory_os.sh" in render_deploy_plan(report)
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```bash
python -m pytest tests/scripts/test_memory_os_deploy.py -q
```

Expected: FAIL because `scripts/deploy_memory_os.py` does not exist.

- [ ] **Step 3: Implement deployment orchestrator**

Create `scripts/deploy_memory_os.py`:

```python
#!/usr/bin/env python3
"""Automated Memory-OS deployment orchestrator.

This script coordinates existing safe primitives. It does not replace
install_memory_os.sh and does not restart Hermes unless explicitly requested.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable


RunCommand = Callable[[list[str]], dict[str, Any]]


def deploy_memory_os(
    *,
    repo_root: Path,
    remote_repo_root: str = "",
    hermes_home: str,
    mode: str,
    hindsight_mode: str,
    phase: str,
    profile: str,
    host: str = "",
    timeout: int = 60,
    allow_restart: bool = False,
    restart_command: str = "",
    run_command: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if phase not in {"plan", "preflight", "dry-run", "apply", "postcheck"}:
        raise SystemExit("--phase must be one of: plan, preflight, dry-run, apply, postcheck")
    if profile not in {"fresh", "upgrade"}:
        raise SystemExit("--profile must be fresh or upgrade")
    if hindsight_mode not in {"auto", "off", "adopt", "wizard"}:
        raise SystemExit("--hindsight must be auto, off, adopt, or wizard")
    runner = run_command or _run_command
    repo_root = repo_root.resolve()
    command_repo_root = remote_repo_root or str(repo_root)
    commands = _build_commands(
        repo_root=command_repo_root,
        hermes_home=hermes_home,
        mode=mode,
        hindsight_mode=hindsight_mode,
        host=host,
        allow_restart=allow_restart,
        restart_command=restart_command,
    )
    report: dict[str, Any] = {
        "schema_version": "memory-os.deploy.v0",
        "phase": phase,
        "profile": profile,
        "host": host or "local",
        "hermes_home": hermes_home,
        "mode": mode,
        "hindsight_mode": hindsight_mode,
        "restart_requested": bool(allow_restart and restart_command),
        "commands": commands,
        "preflight": {"status": "not_run"},
        "dry_run": {"status": "not_run"},
        "apply": {"status": "not_run"},
        "postcheck": {"status": "not_run"},
        "rollback_hint": "rerun installer with previous config backup or disable substrate_providers.hindsight.enabled",
    }
    if phase == "plan":
        return report

    preflight = _run_json(commands["compat"], runner=runner, host=host, timeout=timeout)
    report["preflight"] = _classify_preflight(preflight, profile=profile)
    if phase == "preflight":
        return report

    if phase in {"dry-run", "apply"}:
        dry_run = _run_json(commands["install_dry_run"], runner=runner, host=host, timeout=timeout)
        report["dry_run"] = _classify_install(dry_run, expected_dry_run=True)
        if phase == "dry-run":
            return report

    if phase == "apply":
        if profile == "upgrade" and report["preflight"]["status"] != "pass":
            report["apply"] = {"status": "blocked", "reason": "preflight_compat_failed"}
            return report
        if report["dry_run"]["status"] != "pass":
            report["apply"] = {"status": "blocked", "reason": "install_dry_run_failed"}
            return report
        apply_result = _run_json(commands["install_apply"], runner=runner, host=host, timeout=timeout)
        report["apply"] = _classify_install(apply_result, expected_dry_run=False)
        if report["restart_requested"]:
            restart_result = runner(commands["restart"], host=host or None, timeout=timeout)
            report["restart"] = _redact_process_result(restart_result)
        postcheck = _run_json(commands["compat"], runner=runner, host=host, timeout=timeout)
        report["postcheck"] = _classify_postcheck(postcheck)
        return report

    if phase == "postcheck":
        postcheck = _run_json(commands["compat"], runner=runner, host=host, timeout=timeout)
        report["postcheck"] = _classify_postcheck(postcheck)
    return report


def _build_commands(
    *,
    repo_root: str,
    hermes_home: str,
    mode: str,
    hindsight_mode: str,
    host: str,
    allow_restart: bool,
    restart_command: str,
) -> dict[str, list[str]]:
    install_base = [
        "bash",
        f"{repo_root.rstrip('/')}/scripts/install_memory_os.sh",
        "--yes",
        f"--{mode}",
        "--hermes-home",
        hermes_home,
        "--hindsight",
        hindsight_mode,
        "--skip-verify",
    ]
    compat = [
        "python",
        f"{repo_root.rstrip('/')}/scripts/memory_os_upgrade_compat_check.py",
        "--hermes-home",
        hermes_home,
        "--output",
        "json",
    ]
    commands = {
        "compat": compat,
        "install_dry_run": install_base + ["--dry-run"],
        "install_apply": install_base,
    }
    if allow_restart and restart_command:
        commands["restart"] = shlex.split(restart_command)
    if host:
        return {name: _ssh_wrap(host, argv) for name, argv in commands.items()}
    return commands


def _ssh_wrap(host: str, argv: list[str]) -> list[str]:
    return ["ssh", host, shlex.join(argv)]


def _run_json(command: list[str], *, runner: Callable[..., dict[str, Any]], host: str, timeout: int) -> dict[str, Any]:
    result = runner(command, host=host or None, timeout=timeout)
    redacted = _redact_process_result(result)
    try:
        redacted["json"] = json.loads(str(result.get("stdout") or ""))
    except json.JSONDecodeError:
        redacted["json"] = None
    return redacted


def _run_command(argv: list[str], *, host: str | None = None, timeout: int = 60) -> dict[str, Any]:
    completed = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    return {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def _redact_process_result(result: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(result, ensure_ascii=False)
    for marker in ("apiKey", "api_key", "token", "SECRET"):
        text = text.replace(marker, "[redacted-key]")
    return json.loads(text)


def _classify_preflight(result: dict[str, Any], *, profile: str) -> dict[str, Any]:
    fail = _classification_failures(result)
    if not fail:
        return {"status": "pass", "compat": result.get("json")}
    if profile == "fresh" and all(item.get("code") == "memory_provider_not_memory_os" for item in fail):
        return {"status": "warn_expected_for_fresh", "compat": result.get("json")}
    return {"status": "fail", "compat": result.get("json"), "fail": fail}


def _classify_install(result: dict[str, Any], *, expected_dry_run: bool) -> dict[str, Any]:
    if int(result.get("exit_code", 1)) != 0:
        return {"status": "fail", "exit_code": result.get("exit_code")}
    data = result.get("json")
    if not isinstance(data, dict) or data.get("schema_version") != "memory-os.install.v0":
        return {"status": "fail", "reason": "install_json_invalid"}
    if bool(data.get("dry_run")) != expected_dry_run:
        return {"status": "fail", "reason": "dry_run_mismatch"}
    return {"status": "pass" if expected_dry_run else "applied", "install": data}


def _classify_postcheck(result: dict[str, Any]) -> dict[str, Any]:
    fail = _classification_failures(result)
    if fail:
        return {"status": "fail", "compat": result.get("json"), "fail": fail}
    return {"status": "pass", "compat": result.get("json")}


def _classification_failures(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("json")
    if not isinstance(data, dict):
        return [{"code": "compat_json_invalid"}]
    classification = data.get("classification") if isinstance(data.get("classification"), dict) else {}
    fail = classification.get("fail") if isinstance(classification.get("fail"), list) else []
    return [item for item in fail if isinstance(item, dict)]


def classify_deploy_report(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fail: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []
    passed: list[dict[str, Any]] = []
    for key in ("preflight", "dry_run", "apply", "postcheck"):
        status = (report.get(key) or {}).get("status")
        if status in {"pass", "applied"}:
            passed.append({"code": f"{key}_{status}"})
        elif status == "warn_expected_for_fresh":
            warn.append({"code": "fresh_preflight_provider_mismatch_expected"})
        elif status == "blocked":
            fail.append({"code": (report.get(key) or {}).get("reason") or f"{key}_blocked"})
        elif status == "fail":
            fail.append({"code": f"{key}_failed"})
    return {"pass": passed, "warn": warn, "fail": fail}


def render_deploy_plan(report: dict[str, Any]) -> str:
    lines = [
        f"Memory-OS deploy plan: phase={report['phase']} profile={report['profile']} host={report['host']}",
        f"restart_requested={str(report['restart_requested']).lower()}",
    ]
    for name, argv in report["commands"].items():
        lines.append(f"{name}: {shlex.join(argv)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automate Memory-OS deployment with compatibility gates.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--remote-repo-root", default="", help="Path to this checkout on the SSH target. Required when --host cannot use --repo-root.")
    parser.add_argument("--host", default="")
    parser.add_argument("--hermes-home", required=True)
    parser.add_argument("--mode", choices=["production-safe", "test-host", "operational"], default="production-safe")
    parser.add_argument("--hindsight", choices=["auto", "off", "adopt", "wizard"], default="auto")
    parser.add_argument("--phase", choices=["plan", "preflight", "dry-run", "apply", "postcheck"], default="plan")
    parser.add_argument("--profile", choices=["fresh", "upgrade"], default="upgrade")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--allow-restart", action="store_true")
    parser.add_argument("--restart-command", default="")
    parser.add_argument("--output", choices=["summary", "json"], default="summary")
    args = parser.parse_args(argv)
    report = deploy_memory_os(
        repo_root=args.repo_root,
        remote_repo_root=args.remote_repo_root,
        host=args.host,
        hermes_home=args.hermes_home,
        mode=args.mode,
        hindsight_mode=args.hindsight,
        phase=args.phase,
        profile=args.profile,
        timeout=args.timeout,
        allow_restart=args.allow_restart,
        restart_command=args.restart_command,
    )
    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_deploy_plan(report))
    return 1 if classify_deploy_report(report)["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run deployment tests**

Run:

```bash
python -m pytest tests/scripts/test_memory_os_deploy.py -q
```

Expected: PASS.

- [ ] **Step 5: Document deployment profiles**

In `docs/internal-memory-os/01-contracts/30-hermes-upgrade-compatibility-gate.md`, add:

```markdown
## Automated Deployment Wrapper

Use `scripts/deploy_memory_os.py` to orchestrate installation and compatibility
checks. The low-level installer remains `scripts/install_memory_os.sh`; the
deploy wrapper only sequences gates and classifies stop conditions.

Profiles:

| Profile | Preflight meaning | Postcheck requirement |
| --- | --- | --- |
| `fresh` | `memory_provider_not_memory_os` is expected before install; other FAIL remains blocking. | Compatibility must PASS after install. |
| `upgrade` | Compatibility must PASS before install/apply. | Compatibility must PASS after install. |

Phases:

| Phase | Behavior |
| --- | --- |
| `plan` | Render commands only. No target contact and no writes. |
| `preflight` | Run read-only compatibility check only. |
| `dry-run` | Run preflight plus installer dry-run. |
| `apply` | Run preflight, installer dry-run, installer apply, then postcheck. |
| `postcheck` | Run read-only compatibility check after a separately performed install. |

The deploy wrapper does not restart Hermes by default. Restart requires
`--allow-restart --restart-command '...'` and should only be used after owner
approval for the exact target service.
```

In `docs/quickstart.md`, add:

```bash
# Fresh host, local execution on the target:
python scripts/deploy_memory_os.py \
  --hermes-home /root/.hermes \
  --profile fresh \
  --phase apply \
  --mode production-safe \
  --hindsight off

# Existing Hermes + Hindsight host, remote orchestration:
python scripts/deploy_memory_os.py \
  --host hermes-media \
  --remote-repo-root /opt/Hermes-Memory-OS \
  --hermes-home /root/.hermes \
  --profile upgrade \
  --phase dry-run \
  --mode operational \
  --hindsight auto
```

- [ ] **Step 6: Add deployment test to the verification set**

Run:

```bash
python -m pytest tests/scripts/test_memory_os_deploy.py tests/scripts/test_memory_os_plugin_install.py tests/scripts/test_memory_os_upgrade_compat_check.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_memory_os.py tests/scripts/test_memory_os_deploy.py docs/internal-memory-os/01-contracts/30-hermes-upgrade-compatibility-gate.md docs/quickstart.md
git commit -m "feat: add memory-os deployment orchestration gate"
```

---

### Task 5: Add Substrate Router and Shadow Recall Evidence

**Files:**
- Create: `plugins/memory/memory_os/substrates/router.py`
- Modify: `plugins/memory/memory_os/prefetch.py`
- Modify: `plugins/memory/memory_os/memory_sources.py`
- Test: `tests/plugins/memory/test_memory_os_substrate_router.py`
- Test: `tests/plugins/memory/test_memory_os_prefetch.py`

- [ ] **Step 1: Write router tests**

Create `tests/plugins/memory/test_memory_os_substrate_router.py`:

```python
from plugins.memory.memory_os.substrates.base import GroundingFact, ProviderHealth
from plugins.memory.memory_os.substrates.router import SubstrateRouter


class FakeProvider:
    def __init__(self, name, facts=None, status="ok"):
        self.name = name
        self.facts = facts or []
        self.status = status

    def health(self):
        return ProviderHealth(provider=self.name, status=self.status, capabilities=["recall"])

    def recall(self, query, *, consumer):
        return list(self.facts)


def test_router_returns_fallback_when_provider_disabled():
    router = SubstrateRouter(providers=[FakeProvider("hindsight", status="disabled")])

    result = router.recall("memory", consumer="grounded_expression")

    assert result["facts"] == []
    assert result["fallback_triggered"] is True
    assert result["selected_provider"] == "deterministic_fallback"


def test_router_records_shadow_hindsight_without_making_it_authoritative():
    router = SubstrateRouter(
        providers=[
            FakeProvider(
                "hindsight",
                facts=[
                    GroundingFact(
                        provider="hindsight",
                        capability="recall",
                        body_summary="shadow",
                        confidence=0.6,
                        provenance="hindsight_recall",
                        source_event_refs=["h1"],
                        substrate_snapshot_id="hindsight:bank:v1",
                        advisory_only=True,
                        authority_class="derived_projection",
                    )
                ]
            )
        ],
        mode="shadow",
    )

    result = router.recall("memory", consumer="low_clue_recall")

    assert result["facts"][0]["provider"] == "hindsight"
    assert result["authoritative"] is False
    assert result["recall_llm_triggered"] is False
    assert result["local_first_authority_preserved"] is True


def test_active_hindsight_does_not_outrank_local_canonical_fact():
    local_fact = GroundingFact(
        provider="local_artifact",
        capability="recall",
        body_summary="local canonical",
        confidence=1.0,
        provenance="crystallized",
        source_event_refs=["cmem_1"],
        substrate_snapshot_id="local:canonical:v4",
        advisory_only=False,
        authority_class="local_canonical",
    )
    hindsight_fact = GroundingFact(
        provider="hindsight",
        capability="recall",
        body_summary="external candidate",
        confidence=0.99,
        provenance="hindsight_recall",
        source_event_refs=["h1"],
        substrate_snapshot_id="hindsight:bank:v1",
        advisory_only=True,
        authority_class="derived_projection",
    )
    router = SubstrateRouter(
        providers=[
            FakeProvider("hindsight", facts=[hindsight_fact]),
            FakeProvider("local_artifact", facts=[local_fact]),
        ],
        mode="active",
    )

    result = router.recall("memory", consumer="grounded_expression")

    assert result["facts"][0]["provider"] == "local_artifact"
    assert result["facts"][0]["authority_class"] == "local_canonical"
    assert result["facts"][1]["provider"] == "hindsight"
    assert result["facts"][1]["advisory_only"] is True
    assert result["authoritative"] is True
    assert result["external_authoritative_count"] == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```bash
python -m pytest tests/plugins/memory/test_memory_os_substrate_router.py -q
```

Expected: FAIL because `router.py` does not exist.

- [ ] **Step 3: Implement router**

Create `plugins/memory/memory_os/substrates/router.py`:

```python
"""Capability router for optional Memory-OS substrates."""

from __future__ import annotations

from typing import Any

from .base import GroundingFact


LOCAL_AUTHORITY_CLASSES = {"local_canonical", "owner_approved"}


def _health_value(health: Any, key: str, default: Any = None) -> Any:
    if isinstance(health, dict):
        return health.get(key, default)
    return getattr(health, key, default)


def _fact_to_dict(fact: Any) -> dict[str, Any]:
    if isinstance(fact, GroundingFact):
        return fact.to_monitor_dict() | {"body_summary": fact.body_summary}
    if isinstance(fact, dict):
        value = dict(fact)
        value.setdefault("advisory_only", True)
        value.setdefault("authority_class", "derived_projection")
        value.setdefault("recall_llm_triggered", False)
        return value
    return {
        "provider": "unknown",
        "body_summary": str(fact),
        "advisory_only": True,
        "authority_class": "derived_projection",
        "recall_llm_triggered": False,
    }


def _rank_fact(fact: dict[str, Any]) -> tuple[int, float]:
    authority_class = str(fact.get("authority_class") or "")
    provider = str(fact.get("provider") or "")
    confidence = float(fact.get("confidence") or 0.0)
    if provider == "local_artifact" and authority_class in LOCAL_AUTHORITY_CLASSES:
        return (0, -confidence)
    if authority_class in LOCAL_AUTHORITY_CLASSES:
        return (1, -confidence)
    return (2, -confidence)


class SubstrateRouter:
    def __init__(self, *, providers: list[Any] | None = None, mode: str = "shadow") -> None:
        self.providers = list(providers or [])
        self.mode = mode if mode in {"shadow", "active"} else "shadow"

    def recall(self, query: str, *, consumer: str) -> dict[str, Any]:
        facts: list[dict[str, Any]] = []
        fallback_triggered = True
        for provider in self.providers:
            health = provider.health()
            if _health_value(health, "status") != "ok" or "recall" not in set(_health_value(health, "capabilities", []) or []):
                continue
            provider_facts = provider.recall(query, consumer=consumer)
            if provider_facts:
                facts.extend(_fact_to_dict(fact) for fact in provider_facts)
                fallback_triggered = False
        facts.sort(key=_rank_fact)
        selected = str(facts[0].get("provider") or "unknown") if facts else "deterministic_fallback"
        authoritative = any(
            fact.get("advisory_only") is False
            and str(fact.get("authority_class") or "") in LOCAL_AUTHORITY_CLASSES
            for fact in facts
        )
        external_authoritative_count = sum(
            1
            for fact in facts
            if str(fact.get("provider") or "") != "local_artifact"
            and str(fact.get("authority_class") or "") in LOCAL_AUTHORITY_CLASSES
        )
        return {
            "schema_version": "memory-os.substrate_recall.v0",
            "consumer": consumer,
            "selected_provider": selected,
            "facts": facts,
            "authoritative": authoritative,
            "external_authoritative_count": external_authoritative_count,
            "local_first_authority_preserved": external_authoritative_count == 0,
            "fallback_triggered": fallback_triggered,
            "recall_llm_triggered": any(bool(fact.get("recall_llm_triggered")) for fact in facts),
        }
```

- [ ] **Step 4: Add shadow evidence recording without live prompt injection**

In `plugins/memory/memory_os/prefetch.py`, add a small shadow report path after route selection:

```python
from .substrates.ledger import SubstrateOperationLedger


def _record_substrate_shadow_recall(
    *,
    store: MemoryOSStore,
    query: str,
    report: dict[str, Any],
) -> None:
    path = store.roots.memory_os_root / "system" / "substrate_recall_shadow.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    facts = report.get("facts") if isinstance(report.get("facts"), list) else []
    record = {
        "schema_version": "memory-os.substrate_recall_shadow.v0",
        "query_class": report.get("query_class", ""),
        "query_sha256": _safe_query_hash(query),
        "selected_provider": report.get("selected_provider", ""),
        "fact_count": len(facts),
        "authoritative": bool(report.get("authoritative")),
        "external_authoritative_count": int(report.get("external_authoritative_count") or 0),
        "local_first_authority_preserved": bool(report.get("local_first_authority_preserved")),
        "recall_llm_triggered": bool(report.get("recall_llm_triggered")),
        "fallback_triggered": bool(report.get("fallback_triggered")),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    operation_ledger = SubstrateOperationLedger(store.roots.memory_os_root / "system" / "substrate_operations.jsonl")
    for fact in facts:
        provider = str(fact.get("provider") or "")
        if provider != "hindsight":
            continue
        operation_ledger.append(
            {
                "provider": "hindsight",
                "operation": "recall",
                "recall_llm_triggered": bool(fact.get("recall_llm_triggered")),
                "advisory_only": bool(fact.get("advisory_only")),
                "authority_class": str(fact.get("authority_class") or ""),
                "substrate_snapshot_id": str(fact.get("substrate_snapshot_id") or ""),
            }
        )
```

Use a hash helper, not raw query:

```python
def _safe_query_hash(query: str) -> str:
    import hashlib

    return hashlib.sha256(str(query or "").encode("utf-8")).hexdigest()
```

Wire this only when Hindsight recall mode is `shadow`; do not append Hindsight facts to the live prompt in this task.

- [ ] **Step 5: Run router and prefetch tests**

Run:

```bash
python -m pytest tests/plugins/memory/test_memory_os_substrate_router.py tests/plugins/memory/test_memory_os_prefetch.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/memory/memory_os/substrates/router.py plugins/memory/memory_os/prefetch.py plugins/memory/memory_os/memory_sources.py tests/plugins/memory/test_memory_os_substrate_router.py tests/plugins/memory/test_memory_os_prefetch.py
git commit -m "feat: record shadow substrate recall evidence"
```

---

### Task 6: Add Governed Retain Command for Approved Crystallized Memory

**Files:**
- Modify: `plugins/memory/memory_os/adapters/hindsight.py`
- Modify: `plugins/memory/memory_os/cli.py`
- Test: `tests/plugins/memory/test_memory_os_hindsight_adapter.py`
- Test: `tests/system_modularization/test_memory_os_agent_os_shell.py`

- [ ] **Step 1: Write retain-pending CLI tests**

Append to `tests/system_modularization/test_memory_os_agent_os_shell.py`:

```python
def test_hindsight_retain_pending_dry_run_is_no_write(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_retain_pending_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    report = hindsight_retain_pending_report(store, apply=False)

    assert report["schema_version"] == "memory-os.hindsight_retain_pending.v0"
    assert report["dry_run"] is True
    assert report["actual_retain"] is False
    assert report["raw_body_included"] is False
    assert report["ledger_write"] is False
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```bash
python -m pytest tests/system_modularization/test_memory_os_agent_os_shell.py::test_hindsight_retain_pending_dry_run_is_no_write -q
```

Expected: FAIL because the report does not exist.

- [ ] **Step 3: Implement dry-run/apply report**

In `plugins/memory/memory_os/cli.py`, add:

```python
def hindsight_retain_pending_report(store: MemoryOSStore, *, apply: bool = False) -> dict[str, Any]:
    from .adapters.hindsight import HindsightAdapter, HindsightAdapterConfig
    from .substrates.ledger import SubstrateOperationLedger
    from .substrates.projection import ProjectionLedger

    config = load_config(store.roots.hermes_home)
    substrate = ((config.get("substrate_providers") or {}).get("hindsight") or {})
    enabled = bool(substrate.get("enabled")) and bool(substrate.get("retain_enabled"))
    operation_ledger = SubstrateOperationLedger(store.roots.memory_os_root / "system" / "substrate_operations.jsonl")
    projection_ledger = ProjectionLedger(store.roots.memory_os_root / "system" / "projection_ledger.jsonl")
    if not apply:
        return {
            "schema_version": "memory-os.hindsight_retain_pending.v0",
            "dry_run": True,
            "enabled": enabled,
            "actual_retain": False,
            "raw_body_included": False,
            "ledger_write": False,
            "candidate_count": len(read_candidate_queue(store.roots)),
        }
    adapter = HindsightAdapter(store, config=HindsightAdapterConfig(enabled=enabled), client=None)
    report = adapter.export_all()
    exported_records = report.get("exported_records") if isinstance(report.get("exported_records"), list) else []
    for exported in exported_records:
        source_class = str(exported.get("source_class") or "")
        operation_ledger.append(
            {
                "provider": "hindsight",
                "operation": "retain",
                "source_class": source_class,
                "raw_body_included": False,
                "source_record_ref": str(exported.get("source_record_ref") or ""),
                "substrate_record_id": str(exported.get("substrate_record_id") or ""),
                "substrate_snapshot_id": str(exported.get("substrate_snapshot_id") or ""),
            }
        )
        projection_ledger.record_retain(
            provider="hindsight",
            source_record_ref=str(exported.get("source_record_ref") or ""),
            source_version=str(exported.get("source_version") or "current"),
            substrate_record_id=str(exported.get("substrate_record_id") or ""),
            substrate_snapshot_id=str(exported.get("substrate_snapshot_id") or ""),
        )
    return {
        "schema_version": "memory-os.hindsight_retain_pending.v0",
        "dry_run": False,
        "enabled": enabled,
        "actual_retain": bool(report.get("exported_count")),
        "raw_body_included": False,
        "ledger_write": bool(exported_records),
        "adapter_report": report,
    }
```

Update `HindsightAdapter.export_all()` so successful exports include an `exported_records` list with `source_record_ref`, `source_version`, `source_class`, `substrate_record_id`, and `substrate_snapshot_id`. The first apply implementation may report unavailable when no real client is configured. That is acceptable; it must not retain raw or silently succeed.

- [ ] **Step 4: Wire CLI**

Add subcommand:

```python
retain = hindsight_sub.add_parser("retain-pending")
retain.add_argument("--apply", action="store_true")
```

Dispatch:

```python
if args.hindsight_command == "retain-pending":
    print(json.dumps(hindsight_retain_pending_report(store, apply=bool(args.apply)), ensure_ascii=False, indent=2, sort_keys=True))
    return 0
```

- [ ] **Step 5: Run tests**

Run:

```bash
python -m pytest tests/plugins/memory/test_memory_os_hindsight_adapter.py tests/system_modularization/test_memory_os_agent_os_shell.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/memory/memory_os/adapters/hindsight.py plugins/memory/memory_os/cli.py tests/plugins/memory/test_memory_os_hindsight_adapter.py tests/system_modularization/test_memory_os_agent_os_shell.py
git commit -m "feat: add governed hindsight retain command"
```

---

### Task 6A: Add Projection Retract/Invalidate for Canonical Demotion

**Files:**
- Create: `plugins/memory/memory_os/substrates/projection.py`
- Modify: `plugins/memory/memory_os/substrates/hindsight.py`
- Modify: `plugins/memory/memory_os/cli.py`
- Modify: `plugins/modules/governance/crystallized_revalidator.py`
- Test: `tests/plugins/memory/test_memory_os_projection_coherence.py`
- Test: `tests/system_modularization/test_memory_os_agent_os_shell.py`

- [ ] **Step 1: Write projection coherence tests**

Create `tests/plugins/memory/test_memory_os_projection_coherence.py`:

```python
from plugins.memory.memory_os.substrates.projection import (
    ProjectionLedger,
    derive_projection_coherence,
)


def test_projection_retract_marks_derived_fact_invalid(tmp_path):
    ledger = ProjectionLedger(tmp_path / "projection_ledger.jsonl")
    ledger.record_retain(
        provider="hindsight",
        source_record_ref="cmem_1",
        source_version="4",
        substrate_record_id="h1",
        substrate_snapshot_id="hindsight:bank:v4",
    )

    ledger.record_invalidate(
        provider="hindsight",
        source_record_ref="cmem_1",
        source_version="4",
        reason="crystallized_demoted",
        substrate_snapshot_id="hindsight:bank:v5",
    )

    coherence = derive_projection_coherence(ledger.read_all(), provider="hindsight")

    assert coherence["active_projection_count"] == 0
    assert coherence["retract_count"] == 1
    assert coherence["projection_stale_count"] == 0


def test_missing_retract_is_reported_as_stale_projection(tmp_path):
    ledger = ProjectionLedger(tmp_path / "projection_ledger.jsonl")
    ledger.record_retain(
        provider="hindsight",
        source_record_ref="cmem_2",
        source_version="1",
        substrate_record_id="h2",
        substrate_snapshot_id="hindsight:bank:v1",
    )

    coherence = derive_projection_coherence(
        ledger.read_all(),
        provider="hindsight",
        demoted_source_refs={"cmem_2"},
    )

    assert coherence["projection_stale_count"] == 1
    assert coherence["stale_source_refs"] == ["cmem_2"]


def test_owner_revoke_path_records_projection_invalidation(tmp_path):
    from plugins.modules.governance.crystallized_revalidator import (
        invalidate_hindsight_projection_for_canonical_change,
    )

    invalidate_hindsight_projection_for_canonical_change(
        projection_ledger_path=tmp_path / "projection_ledger.jsonl",
        record_id="cmem_3",
        record_version="2",
        reason="owner_revoked",
        substrate_snapshot_id="hindsight:bank:v3",
    )

    records = ProjectionLedger(tmp_path / "projection_ledger.jsonl").read_all()

    assert records[-1]["operation"] == "invalidate"
    assert records[-1]["reason"] == "owner_revoked"
    assert records[-1]["source_record_ref"] == "cmem_3"
```

Append this CLI test to `tests/system_modularization/test_memory_os_agent_os_shell.py`:

```python
def test_hindsight_retract_dry_run_is_no_delete(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_retract_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    report = hindsight_retract_report(store, record_id="cmem_1", reason="owner_revoked", apply=False)

    assert report["schema_version"] == "memory-os.hindsight_retract.v0"
    assert report["dry_run"] is True
    assert report["actual_delete"] is False
    assert report["invalidation_reason"] == "owner_revoked"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:

```bash
python -m pytest \
  tests/plugins/memory/test_memory_os_projection_coherence.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py::test_hindsight_retract_dry_run_is_no_delete \
  -q
```

Expected: FAIL because projection ledger and retract report do not exist.

- [ ] **Step 3: Implement projection ledger**

Create `plugins/memory/memory_os/substrates/projection.py`:

```python
"""Projection coherence helpers for derived substrates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ProjectionLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def record_retain(
        self,
        *,
        provider: str,
        source_record_ref: str,
        source_version: str,
        substrate_record_id: str,
        substrate_snapshot_id: str,
    ) -> None:
        self.append(
            {
                "provider": provider,
                "operation": "retain",
                "source_record_ref": source_record_ref,
                "source_version": source_version,
                "substrate_record_id": substrate_record_id,
                "substrate_snapshot_id": substrate_snapshot_id,
                "projection_status": "active",
            }
        )

    def record_invalidate(
        self,
        *,
        provider: str,
        source_record_ref: str,
        source_version: str,
        reason: str,
        substrate_snapshot_id: str,
    ) -> None:
        self.append(
            {
                "provider": provider,
                "operation": "invalidate",
                "source_record_ref": source_record_ref,
                "source_version": source_version,
                "reason": reason,
                "substrate_snapshot_id": substrate_snapshot_id,
                "projection_status": "invalidated",
            }
        )

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
        return records


def derive_projection_coherence(
    records: list[dict[str, Any]],
    *,
    provider: str,
    demoted_source_refs: set[str] | None = None,
) -> dict[str, Any]:
    demoted_source_refs = demoted_source_refs or set()
    provider_records = [record for record in records if record.get("provider") == provider]
    retained_refs = {
        str(record.get("source_record_ref"))
        for record in provider_records
        if record.get("operation") == "retain"
    }
    invalidated_refs = {
        str(record.get("source_record_ref"))
        for record in provider_records
        if record.get("operation") in {"invalidate", "retract"}
    }
    active_refs = sorted(ref for ref in retained_refs if ref and ref not in invalidated_refs)
    stale_refs = sorted(ref for ref in active_refs if ref in demoted_source_refs)
    return {
        "provider": provider,
        "active_projection_count": len(active_refs) - len(stale_refs),
        "retract_count": len(invalidated_refs),
        "projection_stale_count": len(stale_refs),
        "stale_source_refs": stale_refs,
    }
```

- [ ] **Step 4: Add Hindsight invalidation surface**

In `plugins/memory/memory_os/substrates/hindsight.py`, extend the client protocol:

```python
def invalidate(self, payload: dict[str, Any]) -> dict[str, Any]:
    ...
```

Add method to `GovernedHindsightSubstrate`:

```python
def invalidate_projection(self, *, source_record_ref: str, source_version: str, reason: str) -> dict[str, Any]:
    if not self.config.enabled:
        return {"ok": False, "status": "disabled", "operation": "invalidate"}
    payload = {
        "schema_version": "memory-os.hindsight_invalidate.v0",
        "source_record_ref": source_record_ref,
        "source_version": source_version,
        "reason": reason,
        "substrate_snapshot_id": self.config.snapshot_id,
        "delete_policy": "invalidate_not_delete",
    }
    if self.client is None:
        return {"ok": False, "status": "unavailable", "operation": "invalidate", "payload": payload}
    return self.client.invalidate(payload)
```

This method invalidates the derived projection. It must not delete canonical Memory-OS state.

- [ ] **Step 5: Implement CLI retract report**

In `plugins/memory/memory_os/cli.py`, add:

```python
def hindsight_retract_report(
    store: MemoryOSStore,
    *,
    record_id: str,
    reason: str,
    apply: bool = False,
) -> dict[str, Any]:
    config = load_config(store.roots.hermes_home)
    substrate = ((config.get("substrate_providers") or {}).get("hindsight") or {})
    projection_ledger = ProjectionLedger(store.roots.memory_os_root / "system" / "projection_ledger.jsonl")
    planned = {
        "provider": "hindsight",
        "source_record_ref": record_id,
        "source_version": "current",
        "reason": reason,
        "substrate_snapshot_id": str(substrate.get("substrate_snapshot_id") or ""),
    }
    if apply:
        projection_ledger.record_invalidate(
            provider="hindsight",
            source_record_ref=record_id,
            source_version="current",
            reason=reason,
            substrate_snapshot_id=str(substrate.get("substrate_snapshot_id") or ""),
        )
    return {
        "schema_version": "memory-os.hindsight_retract.v0",
        "dry_run": not apply,
        "enabled": bool(substrate.get("enabled")),
        "actual_delete": False,
        "actual_invalidate": bool(apply),
        "invalidation_reason": reason,
        "planned": planned,
    }
```

Wire `hindsight retract --record-id ID --reason REASON [--apply]`.

- [ ] **Step 6: Couple crystallized revalidation to projection invalidation**

In `plugins/modules/governance/crystallized_revalidator.py`, add an exported narrow hook and call it at the point where a crystallized record is actually demoted or owner approval is revoked:

```python
def invalidate_hindsight_projection_for_canonical_change(
    *,
    projection_ledger_path: Path,
    record_id: str,
    record_version: str,
    reason: str,
    substrate_snapshot_id: str,
) -> None:
    projection_ledger = ProjectionLedger(projection_ledger_path)
    projection_ledger.record_invalidate(
        provider="hindsight",
        source_record_ref=record_id,
        source_version=record_version,
        reason=reason,
        substrate_snapshot_id=substrate_snapshot_id,
    )
```

Call this only after the canonical demotion/revocation state transition succeeds. If the revalidator has a queued side-effect mechanism, enqueue this invalidation there and require the queue item to be visible in monitor as pending until applied.

In the same implementation slice, grep and enumerate every owner-facing revoke/demotion entrypoint and wire the same hook. Minimum search commands:

```bash
rg -n "revoke|revoked|demote|demoted|owner_approved|APPROVE_FOR_CRYSTALLIZED|crystallized" plugins/memory plugins/modules tests
```

Add one test per discovered public entrypoint. If an entrypoint cannot affect projected Hindsight records, add a test or doc assertion explaining the proof.

- [ ] **Step 7: Run projection coherence tests**

Run:

```bash
python -m pytest \
  tests/plugins/memory/test_memory_os_projection_coherence.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py::test_hindsight_retract_dry_run_is_no_delete \
  -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add plugins/memory/memory_os/substrates/projection.py plugins/memory/memory_os/substrates/hindsight.py plugins/memory/memory_os/cli.py plugins/modules/governance/crystallized_revalidator.py tests/plugins/memory/test_memory_os_projection_coherence.py tests/system_modularization/test_memory_os_agent_os_shell.py
git commit -m "feat: invalidate derived hindsight projections"
```

---

### Task 7: Keep Reflect Explicit, Async, and Default Off

**Files:**
- Modify: `plugins/memory/memory_os/substrates/hindsight.py`
- Modify: `plugins/memory/memory_os/cli.py`
- Test: `tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py`
- Test: `tests/system_modularization/test_memory_os_agent_os_shell.py`

- [ ] **Step 1: Write reflect CLI disabled test**

Append:

```python
def test_hindsight_reflect_dry_run_reports_disabled_by_default(tmp_path):
    from plugins.memory.memory_os.cli import hindsight_reflect_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()

    report = hindsight_reflect_report(store, query="what pattern matters?", apply=False)

    assert report["schema_version"] == "memory-os.hindsight_reflect.v0"
    assert report["status"] == "disabled"
    assert report["off_hot_path"] is True
    assert report["actual_canonical_write"] is False
```

- [ ] **Step 2: Run the test to confirm it fails**

Run:

```bash
python -m pytest tests/system_modularization/test_memory_os_agent_os_shell.py::test_hindsight_reflect_dry_run_reports_disabled_by_default -q
```

Expected: FAIL.

- [ ] **Step 3: Implement reflect report**

In `cli.py`:

```python
def hindsight_reflect_report(store: MemoryOSStore, *, query: str, apply: bool = False) -> dict[str, Any]:
    from .substrates.ledger import SubstrateOperationLedger

    config = load_config(store.roots.hermes_home)
    substrate = ((config.get("substrate_providers") or {}).get("hindsight") or {})
    if not bool(substrate.get("reflect_enabled")):
        return {
            "schema_version": "memory-os.hindsight_reflect.v0",
            "status": "disabled",
            "off_hot_path": True,
            "actual_canonical_write": False,
            "query_sha256": _sha256_text(query),
        }
    if apply:
        SubstrateOperationLedger(store.roots.memory_os_root / "system" / "substrate_operations.jsonl").append(
            {
                "provider": "hindsight",
                "operation": "reflect",
                "phase": "async",
                "raw_body_included": False,
                "substrate_snapshot_id": str(substrate.get("substrate_snapshot_id") or ""),
            }
        )
    return {
        "schema_version": "memory-os.hindsight_reflect.v0",
        "status": "configured",
        "off_hot_path": True,
        "actual_canonical_write": False,
        "query_sha256": _sha256_text(query),
        "dry_run": not apply,
    }


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
```

Add `hindsight reflect --query TEXT [--apply]` parser. `--apply` must still not write canonical; reflected output can only become a candidate through a later owner-gated path.

The later owner-gated candidate promotion is intentionally outside this implementation plan. Do not add an implicit reflect-to-candidate shortcut while implementing Task 7.

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py tests/system_modularization/test_memory_os_agent_os_shell.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/memory_os/substrates/hindsight.py plugins/memory/memory_os/cli.py tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py tests/system_modularization/test_memory_os_agent_os_shell.py
git commit -m "feat: keep hindsight reflect explicit and off hot path"
```

---

### Task 8: Extend Monitor and Upgrade Compatibility Checks

**Files:**
- Modify: `scripts/memory_os_upgrade_compat_check.py`
- Modify: `scripts/memory_os_3_200_monitor.py`
- Modify: `plugins/memory/memory_os/cli.py`
- Test: `tests/scripts/test_memory_os_upgrade_compat_check.py`
- Test: `tests/scripts/test_memory_os_3_200_monitor.py`

- [ ] **Step 1: Write upgrade compatibility classification tests**

Append to `tests/scripts/test_memory_os_upgrade_compat_check.py`:

```python
def test_upgrade_check_accepts_optional_hindsight_off():
    from scripts.memory_os_upgrade_compat_check import classify_report

    results = {
        "memory_provider": {"exit_code": 0, "stdout_preview": "Provider: memory_os active"},
        "hindsight_status": {
            "exit_code": 0,
            "json": {
                "schema_version": "memory-os.hindsight_substrate_status.v0",
                "enabled": False,
                "status": "optional_not_configured",
            },
        },
    }

    classification = classify_report(results)

    assert {"code": "hindsight_optional_off_ok"} in classification["pass"]
    assert not [item for item in classification["fail"] if item["code"].startswith("hindsight")]


def test_upgrade_check_fails_when_substrate_monitor_reports_raw_retain():
    from scripts.memory_os_upgrade_compat_check import classify_report

    results = {
        "memory_provider": {"exit_code": 0, "stdout_preview": "Provider: memory_os active"},
        "hindsight_status": {
            "exit_code": 0,
            "json": {
                "schema_version": "memory-os.hindsight_substrate_status.v0",
                "enabled": True,
                "status": "configured",
                "recall_mode": "shadow",
                "substrate_monitor": {
                    "raw_retained_count": 1,
                    "no_raw_retained": False,
                    "projection_stale_count": 0,
                    "local_first_authority_preserved": True,
                },
            },
        },
    }

    classification = classify_report(results)

    assert {"code": "hindsight_raw_retain_detected"} in classification["fail"]


def test_upgrade_check_fails_when_projection_stale_count_is_positive():
    from scripts.memory_os_upgrade_compat_check import classify_report

    results = {
        "memory_provider": {"exit_code": 0, "stdout_preview": "Provider: memory_os active"},
        "hindsight_status": {
            "exit_code": 0,
            "json": {
                "schema_version": "memory-os.hindsight_substrate_status.v0",
                "enabled": True,
                "status": "configured",
                "recall_mode": "shadow",
                "substrate_monitor": {
                    "raw_retained_count": 0,
                    "projection_stale_count": 1,
                    "local_first_authority_preserved": True,
                },
            },
        },
    }

    classification = classify_report(results)

    assert {"code": "hindsight_projection_stale"} in classification["fail"]


def test_upgrade_check_fails_when_external_provider_claims_authority():
    from scripts.memory_os_upgrade_compat_check import classify_report

    results = {
        "memory_provider": {"exit_code": 0, "stdout_preview": "Provider: memory_os active"},
        "hindsight_status": {
            "exit_code": 0,
            "json": {
                "schema_version": "memory-os.hindsight_substrate_status.v0",
                "enabled": True,
                "status": "configured",
                "recall_mode": "active",
                "substrate_monitor": {
                    "raw_retained_count": 0,
                    "projection_stale_count": 0,
                    "local_first_authority_preserved": False,
                    "external_authoritative_count": 1,
                },
            },
        },
    }

    classification = classify_report(results)

    assert {"code": "hindsight_overrode_local_authority"} in classification["fail"]
```

- [ ] **Step 2: Run test to confirm it fails**

Run:

```bash
python -m pytest tests/scripts/test_memory_os_upgrade_compat_check.py::test_upgrade_check_accepts_optional_hindsight_off -q
```

Expected: FAIL because `hindsight_status` is not classified.

- [ ] **Step 3: Add read-only command spec**

In `scripts/memory_os_upgrade_compat_check.py`, add to `COMMANDS`:

```python
CommandSpec("hindsight_status", ("hermes", "memory-os-agent-os", "hindsight", "status")),
```

Add classifier:

```python
def _require_hindsight_status(results: dict[str, dict[str, Any]], passed: list[dict[str, Any]], fail: list[dict[str, Any]]) -> None:
    data = results.get("hindsight_status", {}).get("json")
    if not isinstance(data, dict):
        fail.append({"code": "hindsight_status_missing_json"})
        return
    if data.get("schema_version") != "memory-os.hindsight_substrate_status.v0":
        fail.append({"code": "hindsight_status_schema_mismatch"})
        return
    if data.get("enabled") is False and data.get("status") == "optional_not_configured":
        passed.append({"code": "hindsight_optional_off_ok"})
        return
    if data.get("enabled") is True and data.get("recall_mode") in {"shadow", "active"}:
        monitor = data.get("substrate_monitor") if isinstance(data.get("substrate_monitor"), dict) else {}
        if int(monitor.get("raw_retained_count") or 0) > 0 or monitor.get("no_raw_retained") is False:
            fail.append({"code": "hindsight_raw_retain_detected"})
            return
        if int(monitor.get("projection_stale_count") or 0) > 0:
            fail.append({"code": "hindsight_projection_stale"})
            return
        if monitor.get("local_first_authority_preserved") is False:
            fail.append({"code": "hindsight_overrode_local_authority"})
            return
        passed.append({"code": "hindsight_configured_ok"})
        return
    fail.append({"code": "hindsight_status_invalid", "status": data.get("status")})
```

Call it from `classify_report()`.

- [ ] **Step 4: Add monitor fields**

In `scripts/memory_os_3_200_monitor.py`, derive the Memory-OS substrate monitor fields from the operation and projection ledgers:

```python
from plugins.memory.memory_os.substrates.ledger import (
    SubstrateOperationLedger,
    derive_substrate_monitor_fields,
)
from plugins.memory.memory_os.substrates.projection import (
    ProjectionLedger,
    derive_projection_coherence,
)


def _derive_hindsight_monitor(store: MemoryOSStore, status: dict[str, Any]) -> dict[str, Any]:
    operations_path = store.roots.memory_os_root / "system" / "substrate_operations.jsonl"
    projections_path = store.roots.memory_os_root / "system" / "projection_ledger.jsonl"
    operation_records = SubstrateOperationLedger(operations_path).read_all()
    projection_records = ProjectionLedger(projections_path).read_all()
    operation_fields = derive_substrate_monitor_fields(operation_records, provider="hindsight")
    projection_fields = derive_projection_coherence(projection_records, provider="hindsight")
    recall_shadow = status.get("substrate_recall_shadow") if isinstance(status.get("substrate_recall_shadow"), dict) else {}
    return {
        **operation_fields,
        **projection_fields,
        "retain_source_class_allowed": ["crystallized", "owner_approved", "distilled"],
        "local_first_authority_preserved": recall_shadow.get("local_first_authority_preserved") if recall_shadow else None,
        "external_authoritative_count": int(recall_shadow.get("external_authoritative_count") or 0),
        "kill_switch_forced_disabled": bool(status.get("kill_switch_forced_disabled")),
    }


"hindsight_substrate": status.get("hindsight_substrate", {}),
"substrate_recall": _derive_hindsight_monitor(store, status),
```

If the monitor already has a consolidated report object, place these fields next to existing Memory-OS substrate, `memory_sources`, and `low_clue_recall` fields. Do not report `no_raw_retained`, `recall_llm_triggered`, or `reflect_off_hot_path` unless the value came from ledger-derived fields.

- [ ] **Step 5: Run monitor and compat tests**

Run:

```bash
python -m pytest tests/scripts/test_memory_os_upgrade_compat_check.py tests/scripts/test_memory_os_3_200_monitor.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/memory_os_upgrade_compat_check.py scripts/memory_os_3_200_monitor.py tests/scripts/test_memory_os_upgrade_compat_check.py tests/scripts/test_memory_os_3_200_monitor.py
git commit -m "test: monitor governed hindsight substrate boundaries"
```

---

### Task 9: Document Operator Modes and Rollout Gates

**Files:**
- Modify: `README.md`
- Modify: `docs/configuration.md`
- Modify: `docs/quickstart.md`
- Modify: `docs/memory-os-hermes-integration-boundary-design-v3.md`

- [ ] **Step 1: Update quickstart install examples**

In `README.md` and `docs/quickstart.md`, add:

```bash
# Normal open-source install. Hindsight stays off unless an existing
# Hermes Hindsight config is detected, in which case it is adopted in shadow mode.
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --operational --hindsight auto

# Conservative install: never adopt Hindsight automatically.
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --production-safe --hindsight off
```

- [ ] **Step 2: Document exact mode semantics**

In `docs/configuration.md`, add section:

```markdown
## Optional Governed Hindsight Substrate

Memory-OS treats Hindsight as an optional governed substrate, not as the active
Hermes memory provider. The production relationship remains:

```text
memory.provider = memory_os
Hindsight direct provider = not selected
Memory-OS Hindsight substrate = optional, governed, derived projection
```

Installer modes:

| Mode | Behavior |
| --- | --- |
| `--hindsight auto` | Default. If `$HERMES_HOME/hindsight/config.json` exists, copy safe connection metadata into Memory-OS and enable Hindsight in `shadow` recall mode. If no config exists, keep Hindsight disabled. |
| `--hindsight off` | Keep Hindsight disabled even if a legacy config exists. |
| `--hindsight adopt` | Require an existing legacy config and adopt it into Memory-OS shadow mode, failing if config is missing. |
| `--hindsight wizard` | Defer setup to an operator-guided command. |

Adoption never enables Hermes direct `memory.provider=hindsight` and never turns
on raw turn retention. Retain accepts only governed Memory-OS sources:
`crystallized`, `owner_approved`, and explicitly enabled `distilled`.

Hindsight is a derived projection of canonical Memory-OS state. Every retained
projection must have a projection ledger entry, and every canonical demotion or
owner revocation must produce an invalidate/retract entry. Monitor and upgrade
checks treat stale active projections as a stop signal.

LocalArtifact remains the primary authority. Hindsight recall is always marked
`advisory_only=true` and `authority_class=derived_projection`; `active` mode
only means Hindsight facts may be injected as advisory context after local
canonical facts. It does not make Hindsight authoritative.
```

- [ ] **Step 3: Patch V3 caveats**

In `docs/memory-os-hermes-integration-boundary-design-v3.md`, add a correction note:

```markdown
### 0.15 Evidence Corrections

- `memory.provider` is a single external provider slot, but Hermes built-in
  `MEMORY.md` and `USER.md` remain active when their config flags are true.
- `context.engine` is a separate single engine slot. It can coexist with
  `memory.provider=memory_os`, but it is not a second memory provider.
- Current 0.15.1 wraps recalled provider context as authoritative reference
  data, so Memory-OS recall output must carry its own advisory/provenance
  markers.
```

- [ ] **Step 4: Run docs sanity checks**

Run:

```bash
rg -n "memory.provider=hindsight|auto_retain=true|raw transcript retain" README.md docs --glob "!docs/superpowers/plans/2026-06-01-memory-os-governed-hindsight-substrate.md"
python scripts/memory_os_upgrade_compat_check.py --host hermes-media --output summary
```

Expected:
- `rg` has no new unsafe recommendation to set `memory.provider=hindsight`.
- Compat check prints `Memory-OS Hermes upgrade compatibility: PASS`.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/configuration.md docs/quickstart.md docs/memory-os-hermes-integration-boundary-design-v3.md
git commit -m "docs: document governed hindsight substrate rollout"
```

---

### Task 10: Live Shadow Rollout on hermes-media After Implementation

**Files:**
- No source edits in this task.
- Commands target `hermes-media` through `scripts/deploy_memory_os.py` first. Direct SSH commands are diagnostic fallback only.

- [ ] **Step 1: Render deployment plan**

Run:

```powershell
python scripts/deploy_memory_os.py `
  --host hermes-media `
  --remote-repo-root /opt/Hermes-Memory-OS `
  --hermes-home /root/.hermes `
  --profile upgrade `
  --phase plan `
  --mode operational `
  --hindsight auto
```

Expected:
- Report schema is `memory-os.deploy.v0`.
- `restart_requested=false`.
- Install command includes `--hindsight auto`.
- No secrets or raw memory bodies are printed.

- [ ] **Step 2: Run read-only deployment preflight**

Run:

```powershell
python scripts/deploy_memory_os.py `
  --host hermes-media `
  --remote-repo-root /opt/Hermes-Memory-OS `
  --hermes-home /root/.hermes `
  --profile upgrade `
  --phase preflight `
  --mode operational `
  --hindsight auto `
  --output json
```

Expected:
- `preflight.status=pass`.
- Compatibility check has no FAIL.
- If this fails, stop before install dry-run.

- [ ] **Step 3: Run automated install dry-run**

Run:

```powershell
python scripts/deploy_memory_os.py `
  --host hermes-media `
  --remote-repo-root /opt/Hermes-Memory-OS `
  --hermes-home /root/.hermes `
  --profile upgrade `
  --phase dry-run `
  --mode operational `
  --hindsight auto `
  --output json
```

Expected:
- `preflight.status=pass`.
- `dry_run.status=pass`.
- Installer dry-run reports `memory-os.install.v0`.
- Planned Hindsight mode is adoption into Memory-OS shadow mode.
- No actual retain, restart, cleanup, or shadow-journal apply.

- [ ] **Step 4: Run bank pollution and projection pre-apply scan**

Run read-only diagnostics:

```powershell
ssh hermes-media 'hermes memory-os-agent-os hindsight status'
ssh hermes-media 'hermes memory-os-agent-os hindsight retain-pending'
ssh hermes-media 'hermes memory-os-agent-os hindsight retract --record-id dry-run-placeholder --reason rollout_precheck'
```

Expected:
- No raw body included.
- No actual retain or delete.
- `substrate_monitor.raw_retained_count=0`.
- `projection_stale_count=0` or unavailable before first retain.
- No indication that direct Hermes Hindsight provider is active.

- [ ] **Step 5: Apply automated deployment only after review**

Run only after owner approval:

```powershell
python scripts/deploy_memory_os.py `
  --host hermes-media `
  --remote-repo-root /opt/Hermes-Memory-OS `
  --hermes-home /root/.hermes `
  --profile upgrade `
  --phase apply `
  --mode operational `
  --hindsight auto `
  --output json
```

Expected:
- `preflight.status=pass`.
- `dry_run.status=pass`.
- `apply.status=applied`.
- `postcheck.status=pass`.
- `memory.provider=memory_os`.
- Memory-OS config gains `substrate_providers.hindsight.enabled=true` only when adoption is applicable.
- Recall remains `shadow`.
- Reflect remains disabled.
- No service restart unless `--allow-restart --restart-command` was explicitly supplied.

- [ ] **Step 6: Restart gate**

If the active gateway needs config reload, ask the owner before restart. If approved, restart only the intended `hermes-media` gateway service or process through the deployment wrapper:

```powershell
python scripts/deploy_memory_os.py `
  --host hermes-media `
  --remote-repo-root /opt/Hermes-Memory-OS `
  --hermes-home /root/.hermes `
  --profile upgrade `
  --phase apply `
  --mode operational `
  --hindsight auto `
  --allow-restart `
  --restart-command 'systemctl --user restart hermes-gateway.service' `
  --output json
```

Expected:
- Restart command is present in the deploy report.
- Restart scope is exactly the intended service.
- Postcheck compatibility PASS after restart.

- [ ] **Step 7: Promotion gate**

Do not promote Hindsight recall to active until all are true:

```text
local tests PASS
deployment dry-run PASS
deployment apply postcheck PASS
upgrade compatibility PASS
hindsight bank pollution scan PASS
substrate monitor derives no_raw_retained = true from raw_retained_count = 0
substrate monitor derives recall_llm_triggered = false from recall operation records
substrate monitor derives reflect_off_hot_path = true from reflect_hot_path_count = 0
projection monitor reports projection_stale_count = 0 and retract_count >= expected invalidations
recall monitor reports local_first_authority_preserved = true and external_authoritative_count = 0
shadow recall monitor has no FAIL for at least one observation window
owner approves active recall
```

Promotion command, when implemented and approved:

```powershell
ssh hermes-media 'hermes memory-os-agent-os hindsight set-recall-mode active --apply'
```

Expected: active recall only changes Memory-OS substrate routing, not Hermes direct provider.

---

## Verification Matrix

Run before claiming implementation complete:

```bash
python -m pytest \
  tests/plugins/memory/test_memory_os_substrate_base.py \
  tests/plugins/memory/test_memory_os_substrate_ledger.py \
  tests/plugins/memory/test_memory_os_local_artifact_provider.py \
  tests/plugins/memory/test_memory_os_hindsight_adapter.py \
  tests/plugins/memory/test_memory_os_hindsight_substrate_config.py \
  tests/plugins/memory/test_memory_os_hindsight_substrate_provider.py \
  tests/plugins/memory/test_memory_os_projection_coherence.py \
  tests/plugins/memory/test_memory_os_substrate_router.py \
  tests/plugins/memory/test_memory_os_prefetch.py \
  tests/scripts/test_memory_os_plugin_install.py \
  tests/scripts/test_memory_os_deploy.py \
  tests/scripts/test_memory_os_upgrade_compat_check.py \
  tests/scripts/test_memory_os_3_200_monitor.py \
  tests/system_modularization/test_memory_os_agent_os_shell.py \
  -q
```

Run before any live promotion:

```bash
python scripts/deploy_memory_os.py --host hermes-media --remote-repo-root /opt/Hermes-Memory-OS --hermes-home /root/.hermes --profile upgrade --phase dry-run --mode operational --hindsight auto --output json
python scripts/memory_os_upgrade_compat_check.py --host hermes-media --output summary
```

Expected:

```text
Memory-OS Hermes upgrade compatibility: PASS
WARN: []
FAIL: []
```

## Review Checklist

- Hindsight disabled by default for clean open-source installs.
- Existing Hindsight config is adopted into Memory-OS shadow mode, not used as direct Hermes provider.
- Direct Hermes Hindsight `auto_retain` is never required and never recommended.
- Automated deployment has plan, preflight, dry-run, apply, and postcheck phases.
- Deployment compatibility distinguishes `fresh` and `upgrade` profiles.
- Deployment apply is blocked when upgrade preflight or installer dry-run fails.
- Deployment does not restart Hermes unless explicitly passed `--allow-restart --restart-command`.
- Hindsight retain accepts only governed source classes.
- Hindsight retract/invalidate is wired to canonical demotion and owner revocation.
- Every public owner revoke/demotion path either calls projection invalidation after canonical state changes, or proves it cannot affect Hindsight-projected records.
- Projection monitor reports stale derived facts as a stop signal.
- Compat/monitor classify `projection_stale_count>0`, `local_first_authority_preserved=false`, and `external_authoritative_count>0` as FAIL.
- LocalArtifact remains the first-ranked authority; Hindsight remains advisory in shadow and active modes.
- Recall trigger is deterministic and reportable.
- Reflect remains explicit, async, and off hot path.
- Reflect-to-candidate promotion is deferred to a later owner-gated slice and is not silently added here.
- Monitor fields `no_raw_retained`, `recall_llm_triggered`, `reflect_off_hot_path`, `retract_count`, and `projection_stale_count` are derived from ledgers.
- Each retain/recall/reflect/retract record carries `substrate_snapshot_id`.
- Global kill switch forces optional external substrates disabled.
- `hindsight_adapter_enabled` is compatibility-only and not an effective enable source.
- CLI and installer never print secrets.
- Doctor treats optional Hindsight-off as healthy.
- Monitor distinguishes local PASS, integration PASS, live PASS, and shadow evidence.
- Live rollout on `hermes-media` starts as read-only, then dry-run, then owner-approved apply, then optional restart, then observation, then promotion.
