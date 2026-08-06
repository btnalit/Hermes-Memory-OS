"""Memory-OS v0 schema definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EVENT_SCHEMA_VERSION = "memory-os.event.v0"
WORKING_SCHEMA_VERSION = "memory-os.working.v1"
WORKING_SCHEMA_VERSION_V0 = "memory-os.working.v0"  # read-compatible
CRYSTALLIZED_SCHEMA_VERSION = "memory-os.crystallized.v0"
IDENTITY_MANIFEST_SCHEMA_VERSION = "memory-os.identity_manifest.v0"
CROSS_PROFILE_VIEW_SCHEMA_VERSION = "memory-os.cross_profile_view.v0"


class ValidationError(ValueError):
    """Raised when a Memory-OS record does not match a supported schema."""


def _require(data: dict[str, Any], field_name: str) -> Any:
    if field_name not in data:
        raise ValidationError(f"Missing required field: {field_name}")
    value = data[field_name]
    if value is None or value == "":
        raise ValidationError(f"Field must not be empty: {field_name}")
    return value


def _require_schema(data: dict[str, Any], expected: str) -> None:
    actual = _require(data, "schema_version")
    if actual != expected:
        raise ValidationError(f"Unsupported schema_version: {actual}")


def _dict_value(data: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = data.get(field_name, {})
    if not isinstance(value, dict):
        raise ValidationError(f"Field must be an object: {field_name}")
    return dict(value)


def _list_value(data: dict[str, Any], field_name: str) -> list[Any]:
    value = data.get(field_name, [])
    if not isinstance(value, list):
        raise ValidationError(f"Field must be a list: {field_name}")
    return list(value)


@dataclass(frozen=True)
class EventEnvelope:
    schema_version: str
    id: str
    ts: str
    profile: str
    source: str
    kind: str
    summary: str
    safe_ref: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    sensitivity: str = "private"
    body_policy: str = "summary_only"
    hashes: dict[str, Any] = field(default_factory=dict)
    # RESERVED: every producer writes "raw" and nothing migrates it — the
    # promotion state machine this field implies was never built. A census
    # test pins that ("raw"-only across all producers); implementing real
    # promotion states means consciously updating producer + census together.
    promotion_state: str = "raw"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope":
        _require_schema(data, EVENT_SCHEMA_VERSION)
        for field_name in ("id", "ts", "profile", "source", "kind", "summary", "sensitivity", "body_policy", "promotion_state"):
            _require(data, field_name)
        return cls(
            schema_version=EVENT_SCHEMA_VERSION,
            id=str(data["id"]),
            ts=str(data["ts"]),
            profile=str(data["profile"]),
            source=str(data["source"]),
            kind=str(data["kind"]),
            summary=str(data["summary"]),
            safe_ref=_dict_value(data, "safe_ref"),
            tags=[str(item) for item in _list_value(data, "tags")],
            sensitivity=str(data["sensitivity"]),
            body_policy=str(data["body_policy"]),
            hashes=_dict_value(data, "hashes"),
            promotion_state=str(data["promotion_state"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "ts": self.ts,
            "profile": self.profile,
            "source": self.source,
            "kind": self.kind,
            "summary": self.summary,
            "safe_ref": dict(self.safe_ref),
            "tags": list(self.tags),
            "sensitivity": self.sensitivity,
            "body_policy": self.body_policy,
            "hashes": dict(self.hashes),
            "promotion_state": self.promotion_state,
        }


@dataclass(frozen=True)
class WorkingItem:
    id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    text: str
    source_event_id: str = ""
    tags: list[str] = field(default_factory=list)
    weight: float = 0.0
    last_decayed_at: str = ""  # v1: last decay calculation timestamp; empty = never decayed
    expired_at: str = ""       # v1: when the item was first marked expired; empty = not expired


@dataclass(frozen=True)
class WorkingDocument:
    schema_version: str
    updated_at: str
    items: list[WorkingItem] = field(default_factory=list)


@dataclass(frozen=True)
class CrystallizedFrontmatter:
    schema_version: str
    id: str
    kind: str
    created_at: str
    approved_by: str
    approved_at: str
    source_event_ids: list[str]
    tags: list[str] = field(default_factory=list)
    sensitivity: str = "private"
    hindsight_indexed: bool = False


@dataclass(frozen=True)
class IdentitySource:
    kind: str
    path: str
    sha256: str = ""
    size: int | None = None
    mtime: str = ""
    owner_controlled: bool = True
    memory_os_writable: bool = False


@dataclass(frozen=True)
class IdentityManifest:
    schema_version: str
    profile: str
    identity_sources: list[IdentitySource]
    last_checked_at: str


@dataclass(frozen=True)
class CrossProfileView:
    schema_version: str
    view_id: str
    producer_profile: str
    consumer_profile: str
    scope: str
    created_at: str
    expires_at: str
    source_refs: list[str]
    body_policy: str
    path: str


class SchemaRegistry:
    """Read/write compatibility registry for Memory-OS schema versions."""

    _current = {
        "event": EVENT_SCHEMA_VERSION,
        "working": WORKING_SCHEMA_VERSION,
        "crystallized": CRYSTALLIZED_SCHEMA_VERSION,
        "identity_manifest": IDENTITY_MANIFEST_SCHEMA_VERSION,
        "cross_profile_view": CROSS_PROFILE_VIEW_SCHEMA_VERSION,
    }

    _read_compatible = {
        kind: {version}
        for kind, version in _current.items()
    }
    _read_compatible["working"] = {WORKING_SCHEMA_VERSION, WORKING_SCHEMA_VERSION_V0}

    def current_write_version(self, kind: str) -> str:
        if kind not in self._current:
            raise ValidationError(f"Unknown schema kind: {kind}")
        return self._current[kind]

    def can_read(self, kind: str, version: str) -> bool:
        return version in self._read_compatible.get(kind, set())
