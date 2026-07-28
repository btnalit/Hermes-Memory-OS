"""
Safe recovery marker verification for Memory-OS.

Verifies that the "safe recovery marker" (current task state) is not
overwritten by subsequent updaters after session restoration.  This
prevents a completed/cancelled/superseded task from being resurrected
as the active continuation target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

RECOVERY_MARKER_SCHEMA_VERSION = "memory-os.recovery_marker.v1"


@dataclass
class RecoveryMarker:
    """A safe recovery marker for a task.

    The marker records the task state at the time it was saved as the
    "current task".  Subsequent updaters must not overwrite this marker
    with a stale or completed task.
    """

    task_id: str = ""
    task_revision: int = 0
    task_status: str = ""  # active | completed | cancelled | superseded
    saved_at: str = ""
    session_id: str = ""
    marker_version: int = 1

    def is_valid(self) -> bool:
        return bool(self.task_id) and self.task_revision > 0

    def is_terminal(self) -> bool:
        """A terminal task should not be resurrected as current."""
        return self.task_status in ("completed", "cancelled", "superseded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RECOVERY_MARKER_SCHEMA_VERSION,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_status": self.task_status,
            "saved_at": self.saved_at,
            "session_id": self.session_id,
            "marker_version": self.marker_version,
            "is_valid": self.is_valid(),
            "is_terminal": self.is_terminal(),
        }


@dataclass
class RecoveryMarkerVerification:
    """Result of verifying a recovery marker against a new updater."""

    original_marker: RecoveryMarker
    updater_task_id: str = ""
    updater_revision: int = 0
    verified: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RECOVERY_MARKER_SCHEMA_VERSION,
            "original_task_id": self.original_marker.task_id,
            "original_revision": self.original_marker.task_revision,
            "original_status": self.original_marker.task_status,
            "updater_task_id": self.updater_task_id,
            "updater_revision": self.updater_revision,
            "verified": self.verified,
            "error": self.error,
        }


def verify_recovery_marker(
    marker: RecoveryMarker,
    updater_task_id: str,
    updater_revision: int,
) -> RecoveryMarkerVerification:
    """Verify that an updater does not overwrite a valid recovery marker.

    Rules:
    - If the marker is terminal (completed/cancelled/superseded), the
      updater MUST NOT set it as the current task.
    - If the updater has a lower revision, it MUST NOT overwrite.
    - If the updater is for a different task, it MAY overwrite.
    - If the marker is invalid (empty task_id), the updater MAY proceed.
    """
    result = RecoveryMarkerVerification(
        original_marker=marker,
        updater_task_id=updater_task_id,
        updater_revision=updater_revision,
    )

    if not marker.is_valid():
        result.verified = True
        result.error = "invalid_marker_allow_proceed"
        return result

    if marker.is_terminal() and marker.task_id == updater_task_id:
        result.verified = False
        result.error = "terminal_task_resurrected"
        return result

    if marker.task_id == updater_task_id and updater_revision < marker.task_revision:
        result.verified = False
        result.error = "lower_revision_overwrite"
        return result

    result.verified = True
    return result


def validate_recovery_chain(
    markers: list[RecoveryMarker],
) -> list[RecoveryMarkerVerification]:
    """Validate a chain of recovery markers across sessions.

    Each marker is validated against the next marker in the chain.
    """
    results: list[RecoveryMarkerVerification] = []
    for i in range(len(markers) - 1):
        result = verify_recovery_marker(
            markers[i],
            markers[i + 1].task_id,
            markers[i + 1].task_revision,
        )
        results.append(result)
    return results