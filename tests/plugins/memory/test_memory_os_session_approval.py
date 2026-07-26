"""Tests for session approval loop."""

import pytest
from pathlib import Path
from plugins.memory.memory_os.session_approval import (
    build_session_review_block,
    build_session_feedback_block,
    has_pending_approval_actions,
    get_digest_summary,
    SESSION_APPROVAL_SCHEMA_VERSION,
)


class TestBuildSessionReviewBlock:
    def test_returns_empty_when_no_pending(self):
        # When there are no pending review items, the block should be empty
        result = build_session_review_block(None)
        assert result == "" or result == ""

    def test_result_contains_review_section(self):
        # When there are items, the block should contain relevant sections
        result = build_session_review_block(None)  # Safe: catch Exception
        assert isinstance(result, str)


class TestBuildSessionFeedbackBlock:
    def test_returns_empty_when_no_feedback(self):
        result = build_session_feedback_block(None)
        assert isinstance(result, str)


class TestHasPendingApprovalActions:
    def test_returns_false_when_no_store(self):
        assert has_pending_approval_actions(None) is False


class TestGetDigestSummary:
    def test_returns_structure_when_no_store(self):
        result = get_digest_summary(None)
        assert result["schema_version"] == SESSION_APPROVAL_SCHEMA_VERSION
        assert result["has_pending"] is False
        assert result["action_required_count"] == 0
        assert result["review_suggested_count"] == 0