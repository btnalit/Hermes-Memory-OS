"""Manifest and compatibility contracts for portable Hermes modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ManifestValidationError(ValueError):
    """Raised when a module manifest is missing required contract fields."""


@dataclass(frozen=True)
class CompatibilityReport:
    status: str
    reasons: tuple[str, ...] = ()
    read_only_schema_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleManifest:
    name: str
    kind: str
    version: str
    layer: str
    required_dependencies: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    commands: tuple[str, ...]
    schedules: tuple[str, ...]
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    default_enabled: bool
    default_delivery_mode: str
    profile_scope: str
    memory_os_min_version: str
    memory_os_max_version: str
    schema_versions: dict[str, tuple[str, ...]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleManifest":
        for section in ("name", "kind", "version", "layer", "dependencies", "provides", "defaults", "memory_os_compat"):
            if section not in data:
                raise ManifestValidationError(f"Missing required manifest section: {section}")

        dependencies = _dict(data, "dependencies")
        provides = _dict(data, "provides")
        defaults = _dict(data, "defaults")
        compat = _dict(data, "memory_os_compat")
        schema_versions = _dict(compat, "schema_versions")

        return cls(
            name=_string(data, "name"),
            kind=_string(data, "kind"),
            version=_string(data, "version"),
            layer=_string(data, "layer"),
            required_dependencies=_strings(dependencies.get("required", [])),
            optional_dependencies=_strings(dependencies.get("optional", [])),
            commands=_strings(provides.get("commands", [])),
            schedules=_strings(provides.get("schedules", [])),
            reads=_strings(provides.get("reads", [])),
            writes=_strings(provides.get("writes", [])),
            default_enabled=bool(defaults.get("enabled", False)),
            default_delivery_mode=str(defaults.get("delivery_mode", "no-send")),
            profile_scope=str(defaults.get("profile_scope", "per-profile")),
            memory_os_min_version=_string(compat, "min_version"),
            memory_os_max_version=_string(compat, "max_version"),
            schema_versions={str(kind): _strings(versions) for kind, versions in schema_versions.items()},
        )

    def can_read_schema(self, kind: str, schema_version: str) -> bool:
        return schema_version in self.schema_versions.get(kind, ())

    def compatibility_report(
        self,
        *,
        memory_os_version: str,
        schema_versions: dict[str, str],
    ) -> CompatibilityReport:
        if not _version_in_range(memory_os_version, self.memory_os_min_version, self.memory_os_max_version):
            return CompatibilityReport(
                status="incompatible",
                reasons=(f"memory_os_version {memory_os_version} outside {self.memory_os_min_version}..{self.memory_os_max_version}",),
            )

        unknown = tuple(
            kind
            for kind, version in sorted(schema_versions.items())
            if kind in self.schema_versions and not self.can_read_schema(kind, version)
        )
        if unknown:
            return CompatibilityReport(status="read_only_unknown_schema", read_only_schema_kinds=unknown)

        return CompatibilityReport(status="compatible")


def _dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ManifestValidationError(f"Manifest field must be an object: {key}")
    return dict(value)


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if value is None or value == "":
        raise ManifestValidationError(f"Missing required manifest field: {key}")
    return str(value)


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ManifestValidationError("Manifest field must be a list")
    return tuple(str(item) for item in value)


def _version_in_range(version: str, minimum: str, maximum: str) -> bool:
    parsed = _parse_version(version)
    return parsed >= _parse_version(minimum) and _matches_max(parsed, maximum)


def _parse_version(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3:
        raise ManifestValidationError(f"Version must be major.minor.patch: {version}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _matches_max(version: tuple[int, int, int], maximum: str) -> bool:
    parts = maximum.split(".")
    if len(parts) != 3:
        raise ManifestValidationError(f"Version must be major.minor.patch: {maximum}")
    for actual, expected in zip(version, parts, strict=True):
        if expected == "x":
            return True
        expected_int = int(expected)
        if actual < expected_int:
            return True
        if actual > expected_int:
            return False
    return True
