"""Knob A/B Self-Validation — stratified real-result evaluation for min_cluster_size.

No-agent lane: deterministic data join + confirm rate comparison.
Only tighten direction (override > prior) can auto-decide; relax always falls
back to owner. Module constants AB_MARGIN and AB_MIN_OBS are NOT in
OVERRIDABLE_KNOBS — boundary-is-store protection (stronger than meta marking).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Module constants (boundary-is-store: NOT in OVERRIDABLE_KNOBS) ──
AB_MARGIN = 0.15    # confirm rate diff >= 15pp to decide (conservative start)
AB_MIN_OBS = 5      # at least 5 owner decisions (confirm+reject) per layer to decide


def knob_ab_eval_manifest() -> dict[str, Any]:
    return {
        "name": "knob_ab_eval",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0"],
        },
        "provides": {
            "commands": ["status", "doctor", "run_once"],
            "schedules": [],
            "reads": [
                "memory_os.knob_overrides",
                "memory_os.candidate_triage",
                "memory_os.owner_actions",
            ],
            "writes": ["memory_os.knob_overrides"],
        },
        "defaults": {
            "enabled": True,
            "profile_scope": "per-profile",
        },
    }


class KnobABEvalModule:
    """Stratified real-result A/B evaluation for overridable knobs with ab_metric."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "knob_ab_eval"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def run_once(
        self,
        *,
        store: Any = None,
        _now: datetime | None = None,
        _store_root: Path | None = None,
    ) -> dict[str, Any]:
        """Run one tick: evaluate active overrides with ab_metric.

        For each active override on a knob with ab_metric set:
        - Tighten (override > prior): evaluate using real owner decisions,
          stratified by cluster_size. Auto-confirm if the discarded layer
          (size==prior) has significantly lower confirm rate than the retained
          layer (size>=override). Auto-revert if significantly higher.
        - Relax (override < prior): always falls back to owner (no data).
        - Insufficient observations: falls back to owner (conservative).
        """
        from plugins.memory.memory_os.knob_overrides import (
            OVERRIDABLE_KNOBS,
            list_active_overrides,
            confirm_override,
            revert_override,
        )
        from plugins.memory.memory_os.jsonl_io import build_error_record

        now = _now or datetime.now(timezone.utc)
        active = list_active_overrides(_store_root=_store_root, _now=now)

        confirmed = 0
        reverted = 0
        skipped_no_data = 0
        skipped_insufficient_obs = 0
        error_records: list[dict[str, Any]] = []

        for override in active:
            knob_name = str(override.get("knob") or "")
            knob_spec = OVERRIDABLE_KNOBS.get(knob_name)
            if knob_spec is None:
                continue
            ab_metric = knob_spec.get("ab_metric")
            if not ab_metric:
                continue  # knob not configured for A/B

            override_value = override.get("override_value")
            prior_value = override.get("prior_value")

            # Only tighten direction has real data
            if override_value <= prior_value:
                skipped_no_data += 1
                continue

            # Three-table join for data provenance (F3):
            #   1. candidate_triage.jsonl — promotion records with cluster_size (C6)
            #   2. owner_actions.jsonl — owner decisions, joined by target_id
            #   3. Group by cluster_size, compute confirm rate per layer
            try:
                layer_rates = _compute_stratified_confirm_rates(
                    store, knob_name=knob_name,
                )
            except Exception:
                error_records.append(
                    build_error_record(
                        component="knob_ab_eval",
                        operation="compute_stratified_confirm_rates",
                        error_code="COMPUTE_FAILED",
                        severity="error",
                        recoverable=True,
                        details={"knob": knob_name, "override_id": override.get("id")},
                    )
                )
                continue

            if not layer_rates:
                skipped_insufficient_obs += 1
                continue

            # Discarded layer: size==prior_value (dropped by tightening)
            # Retained layer: size>=override_value
            discarded_rate = layer_rates.get(prior_value)
            retained_rate = _aggregate_retained_rate(layer_rates, min_size=override_value)

            if discarded_rate is None or retained_rate is None:
                skipped_insufficient_obs += 1
                continue

            disc_conf = discarded_rate.get("confirm_rate", 0.0)
            disc_obs = discarded_rate.get("observations", 0)
            ret_conf = retained_rate.get("confirm_rate", 0.0)
            ret_obs = retained_rate.get("observations", 0)

            if disc_obs < AB_MIN_OBS or ret_obs < AB_MIN_OBS:
                skipped_insufficient_obs += 1
                continue

            diff = ret_conf - disc_conf

            if diff >= AB_MARGIN:
                # Discarded layer significantly worse → tighten is better → auto-confirm
                try:
                    confirm_override(
                        override["id"],
                        reason=f"ab_confirmed_diff_{diff:.2f}",
                        _store_root=_store_root,
                    )
                    confirmed += 1
                except Exception:
                    error_records.append(
                        build_error_record(
                            component="knob_ab_eval",
                            operation="confirm_override",
                            error_code="CONFIRM_FAILED",
                            severity="error",
                            recoverable=True,
                            details={"override_id": override.get("id")},
                        )
                    )
            elif diff <= -AB_MARGIN:
                # Discarded layer significantly better → tighten is worse → auto-revert
                try:
                    revert_override(
                        override["id"],
                        reason="ab_reverted",
                        _store_root=_store_root,
                    )
                    reverted += 1
                except Exception:
                    error_records.append(
                        build_error_record(
                            component="knob_ab_eval",
                            operation="revert_override",
                            error_code="REVERT_FAILED",
                            severity="error",
                            recoverable=True,
                            details={"override_id": override.get("id")},
                        )
                    )
            else:
                # Not clear enough → fall back to owner (TTL path in override_sweep)
                skipped_insufficient_obs += 1

        result = {
            "schema_version": "hermes.knob_ab_eval_result.v0",
            "module": "knob_ab_eval",
            "profile": self.profile,
            "ab_confirmed_count": confirmed,
            "ab_reverted_count": reverted,
            "skipped_no_data_count": skipped_no_data,
            "skipped_insufficient_obs_count": skipped_insufficient_obs,
            "error_records": error_records,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

        # Record run
        self.module_root.mkdir(parents=True, exist_ok=True)
        with self.runs_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

        return result

    def status(self) -> dict[str, Any]:
        active_count = 0
        try:
            from plugins.memory.memory_os.knob_overrides import (
                OVERRIDABLE_KNOBS,
                list_active_overrides,
            )
            active = list_active_overrides()
            active_count = len([
                o for o in active
                if OVERRIDABLE_KNOBS.get(str(o.get("knob") or ""), {}).get("ab_metric")
            ])
        except Exception:
            pass
        return {
            "schema_version": "hermes.knob_ab_eval_status.v0",
            "module": "knob_ab_eval",
            "profile": self.profile,
            "ab_eligible_override_count": active_count,
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        return {
            "schema_version": "hermes.knob_ab_eval_doctor.v0",
            "module": "knob_ab_eval",
            "profile": self.profile,
            "status": "ok",
            "findings": findings,
        }


# ── Internal helpers ──────────────────────────────────────────────────────

def _compute_stratified_confirm_rates(
    store: Any,
    *,
    knob_name: str,
) -> dict[int, dict[str, Any]]:
    """Three-table join: triage (cluster_size) → owner_actions (target_id) → group by cluster_size.

    Returns dict[cluster_size -> {"confirm_rate": float, "observations": int}].
    """
    from plugins.memory.memory_os.crystallized import read_candidate_triage

    # 1. Read candidate_triage for promote records with cluster_size
    triage_records = []
    try:
        triage_records = read_candidate_triage(store)
    except Exception:
        pass

    # Build candidate_id -> cluster_size mapping from promote/demote records
    candidate_cluster_map: dict[str, int] = {}
    for rec in triage_records:
        cid = str(rec.get("candidate_id") or "")
        cs = rec.get("cluster_size")
        if cid and isinstance(cs, int) and cs > 0:
            # Keep the largest cluster_size for each candidate
            if cid not in candidate_cluster_map or cs > candidate_cluster_map[cid]:
                candidate_cluster_map[cid] = cs

    if not candidate_cluster_map:
        return {}

    # 2. Read owner_actions for decisions on these candidates
    owner_actions_path = store.roots.memory_os_root / "system" / "owner_actions.jsonl"
    owner_decisions: dict[str, str] = {}  # candidate_id -> decision (confirmed/rejected)
    if owner_actions_path.exists():
        for line in owner_actions_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            target_id = str(rec.get("target_id") or rec.get("candidate_id") or "")
            action = str(rec.get("action") or "").lower()
            if target_id and target_id in candidate_cluster_map:
                if action in ("approve", "confirm", "confirmed"):
                    owner_decisions[target_id] = "confirmed"
                elif action in ("reject", "rejected", "demote"):
                    owner_decisions[target_id] = "rejected"

    # 3. Group by cluster_size, compute confirm rate
    layer_stats: dict[int, dict[str, int]] = defaultdict(lambda: {"confirmed": 0, "rejected": 0})
    for cid, cs in candidate_cluster_map.items():
        decision = owner_decisions.get(cid)
        if decision == "confirmed":
            layer_stats[cs]["confirmed"] += 1
        elif decision == "rejected":
            layer_stats[cs]["rejected"] += 1

    result: dict[int, dict[str, Any]] = {}
    for cs, stats in layer_stats.items():
        total = stats["confirmed"] + stats["rejected"]
        if total > 0:
            result[cs] = {
                "confirm_rate": stats["confirmed"] / total,
                "observations": total,
                "confirmed": stats["confirmed"],
                "rejected": stats["rejected"],
            }
    return result


def _aggregate_retained_rate(
    layer_rates: dict[int, dict[str, Any]],
    min_size: int,
) -> dict[str, Any] | None:
    """Aggregate confirm rate across all layers with size >= min_size."""
    total_confirmed = 0
    total_rejected = 0
    for cs, stats in layer_rates.items():
        if cs >= min_size:
            total_confirmed += stats.get("confirmed", 0)
            total_rejected += stats.get("rejected", 0)
    total = total_confirmed + total_rejected
    if total == 0:
        return None
    return {
        "confirm_rate": total_confirmed / total,
        "observations": total,
        "confirmed": total_confirmed,
        "rejected": total_rejected,
    }
