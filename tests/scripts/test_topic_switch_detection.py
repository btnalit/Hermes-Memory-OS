"""Test topic switch detection for foreground task anchor.

Verifies that _is_topic_switch correctly detects topic switches
and that _refresh_current_task_anchor_from_query handles them properly
with the >= 2 consecutive rule.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plugins.memory.memory_os.__init__ import (
    MemoryOSProvider,
    _format_current_task_anchor,
    _extract_anchor_current_task,
)


def make_memory_provider() -> MemoryOSProvider:
    """Create a bare MemoryOSProvider with minimum setup needed for test."""
    p = MemoryOSProvider()
    p._current_task_anchor = ""
    p._consecutive_topic_switch_count = 0
    p._foreground_task_only_prefetch = False
    return p


# ── Tests for _is_topic_switch ─────────────────────────────

def test_no_anchor_returns_false():
    """No anchor → no topic switch possible."""
    p = make_memory_provider()
    p._current_task_anchor = ""
    assert p._is_topic_switch("something") is False


def test_same_entities_no_switch():
    """Same key entities → not a topic switch."""
    p = make_memory_provider()
    p._current_task_anchor = _format_current_task_anchor(
        task="Analyzing M003 Canada vs Bosnia devig",
        operations=[],
        session_id="test",
    )
    # New query shares M003 + Canada
    assert p._is_topic_switch("M003 Canada line movement") is False


def test_related_entities_no_switch():
    """Partially overlapping entities → not a topic switch."""
    p = make_memory_provider()
    p._current_task_anchor = _format_current_task_anchor(
        task="Canada vs Bosnia M003 devig-h2h shin",
        operations=[],
        session_id="test",
    )
    # New query shares "Canada" but not "Bosnia" or "M003"
    assert p._is_topic_switch("Canada lineup Davies OUT") is False


def test_completely_different_entities_is_switch():
    """No overlapping entities → topic switch."""
    p = make_memory_provider()
    p._current_task_anchor = _format_current_task_anchor(
        task="Analyzing M003 Canada vs Bosnia match",
        operations=[],
        session_id="test",
    )
    assert p._is_topic_switch("安装 ComfyUI 并渲染视频") is True


def test_chinese_keyword_overlap_not_switch():
    """Shared CJK keyword prevents false topic switch."""
    p = make_memory_provider()
    p._current_task_anchor = _format_current_task_anchor(
        task="继续修 M003 的网关问题",
        operations=[],
        session_id="test",
    )
    # Query shares "网关" CJK keyword with anchor → NOT a topic switch
    assert p._is_topic_switch("网关又报错了") is False


def test_chinese_to_chinese_switch():
    """Chinese-only queries with zero CJK keyword overlap → topic switch."""
    p = make_memory_provider()
    p._current_task_anchor = _format_current_task_anchor(
        task="修 M003 的管线修复问题",
        operations=[],
        session_id="test",
    )
    assert p._is_topic_switch("pytest 测试怎么写") is True


def test_real_conversation_flow():
    """Simulate the exact conversation flow that caused the lag."""
    p = make_memory_provider()
    # Start: M003 analysis task
    p._current_task_anchor = _format_current_task_anchor(
        task="分析 M003 Canada vs Bosnia 全链修复验证，检查 devig/crossbook/consistency/manifest/DR 各 artifact 是否通过",
        operations=[],
        session_id="test",
    )
    assert p._current_task_anchor
    assert p._consecutive_topic_switch_count == 0

    # Q1: User asks about memory system
    # Should detect topic switch (counter goes 0→1), keeps old anchor
    p._refresh_current_task_anchor_from_query("你看看你会话注入了那些记忆")
    assert p._consecutive_topic_switch_count == 1
    # Anchor should still contain M003 reference (not replaced)
    assert "M003" in p._current_task_anchor
    assert not p._foreground_task_only_prefetch

    # Q2: User confirms memory is normal (still on memory topic)
    # Second consecutive zero-overlap → counter 1→2, anchor cleared
    p._refresh_current_task_anchor_from_query("不用了，我要确认正常的")
    assert p._consecutive_topic_switch_count == 0  # reset after clear
    assert p._current_task_anchor == ""  # cleared!


def test_single_off_topic_question_does_not_clear():
    """One off-topic question followed by back-to-topic → counter resets."""
    p = make_memory_provider()
    p._current_task_anchor = _format_current_task_anchor(
        task="M003 Canada vs Bosnia devig-h2h analysis",
        operations=[],
        session_id="test",
    )

    # Q1: Off-topic question
    p._refresh_current_task_anchor_from_query("今天天气怎么样")
    assert p._consecutive_topic_switch_count == 1
    assert "M003" in p._current_task_anchor  # still preserved

    # Q2: Back to M003 topic
    p._refresh_current_task_anchor_from_query("Canada offside line 是多少")
    assert p._consecutive_topic_switch_count == 0  # reset
    # Anchor should be replaced with new query
    assert "M003" not in p._current_task_anchor  # replaced by new task


def test_non_switch_query_resets_counter():
    """A query that IS related to the anchor resets the counter to 0."""
    p = make_memory_provider()
    p._current_task_anchor = _format_current_task_anchor(
        task="修 M003 管线问题",
        operations=[],
        session_id="test",
    )
    p._consecutive_topic_switch_count = 1  # simulate one prior switch

    # Now user says something relevant
    p._refresh_current_task_anchor_from_query("M003 devig 结果看了吗")
    assert p._consecutive_topic_switch_count == 0  # reset


# ── Helpers ────────────────────────────────────────────────

def run_tests():
    """Run all test_* functions, print pass/fail."""
    import traceback
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✅ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*40}")
    print(f"  {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
