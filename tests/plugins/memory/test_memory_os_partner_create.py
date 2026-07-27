"""Tests for partner creation."""

from pathlib import Path

from plugins.memory.memory_os.partner_create import (
    create_partner,
    generate_partner_id,
    make_soul_md,
)


def _layout_and_partner_config(tmp_path: Path, partner_id: str) -> tuple[Path, Path]:
    mos_root = tmp_path / "profiles" / "sannai" / "memory-os"
    (mos_root / "community" / "charters").mkdir(parents=True)
    (mos_root / "community" / "roster.jsonl").touch()
    (mos_root / "community" / "budget.yaml").write_text(
        "global:\n  max_active_partners: 2\n", encoding="utf-8"
    )
    mos_root.parent.joinpath("config.yaml").write_text(
        "model:\n  default: sannai-model\n  provider: sannai-provider\n"
        "  base_url: https://sannai.example/v1\n",
        encoding="utf-8",
    )
    partner_config = mos_root.parent.parent / partner_id / "config.yaml"
    partner_config.parent.mkdir(parents=True)
    partner_config.write_text(
        "model:\n  default: partner-model\n  provider: partner-provider\n"
        "  base_url: https://partner.example/v1\n",
        encoding="utf-8",
    )
    return mos_root, partner_config


class TestGeneratePartnerId:
    def test_simple(self) -> None:
        pid = generate_partner_id("阿澜")
        assert pid.startswith("partner-")

    def test_special_chars(self) -> None:
        assert generate_partner_id("Test Friend!").startswith("testfriend-")


class TestMakeSoulMd:
    def test_contains_name(self) -> None:
        soul = make_soul_md("阿澜", "理性、好奇", "alan-001")
        assert all(value in soul for value in ("阿澜", "alan-001", "理性、好奇"))


class TestCreatePartner:
    def test_create_partner(self, tmp_path: Path) -> None:
        mos_root, partner_config = _layout_and_partner_config(tmp_path, "test-001")
        result = create_partner(
            mos_root,
            name="测试伙伴",
            personality="好奇、友善",
            partner_id="test-001",
            tags=["测试"],
            actor="sannai",
            partner_config_path=partner_config,
        )
        assert result.status == "ok"
        assert result.partner_id == "test-001"
        assert "partner-provider:partner-model@partner.example" in (
            mos_root / "community" / "roster.jsonl"
        ).read_text(encoding="utf-8")
        profile = mos_root / "community" / "partners" / "test-001"
        assert (profile / "SOUL.md").exists()
        assert (profile / "memory" / "about_sannai.jsonl").exists()
        assert (profile / "memory" / "state.json").exists()

    def test_duplicate_id(self, tmp_path: Path) -> None:
        mos_root, partner_config = _layout_and_partner_config(tmp_path, "dup-01")
        first = create_partner(
            mos_root, "A", "friendly", partner_id="dup-01", actor="sannai",
            partner_config_path=partner_config,
        )
        assert first.status == "ok"
        second = create_partner(
            mos_root, "B", "curious", partner_id="dup-01", actor="sannai",
            partner_config_path=partner_config,
        )
        assert second.status == "fail"
        assert second.errors == ["duplicate id: dup-01"]
