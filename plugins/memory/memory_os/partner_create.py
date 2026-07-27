"""Safe partner-profile creation for Hermes Community."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from urllib.parse import urlparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .community import RosterEntry, reserve_roster_entry, validate_partner_id, validate_roster
from .jsonl_io import write_json_atomic

PARTNER_CREATE_SCHEMA_VERSION = "memory-os.community.partner_create.v1"
_AUTHORIZED_ACTORS = {"owner", "sannai", "hermes_owner_delegate"}
_KNOWN_PROVIDER_ENDPOINTS = {
    "openai-codex": "chatgpt.com",
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
    "deepseek": "api.deepseek.com",
}


@dataclass
class PartnerProfile:
    id: str = ""
    name: str = ""
    backend: str = ""
    personality: str = ""
    tags: list[str] = field(default_factory=list)
    relationship: str = "acquaintance"
    lifecycle: str = "open-ended"
    token_budget_weekly: int = 200000


@dataclass
class PartnerCreateResult:
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
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "roster_path": self.roster_path,
            "profile_path": self.profile_path,
            "channel": self.channel,
            "created_at": self.created_at,
        }


def generate_partner_id(name: str) -> str:
    """Generate a portable opaque id while keeping a safe ASCII name slug."""

    slug = "".join(char for char in name.casefold() if char.isascii() and char.isalnum())[:24]
    prefix = slug if slug and slug[0].isalpha() else "partner"
    partner_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
    return validate_partner_id(partner_id)


def make_soul_md(name: str, personality: str, partner_id: str) -> str:
    return f"""# {name} ({partner_id})

## 身份
{personality}

## 性格
- 好奇、友善、愿意交流
- 尊重他人的边界和隐私
- 有自己的想法，也愿意倾听

## 与 Sannai 的关系
朋友。互相尊重、互相学习；任何共同历史都通过社区 shared 视图读取。

## 边界
- 不替任何人做决定
- 不直接写入 Sannai 的成熟记忆
- 没有联网、支付或外部发布权限
- 她不想聊时不追问
"""


def _contained(root: Path, child: Path) -> bool:
    resolved_root = root.resolve()
    resolved_child = child.resolve()
    return resolved_child == resolved_root or resolved_root in resolved_child.parents


def _load_backend_identity(config_path: Path) -> tuple[dict[str, str], str]:
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        return {}, f"backend config unavailable: {type(exc).__name__}"
    model = payload.get("model")
    if not isinstance(model, dict):
        return {}, "backend config model section missing"
    provider = str(model.get("provider") or "").strip().casefold()
    model_name = str(model.get("default") or "").strip().casefold()
    base_url = str(model.get("base_url") or "").strip()
    try:
        endpoint = (urlparse(base_url).hostname or "").casefold() if base_url else ""
    except ValueError:
        endpoint = ""
    if not provider or not model_name:
        return {}, "backend config provider/default missing"
    endpoint = endpoint or _KNOWN_PROVIDER_ENDPOINTS.get(provider, "")
    if not endpoint:
        return {}, "backend config canonical endpoint missing"
    return {"provider": provider, "model": model_name, "endpoint": endpoint}, ""


def _heterogeneous_backend(partner: dict[str, str], sannai: dict[str, str]) -> bool:
    if partner["model"] == sannai["model"]:
        return False
    if partner["endpoint"] and partner["endpoint"] == sannai["endpoint"]:
        return False
    if partner["provider"] == sannai["provider"]:
        return False
    return True


def _backend_label(identity: dict[str, str]) -> str:
    endpoint = f"@{identity['endpoint']}" if identity.get("endpoint") else ""
    return f"{identity['provider']}:{identity['model']}{endpoint}"


def _max_active_partners(memory_os_root: Path) -> tuple[int, str]:
    path = memory_os_root / "community" / "budget.yaml"
    if not path.exists():
        return 0, "budget configuration missing"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or not isinstance(data.get("global"), dict):
            return 0, "budget configuration invalid"
        value = int(data["global"]["max_active_partners"])
        if value < 0:
            return 0, "budget configuration invalid"
        return value, ""
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        return 0, "budget configuration invalid"


def create_partner(
    memory_os_root: Path,
    name: str,
    personality: str,
    *,
    partner_id: str | None = None,
    partner_config_path: Path | None = None,
    tags: list[str] | None = None,
    actor: str = "",
) -> PartnerCreateResult:
    """Create one isolated partner profile and append one unique roster row.

    The caller must identify an authorized actor.  This is an explicit tool
    boundary, not an automatic background creation lane.
    """

    result = PartnerCreateResult(
        partner_name=str(name or ""),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    if actor not in _AUTHORIZED_ACTORS:
        result.status = "fail"
        result.errors.append("actor is not authorized to create partners")
        return result
    if not str(name or "").strip() or not str(personality or "").strip():
        result.status = "fail"
        result.errors.append("name and personality are required")
        return result
    root = Path(memory_os_root).resolve()
    if partner_id is None:
        result.status = "fail"
        result.errors.append("partner_id required after Hermes profile creation")
        return result
    pid = partner_id
    try:
        validate_partner_id(pid)
    except ValueError:
        result.status = "fail"
        result.errors.append("invalid partner id")
        return result
    result.partner_id = pid
    if partner_config_path is None:
        result.status = "fail"
        result.errors.append("partner profile config required")
        return result
    active_home = root.parent
    profiles_root = active_home.parent if active_home.parent.name == "profiles" else active_home / "profiles"
    expected_config = (profiles_root / pid / "config.yaml").resolve()
    if Path(partner_config_path).resolve() != expected_config:
        result.status = "fail"
        result.errors.append("partner profile config path does not match partner id")
        return result
    sannai_identity, sannai_error = _load_backend_identity(root.parent / "config.yaml")
    partner_identity, partner_error = _load_backend_identity(Path(partner_config_path))
    if sannai_error or partner_error:
        result.status = "fail"
        result.errors.extend(error for error in (sannai_error, partner_error) if error)
        return result
    if not _heterogeneous_backend(partner_identity, sannai_identity):
        result.status = "fail"
        result.errors.append("partner backend must differ from sannai backend")
        return result
    backend = _backend_label(partner_identity)

    community_root = root / "community"
    roster_path = community_root / "roster.jsonl"
    partners_root = community_root / "partners"
    partners_dir = partners_root / pid
    charter_dir = community_root / "charters"
    charter_path = charter_dir / f"{pid}.md"
    result.roster_path = str(roster_path)
    result.profile_path = str(partners_dir)
    result.channel = f"mailbox:{pid}:direct_sannai"

    if not _contained(partners_root, partners_dir) or not _contained(charter_dir, charter_path):
        result.status = "fail"
        result.errors.append("invalid partner id")
        return result
    if partners_dir.exists():
        result.status = "fail"
        result.errors.append(f"duplicate id: {pid}")
        return result
    roster_errors = validate_roster(roster_path)
    if roster_errors:
        result.status = "fail"
        result.errors.append(f"roster invalid: {roster_errors[0]}")
        return result
    limit, budget_error = _max_active_partners(root)
    if budget_error:
        result.status = "fail"
        result.errors.append(budget_error)
        return result

    partners_root.mkdir(parents=True, exist_ok=True)
    charter_dir.mkdir(parents=True, exist_ok=True)
    staging = partners_root / f".{pid}.{uuid.uuid4().hex}.staging"
    published = False
    try:
        memory_dir = staging / "memory"
        (memory_dir / "recent_conversations").mkdir(parents=True)
        (memory_dir / "about_sannai.jsonl").write_text("", encoding="utf-8")
        write_json_atomic(
            memory_dir / "state.json",
            {
                "mood": "平静",
                "last_interaction": "",
                "last_newspaper_ts": "",
                "topic_interest": [],
                "pending_thoughts": [],
            },
        )
        (staging / "SOUL.md").write_text(make_soul_md(name, personality, pid), encoding="utf-8")
        staging.rename(partners_dir)
        published = True
        charter_path.write_text(
            f"# 伙伴契约: {name} ({pid})\n"
            "- 类型: open-ended\n"
            "- 创建主体: Sannai / Owner / Owner-delegated Hermes\n"
            "- 退役条件: owner 审批\n"
            "- 退役方式: 提前告知、shared 归档（不删除）、roster 状态迁移\n"
            "- 禁止: 无告知删除、直接写入 Sannai 成熟记忆、外部发布/支付\n",
            encoding="utf-8",
        )
    except FileExistsError:
        shutil.rmtree(staging, ignore_errors=True)
        result.status = "fail"
        result.errors.append(f"duplicate id: {pid}")
        return result
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if published:
            shutil.rmtree(partners_dir, ignore_errors=True)
        result.status = "fail"
        result.errors.append(f"failed to create partner profile: {type(exc).__name__}")
        return result

    roster_errors = reserve_roster_entry(
        roster_path,
        RosterEntry(
            id=pid,
            name=str(name).strip(),
            backend=backend,
            channel=result.channel,
            introduced_by=actor,
            relationship="friend",
            known_since=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            tags=list(tags or []),
            charter=str(charter_path),
        ),
        max_active=limit,
    )
    if roster_errors:
        shutil.rmtree(partners_dir, ignore_errors=True)
        try:
            charter_path.unlink()
        except OSError:
            pass
        result.status = "fail"
        result.errors.extend(roster_errors)
        return result

    # Restrict private partner files to the profile owner on POSIX.
    for path in [partners_dir, *partners_dir.rglob("*")]:
        try:
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        except OSError:
            result.warnings.append(f"failed to restrict mode: {path.name}")
    return result
