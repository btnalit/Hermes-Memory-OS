"""Tests for the community table (窗台) and interest garden (兴趣花园).

Covers write_to_table/read_table and update_interests/get_interests_summary
round-tripping Chinese content — both modules were added with zero test
coverage and their writes did not specify an explicit encoding.
"""

from pathlib import Path

from plugins.memory.memory_os.community_table import write_to_table, read_table, get_unread_shares
from plugins.memory.memory_os.community_interest_garden import (
    update_interests,
    get_interests_summary,
)


class TestCommunityTable:
    def test_write_and_read_round_trips_chinese_text(self, tmp_path: Path) -> None:
        write_to_table(tmp_path, actor="sannai", actor_name="三奶", text="今天蝴蝶停在叶子上好久")
        entries = read_table(tmp_path)
        assert len(entries) == 1
        assert entries[0]["actor_name"] == "三奶"
        assert entries[0]["text"] == "今天蝴蝶停在叶子上好久"

        raw = (tmp_path / "shared" / "table.jsonl").read_text(encoding="utf-8")
        assert "三奶" in raw
        assert "蝴蝶" in raw

    def test_share_type_and_unread_shares(self, tmp_path: Path) -> None:
        write_to_table(
            tmp_path,
            actor="partner-df1c2405",
            actor_name="流萤",
            text="看到一朵形状奇怪的云",
            share_type="share",
            share_url="https://example.com/cloud.jpg",
        )
        shares = get_unread_shares(tmp_path, last_seen_ts="1970-01-01T00:00:00+00:00")
        assert len(shares) == 1
        assert shares[0]["actor_name"] == "流萤"

    def test_rate_limit_blocks_sixth_entry_in_one_hour(self, tmp_path: Path) -> None:
        for i in range(5):
            write_to_table(tmp_path, actor="sannai", actor_name="三奶", text=f"note {i}")
        try:
            write_to_table(tmp_path, actor="sannai", actor_name="三奶", text="note 5")
            raised = False
        except RuntimeError:
            raised = True
        assert raised


class TestInterestGarden:
    def test_update_interests_round_trips_chinese_topics(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        update_interests(state_path, text="今天看到月亮和云，还有一只蜗牛")
        interests = update_interests(state_path, text="又看到月亮了")

        topics = {entry["topic"] for entry in interests}
        assert "月亮" in topics
        assert "云" in topics
        assert "蜗牛" in topics

        moon_entry = next(entry for entry in interests if entry["topic"] == "月亮")
        assert moon_entry["count"] == 2

        raw = state_path.read_text(encoding="utf-8")
        assert "月亮" in raw

    def test_get_interests_summary_natural_language(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        update_interests(state_path, text="月亮")
        summary = get_interests_summary(state_path)
        assert summary == "最近喜欢聊月亮"
