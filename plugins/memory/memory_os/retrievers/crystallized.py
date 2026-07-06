"""Crystallized memory retriever — approved canonical records."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.recall_types import RecallObject, RecallType

if TYPE_CHECKING:
    from plugins.memory.memory_os.store import MemoryOSStore


class CrystallizedRetriever:
    """Retrieve owner-approved crystallized memory records.

    Scans ``crystallized/*.md`` files and returns entries whose content
    matches the query via simple token overlap.  Does NOT depend on the
    FTS5 index — this is a deterministic filesystem reader.
    """

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

        q_lower = query.lower()
        q_words = [w for w in q_lower.split() if len(w) > 1]

        objects: list[RecallObject] = []
        for md_path in sorted(crystallized_root.glob("*.md")):
            try:
                text = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            body_lower = text.lower()

            # Extract frontmatter kind for metadata
            kind = ""
            for line in text.split("\n"):
                if line.startswith("---"):
                    continue
                if line.startswith("kind:"):
                    kind = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break

            # Score: token overlap ratio
            score = 0.5  # baseline for existing records
            if q_words:
                hits = sum(1 for w in q_words if w in body_lower)
                score = min(1.0, 0.5 + hits / max(len(q_words), 1) * 0.5)

            # Get first meaningful body paragraph
            parts = text.split("---", 2)
            body = parts[-1].strip() if len(parts) >= 3 else text.strip()
            first_para = body.split("\n\n")[0].strip() if body else ""

            objects.append(RecallObject(
                recall_type=RecallType.CRYSTALLIZED.value,
                content=first_para[:300],
                score=score,
                source_ref=f"crystallized:{md_path.stem}",
                metadata={
                    "kind": kind,
                    "file": md_path.name,
                    "size_chars": len(text),
                },
            ))

        objects.sort(key=lambda o: o.score, reverse=True)
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
            lines.append(f"-{kind_tag} {obj.content[:200]}")
        return "\n".join(lines)
