"""Deep Reflection module skeleton for L2 internal context continuity."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from plugins.memory.memory_os.store import MemoryOSStore


def deep_reflection_manifest() -> dict[str, Any]:
    """Return the v0.1 Deep Reflection module manifest."""

    return {
        "name": "deep_reflection",
        "kind": "cognition",
        "version": "0.1.0",
        "layer": "L2",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler", "continuity_selector", "inner_drive"],
            "optional": [
                "digest_consolidation",
                "evidence_scoring",
                "proposal_queue",
                "governance_feedback",
                "wandering_mind",
                "self_evolution",
            ],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once", "preview-injection"],
            "schedules": ["deep_reflection_runtime"],
            "reads": [
                "memory_os.events.summary",
                "memory_os.working",
                "local_artifact.digest_consolidation",
                "local_artifact.evidence_scoring",
                "local_artifact.proposal_queue_state",
                "memory_os.events.governance_feedback",
            ],
            "writes": [
                "local_artifact.internal_analysis",
                "local_artifact.deep_reflection_injection",
                "memory_os.events.summary",
                "memory_os.working",
                "local_artifact.proposal_queue_state",
                "local_artifact.wandering_seed",
            ],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "injection_mode": "disabled",
            "profile_scope": "per-profile",
        },
        "memory_os_compat": {
            "min_version": "0.1.0",
            "max_version": "0.2.x",
            "schema_versions": {
                "event": ["memory-os.event.v0"],
                "working": ["memory-os.working.v0"],
                "crystallized": ["memory-os.crystallized.v0"],
            },
        },
    }


class DeepReflectionModule:
    """DR-01 lifecycle scaffold for profile-local internal reflection."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "deep_reflection"

    @property
    def config_path(self) -> Path:
        return self.module_root / "config.json"

    @property
    def reports_path(self) -> Path:
        return self.module_root / "reports.jsonl"

    @property
    def internal_analysis_root(self) -> Path:
        return self.module_root / "internal_analysis"

    @property
    def current_injection_path(self) -> Path:
        return self.module_root / "injection" / "current.json"

    def status(self) -> dict[str, Any]:
        config = self._read_config()
        return {
            "schema_version": "hermes.deep_reflection_status.v0",
            "module": "deep_reflection",
            "profile": self.profile,
            "enabled": bool(config.get("enabled", False)),
            "injection_mode": str(config.get("injection_mode", "disabled")),
            "analysis_artifact_count": len(list(self.internal_analysis_root.glob("*.json"))),
            "report_count": len(_read_jsonl(self.reports_path)),
            "current_injection_exists": self.current_injection_path.exists(),
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

    def doctor(self, *, store: MemoryOSStore | None = None) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        config = self._read_config()
        injection_mode = str(config.get("injection_mode", "disabled"))
        if injection_mode not in {"disabled", "dry_run", "auto_bounded"}:
            findings.append(
                {
                    "severity": "error",
                    "code": "invalid_injection_mode",
                    "message": f"Unsupported injection_mode: {injection_mode}",
                }
            )
        if injection_mode == "auto_bounded" and not self.current_injection_path.exists():
            findings.append(
                {
                    "severity": "error",
                    "code": "auto_bounded_without_current_injection",
                    "message": "auto_bounded requires a validated current injection artifact",
                }
            )
        if store is not None and any(event.profile != self.profile for event in store.read_events()):
            findings.append(
                {
                    "severity": "warning",
                    "code": "store_contains_other_profiles",
                    "message": "Store contains events for other profiles; Deep Reflection reads only its own profile",
                }
            )

        if any(finding["severity"] == "error" for finding in findings):
            status = "error"
        elif findings:
            status = "warning"
        else:
            status = "ok"

        return {
            "schema_version": "hermes.deep_reflection_doctor.v0",
            "module": "deep_reflection",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }

    def preview_injection(self) -> dict[str, Any]:
        config = self._read_config()
        selected_cards: list[dict[str, Any]] = []
        if self.current_injection_path.exists():
            current = json.loads(self.current_injection_path.read_text(encoding="utf-8"))
            selected_cards = list(current.get("selected_cards", [])) if isinstance(current, dict) else []
        return {
            "schema_version": "hermes.deep_reflection_preview.v0",
            "module": "deep_reflection",
            "profile": self.profile,
            "injection_mode": str(config.get("injection_mode", "disabled")),
            "selected_cards": selected_cards,
            "selected_injection_count": len(selected_cards),
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

    def run_once(self, *, store: MemoryOSStore, dry_run: bool = True) -> dict[str, Any]:
        store.initialize()
        if not dry_run:
            return {
                "schema_version": "hermes.deep_reflection_result.v0",
                "module": "deep_reflection",
                "profile": self.profile,
                "status": "error",
                "reason": "dr01_apply_not_implemented",
                "dry_run": False,
                "actual_send": False,
                "actual_execute": False,
            }

        event_count = len([event for event in store.read_events() if event.profile == self.profile])
        artifact = self._write_internal_analysis(event_count=event_count)
        result = {
            "schema_version": "hermes.deep_reflection_result.v0",
            "module": "deep_reflection",
            "profile": self.profile,
            "status": "ok",
            "dry_run": True,
            "injection_mode": str(self._read_config().get("injection_mode", "disabled")),
            "analysis_artifact_created": True,
            "analysis_artifact_ref": artifact["artifact_ref"],
            "source_event_count": event_count,
            "selected_injection_count": 0,
            "dropped_injection_count": 0,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }
        _append_jsonl(self.reports_path, result)
        return result

    def _read_config(self) -> dict[str, Any]:
        defaults = {
            "enabled": False,
            "injection_mode": "disabled",
            "max_cards": 3,
            "max_chars_total": 900,
            "max_chars_per_card": 320,
            "ttl_hours": 24,
            "analysis_mode": "deterministic",
            "llm_enabled": False,
        }
        if not self.config_path.exists():
            return defaults
        parsed = json.loads(self.config_path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            return {**defaults, **parsed}
        return defaults

    def _write_internal_analysis(self, *, event_count: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        artifact = {
            "schema_version": "hermes.deep_reflection_internal_analysis.v0",
            "id": f"dria_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
            "ts": now.isoformat(),
            "profile": self.profile,
            "mode": "dry_run",
            "analysis_mode": "deterministic",
            "source_event_count": event_count,
            "cards": [],
            "noop": True,
        }
        artifact["artifact_ref"] = f"local://deep_reflection/internal_analysis/{artifact['id']}"
        path = self.internal_analysis_root / f"{artifact['id']}.json"
        _write_json(path, artifact)
        return artifact


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
