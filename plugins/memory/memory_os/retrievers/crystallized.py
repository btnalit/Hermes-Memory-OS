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
                objects.append(
                    RecallObject(
                        recall_type=RecallType.CRYSTALLIZED.value,
                        content=first_para[:300],
                        score=score,
                        source_ref=f"crystallized:{record_id}",
                        metadata={
                            "kind": str(frontmatter.get("kind") or ""),
                            "record_id": record_id,
                            "canonical_state": str(frontmatter.get("canonical_state") or "active"),
                        },
                        authority_class="owner_confirmed",
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
