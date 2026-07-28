"""Tests for recovery marker verification."""

import pytest
from plugins.memory.memory_os.recovery_marker import (
    RecoveryMarker, verify_recovery_marker, validate_recovery_chain
)


class TestRecoveryMarker:
    def test_valid_marker(self):
        marker = RecoveryMarker(task_id="task-1", task_revision=5, task_status="active")
        assert marker.is_valid()
        assert not marker.is_terminal()

    def test_terminal_marker(self):
        marker = RecoveryMarker(task_id="task-1", task_revision=5, task_status="completed")
        assert marker.is_terminal()

    def test_invalid_marker(self):
        marker = RecoveryMarker()
        assert not marker.is_valid()


class TestVerifyRecoveryMarker:
    def test_terminal_resurrected(self):
        marker = RecoveryMarker(task_id="task-1", task_revision=5, task_status="completed")
        result = verify_recovery_marker(marker, "task-1", 6)
        assert not result.verified
        assert result.error == "terminal_task_resurrected"

    def test_lower_revision(self):
        marker = RecoveryMarker(task_id="task-1", task_revision=5, task_status="active")
        result = verify_recovery_marker(marker, "task-1", 3)
        assert not result.verified
        assert result.error == "lower_revision_overwrite"

    def test_same_task_higher_revision(self):
        marker = RecoveryMarker(task_id="task-1", task_revision=5, task_status="active")
        result = verify_recovery_marker(marker, "task-1", 6)
        assert result.verified

    def test_different_task(self):
        marker = RecoveryMarker(task_id="task-1", task_revision=5, task_status="active")
        result = verify_recovery_marker(marker, "task-2", 1)
        assert result.verified

    def test_terminal_marker_does_not_block_a_genuinely_new_task(self):
        marker = RecoveryMarker(task_id="task-1", task_revision=5, task_status="completed")
        result = verify_recovery_marker(marker, "task-2", 1)
        assert result.verified

    def test_invalid_marker_allow(self):
        marker = RecoveryMarker()
        result = verify_recovery_marker(marker, "task-1", 1)
        assert result.verified
        assert "invalid_marker" in result.error


class TestValidateChain:
    def test_valid_chain(self):
        markers = [
            RecoveryMarker(task_id="task-1", task_revision=1, task_status="active"),
            RecoveryMarker(task_id="task-1", task_revision=2, task_status="active"),
            RecoveryMarker(task_id="task-1", task_revision=3, task_status="completed"),
        ]
        results = validate_recovery_chain(markers)
        assert all(r.verified for r in results)

    def test_broken_chain(self):
        markers = [
            RecoveryMarker(task_id="task-1", task_revision=3, task_status="completed"),
            RecoveryMarker(task_id="task-1", task_revision=4, task_status="active"),
        ]
        results = validate_recovery_chain(markers)
        assert not results[0].verified  # terminal resurrected

    def test_chain_may_advance_from_terminal_task_to_new_task(self):
        markers = [
            RecoveryMarker(task_id="task-1", task_revision=3, task_status="completed"),
            RecoveryMarker(task_id="task-2", task_revision=1, task_status="active"),
        ]
        results = validate_recovery_chain(markers)
        assert results[0].verified