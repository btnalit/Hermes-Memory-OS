#!/usr/bin/env python3
"""Memory-OS index sync helper (no_agent).

Calls sync_from_store to bring the SQLite FTS5 index up to date
with canonical filesystem store. Non-authoritative cache — fail-open.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERMES_HOME = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
REPO_ROOT = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.index import MemoryOSIndex, _markdown_records
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.crystallized import is_active_crystallized_frontmatter, read_candidate_queue


def _canonical_counts(store: MemoryOSStore) -> dict[str, int]:
    """Count canonical filesystem records for drift comparison.

    Counting methodology MUST match the index's semantics, not raw filesystem
    counts. Three deliberate choices:

    1. **events**: counted via JSONL parse (same parser as ``_index_events``)
       so malformed/unparseable lines are excluded, without triggering
       quarantine side effects from ``store.read_events()``.
    2. **working_items**: counted per *item* inside each ``<kind>.json``
       document (index stores one row per item), not per .json file.
    3. **crystallized_candidates**: counted by *distinct* candidate_id
       (index uses INSERT OR REPLACE with candidate_id as primary key).
    4. **crystallized_records**: uses the same ``_markdown_records`` +
       ``is_active_crystallized_frontmatter`` pipeline as ``_index_crystallized_records``.
    5. **audit_entries**: snapshot taken BEFORE sync so the index_sync
       process's own ``append_audit`` call is not counted against it
       (caller must count this BEFORE running sync/rebuild).
    """
    roots = store.roots
    event_lines = 0
    for path in sorted(roots.events_root.glob("*/*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "id" in obj:
                    event_lines += 1
            except json.JSONDecodeError:
                pass  # malformed → not indexed, exclude from canonical
    # Count items inside working-memory JSON documents, not files.
    working = 0
    for path in sorted(roots.working_root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            working += len(doc.get("items", []))
        except (json.JSONDecodeError, OSError):
            pass
    # Count distinct candidate_ids to match index's PRIMARY KEY dedup.
    candidate_ids: set[str] = set()
    for c in read_candidate_queue(roots):
        candidate_ids.add(c.candidate_id)
    candidates = len(candidate_ids)
    crystallized = 0
    for path in sorted(roots.crystallized_root.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        for frontmatter, _ in _markdown_records(content):
            if is_active_crystallized_frontmatter(frontmatter):
                crystallized += 1
    audit_lines = 0
    if roots.audit_path.exists():
        audit_lines = len([l for l in roots.audit_path.read_text(encoding="utf-8").splitlines() if l.strip()])
    return {
        "events": event_lines,
        "working_items": working,
        "crystallized_candidates": candidates,
        "crystallized_records": crystallized,
        "audit_entries": audit_lines,
    }


def _drift_report(index: dict[str, int], canonical: dict[str, int]) -> dict[str, dict[str, int]]:
    """Compare index counts to canonical; return per-table drift detail."""
    drifts: dict[str, dict[str, int]] = {}
    for table in ("events", "working_items", "crystallized_candidates", "crystallized_records", "audit_entries"):
        i = index.get(table, 0)
        c = canonical.get(table, 0)
        diff = abs(i - c)
        if diff > 0:
            drifts[table] = {"index": i, "canonical": c, "diff": diff}
    return drifts


def main() -> int:
    hermes_home = os.environ.get("HERMES_HOME", "")
    profile = os.environ.get("HERMES_PROFILE", "default")

    if not hermes_home:
        hermes_home = str(Path.home() / ".hermes")

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()

    index = MemoryOSIndex(roots)
    # E1: cron path must set embedder, else index-time embeddings are skipped
    # and vector search silently degrades to FTS5 (provider path sets it at
    # MemoryOSProvider.prefetch via self._index._embedder = self._embedder).
    try:
        from plugins.memory.memory_os.embedder import build_embedder

        _embedder = build_embedder(roots, batch=True)
        if _embedder is not None:
            index._embedder = _embedder
    except Exception:
        pass  # graceful degrade: embedder unavailable -> keep FTS5 floor
    now = datetime.now(timezone.utc)

    # Snapshot canonical counts BEFORE sync/rebuild so that the
    # index_sync process's own audit entry is not counted against it.
    canonical = _canonical_counts(store)

    if not roots.index_path.exists():
        # First-use: full rebuild
        ok = index.try_rebuild_from_store(store)
        counts = index.counts()
        status = "ok" if ok else "error"
    else:
        # Incremental sync (events true-incr, others clear+reload)
        try:
            counts = index.sync_from_store(store)
            status = "ok"
        except Exception as exc:
            counts = index.counts()
            status = "error"

    # Drift check: index vs canonical filesystem
    drifts = _drift_report(counts, canonical)
    drift_ok = len(drifts) == 0

    summary = {
        "tick": now.isoformat().replace("+00:00", "Z"),
        "status": status,
        "counts": counts,
        "canonical_counts": canonical,
        "drift": drifts,
        "drift_ok": drift_ok,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
