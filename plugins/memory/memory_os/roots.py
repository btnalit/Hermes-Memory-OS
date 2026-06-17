"""Profile-local root resolution for Memory-OS."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .schema import IdentitySource


class RootValidationError(ValueError):
    """Raised when a root would break profile-local storage boundaries."""


_STATE_SOURCE_FILES = {
    "diary.md": "state:diary",
    "self_memory.md": "state:self_memory",
    "lingering_thoughts.json": "state:lingering_thoughts",
}


def _contains_traversal(value: str | Path) -> bool:
    return any(part == ".." for part in Path(value).parts)


def _validate_profile(profile: str | None) -> str:
    if not profile:
        return ""
    if _contains_traversal(profile) or "/" in profile or "\\" in profile:
        raise RootValidationError(f"profile contains path traversal: {profile}")
    return profile


def _validate_external_root(path: str | Path) -> Path:
    if _contains_traversal(path):
        raise RootValidationError(f"external_state_roots contains path traversal: {path}")
    return Path(path).expanduser().resolve()


def _source_for(kind: str, path: Path) -> IdentitySource:
    stat = path.stat()
    return IdentitySource(
        kind=kind,
        path=str(path.resolve()),
        size=stat.st_size,
        mtime=str(stat.st_mtime),
        owner_controlled=True,
        memory_os_writable=False,
    )


@dataclass(frozen=True)
class MemoryOSRoots:
    hermes_home: Path
    profile: str
    memory_os_root: Path
    events_root: Path
    working_root: Path
    crystallized_root: Path
    identity_manifest_path: Path
    relationships_root: Path
    index_path: Path
    audit_path: Path
    imports_root: Path
    quarantine_root: Path
    identity_sources: list[IdentitySource] = field(default_factory=list)
    external_state_roots: tuple[Path, ...] = field(default_factory=tuple)

    @classmethod
    def from_profile(cls, profile: str | None = None) -> "MemoryOSRoots":
        """Resolve roots from HERMES_HOME env var with optional profile override.

        Falls back to $HOME/.hermes if HERMES_HOME is not set.
        """
        import os
        hermes_home = os.environ.get("HERMES_HOME")
        if not hermes_home:
            hermes_home = Path.home() / ".hermes"
        return cls.from_hermes_home(hermes_home, profile=profile)

    @classmethod
    def from_hermes_home(
        cls,
        hermes_home: str | Path,
        *,
        profile: str | None = None,
        external_state_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    ) -> "MemoryOSRoots":
        resolved_profile = _validate_profile(profile)
        home = Path(hermes_home).expanduser().resolve()
        memory_os_root = home / "memory-os"
        external_roots = tuple(_validate_external_root(root) for root in (external_state_roots or ()))

        identity_sources: list[IdentitySource] = []
        profile_sources = (
            ("soul", home / "SOUL.md"),
            ("memory", home / "memories" / "MEMORY.md"),
            ("user", home / "memories" / "USER.md"),
        )
        for kind, path in profile_sources:
            if path.exists():
                identity_sources.append(_source_for(kind, path))

        for root in external_roots:
            for file_name, kind in _STATE_SOURCE_FILES.items():
                path = root / file_name
                if path.exists():
                    identity_sources.append(_source_for(kind, path))

        return cls(
            hermes_home=home,
            profile=resolved_profile,
            memory_os_root=memory_os_root,
            events_root=memory_os_root / "events",
            working_root=memory_os_root / "working",
            crystallized_root=memory_os_root / "crystallized",
            identity_manifest_path=memory_os_root / "identity" / "manifest.json",
            relationships_root=memory_os_root / "relationships",
            index_path=memory_os_root / "index" / "memory_os.db",
            audit_path=memory_os_root / "audit" / "write_audit.jsonl",
            imports_root=memory_os_root / "imports",
            quarantine_root=memory_os_root / "quarantine",
            identity_sources=identity_sources,
            external_state_roots=external_roots,
        )
