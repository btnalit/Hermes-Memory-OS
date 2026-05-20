"""Install/enable/disable/status/doctor scaffold for portable Hermes modules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bus import ModuleBus
from .contracts import ModuleManifest


class LifecycleError(RuntimeError):
    """Raised when a module lifecycle operation is unsafe or invalid."""


@dataclass(frozen=True)
class ModuleStatus:
    name: str
    installed: bool
    enabled: bool
    profile: str
    version: str = ""
    kind: str = ""
    layer: str = ""
    delivery_mode: str = "no-send"
    required_dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.module_status.v0",
            "name": self.name,
            "installed": self.installed,
            "enabled": self.enabled,
            "profile": self.profile,
            "version": self.version,
            "kind": self.kind,
            "layer": self.layer,
            "delivery_mode": self.delivery_mode,
            "required_dependencies": list(self.required_dependencies),
        }


@dataclass(frozen=True)
class DoctorReport:
    module: str
    status: str
    findings: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.module_doctor.v0",
            "module": self.module,
            "status": self.status,
            "findings": [dict(finding) for finding in self.findings],
        }


class ModuleLifecycle:
    """Profile-local lifecycle registry for module manifests."""

    def __init__(
        self,
        hermes_home: str | Path,
        *,
        profile: str,
        available_dependencies: tuple[str, ...] | list[str] = (),
        memory_os_version: str = "0.1.0",
        schema_versions: dict[str, str] | None = None,
    ) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile
        self.available_dependencies = {str(dep) for dep in available_dependencies}
        self.memory_os_version = memory_os_version
        self.schema_versions = schema_versions or {
            "event": "memory-os.event.v0",
            "working": "memory-os.working.v0",
            "crystallized": "memory-os.crystallized.v0",
        }
        self.root = self.hermes_home / "system-modules"
        self.bus = ModuleBus(self.root / "module_bus.jsonl")

    def install(self, raw_manifest: dict[str, Any]) -> ModuleStatus:
        manifest = ModuleManifest.from_dict(raw_manifest)
        self._manifest_path(manifest.name).parent.mkdir(parents=True, exist_ok=True)
        self._write_json(self._manifest_path(manifest.name), raw_manifest)
        self.bus.publish(
            "module.discovered",
            profile=self.profile,
            module=manifest.name,
            payload={"version": manifest.version, "kind": manifest.kind, "layer": manifest.layer},
        )
        return self.status(manifest.name)

    def enable(self, name: str, *, delivery_mode: str | None = None, allow_send: bool = False) -> ModuleStatus:
        manifest = self._load_manifest(name)
        selected_delivery = delivery_mode or manifest.default_delivery_mode
        if selected_delivery == "send" and not allow_send:
            raise LifecycleError("send delivery requires explicit allow_send=True")

        findings = self._doctor_findings(manifest, delivery_mode=selected_delivery)
        errors = [finding for finding in findings if finding["severity"] == "error"]
        if errors:
            raise LifecycleError("; ".join(str(error["message"]) for error in errors))

        self._write_state(manifest, enabled=True, delivery_mode=selected_delivery)
        self.bus.publish(
            "module.health_changed",
            profile=self.profile,
            module=name,
            payload={"state": "enabled", "delivery_mode": selected_delivery},
        )
        return self.status(name)

    def disable(self, name: str) -> ModuleStatus:
        manifest = self._load_manifest(name)
        current = self._read_state(name)
        self._write_state(
            manifest,
            enabled=False,
            delivery_mode=str(current.get("delivery_mode", manifest.default_delivery_mode)),
        )
        self.bus.publish(
            "module.health_changed",
            profile=self.profile,
            module=name,
            payload={"state": "disabled"},
        )
        return self.status(name)

    def status(self, name: str) -> ModuleStatus:
        path = self._manifest_path(name)
        if not path.exists():
            return ModuleStatus(name=name, installed=False, enabled=False, profile=self.profile)
        manifest = self._load_manifest(name)
        state = self._read_state(name)
        return ModuleStatus(
            name=manifest.name,
            installed=True,
            enabled=bool(state.get("enabled", manifest.default_enabled)),
            profile=self.profile,
            version=manifest.version,
            kind=manifest.kind,
            layer=manifest.layer,
            delivery_mode=str(state.get("delivery_mode", manifest.default_delivery_mode)),
            required_dependencies=manifest.required_dependencies,
        )

    def doctor(self, name: str) -> DoctorReport:
        if not self._manifest_path(name).exists():
            return DoctorReport(
                module=name,
                status="error",
                findings=(
                    {
                        "severity": "error",
                        "code": "module_not_installed",
                        "message": f"Module is not installed: {name}",
                    },
                ),
            )
        manifest = self._load_manifest(name)
        findings = self._doctor_findings(manifest, delivery_mode=self.status(name).delivery_mode)
        status = "error" if any(finding["severity"] == "error" for finding in findings) else "ok"
        return DoctorReport(module=name, status=status, findings=tuple(findings))

    def _doctor_findings(self, manifest: ModuleManifest, *, delivery_mode: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for dependency in manifest.required_dependencies:
            dependency_name = dependency.split()[0]
            if dependency_name not in self.available_dependencies:
                findings.append(
                    {
                        "severity": "error",
                        "code": "missing_required_dependency",
                        "message": f"Missing required dependency: {dependency_name}",
                    }
                )

        compatibility = manifest.compatibility_report(
            memory_os_version=self.memory_os_version,
            schema_versions=self.schema_versions,
        )
        if compatibility.status == "incompatible":
            findings.append(
                {
                    "severity": "error",
                    "code": "memory_os_incompatible",
                    "message": "; ".join(compatibility.reasons),
                }
            )
        elif compatibility.status == "read_only_unknown_schema":
            findings.append(
                {
                    "severity": "warning",
                    "code": "memory_os_schema_read_only",
                    "message": "Unknown readable schema versions: "
                    + ", ".join(compatibility.read_only_schema_kinds),
                }
            )

        if delivery_mode == "send":
            findings.append(
                {
                    "severity": "error",
                    "code": "delivery_send_enabled",
                    "message": "Real send delivery is disabled by default in v0.1",
                }
            )
        return findings

    def _load_manifest(self, name: str) -> ModuleManifest:
        path = self._manifest_path(name)
        if not path.exists():
            raise LifecycleError(f"Module is not installed: {name}")
        return ModuleManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _manifest_path(self, name: str) -> Path:
        return self.root / "installed" / f"{name}.json"

    def _state_path(self, name: str) -> Path:
        return self.root / "profiles" / self.profile / f"{name}.json"

    def _read_state(self, name: str) -> dict[str, Any]:
        path = self._state_path(name)
        if not path.exists():
            return {}
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return dict(parsed) if isinstance(parsed, dict) else {}

    def _write_state(self, manifest: ModuleManifest, *, enabled: bool, delivery_mode: str) -> None:
        state = {
            "schema_version": "hermes.module_profile_state.v0",
            "name": manifest.name,
            "profile": self.profile,
            "enabled": enabled,
            "delivery_mode": delivery_mode,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json(self._state_path(manifest.name), state)

    @staticmethod
    def _write_json(path: Path, document: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
