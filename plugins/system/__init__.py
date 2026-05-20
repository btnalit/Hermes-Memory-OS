"""Portable Hermes system-module contracts."""

from .bus import ModuleBus, ModuleBusEvent
from .contracts import CompatibilityReport, ManifestValidationError, ModuleManifest
from .lifecycle import DoctorReport, LifecycleError, ModuleLifecycle, ModuleStatus
from .scheduler import LockResult, ScheduleCoordinator

__all__ = [
    "CompatibilityReport",
    "DoctorReport",
    "LifecycleError",
    "LockResult",
    "ManifestValidationError",
    "ModuleBus",
    "ModuleBusEvent",
    "ModuleLifecycle",
    "ModuleManifest",
    "ModuleStatus",
    "ScheduleCoordinator",
]
