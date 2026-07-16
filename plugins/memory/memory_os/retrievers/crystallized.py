"""Crystallized memory retriever — approved canonical records."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.crystallized import (
    _parse_markdown_records,
    is_active_crystallized_frontmatter,
)
from plugins.memory.memory_os.recall_types import RecallObject, RecallType

if TYPE_CHECKING:
    from plugins.memory.memory_os.store import MemoryOSStore


def _frontmatter_true(frontmatter: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = frontmatter.get(key)
        if value is True or str(value or "").strip().casefold() in {"true", "yes", "1"}:
            return True
    return False


def _frontmatter_owner_approved_permanent(frontmatter: dict[str, Any]) -> bool:
    approved_by = str(frontmatter.get("approved_by") or "").strip().casefold()
    provisional = _frontmatter_true(frontmatter, "provisional")
    return approved_by == "owner" and not provisional


def _frontmatter_entity_refs(frontmatter: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("entity_refs", "entities"):
        value = frontmatter.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif isinstance(value, str):
            values.extend(value.split(","))
    return sorted({
        " ".join(str(value or "").strip().split())
        for value in values
        if len(" ".join(str(value or "").strip().split())) >= 2
    }, key=lambda value: (value.casefold(), value))


class CrystallizedRetriever:
    """Retrieve active Owner-approved crystallized memory records."""

    @property
    def recall_type(self) -> RecallType:
        return RecallType.CRYSTALLIZED

    def retrieve(
        self,
        store: "MemoryOSStore",
        query: str,
        *,
        top_k: int = 10,
        scope: dict[str, Any] | None = None,
    ) -> list[RecallObject]:
        crystallized_root = store.roots.crystallized_root
        if not crystallized_root.exists():
            return []

        q_words = [word for word in query.lower().split() if len(word) > 1]
        objects: list[RecallObject] = []
        for md_path in sorted(crystallized_root.glob("*.md")):
            try:
                records = _parse_markdown_records(md_path.read_text(encoding="utf-8"))
            except OSError:
                continue
            for frontmatter, body in records:
                if not is_active_crystallized_frontmatter(frontmatter):
                    continue
                record_id = str(frontmatter.get("id") or "").strip()
                if not record_id:
                    continue
                body_lower = body.lower()
                score = 0.5
                if q_words:
                    hits = sum(1 for word in q_words if word in body_lower)
                    score = min(1.0, 0.5 + hits / len(q_words) * 0.5)
                first_para = body.split("\n\n")[0].strip() if body else ""
                kind = str(frontmatter.get("kind") or "").strip()
                owner_approved_permanent = _frontmatter_owner_approved_permanent(frontmatter)
                owner_pinned = owner_approved_permanent and _frontmatter_true(
                    frontmatter, "owner_pinned", "owner_pin",
                )
                safety_rule = owner_approved_permanent and kind.casefold() in {
                    "safety_rule", "security_rule", "boundary", "safety_boundary",
                }
                objects.append(
                    RecallObject(
                        recall_type=RecallType.CRYSTALLIZED.value,
                        content=first_para[:300],
                        score=score,
                        source_ref=f"crystallized:{record_id}",
                        metadata={
                            "kind": kind,
                            "record_id": record_id,
                            "canonical_state": str(frontmatter.get("canonical_state") or "active"),
                            "entity_refs": _frontmatter_entity_refs(frontmatter),
                            "owner_approved_permanent": owner_approved_permanent,
                            "owner_pinned": owner_pinned,
                            "safety_rule": safety_rule,
                        },
                        authority_class="owner_confirmed" if owner_approved_permanent else "session_working",
                        claim_key=str(frontmatter.get("claim_key") or ""),
                    )
                )

        objects.sort(key=lambda obj: (-obj.score, obj.source_ref))
        return objects[:top_k]

    def format_context(
        self,
        objects: list[RecallObject],
        *,
        budget: int = 800,
    ) -> str:
        if not objects:
            return ""
        lines = ["### Crystallized Memory (recall)"]
        for obj in objects:
            kind_tag = f" [{obj.metadata['kind']}]" if obj.metadata.get("kind") else ""
            lines.append(f"-{kind_tag} {obj.content}")
        return "\n".join(lines)
