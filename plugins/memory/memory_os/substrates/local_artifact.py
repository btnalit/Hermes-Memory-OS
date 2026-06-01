"""Local canonical artifact substrate."""

from __future__ import annotations

from typing import Any

from ..crystallized import CrystallizedMemoryService, is_active_crystallized_frontmatter
from .base import GroundingFact, ProviderHealth, SubstrateSnapshot


class LocalArtifactProvider:
    name = "local_artifact"

    def __init__(self, store: Any) -> None:
        self.store = store

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            status="ok",
            capabilities=["recall"],
            substrate_snapshot_id=SubstrateSnapshot(self.name, "canonical", "current").snapshot_id,
        )

    def recall(self, query: str, *, consumer: str) -> list[GroundingFact]:
        terms = {part.casefold() for part in str(query or "").split() if part.strip()}
        facts: list[GroundingFact] = []
        for record in self._iter_records():
            summary = str(record.get("summary") or "")
            if terms and not any(term in summary.casefold() for term in terms):
                continue
            version = str(record.get("version") or "current")
            facts.append(
                GroundingFact(
                    provider=self.name,
                    capability="recall",
                    body_summary=summary,
                    confidence=1.0,
                    provenance="crystallized",
                    source_event_refs=[str(item) for item in record.get("source_event_refs", [])],
                    substrate_snapshot_id=SubstrateSnapshot(self.name, "canonical", version).snapshot_id,
                    consumer=consumer,
                    advisory_only=False,
                    authority_class="local_canonical",
                )
            )
        return facts

    def _iter_records(self) -> list[dict[str, Any]]:
        existing = getattr(self.store, "iter_crystallized_records", None)
        if callable(existing):
            return [dict(record) for record in existing()]
        roots = getattr(self.store, "roots", None)
        if roots is None or not roots.crystallized_root.exists():
            return []
        service = CrystallizedMemoryService(self.store)
        records: list[dict[str, Any]] = []
        for path in sorted(roots.crystallized_root.glob("*.md")):
            for record in service.read_records(path.name):
                if not is_active_crystallized_frontmatter(record.frontmatter):
                    continue
                records.append(
                    {
                        "record_id": str(record.frontmatter.get("id") or ""),
                        "summary": record.body,
                        "source_event_refs": [str(item) for item in record.frontmatter.get("source_event_ids", [])],
                        "state": "crystallized",
                        "owner_approved": bool(record.frontmatter.get("approved_by")),
                        "version": str(record.frontmatter.get("version") or record.frontmatter.get("created_at") or "current"),
                    }
                )
        return records
