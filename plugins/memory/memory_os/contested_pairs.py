"""V2-A A0: Contested pairs projection and rebuildable index.

Three-layer authority model (owner ruling #1):
1. Crystallized frontmatter ``contested_refs`` — the authority
2. ``system/contested_pairs.jsonl`` — rebuildable derived index
3. Monitor drift assertion — index count == record scan count
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTESTED_PAIRS_SCHEMA_VERSION = "memory-os.contested_pairs.v0"


def _contested_pairs_path(store: Any) -> Path:
    return store.roots.memory_os_root / "system" / "contested_pairs.jsonl"


def rebuild_contested_pairs_index(store: Any) -> dict[str, Any]:
    """Full scan of crystallized records to rebuild contested_pairs.jsonl.

    Reads every active crystallized record with non-empty ``contested_refs``
    and produces one pair per reference.  This file is ALWAYS a derived
    index — the crystallized frontmatter is the authority.
    """
    from .crystallized import is_active_crystallized_frontmatter

    path = _contested_pairs_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)

    pairs: list[dict[str, Any]] = []
    scanned = 0
    with_contested = 0
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if store.roots.crystallized_root.exists():
        for md_path in sorted(store.roots.crystallized_root.glob("*.md")):
            content = md_path.read_text(encoding="utf-8")
            from .crystallized import _parse_markdown_records
            for fm, _body in _parse_markdown_records(content):
                scanned += 1
                if not is_active_crystallized_frontmatter(fm):
                    continue
                contested_refs = fm.get("contested_refs")
                if not isinstance(contested_refs, list) or not contested_refs:
                    continue
                with_contested += 1
                source_id = str(fm.get("id") or "")
                for target_id in contested_refs:
                    pairs.append({
                        "schema_version": CONTESTED_PAIRS_SCHEMA_VERSION,
                        "source_id": source_id,
                        "target_id": str(target_id),
                        "source_canonical_state": str(fm.get("canonical_state") or "active"),
                        "rebuilt_at": now,
                    })

    # Atomic write: build in memory, write once
    lines = "\n".join(
        json.dumps(pair, ensure_ascii=False, sort_keys=True)
        for pair in pairs
    )
    if lines:
        lines += "\n"
    path.write_text(lines, encoding="utf-8")

    return {
        "status": "ok",
        "pairs_count": len(pairs),
        "records_scanned": scanned,
        "records_with_contested_refs": with_contested,
        "schema_version": CONTESTED_PAIRS_SCHEMA_VERSION,
    }


def read_contested_pairs(store: Any) -> list[dict[str, Any]]:
    """Read the contested pairs index."""
    path = _contested_pairs_path(store)
    if not path.exists():
        return []
    pairs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            pair = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(pair, dict):
            pairs.append(pair)
    return pairs


def count_active_contested_records(store: Any) -> int:
    """Count active crystallized records with non-empty contested_refs."""
    from .crystallized import is_active_crystallized_frontmatter

    count = 0
    if store.roots.crystallized_root.exists():
        for md_path in sorted(store.roots.crystallized_root.glob("*.md")):
            content = md_path.read_text(encoding="utf-8")
            from .crystallized import _parse_markdown_records
            for fm, _body in _parse_markdown_records(content):
                if not is_active_crystallized_frontmatter(fm):
                    continue
                refs = fm.get("contested_refs")
                if isinstance(refs, list) and refs:
                    count += 1
    return count


def contested_pairs_drift_check(store: Any) -> dict[str, Any]:
    """Monitor drift assertion: index count == authority scan count.

    Returns WARN when the derived index has drifted from the authority
    records — caller should trigger rebuild_contested_pairs_index().
    """
    pairs = read_contested_pairs(store)
    authority_count = count_active_contested_records(store)
    # Each authority record may have N refs → N pairs
    # So we count unique source_ids in pairs
    unique_sources = len({p.get("source_id") for p in pairs if p.get("source_id")})

    drift = unique_sources != authority_count
    return {
        "schema_version": "memory-os.contested_pairs_drift.v0",
        "status": "warn" if drift else "ok",
        "drift_detected": drift,
        "index_unique_sources": unique_sources,
        "authority_count": authority_count,
    }
