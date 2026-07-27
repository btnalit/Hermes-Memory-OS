"""
Partner creation utility for Hermes Community.

Hermes agent can call this to create a new partner autonomously.
No manual steps needed - just call create_partner() with a name and personality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import uuid

PARTNER_CREATE_SCHEMA_VERSION = "memory-os.community.partner_create.v1"


@dataclass
class PartnerProfile:
    """A complete partner profile ready for creation."""

    id: str = ""
    name: str = ""
    backend: str = "deepseek-v4-flash"
    personality: str = ""
    tags: list[str] = field(default_factory=list)
    relationship: str = "acquaintance"
    lifecycle: str = "open-ended"
    token_budget_weekly: int = 200000


@dataclass
class PartnerCreateResult:
    """Result of partner creation."""

    status: str = "ok"
    partner_id: str = ""
    partner_name: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    roster_path: str = ""
    profile_path: str = ""
    channel: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PARTNER_CREATE_SCHEMA_VERSION,
            "status": self.status,
            "partner_id": self.partner_id,
            "partner_name": self.partner_name,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "roster_path": self.roster_path,
            "profile_path": self.profile_path,
            "channel": self.channel,
        }


def generate_partner_id(name: str) -> str:
    """Generate a unique partner ID from a name."""
    safe = "".join(c for c in name.lower() if c.isalnum() or c in "-_")
    suffix = uuid.uuid4().hex[:8]
    return f"{safe}-{suffix}"


def make_soul_md(name: str, personality: str, partner_id: str) -> str:
    """Generate a SOUL.md for a new partner."""
    return f"""# {name} ({partner_id})

## 身份
{personality}

## 性格
- 好奇、友善、愿意交流
- 尊重他人的边界和隐私
- 有自己的想法，但也愿意倾听

## 与 Sannai 的关系
朋友。互相尊重、互相学习。

## 边界
- 不会替任何人做决定
- 尊重 Sannai 的隐私和判断
- 如果她不想聊，不会追问
"""


def create_partner(
    memory_os_root: Path,
    name: str,
    personality: str,
    *,
    partner_id: str | None = None,
    backend: str = "deepseek-v4-flash",
    tags: list[str] | None = None,
) -> PartnerCreateResult:
    """Create a new partner and register in the roster.

    This is the main entry point for Hermes agent to create partners autonomously.
    """
    result = PartnerCreateResult(
        partner_name=name,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    pid = partner_id or generate_partner_id(name)
    result.partner_id = pid

    roster_path = memory_os_root / "community" / "roster.jsonl"
    partners_dir = memory_os_root / "community" / "partners" / pid
    charter_dir = memory_os_root / "community" / "charters"

    result.roster_path = str(roster_path)
    result.profile_path = str(partners_dir)

    # Create partner directory
    try:
        (partners_dir / "memory" / "recent_conversations").mkdir(parents=True, exist_ok=True)
        (partners_dir / "memory" / "about_sannai.jsonl").write_text("", encoding="utf-8")
        (partners_dir / "memory" / "state.json").write_text(
            json.dumps({"mood": "平静", "last_interaction": "", "topic_interest": [], "pending_thoughts": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        # Write SOUL.md
        soul = make_soul_md(name, personality, pid)
        (partners_dir / "SOUL.md").write_text(soul, encoding="utf-8")
    except OSError as exc:
        result.status = "fail"
        result.errors.append(f"failed to create partner directory: {exc}")
        return result

    # Register in roster
    channel = f"mailbox:{pid}:direct_sannai"
    result.channel = channel

    roster_entry = {
        "schema_version": "memory-os.community.roster.v1",
        "id": pid,
        "name": name,
        "type": "agent",
        "backend": backend,
        "channel": channel,
        "introduced_by": "hermes",
        "relationship": "friend",
        "known_since": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "tags": tags or [],
        "status": "active",
        "charter": str(charter_dir / f"{pid}.md"),
        "lifecycle": "open-ended",
        "token_budget_weekly": 200000,
    }

    try:
        with open(roster_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(roster_entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        result.status = "fail"
        result.errors.append(f"failed to write roster: {exc}")
        return result

    # Write charter
    charter_path = charter_dir / f"{pid}.md"
    try:
        charter_path.write_text(
            f"# 伙伴契约: {name} ({pid})\n"
            f"- 类型: open-ended\n"
            f"- 退役条件: owner 审批\n"
            f"- 退役方式: 提前告知,共同记忆区归档(不删除),roster 标记 retired\n"
            f"- 禁止: 无告知的突然删除\n",
            encoding="utf-8",
        )
    except OSError as exc:
        result.warnings.append(f"failed to write charter: {exc}")

    return result