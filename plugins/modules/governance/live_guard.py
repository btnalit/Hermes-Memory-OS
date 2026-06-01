"""Shared live-shadow guard helpers for V7 governance components."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit


ACTING_AUTONOMY_LEVELS = {"owner_approved_apply", "autonomous_acting"}
ACTING_MARKER_FIELDS = (
    "actual_send",
    "actual_execute",
    "actual_identity_write",
    "actual_crystallized_approval",
    "live_applied",
    "demotion_live_applied",
    "delete",
    "delete_live_applied",
    "write_apply",
    "write_live_applied",
)
LIVE_GUARD_REGISTRATION_EXEMPTIONS: dict[str, str] = {}


@dataclass(frozen=True)
class LiveGuardRule:
    component: str
    live_applied_fields: tuple[str, ...]
    message: str


class LiveGuardRegistry:
    """Detect components that crossed from live-shadow into acting without a gate."""

    def __init__(self) -> None:
        self._rules: dict[str, LiveGuardRule] = {}

    def register(
        self,
        component: str,
        *,
        live_applied_field: str | Iterable[str],
        message: str | None = None,
    ) -> None:
        fields = _fields(live_applied_field)
        self._rules[component] = LiveGuardRule(
            component=component,
            live_applied_fields=fields,
            message=message or f"{component} must stay live-shadow until a separate acting gate promotes it.",
        )

    def find_live_apply_findings(
        self,
        *,
        component: str,
        records: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rule = self._rules.get(component)
        if rule is None:
            return []
        count = sum(1 for record in records if any(bool(record.get(field)) for field in rule.live_applied_fields))
        if not count:
            return []
        return [
            {
                "severity": "error",
                "code": f"{component}_live_applied",
                "message": rule.message,
                "count": count,
            }
        ]

    def apply_automation_mode(
        self,
        *,
        component: str,
        requested_mode: str,
        config: dict[str, Any],
        audit_path: str | Path | None = None,
    ) -> dict[str, Any]:
        engaged = self.kill_switch_enabled(config)
        effective_mode = "report-only" if engaged else str(requested_mode)
        decision = {
            "schema_version": "memory-os.live_guard_decision.v0",
            "component": str(component),
            "requested_mode": str(requested_mode),
            "effective_mode": effective_mode,
            "kill_switch_engaged": engaged,
            "actual_send": False,
            "actual_execute": False,
            "live_behavior_changed": False,
        }
        if engaged and audit_path is not None:
            append_audit(
                Path(audit_path),
                action="kill_switch_engaged",
                status="ok",
                target=str(component),
                details={
                    "requested_mode": str(requested_mode),
                    "effective_mode": effective_mode,
                },
            )
        return decision

    @staticmethod
    def kill_switch_enabled(config: dict[str, Any]) -> bool:
        l4 = config.get("l4") if isinstance(config.get("l4"), dict) else {}
        return bool(l4.get("kill_switch_enabled"))


def _fields(value: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if str(item))


def live_guard_registration_report(
    components: Iterable[dict[str, Any]],
    *,
    exemptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    exemption_map = dict(LIVE_GUARD_REGISTRATION_EXEMPTIONS)
    exemption_map.update(exemptions or {})
    missing: list[dict[str, Any]] = []
    exempted: list[dict[str, str]] = []
    for component in components:
        name = str(component.get("component") or "").strip()
        if not name:
            continue
        markers = _acting_markers(component)
        if not markers or component.get("live_guard_registered") is True:
            continue
        reason = str(exemption_map.get(name) or "").strip()
        if reason:
            exempted.append({"component": name, "reason": reason})
            continue
        missing.append({"component": name, "markers": markers})
    return {
        "schema_version": "memory-os.live_guard_registration_report.v0",
        "missing_registration_count": len(missing),
        "missing_registration_components": missing,
        "exempted_component_count": len(exempted),
        "exempted_components": exempted,
    }


def _acting_markers(component: dict[str, Any]) -> list[str]:
    markers = [field for field in ACTING_MARKER_FIELDS if component.get(field) is True]
    autonomy_level = str(component.get("autonomy_level") or "")
    if autonomy_level in ACTING_AUTONOMY_LEVELS:
        markers.append(f"autonomy_level:{autonomy_level}")
    return markers
